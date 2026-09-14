# Phase 2 Sub-project 4: Projects Manager Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new "Management" nav group with two pages — `/pm-dashboard` (portfolio + per-project
health, becomes the Projects Manager home route) and `/review-queue` (front-end for Phase 1's
existing Request approval workflow) — gated to the `Projects Manager` role.

**Architecture:** `/pm-dashboard` gets one new, small, unpaginated aggregation API endpoint
(`api/project_health.py`). `/review-queue` is a pure front-end for two existing, unchanged Phase 1
functions (`get_review_queue`, `triage_request`) — the real authorization for actually approving/
rejecting/deferring a Request already lives in Phase 1's native Frappe Workflow (role-gated at the
transition level), so this task adds no new authorization logic of its own. Both pages follow the
exact shape every prior portal page in this project uses.

**Tech Stack:** Frappe v16 `www` pages, Jinja2, the existing `Project`/`Task`/`Request` doctypes.

**Spec:** `docs/specs/2026-09-14-portal-pm-dashboard-design.md`

## Global Constraints

- Everything belongs to the single existing `Upande Dev Tools` module — no new module.
- Bench root `/home/jk/Projects/upande-local-bench-v16`, site `kaitet.local`. Whole-app
  `bench run-tests` is broken by a pre-existing unrelated ERPNext bug — always scope test runs
  with `--module`.
- `ruff` is on PATH (tabs, double quotes, 110 char lines) for every Python file touched.
- Every new page's `.py` controller follows this exact shape (only `page_title`/`active_route`
  differ per page), matching every prior page in this project:
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
  roles, require_all_roles=False)` in `upande_dev_tools/setup.py`'s `register_dev_portal_pages()`.
  Do not alter `register_dev_portal_page`/`run_setup`/`create_task_custom_fields` themselves.
- `upande_dev_tools/tests/test_portal.py`'s `IntegrationTestPortal` class is where every new
  access-control/registration test in this plan is appended — reuse its existing
  `_make_user`/`_make_page` helpers, do not redeclare the class or duplicate imports.
- Both new pages are gated to `allowed_roles=["Projects Manager"]`, nav_group `"Management"` — a
  NEW nav group distinct from every prior page's `"Developer"` group.
- This bench has a real, large historical `Request`/`Task`/`Project` dataset already in it
  (26 real Projects, ~1179 imported Request/Task records, ~29 real users holding `Projects
  Manager`) — irrelevant to your own tests (which use throwaway fixtures), but useful for live
  verification: real data will actually show up on both pages.

---

### Task 1: PM Dashboard page (`/pm-dashboard`)

**Files:**
- Create: `upande_dev_tools/api/project_health.py`
- Create: `upande_dev_tools/www/pm-dashboard.html`
- Create: `upande_dev_tools/www/pm_dashboard.py`
- Modify: `upande_dev_tools/setup.py` (add registration call)
- Test: `upande_dev_tools/tests/test_portal.py` (append)
- Test: `upande_dev_tools/tests/test_project_health_api.py` (new file)

**Interfaces:**
- Produces: `upande_dev_tools.api.project_health.get_project_health() -> dict` returning
  `{"project_count": int, "total_overdue_tasks": int, "total_open_requests": int, "projects":
  [...]}`; `/pm-dashboard`, registered with `allowed_roles=["Projects Manager"]`,
  `nav_group="Management"`, `sort_order=10`. This route is already named in `portal.py`'s
  `HOME_ROUTE_BY_ROLE` as the Projects Manager home route — this task is what makes it a real,
  reachable page for the first time.

- [ ] **Step 1: Write the failing API test**

Create `upande_dev_tools/tests/test_project_health_api.py`:

```python
# Copyright (c) 2026, Upande Limited

import frappe
from frappe.tests import IntegrationTestCase

from upande_dev_tools.api.project_health import get_project_health


class IntegrationTestProjectHealthApi(IntegrationTestCase):
	def _make_user(self, email: str, roles: list[str]) -> str:
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Test", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		user = frappe.get_doc("User", email)
		if roles:
			user.add_roles(*roles)
		return email

	def test_get_project_health_denies_users_without_projects_manager_role(self) -> None:
		other = self._make_user("project-health-noperm@example.test", ["Dev Team"])
		frappe.set_user(other)
		try:
			with self.assertRaises(frappe.PermissionError):
				get_project_health()
		finally:
			frappe.set_user("Administrator")

	def test_get_project_health_returns_aggregate_and_per_project_data(self) -> None:
		pm = self._make_user("project-health-pm@example.test", ["Projects Manager"])
		frappe.set_user(pm)
		try:
			result = get_project_health()
		finally:
			frappe.set_user("Administrator")
		self.assertIn("project_count", result)
		self.assertIn("total_overdue_tasks", result)
		self.assertIn("total_open_requests", result)
		self.assertIsInstance(result["projects"], list)
		if result["projects"]:
			row = result["projects"][0]
			for key in ("name", "project_name", "status", "total_tasks", "completed_tasks", "overdue_tasks", "open_requests"):
				self.assertIn(key, row)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_project_health_api`
Expected: FAIL — `upande_dev_tools.api.project_health` doesn't exist yet.

- [ ] **Step 3: Implement the API**

`upande_dev_tools/api/project_health.py`:

```python
import frappe
from frappe.utils import today

PM_ROLES = {"Projects Manager"}


def _require_projects_manager():
	if not PM_ROLES & set(frappe.get_roles()):
		frappe.throw("Not permitted", frappe.PermissionError)


@frappe.whitelist()
def get_project_health() -> dict:
	_require_projects_manager()

	projects = frappe.get_all(
		"Project",
		filters={"status": ["!=", "Cancelled"]},
		fields=["name", "project_name", "status"],
		order_by="project_name asc",
		ignore_permissions=True,
	)
	for project in projects:
		project["total_tasks"] = frappe.db.count("Task", {"project": project.name})
		project["completed_tasks"] = frappe.db.count(
			"Task", {"project": project.name, "status": "Completed"}
		)
		project["overdue_tasks"] = frappe.db.count(
			"Task",
			{
				"project": project.name,
				"status": ["not in", ["Completed", "Cancelled"]],
				"exp_end_date": ["<", today()],
			},
		)
		project["open_requests"] = frappe.db.count(
			"Request", {"project": project.name, "workflow_state": ["not in", ["Completed", "Rejected"]]}
		)

	return {
		"project_count": len(projects),
		"total_overdue_tasks": sum(p["overdue_tasks"] for p in projects),
		"total_open_requests": sum(p["open_requests"] for p in projects),
		"projects": projects,
	}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_project_health_api`
Expected: PASS

- [ ] **Step 5: Write the page controller**

`upande_dev_tools/www/pm_dashboard.py` — follow the Global Constraints controller shape exactly,
with `route="pm-dashboard"`, `page_title="Dashboard"`, `active_route="pm-dashboard"`.

- [ ] **Step 6: Write the page template**

`upande_dev_tools/www/pm-dashboard.html` — follow the Global Constraints template shape. Inside
the `{% call dpx_shell() %}` block:

```html
<div class="dpx-page-hd">
	<div class="eyebrow">Management</div>
	<div class="ttl">Dashboard</div>
	<div class="sub">Portfolio health across every active project.</div>
</div>
<div class="dpx-kpis" id="pm-kpis"></div>
<div class="dpx-card">
	<div class="dpx-card-hd"><div class="ttl">Projects</div></div>
	<div class="dpx-card-body">
		<table id="pm-projects-table">
			<thead>
				<tr><th>Project</th><th>Status</th><th>Completion</th><th>Overdue</th><th>Open Requests</th><th></th></tr>
			</thead>
			<tbody></tbody>
		</table>
	</div>
</div>
<script>
frappe.ready(function() {
	function kpiTile(label, value) {
		var kpi = document.createElement("div");
		kpi.className = "dpx-kpi";
		var lbl = document.createElement("div");
		lbl.className = "lbl";
		lbl.textContent = label;
		var val = document.createElement("div");
		val.className = "v";
		val.textContent = value;
		kpi.appendChild(lbl);
		kpi.appendChild(val);
		return kpi;
	}

	frappe.call({method: "upande_dev_tools.api.project_health.get_project_health"}).then(function(r) {
		var data = r.message || {project_count: 0, total_overdue_tasks: 0, total_open_requests: 0, projects: []};

		var kpiRoot = document.querySelector("#pm-kpis");
		kpiRoot.appendChild(kpiTile("Active Projects", data.project_count));
		kpiRoot.appendChild(kpiTile("Overdue Tasks", data.total_overdue_tasks));
		kpiRoot.appendChild(kpiTile("Open Requests", data.total_open_requests));

		var tbody = document.querySelector("#pm-projects-table tbody");
		data.projects.forEach(function(project) {
			var tr = document.createElement("tr");

			var nameTd = document.createElement("td");
			nameTd.textContent = project.project_name || project.name;
			tr.appendChild(nameTd);

			var statusTd = document.createElement("td");
			statusTd.textContent = project.status;
			tr.appendChild(statusTd);

			var completionTd = document.createElement("td");
			var pct = project.total_tasks ? Math.round((project.completed_tasks / project.total_tasks) * 100) : 0;
			completionTd.textContent = pct + "% (" + project.completed_tasks + "/" + project.total_tasks + ")";
			tr.appendChild(completionTd);

			var overdueTd = document.createElement("td");
			overdueTd.textContent = project.overdue_tasks;
			tr.appendChild(overdueTd);

			var requestsTd = document.createElement("td");
			requestsTd.textContent = project.open_requests;
			tr.appendChild(requestsTd);

			var linkTd = document.createElement("td");
			var link = document.createElement("a");
			link.className = "udt-link";
			link.href = "/backlog-board?project=" + encodeURIComponent(project.name);
			link.textContent = "View backlog";
			linkTd.appendChild(link);
			tr.appendChild(linkTd);

			tbody.appendChild(tr);
		});
	});
});
</script>
```

- [ ] **Step 7: Add registration**

In `upande_dev_tools/setup.py`'s `register_dev_portal_pages()`, add:

```python
	register_dev_portal_page(
		route="pm-dashboard",
		title="Dashboard",
		icon="home",
		nav_group="Management",
		sort_order=10,
		roles=["Projects Manager"],
	)
```

- [ ] **Step 8: Write the access-control tests**

Append to `upande_dev_tools/tests/test_portal.py`'s `IntegrationTestPortal` class (add
`from upande_dev_tools.www.pm_dashboard import get_context as pm_dashboard_get_context` to the
file's imports):

```python
	def test_pm_dashboard_permits_projects_manager_and_denies_others(self) -> None:
		pm = self._make_user("pm-dashboard-pm@example.test", ["Projects Manager"])
		other = self._make_user("pm-dashboard-other@example.test", [])

		frappe.set_user(pm)
		try:
			pm_dashboard_get_context({})  # must not raise
		finally:
			frappe.set_user("Administrator")

		frappe.set_user(other)
		try:
			with self.assertRaises(frappe.Redirect):
				pm_dashboard_get_context({})
			self.assertEqual(frappe.local.flags.redirect_location, "/requests-portal")
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None

	def test_pm_dashboard_page_is_registered_with_correct_attributes(self) -> None:
		doc = frappe.get_doc("Dev Portal Page", "pm-dashboard")
		self.assertEqual(doc.title, "Dashboard")
		self.assertEqual(doc.icon, "home")
		self.assertEqual(doc.nav_group, "Management")
		self.assertEqual(doc.sort_order, 10)
		self.assertEqual({row.role for row in doc.allowed_roles}, {"Projects Manager"})

	def test_resolve_home_route_for_projects_manager_is_now_reachable(self) -> None:
		# Closes the same gap Sub-project 2's Task 2 closed for Dev Team/dev-dashboard:
		# /pm-dashboard is now a real, registered, permitted page for Projects Manager.
		pm = self._make_user("pm-dashboard-home-route@example.test", ["Projects Manager"])
		self.assertEqual(resolve_home_route(pm), "/pm-dashboard")
		frappe.set_user(pm)
		try:
			enforce_page_access("pm-dashboard")  # must not raise
		finally:
			frappe.set_user("Administrator")
```

(`resolve_home_route`/`enforce_page_access` are already imported at the top of `test_portal.py`
from Sub-project 1 — no new import needed for the last test.)

- [ ] **Step 9: Migrate, build, and run tests**

Run: `bench --site kaitet.local migrate`
Run: `bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_portal`
Run: `bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_project_health_api`
Expected: both PASS

- [ ] **Step 10: Live-verify**

Using the established live-render technique (a throwaway Projects Manager user, authenticated
HTTP request against the running dev server at `http://kaitet.local:8002`), confirm `/pm-dashboard`
renders with real KPI numbers and a real project table (this bench has 26 real projects — confirm
the count matches), a Dev-Team-only user (no Projects Manager role) is redirected away, and
`/dev-tools` now redirects a Projects Manager user all the way to a working `/pm-dashboard` (the
same end-to-end path Sub-project 2's Task 2 verified for Dev Team). Clean up the throwaway user
afterward.

- [ ] **Step 11: Commit**

```bash
ruff format upande_dev_tools/api/project_health.py upande_dev_tools/www/pm_dashboard.py \
  upande_dev_tools/setup.py upande_dev_tools/tests/test_portal.py \
  upande_dev_tools/tests/test_project_health_api.py
git add upande_dev_tools/api/project_health.py upande_dev_tools/www/pm-dashboard.html \
  upande_dev_tools/www/pm_dashboard.py upande_dev_tools/setup.py \
  upande_dev_tools/tests/test_portal.py upande_dev_tools/tests/test_project_health_api.py
git commit -m "feat: add the PM Dashboard portal page and project health API

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Review Queue page (`/review-queue`)

**Files:**
- Create: `upande_dev_tools/www/review-queue.html`
- Create: `upande_dev_tools/www/review_queue.py`
- Modify: `upande_dev_tools/setup.py` (add registration call)
- Test: `upande_dev_tools/tests/test_portal.py` (append)

**Interfaces:**
- Consumes: the existing, unchanged `upande_dev_tools.api.requests.get_review_queue` and
  `upande_dev_tools.api.requests.triage_request` (both from Phase 1 — `triage_request` already
  re-checks the `Projects Manager` role via `apply_workflow`'s own Workflow Transition rules, so
  this task adds no new authorization logic).
- Produces: `/review-queue`, registered with `allowed_roles=["Projects Manager"]`,
  `nav_group="Management"`, `sort_order=20`.

- [ ] **Step 1: Write the failing tests**

Append to `upande_dev_tools/tests/test_portal.py`'s `IntegrationTestPortal` class (add
`from upande_dev_tools.www.review_queue import get_context as review_queue_get_context` to the
file's imports):

```python
	def test_review_queue_permits_projects_manager_and_denies_others(self) -> None:
		pm = self._make_user("review-queue-pm@example.test", ["Projects Manager"])
		other = self._make_user("review-queue-other@example.test", [])

		frappe.set_user(pm)
		try:
			review_queue_get_context({})  # must not raise
		finally:
			frappe.set_user("Administrator")

		frappe.set_user(other)
		try:
			with self.assertRaises(frappe.Redirect):
				review_queue_get_context({})
			self.assertEqual(frappe.local.flags.redirect_location, "/requests-portal")
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None

	def test_review_queue_page_is_registered_with_correct_attributes(self) -> None:
		doc = frappe.get_doc("Dev Portal Page", "review-queue")
		self.assertEqual(doc.title, "Review Queue")
		self.assertEqual(doc.icon, "check-circle")
		self.assertEqual(doc.nav_group, "Management")
		self.assertEqual(doc.sort_order, 20)
		self.assertEqual({row.role for row in doc.allowed_roles}, {"Projects Manager"})

	def test_management_nav_group_lists_both_pages_in_order(self) -> None:
		pm = self._make_user("management-nav-order@example.test", ["Projects Manager"])
		items = get_nav_items(pm)
		management_routes = [item["route"] for item in items if item["nav_group"] == "Management"]
		self.assertEqual(management_routes, ["pm-dashboard", "review-queue"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_portal`
Expected: FAIL — `upande_dev_tools.www.review_queue` doesn't exist yet.

- [ ] **Step 3: Write the page controller**

`upande_dev_tools/www/review_queue.py` — follow the Global Constraints controller shape exactly,
with `route="review-queue"`, `page_title="Review Queue"`, `active_route="review-queue"`.

- [ ] **Step 4: Write the page template**

`upande_dev_tools/www/review-queue.html` — follow the Global Constraints template shape. Inside
the `{% call dpx_shell() %}` block:

```html
<div class="dpx-page-hd">
	<div class="eyebrow">Management</div>
	<div class="ttl">Review Queue</div>
	<div class="sub">Requests awaiting your approval.</div>
</div>
<div class="dpx-card">
	<div class="dpx-card-hd"><div class="ttl">Pending Requests</div></div>
	<div class="dpx-card-body">
		<table id="review-queue-table">
			<thead>
				<tr><th>Title</th><th>Type</th><th>Area</th><th>Raised By</th><th>Age</th><th>Project</th><th>Priority</th><th></th></tr>
			</thead>
			<tbody></tbody>
		</table>
	</div>
</div>
<script>
frappe.ready(function() {
	function buildRow(request) {
		var tr = document.createElement("tr");
		tr.dataset.name = request.name;

		["title", "request_type", "product_area", "raised_by_user"].forEach(function(field) {
			var td = document.createElement("td");
			td.textContent = request[field] || "";
			tr.appendChild(td);
		});

		var ageTd = document.createElement("td");
		ageTd.textContent = request.creation || "";
		tr.appendChild(ageTd);

		var projectTd = document.createElement("td");
		var projectInput = document.createElement("input");
		projectInput.type = "text";
		projectInput.className = "rq-project";
		projectInput.value = request.project || "";
		projectInput.placeholder = "Project name";
		projectTd.appendChild(projectInput);
		tr.appendChild(projectTd);

		var priorityTd = document.createElement("td");
		var prioritySelect = document.createElement("select");
		prioritySelect.className = "rq-priority";
		["Low", "Medium", "High", "Urgent"].forEach(function(p) {
			var opt = document.createElement("option");
			opt.value = p;
			opt.textContent = p;
			prioritySelect.appendChild(opt);
		});
		priorityTd.appendChild(prioritySelect);
		tr.appendChild(priorityTd);

		var actionsTd = document.createElement("td");
		[["Approve", "Approve"], ["Reject", "Reject"], ["Defer", "Defer"]].forEach(function(pair) {
			var btn = document.createElement("button");
			btn.className = "pill";
			btn.style.marginRight = "6px";
			btn.textContent = pair[0];
			btn.addEventListener("click", function() {
				frappe.call({
					method: "upande_dev_tools.api.requests.triage_request",
					args: {
						name: request.name,
						action: pair[1],
						project: projectInput.value || undefined,
						priority: prioritySelect.value || undefined
					}
				}).then(function() {
					tr.remove();
				});
			});
			actionsTd.appendChild(btn);
		});
		tr.appendChild(actionsTd);

		return tr;
	}

	frappe.call({method: "upande_dev_tools.api.requests.get_review_queue"}).then(function(r) {
		var tbody = document.querySelector("#review-queue-table tbody");
		(r.message || []).forEach(function(request) {
			tbody.appendChild(buildRow(request));
		});
	});
});
</script>
```

- [ ] **Step 5: Add registration**

In `upande_dev_tools/setup.py`'s `register_dev_portal_pages()`, add:

```python
	register_dev_portal_page(
		route="review-queue",
		title="Review Queue",
		icon="check-circle",
		nav_group="Management",
		sort_order=20,
		roles=["Projects Manager"],
	)
```

- [ ] **Step 6: Migrate, build, and run tests**

Run: `bench --site kaitet.local migrate`
Run: `bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_portal`
Expected: PASS

- [ ] **Step 7: Live-verify**

Confirm `/review-queue` renders for a Projects Manager user and denies a no-role user, the same way
Task 1 was verified. If there are any real `Under Review` Requests in this bench's dataset (check
first — the imported historical backlog may include some), confirm the page lists them; if you can
drive an actual approve/reject/defer click (not just inspect static HTML), create a throwaway test
Request in `Under Review` state, approve it via the page, and confirm it disappears from the table
and its `workflow_state` actually changed in the DB. Clean up any throwaway data afterward.

- [ ] **Step 8: Commit**

```bash
ruff format upande_dev_tools/www/review_queue.py upande_dev_tools/setup.py upande_dev_tools/tests/test_portal.py
git add upande_dev_tools/www/review-queue.html upande_dev_tools/www/review_queue.py \
  upande_dev_tools/setup.py upande_dev_tools/tests/test_portal.py
git commit -m "feat: add the Review Queue portal page

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Sub-project 4 acceptance check

After Task 2, run every module this plan touched, plus the full acceptance list from
Sub-projects 2-3 to confirm no regression:

```bash
bench --site kaitet.local run-tests --module upande_dev_tools.upande_dev_tools.doctype.dev_portal_page.test_dev_portal_page
bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_portal
bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_dev_portal_settings_api
bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_project_health_api
bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_code_snapshots_api
bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_activity_log_api
bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_requests_api
bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_deployments_api
```

Expected: all pass. At this point: a Projects Manager reaches a real, working `/pm-dashboard` home
page with portfolio-wide KPIs and per-project health (drilling into the existing Backlog Board),
and can actually approve/reject/defer pending Requests from `/review-queue` without touching the
desk. The portal now serves three distinct audiences end-to-end for its first two roles (Dev Team,
Projects Manager) — Sub-project 5 (Customer/Employee portal) is the last piece of Phase 2.
