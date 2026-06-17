import importlib
import frappe


HOOK_KEYS = [
    "doc_events",
    "scheduler_events",
    "fixtures",
    "override_doctype_class",
    "override_whitelisted_methods",
    "permission_query_conditions",
    "has_permission",
    "doctype_js",
    "doctype_list_js",
    "app_include_js",
    "app_include_css",
    "add_to_apps_screen",
]


@frappe.whitelist()
def get_installed_apps():
    return frappe.get_installed_apps()


@frappe.whitelist()
def get_app_hooks(app_name: str):
    try:
        hooks_module = importlib.import_module(f"{app_name}.hooks")

        data = {
            "app_name": app_name,
            "hooks": {},
        }

        for key in HOOK_KEYS:
            value = getattr(hooks_module, key, None)
            if value:
                data["hooks"][key] = value

        return data

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Hooks Explorer Error")
        return {
            "app_name": app_name,
            "error": str(e),
            "hooks": {},
        }
