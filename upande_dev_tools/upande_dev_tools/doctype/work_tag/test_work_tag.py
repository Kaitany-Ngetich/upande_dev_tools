# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase


class IntegrationTestWorkTag(IntegrationTestCase):
	def test_named_by_tag_name(self) -> None:
		name = "Test Work Tag Named By Tag Name"
		if frappe.db.exists("Work Tag", name):
			frappe.delete_doc("Work Tag", name, force=True)
		doc = frappe.get_doc({"doctype": "Work Tag", "tag_name": name}).insert(ignore_permissions=True)
		self.assertEqual(doc.name, name)
