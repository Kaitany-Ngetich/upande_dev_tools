# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
#
# Hooks Explorer v2 (www/hooks-explorer-v2.html).

from upande_dev_tools import portal
from upande_dev_tools.dev_v2 import page_context

no_cache = 1


def get_context(context):
	context = page_context(context, "hooks-explorer", "Hooks Explorer")
	context.page_v = portal.asset_version("js/dev-v2-hooks-explorer.js")
	context.css_v = portal.asset_version("css/dev-v2-hooks-explorer.css")
	return context
