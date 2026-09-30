import json

import frappe
from frappe import _
from frappe.utils import getdate, nowdate, today

from upande_dev_tools.setup import DEV_TOOLS_PROJECT_TYPE

BOARD_ROLES = {"Dev Team", "Projects Manager", "System Manager"}

STAGES = ["Triage", "Todo", "In Progress", "In Review", "Blocked", "Done"]


def _priority_rank() -> dict[str, int]:
	"""Priority Level (Master Data page-editable) ordered by its own sort_order - the real
	source of truth for what a valid priority is and how it ranks, instead of a hardcoded
	list that silently rejects whatever an admin adds there. The table is a handful of rows,
	so querying it fresh per board load costs nothing worth caching."""
	levels = frappe.get_all("Priority Level", order_by="sort_order asc", pluck="name")
	return {name: i + 1 for i, name in enumerate(levels)}


def normalize_priority(doctype: str, fieldname: str, value: str | None) -> str | None:
	"""Priority Level (this app's own master data, Master Data page-editable) is the one
	place priority names are meant to be extended - but several doctypes we write a priority
	into don't read from it at all: Task and ToDo both have their own hardcoded, non-
	extensible Select field, and Issue links to a wholly separate "Issue Priority" master
	that doesn't carry "Urgent" today. Rather than assume those vocabularies stay in sync
	with Priority Level forever (the exact assumption that broke once already), clamp
	whatever we're about to write down to what the TARGET field can actually accept."""
	if not value:
		return value

	field = frappe.get_meta(doctype).get_field(fieldname)
	if not field:
		return value

	if field.fieldtype == "Select":
		allowed = [o for o in (field.options or "").split("\n") if o]
	elif field.fieldtype == "Link":
		allowed = frappe.get_all(field.options, pluck="name")
	else:
		return value

	if value in allowed:
		return value
	if value == "Urgent" and "High" in allowed:
		return "High"
	for fallback in ("High", "Medium", "Low"):
		if fallback in allowed:
			return fallback
	return None


def _validate_tags(tags: list[str]) -> None:
	"""Tags are Master Data page-editable (Work Tag), the same as Priority Level/Product
	Area/Request Type - so the vocabulary lives in one place a PM can extend, and a stray
	typo in a free-text tag can't quietly create a tag nobody will ever filter by again."""
	if not tags:
		return
	known = set(frappe.get_all("Work Tag", pluck="name"))
	unknown = [t for t in tags if t not in known]
	if unknown:
		frappe.throw(
			_("Add {0} as a Tag in Master Data before using it.").format(", ".join(unknown)),
			frappe.ValidationError,
		)


# High enough that a real backlog (2300+ items today across one project) never gets silently
# truncated - the frontend never passes its own limit, so this default is the only ceiling
# that matters in practice. Truncating here is what caused two real bugs: a freshly created
# task with no priority/due date sorts last and fell off the cut entirely, and the
# "Requests" source filter (client-side, applied AFTER this truncation) could only ever show
# whichever Requests survived being crowded out of the combined Task+Issue+Request list by
# higher-priority/more-recent Tasks.
BOARD_LIMIT = 10000

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
	"Withdrawn": "Done",
	"Closed": "Done",
}

STAGE_SETTERS = {"Task": (TASK_STATUS, "status"), "Issue": (ISSUE_STATUS, "status")}

EDITABLE = {
	"Task": {
		"title": "subject",
		"description": "description",
		"priority": "priority",
		"project": "project",
		"start": "exp_start_date",
		"end": "exp_end_date",
		"module": "custom_module",
	},
	"Issue": {
		"title": "subject",
		"description": "description",
		"priority": "priority",
		"project": "project",
		"start": "opening_date",
		"end": "sla_resolution_by",
		"module": "custom_module",
	},
}


@frappe.whitelist()
def get_board(project: str | None = None, limit: int = BOARD_LIMIT, tag: str | None = None) -> dict:
	if project:
		if not frappe.has_permission("Project", "read", project):
			frappe.throw(_("Not permitted to view this project."), frappe.PermissionError)
	elif not set(frappe.get_roles()) & BOARD_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	if project:
		filters = {"project": project}
	else:
		# No single project requested - restrict to the Dev Tools-flagged set, same baseline
		# every other dashboard aggregate applies, rather than every project in the ERP.
		dev_tools_projects = frappe.get_all(
			"Project", filters={"project_type": DEV_TOOLS_PROJECT_TYPE}, pluck="name", ignore_permissions=True
		)
		filters = {"project": ["in", dev_tools_projects or [""]]}
	items = _tasks(filters) + _issues(filters) + _requests(filters)
	_resolve_people(items)

	if tag:
		tagged_names = (
			set(_names_with_tag("Task", tag))
			| set(_names_with_tag("Issue", tag))
			| set(_names_with_tag("Request", tag))
		)
		items = [i for i in items if i["name"] in tagged_names]

	now = getdate(today())
	for item in items:
		due = getdate(item["end"]) if item["end"] else None
		item["late"] = bool(due and due < now and item["stage"] != "Done")

	items.sort(key=lambda i: (-i["rank"], i["end"] or "9999-12-31", i["title"]))
	limit = min(int(limit), 20000)
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
			"custom_module",
			"exp_start_date",
			"exp_end_date",
			"_assign",
		],
		ignore_permissions=True,
	)
	items = [
		{
			"doctype": "Task",
			"name": row.name,
			"title": row.subject,
			"status": row.status,
			"stage": TASK_STAGE.get(row.status, "Todo"),
			"rank": _priority_rank().get(row.priority, 0),
			"priority": row.priority,
			"project": row.project,
			"module": row.custom_module,
			"start": _date(row.exp_start_date),
			"end": _date(row.exp_end_date),
			"movable": True,
			"_assign": row._assign,
		}
		for row in rows
	]
	_attach_tags("Task", items)
	return items


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
	items = [
		{
			"doctype": "Issue",
			"name": row.name,
			"title": row.subject,
			"status": row.status,
			"stage": ISSUE_STAGE.get(row.status, "Triage"),
			"rank": _priority_rank().get(row.priority, 0),
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
	# Tasks and Requests already carry theirs. An Issue that could be tagged from the
	# sheet but never showed the tag back was the odd one out.
	_attach_tags("Issue", items)
	return items


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
	items = [
		{
			"doctype": "Request",
			"name": row.name,
			"title": row.title,
			"status": row.workflow_state or "Requested",
			"stage": REQUEST_STAGE.get(row.workflow_state or "", "Triage"),
			"rank": _priority_rank().get(row.priority, 0),
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
	_attach_tags("Request", items)
	return items


def _attach_tags(doctype: str, items: list[dict]) -> None:
	"""Frappe's own tagging (Tag Link), not a custom field - so a board item's tags are
	fetched the same way its own core sidebar "Add Tag" widget resolves them."""
	if not items:
		return
	names = [item["name"] for item in items]
	rows = frappe.get_all(
		"Tag Link",
		filters={"document_type": doctype, "document_name": ["in", names]},
		fields=["document_name", "tag"],
	)
	by_name: dict[str, list[str]] = {}
	for row in rows:
		by_name.setdefault(row.document_name, []).append(row.tag)
	for item in items:
		item["tags"] = by_name.get(item["name"], [])


def _names_with_tag(doctype: str, tag: str) -> list[str]:
	return frappe.get_all("Tag Link", filters={"document_type": doctype, "tag": tag}, pluck="document_name")


@frappe.whitelist()
def get_used_tags(doctype: str) -> list[str]:
	"""Tag names only, not sensitive - open to any logged-in user so a customer raising a
	request can pick from tags already in use, same as get_assignable_users/get_employees."""
	if doctype not in ("Task", "Issue", "Request"):
		frappe.throw(_("Unknown work item."), frappe.ValidationError)

	return sorted(set(frappe.get_all("Tag Link", filters={"document_type": doctype}, pluck="tag")))


@frappe.whitelist()
def get_work_tags() -> list[str]:
	"""The Work Tag master list (Master Data page-editable), active entries only - this is
	what fills the tag picker on Task/Request creation. Tag names aren't sensitive, open to
	any logged-in user for the same reason get_used_tags/get_employees are: a customer
	raising a request needs to pick from it too."""
	return frappe.get_all("Work Tag", filters={"disabled": 0}, pluck="name", order_by="tag_name asc")


def _set_doc_tags(doctype: str, name: str, tags: list[str]) -> None:
	"""Same shape Frappe's own DocTags/update_tags maintain (_user_tags CSV + Tag Link rows),
	written directly with ignore_permissions rather than through frappe.desk.doctype.tag.tag's
	helpers - those call doc.check_permission("write"), which doesn't line up with this app's
	own PM/Dev Team role model, the same class of mismatch already hit with assignment."""
	tags = sorted({t.strip() for t in tags if t and t.strip()})
	frappe.db.set_value(doctype, name, "_user_tags", ",".join(tags), update_modified=False)
	frappe.db.delete("Tag Link", {"document_type": doctype, "document_name": name})
	for tag in tags:
		if not frappe.db.exists("Tag", tag):
			frappe.get_doc({"doctype": "Tag", "name": tag}).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Tag Link",
				"document_type": doctype,
				"document_name": name,
				"tag": tag,
				"title": name,
			}
		).insert(ignore_permissions=True)


@frappe.whitelist()
def add_tag(doctype: str, name: str, tag: str) -> dict:
	if doctype not in ("Task", "Issue", "Request"):
		frappe.throw(_("Unknown work item."), frappe.ValidationError)
	if not set(frappe.get_roles()) & BOARD_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	_validate_tags([tag])

	existing = frappe.get_all(
		"Tag Link", filters={"document_type": doctype, "document_name": name}, pluck="tag"
	)
	_set_doc_tags(doctype, name, [*existing, tag])
	return {"name": name, "tag": tag}


@frappe.whitelist()
def remove_tag(doctype: str, name: str, tag: str) -> dict:
	if doctype not in ("Task", "Issue", "Request"):
		frappe.throw(_("Unknown work item."), frappe.ValidationError)
	if not set(frappe.get_roles()) & BOARD_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	existing = frappe.get_all(
		"Tag Link", filters={"document_type": doctype, "document_name": name}, pluck="tag"
	)
	_set_doc_tags(doctype, name, [t for t in existing if t != tag])
	return {"name": name, "tag": tag}


@frappe.whitelist()
def delete_task(name: str) -> None:
	"""PM/System Manager can delete any Task; a developer can delete one they're currently
	assigned to. Clears the parent Request's link rather than leaving it pointing at a dead
	Task, and drops that Request back to Approved so it re-enters the scheduling step."""
	if not set(frappe.get_roles()) & BOARD_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	doc = frappe.get_doc("Task", name)
	is_reviewer = {"Projects Manager", "System Manager"} & set(frappe.get_roles())
	if not is_reviewer:
		assignees = json.loads(doc.get("_assign") or "[]")
		if frappe.session.user not in assignees:
			frappe.throw(_("You can only delete tasks assigned to you."), frappe.PermissionError)

	request_name = frappe.db.get_value("Request", {"linked_task": name}, "name")
	if request_name:
		frappe.db.set_value(
			"Request",
			request_name,
			{"linked_task": None, "workflow_state": "Approved"},
			update_modified=False,
		)

	frappe.delete_doc("Task", name, ignore_permissions=True)


@frappe.whitelist()
def create_task(
	project: str,
	subject: str,
	tags: list[str] | str | None = None,
	description: str | None = None,
	priority: str | None = None,
	module: str | None = None,
	complete_by: str | None = None,
	assign_to: str | list[str] | None = None,
) -> dict:
	"""Ad-hoc work that never started life as a Request - internal cleanup, a chore, anything
	a PM or dev just needs to log directly. Every other Task on this board comes from
	Request.on_update() once a Request is scheduled; this is the one place a Task is created
	with no linked Request at all, and custom_request is deliberately left blank. tags is
	mandatory - it's the one classification the board can actually filter on, for a Task the
	same as for a Request.

	Anyone outside Dev Team/Projects Manager can call this too, but doesn't get a Task straight
	onto the board - only Dev Team/Projects Manager are trusted to skip review. Everyone else's
	"add to backlog" becomes a Request instead (as "Chore"), going through the normal review
	pipeline like anything else they raise. project is deliberately NOT forwarded: a plain
	user calling this from outside the board has no reason to have Project read access, and
	create_request would just deny it - a PM attaches the right project during accept_request,
	same as any other request that came in without one.
	"""
	if not set(frappe.get_roles()) & BOARD_ROLES:
		# Lazy import: requests.py imports from this module at load time, so importing it
		# back here at module load time would be circular.
		from upande_dev_tools.api.requests import create_request

		return create_request(
			title=subject,
			request_type="Chore",
			description=description,
			tags=tags,
		)

	if not (project and subject):
		frappe.throw(_("Set a project and a title before creating a task."), frappe.ValidationError)

	if isinstance(tags, str):
		tags = [t.strip() for t in tags.split(",")]
	tags = [t for t in (tags or []) if t and t.strip()]
	if not tags:
		frappe.throw(_("Add at least one tag before creating this task."), frappe.ValidationError)
	_validate_tags(tags)

	task = frappe.get_doc(
		{
			"doctype": "Task",
			"subject": subject,
			"description": description,
			"project": project,
			"priority": normalize_priority("Task", "priority", priority),
			"custom_module": module,
			"exp_end_date": complete_by,
		}
	)
	task.flags.ignore_recursion_check = True
	task.insert(ignore_permissions=True)
	_set_doc_tags("Task", task.name, tags)

	if assign_to:
		# Lazy import: requests.py imports normalize_priority from this module, so importing
		# these back at module load time here would be circular.
		from upande_dev_tools.api.requests import _assign_many, parse_users

		_assign_many("Task", task.name, parse_users(assign_to), date=complete_by, priority=priority)

	return {"name": task.name}


def _resolve_people(items: list[dict]) -> None:
	"""Carries both halves of an assignment: `assignees` are the display names every view
	renders, `assignee_ids` the emails those names resolve from. Full names are not unique on
	this bench (two Brians, two Beatrice Temburs), so anything that writes an assignment back
	has to round-trip the email - matching a person by their displayed name picks whichever
	duplicate happens to sort first."""
	emails: set[str] = set()
	for item in items:
		assigned = item.pop("_assign", None)
		item["assignee_ids"] = json.loads(assigned) if assigned else []
		item["assignees"] = list(item["assignee_ids"])
		emails.update(item["assignee_ids"])

	if not emails:
		return

	rows = frappe.get_all("User", filters={"name": ["in", list(emails)]}, fields=["name", "full_name"])
	names = {row.name: row.full_name or row.name for row in rows}
	for item in items:
		item["assignees"] = [names.get(email, email) for email in item["assignee_ids"]]


def _apply_status(doc, status: str) -> str:
	"""Puts a doc on a status without saving it. The sheet's Status column writes one of
	these directly; a stage is just a status this board has a friendlier name for."""
	if doc.doctype not in STAGE_SETTERS:
		frappe.throw(_("{0} is moved through its own workflow, not the board.").format(_(doc.doctype)))

	_, fieldname = STAGE_SETTERS[doc.doctype]
	if status not in frappe.get_meta(doc.doctype).get_field(fieldname).options.split("\n"):
		frappe.throw(_("{0} has no status {1}.").format(_(doc.doctype), status), frappe.ValidationError)

	doc.set(fieldname, status)

	# Stamp when the work actually finished. Nothing recorded this before, so no
	# measure of delivery or cycle time could ever be computed from it.
	stage_map = TASK_STAGE if doc.doctype == "Task" else ISSUE_STAGE
	if doc.doctype == "Task" and doc.meta.has_field("completed_on"):
		if stage_map.get(status) == "Done":
			doc.completed_on = doc.completed_on or nowdate()
			if doc.meta.has_field("completed_by"):
				doc.completed_by = doc.completed_by or frappe.session.user
		else:
			doc.completed_on = None

	return status


def _apply_stage(doc, stage: str) -> str:
	"""Puts a doc on a stage without saving it, so a stage change can ride along with the
	rest of an edit in one save instead of needing its own round trip."""
	if doc.doctype not in STAGE_SETTERS:
		frappe.throw(_("{0} is moved through its own workflow, not the board.").format(_(doc.doctype)))

	if stage not in STAGES:
		frappe.throw(_("Unknown stage {0}.").format(stage), frappe.ValidationError)

	status_map, _fieldname = STAGE_SETTERS[doc.doctype]
	return _apply_status(doc, status_map[stage])


def _save(doc) -> None:
	if doc.doctype == "Task":
		# Same pypika/recursive-CTE incompatibility already worked around in
		# Request.on_update() - Task.on_update() always runs check_recursion() on save,
		# and this bench's pypika can't run the query it needs.
		doc.flags.ignore_recursion_check = True
	doc.save(ignore_permissions=True)


@frappe.whitelist()
def set_stage(doctype: str, name: str, stage: str) -> dict:
	if not set(frappe.get_roles()) & BOARD_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	if doctype not in STAGE_SETTERS:
		frappe.throw(_("{0} is moved through its own workflow, not the board.").format(_(doctype)))

	doc = frappe.get_doc(doctype, name)
	status = _apply_stage(doc, stage)
	_save(doc)
	return {"name": name, "status": status, "stage": stage}


def _editable_value(doctype: str, field: str, fieldname: str, value):
	"""Validates and coerces one board-editable field. Shared by the single-cell path the
	sheet and the timeline use and the whole-form path the edit dialog uses, so a value the
	sheet refuses is not one the dialog quietly writes."""
	if field == "title" and not (value or "").strip():
		frappe.throw(_("A work item needs a title."), frappe.ValidationError)

	if field == "priority" and value and value not in _priority_rank():
		frappe.throw(_("Unknown priority {0}.").format(value), frappe.ValidationError)

	if field == "module" and value and not frappe.db.exists("Product Area", value):
		frappe.throw(_("Unknown module {0}.").format(value), frappe.ValidationError)

	if field == "project" and value and not frappe.db.exists("Project", value):
		frappe.throw(_("Unknown project {0}.").format(value), frappe.ValidationError)

	coerced = _coerce(frappe.get_meta(doctype).get_field(fieldname).fieldtype, value)
	if field == "priority":
		coerced = normalize_priority(doctype, fieldname, coerced)
	return coerced


@frappe.whitelist()
def set_field(doctype: str, name: str, field: str, value: str | None = None) -> dict:
	if not set(frappe.get_roles()) & BOARD_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	fields = EDITABLE.get(doctype)
	if not fields or field not in fields:
		frappe.throw(_("{0} cannot be edited from the board.").format(field), frappe.ValidationError)

	fieldname = fields[field]
	doc = frappe.get_doc(doctype, name)
	doc.set(fieldname, _editable_value(doctype, field, fieldname, value))
	_save(doc)
	return {"name": name, "field": field, "value": value or ""}


@frappe.whitelist()
def get_editable(doctype: str, name: str) -> dict:
	"""What the edit dialog opens on. The board payload deliberately carries no descriptions
	- there are thousands of rows in it and no view renders one - so the single item about to
	be edited fetches its own, rather than every item paying for the one."""
	if not set(frappe.get_roles()) & BOARD_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	fields = EDITABLE.get(doctype)
	if not fields:
		frappe.throw(
			_("{0} is moved through its own workflow, not the board.").format(_(doctype)),
			frappe.ValidationError,
		)

	doc = frappe.get_doc(doctype, name)
	values = {field: doc.get(fieldname) for field, fieldname in fields.items()}
	values["start"] = _date(values.get("start"))
	values["end"] = _date(values.get("end"))
	values["status"] = doc.get("status")
	stage_map = TASK_STAGE if doctype == "Task" else ISSUE_STAGE
	values["stage"] = stage_map.get(doc.get("status"), "Todo")
	values["tags"] = sorted(
		frappe.get_all(
			"Tag Link", filters={"document_type": doctype, "document_name": name}, pluck="tag"
		)
	)
	values["assignees"] = json.loads(doc.get("_assign") or "[]")
	return values


@frappe.whitelist()
def update_work(doctype: str, name: str, values: dict | str) -> dict:
	"""The edit dialog's save. Every plain field lands in one doc.save() rather than a field's
	worth of round trips, so a half-applied edit is not a state this board can end up in.
	Stage, tags and assignment are not plain fields and still go through the paths that own
	them - assignment in particular is reviewer-only, which a Dev Team member editing anything
	else about a task must not be able to route around."""
	if not set(frappe.get_roles()) & BOARD_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	fields = EDITABLE.get(doctype)
	if not fields:
		frappe.throw(
			_("{0} is moved through its own workflow, not the board.").format(_(doctype)),
			frappe.ValidationError,
		)

	if isinstance(values, str):
		values = json.loads(values)

	doc = frappe.get_doc(doctype, name)
	for field, fieldname in fields.items():
		if field in values:
			doc.set(fieldname, _editable_value(doctype, field, fieldname, values[field]))

	if not doc.get(fields["title"]):
		frappe.throw(_("A work item needs a title."), frappe.ValidationError)

	start, end = doc.get(fields["start"]), doc.get(fields["end"])
	if start and end and getdate(end) < getdate(start):
		frappe.throw(_("The due date cannot fall before the start date."), frappe.ValidationError)

	if values.get("stage"):
		_apply_stage(doc, values["stage"])
	# The sheet's Status column is more specific than a stage, so it wins if both arrive.
	if values.get("status"):
		_apply_status(doc, values["status"])
	_save(doc)

	if "tags" in values:
		tags = values["tags"]
		if isinstance(tags, str):
			tags = tags.split(",")
		tags = [t.strip() for t in (tags or []) if t and t.strip()]
		_validate_tags(tags)
		_set_doc_tags(doctype, name, tags)

	# Lazy import: requests.py imports from this module, so importing it back at module
	# load time here would be circular.
	from upande_dev_tools.api.requests import parse_users, reassign_task

	if doctype == "Task" and values.get("assign_to") is not None:
		people = parse_users(values["assign_to"])
		if people and people != json.loads(doc.get("_assign") or "[]"):
			reassign_task(name, people)

	return {"name": name}


# A fill dragged down a long column, or a paste out of a real spreadsheet, can name more
# rows than anyone meant to touch. Past this the sheet is told to make a smaller selection
# rather than the server quietly working through thousands of saves.
BULK_LIMIT = 200


@frappe.whitelist()
def bulk_update(changes: list | str) -> dict:
	"""Every cell a fill or a paste touched, in one request. Rows are independent: one that
	fails is rolled back to its own savepoint and reported by name, and the rest still save
	- a paste over twenty rows should not be undone by the one Request hiding among them."""
	if not set(frappe.get_roles()) & BOARD_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	if isinstance(changes, str):
		changes = json.loads(changes)
	changes = changes or []

	if len(changes) > BULK_LIMIT:
		frappe.throw(
			_("That is {0} rows at once. Select up to {1} and try again.").format(
				len(changes), BULK_LIMIT
			),
			frappe.ValidationError,
		)

	saved: list[str] = []
	failed: list[dict] = []
	for i, change in enumerate(changes):
		doctype, name = change.get("doctype"), change.get("name")
		point = f"udt_bulk_{i}"
		frappe.db.savepoint(point)
		try:
			update_work(doctype, name, change.get("values") or {})
			saved.append(name)
		except Exception as e:
			frappe.db.rollback(save_point=point)
			failed.append({"name": name, "error": str(e) or _("Could not save that row.")})

	return {"saved": saved, "failed": failed}


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


@frappe.whitelist()
def get_projects() -> list[dict]:
	"""The Dev-Tools-flagged project set, same baseline every other board query uses - so a
	project picker on the board never offers one of the unrelated business projects this app
	deliberately keeps out of everything else."""
	if not set(frappe.get_roles()) & BOARD_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	return frappe.get_all(
		"Project",
		filters={"project_type": DEV_TOOLS_PROJECT_TYPE},
		fields=["name", "project_name"],
		order_by="project_name asc",
		ignore_permissions=True,
	)


PREVIEW_LIMIT = 280
IMAGE_TYPES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif")


@frappe.whitelist()
def get_preview(doctype: str, name: str) -> dict:
	"""Enough of a work item to decide whether to open it: what it is, where it
	stands, the first part of what was written, and the screenshot if one came
	with it - which, for an issue raised from the app, it usually did."""
	if doctype not in ("Task", "Issue", "Request"):
		frappe.throw(_("Unknown work item."), frappe.ValidationError)
	if not set(frappe.get_roles()) & BOARD_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	fields = {
		"Task": ["subject", "status", "priority", "project", "description", "custom_module", "_assign"],
		"Issue": [
			"subject",
			"status",
			"priority",
			"project",
			"description",
			"custom_module",
			"_assign",
			"raised_by",
		],
		"Request": [
			"title",
			"workflow_state",
			"priority",
			"project",
			"description",
			"product_area",
			"owner",
		],
	}[doctype]

	doc = frappe.db.get_value(doctype, name, fields, as_dict=True)
	if not doc:
		frappe.throw(_("That work item is gone."), frappe.DoesNotExistError)

	assigned = json.loads(doc.get("_assign")) if doc.get("_assign") else []
	names = _resolve_names(set(assigned))

	return {
		"doctype": doctype,
		"name": name,
		"title": doc.get("subject") or doc.get("title"),
		"status": doc.get("status") or doc.get("workflow_state") or "Open",
		"priority": doc.get("priority"),
		"project": doc.get("project"),
		"module": doc.get("custom_module") or doc.get("product_area"),
		"by": doc.get("raised_by") or doc.get("owner"),
		"assignees": [names.get(who, who) for who in assigned],
		"summary": _summarise(doc.get("description")),
		# Served through this app rather than linked directly: an attachment on an
		# issue is private, and reading the board does not grant read on the file.
		"image": (
			f"/api/method/upande_dev_tools.api.board.preview_image"
			f"?doctype={doctype}&name={frappe.utils.quoted(name)}"
			if _first_image(doctype, name)
			else None
		),
	}


@frappe.whitelist()
def preview_image(doctype: str, name: str):
	if doctype not in ("Task", "Issue", "Request"):
		frappe.throw(_("Unknown work item."), frappe.ValidationError)
	if not set(frappe.get_roles()) & BOARD_ROLES:
		raise frappe.PermissionError

	url = _first_image(doctype, name)
	if not url:
		raise frappe.DoesNotExistError

	row = frappe.db.get_value("File", {"file_url": url}, ["name", "file_name"], as_dict=True)
	content = frappe.get_doc("File", row.name).get_content()

	frappe.response.filename = row.file_name
	frappe.response.filecontent = content
	frappe.response.type = "download"
	frappe.response.display_content_as = "inline"


def _summarise(html: str | None) -> str:
	if not html:
		return ""
	text = " ".join(frappe.utils.strip_html(html).split())
	if len(text) <= PREVIEW_LIMIT:
		return text
	# cut on a word so the trail reads as a sentence breaking off, not a slice
	return text[:PREVIEW_LIMIT].rsplit(" ", 1)[0] + "…"


def _first_image(doctype: str, name: str) -> str | None:
	files = frappe.get_all(
		"File",
		filters={"attached_to_doctype": doctype, "attached_to_name": name},
		fields=["file_url", "file_name"],
		order_by="creation asc",
		ignore_permissions=True,
	)
	images = [f for f in files if (f.file_url or "").lower().endswith(IMAGE_TYPES)]
	if not images:
		return None
	# a file the reporter called a screenshot beats an incidental photo
	shots = [f for f in images if "screenshot" in (f.file_name or "").lower()]
	return (shots or images)[0].file_url


def _resolve_names(emails: set[str]) -> dict[str, str]:
	if not emails:
		return {}
	rows = frappe.get_all("User", filters={"name": ["in", list(emails)]}, fields=["name", "full_name"])
	return {row.name: row.full_name or row.name for row in rows}
