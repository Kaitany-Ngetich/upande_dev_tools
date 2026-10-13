# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
"""My Backlog v2 - "your open work and meetings", for the SIGNED-IN user only.

WHO / SCOPING (same as the current page, tightened)
    The current page calls api.requests.get_my_backlog() with no argument, i.e. the signed-in
    user. That function also accepts a `user` argument (allowed for Dev Team / Projects Manager /
    System Manager). These v2 endpoints take NO user argument at all: every query is built from
    frappe.session.user, so another person's items can never be requested.
    Access = the Dev Portal Page "my-backlog" role rule (portal._route_permits), the same rule
    the page controller enforces; guests are refused.

WHAT EACH NUMBER MEANS
    task assigned to me   Task whose `_assign` JSON list contains my user id EXACTLY. The current
                          code used `_assign LIKE %user%`, which also matches longer ids that
                          merely end with mine (ian@x.com matches brian@x.com). Here the match is
                          on the quoted JSON element, with LIKE wildcards in the id escaped.
                          `_assign` is the cache Frappe keeps of the open ToDo rows; ToDo is NOT
                          used as well (they would double count). Verified equal locally.
    open task             status not in (Completed, Cancelled, Template). Template rows are
                          blueprints, not work (the current page counted them).
    due date              Task.exp_end_date is a DATETIME (always 00:00:00 here); only its DATE
                          is used. "Today" is the SITE date (System Settings time zone), not the
                          browser's.
    overdue               due date < today, or (no due date and status = "Overdue"). The Task
                          status "Overdue" is set by a nightly job and never reset, so the date
                          wins over the status flag when there is a date.
    buckets (mutually exclusive, add up to OPEN):
                          overdue | today | this week (tomorrow .. today+6) | later (today+7 ..)
                          | no due date
    effective status      "Overdue" if overdue (above); a stale "Overdue" flag on a task whose date is
                          not past (rescheduled after the nightly job flagged it) reads as "Open";
                          otherwise the Task status. by_status adds up to OPEN.
    can_change_status     the signed-in user holds a role that api.requests.update_task_status accepts
                          (Dev Team / Projects Manager / System Manager). The page only offers status
                          changes then; the write itself is always that endpoint, which re-checks.
    age bands             open tasks by days since creation: <7, 7-13, 14-29, 30+ (same bands as the
                          current Progress tab; they add up to OPEN).
    completed             Task.status = Completed, assigned to me, on the day
                          COALESCE(completed_on, DATE(modified)). completed_on is empty on 44 of 45
                          completed tasks locally, so the current "completed this week" was nearly
                          always 0; falling back to the last-modified date is an approximation and
                          is flagged per row (`approx`).
    this week / last week the 7 days ending today / the 7 days before that (same as current page)
    my requests           Request.owner = me (any state). "In flight" = workflow_state in
                          ("", Under Review, Approved, Scheduled, In Progress, Deferred).
    meetings              Event not Closed/Cancelled with me as an Event Participant (email),
                          starting from the start of today up to `meeting_days` days ahead.
                          (The current page showed only the next 24 hours.)

FILTERS (all applied in SQL before the 5000-row safety cap, except the derived ones)
    project, module, priority, q (subject / id search)   -> tasks, completed, requests (project,
                          priority, q only; requests have no module)
    status (effective), due (bucket), from_date/to_date (due date range)  -> open tasks only
    Every KPI, chart and list follows these. Meetings follow none of them (a meeting is not a task).

IDENTITIES (checked in tests / by SQL)
    kpis.open = overdue + due_today + due_week + later + no_due_date = sum(by_status) = len(tasks)
    sum(due_chart) = tasks due today..today+13
    sum(done_chart) = completed_week + completed_prev_week
"""

import json
from datetime import date, datetime, timedelta

import frappe
from frappe import _
from frappe.utils import get_datetime, getdate, now_datetime

from upande_dev_tools import portal
from upande_dev_tools.api.requests import REVIEWER_ROLES

ROUTE = "my-backlog"
ROW_LIMIT = 5000
DONE_LIMIT = 100
CLOSED = ("Completed", "Cancelled", "Template")
REQUEST_OPEN_STATES = ("", "Under Review", "Approved", "Scheduled", "In Progress", "Deferred")
BUCKETS = ("overdue", "today", "week", "later", "none")
BUCKET_LABELS = {
	"overdue": "Overdue",
	"today": "Due today",
	"week": "Due this week",
	"later": "Due later",
	"none": "No due date",
}
STATUS_ORDER = ("Overdue", "Working", "Pending Review", "Open")
AGE_BANDS = (("Under a week", 7), ("1-2 weeks", 14), ("2-4 weeks", 30), ("Over a month", None))


# ---------------------------------------------------------------- access / helpers
def _me() -> str:
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Please sign in."), frappe.PermissionError)
	if not portal._route_permits("/" + ROUTE, set(frappe.get_roles(user))):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	return user


def _like_escape(s: str) -> str:
	return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _assigned_clause(user: str):
	"""SQL + params: `_assign` JSON list contains `user` exactly (quoted element match)."""
	return "t._assign LIKE %s", ['%"' + _like_escape(user) + '"%']


def _s(v) -> str:
	return str(v or "").strip()


def _day(v) -> date | None:
	return getdate(v) if v else None


def _iso(v) -> str | None:
	d = _day(v)
	return d.isoformat() if d else None


def _task_filters(kw: dict, user: str):
	"""WHERE fragments shared by open and completed task queries."""
	where, params = [], []
	clause, p = _assigned_clause(user)
	where.append(clause)
	params += p
	for key, col in (("project", "t.project"), ("module", "t.custom_module"), ("priority", "t.priority")):
		val = _s(kw.get(key))
		if val:
			if val == "__none__":
				where.append(f"COALESCE({col}, '') = ''")
			else:
				where.append(f"{col} = %s")
				params.append(val)
	q = _s(kw.get("q"))
	if q:
		where.append("(t.subject LIKE %s OR t.name LIKE %s)")
		like = "%" + _like_escape(q) + "%"
		params += [like, like]
	return where, params


def _bucket(due: date | None, status: str, today: date) -> str:
	if due is None:
		return "overdue" if status == "Overdue" else "none"
	if due < today:
		return "overdue"
	if due == today:
		return "today"
	if due <= today + timedelta(days=6):
		return "week"
	return "later"


def _effective_status(bucket: str, status: str) -> str:
	"""Status as the page shows it: the due date decides "Overdue", not the stale nightly flag."""
	if bucket == "overdue":
		return "Overdue"
	return "Open" if status == "Overdue" else status


def _age_bands(tasks: list[dict]) -> list[dict]:
	"""Count tasks into AGE_BANDS by `age_days` (each task in exactly one band)."""
	counts = [0] * len(AGE_BANDS)
	for t in tasks:
		for i, (_label, limit) in enumerate(AGE_BANDS):
			if limit is None or t["age_days"] < limit:
				counts[i] += 1
				break
	return [{"label": label, "count": counts[i]} for i, (label, _limit) in enumerate(AGE_BANDS)]


def _assignee_count(raw) -> int:
	try:
		return len(json.loads(raw)) if raw else 0
	except ValueError, TypeError:
		return 0


def _fetch_open(kw: dict, user: str, today: date):
	where, params = _task_filters(kw, user)
	where.append("t.status NOT IN %s")
	params.append(CLOSED)
	rows = frappe.db.sql(
		f"""SELECT t.name, t.subject, t.status, t.priority, t.project, t.custom_module AS module,
			t.exp_end_date, t.creation, t._assign
		FROM `tabTask` t WHERE {" AND ".join(where)}
		ORDER BY (t.exp_end_date IS NULL), t.exp_end_date, t.creation DESC
		LIMIT {ROW_LIMIT + 1}""",
		params,
		as_dict=True,
	)
	truncated = len(rows) > ROW_LIMIT
	out = []
	for r in rows[:ROW_LIMIT]:
		due = _day(r.exp_end_date)
		bucket = _bucket(due, r.status, today)
		out.append(
			{
				"name": r.name,
				"subject": r.subject,
				"status": r.status,
				"effective_status": _effective_status(bucket, r.status),
				"priority": r.priority or "",
				"project": r.project or "",
				"module": r.module or "",
				"due_date": due.isoformat() if due else None,
				"days_to_due": (due - today).days if due else None,
				"bucket": bucket,
				"created": _iso(r.creation),
				"age_days": max(0, (today - getdate(r.creation)).days),
				"assignees": _assignee_count(r._assign),
			}
		)
	return out, truncated


def _status_options() -> list[str]:
	"""Task.status Select options, the list update_task_status validates against."""
	return [o for o in frappe.get_meta("Task").get_field("status").options.split("\n") if o]


def _facets(user: str):
	"""Filter choices from the whole open backlog (not the filtered subset)."""
	clause, params = _assigned_clause(user)
	rows = frappe.db.sql(
		f"""SELECT t.project, t.custom_module AS module, t.priority FROM `tabTask` t
		WHERE {clause} AND t.status NOT IN %s GROUP BY t.project, t.custom_module, t.priority""",
		[*params, CLOSED],
		as_dict=True,
	)
	return {
		"projects": sorted({r.project for r in rows if r.project}),
		"modules": sorted({r.module for r in rows if r.module}),
		"priorities": sorted({r.priority for r in rows if r.priority}),
	}


def _fetch_completed(kw: dict, user: str, today: date):
	start = today - timedelta(days=13)
	where, params = _task_filters(kw, user)
	where.append("t.status = 'Completed'")
	where.append("COALESCE(t.completed_on, DATE(t.modified)) BETWEEN %s AND %s")
	params += [start, today]
	rows = frappe.db.sql(
		f"""SELECT t.name, t.subject, t.priority, t.project, t.custom_module AS module,
			COALESCE(t.completed_on, DATE(t.modified)) AS done_on, (t.completed_on IS NULL) AS approx
		FROM `tabTask` t WHERE {" AND ".join(where)}
		ORDER BY done_on DESC, t.modified DESC LIMIT {ROW_LIMIT}""",
		params,
		as_dict=True,
	)
	return [
		{
			"name": r.name,
			"subject": r.subject,
			"priority": r.priority or "",
			"project": r.project or "",
			"module": r.module or "",
			"done_on": getdate(r.done_on).isoformat(),
			"approx": bool(r.approx),
		}
		for r in rows
	]


def _fetch_requests(kw: dict, user: str):
	where, params = ["r.owner = %s"], [user]
	for key in ("project", "priority"):
		val = _s(kw.get(key))
		if val:
			where.append(f"r.{key} = %s")
			params.append(val)
	q = _s(kw.get("q"))
	if q:
		where.append("(r.title LIKE %s OR r.name LIKE %s)")
		like = "%" + _like_escape(q) + "%"
		params += [like, like]
	rows = frappe.db.sql(
		f"""SELECT r.name, r.title, r.request_type, r.workflow_state, r.priority, r.project,
			r.linked_task, r.creation
		FROM `tabRequest` r WHERE {" AND ".join(where)} ORDER BY r.creation DESC LIMIT {ROW_LIMIT}""",
		params,
		as_dict=True,
	)
	return [
		{
			"name": r.name,
			"title": r.title,
			"request_type": r.request_type or "",
			"state": r.workflow_state or "",
			"in_flight": (r.workflow_state or "") in REQUEST_OPEN_STATES,
			"priority": r.priority or "",
			"project": r.project or "",
			"linked_task": r.linked_task or "",
			"created": _iso(r.creation),
		}
		for r in rows
	]


def _fetch_meetings(user: str, days: int):
	now = now_datetime()
	start = datetime.combine(now.date(), datetime.min.time())
	end = start + timedelta(days=days + 1)
	rows = frappe.db.sql(
		"""SELECT e.name, e.subject, e.starts_on, e.ends_on, e.all_day, e.event_category, e.location,
			e.google_meet_link
		FROM `tabEvent` e
		WHERE COALESCE(e.status, 'Open') NOT IN ('Closed', 'Cancelled')
			AND e.starts_on >= %s AND e.starts_on < %s
			AND EXISTS (SELECT 1 FROM `tabEvent Participants` p
				WHERE p.parenttype = 'Event' AND p.parent = e.name AND p.email = %s)
		ORDER BY e.starts_on LIMIT 200""",
		(start, end, user),
		as_dict=True,
	)
	out = []
	for r in rows:
		s = get_datetime(r.starts_on)
		e = get_datetime(r.ends_on) if r.ends_on else None
		out.append(
			{
				"name": r.name,
				"subject": r.subject,
				"starts_on": s.strftime("%Y-%m-%d %H:%M"),
				"ends_on": e.strftime("%Y-%m-%d %H:%M") if e else None,
				"date": s.date().isoformat(),
				"all_day": bool(r.all_day),
				"category": r.event_category or "",
				"location": r.location or "",
				"link": r.google_meet_link or "",
				"is_today": s.date() == now.date(),
				"started": bool(s < now and not r.all_day),
			}
		)
	return out


# ---------------------------------------------------------------- endpoints
@frappe.whitelist()
def get_my_backlog(
	project=None,
	module=None,
	priority=None,
	status=None,
	due=None,
	q=None,
	from_date=None,
	to_date=None,
	meeting_days=7,
):
	"""Everything open for the signed-in user, rolled up on the server. See module docstring."""
	try:
		user = _me()
		kw = {"project": project, "module": module, "priority": priority, "q": q}
		today = getdate()
		try:
			mdays = min(max(int(meeting_days or 7), 1), 30)
		except TypeError, ValueError:
			mdays = 7

		tasks, truncated = _fetch_open(kw, user, today)
		status, due = _s(status), _s(due)
		f_from, f_to = _day(from_date), _day(to_date)
		if status:
			tasks = [t for t in tasks if t["effective_status"] == status]
		if due in BUCKETS:
			tasks = [t for t in tasks if t["bucket"] == due]
		if f_from or f_to:
			tasks = [
				t
				for t in tasks
				if t["due_date"]
				and (not f_from or t["due_date"] >= f_from.isoformat())
				and (not f_to or t["due_date"] <= f_to.isoformat())
			]

		# Overdue first (oldest due date first), then by due date, undated last.
		def sort_key(t):
			return (t["due_date"] is None, t["due_date"] or "", t["subject"] or "")

		tasks.sort(key=sort_key)

		counts = dict.fromkeys(BUCKETS, 0)
		by_status = {}
		by_priority = {}
		by_module = {}
		due_by_day = {}
		for t in tasks:
			counts[t["bucket"]] += 1
			by_status[t["effective_status"]] = by_status.get(t["effective_status"], 0) + 1
			by_priority[t["priority"] or "No priority"] = (
				by_priority.get(t["priority"] or "No priority", 0) + 1
			)
			by_module[t["module"] or "No module"] = by_module.get(t["module"] or "No module", 0) + 1
			if t["due_date"]:
				due_by_day[t["due_date"]] = due_by_day.get(t["due_date"], 0) + 1

		completed = _fetch_completed(kw, user, today)
		week_start = today - timedelta(days=6)
		done_by_day = {}
		this_week = prev_week = 0
		for c in completed:
			done_by_day[c["done_on"]] = done_by_day.get(c["done_on"], 0) + 1
			if getdate(c["done_on"]) >= week_start:
				this_week += 1
			else:
				prev_week += 1

		requests = _fetch_requests(kw, user)
		meetings = _fetch_meetings(user, mdays)

		due_chart = []
		done_chart = []
		for i in range(14):
			d = today + timedelta(days=i)
			due_chart.append({"date": d.isoformat(), "count": due_by_day.get(d.isoformat(), 0)})
			p = today - timedelta(days=13 - i)
			done_chart.append({"date": p.isoformat(), "count": done_by_day.get(p.isoformat(), 0)})

		open_total = len(tasks)
		return {
			"success": True,
			"today": today.isoformat(),
			"can_change_status": bool(set(frappe.get_roles(user)) & REVIEWER_ROLES),
			"status_options": _status_options(),
			"kpis": {
				"open": open_total,
				"overdue": counts["overdue"],
				"due_today": counts["today"],
				"due_week": counts["week"],
				"later": counts["later"],
				"no_due_date": counts["none"],
				"completed_week": this_week,
				"completed_prev_week": prev_week,
				"requests_in_flight": sum(1 for r in requests if r["in_flight"]),
				"requests_total": len(requests),
				"meetings": len(meetings),
				"meetings_today": sum(1 for m in meetings if m["is_today"]),
			},
			"buckets": [{"key": k, "label": BUCKET_LABELS[k], "count": counts[k]} for k in BUCKETS],
			"by_status": [{"label": s, "count": by_status[s]} for s in STATUS_ORDER if by_status.get(s)]
			+ [{"label": s, "count": n} for s, n in sorted(by_status.items()) if s not in STATUS_ORDER],
			"by_priority": [
				{"label": k, "count": v} for k, v in sorted(by_priority.items(), key=lambda x: -x[1])
			],
			"by_module": [
				{"label": k, "count": v} for k, v in sorted(by_module.items(), key=lambda x: -x[1])
			],
			"age_bands": _age_bands(tasks),
			"due_chart": due_chart,
			"done_chart": done_chart,
			"tasks": tasks,
			"completed": completed[:DONE_LIMIT],
			"completed_total": len(completed),
			"requests": requests,
			"meetings": meetings,
			"options": _facets(user),
			"truncated": truncated,
			"row_limit": ROW_LIMIT,
		}
	except frappe.PermissionError:
		raise
	except Exception:
		frappe.log_error(title="my_backlog_v2.get_my_backlog")
		return {"success": False, "error": "Could not load your backlog. Please try again."}


@frappe.whitelist()
def get_task_detail(name):
	"""One task, only if it is assigned to the signed-in user."""
	user = _me()
	name = _s(name)
	clause, params = _assigned_clause(user)
	row = frappe.db.sql(
		f"""SELECT t.name, t.subject, t.status, t.priority, t.project, t.custom_module AS module,
			t.exp_start_date, t.exp_end_date, t.creation, t.modified, t.completed_on, t.description,
			t.parent_task, t._assign
		FROM `tabTask` t WHERE t.name = %s AND {clause}""",
		[name, *params],
		as_dict=True,
	)
	if not row:
		return {"success": False, "error": "That task is not on your backlog."}
	t = row[0]
	today = getdate()
	due = _day(t.exp_end_date)
	requests = frappe.db.sql(
		"SELECT name, title, workflow_state FROM `tabRequest` WHERE linked_task = %s AND owner = %s",
		(t.name, user),
		as_dict=True,
	)
	return {
		"success": True,
		"task": {
			"name": t.name,
			"subject": t.subject,
			"status": t.status,
			"priority": t.priority or "",
			"project": t.project or "",
			"module": t.module or "",
			"start_date": _iso(t.exp_start_date),
			"due_date": due.isoformat() if due else None,
			"days_to_due": (due - today).days if due else None,
			"created": _iso(t.creation),
			"modified": str(t.modified)[:16],
			"completed_on": _iso(t.completed_on),
			"parent_task": t.parent_task or "",
			"assignees": _assignee_count(t._assign),
			"description": frappe.utils.strip_html(t.description or "")[:2000],
			"requests": [
				{"name": r.name, "title": r.title, "state": r.workflow_state or ""} for r in requests
			],
		},
	}


@frappe.whitelist()
def get_request_detail(name):
	"""One request, only if the signed-in user raised it."""
	user = _me()
	row = frappe.db.sql(
		"""SELECT name, title, request_type, workflow_state, priority, project, linked_task, source,
			creation, modified, description, resolution_notes
		FROM `tabRequest` WHERE name = %s AND owner = %s""",
		(_s(name), user),
		as_dict=True,
	)
	if not row:
		return {"success": False, "error": "That request is not one you raised."}
	r = row[0]
	return {
		"success": True,
		"request": {
			"name": r.name,
			"title": r.title,
			"request_type": r.request_type or "",
			"state": r.workflow_state or "",
			"priority": r.priority or "",
			"project": r.project or "",
			"linked_task": r.linked_task or "",
			"source": r.source or "",
			"created": _iso(r.creation),
			"modified": str(r.modified)[:16],
			"description": frappe.utils.strip_html(r.description or "")[:2000],
			"resolution_notes": r.resolution_notes or "",
		},
	}
