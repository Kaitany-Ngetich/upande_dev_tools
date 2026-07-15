// Copyright (c) 2026, Upande Limited
// Selective Customization Export for Customize Form

frappe.ui.form.on("Customize Form", {
	refresh(frm) {
		if (!frappe.boot.developer_mode || !frm.doc.doc_type) {
			return;
		}

		/*
		 * The standard Customize Form script adds its Export Customizations
		 * button during refresh. Delay our replacement until that refresh
		 * handler has finished.
		 */
		setTimeout(() => {
			frm.remove_custom_button(
				__("Export Customizations"),
				__("Actions")
			);

			frm.add_custom_button(
				__("Export Customizations"),
				() => show_selective_export_dialog(frm),
				__("Actions")
			);
		}, 0);
	},
});


async function show_selective_export_dialog(frm) {
	const apps = await frappe.xcall(
		"upande_dev_tools.api.customization_exporter.get_exportable_apps"
	);

	if (!apps?.length) {
		frappe.msgprint(
			__("No installed applications with exportable modules were found.")
		);
		return;
	}

	let dialog;

	dialog = new frappe.ui.Dialog({
		title: __("Export Selected Custom Fields"),
		size: "large",

		fields: [
			{
				fieldtype: "HTML",
				fieldname: "instructions",
				options: `
					<div class="alert alert-info">
						${__(
							"Select the target application and module, then choose the exact Custom Fields that should be written to that module's customization file."
						)}
					</div>
				`,
			},
			{
				fieldtype: "Select",
				fieldname: "app",
				label: __("App"),
				options: ["", ...apps].join("\n"),
				reqd: 1,

				change() {
					dialog.set_value("module", "");
					dialog.set_value("custom_fields", []);

					dialog.fields_dict.module.refresh();
					dialog.fields_dict.custom_fields.refresh();
				},
			},
			{
				fieldtype: "Link",
				fieldname: "module",
				label: __("Module"),
				options: "Module Def",
				reqd: 1,

				get_query() {
					const app = dialog?.get_value("app");

					return {
						filters: {
							app_name: app || "",
						},
					};
				},

				change() {
					dialog.set_value("custom_fields", []);
					dialog.fields_dict.custom_fields.refresh();
				},
			},
			{
				fieldtype: "Section Break",
				label: __("Custom Fields"),
			},
			{
				fieldtype: "MultiSelectList",
				fieldname: "custom_fields",
				label: __("Custom Fields to Export"),
				reqd: 1,

				description: __(
					"Only Custom Fields belonging to the selected DocType and Module are displayed."
				),

				async get_data(txt) {
					const module = dialog?.get_value("module");

					if (!module || !frm.doc.doc_type) {
						return [];
					}

					return (
						(await frappe.xcall(
							"upande_dev_tools.api.customization_exporter.get_custom_field_options",
							{
								doctype: frm.doc.doc_type,
								module,
								txt: txt || "",
							}
						)) || []
					);
				},
			},
			{
				fieldtype: "Section Break",
				label: __("Export Options"),
			},
			{
				fieldtype: "Check",
				fieldname: "sync_on_migrate",
				label: __("Sync on Migrate"),
				default: 1,
			},
			{
				fieldtype: "Check",
				fieldname: "with_permissions",
				label: __("Export Custom Permissions"),
				default: 0,

				description: __(
					"Custom permissions do not belong to individual Custom Fields. When enabled, all custom permissions for this DocType will be exported."
				),
			},
			{
				fieldtype: "HTML",
				fieldname: "warning",
				options: `
					<div class="alert alert-warning">
						<strong>${__("Important")}:</strong>
						${__(
							"The selected Custom Fields will be added or updated while existing customizations in the same module and DocType JSON file are preserved."
						)}
					</div>
				`,
			},
		],

		primary_action_label: __("Export Selected Fields"),

		async primary_action(values) {
			const selected_fields = values.custom_fields || [];

			if (!selected_fields.length) {
				frappe.throw(
					__("Select at least one Custom Field to export.")
				);
			}

			const primary_button = dialog.get_primary_btn();
			primary_button.prop("disabled", true);

			try {
				const result = await frappe.xcall(
					"upande_dev_tools.api.customization_exporter.export_selected_customizations",
					{
						app: values.app,
						module: values.module,
						doctype: frm.doc.doc_type,
						custom_fields: selected_fields,
						sync_on_migrate: values.sync_on_migrate,
						with_permissions: values.with_permissions,
					}
				);

				dialog.hide();

				frappe.msgprint({
					title: __("Export Completed"),
					indicator: "green",
					message: `
						<p>
							${__(
								"{0} Custom Field(s) exported successfully.",
								[result.custom_field_count]
							)}
						</p>

						<p>
							<strong>${__("App")}:</strong>
							${frappe.utils.escape_html(result.app)}
						</p>

						<p>
							<strong>${__("Module")}:</strong>
							${frappe.utils.escape_html(result.module)}
						</p>

						<p>
							<strong>${__("File")}:</strong><br>
							<code>${frappe.utils.escape_html(result.path)}</code>
						</p>
					`,
				});
			} finally {
				primary_button.prop("disabled", false);
			}
		},
	});

	dialog.show();
}
