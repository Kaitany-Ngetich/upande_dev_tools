# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

from datetime import date, timedelta

import frappe
from frappe.utils import getdate, today

from upande_dev_tools.setup import DEV_TOOLS_PROJECT_TYPE

PRIORITY_POINTS = {"Low": 1, "Medium": 2, "High": 4, "Urgent": 6}
OVERDUE_BONUS = 1
LEADERBOARD_SIZE = 10
STREAK_BADGE_DAYS = 5
OVERDUE_BADGE_COUNT = 5
CAPTURE_BADGE_COUNT = 10

BADGES = [
	("first_close", "First close", "Close your first task."),
	("streak_5", "On a roll", "Close at least one task on 5 weekdays in a row."),
	("overdue_slayer", "Overdue slayer", "Clear 5 overdue tasks."),
	("deploy_day", "Deploy day", "Get a deployment you requested all the way to Deployed."),
	("capture_champion", "Capture champion", "Raise 10 requests from the mobile app."),
]


def is_overdue(task: dict) -> bool:
	end, done = task.get("exp_end_date"), task.get("completed_on")
	return bool(end and done and getdate(end) < getdate(done))


def task_points(task: dict) -> int:
	return PRIORITY_POINTS.get(task.get("priority"), 0) + (OVERDUE_BONUS if is_overdue(task) else 0)


def _previous_weekday(day: date) -> date:
	day -= timedelta(days=1)
	while day.weekday() > 4:
		day -= timedelta(days=1)
	return day


def compute_streaks(close_dates: set[date], on: date) -> tuple[int, int]:
	"""(current, best) runs of consecutive weekdays with a close. Weekend closes neither extend nor break a run. The
	current run must end today or on the previous weekday."""
	days = sorted(d for d in close_dates if d.weekday() <= 4)
	if not days:
		return 0, 0
	best = run = 1
	for prev, cur in zip(days, days[1:]):
		run = run + 1 if _previous_weekday(cur) == prev else 1
		best = max(best, run)

	have = set(days)
	cursor = on
	while cursor.weekday() > 4:
		cursor -= timedelta(days=1)
	if cursor not in have:
		cursor = _previous_weekday(cursor)
	current = 0
	while cursor in have:
		current += 1
		cursor = _previous_weekday(cursor)
	return current, max(best, current)


def _week_start(day: date) -> date:
	return day - timedelta(days=day.weekday())


def _project_filter() -> dict:
	"""Dev Tools-flagged projects only, like the board; all tasks when none are flagged yet."""
	projects = frappe.get_all(
		"Project", filters={"project_type": DEV_TOOLS_PROJECT_TYPE}, pluck="name", ignore_permissions=True
	)
	return {"project": ["in", projects]} if projects else {}


def _closed_tasks(extra: dict) -> list[dict]:
	filters = {"status": "Completed", "completed_on": ["is", "set"], **_project_filter(), **extra}
	return frappe.get_all(
		"Task",
		filters=filters,
		fields=["name", "priority", "exp_end_date", "completed_on", "completed_by"],
		ignore_permissions=True,
		limit_page_length=0,
	)


def _leaderboard(week_start: date) -> list[dict]:
	totals: dict[str, dict] = {}
	for task in _closed_tasks({"completed_on": [">=", week_start]}):
		if not task.completed_by:
			continue
		row = totals.setdefault(task.completed_by, {"user": task.completed_by, "points": 0, "closed": 0})
		row["points"] += task_points(task)
		row["closed"] += 1
	rows = sorted((r for r in totals.values() if r["points"] > 0), key=lambda r: (-r["points"], -r["closed"], r["user"]))
	rows = rows[:LEADERBOARD_SIZE]
	if rows:
		names = {
			u.name: u.full_name
			for u in frappe.get_all(
				"User",
				filters={"name": ["in", [r["user"] for r in rows]]},
				fields=["name", "full_name"],
				ignore_permissions=True,
			)
		}
		for row in rows:
			row["full_name"] = names.get(row["user"]) or row["user"]
	return rows


@frappe.whitelist()
def get_achievements() -> dict:
	user = frappe.session.user
	now = getdate(today())
	week_start = _week_start(now)

	mine = _closed_tasks({"completed_by": user})
	points_today = points_week = points_total = closed_today = closed_week = overdue_closed = 0
	close_dates: set[date] = set()
	for task in mine:
		done = getdate(task.completed_on)
		pts = task_points(task)
		points_total += pts
		close_dates.add(done)
		overdue_closed += int(is_overdue(task))
		if done >= week_start:
			points_week += pts
			closed_week += 1
		if done == now:
			points_today += pts
			closed_today += 1
	streak, best_streak = compute_streaks(close_dates, now)

	deployed = frappe.db.count("Deployment Request", {"requested_by_user": user, "workflow_state": "Deployed"})
	captured = frappe.db.count("Request", {"raised_by_user": user, "source": "Mobile App"})
	earned = {
		"first_close": bool(mine),
		"streak_5": best_streak >= STREAK_BADGE_DAYS,
		"overdue_slayer": overdue_closed >= OVERDUE_BADGE_COUNT,
		"deploy_day": deployed > 0,
		"capture_champion": captured >= CAPTURE_BADGE_COUNT,
	}
	progress = {
		"first_close": (min(len(mine), 1), 1),
		"streak_5": (min(best_streak, STREAK_BADGE_DAYS), STREAK_BADGE_DAYS),
		"overdue_slayer": (min(overdue_closed, OVERDUE_BADGE_COUNT), OVERDUE_BADGE_COUNT),
		"deploy_day": (min(deployed, 1), 1),
		"capture_champion": (min(captured, CAPTURE_BADGE_COUNT), CAPTURE_BADGE_COUNT),
	}
	return {
		"points_today": points_today,
		"points_week": points_week,
		"points_total": points_total,
		"streak": streak,
		"best_streak": best_streak,
		"closed_today": closed_today,
		"closed_week": closed_week,
		"week_days": sorted(d.isoformat() for d in close_dates if d >= week_start),
		"badges": [
			{
				"key": key,
				"label": label,
				"description": desc,
				"earned": earned[key],
				"progress": {"current": progress[key][0], "target": progress[key][1]},
			}
			for key, label, desc in BADGES
		],
		"leaderboard": _leaderboard(week_start),
	}
