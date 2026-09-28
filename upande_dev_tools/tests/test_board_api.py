# Copyright (c) 2026, Upande Limited

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from upande_dev_tools.api.board import (
	BULK_LIMIT,
	STAGES,
	get_board,
	get_editable,
	get_modules,
	get_preview,
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

	def _work_tag(self, name: str) -> str:
		if not frappe.db.exists("Work Tag", name):
			frappe.get_doc({"doctype": "Work Tag", "tag_name": name}).insert(ignore_permissions=True)
		return name

	def test_set_field_renames_a_work_item(self) -> None:
		task = self._task(self._project(), subject="Old name")
		set_field("Task", task, "title", "New name")
		self.assertEqual(frappe.db.get_value("Task", task, "subject"), "New name")

	def test_a_work_item_cannot_be_left_without_a_title(self) -> None:
		task = self._task(self._project())
		with self.assertRaises(frappe.ValidationError):
			set_field("Task", task, "title", "   ")

	def test_set_field_rejects_an_unknown_project(self) -> None:
		task = self._task(self._project())
		with self.assertRaises(frappe.ValidationError):
			set_field("Task", task, "project", "Not A Project")

	def test_get_editable_carries_what_the_dialog_needs(self) -> None:
		project = self._project()
		tag = self._work_tag("board-edit-test")
		task = self._task(
			project,
			subject="Read me back",
			description="<p>A description the board never carries</p>",
			exp_start_date=today(),
			exp_end_date=add_days(today(), 3),
		)
		update_work("Task", task, {"tags": [tag]})

		values = get_editable("Task", task)
		self.assertEqual(values["title"], "Read me back")
		self.assertIn("never carries", values["description"])
		self.assertEqual(values["project"], project)
		self.assertEqual(values["start"], today())
		self.assertEqual(values["end"], add_days(today(), 3))
		self.assertEqual(values["assignees"], [])
		self.assertEqual(values["tags"], [tag])
		self.assertIn(values["stage"], STAGES)

	def test_get_editable_refuses_a_workflow_governed_request(self) -> None:
		request = frappe.get_doc({"doctype": "Request", "title": "No edits"}).insert(
			ignore_permissions=True
		)
		with self.assertRaises(frappe.ValidationError):
			get_editable("Request", request.name)

	def test_update_work_saves_every_field_in_one_go(self) -> None:
		area = frappe.get_all("Product Area", limit=1, pluck="name")
		if not area:
			self.skipTest("No Product Area master data on this site.")
		task = self._task(self._project(), subject="Before")
		project = self._project()

		update_work(
			"Task",
			task,
			{
				"title": "After",
				"description": "Rewritten",
				"module": area[0],
				"project": project,
				"start": today(),
				"end": add_days(today(), 5),
				"stage": "In Progress",
			},
		)

		row = frappe.db.get_value(
			"Task",
			task,
			["subject", "description", "custom_module", "project", "exp_start_date", "exp_end_date", "status"],
			as_dict=True,
		)
		self.assertEqual(row.subject, "After")
		self.assertEqual(row.description, "Rewritten")
		self.assertEqual(row.custom_module, area[0])
		self.assertEqual(row.project, project)
		# exp_start_date/exp_end_date are Datetime on this bench, so _coerce stamps an
		# end-of-day time onto them - the date is what the board ever reads back.
		self.assertEqual(str(row.exp_start_date)[:10], today())
		self.assertEqual(str(row.exp_end_date)[:10], add_days(today(), 5))
		self.assertEqual(row.status, "Working")

	def test_update_work_leaves_out_what_it_was_not_given(self) -> None:
		"""The edit dialog drops the description when it carries formatting it cannot
		safely flatten - so a save that says nothing about a field must not blank it."""
		task = self._task(self._project(), description="<p>Keep me</p>")
		update_work("Task", task, {"title": "Renamed only"})
		self.assertEqual(frappe.db.get_value("Task", task, "description"), "<p>Keep me</p>")

	def test_update_work_refuses_a_due_date_before_the_start(self) -> None:
		task = self._task(self._project())
		with self.assertRaises(frappe.ValidationError):
			update_work("Task", task, {"start": today(), "end": add_days(today(), -2)})

	def test_update_work_refuses_a_work_item_with_no_title(self) -> None:
		task = self._task(self._project())
		with self.assertRaises(frappe.ValidationError):
			update_work("Task", task, {"title": ""})

	def test_update_work_stamps_a_task_it_finishes(self) -> None:
		task = self._task(self._project())
		update_work("Task", task, {"stage": "Done"})
		self.assertEqual(str(frappe.db.get_value("Task", task, "completed_on")), today())

	def test_update_work_rejects_a_tag_that_is_not_master_data(self) -> None:
		task = self._task(self._project())
		with self.assertRaises(frappe.ValidationError):
			update_work("Task", task, {"tags": ["not-in-master-data"]})

	def test_update_work_refuses_a_workflow_governed_request(self) -> None:
		request = frappe.get_doc({"doctype": "Request", "title": "No edits"}).insert(
			ignore_permissions=True
		)
		with self.assertRaises(frappe.ValidationError):
			update_work("Request", request.name, {"title": "Renamed"})

	def test_update_work_denies_users_without_a_board_role(self) -> None:
		task = self._task(self._project())
		outsider = self._user("board-writer@example.test", ["Employee"])
		frappe.set_user(outsider)
		try:
			with self.assertRaises(frappe.PermissionError):
				update_work("Task", task, {"title": "Not yours"})
		finally:
			frappe.set_user("Administrator")

	def test_bulk_update_fills_a_column_in_one_call(self) -> None:
		project = self._project()
		tasks = [self._task(project, subject=f"Bulk {i}") for i in range(3)]

		result = bulk_update(
			[{"doctype": "Task", "name": name, "values": {"priority": "High"}} for name in tasks]
		)

		self.assertEqual(sorted(result["saved"]), sorted(tasks))
		self.assertEqual(result["failed"], [])
		for name in tasks:
			self.assertEqual(frappe.db.get_value("Task", name, "priority"), "High")

	def test_bulk_update_carries_several_fields_per_row(self) -> None:
		task = self._task(self._project())
		bulk_update(
			[
				{
					"doctype": "Task",
					"name": task,
					"values": {"priority": "Low", "stage": "In Progress", "title": "Two cells"},
				}
			]
		)
		row = frappe.db.get_value("Task", task, ["priority", "status", "subject"], as_dict=True)
		self.assertEqual(row.priority, "Low")
		self.assertEqual(row.status, "Working")
		self.assertEqual(row.subject, "Two cells")

	def test_one_bad_row_does_not_undo_the_others(self) -> None:
		"""A paste over twenty rows should not be thrown away by the one among them that
		cannot take the value - each row stands or falls on its own savepoint."""
		project = self._project()
		good, other = self._task(project, subject="Keeps"), self._task(project, subject="Also keeps")

		result = bulk_update(
			[
				{"doctype": "Task", "name": good, "values": {"priority": "High"}},
				{"doctype": "Task", "name": "TASK-DOES-NOT-EXIST", "values": {"priority": "High"}},
				{"doctype": "Task", "name": other, "values": {"priority": "High"}},
			]
		)

		self.assertEqual(sorted(result["saved"]), sorted([good, other]))
		self.assertEqual([f["name"] for f in result["failed"]], ["TASK-DOES-NOT-EXIST"])
		self.assertTrue(result["failed"][0]["error"])
		self.assertEqual(frappe.db.get_value("Task", good, "priority"), "High")
		self.assertEqual(frappe.db.get_value("Task", other, "priority"), "High")

	def test_bulk_update_names_the_row_that_refused(self) -> None:
		project = self._project()
		task = self._task(project)
		request = frappe.get_doc({"doctype": "Request", "title": "No edits"}).insert(
			ignore_permissions=True
		)

		result = bulk_update(
			[
				{"doctype": "Task", "name": task, "values": {"priority": "Low"}},
				{"doctype": "Request", "name": request.name, "values": {"priority": "Low"}},
			]
		)
		self.assertEqual(result["saved"], [task])
		self.assertEqual([f["name"] for f in result["failed"]], [request.name])

	def test_bulk_update_refuses_more_rows_than_anyone_meant_to_touch(self) -> None:
		task = self._task(self._project())
		with self.assertRaises(frappe.ValidationError):
			bulk_update(
				[{"doctype": "Task", "name": task, "values": {"priority": "Low"}}] * (BULK_LIMIT + 1)
			)

	def test_bulk_update_denies_users_without_a_board_role(self) -> None:
		task = self._task(self._project())
		outsider = self._user("board-bulk@example.test", ["Employee"])
		frappe.set_user(outsider)
		try:
			with self.assertRaises(frappe.PermissionError):
				bulk_update([{"doctype": "Task", "name": task, "values": {"priority": "Low"}}])
		finally:
			frappe.set_user("Administrator")

	def test_update_work_writes_a_raw_status(self) -> None:
		"""The sheet has a Status column as well as a Stage one - it is the finer of the
		two, so it has to be writable on its own."""
		task = self._task(self._project())
		update_work("Task", task, {"status": "Pending Review"})
		self.assertEqual(frappe.db.get_value("Task", task, "status"), "Pending Review")

	def test_a_status_that_finishes_the_work_is_stamped_too(self) -> None:
		task = self._task(self._project())
		update_work("Task", task, {"status": "Completed"})
		self.assertEqual(str(frappe.db.get_value("Task", task, "completed_on")), today())
