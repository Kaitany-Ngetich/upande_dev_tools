# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from upande_dev_tools.api.master_data import (
	add_master_data,
	delete_master_data,
	get_master_data,
	get_master_data_kinds,
	has_master_data_access,
	set_master_data_disabled,
	update_master_data,
)

ALL_THREE = ["Dev Team", "Projects Manager", "System Manager"]


class IntegrationTestMasterDataApi(IntegrationTestCase):
	def _make_user(self, email: str, roles: list[str]) -> str:
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Test", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		user = frappe.get_doc("User", email)
		if roles:
			user.add_roles(*roles)
		return email

	def test_get_master_data_kinds_denies_users_without_access(self) -> None:
		outsider = self._make_user("outsider-masterdata@example.test", [])
		frappe.set_user(outsider)
		try:
			with self.assertRaises(frappe.PermissionError):
				get_master_data_kinds()
		finally:
			frappe.set_user("Administrator")

	def test_get_master_data_is_readable_by_anyone_but_still_write_gated(self) -> None:
		"""get_master_data itself is deliberately public read (see its own docstring) - the
		board and the request form both need Priority Level/Product Area without needing
		all three CRUD roles. has_master_data_access still gates the writes below it."""
		outsider = self._make_user("outsider-masterdata-flag@example.test", [])
		frappe.set_user(outsider)
		try:
			self.assertFalse(has_master_data_access())
			get_master_data("priority_level")
			with self.assertRaises(frappe.PermissionError):
				add_master_data("priority_level", "Outsider-added level")
		finally:
			frappe.set_user("Administrator")
		all_three = self._make_user("all-three-masterdata-flag@example.test", ALL_THREE)
		frappe.set_user(all_three)
		try:
			self.assertTrue(has_master_data_access())
			get_master_data("priority_level")
		finally:
			frappe.set_user("Administrator")

	def test_get_master_data_kinds_lists_all_kinds(self) -> None:
		all_three = self._make_user("all-three-masterdata@example.test", ALL_THREE)
		frappe.set_user(all_three)
		try:
			kinds = get_master_data_kinds()
		finally:
			frappe.set_user("Administrator")
		self.assertEqual({k["key"] for k in kinds}, {"request_type", "priority_level", "product_area", "tag"})

	def test_two_of_the_three_roles_is_not_enough(self) -> None:
		"""Dev Team AND Projects Manager AND System Manager together - having only two of
		the three is the same as having none for real CRUD here."""
		for pair in (["Dev Team", "Projects Manager"], ["Dev Team", "System Manager"], ["Projects Manager", "System Manager"]):
			user = self._make_user(f"two-of-three-{'-'.join(pair).lower().replace(' ', '')}@example.test", pair)
			frappe.set_user(user)
			try:
				self.assertFalse(has_master_data_access())
				with self.assertRaises(frappe.PermissionError):
					add_master_data(key="product_area", value="Should never be created")
			finally:
				frappe.set_user("Administrator")

	def test_add_and_list_a_product_area(self) -> None:
		dev = self._make_user("dev-masterdata@example.test", ALL_THREE)
		name = "Test Master Data Product Area"
		if frappe.db.exists("Product Area", name):
			frappe.delete_doc("Product Area", name, force=True)

		frappe.set_user(dev)
		try:
			add_master_data(key="product_area", value=name)
			rows = get_master_data(key="product_area")
		finally:
			frappe.set_user("Administrator")

		self.assertIn(name, [r["name"] for r in rows])

	def test_add_master_data_rejects_a_duplicate(self) -> None:
		dev = self._make_user("dev-masterdata-dup@example.test", ALL_THREE)
		name = "Test Master Data Duplicate Area"
		if frappe.db.exists("Product Area", name):
			frappe.delete_doc("Product Area", name, force=True)

		frappe.set_user(dev)
		try:
			add_master_data(key="product_area", value=name)
			with self.assertRaises(frappe.DuplicateEntryError):
				add_master_data(key="product_area", value=name)
		finally:
			frappe.set_user("Administrator")

	def test_add_master_data_rejects_an_unknown_kind(self) -> None:
		dev = self._make_user("dev-masterdata-badkind@example.test", ALL_THREE)
		frappe.set_user(dev)
		try:
			with self.assertRaises(frappe.ValidationError):
				add_master_data(key="task_status", value="Whatever")
		finally:
			frappe.set_user("Administrator")

	def test_set_master_data_disabled_toggles_the_flag(self) -> None:
		dev = self._make_user("dev-masterdata-disable@example.test", ALL_THREE)
		name = "Test Master Data Disable Type"
		if frappe.db.exists("Request Type", name):
			frappe.delete_doc("Request Type", name, force=True)

		frappe.set_user(dev)
		try:
			add_master_data(key="request_type", value=name)
			set_master_data_disabled(key="request_type", name=name, disabled=True)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(frappe.db.get_value("Request Type", name, "disabled"), 1)

	def test_priority_level_add_respects_sort_order(self) -> None:
		dev = self._make_user("dev-masterdata-sort@example.test", ALL_THREE)
		name = "Test Master Data Priority Level"
		if frappe.db.exists("Priority Level", name):
			frappe.delete_doc("Priority Level", name, force=True)

		frappe.set_user(dev)
		try:
			add_master_data(key="priority_level", value=name, sort_order=7)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(frappe.db.get_value("Priority Level", name, "sort_order"), 7)

	def test_update_master_data_renames_and_repoints_existing_links(self) -> None:
		"""Renaming is a real frappe.rename_doc (force=True, since these ship
		allow_rename=0) - an existing Request already classified under the old name has
		to end up pointing at the new one, not left dangling."""
		all_three = self._make_user("update-masterdata-rename@example.test", ALL_THREE)
		old_name = "Test Master Data Old Area"
		new_name = "Test Master Data Renamed Area"
		for name in (old_name, new_name):
			if frappe.db.exists("Product Area", name):
				frappe.delete_doc("Product Area", name, force=True)

		frappe.set_user(all_three)
		try:
			add_master_data(key="product_area", value=old_name)
			request = frappe.get_doc(
				{"doctype": "Request", "title": "Uses the old area name", "product_area": old_name}
			)
			request.flags.ignore_recursion_check = True
			request.insert(ignore_permissions=True)
			result = update_master_data(key="product_area", name=old_name, value=new_name)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(result["name"], new_name)
		self.assertFalse(frappe.db.exists("Product Area", old_name))
		self.assertEqual(frappe.db.get_value("Request", request.name, "product_area"), new_name)

	def test_update_master_data_updates_priority_level_sort_order(self) -> None:
		all_three = self._make_user("update-masterdata-sort@example.test", ALL_THREE)
		name = "Test Master Data Resort Level"
		if frappe.db.exists("Priority Level", name):
			frappe.delete_doc("Priority Level", name, force=True)

		frappe.set_user(all_three)
		try:
			add_master_data(key="priority_level", value=name, sort_order=1)
			update_master_data(key="priority_level", name=name, value=name, sort_order=9)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(frappe.db.get_value("Priority Level", name, "sort_order"), 9)

	def test_update_master_data_denies_a_solo_role_caller(self) -> None:
		dev = self._make_user("update-masterdata-denied@example.test", ["Dev Team"])
		name = "Test Master Data Update Denied"
		if not frappe.db.exists("Product Area", name):
			frappe.get_doc({"doctype": "Product Area", "area_name": name}).insert(ignore_permissions=True)
		frappe.set_user(dev)
		try:
			with self.assertRaises(frappe.PermissionError):
				update_master_data(key="product_area", name=name, value="Should not rename")
		finally:
			frappe.set_user("Administrator")

	def test_delete_master_data_removes_an_unused_entry(self) -> None:
		all_three = self._make_user("delete-masterdata@example.test", ALL_THREE)
		name = "Test Master Data To Delete"
		if not frappe.db.exists("Product Area", name):
			frappe.get_doc({"doctype": "Product Area", "area_name": name}).insert(ignore_permissions=True)

		frappe.set_user(all_three)
		try:
			delete_master_data(key="product_area", name=name)
		finally:
			frappe.set_user("Administrator")

		self.assertFalse(frappe.db.exists("Product Area", name))

	def test_delete_master_data_refuses_an_entry_still_in_use(self) -> None:
		"""disable exists for exactly this case - a real delete has to refuse rather than
		leave an existing Request's product_area pointing at nothing."""
		all_three = self._make_user("delete-masterdata-in-use@example.test", ALL_THREE)
		name = "Test Master Data In Use Area"
		if not frappe.db.exists("Product Area", name):
			frappe.get_doc({"doctype": "Product Area", "area_name": name}).insert(ignore_permissions=True)

		frappe.set_user(all_three)
		try:
			request = frappe.get_doc(
				{"doctype": "Request", "title": "Keeps this area in use", "product_area": name}
			)
			request.flags.ignore_recursion_check = True
			request.insert(ignore_permissions=True)
			with self.assertRaises(frappe.LinkExistsError):
				delete_master_data(key="product_area", name=name)
		finally:
			frappe.set_user("Administrator")
		self.assertTrue(frappe.db.exists("Product Area", name))

	def test_delete_master_data_denies_a_solo_role_caller(self) -> None:
		dev = self._make_user("delete-masterdata-denied@example.test", ["Projects Manager"])
		name = "Test Master Data Delete Denied"
		if not frappe.db.exists("Product Area", name):
			frappe.get_doc({"doctype": "Product Area", "area_name": name}).insert(ignore_permissions=True)
		frappe.set_user(dev)
		try:
			with self.assertRaises(frappe.PermissionError):
				delete_master_data(key="product_area", name=name)
		finally:
			frappe.set_user("Administrator")
		self.assertTrue(frappe.db.exists("Product Area", name))
