# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase


class IntegrationTestRequestType(IntegrationTestCase):
	def test_named_by_type_name(self) -> None:
		name = "Test Request Type Named By Type Name"
		if frappe.db.exists("Request Type", name):
			frappe.delete_doc("Request Type", name, force=True)
		doc = frappe.get_doc({"doctype": "Request Type", "type_name": name}).insert(ignore_permissions=True)
		self.assertEqual(doc.name, name)

	def test_a_user_with_no_role_at_all_can_still_read_it(self) -> None:
		"""The public Requests page's Kind dropdown fetches this via frappe.client.get_list,
		which enforces normal DocPerm - unlike this app's own API wrappers (frappe.get_all,
		which ignores permissions by default). Without an "All" role grant here, anyone
		raising a request with no other app role at all gets a PermissionError instead of
		a working form."""
		email = "request-type-zero-role@example.test"
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Zero", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		frappe.set_user(email)
		try:
			self.assertTrue(frappe.has_permission("Request Type", "read"))
			frappe.get_list("Request Type", limit_page_length=0)
		finally:
			frappe.set_user("Administrator")
