frappe.pages["hooks-explorer"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Hooks Explorer",
		single_column: true,
	});

	let current_data = null;

	$(page.body).html(`
		<div class="frappe-card" style="padding: 20px;">
			<div style="display:flex; gap:15px; margin-bottom:15px; flex-wrap:wrap;">
				<div>
					<label><b>Select App</b></label>
					<select id="app-selector" class="form-control" style="min-width:300px;"></select>
				</div>

				<div>
					<label><b>Search Hooks</b></label>
					<input id="hook-search" class="form-control" style="min-width:300px;"
						placeholder="Search e.g. Sales Invoice, on_submit, scheduler..." />
				</div>
			</div>

			<h4>Hooks Output</h4>
			<div id="hooks-output">Select an app to view hooks.</div>
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
		$("#hooks-output").html(`<p>Loading hooks for <b>${app_name}</b>...</p>`);

		frappe.call({
			method: "upande_dev_tools.api.hooks_explorer.get_app_hooks",
			args: { app_name },
			callback(r) {
				if (!r.message) {
					$("#hooks-output").html(`<p>No response received.</p>`);
					return;
				}

				if (r.message.error) {
					$("#hooks-output").html(`
						<div class="alert alert-danger">
							<b>Error:</b> ${r.message.error}
						</div>
					`);
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

		let html = `
			<h5>App: ${data.app_name}</h5>
			<hr>
		`;

		if (!Object.keys(hooks).length) {
			html += `<p>No hooks found for this app.</p>`;
			$("#hooks-output").html(html);
			return;
		}

		let match_count = 0;

		Object.keys(hooks).forEach((hook_type) => {
			const hook_json = JSON.stringify(hooks[hook_type], null, 2);
			const searchable_text = `${hook_type} ${hook_json}`.toLowerCase();

			if (query && !searchable_text.includes(query)) {
				return;
			}

			match_count++;

			html += `
				<div style="margin-bottom:20px;">
					<h5>${escape_html(hook_type)}</h5>
					<pre style="background:#f7f7f7;padding:12px;border-radius:6px;max-height:300px;overflow:auto;">${escape_html(hook_json)}</pre>
				</div>
			`;
		});

		if (query && match_count === 0) {
			html += `<p>No matching hooks found for <b>${escape_html(search_text)}</b>.</p>`;
		}

		$("#hooks-output").html(html);
	}

	function escape_html(text) {
		return $("<div>").text(text).html();
	}
};
