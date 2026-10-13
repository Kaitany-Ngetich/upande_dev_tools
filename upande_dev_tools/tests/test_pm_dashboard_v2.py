# Read-only checks for api/v2/pm_dashboard.py (the PM Console). Run:
#   bench --site kaitet.local execute upande_dev_tools.tests.test_pm_dashboard_v2.main
# The pure rules need no database; the identity and permission checks read only, as real users
# through frappe.set_user, and end with a rollback.
from datetime import date

import frappe

from upande_dev_tools.api.v2 import pm_dashboard as pm

TODAY = date(2026, 10, 12)
FAILED = []


def check(name, ok, detail=""):
	print(("PASS " if ok else "FAIL ") + name + (f" :: {detail}" if detail else ""))
	if not ok:
		FAILED.append(name)
	return ok


def pure_rules():
	d = date
	check("overdue: yesterday", pm.is_overdue(d(2026, 10, 11), TODAY))
	check("overdue: due today is not late", not pm.is_overdue(TODAY, TODAY))
	check("overdue: no due date is never late", not pm.is_overdue(None, TODAY))
	check("days late", pm.days_late(d(2026, 10, 2), TODAY) == 10 and pm.days_late(TODAY, TODAY) == 0)
	check("stuck: Working and 14 days quiet", pm.is_stuck("Working", 14))
	check("stuck: 13 days is not stuck", not pm.is_stuck("Working", 13))
	check(
		"stuck: other statuses never", not pm.is_stuck("Open", 90) and not pm.is_stuck("Pending Review", 90)
	)
	check(
		"median odd / even / empty",
		pm.median([3, 1, 2]) == 2 and pm.median([1, 2, 3, 4]) == 2.5 and pm.median([]) is None,
	)
	check("overload: above twice the median", pm.carrying_a_lot(11, 5) and not pm.carrying_a_lot(10, 5))
	check("overload: no median, no flag", not pm.carrying_a_lot(5, None) and not pm.carrying_a_lot(5, 0))
	h = pm.project_health
	check("health: nothing open is green", h(0, 0, None, TODAY)["level"] == "good")
	check("health: exactly 20% overdue is green", h(10, 2, d(2026, 10, 10), TODAY)["level"] == "good")
	check(
		"health: over 20% overdue is amber, with the reason",
		(r := h(10, 3, d(2026, 10, 10), TODAY))["level"] == "watch" and "3 of 10" in r["reason"],
		r["reason"],
	)
	check("health: quiet 14 days is amber", h(5, 0, d(2026, 9, 28), TODAY)["level"] == "watch")
	check("health: quiet 13 days is green", h(5, 0, d(2026, 9, 29), TODAY)["level"] == "good")
	check(
		"health: both reasons are joined",
		(r := h(10, 5, d(2026, 9, 1), TODAY))["reason"].count(";") == 1,
		r["reason"],
	)
	check(
		"week start is a Monday",
		pm.week_start(TODAY) == date(2026, 10, 12)
		and pm.week_start(date(2026, 10, 18)) == date(2026, 10, 12),
	)

	acts = pm._row_actions
	check(
		"actions: Projects Manager decides and acts",
		acts("request", {"Projects Manager"}) == ["accept", "defer", "reject"]
		and "reassign" in acts("task", {"Projects Manager"}),
	)
	check(
		"actions: System Manager alone acts on tasks but cannot decide",
		acts("request", {"System Manager"}) == []
		and acts("approved", {"System Manager"}) == []
		and "done" in acts("task", {"System Manager"}),
	)
	check("actions: no role, no actions", acts("task", set()) == [] and acts("request", set()) == [])


def sql(q, p=None):
	return frappe.db.sql(q, p or {}, as_list=True)[0][0]


def identities():
	frappe.set_user("Administrator")
	r = pm.get_pm_console()
	n = r["counts"]
	check(
		"counts equal list lengths",
		n["decide"] == len(r["decide"])
		and n["late"] == len(r["late"])
		and n["no_owner"] == len(r["no_owner"])
		and n["stuck"] == len(r["stuck"]),
	)
	check(
		"Decide = every Under Review request (read-only SQL)",
		n["decide"] == sql("SELECT COUNT(*) FROM tabRequest WHERE workflow_state = 'Under Review'"),
	)
	projects = tuple(p["value"] for p in r["options"]["projects"])
	scope = "project IN %(p)s AND is_group = 0 AND status NOT IN ('Template', 'Cancelled')"
	open_n = sql(f"SELECT COUNT(*) FROM tabTask WHERE {scope} AND status <> 'Completed'", {"p": projects})
	check(
		"projects: open sums to the portfolio's open tasks",
		sum(p["open"] for p in r["projects"]) == open_n,
		f"{open_n}",
	)
	extra = sql(
		f"SELECT COALESCE(SUM(JSON_LENGTH(_assign) - 1), 0) FROM tabTask WHERE {scope} AND status <> 'Completed' AND JSON_VALID(_assign) AND JSON_LENGTH(_assign) > 0",
		{"p": projects},
	)
	unassigned = sql(
		f"SELECT COUNT(*) FROM tabTask WHERE {scope} AND status <> 'Completed' AND (_assign IS NULL OR _assign IN ('', '[]'))",
		{"p": projects},
	)
	check(
		"people: open sums to open assigned tasks + extra assignments",
		sum(p["open"] for p in r["people"]["rows"]) == open_n - unassigned + int(extra),
		f"{open_n} - {unassigned} + {extra}",
	)
	check(
		"late: every row is before today and open",
		all(x["days_late"] > 0 and x["status"] != "Completed" for x in r["late"]),
	)
	check("late: no task twice", len({x["name"] for x in r["late"]}) == len(r["late"]))
	check(
		"stuck: tasks are Working and quiet",
		all(x["status"] == "Working" and x["quiet_days"] >= 14 for x in r["stuck"] if x["kind"] == "task"),
	)
	check(
		"no owner: tasks have nobody",
		all(not x["assignee_ids"] for x in r["no_owner"] if x["kind"] == "task"),
	)
	check("weekly has 12 weeks", len(r["weekly"]) == 12)
	one = r["options"]["assignees"][0]["value"]
	f = pm.get_pm_console(assignee=one)
	check("assignee filter: people shows that person only", [p["user"] for p in f["people"]["rows"]] == [one])
	check(
		"bad filter is a handled error",
		pm.get_pm_console(project="nope")["success"] is False
		and pm.get_pm_console(days="5")["success"] is False,
	)


def permissions():
	roles = lambda u: sorted(set(frappe.get_roles(u)) & {"System Manager", "Projects Manager", "Dev Team"})  # noqa: E731
	for label, user in USERS:
		if not user:
			continue
		frappe.set_user(user)
		try:
			pm.get_pm_console()
			got = "allowed"
		except frappe.PermissionError:
			got = "denied"
		want = "allowed" if set(frappe.get_roles()) & pm.MANAGER_ROLES else "denied"
		check(f"{label} ({user}, {roles(user)}) is {want}", got == want)
	frappe.set_user("Guest")
	try:
		pm.get_pm_console()
		check("Guest is denied", False)
	except frappe.PermissionError:
		check("Guest is denied", True)
	frappe.set_user("Administrator")


USERS = [("Administrator", "Administrator")]


def main():
	try:
		pure_rules()
		frappe.set_user("Administrator")
		USERS.extend(pick_users())
		identities()
		permissions()
	finally:
		frappe.set_user("Administrator")
		frappe.db.rollback()
	print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL PASSED")


def pick_users():
	"""One real enabled user for each role mix (None when the site has no such user). Roles come from
	frappe.get_roles, so roles given through a Role Profile count."""
	managers = pm.MANAGER_ROLES
	found = {}
	for (name,) in frappe.db.sql(
		"SELECT name FROM tabUser WHERE enabled = 1 AND user_type = 'System User' AND name NOT IN ('Administrator', 'Guest') ORDER BY name LIMIT 300"
	):
		roles = set(frappe.get_roles(name))
		if "Projects Manager" in roles:
			found.setdefault("Projects Manager", name)
		elif "Dev Team" in roles and not roles & managers:
			found.setdefault("Dev Team only", name)
		elif not roles & (managers | {"Dev Team"}):
			found.setdefault("no Dev roles", name)
	return [(k, found.get(k)) for k in ("Projects Manager", "Dev Team only", "no Dev roles")]
