# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import html
import json

import frappe
from frappe import _
from frappe.utils import strip_html_tags

from upande_dev_tools.api.notifications import notify
from upande_dev_tools.api.requests import REVIEWER_ROLES

COMMENT_DOCTYPES = {"Task": "/task/{0}", "Request": "/request/{0}"}
MAX_COMMENT_LENGTH = 5000


def _plain(content: str | None) -> str:
	return html.unescape(strip_html_tags(content or "")).strip()


def _require_access(doctype: str, name: str) -> None:
	if doctype not in COMMENT_DOCTYPES:
		frappe.throw(_("Comments are available on Task and Request only."), frappe.ValidationError)
	if not frappe.db.exists(doctype, name):
		frappe.throw(_("{0} not found.").format(_(doctype)), frappe.DoesNotExistError)
	if not (set(frappe.get_roles()) & REVIEWER_ROLES or frappe.has_permission(doctype, "read", name)):
		frappe.throw(_("Not permitted."), frappe.PermissionError)


@frappe.whitelist()
def get_comments(doctype: str, name: str) -> list[dict]:
	_require_access(doctype, name)
	rows = frappe.get_all(
		"Comment",
		filters={"reference_doctype": doctype, "reference_name": name, "comment_type": "Comment"},
		fields=["name", "content", "comment_email", "comment_by", "creation"],
		order_by="creation asc",
		ignore_permissions=True,
	)
	emails = {r.comment_email for r in rows if r.comment_email}
	names = {}
	if emails:
		names = {
			u.name: u.full_name
			for u in frappe.get_all(
				"User", filters={"name": ["in", list(emails)]}, fields=["name", "full_name"], ignore_permissions=True
			)
		}
	return [
		{
			"name": r.name,
			"content": _plain(r.content),
			"comment_by": r.comment_email or r.comment_by,
			"full_name": names.get(r.comment_email) or r.comment_by or r.comment_email,
			"creation": r.creation,
		}
		for r in rows
	]


@frappe.whitelist()
def add_comment(doctype: str, name: str, text: str) -> dict:
	_require_access(doctype, name)
	text = (text or "").strip()
	if not text:
		frappe.throw(_("Write something first."), frappe.ValidationError)
	if len(text) > MAX_COMMENT_LENGTH:
		frappe.throw(_("Comment is too long."), frappe.ValidationError)

	doc = frappe.get_doc(doctype, name)
	comment = doc.add_comment("Comment", frappe.utils.escape_html(text).replace("\n", "<br>"))
	_notify_participants(doc, text)
	return {
		"name": comment.name,
		"content": text,
		"comment_by": frappe.session.user,
		"full_name": frappe.utils.get_fullname(frappe.session.user),
		"creation": comment.creation,
	}


def participants(doc) -> set[str]:
	"""Everyone with a stake in the document, except the person acting now."""
	people: set[str] = set()
	try:
		people.update(u for u in json.loads(doc.get("_assign") or "[]") if isinstance(u, str))
	except ValueError:
		pass
	if doc.doctype == "Request":
		people.update(u for u in (doc.get("raised_by_user"), doc.owner) if u)
	people.update(
		u
		for u in frappe.get_all(
			"Comment",
			filters={"reference_doctype": doc.doctype, "reference_name": doc.name, "comment_type": "Comment"},
			pluck="comment_email",
			ignore_permissions=True,
		)
		if u
	)
	people.discard(frappe.session.user)
	return people


def _notify_participants(doc, text: str) -> None:
	try:
		who = frappe.utils.get_fullname(frappe.session.user)
		notify(
			sorted(participants(doc)),
			_("New comment on {0}").format(doc.get("subject") or doc.get("title") or doc.name),
			f"{who}: {text}",
			COMMENT_DOCTYPES[doc.doctype].format(doc.name),
			"event",
		)
	except Exception:
		frappe.log_error(title="Dev Tools push: comment notify")
