# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from upande_dev_tools.api.dev_portal_settings import (
	get_peak_hours_settings,
	get_registered_pages,
	update_page_roles,
	update_peak_hours_settings,
)
from upande_dev_tools.www.dev_portal_settings import get_context


class IntegrationTestDevPortalSettingsApi(IntegrationTestCase):
	def _make_user(self, email: str, roles: list[str]) -> str:
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Test", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		user = frappe.get_doc("User", email)
		if roles:
			user.add_roles(*roles)
		return email

	def _make_page(self, route: str, roles: list[str]) -> str:
		if frappe.db.exists("Dev Portal Page", route):
			frappe.delete_doc("Dev Portal Page", route, ignore_permissions=True, force=True)
		return (
			frappe.get_doc(
				{
					"doctype": "Dev Portal Page",
					"route": route,
					"title": route,
					"nav_group": "Test",
					"allowed_roles": [{"role": role} for role in roles],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_get_registered_pages_requires_both_roles(self) -> None:
		dev_only = self._make_user("settings-dev-only@example.test", ["Dev Team"])
		frappe.set_user(dev_only)
		try:
			with self.assertRaises(frappe.PermissionError):
				get_registered_pages()
		finally:
			frappe.set_user("Administrator")

	def test_get_registered_pages_lists_pages_for_dual_role_user(self) -> None:
		self._make_page("settings-list-test", ["Dev Team"])
		both = self._make_user("settings-both@example.test", ["Dev Team", "System Manager"])
		frappe.set_user(both)
		try:
			pages = get_registered_pages()
		finally:
			frappe.set_user("Administrator")
		self.assertIn("settings-list-test", [p["route"] for p in pages])

	def test_update_page_roles_requires_both_roles(self) -> None:
		self._make_page("settings-update-guard", ["Dev Team"])
		dev_only = self._make_user("settings-update-dev-only@example.test", ["Dev Team"])
		frappe.set_user(dev_only)
		try:
			with self.assertRaises(frappe.PermissionError):
				update_page_roles(route="settings-update-guard", roles=["Projects Manager"])
		finally:
			frappe.set_user("Administrator")

	def test_update_page_roles_replaces_allowed_roles(self) -> None:
		self._make_page("settings-update-test", ["Dev Team"])
		both = self._make_user("settings-update-both@example.test", ["Dev Team", "System Manager"])
		frappe.set_user(both)
		try:
			update_page_roles(route="settings-update-test", roles=["Projects Manager"])
		finally:
			frappe.set_user("Administrator")

		doc = frappe.get_doc("Dev Portal Page", "settings-update-test")
		self.assertEqual([row.role for row in doc.allowed_roles], ["Projects Manager"])

	def test_get_context_denies_single_role_user(self) -> None:
		dev_only = self._make_user("settings-context-dev-only@example.test", ["Dev Team"])
		frappe.set_user(dev_only)
		try:
			with self.assertRaises(frappe.Redirect):
				get_context({})
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None

	def test_update_page_roles_refuses_to_lock_out_settings_page(self) -> None:
		both = self._make_user("settings-lockout-guard@example.test", ["Dev Team", "System Manager"])
		frappe.set_user(both)
		try:
			with self.assertRaises(frappe.ValidationError):
				update_page_roles(route="dev-portal-settings", roles=["Dev Team"])
		finally:
			frappe.set_user("Administrator")
		doc = frappe.get_doc("Dev Portal Page", "dev-portal-settings")
		self.assertEqual({row.role for row in doc.allowed_roles}, {"Dev Team", "System Manager"})

	def test_update_page_roles_guard_accounts_for_require_all_roles(self) -> None:
		both = self._make_user("settings-lockout-guard-strict@example.test", ["Dev Team", "System Manager"])
		frappe.set_user(both)
		try:
			with self.assertRaises(frappe.ValidationError):
				update_page_roles(
					route="dev-portal-settings",
					roles=["Dev Team", "System Manager", "Projects Manager"],
					require_all_roles=True,
				)
		finally:
			frappe.set_user("Administrator")
		doc = frappe.get_doc("Dev Portal Page", "dev-portal-settings")
		self.assertEqual({row.role for row in doc.allowed_roles}, {"Dev Team", "System Manager"})

	def _reset_peak_hours(self) -> None:
		settings = frappe.get_single("Dev Portal Settings")
		settings.peak_hours_enabled = 0
		settings.peak_start_time = None
		settings.peak_end_time = None
		settings.save(ignore_permissions=True)

	def test_update_peak_hours_settings_requires_both_roles(self) -> None:
		dev_only = self._make_user("peak-update-dev-only@example.test", ["Dev Team"])
		frappe.set_user(dev_only)
		try:
			with self.assertRaises(frappe.PermissionError):
				update_peak_hours_settings(peak_hours_enabled=1, peak_start_time="20:00:00", peak_end_time="06:00:00")
		finally:
			frappe.set_user("Administrator")

	def test_update_peak_hours_settings_requires_both_times_when_enabling(self) -> None:
		both = self._make_user("peak-update-both@example.test", ["Dev Team", "System Manager"])
		frappe.set_user(both)
		try:
			with self.assertRaises(frappe.ValidationError):
				update_peak_hours_settings(peak_hours_enabled=1, peak_start_time=None, peak_end_time=None)
		finally:
			frappe.set_user("Administrator")
			self._reset_peak_hours()

	def test_update_and_get_peak_hours_settings_round_trip(self) -> None:
		both = self._make_user("peak-update-roundtrip@example.test", ["Dev Team", "System Manager"])
		pm = self._make_user("peak-read-pm@example.test", ["Projects Manager"])
		frappe.set_user(both)
		try:
			update_peak_hours_settings(peak_hours_enabled=1, peak_start_time="20:00:00", peak_end_time="06:00:00")
		finally:
			frappe.set_user("Administrator")

		# A Projects Manager can read the configured window (they're the ones asked to
		# approve against it) even though only Dev Team/System Manager can change it.
		frappe.set_user(pm)
		try:
			settings = get_peak_hours_settings()
		finally:
			frappe.set_user("Administrator")
			self._reset_peak_hours()

		self.assertTrue(settings["peak_hours_enabled"])
		self.assertEqual(settings["peak_start_time"], "20:00:00")
		self.assertEqual(settings["peak_end_time"], "06:00:00")

	def test_get_peak_hours_settings_denies_outsiders(self) -> None:
		outsider = self._make_user("peak-read-outsider@example.test", [])
		frappe.set_user(outsider)
		try:
			with self.assertRaises(frappe.PermissionError):
				get_peak_hours_settings()
		finally:
			frappe.set_user("Administrator")
