# Copyright (c) 2026, Upande Limited

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
