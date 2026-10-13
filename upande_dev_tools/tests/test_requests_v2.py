# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
"""Tests for api/v2/requests.py.

Pure helpers (no site needed):
    env/bin/python -m unittest upande_dev_tools.tests.test_requests_v2
Permission walk through the real endpoints, as real users, rolled back at the end (writes the
page makes are exercised, then undone; no mail is sent because nothing commits):
    bench --site kaitet.local execute upande_dev_tools.tests.test_requests_v2.main
"""

import unittest
from datetime import date, datetime

from upande_dev_tools.api.v2 import requests as R


class TestRowActions(unittest.TestCase):
	def test_edit_is_for_triage_roles_or_the_submitter_while_under_review(self):
		self.assertTrue(R.row_actions("Approved", False, False, True)["can_edit"])
		self.assertTrue(R.row_actions("Under Review", True, True, False)["can_edit"])
		self.assertFalse(R.row_actions("Approved", True, True, False)["can_edit"])
		self.assertFalse(R.row_actions("Under Review", False, False, False)["can_edit"])

	def test_withdraw_needs_the_raiser_and_an_unfinished_state(self):
		for state in R.WITHDRAWABLE:
			self.assertTrue(R.row_actions(state, True, True, False)["can_withdraw"], state)
		for state in ("Completed", "Rejected", "Withdrawn", "Closed"):
			self.assertFalse(R.row_actions(state, True, True, False)["can_withdraw"], state)
		self.assertFalse(R.row_actions("Under Review", False, False, True)["can_withdraw"])

	def test_raised_for_employee_may_withdraw_and_confirm_but_not_edit(self):
		a = R.row_actions("Completed", False, True, False)
		self.assertEqual(a, {"can_edit": False, "can_withdraw": False, "can_confirm": True})
		self.assertTrue(R.row_actions("In Progress", False, True, False)["can_withdraw"])

	def test_confirm_only_when_completed(self):
		self.assertTrue(R.row_actions("Completed", True, True, False)["can_confirm"])
		self.assertFalse(R.row_actions("Closed", True, True, False)["can_confirm"])
		self.assertFalse(R.row_actions("Completed", False, False, True)["can_confirm"])


class TestHelpers(unittest.TestCase):
	def test_median(self):
		self.assertIsNone(R._median([]))
		self.assertEqual(R._median([None, 3, 1, 2]), 2)
		self.assertEqual(R._median([1, 2, 3, 4]), 2.5)

	def test_bucket_unit_follows_span(self):
		self.assertEqual(R._bucket_fn(30)[0], "day")
		self.assertEqual(R._bucket_fn(90)[0], "week")
		self.assertEqual(R._bucket_fn(900)[0], "month")

	def test_week_buckets_start_on_monday(self):
		_unit, fn = R._bucket_fn(90)
		self.assertEqual(fn(date(2026, 10, 14)), "2026-10-12")

	def test_derive_closed_request_uses_history(self):
		row = {
			"creation": datetime(2026, 1, 1, 8),
			"modified": datetime(2026, 1, 9, 8),
			"workflow_state": "Completed",
			"owner": "a@x",
		}
		hist = [
			(datetime(2026, 1, 1, 10), "Under Review", "Approved", "pm@x"),
			(datetime(2026, 1, 3, 8), "Approved", "Completed", "dev@x"),
		]
		d = R._derive(row, hist, [], datetime(2026, 2, 1))
		self.assertEqual(d["first_response_hours"], 2)
		self.assertEqual(d["close_hours"], 48)
		self.assertFalse(d["resolved_estimated"])

	def test_derive_withdrawn_without_history_is_estimated(self):
		row = {
			"creation": datetime(2026, 1, 1),
			"modified": datetime(2026, 1, 2),
			"workflow_state": "Withdrawn",
			"owner": "a@x",
		}
		d = R._derive(row, [], [], datetime(2026, 2, 1))
		self.assertTrue(d["resolved_estimated"])
		self.assertEqual(d["close_hours"], 24)


# ---------------------------------------------------------------- permission walk


def main():
	"""Print what each kind of user sees and may do. Everything is rolled back."""
	import frappe

	frappe.db.commit = lambda *a, **k: None  # nothing in this walk may persist

	from upande_dev_tools.api import requests as W

	users = {
		"neither": "diag-neither@example.test",
		"dev": "diag-dev-only@example.test",
		"pm": "diag-pm-only@example.test",
		"admin": "Administrator",
	}
	for label, u in users.items():
		frappe.set_user(u)
		o = R.get_form_options()
		ov = R.get_requests_overview(from_date="2000-01-01", to_date="2026-12-31")
		print(
			label,
			"kinds",
			o["request_types"],
			"triage",
			o["triage_fields"],
			"areas",
			len(o["product_areas"]),
			"prios",
			o["priorities"],
			"| rows",
			len(ov["rows"]),
			"edit",
			sum(r["can_edit"] for r in ov["rows"]),
			"withdraw",
			sum(r["can_withdraw"] for r in ov["rows"]),
			"confirm",
			sum(r["can_confirm"] for r in ov["rows"]),
			"area_in_rows",
			sum(1 for r in ov["rows"] if r["product_area"]),
		)

	# non-triage user: create drops module/priority, refuses Note, requires known tags
	frappe.set_user(users["neither"])
	tag = frappe.get_all("Work Tag", pluck="name", limit=1)[0]
	made = W.create_request(
		title="ZZTEST perm walk",
		request_type="Feature",
		product_area="Accounting",
		priority="Urgent",
		tags=[tag],
		source="Web Portal",
	)
	print(
		"neither create: area",
		made["product_area"],
		"priority",
		made["priority"],
		"state",
		made["workflow_state"],
	)
	for label, call in {
		"Note by non-dev": lambda: W.create_request(title="ZZTEST n", request_type="Note", tags=[tag]),
		"no tags": lambda: W.create_request(title="ZZTEST t", request_type="Feature", tags=[]),
		"unknown tag": lambda: W.create_request(title="ZZTEST u", request_type="Feature", tags=["nope-tag"]),
	}.items():
		try:
			call()
			print(label, "ALLOWED (unexpected)")
		except Exception as e:
			print(label, "->", type(e).__name__)

	# the raiser's own actions
	d = R.get_request_detail(made["name"])
	print(
		"own detail",
		d["can_edit"],
		d["can_withdraw"],
		d["can_confirm"],
		d["full_detail"],
		"description_raw" in d,
	)
	W.update_request(made["name"], title="ZZTEST perm walk edited", tags=[tag])
	frappe.set_user(users["dev"])
	try:
		W.withdraw_request(made["name"])
		print("other withdraws: ALLOWED (unexpected)")
	except Exception as e:
		print("other withdraws ->", type(e).__name__)
	d = R.get_request_detail(made["name"])
	print(
		"dev sees other's: full",
		d["full_detail"],
		"can_edit",
		d["can_edit"],
		"can_withdraw",
		d["can_withdraw"],
	)
	frappe.set_user(users["pm"])
	other = R.get_request_detail(made["name"])
	print("pm sees other's: full", other["full_detail"], other["can_edit"], other["can_withdraw"])
	frappe.set_user("Guest")
	for fn in (R.get_form_options, lambda: R.get_requests_overview()):
		try:
			fn()
			print("guest ALLOWED (unexpected)")
		except frappe.PermissionError:
			print("guest -> PermissionError")
	frappe.set_user(users["neither"])
	W.withdraw_request(made["name"])
	print("raiser withdraws ->", frappe.db.get_value("Request", made["name"], "workflow_state"))
	frappe.set_user("Administrator")
	frappe.db.rollback()
