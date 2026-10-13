# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
"""Pure-logic and permission tests for api/v2/code_snapshots.py (no database writes).

Run: python -m unittest upande_dev_tools.tests.test_code_snapshots_v2  (from the bench env)
"""

import unittest
from datetime import date
from unittest import mock

import frappe

from upande_dev_tools.api.v2 import code_snapshots as cs

BASE = {
	"from_date": date(2026, 10, 1),
	"to_date": date(2026, 10, 3),
	"all_dates": False,
	"source_type": "",
	"app": "",
	"trigger": "",
	"kind": "",
	"search": "",
}


class TestWhere(unittest.TestCase):
	def test_date_window_is_half_open_and_optional(self):
		sql, p = cs._where(BASE)
		self.assertIn("s.snapshot_time >= %(f)s AND s.snapshot_time < %(t)s", sql)
		self.assertEqual(p["t"], date(2026, 10, 4))
		sql, p = cs._where(BASE, with_dates=False)
		self.assertEqual((sql, p), ("1=1", {}))

	def test_filters_and_like_escaping(self):
		sql, p = cs._where({**BASE, "source_type": "DocType", "app": cs.NONE_KEY, "search": "a_b%"})
		self.assertIn("s.source_type = %(src)s", sql)
		self.assertIn("s.app IS NULL OR s.app = ''", sql)
		self.assertEqual(p["q"], "%a\\_b\\%%")


class TestSummaries(unittest.TestCase):
	def test_load_rejects_non_objects(self):
		self.assertIsNone(cs._load("[1]"))
		self.assertIsNone(cs._load("not json"))
		self.assertEqual(cs._load('{"a": 1}'), {"a": 1})

	def test_doctype_diff_counts_added_removed_changed(self):
		prev = {"fields": [{"fieldname": "a", "label": "A"}, {"fieldname": "b"}]}
		cur = {"fields": [{"fieldname": "a", "label": "A2"}, {"fieldname": "c"}]}
		ch = cs._doctype_summary(cur, prev)["changes"]
		self.assertEqual(
			(ch["fields_added"], ch["fields_removed"], ch["fields_changed"]), (["c"], ["b"], ["a"])
		)
		self.assertEqual(ch["counts"], {"added": 1, "removed": 1, "changed": 1})

	def test_doctype_diff_ignores_row_ids_and_modified_stamps(self):
		prev = {"fields": [{"fieldname": "a", "name": "x1", "modified": "2026-08-18"}]}
		cur = {"fields": [{"fieldname": "a", "name": "y2", "modified": "2026-08-28"}]}
		self.assertEqual(cs._doctype_summary(cur, prev)["changes"]["counts"]["changed"], 0)

	def test_script_diff_counts_lines_and_never_returns_code(self):
		prev = {"script": "a\nb\nc"}
		cur = {"script": "a\nB\nc\nd", "disabled": 0}
		out = cs._script_summary("Server Script", cur, prev)
		self.assertEqual((out["changes"]["lines_added"], out["changes"]["lines_removed"]), (2, 1))
		self.assertNotIn("a\nB", repr(out))


class TestGate(unittest.TestCase):
	def test_every_read_endpoint_refuses_users_without_dev_team(self):
		with mock.patch.object(frappe, "get_roles", return_value=["Guest", "Sales User"]):
			for fn in (cs.get_overview, cs.get_snapshots, cs.get_runs, cs.get_snapshot):
				self.assertFalse(fn()["success"], fn.__name__)
