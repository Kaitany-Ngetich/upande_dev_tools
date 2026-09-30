# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import frappe

from upande_dev_tools.portal import enforce_page_access

no_cache = 1


def get_context(context):
	enforce_page_access("deployments")
	context = frappe._dict(context)
	context.no_cache = 1
	context.page_title = "Deployments"
	context.active_route = "deployments"
	context.csrf_token = frappe.sessions.get_csrf_token()
	context.is_approver = bool(set(frappe.get_roles()) & {"Projects Manager", "System Manager"})
	return context
