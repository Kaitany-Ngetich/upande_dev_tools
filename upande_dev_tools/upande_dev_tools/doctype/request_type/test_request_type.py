# Copyright (c) 2026, Upande Limited
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
