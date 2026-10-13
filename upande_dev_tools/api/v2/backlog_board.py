# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
"""Backlog Board v2 - read model of the Dev Tools board: Tasks, Issues and Requests in one list.

This module only READS. Every write the page makes (move, create, edit, reassign, delete,
bulk edit) calls the existing whitelisted endpoints in api/board.py and api/requests.py, so
their permission checks, validation and side effects stay exactly as they are.

WHAT IS ON THE BOARD (same scope as api.board.get_board)
    - With no project chosen: Tasks, Issues and Requests whose project has Project Type
      "Dev Tools". Work with no project is not on the board (e.g. Requests not yet
      assigned a project) - the page says how many.
    - With a project chosen: that project's items; the caller needs read permission on it.

ONE PIECE OF WORK = ONE ITEM
    A Request that has been scheduled gets a Task (Request.linked_task <-> Task.custom_request).
    The current board lists both, so that work is counted twice. v2 counts it once, as the
    Task, and says how many Requests were folded into their Task. `include_linked=1` shows
    both again. A Request is only folded away when its Task is itself on the board (same
    project scope), so nothing disappears.

STAGES (columns) - the current page's mapping, with one change
    Task    Open/Template->Todo  Working/Overdue->In Progress  Pending Review->In Review
            Completed->Done      Cancelled->Dropped   (was Done)
    Issue   Open->Triage  Replied->In Progress  On Hold->Blocked  Resolved/Closed->Done
    Request ""/Under Review->Triage  Approved/Scheduled->Todo  In Progress->In Progress
            Deferred->Blocked  Completed/Closed->Done  Rejected/Withdrawn->Dropped (was Done)
    "Dropped" = work that ended without being done, so it no longer inflates "Done".
    Status values not in the table are shown in the Task=Todo / Issue,Request=Triage column
    (as the current page does) and counted in `notes.unmapped`.

OVERDUE
    overdue = has a due date AND due date < today (site date) AND stage not in (Done, Dropped).
    Task due = exp_end_date; Issue due = date part of sla_resolution_by; Requests have no due
    date and are never overdue. Today is the site's own today (frappe.utils.today()).

IDENTITIES (verified in tests/test_backlog_board_v2.py and by the page)
    total = sum(stage counts) = sum(kind counts)            (every item has one stage, one kind)
    open  = total - done - dropped
    kpis follow every filter: they are computed in SQL over the full filtered set, never over
    the capped row list. `items` is capped at ROW_LIMIT (truncated: true when it is).
    Assignee counts in the filter list add up to more than the total on purpose: an item
    with two assignees counts once for each.

PERMISSIONS (identical to the current endpoints)
    get_board is open to any logged-in user (Dev Portal Page "backlog-board" is open to All);
    a specific project needs frappe.has_permission("Project", "read"). The row data returned
    here is the same set of fields get_board returns. Everything get_preview guards behind
    BOARD_ROLES (description, who raised it, history, comments, linked documents) is behind
    is_board_role() here too. Nothing here writes or commits.
"""

import json
import re

import frappe
from frappe import _
from frappe.utils import getdate, today

from upande_dev_tools.api.board import (
	ISSUE_STAGE,
	REQUEST_STAGE,
	STAGES,
	TASK_STAGE,
	is_board_role,
)
from upande_dev_tools.setup import DEV_TOOLS_PROJECT_TYPE

ROW_LIMIT = 2000
DONE_STAGES = ("Done", "Dropped")
ALL_STAGES = [*STAGES, "Dropped"]
NONE = "__none__"

# Stage per native status, per doctype. Dropped is the one change from the current page.
_TASK = {**TASK_STAGE, "Cancelled": "Dropped"}
_ISSUE = dict(ISSUE_STAGE)
_REQUEST = {**REQUEST_STAGE, "Rejected": "Dropped", "Withdrawn": "Dropped"}
_DEFAULT = {"Task": "Todo", "Issue": "Triage", "Request": "Triage"}
_MAPS = {"Task": _TASK, "Issue": _ISSUE, "Request": _REQUEST}
KINDS = ("Task", "Issue", "Request")


def _stage_case(kind: str, col: str) -> str:
	esc = frappe.db.escape
	whens = " ".join(f"WHEN {esc(s)} THEN {esc(st)}" for s, st in _MAPS[kind].items())
	return f"CASE {col} {whens} ELSE {esc(_DEFAULT[kind])} END"


def _err(msg):
	return {"success": False, "error": msg}


def _text(v) -> str:
	return str(v or "").strip()


# ---------------------------------------------------------------- scope + SQL


def _scope(project: str):
	"""(project ids list, error). Same rule as get_board."""
	if project:
		if not frappe.db.exists("Project", project):
			return None, _("That project does not exist.")
		if not frappe.has_permission("Project", "read", project):
			return None, _("Not permitted to view this project.")
		return [project], None
	ids = frappe.get_all(
		"Project", filters={"project_type": DEV_TOOLS_PROJECT_TYPE}, pluck="name", ignore_permissions=True
	)
	return ids or [""], None


def _union(include_linked: bool, ids: list):
	"""The three doctypes as one derived table `u`, scoped to project ids (params returned)."""
	marks = ", ".join(["%s"] * len(ids))
	dedupe = (
		""
		if include_linked
		else f"""AND NOT EXISTS (SELECT 1 FROM `tabTask` t2 WHERE t2.name = r.linked_task
			AND t2.project IN ({marks}))"""
	)
	sql = f"""(
	SELECT 'Task' AS kind, t.name, t.subject AS title, t.status, {_stage_case("Task", "t.status")} AS stage,
		t.priority, t.project, t.custom_module AS module, DATE(t.exp_start_date) AS start_date,
		DATE(t.exp_end_date) AS due_date, t._assign AS assign, t.custom_request AS linked,
		t.creation, t.modified, t.owner
	FROM `tabTask` t WHERE t.project IN ({marks})
	UNION ALL
	SELECT 'Issue', i.name, i.subject, i.status, {_stage_case("Issue", "i.status")},
		i.priority, i.project, i.custom_module, DATE(i.opening_date),
		DATE(i.sla_resolution_by), i._assign, NULL, i.creation, i.modified, i.owner
	FROM `tabIssue` i WHERE i.project IN ({marks})
	UNION ALL
	SELECT 'Request', r.name, r.title, COALESCE(NULLIF(r.workflow_state, ''), 'Requested'),
		{_stage_case("Request", "COALESCE(r.workflow_state, '')")},
		r.priority, r.project, r.product_area, NULL, NULL, r._assign, r.linked_task,
		r.creation, r.modified, r.owner
	FROM `tabRequest` r WHERE r.project IN ({marks}) {dedupe}
	) u"""
	params = list(ids) * (3 if include_linked else 4)
	return sql, params


def _like(s: str) -> str:
	return "%" + s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _where(a: dict, skip: tuple = ()):
	"""Filter fragments over derived table u. Returns (sql, params)."""
	w, p = [], []
	if a["kind"] and "kind" not in skip:
		w.append("u.kind = %s")
		p.append(a["kind"])
	stage = a["stage"]
	if stage and "stage" not in skip:
		if stage == "open":
			w.append("u.stage NOT IN ('Done', 'Dropped')")
		else:
			w.append("u.stage = %s")
			p.append(stage)
	if a["priority"] and "priority" not in skip:
		if a["priority"] == NONE:
			w.append("(u.priority IS NULL OR u.priority = '')")
		else:
			w.append("u.priority = %s")
			p.append(a["priority"])
	if a["module"] and "module" not in skip:
		if a["module"] == NONE:
			w.append("(u.module IS NULL OR u.module = '')")
		else:
			w.append("u.module = %s")
			p.append(a["module"])
	if a["assignee"] and "assignee" not in skip:
		if a["assignee"] == NONE:
			w.append("(u.assign IS NULL OR u.assign IN ('', '[]'))")
		else:
			w.append("u.assign LIKE %s")
			p.append(_like('"' + a["assignee"] + '"'))
	if a["tag"] and "tag" not in skip:
		w.append(
			"EXISTS (SELECT 1 FROM `tabTag Link` tl WHERE tl.document_type = u.kind "
			"AND tl.document_name = u.name AND tl.tag = %s)"
		)
		p.append(a["tag"])
	if a["q"] and "q" not in skip:
		w.append("(u.title LIKE %s OR u.name LIKE %s)")
		p += [_like(a["q"]), _like(a["q"])]
	due = a["due"]
	if due and "due" not in skip:
		t = a["today"]
		if due == "overdue":
			w.append("(u.due_date < %s AND u.stage NOT IN ('Done', 'Dropped'))")
			p.append(t)
		elif due == "today":
			w.append("u.due_date = %s")
			p.append(t)
		elif due == "week":
			w.append("u.due_date BETWEEN %s AND DATE_ADD(%s, INTERVAL 7 DAY)")
			p += [t, t]
		elif due == "month":
			w.append("u.due_date BETWEEN %s AND DATE_ADD(%s, INTERVAL 30 DAY)")
			p += [t, t]
		elif due == "none":
			w.append("u.due_date IS NULL")
	if a["from_date"] and "dates" not in skip:
		w.append("u.due_date >= %s")
		p.append(a["from_date"])
	if a["to_date"] and "dates" not in skip:
		w.append("u.due_date <= %s")
		p.append(a["to_date"])
	return (" AND ".join(w) or "1=1"), p


def _args(kw: dict) -> dict:
	g = lambda k: _text(kw.get(k))  # noqa: E731

	def d(k):
		v = g(k)
		try:
			return str(getdate(v)) if v else ""
		except Exception:
			return ""

	f, t = d("from_date"), d("to_date")
	if f and t and f > t:
		f, t = t, f
	kind = g("kind")
	stage = g("stage")
	due = g("due")
	return {
		"project": g("project"),
		"kind": kind if kind in KINDS else "",
		"stage": stage if stage == "open" or stage in ALL_STAGES else "",
		"priority": g("priority"),
		"module": g("module"),
		"assignee": g("assignee"),
		"tag": g("tag"),
		"q": g("q")[:100],
		"due": due if due in ("overdue", "today", "week", "month", "none") else "",
		"from_date": f,
		"to_date": t,
		"include_linked": g("include_linked") in ("1", "true", "True"),
		"today": str(getdate(today())),
	}


def _priority_order() -> list:
	return frappe.get_all("Priority Level", order_by="sort_order asc", pluck="name")


def _assignees(emails: set) -> dict:
	if not emails:
		return {}
	rows = frappe.get_all("User", filters={"name": ["in", list(emails)]}, fields=["name", "full_name"])
	return {r.name: r.full_name or r.name for r in rows}


def _loads(v) -> list:
	try:
		out = json.loads(v) if v else []
		return [str(x) for x in out] if isinstance(out, list) else []
	except ValueError:
		return []


# ---------------------------------------------------------------- the board


@frappe.whitelist()
def get_backlog(
	project: str | None = None,
	kind: str | None = None,
	stage: str | None = None,
	priority: str | None = None,
	module: str | None = None,
	assignee: str | None = None,
	tag: str | None = None,
	q: str | None = None,
	due: str | None = None,
	from_date: str | None = None,
	to_date: str | None = None,
	include_linked: str | None = None,
) -> dict:
	"""Everything the page needs in one call: KPIs, stage columns, rows and filter options."""
	if frappe.session.user == "Guest":
		return _err(_("Please sign in."))
	a = _args(locals())
	ids, err = _scope(a["project"])
	if err:
		return _err(err)
	usql, uparams = _union(a["include_linked"], ids)
	wsql, wparams = _where(a)
	order = _priority_order()
	rank = (
		"CASE u.priority "
		+ " ".join(f"WHEN {frappe.db.escape(n)} THEN {i + 1}" for i, n in enumerate(order))
		+ " ELSE 0 END"
	)
	unassigned = "(u.assign IS NULL OR u.assign IN ('', '[]'))"
	late = "(u.due_date < %s AND u.stage NOT IN ('Done', 'Dropped'))"

	# 1. every roll-up from ONE grouped query over the full filtered set
	groups = frappe.db.sql(
		f"""SELECT u.kind, u.stage, COUNT(*) n, SUM({late}) late,
			SUM({unassigned} AND u.stage NOT IN ('Done', 'Dropped')) unassigned_open
		FROM {usql} WHERE {wsql} GROUP BY u.kind, u.stage""",
		[a["today"], *uparams, *wparams],
		as_dict=True,
	)
	by_stage = {s: {"stage": s, "count": 0, "late": 0} for s in ALL_STAGES}
	by_kind = {k: 0 for k in KINDS}
	total = late_n = unassigned_n = 0
	for g in groups:
		n = int(g.n)
		total += n
		by_kind[g.kind] += n
		by_stage[g.stage]["count"] += n
		by_stage[g.stage]["late"] += int(g.late or 0)
		late_n += int(g.late or 0)
		unassigned_n += int(g.unassigned_open or 0)
	done = by_stage["Done"]["count"]
	dropped = by_stage["Dropped"]["count"]

	# 2. the rows, filtered in SQL before the cap
	rows = frappe.db.sql(
		f"""SELECT u.kind, u.name, u.title, u.status, u.stage, u.priority, u.project, u.module,
			u.start_date, u.due_date, u.assign, u.linked, u.modified, u.owner,
			({late}) AS late, {rank} AS prank
		FROM {usql} WHERE {wsql}
		ORDER BY prank DESC, u.due_date IS NULL, u.due_date, u.title
		LIMIT {ROW_LIMIT}""",
		[a["today"], *uparams, *wparams],
		as_dict=True,
	)
	emails = set()
	for r in rows:
		r["assignee_ids"] = _loads(r.pop("assign"))
		r["own"] = r.pop("owner") == frappe.session.user
		emails.update(r["assignee_ids"])
	names = _assignees(emails)
	_attach_tags(rows)
	items = [
		{
			"kind": r.kind,
			"name": r.name,
			"title": r.title,
			"status": r.status,
			"stage": r.stage,
			"priority": r.priority or "",
			"project": r.project,
			"module": r.module or "",
			"start": str(r.start_date) if r.start_date else "",
			"due": str(r.due_date) if r.due_date else "",
			"late": bool(r.late),
			"assignee_ids": r.assignee_ids,
			"assignees": [names.get(e, e) for e in r.assignee_ids],
			"tags": r.tags,
			"linked": r.linked or "",
			"modified": str(r.modified),
			"own": r.own,
		}
		for r in rows
	]

	return {
		"success": True,
		"today": a["today"],
		"row_limit": ROW_LIMIT,
		"truncated": total > len(items),
		"kpis": {
			"total": total,
			"open": total - done - dropped,
			"done": done,
			"dropped": dropped,
			"overdue": late_n,
			"unassigned_open": unassigned_n,
		},
		"stages": [by_stage[s] for s in ALL_STAGES],
		"kinds": by_kind,
		"items": items,
		"options": _options(a, usql, uparams, order),
		"notes": _notes(a, ids, usql, uparams),
	}


def _attach_tags(rows: list) -> None:
	for r in rows:
		r["tags"] = []
	if not rows:
		return
	by = {}
	for kind in KINDS:
		names = [r.name for r in rows if r.kind == kind]
		if not names:
			continue
		for t in frappe.get_all(
			"Tag Link",
			filters={"document_type": kind, "document_name": ["in", names]},
			fields=["document_name", "tag"],
			limit=50000,
		):
			by.setdefault((kind, t.document_name), []).append(t.tag)
	for r in rows:
		r["tags"] = sorted(by.get((r.kind, r.name), []))


def _options(a, usql, uparams, order) -> dict:
	"""Filter lists from the whole project scope (not narrowed by the other filters)."""
	areas = frappe.db.sql(
		f"SELECT u.module, COUNT(*) n FROM {usql} WHERE u.module IS NOT NULL AND u.module <> '' "
		"GROUP BY u.module ORDER BY u.module",
		uparams,
	)
	tags = frappe.db.sql(
		f"""SELECT tl.tag, COUNT(*) n FROM `tabTag Link` tl
		JOIN {usql} ON u.kind = tl.document_type AND u.name = tl.document_name
		GROUP BY tl.tag ORDER BY tl.tag""",
		uparams,
	)
	assigns = frappe.db.sql(f"SELECT u.assign, COUNT(*) FROM {usql} GROUP BY u.assign", uparams)
	counts: dict = {}
	for raw, n in assigns:
		for e in _loads(raw):
			counts[e] = counts.get(e, 0) + int(n)
	names = _assignees(set(counts))
	people = sorted(
		({"value": e, "label": names.get(e, e), "count": c} for e, c in counts.items()),
		key=lambda x: x["label"].lower(),
	)
	opts = {
		"priorities": order,
		"areas": [{"value": r[0], "count": int(r[1])} for r in areas],
		"tags": [{"value": r[0], "count": int(r[1])} for r in tags],
		"assignees": people,
		"projects": [],
	}
	if is_board_role():
		opts["projects"] = frappe.get_all(
			"Project",
			filters={"project_type": DEV_TOOLS_PROJECT_TYPE},
			fields=["name", "project_name"],
			order_by="project_name asc",
			ignore_permissions=True,
		)
	elif a["project"]:
		opts["projects"] = [{"name": a["project"], "project_name": a["project"]}]
	return opts


def _notes(a, ids, usql, uparams) -> dict:
	"""Counts that explain differences from the old board or from the raw tables."""
	notes = {"folded_requests": 0, "no_project_requests": 0, "unmapped": []}
	if not a["include_linked"]:
		marks = ", ".join(["%s"] * len(ids))
		notes["folded_requests"] = int(
			frappe.db.sql(
				f"""SELECT COUNT(*) FROM `tabRequest` r WHERE r.project IN ({marks})
				AND EXISTS (SELECT 1 FROM `tabTask` t2 WHERE t2.name = r.linked_task
					AND t2.project IN ({marks}))""",
				[*ids, *ids],
			)[0][0]
		)
	if not a["project"]:
		notes["no_project_requests"] = int(
			frappe.db.sql("SELECT COUNT(*) FROM `tabRequest` WHERE project IS NULL OR project = ''")[0][0]
		)
	for kind, col, table in (
		("Task", "status", "tabTask"),
		("Issue", "status", "tabIssue"),
		("Request", "workflow_state", "tabRequest"),
	):
		known = [*_MAPS[kind].keys(), ""]
		marks = ", ".join(["%s"] * len(known))
		pmarks = ", ".join(["%s"] * len(ids))
		rows = frappe.db.sql(
			f"""SELECT COALESCE({col}, ''), COUNT(*) FROM `{table}`
			WHERE project IN ({pmarks}) AND COALESCE({col}, '') NOT IN ({marks}) GROUP BY 1""",
			[*ids, *known],
		)
		notes["unmapped"] += [{"kind": kind, "status": r[0], "count": int(r[1])} for r in rows]
	return notes


# ---------------------------------------------------------------- drill-down

_TABLE = {
	"Task": (
		"tabTask",
		"subject",
		"status",
		"custom_module",
		"exp_start_date",
		"exp_end_date",
		"custom_request",
	),
	"Issue": (
		"tabIssue",
		"subject",
		"status",
		"custom_module",
		"opening_date",
		"DATE(sla_resolution_by)",
		"NULL",
	),
	"Request": (
		"tabRequest",
		"title",
		"COALESCE(NULLIF(workflow_state,''),'Requested')",
		"product_area",
		"NULL",
		"NULL",
		"linked_task",
	),
}


def _project_visible(project) -> bool:
	if not project:
		return False
	ptype = frappe.db.get_value("Project", project, "project_type")
	return ptype == DEV_TOOLS_PROJECT_TYPE or bool(frappe.has_permission("Project", "read", project))


@frappe.whitelist()
def get_backlog_item(doctype: str, name: str) -> dict:
	"""One item, its history and its links. Basic facts for anyone who can see the board;
	description, who raised it, history and comments for board roles only (as get_preview)."""
	if frappe.session.user == "Guest":
		return _err(_("Please sign in."))
	if doctype not in KINDS:
		return _err(_("Unknown work item."))
	table, title_c, status_c, mod_c, start_c, due_c, link_c = _TABLE[doctype]
	row = frappe.db.sql(
		f"""SELECT {title_c} title, {status_c} status, priority, project, {mod_c} module, {start_c} start_date,
			{due_c} due_date, {link_c} linked, _assign, creation, modified, owner
		FROM `{table}` WHERE name = %s""",
		[name],
		as_dict=True,
	)
	if not row:
		return _err(_("That work item is gone."))
	r = row[0]
	if not _project_visible(r.project):
		return _err(_("Not permitted to view this item."))
	stage = _MAPS[doctype].get(
		r.status if doctype != "Request" or r.status != "Requested" else "", _DEFAULT[doctype]
	)
	due = str(r.due_date)[:10] if r.due_date else ""
	assignee_ids = _loads(r._assign)
	names = _assignees(set(assignee_ids))
	out = {
		"success": True,
		"kind": doctype,
		"name": name,
		"title": r.title,
		"status": r.status,
		"stage": stage,
		"priority": r.priority or "",
		"project": r.project,
		"module": r.module or "",
		"start": str(r.start_date)[:10] if r.start_date else "",
		"due": due,
		"late": bool(due and due < str(getdate(today())) and stage not in DONE_STAGES),
		"assignee_ids": assignee_ids,
		"assignees": [names.get(e, e) for e in assignee_ids],
		"tags": frappe.get_all(
			"Tag Link", filters={"document_type": doctype, "document_name": name}, pluck="tag"
		),
		"created": str(r.creation),
		"modified": str(r.modified),
		"detail": False,
	}
	if not is_board_role():
		return out
	out["detail"] = True
	out["project_name"] = frappe.db.get_value("Project", r.project, "project_name")
	extra = {
		"Task": ["description"],
		"Issue": ["description", "raised_by"],
		"Request": ["description", "request_type", "source", "resolution_notes"],
	}[doctype]
	d = frappe.db.get_value(doctype, name, extra, as_dict=True) or {}
	out["description"] = _plain(d.get("description"), 4000)
	out["request_type"] = d.get("request_type") or ""
	out["source"] = d.get("source") or ""
	out["resolution_notes"] = _plain(d.get("resolution_notes"), 2000)
	who = {r.owner, d.get("raised_by")} - {None, ""}
	pn = _assignees(who)
	out["raised_by"] = pn.get(d.get("raised_by") or r.owner, d.get("raised_by") or r.owner)

	# links: the Request <-> Task pair
	links = []
	if r.linked:
		other = "Request" if doctype == "Task" else "Task"
		t = {
			"Request": ("tabRequest", "title", "COALESCE(NULLIF(workflow_state,''),'Requested')"),
			"Task": ("tabTask", "subject", "status"),
		}[other]
		o = frappe.db.sql(
			f"SELECT name, {t[1]} title, {t[2]} status FROM `{t[0]}` WHERE name = %s",
			[r.linked],
			as_dict=True,
		)
		links.append(
			{
				"kind": other,
				"name": r.linked,
				"title": o[0].title if o else "",
				"status": o[0].status if o else "",
				"missing": not o,
			}
		)
	if doctype == "Request":
		for tk in frappe.get_all(
			"Task",
			filters={"custom_request": name},
			fields=["name", "subject", "status"],
			limit=20,
			ignore_permissions=True,
		):
			if tk.name != r.linked:
				links.append(
					{
						"kind": "Task",
						"name": tk.name,
						"title": tk.subject,
						"status": tk.status,
						"missing": False,
					}
				)
	out["links"] = links
	out["history"] = _history(doctype, name, r.creation, r.owner)
	return out


def _plain(html, limit) -> str:
	if not html:
		return ""
	text = re.sub(r"[ \t]+", " ", frappe.utils.strip_html(str(html))).strip()
	text = re.sub(r"\n\s*\n+", "\n\n", text)
	return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "..."


def _history(doctype: str, name: str, created, owner) -> list:
	"""Created + field changes (Version) + comments/assignments/workflow (Comment), newest first."""
	meta = frappe.get_meta(doctype)
	ev = [{"when": str(created), "who": owner, "what": "Created", "type": "created"}]
	for v in frappe.get_all(
		"Version",
		filters={"ref_doctype": doctype, "docname": name},
		fields=["creation", "owner", "data"],
		order_by="creation desc",
		limit=100,
	):
		try:
			data = json.loads(v.data or "{}")
		except ValueError:
			continue
		for ch in data.get("changed") or []:
			if not isinstance(ch, list) or len(ch) < 3 or ch[0] in ("modified", "modified_by", "_assign"):
				continue
			label = meta.get_label(ch[0]) or ch[0]
			old, new = (
				(str(ch[1]) if ch[1] not in (None, "") else "empty"),
				(str(ch[2]) if ch[2] not in (None, "") else "empty"),
			)
			ev.append(
				{
					"when": str(v.creation),
					"who": v.owner,
					"what": f"{label}: {old[:80]} -> {new[:80]}",
					"type": "change",
				}
			)
	for c in frappe.get_all(
		"Comment",
		filters={
			"reference_doctype": doctype,
			"reference_name": name,
			"comment_type": ["in", ["Comment", "Assigned", "Assignment Completed", "Workflow", "Info"]],
		},
		fields=["creation", "owner", "comment_type", "content"],
		order_by="creation desc",
		limit=100,
	):
		ev.append(
			{
				"when": str(c.creation),
				"who": c.owner,
				"what": _plain(c.content, 300),
				"type": c.comment_type.lower(),
			}
		)
	ev.sort(key=lambda e: e["when"], reverse=True)
	ev = ev[:120]
	names = _assignees({e["who"] for e in ev if e["who"]})
	for e in ev:
		e["who"] = names.get(e["who"], e["who"])
	return ev
