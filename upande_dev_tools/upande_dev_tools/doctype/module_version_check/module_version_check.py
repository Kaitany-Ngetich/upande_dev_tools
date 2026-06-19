import os
import subprocess
import requests

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime, get_bench_path


DOCTYPE = "Module Version Check"


class ModuleVersionCheck(Document):
    pass


class GitCommandError(Exception):
    pass


def is_local_environment():
    if frappe.conf.get("developer_mode") == 1:
        return True

    request_host = ""
    if getattr(frappe.local, "request", None):
        request_host = frappe.local.request.host or ""

    return any(host in request_host for host in ["localhost", "127.0.0.1", "0.0.0.0"])


def run_git_command(repo_path, args, timeout=30):
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
        raise GitCommandError(e.stderr.strip() or e.stdout.strip() or str(e))

    except subprocess.TimeoutExpired:
        raise GitCommandError(f"Git command timed out: git {' '.join(args)}")


def get_repo_path(app_name):
    repo_path = os.path.join(get_bench_path(), "apps", app_name)

    if not os.path.exists(repo_path):
        raise Exception(f"App path not found: {repo_path}")

    if not os.path.exists(os.path.join(repo_path, ".git")):
        raise Exception(f"Not a Git repository: {repo_path}")

    return repo_path


def get_current_branch(repo_path):
    branch = run_git_command(repo_path, ["branch", "--show-current"], timeout=10)

    if not branch:
        commit = run_git_command(repo_path, ["rev-parse", "--short", "HEAD"], timeout=10)
        return f"DETACHED-{commit}"

    return branch


def get_upstream_branch(repo_path):
    try:
        return run_git_command(
            repo_path,
            ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
            timeout=10,
        )
    except GitCommandError:
        return None


def get_default_remote_branch(repo_path):
    try:
        origin_head = run_git_command(
            repo_path,
            ["symbolic-ref", "refs/remotes/origin/HEAD"],
            timeout=10,
        )
        return origin_head.replace("refs/remotes/", "")
    except GitCommandError:
        pass

    for branch in ["origin/main", "origin/master", "origin/develop"]:
        try:
            run_git_command(repo_path, ["rev-parse", "--verify", branch], timeout=10)
            return branch
        except GitCommandError:
            continue

    return None


def get_working_tree_status(repo_path):
    return run_git_command(repo_path, ["status", "--porcelain"], timeout=10)


def get_repository_url(app_name):
    try:
        repo_path = get_repo_path(app_name)
        remote_url = run_git_command(
            repo_path,
            ["remote", "get-url", "origin"],
            timeout=10,
        )

        if remote_url.startswith("https://github.com/"):
            return remote_url.replace(".git", "")

        if remote_url.startswith("git@github.com:"):
            repo = remote_url.replace("git@github.com:", "")
            return f"https://github.com/{repo}".replace(".git", "")

        if remote_url.startswith("git@") and ":" in remote_url:
            repo = remote_url.split(":", 1)[1]
            return f"https://github.com/{repo}".replace(".git", "")

        return remote_url.replace(".git", "")

    except Exception:
        return ""


def analyse_local_repo(app_name, fetch=True):
    repo_path = get_repo_path(app_name)

    if fetch:
        run_git_command(repo_path, ["fetch", "--all", "--prune"], timeout=45)

    current_branch = get_current_branch(repo_path)
    current_commit = run_git_command(repo_path, ["rev-parse", "--short", "HEAD"], timeout=10)

    upstream = get_upstream_branch(repo_path)

    if not upstream:
        upstream = get_default_remote_branch(repo_path)

    if not upstream:
        return {
            "environment": "Local Machine",
            "current_branch": current_branch,
            "current_commit": current_commit,
            "upstream_branch": "",
            "commits_behind": 0,
            "commits_ahead": 0,
            "has_uncommitted_changes": bool(get_working_tree_status(repo_path)),
            "status": "Error",
            "status_message": (
                f"Branch '{current_branch}' has no upstream branch and no default remote "
                f"branch could be detected. Set upstream using: "
                f"git branch --set-upstream-to=origin/main {current_branch}"
            ),
        }

    behind = int(
        run_git_command(repo_path, ["rev-list", f"HEAD..{upstream}", "--count"], timeout=10)
    )

    ahead = int(
        run_git_command(repo_path, ["rev-list", f"{upstream}..HEAD", "--count"], timeout=10)
    )

    has_uncommitted_changes = bool(get_working_tree_status(repo_path))

    if behind > 0:
        status = "Stale"
        message = (
            f"❌ Stale code. Branch '{current_branch}' is {behind} commit(s) behind "
            f"{upstream}. Pull latest changes before deployment."
        )
    elif ahead > 0:
        status = "Ahead"
        message = (
            f"⚠️ Local branch '{current_branch}' is {ahead} commit(s) ahead of {upstream}. "
            "Push your commits or confirm this is intentional."
        )
    elif has_uncommitted_changes:
        status = "Dirty"
        message = (
            f"⚠️ Branch '{current_branch}' is synced with {upstream}, but has uncommitted "
            "or untracked local changes."
        )
    else:
        status = "Clean"
        message = f"✅ Clean. Branch '{current_branch}' is fully synced with {upstream}."

    return {
        "environment": "Local Machine",
        "current_branch": current_branch,
        "current_commit": current_commit,
        "upstream_branch": upstream,
        "commits_behind": behind,
        "commits_ahead": ahead,
        "has_uncommitted_changes": has_uncommitted_changes,
        "status": status,
        "status_message": message,
    }


def get_github_repo_info(repository_name, token):
    clean_repo = (
        repository_name
        .strip()
        .replace("https://github.com/", "")
        .replace(".git", "")
        .strip("/")
    )

    url = f"https://api.github.com/repos/{clean_repo}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    response = requests.get(url, headers=headers, timeout=30)

    if response.status_code != 200:
        raise Exception(
            f"GitHub API error {response.status_code}: repository '{clean_repo}' not found "
            "or token has no access."
        )

    return response.json(), clean_repo, headers


def analyse_live_repo(app_name, repository_name):
    github_token = frappe.conf.get("github_token")

    if not github_token:
        raise Exception("Missing 'github_token' in site_config.json.")

    if not repository_name:
        raise Exception("GitHub Repository is required for live server checks.")

    repo_info, clean_repo, headers = get_github_repo_info(repository_name, github_token)
    default_branch = repo_info.get("default_branch") or "main"

    repo_path = get_repo_path(app_name)

    deployed_commit = run_git_command(repo_path, ["rev-parse", "HEAD"], timeout=10)
    deployed_short_commit = deployed_commit[:7]
    current_branch = get_current_branch(repo_path)

    branch_url = f"https://api.github.com/repos/{clean_repo}/branches/{default_branch}"
    branch_response = requests.get(branch_url, headers=headers, timeout=30)

    if branch_response.status_code != 200:
        raise Exception(f"Could not read default branch '{default_branch}' from GitHub.")

    latest_remote_commit = branch_response.json()["commit"]["sha"]
    latest_short_commit = latest_remote_commit[:7]

    compare_url = (
        f"https://api.github.com/repos/{clean_repo}/compare/"
        f"{deployed_commit}...{latest_remote_commit}"
    )
    compare_response = requests.get(compare_url, headers=headers, timeout=30)

    if compare_response.status_code != 200:
        raise Exception("Could not compare deployed commit with GitHub default branch.")

    compare_data = compare_response.json()
    behind = compare_data.get("ahead_by", 0)

    has_uncommitted_changes = bool(get_working_tree_status(repo_path))

    if deployed_commit == latest_remote_commit and not has_uncommitted_changes:
        status = "Clean"
        message = (
            f"✅ Live server is clean. Deployed commit {deployed_short_commit} matches "
            f"GitHub {default_branch}."
        )
    elif deployed_commit == latest_remote_commit and has_uncommitted_changes:
        status = "Dirty"
        message = (
            f"⚠️ Live server is on latest commit {deployed_short_commit}, but has "
            "uncommitted local changes."
        )
    else:
        status = "Stale"
        message = (
            f"❌ Live server is stale. Deployed commit {deployed_short_commit} is behind "
            f"GitHub {default_branch} latest commit {latest_short_commit}."
        )

    return {
        "environment": "Live Server",
        "current_branch": current_branch,
        "current_commit": deployed_short_commit,
        "upstream_branch": f"origin/{default_branch}",
        "commits_behind": behind,
        "commits_ahead": 0,
        "has_uncommitted_changes": has_uncommitted_changes,
        "status": status,
        "status_message": message,
    }


def get_risk_level(status, behind=0, ahead=0):
    if status == "Clean":
        return "Low"

    if status in ["Dirty", "Ahead"]:
        return "Medium"

    if status == "Stale":
        return "Critical" if behind >= 10 else "High"

    if status == "Error":
        return "Critical"

    return "Medium"


def update_check_doc(doc, result):
    doc.environment = result.get("environment")
    doc.current_branch = result.get("current_branch")
    doc.current_commit = result.get("current_commit")
    doc.upstream_branch = result.get("upstream_branch")

    doc.commits_behind = result.get("commits_behind", 0)
    doc.commits_ahead = result.get("commits_ahead", 0)
    doc.has_uncommitted_changes = result.get("has_uncommitted_changes", False)

    doc.status = result.get("status")
    doc.status_message = result.get("status_message")

    doc.safe_to_deploy = doc.status == "Clean"
    doc.risk_level = get_risk_level(
        doc.status,
        doc.commits_behind,
        doc.commits_ahead,
    )

    doc.last_checked_at = now_datetime()

    if hasattr(doc, "last_checked_by"):
        doc.last_checked_by = frappe.session.user


@frappe.whitelist()
def run_freshness_check(docname):
    doc = frappe.get_doc(DOCTYPE, docname)

    try:
        if is_local_environment():
            result = analyse_local_repo(doc.module_name)
        else:
            result = analyse_live_repo(doc.module_name, doc.repository_name)

        if not doc.repository_name:
            doc.repository_name = get_repository_url(doc.module_name)

        update_check_doc(doc, result)

    except Exception as e:
        doc.status = "Error"
        doc.status_message = str(e)
        doc.safe_to_deploy = 0
        doc.risk_level = "Critical"
        doc.last_checked_at = now_datetime()

        if hasattr(doc, "last_checked_by"):
            doc.last_checked_by = frappe.session.user

    doc.save(ignore_permissions=True)
    return doc.as_dict()


@frappe.whitelist()
def scan_installed_apps():
    apps = frappe.get_installed_apps()

    created = 0
    updated = 0
    skipped = 0

    for app in apps:
        try:
            existing = frappe.db.exists(
                DOCTYPE,
                {"module_name": app},
            )

            if existing:
                doc = frappe.get_doc(DOCTYPE, existing)
                updated += 1
            else:
                doc = frappe.new_doc(DOCTYPE)
                doc.module_name = app
                doc.status = ""
                doc.environment = ""
                created += 1

            if not doc.repository_name:
                doc.repository_name = get_repository_url(app)

            doc.save(ignore_permissions=True)

        except Exception:
            skipped += 1

    frappe.db.commit()

    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "total": len(apps),
    }