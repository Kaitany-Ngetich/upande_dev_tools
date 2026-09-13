# Copyright (c) 2026, shadrack@upande.com and contributors
# For license information, please see license.txt

import frappe

from upande_dev_tools.portal import enforce_page_access

no_cache = 1


def get_context(context):
	enforce_page_access("dev-portal-settings")
	context.no_cache = 1
	context.page_title = "Settings"
	context.active_route = "dev-portal-settings"
	context.csrf_token = frappe.sessions.get_csrf_token()
	return context
