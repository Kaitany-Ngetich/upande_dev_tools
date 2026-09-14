# Phase 2, Sub-project 5: Customer/Employee Requests Portal — Design

Date: 2026-09-14
App: `upande_dev_tools`
Related: `docs/specs/2026-09-13-portal-shell-design.md` (Sub-project 1 — the shell/access-control
this sub-project builds a page on), `docs/specs/2026-09-13-requests-backlog-phase1-design.md`
(Phase 1 — `create_request`/`get_my_requests`, both reused unchanged here)

## Context: the wider roadmap

This is the last piece of Phase 2. Sub-projects 2-4 built the Dev Team and Projects Manager sides
of the portal; this sub-project is the third and final audience — any authenticated user who is
neither Dev Team nor Projects Manager (Kaitet/Karen Roses staff across departments, i.e. the
"customers" of the dev team in the original request, who are themselves Employees, not external
Frappe `Customer` records). `portal.py`'s `DEFAULT_AUTHENTICATED_ROUTE` has been `/requests-portal`
since Sub-project 1, reserved as the fallback home route for exactly this audience, unbuilt until
now — the same situation `/dev-dashboard` and `/pm-dashboard` were each in before their own
sub-projects.

Phase 1 already shipped the entire backend this sub-project needs, unchanged: `create_request()`
(any authenticated user, no role gate — `before_insert` auto-resolves `raised_by_user`/
`raised_by_employee`/`raised_by_contact` from the session user) and `get_my_requests(status=None)`
(scoped to `raised_by_user == frappe.session.user`, already returns `priority`/`workflow_state`).
This sub-project is front-end work only, the same shape Sub-project 3's My Day/Backlog Board were
for Phase 1's other unused endpoints.

## Problem

- Any authenticated user without a Dev Team or Projects Manager role reaches no home page at all
  today — `enforce_page_access` on the unregistered `/requests-portal` falls through to the desk.
- There is no way for a staff member to submit a dev request, or see the status/priority of one
  they already raised, without desk access — defeating the whole point of the portal for the
  audience it was originally scoped for.

## Design

### One new page, one new nav group

| Route | Title | `nav_group` | `sort_order` | `allowed_roles` |
|---|---|---|---|---|
| `/requests-portal` | My Requests | `Requests` | 10 | `["All"]` |

`"All"` is the one role every Frappe user holds unconditionally, including Dev Team and Projects
Manager users — so this page (and its own nav group) is visible to literally everyone, not just
the audience it defaults new users to. That's intentional: nothing about submitting or tracking a
request is Dev-Team- or PM-specific, and a Dev Team member occasionally wants to raise a request
like anyone else. `enforce_page_access`'s existing fail-closed design (deny on unregistered route,
deny on empty `allowed_roles`) is unaffected — `"All"` is a real, always-present role, not an
opt-out of the gate.

The page follows the exact pattern every prior page in this project uses: `enforce_page_access` in
`get_context`, the `head_include` block override, `{% call dpx_shell() %}`.

### Page content: submit + track, no new API

- A submit form: `title` (text), `request_type` (select — the same `Feature`/`Bug`/`Master
  Data`/`Question`/`Note` options `Request`'s own doctype defines, read from the field's own Select
  options rather than hardcoded a second time), `description` (textarea), `product_area` (text) —
  calling `upande_dev_tools.api.requests.create_request` unchanged. On success, clear the form and
  refresh the list below without a full page reload.
- A "My Requests" table below it: title, type, priority, status, submitted date — calling
  `upande_dev_tools.api.requests.get_my_requests` unchanged, re-fetched after every successful
  submission.
- No pagination — a single user's own request history is not expected to grow into the thousands;
  if that changes later, that's a follow-up, not a concern for this sub-project.

## Testing

- `enforce_page_access` gating tests: any authenticated user (even one holding no roles beyond the
  default `All`) permits; a Guest denies (the existing Guest-redirect-to-login path, already
  covered by the shared `enforce_page_access` test suite — no new logic to test there).
- A registration-attribute test for the new `Dev Portal Page` record.
- A test confirming Dev Team and Projects Manager users ALSO see the new `"Requests"` group
  alongside their own (`Developer`/`Management`) — the intentional cross-audience visibility this
  design relies on, not an accidental leak.
- No new tests for `create_request`/`get_my_requests` themselves — both are unchanged, already
  Phase-1-tested functions; this sub-project only adds a front-end.

## Out of scope

- Any change to `create_request`/`get_my_requests`'s own logic or permission model.
- A way for a customer/employee to edit or withdraw a request after submitting it — Phase 1's
  Request workflow already has no such transition from `Under Review`, and this sub-project doesn't
  add one.
- Any notification when a submitted request's status changes.
