# Copyright (c) 2026, shadrack@upande.com and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class DeveloperActivityLog(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		activity_time: DF.Datetime | None
		activity_type: DF.Literal["Backup", "Git Monitor", "Differences", "Hooks", "Error"]
		description: DF.SmallText | None
		performed_by: DF.Link | None
		reference_doctype: DF.Link | None
		reference_name: DF.DynamicLink | None
		source: DF.Data | None
		status: DF.Literal["Success", "Warning", "Error", "Info"]
		title: DF.Data | None
	# end: auto-generated types

	pass
