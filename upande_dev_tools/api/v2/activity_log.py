# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
"""Activity Log v2 - what the developer tools recorded and when (read-only).

Two sources, both written by the tools themselves (backup scheduler, git monitor, hooks, the
difference checker), never by people typing:

    Developer Activity Log   one row per recorded event: activity_time, type, title, description,
                             status (Success / Warning / Error / Info), source, performed_by.
    Field Difference Log     one row per field that differs between this site and a live snapshot:
                             comparison_time, doctype, field, issue type, live / local value, status.
                             The checker deletes a doctype's old rows before saving a new run, so
                             this table only ever holds the LATEST comparison per doctype.

WHAT THE NUMBERS MEAN
    entries   = rows of Developer Activity Log in the filtered set (no joins, so no double counting).
    the day   = DATE(activity_time), i.e. the calendar day in the SITE time zone (the stored value is a
                naive site-time datetime). Range predicates are half-open
                (>= from 00:00, < to+1 00:00) so no index-hostile DATE() wraps the column and the last
                day is complete.
    people    = performed_by ("Administrator" for scheduled jobs and other automatic runs; empty
                values are shown as "Not recorded").
    "app"     = the row's `source` (Scheduler, Difference Checker ...), because the doctype has no
                app field. `activity_type` is the kind of activity (Backup, Git Monitor ...).

IDENTITIES (verified in tests/test_activity_log_v2.py and against raw SQL)
    total = sum(by_day.total) = sum(by_type) = sum(by_status) = sum(by_source) = sum(by_user incl. "Other")
    errors = by_day errors summed = by_status["Error"];   warnings likewise
    every figure (KPIs, chart, breakdowns, list total, export) uses the same WHERE, so it follows
    every filter.
    differences: total = sum(by_day) = sum(by_issue_type) = sum(by_status) = sum(by_doctype incl. "Other")

PERMISSIONS (never wider than the current page)
    Developer Activity Log: the current endpoint (api/activity_log.py) needs the "Dev Team" role and
    then reads with ignore_permissions, so every endpoint here needs "Dev Team" too.
    Field Difference Log: the current page does not show it; its doctype permission is System
    Manager only. So the difference endpoints additionally need frappe.has_permission on the doctype
    (System Manager); other Dev Team members just do not get that tab (can_see_differences = False).

SECRETS
    Values of fields named like password / secret / token / api key / private key / credential / auth,
    and of any field defined with type Password, are replaced by "[hidden]" in the detail view and the
    CSV. Free text (descriptions) has "token=...", "password: ..." style pairs and Bearer tokens
    scrubbed. Search never looks inside values or descriptions, so it cannot be used to guess a
    hidden value.
"""

import re
from datetime import date, timedelta

import frappe
from frappe import _
from frappe.utils import add_days, cint, getdate, nowdate

DEV_TOOLS_ROLES = {"Dev Team"}
ACTIVITY = "Developer Activity Log"
DIFF = "Field Difference Log"

MAX_DAYS = 366
DEFAULT_DAYS = 30
ALL_TIME_CHART_DAYS = 90
PAGE_MAX = 200
EXPORT_LIMIT = 5000
TOP_USERS = 15
TOP_DOCTYPES = 15
OPTION_LIMIT = 200
MAX_START = 100000
VALUE_LIMIT = 2000

HIDDEN = "[hidden]"
SENSITIVE_NAME = re.compile(
	r"pass(word|wd|phrase)?|secret|token|api[_ ]?key|apikey|private[_ ]?key|credential|authoriz|auth[_ ]?key|"
	r"access[_ ]?key|client[_ ]?secret|signature|(?<![a-z])otp|pin[_ ]?code|cookie|session[_ ]?id",
	re.I,
)
_PAIR = re.compile(
	r"((?:pass(?:word|wd|phrase)?|secret|token|api[_ -]?key|apikey|private[_ -]?key|authorization|credential"
	r"|access[_ -]?key|client[_ -]?secret|cookie|sid)[\w-]*\s*[:=]\s*)(?:(?:bearer|basic|token)\s+)?(\"[^\"]*\"|'[^']*'|\S+)",
	re.I,
)
_BEARER = re.compile(r"(bearer|token|basic)\s+[A-Za-z0-9._~+/=-]{8,}", re.I)

STATUS_ORDER = ["Error", "Warning", "Info", "Success"]


# ---------------------------------------------------------------- permissions


def _require_dev_team():
	if not DEV_TOOLS_ROLES & set(frappe.get_roles()):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def _can_see_differences() -> bool:
	try:
		return bool(frappe.has_permission(DIFF, "read"))
	except Exception:
		return False


def _require_differences():
	_require_dev_team()
	if not _can_see_differences():
		frappe.throw(_("Not permitted"), frappe.PermissionError)


# ---------------------------------------------------------------- helpers


def _g(kw, key):
	return str(kw.get(key) or "").strip()


def _range(kw):
	"""(from, to, clamped, all_time). Default: the last 30 days up to today (site time). At most 366 days.

	all_time (the current page's behaviour: every row ever recorded) leaves the filters unbounded;
	from / to then only describe the window of the per-day chart: the last ALL_TIME_CHART_DAYS days.
	"""
	today = getdate(nowdate())
	if cint(kw.get("all_time")):
		return add_days(today, -(ALL_TIME_CHART_DAYS - 1)), today, False, True
	to_date = getdate(_g(kw, "to_date") or today)
	from_date = getdate(_g(kw, "from_date") or add_days(to_date, -(DEFAULT_DAYS - 1)))
	if from_date > to_date:
		from_date, to_date = to_date, from_date
	clamped = False
	if (to_date - from_date).days + 1 > MAX_DAYS:
		from_date = to_date - timedelta(days=MAX_DAYS - 1)
		clamped = True
	return from_date, to_date, clamped, False


def _bounds(a, col):
	"""WHERE parts and params for the date range of column `col` (none when all_time)."""
	if a["all_time"]:
		return [], {}
	return [f"{col} >= %(f)s", f"{col} < %(t)s"], {"f": a["from"], "t": add_days(a["to"], 1)}


def _range_out(a):
	return {
		"from": _iso(a["from"]),
		"to": _iso(a["to"]),
		"clamped": a["clamped"],
		"max_days": MAX_DAYS,
		"all_time": a["all_time"],
	}


def _like(text):
	t = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
	return f"%{t}%"


def _scrub(text):
	"""Remove secrets from free text."""
	if not text:
		return text
	text = _PAIR.sub(lambda m: m.group(1) + HIDDEN, text)
	return _BEARER.sub(lambda m: m.group(1) + " " + HIDDEN, text)


def _days(f, t):
	out, d = [], f
	while d <= t:
		out.append(d)
		d += timedelta(days=1)
	return out


def _iso(d):
	return d.isoformat() if isinstance(d, date) else str(d)


def _user_names(users):
	users = [u for u in set(users) if u]
	if not users:
		return {}
	rows = frappe.get_all("User", filters={"name": ["in", users]}, fields=["name", "full_name"], limit=500)
	return {r.name: r.full_name or r.name for r in rows}


def _fail(msg):
	return {"success": False, "error": msg}


def _top(rows, key, n, other_label):
	"""rows sorted by count desc -> top n + "Other" so the parts add up to the total."""
	rows = sorted(rows, key=lambda r: (-r["count"], str(r[key] or "")))
	head, tail = rows[:n], rows[n:]
	if tail:
		head.append(
			{
				key: "__other__",
				"label": other_label.format(n=len(tail)),
				"count": sum(r["count"] for r in tail),
				"errors": sum(r.get("errors", 0) for r in tail),
			}
		)
	return head


# ================================================================ Developer Activity Log


def _known_status(value):
	"""The current page ignores a ?status= it does not know; so does this one."""
	return value if value in STATUS_ORDER else ""


def _a_args(kw):
	f, t, clamped, all_time = _range(kw)
	return {
		"from": f,
		"to": t,
		"clamped": clamped,
		"all_time": all_time,
		"user": _g(kw, "user"),
		"type": _g(kw, "activity_type"),
		"status": _known_status(_g(kw, "status")),
		"source": _g(kw, "source"),
		"search": _g(kw, "search")[:100],
		"sort": _g(kw, "sort"),
	}


def _a_where(a, skip=()):
	w, p = _bounds(a, "activity_time")
	if "user" not in skip and a["user"]:
		if a["user"] == "__none__":
			w.append("IFNULL(performed_by, '') = ''")
		else:
			w.append("performed_by = %(user)s")
			p["user"] = a["user"]
	if a["type"]:
		w.append("activity_type = %(type)s")
		p["type"] = a["type"]
	if a["status"]:
		w.append("status = %(status)s")
		p["status"] = a["status"]
	if "source" not in skip and a["source"]:
		if a["source"] == "__none__":
			w.append("IFNULL(source, '') = ''")
		else:
			w.append("source = %(source)s")
			p["source"] = a["source"]
	if a["search"]:
		w.append(
			"(title LIKE %(q)s OR source LIKE %(q)s OR reference_name LIKE %(q)s OR performed_by LIKE %(q)s)"
		)
		p["q"] = _like(a["search"])
	return " AND ".join(w) or "1=1", p


def _group(a, col, label_null="Not recorded"):
	where, p = _a_where(a)
	# nosemgrep: frappe-sql-format-injection -- col is a fixed literal from this module
	rows = frappe.db.sql(
		f"""SELECT IFNULL(NULLIF({col}, ''), '__none__') AS k, COUNT(*) AS c,
			SUM(status = 'Error') AS e
		FROM `tab{ACTIVITY}` WHERE {where} GROUP BY k""",
		p,
		as_dict=True,
	)
	return [
		{
			"key": r.k,
			"label": label_null if r.k == "__none__" else r.k,
			"count": int(r.c),
			"errors": int(r.e or 0),
		}
		for r in rows
	]


@frappe.whitelist()
def get_activity_summary(**kw):
	"""KPIs, per-day chart and breakdowns for the filtered Developer Activity Log."""
	_require_dev_team()
	try:
		a = _a_args(kw)
		where, p = _a_where(a)
		tot = frappe.db.sql(
			f"""SELECT COUNT(*) AS n, SUM(status='Error') AS errors, SUM(status='Warning') AS warnings,
				COUNT(DISTINCT performed_by) AS users, COUNT(DISTINCT DATE(activity_time)) AS active_days,
				MAX(activity_time) AS last_at
			FROM `tab{ACTIVITY}` WHERE {where}""",  # nosemgrep: frappe-sql-format-injection
			p,
			as_dict=True,
		)[0]
		day_rows = frappe.db.sql(
			f"""SELECT DATE(activity_time) AS d, COUNT(*) AS c, SUM(status='Error') AS e,
				SUM(status='Warning') AS w
			FROM `tab{ACTIVITY}` WHERE {where} GROUP BY d""",  # nosemgrep: frappe-sql-format-injection
			p,
			as_dict=True,
		)
		per_day = {_iso(r.d): r for r in day_rows}  # all_time: only the chart window is read back
		by_day = []
		for d in _days(a["from"], a["to"]):
			r = per_day.get(_iso(d))
			by_day.append(
				{
					"date": _iso(d),
					"total": int(r.c) if r else 0,
					"errors": int(r.e or 0) if r else 0,
					"warnings": int(r.w or 0) if r else 0,
				}
			)
		by_type = sorted(_group(a, "activity_type"), key=lambda r: -r["count"])
		by_status = _group(a, "status")
		by_status.sort(key=lambda r: STATUS_ORDER.index(r["key"]) if r["key"] in STATUS_ORDER else 99)
		by_source = sorted(_group(a, "source"), key=lambda r: -r["count"])
		users = _group(a, "performed_by")
		names = _user_names([u["key"] for u in users if u["key"] != "__none__"])
		for u in users:
			if u["key"] in names:
				u["name"] = names[u["key"]]
		by_user = _top(users, "key", TOP_USERS, "{n} other people")

		# option lists: follow the date range only, so choosing one value never empties the other lists
		od = {
			"from": a["from"],
			"to": a["to"],
			"all_time": a["all_time"],
			"user": "",
			"type": "",
			"status": "",
			"source": "",
			"search": "",
		}
		ow, op = _a_where(od)
		opts = {}
		for key, col in (("users", "performed_by"), ("sources", "source"), ("types", "activity_type")):
			opts[key] = frappe.db.sql(
				f"""SELECT DISTINCT {col} FROM `tab{ACTIVITY}`
				WHERE {ow} AND IFNULL({col}, '') <> '' ORDER BY {col} LIMIT {OPTION_LIMIT}""",  # nosemgrep
				op,
				pluck=col,
			)
		opts["user_names"] = _user_names(opts["users"])
		n = int(tot.n or 0)
		return {
			"success": True,
			"range": _range_out(a),
			"totals": {
				"entries": n,
				"errors": int(tot.errors or 0),
				"warnings": int(tot.warnings or 0),
				"problems": int(tot.errors or 0) + int(tot.warnings or 0),
				"users": int(tot.users or 0),
				"active_days": int(tot.active_days or 0),
				"days": len(by_day),
				"avg_per_active_day": (n / tot.active_days) if tot.active_days else 0,
				"last_at": str(tot.last_at) if tot.last_at else None,
			},
			"by_day": by_day,
			"by_type": by_type,
			"by_status": by_status,
			"by_source": by_source,
			"by_user": by_user,
			"options": opts,
			"can_see_differences": _can_see_differences(),
		}
	except frappe.PermissionError:
		raise
	except Exception:
		frappe.log_error(title="Activity Log v2: summary")
		return _fail(_("The activity summary could not be loaded. Please try again."))


_A_SORT = {
	"newest": "activity_time DESC, name DESC",
	"oldest": "activity_time ASC, name ASC",
	"problems": "FIELD(status, 'Error', 'Warning', 'Info', 'Success') ASC, activity_time DESC, name DESC",
}
_A_FIELDS = "name, activity_time, activity_type, title, status, source, performed_by, reference_doctype, reference_name"


@frappe.whitelist()
def get_activity_list(start=0, limit=50, **kw):
	"""One page of the filtered log, plus the full count of the filtered set."""
	_require_dev_team()
	try:
		a = _a_args(kw)
		where, p = _a_where(a)
		start = min(max(0, cint(start)), MAX_START)
		limit = max(1, min(cint(limit) or 50, PAGE_MAX))
		order = _A_SORT.get(a["sort"], _A_SORT["newest"])
		rows = frappe.db.sql(
			f"""SELECT {_A_FIELDS} FROM `tab{ACTIVITY}` WHERE {where}
			ORDER BY {order} LIMIT %(start)s, %(limit)s""",  # nosemgrep: frappe-sql-format-injection
			{**p, "start": start, "limit": limit},
			as_dict=True,
		)
		total = frappe.db.sql(
			f"SELECT COUNT(*) FROM `tab{ACTIVITY}` WHERE {where}",  # nosemgrep
			p,
		)[0][0]
		names = _user_names([r.performed_by for r in rows])
		out = [
			{
				**r,
				"activity_time": str(r.activity_time) if r.activity_time else None,
				"user_name": names.get(r.performed_by) or r.performed_by or "",
			}
			for r in rows
		]
		return {"success": True, "rows": out, "total": int(total), "start": start, "limit": limit}
	except Exception:
		frappe.log_error(title="Activity Log v2: list")
		return _fail(_("The log could not be loaded. Please try again."))


@frappe.whitelist()
def get_activity_entry(name=None):
	"""Full detail of one entry (description with secrets scrubbed)."""
	_require_dev_team()
	name = (name or "").strip()
	row = frappe.db.get_value(
		ACTIVITY,
		name,
		[
			"name",
			"activity_time",
			"activity_type",
			"title",
			"description",
			"status",
			"source",
			"performed_by",
			"reference_doctype",
			"reference_name",
			"creation",
			"owner",
		],
		as_dict=True,
	)
	if not row:
		return _fail(_("That entry was not found. It may have been deleted."))
	row["description"] = _scrub(row.description or "")[:20000]
	row["activity_time"] = str(row.activity_time) if row.activity_time else None
	row["creation"] = str(row.creation)
	row["user_name"] = _user_names([row.performed_by]).get(row.performed_by) or row.performed_by or ""
	return {"success": True, "entry": row}


@frappe.whitelist()
def get_activity_export(**kw):
	"""CSV rows for the filtered log: newest first, capped at EXPORT_LIMIT (truncated flag + full total)."""
	_require_dev_team()
	try:
		a = _a_args(kw)
		where, p = _a_where(a)
		order = _A_SORT.get(a["sort"], _A_SORT["newest"])
		rows = frappe.db.sql(
			f"""SELECT {_A_FIELDS}, description FROM `tab{ACTIVITY}` WHERE {where}
			ORDER BY {order} LIMIT {EXPORT_LIMIT}""",  # nosemgrep: frappe-sql-format-injection
			p,
			as_dict=True,
		)
		total = frappe.db.sql(f"SELECT COUNT(*) FROM `tab{ACTIVITY}` WHERE {where}", p)[0][0]  # nosemgrep
		for r in rows:
			r["activity_time"] = str(r.activity_time) if r.activity_time else ""
			r["description"] = _scrub(r.description or "")[:VALUE_LIMIT]
		return {
			"success": True,
			"rows": rows,
			"total": int(total),
			"truncated": int(total) > len(rows),
			"row_limit": EXPORT_LIMIT,
		}
	except Exception:
		frappe.log_error(title="Activity Log v2: export")
		return _fail(_("The export could not be prepared. Please try again."))


# ================================================================ Field Difference Log


def _d_args(kw):
	f, t, clamped, all_time = _range(kw)
	return {
		"from": f,
		"to": t,
		"clamped": clamped,
		"all_time": all_time,
		"issue_type": _g(kw, "issue_type"),
		"status": _g(kw, "status"),
		"doctype": _g(kw, "doctype_name"),
		"user": _g(kw, "user"),
		"search": _g(kw, "search")[:100],
	}


def _d_where(a):
	w, p = _bounds(a, "comparison_time")
	for key, col in (
		("issue_type", "issue_type"),
		("status", "status"),
		("doctype", "doctype_name"),
		("user", "owner"),
	):
		if a[key]:
			w.append(f"{col} = %({key})s")
			p[key] = a[key]
	if a["search"]:
		w.append("(doctype_name LIKE %(q)s OR field_name LIKE %(q)s)")
		p["q"] = _like(a["search"])
	return " AND ".join(w) or "1=1", p


def _dgroup(a, col):
	where, p = _d_where(a)
	rows = frappe.db.sql(
		f"""SELECT IFNULL(NULLIF({col}, ''), '__none__') AS k, COUNT(*) AS c
		FROM `tab{DIFF}` WHERE {where} GROUP BY k""",  # nosemgrep: frappe-sql-format-injection
		p,
		as_dict=True,
	)
	return [
		{"key": r.k, "label": "Not recorded" if r.k == "__none__" else r.k, "count": int(r.c)} for r in rows
	]


@frappe.whitelist()
def get_difference_summary(**kw):
	"""KPIs, per-day chart and breakdowns for Field Difference Log (latest comparison per doctype)."""
	_require_differences()
	try:
		a = _d_args(kw)
		where, p = _d_where(a)
		tot = frappe.db.sql(
			f"""SELECT COUNT(*) AS n, COUNT(DISTINCT doctype_name) AS doctypes, MAX(comparison_time) AS last_at,
				SUM(status = 'New') AS new_n
			FROM `tab{DIFF}` WHERE {where}""",  # nosemgrep: frappe-sql-format-injection
			p,
			as_dict=True,
		)[0]
		dup = frappe.db.sql(
			f"""SELECT COALESCE(SUM(c - 1), 0) FROM (
				SELECT COUNT(*) AS c FROM `tab{DIFF}` WHERE {where}
				GROUP BY doctype_name, field_name, issue_type HAVING c > 1) x""",  # nosemgrep
			p,
		)[0][0]
		day_rows = frappe.db.sql(
			f"""SELECT DATE(comparison_time) AS d, COUNT(*) AS c FROM `tab{DIFF}`
			WHERE {where} GROUP BY d""",  # nosemgrep: frappe-sql-format-injection
			p,
			as_dict=True,
		)
		per_day = {_iso(r.d): int(r.c) for r in day_rows}
		by_day = [{"date": _iso(d), "total": per_day.get(_iso(d), 0)} for d in _days(a["from"], a["to"])]
		docs = _dgroup(a, "doctype_name")
		od = {
			"from": a["from"],
			"to": a["to"],
			"all_time": a["all_time"],
			"issue_type": "",
			"status": "",
			"doctype": "",
			"user": "",
			"search": "",
		}
		ow, op = _d_where(od)
		doctypes = frappe.db.sql(
			f"""SELECT DISTINCT doctype_name FROM `tab{DIFF}` WHERE {ow} AND IFNULL(doctype_name,'') <> ''
			ORDER BY doctype_name LIMIT {OPTION_LIMIT}""",  # nosemgrep: frappe-sql-format-injection
			op,
			pluck="doctype_name",
		)
		return {
			"success": True,
			"range": _range_out(a),
			"totals": {
				"differences": int(tot.n or 0),
				"new": int(tot.new_n or 0),
				"doctypes": int(tot.doctypes or 0),
				"duplicates": int(dup or 0),
				"last_at": str(tot.last_at) if tot.last_at else None,
			},
			"by_day": by_day,
			"by_issue_type": sorted(_dgroup(a, "issue_type"), key=lambda r: -r["count"]),
			"by_status": sorted(_dgroup(a, "status"), key=lambda r: -r["count"]),
			"by_doctype": _top(docs, "key", TOP_DOCTYPES, "{n} other doctypes"),
			"options": {"doctypes": doctypes},
		}
	except frappe.PermissionError:
		raise
	except Exception:
		frappe.log_error(title="Activity Log v2: difference summary")
		return _fail(_("The differences could not be loaded. Please try again."))


def _password_fields(pairs):
	"""Subset of (doctype, fieldname) pairs whose field is defined as type Password."""
	pairs = list({p for p in pairs if p[0] and p[1]})
	hidden = set()
	for i in range(0, len(pairs), 200):
		chunk = pairs[i : i + 200]
		flat = [x for p in chunk for x in p]
		ph = ", ".join(["(%s, %s)"] * len(chunk))
		for table, parent_col in (("DocField", "parent"), ("Custom Field", "dt")):
			for r in frappe.db.sql(
				f"""SELECT {parent_col}, fieldname FROM `tab{table}`
				WHERE fieldtype = 'Password' AND ({parent_col}, fieldname) IN ({ph})""",  # nosemgrep
				flat,
			):
				hidden.add((r[0], r[1]))
	return hidden


def _safe_value(value, doctype, field, pw, limit):
	if value is None or value == "":
		return value, False
	if SENSITIVE_NAME.search(field or "") or (doctype, field) in pw:
		return HIDDEN, True
	return _scrub(str(value))[:limit], False


_D_FIELDS = "name, comparison_time, doctype_name, field_name, issue_type, status, source_snapshot, owner"


@frappe.whitelist()
def get_difference_list(start=0, limit=50, **kw):
	"""One page of differences (no values; open an entry to see before/after)."""
	_require_differences()
	try:
		a = _d_args(kw)
		where, p = _d_where(a)
		start = min(max(0, cint(start)), MAX_START)
		limit = max(1, min(cint(limit) or 50, PAGE_MAX))
		rows = frappe.db.sql(
			f"""SELECT {_D_FIELDS} FROM `tab{DIFF}` WHERE {where}
			ORDER BY comparison_time DESC, doctype_name, field_name, name LIMIT %(start)s, %(limit)s""",  # nosemgrep
			{**p, "start": start, "limit": limit},
			as_dict=True,
		)
		total = frappe.db.sql(f"SELECT COUNT(*) FROM `tab{DIFF}` WHERE {where}", p)[0][0]  # nosemgrep
		names = _user_names([r.owner for r in rows])
		pw = _password_fields([(r.doctype_name, r.field_name) for r in rows])
		out = [
			{
				**r,
				"comparison_time": str(r.comparison_time) if r.comparison_time else None,
				"user_name": names.get(r.owner) or r.owner or "",
				"redacted": bool(
					SENSITIVE_NAME.search(r.field_name or "") or (r.doctype_name, r.field_name) in pw
				),
			}
			for r in rows
		]
		return {"success": True, "rows": out, "total": int(total), "start": start, "limit": limit}
	except Exception:
		frappe.log_error(title="Activity Log v2: difference list")
		return _fail(_("The differences could not be loaded. Please try again."))


@frappe.whitelist()
def get_difference_entry(name=None):
	"""One difference with its live (before) and local (after) values, secrets hidden."""
	_require_differences()
	name = (name or "").strip()
	row = frappe.db.get_value(
		DIFF,
		name,
		[
			"name",
			"comparison_time",
			"doctype_name",
			"field_name",
			"issue_type",
			"status",
			"source_snapshot",
			"live_value",
			"local_value",
			"owner",
		],
		as_dict=True,
	)
	if not row:
		return _fail(_("That entry was not found. It may have been replaced by a newer comparison."))
	pw = _password_fields([(row.doctype_name, row.field_name)])
	row["live_value"], hid1 = _safe_value(row.live_value, row.doctype_name, row.field_name, pw, VALUE_LIMIT)
	row["local_value"], hid2 = _safe_value(row.local_value, row.doctype_name, row.field_name, pw, VALUE_LIMIT)
	row["redacted"] = hid1 or hid2
	row["comparison_time"] = str(row.comparison_time) if row.comparison_time else None
	row["user_name"] = _user_names([row.owner]).get(row.owner) or row.owner or ""
	return {"success": True, "entry": row}


@frappe.whitelist()
def get_difference_export(**kw):
	"""CSV rows for the filtered differences, values hidden for secret-like fields."""
	_require_differences()
	try:
		a = _d_args(kw)
		where, p = _d_where(a)
		rows = frappe.db.sql(
			f"""SELECT {_D_FIELDS}, live_value, local_value FROM `tab{DIFF}` WHERE {where}
			ORDER BY comparison_time DESC, doctype_name, field_name, name LIMIT {EXPORT_LIMIT}""",  # nosemgrep
			p,
			as_dict=True,
		)
		total = frappe.db.sql(f"SELECT COUNT(*) FROM `tab{DIFF}` WHERE {where}", p)[0][0]  # nosemgrep
		pw = _password_fields([(r.doctype_name, r.field_name) for r in rows])
		for r in rows:
			r["live_value"], _h = _safe_value(r.live_value, r.doctype_name, r.field_name, pw, 1000)
			r["local_value"], _h = _safe_value(r.local_value, r.doctype_name, r.field_name, pw, 1000)
			r["comparison_time"] = str(r.comparison_time) if r.comparison_time else ""
		return {
			"success": True,
			"rows": rows,
			"total": int(total),
			"truncated": int(total) > len(rows),
			"row_limit": EXPORT_LIMIT,
		}
	except Exception:
		frappe.log_error(title="Activity Log v2: difference export")
		return _fail(_("The export could not be prepared. Please try again."))
