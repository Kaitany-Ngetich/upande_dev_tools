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
def promote_to_task(name: str) -> dict:
	from frappe.model.workflow import apply_workflow

	doc = frappe.get_doc("Request", name)
	action = "Promote Note" if doc.request_type == "Note" else "Schedule"
	updated = apply_workflow(doc, action)
	return updated.as_dict()


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
		fields=["name", "subject", "starts_on", "ends_on", "event_category", "location"],
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
	"""Every open (not Completed/Cancelled) task assigned to a developer, not just today's -
	the "for more than the day" view My Day deliberately doesn't provide, so a PM can see the
	whole of someone's plate, not just what's due today."""
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
	"""Per-developer breakdown of a customer's own active work - how many of their tasks each
	developer currently has, and how many are done. Deliberately minimal (no titles, no due
	dates, no overdue/incoming detail - that's the PM's own get_team_workload) so it's safe to
	show a customer.

	Permission is intentionally narrower than "can read this Project": this app doesn't set up
	Project-level User Permissions for customer/employee accounts, so has_permission("Project",
	...) would fail for the very users this endpoint exists for. Instead: a reviewer (Dev
	Team/PM/System Manager) can see any project, and anyone else can see a project only if
	they've actually raised a request against it - a real, checkable relationship instead of a
	permission this app doesn't grant them.
	"""
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
