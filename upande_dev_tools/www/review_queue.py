# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import frappe

from upande_dev_tools.portal import enforce_page_access

no_cache = 1


def get_context(context):
	enforce_page_access("review-queue")
	context = frappe._dict(context)
	context.no_cache = 1
	context.page_title = "Review Queue"
	context.active_route = "review-queue"
	context.csrf_token = frappe.sessions.get_csrf_token()
	return context
