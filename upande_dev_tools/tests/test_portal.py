# Copyright (c) 2026, Upande Limited

import frappe
from frappe.tests import IntegrationTestCase

from upande_dev_tools.api.code_editor import get_installed_apps as code_editor_get_installed_apps
from upande_dev_tools.api.dashboard import get_dashboard_data
from upande_dev_tools.api.hooks_explorer import get_installed_apps as hooks_explorer_get_installed_apps
from upande_dev_tools.portal import enforce_page_access, get_nav_items, resolve_home_route
from upande_dev_tools.setup import register_dev_portal_page
from upande_dev_tools.www.code_editor import get_context as code_editor_get_context
from upande_dev_tools.www.dev_dashboard import get_context as dev_dashboard_get_context
from upande_dev_tools.www.dev_tools import get_context
from upande_dev_tools.www.hooks_explorer import get_context as hooks_explorer_get_context
from upande_dev_tools.www.my_day import get_context as my_day_get_context


class IntegrationTestPortal(IntegrationTestCase):
	def _make_user(self, email: str, roles: list[str]) -> str:
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Test", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		user = frappe.get_doc("User", email)
		if roles:
			user.add_roles(*roles)
		return email

	def _make_page(
		self,
		route: str,
		roles: list[str],
		require_all_roles: bool = False,
		nav_group: str = "Test",
		sort_order: int = 0,
	) -> str:
		if frappe.db.exists("Dev Portal Page", route):
			frappe.delete_doc("Dev Portal Page", route, ignore_permissions=True, force=True)
		return (
			frappe.get_doc(
				{
					"doctype": "Dev Portal Page",
					"route": route,
					"title": route,
					"nav_group": nav_group,
					"sort_order": sort_order,
					"require_all_roles": 1 if require_all_roles else 0,
					"allowed_roles": [{"role": role} for role in roles],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_resolve_home_route_prioritizes_dev_team(self) -> None:
		dev = self._make_user("portal-dev@example.test", ["Dev Team"])
		self.assertEqual(resolve_home_route(dev), "/dev-dashboard")

	def test_resolve_home_route_falls_back_to_projects_manager(self) -> None:
		pm = self._make_user("portal-pm@example.test", ["Projects Manager"])
		self.assertEqual(resolve_home_route(pm), "/pm-dashboard")

	def test_resolve_home_route_defaults_for_any_other_authenticated_user(self) -> None:
		other = self._make_user("portal-other@example.test", [])
		self.assertEqual(resolve_home_route(other), "/requests-portal")

	def test_resolve_home_route_sends_guest_to_login(self) -> None:
		self.assertEqual(resolve_home_route("Guest"), "/login")

	def test_enforce_page_access_permits_matching_role(self) -> None:
		self._make_page("portal-test-permit", ["Dev Team"])
		dev = self._make_user("portal-permit@example.test", ["Dev Team"])
		frappe.set_user(dev)
		try:
			enforce_page_access("portal-test-permit")  # must not raise
		finally:
			frappe.set_user("Administrator")

	def test_enforce_page_access_redirects_when_denied(self) -> None:
		self._make_page("portal-test-deny", ["Projects Manager"])
		dev = self._make_user("portal-deny@example.test", ["Dev Team"])
		frappe.set_user(dev)
		try:
			with self.assertRaises(frappe.Redirect):
				enforce_page_access("portal-test-deny")
			self.assertEqual(frappe.local.flags.redirect_location, "/dev-dashboard")
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None

	def test_enforce_page_access_requires_every_role_when_require_all_roles(self) -> None:
		self._make_page("portal-test-dual", ["Dev Team", "System Manager"], require_all_roles=True)
		dev_only = self._make_user("portal-dual-partial@example.test", ["Dev Team"])
		frappe.set_user(dev_only)
		try:
			with self.assertRaises(frappe.Redirect):
				enforce_page_access("portal-test-dual")
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None

	def test_enforce_page_access_denies_unregistered_route(self) -> None:
		dev = self._make_user("portal-unregistered@example.test", ["Dev Team"])
		frappe.set_user(dev)
		try:
			with self.assertRaises(frappe.Redirect):
				enforce_page_access("portal-test-does-not-exist")
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None

	def test_enforce_page_access_sends_guest_to_login_with_redirect_param(self) -> None:
		# The Guest check runs before any page lookup, so this route need not exist —
		# self-contained, not dependent on another test method having created a page.
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.Redirect):
				enforce_page_access("portal-test-guest-route")
			self.assertEqual(
				frappe.local.flags.redirect_location, "/login?redirect-to=/portal-test-guest-route"
			)
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None

	def test_get_nav_items_only_returns_permitted_pages(self) -> None:
		self._make_page("portal-nav-visible", ["Dev Team"], nav_group="Group A", sort_order=1)
		self._make_page("portal-nav-hidden", ["Projects Manager"], nav_group="Group A", sort_order=2)
		dev = self._make_user("portal-nav@example.test", ["Dev Team"])
		items = get_nav_items(dev)
		routes = {item["route"] for item in items}
		self.assertIn("portal-nav-visible", routes)
		self.assertNotIn("portal-nav-hidden", routes)

	def test_get_nav_items_empty_for_guest(self) -> None:
		self.assertEqual(get_nav_items("Guest"), [])

	def test_enforce_page_access_denies_when_allowed_roles_empty(self) -> None:
		self._make_page("portal-test-no-roles", [])
		dev = self._make_user("portal-no-roles@example.test", ["Dev Team", "System Manager"])
		frappe.set_user(dev)
		try:
			with self.assertRaises(frappe.Redirect):
				enforce_page_access("portal-test-no-roles")
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None

	def test_register_dev_portal_page_is_create_only(self) -> None:
		if frappe.db.exists("Dev Portal Page", "portal-register-test"):
			frappe.delete_doc("Dev Portal Page", "portal-register-test", ignore_permissions=True, force=True)

		register_dev_portal_page(
			route="portal-register-test",
			title="Register Test",
			icon="test",
			nav_group="Test",
			sort_order=1,
			roles=["Dev Team"],
		)
		doc = frappe.get_doc("Dev Portal Page", "portal-register-test")
		self.assertEqual([row.role for row in doc.allowed_roles], ["Dev Team"])

		# An admin's later edit (e.g. via the settings screen) must survive re-registration.
		doc.allowed_roles = []
		doc.append("allowed_roles", {"role": "System Manager"})
		doc.save(ignore_permissions=True)

		register_dev_portal_page(
			route="portal-register-test",
			title="Register Test",
			icon="test",
			nav_group="Test",
			sort_order=1,
			roles=["Dev Team"],
		)
		doc.reload()
		self.assertEqual([row.role for row in doc.allowed_roles], ["System Manager"])

	def test_dev_portal_settings_page_is_self_registered(self) -> None:
		self.assertTrue(frappe.db.exists("Dev Portal Page", "dev-portal-settings"))
		doc = frappe.get_doc("Dev Portal Page", "dev-portal-settings")
		self.assertTrue(doc.require_all_roles)
		self.assertEqual({row.role for row in doc.allowed_roles}, {"Dev Team", "System Manager"})

	def test_dev_tools_entry_redirects_to_resolved_home(self) -> None:
		dev = self._make_user("dev-tools-entry@example.test", ["Dev Team"])
		frappe.set_user(dev)
		try:
			with self.assertRaises(frappe.Redirect):
				get_context({})
			self.assertEqual(frappe.local.flags.redirect_location, "/dev-dashboard")
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None

	def test_resolve_home_route_skips_role_priority_route_that_denies_user(self) -> None:
		self._make_page("dev-dashboard", [])  # registered but denies everyone (empty allowed_roles)
		dev = self._make_user("home-route-skip@example.test", ["Dev Team"])
		try:
			self.assertEqual(resolve_home_route(dev), "/requests-portal")
		finally:
			frappe.delete_doc("Dev Portal Page", "dev-dashboard", ignore_permissions=True, force=True)
			# "dev-dashboard" is a real, permanently self-registered page (see setup.py) as of
			# the Tools Dashboard port — restore it so later tests see the same state migrate
			# would have left them in, regardless of test execution order.
			register_dev_portal_page(
				route="dev-dashboard",
				title="Dashboard",
				icon="home",
				nav_group="Developer",
				sort_order=10,
				roles=["Dev Team"],
			)

	def test_enforce_page_access_permits_user_holding_every_required_role(self) -> None:
		self._make_page("portal-test-dual-allow", ["Dev Team", "System Manager"], require_all_roles=True)
		both = self._make_user("portal-dual-allow@example.test", ["Dev Team", "System Manager"])
		frappe.set_user(both)
		try:
			enforce_page_access("portal-test-dual-allow")  # must not raise
		finally:
			frappe.set_user("Administrator")

	def test_get_nav_items_requires_every_role_when_require_all_roles(self) -> None:
		self._make_page(
			"portal-nav-dual", ["Dev Team", "System Manager"], require_all_roles=True, nav_group="Group B"
		)
		dev_only = self._make_user("portal-nav-dual-partial@example.test", ["Dev Team"])
		both = self._make_user("portal-nav-dual-both@example.test", ["Dev Team", "System Manager"])
		self.assertNotIn("portal-nav-dual", {item["route"] for item in get_nav_items(dev_only)})
		self.assertIn("portal-nav-dual", {item["route"] for item in get_nav_items(both)})

	def test_dev_tools_entry_redirects_guest_to_login(self) -> None:
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.Redirect):
				get_context({})
			self.assertEqual(frappe.local.flags.redirect_location, "/login")
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None

	def test_enforce_page_access_terminates_loop_when_home_route_is_itself_denied(self) -> None:
		self._make_page("dev-dashboard", [])  # registered but denies everyone
		dev = self._make_user("loop-guard-registered@example.test", ["Dev Team"])
		frappe.set_user(dev)
		try:
			with self.assertRaises(frappe.Redirect):
				enforce_page_access("dev-dashboard")
			# _route_permits already agrees with enforce_page_access's own denial for a
			# *registered* page (both run the identical _is_permitted check), so
			# resolve_home_route already skips this denied route on its own and lands on
			# the next fallback (here, the unregistered default "/requests-portal") without
			# ever needing the new same-route guard below to fire. That guard's registered-page
			# arm exists for defense in depth (see enforce_page_access), not because this
			# scenario can currently loop.
			self.assertEqual(frappe.local.flags.redirect_location, "/requests-portal")
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None
			frappe.delete_doc("Dev Portal Page", "dev-dashboard", ignore_permissions=True, force=True)
			# "dev-dashboard" is a real, permanently self-registered page (see setup.py) as of
			# the Tools Dashboard port — restore it so later tests see the same state migrate
			# would have left them in, regardless of test execution order.
			register_dev_portal_page(
				route="dev-dashboard",
				title="Dashboard",
				icon="home",
				nav_group="Developer",
				sort_order=10,
				roles=["Dev Team"],
			)

	def test_enforce_page_access_terminates_loop_when_home_route_is_unregistered(self) -> None:
		# Uses Projects Manager/"pm-dashboard" rather than Dev Team/"dev-dashboard": the latter
		# is now a real, permanently self-registered page (the Tools Dashboard port), so it can
		# no longer stand in for "a role-priority home route with no page registered yet" —
		# "pm-dashboard" (not yet built) still can.
		pm = self._make_user("loop-guard-unregistered@example.test", ["Projects Manager"])
		frappe.set_user(pm)
		try:
			with self.assertRaises(frappe.Redirect):
				enforce_page_access("pm-dashboard")
			self.assertEqual(frappe.local.flags.redirect_location, "/app")
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None

	def test_hooks_explorer_permits_dev_team_and_denies_others(self) -> None:
		dev = self._make_user("hooks-explorer-dev@example.test", ["Dev Team"])
		other = self._make_user("hooks-explorer-other@example.test", [])

		frappe.set_user(dev)
		try:
			hooks_explorer_get_context({})  # must not raise
		finally:
			frappe.set_user("Administrator")

		frappe.set_user(other)
		try:
			with self.assertRaises(frappe.Redirect):
				hooks_explorer_get_context({})
			self.assertEqual(frappe.local.flags.redirect_location, "/requests-portal")
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None

	def test_dev_dashboard_permits_dev_team_and_denies_others(self) -> None:
		dev = self._make_user("dev-dashboard-dev@example.test", ["Dev Team"])
		other = self._make_user("dev-dashboard-other@example.test", [])

		frappe.set_user(dev)
		try:
			dev_dashboard_get_context({})  # must not raise
		finally:
			frappe.set_user("Administrator")

		frappe.set_user(other)
		try:
			with self.assertRaises(frappe.Redirect):
				dev_dashboard_get_context({})
			self.assertEqual(frappe.local.flags.redirect_location, "/requests-portal")
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None

	def test_code_editor_permits_dev_team_and_denies_others(self) -> None:
		dev = self._make_user("code-editor-dev@example.test", ["Dev Team"])
		other = self._make_user("code-editor-other@example.test", [])

		frappe.set_user(dev)
		try:
			code_editor_get_context({})  # must not raise
		finally:
			frappe.set_user("Administrator")

		frappe.set_user(other)
		try:
			with self.assertRaises(frappe.Redirect):
				code_editor_get_context({})
			self.assertEqual(frappe.local.flags.redirect_location, "/requests-portal")
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None

	def test_resolve_home_route_for_dev_team_is_now_reachable(self) -> None:
		# Closes the gap Sub-project 1's final review flagged: /dev-dashboard is now a real,
		# registered, permitted page for Dev Team, so enforce_page_access on it must NOT hit
		# the loop-guard's /app fallback (that fallback only fires when the resolved home route
		# is itself denied or unregistered).
		dev = self._make_user("dev-dashboard-home-route@example.test", ["Dev Team"])
		self.assertEqual(resolve_home_route(dev), "/dev-dashboard")
		frappe.set_user(dev)
		try:
			enforce_page_access("dev-dashboard")  # must not raise
		finally:
			frappe.set_user("Administrator")

	def test_dev_tools_apis_deny_users_without_dev_team_role(self) -> None:
		other = self._make_user("dev-tools-api-noperm@example.test", [])
		frappe.set_user(other)
		try:
			with self.assertRaises(frappe.PermissionError):
				get_dashboard_data()
			with self.assertRaises(frappe.PermissionError):
				hooks_explorer_get_installed_apps()
			with self.assertRaises(frappe.PermissionError):
				code_editor_get_installed_apps()
		finally:
			frappe.set_user("Administrator")

	def test_developer_nav_group_lists_all_tools_in_order(self) -> None:
		dev = self._make_user("developer-nav-order@example.test", ["Dev Team"])
		items = get_nav_items(dev)
		developer_routes = [item["route"] for item in items if item["nav_group"] == "Developer"]
		self.assertEqual(
			developer_routes, ["dev-dashboard", "hooks-explorer", "code-editor", "my-day"]
		)

	def test_ported_pages_are_registered_with_correct_attributes(self) -> None:
		expected = {
			"dev-dashboard": ("Dashboard", "home", 10),
			"hooks-explorer": ("Hooks Explorer", "search", 20),
			"code-editor": ("Code Editor", "code", 30),
		}
		for route, (title, icon, sort_order) in expected.items():
			doc = frappe.get_doc("Dev Portal Page", route)
			self.assertEqual(doc.title, title)
			self.assertEqual(doc.icon, icon)
			self.assertEqual(doc.nav_group, "Developer")
			self.assertEqual(doc.sort_order, sort_order)
			self.assertEqual({row.role for row in doc.allowed_roles}, {"Dev Team"})

	def test_my_day_permits_dev_team_and_denies_others(self) -> None:
		dev = self._make_user("my-day-dev@example.test", ["Dev Team"])
		other = self._make_user("my-day-other@example.test", [])

		frappe.set_user(dev)
		try:
			my_day_get_context({})  # must not raise
		finally:
			frappe.set_user("Administrator")

		frappe.set_user(other)
		try:
			with self.assertRaises(frappe.Redirect):
				my_day_get_context({})
			self.assertEqual(frappe.local.flags.redirect_location, "/requests-portal")
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None

	def test_my_day_page_is_registered_with_correct_attributes(self) -> None:
		doc = frappe.get_doc("Dev Portal Page", "my-day")
		self.assertEqual(doc.title, "My Day")
		self.assertEqual(doc.icon, "calendar")
		self.assertEqual(doc.nav_group, "Developer")
		self.assertEqual(doc.sort_order, 40)
		self.assertEqual({row.role for row in doc.allowed_roles}, {"Dev Team"})
