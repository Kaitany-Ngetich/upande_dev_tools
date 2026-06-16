import subprocess
from pathlib import Path

import frappe


def run_git_command(repo_path, args):
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=repo_path,
            text=True,
            capture_output=True,
            timeout=20,
        )
        return {
            "success": result.returncode == 0,
            "output": result.stdout.strip(),
            "error": result.stderr.strip(),
        }
    except Exception as e:
        return {"success": False, "output": "", "error": str(e)}


@frappe.whitelist()
def check_app_git_status(app_name):
    """
    Check whether a Frappe app's local git branch is safe.
    Blocks risky states like:
    - local branch behind remote
    - local branch diverged
    - uncommitted changes
    """

    if app_name not in frappe.get_installed_apps():
        frappe.throw(f"{app_name} is not installed on this site")

    app_package_path = Path(frappe.get_app_path(app_name))
    repo_path = app_package_path.parent

    if not (repo_path / ".git").exists():
        frappe.throw(f"{app_name} is not a git repository")

    run_git_command(repo_path, ["fetch", "--all", "--prune"])

    branch = run_git_command(repo_path, ["rev-parse", "--abbrev-ref", "HEAD"])["output"]

    upstream_result = run_git_command(
        repo_path, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"]
    )

    if not upstream_result["success"]:
        return {
            "app_name": app_name,
            "branch": branch,
            "status": "NO_UPSTREAM",
            "safe_to_deploy": False,
            "message": "This branch has no upstream remote branch configured.",
        }

    upstream = upstream_result["output"]

    counts = run_git_command(
        repo_path, ["rev-list", "--left-right", "--count", f"HEAD...{upstream}"]
    )["output"]

    ahead, behind = [int(x) for x in counts.split()]

    dirty = bool(run_git_command(repo_path, ["status", "--porcelain"])["output"])

    if dirty:
        status = "BLOCKED_UNCOMMITTED_CHANGES"
        safe = False
        message = "Local repository has uncommitted changes. Commit or stash them first."
    elif behind > 0 and ahead > 0:
        status = "BLOCKED_DIVERGED"
        safe = False
        message = f"Local branch has diverged from {upstream}. Pull/rebase and resolve conflicts first."
    elif behind > 0:
        status = "BLOCKED_BEHIND_REMOTE"
        safe = False
        message = f"Local branch is behind {upstream} by {behind} commit(s). Pull latest changes first."
    else:
        status = "SAFE"
        safe = True
        message = "Local branch is up to date or ahead of remote. Safe to continue."

    return {
        "app_name": app_name,
        "repo_path": str(repo_path),
        "branch": branch,
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
        "has_uncommitted_changes": dirty,
        "status": status,
        "safe_to_deploy": safe,
        "message": message,
    }