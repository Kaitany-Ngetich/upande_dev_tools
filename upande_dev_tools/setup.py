import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

# Every field this app adds to a standard doctype lives in its own "Dev Tools" tab (a Tab
# Break custom field) rather than mixed into that doctype's stock layout - keeps it obvious
# at a glance which fields are this app's and which are core Task/Project fields.
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
			"description": "The Request this Task was promoted from, if any.",
		},
		{
			"fieldname": "custom_planned_for",
			"label": "Planned For",
			"fieldtype": "Date",
			"insert_after": "custom_request",
			"description": "The day a developer has chosen to work on this task.",
		},
	]
}

PROJECT_CUSTOM_FIELDS = {
	"Project": [
		{
			"fieldname": "dev_tools_tab",
			"label": "Dev Tools",
			"fieldtype": "Tab Break",
			# Inserted before the standard "Connections" tab (Project's own last field),
			# not after it, so Connections stays the final tab as ERPNext ships it.
			"insert_after": "notes",
		},
		{
			"fieldname": "custom_project_scope",
			"label": "Project Scope",
			"fieldtype": "Select",
			"options": "\nInternal\nExternal",
			"insert_after": "dev_tools_tab",
			"description": (
				"Internal Upande work (e.g. building a greenhouse) vs an external/customer"
				" engagement (e.g. an ERP implementation)."
			),
		},
	]
}


def create_task_custom_fields() -> None:
	create_custom_fields(TASK_CUSTOM_FIELDS, update=True)


def create_project_custom_fields() -> None:
	create_custom_fields(PROJECT_CUSTOM_FIELDS, update=True)


def backfill_project_scope() -> None:
	"""One-time-per-row heuristic: a Project with a customer set reads as an external/customer
	engagement, one with no customer reads as Upande's own internal work. Only ever touches
	rows still unset, so a value someone corrects by hand is never overwritten on a later
	migrate."""
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


def register_installed_apps_as_deployment_apps() -> None:
	"""Seeds one Deployment App per app currently installed on this bench, so choosing what to
	deploy starts as a dropdown of what's actually here - not a blank list you have to type
	into from memory. repository_url is left blank (fill in once known); it's not required,
	since the point of the record is "this app exists and is deployable", not the URL. Doesn't
	stop anyone from adding a Deployment App for something not installed here (e.g. a
	client-only repo) - that's still just a new Deployment App record via the Link field's own
	quick-entry."""
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


def run_setup() -> None:
	create_task_custom_fields()
	create_project_custom_fields()
	backfill_project_scope()
	register_dev_portal_pages()
	register_installed_apps_as_deployment_apps()
