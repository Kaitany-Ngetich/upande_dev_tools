# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
"""PM Console (route pm-dashboard-v2) - a work console for the people who run the backlog.

Design rule: every number opens a list, every list row has an action, and a panel with no
decision or action does not exist. This module only READS. Every action the page offers
calls an existing whitelisted endpoint of api/requests.py (accept_request, triage_request,
reassign_task, update_task_status, promote_to_task); nothing is re-implemented here.

WHO MAY CALL THIS: a user with the Projects Manager or System Manager role
(portfolio.MANAGER_ROLES, imported, not copied), the same gate as api.portfolio.get_portfolio.
Every endpoint re-checks it (a whitelisted endpoint can be called without the page). The page is
additionally gated by the Dev Portal Page registry for the route `pm-dashboard`. Nothing here
writes or commits and no secret field is read.

PER-ROW `actions` (what the page may draw; the existing endpoints enforce the same rules again)
    task rows     reassign, due, done, pending : the caller holds a requests.REVIEWER_ROLES role
                  (reassign_task and update_task_status check exactly that)
    request rows  accept, defer, reject, schedule : the caller holds DECIDER_ROLE ("Projects
                  Manager"), because the Request Review workflow only lets that role take those
                  transitions (same rule as the Review Queue page). A System Manager without that
                  role sees the rows but no decision buttons.

SCOPE (the old PM Dashboard's definition)
    Portfolio    = Tasks whose Project has project_type "Dev Tools" and is not Cancelled.
                   Group (parent) tasks, Template and Cancelled tasks are never counted.
    Open task    = portfolio task whose status is not Completed.
    Today        = the site date (nowdate()) and server clock; ages are whole days.

WHAT IS COUNTED (one definition per number; the count strip, the tab counts and the lists
are the same list, so they can never disagree)
    Decide       = every Request in workflow_state "Under Review", with or without a project
                   (equals the Review Queue's "Waiting for a decision" tab). Oldest first. Age =
                   whole days since the request was created.
    Late         = open task whose due date (exp_end_date) is BEFORE today. Due today is not late.
                   A task with no due date is never late. Sorted by days late; the page groups it
                   by the FIRST person on the task (so a shared task is listed once).
    No owner     = open tasks with nobody in _assign, plus Requests in "Approved" with no linked
                   Task (approved, nobody scheduled or assigned it yet). Under Review requests
                   belong to Decide; Scheduled/In Progress requests are held through their Task.
    Gone quiet   = (the Stuck tab) tasks with status "Working" whose last change (DATE(modified))
                   is 14 or more days ago, plus Issues with status "On Hold" in the portfolio.
    People       = one row per user in Task._assign of an open task, or of a task finished in the
                   chosen days. SHARED-ASSIGNMENT RULE: a task assigned to two people counts for
                   both, so sum(people.open) = open assigned tasks + extra assignments. Delivered =
                   Completed tasks whose completion day is in the last N days (today included).
                   Completion day = the first of completed_on, act_end_date, DATE(modified), never
                   after today (few tasks record completed_on, so the fallback matters).
                   Due in 7 days = open, due date from today up to and including today + 7.
                   Carrying a lot = open > 2 x the median open count of the people with open work.
    Projects     = one row per portfolio project; open tasks of the rows add up to the open tasks
                   of the portfolio. Next due = earliest due date of an open task that is today or
                   later. Owner = the user who created the project (Project has no manager field).
                   Health is automatic: "worth a look" when MORE than 20% of the open tasks are
                   overdue, or (with open work) no task of the project changed for 14 days; else
                   "on track". The reason is returned in words.
    Weekly line  = per ISO week of the last 12 weeks, tasks raised (created) and delivered (completion
                   day), following the page filters.

FILTERS (all optional, all apply to every list): project (a portfolio project), area (Task
custom_module, else the linked Request's product_area), priority, assignee (a user in _assign; for
requests, requested_assignee or _assign). Issues follow project, area (custom_module), priority and
assignee the same way. With an assignee filter the People tab shows that person only.
"""

import json
from datetime import date, timedelta

import frappe
from frappe import _
from frappe.utils import add_days, getdate, now_datetime, nowdate, strip_html_tags

from upande_dev_tools.api.portfolio import MANAGER_ROLES
from upande_dev_tools.api.requests import REVIEWER_ROLES
from upande_dev_tools.setup import DEV_TOOLS_PROJECT_TYPE

ROW_LIMIT = 1000
STUCK_DAYS = 14
DUE_SOON_DAYS = 7
LATE_SHARE_LIMIT_PCT = 20  # health: amber when MORE than this share of open tasks is overdue
OVERLOAD_FACTOR = 2  # carrying a lot: open > this x the team median
WEEKS = 12
DELIVERED_DAYS = (7, 30, 90)
DEFAULT_DELIVERED_DAYS = 30
HISTORY_LIMIT = 30
DECIDER_ROLE = "Projects Manager"  # the Request Review workflow's role for Approve/Reject/Defer/Schedule
HISTORY_FIELDS = ("status", "priority", "exp_end_date", "subject", "workflow_state", "project")
ITEM_DOCTYPES = ("Task", "Request", "Issue")

# --- SQL fragments (alias t = Task, r = linked Request) ------------------------------------
T_FROM = "`tabTask` t LEFT JOIN `tabRequest` r ON r.name = t.custom_request"
AREA = "COALESCE(NULLIF(t.custom_module, ''), NULLIF(r.product_area, ''))"
OPEN = "t.status <> 'Completed'"
COMP = "(CASE WHEN t.status = 'Completed' THEN LEAST(COALESCE(t.completed_on, t.act_end_date, DATE(t.modified)), %(today)s) END)"
DUE = "DATE(t.exp_end_date)"
OVERDUE = f"({OPEN} AND {DUE} < %(today)s)"
UNASSIGNED = "(t._assign IS NULL OR t._assign IN ('', '[]'))"
ASSIGNEE_JOIN = (
	"JSON_TABLE(CASE WHEN JSON_VALID(t._assign) THEN IF(JSON_LENGTH(t._assign) > 0, t._assign, '[null]') "
	"ELSE '[null]' END, '$[*]' COLUMNS (who VARCHAR(140) PATH '$' NULL ON EMPTY)) jt"
)
TASK_COLS = (
	f"t.name, t.subject, t.status, t.priority, t.project, {AREA} AS area, t._assign, {DUE} AS due, "
	"DATE(t.modified) AS modified, t.custom_request AS request"
)
OPEN_PORTFOLIO = "t.project IN %(all_projects)s AND t.is_group = 0 AND t.status NOT IN ('Template', 'Cancelled', 'Completed')"


class _Bad(Exception):
	"""A request the caller can fix (bad filter); returned as {success: False, error}."""


# =========================================================================================
# Pure rules (unit tested in tests/test_pm_dashboard_v2.py)
# =========================================================================================


def is_overdue(due: date | None, today: date) -> bool:
	"""Due strictly before today. No due date is never overdue."""
	return due is not None and due < today


def days_late(due: date | None, today: date) -> int:
	return (today - due).days if is_overdue(due, today) else 0


def is_stuck(status: str, quiet_days: int) -> bool:
	"""In progress and unchanged for STUCK_DAYS or more days."""
	return status == "Working" and quiet_days >= STUCK_DAYS


def median(values: list) -> float | None:
	if not values:
		return None
	o = sorted(values)
	m = len(o) // 2
	return o[m] if len(o) % 2 else (o[m - 1] + o[m]) / 2


def carrying_a_lot(open_n: int, team_median: float | None) -> bool:
	"""More than OVERLOAD_FACTOR x the team median (people with open work only)."""
	return bool(team_median) and open_n > OVERLOAD_FACTOR * team_median


def project_health(open_n: int, overdue_n: int, last_change: date | None, today: date) -> dict:
	"""Automatic health. Amber ("watch") when more than LATE_SHARE_LIMIT_PCT percent of the open
	tasks are overdue, or when there is open work and nothing changed for STUCK_DAYS days."""
	if not open_n:
		return {"level": "good", "reason": "Nothing open"}
	reasons = []
	if overdue_n * 100 > open_n * LATE_SHARE_LIMIT_PCT:
		reasons.append(f"{overdue_n} of {open_n} open tasks are overdue ({round(overdue_n * 100 / open_n)}%)")
	if last_change is None or (today - last_change).days >= STUCK_DAYS:
		reasons.append(
			"nothing has changed for "
			+ (f"{(today - last_change).days} days" if last_change else "a long time")
		)
	if reasons:
		text = "; ".join(reasons)
		return {"level": "watch", "reason": text[0].upper() + text[1:]}
	return {"level": "good", "reason": f"{overdue_n} overdue of {open_n} open, recent activity"}


def week_start(day: date) -> date:
	return day - timedelta(days=day.weekday())


# =========================================================================================
# Helpers
# =========================================================================================


def _guard():
	if not set(frappe.get_roles()) & MANAGER_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)


def _wrap(fn):
	"""Permission check, then run; a handled problem comes back as {success: False}."""
	_guard()
	try:
		return fn()
	except _Bad as e:
		return {"success": False, "error": str(e)}


def _s(v) -> str:
	return str(v).strip() if v not in (None, "") else ""


def _q(sql, params=None):
	return frappe.db.sql(sql, params or {}, as_dict=True)


def _like_member(email: str) -> str:
	"""LIKE pattern matching `"email"` inside a JSON _assign list."""
	return '%"' + email.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + '"%'


def _who(raw) -> list[str]:
	try:
		v = json.loads(raw) if raw else []
	except TypeError, ValueError:
		return []
	return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []


def _names(emails) -> dict[str, str]:
	emails = [e for e in set(emails) if e]
	if not emails:
		return {}
	rows = frappe.get_all(
		"User", filters={"name": ["in", emails]}, fields=["name", "full_name"], ignore_permissions=True
	)
	return {r.name: r.full_name or r.name for r in rows}


def _iso(v):
	return str(v) if v else None


def _plain(html, limit=400) -> str:
	text = " ".join(strip_html_tags(html or "").split())
	return text if len(text) <= limit else text[: limit - 1] + "…"


def _age_days(created, now) -> int:
	return max(0, int((now - created).total_seconds() // 86400))


def _row_actions(kind: str, roles: set) -> list[str]:
	"""What the caller may do to a row of this kind (see the module docstring)."""
	if kind == "task":
		return ["reassign", "due", "done", "pending"] if roles & REVIEWER_ROLES else []
	if kind == "request":
		return ["accept", "defer", "reject"] if DECIDER_ROLE in roles else []
	if kind == "approved":
		return ["schedule"] if DECIDER_ROLE in roles else []
	return []


class _Filters:
	"""Validated filters and the SQL they translate to (parameters are always bound)."""

	def __init__(self, kw):
		self.today = getdate(nowdate())
		self.project = _s(kw.get("project"))
		self.area = _s(kw.get("area"))
		self.priority = _s(kw.get("priority"))
		self.assignee = _s(kw.get("assignee"))
		try:
			self.days = int(kw.get("days") or DEFAULT_DELIVERED_DAYS)
		except TypeError, ValueError:
			raise _Bad(_("Days must be a number.")) from None
		if self.days not in DELIVERED_DAYS:
			raise _Bad(_("Pick 7, 30 or 90 days."))
		self.project_rows = _q(
			"""SELECT name, project_name, owner FROM `tabProject`
			WHERE project_type = %s AND IFNULL(status, '') <> 'Cancelled' ORDER BY project_name""",
			(DEV_TOOLS_PROJECT_TYPE,),
		)
		self.all_projects = [p.name for p in self.project_rows]
		if self.project and self.project not in self.all_projects:
			raise _Bad(_("Unknown project."))
		self.projects = [self.project] if self.project else self.all_projects
		self.labels = {p.name: p.project_name or p.name for p in self.project_rows}

	def params(self, **extra):
		return {
			"today": self.today,
			"frm": add_days(self.today, 1 - self.days),
			"soon": add_days(self.today, DUE_SOON_DAYS),
			"projects": tuple(self.projects) or ("",),
			"all_projects": tuple(self.all_projects) or ("",),
			"project": self.project,
			"prio": self.priority,
			"area": self.area,
			"asg": _like_member(self.assignee),
			"asgu": self.assignee,
			**extra,
		}

	def task_where(self) -> str:
		c = ["t.project IN %(projects)s", "t.is_group = 0", "t.status NOT IN ('Template', 'Cancelled')"]
		if self.priority:
			c.append("t.priority = %(prio)s")
		if self.area:
			c.append(f"{AREA} = %(area)s")
		if self.assignee:
			c.append("t._assign LIKE %(asg)s")
		return " AND ".join(c)

	def request_where(self) -> str:
		c = ["1 = 1"]
		if self.project:
			c.append("r.project = %(project)s")
		if self.priority:
			c.append("r.priority = %(prio)s")
		if self.area:
			c.append("r.product_area = %(area)s")
		if self.assignee:
			c.append("(r.requested_assignee = %(asgu)s OR r._assign LIKE %(asg)s)")
		return " AND ".join(c)

	def issue_where(self) -> str:
		c = ["i.project IN %(projects)s", "i.status = 'On Hold'"]
		if self.priority:
			c.append("i.priority = %(prio)s")
		if self.area:
			c.append("i.custom_module = %(area)s")
		if self.assignee:
			c.append("i._assign LIKE %(asg)s")
		return " AND ".join(c)


def _task_rows(f: _Filters, extra: str, order: str, roles: set, **params) -> list[dict]:
	"""Task rows for a list, shaped for the page (names, days late, actions)."""
	rows = _q(
		f"SELECT {TASK_COLS} FROM {T_FROM} WHERE {f.task_where()} AND {extra} ORDER BY {order}, t.name LIMIT {ROW_LIMIT}",
		f.params(**params),
	)
	ids = {r.name: _who(r.pop("_assign")) for r in rows}
	people = _names({x for v in ids.values() for x in v})
	actions = _row_actions("task", roles)
	return [
		{
			"kind": "task", "name": r.name, "title": r.subject, "status": r.status, "priority": r.priority,
			"project": r.project, "project_label": f.labels.get(r.project, r.project), "area": r.area,
			"assignee_ids": ids[r.name], "assignees": [people.get(x, x) for x in ids[r.name]],
			"due": _iso(r.due), "days_late": days_late(r.due, f.today), "modified": _iso(r.modified),
			"quiet_days": (f.today - r.modified).days, "request": r.request, "actions": actions,
		}
		for r in rows
	]  # fmt: skip


def _request_rows(f: _Filters, state_where: str, kind: str, roles: set) -> list[dict]:
	now = now_datetime()
	rows = _q(
		f"""SELECT r.name, r.title, r.request_type, r.product_area AS area, r.priority, r.project, r.owner,
			r.requested_assignee, r.creation FROM `tabRequest` r
		WHERE {f.request_where()} AND {state_where} ORDER BY r.creation, r.name LIMIT {ROW_LIMIT}""",
		f.params(),
	)
	people = _names({x for r in rows for x in (r.owner, r.requested_assignee)})
	actions = _row_actions(kind, roles)
	return [
		{
			"kind": kind, "name": r.name, "title": r.title, "type": r.request_type, "area": r.area,
			"priority": r.priority, "project": r.project, "project_label": f.labels.get(r.project, r.project),
			"requester": people.get(r.owner, r.owner), "requested_for": r.requested_assignee,
			"created": _iso(r.creation.date()), "age_days": _age_days(r.creation, now), "actions": actions,
		}
		for r in rows
	]  # fmt: skip


# =========================================================================================
# Lists
# =========================================================================================


def _decide(f, roles):
	return _request_rows(f, "r.workflow_state = 'Under Review'", "request", roles)


def _late(f, roles):
	return _task_rows(f, OVERDUE, f"DATEDIFF(%(today)s, {DUE}) DESC", roles)


def _no_owner(f, roles):
	tasks = _task_rows(f, f"{OPEN} AND {UNASSIGNED}", f"({DUE} IS NULL), {DUE}, t.creation", roles)
	approved = _request_rows(
		f, "r.workflow_state = 'Approved' AND IFNULL(r.linked_task, '') = ''", "approved", roles
	)
	return tasks + approved


def _stuck(f, roles):
	working = _task_rows(f, "t.status = 'Working'", "t.modified", roles)
	tasks = [t for t in working if is_stuck(t["status"], t["quiet_days"])]
	issues = _q(
		f"""SELECT i.name, i.subject, i.project, i.priority, i.custom_module AS area, i._assign,
			DATE(i.modified) AS modified FROM `tabIssue` i WHERE {f.issue_where()}
		ORDER BY i.modified LIMIT {ROW_LIMIT}""",
		f.params(),
	)
	ids = {i.name: _who(i.pop("_assign")) for i in issues}
	people = _names({x for v in ids.values() for x in v})
	return tasks + [
		{
			"kind": "issue", "name": i.name, "title": i.subject, "status": "On Hold", "priority": i.priority,
			"project": i.project, "project_label": f.labels.get(i.project, i.project), "area": i.area,
			"assignee_ids": ids[i.name], "assignees": [people.get(x, x) for x in ids[i.name]],
			"modified": _iso(i.modified), "quiet_days": (f.today - i.modified).days, "actions": [],
		}
		for i in issues
	]  # fmt: skip


def _people(f):
	rows = _q(
		f"""SELECT x.who, SUM(x.is_open) AS open_n, SUM(x.late) AS overdue_n, SUM(x.soon) AS soon_n,
			SUM(x.delivered) AS delivered_n
		FROM (SELECT DISTINCT t.name, jt.who AS who, ({OPEN}) AS is_open, IFNULL({OVERDUE}, 0) AS late,
				IFNULL(({OPEN} AND {DUE} BETWEEN %(today)s AND %(soon)s), 0) AS soon,
				IFNULL(({COMP} BETWEEN %(frm)s AND %(today)s), 0) AS delivered
			FROM {T_FROM} JOIN {ASSIGNEE_JOIN}
			WHERE {f.task_where()} AND jt.who IS NOT NULL {"AND jt.who = %(asgu)s" if f.assignee else ""}
				AND ({OPEN} OR {COMP} BETWEEN %(frm)s AND %(today)s)) x
		GROUP BY x.who""",
		f.params(),
	)
	names = _names([r.who for r in rows])
	people = [
		{
			"user": r.who, "name": names.get(r.who, r.who), "open": int(r.open_n or 0), "overdue": int(r.overdue_n or 0),
			"due_soon": int(r.soon_n or 0), "delivered": int(r.delivered_n or 0),
		}
		for r in rows
	]  # fmt: skip
	team_median = median([p["open"] for p in people if p["open"]])
	for p in people:
		p["heavy"] = carrying_a_lot(p["open"], team_median)
	people.sort(key=lambda p: (-p["open"], p["name"]))
	return {"rows": people, "median_open": team_median}


def _projects(f):
	rows = {
		r.project: r
		for r in _q(
			f"""SELECT t.project, SUM({OPEN}) AS open_n, IFNULL(SUM({OVERDUE}), 0) AS overdue_n,
				SUM(t.status = 'Completed') AS done_n,
				MIN(CASE WHEN {OPEN} AND {DUE} >= %(today)s THEN {DUE} END) AS next_due,
				MAX(DATE(t.modified)) AS last_change
			FROM {T_FROM} WHERE {f.task_where()} GROUP BY t.project""",
			f.params(),
		)
	}
	owners = _names([p.owner for p in f.project_rows])
	out = []
	for p in f.project_rows:
		if p.name not in f.projects:
			continue
		r = rows.get(p.name)
		open_n, late = (int(r.open_n or 0), int(r.overdue_n or 0)) if r else (0, 0)
		last = r.last_change if r else None
		out.append(
			{
				"project": p.name, "label": f.labels[p.name], "owner": owners.get(p.owner, p.owner),
				"open": open_n, "overdue": late, "done": int(r.done_n or 0) if r else 0,
				"next_due": _iso(r.next_due) if r else None, "last_change": _iso(last),
				"health": project_health(open_n, late, last, f.today),
			}
		)  # fmt: skip
	out.sort(key=lambda x: (x["health"]["level"] != "watch", -x["open"], x["label"]))
	return out


def _weekly(f):
	"""Raised vs delivered for each of the last WEEKS ISO weeks (the current week is partial)."""
	first = week_start(f.today) - timedelta(weeks=WEEKS - 1)
	wk = "DATE_SUB(DATE({0}), INTERVAL WEEKDAY({0}) DAY)"
	raised = {
		r.wk: int(r.n)
		for r in _q(
			f"""SELECT {wk.format("t.creation")} AS wk, COUNT(*) AS n FROM {T_FROM}
			WHERE {f.task_where()} AND DATE(t.creation) >= %(first)s GROUP BY wk""",
			f.params(first=first),
		)
	}
	done = {
		r.wk: int(r.n)
		for r in _q(
			f"""SELECT {wk.format(COMP)} AS wk, COUNT(*) AS n FROM {T_FROM}
			WHERE {f.task_where()} AND {COMP} >= %(first)s GROUP BY wk""",
			f.params(first=first),
		)
	}
	weeks = [first + timedelta(weeks=i) for i in range(WEEKS)]
	return [{"week": str(w), "raised": raised.get(w, 0), "delivered": done.get(w, 0)} for w in weeks]


def _options(f):
	"""Filter choices from the whole portfolio, unfiltered, so a choice never disappears."""
	p = f.params()
	areas = {
		r.a
		for r in _q(
			f"""SELECT {AREA} AS a FROM {T_FROM} WHERE {OPEN_PORTFOLIO} GROUP BY a
			UNION SELECT product_area FROM `tabRequest` WHERE workflow_state IN ('Under Review', 'Approved')""",
			p,
		)
		if r.a
	}
	who = [
		r.who
		for r in _q(
			f"SELECT DISTINCT jt.who FROM {T_FROM} JOIN {ASSIGNEE_JOIN} WHERE {OPEN_PORTFOLIO} AND jt.who IS NOT NULL",
			p,
		)
	]
	names = _names(who)
	levels = frappe.db.sql(
		"SELECT name FROM `tabPriority Level` WHERE IFNULL(disabled, 0) = 0 ORDER BY sort_order"
	)
	return {
		"projects": [{"value": k, "label": v} for k, v in f.labels.items()],
		"areas": sorted(areas),
		"priorities": [x[0] for x in levels],
		"assignees": sorted(
			({"value": w, "label": names.get(w, w)} for w in who), key=lambda x: x["label"].lower()
		),
	}


# =========================================================================================
# Public endpoints
# =========================================================================================


@frappe.whitelist()
def get_pm_console(project=None, area=None, priority=None, assignee=None, days=None):
	"""Every list the console shows, for one filter state, in one read. The counts are the list
	lengths (`truncated` names a list that hit ROW_LIMIT, in which case its count is the limit)."""
	kw = {"project": project, "area": area, "priority": priority, "assignee": assignee, "days": days}

	def run():
		f = _Filters(kw)
		roles = set(frappe.get_roles())
		out = {
			"success": True, "today": str(f.today), "days": f.days, "decide": _decide(f, roles),
			"late": _late(f, roles), "no_owner": _no_owner(f, roles), "stuck": _stuck(f, roles),
			"people": _people(f), "projects": _projects(f), "weekly": _weekly(f), "options": _options(f),
			"can_act": bool(roles & REVIEWER_ROLES), "can_decide": DECIDER_ROLE in roles,
		}  # fmt: skip
		out["counts"] = {k: len(out[k]) for k in ("decide", "late", "no_owner", "stuck", "projects")}
		out["counts"]["people"] = len(out["people"]["rows"])
		out["truncated"] = [k for k, n in out["counts"].items() if n >= ROW_LIMIT]
		return out

	return _wrap(run)


@frappe.whitelist()
def get_pm_person_tasks(person, project=None, area=None, priority=None):
	"""A person's open portfolio tasks (the rows behind a People line), same filters as the console."""
	person = _s(person)

	def run():
		if not person:
			raise _Bad(_("Pick a person."))
		f = _Filters({"project": project, "area": area, "priority": priority})
		rows = _task_rows(
			f,
			f"{OPEN} AND t._assign LIKE %(who)s",
			f"({DUE} IS NULL), {DUE}",
			set(frappe.get_roles()),
			who=_like_member(person),
		)
		return {"success": True, "person": person, "rows": [r for r in rows if person in r["assignee_ids"]]}

	return _wrap(run)


@frappe.whitelist()
def get_pm_item(doctype, name):
	"""The facts and history of one Task, Request or Issue for the drawer. A Task or Issue must belong
	to a portfolio project; a Request may have no project yet (that is the point of Decide)."""

	def run():
		if doctype not in ITEM_DOCTYPES:
			raise _Bad(_("Unknown item type."))
		f = _Filters({})
		doc = frappe.db.get_value(doctype, name, "*", as_dict=True)
		if not doc or (doctype != "Request" and doc.project not in f.all_projects):
			raise _Bad(_("Not found."))
		holders = _who(doc.get("_assign"))
		people = _names([*holders, doc.owner])
		facts = [
			("Status", doc.get("workflow_state") if doctype == "Request" else doc.status),
			("Priority", doc.priority),
			("Project", f.labels.get(doc.project, doc.project)),
		]
		if doctype == "Request":
			facts += [
				("Type", doc.request_type),
				("Product area", doc.product_area),
				("Raised by", people.get(doc.owner, doc.owner)),
				("Linked task", doc.linked_task),
			]
		else:
			facts.append(("Product area", doc.get("custom_module")))
		if doctype == "Task":
			facts += [
				("Due", _iso(getdate(doc.exp_end_date)) if doc.exp_end_date else None),
				("Linked request", doc.custom_request),
			]
		facts += [
			("Assigned to", ", ".join(people.get(x, x) for x in holders) or "Nobody"),
			("Created", _iso(doc.creation.date())),
			("Last changed", _iso(doc.modified.date())),
		]
		return {
			"success": True, "doctype": doctype, "name": name,
			"title": doc.title if doctype == "Request" else doc.subject,
			"facts": [[k, str(v)] for k, v in facts if v], "description": _plain(doc.get("description"), 1200),
			"history": _history(doctype, name, doc), "project": doc.project,
		}  # fmt: skip

	return _wrap(run)


def _history(doctype, name, doc):
	"""Newest first: creation, notes and workflow/assignment comments, and changes to a few fields."""
	events = [{"at": str(doc.creation), "text": f"{doctype} created", "by": doc.owner}]
	for c in _q(
		"""SELECT comment_type, content, comment_email, creation FROM tabComment
		WHERE reference_doctype = %s AND reference_name = %s
		AND comment_type IN ('Comment', 'Workflow', 'Assigned', 'Assignment Completed')
		ORDER BY creation DESC LIMIT %s""",
		(doctype, name, HISTORY_LIMIT),
	):
		label = {"Comment": "Note: ", "Workflow": "Moved to "}.get(c.comment_type, "")
		events.append({"at": str(c.creation), "text": label + _plain(c.content, 300), "by": c.comment_email})
	for v in _q(
		"SELECT creation, owner, data FROM tabVersion WHERE ref_doctype = %s AND docname = %s ORDER BY creation DESC LIMIT %s",
		(doctype, name, HISTORY_LIMIT),
	):
		try:
			changed = (json.loads(v.data) if v.data else {}).get("changed") or []
		except TypeError, ValueError:
			continue
		for ch in changed:
			if ch and ch[0] in HISTORY_FIELDS and len(ch) > 2:
				text = f"{ch[0].replace('_', ' ').capitalize()}: {ch[1] or 'empty'} to {ch[2] or 'empty'}"
				events.append({"at": str(v.creation), "text": text, "by": v.owner})
	events.sort(key=lambda e: e["at"], reverse=True)
	return events[:HISTORY_LIMIT]
