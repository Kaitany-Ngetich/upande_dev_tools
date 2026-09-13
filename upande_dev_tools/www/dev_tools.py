# Copyright (c) 2026, shadrack@upande.com and contributors
# For license information, please see license.txt

import frappe

from upande_dev_tools.portal import resolve_home_route

no_cache = 1


def get_context(context):
	frappe.local.flags.redirect_location = resolve_home_route()
	raise frappe.Redirect
