import frappe
from frappe.utils import cint

DEV_TOOLS_ROLES = {"Dev Team"}


def _require_dev_team():
	if not DEV_TOOLS_ROLES & set(frappe.get_roles()):
		frappe.throw("Not permitted", frappe.PermissionError)


def _clamp_pagination(start: int, limit: int) -> tuple[int, int]:
	start = max(0, cint(start))
	limit = max(1, min(cint(limit), 200))
	return start, limit


@frappe.whitelist()
def get_snapshots(app: str | None = None, search: str | None = None, start: int = 0, limit: int = 50) -> dict:
	_require_dev_team()
	start, limit = _clamp_pagination(start, limit)
	filters: dict = {}
	if app:
		filters["app"] = app
	if search:
		filters["document_name"] = ["like", f"%{search}%"]

	rows = frappe.get_all(
		"Code Backup Snapshot",
		filters=filters,
		fields=[
			"name",
			"snapshot_time",
			"source_type",
			"document_name",
			"module",
			"app",
			"changed_since_last_backup",
			"backed_up_by",
			"version_label",
		],
		order_by="snapshot_time desc",
		start=start,
		limit_page_length=limit,
		ignore_permissions=True,
	)
	total = frappe.db.count("Code Backup Snapshot", filters=filters)
	return {"rows": rows, "total": total}
