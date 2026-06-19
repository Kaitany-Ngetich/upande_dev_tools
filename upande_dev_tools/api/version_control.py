import os
import subprocess
import requests
import frappe
from frappe.utils import get_bench_path


class GitCommandError(Exception):
    pass


def run_git_command(repo_path, args, timeout=30):
    """Execute git commands safely."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
        )
        return result.stdout.strip()

    except subprocess.CalledProcessError as e:
        raise GitCommandError(
            e.stderr.strip() or e.stdout.strip() or str(e)
        )

    except subprocess.TimeoutExpired:
        raise GitCommandError(
            f"Git command timed out: git {' '.join(args)}"
        )


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
def analyse_repository(app_name):
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
            "message": (
                f"Branch '{current_branch}' "
                "has no upstream tracking branch."
            ),
        }

    ahead, behind = get_ahead_behind(
        repo_path,
        upstream,
    )

    dirty = bool(
        get_working_tree_status(repo_path)
    )

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