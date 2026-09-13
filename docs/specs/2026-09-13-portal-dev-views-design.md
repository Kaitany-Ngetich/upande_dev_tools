# Phase 2, Sub-project 3: New Developer Portal Views — Design

Date: 2026-09-13
App: `upande_dev_tools`
Related: `docs/specs/2026-09-13-portal-shell-design.md` (Sub-project 1 — the shell/access-control
this sub-project builds pages on), `docs/specs/2026-09-13-portal-dev-tools-port-design.md`
(Sub-project 2 — the ported Tools Dashboard this sub-project extends)

## Context: the wider roadmap

Sub-project 2 ported three existing desk tools into the portal. This sub-project is the other
half of Phase 2's original "Developer dashboard" scope: new dev-facing views that never existed
anywhere before. Two of the four — My Day and the Backlog Board — turn out to already have
working, permission-checked API endpoints from Phase 1 (`get_my_day`, `get_backlog_board`,
`get_upcoming_meetings` in `api/requests.py`) that have simply never had a UI; this sub-project is
mostly front-end work for those two. The other two — Code Snapshots and Activity/Error Log — need
new, small, paginated API endpoints, since the existing `api/dashboard.py` only ever returns a
top-N summary for the Tools Dashboard's cards.

## Problem

- Developers have no single place to see "what am I supposed to work on today" (My Day) or "what's
  in the pipeline across Requests and Tasks" (Backlog Board) — both already computed server-side,
  never surfaced.
- The Tools Dashboard's "Recent Backup Snapshots" and "Recent Errors" cards are dead-ends: a top-10
  summary with no way to search, filter, or see more without leaving the portal for the desk.

## Design

### Four new portal pages, all under the existing "Developer" nav group

| Route | Title | `sort_order` | Data source |
|---|---|---|---|
| `/my-day` | My Day | 40 | `api.requests.get_my_day` (unchanged) |
| `/backlog-board` | Backlog Board | 50 | `api.requests.get_backlog_board` (unchanged) |
| `/code-snapshots` | Code Snapshots | 60 | new `api.code_snapshots.get_snapshots` |
| `/activity-log` | Activity Log | 70 | new `api.activity_log.get_activity_log` |

All four follow the exact pattern every page in Sub-projects 1-2 uses: `enforce_page_access` in
`get_context`, the `head_include` block override, `{% call dpx_shell() %}`, registered via
`register_dev_portal_page(..., roles=["Dev Team"])` in `setup.py`.

### My Day (`/my-day`)

Renders `get_my_day()`'s two lists directly: today's assigned `Task`s (already sorted by priority
descending) as a simple card list, and today's meetings (already sorted by start time) beneath it.
No new API, no new logic — this page's entire job is presenting data the backend already computes
correctly. `get_my_day` already permission-checks (a user can only ever see their own day unless
they hold a `REVIEWER_ROLES` role), so the page itself only needs the standard `Dev Team`
`enforce_page_access` gate on top.

### Backlog Board (`/backlog-board`)

Renders `get_backlog_board()`'s `{"tasks": [...], "requests": [...]}` as two side-by-side board
sections — "Requests" and "Tasks" — each internally grouped into columns. Columns are **derived
from whatever distinct `workflow_state` (Requests) / `status` (Tasks) values are actually present
in the returned rows**, not a hardcoded list of possible statuses — this keeps the board honest
about the data's real shape (a `workflow_state`/`status` value added to either doctype later shows
up as its own column automatically, no page change needed) rather than encoding a parallel,
driftable list of "the statuses we expect to see" in the front-end. Within each column, rows keep
the ordering the API already returns (priority desc, then `exp_end_date`/target date asc).

An optional `?project=<name>` query param is passed straight through to `get_backlog_board(project=...)`
(which already permission-checks a specific project via `frappe.has_permission`) — useful later
when a Projects Manager view links here scoped to one project, though this sub-project doesn't
build that link itself (Sub-project 4's job).

### Code Snapshots (`/code-snapshots`)

New endpoint, `upande_dev_tools/api/code_snapshots.py`:

```python
@frappe.whitelist()
def get_snapshots(app: str | None = None, search: str | None = None, start: int = 0, limit: int = 50) -> dict:
    _require_dev_team()
    filters: dict = {}
    if app:
        filters["app"] = app
    if search:
        filters["document_name"] = ["like", f"%{search}%"]
    rows = frappe.get_all(
        "Code Backup Snapshot",
        filters=filters,
        fields=["name", "snapshot_time", "source_type", "document_name", "module", "app",
                "changed_since_last_backup", "backed_up_by", "version_label"],
        order_by="snapshot_time desc",
        start=start,
        limit_page_length=limit,
        ignore_permissions=True,
    )
    total = frappe.db.count("Code Backup Snapshot", filters=filters)
    return {"rows": rows, "total": total}
```

(`Code Backup Snapshot`'s own doctype permissions are System-Manager-only — same situation
Sub-project 2's final review found and fixed for the other dev-tools endpoints — so this endpoint
uses `ignore_permissions=True` plus its own explicit `_require_dev_team()` guard from the start,
rather than shipping the same gap and fixing it in a follow-up review.)

The page renders a simple searchable/filterable table (search box, an app-name filter dropdown
populated from the distinct `app` values in the current result set) with "Load more" pagination
(bumping `start` by `limit` on each click) — no infinite-scroll complexity, matching the plain,
un-fancy interaction level the rest of this portal already uses (the settings page's own table is
the closest precedent).

### Activity Log (`/activity-log`)

New endpoint, `upande_dev_tools/api/activity_log.py`:

```python
@frappe.whitelist()
def get_activity_log(status: str | None = None, search: str | None = None, start: int = 0, limit: int = 50) -> dict:
    _require_dev_team()
    filters: dict = {}
    if status:
        filters["status"] = status
    if search:
        filters["title"] = ["like", f"%{search}%"]
    rows = frappe.get_all(
        "Developer Activity Log",
        filters=filters,
        fields=["name", "activity_time", "activity_type", "title", "description", "status",
                "source", "reference_doctype", "reference_name", "performed_by"],
        order_by="activity_time desc",
        start=start,
        limit_page_length=limit,
        ignore_permissions=True,
    )
    total = frappe.db.count("Developer Activity Log", filters=filters)
    return {"rows": rows, "total": total}
```

Same `?status=` query param the Tools Dashboard's "Recent Errors" card link uses
(`/activity-log?status=Error`) doubles as this page's own filter dropdown value, read from the URL
on page load and kept in sync with the dropdown afterward. The status filter's options are the
doctype's own `Select` field options (`Success`/`Warning`/`Error`/`Info`), read from the doctype
meta rather than hardcoded a second time in the front-end.

### Tools Dashboard UI update

`public/js/dev-dashboard-portal.js`'s existing card-rendering functions get minimal changes, not a
redesign:

- The "Snapshots Today" / "Last Backup" KPI tiles and the "Recent Backup Snapshots" card's header
  become a link to `/code-snapshots`.
- The "Recent Errors" card's header becomes a link to `/activity-log?status=Error`.
- The "Recent Activity" card's header becomes a link to `/activity-log`.
- The version-check KPIs, the field-difference card, and the hooks-summary card are unchanged
  (version/field-difference have no portal page in this sub-project's scope — they keep linking to
  the desk via the existing `/app/<slug>` pattern Sub-project 2 established; hooks-summary already
  links to `/hooks-explorer` via the existing `udt_open_hooks_explorer()` fix).

## Testing

- `enforce_page_access` gating tests for all four new pages (Dev Team permits, no-role denies),
  matching the exact pattern every prior page in this project uses.
- Registration-attribute tests for all four new `Dev Portal Page` records (route, title, icon,
  nav_group, sort_order, allowed_roles) — Sub-project 2's final review flagged this exact gap for
  its own three pages; these four ship with it from the start.
- Permission-denial tests for both new API endpoints (`get_snapshots`, `get_activity_log`) — a
  zero-role user gets `frappe.PermissionError` — matching the exact pattern Sub-project 2's
  security fix established, applied from the start rather than discovered in a later review.
- A test confirming the Developer nav group now lists all seven tools — the three from
  Sub-project 2 (`dev-dashboard`, `hooks-explorer`, `code-editor`) plus this sub-project's four
  (`my-day`, `backlog-board`, `code-snapshots`, `activity-log`) — in `sort_order` order.
- No new tests for the ported/updated dashboard JS itself beyond a live render check, consistent
  with how every other JS-only change in this project has been verified.

## Out of scope

- Any change to `get_my_day`/`get_backlog_board`/`get_upcoming_meetings`'s own logic — this
  sub-project only builds front-ends for them.
- A dedicated portal page for `Module Version Check` or `Field Difference Log` — the Tools
  Dashboard's existing desk links for those stay as they are.
- Cross-project or PM-level views of the backlog board (Sub-project 4's job) — the `?project=`
  param is wired through but nothing in this sub-project links to it yet.
- Any notification/alerting on new errors appearing in the Activity Log.
