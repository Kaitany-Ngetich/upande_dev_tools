# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
"""Duty rota: who is on duty when (any duty type, support first), and swap / cover requests.

Contract: duty-roster-contract.md (the Dev Tools app and the web page "Duty rota" are built to it).

ACCESS
    Read (rota, requests, people, duty types): Dev Team, Projects Manager, System Manager.
    Request a change: any reader. A non-manager may only move themselves out of a slot they are on.
    Cancel: the requester, or a manager. Decide, save / delete slots, edit duty types: managers only
    (Projects Manager, System Manager).

RULES (the app checks the same before sending; the server is the authority)
    Slot: real dates, end >= start, nobody twice. Overlapping slots of one duty type are allowed
    (a weekly header over daily rows) and only warned about.
    Request: from_user is on `slot`; to_user is an enabled user and not from_user.
        Replace: to_user is not already on `slot`.
        Swap: `swap_slot` is another slot of the same duty type, to_user is on it, from_user is not,
        and to_user is not already on `slot`.
        One pending request per person and slot: from_user on `slot` (and, for a swap, to_user on
        `swap_slot`) may not already be in another pending request.
    Approval re-checks all of that against the slots as they are NOW (they may have been edited since
    the request) and applies the change to both slots in one savepoint: all or nothing.

NOTIFICATIONS go through api.notifications.notify (upande_mobile's outbox), kind "duty". The person who
did the action is never notified about it.
"""

import json
import re
from datetime import date

import frappe
from frappe import _
from frappe.utils import add_days, cint, get_datetime, getdate, now_datetime, today

from upande_dev_tools.api.notifications import notify

SLOT = "Duty Rota Slot"
REQUEST = "Duty Change Request"
DUTY_TYPE = "Duty Type"

READ_ROLES = {"Dev Team", "Projects Manager", "System Manager"}
MANAGER_ROLES = {"Projects Manager", "System Manager"}
PEOPLE_ROLE = "Dev Team"
PM_ROLE = "Projects Manager"

KIND = "duty"
ROUTE = "/duty"
REQUESTS_ROUTE = "/duty?tab=requests"

REQUEST_TYPES = ("Swap", "Replace")
STATUSES = ("Pending", "Approved", "Rejected", "Cancelled")
CADENCES = ("Weekly", "Daily", "Custom")
WINDOW_BACK_DAYS = 28
WINDOW_AHEAD_DAYS = 26 * 7
MAX_WINDOW_DAYS = 3 * 366
MAX_SLOT_DAYS = 366
MAX_ASSIGNEES = 30
MAX_LABEL = 140
MAX_TEXT = 1000
REQUESTS_LIMIT = 300
PEOPLE_LIMIT = 200
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --------------------------------------------------------------------------- #
# Access
# --------------------------------------------------------------------------- #


def _roles(user: str | None = None) -> set[str]:
	return set(frappe.get_roles(user or frappe.session.user))


def is_manager(user: str | None = None) -> bool:
	return bool(_roles(user) & MANAGER_ROLES)


def _require_reader() -> str:
	user = frappe.session.user
	if user == "Guest" or not (_roles(user) & READ_ROLES):
		frappe.throw(_("The duty rota is for the Dev Team and project managers."), frappe.PermissionError)
	return user


def _require_manager() -> str:
	user = _require_reader()
	if not is_manager(user):
		frappe.throw(_("Only a project manager can do this."), frappe.PermissionError)
	return user


# --------------------------------------------------------------------------- #
# Small parsers
# --------------------------------------------------------------------------- #


def _text(value, length: int = MAX_TEXT) -> str:
	return value.strip()[:length] if isinstance(value, str) else ""


def parse_date(value, label: str) -> date:
	"""A real calendar date written YYYY-MM-DD (2026-02-30 is refused)."""
	text = value.strip() if isinstance(value, str) else (value.isoformat() if isinstance(value, date) else "")
	if not DATE_PATTERN.match(text):
		frappe.throw(_("{0} must be a date like 2026-11-16.").format(label), frappe.ValidationError)
	try:
		return date.fromisoformat(text)
	except ValueError:
		frappe.throw(_("{0} is not a real date.").format(label), frappe.ValidationError)


def _truthy(value) -> bool:
	if isinstance(value, str):
		return value.strip().lower() in ("1", "true", "yes", "on")
	return bool(value)


def _json(value, label: str):
	if isinstance(value, str):
		try:
			return json.loads(value)
		except ValueError:
			frappe.throw(_("{0} is not valid JSON.").format(label), frappe.ValidationError)
	return value


def _enabled_user(user, label: str) -> str:
	user = _text(user, 140)
	if not user or user in ("Guest", "Administrator") or not frappe.db.get_value("User", {"name": user, "enabled": 1}):
		frappe.throw(_("{0}: {1} is not an active user.").format(label, user or _("nobody")), frappe.ValidationError)
	return user


def _full_names(users) -> dict[str, str]:
	users = [u for u in set(users) if u]
	if not users:
		return {}
	rows = frappe.get_all("User", filters={"name": ["in", users]}, fields=["name", "full_name"], ignore_permissions=True)
	names = {r.name: (r.full_name or r.name) for r in rows}
	return {u: names.get(u, u) for u in users}


def _iso(value) -> str | None:
	return str(getdate(value)) if value else None


# --------------------------------------------------------------------------- #
# Shapes
# --------------------------------------------------------------------------- #


def slot_dict(doc) -> dict:
	return {
		"name": doc.name,
		"duty_type": doc.duty_type,
		"label": doc.label or "",
		"start_date": _iso(doc.start_date),
		"end_date": _iso(doc.end_date),
		"notes": doc.notes or "",
		"assignees": [{"user": a.user, "full_name": a.full_name or a.user} for a in (doc.assignees or [])],
	}


def _slots_by_name(names) -> dict:
	names = [n for n in set(names) if n]
	if not names:
		return {}
	rows = frappe.get_all(SLOT, filters={"name": ["in", names]}, fields=["name", "label", "start_date", "end_date"])
	return {r.name: r for r in rows}


def request_dicts(docs) -> list[dict]:
	docs = list(docs)
	people = _full_names(u for d in docs for u in (d.from_user, d.to_user, d.requested_by, d.decided_by))
	slots = _slots_by_name(n for d in docs for n in (d.slot, d.swap_slot))
	out = []
	for d in docs:
		slot = slots.get(d.slot) or frappe._dict()
		swap = slots.get(d.swap_slot) if d.swap_slot else None
		out.append(
			{
				"name": d.name,
				"duty_type": d.duty_type,
				"slot": d.slot,
				"slot_label": slot.get("label") or "",
				"slot_start": _iso(slot.get("start_date")),
				"slot_end": _iso(slot.get("end_date")),
				"request_type": d.request_type,
				"from_user": d.from_user,
				"from_user_name": people.get(d.from_user, d.from_user),
				"to_user": d.to_user,
				"to_user_name": people.get(d.to_user, d.to_user),
				"swap_slot": d.swap_slot or None,
				"swap_slot_label": (swap.label or "") if swap else None,
				"swap_slot_start": _iso(swap.start_date) if swap else None,
				"swap_slot_end": _iso(swap.end_date) if swap else None,
				"reason": d.reason or "",
				"status": d.status,
				"requested_by": d.requested_by,
				"requested_by_name": people.get(d.requested_by, d.requested_by),
				"decided_by": d.decided_by or None,
				"decided_by_name": people.get(d.decided_by) if d.decided_by else None,
				"decision_note": d.decision_note or None,
				"creation": get_datetime(d.creation).isoformat() if d.creation else None,
			}
		)
	return out


def request_dict(doc) -> dict:
	return request_dicts([doc])[0]


def slot_title(slot) -> str:
	if slot.label:
		return slot.label
	start, end = _iso(slot.start_date), _iso(slot.end_date)
	return start if start == end else f"{start} to {end}"


# --------------------------------------------------------------------------- #
# Validation shared by the doctypes, the API and approval
# --------------------------------------------------------------------------- #


def users_on(slot) -> list[str]:
	return [a.user for a in (slot.assignees or []) if a.user]


def validate_slot(doc) -> None:
	"""Called from Duty Rota Slot.validate: the rules hold however the slot is saved (API, desk, import)."""
	if not doc.duty_type:
		frappe.throw(_("Pick a duty type."), frappe.ValidationError)
	start, end = getdate(doc.start_date), getdate(doc.end_date)
	if not start or not end:
		frappe.throw(_("A slot needs a start and an end date."), frappe.ValidationError)
	if end < start:
		frappe.throw(_("The end date is before the start date."), frappe.ValidationError)
	if (end - start).days >= MAX_SLOT_DAYS:
		frappe.throw(_("A slot can be at most a year long."), frappe.ValidationError)
	users = users_on(doc)
	if len(users) != len(set(users)):
		frappe.throw(_("Someone is listed twice on this slot."), frappe.ValidationError)
	if len(users) > MAX_ASSIGNEES:
		frappe.throw(_("A slot can have at most {0} people.").format(MAX_ASSIGNEES), frappe.ValidationError)


def validate_change(request_type, slot, swap_slot, from_user, to_user) -> None:
	"""The request rules against the slots as they are now. Used when a request is made and again at approval."""
	if request_type not in REQUEST_TYPES:
		frappe.throw(_("A request is a Swap or a Replace."), frappe.ValidationError)
	if not to_user:
		frappe.throw(_("Pick who comes in."), frappe.ValidationError)
	if to_user == from_user:
		frappe.throw(_("Pick someone else."), frappe.ValidationError)
	on_slot = users_on(slot)
	if from_user not in on_slot:
		frappe.throw(
			_("{0} is no longer on {1}.").format(_full_names([from_user])[from_user], slot_title(slot)), frappe.ValidationError
		)
	if to_user in on_slot:
		frappe.throw(
			_("{0} is already on {1}.").format(_full_names([to_user])[to_user], slot_title(slot)), frappe.ValidationError
		)
	if request_type == "Swap":
		if not swap_slot:
			frappe.throw(_("Pick the slot taken in return."), frappe.ValidationError)
		if swap_slot.name == slot.name:
			frappe.throw(_("Pick a different slot to swap with."), frappe.ValidationError)
		if swap_slot.duty_type != slot.duty_type:
			frappe.throw(_("Both slots of a swap must be the same duty type."), frappe.ValidationError)
		on_swap = users_on(swap_slot)
		if to_user not in on_swap:
			frappe.throw(
				_("{0} is no longer on {1}.").format(_full_names([to_user])[to_user], slot_title(swap_slot)),
				frappe.ValidationError,
			)
		if from_user in on_swap:
			frappe.throw(
				_("{0} is already on {1}.").format(_full_names([from_user])[from_user], slot_title(swap_slot)),
				frappe.ValidationError,
			)


def _pending_for(slot: str, user: str, exclude: str | None = None) -> str | None:
	"""A pending request that already moves `user` out of `slot` (from either side of a swap)."""
	for filters in ({"slot": slot, "from_user": user}, {"swap_slot": slot, "to_user": user, "request_type": "Swap"}):
		filters = dict(filters, status="Pending")
		if exclude:
			filters["name"] = ["!=", exclude]
		found = frappe.db.get_value(REQUEST, filters, "name")
		if found:
			return found
	return None


def _load_slot(name, for_update: bool = False, label: str | None = None):
	name = _text(name, 140)
	if not name or not frappe.db.exists(SLOT, name):
		frappe.throw(_("{0} was not found. It may have been deleted.").format(label or _("That slot")), frappe.DoesNotExistError)
	return frappe.get_doc(SLOT, name, for_update=for_update)


def _load_request(name, for_update: bool = False):
	name = _text(name, 140)
	if not name or not frappe.db.exists(REQUEST, name):
		frappe.throw(_("That request was not found."), frappe.DoesNotExistError)
	return frappe.get_doc(REQUEST, name, for_update=for_update)


# --------------------------------------------------------------------------- #
# Notifications
# --------------------------------------------------------------------------- #


def _send(users, title: str, body: str, route: str, dedupe_key: str) -> int:
	"""Through the outbox; never to the person who did the action. Best effort, never raises."""
	me = frappe.session.user
	return notify([u for u in set(users) if u and u != me], title, body, route, KIND, dedupe_key=dedupe_key)


def project_managers() -> list[str]:
	members = frappe.get_all("Has Role", filters={"role": PM_ROLE, "parenttype": "User"}, pluck="parent")
	if not members:
		return []
	return frappe.get_all("User", filters={"name": ["in", members], "enabled": 1}, pluck="name", ignore_permissions=True)


def request_summary(req: dict) -> str:
	slot = req["slot_label"] or req["slot_start"] or req["slot"]
	if req["request_type"] == "Swap":
		other = req["swap_slot_label"] or req["swap_slot_start"] or ""
		return f"{req['from_user_name']} swaps {slot} with {req['to_user_name']}" + (f" ({other})" if other else "")
	return f"{req['to_user_name']} covers {req['from_user_name']} on {slot}"


def notify_new_request(doc) -> None:
	req = request_dict(doc)
	key = f"duty-req:{doc.name}:Pending"
	summary = request_summary(req)
	_send(project_managers(), _("Duty swap requested"), summary, REQUESTS_ROUTE, key)
	# The other person: asked to swap, or to cover.
	title = _("Duty swap requested") if doc.request_type == "Swap" else _("Duty cover requested")
	_send([doc.to_user], title, summary, REQUESTS_ROUTE, key)


def notify_decision(doc) -> None:
	req = request_dict(doc)
	title = _("Swap approved") if doc.status == "Approved" else _("Swap rejected")
	body = request_summary(req) + (f" · {doc.decision_note}" if doc.decision_note else "")
	_send([doc.requested_by, doc.from_user, doc.to_user], title, body, REQUESTS_ROUTE, f"duty-req:{doc.name}:{doc.status}")


def notify_slot_change(slot, before_users, before_dates, key_suffix: str | None = None) -> None:
	"""Tell the people a PM's edit concerns: who was added, who was removed, and (when the dates moved) who stayed.
	One key per save (`duty-slot:<name>:<modified>`), so a repeated call for the same save notifies once."""
	key = f"duty-slot:{slot.name}:{key_suffix or slot.modified}"
	now_users = users_on(slot) if key_suffix != "deleted" else []
	added = [u for u in now_users if u not in before_users]
	removed = [u for u in before_users if u not in now_users]
	title = slot_title(slot)
	when = _iso(slot.start_date) if _iso(slot.start_date) == _iso(slot.end_date) else f"{_iso(slot.start_date)} to {_iso(slot.end_date)}"
	if added:
		_send(added, _("You are on duty"), f"{slot.duty_type}: {title} ({when})", ROUTE, key)
	if removed:
		_send(removed, _("You are off duty"), f"{slot.duty_type}: {title} ({when})", ROUTE, key)
	dates_moved = before_dates and before_dates != (_iso(slot.start_date), _iso(slot.end_date))
	stayed = [u for u in now_users if u in before_users]
	if dates_moved and stayed:
		_send(stayed, _("Duty dates changed"), f"{slot.duty_type}: {title} is now {when}", ROUTE, key)


# --------------------------------------------------------------------------- #
# Read
# --------------------------------------------------------------------------- #


@frappe.whitelist(methods=["GET", "POST"])
def duty_types() -> list[dict]:
	_require_reader()
	return frappe.get_all(
		DUTY_TYPE,
		filters={"is_active": 1},
		fields=["name", "duty_name", "description", "default_cadence", "people_per_slot", "is_active"],
		order_by="duty_name asc",
	)


@frappe.whitelist(methods=["GET", "POST"])
def all_duty_types() -> list[dict]:
	"""Master Data: every duty type, inactive ones too, with how many slots use each."""
	_require_reader()
	rows = frappe.get_all(
		DUTY_TYPE,
		fields=["name", "duty_name", "description", "default_cadence", "people_per_slot", "is_active"],
		order_by="duty_name asc",
	)
	counts = dict(frappe.db.sql(f"select duty_type, count(*) from `tab{SLOT}` group by duty_type"))
	for row in rows:
		row["slots"] = cint(counts.get(row.name))
	return rows


@frappe.whitelist(methods=["GET", "POST"])
def rota(duty_type: str, start: str | None = None, end: str | None = None) -> dict:
	user = _require_reader()
	duty_type = _text(duty_type, 140)
	if not duty_type or not frappe.db.exists(DUTY_TYPE, duty_type):
		frappe.throw(_("Unknown duty type."), frappe.ValidationError)
	day = getdate(today())
	window_start = parse_date(start, _("Start")) if start else add_days(day, -WINDOW_BACK_DAYS)
	window_end = parse_date(end, _("End")) if end else add_days(day, WINDOW_AHEAD_DAYS)
	window_start, window_end = getdate(window_start), getdate(window_end)
	if window_end < window_start:
		frappe.throw(_("The end of the window is before its start."), frappe.ValidationError)
	if (window_end - window_start).days > MAX_WINDOW_DAYS:
		frappe.throw(_("Ask for at most three years at a time."), frappe.ValidationError)
	names = frappe.get_all(
		SLOT,
		filters={"duty_type": duty_type, "end_date": [">=", window_start], "start_date": ["<=", window_end]},
		pluck="name",
		order_by="start_date asc, end_date asc, name asc",
		limit_page_length=0,
	)
	return {
		"duty_type": duty_type,
		"slots": [slot_dict(frappe.get_doc(SLOT, n)) for n in names],
		"me": user,
		"can_manage": is_manager(user),
	}


@frappe.whitelist(methods=["GET", "POST"])
def change_requests(duty_type: str | None = None, status: str | None = None, mine: int | str | bool = 0) -> list[dict]:
	user = _require_reader()
	filters = {}
	if duty_type:
		filters["duty_type"] = _text(duty_type, 140)
	if status:
		if status not in STATUSES:
			frappe.throw(_("Unknown status."), frappe.ValidationError)
		filters["status"] = status
	or_filters = None
	if _truthy(mine) or not is_manager(user):
		or_filters = {"requested_by": user, "from_user": user, "to_user": user}
	names = frappe.get_all(
		REQUEST,
		filters=filters,
		or_filters=or_filters,
		pluck="name",
		order_by="creation desc",
		limit_page_length=REQUESTS_LIMIT,
	)
	return request_dicts(frappe.get_doc(REQUEST, n) for n in names)


@frappe.whitelist(methods=["GET", "POST"])
def people(search: str | None = None) -> list[dict]:
	_require_reader()
	members = frappe.get_all("Has Role", filters={"role": PEOPLE_ROLE, "parenttype": "User"}, pluck="parent")
	if not members:
		return []
	rows = frappe.get_all(
		"User",
		filters={"name": ["in", list(set(members) - {"Administrator", "Guest"})], "enabled": 1},
		fields=["name", "full_name"],
		ignore_permissions=True,
		limit_page_length=0,
	)
	q = _text(search, 100).lower()
	out = [
		{"user": r.name, "full_name": r.full_name or r.name}
		for r in rows
		if not q or q in (r.full_name or "").lower() or q in r.name.lower()
	]
	return sorted(out, key=lambda p: p["full_name"].lower())[:PEOPLE_LIMIT]


# --------------------------------------------------------------------------- #
# Write: requests
# --------------------------------------------------------------------------- #


@frappe.whitelist(methods=["POST"])
def request_change(
	slot: str,
	request_type: str,
	to_user: str,
	from_user: str | None = None,
	swap_slot: str | None = None,
	reason: str | None = None,
) -> dict:
	user = _require_reader()
	manager = is_manager(user)
	slot_doc = _load_slot(slot)
	from_user = _text(from_user, 140) or user
	if not manager and from_user != user:
		frappe.throw(_("You can only ask to move yourself out of a slot."), frappe.PermissionError)
	if request_type not in REQUEST_TYPES:
		frappe.throw(_("A request is a Swap or a Replace."), frappe.ValidationError)
	to_user = _enabled_user(to_user, _("Who comes in"))
	swap_doc = None
	if request_type == "Swap":
		if not swap_slot:
			frappe.throw(_("Pick the slot taken in return."), frappe.ValidationError)
		swap_doc = _load_slot(swap_slot, label=_("The slot to swap with"))
	validate_change(request_type, slot_doc, swap_doc, from_user, to_user)
	busy = _pending_for(slot_doc.name, from_user) or (swap_doc and _pending_for(swap_doc.name, to_user))
	if busy:
		frappe.throw(
			_("There is already a pending request ({0}) for this. Wait for it to be decided or cancel it.").format(busy),
			frappe.ValidationError,
		)
	doc = frappe.get_doc(
		{
			"doctype": REQUEST,
			"duty_type": slot_doc.duty_type,
			"slot": slot_doc.name,
			"request_type": request_type,
			"from_user": from_user,
			"to_user": to_user,
			"swap_slot": swap_doc.name if swap_doc else None,
			"reason": _text(reason),
			"status": "Pending",
			"requested_by": user,
		}
	)
	doc.insert(ignore_permissions=True)
	notify_new_request(doc)
	return request_dict(doc)


@frappe.whitelist(methods=["POST"])
def cancel_request(name: str) -> dict:
	user = _require_reader()
	doc = _load_request(name, for_update=True)
	if doc.requested_by != user and not is_manager(user):
		frappe.throw(_("Only the person who asked, or a project manager, can cancel this."), frappe.PermissionError)
	if doc.status != "Pending":
		frappe.throw(_("This request is no longer pending."), frappe.ValidationError)
	doc.status = "Cancelled"
	doc.decided_by = user
	doc.decided_at = now_datetime()
	doc.save(ignore_permissions=True)
	return request_dict(doc)


@frappe.whitelist(methods=["POST"])
def decide(name: str, approve: int | str | bool, note: str | None = None) -> dict:
	user = _require_manager()
	approve = _truthy(approve)
	doc = _load_request(name, for_update=True)
	if doc.status != "Pending":
		frappe.throw(_("This request is no longer pending."), frappe.ValidationError)
	savepoint = "duty_decide_" + frappe.generate_hash(length=8)
	frappe.db.savepoint(savepoint)
	try:
		if approve:
			apply_change(doc)
		doc.status = "Approved" if approve else "Rejected"
		doc.decided_by = user
		doc.decided_at = now_datetime()
		doc.decision_note = _text(note)
		doc.save(ignore_permissions=True)
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		raise
	frappe.db.release_savepoint(savepoint)
	notify_decision(doc)
	return request_dict(doc)


def apply_change(doc) -> None:
	"""Apply an approved request to its slot(s). Re-checks everything against the slots as they are now; the caller
	holds a savepoint, so a failure half-way leaves both slots untouched."""
	slot = _load_slot(doc.slot, for_update=True, label=_("The slot of this request"))
	swap = _load_slot(doc.swap_slot, for_update=True, label=_("The slot to swap with")) if doc.request_type == "Swap" else None
	_enabled_user(doc.to_user, _("Who comes in"))
	validate_change(doc.request_type, slot, swap, doc.from_user, doc.to_user)
	names = _full_names([doc.from_user, doc.to_user])
	_replace(slot, doc.from_user, doc.to_user, names[doc.to_user])
	slot.save(ignore_permissions=True)
	if swap:
		_replace(swap, doc.to_user, doc.from_user, names[doc.from_user])
		swap.save(ignore_permissions=True)


def _replace(slot, old: str, new: str, full_name: str) -> None:
	for row in slot.assignees:
		if row.user == old:
			row.user = new
			row.full_name = full_name
			return


# --------------------------------------------------------------------------- #
# Write: slots and duty types (managers)
# --------------------------------------------------------------------------- #


def _overlap_warning(doc) -> None:
	"""Overlapping slots of one duty type are allowed (a weekly header over daily rows); say so, never block."""
	others = frappe.get_all(
		SLOT,
		filters={
			"duty_type": doc.duty_type,
			"name": ["!=", doc.name or ""],
			"start_date": ["<=", doc.end_date],
			"end_date": [">=", doc.start_date],
		},
		fields=["name", "label", "start_date", "end_date"],
		limit_page_length=5,
	)
	if others:
		frappe.msgprint(
			_("This slot overlaps {0}.").format(", ".join(slot_title(o) for o in others)),
			indicator="orange",
			alert=True,
		)
	wanted = cint(frappe.db.get_value(DUTY_TYPE, doc.duty_type, "people_per_slot"))
	if wanted and len(users_on(doc)) < wanted:
		frappe.msgprint(
			_("{0} usually has {1} people per slot; this one has {2}.").format(doc.duty_type, wanted, len(users_on(doc))),
			indicator="orange",
			alert=True,
		)


@frappe.whitelist(methods=["POST"])
def save_slot(slot: str | dict) -> dict:
	_require_manager()
	data = _json(slot, _("Slot"))
	if not isinstance(data, dict):
		frappe.throw(_("Slot must be an object."), frappe.ValidationError)
	duty_type = _text(data.get("duty_type"), 140)
	if not duty_type or not frappe.db.exists(DUTY_TYPE, duty_type):
		frappe.throw(_("Pick a duty type."), frappe.ValidationError)
	start = parse_date(data.get("start_date"), _("Start date"))
	end = parse_date(data.get("end_date"), _("End date"))
	if end < start:
		frappe.throw(_("The end date is before the start date."), frappe.ValidationError)
	assignees = data.get("assignees") or []
	if not isinstance(assignees, list):
		frappe.throw(_("Assignees must be a list of users."), frappe.ValidationError)
	users = [a.get("user") if isinstance(a, dict) else a for a in assignees]
	if any(not isinstance(u, str) or not u.strip() for u in users):
		frappe.throw(_("Assignees must be a list of users."), frappe.ValidationError)
	users = [u.strip() for u in users]
	if len(users) != len(set(users)):
		frappe.throw(_("Someone is listed twice."), frappe.ValidationError)
	users = [_enabled_user(u, _("Assignee")) for u in users]

	name = _text(data.get("name"), 140)
	if name:
		doc = _load_slot(name, for_update=True)
		before_users, before_dates = users_on(doc), (_iso(doc.start_date), _iso(doc.end_date))
	else:
		doc = frappe.new_doc(SLOT)
		before_users, before_dates = [], None
	names = _full_names(users)
	doc.duty_type = duty_type
	doc.label = _text(data.get("label"), MAX_LABEL)
	doc.notes = _text(data.get("notes"))
	doc.start_date = start
	doc.end_date = end
	# The table is rewritten in the given order (the order the PM sees).
	doc.set("assignees", [{"user": u, "full_name": names[u]} for u in users])
	doc.save(ignore_permissions=True) if name else doc.insert(ignore_permissions=True)
	_overlap_warning(doc)
	notify_slot_change(doc, before_users, before_dates)
	return slot_dict(doc)


@frappe.whitelist(methods=["POST"])
def delete_slot(name: str) -> dict:
	_require_manager()
	doc = _load_slot(name, for_update=True)
	pending = frappe.get_all(
		REQUEST, filters={"status": "Pending"}, or_filters={"slot": doc.name, "swap_slot": doc.name}, pluck="name", limit_page_length=1
	)
	if pending:
		frappe.throw(_("A pending request ({0}) points at this slot. Decide it first.").format(pending[0]), frappe.ValidationError)
	before = users_on(doc)
	# Decided requests keep their history; their slot simply shows as gone.
	frappe.delete_doc(SLOT, doc.name, ignore_permissions=True, force=True)
	notify_slot_change(doc, before, None, key_suffix="deleted")
	return {"deleted": 1}


@frappe.whitelist(methods=["POST"])
def save_duty_type(duty_type: str | dict) -> dict:
	"""Master Data: create or edit a duty type (managers). The name is the duty name and is not renamed here."""
	_require_manager()
	data = _json(duty_type, _("Duty type"))
	if not isinstance(data, dict):
		frappe.throw(_("Duty type must be an object."), frappe.ValidationError)
	duty_name = _text(data.get("duty_name"), MAX_LABEL)
	if not duty_name:
		frappe.throw(_("A duty type needs a name."), frappe.ValidationError)
	cadence = data.get("default_cadence") or "Weekly"
	if cadence not in CADENCES:
		frappe.throw(_("Cadence is Weekly, Daily or Custom."), frappe.ValidationError)
	per_slot = cint(data.get("people_per_slot"))
	if per_slot < 0 or per_slot > MAX_ASSIGNEES:
		frappe.throw(_("People per slot must be between 0 and {0}.").format(MAX_ASSIGNEES), frappe.ValidationError)
	name = _text(data.get("name"), 140)
	if name:
		if not frappe.db.exists(DUTY_TYPE, name):
			frappe.throw(_("That duty type was not found."), frappe.DoesNotExistError)
		if duty_name != name:
			frappe.throw(_("A duty type cannot be renamed here."), frappe.ValidationError)
		doc = frappe.get_doc(DUTY_TYPE, name)
	else:
		if frappe.db.exists(DUTY_TYPE, duty_name):
			frappe.throw(_("{0} already exists.").format(duty_name), frappe.DuplicateEntryError)
		doc = frappe.new_doc(DUTY_TYPE)
		doc.duty_name = duty_name
	doc.description = _text(data.get("description"))
	doc.default_cadence = cadence
	doc.people_per_slot = per_slot
	doc.is_active = 1 if _truthy(data.get("is_active", 1)) else 0
	doc.save(ignore_permissions=True) if name else doc.insert(ignore_permissions=True)
	return {
		"name": doc.name,
		"duty_name": doc.duty_name,
		"description": doc.description or "",
		"default_cadence": doc.default_cadence,
		"people_per_slot": cint(doc.people_per_slot),
		"is_active": cint(doc.is_active),
	}


# --------------------------------------------------------------------------- #
# Scheduler
# --------------------------------------------------------------------------- #


def send_start_reminders() -> None:
	"""Daily: remind the people on every slot that starts tomorrow (once per slot and person)."""
	try:
		tomorrow = add_days(getdate(today()), 1)
		for name in frappe.get_all(SLOT, filters={"start_date": tomorrow}, pluck="name", limit_page_length=0):
			slot = frappe.get_doc(SLOT, name)
			notify(
				users_on(slot),
				_("Your duty starts tomorrow"),
				f"{slot.duty_type}: {slot_title(slot)}",
				ROUTE,
				KIND,
				dedupe_key=f"duty-start:{slot.name}",
			)
	except Exception:
		frappe.log_error(title="Duty rota: start reminders failed")
