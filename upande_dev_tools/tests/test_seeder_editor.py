# Copyright (c) 2026, Upande LTD and contributors
"""Seed Job editor endpoints (create / edit / duplicate / delete). Runs on the local site inside one
transaction that is rolled back; frappe.db.commit is a no-op. Nothing is enqueued or sent anywhere.

Run (from sites/): ../env/bin/python -m upande_dev_tools.tests.test_seeder_editor
"""
import json
import unittest
from unittest import mock

import frappe

from upande_dev_tools.api import seeder

DATA = {
	"source_url": "https://example.invalid", "auth_type": "API Key", "api_key": "K1", "api_secret": "S3CRET",
	"page_size": 200, "ignore_permissions": 1, "ignore_links": 1, "ignore_mandatory": 1,
	"anonymise_fields": '{"email_id": "***"}',
	"doctypes": [
		{"doctype_name": "Note", "filters": "[]", "fields": '["*"]', "include_children": 1, "order_by": "name asc"},
		{"doctype_name": "ToDo", "filters": '[["ToDo","status","=","Open"]]', "fields": "", "include_children": 0, "order_by": "modified desc"},
	],
}


class T(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.init(site="kaitet.local", sites_path=".")
		frappe.connect()
		frappe.set_user("Administrator")

	def setUp(self):
		frappe.db.savepoint("t")
		self.p = mock.patch.object(frappe.db, "commit", lambda *a, **k: None)
		self.p.start()

	def tearDown(self):
		self.p.stop()
		frappe.db.rollback(save_point="t")

	def test_create_edit_duplicate_delete(self):
		r = seeder.save_seed_job(json.dumps(DATA))
		n = r["name"]
		f = seeder.get_job_form(n)
		self.assertTrue(f["api_secret_set"])
		self.assertNotIn("S3CRET", json.dumps(f))
		self.assertEqual([d["doctype_name"] for d in f["doctypes"]], ["Note", "ToDo"])
		self.assertEqual(f["doctypes"][1]["fields"], '["*"]')
		# edit with blank secret keeps it; reorder + remove
		d2 = dict(DATA, api_secret="", page_size=300, doctypes=[dict(f["doctypes"][1])])
		seeder.save_seed_job(json.dumps(d2), n)
		job = frappe.get_doc("Seed Job", n)
		self.assertEqual(job.get_password("api_secret"), "S3CRET")
		self.assertEqual((job.page_size, len(job.doctypes)), (300, 1))
		c = seeder.duplicate_seed_job(n)["name"]
		self.assertNotEqual(c, n)
		self.assertEqual(frappe.get_doc("Seed Job", c).get_password("api_secret"), "S3CRET")
		seeder.delete_seed_job(c)
		self.assertFalse(frappe.db.exists("Seed Job", c))

	def test_validation_and_lock(self):
		for bad in (dict(DATA, source_url="ftp://x"), dict(DATA, page_size=1), dict(DATA, anonymise_fields="[1]"),
				dict(DATA, doctypes=[]), dict(DATA, doctypes=[{"doctype_name": "Nope Nope"}]),
				dict(DATA, doctypes=[DATA["doctypes"][0], DATA["doctypes"][0]]),
				dict(DATA, doctypes=[dict(DATA["doctypes"][0], order_by="name; drop table")]),
				dict(DATA, doctypes=[dict(DATA["doctypes"][0], filters="{}")])):
			with self.assertRaises(frappe.ValidationError, msg=str(bad)[:80]):
				seeder.save_seed_job(json.dumps(bad))
		n = seeder.save_seed_job(json.dumps(DATA))["name"]
		frappe.db.set_value("Seed Job", n, "status", "Running")
		with self.assertRaises(frappe.ValidationError):
			seeder.save_seed_job(json.dumps(DATA), n)
		with self.assertRaises(frappe.ValidationError):
			seeder.delete_seed_job(n)

	def test_access(self):
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				seeder.save_seed_job(json.dumps(DATA))
		finally:
			frappe.set_user("Administrator")

	def test_filter_builder_payloads(self):
		fields = {f["fieldname"] for f in seeder.get_doctype_fields("ToDo")}
		self.assertTrue({"status", "name", "modified", "description"} <= fields)
		self.assertNotIn("Section Break", {f["fieldtype"] for f in seeder.get_doctype_fields("ToDo")})
		good = [["ToDo", "status", "!=", "Closed"], ["ToDo", "description", "not like", "%x%"],
			["ToDo", "status", "in", ["Open", "Closed"]], ["ToDo", "status", "not in", ["Open"]],
			["ToDo", "date", "between", ["2026-01-01", "2026-02-01"]], ["ToDo", "reference_name", "is", "set"]]
		d = dict(DATA, doctypes=[dict(DATA["doctypes"][1], filters=json.dumps(good))])
		n = seeder.save_seed_job(json.dumps(d))["name"]
		self.assertEqual(json.loads(seeder.get_job_form(n)["doctypes"][0]["filters"]), good)
		for bad in ([["ToDo", "nope_field", "=", 1]], [["ToDo", "status", "regexp", "x"]], [["x"]]):
			with self.assertRaises(frappe.ValidationError, msg=str(bad)):
				seeder.save_seed_job(json.dumps(dict(d, doctypes=[dict(d["doctypes"][0], filters=json.dumps(bad))])))
		with self.assertRaises(frappe.ValidationError):
			seeder.get_doctype_fields("Not A Doctype")

	def test_saved_sites(self):
		# add a new site from the form: saved on a Deployment Instance, job linked, sign-in reusable
		d = dict(DATA, new_site={"name": "ZZ Test Site", "environment": "Staging"})
		n1 = seeder.save_seed_job(json.dumps(d))["name"]
		self.assertEqual(frappe.db.get_value("Seed Job", n1, "instance"), "ZZ Test Site")
		inst = frappe.get_doc("Deployment Instance", "ZZ Test Site")
		self.assertEqual((inst.environment_type, inst.site_url, inst.seeder_api_key), ("Staging", DATA["source_url"], "K1"))
		self.assertEqual(inst.get_password("seeder_api_secret"), "S3CRET")
		site = [s for s in seeder.list_sites() if s["name"] == "ZZ Test Site"][0]
		self.assertTrue(site["has_signin"])
		self.assertNotIn("S3CRET", json.dumps(site))
		# a second job picks the existing site with no sign-in typed: it inherits it
		d2 = dict(DATA, instance="ZZ Test Site", api_key="", api_secret="", source_url="https://ignored.invalid")
		n2 = seeder.save_seed_job(json.dumps(d2))["name"]
		j2 = frappe.get_doc("Seed Job", n2)
		self.assertEqual((j2.instance, j2.source_url, j2.api_key, j2.get_password("api_secret")), ("ZZ Test Site", DATA["source_url"], "K1", "S3CRET"))
		self.assertEqual(seeder.get_job_form(n2)["instance"], "ZZ Test Site")
		# different sign-in for one job does not change the site unless asked
		d3 = dict(d2, api_key="K2", api_secret="OTHER")
		n3 = seeder.save_seed_job(json.dumps(d3))["name"]
		self.assertEqual(frappe.get_doc("Seed Job", n3).get_password("api_secret"), "OTHER")
		self.assertEqual(frappe.get_doc("Deployment Instance", "ZZ Test Site").get_password("seeder_api_secret"), "S3CRET")
		seeder.save_seed_job(json.dumps(dict(d3, update_site=1)), n3)
		self.assertEqual(frappe.get_doc("Deployment Instance", "ZZ Test Site").seeder_api_key, "K2")
		with self.assertRaises(frappe.ValidationError):
			seeder.save_seed_job(json.dumps(d))  # same new-site name again
		self.assertEqual(frappe.db.get_value("Seed Job", seeder.duplicate_seed_job(n2)["name"], "instance"), "ZZ Test Site")

	def _fake_client(self):
		calls = []

		class C:
			def get_list(_, doctype, fields=None, filters=None, order_by=None, limit_page_length=None):
				names = ["zz-kid-1", "zz-kid-2"]
				after = [f for f in filters if f[0] == "name"]
				return [] if after else [{"name": n, "title": n, "public": 0, "content": "x", "creation": "2020-01-01", "modified": "2020-01-01"} for n in names]

			def get_api(_, method, params=None):
				calls.append((method, params))
				parents = json.loads(params["filters"])[0][2]
				return [{"name": f"c-{p}", "parent": p, "user": "Administrator", "idx": 1} for p in parents if p != "zz-kid-2"]

		return C(), calls

	def _note_job(self):
		d = dict(DATA, doctypes=[dict(DATA["doctypes"][0], doctype_name="Note")])
		return seeder.save_seed_job(json.dumps(d))["name"]

	def test_new_job_fetches_child_tables(self):
		n = self._note_job()
		client, calls = self._fake_client()
		job = frappe.get_doc("Seed Job", n)
		with mock.patch.object(seeder, "_is_stopped", lambda *_: False):
			self.assertTrue(seeder._import_doctype(job, job.doctypes[0], client))
		self.assertEqual(frappe.db.count("Note", {"name": ["like", "zz-kid-%"]}), 2)
		kids = frappe.db.get_all("Note Seen By", filters={"parent": ["like", "zz-kid-%"]}, fields=["parent", "parentfield", "parenttype", "idx"])
		self.assertEqual([(k.parent, k.parentfield, k.parenttype) for k in kids], [("zz-kid-1", "seen_by", "Note")])
		self.assertEqual(calls[0][1]["parent"], "Note")

	def test_populate_children_for_existing_parents(self):
		n = self._note_job()
		client, calls = self._fake_client()
		for nm in ("zz-kid-1", "zz-kid-2"):
			frappe.db.sql("insert into `tabNote` (name, title, creation, modified) values (%s, %s, now(), now())", (nm, nm))
		with mock.patch.object(seeder, "_client", lambda *_: client), mock.patch.object(seeder, "_is_stopped", lambda *_: False), \
				mock.patch.object(frappe, "enqueue", lambda *a, **k: None):
			seeder.populate_children(n)
			self.assertEqual(frappe.db.get_value("Seed Job", n, "status"), "Queued")
			frappe.db.set_value("Seed Job", n, "status", "Completed")
			seeder.run_populate_children(n, None, "Completed")
			first = len(calls)
			seeder.run_populate_children(n, None, "Completed")
		self.assertEqual(frappe.db.count("Note Seen By", {"parent": "zz-kid-1"}), 1)
		self.assertEqual(frappe.db.get_value("Seed Job", n, "status"), "Completed")
		self.assertTrue(frappe.db.exists("Seed Job Log", {"seed_job": n, "message": ["like", "Child tables filled%"]}))
		self.assertGreaterEqual(len(calls), first)  # zz-kid-1 is skipped the second time, zz-kid-2 still has none

	def test_search(self):
		self.assertIn("Note", seeder.search_doctypes("Note"))


if __name__ == "__main__":
	unittest.main()
