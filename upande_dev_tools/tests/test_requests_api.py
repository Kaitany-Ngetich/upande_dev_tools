# Copyright (c) 2026, Upande Limited

import frappe
from frappe.tests import IntegrationTestCase

from upande_dev_tools.api.requests import create_request, get_my_requests, get_review_queue


class IntegrationTestRequestsApi(IntegrationTestCase):
	def test_task_has_request_custom_fields(self) -> None:
		meta = frappe.get_meta("Task")
		self.assertTrue(meta.has_field("custom_request"))
		self.assertTrue(meta.has_field("custom_planned_for"))

	def _make_user(self, email: str, roles: list[str]) -> str:
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Test", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		user = frappe.get_doc("User", email)
		if roles:
			user.add_roles(*roles)
		return email

	def test_create_request_rejects_note_from_non_dev(self) -> None:
		pm = self._make_user("pm-create@example.test", ["Projects Manager"])
		frappe.set_user(pm)
		try:
			with self.assertRaises(frappe.ValidationError):
				create_request(title="sneaky note", request_type="Note")
		finally:
			frappe.set_user("Administrator")

	def test_get_my_requests_scopes_to_caller(self) -> None:
		dev = self._make_user("dev-scope@example.test", ["Dev Team"])
		other = self._make_user("other-scope@example.test", ["Dev Team"])

		frappe.set_user(dev)
		created = create_request(title="My own request", request_type="Bug")
		frappe.set_user(other)
		create_request(title="Someone else's request", request_type="Bug")

		frappe.set_user(dev)
		try:
			mine = get_my_requests()
		finally:
			frappe.set_user("Administrator")
		self.assertEqual([r["name"] for r in mine], [created["name"]])

	def test_get_review_queue_requires_reviewer_role(self) -> None:
		outsider = self._make_user("outsider-queue@example.test", [])
		frappe.set_user(outsider)
		try:
			with self.assertRaises(frappe.PermissionError):
				get_review_queue()
		finally:
			frappe.set_user("Administrator")
