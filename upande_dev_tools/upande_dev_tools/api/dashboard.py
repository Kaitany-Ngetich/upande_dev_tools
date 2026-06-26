import frappe

@frappe.whitelist()
def get_dashboard_data():
    rows = frappe.get_all(
        "Module Version Check",
        fields=[
            "module_name",
            "status_message",
            "current_branch",
            "commits_ahead",
            "commits_behind",
            "has_uncommitted_changes",
            "risk_level",
            "last_checked_at"
        ],
        order_by="modified desc",
        limit_page_length=100
    )

    clean = stale = dirty = 0

    for row in rows:
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

    return {
        "installed_apps": len(rows),
        "clean_apps": clean,
        "stale_apps": stale,
        "dirty_apps": dirty,
        "apps": rows
    }
