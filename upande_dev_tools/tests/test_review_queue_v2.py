# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
"""Tests for api/v2/review_queue.py.

1. Pure helpers (no site needed):  python -m unittest upande_dev_tools.tests.test_review_queue_v2
2. Permissions and the real decision endpoints, in-process as real users, ALWAYS rolled back
   (nothing is committed, mail is muted):
       bench --site kaitet.local execute upande_dev_tools.tests.test_review_queue_v2.check_site
"""

import unittest
from datetime import datetime

from upande_dev_tools.api.v2 import review_queue as rq

PM = {"Projects Manager"}
DEV = {"Dev Team"}


class TestAllowedActions(unittest.TestCase):
	def test_waiting_needs_the_workflow_role(self):
		self.assertEqual(rq.allowed_actions("Under Review", PM, False), ["accept", "approve", "defer", "reject"])
		self.assertEqual(rq.allowed_actions("Under Review", DEV | {"System Manager"}, False), [])

	def test_approved_and_deferred(self):
		self.assertEqual(rq.allowed_actions("Approved", PM, False), ["schedule"])
		self.assertEqual(rq.allowed_actions("Deferred", PM, False), ["reopen"])
		self.assertEqual(rq.allowed_actions("Approved", DEV, False), [])
		self.assertEqual(rq.allowed_actions("Deferred", DEV, False), [])

	def test_reassign_needs_a_task_and_a_reviewer_role(self):
		for state in ("Scheduled", "In Progress"):
			self.assertEqual(rq.allowed_actions(state, DEV, True), ["reassign"])
			self.assertEqual(rq.allowed_actions(state, PM, True), ["reassign"])
			self.assertEqual(rq.allowed_actions(state, PM, False), [])
		self.assertEqual(rq.allowed_actions("Scheduled", {"Customer"}, True), [])

	def test_closed_states_have_no_actions(self):
		for state in ("Rejected", "Completed", "Withdrawn", "Closed"):
			self.assertEqual(rq.allowed_actions(state, PM | DEV, True), [])


class TestAgeHelpers(unittest.TestCase):
	NOW = datetime(2026, 10, 12, 12, 0, 0)

	def test_age_is_whole_days_never_negative(self):
		self.assertEqual(rq._age_days(datetime(2026, 10, 12, 1, 0, 0), self.NOW), 0)
		self.assertEqual(rq._age_days(datetime(2026, 10, 10, 13, 0, 0), self.NOW), 1)
		self.assertEqual(rq._age_days(datetime(2026, 10, 13, 0, 0, 0), self.NOW), 0)
		self.assertEqual(rq._age_days(None, self.NOW), 0)

	def test_labels_and_bands(self):
		self.assertEqual([rq._age_label(d) for d in (0, 1, 9)], ["Today", "1 day", "9 days"])
		self.assertEqual([rq._age_band(d) for d in (0, 2, 3, 6, 7, 13, 14, 90)], ["fresh", "fresh", "few", "few", "week", "week", "fortnight", "fortnight"])

	def test_plain_text(self):
		self.assertEqual(rq._plain("<p>a &amp; b</p><p>c</p>"), "a & b\nc")
		self.assertEqual(rq._plain(None), "")


class TestWhere(unittest.TestCase):
	def test_filters_are_parameters_not_sql(self):
		sql, p = rq._where({"search": "x'; drop table y; --", "priority": rq.NONE}, ("Under Review",), self.now())
		self.assertNotIn("drop table", sql)
		self.assertIn("r.priority IS NULL", sql)
		self.assertTrue(p["q"].startswith("%x'"))

	@staticmethod
	def now():
		return datetime(2026, 10, 12)


def _roles_of(user):
	import frappe

	return set(frappe.get_roles(user))


def check_site():
	"""Permissions + decision endpoints against the local site. Rolls back everything."""
	import frappe

	from upande_dev_tools.api import requests as api

	frappe.flags.mute_emails = True
	frappe.db.commit = lambda *a, **k: None  # nothing in here may persist
	out = []

	def as_user(user, fn, *a, **k):
		frappe.set_user(user)
		try:
			return fn(*a, **k)
		except Exception as e:
			return f"{type(e).__name__}: {str(e)[:70]}"
		finally:
			frappe.set_user("Administrator")

	users = {
		"pm": "diag-pm-only@example.test",
		"dev": "diag-dev-only@example.test",
		"both": "diag-both@example.test",
		"none": "brian.otieno@example.test",
	}
	for label, user in users.items():
		r = as_user(user, rq.get_review_queue)
		shown = r if isinstance(r, str) else f"ok rows={len(r['rows'])} can_decide={r['can_decide']}"
		out.append(f"get_review_queue as {label:4} ({sorted(_roles_of(user) & {'Projects Manager', 'Dev Team', 'System Manager'})}): {shown}")
	out.append("Guest: " + str(as_user("Guest", rq.get_review_queue)))

	waiting = as_user(users["pm"], rq.get_review_queue)["rows"]
	projects = frappe.get_all("Project", pluck="name", limit=1)
	prio = frappe.db.get_value("Priority Level", {"disabled": 0}, "name")
	people = ["judah@upande.com", "mark@upande.com"]
	due = "2026-12-01"
	req = waiting[0]["name"]

	# decisions as a Dev Team-only user must be refused by the workflow, and change nothing
	for label, fn, kw in [
		("accept", api.accept_request, dict(name=req, project=projects[0], priority=prio, complete_by=due, assign_to=people[0])),
		("defer", api.triage_request, dict(name=req, action="Defer", reason="t")),
		("reject", api.triage_request, dict(name=req, action="Reject", reason="t")),
		("approve", api.triage_request, dict(name=req, action="Approve", project=projects[0], priority=prio)),
	]:
		out.append(f"DEV-only {label}: {as_user(users['dev'], fn, **kw)}")
		frappe.db.rollback()
	out.append("state after refusals: " + frappe.db.get_value("Request", req, "workflow_state"))

	# PM: accept = approve + schedule + task + assignment
	res = as_user(users["pm"], api.accept_request, name=req, project=projects[0], priority=prio, complete_by=due, assign_to=",".join(people), comment="check")
	if isinstance(res, dict):
		task = res["task"]
		out.append(f"PM accept: state={res['workflow_state']} task={task} assigned={res['assigned_to']}")
		out.append(f"  task due={frappe.db.get_value('Task', task, 'exp_end_date')} open ToDos={frappe.db.count('ToDo', {'reference_name': task, 'status': 'Open'})}")
		out.append("  v2 actions on that row: " + str([r["actions"] for r in as_user(users["pm"], rq.get_review_queue, view="scheduled")["rows"] if r["name"] == req]))
		as_user(users["pm"], api.reassign_task, name=task, assign_to=people[0], complete_by="2026-12-15")
		out.append(f"  reassign -> _assign={frappe.db.get_value('Task', task, '_assign')} due={frappe.db.get_value('Task', task, 'exp_end_date')}")
	else:
		out.append(f"PM accept: {res}")
	frappe.db.rollback()

	# PM: approve (schedule later) -> promote_to_task (Schedule) -> reassign_task
	res = as_user(users["pm"], api.triage_request, name=req, action="Approve", project=projects[0], priority=prio, reason="ok")
	out.append("PM approve: " + (res["workflow_state"] if isinstance(res, dict) else res))
	res = as_user(users["pm"], api.promote_to_task, name=req)
	out.append("PM schedule: " + (f"{res['workflow_state']} linked_task={res.get('linked_task')}" if isinstance(res, dict) else res))
	frappe.db.rollback()

	# PM: defer (reason required) -> reopen
	out.append("PM defer without reason: " + str(as_user(users["pm"], api.triage_request, name=req, action="Defer")))
	res = as_user(users["pm"], api.triage_request, name=req, action="Defer", reason="later")
	out.append("PM defer: " + (res["workflow_state"] if isinstance(res, dict) else res))
	res = as_user(users["pm"], api.triage_request, name=req, action="Reopen")
	out.append("PM reopen: " + (res["workflow_state"] if isinstance(res, dict) else res))
	frappe.db.rollback()
	res = as_user(users["pm"], api.triage_request, name=req, action="Reject", reason="no")
	out.append("PM reject: " + (res["workflow_state"] if isinstance(res, dict) else res))
	frappe.db.rollback()

	out.append("DB writes kept: " + str(frappe.db.get_value("Request", req, "workflow_state")))
	print("\n".join(out))
