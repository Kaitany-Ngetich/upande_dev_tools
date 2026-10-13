# Unit checks for the pure helpers of api/v2/dev_dashboard.py and a read-only permission check.
# Run: bench --site kaitet.local execute upande_dev_tools.tests.test_dev_dashboard_v2.main
# (the helper checks alone also run with the bench's python: no site is needed for them).
import frappe

from upande_dev_tools.api.v2 import dev_dashboard as D


def check_helpers():
	s = D.parse_status_v2(
		"# branch.oid abcdef1234567\n# branch.head main\n# branch.upstream upstream/main\n"
		"# branch.ab +2 -3\n1 .M N... 100644 100644 100644 a b file.py\n? new.txt\n? other.txt\n"
	)
	assert (s["head"], s["upstream"], s["ahead"], s["behind"], s["tracked"], s["untracked"]) == (
		"main",
		"upstream/main",
		2,
		3,
		1,
		2,
	)
	assert D.parse_status_v2("")["ahead"] == 0

	assert D.sync_state(False, 5, 5) == "no_upstream"
	assert D.sync_state(True, 1, 1) == "diverged"
	assert D.sync_state(True, 0, 1) == "behind"
	assert D.sync_state(True, 1, 0) == "ahead"
	assert D.sync_state(True, 0, 0) == "synced"

	cfg = (
		"remote.origin.url https://u:tok@github.com/a/b.git\n"
		"remote.upstream.url git@github.com:org/repo.git\nbranch.dev.x.remote upstream\n"
	)
	assert D.parse_remote_config(cfg, "dev.x") == "git@github.com:org/repo.git"
	assert D.parse_remote_config(cfg, "other") == "https://u:tok@github.com/a/b.git"
	assert D.parse_remote_config("", "main") is None

	assert D._clean_repo_url("https://user:secret@github.com/a/b.git?x=1#f") == "https://github.com/a/b"
	assert D._clean_repo_url("git@github.com:org/repo.git") == "https://github.com/org/repo"
	assert D._clean_repo_url("ssh://git@host/x") is None
	assert D._clean_repo_url("") is None

	red = D._redact("password=hunter2 and https://u:p@h.com/x Bearer abc.def")
	assert "hunter2" not in red and "u:p@" not in red and "abc.def" not in red
	assert D._redact("a\n\n b", keep_lines=True) == "a\n\nb"


def check_permissions():
	"""Read-only: an enabled user without Dev Team must be refused; Dev Team users get the payload."""
	frappe.db.commit = lambda *a, **k: None
	out = {}
	for user in frappe.get_all("User", filters={"enabled": 1}, pluck="name", limit=60):
		roles = set(frappe.get_roles(user))
		if user in ("Guest",):
			continue
		frappe.set_user(user)
		try:
			D.get_dev_dashboard()
			out[user] = "ok"
		except frappe.PermissionError:
			out[user] = "denied"
		finally:
			frappe.set_user("Administrator")
		assert (out[user] == "ok") == ("Dev Team" in roles), (user, out[user], roles)
	return out


def check_duplicate_endpoint():
	"""get_deployment_for_duplicate follows the current recent-deployments rule (viewer roles)."""
	name = frappe.db.get_value("Deployment Request", {}, "name")
	for user in frappe.get_all("User", filters={"enabled": 1}, pluck="name", limit=60):
		if user == "Guest":
			continue
		allowed = bool(D.DEPLOYMENT_VIEWER_ROLES & set(frappe.get_roles(user)))
		frappe.set_user(user)
		try:
			D.get_deployment_for_duplicate(name)
			got = True
		except frappe.PermissionError:
			got = False
		finally:
			frappe.set_user("Administrator")
		assert got == allowed, (user, got, allowed)


def check_unreadable_and_filters():
	"""An unreadable app must not break sorting/filtering, and the Behind/Not pushed filters
	include diverged apps (so they match the Behind remote card)."""
	good = {
		"error": None,
		"sync": "synced",
		"ahead": 0,
		"behind": 0,
		"changes": 0,
		"branch": "main",
		"tracked_changes": 0,
	}
	live = [
		{"app": "a_ok", **good, "repo_url": None},
		{"app": "b_bad", **D._unreadable("b_bad", "x")},
		{"app": "c_div", **good, "sync": "diverged", "ahead": 2, "behind": 3},
		{"app": "d_beh", **good, "sync": "behind", "behind": 1},
	]
	original = D._live_git
	D._live_git = lambda refresh=False: (live, 0.0, False)
	try:
		whole = D._apps_section("", "", False)
		t = whole["totals"]
		assert (t["apps"], t["unreadable"], t["up_to_date"], t["needs_attention"]) == (4, 1, 1, 3)
		assert (
			t["apps"]
			== t["synced"] + t["behind"] + t["ahead"] + t["diverged"] + t["no_upstream"] + t["unreadable"]
		)
		assert [r["app"] for r in D._apps_section("", "behind", False)["rows"]] == ["c_div", "d_beh"]
		assert [r["app"] for r in D._apps_section("", "ahead", False)["rows"]] == ["c_div"]
		assert [r["app"] for r in D._apps_section("", "clean", False)["rows"]] == ["a_ok"]
	finally:
		D._live_git = original


def main():
	check_helpers()
	check_unreadable_and_filters()
	print("filters ok")
	print("helpers ok")
	check_duplicate_endpoint()
	print("duplicate endpoint ok")
	res = check_permissions()
	print(
		"permissions ok:",
		sum(v == "ok" for v in res.values()),
		"allowed,",
		sum(v == "denied" for v in res.values()),
		"denied",
	)
