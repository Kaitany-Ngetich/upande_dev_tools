# Copyright (c) 2026, shadrack@upande.com and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase


class IntegrationTestDevPortalPage(IntegrationTestCase):
	def test_named_by_route(self) -> None:
		doc = frappe.get_doc(
			{
				"doctype": "Dev Portal Page",
				"route": "dev-portal-page-test-route",
				"title": "Test Page",
				"nav_group": "Test",
				"allowed_roles": [{"role": "Dev Team"}],
			}
		).insert(ignore_permissions=True)
		self.assertEqual(doc.name, "dev-portal-page-test-route")

	def test_allowed_roles_saves_has_role_rows(self) -> None:
		doc = frappe.get_doc(
			{
				"doctype": "Dev Portal Page",
				"route": "dev-portal-page-test-roles",
				"title": "Test Roles",
				"nav_group": "Test",
				"allowed_roles": [{"role": "Dev Team"}, {"role": "System Manager"}],
			}
		).insert(ignore_permissions=True)
		roles = {row.role for row in doc.allowed_roles}
		self.assertEqual(roles, {"Dev Team", "System Manager"})

	def test_dev_team_alone_cannot_write_or_create(self) -> None:
		email = "dev-portal-page-perm-test@example.test"
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Test", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		user = frappe.get_doc("User", email)
		if "Dev Team" not in {r.role for r in user.roles}:
			user.add_roles("Dev Team")

		self.assertTrue(frappe.has_permission("Dev Portal Page", "read", user=email))
		self.assertFalse(frappe.has_permission("Dev Portal Page", "write", user=email))
		self.assertFalse(frappe.has_permission("Dev Portal Page", "create", user=email))
