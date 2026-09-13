# Copyright (c) 2026, shadrack@upande.com and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = ["Project", "Task", "User", "Employee", "Contact"]


class IntegrationTestRequest(IntegrationTestCase):
	def test_can_be_created_with_title_and_type(self) -> None:
		doc = frappe.get_doc(
			{
				"doctype": "Request",
				"title": "Add export button",
				"request_type": "Feature",
			}
		).insert(ignore_permissions=True)
		self.assertTrue(doc.name.startswith("REQ-"))
