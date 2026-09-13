# Requests & Backlog — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the `Request` doctype, its approval workflow, the Task/Project integration, and the whitelisted API that Phase 2 (portal) and Phase 3 (mobile) will both build on — usable from the desk immediately.

**Architecture:** A new Frappe module `Requests` inside `upande_dev_tools`, laid out like ERPNext's `projects` module (`doctype/`, `workspace/`, a flat `utils.py`). One `Request` doctype drives everything through a native Frappe `Workflow` (fixture-shipped), which is also what enforces every access rule described below — no hand-rolled permission checks duplicate what the workflow engine already does for free. Two Task custom fields close the loop back to the official backlog.

**Tech Stack:** Frappe framework (this bench: `>=16.0.0,<=17.0.0`), Python 3.14, MariaDB via the Frappe ORM. No JavaScript in this phase — Frappe's Workflow feature renders its own action buttons, so no client script is needed yet.

**Spec:** `docs/specs/2026-09-13-requests-backlog-phase1-design.md`

## Global Constraints

- Frappe version floor/ceiling: `>=16.0.0,<=17.0.0` (`pyproject.toml`).
- Every `@frappe.whitelist()` method must have full parameter **and return** type annotations — this app sets `require_type_annotated_api_methods = True` in `hooks.py`. Untyped whitelisted methods will fail CI.
- New Python files: tab indentation, double-quoted strings, 110-char lines (`pyproject.toml`'s `[tool.ruff.format]`). Run `ruff format <file>` on every new/modified `.py` file before committing — this normalizes whitespace/quotes automatically, so don't hand-fuss over exact indentation while writing.
- Doctype controller files start with:
  ```
  # Copyright (c) 2026, shadrack@upande.com and contributors
  # For license information, please see license.txt
  ```
  Test files start with:
  ```
  # Copyright (c) 2026, shadrack@upande.com and Contributors
  # See license.txt
  ```
  (Exact capitalization/wording differs between the two — that's the existing convention in this app, matched from `module_version_check.py`/`test_module_version_check.py`.)
- Doctype tests extend `frappe.tests.IntegrationTestCase` (the convention already used by `test_module_version_check.py`), named `IntegrationTest<DoctypeNameNoSpaces>`.
- API-module tests (testing `requests/utils.py`, not tied to one doctype) live in the app's existing top-level `tests/` folder, matching `upande_dev_tools/tests/test_customization_exporter.py`'s pattern.
- All paths below are relative to the app repo root (`apps/upande_dev_tools/`), i.e. `upande_dev_tools/hooks.py` means `apps/upande_dev_tools/upande_dev_tools/hooks.py`.
- After any task that adds a fixture, custom field, or new doctype, run `bench --site <site> migrate` before running that task's tests — fixtures and `after_migrate` hooks only take effect after a migrate.

## Deviations from the spec's illustrative file tree (decided during planning)

The spec's "Module layout" section sketched an example tree; these are the concrete, corrected choices this plan implements:

1. **No `fixtures/custom_docperm.json`.** `Request` is a doctype we own, so its role grants belong directly in `request.json`'s own `permissions` list, not a `Custom DocPerm` fixture (that mechanism is for customizing permissions on a *foreign* doctype, which we don't do in Phase 1).
2. **Task custom fields ship as code, not a static fixture.** This app's sibling `upande_coffee` already establishes the pattern of an `after_migrate` hook calling `frappe.custom.doctype.custom_field.custom_field.create_custom_fields(...)` — idempotent, re-applies on every migrate, and is the standard Frappe helper for exactly this. This plan follows that precedent (`requests/setup.py`) instead of hand-typing a ~50-key-per-field native customization JSON blob.
3. **No `dashboard_chart/`/`number_card/` in Phase 1.** Those are Desk analytics widgets that Phase 2's real dashboard supersedes; building them now would be thrown away. Phase 1's "usable from the desk" goal is met by the doctype + one workspace with shortcuts.
4. **No `Open` workflow state.** Frappe assigns the *first row* of a Workflow's `states` table as the default state of every newly inserted document (`frappe.model.workflow.validate_workflow`) — so making `Under Review` that first row gives the spec's "automatically, no separate action" behavior for free, without a transient state that would need extra code to skip past.
5. **`Request.priority` options are `Low/Medium/High/Urgent`**, not `Low/Medium/High/Critical` as in the spec's prose — matching Task's own native `priority` field options exactly (`erpnext/projects/doctype/task/task.json`), so the value copies straight across when a Task is created with no translation step. Same scale, aligned vocabulary.
6. **An extra `Reopen` transition** (`Deferred → Under Review`, Projects Manager) so a deferred request isn't a permanent dead end.
7. **The `Dev Team` + `System Manager` dual-role `has_permission` gate described in the spec is not implemented by this plan.** It gates a settings *doctype/page* that doesn't exist until Phase 2 — there is nothing to attach it to yet. This plan only ships the `Dev Team` role itself (Task 2); the `has_permission` hook lands with Phase 2's settings page.
8. **An extra `Promote Note` transition** (`Under Review → Scheduled`, Dev Team, conditioned on `doc.request_type == "Note"`) implements the spec's "Note self-promotion" using the workflow engine's own `condition` field, rather than bypassing the workflow engine in Python — `validate_workflow` runs on every `save()` regardless of `ignore_permissions`, so a hand-rolled bypass would have been rejected by the framework anyway. `promote_to_task` becomes a two-line dispatch instead of two separate code paths.

---

### Task 1: `Requests` module scaffold + the `Request` doctype

**Files:**
- Modify: `upande_dev_tools/modules.txt`
- Create: `upande_dev_tools/requests/__init__.py`
- Create: `upande_dev_tools/requests/doctype/__init__.py`
- Create: `upande_dev_tools/requests/doctype/request/__init__.py`
- Create: `upande_dev_tools/requests/doctype/request/request.json`
- Create: `upande_dev_tools/requests/doctype/request/request.py`
- Test: `upande_dev_tools/requests/doctype/request/test_request.py`

**Interfaces:**
- Produces: doctype `Request` with fields `title`, `request_type` (`Feature`/`Bug`/`Master Data`/`Question`/`Note`), `priority` (`Low`/`Medium`/`High`/`Urgent`), `workflow_state`, `description`, `product_area`, `project` (Link Project), `linked_task` (Link Task), `raised_by_user`/`raised_by_employee`/`raised_by_contact`, `source`, `resolution_notes`. Later tasks add controller logic and API functions on top of this schema — nothing here yet reads or writes those fields programmatically.

- [ ] **Step 1: Add the module**

Append a line to `upande_dev_tools/modules.txt` so it reads:

```
Upande Dev Tools
Requests
```

- [ ] **Step 2: Create the module package**

`upande_dev_tools/requests/__init__.py` — empty file.
`upande_dev_tools/requests/doctype/__init__.py` — empty file.
`upande_dev_tools/requests/doctype/request/__init__.py` — empty file.

- [ ] **Step 3: Write the doctype schema**

`upande_dev_tools/requests/doctype/request/request.json`:

```json
{
 "actions": [],
 "allow_rename": 0,
 "autoname": "REQ-.YYYY.-.#####",
 "creation": "2026-09-13 00:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": [
  "title",
  "request_type",
  "column_break_type",
  "priority",
  "workflow_state",
  "section_break_details",
  "description",
  "product_area",
  "column_break_details2",
  "project",
  "linked_task",
  "section_break_submitter",
  "raised_by_user",
  "raised_by_employee",
  "column_break_submitter2",
  "raised_by_contact",
  "source",
  "section_break_resolution",
  "resolution_notes"
 ],
 "fields": [
  {
   "fieldname": "title",
   "fieldtype": "Data",
   "in_list_view": 1,
   "label": "Title",
   "reqd": 1
  },
  {
   "default": "Feature",
   "fieldname": "request_type",
   "fieldtype": "Select",
   "in_list_view": 1,
   "label": "Type",
   "options": "Feature\nBug\nMaster Data\nQuestion\nNote",
   "reqd": 1
  },
  {
   "fieldname": "column_break_type",
   "fieldtype": "Column Break"
  },
  {
   "fieldname": "priority",
   "fieldtype": "Select",
   "in_list_view": 1,
   "in_standard_filter": 1,
   "label": "Priority",
   "options": "\nLow\nMedium\nHigh\nUrgent"
  },
  {
   "fieldname": "workflow_state",
   "fieldtype": "Select",
   "in_list_view": 1,
   "in_standard_filter": 1,
   "label": "Status",
   "options": "\nUnder Review\nApproved\nRejected\nDeferred\nScheduled\nIn Progress\nCompleted",
   "read_only": 1
  },
  {
   "fieldname": "section_break_details",
   "fieldtype": "Section Break",
   "label": "Details"
  },
  {
   "fieldname": "description",
   "fieldtype": "Text Editor",
   "label": "Description"
  },
  {
   "fieldname": "product_area",
   "fieldtype": "Data",
   "label": "Product Area"
  },
  {
   "fieldname": "column_break_details2",
   "fieldtype": "Column Break"
  },
  {
   "fieldname": "project",
   "fieldtype": "Link",
   "in_standard_filter": 1,
   "label": "Project",
   "options": "Project"
  },
  {
   "fieldname": "linked_task",
   "fieldtype": "Link",
   "label": "Task",
   "options": "Task",
   "read_only": 1
  },
  {
   "fieldname": "section_break_submitter",
   "fieldtype": "Section Break",
   "label": "Submitter"
  },
  {
   "fieldname": "raised_by_user",
   "fieldtype": "Link",
   "label": "Raised By (User)",
   "options": "User",
   "read_only": 1
  },
  {
   "fieldname": "raised_by_employee",
   "fieldtype": "Link",
   "label": "Raised By (Employee)",
   "options": "Employee",
   "read_only": 1
  },
  {
   "fieldname": "column_break_submitter2",
   "fieldtype": "Column Break"
  },
  {
   "fieldname": "raised_by_contact",
   "fieldtype": "Link",
   "label": "Raised By (Contact)",
   "options": "Contact",
   "read_only": 1
  },
  {
   "default": "Desk",
   "fieldname": "source",
   "fieldtype": "Select",
   "label": "Source",
   "options": "Desk\nWeb Portal\nMobile App",
   "read_only": 1
  },
  {
   "fieldname": "section_break_resolution",
   "fieldtype": "Section Break",
   "label": "Resolution"
  },
  {
   "fieldname": "resolution_notes",
   "fieldtype": "Small Text",
   "label": "Resolution Notes"
  }
 ],
 "index_web_pages_for_search": 1,
 "links": [],
 "modified": "2026-09-13 00:00:00.000000",
 "modified_by": "Administrator",
 "module": "Requests",
 "name": "Request",
 "naming_rule": "Expression (old style)",
 "owner": "Administrator",
 "permissions": [
  {
   "create": 1,
   "delete": 1,
   "email": 1,
   "export": 1,
   "print": 1,
   "read": 1,
   "report": 1,
   "role": "System Manager",
   "share": 1,
   "write": 1
  },
  {
   "create": 1,
   "read": 1,
   "report": 1,
   "role": "Dev Team",
   "share": 1,
   "write": 1
  },
  {
   "create": 1,
   "read": 1,
   "report": 1,
   "role": "Projects Manager",
   "share": 1,
   "write": 1
  }
 ],
 "sort_field": "creation",
 "sort_order": "DESC",
 "states": [],
 "title_field": "title",
 "track_changes": 1
}
```

- [ ] **Step 4: Write the minimal controller**

`upande_dev_tools/requests/doctype/request/request.py`:

```python
# Copyright (c) 2026, shadrack@upande.com and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class Request(Document):
	pass
```

- [ ] **Step 5: Write the failing test**

`upande_dev_tools/requests/doctype/request/test_request.py`:

```python
# Copyright (c) 2026, shadrack@upande.com and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = []


class IntegrationTestRequest(IntegrationTestCase):
	def test_can_be_created_with_title_and_type(self) -> None:
		doc = frappe.get_doc(
			{
				"doctype": "Request",
				"title": "Add export button",
				"request_type": "Feature",
			}
		).insert(ignore_permissions=True)
		self.assertTrue(doc.name.startswith("REQ-"))
```

Note: this test does **not** assert `workflow_state == "Under Review"` yet — the Workflow record that assigns that default doesn't exist until Task 2. Without an active Workflow, `workflow_state` is simply left blank on insert, which is correct for this task.

- [ ] **Step 6: Run test to verify it fails**

Run: `bench --site <site> run-tests --app upande_dev_tools --module upande_dev_tools.requests.doctype.request.test_request`
Expected: FAIL — `Request` is not a valid DocType (JSON not yet synced).

- [ ] **Step 7: Sync and re-run**

Run: `bench --site <site> migrate`
Run: `bench --site <site> run-tests --app upande_dev_tools --module upande_dev_tools.requests.doctype.request.test_request`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
ruff format upande_dev_tools/requests/doctype/request/request.py upande_dev_tools/requests/doctype/request/test_request.py
git add upande_dev_tools/modules.txt upande_dev_tools/requests
git commit -m "feat: scaffold Requests module and Request doctype

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Approval workflow (Role, Workflow State, Workflow Action Master, Workflow fixtures)

**Files:**
- Modify: `upande_dev_tools/hooks.py`
- Create: `upande_dev_tools/fixtures/role.json`
- Create: `upande_dev_tools/fixtures/workflow_state.json`
- Create: `upande_dev_tools/fixtures/workflow_action_master.json`
- Create: `upande_dev_tools/fixtures/workflow.json`
- Test: `upande_dev_tools/requests/doctype/request/test_request.py` (extend)

**Interfaces:**
- Produces: an active `Request Review` Workflow on `Request`, states `Under Review` (default) / `Approved` / `Rejected` / `Deferred` / `Scheduled` / `In Progress` / `Completed`, actions `Approve`/`Reject`/`Defer`/`Reopen`/`Schedule`/`Promote Note`/`Start Work`/`Complete`. Role `Dev Team` exists. Later tasks rely on these exact state/action/role names verbatim.

- [ ] **Step 1: Write the failing tests**

Append to `upande_dev_tools/requests/doctype/request/test_request.py`:

```python
	def test_new_request_defaults_to_under_review(self) -> None:
		doc = frappe.get_doc(
			{
				"doctype": "Request",
				"title": "Needs triage",
				"request_type": "Bug",
			}
		).insert(ignore_permissions=True)
		self.assertEqual(doc.workflow_state, "Under Review")

	def test_only_projects_manager_can_approve(self) -> None:
		from frappe.model.workflow import apply_workflow

		if not frappe.db.exists("User", "dev-only@example.test"):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": "dev-only@example.test",
					"first_name": "Dev",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
		user = frappe.get_doc("User", "dev-only@example.test")
		user.add_roles("Dev Team")

		doc = frappe.get_doc(
			{
				"doctype": "Request",
				"title": "Needs triage",
				"request_type": "Bug",
				"project": None,
				"priority": "High",
			}
		).insert(ignore_permissions=True)

		frappe.set_user("dev-only@example.test")
		try:
			with self.assertRaises(frappe.ValidationError):
				apply_workflow(doc, "Approve")
		finally:
			frappe.set_user("Administrator")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `bench --site <site> run-tests --app upande_dev_tools --module upande_dev_tools.requests.doctype.request.test_request`
Expected: FAIL — no active Workflow for `Request`, so `workflow_state` stays blank and `apply_workflow` raises "no workflow found" rather than a permission error.

- [ ] **Step 3: Ship the Role**

`upande_dev_tools/fixtures/role.json`:

```json
[
 {
  "desk_access": 1,
  "disabled": 0,
  "docstatus": 0,
  "doctype": "Role",
  "home_page": null,
  "is_custom": 0,
  "modified": "2026-09-13 00:00:00.000000",
  "modified_by": "Administrator",
  "name": "Dev Team",
  "restrict_to_domain": null,
  "role_name": "Dev Team",
  "two_factor_auth": 0
 }
]
```

- [ ] **Step 4: Ship the Workflow States**

`upande_dev_tools/fixtures/workflow_state.json`:

```json
[
 {
  "docstatus": 0,
  "doctype": "Workflow State",
  "icon": "eye-open",
  "modified": "2026-09-13 00:00:00.000000",
  "name": "Under Review",
  "style": "Warning",
  "workflow_state_name": "Under Review"
 },
 {
  "docstatus": 0,
  "doctype": "Workflow State",
  "icon": "ok",
  "modified": "2026-09-13 00:00:00.000000",
  "name": "Approved",
  "style": "Success",
  "workflow_state_name": "Approved"
 },
 {
  "docstatus": 0,
  "doctype": "Workflow State",
  "icon": "remove",
  "modified": "2026-09-13 00:00:00.000000",
  "name": "Rejected",
  "style": "Danger",
  "workflow_state_name": "Rejected"
 },
 {
  "docstatus": 0,
  "doctype": "Workflow State",
  "icon": "time",
  "modified": "2026-09-13 00:00:00.000000",
  "name": "Deferred",
  "style": "Inverse",
  "workflow_state_name": "Deferred"
 },
 {
  "docstatus": 0,
  "doctype": "Workflow State",
  "icon": "calendar",
  "modified": "2026-09-13 00:00:00.000000",
  "name": "Scheduled",
  "style": "Info",
  "workflow_state_name": "Scheduled"
 },
 {
  "docstatus": 0,
  "doctype": "Workflow State",
  "icon": "cog",
  "modified": "2026-09-13 00:00:00.000000",
  "name": "In Progress",
  "style": "Primary",
  "workflow_state_name": "In Progress"
 },
 {
  "docstatus": 0,
  "doctype": "Workflow State",
  "icon": "ok-circle",
  "modified": "2026-09-13 00:00:00.000000",
  "name": "Completed",
  "style": "Success",
  "workflow_state_name": "Completed"
 }
]
```

- [ ] **Step 5: Ship the Workflow Actions**

`upande_dev_tools/fixtures/workflow_action_master.json`:

```json
[
 {"docstatus": 0, "doctype": "Workflow Action Master", "modified": "2026-09-13 00:00:00.000000", "name": "Approve", "workflow_action_name": "Approve"},
 {"docstatus": 0, "doctype": "Workflow Action Master", "modified": "2026-09-13 00:00:00.000000", "name": "Reject", "workflow_action_name": "Reject"},
 {"docstatus": 0, "doctype": "Workflow Action Master", "modified": "2026-09-13 00:00:00.000000", "name": "Defer", "workflow_action_name": "Defer"},
 {"docstatus": 0, "doctype": "Workflow Action Master", "modified": "2026-09-13 00:00:00.000000", "name": "Reopen", "workflow_action_name": "Reopen"},
 {"docstatus": 0, "doctype": "Workflow Action Master", "modified": "2026-09-13 00:00:00.000000", "name": "Schedule", "workflow_action_name": "Schedule"},
 {"docstatus": 0, "doctype": "Workflow Action Master", "modified": "2026-09-13 00:00:00.000000", "name": "Promote Note", "workflow_action_name": "Promote Note"},
 {"docstatus": 0, "doctype": "Workflow Action Master", "modified": "2026-09-13 00:00:00.000000", "name": "Start Work", "workflow_action_name": "Start Work"},
 {"docstatus": 0, "doctype": "Workflow Action Master", "modified": "2026-09-13 00:00:00.000000", "name": "Complete", "workflow_action_name": "Complete"}
]
```

- [ ] **Step 6: Ship the Workflow**

`upande_dev_tools/fixtures/workflow.json` (note: `Under Review` is listed **first** in `states` — that's what makes it the default initial state):

```json
[
 {
  "docstatus": 0,
  "doctype": "Workflow",
  "document_type": "Request",
  "enable_action_confirmation": 0,
  "is_active": 1,
  "modified": "2026-09-13 00:00:00.000000",
  "name": "Request Review",
  "override_status": 0,
  "send_email_alert": 0,
  "workflow_name": "Request Review",
  "workflow_state_field": "workflow_state",
  "states": [
   {"state": "Under Review", "doc_status": "0", "allow_edit": "Projects Manager", "update_field": null, "update_value": null, "message": null, "next_action_email_template": null, "is_optional_state": 0, "avoid_status_override": 0, "send_email": 0, "evaluate_as_expression": 0, "workflow_builder_id": null},
   {"state": "Approved", "doc_status": "0", "allow_edit": "Projects Manager", "update_field": null, "update_value": null, "message": null, "next_action_email_template": null, "is_optional_state": 0, "avoid_status_override": 0, "send_email": 0, "evaluate_as_expression": 0, "workflow_builder_id": null},
   {"state": "Rejected", "doc_status": "0", "allow_edit": "System Manager", "update_field": null, "update_value": null, "message": null, "next_action_email_template": null, "is_optional_state": 0, "avoid_status_override": 0, "send_email": 0, "evaluate_as_expression": 0, "workflow_builder_id": null},
   {"state": "Deferred", "doc_status": "0", "allow_edit": "Projects Manager", "update_field": null, "update_value": null, "message": null, "next_action_email_template": null, "is_optional_state": 0, "avoid_status_override": 0, "send_email": 0, "evaluate_as_expression": 0, "workflow_builder_id": null},
   {"state": "Scheduled", "doc_status": "0", "allow_edit": "Dev Team", "update_field": null, "update_value": null, "message": null, "next_action_email_template": null, "is_optional_state": 0, "avoid_status_override": 0, "send_email": 0, "evaluate_as_expression": 0, "workflow_builder_id": null},
   {"state": "In Progress", "doc_status": "0", "allow_edit": "Dev Team", "update_field": null, "update_value": null, "message": null, "next_action_email_template": null, "is_optional_state": 0, "avoid_status_override": 0, "send_email": 0, "evaluate_as_expression": 0, "workflow_builder_id": null},
   {"state": "Completed", "doc_status": "0", "allow_edit": "System Manager", "update_field": null, "update_value": null, "message": null, "next_action_email_template": null, "is_optional_state": 0, "avoid_status_override": 0, "send_email": 0, "evaluate_as_expression": 0, "workflow_builder_id": null}
  ],
  "transitions": [
   {"state": "Under Review", "action": "Approve", "next_state": "Approved", "allowed": "Projects Manager", "allow_self_approval": 1, "condition": null, "send_email_to_creator": 0, "transition_tasks": null, "workflow_builder_id": null},
   {"state": "Under Review", "action": "Reject", "next_state": "Rejected", "allowed": "Projects Manager", "allow_self_approval": 1, "condition": null, "send_email_to_creator": 0, "transition_tasks": null, "workflow_builder_id": null},
   {"state": "Under Review", "action": "Defer", "next_state": "Deferred", "allowed": "Projects Manager", "allow_self_approval": 1, "condition": null, "send_email_to_creator": 0, "transition_tasks": null, "workflow_builder_id": null},
   {"state": "Under Review", "action": "Promote Note", "next_state": "Scheduled", "allowed": "Dev Team", "allow_self_approval": 1, "condition": "doc.request_type == \"Note\"", "send_email_to_creator": 0, "transition_tasks": null, "workflow_builder_id": null},
   {"state": "Deferred", "action": "Reopen", "next_state": "Under Review", "allowed": "Projects Manager", "allow_self_approval": 1, "condition": null, "send_email_to_creator": 0, "transition_tasks": null, "workflow_builder_id": null},
   {"state": "Approved", "action": "Schedule", "next_state": "Scheduled", "allowed": "Projects Manager", "allow_self_approval": 1, "condition": null, "send_email_to_creator": 0, "transition_tasks": null, "workflow_builder_id": null},
   {"state": "Scheduled", "action": "Start Work", "next_state": "In Progress", "allowed": "Dev Team", "allow_self_approval": 1, "condition": null, "send_email_to_creator": 0, "transition_tasks": null, "workflow_builder_id": null},
   {"state": "In Progress", "action": "Complete", "next_state": "Completed", "allowed": "Dev Team", "allow_self_approval": 1, "condition": null, "send_email_to_creator": 0, "transition_tasks": null, "workflow_builder_id": null}
  ]
 }
]
```

- [ ] **Step 7: Register the fixtures**

In `upande_dev_tools/hooks.py`, replace the commented-out `# fixtures = [...]` block with:

```python
fixtures = [
	{"doctype": "Role", "filters": [["name", "in", ["Dev Team"]]]},
	{
		"doctype": "Workflow State",
		"filters": [
			[
				"name",
				"in",
				[
					"Under Review",
					"Approved",
					"Rejected",
					"Deferred",
					"Scheduled",
					"In Progress",
					"Completed",
				],
			]
		],
	},
	{
		"doctype": "Workflow Action Master",
		"filters": [
			[
				"name",
				"in",
				[
					"Approve",
					"Reject",
					"Defer",
					"Reopen",
					"Schedule",
					"Promote Note",
					"Start Work",
					"Complete",
				],
			]
		],
	},
	{"doctype": "Workflow", "filters": [["name", "in", ["Request Review"]]]},
]
```

- [ ] **Step 8: Migrate and run tests**

Run: `bench --site <site> migrate`
Run: `bench --site <site> run-tests --app upande_dev_tools --module upande_dev_tools.requests.doctype.request.test_request`
Expected: PASS — the second test now correctly gets a `WorkflowPermissionError` (a `frappe.ValidationError` subclass) because `dev-only@example.test` only holds `Dev Team`, not `Projects Manager`.

- [ ] **Step 9: Commit**

```bash
git add upande_dev_tools/hooks.py upande_dev_tools/fixtures upande_dev_tools/requests/doctype/request/test_request.py
git commit -m "feat: ship Request approval workflow and Dev Team role

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Task custom fields (`custom_request`, `custom_planned_for`)

**Files:**
- Create: `upande_dev_tools/requests/setup.py`
- Modify: `upande_dev_tools/hooks.py`
- Test: `upande_dev_tools/tests/test_requests_api.py`

**Interfaces:**
- Produces: `Task.custom_request` (Link → Request, read-only) and `Task.custom_planned_for` (Date). Task 4's `on_update` sets `custom_request`; Phase 2/3's "my day" queries filter on `custom_planned_for`.

- [ ] **Step 1: Write the failing test**

`upande_dev_tools/tests/test_requests_api.py`:

```python
# Copyright (c) 2026, shadrack@upande.com and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase


class IntegrationTestRequestsApi(IntegrationTestCase):
	def test_task_has_request_custom_fields(self) -> None:
		meta = frappe.get_meta("Task")
		self.assertTrue(meta.has_field("custom_request"))
		self.assertTrue(meta.has_field("custom_planned_for"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site <site> run-tests --app upande_dev_tools --module upande_dev_tools.tests.test_requests_api`
Expected: FAIL — `Task` has no such fields yet.

- [ ] **Step 3: Write the setup module**

`upande_dev_tools/requests/setup.py`:

```python
# Copyright (c) 2026, shadrack@upande.com and contributors
# For license information, please see license.txt

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
```

- [ ] **Step 4: Wire it into `after_migrate`**

In `upande_dev_tools/hooks.py`, add (near the other commented install hooks):

```python
after_migrate = "upande_dev_tools.requests.setup.create_task_custom_fields"
```

- [ ] **Step 5: Migrate and run the test**

Run: `bench --site <site> migrate`
Run: `bench --site <site> run-tests --app upande_dev_tools --module upande_dev_tools.tests.test_requests_api`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
ruff format upande_dev_tools/requests/setup.py
git add upande_dev_tools/requests/setup.py upande_dev_tools/hooks.py upande_dev_tools/tests/test_requests_api.py
git commit -m "feat: ship Task.custom_request and Task.custom_planned_for

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Request controller — submitter resolution, approval guard, auto-created Task

**Files:**
- Modify: `upande_dev_tools/requests/doctype/request/request.py`
- Test: `upande_dev_tools/requests/doctype/request/test_request.py` (extend)

**Interfaces:**
- Consumes: `Task.custom_request`/`custom_planned_for` (Task 3); Workflow states `Approved`/`Scheduled` (Task 2).
- Produces: on any new `Request`, `raised_by_user`/`raised_by_employee`/`raised_by_contact` are auto-resolved; approving without `project`+`priority` raises `frappe.ValidationError`; creating a `Note` without the `Dev Team` role raises `frappe.ValidationError`; reaching `Scheduled` creates/links a `Task` and sets `linked_task`. Task 6's `promote_to_task` relies on this last behavior.

- [ ] **Step 1: Write the failing tests**

Append to `upande_dev_tools/requests/doctype/request/test_request.py`:

```python
	def _make_project(self) -> str:
		name = "Requests Phase 1 Test Project"
		if frappe.db.exists("Project", name):
			return name
		return frappe.get_doc({"doctype": "Project", "project_name": name}).insert(
			ignore_permissions=True
		).name

	def test_raised_by_user_defaults_to_session_user(self) -> None:
		if not frappe.db.exists("User", "dev-note@example.test"):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": "dev-note@example.test",
					"first_name": "Dev",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
		frappe.get_doc("User", "dev-note@example.test").add_roles("Dev Team")

		frappe.set_user("dev-note@example.test")
		try:
			doc = frappe.get_doc(
				{"doctype": "Request", "title": "Quick note", "request_type": "Note"}
			).insert(ignore_permissions=True)
			self.assertEqual(doc.raised_by_user, "dev-note@example.test")
		finally:
			frappe.set_user("Administrator")

	def test_note_requires_dev_team_role(self) -> None:
		if not frappe.db.exists("User", "no-dev-role@example.test"):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": "no-dev-role@example.test",
					"first_name": "NoRole",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)

		frappe.set_user("no-dev-role@example.test")
		try:
			with self.assertRaises(frappe.ValidationError):
				frappe.get_doc(
					{"doctype": "Request", "title": "Not allowed", "request_type": "Note"}
				).insert(ignore_permissions=True)
		finally:
			frappe.set_user("Administrator")

	def test_approve_requires_project_and_priority(self) -> None:
		doc = frappe.get_doc(
			{"doctype": "Request", "title": "Needs triage", "request_type": "Bug"}
		).insert(ignore_permissions=True)
		doc.workflow_state = "Approved"
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

	def test_scheduling_creates_linked_task(self) -> None:
		project = self._make_project()
		doc = frappe.get_doc(
			{
				"doctype": "Request",
				"title": "Ship the button",
				"request_type": "Feature",
				"project": project,
				"priority": "High",
			}
		).insert(ignore_permissions=True)
		doc.workflow_state = "Approved"
		doc.save(ignore_permissions=True)
		doc.workflow_state = "Scheduled"
		doc.save(ignore_permissions=True)

		self.assertTrue(doc.linked_task)
		task = frappe.get_doc("Task", doc.linked_task)
		self.assertEqual(task.custom_request, doc.name)
		self.assertEqual(task.subject, doc.title)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `bench --site <site> run-tests --app upande_dev_tools --module upande_dev_tools.requests.doctype.request.test_request`
Expected: FAIL — none of this logic exists in the controller yet.

- [ ] **Step 3: Implement the controller**

`upande_dev_tools/requests/doctype/request/request.py`:

```python
# Copyright (c) 2026, shadrack@upande.com and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.contacts.doctype.contact.contact import get_contact_name
from frappe.model.document import Document


class Request(Document):
	def before_insert(self) -> None:
		self.raised_by_user = self.raised_by_user or frappe.session.user
		if not self.raised_by_employee:
			self.raised_by_employee = frappe.db.get_value(
				"Employee", {"user_id": self.raised_by_user}, "name"
			)
		if not self.raised_by_contact:
			self.raised_by_contact = get_contact_name(self.raised_by_user)

	def validate(self) -> None:
		if self.is_new() and self.request_type == "Note" and "Dev Team" not in frappe.get_roles():
			frappe.throw(_("Only Dev Team members can raise a Note."))

		if self.workflow_state == "Approved" and not (self.project and self.priority):
			frappe.throw(_("Set Project and Priority before approving a request."))

	def on_update(self) -> None:
		if (
			self.workflow_state == "Scheduled"
			and self.has_value_changed("workflow_state")
			and not self.linked_task
		):
			task = frappe.get_doc(
				{
					"doctype": "Task",
					"subject": self.title,
					"description": self.description,
					"project": self.project,
					"priority": self.priority,
					"custom_request": self.name,
				}
			)
			task.insert(ignore_permissions=True)
			self.db_set("linked_task", task.name, update_modified=False)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `bench --site <site> run-tests --app upande_dev_tools --module upande_dev_tools.requests.doctype.request.test_request`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
ruff format upande_dev_tools/requests/doctype/request/request.py
git add upande_dev_tools/requests/doctype/request
git commit -m "feat: resolve request submitter and auto-create Task on Schedule

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: Create/list API — `create_request`, `get_my_requests`, `get_review_queue`

**Files:**
- Create: `upande_dev_tools/requests/utils.py`
- Test: `upande_dev_tools/tests/test_requests_api.py` (extend)

**Interfaces:**
- Consumes: `Request` doctype (Task 1), submitter auto-resolution and Note guard (Task 4).
- Produces: `create_request(title, request_type, description=None, product_area=None, project=None, source="Desk") -> dict`, `get_my_requests(status=None) -> list[dict]`, `get_review_queue() -> list[dict]`. Task 6 imports `create_request`'s output shape (a dict with `name`).

- [ ] **Step 1: Write the failing tests**

Change the top-level import line in `upande_dev_tools/tests/test_requests_api.py` from a bare `import frappe` / `IntegrationTestCase` pair to also pull in the new functions:

```python
from upande_dev_tools.requests.utils import create_request, get_my_requests, get_review_queue
```

Then add the following as new **methods inside the existing `IntegrationTestRequestsApi` class** (the one Task 3 created, holding `test_task_has_request_custom_fields`) — do not declare the class again, just extend its body:

```python
	def _make_user(self, email: str, roles: list[str]) -> str:
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Test", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		user = frappe.get_doc("User", email)
		if roles:
			user.add_roles(*roles)
		return email

	def test_create_request_rejects_note_from_non_dev(self) -> None:
		pm = self._make_user("pm-create@example.test", ["Projects Manager"])
		frappe.set_user(pm)
		try:
			with self.assertRaises(frappe.ValidationError):
				create_request(title="sneaky note", request_type="Note")
		finally:
			frappe.set_user("Administrator")

	def test_get_my_requests_scopes_to_caller(self) -> None:
		dev = self._make_user("dev-scope@example.test", ["Dev Team"])
		other = self._make_user("other-scope@example.test", ["Dev Team"])

		frappe.set_user(dev)
		created = create_request(title="My own request", request_type="Bug")
		frappe.set_user(other)
		create_request(title="Someone else's request", request_type="Bug")

		frappe.set_user(dev)
		try:
			mine = get_my_requests()
		finally:
			frappe.set_user("Administrator")
		self.assertEqual([r["name"] for r in mine], [created["name"]])

	def test_get_review_queue_requires_reviewer_role(self) -> None:
		outsider = self._make_user("outsider-queue@example.test", [])
		frappe.set_user(outsider)
		try:
			with self.assertRaises(frappe.PermissionError):
				get_review_queue()
		finally:
			frappe.set_user("Administrator")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `bench --site <site> run-tests --app upande_dev_tools --module upande_dev_tools.tests.test_requests_api`
Expected: FAIL — `upande_dev_tools.requests.utils` doesn't exist yet.

- [ ] **Step 3: Implement the API module**

`upande_dev_tools/requests/utils.py`:

```python
# Copyright (c) 2026, shadrack@upande.com and contributors
# For license information, please see license.txt

import frappe
from frappe import _

REVIEWER_ROLES = {"Dev Team", "Projects Manager", "System Manager"}


@frappe.whitelist()
def create_request(
	title: str,
	request_type: str,
	description: str | None = None,
	product_area: str | None = None,
	project: str | None = None,
	source: str = "Desk",
) -> dict:
	doc = frappe.get_doc(
		{
			"doctype": "Request",
			"title": title,
			"request_type": request_type,
			"description": description,
			"product_area": product_area,
			"project": project,
			"source": source,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.as_dict()


@frappe.whitelist()
def get_my_requests(status: str | None = None) -> list[dict]:
	filters: dict[str, str] = {"raised_by_user": frappe.session.user}
	if status:
		filters["workflow_state"] = status

	return frappe.get_all(
		"Request",
		filters=filters,
		fields=[
			"name",
			"title",
			"request_type",
			"workflow_state",
			"priority",
			"project",
			"linked_task",
			"creation",
		],
		order_by="creation desc",
		ignore_permissions=True,
	)


@frappe.whitelist()
def get_review_queue() -> list[dict]:
	if not set(frappe.get_roles()) & REVIEWER_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	return frappe.get_all(
		"Request",
		filters={"workflow_state": "Under Review"},
		fields=["name", "title", "request_type", "product_area", "project", "raised_by_user", "creation"],
		order_by="creation asc",
		ignore_permissions=True,
	)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `bench --site <site> run-tests --app upande_dev_tools --module upande_dev_tools.tests.test_requests_api`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
ruff format upande_dev_tools/requests/utils.py
git add upande_dev_tools/requests/utils.py upande_dev_tools/tests/test_requests_api.py
git commit -m "feat: add create_request/get_my_requests/get_review_queue API

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: Triage & promotion API — `triage_request`, `promote_to_task`

**Files:**
- Modify: `upande_dev_tools/requests/utils.py`
- Test: `upande_dev_tools/tests/test_requests_api.py` (extend)

**Interfaces:**
- Consumes: `create_request` (Task 5); Workflow transitions `Approve`/`Reject`/`Defer`/`Reopen`/`Schedule`/`Promote Note`/`Start Work`/`Complete` (Task 2); the `on_update` auto-Task-creation (Task 4).
- Produces: `triage_request(name, action, project=None, priority=None) -> dict`, `promote_to_task(name) -> dict`. Task 7/8 don't depend on these directly, but Phase 2/3 will call them for every workflow action a human takes.

- [ ] **Step 1: Write the failing tests**

Widen the import line at the top of `upande_dev_tools/tests/test_requests_api.py` (added in Task 5) to also pull in `promote_to_task`/`triage_request`:

```python
from upande_dev_tools.requests.utils import (
	create_request,
	get_my_requests,
	get_review_queue,
	promote_to_task,
	triage_request,
)
```

Then add the following as new methods inside the existing `IntegrationTestRequestsApi` class:

```python
	def test_triage_and_promote_normal_request(self) -> None:
		dev = self._make_user("dev-triage@example.test", ["Dev Team"])
		pm = self._make_user("pm-triage@example.test", ["Projects Manager"])
		project = self._make_project()

		frappe.set_user(dev)
		created = create_request(title="Add CSV export", request_type="Feature", project=project)

		frappe.set_user(pm)
		triage_request(created["name"], "Approve", priority="High")
		promote_to_task(created["name"])
		frappe.set_user("Administrator")

		doc = frappe.get_doc("Request", created["name"])
		self.assertEqual(doc.workflow_state, "Scheduled")
		self.assertTrue(doc.linked_task)

	def test_promote_to_task_lets_dev_team_self_promote_a_note(self) -> None:
		dev = self._make_user("dev-note-promote@example.test", ["Dev Team"])
		frappe.set_user(dev)
		created = create_request(title="Remember to refactor this", request_type="Note")
		promote_to_task(created["name"])
		frappe.set_user("Administrator")

		doc = frappe.get_doc("Request", created["name"])
		self.assertEqual(doc.workflow_state, "Scheduled")

	def test_dev_team_can_start_and_complete_scheduled_request(self) -> None:
		dev = self._make_user("dev-lifecycle@example.test", ["Dev Team"])
		pm = self._make_user("pm-lifecycle@example.test", ["Projects Manager"])
		project = self._make_project()

		frappe.set_user(pm)
		created = create_request(title="Small fix", request_type="Bug", project=project)
		triage_request(created["name"], "Approve", priority="Low")
		promote_to_task(created["name"])

		frappe.set_user(dev)
		triage_request(created["name"], "Start Work")
		triage_request(created["name"], "Complete")
		frappe.set_user("Administrator")

		doc = frappe.get_doc("Request", created["name"])
		self.assertEqual(doc.workflow_state, "Completed")
```

You'll also need the `_make_project` helper on this class — it's identical to the one on `IntegrationTestRequest` in Task 4; copy it in (both classes create the same fixture-style test project, and there is no shared test-utilities module in this app to import it from, matching the existing pattern of small, self-contained test files):

```python
	def _make_project(self) -> str:
		name = "Requests Phase 1 Test Project"
		if frappe.db.exists("Project", name):
			return name
		return frappe.get_doc({"doctype": "Project", "project_name": name}).insert(
			ignore_permissions=True
		).name
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `bench --site <site> run-tests --app upande_dev_tools --module upande_dev_tools.tests.test_requests_api`
Expected: FAIL — `triage_request`/`promote_to_task` don't exist yet.

- [ ] **Step 3: Implement**

Append to `upande_dev_tools/requests/utils.py`:

```python
@frappe.whitelist()
def triage_request(
	name: str,
	action: str,
	project: str | None = None,
	priority: str | None = None,
) -> dict:
	from frappe.model.workflow import apply_workflow

	doc = frappe.get_doc("Request", name)
	if project:
		doc.project = project
	if priority:
		doc.priority = priority
	if project or priority:
		doc.save()

	updated = apply_workflow(doc, action)
	return updated.as_dict()


@frappe.whitelist()
def promote_to_task(name: str) -> dict:
	from frappe.model.workflow import apply_workflow

	doc = frappe.get_doc("Request", name)
	action = "Promote Note" if doc.request_type == "Note" else "Schedule"
	updated = apply_workflow(doc, action)
	return updated.as_dict()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `bench --site <site> run-tests --app upande_dev_tools --module upande_dev_tools.tests.test_requests_api`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
ruff format upande_dev_tools/requests/utils.py
git add upande_dev_tools/requests/utils.py upande_dev_tools/tests/test_requests_api.py
git commit -m "feat: add triage_request/promote_to_task API

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 7: Backlog board API — `get_backlog_board`

**Files:**
- Modify: `upande_dev_tools/requests/utils.py`
- Test: `upande_dev_tools/tests/test_requests_api.py` (extend)

**Interfaces:**
- Consumes: `create_request` (Task 5); `custom_planned_for` field (Task 3).
- Produces: `get_backlog_board(project=None) -> dict` returning `{"tasks": [...], "requests": [...]}`. This is the data source Phase 2's dashboards call directly.

- [ ] **Step 1: Write the failing tests**

Append to `upande_dev_tools/tests/test_requests_api.py` (add `get_backlog_board` to the import line from Task 6, and add these methods):

```python
	def test_get_backlog_board_returns_requests_for_project(self) -> None:
		project = self._make_project()
		created = create_request(title="Board item", request_type="Feature", project=project)

		board = get_backlog_board(project=project)
		self.assertIn(created["name"], [r["name"] for r in board["requests"]])

	def test_get_backlog_board_denies_outsider_without_project(self) -> None:
		outsider = self._make_user("outsider-board@example.test", [])
		frappe.set_user(outsider)
		try:
			with self.assertRaises(frappe.PermissionError):
				get_backlog_board()
		finally:
			frappe.set_user("Administrator")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `bench --site <site> run-tests --app upande_dev_tools --module upande_dev_tools.tests.test_requests_api`
Expected: FAIL — `get_backlog_board` doesn't exist yet.

- [ ] **Step 3: Implement**

Append to `upande_dev_tools/requests/utils.py`:

```python
@frappe.whitelist()
def get_backlog_board(project: str | None = None) -> dict:
	if project:
		if not frappe.has_permission("Project", "read", project):
			frappe.throw(_("Not permitted to view this project."), frappe.PermissionError)
	elif not set(frappe.get_roles()) & REVIEWER_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	filters: dict[str, str] = {"project": project} if project else {}

	tasks = frappe.get_all(
		"Task",
		filters=filters,
		fields=[
			"name",
			"subject",
			"status",
			"priority",
			"project",
			"custom_request",
			"custom_planned_for",
			"exp_end_date",
		],
		order_by="priority desc, exp_end_date asc",
		ignore_permissions=True,
	)
	requests = frappe.get_all(
		"Request",
		filters=filters,
		fields=["name", "title", "request_type", "workflow_state", "priority", "project", "linked_task"],
		ignore_permissions=True,
	)
	return {"tasks": tasks, "requests": requests}
```

Note: customer-to-project visibility (whether a specific customer's portal user has native `read` on their own `Project`) is a portal/permission concern that Phase 2 will need to verify against this site's actual `Project` permission setup — `frappe.has_permission` is the correct, standard check and is wired in now, but Phase 1 doesn't attempt to grant customers `Project` read access itself (that's out of scope per the spec).

- [ ] **Step 4: Run tests to verify they pass**

Run: `bench --site <site> run-tests --app upande_dev_tools --module upande_dev_tools.tests.test_requests_api`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
ruff format upande_dev_tools/requests/utils.py
git add upande_dev_tools/requests/utils.py upande_dev_tools/tests/test_requests_api.py
git commit -m "feat: add get_backlog_board API

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 8: Calendar API — `get_upcoming_meetings`, `get_my_day`

**Files:**
- Modify: `upande_dev_tools/requests/utils.py`
- Test: `upande_dev_tools/tests/test_requests_api.py` (extend)

**Interfaces:**
- Consumes: `custom_planned_for` (Task 3); native Frappe `Event`/`Event Participants`/`Dynamic Link`.
- Produces: `get_upcoming_meetings(project=None, for_user=None, within_days=14) -> list[dict]`, `get_my_day(user=None) -> dict` returning `{"date": ..., "tasks": [...], "meetings": [...]}`. This is what Phase 2's dashboard and Phase 3's mobile home screen both call.

- [ ] **Step 1: Write the failing tests**

Append to `upande_dev_tools/tests/test_requests_api.py` (add `get_my_day`, `get_upcoming_meetings` to the Task 6 import line, and add `from frappe.desk.form.assign_to import add as add_assignment` and `from frappe.utils import add_to_date, now_datetime, today` at the top):

```python
	def test_get_upcoming_meetings_by_project(self) -> None:
		project = self._make_project()
		event = frappe.get_doc(
			{
				"doctype": "Event",
				"subject": "Sprint planning",
				"starts_on": add_to_date(now_datetime(), hours=2),
				"ends_on": add_to_date(now_datetime(), hours=3),
			}
		)
		event.append("links", {"link_doctype": "Project", "link_name": project})
		event.insert(ignore_permissions=True)

		meetings = get_upcoming_meetings(project=project)
		self.assertIn(event.name, [m["name"] for m in meetings])

	def test_get_my_day_returns_assigned_planned_task_and_events(self) -> None:
		dev = self._make_user("dev-myday@example.test", ["Dev Team"])
		project = self._make_project()

		task = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": "Fix login bug",
				"project": project,
				"custom_planned_for": today(),
			}
		).insert(ignore_permissions=True)
		add_assignment({"doctype": "Task", "name": task.name, "assign_to": [dev]})

		event = frappe.get_doc(
			{
				"doctype": "Event",
				"subject": "Standup",
				"starts_on": add_to_date(now_datetime(), hours=1),
				"ends_on": add_to_date(now_datetime(), hours=1, minutes=15),
			}
		)
		event.append("event_participants", {"email": dev})
		event.insert(ignore_permissions=True)

		frappe.set_user(dev)
		try:
			day = get_my_day()
		finally:
			frappe.set_user("Administrator")

		self.assertEqual([t["name"] for t in day["tasks"]], [task.name])
		self.assertIn(event.name, [m["name"] for m in day["meetings"]])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `bench --site <site> run-tests --app upande_dev_tools --module upande_dev_tools.tests.test_requests_api`
Expected: FAIL — `get_upcoming_meetings`/`get_my_day` don't exist yet.

- [ ] **Step 3: Implement**

Append to `upande_dev_tools/requests/utils.py`:

```python
@frappe.whitelist()
def get_upcoming_meetings(
	project: str | None = None,
	for_user: str | None = None,
	within_days: int = 14,
) -> list[dict]:
	from frappe.utils import add_to_date, now_datetime

	if project:
		event_names = frappe.get_all(
			"Dynamic Link",
			filters={"parenttype": "Event", "link_doctype": "Project", "link_name": project},
			pluck="parent",
		)
	else:
		user = for_user or frappe.session.user
		event_names = frappe.get_all(
			"Event Participants",
			filters={"parenttype": "Event", "email": user},
			pluck="parent",
		)

	if not event_names:
		return []

	now = now_datetime()
	end = add_to_date(now, days=within_days)
	return frappe.get_all(
		"Event",
		filters=[
			["name", "in", event_names],
			["starts_on", ">=", now],
			["starts_on", "<=", end],
		],
		fields=["name", "subject", "starts_on", "ends_on", "event_category", "location"],
		order_by="starts_on asc",
		ignore_permissions=True,
	)


@frappe.whitelist()
def get_my_day(user: str | None = None) -> dict:
	from frappe.utils import today

	user = user or frappe.session.user
	day = today()

	tasks = frappe.get_all(
		"Task",
		filters=[
			["_assign", "like", f"%{user}%"],
			["custom_planned_for", "=", day],
		],
		fields=["name", "subject", "status", "priority", "project", "custom_request", "exp_end_date"],
		order_by="priority desc",
		ignore_permissions=True,
	)
	meetings = get_upcoming_meetings(for_user=user, within_days=1)
	return {"date": day, "tasks": tasks, "meetings": meetings}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `bench --site <site> run-tests --app upande_dev_tools --module upande_dev_tools.tests.test_requests_api`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
ruff format upande_dev_tools/requests/utils.py
git add upande_dev_tools/requests/utils.py upande_dev_tools/tests/test_requests_api.py
git commit -m "feat: add get_upcoming_meetings/get_my_day calendar API

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 9: Requests workspace (desk usability)

**Files:**
- Create: `upande_dev_tools/requests/workspace/requests/requests.json`

**Interfaces:**
- Consumes: `Request` doctype (Task 1).
- Produces: a "Requests" entry in the desk sidebar with a shortcut into the `Request` list — nothing else depends on this file.

- [ ] **Step 1: Write the workspace**

`upande_dev_tools/requests/workspace/requests/requests.json`:

```json
{
 "charts": [],
 "content": "[{\"id\":\"reqs-header\",\"type\":\"header\",\"data\":{\"text\":\"<span class=\\\"h4\\\"><b>Requests</b></span>\",\"col\":12}},{\"id\":\"reqs-shortcut\",\"type\":\"shortcut\",\"data\":{\"shortcut_name\":\"Requests\",\"col\":3}},{\"id\":\"reqs-queue-shortcut\",\"type\":\"shortcut\",\"data\":{\"shortcut_name\":\"Review Queue\",\"col\":3}}]",
 "creation": "2026-09-13 00:00:00.000000",
 "custom_blocks": [],
 "docstatus": 0,
 "doctype": "Workspace",
 "hide_custom": 0,
 "idx": 0,
 "indicator_color": "blue",
 "is_hidden": 0,
 "label": "Requests",
 "link_type": "DocType",
 "links": [],
 "modified": "2026-09-13 00:00:00.000000",
 "modified_by": "Administrator",
 "module": "Requests",
 "name": "Requests",
 "number_cards": [],
 "owner": "Administrator",
 "public": 1,
 "quick_lists": [],
 "roles": [],
 "sequence_id": 1.0,
 "shortcuts": [
  {
   "color": "Grey",
   "doc_view": "List",
   "label": "Requests",
   "link_to": "Request",
   "stats_filter": "[]",
   "type": "DocType"
  },
  {
   "color": "Grey",
   "doc_view": "List",
   "label": "Review Queue",
   "link_to": "Request",
   "stats_filter": "[[\"Request\", \"workflow_state\", \"=\", \"Under Review\"]]",
   "type": "DocType"
  }
 ],
 "title": "Requests",
 "type": "Workspace"
}
```

- [ ] **Step 2: Migrate and verify**

Run: `bench --site <site> migrate`

Verify by loading the desk (`/app/requests`) and confirming the "Requests" workspace appears with both shortcuts working — this is a visual/manual check, not a pytest, since a Workspace record has no behavior to unit test beyond "the JSON is valid and syncs," which `bench migrate` already proves by not erroring.

- [ ] **Step 3: Commit**

```bash
git add upande_dev_tools/requests/workspace
git commit -m "feat: add Requests workspace

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Phase 1 acceptance check

After Task 9, run the full suite once to confirm nothing regressed:

```bash
bench --site <site> run-tests --app upande_dev_tools
```

Expected: all tests pass, including the pre-existing `test_customization_exporter.py` and `test_module_version_check.py`/etc. suites untouched by this plan.

At this point: a Projects Manager can review and approve/reject/defer a request from the desk; a developer can raise a Note and self-promote it; approving+scheduling a request creates a linked Task; and every capability is also reachable headlessly via `upande_dev_tools.requests.utils.*` over `/api/method/...` — ready for Phase 2 (portal) and Phase 3 (mobile) to build on without touching this layer again.
