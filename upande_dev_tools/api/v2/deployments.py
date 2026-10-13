# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
"""Deployments v2 - read-only dashboard over Deployment Request / Instance / App.

ACCESS: same rule as the current endpoint api.deployments.get_recent_deployments, which is the
one the current page reads: Dev Team, System Manager or Projects Manager
(`DEPLOYMENT_VIEWER_ROLES`, imported from the current module so the two cannot drift). The
current page shows every request to those roles (no owner scoping), so v2 does too.

SECRETS: Deployment Instance rows hold a site URL and notes; Deployment Request carries copies
of the site URL and repository URL. None of those columns is ever selected here. Instances are
read as (name, environment_type) only, apps as (name, default_branch) only.

READ-ONLY: nothing here writes, commits, approves or starts a deployment.

DEFINITIONS (all computed on the server over the full filtered set)

  date        the day the request was raised (DATE(creation), site time zone, Africa/Nairobi).
              The range is inclusive: creation >= from 00:00 and < (to + 1 day) 00:00. An empty
              from/to means "no limit" on that side.
  stage       the one status a request is in right now. Mutually exclusive, so the parts add up:
                Declined          workflow Requested + approval Rejected (it will never start)
                Waiting approval  workflow Requested + raised in peak hours, approval Pending
                Requested         workflow Requested, free to start
                In Progress / Deployed / Failed   the workflow state
  open        Requested + Waiting approval + In Progress + Failed (needs someone's attention).
              Declined and Deployed are closed.
  finished    Deployed + Failed. A Failed request that is retried goes back to In Progress, so
              "failed" counts requests whose CURRENT state is Failed.
  success rate  Deployed / (Deployed + Failed). Requests still in flight (Requested, Waiting
              approval, In Progress) and Declined ones are NOT in the denominator.
  app         one app can exist under two spellings in Deployment App (upande-crm and
              upande_crm). Apps are grouped by name lower-cased with "-" read as "_"; the label
              shown is the spelling used most.
  age         now - creation, never negative (a request dated in the future shows 0 and is
              flagged in `notes.future_dated`).
  lead time   time from raised to deployed, only for requests whose Deployed transition is in
              the Version log (track_changes). There is no "deployed at" column: `modified`
              moves on every edit and was bulk-set by a data import, so it is NOT used.
              `lead_time.measured` says how many deployed requests could be measured.
  time to start  raised -> first move to In Progress, same source.

IDENTITIES (verified in tests/ and by hand, see the page report)
  total = sum(by_stage.count) = sum(by_app.raised) = sum(by_instance.raised)
        = sum(by_requester.raised) = sum(trend series, every group_by)
  open = Requested + Waiting approval + In Progress + Failed = len(open_queue) (unless capped)
  finished = deployed + failed;  success_rate = deployed / finished
"""

import datetime as _dt
import json
import statistics
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import add_days, cint, get_datetime, getdate, now_datetime

from upande_dev_tools.api.deployments import DEPLOYMENT_VIEWER_ROLES

ROW_LIMIT = 500
STAGES = ["Waiting approval", "Requested", "In Progress", "Failed", "Deployed", "Declined"]
OPEN_STAGES = ("Waiting approval", "Requested", "In Progress", "Failed")
GROUPS = ("stage", "instance", "app", "requester")
STALE_DAYS = 7
TOP_SERIES = 6

_STAGE_SQL = """(CASE
	WHEN r.workflow_state = 'Requested' AND r.approval_status = 'Rejected' THEN 'Declined'
	WHEN r.workflow_state = 'Requested' AND r.requires_approval = 1
		AND r.approval_status = 'Pending' THEN 'Waiting approval'
	ELSE r.workflow_state END)"""
_APP_SQL = "LOWER(REPLACE(r.app, '-', '_'))"
_REQ_SQL = "COALESCE(NULLIF(r.requested_by_user, ''), '')"


def _check_access():
	if not set(frappe.get_roles()) & DEPLOYMENT_VIEWER_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)


def _g(kw, key):
	return str(kw.get(key) or "").strip()


def _args(kw):
	def day(key):
		v = _g(kw, key)
		try:
			return getdate(v) if v else None
		except Exception:
			return None

	f, t = day("from_date"), day("to_date")
	if f and t and f > t:
		f, t = t, f
	return {
		"from_date": f,
		"to_date": t,
		"stage": _g(kw, "stage") if _g(kw, "stage") in STAGES else "",
		"instance": _g(kw, "instance"),
		"app": _g(kw, "app").lower().replace("-", "_"),
		"requester": _g(kw, "requester"),
		"q": _g(kw, "q")[:80],
	}


def _where(a, skip=()):
	cond, p = ["1=1"], {}
	if a["from_date"] and "date" not in skip:
		cond.append("r.creation >= %(from_dt)s")
		p["from_dt"] = str(a["from_date"]) + " 00:00:00"
	if a["to_date"] and "date" not in skip:
		cond.append("r.creation < %(to_dt)s")
		p["to_dt"] = str(add_days(a["to_date"], 1)) + " 00:00:00"
	if a["stage"] and "stage" not in skip:
		cond.append(_STAGE_SQL + " = %(stage)s")
		p["stage"] = a["stage"]
	if a["instance"] and "instance" not in skip:
		cond.append("r.instance = %(instance)s")
		p["instance"] = a["instance"]
	if a["app"] and "app" not in skip:
		cond.append(_APP_SQL + " = %(app)s")
		p["app"] = a["app"]
	if a["requester"] and "requester" not in skip:
		cond.append(_REQ_SQL + " = %(requester)s")
		p["requester"] = a["requester"]
	if a["q"] and "q" not in skip:
		cond.append(
			"(r.name LIKE %(q)s OR r.app LIKE %(q)s OR r.instance LIKE %(q)s OR r.branch LIKE %(q)s"
			" OR r.commit_hash LIKE %(q)s OR r.requested_by_user LIKE %(q)s)"
		)
		p["q"] = "%" + frappe.db.escape(a["q"], percent=False).strip("'") + "%"
	return " AND ".join(cond), p


_FROM = "FROM `tabDeployment Request` r"


def _display_names(rows):
	"""canonical app key -> the spelling used most (ties: the shorter, then alphabetical)."""
	count = defaultdict(lambda: defaultdict(int))
	for key, name, n in rows:
		count[key][name] += n
	return {k: sorted(v.items(), key=lambda x: (-x[1], len(x[0]), x[0]))[0][0] for k, v in count.items()}


def _app_names(where, p):
	rows = frappe.db.sql(
		f"SELECT {_APP_SQL}, r.app, COUNT(*) {_FROM} WHERE {where} AND r.app IS NOT NULL GROUP BY 1, 2",
		p,
	)
	return _display_names(rows)


def _users(names):
	names = [n for n in names if n]
	if not names:
		return {}
	rows = frappe.db.sql(
		"SELECT name, full_name FROM `tabUser` WHERE name IN %(n)s", {"n": tuple(names)}, as_dict=True
	)
	return {r.name: r.full_name or r.name for r in rows}


def _history(where, p):
	"""request name -> {started, deployed, failed_times, events[]} from the Version log."""
	rows = frappe.db.sql(
		f"""SELECT v.docname, v.creation, v.owner, v.data
		FROM `tabVersion` v INNER JOIN `tabDeployment Request` r ON r.name = v.docname
		WHERE v.ref_doctype = 'Deployment Request' AND v.data LIKE '%%workflow_state%%' AND {where}
		ORDER BY v.creation ASC""",
		p,
		as_dict=True,
	)
	out = defaultdict(lambda: {"events": [], "started": None, "deployed": None, "failed_times": 0})
	for v in rows:
		try:
			changed = json.loads(v.data).get("changed") or []
		except Exception:
			continue
		for ch in changed:
			if len(ch) >= 3 and ch[0] == "workflow_state":
				h = out[v.docname]
				h["events"].append({"when": v.creation, "by": v.owner, "from": ch[1], "to": ch[2]})
				if ch[2] == "In Progress" and not h["started"]:
					h["started"] = v.creation
				elif ch[2] == "Deployed":
					h["deployed"] = v.creation
				elif ch[2] == "Failed":
					h["failed_times"] += 1
	return out


def _hours(a, b):
	if not a or not b:
		return None
	h = (get_datetime(b) - get_datetime(a)).total_seconds() / 3600
	return round(h, 2) if h >= 0 else None


def _age_days(creation, now):
	return round(max(0.0, (now - get_datetime(creation)).total_seconds() / 86400), 2)


def _row(r, now, names, users, hist):
	h = hist.get(r["name"]) or {}
	return {
		"name": r["name"],
		"app": names.get(r["app_key"]) or r["app"] or "",
		"instance": r["instance"] or "",
		"branch": r["branch"] or "",
		"commit_hash": r["commit_hash"] or "",
		"stage": r["stage"],
		"workflow_state": r["workflow_state"],
		"pending_approval": bool(r["requires_approval"]) and r["approval_status"] == "Pending",
		"requested_by": r["requester"] or "",
		"requested_by_name": users.get(r["requester"]) or r["requester"] or "",
		"creation": str(r["creation"]),
		"age_days": _age_days(r["creation"], now),
		"future_dated": get_datetime(r["creation"]) > now,
		"lead_hours": _hours(r["creation"], h.get("deployed")) if r["stage"] == "Deployed" else None,
		"has_retried": bool(h.get("failed_times")),
	}


_COLS = f"""r.name, r.app, {_APP_SQL} AS app_key, r.instance, r.branch, r.commit_hash,
	{_STAGE_SQL} AS stage, r.workflow_state, r.requires_approval, r.approval_status,
	{_REQ_SQL} AS requester, r.creation"""


def _bucket(a, first, last):
	"""granularity + function date -> bucket start, for the trend chart."""
	span = (last - first).days
	if span <= 62:
		return "day", lambda d: d
	if span <= 400:
		return "week", lambda d: add_days(d, -d.weekday())
	return "month", lambda d: d.replace(day=1)


def _next(unit, d):
	if unit == "day":
		return add_days(d, 1)
	if unit == "week":
		return add_days(d, 7)
	return (d.replace(day=28) + _dt.timedelta(days=4)).replace(day=1)


def _label(unit, d, with_year=False):
	if unit == "month":
		return d.strftime("%b %Y")
	return d.strftime("%d %b %y" if with_year else "%d %b")


def _trend(a, where, p, group_by, names, users, now):
	expr = {"stage": _STAGE_SQL, "instance": "COALESCE(r.instance, '')", "app": _APP_SQL, "requester": _REQ_SQL}[
		group_by
	]
	rows = frappe.db.sql(
		f"SELECT DATE(r.creation) d, {expr} g, COUNT(*) n {_FROM} WHERE {where} GROUP BY 1, 2", p
	)
	if not rows:
		return {"unit": "day", "labels": [], "series": [], "group_by": group_by}
	first = a["from_date"] or min(r[0] for r in rows)
	last = a["to_date"] or max(r[0] for r in rows)
	first, last = min(first, min(r[0] for r in rows)), max(last, max(r[0] for r in rows))
	unit, start_of = _bucket(a, first, last)
	starts, d = [], start_of(first)
	while d <= last:
		starts.append(d)
		d = _next(unit, d)
	idx = {s: i for i, s in enumerate(starts)}
	per = defaultdict(lambda: [0] * len(starts))
	tot = defaultdict(int)
	for day, g, n in rows:
		per[g][idx[start_of(day)]] += n
		tot[g] += n
	if group_by == "stage":
		keys = [s for s in STAGES if s in per]
	else:
		keys = [k for k, _n in sorted(tot.items(), key=lambda x: (-x[1], str(x[0])))]
	label = {
		"stage": lambda k: k,
		"instance": lambda k: k or "No instance",
		"app": lambda k: names.get(k) or k or "No app",
		"requester": lambda k: users.get(k) or k or "Unknown",
	}[group_by]
	series = [{"key": k, "label": label(k), "total": tot[k], "data": per[k]} for k in keys[:TOP_SERIES]]
	rest = keys[TOP_SERIES:]
	if rest:
		series.append(
			{
				"key": "__other__",
				"label": "Other (%d)" % len(rest),
				"total": sum(tot[k] for k in rest),
				"data": [sum(per[k][i] for k in rest) for i in range(len(starts))],
			}
		)
	return {
		"unit": unit,
		"group_by": group_by,
		"labels": [_label(unit, s, starts[0].year != starts[-1].year) for s in starts],
		"starts": [str(s) for s in starts],
		"series": series,
	}


def _breakdown(where, p, expr, label_of, extra_group=None):
	rows = frappe.db.sql(
		f"""SELECT {expr} k,
			SUM(1) raised,
			SUM({_STAGE_SQL} = 'Deployed') deployed,
			SUM({_STAGE_SQL} = 'Failed') failed,
			SUM({_STAGE_SQL} IN ('Waiting approval','Requested','In Progress','Failed')) open_n,
			MAX(r.creation) last_raised
		{_FROM} WHERE {where} GROUP BY 1""",
		p,
		as_dict=True,
	)
	out = []
	for r in rows:
		fin = cint(r.deployed) + cint(r.failed)
		out.append(
			{
				"key": r.k or "",
				"label": label_of(r.k or ""),
				"raised": cint(r.raised),
				"deployed": cint(r.deployed),
				"failed": cint(r.failed),
				"open": cint(r.open_n),
				"success_rate": round(100.0 * cint(r.deployed) / fin, 1) if fin else None,
				"last_raised": str(r.last_raised) if r.last_raised else None,
			}
		)
	out.sort(key=lambda x: (-x["raised"], x["label"].lower()))
	return out


def _options():
	apps = frappe.db.sql(
		f"SELECT {_APP_SQL}, r.app, COUNT(*) {_FROM} WHERE r.app IS NOT NULL GROUP BY 1, 2"
	)
	disp = _display_names(apps)
	registry = frappe.db.sql("SELECT name FROM `tabDeployment App`", pluck=True)
	reg_groups = defaultdict(list)
	for n in registry:
		reg_groups[n.lower().replace("-", "_")].append(n)
		disp.setdefault(n.lower().replace("-", "_"), n)
	instances = frappe.db.sql(
		"SELECT name, environment_type FROM `tabDeployment Instance` ORDER BY name", as_dict=True
	)
	reqs = frappe.db.sql(f"SELECT DISTINCT {_REQ_SQL} {_FROM}", pluck=True)
	users = _users(reqs)
	return {
		"apps": sorted(
			[{"value": k, "label": v} for k, v in disp.items()], key=lambda x: x["label"].lower()
		),
		"instances": [{"value": i.name, "label": i.name, "environment": i.environment_type} for i in instances],
		"requesters": sorted(
			[{"value": u, "label": users.get(u) or u} for u in reqs if u], key=lambda x: x["label"].lower()
		),
		"stages": STAGES,
		"duplicate_registry_apps": sorted(
			[sorted(v) for v in reg_groups.values() if len(v) > 1], key=lambda x: x[0].lower()
		),
	}


@frappe.whitelist()
def get_deployments(**kw):
	"""Everything the Deployments v2 page shows, for one filter set (see module docstring)."""
	_check_access()
	a = _args(kw)
	group_by = _g(kw, "group_by") if _g(kw, "group_by") in GROUPS else "stage"
	where, p = _where(a)
	now = now_datetime()

	names = _app_names(where, p)
	by_stage_rows = frappe.db.sql(
		f"SELECT {_STAGE_SQL} s, COUNT(*) {_FROM} WHERE {where} GROUP BY 1", p
	)
	counts = {s: 0 for s in STAGES}
	for s, n in by_stage_rows:
		counts[s] = counts.get(s, 0) + cint(n)
	total = sum(counts.values())
	n_open = sum(counts[s] for s in OPEN_STAGES)
	finished = counts["Deployed"] + counts["Failed"]

	rows = frappe.db.sql(
		f"SELECT {_COLS} {_FROM} WHERE {where} ORDER BY r.creation DESC, r.name DESC LIMIT %(lim)s",
		{**p, "lim": ROW_LIMIT},
		as_dict=True,
	)
	open_rows = frappe.db.sql(
		f"""SELECT {_COLS} {_FROM}
		WHERE {where} AND {_STAGE_SQL} IN ('Waiting approval','Requested','In Progress','Failed')
		ORDER BY r.creation ASC, r.name ASC LIMIT %(lim)s""",
		{**p, "lim": ROW_LIMIT},
		as_dict=True,
	)
	hist = _history(where, p)
	users = _users({r["requester"] for r in rows + open_rows} | {x for x in [a["requester"]] if x})

	leads, starts, retried = [], [], 0
	deployed_names = frappe.db.sql(
		f"SELECT r.name, r.creation {_FROM} WHERE {where} AND {_STAGE_SQL} = 'Deployed'", p
	)
	for name, created in deployed_names:
		lh = _hours(created, (hist.get(name) or {}).get("deployed"))
		if lh is not None:
			leads.append(lh)
	start_rows = frappe.db.sql(f"SELECT r.name, r.creation {_FROM} WHERE {where}", p)
	for name, created in start_rows:
		h = hist.get(name)
		if h:
			sh = _hours(created, h.get("started"))
			if sh is not None:
				starts.append(sh)
			if h["failed_times"]:
				retried += 1

	def agg(xs):
		return (
			{"measured": len(xs), "median_hours": round(statistics.median(xs), 2), "mean_hours": round(sum(xs) / len(xs), 2), "max_hours": round(max(xs), 2)}
			if xs
			else {"measured": 0, "median_hours": None, "mean_hours": None, "max_hours": None}
		)

	open_ages = [_age_days(r["creation"], now) for r in open_rows]
	stale = frappe.db.sql(
		f"""SELECT COUNT(*) {_FROM} WHERE {where} AND {_STAGE_SQL} = 'In Progress'
		AND r.creation < %(stale)s""",
		{**p, "stale": add_days(now, -STALE_DAYS)},
	)[0][0]
	stale_wait = frappe.db.sql(
		f"""SELECT COUNT(*) {_FROM} WHERE {where} AND {_STAGE_SQL} = 'Waiting approval'
		AND r.creation < %(stale)s""",
		{**p, "stale": add_days(now, -STALE_DAYS)},
	)[0][0]
	future = frappe.db.sql(
		f"SELECT r.name, r.creation {_FROM} WHERE {where} AND r.creation > %(now)s ORDER BY r.creation LIMIT 20",
		{**p, "now": now},
	)
	no_commit = frappe.db.sql(
		f"""SELECT COUNT(*) {_FROM} WHERE {where} AND {_STAGE_SQL} = 'Deployed'
		AND (r.commit_hash IS NULL OR r.commit_hash = '')""",
		p,
	)[0][0]
	no_deployer = frappe.db.sql(
		f"""SELECT COUNT(*) {_FROM} WHERE {where} AND {_STAGE_SQL} = 'Deployed'
		AND (r.deployed_by_user IS NULL OR r.deployed_by_user = '')""",
		p,
	)[0][0]

	by_app = _breakdown(where, p, _APP_SQL, lambda k: names.get(k) or k or "No app")
	by_instance = _breakdown(where, p, "COALESCE(r.instance, '')", lambda k: k or "No instance")
	req_rows = _breakdown(where, p, _REQ_SQL, lambda k: k)
	rq_users = _users([x["key"] for x in req_rows])
	for x in req_rows:
		x["label"] = rq_users.get(x["key"]) or x["key"] or "Unknown"
	by_stage = [{"stage": s, "count": counts[s]} for s in STAGES]

	trend = _trend(a, where, p, group_by, names, {**users, **rq_users}, now)
	req_users = {**users, **rq_users}
	table = [_row(r, now, names, req_users, hist) for r in rows]
	queue = [_row(r, now, names, req_users, hist) for r in open_rows]

	return {
		"success": True,
		"filters": {k: (str(v) if v is not None else "") for k, v in a.items()},
		"totals": {
			"raised": total,
			"open": n_open,
			"waiting_approval": counts["Waiting approval"],
			"in_progress": counts["In Progress"],
			"deployed": counts["Deployed"],
			"failed": counts["Failed"],
			"declined": counts["Declined"],
			"finished": finished,
			"in_flight": counts["Waiting approval"] + counts["Requested"] + counts["In Progress"],
			"success_rate": round(100.0 * counts["Deployed"] / finished, 1) if finished else None,
			"oldest_open_days": max(open_ages) if open_ages else None,
			"avg_open_age_days": round(sum(open_ages) / len(open_ages), 1) if open_ages else None,
			"retried": retried,
		},
		"lead_time": {**agg(leads), "deployed": counts["Deployed"]},
		"time_to_start": agg(starts),
		"by_stage": by_stage,
		"by_app": by_app,
		"by_instance": by_instance,
		"by_requester": req_rows,
		"trend": trend,
		"requests": table,
		"open_queue": queue,
		"truncated": total > ROW_LIMIT,
		"open_truncated": n_open > ROW_LIMIT,
		"row_limit": ROW_LIMIT,
		"notes": {
			"stale_in_progress": cint(stale),
			"stale_waiting_approval": cint(stale_wait),
			"stale_days": STALE_DAYS,
			"future_dated": [{"name": n, "creation": str(c)} for n, c in future],
			"deployed_without_commit": cint(no_commit),
			"deployed_without_deployer": cint(no_deployer),
		},
		"options": _options(),
	}


@frappe.whitelist()
def get_deployment_instances(**kw):
	"""Per instance: current state from the whole history (date and stage filters are ignored on
	purpose: "what is on the instance now" does not depend on a reporting range). Follows the
	app and instance filters. Latest deployed request per app, duplicate-spelling flags."""
	_check_access()
	a = _args(kw)
	a.update(from_date=None, to_date=None, stage="", requester="", q="")
	where, p = _where(a)
	now = now_datetime()
	inst = frappe.db.sql(
		"SELECT name, environment_type FROM `tabDeployment Instance` ORDER BY name", as_dict=True
	)
	if a["instance"]:
		inst = [i for i in inst if i.name == a["instance"]]
	rows = frappe.db.sql(
		f"""SELECT r.name, r.app, {_APP_SQL} app_key, r.instance, r.branch, r.commit_hash,
			{_STAGE_SQL} stage, r.creation, LEAST(r.creation, %(now)s) eff {_FROM}
		WHERE {where} ORDER BY eff DESC, r.name DESC""",
		{**p, "now": now},
		as_dict=True,
	)
	names = _display_names([(r.app_key, r.app, 1) for r in rows if r.app])
	by_inst = defaultdict(list)
	for r in rows:
		by_inst[r.instance or ""].append(r)
	out = []
	for i in inst:
		rs = by_inst.get(i.name, [])
		apps = {}
		spell = defaultdict(set)
		for r in rs:
			if r.app:
				spell[r.app_key].add(r.app)
			if r.stage != "Deployed" or not r.app:
				continue
			ap = apps.setdefault(
				r.app_key,
				{
					"app": names.get(r.app_key) or r.app,
					"key": r.app_key,
					"deployed_count": 0,
					"latest": {
						"name": r.name,
						"branch": r.branch or "",
						"commit_hash": r.commit_hash or "",
						"creation": str(r.creation),
						"future_dated": get_datetime(r.creation) > now,
					},
				},
			)
			ap["deployed_count"] += 1
		last = next((r for r in rs if r.stage == "Deployed"), None)
		open_n = sum(1 for r in rs if r.stage in OPEN_STAGES)
		out.append(
			{
				"name": i.name,
				"environment": i.environment_type or "",
				"requests": len(rs),
				"deployed": sum(1 for r in rs if r.stage == "Deployed"),
				"failed": sum(1 for r in rs if r.stage == "Failed"),
				"open": open_n,
				"last_deployed": (
					{
						"name": last.name,
						"app": names.get(last.app_key) or last.app,
						"creation": str(last.creation),
						"future_dated": get_datetime(last.creation) > now,
					}
					if last
					else None
				),
				"apps": sorted(apps.values(), key=lambda x: x["app"].lower()),
				"duplicate_spellings": sorted(
					[sorted(v) for v in spell.values() if len(v) > 1], key=lambda x: x[0].lower()
				),
			}
		)
	return {"success": True, "instances": out}


@frappe.whitelist()
def get_deployment_request(name=None):
	"""One request with its timeline. Secrets (site / repository URLs, instance notes) are never read."""
	_check_access()
	name = str(name or "").strip()
	row = frappe.db.sql(
		f"""SELECT r.name, r.app, r.instance, r.branch, r.commit_hash, r.workflow_state,
			{_STAGE_SQL} stage, r.requires_approval, r.approval_status, r.approved_by, r.approved_on,
			r.approval_note, r.requested_by_user, r.deployed_by_user, r.linked_request,
			r.description, r.errors, r.fix_notes, r.creation, r.modified {_FROM} WHERE r.name = %(n)s""",
		{"n": name},
		as_dict=True,
	)
	if not row:
		return {"success": False, "error": _("That deployment request was not found.")}
	r = row[0]
	now = now_datetime()
	hist = _history("r.name = %(n)s", {"n": name}).get(name) or {"events": []}
	people = _users([r.requested_by_user, r.approved_by, r.deployed_by_user] + [e["by"] for e in hist["events"]])
	who = lambda u: (people.get(u) or u) if u else ""  # noqa: E731

	timeline = [{"when": str(r.creation), "what": "Request raised", "by": who(r.requested_by_user)}]
	if r.requires_approval:
		timeline.append(
			{"when": str(r.creation), "what": "Raised in peak hours: approval needed", "by": ""}
		)
	if r.approved_on:
		timeline.append(
			{
				"when": str(r.approved_on),
				"what": "Approval " + (r.approval_status or "").lower(),
				"by": who(r.approved_by),
				"note": (r.approval_note or "")[:500],
			}
		)
	for e in hist["events"]:
		timeline.append(
			{"when": str(e["when"]), "what": "%s to %s" % (e["from"], e["to"]), "by": who(e["by"])}
		)
	timeline.sort(key=lambda x: x["when"])

	app = frappe.db.get_value("Deployment App", r.app, ["name", "default_branch"], as_dict=True) if r.app else None
	env = frappe.db.get_value("Deployment Instance", r.instance, "environment_type") if r.instance else None
	linked = None
	if r.linked_request:
		linked = frappe.db.get_value(
			"Request", r.linked_request, ["name", "title", "workflow_state", "request_type"], as_dict=True
		)
	sibling_rows = frappe.db.sql(
		f"""SELECT r.name, {_STAGE_SQL} stage, r.branch, r.commit_hash, r.creation {_FROM}
		WHERE r.instance = %(i)s AND {_APP_SQL} = %(a)s AND r.name != %(n)s
		ORDER BY r.creation DESC LIMIT 6""",
		{"i": r.instance, "a": (r.app or "").lower().replace("-", "_"), "n": name},
		as_dict=True,
	)
	strip = frappe.utils.strip_html_tags
	return {
		"success": True,
		"request": {
			"name": r.name,
			"app": r.app or "",
			"app_default_branch": (app or {}).get("default_branch") or "",
			"instance": r.instance or "",
			"environment": env or "",
			"branch": r.branch or "",
			"commit_hash": r.commit_hash or "",
			"stage": r.stage,
			"workflow_state": r.workflow_state,
			"requires_approval": cint(r.requires_approval),
			"pending_approval": bool(r.requires_approval) and r.approval_status == "Pending",
			"approval_status": r.approval_status or "",
			"requested_by": who(r.requested_by_user) or "",
			"deployed_by": who(r.deployed_by_user) or "",
			"creation": str(r.creation),
			"modified": str(r.modified),
			"age_days": _age_days(r.creation, now),
			"future_dated": get_datetime(r.creation) > now,
			"description": strip(r.description or "")[:2000],
			"errors": (r.errors or "")[:2000],
			"fix_notes": (r.fix_notes or "")[:2000],
			"lead_hours": _hours(r.creation, hist.get("deployed")) if r.stage == "Deployed" else None,
			"start_hours": _hours(r.creation, hist.get("started")),
			"linked_request": dict(linked) if linked else None,
			"linked_request_name": r.linked_request or "",
		},
		"timeline": timeline,
		"history_known": bool(hist["events"]),
		"same_app_on_instance": [
			{"name": s.name, "stage": s.stage, "branch": s.branch or "", "commit_hash": s.commit_hash or "", "creation": str(s.creation)}
			for s in sibling_rows
		],
	}
