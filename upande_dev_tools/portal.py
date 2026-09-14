# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import frappe

HOME_ROUTE_BY_ROLE = (
	("Dev Team", "/dev-dashboard"),
	("Projects Manager", "/pm-dashboard"),
)
DEFAULT_AUTHENTICATED_ROUTE = "/requests-portal"
LOGIN_ROUTE = "/login"


def resolve_home_route(user: str | None = None) -> str:
	user = user or frappe.session.user
	if user == "Guest":
		return LOGIN_ROUTE

	roles = set(frappe.get_roles(user))
	for role, route in HOME_ROUTE_BY_ROLE:
		if role in roles and _route_permits(route, roles):
			return route
	if _route_permits(DEFAULT_AUTHENTICATED_ROUTE, roles):
		return DEFAULT_AUTHENTICATED_ROUTE
	return "/app"


def _fetch_page(route: str) -> frappe._dict | None:
	return frappe.db.get_value("Dev Portal Page", route, ["name", "require_all_roles"], as_dict=True)


def _allowed_roles(page_name: str) -> set[str]:
	return set(
		frappe.get_all(
			"Has Role",
			filters={"parent": page_name, "parenttype": "Dev Portal Page"},
			pluck="role",
		)
	)


def _is_permitted(allowed: set[str], require_all: bool, user_roles: set[str]) -> bool:
	if not allowed:
		return False
	if require_all:
		return allowed <= user_roles
	return bool(user_roles & allowed)


def _route_permits(route: str, user_roles: set[str]) -> bool:
	"""Unregistered route -> permitted."""
	page = _fetch_page(route.lstrip("/"))
	if not page:
		return True
	return _is_permitted(_allowed_roles(page.name), bool(page.require_all_roles), user_roles)


def enforce_page_access(route: str) -> None:
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = f"{LOGIN_ROUTE}?redirect-to=/{route}"
		raise frappe.Redirect

	page = _fetch_page(route)
	if page and _is_permitted(
		_allowed_roles(page.name), bool(page.require_all_roles), set(frappe.get_roles())
	):
		return

	target = resolve_home_route()
	if target == f"/{route}":
		# avoid redirect loop: target must not equal the denied route
		target = "/app"
	frappe.local.flags.redirect_location = target
	raise frappe.Redirect


def get_nav_items(user: str | None = None) -> list[dict]:
	user = user or frappe.session.user
	if user == "Guest":
		return []

	pages = frappe.get_all(
		"Dev Portal Page",
		fields=["name", "route", "title", "icon", "nav_group", "sort_order", "require_all_roles"],
		order_by="nav_group asc, sort_order asc, title asc",
	)
	if not pages:
		return []

	role_rows = frappe.get_all(
		"Has Role",
		filters={"parent": ["in", [page.name for page in pages]], "parenttype": "Dev Portal Page"},
		fields=["parent", "role"],
	)
	roles_by_page: dict[str, set[str]] = {}
	for row in role_rows:
		roles_by_page.setdefault(row.parent, set()).add(row.role)

	user_roles = set(frappe.get_roles(user))
	return [
		page
		for page in pages
		if _is_permitted(roles_by_page.get(page.name, set()), bool(page.require_all_roles), user_roles)
	]
