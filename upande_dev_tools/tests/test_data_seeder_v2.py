# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt
"""Data Seeder: end-to-end tests against a LOCAL MOCK of a Frappe remote. No real site is touched.

A tiny http.server on 127.0.0.1 (random free port) answers /?cmd=login, /api/method/... and
/api/resource/Note the way FrappeClient expects. The real code in api/seeder.py and
api/v2/data_seeder.py runs in-process on the local site INSIDE ONE TRANSACTION:
  * frappe.db.commit is replaced by a no-op and frappe.db.rollback by "rollback to savepoint"
    (the worker commits and rolls back for real, which would otherwise end the test transaction),
  * frappe.enqueue is captured (no worker runs),
  * tearDown rolls everything back and asserts the row counts of every table touched are unchanged.
The only DocType seeded is Note (two rows exist locally; only counts are read).

Run (from /home/jk/Projects/upande-local-bench-v16/sites):
  ../env/bin/python -m upande_dev_tools.tests.test_data_seeder_v2
"""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock
from urllib.parse import parse_qs, urlparse

import frappe

SECRET = "SUPERSECRETVALUE-xyz"
KEY = "AKEYVALUE12345"
PASSWORD = "p@ssw0rd-TOPSECRET"
GOOD_USER = "seed@mock.test"
TABLES = ("Note", "Note Seen By", "Seed Job", "Seed Job DocType", "Seed Job Log")

NOTES = [
	{"name": f"mock-note-{i}", "title": f"Mock {i}", "public": 1, "content": "x",
	 "owner": "Administrator", "modified_by": "Administrator", "docstatus": 0, "idx": 0,
	 "creation": "2020-01-01 00:00:00", "modified": "2020-01-01 00:00:00"}
	for i in range(1, 6)
]
NOTES[2]["seen_by"] = [{"name": "mock-seen-1", "user": "Administrator", "creation": "2020-01-01 00:00:00",
	"modified": "2020-01-01 00:00:00", "owner": "Administrator", "modified_by": "Administrator"}]

MOCK = {"fail_resource": False, "requests": []}


class Handler(BaseHTTPRequestHandler):
	def log_message(self, *a):
		pass

	def _send(self, code, body):
		raw = json.dumps(body).encode()
		self.send_response(code)
		self.send_header("Content-Type", "application/json")
		self.send_header("Content-Length", str(len(raw)))
		self.end_headers()
		self.wfile.write(raw)

	def _authed(self, q):
		import base64
		h = self.headers.get("Authorization", "")
		if h == "Basic " + base64.b64encode(f"{KEY}:{SECRET}".encode()).decode():
			return True
		return "sid=mock" in (self.headers.get("Cookie") or "")

	def do_POST(self):
		self.do_GET()

	def do_GET(self):
		u = urlparse(self.path)
		q = {k: v[0] for k, v in parse_qs(u.query).items()}
		MOCK["requests"].append(self.path)
		if q.get("cmd") == "login":
			if q.get("usr") == GOOD_USER and q.get("pwd") == PASSWORD:
				self.send_response(200)
				self.send_header("Set-Cookie", "sid=mock; Path=/")
				body = json.dumps({"message": "Logged In"}).encode()
				self.send_header("Content-Type", "application/json")
				self.send_header("Content-Length", str(len(body)))
				self.end_headers()
				self.wfile.write(body)
				return
			return self._send(401, {"exc_type": "AuthenticationError", "message": "Incorrect password"})
		if q.get("cmd") == "logout":
			return self._send(200, {"message": "ok"})
		if not self._authed(q):
			return self._send(401, {"exc_type": "AuthenticationError", "exception": "frappe.exceptions.AuthenticationError"})
		if u.path == "/api/method/frappe.auth.get_logged_user":
			return self._send(200, {"message": "seed@mock.test"})
		if u.path == "/api/method/frappe.client.get_count":
			return self._send(200, {"message": len(NOTES)})
		if u.path == "/api/resource/Note":
			if MOCK["fail_resource"]:
				return self._send(403, {"exc_type": "PermissionError", "exception": f"leaked {SECRET} here"})
			rows = sorted(NOTES, key=lambda r: r["name"])
			for f in json.loads(q.get("filters") or "[]"):
				if f[0] == "name" and f[1] == ">":
					rows = [r for r in rows if r["name"] > f[2]]
			rows = rows[: int(q.get("limit_page_length") or 20)]
			return self._send(200, {"data": rows})
		return self._send(404, {"exc_type": "DoesNotExistError"})


def _counts():
	return {t: frappe.db.count(t) for t in TABLES}


class Crash(BaseException):
	"""Simulates the worker process dying (not an Exception, so the seeder cannot catch it)."""


class TestSeederEndToEnd(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		if not getattr(frappe.local, "site", None):
			raise unittest.SkipTest("needs a connected site")
		cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
		cls.port = cls.server.server_address[1]
		threading.Thread(target=cls.server.serve_forever, daemon=True).start()
		cls.url = f"http://127.0.0.1:{cls.port}"

	@classmethod
	def tearDownClass(cls):
		if getattr(cls, "server", None):
			cls.server.shutdown()

	def setUp(self):
		from upande_dev_tools.api import seeder

		self.seeder = seeder
		frappe.set_user("Administrator")
		frappe.db.rollback()
		self.before = _counts()
		MOCK["fail_resource"] = False
		MOCK["requests"].clear()
		self.enqueued = []
		self.real_commit, self.real_rollback, self.real_enqueue = frappe.db.commit, frappe.db.rollback, frappe.enqueue
		frappe.db.commit = lambda *a, **k: None
		frappe.enqueue = lambda *a, **k: self.enqueued.append((a, k))
		self.job = self.make_job()
		frappe.db.sql("savepoint seedtest")
		frappe.db.rollback = lambda *a, **k: frappe.db.sql("rollback to savepoint seedtest")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback = self.real_rollback
		frappe.db.commit = self.real_commit
		frappe.enqueue = self.real_enqueue
		frappe.db.rollback()
		self.assertEqual(_counts(), self.before, "the test left rows behind")

	def make_job(self, **kw):
		d = {
			"doctype": "Seed Job", "source_url": self.url, "auth_type": "API Key", "api_key": KEY,
			"api_secret": SECRET, "page_size": 2, "doctypes": [{"doctype_name": "Note"}],
		}
		d.update(kw)
		return frappe.get_doc(d).insert(ignore_permissions=True).name

	def row(self):
		return frappe.get_all("Seed Job DocType", {"parent": self.job}, ["*"])[0]

	def status(self):
		return frappe.db.get_value("Seed Job", self.job, "status")

	def mock_notes(self):
		return frappe.db.count("Note", {"name": ["like", "mock-note-%"]})

	# -- happy path, pagination, idempotency ------------------------------------------------
	def test_full_run_paginates_and_is_idempotent(self):
		self.seeder.start_seed_job(self.job)
		self.assertEqual(len(self.enqueued), 1)
		self.assertEqual(self.status(), "Queued")
		self.seeder.run_seed_job(self.job)
		r = self.row()
		self.assertEqual((self.status(), r.status, r.rows_imported, r.current_page, r.last_cursor),
			("Completed", "Completed", 5, 3, "mock-note-5"))
		self.assertEqual(self.mock_notes(), 5)
		self.assertEqual(frappe.db.count("Note Seen By", {"parent": "mock-note-3"}), 1)
		# re-run from the start: INSERT IGNORE means no duplicates and no error
		frappe.db.set_value("Seed Job DocType", r.name, {"status": "Pending", "last_cursor": "", "current_page": 0, "rows_imported": 0})
		frappe.db.set_value("Seed Job", self.job, "status", "Draft")
		self.seeder.run_seed_job(self.job)
		self.assertEqual((self.status(), self.mock_notes()), ("Completed", 5))
		self.assertEqual(frappe.db.count("Note Seen By", {"parent": "mock-note-3"}), 1)

	# -- crash and resume -------------------------------------------------------------------
	def test_crash_after_first_page_resumes_with_no_gap_or_duplicate(self):
		from frappe.frappeclient import FrappeClient

		real = FrappeClient.get_list
		calls = []

		def crashing(client, *a, **k):
			calls.append(1)
			if len(calls) == 2:
				raise Crash()
			return real(client, *a, **k)

		with mock.patch.object(FrappeClient, "get_list", crashing):
			with self.assertRaises(Crash):
				self.seeder.run_seed_job(self.job)
		r = self.row()
		self.assertEqual((r.last_cursor, r.rows_imported, self.mock_notes()), ("mock-note-2", 2, 2))
		self.assertEqual(self.status(), "Running")  # stuck: nothing is alive
		with self.assertRaises(frappe.ValidationError):
			self.seeder.start_seed_job(self.job)  # refused while "Running"
		self.seeder.pause_seed_job(self.job)  # the recovery path the page offers
		self.seeder.resume_seed_job(self.job)
		self.seeder.run_seed_job(self.job)
		self.assertEqual((self.status(), self.row().rows_imported, self.mock_notes()), ("Completed", 5, 5))
		names = frappe.get_all("Note", {"name": ["like", "mock-note-%"]}, pluck="name")
		self.assertEqual(sorted(names), sorted(set(names)))

	# -- failing doctype --------------------------------------------------------------------
	def test_failing_doctype_is_plain_language_then_retry_works(self):
		MOCK["fail_resource"] = True
		self.seeder.run_seed_job(self.job)
		r = self.row()
		self.assertEqual((self.status(), r.status, r.error_count), ("Failed", "Failed", 1))
		self.assertIn("refused the request", r.last_error)
		self.assertNotIn(SECRET, r.last_error)
		self.assertNotEqual(r.last_error.strip(), "None")
		MOCK["fail_resource"] = False
		self.seeder.retry_doctype(self.job, r.name)
		self.seeder.run_seed_job(self.job)
		self.assertEqual((self.status(), self.mock_notes()), ("Completed", 5))

	# -- cancel -----------------------------------------------------------------------------
	def test_cancel_stops_after_the_page_and_start_continues(self):
		from frappe.frappeclient import FrappeClient

		real = FrappeClient.get_list
		n = []

		def cancelling(client, *a, **k):
			out = real(client, *a, **k)
			n.append(1)
			if len(n) == 1:
				self.seeder.cancel_seed_job(self.job)
			return out

		with mock.patch.object(FrappeClient, "get_list", cancelling):
			self.seeder.run_seed_job(self.job)
		self.assertEqual((self.status(), self.row().status, self.mock_notes()), ("Cancelled", "Paused", 2))
		self.seeder.start_seed_job(self.job)
		self.seeder.run_seed_job(self.job)
		self.assertEqual((self.status(), self.mock_notes()), ("Completed", 5))

	# -- bad credentials / unreachable ------------------------------------------------------
	def test_bad_password_and_bad_key_give_a_reason(self):
		from upande_dev_tools.api.v2 import data_seeder as ds

		bad = self.make_job(auth_type="Password", source_user=GOOD_USER, source_password="wrong-pw-123")
		self.seeder.run_seed_job(bad)
		err = frappe.db.get_value("Seed Job", bad, "last_error")
		self.assertEqual(frappe.db.get_value("Seed Job", bad, "status"), "Failed")
		self.assertIn("refused the login", err)
		self.assertNotIn("wrong-pw-123", err)
		r = ds.test_connection(bad)
		self.assertFalse(r["success"])
		self.assertIn("refused the login", r["error"])
		badkey = self.make_job(api_secret="not-the-secret")
		r = ds.test_connection(badkey)
		self.assertFalse(r["success"])
		self.assertIn("refused", r["error"])

	def test_good_password_login_and_test_connection(self):
		from upande_dev_tools.api.v2 import data_seeder as ds

		ok = self.make_job(auth_type="Password", source_user=GOOD_USER, source_password=PASSWORD)
		r = ds.test_connection(ok)
		self.assertTrue(r["success"])
		self.assertEqual(r["user"], "seed@mock.test")
		self.assertTrue(any("cmd=logout" in p for p in MOCK["requests"]))

	def test_unreachable_remote_is_a_clear_error(self):
		from upande_dev_tools.api.v2 import data_seeder as ds

		dead = self.make_job(source_url="http://127.0.0.1:1")
		r = ds.test_connection(dead)
		self.assertFalse(r["success"])
		self.assertIn("Could not connect", r["error"])
		self.seeder.run_seed_job(dead)
		self.assertIn("Could not connect", frappe.db.get_value("Seed Job DocType", {"parent": dead}, "last_error") or frappe.db.get_value("Seed Job", dead, "last_error"))

	# -- state guards -----------------------------------------------------------------------
	def test_state_guards(self):
		self.seeder.run_seed_job(self.job)  # Completed
		for fn in (self.seeder.pause_seed_job, self.seeder.cancel_seed_job, self.seeder.resume_seed_job):
			with self.assertRaises(frappe.ValidationError):
				fn(self.job)
		self.assertEqual(self.status(), "Completed")
		other = self.make_job()
		with self.assertRaises(frappe.ValidationError):
			self.seeder.retry_doctype(self.job, frappe.get_all("Seed Job DocType", {"parent": other}, pluck="name")[0])
		self.seeder.start_seed_job(other)
		with self.assertRaises(frappe.ValidationError):
			self.seeder.start_seed_job(other)  # already Queued
		with self.assertRaises(frappe.DoesNotExistError):
			self.seeder.pause_seed_job("SJ-NOPE")

	def test_columns_exist_in_the_table_and_children_carry_their_parent(self):
		cols = self.seeder._columns_for("Note Seen By")
		self.assertTrue({"parent", "parenttype", "parentfield"} <= set(cols))
		for dt in ("Note", "Note Seen By", "Sales Order"):
			self.assertLessEqual(set(self.seeder._columns_for(dt)), set(frappe.db.get_table_columns(dt)))

	def test_a_job_with_no_password_does_not_raise_a_dialog(self):
		from upande_dev_tools.api.v2 import data_seeder as ds

		frappe.local.message_log = []
		ds.get_job(self.job)
		self.assertEqual(frappe.local.message_log, [])

	def test_keyset_ignores_custom_order_by(self):
		frappe.db.set_value("Seed Job DocType", self.row().name, "order_by", "creation desc")
		self.seeder.run_seed_job(self.job)
		self.assertEqual((self.status(), self.mock_notes()), ("Completed", 5))
		self.assertTrue(any("Order By" in m for m in frappe.get_all("Seed Job Log", {"seed_job": self.job, "level": "Warning"}, pluck="message")))

	# -- secrets ----------------------------------------------------------------------------
	def test_secrets_never_leave_the_server(self):
		from upande_dev_tools.api.v2 import data_seeder as ds

		MOCK["fail_resource"] = True  # the mock echoes SECRET inside its error body
		self.seeder.run_seed_job(self.job)
		pw = self.make_job(auth_type="Password", source_user=GOOD_USER, source_password=PASSWORD)
		blobs = []
		for name in (self.job, pw):
			blobs += [ds.get_job(name), ds.get_progress(name), ds.test_connection(name), self.seeder.get_progress(name)]
		blobs.append(ds.get_overview())
		text = json.dumps(blobs, default=str)
		for s in (SECRET, KEY, PASSWORD):
			self.assertNotIn(s, text)
		for t in ("Seed Job Log",):
			self.assertNotIn(SECRET, json.dumps(frappe.get_all(t, fields=["message"]), default=str))
		cfg = ds.get_job(self.job)["config"]
		self.assertEqual((cfg["api_key_set"], cfg["api_secret_set"]), (True, True))
		self.assertTrue(ds.get_job(pw)["config"]["password_set"])
		e = Exception(f"boom {SECRET} https://user:pw@host/x")
		msg = self.seeder.friendly_error(e, frappe.get_doc("Seed Job", self.job))
		self.assertNotIn(SECRET, msg)
		self.assertNotIn("user:pw@", msg)

	# -- permissions ------------------------------------------------------------------------
	def _users(self):
		sm = frappe.get_all("Has Role", {"role": "System Manager", "parenttype": "User"}, pluck="parent")
		sm = [u for u in sm if u != "Administrator" and frappe.db.get_value("User", u, "enabled")]
		anyone = frappe.get_all("User", {"enabled": 1, "name": ["not in", ["Administrator", "Guest", *sm]]}, pluck="name", limit=20)
		return sm, anyone

	def test_permissions_follow_the_page_rule(self):
		from upande_dev_tools.api.v2 import data_seeder as ds

		sm, others = self._users()
		self.assertTrue(sm and others, "need local users with and without System Manager")
		deny = [lambda: ds.get_overview(), lambda: ds.get_job(self.job), lambda: ds.get_progress(self.job),
			lambda: ds.test_connection(self.job), lambda: self.seeder.start_seed_job(self.job),
			lambda: self.seeder.pause_seed_job(self.job), lambda: self.seeder.cancel_seed_job(self.job),
			lambda: self.seeder.resume_seed_job(self.job), lambda: self.seeder.dry_run(self.job),
			lambda: self.seeder.test_connection(self.job), lambda: self.seeder.get_progress(self.job),
			lambda: self.seeder.retry_doctype(self.job, self.row().name)]
		for user in others[:3]:
			roles = set(frappe.get_roles(user))
			if "System Manager" in roles:
				continue
			frappe.set_user(user)
			for call in deny:
				with self.assertRaises(frappe.PermissionError, msg=user):
					call()
		frappe.set_user(sm[0])
		self.assertTrue(ds.get_overview()["jobs"])
		self.assertEqual(ds.get_job(self.job)["job"]["name"], self.job)
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			ds.get_overview()
		self.assertEqual(self.enqueued, [])  # nothing denied ever queued work

	def test_page_rule_follows_the_dev_portal_page_row(self):
		_sm, others = self._users()
		role = "Dev Team"
		dev = [u for u in others if role in frappe.get_roles(u) and "System Manager" not in frappe.get_roles(u)]
		if not dev:
			self.skipTest("no Dev Team-only user locally")
		frappe.db.set_value("Has Role", {"parent": "dev-data-seeder", "parenttype": "Dev Portal Page"}, "role", role)
		frappe.set_user(dev[0])
		self.assertEqual(self.seeder.get_progress(self.job)["job"]["status"], "Draft")

	# -- v2 read shapes ---------------------------------------------------------------------
	def test_v2_reads_describe_state_in_plain_language(self):
		from upande_dev_tools.api.v2 import data_seeder as ds

		d = ds.get_job(self.job)
		self.assertEqual(d["doctypes"][0]["state"], "waiting")
		self.assertIsNone(d["job"]["remaining_max"])  # not counted yet
		self.assertTrue(d["job"]["idle"])
		self.assertTrue(any("not counted" in c["text"] for c in d["preflight"]))
		self.seeder.run_seed_job(self.job)
		d = ds.get_progress(self.job, level="Info")
		self.assertEqual((d["doctypes"][0]["state"], d["job"]["doctypes_done"]), ("done", 1))
		self.assertTrue(d["log"]["rows"] and all(r["level"] == "Info" for r in d["log"]["rows"]))
		self.assertEqual(ds.get_progress(self.job, q="zzz-nothing")["log"]["total"], 0)
		frappe.db.set_value("Seed Job DocType", self.row().name, "status", "Running")
		frappe.db.set_value("Seed Job", self.job, "status", "Failed")
		self.assertEqual(ds.get_progress(self.job)["doctypes"][0]["state"], "interrupted")

	def test_stale_running_job_is_flagged_and_polling_flag_stops_when_idle(self):
		from upande_dev_tools.api.v2 import data_seeder as ds

		frappe.db.set_value("Seed Job", self.job, {"status": "Running", "last_heartbeat": "2020-01-01 00:00:00"})
		j = ds.get_progress(self.job)["job"]
		self.assertTrue(j["stale"])
		self.assertFalse(j["idle"])
		frappe.db.set_value("Seed Job", self.job, "status", "Paused")
		self.assertTrue(ds.get_progress(self.job)["job"]["idle"])

	def test_preflight_catches_bad_configuration(self):
		from upande_dev_tools.api.v2 import data_seeder as ds

		bad = self.make_job(source_url="ftp://x", doctypes=[{"doctype_name": "Note"}, {"doctype_name": "Note Seen By"}, {"doctype_name": "User"}])
		texts = " | ".join(c["text"] for c in ds.get_job(bad)["preflight"])
		self.assertIn("http://", texts)
		self.assertIn("child tables cannot be seeded", texts)
		self.assertIn("who can sign in", texts)
		self.assertIn("listed more than once", " | ".join(c["text"] for c in ds.get_job(self.make_job(doctypes=[{"doctype_name": "Note"}, {"doctype_name": "Note"}]))["preflight"]))
		start = ds.get_job(bad)["config"]
		self.assertNotIn("api_secret", start)


def run():
	import sys

	suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
	res = unittest.TextTestRunner(verbosity=2).run(suite)
	return res.wasSuccessful()


if __name__ == "__main__":
	frappe.init(site="kaitet.local", sites_path=".")
	frappe.connect()
	try:
		ok = run()
	finally:
		frappe.destroy()
	raise SystemExit(0 if ok else 1)
