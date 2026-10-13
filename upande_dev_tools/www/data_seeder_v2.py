# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
#
# Data Seeder v2 (www/data-seeder-v2.html). Opens for the roles on the Dev Portal Page
# `dev-data-seeder` (System Manager by default); api/seeder.py enforces the same rule on every endpoint.

from upande_dev_tools import portal
from upande_dev_tools.dev_v2 import page_context

no_cache = 1


def get_context(context):
	context = page_context(context, "data-seeder", "Data Seeder", access_route="dev-data-seeder")
	context.page_v = portal.asset_version("js/dev-v2-data-seeder.js")
	context.css_v = portal.asset_version("css/dev-v2-data-seeder.css")
	return context
