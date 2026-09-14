import frappe
from frappe.auth import LoginManager


@frappe.whitelist(allow_guest=True)
def mobile_login(usr: str, pwd: str) -> dict:
	"""Authenticates usr/pwd and returns the session id directly in the response body.

	Exists because React Native's networking layer does not reliably expose a login
	response's Set-Cookie header to JS - the OS-level cookie store absorbs it first,
	a real gotcha already hit in the sibling upande-production/upande-packhouse mobile
	apps. Returning {sid, user_id, full_name} in the JSON body sidesteps that entirely,
	instead of relying on the stock /api/method/login endpoint + Set-Cookie parsing.
	"""
	login_manager = LoginManager()
	login_manager.authenticate(user=usr, pwd=pwd)
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
