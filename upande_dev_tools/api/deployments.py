import frappe
from frappe import _

DEPLOYER_ROLES = {"Dev Team", "System Manager"}
DEPLOYMENT_VIEWER_ROLES = {"Dev Team", "System Manager", "Projects Manager"}


@frappe.whitelist()
def create_deployment_request(
	app: str,
	instance: str,
	branch: str | None = None,
	description: str | None = None,
	linked_request: str | None = None,
) -> dict:
	if not set(frappe.get_roles()) & DEPLOYER_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	doc = frappe.get_doc(
		{
			"doctype": "Deployment Request",
			"app": app,
			"instance": instance,
			"branch": branch,
			"description": description,
			"linked_request": linked_request,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.as_dict()


@frappe.whitelist()
def get_my_deployment_requests(status: str | None = None) -> list[dict]:
	filters: dict[str, str] = {"requested_by_user": frappe.session.user}
	if status:
		filters["workflow_state"] = status

	return frappe.get_all(
		"Deployment Request",
		filters=filters,
		fields=["name", "app", "instance", "branch", "workflow_state", "creation"],
		order_by="creation desc",
		ignore_permissions=True,
	)


@frappe.whitelist()
def get_deployment_queue() -> list[dict]:
	if not set(frappe.get_roles()) & DEPLOYER_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	return frappe.get_all(
		"Deployment Request",
		filters={"workflow_state": ["in", ["Requested", "In Progress", "Failed"]]},
		fields=["name", "app", "instance", "branch", "workflow_state", "requested_by_user", "creation"],
		order_by="creation asc",
		ignore_permissions=True,
	)


@frappe.whitelist()
def get_recent_deployments(limit: int = 10) -> dict:
	"""Recent deployment activity across every status, not just the pending queue -
	get_deployment_queue only ever shows Requested/In Progress/Failed rows (and is Dev
	Team/System Manager only), so a PM watching the dashboard had no way to see deployment
	history at all, successful or not."""
	if not set(frappe.get_roles()) & DEPLOYMENT_VIEWER_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	limit = max(1, min(int(limit), 50))
	rows = frappe.get_all(
		"Deployment Request",
		fields=["name", "app", "instance", "branch", "commit_hash", "workflow_state", "creation"],
		order_by="creation desc",
		limit=limit,
		ignore_permissions=True,
	)
	counts = frappe.db.sql(
		"select workflow_state, count(*) from `tabDeployment Request` group by workflow_state",
	)
	return {"recent": rows, "counts_by_state": dict(counts)}


@frappe.whitelist()
def update_deployment_status(
	name: str,
	action: str,
	commit_hash: str | None = None,
	errors: str | None = None,
	fix_notes: str | None = None,
) -> dict:
	from frappe.model.workflow import apply_workflow

	doc = frappe.get_doc("Deployment Request", name)
	if commit_hash:
		doc.commit_hash = commit_hash
	if errors:
		doc.errors = errors
	if fix_notes:
		doc.fix_notes = fix_notes
	if action == "Mark Deployed":
		doc.deployed_by_user = frappe.session.user
	if commit_hash or errors or fix_notes or action == "Mark Deployed":
		doc.save()

	updated = apply_workflow(doc, action)
	return updated.as_dict()
