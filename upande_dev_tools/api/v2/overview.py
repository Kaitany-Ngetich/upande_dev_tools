# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
"""Dev Tools Overview v2: the landing page of the Dev Tools portal.

Read-only. Every figure is computed in SQL over the full filtered set and is the SAME
definition the page it links to uses, so a card and its page agree for the same filters.

FILTERS (all optional): from_date / to_date (default: last 90 days, both ends inclusive),
product_area, priority.  A card that cannot honour a filter says so in `note`; it is
never silently ignored.

WHO SEES WHAT (mirrors the current endpoints; a card the caller's roles do not allow is
OMITTED from the response, never returned as zero):
  Open requests, Overdue work, Blocked work   any signed-in user   (Requests and the board are public,
                                                                   see requests.get_my_requests / board.get_board)
  Awaiting review                             Dev Team, Projects Manager, System Manager (requests.REVIEWER_ROLES)
  Deployments in flight                       Dev Team, Projects Manager, System Manager (deployments.DEPLOYMENT_VIEWER_ROLES)
  Backup freshness, Bench health, Activity    Dev Team (code_snapshots / dashboard / activity_log gate)
  Navigation tiles                            only pages portal._route_permits allows this user (+ Desk lists the user may read)

DEFINITIONS (date column in brackets)
  Open requests        Request created in the range [creation] whose workflow_state is not Completed,
                       Rejected, Withdrawn or Closed (blank counts as open; the board's "Done" stage).
  Awaiting review      Request created in the range with workflow_state = Under Review (the Review Queue).
  Overdue work         Task or Issue in a Dev Tools project, not Completed/Cancelled (Task) or
                       Resolved/Closed (Issue), whose due date [exp_end_date / sla_resolution_by] is
                       before today AND inside the range (the board's "late" flag).
  Blocked work         Request in state Deferred plus Issue On Hold, in a Dev Tools project, created
                       in the range [creation] (the board's "Blocked" stage; Tasks have no blocked state).
  Deployments in flight  Deployment Request in state Requested or In Progress, created in the range.
  Backup freshness     Newest Code Backup Snapshot at or before the end of the range, aged against the
                       end of the range (or now if that is later). Follows the range only.
  Bench health         Module Version Check rows, status derived exactly as the Dev Dashboard does:
                       uncommitted changes -> Dirty, else behind upstream -> Stale, else ahead -> Ahead,
                       else Clean. Current state: not affected by any filter.
  Developer activity   Developer Activity Log rows with activity_time in the range.

IDENTITIES (checked in tests / by hand, see report)
  open_requests + closed_requests_of_opened = requests_opened_in_range (= sum of by_state)
  clean + stale + dirty + ahead = apps
  chart opened (sum of buckets) = requests_opened_in_range; chart closed (sum) = requests that
  reached a closed state inside the range.
"""

import json
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import add_days, cint, get_datetime, getdate, now_datetime, today

from upande_dev_tools import dev_v2, portal
from upande_dev_tools.api.deployments import DEPLOYMENT_APPROVER_ROLES, DEPLOYMENT_VIEWER_ROLES
from upande_dev_tools.api.requests import REVIEWER_ROLES
from upande_dev_tools.setup import DEV_TOOLS_PROJECT_TYPE

DEV_TEAM_ROLES = {"Dev Team"}  # activity_log / code_snapshots / dashboard gate
CLOSED_REQUEST_STATES = ("Completed", "Rejected", "Withdrawn", "Closed")
TASK_DONE = ("Completed", "Cancelled")
ISSUE_DONE = ("Resolved", "Closed")
DEFAULT_DAYS = 90
MAX_RANGE_DAYS = 3660
ROW_LIMIT = 200
STALE_REVIEW_DAYS = 7

DEV_PROJECTS_SQL = "(SELECT name FROM `tabProject` WHERE project_type = %(ptype)s)"

PAGE_BLURBS = {
	"dev-tools": "This page",
	"dev-dashboard": "App versions, backups and recent developer activity",
	"my-backlog": "Your tasks, requests and upcoming meetings",
	"backlog-board": "Every task, issue and request on one board",
	"hooks-explorer": "What each installed app hooks into",
	"code-snapshots": "Saved copies of customised code",
	"version-check": "Which apps are behind, ahead or have local changes",
	"activity-log": "What the background jobs did, and when",
	"pm-dashboard": "How the portfolio is doing: delivery, risks, people",
	"review-queue": "New requests waiting for a decision",
	"requests": "Everything that has been asked for, and where it stands",
	"deployments": "Deployment requests, approvals and recent releases",
	"master-data": "Request types, priorities, product areas and tags",
	"code-editor": "Edit the code of installed apps, with a safety copy on every save",
	"dev-portal-settings": "Which pages the portal shows, and to whom",
	"data-seeder": "Pull data from a remote site for development and testing",
}

#: Portal pages that have no v2 page yet: (key, label, current route, icon). Listed in the
#: "Developer" group, linked to their current page, and shown to the roles that may open it.
PAGES_WITHOUT_V2 = ()

#: Desk lists, as in the Desk workspace "Dev Tools": (group, [(doctype, tile label, blurb, icon), ...]).
#: A tile is shown only when the user may read the doctype.
DESK_GROUPS = (
	(
		"Requests in Desk",
		(
			("Request", "Requests", "All raised requests", "layers"),
			(
				"Request Type",
				"Request Types",
				"Feature, bug, chore and the other kinds of request",
				"clipboard",
			),
		),
	),
	(
		"Deployments in Desk",
		(
			("Deployment Request", "Deployment Requests", "Ship an app to an instance", "truck"),
			("Deployment Instance", "Deployment Instances", "Where things get deployed", "cube"),
			("Deployment App", "Deployment Apps", "Apps tracked for deployment", "grid"),
		),
	),
	(
		"Bench health in Desk",
		(
			("Module Version Check", "Module Version Check", "Git drift per installed app", "check"),
			(
				"Code Backup Snapshot",
				"Code Backup Snapshots",
				"Point-in-time copies of customised code",
				"cube",
			),
			("Code Backup Settings", "Code Backup Settings", "What to back up and how often", "gear"),
			("Developer Activity Log", "Developer Activity Log", "What changed, and when", "chart"),
			("Field Difference Log", "Field Difference Log", "Local against live schema drift", "doc"),
		),
	),
	(
		"Master data in Desk",
		(
			("Priority Level", "Priority Levels", "Low, Medium, High, Urgent and their order", "chart"),
			("Product Area", "Product Areas", "The modules a request or task belongs to", "tree"),
			("Work Tag", "Work Tags", "The tag vocabulary tasks and requests use", "file"),
			("Dev Portal Page", "Dev Portal Pages", "Portal page registry and who sees each page", "layout"),
		),
	),
)


# ---------------------------------------------------------------------------- helpers


def _roles() -> set[str]:
	if frappe.session.user == "Guest":
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	return set(frappe.get_roles())


def _allowed(kind: str, roles: set[str]) -> bool:
	needed = {
		"public": None,
		"review": REVIEWER_ROLES,
		"deploy": DEPLOYMENT_VIEWER_ROLES,
		"approve": DEPLOYMENT_APPROVER_ROLES,
		"dev": DEV_TEAM_ROLES,
	}[kind]
	return needed is None or bool(needed & roles)


def _filters(from_date, to_date, product_area, priority) -> dict:
	end = getdate(to_date) if to_date else getdate(today())
	start = getdate(from_date) if from_date else add_days(end, -(DEFAULT_DAYS - 1))
	if start > end:
		start, end = end, start
	if (end - start).days > MAX_RANGE_DAYS:
		frappe.throw(_("Please choose a range of ten years or less."), frappe.ValidationError)
	return {
		"start": start,
		"end": end,
		"start_dt": f"{start} 00:00:00",
		"end_dt": f"{add_days(end, 1)} 00:00:00",  # exclusive
		"today": getdate(today()),
		"area": (product_area or "").strip() or None,
		"priority": (priority or "").strip() or None,
		"ptype": DEV_TOOLS_PROJECT_TYPE,
	}


def _params(f: dict) -> dict:
	return {
		"start": f["start"],
		"end": f["end"],
		"start_dt": f["start_dt"],
		"end_dt": f["end_dt"],
		"today": f["today"],
		"area": f["area"],
		"priority": f["priority"],
		"ptype": f["ptype"],
	}


def _sql(query: str, f: dict, as_dict=True):
	return frappe.db.sql(query, _params(f), as_dict=as_dict)


def _area_sql(f: dict, col: str) -> str:
	return f" AND {col} = %(area)s" if f["area"] else ""


def _prio_sql(f: dict, col: str = "priority") -> str:
	return f" AND {col} = %(priority)s" if f["priority"] else ""


def _doc_url(doctype: str, name: str) -> str:
	return "/app/{}/{}".format(doctype.lower().replace(" ", "-"), name)


def _fmt_dt(value) -> str:
	return get_datetime(value).strftime("%-d %b %Y %H:%M") if value else ""


def _fmt_d(value) -> str:
	return getdate(value).strftime("%-d %b %Y") if value else ""


def _can_open(route: str, roles: set[str]) -> bool:
	"""portal._route_permits, remembered for the rest of the request (it costs two queries and
	one request asks about ~40 routes). `route` may start with a slash."""
	cache = getattr(frappe.local, "dov_route_access", None)
	if cache is None:
		cache = frappe.local.dov_route_access = {}
	key = (route.lstrip("/"), frozenset(roles))
	if key not in cache:
		cache[key] = portal._route_permits(route, roles)
	return cache[key]


def _route_for(roles: set[str], *candidates: str) -> str | None:
	"""First v2 route among `candidates` (NAV keys) the user may open."""
	by_key = {key: (href, route) for _g, items in dev_v2.NAV for key, _l, href, route, _i in items}
	for key in candidates:
		href, route = by_key[key]
		if _can_open(route, roles):
			return href
	return None


# ------------------------------------------------------------------------------ figures


def _request_states(f: dict) -> dict[str, int]:
	"""Requests created in the range, by workflow state ('' = blank)."""
	rows = _sql(
		"""SELECT COALESCE(workflow_state, '') AS state, COUNT(*) AS n FROM `tabRequest`
		   WHERE docstatus < 2 AND creation >= %(start_dt)s AND creation < %(end_dt)s"""
		+ _area_sql(f, "product_area")
		+ _prio_sql(f)
		+ " GROUP BY 1",
		f,
	)
	return {r.state: cint(r.n) for r in rows}


def _overdue_sql(f: dict) -> tuple[str, str]:
	"""(task query, issue query) selecting rows; columns shared via `_select` below."""
	task = (
		"""FROM `tabTask` WHERE project IN """
		+ DEV_PROJECTS_SQL
		+ """ AND status NOT IN ('Completed', 'Cancelled')
		   AND exp_end_date > '1000-01-01' AND exp_end_date < %(today)s
		   AND exp_end_date BETWEEN %(start)s AND %(end)s"""
		+ _area_sql(f, "custom_module")
		+ _prio_sql(f)
	)
	issue = (
		"""FROM `tabIssue` WHERE project IN """
		+ DEV_PROJECTS_SQL
		+ """ AND status NOT IN ('Resolved', 'Closed')
		   AND sla_resolution_by IS NOT NULL AND DATE(sla_resolution_by) < %(today)s
		   AND DATE(sla_resolution_by) BETWEEN %(start)s AND %(end)s"""
		+ _area_sql(f, "custom_module")
		+ _prio_sql(f)
	)
	return task, issue


def _overdue_count(f: dict) -> int:
	task, issue = _overdue_sql(f)
	t = _sql("SELECT COUNT(*) AS n " + task, f)[0].n
	i = _sql("SELECT COUNT(*) AS n " + issue, f)[0].n
	return cint(t) + cint(i)


def _blocked_parts(f: dict) -> tuple[str, str]:
	req = (
		"""FROM `tabRequest` WHERE docstatus < 2 AND workflow_state = 'Deferred'
		   AND project IN """
		+ DEV_PROJECTS_SQL
		+ """ AND creation >= %(start_dt)s AND creation < %(end_dt)s"""
		+ _area_sql(f, "product_area")
		+ _prio_sql(f)
	)
	issue = (
		"""FROM `tabIssue` WHERE status = 'On Hold' AND project IN """
		+ DEV_PROJECTS_SQL
		+ """ AND creation >= %(start_dt)s AND creation < %(end_dt)s"""
		+ _area_sql(f, "custom_module")
		+ _prio_sql(f)
	)
	return req, issue


def _blocked_count(f: dict) -> int:
	req, issue = _blocked_parts(f)
	return cint(_sql("SELECT COUNT(*) AS n " + req, f)[0].n) + cint(
		_sql("SELECT COUNT(*) AS n " + issue, f)[0].n
	)


def _deploy_states(f: dict) -> dict[str, int]:
	rows = _sql(
		"""SELECT workflow_state AS state, COUNT(*) AS n FROM `tabDeployment Request`
		   WHERE docstatus < 2 AND creation >= %(start_dt)s AND creation < %(end_dt)s GROUP BY 1""",
		f,
	)
	return {(r.state or ""): cint(r.n) for r in rows}


def _pending_approvals(f: dict) -> int:
	return cint(
		_sql(
			"""SELECT COUNT(*) AS n FROM `tabDeployment Request`
			   WHERE docstatus < 2 AND requires_approval = 1 AND approval_status = 'Pending'
			   AND creation >= %(start_dt)s AND creation < %(end_dt)s""",
			f,
		)[0].n
	)


def _backup(f: dict) -> dict:
	as_of = min(now_datetime(), get_datetime(f["end_dt"]) - timedelta(seconds=1))
	last = frappe.db.sql(
		"SELECT MAX(snapshot_time) FROM `tabCode Backup Snapshot` WHERE snapshot_time <= %s", (as_of,)
	)[0][0]
	in_range = frappe.db.sql(
		"SELECT COUNT(*) FROM `tabCode Backup Snapshot` WHERE snapshot_time >= %s AND snapshot_time < %s",
		(f["start_dt"], f["end_dt"]),
	)[0][0]
	interval = cint(frappe.db.get_single_value("Code Backup Settings", "backup_intervals_hours")) or 4
	enabled = bool(cint(frappe.db.get_single_value("Code Backup Settings", "enabled")))
	age_hours = None if not last else max(0.0, (as_of - get_datetime(last)).total_seconds() / 3600)
	return {
		"last": last,
		"age_hours": age_hours,
		"in_range": cint(in_range),
		"interval": interval,
		"enabled": enabled,
		"on_schedule": age_hours is not None and age_hours <= 2 * interval,
	}


def _age_text(hours: float) -> tuple[float, str]:
	if hours < 1:
		return round(hours * 60), "min"
	if hours < 48:
		return round(hours), "h"
	return round(hours / 24), "d"


def _bench(f: dict) -> dict:
	rows = frappe.db.sql(
		"""SELECT module_name, has_uncommitted_changes AS dirty, commits_behind AS behind,
		          commits_ahead AS ahead, last_checked_at FROM `tabModule Version Check`""",
		as_dict=True,
	)
	out = {"apps": len(rows), "clean": 0, "stale": 0, "dirty": 0, "ahead": 0, "last_checked": None}
	for r in rows:
		if r.dirty:
			out["dirty"] += 1
		elif cint(r.behind) > 0:
			out["stale"] += 1
		elif cint(r.ahead) > 0:
			out["ahead"] += 1
		else:
			out["clean"] += 1
		if r.last_checked_at and (not out["last_checked"] or r.last_checked_at > out["last_checked"]):
			out["last_checked"] = r.last_checked_at
	return out


def _activity(f: dict) -> dict:
	rows = _sql(
		"""SELECT status, COUNT(*) AS n FROM `tabDeveloper Activity Log`
		   WHERE activity_time >= %(start_dt)s AND activity_time < %(end_dt)s GROUP BY 1""",
		f,
	)
	by = {(r.status or ""): cint(r.n) for r in rows}
	return {"total": sum(by.values()), "errors": by.get("Error", 0), "warnings": by.get("Warning", 0)}


# ------------------------------------------------------------------------------- chart


def _bucket_of(day, mode: str):
	if mode == "week":
		return day - timedelta(days=day.weekday())
	if mode == "month":
		return day.replace(day=1)
	return day


def _mode_for(f: dict) -> str:
	days = (f["end"] - f["start"]).days + 1
	return "day" if days <= 45 else "week" if days <= 200 else "month"


def _closed_dates(f: dict) -> dict[str, object]:
	"""name -> the day the request reached a closed state, for requests (matching the area and
	priority filters) that are closed NOW and closed on or before the end of the range.
	Date = the latest recorded workflow_state change into a closed state (Version log);
	when no change was logged, the request's last-modified day."""
	rows = _sql(
		"""SELECT name, modified FROM `tabRequest`
		   WHERE docstatus < 2 AND workflow_state IN ('Completed', 'Rejected', 'Withdrawn', 'Closed')
		   AND modified >= %(start_dt)s AND creation < %(end_dt)s"""
		+ _area_sql(f, "product_area")
		+ _prio_sql(f),
		f,
	)
	if not rows:
		return {}
	closed = {r.name: getdate(r.modified) for r in rows}
	names = list(closed)
	for i in range(0, len(names), 500):
		chunk = names[i : i + 500]
		versions = frappe.db.sql(
			"""SELECT docname, creation, data FROM `tabVersion`
			   WHERE ref_doctype = 'Request' AND docname IN %(names)s AND data LIKE '%%workflow_state%%'
			   ORDER BY creation ASC""",
			{"names": chunk},
			as_dict=True,
		)
		for v in versions:
			try:
				changed = (json.loads(v.data or "{}") or {}).get("changed") or []
			except ValueError:
				continue
			for ch in changed:
				if len(ch) >= 3 and ch[0] == "workflow_state" and ch[2] in CLOSED_REQUEST_STATES:
					closed[v.docname] = getdate(v.creation)  # ascending: the latest wins
	return {n: d for n, d in closed.items() if f["start"] <= d <= f["end"]}


def _chart(f: dict) -> dict:
	mode = _mode_for(f)
	buckets: list = []
	cur = _bucket_of(f["start"], mode)
	while cur <= f["end"]:
		buckets.append(cur)
		if mode == "day":
			cur = cur + timedelta(days=1)
		elif mode == "week":
			cur = cur + timedelta(days=7)
		else:
			cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
	opened = dict.fromkeys(buckets, 0)
	closed = dict.fromkeys(buckets, 0)
	rows = _sql(
		"""SELECT DATE(creation) AS d, COUNT(*) AS n FROM `tabRequest`
		   WHERE docstatus < 2 AND creation >= %(start_dt)s AND creation < %(end_dt)s"""
		+ _area_sql(f, "product_area")
		+ _prio_sql(f)
		+ " GROUP BY 1",
		f,
	)
	for r in rows:
		opened[_bucket_of(getdate(r.d), mode)] += cint(r.n)
	for day in _closed_dates(f).values():
		closed[_bucket_of(day, mode)] += 1
	return {
		"granularity": mode,
		"labels": [str(b) for b in buckets],
		"opened": [opened[b] for b in buckets],
		"closed": [closed[b] for b in buckets],
		"opened_total": sum(opened.values()),
		"closed_total": sum(closed.values()),
	}


def _page_label(route: str) -> tuple[str, str]:
	"""(label, href) for a current portal `route`: its v2 page when one exists (first NAV entry
	wins when two share a route), else the current page. Label: NAV, else the Dev Portal Page title."""
	for _g, items in dev_v2.NAV:
		for key, label, href, nav_route, _i in items:
			if nav_route == route and key != "dev-tools":
				return label, href
	title = frappe.db.get_value("Dev Portal Page", route, "title") or route.replace("-", " ").title()
	return title, "/" + route


def _landing(roles: set[str]) -> dict:
	"""Where /dev-tools would send this person (portal.resolve_home_route), as v2 shortcuts.
	`home` follows the role rule (Dev Team, then Projects Manager, then Requests); `last` is the
	page the browser was last on, when it is still a page the person may open."""
	home_route = next(
		(r for role, r in portal.HOME_ROUTE_BY_ROLE if role in roles and _can_open(r, roles)),
		portal.DEFAULT_AUTHENTICATED_ROUTE if _can_open(portal.DEFAULT_AUTHENTICATED_ROUTE, roles) else None,
	)
	out = {"home": None, "last": None}
	if home_route:
		label, href = _page_label(home_route.lstrip("/"))
		out["home"] = {"label": label, "href": href}
	last = portal._last_page(roles)
	if last and last != "/dev-tools" and (not home_route or last != home_route):
		label, href = _page_label(last.lstrip("/"))
		out["last"] = {"label": label, "href": href}
	return out


def _quick_actions(roles: set[str]) -> list[dict]:
	"""Things most people come here to do, shown first. Raising a request is open to everyone
	who may open the Requests page (it is where the raise form lives)."""
	out = []
	if _can_open("requests-portal", roles):
		out.append({"label": "Raise a request", "href": "/requests-v2", "icon": "user-plus"})
	return out


def _nav_groups(roles: set[str]) -> list[dict]:
	"""v2 page tiles by sidebar group (the sidebar's rule), plus pages that have no v2 yet.
	Each tile carries `beta` (false when the tile links to the existing page because there is
	no v2 yet)."""
	groups = []
	for group, items in dev_v2.NAV:
		pages = [
			{
				"key": key,
				"label": label,
				"href": href,
				"icon": icon,
				"blurb": PAGE_BLURBS.get(key, ""),
				"beta": True,
			}
			for key, label, href, route, icon in items
			if key != "dev-tools" and _can_open(route, roles)
		]
		if group == "Developer":
			pages += [
				{
					"key": key,
					"label": label,
					"href": "/" + route,
					"icon": icon,
					"blurb": PAGE_BLURBS.get(key, ""),
					"beta": False,
				}
				for key, label, route, icon in PAGES_WITHOUT_V2
				if _can_open(route, roles)
			]
		if pages:
			groups.append({"group": group, "pages": pages})
	return groups


def _desk_groups() -> list[dict]:
	"""Desk list tiles the signed-in user may read (Frappe's own doctype permission)."""
	groups = []
	for group, items in DESK_GROUPS:
		pages = [
			{
				"key": doctype,
				"label": label,
				"href": _desk_url(doctype),
				"icon": icon,
				"blurb": blurb,
			}
			for doctype, label, blurb, icon in items
			if frappe.db.exists("DocType", doctype) and frappe.has_permission(doctype, "read")
		]
		if pages:
			groups.append({"group": group, "pages": pages})
	return groups


def _desk_url(doctype: str) -> str:
	return "/app/" + doctype.lower().replace(" ", "-")


# ----------------------------------------------------------------------------- endpoint


@frappe.whitelist()
def get_overview(from_date=None, to_date=None, product_area=None, priority=None):
	"""Headline cards, the 'needs attention' list, the opened-vs-closed series and the
	navigation tiles this user may open, for the given filters."""
	try:
		roles = _roles()
		f = _filters(from_date, to_date, product_area, priority)
	except frappe.ValidationError as e:
		return {"success": False, "error": str(e)}

	area_note = "not split by product area or priority"
	kpis: list[dict] = []
	attention: list[dict] = []
	requests_href = _route_for(roles, "requests")

	# --- requests (public)
	states = _request_states(f)
	opened_total = sum(states.values())
	closed_of_opened = sum(n for s, n in states.items() if s in CLOSED_REQUEST_STATES)
	open_n = opened_total - closed_of_opened
	kpis.append(
		{
			"key": "open_requests",
			"label": "Open requests",
			"value": open_n,
			"unit": f"of {opened_total} opened in this range",
			"route": requests_href,
			"title": "Requests created in the range that are not yet Completed, Rejected, Withdrawn or Closed.",
		}
	)

	# --- awaiting review
	review_n = None
	if _allowed("review", roles):
		review_n = states.get("Under Review", 0)
		kpis.append(
			{
				"key": "awaiting_review",
				"label": "Awaiting review",
				"value": review_n,
				"unit": "requests under review",
				"route": _route_for(roles, "review-queue", "requests"),
				"title": "Requests created in the range that are in the Under Review state (the Review Queue).",
			}
		)
		stale = _sql(
			"""SELECT name, title, DATEDIFF(%(today)s, DATE(creation)) AS days FROM `tabRequest`
			   WHERE docstatus < 2 AND workflow_state = 'Under Review'
			   AND creation >= %(start_dt)s AND creation < %(end_dt)s
			   AND DATEDIFF(%(today)s, DATE(creation)) > """
			+ str(STALE_REVIEW_DAYS)
			+ _area_sql(f, "product_area")
			+ _prio_sql(f)
			+ " ORDER BY creation ASC",
			f,
		)
		if stale:
			attention.append(
				{
					"key": "slow_review",
					"text": f"{len(stale)} request{'s' if len(stale) != 1 else ''} waiting more than "
					f"{STALE_REVIEW_DAYS} days for a decision",
					"detail": f"Longest wait: {stale[0].title or stale[0].name}, {stale[0].days} days",
					"route": _route_for(roles, "review-queue", "requests"),
					"kpi": "awaiting_review",
				}
			)

	# --- overdue + blocked (public, Dev Tools projects)
	overdue = _overdue_count(f)
	kpis.append(
		{
			"key": "overdue_work",
			"label": "Overdue work",
			"value": overdue,
			"unit": "tasks and issues past their due date",
			"route": _route_for(roles, "backlog-board"),
			"title": "Open tasks and issues in Dev Tools projects whose due date is before today and "
			"falls inside the range (the board's late flag).",
		}
	)
	blocked = _blocked_count(f)
	kpis.append(
		{
			"key": "blocked_work",
			"label": "Blocked work",
			"value": blocked,
			"unit": "deferred requests and issues on hold",
			"route": _route_for(roles, "backlog-board"),
			"title": "Deferred requests and On Hold issues in Dev Tools projects, created in the range "
			"(the board's Blocked column).",
		}
	)
	if overdue:
		task_q, _issue = _overdue_sql(f)
		worst = _sql(
			"SELECT subject, exp_end_date AS due, DATEDIFF(%(today)s, exp_end_date) AS days "
			+ task_q
			+ " ORDER BY exp_end_date ASC LIMIT 1",
			f,
		)
		attention.append(
			{
				"key": "overdue",
				"text": f"{overdue} item{'s are' if overdue != 1 else ' is'} past the due date",
				"detail": f"Longest overdue: {worst[0].subject}, {worst[0].days} days" if worst else "",
				"route": _route_for(roles, "backlog-board"),
				"kpi": "overdue_work",
			}
		)
	if blocked:
		attention.append(
			{
				"key": "blocked",
				"text": f"{blocked} item{'s are' if blocked != 1 else ' is'} blocked",
				"detail": "Deferred requests and issues on hold",
				"route": _route_for(roles, "backlog-board"),
				"kpi": "blocked_work",
			}
		)

	# --- deployments
	if _allowed("deploy", roles):
		dep = _deploy_states(f)
		flight = dep.get("Requested", 0) + dep.get("In Progress", 0)
		kpis.append(
			{
				"key": "deployments",
				"label": "Deployments in flight",
				"value": flight,
				"unit": f"{dep.get('In Progress', 0)} running, {dep.get('Requested', 0)} requested",
				"note": area_note,
				"route": _route_for(roles, "deployments"),
				"title": "Deployment requests created in the range that are Requested or In Progress. "
				"Deployments are not split by product area or priority.",
			}
		)
		if dep.get("Failed"):
			attention.append(
				{
					"key": "dep_failed",
					"text": f"{dep['Failed']} deployment{'s' if dep['Failed'] != 1 else ''} failed",
					"detail": "Needs a retry or a fix",
					"route": _route_for(roles, "deployments"),
					"kpi": "deployments",
				}
			)
		if _allowed("approve", roles):
			pend = _pending_approvals(f)
			if pend:
				attention.append(
					{
						"key": "dep_approval",
						"text": f"{pend} deployment{'s' if pend != 1 else ''} waiting for approval",
						"detail": "Raised during peak hours",
						"route": _route_for(roles, "deployments"),
						"kpi": "deployments",
					}
				)

	# --- developer-team only
	if _allowed("dev", roles):
		b = _backup(f)
		if b["age_hours"] is None:
			unit = "no snapshot yet" if not b["last"] else ""
			value, suffix = None, ""
		else:
			value, suffix = _age_text(b["age_hours"])
			unit = f"since {_fmt_dt(b['last'])}"
		kpis.append(
			{
				"key": "backup",
				"label": "Last code backup",
				"value": value,
				"suffix": (suffix + " ago") if suffix else "",
				"unit": unit,
				"tone": "good" if b["on_schedule"] else "warn",
				"note": area_note,
				"detail": f"{b['in_range']} snapshots in range, scheduled every {b['interval']} h"
				+ ("" if b["enabled"] else " (scheduled backups are switched off)"),
				"route": _route_for(roles, "code-snapshots"),
				"title": "Age of the newest code snapshot at the end of the range. Green when it is within "
				f"twice the backup interval ({b['interval']} h). Not split by product area or priority.",
			}
		)
		if not b["on_schedule"]:
			attention.append(
				{
					"key": "backup",
					"text": "Code backups are behind schedule"
					if b["last"]
					else "No code backup has been taken yet",
					"detail": f"Last snapshot {_fmt_dt(b['last'])}" if b["last"] else "",
					"route": _route_for(roles, "code-snapshots"),
					"kpi": "backup",
				}
			)
		bench = _bench(f)
		kpis.append(
			{
				"key": "bench",
				"label": "Apps up to date",
				"value": bench["clean"],
				"suffix": f"of {bench['apps']}",
				"unit": f"{bench['dirty']} with local changes, {bench['stale']} behind",
				"tone": "good" if bench["apps"] and bench["clean"] == bench["apps"] else "warn",
				"note": "current state, not filtered",
				"route": _route_for(roles, "version-check", "dev-dashboard"),
				"title": "Installed apps with no local changes and nothing to pull, from the last version "
				"check. It is the current state, so no filter applies.",
			}
		)
		if bench["dirty"] or bench["stale"]:
			attention.append(
				{
					"key": "bench",
					"text": f"{bench['dirty'] + bench['stale']} of {bench['apps']} apps need attention",
					"detail": f"{bench['dirty']} with uncommitted changes, {bench['stale']} behind upstream",
					"route": _route_for(roles, "version-check", "dev-dashboard"),
					"kpi": "bench",
				}
			)
		act = _activity(f)
		kpis.append(
			{
				"key": "activity",
				"label": "Developer activity",
				"value": act["total"],
				"unit": f"{act['errors']} errors, {act['warnings']} warnings",
				"note": area_note,
				"route": _route_for(roles, "activity-log"),
				"title": "Developer Activity Log entries in the range. Not split by product area or priority.",
			}
		)
		if act["errors"]:
			attention.append(
				{
					"key": "errors",
					"text": f"{act['errors']} error{'s' if act['errors'] != 1 else ''} in the activity log",
					"detail": "Logged by the background jobs in this range",
					"route": _route_for(roles, "activity-log"),
					"kpi": "activity",
				}
			)

	return {
		"success": True,
		"filters": {
			"from_date": str(f["start"]),
			"to_date": str(f["end"]),
			"product_area": f["area"] or "",
			"priority": f["priority"] or "",
		},
		"kpis": kpis,
		"attention": [a for a in attention if a.get("route")][:8],
		"requests": {
			"opened": opened_total,
			"open": open_n,
			"closed_of_opened": closed_of_opened,
			"by_state": states,
		},
		"chart": _chart(f),
		"nav": _nav_groups(roles),
		"desk": _desk_groups(),
		"landing": _landing(roles),
		"quick": _quick_actions(roles),
		"options": {
			"product_areas": frappe.get_all("Product Area", pluck="name", order_by="name asc"),
			"priorities": frappe.get_all(
				"Priority Level", filters={"disabled": 0}, pluck="name", order_by="sort_order asc"
			),
		},
	}


# ---------------------------------------------------------------------------- drill-down

DRILL_KPIS = {
	"open_requests": "public",
	"awaiting_review": "review",
	"overdue_work": "public",
	"blocked_work": "public",
	"deployments": "deploy",
	"backup": "dev",
	"bench": "dev",
	"activity": "dev",
}


@frappe.whitelist()
def get_overview_items(kpi, from_date=None, to_date=None, product_area=None, priority=None):
	"""The records behind one card, newest or most urgent first, same filters and same
	permission as the card. Totals cover the full set; rows are capped at ROW_LIMIT."""
	try:
		roles = _roles()
		f = _filters(from_date, to_date, product_area, priority)
	except frappe.ValidationError as e:
		return {"success": False, "error": str(e)}
	if kpi not in DRILL_KPIS:
		return {"success": False, "error": "Unknown figure."}
	if not _allowed(DRILL_KPIS[kpi], roles):
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	rows: list[dict] = []
	total = 0
	lim = f" LIMIT {ROW_LIMIT}"
	if kpi in ("open_requests", "awaiting_review"):
		state_sql = (
			" AND workflow_state = 'Under Review'"
			if kpi == "awaiting_review"
			else " AND COALESCE(workflow_state, '') NOT IN ('Completed', 'Rejected', 'Withdrawn', 'Closed')"
		)
		base = (
			"""FROM `tabRequest` WHERE docstatus < 2 AND creation >= %(start_dt)s AND creation < %(end_dt)s"""
			+ state_sql
			+ _area_sql(f, "product_area")
			+ _prio_sql(f)
		)
		total = cint(_sql("SELECT COUNT(*) AS n " + base, f)[0].n)
		for r in _sql(
			"SELECT name, title, workflow_state, priority, product_area, creation "
			+ base
			+ " ORDER BY creation ASC"
			+ lim,
			f,
		):
			rows.append(
				{
					"name": r.name,
					"title": r.title,
					"status": r.workflow_state or "Under Review",
					"priority": r.priority or "",
					"detail": r.product_area or "",
					"date": _fmt_d(r.creation),
					"url": _doc_url("Request", r.name),
				}
			)
	elif kpi == "overdue_work":
		task_q, issue_q = _overdue_sql(f)
		total = _overdue_count(f)
		items = []
		for r in _sql(
			"SELECT name, subject, status, priority, custom_module AS area, exp_end_date AS due " + task_q, f
		):
			items.append(("Task", r))
		for r in _sql(
			"SELECT name, subject, status, priority, custom_module AS area, DATE(sla_resolution_by) AS due "
			+ issue_q,
			f,
		):
			items.append(("Issue", r))
		items.sort(key=lambda x: str(x[1].due))
		for dt, r in items[:ROW_LIMIT]:
			rows.append(
				{
					"name": r.name,
					"title": r.subject,
					"status": r.status,
					"priority": r.priority or "",
					"detail": f"{dt}{' · ' + r.area if r.area else ''} · {(f['today'] - getdate(r.due)).days} days late",
					"date": _fmt_d(r.due),
					"url": _doc_url(dt, r.name),
				}
			)
	elif kpi == "blocked_work":
		req_q, issue_q = _blocked_parts(f)
		total = _blocked_count(f)
		items = [
			("Request", r)
			for r in _sql(
				"SELECT name, title, workflow_state AS status, priority, product_area AS area, creation "
				+ req_q,
				f,
			)
		] + [
			("Issue", r)
			for r in _sql(
				"SELECT name, subject AS title, status, priority, custom_module AS area, creation " + issue_q,
				f,
			)
		]
		items.sort(key=lambda x: str(x[1].creation))
		for dt, r in items[:ROW_LIMIT]:
			rows.append(
				{
					"name": r.name,
					"title": r.title,
					"status": r.status,
					"priority": r.priority or "",
					"detail": f"{dt}{' · ' + r.area if r.area else ''}",
					"date": _fmt_d(r.creation),
					"url": _doc_url(dt, r.name),
				}
			)
	elif kpi == "deployments":
		base = """FROM `tabDeployment Request` WHERE docstatus < 2
		   AND workflow_state IN ('Requested', 'In Progress')
		   AND creation >= %(start_dt)s AND creation < %(end_dt)s"""
		total = cint(_sql("SELECT COUNT(*) AS n " + base, f)[0].n)
		for r in _sql(
			"SELECT name, app, instance, branch, workflow_state, creation "
			+ base
			+ " ORDER BY creation ASC"
			+ lim,
			f,
		):
			rows.append(
				{
					"name": r.name,
					"title": f"{r.app} to {r.instance}",
					"status": r.workflow_state,
					"priority": "",
					"detail": r.branch or "",
					"date": _fmt_d(r.creation),
					"url": _doc_url("Deployment Request", r.name),
				}
			)
	elif kpi == "backup":
		base = "FROM `tabCode Backup Snapshot` WHERE snapshot_time >= %(start_dt)s AND snapshot_time < %(end_dt)s"
		total = cint(_sql("SELECT COUNT(*) AS n " + base, f)[0].n)
		for r in _sql(
			"SELECT name, source_type, document_name, app, module, snapshot_time "
			+ base
			+ " ORDER BY snapshot_time DESC"
			+ lim,
			f,
		):
			rows.append(
				{
					"name": r.name,
					"title": r.document_name or r.name,
					"status": r.source_type,
					"priority": "",
					"detail": r.app or r.module or "",
					"date": _fmt_dt(r.snapshot_time),
					"url": _doc_url("Code Backup Snapshot", r.name),
				}
			)
	elif kpi == "bench":
		res = frappe.db.sql(
			"""SELECT module_name, has_uncommitted_changes AS dirty, commits_behind AS behind,
			   commits_ahead AS ahead, current_branch, last_checked_at FROM `tabModule Version Check`
			   ORDER BY module_name ASC""",
			as_dict=True,
		)
		total = len(res)
		order = {"Dirty": 0, "Stale": 1, "Ahead": 2, "Clean": 3}
		items = []
		for r in res:
			status = (
				"Dirty"
				if r.dirty
				else "Stale"
				if cint(r.behind) > 0
				else "Ahead"
				if cint(r.ahead) > 0
				else "Clean"
			)
			items.append((order[status], status, r))
		items.sort(key=lambda x: (x[0], x[2].module_name))
		for _o, status, r in items[:ROW_LIMIT]:
			bits = [r.current_branch or ""]
			if cint(r.behind):
				bits.append(f"{cint(r.behind)} behind")
			if cint(r.ahead):
				bits.append(f"{cint(r.ahead)} ahead")
			rows.append(
				{
					"name": r.module_name,
					"title": r.module_name,
					"status": status,
					"priority": "",
					"detail": " · ".join(b for b in bits if b),
					"date": _fmt_dt(r.last_checked_at),
					"url": _doc_url("Module Version Check", r.module_name),
				}
			)
	elif kpi == "activity":
		base = "FROM `tabDeveloper Activity Log` WHERE activity_time >= %(start_dt)s AND activity_time < %(end_dt)s"
		total = cint(_sql("SELECT COUNT(*) AS n " + base, f)[0].n)
		for r in _sql(
			"SELECT name, title, status, activity_type, activity_time "
			+ base
			+ " ORDER BY (status = 'Error') DESC, activity_time DESC"
			+ lim,
			f,
		):
			rows.append(
				{
					"name": r.name,
					"title": r.title,
					"status": r.status,
					"priority": "",
					"detail": r.activity_type or "",
					"date": _fmt_dt(r.activity_time),
					"url": _doc_url("Developer Activity Log", r.name),
				}
			)

	return {
		"success": True,
		"kpi": kpi,
		"rows": rows,
		"total": total,
		"row_limit": ROW_LIMIT,
		"truncated": total > len(rows),
	}
