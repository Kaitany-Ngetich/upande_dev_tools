# Read-only checks for api/v2/backlog_board.py and the role flags of www/backlog_board_v2.py.
# Run: bench --site kaitet.local execute upande_dev_tools.tests.test_backlog_board_v2.main
import frappe

from upande_dev_tools.api import board
from upande_dev_tools.api.v2 import backlog_board as bb


def test_pure_helpers():
	assert bb._like("50%_a\\b") == "%50\\%\\_a\\\\b%"
	assert bb._loads('["a@x", "b@x"]') == ["a@x", "b@x"]
	assert bb._loads("not json") == [] and bb._loads(None) == [] and bb._loads('{"a": 1}') == []
	a = bb._args(
		{
			"kind": "Bogus",
			"stage": "open",
			"due": "later",
			"from_date": "2026-10-10",
			"to_date": "2026-01-01",
			"q": "x" * 300,
		}
	)
	assert a["kind"] == "" and a["stage"] == "open" and a["due"] == ""
	assert (a["from_date"], a["to_date"]) == ("2026-01-01", "2026-10-10"), "an inverted range is swapped"
	assert len(a["q"]) == 100
	assert bb._args({"stage": "Dropped"})["stage"] == "Dropped" and bb._args({"stage": "Nope"})["stage"] == ""
	where, params = bb._where(bb._args({"assignee": bb.NONE, "priority": bb.NONE}))
	assert "u.assign IS NULL" in where and "u.priority IS NULL" in where and params == []


def test_identities():
	frappe.set_user("Administrator")
	d = bb.get_backlog()
	k = d["kpis"]
	assert k["total"] == sum(s["count"] for s in d["stages"]) == sum(d["kinds"].values())
	assert k["open"] == k["total"] - k["done"] - k["dropped"]
	assert k["overdue"] == sum(s["late"] for s in d["stages"])
	if not d["truncated"]:
		assert len(d["items"]) == k["total"]
		assert sum(1 for i in d["items"] if i["late"]) == k["overdue"]
	assert all(i["stage"] in bb.ALL_STAGES and i["kind"] in bb.KINDS for i in d["items"])
	# a filter narrows the rows and the KPIs together
	only = bb.get_backlog(kind="Request", include_linked="1")
	assert only["kpis"]["total"] == only["kinds"]["Request"] == sum(1 for i in only["items"])
	assert {i["kind"] for i in only["items"]} <= {"Request"}
	assert all(isinstance(i["own"], bool) for i in d["items"])
	return d


def _users_by_class():
	"""One enabled user per class: no board role / board role only / manager."""
	out = {}
	for u in frappe.get_all(
		"User", filters={"enabled": 1, "user_type": "System User"}, pluck="name", limit=400
	):
		roles = set(frappe.get_roles(u))
		if u in ("Administrator", "Guest"):
			continue
		if not roles & board.BOARD_ROLES:
			out.setdefault("viewer", u)
		elif not roles & {"Projects Manager", "System Manager"}:
			out.setdefault("dev", u)
		else:
			out.setdefault("manager", u)
	return out


def test_roles():
	users = _users_by_class()
	item = frappe.get_all("Task", filters={"project": ["is", "set"]}, pluck="name", limit=1)[0]
	for cls, user in users.items():
		frappe.set_user(user)
		try:
			d = bb.get_backlog()
			detail = bb.get_backlog_item("Task", item)
			board_role = board.is_board_role()
			assert board_role == (cls != "viewer")
			assert bool(d["options"]["projects"]) == board_role, "project picker data is board-roles only"
			assert detail.get("detail") is board_role, "description and history are board-roles only"
			print(
				cls,
				user,
				"board_role",
				board_role,
				"can_create",
				board.can_create_task_directly(),
				"items",
				d["kpis"]["total"],
			)
		finally:
			frappe.set_user("Administrator")


def _refused(fn, *args, **kwargs):
	"""True when the endpoint refuses with a PermissionError (nothing is written before it does)."""
	try:
		fn(*args, **kwargs)
	except frappe.PermissionError:
		return True
	return False


def test_write_gates():
	"""The page hides these controls by role; the endpoints must refuse them regardless."""
	from upande_dev_tools.api import requests

	users = _users_by_class()
	task = frappe.get_all("Task", filters={"project": ["is", "set"]}, pluck="name", limit=1)[0]
	other_request = frappe.get_all("Request", filters={"owner": ["!=", users["dev"]]}, pluck="name", limit=1)[
		0
	]
	frappe.set_user(users["viewer"])
	try:
		assert _refused(board.set_stage, "Task", task, "Done")
		assert _refused(board.set_field, "Task", task, "title", "x")
		assert _refused(board.update_work, "Task", task, {"title": "x"})
		assert _refused(board.bulk_update, [])
		assert _refused(board.get_editable, "Task", task)
		assert _refused(board.get_preview, "Task", task)
		assert _refused(board.get_projects)
		assert _refused(board.delete_task, task)
		assert _refused(requests.reassign_task, task, "Administrator")
		assert _refused(requests.delete_request, other_request)
	finally:
		frappe.set_user("Administrator")
	frappe.set_user(users["dev"])
	try:
		assert _refused(board.delete_task, task), "a Dev Team member may only delete a task assigned to them"
		assert _refused(requests.delete_request, other_request), (
			"...and only their own request while Under Review"
		)
	finally:
		frappe.set_user("Administrator")
	frappe.db.rollback()


def main():
	frappe.db.commit = lambda *a, **k: None  # reads only
	test_pure_helpers()
	d = test_identities()
	test_roles()
	test_write_gates()
	print("ok", d["kpis"])
