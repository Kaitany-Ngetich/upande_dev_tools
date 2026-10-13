# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
#
# Backlog Board v2 (www/backlog-board-v2.html): the full board of Tasks, Issues and Requests.
# Access follows the current page (Dev Portal Page "backlog-board"), via dev_v2.page_context.
# The role flags below are the same ones the current controller hands its page; the endpoints
# in api/board.py re-check them on every write.

import frappe

from upande_dev_tools import portal
from upande_dev_tools.api.board import can_create_task_directly, is_board_role
from upande_dev_tools.dev_v2 import page_context

no_cache = 1

#: Roles that may review anything (reassign, delete any task or request).
MANAGER_ROLES = {"Projects Manager", "System Manager"}


def get_context(context):
	context = page_context(context, "backlog-board", "Backlog Board")
	roles = set(frappe.get_roles())
	context.ph_wide = True
	context.page_v = portal.asset_version("js/dev-v2-backlog-board.js")
	context.css_v = portal.asset_version("css/dev-v2-backlog-board.css")
	# Drives "New task" (a real Task) vs "Add to backlog" (a Request) - see can_create_task_directly.
	context.can_create_task = can_create_task_directly()
	# Drives the project picker and every edit control - see is_board_role.
	context.is_board_role = is_board_role()
	# Drives the delete rules: managers delete anything, other board roles only their own work.
	context.is_manager = bool(MANAGER_ROLES & roles)
	return context
