# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import os

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

APP_NAME = "upande_dev_tools"
MODULE_NAME = "Upande Dev Tools"

# Workspace docname; it slugs to the /desk/dev-tools route, so it must match NAV_NAME.
WORKSPACE_NAME = "Dev Tools"
# Workspace docname before the rename; still the Module Def name, which does not change.
LEGACY_WORKSPACE_NAME = "Upande Dev Tools"
# Docname of the Desktop Icon and Workspace Sidebar this app ships.
NAV_NAME = "Dev Tools"
# User-facing name on the sidebar header, Desktop Icon and Workspace.
NAV_TITLE = "Dev Tools"
# Pre-rename docnames left on sites as site data (standard=0).
LEGACY_NAV_NAME = "Upande Dev Tools"

TASK_CUSTOM_FIELDS = {
	"Task": [
		{
			"fieldname": "dev_tools_tab",
			"label": "Dev Tools",
			"fieldtype": "Tab Break",
			"insert_after": "template_task",
		},
		{
			"fieldname": "custom_request",
			"label": "Request",
			"fieldtype": "Link",
			"options": "Request",
			"insert_after": "dev_tools_tab",
			"read_only": 1,
		},
		{
			"fieldname": "custom_planned_for",
			"label": "Planned For",
			"fieldtype": "Date",
			"insert_after": "custom_request",
		},
		{
			"fieldname": "custom_module",
			"label": "Module",
			"fieldtype": "Link",
			"options": "Product Area",
			"insert_after": "custom_planned_for",
			"description": "The part of the system this work belongs to.",
		},
	]
}

ISSUE_CUSTOM_FIELDS = {
	"Issue": [
		{
			"fieldname": "dev_tools_tab",
			"label": "Dev Tools",
			"fieldtype": "Tab Break",
			"insert_after": "content_type",
		},
		{
			"fieldname": "custom_module",
			"label": "Module",
			"fieldtype": "Link",
			"options": "Product Area",
			"insert_after": "dev_tools_tab",
			"description": "The part of the system this issue belongs to.",
		},
	]
}

PROJECT_CUSTOM_FIELDS = {
	"Project": [
		{
			"fieldname": "dev_tools_tab",
			"label": "Dev Tools",
			"fieldtype": "Tab Break",
			# insert_after=notes keeps this tab before the standard Connections tab.
			"insert_after": "notes",
		},
		{
			"fieldname": "custom_project_scope",
			"label": "Project Scope",
			"fieldtype": "Select",
			"options": "\nInternal\nExternal",
			"insert_after": "dev_tools_tab",
		},
	]
}


def create_task_custom_fields() -> None:
	create_custom_fields(TASK_CUSTOM_FIELDS, update=True)


def create_issue_custom_fields() -> None:
	create_custom_fields(ISSUE_CUSTOM_FIELDS, update=True)


def create_project_custom_fields() -> None:
	create_custom_fields(PROJECT_CUSTOM_FIELDS, update=True)


def backfill_project_scope() -> None:
	"""customer set -> External, else Internal. Only updates rows where
	custom_project_scope is still unset."""
	frappe.db.sql(
		"""
		update `tabProject`
		set custom_project_scope = case
			when customer is not null and customer != '' then 'External'
			else 'Internal'
		end
		where custom_project_scope is null or custom_project_scope = ''
		"""
	)


# Must match existing Request.request_type values exactly (Link resolves by docname).
REQUEST_TYPES = ["Feature", "Bug", "Master Data", "Question", "Note", "Chore"]

# (name, sort_order) - lower sorts first.
PRIORITY_LEVELS = [("Low", 0), ("Medium", 1), ("High", 2), ("Urgent", 3)]

# "Seucity" is a typo for "Security" and is intentionally not seeded; see fix_product_area_typo().
PRODUCT_AREAS = [
	"HR",
	"Roses-Sprays",
	"Roses-Standard",
	"Sales",
	"Scouting & Crop Protection",
	"Stores",
	"CRM",
	"livestock management",
	"Payroll",
	"Agric Production",
	"Agric Forecasting",
	"Accounting",
	"Asset Maintenance",
	"Asset Management",
	"QC",
	"Procurement",
	"Dairy",
	"Yoghurt",
	"Shopify",
	"IoT Integration",
	"Security",
	"All",
	"Poultry",
	"Coffee",
	"Coffee Production",
	"Whatsapp integration",
	"Material Request",
	"Mpesa Integration",
	"Loans",
	"Clinic",
	"Fillers",
]

# "Critial Path" and "Critical Path" were the same tag with a typo; normalized to one value.
REQUEST_TAGS = ["Critical Path", "Good to have", "Important (post-go live)", "Important (post-migration)"]

# The one Project Type (native ERPNext Link field on Project) that marks a project as
# belonging to Dev Tools tracking. Every dashboard/portfolio aggregate query filters to this
# value so unrelated business projects (this bench has 27 total, most not software work)
# never distort the counts - see api/portfolio.py, api/project_health.py, api/board.py.
# Deliberately no backfill: every existing project starts excluded, and whoever owns this
# rollout marks the real Dev Tools projects with this type by hand.
DEV_TOOLS_PROJECT_TYPE = "Dev Tools"


def register_master_data() -> None:
	if not frappe.db.exists("Project Type", DEV_TOOLS_PROJECT_TYPE):
		frappe.get_doc({"doctype": "Project Type", "project_type": DEV_TOOLS_PROJECT_TYPE}).insert(
			ignore_permissions=True
		)

	for type_name in REQUEST_TYPES:
		if not frappe.db.exists("Request Type", type_name):
			frappe.get_doc({"doctype": "Request Type", "type_name": type_name}).insert(
				ignore_permissions=True
			)

	for level_name, sort_order in PRIORITY_LEVELS:
		if not frappe.db.exists("Priority Level", level_name):
			frappe.get_doc(
				{"doctype": "Priority Level", "level_name": level_name, "sort_order": sort_order}
			).insert(ignore_permissions=True)

	for area_name in PRODUCT_AREAS:
		if not frappe.db.exists("Product Area", area_name):
			frappe.get_doc({"doctype": "Product Area", "area_name": area_name}).insert(
				ignore_permissions=True
			)

	for tag_name in REQUEST_TAGS:
		if not frappe.db.exists("Request Tag", tag_name):
			frappe.get_doc({"doctype": "Request Tag", "tag_name": tag_name}).insert(ignore_permissions=True)


def fix_product_area_typo() -> None:
	"""'Seucity' was a typo for 'Security' in the source data. No-op once fixed."""
	frappe.db.sql("update `tabRequest` set product_area = 'Security' where product_area = 'Seucity'")


def register_installed_apps_as_deployment_apps() -> None:
	for app_name in frappe.get_installed_apps():
		if frappe.db.exists("Deployment App", app_name):
			continue
		frappe.get_doc(
			{
				"doctype": "Deployment App",
				"app_name": app_name,
				"default_branch": "main",
			}
		).insert(ignore_permissions=True)


def register_dev_portal_page(
	route: str,
	title: str,
	icon: str,
	nav_group: str,
	sort_order: int,
	roles: list[str],
	require_all_roles: bool = False,
) -> None:
	if frappe.db.exists("Dev Portal Page", route):
		return

	frappe.get_doc(
		{
			"doctype": "Dev Portal Page",
			"route": route,
			"title": title,
			"icon": icon,
			"nav_group": nav_group,
			"sort_order": sort_order,
			"require_all_roles": 1 if require_all_roles else 0,
			"allowed_roles": [{"role": role} for role in roles],
		}
	).insert(ignore_permissions=True)


def register_dev_portal_pages() -> None:
	register_dev_portal_page(
		route="dev-portal-settings",
		title="Settings",
		icon="settings",
		nav_group="Admin",
		sort_order=100,
		roles=["Dev Team", "System Manager"],
		require_all_roles=True,
	)
	register_dev_portal_page(
		route="hooks-explorer",
		title="Hooks Explorer",
		icon="search",
		nav_group="Developer",
		sort_order=20,
		roles=["Dev Team"],
	)
	register_dev_portal_page(
		route="dev-dashboard",
		title="Dashboard",
		icon="home",
		nav_group="Developer",
		sort_order=10,
		roles=["Dev Team"],
	)
	register_dev_portal_page(
		route="code-editor",
		title="Code Editor",
		icon="code",
		nav_group="Developer",
		sort_order=30,
		roles=["Dev Team"],
	)
	register_dev_portal_page(
		route="my-day",
		title="My Day",
		icon="calendar",
		nav_group="Developer",
		sort_order=40,
		roles=["Dev Team"],
	)
	register_dev_portal_page(
		route="backlog-board",
		title="Backlog Board",
		icon="trello",
		nav_group="Developer",
		sort_order=50,
		roles=["Dev Team", "Projects Manager"],
	)
	register_dev_portal_page(
		route="code-snapshots",
		title="Code Snapshots",
		icon="archive",
		nav_group="Developer",
		sort_order=60,
		roles=["Dev Team"],
	)
	register_dev_portal_page(
		route="activity-log",
		title="Activity Log",
		icon="activity",
		nav_group="Developer",
		sort_order=70,
		roles=["Dev Team"],
	)
	register_dev_portal_page(
		route="pm-dashboard",
		title="Dashboard",
		icon="home",
		nav_group="Management",
		sort_order=10,
		roles=["Projects Manager"],
	)
	register_dev_portal_page(
		route="review-queue",
		title="Review Queue",
		icon="check-circle",
		nav_group="Management",
		sort_order=20,
		roles=["Projects Manager"],
	)
	register_dev_portal_page(
		route="requests-portal",
		title="My Requests",
		icon="inbox",
		nav_group="Requests",
		sort_order=10,
		roles=["All"],
	)
	register_dev_portal_page(
		route="master-data",
		title="Master Data",
		icon="database",
		nav_group="Admin",
		sort_order=90,
		roles=["Dev Team", "Projects Manager"],
	)


# Frappe syncs these from the app package root as flat <scrub(label)>.json files rather than
# from a module directory (frappe.model.sync.sync_for).
_APP_LEVEL_DIRS = ("desktop_icon", "workspace_sidebar")

_WORKSPACE_PATH = os.path.join("upande_dev_tools", "workspace", "upande_dev_tools", "upande_dev_tools.json")


def _nav_resource_paths() -> list[str]:
	app_root = frappe.get_app_path(APP_NAME)
	paths = []

	for folder in _APP_LEVEL_DIRS:
		folder_path = os.path.join(app_root, folder)
		if not os.path.isdir(folder_path):
			continue
		paths.extend(
			os.path.join(folder_path, name)
			for name in sorted(os.listdir(folder_path))
			if name.endswith(".json")
		)

	workspace = os.path.join(app_root, _WORKSPACE_PATH)
	if os.path.isfile(workspace):
		paths.append(workspace)

	return paths


def resync_nav_resources() -> None:
	"""Force-reload the nav JSON. import_file_by_path otherwise skips a record whose DB
	`modified` is not older than the file's, so shipped layout edits never land."""
	from frappe.modules.import_file import import_file_by_path, read_doc_from_file

	for path in _nav_resource_paths():
		try:
			if not frappe.db.exists("DocType", read_doc_from_file(path).get("doctype")):
				continue
			import_file_by_path(path, force=True, ignore_version=True)
			frappe.db.commit()  # nosemgrep - each nav record must land independently
		except Exception:
			frappe.db.rollback()
			frappe.log_error(
				title=f"{APP_NAME} resync_nav_resources: {os.path.basename(path)}",
				message=frappe.get_traceback(),
			)

	frappe.clear_cache()


def _stale_desktop_icons() -> list[str]:
	"""Tiles opening the same destination as the icon we ship, matched on destination so a
	renamed or auto-generated duplicate is caught whatever it is labelled."""
	targets = [WORKSPACE_NAME, NAV_NAME, LEGACY_NAV_NAME]
	names = set(
		frappe.get_all(
			"Desktop Icon",
			or_filters=[
				["link_to", "in", targets],
				["sidebar", "in", targets],
				["label", "in", targets],
			],
			pluck="name",
		)
	)
	names.update(frappe.get_all("Desktop Icon", filters={"icon_type": "App", "app": APP_NAME}, pluck="name"))
	names.discard(NAV_NAME)
	return sorted(names)


def enforce_single_desktop_icon() -> None:
	"""Leave exactly one Desk tile for this app: desktop_icon/dev_tools.json."""
	if not frappe.db.exists("DocType", "Desktop Icon"):
		return

	for name in _stale_desktop_icons():
		try:
			# Desktop Icon.on_trash deletes the app's shipped JSON when developer_mode is on
			# and both standard and app are set; clear them so it cannot take ours with it.
			frappe.db.set_value(
				"Desktop Icon",
				name,
				{"standard": 0, "app": None, "restrict_removal": 0},
				update_modified=False,
			)
			frappe.delete_doc("Desktop Icon", name, ignore_permissions=True, force=True, ignore_missing=True)
			print(f"{APP_NAME}: removed duplicate Desktop Icon '{name}'")
		except Exception:
			frappe.log_error(
				title=f"{APP_NAME} enforce_single_desktop_icon: {name}",
				message=frappe.get_traceback(),
			)

	frappe.cache.delete_key("desktop_icons")
	frappe.cache.delete_key("bootinfo")


def enforce_single_workspace_sidebar() -> None:
	"""Leave exactly one Workspace Sidebar for this module: workspace_sidebar/dev_tools.json.

	Site-created and auto-generated sidebars carry standard=0 and no `app`, so
	frappe.model.sync.remove_orphan_entities() can never reach them."""
	if not frappe.db.exists("DocType", "Workspace Sidebar"):
		return

	stale = frappe.get_all(
		"Workspace Sidebar",
		filters={
			"module": MODULE_NAME,
			"standard": 0,
			"for_user": ["in", ["", None]],
			"name": ["!=", NAV_NAME],
		},
		pluck="name",
	)
	for name in stale:
		try:
			# Workspace Sidebar.on_trash deletes the app's shipped JSON when developer_mode is
			# on and `app` is set.
			frappe.db.set_value(
				"Workspace Sidebar", name, {"standard": 0, "app": None}, update_modified=False
			)
			frappe.delete_doc(
				"Workspace Sidebar", name, ignore_permissions=True, force=True, ignore_missing=True
			)
			print(f"{APP_NAME}: removed stale Workspace Sidebar '{name}'")
		except Exception:
			frappe.log_error(
				title=f"{APP_NAME} enforce_single_workspace_sidebar: {name}",
				message=frappe.get_traceback(),
			)

	frappe.cache.delete_key("bootinfo")


def sync_workspace_sidebar_title() -> None:
	"""Force NAV_TITLE onto the sidebar header and the Workspace label. The Workspace docname
	is the pre-rename MODULE_NAME, and Workspace.label falls back to it, so reading the label
	and copying it onto the sidebar puts the old name back. db_set, not save: Workspace.on_update
	re-exports the record to the app folder under developer_mode."""
	if not frappe.db.exists("DocType", "Workspace Sidebar"):
		return

	if frappe.db.exists("Workspace Sidebar", NAV_NAME):
		if frappe.db.get_value("Workspace Sidebar", NAV_NAME, "title") != NAV_TITLE:
			frappe.db.set_value("Workspace Sidebar", NAV_NAME, "title", NAV_TITLE, update_modified=False)

	if frappe.db.exists("Workspace", WORKSPACE_NAME):
		for field in ("label", "title"):
			if frappe.db.get_value("Workspace", WORKSPACE_NAME, field) != NAV_TITLE:
				frappe.db.set_value("Workspace", WORKSPACE_NAME, field, NAV_TITLE, update_modified=False)


def rename_legacy_workspace() -> None:
	"""Rename the Workspace docname to WORKSPACE_NAME. The docname is what /desk/<slug>
	resolves against, so while it stays "Upande Dev Tools" the Desktop Icon's /desk/dev-tools
	route 404s. rename_doc is imported directly: the frappe.rename_doc wrapper is whitelisted
	and drops ignore_permissions."""
	from frappe.model.rename_doc import rename_doc

	if not frappe.db.exists("DocType", "Workspace"):
		return
	if not frappe.db.exists("Workspace", LEGACY_WORKSPACE_NAME):
		return
	if frappe.db.exists("Workspace", WORKSPACE_NAME):
		frappe.delete_doc("Workspace", LEGACY_WORKSPACE_NAME, force=True, ignore_permissions=True)
		return

	rename_doc(
		"Workspace",
		LEGACY_WORKSPACE_NAME,
		WORKSPACE_NAME,
		force=True,
		ignore_permissions=True,
		show_alert=False,
	)


def run_setup() -> None:
	create_task_custom_fields()
	create_issue_custom_fields()
	create_project_custom_fields()
	backfill_project_scope()
	register_master_data()
	fix_product_area_typo()
	register_dev_portal_pages()
	register_installed_apps_as_deployment_apps()
	# Before the resync, or the shipped JSON inserts a second Workspace beside the old one.
	rename_legacy_workspace()
	# Nav last: the shipped records must exist before the duplicates around them are pruned.
	resync_nav_resources()
	enforce_single_desktop_icon()
	enforce_single_workspace_sidebar()
	sync_workspace_sidebar_title()
