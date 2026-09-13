import frappe
from frappe import _

REVIEWER_ROLES = {"Dev Team", "Projects Manager", "System Manager"}


@frappe.whitelist()
def create_request(
	title: str,
	request_type: str,
	description: str | None = None,
	product_area: str | None = None,
	project: str | None = None,
	source: str = "Desk",
) -> dict:
	doc = frappe.get_doc(
		{
			"doctype": "Request",
			"title": title,
			"request_type": request_type,
			"description": description,
			"product_area": product_area,
			"project": project,
			"source": source,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.as_dict()


@frappe.whitelist()
def get_my_requests(status: str | None = None) -> list[dict]:
	filters: dict[str, str] = {"raised_by_user": frappe.session.user}
	if status:
		filters["workflow_state"] = status

	return frappe.get_all(
		"Request",
		filters=filters,
		fields=[
			"name",
			"title",
			"request_type",
			"workflow_state",
			"priority",
			"project",
			"linked_task",
			"creation",
		],
		order_by="creation desc",
		ignore_permissions=True,
	)


@frappe.whitelist()
def get_review_queue() -> list[dict]:
	if not set(frappe.get_roles()) & REVIEWER_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	return frappe.get_all(
		"Request",
		filters={"workflow_state": "Under Review"},
		fields=["name", "title", "request_type", "product_area", "project", "raised_by_user", "creation"],
		order_by="creation asc",
		ignore_permissions=True,
	)
