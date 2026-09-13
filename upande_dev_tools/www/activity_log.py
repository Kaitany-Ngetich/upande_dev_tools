# Copyright (c) 2026, Upande Limited

import frappe

from upande_dev_tools.portal import enforce_page_access

no_cache = 1


def get_context(context):
	enforce_page_access("activity-log")
	context = frappe._dict(context)
	context.no_cache = 1
	context.page_title = "Activity Log"
	context.active_route = "activity-log"
	context.csrf_token = frappe.sessions.get_csrf_token()
	context.initial_status = frappe.form_dict.get("status") or ""
	return context
