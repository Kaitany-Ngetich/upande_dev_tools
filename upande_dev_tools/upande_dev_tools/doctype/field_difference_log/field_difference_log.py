# Copyright (c) 2026, shadrack@upande.com and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class FieldDifferenceLog(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		comparison_time: DF.Datetime | None
		doctype_name: DF.Link | None
		field_name: DF.Data | None
		issue_type: DF.Literal[None]
		live_value: DF.SmallText | None
		local_value: DF.SmallText | None
		source_snapshot: DF.Link | None
		status: DF.Literal["New", "Reviewed", "Ignored"]
	# end: auto-generated types

	pass
