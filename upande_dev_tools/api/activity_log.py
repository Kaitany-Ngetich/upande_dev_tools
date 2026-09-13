import frappe

DEV_TOOLS_ROLES = {"Dev Team"}


def _require_dev_team():
	if not DEV_TOOLS_ROLES & set(frappe.get_roles()):
		frappe.throw("Not permitted", frappe.PermissionError)


@frappe.whitelist()
def get_activity_log(
	status: str | None = None, search: str | None = None, start: int = 0, limit: int = 50
) -> dict:
	_require_dev_team()
	filters: dict = {}
	if status:
		filters["status"] = status
	if search:
		filters["title"] = ["like", f"%{search}%"]

	rows = frappe.get_all(
		"Developer Activity Log",
		filters=filters,
		fields=[
			"name",
			"activity_time",
			"activity_type",
			"title",
			"description",
			"status",
			"source",
			"reference_doctype",
			"reference_name",
			"performed_by",
		],
		order_by="activity_time desc",
		start=start,
		limit_page_length=limit,
		ignore_permissions=True,
	)
	total = frappe.db.count("Developer Activity Log", filters=filters)
	return {"rows": rows, "total": total}
