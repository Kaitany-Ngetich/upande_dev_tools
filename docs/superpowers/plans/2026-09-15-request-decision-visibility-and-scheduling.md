# Request Decision Visibility & Scheduling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Request decisions (approve/reject/defer/schedule) and their scheduling data visible and durable, across the customer portal, PM dashboard, Review Queue, and Backlog Board.

**Architecture:** A new `Request Update` doctype becomes the audit trail for every decision note (customer-visible or internal); two new plain fields on `Request` (`scheduled_date`, `deferred_until`) carry PM-committed dates independent of any transition; five backend API methods (three new, two extended) expose this; four frontend surfaces (Review Queue, Backlog Board, PM Dashboard, customer portal) consume it.

**Tech Stack:** Frappe/Python backend (`upande_dev_tools` app), vanilla JS frontend (`public/js/*.js`, no framework), Frappe's own testing framework (`IntegrationTestCase`).

**Spec:** `docs/specs/2026-09-15-request-decision-visibility-and-scheduling-design.md`

## Global Constraints

- `Request` is a first-party doctype of this app (`upande_dev_tools/upande_dev_tools/doctype/request/request.json`) — schema changes go directly into that JSON's `fields`/`field_order`, NOT through `create_custom_fields` (that mechanism is only for extending doctypes this app doesn't own, like `Task`/`Issue` — see `upande_dev_tools/setup.py`'s `TASK_CUSTOM_FIELDS`).
- Every new/changed whitelisted method lives in `upande_dev_tools/api/requests.py` unless stated otherwise, and reuses the existing `REVIEWER_ROLES = {"Dev Team", "Projects Manager", "System Manager"}` constant already defined there for the PM+Dev-Team permission boundary this spec calls for.
- `resolution_notes` (Small Text, on `Request`) is being removed. A `pre_model_sync` patch (see `upande_dev_tools/patches.txt`'s existing `[pre_model_sync]` section and `upande_dev_tools/patches/rename_workspace_to_dev_tools.py` for the file pattern this app already uses) must copy any existing non-empty value into a synthesized `Request Update` row BEFORE the doctype JSON change removes the column — patches in that section run before schema migration, exactly for this reason.
- **Corrected scope note, found while planning:** the design's "priority cards click through to a filtered list, matching the existing 'What people asked for'/'Who is carrying what' cards" is not accurate — investigation during planning (not present in the original design work) found NEITHER existing card is actually clickable; `pm-dashboard.js` has no per-card navigation at all today, only toolbar buttons (`root.on("click", ".pm-reload"...)` etc.). The customer portal's own `rp_card` function, however, already links each request card straight to the desk's native record view (`<a href="/app/request/${name}">`), which is this codebase's one existing "click through to Frappe's own UI" convention. Task 8 below builds the priority card's click-through the same way — a plain link to the desk's native List View for `Request`, filtered by priority via query string (`/app/request?priority=Urgent`) — rather than inventing new portal-side filtered-list UI, since no such component exists to reuse and building one would be well beyond this sub-project's scope.
- `Request.priority` is a Link to `Priority Level`, not a Select — its values are whatever `Priority Level` records exist, but `public/js/review-queue.js` already hardcodes `const PRIORITIES = ["Low", "Medium", "High", "Urgent"]` for its own dropdown; reuse that same list (don't query `Priority Level` dynamically) for consistency with the rest of this app's existing UI.
- All new/changed whitelisted methods use `ignore_permissions=True` internally after their own explicit role check, matching every existing method in `api/requests.py` (Frappe's own doctype-level permissions are not relied on for these bespoke, role-checked API surfaces).
- **Known dependency, not to be worked around:** `upande_dev_tools/tests/test_requests_api.py` has a live, in-progress git rebase conflict (owned by a different, separate development effort) as of this plan's writing. Task 5 and Task 12 below add tests to that exact file. Before starting either task, confirm `git status` no longer shows `upande_dev_tools/tests/test_requests_api.py` as unmerged (`UU`) — if it still does, stop and report back rather than editing a conflicted file.

---

### Task 1: `Request Update` doctype

**Files:**
- Create: `upande_dev_tools/upande_dev_tools/doctype/request_update/request_update.json`
- Create: `upande_dev_tools/upande_dev_tools/doctype/request_update/request_update.py`
- Create: `upande_dev_tools/upande_dev_tools/doctype/request_update/__init__.py`
- Test: `upande_dev_tools/upande_dev_tools/doctype/request_update/test_request_update.py`

**Interfaces:**
- Consumes: nothing from a prior task.
- Produces: the `Request Update` doctype with fields `request` (Link → Request), `action` (Data),
  `from_state` (Data), `to_state` (Data), `note` (Text), `visible_to_customer` (Check), `actor`
  (Link → User, read-only, auto-set) — consumed by Task 3 (`add_request_note`/
  `get_request_updates`).

- [ ] **Step 1: Create the doctype files**

`upande_dev_tools/upande_dev_tools/doctype/request_update/__init__.py`:
```python
```
(empty file, matching every other doctype folder's `__init__.py` in this app)

`upande_dev_tools/upande_dev_tools/doctype/request_update/request_update.json`:
```json
{
 "actions": [],
 "allow_rename": 0,
 "autoname": "hash",
 "creation": "2026-09-15 00:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": [
  "request",
  "action",
  "from_state",
  "to_state",
  "note",
  "visible_to_customer",
  "actor"
 ],
 "fields": [
  {
   "fieldname": "request",
   "fieldtype": "Link",
   "in_list_view": 1,
   "label": "Request",
   "options": "Request",
   "reqd": 1
  },
  {
   "fieldname": "action",
   "fieldtype": "Data",
   "in_list_view": 1,
   "label": "Action"
  },
  {
   "fieldname": "from_state",
   "fieldtype": "Data",
   "label": "From State"
  },
  {
   "fieldname": "to_state",
   "fieldtype": "Data",
   "label": "To State"
  },
  {
   "fieldname": "note",
   "fieldtype": "Text",
   "label": "Note"
  },
  {
   "default": "0",
   "fieldname": "visible_to_customer",
   "fieldtype": "Check",
   "in_list_view": 1,
   "label": "Visible To Customer"
  },
  {
   "fieldname": "actor",
   "fieldtype": "Link",
   "label": "Actor",
   "options": "User",
   "read_only": 1
  }
 ],
 "index_web_pages_for_search": 1,
 "links": [],
 "modified": "2026-09-15 00:00:00.000000",
 "modified_by": "Administrator",
 "module": "Upande Dev Tools",
 "name": "Request Update",
 "naming_rule": "Random",
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
 "sort_order": "ASC",
 "states": [],
 "track_changes": 0
}
```

`upande_dev_tools/upande_dev_tools/doctype/request_update/request_update.py`:
```python
# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class RequestUpdate(Document):
	def before_insert(self) -> None:
		self.actor = self.actor or frappe.session.user
```

- [ ] **Step 2: Write the doctype test**

`upande_dev_tools/upande_dev_tools/doctype/request_update/test_request_update.py`:
```python
# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase


class IntegrationTestRequestUpdate(IntegrationTestCase):
	def _make_request(self) -> str:
		return frappe.get_doc(
			{"doctype": "Request", "title": "Needs a note", "request_type": "Bug"}
		).insert(ignore_permissions=True).name

	def test_actor_defaults_to_session_user(self) -> None:
		request_name = self._make_request()
		doc = frappe.get_doc(
			{"doctype": "Request Update", "request": request_name, "note": "Looking into it."}
		).insert(ignore_permissions=True)
		self.assertEqual(doc.actor, frappe.session.user)

	def test_requires_a_request_link(self) -> None:
		with self.assertRaises(frappe.MandatoryError):
			frappe.get_doc({"doctype": "Request Update", "note": "Orphaned note."}).insert(
				ignore_permissions=True
			)

	def test_visible_to_customer_defaults_to_zero(self) -> None:
		request_name = self._make_request()
		doc = frappe.get_doc(
			{"doctype": "Request Update", "request": request_name, "note": "Internal only."}
		).insert(ignore_permissions=True)
		self.assertEqual(doc.visible_to_customer, 0)
```

- [ ] **Step 3: Run migration and the test**

Run: `bench --site <your-site> migrate` (creates the new doctype's table), then
`bench --site <your-site> run-tests --app upande_dev_tools --module upande_dev_tools.upande_dev_tools.doctype.request_update.test_request_update`
Expected: PASS, 3 tests.

- [ ] **Step 4: Commit**

```bash
git add upande_dev_tools/upande_dev_tools/doctype/request_update/
git commit -m "feat: add Request Update doctype for decision/audit history"
```

---

### Task 2: `Request` schema — `scheduled_date`/`deferred_until`, and the `resolution_notes` removal patch

**Files:**
- Modify: `upande_dev_tools/upande_dev_tools/doctype/request/request.json`
- Modify: `upande_dev_tools/upande_dev_tools/doctype/request/request.py`
- Create: `upande_dev_tools/patches/migrate_resolution_notes_to_request_update.py`
- Modify: `upande_dev_tools/patches.txt`
- Test: `upande_dev_tools/upande_dev_tools/doctype/request/test_request.py`

**Interfaces:**
- Consumes: `Request Update` doctype (Task 1).
- Produces: `Request.scheduled_date` (Date), `Request.deferred_until` (Date) — consumed by Task 5
  (setting them), Task 6 (`get_my_requests` returning `scheduled_date`), Task 7
  (`_priority_breakdown`/`_risks` reading `deferred_until`), Task 11 (portal displaying
  `scheduled_date`). `Request.on_update()` seeds `Task.custom_planned_for` from
  `Request.scheduled_date` when the linked Task is created.

- [ ] **Step 1: Add the patch (runs BEFORE the schema change removes `resolution_notes`)**

`upande_dev_tools/patches/migrate_resolution_notes_to_request_update.py`:
```python
# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import frappe


def execute() -> None:
	"""Runs in [pre_model_sync], before request.json's schema change drops
	resolution_notes - copies any existing non-empty value into a Request Update row so
	no historical decision text is silently lost."""
	if not frappe.db.table_has_column("Request", "resolution_notes"):
		return

	rows = frappe.db.get_all(
		"Request", filters={"resolution_notes": ["is", "set"]}, fields=["name", "resolution_notes"]
	)
	for row in rows:
		if not (row.resolution_notes or "").strip():
			continue
		frappe.get_doc(
			{
				"doctype": "Request Update",
				"request": row.name,
				"note": row.resolution_notes,
				"visible_to_customer": 0,
			}
		).insert(ignore_permissions=True)
```

Add to `upande_dev_tools/patches.txt`'s `[pre_model_sync]` section (after the existing
`upande_dev_tools.patches.rename_workspace_to_dev_tools` line):
```
upande_dev_tools.patches.migrate_resolution_notes_to_request_update
```

- [ ] **Step 2: Change the doctype schema**

In `request.json`, remove `"resolution_notes"` from `field_order` and remove its field object
(the `section_break_resolution`/`resolution_notes` pair at the end of the current file) entirely.
Add two new fields at the end of `field_order` (`"scheduled_date"`, `"deferred_until"`) and their
field objects to `fields`:
```json
  {
   "fieldname": "scheduled_date",
   "fieldtype": "Date",
   "label": "Scheduled Date",
   "description": "The date committed to when this request was scheduled. Independently editable afterward."
  },
  {
   "fieldname": "deferred_until",
   "fieldtype": "Date",
   "label": "Deferred Until",
   "description": "When this deferred request should be revisited."
  }
```
Also update `modified` to `"2026-09-15 00:00:00.000000"`.

- [ ] **Step 3: Write the failing test for Task auto-creation carrying the scheduled date**

Add to `upande_dev_tools/upande_dev_tools/doctype/request/test_request.py` (inside
`IntegrationTestRequest`):
```python
	def test_scheduling_seeds_task_planned_for_from_scheduled_date(self) -> None:
		project = self._make_project()
		doc = frappe.get_doc(
			{
				"doctype": "Request",
				"title": "Ship with a date",
				"request_type": "Feature",
				"project": project,
				"priority": "High",
				"scheduled_date": "2026-10-01",
			}
		).insert(ignore_permissions=True)
		doc.workflow_state = "Approved"
		doc.save(ignore_permissions=True)
		doc.workflow_state = "Scheduled"
		doc.save(ignore_permissions=True)

		task = frappe.get_doc("Task", doc.linked_task)
		self.assertEqual(str(task.custom_planned_for), "2026-10-01")
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `bench --site <your-site> migrate` then
`bench --site <your-site> run-tests --app upande_dev_tools --module upande_dev_tools.upande_dev_tools.doctype.request.test_request`
Expected: FAIL on the new test - `custom_planned_for` is not set (the `on_update` Task-creation
block doesn't pass it yet).

- [ ] **Step 5: Implement**

In `request.py`'s `on_update()`, add `"custom_planned_for": self.scheduled_date` to the `Task`
document dict passed to `frappe.get_doc`:
```python
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
					"custom_planned_for": self.scheduled_date,
				}
			)
			# Skip Task's recursion check - a query this bench's pypika can't execute, and
			# unnecessary on a freshly created Task anyway.
			task.flags.ignore_recursion_check = True
			task.insert(ignore_permissions=True)
			self.db_set("linked_task", task.name, update_modified=False)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run the same command as Step 4.
Expected: PASS, all tests in this module including the new one and the pre-existing
`test_scheduling_creates_linked_task`.

- [ ] **Step 7: Commit**

```bash
git add upande_dev_tools/upande_dev_tools/doctype/request/request.json \
        upande_dev_tools/upande_dev_tools/doctype/request/request.py \
        upande_dev_tools/upande_dev_tools/doctype/request/test_request.py \
        upande_dev_tools/patches/migrate_resolution_notes_to_request_update.py \
        upande_dev_tools/patches.txt
git commit -m "feat: add scheduled_date/deferred_until to Request, remove resolution_notes (migrated)"
```

---

### Task 3: `add_request_note` / `get_request_updates` API methods

**Files:**
- Modify: `upande_dev_tools/api/requests.py`
- Test: `upande_dev_tools/tests/test_requests_api.py`

**Interfaces:**
- Consumes: `Request Update` doctype (Task 1).
- Produces: `add_request_note(name, note, visible_to_customer, action=None, from_state=None,
  to_state=None) -> dict` and `get_request_updates(name) -> list[dict]` — consumed by Task 5
  (transition-attached notes) and Task 9/10 (standalone "Add note" UI), Task 11 (customer portal
  history).

**Before starting:** run `git status` and confirm `upande_dev_tools/tests/test_requests_api.py` is
NOT listed as unmerged (`UU`). If it still is, stop and report back rather than editing it.

- [ ] **Step 1: Write the failing tests**

Add to `upande_dev_tools/tests/test_requests_api.py` (match this file's existing imports/style —
read it in full first):
```python
class TestAddRequestNote(IntegrationTestCase):
	def _make_request(self) -> str:
		return frappe.get_doc(
			{"doctype": "Request", "title": "Needs a note", "request_type": "Bug"}
		).insert(ignore_permissions=True).name

	def test_dev_team_can_add_a_standalone_note(self) -> None:
		from upande_dev_tools.api.requests import add_request_note

		request_name = self._make_request()
		if not frappe.db.exists("User", "note-author@example.test"):
			frappe.get_doc(
				{"doctype": "User", "email": "note-author@example.test", "first_name": "Note", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		frappe.get_doc("User", "note-author@example.test").add_roles("Dev Team")

		frappe.set_user("note-author@example.test")
		try:
			result = add_request_note(request_name, note="Investigating.", visible_to_customer=False)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(result["request"], request_name)
		self.assertEqual(result["actor"], "note-author@example.test")

	def test_non_reviewer_cannot_add_a_note(self) -> None:
		from upande_dev_tools.api.requests import add_request_note

		request_name = self._make_request()
		if not frappe.db.exists("User", "no-role@example.test"):
			frappe.get_doc(
				{"doctype": "User", "email": "no-role@example.test", "first_name": "NoRole", "send_welcome_email": 0}
			).insert(ignore_permissions=True)

		frappe.set_user("no-role@example.test")
		try:
			with self.assertRaises(frappe.PermissionError):
				add_request_note(request_name, note="Not allowed.", visible_to_customer=False)
		finally:
			frappe.set_user("Administrator")

	def test_get_request_updates_filters_to_visible_only_for_the_customer(self) -> None:
		from upande_dev_tools.api.requests import add_request_note, get_request_updates

		request_name = self._make_request()
		frappe.get_doc(
			{"doctype": "Request Update", "request": request_name, "note": "Internal", "visible_to_customer": 0}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{"doctype": "Request Update", "request": request_name, "note": "Public", "visible_to_customer": 1}
		).insert(ignore_permissions=True)

		reviewer_view = get_request_updates(request_name)
		self.assertEqual(len(reviewer_view), 2)

		frappe.db.set_value(
			"Request", request_name, "raised_by_user", "customer-viewer@example.test", update_modified=False
		)
		if not frappe.db.exists("User", "customer-viewer@example.test"):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": "customer-viewer@example.test",
					"first_name": "Customer",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)

		frappe.set_user("customer-viewer@example.test")
		try:
			customer_view = get_request_updates(request_name)
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(len(customer_view), 1)
		self.assertEqual(customer_view[0]["note"], "Public")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bench --site <your-site> run-tests --app upande_dev_tools --module upande_dev_tools.tests.test_requests_api`
Expected: FAIL - `add_request_note`/`get_request_updates` don't exist yet.

- [ ] **Step 3: Implement**

Add to `upande_dev_tools/api/requests.py`:
```python
@frappe.whitelist()
def add_request_note(
	name: str,
	note: str,
	visible_to_customer: bool = False,
	action: str | None = None,
	from_state: str | None = None,
	to_state: str | None = None,
) -> dict:
	if not set(frappe.get_roles()) & REVIEWER_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	doc = frappe.get_doc(
		{
			"doctype": "Request Update",
			"request": name,
			"note": note,
			"visible_to_customer": 1 if visible_to_customer else 0,
			"action": action,
			"from_state": from_state,
			"to_state": to_state,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.as_dict()


@frappe.whitelist()
def get_request_updates(name: str) -> list[dict]:
	filters: dict = {"request": name}
	if not set(frappe.get_roles()) & REVIEWER_ROLES:
		if not frappe.db.exists("Request", {"name": name, "raised_by_user": frappe.session.user}):
			frappe.throw(_("Not permitted."), frappe.PermissionError)
		filters["visible_to_customer"] = 1

	return frappe.get_all(
		"Request Update",
		filters=filters,
		fields=["name", "action", "from_state", "to_state", "note", "visible_to_customer", "actor", "creation"],
		order_by="creation asc",
		ignore_permissions=True,
	)
```

- [ ] **Step 4: Run the tests to verify they pass**

Same command as Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add upande_dev_tools/api/requests.py upande_dev_tools/tests/test_requests_api.py
git commit -m "feat: add add_request_note/get_request_updates API methods"
```

---

### Task 4: `update_request_dates` API method

**Files:**
- Modify: `upande_dev_tools/api/requests.py`
- Test: `upande_dev_tools/tests/test_requests_api.py`

**Interfaces:**
- Consumes: `Request.scheduled_date`/`deferred_until` (Task 2).
- Produces: `update_request_dates(name, scheduled_date=None, deferred_until=None) -> dict` —
  consumed by Task 9's standalone "Add note" modal (date-editing).

- [ ] **Step 1: Write the failing tests**

Add to `upande_dev_tools/tests/test_requests_api.py`:
```python
class TestUpdateRequestDates(IntegrationTestCase):
	def _make_request(self) -> str:
		return frappe.get_doc(
			{"doctype": "Request", "title": "Needs dates", "request_type": "Bug"}
		).insert(ignore_permissions=True).name

	def test_updates_both_dates(self) -> None:
		from upande_dev_tools.api.requests import update_request_dates

		request_name = self._make_request()
		result = update_request_dates(request_name, scheduled_date="2026-11-01", deferred_until="2026-11-15")
		self.assertEqual(result["scheduled_date"], "2026-11-01")
		self.assertEqual(result["deferred_until"], "2026-11-15")
		doc = frappe.get_doc("Request", request_name)
		self.assertEqual(str(doc.scheduled_date), "2026-11-01")
		self.assertEqual(str(doc.deferred_until), "2026-11-15")

	def test_requires_at_least_one_date(self) -> None:
		from upande_dev_tools.api.requests import update_request_dates

		request_name = self._make_request()
		with self.assertRaises(frappe.ValidationError):
			update_request_dates(request_name)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bench --site <your-site> run-tests --app upande_dev_tools --module upande_dev_tools.tests.test_requests_api`
Expected: FAIL - `update_request_dates` doesn't exist.

- [ ] **Step 3: Implement**

Add to `upande_dev_tools/api/requests.py`:
```python
@frappe.whitelist()
def update_request_dates(
	name: str, scheduled_date: str | None = None, deferred_until: str | None = None
) -> dict:
	if not set(frappe.get_roles()) & REVIEWER_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	if scheduled_date is None and deferred_until is None:
		frappe.throw(_("Provide at least one date to update."), frappe.ValidationError)

	values = {}
	if scheduled_date is not None:
		values["scheduled_date"] = scheduled_date
	if deferred_until is not None:
		values["deferred_until"] = deferred_until
	for field, value in values.items():
		frappe.db.set_value("Request", name, field, value, update_modified=False)

	return {"name": name, **values}
```

- [ ] **Step 4: Run the tests to verify they pass**

Same command as Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add upande_dev_tools/api/requests.py upande_dev_tools/tests/test_requests_api.py
git commit -m "feat: add update_request_dates API method"
```

---

### Task 5: `accept_request`/`triage_request` require dates and accept a note

**Files:**
- Modify: `upande_dev_tools/api/requests.py`
- Test: `upande_dev_tools/tests/test_requests_api.py`

**Interfaces:**
- Consumes: `add_request_note` (Task 3), `Request.scheduled_date`/`deferred_until` (Task 2).
- Produces: `accept_request(name, project, priority, scheduled_date, assign_to=None, note=None,
  visible_to_customer=False)` (new required `scheduled_date` param, inserted before the existing
  optional ones) and `triage_request(name, action, project=None, priority=None,
  deferred_until=None, note=None, visible_to_customer=False)` (new optional params; validated as
  required only when `action == "Defer"`) — consumed by Task 9 (Review Queue UI).

**Before starting:** confirm (again) `upande_dev_tools/tests/test_requests_api.py` is not `UU`.

- [ ] **Step 1: Write the failing tests**

Add to `upande_dev_tools/tests/test_requests_api.py`:
```python
class TestAcceptRequestRequiresScheduledDate(IntegrationTestCase):
	def _make_project(self) -> str:
		name = "Decision Visibility Test Project"
		existing = frappe.db.exists("Project", {"project_name": name})
		if existing:
			return existing
		company = frappe.db.get_value("Company", {}, "name")
		if not company:
			self.skipTest("No Company exists on this site to attach a test Project to.")
		return (
			frappe.get_doc({"doctype": "Project", "project_name": name, "company": company})
			.insert(ignore_permissions=True)
			.name
		)

	def _make_request(self) -> str:
		return frappe.get_doc(
			{"doctype": "Request", "title": "Needs scheduling", "request_type": "Bug"}
		).insert(ignore_permissions=True).name

	def test_accept_request_requires_scheduled_date(self) -> None:
		from upande_dev_tools.api.requests import accept_request

		request_name = self._make_request()
		project = self._make_project()
		with self.assertRaises(frappe.ValidationError):
			accept_request(request_name, project=project, priority="High", scheduled_date=None)

	def test_accept_request_sets_scheduled_date_and_optional_note(self) -> None:
		from upande_dev_tools.api.requests import accept_request

		request_name = self._make_request()
		project = self._make_project()
		result = accept_request(
			request_name,
			project=project,
			priority="High",
			scheduled_date="2026-10-05",
			note="Sounds good, scheduling this.",
			visible_to_customer=True,
		)
		self.assertEqual(result["workflow_state"], "Scheduled")
		doc = frappe.get_doc("Request", request_name)
		self.assertEqual(str(doc.scheduled_date), "2026-10-05")
		updates = frappe.get_all("Request Update", filters={"request": request_name}, fields=["note", "to_state"])
		self.assertEqual(len(updates), 1)
		self.assertEqual(updates[0]["to_state"], "Scheduled")

	def test_triage_request_defer_requires_deferred_until(self) -> None:
		from upande_dev_tools.api.requests import triage_request

		request_name = self._make_request()
		with self.assertRaises(frappe.ValidationError):
			triage_request(request_name, action="Defer", deferred_until=None)

	def test_triage_request_defer_sets_deferred_until(self) -> None:
		from upande_dev_tools.api.requests import triage_request

		request_name = self._make_request()
		triage_request(request_name, action="Defer", deferred_until="2026-11-20")
		doc = frappe.get_doc("Request", request_name)
		self.assertEqual(str(doc.deferred_until), "2026-11-20")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bench --site <your-site> run-tests --app upande_dev_tools --module upande_dev_tools.tests.test_requests_api`
Expected: FAIL - `accept_request` doesn't require `scheduled_date` yet; `triage_request` doesn't
accept/require `deferred_until` yet.

- [ ] **Step 3: Implement**

Replace `accept_request` in `upande_dev_tools/api/requests.py`:
```python
@frappe.whitelist()
def accept_request(
	name: str,
	project: str,
	priority: str,
	scheduled_date: str,
	assign_to: str | None = None,
	note: str | None = None,
	visible_to_customer: bool = False,
) -> dict:
	"""Approve a request and schedule it in one step, which is what creates the Task,
	then hand that Task to whoever will do the work."""
	from frappe.desk.form.assign_to import add as add_assignment
	from frappe.model.workflow import apply_workflow

	if not set(frappe.get_roles()) & REVIEWER_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	if not (project and priority):
		frappe.throw(_("Set a project and a priority before accepting."), frappe.ValidationError)
	if not scheduled_date:
		frappe.throw(_("Set a scheduled date before accepting."), frappe.ValidationError)

	doc = frappe.get_doc("Request", name)
	doc.project = project
	doc.priority = priority
	doc.scheduled_date = scheduled_date
	doc.save()

	from_state = doc.workflow_state
	doc = apply_workflow(doc, "Approve")
	doc = apply_workflow(doc, "Schedule")
	doc.reload()

	if note:
		add_request_note(
			name, note=note, visible_to_customer=visible_to_customer,
			action="Schedule", from_state=from_state, to_state=doc.workflow_state,
		)

	if assign_to and doc.linked_task:
		add_assignment({"doctype": "Task", "name": doc.linked_task, "assign_to": [assign_to], "notify": 0})

	return {
		"name": doc.name,
		"workflow_state": doc.workflow_state,
		"task": doc.linked_task,
		"assigned_to": assign_to,
	}
```

Replace `triage_request`:
```python
@frappe.whitelist()
def triage_request(
	name: str,
	action: str,
	project: str | None = None,
	priority: str | None = None,
	deferred_until: str | None = None,
	note: str | None = None,
	visible_to_customer: bool = False,
) -> dict:
	from frappe.model.workflow import apply_workflow

	if action == "Defer" and not deferred_until:
		frappe.throw(_("Set a date to revisit this before deferring."), frappe.ValidationError)

	doc = frappe.get_doc("Request", name)
	if project:
		doc.project = project
	if priority:
		doc.priority = priority
	if action == "Defer":
		doc.deferred_until = deferred_until
	if project or priority or action == "Defer":
		doc.save()

	from_state = doc.workflow_state
	updated = apply_workflow(doc, action)

	if note:
		add_request_note(
			name, note=note, visible_to_customer=visible_to_customer,
			action=action, from_state=from_state, to_state=updated.workflow_state,
		)

	return updated.as_dict()
```

- [ ] **Step 4: Run the tests to verify they pass**

Same command as Step 2. Expected: PASS, including the pre-existing `triage_request`/
`accept_request` tests elsewhere in this file (re-run the whole module, not just the new class,
to confirm nothing broke).

- [ ] **Step 5: Commit**

```bash
git add upande_dev_tools/api/requests.py upande_dev_tools/tests/test_requests_api.py
git commit -m "feat: accept_request requires scheduled_date, triage_request Defer requires deferred_until"
```

---

### Task 6: `get_my_requests` returns `scheduled_date`

**Files:**
- Modify: `upande_dev_tools/api/requests.py`
- Test: `upande_dev_tools/tests/test_requests_api.py`

**Interfaces:**
- Consumes: `Request.scheduled_date` (Task 2).
- Produces: `get_my_requests` now includes `scheduled_date` in its returned dicts — consumed by
  Task 11 (customer portal).

- [ ] **Step 1: Write the failing test**

Add to `upande_dev_tools/tests/test_requests_api.py`:
```python
class TestGetMyRequestsIncludesScheduledDate(IntegrationTestCase):
	def test_scheduled_date_is_returned(self) -> None:
		from upande_dev_tools.api.requests import get_my_requests

		doc = frappe.get_doc(
			{
				"doctype": "Request",
				"title": "Has a date",
				"request_type": "Bug",
				"scheduled_date": "2026-12-01",
			}
		).insert(ignore_permissions=True)

		frappe.set_user(doc.raised_by_user)
		try:
			rows = get_my_requests()
		finally:
			frappe.set_user("Administrator")

		row = next(r for r in rows if r["name"] == doc.name)
		self.assertEqual(str(row["scheduled_date"]), "2026-12-01")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `bench --site <your-site> run-tests --app upande_dev_tools --module upande_dev_tools.tests.test_requests_api`
Expected: FAIL - `KeyError: 'scheduled_date'`.

- [ ] **Step 3: Implement**

In `get_my_requests`, add `"scheduled_date"` to the `fields` list (after `"linked_task"`):
```python
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
			"scheduled_date",
			"creation",
		],
		order_by="creation desc",
		ignore_permissions=True,
	)
```

- [ ] **Step 4: Run the test to verify it passes**

Same command as Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add upande_dev_tools/api/requests.py upande_dev_tools/tests/test_requests_api.py
git commit -m "feat: get_my_requests returns scheduled_date"
```

---

### Task 7: PM dashboard backend - `_priority_breakdown` and the overdue-deferral risk bucket

**Files:**
- Modify: `upande_dev_tools/api/portfolio.py`
- Test: `upande_dev_tools/tests/test_portfolio_api.py` (create if it doesn't already exist - check
  first; if `upande_dev_tools/tests/` already has a portfolio test file under a different name,
  add to that one instead and use its existing import/fixture conventions)

**Interfaces:**
- Consumes: `Request.priority`/`deferred_until` (Task 2).
- Produces: `get_portfolio()`'s returned dict gains a new `"priority_breakdown"` key (list of
  `{"priority": str, "count": int}`, one row per entry in the `PRIORITIES` list, open requests
  only); `_risks()` gains a `"kind": "Deferred, overdue"` bucket — consumed by Task 8
  (pm-dashboard.js rendering).

- [ ] **Step 1: Write the failing tests**

Check for an existing test file covering `api/portfolio.py` first (`grep -rl "get_portfolio"
upande_dev_tools/tests/`). If found, add to it; otherwise create
`upande_dev_tools/tests/test_portfolio_api.py`:
```python
# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase


class TestPortfolioPriorityBreakdown(IntegrationTestCase):
	def test_priority_breakdown_counts_open_requests_by_priority(self) -> None:
		from upande_dev_tools.api.portfolio import get_portfolio

		frappe.get_doc(
			{"doctype": "Request", "title": "Urgent one", "request_type": "Bug", "priority": "Urgent"}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{"doctype": "Request", "title": "Completed urgent, excluded", "request_type": "Bug", "priority": "Urgent", "workflow_state": "Completed"}
		).insert(ignore_permissions=True)

		frappe.set_user("Administrator")
		result = get_portfolio()
		breakdown = {row["priority"]: row["count"] for row in result["priority_breakdown"]}
		self.assertGreaterEqual(breakdown.get("Urgent", 0), 1)

	def test_risks_includes_overdue_deferred_requests(self) -> None:
		from frappe.utils import add_days, today
		from upande_dev_tools.api.portfolio import get_portfolio

		frappe.get_doc(
			{
				"doctype": "Request",
				"title": "Overdue deferral",
				"request_type": "Bug",
				"workflow_state": "Deferred",
				"deferred_until": add_days(today(), -3),
			}
		).insert(ignore_permissions=True)

		frappe.set_user("Administrator")
		result = get_portfolio()
		kinds = {row["kind"] for row in result["risks"]}
		self.assertIn("Deferred, overdue", kinds)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bench --site <your-site> run-tests --app upande_dev_tools --module <the module path from Step 1>`
Expected: FAIL - `KeyError: 'priority_breakdown'`, and no `"Deferred, overdue"` kind present.

- [ ] **Step 3: Implement**

In `upande_dev_tools/api/portfolio.py`, add a new function (near `_requests`):
```python
PRIORITIES = ["Low", "Medium", "High", "Urgent"]
OPEN_REQUEST = ["not in", ["Completed", "Rejected"]]


def _priority_breakdown(scoped: dict) -> list[dict]:
	rows = frappe.get_all(
		"Request",
		filters={**scoped, "workflow_state": OPEN_REQUEST},
		fields=["priority"],
		ignore_permissions=True,
	)
	counts: dict[str, int] = defaultdict(int)
	for row in rows:
		counts[row.priority or "None"] += 1
	return [{"priority": p, "count": counts.get(p, 0)} for p in PRIORITIES]
```

Add `"priority_breakdown": _priority_breakdown(scoped),` to `get_portfolio`'s returned dict
(alongside the existing `"requests": _requests(scoped, end),` line).

In `_risks()`, add a new loop (after the existing `Request` "Awaiting you" loop, before the
`names = _names(...)` line):
```python
	from frappe.utils import getdate as _getdate

	for req in frappe.get_all(
		"Request",
		filters={**scoped, "workflow_state": "Deferred", "deferred_until": ["<", str(end)]},
		fields=["name", "title", "deferred_until"],
		limit=5,
		ignore_permissions=True,
	):
		out.append(
			{
				"kind": "Deferred, overdue",
				"doctype": "Request",
				"name": req.name,
				"title": req.title,
				"days": (getdate(end) - getdate(req.deferred_until)).days,
				"who": [],
			}
		)
```
(Remove the redundant `from frappe.utils import getdate as _getdate` line and just use the
already-imported `getdate` from this module's top-level import — it's already imported at the top
of the file, so this inline import is unnecessary; use `getdate` directly.)

- [ ] **Step 4: Run the tests to verify they pass**

Same command as Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add upande_dev_tools/api/portfolio.py upande_dev_tools/tests/test_portfolio_api.py
git commit -m "feat: add priority breakdown and overdue-deferral risk bucket to PM portfolio"
```

---

### Task 8: PM dashboard frontend - "By priority" card + overdue-deferral risk rendering

**Files:**
- Modify: `upande_dev_tools/public/js/pm-dashboard.js`

**Interfaces:**
- Consumes: `priority_breakdown` and the `"Deferred, overdue"` risk kind (Task 7).
- Produces: nothing consumed by a later task (frontend leaf).

- [ ] **Step 1: Read the current render call site and `pm_risks`/`pm_requests` functions in full**

Read `upande_dev_tools/public/js/pm-dashboard.js` completely before editing - find where
`pm_requests(d.requests)` is called (around line 233) and the `pm_risks` function (around line
311) to match their exact existing card/list markup conventions.

- [ ] **Step 2: Add the priority card**

Add a new function alongside `pm_requests`:
```javascript
function pm_priority(rows) {
	const total = rows.reduce((sum, r) => sum + r.count, 0);
	const share = (n) => (total ? Math.round((n / total) * 100) : 0);
	const tone = { Low: "calm", Medium: "ok", High: "warn", Urgent: "bad" };
	return `
		<div class="dpx-card">
			<div class="dpx-card-hd"><div class="ttl">By priority</div>
				<span class="pm-tally"><b>${total}</b> open</span></div>
			<div class="dpx-card-body">
				<div class="pm-req">
					${rows
						.map(
							(r) => `<a class="r ${tone[r.priority] || "calm"}" href="/app/request?priority=${encodeURIComponent(
								r.priority
							)}&workflow_state=%5B%22not%20in%22%2C%5B%22Completed%22%2C%22Rejected%22%5D%5D">
								<span class="n">${r.count}</span>
								<span class="l">${pm_esc(r.priority)}</span>
								<span class="bar"><i style="width:${share(r.count)}%"></i></span>
							</a>`
						)
						.join("")}
				</div>
			</div>
		</div>`;
}
```
(This mirrors `pm_requests`'s exact markup, but each row is an `<a>` linking to the desk's native
Request List View pre-filtered by priority and open workflow states - the corrected click-through
approach noted in this plan's Global Constraints, not the non-existent "existing card behavior.")

Add the card to the render call site, alongside the existing `pm_requests(d.requests)` call:
```javascript
${pm_priority(d.priority_breakdown)}
```

- [ ] **Step 3: Render the new risk kind**

In `pm_risks`, find how each risk row's `kind` becomes a badge/label (read the function body) and
confirm `"Deferred, overdue"` renders through the same generic path every other `kind` value
already does (it should, since `pm_risks` iterates the `risks` array generically) - if the function
hardcodes a fixed set of kind-to-style mappings anywhere, add `"Deferred, overdue"` to that mapping
following the existing pattern (e.g. if there's a color/icon lookup keyed by `kind`, add an entry
for it there); otherwise no change is needed here.

- [ ] **Step 4: Manual verification**

Since this file has no JS unit test harness in this app (confirm by checking for a `tests/`
directory alongside `public/js/` - there is none for this app's frontend), verify by loading
`/pm-dashboard` in a browser as a Projects Manager user and confirming the new "By priority" card
renders with correct counts, and that an overdue deferred request appears in "Needs attention".

- [ ] **Step 5: Commit**

```bash
git add upande_dev_tools/public/js/pm-dashboard.js
git commit -m "feat: render priority breakdown card and overdue-deferral risks on PM dashboard"
```

---

### Task 9: Review Queue - required date pickers, optional note + visibility, standalone Add-note

**Files:**
- Modify: `upande_dev_tools/public/js/review-queue.js`

**Interfaces:**
- Consumes: `accept_request`/`triage_request`'s new required/optional params (Task 5),
  `add_request_note`/`update_request_dates` (Tasks 3-4).
- Produces: nothing consumed by a later task (frontend leaf), except the "Add note" modal markup
  pattern this task establishes, which Task 10 (Backlog Board) reuses.

- [ ] **Step 1: Read the current file in full**

Read `upande_dev_tools/public/js/review-queue.js` completely - identify exactly how the Accept and
Defer actions currently call `frappe.xcall("upande_dev_tools.api.requests.accept_request", ...)`
and `triage_request`, and how each row's per-request state (project/priority/assignee selects) is
currently tracked, so the new date/note inputs follow the same per-row state pattern rather than a
new one.

- [ ] **Step 2: Add required date inputs to Accept/Defer**

For the Accept action's row UI, add a `<input type="date">` bound to that row's state, and block
the `accept_request` xcall (show an inline validation message, don't submit) if it's empty. Pass
the value as the new required `scheduled_date` argument to `accept_request`.

For the Defer action, add the same kind of required `<input type="date">`, block `triage_request`
if empty when the action is `"Defer"`, and pass it as `deferred_until`.

For all three actions (Accept/Defer/Reject), add an optional `<textarea>` for a note and a
`<input type="checkbox">` labelled "Visible to customer", and pass `note`/`visible_to_customer`
through to whichever call the action already makes (`accept_request` or `triage_request` - both
now accept these two optional params per Task 5; for Reject, call
`upande_dev_tools.api.requests.add_request_note` directly right after the existing
`triage_request(name, "Reject")` xcall succeeds, if a note was entered, since `triage_request`'s
note pass-through only fires when the caller supplies one).

- [ ] **Step 3: Add a standalone "Add note" button per row**

Add a small button/icon per request row (not tied to Accept/Defer/Reject) that opens a minimal
modal (note textarea + visible-to-customer checkbox + optional scheduled-date/deferred-until date
inputs, pre-filled with the row's current values if any), and on submit calls
`upande_dev_tools.api.requests.add_request_note` (always, if a note was entered) and
`upande_dev_tools.api.requests.update_request_dates` (only if a date field was changed from its
current value) as two separate xcalls.

- [ ] **Step 4: Manual verification**

No JS test harness exists for this app's frontend (see Task 8, Step 4). Verify manually in a
browser as a Projects Manager: Accept is blocked without a date, succeeds with one and an optional
customer-visible note; Defer is blocked without a date; the standalone Add-note button works
independent of any transition.

- [ ] **Step 5: Commit**

```bash
git add upande_dev_tools/public/js/review-queue.js
git commit -m "feat: Review Queue requires scheduling/deferral dates, supports decision notes"
```

---

### Task 10: Backlog Board - standalone Add-note button on request cards

**Files:**
- Modify: `upande_dev_tools/public/js/backlog-board.js`

**Interfaces:**
- Consumes: `add_request_note` (Task 3), the modal pattern established in Task 9.
- Produces: nothing consumed by a later task (frontend leaf).

- [ ] **Step 1: Read the current `card()` function and request-card branch in full**

Read `upande_dev_tools/public/js/backlog-board.js`'s `card(item)` function (around line 1285) -
confirm how it currently distinguishes a `Request` item (`movable: false`) from `Task`/`Issue`
items, since the Add-note button is added ONLY to Request cards (Tasks/Issues aren't in this
spec's scope) without making them draggable.

- [ ] **Step 2: Add the button**

Add a small "Add note" button/icon to each Request card's markup (not affecting its `movable:
false`/non-draggable behavior at all), reusing the same modal pattern from Task 9 (note textarea +
visible-to-customer checkbox), calling `upande_dev_tools.api.requests.add_request_note` on submit.

- [ ] **Step 3: Manual verification**

Verify in a browser: the button appears only on Request cards, opens the modal, submits
successfully, and Request cards remain non-draggable exactly as before.

- [ ] **Step 4: Commit**

```bash
git add upande_dev_tools/public/js/backlog-board.js
git commit -m "feat: add standalone note button to Backlog Board request cards"
```

---

### Task 11: Customer portal - decision history and scheduled date

**Files:**
- Modify: `upande_dev_tools/public/js/requests-portal.js`

**Interfaces:**
- Consumes: `get_request_updates` (Task 3), `scheduled_date` from `get_my_requests` (Task 6).
- Produces: nothing consumed by a later task (frontend leaf).

- [ ] **Step 1: Read the current file in full**

Read `upande_dev_tools/public/js/requests-portal.js` completely - specifically `rp_card(r)` (the
per-request card renderer) and however cards are expanded/detail-viewed today (if at all - if
there's no existing expand/detail interaction, the history renders inline in the card itself).

- [ ] **Step 2: Show the scheduled date**

In `rp_card`, add a line showing `Expected: <scheduled_date>` when `r.scheduled_date` is set,
alongside the existing status chip - e.g. inside the `.rp-meta` block:
```javascript
${r.scheduled_date ? `<span>Expected: ${rp_esc(String(r.scheduled_date).slice(0, 10))}</span>` : ""}
```

- [ ] **Step 3: Show the decision history**

Add a call to `upande_dev_tools.api.requests.get_request_updates` for each request (or lazily, on
card expand, if this file has an expand interaction - check first) and render the returned rows
(already filtered server-side to `visible_to_customer` ones for this customer) as a small
chronological list under the card, each entry showing its note text and date.

- [ ] **Step 4: Manual verification**

Verify in a browser as a customer/portal user: a request with a customer-visible note shows it; an
internal-only note (seeded directly via desk) does NOT appear; a scheduled request shows "Expected:
<date>".

- [ ] **Step 5: Commit**

```bash
git add upande_dev_tools/public/js/requests-portal.js
git commit -m "feat: customer portal shows decision history and scheduled date"
```

---

### Task 12: End-to-end integration test - the full approval workflow loop

**Files:**
- Test: `upande_dev_tools/tests/test_requests_api.py`

**Interfaces:**
- Consumes: everything from Tasks 1-7 (the full backend surface).
- Produces: nothing consumed by a later task (final verification task).

**Before starting:** confirm (again) `upande_dev_tools/tests/test_requests_api.py` is not `UU`.

- [ ] **Step 1: Write the end-to-end test**

Add to `upande_dev_tools/tests/test_requests_api.py`:
```python
class TestFullApprovalWorkflowEndToEnd(IntegrationTestCase):
	def _make_project(self) -> str:
		name = "E2E Decision Visibility Project"
		existing = frappe.db.exists("Project", {"project_name": name})
		if existing:
			return existing
		company = frappe.db.get_value("Company", {}, "name")
		if not company:
			self.skipTest("No Company exists on this site to attach a test Project to.")
		return (
			frappe.get_doc({"doctype": "Project", "project_name": name, "company": company})
			.insert(ignore_permissions=True)
			.name
		)

	def _make_user(self, email: str, roles: list[str]) -> str:
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "E2E", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		if roles:
			frappe.get_doc("User", email).add_roles(*roles)
		return email

	def test_customer_to_pm_to_developer_to_customer_loop(self) -> None:
		from upande_dev_tools.api.requests import (
			accept_request,
			create_request,
			get_my_day,
			get_my_requests,
			get_request_updates,
			update_task_status,
		)

		customer = self._make_user("e2e-customer@example.test", [])
		developer = self._make_user("e2e-developer@example.test", ["Dev Team"])
		project = self._make_project()

		# 1. Customer submits a request.
		frappe.set_user(customer)
		try:
			created = create_request(
				title="E2E: add a widget", request_type="Feature", project=project, source="Web Portal"
			)
		finally:
			frappe.set_user("Administrator")
		request_name = created["name"]

		# 2. PM accepts it with a scheduled date, an assignee, and a customer-visible note.
		result = accept_request(
			request_name,
			project=project,
			priority="High",
			scheduled_date="2026-12-10",
			assign_to=developer,
			note="Approved - we'll get to this on the 10th.",
			visible_to_customer=True,
		)
		self.assertEqual(result["workflow_state"], "Scheduled")
		task_name = result["task"]
		self.assertTrue(task_name)

		# 3. The Task carries the right planned-for date and assignment.
		task = frappe.get_doc("Task", task_name)
		self.assertEqual(str(task.custom_planned_for), "2026-12-10")
		self.assertIn(developer, (task._assign or ""))

		# 4. The developer sees it in My Day once planned_for matches today - simulate by
		# reading the task back with today's date instead, proving the query shape works
		# (the actual date is in the future here, so directly assert via get_developer_backlog
		# instead, which isn't date-restricted).
		from upande_dev_tools.api.requests import get_developer_backlog

		frappe.set_user(developer)
		try:
			backlog = get_developer_backlog()
		finally:
			frappe.set_user("Administrator")
		self.assertIn(task_name, [t["name"] for t in backlog])

		# 5. The customer's own view surfaces the note and the scheduled date.
		frappe.set_user(customer)
		try:
			my_requests = get_my_requests()
			updates = get_request_updates(request_name)
		finally:
			frappe.set_user("Administrator")
		my_row = next(r for r in my_requests if r["name"] == request_name)
		self.assertEqual(str(my_row["scheduled_date"]), "2026-12-10")
		self.assertEqual(len(updates), 1)
		self.assertEqual(updates[0]["note"], "Approved - we'll get to this on the 10th.")

		# 6. Developer completes the task.
		frappe.set_user(developer)
		try:
			update_task_status(task_name, "Completed")
		finally:
			frappe.set_user("Administrator")

		# 7. Customer's view reflects the final state.
		frappe.set_user(customer)
		try:
			final_requests = get_my_requests()
		finally:
			frappe.set_user("Administrator")
		final_row = next(r for r in final_requests if r["name"] == request_name)
		self.assertEqual(frappe.get_value("Task", task_name, "status"), "Completed")
		# The Request's own workflow_state doesn't auto-advance when its Task completes
		# (no such link exists in this codebase today) - this is the one part of "does the
		# customer see the final state" that remains a Request-side gap, documented here
		# rather than silently assumed away. The Task itself, which the customer cannot see
		# directly, IS Completed; the Request stays "Scheduled" from the customer's own view.
		self.assertEqual(final_row["workflow_state"], "Scheduled")
```

- [ ] **Step 2: Run the test**

Run: `bench --site <your-site> run-tests --app upande_dev_tools --module upande_dev_tools.tests.test_requests_api`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add upande_dev_tools/tests/test_requests_api.py
git commit -m "test: add end-to-end customer-to-PM-to-developer-to-customer workflow test"
```

**Note for whoever executes this plan:** Step 1's final assertion documents a real, pre-existing
gap this sub-project does NOT fix: a Request's `workflow_state` never advances past `Scheduled`
when its linked Task completes, so a customer's own view never shows "done" even once the actual
work is finished. This wasn't in the approved spec's scope (spec covers decision visibility and
scheduling, not state-sync automation) - flag it back to the user as a candidate for a future
sub-project rather than silently fixing or silently ignoring it.

---

## Self-review

**Spec coverage:** every spec section has a task - data model (Tasks 1-2), all 5 API
methods/changes (Tasks 3-6), PM dashboard priority card + overdue-deferral bucket (Tasks 7-8),
Review Queue + standalone note UI (Task 9), Backlog Board note button (Task 10), customer portal
(Task 11), end-to-end test (Task 12).

**Placeholder scan:** no TBD/TODO; every step has real code. Task 8/9/10/11's frontend steps are
necessarily less prescriptive about exact DOM insertion points than the backend tasks, since this
app's JS files have no existing component boundaries to slot new markup into cleanly (confirmed:
no JS test harness exists for this frontend) - each such step still names the exact function,
exact existing pattern to match, and exact new API calls to wire, which is the maximum precision
available without rewriting those files' architecture (out of scope here).

**Type/interface consistency:** `Request Update` fields (Task 1) match exactly what Task 3's
`add_request_note`/`get_request_updates` read and write; `scheduled_date`/`deferred_until` (Task 2)
match every later task's usage; `accept_request`/`triage_request`'s new signatures (Task 5) are
used identically by Task 9's frontend description.

**Scope check, sizing:** 12 tasks is larger than this project's two prior mobile-app plans (7-9
tasks each), but reflects genuinely more surface area (a new doctype, a schema migration patch,
5 backend methods across 2 files, and 4 separate frontend surfaces with no shared component layer
to reuse) - splitting further would cut across tasks that already depend tightly on each other
(e.g. Task 9's Review Queue changes are meaningless without Task 5's API changes) with no clean
subsystem boundary, unlike the mobile project's nav-shell-vs-screens split. Kept as one plan.
