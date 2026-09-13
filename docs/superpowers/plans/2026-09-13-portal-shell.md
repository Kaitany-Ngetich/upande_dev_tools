# Portal Shell & Access Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the `Dev Portal Page` registry doctype, the routing/access-control helpers it drives, the shared Role-Advisor-styled shell, and the settings page itself — the foundation Phase 2's Developer/PM/Customer dashboards (Sub-projects 2-4) build their pages on top of.

**Architecture:** One doctype (`Dev Portal Page`) is the single source of truth for both sidebar navigation and page-level access control. Two shared Python helpers (`resolve_home_route`, `enforce_page_access`) and one Jinja-exposed helper (`get_nav_items`) in a new `upande_dev_tools/portal.py` read it. A shared CSS file + Jinja include give every future `www` page identical chrome without duplicating it. Pages self-register via the same idempotent `after_install`/`after_migrate` pattern Phase 1 established for Task's custom fields.

**Tech Stack:** Frappe framework (`>=16.0.0,<=17.0.0`), Python 3.14, server-rendered Jinja (`www/*.html` extending `templates/web.html`) — no JS framework/bundler, matching `upande_packhouse`'s own portal pages.

**Spec:** `docs/specs/2026-09-13-portal-shell-design.md`

## Global Constraints

- Frappe version floor/ceiling: `>=16.0.0,<=17.0.0`.
- Every `@frappe.whitelist()` method must have full parameter **and return** type annotations.
- New Python files: tab indentation, double-quoted strings, 110-char lines. Run `ruff format <file>` on every new/modified `.py` file before committing, and `ruff format --check` to actually confirm — do not claim "clean" without running it.
- Doctype controller files: `# Copyright (c) 2026, shadrack@upande.com and contributors` / `# For license information, please see license.txt`. Doctype test files: `# Copyright (c) 2026, shadrack@upande.com and Contributors` / `# See license.txt`. Top-level `tests/` folder files (not tied to one doctype): `# Copyright (c) 2026, Upande Limited` (matching `upande_dev_tools/tests/test_customization_exporter.py`). App-root files (`upande_dev_tools/portal.py`, matching the existing `upande_dev_tools/setup.py`) and `api/` files: no header. `www/*.py` page controllers: the doctype-controller header (this app has no prior `www/` convention of its own, and these are licensed source files — follow the same convention as controllers).
- This doctype and every new file join the app's existing, single `Upande Dev Tools` module — no new entry in `modules.txt`.
- All paths relative to the app repo root (`apps/upande_dev_tools/`).
- After adding a doctype or fixture, run `bench --site <site> migrate` before running that task's tests.
- This bench has two known, pre-existing, unrelated test-environment quirks documented in Phase 1's plan (`docs/superpowers/plans/2026-09-13-requests-backlog-phase1.md`): a whole-app `bench run-tests` failure (use `--module` always) and a bench-specific `pypika`/`Task.check_recursion` crash on any programmatic `Task` insert (irrelevant to this plan — nothing here creates a `Task`). Neither should resurface here, but if a test failure mentions "Company" or a country's "regional setup", it's that first quirk, not a defect in this plan's own code.
- **Redirect mechanism**: Frappe's own `www/login.py` establishes the pattern for a quiet page redirect from inside `get_context()`: set `frappe.local.flags.redirect_location = <url>` then `raise frappe.Redirect`. Use this exact pattern everywhere this plan redirects — do not invent a different mechanism (an HTML meta-refresh, a JS redirect, etc.).
- **Role-list child table**: reuse Frappe's own built-in `Has Role` child doctype (fields: just `role`, a Link to Role) for `Dev Portal Page.allowed_roles` — this is the exact mechanism Frappe's own `Workspace.roles` field already uses (`"fieldtype": "Table", "options": "Has Role"`). Do not create a new child doctype for this.

---

### Task 1: The `Dev Portal Page` doctype

**Files:**
- Create: `upande_dev_tools/upande_dev_tools/doctype/dev_portal_page/__init__.py`
- Create: `upande_dev_tools/upande_dev_tools/doctype/dev_portal_page/dev_portal_page.json`
- Create: `upande_dev_tools/upande_dev_tools/doctype/dev_portal_page/dev_portal_page.py`
- Test: `upande_dev_tools/upande_dev_tools/doctype/dev_portal_page/test_dev_portal_page.py`

**Interfaces:**
- Produces: doctype `Dev Portal Page` with fields `route` (Data, unique, is the doc name), `title`, `icon`, `nav_group`, `sort_order` (Int), `allowed_roles` (Table, options `Has Role`), `require_all_roles` (Check). Task 2's helpers read this schema directly.

This doctype joins the app's existing, single `Upande Dev Tools` module — no `modules.txt` change, no module-level package files beyond this doctype's own folder.

- [ ] **Step 1: Create the package file**

`upande_dev_tools/upande_dev_tools/doctype/dev_portal_page/__init__.py` — empty file.

- [ ] **Step 2: Write the failing tests**

`upande_dev_tools/upande_dev_tools/doctype/dev_portal_page/test_dev_portal_page.py`:

```python
# Copyright (c) 2026, shadrack@upande.com and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase


class IntegrationTestDevPortalPage(IntegrationTestCase):
	def test_named_by_route(self) -> None:
		doc = frappe.get_doc(
			{
				"doctype": "Dev Portal Page",
				"route": "dev-portal-page-test-route",
				"title": "Test Page",
				"nav_group": "Test",
				"allowed_roles": [{"role": "Dev Team"}],
			}
		).insert(ignore_permissions=True)
		self.assertEqual(doc.name, "dev-portal-page-test-route")

	def test_allowed_roles_saves_has_role_rows(self) -> None:
		doc = frappe.get_doc(
			{
				"doctype": "Dev Portal Page",
				"route": "dev-portal-page-test-roles",
				"title": "Test Roles",
				"nav_group": "Test",
				"allowed_roles": [{"role": "Dev Team"}, {"role": "System Manager"}],
			}
		).insert(ignore_permissions=True)
		roles = {row.role for row in doc.allowed_roles}
		self.assertEqual(roles, {"Dev Team", "System Manager"})
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `bench --site <site> run-tests --app upande_dev_tools --module upande_dev_tools.upande_dev_tools.doctype.dev_portal_page.test_dev_portal_page`
Expected: FAIL — `Dev Portal Page` doesn't exist yet.

- [ ] **Step 4: Write the doctype schema**

`upande_dev_tools/upande_dev_tools/doctype/dev_portal_page/dev_portal_page.json`:

```json
{
 "actions": [],
 "allow_rename": 0,
 "autoname": "field:route",
 "creation": "2026-09-13 00:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": [
  "route",
  "title",
  "column_break_type",
  "icon",
  "nav_group",
  "sort_order",
  "section_break_roles",
  "allowed_roles",
  "require_all_roles"
 ],
 "fields": [
  {
   "fieldname": "route",
   "fieldtype": "Data",
   "in_list_view": 1,
   "label": "Route",
   "reqd": 1,
   "unique": 1
  },
  {
   "fieldname": "title",
   "fieldtype": "Data",
   "in_list_view": 1,
   "label": "Title",
   "reqd": 1
  },
  {
   "fieldname": "column_break_type",
   "fieldtype": "Column Break"
  },
  {
   "fieldname": "icon",
   "fieldtype": "Data",
   "label": "Icon"
  },
  {
   "fieldname": "nav_group",
   "fieldtype": "Data",
   "in_list_view": 1,
   "in_standard_filter": 1,
   "label": "Nav Group"
  },
  {
   "default": "0",
   "fieldname": "sort_order",
   "fieldtype": "Int",
   "label": "Sort Order"
  },
  {
   "fieldname": "section_break_roles",
   "fieldtype": "Section Break",
   "label": "Access"
  },
  {
   "fieldname": "allowed_roles",
   "fieldtype": "Table",
   "label": "Allowed Roles",
   "options": "Has Role"
  },
  {
   "default": "0",
   "fieldname": "require_all_roles",
   "fieldtype": "Check",
   "label": "Require All Roles"
  }
 ],
 "index_web_pages_for_search": 1,
 "links": [],
 "modified": "2026-09-13 00:00:00.000000",
 "modified_by": "Administrator",
 "module": "Upande Dev Tools",
 "name": "Dev Portal Page",
 "naming_rule": "By fieldname",
 "owner": "Administrator",
 "permissions": [
  {
   "create": 1,
   "delete": 1,
   "email": 1,
   "export": 1,
   "print": 1,
   "read": 1,
   "report": 1,
   "role": "System Manager",
   "share": 1,
   "write": 1
  },
  {
   "create": 1,
   "read": 1,
   "report": 1,
   "role": "Dev Team",
   "share": 1,
   "write": 1
  }
 ],
 "sort_field": "creation",
 "sort_order": "DESC",
 "states": [],
 "title_field": "title"
}
```

- [ ] **Step 5: Write the minimal controller**

`upande_dev_tools/upande_dev_tools/doctype/dev_portal_page/dev_portal_page.py`:

```python
# Copyright (c) 2026, shadrack@upande.com and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class DevPortalPage(Document):
	pass
```

- [ ] **Step 6: Migrate and run tests**

Run: `bench --site <site> migrate`
Run: `bench --site <site> run-tests --app upande_dev_tools --module upande_dev_tools.upande_dev_tools.doctype.dev_portal_page.test_dev_portal_page`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
ruff format upande_dev_tools/upande_dev_tools/doctype/dev_portal_page/dev_portal_page.py upande_dev_tools/upande_dev_tools/doctype/dev_portal_page/test_dev_portal_page.py
git add upande_dev_tools/upande_dev_tools/doctype/dev_portal_page
git commit -m "feat: add Dev Portal Page registry doctype

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Routing & access-control helpers (`upande_dev_tools/portal.py`)

**Files:**
- Create: `upande_dev_tools/portal.py`
- Test: `upande_dev_tools/tests/test_portal.py`

**Interfaces:**
- Consumes: `Dev Portal Page` (Task 1).
- Produces: `resolve_home_route(user=None) -> str`, `enforce_page_access(route) -> None` (raises `frappe.Redirect` on denial, returns `None` silently when permitted), `get_nav_items(user=None) -> list[dict]`. Task 3's setup function creates the `Dev Portal Page` records these read; Task 5's settings page and Task 6's vanity route both call `enforce_page_access`; Task 4's shell template calls `get_nav_items` as a Jinja global.

- [ ] **Step 1: Write the failing tests**

`upande_dev_tools/tests/test_portal.py`:

```python
# Copyright (c) 2026, Upande Limited

import frappe
from frappe.tests import IntegrationTestCase

from upande_dev_tools.portal import enforce_page_access, get_nav_items, resolve_home_route


class IntegrationTestPortal(IntegrationTestCase):
	def _make_user(self, email: str, roles: list[str]) -> str:
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Test", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		user = frappe.get_doc("User", email)
		if roles:
			user.add_roles(*roles)
		return email

	def _make_page(
		self,
		route: str,
		roles: list[str],
		require_all_roles: bool = False,
		nav_group: str = "Test",
		sort_order: int = 0,
	) -> str:
		if frappe.db.exists("Dev Portal Page", route):
			frappe.delete_doc("Dev Portal Page", route, ignore_permissions=True, force=True)
		return (
			frappe.get_doc(
				{
					"doctype": "Dev Portal Page",
					"route": route,
					"title": route,
					"nav_group": nav_group,
					"sort_order": sort_order,
					"require_all_roles": 1 if require_all_roles else 0,
					"allowed_roles": [{"role": role} for role in roles],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_resolve_home_route_prioritizes_dev_team(self) -> None:
		dev = self._make_user("portal-dev@example.test", ["Dev Team"])
		self.assertEqual(resolve_home_route(dev), "/dev-dashboard")

	def test_resolve_home_route_falls_back_to_projects_manager(self) -> None:
		pm = self._make_user("portal-pm@example.test", ["Projects Manager"])
		self.assertEqual(resolve_home_route(pm), "/pm-dashboard")

	def test_resolve_home_route_defaults_for_any_other_authenticated_user(self) -> None:
		other = self._make_user("portal-other@example.test", [])
		self.assertEqual(resolve_home_route(other), "/requests-portal")

	def test_resolve_home_route_sends_guest_to_login(self) -> None:
		self.assertEqual(resolve_home_route("Guest"), "/login")

	def test_enforce_page_access_permits_matching_role(self) -> None:
		self._make_page("portal-test-permit", ["Dev Team"])
		dev = self._make_user("portal-permit@example.test", ["Dev Team"])
		frappe.set_user(dev)
		try:
			enforce_page_access("portal-test-permit")  # must not raise
		finally:
			frappe.set_user("Administrator")

	def test_enforce_page_access_redirects_when_denied(self) -> None:
		self._make_page("portal-test-deny", ["Projects Manager"])
		dev = self._make_user("portal-deny@example.test", ["Dev Team"])
		frappe.set_user(dev)
		try:
			with self.assertRaises(frappe.Redirect):
				enforce_page_access("portal-test-deny")
			self.assertEqual(frappe.local.flags.redirect_location, "/dev-dashboard")
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None

	def test_enforce_page_access_requires_every_role_when_require_all_roles(self) -> None:
		self._make_page("portal-test-dual", ["Dev Team", "System Manager"], require_all_roles=True)
		dev_only = self._make_user("portal-dual-partial@example.test", ["Dev Team"])
		frappe.set_user(dev_only)
		try:
			with self.assertRaises(frappe.Redirect):
				enforce_page_access("portal-test-dual")
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None

	def test_enforce_page_access_denies_unregistered_route(self) -> None:
		dev = self._make_user("portal-unregistered@example.test", ["Dev Team"])
		frappe.set_user(dev)
		try:
			with self.assertRaises(frappe.Redirect):
				enforce_page_access("portal-test-does-not-exist")
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None

	def test_enforce_page_access_sends_guest_to_login_with_redirect_param(self) -> None:
		# The Guest check runs before any page lookup, so this route need not exist —
		# self-contained, not dependent on another test method having created a page.
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.Redirect):
				enforce_page_access("portal-test-guest-route")
			self.assertEqual(
				frappe.local.flags.redirect_location, "/login?redirect-to=/portal-test-guest-route"
			)
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None

	def test_get_nav_items_only_returns_permitted_pages(self) -> None:
		self._make_page("portal-nav-visible", ["Dev Team"], nav_group="Group A", sort_order=1)
		self._make_page("portal-nav-hidden", ["Projects Manager"], nav_group="Group A", sort_order=2)
		dev = self._make_user("portal-nav@example.test", ["Dev Team"])
		items = get_nav_items(dev)
		routes = {item["route"] for item in items}
		self.assertIn("portal-nav-visible", routes)
		self.assertNotIn("portal-nav-hidden", routes)

	def test_get_nav_items_empty_for_guest(self) -> None:
		self.assertEqual(get_nav_items("Guest"), [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `bench --site <site> run-tests --app upande_dev_tools --module upande_dev_tools.tests.test_portal`
Expected: FAIL — `upande_dev_tools.portal` doesn't exist yet.

- [ ] **Step 3: Implement**

`upande_dev_tools/portal.py`:

```python
import frappe

HOME_ROUTE_BY_ROLE = (
	("Dev Team", "/dev-dashboard"),
	("Projects Manager", "/pm-dashboard"),
)
DEFAULT_AUTHENTICATED_ROUTE = "/requests-portal"
LOGIN_ROUTE = "/login"


def resolve_home_route(user: str | None = None) -> str:
	user = user or frappe.session.user
	if user == "Guest":
		return LOGIN_ROUTE

	roles = set(frappe.get_roles(user))
	for role, route in HOME_ROUTE_BY_ROLE:
		if role in roles:
			return route
	return DEFAULT_AUTHENTICATED_ROUTE


def _fetch_page(route: str) -> frappe._dict | None:
	return frappe.db.get_value(
		"Dev Portal Page", route, ["name", "require_all_roles"], as_dict=True
	)


def _allowed_roles(page_name: str) -> set[str]:
	return set(
		frappe.get_all(
			"Has Role",
			filters={"parent": page_name, "parenttype": "Dev Portal Page"},
			pluck="role",
		)
	)


def _is_permitted(allowed: set[str], require_all: bool, user_roles: set[str]) -> bool:
	if not allowed:
		return False
	if require_all:
		return allowed <= user_roles
	return bool(user_roles & allowed)


def enforce_page_access(route: str) -> None:
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = f"{LOGIN_ROUTE}?redirect-to=/{route}"
		raise frappe.Redirect

	page = _fetch_page(route)
	if not page:
		frappe.local.flags.redirect_location = resolve_home_route()
		raise frappe.Redirect

	allowed = _allowed_roles(page.name)
	if not _is_permitted(allowed, bool(page.require_all_roles), set(frappe.get_roles())):
		frappe.local.flags.redirect_location = resolve_home_route()
		raise frappe.Redirect


def get_nav_items(user: str | None = None) -> list[dict]:
	user = user or frappe.session.user
	if user == "Guest":
		return []

	pages = frappe.get_all(
		"Dev Portal Page",
		fields=["name", "route", "title", "icon", "nav_group", "sort_order", "require_all_roles"],
		order_by="nav_group asc, sort_order asc, title asc",
	)
	if not pages:
		return []

	role_rows = frappe.get_all(
		"Has Role",
		filters={"parent": ["in", [page.name for page in pages]], "parenttype": "Dev Portal Page"},
		fields=["parent", "role"],
	)
	roles_by_page: dict[str, set[str]] = {}
	for row in role_rows:
		roles_by_page.setdefault(row.parent, set()).add(row.role)

	user_roles = set(frappe.get_roles(user))
	return [
		page
		for page in pages
		if _is_permitted(roles_by_page.get(page.name, set()), bool(page.require_all_roles), user_roles)
	]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `bench --site <site> run-tests --app upande_dev_tools --module upande_dev_tools.tests.test_portal`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
ruff format upande_dev_tools/portal.py upande_dev_tools/tests/test_portal.py
git add upande_dev_tools/portal.py upande_dev_tools/tests/test_portal.py
git commit -m "feat: add portal routing/access-control helpers

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Self-registration (`register_dev_portal_page`) + `run_setup` wiring

**Files:**
- Modify: `upande_dev_tools/setup.py`
- Modify: `upande_dev_tools/hooks.py`
- Test: `upande_dev_tools/tests/test_portal.py` (extend)

**Interfaces:**
- Consumes: `Dev Portal Page` (Task 1).
- Produces: `register_dev_portal_page(route, title, icon, nav_group, sort_order, roles, require_all_roles=False) -> None` (create-if-missing, never overwrites an existing record — so an admin's later edits via the settings screen survive a future `bench migrate`), `register_dev_portal_pages() -> None` (registers the settings page itself), `run_setup() -> None` (calls `create_task_custom_fields()` — from Phase 1 — and `register_dev_portal_pages()`, and is what `hooks.py`'s `after_install`/`after_migrate` now point to instead of `create_task_custom_fields` directly). Task 5's settings page relies on its own `Dev Portal Page` record existing after this task lands.

- [ ] **Step 1: Write the failing test**

Append to `upande_dev_tools/tests/test_portal.py` (add `from upande_dev_tools.setup import register_dev_portal_page` to the imports):

```python
	def test_register_dev_portal_page_is_create_only(self) -> None:
		if frappe.db.exists("Dev Portal Page", "portal-register-test"):
			frappe.delete_doc("Dev Portal Page", "portal-register-test", ignore_permissions=True, force=True)

		register_dev_portal_page(
			route="portal-register-test",
			title="Register Test",
			icon="test",
			nav_group="Test",
			sort_order=1,
			roles=["Dev Team"],
		)
		doc = frappe.get_doc("Dev Portal Page", "portal-register-test")
		self.assertEqual([row.role for row in doc.allowed_roles], ["Dev Team"])

		# An admin's later edit (e.g. via the settings screen) must survive re-registration.
		doc.allowed_roles = []
		doc.append("allowed_roles", {"role": "System Manager"})
		doc.save(ignore_permissions=True)

		register_dev_portal_page(
			route="portal-register-test",
			title="Register Test",
			icon="test",
			nav_group="Test",
			sort_order=1,
			roles=["Dev Team"],
		)
		doc.reload()
		self.assertEqual([row.role for row in doc.allowed_roles], ["System Manager"])

	def test_dev_portal_settings_page_is_self_registered(self) -> None:
		self.assertTrue(frappe.db.exists("Dev Portal Page", "dev-portal-settings"))
		doc = frappe.get_doc("Dev Portal Page", "dev-portal-settings")
		self.assertTrue(doc.require_all_roles)
		self.assertEqual({row.role for row in doc.allowed_roles}, {"Dev Team", "System Manager"})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `bench --site <site> run-tests --app upande_dev_tools --module upande_dev_tools.tests.test_portal`
Expected: FAIL — `register_dev_portal_page` doesn't exist yet, and no `dev-portal-settings` record exists.

- [ ] **Step 3: Implement**

Append to `upande_dev_tools/setup.py`:

```python
def register_dev_portal_page(
	route: str,
	title: str,
	icon: str,
	nav_group: str,
	sort_order: int,
	roles: list[str],
	require_all_roles: bool = False,
) -> None:
	if frappe.db.exists("Dev Portal Page", route):
		return

	frappe.get_doc(
		{
			"doctype": "Dev Portal Page",
			"route": route,
			"title": title,
			"icon": icon,
			"nav_group": nav_group,
			"sort_order": sort_order,
			"require_all_roles": 1 if require_all_roles else 0,
			"allowed_roles": [{"role": role} for role in roles],
		}
	).insert(ignore_permissions=True)


def register_dev_portal_pages() -> None:
	register_dev_portal_page(
		route="dev-portal-settings",
		title="Settings",
		icon="settings",
		nav_group="Admin",
		sort_order=100,
		roles=["Dev Team", "System Manager"],
		require_all_roles=True,
	)


def run_setup() -> None:
	create_task_custom_fields()
	register_dev_portal_pages()
```

In `upande_dev_tools/hooks.py`, change:

```python
after_install = "upande_dev_tools.setup.create_task_custom_fields"
after_migrate = "upande_dev_tools.setup.create_task_custom_fields"
```

to:

```python
after_install = "upande_dev_tools.setup.run_setup"
after_migrate = "upande_dev_tools.setup.run_setup"
```

- [ ] **Step 4: Migrate and run tests**

Run: `bench --site <site> migrate`
Run: `bench --site <site> run-tests --app upande_dev_tools --module upande_dev_tools.tests.test_portal`
Expected: PASS — including `test_dev_portal_settings_page_is_self_registered`, since `bench migrate` just ran `after_migrate` → `run_setup()` → `register_dev_portal_pages()`.

Also re-run Task 3's own module (unaffected, sanity check):

Run: `bench --site <site> run-tests --app upande_dev_tools --module upande_dev_tools.tests.test_requests_api`
Expected: PASS (unchanged — `create_task_custom_fields` still runs, just via `run_setup` now).

- [ ] **Step 5: Commit**

```bash
ruff format upande_dev_tools/setup.py
git add upande_dev_tools/setup.py upande_dev_tools/hooks.py upande_dev_tools/tests/test_portal.py
git commit -m "feat: self-register Dev Portal Page records via run_setup

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Shared shell — CSS + Jinja include + `jinja` hook

**Files:**
- Create: `upande_dev_tools/templates/includes/__init__.py` (this app has no `templates/includes/` folder yet — `frappe/templates/includes/` itself ships an `__init__.py` even though the folder holds only templates, and this app's convention, per `templates/__init__.py`/`templates/pages/__init__.py`, is to match that)
- Create: `upande_dev_tools/public/css/dev-portal.css`
- Create: `upande_dev_tools/templates/includes/dev_portal_shell.html`
- Modify: `upande_dev_tools/hooks.py`

**Interfaces:**
- Consumes: `get_nav_items` (Task 2), exposed as a Jinja global via the `jinja` hook.
- Produces: a reusable `{% include %}`-able sidebar/topbar shell, and the shared stylesheet it uses. Task 5 and Task 6's pages both include this template.

- [ ] **Step 1: Create the package file**

`upande_dev_tools/templates/includes/__init__.py` — empty file.

- [ ] **Step 2: Write the shared stylesheet**

`upande_dev_tools/public/css/dev-portal.css` — ports the Role Advisor tokens from `upande_packhouse/upande_packhouse/public/css/packhouse-portal.css` and the inline `<style>` block in `upande_packhouse/upande_packhouse/www/packhouse-dashboard.html`, scoped under one root class `.dpx` (short for "dev portal"), so it can never leak into or clash with Frappe's own desk/website styles:

```css
/* Dev Portal shell — shares the Role Advisor design language used across
 * Upande's other dashboards (see upande_packhouse/public/css/packhouse-portal.css).
 * Scoped under .dpx so it only ever touches this portal's own shell.
 */

.dpx {
	--ink: #0a0a0a;
	--ink-2: #2a2a26;
	--ink-3: #3a3a34;
	--ink-4: #5a5a52;
	--ink-mute: #8a8780;
	--ink-faint: #b8b6ae;
	--bg: #f4f3ef;
	--surface: #fafaf6;
	--surface-2: #ffffff;
	--hairline: rgba(10, 10, 10, 0.06);
	--shadow-card: 0 1px 0 rgba(10, 10, 10, 0.04), 0 8px 32px -16px rgba(10, 10, 10, 0.1);
	--shadow-hover: 0 1px 0 rgba(10, 10, 10, 0.06), 0 24px 48px -24px rgba(10, 10, 10, 0.18);
	--grad-ink: linear-gradient(135deg, #0a0a0a 0%, #3a3a34 100%);
	--sans: "Poppins", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
	--display: "Fraunces", Georgia, serif;
	--mono: "JetBrains Mono", "SF Mono", ui-monospace, Menlo, monospace;
	--sidebar-w: 248px;

	position: fixed;
	top: 0;
	left: 0;
	right: 0;
	bottom: 0;
	width: 100vw;
	height: 100vh;
	z-index: 2147483000;
	font-family: var(--sans);
	background: var(--bg);
	color: var(--ink-3);
	font-size: 13px;
	line-height: 1.55;
	display: grid;
	grid-template-columns: var(--sidebar-w) 1fr;
}
.dpx *{box-sizing:border-box;margin:0;padding:0}
html:has(.dpx),body:has(.dpx){margin:0!important;padding:0!important;overflow:hidden!important;height:100vh!important}
.dpx svg.ic{width:16px;height:16px;flex-shrink:0;stroke:currentColor;fill:none;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round}

/* ══ SIDEBAR ══ */
.dpx .dpx-side{background:var(--surface-2);border-right:1px solid var(--hairline);height:100vh;position:sticky;top:0;display:flex;flex-direction:column;overflow:hidden}
.dpx .dpx-side .brand{padding:20px 18px 16px;display:flex;align-items:center;gap:12px;text-decoration:none;border-bottom:1px solid var(--hairline)}
.dpx .dpx-side .brand .name{font:600 14px var(--sans);color:var(--ink);letter-spacing:-.2px}
.dpx .dpx-side .brand .name small{display:block;font:500 10px var(--sans);text-transform:uppercase;letter-spacing:1.6px;color:var(--ink-mute);margin-top:2px}
.dpx .dpx-side .nav{flex:1 1 auto;min-height:0;overflow-y:auto;padding:8px 0 16px;list-style:none;display:flex;flex-direction:column}
.dpx .dpx-side .group-lbl{padding:16px 20px 6px;font:600 10px var(--sans);color:var(--ink-mute);letter-spacing:1.8px;text-transform:uppercase}
.dpx .dpx-side .nav-item{display:flex;align-items:center;gap:12px;padding:10px 12px;font:500 13px var(--sans);color:var(--ink-4);text-decoration:none;margin:2px 10px;border-radius:12px;transition:background .18s ease,color .18s ease}
.dpx .dpx-side .nav-item:hover{background:rgba(10,10,10,0.04);color:var(--ink)}
.dpx .dpx-side .nav-item.active{background:var(--grad-ink);color:#fafaf6;box-shadow:0 4px 14px rgba(10,10,10,0.2)}
.dpx .dpx-side .footer{padding:14px 18px;border-top:1px solid var(--hairline);display:flex;align-items:center;gap:11px;font-size:11px;color:var(--ink-4)}
.dpx .dpx-side .footer .av{width:30px;height:30px;border-radius:50%;background:var(--grad-ink);color:#fafaf6;display:flex;align-items:center;justify-content:center;font-weight:600;font-size:12px}
.dpx .dpx-side .footer .who .nm{font-weight:600;color:var(--ink);font-size:12px}
.dpx .dpx-side .footer .who .em{font-size:10px;color:var(--ink-mute)}

/* ══ MAIN / TOPBAR ══ */
.dpx .dpx-main{min-width:0;height:100vh;overflow-y:auto;display:flex;flex-direction:column}
.dpx .dpx-topbar{background:var(--surface-2);border-bottom:1px solid var(--hairline);padding:14px 40px;display:flex;align-items:center;gap:16px;position:sticky;top:0;z-index:10}
.dpx .dpx-topbar h1{font:600 17px var(--sans);color:var(--ink);letter-spacing:-.3px}
.dpx .dpx-content{flex:1;padding:32px 40px 64px}

/* ══ PAGE HEAD ══ */
.dpx .dpx-page-hd{margin-bottom:30px}
.dpx .dpx-page-hd .eyebrow{font:500 11px var(--sans);text-transform:uppercase;letter-spacing:2.2px;color:var(--ink-mute);margin-bottom:12px;display:inline-flex;align-items:center;gap:10px}
.dpx .dpx-page-hd .eyebrow::before{content:"";width:18px;height:1px;background:var(--ink-3)}
.dpx .dpx-page-hd .ttl{font:600 40px/1.05 var(--sans);color:var(--ink);letter-spacing:-1.3px}
.dpx .dpx-page-hd .sub{margin-top:10px;font-size:15px;color:var(--ink-4)}

/* ══ KPI CARDS ══ */
.dpx .dpx-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:18px;margin-bottom:32px}
.dpx .dpx-kpi{background:var(--surface-2);border-radius:20px;padding:26px 28px;box-shadow:var(--shadow-card);transition:transform .25s ease,box-shadow .25s ease}
.dpx .dpx-kpi:hover{transform:translateY(-3px);box-shadow:var(--shadow-hover)}
.dpx .dpx-kpi .lbl{font:500 10.5px var(--sans);text-transform:uppercase;letter-spacing:1.4px;color:var(--ink-mute);margin-bottom:12px}
.dpx .dpx-kpi .v{font:600 34px/1 var(--sans);letter-spacing:-1px;color:var(--ink);font-variant-numeric:tabular-nums}
.dpx .dpx-kpi .sub{font:500 12px var(--sans);color:var(--ink-mute);margin-top:12px}

/* ══ CARDS / TABLES ══ */
.dpx .dpx-card{background:var(--surface-2);border-radius:22px;box-shadow:var(--shadow-card)}
.dpx .dpx-card-hd{padding:20px 24px 0;margin-bottom:2px}
.dpx .dpx-card-hd .ttl{font:600 16px var(--sans);color:var(--ink);letter-spacing:-.25px}
.dpx .dpx-card-body{padding:16px 24px 22px}
.dpx table{width:100%;border-collapse:collapse}
.dpx table th{font:500 10.5px var(--sans);text-transform:uppercase;letter-spacing:1.2px;color:var(--ink-mute);border-bottom:1px solid var(--hairline);padding:10px 12px;text-align:left}
.dpx table td{padding:11px 12px;border-bottom:1px solid var(--hairline);color:var(--ink-3)}
.dpx table tbody tr:hover{background:rgba(10,10,10,0.025)}
.dpx .pill{border-radius:999px;font:500 11px var(--sans);padding:3px 10px;display:inline-block}
```

- [ ] **Step 3: Write the shared shell include**

`upande_dev_tools/templates/includes/dev_portal_shell.html`:

```html
<link href="/assets/upande_dev_tools/css/dev-portal.css" rel="stylesheet">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600;9..144,700&family=Poppins:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">

<div class="dpx">
	<aside class="dpx-side">
		<a class="brand" href="{{ frappe.utils.get_url() }}">
			<span class="name">Upande Dev Tools<small>Dev Portal</small></span>
		</a>
		<nav class="nav">
			{% set nav_items = get_nav_items() %}
			{% set ns = namespace(last_group="") %}
			{% for item in nav_items %}
				{% if item.nav_group != ns.last_group %}
					<span class="group-lbl">{{ item.nav_group }}</span>
					{% set ns.last_group = item.nav_group %}
				{% endif %}
				<a class="nav-item{% if item.route == active_route %} active{% endif %}" href="/{{ item.route }}">
					<span>{{ item.title }}</span>
				</a>
			{% endfor %}
		</nav>
		<div class="footer">
			<span class="av">{{ frappe.utils.get_fullname(frappe.session.user)[0] | upper }}</span>
			<div class="who">
				<div class="nm">{{ frappe.utils.get_fullname(frappe.session.user) }}</div>
				<div class="em">{{ frappe.session.user }}</div>
			</div>
		</div>
	</aside>
	<main class="dpx-main">
		<div class="dpx-topbar">
			<h1>{{ page_title }}</h1>
		</div>
		<div class="dpx-content">
			{% block dpx_content %}{% endblock %}
		</div>
	</main>
</div>
```

- [ ] **Step 4: Expose `get_nav_items` as a Jinja global**

In `upande_dev_tools/hooks.py`, replace the commented-out `# jinja = {...}` block with:

```python
jinja = {
	"methods": ["upande_dev_tools.portal.get_nav_items"],
}
```

- [ ] **Step 5: Migrate and verify**

Run: `bench --site <site> migrate`

Verify by running `bench --site <site> console` and confirming the Jinja environment resolves the method:

```python
import frappe
frappe.init(site="<site>")
frappe.connect()
from frappe.utils.jinja import get_jenv
assert "get_nav_items" in get_jenv().globals
```

This task has no automated test beyond the above — a CSS file and an unused-until-Task-5/6 Jinja include have no behavior to unit test; `bench migrate` completing and the Jinja global resolving are the correctness signals, matching how Phase 1 verified its workspace-JSON tasks.

- [ ] **Step 6: Commit**

```bash
git add upande_dev_tools/public/css/dev-portal.css upande_dev_tools/templates/includes/dev_portal_shell.html upande_dev_tools/hooks.py
git commit -m "feat: add shared portal shell (CSS + Jinja include)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: The settings page

**Files:**
- Create: `upande_dev_tools/www/__init__.py` (this app has no `www/` folder yet — `frappe/www/__init__.py` confirms Frappe's own `www/` is a proper Python package, not just a template directory)
- Create: `upande_dev_tools/www/dev-portal-settings.html`
- Create: `upande_dev_tools/www/dev_portal_settings.py`
- Create: `upande_dev_tools/api/dev_portal_settings.py`
- Test: `upande_dev_tools/tests/test_dev_portal_settings_api.py`

**Interfaces:**
- Consumes: `enforce_page_access` (Task 2), `dev_portal_shell.html` (Task 4), `Dev Portal Page` + `Has Role` (Task 1).
- Produces: the `/dev-portal-settings` page itself, and two whitelisted functions (`get_registered_pages`, `update_page_roles`) the page's own JS calls.

- [ ] **Step 1: Create the package file**

`upande_dev_tools/www/__init__.py` — empty file.

- [ ] **Step 2: Write the failing tests**

`upande_dev_tools/tests/test_dev_portal_settings_api.py`:

```python
# Copyright (c) 2026, Upande Limited

import frappe
from frappe.tests import IntegrationTestCase

from upande_dev_tools.api.dev_portal_settings import get_registered_pages, update_page_roles


class IntegrationTestDevPortalSettingsApi(IntegrationTestCase):
	def _make_user(self, email: str, roles: list[str]) -> str:
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Test", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		user = frappe.get_doc("User", email)
		if roles:
			user.add_roles(*roles)
		return email

	def _make_page(self, route: str, roles: list[str]) -> str:
		if frappe.db.exists("Dev Portal Page", route):
			frappe.delete_doc("Dev Portal Page", route, ignore_permissions=True, force=True)
		return (
			frappe.get_doc(
				{
					"doctype": "Dev Portal Page",
					"route": route,
					"title": route,
					"nav_group": "Test",
					"allowed_roles": [{"role": role} for role in roles],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_get_registered_pages_requires_both_roles(self) -> None:
		dev_only = self._make_user("settings-dev-only@example.test", ["Dev Team"])
		frappe.set_user(dev_only)
		try:
			with self.assertRaises(frappe.PermissionError):
				get_registered_pages()
		finally:
			frappe.set_user("Administrator")

	def test_get_registered_pages_lists_pages_for_dual_role_user(self) -> None:
		self._make_page("settings-list-test", ["Dev Team"])
		both = self._make_user("settings-both@example.test", ["Dev Team", "System Manager"])
		frappe.set_user(both)
		try:
			pages = get_registered_pages()
		finally:
			frappe.set_user("Administrator")
		self.assertIn("settings-list-test", [p["route"] for p in pages])

	def test_update_page_roles_requires_both_roles(self) -> None:
		self._make_page("settings-update-guard", ["Dev Team"])
		dev_only = self._make_user("settings-update-dev-only@example.test", ["Dev Team"])
		frappe.set_user(dev_only)
		try:
			with self.assertRaises(frappe.PermissionError):
				update_page_roles(route="settings-update-guard", roles=["Projects Manager"])
		finally:
			frappe.set_user("Administrator")

	def test_update_page_roles_replaces_allowed_roles(self) -> None:
		self._make_page("settings-update-test", ["Dev Team"])
		both = self._make_user("settings-update-both@example.test", ["Dev Team", "System Manager"])
		frappe.set_user(both)
		try:
			update_page_roles(route="settings-update-test", roles=["Projects Manager"])
		finally:
			frappe.set_user("Administrator")

		doc = frappe.get_doc("Dev Portal Page", "settings-update-test")
		self.assertEqual([row.role for row in doc.allowed_roles], ["Projects Manager"])
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `bench --site <site> run-tests --app upande_dev_tools --module upande_dev_tools.tests.test_dev_portal_settings_api`
Expected: FAIL — `upande_dev_tools.api.dev_portal_settings` doesn't exist yet.

- [ ] **Step 4: Implement the API**

`upande_dev_tools/api/dev_portal_settings.py`:

```python
import frappe
from frappe import _


def _require_dual_role(role_a: str, role_b: str) -> None:
	roles = set(frappe.get_roles())
	if not ({role_a, role_b} <= roles):
		frappe.throw(_("Not permitted."), frappe.PermissionError)


@frappe.whitelist()
def get_registered_pages() -> list[dict]:
	_require_dual_role("Dev Team", "System Manager")

	pages = frappe.get_all(
		"Dev Portal Page",
		fields=["name", "route", "title", "nav_group", "sort_order", "require_all_roles"],
		order_by="nav_group asc, sort_order asc, title asc",
	)
	role_rows = frappe.get_all(
		"Has Role",
		filters={"parent": ["in", [page.name for page in pages]], "parenttype": "Dev Portal Page"},
		fields=["parent", "role"],
	)
	roles_by_page: dict[str, list[str]] = {}
	for row in role_rows:
		roles_by_page.setdefault(row.parent, []).append(row.role)

	for page in pages:
		page["allowed_roles"] = roles_by_page.get(page.name, [])
	return pages


@frappe.whitelist()
def update_page_roles(route: str, roles: list[str] | str, require_all_roles: bool | int = False) -> dict:
	_require_dual_role("Dev Team", "System Manager")

	if isinstance(roles, str):
		roles = frappe.parse_json(roles)

	doc = frappe.get_doc("Dev Portal Page", route)
	doc.allowed_roles = []
	for role in roles:
		doc.append("allowed_roles", {"role": role})
	doc.require_all_roles = 1 if int(require_all_roles) else 0
	doc.save(ignore_permissions=True)
	return doc.as_dict()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `bench --site <site> run-tests --app upande_dev_tools --module upande_dev_tools.tests.test_dev_portal_settings_api`
Expected: PASS

- [ ] **Step 6: Write the page controller and template**

`upande_dev_tools/www/dev_portal_settings.py`:

```python
# Copyright (c) 2026, shadrack@upande.com and contributors
# For license information, please see license.txt

import frappe

from upande_dev_tools.portal import enforce_page_access

no_cache = 1


def get_context(context):
	enforce_page_access("dev-portal-settings")
	context.no_cache = 1
	context.page_title = "Settings"
	context.active_route = "dev-portal-settings"
	context.csrf_token = frappe.sessions.get_csrf_token()
	return context
```

`upande_dev_tools/www/dev-portal-settings.html`:

```html
{% extends "templates/web.html" %}
{% block page_content %}
{% raw %}
{% include "upande_dev_tools/templates/includes/dev_portal_shell.html" %}
{% endraw %}
<div class="dpx-page-hd">
	<div class="eyebrow">Admin</div>
	<div class="ttl">Portal Pages</div>
	<div class="sub">Choose which roles can see each page. Dev Team + System Manager only.</div>
</div>
<div class="dpx-card">
	<div class="dpx-card-hd"><div class="ttl">Registered Pages</div></div>
	<div class="dpx-card-body">
		<table id="dps-table">
			<thead>
				<tr><th>Page</th><th>Nav Group</th><th>Allowed Roles</th><th>Require All</th><th></th></tr>
			</thead>
			<tbody></tbody>
		</table>
	</div>
</div>
<script>
frappe.ready(function() {
	frappe.call({method: "upande_dev_tools.api.dev_portal_settings.get_registered_pages"}).then(function(r) {
		var tbody = document.querySelector("#dps-table tbody");
		(r.message || []).forEach(function(page) {
			var tr = document.createElement("tr");
			tr.innerHTML =
				"<td>" + page.title + " <span class=\"pill\">/" + page.route + "</span></td>" +
				"<td>" + page.nav_group + "</td>" +
				"<td><input type=\"text\" class=\"dps-roles\" value=\"" + page.allowed_roles.join(", ") + "\"></td>" +
				"<td><input type=\"checkbox\" class=\"dps-require-all\"" + (page.require_all_roles ? " checked" : "") + "></td>" +
				"<td><button class=\"dps-save\">Save</button></td>";
			tr.querySelector(".dps-save").addEventListener("click", function() {
				var roles = tr.querySelector(".dps-roles").value.split(",").map(function(s) { return s.trim(); }).filter(Boolean);
				var requireAll = tr.querySelector(".dps-require-all").checked;
				frappe.call({
					method: "upande_dev_tools.api.dev_portal_settings.update_page_roles",
					args: {route: page.route, roles: roles, require_all_roles: requireAll ? 1 : 0}
				});
			});
			tbody.appendChild(tr);
		});
	});
});
</script>
{% endblock %}
```

- [ ] **Step 7: Migrate and verify**

Run: `bench --site <site> migrate`

Verify by visiting `/dev-portal-settings` as a user with both `Dev Team` and `System Manager` (should render the page listing) and as a user with only one of the two roles (should redirect quietly to their own home route) — a manual/visual check, since browser-rendered JS behavior isn't covered by the Python integration tests above (those cover the API layer and `enforce_page_access`, which are the parts with real logic).

- [ ] **Step 8: Commit**

```bash
ruff format upande_dev_tools/api/dev_portal_settings.py upande_dev_tools/www/dev_portal_settings.py upande_dev_tools/tests/test_dev_portal_settings_api.py
git add upande_dev_tools/www/dev-portal-settings.html upande_dev_tools/www/dev_portal_settings.py upande_dev_tools/api/dev_portal_settings.py upande_dev_tools/tests/test_dev_portal_settings_api.py
git commit -m "feat: add the dual-role-gated settings page

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: Vanity entry route (`/dev-tools`)

**Files:**
- Create: `upande_dev_tools/www/dev-tools.html`
- Create: `upande_dev_tools/www/dev_tools.py`
- Test: `upande_dev_tools/tests/test_portal.py` (extend)

**Interfaces:**
- Consumes: `resolve_home_route` (Task 2).
- Produces: `/dev-tools`, a single bookmarkable URL that immediately redirects any visitor to their own dashboard.

- [ ] **Step 1: Write the failing test**

Append to `upande_dev_tools/tests/test_portal.py` (add `from upande_dev_tools.www.dev_tools import get_context` to the imports — this is the one place in this plan that imports directly from a `www` module, since it's the unit under test):

```python
	def test_dev_tools_entry_redirects_to_resolved_home(self) -> None:
		dev = self._make_user("dev-tools-entry@example.test", ["Dev Team"])
		frappe.set_user(dev)
		try:
			with self.assertRaises(frappe.Redirect):
				get_context({})
			self.assertEqual(frappe.local.flags.redirect_location, "/dev-dashboard")
		finally:
			frappe.set_user("Administrator")
			frappe.local.flags.redirect_location = None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bench --site <site> run-tests --app upande_dev_tools --module upande_dev_tools.tests.test_portal`
Expected: FAIL — `upande_dev_tools.www.dev_tools` doesn't exist yet.

- [ ] **Step 3: Implement**

`upande_dev_tools/www/dev_tools.py`:

```python
# Copyright (c) 2026, shadrack@upande.com and contributors
# For license information, please see license.txt

import frappe

from upande_dev_tools.portal import resolve_home_route

no_cache = 1


def get_context(context):
	frappe.local.flags.redirect_location = resolve_home_route()
	raise frappe.Redirect
```

`upande_dev_tools/www/dev-tools.html` (never actually rendered — `get_context` always redirects first — but Frappe's router expects a template file to exist for the route):

```html
{% extends "templates/web.html" %}
{% block page_content %}
{% endblock %}
```

- [ ] **Step 4: Migrate and run tests**

Run: `bench --site <site> migrate`
Run: `bench --site <site> run-tests --app upande_dev_tools --module upande_dev_tools.tests.test_portal`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
ruff format upande_dev_tools/www/dev_tools.py upande_dev_tools/tests/test_portal.py
git add upande_dev_tools/www/dev-tools.html upande_dev_tools/www/dev_tools.py upande_dev_tools/tests/test_portal.py
git commit -m "feat: add /dev-tools vanity entry route

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Sub-project 1 acceptance check

After Task 6, run every module this plan touched:

```bash
bench --site <site> run-tests --app upande_dev_tools --module upande_dev_tools.upande_dev_tools.doctype.dev_portal_page.test_dev_portal_page
bench --site <site> run-tests --app upande_dev_tools --module upande_dev_tools.tests.test_portal
bench --site <site> run-tests --app upande_dev_tools --module upande_dev_tools.tests.test_dev_portal_settings_api
bench --site <site> run-tests --app upande_dev_tools --module upande_dev_tools.tests.test_requests_api
bench --site <site> run-tests --app upande_dev_tools --module upande_dev_tools.tests.test_deployments_api
```

Expected: all pass. At this point: `/dev-tools` sends any logged-in visitor to their own dashboard's route (even though Sub-projects 2-4 haven't built those pages yet — the redirect target is a plain string, not a dependency); `/dev-portal-settings` renders for anyone holding both `Dev Team` and `System Manager`, listing every registered page with its roles editable, and quietly redirects anyone else away; and any future `www` page just needs its own `enforce_page_access(route)` call plus a `register_dev_portal_page(...)` registration to gain identical chrome, automatic sidebar placement, and role-gated access with zero new plumbing.
