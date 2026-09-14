"""Everything a projects manager needs to answer "how are we doing" in one read.

Every figure here is measured, not estimated. Where a measure depends on data the
team has to record - a completion date, a due date - the count of items it could
actually be computed from is returned alongside it, so a number is never quoted
with more confidence than the data behind it deserves.
"""

import json
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import add_days, getdate, today

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
	# A portfolio measures work that belongs to a project. Tasks imported without
	# one - on this bench, an agronomy backlog of over a thousand rows - are not
	# the dev team's and would swamp every count, so they are excluded and said so.
	scoped = {"project": ["in", projects]} if projects is not None else {"project": ["is", "set"]}
	loose = frappe.db.count("Task", {"project": ["is", "not set"]})

	now = _window(scoped, start, end)
	before = _window(scoped, prev_start, start)

	open_total = frappe.db.count("Task", {**scoped, "status": OPEN_TASK})
	# Little's law, stated plainly: at the rate of the period just measured, how
	# long until the open pile is gone. Only meaningful if anything shipped.
	rate = now["delivered"] / days if now["delivered"] else 0
	forecast = round(open_total / rate) if rate else None

	return {
		"period": {
			"days": days,
			"from": str(start),
			"to": str(end),
			"excluded": loose,
			"open": open_total,
			"clears_in": forecast,
			"clears_on": str(add_days(end, forecast)) if forecast and forecast < 3650 else None,
		},
		"kpis": _kpis(now, before, scoped, end),
		"flow": _flow(scoped, end),
		"wins": _wins(scoped, start),
		"risks": _risks(scoped, end),
		"people": _people(scoped, end),
		"modules": _modules(scoped, start, end),
		"ageing": _ageing(scoped, end),
		"projects": _projects_roll(projects, end),
		"requests": _requests(scoped, end),
		"stalled": _stalled(scoped, end),
	}


def _projects(scope: str | None) -> list[str] | None:
	if not scope:
		return None
	if scope not in ("Internal", "External"):
		frappe.throw(_("scope must be Internal or External."), frappe.ValidationError)
	return frappe.get_all(
		"Project", filters={"custom_project_scope": scope}, pluck="name", ignore_permissions=True
	) or [""]


def _window(scoped: dict, start, end) -> dict:
	"""What was delivered and what arrived between two dates."""
	done = frappe.get_all(
		"Task",
		filters={**scoped, "status": "Completed", "completed_on": ["between", [start, end]]},
		fields=["name", "subject", "creation", "completed_on", "exp_end_date", "custom_module", "_assign"],
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
		"on_time": round(on_time / datable * 100) if datable else None,
		"datable": datable,
	}


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
			"Cycle time",
			now["cycle"],
			before["cycle"],
			"down",
			unit="d",
			note="Median days from a task being raised to being finished.",
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


def _risks(scoped: dict, end) -> list[dict]:
	out = []
	for task in frappe.get_all(
		"Task",
		filters=_overdue_filters(scoped, end),
		fields=["name", "subject", "exp_end_date", "_assign"],
		order_by="exp_end_date asc",
		limit=8,
		ignore_permissions=True,
	):
		out.append(
			{
				"kind": "Past due",
				"doctype": "Task",
				"name": task.name,
				"title": task.subject,
				"days": (getdate(end) - getdate(task.exp_end_date)).days,
				"who": _assignees(task),
			}
		)

	for issue in frappe.get_all(
		"Issue",
		filters={**scoped, "status": "On Hold"},
		fields=["name", "subject", "opening_date", "_assign"],
		limit=5,
		ignore_permissions=True,
	):
		out.append(
			{
				"kind": "On hold",
				"doctype": "Issue",
				"name": issue.name,
				"title": issue.subject,
				"days": (getdate(end) - getdate(issue.opening_date)).days if issue.opening_date else 0,
				"who": _assignees(issue),
			}
		)

	for req in frappe.get_all(
		"Request",
		filters={**scoped, "workflow_state": DECIDING},
		fields=["name", "title", "creation"],
		limit=5,
		ignore_permissions=True,
	):
		out.append(
			{
				"kind": "Awaiting you",
				"doctype": "Request",
				"name": req.name,
				"title": req.title,
				"days": (getdate(end) - getdate(req.creation)).days,
				"who": [],
			}
		)

	names = _names({w for row in out for w in row["who"]})
	for row in out:
		row["who"] = [names.get(w, w) for w in row["who"]]
	return sorted(out, key=lambda r: -r["days"])[:10]


def _people(scoped: dict, end) -> list[dict]:
	buckets: dict[str, dict] = {}
	for task in frappe.get_all(
		"Task",
		filters={**scoped, "status": OPEN_TASK},
		fields=["name", "exp_end_date", "_assign"],
		ignore_permissions=True,
	):
		for who in _assignees(task) or ["Unassigned"]:
			bucket = buckets.setdefault(who, {"user": who, "open": 0, "overdue": 0, "delivered": 0})
			bucket["open"] += 1
			if task.exp_end_date and getdate(task.exp_end_date) < getdate(end):
				bucket["overdue"] += 1

	for task in frappe.get_all(
		"Task",
		filters={**scoped, "status": "Completed", "completed_on": [">=", add_days(end, -30)]},
		fields=["name", "_assign"],
		ignore_permissions=True,
	):
		for who in _assignees(task) or ["Unassigned"]:
			buckets.setdefault(who, {"user": who, "open": 0, "overdue": 0, "delivered": 0})["delivered"] += 1

	names = _names({w for w in buckets if w != "Unassigned"})
	for who, bucket in buckets.items():
		bucket["name"] = "Unassigned" if who == "Unassigned" else names.get(who, who)
	return sorted(buckets.values(), key=lambda b: (-b["open"], -b["delivered"]))


def _modules(scoped: dict, start, end) -> list[dict]:
	"""A dot per task, so the size of a module and its mix read at once rather
	than as a bar whose proportions have to be decoded."""
	counts: dict[str, dict] = defaultdict(lambda: {"open": 0, "late": 0, "delivered": 0})
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
		fields=["custom_module"],
		ignore_permissions=True,
	):
		counts[task.custom_module or "No module"]["delivered"] += 1

	rows = [{"module": key, **value, "total": sum(value.values())} for key, value in counts.items()]
	return sorted(rows, key=lambda r: -r["total"])[:10]


AGE_BANDS = [("Under a week", 7), ("One to two weeks", 14), ("Two to four weeks", 30), ("Over a month", None)]


def _ageing(scoped: dict, end) -> list[dict]:
	"""How long open work has been open. A backlog that is merely large is one
	thing; a backlog that is old is another."""
	bands = [{"label": label, "count": 0} for label, _ in AGE_BANDS]
	for task in frappe.get_all(
		"Task", filters={**scoped, "status": OPEN_TASK}, fields=["creation"], ignore_permissions=True
	):
		age = (getdate(end) - getdate(task.creation)).days
		for index, (_, ceiling) in enumerate(AGE_BANDS):
			if ceiling is None or age < ceiling:
				bands[index]["count"] += 1
				break
	return bands


def _projects_roll(projects: list[str] | None, end) -> list[dict]:
	filters = {"status": ["!=", "Cancelled"]}
	if projects is not None:
		filters["name"] = ["in", projects]

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
