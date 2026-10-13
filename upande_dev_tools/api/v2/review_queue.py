# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
"""Review Queue v2 - read model for the requests waiting for a decision.

Source of truth: tabRequest (workflow_state), tabTask (the task an accepted request became),
Tag Link (tags), Comment/Version (history). Nothing here writes: every decision the page
makes calls the existing api.requests endpoints (accept_request, triage_request,
promote_to_task, reassign_task), which own validation, permissions and side effects. This
module only says which of those the caller may use on each row (`allowed_actions`), so the
page can hide the controls the endpoints would refuse.

WHO MAY READ (same as the current page and its endpoint)
- The current page /review-queue is open to the roles on its Dev Portal Page row
  (portal.enforce_page_access) and its endpoint get_review_queue (api/requests.py) throws
  unless the caller holds a REVIEWER_ROLES role. Every function here enforces BOTH.
- The current queue shows every "Under Review" request to those users - there is no per-row
  hiding (Requests are public inside the portal: api.requests.get_my_requests lists all of
  them to every user). So no row is filtered by owner/assignee; access is the role gate only.
- Never selected: description is only returned by the detail call, as plain text.

VIEWS (the four tabs) = groups of Request.workflow_state
- waiting   : Under Review            (the current queue - triage needed)
- approved  : Approved                (decided yes, not yet scheduled)
- deferred  : Deferred                (parked - revisit)
- scheduled : Scheduled, In Progress  (accepted; has a task with a "complete by" date)

AGE: whole days between Request.creation and "now" (server clock, site time zone - both are
stored in the same zone), floored, never negative. The current page does this in the
browser, so users in another time zone saw a different number.

IDENTITIES (verified in tests/ and by SQL, see report)
- counts of the four views add up to open_total (same non-status filters);
- by_priority, by_type and by_age_band each add up to totals.count;
- totals.count == len(rows) unless truncated is true;
- totals.over_week == by_age_band[week + fortnight].
"""

import json
import re

import frappe
from frappe import _
from frappe.utils import now_datetime

from upande_dev_tools import portal
from upande_dev_tools.api.requests import REVIEWER_ROLES

PAGE_ROUTE = "review-queue"
ROW_LIMIT = 500
# The Request Review workflow lets only this role take the Approve / Reject / Defer / Reopen /
# Schedule transitions (fixtures/workflow.json); Dev Team and System Manager alone cannot.
DECIDER_ROLE = "Projects Manager"
NONE = "__none__"

VIEWS = {
	"waiting": ("Under Review",),
	"approved": ("Approved",),
	"deferred": ("Deferred",),
	"scheduled": ("Scheduled", "In Progress"),
}
ALL_OPEN = tuple(s for states in VIEWS.values() for s in states)

# (key, label, lower bound in days); soft wording, no alarm.
AGE_BANDS = (
	("fresh", "Under 3 days", 0),
	("few", "3 to 6 days", 3),
	("week", "A week or more", 7),
	("fortnight", "Two weeks or more", 14),
)


# --------------------------------------------------------------------------- access
def allowed_actions(state: str, roles: set, has_task: bool) -> list[str]:
	"""Row actions the caller may take, by Request.workflow_state.

	Under Review : accept (approve + schedule + assign), approve (schedule later), defer, reject
	Approved     : schedule      Deferred : reopen
	Scheduled / In Progress with a Task : reassign (api.requests.reassign_task, REVIEWER_ROLES)
	The first four need the workflow role DECIDER_ROLE, so a reviewer without it gets none."""
	decides = DECIDER_ROLE in roles
	if state == "Under Review":
		return ["accept", "approve", "defer", "reject"] if decides else []
	if state == "Approved":
		return ["schedule"] if decides else []
	if state == "Deferred":
		return ["reopen"] if decides else []
	if state in ("Scheduled", "In Progress") and has_task and roles & REVIEWER_ROLES:
		return ["reassign"]
	return []


def _require_access() -> None:
	"""Same gate as the current page (Dev Portal Page roles) AND the current endpoint
	(REVIEWER_ROLES)."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	roles = set(frappe.get_roles())
	if not roles & REVIEWER_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	if not portal._route_permits(PAGE_ROUTE, roles):
		frappe.throw(_("Not permitted."), frappe.PermissionError)


def _fail(message: str) -> dict:
	return {"success": False, "error": message}


# --------------------------------------------------------------------------- helpers
def _age_days(creation, now) -> int:
	if not creation:
		return 0
	return max(0, int((now - creation).total_seconds() // 86400))


def _age_label(days: int) -> str:
	if days <= 0:
		return "Today"
	return "1 day" if days == 1 else f"{days} days"


def _age_band(days: int) -> str:
	band = AGE_BANDS[0][0]
	for key, _label, low in AGE_BANDS:
		if days >= low:
			band = key
	return band


def _plain(text, limit: int = 6000) -> str:
	"""Rich text -> plain text (descriptions and comments are HTML from the Text Editor)."""
	if not text:
		return ""
	text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", str(text))
	text = re.sub(r"<[^>]+>", "", text)
	text = (
		text.replace("&nbsp;", " ")
		.replace("&amp;", "&")
		.replace("&lt;", "<")
		.replace("&gt;", ">")
		.replace("&quot;", '"')
		.replace("&#39;", "'")
	)
	text = re.sub(r"\n{3,}", "\n\n", text).strip()
	return text[:limit]


def _where(args: dict, states: tuple, now) -> tuple[str, dict]:
	"""WHERE clause (alias r) for tabRequest. All user input goes in as parameters."""
	conds = ["r.workflow_state IN %(states)s"]
	p: dict = {"states": states, "now": now}

	def eq(field: str, key: str, value) -> None:
		if value == NONE:
			conds.append(f"(r.{field} IS NULL OR r.{field} = '')")
		elif value:
			conds.append(f"r.{field} = %({key})s")
			p[key] = value

	eq("priority", "priority", args.get("priority"))
	eq("request_type", "request_type", args.get("request_type"))
	eq("product_area", "product_area", args.get("product_area"))
	eq("project", "project", args.get("project"))
	eq("owner", "raised_by", args.get("raised_by"))
	eq("requested_assignee", "requested_for", args.get("requested_for"))

	tag = args.get("tag")
	if tag:
		conds.append(
			"EXISTS (SELECT 1 FROM `tabTag Link` tl WHERE tl.document_type = 'Request' "
			"AND tl.document_name = r.name AND tl.tag = %(tag)s)"
		)
		p["tag"] = tag

	q = (args.get("search") or "").strip()
	if q:
		like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
		conds.append(
			"(r.title LIKE %(q)s OR r.name LIKE %(q)s OR r.product_area LIKE %(q)s "
			"OR r.owner LIKE %(q)s OR r.request_type LIKE %(q)s)"
		)
		p["q"] = like

	try:
		min_age = int(args.get("min_age_days") or 0)
	except (TypeError, ValueError):
		min_age = 0
	if min_age > 0:
		conds.append("TIMESTAMPDIFF(SECOND, r.creation, %(now)s) >= %(min_age_s)s")
		p["min_age_s"] = min_age * 86400

	return " AND ".join(conds), p


def _users(names) -> dict:
	names = [n for n in set(names) if n]
	if not names:
		return {}
	rows = frappe.db.sql(
		"SELECT name, full_name FROM `tabUser` WHERE name IN %(n)s", {"n": names}, as_dict=True
	)
	return {r.name: r.full_name or r.name for r in rows}


def _assignees(raw) -> list[str]:
	try:
		value = json.loads(raw) if raw else []
	except ValueError:
		return []
	return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


# --------------------------------------------------------------------------- list
@frappe.whitelist()
def get_review_queue(
	view: str = "waiting",
	priority: str | None = None,
	request_type: str | None = None,
	product_area: str | None = None,
	project: str | None = None,
	tag: str | None = None,
	raised_by: str | None = None,
	requested_for: str | None = None,
	search: str | None = None,
	min_age_days: int | str | None = None,
) -> dict:
	"""Rows, KPIs and breakdowns for one view. Every number follows every filter; tab counts
	follow the filters too (except the view itself)."""
	_require_access()
	roles = set(frappe.get_roles())
	if view not in VIEWS:
		view = "waiting"
	args = {
		"priority": priority,
		"request_type": request_type,
		"product_area": product_area,
		"project": project,
		"tag": tag,
		"raised_by": raised_by,
		"requested_for": requested_for,
		"search": search,
		"min_age_days": min_age_days,
	}
	now = now_datetime()
	where_open, p_open = _where(args, ALL_OPEN, now)
	where, p = _where(args, VIEWS[view], now)

	age_s = "GREATEST(TIMESTAMPDIFF(SECOND, r.creation, %(now)s), 0)"

	# tab counts (same filters, all four views)
	state_counts = {
		r.workflow_state: r.n
		for r in frappe.db.sql(
			f"SELECT r.workflow_state, COUNT(*) AS n FROM tabRequest r WHERE {where_open} "
			"GROUP BY r.workflow_state",
			p_open,
			as_dict=True,
		)
	}
	counts = {k: sum(state_counts.get(s, 0) for s in states) for k, states in VIEWS.items()}

	# totals / breakdowns for the selected view (full filtered set)
	t = frappe.db.sql(
		f"""SELECT COUNT(*) AS n,
		        COALESCE(MAX({age_s}), 0) AS max_s,
		        COALESCE(AVG({age_s}), 0) AS avg_s,
		        COALESCE(SUM({age_s} >= 7 * 86400), 0) AS over_week,
		        COALESCE(SUM(r.priority IS NULL OR r.priority = ''), 0) AS no_priority,
		        COALESCE(SUM(r.project IS NULL OR r.project = ''), 0) AS no_project
		   FROM tabRequest r WHERE {where}""",
		p,
		as_dict=True,
	)[0]
	by_priority = frappe.db.sql(
		f"""SELECT COALESCE(NULLIF(r.priority, ''), %(none)s) AS k, COUNT(*) AS n
		    FROM tabRequest r WHERE {where} GROUP BY k""",
		{**p, "none": NONE},
		as_dict=True,
	)
	by_type = frappe.db.sql(
		f"""SELECT COALESCE(NULLIF(r.request_type, ''), %(none)s) AS k, COUNT(*) AS n
		    FROM tabRequest r WHERE {where} GROUP BY k ORDER BY n DESC, k""",
		{**p, "none": NONE},
		as_dict=True,
	)
	by_band = frappe.db.sql(
		f"""SELECT CASE WHEN {age_s} >= 14 * 86400 THEN 'fortnight'
		              WHEN {age_s} >= 7 * 86400 THEN 'week'
		              WHEN {age_s} >= 3 * 86400 THEN 'few' ELSE 'fresh' END AS k,
		       COUNT(*) AS n
		    FROM tabRequest r WHERE {where} GROUP BY k""",
		p,
		as_dict=True,
	)

	rank = {
		r.name: r.sort_order
		for r in frappe.db.sql("SELECT name, sort_order FROM `tabPriority Level`", as_dict=True)
	}
	prio_rows = [
		{"key": r.k, "label": "Not set" if r.k == NONE else r.k, "count": int(r.n)} for r in by_priority
	]
	prio_rows.sort(key=lambda x: (x["key"] == NONE, -rank.get(x["key"], -1)))
	band_n = {r.k: int(r.n) for r in by_band}

	# rows: oldest first (longest wait on top); row_limit applied after filtering
	rows = frappe.db.sql(
		f"""SELECT r.name, r.title, r.request_type, r.priority, r.workflow_state, r.product_area,
		        r.project, pr.project_name, r.owner, r.requested_assignee, r.raised_by_employee,
		        e.employee_name, e.user_id AS employee_user, r.creation, r.source, r.linked_task,
		        t.status AS task_status, t.exp_end_date AS task_due, t._assign AS task_assign
		   FROM tabRequest r
		   LEFT JOIN tabProject pr ON pr.name = r.project
		   LEFT JOIN tabEmployee e ON e.name = r.raised_by_employee
		   LEFT JOIN tabTask t ON t.name = r.linked_task
		   WHERE {where}
		   ORDER BY r.creation ASC, r.name ASC
		   LIMIT {ROW_LIMIT + 1}""",
		p,
		as_dict=True,
	)
	truncated = len(rows) > ROW_LIMIT
	rows = rows[:ROW_LIMIT]
	names = [r.name for r in rows]

	tags: dict = {}
	stage_since: dict = {}
	if names:
		for r in frappe.db.sql(
			"SELECT document_name, tag FROM `tabTag Link` WHERE document_type='Request' "
			"AND document_name IN %(n)s ORDER BY tag",
			{"n": names},
			as_dict=True,
		):
			tags.setdefault(r.document_name, []).append(r.tag)
		# when it entered its current state: latest Workflow comment naming that state
		for r in frappe.db.sql(
			"""SELECT c.reference_name AS name, c.content, MAX(c.creation) AS at
			   FROM tabComment c
			   WHERE c.reference_doctype='Request' AND c.comment_type='Workflow'
			     AND c.reference_name IN %(n)s GROUP BY c.reference_name, c.content""",
			{"n": names},
			as_dict=True,
		):
			stage_since[(r.name, r.content)] = r.at

	people = _users(
		[r.owner for r in rows]
		+ [r.requested_assignee for r in rows]
		+ [a for r in rows for a in _assignees(r.task_assign)]
	)

	out = []
	for r in rows:
		days = _age_days(r.creation, now)
		on_behalf = bool(r.employee_name and r.employee_user != r.owner)
		out.append(
			{
				"name": r.name,
				"title": r.title,
				"request_type": r.request_type or "",
				"priority": r.priority or "",
				"priority_rank": rank.get(r.priority, -1) if r.priority else -2,
				"status": r.workflow_state,
				"product_area": r.product_area or "",
				"project": r.project or "",
				"project_name": r.project_name or r.project or "",
				"raised_by": r.owner,
				"raised_by_name": people.get(r.owner, r.owner),
				"raised_for": r.employee_name if on_behalf else "",
				"requested_for": r.requested_assignee or "",
				"requested_for_name": people.get(r.requested_assignee, r.requested_assignee or ""),
				"source": r.source or "",
				"tags": tags.get(r.name, []),
				"creation": str(r.creation),
				"age_days": days,
				"age_label": _age_label(days),
				"age_band": _age_band(days),
				"stage_since": str(stage_since[(r.name, r.workflow_state)])
				if (r.name, r.workflow_state) in stage_since
				else "",
				"task": r.linked_task or "",
				"task_status": r.task_status or "",
				"due": str(r.task_due)[:10] if r.task_due else "",
				"assignees": [people.get(a, a) for a in _assignees(r.task_assign)],
				"assignee_ids": _assignees(r.task_assign),
				"scheduled_without_task": r.workflow_state == "Scheduled" and not r.linked_task,
				"actions": allowed_actions(r.workflow_state, roles, bool(r.linked_task)),
			}
		)

	n = int(t.n)
	max_days = int(t.max_s // 86400)
	return {
		"success": True,
		"view": view,
		"counts": counts,
		"open_total": sum(counts.values()),
		"totals": {
			"count": n,
			"longest_days": max_days,
			"average_days": round(float(t.avg_s) / 86400, 1),
			"over_week": int(t.over_week),
			"no_priority": int(t.no_priority),
			"no_project": int(t.no_project),
			"scheduled_without_task": sum(1 for r in out if r["scheduled_without_task"]),
		},
		"by_priority": prio_rows,
		"by_type": [
			{"key": r.k, "label": "Not set" if r.k == NONE else r.k, "count": int(r.n)} for r in by_type
		],
		"by_age_band": [
			{"key": k, "label": label, "min_days": low, "count": band_n.get(k, 0)}
			for k, label, low in AGE_BANDS
		],
		"rows": out,
		"can_decide": DECIDER_ROLE in roles,
		"truncated": truncated,
		"row_limit": ROW_LIMIT,
		"as_of": str(now)[:19],
	}


@frappe.whitelist()
def get_review_queue_options() -> dict:
	"""Filter choices from the open requests (all four views), unfiltered, so a choice never
	disappears because another filter is on."""
	_require_access()
	ph = {"s": ALL_OPEN}
	base = "FROM tabRequest r WHERE r.workflow_state IN %(s)s"

	def distinct(col: str) -> list[str]:
		return [
			x[0]
			for x in frappe.db.sql(
				f"SELECT DISTINCT r.{col} {base} AND r.{col} IS NOT NULL AND r.{col} <> '' ORDER BY 1",
				ph,
			)
		]

	owners = distinct("owner")
	requested = distinct("requested_assignee")
	people = _users(owners + requested)
	projects = frappe.db.sql(
		"SELECT DISTINCT r.project AS value, COALESCE(p.project_name, r.project) AS label "
		"FROM tabRequest r LEFT JOIN tabProject p ON p.name = r.project "
		"WHERE r.workflow_state IN %(s)s AND r.project IS NOT NULL AND r.project <> '' ORDER BY label",
		ph,
		as_dict=True,
	)
	tag_rows = [
		x[0]
		for x in frappe.db.sql(
			"SELECT DISTINCT tl.tag FROM `tabTag Link` tl JOIN tabRequest r ON r.name = tl.document_name "
			"WHERE tl.document_type = 'Request' AND r.workflow_state IN %(s)s ORDER BY tl.tag",
			ph,
		)
	]
	levels = frappe.db.sql(
		"SELECT name FROM `tabPriority Level` WHERE COALESCE(disabled, 0) = 0 ORDER BY sort_order",
		as_list=True,
	)
	priorities = [x[0] for x in levels]
	decision_priorities = list(priorities)  # what a decision may set: enabled levels only
	for extra in distinct("priority"):  # a level that was later disabled but is still in use
		if extra not in priorities:
			priorities.append(extra)
	return {
		"success": True,
		"priorities": priorities,
		"decision_priorities": decision_priorities,
		"request_types": distinct("request_type"),
		"product_areas": distinct("product_area"),
		"projects": [{"value": p.value, "label": p.label} for p in projects],
		"tags": tag_rows,
		"raised_by": [{"value": o, "label": people.get(o, o)} for o in owners],
		"requested_for": [{"value": o, "label": people.get(o, o)} for o in requested],
	}


# --------------------------------------------------------------------------- detail
@frappe.whitelist()
def get_request_detail(name: str) -> dict:
	"""One request with its decision history. Same audience as the queue."""
	_require_access()
	if not name or not frappe.db.exists("Request", name):
		return _fail("That request could not be found. It may have been deleted.")
	now = now_datetime()
	r = frappe.db.sql(
		"""SELECT r.name, r.title, r.description, r.request_type, r.priority, r.workflow_state,
		        r.product_area, r.project, pr.project_name, r.owner, r.requested_assignee,
		        r.raised_by_employee, e.employee_name, e.user_id AS employee_user, r.creation,
		        r.modified, r.source, r.linked_task
		   FROM tabRequest r
		   LEFT JOIN tabProject pr ON pr.name = r.project
		   LEFT JOIN tabEmployee e ON e.name = r.raised_by_employee
		   WHERE r.name = %s""",
		(name,),
		as_dict=True,
	)[0]

	task = None
	if r.linked_task:
		task = frappe.db.sql(
			"SELECT name, subject, status, priority, exp_end_date, completed_on, _assign "
			"FROM tabTask WHERE name = %s",
			(r.linked_task,),
			as_dict=True,
		)
		task = task[0] if task else None

	tags = [
		x[0]
		for x in frappe.db.sql(
			"SELECT tag FROM `tabTag Link` WHERE document_type='Request' AND document_name=%s ORDER BY tag",
			(name,),
		)
	]

	events = [
		{
			"at": str(r.creation),
			"kind": "raised",
			"title": "Request raised",
			"by": r.owner,
			"text": "",
		}
	]
	for c in frappe.db.sql(
		"""SELECT comment_type, content, comment_email, creation FROM tabComment
		   WHERE reference_doctype='Request' AND reference_name=%s
		     AND comment_type IN ('Comment','Workflow','Assigned','Assignment Completed')
		   ORDER BY creation LIMIT 200""",
		(name,),
		as_dict=True,
	):
		if c.comment_type == "Workflow":
			events.append(
				{
					"at": str(c.creation),
					"kind": "decision",
					"title": f"Moved to {_plain(c.content, 80)}",
					"by": c.comment_email,
					"text": "",
				}
			)
		elif c.comment_type == "Comment":
			events.append(
				{
					"at": str(c.creation),
					"kind": "note",
					"title": "Note or reason",
					"by": c.comment_email,
					"text": _plain(c.content, 2000),
				}
			)
		else:
			events.append(
				{
					"at": str(c.creation),
					"kind": "assign",
					"title": _plain(c.content, 200),
					"by": c.comment_email,
					"text": "",
				}
			)
	labels = {
		"priority": "Priority",
		"project": "Project",
		"product_area": "Product area",
		"request_type": "Type",
		"title": "Title",
	}
	for v in frappe.db.sql(
		"SELECT owner, creation, data FROM tabVersion WHERE ref_doctype='Request' AND docname=%s "
		"ORDER BY creation LIMIT 200",
		(name,),
		as_dict=True,
	):
		try:
			changed = (json.loads(v.data) or {}).get("changed") or []
		except ValueError:
			continue
		# state changes already appear as Workflow comments; linked_task is bookkeeping
		bits = [
			f"{labels[f]}: {_plain(old, 80) or 'empty'} to {_plain(new, 80) or 'empty'}"
			for f, old, new in (c for c in changed if len(c) == 3)
			if f in labels
		]
		if bits:
			events.append(
				{
					"at": str(v.creation),
					"kind": "edit",
					"title": "Details changed",
					"by": v.owner,
					"text": "\n".join(bits),
				}
			)
	events.sort(key=lambda e: e["at"])

	people = _users(
		[r.owner, r.requested_assignee]
		+ [e["by"] for e in events]
		+ (_assignees(task._assign) if task else [])
	)
	for e in events:
		e["by_name"] = people.get(e["by"], e["by"] or "")

	days = _age_days(r.creation, now)
	return {
		"success": True,
		"request": {
			"name": r.name,
			"title": r.title,
			"description": _plain(r.description),
			"request_type": r.request_type or "",
			"priority": r.priority or "",
			"status": r.workflow_state,
			"product_area": r.product_area or "",
			"project": r.project or "",
			"project_name": r.project_name or r.project or "",
			"raised_by": r.owner,
			"raised_by_name": people.get(r.owner, r.owner),
			"raised_for": r.employee_name if (r.employee_name and r.employee_user != r.owner) else "",
			"requested_for_name": people.get(r.requested_assignee, r.requested_assignee or ""),
			"source": r.source or "",
			"tags": tags,
			"creation": str(r.creation),
			"modified": str(r.modified),
			"age_days": days,
			"age_label": _age_label(days),
			"age_band": _age_band(days),
		},
		"task": {
			"name": task.name,
			"subject": task.subject,
			"status": task.status,
			"priority": task.priority,
			"due": str(task.exp_end_date)[:10] if task.exp_end_date else "",
			"completed_on": str(task.completed_on)[:10] if task.completed_on else "",
			"assignees": [people.get(a, a) for a in _assignees(task._assign)],
			"assignee_ids": _assignees(task._assign),
		}
		if task
		else None,
		"history": events,
		"actions": allowed_actions(r.workflow_state, set(frappe.get_roles()), bool(task)),
	}
