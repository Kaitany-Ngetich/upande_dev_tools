# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
#
# Duty rota (www/duty-rota.html): who is on duty when, swap / cover requests, and (for project managers) editing
# slots and deciding requests. Page access follows the Dev Portal Page "duty-rota"; every endpoint in api/duty.py
# re-checks roles on its own, so `can_manage` below only decides which controls are drawn.

from upande_dev_tools import portal
from upande_dev_tools.api.duty import is_manager
from upande_dev_tools.dev_v2 import page_context

no_cache = 1


def get_context(context):
	page_context(context, "duty-rota", "Duty Rota")
	context.can_manage = is_manager()
	context.page_v = portal.asset_version("js/dev-v2-duty-rota.js")
	context.css_v = portal.asset_version("css/dev-v2-duty-rota.css")
	return context
