# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
#
# Dev Tools Overview v2 (www/dev-tools-v2.html).
#
# ACCESS: the overview is the landing page, so it is open to every signed-in user (the
# same rule as /dev-tools, which sends anyone signed in on to their own home page).
# NAV's default for this page is the Dev Dashboard route (Dev Team only), which would
# turn Projects Managers and requesters away from their landing page, so the "Requests"
# portal page (open to All) is the access rule here. What each person then SEES is
# decided per card and per tile by api/v2/overview.py, from their roles.

from upande_dev_tools import portal
from upande_dev_tools.dev_v2 import page_context

no_cache = 1


def get_context(context):
	context = page_context(context, "dev-tools", "Dev Tools Overview", access_route="requests-portal")
	context.page_v = portal.asset_version("js/dev-v2-dev-tools.js")
	context.css_v = portal.asset_version("css/dev-v2-dev-tools.css")
	return context
