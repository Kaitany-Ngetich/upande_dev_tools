# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import frappe
from frappe import _

MASTER_DATA_ROLES = {"Dev Team", "Projects Manager"}

# Never accept a raw doctype name from the caller - only these keys are reachable here.
MASTER_DATA_DOCTYPES: dict[str, tuple[str, str]] = {
	"request_type": ("Request Type", "type_name"),
	"priority_level": ("Priority Level", "level_name"),
	"product_area": ("Product Area", "area_name"),
	"request_tag": ("Request Tag", "tag_name"),
}


def _require_access() -> None:
	if not MASTER_DATA_ROLES & set(frappe.get_roles()):
		frappe.throw(_("Not permitted."), frappe.PermissionError)


def _resolve(key: str) -> tuple[str, str]:
	if key not in MASTER_DATA_DOCTYPES:
		frappe.throw(_("Unknown master data type."), frappe.ValidationError)
	return MASTER_DATA_DOCTYPES[key]


@frappe.whitelist()
def get_master_data_kinds() -> list[dict]:
	"""What this page can manage - drives the tab list client-side."""
	_require_access()
	return [
		{"key": "request_type", "label": "Request Types", "has_sort_order": False},
		{"key": "priority_level", "label": "Priority Levels", "has_sort_order": True},
		{"key": "product_area", "label": "Product Areas", "has_sort_order": False},
		{"key": "request_tag", "label": "Request Tags", "has_sort_order": False},
	]


@frappe.whitelist()
def get_master_data(key: str) -> list[dict]:
	_require_access()
	doctype, name_field = _resolve(key)
	fields = ["name", "disabled"]
	order_by = f"{name_field} asc"
	if doctype == "Priority Level":
		fields.append("sort_order")
		order_by = "sort_order asc"
	return frappe.get_all(doctype, fields=fields, order_by=order_by, ignore_permissions=True)


@frappe.whitelist()
def add_master_data(key: str, value: str, sort_order: int = 0) -> dict:
	_require_access()
	doctype, name_field = _resolve(key)

	value = (value or "").strip()
	if not value:
		frappe.throw(_("A value is required."), frappe.ValidationError)
	if frappe.db.exists(doctype, value):
		frappe.throw(_("{0} already exists.").format(value), frappe.DuplicateEntryError)

	doc_fields: dict = {"doctype": doctype, name_field: value}
	if doctype == "Priority Level":
		doc_fields["sort_order"] = sort_order
	doc = frappe.get_doc(doc_fields)
	doc.insert(ignore_permissions=True)
	return {"name": doc.name}


@frappe.whitelist()
def set_master_data_disabled(key: str, name: str, disabled: bool) -> None:
	_require_access()
	doctype, _name_field = _resolve(key)
	if not frappe.db.exists(doctype, name):
		frappe.throw(_("Not found."), frappe.DoesNotExistError)
	frappe.db.set_value(doctype, name, "disabled", 1 if disabled else 0)
