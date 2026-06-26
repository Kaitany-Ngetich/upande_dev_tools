import os
import ast
import frappe


def get_hooks_path(app_name):
    app_path = frappe.get_app_path(app_name)
    return os.path.join(app_path, "hooks.py")


def read_hooks_ast(app_name):
    path = get_hooks_path(app_name)

    if not os.path.exists(path):
        return None

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    try:
        return ast.parse(content)
    except Exception:
        return None


def extract_assigned_value(tree, variable_name):
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == variable_name:
                    try:
                        return ast.literal_eval(node.value)
                    except Exception:
                        return None
    return None


def count_items(value):
    if not value:
        return 0

    if isinstance(value, list):
        return len(value)

    if isinstance(value, dict):
        total = 0
        for item in value.values():
            if isinstance(item, list):
                total += len(item)
            elif isinstance(item, dict):
                total += count_items(item)
            else:
                total += 1
        return total

    return 1


@frappe.whitelist()
def get_hooks_summary():
    totals = {
        "doc_events": 0,
        "scheduler_events": 0,
        "override_methods": 0,
        "fixtures": 0,
        "permissions": 0,
        "whitelisted_methods": 0,
    }

    apps = frappe.get_installed_apps()

    for app in apps:
        tree = read_hooks_ast(app)
        if not tree:
            continue

        totals["doc_events"] += count_items(extract_assigned_value(tree, "doc_events"))
        totals["scheduler_events"] += count_items(extract_assigned_value(tree, "scheduler_events"))
        totals["override_methods"] += count_items(extract_assigned_value(tree, "override_whitelisted_methods"))
        totals["fixtures"] += count_items(extract_assigned_value(tree, "fixtures"))
        totals["permissions"] += count_items(extract_assigned_value(tree, "permission_query_conditions"))
        totals["whitelisted_methods"] += count_items(extract_assigned_value(tree, "override_whitelisted_methods"))

    return totals
