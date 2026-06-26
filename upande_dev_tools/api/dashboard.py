import frappe
from frappe.utils import format_datetime, today, get_datetime
from upande_dev_tools.api.hooks_summary import get_hooks_summary

@frappe.whitelist()
def get_dashboard_data():
    version_rows = get_version_rows()
    backup_rows = get_backup_rows()
    activity_rows = get_activity_rows()
    error_rows = get_error_rows()

    clean = stale = dirty = 0

    for row in version_rows:
        message = (row.status_message or "").lower()

        if row.has_uncommitted_changes:
            row["status"] = "Dirty"
            dirty += 1
        elif row.commits_behind and row.commits_behind > 0:
            row["status"] = "Stale"
            stale += 1
        elif "clean" in message or "fully synced" in message:
            row["status"] = "Clean"
            clean += 1
        else:
            row["status"] = row.risk_level or "Unknown"
    hooks_summary = get_hooks_summary()

    return {
        "installed_apps": len(version_rows),
        "clean_apps": clean,
        "stale_apps": stale,
        "dirty_apps": dirty,

        "snapshots_today": get_snapshots_today(),
        "last_backup_display": get_last_backup_display(),

        "apps": version_rows,
        "backup_snapshots": backup_rows,
        "activity_logs": activity_rows,
        "recent_errors": error_rows,

        "missing_local_count": get_difference_count("Missing in Local"),
        "missing_live_count": get_difference_count("Missing in Live"),
        "different_type_count": get_difference_count("Different Type"),
        "different_property_count": get_difference_count("Different Property"),
        "field_differences": get_field_differences(),
        "hooks_summary": hooks_summary,
}

def get_version_rows():
    if not frappe.db.exists("DocType", "Module Version Check"):
        return []

    return frappe.get_all(
        "Module Version Check",
        fields=[
            "module_name",
            "status_message",
            "current_branch",
            "upstream_branch",
            "commits_ahead",
            "commits_behind",
            "has_uncommitted_changes",
            "risk_level",
            "last_checked_at"
        ],
        order_by="modified desc",
        limit_page_length=100
    )


def get_backup_rows():
    if not frappe.db.exists("DocType", "Code Backup Snapshot"):
        return []

    rows = frappe.get_all(
        "Code Backup Snapshot",
        fields=[
            "name",
            "snapshot_time",
            "source_type",
            "document_name",
            "module",
            "app",
            "changed_since_last_backup"
        ],
        order_by="snapshot_time desc",
        limit_page_length=10
    )

    for row in rows:
        row["snapshot_time_display"] = format_datetime(row.snapshot_time) if row.snapshot_time else ""
        row["app_module"] = row.app or row.module or ""

    return rows


def get_snapshots_today():
    if not frappe.db.exists("DocType", "Code Backup Snapshot"):
        return 0

    return frappe.db.count(
        "Code Backup Snapshot",
        filters={
            "snapshot_time": [">=", today()]
        }
    )


def get_last_backup_display():
    if not frappe.db.exists("DocType", "Code Backup Snapshot"):
        return "No backup yet"

    last = frappe.get_all(
        "Code Backup Snapshot",
        fields=["snapshot_time"],
        order_by="snapshot_time desc",
        limit=1
    )

    if not last:
        return "No backup yet"

    return format_datetime(last[0].snapshot_time)


def get_activity_rows():
    if not frappe.db.exists("DocType", "Developer Activity Log"):
        return []

    rows = frappe.get_all(
        "Developer Activity Log",
        fields=[
            "activity_time",
            "activity_type",
            "title",
            "status",
            "source"
        ],
        order_by="activity_time desc",
        limit_page_length=10
    )

    for row in rows:
        row["activity_time_display"] = format_datetime(row.activity_time) if row.activity_time else ""

    return rows


def get_error_rows():
    if not frappe.db.exists("DocType", "Developer Activity Log"):
        return []

    rows = frappe.get_all(
        "Developer Activity Log",
        filters={
            "status": "Error"
        },
        fields=[
            "activity_time",
            "title",
            "description",
            "status"
        ],
        order_by="activity_time desc",
        limit_page_length=5
    )

    for row in rows:
        row["activity_time_display"] = format_datetime(row.activity_time) if row.activity_time else ""

    return rows


def get_difference_count(issue_type):
    if not frappe.db.exists("DocType", "Field Difference Log"):
        return 0

    return frappe.db.count(
        "Field Difference Log",
        filters={"issue_type": issue_type}
    )


def get_field_differences():
    if not frappe.db.exists("DocType", "Field Difference Log"):
        return []

    return frappe.get_all(
        "Field Difference Log",
        fields=[
            "name",
            "doctype_name",
            "field_name",
            "issue_type",
            "live_value",
            "local_value",
            "status"
        ],
        order_by="comparison_time desc",
        limit_page_length=20
    )
