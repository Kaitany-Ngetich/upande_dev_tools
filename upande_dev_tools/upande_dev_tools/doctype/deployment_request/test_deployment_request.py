# Copyright (c) 2026, shadrack@upande.com and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

# See the identical note in test_request.py — Deployment Request links
# directly to User (requested_by_user, deployed_by_user) and Employee
# (requested_by_employee), and both eventually reach the same broken
# Company regional setup during IntegrationTestCase's automatic missing-record
# walk. `app`/`instance`/`linked_request` don't need listing here: the first
# two have no Link fields of their own, and `linked_request` recurses into
# Request, which already excludes the doctypes that would reach Company.
IGNORE_TEST_RECORD_DEPENDENCIES = ["User", "Employee"]


class IntegrationTestDeploymentRequest(IntegrationTestCase):
	def _make_app(self) -> str:
		if frappe.db.exists("Deployment App", "Requests Phase 1 Test App"):
			return "Requests Phase 1 Test App"
		return (
			frappe.get_doc(
				{
					"doctype": "Deployment App",
					"app_name": "Requests Phase 1 Test App",
					"repository_url": "https://github.com/example/test-app.git",
					"default_branch": "main",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _make_instance(self) -> str:
		if frappe.db.exists("Deployment Instance", "Requests Phase 1 Test Instance"):
			return "Requests Phase 1 Test Instance"
		return (
			frappe.get_doc(
				{
					"doctype": "Deployment Instance",
					"instance_name": "Requests Phase 1 Test Instance",
					"environment_type": "Staging",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_branch_defaults_from_app(self) -> None:
		doc = frappe.get_doc(
			{
				"doctype": "Deployment Request",
				"app": self._make_app(),
				"instance": self._make_instance(),
			}
		).insert(ignore_permissions=True)
		self.assertEqual(doc.branch, "main")

	def test_requested_by_user_defaults_to_session_user(self) -> None:
		doc = frappe.get_doc(
			{
				"doctype": "Deployment Request",
				"app": self._make_app(),
				"instance": self._make_instance(),
			}
		).insert(ignore_permissions=True)
		self.assertEqual(doc.requested_by_user, "Administrator")

	def test_defaults_to_requested_state(self) -> None:
		doc = frappe.get_doc(
			{
				"doctype": "Deployment Request",
				"app": self._make_app(),
				"instance": self._make_instance(),
			}
		).insert(ignore_permissions=True)
		self.assertEqual(doc.workflow_state, "Requested")
