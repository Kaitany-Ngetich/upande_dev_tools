# Phase 2 Sub-project 2: Port Existing Dev Tools to the Portal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the three existing desk tools (Hooks Explorer, Tools Dashboard, Code Editor) into
the portal shell built in Sub-project 1, functionally unchanged, then remove the old desk pages.

**Architecture:** Each tool becomes one `www` page pair (`.py` controller + `.html` template)
following the exact pattern `www/dev_portal_settings.py`/`dev-portal-settings.html` established:
`enforce_page_access` in `get_context`, a `head_include` block override for shell CSS/fonts, and
`{% call dpx_shell() %}` wrapping the tool's own content. Each tool's existing `page/<x>/<x>.js`
moves to `public/js/<x>-portal.js`, keeping its data-fetching/rendering logic unchanged and only
replacing its desk-specific mounting boilerplate. No changes to any existing API module.

**Tech Stack:** Frappe v16 `www` pages, Jinja2, existing Monaco Editor static assets, existing
whitelisted API modules (`api/dashboard.py`, `api/code_editor.py`, `api/hooks_explorer.py`).

**Spec:** `docs/specs/2026-09-13-portal-dev-tools-port-design.md`

## Global Constraints

- Everything belongs to the single existing `Upande Dev Tools` module — no new module.
- Bench root `/home/jk/Projects/upande-local-bench-v16`, site `kaitet.local`. Whole-app
  `bench run-tests` is broken by a pre-existing unrelated ERPNext bug — always scope test runs
  with `--module`.
- `ruff` is on PATH (tabs, double quotes, 110 char lines) for every Python file touched.
- After any change to `public/js/*.js` or `public/css/*.css`, run
  `bench build --app upande_dev_tools` before verifying live (static assets are served from the
  built/linked `sites/assets/` tree, not read live from the source directory).
- The shared shell (`upande_dev_tools/templates/includes/dev_portal_shell.html` and
  `dev_portal_shell_head.html`) is complete and correct as of Sub-project 1's final polish
  commit (`09e8fb6`) — do not modify it in this plan. Every new page consumes it exactly the way
  `www/dev-portal-settings.html` does:
  ```jinja
  {% extends "templates/web.html" %}
  {% block head_include %}
  	{{ super() }}
  	{% include "templates/includes/dev_portal_shell_head.html" %}
  {% endblock %}
  {% block page_content %}
  {% from "templates/includes/dev_portal_shell.html" import dpx_shell with context %}
  {% call dpx_shell() %}
  ...
  {% endcall %}
  {% endblock %}
  ```
- Every new page's `.py` controller follows this exact shape (only `page_title`/`active_route`
  differ per page):
  ```python
  # Copyright (c) 2026, shadrack@upande.com and contributors
  # For license information, please see license.txt

  import frappe

  from upande_dev_tools.portal import enforce_page_access

  no_cache = 1


  def get_context(context):
  	enforce_page_access("<route>")
  	context.no_cache = 1
  	context.page_title = "<Title>"
  	context.active_route = "<route>"
  	context.csrf_token = frappe.sessions.get_csrf_token()
  	return context
  ```
- Registration goes through `register_dev_portal_page(route, title, icon, nav_group, sort_order,
  roles, require_all_roles=False)` in `upande_dev_tools/setup.py` (from Sub-project 1's Task 3),
  called from `register_dev_portal_pages()` in that same file — add one call per new page there,
  alongside the existing `dev-portal-settings` call. Do not alter
  `register_dev_portal_page`/`run_setup`/`create_task_custom_fields` themselves.
- `upande_dev_tools/tests/test_portal.py`'s `IntegrationTestPortal` class (from Sub-project 1) is
  where every new access-control test in this plan is appended — reuse its existing
  `_make_user`/`_make_page` helpers, do not redeclare the class or duplicate imports.
- When deleting a desk `Page` doctype folder, also remove its shortcut entry from
  `upande_dev_tools/upande_dev_tools/workspace/upande_dev_tools/upande_dev_tools.json`'s
  `shortcuts` array (each has `"type": "Page"` and a `"link_to"` matching the old page name) —
  a dangling shortcut to a deleted page breaks the workspace.
- Bootstrap's website bundle carries a bare `.nav{flex-wrap:wrap}` rule (Sub-project 1's final
  polish fix) — any NEW top-level `<nav>`/`.nav`-classed element a ported tool's own markup
  introduces needs the same defensive `flex-wrap:nowrap` if it's meant to be a vertical list.
  None of the three tools ported here introduce one (their own internal structure uses different
  class names), but double-check this if a tool's markup surprises you.

---

### Task 1: Port Hooks Explorer

**Files:**
- Create: `upande_dev_tools/www/__init__.py` already exists (Sub-project 1) — verify, don't recreate.
- Create: `upande_dev_tools/www/hooks-explorer.html`
- Create: `upande_dev_tools/www/hooks_explorer.py`
- Create: `upande_dev_tools/public/js/hooks-explorer-portal.js`
- Modify: `upande_dev_tools/setup.py` (add registration call)
- Modify: `upande_dev_tools/upande_dev_tools/workspace/upande_dev_tools/upande_dev_tools.json`
  (remove the `hooks-explorer` `Page`-type shortcut — this tool no longer has a desk page)
- Delete: `upande_dev_tools/upande_dev_tools/page/hooks_explorer/` (both `.json` and `.js`)
- Test: `upande_dev_tools/tests/test_portal.py` (append)

**Interfaces:**
- Consumes: `enforce_page_access`, `register_dev_portal_page`, `dpx_shell`, the existing
  `upande_dev_tools.api.hooks_explorer.get_installed_apps`/`get_app_hooks` whitelisted functions
  (unchanged).
- Produces: `/hooks-explorer`, registered with `allowed_roles=["Dev Team"]`,
  `nav_group="Developer"`, `sort_order=20`.

- [ ] **Step 1: Read the existing desk page**

Read `upande_dev_tools/upande_dev_tools/page/hooks_explorer/hooks_explorer.js` in full (134
lines) before starting — you are porting it, not rewriting it.

- [ ] **Step 2: Write the failing tests**

Append to `upande_dev_tools/tests/test_portal.py`'s `IntegrationTestPortal` class (add
`from upande_dev_tools.www.hooks_explorer import get_context as hooks_explorer_get_context` to
the file's imports):

```python
	def test_hooks_explorer_permits_dev_team_and_denies_others(self) -> None:
		dev = self._make_user("hooks-explorer-dev@example.test", ["Dev Team"])
		other = self._make_user("hooks-explorer-other@example.test", [])

		frappe.set_user(dev)
		try:
			hooks_explorer_get_context({})  # must not raise
		finally:
			frappe.set_user("Administrator")

		frappe.set_user(other)
		try:
			with self.assertRaises(frappe.Redirect):
				hooks_explorer_get_context({})
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_portal`
Expected: FAIL — `upande_dev_tools.www.hooks_explorer` doesn't exist yet.

- [ ] **Step 4: Write the page controller**

`upande_dev_tools/www/hooks_explorer.py` — follow the Global Constraints controller shape exactly,
with `route="hooks-explorer"`, `page_title="Hooks Explorer"`, `active_route="hooks-explorer"`.

- [ ] **Step 5: Write the page template**

`upande_dev_tools/www/hooks-explorer.html` — follow the Global Constraints template shape. Inside
the `{% call dpx_shell() %}` block, put only a page heading and a mount point, then the JS asset:

```html
<div class="dpx-page-hd">
	<div class="eyebrow">Developer</div>
	<div class="ttl">Hooks Explorer</div>
	<div class="sub">Browse and search every installed app's hooks.py.</div>
</div>
<div id="udt-hooks-explorer-root"></div>
<script src="/assets/upande_dev_tools/js/hooks-explorer-portal.js"></script>
<script>
	upande_dev_tools_portal.mount_hooks_explorer(document.getElementById("udt-hooks-explorer-root"));
</script>
```

- [ ] **Step 6: Port the JS**

Create `upande_dev_tools/public/js/hooks-explorer-portal.js`. Copy the body of
`hooks_explorer.js`'s `frappe.pages["hooks-explorer"].on_page_load = function (wrapper) { ... }`
wholesale, with exactly these changes:

1. Wrap it as a namespaced mount function instead of a desk page-load handler:
   ```javascript
   window.upande_dev_tools_portal = window.upande_dev_tools_portal || {};

   upande_dev_tools_portal.mount_hooks_explorer = function (root) {
   	let current_data = null;

   	$(root).html(`
   		<div class="frappe-card" style="padding: 20px;">
   		... (unchanged — the exact same template string hooks_explorer.js already builds) ...
   		</div>
   	`);

   	// ... rest of the original function body, completely unchanged ...
   };
   ```
2. The only two mechanical substitutions: `frappe.pages["hooks-explorer"].on_page_load =
   function (wrapper) {` becomes `upande_dev_tools_portal.mount_hooks_explorer = function (root) {`,
   and the original's `const page = frappe.ui.make_app_page({...}); $(page.body).html(...)` two
   lines become a single `$(root).html(...)` call with the identical template string argument.
3. Everything else — `frappe.call(...)` blocks, the `$(document).on("change", "#app-selector",
   ...)` / `$(document).on("input", "#hook-search", ...)` delegated handlers, `load_hooks()`,
   `render_hooks()`, `escape_html()` — copy verbatim, unchanged. (The delegated `$(document).on`
   handlers work identically regardless of where `#app-selector`/`#hook-search` live in the DOM,
   so they need no changes.)

- [ ] **Step 7: Add registration**

In `upande_dev_tools/setup.py`'s `register_dev_portal_pages()`, add:

```python
	register_dev_portal_page(
		route="hooks-explorer",
		title="Hooks Explorer",
		icon="search",
		nav_group="Developer",
		sort_order=20,
		roles=["Dev Team"],
	)
```

- [ ] **Step 8: Migrate, build, and run tests**

Run: `bench --site kaitet.local migrate`
Run: `bench build --app upande_dev_tools`
Run: `bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_portal`
Expected: PASS

- [ ] **Step 9: Live-verify the port**

Using the same live-render technique already proven in this project (patch
`frappe.sessions.get_csrf_token` in a throwaway `bench console` script when console lacks a real
session, or render via `frappe.website.page_renderers.template_page.TemplatePage` directly),
confirm: the page renders with no literal `{% `/`{{ ` leakage, `hooks-explorer-portal.js` is
referenced and loads without a 404, and the shell's sidebar highlights "Hooks Explorer" as active
(`active_route` matches). If you can reach the running dev server directly (it's already up on
`http://kaitet.local:8002`), a real authenticated GET to `/hooks-explorer` is even better evidence
— use whichever you can actually drive from your sandbox, and say which you used.

- [ ] **Step 10: Remove the old desk page**

Delete `upande_dev_tools/upande_dev_tools/page/hooks_explorer/hooks_explorer.json` and
`hooks_explorer.js`. In `upande_dev_tools/upande_dev_tools/workspace/upande_dev_tools/
upande_dev_tools.json`, remove the shortcut object with `"link_to": "hooks-explorer"`. Run
`bench --site kaitet.local migrate` again to confirm the workspace change and page deletion don't
break anything.

- [ ] **Step 11: Commit**

```bash
ruff format upande_dev_tools/www/hooks_explorer.py upande_dev_tools/setup.py upande_dev_tools/tests/test_portal.py
git add upande_dev_tools/www/hooks-explorer.html upande_dev_tools/www/hooks_explorer.py \
  upande_dev_tools/public/js/hooks-explorer-portal.js upande_dev_tools/setup.py \
  upande_dev_tools/tests/test_portal.py \
  upande_dev_tools/upande_dev_tools/workspace/upande_dev_tools/upande_dev_tools.json
git rm -r upande_dev_tools/upande_dev_tools/page/hooks_explorer
git commit -m "feat: port Hooks Explorer to the portal, remove the desk page

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Port Tools Dashboard as the Dev Team home page (`/dev-dashboard`)

**Files:**
- Create: `upande_dev_tools/www/dev-dashboard.html`
- Create: `upande_dev_tools/www/dev_dashboard.py`
- Create: `upande_dev_tools/public/js/dev-dashboard-portal.js`
- Modify: `upande_dev_tools/setup.py` (add registration call)
- Modify: `upande_dev_tools/upande_dev_tools/workspace/upande_dev_tools/upande_dev_tools.json`
  (remove the `upande-dev-dashboard` `Page`-type shortcut)
- Delete: `upande_dev_tools/upande_dev_tools/page/upande_dev_dashboard/`
- Test: `upande_dev_tools/tests/test_portal.py` (append)

**Interfaces:**
- Consumes: `enforce_page_access`, `register_dev_portal_page`, `resolve_home_route` (Sub-project
  1's `portal.py` — its `HOME_ROUTE_BY_ROLE` already names `/dev-dashboard` for `Dev Team`; this
  task is what makes that route exist and be reachable), `dpx_shell`, the existing
  `upande_dev_tools.api.dashboard.get_dashboard_data` whitelisted function (unchanged).
- Produces: `/dev-dashboard`, registered with `allowed_roles=["Dev Team"]`,
  `nav_group="Developer"`, `sort_order=10` (lowest in its group — it's the section's landing
  page).

- [ ] **Step 1: Read the existing desk page**

Read `upande_dev_tools/upande_dev_tools/page/upande_dev_dashboard/upande_dev_dashboard.js` in
full (646 lines) before starting.

- [ ] **Step 2: Write the failing tests**

Append to `upande_dev_tools/tests/test_portal.py`'s `IntegrationTestPortal` class (add
`from upande_dev_tools.www.dev_dashboard import get_context as dev_dashboard_get_context` to the
file's imports):

```python
	def test_dev_dashboard_permits_dev_team_and_denies_others(self) -> None:
		dev = self._make_user("dev-dashboard-dev@example.test", ["Dev Team"])
		other = self._make_user("dev-dashboard-other@example.test", [])

		frappe.set_user(dev)
		try:
			dev_dashboard_get_context({})  # must not raise
		finally:
			frappe.set_user("Administrator")

		frappe.set_user(other)
		try:
			with self.assertRaises(frappe.Redirect):
				dev_dashboard_get_context({})
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None

	def test_resolve_home_route_for_dev_team_is_now_reachable(self) -> None:
		# Closes the gap Sub-project 1's final review flagged: /dev-dashboard is now a real,
		# registered, permitted page for Dev Team, so enforce_page_access on it must NOT hit
		# the loop-guard's /app fallback (that fallback only fires when the resolved home route
		# is itself denied or unregistered).
		dev = self._make_user("dev-dashboard-home-route@example.test", ["Dev Team"])
		self.assertEqual(resolve_home_route(dev), "/dev-dashboard")
		frappe.set_user(dev)
		try:
			enforce_page_access("dev-dashboard")  # must not raise
		finally:
			frappe.set_user("Administrator")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_portal`
Expected: FAIL — `upande_dev_tools.www.dev_dashboard` doesn't exist yet.

- [ ] **Step 4: Write the page controller**

`upande_dev_tools/www/dev_dashboard.py` — follow the Global Constraints controller shape exactly,
with `route="dev-dashboard"`, `page_title="Dashboard"`, `active_route="dev-dashboard"`.

- [ ] **Step 5: Write the page template**

`upande_dev_tools/www/dev-dashboard.html` — follow the Global Constraints template shape. This
tool's existing desk JS builds its own full-page layout (KPI section, version table, backup
table, field differences, hooks summary, activity feed, system health) inside `page.body` — port
that whole layout as the mount point's inner content, so the `{% call dpx_shell() %}` block is
just:

```html
<div id="udt-dev-dashboard-root"></div>
<script src="/assets/upande_dev_tools/js/dev-dashboard-portal.js"></script>
<script>
	upande_dev_tools_portal.mount_dev_dashboard(document.getElementById("udt-dev-dashboard-root"));
</script>
```

(No separate `.dpx-page-hd` here — the ported dashboard's own section markup already carries a
heading; don't duplicate one.)

- [ ] **Step 6: Port the JS**

Create `upande_dev_tools/public/js/dev-dashboard-portal.js`. Apply the exact same two mechanical
substitutions as Task 1's Step 6:
`frappe.pages["upande-dev-dashboard"].on_page_load = function(wrapper) {` →
`upande_dev_tools_portal.mount_dev_dashboard = function (root) {`, and replace
`const page = frappe.ui.make_app_page({...}); $(page.body).html(...)` with `$(root).html(...)`
using the identical template string. Copy every other line — the `<style>` block (it's already
scoped under `.udt-section`/`.udt-*` class names, distinct from `.dpx-*`, so it coexists safely),
the `frappe.call({method: "upande_dev_tools.api.dashboard.get_dashboard_data", ...})` block, and
every `udt_render_*` function — completely unchanged. Prepend the same
`window.upande_dev_tools_portal = window.upande_dev_tools_portal || {};` guard as Task 1 (in case
this file loads before or after `hooks-explorer-portal.js` — only one of the two needs the guard
line to actually execute first, but including it in both is harmless and avoids load-order
assumptions).

- [ ] **Step 7: Add registration**

In `upande_dev_tools/setup.py`'s `register_dev_portal_pages()`, add:

```python
	register_dev_portal_page(
		route="dev-dashboard",
		title="Dashboard",
		icon="home",
		nav_group="Developer",
		sort_order=10,
		roles=["Dev Team"],
	)
```

- [ ] **Step 8: Migrate, build, and run tests**

Run: `bench --site kaitet.local migrate`
Run: `bench build --app upande_dev_tools`
Run: `bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_portal`
Expected: PASS

- [ ] **Step 9: Live-verify the port**

Same approach as Task 1's Step 9, applied to `/dev-dashboard`. Additionally confirm: visiting
`/dev-tools` (Sub-project 1's vanity redirect) as a Dev Team user now actually lands on a real,
rendering page instead of a route that would itself redirect further (this was previously
untestable end-to-end since `/dev-dashboard` didn't exist).

- [ ] **Step 10: Remove the old desk page**

Delete `upande_dev_tools/upande_dev_tools/page/upande_dev_dashboard/upande_dev_dashboard.json`
and `upande_dev_dashboard.js`. In the workspace JSON, remove the shortcut with
`"link_to": "upande-dev-dashboard"`. Run `bench --site kaitet.local migrate` again.

- [ ] **Step 11: Commit**

```bash
ruff format upande_dev_tools/www/dev_dashboard.py upande_dev_tools/setup.py upande_dev_tools/tests/test_portal.py
git add upande_dev_tools/www/dev-dashboard.html upande_dev_tools/www/dev_dashboard.py \
  upande_dev_tools/public/js/dev-dashboard-portal.js upande_dev_tools/setup.py \
  upande_dev_tools/tests/test_portal.py \
  upande_dev_tools/upande_dev_tools/workspace/upande_dev_tools/upande_dev_tools.json
git rm -r upande_dev_tools/upande_dev_tools/page/upande_dev_dashboard
git commit -m "feat: port Tools Dashboard to the portal as /dev-dashboard, remove the desk page

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Port Code Editor

**Files:**
- Create: `upande_dev_tools/www/code-editor.html`
- Create: `upande_dev_tools/www/code_editor.py`
- Create: `upande_dev_tools/public/js/code-editor-portal.js`
- Modify: `upande_dev_tools/setup.py` (add registration call)
- Modify: `upande_dev_tools/upande_dev_tools/workspace/upande_dev_tools/upande_dev_tools.json`
  (remove the `code-editor` `Page`-type shortcut)
- Delete: `upande_dev_tools/upande_dev_tools/page/code_editor/`
- Test: `upande_dev_tools/tests/test_portal.py` (append)

**Interfaces:**
- Consumes: `enforce_page_access`, `register_dev_portal_page`, `dpx_shell`, the existing
  `upande_dev_tools.api.code_editor.*` whitelisted functions (unchanged), the existing
  self-hosted Monaco assets at `/assets/upande_dev_tools/js/monaco/vs/` (unchanged — already
  built and served; this task does not touch them).
- Produces: `/code-editor`, registered with `allowed_roles=["Dev Team"]`,
  `nav_group="Developer"`, `sort_order=30`.

- [ ] **Step 1: Read the existing desk page**

Read `upande_dev_tools/upande_dev_tools/page/code_editor/code_editor.js` in full (636 lines)
before starting — this is the largest and most stateful of the three ports (file tree, open
tabs, active-tab tracking, Monaco lifecycle), so read carefully before touching anything.

- [ ] **Step 2: Write the failing tests**

Append to `upande_dev_tools/tests/test_portal.py`'s `IntegrationTestPortal` class (add
`from upande_dev_tools.www.code_editor import get_context as code_editor_get_context` to the
file's imports):

```python
	def test_code_editor_permits_dev_team_and_denies_others(self) -> None:
		dev = self._make_user("code-editor-dev@example.test", ["Dev Team"])
		other = self._make_user("code-editor-other@example.test", [])

		frappe.set_user(dev)
		try:
			code_editor_get_context({})  # must not raise
		finally:
			frappe.set_user("Administrator")

		frappe.set_user(other)
		try:
			with self.assertRaises(frappe.Redirect):
				code_editor_get_context({})
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_portal`
Expected: FAIL — `upande_dev_tools.www.code_editor` doesn't exist yet.

- [ ] **Step 4: Write the page controller**

`upande_dev_tools/www/code_editor.py` — follow the Global Constraints controller shape exactly,
with `route="code-editor"`, `page_title="Code Editor"`, `active_route="code-editor"`.

- [ ] **Step 5: Write the page template**

`upande_dev_tools/www/code-editor.html` — follow the Global Constraints template shape. The
existing desk version fills its entire page body with the editor shell (no separate page-title
banner), so port it the same way as Task 2 — the `{% call dpx_shell() %}` block is just the
mount point plus scripts:

```html
<div id="udt-code-editor-root"></div>
<script src="/assets/upande_dev_tools/js/code-editor-portal.js"></script>
<script>
	upande_dev_tools_portal.mount_code_editor(document.getElementById("udt-code-editor-root"));
</script>
```

The Monaco loader script itself does NOT need a separate `<script src>` tag here — the existing
`code_editor.js` already bootstraps Monaco lazily via `frappe.require("/assets/upande_dev_tools/
js/monaco/vs/loader.js", ...)` inside its own `load_monaco()` function, which is being carried
over unchanged in Step 6 below. `frappe.require` is a core Frappe utility available on `www`
pages exactly as on desk pages (it is not desk-specific).

- [ ] **Step 6: Port the JS**

Create `upande_dev_tools/public/js/code-editor-portal.js`. Apply the same two mechanical
substitutions as Tasks 1 and 2: `frappe.pages["code-editor"].on_page_load = function(wrapper) {`
→ `upande_dev_tools_portal.mount_code_editor = function (root) {`, and replace the
`build_shell(page)` / `load_monaco()` calls' `page` argument path — `build_shell` currently does
`$(page.body).html(...)` — with `root` (rename the parameter from `page` to `root` throughout
`build_shell`, and change its one `$(page.body).html(...)` call to `$(root).html(...)`). Copy
every other line — the module-level state variables (`udt_editor`, `udt_current_app`,
`udt_current_file`, `udt_file_tree`, `udt_open_tabs`, `udt_active_tab`, `udt_is_switching_tab`),
`load_monaco()`, the file-tree/tab-management functions, every `frappe.call(...)` to
`upande_dev_tools.api.code_editor.*`, and the entire `<style>` block (already scoped under
`.udt-*` class names) — completely unchanged. Prepend the same
`window.upande_dev_tools_portal = window.upande_dev_tools_portal || {};` guard.

- [ ] **Step 7: Add registration**

In `upande_dev_tools/setup.py`'s `register_dev_portal_pages()`, add:

```python
	register_dev_portal_page(
		route="code-editor",
		title="Code Editor",
		icon="code",
		nav_group="Developer",
		sort_order=30,
		roles=["Dev Team"],
	)
```

- [ ] **Step 8: Migrate, build, and run tests**

Run: `bench --site kaitet.local migrate`
Run: `bench build --app upande_dev_tools`
Run: `bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_portal`
Expected: PASS

- [ ] **Step 9: Live-verify the port**

Same approach as Tasks 1 and 2's Step 9, applied to `/code-editor`. Additionally confirm Monaco
actually initializes (the rendered page, once JS executes, replaces the `#editor` div's content —
if you can only verify server-rendered HTML and not execute client JS, at minimum confirm the
`<script src="/assets/upande_dev_tools/js/monaco/vs/loader.js">`-triggering `frappe.require(...)`
call and the `#editor` mount div are both present in the rendered/ported JS and HTML respectively,
and say clearly that JS execution itself wasn't verified if your sandbox can't run a browser).

- [ ] **Step 10: Remove the old desk page**

Delete `upande_dev_tools/upande_dev_tools/page/code_editor/code_editor.json` and
`code_editor.js`. In the workspace JSON, remove the shortcut with `"link_to": "code-editor"`. Run
`bench --site kaitet.local migrate` again.

- [ ] **Step 11: Commit**

```bash
ruff format upande_dev_tools/www/code_editor.py upande_dev_tools/setup.py upande_dev_tools/tests/test_portal.py
git add upande_dev_tools/www/code-editor.html upande_dev_tools/www/code_editor.py \
  upande_dev_tools/public/js/code-editor-portal.js upande_dev_tools/setup.py \
  upande_dev_tools/tests/test_portal.py \
  upande_dev_tools/upande_dev_tools/workspace/upande_dev_tools/upande_dev_tools.json
git rm -r upande_dev_tools/upande_dev_tools/page/code_editor
git commit -m "feat: port Code Editor to the portal, remove the desk page

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Sub-project 2 acceptance check

After Task 3, run every module this plan touched:

```bash
bench --site kaitet.local run-tests --module upande_dev_tools.upande_dev_tools.doctype.dev_portal_page.test_dev_portal_page
bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_portal
bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_dev_portal_settings_api
bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_requests_api
bench --site kaitet.local run-tests --module upande_dev_tools.tests.test_deployments_api
```

Expected: all pass. At this point: a Dev Team user landing on `/dev-tools` or logging in reaches
a real, working `/dev-dashboard`; `/code-editor` and `/hooks-explorer` are reachable from its
sidebar under "Developer"; none of the three old desk `Page` doctypes exist anymore, and the
workspace has no dangling shortcuts to them. Sub-project 3 (the new dev-facing views — my day,
backlog board, code snapshots, error logs) can then add pages to this same "Developer" nav group
with zero new plumbing, exactly as Sub-project 1 intended.
