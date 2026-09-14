# Copyright (c) 2026, Upande Limited

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from upande_dev_tools import portal
from upande_dev_tools.api.code_editor import get_installed_apps as code_editor_get_installed_apps
from upande_dev_tools.api.dashboard import get_dashboard_data
from upande_dev_tools.api.hooks_explorer import get_installed_apps as hooks_explorer_get_installed_apps
from upande_dev_tools.api.requests import create_request, get_my_requests
from upande_dev_tools.portal import enforce_page_access, get_nav_items, resolve_home_route
from upande_dev_tools.setup import register_dev_portal_page
from upande_dev_tools.www.activity_log import get_context as activity_log_get_context
from upande_dev_tools.www.backlog_board import get_context as backlog_board_get_context
from upande_dev_tools.www.code_editor import get_context as code_editor_get_context
from upande_dev_tools.www.code_snapshots import get_context as code_snapshots_get_context
from upande_dev_tools.www.dev_dashboard import get_context as dev_dashboard_get_context
from upande_dev_tools.www.dev_tools import get_context
from upande_dev_tools.www.hooks_explorer import get_context as hooks_explorer_get_context
from upande_dev_tools.www.my_day import get_context as my_day_get_context
from upande_dev_tools.www.pm_dashboard import get_context as pm_dashboard_get_context
from upande_dev_tools.www.requests_portal import get_context as requests_portal_get_context
from upande_dev_tools.www.review_queue import get_context as review_queue_get_context


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
		self._make_page("portal-test-home-route-skip", [])  # registered but denies everyone
		dev = self._make_user("home-route-skip@example.test", ["Dev Team"])
		with patch.object(portal, "HOME_ROUTE_BY_ROLE", (("Dev Team", "/portal-test-home-route-skip"),)):
			self.assertEqual(resolve_home_route(dev), "/requests-portal")

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
		self._make_page("portal-test-loop-registered", [])  # registered but denies everyone
		dev = self._make_user("loop-guard-registered@example.test", ["Dev Team"])
		frappe.set_user(dev)
		try:
			with patch.object(portal, "HOME_ROUTE_BY_ROLE", (("Dev Team", "/portal-test-loop-registered"),)):
				with self.assertRaises(frappe.Redirect):
					enforce_page_access("portal-test-loop-registered")
				self.assertEqual(frappe.local.flags.redirect_location, "/requests-portal")
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None

	def test_enforce_page_access_terminates_loop_when_home_route_is_unregistered(self) -> None:
		pm = self._make_user("loop-guard-unregistered@example.test", ["Projects Manager"])
		frappe.set_user(pm)
		try:
			with patch.object(
				portal, "HOME_ROUTE_BY_ROLE", (("Projects Manager", "/portal-test-never-registered"),)
			):
				with self.assertRaises(frappe.Redirect):
					enforce_page_access("portal-test-never-registered")
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

	def test_developer_nav_group_lists_all_seven_tools_in_order(self) -> None:
		dev = self._make_user("developer-nav-order-full@example.test", ["Dev Team"])
		items = get_nav_items(dev)
		developer_routes = [item["route"] for item in items if item["nav_group"] == "Developer"]
		self.assertEqual(
			developer_routes,
			[
				"dev-dashboard",
				"hooks-explorer",
				"code-editor",
				"my-day",
				"backlog-board",
				"code-snapshots",
				"activity-log",
			],
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

	def test_backlog_board_permits_dev_team_and_denies_others(self) -> None:
		dev = self._make_user("backlog-board-dev@example.test", ["Dev Team"])
		other = self._make_user("backlog-board-other@example.test", [])

		frappe.set_user(dev)
		try:
			backlog_board_get_context({})  # must not raise
		finally:
			frappe.set_user("Administrator")

		frappe.set_user(other)
		try:
			with self.assertRaises(frappe.Redirect):
				backlog_board_get_context({})
			self.assertEqual(frappe.local.flags.redirect_location, "/requests-portal")
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None

	def test_backlog_board_page_is_registered_with_correct_attributes(self) -> None:
		doc = frappe.get_doc("Dev Portal Page", "backlog-board")
		self.assertEqual(doc.title, "Backlog Board")
		self.assertEqual(doc.icon, "trello")
		self.assertEqual(doc.nav_group, "Developer")
		self.assertEqual(doc.sort_order, 50)
		# Projects Manager was added (final-review fix wave) so PM Dashboard's drill-down link
		# to /backlog-board?project=<name> works for Projects Manager users too; the underlying
		# get_backlog_board API already independently permission-checks project-scoped reads.
		self.assertEqual({row.role for row in doc.allowed_roles}, {"Dev Team", "Projects Manager"})

	def test_code_snapshots_permits_dev_team_and_denies_others(self) -> None:
		dev = self._make_user("code-snapshots-dev@example.test", ["Dev Team"])
		other = self._make_user("code-snapshots-other@example.test", [])

		frappe.set_user(dev)
		try:
			code_snapshots_get_context({})  # must not raise
		finally:
			frappe.set_user("Administrator")

		frappe.set_user(other)
		try:
			with self.assertRaises(frappe.Redirect):
				code_snapshots_get_context({})
			self.assertEqual(frappe.local.flags.redirect_location, "/requests-portal")
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None

	def test_code_snapshots_page_is_registered_with_correct_attributes(self) -> None:
		doc = frappe.get_doc("Dev Portal Page", "code-snapshots")
		self.assertEqual(doc.title, "Code Snapshots")
		self.assertEqual(doc.icon, "archive")
		self.assertEqual(doc.nav_group, "Developer")
		self.assertEqual(doc.sort_order, 60)
		self.assertEqual({row.role for row in doc.allowed_roles}, {"Dev Team"})

	def test_activity_log_permits_dev_team_and_denies_others(self) -> None:
		dev = self._make_user("activity-log-page-dev@example.test", ["Dev Team"])
		other = self._make_user("activity-log-page-other@example.test", [])

		frappe.set_user(dev)
		try:
			activity_log_get_context({})  # must not raise
		finally:
			frappe.set_user("Administrator")

		frappe.set_user(other)
		try:
			with self.assertRaises(frappe.Redirect):
				activity_log_get_context({})
			self.assertEqual(frappe.local.flags.redirect_location, "/requests-portal")
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None

	def test_activity_log_page_is_registered_with_correct_attributes(self) -> None:
		doc = frappe.get_doc("Dev Portal Page", "activity-log")
		self.assertEqual(doc.title, "Activity Log")
		self.assertEqual(doc.icon, "activity")
		self.assertEqual(doc.nav_group, "Developer")
		self.assertEqual(doc.sort_order, 70)
		self.assertEqual({row.role for row in doc.allowed_roles}, {"Dev Team"})

	def test_pm_dashboard_permits_projects_manager_and_denies_others(self) -> None:
		pm = self._make_user("pm-dashboard-pm@example.test", ["Projects Manager"])
		other = self._make_user("pm-dashboard-other@example.test", [])

		frappe.set_user(pm)
		try:
			pm_dashboard_get_context({})  # must not raise
		finally:
			frappe.set_user("Administrator")

		frappe.set_user(other)
		try:
			with self.assertRaises(frappe.Redirect):
				pm_dashboard_get_context({})
			self.assertEqual(frappe.local.flags.redirect_location, "/requests-portal")
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None

	def test_pm_dashboard_page_is_registered_with_correct_attributes(self) -> None:
		doc = frappe.get_doc("Dev Portal Page", "pm-dashboard")
		self.assertEqual(doc.title, "Dashboard")
		self.assertEqual(doc.icon, "home")
		self.assertEqual(doc.nav_group, "Management")
		self.assertEqual(doc.sort_order, 10)
		self.assertEqual({row.role for row in doc.allowed_roles}, {"Projects Manager"})

	def test_resolve_home_route_for_projects_manager_is_now_reachable(self) -> None:
		# Closes the same gap Sub-project 2's Task 2 closed for Dev Team/dev-dashboard:
		# /pm-dashboard is now a real, registered, permitted page for Projects Manager.
		pm = self._make_user("pm-dashboard-home-route@example.test", ["Projects Manager"])
		self.assertEqual(resolve_home_route(pm), "/pm-dashboard")
		frappe.set_user(pm)
		try:
			enforce_page_access("pm-dashboard")  # must not raise
		finally:
			frappe.set_user("Administrator")

	def test_review_queue_permits_projects_manager_and_denies_others(self) -> None:
		pm = self._make_user("review-queue-pm@example.test", ["Projects Manager"])
		other = self._make_user("review-queue-other@example.test", [])

		frappe.set_user(pm)
		try:
			review_queue_get_context({})  # must not raise
		finally:
			frappe.set_user("Administrator")

		frappe.set_user(other)
		try:
			with self.assertRaises(frappe.Redirect):
				review_queue_get_context({})
			self.assertEqual(frappe.local.flags.redirect_location, "/requests-portal")
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None

	def test_review_queue_page_is_registered_with_correct_attributes(self) -> None:
		doc = frappe.get_doc("Dev Portal Page", "review-queue")
		self.assertEqual(doc.title, "Review Queue")
		self.assertEqual(doc.icon, "check-circle")
		self.assertEqual(doc.nav_group, "Management")
		self.assertEqual(doc.sort_order, 20)
		self.assertEqual({row.role for row in doc.allowed_roles}, {"Projects Manager"})

	def test_management_nav_group_lists_both_pages_in_order(self) -> None:
		pm = self._make_user("management-nav-order@example.test", ["Projects Manager"])
		items = get_nav_items(pm)
		management_routes = [item["route"] for item in items if item["nav_group"] == "Management"]
		self.assertEqual(management_routes, ["pm-dashboard", "review-queue"])

	def test_nav_groups_are_scoped_to_each_users_own_roles(self) -> None:
		dev_only = self._make_user("nav-scope-dev-only@example.test", ["Dev Team"])
		pm_only = self._make_user("nav-scope-pm-only@example.test", ["Projects Manager"])
		both = self._make_user("nav-scope-both@example.test", ["Dev Team", "Projects Manager"])

		# Scoped to the real "Developer"/"Management" nav groups only: other tests in this class
		# register their own throwaway Dev Portal Page rows (nav_group "Test"/"Group A") that are
		# never torn down mid-run (IntegrationTestCase only rolls back at class teardown), so an
		# unfiltered set comparison here would be flaky depending on test execution order.
		known_groups = {"Developer", "Management"}
		dev_groups = {item["nav_group"] for item in get_nav_items(dev_only)} & known_groups
		pm_groups = {item["nav_group"] for item in get_nav_items(pm_only)} & known_groups
		both_groups = {item["nav_group"] for item in get_nav_items(both)} & known_groups

		self.assertEqual(dev_groups, {"Developer"})
		# Projects Manager now also sees "Developer" via backlog-board (final-review fix wave,
		# Fix 1): the PM Dashboard's drill-down link only works once Projects Manager is added
		# to backlog-board's allowed roles, so a Projects-Manager-only user legitimately sees
		# both nav groups now.
		self.assertEqual(pm_groups, {"Developer", "Management"})
		self.assertEqual(both_groups, {"Developer", "Management"})

	def test_requests_portal_permits_any_authenticated_user(self) -> None:
		other = self._make_user("requests-portal-other@example.test", [])
		frappe.set_user(other)
		try:
			requests_portal_get_context({})  # must not raise
		finally:
			frappe.set_user("Administrator")

	def test_requests_portal_denies_guest(self) -> None:
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.Redirect):
				requests_portal_get_context({})
			self.assertEqual(frappe.local.flags.redirect_location, "/login?redirect-to=/requests-portal")
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None

	def test_requests_portal_page_is_registered_with_correct_attributes(self) -> None:
		doc = frappe.get_doc("Dev Portal Page", "requests-portal")
		self.assertEqual(doc.title, "My Requests")
		self.assertEqual(doc.icon, "inbox")
		self.assertEqual(doc.nav_group, "Requests")
		self.assertEqual(doc.sort_order, 10)
		self.assertEqual({row.role for row in doc.allowed_roles}, {"All"})

	def test_requests_nav_group_is_visible_to_every_audience(self) -> None:
		dev = self._make_user("requests-nav-dev@example.test", ["Dev Team"])
		pm = self._make_user("requests-nav-pm@example.test", ["Projects Manager"])
		plain = self._make_user("requests-nav-plain@example.test", [])

		for user in (dev, pm, plain):
			groups = {item["nav_group"] for item in get_nav_items(user)}
			self.assertIn("Requests", groups)

	def test_requests_portal_end_to_end_for_a_zero_role_user(self) -> None:
		plain = self._make_user("requests-portal-e2e@example.test", [])
		frappe.set_user(plain)
		try:
			create_request(title="Portal E2E test request", request_type="Feature", source="Web Portal")
			my_requests = get_my_requests()
		finally:
			frappe.set_user("Administrator")

		titles = [r["title"] for r in my_requests]
		self.assertIn("Portal E2E test request", titles)
		matching = [r for r in my_requests if r["title"] == "Portal E2E test request"]
		self.assertEqual(len(matching), 1)
		created = frappe.get_doc("Request", matching[0]["name"])
		self.assertEqual(created.raised_by_user, plain)
		self.assertEqual(created.source, "Web Portal")
