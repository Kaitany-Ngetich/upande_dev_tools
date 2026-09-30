# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

"""Seeds a realistic-looking batch of Request records so the (now-public) Requests Portal
and Review Queue have enough volume to actually look like a live system instead of one
lonely test row. Safe to re-run - each run adds another batch rather than erroring, since
there's no uniqueness constraint to collide with; run it again if you want more.

    bench --site kaitet.local execute upande_dev_tools.seed_demo_requests.run
"""

import random

import frappe
from frappe.utils import add_days, now_datetime, random_string

from upande_dev_tools.api.requests import create_request

PERSONAS = [
	("amina.wanjiru@example.test", "Amina", "Wanjiru", []),
	("brian.otieno@example.test", "Brian", "Otieno", []),
	("grace.mutiso@example.test", "Grace", "Mutiso", []),
	("daniel.kiptoo@example.test", "Daniel", "Kiptoo", []),
	("faith.nyambura@example.test", "Faith", "Nyambura", []),
	("peter.omondi@example.test", "Peter", "Omondi", []),
	("lucy.chebet@example.test", "Lucy", "Chebet", ["Dev Team"]),
	("samuel.kariuki@example.test", "Samuel", "Kariuki", ["Dev Team"]),
	("esther.wambui@example.test", "Esther", "Wambui", ["Projects Manager"]),
]

# (title, request_type, weight toward being "old and resolved")
TITLES = [
	("Login page throws a blank screen on slow connections", "Bug"),
	("Add a bulk-export button to the Requests Portal", "Feature"),
	("Coldroom sensor readings are 2 hours behind on the dashboard", "Bug"),
	("Can we get a weekly digest email of open requests?", "Feature"),
	("Payroll report totals don't match the bank file", "Bug"),
	("Rename \"Master Data\" to \"Reference Data\" in the sidebar", "Chore"),
	("Add Swahili as a language option on the mobile app", "Feature"),
	("Product Area list is missing \"Warehouse Ops\"", "Master Data"),
	("Why does the backlog board hide Done items after a week?", "Question"),
	("Duplicate customer records after the last CRM import", "Bug"),
	("Add a dark mode toggle to the dev portal", "Feature"),
	("Priority Level \"Urgent\" isn't showing red on the board", "Bug"),
	("Quick note: check with IT about the new office wifi", "Note"),
	("Set up SSO for the new HR system", "Feature"),
	("Task assignment emails go to spam for some users", "Bug"),
	("Add \"Livestock\" as a Product Area", "Master Data"),
	("Deployment history page loads slowly on mobile data", "Bug"),
	("Can the review queue show how long a request has waited?", "Feature"),
	("Typo on the settings page: \"Pemissions\"", "Chore"),
	("Add an audit trail export for compliance", "Feature"),
	("Backlog board drag-and-drop breaks on Safari", "Bug"),
	("Question: who approves a request raised on someone else's behalf?", "Question"),
	("Add a \"Snoozed\" state so a request isn't lost, just paused", "Feature"),
	("Activity log timestamps are in UTC, should be local time", "Bug"),
	("Quick note: archive the old staging deployment instance", "Note"),
	("Add Product Area \"Shopify\" for the new e-commerce work", "Master Data"),
	("Code editor doesn't show a diff before saving", "Feature"),
	("My Backlog page shows tasks assigned to someone else", "Bug"),
	("Chore: clean up unused Work Tags from last year", "Chore"),
	("Add a filter for \"raised in the last 7 days\"", "Feature"),
	("Portfolio dashboard percentage rounds oddly (100.0% shows as 99%)", "Bug"),
	("Can requests have an attachment, e.g. a screenshot?", "Question"),
	("Add \"Mpesa Integration\" as a Product Area option", "Master Data"),
	("Chore: rotate the deployment app's access token", "Chore"),
	("Hooks explorer times out on a large app", "Bug"),
]

# Roughly the shape of a real backlog: most things get triaged and worked, a handful
# rejected or deferred, a few still sitting untouched.
FINAL_STATES = (
	["Under Review"] * 6
	+ ["Approved"] * 3
	+ ["Scheduled"] * 3
	+ ["In Progress"] * 5
	+ ["Completed"] * 10
	+ ["Rejected"] * 3
	+ ["Deferred"] * 2
	+ ["Withdrawn"] * 2
)


def _ensure_persona(email: str, first: str, last: str, roles: list[str]) -> str:
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": first,
				"last_name": last,
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
	if roles:
		user = frappe.get_doc("User", email)
		user.add_roles(*roles)
	return email


def run(count: int = 35) -> dict:
	for email, first, last, roles in PERSONAS:
		_ensure_persona(email, first, last, roles)

	product_areas = frappe.get_all("Product Area", pluck="name")
	priorities = frappe.get_all("Priority Level", pluck="name")

	dev_team_personas = [email for email, _, _, roles in PERSONAS if "Dev Team" in roles]
	dev_tools_project = frappe.db.get_value("Project", {"project_type": "Dev Tools"}, "name")

	created: list[str] = []
	admin = frappe.session.user
	try:
		for i in range(count):
			title, request_type = random.choice(TITLES)
			# A little variety so re-running doesn't produce visibly identical titles.
			if random.random() < 0.3:
				title = f"{title} ({random_string(4)})"
			# "Note" is Dev-Team-only (Request.validate()) - keep the persona compatible
			# with what it's raising instead of hitting that guard.
			eligible = dev_team_personas if request_type == "Note" else [p[0] for p in PERSONAS]
			persona = random.choice(eligible)

			final_state = random.choice(FINAL_STATES)
			# Approved/Scheduled/In Progress/Completed all require project + priority set
			# (Request.validate()) - true for a real approved request, so the demo data
			# should look the same way rather than leaving them blank.
			needs_project_priority = final_state in ("Approved", "Scheduled", "In Progress", "Completed")

			frappe.set_user(persona)
			doc = create_request(
				title=title,
				request_type=request_type,
				product_area=random.choice(product_areas) if product_areas and random.random() < 0.7 else None,
				tags=[request_type],
				source=random.choice(["Desk", "Web Portal", "Mobile App"]),
			)
			frappe.set_user(admin)

			name = doc["name"]
			days_ago = random.randint(1, 60)
			creation = add_days(now_datetime(), -days_ago)

			updates = {
				"workflow_state": final_state,
				"creation": creation,
				"modified": add_days(creation, random.randint(0, min(days_ago, 10))),
			}
			# project/priority are backfilled directly (not passed to create_request) -
			# a plain persona has no Project read permission, and this is demo data, not
			# a test of that permission check.
			if needs_project_priority:
				updates["project"] = dev_tools_project
				updates["priority"] = random.choice(priorities) if priorities else None
			elif priorities and random.random() < 0.8:
				updates["priority"] = random.choice(priorities)
			frappe.db.set_value("Request", name, updates, update_modified=False)
			created.append(name)
	finally:
		frappe.set_user(admin)

	frappe.db.commit()
	return {"created": len(created), "names": created}
