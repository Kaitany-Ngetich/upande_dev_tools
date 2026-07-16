# Selective Customization Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let developers bulk-select which customizations of a DocType (custom fields, their property setters, plus opt-in links/doctype-level property setters/permissions, across parent and child tables) get written to a specific app's `custom/*.json`, producing files byte-for-byte compatible with Frappe's native `export_customizations`.

**Architecture:** Extend the existing `upande_dev_tools/api/customization_exporter.py` and `public/js/customize_form_export.js`. Each customization is addressed as a "target" (`<doctype>|||<fieldname>`). The exporter builds one JSON file per DocType (parent + each child table with selected targets) by replicating native `export_customizations` field-for-field but filtered to the selected fieldnames, then merges into any existing file (add/update selected, preserve unrelated) and serializes with `frappe.as_json` + name-sorted lists + no trailing newline.

**Tech Stack:** Frappe framework (Python 3, whitelisted methods), Frappe UI Dialog/MultiSelectList (vanilla JS), Frappe test runner (`FrappeTestCase`).

## Global Constraints

- Byte-for-byte parity target: selecting **every** target + ticking **all three** include-checkboxes + routing to one module MUST produce files identical to `frappe.modules.utils.export_customizations` for that module.
- Serialize via `frappe.as_json(data)` (which is `indent=1`, `sort_keys=True`) with **no trailing newline**.
- Every list (`custom_fields`, `property_setters`, `links`, `custom_perms`) MUST be sorted by `name` before writing (matches native `order_by="name"`).
- Write only a DocType's file when it has `custom_fields` OR `property_setters` OR `custom_perms` (matches native guard — links alone do not trigger a write).
- Preserve existing merge/upsert behavior (add-or-update selected records, keep unrelated ones). Never delete unrelated customizations.
- Access guards unchanged: `frappe.only_for("System Manager")` for all methods; developer mode required for the write path.
- Copyright header on new/modified files: `# Copyright (c) 2026, Upande Limited` (Python) / `// Copyright (c) 2026, Upande Limited` (JS).
- Target token format: `f"{doctype}|||{fieldname}"`. `|||` is the separator (never appears in DocType names or fieldnames).
- Field partition rule for Property Setters: field-level = `doctype_or_field == "DocField"` (keyed by `field_name`); doctype-level = `doctype_or_field == "DocType"`.

## Prerequisites

- A test site with `upande_dev_tools` installed and DB access. `kmnh` works but has only `frappe`; `kaitet.local` currently returns MariaDB "Access denied" (fix its DB password before using it). Tests below use a **frappe-native** parent+child DocType (`Contact`, which has child tables `Contact Email` and `Contact Phone`) so ERPNext is not required. Substitute your site name for `<site>`.
- Run all tests with: `bench --site <site> run-tests --module upande_dev_tools.tests.test_customization_exporter`.

## File Structure

- Modify: `upande_dev_tools/api/customization_exporter.py` — replace `get_custom_field_options` with `get_customization_targets`; add target/serialization helpers; rewrite `export_selected_customizations`. Keep existing `_merge_customization_data`, `_upsert_records`, `_custom_field_key`, `_property_setter_key`, `_custom_permission_key`, `_load_existing_customization_file`, `_parse_selected_fields`, `_validate_*`, `_validate_access`.
- Modify: `upande_dev_tools/public/js/customize_form_export.js` — new dialog (targets multiselect + three checkboxes).
- Create: `upande_dev_tools/tests/__init__.py` — empty package marker.
- Create: `upande_dev_tools/tests/test_customization_exporter.py` — parity, split, idempotency tests.

---

### Task 1: Backend — `get_customization_targets`

Replaces the broken `get_custom_field_options` (its `dt`/`module` filter is commented out, so it lists every DocType's fields). Returns one target per field that carries a customization, across the parent DocType and all its child tables.

**Files:**
- Modify: `upande_dev_tools/api/customization_exporter.py` (remove `get_custom_field_options` and its helper `_get_field_description`; add `get_customization_targets`, `_collect_targets_for_doctype`, `_encode_target`, `_decode_target`)
- Test: `upande_dev_tools/tests/test_customization_exporter.py`

**Interfaces:**
- Produces:
  - `get_customization_targets(doctype: str) -> list[dict]` — each dict: `{"value": "<doctype>|||<fieldname>", "description": "<DocType> · <label> — <fieldname> — <kind>"}` where `<kind>` is `"Custom Field"`, `"N property setter(s)"`, or `"Custom Field + N property setter(s)"`. Parent-DocType targets are returned first, then each child table's targets; within a DocType, ordered by `Custom Field.idx asc, fieldname asc` then fieldnames that only have property setters.
  - `_encode_target(doctype: str, fieldname: str) -> str` → `f"{doctype}|||{fieldname}"`
  - `_decode_target(token: str) -> tuple[str, str]` → `(doctype, fieldname)`; raises `frappe.ValidationError` via `frappe.throw` if `|||` absent.

- [ ] **Step 1: Write the failing test**

Add to `upande_dev_tools/tests/test_customization_exporter.py` (create the file with this content; also create empty `upande_dev_tools/tests/__init__.py`):

```python
# Copyright (c) 2026, Upande Limited

import frappe
from frappe.tests.utils import FrappeTestCase

from upande_dev_tools.api import customization_exporter as ce

PARENT = "Contact"
CHILD = "Contact Email"


def _make_custom_field(dt, fieldname):
    if frappe.db.exists("Custom Field", {"dt": dt, "fieldname": fieldname}):
        return
    frappe.get_doc(
        {
            "doctype": "Custom Field",
            "dt": dt,
            "fieldname": fieldname,
            "label": fieldname.replace("_", " ").title(),
            "fieldtype": "Data",
            "insert_after": "email_id" if dt == CHILD else "email_ids",
        }
    ).insert(ignore_permissions=True)


class TestCustomizationTargets(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        _make_custom_field(PARENT, "udt_parent_note")
        _make_custom_field(CHILD, "udt_child_note")

    def test_targets_include_parent_and_child_custom_fields(self):
        targets = ce.get_customization_targets(PARENT)
        values = {t["value"] for t in targets}
        self.assertIn(ce._encode_target(PARENT, "udt_parent_note"), values)
        self.assertIn(ce._encode_target(CHILD, "udt_child_note"), values)

    def test_decode_roundtrip(self):
        token = ce._encode_target(PARENT, "udt_parent_note")
        self.assertEqual(ce._decode_target(token), (PARENT, "udt_parent_note"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site <site> run-tests --module upande_dev_tools.tests.test_customization_exporter`
Expected: FAIL — `AttributeError: module ... has no attribute 'get_customization_targets'` (and `_encode_target`).

- [ ] **Step 3: Write minimal implementation**

In `customization_exporter.py`, delete `get_custom_field_options` and `_get_field_description`, and add:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bench --site <site> run-tests --module upande_dev_tools.tests.test_customization_exporter`
Expected: PASS (`TestCustomizationTargets`).

- [ ] **Step 5: Commit**

```bash
git add upande_dev_tools/api/customization_exporter.py upande_dev_tools/tests/__init__.py upande_dev_tools/tests/test_customization_exporter.py
git commit -m "feat(exporter): add get_customization_targets for parent+child fields"
```

---

### Task 2: Backend — parity serialization + per-DocType file builder

Add the helpers that make each file byte-identical to native: name-sorting, no-trailing-newline write, and a routine that builds one DocType's customization dict filtered to selected fieldnames + the three include options.

**Files:**
- Modify: `upande_dev_tools/api/customization_exporter.py` (add `_sort_by_name`, `_sort_customization_lists`; change `_write_customization_file` to drop the trailing newline; add `_build_doctype_customization`)
- Test: `upande_dev_tools/tests/test_customization_exporter.py`

**Interfaces:**
- Consumes: `_decode_target` (Task 1), existing `_load_existing_customization_file`, `_merge_customization_data`.
- Produces:
  - `_sort_customization_lists(data: dict) -> dict` — returns `data` with `custom_fields`/`property_setters`/`links`/`custom_perms` each sorted by `name`.
  - `_build_doctype_customization(doctype, fieldnames, include_links, include_doctype_property_setters, with_permissions, sync_on_migrate) -> dict` — the native-shaped customization dict for one DocType filtered to `fieldnames` (a list/set of fieldnames selected for this DocType), plus opt-in links/doctype-level property setters/perms.
  - `_write_customization_file(*, file_path, data)` — writes `frappe.as_json(data)` with no trailing newline (atomic temp-file swap retained).

- [ ] **Step 1: Write the failing test**

Append to `test_customization_exporter.py`:

```python
class TestDoctypeCustomizationBuilder(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        _make_custom_field(PARENT, "udt_parent_note")

    def test_build_includes_selected_field_only(self):
        data = ce._build_doctype_customization(
            doctype=PARENT,
            fieldnames={"udt_parent_note"},
            include_links=False,
            include_doctype_property_setters=False,
            with_permissions=False,
            sync_on_migrate=1,
        )
        fieldnames = {cf["fieldname"] for cf in data["custom_fields"]}
        self.assertEqual(fieldnames, {"udt_parent_note"})
        self.assertEqual(data["doctype"], PARENT)
        self.assertEqual(data["links"], [])
        self.assertEqual(data["custom_perms"], [])

    def test_lists_sorted_by_name(self):
        _make_custom_field(PARENT, "udt_aaa")
        data = ce._build_doctype_customization(
            doctype=PARENT,
            fieldnames={"udt_parent_note", "udt_aaa"},
            include_links=False,
            include_doctype_property_setters=False,
            with_permissions=False,
            sync_on_migrate=1,
        )
        names = [cf["name"] for cf in data["custom_fields"]]
        self.assertEqual(names, sorted(names))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site <site> run-tests --module upande_dev_tools.tests.test_customization_exporter`
Expected: FAIL — `AttributeError: ... has no attribute '_build_doctype_customization'`.

- [ ] **Step 3: Write minimal implementation**

Add to `customization_exporter.py`:

```python
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
```

Then change `_write_customization_file` to drop the trailing newline — replace:

```python
        temporary_path.write_text(
            f"{frappe.as_json(data)}\n",
            encoding="utf-8",
        )
```

with:

```python
        temporary_path.write_text(
            frappe.as_json(data),
            encoding="utf-8",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bench --site <site> run-tests --module upande_dev_tools.tests.test_customization_exporter`
Expected: PASS (`TestDoctypeCustomizationBuilder`).

- [ ] **Step 5: Commit**

```bash
git add upande_dev_tools/api/customization_exporter.py upande_dev_tools/tests/test_customization_exporter.py
git commit -m "feat(exporter): add per-doctype builder, name-sort, drop trailing newline"
```

---

### Task 3: Backend — rewrite `export_selected_customizations`

Accept targets + the three include options, group targets by DocType, write/merge one file per DocType (parent + each child table with selected targets), applying the native write guard, merge, sort, and parity serialization.

**Files:**
- Modify: `upande_dev_tools/api/customization_exporter.py` (rewrite `export_selected_customizations`)
- Test: `upande_dev_tools/tests/test_customization_exporter.py`

**Interfaces:**
- Consumes: `_decode_target`, `_build_doctype_customization`, `_sort_customization_lists` (Tasks 1–2); existing `_parse_selected_fields`, `_load_existing_customization_file`, `_merge_customization_data`, `_write_customization_file`, `_validate_*`, `_validate_access`.
- Produces:
  - `export_selected_customizations(app, module, doctype, targets, include_links=0, include_doctype_property_setters=0, with_permissions=0, sync_on_migrate=1) -> dict` — writes one file per DocType. Returns `{"app", "module", "doctype", "files": [ {"doctype", "path", "file_action", "custom_field_count", "property_setter_count", "link_count", "custom_permission_count"} ], "total_files"}`.

Merge semantics: build the native-shaped dict for the DocType (filtered to its selected fieldnames + include options), load any existing file, merge (upsert selected records, preserve unrelated), sort every list by `name`, write with no trailing newline. Write a DocType's file only when the merged result has `custom_fields` OR `property_setters` OR `custom_perms`.

- [ ] **Step 1: Write the failing test**

Append to `test_customization_exporter.py`:

```python
import os


class TestExportSelected(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        if not frappe.conf.developer_mode:
            self.skipTest("developer_mode required")
        _make_custom_field(PARENT, "udt_parent_note")
        _make_custom_field(CHILD, "udt_child_note")
        self.module = "Contacts"  # module owning Contact; app frappe
        self.app = "frappe"
        self._cleanup_files()

    def tearDown(self):
        self._cleanup_files()

    def _custom_dir(self):
        from pathlib import Path

        return Path(frappe.get_module_path(self.module)) / "custom"

    def _cleanup_files(self):
        for dt in (PARENT, CHILD):
            f = self._custom_dir() / f"{frappe.scrub(dt)}.json"
            if f.exists():
                f.unlink()

    def test_exports_parent_and_child_to_separate_files(self):
        result = ce.export_selected_customizations(
            app=self.app,
            module=self.module,
            doctype=PARENT,
            targets=[
                ce._encode_target(PARENT, "udt_parent_note"),
                ce._encode_target(CHILD, "udt_child_note"),
            ],
        )
        written = {row["doctype"] for row in result["files"]}
        self.assertIn(PARENT, written)
        self.assertIn(CHILD, written)
        self.assertTrue((self._custom_dir() / "contact.json").exists())
        self.assertTrue((self._custom_dir() / "contact_email.json").exists())
```

Note: `self.app`/`self.module` assume `Contact` is owned by the `frappe` app's `Contacts` module. Confirm on your site with `frappe.db.get_value("DocType", "Contact", "module")` and adjust if different.

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site <site> run-tests --module upande_dev_tools.tests.test_customization_exporter`
Expected: FAIL — `TypeError` (old signature has no `targets` param) or assertion error on separate files.

- [ ] **Step 3: Write minimal implementation**

Replace the entire `export_selected_customizations` function body with:

```python
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
) -> dict[str, Any]:
    """Write selected customizations to a module, one JSON file per DocType.

    Existing unrelated customizations in each file are preserved.
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

    tokens = _parse_selected_fields(targets)
    if not tokens:
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

    folder_path = Path(frappe.get_module_path(module)) / "custom"
    folder_path.mkdir(parents=True, exist_ok=True)

    files: list[dict[str, Any]] = []

    # Parent first, then child tables, for stable output ordering.
    ordered_doctypes = [doctype] + sorted(
        dt for dt in fieldnames_by_doctype if dt != doctype
    )

    for dt in ordered_doctypes:
        if dt not in fieldnames_by_doctype:
            continue

        incoming = _build_doctype_customization(
            doctype=dt,
            fieldnames=fieldnames_by_doctype[dt],
            include_links=bool(include_links),
            include_doctype_property_setters=bool(include_doctype_property_setters),
            with_permissions=bool(with_permissions),
            sync_on_migrate=sync_on_migrate,
        )

        file_path = folder_path / f"{frappe.scrub(dt)}.json"
        existing_data, file_existed = _load_existing_customization_file(
            file_path=file_path,
            doctype=dt,
            sync_on_migrate=sync_on_migrate,
        )
        merged = _sort_customization_lists(
            _merge_customization_data(
                existing_data=existing_data,
                incoming_data=incoming,
            )
        )

        if not (
            merged["custom_fields"]
            or merged["property_setters"]
            or merged["custom_perms"]
        ):
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bench --site <site> run-tests --module upande_dev_tools.tests.test_customization_exporter`
Expected: PASS (`TestExportSelected`).

- [ ] **Step 5: Commit**

```bash
git add upande_dev_tools/api/customization_exporter.py upande_dev_tools/tests/test_customization_exporter.py
git commit -m "feat(exporter): rewrite export_selected_customizations for targets + child files"
```

---

### Task 4: Backend — byte-for-byte parity test vs native export

Prove the Global Constraint: select every target + all include options + one module ⇒ files identical to `frappe.modules.utils.export_customizations`.

**Files:**
- Test: `upande_dev_tools/tests/test_customization_exporter.py`

**Interfaces:**
- Consumes: `get_customization_targets`, `export_selected_customizations` (Tasks 1,3); `frappe.modules.utils.export_customizations`.

- [ ] **Step 1: Write the failing test**

Append to `test_customization_exporter.py`:

```python
from frappe.modules.utils import export_customizations


class TestNativeParity(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        if not frappe.conf.developer_mode:
            self.skipTest("developer_mode required")
        _make_custom_field(PARENT, "udt_parent_note")
        _make_custom_field(CHILD, "udt_child_note")
        # A doctype-level property setter (sort order) so parity covers it.
        frappe.make_property_setter(
            {
                "doctype": PARENT,
                "doctype_or_field": "DocType",
                "property": "sort_field",
                "value": "modified",
                "property_type": "Data",
            },
            is_system_generated=False,
        )
        self.module = "Contacts"
        self.app = "frappe"
        from pathlib import Path

        self.custom_dir = Path(frappe.get_module_path(self.module)) / "custom"
        self._cleanup()

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        for dt in (PARENT, CHILD):
            f = self.custom_dir / f"{frappe.scrub(dt)}.json"
            if f.exists():
                f.unlink()

    def _read_all(self):
        out = {}
        for dt in (PARENT, CHILD):
            f = self.custom_dir / f"{frappe.scrub(dt)}.json"
            out[dt] = f.read_bytes() if f.exists() else None
        return out

    def test_full_select_matches_native_bytes(self):
        # Native export.
        export_customizations(
            module=self.module,
            doctype=PARENT,
            sync_on_migrate=1,
            with_permissions=1,
        )
        native = self._read_all()
        self._cleanup()

        # Tool export: every target + all include options.
        targets = [t["value"] for t in get_customization_targets(PARENT)]
        ce.export_selected_customizations(
            app=self.app,
            module=self.module,
            doctype=PARENT,
            targets=targets,
            include_links=1,
            include_doctype_property_setters=1,
            with_permissions=1,
            sync_on_migrate=1,
        )
        tool = self._read_all()

        self.assertEqual(tool.keys(), native.keys())
        for dt in native:
            self.assertEqual(
                tool[dt], native[dt], f"byte mismatch for {dt}"
            )
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `bench --site <site> run-tests --module upande_dev_tools.tests.test_customization_exporter`
Expected: This is the acceptance test. If it fails, the diff pinpoints the parity gap (ordering, newline, missing key). Fix in `customization_exporter.py` until it PASSES. Do not proceed until green.

Common failure causes and fixes (apply only if the test fails):
- Trailing newline mismatch → confirm Task 2 Step 3 removed the `\n`.
- List order mismatch → confirm `_sort_customization_lists` runs on the merged dict (Task 3).
- Missing `custom_perms`/`links` → confirm include options are passed as `1` in the test and honored in `_build_doctype_customization`.

- [ ] **Step 3: Commit**

```bash
git add upande_dev_tools/tests/test_customization_exporter.py
git commit -m "test(exporter): byte-for-byte parity with native export_customizations"
```

---

### Task 5: Backend — split + idempotency test

Prove the feature's reason for existing: route field A to app/module 1 and field B to app/module 2 without duplication, and re-exporting does not change bytes.

**Files:**
- Test: `upande_dev_tools/tests/test_customization_exporter.py`

- [ ] **Step 1: Write the failing test**

Append to `test_customization_exporter.py`:

```python
class TestSplitAndIdempotency(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        if not frappe.conf.developer_mode:
            self.skipTest("developer_mode required")
        _make_custom_field(PARENT, "udt_field_a")
        _make_custom_field(PARENT, "udt_field_b")
        self.module = "Contacts"
        self.app = "frappe"
        from pathlib import Path

        self.file = Path(frappe.get_module_path(self.module)) / "custom" / "contact.json"
        if self.file.exists():
            self.file.unlink()

    def tearDown(self):
        if self.file.exists():
            self.file.unlink()

    def _fieldnames_in_file(self):
        import json

        data = json.loads(self.file.read_text())
        return {cf["fieldname"] for cf in data["custom_fields"]}

    def test_second_field_merges_without_duplicating_first(self):
        ce.export_selected_customizations(
            app=self.app, module=self.module, doctype=PARENT,
            targets=[ce._encode_target(PARENT, "udt_field_a")],
        )
        self.assertEqual(self._fieldnames_in_file(), {"udt_field_a"})

        ce.export_selected_customizations(
            app=self.app, module=self.module, doctype=PARENT,
            targets=[ce._encode_target(PARENT, "udt_field_b")],
        )
        self.assertEqual(self._fieldnames_in_file(), {"udt_field_a", "udt_field_b"})

    def test_reexport_is_idempotent(self):
        args = dict(
            app=self.app, module=self.module, doctype=PARENT,
            targets=[ce._encode_target(PARENT, "udt_field_a")],
        )
        ce.export_selected_customizations(**args)
        first = self.file.read_bytes()
        ce.export_selected_customizations(**args)
        second = self.file.read_bytes()
        self.assertEqual(first, second)
```

- [ ] **Step 2: Run test to verify it passes**

Run: `bench --site <site> run-tests --module upande_dev_tools.tests.test_customization_exporter`
Expected: PASS (`TestSplitAndIdempotency`).

- [ ] **Step 3: Commit**

```bash
git add upande_dev_tools/tests/test_customization_exporter.py
git commit -m "test(exporter): split-across-apps and idempotent re-export"
```

---

### Task 6: Frontend — targets dialog with include options

Replace the dialog to use the grouped targets multiselect and the three include checkboxes; report per-file results.

**Files:**
- Modify: `upande_dev_tools/public/js/customize_form_export.js` (rewrite `show_selective_export_dialog` and `primary_action`)
- Manual verification (no unit test; JS runs in-browser)

**Interfaces:**
- Consumes: `get_customization_targets`, `export_selected_customizations` (Tasks 1,3), `get_exportable_apps` (unchanged).

- [ ] **Step 1: Rewrite the dialog**

Replace the `custom_fields` MultiSelectList field, the `with_permissions` check, and `primary_action` in `customize_form_export.js`. The App/Module fields and the button-replacement `refresh` handler stay as-is. New field set (replace the array from the `Section Break "Custom Fields"` onward):

```javascript
			{
				fieldtype: "Section Break",
				label: __("Customizations to Export"),
			},
			{
				fieldtype: "MultiSelectList",
				fieldname: "targets",
				label: __("Fields / Property Setters"),
				reqd: 1,
				description: __(
					"Custom fields and field-level property setters for this DocType and its child tables. Each item is written to its own DocType file in the selected app."
				),

				async get_data(txt) {
					if (!frm.doc.doc_type) {
						return [];
					}

					const rows =
						(await frappe.xcall(
							"upande_dev_tools.api.customization_exporter.get_customization_targets",
							{ doctype: frm.doc.doc_type }
						)) || [];

					const needle = (txt || "").toLowerCase();
					return needle
						? rows.filter((r) =>
								(r.description || r.value)
									.toLowerCase()
									.includes(needle)
						  )
						: rows;
				},
			},
			{
				fieldtype: "Section Break",
				label: __("Also Include (goes to the selected app)"),
			},
			{
				fieldtype: "Check",
				fieldname: "include_links",
				label: __("Include DocType Links (Connections)"),
				default: 0,
			},
			{
				fieldtype: "Check",
				fieldname: "include_doctype_property_setters",
				label: __("Include DocType-level property settings"),
				default: 0,
				description: __(
					"Sort order, title field, search fields, and other DocType-level settings."
				),
			},
			{
				fieldtype: "Check",
				fieldname: "with_permissions",
				label: __("Include Custom Permissions"),
				default: 0,
				description: __(
					"Custom permissions are force-synced on every migrate, overriding other customizations."
				),
			},
			{
				fieldtype: "Check",
				fieldname: "sync_on_migrate",
				label: __("Sync on Migrate"),
				default: 1,
			},
```

- [ ] **Step 2: Rewrite `primary_action`**

Replace `primary_action` with:

```javascript
		primary_action_label: __("Export Selected"),

		async primary_action(values) {
			const targets = values.targets || [];
			if (!targets.length) {
				frappe.throw(__("Select at least one customization to export."));
			}

			const primary_button = dialog.get_primary_btn();
			primary_button.prop("disabled", true);

			try {
				const result = await frappe.xcall(
					"upande_dev_tools.api.customization_exporter.export_selected_customizations",
					{
						app: values.app,
						module: values.module,
						doctype: frm.doc.doc_type,
						targets,
						include_links: values.include_links,
						include_doctype_property_setters:
							values.include_doctype_property_setters,
						with_permissions: values.with_permissions,
						sync_on_migrate: values.sync_on_migrate,
					}
				);

				dialog.hide();

				const rows = (result.files || [])
					.map(
						(f) =>
							`<tr>
								<td>${frappe.utils.escape_html(f.doctype)}</td>
								<td>${f.file_action}</td>
								<td>${f.custom_field_count}</td>
								<td>${f.property_setter_count}</td>
								<td><code>${frappe.utils.escape_html(f.path)}</code></td>
							</tr>`
					)
					.join("");

				frappe.msgprint({
					title: __("Export Completed"),
					indicator: "green",
					message: `
						<p>${__("{0} file(s) written to app {1}.", [
							result.total_files,
							frappe.utils.escape_html(result.app),
						])}</p>
						<table class="table table-bordered">
							<thead><tr>
								<th>${__("DocType")}</th>
								<th>${__("Action")}</th>
								<th>${__("Fields")}</th>
								<th>${__("Prop. Setters")}</th>
								<th>${__("File")}</th>
							</tr></thead>
							<tbody>${rows}</tbody>
						</table>
					`,
				});
			} finally {
				primary_button.prop("disabled", false);
			}
		},
```

Also update the App `change()` and Module `change()` handlers: replace every reference to `custom_fields` with `targets` (e.g. `dialog.set_value("targets", []); dialog.fields_dict.targets.refresh();`).

- [ ] **Step 3: Build assets and manually verify**

Run: `bench build --app upande_dev_tools` then `bench --site <site> clear-cache`.
Then in the browser (developer mode, logged in as System Manager):
1. Open **Customize Form**, pick a DocType with custom fields on parent and a child table (e.g. `Contact`).
2. Click **Actions → Export Customizations**. Confirm the dialog lists parent and child targets (grouped by DocType in the description).
3. Pick App + Module, select one parent field, click **Export Selected**. Confirm the success table shows one file (`contact.json`) and the file on disk contains only that field.
4. Re-open, select a child-table field, export. Confirm a separate `contact_email.json` is written and the parent file is unchanged.

Expected: dialog behaves as described; files match; no console errors.

- [ ] **Step 4: Commit**

```bash
git add upande_dev_tools/public/js/customize_form_export.js
git commit -m "feat(ui): targets multiselect + include options for selective export"
```

---

### Task 7: Full suite + docs

**Files:**
- Modify: `upande_dev_tools/README.md` (document the feature) — optional if a README section exists; otherwise add a short "Selective Customization Export" section.

- [ ] **Step 1: Run the entire test module**

Run: `bench --site <site> run-tests --module upande_dev_tools.tests.test_customization_exporter`
Expected: all classes PASS (`TestCustomizationTargets`, `TestDoctypeCustomizationBuilder`, `TestExportSelected`, `TestNativeParity`, `TestSplitAndIdempotency`).

- [ ] **Step 2: Document the feature**

Add to `upande_dev_tools/README.md`:

```markdown
## Selective Customization Export

In developer mode, **Customize Form → Actions → Export Customizations** opens a
dialog to bulk-select custom fields / field-level property setters (parent and
child tables) and write them to a chosen app's `custom/*.json`. Optional
checkboxes add DocType Links, DocType-level property settings, and custom
permissions. Existing customizations in the target files are preserved (merge,
not overwrite). Output is byte-for-byte compatible with Frappe's native
`export_customizations`, so `bench migrate` syncs it identically.
```

- [ ] **Step 3: Commit**

```bash
git add upande_dev_tools/README.md
git commit -m "docs: document selective customization export"
```

---

## Self-Review

- **Spec coverage:** targets/parent+child (Task 1,3), field-level PS routing (Task 2,3), three include checkboxes (Task 2,3,6), byte parity incl. sort + no-newline (Task 2,4), child separate files (Task 3), merge/no-duplication (Task 5), broken `get_custom_field_options` filter replaced (Task 1), UI (Task 6). Issue #34562 "Module (for export)" pre-filter was marked optional in the spec and is intentionally deferred (YAGNI) — targets are chosen explicitly, which supersedes module-based filtering; add later if desired.
- **Placeholder scan:** none — all steps carry concrete code/commands. The only site-specific value is `<site>` and the `Contacts`/`frappe` module/app for `Contact`, flagged for confirmation in Task 3 Step 1.
- **Type consistency:** `_encode_target`/`_decode_target`, `_build_doctype_customization`, `_sort_customization_lists`, `export_selected_customizations` signatures match across tasks; JS field name `targets` used consistently; result shape (`files`, `total_files`, per-file counts) consistent between Task 3 and Task 6.
```
