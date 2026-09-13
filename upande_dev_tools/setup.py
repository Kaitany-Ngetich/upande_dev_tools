from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

TASK_CUSTOM_FIELDS = {
	"Task": [
		{
			"fieldname": "custom_request",
			"label": "Request",
			"fieldtype": "Link",
			"options": "Request",
			"insert_after": "project",
			"read_only": 1,
			"description": "The Request this Task was promoted from, if any.",
		},
		{
			"fieldname": "custom_planned_for",
			"label": "Planned For",
			"fieldtype": "Date",
			"insert_after": "priority",
			"description": "The day a developer has chosen to work on this task.",
		},
	]
}


def create_task_custom_fields() -> None:
	create_custom_fields(TASK_CUSTOM_FIELDS, update=True)
