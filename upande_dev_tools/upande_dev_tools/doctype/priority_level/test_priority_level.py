# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase


class IntegrationTestPriorityLevel(IntegrationTestCase):
	def test_named_by_level_name_and_sorts_by_sort_order(self) -> None:
		name = "Test Priority Level Named By Level Name"
		if frappe.db.exists("Priority Level", name):
			frappe.delete_doc("Priority Level", name, force=True)
		doc = frappe.get_doc({"doctype": "Priority Level", "level_name": name, "sort_order": 5}).insert(
			ignore_permissions=True
		)
		self.assertEqual(doc.name, name)
		self.assertEqual(doc.sort_order, 5)
