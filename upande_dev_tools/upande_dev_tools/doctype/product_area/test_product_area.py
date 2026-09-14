# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase


class IntegrationTestProductArea(IntegrationTestCase):
	def test_named_by_area_name(self) -> None:
		name = "Test Product Area Named By Area Name"
		if frappe.db.exists("Product Area", name):
			frappe.delete_doc("Product Area", name, force=True)
		doc = frappe.get_doc({"doctype": "Product Area", "area_name": name}).insert(ignore_permissions=True)
		self.assertEqual(doc.name, name)
