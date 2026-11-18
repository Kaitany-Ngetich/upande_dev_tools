# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class DutyType(Document):
	def validate(self):
		self.duty_name = (self.duty_name or "").strip()
		if (self.people_per_slot or 0) < 0:
			frappe.throw(_("People per slot cannot be negative."), frappe.ValidationError)
