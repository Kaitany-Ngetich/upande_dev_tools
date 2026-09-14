# Phase 2 Sub-project 5: Requests Portal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `/requests-portal` — a submit-and-track page for any authenticated user, becoming the
default home route for anyone who isn't Dev Team or Projects Manager — the last piece of Phase 2.

**Architecture:** Pure front-end for two existing, unchanged Phase 1 functions
(`create_request`, `get_my_requests`). No new API. One new `Dev Portal Page` registration, gated to
`allowed_roles=["All"]` (the one role every Frappe user always holds), in a new `"Requests"` nav
group visible to every audience this project has built so far.

**Tech Stack:** Frappe v16 `www` page, Jinja2, Phase 1's `Request` doctype/API (unchanged).

**Spec:** `docs/specs/2026-09-14-portal-requests-portal-design.md`

## Global Constraints

- Everything belongs to the single existing `Upande Dev Tools` module — no new module.
- Bench root `/home/jk/Projects/upande-local-bench-v16`, site `kaitet.local`. Whole-app
  `bench run-tests` is broken by a pre-existing unrelated ERPNext bug — always scope test runs
  with `--module`.
- `ruff` is on PATH (tabs, double quotes, 110 char lines) for the Python file touched.
- The page controller follows this exact shape, matching every prior page in this project:
  ```python
  # Copyright (c) 2026, shadrack@upande.com and contributors
  # For license information, please see license.txt

  import frappe

  from upande_dev_tools.portal import enforce_page_access

  no_cache = 1


  def get_context(context):
  	enforce_page_access("requests-portal")
  	context = frappe._dict(context)
  	context.no_cache = 1
  	context.page_title = "My Requests"
  	context.active_route = "requests-portal"
  	context.csrf_token = frappe.sessions.get_csrf_token()
  	return context
  ```
- The template follows the exact shape every prior page uses:
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
- The `request_type` dropdown's options are a literal list matching `Request.request_type`'s real
  Select field options (`Feature`/`Bug`/`Master Data`/`Question`/`Note`) — this project already
  ruled on the equivalent tension for the Activity Log page's status dropdown (Sub-project 3,
  Task 4): building a dynamic doctype-meta-fetch mechanism for a plain `www` page is unrequested
  scope invention with no precedent anywhere in this codebase; a literal list that matches the
  doctype's real values today is the established, accepted pattern. Do not attempt to fetch field
  meta dynamically.
- `create_request` itself still enforces that only a `Dev Team` member may submit a `request_type`
  of `Note` (`upande_dev_tools/upande_dev_tools/doctype/request/request.py`'s `validate()`,
  unchanged, out of this sub-project's scope) — a non-Dev-Team user selecting "Note" and submitting
  will get a normal server-side validation error surfaced by `frappe.call`'s own error handling
  (the same mechanism the Review Queue's approve-without-project error already relies on). This is
  acceptable, expected behavior for an edge case — do not add client-side logic to hide or filter
  the "Note" option based on the viewer's own roles; that's more complexity than this small
  sub-project's scope calls for, and the server-side rejection is already clear.
- Registration goes through `register_dev_portal_page(route, title, icon, nav_group, sort_order,
  roles, require_all_roles=False)` in `upande_dev_tools/setup.py`'s `register_dev_portal_pages()`.
  Do not alter `register_dev_portal_page`/`run_setup`/`create_task_custom_fields` themselves.
- `upande_dev_tools/tests/test_portal.py`'s `IntegrationTestPortal` class is where every new
  access-control/registration test in this plan is appended — reuse its existing
  `_make_user`/`_make_page` helpers, do not redeclare the class or duplicate imports.
- This bench has a real, large historical dataset (1179 imported Request/Task records, 26 real
  Projects, real users across multiple roles) — irrelevant to this task's own throwaway-fixture
  tests, but useful for live verification: submitting a real request via this page and seeing it
  appear in "My Requests" is a meaningful end-to-end check.

---

### Task 1: Requests Portal page (`/requests-portal`)

**Files:**
- Create: `upande_dev_tools/www/requests-portal.html`
- Create: `upande_dev_tools/www/requests_portal.py`
- Modify: `upande_dev_tools/setup.py` (add registration call)
- Test: `upande_dev_tools/tests/test_portal.py` (append)

**Interfaces:**
- Consumes: the existing, unchanged `upande_dev_tools.api.requests.create_request` and
  `upande_dev_tools.api.requests.get_my_requests`.
- Produces: `/requests-portal`, registered with `allowed_roles=["All"]`, `nav_group="Requests"`,
  `sort_order=10`. This route is already named in `portal.py` as `DEFAULT_AUTHENTICATED_ROUTE` —
  this task is what makes it a real, reachable page for the first time.

- [ ] **Step 1: Write the failing tests**

Append to `upande_dev_tools/tests/test_portal.py`'s `IntegrationTestPortal` class (add
`from upande_dev_tools.www.requests_portal import get_context as requests_portal_get_context` to
the file's imports):

```python
	def test_requests_portal_permits_any_authenticated_user(self) -> None:
		other = self._make_user("requests-portal-other@example.test", [])
		frappe.set_user(other)
		try:
			requests_portal_get_context({})  # must not raise
		finally:
			frappe.set_user("Administrator")

	def test_requests_portal_denies_guest(self) -> None:
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.Redirect):
				requests_portal_get_context({})
			self.assertEqual(frappe.local.flags.redirect_location, "/login?redirect-to=/requests-portal")
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None

	def test_requests_portal_page_is_registered_with_correct_attributes(self) -> None:
		doc = frappe.get_doc("Dev Portal Page", "requests-portal")
		self.assertEqual(doc.title, "My Requests")
		self.assertEqual(doc.icon, "inbox")
		self.assertEqual(doc.nav_group, "Requests")
		self.assertEqual(doc.sort_order, 10)
		self.assertEqual({row.role for row in doc.allowed_roles}, {"All"})

	def test_requests_nav_group_is_visible_to_every_audience(self) -> None:
		dev = self._make_user("requests-nav-dev@example.test", ["Dev Team"])
		pm = self._make_user("requests-nav-pm@example.test", ["Projects Manager"])
		plain = self._make_user("requests-nav-plain@example.test", [])

		for user in (dev, pm, plain):
			groups = {item["nav_group"] for item in get_nav_items(user)}
			self.assertIn("Requests", groups)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_portal`
Expected: FAIL — `upande_dev_tools.www.requests_portal` doesn't exist yet.

- [ ] **Step 3: Write the page controller**

`upande_dev_tools/www/requests_portal.py` — follow the Global Constraints controller shape exactly
(already given verbatim above).

- [ ] **Step 4: Write the page template**

`upande_dev_tools/www/requests-portal.html` — follow the Global Constraints template shape.
Inside the `{% call dpx_shell() %}` block:

```html
<div class="dpx-page-hd">
	<div class="eyebrow">Requests</div>
	<div class="ttl">My Requests</div>
	<div class="sub">Submit a request and track its status.</div>
</div>
<div class="dpx-card">
	<div class="dpx-card-hd"><div class="ttl">Submit a Request</div></div>
	<div class="dpx-card-body">
		<form id="rp-submit-form">
			<div style="margin-bottom:10px;">
				<input type="text" id="rp-title" placeholder="Title" required
					style="width:100%;padding:8px 12px;border-radius:8px;border:1px solid var(--hairline);">
			</div>
			<div style="margin-bottom:10px;">
				<select id="rp-request-type" style="padding:8px 12px;border-radius:8px;border:1px solid var(--hairline);">
					<option value="Feature">Feature</option>
					<option value="Bug">Bug</option>
					<option value="Master Data">Master Data</option>
					<option value="Question">Question</option>
					<option value="Note">Note</option>
				</select>
				<input type="text" id="rp-product-area" placeholder="Product area (optional)"
					style="padding:8px 12px;border-radius:8px;border:1px solid var(--hairline);">
			</div>
			<div style="margin-bottom:10px;">
				<textarea id="rp-description" placeholder="Description (optional)" rows="3"
					style="width:100%;padding:8px 12px;border-radius:8px;border:1px solid var(--hairline);"></textarea>
			</div>
			<button type="submit" class="pill" style="cursor:pointer;border:1px solid var(--hairline);background:none;">Submit</button>
			<span id="rp-submit-error" style="color:#c4302b;margin-left:10px;"></span>
		</form>
	</div>
</div>
<div class="dpx-card" style="margin-top: 18px;">
	<div class="dpx-card-hd"><div class="ttl">My Requests</div></div>
	<div class="dpx-card-body">
		<table id="rp-requests-table">
			<thead><tr><th>Title</th><th>Type</th><th>Priority</th><th>Status</th><th>Submitted</th></tr></thead>
			<tbody></tbody>
		</table>
	</div>
</div>
<script>
frappe.ready(function() {
	function loadMyRequests() {
		frappe.call({method: "upande_dev_tools.api.requests.get_my_requests"}).then(function(r) {
			var tbody = document.querySelector("#rp-requests-table tbody");
			tbody.innerHTML = "";
			(r.message || []).forEach(function(request) {
				var tr = document.createElement("tr");
				[request.title, request.request_type, request.priority || "", request.workflow_state, request.creation].forEach(function(v) {
					var td = document.createElement("td");
					td.textContent = v || "";
					tr.appendChild(td);
				});
				tbody.appendChild(tr);
			});
		});
	}

	document.querySelector("#rp-submit-form").addEventListener("submit", function(e) {
		e.preventDefault();
		var errorEl = document.querySelector("#rp-submit-error");
		errorEl.textContent = "";

		frappe.call({
			method: "upande_dev_tools.api.requests.create_request",
			args: {
				title: document.querySelector("#rp-title").value,
				request_type: document.querySelector("#rp-request-type").value,
				product_area: document.querySelector("#rp-product-area").value || undefined,
				description: document.querySelector("#rp-description").value || undefined
			}
		}).then(function() {
			document.querySelector("#rp-submit-form").reset();
			loadMyRequests();
		}).catch(function() {
			errorEl.textContent = "Could not submit — check the form and try again.";
		});
	});

	loadMyRequests();
});
</script>
```

- [ ] **Step 5: Add registration**

In `upande_dev_tools/setup.py`'s `register_dev_portal_pages()`, add:

```python
	register_dev_portal_page(
		route="requests-portal",
		title="My Requests",
		icon="inbox",
		nav_group="Requests",
		sort_order=10,
		roles=["All"],
	)
```

- [ ] **Step 6: Migrate and run tests**

Run: `bench --site kaitet.local migrate`
Run: `bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_portal`
Expected: PASS

- [ ] **Step 7: Live-verify**

Using the established live-render technique (a throwaway plain user with no special roles,
authenticated against the running dev server at `http://kaitet.local:8002`), confirm
`/requests-portal` renders, the submit form is present, and a Guest is redirected to login.
Additionally: submit one real request through the form as your throwaway user, confirm it
appears in the "My Requests" table afterward with the correct title/type/status, and confirm via
`frappe.db.exists`/`frappe.get_doc` that a real `Request` record was created with
`raised_by_user` correctly resolved to your throwaway user. Delete the throwaway request and user
afterward. Also confirm a Dev Team user and a Projects Manager user both see the new "Requests"
group in their own sidebar alongside their existing group.

- [ ] **Step 8: Commit**

```bash
ruff format upande_dev_tools/www/requests_portal.py upande_dev_tools/setup.py upande_dev_tools/tests/test_portal.py
git add upande_dev_tools/www/requests-portal.html upande_dev_tools/www/requests_portal.py \
  upande_dev_tools/setup.py upande_dev_tools/tests/test_portal.py
git commit -m "feat: add the Requests Portal page

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Sub-project 5 acceptance check

After Task 1, run every module this whole Phase 2 has touched to confirm no regression:

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

Expected: all pass. At this point, Phase 2 is complete: every audience the original request named
— developers, Projects Managers, and customers/employees — has a real, working, role-gated home
page in the portal, and the desk-only Tools Dashboard/Code Editor/Hooks Explorer are fully retired
in favor of it.
