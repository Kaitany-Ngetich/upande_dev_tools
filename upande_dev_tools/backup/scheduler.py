import json
import hashlib
import frappe
from frappe.utils import now_datetime


def make_hash(content):
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def log_activity(activity_type, title, description="", status="Success", source="Scheduler"):
    if not frappe.db.exists("DocType", "Developer Activity Log"):
        return

    log = frappe.new_doc("Developer Activity Log")
    log.activity_time = now_datetime()
    log.activity_type = activity_type
    log.title = title
    log.description = description
    log.status = status
    log.source = source
    log.performed_by = frappe.session.user or "Administrator"
    log.insert(ignore_permissions=True)


def save_snapshot(source_type, document_name, content, app=None, module=None):
    content_hash = make_hash(content)

    last = frappe.get_all(
        "Code Backup Snapshot",
        filters={
            "source_type": source_type,
            "document_name": document_name
        },
        fields=["name", "content_hash"],
        order_by="creation desc",
        limit=1
    )

    if last and last[0].content_hash == content_hash:
        return False

    snap = frappe.new_doc("Code Backup Snapshot")
    snap.snapshot_time = now_datetime()
    snap.source_type = source_type
    snap.document_name = document_name
    snap.app = app
    snap.module = module
    snap.content_hash = content_hash
    snap.changed_since_last_backup = 1
    snap.content_json = content
    snap.script_code = content
    snap.backed_up_by = "Scheduler"
    snap.version_label = str(now_datetime())
    snap.insert(ignore_permissions=True)

    return True


@frappe.whitelist()
def run_code_backup():
    settings = get_settings()

    if not settings.get("enabled"):
        log_activity("Backup", "Code backup skipped", "Backup is disabled", "Warning")
        return {"status": "skipped"}

    saved = 0

    if settings.get("include_doctypes"):
        saved += backup_doctypes()

    if settings.get("include_server_scripts"):
        saved += backup_server_scripts()

    if settings.get("include_client_scripts"):
        saved += backup_client_scripts()

    frappe.db.set_single_value("Code Backup Settings", "last_backup_time", now_datetime())

    log_activity(
        "Backup",
        "Code backup completed",
        f"{saved} changed snapshots saved",
        "Success"
    )

    frappe.db.commit()

    return {
        "status": "success",
        "snapshots_saved": saved
    }


def get_settings():
    defaults = {
        "enabled": 1,
        "include_doctypes": 1,
        "include_server_scripts": 1,
        "include_client_scripts": 1
    }

    try:
        if not frappe.db.exists("DocType", "Code Backup Settings"):
            return defaults

        doc = frappe.get_single("Code Backup Settings")

        return {
            "enabled": doc.enabled if doc.enabled is not None else 1,
            "include_doctypes": doc.include_doctypes if doc.include_doctypes is not None else 1,
            "include_server_scripts": doc.include_server_scripts if doc.include_server_scripts is not None else 1,
            "include_client_scripts": doc.include_client_scripts if doc.include_client_scripts is not None else 1
        }

    except Exception:
        return defaults

def backup_doctypes():
    count = 0

    rows = frappe.get_all(
        "DocType",
        fields=["name", "module", "app"],
        limit_page_length=1000
    )

    for row in rows:
        try:
            doc = frappe.get_doc("DocType", row.name)
            content = json.dumps(doc.as_dict(), default=str, indent=2, sort_keys=True)

            if save_snapshot("DocType", row.name, content, row.app, row.module):
                count += 1

        except Exception as e:
            log_activity("Error", f"DocType backup failed: {row.name}", str(e), "Error")

    return count


def backup_server_scripts():
    count = 0

    if not frappe.db.exists("DocType", "Server Script"):
        return count

    rows = frappe.get_all(
        "Server Script",
        fields=["name", "script_type", "reference_doctype", "script"],
        limit_page_length=1000
    )

    for row in rows:
        try:
            content = json.dumps(row, default=str, indent=2, sort_keys=True)

            if save_snapshot("Server Script", row.name, content, None, row.reference_doctype):
                count += 1

        except Exception as e:
            log_activity("Error", f"Server Script backup failed: {row.name}", str(e), "Error")

    return count


def backup_client_scripts():
    count = 0

    if not frappe.db.exists("DocType", "Client Script"):
        return count

    rows = frappe.get_all(
        "Client Script",
        fields=["name", "dt", "script", "enabled"],
        limit_page_length=1000
    )

    for row in rows:
        try:
            content = json.dumps(row, default=str, indent=2, sort_keys=True)

            if save_snapshot("Client Script", row.name, content, None, row.dt):
                count += 1

        except Exception as e:
            log_activity("Error", f"Client Script backup failed: {row.name}", str(e), "Error")

    return count
