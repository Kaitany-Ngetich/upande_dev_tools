# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
#
# Deployments v2 (www/deployments-v2.html). Same page access as the current /deployments page.
# The capability flags below only decide which controls are drawn; every write endpoint in
# api/deployments.py re-checks the same roles on its own.

import frappe

from upande_dev_tools import portal
from upande_dev_tools.api.deployments import (
	DEPLOYER_ROLES,
	DEPLOYMENT_APPROVER_ROLES,
	can_change_deployment_state,
)
from upande_dev_tools.dev_v2 import page_context

no_cache = 1


def get_context(context):
	page_context(context, "deployments", "Deployments")
	roles = set(frappe.get_roles())
	context.can_create = bool(roles & DEPLOYER_ROLES)
	context.is_approver = bool(roles & DEPLOYMENT_APPROVER_ROLES)
	context.can_change_state = can_change_deployment_state()
	context.page_v = portal.asset_version("js/dev-v2-deployments.js")
	context.css_v = portal.asset_version("css/dev-v2-deployments.css")
	return context
