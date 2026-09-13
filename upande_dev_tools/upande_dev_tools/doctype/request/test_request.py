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

	def test_new_request_defaults_to_under_review(self) -> None:
		doc = frappe.get_doc(
			{
				"doctype": "Request",
				"title": "Needs triage",
				"request_type": "Bug",
			}
		).insert(ignore_permissions=True)
		self.assertEqual(doc.workflow_state, "Under Review")

	def test_only_projects_manager_can_approve(self) -> None:
		from frappe.model.workflow import apply_workflow

		if not frappe.db.exists("User", "dev-only@example.test"):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": "dev-only@example.test",
					"first_name": "Dev",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
		user = frappe.get_doc("User", "dev-only@example.test")
		user.add_roles("Dev Team")

		doc = frappe.get_doc(
			{
				"doctype": "Request",
				"title": "Needs triage",
				"request_type": "Bug",
				"project": None,
				"priority": "High",
			}
		).insert(ignore_permissions=True)

		frappe.set_user("dev-only@example.test")
		try:
			with self.assertRaises(frappe.ValidationError):
				apply_workflow(doc, "Approve")
		finally:
			frappe.set_user("Administrator")
