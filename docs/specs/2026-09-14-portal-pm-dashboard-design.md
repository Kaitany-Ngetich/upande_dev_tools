# Phase 2, Sub-project 4: Projects Manager Dashboard — Design

Date: 2026-09-14
App: `upande_dev_tools`
Related: `docs/specs/2026-09-13-portal-shell-design.md` (Sub-project 1 — the shell/access-control
this sub-project builds pages on), `docs/specs/2026-09-13-requests-backlog-phase1-design.md`
(Phase 1 — `get_review_queue`/`triage_request`/`get_backlog_board`, all reused unchanged here)

## Context: the wider roadmap

Sub-projects 1-3 built the portal shell and a full Developer-facing surface (three ported desk
tools plus four new pages). This sub-project is the Projects Manager side: Phase 1 already shipped
two whitelisted API functions with zero UI — `get_review_queue()` (pending `Request` approvals) and
`triage_request()` (the actual Approve/Reject/Defer action, already re-enforced at the workflow-
transition level by Phase 1's own native Frappe Workflow, independent of anything this sub-project
adds) — plus `get_backlog_board(project=...)`, already consumed by the Developer backlog board and
reusable here unchanged. `portal.py`'s `HOME_ROUTE_BY_ROLE` has reserved `/pm-dashboard` for the
`Projects Manager` role since Sub-project 1, unbuilt until now — the same situation `/dev-dashboard`
was in before Sub-project 2.

This bench already has real data to build against: the `Projects Manager` role exists and is held
by ~29 real users, and 26 real `Project` records exist (Karen Roses / Kaitet agricultural projects).

## Problem

- A Projects Manager logging in today reaches no home page at all — `enforce_page_access` on the
  unregistered `/pm-dashboard` route falls through to the loop-guard's `/app` fallback (the desk),
  defeating the entire point of the portal for this audience.
- Pending `Request` approvals are only reachable via the desk's own workflow UI. `triage_request`
  already exists and already re-checks the `Projects Manager` role at the workflow-transition level
  (Phase 1's native Frappe Workflow), but nothing in the portal calls it.
- There is no cross-project view of health at all — a PM managing multiple projects has no single
  place to see which ones have overdue work or a backlog of pending approvals.

## Design

### A new nav group: "Management"

Distinct from the existing "Developer" group — these two pages are gated to `allowed_roles=
["Projects Manager"]`, not `Dev Team`. (A user holding both roles sees both nav groups; that's the
existing OR-semantics `enforce_page_access`/`get_nav_items` already provide, nothing new needed.)

| Route | Title | `sort_order` | Data source |
|---|---|---|---|
| `/pm-dashboard` | Dashboard | 10 | new `api.project_health.get_project_health` |
| `/review-queue` | Review Queue | 20 | existing `api.requests.get_review_queue` (read) + existing `api.requests.triage_request` (actions) |

Both follow the exact pattern every page in this project uses: `enforce_page_access` in
`get_context`, the `head_include` block override, `{% call dpx_shell() %}`.

### `/pm-dashboard` — portfolio + per-project health

New endpoint, `upande_dev_tools/api/project_health.py`:

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

(No pagination — 26 projects today, and this is a portfolio-wide summary view, not a growing log
like Code Snapshots/Activity Log; if the project count grows enough to matter, that's a future
change, not a concern for this sub-project.)

The page renders three KPI tiles (open projects, total overdue tasks, total open requests) plus a
table of projects with a completion percentage (`completed_tasks / total_tasks`), overdue count,
and open-request count per row — each row links to `/backlog-board?project=<name>` (Sub-project 3's
existing page, reused unchanged) for the detail view.

### `/review-queue` — the PM's actual approval work

No new endpoint — this page is a front-end for two existing, unchanged Phase 1 functions:
`get_review_queue()` (list) and `triage_request(name, action, project=None, priority=None)`
(action). The page renders each pending `Request` as a row with its title, type, product area,
raised-by, age, an editable project picker and priority selector, and three buttons — Approve,
Reject, Defer — each calling `triage_request` with the matching workflow action name. A
successful action removes that row from the table (it's no longer `Under Review`) without a full
page reload.

Because `triage_request` calls `apply_workflow`, which itself checks the `Projects Manager` role at
the Workflow Transition level, this page carries no special new authorization logic beyond the
standard page-level `enforce_page_access` gate — the real authorization was already built in
Phase 1 and needs no duplication here.

## Testing

- `enforce_page_access` gating tests for both new pages (Projects Manager permits, no-role denies),
  matching every prior page in this project.
- Registration-attribute tests for both new `Dev Portal Page` records.
- A permission-denial test for `get_project_health` (a zero-role/Dev-Team-only user gets
  `frappe.PermissionError`), matching the pattern Sub-project 2's security fix established.
- No new test for `get_review_queue`/`triage_request` themselves — both are unchanged, already
  Phase-1-tested functions; this sub-project only adds a front-end.
- A nav-group test confirming both new "Management" pages appear, in order, alongside the existing
  "Developer" group's seven — the full nine-page registry, sorted by `nav_group asc, sort_order asc`.

## Out of scope

- Any change to `get_review_queue`/`triage_request`/`get_backlog_board`'s own logic.
- A dedicated "create/edit Project" page — Project management stays on the desk.
- Notifications when a new Request enters the review queue.
- Any Gantt/timeline visualization — the health table is a flat summary, not a scheduling view.
