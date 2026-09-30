# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import datetime

import frappe
from frappe.model.document import Document
from frappe.utils import get_time, now_datetime


def is_peak_hours(at: datetime.datetime | None = None) -> bool:
	"""Whether `at` (default: right now) falls inside the peak-hours window configured on
	Dev Portal Settings. A window that crosses midnight (e.g. 20:00-06:00) wraps correctly -
	it's "outside [end, start)" rather than "inside [start, end]" in that case."""
	settings = frappe.get_single("Dev Portal Settings")
	if not settings.peak_hours_enabled or not settings.peak_start_time or not settings.peak_end_time:
		return False

	start = get_time(settings.peak_start_time)
	end = get_time(settings.peak_end_time)
	now = get_time((at or now_datetime()).time())

	if start == end:
		return True  # a zero-width window means "always" rather than "never"
	if start < end:
		return start <= now < end
	return now >= start or now < end  # wraps past midnight


class DeploymentRequest(Document):
	def before_insert(self) -> None:
		self.requested_by_user = self.requested_by_user or frappe.session.user
		if not self.requested_by_employee:
			self.requested_by_employee = frappe.db.get_value(
				"Employee", {"user_id": self.requested_by_user}, "name"
			)
		# Flagged once, at the moment of creation - a later edit (or a peak-hours config
		# change) must not retroactively flag or unflag something already in the queue.
		if is_peak_hours():
			self.requires_approval = 1
			self.approval_status = "Pending"

	def validate(self) -> None:
		# The real backstop: api.deployments.update_deployment_status also checks this (for a
		# friendlier error before the workflow engine gets involved), but this doctype is
		# workflow-governed, and Dev Team can drive that workflow straight from the desk form
		# - a path that never goes through that API method at all. Enforcing it here too means
		# a flagged deployment can't start regardless of which door someone comes in through.
		if (
			self.requires_approval
			and self.approval_status != "Approved"
			and self.has_value_changed("workflow_state")
			and self.workflow_state == "In Progress"
		):
			frappe.throw(
				frappe._(
					"This deployment was raised during peak hours and needs Projects Manager "
					"approval before it can start."
				),
				frappe.PermissionError,
			)
