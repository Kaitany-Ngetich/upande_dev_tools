# Copyright (c) 2026, shadrack@upande.com and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase


class IntegrationTestDeploymentInstance(IntegrationTestCase):
	def test_named_by_instance_name(self) -> None:
		doc = frappe.get_doc(
			{
				"doctype": "Deployment Instance",
				"instance_name": "Kaitet v16 Production",
				"environment_type": "Production",
			}
		).insert(ignore_permissions=True)
		self.assertEqual(doc.name, "Kaitet v16 Production")
