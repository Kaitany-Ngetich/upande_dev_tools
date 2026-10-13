# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
"""Code Snapshots v2 - how many code backups exist, how big, how fresh, and what is in one.

Source: `Code Backup Snapshot` (one row = one saved version of one DocType / Server Script /
Client Script; written by backup/scheduler.py only when the content hash changed) and
`Developer Activity Log` (one row per scheduler run, activity_type "Backup", plus
"Error" rows whose title says "backup failed").

DEFINITIONS
    snapshot            one row of Code Backup Snapshot, dated by snapshot_time (site time zone,
                        naive; the same clock as now_datetime(), no conversion is done)
    size                LENGTH(content_json) in BYTES (shown as KB/MB). The scheduler also copies the
                        same text into script_code, so the database holds about twice this
                        (verified: 2 x 266.2 MB of content vs 511.8 MB table size locally).
    version number      n-th snapshot of the same (source_type, document_name), by id, over the WHOLE
                        table (not only the filtered rows). Version 1 = "first recorded", others
                        = "changed". The stored flag changed_since_last_backup is 1 on every row
                        (even a first version), so it is NOT used.
    retention           Code Backup Settings.retention_days (doctype default 30). NOTHING in the app
                        deletes old snapshots, so "past retention" is the count/size of snapshots
                        older than now - retention_days. Cutoff = now - retention_days days.
    schedule            Code Backup Settings.backup_intervals_hours (doctype default 4). Freshness
                        compares the age of the last scheduler check with this interval.
    last good snapshot  MAX(snapshot_time) (last time something changed and was saved);
    last check          latest Developer Activity Log "Backup" row with status Success (the run
                        happened and saved nothing, or saved something).
    failure             Developer Activity Log row with status "Error" and a backup title, or an
                        activity_type "Error" whose title contains "backup failed".

IDENTITIES (verified in tests/report; every figure follows every filter except where noted)
    snapshots = sum(by_day.snapshots) = sum(by_source) = sum(by_app) = sum(by_trigger)
              = first_recorded + changed
    size_bytes = sum(by_day.bytes) = sum(by_source.bytes) = sum(by_app.bytes)
    snapshots_past_retention <= snapshots_all_dates (retention card ignores only the date range)
    runs = checked_no_change + saved + other + failed  (run figures are for the date range
           only: the log records no app/source, so source/app/search filters do not apply to them)

SECRETS: Code Backup Settings is read through an explicit short list of non-secret fields.
Snapshot content is never returned - only counts, field/key names and line totals.
READ ONLY: nothing here writes, commits, triggers a backup or restores anything.
"""

import difflib
import json

import frappe
from frappe.utils import add_days, add_to_date, get_datetime, getdate, now_datetime, nowdate

from upande_dev_tools.api.code_snapshots import _require_dev_team

ROW_LIMIT = 200
MAX_PAGE = 200
NONE_KEY = "__none__"
DEFAULT_INTERVAL_HOURS = 4  # doctype default of backup_intervals_hours
DEFAULT_RETENTION_DAYS = 30  # doctype default of retention_days
SOURCE_TYPES = ("DocType", "Server Script", "Client Script")
APP_TOP = 12
DIFF_LINE_CAP = 20000

_SORTS = {
	"snapshot_time": "s.snapshot_time",
	"document_name": "s.document_name",
	"source_type": "s.source_type",
	"app": "s.app",
	"name": "s.name",
}

_META_KEY = "upande_dev_tools:code_snapshots_v2:meta"


def _meta():
	"""Per-snapshot facts that never change once written: size in bytes and version number.
	Snapshots are append-only, so they are cached and only rows newer than the cache are read
	(LENGTH() of the code column is the slow part). A changed row count or max id rebuilds it."""
	cache = frappe.cache()
	m = cache.get_value(_META_KEY)
	cnt, mx = frappe.db.sql("SELECT COUNT(*), COALESCE(MAX(name), 0) FROM `tabCode Backup Snapshot`")[0]
	if m and m.get("count") == cnt and m.get("max") == mx:
		return m
	if m and m.get("max", 0) <= mx and m.get("count", 0) <= cnt:
		base, rows = (
			m,
			frappe.db.sql(
				"""SELECT name, source_type, document_name, LENGTH(content_json) FROM `tabCode Backup Snapshot`
			WHERE name > %s ORDER BY name""",
				(m["max"],),
			),
		)
	else:
		base = {"bytes": {}, "ver": {}, "seen": {}}
		rows = frappe.db.sql(
			"""SELECT name, source_type, document_name, LENGTH(content_json) FROM `tabCode Backup Snapshot`
			ORDER BY name"""
		)
	bytes_, ver, seen = base["bytes"], base["ver"], base["seen"]
	for name, src, doc, ln in rows:
		key = f"{src}|{doc}"
		seen[key] = seen.get(key, 0) + 1
		bytes_[name] = int(ln or 0)
		ver[name] = seen[key]
	m = {"count": cnt, "max": mx, "bytes": bytes_, "ver": ver, "seen": seen}
	cache.set_value(_META_KEY, m)
	return m


def _fail(msg):
	return {"success": False, "error": msg}


def _args(kw):
	g = lambda k: str(kw.get(k) or "").strip()  # noqa: E731
	today = getdate(nowdate())
	to_date = getdate(g("to_date") or today)
	from_date = getdate(g("from_date") or add_days(to_date, -29))
	all_dates = g("all_dates") in ("1", "true", "True")
	if all_dates:  # the current page has no date window: span the first snapshot up to today
		first = frappe.db.sql("SELECT MIN(snapshot_time) FROM `tabCode Backup Snapshot`")[0][0]
		from_date, to_date = (getdate(first) if first else today), today
	if from_date > to_date:
		from_date, to_date = to_date, from_date
	source = g("source_type")
	if source and source not in SOURCE_TYPES:
		source = ""
	return {
		"from_date": from_date,
		"to_date": to_date,
		"all_dates": all_dates,
		"source_type": source,
		"app": g("app"),
		"trigger": g("trigger"),
		"kind": g("kind") if g("kind") in ("new", "changed") else "",
		"search": g("search")[:100],
	}


def _where(a, with_dates=True):
	conds, p = [], {}
	if with_dates:
		conds.append("s.snapshot_time >= %(f)s AND s.snapshot_time < %(t)s")
		p["f"] = a["from_date"]
		p["t"] = add_days(a["to_date"], 1)
	if a["source_type"]:
		conds.append("s.source_type = %(src)s")
		p["src"] = a["source_type"]
	if a["app"] == NONE_KEY:
		conds.append("(s.app IS NULL OR s.app = '')")
	elif a["app"]:
		conds.append("s.app = %(app)s")
		p["app"] = a["app"]
	if a["trigger"]:
		conds.append("COALESCE(s.backed_up_by, '') = %(trg)s")
		p["trg"] = a["trigger"]
	if a["search"]:
		conds.append("s.document_name LIKE %(q)s")
		p["q"] = "%" + a["search"].replace("%", "\\%").replace("_", "\\_") + "%"
	return (" AND ".join(conds) or "1=1"), p


def _settings():
	"""Non-secret facts only. The scheduler writes last_backup_time into the Singles table under
	that name, while the doctype field is last_back_up_time (never written), so both are read."""
	fields = (
		"enabled",
		"backup_intervals_hours",
		"retention_days",
		"include_doctypes",
		"include_server_scripts",
		"include_client_scripts",
		"last_backup_time",
		"last_back_up_time",
	)
	# explicit non-secret field list; a field never saved is simply absent from tabSingles
	vals = dict(
		frappe.db.sql(
			"""SELECT field, value FROM tabSingles WHERE doctype = 'Code Backup Settings' AND field IN %(f)s""",
			{"f": fields},
		)
	)

	def flag(field):
		v = vals.get(field)
		return True if v in (None, "") else bool(int(v))

	interval, retention, enabled = (
		vals.get("backup_intervals_hours"),
		vals.get("retention_days"),
		vals.get("enabled"),
	)
	last = vals.get("last_backup_time") or vals.get("last_back_up_time")

	return {
		"enabled": flag("enabled"),
		"interval_hours": int(interval or 0) or DEFAULT_INTERVAL_HOURS,
		"retention_days": int(retention or 0) or DEFAULT_RETENTION_DAYS,
		"include_doctypes": flag("include_doctypes"),
		"include_server_scripts": flag("include_server_scripts"),
		"include_client_scripts": flag("include_client_scripts"),
		"last_check_setting": str(last) if last else None,
		"values_saved": any(v is not None for v in (interval, retention, enabled)),
	}


def _hours(a, b):
	return round((get_datetime(a) - get_datetime(b)).total_seconds() / 3600, 2)


def _freshness(settings, now):
	"""Soft state from the age of the last good snapshot and last check vs the schedule."""
	last_snap = frappe.db.sql("SELECT MAX(snapshot_time) FROM `tabCode Backup Snapshot`")[0][0]
	last_check = frappe.db.sql(
		"""SELECT MAX(activity_time) FROM `tabDeveloper Activity Log`
		   WHERE activity_type = 'Backup' AND status = 'Success'"""
	)[0][0]
	interval = settings["interval_hours"]
	out = {
		"interval_hours": interval,
		"last_snapshot": str(last_snap) if last_snap else None,
		"last_snapshot_age_hours": _hours(now, last_snap) if last_snap else None,
		"last_check": str(last_check) if last_check else None,
		"last_check_age_hours": _hours(now, last_check) if last_check else None,
	}
	age = out["last_check_age_hours"]
	if not settings["enabled"]:
		state, text = "paused", "Backups are switched off in the settings."
	elif age is None:
		state, text = "none", "No backup run has been recorded yet."
	elif age <= interval * 1.5:
		state, text = "good", "Checks are running on schedule."
	elif age <= interval * 6:
		state, text = "late", "The last check was a little later than the schedule."
	else:
		state, text = "stale", "No backup check has been recorded for a while, worth a look."
	out["state"] = state
	out["text"] = text
	return out


def _run_rows(a):
	"""Scheduler runs and failures in the date range, from the activity log."""
	return frappe.db.sql(
		"""SELECT DATE(activity_time) AS d,
			SUM(activity_type = 'Backup' AND title = 'Code backup completed' AND status = 'Success') AS saved,
			SUM(activity_type = 'Backup' AND title = 'Code backup checked' AND status = 'Success') AS no_change,
			SUM(status = 'Error') AS failed,
			SUM(NOT (status = 'Error') AND NOT (status = 'Success' AND title IN
				('Code backup completed', 'Code backup checked'))) AS other,
			COUNT(*) AS runs
		   FROM `tabDeveloper Activity Log`
		   WHERE (activity_type = 'Backup' OR (activity_type = 'Error' AND title LIKE %(bk)s))
			AND activity_time >= %(f)s AND activity_time < %(t)s
		   GROUP BY DATE(activity_time)""",
		{"f": a["from_date"], "t": add_days(a["to_date"], 1), "bk": "%backup failed%"},
		as_dict=True,
	)


def _days(f, t):
	d = getdate(f)
	end = getdate(t)
	out = []
	while d <= end:
		out.append(str(d))
		d = add_days(d, 1)
	return out


@frappe.whitelist()
def get_overview(**kw):
	"""Everything the summary needs in one call: settings, freshness, KPIs, series, roll-ups.
	`all_dates=1` ignores from/to and spans the first snapshot to today (the current page's view)."""
	try:
		_require_dev_team()
		a = _args(kw)
		now = now_datetime()
		settings = _settings()
		cutoff = add_to_date(now, days=-settings["retention_days"])
		where, p = _where(a)

		meta = _meta()
		ver, size = meta["ver"], meta["bytes"]
		light = frappe.db.sql(
			f"""SELECT s.name, s.snapshot_time, s.source_type, s.document_name, COALESCE(NULLIF(s.app, ''), %(none)s),
				COALESCE(NULLIF(s.backed_up_by, ''), 'Unknown')
			FROM `tabCode Backup Snapshot` s WHERE {where}""",
			{**p, "none": NONE_KEY},
		)
		by_day, by_src, by_app, by_trg = {}, {}, {}, {}
		total = bytes_ = new = past_n = past_b = 0
		docset = set()
		for name, st, src, doc, app, trg in light:
			is_new = ver.get(name) == 1
			if (a["kind"] == "new" and not is_new) or (a["kind"] == "changed" and is_new):
				continue
			b = size.get(name, 0)
			total += 1
			bytes_ += b
			new += is_new
			docset.add((src, doc))
			if st < cutoff:
				past_n += 1
				past_b += b
			day = by_day.setdefault(str(st.date()), {"snapshots": 0, "bytes": 0, "new": 0, "changed": 0})
			day["snapshots"] += 1
			day["bytes"] += b
			day["new" if is_new else "changed"] += 1
			for bucket, key in ((by_src, src), (by_app, app), (by_trg, trg)):
				e = bucket.setdefault(key, {"snapshots": 0, "bytes": 0})
				e["snapshots"] += 1
				e["bytes"] += b
		docs = len(docset)

		runs = {str(r.d): r for r in _run_rows(a)}
		series = []
		for d in _days(a["from_date"], a["to_date"]):
			x = by_day.get(d, {"snapshots": 0, "bytes": 0, "new": 0, "changed": 0})
			r = runs.get(d)
			series.append(
				{
					"day": d,
					**x,
					"runs": int(r.runs) if r else 0,
					"saved_runs": int(r.saved) if r else 0,
					"failed": int(r.failed) if r else 0,
				}
			)
		run_tot = {
			k: sum(int(r[k] or 0) for r in runs.values())
			for k in ("runs", "saved", "no_change", "failed", "other")
		}

		def rows(bucket, label_key):
			return sorted(
				({label_key: k, **v} for k, v in bucket.items()),
				key=lambda r: (-r["snapshots"], str(r[label_key])),
			)

		apps = rows(by_app, "app")
		if len(apps) > APP_TOP:
			rest = apps[APP_TOP:]
			apps = [
				*apps[:APP_TOP],
				{
					"app": "__other__",
					"snapshots": sum(r["snapshots"] for r in rest),
					"bytes": sum(r["bytes"] for r in rest),
					"count_apps": len(rest),
				},
			]

		# retention: ignores only the date range, so it shows what is really on disk for these filters
		w2, p2 = _where(a, with_dates=False)
		allrows = frappe.db.sql(
			f"SELECT s.name, s.snapshot_time FROM `tabCode Backup Snapshot` s WHERE {w2}", p2
		)
		kind_ok = (lambda n: True) if not a["kind"] else (lambda n: (ver.get(n) == 1) == (a["kind"] == "new"))
		allrows = [r for r in allrows if kind_ok(r[0])]
		ret = frappe._dict(
			n=len(allrows),
			b=sum(size.get(r[0], 0) for r in allrows),
			oldest=min((r[1] for r in allrows), default=None),
			past_n=sum(1 for r in allrows if r[1] < cutoff),
			past_b=sum(size.get(r[0], 0) for r in allrows if r[1] < cutoff),
		)
		oldest = ret.oldest

		options = {
			"apps": [
				r[0]
				for r in frappe.db.sql(
					"""SELECT DISTINCT app FROM `tabCode Backup Snapshot`
					   WHERE app IS NOT NULL AND app <> '' ORDER BY app"""
				)
			],
			"has_unassigned": bool(
				frappe.db.sql(
					"""SELECT 1 FROM `tabCode Backup Snapshot` WHERE app IS NULL OR app = '' LIMIT 1"""
				)
			),
			"triggers": [
				r[0]
				for r in frappe.db.sql(
					"""SELECT DISTINCT COALESCE(NULLIF(backed_up_by, ''), 'Unknown')
					   FROM `tabCode Backup Snapshot` ORDER BY 1"""
				)
			],
		}
		return {
			"success": True,
			"all_dates": a["all_dates"],
			"from_date": str(a["from_date"]),
			"to_date": str(a["to_date"]),
			"now": str(now),
			"settings": settings,
			"freshness": _freshness(settings, now),
			"kpis": {
				"snapshots": total,
				"size_bytes": bytes_,
				"documents": int(docs or 0),
				"first_recorded": new,
				"changed": total - new,
				"apps": len([k for k in by_app if k != NONE_KEY]),
			},
			"runs": run_tot,
			"retention": {
				"retention_days": settings["retention_days"],
				"cutoff": str(cutoff),
				"snapshots_all_dates": int(ret.n or 0),
				"size_all_dates_bytes": int(ret.b or 0),
				"past_snapshots": int(ret.past_n or 0),
				"past_bytes": int(ret.past_b or 0),
				"oldest": str(oldest) if oldest else None,
				"oldest_age_days": round(_hours(now, oldest) / 24, 1) if oldest else None,
				"past_in_range": past_n,
				"past_in_range_bytes": past_b,
				"cleanup_exists": False,
			},
			"by_day": series,
			"by_source": rows(by_src, "source_type"),
			"by_app": apps,
			"by_trigger": rows(by_trg, "trigger"),
			"options": options,
		}
	except frappe.PermissionError:
		return _fail("You do not have access to code snapshots.")
	except Exception:
		frappe.log_error(title="code_snapshots_v2.get_overview")
		return _fail("The snapshot summary could not be loaded. Please try again.")


@frappe.whitelist()
def get_snapshots(sort="snapshot_time", desc=1, start=0, limit=50, **kw):
	"""Snapshot list (no content) with the same filters as the overview."""
	try:
		_require_dev_team()
		a = _args(kw)
		start = max(0, int(start or 0))
		limit = max(1, min(int(limit or 50), MAX_PAGE))
		order = _SORTS.get(sort, "s.snapshot_time")
		direction = "DESC" if str(desc) not in ("0", "false", "False", "") else "ASC"
		where, p = _where(a)
		meta = _meta()
		ver, size = meta["ver"], meta["bytes"]
		cols = """s.name, s.snapshot_time, s.source_type, s.document_name, s.app, s.module,
			s.backed_up_by AS trigger_by, s.changed_since_last_backup AS changed_flag"""
		if a["kind"]:
			firsts = [n for n, v in ver.items() if v == 1] or [0]
			where += " AND s.name " + ("IN" if a["kind"] == "new" else "NOT IN") + " %(firsts)s"
			p["firsts"] = firsts
		py_sort = sort in ("size", "version")
		if py_sort:
			allr = frappe.db.sql(
				f"SELECT {cols} FROM `tabCode Backup Snapshot` s WHERE {where}", p, as_dict=True
			)
			key = (lambda r: size.get(r.name, 0)) if sort == "size" else (lambda r: ver.get(r.name, 0))
			allr.sort(key=lambda r: (key(r), r.name), reverse=direction == "DESC")
			total = len(allr)
			rows = allr[start : start + limit]
		else:
			total = frappe.db.sql(f"SELECT COUNT(*) FROM `tabCode Backup Snapshot` s WHERE {where}", p)[0][0]
			rows = frappe.db.sql(
				f"""SELECT {cols} FROM `tabCode Backup Snapshot` s WHERE {where}
				ORDER BY {order} {direction}, s.name DESC LIMIT %(lim)s OFFSET %(off)s""",
				{**p, "lim": limit, "off": start},
				as_dict=True,
			)
		for r in rows:
			r["snapshot_time"] = str(r["snapshot_time"])
			r["bytes"] = size.get(r["name"], 0)
			r["version"] = ver.get(r["name"], 1)
			r["changed_flag"] = bool(r["changed_flag"])
			r["name"] = str(r["name"])
		return {"success": True, "rows": rows, "total": int(total), "start": start, "limit": limit}
	except frappe.PermissionError:
		return _fail("You do not have access to code snapshots.")
	except Exception:
		frappe.log_error(title="code_snapshots_v2.get_snapshots")
		return _fail("The snapshot list could not be loaded. Please try again.")


@frappe.whitelist()
def get_runs(from_date=None, to_date=None, limit=100, all_dates=0):
	"""Recent scheduler runs and failures (newest first) for the date range."""
	try:
		_require_dev_team()
		a = _args({"from_date": from_date, "to_date": to_date, "all_dates": all_dates})
		limit = max(1, min(int(limit or 100), ROW_LIMIT))
		where = """(activity_type = 'Backup' OR (activity_type = 'Error' AND title LIKE %(bk)s))
			AND activity_time >= %(f)s AND activity_time < %(t)s"""
		p = {"f": a["from_date"], "t": add_days(a["to_date"], 1), "bk": "%backup failed%"}
		total = frappe.db.sql(f"SELECT COUNT(*) FROM `tabDeveloper Activity Log` WHERE {where}", p)[0][0]
		rows = frappe.db.sql(
			f"""SELECT name, activity_time, activity_type, title, LEFT(description, 300) AS description, status
			FROM `tabDeveloper Activity Log` WHERE {where}
			ORDER BY activity_time DESC LIMIT %(lim)s""",
			{**p, "lim": limit},
			as_dict=True,
		)
		for r in rows:
			r["activity_time"] = str(r["activity_time"])
		return {
			"success": True,
			"rows": rows,
			"total": int(total),
			"truncated": int(total) > len(rows),
			"row_limit": limit,
		}
	except frappe.PermissionError:
		return _fail("You do not have access to code snapshots.")
	except Exception:
		frappe.log_error(title="code_snapshots_v2.get_runs")
		return _fail("The run history could not be loaded. Please try again.")


def _load(text):
	try:
		d = json.loads(text or "")
		return d if isinstance(d, dict) else None
	except ValueError:
		return None


def _count(d, key):
	v = d.get(key)
	return len(v) if isinstance(v, list) else 0


# Bookkeeping that changes on every save without being a real change (child-row ids included).
_IGNORE = {
	"name",
	"parent",
	"parenttype",
	"parentfield",
	"modified",
	"creation",
	"modified_by",
	"owner",
	"idx",
	"_user_tags",
	"_comments",
	"_assign",
	"_liked_by",
}


def _doctype_summary(cur, prev):
	fields = [f for f in (cur.get("fields") or []) if isinstance(f, dict)]
	out = {
		"kind": "DocType",
		"facts": {
			"module": cur.get("module"),
			"fields": len(fields),
			"permission rules": _count(cur, "permissions"),
			"links": _count(cur, "links"),
			"actions": _count(cur, "actions"),
			"is child table": bool(cur.get("istable")),
			"single": bool(cur.get("issingle")),
			"submittable": bool(cur.get("is_submittable")),
			"custom": bool(cur.get("custom")),
		},
	}
	if prev is not None:
		pf = {f.get("fieldname"): f for f in (prev.get("fields") or []) if isinstance(f, dict)}
		cf = {f.get("fieldname"): f for f in fields}
		added = sorted(k for k in cf if k not in pf and k)
		removed = sorted(k for k in pf if k not in cf and k)
		changed = sorted(
			k
			for k in cf
			if k in pf
			and k
			and {x: y for x, y in cf[k].items() if x not in _IGNORE}
			!= {x: y for x, y in pf[k].items() if x not in _IGNORE}
		)
		props = sorted(
			k
			for k in set(cur) | set(prev)
			if k not in _IGNORE
			and k not in ("fields", "permissions", "links", "actions", "states")
			and cur.get(k) != prev.get(k)
		)
		out["changes"] = {
			"fields_added": added[:30],
			"fields_removed": removed[:30],
			"fields_changed": changed[:30],
			"counts": {"added": len(added), "removed": len(removed), "changed": len(changed)},
			"settings_changed": props[:30],
		}
	return out


def _script_text(d, source):
	return d.get("script") if source == "Client Script" or source == "Server Script" else ""


def _script_summary(source, cur, prev):
	text = _script_text(cur, source) or ""
	facts = {"lines": len(text.splitlines()), "characters": len(text)}
	if source == "Server Script":
		facts.update(
			{
				"script type": cur.get("script_type"),
				"document type": cur.get("reference_doctype"),
				"document event": cur.get("doctype_event"),
				"api method": cur.get("api_method"),
				"switched off": bool(cur.get("disabled")),
			}
		)
	else:
		facts.update(
			{
				"document type": cur.get("dt"),
				"view": cur.get("view"),
				"enabled": bool(cur.get("enabled")),
			}
		)
	out = {"kind": source, "facts": facts}
	if prev is not None:
		a = (_script_text(prev, source) or "").splitlines()
		b = text.splitlines()
		if len(a) + len(b) > DIFF_LINE_CAP:
			out["changes"] = {"too_large": True}
		else:
			added = removed = 0
			for line in difflib.unified_diff(a, b, lineterm="", n=0):
				if line.startswith("+") and not line.startswith("+++"):
					added += 1
				elif line.startswith("-") and not line.startswith("---"):
					removed += 1
			props = sorted(
				k
				for k in set(cur) | set(prev)
				if k not in _IGNORE and k != "script" and cur.get(k) != prev.get(k)
			)
			out["changes"] = {"lines_added": added, "lines_removed": removed, "settings_changed": props[:30]}
	return out


@frappe.whitelist()
def get_snapshot(name=None):
	"""Contents summary of one snapshot: size, key facts, and what changed since the previous
	version. Only counts and names are returned, never the code itself."""
	try:
		_require_dev_team()
		try:
			sid = int(name)
		except TypeError, ValueError:
			return _fail("Snapshot not found.")
		meta = _meta()
		row = frappe.db.sql(
			"""SELECT name, snapshot_time, source_type, document_name, app, module, backed_up_by, content_hash
			FROM `tabCode Backup Snapshot` WHERE name = %(n)s""",
			{"n": sid},
			as_dict=True,
		)
		if not row:
			return _fail("Snapshot not found.")
		r = row[0]
		r["bytes"] = meta["bytes"].get(sid, 0)
		r["version"] = meta["ver"].get(sid, 1)
		history = frappe.db.sql(
			"""SELECT name, snapshot_time, 0 AS bytes
			FROM `tabCode Backup Snapshot` WHERE source_type = %s AND document_name = %s
			ORDER BY name DESC LIMIT 25""",
			(r.source_type, r.document_name),
			as_dict=True,
		)
		versions_total = frappe.db.count(
			"Code Backup Snapshot", {"source_type": r.source_type, "document_name": r.document_name}
		)
		cur_text = frappe.db.get_value("Code Backup Snapshot", sid, "content_json")
		prev = frappe.db.sql(
			"""SELECT name, snapshot_time, content_json FROM `tabCode Backup Snapshot`
			WHERE source_type = %s AND document_name = %s AND name < %s ORDER BY name DESC LIMIT 1""",
			(r.source_type, r.document_name, sid),
			as_dict=True,
		)
		cur = _load(cur_text)
		prev_doc = _load(prev[0].content_json) if prev else None
		if cur is None:
			summary = {"kind": r.source_type, "facts": {}, "unreadable": True}
		elif r.source_type == "DocType":
			summary = _doctype_summary(cur, prev_doc if prev else None)
		else:
			summary = _script_summary(r.source_type, cur, prev_doc if prev else None)
		return {
			"success": True,
			"can_open_in_desk": bool(frappe.has_permission("Code Backup Snapshot", "read")),
			"snapshot": {
				"name": str(r.name),
				"snapshot_time": str(r.snapshot_time),
				"source_type": r.source_type,
				"document_name": r.document_name,
				"app": r.app,
				"module": r.module,
				"trigger": r.backed_up_by,
				"version": int(r.version),
				"versions_total": int(versions_total),
				"bytes": int(r.bytes or 0),
				"content_hash": (r.content_hash or "")[:12],
				"previous": {"name": str(prev[0].name), "snapshot_time": str(prev[0].snapshot_time)}
				if prev
				else None,
			},
			"summary": summary,
			"history": [
				{
					"name": str(h.name),
					"snapshot_time": str(h.snapshot_time),
					"bytes": meta["bytes"].get(h.name, 0),
				}
				for h in history
			],
		}
	except frappe.PermissionError:
		return _fail("You do not have access to code snapshots.")
	except Exception:
		frappe.log_error(title="code_snapshots_v2.get_snapshot")
		return _fail("That snapshot could not be loaded. Please try again.")
