# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
#
# Settings v2 (www/dev-portal-settings-v2.html). Opens under the same Dev Portal Page rule as the
# current Settings page ("dev-portal-settings"); what the person may change is decided per
# section by the same roles the existing endpoints check.

import frappe

from upande_dev_tools import portal
from upande_dev_tools.api.dev_portal_settings import SETTINGS_ROLES
from upande_dev_tools.dev_v2 import page_context

no_cache = 1

#: Roles that may read (not change) the peak-hours window: get_peak_hours_settings.
PEAK_READ_ROLES = {*SETTINGS_ROLES, "Projects Manager"}


def get_context(context):
	context = page_context(context, "dev-portal-settings", "Settings")
	roles = set(frappe.get_roles())
	context.can_manage = set(SETTINGS_ROLES) <= roles
	context.can_read_peak = bool(roles & PEAK_READ_ROLES)
	context.settings_roles = " and ".join(SETTINGS_ROLES)
	context.page_v = portal.asset_version("js/dev-v2-dev-portal-settings.js")
	context.css_v = portal.asset_version("css/dev-v2-dev-portal-settings.css")
	return context
