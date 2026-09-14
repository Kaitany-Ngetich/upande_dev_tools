# Copyright (c) 2026, Upande Limited

import frappe
from frappe.tests import IntegrationTestCase

from upande_dev_tools.api.project_health import get_project_health


class IntegrationTestProjectHealthApi(IntegrationTestCase):
	def _make_user(self, email: str, roles: list[str]) -> str:
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Test", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		user = frappe.get_doc("User", email)
		if roles:
			user.add_roles(*roles)
		return email

	def test_get_project_health_denies_users_without_projects_manager_role(self) -> None:
		other = self._make_user("project-health-noperm@example.test", ["Dev Team"])
		frappe.set_user(other)
		try:
			with self.assertRaises(frappe.PermissionError):
				get_project_health()
		finally:
			frappe.set_user("Administrator")

	def test_get_project_health_returns_aggregate_and_per_project_data(self) -> None:
		pm = self._make_user("project-health-pm@example.test", ["Projects Manager"])
		frappe.set_user(pm)
		try:
			result = get_project_health()
		finally:
			frappe.set_user("Administrator")
		self.assertIn("project_count", result)
		self.assertIn("total_overdue_tasks", result)
		self.assertIn("total_open_requests", result)
		self.assertIsInstance(result["projects"], list)
		if result["projects"]:
			row = result["projects"][0]
			for key in (
				"name",
				"project_name",
				"status",
				"total_tasks",
				"completed_tasks",
				"overdue_tasks",
				"open_requests",
			):
				self.assertIn(key, row)
