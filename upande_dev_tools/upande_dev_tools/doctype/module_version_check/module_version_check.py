import os
import subprocess

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime, get_bench_path


DOCTYPE = "Module Version Check"


class GitCommandError(Exception):
    pass


class ModuleVersionCheck(Document):
    @frappe.whitelist()
    def run_version_check(self) -> dict:
        result = analyse_local_repo(get_doc_app_folder(self), fetch=False)
        update_check_doc(self, result)
        self.save(ignore_permissions=True)
        frappe.db.commit()
        return self.as_dict()

    @frappe.whitelist()
    def run_version_check_with_fetch(self) -> dict:
        result = analyse_local_repo(get_doc_app_folder(self), fetch=True)
        update_check_doc(self, result)
        self.save(ignore_permissions=True)
        frappe.db.commit()
        return self.as_dict()


def run_git_command(repo_path: str, args: list[str], timeout: int = 30) -> str:
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


def get_repo_path(app_folder: str) -> str:
    if not app_folder:
        raise Exception("Missing app_folder.")

    repo_path = os.path.join(get_bench_path(), "apps", app_folder)

    if not os.path.exists(repo_path):
        raise Exception(f"App folder not found: {repo_path}")

    if not os.path.exists(os.path.join(repo_path, ".git")):
        raise Exception(f"No Git repository found for app folder: {app_folder}")

    return repo_path


def normalize_remote_url(remote_url: str) -> str:
    if not remote_url:
        return ""

    remote_url = remote_url.strip()

    if remote_url.startswith("https://github.com/"):
        return remote_url.replace(".git", "")

    if remote_url.startswith("git@github.com:"):
        repo = remote_url.replace("git@github.com:", "")
        return f"https://github.com/{repo}".replace(".git", "")

    if remote_url.startswith("git@") and ":" in remote_url:
        repo = remote_url.split(":", 1)[1]
        return f"https://github.com/{repo}".replace(".git", "")

    return remote_url.replace(".git", "")


def get_current_branch(repo_path: str) -> str:
    branch = run_git_command(repo_path, ["branch", "--show-current"], timeout=10)

    if not branch:
        commit = run_git_command(repo_path, ["rev-parse", "--short", "HEAD"], timeout=10)
        return f"DETACHED-{commit}"

    return branch


def get_primary_remote(repo_path: str) -> str:
    try:
        current_branch = get_current_branch(repo_path)

        if not current_branch.startswith("DETACHED-"):
            remote = run_git_command(
                repo_path,
                ["config", f"branch.{current_branch}.remote"],
                timeout=10,
            )
            if remote:
                return remote
    except Exception:
        pass

    try:
        remotes = run_git_command(repo_path, ["remote"], timeout=10).splitlines()
        return remotes[0] if remotes else ""
    except Exception:
        return ""


def get_repository_url(app_folder: str) -> str:
    repo_path = get_repo_path(app_folder)
    remote = get_primary_remote(repo_path)

    if not remote:
        return ""

    remote_url = run_git_command(repo_path, ["remote", "get-url", remote], timeout=10)
    return normalize_remote_url(remote_url)


def get_current_commit(repo_path: str) -> str:
    return run_git_command(repo_path, ["rev-parse", "--short", "HEAD"], timeout=10)


def get_upstream_branch(repo_path: str) -> str:
    try:
        return run_git_command(
            repo_path,
            ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
            timeout=10,
        )
    except GitCommandError:
        return ""


def get_default_remote_branch(repo_path: str) -> str:
    remote = get_primary_remote(repo_path)

    if not remote:
        return ""

    try:
        remote_head = run_git_command(
            repo_path,
            ["symbolic-ref", f"refs/remotes/{remote}/HEAD"],
            timeout=10,
        )
        return remote_head.replace("refs/remotes/", "")
    except GitCommandError:
        pass

    for branch in [f"{remote}/main", f"{remote}/master", f"{remote}/develop"]:
        try:
            run_git_command(repo_path, ["rev-parse", "--verify", branch], timeout=10)
            return branch
        except GitCommandError:
            continue

    return ""


def get_working_tree_status(repo_path: str) -> str:
    return run_git_command(repo_path, ["status", "--porcelain"], timeout=10)


def fetch_remote_safely(repo_path: str, remote: str) -> bool:
    if not remote:
        return False

    try:
        run_git_command(repo_path, ["fetch", remote, "--prune"], timeout=15)
        return True
    except Exception:
        return False


def analyse_local_repo(app_folder: str, fetch: bool = False) -> dict:
    repo_path = get_repo_path(app_folder)
    remote = get_primary_remote(repo_path)
    repository_url = get_repository_url(app_folder)

    fetch_success = False
    if fetch and remote:
        fetch_success = fetch_remote_safely(repo_path, remote)

    current_branch = get_current_branch(repo_path)
    current_commit = get_current_commit(repo_path)
    upstream = get_upstream_branch(repo_path) or get_default_remote_branch(repo_path)
    has_uncommitted_changes = bool(get_working_tree_status(repo_path))

    if not remote:
        return {
            "environment": "Local Machine",
            "repository_url": "",
            "repository_name": "",
            "current_branch": current_branch,
            "current_commit": current_commit,
            "upstream_branch": "",
            "commits_behind": 0,
            "commits_ahead": 0,
            "has_uncommitted_changes": has_uncommitted_changes,
            "status": "Error",
            "status_message": "Repository has no configured Git remote.",
        }

    if not upstream:
        return {
            "environment": "Local Machine",
            "repository_url": repository_url,
            "repository_name": repository_url,
            "current_branch": current_branch,
            "current_commit": current_commit,
            "upstream_branch": "",
            "commits_behind": 0,
            "commits_ahead": 0,
            "has_uncommitted_changes": has_uncommitted_changes,
            "status": "Error",
            "status_message": (
                f"Branch '{current_branch}' has no upstream branch. "
                f"Remote detected: '{remote}'."
            ),
        }

    behind = int(run_git_command(repo_path, ["rev-list", f"HEAD..{upstream}", "--count"], timeout=10))
    ahead = int(run_git_command(repo_path, ["rev-list", f"{upstream}..HEAD", "--count"], timeout=10))

    if behind > 0 and ahead > 0:
        status = "Diverged"
        message = (
            f"⚠️ Diverged. Local branch '{current_branch}' is {ahead} commit(s) ahead "
            f"and {behind} commit(s) behind {upstream}."
        )
    elif has_uncommitted_changes:
        status = "Dirty"
        message = (
            f"⚠️ Branch '{current_branch}' is synced with {upstream}, but has "
            "uncommitted or untracked local changes."
        )
    elif behind > 0:
        status = "Stale"
        message = (
            f"❌ Stale code. Branch '{current_branch}' is {behind} commit(s) behind "
            f"{upstream}. Pull latest changes."
        )
    elif ahead > 0:
        status = "Ahead"
        message = (
            f"⚠️ Local branch '{current_branch}' is {ahead} commit(s) ahead of {upstream}. "
            "Push your commits or confirm this is intentional."
        )
    else:
        status = "Clean"
        message = f"✅ Clean. Branch '{current_branch}' is fully synced with {upstream}."

    if fetch:
        message += " Remote fetch completed." if fetch_success else " Remote fetch skipped or failed, but local check completed."

    return {
        "environment": "Local Machine",
        "repository_url": repository_url,
        "repository_name": repository_url,
        "current_branch": current_branch,
        "current_commit": current_commit,
        "upstream_branch": upstream,
        "commits_behind": behind,
        "commits_ahead": ahead,
        "has_uncommitted_changes": has_uncommitted_changes,
        "status": status,
        "status_message": message,
    }


def get_risk_level(status: str, behind: int = 0, ahead: int = 0) -> str:
    if status == "Clean":
        return "Low"
    if status in ["Dirty", "Ahead"]:
        return "Medium"
    if status == "Stale":
        return "Critical" if behind >= 10 else "High"
    if status in ["Diverged", "Error"]:
        return "Critical"
    return "Medium"


def set_field_if_exists(doc, fieldname: str, value) -> None:
    fieldnames = [df.fieldname for df in doc.meta.fields]
    if fieldname in fieldnames:
        setattr(doc, fieldname, value)


def update_check_doc(doc, result: dict) -> None:
    set_field_if_exists(doc, "environment", result.get("environment"))
    set_field_if_exists(doc, "repository_url", result.get("repository_url"))
    set_field_if_exists(doc, "repository_name", result.get("repository_name"))
    set_field_if_exists(doc, "current_branch", result.get("current_branch"))
    set_field_if_exists(doc, "upstream_branch", result.get("upstream_branch"))
    set_field_if_exists(doc, "current_commit", result.get("current_commit"))
    set_field_if_exists(doc, "currrent_commit", result.get("current_commit"))
    set_field_if_exists(doc, "commits_behind", result.get("commits_behind", 0))
    set_field_if_exists(doc, "commits_ahead", result.get("commits_ahead", 0))
    set_field_if_exists(doc, "has_uncommitted_changes", result.get("has_uncommitted_changes", 0))
    set_field_if_exists(doc, "status", result.get("status"))
    set_field_if_exists(doc, "status_message", result.get("status_message"))
    set_field_if_exists(doc, "safe_to_deploy", result.get("status") == "Clean")

    set_field_if_exists(
        doc,
        "risk_level",
        get_risk_level(
            result.get("status"),
            result.get("commits_behind", 0),
            result.get("commits_ahead", 0),
        ),
    )

    set_field_if_exists(doc, "last_checked_at", now_datetime())
    set_field_if_exists(doc, "last_checked_by", frappe.session.user)


def get_doc_app_folder(doc) -> str:
    return getattr(doc, "app_folder", None) or doc.module_name


@frappe.whitelist()
def run_freshness_check(docname: str) -> dict:
    doc = frappe.get_doc(DOCTYPE, docname)

    try:
        result = analyse_local_repo(get_doc_app_folder(doc), fetch=False)
        update_check_doc(doc, result)
    except Exception as e:
        set_field_if_exists(doc, "status", "Error")
        set_field_if_exists(doc, "status_message", str(e))
        set_field_if_exists(doc, "safe_to_deploy", 0)
        set_field_if_exists(doc, "risk_level", "Critical")
        set_field_if_exists(doc, "last_checked_at", now_datetime())
        set_field_if_exists(doc, "last_checked_by", frappe.session.user)

    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return doc.as_dict()


@frappe.whitelist()
def run_freshness_check_with_fetch(docname: str) -> dict:
    doc = frappe.get_doc(DOCTYPE, docname)

    try:
        result = analyse_local_repo(get_doc_app_folder(doc), fetch=True)
        update_check_doc(doc, result)
    except Exception as e:
        set_field_if_exists(doc, "status", "Error")
        set_field_if_exists(doc, "status_message", str(e))
        set_field_if_exists(doc, "safe_to_deploy", 0)
        set_field_if_exists(doc, "risk_level", "Critical")
        set_field_if_exists(doc, "last_checked_at", now_datetime())
        set_field_if_exists(doc, "last_checked_by", frappe.session.user)

    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return doc.as_dict()


@frappe.whitelist()
def scan_installed_apps() -> dict:
    apps = frappe.get_installed_apps()

    created = 0
    updated = 0
    skipped = 0
    errors = []

    for app in apps:
        try:
            existing = frappe.db.exists(DOCTYPE, {"module_name": app})

            if existing:
                doc = frappe.get_doc(DOCTYPE, existing)
                updated += 1
            else:
                doc = frappe.new_doc(DOCTYPE)
                doc.module_name = app
                created += 1

            set_field_if_exists(doc, "app_folder", app)

            try:
                repository_url = get_repository_url(app)
                set_field_if_exists(doc, "repository_url", repository_url)
                set_field_if_exists(doc, "repository_name", repository_url)
            except Exception as repo_error:
                set_field_if_exists(doc, "status", "Error")
                set_field_if_exists(doc, "status_message", str(repo_error))
                set_field_if_exists(doc, "risk_level", "Critical")
                errors.append(f"{app}: {repo_error}")

            doc.save(ignore_permissions=True)

        except Exception as e:
            skipped += 1
            errors.append(f"{app}: {e}")

    frappe.db.commit()
    return {"created": created, "updated": updated, "skipped": skipped, "total": len(apps), "errors": errors}


@frappe.whitelist()
def run_all_version_checks() -> dict:
    docs = frappe.get_all(DOCTYPE, pluck="name")

    checked = 0
    failed = 0
    errors = []

    for docname in docs:
        try:
            run_freshness_check(docname)
            checked += 1
        except Exception as e:
            failed += 1
            errors.append(f"{docname}: {e}")

    return {"checked": checked, "failed": failed, "errors": errors}


@frappe.whitelist()
def run_all_version_checks_with_fetch() -> dict:
    docs = frappe.get_all(DOCTYPE, pluck="name")

    checked = 0
    failed = 0
    errors = []

    for docname in docs:
        try:
            run_freshness_check_with_fetch(docname)
            checked += 1
        except Exception as e:
            failed += 1
            errors.append(f"{docname}: {e}")

    return {"checked": checked, "failed": failed, "errors": errors}