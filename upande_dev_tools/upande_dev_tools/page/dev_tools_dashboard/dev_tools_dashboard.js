frappe.pages['dev_tools_dashboard'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Tools Dashboard',
		single_column: true
	});
}