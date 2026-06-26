# Copyright (c) 2026, shadrack@upande.com and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class CodeBackupSnapshot(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		app: DF.Data | None
		backed_up_by: DF.Data | None
		changed_since_last_backup: DF.Check
		content_hash: DF.Data | None
		content_json: DF.Code | None
		document_name: DF.Data | None
		module: DF.Data | None
		name: DF.Int | None
		script_code: DF.Code | None
		snapshot_time: DF.Datetime | None
		source_type: DF.Literal["DocType", "Server Script", "Client Script"]
		version_label: DF.Data | None
	# end: auto-generated types

	pass
