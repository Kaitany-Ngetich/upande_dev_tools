# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import frappe
from frappe import _

SETTINGS_ROLES = ("Dev Team", "System Manager")
SETTINGS_ROUTE = "dev-portal-settings"


def _require_dual_role(role_a: str, role_b: str) -> None:
	roles = set(frappe.get_roles())
	if not ({role_a, role_b} <= roles):
		frappe.throw(_("Not permitted."), frappe.PermissionError)


@frappe.whitelist()
def get_registered_pages() -> list[dict]:
	_require_dual_role(*SETTINGS_ROLES)

	pages = frappe.get_all(
		"Dev Portal Page",
		fields=["name", "route", "title", "nav_group", "sort_order", "require_all_roles"],
		order_by="nav_group asc, sort_order asc, title asc",
	)
	role_rows = frappe.get_all(
		"Has Role",
		filters={"parent": ["in", [page.name for page in pages]], "parenttype": "Dev Portal Page"},
		fields=["parent", "role"],
	)
	roles_by_page: dict[str, list[str]] = {}
	for row in role_rows:
		roles_by_page.setdefault(row.parent, []).append(row.role)

	for page in pages:
		page["allowed_roles"] = roles_by_page.get(page.name, [])
	return pages


@frappe.whitelist()
def update_page_roles(route: str, roles: list[str] | str, require_all_roles: bool | int = False) -> dict:
	_require_dual_role(*SETTINGS_ROLES)

	if isinstance(roles, str):
		roles = frappe.parse_json(roles)

	if route == SETTINGS_ROUTE:
		new_require_all = bool(int(require_all_roles))
		proposed = set(roles)
		settings_roles = set(SETTINGS_ROLES)
		# OR mode: proposed must be a superset of settings_roles. AND mode: a subset.
		still_reachable = proposed <= settings_roles if new_require_all else proposed >= settings_roles
		if not still_reachable:
			frappe.throw(
				_("The settings page must always stay reachable by both Dev Team and System Manager."),
				frappe.ValidationError,
			)

	doc = frappe.get_doc("Dev Portal Page", route)
	doc.allowed_roles = []
	for role in roles:
		doc.append("allowed_roles", {"role": role})
	doc.require_all_roles = 1 if int(require_all_roles) else 0
	doc.save(ignore_permissions=True)
	return doc.as_dict()
