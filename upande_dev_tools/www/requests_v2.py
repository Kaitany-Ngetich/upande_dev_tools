# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
#
# Requests v2 (www/requests-v2.html): raise, track and follow requests. Access follows the
# current /requests-portal page (the NAV maps it); writes go through api/requests.py.

from upande_dev_tools import portal
from upande_dev_tools.dev_v2 import page_context

no_cache = 1


def get_context(context):
	context = page_context(context, "requests", "Requests")
	context.page_v = portal.asset_version("js/dev-v2-requests.js")
	context.css_v = portal.asset_version("css/dev-v2-requests.css")
	return context
