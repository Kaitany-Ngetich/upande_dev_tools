# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
"""Requests v2 - raise, track and follow requests (www/requests-v2.html).

Source: doctype Request (+ Request Type, Priority Level, Product Area, Tag Link, Task, Version,
Comment). Every endpoint in this module READS. The page writes through the existing endpoints of
upande_dev_tools.api.requests (create_request, update_request, withdraw_request,
confirm_request_complete), so validation, permissions and side effects stay exactly as on the
current /requests-portal page. This module only tells the page which of those actions the
signed-in user may use (`can_edit`, `can_withdraw`, `can_confirm`) and which choices the raise
form offers (get_form_options).

WHO MAY SEE WHAT (security, mirrors the current page exactly)
    * Page access = the Dev Portal Page "requests-portal" (today: role All, i.e. every signed-in
      user). Every endpoint here re-checks it, because a whitelisted method can be called without
      the page.
    * The current page (api.requests.get_my_requests) shows every request to everyone: title,
      type, status, priority, project, raiser, tags, "being built" flag, who it is assigned to
      and when it was raised. v2 shows exactly that to everyone.
    * Triage detail is NOT shown by the current page, so it is limited to "privileged" people:
      Dev Team / Projects Manager / System Manager (the REVIEWER_ROLES of api.requests), and, for
      their own requests only, the person who raised it (owner or the employee it was raised
      for). That covers: product area, the linked Task's name/status/due date, who made each
      decision and when, comment text and the resolution notes. Everyone else gets a timeline of
      "raised / moved to <state> on <date>" without names or text. Product-area filters and the
      product-area breakdown are ignored for non-privileged users, so a filter cannot be used to
      reveal a product area.

DEFINITIONS (every figure follows every filter)
    open        = status not in Completed / Rejected / Withdrawn / Closed (the same set the current
                  page uses; "Deferred" counts as open there and here).
    closed out  = status in Completed / Rejected / Withdrawn / Closed.
    cohort      = requests whose creation date (site time zone, as stored) is in [from, to] and
                  that pass every other filter.
    opened      = a cohort request.     opened series sums to `raised`.
    closed      = date the request entered a closed-out status, taken from its change history
                  (Version). When the history has no such step (Withdraw / Confirm complete are
                  written with db_set and leave no history) the last-modified time is used and the
                  row is flagged `resolved_estimated`.
    first response = earliest of: the first status change, the first comment written by someone
                  other than the raiser. Unknown (None) when there is no recorded history.
    time to close = resolved - creation (cohort requests that are closed out).
    reopened    = number of times the status went back to "Under Review".

IDENTITIES (verified in the module tests / report)
    raised == opened series total == sum(by_status) == sum(by_type) == sum(by_priority)
           == sum(by_requester) == open + closed_out
    closed_out == completed + closed + rejected + withdrawn
    by_product_area (privileged) sums to raised, by_type includes types with 0 requests.
    The closed series counts requests CLOSED in the period (any creation date, same filters),
    so it can differ from the cohort's closed_out; both are labelled.
"""

import json
import re
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import add_days, get_datetime, getdate, now_datetime, nowdate, strip_html_tags

from upande_dev_tools import portal
from upande_dev_tools.api.board import get_modules, get_work_tags
from upande_dev_tools.api.requests import (
	REVIEWER_ROLES,
	_resolve_user_display_names,
	get_assignable_users,
	get_employees,
)

PAGE_ROUTE = "requests-portal"
TERMINAL = ("Completed", "Rejected", "Withdrawn", "Closed")
STATE_ORDER = (
	"Under Review",
	"Approved",
	"Deferred",
	"Scheduled",
	"In Progress",
	"Completed",
	"Closed",
	"Rejected",
	"Withdrawn",
)
# States api.requests.withdraw_request accepts (it hardcodes the same set).
WITHDRAWABLE = ("Under Review", "Approved", "Deferred", "Scheduled", "In Progress")
# Roles for which the current raise form shows Module / Priority and which may edit any request
# from the page (requests_portal.py `is_reviewer`). Narrower than REVIEWER_ROLES: no System Manager.
TRIAGE_FORM_ROLES = {"Dev Team", "Projects Manager"}
ROW_LIMIT = 500
FETCH_CAP = 20000
NONE_KEY = "__none__"


# ---------------------------------------------------------------- access


def _check_access():
	"""Same rule as portal.enforce_page_access("requests-portal"): the page must be registered
	and the user must hold one of its roles. Returns (user, privileged, my_employee)."""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Please sign in."), frappe.PermissionError)
	page = portal._fetch_page(PAGE_ROUTE)
	roles = set(frappe.get_roles(user))
	if not (
		page and portal._is_permitted(portal._allowed_roles(page.name), bool(page.require_all_roles), roles)
	):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	privileged = bool(roles & REVIEWER_ROLES)
	employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
	return user, privileged, employee


def _is_mine(row, user, employee):
	"""The submitter, or the employee the request was raised for (what withdraw / confirm accept)."""
	return row["owner"] == user or bool(employee and row.get("raised_by_employee") == employee)


def row_actions(state, is_owner, is_raiser, triage_form_role):
	"""Which write buttons the current page shows on a request, as booleans.

	edit      = a Dev Team / Projects Manager user, or the submitter while still "Under Review"
	            (api.requests.update_request refuses anything else).
	withdraw  = the submitter or raised-for employee, from a state in WITHDRAWABLE.
	confirm   = the submitter or raised-for employee, once "Completed" (moves it to "Closed")."""
	return {
		"can_edit": bool(triage_form_role or (is_owner and state == "Under Review")),
		"can_withdraw": bool(is_raiser and state in WITHDRAWABLE),
		"can_confirm": bool(is_raiser and state == "Completed"),
	}


def _actions_for(row, user, employee):
	return row_actions(
		row["workflow_state"],
		row["owner"] == user,
		_is_mine(row, user, employee),
		bool(set(frappe.get_roles(user)) & TRIAGE_FORM_ROLES),
	)


# ---------------------------------------------------------------- helpers


def _args(kw):
	g = lambda k: str(kw.get(k) or "").strip()  # noqa: E731
	to_date = getdate(g("to_date") or nowdate())
	from_date = getdate(g("from_date") or add_days(to_date, -89))
	if from_date > to_date:
		from_date, to_date = to_date, from_date
	return {
		"from_date": from_date,
		"to_date": to_date,
		"status": g("status"),
		"scope": g("scope") if g("scope") in ("open", "closed") else "",
		"request_type": g("request_type"),
		"priority": g("priority"),
		"product_area": g("product_area"),
		"requester": g("requester"),
		"assignee": g("assignee"),
		"project": g("project"),
		"tag": g("tag"),
		"mine": g("mine") in ("1", "true"),
		"q": g("q"),
	}


def _norm_title(t):
	return re.sub(r"\s+", " ", (t or "").strip().lower())


def _like(s):
	return "%" + s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _where(a, privileged, user, employee):
	w, p = ["1=1"], {}
	if a["status"]:
		w.append("r.workflow_state = %(status)s")
		p["status"] = a["status"]
	if a["scope"] == "open":
		w.append("IFNULL(r.workflow_state,'') NOT IN %(term)s")
		p["term"] = TERMINAL
	elif a["scope"] == "closed":
		w.append("r.workflow_state IN %(term)s")
		p["term"] = TERMINAL
	if a["request_type"]:
		w.append("r.request_type = %(rtype)s")
		p["rtype"] = a["request_type"]
	if a["priority"]:
		if a["priority"] == NONE_KEY:
			w.append("IFNULL(r.priority,'') = ''")
		else:
			w.append("r.priority = %(prio)s")
			p["prio"] = a["priority"]
	if a["product_area"] and privileged:
		if a["product_area"] == NONE_KEY:
			w.append("IFNULL(r.product_area,'') = ''")
		else:
			w.append("r.product_area = %(area)s")
			p["area"] = a["product_area"]
	if a["requester"]:
		w.append("r.owner = %(req)s")
		p["req"] = a["requester"]
	if a["project"]:
		if a["project"] == NONE_KEY:
			w.append("IFNULL(r.project,'') = ''")
		else:
			w.append("r.project = %(proj)s")
			p["proj"] = a["project"]
	if a["tag"]:
		w.append(
			"EXISTS (SELECT 1 FROM `tabTag Link` tl WHERE tl.document_type = 'Request'"
			" AND tl.document_name = r.name AND tl.tag = %(tag)s)"
		)
		p["tag"] = a["tag"]
	if a["mine"]:
		if employee:
			w.append("(r.owner = %(me)s OR r.raised_by_employee = %(emp)s)")
			p["emp"] = employee
		else:
			w.append("r.owner = %(me)s")
		p["me"] = user
	if a["q"]:
		w.append("(r.title LIKE %(q)s OR r.name LIKE %(q)s OR r.description LIKE %(q)s)")
		p["q"] = _like(a["q"])
	return " AND ".join(w), p


def _chunks(seq, n=500):
	seq = list(seq)
	for i in range(0, len(seq), n):
		yield seq[i : i + n]


def _history(names):
	"""{request: [(ts, from_state, to_state, actor)]} oldest first, from Version."""
	out = {}
	for part in _chunks(names):
		rows = frappe.db.sql(
			"""SELECT docname, creation, owner, data FROM `tabVersion`
			   WHERE ref_doctype = 'Request' AND docname IN %(n)s AND data LIKE %(like)s
			   ORDER BY creation ASC, name ASC""",
			{"n": part, "like": "%workflow_state%"},
			as_dict=True,
		)
		for v in rows:
			try:
				changed = json.loads(v.data or "{}").get("changed") or []
			except ValueError:
				continue
			for ch in changed:
				if len(ch) >= 3 and ch[0] == "workflow_state":
					out.setdefault(v.docname, []).append((v.creation, ch[1] or None, ch[2], v.owner))
	return out


def _first_comments(names):
	"""{request: [(ts, author)]} of human comments (not the automatic Workflow ones)."""
	out = {}
	for part in _chunks(names):
		for c in frappe.db.sql(
			"""SELECT reference_name, creation, comment_email FROM `tabComment`
			   WHERE reference_doctype = 'Request' AND reference_name IN %(n)s
			     AND comment_type = 'Comment' ORDER BY creation ASC""",
			{"n": part},
			as_dict=True,
		):
			out.setdefault(c.reference_name, []).append((c.creation, c.comment_email))
	return out


def _tasks_for(names, linked):
	"""Tasks reached through Request.linked_task or Task.custom_request: {request: task row}."""
	by_req, wanted = {}, set(linked.values())
	rows = []
	for part in _chunks(names):
		rows += frappe.db.sql(
			"SELECT name, subject, status, project, exp_end_date, _assign, custom_request FROM `tabTask`"
			" WHERE custom_request IN %(n)s",
			{"n": part},
			as_dict=True,
		)
	for part in _chunks([t for t in wanted if t]):
		rows += frappe.db.sql(
			"SELECT name, subject, status, project, exp_end_date, _assign, custom_request FROM `tabTask`"
			" WHERE name IN %(n)s",
			{"n": part},
			as_dict=True,
		)
	by_name = {t.name: t for t in rows}
	for req in names:
		t = by_name.get(linked.get(req))
		if not t:
			t = next((x for x in rows if x.custom_request == req), None)
		if t:
			by_req[req] = t
	return by_req


def _assignees(task):
	try:
		return json.loads(task._assign) if task and task._assign else []
	except ValueError:
		return []


def _derive(r, hist, comments, now):
	"""Response / resolution facts for one request from its recorded history."""
	created = get_datetime(r["creation"])
	state = r["workflow_state"]
	tr = sorted(hist or [], key=lambda x: x[0])
	resolved, reopened = None, 0
	for ts, _frm, to, _actor in tr:
		if to in TERMINAL:
			if resolved is None:
				resolved = ts
		else:
			resolved = None
		if to == "Under Review":
			reopened += 1
	resp = [ts for ts, _f, _t, _a in tr[:1]]
	resp += [ts for ts, who in (comments or []) if who != r["owner"]][:1]
	first = min(resp) if resp else None
	if first is not None and get_datetime(first) < created:
		first = None
	estimated = False
	if state in TERMINAL:
		if resolved is None:
			resolved, estimated = r["modified"], True
		if get_datetime(resolved) < created:
			resolved = created
	else:
		resolved = None
	return {
		"first_response_at": first,
		"first_response_hours": None
		if first is None
		else round((get_datetime(first) - created).total_seconds() / 3600, 2),
		"resolved_at": resolved,
		"resolved_estimated": estimated if resolved else False,
		"close_hours": None
		if resolved is None
		else round((get_datetime(resolved) - created).total_seconds() / 3600, 2),
		"reopened": reopened,
		"age_days": None if state in TERMINAL else max(0, (now - created).days),
	}


def _median(xs):
	xs = sorted(x for x in xs if x is not None)
	if not xs:
		return None
	m = len(xs) // 2
	return round(xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2, 2)


def _bucket_fn(span_days):
	if span_days <= 31:
		return "day", lambda d: d.isoformat()
	if span_days <= 400:
		return "week", lambda d: (d - timedelta(days=d.weekday())).isoformat()
	return "month", lambda d: d.replace(day=1).isoformat()


def _bucket_keys(unit, start, end, fn):
	keys, d = [], start
	while d <= end:
		k = fn(d)
		if not keys or keys[-1] != k:
			keys.append(k)
		d += timedelta(days=1)
	return keys


def _group(rows, key, order=None, labels=None):
	out = {}
	for r in rows:
		k = r.get(key) or NONE_KEY
		g = out.setdefault(k, {"key": k, "total": 0, "open": 0, "closed": 0})
		g["total"] += 1
		g["open" if r["is_open"] else "closed"] += 1
	res = list(out.values())
	for g in res:
		g["label"] = (labels or {}).get(g["key"]) or ("Not set" if g["key"] == NONE_KEY else g["key"])
	if order:
		rank = {k: i for i, k in enumerate(order)}
		res.sort(key=lambda g: (rank.get(g["key"], 99), -g["total"], g["label"]))
	else:
		res.sort(key=lambda g: (-g["total"], g["label"].lower()))
	return res


# ---------------------------------------------------------------- list / overview


def _load(a, privileged, user, employee):
	"""Every request that passes the non-date filters, enriched. Returns (rows, truncated_fetch)."""
	where, p = _where(a, privileged, user, employee)
	rows = frappe.db.sql(
		f"""SELECT r.name, r.title, r.request_type, r.workflow_state, r.priority, r.product_area,
		           r.project, r.linked_task, r.owner, r.raised_by_employee, r.creation, r.modified
		    FROM `tabRequest` r WHERE {where} ORDER BY r.creation DESC LIMIT {FETCH_CAP + 1}""",
		p,
		as_dict=True,
	)
	capped = len(rows) > FETCH_CAP
	rows = rows[:FETCH_CAP]
	names = [r["name"] for r in rows]
	hist, comments = _history(names), _first_comments(names)
	tasks = _tasks_for(names, {r["name"]: r["linked_task"] for r in rows if r["linked_task"]})
	tags = {}
	for part in _chunks(names):
		for t in frappe.db.sql(
			"SELECT document_name, tag FROM `tabTag Link` WHERE document_type='Request' AND document_name IN %(n)s",
			{"n": part},
			as_dict=True,
		):
			tags.setdefault(t.document_name, []).append(t.tag)
	emails = {r["owner"] for r in rows if r["owner"]}
	for t in tasks.values():
		emails.update(_assignees(t))
	people = _resolve_user_display_names(emails)
	now = now_datetime()
	triage_role = bool(set(frappe.get_roles(user)) & TRIAGE_FORM_ROLES)
	for r in rows:
		mine = _is_mine(r, user, employee)
		r.update(row_actions(r["workflow_state"], r["owner"] == user, mine, triage_role))
		r["can_see_detail"] = privileged or mine
		r["is_open"] = r["workflow_state"] not in TERMINAL
		r.update(_derive(r, hist.get(r["name"]), comments.get(r["name"]), now))
		task = tasks.get(r["name"])
		r["has_task"] = bool(task)
		r["assignee_emails"] = _assignees(task)
		r["assignees"] = [people.get(e, e) for e in r["assignee_emails"]]
		r["raised_by_name"] = people.get(r["owner"], r["owner"])
		r["tags"] = tags.get(r["name"], [])
		r["is_mine"] = mine
		r["_title_key"] = _norm_title(r["title"])
		if not r["can_see_detail"]:
			r["product_area"] = None
		if r["can_see_detail"] and task:
			r["task"] = task.name
			r["task_status"] = task.status
	if a["assignee"]:
		rows = [r for r in rows if a["assignee"] in r["assignee_emails"]]
	return rows, capped


def _day(v):
	return getdate(v) if v else None


@frappe.whitelist()
def get_requests_overview(**kw):
	"""Everything the page shows in one call: KPIs, opened-vs-closed series, breakdowns, the list."""
	try:
		user, privileged, employee = _check_access()
		a = _args(kw)
		rows, capped = _load(a, privileged, user, employee)
		return _overview(a, rows, capped, privileged, user, employee)
	except frappe.PermissionError:
		raise
	except Exception:
		frappe.logger("requests_v2").exception("overview")
		return {"success": False, "error": _("Could not load requests. Please try again.")}


def _overview(a, rows, capped, privileged, user, employee):
	f, t = a["from_date"], a["to_date"]
	cohort = [r for r in rows if f <= _day(r["creation"]) <= t]
	closed_in = [r for r in rows if r["resolved_at"] and f <= _day(r["resolved_at"]) <= t]

	# --- duplicates: same title (ignoring case/spacing) among ALL requests, flagged on the cohort
	counts = {}
	for k, n in frappe.db.sql(
		"SELECT LOWER(TRIM(title)), COUNT(*) FROM `tabRequest` GROUP BY LOWER(TRIM(title)) HAVING COUNT(*) > 1"
	):
		counts[_norm_title(k)] = n
	dup_groups = {}
	for r in cohort:
		n = counts.get(r["_title_key"], 0)
		r["duplicates"] = n - 1 if n > 1 else 0
		if n > 1:
			dup_groups.setdefault(r["_title_key"], []).append(r)

	# --- chart series
	starts = [_day(r["creation"]) for r in rows] + [_day(r["resolved_at"]) for r in rows if r["resolved_at"]]
	start = max(f, min(starts)) if starts else f
	start = min(start, t)
	unit, fn = _bucket_fn((t - start).days + 1)
	keys = _bucket_keys(unit, start, t, fn)
	opened, closed = dict.fromkeys(keys, 0), dict.fromkeys(keys, 0)
	for r in cohort:
		opened[fn(max(_day(r["creation"]), start))] += 1
	for r in closed_in:
		closed[fn(max(_day(r["resolved_at"]), start))] += 1

	n_open = sum(1 for r in cohort if r["is_open"])
	states = {}
	for r in cohort:
		states[r["workflow_state"]] = states.get(r["workflow_state"], 0) + 1
	by_status = [
		{
			"key": s,
			"label": s,
			"total": states[s],
			"open": states[s] if s not in TERMINAL else 0,
			"closed": states[s] if s in TERMINAL else 0,
		}
		for s in sorted(states, key=lambda s: STATE_ORDER.index(s) if s in STATE_ORDER else 99)
	]
	type_rows = frappe.get_all(
		"Request Type", fields=["name", "disabled"], order_by="name asc", ignore_permissions=True
	)
	by_type = _group(cohort, "request_type")
	have = {g["key"] for g in by_type}
	disabled = {x.name for x in type_rows if x.disabled}
	for x in type_rows:
		if x.name not in have and not a["request_type"]:
			by_type.append({"key": x.name, "label": x.name, "total": 0, "open": 0, "closed": 0})
	for g in by_type:
		g["disabled"] = g["key"] in disabled
	prio_order = frappe.get_all("Priority Level", pluck="name", ignore_permissions=True)
	by_priority = _group(cohort, "priority", order=["Urgent", "High", "Medium", "Low"])
	people = {r["owner"]: r["raised_by_name"] for r in cohort}
	by_requester = _group(cohort, "owner", labels=people)

	to_close = [r["close_hours"] for r in cohort if r["close_hours"] is not None]
	resp = [r["first_response_hours"] for r in cohort if r["first_response_hours"] is not None]
	completed_waiting = sum(1 for r in cohort if r["workflow_state"] == "Completed")
	waiting = sum(
		1 for r in cohort if r["workflow_state"] == "Under Review" and r["first_response_hours"] is None
	)
	open_ages = [r["age_days"] for r in cohort if r["is_open"] and r["age_days"] is not None]
	kpis = {
		"raised": len(cohort),
		"open": n_open,
		"closed_out": len(cohort) - n_open,
		"completed": states.get("Completed", 0),
		"closed": states.get("Closed", 0),
		"rejected": states.get("Rejected", 0),
		"withdrawn": states.get("Withdrawn", 0),
		"awaiting_signoff": completed_waiting,
		"oldest_open_days": max(open_ages) if open_ages else None,
		"waiting_first_response": waiting,
		"median_first_response_hours": _median(resp),
		"first_response_known": len(resp),
		"median_close_hours": _median(to_close),
		"close_known": len(to_close),
		"close_estimated": sum(1 for r in cohort if r["close_hours"] is not None and r["resolved_estimated"]),
		"reopened_requests": sum(1 for r in cohort if r["reopened"]),
		"reopened_times": sum(r["reopened"] for r in cohort),
	}

	listing = sorted(cohort, key=lambda r: r["creation"], reverse=True)
	total_rows = len(listing)
	listing = listing[:ROW_LIMIT]
	out_rows = [_public_row(r) for r in listing]

	# filter choices come from the data the user can see, never narrowed by their own selection
	notes = {}
	if privileged:
		beyond = frappe.db.sql(
			"""SELECT COUNT(*) FROM `tabRequest` WHERE workflow_state IN ('Scheduled','In Progress','Completed','Closed')
			   AND IFNULL(linked_task,'') = ''"""
		)[0][0]
		orphans = frappe.db.sql(
			"""SELECT COUNT(*) FROM `tabTask` t WHERE IFNULL(t.custom_request,'') <> ''
			   AND NOT EXISTS (SELECT 1 FROM `tabRequest` r WHERE r.name = t.custom_request)"""
		)[0][0]
		notes = {"scheduled_without_task": beyond, "tasks_pointing_nowhere": orphans}

	return {
		"success": True,
		"from_date": f.isoformat(),
		"to_date": t.isoformat(),
		"privileged": privileged,
		"kpis": kpis,
		"series": {
			"unit": unit,
			"labels": keys,
			"opened": [opened[k] for k in keys],
			"closed": [closed[k] for k in keys],
			"opened_total": sum(opened.values()),
			"closed_total": sum(closed.values()),
		},
		"by_status": by_status,
		"by_type": by_type,
		"by_priority": by_priority,
		"by_product_area": _group(cohort, "product_area") if privileged else None,
		"by_requester": by_requester[:15],
		"requesters_total": len(by_requester),
		"duplicates": {
			"groups": [
				{
					"title": v[0]["title"],
					"count": counts[k],
					"in_view": len(v),
					"requests": [
						{"name": x["name"], "status": x["workflow_state"], "raised": x["creation"]} for x in v
					],
				}
				for k, v in sorted(dup_groups.items(), key=lambda kv: -counts[kv[0]])
			],
			"requests": sum(len(v) for v in dup_groups.values()),
		},
		"rows": out_rows,
		"total_rows": total_rows,
		"truncated": total_rows > ROW_LIMIT or capped,
		"row_limit": ROW_LIMIT,
		"notes": notes,
		"options": _options(privileged, prio_order),
	}


def _public_row(r):
	keep = (
		"name title request_type workflow_state priority product_area project owner raised_by_name creation "
		"is_open is_mine tags assignees has_task task task_status first_response_hours close_hours "
		"resolved_at resolved_estimated reopened age_days duplicates can_see_detail can_edit can_withdraw can_confirm"
	).split()
	out = {k: r.get(k) for k in keep}
	out["creation"] = str(r["creation"])
	out["resolved_at"] = str(r["resolved_at"]) if r.get("resolved_at") else None
	return out


def _options(privileged, prio_order):
	"""Filter choices: every value in use, not just those inside the current selection."""
	d = frappe.db.sql(
		"""SELECT DISTINCT request_type, priority, project, owner, product_area FROM `tabRequest`""",
		as_dict=True,
	)
	owners = sorted({x.owner for x in d if x.owner})
	names = _resolve_user_display_names(set(owners))
	projects = sorted({x.project for x in d if x.project})
	pn = (
		{
			p.name: p.project_name
			for p in frappe.get_all(
				"Project",
				filters={"name": ["in", projects]},
				fields=["name", "project_name"],
				ignore_permissions=True,
			)
		}
		if projects
		else {}
	)
	tags = frappe.db.sql(
		"SELECT DISTINCT tag FROM `tabTag Link` WHERE document_type = 'Request' ORDER BY tag", pluck=True
	)
	assignees = set()
	for (a,) in frappe.db.sql(
		"""SELECT DISTINCT t._assign FROM `tabTask` t JOIN `tabRequest` r ON r.linked_task = t.name
		   WHERE IFNULL(t._assign,'') <> ''"""
	):
		try:
			assignees.update(json.loads(a))
		except ValueError:
			pass
	an = _resolve_user_display_names(assignees)
	return {
		"statuses": list(STATE_ORDER),
		"request_types": sorted(frappe.get_all("Request Type", pluck="name", ignore_permissions=True)),
		"priorities": [p for p in ["Urgent", "High", "Medium", "Low"]]
		+ [p for p in prio_order if p not in ("Urgent", "High", "Medium", "Low")],
		"product_areas": sorted({x.product_area for x in d if x.product_area}) if privileged else [],
		"requesters": [{"value": o, "label": names.get(o, o)} for o in owners],
		"projects": [{"value": p, "label": pn.get(p) or p} for p in projects],
		"tags": tags,
		"assignees": sorted(
			({"value": e, "label": an.get(e, e)} for e in assignees), key=lambda x: x["label"].lower()
		),
	}


# ---------------------------------------------------------------- drill-down


@frappe.whitelist()
def get_request_detail(name: str):
	"""One request: description, timeline, comments, decision and linked work.
	Triage detail (who decided, comment text, resolution notes, task) only for reviewers and the
	person who raised it; everyone else gets dates and states."""
	try:
		user, privileged, employee = _check_access()
		doc = frappe.db.get_value(
			"Request",
			name,
			[
				"name",
				"title",
				"request_type",
				"workflow_state",
				"priority",
				"product_area",
				"project",
				"linked_task",
				"owner",
				"raised_by_employee",
				"creation",
				"modified",
				"source",
				"description",
				"resolution_notes",
				"requested_assignee",
			],
			as_dict=True,
		)
		if not doc:
			return {"success": False, "error": _("That request no longer exists.")}
		full = privileged or _is_mine(doc, user, employee)
		now = now_datetime()
		hist = _history([name]).get(name, [])
		cmts = frappe.db.sql(
			"""SELECT creation, comment_email, content FROM `tabComment`
			   WHERE reference_doctype='Request' AND reference_name=%s AND comment_type='Comment'
			   ORDER BY creation ASC""",
			name,
			as_dict=True,
		)
		derived = _derive(
			{
				"creation": doc.creation,
				"modified": doc.modified,
				"workflow_state": doc.workflow_state,
				"owner": doc.owner,
			},
			hist,
			[(c.creation, c.comment_email) for c in cmts],
			now,
		)
		emails = {doc.owner} | {h[3] for h in hist} | {c.comment_email for c in cmts if c.comment_email}
		if doc.requested_assignee:
			emails.add(doc.requested_assignee)
		task = _tasks_for([name], {name: doc.linked_task} if doc.linked_task else {}).get(name)
		emails.update(_assignees(task))
		people = _resolve_user_display_names(emails)
		who = lambda e: people.get(e, e)  # noqa: E731

		events = [
			{
				"kind": "raised",
				"at": str(doc.creation),
				"text": _("Raised"),
				"by": who(doc.owner) if full else None,
			}
		]
		prev = doc.creation
		decision = None
		for ts, frm, to, actor in hist:
			ev = {
				"kind": "state",
				"at": str(ts),
				"from": frm,
				"to": to,
				"text": _("Moved to {0}").format(to),
				"by": who(actor) if full else None,
				"after_hours": round((get_datetime(ts) - get_datetime(prev)).total_seconds() / 3600, 2),
			}
			events.append(ev)
			prev = ts
			if to in ("Approved", "Rejected", "Deferred", "Withdrawn", "Completed", "Closed"):
				decision = ev
		if full:
			for c in cmts:
				text = strip_html_tags(c.content or "").strip()[:2000]
				events.append(
					{"kind": "comment", "at": str(c.creation), "text": text, "by": who(c.comment_email)}
				)
		events.sort(key=lambda e: e["at"])
		reason = None
		if full and decision:
			dts = get_datetime(decision["at"])
			for c in cmts:
				if c.comment_email and dts <= get_datetime(c.creation) <= dts + timedelta(minutes=10):
					reason = strip_html_tags(c.content or "").strip()[:2000]
					break
		if decision and not full:
			decision = {k: decision[k] for k in ("kind", "at", "to", "text")}

		same = frappe.db.sql(
			"""SELECT name, workflow_state, creation FROM `tabRequest`
			   WHERE LOWER(TRIM(title)) = %s AND name <> %s ORDER BY creation""",
			(_norm_title(doc.title), name),
			as_dict=True,
		)
		raised_for = None
		if full and doc.raised_by_employee:
			raised_for = (
				frappe.db.get_value("Employee", doc.raised_by_employee, "employee_name")
				or doc.raised_by_employee
			)
		out = _actions_for(doc, user, employee) | {
			"name": doc.name,
			"title": doc.title,
			"request_type": doc.request_type,
			"workflow_state": doc.workflow_state,
			"is_open": doc.workflow_state not in TERMINAL,
			"priority": doc.priority,
			"project": doc.project,
			"project_name": doc.project and frappe.db.get_value("Project", doc.project, "project_name"),
			"raised_by": who(doc.owner),
			"raised_at": str(doc.creation),
			"description": strip_html_tags(doc.description or "").strip()[:4000],
			"tags": frappe.get_all(
				"Tag Link",
				filters={"document_type": "Request", "document_name": name},
				pluck="tag",
				ignore_permissions=True,
			),
			"assignees": [who(e) for e in _assignees(task)],
			"has_task": bool(task),
			"full_detail": full,
			"first_response_hours": derived["first_response_hours"],
			"close_hours": derived["close_hours"],
			"resolved_at": str(derived["resolved_at"]) if derived["resolved_at"] else None,
			"resolved_estimated": derived["resolved_estimated"],
			"reopened": derived["reopened"],
			"age_days": derived["age_days"],
			"events": events,
			"decision": decision,
			"duplicates": [
				{"name": s.name, "status": s.workflow_state, "raised": str(s.creation)} for s in same
			],
		}
		if out["can_edit"]:
			# the raw text the Edit form needs (the display copy above is stripped and cut)
			out["description_raw"] = doc.description or ""
		if full:
			out.update(
				{
					"product_area": doc.product_area,
					"source": doc.source,
					"raised_for": raised_for,
					"requested_assignee": who(doc.requested_assignee) if doc.requested_assignee else None,
					"resolution_notes": doc.resolution_notes,
					"decision_reason": reason,
					"task": task
					and {
						"name": task.name,
						"subject": task.subject,
						"status": task.status,
						"due": str(task.exp_end_date)[:10] if task.exp_end_date else None,
						"project": task.project,
					},
					"linked_task_missing": bool(doc.linked_task and not task),
				}
			)
		return out | {"success": True}
	except frappe.PermissionError:
		raise
	except Exception:
		frappe.logger("requests_v2").exception("detail")
		return {"success": False, "error": _("Could not load this request. Please try again.")}


# ---------------------------------------------------------------- raise form


@frappe.whitelist()
def get_form_options():
	"""What the "Raise a request" form offers this user. Same sources and rules as the current page:
	kinds from Request Type (read with the caller's own permissions; "Note" only for Dev Team),
	employees / assignable users / work tags through their existing endpoints, and the triage fields
	(Module, Priority) only for Dev Team and Projects Manager - api.requests.create_request drops
	them for everyone else anyway."""
	user, _privileged, employee = _check_access()
	roles = set(frappe.get_roles(user))
	can_note = "Dev Team" in roles
	triage = bool(roles & TRIAGE_FORM_ROLES)
	kinds = frappe.get_list("Request Type", pluck="name", order_by="creation asc", limit_page_length=0)
	return {
		"request_types": [k for k in kinds if can_note or k != "Note"],
		"triage_fields": triage,
		"product_areas": get_modules() if triage else [],
		"priorities": frappe.get_list(
			"Priority Level", pluck="name", order_by="sort_order asc", limit_page_length=0
		)
		if triage
		else [],
		"employees": [{"value": e.name, "label": e.employee_name or e.name} for e in get_employees()],
		"users": [{"value": u.name, "label": u.full_name or u.name} for u in get_assignable_users()],
		"tags": get_work_tags(),
		"my_employee": employee,
	}
