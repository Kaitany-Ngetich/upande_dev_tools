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
