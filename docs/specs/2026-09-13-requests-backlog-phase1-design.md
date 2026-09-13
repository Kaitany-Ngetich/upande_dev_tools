# Requests & Backlog — Phase 1: Data Model & Foundations — Design

Date: 2026-09-13
App: `upande_dev_tools`
Related: `upande_dev_tools/api/customization_exporter.py`, ERPNext `erpnext/projects` module,
`upande_scp`/`upande_work_management` fixture patterns (Role, Workflow, Custom DocPerm)

## Context: the wider roadmap

Projects currently end up with two backlogs: the official one (Project → Task) and an
unofficial one scattered across chats, calls, and memory, because raising a proper Task
has too much friction for a busy developer or a customer. The fix is a lightweight
**Requests** layer that funnels every incoming ask (customer feature request, employee
report, developer quick-note) into one reviewable queue, from which a Projects Manager
promotes what matters into the official backlog (Task).

This is phase 1 of 3:

1. **Phase 1 (this spec)** — `Request` doctype, approval workflow, Project/Task
   customizations, roles, and the whitelisted API. Usable from the desk immediately;
   the foundation the later phases build on.
2. **Phase 2** — `www` portal: role-scoped dashboards (Developer, Projects Manager,
   Customer/Employee) and the settings page, replacing the current desk pages. Every
   audience sees upcoming meetings and each developer's tasks for the day, scoped to
   what that audience is allowed to see.
3. **Phase 3** — mobile app (quick-capture + backlog + stats), styled to match
   `upande-production` / `upande-packhouse`. Same calendar/day view as the dashboard,
   but deeper — a developer's own meetings and today's tasks are the app's home
   screen, not a widget on it.

Each phase gets its own spec and plan. This document covers Phase 1 only.

## Problem

- Developers are too busy to keep the backlog current, so real asks live in phone
  calls, chat threads, and meetings instead.
- Project Managers have no single source of truth and must reconstruct status from
  multiple informal channels.
- There is no low-friction way for a developer to jot something down on their phone,
  nor for a customer or employee to raise a request and see when it will be
  prioritized.
- The existing `upande_dev_tools` app has no Projects-module integration at all: no
  custom fields, no roles, no fixtures beyond code-tooling doctypes.

## Module layout

`upande_dev_tools` currently has one module (`Upande Dev Tools`, holding the
code/version/backup-tooling doctypes and pages) plus app-root packages (`api/`,
`backup/`, `comparison/`, `config/`) — this already matches how Frappe apps split a
flat app-root layer from a module folder (e.g. `erpnext/api.py` next to
`erpnext/projects/`). Phase 1 adds a **second module**, `Requests`, following the same
folder shape ERPNext's own `projects` module uses:

```
upande_dev_tools/
  requests/
    __init__.py
    utils.py                          # whitelisted API + cross-doctype helpers
    doctype/
      request/
        request.json
        request.py
        request.js
        request_list.js
    dashboard_chart/
      requests_by_status/
    number_card/
      open_requests/
    workspace/
      requests/
        requests.json
  fixtures/
    role.json                         # Dev Team
    workflow.json                     # Request Review
    workflow_state.json
    workflow_action_master.json
    custom_field.json                 # Task.custom_request, Task.custom_planned_for
    custom_docperm.json               # Dev Team grants on Request + settings doctype
```

`modules.txt` gains `Requests`. The existing `Upande Dev Tools` module is untouched in
Phase 1 (its own light cleanup, if any, is tracked separately from this feature work).

## The `Request` doctype

One doctype covers every kind of incoming ask — customer feature request, employee
issue report, developer quick-note — distinguished by `request_type`. This keeps the
system to a single funnel instead of parallel "official" and "unofficial" tables.

**Fields**

| Field | Type | Notes |
|---|---|---|
| `title` | Data | Required. Only required field for a `Note`. |
| `description` | Text Editor | Optional. |
| `request_type` | Select | `Feature`, `Bug`, `Master Data`, `Question`, `Note`. `Note` is the frictionless dev quick-capture case — title only, no review expected until the developer chooses to promote it. |
| `product_area` | Data | Free text (e.g. "CRM", "Payroll") — the submitter's own words; not a Link, since a customer won't know internal module names. |
| `priority` | Select (`Low`/`Medium`/`High`/`Critical`) | Set by the Projects Manager at Approval. This is what a customer sees as "when this will be prioritized." |
| `project` | Link → Project | Optional at creation, required before `Approved`. |
| `linked_task` | Link → Task | Read-only; set when the request is Scheduled. |
| `raised_by_user` | Link → User | Defaults to the session user. |
| `raised_by_employee` | Link → Employee | Auto-resolved from the session user via `Employee.user_id`, when one exists. |
| `raised_by_contact` | Link → Contact | Auto-resolved for portal/customer submissions. |
| `source` | Select (`Web Portal`/`Mobile App`/`Desk`) | Set by the API method used to create it, not the user. |
| `resolution_notes` | Small Text | Filled in on completion. |

Standard Frappe attachments and the document comment timeline cover screenshots and
discussion — no custom fields needed for those.

## Workflow (approval = priority management)

A native **Workflow** (fixture-shipped, same mechanism as `upande_scp`'s
`Spray Supervisor` flow and `upande_work_management`'s approval chain) drives the
lifecycle instead of ad-hoc status code:

```
Open --(submit, automatic)--> Under Review --(Approve)--> Approved
                                    |                          |
                                    +--(Reject)--> Rejected    +--(Schedule)--> Scheduled --(start work)--> In Progress --(complete)--> Completed
                                    |
                                    +--(Defer)--> Deferred
```

- `Open → Under Review` happens automatically on submit — no separate action.
- `Approve` / `Reject` / `Defer` are restricted to the **Projects Manager** role,
  which already exists in the Projects module (`erpnext/projects/doctype/project`) —
  no need to invent a new "Project Manager" role.
- `Approve` requires `project` and `priority` to be set (validated in
  `request.py`, not just the workflow transition).
- `Schedule` creates or links a `Task` under `project`, copies `title`/`description`
  onto it, sets `Task.custom_request` back to this Request, and moves the Request to
  `Scheduled`. From here the Task **is** the official backlog item; the Request keeps
  the audit trail of where it came from.
- A `Note`-type Request needs no external review. Rather than adding a second workflow
  graph, `promote_to_task` (see API surface below) applies the existing `Approve` then
  `Schedule` transitions programmatically in one call when `request_type == "Note"` and
  the caller is the Request's own owner — the workflow definition stays a single linear
  graph; only the intermediate wait is skipped for this one type.

## Project/Task customizations (fixtures)

Two `Custom Field`s on `Task`, exported the same way the app already exports
customizations (`upande_dev_tools/api/customization_exporter.py`), shipped as
`fixtures/custom_field.json`:

- `custom_request` (Link → Request, read-only) — traceability back to the originating
  Request.
- `custom_planned_for` (Date) — "what I'm working on today," set by a developer from
  the dashboard/app. Deliberately separate from `exp_start_date` (schedule) since a
  developer's daily pick and the task's planned schedule are different concerns.

No new `Project` fields are needed in Phase 1 — Phase 2's dashboards read `Task` +
`Request` data filtered by `Project` directly.

## Roles & permissions

- **`Dev Team`** — a new Role, shipped via `fixtures/role.json` (same shape as
  `upande_scp/fixtures/role.json`). Not assigned to anyone automatically; site admins
  assign it, same as any other shipped role.
- **Settings page requires `Dev Team` AND `System Manager`.** Standard Frappe
  `DocPerm` role lists are OR'd, so expressing an AND requirement needs a
  `has_permission` hook (registered in `hooks.py`'s existing, currently-commented
  `has_permission` slot) that checks both roles are present in
  `frappe.get_roles()` before allowing access to the settings doctype. This is the
  standard Frappe mechanism for permission logic finer than a plain role list.
- `Request` doctype `DocPerm`/`Custom DocPerm`: `Dev Team` gets read/write/create;
  `Projects Manager` gets read/write plus the workflow actions above; portal/customer
  access is granted narrowly through the whitelisted API (Phase 2), not broad
  doctype-level portal permissions.
- **These are the only two roles the whole feature ever checks**, in every phase:
  `Dev Team` gates every developer-facing view (the portal's Developer dashboard, and
  the mobile app in its entirety — Phase 3 introduces no app-specific role); `Dev Team`
  **and** `System Manager` together gate settings/admin surfaces, whether that surface
  is the portal's settings page or an equivalent admin screen inside the mobile app.
  Later phases must reuse this pair rather than defining new roles or a separate
  mobile permission model.

## Calendar integration

"Meetings" are native Frappe `Event` records — no new doctype and no new custom
fields are needed. `Event` already carries everything required for this:

- `event_participants` (child table) resolves participants by `email`, which matches
  `Employee.user_id` / `User.name` — this is how "which meetings is this developer in"
  is answered.
- `links` (Dynamic Link child table) is the native way to associate an `Event` with a
  `Project` or `Task` — this is how "which meetings belong to this project" is
  answered, using the mechanism Frappe already ships rather than inventing a
  `Request`/`Event` link field.

Two whitelisted helpers in `requests/utils.py` sit on top of this, and are what Phase 2
and Phase 3 both call — neither phase re-implements the query:

- `get_upcoming_meetings(project=None)` — `Event`s linked (via `links`) to the given
  project, or, with no project, every event the caller participates in. Powers the
  "upcoming meetings" view for all three dashboard audiences and the mobile app.
- `get_my_day(user=None)` — one call combining a developer's today: `Task`s assigned to
  them (via the standard Frappe assignment/`ToDo` mechanism — `_assign` — **not** a new
  "assigned developer" field) where `custom_planned_for` is today, plus today's `Event`s
  from `get_upcoming_meetings`. This is the mobile app's home-screen data source and
  the dashboard's per-developer widget; both read the same method so the two surfaces
  never drift apart.

Visibility is scoped by caller inside these methods, not by two separate
implementations: a customer calling `get_upcoming_meetings(project=X)` only ever sees
events linked to a project they're a stakeholder on; a developer calling `get_my_day()`
only ever sees their own assignments and events.

## API surface (shared by desk, portal, and mobile)

All whitelisted methods live in `upande_dev_tools/requests/utils.py` and are called the
same way from every client — the desk, the future `www` portal, and the mobile app —
over `/api/method/...`, matching how `upande-packhouse`/`upande-production` already
authenticate (session cookie from `/api/method/login`, no separate mobile-only API):

- `create_request(title, request_type, description=None, product_area=None, project=None)`
  — resolves `raised_by_*` and `source` server-side from the session.
- `get_my_requests(status=None)` — the caller's own requests, any state.
- `get_review_queue()` — requests in `Under Review`, for Projects Managers.
- `triage_request(name, action, project=None, priority=None)` — wraps the workflow
  action (`Approve`/`Reject`/`Defer`) plus the project/priority validation.
- `promote_to_task(name)` — the `Schedule` transition; creates/links the Task.
- `get_backlog_board(project=None)` — Tasks + linked Requests grouped by status, the
  data source for Phase 2's dashboards.
- `get_upcoming_meetings(project=None)` / `get_my_day(user=None)` — see Calendar
  integration above.

## Testing

Standard Frappe doctype tests (`test_request.py`) covering: workflow transition guards
(Approve without project/priority fails; only Projects Manager can Approve/Reject/Defer;
a Note can self-promote), `raised_by_*` auto-resolution for a user with and without a
linked Employee, and `promote_to_task` producing a Task with `custom_request` set back
correctly. `test_utils.py` covers `get_my_day` (returns only the calling user's assigned,
`custom_planned_for`-today tasks and their own events) and `get_upcoming_meetings`
(scoped to a project's linked events, or the caller's participation when no project is
given).

## Out of scope (deferred to later phases)

- The `www` portal pages and role-scoped dashboards, including any calendar/"my day"
  UI widget (Phase 2). Phase 1 ships only the `get_upcoming_meetings`/`get_my_day` API.
- The mobile app (Phase 3).
- Migrating the existing desk pages (`upande_dev_dashboard`, `hooks_explorer`,
  `code_editor`) into the portal (Phase 2).
- Any restructuring of the existing `Upande Dev Tools` module's code-tooling doctypes —
  out of scope for this feature; that module is already close to Frappe convention.
