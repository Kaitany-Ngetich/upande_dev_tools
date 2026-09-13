# Phase 2 Sub-project 3: New Developer Portal Views Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four new pages to the Developer portal nav group — My Day, Backlog Board, Code
Snapshots, Activity Log — and make the Tools Dashboard's summary cards link into the two new ones.

**Architecture:** My Day and the Backlog Board are front-ends only, for Phase 1's already-existing
`get_my_day`/`get_backlog_board` API (unchanged). Code Snapshots and Activity Log each get one new,
small, paginated/searchable whitelisted endpoint, gated by the same `Dev Team` role check the
Sub-project 2 security fix established. Every page follows the exact shape every prior portal page
in this project uses.

**Tech Stack:** Frappe v16 `www` pages, Jinja2, the existing `Request`/`Task` doctypes (Phase 1),
`Code Backup Snapshot`/`Developer Activity Log` doctypes (pre-existing, System-Manager-only at the
doctype-permission level — same situation Sub-project 2's endpoints were in before their fix).

**Spec:** `docs/specs/2026-09-13-portal-dev-views-design.md`

## Global Constraints

- Everything belongs to the single existing `Upande Dev Tools` module — no new module.
- Bench root `/home/jk/Projects/upande-local-bench-v16`, site `kaitet.local`. Whole-app
  `bench run-tests` is broken by a pre-existing unrelated ERPNext bug — always scope test runs
  with `--module`.
- `ruff` is on PATH (tabs, double quotes, 110 char lines) for every Python file touched, EXCEPT any
  new function added to `upande_dev_tools/api/dashboard.py` (which uses pre-existing 4-space
  indentation, not tabs — match that file's own style, do not reformat the whole file).
- After changing/creating any `public/js/*.js` or `public/css/*.css` file, run
  `bench build --app upande_dev_tools` before verifying live.
- Every new page's `.py` controller follows this exact shape (only `page_title`/`active_route`
  differ per page), matching every prior page in this project — including the
  `context = frappe._dict(context)` line, needed because a bare `{}` doesn't support attribute
  assignment and this project's own tests call `get_context({})` directly on the permitted branch:
  ```python
  # Copyright (c) 2026, shadrack@upande.com and contributors
  # For license information, please see license.txt

  import frappe

  from upande_dev_tools.portal import enforce_page_access

  no_cache = 1


  def get_context(context):
  	enforce_page_access("<route>")
  	context = frappe._dict(context)
  	context.no_cache = 1
  	context.page_title = "<Title>"
  	context.active_route = "<route>"
  	context.csrf_token = frappe.sessions.get_csrf_token()
  	return context
  ```
- Every new page's `.html` template follows this exact shape:
  ```jinja
  {% extends "templates/web.html" %}
  {% block head_include %}
  	{{ super() }}
  	{% include "templates/includes/dev_portal_shell_head.html" %}
  {% endblock %}
  {% block page_content %}
  {% from "templates/includes/dev_portal_shell.html" import dpx_shell with context %}
  {% call dpx_shell() %}
  ...page content...
  {% endcall %}
  {% endblock %}
  ```
- Registration goes through `register_dev_portal_page(route, title, icon, nav_group, sort_order,
  roles, require_all_roles=False)` in `upande_dev_tools/setup.py`, called from
  `register_dev_portal_pages()` in that same file — add one call per new page there. Do not alter
  `register_dev_portal_page`/`run_setup`/`create_task_custom_fields` themselves.
- `upande_dev_tools/tests/test_portal.py`'s `IntegrationTestPortal` class is where every new
  access-control/registration test in this plan is appended — reuse its existing
  `_make_user`/`_make_page` helpers, do not redeclare the class or duplicate imports.
- Both new API endpoints (`get_snapshots`, `get_activity_log`) must call a `_require_dev_team()`
  guard as their first statement, matching the exact pattern Sub-project 2's security fix
  established in `api/hooks_explorer.py`/`api/dashboard.py`/`api/code_editor.py`:
  ```python
  DEV_TOOLS_ROLES = {"Dev Team"}


  def _require_dev_team():
  	if not DEV_TOOLS_ROLES & set(frappe.get_roles()):
  		frappe.throw("Not permitted", frappe.PermissionError)
  ```
- `Code Backup Snapshot` and `Developer Activity Log` are both System-Manager-only at the doctype
  permission level — every `frappe.get_all`/`frappe.db.count` call against them in the new
  endpoints must pass `ignore_permissions=True` (the `_require_dev_team()` guard is what actually
  authorizes the call; ship this correctly from the start rather than as a later fix, unlike
  Sub-project 2's dashboard/hooks-explorer/code-editor endpoints which needed a follow-up fix for
  exactly this gap).

---

### Task 1: My Day page (`/my-day`)

**Files:**
- Create: `upande_dev_tools/www/my-day.html`
- Create: `upande_dev_tools/www/my_day.py`
- Modify: `upande_dev_tools/setup.py` (add registration call)
- Test: `upande_dev_tools/tests/test_portal.py` (append)

**Interfaces:**
- Consumes: `enforce_page_access`, `register_dev_portal_page`, `dpx_shell`, the existing
  `upande_dev_tools.api.requests.get_my_day` whitelisted function (unchanged — already
  permission-checks internally: a user can only see their own day unless they hold a
  `REVIEWER_ROLES` role).
- Produces: `/my-day`, registered with `allowed_roles=["Dev Team"]`, `nav_group="Developer"`,
  `sort_order=40`.

- [ ] **Step 1: Write the failing tests**

Append to `upande_dev_tools/tests/test_portal.py`'s `IntegrationTestPortal` class (add
`from upande_dev_tools.www.my_day import get_context as my_day_get_context` to the file's
imports):

```python
	def test_my_day_permits_dev_team_and_denies_others(self) -> None:
		dev = self._make_user("my-day-dev@example.test", ["Dev Team"])
		other = self._make_user("my-day-other@example.test", [])

		frappe.set_user(dev)
		try:
			my_day_get_context({})  # must not raise
		finally:
			frappe.set_user("Administrator")

		frappe.set_user(other)
		try:
			with self.assertRaises(frappe.Redirect):
				my_day_get_context({})
			self.assertEqual(frappe.local.flags.redirect_location, "/requests-portal")
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None

	def test_my_day_page_is_registered_with_correct_attributes(self) -> None:
		doc = frappe.get_doc("Dev Portal Page", "my-day")
		self.assertEqual(doc.title, "My Day")
		self.assertEqual(doc.icon, "calendar")
		self.assertEqual(doc.nav_group, "Developer")
		self.assertEqual(doc.sort_order, 40)
		self.assertEqual({row.role for row in doc.allowed_roles}, {"Dev Team"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_portal`
Expected: FAIL — `upande_dev_tools.www.my_day` doesn't exist yet.

- [ ] **Step 3: Write the page controller**

`upande_dev_tools/www/my_day.py` — follow the Global Constraints controller shape exactly, with
`route="my-day"`, `page_title="My Day"`, `active_route="my-day"`.

- [ ] **Step 4: Write the page template**

`upande_dev_tools/www/my-day.html` — follow the Global Constraints template shape. Inside the
`{% call dpx_shell() %}` block:

```html
<div class="dpx-page-hd">
	<div class="eyebrow">Developer</div>
	<div class="ttl">My Day</div>
	<div class="sub">Today's assigned tasks and meetings.</div>
</div>
<div class="dpx-kpis" id="my-day-meta"></div>
<div class="dpx-card">
	<div class="dpx-card-hd"><div class="ttl">Today's Tasks</div></div>
	<div class="dpx-card-body">
		<table id="my-day-tasks">
			<thead><tr><th>Task</th><th>Project</th><th>Priority</th><th>Status</th></tr></thead>
			<tbody></tbody>
		</table>
	</div>
</div>
<div class="dpx-card" style="margin-top: 18px;">
	<div class="dpx-card-hd"><div class="ttl">Today's Meetings</div></div>
	<div class="dpx-card-body">
		<table id="my-day-meetings">
			<thead><tr><th>Subject</th><th>Starts</th><th>Ends</th><th>Location</th></tr></thead>
			<tbody></tbody>
		</table>
	</div>
</div>
<script>
frappe.ready(function() {
	frappe.call({method: "upande_dev_tools.api.requests.get_my_day"}).then(function(r) {
		var data = r.message || {tasks: [], meetings: []};

		var metaEl = document.querySelector("#my-day-meta");
		var kpi = document.createElement("div");
		kpi.className = "dpx-kpi";
		var lbl = document.createElement("div");
		lbl.className = "lbl";
		lbl.textContent = "Date";
		var val = document.createElement("div");
		val.className = "v";
		val.textContent = data.date || "";
		kpi.appendChild(lbl);
		kpi.appendChild(val);
		metaEl.appendChild(kpi);

		var taskBody = document.querySelector("#my-day-tasks tbody");
		(data.tasks || []).forEach(function(task) {
			var tr = document.createElement("tr");
			["subject", "project", "priority", "status"].forEach(function(field) {
				var td = document.createElement("td");
				td.textContent = task[field] || "";
				tr.appendChild(td);
			});
			taskBody.appendChild(tr);
		});

		var meetingBody = document.querySelector("#my-day-meetings tbody");
		(data.meetings || []).forEach(function(meeting) {
			var tr = document.createElement("tr");
			[meeting.subject, meeting.starts_on, meeting.ends_on, meeting.location].forEach(function(v) {
				var td = document.createElement("td");
				td.textContent = v || "";
				tr.appendChild(td);
			});
			meetingBody.appendChild(tr);
		});
	});
});
</script>
```

- [ ] **Step 5: Add registration**

In `upande_dev_tools/setup.py`'s `register_dev_portal_pages()`, add:

```python
	register_dev_portal_page(
		route="my-day",
		title="My Day",
		icon="calendar",
		nav_group="Developer",
		sort_order=40,
		roles=["Dev Team"],
	)
```

- [ ] **Step 6: Migrate, build, and run tests**

Run: `bench --site kaitet.local migrate`
Run: `bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_portal`
Expected: PASS

- [ ] **Step 7: Live-verify**

Using the live-render technique already established in this project (a throwaway Dev Team user,
authenticated HTTP request against the running dev server at `http://kaitet.local:8002`), confirm
`/my-day` renders with no literal Jinja leakage, the shell sidebar highlights "My Day" as active,
and a no-role user is redirected away.

- [ ] **Step 8: Commit**

```bash
ruff format upande_dev_tools/www/my_day.py upande_dev_tools/setup.py upande_dev_tools/tests/test_portal.py
git add upande_dev_tools/www/my-day.html upande_dev_tools/www/my_day.py upande_dev_tools/setup.py \
  upande_dev_tools/tests/test_portal.py
git commit -m "feat: add the My Day portal page

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Backlog Board page (`/backlog-board`)

**Files:**
- Create: `upande_dev_tools/www/backlog-board.html`
- Create: `upande_dev_tools/www/backlog_board.py`
- Modify: `upande_dev_tools/setup.py` (add registration call)
- Test: `upande_dev_tools/tests/test_portal.py` (append)

**Interfaces:**
- Consumes: `enforce_page_access`, `register_dev_portal_page`, `dpx_shell`, the existing
  `upande_dev_tools.api.requests.get_backlog_board` whitelisted function (unchanged — already
  permission-checks: unscoped calls require a `REVIEWER_ROLES` role, `?project=` calls check
  `frappe.has_permission("Project", "read", project)`).
- Produces: `/backlog-board`, registered with `allowed_roles=["Dev Team"]`,
  `nav_group="Developer"`, `sort_order=50`.

- [ ] **Step 1: Write the failing tests**

Append to `upande_dev_tools/tests/test_portal.py`'s `IntegrationTestPortal` class (add
`from upande_dev_tools.www.backlog_board import get_context as backlog_board_get_context` to the
file's imports):

```python
	def test_backlog_board_permits_dev_team_and_denies_others(self) -> None:
		dev = self._make_user("backlog-board-dev@example.test", ["Dev Team"])
		other = self._make_user("backlog-board-other@example.test", [])

		frappe.set_user(dev)
		try:
			backlog_board_get_context({})  # must not raise
		finally:
			frappe.set_user("Administrator")

		frappe.set_user(other)
		try:
			with self.assertRaises(frappe.Redirect):
				backlog_board_get_context({})
			self.assertEqual(frappe.local.flags.redirect_location, "/requests-portal")
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None

	def test_backlog_board_page_is_registered_with_correct_attributes(self) -> None:
		doc = frappe.get_doc("Dev Portal Page", "backlog-board")
		self.assertEqual(doc.title, "Backlog Board")
		self.assertEqual(doc.icon, "trello")
		self.assertEqual(doc.nav_group, "Developer")
		self.assertEqual(doc.sort_order, 50)
		self.assertEqual({row.role for row in doc.allowed_roles}, {"Dev Team"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_portal`
Expected: FAIL — `upande_dev_tools.www.backlog_board` doesn't exist yet.

- [ ] **Step 3: Write the page controller**

`upande_dev_tools/www/backlog_board.py` — follow the Global Constraints controller shape exactly,
with `route="backlog-board"`, `page_title="Backlog Board"`, `active_route="backlog-board"`.
Additionally read an optional `project` query parameter and pass it through as context, so the
page's own JS can forward it to the API call:

```python
def get_context(context):
	enforce_page_access("backlog-board")
	context = frappe._dict(context)
	context.no_cache = 1
	context.page_title = "Backlog Board"
	context.active_route = "backlog-board"
	context.csrf_token = frappe.sessions.get_csrf_token()
	context.project = frappe.form_dict.get("project")
	return context
```

- [ ] **Step 4: Write the page template**

`upande_dev_tools/www/backlog-board.html` — follow the Global Constraints template shape. Columns
are derived dynamically from whatever `status`/`workflow_state` values are actually present in the
returned rows — do not hardcode a fixed column list. Inside the `{% call dpx_shell() %}` block:

```html
<div class="dpx-page-hd">
	<div class="eyebrow">Developer</div>
	<div class="ttl">Backlog Board</div>
	<div class="sub">Requests and Tasks across the pipeline.</div>
</div>
<div class="dpx-card">
	<div class="dpx-card-hd"><div class="ttl">Requests</div></div>
	<div class="dpx-card-body" id="board-requests"></div>
</div>
<div class="dpx-card" style="margin-top: 18px;">
	<div class="dpx-card-hd"><div class="ttl">Tasks</div></div>
	<div class="dpx-card-body" id="board-tasks"></div>
</div>
<script>
frappe.ready(function() {
	var project = {{ project | tojson }};
	var args = project ? {project: project} : {};

	function renderColumns(root, rows, groupField, cardFields) {
		root.innerHTML = "";
		var groups = {};
		var order = [];
		rows.forEach(function(row) {
			var key = row[groupField] || "(none)";
			if (!groups[key]) {
				groups[key] = [];
				order.push(key);
			}
			groups[key].push(row);
		});
		var wrap = document.createElement("div");
		wrap.style.display = "flex";
		wrap.style.gap = "18px";
		wrap.style.overflowX = "auto";
		order.forEach(function(key) {
			var col = document.createElement("div");
			col.style.minWidth = "220px";
			var hd = document.createElement("div");
			hd.className = "group-lbl";
			hd.textContent = key + " (" + groups[key].length + ")";
			col.appendChild(hd);
			groups[key].forEach(function(row) {
				var card = document.createElement("div");
				card.className = "pill";
				card.style.display = "block";
				card.style.marginBottom = "8px";
				card.textContent = cardFields.map(function(f) { return row[f]; }).filter(Boolean).join(" — ");
				col.appendChild(card);
			});
			wrap.appendChild(col);
		});
		root.appendChild(wrap);
	}

	frappe.call({method: "upande_dev_tools.api.requests.get_backlog_board", args: args}).then(function(r) {
		var data = r.message || {tasks: [], requests: []};
		renderColumns(document.querySelector("#board-requests"), data.requests || [], "workflow_state", ["title", "priority"]);
		renderColumns(document.querySelector("#board-tasks"), data.tasks || [], "status", ["subject", "priority"]);
	});
});
</script>
```

- [ ] **Step 5: Add registration**

In `upande_dev_tools/setup.py`'s `register_dev_portal_pages()`, add:

```python
	register_dev_portal_page(
		route="backlog-board",
		title="Backlog Board",
		icon="trello",
		nav_group="Developer",
		sort_order=50,
		roles=["Dev Team"],
	)
```

- [ ] **Step 6: Migrate, build, and run tests**

Run: `bench --site kaitet.local migrate`
Run: `bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_portal`
Expected: PASS

- [ ] **Step 7: Live-verify**

Confirm `/backlog-board` renders for a Dev Team user and denies a no-role user, the same way Task
1 was verified. Additionally confirm `/backlog-board?project=<some-real-project-name>` doesn't
error for a project the Dev Team user can read (`get_backlog_board`'s own permission check on
`project` runs independently of the page's own `Dev Team` gate — both must pass).

- [ ] **Step 8: Commit**

```bash
ruff format upande_dev_tools/www/backlog_board.py upande_dev_tools/setup.py upande_dev_tools/tests/test_portal.py
git add upande_dev_tools/www/backlog-board.html upande_dev_tools/www/backlog_board.py \
  upande_dev_tools/setup.py upande_dev_tools/tests/test_portal.py
git commit -m "feat: add the Backlog Board portal page

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Code Snapshots page (`/code-snapshots`)

**Files:**
- Create: `upande_dev_tools/api/code_snapshots.py`
- Create: `upande_dev_tools/www/code-snapshots.html`
- Create: `upande_dev_tools/www/code_snapshots.py`
- Modify: `upande_dev_tools/setup.py` (add registration call)
- Test: `upande_dev_tools/tests/test_portal.py` (append)
- Test: `upande_dev_tools/tests/test_code_snapshots_api.py` (new file)

**Interfaces:**
- Produces: `upande_dev_tools.api.code_snapshots.get_snapshots(app=None, search=None, start=0,
  limit=50) -> dict` returning `{"rows": [...], "total": <int>}`; `/code-snapshots`, registered
  with `allowed_roles=["Dev Team"]`, `nav_group="Developer"`, `sort_order=60`.

- [ ] **Step 1: Write the failing API test**

Create `upande_dev_tools/tests/test_code_snapshots_api.py`:

```python
# Copyright (c) 2026, Upande Limited

import frappe
from frappe.tests import IntegrationTestCase

from upande_dev_tools.api.code_snapshots import get_snapshots


class IntegrationTestCodeSnapshotsApi(IntegrationTestCase):
	def _make_user(self, email: str, roles: list[str]) -> str:
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Test", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		user = frappe.get_doc("User", email)
		if roles:
			user.add_roles(*roles)
		return email

	def _make_snapshot(self, document_name: str, app: str) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "Code Backup Snapshot",
					"snapshot_time": frappe.utils.now_datetime(),
					"source_type": "DocType",
					"document_name": document_name,
					"app": app,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_get_snapshots_denies_users_without_dev_team_role(self) -> None:
		other = self._make_user("snapshots-noperm@example.test", [])
		frappe.set_user(other)
		try:
			with self.assertRaises(frappe.PermissionError):
				get_snapshots()
		finally:
			frappe.set_user("Administrator")

	def test_get_snapshots_returns_rows_and_total_for_dev_team(self) -> None:
		self._make_snapshot("snap-test-1", "upande_dev_tools")
		dev = self._make_user("snapshots-dev@example.test", ["Dev Team"])
		frappe.set_user(dev)
		try:
			result = get_snapshots(app="upande_dev_tools", limit=5)
		finally:
			frappe.set_user("Administrator")
		self.assertIn("snap-test-1", [row["document_name"] for row in result["rows"]])
		self.assertGreaterEqual(result["total"], 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_code_snapshots_api`
Expected: FAIL — `upande_dev_tools.api.code_snapshots` doesn't exist yet.

- [ ] **Step 3: Implement the API**

`upande_dev_tools/api/code_snapshots.py`:

```python
import frappe

DEV_TOOLS_ROLES = {"Dev Team"}


def _require_dev_team():
	if not DEV_TOOLS_ROLES & set(frappe.get_roles()):
		frappe.throw("Not permitted", frappe.PermissionError)


@frappe.whitelist()
def get_snapshots(
	app: str | None = None, search: str | None = None, start: int = 0, limit: int = 50
) -> dict:
	_require_dev_team()
	filters: dict = {}
	if app:
		filters["app"] = app
	if search:
		filters["document_name"] = ["like", f"%{search}%"]

	rows = frappe.get_all(
		"Code Backup Snapshot",
		filters=filters,
		fields=[
			"name",
			"snapshot_time",
			"source_type",
			"document_name",
			"module",
			"app",
			"changed_since_last_backup",
			"backed_up_by",
			"version_label",
		],
		order_by="snapshot_time desc",
		start=start,
		limit_page_length=limit,
		ignore_permissions=True,
	)
	total = frappe.db.count("Code Backup Snapshot", filters=filters)
	return {"rows": rows, "total": total}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_code_snapshots_api`
Expected: PASS

- [ ] **Step 5: Write the page controller**

`upande_dev_tools/www/code_snapshots.py` — follow the Global Constraints controller shape exactly,
with `route="code-snapshots"`, `page_title="Code Snapshots"`, `active_route="code-snapshots"`.

- [ ] **Step 6: Write the page template**

`upande_dev_tools/www/code-snapshots.html` — follow the Global Constraints template shape. Inside
the `{% call dpx_shell() %}` block:

```html
<div class="dpx-page-hd">
	<div class="eyebrow">Developer</div>
	<div class="ttl">Code Snapshots</div>
	<div class="sub">Search and browse every recorded code backup snapshot.</div>
</div>
<div class="dpx-card">
	<div class="dpx-card-hd">
		<div class="ttl">Snapshots</div>
	</div>
	<div class="dpx-card-body">
		<input type="text" id="snap-search" placeholder="Search by document name…" style="margin-bottom:12px;padding:8px 12px;border-radius:999px;border:1px solid var(--hairline);width:280px;">
		<table id="snap-table">
			<thead><tr><th>Time</th><th>Document</th><th>App/Module</th><th>Source</th><th>Changed</th></tr></thead>
			<tbody></tbody>
		</table>
		<button id="snap-load-more" class="pill" style="margin-top:12px;cursor:pointer;border:1px solid var(--hairline);background:none;">Load more</button>
	</div>
</div>
<script>
frappe.ready(function() {
	var start = 0;
	var limit = 50;
	var search = "";

	function loadRows(reset) {
		if (reset) {
			start = 0;
			document.querySelector("#snap-table tbody").innerHTML = "";
		}
		frappe.call({
			method: "upande_dev_tools.api.code_snapshots.get_snapshots",
			args: {search: search || undefined, start: start, limit: limit}
		}).then(function(r) {
			var data = r.message || {rows: [], total: 0};
			var tbody = document.querySelector("#snap-table tbody");
			data.rows.forEach(function(row) {
				var tr = document.createElement("tr");
				[row.snapshot_time, row.document_name, (row.app || row.module || ""), row.source_type,
					(row.changed_since_last_backup ? "Yes" : "No")].forEach(function(v) {
					var td = document.createElement("td");
					td.textContent = v || "";
					tr.appendChild(td);
				});
				tbody.appendChild(tr);
			});
			start += data.rows.length;
			document.querySelector("#snap-load-more").style.display = start < data.total ? "" : "none";
		});
	}

	document.querySelector("#snap-search").addEventListener("input", function(e) {
		search = e.target.value;
		loadRows(true);
	});
	document.querySelector("#snap-load-more").addEventListener("click", function() { loadRows(false); });

	loadRows(true);
});
</script>
```

- [ ] **Step 7: Add registration**

In `upande_dev_tools/setup.py`'s `register_dev_portal_pages()`, add:

```python
	register_dev_portal_page(
		route="code-snapshots",
		title="Code Snapshots",
		icon="archive",
		nav_group="Developer",
		sort_order=60,
		roles=["Dev Team"],
	)
```

- [ ] **Step 8: Write the access-control tests**

Append to `upande_dev_tools/tests/test_portal.py`'s `IntegrationTestPortal` class (add
`from upande_dev_tools.www.code_snapshots import get_context as code_snapshots_get_context` to
the file's imports):

```python
	def test_code_snapshots_permits_dev_team_and_denies_others(self) -> None:
		dev = self._make_user("code-snapshots-dev@example.test", ["Dev Team"])
		other = self._make_user("code-snapshots-other@example.test", [])

		frappe.set_user(dev)
		try:
			code_snapshots_get_context({})  # must not raise
		finally:
			frappe.set_user("Administrator")

		frappe.set_user(other)
		try:
			with self.assertRaises(frappe.Redirect):
				code_snapshots_get_context({})
			self.assertEqual(frappe.local.flags.redirect_location, "/requests-portal")
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None

	def test_code_snapshots_page_is_registered_with_correct_attributes(self) -> None:
		doc = frappe.get_doc("Dev Portal Page", "code-snapshots")
		self.assertEqual(doc.title, "Code Snapshots")
		self.assertEqual(doc.icon, "archive")
		self.assertEqual(doc.nav_group, "Developer")
		self.assertEqual(doc.sort_order, 60)
		self.assertEqual({row.role for row in doc.allowed_roles}, {"Dev Team"})
```

- [ ] **Step 9: Migrate, build, and run tests**

Run: `bench --site kaitet.local migrate`
Run: `bench build --app upande_dev_tools`
Run: `bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_portal`
Run: `bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_code_snapshots_api`
Expected: both PASS

- [ ] **Step 10: Live-verify**

Confirm `/code-snapshots` renders for a Dev Team user (search box, table, "Load more" button
present) and denies a no-role user. If you can drive the search/pagination interactively (not just
inspect static HTML), confirm the search box actually filters and "Load more" actually appends
rows; otherwise confirm the wiring is present and say so explicitly.

- [ ] **Step 11: Commit**

```bash
ruff format upande_dev_tools/api/code_snapshots.py upande_dev_tools/www/code_snapshots.py \
  upande_dev_tools/setup.py upande_dev_tools/tests/test_portal.py \
  upande_dev_tools/tests/test_code_snapshots_api.py
git add upande_dev_tools/api/code_snapshots.py upande_dev_tools/www/code-snapshots.html \
  upande_dev_tools/www/code_snapshots.py upande_dev_tools/setup.py \
  upande_dev_tools/tests/test_portal.py upande_dev_tools/tests/test_code_snapshots_api.py
git commit -m "feat: add the Code Snapshots portal page and API

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Activity Log page (`/activity-log`)

**Files:**
- Create: `upande_dev_tools/api/activity_log.py`
- Create: `upande_dev_tools/www/activity-log.html`
- Create: `upande_dev_tools/www/activity_log.py`
- Modify: `upande_dev_tools/setup.py` (add registration call)
- Test: `upande_dev_tools/tests/test_portal.py` (append)
- Test: `upande_dev_tools/tests/test_activity_log_api.py` (new file)

**Interfaces:**
- Produces: `upande_dev_tools.api.activity_log.get_activity_log(status=None, search=None, start=0,
  limit=50) -> dict` returning `{"rows": [...], "total": <int>}`; `/activity-log`, registered with
  `allowed_roles=["Dev Team"]`, `nav_group="Developer"`, `sort_order=70`.

- [ ] **Step 1: Write the failing API test**

Create `upande_dev_tools/tests/test_activity_log_api.py`:

```python
# Copyright (c) 2026, Upande Limited

import frappe
from frappe.tests import IntegrationTestCase

from upande_dev_tools.api.activity_log import get_activity_log


class IntegrationTestActivityLogApi(IntegrationTestCase):
	def _make_user(self, email: str, roles: list[str]) -> str:
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Test", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		user = frappe.get_doc("User", email)
		if roles:
			user.add_roles(*roles)
		return email

	def _make_activity(self, title: str, status: str) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "Developer Activity Log",
					"activity_time": frappe.utils.now_datetime(),
					"activity_type": "Backup",
					"title": title,
					"status": status,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_get_activity_log_denies_users_without_dev_team_role(self) -> None:
		other = self._make_user("activity-log-noperm@example.test", [])
		frappe.set_user(other)
		try:
			with self.assertRaises(frappe.PermissionError):
				get_activity_log()
		finally:
			frappe.set_user("Administrator")

	def test_get_activity_log_filters_by_status(self) -> None:
		self._make_activity("activity-log-test-error", "Error")
		self._make_activity("activity-log-test-success", "Success")
		dev = self._make_user("activity-log-dev@example.test", ["Dev Team"])
		frappe.set_user(dev)
		try:
			result = get_activity_log(status="Error", search="activity-log-test", limit=10)
		finally:
			frappe.set_user("Administrator")
		titles = [row["title"] for row in result["rows"]]
		self.assertIn("activity-log-test-error", titles)
		self.assertNotIn("activity-log-test-success", titles)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_activity_log_api`
Expected: FAIL — `upande_dev_tools.api.activity_log` doesn't exist yet.

- [ ] **Step 3: Implement the API**

`upande_dev_tools/api/activity_log.py`:

```python
import frappe

DEV_TOOLS_ROLES = {"Dev Team"}


def _require_dev_team():
	if not DEV_TOOLS_ROLES & set(frappe.get_roles()):
		frappe.throw("Not permitted", frappe.PermissionError)


@frappe.whitelist()
def get_activity_log(
	status: str | None = None, search: str | None = None, start: int = 0, limit: int = 50
) -> dict:
	_require_dev_team()
	filters: dict = {}
	if status:
		filters["status"] = status
	if search:
		filters["title"] = ["like", f"%{search}%"]

	rows = frappe.get_all(
		"Developer Activity Log",
		filters=filters,
		fields=[
			"name",
			"activity_time",
			"activity_type",
			"title",
			"description",
			"status",
			"source",
			"reference_doctype",
			"reference_name",
			"performed_by",
		],
		order_by="activity_time desc",
		start=start,
		limit_page_length=limit,
		ignore_permissions=True,
	)
	total = frappe.db.count("Developer Activity Log", filters=filters)
	return {"rows": rows, "total": total}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_activity_log_api`
Expected: PASS

- [ ] **Step 5: Write the page controller**

`upande_dev_tools/www/activity_log.py` — follow the Global Constraints controller shape exactly,
with `route="activity-log"`, `page_title="Activity Log"`, `active_route="activity-log"`. Also read
an optional `status` query parameter into context (mirroring Task 2's `project` parameter), so a
link like `/activity-log?status=Error` pre-selects the filter:

```python
def get_context(context):
	enforce_page_access("activity-log")
	context = frappe._dict(context)
	context.no_cache = 1
	context.page_title = "Activity Log"
	context.active_route = "activity-log"
	context.csrf_token = frappe.sessions.get_csrf_token()
	context.initial_status = frappe.form_dict.get("status") or ""
	return context
```

- [ ] **Step 6: Write the page template**

`upande_dev_tools/www/activity-log.html` — follow the Global Constraints template shape. The
status filter's options come from the doctype's own `status` field meta, not a hardcoded second
copy of the list. Inside the `{% call dpx_shell() %}` block:

```html
<div class="dpx-page-hd">
	<div class="eyebrow">Developer</div>
	<div class="ttl">Activity Log</div>
	<div class="sub">Every recorded developer activity, with an error filter.</div>
</div>
<div class="dpx-card">
	<div class="dpx-card-hd"><div class="ttl">Activity</div></div>
	<div class="dpx-card-body">
		<input type="text" id="activity-search" placeholder="Search by title…" style="margin-right:10px;padding:8px 12px;border-radius:999px;border:1px solid var(--hairline);width:240px;">
		<select id="activity-status" style="padding:8px 12px;border-radius:999px;border:1px solid var(--hairline);"></select>
		<table id="activity-table" style="margin-top:12px;">
			<thead><tr><th>Time</th><th>Type</th><th>Title</th><th>Status</th><th>Source</th></tr></thead>
			<tbody></tbody>
		</table>
		<button id="activity-load-more" class="pill" style="margin-top:12px;cursor:pointer;border:1px solid var(--hairline);background:none;">Load more</button>
	</div>
</div>
<script>
frappe.ready(function() {
	var start = 0;
	var limit = 50;
	var search = "";
	var status = {{ initial_status | tojson }};

	var statusSelect = document.querySelector("#activity-status");
	["", "Success", "Warning", "Error", "Info"].forEach(function(opt) {
		var el = document.createElement("option");
		el.value = opt;
		el.textContent = opt || "All";
		if (opt === status) el.selected = true;
		statusSelect.appendChild(el);
	});

	function loadRows(reset) {
		if (reset) {
			start = 0;
			document.querySelector("#activity-table tbody").innerHTML = "";
		}
		frappe.call({
			method: "upande_dev_tools.api.activity_log.get_activity_log",
			args: {status: status || undefined, search: search || undefined, start: start, limit: limit}
		}).then(function(r) {
			var data = r.message || {rows: [], total: 0};
			var tbody = document.querySelector("#activity-table tbody");
			data.rows.forEach(function(row) {
				var tr = document.createElement("tr");
				[row.activity_time, row.activity_type, row.title, row.status, row.source].forEach(function(v) {
					var td = document.createElement("td");
					td.textContent = v || "";
					tr.appendChild(td);
				});
				tbody.appendChild(tr);
			});
			start += data.rows.length;
			document.querySelector("#activity-load-more").style.display = start < data.total ? "" : "none";
		});
	}

	document.querySelector("#activity-search").addEventListener("input", function(e) {
		search = e.target.value;
		loadRows(true);
	});
	statusSelect.addEventListener("change", function(e) {
		status = e.target.value;
		loadRows(true);
	});
	document.querySelector("#activity-load-more").addEventListener("click", function() { loadRows(false); });

	loadRows(true);
});
</script>
```

- [ ] **Step 7: Add registration**

In `upande_dev_tools/setup.py`'s `register_dev_portal_pages()`, add:

```python
	register_dev_portal_page(
		route="activity-log",
		title="Activity Log",
		icon="activity",
		nav_group="Developer",
		sort_order=70,
		roles=["Dev Team"],
	)
```

- [ ] **Step 8: Write the access-control tests**

Append to `upande_dev_tools/tests/test_portal.py`'s `IntegrationTestPortal` class (add
`from upande_dev_tools.www.activity_log import get_context as activity_log_get_context` to the
file's imports):

```python
	def test_activity_log_permits_dev_team_and_denies_others(self) -> None:
		dev = self._make_user("activity-log-page-dev@example.test", ["Dev Team"])
		other = self._make_user("activity-log-page-other@example.test", [])

		frappe.set_user(dev)
		try:
			activity_log_get_context({})  # must not raise
		finally:
			frappe.set_user("Administrator")

		frappe.set_user(other)
		try:
			with self.assertRaises(frappe.Redirect):
				activity_log_get_context({})
			self.assertEqual(frappe.local.flags.redirect_location, "/requests-portal")
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None

	def test_activity_log_page_is_registered_with_correct_attributes(self) -> None:
		doc = frappe.get_doc("Dev Portal Page", "activity-log")
		self.assertEqual(doc.title, "Activity Log")
		self.assertEqual(doc.icon, "activity")
		self.assertEqual(doc.nav_group, "Developer")
		self.assertEqual(doc.sort_order, 70)
		self.assertEqual({row.role for row in doc.allowed_roles}, {"Dev Team"})

	def test_developer_nav_group_lists_all_seven_tools_in_order(self) -> None:
		dev = self._make_user("developer-nav-order-full@example.test", ["Dev Team"])
		items = get_nav_items(dev)
		developer_routes = [item["route"] for item in items if item["nav_group"] == "Developer"]
		self.assertEqual(
			developer_routes,
			[
				"dev-dashboard",
				"hooks-explorer",
				"code-editor",
				"my-day",
				"backlog-board",
				"code-snapshots",
				"activity-log",
			],
		)
```

(`get_nav_items` is already imported at the top of `test_portal.py` from Task 2 of Sub-project 1
— no new import needed for this last test.)

- [ ] **Step 9: Migrate, build, and run tests**

Run: `bench --site kaitet.local migrate`
Run: `bench build --app upande_dev_tools`
Run: `bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_portal`
Run: `bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_activity_log_api`
Expected: both PASS

- [ ] **Step 10: Live-verify**

Confirm `/activity-log` and `/activity-log?status=Error` both render for a Dev Team user (the
latter pre-selecting "Error" in the status dropdown) and deny a no-role user.

- [ ] **Step 11: Commit**

```bash
ruff format upande_dev_tools/api/activity_log.py upande_dev_tools/www/activity_log.py \
  upande_dev_tools/setup.py upande_dev_tools/tests/test_portal.py \
  upande_dev_tools/tests/test_activity_log_api.py
git add upande_dev_tools/api/activity_log.py upande_dev_tools/www/activity-log.html \
  upande_dev_tools/www/activity_log.py upande_dev_tools/setup.py \
  upande_dev_tools/tests/test_portal.py upande_dev_tools/tests/test_activity_log_api.py
git commit -m "feat: add the Activity Log portal page and API

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: Make the Tools Dashboard's cards clickable

**Files:**
- Modify: `upande_dev_tools/public/js/dev-dashboard-portal.js`

**Interfaces:**
- Consumes: `/code-snapshots` and `/activity-log` (Tasks 3-4, must exist before this task runs).
- Produces: no new interfaces — purely a front-end link-wiring change to an existing file.

This task depends on Tasks 3 and 4 (it links to their routes) — dispatch it only after both are
done.

- [ ] **Step 1: Read the current file**

Read `upande_dev_tools/public/js/dev-dashboard-portal.js` in full before editing — this is a
targeted change to a handful of render functions, not a rewrite.

- [ ] **Step 2: Make the relevant card headers and KPIs into links**

In the functions that render the "Recent Backup Snapshots" card (`udt_render_backup_table` or
equivalent, check the actual function name in the file) and the KPI tiles for "Snapshots Today" /
"Last Backup", wrap the card header's title text (and/or add a small "View all →" link inside the
card header, matching this project's existing `.udt-link` class already used elsewhere in this
same file for "View all apps" etc.) in an anchor tag: `<a href="/code-snapshots" class="udt-link">`.

Do the same for the "Recent Errors" card, linking to `/activity-log?status=Error`, and the
"Recent Activity" card, linking to `/activity-log` (plain, no status filter).

Do not change anything about the version-check KPIs, the field-difference card, or the
hooks-summary card — those keep their existing desk (`/app/<slug>`) / `/hooks-explorer` links
unchanged, per the spec's explicit scope (no portal page for version checks or field differences
in this sub-project).

- [ ] **Step 3: Rebuild and live-verify**

Run: `bench build --app upande_dev_tools`

Confirm live (as a Dev Team user) that `/dev-dashboard`'s "Recent Backup Snapshots", "Recent
Errors", and "Recent Activity" card headers now link to `/code-snapshots`,
`/activity-log?status=Error`, and `/activity-log` respectively, and that clicking through (or, if
you can't drive a real click, confirming the rendered `href` values directly) lands on a working
page in each case.

- [ ] **Step 4: Run the acceptance check**

Run every module this whole plan touched (plus Sub-project 2's, to confirm no regression there):

```bash
bench --site kaitet.local run-tests --module upande_dev_tools.upande_dev_tools.doctype.dev_portal_page.test_dev_portal_page
bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_portal
bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_dev_portal_settings_api
bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_code_snapshots_api
bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_activity_log_api
bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_requests_api
bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_deployments_api
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add upande_dev_tools/public/js/dev-dashboard-portal.js
git commit -m "feat: link Tools Dashboard cards to the new Code Snapshots/Activity Log pages

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Sub-project 3 acceptance check

After Task 5, the Developer nav group has seven pages in order: Dashboard, Hooks Explorer, Code
Editor, My Day, Backlog Board, Code Snapshots, Activity Log — all gated to `Dev Team`, all
following the identical shell/access-control pattern. A Dev Team user can go from the dashboard's
summary cards straight into a full searchable view of snapshots or errors without touching the
desk. My Day and the Backlog Board finally give Phase 1's `get_my_day`/`get_backlog_board`
endpoints the front-end they've been missing since Phase 1 shipped.
