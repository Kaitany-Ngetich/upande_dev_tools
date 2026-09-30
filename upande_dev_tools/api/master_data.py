# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import frappe
from frappe import _

MASTER_DATA_CRUD_ROLES = {"Dev Team", "Projects Manager", "System Manager"}

# Never accept a raw doctype name from the caller - only these keys are reachable here.
MASTER_DATA_DOCTYPES: dict[str, tuple[str, str]] = {
	"request_type": ("Request Type", "type_name"),
	"priority_level": ("Priority Level", "level_name"),
	"product_area": ("Product Area", "area_name"),
	"tag": ("Work Tag", "tag_name"),
}


def has_master_data_access(user: str | None = None) -> bool:
	"""All three - Dev Team, Projects Manager AND System Manager together, not any one or
	two of them - are trusted with real CRUD here. Master Data drives the vocabulary every
	Request/Task on the board gets classified by, so changing or removing an entry is a
	wider-reaching action than most things this app gates to a single role or an OR of two."""
	return MASTER_DATA_CRUD_ROLES <= set(frappe.get_roles(user))


def _require_access() -> None:
	if not has_master_data_access():
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
		{"key": "tag", "label": "Tags", "has_sort_order": False},
	]


@frappe.whitelist()
def get_master_data(key: str) -> list[dict]:
	"""Read-only, and deliberately not behind _require_access: Priority Level and Product
	Area are the two master-data kinds with no dedicated public-read wrapper of their own
	(Request Type goes out via a plain frappe.client.get_list the app itself opened to
	"All"; Work Tag has get_work_tags) - anything on this dashboard that offers priority
	or product-area choices, filters or groupings needs the live list too, the same as
	those two already do, or it's back to hardcoding a copy that silently drifts from
	whatever Master Data actually says. Adding, renaming, disabling or deleting an entry
	still goes through add/update/set_disabled/delete_master_data below, all role-gated."""
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


@frappe.whitelist()
def update_master_data(key: str, name: str, value: str, sort_order: int = 0) -> dict:
	"""Renaming is a real frappe.rename_doc, not a relabel - these doctypes autoname by
	their own value field, so the value IS the document name, and every Request/Task
	already pointing at the old one is repointed at the new one automatically as part of
	the rename, the same as renaming any other linked document in Frappe."""
	_require_access()
	doctype, _name_field = _resolve(key)
	if not frappe.db.exists(doctype, name):
		frappe.throw(_("Not found."), frappe.DoesNotExistError)

	value = (value or "").strip()
	if not value:
		frappe.throw(_("A value is required."), frappe.ValidationError)

	if value != name:
		if frappe.db.exists(doctype, value):
			frappe.throw(_("{0} already exists.").format(value), frappe.DuplicateEntryError)
		# All four of these doctypes ship allow_rename=0 - that's to stop a casual rename
		# from the raw doctype list, not to block this deliberate one, so force=True.
		# frappe.rename_doc (unlike get_doc().insert/delete_doc) has no ignore_permissions
		# of its own - every CRUD role here already carries real write permission on all
		# four doctypes (see each one's own permissions block), so none is needed.
		frappe.rename_doc(doctype, name, value, force=True)
	if doctype == "Priority Level":
		frappe.db.set_value(doctype, value, "sort_order", sort_order)
	return {"name": value}


@frappe.whitelist()
def delete_master_data(key: str, name: str) -> None:
	"""A real delete, not another disable - for the (hopefully rare) entry that was never
	really used and shouldn't linger even hidden. frappe.delete_doc still refuses this on
	its own if anything is actually linked to it, which is exactly the case disable exists
	for instead - this re-throws that as the same friendly guidance the rest of this page
	already gives, not a raw LinkExistsError."""
	_require_access()
	doctype, _name_field = _resolve(key)
	if not frappe.db.exists(doctype, name):
		frappe.throw(_("Not found."), frappe.DoesNotExistError)
	try:
		frappe.delete_doc(doctype, name, ignore_permissions=True)
	except frappe.LinkExistsError:
		frappe.throw(
			_("{0} is still in use elsewhere - disable it instead of deleting it.").format(name),
			frappe.LinkExistsError,
		)
