# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import frappe

from upande_dev_tools.portal import enforce_page_access

no_cache = 1


def get_context(context):
	enforce_page_access("requests-portal")
	context = frappe._dict(context)
	context.no_cache = 1
	context.page_title = "Requests"
	context.active_route = "requests-portal"
	context.csrf_token = frappe.sessions.get_csrf_token()
	roles = set(frappe.get_roles())
	context.can_raise_note = "Dev Team" in roles
	# Module/Priority/Tags are triage classification - the reviewer's call, not the raiser's -
	# so only Dev Team/Projects Manager see those fields on the create form at all; everyone
	# else gets the plain version and the reviewer fills these in at accept time instead.
	context.is_reviewer = bool(roles & {"Dev Team", "Projects Manager"})
	return context
