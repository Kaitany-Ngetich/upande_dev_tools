# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
#
# PM Dashboard v2 (www/pm-dashboard-v2.html). Access follows the current page's route
# (pm-dashboard) through dev_v2.page_context; the API enforces the manager roles itself.

from upande_dev_tools import portal
from upande_dev_tools.dev_v2 import page_context

no_cache = 1


def get_context(context):
	page_context(context, "pm-dashboard", "PM Dashboard")
	context.page_v = portal.asset_version("js/dev-v2-pm-dashboard.js")
	context.page_css_v = portal.asset_version("css/dev-v2-pm-dashboard.css")
	return context
