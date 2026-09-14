import os

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
	"""Whether user_roles may access `route` (leading slash optional). A route with
	no `Dev Portal Page` registration yet is treated as permitted — an optimistic
	default for a route a later sub-project hasn't registered as a page yet, so
	behavior for not-yet-built dashboards (dev-dashboard, pm-dashboard, as of this
	sub-project) matches what it was before this function existed. This exists so
	resolve_home_route never hands back a route enforce_page_access would then
	deny for the same user — that combination was a self-redirect infinite loop.
	"""
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
		# resolve_home_route just picked the very route we're about to deny — redirecting
		# there would loop forever. Fall through to a route this function never gates.
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


def asset_version(path: str) -> str:
	"""Cache key for a file under this app's public/ - these are plain <link>/<script>
	tags, so they miss the bundler's hashed filenames and are served with a 12 hour
	max-age."""
	full = frappe.get_app_path("upande_dev_tools", "public", *path.split("/"))
	try:
		return str(int(os.path.getmtime(full)))
	except OSError:
		return frappe.utils.random_string(8)
