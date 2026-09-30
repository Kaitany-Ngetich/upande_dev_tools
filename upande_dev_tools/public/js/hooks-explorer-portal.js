// Copyright (c) 2026, Upande LTD and contributors
// For license information, please see license.txt

window.upande_dev_tools_portal = window.upande_dev_tools_portal || {};

upande_dev_tools_portal.mount_hooks_explorer = function (root) {
	let current_data = null;

	$(root).html(`
		<div class="dpx-board">
			<div class="dpx-bb-tb">
				<div class="dpx-bb-tb-hd">
					<div class="dpx-bb-tb-title">
						<div class="dpx-bb-tb-row">
							<span class="dpx-bb-mark">${hx_ico("search", 14)}</span>
							<h2>Hooks Explorer</h2>
						</div>
						<div class="dpx-bb-tb-sub">Browse and search every installed app's hooks.py</div>
					</div>
				</div>
				<div class="dpx-bb-tb-cmd">
					<div class="dpx-bb-grp">
						<span class="dpx-bb-grp-lbl">App</span>
						<select id="app-selector" class="dpx-bb-field"></select>
					</div>
					<span class="dpx-bb-sep"></span>
					<div class="dpx-bb-grp hx-search-grp">
						<input id="hook-search" class="dpx-bb-field hx-search" type="text"
							placeholder="Search e.g. Sales Invoice, on_submit, scheduler...">
					</div>
				</div>
			</div>
			<div class="bb-stage"><div id="hooks-output"></div></div>
		</div>
	`);

	frappe.call({
		method: "upande_dev_tools.api.hooks_explorer.get_installed_apps",
		callback(r) {
			const apps = r.message || [];
			const selector = $("#app-selector");

			selector.empty();

			apps.forEach((app) => {
				selector.append(`<option value="${app}">${app}</option>`);
			});

			const default_app = apps.includes("upande_kaitet") ? "upande_kaitet" : apps[0];

			if (default_app) {
				selector.val(default_app);
				load_hooks(default_app);
			}
		},
	});

	$(document).on("change", "#app-selector", function () {
		$("#hook-search").val("");
		load_hooks($(this).val());
	});

	$(document).on("input", "#hook-search", function () {
		render_hooks(current_data, $(this).val());
	});

	function load_hooks(app_name) {
		$("#hooks-output").html(hx_blank(`Loading hooks for ${app_name}…`, ""));

		frappe.call({
			method: "upande_dev_tools.api.hooks_explorer.get_app_hooks",
			args: { app_name },
			callback(r) {
				if (!r.message) {
					$("#hooks-output").html(hx_blank("No response received", ""));
					return;
				}

				if (r.message.error) {
					$("#hooks-output").html(hx_blank("Could not read this app's hooks", r.message.error));
					return;
				}

				current_data = r.message;
				render_hooks(current_data, $("#hook-search").val());
			},
		});
	}

	function render_hooks(data, search_text = "") {
		if (!data) return;

		const hooks = data.hooks || {};
		const query = (search_text || "").toLowerCase();

		if (!Object.keys(hooks).length) {
			$("#hooks-output").html(hx_blank("No hooks found for this app", ""));
			return;
		}

		const sections = [];

		Object.keys(hooks).forEach((hook_type) => {
			const hook_json = JSON.stringify(hooks[hook_type], null, 2);
			const searchable_text = `${hook_type} ${hook_json}`.toLowerCase();

			if (query && !searchable_text.includes(query)) return;

			sections.push(`
				<div class="dpx-card hx-section">
					<div class="dpx-card-hd"><div class="ttl">${hx_esc(hook_type)}</div></div>
					<div class="dpx-card-body" style="padding-top:0">
						<pre class="hx-pre">${hx_esc(hook_json)}</pre>
					</div>
				</div>`);
		});

		if (!sections.length) {
			$("#hooks-output").html(
				query
					? hx_blank("No matching hooks", `Nothing in ${hx_esc(data.app_name)} matches "${hx_esc(search_text)}".`)
					: hx_blank("No hooks found for this app", "")
			);
			return;
		}

		$("#hooks-output").html(sections.join(""));
	}

	function hx_blank(heading, body) {
		return `<div class="dpx-card"><div class="dpx-bb-blank">
			<h3>${hx_esc(heading)}</h3>${body ? `<p>${hx_esc(body)}</p>` : ""}</div></div>`;
	}
};

const HX_ICONS = {
	search: '<path d="m21 21-4.34-4.34"/><circle cx="11" cy="11" r="8"/>',
};

function hx_ico(name, size) {
	const s = size || 15;
	return `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="currentColor"
		stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${
			HX_ICONS[name] || ""
		}</svg>`;
}

function hx_esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}
