# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
"""Tests for api/v2/master_data.py (the reads behind the Master Data v2 page).

Pure helpers (no site needed):
    env/bin/python -m unittest upande_dev_tools.tests.test_master_data_v2
Permission walk through the real endpoints as real users, rolled back at the end:
    bench --site kaitet.local execute upande_dev_tools.tests.test_master_data_v2.main
"""

import unittest
from datetime import date

from upande_dev_tools.api.v2 import master_data as M


class TestSimilarGroups(unittest.TestCase):
	def test_case_spacing_and_punctuation_group_together(self):
		groups = M._similar_groups(["Good to have", "good-to-have", "Bug"])
		self.assertEqual([sorted(g) for g in groups], [["Good to have", "good-to-have"]])

	def test_abbreviation_matches_its_full_name(self):
		groups = M._similar_groups(["HR", "Human Resources", "Finance"])
		self.assertEqual([sorted(g) for g in groups], [["HR", "Human Resources"]])

	def test_unrelated_names_form_no_group(self):
		self.assertEqual(M._similar_groups(["Bug", "Feature", "Question"]), [])


class TestDateSql(unittest.TestCase):
	def test_bounds_are_inclusive_of_the_last_day(self):
		sql, vals = M._date_sql("d", date(2026, 10, 1), date(2026, 10, 3))
		self.assertEqual(vals, ["2026-10-01", "2026-10-04"])
		self.assertIn("d.creation >=", sql)
		self.assertIn("d.creation <", sql)

	def test_swapped_dates_are_put_in_order(self):
		self.assertEqual(M._dates("2026-10-05", "2026-10-01"), (date(2026, 10, 1), date(2026, 10, 5)))

	def test_no_dates_adds_nothing(self):
		self.assertEqual(M._date_sql("d", None, None), ("", []))


def main():
	"""Who may call the v2 reads: only users holding all three CRUD roles (and the route rule)."""
	import frappe

	roles_all = ["Dev Team", "Projects Manager", "System Manager"]
	frappe.flags.in_test = True
	try:
		for email, roles in (
			("mdv2-none@example.test", []),
			("mdv2-two@example.test", roles_all[:2]),
			("mdv2-all@example.test", roles_all),
		):
			user = frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "T", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
			user.add_roles(*roles)
			frappe.set_user(email)
			try:
				M.get_master_summary()
				allowed = True
			except frappe.PermissionError:
				allowed = False
			frappe.set_user("Administrator")
			print(email, "allowed" if allowed else "denied")
	finally:
		frappe.set_user("Administrator")
		frappe.db.rollback()


if __name__ == "__main__":
	unittest.main()
