# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from upande_dev_tools.api.deployments import (
	approve_deployment_request,
	create_deployment_request,
	get_deployment_queue,
	get_my_deployment_requests,
	get_pending_deployment_approvals,
	get_recent_deployments,
	reject_deployment_request,
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
		# Changing state needs Dev Team AND System Manager together - creating the request
		# itself only needs one of DEPLOYER_ROLES, but progressing it needs both.
		dev = self._make_user("dev-deploy@example.test", ["Dev Team", "System Manager"])
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
		dev = self._make_user("dev-retry@example.test", ["Dev Team", "System Manager"])
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

	def test_update_deployment_status_denies_a_solo_role_caller(self) -> None:
		"""Dev Team and System Manager together, not either alone - see
		can_change_deployment_state."""
		app = self._make_app()
		instance = self._make_instance()
		dev_only = self._make_user("dev-only-state@example.test", ["Dev Team"])
		sysmgr_only = self._make_user("sysmgr-only-state@example.test", ["System Manager"])

		frappe.set_user(dev_only)
		try:
			created = create_deployment_request(app=app, instance=instance)
		finally:
			frappe.set_user("Administrator")

		for solo in (dev_only, sysmgr_only):
			frappe.set_user(solo)
			try:
				with self.assertRaises(frappe.PermissionError):
					update_deployment_status(created["name"], "Start Deployment")
			finally:
				frappe.set_user("Administrator")

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

	def test_get_recent_deployments_permits_projects_manager(self) -> None:
		dev = self._make_user("dev-recent-deploy@example.test", ["Dev Team"])
		pm = self._make_user("pm-recent-deploy@example.test", ["Projects Manager"])
		app = self._make_app()
		instance = self._make_instance()

		frappe.set_user(dev)
		try:
			created = create_deployment_request(app=app, instance=instance)
		finally:
			frappe.set_user("Administrator")

		frappe.set_user(pm)
		try:
			result = get_recent_deployments(limit=5)
		finally:
			frappe.set_user("Administrator")

		self.assertIn(created["name"], [r["name"] for r in result["recent"]])
		self.assertIn("counts_by_state", result)

	def test_get_recent_deployments_denies_outsiders(self) -> None:
		outsider = self._make_user("outsider-recent-deploy@example.test", [])
		frappe.set_user(outsider)
		try:
			with self.assertRaises(frappe.PermissionError):
				get_recent_deployments()
		finally:
			frappe.set_user("Administrator")

	def test_get_recent_deployments_clamps_limit(self) -> None:
		dev = self._make_user("dev-recent-deploy-limit@example.test", ["Dev Team"])
		frappe.set_user(dev)
		try:
			result = get_recent_deployments(limit=999)
		finally:
			frappe.set_user("Administrator")
		self.assertLessEqual(len(result["recent"]), 50)

	def _set_peak_hours(self, enabled: bool, start: str = "00:00:00", end: str = "23:59:59") -> None:
		settings = frappe.get_single("Dev Portal Settings")
		settings.peak_hours_enabled = 1 if enabled else 0
		settings.peak_start_time = start if enabled else None
		settings.peak_end_time = end if enabled else None
		settings.save(ignore_permissions=True)

	def test_deployment_flagged_when_raised_inside_peak_hours(self) -> None:
		# 00:00:00-23:59:59 covers the whole day, so "right now" (whenever the test runs)
		# always falls inside it - deterministic without needing to mock the clock.
		dev = self._make_user("dev-peak-flag@example.test", ["Dev Team"])
		app = self._make_app()
		instance = self._make_instance()

		self._set_peak_hours(True)
		try:
			frappe.set_user(dev)
			try:
				created = create_deployment_request(app=app, instance=instance)
			finally:
				frappe.set_user("Administrator")
		finally:
			self._set_peak_hours(False)

		doc = frappe.get_doc("Deployment Request", created["name"])
		self.assertEqual(doc.requires_approval, 1)
		self.assertEqual(doc.approval_status, "Pending")

	def test_deployment_not_flagged_when_peak_hours_disabled(self) -> None:
		dev = self._make_user("dev-peak-off@example.test", ["Dev Team"])
		app = self._make_app()
		instance = self._make_instance()

		self._set_peak_hours(False)
		frappe.set_user(dev)
		try:
			created = create_deployment_request(app=app, instance=instance)
		finally:
			frappe.set_user("Administrator")

		doc = frappe.get_doc("Deployment Request", created["name"])
		self.assertEqual(doc.requires_approval, 0)

	def test_start_deployment_blocked_until_pm_approves(self) -> None:
		dev = self._make_user("dev-peak-block@example.test", ["Dev Team", "System Manager"])
		pm = self._make_user("pm-peak-approve@example.test", ["Projects Manager"])
		app = self._make_app()
		instance = self._make_instance()

		self._set_peak_hours(True)
		try:
			frappe.set_user(dev)
			try:
				created = create_deployment_request(app=app, instance=instance)
				with self.assertRaises(frappe.PermissionError):
					update_deployment_status(created["name"], "Start Deployment")
			finally:
				frappe.set_user("Administrator")
		finally:
			self._set_peak_hours(False)

		frappe.set_user(pm)
		try:
			approved = approve_deployment_request(created["name"])
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(approved["approval_status"], "Approved")
		self.assertEqual(approved["approved_by"], pm)

		frappe.set_user(dev)
		try:
			started = update_deployment_status(created["name"], "Start Deployment")
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(started["workflow_state"], "In Progress")

	def test_reject_deployment_request_blocks_it_indefinitely(self) -> None:
		dev = self._make_user("dev-peak-reject@example.test", ["Dev Team"])
		pm = self._make_user("pm-peak-reject@example.test", ["Projects Manager"])
		app = self._make_app()
		instance = self._make_instance()

		self._set_peak_hours(True)
		try:
			frappe.set_user(dev)
			try:
				created = create_deployment_request(app=app, instance=instance)
			finally:
				frappe.set_user("Administrator")
		finally:
			self._set_peak_hours(False)

		frappe.set_user(pm)
		try:
			rejected = reject_deployment_request(created["name"], note="Wait until after hours.")
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(rejected["approval_status"], "Rejected")

		frappe.set_user(dev)
		try:
			with self.assertRaises(frappe.PermissionError):
				update_deployment_status(created["name"], "Start Deployment")
		finally:
			frappe.set_user("Administrator")

	def test_approve_and_reject_deployment_require_pm_or_system_manager(self) -> None:
		dev = self._make_user("dev-peak-noauth@example.test", ["Dev Team"])
		app = self._make_app()
		instance = self._make_instance()

		self._set_peak_hours(True)
		try:
			frappe.set_user(dev)
			try:
				created = create_deployment_request(app=app, instance=instance)
			finally:
				frappe.set_user("Administrator")
		finally:
			self._set_peak_hours(False)

		frappe.set_user(dev)
		try:
			with self.assertRaises(frappe.PermissionError):
				approve_deployment_request(created["name"])
			with self.assertRaises(frappe.PermissionError):
				reject_deployment_request(created["name"])
		finally:
			frappe.set_user("Administrator")

	def test_workflow_itself_blocks_start_even_bypassing_the_api(self) -> None:
		"""The desk form drives this workflow directly (its own "Start Deployment" button
		calls apply_workflow, never this app's update_deployment_status) - the block has to
		hold at the doctype level too, not just in the one API method."""
		from frappe.model.workflow import apply_workflow

		# Both roles, so the only thing this test can be blocked by is the peak-hours check -
		# see test_workflow_itself_blocks_a_solo_role_state_change_too for the dual-role one.
		dev = self._make_user("dev-peak-bypass@example.test", ["Dev Team", "System Manager"])
		app = self._make_app()
		instance = self._make_instance()

		self._set_peak_hours(True)
		try:
			frappe.set_user(dev)
			try:
				created = create_deployment_request(app=app, instance=instance)
			finally:
				frappe.set_user("Administrator")
		finally:
			self._set_peak_hours(False)

		doc = frappe.get_doc("Deployment Request", created["name"])
		with self.assertRaises(frappe.PermissionError):
			apply_workflow(doc, "Start Deployment")

	def test_workflow_itself_blocks_a_solo_role_state_change_too(self) -> None:
		"""Same shape as test_workflow_itself_blocks_start_even_bypassing_the_api, but for the
		dual-role gate rather than peak hours - a lone Dev Team member driving the workflow
		straight from the desk form must not be able to route around update_deployment_status
		either."""
		from frappe.model.workflow import apply_workflow

		dev = self._make_user("dev-soloista@example.test", ["Dev Team"])
		app = self._make_app()
		instance = self._make_instance()

		frappe.set_user(dev)
		try:
			created = create_deployment_request(app=app, instance=instance)
			doc = frappe.get_doc("Deployment Request", created["name"])
			# Administrator (every role, including both of these) would sail straight
			# through this check - it has to run as the solo-role user to mean anything.
			with self.assertRaises(frappe.PermissionError):
				apply_workflow(doc, "Start Deployment")
		finally:
			frappe.set_user("Administrator")

	def test_get_pending_deployment_approvals_lists_only_pending_flagged(self) -> None:
		dev = self._make_user("dev-peak-pending@example.test", ["Dev Team"])
		pm = self._make_user("pm-peak-pending@example.test", ["Projects Manager"])
		app = self._make_app()
		instance = self._make_instance()

		self._set_peak_hours(True)
		try:
			frappe.set_user(dev)
			try:
				flagged = create_deployment_request(app=app, instance=instance)
			finally:
				frappe.set_user("Administrator")
		finally:
			self._set_peak_hours(False)

		frappe.set_user(dev)
		try:
			not_flagged = create_deployment_request(app=app, instance=instance)
		finally:
			frappe.set_user("Administrator")

		frappe.set_user(pm)
		try:
			pending = get_pending_deployment_approvals()
		finally:
			frappe.set_user("Administrator")
		pending_names = {r["name"] for r in pending}
		self.assertIn(flagged["name"], pending_names)
		self.assertNotIn(not_flagged["name"], pending_names)
