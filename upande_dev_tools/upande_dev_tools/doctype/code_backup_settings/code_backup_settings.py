# Copyright (c) 2026, shadrack@upande.com and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class CodeBackupSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		back_up_storage_mode: DF.Literal["Database", "File", "Both"]
		backup_intervals_hours: DF.Int
		enabled: DF.Check
		include_client_scripts: DF.Check
		include_doctypes: DF.Check
		include_server_scripts: DF.Check
		last_back_up_time: DF.Datetime | None
		retention_days: DF.Int
	# end: auto-generated types

	pass
