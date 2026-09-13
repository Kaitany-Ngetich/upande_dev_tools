# Copyright (c) 2026, Upande Limited

import frappe
from frappe.tests import IntegrationTestCase

from upande_dev_tools.portal import enforce_page_access, get_nav_items, resolve_home_route
from upande_dev_tools.setup import register_dev_portal_page


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
