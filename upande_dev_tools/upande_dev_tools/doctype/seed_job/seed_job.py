# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.model.document import Document


class SeedJob(Document):
	def validate(self):
		if self.anonymise_fields:
			try:
				parsed = json.loads(self.anonymise_fields)
			except (TypeError, ValueError) as e:
				frappe.throw(_("Anonymise Fields is not valid JSON: {0}").format(e))
			if not isinstance(parsed, dict):
				frappe.throw(_("Anonymise Fields must be a JSON object of {{fieldname: replacement}}."))

		for row in self.doctypes:
			for field, default in (("filters", "[]"), ("fields", '["*"]')):
				value = row.get(field) or default
				try:
					json.loads(value)
				except (TypeError, ValueError) as e:
					frappe.throw(
						_("Row #{0} ({1}): {2} is not valid JSON: {3}").format(
							row.idx, row.doctype_name, field, e
						)
					)

	def on_trash(self):
		frappe.db.delete("Seed Job Log", {"seed_job": self.name})
