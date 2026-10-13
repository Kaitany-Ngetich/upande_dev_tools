# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
#
# Dev Dashboard v2 (www/dev-dashboard-v2.html): bench health and git state. Open to the roles
# that may open /dev-dashboard.

from upande_dev_tools import portal
from upande_dev_tools.dev_v2 import page_context

no_cache = 1


def get_context(context):
	context = page_context(context, "dev-dashboard", "Dev Dashboard")
	context.page_v = portal.asset_version("js/dev-v2-dev-dashboard.js")
	context.css_v = portal.asset_version("css/dev-v2-dev-dashboard.css")
	return context
