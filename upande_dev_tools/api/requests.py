# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _

REVIEWER_ROLES = {"Dev Team", "Projects Manager", "System Manager"}


def _resolve_user_display_names(emails: set[str]) -> dict[str, str]:
	if not emails:
		return {}
	rows = frappe.get_all("User", filters={"name": ["in", list(emails)]}, fields=["name", "full_name"])
	return {row.name: row.full_name or row.name for row in rows}


@frappe.whitelist()
def create_request(
	title: str,
	request_type: str,
	description: str | None = None,
	product_area: str | None = None,
	project: str | None = None,
	source: str = "Desk",
) -> dict:
	if project and not frappe.has_permission("Project", "read", project):
		frappe.throw(_("Not permitted to view this project."), frappe.PermissionError)

	doc = frappe.get_doc(
		{
			"doctype": "Request",
			"title": title,
			"request_type": request_type,
			"description": description,
			"product_area": product_area,
			"project": project,
			"source": source,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.as_dict()


@frappe.whitelist()
def get_my_requests(status: str | None = None) -> list[dict]:
	filters: dict[str, str] = {"raised_by_user": frappe.session.user}
	if status:
		filters["workflow_state"] = status

	return frappe.get_all(
		"Request",
		filters=filters,
		fields=[
			"name",
			"title",
			"request_type",
			"workflow_state",
			"priority",
			"project",
			"linked_task",
			"creation",
		],
		order_by="creation desc",
		ignore_permissions=True,
	)


@frappe.whitelist()
def get_review_queue() -> list[dict]:
	if not set(frappe.get_roles()) & REVIEWER_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	return frappe.get_all(
		"Request",
		filters={"workflow_state": "Under Review"},
		fields=[
			"name",
			"title",
			"request_type",
			"product_area",
			"project",
			"priority",
			"raised_by_user",
			"creation",
		],
		order_by="creation asc",
		ignore_permissions=True,
	)


@frappe.whitelist()
def triage_request(
	name: str,
	action: str,
	project: str | None = None,
	priority: str | None = None,
) -> dict:
	from frappe.model.workflow import apply_workflow

	doc = frappe.get_doc("Request", name)
	if project:
		doc.project = project
	if priority:
		doc.priority = priority
	if project or priority:
		doc.save()

	updated = apply_workflow(doc, action)
	return updated.as_dict()


@frappe.whitelist()
def get_assignable_users() -> list[dict]:
	if not set(frappe.get_roles()) & REVIEWER_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	members = frappe.get_all("Has Role", filters={"role": "Dev Team", "parenttype": "User"}, pluck="parent")
	if not members:
		return []
	return frappe.get_all(
		"User",
		filters={"name": ["in", members], "enabled": 1},
		fields=["name", "full_name"],
		order_by="full_name asc",
	)


@frappe.whitelist()
def accept_request(name: str, project: str, priority: str, assign_to: str | None = None) -> dict:
	"""Approve a request and schedule it in one step, which is what creates the Task,
	then hand that Task to whoever will do the work."""
	from frappe.desk.form.assign_to import add as add_assignment
	from frappe.model.workflow import apply_workflow

	if not set(frappe.get_roles()) & REVIEWER_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	if not (project and priority):
		frappe.throw(_("Set a project and a priority before accepting."), frappe.ValidationError)

	doc = frappe.get_doc("Request", name)
	doc.project = project
	doc.priority = priority
	doc.save()

	doc = apply_workflow(doc, "Approve")
	doc = apply_workflow(doc, "Schedule")
	doc.reload()

	if assign_to and doc.linked_task:
		add_assignment({"doctype": "Task", "name": doc.linked_task, "assign_to": [assign_to], "notify": 0})

	return {
		"name": doc.name,
		"workflow_state": doc.workflow_state,
		"task": doc.linked_task,
		"assigned_to": assign_to,
	}


@frappe.whitelist()
def promote_to_task(name: str) -> dict:
	from frappe.model.workflow import apply_workflow

	doc = frappe.get_doc("Request", name)
	action = "Promote Note" if doc.request_type == "Note" else "Schedule"
	updated = apply_workflow(doc, action)
	return updated.as_dict()


@frappe.whitelist()
def get_backlog_board(project: str | None = None) -> dict:
	if project:
		if not frappe.has_permission("Project", "read", project):
			frappe.throw(_("Not permitted to view this project."), frappe.PermissionError)
	elif not set(frappe.get_roles()) & REVIEWER_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	filters: dict[str, str] = {"project": project} if project else {}

	tasks = frappe.get_all(
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
			"exp_end_date",
			"_assign",
		],
		order_by="priority desc, exp_end_date asc",
		ignore_permissions=True,
	)
	requests = frappe.get_all(
		"Request",
		filters=filters,
		fields=[
			"name",
			"title",
			"request_type",
			"workflow_state",
			"priority",
			"project",
			"linked_task",
			"raised_by_user",
			"raised_by_employee",
			"raised_by_contact",
			"raised_by_customer",
		],
		ignore_permissions=True,
	)

	# Backlog Board's whole point is to read like the source spreadsheet did - owner and
	# requester visible on every card, not just title/priority. _assign is a JSON-encoded
	# list of user emails; resolve to full names once in bulk rather than per-row.
	assignee_emails: set[str] = set()
	for task in tasks:
		task["_assign"] = json.loads(task["_assign"]) if task.get("_assign") else []
		assignee_emails.update(task["_assign"])
	user_names = _resolve_user_display_names(assignee_emails)
	for task in tasks:
		task["assigned_to"] = [user_names.get(email, email) for email in task["_assign"]]

	requester_user_emails = {r["raised_by_user"] for r in requests if r.get("raised_by_user")}
	requester_names = _resolve_user_display_names(requester_user_emails)
	employee_ids = {r["raised_by_employee"] for r in requests if r.get("raised_by_employee")}
	employee_names: dict[str, str] = {}
	if employee_ids:
		employee_rows = frappe.get_all(
			"Employee", filters={"name": ["in", list(employee_ids)]}, fields=["name", "employee_name"]
		)
		employee_names = {row.name: row.employee_name for row in employee_rows}
	for req in requests:
		if req.get("raised_by_employee"):
			req["requested_by"] = employee_names.get(req["raised_by_employee"], req["raised_by_employee"])
		elif req.get("raised_by_user"):
			req["requested_by"] = requester_names.get(req["raised_by_user"], req["raised_by_user"])
		elif req.get("raised_by_contact"):
			req["requested_by"] = req["raised_by_contact"]
		elif req.get("raised_by_customer"):
			# No single named individual on record - true for every request bulk-imported from
			# a client's own backlog spreadsheet, where only the client's identity, not a
			# specific person's, is known.
			req["requested_by"] = req["raised_by_customer"]
		else:
			req["requested_by"] = None

	return {"tasks": tasks, "requests": requests}


@frappe.whitelist()
def get_upcoming_meetings(
	project: str | None = None,
	for_user: str | None = None,
	within_days: int = 14,
) -> list[dict]:
	from frappe.utils import add_to_date, now_datetime

	if project:
		if not frappe.has_permission("Project", "read", project):
			frappe.throw(_("Not permitted to view this project."), frappe.PermissionError)
		event_names = frappe.get_all(
			"Dynamic Link",
			filters={"parenttype": "Event", "link_doctype": "Project", "link_name": project},
			pluck="parent",
		)
	else:
		user = for_user or frappe.session.user
		if user != frappe.session.user and not set(frappe.get_roles()) & REVIEWER_ROLES:
			frappe.throw(_("Not permitted."), frappe.PermissionError)
		event_names = frappe.get_all(
			"Event Participants",
			filters={"parenttype": "Event", "email": user},
			pluck="parent",
		)

	if not event_names:
		return []

	now = now_datetime()
	end = add_to_date(now, days=within_days)
	return frappe.get_all(
		"Event",
		filters=[
			["name", "in", event_names],
			["starts_on", ">=", now],
			["starts_on", "<=", end],
		],
		fields=[
			"name",
			"subject",
			"starts_on",
			"ends_on",
			"event_category",
			"location",
			"google_meet_link",
		],
		order_by="starts_on asc",
		ignore_permissions=True,
	)


@frappe.whitelist()
def get_my_day(user: str | None = None) -> dict:
	from frappe.utils import today

	user = user or frappe.session.user
	if user != frappe.session.user and not set(frappe.get_roles()) & REVIEWER_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	day = today()

	tasks = frappe.get_all(
		"Task",
		filters=[
			["_assign", "like", f"%{user}%"],
			["custom_planned_for", "=", day],
		],
		fields=["name", "subject", "status", "priority", "project", "custom_request", "exp_end_date"],
		order_by="priority desc",
		ignore_permissions=True,
	)
	meetings = get_upcoming_meetings(for_user=user, within_days=1)
	return {"date": day, "tasks": tasks, "meetings": meetings}


@frappe.whitelist()
def get_developer_backlog(user: str | None = None, project: str | None = None) -> list[dict]:
	"""Every open task assigned to a developer, not just today's (unlike My Day)."""
	user = user or frappe.session.user
	if user != frappe.session.user and not set(frappe.get_roles()) & REVIEWER_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	filters: list = [
		["_assign", "like", f"%{user}%"],
		["status", "not in", ["Completed", "Cancelled"]],
	]
	if project:
		filters.append(["project", "=", project])

	return frappe.get_all(
		"Task",
		filters=filters,
		fields=["name", "subject", "status", "priority", "project", "custom_planned_for", "exp_end_date"],
		order_by="custom_planned_for asc, priority desc",
		ignore_permissions=True,
	)


@frappe.whitelist()
def get_customer_workload(project: str) -> list[dict]:
	if not (
		set(frappe.get_roles()) & REVIEWER_ROLES
		or frappe.db.exists("Request", {"project": project, "raised_by_user": frappe.session.user})
	):
		frappe.throw(_("Not permitted to view this project."), frappe.PermissionError)

	tasks = frappe.get_all(
		"Task",
		filters={"project": project, "status": ["!=", "Cancelled"]},
		fields=["status", "_assign"],
		ignore_permissions=True,
	)
	per_dev: dict[str, dict] = {}
	for task in tasks:
		assignees = json.loads(task["_assign"]) if task.get("_assign") else []
		for email in assignees:
			bucket = per_dev.setdefault(email, {"user": email, "active_tasks": 0, "completed_tasks": 0})
			if task["status"] == "Completed":
				bucket["completed_tasks"] += 1
			else:
				bucket["active_tasks"] += 1

	names = _resolve_user_display_names(set(per_dev))
	result = []
	for email, bucket in per_dev.items():
		bucket["full_name"] = names.get(email, email)
		result.append(bucket)
	result.sort(key=lambda b: b["active_tasks"], reverse=True)
	return result


@frappe.whitelist()
def update_task_status(name: str, status: str) -> dict:
	"""Validates status against Task's own Select options, not a hardcoded list."""
	if not set(frappe.get_roles()) & REVIEWER_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	valid_statuses = frappe.get_meta("Task").get_field("status").options.split("\n")
	if status not in valid_statuses:
		frappe.throw(_("Invalid status."), frappe.ValidationError)

	if not frappe.db.exists("Task", name):
		frappe.throw(_("Task not found."), frappe.DoesNotExistError)

	frappe.db.set_value("Task", name, "status", status)
	return {"name": name, "status": status}
