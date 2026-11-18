# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class DutyChangeRequest(Document):
	def validate(self):
		# The full rules (who is on which slot, pending duplicates) live in api/duty.py and run when a request is
		# made and again when it is approved; these hold however the document is saved.
		if self.from_user == self.to_user:
			frappe.throw(_("Pick someone else."), frappe.ValidationError)
		if self.request_type == "Swap" and not self.swap_slot:
			frappe.throw(_("A swap needs the slot taken in return."), frappe.ValidationError)
		if self.request_type == "Replace":
			self.swap_slot = None
		if self.slot and not self.duty_type:
			self.duty_type = frappe.db.get_value("Duty Rota Slot", self.slot, "duty_type")
