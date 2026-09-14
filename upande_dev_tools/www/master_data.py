# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import frappe

from upande_dev_tools.portal import enforce_page_access

no_cache = 1


def get_context(context):
	enforce_page_access("master-data")
	context = frappe._dict(context)
	context.no_cache = 1
	context.page_title = "Master Data"
	context.active_route = "master-data"
	context.csrf_token = frappe.sessions.get_csrf_token()
	return context
