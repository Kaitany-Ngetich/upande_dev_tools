"""Role gates and row-shape checks for the Deployments v2 page.

Run: bench --site kaitet.local execute upande_dev_tools.tests.test_deployments_v2.main

Writes are never executed: the write endpoints are only called as users who must be REFUSED
(they raise before touching any record), and the allowed paths are asserted from the page
flags and the role sets instead.
"""

import frappe

from upande_dev_tools import dev_v2
from upande_dev_tools.api import deployments as W
from upande_dev_tools.api.v2 import deployments as R
from upande_dev_tools.www import deployments_v2 as page

DEV_ONLY = "diag-dev-only@example.test"
PM_ONLY = "diag-pm-only@example.test"
DEV_AND_PM = "diag-both@example.test"
NO_ROLE = "a.rotich@karenroses.com"

#: user -> (can_create, is_approver, can_change_state) as the page must draw them
EXPECTED_FLAGS = {
	DEV_ONLY: (True, False, False),
	PM_ONLY: (False, True, False),
	DEV_AND_PM: (True, True, False),
	"Administrator": (True, True, True),
}


def _refused(fn, *args, **kw):
	try:
		fn(*args, **kw)
	except frappe.PermissionError:
		return True
	return False


def main():
	dev_v2.get_csrf_token = lambda: "test"  # no session exists under bench execute
	failures = []

	def check(label, ok):
		print(("PASS " if ok else "FAIL ") + label)
		if not ok:
			failures.append(label)

	for user, expected in EXPECTED_FLAGS.items():
		frappe.set_user(user)
		ctx = page.get_context(frappe._dict())
		check(f"page flags {user}", (ctx.can_create, ctx.is_approver, ctx.can_change_state) == expected)

	frappe.set_user(NO_ROLE)
	check("read refused without a viewer role", _refused(R.get_deployments))
	check("create refused without a deployer role", _refused(W.create_deployment_request, app="x", instance="y"))
	check("approve refused without an approver role", _refused(W.approve_deployment_request, name="none"))
	frappe.set_user(PM_ONLY)
	check("create refused for Projects Manager only", _refused(W.create_deployment_request, app="x", instance="y"))
	check("state change refused for Projects Manager only", _refused(W.update_deployment_status, name="none", action="Start Deployment"))
	frappe.set_user(DEV_ONLY)
	check("approve refused for Dev Team only", _refused(W.approve_deployment_request, name="none"))
	check("reject refused for Dev Team only", _refused(W.reject_deployment_request, name="none"))
	check("state change refused for Dev Team without System Manager", _refused(W.update_deployment_status, name="none", action="Start Deployment"))
	frappe.set_user(DEV_AND_PM)
	check("state change refused without System Manager (Dev Team + PM)", _refused(W.update_deployment_status, name="none", action="Start Deployment"))

	frappe.set_user("Administrator")
	data = R.get_deployments(from_date="", to_date="")
	rows = data["requests"]
	check("rows carry workflow_state and pending_approval", all("workflow_state" in r and "pending_approval" in r for r in rows))
	check("waiting approval = rows flagged pending (Requested only)", data["totals"]["waiting_approval"] == sum(1 for r in rows if r["pending_approval"] and r["workflow_state"] == "Requested"))
	check("open queue size = open total", len(data["open_queue"]) == data["totals"]["open"])
	frappe.set_user("Administrator")
	print("FAILURES:", failures or "none")
