# Read-only role/identity check for api/v2/overview.py.
# Run: bench --site kaitet.local execute upande_dev_tools.tests.test_overview_v2.main
import frappe

ROLE_USERS = ("Administrator", "diag-dev-only@example.test", "diag-pm-only@example.test", "diag-both@example.test")


def _plain_user() -> str | None:
	"""An enabled system user with none of the Dev Tools roles (only the implicit All role)."""
	rows = frappe.db.sql(
		"""SELECT name FROM tabUser WHERE enabled = 1 AND user_type = 'System User' AND name NOT IN
		   (SELECT parent FROM `tabHas Role` WHERE parenttype = 'User'
		    AND role IN ('Dev Team', 'Projects Manager', 'System Manager')) LIMIT 1"""
	)
	return rows[0][0] if rows else None


def main():
	frappe.db.commit = lambda *a, **k: None  # reads only
	from upande_dev_tools.api.v2 import overview as O

	users = list(ROLE_USERS) + [u for u in [_plain_user()] if u]
	for u in users:
		frappe.set_user(u)
		d = O.get_overview(from_date="2026-01-01", to_date="2026-10-11")
		keys = [k["key"] for k in d["kpis"]]
		pages = [p["key"] for g in d["nav"] for p in g["pages"]]
		desk = [p["key"] for g in d["desk"] for p in g["pages"]]
		print(u)
		print("  kpis", keys)
		print("  pages", pages)
		print("  desk", desk)
		print("  home", d["landing"]["home"], "quick", [q["label"] for q in d["quick"]])
		r = d["requests"]
		assert r["open"] + r["closed_of_opened"] == r["opened"] == sum(r["by_state"].values()), "request identity"
		for kpi in O.DRILL_KPIS:
			try:
				O.get_overview_items(kpi, from_date="2026-01-01", to_date="2026-10-11")
				allowed = True
			except frappe.PermissionError:
				allowed = False
			assert allowed == (kpi in keys), (u, kpi, allowed)
	frappe.set_user("Guest")
	try:
		O.get_overview()
		print("Guest: ALLOWED (bug)")
	except frappe.PermissionError:
		print("Guest: PermissionError")
	frappe.set_user("Administrator")
