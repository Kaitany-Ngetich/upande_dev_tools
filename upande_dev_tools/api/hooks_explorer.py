import frappe
from frappe import _


@frappe.whitelist()
def get_installed_apps():
    """Return all installed apps"""
    return frappe.get_installed_apps()


@frappe.whitelist()
def get_app_hooks(app_name):
    """
    Read hooks for a specific app.
    Returns the most commonly used hooks.
    """

    hooks = frappe.get_hooks(app_name=app_name)

    return {
        "app_name": app_name,
        "doc_events": hooks.get("doc_events", {}),
        "scheduled_events": hooks.get("scheduler_events", {}),
        "fixtures": hooks.get("fixtures", []),
        "override_whitelisted_methods": hooks.get(
            "override_whitelisted_methods", {}
        ),
        "permission_query_conditions": hooks.get(
            "permission_query_conditions", {}
        ),
        "has_permission": hooks.get("has_permission", {}),
    }