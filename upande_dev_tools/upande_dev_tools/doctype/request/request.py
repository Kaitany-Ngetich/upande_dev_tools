# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.contacts.doctype.contact.contact import get_contact_name
from frappe.model.document import Document


class Request(Document):
	def before_insert(self) -> None:
		self.raised_by_user = self.raised_by_user or frappe.session.user
		if not self.raised_by_employee:
			self.raised_by_employee = frappe.db.get_value(
				"Employee", {"user_id": self.raised_by_user}, "name"
			)
		if not self.raised_by_contact:
			self.raised_by_contact = get_contact_name(self.raised_by_user)

	def validate(self) -> None:
		if self.is_new() and self.request_type == "Note" and "Dev Team" not in frappe.get_roles():
			frappe.throw(_("Only Dev Team members can raise a Note."))

		if self.workflow_state == "Approved" and not (self.project and self.priority):
			frappe.throw(_("Set Project and Priority before approving a request."))

	def on_update(self) -> None:
		if (
			self.workflow_state == "Scheduled"
			and self.has_value_changed("workflow_state")
			and not self.linked_task
		):
			task = frappe.get_doc(
				{
					"doctype": "Task",
					"subject": self.title,
					"description": self.description,
					"project": self.project,
					"priority": self.priority,
					"custom_request": self.name,
				}
			)
			# Skip Task's recursion check - a query this bench's pypika can't execute, and
			# unnecessary on a freshly created Task anyway.
			task.flags.ignore_recursion_check = True
			task.insert(ignore_permissions=True)
			self.db_set("linked_task", task.name, update_modified=False)
