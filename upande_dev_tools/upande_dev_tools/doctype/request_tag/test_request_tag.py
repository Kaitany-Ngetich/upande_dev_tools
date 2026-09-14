# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase


class IntegrationTestRequestTag(IntegrationTestCase):
	def test_named_by_tag_name(self) -> None:
		name = "Test Request Tag Named By Tag Name"
		if frappe.db.exists("Request Tag", name):
			frappe.delete_doc("Request Tag", name, force=True)
		doc = frappe.get_doc({"doctype": "Request Tag", "tag_name": name}).insert(ignore_permissions=True)
		self.assertEqual(doc.name, name)
