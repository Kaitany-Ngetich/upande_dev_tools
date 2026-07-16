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

			frm.add_custom_button(
				__("View Current Customizations"),
				() => show_current_customizations_dialog(frm),
				__("Actions")
			);

			frm.add_custom_button(
				__("Reconcile Field Apps"),
				() => show_reconcile_dialog(frm),
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

	// Pre-select the fields already present in the chosen module's files, so the
	// developer sees what is already there, what is missing, and can uncheck
	// anything that belongs elsewhere.
	async function preselect_existing(dialog) {
		dialog._preselected = [];
		dialog.set_value("targets", []);

		const module = dialog.get_value("module");
		if (!module || !frm.doc.doc_type) {
			dialog.fields_dict.targets.refresh();
			return;
		}

		const [targets, current] = await Promise.all([
			frappe.xcall(
				"upande_dev_tools.api.customization_exporter.get_customization_targets",
				{ doctype: frm.doc.doc_type }
			),
			frappe.xcall(
				"upande_dev_tools.api.customization_exporter.get_current_customizations",
				{ module, doctype: frm.doc.doc_type }
			),
		]);

		const selectable = new Set((targets || []).map((t) => t.value));
		const existing = [];
		(current.files || []).forEach((file) =>
			(file.fields || []).forEach((field) => {
				if (selectable.has(field.value)) {
					existing.push(field.value);
				}
			})
		);

		dialog._preselected = existing;
		dialog.set_value("targets", existing);
		dialog.fields_dict.targets.refresh();
	}

	dialog = new frappe.ui.Dialog({
		title: __("Export Customizations"),
		size: "large",

		fields: [
			{
				fieldtype: "HTML",
				fieldname: "dup_banner",
				options: "",
			},
			{
				fieldtype: "Select",
				fieldname: "app",
				label: __("App"),
				options: ["", ...apps].join("\n"),
				reqd: 1,

				change() {
					dialog.set_value("module", "");
					dialog.fields_dict.module.refresh();
					preselect_existing(dialog);
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
					return { filters: { app_name: app || "" } };
				},

				change() {
					preselect_existing(dialog);
				},
			},
			{
				fieldtype: "Section Break",
				label: __("Fields"),
			},
			{
				fieldtype: "MultiSelectList",
				fieldname: "targets",
				label: __("Fields to keep in this app"),

				description: __(
					"Checked fields are already exported to this app. Add any that are missing, and remove any that belong to a different app. Saving updates the app's files to match this selection. Covers the DocType and its child tables."
				),

				async get_data(txt) {
					if (!frm.doc.doc_type) {
						return [];
					}

					const rows =
						(await frappe.xcall(
							"upande_dev_tools.api.customization_exporter.get_customization_targets",
							{ doctype: frm.doc.doc_type }
						)) || [];

					const needle = (txt || "").toLowerCase();
					return needle
						? rows.filter((r) =>
								(r.description || r.value)
									.toLowerCase()
									.includes(needle)
						  )
						: rows;
				},
			},
			{
				fieldtype: "Section Break",
				label: __("Also include"),
			},
			{
				fieldtype: "Check",
				fieldname: "include_links",
				label: __("DocType Links (Connections)"),
				default: 0,
			},
			{
				fieldtype: "Check",
				fieldname: "include_doctype_property_setters",
				label: __("DocType-level property settings"),
				default: 0,

				description: __(
					"Sort order, title field, search fields, and other DocType-level settings."
				),
			},
			{
				fieldtype: "Check",
				fieldname: "with_permissions",
				label: __("Custom permissions"),
				default: 0,

				description: __(
					"Custom permissions are force-synced on every migrate, overriding other customizations."
				),
			},
			{
				fieldtype: "Check",
				fieldname: "sync_on_migrate",
				label: __("Sync on migrate"),
				default: 1,
			},
		],

		primary_action_label: __("Save"),

		async primary_action(values) {
			if (dialog._has_duplicates) {
				frappe.msgprint({
					title: __("Resolve Duplicates First"),
					indicator: "red",
					message: __(
						"Some fields exist in more than one app. Use Reconcile Field Apps to fix this before exporting."
					),
				});
				return;
			}

			const selected = values.targets || [];
			const preselected = dialog._preselected || [];
			const removed = preselected.filter((v) => !selected.includes(v));

			if (!selected.length && !removed.length) {
				frappe.msgprint(__("Select at least one field to export."));
				return;
			}

			const run = async () => {
				const primary_button = dialog.get_primary_btn();
				primary_button.prop("disabled", true);

				try {
					const result = await frappe.xcall(
						"upande_dev_tools.api.customization_exporter.export_selected_customizations",
						{
							app: values.app,
							module: values.module,
							doctype: frm.doc.doc_type,
							targets: selected,
							include_links: values.include_links,
							include_doctype_property_setters:
								values.include_doctype_property_setters,
							with_permissions: values.with_permissions,
							sync_on_migrate: values.sync_on_migrate,
							remove_unselected: 1,
						}
					);

					dialog.hide();
					show_export_result(result);
				} finally {
					primary_button.prop("disabled", false);
				}
			};

			if (removed.length) {
				frappe.confirm(
					__(
						"Remove {0} field(s) from app {1} and save the rest?",
						[removed.length, values.app]
					),
					run
				);
			} else {
				run();
			}
		},
	});

	dialog.show();
	check_export_duplicates(dialog, frm);
}


async function check_export_duplicates(dialog, frm) {
	const banner = dialog.fields_dict.dup_banner.$wrapper;
	const data = await frappe.xcall(
		"upande_dev_tools.api.customization_exporter.get_duplicate_fields",
		{ doctype: frm.doc.doc_type }
	);

	dialog._has_duplicates = data.count > 0;

	if (!data.count) {
		banner.empty();
		dialog.get_primary_btn().prop("disabled", false);
		return;
	}

	const items = data.duplicates
		.map(
			(d) =>
				`<li><b>${frappe.utils.escape_html(d.label)}</b>
					<span class="text-muted">(${frappe.utils.escape_html(
						d.fieldname
					)})</span> — ${d.apps
					.map((a) => frappe.utils.escape_html(a))
					.join(", ")}</li>`
		)
		.join("");

	banner.html(`
		<div class="alert alert-danger" style="margin-bottom:12px;">
			<div style="font-weight:600; margin-bottom:6px;">
				${__("{0} field(s) exist in more than one app", [data.count])}
			</div>
			<ul style="margin:0 0 8px 18px; padding:0;">${items}</ul>
			<button class="btn btn-xs btn-primary udt-open-reconcile">
				${__("Reconcile Field Apps")}
			</button>
		</div>
	`);

	dialog.get_primary_btn().prop("disabled", true);

	banner.find(".udt-open-reconcile").on("click", () => {
		dialog.hide();
		show_reconcile_dialog(frm);
	});
}


function show_export_result(result) {
	const rows = (result.files || [])
		.map(
			(f) =>
				`<tr>
					<td>${frappe.utils.escape_html(f.doctype)}</td>
					<td>${f.file_action}</td>
					<td>${f.custom_field_count}</td>
					<td>${f.property_setter_count}</td>
					<td><code>${frappe.utils.escape_html(f.path)}</code></td>
				</tr>`
		)
		.join("");

	frappe.msgprint({
		title: __("Customizations Saved"),
		indicator: "green",
		message: `
			<p>${__("{0} file(s) updated in app {1}.", [
				result.total_files,
				frappe.utils.escape_html(result.app),
			])}</p>
			<table class="table table-bordered">
				<thead><tr>
					<th>${__("DocType")}</th>
					<th>${__("Action")}</th>
					<th>${__("Fields")}</th>
					<th>${__("Prop. Setters")}</th>
					<th>${__("File")}</th>
				</tr></thead>
				<tbody>${rows}</tbody>
			</table>
		`,
	});
}


async function show_current_customizations_dialog(frm) {
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

	async function load_current(dialog) {
		const module = dialog?.get_value("module");
		const wrapper = dialog.fields_dict.current_list.$wrapper;

		if (!module || !frm.doc.doc_type) {
			wrapper.html(
				`<div class="text-muted">${__(
					"Select an app and module to view its current customizations."
				)}</div>`
			);
			return;
		}

		wrapper.html(`<div class="text-muted">${__("Loading…")}</div>`);

		const data = await frappe.xcall(
			"upande_dev_tools.api.customization_exporter.get_current_customizations",
			{ module, doctype: frm.doc.doc_type }
		);

		render_current_customizations(wrapper, data);
	}

	dialog = new frappe.ui.Dialog({
		title: __("Current Customizations"),
		size: "large",

		fields: [
			{
				fieldtype: "Select",
				fieldname: "app",
				label: __("App"),
				options: ["", ...apps].join("\n"),
				reqd: 1,

				change() {
					dialog.set_value("module", "");
					dialog.fields_dict.module.refresh();
					load_current(dialog);
				},
			},
			{
				fieldtype: "Column Break",
			},
			{
				fieldtype: "Link",
				fieldname: "module",
				label: __("Module"),
				options: "Module Def",
				reqd: 1,

				get_query() {
					const app = dialog?.get_value("app");
					return { filters: { app_name: app || "" } };
				},

				change() {
					load_current(dialog);
				},
			},
			{
				fieldtype: "Section Break",
			},
			{
				fieldtype: "HTML",
				fieldname: "current_list",
				options: `<p class="text-muted">${__(
					"Select an app and module to view its saved customizations."
				)}</p>`,
			},
		],

		primary_action_label: __("Save Changes"),

		async primary_action() {
			const wrapper = dialog.fields_dict.current_list.$wrapper;
			const all_boxes = wrapper.find("input.udt-cust-field");

			if (!all_boxes.length) {
				frappe.msgprint(
					__("There are no field customizations to update for this module.")
				);
				return;
			}

			const keep_targets = all_boxes
				.filter((_i, el) => el.checked)
				.map((_i, el) => el.getAttribute("data-target"))
				.get();

			const removed_count = all_boxes.length - keep_targets.length;

			if (!removed_count) {
				frappe.msgprint(__("Nothing to remove — all fields are still checked."));
				return;
			}

			frappe.confirm(
				__(
					"Remove {0} field(s) from the customization JSON file(s)? This cannot be undone from here.",
					[removed_count]
				),
				async () => {
					const primary_button = dialog.get_primary_btn();
					primary_button.prop("disabled", true);

					try {
						const result = await frappe.xcall(
							"upande_dev_tools.api.customization_exporter.update_current_customizations",
							{
								module: dialog.get_value("module"),
								doctype: frm.doc.doc_type,
								keep_targets,
							}
						);

						const rows = (result.results || [])
							.map(
								(r) =>
									`<tr>
										<td>${frappe.utils.escape_html(r.doctype)}</td>
										<td>${r.action}</td>
										<td>${r.removed_custom_fields}</td>
										<td>${r.removed_property_setters}</td>
									</tr>`
							)
							.join("");

						frappe.msgprint({
							title: __("Customizations Updated"),
							indicator: "green",
							message: `
								<p>${__("{0} custom field(s) removed.", [
									result.total_removed_custom_fields,
								])}</p>
								<table class="table table-bordered">
									<thead><tr>
										<th>${__("DocType")}</th>
										<th>${__("Action")}</th>
										<th>${__("Fields Removed")}</th>
										<th>${__("Prop. Setters Removed")}</th>
									</tr></thead>
									<tbody>${rows}</tbody>
								</table>
							`,
						});

						await load_current(dialog);
					} finally {
						primary_button.prop("disabled", false);
					}
				}
			);
		},
	});

	dialog.show();
}


function render_current_customizations(wrapper, data) {
	const files = (data && data.files) || [];
	const total_fields = files.reduce((n, f) => n + (f.fields || []).length, 0);

	if (!total_fields) {
		wrapper.html(
			`<p class="text-muted">${__(
				"No field customizations are saved for this DocType in the selected module."
			)}</p>`
		);
		return;
	}

	const sections = files
		.filter((file) => file.fields.length || file_has_preserved(file))
		.map((file) => {
			const heading = file.is_child
				? `${frappe.utils.escape_html(file.doctype)} <span class="text-muted">· ${__(
						"child table"
				  )}</span>`
				: frappe.utils.escape_html(file.doctype);

			const preserved = preserved_summary(file);
			const preserved_note = preserved
				? `<div class="text-muted small" style="margin-bottom:8px;">${__(
						"Also in file"
				  )}: ${preserved}</div>`
				: "";

			const rows = file.fields.length
				? file.fields
						.map((f) => {
							const meta = [];
							if (f.fieldtype) {
								meta.push(frappe.utils.escape_html(f.fieldtype));
							}
							if (f.property_setter_count) {
								meta.push(
									__("{0} property setter(s)", [
										f.property_setter_count,
									])
								);
							}
							const meta_text = meta.length
								? `<span class="text-muted">${meta.join(", ")}</span>`
								: "";
							return `
								<label class="udt-field-row" style="display:flex; gap:10px; align-items:center; padding:6px 4px; border-top:1px solid var(--border-color); margin:0; font-weight:normal; cursor:pointer;">
									<input type="checkbox" class="udt-cust-field" checked
										data-target="${frappe.utils.escape_html(f.value)}"
										style="margin:0;">
									<span style="flex:1;">${frappe.utils.escape_html(f.label)}</span>
									<code style="flex:1;">${frappe.utils.escape_html(f.fieldname)}</code>
									<span style="flex:1; text-align:right;">${meta_text}</span>
								</label>`;
						})
						.join("")
				: "";

			return `
				<div style="margin-bottom:20px;">
					<div style="font-weight:600; margin-bottom:2px;">${heading}</div>
					<div class="text-muted small" style="margin-bottom:6px;">${frappe.utils.escape_html(
						file.path
					)}</div>
					${preserved_note}
					<div>${rows}</div>
				</div>`;
		})
		.join("");

	wrapper.html(`
		<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
			<span class="text-muted small">${__(
				"Uncheck a field to remove it from the file on Save. The Custom Field stays in the database."
			)}</span>
			<span>
				<a class="udt-check-all">${__("Select all")}</a>
				&nbsp;·&nbsp;
				<a class="udt-uncheck-all">${__("Clear all")}</a>
			</span>
		</div>
		${sections}
	`);

	wrapper.find(".udt-check-all").on("click", (e) => {
		e.preventDefault();
		wrapper.find("input.udt-cust-field").prop("checked", true);
	});
	wrapper.find(".udt-uncheck-all").on("click", (e) => {
		e.preventDefault();
		wrapper.find("input.udt-cust-field").prop("checked", false);
	});
}


function file_has_preserved(file) {
	return (
		file.doctype_property_setter_count ||
		file.link_count ||
		file.custom_perm_count
	);
}


function preserved_summary(file) {
	const parts = [];
	if (file.doctype_property_setter_count) {
		parts.push(
			__("{0} DocType property setter(s)", [
				file.doctype_property_setter_count,
			])
		);
	}
	if (file.link_count) {
		parts.push(__("{0} link(s)", [file.link_count]));
	}
	if (file.custom_perm_count) {
		parts.push(__("{0} permission(s)", [file.custom_perm_count]));
	}
	return parts.join(", ");
}


async function show_reconcile_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Reconcile Field Apps — {0}", [frm.doc.doc_type]),
		size: "extra-large",

		fields: [
			{
				fieldtype: "HTML",
				fieldname: "matrix",
				options: `<p class="text-muted">${__("Loading…")}</p>`,
			},
		],

		primary_action_label: __("Save"),

		async primary_action() {
			const wrapper = dialog.fields_dict.matrix.$wrapper;

			const unresolved = wrapper
				.find("tr.udt-field-row")
				.filter(
					(_i, tr) =>
						$(tr).find("input.udt-cell:checked").length > 1
				);

			if (unresolved.length) {
				frappe.msgprint({
					title: __("One App per Field"),
					indicator: "red",
					message: __(
						"{0} field(s) are still assigned to more than one app. Pick a single app (or none) for each highlighted row.",
						[unresolved.length]
					),
				});
				return;
			}

			const keep_map = {};
			wrapper.find("tr.udt-field-row").each((_i, tr) => {
				const row = $(tr);
				const target = row.attr("data-target");
				const original = (row.attr("data-original") || "")
					.split(",")
					.filter(Boolean);
				const checked = row
					.find("input.udt-cell:checked")
					.map((_j, el) => el.getAttribute("data-app"))
					.get();

				const changed =
					checked.length !== original.length ||
					checked.some((a) => !original.includes(a));

				if (changed) {
					keep_map[target] = checked[0] || "";
				}
			});

			if (!Object.keys(keep_map).length) {
				frappe.msgprint(__("No changes to save."));
				return;
			}

			const primary_button = dialog.get_primary_btn();
			primary_button.prop("disabled", true);

			try {
				const result = await frappe.xcall(
					"upande_dev_tools.api.customization_exporter.reconcile_field_apps",
					{ doctype: frm.doc.doc_type, keep_map }
				);

				frappe.show_alert({
					message: __("{0} field placement(s) removed.", [
						result.total_removed,
					]),
					indicator: "green",
				});

				await load_field_matrix(dialog, frm);
			} finally {
				primary_button.prop("disabled", false);
			}
		},
	});

	dialog.show();
	load_field_matrix(dialog, frm);
}


async function load_field_matrix(dialog, frm) {
	const wrapper = dialog.fields_dict.matrix.$wrapper;
	wrapper.html(`<p class="text-muted">${__("Loading…")}</p>`);

	const data = await frappe.xcall(
		"upande_dev_tools.api.customization_exporter.get_field_app_matrix",
		{ doctype: frm.doc.doc_type }
	);

	render_field_app_matrix(wrapper, data);
}


function render_field_app_matrix(wrapper, data) {
	const apps = data.apps || [];
	const fields = data.fields || [];

	if (!fields.length) {
		wrapper.html(
			`<p class="text-muted">${__(
				"No exported field customizations were found across installed apps for this DocType."
			)}</p>`
		);
		return;
	}

	if (!apps.length) {
		wrapper.html(
			`<p class="text-muted">${__("No apps contain these fields.")}</p>`
		);
		return;
	}

	const app_headers = apps
		.map(
			(a) =>
				`<th class="text-center" style="white-space:nowrap;">${frappe.utils.escape_html(
					a
				)}</th>`
		)
		.join("");

	let last_doctype = null;
	const body = fields
		.map((f) => {
			let group = "";
			if (f.doctype !== last_doctype) {
				last_doctype = f.doctype;
				group = `<tr class="udt-group"><td colspan="${
					apps.length + 1
				}" style="background:var(--subtle-fg,#f4f5f6); font-weight:600;">
					${frappe.utils.escape_html(f.doctype)}</td></tr>`;
			}

			const cells = apps
				.map((a) => {
					const present = f.apps.includes(a);
					return `<td class="text-center">
						<input type="checkbox" class="udt-cell"
							data-app="${frappe.utils.escape_html(a)}"
							${present ? "checked" : ""}>
					</td>`;
				})
				.join("");

			return `${group}
				<tr class="udt-field-row ${f.is_duplicate ? "udt-dupe" : ""}"
					data-target="${frappe.utils.escape_html(f.value)}"
					data-original="${frappe.utils.escape_html(f.apps.join(","))}">
					<td>
						<div>${frappe.utils.escape_html(f.label)}</div>
						<code class="text-muted">${frappe.utils.escape_html(f.fieldname)}</code>
					</td>
					${cells}
				</tr>`;
		})
		.join("");

	wrapper.html(`
		<div class="text-muted small" style="margin-bottom:8px;">
			${__(
				"Each field should belong to one app. Picking an app clears the others in that row; clear all to remove the field everywhere. Rows in red are still duplicated."
			)}
		</div>
		<div style="max-height:60vh; overflow:auto;">
			<table class="table table-bordered" style="margin:0;">
				<thead style="position:sticky; top:0; background:var(--fg-color,#fff); z-index:1;">
					<tr>
						<th style="min-width:220px;">${__("Field")}</th>
						${app_headers}
					</tr>
				</thead>
				<tbody>${body}</tbody>
			</table>
		</div>
	`);

	const paint = (row) => {
		const dupe = row.find("input.udt-cell:checked").length > 1;
		row.css("background", dupe ? "var(--red-50, #fdeaea)" : "");
	};

	wrapper.find("tr.udt-field-row").each((_i, tr) => paint($(tr)));

	wrapper.find("input.udt-cell").on("change", function () {
		const row = $(this).closest("tr.udt-field-row");
		if (this.checked) {
			// One app per field: clear the other cells in this row.
			row.find("input.udt-cell").not(this).prop("checked", false);
		}
		paint(row);
	});
}
