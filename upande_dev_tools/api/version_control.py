# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import os
import subprocess

import frappe
from frappe.utils import get_bench_path, now_datetime


class GitCommandError(Exception):
	pass


def run_git_command(repo_path, args, timeout=30):
	"""Execute git commands safely."""
	try:
		result = subprocess.run(
			["git", *args],
			cwd=repo_path,
			capture_output=True,
			text=True,
			check=True,
			timeout=timeout,
		)
		return result.stdout.strip()

	except subprocess.CalledProcessError as e:
		raise GitCommandError(e.stderr.strip() or e.stdout.strip() or str(e))

	except subprocess.TimeoutExpired:
		raise GitCommandError(f"Git command timed out: git {' '.join(args)}")


def get_repo_path(app_name):
	"""Return repo root path."""
	repo_path = os.path.join(
		get_bench_path(),
		"apps",
		app_name,
	)

	if not os.path.exists(repo_path):
		raise Exception(f"App '{app_name}' not found.")

	if not os.path.exists(os.path.join(repo_path, ".git")):
		raise Exception(f"'{app_name}' is not a git repository.")

	return repo_path


def get_current_branch(repo_path):
	return run_git_command(
		repo_path,
		["branch", "--show-current"],
		timeout=10,
	)


def get_upstream_branch(repo_path):
	try:
		return run_git_command(
			repo_path,
			[
				"rev-parse",
				"--abbrev-ref",
				"--symbolic-full-name",
				"@{u}",
			],
			timeout=10,
		)
	except Exception:
		return None


def get_working_tree_status(repo_path):
	return run_git_command(
		repo_path,
		["status", "--porcelain"],
		timeout=10,
	)


def get_ahead_behind(repo_path, upstream):
	behind = int(
		run_git_command(
			repo_path,
			["rev-list", f"HEAD..{upstream}", "--count"],
			timeout=10,
		)
	)

	ahead = int(
		run_git_command(
			repo_path,
			["rev-list", f"{upstream}..HEAD", "--count"],
			timeout=10,
		)
	)

	return ahead, behind


@frappe.whitelist()
def analyse_repository(app_name: str):
	"""
	Main API callable from Desk, DocTypes, Pages.
	"""

	repo_path = get_repo_path(app_name)

	run_git_command(
		repo_path,
		["fetch", "--all", "--prune"],
		timeout=45,
	)

	current_branch = get_current_branch(repo_path)
	upstream = get_upstream_branch(repo_path)

	if not upstream:
		return {
			"status": "ERROR",
			"message": (f"Branch '{current_branch}' has no upstream tracking branch."),
		}

	ahead, behind = get_ahead_behind(
		repo_path,
		upstream,
	)

	dirty = bool(get_working_tree_status(repo_path))

	if behind > 0:
		status = "STALE"

	elif ahead > 0:
		status = "AHEAD"

	elif dirty:
		status = "DIRTY"

	else:
		status = "CLEAN"

	return {
		"status": status,
		"branch": current_branch,
		"upstream": upstream,
		"ahead": ahead,
		"behind": behind,
		"dirty": dirty,
	}


RISK_BY_STATUS = {
	"CLEAN": "Low",
	"AHEAD": "Medium",
	"STALE": "Medium",
	"DIRTY": "High",
	"ERROR": "Critical",
}

MESSAGE_BY_STATUS = {
	"CLEAN": "Fully synced with {upstream}",
	"AHEAD": "{ahead} commit(s) not pushed to {upstream}",
	"STALE": "{behind} commit(s) behind {upstream}",
	"DIRTY": "Uncommitted changes in the working tree",
}


@frappe.whitelist()
def scan_bench(fetch: int = 0) -> dict:
	"""Read every installed app's git state and record it, which is what the
	dashboard reads. Nothing wrote these rows before, so the page had nothing
	to show however healthy the bench was.

	Fetching from every remote is slow and needs the network, so it is off by
	default - the comparison then runs against the last fetched remote.
	"""
	checked = 0
	failed = []

	for app_name in frappe.get_installed_apps():
		try:
			result = _analyse(app_name, bool(int(fetch)))
		except Exception:
			failed.append(app_name)
			continue

		doc = (
			frappe.get_doc("Module Version Check", app_name)
			if frappe.db.exists("Module Version Check", app_name)
			else frappe.new_doc("Module Version Check")
		)
		doc.module_name = app_name
		doc.app_folder = app_name
		doc.environment = "Local Machine"
		doc.current_branch = result.get("branch")
		doc.upstream_branch = result.get("upstream")
		doc.commits_ahead = result.get("ahead") or 0
		doc.commits_behind = result.get("behind") or 0
		doc.has_uncommitted_changes = 1 if result.get("dirty") else 0
		doc.status = (result.get("status") or "").title() or "Clean"
		doc.risk_level = RISK_BY_STATUS.get(result.get("status"), "Medium")
		doc.safe_to_deploy = 1 if result.get("status") == "CLEAN" else 0
		doc.last_checked_at = now_datetime()
		doc.last_checked_by = frappe.session.user
		doc.status_message = result.get("message") or MESSAGE_BY_STATUS.get(result.get("status"), "").format(
			upstream=result.get("upstream") or "remote",
			ahead=result.get("ahead") or 0,
			behind=result.get("behind") or 0,
		)
		doc.flags.ignore_permissions = True
		doc.save()
		checked += 1

	# nosemgrep: frappe-manual-commit - whitelisted endpoint; the checked rows must persist before the result is returned.
	frappe.db.commit()
	return {"checked": checked, "failed": failed}


def _analyse(app_name: str, fetch: bool) -> dict:
	repo_path = get_repo_path(app_name)
	if fetch:
		run_git_command(repo_path, ["fetch", "--all", "--prune"], timeout=45)

	branch = get_current_branch(repo_path)
	upstream = get_upstream_branch(repo_path)
	dirty = bool(get_working_tree_status(repo_path))

	if not upstream:
		return {
			"status": "DIRTY" if dirty else "CLEAN",
			"branch": branch,
			"upstream": None,
			"ahead": 0,
			"behind": 0,
			"dirty": dirty,
			"message": f"Branch '{branch}' tracks no remote",
		}

	ahead, behind = get_ahead_behind(repo_path, upstream)
	status = "STALE" if behind else "DIRTY" if dirty else "AHEAD" if ahead else "CLEAN"
	return {
		"status": status,
		"branch": branch,
		"upstream": upstream,
		"ahead": ahead,
		"behind": behind,
		"dirty": dirty,
	}
