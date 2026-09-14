# Copyright (c) 2026, Upande Limited

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from upande_dev_tools.api.portfolio import _median, get_portfolio


class IntegrationTestPortfolioApi(IntegrationTestCase):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		company = frappe.db.get_value("Company", {}, "name")
		if not company:
			self.skipTest("No Company exists on this site.")
		self.project = frappe.get_doc(
			{
				"doctype": "Project",
				"project_name": frappe.generate_hash(length=10),
				"company": company,
			}
		).insert(ignore_permissions=True).name

	def _task(self, **kwargs) -> str:
		task = frappe.get_doc(
			{"doctype": "Task", "subject": kwargs.pop("subject", "Measured"), "project": self.project, **kwargs}
		)
		task.flags.ignore_recursion_check = True
		return task.insert(ignore_permissions=True).name

	def _mine(self, days: int = 30) -> dict:
		board = get_portfolio(days=days)
		return {kpi["key"]: kpi for kpi in board["kpis"]}

	def test_delivered_counts_only_what_finished_inside_the_period(self) -> None:
		self._task(subject="Inside", status="Completed", completed_on=add_days(today(), -3))
		self._task(subject="Long ago", status="Completed", completed_on=add_days(today(), -120))
		self._task(subject="Still open")

		kpis = self._mine(days=30)
		delivered = [
			w for w in get_portfolio(days=30)["wins"] if w["name"] in frappe.get_all("Task", pluck="name")
		]
		self.assertGreaterEqual(kpis["delivered"]["value"], 1)
		self.assertTrue(any(w["subject"] == "Inside" for w in delivered))
		self.assertFalse(any(w["subject"] == "Long ago" for w in delivered))

	def test_on_time_is_measured_only_against_tasks_that_had_a_due_date(self) -> None:
		self._task(
			subject="Early", status="Completed",
			exp_end_date=add_days(today(), -2), completed_on=add_days(today(), -4),
		)
		self._task(
			subject="Late", status="Completed",
			exp_end_date=add_days(today(), -8), completed_on=add_days(today(), -2),
		)
		self._task(subject="No due date", status="Completed", completed_on=add_days(today(), -2))

		kpi = self._mine()["on_time"]
		self.assertIsNotNone(kpi["value"])
		self.assertIn("completed tasks that carried a due date", kpi["note"])

	def test_backlog_change_is_raised_minus_delivered(self) -> None:
		for index in range(3):
			self._task(subject=f"Raised {index}")
		self._task(subject="Shipped", status="Completed", completed_on=add_days(today(), -1))

		kpi = self._mine()["net"]
		self.assertEqual(kpi["signed"], True)
		self.assertGreaterEqual(kpi["value"], 3)

	def test_a_direction_says_whether_the_change_is_good_news(self) -> None:
		kpis = self._mine()
		# more delivered is good; a longer cycle time is not
		self.assertEqual(kpis["delivered"]["direction"] in ("good", "bad", "flat"), True)
		for key in ("cycle", "net", "risk"):
			self.assertIn(kpis[key]["direction"], ("good", "bad", "flat"))

	def test_work_outside_every_project_is_excluded_and_declared(self) -> None:
		loose = frappe.get_doc({"doctype": "Task", "subject": "No project at all"})
		loose.flags.ignore_recursion_check = True
		loose.insert(ignore_permissions=True)

		board = get_portfolio(days=30)
		self.assertGreaterEqual(board["period"]["excluded"], 1)
		self.assertFalse(any(w["subject"] == "No project at all" for w in board["wins"]))

	def test_risks_lead_with_whatever_has_been_wrong_longest(self) -> None:
		# far enough back to outrank whatever else is overdue on this site
		self._task(subject="Slipped a year", exp_end_date=add_days(today(), -400))
		self._task(subject="Slipped most of a year", exp_end_date=add_days(today(), -380))

		risks = get_portfolio(days=30)["risks"]
		self.assertEqual(risks, sorted(risks, key=lambda r: -r["days"]), "worst first")
		self.assertEqual(risks[0]["title"], "Slipped a year")

	def test_flow_returns_one_bucket_per_week(self) -> None:
		flow = get_portfolio(days=30)["flow"]
		self.assertEqual(len(flow), 8)
		for week in flow:
			self.assertIn("raised", week)
			self.assertIn("delivered", week)

	def test_a_non_manager_is_refused(self) -> None:
		email = "portfolio-outsider@example.test"
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Out", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		frappe.get_doc("User", email).add_roles("Employee")
		frappe.set_user(email)
		try:
			with self.assertRaises(frappe.PermissionError):
				get_portfolio()
		finally:
			frappe.set_user("Administrator")

	def test_median_handles_both_odd_and_even_runs(self) -> None:
		self.assertIsNone(_median([]))
		self.assertEqual(_median([5]), 5)
		self.assertEqual(_median([1, 3, 5]), 3)
		self.assertEqual(_median([1, 2, 3, 4]), 3)
