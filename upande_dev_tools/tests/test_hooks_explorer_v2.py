# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
"""Pure-logic tests for api/v2/hooks_explorer.py (no site needed).

Run: python -m unittest upande_dev_tools.tests.test_hooks_explorer_v2   (from the bench venv)
"""

import unittest
from typing import ClassVar

from upande_dev_tools.api.v2 import hooks_explorer as H


class TestEntries(unittest.TestCase):
	def test_doc_events_tuple_key_expands_per_doctype(self):
		value = {("A", "B"): {"on_submit": ["x.y.f", "x.y.g"]}, "*": {"on_update": "x.y.h"}}
		got = list(H._entries_for("app", "doc_events", value))
		self.assertEqual(len(got), 5)  # 2 doctypes x 2 handlers + 1
		self.assertEqual({g[0] for g in got}, {"A", "B", "*"})

	def test_scheduler_cron_and_frequency(self):
		value = {"daily": ["a.b.c"], "cron": {"0 1 * * *": ["a.b.d", "a.b.e"]}}
		got = list(H._entries_for("app", "scheduler_events", value))
		self.assertEqual(len(got), 3)
		self.assertEqual(got[0][0], "daily")

	def test_fixtures_scope_is_doctype(self):
		got = list(H._entries_for("app", "fixtures", [{"dt": "Role", "filters": [["a", "=", 1]]}, "Custom Field"]))
		self.assertEqual([g[4] for g in got], ["Role", "Custom Field"])

	def test_kind(self):
		self.assertEqual(H._kind_of("a.b.c", "doc_events"), "python")
		self.assertEqual(H._kind_of("/assets/app/js/x.js?v=1", "app_include_js"), "file")
		self.assertEqual(H._kind_of("Role", "fixtures"), "fixture")


class TestJsonable(unittest.TestCase):
	def test_tuple_keys_sets_and_secrets(self):
		out = H._jsonable({("A", "B"): {"api_key": "abc", "ok": {1, 2}}, "x": object})
		self.assertIn("A / B", out)
		self.assertEqual(out["A / B"]["api_key"], "***")
		self.assertEqual(sorted(out["A / B"]["ok"]), [1, 2])
		self.assertTrue(isinstance(out["x"], str))


class TestMatch(unittest.TestCase):
	E: ClassVar[dict] = {
		"app": "a", "category": "Document events", "hook": "doc_events", "scope": "*", "event": "on_update",
		"handler": "a.b.c", "doctype": None, "all_doctypes": True, "duplicate_of_count": 0,
		"overridden": False, "found": True,
	}

	def test_doctype_filter_includes_every_doctype_hooks(self):
		a = H._args({"doctype": "Sales Invoice"})
		self.assertTrue(H._match(self.E, a))

	def test_search_terms_all_required(self):
		self.assertTrue(H._match(self.E, H._args({"q": "on_update a.b"})))
		self.assertFalse(H._match(self.E, H._args({"q": "on_update zzz"})))

	def test_status_missing(self):
		self.assertFalse(H._match(self.E, H._args({"status": "missing"})))


if __name__ == "__main__":
	unittest.main()
