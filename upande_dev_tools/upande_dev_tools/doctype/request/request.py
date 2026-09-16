# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from upande_dev_tools.api.board import _set_doc_tags, normalize_priority


class Request(Document):
	def before_insert(self) -> None:
		# owner is already the submitter by the time before_insert runs (Document.insert()
		# sets it before running this hook) - no separate raised_by_user field needed.
		# Everyone raising or receiving a request here is staff - "raised_by_employee" is the
		# one "who is this for" field, defaulting to the submitter's own Employee record but
		# explicitly overridable (create_request's raised_by_employee param) when a PM/dev
		# raises something on a colleague's behalf.
		if not self.raised_by_employee:
			self.raised_by_employee = frappe.db.get_value("Employee", {"user_id": self.owner}, "name")

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
					# Task.priority is a hardcoded Select, not linked to Priority Level (this
					# app's own, Master Data page-extensible priority list) - clamp rather than
					# assume the two always agree.
					"priority": normalize_priority("Task", "priority", self.priority),
					"custom_request": self.name,
					"custom_module": self.product_area,
				}
			)
			# Skip Task's recursion check - a query this bench's pypika can't execute, and
			# unnecessary on a freshly created Task anyway.
			task.flags.ignore_recursion_check = True
			task.insert(ignore_permissions=True)
			self.db_set("linked_task", task.name, update_modified=False)

			# The tag is the one classification the board can filter on for either doctype -
			# carrying it forward is what makes a promoted Request's Task still findable by
			# the same tag on the board afterwards.
			tags = frappe.get_all(
				"Tag Link", filters={"document_type": "Request", "document_name": self.name}, pluck="tag"
			)
			if tags:
				_set_doc_tags("Task", task.name, tags)
