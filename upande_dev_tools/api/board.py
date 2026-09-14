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

EDITABLE = {
	"Task": {
		"priority": "priority",
		"start": "exp_start_date",
		"end": "exp_end_date",
		"module": "custom_module",
	},
	"Issue": {
		"priority": "priority",
		"start": "opening_date",
		"end": "sla_resolution_by",
		"module": "custom_module",
	},
}


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


def _date(value) -> str:
	return str(getdate(value)) if value else ""


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
			"custom_module",
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
			"module": row.custom_module,
			"start": _date(row.exp_start_date or row.custom_planned_for),
			"end": _date(row.exp_end_date or row.custom_planned_for),
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
			"custom_module",
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
			"module": row.custom_module,
			"start": _date(row.opening_date),
			"end": _date(row.sla_resolution_by),
			"movable": True,
			"_assign": row._assign,
		}
		for row in rows
	]


def _requests(filters: dict) -> list[dict]:
	rows = frappe.get_all(
		"Request",
		filters=filters,
		fields=[
			"name",
			"title",
			"workflow_state",
			"priority",
			"project",
			"product_area",
			"linked_task",
			"_assign",
		],
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
			"module": row.product_area,
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


@frappe.whitelist()
def set_field(doctype: str, name: str, field: str, value: str | None = None) -> dict:
	if not set(frappe.get_roles()) & BOARD_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	fields = EDITABLE.get(doctype)
	if not fields or field not in fields:
		frappe.throw(_("{0} cannot be edited from the board.").format(field), frappe.ValidationError)

	if field == "priority" and value and value not in PRIORITY_RANK:
		frappe.throw(_("Unknown priority {0}.").format(value), frappe.ValidationError)

	if field == "module" and value and not frappe.db.exists("Product Area", value):
		frappe.throw(_("Unknown module {0}.").format(value), frappe.ValidationError)

	fieldname = fields[field]
	doc = frappe.get_doc(doctype, name)
	doc.set(fieldname, _coerce(doc.meta.get_field(fieldname).fieldtype, value))
	doc.save()
	return {"name": name, "field": field, "value": value or ""}


def _coerce(fieldtype: str, value: str | None):
	if not value:
		return None
	if fieldtype == "Datetime":
		return f"{getdate(value)} 17:00:00"
	if fieldtype == "Date":
		return getdate(value)
	return value


@frappe.whitelist()
def get_modules() -> list[str]:
	return frappe.get_all("Product Area", pluck="name", order_by="name asc")
