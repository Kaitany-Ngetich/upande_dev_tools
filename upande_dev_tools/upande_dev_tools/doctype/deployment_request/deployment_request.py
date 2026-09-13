# Copyright (c) 2026, shadrack@upande.com and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class DeploymentRequest(Document):
	def before_insert(self) -> None:
		self.requested_by_user = self.requested_by_user or frappe.session.user
		if not self.requested_by_employee:
			self.requested_by_employee = frappe.db.get_value(
				"Employee", {"user_id": self.requested_by_user}, "name"
			)
