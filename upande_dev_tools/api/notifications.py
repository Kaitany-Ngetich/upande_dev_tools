# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
#
# Notifications to the Dev Tools mobile app, through upande_mobile's outbox (when it is installed on the site):
# each one is written in the caller's transaction, pushed with retries by upande_mobile's scheduler, and kept in the
# person's in-app inbox. Everything here is best effort: it never breaks the save or job that asked for it.

import json

import frappe
from frappe import _
from frappe.utils import cint, getdate, today

APP_NAME = "Upande Dev Tools"
REMINDER_CACHE_PREFIX = "upande_dev_tools_reminder"
REMINDER_TTL_SECONDS = 36 * 60 * 60
REQUEST_NOTIFY_STATES = {"Approved", "Rejected", "Deferred", "Scheduled"}
OPEN_TASK_STATUSES = ["Completed", "Cancelled", "Template"]


def _push_available() -> bool:
	return "upande_mobile" in frappe.get_installed_apps()


def notify(
	users: list[str],
	title: str,
	body: str,
	route: str,
	kind: str,
	dedupe_key: str | None = None,
	data: dict | None = None,
) -> int:
	"""Queue a notification for each of `users` through upande_mobile's outbox, in the caller's transaction (it is
	sent by upande_mobile's scheduler, with retries, and kept in each person's in-app inbox). `dedupe_key` makes a
	repeat of the same event for the same person a no-op. Never raises. Returns how many were queued; a no-op when
	upande_mobile is not installed."""
	try:
		recipients = sorted({u for u in (users or []) if u and u not in ("Administrator", "Guest")})
		if not recipients or not _push_available():
			return 0
		from upande_mobile.push import notify_user

		payload = dict(data or {}, kind=kind)
		queued = 0
		for user in recipients:
			try:
				queued += cint(
					notify_user(
						APP_NAME,
						user,
						title,
						body,
						dict(payload),
						route=route,
						channel=_channel(kind),
						kind=kind,
						dedupe_key=dedupe_key,
					)
				)
			except Exception:
				frappe.log_error(title="Dev Tools push: could not queue")
		return queued
	except Exception:
		frappe.log_error(title="Dev Tools push: could not queue")
		return 0


def send_push(users: list[str], title: str, body: str, route: str, kind: str) -> int:
	"""Kept for background jobs queued before the outbox existed: they now just queue through `notify`."""
	return notify(users, title, body, route, kind)


def deployment_extra_recipients(doc) -> list[str]:
	"""Who else hears about a Deployment Request's state change, besides `requested_by_user`. Nobody for now;
	return user ids here (for example the app's owners or the on-call reviewer) to widen it."""
	return []


# The hook the deployment handler calls for extra recipients (see `deployment_extra_recipients`).
DEPLOYMENT_EXTRA_RECIPIENTS = deployment_extra_recipients


def _channel(kind: str) -> str:
	return {"task_due": "reminders", "digest": "reminders"}.get(kind, "events")


def _assignees(raw: str | None) -> list[str]:
	try:
		value = json.loads(raw) if raw else []
	except ValueError:
		return []
	return [u for u in value if isinstance(u, str)] if isinstance(value, list) else []


def _already_reminded(task: str, user: str, day: str) -> bool:
	"""True when this person was already reminded about this task today; otherwise records it."""
	key = f"{REMINDER_CACHE_PREFIX}:{day}:{task}:{user}"
	if frappe.cache.get_value(key):
		return True
	frappe.cache.set_value(key, 1, expires_in_sec=REMINDER_TTL_SECONDS)
	return False


def send_due_reminders() -> None:
	"""Hourly: remind assignees of open Tasks due today or overdue, once per task, person and day."""
	try:
		if not _push_available():
			return
		day = today()
		tasks = frappe.get_all(
			"Task",
			filters={"status": ["not in", OPEN_TASK_STATUSES], "exp_end_date": ["<=", day], "_assign": ["like", "%@%"]},
			fields=["name", "subject", "exp_end_date", "_assign"],
			ignore_permissions=True,
			limit_page_length=500,
		)
		for task in tasks:
			overdue = getdate(task.exp_end_date) < getdate(day)
			for user in _assignees(task._assign):
				if _already_reminded(task.name, user, day):
					continue
				title = _("Task overdue") if overdue else _("Task due today")
				notify(
					[user],
					title,
					task.subject or task.name,
					f"/task/{task.name}",
					"task_due",
					dedupe_key=f"task_due:{task.name}:{day}",
				)
	except Exception:
		frappe.log_error(title="Dev Tools push: due reminders failed")


def send_morning_digest() -> None:
	"""Weekday 08:00: each Dev Team user gets their planned-for-today and overdue counts."""
	try:
		if not _push_available():
			return
		day = today()
		members = frappe.get_all("Has Role", filters={"role": "Dev Team", "parenttype": "User"}, pluck="parent")
		if not members:
			return
		users = frappe.get_all(
			"User", filters={"name": ["in", members], "enabled": 1}, pluck="name", ignore_permissions=True
		)
		tasks = frappe.get_all(
			"Task",
			filters={"status": ["not in", OPEN_TASK_STATUSES]},
			fields=["custom_planned_for", "exp_end_date", "_assign"],
			ignore_permissions=True,
			limit_page_length=0,
		)
		counts: dict[str, list[int]] = {}
		for task in tasks:
			planned = bool(task.custom_planned_for and str(task.custom_planned_for) == day)
			overdue = bool(task.exp_end_date and getdate(task.exp_end_date) < getdate(day))
			if not (planned or overdue):
				continue
			for user in _assignees(task._assign):
				bucket = counts.setdefault(user, [0, 0])
				bucket[0] += int(planned)
				bucket[1] += int(overdue)
		for user in users:
			planned, overdue = counts.get(user, [0, 0])
			if not (planned or overdue):
				continue
			body = _("{0} planned for today, {1} overdue").format(planned, overdue)
			notify([user], _("Your day"), body, "/", "digest", dedupe_key=f"digest:{day}")
	except Exception:
		frappe.log_error(title="Dev Tools push: morning digest failed")


# doc_events handlers. Cheap and exception-safe: they must never break the save.


def on_todo_insert(doc, method: str | None = None) -> None:
	try:
		if doc.reference_type != "Task" or doc.status != "Open" or not doc.allocated_to:
			return
		if doc.allocated_to == frappe.session.user:
			return
		subject = frappe.db.get_value("Task", doc.reference_name, "subject") or doc.reference_name
		notify(
			[doc.allocated_to],
			_("Task assigned to you"),
			subject,
			f"/task/{doc.reference_name}",
			"task",
			dedupe_key=f"todo:{doc.name}",
		)
	except Exception:
		frappe.log_error(title="Dev Tools push: task assignment")


# Request and deployment dedupe keys name one transition (state + the save's `modified`), not one state: a hook
# fired twice for the same save is deduped, but reaching the same state again later notifies again.


def on_request_update(doc, method: str | None = None) -> None:
	try:
		state = doc.workflow_state
		if state not in REQUEST_NOTIFY_STATES or not doc.raised_by_user:
			return
		before = doc.get_doc_before_save()
		if before and before.workflow_state == state:
			return
		if doc.raised_by_user == frappe.session.user:
			return
		notify(
			[doc.raised_by_user],
			_("Request {0}").format(_(state)),
			doc.title or doc.name,
			f"/request/{doc.name}",
			"event",
			dedupe_key=f"request:{doc.name}:{state}:{doc.modified}",
		)
	except Exception:
		frappe.log_error(title="Dev Tools push: request state")


def on_deployment_update(doc, method: str | None = None) -> None:
	try:
		if not doc.requested_by_user:
			return
		before = doc.get_doc_before_save()
		if before and before.workflow_state == doc.workflow_state:
			return
		if not before and not doc.workflow_state:
			return
		recipients = [doc.requested_by_user]
		try:
			recipients += [u for u in (DEPLOYMENT_EXTRA_RECIPIENTS(doc) or []) if isinstance(u, str)]
		except Exception:
			frappe.log_error(title="Dev Tools push: deployment extra recipients")
		notify(
			recipients,
			_("Deployment {0}").format(_(doc.workflow_state or "")),
			f"{doc.app or ''} -> {doc.instance or ''}".strip(),
			"/deployments",
			"deployment",
			dedupe_key=f"deployment:{doc.name}:{doc.workflow_state or ''}:{doc.modified}",
		)
	except Exception:
		frappe.log_error(title="Dev Tools push: deployment state")
