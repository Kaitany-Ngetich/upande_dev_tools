import json

import frappe
from frappe import _
from frappe.utils import getdate, today

BOARD_ROLES = {"Dev Team", "Projects Manager", "System Manager"}

STAGES = ["Triage", "Todo", "In Progress", "In Review", "Blocked", "Done"]

PRIORITY_RANK = {"Low": 1, "Medium": 2, "High": 3, "Urgent": 4}

BOARD_LIMIT = 500

TASK_STAGE = {
	"Open": "Todo",
	"Template": "Todo",
	"Working": "In Progress",
	"Overdue": "In Progress",
	"Pending Review": "In Review",
	"Completed": "Done",
	"Cancelled": "Done",
}
TASK_STATUS = {
	"Triage": "Open",
	"Todo": "Open",
	"In Progress": "Working",
	"In Review": "Pending Review",
	"Blocked": "Pending Review",
	"Done": "Completed",
}

ISSUE_STAGE = {
	"Open": "Triage",
	"Replied": "In Progress",
	"On Hold": "Blocked",
	"Resolved": "Done",
	"Closed": "Done",
}
ISSUE_STATUS = {
	"Triage": "Open",
	"Todo": "Open",
	"In Progress": "Replied",
	"In Review": "Replied",
	"Blocked": "On Hold",
	"Done": "Resolved",
}

REQUEST_STAGE = {
	"": "Triage",
	"Under Review": "Triage",
	"Approved": "Todo",
	"Scheduled": "Todo",
	"In Progress": "In Progress",
	"Completed": "Done",
	"Rejected": "Done",
	"Deferred": "Blocked",
}

STAGE_SETTERS = {"Task": (TASK_STATUS, "status"), "Issue": (ISSUE_STATUS, "status")}


@frappe.whitelist()
def get_board(project: str | None = None, limit: int = BOARD_LIMIT) -> dict:
	if project:
		if not frappe.has_permission("Project", "read", project):
			frappe.throw(_("Not permitted to view this project."), frappe.PermissionError)
	elif not set(frappe.get_roles()) & BOARD_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	filters = {"project": project} if project else {}
	items = _tasks(filters) + _issues(filters) + _requests(filters)
	_resolve_people(items)

	now = getdate(today())
	for item in items:
		due = getdate(item["end"]) if item["end"] else None
		item["late"] = bool(due and due < now and item["stage"] != "Done")

	items.sort(key=lambda i: (-i["rank"], i["end"] or "9999-12-31", i["title"]))
	limit = min(int(limit), 2000)
	return {"items": items[:limit], "total": len(items), "stages": STAGES}


def _tasks(filters: dict) -> list[dict]:
	rows = frappe.get_all(
		"Task",
		filters=filters,
		fields=[
			"name",
			"subject",
			"status",
			"priority",
			"project",
			"custom_request",
			"custom_planned_for",
			"exp_start_date",
			"exp_end_date",
			"_assign",
		],
		ignore_permissions=True,
	)
	return [
		{
			"doctype": "Task",
			"name": row.name,
			"title": row.subject,
			"status": row.status,
			"stage": TASK_STAGE.get(row.status, "Todo"),
			"rank": PRIORITY_RANK.get(row.priority, 0),
			"priority": row.priority,
			"project": row.project,
			"start": str(row.exp_start_date or row.custom_planned_for or ""),
			"end": str(row.exp_end_date or row.custom_planned_for or ""),
			"movable": True,
			"_assign": row._assign,
		}
		for row in rows
	]


def _issues(filters: dict) -> list[dict]:
	rows = frappe.get_all(
		"Issue",
		filters=filters,
		fields=[
			"name",
			"subject",
			"status",
			"priority",
			"project",
			"opening_date",
			"sla_resolution_by",
			"_assign",
		],
		ignore_permissions=True,
	)
	return [
		{
			"doctype": "Issue",
			"name": row.name,
			"title": row.subject,
			"status": row.status,
			"stage": ISSUE_STAGE.get(row.status, "Triage"),
			"rank": PRIORITY_RANK.get(row.priority, 0),
			"priority": row.priority,
			"project": row.project,
			"start": str(row.opening_date or ""),
			"end": str(getdate(row.sla_resolution_by) if row.sla_resolution_by else ""),
			"movable": True,
			"_assign": row._assign,
		}
		for row in rows
	]


def _requests(filters: dict) -> list[dict]:
	rows = frappe.get_all(
		"Request",
		filters=filters,
		fields=["name", "title", "workflow_state", "priority", "project", "linked_task", "_assign"],
		ignore_permissions=True,
	)
	return [
		{
			"doctype": "Request",
			"name": row.name,
			"title": row.title,
			"status": row.workflow_state or "Requested",
			"stage": REQUEST_STAGE.get(row.workflow_state or "", "Triage"),
			"rank": PRIORITY_RANK.get(row.priority, 0),
			"priority": row.priority,
			"project": row.project,
			"start": "",
			"end": "",
			"movable": False,
			"_assign": row._assign,
		}
		for row in rows
	]


def _resolve_people(items: list[dict]) -> None:
	emails: set[str] = set()
	for item in items:
		assigned = item.pop("_assign", None)
		item["assignees"] = json.loads(assigned) if assigned else []
		emails.update(item["assignees"])

	if not emails:
		return

	rows = frappe.get_all("User", filters={"name": ["in", list(emails)]}, fields=["name", "full_name"])
	names = {row.name: row.full_name or row.name for row in rows}
	for item in items:
		item["assignees"] = [names.get(email, email) for email in item["assignees"]]


@frappe.whitelist()
def set_stage(doctype: str, name: str, stage: str) -> dict:
	if not set(frappe.get_roles()) & BOARD_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	if doctype not in STAGE_SETTERS:
		frappe.throw(_("{0} is moved through its own workflow, not the board.").format(_(doctype)))

	if stage not in STAGES:
		frappe.throw(_("Unknown stage {0}.").format(stage), frappe.ValidationError)

	status_map, fieldname = STAGE_SETTERS[doctype]
	status = status_map[stage]
	if status not in frappe.get_meta(doctype).get_field(fieldname).options.split("\n"):
		frappe.throw(_("{0} has no status {1}.").format(_(doctype), status), frappe.ValidationError)

	doc = frappe.get_doc(doctype, name)
	doc.set(fieldname, status)
	doc.save()
	return {"name": name, "status": status, "stage": stage}
