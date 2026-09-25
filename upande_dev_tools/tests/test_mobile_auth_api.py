# Copyright (c) 2026, Upande Limited

import frappe
from frappe.auth import CookieManager
from frappe.tests import IntegrationTestCase
from frappe.utils import set_request
from frappe.utils.password import update_password

from upande_dev_tools.api.mobile_auth import get_session_context, mobile_login


class IntegrationTestMobileAuthApi(IntegrationTestCase):
	def setUp(self) -> None:
		"""Set up request context for LoginManager in bare test calls.

		LoginManager.__init__ unconditionally reads frappe.local.request.path to check if
		this is a login request. IntegrationTestCase clears frappe.local.request by design,
		so we must restore it here. This is necessary because mobile_login() calls
		LoginManager() directly, not through the HTTP layer that would normally set this up.

		See frappe/core/doctype/user/test_user.py and
		frappe/core/doctype/activity_log/test_activity_log.py for canonical examples.
		"""
		set_request(path="/api/method/upande_dev_tools.api.mobile_auth.mobile_login")
		frappe.local.cookie_manager = CookieManager()
		frappe.local.request_ip = "127.0.0.1"

	def _make_user(self, email: str, roles: list[str], password: str) -> str:
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Test", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		user = frappe.get_doc("User", email)
		if roles:
			user.add_roles(*roles)
		update_password(email, password)
		return email

	def test_mobile_login_returns_sid_for_valid_credentials(self) -> None:
		email = self._make_user("mobile-login-ok@example.test", ["Dev Team"], "TestPass123!")
		try:
			result = mobile_login(usr=email, pwd="TestPass123!")
			self.assertTrue(result["sid"])
			self.assertEqual(result["user_id"], email)
			self.assertTrue(result["full_name"])
		finally:
			frappe.set_user("Administrator")

	def test_mobile_login_rejects_bad_password(self) -> None:
		email = self._make_user("mobile-login-bad@example.test", [], "TestPass123!")
		try:
			with self.assertRaises(frappe.AuthenticationError):
				mobile_login(usr=email, pwd="wrong-password")
		finally:
			frappe.set_user("Administrator")

	def test_mobile_login_rejects_when_user_pass_login_disabled(self) -> None:
		email = self._make_user("mobile-login-disabled@example.test", [], "TestPass123!")
		frappe.db.set_single_value("System Settings", "disable_user_pass_login", 1)
		# frappe.local.system_settings is a per-process cache that set_single_value alone does
		# not invalidate - without this, get_system_settings can keep returning whatever it
		# first cached, regardless of what other tests already ran.
		frappe.clear_cache()
		try:
			with self.assertRaises(frappe.AuthenticationError):
				mobile_login(usr=email, pwd="TestPass123!")
		finally:
			frappe.db.set_single_value("System Settings", "disable_user_pass_login", 0)
			frappe.clear_cache()
			frappe.set_user("Administrator")

	def test_mobile_login_rejects_2fa_enrolled_user(self) -> None:
		# should_run_2fa checks the "All" role's two_factor_auth flag (every user has "All"),
		# combined with the site-wide enable_two_factor_auth setting - see
		# frappe.twofactor.two_factor_is_enabled_for_.
		email = self._make_user("mobile-login-2fa@example.test", [], "TestPass123!")
		frappe.db.set_single_value("System Settings", "enable_two_factor_auth", 1)
		frappe.db.set_value("Role", "All", "two_factor_auth", 1)
		frappe.clear_cache()
		try:
			with self.assertRaises(frappe.AuthenticationError):
				mobile_login(usr=email, pwd="TestPass123!")
		finally:
			frappe.db.set_value("Role", "All", "two_factor_auth", 0)
			frappe.db.set_single_value("System Settings", "enable_two_factor_auth", 0)
			frappe.clear_cache()
			frappe.set_user("Administrator")

	def test_get_session_context_returns_roles_for_authenticated_user(self) -> None:
		email = self._make_user(
			"mobile-context@example.test", ["Dev Team", "Projects Manager"], "TestPass123!"
		)
		frappe.set_user(email)
		try:
			context = get_session_context()
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(context["email"], email)
		self.assertIn("Dev Team", context["roles"])
		self.assertIn("Projects Manager", context["roles"])

	def test_get_session_context_excludes_mobile_roles_for_zero_role_user(self) -> None:
		email = self._make_user("mobile-context-none@example.test", [], "TestPass123!")
		frappe.set_user(email)
		try:
			context = get_session_context()
		finally:
			frappe.set_user("Administrator")
		self.assertNotIn("Dev Team", context["roles"])
		self.assertNotIn("Projects Manager", context["roles"])
