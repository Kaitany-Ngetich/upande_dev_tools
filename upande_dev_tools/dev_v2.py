# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
"""Shared page context for the Dev Tools v2 www pages (www/*-v2.html).

Same contract as upande_packhouse.packhouse_v2 / upande_agriculture.agri_v2: every page
controller calls `page_context(...)` so the shell (templates/includes/dev_v2/shell_start.html)
gets the CSRF token, company, user and sidebar, and the shell shows a BETA label.

ACCESS: a v2 page is open to exactly the roles that may open its current portal page. Each
page passes that page's route as `access_route`; `portal.enforce_page_access` (Dev Portal
Page + Has Role) decides, and the sidebar only lists pages the user may open. The page's
API endpoints must also enforce the same rule themselves (an endpoint can be called without
the page), exactly as the current endpoints do.
"""

import os
from urllib.parse import urlencode

import frappe
from frappe.sessions import get_csrf_token

from upande_dev_tools import portal

_PUBLIC = os.path.join(os.path.dirname(__file__), "public")

#: Sidebar, in order: (group, [(page key, label, href, current portal route, icon), ...]).
#: Page key == the www page name without "-v2"; the current route is what access follows.
NAV = [
	(
		"Overview",
		[("dev-tools", "Dev Tools Overview", "/dev-tools-v2", "requests-portal", "layout")],
	),
	(
		"Developer",
		[
			("dev-dashboard", "Dev Dashboard", "/dev-dashboard-v2", "dev-dashboard", "chart"),
			("my-backlog", "My Backlog", "/my-backlog-v2", "my-backlog", "user-plus"),
			("backlog-board", "Backlog Board", "/backlog-board-v2", "backlog-board", "grid"),
			("hooks-explorer", "Hooks Explorer", "/hooks-explorer-v2", "hooks-explorer", "tree"),
			("code-editor", "Code Editor", "/code-editor-v2", "code-editor", "doc"),
			("code-snapshots", "Code Snapshots", "/code-snapshots-v2", "code-snapshots", "cube"),
			("version-check", "Version Check", "/version-check-v2", "dev-dashboard", "check"),
			("activity-log", "Activity Log", "/activity-log-v2", "activity-log", "doc"),
			("data-seeder", "Data Seeder", "/data-seeder-v2", "dev-data-seeder", "down"),
		],
	),
	(
		"Management",
		[
			("pm-dashboard", "PM Dashboard", "/pm-dashboard-v2", "pm-dashboard", "chart"),
			("review-queue", "Review Queue", "/review-queue-v2", "review-queue", "clipboard"),
			("requests", "Requests", "/requests-v2", "requests-portal", "layers"),
			("deployments", "Deployments", "/deployments-v2", "deployments", "truck"),
		],
	),
	(
		"Admin",
		[
			("master-data", "Master Data", "/master-data-v2", "master-data", "gear"),
			("dev-portal-settings", "Settings", "/dev-portal-settings-v2", "dev-portal-settings", "gear"),
		],
	),
]


def _nav_for(user_roles):
	out = []
	for group, items in NAV:
		allowed = [
			(key, label, href, icon)
			for key, label, href, route, icon in items
			if portal._route_permits("/" + route, user_roles)
		]
		if allowed:
			out.append((group, allowed))
	return out


def page_context(context, active_page, title, access_route=None, section=None):
	"""Fill the context every Dev Tools v2 page's shell needs. Returns context."""
	if frappe.session.user == "Guest":
		path = frappe.request.full_path if frappe.request else "/" + active_page + "-v2"
		frappe.local.flags.redirect_location = "/login?" + urlencode({"redirect-to": path.rstrip("?")})
		raise frappe.Redirect(302)
	route = access_route or dict((k, r) for _g, items in NAV for k, _l, _h, r, _i in items).get(active_page)
	if route:
		portal.enforce_page_access(route)
	context.no_cache = 1
	context.csrf_token = get_csrf_token()
	context.ph_active = active_page
	context.ph_title = title
	context.ph_section = section or _section_of(active_page)
	user = frappe.session.user
	full = frappe.utils.get_fullname(user) if user != "Guest" else ""
	context.ph_user = user
	context.ph_user_name = full or user.split("@")[0]
	context.ph_company = frappe.db.get_single_value("Global Defaults", "default_company") or "Upande"
	context.ph_nav = _nav_for(set(frappe.get_roles(user)))
	context.ph_v = _asset_version()
	return context


def _asset_version():
	"""Cache-buster for the shared css/js: changes whenever either file changes."""
	try:
		return str(
			int(
				max(
					os.path.getmtime(os.path.join(_PUBLIC, "css", "dev-v2.css")),
					os.path.getmtime(os.path.join(_PUBLIC, "js", "dev-v2.js")),
				)
			)
		)
	except OSError:
		return "1"


def _section_of(active_page):
	for group, items in NAV:
		if any(i[0] == active_page for i in items):
			return group
	return "Dev Tools"
