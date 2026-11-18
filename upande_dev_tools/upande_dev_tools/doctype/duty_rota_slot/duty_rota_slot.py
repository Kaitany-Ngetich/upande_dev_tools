# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class DutyRotaSlot(Document):
	def validate(self):
		from upande_dev_tools.api.duty import validate_slot

		validate_slot(self)
