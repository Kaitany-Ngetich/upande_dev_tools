# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
#
# Code Snapshots v2 (www/code-snapshots-v2.html). Open to the roles that may open /code-snapshots;
# the API endpoints enforce the Dev Team role themselves.

from upande_dev_tools import portal
from upande_dev_tools.dev_v2 import page_context

no_cache = 1


def get_context(context):
	context = page_context(context, "code-snapshots", "Code Snapshots")
	context.page_v = portal.asset_version("js/dev-v2-code-snapshots.js")
	context.css_v = portal.asset_version("css/dev-v2-code-snapshots.css")
	return context
