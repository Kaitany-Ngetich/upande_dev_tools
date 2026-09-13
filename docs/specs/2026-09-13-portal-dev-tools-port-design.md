# Phase 2, Sub-project 2: Port Existing Dev Tools to the Portal — Design

Date: 2026-09-13
App: `upande_dev_tools`
Related: `docs/specs/2026-09-13-portal-shell-design.md` (Sub-project 1 — the shell, access control,
and page registry this sub-project builds on), `upande_packhouse` (design language reference,
already reconciled against the actual shell CSS during Sub-project 1's post-completion polish)

## Context: the wider roadmap

Sub-project 1 shipped the portal shell, the `Dev Portal Page` registry, and the dual-role-gated
settings page. Phase 2's original plan named a "Developer dashboard" as Sub-project 2, covering
both (a) porting three existing, fully-built desk tools into the portal and (b) new dev-facing
views that don't exist yet (my day, backlog board, code snapshots, error logs). Per discussion,
that's being split in two:

1. **This document** — port the three existing desk tools (Tools Dashboard, Hooks Explorer,
   Code Editor) into the portal shell, functionally unchanged. Mechanical, lower-risk, and it
   gives Dev Team users a working portal home page immediately.
2. **Sub-project 3** (not yet designed) — the new dev-facing views: my day, backlog board, code
   snapshots, error logs.
3. Sub-project 4: Projects Manager dashboard. Sub-project 5: Customer/Employee portal.

## Problem

- `Dev Portal Page`'s `HOME_ROUTE_BY_ROLE` already promises Dev Team users a `/dev-dashboard`
  landing page (from Sub-project 1's `portal.py`), but nothing has registered that route yet —
  today, any Dev Team user hitting their own home page gets `enforce_page_access`'s fail-closed
  "unregistered route" redirect loop guard kicking in (falling through to `/app`, the desk),
  never actually reaching a portal page. This sub-project is what makes that route real.
- Three fully-functional tools already exist only on the desk: `upande-dev-dashboard` (KPIs,
  version/deploy history, backup table, schema field-difference detector, hooks summary,
  activity feed, system health — `page/upande_dev_dashboard/upande_dev_dashboard.js`,
  646 lines), `hooks-explorer` (per-app hook browser/search — `page/hooks_explorer/
  hooks_explorer.js`, 134 lines), and `code-editor` (a full Monaco-based IDE — file tree, tabs,
  run panel — `page/code_editor/code_editor.js`, 636 lines). None of them are reachable by a
  Website User or anyone without desk access, which defeats the point of the portal.

## Design

### Page structure

Three new `www` pages, each following the exact pattern Sub-project 1's Task 5 established:

| Route | Title | Replaces desk page | `nav_group` |
|---|---|---|---|
| `/dev-dashboard` | Dashboard | `upande-dev-dashboard` | Developer |
| `/code-editor` | Code Editor | `code-editor` | Developer |
| `/hooks-explorer` | Hooks Explorer | `hooks-explorer` | Developer |

Each page's `.py` controller: `no_cache = 1`, `get_context()` calls
`enforce_page_access("<route>")`, sets `page_title`/`active_route`/`csrf_token`, exactly like
`www/dev_portal_settings.py`. Each page's `.html`: `{% extends "templates/web.html" %}`, a
`{% block head_include %}{{ super() }}{% include "templates/includes/dev_portal_shell_head.html" %}
{% endblock %}` (plus, for Code Editor, its own extra `<script src=".../monaco/vs/loader.js">`
bootstrapping — Monaco loads on demand via `frappe.require()`, unchanged from the desk version),
then `{% from "templates/includes/dev_portal_shell.html" import dpx_shell with context %}` /
`{% call dpx_shell() %}...{% endcall %}` wrapping the tool's own mount point (a single `<div>`
each tool's ported JS renders into) plus a `<script src="/assets/upande_dev_tools/js/<name>-
portal.js">` tag.

`/dev-dashboard` becomes the Dev Team home route (`HOME_ROUTE_BY_ROLE` in `portal.py` already
points there — no change needed there), registered with `allowed_roles=["Dev Team"]` via
`register_dev_portal_page` in `setup.py`, same for the other two.

### Porting each tool's front-end

Each tool's existing `page/<x>/<x>.js` moves to a new `public/js/<x>-portal.js`, preserving its
actual rendering/data logic — the `frappe.call({method: "upande_dev_tools.api...."})` calls, the
render functions, Monaco setup — almost unchanged. Only the desk-specific mounting boilerplate
changes:

- `frappe.pages["<x>"].on_page_load = function(wrapper) { ... }` → a plain function invoked
  directly by an inline `<script>` at the bottom of the page's `.html` (e.g.
  `<script>upande_dev_tools_portal.mount_dev_dashboard(document.getElementById("udt-mount"));
  </script>`), since there's no desk page-registry to hook into on a `www` page.
  `frappe.ui.make_app_page({parent: wrapper, ...})` is replaced by a plain `document.
  getElementById("udt-mount")` div the `.html` file itself provides inside the `{% call
  dpx_shell() %}` block — the portal shell already supplies the page chrome (title bar, sidebar),
  so each tool's own root-level page-frame markup (each currently builds its own header/breadcrumb
  via `page.body`) is trimmed to just its content area.
- Everything below that boundary — the actual `frappe.call()` data-fetching, the DOM-building
  render functions, Monaco's `editor.create()`/tab management, the CSS each file already
  ships in its own `<style>` block — carries over unchanged. These tools' CSS is already
  self-scoped under tool-specific class prefixes (`udt-*`), so it coexists with `.dpx` without
  collision, the same way `dev-portal.css` itself is scoped.

No changes to `api/dashboard.py`, `api/code_editor.py`, or `api/hooks_explorer.py` — all three
are already `@frappe.whitelist()` functions, callable identically from a `www` page's JS as from
a desk page's JS.

### Desk page removal

Once each portal page is registered, built, and verified live, delete the corresponding desk
`Page` doctype folder (`upande_dev_tools/page/upande_dev_dashboard/`, `.../hooks_explorer/`,
`.../code_editor/`) and its two files (`.json`, `.js`) each. Also remove any workspace shortcuts
pointing at the old desk pages (the app's single workspace, `upande_dev_tools.json`, currently
links to these — check during implementation and update alongside).

## Testing

- `Dev Portal Page` registration for the three new routes: covered the same way Sub-project 1
  tested `dev-portal-settings`'s self-registration (`register_dev_portal_page` idempotency,
  correct `allowed_roles`/`nav_group`).
- `enforce_page_access` gating: each of the three pages' `get_context()` denies a non-Dev-Team
  user and permits a Dev Team user, tested the same way `test_get_context_denies_single_role_user`
  tested the settings page.
- `resolve_home_route` for a Dev Team user now resolving to a route that's actually registered
  and permitted (closing the gap Sub-project 1 left open, where `/dev-dashboard` didn't exist as
  a registry entry yet) — add the test the final Sub-project 1 review flagged as future work:
  a Dev Team user's home route resolves to `/dev-dashboard` and `enforce_page_access` permits it
  without the loop-guard's `/app` fallback ever triggering.
- No new tests for the ported JS itself (Monaco, dashboard rendering, hooks search) beyond a
  live render/click-through check per page — this logic isn't unit-testable the way Python is,
  and it's carried over from already-working desk tools, not new logic.

## Out of scope

- Any change to what each tool actually shows or does — this is a straight port, not a redesign
  or feature addition.
- The new dev-facing views (my day, backlog board, code snapshots, error logs) — Sub-project 3.
- Any visual redesign of the tools themselves beyond fitting them into the portal shell's content
  area (Code Editor's own VS-Code-dark-theme styling stays as-is; it doesn't need to match the
  Role Advisor light theme, the same way Frappe's own desk retains its own look next to a website).
