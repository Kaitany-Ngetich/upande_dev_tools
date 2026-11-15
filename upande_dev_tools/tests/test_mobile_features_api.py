# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

from datetime import date
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from upande_dev_tools.api import achievements, comments, notifications


class IntegrationTestAchievementsPure(IntegrationTestCase):
	def test_points_follow_priority_and_overdue_bonus(self) -> None:
		on_time = {"priority": "High", "exp_end_date": "2026-11-10", "completed_on": "2026-11-10"}
		late = {"priority": "Urgent", "exp_end_date": "2026-11-09", "completed_on": "2026-11-10"}
		self.assertEqual(achievements.task_points(on_time), 4)
		self.assertEqual(achievements.task_points(late), 7)
		self.assertEqual(achievements.task_points({"priority": "Low", "completed_on": "2026-11-10"}), 1)
		self.assertEqual(achievements.task_points({"priority": "Medium"}), 2)

	def test_streak_skips_weekends_and_allows_yesterday(self) -> None:
		# 2026-11-16 is a Monday.
		fri, thu, wed = date(2026, 11, 13), date(2026, 11, 12), date(2026, 11, 11)
		self.assertEqual(achievements.compute_streaks({wed, thu, fri}, date(2026, 11, 16)), (3, 3))
		self.assertEqual(achievements.compute_streaks({wed, thu, fri, date(2026, 11, 16)}, date(2026, 11, 16)), (4, 4))
		self.assertEqual(achievements.compute_streaks({wed, thu, fri}, date(2026, 11, 14)), (3, 3))
		# A weekend close neither breaks nor extends the run.
		self.assertEqual(achievements.compute_streaks({thu, fri, date(2026, 11, 14)}, date(2026, 11, 16)), (2, 2))

	def test_streak_breaks_after_a_missed_weekday(self) -> None:
		self.assertEqual(achievements.compute_streaks({date(2026, 11, 11)}, date(2026, 11, 16))[0], 0)
		current, best = achievements.compute_streaks(
			{date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 13)}, date(2026, 11, 13)
		)
		self.assertEqual((current, best), (1, 3))
		self.assertEqual(achievements.compute_streaks(set(), date(2026, 11, 16)), (0, 0))

	def test_get_achievements_has_the_documented_shape(self) -> None:
		result = achievements.get_achievements()
		for key in ("points_today", "points_week", "points_total", "streak", "best_streak", "closed_today", "closed_week"):
			self.assertIsInstance(result[key], int)
		self.assertEqual(
			[b["key"] for b in result["badges"]],
			["first_close", "streak_5", "overdue_slayer", "deploy_day", "capture_champion"],
		)
		self.assertLessEqual(len(result["leaderboard"]), 10)
		self.assertTrue(all(row["points"] > 0 for row in result["leaderboard"]))


class IntegrationTestCommentsApi(IntegrationTestCase):
	def _user(self, email: str, roles: list[str]) -> str:
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Test", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		if roles:
			frappe.get_doc("User", email).add_roles(*roles)
		return email

	def test_only_task_and_request_have_comments(self) -> None:
		with self.assertRaises(frappe.ValidationError):
			comments.get_comments("User", "Administrator")

	def test_add_and_read_a_comment_strips_html_and_notifies_others(self) -> None:
		dev = self._user("dev-comment@example.test", ["Dev Team"])
		other = self._user("dev-comment-2@example.test", ["Dev Team"])
		frappe.set_user(dev)
		try:
			from upande_dev_tools.api.requests import create_request

			request = create_request(title="Comment on me", request_type="Bug")["name"]
			frappe.set_user("Administrator")
			frappe.get_doc("Request", request).add_comment("Comment", "<p>earlier</p>")
			frappe.db.set_value("Comment", {"reference_name": request}, "comment_email", other)
			frappe.set_user(dev)
			with patch.object(comments, "notify") as notify:
				added = comments.add_comment("Request", request, "Looks <b>good</b>")
			rows = comments.get_comments("Request", request)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(added["comment_by"], dev)
		self.assertEqual(rows[-1]["content"], "Looks good")
		recipients = notify.call_args[0][0]
		self.assertIn(other, recipients)
		self.assertNotIn(dev, recipients)
		self.assertEqual(notify.call_args[0][3], f"/request/{request}")

	def test_unrelated_user_without_roles_cannot_comment(self) -> None:
		dev = self._user("dev-comment-3@example.test", ["Dev Team"])
		nobody = self._user("nobody-comment@example.test", [])
		frappe.set_user(dev)
		try:
			from upande_dev_tools.api.requests import create_request

			request = create_request(title="Private-ish", request_type="Bug")["name"]
			frappe.set_user(nobody)
			with self.assertRaises(frappe.PermissionError):
				comments.add_comment("Request", request, "hi")
		finally:
			frappe.set_user("Administrator")


class IntegrationTestNotifications(IntegrationTestCase):
	def test_notify_is_a_no_op_without_upande_mobile(self) -> None:
		with (
			patch.object(notifications, "_push_available", return_value=False),
			patch.object(notifications.frappe, "enqueue") as enqueue,
		):
			notifications.notify(["a@example.test"], "t", "b", "/task/T-1", "event")
		enqueue.assert_not_called()

	def test_notify_enqueues_once_for_unique_recipients(self) -> None:
		with (
			patch.object(notifications, "_push_available", return_value=True),
			patch.object(notifications.frappe, "enqueue") as enqueue,
		):
			notifications.notify(["a@example.test", "a@example.test", ""], "t", "b", "/task/T-1", "event")
		self.assertEqual(enqueue.call_args.kwargs["users"], ["a@example.test"])

	def test_send_push_calls_upande_mobile_with_route(self) -> None:
		with (
			patch.object(notifications, "_push_available", return_value=True),
			patch("upande_mobile.push.notify_user", return_value=1) as send,
		):
			reached = notifications.send_push(["a@example.test"], "t", "b", "/deployments", "event")
		self.assertEqual(reached, 1)
		self.assertEqual(send.call_args.args[:2], (notifications.APP_NAME, "a@example.test"))
		self.assertEqual(send.call_args.kwargs["route"], "/deployments")

	def test_reminders_are_sent_once_per_task_user_and_day(self) -> None:
		task = frappe._dict(name="TASK-1", subject="Fix", exp_end_date="2020-01-01", _assign='["a@example.test"]')
		seen: set[str] = set()

		with (
			patch.object(notifications, "_push_available", return_value=True),
			patch.object(notifications.frappe, "get_all", return_value=[task]),
			patch.object(notifications.frappe.cache, "get_value", side_effect=lambda k: k in seen),
			patch.object(notifications.frappe.cache, "set_value", side_effect=lambda k, *a, **kw: seen.add(k)),
			patch.object(notifications, "notify") as notify,
		):
			notifications.send_due_reminders()
			notifications.send_due_reminders()
		self.assertEqual(notify.call_count, 1)
		self.assertEqual(notify.call_args.args[3:], ("/task/TASK-1", "task_due"))

	def test_handlers_never_raise(self) -> None:
		with patch.object(notifications.frappe, "log_error"):
			notifications.on_todo_insert(None)
			notifications.on_request_update(None)
			notifications.on_deployment_update(None)

	def test_hooks_register_the_scheduler_jobs_and_doc_events(self) -> None:
		from upande_dev_tools import hooks

		self.assertIn("upande_dev_tools.api.notifications.send_due_reminders", hooks.scheduler_events["hourly"])
		self.assertIn("0 8 * * 1-5", hooks.scheduler_events["cron"])
		self.assertIn("*/5 * * * *", hooks.scheduler_events["cron"])
		self.assertEqual(set(hooks.doc_events), {"ToDo", "Request", "Deployment Request"})
