import frappe
from frappe.utils import today

PM_ROLES = {"Projects Manager"}


def _require_projects_manager():
	if not PM_ROLES & set(frappe.get_roles()):
		frappe.throw("Not permitted", frappe.PermissionError)


@frappe.whitelist()
def get_project_health() -> dict:
	_require_projects_manager()

	projects = frappe.get_all(
		"Project",
		filters={"status": ["!=", "Cancelled"]},
		fields=["name", "project_name", "status"],
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
