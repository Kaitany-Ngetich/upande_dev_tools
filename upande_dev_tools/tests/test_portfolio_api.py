# Copyright (c) 2026, Upande Limited

import frappe
from frappe.desk.form.assign_to import add as add_assignment
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, today

from upande_dev_tools.api.portfolio import _forecast, _median, get_portfolio


class IntegrationTestPortfolioApi(IntegrationTestCase):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		company = frappe.db.get_value("Company", {}, "name")
		if not company:
			self.skipTest("No Company exists on this site.")
		from upande_dev_tools.setup import DEV_TOOLS_PROJECT_TYPE

		self.project = (
			frappe.get_doc(
				{
					"doctype": "Project",
					"project_name": frappe.generate_hash(length=10),
					"company": company,
					"project_type": DEV_TOOLS_PROJECT_TYPE,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _task(self, **kwargs) -> str:
		task = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": kwargs.pop("subject", "Measured"),
				"project": self.project,
				**kwargs,
			}
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
			subject="Early",
			status="Completed",
			exp_end_date=add_days(today(), -2),
			completed_on=add_days(today(), -4),
		)
		self._task(
			subject="Late",
			status="Completed",
			exp_end_date=add_days(today(), -8),
			completed_on=add_days(today(), -2),
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
		# Scoped to this test's own project - this shared bench already has a real task
		# hundreds of days overdue, which would otherwise outrank these fixtures on a
		# portfolio-wide query and make the ordering assertion depend on live data.
		from upande_dev_tools.api.portfolio import _risks

		self._task(subject="Slipped a year", exp_end_date=add_days(today(), -400))
		self._task(subject="Slipped most of a year", exp_end_date=add_days(today(), -380))

		risks = _risks({"project": self.project}, getdate(today()))
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

	def test_due_soon_only_counts_open_work_due_within_a_week_and_not_yet_late(self) -> None:
		self._task(subject="Due in 3 days", exp_end_date=add_days(today(), 3))
		self._task(subject="Due in 20 days", exp_end_date=add_days(today(), 20))
		self._task(subject="Already overdue", exp_end_date=add_days(today(), -1))
		self._task(subject="No due date")

		# Scoped to this test's own project, not the wider Dev Tools portfolio - this
		# shared bench already has real tasks due today that would otherwise crowd a
		# shared 10-row cap and hide the fixtures being asserted on here.
		from upande_dev_tools.api.portfolio import _due_soon

		due_soon = _due_soon({"project": self.project}, getdate(today()))
		titles = {row["subject"] for row in due_soon["items"]}
		self.assertIn("Due in 3 days", titles)
		self.assertNotIn("Due in 20 days", titles)
		self.assertNotIn("Already overdue", titles)
		self.assertNotIn("No due date", titles)
		self.assertEqual(due_soon["total"], 1)

	def test_a_person_whose_open_queue_is_mostly_late_is_flagged_over_capacity(self) -> None:
		email = "portfolio-drowning@example.test"
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Drowning", "send_welcome_email": 0}
			).insert(ignore_permissions=True)

		for index in range(5):
			task = self._task(subject=f"Late {index}", exp_end_date=add_days(today(), -1))
			add_assignment({"doctype": "Task", "name": task, "assign_to": [email]})

		people = {p["user"]: p for p in get_portfolio(days=30)["people"]}
		self.assertIn(email, people)
		self.assertTrue(people[email]["over_capacity"])
		self.assertIn(people[email]["overload_reason"], ("lateness", "both"))
		self.assertEqual(people[email]["overdue"], 5)

	def test_forecast_history_counts_only_what_was_actually_open_at_each_past_week(self) -> None:
		# well before the 12-week (84-day) history window, so it predates every checkpoint
		old_task = self._task(subject="Old, still open", exp_end_date=add_days(today(), 30))
		frappe.db.set_value("Task", old_task, "creation", add_days(today(), -100), update_modified=False)
		self._task(subject="Finished this week", status="Completed", completed_on=add_days(today(), -1))

		board = _forecast({"project": self.project}, open_total=1, end=getdate(today()))
		self.assertEqual(len(board["history"]), 12)
		# the task created 50 days ago and still open should count as open at every
		# checkpoint in the 12-week history, including the earliest one
		self.assertGreaterEqual(board["history"][0]["open"], 1)
		self.assertGreaterEqual(board["history"][-1]["open"], 1)
		self.assertEqual(board["history"][-1]["completed"], 1)

	def test_forecast_reports_insufficient_data_when_nothing_has_ever_been_completed(self) -> None:
		self._task(subject="Still open, nothing finished ever")
		board = _forecast({"project": self.project}, open_total=1, end=getdate(today()))
		self.assertTrue(board["insufficient"])
		self.assertIn("note", board)

	def test_forecast_is_done_immediately_when_nothing_is_open(self) -> None:
		board = _forecast({"project": self.project}, open_total=0, end=getdate(today()))
		self.assertTrue(board["done"])
		self.assertEqual(board["p50_weeks"], 0)

	def test_forecast_resamples_real_throughput_rather_than_averaging_it(self) -> None:
		# a steady 5/week for the whole history window - with 25 open, a resampling
		# forecast built on this should land close to 5 weeks at the median
		for week in range(12):
			for i in range(5):
				self._task(
					subject=f"Done wk{week}-{i}",
					status="Completed",
					completed_on=add_days(today(), -7 * week),
				)
		board = _forecast({"project": self.project}, open_total=25, end=getdate(today()))
		self.assertFalse(board["insufficient"])
		self.assertAlmostEqual(board["p50_weeks"], 5, delta=2)
		self.assertGreaterEqual(board["p85_weeks"], board["p50_weeks"])
