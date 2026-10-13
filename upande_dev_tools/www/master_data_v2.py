# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
#
# Master Data v2 (www/master-data-v2.html): manage the four master lists and see their usage.

from upande_dev_tools import portal
from upande_dev_tools.dev_v2 import page_context

no_cache = 1


def get_context(context):
	context = page_context(context, "master-data", "Master Data")
	context.page_v = portal.asset_version("js/dev-v2-master-data.js")
	context.page_css_v = portal.asset_version("css/dev-v2-master-data.css")
	return context
