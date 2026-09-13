# Copyright (c) 2026, Upande Limited

import frappe
from frappe.tests import IntegrationTestCase

from upande_dev_tools.api.activity_log import get_activity_log


class IntegrationTestActivityLogApi(IntegrationTestCase):
	def _make_user(self, email: str, roles: list[str]) -> str:
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Test", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		user = frappe.get_doc("User", email)
		if roles:
			user.add_roles(*roles)
		return email

	def _make_activity(self, title: str, status: str) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "Developer Activity Log",
					"activity_time": frappe.utils.now_datetime(),
					"activity_type": "Backup",
					"title": title,
					"status": status,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_get_activity_log_denies_users_without_dev_team_role(self) -> None:
		other = self._make_user("activity-log-noperm@example.test", [])
		frappe.set_user(other)
		try:
			with self.assertRaises(frappe.PermissionError):
				get_activity_log()
		finally:
			frappe.set_user("Administrator")

	def test_get_activity_log_filters_by_status(self) -> None:
		self._make_activity("activity-log-test-error", "Error")
		self._make_activity("activity-log-test-success", "Success")
		dev = self._make_user("activity-log-dev@example.test", ["Dev Team"])
		frappe.set_user(dev)
		try:
			result = get_activity_log(status="Error", search="activity-log-test", limit=10)
		finally:
			frappe.set_user("Administrator")
		titles = [row["title"] for row in result["rows"]]
		self.assertIn("activity-log-test-error", titles)
		self.assertNotIn("activity-log-test-success", titles)

	def test_get_activity_log_clamps_pagination_arguments(self) -> None:
		dev = self._make_user("activity-log-pagination@example.test", ["Dev Team"])
		frappe.set_user(dev)
		try:
			result_zero_limit = get_activity_log(limit=0)
			self.assertLessEqual(len(result_zero_limit["rows"]), 200)

			result_negative = get_activity_log(start=-5, limit=-1)
			self.assertLessEqual(len(result_negative["rows"]), 200)
		finally:
			frappe.set_user("Administrator")

	def test_get_activity_log_rejects_non_string_filter_types(self) -> None:
		dev = self._make_user("activity-log-type-guard@example.test", ["Dev Team"])
		frappe.set_user(dev)
		try:
			with self.assertRaises(Exception):
				get_activity_log(status=["!=", "zzz"])
		finally:
			frappe.set_user("Administrator")
