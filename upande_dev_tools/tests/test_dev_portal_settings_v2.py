# Tests for api/v2/dev_portal_settings.py and www/dev_portal_settings_v2.py. Reads only; nothing is written.
#
# Pure logic (access_diff / refusal-free identities):
#   python -m unittest upande_dev_tools.tests.test_dev_portal_settings_v2   (from apps/upande_dev_tools)
# Permission matrix against the local site (read-only):
#   bench --site kaitet.local execute upande_dev_tools.tests.test_dev_portal_settings_v2.main

import unittest

import frappe

from upande_dev_tools.api.v2.dev_portal_settings import access_diff

ROLES_OF = {
	"a": {"All", "Dev Team"},
	"b": {"All", "Dev Team", "System Manager"},
	"c": {"All", "Projects Manager"},
	"d": {"All"},
}


class TestAccessDiff(unittest.TestCase):
	def diff(self, before, after, me=("All",)):
		return access_diff(ROLES_OF, before, after, set(me))

	def test_adding_a_role_in_or_mode_only_gains(self):
		r = self.diff(({"Dev Team"}, False), ({"Dev Team", "Projects Manager"}, False))
		self.assertEqual((r["before"], r["after"], r["gain"], r["lose_n"]), (2, 3, ["c"], 0))

	def test_require_all_loses_people_missing_a_role(self):
		r = self.diff(({"Dev Team", "System Manager"}, False), ({"Dev Team", "System Manager"}, True))
		self.assertEqual((r["before"], r["after"], r["lose"]), (2, 1, ["a"]))

	def test_no_roles_means_nobody(self):
		r = self.diff(({"Dev Team"}, False), (set(), False), me=("Dev Team",))
		self.assertEqual((r["after"], r["lose_n"]), (0, 2))
		self.assertTrue(r["you_before"])
		self.assertFalse(r["you_after"])

	def test_all_role_opens_for_everyone(self):
		r = self.diff((set(), False), ({"All"}, False))
		self.assertEqual((r["before"], r["after"], r["gain_n"]), (0, 4, 4))

	def test_identity_after_equals_before_minus_lose_plus_gain(self):
		for after in ({"Dev Team"}, {"System Manager"}, {"Projects Manager", "Dev Team"}, set()):
			for flag in (False, True):
				r = self.diff(({"Dev Team"}, False), (after, flag))
				self.assertEqual(r["after"], r["before"] - r["lose_n"] + r["gain_n"])

	def test_names_are_capped(self):
		many = {f"u{i}": {"All", "X"} for i in range(30)}
		r = access_diff(many, (set(), False), ({"X"}, False), set())
		self.assertEqual((r["gain_n"], len(r["gain"])), (30, 10))


def main():
	"""Who may call each endpoint (expected: Dev Team AND System Manager for the v2 reads)."""
	from upande_dev_tools import dev_v2
	from upande_dev_tools.api import dev_portal_settings as old
	from upande_dev_tools.api.v2 import dev_portal_settings as new
	from upande_dev_tools.www import dev_portal_settings_v2 as www

	dev_v2.get_csrf_token = lambda: "token"  # no browser session in a script

	users = {
		"dual": "austin@upande.com",
		"dev-only": "diag-dev-only@example.test",
		"sm+pm (no Dev Team)": "api@upande.com",
		"pm-only": "diag-pm-only@example.test",
		"website user": "amina.wanjiru@example.test",
	}

	def attempt(fn, *args):
		try:
			fn(*args)
			return "ok"
		except frappe.PermissionError:
			return "DENIED"
		except Exception as e:
			return type(e).__name__

	for label, user in users.items():
		frappe.set_user(user)
		try:
			ctx = frappe._dict()
			try:
				www.get_context(ctx)
				page = "opens"
			except frappe.Redirect:
				page = "redirected"
			print(
				f"{label:20} page={page:10} can_manage={ctx.get('can_manage')} can_read_peak={ctx.get('can_read_peak')} "
				f"get_settings={attempt(new.get_settings)} "
				f"preview={attempt(new.preview_access, 'dev-portal-settings', ['Dev Team', 'System Manager'], 1)} "
				f"old.get_registered_pages={attempt(old.get_registered_pages)} "
				f"old.get_peak={attempt(old.get_peak_hours_settings)}"
			)
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None
