# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from upande_dev_tools.api.code_snapshots import get_snapshots


class IntegrationTestCodeSnapshotsApi(IntegrationTestCase):
	def _make_user(self, email: str, roles: list[str]) -> str:
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Test", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		user = frappe.get_doc("User", email)
		if roles:
			user.add_roles(*roles)
		return email

	def _make_snapshot(self, document_name: str, app: str) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "Code Backup Snapshot",
					"snapshot_time": frappe.utils.now_datetime(),
					"source_type": "DocType",
					"document_name": document_name,
					"app": app,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_get_snapshots_denies_users_without_dev_team_role(self) -> None:
		other = self._make_user("snapshots-noperm@example.test", [])
		frappe.set_user(other)
		try:
			with self.assertRaises(frappe.PermissionError):
				get_snapshots()
		finally:
			frappe.set_user("Administrator")

	def test_get_snapshots_returns_rows_and_total_for_dev_team(self) -> None:
		self._make_snapshot("snap-test-1", "upande_dev_tools")
		dev = self._make_user("snapshots-dev@example.test", ["Dev Team"])
		frappe.set_user(dev)
		try:
			result = get_snapshots(app="upande_dev_tools", limit=5)
		finally:
			frappe.set_user("Administrator")
		self.assertIn("snap-test-1", [row["document_name"] for row in result["rows"]])
		self.assertGreaterEqual(result["total"], 1)

	def test_get_snapshots_clamps_pagination_arguments(self) -> None:
		dev = self._make_user("snapshots-pagination@example.test", ["Dev Team"])
		frappe.set_user(dev)
		try:
			result_zero_limit = get_snapshots(limit=0)
			self.assertLessEqual(len(result_zero_limit["rows"]), 200)

			result_negative = get_snapshots(start=-5, limit=-1)
			self.assertLessEqual(len(result_negative["rows"]), 200)
		finally:
			frappe.set_user("Administrator")

	def test_get_snapshots_rejects_non_string_filter_types(self) -> None:
		dev = self._make_user("snapshots-type-guard@example.test", ["Dev Team"])
		frappe.set_user(dev)
		try:
			with self.assertRaises(Exception):
				get_snapshots(app=["like", "%"])
		finally:
			frappe.set_user("Administrator")
