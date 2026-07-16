# Selective, Parity-Preserving Customization Export — Design

Date: 2026-07-16
App: `upande_dev_tools`
Related: Frappe `frappe/modules/utils.py::export_customizations`, GitHub issue frappe/frappe#34562

## Problem

Frappe's native **Export Customizations** writes *every* customization of a DocType
into a single `<module>/custom/<doctype>.json`. When a team maintains several apps
that each customize the same DocType (e.g. `Stock Entry`), there is no way to say
"field A belongs to app 1, field B belongs to app 2." Using the native export from
two apps duplicates every field into both apps' JSON files.

We need a UX-friendly way to **bulk-select** which customizations go to which app,
**without losing any functionality** of the native export, and the produced JSON must
be **byte-for-byte compatible** with Frappe's format so `bench migrate` /
`sync_customizations` applies it identically.

An existing partial implementation lives in
`upande_dev_tools/api/customization_exporter.py` and
`upande_dev_tools/public/js/customize_form_export.js`. This design closes the gaps
between it and the native export.

## Baseline: what native `export_customizations` produces

For a DocType it writes `<module>/custom/<doctype>.json` with these keys, **each list
ordered by `name`**:

- `custom_fields` — every `Custom Field` where `dt = doctype`
- `property_setters` — every `Property Setter` where `doc_type = doctype`
  (includes **doctype-level** setters: sort order, title field, search fields, etc.,
  and setters on **standard** fields such as relabel/hide)
- `links` — every `DocType Link` where `parent = doctype`
- `custom_perms` — only when "with permissions" is checked (all `Custom DocPerm`)
- `doctype`, `sync_on_migrate`

It **recurses into every child table**, writing a *separate* `<child_doctype>.json`.
Serialization is `frappe.as_json` (`indent=1`, `sort_keys=True`, **no trailing
newline**), overwriting the whole file each run.

Issue #34562 asks for one addition: filter exported items by the Custom Field's
**"Module (for export)"** field (`Custom Field.module`, confirmed to exist).

## Gaps in the current build (to fix)

| # | Area | Native | Current build | Fix |
|---|------|--------|---------------|-----|
| 1 | Field option filter | — | `dt`/`module` filter commented out → lists every DocType's fields | Filter to this DocType (+ children) |
| 2 | List ordering | `order_by="name"` | selection/merge-append order | Sort every list by `name` before write |
| 3 | Trailing newline | none | writes `...)}\n` | Drop the newline |
| 4 | Child tables | separate files | not handled | Fan out to `<child>.json` |
| 5 | Doctype-level property setters | included | only field-level for selected fields | Include via opt-in checkbox |
| 6 | DocType Links | exported | always `[]` | Include via opt-in checkbox |
| 7 | Property setter `module` filter | none | filters by `module` | Route by field, not module |

The **merge (add/update selected, preserve unrelated)** behavior is intentional and
kept — it is what makes per-app splitting safe and is not a gap.

## Design

### Core model — "customization targets"

The selectable unit is a **customization target**: a field that carries a
customization, on the parent DocType **or any child table**. A target is either:

- a **Custom Field** (carries its field def + any Property Setters on that field), or
- a **standard field** that has one or more Property Setters (e.g. a relabeled or
  hidden built-in field).

Selecting a target pulls its `Custom Field` record (if custom) **and** all
`Property Setter` rows targeting that field. This covers the standard-field-relabel
case that native full export includes but naive per-field selection would miss
(gaps #5/#7).

Three separate opt-in checkboxes handle non-field items ("per-export checkboxes" —
whatever is ticked goes into the app currently being exported to):

- **Include DocType Links** → all `DocType Link` for the DocType
- **Include doctype-level property settings** → `Property Setter` where
  `doctype_or_field = "DocType"`
- **Include custom permissions** → all `Custom DocPerm` (native `with_permissions`)

**Parity invariant (acceptance test):** selecting *every* target + ticking all three
checkboxes + routing to one module ⇒ output is **byte-for-byte identical** to native
`export_customizations` for that module.

### Serialization rules (byte-identity)

- Write via `frappe.as_json(data)` with **no trailing newline**.
- Before writing, **sort every list by `name`**: `custom_fields`, `property_setters`,
  `links`, `custom_perms` (matches native `order_by="name"`). Top-level keys already
  match because `as_json` uses `sort_keys=True`.
- Keep the atomic temp-file write and the merge/upsert (add-or-update selected,
  preserve unrelated). Merged output is re-sorted so it stays parity-clean regardless
  of insertion order.

### Child tables (separate files)

For each distinct child DocType among the selected targets, write/merge its own
`<child_doctype>.json` in the **same** module's `custom/` folder — mirroring native
separate-file behavior (gap #4). The dialog groups targets under their DocType
(parent first, then each child table) so child fields can also be split per app.

### Backend — `upande_dev_tools/api/customization_exporter.py`

- `get_exportable_apps()` — unchanged.
- `get_customization_targets(doctype)` — **replaces** `get_custom_field_options`.
  Returns targets grouped by parent + child DocTypes. Each target labeled
  `Label — fieldname — [Custom Field | N property setter(s)]`. Fixes gap #1.
- `export_selected_customizations(app, module, doctype, targets, include_links,
  include_doctype_property_setters, with_permissions, sync_on_migrate)` — extended to:
  resolve field-level property setters per target; fan child DocTypes out to their own
  files; apply sort + no-newline serialization; keep the merge/upsert.
- Keep guards: `frappe.only_for("System Manager")` and developer-mode required for the
  write path.

Optional convenience (issue #34562): accept a flag to pre-filter targets to those whose
`Custom Field.module` equals the chosen module.

### UI — `upande_dev_tools/public/js/customize_form_export.js`

Same approach: remove the native "Export Customizations" button and add ours. Dialog:

1. **App** (Select)
2. **Module** (Link `Module Def`, filtered by app)
3. **Targets** (MultiSelectList, grouped by DocType — parent then child tables)
4. **Include DocType Links** (Check)
5. **Include doctype-level property settings** (Check)
6. **Export Custom Permissions** (Check)
7. **Sync on Migrate** (Check, default 1)
8. Optional: **Only fields marked for this module** (Check, pre-filters by
   `Custom Field.module`)

Success message reports per-file results (created/updated + counts), including any
child-table files written.

## Verification

A parity test (`upande_dev_tools/tests`):

1. On a DocType customized with parent + child-table custom fields plus a
   doctype-level property setter and a link, run native `export_customizations` to
   module M; capture the bytes of every file it writes.
2. In a clean state, drive `export_selected_customizations` selecting **all** targets +
   ticking all three checkboxes, to module M.
3. Assert every generated file is **byte-identical** to the native snapshot.

Also drive the split case: route field A to app 1 and field B to app 2; assert each
file contains only its field, the union equals the native export, and re-exporting is
idempotent (merge does not duplicate).

## Out of scope

- Changing native Frappe behavior.
- Non-customization exports (fixtures, standard doctypes).
- Reverting/removing customizations from a file (this tool only adds/updates).
