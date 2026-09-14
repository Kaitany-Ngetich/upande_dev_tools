app_name = "upande_dev_tools"
app_title = "Upande Dev Tools"
app_publisher = "shadrack@upande.com"
app_description = "Internal developer tools for Upande workflows"
app_email = "dev@upande.com"
app_license = "mit"

# Apps
# ------------------

required_apps = ["erpnext"]

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "upande_dev_tools",
# 		"logo": "/assets/upande_dev_tools/logo.png",
# 		"title": "Upande Dev Tools",
# 		"route": "/upande_dev_tools",
# 		"has_permission": "upande_dev_tools.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/upande_dev_tools/css/upande_dev_tools.css"
# app_include_js = "/assets/upande_dev_tools/js/upande_dev_tools.js"

# include js, css files in header of web template
# web_include_css = "/assets/upande_dev_tools/css/upande_dev_tools.css"
# web_include_js = "/assets/upande_dev_tools/js/upande_dev_tools.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "upande_dev_tools/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "upande_dev_tools/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# website user home page (called by frappe.website.utils.get_home_page as
# frappe.get_attr(hook)(frappe.session.user) — this is what actually drives the
# post-login redirect, unlike the vanity /dev-tools route or the denied-access
# redirect, which are the only two callers of resolve_home_route before this hook)
get_website_user_home_page = "upande_dev_tools.portal.resolve_home_route"


def _pin_resolved_home_page_on_login(login_manager=None, **kwargs):
	"""`on_login` handler (registered below) - deliberately lives in this module, not
	portal.py, since this file is the one place a hook-collision workaround like this
	belongs.

	`get_website_user_home_page` above is Frappe's own hook for exactly this, but it is
	single-valued: frappe/website/utils.py's get_home_page_via_hooks() calls only the
	LAST app's registration for that hook name (`frappe.get_attr(home_page_method[-1])(...)`,
	not "first truthy result wins"). On this bench the `builder` app is installed after
	upande_dev_tools and also registers `get_website_user_home_page` (returning a falsy
	value whenever "Builder Settings".home_page is unset, which it is here) - so ours is
	silently shadowed and never even invoked. Confirmed live: a fresh login for a Dev
	Team/Projects Manager user came back with home_page "desk", not resolve_home_route's
	"/dev-dashboard"/"/pm-dashboard", until this handler was added.

	`on_login` doesn't have that problem: frappe/auth.py's LoginManager.run_trigger calls
	every app's registered handler, not just the last. And frappe/website/utils.py's
	get_home_page() checks `frappe.local.flags.home_page` before any role/hook/website-
	settings lookup, so pinning it here guarantees resolve_home_route's route wins
	regardless of what any other installed app does with the get_website_user_home_page
	hook name. frappe.session.user is not yet switched to the newly authenticated user
	when on_login fires (that happens later in the same login request, in make_session),
	so this uses login_manager.user - passed in by run_trigger - instead of
	resolve_home_route's own frappe.session.user default.
	"""
	import frappe

	from upande_dev_tools.portal import resolve_home_route

	if login_manager is None:
		return
	try:
		frappe.local.flags.home_page = resolve_home_route(login_manager.user)
	except Exception:
		# Never let a problem resolving this app's own home-route registry (e.g. mid-
		# migration, a missing Dev Portal Page row) break login sitewide for every app
		# on this bench - falling through to Frappe's normal home-page resolution is
		# always safe, this pin is a pure enhancement on top of it.
		frappe.log_error(title="upande_dev_tools: failed to pin resolved home page on login")


on_login = ["upande_dev_tools.hooks._pin_resolved_home_page_on_login"]

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
jinja = {
	"methods": [
		"upande_dev_tools.portal.get_nav_items",
		"upande_dev_tools.portal.resolve_home_route",
	],
}

# Installation
# ------------

# before_install = "upande_dev_tools.install.before_install"
# after_install = "upande_dev_tools.install.after_install"

after_install = "upande_dev_tools.setup.run_setup"
after_migrate = "upande_dev_tools.setup.run_setup"

# Uninstallation
# ------------

# before_uninstall = "upande_dev_tools.uninstall.before_uninstall"
# after_uninstall = "upande_dev_tools.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "upande_dev_tools.utils.before_app_install"
# after_app_install = "upande_dev_tools.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "upande_dev_tools.utils.before_app_uninstall"
# after_app_uninstall = "upande_dev_tools.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "upande_dev_tools.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "upande_dev_tools.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"upande_dev_tools.tasks.all"
# 	],
# 	"daily": [
# 		"upande_dev_tools.tasks.daily"
# 	],
# 	"hourly": [
# 		"upande_dev_tools.tasks.hourly"
# 	],
# 	"weekly": [
# 		"upande_dev_tools.tasks.weekly"
# 	],
# 	"monthly": [
# 		"upande_dev_tools.tasks.monthly"
# 	],
# }
# scheduler_events = {
#    "cron": {
#        "0 */4 * * *": [
#           "upande_dev_tools.backup.scheduler.run_code_backup"
#        ]
#    }
# }
# Testing
# -------

# before_tests = "upande_dev_tools.install.before_tests"

scheduler_events = {"cron": {"*/5 * * * *": ["upande_dev_tools.backup.scheduler.run_code_backup"]}}
# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "upande_dev_tools.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "upande_dev_tools.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "upande_dev_tools.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["upande_dev_tools.utils.before_request"]
# after_request = ["upande_dev_tools.utils.after_request"]

# Job Events
# ----------
# before_job = ["upande_dev_tools.utils.before_job"]
# after_job = ["upande_dev_tools.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"upande_dev_tools.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
export_python_type_annotations = True

# Require all whitelisted methods to have type annotations
require_type_annotated_api_methods = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

doctype_js = {
	"Customize Form": "public/js/customize_form_export.js",
}

fixtures = [
	{"doctype": "Role", "filters": [["name", "in", ["Dev Team"]]]},
	{
		"doctype": "Workflow State",
		"filters": [
			[
				"name",
				"in",
				[
					"Under Review",
					"Approved",
					"Rejected",
					"Deferred",
					"Scheduled",
					"In Progress",
					"Completed",
					"Requested",
					"Deployed",
					"Failed",
				],
			]
		],
	},
	{
		"doctype": "Workflow Action Master",
		"filters": [
			[
				"name",
				"in",
				[
					"Approve",
					"Reject",
					"Defer",
					"Reopen",
					"Schedule",
					"Promote Note",
					"Start Work",
					"Complete",
					"Start Deployment",
					"Mark Deployed",
					"Mark Failed",
					"Retry",
				],
			]
		],
	},
	{"doctype": "Workflow", "filters": [["name", "in", ["Request Review", "Deployment Review"]]]},
]
