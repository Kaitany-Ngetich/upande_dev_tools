# Copyright (c) 2026, Upande Limited

import frappe
from frappe.desk.form.assign_to import add as add_assignment
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from upande_dev_tools.api.project_health import get_project_health, get_team_workload


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

	def _make_project(self, scope: str = "Internal") -> str:
		name = f"Team Workload Test Project ({scope})"
		existing = frappe.db.exists("Project", {"project_name": name})
		if existing:
			return existing
		company = frappe.db.get_value("Company", {}, "name")
		if not company:
			self.skipTest("No Company exists on this site to attach a test Project to.")
		return (
			frappe.get_doc(
				{
					"doctype": "Project",
					"project_name": name,
					"company": company,
					"custom_project_scope": scope,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

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

	def test_get_project_health_filters_by_scope(self) -> None:
		pm = self._make_user("project-health-scope-pm@example.test", ["Projects Manager"])
		internal = self._make_project("Internal")
		external = self._make_project("External")

		frappe.set_user(pm)
		try:
			result = get_project_health(scope="External")
		finally:
			frappe.set_user("Administrator")

		names = [p["name"] for p in result["projects"]]
		self.assertIn(external, names)
		self.assertNotIn(internal, names)

	def test_get_project_health_rejects_an_invalid_scope(self) -> None:
		pm = self._make_user("project-health-badscope-pm@example.test", ["Projects Manager"])
		frappe.set_user(pm)
		try:
			with self.assertRaises(frappe.ValidationError):
				get_project_health(scope="Nonsense")
		finally:
			frappe.set_user("Administrator")

	def test_get_team_workload_denies_users_without_projects_manager_role(self) -> None:
		other = self._make_user("team-workload-noperm@example.test", ["Dev Team"])
		frappe.set_user(other)
		try:
			with self.assertRaises(frappe.PermissionError):
				get_team_workload()
		finally:
			frappe.set_user("Administrator")

	def test_get_team_workload_counts_open_tasks_and_incoming_requests_per_dev(self) -> None:
		from upande_dev_tools.api.requests import create_request, promote_to_task, triage_request

		dev = self._make_user("team-workload-dev@example.test", ["Dev Team", "Projects User"])
		pm = self._make_user("team-workload-pm@example.test", ["Projects Manager"])
		project = self._make_project("External")

		frappe.set_user(dev)
		created = create_request(title="Workload test request", request_type="Bug", project=project)

		frappe.set_user(pm)
		triage_request(created["name"], "Approve", priority="High")
		promote_to_task(created["name"])
		req_doc = frappe.get_doc("Request", created["name"])

		# add_assignment (like every other use of it in this suite) runs as Administrator -
		# "Projects Manager" has no DocPerm read access to Task on this bench, and assigning
		# a task is a real Dev Team/admin action in production, not something this test needs
		# the PM persona itself to be able to do.
		frappe.set_user("Administrator")
		add_assignment({"doctype": "Task", "name": req_doc.linked_task, "assign_to": [dev]})
		# Real dates, not just "any truthy value" - frappe.get_all returns Date-fieldtype
		# columns as datetime.date, not the string today() gives; a comparison bug that
		# compares them directly (instead of normalizing both with getdate()) silently never
		# matches, so exercise it here rather than relying on a synthetic fixture that never
		# sets these fields at all.
		frappe.db.set_value("Task", req_doc.linked_task, "custom_planned_for", today())
		frappe.db.set_value("Task", req_doc.linked_task, "exp_end_date", add_days(today(), -2))

		frappe.set_user(pm)
		result = get_team_workload(project=project)
		frappe.set_user("Administrator")

		dev_row = next(d for d in result["developers"] if d["user"] == dev)
		self.assertGreaterEqual(dev_row["open_tasks"], 1)
		self.assertGreaterEqual(dev_row["incoming_requests"], 1)
		self.assertGreaterEqual(dev_row["due_today"], 1)
		self.assertGreaterEqual(dev_row["overdue"], 1)
		self.assertEqual(dev_row["full_name"], frappe.db.get_value("User", dev, "full_name"))
		self.assertIn("open_tasks", result)
		self.assertIn("closed_tasks", result)
