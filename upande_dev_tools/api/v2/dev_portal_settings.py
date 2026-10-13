# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
"""Settings v2 reads: the registered portal pages with who can open them, and the peak-hours window.

Nothing in this module writes. The page's two saves call the existing endpoints in
api/dev_portal_settings.py (update_page_roles, update_peak_hours_settings), so the
lock-out guard, the both-times rule and the dual-role permission stay exactly as they are.

DEFINITIONS
    can_open(page, user) = portal._is_permitted(page roles, page.require_all_roles, user roles):
        no roles listed          -> nobody
        require_all_roles = 0    -> the user has at least one listed role
        require_all_roles = 1    -> the user has every listed role
    Every signed-in person also holds the role "All" (so a page that lists "All" opens for everyone).
    people(page)  = enabled users (Administrator and Guest left out: Administrator holds every
                    role) for whom can_open is true.
    A v2 page opens under the SAME Dev Portal Page row as its current page (dev_v2.NAV), so a
    row's "also opens" lists the v2 pages that follow it.

IDENTITIES (checked in tests/test_dev_portal_settings_v2.py)
    preview.after = |users that can open under the proposed roles|
    preview.before = people(page) for the saved roles
    gain + lose = users whose answer changes; after = before - lose + gain

ACCESS: identical to the current endpoints. get_settings and preview_access need Dev Team AND
System Manager (api.dev_portal_settings._require_dual_role). The page also reads the peak-hours
window for Projects Manager through the existing get_peak_hours_settings.
"""

import frappe

from upande_dev_tools import portal
from upande_dev_tools.api.dev_portal_settings import (
	SETTINGS_ROLES,
	SETTINGS_ROUTE,
	_require_dual_role,
)
from upande_dev_tools.dev_v2 import NAV

#: Accounts that are never counted as people (Administrator holds every role).
SYSTEM_USERS = ("Administrator", "Guest")
#: Names listed in a "who gains / loses access" preview.
PREVIEW_NAMES = 10


def _roles_by_user() -> dict[str, set[str]]:
	"""{enabled user: roles}, each with the implicit role "All"."""
	rows = frappe.db.sql(
		"""select h.parent, h.role from `tabHas Role` h
		join `tabUser` u on u.name = h.parent
		where h.parenttype = 'User' and u.enabled = 1 and u.name not in %(skip)s""",
		{"skip": SYSTEM_USERS},
	)
	users = frappe.get_all("User", {"enabled": 1, "name": ["not in", SYSTEM_USERS]}, pluck="name")
	roles = {u: {"All"} for u in users}
	for user, role in rows:
		roles.setdefault(user, {"All"}).add(role)
	return roles


def _can_open(allowed: set[str], require_all: bool, roles_of: dict[str, set[str]]) -> set[str]:
	"""Users in `roles_of` that can open a page with this rule."""
	return {u for u, r in roles_of.items() if portal._is_permitted(allowed, require_all, r)}


def _v2_pages_by_route() -> dict[str, list[dict]]:
	"""{current route: [v2 pages that open under it]}."""
	out: dict[str, list[dict]] = {}
	for _group, items in NAV:
		for _key, label, href, route, _icon in items:
			out.setdefault(route, []).append({"label": label, "href": href})
	return out


def _peak_now() -> bool:
	from upande_dev_tools.upande_dev_tools.doctype.deployment_request.deployment_request import is_peak_hours

	return is_peak_hours()


@frappe.whitelist()
def get_settings() -> dict:
	"""Everything the page shows, in one read (Dev Team AND System Manager only)."""
	_require_dual_role(*SETTINGS_ROLES)

	pages = frappe.get_all(
		"Dev Portal Page",
		fields=["name", "route", "title", "nav_group", "icon", "sort_order", "require_all_roles"],
		order_by="nav_group asc, sort_order asc, title asc",
	)
	role_rows = frappe.get_all(
		"Has Role",
		filters={"parent": ["in", [p.name for p in pages]], "parenttype": "Dev Portal Page"},
		fields=["parent", "role"],
		order_by="idx asc",
	)
	allowed_by_page: dict[str, list[str]] = {}
	for row in role_rows:
		allowed_by_page.setdefault(row.parent, []).append(row.role)

	roles_of = _roles_by_user()
	v2 = _v2_pages_by_route()
	for page in pages:
		allowed = allowed_by_page.get(page.name, [])
		page["allowed_roles"] = allowed
		page["require_all_roles"] = int(page.require_all_roles or 0)
		page["people"] = len(_can_open(set(allowed), bool(page.require_all_roles), roles_of))
		page["also_opens"] = v2.get(page.route, [])

	role_people: dict[str, int] = {}
	for roles in roles_of.values():
		for role in roles:
			role_people[role] = role_people.get(role, 0) + 1
	roles = [
		{"name": r.name, "people": role_people.get(r.name, 0)}
		for r in frappe.get_all("Role", filters={"disabled": 0}, fields=["name"], order_by="name asc")
	]

	settings = frappe.get_single("Dev Portal Settings")
	return {
		"pages": pages,
		"roles": roles,
		"people_total": len(roles_of),
		"settings_route": SETTINGS_ROUTE,
		"settings_roles": list(SETTINGS_ROLES),
		"peak": {
			"enabled": bool(settings.peak_hours_enabled),
			"start": str(settings.peak_start_time) if settings.peak_start_time else None,
			"end": str(settings.peak_end_time) if settings.peak_end_time else None,
			"inside_now": _peak_now(),
		},
	}


def access_diff(
	roles_of: dict[str, set[str]],
	before: tuple[set[str], bool],
	after: tuple[set[str], bool],
	me: set[str],
) -> dict:
	"""Who gains / loses access when a page's rule changes from `before` to `after`
	(each a (roles, require_all) pair). `me` is the signed-in user's roles."""
	was = _can_open(*before, roles_of)
	will = _can_open(*after, roles_of)
	gain, lose = sorted(will - was), sorted(was - will)
	return {
		"before": len(was),
		"after": len(will),
		"gain_n": len(gain),
		"lose_n": len(lose),
		"gain": gain[:PREVIEW_NAMES],
		"lose": lose[:PREVIEW_NAMES],
		"you_before": portal._is_permitted(*before, me),
		"you_after": portal._is_permitted(*after, me),
	}


@frappe.whitelist()
def preview_access(route: str, roles: list[str] | str, require_all_roles: bool | int = False) -> dict:
	"""What saving this rule would change, without saving it (Dev Team AND System Manager only)."""
	_require_dual_role(*SETTINGS_ROLES)
	if isinstance(roles, str):
		roles = frappe.parse_json(roles)
	page = frappe.db.get_value("Dev Portal Page", route, ["name", "require_all_roles"], as_dict=True)
	if not page:
		frappe.throw(frappe._("Unknown page."), frappe.DoesNotExistError)

	saved = set(portal._allowed_roles(page.name))
	result = access_diff(
		_roles_by_user(),
		(saved, bool(page.require_all_roles)),
		(set(roles), bool(int(require_all_roles))),
		set(frappe.get_roles()),
	)
	for key in ("gain", "lose"):
		result[key] = [{"user": u, "name": frappe.utils.get_fullname(u)} for u in result[key]]
	return result
