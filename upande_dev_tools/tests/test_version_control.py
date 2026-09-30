# Copyright (c) 2026, Upande Limited

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from upande_dev_tools.api.dashboard import get_dashboard_data
from upande_dev_tools.api.version_control import scan_bench


class IntegrationTestVersionControl(IntegrationTestCase):
	def test_scan_records_every_installed_app(self) -> None:
		result = scan_bench()
		self.assertEqual(result["failed"], [])
		self.assertEqual(result["checked"], len(frappe.get_installed_apps()))

		for app in frappe.get_installed_apps():
			self.assertTrue(frappe.db.exists("Module Version Check", app), app)

	def test_a_scanned_app_reports_a_real_branch(self) -> None:
		scan_bench()
		row = frappe.db.get_value(
			"Module Version Check",
			"upande_dev_tools",
			["current_branch", "status", "last_checked_at"],
			as_dict=True,
		)
		self.assertTrue(row.current_branch)
		self.assertIn(row.status, ("Clean", "Dirty", "Ahead", "Stale"))
		self.assertTrue(row.last_checked_at)

	def test_dashboard_counts_agree_with_what_it_lists(self) -> None:
		scan_bench()
		data = get_dashboard_data()
		states = [app["status"] for app in data["apps"]]

		self.assertEqual(data["installed_apps"], len(data["apps"]))
		self.assertEqual(data["clean_apps"], states.count("Clean"))
		self.assertEqual(data["dirty_apps"], states.count("Dirty"))
		self.assertEqual(data["stale_apps"], states.count("Stale"))

	def test_a_clean_app_is_never_reported_by_its_risk_level(self) -> None:
		scan_bench()
		for app in get_dashboard_data()["apps"]:
			self.assertNotIn(app["status"], ("Low", "Medium", "High", "Critical"))

	def test_repo_url_resolves_a_remote_that_is_not_named_origin(self) -> None:
		"""The real bug: get_repo_url used to hardcode "remote get-url origin", which only
		one app on this bench actually uses - every other one (frappe included) tracks a
		remote named "upstream" instead, and used to come back with no URL at all despite
		being a perfectly normal, fully-configured clone."""
		scan_bench()
		row = frappe.db.get_value("Module Version Check", "frappe", "repository_url")
		self.assertTrue(row)
		self.assertTrue(row.startswith("https://"))

	def test_scan_bench_never_erases_a_known_good_repository_url(self) -> None:
		"""A blank result from one scan (a flaky git command, a momentary lock, whatever)
		must never overwrite a URL a previous scan already found - that's what made the
		dashboard's "copy repo URL" button work for a while and then vanish."""
		scan_bench()
		known_good = frappe.db.get_value("Module Version Check", "frappe", "repository_url")
		self.assertTrue(known_good)

		with patch(
			"upande_dev_tools.api.version_control._analyse",
			return_value={
				"status": "CLEAN",
				"branch": "version-16",
				"upstream": "upstream/version-16",
				"ahead": 0,
				"behind": 0,
				"dirty": False,
				"repo_url": None,
			},
		):
			scan_bench()

		self.assertEqual(frappe.db.get_value("Module Version Check", "frappe", "repository_url"), known_good)
