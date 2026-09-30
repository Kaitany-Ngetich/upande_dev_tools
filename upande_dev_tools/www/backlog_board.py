# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import frappe

from upande_dev_tools.api.board import can_create_task_directly, is_board_role
from upande_dev_tools.portal import enforce_page_access

no_cache = 1


def get_context(context):
	enforce_page_access("backlog-board")
	context = frappe._dict(context)
	context.no_cache = 1
	context.page_title = "Backlog Board"
	context.active_route = "backlog-board"
	context.csrf_token = frappe.sessions.get_csrf_token()
	# frappe.ui.form.make_control is not in frappe-web.bundle.js; this page renders
	# Frappe Date controls (see public/js/date-field.js), which need it.
	context.web_include_js = ["controls.bundle.js"]
	context.project = frappe.form_dict.get("project")
	# Drives which fields the "New task" popup shows - see can_create_task_directly.
	context.can_create_task = can_create_task_directly()
	# Drives whether the project picker (get_projects, BOARD_ROLES-only) is even fetched -
	# get_master_data (Priority Level) is public read now, so it needs no flag of its own.
	context.is_board_role = is_board_role()
	return context
