# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import frappe
from frappe import _

DEPLOYER_ROLES = {"Dev Team", "System Manager"}
DEPLOYMENT_VIEWER_ROLES = {"Dev Team", "System Manager", "Projects Manager"}
DEPLOYMENT_APPROVER_ROLES = {"Projects Manager", "System Manager"}
DEPLOYMENT_STATE_CHANGE_ROLES = {"Dev Team", "System Manager"}


def can_change_deployment_state(user: str | None = None) -> bool:
	"""Start/Mark Deployed/Mark Failed/Retry need Dev Team AND System Manager together -
	same dual-gate shape as Dev Portal Settings, not either role alone (DEPLOYER_ROLES,
	which this deliberately doesn't reuse, is an OR set for a different question - who
	may raise a request at all). The Workflow's own "allowed" role stays Dev Team, so the
	transition buttons stay visible to the right audience; this is the real backstop, and
	DeploymentRequest.validate() enforces it again so the desk form can't drive a state
	change around it - see that docstring for why a wrapper here alone isn't enough."""
	return DEPLOYMENT_STATE_CHANGE_ROLES <= set(frappe.get_roles(user))


@frappe.whitelist()
def get_deployment_apps() -> list[dict]:
	if not set(frappe.get_roles()) & DEPLOYER_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	return frappe.get_all(
		"Deployment App", fields=["name", "default_branch"], order_by="name asc", ignore_permissions=True
	)


@frappe.whitelist()
def get_deployment_instances() -> list[dict]:
	if not set(frappe.get_roles()) & DEPLOYER_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	return frappe.get_all(
		"Deployment Instance",
		fields=["name", "environment_type"],
		order_by="name asc",
		ignore_permissions=True,
	)


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
		fields=["name", "app", "instance", "branch", "workflow_state", "requires_approval", "approval_status", "creation"],
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
		fields=[
			"name", "app", "instance", "branch", "workflow_state",
			"requires_approval", "approval_status", "requested_by_user", "creation",
		],
		order_by="creation asc",
		ignore_permissions=True,
	)


@frappe.whitelist()
def get_recent_deployments(limit: int = 10) -> dict:
	"""Deployment activity across every status, unlike get_deployment_queue (Requested/In
	Progress/Failed only, Dev Team/System Manager only)."""
	if not set(frappe.get_roles()) & DEPLOYMENT_VIEWER_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	limit = max(1, min(int(limit), 50))
	rows = frappe.get_all(
		"Deployment Request",
		fields=[
			"name",
			"app",
			"instance",
			"branch",
			"commit_hash",
			"description",
			"workflow_state",
			"requires_approval",
			"approval_status",
			"requested_by_user",
			"creation",
		],
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

	if not can_change_deployment_state():
		frappe.throw(
			_("Changing a deployment's state needs both Dev Team and System Manager."),
			frappe.PermissionError,
		)

	doc = frappe.get_doc("Deployment Request", name)
	if action == "Start Deployment" and doc.requires_approval and doc.approval_status != "Approved":
		frappe.throw(
			_(
				"This deployment was raised during peak hours and needs Projects Manager "
				"approval before it can start."
			),
			frappe.PermissionError,
		)
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


@frappe.whitelist()
def get_pending_deployment_approvals() -> list[dict]:
	if not set(frappe.get_roles()) & DEPLOYMENT_APPROVER_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	return frappe.get_all(
		"Deployment Request",
		filters={"requires_approval": 1, "approval_status": "Pending"},
		fields=[
			"name",
			"app",
			"instance",
			"branch",
			"description",
			"requested_by_user",
			"creation",
		],
		order_by="creation asc",
		ignore_permissions=True,
	)


@frappe.whitelist()
def approve_deployment_request(name: str, note: str | None = None) -> dict:
	if not set(frappe.get_roles()) & DEPLOYMENT_APPROVER_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	doc = frappe.get_doc("Deployment Request", name)
	if not doc.requires_approval:
		frappe.throw(_("This deployment was never flagged for approval."), frappe.ValidationError)
	if doc.approval_status == "Approved":
		return doc.as_dict()

	doc.approval_status = "Approved"
	doc.approved_by = frappe.session.user
	doc.approved_on = frappe.utils.now_datetime()
	if note:
		doc.approval_note = note
	doc.save(ignore_permissions=True)
	return doc.as_dict()


@frappe.whitelist()
def reject_deployment_request(name: str, note: str | None = None) -> dict:
	if not set(frappe.get_roles()) & DEPLOYMENT_APPROVER_ROLES:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	doc = frappe.get_doc("Deployment Request", name)
	if not doc.requires_approval:
		frappe.throw(_("This deployment was never flagged for approval."), frappe.ValidationError)

	doc.approval_status = "Rejected"
	doc.approved_by = frappe.session.user
	doc.approved_on = frappe.utils.now_datetime()
	if note:
		doc.approval_note = note
	doc.save(ignore_permissions=True)
	return doc.as_dict()
