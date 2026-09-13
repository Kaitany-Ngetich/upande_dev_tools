# Copyright (c) 2026, Upande Limited

import frappe
from frappe.tests import IntegrationTestCase

from upande_dev_tools.api.deployments import (
	create_deployment_request,
	get_deployment_queue,
	get_my_deployment_requests,
	update_deployment_status,
)


class IntegrationTestDeploymentsApi(IntegrationTestCase):
	def _make_user(self, email: str, roles: list[str]) -> str:
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Test", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		user = frappe.get_doc("User", email)
		if roles:
			user.add_roles(*roles)
		return email

	def _make_app(self) -> str:
		if frappe.db.exists("Deployment App", "Deployments Api Test App"):
			return "Deployments Api Test App"
		return (
			frappe.get_doc(
				{
					"doctype": "Deployment App",
					"app_name": "Deployments Api Test App",
					"repository_url": "https://github.com/example/api-test-app.git",
					"default_branch": "main",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _make_instance(self) -> str:
		if frappe.db.exists("Deployment Instance", "Deployments Api Test Instance"):
			return "Deployments Api Test Instance"
		return (
			frappe.get_doc(
				{
					"doctype": "Deployment Instance",
					"instance_name": "Deployments Api Test Instance",
					"environment_type": "Staging",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_create_and_progress_deployment_lifecycle(self) -> None:
		dev = self._make_user("dev-deploy@example.test", ["Dev Team"])
		app = self._make_app()
		instance = self._make_instance()

		frappe.set_user(dev)
		try:
			created = create_deployment_request(app=app, instance=instance)
			update_deployment_status(created["name"], "Start Deployment")
			update_deployment_status(created["name"], "Mark Deployed", commit_hash="abc1234")
		finally:
			frappe.set_user("Administrator")

		doc = frappe.get_doc("Deployment Request", created["name"])
		self.assertEqual(doc.workflow_state, "Deployed")
		self.assertEqual(doc.commit_hash, "abc1234")
		self.assertEqual(doc.deployed_by_user, dev)

	def test_failed_deployment_can_be_retried(self) -> None:
		dev = self._make_user("dev-retry@example.test", ["Dev Team"])
		app = self._make_app()
		instance = self._make_instance()

		frappe.set_user(dev)
		try:
			created = create_deployment_request(app=app, instance=instance)
			update_deployment_status(created["name"], "Start Deployment")
			update_deployment_status(created["name"], "Mark Failed", errors="migrate failed")
			update_deployment_status(created["name"], "Retry")
		finally:
			frappe.set_user("Administrator")

		doc = frappe.get_doc("Deployment Request", created["name"])
		self.assertEqual(doc.workflow_state, "In Progress")
		self.assertEqual(doc.errors, "migrate failed")

	def test_get_deployment_queue_requires_dev_team_or_system_manager(self) -> None:
		outsider = self._make_user("outsider-deploy@example.test", [])
		frappe.set_user(outsider)
		try:
			with self.assertRaises(frappe.PermissionError):
				get_deployment_queue()
		finally:
			frappe.set_user("Administrator")

	def test_get_my_deployment_requests_scopes_to_caller(self) -> None:
		dev = self._make_user("dev-mydeploy@example.test", ["Dev Team"])
		other = self._make_user("other-mydeploy@example.test", ["Dev Team"])
		app = self._make_app()
		instance = self._make_instance()

		try:
			frappe.set_user(dev)
			created = create_deployment_request(app=app, instance=instance)
			frappe.set_user(other)
			create_deployment_request(app=app, instance=instance)

			frappe.set_user(dev)
			mine = get_my_deployment_requests()
		finally:
			frappe.set_user("Administrator")
		self.assertEqual([r["name"] for r in mine], [created["name"]])

	def test_create_deployment_request_requires_dev_team_or_system_manager(self) -> None:
		outsider = self._make_user("outsider-create-deploy@example.test", [])
		app = self._make_app()
		instance = self._make_instance()

		frappe.set_user(outsider)
		try:
			with self.assertRaises(frappe.PermissionError):
				create_deployment_request(app=app, instance=instance)
		finally:
			frappe.set_user("Administrator")
