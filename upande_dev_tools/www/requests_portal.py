# Copyright (c) 2026, Upande Limited

import frappe

from upande_dev_tools.portal import enforce_page_access

no_cache = 1


def get_context(context):
	enforce_page_access("requests-portal")
	context = frappe._dict(context)
	context.no_cache = 1
	context.page_title = "My Requests"
	context.active_route = "requests-portal"
	context.csrf_token = frappe.sessions.get_csrf_token()
	context.can_raise_note = "Dev Team" in frappe.get_roles()
	return context
