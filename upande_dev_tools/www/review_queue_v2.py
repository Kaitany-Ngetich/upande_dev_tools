# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
#
# Review Queue v2 (www/review-queue-v2.html): the full replacement of /review-queue. Reads come
# from api.v2.review_queue; every decision calls the same api.requests endpoints as the current page.

from upande_dev_tools import portal
from upande_dev_tools.dev_v2 import page_context

no_cache = 1


def get_context(context):
	page_context(context, "review-queue", "Review Queue")
	context.page_v = portal.asset_version("js/dev-v2-review-queue.js")
	context.css_v = portal.asset_version("css/dev-v2-review-queue.css")
	return context
