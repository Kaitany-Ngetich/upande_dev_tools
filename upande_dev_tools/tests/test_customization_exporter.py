# Copyright (c) 2026, Upande Limited

import json
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.modules.utils import export_customizations

from upande_dev_tools.api import customization_exporter as ce

PARENT = "Contact"
CHILD = "Contact Email"
MODULE = "Contacts"
APP = "frappe"

# A second app/module used to simulate cross-app duplicates.
APP2 = "upande_dev_tools"
MODULE2 = "Upande Dev Tools"


def _module_custom_dir(module):
    return Path(frappe.get_module_path(module)) / "custom"


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


def _custom_dir():
    return Path(frappe.get_module_path(MODULE)) / "custom"


def _cleanup_files(doctypes):
    for dt in doctypes:
        f = _custom_dir() / f"{frappe.scrub(dt)}.json"
        if f.exists():
            f.unlink()


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


class TestExportSelected(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        if not frappe.conf.developer_mode:
            self.skipTest("developer_mode required")
        _make_custom_field(PARENT, "udt_parent_note")
        _make_custom_field(CHILD, "udt_child_note")
        _cleanup_files([PARENT, CHILD])

    def tearDown(self):
        _cleanup_files([PARENT, CHILD])

    def test_exports_parent_and_child_to_separate_files(self):
        result = ce.export_selected_customizations(
            app=APP,
            module=MODULE,
            doctype=PARENT,
            targets=[
                ce._encode_target(PARENT, "udt_parent_note"),
                ce._encode_target(CHILD, "udt_child_note"),
            ],
        )
        written = {row["doctype"] for row in result["files"]}
        self.assertIn(PARENT, written)
        self.assertIn(CHILD, written)
        self.assertTrue((_custom_dir() / "contact.json").exists())
        self.assertTrue((_custom_dir() / "contact_email.json").exists())


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
        self.custom_dir = _custom_dir()
        _cleanup_files([PARENT, CHILD])

    def tearDown(self):
        _cleanup_files([PARENT, CHILD])

    def _read_all(self):
        out = {}
        for dt in (PARENT, CHILD):
            f = self.custom_dir / f"{frappe.scrub(dt)}.json"
            out[dt] = f.read_bytes() if f.exists() else None
        return out

    def test_full_select_matches_native_bytes(self):
        # Native export.
        export_customizations(
            module=MODULE,
            doctype=PARENT,
            sync_on_migrate=1,
            with_permissions=1,
        )
        native = self._read_all()
        _cleanup_files([PARENT, CHILD])

        # Tool export: every target + all include options.
        targets = [t["value"] for t in ce.get_customization_targets(PARENT)]
        ce.export_selected_customizations(
            app=APP,
            module=MODULE,
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
            self.assertEqual(tool[dt], native[dt], f"byte mismatch for {dt}")


class TestSplitAndIdempotency(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        if not frappe.conf.developer_mode:
            self.skipTest("developer_mode required")
        _make_custom_field(PARENT, "udt_field_a")
        _make_custom_field(PARENT, "udt_field_b")
        self.file = _custom_dir() / "contact.json"
        if self.file.exists():
            self.file.unlink()

    def tearDown(self):
        if self.file.exists():
            self.file.unlink()

    def _fieldnames_in_file(self):
        data = json.loads(self.file.read_text())
        return {cf["fieldname"] for cf in data["custom_fields"]}

    def test_second_field_merges_without_duplicating_first(self):
        ce.export_selected_customizations(
            app=APP,
            module=MODULE,
            doctype=PARENT,
            targets=[ce._encode_target(PARENT, "udt_field_a")],
        )
        self.assertEqual(self._fieldnames_in_file(), {"udt_field_a"})

        ce.export_selected_customizations(
            app=APP,
            module=MODULE,
            doctype=PARENT,
            targets=[ce._encode_target(PARENT, "udt_field_b")],
        )
        self.assertEqual(
            self._fieldnames_in_file(), {"udt_field_a", "udt_field_b"}
        )

    def test_reexport_is_idempotent(self):
        args = dict(
            app=APP,
            module=MODULE,
            doctype=PARENT,
            targets=[ce._encode_target(PARENT, "udt_field_a")],
        )
        ce.export_selected_customizations(**args)
        first = self.file.read_bytes()
        ce.export_selected_customizations(**args)
        second = self.file.read_bytes()
        self.assertEqual(first, second)


class TestSyncMode(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        if not frappe.conf.developer_mode:
            self.skipTest("developer_mode required")
        _make_custom_field(PARENT, "udt_sync_a")
        _make_custom_field(PARENT, "udt_sync_b")
        self.file = _custom_dir() / "contact.json"
        _cleanup_files([PARENT, CHILD])
        ce.export_selected_customizations(
            app=APP,
            module=MODULE,
            doctype=PARENT,
            targets=[
                ce._encode_target(PARENT, "udt_sync_a"),
                ce._encode_target(PARENT, "udt_sync_b"),
            ],
        )

    def tearDown(self):
        _cleanup_files([PARENT, CHILD])

    def _fieldnames_in_file(self):
        data = json.loads(self.file.read_text())
        return {cf["fieldname"] for cf in data["custom_fields"]}

    def test_sync_removes_unselected(self):
        ce.export_selected_customizations(
            app=APP,
            module=MODULE,
            doctype=PARENT,
            targets=[ce._encode_target(PARENT, "udt_sync_a")],
            remove_unselected=1,
        )
        self.assertEqual(self._fieldnames_in_file(), {"udt_sync_a"})

    def test_sync_empty_selection_deletes_file(self):
        result = ce.export_selected_customizations(
            app=APP,
            module=MODULE,
            doctype=PARENT,
            targets=[],
            remove_unselected=1,
        )
        self.assertFalse(self.file.exists())
        actions = {f["file_action"] for f in result["files"]}
        self.assertIn("deleted", actions)

    def test_add_only_default_keeps_both(self):
        ce.export_selected_customizations(
            app=APP,
            module=MODULE,
            doctype=PARENT,
            targets=[ce._encode_target(PARENT, "udt_sync_a")],
        )
        # Default (merge) mode must not remove udt_sync_b.
        self.assertEqual(
            self._fieldnames_in_file(), {"udt_sync_a", "udt_sync_b"}
        )


class TestFieldReconciliation(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        if not frappe.conf.developer_mode:
            self.skipTest("developer_mode required")
        _make_custom_field(PARENT, "udt_dupe")
        self.file1 = _module_custom_dir(MODULE) / "contact.json"
        self.file2 = _module_custom_dir(MODULE2) / "contact.json"
        self._cleanup()
        # Write the same field to two apps directly, so the duplicate exists
        # on disk (the export guard would otherwise prevent creating one).
        for module in (MODULE, MODULE2):
            data = ce._build_doctype_customization(
                doctype=PARENT,
                fieldnames=["udt_dupe"],
                include_links=False,
                include_doctype_property_setters=False,
                with_permissions=False,
                sync_on_migrate=1,
            )
            file_path = _module_custom_dir(module) / "contact.json"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            ce._write_customization_file(
                file_path=file_path,
                data=ce._sort_customization_lists(data),
            )

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        for f in (self.file1, self.file2):
            if f.exists():
                f.unlink()

    def test_matrix_flags_duplicate(self):
        matrix = ce.get_field_app_matrix(PARENT)
        row = next(
            f for f in matrix["fields"]
            if f["value"] == ce._encode_target(PARENT, "udt_dupe")
        )
        self.assertTrue(row["is_duplicate"])
        self.assertIn(APP, row["apps"])
        self.assertIn(APP2, row["apps"])

    def test_get_duplicate_fields(self):
        dupes = ce.get_duplicate_fields(PARENT)
        values = {d["value"] for d in dupes["duplicates"]}
        self.assertIn(ce._encode_target(PARENT, "udt_dupe"), values)

    def test_reconcile_keeps_one_app(self):
        ce.reconcile_field_apps(
            doctype=PARENT,
            keep_map={ce._encode_target(PARENT, "udt_dupe"): APP},
        )
        after = ce.get_duplicate_fields(PARENT)
        values = {d["value"] for d in after["duplicates"]}
        self.assertNotIn(ce._encode_target(PARENT, "udt_dupe"), values)
        # Kept in APP, removed from APP2.
        self.assertTrue(self.file1.exists())
        self.assertFalse(self.file2.exists())

    def test_export_blocked_when_field_in_another_app(self):
        # udt_dupe is in APP2; exporting it to APP must be blocked.
        with self.assertRaises(frappe.ValidationError):
            ce.export_selected_customizations(
                app=APP, module=MODULE, doctype=PARENT,
                targets=[ce._encode_target(PARENT, "udt_dupe")],
                remove_unselected=1,
            )


class TestViewAndPruneCustomizations(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        if not frappe.conf.developer_mode:
            self.skipTest("developer_mode required")
        _make_custom_field(PARENT, "udt_keep_me")
        _make_custom_field(PARENT, "udt_remove_me")
        self.file = _custom_dir() / "contact.json"
        _cleanup_files([PARENT, CHILD])
        ce.export_selected_customizations(
            app=APP,
            module=MODULE,
            doctype=PARENT,
            targets=[
                ce._encode_target(PARENT, "udt_keep_me"),
                ce._encode_target(PARENT, "udt_remove_me"),
            ],
        )

    def tearDown(self):
        _cleanup_files([PARENT, CHILD])

    def _fieldnames_in_file(self):
        data = json.loads(self.file.read_text())
        return {cf["fieldname"] for cf in data["custom_fields"]}

    def test_get_current_lists_exported_fields(self):
        data = ce.get_current_customizations(module=MODULE, doctype=PARENT)
        parent_file = next(f for f in data["files"] if f["doctype"] == PARENT)
        values = {f["value"] for f in parent_file["fields"]}
        self.assertIn(ce._encode_target(PARENT, "udt_keep_me"), values)
        self.assertIn(ce._encode_target(PARENT, "udt_remove_me"), values)

    def test_prune_removes_unchecked_field(self):
        ce.update_current_customizations(
            module=MODULE,
            doctype=PARENT,
            keep_targets=[ce._encode_target(PARENT, "udt_keep_me")],
        )
        self.assertEqual(self._fieldnames_in_file(), {"udt_keep_me"})

    def test_prune_all_deletes_file(self):
        result = ce.update_current_customizations(
            module=MODULE,
            doctype=PARENT,
            keep_targets=[],
        )
        self.assertFalse(self.file.exists())
        actions = {r["action"] for r in result["results"]}
        self.assertIn("deleted", actions)
