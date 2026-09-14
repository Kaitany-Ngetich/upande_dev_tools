# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase


class IntegrationTestDeploymentInstance(IntegrationTestCase):
	def test_named_by_instance_name(self) -> None:
		# Synthetic name so it can't collide with a real seeded Deployment Instance.
		instance_name = "Test Deployment Instance Named By Instance Name"
		if frappe.db.exists("Deployment Instance", instance_name):
			frappe.delete_doc("Deployment Instance", instance_name, force=True)
		doc = frappe.get_doc(
			{
				"doctype": "Deployment Instance",
				"instance_name": instance_name,
				"environment_type": "Production",
			}
		).insert(ignore_permissions=True)
		self.assertEqual(doc.name, instance_name)
