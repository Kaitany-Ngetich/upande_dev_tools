# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
#
# Activity Log v2 (www/activity-log-v2.html). Open to the roles that may open /activity-log.

from upande_dev_tools import portal
from upande_dev_tools.dev_v2 import page_context

no_cache = 1


def get_context(context):
	context = page_context(context, "activity-log", "Activity Log")
	context.page_v = portal.asset_version("js/dev-v2-activity-log.js")
	context.css_v = portal.asset_version("css/dev-v2-activity-log.css")
	return context
