import frappe
from frappe import _
from frappe.auth import LoginManager
from frappe.twofactor import should_run_2fa


@frappe.whitelist(allow_guest=True)
def mobile_login(usr: str, pwd: str) -> dict:
	"""Authenticates usr/pwd and returns the session id directly in the response body.

	Exists because React Native's networking layer does not reliably expose a login
	response's Set-Cookie header to JS - the OS-level cookie store absorbs it first,
	a real gotcha already hit in the sibling upande-production/upande-packhouse mobile
	apps. Returning {sid, user_id, full_name} in the JSON body sidesteps that entirely,
	instead of relying on the stock /api/method/login endpoint + Set-Cookie parsing.

	Calls LoginManager.authenticate()/post_login() directly rather than LoginManager.login()
	(which reads from frappe.form_dict/frappe.local.response, awkward for a JSON API) - but
	login() is also where two guards live that a real browser login always gets, so they're
	reproduced explicitly here rather than silently skipped:
	- disable_user_pass_login: site-wide "username/password login is off" switch (e.g. SSO-only
	  sites). authenticate() alone doesn't check this at all.
	- should_run_2fa: this endpoint has no OTP round-trip, so a 2FA-enrolled user must be
	  refused here rather than silently logged straight through - otherwise enabling 2FA on
	  this bench would leave a login path that never asks for the second factor.
	force_user_to_reset_password() is deliberately NOT reproduced here: it's a password-expiry
	UX flow (redirect to a reset-password page) with no mobile equivalent, not a security gate -
	a user who's simply due for a password reset can still authenticate.
	"""
	if frappe.get_system_settings("disable_user_pass_login"):
		frappe.throw(_("Login with username and password is not allowed."), frappe.AuthenticationError)

	login_manager = LoginManager()
	login_manager.authenticate(user=usr, pwd=pwd)

	if should_run_2fa(login_manager.user):
		frappe.throw(
			_(
				"Two-factor authentication is enabled for this account. "
				"The mobile app does not support it yet - please sign in from a browser, "
				"or ask an administrator to disable 2FA for this account."
			),
			frappe.AuthenticationError,
		)

	login_manager.post_login()
	return {
		"sid": frappe.session.sid,
		"user_id": frappe.session.user,
		"full_name": frappe.utils.get_fullname(frappe.session.user),
	}


@frappe.whitelist()
def get_session_context() -> dict:
	"""Returns the calling session's identity and roles.

	Deliberately has no role gate: the mobile app calls this right after login to
	decide which tabs to show (or its "no access" screen for a zero-role user), so it
	must succeed and report an empty-of-relevant-roles list rather than raise
	PermissionError for that exact case.
	"""
	return {
		"email": frappe.session.user,
		"full_name": frappe.utils.get_fullname(frappe.session.user),
		"roles": frappe.get_roles(),
	}
