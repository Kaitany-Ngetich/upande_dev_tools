# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
#
# Code Editor v2 (www/code-editor-v2.html). Same access rule as the current page
# (Dev Portal Page "code-editor"); the api/code_editor.py endpoints additionally require
# the Dev Team role.

from upande_dev_tools import portal
from upande_dev_tools.dev_v2 import page_context

no_cache = 1


def get_context(context):
	page_context(context, "code-editor", "Code Editor")
	context.page_v = portal.asset_version("js/dev-v2-code-editor.js")
	context.css_v = portal.asset_version("css/dev-v2-code-editor.css")
	return context
