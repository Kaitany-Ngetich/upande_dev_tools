# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
"""Pure-logic tests for api/v2/activity_log.py (range, status, scrubbing); no DB rows needed."""

from frappe.tests import UnitTestCase
from frappe.utils import add_days, getdate, nowdate

from upande_dev_tools.api.v2 import activity_log as al


class TestActivityLogV2(UnitTestCase):
	def test_default_range_is_30_days_ending_today(self):
		f, t, clamped, all_time = al._range({})
		self.assertEqual((t - f).days + 1, al.DEFAULT_DAYS)
		self.assertEqual(t, getdate(nowdate()))
		self.assertFalse(clamped or all_time)

	def test_range_is_clamped_and_ordered(self):
		f, t, clamped, _ = al._range({"from_date": "2020-01-01", "to_date": "2026-01-01"})
		self.assertTrue(clamped)
		self.assertEqual((t - f).days + 1, al.MAX_DAYS)
		f, t, _c, _a = al._range({"from_date": "2026-02-02", "to_date": "2026-02-01"})
		self.assertLess(f, t)

	def test_all_time_leaves_where_unbounded(self):
		a = al._a_args({"all_time": "1"})
		self.assertTrue(a["all_time"])
		self.assertEqual(al._a_where(a), ("1=1", {}))
		self.assertEqual((a["to"] - a["from"]).days + 1, al.ALL_TIME_CHART_DAYS)

	def test_bounded_where_is_half_open(self):
		a = al._a_args({"from_date": "2026-03-01", "to_date": "2026-03-02"})
		where, p = al._a_where(a)
		self.assertIn("activity_time < %(t)s", where)
		self.assertEqual(p["t"], add_days(a["to"], 1))

	def test_unknown_status_is_ignored(self):
		self.assertEqual(al._known_status("Nope"), "")
		self.assertEqual(al._known_status("Error"), "Error")

	def test_scrub_hides_secrets(self):
		self.assertNotIn("abc12345", al._scrub("api_key=abc12345 ok"))
		self.assertNotIn("zzzzzzzzzz", al._scrub("Authorization: Bearer zzzzzzzzzz"))
		self.assertEqual(al._scrub("plain text"), "plain text")
