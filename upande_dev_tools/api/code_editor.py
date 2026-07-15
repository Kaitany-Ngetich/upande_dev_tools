import os
from pathlib import Path

import frappe
from frappe import _


# =====================================
# Configuration
# =====================================

ALLOWED_EXTENSIONS = {
    ".py", ".js", ".json", ".html", ".css", ".scss",
    ".md", ".txt", ".yml", ".yaml", ".toml"
}

BLOCKED_PARTS = {
    ".git", "node_modules", "__pycache__", ".venv", "env",
    "sites", "logs", "private", "public/files"
}

MAX_TREE_DEPTH = 8


# =====================================
# Helper Functions
# =====================================

def get_bench_path() -> Path:
    return Path(frappe.get_app_path("frappe")).parents[1]


def get_apps_path() -> Path:
    return get_bench_path() / "apps"


def get_app_root(app: str) -> Path:
    return Path(frappe.get_app_path(app)).parents[0]


def get_language(extension: str) -> str:
    mapping = {
        ".py": "python",
        ".js": "javascript",
        ".json": "json",
        ".html": "html",
        ".css": "css",
        ".scss": "scss",
        ".md": "markdown",
        ".txt": "plaintext",
        ".yml": "yaml",
        ".yaml": "yaml",
        ".toml": "toml",
    }
    return mapping.get(extension, "plaintext")


def get_node_type(path: Path) -> str:
    if path.is_dir():
        return "folder"

    extension = path.suffix.lower()

    mapping = {
        ".py": "python",
        ".js": "javascript",
        ".json": "json",
        ".html": "html",
        ".css": "css",
        ".scss": "scss",
        ".md": "markdown",
        ".txt": "text",
        ".yml": "yaml",
        ".yaml": "yaml",
        ".toml": "toml",
    }

    return mapping.get(extension, "file")


def is_safe_path(path: Path, base_path: Path) -> bool:
    try:
        path.resolve().relative_to(base_path.resolve())
        return True
    except ValueError:
        return False


def is_blocked(path: Path) -> bool:
    return any(part in BLOCKED_PARTS for part in path.parts)


def is_allowed_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS


def make_node(path: Path, base_path: Path, app: str | None = None) -> dict:
    relative_path = "" if path == base_path else str(path.relative_to(base_path))

    node = {
        "name": path.name,
        "path": relative_path,
        "absolute_path": str(path),
        "type": get_node_type(path),
        "is_folder": path.is_dir(),
        "extension": path.suffix.lower() if path.is_file() else "",
        "language": get_language(path.suffix.lower()) if path.is_file() else "",
        "app": app,
    }

    if path.is_file():
        stat = path.stat()
        node.update({
            "size": stat.st_size,
            "modified": stat.st_mtime,
        })

    return node


def build_tree(path: Path, base_path: Path, app: str, depth: int = 0) -> dict | None:
    if depth > MAX_TREE_DEPTH:
        return None

    if is_blocked(path):
        return None

    if path.is_file() and not is_allowed_file(path):
        return None

    node = make_node(path, base_path, app)

    if path.is_dir():
        children = []

        try:
            entries = sorted(
                path.iterdir(),
                key=lambda item: (item.is_file(), item.name.lower())
            )
        except PermissionError:
            entries = []

        for entry in entries:
            if entry.name.startswith(".") and entry.name not in {".github"}:
                continue

            if is_blocked(entry):
                continue

            child = build_tree(entry, base_path, app, depth + 1)

            if child:
                children.append(child)

        node["children"] = children

    return node


def validate_file(app: str, path: str) -> tuple[Path, Path]:
    if not app or not path:
        frappe.throw(_("App and path are required"))

    app_path = get_app_root(app)
    file_path = app_path / path

    if not is_safe_path(file_path, app_path):
        frappe.throw(_("Unsafe file path"))

    if is_blocked(file_path):
        frappe.throw(_("Blocked file path"))

    if file_path.suffix.lower() not in ALLOWED_EXTENSIONS:
        frappe.throw(_("File type not allowed"))

    if not file_path.exists():
        frappe.throw(_("File not found"))

    if not file_path.is_file():
        frappe.throw(_("Path is not a file"))

    return app_path, file_path


# =====================================
# Workspace APIs
# =====================================

@frappe.whitelist()
def get_installed_apps() -> list[dict]:
    apps = frappe.get_installed_apps()
    return [{"label": app, "value": app} for app in apps]


@frappe.whitelist()
def get_workspace_tree() -> dict:
    bench_path = get_bench_path()
    apps_path = get_apps_path()
    apps = frappe.get_installed_apps()

    app_nodes = []

    for app in apps:
        try:
            app_path = get_app_root(app)
        except Exception:
            continue

        if not app_path.exists():
            continue

        app_node = build_tree(app_path, app_path, app)

        if app_node:
            app_node["name"] = app
            app_node["type"] = "app"
            app_node["is_folder"] = True
            app_nodes.append(app_node)

    return {
        "name": bench_path.name,
        "path": str(bench_path),
        "type": "workspace",
        "is_folder": True,
        "children": [
            {
                "name": "apps",
                "path": str(apps_path),
                "type": "folder",
                "is_folder": True,
                "children": app_nodes,
            }
        ],
    }


@frappe.whitelist()
def get_app_tree(app: str) -> dict:
    if not app:
        frappe.throw(_("App is required"))

    app_path = get_app_root(app)

    if not app_path.exists():
        frappe.throw(_("App folder not found: {0}").format(app))

    return build_tree(app_path, app_path, app)


# =====================================
# File APIs
# =====================================

@frappe.whitelist()
def get_file_tree(app: str) -> list[dict]:
    if not app:
        frappe.throw(_("App is required"))

    app_path = get_app_root(app)

    if not app_path.exists():
        frappe.throw(_("App folder not found: {0}").format(app))

    tree = []

    for root, dirs, files in os.walk(app_path):
        root_path = Path(root)

        dirs[:] = [
            d for d in dirs
            if d not in BLOCKED_PARTS and not d.startswith(".")
        ]

        if is_blocked(root_path):
            continue

        relative_root = root_path.relative_to(app_path)

        for file_name in files:
            file_path = root_path / file_name
            extension = file_path.suffix.lower()

            if extension not in ALLOWED_EXTENSIONS:
                continue

            if is_blocked(file_path):
                continue

            relative_path = file_path.relative_to(app_path)

            tree.append({
                "file_name": file_name,
                "path": str(relative_path),
                "folder": "" if str(relative_root) == "." else str(relative_root),
                "extension": extension,
                "language": get_language(extension),
                "size": file_path.stat().st_size,
            })

    tree.sort(key=lambda x: x["path"])
    return tree


@frappe.whitelist()
def read_file(app: str, path: str) -> dict:
    app_path, file_path = validate_file(app, path)

    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    stat = file_path.stat()

    return {
        "app": app,
        "app_path": str(app_path),
        "path": path,
        "file_name": file_path.name,
        "extension": file_path.suffix.lower(),
        "language": get_language(file_path.suffix.lower()),
        "size": stat.st_size,
        "modified": stat.st_mtime,
        "content": content,
    }

@frappe.whitelist()
def write_file(app: str, path: str, content: str) -> dict:
    app_path, file_path = validate_file(app, path)

    with open(file_path, "w", encoding="utf-8", newline="") as f:
        f.write(content or "")

    stat = file_path.stat()

    return {
        "app": app,
        "path": path,
        "file_name": file_path.name,
        "extension": file_path.suffix.lower(),
        "language": get_language(file_path.suffix.lower()),
        "size": stat.st_size,
        "modified": stat.st_mtime,
        "message": "File saved successfully",
    }



@frappe.whitelist()
def preview_file(app: str, path: str, max_chars: int = 4000) -> dict:
    app_path, file_path = validate_file(app, path)

    max_chars = int(max_chars or 4000)

    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read(max_chars)

    stat = file_path.stat()

    return {
        "app": app,
        "app_path": str(app_path),
        "path": path,
        "file_name": file_path.name,
        "extension": file_path.suffix.lower(),
        "language": get_language(file_path.suffix.lower()),
        "size": stat.st_size,
        "modified": stat.st_mtime,
        "preview": content,
        "truncated": stat.st_size > max_chars,
    }


@frappe.whitelist()
def search_files(app: str, query: str) -> list[dict]:
    if not query:
        return get_file_tree(app)

    query = query.lower()
    files = get_file_tree(app)

    return [
        file for file in files
        if query in file.get("path", "").lower()
        or query in file.get("file_name", "").lower()
        or query in file.get("folder", "").lower()
    ]
