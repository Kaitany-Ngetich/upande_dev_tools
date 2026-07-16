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


TARGET_SEPARATOR = "|||"


def _encode_target(doctype: str, fieldname: str) -> str:
    return f"{doctype}{TARGET_SEPARATOR}{fieldname}"


def _decode_target(token: str) -> tuple[str, str]:
    if TARGET_SEPARATOR not in (token or ""):
        frappe.throw(_("Invalid customization target: {0}").format(token))
    doctype, fieldname = token.split(TARGET_SEPARATOR, 1)
    return doctype.strip(), fieldname.strip()


@frappe.whitelist()
def get_customization_targets(doctype: str) -> list[dict[str, str]]:
    """Return selectable customization targets for a DocType and its child tables.

    A target is any field that carries a Custom Field and/or a field-level
    Property Setter, on the parent DocType or any of its child tables.
    """
    _validate_access(require_developer_mode=False)

    doctype = (doctype or "").strip()
    if not doctype:
        return []

    _validate_doctype(doctype)

    doctypes = [doctype]
    for df in frappe.get_meta(doctype).get_table_fields():
        if df.options and df.options not in doctypes:
            doctypes.append(df.options)

    targets: list[dict[str, str]] = []
    for dt in doctypes:
        targets.extend(_collect_targets_for_doctype(dt))
    return targets


def _collect_targets_for_doctype(doctype: str) -> list[dict[str, str]]:
    custom_fields = frappe.get_all(
        "Custom Field",
        filters={"dt": doctype},
        fields=["fieldname", "label", "idx"],
        order_by="idx asc, fieldname asc",
    )
    cf_by_fieldname = {row.fieldname: row for row in custom_fields}

    ps_fieldnames = frappe.get_all(
        "Property Setter",
        filters={"doc_type": doctype, "doctype_or_field": "DocField"},
        pluck="field_name",
    )
    ps_count: dict[str, int] = {}
    for fieldname in ps_fieldnames:
        if fieldname:
            ps_count[fieldname] = ps_count.get(fieldname, 0) + 1

    ordered_fieldnames: list[str] = list(cf_by_fieldname.keys())
    for fieldname in sorted(ps_count):
        if fieldname not in cf_by_fieldname:
            ordered_fieldnames.append(fieldname)

    results: list[dict[str, str]] = []
    for fieldname in ordered_fieldnames:
        cf = cf_by_fieldname.get(fieldname)
        count = ps_count.get(fieldname, 0)

        if cf and count:
            kind = _("Custom Field + {0} property setter(s)").format(count)
        elif cf:
            kind = _("Custom Field")
        else:
            kind = _("{0} property setter(s)").format(count)

        label = (cf.label if cf else None) or fieldname
        results.append(
            {
                "value": _encode_target(doctype, fieldname),
                "description": f"{doctype} · {label} — {fieldname} — {kind}",
            }
        )
    return results


_CUSTOMIZATION_LIST_KEYS = (
    "custom_fields",
    "property_setters",
    "links",
    "custom_perms",
)


def _sort_customization_lists(data: dict[str, Any]) -> dict[str, Any]:
    for key in _CUSTOMIZATION_LIST_KEYS:
        rows = data.get(key) or []
        data[key] = sorted(
            rows,
            key=lambda row: str(row.get("name") or ""),
        )
    return data


def _build_doctype_customization(
    doctype: str,
    fieldnames,
    include_links: bool,
    include_doctype_property_setters: bool,
    with_permissions: bool,
    sync_on_migrate: int,
) -> dict[str, Any]:
    """Build the native-shaped customization dict for one DocType.

    Field-level records are limited to ``fieldnames``. Doctype-level property
    setters, links, and custom permissions are added only when their
    corresponding option is enabled.
    """
    fieldnames = list(dict.fromkeys(fieldnames or []))

    custom_fields: list[dict[str, Any]] = []
    property_setters: list[dict[str, Any]] = []

    if fieldnames:
        custom_fields = [
            dict(row)
            for row in frappe.get_all(
                "Custom Field",
                filters={"dt": doctype, "fieldname": ["in", fieldnames]},
                fields="*",
                order_by="name",
            )
        ]
        property_setters = [
            dict(row)
            for row in frappe.get_all(
                "Property Setter",
                filters={
                    "doc_type": doctype,
                    "doctype_or_field": "DocField",
                    "field_name": ["in", fieldnames],
                },
                fields="*",
                order_by="name",
            )
        ]

    if include_doctype_property_setters:
        property_setters += [
            dict(row)
            for row in frappe.get_all(
                "Property Setter",
                filters={"doc_type": doctype, "doctype_or_field": "DocType"},
                fields="*",
                order_by="name",
            )
        ]

    links: list[dict[str, Any]] = []
    if include_links:
        links = [
            dict(row)
            for row in frappe.get_all(
                "DocType Link",
                filters={"parent": doctype},
                fields="*",
                order_by="name",
            )
        ]

    custom_perms: list[dict[str, Any]] = []
    if with_permissions:
        custom_perms = [
            dict(row)
            for row in frappe.get_all(
                "Custom DocPerm",
                filters={"parent": doctype},
                fields="*",
                order_by="name",
            )
        ]

    return {
        "custom_fields": custom_fields,
        "property_setters": property_setters,
        "custom_perms": custom_perms,
        "links": links,
        "doctype": doctype,
        "sync_on_migrate": cint(sync_on_migrate),
    }


def _reconcile_doctype_customization(
    doctype: str,
    fieldnames,
    existing_data: dict[str, Any],
    include_links: bool,
    include_doctype_property_setters: bool,
    with_permissions: bool,
    sync_on_migrate: int,
) -> dict[str, Any]:
    """Reconcile a DocType file to exactly the selected fieldnames.

    Selected fields are written from the database (or preserved from the file
    when absent from the database). Deselected fields that are known to the
    database are removed. Fields present in the file but no longer in the
    database (orphans) are left untouched, since they are not shown in the
    export selection. DocType-level property setters, links, and permissions
    are refreshed when their option is enabled, otherwise preserved.
    """
    selected = list(dict.fromkeys(fieldnames or []))
    selected_set = set(selected)

    existing_cf = [
        row for row in (existing_data.get("custom_fields") or []) if isinstance(row, dict)
    ]
    existing_ps = [
        row for row in (existing_data.get("property_setters") or []) if isinstance(row, dict)
    ]

    # The set of fieldnames this DocType knows about in the database.
    db_known = {
        fn for fn in frappe.get_all("Custom Field", filters={"dt": doctype}, pluck="fieldname") if fn
    }
    db_known |= {
        fn
        for fn in frappe.get_all(
            "Property Setter",
            filters={"doc_type": doctype, "doctype_or_field": "DocField"},
            pluck="field_name",
        )
        if fn
    }

    db_cf_by_fn = {}
    db_field_ps = []
    if selected:
        db_cf_by_fn = {
            row.fieldname: dict(row)
            for row in frappe.get_all(
                "Custom Field",
                filters={"dt": doctype, "fieldname": ["in", selected]},
                fields="*",
                order_by="name",
            )
        }
        db_field_ps = [
            dict(row)
            for row in frappe.get_all(
                "Property Setter",
                filters={
                    "doc_type": doctype,
                    "doctype_or_field": "DocField",
                    "field_name": ["in", selected],
                },
                fields="*",
                order_by="name",
            )
        ]
    db_ps_fns = {ps.get("field_name") for ps in db_field_ps}
    existing_cf_by_fn = {row.get("fieldname"): row for row in existing_cf if row.get("fieldname")}

    # Custom fields: selected (DB-preferred, orphan-kept) + non-selected orphans.
    custom_fields = []
    for fn in selected:
        if fn in db_cf_by_fn:
            custom_fields.append(db_cf_by_fn[fn])
        elif fn in existing_cf_by_fn:
            custom_fields.append(existing_cf_by_fn[fn])
    for row in existing_cf:
        fn = row.get("fieldname")
        if fn not in selected_set and fn not in db_known:
            custom_fields.append(row)  # orphan preserved

    # Field-level property setters: same rule as custom fields.
    property_setters = list(db_field_ps)
    for ps in existing_ps:
        if ps.get("doctype_or_field") != "DocField":
            continue
        fn = ps.get("field_name")
        if fn in selected_set and fn not in db_ps_fns:
            property_setters.append(ps)  # selected orphan kept
        elif fn not in selected_set and fn not in db_known:
            property_setters.append(ps)  # non-selected orphan preserved

    # DocType-level property setters.
    if include_doctype_property_setters:
        property_setters += [
            dict(row)
            for row in frappe.get_all(
                "Property Setter",
                filters={"doc_type": doctype, "doctype_or_field": "DocType"},
                fields="*",
                order_by="name",
            )
        ]
    else:
        property_setters += [
            ps for ps in existing_ps if ps.get("doctype_or_field") != "DocField"
        ]

    if include_links:
        links = [
            dict(row)
            for row in frappe.get_all(
                "DocType Link", filters={"parent": doctype}, fields="*", order_by="name"
            )
        ]
    else:
        links = [r for r in (existing_data.get("links") or []) if isinstance(r, dict)]

    if with_permissions:
        custom_perms = [
            dict(row)
            for row in frappe.get_all(
                "Custom DocPerm", filters={"parent": doctype}, fields="*", order_by="name"
            )
        ]
    else:
        custom_perms = [
            r for r in (existing_data.get("custom_perms") or []) if isinstance(r, dict)
        ]

    return {
        "custom_fields": custom_fields,
        "property_setters": property_setters,
        "custom_perms": custom_perms,
        "links": links,
        "doctype": doctype,
        "sync_on_migrate": cint(sync_on_migrate),
    }


@frappe.whitelist()
def export_selected_customizations(
    app: str,
    module: str,
    doctype: str,
    targets: list[str] | str,
    include_links: int | str = 0,
    include_doctype_property_setters: int | str = 0,
    with_permissions: int | str = 0,
    sync_on_migrate: int | str = 1,
    remove_unselected: int | str = 0,
) -> dict[str, Any]:
    """Write selected customizations to a module, one JSON file per DocType.

    By default this merges (adds/updates) the selected fields and preserves
    every other record in each file. When ``remove_unselected`` is set, each
    affected file is reconciled to the selection: deselected fields known to
    the database are removed and files left empty are deleted.
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
                frappe.bold(module), frappe.bold(module_app), frappe.bold(app)
            )
        )

    include_links = cint(include_links)
    include_doctype_property_setters = cint(include_doctype_property_setters)
    with_permissions = cint(with_permissions)
    sync_on_migrate = cint(sync_on_migrate)
    remove_unselected = cint(remove_unselected)

    tokens = _parse_selected_fields(targets)
    if not tokens and not remove_unselected:
        frappe.throw(_("Select at least one customization to export."))

    # Group selected fieldnames by DocType (parent + child tables).
    valid_doctypes = {doctype}
    for df in frappe.get_meta(doctype).get_table_fields():
        if df.options:
            valid_doctypes.add(df.options)

    fieldnames_by_doctype: dict[str, list[str]] = {}
    for token in tokens:
        dt, fieldname = _decode_target(token)
        if dt not in valid_doctypes:
            frappe.throw(
                _("Target {0} does not belong to {1} or its child tables.").format(
                    frappe.bold(token), frappe.bold(doctype)
                )
            )
        fieldnames_by_doctype.setdefault(dt, [])
        if fieldname not in fieldnames_by_doctype[dt]:
            fieldnames_by_doctype[dt].append(fieldname)

    # Prevent creating cross-app duplicates: a field being exported to this app
    # must not already live in a different app.
    _apps, field_map = _scan_field_locations(doctype)
    conflicts = []
    for token in tokens:
        entry = field_map.get(token)
        if not entry:
            continue
        other_apps = sorted(a for a in entry["apps"] if a != app)
        if other_apps:
            conflicts.append((entry["label"], entry["fieldname"], other_apps))

    if conflicts:
        lines = "".join(
            _("<li><b>{0}</b> ({1}) — already in: {2}</li>").format(
                label, fieldname, ", ".join(other_apps)
            )
            for label, fieldname, other_apps in conflicts
        )
        frappe.throw(
            _(
                "Cannot export — these fields already belong to another app. "
                "Use <b>Reconcile Field Apps</b> to remove them there first:"
            )
            + f"<ul>{lines}</ul>",
            title=_("Duplicate Fields Blocked"),
        )

    folder_path = Path(frappe.get_module_path(module)) / "custom"
    folder_path.mkdir(parents=True, exist_ok=True)

    # In sync mode also reconcile DocTypes whose file exists but had every
    # field deselected, so their removed fields are pruned.
    doctypes_to_process = list(fieldnames_by_doctype.keys())
    if remove_unselected:
        for dt in _doctype_and_children(doctype):
            if dt not in fieldnames_by_doctype and (
                folder_path / f"{frappe.scrub(dt)}.json"
            ).exists():
                doctypes_to_process.append(dt)

    files: list[dict[str, Any]] = []

    # Parent first, then child tables, for stable output ordering.
    ordered_doctypes = [doctype] + sorted(
        dt for dt in doctypes_to_process if dt != doctype
    )

    for dt in ordered_doctypes:
        if dt not in doctypes_to_process:
            continue

        file_path = folder_path / f"{frappe.scrub(dt)}.json"
        existing_data, file_existed = _load_existing_customization_file(
            file_path=file_path,
            doctype=dt,
            sync_on_migrate=sync_on_migrate,
        )

        if remove_unselected:
            result_data = _reconcile_doctype_customization(
                doctype=dt,
                fieldnames=fieldnames_by_doctype.get(dt, []),
                existing_data=existing_data,
                include_links=bool(include_links),
                include_doctype_property_setters=bool(include_doctype_property_setters),
                with_permissions=bool(with_permissions),
                sync_on_migrate=sync_on_migrate,
            )
        else:
            result_data = _merge_customization_data(
                existing_data=existing_data,
                incoming_data=_build_doctype_customization(
                    doctype=dt,
                    fieldnames=fieldnames_by_doctype.get(dt, []),
                    include_links=bool(include_links),
                    include_doctype_property_setters=bool(
                        include_doctype_property_setters
                    ),
                    with_permissions=bool(with_permissions),
                    sync_on_migrate=sync_on_migrate,
                ),
            )

        merged = _sort_customization_lists(result_data)

        is_empty = not (
            merged["custom_fields"]
            or merged["property_setters"]
            or merged["custom_perms"]
        )

        if is_empty:
            if remove_unselected and file_existed:
                file_path.unlink()
                files.append(
                    {
                        "doctype": dt,
                        "path": str(file_path),
                        "file_action": "deleted",
                        "custom_field_count": 0,
                        "property_setter_count": 0,
                        "link_count": 0,
                        "custom_permission_count": 0,
                    }
                )
            continue

        _write_customization_file(file_path=file_path, data=merged)

        files.append(
            {
                "doctype": dt,
                "path": str(file_path),
                "file_action": "updated" if file_existed else "created",
                "custom_field_count": len(merged["custom_fields"]),
                "property_setter_count": len(merged["property_setters"]),
                "link_count": len(merged["links"]),
                "custom_permission_count": len(merged["custom_perms"]),
            }
        )

    return {
        "app": app,
        "module": module,
        "doctype": doctype,
        "files": files,
        "total_files": len(files),
    }


def _doctype_and_children(doctype: str) -> list[str]:
    doctypes = [doctype]
    for df in frappe.get_meta(doctype).get_table_fields():
        if df.options and df.options not in doctypes:
            doctypes.append(df.options)
    return doctypes


@frappe.whitelist()
def get_current_customizations(module: str, doctype: str) -> dict[str, Any]:
    """Return the customizations already present in a module's JSON files.

    Covers the DocType and its child tables so a developer can review, and
    later prune, exactly what has been exported to the selected app/module.
    """
    _validate_access(require_developer_mode=False)

    module = (module or "").strip()
    doctype = (doctype or "").strip()
    if not module or not doctype:
        return {"files": []}

    _validate_doctype(doctype)
    app = _validate_module(module)

    folder_path = Path(frappe.get_module_path(module)) / "custom"

    files: list[dict[str, Any]] = []
    for dt in _doctype_and_children(doctype):
        file_path = folder_path / f"{frappe.scrub(dt)}.json"
        if not file_path.exists():
            continue

        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue

        custom_fields = [
            row
            for row in (data.get("custom_fields") or [])
            if isinstance(row, dict)
        ]
        property_setters = [
            row
            for row in (data.get("property_setters") or [])
            if isinstance(row, dict)
        ]

        cf_by_fieldname = {
            row.get("fieldname"): row
            for row in custom_fields
            if row.get("fieldname")
        }

        field_ps_count: dict[str, int] = {}
        doctype_ps_count = 0
        for ps in property_setters:
            if ps.get("doctype_or_field") == "DocField" and ps.get("field_name"):
                fn = ps["field_name"]
                field_ps_count[fn] = field_ps_count.get(fn, 0) + 1
            elif ps.get("doctype_or_field") == "DocType":
                doctype_ps_count += 1

        ordered_fieldnames = list(cf_by_fieldname.keys())
        for fn in sorted(field_ps_count):
            if fn not in cf_by_fieldname:
                ordered_fieldnames.append(fn)

        fields_out = []
        for fn in ordered_fieldnames:
            cf = cf_by_fieldname.get(fn)
            fields_out.append(
                {
                    "value": _encode_target(dt, fn),
                    "fieldname": fn,
                    "label": (cf.get("label") if cf else None) or fn,
                    "fieldtype": (cf.get("fieldtype") if cf else "") or "",
                    "has_custom_field": bool(cf),
                    "property_setter_count": field_ps_count.get(fn, 0),
                }
            )

        files.append(
            {
                "doctype": dt,
                "is_child": dt != doctype,
                "path": str(file_path),
                "fields": fields_out,
                "doctype_property_setter_count": doctype_ps_count,
                "link_count": len(
                    [r for r in (data.get("links") or []) if isinstance(r, dict)]
                ),
                "custom_perm_count": len(
                    [r for r in (data.get("custom_perms") or []) if isinstance(r, dict)]
                ),
            }
        )

    return {
        "app": app,
        "module": module,
        "doctype": doctype,
        "files": files,
    }


@frappe.whitelist()
def update_current_customizations(
    module: str,
    doctype: str,
    keep_targets: list[str] | str,
) -> dict[str, Any]:
    """Prune field-level customizations from a module's JSON files.

    Any custom field (and its field-level property setters) whose target is not
    in ``keep_targets`` is removed from the file. DocType-level property
    setters, links, and permissions are preserved. A file left with no custom
    fields, property setters, or permissions is deleted. This edits the JSON
    files only; it never deletes the Custom Field record from the database.
    """
    _validate_access(require_developer_mode=True)

    module = (module or "").strip()
    doctype = (doctype or "").strip()
    if not module:
        frappe.throw(_("Module is required."))
    if not doctype:
        frappe.throw(_("DocType is required."))

    _validate_doctype(doctype)
    app = _validate_module(module)

    keep = set(_parse_selected_fields(keep_targets))

    folder_path = Path(frappe.get_module_path(module)) / "custom"

    results: list[dict[str, Any]] = []
    for dt in _doctype_and_children(doctype):
        file_path = folder_path / f"{frappe.scrub(dt)}.json"
        if not file_path.exists():
            continue

        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            frappe.throw(
                _("Could not read customization file {0}: {1}").format(file_path, exc)
            )
        if not isinstance(data, dict):
            continue

        original_cf = [
            row
            for row in (data.get("custom_fields") or [])
            if isinstance(row, dict)
        ]
        original_ps = [
            row
            for row in (data.get("property_setters") or [])
            if isinstance(row, dict)
        ]

        kept_cf = [
            row
            for row in original_cf
            if _encode_target(dt, row.get("fieldname") or "") in keep
        ]

        kept_ps = []
        for ps in original_ps:
            if ps.get("doctype_or_field") == "DocField" and ps.get("field_name"):
                if _encode_target(dt, ps["field_name"]) in keep:
                    kept_ps.append(ps)
            else:
                # Preserve DocType-level property setters.
                kept_ps.append(ps)

        removed_cf = len(original_cf) - len(kept_cf)
        removed_ps = len(original_ps) - len(kept_ps)

        if not removed_cf and not removed_ps:
            results.append(
                {
                    "doctype": dt,
                    "path": str(file_path),
                    "action": "unchanged",
                    "removed_custom_fields": 0,
                    "removed_property_setters": 0,
                }
            )
            continue

        data["custom_fields"] = kept_cf
        data["property_setters"] = kept_ps
        data.setdefault("links", [])
        data.setdefault("custom_perms", [])

        if not (kept_cf or kept_ps or data.get("custom_perms")):
            file_path.unlink()
            action = "deleted"
        else:
            _write_customization_file(
                file_path=file_path,
                data=_sort_customization_lists(data),
            )
            action = "updated"

        results.append(
            {
                "doctype": dt,
                "path": str(file_path),
                "action": action,
                "removed_custom_fields": removed_cf,
                "removed_property_setters": removed_ps,
            }
        )

    return {
        "app": app,
        "module": module,
        "doctype": doctype,
        "results": results,
        "total_removed_custom_fields": sum(
            r["removed_custom_fields"] for r in results
        ),
    }


def _scan_field_locations(doctype: str) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """Scan every installed app's customization files for a field's presence.

    Reads the JSON files directly from disk (globbing ``<app>/*/custom/*.json``)
    without importing any app's Python module, so an uninstalled or broken app
    cannot interfere with the scan.

    Returns ``(apps, field_map)`` where ``field_map`` is keyed by target token
    and each entry records the field's label/type and the apps (and the file
    paths within them) whose customization files contain the field.
    """
    doctypes = _doctype_and_children(doctype)
    scrub_to_doctype = {frappe.scrub(dt): dt for dt in doctypes}

    field_map: dict[str, dict[str, Any]] = {}
    apps_present: set[str] = set()

    def _record(dt: str, fieldname: str, app: str, file_path: Path, cf: dict | None):
        target = _encode_target(dt, fieldname)
        entry = field_map.setdefault(
            target,
            {
                "value": target,
                "doctype": dt,
                "fieldname": fieldname,
                "label": fieldname,
                "fieldtype": "",
                "apps": {},
            },
        )
        if cf:
            entry["label"] = cf.get("label") or fieldname
            entry["fieldtype"] = cf.get("fieldtype") or ""
        entry["apps"].setdefault(app, set()).add(str(file_path))
        apps_present.add(app)

    for app in frappe.get_installed_apps():
        try:
            app_path = Path(frappe.get_app_path(app))
        except Exception:
            continue

        for scrub_name, dt in scrub_to_doctype.items():
            for file_path in app_path.glob(f"*/custom/{scrub_name}.json"):
                try:
                    data = json.loads(file_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                if not isinstance(data, dict):
                    continue

                for cf in data.get("custom_fields") or []:
                    if isinstance(cf, dict) and cf.get("fieldname"):
                        _record(dt, cf["fieldname"], app, file_path, cf)

                for ps in data.get("property_setters") or []:
                    if (
                        isinstance(ps, dict)
                        and ps.get("doctype_or_field") == "DocField"
                        and ps.get("field_name")
                    ):
                        _record(dt, ps["field_name"], app, file_path, None)

    return sorted(apps_present), field_map


@frappe.whitelist()
def get_field_app_matrix(doctype: str) -> dict[str, Any]:
    """Return a field-by-app matrix for reconciliation.

    Each field lists the apps whose customization files contain it. Fields
    present in more than one app are flagged as duplicates.
    """
    _validate_access(require_developer_mode=False)

    doctype = (doctype or "").strip()
    if not doctype:
        return {"doctype": doctype, "apps": [], "fields": [], "duplicate_count": 0}

    _validate_doctype(doctype)

    apps, field_map = _scan_field_locations(doctype)

    fields = []
    for entry in field_map.values():
        app_list = sorted(entry["apps"].keys())
        fields.append(
            {
                "value": entry["value"],
                "doctype": entry["doctype"],
                "fieldname": entry["fieldname"],
                "label": entry["label"],
                "fieldtype": entry["fieldtype"],
                "apps": app_list,
                "is_duplicate": len(app_list) > 1,
            }
        )

    # Duplicates first, then grouped by DocType and fieldname.
    fields.sort(
        key=lambda f: (not f["is_duplicate"], f["doctype"], f["fieldname"])
    )

    return {
        "doctype": doctype,
        "apps": apps,
        "fields": fields,
        "duplicate_count": sum(1 for f in fields if f["is_duplicate"]),
    }


@frappe.whitelist()
def get_duplicate_fields(doctype: str) -> dict[str, Any]:
    """Return only the fields that currently exist in more than one app."""
    _validate_access(require_developer_mode=False)

    doctype = (doctype or "").strip()
    if not doctype:
        return {"doctype": doctype, "duplicates": [], "count": 0}

    _validate_doctype(doctype)

    _apps, field_map = _scan_field_locations(doctype)

    duplicates = [
        {
            "value": entry["value"],
            "doctype": entry["doctype"],
            "fieldname": entry["fieldname"],
            "label": entry["label"],
            "apps": sorted(entry["apps"].keys()),
        }
        for entry in field_map.values()
        if len(entry["apps"]) > 1
    ]
    duplicates.sort(key=lambda d: (d["doctype"], d["fieldname"]))

    return {
        "doctype": doctype,
        "duplicates": duplicates,
        "count": len(duplicates),
    }


def _prune_field_from_file(
    file_path: Path, doctype: str, fieldname: str
) -> dict[str, Any] | None:
    """Remove one field (custom field + field-level property setters) from a
    customization file. Returns a result dict, or ``None`` if nothing
    changed."""
    if not file_path.exists():
        return None

    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        frappe.throw(
            _("Could not read customization file {0}: {1}").format(file_path, exc)
        )
    if not isinstance(data, dict):
        return None

    original_cf = [r for r in (data.get("custom_fields") or []) if isinstance(r, dict)]
    original_ps = [r for r in (data.get("property_setters") or []) if isinstance(r, dict)]

    kept_cf = [r for r in original_cf if r.get("fieldname") != fieldname]
    kept_ps = [
        r
        for r in original_ps
        if not (
            r.get("doctype_or_field") == "DocField"
            and r.get("field_name") == fieldname
        )
    ]

    if len(kept_cf) == len(original_cf) and len(kept_ps) == len(original_ps):
        return None

    data["custom_fields"] = kept_cf
    data["property_setters"] = kept_ps
    data.setdefault("links", [])
    data.setdefault("custom_perms", [])

    if not (kept_cf or kept_ps or data.get("custom_perms")):
        file_path.unlink()
        action = "deleted"
    else:
        _write_customization_file(file_path=file_path, data=_sort_customization_lists(data))
        action = "updated"

    return {
        "doctype": doctype,
        "fieldname": fieldname,
        "action": action,
        "path": str(file_path),
    }


@frappe.whitelist()
def reconcile_field_apps(
    doctype: str, keep_map: dict[str, str] | str
) -> dict[str, Any]:
    """Reconcile which app each field belongs to.

    ``keep_map`` maps a target token to the single app it should remain in
    (use an empty string to remove it from every app). The field is removed
    from every other app that currently contains it. Because each target maps
    to at most one app, this cannot create duplicates.
    """
    _validate_access(require_developer_mode=True)

    doctype = (doctype or "").strip()
    if not doctype:
        frappe.throw(_("DocType is required."))

    _validate_doctype(doctype)

    if isinstance(keep_map, str):
        keep_map = frappe.parse_json(keep_map or "{}")
    if not isinstance(keep_map, dict):
        frappe.throw(_("keep_map must be an object of target to app."))

    _apps, field_map = _scan_field_locations(doctype)

    results: list[dict[str, Any]] = []
    for target, keep_app in keep_map.items():
        entry = field_map.get(target)
        if not entry:
            continue

        keep_app = (keep_app or "").strip()
        dt = entry["doctype"]
        fieldname = entry["fieldname"]

        for app, file_paths in entry["apps"].items():
            if app == keep_app:
                continue
            for file_path in file_paths:
                result = _prune_field_from_file(Path(file_path), dt, fieldname)
                if result:
                    result["app"] = app
                    result["kept_in"] = keep_app
                    results.append(result)

    return {
        "doctype": doctype,
        "results": results,
        "total_removed": len(results),
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
            frappe.as_json(data),
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
