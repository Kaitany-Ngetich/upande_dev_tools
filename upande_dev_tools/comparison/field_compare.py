import json
import frappe
from frappe.utils import now_datetime


COMPARE_PROPERTIES = [
    "fieldtype",
    "label",
    "reqd",
    "hidden",
    "read_only"
]


def get_fields_from_doctype_dict(doctype_dict):
    fields = {}

    for field in doctype_dict.get("fields", []):
        fieldname = field.get("fieldname")
        if fieldname:
            fields[fieldname] = field

    return fields


def get_latest_snapshot_doctype(doctype_name):
    snapshots = frappe.get_all(
        "Code Backup Snapshot",
        filters={
            "source_type": "DocType",
            "document_name": doctype_name
        },
        fields=["name", "content_json", "snapshot_time"],
        order_by="snapshot_time desc",
        limit=1
    )

    if not snapshots:
        return None

    snapshot = snapshots[0]

    try:
        snapshot["content_dict"] = json.loads(snapshot.content_json)
    except Exception:
        snapshot["content_dict"] = {}

    return snapshot


def compare_latest_snapshot(doctype_name):
    snapshot = get_latest_snapshot_doctype(doctype_name)

    if not snapshot:
        return []

    current_doc = frappe.get_doc("DocType", doctype_name)
    current_dict = current_doc.as_dict()

    live_fields = get_fields_from_doctype_dict(snapshot["content_dict"])
    local_fields = get_fields_from_doctype_dict(current_dict)

    differences = []

    for fieldname, live_field in live_fields.items():
        if fieldname not in local_fields:
            differences.append({
                "doctype_name": doctype_name,
                "field_name": fieldname,
                "issue_type": "Missing in Local",
                "live_value": live_field.get("fieldtype") or "Exists",
                "local_value": "—",
                "severity": "High",
                "source_snapshot": snapshot.name
            })

    for fieldname, local_field in local_fields.items():
        if fieldname not in live_fields:
            differences.append({
                "doctype_name": doctype_name,
                "field_name": fieldname,
                "issue_type": "Missing in Live",
                "live_value": "—",
                "local_value": local_field.get("fieldtype") or "Exists",
                "severity": "Medium",
                "source_snapshot": snapshot.name
            })

    for fieldname, live_field in live_fields.items():
        if fieldname not in local_fields:
            continue

        local_field = local_fields[fieldname]

        for prop in COMPARE_PROPERTIES:
            live_value = live_field.get(prop)
            local_value = local_field.get(prop)

            if str(live_value) != str(local_value):
                issue_type = "Different Property"

                if prop == "fieldtype":
                    issue_type = "Different Type"

                differences.append({
                    "doctype_name": doctype_name,
                    "field_name": fieldname,
                    "issue_type": issue_type,
                    "live_value": f"{prop}: {live_value}",
                    "local_value": f"{prop}: {local_value}",
                    "severity": "Critical" if prop == "fieldtype" else "Medium",
                    "source_snapshot": snapshot.name
                })

    return differences


def clear_old_differences(doctype_name):
    old = frappe.get_all(
        "Field Difference Log",
        filters={"doctype_name": doctype_name},
        pluck="name"
    )

    for name in old:
        frappe.delete_doc(
            "Field Difference Log",
            name,
            ignore_permissions=True,
            force=True
        )


def save_differences(differences, doctype_name):
    clear_old_differences(doctype_name)

    for diff in differences:
        doc = frappe.new_doc("Field Difference Log")
        doc.comparison_time = now_datetime()
        doc.doctype_name = diff.get("doctype_name")
        doc.field_name = diff.get("field_name")
        doc.issue_type = diff.get("issue_type")
        doc.live_value = diff.get("live_value")
        doc.local_value = diff.get("local_value")
        doc.status = "New"
        doc.source_snapshot = diff.get("source_snapshot")

        if hasattr(doc, "severity"):
            doc.severity = diff.get("severity")

        doc.insert(ignore_permissions=True)


def log_activity(title, description, status="Success"):
    if not frappe.db.exists("DocType", "Developer Activity Log"):
        return

    log = frappe.new_doc("Developer Activity Log")
    log.activity_time = now_datetime()
    log.activity_type = "Differences"
    log.title = title
    log.description = description
    log.status = status
    log.source = "Difference Checker"
    log.performed_by = frappe.session.user or "Administrator"
    log.insert(ignore_permissions=True)


@frappe.whitelist()
def run_compare_for_doctype(doctype_name):
    differences = compare_latest_snapshot(doctype_name)
    save_differences(differences, doctype_name)

    log_activity(
        f"Field comparison completed for {doctype_name}",
        f"{len(differences)} differences found",
        "Success"
    )

    frappe.db.commit()

    return {
        "doctype": doctype_name,
        "differences_found": len(differences),
        "differences": differences
    }
