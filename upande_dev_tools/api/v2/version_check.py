# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
"""Version Check v2 - what version of each app runs on this site, and how it compares.

READ-ONLY. This module only reads stored results (Module Version Check records, the site's
Installed Application rows, and each app's own `__version__`). It never runs a git check,
never saves a record and never commits. Everything the page WRITES (scan bench, scan installed
apps, run / fetch check, create, edit, rename, delete) goes straight to the endpoint the Dev
Dashboard or the Desk form already uses (see `ACTION_ENDPOINTS` in the page script), so
their validation and permission rules are unchanged.

TWO KINDS OF "DIFFERS" (kept apart on purpose):

1. Version: the version recorded for the app on this site (Installed Application.app_version,
   written when the site was last migrated) versus the version in the app's code now
   (`<app>.__version__`). Compared as SEMANTIC versions, not text: 1.10.2 is newer than 1.9.5
   (text order says the opposite), 1.0 equals 1.0.0, and 17.0.0-dev is older than 17.0.0.
   Placeholders such as "17.x.x-develop (273e9f2)" cannot be compared and are reported as
   "can't compare", never as a mismatch.
2. Code: the stored git check (Module Version Check) - commits behind / ahead of the remote,
   uncommitted local changes, no remote branch to compare with.

PRIMARY STATE (one per app, first match wins):
    never_checked  no Module Version Check record for an installed app
    diverged       behind > 0 AND ahead > 0
    behind         behind > 0
    ahead          ahead > 0
    dirty          uncommitted local changes (and in step with the remote)
    no_remote      no upstream branch recorded, so nothing to compare with
    in_sync        none of the above
Groups: differs = behind + ahead + diverged + dirty; cannot_compare = no_remote + never_checked.

IDENTITIES (verified in tests/ and in the report), for the filtered set:
    apps = in_sync + differs + cannot_compare
    differs = behind + ahead + diverged + dirty
    sum(state counts) = apps = len(rows)
    version_same + version_differs + version_unknown = apps
    version_differs = code_newer + code_older
Every figure (KPIs, state counts, charts, checks) follows the filters; the state counts used
by the state selector follow every filter EXCEPT the state itself (so the selector can show
what each choice would give).

The "Data checks" tab and the freshness line are always computed over ALL records (a stale
or duplicated record is a property of the data, not of a filter).

HISTORY: no history is stored. Module Version Check has one row per app that every scan
overwrites, and track_changes is off (Version table has no rows for it), so "how many
differed last week" cannot be known. The API says so (history.available = False) rather than
inventing a trend.

RISK: the record's stored `risk_level` is shown as is (that is what the Desk list and form
show). Two writers set it with different rules (see `risk_by_desk_rule`): the Desk check
(Dirty/Ahead Medium, Stale High or Critical from 10 commits behind, Diverged/Error Critical) and
"Scan bench" (Dirty High, Stale/Ahead Medium). `risk_differs` marks records whose stored risk is
not what the Desk rule gives for the same stored status and commit counts.

PERMISSIONS: same as the current Dev Dashboard endpoint (api/dashboard.get_dashboard_data):
the Dev Team role, and additionally the Dev Portal Page rule of the "dev-dashboard" route that
the page itself follows (portal._route_permits). The response also says what the caller may do
with the DocType (`can`: read / write / create / delete, from frappe.has_permission) so the page
shows the Desk form's controls only to people the Desk would let use them. No secrets are read
(no tokens, no settings).
"""

import re

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, getdate, now_datetime

from upande_dev_tools import portal

ACCESS_ROUTE = "dev-dashboard"
ROLES = {"Dev Team"}
ROW_LIMIT = 500
OLD_CHECK_DAYS = 7

STATE_LABEL = {
	"in_sync": "In step with remote",
	"behind": "Behind remote",
	"ahead": "Ahead of remote",
	"diverged": "Behind and ahead",
	"dirty": "Local changes",
	"no_remote": "No remote to compare",
	"never_checked": "Not checked yet",
}
DIFFERS = ("behind", "ahead", "diverged", "dirty")
CANNOT = ("no_remote", "never_checked")
STATES = ("in_sync", "behind", "ahead", "diverged", "dirty", "no_remote", "never_checked")
DOCTYPE = "Module Version Check"
RISKS = ("Low", "Medium", "High", "Critical")
# Desk list indicator labels, by the stored `status` field (module_version_check_list.js).
# "Diverged", "No Upstream" and "No Git Repo" are valid values that the Desk list shows as
# "Not Checked"; the page names them properly.
RECORDED_LABEL = {
	"Clean": "Clean / Up-to-Date",
	"Stale": "Stale Code",
	"Ahead": "Ahead of Remote",
	"Dirty": "Uncommitted Changes",
	"Diverged": "Diverged",
	"No Upstream": "No Upstream",
	"No Git Repo": "No Git Repo",
	"Error": "Check Failed",
	"": "Not Checked",
}
CRITICAL_BEHIND = 10


def risk_by_desk_rule(status, behind=0):
	"""Risk the Desk check (`module_version_check.get_risk_level`) gives for a stored status:
	Clean Low; Dirty / Ahead Medium; Stale High, or Critical from CRITICAL_BEHIND commits behind;
	Diverged / Error Critical; anything else Medium."""
	if status == "Clean":
		return "Low"
	if status in ("Dirty", "Ahead"):
		return "Medium"
	if status == "Stale":
		return "Critical" if behind >= CRITICAL_BEHIND else "High"
	if status in ("Diverged", "Error"):
		return "Critical"
	return "Medium"


def _require_access():
	roles = set(frappe.get_roles())
	if not (ROLES & roles) or not portal._route_permits("/" + ACCESS_ROUTE, roles):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


# --------------------------------------------------------------------------- versions
_PLACEHOLDER = re.compile(r"(^|[.\-])x([.\-]|$)", re.I)
_PAREN = re.compile(r"\s*\(.*?\)\s*")
_NUM = re.compile(r"^v?(\d+(?:\.\d+)*)(.*)$", re.I)


def parse_version(value):
	"""Return a sortable key for a version string, or None if it cannot be compared.

	key = (numbers padded to 3 parts, 1 if it is a release else 0, pre-release parts)
	so 1.10 > 1.9, 1.0 == 1.0.0, and 1.0.0-dev < 1.0.0 < 1.0.1.
	"""
	s = _PAREN.sub(" ", str(value or "")).strip()
	if not s or _PLACEHOLDER.search(s):
		return None
	m = _NUM.match(s)
	if not m:
		return None
	nums = [int(x) for x in m.group(1).split(".")]
	while len(nums) < 3:
		nums.append(0)
	while len(nums) > 3 and nums[-1] == 0:
		nums.pop()
	rest = m.group(2).split("+", 1)[0].strip(" -.+_")
	if not rest:
		return (tuple(nums), 1, ())
	parts = [p for p in re.split(r"[.\-_]", rest) if p]
	ids = tuple((0, int(p), "") if p.isdigit() else (1, 0, p.lower()) for p in parts)
	return (tuple(nums), 0, ids)


def compare_versions(recorded, code):
	"""'same' | 'code_newer' | 'code_older' | 'unknown' (one side missing or not comparable)."""
	a, b = parse_version(recorded), parse_version(code)
	if a is None or b is None:
		return "unknown"
	if a == b:
		return "same"
	return "code_newer" if b > a else "code_older"


def _code_version(app):
	try:
		return str(getattr(frappe.get_module(app), "__version__", "") or "") or None
	except Exception:
		return None


# --------------------------------------------------------------------------- data
def _installed_rows():
	return frappe.db.sql(
		"""SELECT app_name, app_version, git_branch, modified FROM `tabInstalled Application`
		WHERE parent = 'Installed Applications' AND parenttype = 'Installed Applications'
		ORDER BY idx""",
		as_dict=True,
	)


def _check_rows():
	if not frappe.db.exists("DocType", "Module Version Check"):
		return []
	return frappe.db.sql(
		"""SELECT name, module_name, app_folder, repository_name, repository_url, environment,
			current_commit, current_branch, upstream_branch, status, commits_ahead, commits_behind,
			has_uncommitted_changes, safe_to_deploy, risk_level, last_checked_at, last_checked_by,
			status_message, owner, creation, modified
		FROM `tabModule Version Check` ORDER BY module_name LIMIT 2000""",
		as_dict=True,
	)


def _state(rec):
	if not rec:
		return "never_checked"
	behind, ahead = cint(rec.commits_behind), cint(rec.commits_ahead)
	if behind and ahead:
		return "diverged"
	if behind:
		return "behind"
	if ahead:
		return "ahead"
	if cint(rec.has_uncommitted_changes):
		return "dirty"
	if not (rec.upstream_branch or "").strip():
		return "no_remote"
	return "in_sync"


def _recorded_label_state(rec):
	"""What the stored 'status' text says, in our vocabulary ('' if unknown)."""
	return {
		"clean": "in_sync",
		"stale": "behind",
		"ahead": "ahead",
		"diverged": "diverged",
		"dirty": "dirty",
	}.get((rec.status or "").strip().lower(), "")


def _build_all():
	"""One row per app: installed apps plus any app that only has a stored record."""
	installed = {r.app_name: r for r in _installed_rows()}
	checks = {}
	for r in _check_rows():
		checks.setdefault((r.app_folder or r.module_name or "").strip() or r.name, []).append(r)
	now = now_datetime()
	rows = []
	for app in list(installed) + [a for a in checks if a not in installed]:
		inst = installed.get(app)
		recs = checks.get(app) or []
		# duplicates: newest check wins; the page reports the rest under Data checks
		rec = max(recs, key=lambda x: x.last_checked_at or x.modified, default=None) if recs else None
		code = _code_version(app) if inst else None
		state = _state(rec)
		checked = rec.last_checked_at if rec else None
		age = round((now - get_datetime(checked)).total_seconds() / 86400, 1) if checked else None
		cmp_ = compare_versions(inst.app_version, code) if inst else "unknown"
		label_state = _recorded_label_state(rec) if rec else ""
		stored_risk = (rec.risk_level or "") if rec else ""
		rows.append(
			{
				"app": app,
				"installed": bool(inst),
				"record": rec.name if rec else None,
				"records": len(recs),
				"recorded_version": inst.app_version if inst else None,
				"code_version": code,
				"version_result": cmp_,
				"recorded_branch": inst.git_branch if inst else None,
				"branch": rec.current_branch if rec else None,
				"upstream": rec.upstream_branch if rec else None,
				"ahead": cint(rec.commits_ahead) if rec else 0,
				"behind": cint(rec.commits_behind) if rec else 0,
				"dirty": bool(cint(rec.has_uncommitted_changes)) if rec else False,
				"state": state,
				"state_label": STATE_LABEL[state],
				"stored_status": (rec.status or "") if rec else "",
				"stored_risk": stored_risk,
				"risk_differs": bool(
					rec
					and rec.status
					and stored_risk != risk_by_desk_rule(rec.status, cint(rec.commits_behind))
				),
				"safe_to_deploy": bool(cint(rec.safe_to_deploy)) if rec else False,
				"repository_name": (rec.repository_name or "") if rec else "",
				"environment": (rec.environment or "") if rec else "",
				"created": str(rec.creation) if rec else None,
				"modified": str(rec.modified) if rec else None,
				"owner": (rec.owner or "") if rec else "",
				"commit": (rec.current_commit or "") if rec else "",
				"repo_url": (rec.repository_url or "") if rec else "",
				"message": (rec.status_message or "") if rec else "",
				"last_checked_at": str(checked) if checked else None,
				"last_checked_by": (rec.last_checked_by or "") if rec else "",
				"check_date": str(getdate(checked)) if checked else None,
				"age_days": age,
				"old_check": bool(age is not None and age > OLD_CHECK_DAYS),
				"label_differs": bool(label_state and label_state != state),
				"branch_differs": bool(
					inst
					and rec
					and inst.git_branch
					and rec.current_branch
					and inst.git_branch != rec.current_branch
				),
			}
		)
	return rows, installed


def _args(kw):
	g = lambda k: str(kw.get(k) or "").strip()  # noqa: E731
	f, t = g("from_date"), g("to_date")
	f = getdate(f) if f else None
	t = getdate(t) if t else None
	if f and t and f > t:
		f, t = t, f
	state = g("status")
	version = g("version")
	safe = g("safe")
	return {
		"from_date": str(f) if f else "",
		"to_date": str(t) if t else "",
		"app": g("app"),
		"status": state if state in STATES or state == "differs" else "",
		"version": version if version in ("same", "differs", "unknown", "code_newer", "code_older") else "",
		"q": g("q").lower(),
		"risk": g("risk") if g("risk") in RISKS else "",
		"recorded": g("recorded") if g("recorded") in RECORDED_LABEL else "",
		"safe": safe if safe in ("yes", "no") else "",
	}


def _match(r, a, skip=()):
	if "app" not in skip and a["app"] and r["app"] != a["app"]:
		return False
	if "status" not in skip and a["status"]:
		if a["status"] == "differs":
			if r["state"] not in DIFFERS:
				return False
		elif r["state"] != a["status"]:
			return False
	if "version" not in skip and a["version"]:
		v = r["version_result"]
		if a["version"] == "differs":
			if v not in ("code_newer", "code_older"):
				return False
		elif v != a["version"]:
			return False
	if "risk" not in skip and a["risk"] and r["stored_risk"] != a["risk"]:
		return False
	if "recorded" not in skip and a["recorded"] and r["stored_status"] != a["recorded"]:
		return False
	if (
		"safe" not in skip
		and a["safe"]
		and (r["record"] is None or r["safe_to_deploy"] != (a["safe"] == "yes"))
	):
		return False
	if "date" not in skip and (a["from_date"] or a["to_date"]):
		d = r["check_date"]
		if not d or (a["from_date"] and d < a["from_date"]) or (a["to_date"] and d > a["to_date"]):
			return False
	if "q" not in skip and a["q"]:
		hay = " ".join(
			str(r.get(k) or "")
			for k in (
				"app",
				"branch",
				"upstream",
				"recorded_version",
				"code_version",
				"message",
				"state_label",
				"repository_name",
				"record",
			)
		).lower()
		if a["q"] not in hay:
			return False
	return True


def _data_checks(rows, checks):
	"""Facts about the stored data itself, over ALL records (not filtered)."""
	by_folder, by_lower = {}, {}
	for r in checks:
		by_folder.setdefault((r.app_folder or "").strip(), []).append(r.name)
		by_lower.setdefault((r.module_name or "").strip().lower(), []).append(r.name)
	dup = sorted({n for g in (by_folder, by_lower) for k, v in g.items() if k and len(v) > 1 for n in v})
	apps = lambda f: [r["app"] for r in rows if f(r)]  # noqa: E731
	mismatch_names = sorted(
		r.name for r in checks if (r.app_folder or r.module_name) and r.app_folder != r.module_name
	)

	def item(key, label, hint, names):
		return {"key": key, "label": label, "hint": hint, "count": len(names), "apps": names[:50]}

	return [
		item(
			"duplicates",
			"Apps with more than one record",
			"Records are named after the app, so two records for one app should not exist. When they do, "
			"the newest check is used here.",
			dup,
		),
		item(
			"not_installed",
			"Records for apps not installed on this site",
			"Old records for apps that were removed or never installed here. Safe to ignore; they only add noise.",
			apps(lambda r: not r["installed"]),
		),
		item(
			"never_checked",
			"Installed apps with no stored check",
			"Nothing has been recorded for these yet, so they cannot be compared.",
			apps(lambda r: r["installed"] and not r["record"]),
		),
		item(
			"old_check",
			f"Checks older than {OLD_CHECK_DAYS} days",
			"The stored result may no longer match the code on disk. Run the scan on the Dev Dashboard to refresh.",
			apps(lambda r: r["old_check"]),
		),
		item(
			"no_remote",
			"Apps whose branch tracks no remote",
			"A check was stored but there was no remote branch to compare with, so 'clean' only means no local changes.",
			apps(lambda r: r["state"] == "no_remote"),
		),
		item(
			"label_differs",
			"Stored status label disagrees with the commit counts",
			"For example a record labelled Stale that is also ahead of the remote (behind and ahead). Counts here use the numbers, not the label.",
			apps(lambda r: r["label_differs"]),
		),
		item(
			"no_commit",
			"Checks without a commit recorded",
			"The bench scan does not store the commit id; only the Desk form check does.",
			apps(lambda r: r["record"] and not r["commit"]),
		),
		item(
			"folder_name",
			"Record name and app folder differ",
			"The app folder is what the check reads; a different record name can hide the real app.",
			mismatch_names,
		),
		item(
			"risk_differs",
			"Stored risk differs from the Desk check's rule",
			"Scan bench and the Desk check rate risk differently (for example a Dirty app is High from Scan bench, "
			"Medium from the Desk check). The stored value is shown as is.",
			apps(lambda r: r["risk_differs"]),
		),
		item(
			"version_unknown",
			"Versions that cannot be compared",
			"A placeholder such as 17.x.x-develop, or no version on record.",
			apps(lambda r: r["installed"] and r["version_result"] == "unknown"),
		),
	]


@frappe.whitelist()
def get_version_check(
	from_date=None,
	to_date=None,
	app=None,
	status=None,
	version=None,
	q=None,
	risk=None,
	recorded=None,
	safe=None,
):
	"""Everything the page shows, for the filtered set. Read-only."""
	try:
		_require_access()
		a = _args(
			{
				"from_date": from_date,
				"to_date": to_date,
				"app": app,
				"status": status,
				"version": version,
				"q": q,
				"risk": risk,
				"recorded": recorded,
				"safe": safe,
			}
		)
		rows, _inst = _build_all()
		checks = _check_rows()
		filtered = [r for r in rows if _match(r, a)]
		for_counts = [r for r in rows if _match(r, a, skip=("status",))]
		state_counts = {s: 0 for s in STATES}
		for r in for_counts:
			state_counts[r["state"]] += 1
		counts = {s: 0 for s in STATES}
		ver = {"same": 0, "code_newer": 0, "code_older": 0, "unknown": 0}
		for r in filtered:
			counts[r["state"]] += 1
			ver[r["version_result"]] += 1
		differs = sum(counts[s] for s in DIFFERS)
		cannot = sum(counts[s] for s in CANNOT)
		total = len(filtered)
		truncated = total > ROW_LIMIT
		last = [get_datetime(r.last_checked_at) for r in checks if r.last_checked_at]
		inst_modified = max((i.modified for i in _installed_rows()), default=None)
		behind_rows = sorted((r for r in filtered if r["behind"]), key=lambda r: -r["behind"])
		by_day = {}
		for r in filtered:
			if r["check_date"]:
				by_day[r["check_date"]] = by_day.get(r["check_date"], 0) + 1
		return {
			"success": True,
			"rows": filtered[:ROW_LIMIT],
			"truncated": truncated,
			"row_limit": ROW_LIMIT,
			"totals": {
				"apps": total,
				"in_sync": counts["in_sync"],
				"differs": differs,
				"cannot_compare": cannot,
				"states": counts,
				"version_same": ver["same"],
				"version_differs": ver["code_newer"] + ver["code_older"],
				"version_unknown": ver["unknown"],
				"code_newer": ver["code_newer"],
				"code_older": ver["code_older"],
				"commits_behind": sum(r["behind"] for r in filtered),
				"commits_ahead": sum(r["ahead"] for r in filtered),
				"with_local_changes": sum(1 for r in filtered if r["dirty"]),
			},
			"state_counts": state_counts,
			"state_labels": STATE_LABEL,
			"behind_chart": [{"app": r["app"], "behind": r["behind"]} for r in behind_rows[:15]],
			"checks_by_day": [{"date": d, "apps": n} for d, n in sorted(by_day.items())],
			"options": {
				"apps": sorted(r["app"] for r in rows),
				"risks": list(RISKS),
				"recorded": [{"value": k, "label": v} for k, v in RECORDED_LABEL.items() if k],
			},
			"recorded_labels": RECORDED_LABEL,
			"can": {
				p: bool(frappe.has_permission(DOCTYPE, p)) for p in ("read", "write", "create", "delete")
			},
			"freshness": {
				"records": len(checks),
				"last_checked_at": str(max(last)) if last else None,
				"oldest_checked_at": str(min(last)) if last else None,
				"age_days": round((now_datetime() - max(last)).total_seconds() / 86400, 1) if last else None,
				"old_after_days": OLD_CHECK_DAYS,
				"versions_recorded_at": str(inst_modified) if inst_modified else None,
			},
			"history": {
				"available": False,
				"reason": "Each scan overwrites the single record kept per app and changes are not tracked, "
				"so there is no earlier state to chart.",
			},
			"checks": _data_checks(rows, checks),
		}
	except frappe.PermissionError:
		frappe.local.response["http_status_code"] = 403
		return {"success": False, "error": "You do not have access to Version Check."}
	except Exception:
		frappe.log_error(title="Version Check v2: get_version_check")
		return {"success": False, "error": "Could not load the version check just now. Please retry."}


@frappe.whitelist()
def get_version_check_detail(app=None):
	"""One app in full: both comparisons, the stored message and any recorded changes."""
	try:
		_require_access()
		app = str(app or "").strip()
		if not app:
			return {"success": False, "error": "Choose an app."}
		rows, _inst = _build_all()
		row = next((r for r in rows if r["app"] == app), None)
		if not row:
			return {"success": False, "error": "No app by that name on this site."}
		changes = []
		if row["record"]:
			for v in frappe.db.sql(
				"""SELECT creation, owner, data FROM `tabVersion`
				WHERE ref_doctype = 'Module Version Check' AND docname = %s
				ORDER BY creation DESC LIMIT 20""",
				row["record"],
				as_dict=True,
			):
				try:
					d = frappe.parse_json(v.data) or {}
				except Exception:
					d = {}
				changes.append(
					{
						"when": str(v.creation),
						"by": v.owner,
						"fields": [
							{"field": c[0], "from": c[1], "to": c[2]}
							for c in (d.get("changed") or [])
							if isinstance(c, list) and len(c) >= 3
						][:20],
					}
				)
		return {"success": True, "row": row, "changes": changes}
	except frappe.PermissionError:
		frappe.local.response["http_status_code"] = 403
		return {"success": False, "error": "You do not have access to Version Check."}
	except Exception:
		frappe.log_error(title="Version Check v2: get_version_check_detail")
		return {"success": False, "error": "Could not load this app just now. Please retry."}
