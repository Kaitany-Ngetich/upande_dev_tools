# Phase 2, Sub-project 1: Portal Shell & Access Control — Design

Date: 2026-09-13
App: `upande_dev_tools`
Related: `docs/specs/2026-09-13-requests-backlog-phase1-design.md` (Phase 1 — the API this
portal reads from), `upande_packhouse` (`upande_packhouse/www/*`, `public/css/packhouse-portal.css`
— the "Role Advisor" design language this portal ports)

## Context: the wider roadmap

Phase 1 shipped the `Request`/`Deployment Request` data model and API, entirely desk-only.
Phase 2 moves developers, Projects Managers, and customers/employees onto a `www` portal —
replacing the current desk pages (Tools Dashboard, Code Editor, Hooks Explorer) with three
role-scoped dashboards plus a settings screen. Phase 2 is itself four sub-projects, each with
its own spec/plan:

1. **Portal shell & access control (this document)** — the shared layout, the page registry
   that drives both navigation and permissions, routing/home-page resolution, and the settings
   page. Nothing else in Phase 2 can be built without this.
2. **Developer dashboard** — "my day", backlog board, code backup snapshots, activity/error
   logs, a rebuilt Code Editor and Hooks Explorer.
3. **Projects Manager dashboard** — project-health visualizations, cross-project backlog view.
4. **Customer/Employee portal** — submit a request, report an issue, see priority/status of
   their own requests.

## Problem

- Everything today lives on the desk, which is fine for developers but not for customers or
  most employees, and doesn't give a Projects Manager a visual, at-a-glance read on project
  health.
- There is no way to control who sees which portal page that doesn't mean editing code —
  and it needs to stay that way as Sub-projects 2-4 (and anything built after them) each add
  new pages.
- Phase 1 deliberately deferred its `Dev Team` + `System Manager` dual-role settings gate here,
  since no settings page existed yet to attach it to.

## Design

### The page registry: `Dev Portal Page`

One doctype, one record per registered portal page — this is the single mechanism that drives
**both** the sidebar navigation **and** access control, so adding a page never means hand-editing
a nav list somewhere:

| Field | Type | Notes |
|---|---|---|
| `route` | Data, unique, autoname (`field:route`) | e.g. `dev-dashboard`, `dev-portal-settings`. |
| `title` | Data | Sidebar label. |
| `icon` | Data | Icon key the shell template maps to an inline SVG (matches the `svg.ic` pattern already used in the Role Advisor CSS). |
| `nav_group` | Data | Sidebar section header (e.g. "Developer", "Project Management", "Requests"). |
| `sort_order` | Int | Ordering within its group. |
| `allowed_roles` | Table (child: `Dev Portal Page Role`, one `role` Link field per row) | Who can see this page. |
| `require_all_roles` | Check, default 0 | When on, the visitor must hold **every** listed role, not just one — this is how the settings page itself (`Dev Team` **and** `System Manager`) is expressed, using the same mechanism every other page uses rather than a one-off hardcoded permission hook. |

New pages **self-register**: each ships a small setup function creating its own `Dev Portal Page`
record only if one doesn't already exist for that route (the same idempotent, create-if-missing
pattern Phase 1 used for `Task`'s custom fields via `after_install`/`after_migrate`) — so a page
ships with sensible default roles, and an admin's later edits in the settings screen are never
overwritten by a future `bench migrate`.

### Routing and access control

Two shared functions, in a new module `upande_dev_tools/portal.py`:

- **`resolve_home_route(user=None)`** — a fixed role-priority lookup: `Dev Team` → the dev
  dashboard's route, `Projects Manager` → the PM dashboard's route, any other authenticated
  user → the request portal's route, guest → `/login`. This one function serves three call
  sites: the denied-access redirect below, a single vanity entry URL (`/dev-tools`, which just
  redirects here immediately), and the "home" link in the shell sidebar.
- **`enforce_page_access(route)`** — called at the top of every page's `get_context()`. Looks
  up the `Dev Portal Page` record for `route`, compares the visitor's roles against
  `allowed_roles` (`require_all_roles` off ⇒ any match is enough; on ⇒ every listed role must be
  held), and if denied, redirects (via `frappe.local.flags.redirect_location` +
  `raise frappe.Redirect`) to `resolve_home_route()` — quietly, no "access denied" page, per the
  earlier UX decision. A route with no matching registry record denies by default (fail closed).
  A guest visiting any gated page redirects to `/login`.
- **`get_nav_items(user=None)`** — returns every `Dev Portal Page` the current viewer can see,
  grouped by `nav_group` and sorted by `sort_order`, for the shared sidebar template. Exposed as
  a Jinja method via the `jinja` hook (`upande_dev_tools/hooks.py`) so the shell include can call
  it directly.

All portal pages require an authenticated Frappe session (desk or portal-only Website User
alike) — there is no anonymous access anywhere in this module.

### One shared shell, not copy-pasted per page

`upande_packhouse`'s own dashboards each inline a full copy of their CSS/sidebar per page —
workable there, but not something to carry into a codebase being open-sourced. Instead:

- **`upande_dev_tools/public/css/dev-portal.css`** — ports the Role Advisor tokens verbatim
  (ink/black palette, Poppins + Fraunces + JetBrains Mono, floating rounded sidebar, sticky
  pill-control topbar, KPI cards, styled tables) from `packhouse-portal.css`, so this portal is
  visually identical to Upande's other dashboards, in one file instead of duplicated per page.
- **`upande_dev_tools/templates/includes/dev_portal_shell.html`** — the sidebar + topbar chrome,
  `{% include %}`-ed by every `www/*.html` page. The sidebar's nav list comes from
  `get_nav_items()` — nothing in this file is page-specific.
- Each page's own `.html`/`.py` supplies only its title, its content, and (for data pages) its
  own whitelisted API calls (from Phase 1's `api/requests.py`/`api/deployments.py`, or new ones
  each sub-project adds) — chrome and access logic are never duplicated per page.

### The settings page

`www/dev-portal-settings.html`/`.py` — itself a registered `Dev Portal Page`
(`require_all_roles=1`, `allowed_roles=[Dev Team, System Manager]`), self-registered the same
way every other page is. Its content: a table of every `Dev Portal Page` record (route, title,
nav group) with `allowed_roles` and `require_all_roles` editable inline via whitelisted API
calls — no separate doctype form needed for this narrow purpose, though a System Manager can
always also reach the raw `Dev Portal Page` list from the desk if needed.

## Testing

Doctype tests for `Dev Portal Page` (field validation, autoname). Unit tests for
`resolve_home_route` (role-priority order, guest fallback) and `enforce_page_access` (allowed
passes through, denied redirects to the resolved home route, `require_all_roles` semantics,
fail-closed on an unregistered route) — these test the pure logic directly; they don't require
the target pages (dev dashboard, PM dashboard, request portal) to exist yet, since Sub-projects
2-4 build those. The settings page's own dual-role gate is tested the same way Phase 1 tested
workflow role gates: as System Manager only, as Dev Team only, as neither, as both.

## Out of scope (deferred to Sub-projects 2-4)

- The dev dashboard, PM dashboard, and request portal pages themselves — this sub-project
  registers the *mechanism*, not those pages' content.
- Rebuilding Code Editor and Hooks Explorer as portal pages (Sub-project 2).
- Any notification/email mechanism on Request or Deployment Request status changes.
- Per-widget or per-section access control within a page — this phase gates whole pages only.
