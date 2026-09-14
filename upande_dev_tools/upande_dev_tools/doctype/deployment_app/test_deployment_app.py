# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase


class IntegrationTestDeploymentApp(IntegrationTestCase):
	def test_named_by_app_name(self) -> None:
		# Obviously-fake name so it can't collide with a real seeded Deployment App.
		app_name = "test-deployment-app-named-by-app-name"
		if frappe.db.exists("Deployment App", app_name):
			frappe.delete_doc("Deployment App", app_name, force=True)
		doc = frappe.get_doc(
			{
				"doctype": "Deployment App",
				"app_name": app_name,
				"repository_url": "https://github.com/example/test-deployment-app.git",
			}
		).insert(ignore_permissions=True)
		self.assertEqual(doc.name, app_name)
		self.assertEqual(doc.default_branch, "main")
