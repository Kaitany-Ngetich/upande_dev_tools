# Copyright (c) 2026, Upande LTD and contributors
"""Unit tests for the pure helpers of api/v2/version_check.py (no site needed).

Run: cd apps/upande_dev_tools && ../../env/bin/python -m unittest upande_dev_tools.tests.test_version_check_v2
"""

import unittest
from types import SimpleNamespace

from upande_dev_tools.api.v2 import version_check as vc


def rec(**kw):
	base = {"commits_ahead": 0, "commits_behind": 0, "has_uncommitted_changes": 0, "upstream_branch": "u/x"}
	return SimpleNamespace(**{**base, **kw})


def row(**kw):
	base = {
		"app": "a",
		"state": "in_sync",
		"version_result": "same",
		"check_date": "2026-09-30",
		"stored_risk": "Low",
		"stored_status": "Clean",
		"safe_to_deploy": True,
		"record": "a",
	}
	return {**base, **kw}


class TestVersionCompare(unittest.TestCase):
	def test_semantic_not_text(self):
		self.assertEqual(vc.compare_versions("1.9.5", "1.10.2"), "code_newer")
		self.assertEqual(vc.compare_versions("1.10.2", "1.9.5"), "code_older")

	def test_equal_forms(self):
		self.assertEqual(vc.compare_versions("1.0", "1.0.0"), "same")

	def test_prerelease_is_older(self):
		self.assertEqual(vc.compare_versions("17.0.0-dev", "17.0.0"), "code_newer")

	def test_placeholders_cannot_compare(self):
		self.assertEqual(vc.compare_versions("17.x.x-develop (273e9f2)", "17.0.0"), "unknown")
		self.assertEqual(vc.compare_versions(None, "1.0.0"), "unknown")


class TestRisk(unittest.TestCase):
	def test_desk_rule(self):
		self.assertEqual(vc.risk_by_desk_rule("Clean"), "Low")
		self.assertEqual(vc.risk_by_desk_rule("Dirty"), "Medium")
		self.assertEqual(vc.risk_by_desk_rule("Stale", 9), "High")
		self.assertEqual(vc.risk_by_desk_rule("Stale", 10), "Critical")
		self.assertEqual(vc.risk_by_desk_rule("Diverged"), "Critical")
		self.assertEqual(vc.risk_by_desk_rule("Error"), "Critical")


class TestState(unittest.TestCase):
	def test_precedence(self):
		self.assertEqual(vc._state(None), "never_checked")
		self.assertEqual(vc._state(rec(commits_ahead=1, commits_behind=2)), "diverged")
		self.assertEqual(vc._state(rec(commits_behind=2, has_uncommitted_changes=1)), "behind")
		self.assertEqual(vc._state(rec(commits_ahead=1)), "ahead")
		self.assertEqual(vc._state(rec(has_uncommitted_changes=1)), "dirty")
		self.assertEqual(vc._state(rec(upstream_branch="")), "no_remote")
		self.assertEqual(vc._state(rec()), "in_sync")


class TestFilters(unittest.TestCase):
	def test_args_drop_unknown_values(self):
		a = vc._args({"risk": "Nope", "recorded": "Nope", "safe": "maybe", "status": "x"})
		self.assertEqual((a["risk"], a["recorded"], a["safe"], a["status"]), ("", "", "", ""))

	def test_match_risk_recorded_safe(self):
		a = vc._args({"risk": "High", "recorded": "Dirty", "safe": "no"})
		self.assertFalse(vc._match(row(), a))
		self.assertTrue(vc._match(row(stored_risk="High", stored_status="Dirty", safe_to_deploy=False), a))

	def test_match_skip_status_for_counts(self):
		a = vc._args({"status": "behind"})
		self.assertFalse(vc._match(row(), a))
		self.assertTrue(vc._match(row(), a, skip=("status",)))

	def test_swapped_dates_are_ordered(self):
		a = vc._args({"from_date": "2026-09-30", "to_date": "2026-09-01"})
		self.assertEqual((a["from_date"], a["to_date"]), ("2026-09-01", "2026-09-30"))


if __name__ == "__main__":
	unittest.main()
