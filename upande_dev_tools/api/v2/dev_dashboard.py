# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
"""Dev Dashboard v2 - bench health and git state (reads only; actions use the existing endpoints).

What the page shows and where each number comes from
----------------------------------------------------
Apps       Read LIVE from git for every app installed on this site (the current page shows
           rows that an earlier "Scan bench" recorded in Module Version Check; those can be
           weeks old and also list apps that are not installed). One `git status
           --porcelain=v2 --branch` per app gives branch, upstream, ahead/behind and the
           working-tree changes; `git log -1` gives the commit date; `git tag --points-at`
           gives an exact tag. Nothing is fetched, so ahead/behind compare with the LAST
           FETCH (the age of that fetch is returned as `fetched_at`). The result is cached
           for CACHE_SECONDS. Only read-only local git commands run (no fetch, no network);
           file names and file contents are never returned (counts only). The repository link
           comes from the local git config (no network) and is stripped of any credentials,
           query string or fragment before it leaves the server.
Drift      Field Difference Log rows that are not "Ignored", counted by issue type.
Deployment Deployment Request rows created in the date range.
Activity   Developer Activity Log rows in the date range; Code Backup Snapshot counts.

Definitions and identities (checked by `tests` and the page's own totals)
    sync state (one per app):  synced | behind | ahead | diverged (ahead AND behind)
                               | no_upstream (no tracking branch, includes a detached HEAD)
    apps = synced + behind + ahead + diverged + no_upstream
    uncommitted = apps whose working tree has changes (tracked or untracked); an
                  independent flag, so it is NOT part of the sum above
    up_to_date  = apps that are synced AND have no uncommitted changes
    needs_attention = apps - up_to_date
    changes = tracked_changes + untracked   (per app)
    deployments = sum(by_state); activity = sum(by_status) = sum(by_type)
All totals are computed over the full filtered set; the row limits only cap the lists and
return `truncated` + the full count.

Permissions: identical to the current endpoint (api.dashboard.get_dashboard_data): the Dev
Team role. The deployment section additionally needs one of DEPLOYMENT_VIEWER_ROLES, as the
current deployments call does (every Dev Team user has it). The `permissions` block only tells
the page which buttons to show; the write endpoints it calls (api.deployments.
create_deployment_request, api.version_control.scan_bench) are the current ones and keep their
own checks.
"""

import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import frappe
from frappe import _
from frappe.utils import add_days, get_bench_path, getdate, now_datetime, nowdate

from upande_dev_tools.api.deployments import DEPLOYER_ROLES, DEPLOYMENT_VIEWER_ROLES

DEV_TEAM_ROLES = {"Dev Team"}
CACHE_KEY = "upande_dev_tools:dev_dashboard_v2:git"
CACHE_SECONDS = 60
MIN_REFRESH_SECONDS = 10
GIT_TIMEOUT = 8
GIT_WORKERS = 6
ROW_LIMIT = 200
RECENT_ERRORS = 5
DESCRIPTION_LIMIT = 5000

_GIT_ENV = {"GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
# Only these (local, read-only) git subcommands are ever run.
_GIT_BASE = ["git", "-c", "core.fsmonitor=false", "--no-optional-locks"]

SYNC_STATES = ("synced", "behind", "ahead", "diverged", "no_upstream")
STATE_FILTERS = (*SYNC_STATES, "uncommitted", "attention", "clean")


def _require_dev_team():
	if not DEV_TEAM_ROLES & set(frappe.get_roles()):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


# --------------------------------------------------------------------------- redaction

_SECRET_KV = re.compile(
	r"(?i)\b(pass(?:word|wd)?|secret|token|api[_-]?key|apikey|authorization|bearer|cookie|sid|private[_-]?key)"
	r"(\s*[:=]\s*|\s+)([^\s,;\"']+)"
)
_URL_CRED = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^\s/@:]+(?::[^\s/@]*)?@")
_BEARER = re.compile(r"(?i)\b(?:bearer|basic)\s+[^\s,;\"']+")
_LONG_TOKEN = re.compile(r"\b[A-Za-z0-9_\-+/=]{32,}\b")


def _like(text):
	return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _redact(text, limit=300, keep_lines=False):
	"""Shorten free text and blank out anything that looks like a credential (line breaks
	are kept when `keep_lines` is set)."""
	if not text:
		return ""
	text = str(text)
	text = _URL_CRED.sub(r"\1[hidden]@", text)
	text = _BEARER.sub("Bearer [hidden]", text)
	text = _SECRET_KV.sub(lambda m: f"{m.group(1)}{m.group(2)}[hidden]", text)
	text = _LONG_TOKEN.sub("[hidden]", text)
	text = (
		"\n".join(" ".join(line.split()) for line in text.splitlines())
		if keep_lines
		else " ".join(text.split())
	)
	return text[: limit - 1] + "…" if len(text) > limit else text


def _clean_repo_url(url):
	"""A browsable https link with no credentials, query or fragment - or None."""
	url = (url or "").strip()
	if not url:
		return None
	if url.startswith("git@") and ":" in url:
		host, _sep, path = url[4:].partition(":")
		url = f"https://{host}/{path}"
	try:
		p = urlparse(url)
	except ValueError:
		return None
	if p.scheme not in ("http", "https") or not p.hostname:
		return None
	host = p.hostname + (f":{p.port}" if p.port else "")
	return f"{p.scheme}://{host}{p.path}".removesuffix(".git").rstrip("/")


# --------------------------------------------------------------------------- live git


def _git(repo, args):
	"""Run one read-only git command; returns stdout or None on any failure/timeout."""
	try:
		out = subprocess.run(
			[*_GIT_BASE, *args],
			cwd=repo,
			capture_output=True,
			text=True,
			timeout=GIT_TIMEOUT,
			env={**os.environ, **_GIT_ENV},
			check=True,
		)
		return out.stdout
	except Exception:
		return None


def _app_repo(app):
	apps_dir = os.path.realpath(os.path.join(get_bench_path(), "apps"))
	repo = os.path.realpath(os.path.join(apps_dir, app))
	if os.path.dirname(repo) != apps_dir or not os.path.exists(os.path.join(repo, ".git")):
		return None
	return repo


def _fetched_at(repo):
	try:
		return time.strftime(
			"%Y-%m-%d %H:%M:%S", time.localtime(os.stat(os.path.join(repo, ".git", "FETCH_HEAD")).st_mtime)
		)
	except OSError:
		return None


def parse_status_v2(text):
	"""Parse `git status --porcelain=v2 --branch` into counts. File names are never kept."""
	out = {"head": None, "oid": None, "upstream": None, "ahead": 0, "behind": 0, "tracked": 0, "untracked": 0}
	for line in (text or "").splitlines():
		if line.startswith("# branch.head "):
			out["head"] = line[14:].strip()
		elif line.startswith("# branch.oid "):
			out["oid"] = line[13:].strip()
		elif line.startswith("# branch.upstream "):
			out["upstream"] = line[18:].strip()
		elif line.startswith("# branch.ab "):
			m = re.match(r"# branch\.ab \+(\d+) -(\d+)", line)
			if m:
				out["ahead"], out["behind"] = int(m.group(1)), int(m.group(2))
		elif line[:2] in ("1 ", "2 ", "u "):
			out["tracked"] += 1
		elif line.startswith("? "):
			out["untracked"] += 1
	return out


def sync_state(has_upstream, ahead, behind):
	if not has_upstream:
		return "no_upstream"
	if ahead and behind:
		return "diverged"
	if behind:
		return "behind"
	if ahead:
		return "ahead"
	return "synced"


def parse_remote_config(text, head):
	"""Pick the repository URL out of `git config --get-regexp` output: the remote the current
	branch tracks, else the first remote. Returns the raw URL (callers must clean it)."""
	urls, tracked = {}, None
	for line in (text or "").splitlines():
		key, _sep, value = line.partition(" ")
		if key.startswith("remote.") and key.endswith(".url"):
			urls.setdefault(key[7:-4], value.strip())
		elif key == f"branch.{head}.remote":
			tracked = value.strip()
	return urls.get(tracked) or next(iter(urls.values()), None)


def _unreadable(app, message):
	"""A row for an app whose git state could not be read: zeroed numbers, no sync state."""
	return {
		"app": app,
		"error": message,
		"sync": None,
		"ahead": 0,
		"behind": 0,
		"tracked_changes": 0,
		"untracked": 0,
		"changes": 0,
	}


def read_app_git(app):
	"""Live read-only git state of one app (4 local git calls, no network)."""
	repo = _app_repo(app)
	if not repo:
		return _unreadable(app, "Not a git checkout in this bench")
	status = _git(repo, ["status", "--porcelain=v2", "--branch"])
	if status is None:
		return _unreadable(app, "Git could not be read (timed out or failed)")
	s = parse_status_v2(status)
	detached = s["head"] in (None, "(detached)")
	oid = s["oid"] if s["oid"] and s["oid"] != "(initial)" else ""
	short = oid[:7]
	date = (_git(repo, ["log", "-1", "--format=%cI"]) or "").strip()
	tags = (_git(repo, ["tag", "--points-at", "HEAD"]) or "").split()
	has_up = bool(s["upstream"])
	remotes = _git(repo, ["config", "--local", "--get-regexp", r"^(remote\..+\.url|branch\..+\.remote)$"])
	return {
		"app": app,
		"branch": f"detached at {short}" if detached else s["head"],
		"detached": detached,
		"upstream": s["upstream"],
		"ahead": s["ahead"] if has_up else 0,
		"behind": s["behind"] if has_up else 0,
		"tracked_changes": s["tracked"],
		"untracked": s["untracked"],
		"changes": s["tracked"] + s["untracked"],
		"commit": short,
		"commit_date": date[:19].replace("T", " ") if date else None,
		"tag": tags[0] if tags else None,
		"sync": sync_state(has_up, s["ahead"], s["behind"]),
		"fetched_at": _fetched_at(repo),
		"repo_url": _clean_repo_url(parse_remote_config(remotes, s["head"])),
		"error": None,
	}


def _live_git(refresh=False):
	"""All installed apps' git state, cached for CACHE_SECONDS (a forced refresh is honoured
	only when the cached copy is older than MIN_REFRESH_SECONDS)."""
	cache = frappe.cache()
	cached = cache.get_value(CACHE_KEY)
	if cached:
		age = time.time() - cached["at"]
		if age < CACHE_SECONDS and (not refresh or age < MIN_REFRESH_SECONDS):
			return cached["apps"], cached["at"], True
	names = sorted(frappe.get_installed_apps())
	with ThreadPoolExecutor(max_workers=GIT_WORKERS) as pool:
		apps = list(pool.map(read_app_git, names))
	at = time.time()
	cache.set_value(CACHE_KEY, {"apps": apps, "at": at}, expires_in_sec=CACHE_SECONDS)
	return apps, at, False


def _recorded_rows():
	"""What the last 'Scan bench' recorded (Module Version Check) - shown for comparison only.
	The repository URL is cleaned of credentials; no other free text is returned."""
	if not frappe.db.exists("DocType", "Module Version Check"):
		return {}
	rows = frappe.db.sql(
		"""SELECT module_name, repository_url, status, current_branch, commits_ahead, commits_behind,
		          has_uncommitted_changes, last_checked_at
		   FROM `tabModule Version Check` ORDER BY modified DESC LIMIT 200""",
		as_dict=True,
	)
	return {r.module_name: r for r in rows}


def _recorded_summary(rec):
	"""The stored scan of one app as the page shows it (no free text, no credentials)."""
	if not rec:
		return None
	return {
		"status": rec.status,
		"branch": rec.current_branch,
		"ahead": rec.commits_ahead or 0,
		"behind": rec.commits_behind or 0,
		"uncommitted": bool(rec.has_uncommitted_changes),
		"checked_at": str(rec.last_checked_at)[:19] if rec.last_checked_at else None,
	}


def _apps_section(search, state, refresh):
	live, at, cached = _live_git(refresh)
	recorded = _recorded_rows()
	search = (search or "").strip().lower()
	rows = []
	for a in live:
		if search and search not in a["app"].lower() and search not in (a.get("branch") or "").lower():
			continue
		rec = recorded.get(a["app"])
		row = dict(a)
		row["repo_url"] = a.get("repo_url") or (_clean_repo_url(rec.repository_url) if rec else None)
		row["recorded"] = _recorded_summary(rec)
		row["needs_attention"] = bool(row["error"]) or row.get("sync") != "synced" or bool(row.get("changes"))
		rows.append(row)

	counts = {s: 0 for s in SYNC_STATES}
	uncommitted = errors = up_to_date = 0
	for r in rows:
		if r["error"]:
			errors += 1
			continue
		counts[r["sync"]] += 1
		if r["changes"]:
			uncommitted += 1
		if r["sync"] == "synced" and not r["changes"]:
			up_to_date += 1
	total = len(rows)
	totals = {
		"apps": total,
		"up_to_date": up_to_date,
		"needs_attention": total - up_to_date,
		"uncommitted": uncommitted,
		"unreadable": errors,
		**counts,
	}
	installed = {a["app"] for a in live}
	recorded_only = [
		{"app": n, "repo_url": _clean_repo_url(r.repository_url), **_recorded_summary(r)}
		for n, r in sorted(recorded.items())
		if n not in installed
	]

	if state in STATE_FILTERS:
		rows = [r for r in rows if _matches_state(r, state)]
	order = {"diverged": 0, "behind": 1, "ahead": 2, "no_upstream": 3, "synced": 4}
	rows.sort(key=lambda r: (not r["changes"], order.get(r.get("sync"), 5), r["app"]))
	return {
		"rows": rows,
		"totals": totals,
		"read_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(at)),
		"cached": cached,
		"recorded_not_installed": recorded_only,
		"recorded_last_scan": max(
			(str(r.last_checked_at)[:19] for r in recorded.values() if r.last_checked_at), default=None
		),
	}


def _matches_state(r, state):
	if state == "uncommitted":
		return bool(r["changes"])
	if state == "behind":  # includes "diverged": the page's Behind remote card counts both
		return bool(r["behind"])
	if state == "ahead":  # includes "diverged"
		return bool(r["ahead"])
	if state == "attention":
		return r["needs_attention"]
	if state == "clean":
		return not r["needs_attention"]
	return r.get("sync") == state


# --------------------------------------------------------------------------- other sections


def _range(from_date, to_date):
	"""Inclusive day range -> (start datetime string, exclusive end datetime string)."""
	to_d = getdate(to_date) if to_date else getdate(nowdate())
	from_d = getdate(from_date) if from_date else getdate(add_days(to_d, -6))
	if from_d > to_d:
		from_d, to_d = to_d, from_d
	return from_d, to_d, f"{from_d} 00:00:00", f"{add_days(to_d, 1)} 00:00:00"


def _drift_section():
	if not frappe.db.exists("DocType", "Field Difference Log"):
		return {"by_type": {}, "total": 0, "rows": [], "truncated": False, "ignored": 0}
	by_type = dict(
		frappe.db.sql(
			"""SELECT issue_type, COUNT(*) FROM `tabField Difference Log`
			   WHERE COALESCE(status, '') != 'Ignored' GROUP BY issue_type"""
		)
	)
	ignored = frappe.db.sql("SELECT COUNT(*) FROM `tabField Difference Log` WHERE status = 'Ignored'")[0][0]
	total = sum(by_type.values())
	rows = frappe.db.sql(
		f"""SELECT name, doctype_name, field_name, issue_type, status, comparison_time
		    FROM `tabField Difference Log` WHERE COALESCE(status, '') != 'Ignored'
		    ORDER BY comparison_time DESC LIMIT {ROW_LIMIT}""",
		as_dict=True,
	)
	for r in rows:
		r["comparison_time"] = str(r.comparison_time)[:19] if r.comparison_time else None
	return {
		"by_type": by_type,
		"total": total,
		"rows": rows,
		"truncated": total > len(rows),
		"ignored": ignored,
	}


def _deployments_section(start, end, state, search):
	if not DEPLOYMENT_VIEWER_ROLES & set(frappe.get_roles()) or not frappe.db.exists(
		"DocType", "Deployment Request"
	):
		return {
			"allowed": False,
			"by_state": {},
			"total": 0,
			"rows": [],
			"truncated": False,
			"pending_approval": 0,
		}
	where = ["creation >= %(start)s", "creation < %(end)s"]
	args = {"start": start, "end": end}
	if search:
		where.append("(app LIKE %(q)s OR instance LIKE %(q)s OR branch LIKE %(q)s)")
		args["q"] = _like(search)
	cond = " AND ".join(where)
	by_state = dict(
		frappe.db.sql(
			f"SELECT COALESCE(workflow_state, ''), COUNT(*) FROM `tabDeployment Request` WHERE {cond} GROUP BY 1",
			args,
		)
	)
	pending = frappe.db.sql(
		f"""SELECT COUNT(*) FROM `tabDeployment Request`
		    WHERE {cond} AND requires_approval = 1 AND approval_status = 'Pending'""",
		args,
	)[0][0]
	row_cond = cond
	if state:
		row_cond += " AND workflow_state = %(state)s"
		args["state"] = state
	rows = frappe.db.sql(
		f"""SELECT name, app, instance, branch, commit_hash, workflow_state, requires_approval,
		           approval_status, requested_by_user, creation
		    FROM `tabDeployment Request` WHERE {row_cond}
		    ORDER BY creation DESC LIMIT {ROW_LIMIT}""",
		args,
		as_dict=True,
	)
	for r in rows:
		r["creation"] = str(r.creation)[:19]
		r["commit_hash"] = (r.commit_hash or "")[:12]
	total = sum(by_state.values())
	shown_total = by_state.get(state, 0) if state else total
	return {
		"allowed": True,
		"by_state": by_state,
		"total": total,
		"rows": rows,
		"truncated": shown_total > len(rows),
		"pending_approval": pending,
	}


def _recent_errors():
	"""The latest RECENT_ERRORS logged errors, whatever the date range (what the current
	page's "Recent errors" card shows)."""
	rows = frappe.db.sql(
		f"""SELECT name, activity_time, title, source, description FROM `tabDeveloper Activity Log`
		    WHERE status = 'Error' ORDER BY activity_time DESC LIMIT {RECENT_ERRORS}""",
		as_dict=True,
	)
	for r in rows:
		r["activity_time"] = str(r.activity_time)[:19] if r.activity_time else None
		r["title"] = _redact(r.title, 160)
		r["description"] = _redact(r.description)
	return rows


def _activity_section(start, end, status, atype, search):
	out = {"by_status": {}, "by_type": {}, "total": 0, "rows": [], "truncated": False, "recent_errors": []}
	if frappe.db.exists("DocType", "Developer Activity Log"):
		where = ["activity_time >= %(start)s", "activity_time < %(end)s"]
		args = {"start": start, "end": end}
		if search:
			where.append("(title LIKE %(q)s OR source LIKE %(q)s)")
			args["q"] = _like(search)
		base = " AND ".join(where)
		out["by_status"] = dict(
			frappe.db.sql(
				f"SELECT COALESCE(status, ''), COUNT(*) FROM `tabDeveloper Activity Log` WHERE {base} GROUP BY 1",
				args,
			)
		)
		out["by_type"] = dict(
			frappe.db.sql(
				f"SELECT COALESCE(activity_type, ''), COUNT(*) FROM `tabDeveloper Activity Log` WHERE {base} GROUP BY 1",
				args,
			)
		)
		out["total"] = sum(out["by_status"].values())
		row_where = base
		if status:
			row_where += " AND status = %(status)s"
			args["status"] = status
		if atype:
			row_where += " AND activity_type = %(atype)s"
			args["atype"] = atype
		rows = frappe.db.sql(
			f"""SELECT name, activity_time, activity_type, title, status, source, description
			    FROM `tabDeveloper Activity Log` WHERE {row_where}
			    ORDER BY activity_time DESC LIMIT {ROW_LIMIT}""",
			args,
			as_dict=True,
		)
		for r in rows:
			r["activity_time"] = str(r.activity_time)[:19] if r.activity_time else None
			r["description"] = _redact(r.description)
			r["title"] = _redact(r.title, 160)
		out["rows"] = rows
		filtered = frappe.db.sql(f"SELECT COUNT(*) FROM `tabDeveloper Activity Log` WHERE {row_where}", args)[
			0
		][0]
		out["filtered_total"] = filtered
		out["recent_errors"] = _recent_errors()
		out["truncated"] = filtered > len(rows)
	return out


def _snapshots_section(start, end):
	out = {"in_range": 0, "changed_in_range": 0, "today": 0, "last_backup": None, "total": 0}
	if not frappe.db.exists("DocType", "Code Backup Snapshot"):
		return out
	a, b = frappe.db.sql(
		"""SELECT COUNT(*), COALESCE(SUM(changed_since_last_backup), 0) FROM `tabCode Backup Snapshot`
		   WHERE snapshot_time >= %s AND snapshot_time < %s""",
		(start, end),
	)[0]
	out["in_range"], out["changed_in_range"] = int(a), int(b)
	out["today"] = frappe.db.sql(
		"SELECT COUNT(*) FROM `tabCode Backup Snapshot` WHERE snapshot_time >= %s", (nowdate(),)
	)[0][0]
	last = frappe.db.sql("SELECT MAX(snapshot_time) FROM `tabCode Backup Snapshot`")[0][0]
	out["last_backup"] = str(last)[:19] if last else None
	out["total"] = frappe.db.sql("SELECT COUNT(*) FROM `tabCode Backup Snapshot`")[0][0]
	return out


# --------------------------------------------------------------------------- endpoint


@frappe.whitelist()
def get_dev_dashboard(
	search: str = "",
	state: str = "",
	from_date: str = "",
	to_date: str = "",
	deploy_state: str = "",
	activity_status: str = "",
	activity_type: str = "",
	refresh: int = 0,
):
	"""Everything the Dev Dashboard page shows, in one read-only call.

	search          app name / branch (Apps), app/instance/branch (Deployments), title/source (Activity)
	state           Apps table filter: synced|behind (any behind, incl. diverged)|ahead (any not pushed,
	                incl. diverged)|diverged|no_upstream|uncommitted|attention|clean
	from_date/to_date  day range for Deployments (raised), Activity and snapshots
	deploy_state    Deployments table filter (workflow state)
	activity_status / activity_type  Activity table filters
	refresh         re-read git now (honoured at most once every MIN_REFRESH_SECONDS)
	"""
	_require_dev_team()
	try:
		search = (search or "").strip()[:100]
		state = (state or "").strip()
		from_d, to_d, start, end = _range(from_date, to_date)
		t0 = time.time()
		apps = _apps_section(search, state, bool(int(refresh or 0)))
		t1 = time.time()
		res = {
			"success": True,
			"from_date": str(from_d),
			"to_date": str(to_d),
			"generated_at": str(now_datetime())[:19],
			"apps": apps,
			"drift": _drift_section(),
			"deployments": _deployments_section(start, end, (deploy_state or "").strip(), search),
			"activity": _activity_section(
				start, end, (activity_status or "").strip(), (activity_type or "").strip(), search
			),
			"snapshots": _snapshots_section(start, end),
			"row_limit": ROW_LIMIT,
			"permissions": {
				"scan": True,
				"raise_deployment": bool(DEPLOYER_ROLES & set(frappe.get_roles())),
			},
			"timing_ms": {"git": round((t1 - t0) * 1000), "total": round((time.time() - t0) * 1000)},
		}
		return res
	except frappe.PermissionError:
		raise
	except Exception:
		frappe.logger("dev_dashboard_v2").exception("Dev Dashboard v2 read failed")
		return {"success": False, "error": "The dashboard could not be read just now. Please try again."}


@frappe.whitelist()
def get_deployment_for_duplicate(name: str):
	"""The fields "Duplicate" pre-fills (app, instance, branch, description) for one Deployment
	Request. Same audience as the current recent-deployments call (DEPLOYMENT_VIEWER_ROLES); the
	description is returned in full but with anything credential-like hidden."""
	if not DEPLOYMENT_VIEWER_ROLES & set(frappe.get_roles()):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	row = frappe.db.get_value(
		"Deployment Request", name, ["app", "instance", "branch", "description"], as_dict=True
	)
	if not row:
		frappe.throw(_("Deployment request not found."), frappe.DoesNotExistError)
	row["description"] = _redact(row.description, DESCRIPTION_LIMIT, keep_lines=True)
	return row
