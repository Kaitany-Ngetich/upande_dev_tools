import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

TASK_CUSTOM_FIELDS = {
	"Task": [
		{
			"fieldname": "custom_request",
			"label": "Request",
			"fieldtype": "Link",
			"options": "Request",
			"insert_after": "project",
			"read_only": 1,
			"description": "The Request this Task was promoted from, if any.",
		},
		{
			"fieldname": "custom_planned_for",
			"label": "Planned For",
			"fieldtype": "Date",
			"insert_after": "priority",
			"description": "The day a developer has chosen to work on this task.",
		},
	]
}


def create_task_custom_fields() -> None:
	create_custom_fields(TASK_CUSTOM_FIELDS, update=True)


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
		roles=["Dev Team"],
	)


def run_setup() -> None:
	create_task_custom_fields()
	register_dev_portal_pages()
