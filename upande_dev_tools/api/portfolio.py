"""Everything a projects manager needs to answer "how are we doing" in one read.

Every figure here is measured, not estimated. Where a measure depends on data the
team has to record - a completion date, a due date - the count of items it could
actually be computed from is returned alongside it, so a number is never quoted
with more confidence than the data behind it deserves.
"""

import json
import random
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import add_days, get_datetime, getdate, today

from upande_dev_tools.setup import DEV_TOOLS_PROJECT_TYPE

MANAGER_ROLES = {"Projects Manager", "System Manager"}
# An unset Date column is stored as 0000-00-00, which is "<" any real date, so a
# task that never had a due date counts as overdue unless it is excluded first.
HAS_DUE = ["is", "set"]
OPEN_TASK = ["not in", ["Completed", "Cancelled"]]
OPEN_ISSUE = ["not in", ["Resolved", "Closed"]]
DECIDING = ["in", ["", "Under Review"]]
BUCKETS = 8


@frappe.whitelist()
def get_portfolio(days: int = 30, scope: str | None = None) -> dict:
	if not set(frappe.get_roles()) & MANAGER_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	days = max(7, min(int(days), 180))
	end = getdate(today())
	start = add_days(end, -days)
	prev_start = add_days(start, -days)

	projects = _projects(scope)
	# A portfolio measures work that belongs to a Dev Tools-flagged project. Tasks imported
	# without any project at all - on this bench, an agronomy backlog of over a thousand rows -
	# are excluded and said so; tasks that DO have a project, but one not flagged for Dev Tools
	# tracking, are equally excluded by _projects()'s own baseline filter.
	scoped = {"project": ["in", projects]}
	loose = frappe.db.count("Task", {"project": ["is", "not set"]})

	now = _window(scoped, start, end)
	before = _window(scoped, prev_start, start)

	open_total = frappe.db.count("Task", {**scoped, "status": OPEN_TASK})
	# Little's law, stated plainly: at the rate of the period just measured, how
	# long until the open pile is gone. Only meaningful if anything shipped.
	rate = now["delivered"] / days if now["delivered"] else 0
	forecast = round(open_total / rate) if rate else None

	period = {
		"days": days,
		"from": str(start),
		"to": str(end),
		"excluded": loose,
		"open": open_total,
		"clears_in": forecast,
		"clears_on": str(add_days(end, forecast)) if forecast and forecast < 3650 else None,
	}
	kpis = _kpis(now, before, scoped, end)
	people = _people(scoped, end)

	return {
		"period": period,
		"kpis": kpis,
		"flow": _flow(scoped, end),
		"wins": _wins(scoped, start),
		"risks": _risks(scoped, end, people),
		"people": people,
		"modules": _modules(scoped, start, end),
		"ageing": _ageing(scoped, end),
		"projects": _projects_roll(projects, end),
		"requests": _requests(scoped, end),
		"stalled": _stalled(scoped, end),
		"due_soon": _due_soon(scoped, end),
		"forecast": _forecast(scoped, open_total, end),
		"needs_you": _needs_you(scoped, end),
		"data_trust": _data_trust(scoped),
		"plan_vs_reality": _plan_vs_reality(scoped, start, end),
		"pipeline": _pipeline(start, end),
		"releases": _releases(),
	}


def _projects(scope: str | None) -> list[str]:
	"""Every project this portfolio measures always starts from the Dev Tools-flagged set -
	otherwise every project in the whole ERP (this bench has 27, most not software work)
	would be aggregated together, distorting every count. `scope` (Internal/External) only
	narrows further within that set; it never widens back out to everything."""
	filters: dict = {"project_type": DEV_TOOLS_PROJECT_TYPE}
	if scope:
		if scope not in ("Internal", "External"):
			frappe.throw(_("scope must be Internal or External."), frappe.ValidationError)
		filters["custom_project_scope"] = scope
	return frappe.get_all("Project", filters=filters, pluck="name", ignore_permissions=True) or [""]


def _window(scoped: dict, start, end) -> dict:
	"""What was delivered and what arrived between two dates."""
	done = frappe.get_all(
		"Task",
		filters={**scoped, "status": "Completed", "completed_on": ["between", [start, end]]},
		fields=[
			"name", "subject", "creation", "completed_on", "exp_end_date", "custom_module",
			"custom_request", "_assign",
		],
		ignore_permissions=True,
	)
	raised = frappe.db.count("Task", {**scoped, "creation": ["between", [start, end]]})

	ages, on_time, datable = [], 0, 0
	for task in done:
		ages.append((getdate(task.completed_on) - getdate(task.creation)).days)
		if task.exp_end_date:
			datable += 1
			if getdate(task.completed_on) <= getdate(task.exp_end_date):
				on_time += 1

	return {
		"done": done,
		"delivered": len(done),
		"raised": raised,
		"cycle": _median(ages),
		"cycle_p85": _percentile(ages, 85),
		"on_time": round(on_time / datable * 100) if datable else None,
		"datable": datable,
	}


def _request_lead_time(done_tasks: list[dict]) -> tuple[int | None, int]:
	"""Idea to done, not just raised-as-a-task to done: the median time from a Request's own
	creation to its linked Task actually finishing, for whichever completed tasks in the
	period trace back to a Request. Tasks created directly on the board (no custom_request)
	don't have an "idea" moment to measure from and are left out, not counted as zero."""
	linked = [t for t in done_tasks if t.get("custom_request")]
	if not linked:
		return None, 0
	requests = frappe.get_all(
		"Request",
		filters={"name": ["in", [t["custom_request"] for t in linked]]},
		fields=["name", "creation"],
		ignore_permissions=True,
	)
	created_by = {r.name: r.creation for r in requests}
	leads = []
	for task in linked:
		raised_on = created_by.get(task["custom_request"])
		if raised_on:
			leads.append((getdate(task["completed_on"]) - getdate(raised_on)).days)
	return _median(leads), len(leads)


def _kpis(now: dict, before: dict, scoped: dict, end) -> list[dict]:
	waiting = frappe.get_all(
		"Request",
		filters={**scoped, "workflow_state": DECIDING},
		fields=["creation"],
		ignore_permissions=True,
	)
	wait_ages = [(getdate(end) - getdate(r.creation)).days for r in waiting]

	overdue = frappe.db.count("Task", _overdue_filters(scoped, end))
	blocked = frappe.db.count("Issue", {**scoped, "status": "On Hold"})

	net = now["raised"] - now["delivered"]
	net_before = before["raised"] - before["delivered"]

	req_lead, req_lead_n = _request_lead_time(now["done"])
	req_lead_before, _ = _request_lead_time(before["done"])

	return [
		_kpi(
			"delivered",
			"Delivered",
			now["delivered"],
			before["delivered"],
			"up",
			note=f"Tasks completed in the period, against {before['delivered']} in the one before.",
		),
		_kpi(
			"cycle",
			"Task lead time",
			now["cycle"],
			before["cycle"],
			"down",
			unit="d",
			note=f"Median days from a task being raised to being finished; the slowest 15% took "
			f"{now['cycle_p85']}d or more."
			if now["cycle_p85"] is not None
			else "Median days from a task being raised to being finished.",
		),
		_kpi(
			"request_lead",
			"Request lead time",
			req_lead,
			req_lead_before,
			"down",
			unit="d",
			note=f"Median days from a Request being raised to its linked task finishing, over "
			f"{req_lead_n} completed task{'s' if req_lead_n != 1 else ''} that trace back to one. "
			"Tasks added straight to the board (no linked Request) aren't counted here."
			if req_lead_n
			else "No completed task in this period traces back to a Request yet.",
		),
		_kpi(
			"on_time",
			"Finished on time",
			now["on_time"],
			before["on_time"],
			"up",
			unit="%",
			note=f"Of the {now['datable']} completed tasks that carried a due date.",
		),
		_kpi(
			"net",
			"Backlog change",
			net,
			net_before,
			"down",
			signed=True,
			note=f"{now['raised']} raised against {now['delivered']} delivered. Below zero is shrinking.",
		),
		_kpi(
			"waiting",
			"Waiting on you",
			len(waiting),
			None,
			"down",
			note=f"Requests with no decision yet. Longest has waited {max(wait_ages or [0])} days.",
		),
		_kpi(
			"risk",
			"At risk now",
			overdue + blocked,
			None,
			"down",
			note=f"{overdue} past due and {blocked} on hold.",
		),
	]


def _overdue_filters(scoped: dict, end) -> list:
	filters = [
		["Task", key, *(value if isinstance(value, list) else ["=", value])] for key, value in scoped.items()
	]
	return [
		*filters,
		["Task", "status", "not in", ["Completed", "Cancelled"]],
		["Task", "exp_end_date", "is", "set"],
		["Task", "exp_end_date", "<", end],
	]


def _kpi(key, label, value, was, better, unit="", signed=False, note="") -> dict:
	delta = None if was is None or value is None else value - was
	direction = "flat"
	if delta:
		rising = delta > 0
		direction = "good" if (rising and better == "up") or (not rising and better == "down") else "bad"
	return {
		"key": key,
		"label": label,
		"value": value,
		"unit": unit,
		"was": was,
		"delta": delta,
		"direction": direction,
		"signed": signed,
		"note": note,
	}


def _flow(scoped: dict, end) -> list[dict]:
	"""Raised against delivered, week by week - whether the team is keeping up."""
	weeks = []
	for index in range(BUCKETS - 1, -1, -1):
		to = add_days(end, -7 * index)
		since = add_days(to, -7)
		weeks.append(
			{
				"label": str(to)[5:],
				"raised": frappe.db.count("Task", {**scoped, "creation": ["between", [since, to]]}),
				"delivered": frappe.db.count(
					"Task", {**scoped, "status": "Completed", "completed_on": ["between", [since, to]]}
				),
			}
		)
	return weeks


def _wins(scoped: dict, start) -> list[dict]:
	rows = frappe.get_all(
		"Task",
		filters={**scoped, "status": "Completed", "completed_on": [">=", start]},
		fields=["name", "subject", "completed_on", "custom_module", "project", "_assign"],
		order_by="completed_on desc",
		limit=12,
		ignore_permissions=True,
	)
	names = _names({who for row in rows for who in _assignees(row)})
	for row in rows:
		row["by"] = [names.get(w, w) for w in _assignees(row)]
		row["completed_on"] = str(row["completed_on"])[:10]
		row.pop("_assign", None)
	return rows


RISK_KIND_WEIGHT = {"Past due": 1.0, "On hold": 0.6, "Awaiting you": 0.35}
PRIORITY_WEIGHT = {"Urgent": 4, "High": 3, "Medium": 2, "Low": 1}


def _risks(scoped: dict, end, people: list[dict] | None = None) -> list[dict]:
	"""Ranked by a real, stated score - age in days times a priority weight (Task.priority;
	Issues and Requests carry no priority signal here, so they're weighted flat and lower,
	reflecting that they aren't yet confirmed, scheduled work) - times a 1.25x bump when the
	only assignee is already flagged over_capacity elsewhere on this page. No weight is applied
	for "blocks N other tasks" or "has a deployment pending" - neither is reliably derivable
	from real data yet (Task has no blocked-by field; Deployment Request's link back to a
	Request is essentially never populated in practice), so the mockup's fuller formula is not
	replicated wholesale."""
	overloaded = {p["user"] for p in (people or []) if p.get("over_capacity")}
	out = []
	for task in frappe.get_all(
		"Task",
		filters=_overdue_filters(scoped, end),
		fields=["name", "subject", "exp_end_date", "priority", "_assign"],
		order_by="exp_end_date asc",
		limit=20,
		ignore_permissions=True,
	):
		days = (getdate(end) - getdate(task.exp_end_date)).days
		who = _assignees(task)
		out.append(
			{
				"kind": "Past due",
				"doctype": "Task",
				"name": task.name,
				"title": task.subject,
				"days": days,
				"who": who,
				"priority": task.priority,
				"score": _risk_score(days, task.priority, "Past due", who, overloaded),
			}
		)

	for issue in frappe.get_all(
		"Issue",
		filters={**scoped, "status": "On Hold"},
		fields=["name", "subject", "opening_date", "_assign"],
		limit=10,
		ignore_permissions=True,
	):
		days = (getdate(end) - getdate(issue.opening_date)).days if issue.opening_date else 0
		who = _assignees(issue)
		out.append(
			{
				"kind": "On hold",
				"doctype": "Issue",
				"name": issue.name,
				"title": issue.subject,
				"days": days,
				"who": who,
				"priority": None,
				"score": _risk_score(days, None, "On hold", who, overloaded),
			}
		)

	for req in frappe.get_all(
		"Request",
		filters={**scoped, "workflow_state": DECIDING},
		fields=["name", "title", "creation"],
		limit=10,
		ignore_permissions=True,
	):
		days = (getdate(end) - getdate(req.creation)).days
		out.append(
			{
				"kind": "Awaiting you",
				"doctype": "Request",
				"name": req.name,
				"title": req.title,
				"days": days,
				"who": [],
				"priority": None,
				"score": _risk_score(days, None, "Awaiting you", [], overloaded),
			}
		)

	names = _names({w for row in out for w in row["who"]})
	for row in out:
		row["who"] = [names.get(w, w) for w in row["who"]]
	return sorted(out, key=lambda r: -r["score"])[:10]


def _risk_score(days: int, priority: str | None, kind: str, who: list[str], overloaded: set[str]) -> float:
	weight = PRIORITY_WEIGHT.get(priority, 2) if priority else 2
	score = days * weight * RISK_KIND_WEIGHT[kind]
	if any(w in overloaded for w in who):
		score *= 1.25
	return round(score, 1)


def _people(scoped: dict, end) -> list[dict]:
	buckets: dict[str, dict] = {}
	for task in frappe.get_all(
		"Task",
		filters={**scoped, "status": OPEN_TASK},
		fields=["name", "status", "exp_end_date", "_assign"],
		ignore_permissions=True,
	):
		for who in _assignees(task) or ["Unassigned"]:
			bucket = buckets.setdefault(
				who, {"user": who, "open": 0, "working": 0, "overdue": 0, "delivered": 0}
			)
			bucket["open"] += 1
			if task.status == "Working":
				bucket["working"] += 1
			if task.exp_end_date and getdate(task.exp_end_date) < getdate(end):
				bucket["overdue"] += 1

	for task in frappe.get_all(
		"Task",
		filters={**scoped, "status": "Completed", "completed_on": [">=", add_days(end, -30)]},
		fields=["name", "_assign"],
		ignore_permissions=True,
	):
		for who in _assignees(task) or ["Unassigned"]:
			buckets.setdefault(
				who, {"user": who, "open": 0, "working": 0, "overdue": 0, "delivered": 0}
			)["delivered"] += 1

	names = _names({w for w in buckets if w != "Unassigned"})
	for who, bucket in buckets.items():
		bucket["name"] = "Unassigned" if who == "Unassigned" else names.get(who, who)

	# "Over capacity" catches two different shapes of overload, both real: a queue
	# far bigger than everyone else's (Stephene: 98 open), or a queue where a large
	# share is already late even if the queue itself isn't huge (Brian: 16 of 29
	# late). A big but on-time queue is not the problem; either of these is.
	real = [b for who, b in buckets.items() if who != "Unassigned"]
	avg_open = (sum(b["open"] for b in real) / len(real)) if real else 0
	for bucket in real:
		volume_overload = bool(avg_open) and bucket["open"] > 2 * avg_open and bucket["overdue"] > 0
		late_share = bucket["overdue"] / bucket["open"] if bucket["open"] else 0
		lateness_overload = bucket["open"] >= 5 and late_share >= 0.3
		bucket["over_capacity"] = volume_overload or lateness_overload
		bucket["overload_reason"] = (
			"both" if volume_overload and lateness_overload else "volume" if volume_overload else "lateness" if lateness_overload else None
		)
		bucket["overdue_share"] = round(late_share * 100) if bucket["open"] else 0
		# "Idle" is real signal, not a guess: nothing open, and nothing delivered in the last
		# 30 days either - not simply "has the smallest queue right now."
		bucket["idle"] = bucket["open"] == 0 and bucket["delivered"] == 0
	if "Unassigned" in buckets:
		buckets["Unassigned"]["over_capacity"] = False
		buckets["Unassigned"]["overload_reason"] = None
		buckets["Unassigned"]["overdue_share"] = 0
		buckets["Unassigned"]["idle"] = False

	return sorted(buckets.values(), key=lambda b: (-b["open"], -b["delivered"]))


def _modules(scoped: dict, start, end) -> list[dict]:
	"""A dot per task, so the size of a module and its mix read at once rather
	than as a bar whose proportions have to be decoded. custom_module and Request's
	product_area share the same value space in this data (confirmed - not assumed),
	so a module's "bug share" can honestly be read off Request.request_type for
	requests raised against the matching product_area."""
	counts: dict[str, dict] = defaultdict(lambda: {"open": 0, "late": 0, "delivered": 0})
	owners: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
	for task in frappe.get_all(
		"Task",
		filters={**scoped, "status": OPEN_TASK},
		fields=["custom_module", "exp_end_date"],
		ignore_permissions=True,
	):
		bucket = counts[task.custom_module or "No module"]
		if task.exp_end_date and getdate(task.exp_end_date) < getdate(end):
			bucket["late"] += 1
		else:
			bucket["open"] += 1
	for task in frappe.get_all(
		"Task",
		filters={**scoped, "status": "Completed", "completed_on": [">=", start]},
		fields=["custom_module", "_assign"],
		ignore_permissions=True,
	):
		module = task.custom_module or "No module"
		counts[module]["delivered"] += 1
		for who in _assignees(task):
			owners[module][who] += 1

	bug_share = _bug_share_by_area()
	names_needed = {max(by.items(), key=lambda kv: kv[1])[0] for by in owners.values() if by}
	names = _names(names_needed)

	rows = []
	for key, value in counts.items():
		top_owner = None
		if owners[key]:
			who, n = max(owners[key].items(), key=lambda kv: kv[1])
			top_owner = {"user": who, "name": names.get(who, who), "share": round(n / sum(owners[key].values()) * 100)}
		rows.append({"module": key, **value, "total": sum(value.values()), "bug_share": bug_share.get(key), "top_owner": top_owner})
	return sorted(rows, key=lambda r: -r["total"])[:10]


def _bug_share_by_area(days: int = 90) -> dict[str, int | None]:
	"""% of requests raised against each product area, all-time-scope, that are Bugs rather
	than Feature/Chore/etc - not project-scoped like Task metrics, because a Request doesn't
	get a project until someone accepts it (see the data model note in the system reference),
	so scoping this by project would undercount exactly the freshest, least-triaged demand."""
	rows = frappe.get_all(
		"Request",
		filters={"product_area": ["is", "set"], "creation": [">=", add_days(getdate(today()), -days)]},
		fields=["product_area", "request_type"],
		ignore_permissions=True,
	)
	totals: dict[str, int] = defaultdict(int)
	bugs: dict[str, int] = defaultdict(int)
	for r in rows:
		totals[r.product_area] += 1
		if r.request_type == "Bug":
			bugs[r.product_area] += 1
	return {area: round(bugs[area] / total * 100) for area, total in totals.items() if total}


AGE_BANDS = [
	("Under a week", 7),
	("One to two weeks", 14),
	("Two to four weeks", 30),
	("One to two months", 60),
	("Two to six months", 180),
	("Over six months", None),
]


def _ageing(scoped: dict, end) -> list[dict]:
	"""How long open work has been open. A backlog that is merely large is one
	thing; a backlog that is old is another."""
	bands = [{"label": label, "count": 0} for label, _ceiling in AGE_BANDS]
	for task in frappe.get_all(
		"Task", filters={**scoped, "status": OPEN_TASK}, fields=["creation"], ignore_permissions=True
	):
		age = (getdate(end) - getdate(task.creation)).days
		for index, (_label, ceiling) in enumerate(AGE_BANDS):
			if ceiling is None or age < ceiling:
				bands[index]["count"] += 1
				break
	return bands


def _projects_roll(projects: list[str], end) -> list[dict]:
	filters = {"status": ["!=", "Cancelled"], "name": ["in", projects]}

	rows = frappe.get_all(
		"Project",
		filters=filters,
		fields=["name", "project_name", "custom_project_scope"],
		order_by="project_name asc",
		limit=10,
		ignore_permissions=True,
	)
	for row in rows:
		row["total"] = frappe.db.count("Task", {"project": row.name})
		row["done"] = frappe.db.count("Task", {"project": row.name, "status": "Completed"})
		row["overdue"] = frappe.db.count("Task", _overdue_filters({"project": row.name}, end))
		row["requests"] = frappe.db.count(
			"Request", {"project": row.name, "workflow_state": ["not in", ["Completed", "Rejected"]]}
		)
	return [row for row in rows if row["total"]]


def _requests(scoped: dict, end) -> dict:
	"""What happens to what people ask for. A team that rejects nothing is not
	triaging, and one that answers nothing is a black hole."""
	states = defaultdict(int)
	ages = []
	for req in frappe.get_all(
		"Request", filters=scoped, fields=["workflow_state", "creation"], ignore_permissions=True
	):
		state = req.workflow_state or "Under Review"
		states[state] += 1
		if state in ("", "Under Review"):
			ages.append((getdate(end) - getdate(req.creation)).days)

	accepted = states["Approved"] + states["Scheduled"] + states["In Progress"] + states["Completed"]
	return {
		"total": sum(states.values()),
		"accepted": accepted,
		"rejected": states["Rejected"],
		"deferred": states["Deferred"],
		"waiting": states["Under Review"],
		"oldest_wait": max(ages) if ages else 0,
	}


FORECAST_HISTORY_WEEKS = 12
FORECAST_TRIALS = 2000
FORECAST_MAX_WEEKS = 260  # a 5-year safety cap on the simulation, not a claim


def _forecast(scoped: dict, open_total: int, end) -> dict:
	"""A real, measured backlog-size history, plus a probabilistic completion range built by
	resampling actual weekly completion counts (Monte Carlo) rather than one average - the
	same technique agile/kanban tools call a throughput forecast.

	This replaces an earlier version of this forecast that projected forward using a due-date
	"hit rate" (completed that week / due that week). Two problems with that, found on
	review: the ratio could exceed 100%, because completions in a week and tasks due that
	same week are not the same population - a week can finish more than was ever due in it.
	And it only ever projected tasks that already had a near-term due date, so undated and
	already-overdue open tasks were silently left out of the forecast date entirely, however
	large a share of the real backlog they were.

	This version counts every currently open task, however it got there or however overdue it
	already is, and resamples from real weekly throughput rather than assuming next week looks
	like the historical average. If nothing has actually been completed in the whole history
	window, that is reported plainly rather than guessed at.
	"""
	history = []
	for index in range(FORECAST_HISTORY_WEEKS - 1, -1, -1):
		as_of = add_days(end, -7 * index)
		w_start = add_days(as_of, -7)
		# creation/completed_on are full datetimes; "<= as_of" would compare against
		# midnight and silently drop anything created or finished later that same day,
		# so the upper bound has to be the start of the NEXT day instead.
		before = add_days(as_of, 1)
		created = frappe.db.count(
			"Task", {**scoped, "status": ["!=", "Cancelled"], "creation": ["<", before]}
		)
		done_by = frappe.db.count(
			"Task", {**scoped, "status": "Completed", "completed_on": ["<", before]}
		)
		completed_that_week = frappe.db.count(
			"Task", {**scoped, "status": "Completed", "completed_on": ["between", [w_start, before]]}
		)
		history.append(
			{
				"label": str(as_of)[5:],
				"date": str(as_of),
				"open": max(0, created - done_by),
				"completed": completed_that_week,
			}
		)

	weekly_throughput = [h["completed"] for h in history]

	if not open_total:
		return {
			"history": history, "open_total": 0, "insufficient": False, "done": True,
			"p50_weeks": 0, "p85_weeks": 0, "p50_date": str(end), "p85_date": str(end), "capped": False,
		}

	if not sum(weekly_throughput):
		return {
			"history": history, "open_total": open_total, "insufficient": True, "done": False,
			"note": f"Nothing has been completed in the last {FORECAST_HISTORY_WEEKS} weeks, so there "
			"is no real throughput to project a completion date from yet.",
		}

	trial_weeks = []
	for _ in range(FORECAST_TRIALS):
		remaining = open_total
		weeks = 0
		while remaining > 0 and weeks < FORECAST_MAX_WEEKS:
			remaining -= random.choice(weekly_throughput)
			weeks += 1
		trial_weeks.append(weeks)
	trial_weeks.sort()
	p50 = trial_weeks[int(len(trial_weeks) * 0.5)]
	p85 = trial_weeks[min(len(trial_weeks) - 1, int(len(trial_weeks) * 0.85))]
	capped = p85 >= FORECAST_MAX_WEEKS

	return {
		"history": history,
		"open_total": open_total,
		"insufficient": False,
		"done": False,
		"p50_weeks": p50,
		"p85_weeks": p85,
		"p50_date": str(add_days(end, p50 * 7)),
		"p85_date": str(add_days(end, p85 * 7)),
		"capped": capped,
	}


def _due_soon(scoped: dict, end) -> dict:
	"""Not late yet - but the next thing that will be, if nothing moves. Distinct
	from `_risks`, which only ever looks backward at what already slipped."""
	horizon = add_days(end, 7)
	rows = frappe.get_all(
		"Task",
		filters={**scoped, "status": OPEN_TASK, "exp_end_date": ["between", [end, horizon]]},
		fields=["name", "subject", "status", "exp_end_date", "custom_module", "_assign"],
		order_by="exp_end_date asc",
		limit=10,
		ignore_permissions=True,
	)
	names = _names({who for row in rows for who in _assignees(row)})
	for row in rows:
		row["who"] = [names.get(w, w) for w in _assignees(row)] or ["Unassigned"]
		row["exp_end_date"] = str(row["exp_end_date"])
		row.pop("_assign", None)
	total = frappe.db.count("Task", {**scoped, "status": OPEN_TASK, "exp_end_date": ["between", [end, horizon]]})
	return {"total": total, "items": rows}


def _stalled(scoped: dict, end) -> list[dict]:
	"""Open work nobody has touched in a fortnight. Distinct from old work: this
	is work that started and then stopped."""
	rows = frappe.get_all(
		"Task",
		filters={**scoped, "status": OPEN_TASK, "modified": ["<", add_days(end, -14)]},
		fields=["name", "subject", "status", "modified", "custom_module", "_assign"],
		order_by="modified asc",
		limit=8,
		ignore_permissions=True,
	)
	names = _names({who for row in rows for who in _assignees(row)})
	for row in rows:
		row["who"] = [names.get(w, w) for w in _assignees(row)] or ["Unassigned"]
		row["quiet"] = (getdate(end) - getdate(row.modified)).days
		row["modified"] = str(row["modified"])[:10]
		row.pop("_assign", None)
	return rows


def _needs_you(scoped: dict, end) -> list[dict]:
	"""Every entry here is something only a Projects Manager decision moves forward - a plain
	backlog-size or overdue count belongs in the KPIs above; this is specifically the queue
	of things waiting on a person, not a number."""
	out = []

	waiting = frappe.get_all(
		"Request", filters={**scoped, "workflow_state": DECIDING}, fields=["creation"], ignore_permissions=True
	)
	if waiting:
		ages = [(getdate(end) - getdate(r.creation)).days for r in waiting]
		out.append(
			{
				"key": "waiting",
				"n": len(waiting),
				"title": "Requests awaiting your decision",
				"sub": f"Oldest has waited {max(ages)} day{'s' if max(ages) != 1 else ''}",
				"href": "/review-queue",
			}
		)

	approved = frappe.get_all(
		"Request", filters={**scoped, "workflow_state": "Approved"}, fields=["creation"], ignore_permissions=True
	)
	if approved:
		ages = [(getdate(end) - getdate(r.creation)).days for r in approved]
		out.append(
			{
				"key": "approved",
				"n": len(approved),
				"title": "Approved, not yet scheduled",
				"sub": f"Oldest approved {max(ages)} day{'s' if max(ages) != 1 else ''} ago",
				"href": "/review-queue",
			}
		)

	pending_deploy = frappe.db.count("Deployment Request", {"requires_approval": 1, "approval_status": "Pending"})
	if pending_deploy:
		out.append(
			{
				"key": "deploy_approval",
				"n": pending_deploy,
				"title": "Deployment approvals",
				"sub": "Raised during peak hours, blocked until you decide",
				"href": "/deployments",
			}
		)

	unconfirmed = frappe.get_all(
		"Request", filters={**scoped, "workflow_state": "Completed"}, fields=["creation"], ignore_permissions=True
	)
	if unconfirmed:
		ages = [(getdate(end) - getdate(r.creation)).days for r in unconfirmed]
		out.append(
			{
				"key": "unconfirmed",
				"n": len(unconfirmed),
				"title": "Completed, raiser hasn't confirmed",
				"sub": f"Oldest {max(ages)} day{'s' if max(ages) != 1 else ''}",
				"href": "/requests-portal",
			}
		)

	overdue_tasks = frappe.get_all(
		"Task", filters=_overdue_filters(scoped, end), fields=["name", "_assign"], ignore_permissions=True
	)
	unassigned = sum(1 for t in overdue_tasks if not _assignees(t))
	if unassigned:
		out.append(
			{
				"key": "unassigned",
				"n": unassigned,
				"title": "Overdue with no assignee",
				"sub": "Nobody is accountable for these",
				"href": "/backlog-board",
			}
		)

	return out


def _data_trust(scoped: dict) -> dict:
	"""How much of the open backlog actually carries the fields every other metric on this
	page assumes are there. A KPI computed over incomplete data isn't wrong, but every number
	above is quoting more confidence than the data behind it deserves unless this is visible
	too."""
	open_tasks = frappe.get_all(
		"Task",
		filters={**scoped, "status": OPEN_TASK},
		fields=["exp_end_date", "custom_module", "_assign"],
		ignore_permissions=True,
	)
	total = len(open_tasks) or 1
	with_due = sum(1 for t in open_tasks if t.exp_end_date)
	with_module = sum(1 for t in open_tasks if t.custom_module)
	with_assignee = sum(1 for t in open_tasks if _assignees(t))
	return {
		"total_open": len(open_tasks),
		"with_due_date": round(with_due / total * 100),
		"with_assignee": round(with_assignee / total * 100),
		"with_module": round(with_module / total * 100),
	}


def _plan_vs_reality(scoped: dict, start, end) -> dict:
	"""Of the work actually delivered this period, how much went through intake at all. A
	completed task with no linked Request was never triaged, prioritised, or reviewed by
	anyone before someone built it - Task.custom_request is the one field that says so."""
	done = frappe.get_all(
		"Task",
		filters={**scoped, "status": "Completed", "completed_on": ["between", [start, end]]},
		fields=["name", "subject", "custom_module", "custom_request", "completed_on"],
		ignore_permissions=True,
	)
	if not done:
		return {"total": 0, "off_books": 0, "pct": 0, "items": []}
	off_books = [t for t in done if not t.custom_request]
	for t in off_books:
		t["days_since"] = (getdate(end) - getdate(t.completed_on)).days
		t["completed_on"] = str(t.completed_on)[:10]
	off_books.sort(key=lambda t: -t["days_since"])
	return {
		"total": len(done),
		"off_books": len(off_books),
		"pct": round(len(off_books) / len(done) * 100),
		"items": off_books[:6],
	}


STAGE_SEQUENCE = [
	("Under Review", "Waiting on you"),
	("Approved", "Approved, not yet scheduled"),
	("Scheduled", "Scheduled, not yet started"),
	("In Progress", "Being built"),
	("Completed", "Done, not yet confirmed"),
]


RELEASE_WEEKS = 8


def _releases() -> dict:
	"""Deployment health, built only from Deployment Request's own fields (app, instance,
	workflow_state, creation) - not from its link back to a Request, which is real in the
	schema but essentially never populated in practice (see the system reference), so
	anything needing that link (ship lag, approval wait, "done not shipped") is left out
	here rather than shown as a permanent, misleading empty state."""
	rows = frappe.get_all(
		"Deployment Request",
		fields=["name", "app", "instance", "workflow_state", "creation"],
		ignore_permissions=True,
		limit_page_length=0,
	)
	if not rows:
		return {"total": 0, "failure_rate": None, "frequency": [], "hotspots": []}

	total = len(rows)
	failed = sum(1 for r in rows if r.workflow_state == "Failed")

	end = getdate(today())
	instances = sorted({r.instance for r in rows if r.instance})
	weeks = []
	for index in range(RELEASE_WEEKS - 1, -1, -1):
		to = add_days(end, -7 * index)
		since = add_days(to, -7)
		weeks.append((str(to)[5:], since, add_days(to, 1)))

	frequency = []
	for instance in instances:
		inst_rows = [r for r in rows if r.instance == instance]
		counts = []
		for label, since, before in weeks:
			counts.append(sum(1 for r in inst_rows if since <= getdate(r.creation) < before))
		frequency.append({"instance": instance, "counts": counts, "total": len(inst_rows)})
	frequency.sort(key=lambda r: -r["total"])
	week_labels = [w[0] for w in weeks]

	hotspot_keys: dict[tuple[str, str], dict] = defaultdict(lambda: {"total": 0, "failed": 0})
	for r in rows:
		key = (r.app or "Unknown", r.instance or "Unknown")
		hotspot_keys[key]["total"] += 1
		if r.workflow_state == "Failed":
			hotspot_keys[key]["failed"] += 1
	hotspots = [
		{
			"app": app,
			"instance": instance,
			"total": v["total"],
			"failed": v["failed"],
			"rate": round(v["failed"] / v["total"] * 100) if v["total"] else 0,
		}
		for (app, instance), v in hotspot_keys.items()
		if v["failed"]
	]
	hotspots.sort(key=lambda r: -r["rate"])

	return {
		"total": total,
		"failure_rate": round(failed / total * 100),
		"failed": failed,
		"week_labels": week_labels,
		"frequency": frequency[:8],
		"hotspots": hotspots[:8],
	}


def _pipeline(start, end) -> dict:
	"""Everything here reads Request site-wide rather than scoped to a Dev Tools project. A
	freshly raised Request usually has no project yet - it's attached post-insert, once
	someone accepts it (see api.requests.create_request) - so scoping this the same way as
	the Task-based metrics above would make the newest, least-triaged demand invisible."""
	return {
		"funnel": _funnel(start, end),
		"stages": _stage_durations(),
		"demand": _demand_by_area(start, end),
		"deferred": _deferred_and_forgotten(),
		"intake_source": _intake_source_wait(start, end),
	}


def _funnel(start, end) -> dict:
	rows = frappe.get_all(
		"Request", filters={"creation": ["between", [start, end]]}, fields=["workflow_state"], ignore_permissions=True
	)
	counts: dict[str, int] = defaultdict(int)
	for r in rows:
		counts[r.workflow_state or "Under Review"] += 1
	accepted = counts["Approved"] + counts["Scheduled"] + counts["In Progress"] + counts["Completed"] + counts["Closed"]
	return {
		"raised": len(rows),
		"accepted": accepted,
		"delivered": counts["Completed"] + counts["Closed"],
		"closed": counts["Closed"],
		"rejected": counts["Rejected"],
		"deferred": counts["Deferred"],
		"withdrawn": counts["Withdrawn"],
		"still_deciding": counts[""] + counts["Under Review"],
	}


def _stage_durations() -> dict:
	"""Median days spent in each Request Review stage, read from Frappe's own Version log of
	workflow_state changes - the literal timestamp each transition actually happened, not an
	estimate. One Version query per request; fine at this app's real request volume, worth
	revisiting if that volume grows by an order of magnitude."""
	requests = frappe.get_all("Request", fields=["name", "creation"], ignore_permissions=True, limit_page_length=0)
	if not requests:
		return {"stages": [], "median_total_days": None, "sample_size": 0}

	per_stage: dict[str, list[float]] = defaultdict(list)
	total_days = []
	for req in requests:
		versions = frappe.get_all(
			"Version",
			filters={"ref_doctype": "Request", "docname": req.name},
			fields=["creation", "data"],
			order_by="creation asc",
			ignore_permissions=True,
		)
		# a Request always starts life in "Under Review" (the Request Review workflow's
		# own default state), so the timeline can always be seeded from its creation.
		timeline = [("Under Review", get_datetime(req.creation))]
		for v in versions:
			try:
				data = json.loads(v.data) if v.data else {}
			except (TypeError, ValueError):
				continue
			for change in data.get("changed") or []:
				if change[0] == "workflow_state" and change[2]:
					timeline.append((change[2], get_datetime(v.creation)))
		for i in range(len(timeline) - 1):
			state, at = timeline[i]
			elapsed = (timeline[i + 1][1] - at).total_seconds() / 86400
			per_stage[state].append(max(0.0, elapsed))
		last_state, last_at = timeline[-1]
		if last_state in ("Completed", "Closed"):
			total_days.append((last_at - get_datetime(req.creation)).total_seconds() / 86400)

	stages = []
	for state, label in STAGE_SEQUENCE:
		days = per_stage.get(state, [])
		stages.append({"state": state, "label": label, "median_days": _median_days(days), "sample_size": len(days)})
	return {"stages": stages, "median_total_days": _median_days(total_days), "sample_size": len(total_days)}


def _demand_by_area(start, end) -> list[dict]:
	rows = frappe.get_all(
		"Request",
		filters={"creation": ["between", [start, end]]},
		fields=["name", "product_area", "workflow_state", "creation"],
		ignore_permissions=True,
	)
	buckets: dict[str, dict] = defaultdict(lambda: {"raised": 0, "accepted": 0, "wait_ages": []})
	for r in rows:
		area = r.product_area or "Unset"
		bucket = buckets[area]
		bucket["raised"] += 1
		if r.workflow_state in ("Approved", "Scheduled", "In Progress", "Completed", "Closed"):
			bucket["accepted"] += 1
		if r.workflow_state in ("", "Under Review"):
			bucket["wait_ages"].append((getdate(end) - getdate(r.creation)).days)

	open_counts: dict[str, int] = defaultdict(int)
	for r in frappe.get_all(
		"Request",
		filters={"workflow_state": ["not in", ["Completed", "Rejected", "Withdrawn", "Closed"]]},
		fields=["product_area"],
		ignore_permissions=True,
	):
		open_counts[r.product_area or "Unset"] += 1

	out = []
	for area, bucket in buckets.items():
		out.append(
			{
				"area": area,
				"raised": bucket["raised"],
				"accepted_pct": round(bucket["accepted"] / bucket["raised"] * 100) if bucket["raised"] else 0,
				"median_wait": _median(bucket["wait_ages"]),
				"open": open_counts.get(area, 0),
			}
		)
	return sorted(out, key=lambda r: -r["raised"])[:10]


def _deferred_and_forgotten() -> list[dict]:
	"""modified stands in for "when it became Deferred" - approximate (any field edit bumps
	it, not only a state change), but there is no dedicated deferred-on timestamp to read
	instead, and this is only ever used to sort oldest-first, not to quote a precise date."""
	rows = frappe.get_all(
		"Request",
		filters={"workflow_state": "Deferred"},
		fields=["name", "title", "product_area", "modified"],
		order_by="modified asc",
		limit=8,
		ignore_permissions=True,
	)
	out = []
	for r in rows:
		out.append(
			{
				"name": r.name,
				"title": r.title,
				"area": r.product_area,
				"days": (getdate(today()) - getdate(r.modified)).days,
			}
		)
	return out


def _intake_source_wait(start, end) -> list[dict]:
	"""modified stands in for "time of first decision," same caveat as _deferred_and_forgotten -
	fine for a median across many requests per source, not precise for any one of them."""
	rows = frappe.get_all(
		"Request",
		filters={"creation": ["between", [start, end]]},
		fields=["source", "workflow_state", "creation", "modified"],
		ignore_permissions=True,
	)
	if not rows:
		return []
	counts: dict[str, int] = defaultdict(int)
	wait_ages: dict[str, list[int]] = defaultdict(list)
	for r in rows:
		source = r.source or "Desk"
		counts[source] += 1
		if r.workflow_state not in ("", "Under Review"):
			wait_ages[source].append((getdate(r.modified) - getdate(r.creation)).days)

	total = len(rows)
	out = [
		{
			"source": source,
			"count": n,
			"share": round(n / total * 100),
			"median_wait": _median(wait_ages.get(source, [])),
		}
		for source, n in counts.items()
	]
	return sorted(out, key=lambda r: -r["count"])


def _assignees(row) -> list[str]:
	raw = row.get("_assign")
	return json.loads(raw) if raw else []


def _names(emails: set[str]) -> dict[str, str]:
	if not emails:
		return {}
	rows = frappe.get_all("User", filters={"name": ["in", list(emails)]}, fields=["name", "full_name"])
	return {row.name: row.full_name or row.name for row in rows}


def _median(values: list[int]) -> int | None:
	if not values:
		return None
	ordered = sorted(values)
	middle = len(ordered) // 2
	if len(ordered) % 2:
		return ordered[middle]
	# round half up, not to even - a median of 2.5 days reads oddly as 2 one time
	# and 4 the next, which is what round() does
	return int((ordered[middle - 1] + ordered[middle]) / 2 + 0.5)


def _median_days(values: list[float]) -> float | None:
	"""Same as _median, but keeps one decimal place instead of rounding to a whole day -
	appropriate where the values are already fractional (hours matter, not just days)."""
	if not values:
		return None
	ordered = sorted(values)
	middle = len(ordered) // 2
	if len(ordered) % 2:
		return round(ordered[middle], 1)
	return round((ordered[middle - 1] + ordered[middle]) / 2, 1)


def _percentile(values: list[int], pct: int) -> int | None:
	if not values:
		return None
	ordered = sorted(values)
	k = (len(ordered) - 1) * (pct / 100)
	lo = int(k)
	hi = min(lo + 1, len(ordered) - 1)
	if lo == hi:
		return ordered[lo]
	return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo))
