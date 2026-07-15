# Copyright (c) 2026, Upande Limited

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

import frappe
from frappe import _
from frappe.utils import cint


@frappe.whitelist()
def get_exportable_apps() -> list[str]:
    """Return installed applications that own at least one Module Def."""
    _validate_access(require_developer_mode=False)

    installed_apps = frappe.get_installed_apps()

    if not installed_apps:
        return []

    module_apps = frappe.get_all(
        "Module Def",
        filters={"app_name": ["in", installed_apps]},
        pluck="app_name",
    )

    return sorted(
        {
            app_name
            for app_name in module_apps
            if app_name and app_name in installed_apps
        }
    )


@frappe.whitelist()
def get_custom_field_options(
    doctype: str,
    module: str,
    txt: str = "",
) -> list[dict[str, str]]:
    """
    Return Custom Fields belonging to the selected DocType and module.
    """
    _validate_access(require_developer_mode=False)

    if not doctype or not module:
        return []

    _validate_doctype(doctype)
    _validate_module(module)

    rows = frappe.get_all(
        "Custom Field",
        filters={
            "dt": doctype,
            "module": module,
        },
        fields=[
            "name",
            "label",
            "fieldname",
            "fieldtype",
            "idx",
        ],
        order_by="idx asc, name asc",
        limit_page_length=500,
    )

    search_text = (txt or "").strip().lower()

    if search_text:
        rows = [
            row
            for row in rows
            if search_text in str(row.get("name") or "").lower()
            or search_text in str(row.get("label") or "").lower()
            or search_text in str(row.get("fieldname") or "").lower()
            or search_text in str(row.get("fieldtype") or "").lower()
        ]

    return [
        {
            "value": row.name,
            "description": _get_field_description(row),
        }
        for row in rows
    ]


@frappe.whitelist()
def export_selected_customizations(
    app: str,
    module: str,
    doctype: str,
    custom_fields: list[str] | str,
    sync_on_migrate: int | str = 1,
    with_permissions: int | str = 0,
) -> dict[str, Any]:
    """
    Create a new customization JSON file or merge selected fields into
    an existing file without deleting unrelated customizations.
    """
    _validate_access(require_developer_mode=True)

    app = (app or "").strip()
    module = (module or "").strip()
    doctype = (doctype or "").strip()

    if not app:
        frappe.throw(_("App is required."))

    if not module:
        frappe.throw(_("Module is required."))

    if not doctype:
        frappe.throw(_("DocType is required."))

    _validate_doctype(doctype)
    module_app = _validate_module(module)

    if module_app != app:
        frappe.throw(
            _("Module {0} belongs to app {1}, not {2}.").format(
                frappe.bold(module),
                frappe.bold(module_app),
                frappe.bold(app),
            )
        )

    selected_names = _parse_selected_fields(custom_fields)

    if not selected_names:
        frappe.throw(
            _("Select at least one Custom Field to export.")
        )

    custom_field_rows = frappe.get_all(
        "Custom Field",
        filters={
            "name": ["in", selected_names],
            "dt": doctype,
            "module": module,
        },
        fields="*",
        order_by="idx asc, name asc",
    )

    rows_by_name = {
        row.name: row
        for row in custom_field_rows
    }

    invalid_names = [
        name
        for name in selected_names
        if name not in rows_by_name
    ]

    if invalid_names:
        frappe.throw(
            _(
                "Some selected Custom Fields do not belong to "
                "DocType {0} and module {1}: {2}"
            ).format(
                frappe.bold(doctype),
                frappe.bold(module),
                ", ".join(invalid_names),
            )
        )

    # Preserve the order selected by the user.
    selected_custom_fields = [
        dict(rows_by_name[name])
        for name in selected_names
    ]

    selected_fieldnames = [
        row.get("fieldname")
        for row in selected_custom_fields
        if row.get("fieldname")
    ]

    property_setters: list[dict[str, Any]] = []

    if selected_fieldnames:
        property_setters = [
            dict(row)
            for row in frappe.get_all(
                "Property Setter",
                filters={
                    "doc_type": doctype,
                    "module": module,
                    "field_name": ["in", selected_fieldnames],
                },
                fields="*",
                order_by="name",
            )
        ]

    custom_permissions: list[dict[str, Any]] = []

    if cint(with_permissions):
        custom_permissions = [
            dict(row)
            for row in frappe.get_all(
                "Custom DocPerm",
                filters={"parent": doctype},
                fields="*",
                order_by="name",
            )
        ]

    incoming_data: dict[str, Any] = {
        "custom_fields": selected_custom_fields,
        "property_setters": property_setters,
        "custom_perms": custom_permissions,
        "links": [],
        "doctype": doctype,
        "sync_on_migrate": cint(sync_on_migrate),
    }

    folder_path = (
        Path(frappe.get_module_path(module))
        / "custom"
    )

    folder_path.mkdir(
        parents=True,
        exist_ok=True,
    )

    file_path = (
        folder_path
        / f"{frappe.scrub(doctype)}.json"
    )

    existing_data, file_existed = (
        _load_existing_customization_file(
            file_path=file_path,
            doctype=doctype,
            sync_on_migrate=cint(sync_on_migrate),
        )
    )

    merged_data = _merge_customization_data(
        existing_data=existing_data,
        incoming_data=incoming_data,
    )

    _write_customization_file(
        file_path=file_path,
        data=merged_data,
    )

    return {
        "app": app,
        "module": module,
        "doctype": doctype,
        "path": str(file_path),
        "file_action": (
            "updated"
            if file_existed
            else "created"
        ),
        "custom_field_count": len(
            selected_custom_fields
        ),
        "property_setter_count": len(
            property_setters
        ),
        "custom_permission_count": len(
            custom_permissions
        ),
        "total_custom_fields": len(
            merged_data["custom_fields"]
        ),
        "total_property_setters": len(
            merged_data["property_setters"]
        ),
        "total_custom_permissions": len(
            merged_data["custom_perms"]
        ),
    }


def _load_existing_customization_file(
    *,
    file_path: Path,
    doctype: str,
    sync_on_migrate: int,
) -> tuple[dict[str, Any], bool]:
    """
    Load the existing JSON file.

    When the file does not exist, return an empty customization
    structure so a new file can be created.
    """
    default_data: dict[str, Any] = {
        "custom_fields": [],
        "property_setters": [],
        "custom_perms": [],
        "links": [],
        "doctype": doctype,
        "sync_on_migrate": cint(
            sync_on_migrate
        ),
    }

    if not file_path.exists():
        return default_data, False

    try:
        existing_data = json.loads(
            file_path.read_text(
                encoding="utf-8"
            )
        )

    except json.JSONDecodeError as exc:
        frappe.throw(
            _(
                "Existing customization file contains "
                "invalid JSON: {0}. Error: {1}"
            ).format(
                file_path,
                exc,
            )
        )

    except OSError as exc:
        frappe.throw(
            _(
                "Could not read existing customization "
                "file {0}: {1}"
            ).format(
                file_path,
                exc,
            )
        )

    if not isinstance(existing_data, dict):
        frappe.throw(
            _(
                "Existing customization file must "
                "contain a JSON object: {0}"
            ).format(file_path)
        )

    existing_doctype = existing_data.get(
        "doctype"
    )

    if (
        existing_doctype
        and existing_doctype != doctype
    ):
        frappe.throw(
            _(
                "Existing file belongs to DocType "
                "{0}, not {1}."
            ).format(
                frappe.bold(existing_doctype),
                frappe.bold(doctype),
            )
        )

    for key in (
        "custom_fields",
        "property_setters",
        "custom_perms",
        "links",
    ):
        if not isinstance(
            existing_data.get(key),
            list,
        ):
            existing_data[key] = []

    existing_data["doctype"] = doctype
    existing_data["sync_on_migrate"] = cint(
        sync_on_migrate
    )

    return existing_data, True


def _merge_customization_data(
    *,
    existing_data: dict[str, Any],
    incoming_data: dict[str, Any],
) -> dict[str, Any]:
    """
    Add or update selected records while preserving unrelated
    records already present in the JSON file.
    """
    merged_data = dict(existing_data)

    merged_data["doctype"] = incoming_data[
        "doctype"
    ]

    merged_data["sync_on_migrate"] = (
        incoming_data["sync_on_migrate"]
    )

    merged_data["custom_fields"] = (
        _upsert_records(
            existing_records=existing_data.get(
                "custom_fields",
                [],
            ),
            incoming_records=incoming_data.get(
                "custom_fields",
                [],
            ),
            key_function=_custom_field_key,
        )
    )

    merged_data["property_setters"] = (
        _upsert_records(
            existing_records=existing_data.get(
                "property_setters",
                [],
            ),
            incoming_records=incoming_data.get(
                "property_setters",
                [],
            ),
            key_function=_property_setter_key,
        )
    )

    # When permissions are selected, add or update them.
    # When permissions are not selected, preserve the existing list.
    if incoming_data.get("custom_perms"):
        merged_data["custom_perms"] = (
            _upsert_records(
                existing_records=existing_data.get(
                    "custom_perms",
                    [],
                ),
                incoming_records=incoming_data[
                    "custom_perms"
                ],
                key_function=_custom_permission_key,
            )
        )
    else:
        merged_data["custom_perms"] = (
            existing_data.get(
                "custom_perms",
                [],
            )
        )

    # Selective Custom Field export does not modify links.
    merged_data["links"] = existing_data.get(
        "links",
        [],
    )

    return merged_data


def _upsert_records(
    *,
    existing_records: list[dict[str, Any]],
    incoming_records: list[dict[str, Any]],
    key_function: Callable[
        [dict[str, Any]],
        tuple[Any, ...] | None,
    ],
) -> list[dict[str, Any]]:
    """
    Replace matching records and append new records.

    Existing unrelated records and their order are preserved.
    """
    result = [
        dict(record)
        for record in (
            existing_records or []
        )
        if isinstance(record, dict)
    ]

    record_index: dict[
        tuple[Any, ...],
        int,
    ] = {}

    for index, record in enumerate(result):
        record_key = key_function(record)

        if record_key:
            record_index[record_key] = index

    for record in incoming_records or []:
        normalized_record = dict(record)
        record_key = key_function(
            normalized_record
        )

        if not record_key:
            continue

        if record_key in record_index:
            existing_index = record_index[
                record_key
            ]

            result[existing_index] = (
                normalized_record
            )
        else:
            record_index[record_key] = len(
                result
            )

            result.append(normalized_record)

    return result


def _custom_field_key(
    record: dict[str, Any],
) -> tuple[Any, ...] | None:
    doctype = record.get("dt")
    fieldname = record.get("fieldname")

    if not doctype or not fieldname:
        return None

    return (
        doctype,
        fieldname,
    )


def _property_setter_key(
    record: dict[str, Any],
) -> tuple[Any, ...] | None:
    doctype = record.get("doc_type")
    property_name = record.get("property")

    if not doctype or not property_name:
        return None

    return (
        doctype,
        record.get("doctype_or_field") or "",
        record.get("field_name") or "",
        record.get("row_name") or "",
        property_name,
    )


def _custom_permission_key(
    record: dict[str, Any],
) -> tuple[Any, ...] | None:
    parent = record.get("parent")
    role = record.get("role")

    if not parent or not role:
        return None

    return (
        parent,
        role,
        cint(record.get("permlevel")),
        cint(record.get("if_owner")),
    )


def _write_customization_file(
    *,
    file_path: Path,
    data: dict[str, Any],
) -> None:
    """
    Write the merged file atomically.

    The existing file is replaced only after the complete merged
    JSON has been written successfully.
    """
    file_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = file_path.with_suffix(
        ".json.tmp"
    )

    try:
        temporary_path.write_text(
            f"{frappe.as_json(data)}\n",
            encoding="utf-8",
        )

        os.replace(
            temporary_path,
            file_path,
        )

    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _parse_selected_fields(
    custom_fields: list[str] | str,
) -> list[str]:
    if isinstance(custom_fields, str):
        try:
            custom_fields = frappe.parse_json(
                custom_fields
            )

        except Exception:
            custom_fields = [
                value.strip()
                for value in custom_fields.split(",")
                if value.strip()
            ]

    if not isinstance(
        custom_fields,
        (list, tuple),
    ):
        frappe.throw(
            _(
                "Custom Fields must be supplied "
                "as a list."
            )
        )

    unique_names: list[str] = []
    seen: set[str] = set()

    for value in custom_fields:
        # Support MultiSelectList values supplied as objects.
        if isinstance(value, dict):
            value = (
                value.get("value")
                or value.get("name")
            )

        name = str(value or "").strip()

        if not name or name in seen:
            continue

        seen.add(name)
        unique_names.append(name)

    return unique_names


def _validate_doctype(
    doctype: str,
) -> None:
    if not frappe.db.exists(
        "DocType",
        doctype,
    ):
        frappe.throw(
            _(
                "DocType {0} does not exist."
            ).format(
                frappe.bold(doctype)
            )
        )


def _validate_module(
    module: str,
) -> str:
    app_name = frappe.db.get_value(
        "Module Def",
        module,
        "app_name",
    )

    if not app_name:
        frappe.throw(
            _(
                "Module {0} does not exist "
                "or has no owning app."
            ).format(
                frappe.bold(module)
            )
        )

    if app_name not in frappe.get_installed_apps():
        frappe.throw(
            _(
                "The app owning module {0} "
                "is not installed."
            ).format(
                frappe.bold(module)
            )
        )

    return app_name


def _validate_access(
    require_developer_mode: bool,
) -> None:
    frappe.only_for("System Manager")

    if (
        require_developer_mode
        and not frappe.conf.developer_mode
    ):
        frappe.throw(
            _(
                "Customizations can only be "
                "exported in developer mode."
            )
        )


def _get_field_description(
    row: frappe._dict,
) -> str:
    label = (
        row.get("label")
        or row.get("fieldname")
        or row.get("name")
    )

    fieldname = row.get("fieldname") or ""
    fieldtype = row.get("fieldtype") or ""

    return (
        f"{label} — {fieldname} — {fieldtype}"
    )
