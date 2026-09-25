# Request Decision Visibility & Scheduling — Design

**Status:** Approved by user, 2026-09-15. First sub-project of a larger Request/Task pipeline
redesign (see Context below); later sub-projects will be spec'd separately once this ships.

## Context

An investigation of the current Request → Task pipeline (backed by direct code reads, not the
older design docs which have drifted from what's actually shipped) found that several pieces of
the intended flow already work correctly:

- Request → Task conversion is automatic: when a Request's workflow reaches `Scheduled`,
  `Request.on_update()` creates the linked Task.
- The PM assigns a developer at the same moment as accepting a request (Review Queue's Accept
  button approves + schedules + assigns in one call).
- Developers see their scheduled work as Tasks in My Day.
- The PM dashboard already has a per-developer workload card.
- The Backlog Board's drag-and-drop already writes back to the server (both Kanban stage-drag and
  Gantt timeline-bar drag call real endpoints).
- Customers already see status changes on their own submitted requests.

This sub-project addresses the gaps that remained after that investigation, all clustered around
one theme: **decisions get made, but the reasoning and the schedule aren't visible or durable**.
Specifically:

1. `Request.resolution_notes` exists but nothing ever reads or writes it — customers see a status
   label, never a PM's explanation.
2. There is no date recording *when* a deferred request should be revisited.
3. The only schedule date lives on the Task (`custom_planned_for`), set later by whichever
   developer picks it up — nothing records a PM's committed date at approval time.
4. The PM dashboard has a status breakdown of requests, but no priority breakdown.

Other gaps found during the same investigation (customer-preferred-developer, customer-proposed
assignment, Issue→Task conversion, dead-code cleanup, broader e2e coverage beyond what this
sub-project needs) are explicitly **out of scope** here — they are candidate future sub-projects,
not part of this spec.

## Goals

- Every workflow decision (Approve/Reject/Defer/Schedule) can carry an optional note, and PM/Dev
  Team can also leave a free-standing note at any time, independent of a transition.
- Each note can be marked visible to the customer or internal-only.
- A deferred request always has a "revisit by" date; an overdue one surfaces on the PM dashboard.
- A scheduled request always has a PM-committed date, recorded at the moment of scheduling (not
  left to the assigned developer to set later), and that date flows onto the created Task.
- The PM dashboard gains a priority breakdown of open requests, matching the existing cards'
  conventions (period filter, click-through to a filtered list).
- The customer portal surfaces the decision history and the scheduled date on their own requests.
- The full customer → PM → developer → customer loop is covered by a real end-to-end test.

## Non-goals

- Customer-preferred-developer field, customer-proposed assignment (a future sub-project).
- Issue → Task conversion (a future sub-project; only Request → Task exists today and stays as is).
- Any change to the workflow's state machine itself (states/transitions/roles are unchanged).
- Cleanup of the dead code found during investigation (duplicate `dashboard.py`, unused
  `get_backlog_board`, unused `get_project_health`/`get_team_workload`) — noted as a separate,
  low-risk cleanup candidate, not bundled into this feature work.

## Data model

### New doctype: `Request Update`

One row per note/decision event on a Request — the audit trail this sub-project is built around.

| Field | Type | Notes |
|---|---|---|
| `request` | Link → Request | required |
| `action` | Data | the workflow transition this note was attached to (`Approve`/`Reject`/`Defer`/`Schedule`/`Promote Note`/`Start Work`/`Complete`/`Reopen`), or blank for a free-standing note |
| `from_state` | Data | workflow state before the transition, blank for a free-standing note |
| `to_state` | Data | workflow state after the transition, blank for a free-standing note |
| `note` | Text | optional |
| `visible_to_customer` | Check | default 0 |
| `actor` | Link → User | auto-set to the acting user, read-only |

Standard Frappe `creation`/`owner` fields provide the timestamp and author; no separate date field
needed. Ordered by `creation` ascending when displayed as a history.

**Permissions:** `System Manager` (all), `Projects Manager` (create/read), `Dev Team`
(create/read) — mirrors `Request`'s own permission model. There is no portal-level `DocPerm`;
customer access is exclusively through the new `get_request_updates` whitelisted method (see
below), matching the existing pattern for `Request` itself.

### `Request` doctype changes

- **Remove** `resolution_notes` (Small Text) — dead field, fully superseded by `Request Update`.
  A one-time patch copies any existing non-empty `resolution_notes` value into a synthesized
  `Request Update` row (`action`/`from_state`/`to_state` blank, `visible_to_customer` = 0, `note`
  = the old field's content) before the field is removed, so no historical data is silently lost.
- **Add** `scheduled_date` (Date, optional) — the PM's committed date, set when a request is
  scheduled; independently editable at any later time via the standalone date-update endpoint
  (not locked to the moment of the Schedule transition).
- **Add** `deferred_until` (Date, optional but required whenever the request is put into
  `Deferred`) — same independent-editability rule.

### `Task` doctype

No schema change. `Request.on_update()`'s existing Task-creation step (fires when `workflow_state`
becomes `Scheduled`) is extended to seed the new Task's `custom_planned_for` from
`Request.scheduled_date` when that field is set.

## Backend API changes (`upande_dev_tools/api/requests.py` unless noted)

- **`add_request_note(name, note, visible_to_customer, action=None, from_state=None,
  to_state=None)`** — new. Creates a `Request Update` row. Two call shapes:
  - *Standalone*: called directly by the new "Add note" UI control, `action`/`from_state`/
    `to_state` left blank.
  - *Transition-attached*: called internally, immediately after a successful `triage_request` /
    `accept_request` / `promote_to_task` call, passing the real transition's action and states.
  - Permission: `Projects Manager` + `Dev Team` (reusing the existing `REVIEWER_ROLES` set already
    defined in this file, despite the name — it currently gates several PM+Dev-Team-shared
    endpoints already, e.g. `get_assignable_users`).
- **`update_request_dates(name, scheduled_date=None, deferred_until=None)`** — new. Updates
  either or both fields directly, independent of any workflow transition. Same permission as
  above. At least one of the two parameters must be provided.
- **`get_request_updates(name)`** — new. Returns the note history for a Request, ordered by
  `creation` ascending. If the caller has `REVIEWER_ROLES`, returns every row; otherwise (the
  customer-portal case) returns only rows where `raised_by_user == frappe.session.user` (checked
  by loading the parent Request) **and** `visible_to_customer = 1`.
- **`accept_request`** — gains a required `scheduled_date` parameter (this call both approves and
  schedules in one step, so the committed date must be supplied here, not left blank). Internally
  calls `add_request_note` with the transition's real action/states if a `note`/
  `visible_to_customer` pair is also passed (both optional, default `note=None`,
  `visible_to_customer=False`).
- **`triage_request`** — when `action` resolves to the `Defer` transition, `deferred_until`
  becomes a required parameter; validation error otherwise. Same optional `note`/
  `visible_to_customer` pass-through as `accept_request`.
- **`get_my_requests`** — extended to also select and return `scheduled_date` alongside the
  existing fields (`name, title, request_type, workflow_state, priority, project, linked_task,
  creation`).

### PM dashboard (`api/portfolio.py`)

- New `_priority_breakdown()` function: counts of currently-open (not `Completed`/`Rejected`)
  requests grouped by `priority`, scoped to the dashboard's existing period filter (7/30/90 days,
  matching how `_requests()` already scopes its own breakdown) and existing scope filter
  (Internal/External). Rendered as a new card on `pm-dashboard.html`, following the exact
  card/click-through convention of the existing `_requests()`/`_people()` cards — clicking a
  priority jumps to a Review-Queue-style filtered list.
- `_risks()` ("Needs attention") gains a new bucket: `Deferred` requests whose `deferred_until` has
  passed, merged into the same age-sorted list as the existing overdue-tasks/on-hold-issues/
  awaiting-decision entries.

## Frontend/UI changes

### Review Queue (`public/js/review-queue.js`)

- The Accept action's flow gains a required scheduled-date picker before it can submit (blocks
  submission with an inline validation message if left blank).
- The Defer action's flow gains a required deferred-until date picker, same validation treatment.
- All three actions (Accept/Defer/Reject) gain an optional note textarea and a "Visible to
  customer" checkbox, passed through to the note-carrying parameters described above.

### Standalone "Add note" control

A small button/icon, opening a modal (note text + visible-to-customer toggle + optional
scheduled-date/deferred-until fields), added wherever a Request is currently rendered to a
PM/Dev Team user:
- Review Queue rows (in addition to the transition-attached notes above — this is for adding a
  note without triggering any transition).
- Backlog Board request cards (`www/backlog-board.html`/`public/js/backlog-board.js`) — Requests
  there are `movable: false` today and stay that way; this only adds the note control, not
  drag-ability.
- PM Dashboard's request-related cards ("Needs attention", "What people asked for").

### Customer portal (`www/requests-portal.html` / `public/js/requests-portal.js`)

Each request card gains:
- A chronological note/decision history section, populated from `get_request_updates`, showing
  only the entries the API already filtered to `visible_to_customer = 1`.
- The scheduled date, when set, rendered as "Expected: `<date>`" alongside the existing status
  chip.

## Testing

- **`Request Update` doctype tests**: creation, the two permission tiers (System
  Manager/Projects Manager/Dev Team can create; other roles cannot), and the
  visible_to_customer-based filtering behavior exercised through `get_request_updates` rather
  than raw doctype access (matching how customer-facing access is tested elsewhere in this app).
- **API tests** for every new/changed method above: `add_request_note` (both call shapes),
  `update_request_dates`, `accept_request`'s new required `scheduled_date` (including the
  validation-error case when omitted), `triage_request`'s Defer path requiring `deferred_until`,
  `get_request_updates`'s two-tier visibility, `get_my_requests` returning `scheduled_date`.
- **Dashboard tests**: `_priority_breakdown()` counts and period-filter scoping; `_risks()`'s new
  overdue-deferral bucket.
- **One end-to-end integration test**, covering the full loop this sub-project set out to make
  visible: a customer creates a request → a PM accepts it with a scheduled date, an assignee, and
  a customer-visible note → verify the resulting Task has the right `custom_planned_for` and is
  assigned to that developer → verify the customer's own view (`get_my_requests` +
  `get_request_updates`) surfaces the note and the scheduled date → simulate the developer
  completing the Task → verify the customer's view reflects the final state.

### Known dependency

There is a live, in-progress git rebase conflict in
`upande_dev_tools/tests/test_requests_api.py`, owned by a separate, currently-active session —
not something this project touched or will touch directly. The implementation plan for this spec
must confirm that conflict is resolved (or land its new tests in a way that doesn't collide with
it, e.g. a new test file) before starting the `triage_request`/`accept_request` test changes
above, since both this spec and that in-progress rebase touch the same file.

## Self-review

- **Placeholder scan:** no TBD/TODO markers; every requirement above states an exact behavior.
- **Internal consistency:** `resolution_notes`' removal is paired with a migration step so no data
  is silently dropped; `scheduled_date`/`deferred_until` are both introduced as independently
  editable per the user's explicit choice, and every endpoint description reflects that (no
  endpoint locks them to only being settable during a transition).
- **Scope check:** every requirement traces to one of the four gaps named in Context; the six
  explicitly out-of-scope gaps from the original investigation are named and deferred, not
  silently dropped.
- **Ambiguity check:** `REVIEWER_ROLES` vs. a note-specific role set was the one real ambiguity —
  resolved by reusing the existing `REVIEWER_ROLES` constant (Projects Manager + Dev Team) already
  defined in `api/requests.py`, matching the user's explicit "PM + Dev Team" answer on note
  authorship.
