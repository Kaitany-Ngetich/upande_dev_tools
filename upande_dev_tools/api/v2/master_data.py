# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
"""Master Data v2 reads: each master list with how often each value is used.

Nothing in this module writes. The page's add / rename / reorder / disable / delete actions call
the existing endpoints in api/master_data.py (add_master_data, update_master_data,
set_master_data_disabled, delete_master_data), so their validation and in-use rules stay as is.

LISTS (the four master doctypes the current page edits) and where each one is USED:
    request_type   Request Type   <- Request.request_type
    priority_level Priority Level <- Request.priority (a real link) and, by the same wording,
                                     Task.priority (a fixed Low/Medium/High/Urgent select) and
                                     Issue.priority (link to Issue Priority). Task/Issue are
                                     matched by name only; no link enforces it.
    product_area   Product Area   <- Request.product_area, Task.custom_module, Issue.custom_module
    tag            Work Tag       <- Tag Link rows on Request, Task and Issue (Frappe tagging)

DEFINITIONS
    uses(value, source) = number of DISTINCT items of that source carrying the value
                          (Tag Link: distinct document_name per tag).
    For tags an item with three tags is counted once under each tag, so
    "total uses" can be larger than the number of items; it is labelled "tag uses".
    Template tasks (Task.is_template = 1) are not real work and are left out.
    The date filter is the ITEM's creation date; "latest item" is the newest item
    that carries the value (inside the same filters).
    "Not used" = the value has no items under the current filters (so it follows the date
    range and the source filter). "No value" items are those with the field empty (for tags:
    items with no tag at all); shown as a count, never as a row.
    Orphans = values found on items that are not in the master list (e.g. a tag on a task
    whose Work Tag was deleted, or a name that differs only by capital letters).

IDENTITIES (verified in the final report):
    values_total = in_use + unused                     (listed master values)
    Non-tag kinds:  sum(row.count for a source) + no_value[source] = items[source]
                    (rows include orphan values; every item is in exactly one row or no-value)
    Tags:           sum(row.count for a source) = number of Tag Link rows of that source
                    and tagged_items + no_value = items
    Counts are SQL over the full filtered set; no row limit applies to the lists (the
    lists are the master lists, at most a few hundred values). Drill-down lists are capped
    and report truncated/total.

ACCESS: identical to the current Master Data page: the Dev Portal Page "master-data" rule
(portal._route_permits) AND api.master_data.has_master_data_access (Dev Team + Projects
Manager + System Manager). The current get_master_data is open to any signed-in user but
returns only names; these endpoints return usage across all requests/tasks, so they follow
the page rule.
"""

import re
from difflib import SequenceMatcher

import frappe
from frappe import _
from frappe.utils import add_days, getdate

from upande_dev_tools import portal
from upande_dev_tools.api.master_data import has_master_data_access

DRILL_LIMIT = 300
NONE_KEY = "__none__"
SIMILAR = 0.86

#: kind -> label, master doctype, name field, sources [(key, label, doctype, column, note)]
KINDS = {
	"request_type": {
		"label": "Request types",
		"doctype": "Request Type",
		"field": "type_name",
		"sources": [("request", "Requests", "Request", "request_type")],
	},
	"priority_level": {
		"label": "Priority levels",
		"doctype": "Priority Level",
		"field": "level_name",
		"sources": [
			("request", "Requests", "Request", "priority"),
			("task", "Tasks", "Task", "priority"),
			("issue", "Issues", "Issue", "priority"),
		],
	},
	"product_area": {
		"label": "Product areas",
		"doctype": "Product Area",
		"field": "area_name",
		"sources": [
			("request", "Requests", "Request", "product_area"),
			("task", "Tasks", "Task", "custom_module"),
			("issue", "Issues", "Issue", "custom_module"),
		],
	},
	"tag": {
		"label": "Tags",
		"doctype": "Work Tag",
		"field": "tag_name",
		"sources": [
			("request", "Requests", "Request", None),
			("task", "Tasks", "Task", None),
			("issue", "Issues", "Issue", None),
		],
	},
}
_BIN = "COLLATE utf8mb4_bin"


def _require_access():
	roles = set(frappe.get_roles())
	if (
		frappe.session.user == "Guest"
		or not portal._route_permits("/master-data", roles)
		or not has_master_data_access()
	):
		frappe.throw(_("Not permitted."), frappe.PermissionError)


def _dates(from_date, to_date):
	"""[(sql, params)] bounds on item creation; both optional. Raises ValueError on bad dates."""
	a = getdate(from_date) if from_date else None
	b = getdate(to_date) if to_date else None
	if a and b and a > b:
		a, b = b, a
	return a, b


def _date_sql(alias, a, b):
	sql, vals = "", []
	if a:
		sql += f" AND {alias}.creation >= %s"
		vals.append(str(a))
	if b:
		sql += f" AND {alias}.creation < %s"
		vals.append(str(add_days(b, 1)))
	return sql, vals


def _item_filter(doctype, alias="d"):
	return f" AND {alias}.is_template = 0" if doctype == "Task" else ""


def _norm(name):
	return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _similar_groups(names):
	"""Groups of names that differ only by case/spacing/punctuation, or are very close
	(difflib >= SIMILAR), or an abbreviation of each other (HR / Human Resources). Returns {name: group_id} and the groups (lists of >= 2 names)."""
	names = sorted(set(names))
	parent = {n: n for n in names}

	def find(x):
		while parent[x] != x:
			parent[x] = parent[parent[x]]
			x = parent[x]
		return x

	norm = {n: _norm(n) for n in names}
	initials = {
		n: "".join(w[0] for w in re.findall(r"[A-Za-z0-9]+", n.lower()))
		if len(re.findall(r"[A-Za-z0-9]+", n)) > 1
		else ""
		for n in names
	}
	for i, a in enumerate(names):
		for b in names[i + 1 :]:
			na, nb = norm[a], norm[b]
			if not na or not nb:
				continue
			if (
				na == nb
				or (initials[a] and initials[a] == nb)
				or (initials[b] and initials[b] == na)
				or (min(len(na), len(nb)) >= 4 and SequenceMatcher(None, na, nb).ratio() >= SIMILAR)
			):
				parent[find(a)] = find(b)
	groups = {}
	for n in names:
		groups.setdefault(find(n), []).append(n)
	groups = [g for g in groups.values() if len(g) > 1]
	return groups


def _usage(kind_cfg, source_keys, a, b):
	"""-> (usage {value: {source_key: [count, latest]}}, items {source: n}, no_value {source: n}).
	One grouped query per source, filtered in SQL."""
	usage, items, no_value = {}, {}, {}
	for key, _label, doctype, col in kind_cfg["sources"]:
		if key not in source_keys:
			continue
		dsql, dvals = _date_sql("d", a, b)
		flt = _item_filter(doctype) + dsql
		items[key] = frappe.db.sql(f"SELECT COUNT(*) FROM `tab{doctype}` d WHERE 1=1{flt}", dvals)[0][0]
		if col:
			rows = frappe.db.sql(
				f"""SELECT d.`{col}` AS v, COUNT(*) AS c, MAX(d.creation) AS last
				FROM `tab{doctype}` d
				WHERE d.`{col}` IS NOT NULL AND d.`{col}` != ''{flt}
				GROUP BY d.`{col}` {_BIN}""",
				dvals,
				as_dict=True,
			)
			no_value[key] = items[key] - sum(r.c for r in rows)
		else:
			rows = frappe.db.sql(
				f"""SELECT tl.tag AS v, COUNT(DISTINCT tl.document_name) AS c, MAX(d.creation) AS last
				FROM `tabTag Link` tl INNER JOIN `tab{doctype}` d ON d.name = tl.document_name
				WHERE tl.document_type = %s{flt}
				GROUP BY tl.tag {_BIN}""",
				[doctype, *dvals],
				as_dict=True,
			)
			tagged = frappe.db.sql(
				f"""SELECT COUNT(DISTINCT tl.document_name)
				FROM `tabTag Link` tl INNER JOIN `tab{doctype}` d ON d.name = tl.document_name
				WHERE tl.document_type = %s{flt}""",
				[doctype, *dvals],
			)[0][0]
			no_value[key] = items[key] - tagged
		for r in rows:
			usage.setdefault(r.v, {})[key] = [int(r.c), r.last]
	return usage, items, no_value


@frappe.whitelist()
def get_master_summary():
	"""Number of values per master list, for the tab labels (not date dependent)."""
	_require_access()
	out = {}
	for key, cfg in KINDS.items():
		out[key] = frappe.db.count(cfg["doctype"])
	return {"success": True, "counts": out}


@frappe.whitelist()
def get_master_usage(kind, from_date=None, to_date=None, source=None, show=None, q=None):
	"""One master list with usage per value.

	kind   request_type | priority_level | product_area | tag
	source '' (all) or one of the kind's source keys (request / task / issue)
	show   '' (all) | used | unused | disabled | similar | orphan
	q      text in the value name
	KPIs are computed over ALL values under the date/source filters; `show` and `q`
	only choose which rows are listed (so the KPIs do not change when you search)."""
	_require_access()
	if kind not in KINDS:
		return {"success": False, "error": "Unknown master data type."}
	cfg = KINDS[kind]
	try:
		a, b = _dates(from_date, to_date)
	except Exception:
		return {"success": False, "error": "Those dates are not valid."}

	all_keys = [s[0] for s in cfg["sources"]]
	source = source if source in all_keys else ""
	keys = [source] if source else all_keys

	field = cfg["field"]
	extra = ", sort_order" if kind == "priority_level" else ""
	masters = frappe.db.sql(
		f"SELECT name, disabled, creation{extra} FROM `tab{cfg['doctype']}` ORDER BY name",
		as_dict=True,
	)
	master_names = {m.name for m in masters}
	usage, items, no_value = _usage(cfg, keys, a, b)

	names = master_names | set(usage)
	groups = _similar_groups(names)
	group_of = {n: i for i, g in enumerate(groups) for n in g}

	rows = []
	mdict = {m.name: m for m in masters}
	for name in sorted(names, key=str.lower):
		m = mdict.get(name)
		u = usage.get(name, {})
		counts = {k: u.get(k, [0, None])[0] for k in keys}
		lasts = [u[k][1] for k in keys if k in u and u[k][1]]
		row = {
			"name": name,
			"in_master": bool(m),
			"disabled": int(m.disabled or 0) if m else 0,
			"counts": counts,
			"total": sum(counts.values()),
			"last_used": str(max(lasts))[:10] if lasts else None,
			"similar_to": [x for x in groups[group_of[name]] if x != name] if name in group_of else [],
			"created": str(m.creation)[:10] if m else None,
		}
		if kind == "priority_level":
			row["sort_order"] = m.sort_order if m else None
		rows.append(row)

	listed = [r for r in rows if r["in_master"]]
	orphans = [r for r in rows if not r["in_master"]]
	kpis = {
		"values": len(listed),
		"in_use": sum(1 for r in listed if r["total"] > 0),
		"unused": sum(1 for r in listed if r["total"] == 0),
		"disabled": sum(1 for r in listed if r["disabled"]),
		"disabled_in_use": sum(1 for r in listed if r["disabled"] and r["total"] > 0),
		"similar_groups": len(groups),
		"orphans": len(orphans),
		"uses": sum(r["total"] for r in rows),
		"items": {k: items.get(k, 0) for k in keys},
		"no_value": {k: no_value.get(k, 0) for k in keys},
		"items_total": sum(items.values()),
		"no_value_total": sum(no_value.values()),
	}

	def keep(r):
		if show == "used" and not (r["in_master"] and r["total"] > 0):
			return False
		if show == "unused" and not (r["in_master"] and r["total"] == 0):
			return False
		if show == "disabled" and not r["disabled"]:
			return False
		if show == "similar" and not r["similar_to"]:
			return False
		if show == "orphan" and r["in_master"]:
			return False
		return not (q and q.strip().lower() not in r["name"].lower())

	return {
		"success": True,
		"kind": kind,
		"label": cfg["label"],
		"doctype": cfg["doctype"],
		"sources": [{"key": s[0], "label": s[1]} for s in cfg["sources"]],
		"active_sources": keys,
		"rows": [r for r in rows if keep(r)],
		"similar_groups": groups,
		"kpis": kpis,
		"field": field,
		"can_edit": has_master_data_access(),
	}


@frappe.whitelist()
def get_value_usage(kind, value):
	"""All-time usage of one value, ignoring every page filter: {source_key: count} per source
	plus the total. Shown before a rename or delete so the person sees what it touches."""
	_require_access()
	if kind not in KINDS:
		return {"success": False, "error": "Unknown master data type."}
	cfg = KINDS[kind]
	usage, _items, _no_value = _usage(cfg, [s[0] for s in cfg["sources"]], None, None)
	counts = {s[0]: usage.get(value, {}).get(s[0], [0, None])[0] for s in cfg["sources"]}
	return {
		"success": True,
		"value": value,
		"counts": counts,
		"total": sum(counts.values()),
		"sources": [{"key": s[0], "label": s[1]} for s in cfg["sources"]],
	}


@frappe.whitelist()
def get_value_items(kind, value, source=None, from_date=None, to_date=None):
	"""Drill-down: the requests / tasks / issues that carry one value (value '__none__' =
	items with no value / no tag). Same filters as the list; newest first; capped."""
	_require_access()
	if kind not in KINDS:
		return {"success": False, "error": "Unknown master data type."}
	cfg = KINDS[kind]
	try:
		a, b = _dates(from_date, to_date)
	except Exception:
		return {"success": False, "error": "Those dates are not valid."}
	if value is None or value == "":
		return {"success": False, "error": "Choose a value."}

	all_keys = [s[0] for s in cfg["sources"]]
	keys = [source] if source in all_keys else all_keys
	title_col = {"Request": "title", "Task": "subject", "Issue": "subject"}
	status_col = {"Request": "workflow_state", "Task": "status", "Issue": "status"}
	out, total, per_source = [], 0, {}
	for key, label, doctype, col in cfg["sources"]:
		if key not in keys:
			continue
		dsql, dvals = _date_sql("d", a, b)
		flt = _item_filter(doctype) + dsql
		params = []
		if col:
			cond = f"(d.`{col}` IS NULL OR d.`{col}` = '')" if value == NONE_KEY else f"d.`{col}` {_BIN} = %s"
			if value != NONE_KEY:
				params.append(value)
			joins = ""
		else:
			joins = (
				" INNER JOIN `tabTag Link` tl ON tl.document_name = d.name AND tl.document_type = %s"
				if value != NONE_KEY
				else ""
			)
			if value != NONE_KEY:
				cond = "tl.tag " + _BIN + " = %s"
				params = [doctype, value]
			else:
				cond = "NOT EXISTS (SELECT 1 FROM `tabTag Link` t2 WHERE t2.document_name = d.name AND t2.document_type = %s)"
				params = [doctype]
		cnt = frappe.db.sql(
			f"SELECT COUNT(DISTINCT d.name) FROM `tab{doctype}` d{joins} WHERE {cond}{flt}",
			[*params, *dvals],
		)[0][0]
		per_source[key] = cnt
		total += cnt
		rows = frappe.db.sql(
			f"""SELECT DISTINCT d.name, d.`{title_col[doctype]}` AS title, d.`{status_col[doctype]}` AS status,
				d.priority, d.creation, d.owner
			FROM `tab{doctype}` d{joins} WHERE {cond}{flt}
			ORDER BY d.creation DESC LIMIT {DRILL_LIMIT}""",
			[*params, *dvals],
			as_dict=True,
		)
		for r in rows:
			out.append(
				{
					"doctype": doctype,
					"source": key,
					"source_label": label[:-1] if label.endswith("s") else label,
					"name": r.name,
					"title": r.title,
					"status": r.status,
					"priority": r.priority,
					"created": str(r.creation)[:10],
					"_c": str(r.creation),
					"owner": r.owner,
				}
			)
	out.sort(key=lambda r: r["_c"], reverse=True)
	truncated = any(per_source[k] > DRILL_LIMIT for k in per_source)
	out = out[: DRILL_LIMIT * len(keys)]
	for r in out:
		r.pop("_c")
	return {
		"success": True,
		"value": value,
		"items": out,
		"total": total,
		"per_source": per_source,
		"truncated": truncated,
		"row_limit": DRILL_LIMIT,
	}
