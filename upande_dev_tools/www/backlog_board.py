# Copyright (c) 2026, Upande Limited

import frappe

from upande_dev_tools.portal import enforce_page_access

no_cache = 1


def get_context(context):
	enforce_page_access("backlog-board")
	context = frappe._dict(context)
	context.no_cache = 1
	context.page_title = "Backlog Board"
	context.active_route = "backlog-board"
	context.csrf_token = frappe.sessions.get_csrf_token()
	context.project = frappe.form_dict.get("project")
	return context
