# Copyright (c) 2026, Upande Limited

import frappe
from frappe.tests import IntegrationTestCase


class IntegrationTestRequestsApi(IntegrationTestCase):
	def test_task_has_request_custom_fields(self) -> None:
		meta = frappe.get_meta("Task")
		self.assertTrue(meta.has_field("custom_request"))
		self.assertTrue(meta.has_field("custom_planned_for"))
