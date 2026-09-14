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


def create_issue_custom_fields() -> None:
	create_custom_fields(ISSUE_CUSTOM_FIELDS, update=True)


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


# request_type/priority/product_area values seeded here are exactly the strings already
# stored on the 1179 real imported Request rows (confirmed directly against the live
# database before writing this list) - since each field kept the same column, converting it
# from Select to Link needed no data migration at all, as long as a master record exists
# under that exact name. "Chore" and "Question" have no existing rows yet but are added so
# they're pickable without a developer touching code, matching what the source backlog sheet
# itself already distinguished (Feature/Issue/Master Data/Chore - "Issue" was mapped to "Bug"
# during the original import, kept as-is here for continuity with the live data).
REQUEST_TYPES = ["Feature", "Bug", "Master Data", "Question", "Note", "Chore"]

# (name, sort_order) - lower sorts first.
PRIORITY_LEVELS = [("Low", 0), ("Medium", 1), ("High", 2), ("Urgent", 3)]

# Every distinct product_area value already live on real Request rows, plus a handful the
# source backlog sheet used that hadn't reached a real row yet. "Seucity" (a typo in the
# source data for one row) is deliberately NOT seeded here - see fix_product_area_typo().
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

# Recovered from the source backlog sheet's own "Priority" column, which actually held a mix
# of the real priority level (Urgent - already covered by PRIORITY_LEVELS) and free-text tags
# that never had anywhere to go, so were silently dropped during the original import. ",Critial
# Path" (178 rows) and "Critical Path" (56 rows) are the same tag with a typo - normalized to
# one here.
REQUEST_TAGS = ["Critical Path", "Good to have", "Important (post-go live)", "Important (post-migration)"]


def register_master_data() -> None:
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
	"""One row in the real imported data has product_area='Seucity' (a typo in the source
	backlog sheet for 'Security', which is already a real Product Area). Runs every migrate
	but is a no-op once fixed - only touches rows still holding the exact typo."""
	frappe.db.sql("update `tabRequest` set product_area = 'Security' where product_area = 'Seucity'")


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
	register_dev_portal_page(
		route="master-data",
		title="Master Data",
		icon="database",
		nav_group="Admin",
		sort_order=90,
		roles=["Dev Team", "Projects Manager"],
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
