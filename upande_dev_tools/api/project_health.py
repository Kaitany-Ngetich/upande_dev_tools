import json

import frappe
from frappe.utils import today

PM_ROLES = {"Projects Manager"}

# Requests already accepted and either scheduled or being worked - the pool that's actually
# headed to (or already with) a developer, as opposed to "Under Review"/"Deferred" which have
# no assignee yet.
INCOMING_REQUEST_STATES = ["Scheduled", "In Progress"]


def _require_projects_manager():
	if not PM_ROLES & set(frappe.get_roles()):
		frappe.throw("Not permitted", frappe.PermissionError)


def _resolve_user_display_names(emails: set[str]) -> dict[str, str]:
	if not emails:
		return {}
	rows = frappe.get_all("User", filters={"name": ["in", list(emails)]}, fields=["name", "full_name"])
	return {row.name: row.full_name or row.name for row in rows}


@frappe.whitelist()
def get_project_health(scope: str | None = None) -> dict:
	_require_projects_manager()

	filters: dict = {"status": ["!=", "Cancelled"]}
	if scope:
		if scope not in ("Internal", "External"):
			frappe.throw("scope must be 'Internal' or 'External'.", frappe.ValidationError)
		filters["custom_project_scope"] = scope

	projects = frappe.get_all(
		"Project",
		filters=filters,
		fields=["name", "project_name", "status", "custom_project_scope", "customer"],
		order_by="project_name asc",
		ignore_permissions=True,
	)
	for project in projects:
		project["total_tasks"] = frappe.db.count("Task", {"project": project.name})
		project["completed_tasks"] = frappe.db.count("Task", {"project": project.name, "status": "Completed"})
		project["overdue_tasks"] = frappe.db.count(
			"Task",
			{
				"project": project.name,
				"status": ["not in", ["Completed", "Cancelled"]],
				"exp_end_date": ["<", today()],
			},
		)
		project["open_requests"] = frappe.db.count(
			"Request", {"project": project.name, "workflow_state": ["not in", ["Completed", "Rejected"]]}
		)

	return {
		"project_count": len(projects),
		"total_overdue_tasks": sum(p["overdue_tasks"] for p in projects),
		"total_open_requests": sum(p["open_requests"] for p in projects),
		"projects": projects,
	}


@frappe.whitelist()
def get_team_workload(project: str | None = None) -> dict:
	"""Per-developer workload, open-vs-closed task totals, and incoming (accepted, not yet
	shown as a specific dev's own day) request counts - the aggregate picture My Day/Backlog
	Board give one dev or one project at a time, but no view previously gave across the whole
	team at once."""
	_require_projects_manager()

	task_filters: dict = {"project": project} if project else {}
	day = today()

	open_tasks = frappe.get_all(
		"Task",
		filters={**task_filters, "status": ["not in", ["Completed", "Cancelled"]]},
		fields=["name", "status", "priority", "custom_planned_for", "exp_end_date", "_assign"],
		ignore_permissions=True,
	)
	closed_tasks_count = frappe.db.count(
		"Task", {**task_filters, "status": ["in", ["Completed", "Cancelled"]]}
	)

	per_dev: dict[str, dict] = {}

	def _bucket(email: str) -> dict:
		return per_dev.setdefault(
			email, {"user": email, "open_tasks": 0, "due_today": 0, "overdue": 0, "incoming_requests": 0}
		)

	for task in open_tasks:
		assignees = json.loads(task["_assign"]) if task.get("_assign") else []
		if not assignees:
			assignees = ["Unassigned"]
		for email in assignees:
			bucket = _bucket(email)
			bucket["open_tasks"] += 1
			if task.get("custom_planned_for") == day:
				bucket["due_today"] += 1
			if task.get("exp_end_date") and task["exp_end_date"] < day:
				bucket["overdue"] += 1

	incoming_requests = frappe.get_all(
		"Request",
		filters={**task_filters, "workflow_state": ["in", INCOMING_REQUEST_STATES]},
		fields=["name", "linked_task"],
		ignore_permissions=True,
	)
	linked_task_names = [r["linked_task"] for r in incoming_requests if r.get("linked_task")]
	task_assignees: dict[str, list[str]] = {}
	if linked_task_names:
		rows = frappe.get_all("Task", filters={"name": ["in", linked_task_names]}, fields=["name", "_assign"])
		task_assignees = {
			row.name: (json.loads(row["_assign"]) if row.get("_assign") else []) for row in rows
		}
	for req in incoming_requests:
		assignees = task_assignees.get(req.get("linked_task"), [])
		for email in assignees or ["Unassigned"]:
			_bucket(email)["incoming_requests"] += 1

	user_names = _resolve_user_display_names({email for email in per_dev if email != "Unassigned"})
	for email, bucket in per_dev.items():
		bucket["full_name"] = "Unassigned" if email == "Unassigned" else user_names.get(email, email)

	developers = sorted(per_dev.values(), key=lambda b: b["open_tasks"], reverse=True)

	return {
		"date": day,
		"open_tasks": len(open_tasks),
		"closed_tasks": closed_tasks_count,
		"developers": developers,
	}
