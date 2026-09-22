# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.utils import cint

from upande_dev_tools.api.board import _attach_tags, _set_doc_tags, _validate_tags, normalize_priority

REVIEWER_ROLES = {"Dev Team", "Projects Manager", "System Manager"}

# Built-in accounts that are not people - Frappe's own user_query leaves these out too.
RESERVED_USERS = ("Administrator", "Guest")


def parse_users(value: "str | list[str] | None") -> list[str]:
	"""The assignee pickers are multi-select, so `assign_to` arrives as a comma-separated
	string (the widget's hidden input), a JSON array (frappe.xcall serialises a JS array that
	way) or a real list. Order is kept and duplicates dropped, so the first person named stays
	first in _assign."""
	if value is None:
		return []
	if isinstance(value, str):
		value = value.strip()
		if not value:
			return []
		if value.startswith("["):
			try:
				value = json.loads(value)
			except ValueError:
				value = [value]
		else:
			value = value.split(",")
	seen: dict[str, None] = {}
	for entry in value:
		entry = (entry or "").strip()
		if entry:
			seen.setdefault(entry, None)
	return list(seen)


def _assign_many(doctype: str, name: str, users: list[str], **kwargs) -> None:
	for user in users:
		_assign(doctype, name, user, **kwargs)


def _assign(doctype: str, name: str, assign_to: str, date=None, priority=None, description=None) -> None:
	"""Writes the ToDo and _assign directly instead of frappe.desk.form.assign_to.add():
	that helper also tries to auto-share the document with the assignee when they can't
	already read it, and that share call does its own permission check against the CALLER
	(not the assignee) - the same class of permission mismatch already hit once with a
	broken User Permission elsewhere in this app. This app's own role checks are what govern
	visibility, not Frappe's sharing model, so skipping the share step is correct here, not a
	shortcut."""
	from frappe.utils import nowdate

	if frappe.db.exists(
		"ToDo",
		{"reference_type": doctype, "reference_name": name, "allocated_to": assign_to, "status": "Open"},
	):
		return

	frappe.get_doc(
		{
			"doctype": "ToDo",
			"allocated_to": assign_to,
			"reference_type": doctype,
			"reference_name": name,
			"description": description or _("Assignment for {0} {1}").format(doctype, name),
			"priority": normalize_priority("ToDo", "priority", priority) or "Medium",
			"status": "Open",
			"date": date or nowdate(),
			"assigned_by": frappe.session.user,
		}
	).insert(ignore_permissions=True)

	current = json.loads(frappe.db.get_value(doctype, name, "_assign") or "[]")
	if assign_to not in current:
		current.append(assign_to)
		frappe.db.set_value(doctype, name, "_assign", json.dumps(current), update_modified=False)


def _is_raiser_or_on_whose_behalf(doc) -> bool:
	"""The literal submitter, or the employee it was raised on behalf of - a PM/dev raising
	something for a colleague shouldn't leave that colleague locked out of withdrawing or
	confirming their own request just because someone else clicked submit for them."""
	if doc.owner == frappe.session.user:
		return True
	if not doc.raised_by_employee:
		return False
	return frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "name") == doc.raised_by_employee


def _transition_workflow_state(doc, allowed_from: set[str], to_state: str) -> None:
	"""Applies the transition directly rather than through frappe.model.workflow.apply_workflow:
	that helper's own permission check only recognises the literal doc owner (via the if_owner
	DocPerm), not "raised on behalf of", so it would block exactly the person this function
	exists to let through. The state-machine guarantee apply_workflow would have given -
	only a legal transition succeeds - is preserved by the allowed_from check below."""
	if doc.workflow_state not in allowed_from:
		frappe.throw(
			_("{0} can't be done from {1}.").format(to_state, doc.workflow_state), frappe.ValidationError
		)
	doc.db_set("workflow_state", to_state, update_modified=False)
	doc.reload()


def _unassign(doctype: str, name: str, user: str) -> None:
	frappe.db.sql(
		"""update `tabToDo` set status='Cancelled'
		   where reference_type=%s and reference_name=%s and allocated_to=%s and status='Open'""",
		(doctype, name, user),
	)
	current = json.loads(frappe.db.get_value(doctype, name, "_assign") or "[]")
	if user in current:
		current.remove(user)
		frappe.db.set_value(doctype, name, "_assign", json.dumps(current), update_modified=False)


def _resolve_user_display_names(emails: set[str]) -> dict[str, str]:
	if not emails:
		return {}
	rows = frappe.get_all("User", filters={"name": ["in", list(emails)]}, fields=["name", "full_name"])
	return {row.name: row.full_name or row.name for row in rows}


@frappe.whitelist()
def create_request(
	title: str,
	request_type: str,
	description: str | None = None,
	product_area: str | None = None,
	project: str | None = None,
	source: str = "Desk",
	raised_by_employee: str | None = None,
	requested_assignee: str | None = None,
	tags: list[str] | str | None = None,
) -> dict:
	"""raised_by_employee defaults to the submitter's own Employee record (Request.before_insert)
	- pass it explicitly when a PM/dev is raising something on a colleague's behalf. Everyone
	using this app is staff, so "who is this for" is always an Employee, never the ERP's own
	Customer/Contact master data. requested_assignee is a suggestion only (a developer naming
	themselves, or naming who they'd like to handle it) - it never creates a real assignment;
	the PM's accept_request call is the only place that ever happens. tags is mandatory - every
	request needs at least one, since that's the one classification carried forward onto the
	Task it becomes and the only thing the backlog board can filter on across both."""
	if project and not frappe.has_permission("Project", "read", project):
		frappe.throw(_("Not permitted to view this project."), frappe.PermissionError)

	if isinstance(tags, str):
		tags = [t.strip() for t in tags.split(",")]
	tags = [t for t in (tags or []) if t and t.strip()]
	if not tags:
		frappe.throw(_("Add at least one tag before raising this."), frappe.ValidationError)
	_validate_tags(tags)

	doc = frappe.get_doc(
		{
			"doctype": "Request",
			"title": title,
			"request_type": request_type,
			"description": description,
			"product_area": product_area,
			"project": project,
			"source": source,
			"raised_by_employee": raised_by_employee,
			"requested_assignee": requested_assignee,
		}
	)
	doc.insert(ignore_permissions=True)
	_set_doc_tags("Request", doc.name, tags)
	return doc.as_dict()


@frappe.whitelist()
def create_requests_bulk(titles: list[str] | str) -> dict:
	"""Creates one Request per title in a single call, so a client capturing several
	quick-capture notes at once doesn't need N sequential round-trips (and the
	partial-failure risk that comes with them - a flaky connection silently dropping some
	of N separate calls). Best-effort, not all-or-nothing: each title is inserted
	independently, and a failure on one title never rolls back the others - the caller
	gets back exactly which titles succeeded and which didn't, and can retry just the
	failed ones.
	"""
	if "Dev Team" not in frappe.get_roles():
		frappe.throw(_("Only Dev Team members can use quick capture."), frappe.PermissionError)

	if isinstance(titles, str):
		titles = json.loads(titles)

	created: list[str] = []
	failed: list[dict] = []
	for raw_title in titles:
		title = (raw_title or "").strip()
		if not title:
			continue
		try:
			doc = frappe.get_doc(
				{
					"doctype": "Request",
					"title": title,
					"request_type": "Note",
					"source": "Mobile App",
				}
			)
			doc.insert(ignore_permissions=True)
			created.append(doc.name)
		except Exception as e:
			failed.append({"title": title, "error": str(e)})

	return {"created": created, "failed": failed}


@frappe.whitelist()
def get_my_requests(status: str | None = None) -> list[dict]:
	"""A plain user sees only what they raised. A PM/Dev Team member sees every request, so
	they can filter by who raised it or who's working it - the same broader visibility they
	already have in Review Queue and Backlog Board."""
	filters: dict[str, str] = {}
	if not set(frappe.get_roles()) & REVIEWER_ROLES:
		filters["owner"] = frappe.session.user
	if status:
		filters["workflow_state"] = status

	requests = frappe.get_all(
		"Request",
		filters=filters,
		fields=[
			"name",
			"title",
			"request_type",
			"workflow_state",
			"priority",
			"project",
			"linked_task",
			"owner",
			"creation",
		],
		order_by="creation desc",
		ignore_permissions=True,
	)

	requester_names = _resolve_user_display_names({r["owner"] for r in requests if r.get("owner")})
	linked_task_names = [r["linked_task"] for r in requests if r.get("linked_task")]
	task_assignees: dict[str, list[str]] = {}
	if linked_task_names:
		rows = frappe.get_all("Task", filters={"name": ["in", linked_task_names]}, fields=["name", "_assign"])
		task_assignees = {
			row.name: (json.loads(row["_assign"]) if row.get("_assign") else []) for row in rows
		}
	assignee_emails: set[str] = {e for emails in task_assignees.values() for e in emails}
	assignee_names = _resolve_user_display_names(assignee_emails)

	for r in requests:
		r["raised_by_name"] = requester_names.get(r["owner"], r["owner"])
		emails = task_assignees.get(r.get("linked_task"), [])
		r["assignees"] = [assignee_names.get(e, e) for e in emails]

	return requests


@frappe.whitelist()
def withdraw_request(name: str) -> dict:
	"""The raiser, or whoever it was raised on behalf of, cancelling something no longer
	needed - a distinct terminal state from Rejected, so the history is honest about who
	ended it."""
	doc = frappe.get_doc("Request", name)
	if not _is_raiser_or_on_whose_behalf(doc):
		frappe.throw(
			_("Only the person who raised this, or who it was raised for, can withdraw it."),
			frappe.PermissionError,
		)

	_transition_workflow_state(
		doc, {"Under Review", "Approved", "Deferred", "Scheduled", "In Progress"}, "Withdrawn"
	)
	return doc.as_dict()


@frappe.whitelist()
def confirm_request_complete(name: str) -> dict:
	"""The raiser, or whoever it was raised on behalf of, signing off that finished work is
	actually acceptable - distinct from a developer marking the Task Completed, which only
	says the work was done, not accepted."""
	doc = frappe.get_doc("Request", name)
	if not _is_raiser_or_on_whose_behalf(doc):
		frappe.throw(
			_("Only the person who raised this, or who it was raised for, can confirm it's complete."),
			frappe.PermissionError,
		)

	_transition_workflow_state(doc, {"Completed"}, "Closed")
	return doc.as_dict()


@frappe.whitelist()
def delete_request(name: str) -> None:
	doc = frappe.get_doc("Request", name)
	is_reviewer = set(frappe.get_roles()) & REVIEWER_ROLES - {"Dev Team"}

	if is_reviewer:
		pass  # Projects Manager / System Manager: any Request, any state.
	elif "Dev Team" in frappe.get_roles() and doc.owner == frappe.session.user:
		if doc.workflow_state != "Under Review":
			frappe.throw(
				_("You can only delete your own requests while they're still Under Review."),
				frappe.PermissionError,
			)
	else:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	frappe.delete_doc("Request", name, ignore_permissions=True)


@frappe.whitelist()
def get_review_queue() -> list[dict]:
	if not set(frappe.get_roles()) & REVIEWER_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	rows = frappe.get_all(
		"Request",
		filters={"workflow_state": "Under Review"},
		fields=[
			"name",
			"title",
			"request_type",
			"product_area",
			"project",
			"priority",
			"owner",
			"requested_assignee",
			"creation",
		],
		order_by="creation asc",
		ignore_permissions=True,
	)
	_attach_tags("Request", rows)
	return rows


@frappe.whitelist()
def triage_request(
	name: str,
	action: str,
	project: str | None = None,
	priority: str | None = None,
	reason: str | None = None,
) -> dict:
	from frappe.model.workflow import apply_workflow

	if action in ("Reject", "Defer") and not (reason or "").strip():
		frappe.throw(_("Give a reason before you {0} this.").format(action.lower()), frappe.ValidationError)

	doc = frappe.get_doc("Request", name)
	if project:
		doc.project = project
	if priority:
		doc.priority = priority
	if project or priority:
		doc.save()

	updated = apply_workflow(doc, action)
	if reason:
		updated.add_comment("Comment", reason)
	return updated.as_dict()


@frappe.whitelist()
def get_assignable_users(txt: str | None = None, limit: int = 0) -> list[dict]:
	"""Every enabled System User, searchable by name or email - the backing query for the
	assignee link control.

	This used to return only holders of the Dev Team role, which quietly dropped people who
	were already carrying work: on this bench Dev Team is granted through a Role Profile, so
	*no* User row holds it directly and the list came back empty; on staging it returned 20
	of 441 users and still omitted two people with open tasks. Work gets handed to whoever
	is actually going to do it, so the set is the same one Frappe's own Assign To dialog
	offers - enabled, System User, minus the two built-in non-person accounts.

	Names and emails only, not sensitive - open to any logged-in user so a customer can
	name who they'd like to handle their request, same list a PM picks a real assignee from."""
	filters: list = [
		["enabled", "=", 1],
		["user_type", "=", "System User"],
		["name", "not in", RESERVED_USERS],
	]
	# Matched the way a Link field's own search does - against the email and every part of
	# the name - so "judah", "Mark" and "judah@" all find the same person.
	or_filters = []
	txt = (txt or "").strip()
	if txt:
		like = f"%{txt}%"
		or_filters = [
			["name", "like", like],
			["full_name", "like", like],
			["first_name", "like", like],
			["last_name", "like", like],
		]

	return frappe.get_all(
		"User",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "full_name"],
		order_by="full_name asc",
		limit_page_length=cint(limit) or 0,
	)


@frappe.whitelist()
def get_employees() -> list[dict]:
	"""Names only, not sensitive - lets anyone raising a request pick who it's really for
	(a PM/dev raising on a colleague's behalf), same as get_assignable_users for developers."""
	return frappe.get_all(
		"Employee",
		filters={"status": "Active"},
		fields=["name", "employee_name"],
		order_by="employee_name asc",
		ignore_permissions=True,
	)


@frappe.whitelist()
def accept_request(
	name: str,
	project: str,
	priority: str,
	complete_by: str,
	assign_to: str | list[str] | None = None,
	comment: str | None = None,
) -> dict:
	"""Approve a request and schedule it in one step, which is what creates the Task, then
	hand that Task to whoever will do the work - the one and only point in the whole lifecycle
	where a real assignment is ever created (never on the Request itself), so reassigning later
	never has to clean up a second, stale ToDo.

	complete_by/assign_to/comment mirror Frappe's own native Assign-To dialog fields (Complete
	By / Assign To / Comment) exactly, because that's what this call turns into under the hood.
	assign_to takes several people (see parse_users) - Frappe's own dialog is multi-select too,
	and one Task can genuinely need more than one pair of hands.
	"""
	from frappe.model.workflow import apply_workflow

	if not set(frappe.get_roles()) & REVIEWER_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	if not (project and priority and complete_by):
		frappe.throw(_("Set a project, a priority and a due date before accepting."), frappe.ValidationError)

	doc = frappe.get_doc("Request", name)
	assignees = parse_users(assign_to) or parse_users(doc.requested_assignee)
	if not assignees:
		frappe.throw(_("Assign this to a developer before accepting."), frappe.ValidationError)

	doc.project = project
	doc.priority = priority
	doc.save()

	doc = apply_workflow(doc, "Approve")
	doc = apply_workflow(doc, "Schedule")
	doc.reload()

	if doc.linked_task:
		frappe.db.set_value("Task", doc.linked_task, "exp_end_date", complete_by, update_modified=False)
		_assign_many(
			"Task", doc.linked_task, assignees, date=complete_by, priority=priority, description=comment
		)

	return {
		"name": doc.name,
		"workflow_state": doc.workflow_state,
		"task": doc.linked_task,
		"assigned_to": assignees,
	}


@frappe.whitelist()
def reassign_task(
	name: str, assign_to: str | list[str], complete_by: str | None = None, comment: str | None = None
) -> dict:
	"""Hands a Task to a new set of people. Closes out whoever is no longer on it, rather than
	just adding to the list, so _assign never accumulates and nobody keeps a stale ToDo for
	work that's no longer theirs. Passing several names assigns all of them; anyone already on
	the Task and named again keeps their existing ToDo untouched."""
	if not set(frappe.get_roles()) & REVIEWER_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	assignees = parse_users(assign_to)
	if not assignees:
		frappe.throw(_("Name at least one person to reassign this to."), frappe.ValidationError)

	doc = frappe.get_doc("Task", name)
	current = json.loads(doc.get("_assign") or "[]")
	for user in current:
		if user not in assignees:
			_unassign("Task", name, user)

	if complete_by:
		frappe.db.set_value("Task", name, "exp_end_date", complete_by, update_modified=False)

	_assign_many(
		"Task",
		name,
		[user for user in assignees if user not in current],
		date=complete_by or doc.exp_end_date,
		priority=doc.priority,
		description=comment,
	)

	return {"name": name, "assigned_to": assignees}


@frappe.whitelist()
def promote_to_task(name: str) -> dict:
	from frappe.model.workflow import apply_workflow

	doc = frappe.get_doc("Request", name)
	action = "Promote Note" if doc.request_type == "Note" else "Schedule"
	updated = apply_workflow(doc, action)
	return updated.as_dict()


@frappe.whitelist()
def get_backlog_board(project: str | None = None) -> dict:
	if project:
		if not frappe.has_permission("Project", "read", project):
			frappe.throw(_("Not permitted to view this project."), frappe.PermissionError)
	elif not set(frappe.get_roles()) & REVIEWER_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	filters: dict[str, str] = {"project": project} if project else {}

	tasks = frappe.get_all(
		"Task",
		filters=filters,
		fields=[
			"name",
			"subject",
			"status",
			"priority",
			"project",
			"custom_request",
			"exp_end_date",
			"_assign",
		],
		order_by="priority desc, exp_end_date asc",
		ignore_permissions=True,
	)
	requests = frappe.get_all(
		"Request",
		filters=filters,
		fields=[
			"name",
			"title",
			"request_type",
			"workflow_state",
			"priority",
			"project",
			"linked_task",
			"owner",
			"raised_by_employee",
		],
		ignore_permissions=True,
	)

	# Backlog Board's whole point is to read like the source spreadsheet did - owner and
	# requester visible on every card, not just title/priority. _assign is a JSON-encoded
	# list of user emails; resolve to full names once in bulk rather than per-row.
	assignee_emails: set[str] = set()
	for task in tasks:
		task["_assign"] = json.loads(task["_assign"]) if task.get("_assign") else []
		assignee_emails.update(task["_assign"])
	user_names = _resolve_user_display_names(assignee_emails)
	for task in tasks:
		task["assigned_to"] = [user_names.get(email, email) for email in task["_assign"]]

	requester_user_emails = {r["owner"] for r in requests if r.get("owner")}
	requester_names = _resolve_user_display_names(requester_user_emails)
	employee_ids = {r["raised_by_employee"] for r in requests if r.get("raised_by_employee")}
	employee_names: dict[str, str] = {}
	if employee_ids:
		employee_rows = frappe.get_all(
			"Employee", filters={"name": ["in", list(employee_ids)]}, fields=["name", "employee_name"]
		)
		employee_names = {row.name: row.employee_name for row in employee_rows}
	for req in requests:
		if req.get("raised_by_employee"):
			req["requested_by"] = employee_names.get(req["raised_by_employee"], req["raised_by_employee"])
		elif req.get("owner"):
			req["requested_by"] = requester_names.get(req["owner"], req["owner"])
		else:
			req["requested_by"] = None

	return {"tasks": tasks, "requests": requests}


@frappe.whitelist()
def get_upcoming_meetings(
	project: str | None = None,
	for_user: str | None = None,
	within_days: int = 14,
) -> list[dict]:
	from frappe.utils import add_to_date, now_datetime

	if project:
		if not frappe.has_permission("Project", "read", project):
			frappe.throw(_("Not permitted to view this project."), frappe.PermissionError)
		event_names = frappe.get_all(
			"Dynamic Link",
			filters={"parenttype": "Event", "link_doctype": "Project", "link_name": project},
			pluck="parent",
		)
	else:
		user = for_user or frappe.session.user
		if user != frappe.session.user and not set(frappe.get_roles()) & REVIEWER_ROLES:
			frappe.throw(_("Not permitted."), frappe.PermissionError)
		event_names = frappe.get_all(
			"Event Participants",
			filters={"parenttype": "Event", "email": user},
			pluck="parent",
		)

	if not event_names:
		return []

	now = now_datetime()
	end = add_to_date(now, days=within_days)
	return frappe.get_all(
		"Event",
		filters=[
			["name", "in", event_names],
			["starts_on", ">=", now],
			["starts_on", "<=", end],
		],
		fields=[
			"name",
			"subject",
			"starts_on",
			"ends_on",
			"event_category",
			"location",
			"google_meet_link",
		],
		order_by="starts_on asc",
		ignore_permissions=True,
	)


@frappe.whitelist()
def get_my_backlog(user: str | None = None, project: str | None = None) -> dict:
	"""Everything open assigned to a developer, one list, sorted by deadline - not split into
	today/later. Undated items sort last, not first, so a real deadline always wins."""
	user = user or frappe.session.user
	if user != frappe.session.user and not set(frappe.get_roles()) & REVIEWER_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	filters: list = [
		["_assign", "like", f"%{user}%"],
		["status", "not in", ["Completed", "Cancelled"]],
	]
	if project:
		filters.append(["project", "=", project])

	tasks = frappe.get_all(
		"Task",
		filters=filters,
		fields=["name", "subject", "status", "priority", "project", "exp_end_date"],
		ignore_permissions=True,
	)
	# get_all returns Date columns as real date objects, not strings - comparing one against
	# a string fallback for undated tasks crashes sort() outright. Sorting on
	# (has_no_date, date) instead means Python only ever compares same-typed values.
	tasks.sort(key=lambda t: (t.exp_end_date is None, t.exp_end_date))

	meetings = get_upcoming_meetings(for_user=user, within_days=1)
	return {"tasks": tasks, "meetings": meetings}


@frappe.whitelist()
def get_customer_workload(project: str) -> list[dict]:
	if not (
		set(frappe.get_roles()) & REVIEWER_ROLES
		or frappe.db.exists("Request", {"project": project, "owner": frappe.session.user})
	):
		frappe.throw(_("Not permitted to view this project."), frappe.PermissionError)

	tasks = frappe.get_all(
		"Task",
		filters={"project": project, "status": ["!=", "Cancelled"]},
		fields=["status", "_assign"],
		ignore_permissions=True,
	)
	per_dev: dict[str, dict] = {}
	for task in tasks:
		assignees = json.loads(task["_assign"]) if task.get("_assign") else []
		for email in assignees:
			bucket = per_dev.setdefault(email, {"user": email, "active_tasks": 0, "completed_tasks": 0})
			if task["status"] == "Completed":
				bucket["completed_tasks"] += 1
			else:
				bucket["active_tasks"] += 1

	names = _resolve_user_display_names(set(per_dev))
	result = []
	for email, bucket in per_dev.items():
		bucket["full_name"] = names.get(email, email)
		result.append(bucket)
	result.sort(key=lambda b: b["active_tasks"], reverse=True)
	return result


@frappe.whitelist()
def update_task_status(name: str, status: str) -> dict:
	"""Validates status against Task's own Select options, not a hardcoded list."""
	if not set(frappe.get_roles()) & REVIEWER_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	valid_statuses = frappe.get_meta("Task").get_field("status").options.split("\n")
	if status not in valid_statuses:
		frappe.throw(_("Invalid status."), frappe.ValidationError)

	if not frappe.db.exists("Task", name):
		frappe.throw(_("Task not found."), frappe.DoesNotExistError)

	frappe.db.set_value("Task", name, "status", status)
	return {"name": name, "status": status}
