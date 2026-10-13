# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt
#
# Dev Data Seeder -- pulls selected records from a remote Frappe/ERPNext site
# into this local site for dev/testing. See the Seed Job doctype for the
# configuration shape and upande_dev_tools/www/dev-data-seeder.html for the UI.
#
# Design notes (see the spec review given alongside this file for the long
# version): one background job per Seed Job, walking its configured DocTypes
# top-to-bottom -- NOT one job per DocType. The row order on the Seed Job IS
# the dependency order (list masters above the transactions that link to
# them); no topological sort needed since the human configuring the job
# already knows that order. Running doctypes sequentially rather than in
# parallel background jobs gives up some throughput in exchange for not
# needing per-worker heartbeats, stale-worker detection, or RQ queue
# introspection to stay correct -- for a dev-only seeding tool, run once in a
# while and never time-critical, that trade is worth it. Each DocType's own
# fetch loop is still fully keyset-paginated with the cursor/counters
# committed in the same transaction as the page's data, so a crash mid-run
# resumes from exactly the last committed page with no duplicates and no
# gaps -- the one property that actually matters for not corrupting a local
# dev site.

import json
import re
import time

import frappe
from frappe import _
from frappe.frappeclient import FrappeClient

from upande_dev_tools import portal

#: The Dev Portal Page row that decides who may use the seeder (page AND endpoints).
SEEDER_ROUTE = "dev-data-seeder"
#: Used only when that row has been deleted.
FALLBACK_ROLE = "System Manager"

NON_COLUMN_FIELDTYPES = {
	"Section Break",
	"Column Break",
	"Tab Break",
	"HTML",
	"Button",
	"Table",
	"Table MultiSelect",
	"Fold",
	"Heading",
}
STANDARD_COLUMNS = ("name", "owner", "creation", "modified", "modified_by", "docstatus", "idx")


def require_access():
	"""Same rule as opening the page: the roles on the Dev Portal Page `dev-data-seeder`
	(System Manager by default). Every endpoint below calls this - an endpoint can be called
	without the page, and these ones run as the site (ignore_permissions, direct inserts)."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	roles = set(frappe.get_roles())
	page = portal._fetch_page(SEEDER_ROUTE)
	if page:
		ok = portal._is_permitted(portal._allowed_roles(page.name), bool(page.require_all_roles), roles)
	else:
		ok = FALLBACK_ROLE in roles
	if not ok:
		frappe.throw(_("Not permitted."), frappe.PermissionError)


def _job_status(name):
	status = frappe.db.get_value("Seed Job", name, "status")
	if status is None and not frappe.db.exists("Seed Job", name):
		frappe.throw(_("Seed Job {0} was not found.").format(name), frappe.DoesNotExistError)
	return status


def _secrets(job):
	out = []
	for fieldname in ("api_key", "api_secret", "source_password"):
		try:
			value = job.get_password(fieldname, raise_exception=False) if fieldname != "api_key" else job.api_key
		except Exception:
			value = None
		if value and len(str(value)) >= 3:
			out.append(str(value))
	return out


def redact(text, job=None):
	"""Remove the job's key, secret and password, and any user:password@ in a URL, from `text`."""
	text = str(text)
	if job is not None:
		for secret in _secrets(job):
			text = text.replace(secret, "***")
	return re.sub(r"(?<=://)[^/@\s]+@", "", text)


def friendly_error(e, job=None):
	"""One plain sentence for a failure talking to the source site. FrappeClient raises
	AuthError() with no text and FrappeException(None) for a 401/403, which used to show as an
	empty message or the word "None"."""
	import requests
	from frappe.frappeclient import AuthError, FrappeException, SiteExpiredError, SiteUnreachableError

	if isinstance(e, AuthError):
		msg = "The source site refused the login. Check the user name and password, or the API key and secret."
	elif isinstance(e, SiteExpiredError):
		msg = "The source site reports that its subscription has expired."
	elif isinstance(e, SiteUnreachableError):
		msg = "The source site did not answer (bad gateway). Try again in a few minutes."
	elif isinstance(e, requests.exceptions.SSLError):
		msg = "The source site's security certificate could not be verified."
	elif isinstance(e, requests.exceptions.Timeout):
		msg = "The source site took too long to answer."
	elif isinstance(e, requests.exceptions.ConnectionError):
		msg = "Could not connect to the source site. Check the address and that the site is up."
	elif isinstance(e, (requests.exceptions.MissingSchema, requests.exceptions.InvalidURL, requests.exceptions.InvalidSchema)):
		msg = "The source site address is not valid. It must start with http:// or https://."
	elif isinstance(e, ValueError):
		msg = (
			"The source site did not answer with data. The address may not be a Frappe site, "
			"or it sent back a login page."
		)
	elif isinstance(e, FrappeException) and (not str(e).strip() or str(e).strip() == "None"):
		msg = (
			"The source site refused the request without giving a reason. The login usually has no "
			"permission to read this DocType, or the API key and secret are wrong."
		)
	else:
		msg = str(e).strip() or type(e).__name__
	return redact(msg, job)[:900]


#: (connect, read) seconds. FrappeClient sets no timeout, so a source that stops answering
#: would hang the background job forever and leave the Seed Job "Running".
REQUEST_TIMEOUT = (10, 120)


def _client(job):
	url = (job.source_url or "").strip().rstrip("/")
	if job.auth_type == "API Key":
		client = FrappeClient(url, api_key=job.api_key, api_secret=job.get_password("api_secret"))
		login = None
	else:
		client = FrappeClient(url)
		login = (job.source_user, job.get_password("source_password"))
	request = client.session.request
	client.session.request = lambda *a, **kw: request(*a, **{"timeout": REQUEST_TIMEOUT, **kw})
	if login:
		client._login(*login)
	return client


def _log(seed_job, doctype_name, level, message):
	frappe.get_doc(
		{
			"doctype": "Seed Job Log",
			"seed_job": seed_job,
			"doctype_name": doctype_name or "",
			"level": level,
			"message": str(message)[:9000],
		}
	).insert(ignore_permissions=True)


def _is_stopped(seed_job):
	return frappe.db.get_value("Seed Job", seed_job, "status") in ("Paused", "Cancelled")


@frappe.whitelist()
def test_connection(name):
	require_access()
	job = frappe.get_doc("Seed Job", name)
	try:
		client = _client(job)
		user = client.get_api("frappe.auth.get_logged_user")
		return {"success": True, "user": user}
	except Exception as e:
		return {"success": False, "error": friendly_error(e, job)}


@frappe.whitelist()
def dry_run(name):
	require_access()
	job = frappe.get_doc("Seed Job", name)
	try:
		client = _client(job)
	except Exception as e:
		return {"success": False, "error": friendly_error(e, job)}

	total = 0
	for row in job.doctypes:
		filters = json.loads(row.filters or "[]")
		try:
			count = int(
				client.get_api(
					"frappe.client.get_count",
					{"doctype": row.doctype_name, "filters": json.dumps(filters)},
				)
				or 0
			)
		except Exception as e:
			count = 0
			_log(job.name, row.doctype_name, "Warning", f"Dry run count failed: {friendly_error(e, job)}")
		frappe.db.set_value("Seed Job DocType", row.name, "rows_expected", count, update_modified=False)
		total += count

	frappe.db.set_value("Seed Job", job.name, "total_rows_expected", total, update_modified=False)
	frappe.db.commit()
	return {"success": True, "total_rows_expected": total}


@frappe.whitelist()
def start_seed_job(name):
	require_access()
	job = frappe.get_doc("Seed Job", name)
	if not job.doctypes:
		frappe.throw(_("Add at least one DocType to seed first."))
	if job.status == "Running":
		frappe.throw(_("This job is already running."))
	if job.status == "Queued":
		frappe.throw(_("This job is already queued."))

	frappe.db.set_value("Seed Job", name, {"status": "Queued", "last_error": ""}, update_modified=False)
	for row in job.doctypes:
		if row.status != "Completed":
			frappe.db.set_value(
				"Seed Job DocType",
				row.name,
				{"status": "Pending", "error_count": 0, "last_error": ""},
				update_modified=False,
			)
	frappe.db.commit()
	_enqueue(name)
	return {"success": True}


@frappe.whitelist()
def resume_seed_job(name):
	require_access()
	status = _job_status(name)
	if status != "Paused":
		frappe.throw(_("Can only resume a Paused job."))
	frappe.db.set_value("Seed Job", name, "status", "Queued", update_modified=False)
	frappe.db.commit()
	_enqueue(name)
	return {"success": True}


@frappe.whitelist()
def pause_seed_job(name):
	require_access()
	if _job_status(name) not in ("Queued", "Running"):
		frappe.throw(_("Only a queued or running job can be paused."))
	frappe.db.set_value("Seed Job", name, "status", "Paused", update_modified=False)
	frappe.db.commit()
	return {"success": True}


@frappe.whitelist()
def cancel_seed_job(name):
	require_access()
	if _job_status(name) not in ("Queued", "Running", "Paused"):
		frappe.throw(_("Only a queued, running or paused job can be cancelled."))
	frappe.db.set_value("Seed Job", name, "status", "Cancelled", update_modified=False)
	frappe.db.commit()
	return {"success": True}


@frappe.whitelist()
def retry_doctype(name, row_name):
	require_access()
	if _job_status(name) in ("Queued", "Running"):
		frappe.throw(_("Wait for the job to stop (or pause it) before retrying a DocType."))
	if not frappe.db.exists("Seed Job DocType", {"name": row_name, "parent": name, "parenttype": "Seed Job"}):
		frappe.throw(_("That DocType row does not belong to this Seed Job."))
	frappe.db.set_value(
		"Seed Job DocType",
		row_name,
		{"status": "Pending", "error_count": 0, "last_error": ""},
		update_modified=False,
	)
	frappe.db.set_value("Seed Job", name, "status", "Queued", update_modified=False)
	frappe.db.commit()
	_enqueue(name)
	return {"success": True}


def _enqueue(name):
	frappe.enqueue(
		"upande_dev_tools.api.seeder.run_seed_job",
		queue="long",
		timeout=36000,
		job_name=f"seed-job-{name}",
		name=name,
	)


@frappe.whitelist()
def get_progress(name):
	require_access()
	job = frappe.db.get_value(
		"Seed Job",
		name,
		[
			"status",
			"total_rows_expected",
			"total_rows_imported",
			"started_at",
			"completed_at",
			"last_heartbeat",
			"last_error",
		],
		as_dict=True,
	)
	rows = frappe.get_all(
		"Seed Job DocType",
		filters={"parent": name},
		fields=[
			"name",
			"doctype_name",
			"status",
			"rows_expected",
			"rows_imported",
			"rows_per_sec",
			"current_page",
			"total_pages",
			"last_cursor",
			"last_page_at",
			"error_count",
			"last_error",
		],
		order_by="idx asc",
	)
	logs = frappe.get_all(
		"Seed Job Log",
		filters={"seed_job": name},
		fields=["doctype_name", "level", "message", "creation"],
		order_by="creation desc",
		limit=50,
	)
	return {"job": job, "doctypes": rows, "logs": logs}


def _table_fields(meta):
	return {df.fieldname: df.options for df in meta.fields if df.fieldtype in ("Table", "Table MultiSelect")}


def _child_tables(doctype):
	"""{table fieldname: child DocType} for the tables this site knows about."""
	return {
		fn: dt for fn, dt in _table_fields(frappe.get_meta(doctype)).items() if frappe.db.exists("DocType", dt)
	}


def _fetch_children(client, doctype, names, tables):
	"""The standard list API leaves child tables out, so ask the source for each table's rows
	of these parents: {fieldname: {parent name: [child rows]}}. One request per table per 100 parents."""
	out = {}
	for fieldname, child_dt in tables.items():
		by_parent = {}
		for i in range(0, len(names), 100):
			rows = client.get_api(
				"frappe.client.get_list",
				{
					"doctype": child_dt,
					"parent": doctype,
					"fields": json.dumps(["*"]),
					"filters": json.dumps(
						[["parent", "in", names[i : i + 100]], ["parenttype", "=", doctype], ["parentfield", "=", fieldname]]
					),
					"order_by": "idx asc",
					"limit_page_length": 50000,
				},
			)
			for r in rows or []:
				by_parent.setdefault(r.get("parent"), []).append(r)
		out[fieldname] = by_parent
	return out


def _columns_for(doctype):
	meta = frappe.get_meta(doctype)
	cols = [df.fieldname for df in meta.fields if df.fieldtype not in NON_COLUMN_FIELDTYPES]
	for c in STANDARD_COLUMNS:
		if c not in cols:
			cols.append(c)
	if meta.istable:
		# without these the child rows were stored with parent = NULL (orphans)
		cols += [c for c in ("parent", "parenttype", "parentfield") if c not in cols]
	# a field in the DocType definition whose column was never created (unmigrated, or a
	# layout-only field) made the whole INSERT fail: "Unknown column ... in INSERT INTO"
	existing = set(frappe.db.get_table_columns(doctype))
	return [c for c in cols if c in existing]


def _row_values(record, columns):
	return tuple(record.get(c) for c in columns)


def _bulk_write(doctype, records):
	"""Bulk-insert `records` (dicts from the remote fetch) into `doctype`'s own
	table, and -- for any Table/Table MultiSelect field whose value is a
	nested list (present when that child was requested via "childfield.*" in
	`fields`) -- bulk-insert those child rows into their own table too, with
	parent/parenttype/parentfield/idx stamped. Any column the local schema
	does not have is simply dropped; any local column missing from the
	fetched record lands as NULL -- this is what makes a source/target
	version mismatch non-fatal instead of a hard failure.
	"""
	meta = frappe.get_meta(doctype)
	table_fields = _table_fields(meta)
	parent_columns = _columns_for(doctype)

	parent_values = [_row_values(r, parent_columns) for r in records]
	frappe.db.bulk_insert(doctype, parent_columns, parent_values, ignore_duplicates=True)

	for fieldname, child_doctype in table_fields.items():
		if not frappe.db.exists("DocType", child_doctype):
			continue
		child_rows = []
		for r in records:
			nested = r.get(fieldname)
			if not isinstance(nested, list):
				continue
			for idx, child in enumerate(nested, start=1):
				child = dict(child)
				child["parent"] = r.get("name")
				child["parenttype"] = doctype
				child["parentfield"] = fieldname
				child["idx"] = child.get("idx") or idx
				child_rows.append(child)
		if not child_rows:
			continue
		child_columns = _columns_for(child_doctype)
		child_values = [_row_values(c, child_columns) for c in child_rows]
		frappe.db.bulk_insert(child_doctype, child_columns, child_values, ignore_duplicates=True)

	return len(records)


def _anonymise(records, mapping):
	def walk(obj):
		if isinstance(obj, dict):
			for k, v in obj.items():
				if k in mapping and not isinstance(v, list | dict):
					obj[k] = mapping[k]
				elif isinstance(v, list | dict):
					walk(v)
		elif isinstance(obj, list):
			for item in obj:
				walk(item)

	for r in records:
		walk(r)


def run_seed_job(name):
	"""The one background job per Seed Job -- see the module docstring for why
	this is sequential across DocTypes rather than one job each."""
	job = frappe.get_doc("Seed Job", name)
	frappe.db.set_value(
		"Seed Job", name, {"status": "Running", "started_at": frappe.utils.now_datetime()}, update_modified=False
	)
	frappe.db.commit()

	try:
		client = _client(job)
	except Exception as e:
		message = friendly_error(e, job)
		frappe.db.set_value("Seed Job", name, {"status": "Failed", "last_error": message}, update_modified=False)
		frappe.db.commit()
		_log(name, "", "Error", f"Could not connect to source site: {message}")
		return

	any_failed = False
	for row in job.doctypes:
		if _is_stopped(name):
			break
		if row.status == "Completed":
			continue
		if not _import_doctype(job, row, client):
			any_failed = True

	final_status = frappe.db.get_value("Seed Job", name, "status")
	if final_status not in ("Paused", "Cancelled"):
		final_status = "Failed" if any_failed else "Completed"
		frappe.db.set_value(
			"Seed Job",
			name,
			{"status": final_status, "completed_at": frappe.utils.now_datetime()},
			update_modified=False,
		)
	frappe.db.commit()


def _update_total_imported(job_name):
	total = (
		frappe.db.sql(
			"SELECT SUM(rows_imported) FROM `tabSeed Job DocType` WHERE parent=%s", job_name
		)[0][0]
		or 0
	)
	frappe.db.set_value("Seed Job", job_name, "total_rows_imported", total, update_modified=False)


def _import_doctype(job, row, client):
	doctype_name = row.doctype_name
	page_size = job.page_size or 500
	filters = json.loads(row.filters or "[]")
	fields = json.loads(row.fields or '["*"]')
	if not row.include_children:
		fields = [f for f in fields if "." not in f]
	anonymise = json.loads(job.anonymise_fields or "{}")
	# The cursor is the last `name` and each page asks for name > cursor, so the pages MUST be
	# ordered by name ascending; any other order_by would skip or repeat records.
	order_by = "name asc"
	if (row.order_by or "name asc").strip().lower() != "name asc":
		_log(job.name, doctype_name, "Warning", f"Order By '{row.order_by}' ignored: pages are always read by name ascending.")

	frappe.db.set_value("Seed Job DocType", row.name, "status", "Running", update_modified=False)
	frappe.db.commit()

	cursor = row.last_cursor or ""
	page = row.current_page or 0
	imported = row.rows_imported or 0
	expected = row.rows_expected or 0

	while True:
		if _is_stopped(job.name):
			frappe.db.set_value("Seed Job DocType", row.name, "status", "Paused", update_modified=False)
			frappe.db.commit()
			return True

		page_filters = [*filters, ["name", ">", cursor]] if cursor else list(filters)
		t0 = time.monotonic()
		try:
			records = client.get_list(
				doctype_name,
				fields=fields,
				filters=page_filters,
				order_by=order_by,
				limit_page_length=page_size,
			)
		except Exception as e:
			message = friendly_error(e, job)
			frappe.db.set_value(
				"Seed Job DocType",
				row.name,
				{"status": "Failed", "error_count": (row.error_count or 0) + 1, "last_error": message},
				update_modified=False,
			)
			frappe.db.commit()
			_log(job.name, doctype_name, "Error", f"Fetch failed at cursor '{cursor}': {message}")
			return False
		fetch_ms = int((time.monotonic() - t0) * 1000)

		if not records:
			break

		if row.include_children:
			tables = {
				fn: dt
				for fn, dt in _child_tables(doctype_name).items()
				if not any(isinstance(r.get(fn), list) for r in records)
			}
			if tables:
				try:
					kids = _fetch_children(client, doctype_name, [r["name"] for r in records], tables)
					for fn, by_parent in kids.items():
						for r in records:
							r[fn] = by_parent.get(r["name"], [])
				except Exception as e:
					_log(
						job.name, doctype_name, "Warning",
						f"Child tables not fetched for page after '{cursor}': {friendly_error(e, job)}. "
						"Use Populate child tables to try again.",
					)

		if anonymise:
			_anonymise(records, anonymise)

		t1 = time.monotonic()
		try:
			n_inserted = _bulk_write(doctype_name, records)
		except Exception as e:
			frappe.db.rollback()
			message = redact(str(e).strip() or type(e).__name__, job)[:900]
			frappe.db.set_value(
				"Seed Job DocType",
				row.name,
				{"status": "Failed", "error_count": (row.error_count or 0) + 1, "last_error": message},
				update_modified=False,
			)
			frappe.db.commit()
			_log(job.name, doctype_name, "Error", f"Insert failed at cursor '{cursor}': {message}")
			return False
		insert_ms = int((time.monotonic() - t1) * 1000)

		cursor = records[-1]["name"]
		page = page + 1
		imported = imported + n_inserted
		elapsed = max((fetch_ms + insert_ms) / 1000.0, 0.001)
		rows_per_sec = round(n_inserted / elapsed, 1)
		total_pages = (expected // page_size + 1) if expected else page

		# Data (just bulk-inserted above) and the cursor/counters that record it
		# land in the same commit -- a crash before this point simply replays
		# the same page next run (ignore_duplicates makes that a no-op for
		# whatever partially landed); a crash after it resumes one page later.
		frappe.db.set_value(
			"Seed Job DocType",
			row.name,
			{
				"current_page": page,
				"last_cursor": cursor,
				"rows_imported": imported,
				"rows_per_sec": rows_per_sec,
				"last_page_at": frappe.utils.now_datetime(),
				"total_pages": total_pages,
			},
			update_modified=False,
		)
		_update_total_imported(job.name)
		frappe.db.set_value("Seed Job", job.name, "last_heartbeat", frappe.utils.now_datetime(), update_modified=False)
		frappe.db.commit()

		_log(
			job.name,
			doctype_name,
			"Info",
			f"Page {page}: {len(records)} rows -- fetch {fetch_ms}ms, insert {insert_ms}ms",
		)

		if len(records) < page_size:
			break

	frappe.db.set_value("Seed Job DocType", row.name, "status", "Completed", update_modified=False)
	frappe.db.commit()
	return True


# ── Job editor (used by the Data Seeder v2 page) ─────────────────────────
#
# Lets the dashboard create, change, copy and delete a Seed Job without opening Desk.
# Secrets are write-only: they are never sent to the browser, and a blank secret on
# save means "keep the one already stored".

_EDIT_LOCKED = ("Queued", "Running")
_SECRET_FIELDS = ("api_secret", "source_password")


def _parse_json_text(value, kind, label):
	text = (value or "").strip()
	if not text:
		return None
	try:
		parsed = json.loads(text)
	except ValueError as e:
		frappe.throw(_("{0}: not valid JSON ({1}).").format(label, e))
	if not isinstance(parsed, kind):
		frappe.throw(_("{0}: expected {1}.").format(label, "a JSON list" if kind is list else "a JSON object"))
	return text


@frappe.whitelist()
def search_doctypes(txt=""):
	"""Local DocType names for the picker (the source site is assumed to have the same ones)."""
	require_access()
	txt = (txt or "").strip()
	filters = {"istable": 0, "issingle": 0, "is_virtual": 0}
	rows = frappe.get_all(
		"DocType",
		filters=filters,
		or_filters={"name": ["like", f"%{txt}%"]} if txt else None,
		pluck="name",
		order_by="name asc",
		limit=40,
	)
	return rows


_FILTER_OPS = {"=", "!=", "<", ">", "<=", ">=", "like", "not like", "in", "not in", "is", "between"}
_STD_FIELDS = (
	("name", "ID", "Data", ""), ("owner", "Created By", "Link", "User"), ("creation", "Created On", "Datetime", ""),
	("modified", "Last Modified", "Datetime", ""), ("modified_by", "Last Modified By", "Link", "User"),
	("docstatus", "Document Status", "Int", ""),
)


def _filterable_fields(doctype):
	if not frappe.db.exists("DocType", doctype):
		frappe.throw(_("{0} is not a DocType on this site.").format(doctype))
	meta = frappe.get_meta(doctype)
	out = [{"fieldname": f, "label": l, "fieldtype": t, "options": o} for f, l, t, o in _STD_FIELDS]
	for f in meta.fields:
		if f.fieldtype in NON_COLUMN_FIELDTYPES or f.fieldtype in ("Table", "Table MultiSelect", "Attach", "Attach Image"):
			continue
		opts = f.options or ""
		if f.fieldtype == "Select":
			opts = "\n".join(o for o in opts.split("\n"))
		out.append({"fieldname": f.fieldname, "label": f.label or f.fieldname, "fieldtype": f.fieldtype, "options": opts})
	return out


@frappe.whitelist()
def list_sites():
	"""Saved sites (Deployment Instances) the form can pick from. Secrets are never sent."""
	require_access()
	rows = frappe.get_all(
		"Deployment Instance",
		fields=["name", "environment_type", "site_url", "seeder_auth_type", "seeder_api_key", "seeder_user"],
		order_by="name asc",
		ignore_permissions=True,
	)
	for r in rows:
		inst = frappe.get_doc("Deployment Instance", r["name"])
		r["has_signin"] = bool(
			(r.seeder_auth_type == "API Key" and r.seeder_api_key and inst.get_password("seeder_api_secret", raise_exception=False))
			or (r.seeder_auth_type == "Password" and r.seeder_user and inst.get_password("seeder_password", raise_exception=False))
		)
		for k in ("seeder_api_key", "seeder_user"):
			r.pop(k, None)
	return rows


def _apply_site(job, data):
	"""Resolve the Site part of the form onto the job: pick a saved one, or add (and save) a new one.
	Sign-in typed in the form wins; a blank secret falls back to the saved site's, then to the job's own."""
	inst = None
	if data.get("new_site"):
		ns = data["new_site"]
		nm = (ns.get("name") or "").strip()
		if not nm:
			frappe.throw(_("Give the new site a name."))
		if frappe.db.exists("Deployment Instance", nm):
			frappe.throw(_("A site called {0} already exists. Pick it from the list instead.").format(nm))
		inst = frappe.new_doc("Deployment Instance")
		inst.instance_name = nm
		inst.environment_type = ns.get("environment") or ""
		inst.site_url = data["source_url"]
		inst.flags._new_site = True
	elif data.get("instance"):
		if not frappe.db.exists("Deployment Instance", data["instance"]):
			frappe.throw(_("Site {0} was not found.").format(data["instance"]))
		inst = frappe.get_doc("Deployment Instance", data["instance"])
		if inst.site_url:
			data["source_url"] = inst.site_url
		elif data["source_url"]:
			inst.site_url = data["source_url"]
	if inst is None:
		job.instance = None
		return

	typed_secret = (data.get("api_secret") if data["auth_type"] == "API Key" else data.get("source_password")) or ""
	typed_secret = typed_secret.strip()
	if not typed_secret and not inst.flags._new_site and inst.seeder_auth_type == data["auth_type"]:
		# Use the saved sign-in for this site.
		data["auth_type"] = inst.seeder_auth_type
		if data["auth_type"] == "API Key":
			data["api_key"] = data.get("api_key") or inst.seeder_api_key
			data["api_secret"] = inst.get_password("seeder_api_secret", raise_exception=False) or ""
		else:
			data["source_user"] = data.get("source_user") or inst.seeder_user
			data["source_password"] = inst.get_password("seeder_password", raise_exception=False) or ""
	elif typed_secret and (inst.flags._new_site or data.get("update_site") or not inst.seeder_auth_type):
		inst.seeder_auth_type = data["auth_type"]
		if data["auth_type"] == "API Key":
			inst.seeder_api_key = (data.get("api_key") or "").strip()
			inst.seeder_api_secret = typed_secret
		else:
			inst.seeder_user = (data.get("source_user") or "").strip()
			inst.seeder_password = typed_secret
	inst.flags.ignore_permissions = True
	if inst.is_new():
		inst.insert()
	else:
		inst.save()
	job.instance = inst.name


@frappe.whitelist()
def get_doctype_fields(doctype):
	"""Fields a filter or field list can use, for the editor's pickers."""
	require_access()
	return _filterable_fields(doctype)


def _check_filters(text, doctype, label):
	"""Each filter is [doctype, field, operator, value] (or [field, operator, value]) or a {field: value} map."""
	if not text:
		return
	names = {f["fieldname"] for f in _filterable_fields(doctype)}
	parsed = json.loads(text)
	for i, f in enumerate(parsed, 1):
		if isinstance(f, dict):
			bad = [k for k in f if k not in names]
		elif isinstance(f, (list, tuple)) and len(f) in (3, 4):
			field, op = (f[1], f[2]) if len(f) == 4 else (f[0], f[1])
			bad = [] if field in names else [field]
			if str(op).lower() not in _FILTER_OPS:
				frappe.throw(_("{0}, filter {1}: operator {2} is not supported.").format(label, i, op))
		else:
			frappe.throw(_("{0}, filter {1}: not a valid filter.").format(label, i))
		if bad:
			frappe.throw(_("{0}, filter {1}: {2} is not a field of {3}.").format(label, i, bad[0], doctype))


@frappe.whitelist()
def get_job_form(name):
	"""Everything the edit form needs. Secrets are reported only as set / not set."""
	require_access()
	if not frappe.db.exists("Seed Job", name):
		frappe.throw(_("Seed Job {0} was not found.").format(name), frappe.DoesNotExistError)
	job = frappe.get_doc("Seed Job", name)
	return {
		"name": job.name,
		"locked": job.status in _EDIT_LOCKED,
		"status": job.status,
		"instance": job.instance or "",
		"source_url": job.source_url or "",
		"auth_type": job.auth_type or "API Key",
		"api_key": job.api_key or "",
		"api_secret_set": bool(job.get_password("api_secret", raise_exception=False)),
		"source_user": job.source_user or "",
		"source_password_set": bool(job.get_password("source_password", raise_exception=False)),
		"page_size": job.page_size or 500,
		"ignore_permissions": int(job.ignore_permissions or 0),
		"ignore_links": int(job.ignore_links or 0),
		"ignore_mandatory": int(job.ignore_mandatory or 0),
		"anonymise_fields": job.anonymise_fields or "{}",
		"doctypes": [
			{
				"row": r.name,
				"doctype_name": r.doctype_name,
				"filters": r.filters or "[]",
				"fields": r.fields or '["*"]',
				"include_children": int(r.include_children or 0),
				"order_by": r.order_by or "name asc",
			}
			for r in job.doctypes
		],
	}


@frappe.whitelist()
def save_seed_job(data, name=None):
	"""Create a Seed Job (no name) or update one. `data` is the JSON from the form."""
	require_access()
	if isinstance(data, str):
		data = json.loads(data)
	if not isinstance(data, dict):
		frappe.throw(_("Nothing to save."))

	source_url = (data.get("source_url") or "").strip()
	if not re.match(r"^https?://[^/\s]+", source_url):
		frappe.throw(_("Source site must start with http:// or https://"))
	auth_type = data.get("auth_type") or "API Key"
	if auth_type not in ("API Key", "Password"):
		frappe.throw(_("Unknown sign-in method."))
	page_size = int(data.get("page_size") or 500)
	if not 10 <= page_size <= 5000:
		frappe.throw(_("Page size must be between 10 and 5000."))
	anon = _parse_json_text(data.get("anonymise_fields"), dict, _("Anonymised fields")) or "{}"

	rows = data.get("doctypes") or []
	if not rows:
		frappe.throw(_("Add at least one DocType."))
	clean_rows, seen = [], set()
	for i, r in enumerate(rows, 1):
		dt = (r.get("doctype_name") or "").strip()
		if not dt or not frappe.db.exists("DocType", dt):
			frappe.throw(_("Row {0}: {1} is not a DocType on this site.").format(i, dt or _("(empty)")))
		if dt in seen:
			frappe.throw(_("Row {0}: {1} is listed twice.").format(i, dt))
		seen.add(dt)
		order_by = (r.get("order_by") or "name asc").strip()
		if not re.match(r"^[A-Za-z0-9_`]+( (asc|desc))?$", order_by, re.I):
			frappe.throw(_("Row {0}: order by must look like `modified asc`.").format(i))
		filters = _parse_json_text(r.get("filters"), list, _("Row {0} filters").format(i)) or "[]"
		_check_filters(filters, dt, _("Row {0} ({1})").format(i, dt))
		clean_rows.append(
			{
				"row": r.get("row"),
				"doctype_name": dt,
				"filters": filters,
				"fields": _parse_json_text(r.get("fields"), list, _("Row {0} fields").format(i)) or '["*"]',
				"include_children": 1 if r.get("include_children") else 0,
				"order_by": order_by,
			}
		)

	if name:
		if not frappe.db.exists("Seed Job", name):
			frappe.throw(_("Seed Job {0} was not found.").format(name), frappe.DoesNotExistError)
		job = frappe.get_doc("Seed Job", name)
		if job.status in _EDIT_LOCKED:
			frappe.throw(_("Pause or cancel the job before changing it."))
	else:
		job = frappe.new_doc("Seed Job")

	data["source_url"] = source_url
	data["auth_type"] = auth_type
	_apply_site(job, data)
	source_url, auth_type = data["source_url"], data["auth_type"]
	job.source_url = source_url
	job.auth_type = auth_type
	job.page_size = page_size
	job.ignore_permissions = 1 if data.get("ignore_permissions") else 0
	job.ignore_links = 1 if data.get("ignore_links") else 0
	job.ignore_mandatory = 1 if data.get("ignore_mandatory") else 0
	job.anonymise_fields = anon
	if auth_type == "API Key":
		job.api_key = (data.get("api_key") or "").strip()
		if (data.get("api_secret") or "").strip():
			job.api_secret = data["api_secret"].strip()
		if not job.api_key:
			frappe.throw(_("API key is required."))
	else:
		job.source_user = (data.get("source_user") or "").strip()
		if (data.get("source_password") or "").strip():
			job.source_password = data["source_password"]
		if not job.source_user:
			frappe.throw(_("User is required."))

	# Keep progress on rows that stay; new or edited rows start from Pending.
	existing = {r.name: r for r in job.doctypes}
	job.set("doctypes", [])
	for r in clean_rows:
		old = existing.get(r["row"])
		fresh = {k: r[k] for k in ("doctype_name", "filters", "fields", "include_children", "order_by")}
		if old and old.doctype_name == r["doctype_name"] and (old.filters or "[]") == r["filters"] and (old.fields or '["*"]') == r["fields"]:
			fresh.update(
				{
					k: old.get(k)
					for k in (
						"status", "rows_expected", "rows_imported", "rows_per_sec", "current_page",
						"total_pages", "last_cursor", "last_page_at", "error_count", "last_error",
					)
				}
			)
		job.append("doctypes", fresh)

	job.flags.ignore_permissions = True
	if job.is_new():
		job.insert()
	else:
		job.save()
	frappe.db.commit()
	return {"success": True, "name": job.name}


@frappe.whitelist()
def duplicate_seed_job(name):
	"""A fresh Draft with the same settings and DocTypes. Secrets are copied; progress is not."""
	require_access()
	if not frappe.db.exists("Seed Job", name):
		frappe.throw(_("Seed Job {0} was not found.").format(name), frappe.DoesNotExistError)
	src = frappe.get_doc("Seed Job", name)
	new = frappe.new_doc("Seed Job")
	for f in ("instance", "source_url", "auth_type", "api_key", "source_user", "page_size", "ignore_permissions",
			"ignore_links", "ignore_mandatory", "anonymise_fields"):
		new.set(f, src.get(f))
	for f in _SECRET_FIELDS:
		value = src.get_password(f, raise_exception=False)
		if value:
			new.set(f, value)
	for r in src.doctypes:
		new.append("doctypes", {k: r.get(k) for k in ("doctype_name", "filters", "fields", "include_children", "order_by")})
	new.flags.ignore_permissions = True
	new.insert()
	frappe.db.commit()
	return {"success": True, "name": new.name}


@frappe.whitelist()
def delete_seed_job(name):
	require_access()
	status = _job_status(name)
	if status in _EDIT_LOCKED:
		frappe.throw(_("Pause or cancel the job before deleting it."))
	frappe.delete_doc("Seed Job", name, ignore_permissions=True)
	frappe.db.commit()
	return {"success": True}


# ── Populate child tables for records that are already here ────────────────

@frappe.whitelist()
def populate_children(name, row_name=None):
	"""Fetch the child tables for parents this job already copied (older jobs came without them).
	Only parents that have no rows locally for a table are asked for, so it can be run again."""
	require_access()
	status = _job_status(name)
	if status in _EDIT_LOCKED:
		frappe.throw(_("Wait for the job to stop (or pause it) first."))
	rows = [r for r in frappe.get_all("Seed Job DocType", filters={"parent": name, "parenttype": "Seed Job"}, fields=["name", "doctype_name", "include_children"])
		if (not row_name or r.name == row_name)]
	if row_name and not rows:
		frappe.throw(_("That DocType row does not belong to this Seed Job."))
	if not any(r.include_children and _child_tables(r.doctype_name) for r in rows):
		frappe.throw(_("None of these DocTypes has child tables to fill (or Include child tables is off)."))
	frappe.db.set_value("Seed Job", name, {"status": "Queued", "last_heartbeat": frappe.utils.now_datetime()}, update_modified=False)
	frappe.db.commit()
	frappe.enqueue(
		"upande_dev_tools.api.seeder.run_populate_children",
		queue="long", timeout=36000, job_name=f"seed-children-{name}",
		name=name, row_name=row_name, prev_status=status,
	)
	return {"success": True}


def run_populate_children(name, row_name=None, prev_status="Completed"):
	job = frappe.get_doc("Seed Job", name)
	frappe.db.set_value("Seed Job", name, {"status": "Running", "last_heartbeat": frappe.utils.now_datetime()}, update_modified=False)
	frappe.db.commit()
	anonymise = json.loads(job.anonymise_fields or "{}")
	try:
		client = _client(job)
	except Exception as e:
		message = friendly_error(e, job)
		frappe.db.set_value("Seed Job", name, {"status": prev_status if prev_status != "Draft" else "Failed", "last_error": message}, update_modified=False)
		frappe.db.commit()
		_log(name, "", "Error", f"Could not connect to source site: {message}")
		return

	failed = False
	for row in job.doctypes:
		if row_name and row.name != row_name:
			continue
		if not row.include_children:
			continue
		tables = _child_tables(row.doctype_name)
		if not tables:
			continue
		added, cursor, parents = {fn: 0 for fn in tables}, "", 0
		try:
			while True:
				if _is_stopped(name):
					return
				names = frappe.db.sql_list(
					f"SELECT name FROM `tab{row.doctype_name}` WHERE name > %s ORDER BY name LIMIT 100", cursor
				)
				if not names:
					break
				cursor = names[-1]
				for fn, child_dt in tables.items():
					have = set(
						frappe.db.sql_list(
							f"SELECT DISTINCT parent FROM `tab{child_dt}` WHERE parenttype=%s AND parentfield=%s AND parent IN ({', '.join(['%s'] * len(names))})",
							(row.doctype_name, fn, *names),
						)
					)
					need = [n for n in names if n not in have]
					if not need:
						continue
					by_parent = _fetch_children(client, row.doctype_name, need, {fn: child_dt})[fn]
					child_rows = []
					for parent, kids in by_parent.items():
						for idx, kid in enumerate(kids, 1):
							kid = dict(kid)
							kid.update({"parent": parent, "parenttype": row.doctype_name, "parentfield": fn, "idx": kid.get("idx") or idx})
							child_rows.append(kid)
					if not child_rows:
						continue
					if anonymise:
						_anonymise(child_rows, anonymise)
					cols = _columns_for(child_dt)
					frappe.db.bulk_insert(child_dt, cols, [_row_values(c, cols) for c in child_rows], ignore_duplicates=True)
					added[fn] += len(child_rows)
				parents += len(names)
				frappe.db.set_value("Seed Job", name, "last_heartbeat", frappe.utils.now_datetime(), update_modified=False)
				frappe.db.commit()
			summary = ", ".join(f"{fn}: {n}" for fn, n in added.items())
			_log(name, row.doctype_name, "Info", f"Child tables filled for {parents} records. Rows added: {summary}")
		except Exception as e:
			frappe.db.rollback()
			failed = True
			_log(name, row.doctype_name, "Error", f"Child tables failed: {friendly_error(e, job)}")
		frappe.db.commit()

	if not _is_stopped(name):
		frappe.db.set_value("Seed Job", name, "status", "Failed" if failed and prev_status == "Draft" else prev_status, update_modified=False)
	frappe.db.commit()
