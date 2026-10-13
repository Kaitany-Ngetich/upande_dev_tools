# Checks for api/v2/my_backlog.py. Pure helpers need no Frappe context:
#   python3 -c "from upande_dev_tools.tests.test_my_backlog_v2 import test_pure; test_pure()"
# Scoping/permission/identity checks are read-only:
#   bench --site kaitet.local execute upande_dev_tools.tests.test_my_backlog_v2.main --kwargs "{'users': ['a@x.com']}"
from datetime import date

import frappe

from upande_dev_tools.api.v2 import my_backlog as M

TODAY = date(2026, 10, 11)


def test_pure():
	b = M._bucket
	assert b(None, "Overdue", TODAY) == "overdue" and b(None, "Open", TODAY) == "none"
	assert b(date(2026, 10, 10), "Open", TODAY) == "overdue"
	assert b(TODAY, "Open", TODAY) == "today"
	assert b(date(2026, 10, 17), "Open", TODAY) == "week" and b(date(2026, 10, 18), "Open", TODAY) == "later"
	e = M._effective_status
	assert e("overdue", "Working") == "Overdue"
	assert e("today", "Overdue") == "Open"  # stale nightly flag, date says not late
	assert e("week", "Pending Review") == "Pending Review"
	tasks = [{"age_days": d} for d in (0, 6, 7, 13, 14, 29, 30, 400)]
	bands = M._age_bands(tasks)
	assert [x["count"] for x in bands] == [2, 2, 2, 2] and sum(x["count"] for x in bands) == len(tasks)
	assert M._like_escape("a_b%c") == "a\\_b\\%c"
	assert (
		M._assignee_count('["a","b"]') == 2 and M._assignee_count("bad") == 0 and M._assignee_count(None) == 0
	)


def main(users=()):
	"""For each user: identities hold, nothing from another user leaks, status rights are as expected."""
	test_pure()
	frappe.db.commit = lambda *a, **k: None  # reads only
	for u in users:
		frappe.set_user(u)
		d = M.get_my_backlog()
		k = d["kpis"]
		assert (
			k["open"]
			== len(d["tasks"])
			== sum(x["count"] for x in d["by_status"])
			== sum(x["count"] for x in d["age_bands"])
		)
		assert k["open"] == k["overdue"] + k["due_today"] + k["due_week"] + k["later"] + k["no_due_date"]
		assert all(f'"{u}"' in (frappe.db.get_value("Task", t["name"], "_assign") or "") for t in d["tasks"])
		assert all(frappe.db.get_value("Request", r["name"], "owner") == u for r in d["requests"])
		assert d["can_change_status"] == bool(set(frappe.get_roles(u)) & M.REVIEWER_ROLES)
		print(
			u, "open", k["open"], "overdue", k["overdue"], "can_change_status", d["can_change_status"], "OK"
		)
	frappe.set_user("Guest")
	try:
		M.get_my_backlog()
		raise AssertionError("guest allowed")
	except frappe.PermissionError:
		print("guest refused OK")
	frappe.set_user("Administrator")
