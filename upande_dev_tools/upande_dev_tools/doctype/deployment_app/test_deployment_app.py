# Copyright (c) 2026, shadrack@upande.com and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase


class IntegrationTestDeploymentApp(IntegrationTestCase):
	def test_named_by_app_name(self) -> None:
		doc = frappe.get_doc(
			{
				"doctype": "Deployment App",
				"app_name": "upande-crm",
				"repository_url": "https://github.com/ghost-mann/upande-crm.git",
			}
		).insert(ignore_permissions=True)
		self.assertEqual(doc.name, "upande-crm")
		self.assertEqual(doc.default_branch, "main")
