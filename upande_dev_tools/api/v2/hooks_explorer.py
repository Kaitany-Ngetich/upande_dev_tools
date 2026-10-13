# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
"""Hooks Explorer v2 - what every installed app registers in its hooks.py.

SOURCE: `frappe.get_hooks(app_name=<app>)` for each installed app. That reads the app's own
hooks.py (a plain data module Frappe already loads on every request) and nothing else. The
handlers those hooks point to are NEVER imported or executed: where a handler lives is found by
walking the app folder on disk and reading the file with `ast.parse` (text only), which also
gives the line number and the first line of the docstring. No source code is returned, only the
dotted path, an app-relative file path, a line number and a docstring line (<= 200 chars).
Values of settings whose name looks like a secret are masked, and no environment/site config is
read.

WHAT ONE ROW IS (a hook "entry"): one registration, counted once:
    doc_events           one per (doctype, event, handler); a tuple key such as ("A", "B") is
                         expanded to one entry per doctype, as frappe.get_doc_hooks() does
    scheduler_events     one per (frequency or cron expression, handler)
    fixtures             one per fixture item
    every other hook     one per list item / per (key, handler) of a dict
App information keys (app_name, app_title, app_publisher, app_license, app_version, required_apps,
...) are not hooks and are not counted; they are shown as "About this app".

IDENTITIES (verified in the report and returned in `checks`):
    total = sum(by_app.count) = sum(by_category.count) = sum(by_hook.count)
    by_app[a].by_category sums to by_app[a].count
    sum over apps of the entries of hook H  =  the entries of H counted from the merged
        frappe.get_hooks(H) (cross-check, returned for doc_events, scheduler_events,
        override_whitelisted_methods, override_doctype_class, fixtures, website_route_rules)
    entries of a doctype with "*" are counted once under "*" (every document type), not once per
        doctype; the "Document types" view shows them separately so nothing is multiplied.

ORDER: apps run in installed-app order (frappe first); `app_order` is the 1-based position.
For override_whitelisted_methods and override_doctype_class the LAST app wins; entries replaced
by a later app are marked `overridden`.

RAW VIEW (`get_app_hooks_raw`): the hooks of one installed app as the current page shows them,
the keys of api.hooks_explorer.HOOK_KEYS first, then every other hook of that app, as plain
JSON (tuple keys joined with " / "). The app name must be an installed app (the current endpoint
imports any `<name>.hooks`); secret-looking keys are masked.

PERMISSIONS: same rule as the current endpoints (api/hooks_explorer._require_dev_team): the
"Dev Team" role. The current get_hooks_summary has no check at all; v2 never exposes counts
without the check. Reads only: no write, no commit.
"""

import ast
import hashlib
import os
import re
from collections import Counter, defaultdict

import frappe
from frappe import _

from upande_dev_tools.api.hooks_explorer import HOOK_KEYS, _require_dev_team

ROW_LIMIT = 500
_SEG = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET = re.compile(r"(secret|token|password|passwd|api_?key|private)", re.I)

#: keys that describe the app itself; shown under "About this app", never counted as hooks
INFO_KEYS = {
	"app_name",
	"app_title",
	"app_publisher",
	"app_description",
	"app_email",
	"app_license",
	"app_icon",
	"app_icon_url",
	"app_icon_route",
	"app_icon_title",
	"app_color",
	"app_logo_url",
	"app_home",
	"app_version",
	"develop_version",
	"frappe_version",
	"required_apps",
	"source_link",
	"export_python_type_annotations",
	"require_type_annotated_api_methods",
	"use_json_request_body",
	"is_frappe_above_v13",
}

CATEGORY_OF = {}
for _cat, _keys in {
	"Document events": ["doc_events"],
	"Scheduled jobs": ["scheduler_events"],
	"Fixtures": ["fixtures"],
	"Overrides": [
		"override_whitelisted_methods",
		"override_doctype_class",
		"extend_doctype_class",
		"override_doctype_dashboards",
		"regional_overrides",
	],
	"Permissions": [
		"permission_query_conditions",
		"has_permission",
		"has_upload_permission",
		"has_website_permission",
	],
	"Website and routes": [
		"website_route_rules",
		"website_redirects",
		"website_context",
		"update_website_context",
		"website_generators",
		"website_path_resolver",
		"get_website_user_home_page",
		"page_renderer",
		"standard_portal_menu_items",
		"webform_list_context",
		"get_web_pages_with_dynamic_routes",
		"base_template",
		"web_include_css",
		"web_include_js",
		"web_include_icons",
	],
	"Boot and Jinja": ["boot_session", "extend_bootinfo", "jinja", "jenv", "notification_config"],
	"Desk scripts and styles": [
		"app_include_js",
		"app_include_css",
		"app_include_icons",
		"doctype_js",
		"doctype_list_js",
		"doctype_tree_js",
		"page_js",
		"email_css",
	],
	"Requests and sessions": [
		"before_request",
		"after_request",
		"on_login",
		"on_logout",
		"on_session_creation",
		"before_job",
		"after_job",
	],
	"Install and migrate": [
		"before_install",
		"after_install",
		"after_migrate",
		"before_migrate",
		"before_uninstall",
		"after_uninstall",
		"before_app_uninstall",
		"after_app_uninstall",
		"after_app_install",
		"setup_wizard_complete",
		"setup_wizard_exception",
		"setup_wizard_requires",
		"setup_wizard_stages",
		"before_tests",
	],
}.items():
	for _k in _keys:
		CATEGORY_OF[_k] = _cat
OTHER = "Other settings"
CATEGORY_ORDER = [
	"Document events",
	"Scheduled jobs",
	"Overrides",
	"Permissions",
	"Fixtures",
	"Website and routes",
	"Boot and Jinja",
	"Desk scripts and styles",
	"Requests and sessions",
	"Install and migrate",
	OTHER,
]
#: hooks whose entries are tied to a document type (scope = the doctype)
DOCTYPE_SCOPED = {
	"doc_events",
	"override_doctype_class",
	"extend_doctype_class",
	"override_doctype_dashboards",
	"permission_query_conditions",
	"has_permission",
	"has_upload_permission",
	"has_website_permission",
	"doctype_js",
	"doctype_list_js",
	"doctype_tree_js",
	"fixtures",
}
LAST_WINS = {"override_whitelisted_methods", "override_doctype_class"}


# --------------------------------------------------------------------------------------------
# normalising hooks.py values into entries
# --------------------------------------------------------------------------------------------


def _short(v, n=160):
	s = v if isinstance(v, str) else repr(v)
	s = re.sub(r"\s+", " ", s).strip()
	return s if len(s) <= n else s[: n - 1] + "…"


def _flat(v):
	"""Yield scalars/dicts out of arbitrarily nested lists/tuples (merged hooks can nest)."""
	if isinstance(v, list | tuple | set):
		for x in v:
			yield from _flat(x)
	elif v is not None:
		yield v


def _text_of(item):
	"""One line describing a non-string list item (dict) without dumping it all."""
	if isinstance(item, dict):
		if "from_route" in item or "to_route" in item:
			return f"{item.get('from_route', '')} → {item.get('to_route', '')}"
		if "source" in item and "target" in item:
			return f"{item.get('source')} → {item.get('target')}"
		if "dt" in item:
			f = item.get("filters")
			return f"{item['dt']}" + (f" (filtered: {_short(f, 80)})" if f else "")
		for k in ("title", "label", "name", "app_name", "fieldname", "doctype"):
			if item.get(k):
				return _short(item[k])
		return _short({k: ("***" if _SECRET.search(str(k)) else v) for k, v in item.items()}, 120)
	return _short(item)


def _kind_of(handler, hook):
	if hook == "fixtures":
		return "fixture"
	if hook in ("website_route_rules", "website_redirects"):
		return "route"
	if isinstance(handler, str):
		low = handler.split("?")[0].lower()
		if low.endswith((".js", ".ts", ".css", ".scss", ".svg", ".html", ".json")) or low.startswith(("/assets/", "assets/")):
			return "file"
		if re.fullmatch(r"[A-Za-z_][\w]*(\.[A-Za-z_][\w]*)+", handler):
			return "python"
	return "setting"


def _entries_for(app, hook, value):
	"""Yield (scope, event, handler_text, raw_handler, doctype) for one hooks.py key."""
	if hook == "doc_events" and isinstance(value, dict):
		for key, events in value.items():
			dts = list(key) if isinstance(key, tuple) else [key]
			if not isinstance(events, dict):
				for dt in dts:
					for h in _flat(events):
						yield dt, "", _text_of(h), h, dt
				continue
			for ev, handlers in events.items():
				for dt in dts:
					for h in _flat(handlers):
						yield dt, str(ev), _text_of(h), h, dt
		return
	if hook == "scheduler_events" and isinstance(value, dict):
		for freq, handlers in value.items():
			if isinstance(handlers, dict):  # cron: {expression: [handlers]}
				for expr, hs in handlers.items():
					for h in _flat(hs):
						yield f"{freq}: {expr}", str(expr), _text_of(h), h, None
			else:
				for h in _flat(handlers):
					yield str(freq), str(freq), _text_of(h), h, None
		return
	if isinstance(value, dict):
		for key, sub in value.items():
			scope = " / ".join(key) if isinstance(key, tuple) else str(key)
			dt = scope if hook in DOCTYPE_SCOPED else None
			if isinstance(sub, dict):
				for k2, v2 in sub.items():
					for h in _flat(v2) if isinstance(v2, list | tuple) else [v2]:
						yield scope, str(k2), _text_of(h), h, dt
			else:
				for h in _flat(sub):
					yield scope, "", _text_of(h), h, dt
		return
	for h in _flat(value):
		scope = ""
		dt = None
		if hook == "fixtures":
			if isinstance(h, dict) and h.get("dt"):
				scope = dt = str(h["dt"])
			elif isinstance(h, str):
				scope = dt = h
		yield scope, "", _text_of(h), h, dt


def _eid(*parts):
	return hashlib.sha1("\x1f".join(str(p) for p in parts).encode()).hexdigest()[:12]


def _collect():
	"""All entries for all installed apps, plus app info. Pure reads of hooks.py data."""
	apps = frappe.get_installed_apps()
	entries, info, seen = [], {}, Counter()
	for order, app in enumerate(apps, start=1):
		try:
			hooks = frappe.get_hooks(app_name=app)
		except Exception:
			info[app] = {"app": app, "order": order, "error": "Could not read this app's hooks.py"}
			continue
		meta = {}
		for k in INFO_KEYS:
			if k in hooks:
				v = hooks[k]
				meta[k] = [_short(x) for x in _flat(v)] if not _SECRET.search(k) else ["***"]
		first = lambda k: (meta.get(k) or [""])[0]  # noqa: E731
		info[app] = {
			"app": app,
			"order": order,
			"title": first("app_title") or app,
			"publisher": first("app_publisher"),
			"description": first("app_description"),
			"license": first("app_license"),
			"version": first("app_version"),
			"required_apps": meta.get("required_apps", []),
		}
		for hook in sorted(hooks):
			if hook in INFO_KEYS:
				continue
			cat = CATEGORY_OF.get(hook, OTHER)
			for scope, event, text, raw, dt in _entries_for(app, hook, hooks[hook]):
				if _SECRET.search(hook):
					text = "***"
				kind = _kind_of(raw, hook)
				ident = (app, hook, scope, event, text)
				seen[ident] += 1
				entries.append(
					{
						"id": _eid(*ident, seen[ident]),
						"app": app,
						"app_order": order,
						"category": cat,
						"hook": hook,
						"scope": scope,
						"event": event,
						"handler": text,
						"kind": kind,
						"doctype": dt if dt and dt != "*" else None,
						"all_doctypes": dt == "*",
						"duplicate_of_count": 0,
						"overridden": False,
					}
				)
	_mark_duplicates_and_overrides(entries)
	return apps, info, entries


def _mark_duplicates_and_overrides(entries):
	groups = defaultdict(list)
	for e in entries:
		if e["kind"] == "python" and e["hook"] in ("doc_events", "scheduler_events"):
			groups[(e["hook"], e["scope"], e["event"], e["handler"])].append(e)
	for g in groups.values():
		for e in g:
			e["duplicate_of_count"] = len(g)
	last = {}
	for e in entries:
		if e["hook"] in LAST_WINS:
			last[(e["hook"], e["scope"])] = e["id"]
	for e in entries:
		if e["hook"] in LAST_WINS:
			e["overridden"] = last[(e["hook"], e["scope"])] != e["id"]


# --------------------------------------------------------------------------------------------
# locating a handler on disk (text only, never imported)
# --------------------------------------------------------------------------------------------

_AST_CACHE = {}  # file -> (mtime, size, {qualified name: (line, doc)})


def _index_file(path):
	try:
		st = os.stat(path)
	except OSError:
		return None
	hit = _AST_CACHE.get(path)
	if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
		return hit[2]
	if st.st_size > 2_000_000:
		return None
	try:
		with open(path, encoding="utf-8") as f:  # nosemgrep
			tree = ast.parse(f.read())
	except (OSError, SyntaxError, ValueError):
		return None
	idx = {}

	def walk(body, prefix):
		for n in body:
			if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
				q = prefix + n.name
				doc = (ast.get_docstring(n) or "").strip().split("\n")[0][:200]
				idx[q] = (n.lineno, doc)
				if isinstance(n, ast.ClassDef):
					walk(n.body, q + ".")
			elif isinstance(n, ast.ImportFrom | ast.Import):
				# re-exported name (e.g. `from .utils import make_custom_fields` in __init__.py)
				for al in n.names:
					idx.setdefault(prefix + (al.asname or al.name.split(".")[0]), (n.lineno, ""))
			elif isinstance(n, ast.Assign):
				for t in n.targets:
					if isinstance(t, ast.Name):
						idx.setdefault(prefix + t.id, (n.lineno, ""))

	walk(tree.body, "")
	mod_doc = (ast.get_docstring(tree) or "").strip().split("\n")[0][:200]
	idx["<module>"] = (1, mod_doc)
	if len(_AST_CACHE) > 3000:
		_AST_CACHE.clear()
	_AST_CACHE[path] = (st.st_mtime, st.st_size, idx)
	return idx


def _bench_apps_dir():
	return os.path.dirname(os.path.dirname(frappe.get_app_path("frappe")))


def _rel(path):
	base = _bench_apps_dir()
	return os.path.relpath(path, os.path.dirname(base)) if path.startswith(base) else os.path.basename(path)


def locate_handler(dotted):
	"""Return {found, file, line, doc, reason} for 'app.pkg.module.function'. Never imports."""
	segs = dotted.split(".")
	if len(segs) < 2 or not all(_SEG.match(s) for s in segs):
		return {"found": False, "reason": "Not a dotted Python path"}
	try:
		root = frappe.get_app_path(segs[0])
	except Exception:
		return {"found": False, "reason": f"'{segs[0]}' is not an app on this bench"}
	if not os.path.isdir(root):
		return {"found": False, "reason": f"'{segs[0]}' is not an app on this bench"}
	cur, file, rest = root, None, []
	for i, seg in enumerate(segs[1:], start=1):
		if os.path.isdir(os.path.join(cur, seg)):
			cur = os.path.join(cur, seg)
			continue
		py = os.path.join(cur, seg + ".py")
		if os.path.isfile(py):
			file, rest = py, segs[i + 1 :]
		else:
			init = os.path.join(cur, "__init__.py")
			if os.path.isfile(init):
				file, rest = init, segs[i:]
		break
	else:
		init = os.path.join(cur, "__init__.py")
		if os.path.isfile(init):
			file, rest = init, []
	if not file:
		return {"found": False, "reason": "No such module in the app folder"}
	idx = _index_file(file)
	if idx is None:
		return {"found": True, "file": _rel(file), "line": None, "doc": "", "reason": "File could not be read"}
	if not rest:
		line, doc = idx["<module>"]
		return {"found": True, "file": _rel(file), "line": line, "doc": doc}
	q = ".".join(rest)
	if q in idx:
		line, doc = idx[q]
		return {"found": True, "file": _rel(file), "line": line, "doc": doc}
	return {
		"found": False,
		"file": _rel(file),
		"reason": "The module exists but defines nothing with that name",
	}


def locate_file(app, path):
	"""'/assets/<app>/js/x.js' -> app/public/js/x.js ; existence only."""
	m = re.match(r"^/?assets/([A-Za-z_][\w]*)/(.+?)(\?.*)?$", path or "")
	if not m or ".." in m.group(2):
		return {"found": None}
	try:
		root = frappe.get_app_path(m.group(1), "public")
	except Exception:
		return {"found": False, "reason": "App not on this bench"}
	f = os.path.join(root, m.group(2))
	return {"found": os.path.isfile(f), "file": _rel(f)} if os.path.realpath(f).startswith(
		os.path.realpath(root)
	) else {"found": None}


def _resolve_all(entries):
	"""Add found/status for each python entry (cheap: file index is cached by mtime)."""
	cache = {}
	for e in entries:
		if e["kind"] == "python":
			if e["handler"] not in cache:
				cache[e["handler"]] = locate_handler(e["handler"])
			e["found"] = cache[e["handler"]].get("found")
		else:
			e["found"] = None


# --------------------------------------------------------------------------------------------
# filtering + roll-ups
# --------------------------------------------------------------------------------------------


def _args(kw):
	g = lambda k: str(kw.get(k) or "").strip()  # noqa: E731
	return {k: g(k) for k in ("app", "category", "hook", "doctype", "q", "status")}


def _match(e, a):
	if a["app"] and e["app"] != a["app"]:
		return False
	if a["category"] and e["category"] != a["category"]:
		return False
	if a["hook"] and e["hook"] != a["hook"]:
		return False
	if a["doctype"]:
		# a doctype filter also shows the "every document type" hooks that fire on it
		if not (e["doctype"] == a["doctype"] or (e["all_doctypes"] and e["hook"] == "doc_events")):
			return False
	if a["status"] == "missing" and e.get("found") is not False:
		return False
	if a["status"] == "duplicate" and e["duplicate_of_count"] < 2:
		return False
	if a["status"] == "overridden" and not e["overridden"]:
		return False
	if a["q"]:
		hay = f"{e['hook']} {e['scope']} {e['event']} {e['handler']} {e['app']}".lower()
		if not all(t in hay for t in a["q"].lower().split()):
			return False
	return True


def _public(e):
	return {k: v for k, v in e.items()}


def _checks(apps, entries):
	"""Cross-check our per-app counts against the merged frappe.get_hooks() for key hooks."""
	out = []
	per_hook = Counter(e["hook"] for e in entries)
	for hook in (
		"doc_events",
		"scheduler_events",
		"override_whitelisted_methods",
		"override_doctype_class",
		"fixtures",
		"website_route_rules",
	):
		merged = frappe.get_hooks(hook, {} if hook not in ("fixtures", "website_route_rules") else [])
		n = sum(1 for _ in _entries_for("*", hook, merged))
		out.append({"hook": hook, "per_app_total": per_hook.get(hook, 0), "merged_total": n})
	return out


@frappe.whitelist()
def get_hooks_overview(
	app=None, category=None, hook=None, doctype=None, q=None, status=None, limit=None
):
	"""Everything the page needs in one call: KPIs, per-app x type matrix, rows, doctypes."""
	_require_dev_team()
	try:
		a = _args(
			{"app": app, "category": category, "hook": hook, "doctype": doctype, "q": q, "status": status}
		)
		apps, info, entries = _collect()
		_resolve_all(entries)
		rows = [e for e in entries if _match(e, a)]

		by_app = {x: {"count": 0, "by_category": Counter()} for x in apps}
		by_cat, by_hook, hook_cat = Counter(), Counter(), {}
		for e in rows:
			by_app[e["app"]]["count"] += 1
			by_app[e["app"]]["by_category"][e["category"]] += 1
			by_cat[e["category"]] += 1
			by_hook[e["hook"]] += 1
			hook_cat[e["hook"]] = e["category"]

		doctypes = defaultdict(
			lambda: {"handlers": 0, "events": set(), "apps": set(), "all_types": False, "hooks": set()}
		)
		for e in rows:
			if e["hook"] == "doc_events" or (e["doctype"] and e["hook"] in DOCTYPE_SCOPED):
				key = "*" if e["all_doctypes"] else e["doctype"]
				if not key:
					continue
				d = doctypes[key]
				d["handlers"] += 1
				d["apps"].add(e["app"])
				d["hooks"].add(e["hook"])
				if e["event"] and e["hook"] == "doc_events":
					d["events"].add(e["event"])
		doctype_rows = [
			{
				"doctype": k,
				"label": "Every document type (*)" if k == "*" else k,
				"handlers": v["handlers"],
				"events": sorted(v["events"]),
				"apps": sorted(v["apps"]),
				"hooks": sorted(v["hooks"]),
			}
			for k, v in doctypes.items()
		]
		doctype_rows.sort(key=lambda r: (-r["handlers"], r["doctype"]))

		all_dts = sorted(
			{e["doctype"] for e in entries if e["doctype"] and e["hook"] in DOCTYPE_SCOPED}
		)
		try:
			lim = max(1, min(int(limit or ROW_LIMIT), 5000))
		except (TypeError, ValueError):
			lim = ROW_LIMIT
		ordered = sorted(rows, key=lambda e: (e["app_order"], e["category"], e["hook"], e["scope"], e["event"]))
		cats = [c for c in CATEGORY_ORDER if c in {e["category"] for e in entries}]
		return {
			"success": True,
			"filters": a,
			"totals": {
				"entries": len(rows),
				"all_entries": len(entries),
				"apps_with_hooks": sum(1 for x in apps if by_app[x]["count"]),
				"installed_apps": len(apps),
				"on_every_doctype": sum(1 for e in rows if e["all_doctypes"]),
				"doctypes_touched": len([k for k in doctypes if k != "*"]),
				"missing_handlers": sum(1 for e in rows if e.get("found") is False),
				"listed_twice": sum(1 for e in rows if e["duplicate_of_count"] > 1),
				"overridden": sum(1 for e in rows if e["overridden"]),
			},
			"by_app": [
				{
					"app": x,
					"order": info[x]["order"],
					"title": info[x].get("title", x),
					"count": by_app[x]["count"],
					"by_category": dict(by_app[x]["by_category"]),
				}
				for x in apps
			],
			"by_category": [{"category": c, "count": by_cat.get(c, 0)} for c in cats],
			"by_hook": sorted(
				[{"hook": h, "category": hook_cat[h], "count": n} for h, n in by_hook.items()],
				key=lambda r: (-r["count"], r["hook"]),
			),
			"categories": cats,
			"hooks": sorted({(e["category"], e["hook"]) for e in entries}),
			"doctype_options": all_dts,
			"rows": [_public(e) for e in ordered[:lim]],
			"row_limit": lim,
			"truncated": len(ordered) > lim,
			"doctypes": doctype_rows,
			"checks": _checks(apps, entries),
		}
	except frappe.PermissionError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Hooks Explorer v2")
		return {"success": False, "error": _("Could not read the hooks of the installed apps.")}


@frappe.whitelist()
def get_hook_detail(app, id):
	"""Handler, where it lives, its docstring line, and who else listens to the same event."""
	_require_dev_team()
	try:
		_apps, info, entries = _collect()
		e = next((x for x in entries if x["id"] == str(id or "") and x["app"] == app), None)
		if not e:
			return {"success": False, "error": _("That hook is no longer registered.")}
		loc = {"found": None}
		if e["kind"] == "python":
			loc = locate_handler(e["handler"])
		elif e["kind"] == "file":
			loc = locate_file(e["app"], e["handler"])
		same = []
		if e["hook"] == "doc_events":
			scopes = {e["scope"]} if e["all_doctypes"] else {e["scope"], "*"}
			pick = lambda x: x["hook"] == "doc_events" and x["event"] == e["event"] and x["scope"] in scopes  # noqa: E731
		elif e["hook"] in ("scheduler_events",) or e["hook"] in LAST_WINS:
			pick = lambda x: x["hook"] == e["hook"] and x["scope"] == e["scope"]  # noqa: E731
		else:
			pick = None
		if pick:
			same = [
				{
					"app": x["app"],
					"app_order": x["app_order"],
					"scope": x["scope"],
					"handler": x["handler"],
					"overridden": x["overridden"],
					"id": x["id"],
				}
				for x in entries
				if pick(x)
			]
			same.sort(key=lambda r: (r["app_order"], r["handler"]))
		return {
			"success": True,
			"entry": e,
			"location": loc,
			"same_event": same,
			"app": info.get(e["app"]),
		}
	except frappe.PermissionError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Hooks Explorer v2 detail")
		return {"success": False, "error": _("Could not read that hook.")}


def _jsonable(value, key=""):
	"""Plain-JSON copy of a hooks.py value: tuple keys joined, sets listed, secrets masked."""
	if key and _SECRET.search(str(key)):
		return "***"
	if isinstance(value, dict):
		return {
			(" / ".join(map(str, k)) if isinstance(k, tuple) else str(k)): _jsonable(v, k)
			for k, v in value.items()
		}
	if isinstance(value, list | tuple | set):
		return [_jsonable(v) for v in value]
	if value is None or isinstance(value, bool | int | float | str):
		return value
	return repr(value)


@frappe.whitelist()
def get_app_hooks_raw(app_name: str):
	"""One app's hooks as JSON, with the same hook keys the current Hooks Explorer lists first."""
	_require_dev_team()
	if app_name not in frappe.get_installed_apps():
		return {"success": False, "error": _("That app is not installed on this site.")}
	try:
		hooks = frappe.get_hooks(app_name=app_name)
		keys = [k for k in HOOK_KEYS if hooks.get(k)] + sorted(
			k for k in hooks if k not in HOOK_KEYS and k not in INFO_KEYS and hooks.get(k)
		)
		return {
			"success": True,
			"app_name": app_name,
			"order": keys,
			"hooks": {k: _jsonable(hooks[k], k) for k in keys},
			"current_page_keys": [k for k in keys if k in HOOK_KEYS],
		}
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Hooks Explorer v2 raw")
		return {"success": False, "error": _("Could not read this app's hooks.")}
