# Copyright (c) 2026, Upande Limited

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from upande_dev_tools.api.board import (
	BULK_LIMIT,
	STAGES,
	create_task,
	get_board,
	get_editable,
	get_modules,
	get_preview,
	get_projects,
	is_board_role,
	bulk_update,
	set_field,
	set_stage,
	update_work,
)


class IntegrationTestBoardApi(IntegrationTestCase):
	def _project(self) -> str:
		company = frappe.db.get_value("Company", {}, "name")
		if not company:
			self.skipTest("No Company exists on this site to attach a test Project to.")
		return (
			frappe.get_doc(
				{
					"doctype": "Project",
					"project_name": frappe.generate_hash(length=10),
					"company": company,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _task(self, project: str, **kwargs) -> str:
		task = frappe.get_doc(
			{
				"doctype": "Task",
				"subject": kwargs.pop("subject", "Board task"),
				"project": project,
				**kwargs,
			}
		)
		# Same pypika/recursive-CTE incompatibility worked around in Request.on_update() and
		# board.py's set_stage/set_field - this bench's pypika can't run the recursion check.
		task.flags.ignore_recursion_check = True
		task.insert(ignore_permissions=True)
		return task.name

	def _issue(self, project: str, **kwargs) -> str:
		issue = frappe.get_doc(
			{
				"doctype": "Issue",
				"subject": kwargs.pop("subject", "Board issue"),
				"project": project,
				**kwargs,
			}
		).insert(ignore_permissions=True)
		return issue.name

	def _user(self, email: str, roles: list[str]) -> str:
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Test", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		frappe.get_doc("User", email).add_roles(*roles)
		return email

	def test_board_merges_tasks_issues_and_requests(self) -> None:
		project = self._project()
		self._task(project, subject="A task")
		self._issue(project, subject="An issue")
		frappe.get_doc({"doctype": "Request", "title": "A request", "project": project}).insert(
			ignore_permissions=True
		)

		items = get_board(project=project)["items"]
		self.assertEqual({item["doctype"] for item in items}, {"Task", "Issue", "Request"})

	def test_every_item_lands_on_a_known_stage(self) -> None:
		project = self._project()
		self._task(project, status="Pending Review")
		self._issue(project, status="On Hold")

		for item in get_board(project=project)["items"]:
			self.assertIn(item["stage"], STAGES)

	def test_overdue_work_is_flagged_but_finished_work_is_not(self) -> None:
		project = self._project()
		yesterday = add_days(today(), -1)
		self._task(project, subject="Slipping", exp_end_date=yesterday)
		self._task(project, subject="Shipped", exp_end_date=yesterday, status="Completed")

		late = {item["title"]: item["late"] for item in get_board(project=project)["items"]}
		self.assertTrue(late["Slipping"])
		self.assertFalse(late["Shipped"])

	def test_dates_come_back_as_plain_iso_dates(self) -> None:
		project = self._project()
		self._task(project, exp_start_date=today(), exp_end_date=add_days(today(), 3))
		self._issue(project, opening_date=today(), sla_resolution_by=f"{add_days(today(), 3)} 17:00:00")

		for item in get_board(project=project)["items"]:
			for field in ("start", "end"):
				if item[field]:
					self.assertRegex(item[field], r"^\d{4}-\d{2}-\d{2}$")

	def test_module_rides_on_every_kind_of_work(self) -> None:
		project = self._project()
		area = frappe.get_all("Product Area", limit=1, pluck="name")
		if not area:
			self.skipTest("No Product Area master data on this site.")
		self._task(project, custom_module=area[0])
		self._issue(project, custom_module=area[0])
		frappe.get_doc(
			{"doctype": "Request", "title": "Scoped", "project": project, "product_area": area[0]}
		).insert(ignore_permissions=True)

		modules = {item["module"] for item in get_board(project=project)["items"]}
		self.assertEqual(modules, {area[0]})

	def test_set_field_writes_a_module(self) -> None:
		area = frappe.get_all("Product Area", limit=1, pluck="name")
		if not area:
			self.skipTest("No Product Area master data on this site.")
		task = self._task(self._project())
		set_field("Task", task, "module", area[0])
		self.assertEqual(frappe.db.get_value("Task", task, "custom_module"), area[0])

	def test_set_field_rejects_an_unknown_module(self) -> None:
		task = self._task(self._project())
		with self.assertRaises(frappe.ValidationError):
			set_field("Task", task, "module", "Not A Module")

	def test_get_modules_lists_master_data(self) -> None:
		self.assertEqual(get_modules(), frappe.get_all("Product Area", pluck="name", order_by="name asc"))

	def test_preview_carries_enough_to_decide_without_opening(self) -> None:
		project = self._project()
		task = self._task(project, subject="Bench is slow", description="<p>It hangs on save.</p>")

		preview = get_preview("Task", task)
		self.assertEqual(preview["title"], "Bench is slow")
		self.assertEqual(preview["summary"], "It hangs on save.")
		self.assertIsNone(preview["image"], "nothing was attached")

	def test_preview_trims_a_long_description_on_a_word(self) -> None:
		body = "<p>" + ("reconciliation " * 60) + "</p>"
		task = self._task(self._project(), description=body)

		summary = get_preview("Task", task)["summary"]
		self.assertTrue(summary.endswith("…"))
		self.assertLess(len(summary), 300)
		self.assertNotIn("  ", summary)

	def test_preview_points_at_an_attached_screenshot(self) -> None:
		issue = self._issue(self._project())
		frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"{frappe.generate_hash(length=8)}-screenshot.png",
				"is_private": 1,
				"attached_to_doctype": "Issue",
				"attached_to_name": issue,
				"content": b"\x89PNG\r\n\x1a\n",
			}
		).insert(ignore_permissions=True)

		image = get_preview("Issue", issue)["image"]
		# served through this app, never linked straight at a private file
		self.assertIn("upande_dev_tools.api.board.preview_image", image)
		self.assertNotIn("/private/files/", image)

	def test_preview_refuses_a_doctype_that_is_not_work(self) -> None:
		with self.assertRaises(frappe.ValidationError):
			get_preview("User", "Administrator")

	def test_preview_denies_someone_without_a_board_role(self) -> None:
		task = self._task(self._project())
		outsider = self._user("preview-outsider@example.test", ["Employee"])
		frappe.set_user(outsider)
		try:
			with self.assertRaises(frappe.PermissionError):
				get_preview("Task", task)
		finally:
			frappe.set_user("Administrator")

	def test_board_reports_total_beyond_the_limit(self) -> None:
		project = self._project()
		for index in range(3):
			self._task(project, subject=f"Task {index}")

		board = get_board(project=project, limit=2)
		self.assertEqual(len(board["items"]), 2)
		self.assertEqual(board["total"], 3)

	def test_board_denies_a_project_the_user_cannot_read(self) -> None:
		project = self._project()
		outsider = self._user("board-outsider@example.test", ["Employee"])
		frappe.set_user(outsider)
		try:
			with self.assertRaises(frappe.PermissionError):
				get_board(project=project)
		finally:
			frappe.set_user("Administrator")

	def test_is_board_role_matches_what_get_projects_enforces(self) -> None:
		outsider = self._user("outsider-board-role-flag@example.test", ["Employee"])
		dev = self._user("dev-board-role-flag@example.test", ["Dev Team"])
		frappe.set_user(outsider)
		try:
			self.assertFalse(is_board_role())
			with self.assertRaises(frappe.PermissionError):
				get_projects()
		finally:
			frappe.set_user("Administrator")
		frappe.set_user(dev)
		try:
			self.assertTrue(is_board_role())
			get_projects()
		finally:
			frappe.set_user("Administrator")

	def test_board_is_readable_by_any_authenticated_user_without_a_project(self) -> None:
		"""backlog-board's Dev Portal Page is open to "All" now - the unscoped, cross-project
		view has to actually be reachable by someone with no board role at all, or the page
		it backs is just a PermissionError. A specific project still needs real read
		permission (see test_board_denies_a_project_the_user_cannot_read)."""
		outsider = self._user("board-no-role@example.test", [])
		frappe.set_user(outsider)
		try:
			get_board()
		finally:
			frappe.set_user("Administrator")

	def test_set_stage_moves_a_task(self) -> None:
		task = self._task(self._project())
		set_stage("Task", task, "In Progress")
		self.assertEqual(frappe.db.get_value("Task", task, "status"), "Working")

	def test_set_stage_moves_an_issue(self) -> None:
		issue = self._issue(self._project())
		set_stage("Issue", issue, "Blocked")
		self.assertEqual(frappe.db.get_value("Issue", issue, "status"), "On Hold")

	def test_set_stage_refuses_a_workflow_governed_request(self) -> None:
		request = frappe.get_doc({"doctype": "Request", "title": "Hands off"}).insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			set_stage("Request", request.name, "Done")

	def test_set_stage_rejects_an_unknown_stage(self) -> None:
		task = self._task(self._project())
		with self.assertRaises(frappe.ValidationError):
			set_stage("Task", task, "Not A Stage")

	def test_set_field_edits_a_task_priority_and_due_date(self) -> None:
		task = self._task(self._project())
		set_field("Task", task, "priority", "Urgent")
		set_field("Task", task, "end", add_days(today(), 7))
		row = frappe.db.get_value("Task", task, ["priority", "exp_end_date"], as_dict=True)
		self.assertEqual(row.priority, "Urgent")
		# exp_end_date is a Datetime on some benches and a Date on others
		self.assertTrue(str(row.exp_end_date).startswith(add_days(today(), 7)))

	def test_an_edited_date_reads_back_as_a_plain_date(self) -> None:
		project = self._project()
		task = self._task(project)
		set_field("Task", task, "end", add_days(today(), 5))
		item = next(i for i in get_board(project=project)["items"] if i["name"] == task)
		self.assertEqual(item["end"], add_days(today(), 5))

	def test_set_field_writes_an_issue_resolution_as_a_datetime(self) -> None:
		issue = self._issue(self._project())
		set_field("Issue", issue, "end", add_days(today(), 4))
		self.assertTrue(
			str(frappe.db.get_value("Issue", issue, "sla_resolution_by")).startswith(add_days(today(), 4))
		)

	def test_set_field_refuses_a_field_that_is_not_editable(self) -> None:
		task = self._task(self._project())
		with self.assertRaises(frappe.ValidationError):
			set_field("Task", task, "subject", "Renamed from the board")

	def test_set_field_refuses_a_workflow_governed_request(self) -> None:
		request = frappe.get_doc({"doctype": "Request", "title": "No edits"}).insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			set_field("Request", request.name, "priority", "High")

	def test_set_field_rejects_an_unknown_priority(self) -> None:
		task = self._task(self._project())
		with self.assertRaises(frappe.ValidationError):
			set_field("Task", task, "priority", "Whenever")

	def test_set_field_denies_users_without_a_board_role(self) -> None:
		task = self._task(self._project())
		outsider = self._user("board-editor@example.test", ["Employee"])
		frappe.set_user(outsider)
		try:
			with self.assertRaises(frappe.PermissionError):
				set_field("Task", task, "priority", "High")
		finally:
			frappe.set_user("Administrator")

	def test_set_stage_denies_users_without_a_board_role(self) -> None:
		task = self._task(self._project())
		outsider = self._user("board-mover@example.test", ["Employee"])
		frappe.set_user(outsider)
		try:
			with self.assertRaises(frappe.PermissionError):
				set_stage("Task", task, "Done")
		finally:
			frappe.set_user("Administrator")

	def _tag(self, name: str = "Chore") -> str:
		if not frappe.db.exists("Work Tag", name):
			frappe.get_doc({"doctype": "Work Tag", "tag_name": name}).insert(ignore_permissions=True)
		return name

	def test_create_task_denies_users_without_a_board_role_but_creates_a_request(self) -> None:
		"""Not permitted to add straight to the board doesn't mean not permitted at all -
		it becomes a Request instead (as "Chore"), going through the normal review pipeline,
		the same as anything else that user raises. project isn't forwarded (an outsider has
		no reason to have Project read access), so it's left for a PM to attach later."""
		project = self._project()
		tag = self._tag()
		outsider = self._user("board-add-outsider@example.test", ["Employee"])
		frappe.set_user(outsider)
		try:
			result = create_task(project=project, subject="Outsider's backlog add", tags=[tag])
		finally:
			frappe.set_user("Administrator")
		self.assertFalse(frappe.db.exists("Task", result["name"]))
		doc = frappe.get_doc("Request", result["name"])
		self.assertEqual(doc.request_type, "Chore")
		self.assertEqual(doc.owner, outsider)
		self.assertFalse(doc.project)

	def test_create_task_still_creates_a_request_for_just_one_of_the_two_trusted_roles(self) -> None:
		"""Dev Team and Projects Manager together are trusted to skip review - either one
		alone is not, same as having neither."""
		project = self._project()
		tag = self._tag()
		for role in ("Dev Team", "Projects Manager"):
			user = self._user(f"board-add-{role.lower().replace(' ', '-')}@example.test", [role])
			frappe.set_user(user)
			try:
				result = create_task(project=project, subject=f"{role} solo backlog add", tags=[tag])
			finally:
				frappe.set_user("Administrator")
			self.assertFalse(frappe.db.exists("Task", result["name"]), f"{role} alone should not skip review")
			self.assertTrue(frappe.db.exists("Request", result["name"]))

	def test_create_task_creates_a_real_task_for_both_trusted_roles_together(self) -> None:
		project = self._project()
		tag = self._tag()
		dev_pm = self._user("board-add-dev-pm@example.test", ["Dev Team", "Projects Manager"])
		frappe.set_user(dev_pm)
		try:
			result = create_task(project=project, subject="Dev+PM direct backlog add", tags=[tag])
		finally:
			frappe.set_user("Administrator")
		self.assertTrue(frappe.db.exists("Task", result["name"]))

	def test_create_task_accepts_no_project_at_all_for_an_untrusted_caller(self) -> None:
		"""The "New task" popup hides the Project field entirely for anyone not trusted to
		skip review, so the client never sends it - project must be genuinely optional on
		this end, not just unused, or every one of those submits 500s before the trust
		check even runs."""
		tag = self._tag()
		outsider = self._user("board-add-no-project@example.test", ["Employee"])
		frappe.set_user(outsider)
		try:
			result = create_task(subject="No project at all", tags=[tag])
		finally:
			frappe.set_user("Administrator")
		self.assertTrue(frappe.db.exists("Request", result["name"]))

	def test_create_task_creates_a_real_task_for_system_manager_alone(self) -> None:
		"""System Manager is the same admin bypass every other board action already grants."""
		project = self._project()
		tag = self._tag()
		admin = self._user("board-add-sysmgr@example.test", ["System Manager"])
		frappe.set_user(admin)
		try:
			result = create_task(project=project, subject="Sysmgr direct backlog add", tags=[tag])
		finally:
			frappe.set_user("Administrator")
		self.assertTrue(frappe.db.exists("Task", result["name"]))
