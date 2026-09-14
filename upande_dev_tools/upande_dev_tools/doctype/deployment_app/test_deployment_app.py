# Copyright (c) 2026, shadrack@upande.com and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase


class IntegrationTestDeploymentApp(IntegrationTestCase):
	def test_named_by_app_name(self) -> None:
		# A synthetic, obviously-fake name - real app names (e.g. "upande-crm") are now taken by
		# genuine Deployment App records seeded from this bench's installed apps and the
		# imported deployment history, so a real-looking name here would collide.
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
