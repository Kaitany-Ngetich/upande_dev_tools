# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.model.document import Document
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate, today

from upande_dev_tools.api import duty

PM = "duty-pm@example.test"
ANN = "duty-ann@example.test"
BEN = "duty-ben@example.test"
CAT = "duty-cat@example.test"
OUTSIDER = "duty-outsider@example.test"
TYPE = "Test Duty"
OTHER_TYPE = "Other Test Duty"


def _day(offset: int) -> str:
	return str(add_days(getdate(today()), offset))


class DutyTestBase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		for email, first, roles in (
			(PM, "Pam", ["Projects Manager", "Dev Team"]),
			(ANN, "Ann", ["Dev Team"]),
			(BEN, "Ben", ["Dev Team"]),
			(CAT, "Cat", ["Dev Team"]),
			(OUTSIDER, "Otto", []),
		):
			if not frappe.db.exists("User", email):
				frappe.get_doc(
					{"doctype": "User", "email": email, "first_name": first, "send_welcome_email": 0}
				).insert(ignore_permissions=True)
			if roles:
				frappe.get_doc("User", email).add_roles(*roles)
		for name in (TYPE, OTHER_TYPE):
			if not frappe.db.exists("Duty Type", name):
				frappe.get_doc({"doctype": "Duty Type", "duty_name": name, "people_per_slot": 2}).insert(
					ignore_permissions=True
				)

	def setUp(self) -> None:
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		# Notifications go to the real outbox (rows in this transaction); nothing ever reaches Expo.
		if "upande_mobile" in frappe.get_installed_apps():
			from upande_mobile import push

			for target in ("enabled", "http_post"):
				p = patch.object(push, target, return_value=True)
				p.start()
				self.addCleanup(p.stop)

	@contextmanager
	def as_user(self, user: str):
		frappe.set_user(user)
		try:
			yield
		finally:
			frappe.set_user("Administrator")

	def slot(self, people, start=10, end=16, duty_type=TYPE, label="") -> dict:
		with self.as_user(PM):
			return duty.save_slot(
				{
					"duty_type": duty_type,
					"label": label,
					"start_date": _day(start),
					"end_date": _day(end),
					"notes": "",
					"assignees": list(people),
				}
			)

	def people_on(self, name: str) -> list[str]:
		return [a.user for a in frappe.get_doc("Duty Rota Slot", name).assignees]

	def notes(self, key_like: str) -> list:
		if "upande_mobile" not in frappe.get_installed_apps():
			self.skipTest("upande_mobile is not installed")
		return frappe.get_all(
			"Mobile Notification",
			filters={"dedupe_key": ["like", key_like]},
			fields=["user", "title", "kind", "route", "dedupe_key"],
			order_by="creation asc",
		)


class IntegrationTestDutyRead(DutyTestBase):
	def test_only_readers_get_in(self) -> None:
		with self.as_user(OUTSIDER):
			for call in (
				duty.duty_types,
				lambda: duty.rota(TYPE),
				duty.change_requests,
				duty.people,
				lambda: duty.request_change("x", "Replace", ANN),
			):
				with self.assertRaises(frappe.PermissionError):
					call()

	def test_rota_shape_window_and_order(self) -> None:
		late = self.slot([ANN], start=20, end=20, label="late")
		early = self.slot([BEN, ANN], start=3, end=9, label="early")
		far = self.slot([CAT], start=400, end=401, label="far")
		with self.as_user(ANN):
			result = duty.rota(TYPE)
			self.assertEqual((result["duty_type"], result["me"], result["can_manage"]), (TYPE, ANN, False))
			names = [s["name"] for s in result["slots"]]
			self.assertLess(names.index(early["name"]), names.index(late["name"]))
			self.assertNotIn(far["name"], names)
			slot = next(s for s in result["slots"] if s["name"] == early["name"])
			self.assertEqual(set(slot), {"name", "duty_type", "label", "start_date", "end_date", "notes", "assignees"})
			self.assertEqual([a["user"] for a in slot["assignees"]], [BEN, ANN])
			self.assertEqual(slot["start_date"], _day(3))
			self.assertIn(far["name"], [s["name"] for s in duty.rota(TYPE, start=_day(390), end=_day(410))["slots"]])
			for bad in ("2026-02-30", "16/11/2026", "x"):
				with self.assertRaises(frappe.ValidationError):
					duty.rota(TYPE, start=bad)
			with self.assertRaises(frappe.ValidationError):
				duty.rota(TYPE, start=_day(10), end=_day(1))
			with self.assertRaises(frappe.ValidationError):
				duty.rota("No such duty")
		with self.as_user(PM):
			self.assertTrue(duty.rota(TYPE)["can_manage"])

	def test_duty_types_hide_inactive_and_people_are_the_dev_team(self) -> None:
		frappe.db.set_value("Duty Type", OTHER_TYPE, "is_active", 0)
		with self.as_user(ANN):
			names = [t["name"] for t in duty.duty_types()]
			self.assertIn(TYPE, names)
			self.assertNotIn(OTHER_TYPE, names)
			self.assertEqual(
				set(duty.duty_types()[0]),
				{"name", "duty_name", "description", "default_cadence", "people_per_slot", "is_active"},
			)
			users = [p["user"] for p in duty.people()]
			self.assertIn(ANN, users)
			self.assertNotIn(OUTSIDER, users)
			self.assertEqual([p["user"] for p in duty.people("ben")], [BEN])
		frappe.db.set_value("Duty Type", OTHER_TYPE, "is_active", 1)


class IntegrationTestDutySlots(DutyTestBase):
	def test_only_a_manager_edits_slots(self) -> None:
		existing = self.slot([ANN])
		with self.as_user(ANN):
			with self.assertRaises(frappe.PermissionError):
				duty.save_slot({"duty_type": TYPE, "start_date": _day(1), "end_date": _day(1), "assignees": []})
			with self.assertRaises(frappe.PermissionError):
				duty.delete_slot(existing["name"])

	def test_slot_validation(self) -> None:
		base = {"duty_type": TYPE, "label": "", "notes": "", "start_date": _day(1), "end_date": _day(2)}
		with self.as_user(PM):
			for bad in (
				dict(base, start_date="2026-02-30", assignees=[]),
				dict(base, start_date="tomorrow", assignees=[]),
				dict(base, start_date=_day(5), end_date=_day(4), assignees=[]),
				dict(base, assignees=[ANN, ANN]),
				dict(base, assignees=[OUTSIDER + "x"]),
				dict(base, assignees=["Administrator"]),
				dict(base, duty_type="No such duty", assignees=[]),
				dict(base, assignees="ann"),
			):
				with self.assertRaises(frappe.ValidationError, msg=bad):
					duty.save_slot(bad)
			with self.assertRaises(frappe.ValidationError):
				duty.save_slot("{not json")
			# The doctype holds the same rules for desk edits.
			with self.assertRaises(frappe.ValidationError):
				frappe.get_doc(
					{
						"doctype": "Duty Rota Slot",
						"duty_type": TYPE,
						"start_date": _day(3),
						"end_date": _day(2),
					}
				).insert()

	def test_overlapping_slots_are_allowed_with_a_warning(self) -> None:
		self.slot([ANN], start=30, end=36, label="week")
		frappe.local.message_log = []
		day = self.slot([BEN, CAT], start=31, end=31)
		self.assertTrue(frappe.db.exists("Duty Rota Slot", day["name"]))
		self.assertIn("overlaps", frappe.as_json(frappe.local.message_log))

	def test_a_daily_slot_starts_and_ends_on_one_day(self) -> None:
		slot = self.slot([ANN, BEN], start=40, end=40)
		self.assertEqual(slot["start_date"], slot["end_date"])

	def test_delete_refuses_while_a_request_is_pending(self) -> None:
		mine = self.slot([ANN, BEN])
		with self.as_user(ANN):
			req = duty.request_change(mine["name"], "Replace", CAT)
		with self.as_user(PM):
			with self.assertRaises(frappe.ValidationError):
				duty.delete_slot(mine["name"])
			duty.decide(req["name"], 0, "no")
			self.assertEqual(duty.delete_slot(mine["name"]), {"deleted": 1})
		self.assertFalse(frappe.db.exists("Duty Rota Slot", mine["name"]))
		# The decided request keeps its history.
		with self.as_user(PM):
			kept = next(r for r in duty.change_requests() if r["name"] == req["name"])
		self.assertEqual((kept["status"], kept["slot_label"]), ("Rejected", ""))


class IntegrationTestDutyRequests(DutyTestBase):
	def test_request_rules(self) -> None:
		mine = self.slot([ANN, BEN], start=10, end=16)
		theirs = self.slot([CAT], start=17, end=23)
		other_type = self.slot([CAT], start=17, end=23, duty_type=OTHER_TYPE)
		with self.as_user(ANN):
			for args, exc in (
				((mine["name"], "Replace", CAT, BEN), frappe.PermissionError),  # moving someone else out
				((mine["name"], "Replace", BEN), frappe.ValidationError),  # already on the slot
				((mine["name"], "Replace", ANN), frappe.ValidationError),  # yourself
				((mine["name"], "Replace", OUTSIDER + "x"), frappe.ValidationError),  # no such user
				((theirs["name"], "Replace", BEN), frappe.ValidationError),  # Ann is not on it
				((mine["name"], "Trade", CAT), frappe.ValidationError),
				((mine["name"], "Swap", CAT), frappe.ValidationError),  # no swap slot
				((mine["name"], "Swap", CAT, None, mine["name"]), frappe.ValidationError),  # same slot
				((mine["name"], "Swap", CAT, None, other_type["name"]), frappe.ValidationError),  # other duty type
				((mine["name"], "Swap", BEN, None, theirs["name"]), frappe.ValidationError),  # Ben not on it
				(("DUTY-SLOT-NOPE", "Replace", CAT), frappe.DoesNotExistError),
			):
				with self.assertRaises(exc, msg=args):
					duty.request_change(*args)
			req = duty.request_change(mine["name"], "Swap", CAT, swap_slot=theirs["name"], reason="dentist")
		self.assertEqual(
			(req["status"], req["from_user"], req["requested_by"], req["swap_slot"], req["duty_type"]),
			("Pending", ANN, ANN, theirs["name"], TYPE),
		)
		self.assertEqual(
			set(req),
			{
				"name", "duty_type", "slot", "slot_label", "slot_start", "slot_end", "request_type", "from_user",
				"from_user_name", "to_user", "to_user_name", "swap_slot", "swap_slot_label", "swap_slot_start",
				"swap_slot_end", "reason", "status", "requested_by", "requested_by_name", "decided_by",
				"decided_by_name", "decision_note", "creation",
			},
		)

	def test_no_double_pending_requests(self) -> None:
		mine = self.slot([ANN, BEN], start=10, end=16)
		theirs = self.slot([CAT], start=17, end=23)
		with self.as_user(ANN):
			duty.request_change(mine["name"], "Replace", CAT)
			with self.assertRaises(frappe.ValidationError):
				duty.request_change(mine["name"], "Swap", CAT, swap_slot=theirs["name"])
		# The other side of a swap is taken too.
		with self.as_user(BEN):
			duty.request_change(mine["name"], "Swap", CAT, swap_slot=theirs["name"])
		with self.as_user(PM):
			with self.assertRaises(frappe.ValidationError):
				duty.request_change(theirs["name"], "Replace", ANN, from_user=CAT)

	def test_a_manager_can_ask_for_anyone(self) -> None:
		mine = self.slot([ANN, BEN])
		with self.as_user(PM):
			req = duty.request_change(mine["name"], "Replace", CAT, from_user=BEN)
		self.assertEqual((req["from_user"], req["requested_by"]), (BEN, PM))

	def test_approving_a_swap_moves_both_people(self) -> None:
		mine = self.slot([ANN, BEN], start=10, end=16)
		theirs = self.slot([CAT], start=17, end=23)
		with self.as_user(ANN):
			req = duty.request_change(mine["name"], "Swap", CAT, swap_slot=theirs["name"])
		with self.as_user(PM):
			done = duty.decide(req["name"], 1, "ok")
		self.assertEqual((done["status"], done["decided_by"], done["decision_note"]), ("Approved", PM, "ok"))
		self.assertEqual(self.people_on(mine["name"]), [CAT, BEN])
		self.assertEqual(self.people_on(theirs["name"]), [ANN])
		full = frappe.get_doc("Duty Rota Slot", mine["name"]).assignees[0].full_name
		self.assertEqual(full, frappe.db.get_value("User", CAT, "full_name"))

	def test_approving_a_cover_and_rejecting_changes_nothing(self) -> None:
		mine = self.slot([ANN, BEN])
		with self.as_user(ANN):
			first = duty.request_change(mine["name"], "Replace", CAT)
		with self.as_user(PM):
			self.assertEqual(duty.decide(first["name"], "0", "busy")["status"], "Rejected")
		self.assertEqual(self.people_on(mine["name"]), [ANN, BEN])
		with self.as_user(ANN):
			second = duty.request_change(mine["name"], "Replace", CAT)
		with self.as_user(PM):
			duty.decide(second["name"], True)
		self.assertEqual(self.people_on(mine["name"]), [CAT, BEN])

	def test_only_a_manager_decides_and_only_pending_requests(self) -> None:
		mine = self.slot([ANN, BEN])
		with self.as_user(ANN):
			req = duty.request_change(mine["name"], "Replace", CAT)
			with self.assertRaises(frappe.PermissionError):
				duty.decide(req["name"], 1)
		with self.as_user(PM):
			duty.decide(req["name"], 1)
			with self.assertRaises(frappe.ValidationError):
				duty.decide(req["name"], 0)

	def test_cancel_is_for_the_requester_or_a_manager(self) -> None:
		mine = self.slot([ANN, BEN])
		with self.as_user(ANN):
			req = duty.request_change(mine["name"], "Replace", CAT)
		with self.as_user(BEN):
			with self.assertRaises(frappe.PermissionError):
				duty.cancel_request(req["name"])
		with self.as_user(ANN):
			self.assertEqual(duty.cancel_request(req["name"])["status"], "Cancelled")
			with self.assertRaises(frappe.ValidationError):
				duty.cancel_request(req["name"])
		with self.as_user(PM):
			with self.assertRaises(frappe.ValidationError):
				duty.decide(req["name"], 1)
		self.assertEqual(self.people_on(mine["name"]), [ANN, BEN])
		# A manager may cancel anyone's.
		with self.as_user(BEN):
			other = duty.request_change(mine["name"], "Replace", CAT)
		with self.as_user(PM):
			self.assertEqual(duty.cancel_request(other["name"])["status"], "Cancelled")

	def test_a_stale_request_is_refused_at_approval(self) -> None:
		mine = self.slot([ANN, BEN])
		with self.as_user(ANN):
			req = duty.request_change(mine["name"], "Replace", CAT)
		# The PM edits the slot afterwards and takes Ann off it.
		with self.as_user(PM):
			duty.save_slot(dict(duty.rota(TYPE)["slots"][0], **{"name": mine["name"], "assignees": [BEN]}) | {"duty_type": TYPE})
			with self.assertRaises(frappe.ValidationError) as caught:
				duty.decide(req["name"], 1)
			self.assertIn("no longer on", str(caught.exception))
			self.assertEqual(frappe.db.get_value("Duty Change Request", req["name"], "status"), "Pending")
			self.assertEqual(self.people_on(mine["name"]), [BEN])
			# It can still be rejected.
			self.assertEqual(duty.decide(req["name"], 0)["status"], "Rejected")

	def test_a_stale_swap_is_refused_when_the_other_person_moved(self) -> None:
		mine = self.slot([ANN], start=10, end=16)
		theirs = self.slot([CAT], start=17, end=23)
		with self.as_user(ANN):
			req = duty.request_change(mine["name"], "Swap", CAT, swap_slot=theirs["name"])
		with self.as_user(PM):
			slot = frappe.get_doc("Duty Rota Slot", theirs["name"])
			duty.save_slot(
				{"name": slot.name, "duty_type": TYPE, "start_date": str(slot.start_date), "end_date": str(slot.end_date), "assignees": [BEN]}
			)
			with self.assertRaises(frappe.ValidationError):
				duty.decide(req["name"], 1)
		self.assertEqual(self.people_on(mine["name"]), [ANN])

	def test_approval_is_all_or_nothing(self) -> None:
		mine = self.slot([ANN, BEN], start=10, end=16)
		theirs = self.slot([CAT], start=17, end=23)
		with self.as_user(ANN):
			req = duty.request_change(mine["name"], "Swap", CAT, swap_slot=theirs["name"])
		real_save = Document.save

		def failing_save(doc, *args, **kwargs):
			if doc.doctype == "Duty Rota Slot" and doc.name == theirs["name"]:
				raise frappe.ValidationError("disk on fire")
			return real_save(doc, *args, **kwargs)

		with self.as_user(PM), patch.object(Document, "save", autospec=True, side_effect=failing_save):
			with self.assertRaises(frappe.ValidationError):
				duty.decide(req["name"], 1)
		# The first slot was saved before the failure; the savepoint undid it.
		self.assertEqual(self.people_on(mine["name"]), [ANN, BEN])
		self.assertEqual(self.people_on(theirs["name"]), [CAT])
		self.assertEqual(frappe.db.get_value("Duty Change Request", req["name"], "status"), "Pending")
		with self.as_user(PM):
			duty.decide(req["name"], 1)
		self.assertEqual(self.people_on(mine["name"]), [CAT, BEN])

	def test_who_sees_which_requests(self) -> None:
		mine = self.slot([ANN, BEN])
		with self.as_user(ANN):
			req = duty.request_change(mine["name"], "Replace", CAT)
		for user, sees in ((ANN, True), (CAT, True), (BEN, False), (PM, True)):
			with self.as_user(user):
				self.assertEqual(req["name"] in [r["name"] for r in duty.change_requests()], sees, user)
		with self.as_user(PM):
			self.assertNotIn(req["name"], [r["name"] for r in duty.change_requests(mine=1)])
			self.assertIn(req["name"], [r["name"] for r in duty.change_requests(duty_type=TYPE, status="Pending")])
			self.assertNotIn(req["name"], [r["name"] for r in duty.change_requests(status="Approved")])
			with self.assertRaises(frappe.ValidationError):
				duty.change_requests(status="Bogus")


class IntegrationTestDutyNotifications(DutyTestBase):
	def test_a_new_request_tells_the_managers_and_the_other_person(self) -> None:
		mine = self.slot([ANN, BEN])
		with self.as_user(ANN):
			req = duty.request_change(mine["name"], "Replace", CAT)
		rows = self.notes(f"duty-req:{req['name']}:Pending")
		users = {r.user for r in rows}
		self.assertIn(PM, users)
		self.assertIn(CAT, users)
		self.assertNotIn(ANN, users)  # never the person who asked
		pm_row = next(r for r in rows if r.user == PM)
		self.assertEqual((pm_row.title, pm_row.kind, pm_row.route), ("Duty swap requested", "duty", "/duty?tab=requests"))

	def test_a_decision_tells_requester_and_both_people_once(self) -> None:
		mine = self.slot([ANN, BEN])
		with self.as_user(BEN):
			req = duty.request_change(mine["name"], "Replace", CAT)
		with self.as_user(PM):
			done = duty.decide(req["name"], 1)
			duty.notify_decision(frappe.get_doc("Duty Change Request", done["name"]))  # a repeat is deduped
		rows = self.notes(f"duty-req:{req['name']}:Approved")
		self.assertEqual(sorted(r.user for r in rows), sorted([BEN, CAT]))
		self.assertEqual({r.title for r in rows}, {"Swap approved"})

	def test_slot_edits_tell_added_and_removed_people_once_per_save(self) -> None:
		mine = self.slot([ANN, BEN])
		with self.as_user(PM):
			first = duty.save_slot(
				{"name": mine["name"], "duty_type": TYPE, "start_date": _day(10), "end_date": _day(16), "assignees": [BEN, CAT]}
			)
			doc = frappe.get_doc("Duty Rota Slot", mine["name"])
			duty.notify_slot_change(doc, [ANN, BEN], (_day(10), _day(16)))  # same save again: deduped
		# Creating the slot told Ann and Ben they are on it; this edit has its own key.
		rows = self.notes(f"duty-slot:{mine['name']}:{doc.modified}")
		self.assertEqual(sorted((r.user, r.title) for r in rows), [(ANN, "You are off duty"), (CAT, "You are on duty")])
		# A later edit is a new transition: moving the dates tells the people who stayed.
		with self.as_user(PM):
			duty.save_slot(dict(first, start_date=_day(11), end_date=_day(17), assignees=[BEN, CAT]))
		rows = self.notes(f"duty-slot:{mine['name']}:%")
		self.assertEqual(sorted(r.user for r in rows if r.title == "Duty dates changed"), [BEN, CAT])
		self.assertEqual(len({r.dedupe_key for r in rows}), 3)  # create, edit, date move

	def test_start_reminders_go_once(self) -> None:
		slot = self.slot([ANN, BEN], start=1, end=7)
		duty.send_start_reminders()
		duty.send_start_reminders()
		rows = self.notes(f"duty-start:{slot['name']}")
		self.assertEqual(sorted(r.user for r in rows), [ANN, BEN])

	def test_hooks_register_the_reminder(self) -> None:
		from upande_dev_tools import hooks

		self.assertIn("upande_dev_tools.api.duty.send_start_reminders", hooks.scheduler_events["cron"]["0 7 * * *"])


class IntegrationTestDutyTypes(DutyTestBase):
	def test_managers_edit_duty_types(self) -> None:
		with self.as_user(ANN):
			with self.assertRaises(frappe.PermissionError):
				duty.save_duty_type({"duty_name": "Night watch"})
		with self.as_user(PM):
			made = duty.save_duty_type({"duty_name": "Night watch", "default_cadence": "Daily", "people_per_slot": 1})
			self.assertEqual((made["name"], made["is_active"]), ("Night watch", 1))
			with self.assertRaises(frappe.DuplicateEntryError):
				duty.save_duty_type({"duty_name": "Night watch"})
			for bad in ({"duty_name": ""}, {"duty_name": "X", "default_cadence": "Hourly"}, {"duty_name": "Y", "people_per_slot": -1}):
				with self.assertRaises(frappe.ValidationError):
					duty.save_duty_type(bad)
			off = duty.save_duty_type(dict(made, is_active=0))
			self.assertEqual(off["is_active"], 0)
			with self.assertRaises(frappe.ValidationError):
				duty.save_duty_type(dict(made, duty_name="Renamed"))
			self.assertIn("Night watch", [t["name"] for t in duty.all_duty_types()])
			self.assertNotIn("Night watch", [t["name"] for t in duty.duty_types()])
