# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from upande_dev_tools.api.master_data import (
	add_master_data,
	get_master_data,
	get_master_data_kinds,
	set_master_data_disabled,
)


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

	def test_get_master_data_kinds_lists_all_kinds(self) -> None:
		pm = self._make_user("pm-masterdata@example.test", ["Projects Manager"])
		frappe.set_user(pm)
		try:
			kinds = get_master_data_kinds()
		finally:
			frappe.set_user("Administrator")
		self.assertEqual({k["key"] for k in kinds}, {"request_type", "priority_level", "product_area", "tag"})

	def test_add_and_list_a_product_area(self) -> None:
		dev = self._make_user("dev-masterdata@example.test", ["Dev Team"])
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
		dev = self._make_user("dev-masterdata-dup@example.test", ["Dev Team"])
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
		dev = self._make_user("dev-masterdata-badkind@example.test", ["Dev Team"])
		frappe.set_user(dev)
		try:
			with self.assertRaises(frappe.ValidationError):
				add_master_data(key="task_status", value="Whatever")
		finally:
			frappe.set_user("Administrator")

	def test_set_master_data_disabled_toggles_the_flag(self) -> None:
		dev = self._make_user("dev-masterdata-disable@example.test", ["Dev Team"])
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
		dev = self._make_user("dev-masterdata-sort@example.test", ["Dev Team"])
		name = "Test Master Data Priority Level"
		if frappe.db.exists("Priority Level", name):
			frappe.delete_doc("Priority Level", name, force=True)

		frappe.set_user(dev)
		try:
			add_master_data(key="priority_level", value=name, sort_order=7)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(frappe.db.get_value("Priority Level", name, "sort_order"), 7)
