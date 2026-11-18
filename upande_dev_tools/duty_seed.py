# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
"""First duty type and the owner's support rota ("Duty Roster Updated.pdf").

Runs from setup.run_setup (after_install / after_migrate) and is idempotent: the Support duty type is created when
missing, and its slots only when Support has no slot at all, so a rota edited on the site is never touched again.
People are matched to users by their exact full name (ignoring case) and only when exactly one enabled user has it;
anyone not matched is listed in the slot's notes so a project manager can add them.
"""

import frappe

SUPPORT = "Support"

WEEKLY = [
	("Week 47", "2026-11-16", "2026-11-22", ["Mark Judah", "Teresiah"]),
	("Week 48", "2026-11-23", "2026-11-29", ["Teddy", "Jennifer", "Otieno"]),
	("Week 49", "2026-11-30", "2026-12-06", ["Wilfred", "Wycliffe", "Rose"]),
	("Week 50", "2026-12-07", "2026-12-13", ["James", "Bavin", "Ivy"]),
	("Week 51", "2026-12-14", "2026-12-20", ["Stephene", "Esperance", "Shadrack"]),
]

DAILY = [
	("2026-12-21", ["Brian", "Austin", "Mandi"]),
	("2026-12-22", ["Teddy", "Teresiah", "Steve Kinyanjui"]),
	("2026-12-23", ["Mark Judah", "Jennifer", "Otieno"]),
	("2026-12-24", ["Wilfred", "Wycliffe", "Rose"]),
	("2026-12-25", ["Wilfred", "Bavin", "Ivy"]),
	("2026-12-26", ["Stephene", "Esperance", "Shadrack"]),
	("2026-12-27", ["Brian", "Austin", "Mandi"]),
	("2026-12-28", ["Teddy", "Teresiah", "Steve Kinyanjui"]),
	("2026-12-29", ["Mark Judah", "Jennifer", "Otieno"]),
	("2026-12-30", ["James", "Wycliffe", "Rose"]),
	("2026-12-31", ["James", "Bavin", "Ivy"]),
	("2027-01-01", ["Stephene", "Esperance", "Shadrack"]),
	("2027-01-02", ["Brian", "Austin", "Mandi"]),
	("2027-01-03", ["Teddy", "Teresiah", "Steve Kinyanjui"]),
]


def _users_by_full_name() -> dict[str, str]:
	rows = frappe.get_all(
		"User",
		filters={"enabled": 1, "name": ["not in", ["Guest", "Administrator"]]},
		fields=["name", "full_name"],
		ignore_permissions=True,
		limit_page_length=0,
	)
	seen: dict[str, list[str]] = {}
	for r in rows:
		if r.full_name:
			seen.setdefault(r.full_name.strip().lower(), []).append(r.name)
	return {k: v[0] for k, v in seen.items() if len(v) == 1}


def seed_support_rota() -> None:
	if not frappe.db.table_exists("Duty Type") or not frappe.db.table_exists("Duty Rota Slot"):
		return
	if not frappe.db.exists("Duty Type", SUPPORT):
		frappe.get_doc(
			{
				"doctype": "Duty Type",
				"duty_name": SUPPORT,
				"description": "First line for user support and incidents.",
				"default_cadence": "Weekly",
				"people_per_slot": 3,
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
	if frappe.db.exists("Duty Rota Slot", {"duty_type": SUPPORT}):
		return
	users = _users_by_full_name()
	for label, start, end, names in WEEKLY + [("", day, day, names) for day, names in DAILY]:
		matched = [users[n.lower()] for n in names if n.lower() in users]
		missing = [n for n in names if n.lower() not in users]
		frappe.get_doc(
			{
				"doctype": "Duty Rota Slot",
				"duty_type": SUPPORT,
				"label": label,
				"start_date": start,
				"end_date": end,
				"notes": ("From the rota PDF, not matched to a user yet: " + ", ".join(missing)) if missing else "",
				"assignees": [{"user": u} for u in dict.fromkeys(matched)],
			}
		).insert(ignore_permissions=True)
