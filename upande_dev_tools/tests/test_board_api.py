# Copyright (c) 2026, Upande Limited

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from upande_dev_tools.api.board import STAGES, get_board, set_stage


class IntegrationTestBoardApi(IntegrationTestCase):
	def _project(self) -> str:
		company = frappe.db.get_value("Company", {}, "name")
		if not company:
			self.skipTest("No Company exists on this site to attach a test Project to.")
		return (
			frappe.get_doc(
				{
					"doctype": "Project",
					"project_name": frappe.generate_hash(length=10),
					"company": company,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _task(self, project: str, **kwargs) -> str:
		task = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": kwargs.pop("subject", "Board task"),
				"project": project,
				**kwargs,
			}
		).insert(ignore_permissions=True)
		return task.name

	def _issue(self, project: str, **kwargs) -> str:
		issue = frappe.get_doc(
			{
				"doctype": "Issue",
				"subject": kwargs.pop("subject", "Board issue"),
				"project": project,
				**kwargs,
			}
		).insert(ignore_permissions=True)
		return issue.name

	def _user(self, email: str, roles: list[str]) -> str:
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Test", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		frappe.get_doc("User", email).add_roles(*roles)
		return email

	def test_board_merges_tasks_issues_and_requests(self) -> None:
		project = self._project()
		self._task(project, subject="A task")
		self._issue(project, subject="An issue")
		frappe.get_doc(
			{"doctype": "Request", "title": "A request", "project": project}
		).insert(ignore_permissions=True)

		items = get_board(project=project)["items"]
		self.assertEqual({item["doctype"] for item in items}, {"Task", "Issue", "Request"})

	def test_every_item_lands_on_a_known_stage(self) -> None:
		project = self._project()
		self._task(project, status="Pending Review")
		self._issue(project, status="On Hold")

		for item in get_board(project=project)["items"]:
			self.assertIn(item["stage"], STAGES)

	def test_overdue_work_is_flagged_but_finished_work_is_not(self) -> None:
		project = self._project()
		yesterday = add_days(today(), -1)
		self._task(project, subject="Slipping", exp_end_date=yesterday)
		self._task(project, subject="Shipped", exp_end_date=yesterday, status="Completed")

		late = {item["title"]: item["late"] for item in get_board(project=project)["items"]}
		self.assertTrue(late["Slipping"])
		self.assertFalse(late["Shipped"])

	def test_board_reports_total_beyond_the_limit(self) -> None:
		project = self._project()
		for index in range(3):
			self._task(project, subject=f"Task {index}")

		board = get_board(project=project, limit=2)
		self.assertEqual(len(board["items"]), 2)
		self.assertEqual(board["total"], 3)

	def test_board_denies_a_project_the_user_cannot_read(self) -> None:
		project = self._project()
		outsider = self._user("board-outsider@example.test", ["Employee"])
		frappe.set_user(outsider)
		try:
			with self.assertRaises(frappe.PermissionError):
				get_board(project=project)
		finally:
			frappe.set_user("Administrator")

	def test_set_stage_moves_a_task(self) -> None:
		task = self._task(self._project())
		set_stage("Task", task, "In Progress")
		self.assertEqual(frappe.db.get_value("Task", task, "status"), "Working")

	def test_set_stage_moves_an_issue(self) -> None:
		issue = self._issue(self._project())
		set_stage("Issue", issue, "Blocked")
		self.assertEqual(frappe.db.get_value("Issue", issue, "status"), "On Hold")

	def test_set_stage_refuses_a_workflow_governed_request(self) -> None:
		request = frappe.get_doc({"doctype": "Request", "title": "Hands off"}).insert(
			ignore_permissions=True
		)
		with self.assertRaises(frappe.ValidationError):
			set_stage("Request", request.name, "Done")

	def test_set_stage_rejects_an_unknown_stage(self) -> None:
		task = self._task(self._project())
		with self.assertRaises(frappe.ValidationError):
			set_stage("Task", task, "Not A Stage")

	def test_set_stage_denies_users_without_a_board_role(self) -> None:
		task = self._task(self._project())
		outsider = self._user("board-mover@example.test", ["Employee"])
		frappe.set_user(outsider)
		try:
			with self.assertRaises(frappe.PermissionError):
				set_stage("Task", task, "Done")
		finally:
			frappe.set_user("Administrator")
