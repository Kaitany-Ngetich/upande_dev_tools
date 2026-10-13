# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
"""Data Seeder v2 reads: Seed Jobs, their DocTypes, progress, log and pre-run checks.

Nothing in this module writes to this site. Start / pause / resume / cancel / retry / count
call the existing endpoints in api/seeder.py, which enforce the same access rule
(`seeder.require_access`: the roles on the Dev Portal Page `dev-data-seeder`).

SECRETS: api_secret and source_password are Password fields. They are never selected here.
api_key is not returned either. The page only learns booleans (key set, secret set, password
set). Log text and errors are passed through `seeder.redact` before they leave the server.

DEFINITIONS
  state (per DocType) : waiting | running | paused | done | failed | interrupted
      interrupted = the row says Running but the job is not Running (the worker stopped).
  stale job           : status Running and no page committed (last_heartbeat / started_at) for
                        STALE_MINUTES. The worker most likely died; Pause then Resume recovers it.
  remaining_max       : sum over unfinished DocTypes of max(expected - imported, 0); None when any
                        unfinished DocType has not been counted yet.
"""

import json
import time
from urllib.parse import urlparse

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, now_datetime

from upande_dev_tools.api import seeder

STALE_MINUTES = 10
LOG_LIMIT = 300
ACTIVE = ("Queued", "Running")

JOB_LABEL = {
	"Draft": "Not started",
	"Queued": "Waiting for a worker",
	"Running": "Running",
	"Paused": "Paused",
	"Completed": "Done",
	"Failed": "Failed",
	"Cancelled": "Cancelled",
}
ROW_STATE = {"Pending": "waiting", "Running": "running", "Paused": "paused", "Completed": "done", "Failed": "failed"}
ROW_LABEL = {
	"waiting": "Waiting",
	"running": "Running",
	"paused": "Paused",
	"done": "Done",
	"failed": "Failed",
	"interrupted": "Interrupted",
}
#: DocTypes that change how this site works or who can sign in.
SENSITIVE = {
	"User", "Role", "Has Role", "DocType", "DocField", "DocPerm", "Custom Field", "Property Setter",
	"Server Script", "Client Script", "Workflow", "System Settings", "Role Permission for Page and Report",
	"Custom DocPerm", "Patch Log", "Module Def", "Email Account", "Print Format",
}


def _check():
	seeder.require_access()


def _host(url):
	try:
		p = urlparse((url or "").strip())
		return p.hostname or ""
	except Exception:
		return ""


def _safe_url(url):
	return seeder.redact((url or "").strip())


def _has_password(name, fieldname):
	return bool(
		frappe.db.sql(
			"select 1 from `__Auth` where doctype='Seed Job' and name=%s and fieldname=%s"
			" and `password` is not null and `password` != '' limit 1",
			(name, fieldname),
		)
	)


def _json(value, default):
	try:
		return json.loads(value or default)
	except (TypeError, ValueError):
		return None


def _minutes_since(dt):
	if not dt:
		return None
	return max(0, int((now_datetime() - get_datetime(dt)).total_seconds() // 60))


def _job_row(j):
	age = _minutes_since(j.last_heartbeat or j.started_at) if j.status == "Running" else None
	return {
		"name": j.name,
		"status": j.status,
		"label": JOB_LABEL.get(j.status, j.status),
		"source": _safe_url(j.source_url),
		"host": _host(j.source_url),
		"auth_type": j.auth_type,
		"expected": cint(j.total_rows_expected),
		"imported": cint(j.total_rows_imported),
		"started_at": j.started_at,
		"completed_at": j.completed_at,
		"last_heartbeat": j.last_heartbeat,
		"stale": bool(age is not None and age >= STALE_MINUTES),
		"stale_minutes": age,
		"error": seeder.redact(j.last_error or ""),
		"modified": j.modified,
	}


@frappe.whitelist()
def get_overview():
	"""Every Seed Job, newest first, with the counts the list needs."""
	_check()
	jobs = frappe.get_all(
		"Seed Job",
		fields=[
			"name", "status", "source_url", "auth_type", "total_rows_expected", "total_rows_imported",
			"started_at", "completed_at", "last_heartbeat", "last_error", "modified",
		],
		order_by="modified desc",
		limit_page_length=200,
	)
	counts = {}
	for r in frappe.get_all("Seed Job DocType", fields=["parent", "status"], limit_page_length=0):
		c = counts.setdefault(r.parent, {"total": 0, "done": 0, "failed": 0})
		c["total"] += 1
		c["done"] += r.status == "Completed"
		c["failed"] += r.status == "Failed"
	rows = []
	for j in jobs:
		row = _job_row(j)
		row["doctypes"] = counts.get(j.name, {"total": 0, "done": 0, "failed": 0})
		rows.append(row)
	return {
		"jobs": rows,
		"active": sum(1 for r in rows if r["status"] in ACTIVE),
		"stale_minutes": STALE_MINUTES,
	}


def _row_view(r, job_status, local_counts):
	state = ROW_STATE.get(r.status, "waiting")
	if state == "running" and job_status != "Running":
		state = "interrupted"
	expected, imported = cint(r.rows_expected), cint(r.rows_imported)
	pct = min(100, round(imported * 100 / expected)) if expected else (100 if state == "done" else 0)
	err = seeder.redact(r.last_error or "")
	if state == "done":
		note = f"Done: {imported:,} records read" + (f" of {expected:,} counted." if expected else ".")
	elif state == "failed":
		note = f"Failed after {imported:,} records. " + (err or "No reason was recorded.")
		if r.last_cursor:
			note += f" Retry continues after {r.last_cursor}."
	elif state == "interrupted":
		note = f"The worker stopped after {imported:,} records. Resume continues after {r.last_cursor or 'the start'}."
	elif state == "paused":
		note = f"Paused at {imported:,} records. Resume continues after {r.last_cursor or 'the start'}."
	elif state == "running":
		note = f"Reading page {cint(r.current_page) + 1}: {imported:,} records so far."
	else:
		note = "Waiting its turn." if not imported else f"Waiting; {imported:,} records already read."
	return {
		"row": r.name,
		"idx": r.idx,
		"doctype": r.doctype_name,
		"state": state,
		"label": ROW_LABEL[state],
		"imported": imported,
		"expected": expected,
		"counted": bool(expected),
		"pct": pct,
		"rows_per_sec": r.rows_per_sec or 0,
		"page": cint(r.current_page),
		"total_pages": cint(r.total_pages),
		"cursor": r.last_cursor or "",
		"last_page_at": r.last_page_at,
		"error_count": cint(r.error_count),
		"error": err,
		"note": note,
		"local_count": local_counts.get(r.doctype_name),
	}


def _local_count(doctype):
	try:
		meta = frappe.get_meta(doctype)
		if meta.istable or meta.issingle or meta.is_virtual or not frappe.db.table_exists(doctype):
			return None
		return frappe.db.count(doctype)
	except Exception:
		return None


def _rows(name, job_status):
	rows = frappe.get_all(
		"Seed Job DocType",
		filters={"parent": name, "parenttype": "Seed Job"},
		fields=[
			"name", "idx", "doctype_name", "status", "rows_expected", "rows_imported", "rows_per_sec",
			"current_page", "total_pages", "last_cursor", "last_page_at", "error_count", "last_error",
		],
		order_by="idx asc",
		limit_page_length=0,
	)
	counts = {d: _local_count(d) for d in {r.doctype_name for r in rows}}
	return [_row_view(r, job_status, counts) for r in rows]


def _remaining_max(rows):
	total = 0
	for r in rows:
		if r["state"] == "done":
			continue
		if not r["counted"]:
			return None
		total += max(r["expected"] - r["imported"], 0)
	return total


def _logs(name, level="", doctype_name="", q="", limit=100, job=None):
	filters = [["seed_job", "=", name]]
	if level in ("Info", "Warning", "Error"):
		filters.append(["level", "=", level])
	if doctype_name:
		filters.append(["doctype_name", "=", doctype_name])
	q = (q or "").strip()[:80]
	if q:
		filters.append(["message", "like", "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"])
	limit = max(1, min(cint(limit) or 100, LOG_LIMIT))
	rows = frappe.get_all(
		"Seed Job Log",
		filters=filters,
		fields=["creation", "level", "doctype_name", "message"],
		order_by="creation desc, name desc",
		limit_page_length=limit,
	)
	return {
		"rows": [
			{**r, "message": seeder.redact(r.message or "", job)} for r in rows
		],
		"total": frappe.db.count("Seed Job Log", filters),
		"limit": limit,
	}


@frappe.whitelist()
def get_progress(name, level="", doctype_name="", q="", limit=100):
	"""Light payload for polling: job state, per-DocType state and the filtered log."""
	_check()
	if not frappe.db.exists("Seed Job", name):
		frappe.throw(_("Seed Job {0} was not found.").format(name), frappe.DoesNotExistError)
	j = frappe.db.get_value(
		"Seed Job",
		name,
		[
			"name", "status", "source_url", "auth_type", "total_rows_expected", "total_rows_imported",
			"started_at", "completed_at", "last_heartbeat", "last_error", "modified",
		],
		as_dict=True,
	)
	job = frappe.get_doc("Seed Job", name)
	rows = _rows(name, j.status)
	view = _job_row(j)
	view["doctypes_total"] = len(rows)
	view["doctypes_done"] = sum(1 for r in rows if r["state"] == "done")
	view["doctypes_failed"] = sum(1 for r in rows if r["state"] == "failed")
	view["remaining_max"] = _remaining_max(rows)
	view["idle"] = j.status not in ACTIVE
	return {
		"job": view,
		"doctypes": rows,
		"log": _logs(name, level, doctype_name, q, limit, job),
		"server_time": str(now_datetime()),
	}


def preflight(job, rows):
	"""Plain-language checks of the saved configuration. [{level: ok|warn|bad, text}]"""
	out = []

	def add(level, text):
		out.append({"level": level, "text": text})

	url = (job.source_url or "").strip()
	p = urlparse(url)
	if p.scheme not in ("http", "https") or not p.hostname:
		add("bad", "The source address must start with http:// or https:// and name a site.")
	else:
		if p.scheme == "http" and p.hostname not in ("localhost", "127.0.0.1"):
			add("warn", "The source address is not encrypted (http). Passwords and data travel in the clear.")
		if p.hostname == frappe.local.site:
			add("bad", "The source is this same site. Seeding would read from itself.")
	if job.auth_type == "API Key":
		if not job.api_key or not _has_password(job.name, "api_secret"):
			add("bad", "API Key sign-in needs both an API key and an API secret. Edit the Seed Job to add them.")
	elif not job.source_user or not _has_password(job.name, "source_password"):
		add("bad", "Password sign-in needs a user name and a password. Edit the Seed Job to add them.")
	if cint(job.page_size) < 1 or cint(job.page_size) > 5000:
		add("warn", f"Page size {cint(job.page_size)} is unusual. 100 to 1,000 records per page is typical.")
	anon = _json(job.anonymise_fields, "{}")
	if not isinstance(anon, dict):
		add("bad", "Anonymise Fields is not a valid JSON object.")
	if not rows:
		add("bad", "No DocTypes are listed. Add at least one on the Seed Job.")
	seen = set()
	for r in job.doctypes:
		dt = r.doctype_name
		tag = f"Row {r.idx} ({dt}): "
		if dt in seen:
			add("warn", tag + "listed more than once.")
		seen.add(dt)
		if not frappe.db.exists("DocType", dt):
			add("bad", tag + "this DocType does not exist on this site.")
			continue
		meta = frappe.get_meta(dt)
		if meta.istable:
			add("bad", tag + "child tables cannot be seeded on their own. Seed the parent DocType instead.")
		elif meta.issingle or meta.is_virtual or not frappe.db.table_exists(dt):
			add("bad", tag + "settings-style and virtual DocTypes cannot be seeded.")
		if dt in SENSITIVE:
			add("warn", tag + "this DocType controls how this site works or who can sign in. Be sure you want it.")
		if not isinstance(_json(r.filters, "[]"), list):
			add("bad", tag + "Filters must be a JSON list.")
		if not isinstance(_json(r.fields, '["*"]'), list):
			add("bad", tag + "Fields must be a JSON list.")
		if (r.order_by or "name asc").strip().lower() != "name asc":
			add("warn", tag + "Order By is ignored. Records are always read by name, oldest name first.")
		if not cint(r.rows_expected) and r.status != "Completed":
			add("warn", tag + "not counted yet. Use Count records to learn how many records to expect.")
	if not any(o["level"] in ("bad",) for o in out):
		add("ok", "The saved settings look usable. A connection test confirms the source side.")
	return out


@frappe.whitelist()
def get_job(name):
	"""Configuration (no secrets) + preflight + the same payload as get_progress."""
	_check()
	if not frappe.db.exists("Seed Job", name):
		frappe.throw(_("Seed Job {0} was not found.").format(name), frappe.DoesNotExistError)
	job = frappe.get_doc("Seed Job", name)
	prog = get_progress(name)
	cfg = {
		"name": job.name,
		"site": job.instance or "",
		"source": _safe_url(job.source_url),
		"host": _host(job.source_url),
		"auth_type": job.auth_type,
		"source_user": job.source_user if job.auth_type == "Password" else "",
		"api_key_set": bool(job.api_key),
		"api_secret_set": _has_password(job.name, "api_secret"),
		"password_set": _has_password(job.name, "source_password"),
		"page_size": cint(job.page_size),
		"anonymise": sorted((_json(job.anonymise_fields, "{}") or {}).keys())
		if isinstance(_json(job.anonymise_fields, "{}"), dict)
		else [],
		"ignore_permissions": cint(job.ignore_permissions),
		"ignore_links": cint(job.ignore_links),
		"ignore_mandatory": cint(job.ignore_mandatory),
		"doctypes": [
			{
				"row": r.name,
				"doctype": r.doctype_name,
				"filters": (r.filters or "[]")[:400],
				"fields": (r.fields or '["*"]')[:400],
				"include_children": cint(r.include_children),
				"child_tables": sorted(seeder._child_tables(r.doctype_name)) if frappe.db.exists("DocType", r.doctype_name) else [],
				"order_by": r.order_by or "name asc",
			}
			for r in job.doctypes
		],
	}
	return {**prog, "config": cfg, "preflight": preflight(job, prog["doctypes"])}


@frappe.whitelist()
def test_connection(name):
	"""Log in to the source and ask who we are. Reads from the source only; writes nothing here."""
	_check()
	if not frappe.db.exists("Seed Job", name):
		frappe.throw(_("Seed Job {0} was not found.").format(name), frappe.DoesNotExistError)
	job = frappe.get_doc("Seed Job", name)
	p = urlparse((job.source_url or "").strip())
	if p.scheme not in ("http", "https") or not p.hostname:
		return {"success": False, "error": "The source address must start with http:// or https://."}
	t0 = time.monotonic()
	client = None
	try:
		client = seeder._client(job)
		user = client.get_api("frappe.auth.get_logged_user")
		return {
			"success": True,
			"user": user,
			"host": p.hostname,
			"ms": int((time.monotonic() - t0) * 1000),
		}
	except Exception as e:
		return {"success": False, "error": seeder.friendly_error(e, job)}
	finally:
		if client is not None and job.auth_type == "Password":
			try:
				client.logout()
			except Exception:
				pass
