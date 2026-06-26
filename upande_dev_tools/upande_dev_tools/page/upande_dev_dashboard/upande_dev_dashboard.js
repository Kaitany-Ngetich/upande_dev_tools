frappe.pages["upande-dev-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Dashboard",
		single_column: true,
	});

	$(page.body).html(`
		<style>
			.udt-dashboard {
				padding: 12px 14px 24px;
				background: #f8fafc;
				min-height: calc(100vh - 110px);
			}

			.udt-title {
				margin-bottom: 14px;
			}

			.udt-title h2 {
				margin: 0;
				font-size: 22px;
				font-weight: 700;
				color: #111827;
			}

			.udt-title p {
				margin: 4px 0 0;
				color: #64748b;
				font-size: 13px;
			}

			.udt-kpi-grid {
				display: grid;
				grid-template-columns: repeat(6, minmax(145px, 1fr));
				gap: 12px;
				margin-bottom: 16px;
			}

			.udt-card {
				background: #fff;
				border: 1px solid #e5e7eb;
				border-radius: 10px;
				padding: 11px 13px;
				min-height: 92px;
				box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
			}

			.udt-card small {
				color: #64748b;
				font-size: 12px;
			}

			.udt-card h3 {
				margin: 5px 0;
				font-size: 22px;
				font-weight: 700;
				line-height: 1.1;
				color: #111827;
			}

			.udt-link {
				color: #2563eb;
				font-size: 12px;
				cursor: pointer;
				font-weight: 500;
			}

			.udt-link:hover {
				text-decoration: underline;
			}

			.udt-grid {
				display: grid;
				grid-template-columns: repeat(2, minmax(0, 1fr));
				gap: 16px;
			}

			.udt-section {
				background: #fff;
				border: 1px solid #e5e7eb;
				border-radius: 12px;
				height: 330px;
				overflow: hidden;
				display: flex;
				flex-direction: column;
				box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
			}

			.udt-section-header {
				padding: 12px 14px;
				border-bottom: 1px solid #eef2f7;
				display: flex;
				align-items: center;
				justify-content: space-between;
				gap: 10px;
			}

			.udt-section-header h4 {
				margin: 0;
				font-size: 16px;
				font-weight: 700;
				color: #111827;
			}

			.udt-section-body {
				padding: 12px 14px;
				overflow-y: auto;
				flex: 1;
			}

			.udt-table {
				margin: 0;
				font-size: 12px;
			}

			.udt-table th {
				background: #f8fafc;
				font-size: 12px;
				font-weight: 700;
				white-space: nowrap;
			}

			.udt-table td {
				vertical-align: middle !important;
			}

			.udt-filters {
				display: grid;
				grid-template-columns: repeat(4, minmax(0, 1fr));
				gap: 10px;
				margin-bottom: 10px;
			}

			.udt-list-item {
				padding: 9px 0;
				border-bottom: 1px solid #f1f5f9;
			}

			.udt-list-item:last-child {
				border-bottom: none;
			}

			.udt-list-title {
				font-size: 13px;
				font-weight: 600;
				color: #111827;
			}

			.udt-list-meta {
				font-size: 12px;
				color: #64748b;
				margin-top: 3px;
			}

			.udt-pill {
				display: inline-block;
				padding: 3px 8px;
				border-radius: 999px;
				background: #eef2ff;
				color: #3730a3;
				font-size: 11px;
				font-weight: 600;
			}

			.udt-empty {
				text-align: center;
				color: #94a3b8;
				padding: 24px 0;
				font-size: 13px;
			}

			.udt-health-card {
				padding: 11px 12px;
				background: #f8fafc;
				border: 1px solid #e5e7eb;
				border-radius: 10px;
				margin-bottom: 10px;
			}

			.udt-health-label {
				color: #64748b;
				font-size: 12px;
			}

			.udt-health-value {
				color: #111827;
				font-size: 18px;
				font-weight: 700;
				margin-top: 3px;
			}

			@media (max-width: 1200px) {
				.udt-kpi-grid {
					grid-template-columns: repeat(3, minmax(145px, 1fr));
				}
			}

			@media (max-width: 900px) {
				.udt-grid {
					grid-template-columns: 1fr;
				}

				.udt-kpi-grid {
					grid-template-columns: repeat(2, minmax(145px, 1fr));
				}
			}
		</style>

		<div class="udt-dashboard">
			<div class="udt-title">
				<h2>Upande Dev Tools Dashboard</h2>
				<p>Monitor code health, backups, hooks and site differences</p>
			</div>

			<div class="udt-kpi-grid">
				<div class="udt-card">
					<small>Installed Apps</small>
					<h3 id="installed-apps">0</h3>
					<small>Total installed</small><br>
					<span class="udt-link" onclick="udt_open_list('Module Version Check')">View all apps</span>
				</div>

				<div class="udt-card">
					<small>Clean Apps</small>
					<h3 id="clean-apps">0</h3>
					<small>Up to date</small><br>
					<span class="udt-link" onclick="udt_open_list('Module Version Check')">View clean apps</span>
				</div>

				<div class="udt-card">
					<small>Stale Apps</small>
					<h3 id="stale-apps">0</h3>
					<small>Behind remote</small><br>
					<span class="udt-link" onclick="udt_open_list('Module Version Check')">View stale apps</span>
				</div>

				<div class="udt-card">
					<small>Dirty Apps</small>
					<h3 id="dirty-apps">0</h3>
					<small>Uncommitted changes</small><br>
					<span class="udt-link" onclick="udt_open_list('Module Version Check')">View dirty apps</span>
				</div>

				<div class="udt-card">
					<small>Snapshots Today</small>
					<h3 id="snapshots-today">0</h3>
					<small>Total snapshots</small><br>
					<span class="udt-link" onclick="udt_open_list('Code Backup Snapshot')">View snapshots</span>
				</div>

				<div class="udt-card">
					<small>Last Backup</small>
					<h3 id="last-backup-display">No backup yet</h3>
					<small>Latest run</small><br>
					<span class="udt-link" onclick="udt_open_list('Code Backup Snapshot')">View history</span>
				</div>
			</div>

			<div class="udt-grid">
				<div class="udt-section">
					<div class="udt-section-header">
						<h4>1. Version Control Monitor</h4>
						<button class="btn btn-xs btn-default" onclick="udt_open_list('Module Version Check')">View All</button>
					</div>
					<div class="udt-section-body">
						<table class="table table-bordered udt-table">
							<thead>
								<tr>
									<th>App</th>
									<th>Branch</th>
									<th>Remote</th>
									<th>Ahead</th>
									<th>Behind</th>
									<th>Dirty</th>
									<th>Risk</th>
									<th>Last Checked</th>
									<th>Actions</th>
								</tr>
							</thead>
							<tbody id="version-table">
								<tr><td colspan="9">Loading...</td></tr>
							</tbody>
						</table>
					</div>
				</div>

				<div class="udt-section">
					<div class="udt-section-header">
						<h4>2. Code Backup Snapshots</h4>
						<button class="btn btn-xs btn-default" onclick="udt_open_list('Code Backup Snapshot')">View All</button>
					</div>
					<div class="udt-section-body">
						<div class="udt-filters">
							<select class="form-control input-sm"><option>All Apps</option></select>
							<select class="form-control input-sm"><option>All Modules</option></select>
							<select class="form-control input-sm"><option>All Source Types</option></select>
							<input class="form-control input-sm" placeholder="Search">
						</div>

						<table class="table table-bordered udt-table">
							<thead>
								<tr>
									<th>Time</th>
									<th>Source Type</th>
									<th>Document</th>
									<th>App / Module</th>
									<th>Changed</th>
									<th>Actions</th>
								</tr>
							</thead>
							<tbody id="backup-table">
								<tr><td colspan="6">Loading...</td></tr>
							</tbody>
						</table>
					</div>
				</div>

				<div class="udt-section">
					<div class="udt-section-header">
						<h4>3. Live vs Local Difference Checker</h4>
						<button class="btn btn-xs btn-default" onclick="udt_open_list('Field Difference Log')">View All</button>
					</div>
					<div class="udt-section-body" id="field-difference-list">
						<div class="udt-empty">Loading...</div>
					</div>
				</div>

				<div class="udt-section">
					<div class="udt-section-header">
						<h4>4. Hooks Explorer</h4>
						<button class="btn btn-xs btn-default" onclick="udt_open_hooks_explorer()">Open Hooks Explorer</button>
					</div>
					<div class="udt-section-body" id="hooks-summary-list">
						<div class="udt-empty">Loading...</div>
					</div>
				</div>

				<div class="udt-section">
					<div class="udt-section-header">
						<h4>5. Developer Activity Timeline</h4>
						<button class="btn btn-xs btn-default" onclick="udt_open_list('Developer Activity Log')">View All</button>
					</div>
					<div class="udt-section-body" id="activity-list">
						<div class="udt-empty">Loading...</div>
					</div>
				</div>

				<div class="udt-section">
					<div class="udt-section-header">
						<h4>6. System Health</h4>
						<span class="udt-pill">Local</span>
					</div>
					<div class="udt-section-body" id="system-health">
						<div class="udt-empty">Loading...</div>
					</div>
				</div>
			</div>
		</div>
	`);

	udt_load_dashboard();
};

window.udt_open_list = function (doctype) {
	frappe.set_route("List", doctype);
};

window.udt_open_doc = function (doctype, name) {
	if (!name) {
		frappe.set_route("List", doctype);
		return;
	}
	frappe.set_route("Form", doctype, name);
};

window.udt_open_hooks_explorer = function () {
	frappe.set_route("hooks-explorer");
};

function udt_load_dashboard() {
	frappe.call({
		method: "upande_dev_tools.api.dashboard.get_dashboard_data",
		callback: function (r) {
			const data = r.message || {};

			console.log("Upande Dev Dashboard Data:", data);

			const version_rows = data.apps || [];
			const backups = data.backup_snapshots || [];
			const fields = data.field_differences || [];
			const hooks = udt_normalize_hooks_summary(data.hooks_summary || {});
			const activities = data.activity_logs || [];

			const health = {
				bench: "my-bench",
				site: "dev.localhost",
				environment: "Local Machine",
			};

			udt_render_kpis(data, version_rows, backups);
			udt_render_version_table(version_rows.slice(0, 5));
			udt_render_backup_table(backups.slice(0, 5));
			udt_render_field_differences(fields.slice(0, 5));
			udt_render_hooks_summary(hooks.slice(0, 8));
			udt_render_activity(activities.slice(0, 8));
			udt_render_system_health(health);
		},
		error: function () {
			frappe.msgprint("Failed to load dashboard data.");
		},
	});
}

function udt_normalize_hooks_summary(summary) {
	if (Array.isArray(summary)) {
		return summary;
	}

	if (!summary || typeof summary !== "object") {
		return [];
	}

	return Object.keys(summary).map(key => {
		const value = summary[key];

		let count = 0;
		let preview = "";

		if (Array.isArray(value)) {
			count = value.length;
			preview = value.slice(0, 3).map(item => {
				if (typeof item === "string") return item;
				if (item && typeof item === "object") return item.name || item.method || item.doctype || JSON.stringify(item);
				return String(item);
			}).join(", ");
		} else if (value && typeof value === "object") {
			count = Object.keys(value).length;
			preview = Object.keys(value).slice(0, 3).join(", ");
		} else if (typeof value === "number") {
			count = value;
			preview = `${value}`;
		} else if (value) {
			count = 1;
			preview = String(value);
		}

		return {
			hook_type: key,
			count: count,
			preview: preview,
			value: value
		};
	});
}

function udt_render_kpis(data, version_rows, backups) {
	$("#installed-apps").text(data.installed_apps || version_rows.length || 0);
	$("#clean-apps").text(data.clean_apps || 0);
	$("#stale-apps").text(data.stale_apps || 0);
	$("#dirty-apps").text(data.dirty_apps || 0);
	$("#snapshots-today").text(data.snapshots_today || 0);
	$("#last-backup-display").html(udt_escape(data.last_backup_display || "No backup yet"));
}

function udt_render_version_table(rows) {
	const tbody = $("#version-table");

	if (!rows.length) {
		tbody.html(`<tr><td colspan="9" class="text-muted text-center">No version records found</td></tr>`);
		return;
	}

	tbody.html(rows.map(row => {
		const name = row.module_name || "";
		const branch = row.current_branch || "";
		const remote = row.upstream_branch || "";
		const ahead = row.commits_ahead || 0;
		const behind = row.commits_behind || 0;
		const dirty = row.has_uncommitted_changes ? "Yes" : "No";
		const risk = row.risk_level || row.status || "";
		const checked = row.last_checked_at || "";

		return `
			<tr>
				<td>${udt_escape(name)}</td>
				<td>${udt_escape(branch)}</td>
				<td>${udt_escape(remote)}</td>
				<td>${udt_escape(ahead)}</td>
				<td>${udt_escape(behind)}</td>
				<td>${udt_escape(dirty)}</td>
				<td>${udt_escape(risk)}</td>
				<td>${udt_escape(checked)}</td>
				<td>
					<button class="btn btn-xs btn-default" onclick="udt_open_doc('Module Version Check', '${udt_escape_attr(name)}')">View</button>
				</td>
			</tr>
		`;
	}).join(""));
}

function udt_render_backup_table(rows) {
	const tbody = $("#backup-table");

	if (!rows.length) {
		tbody.html(`<tr><td colspan="6" class="text-muted text-center">No backup snapshots found</td></tr>`);
		return;
	}

	tbody.html(rows.map(row => {
		const name = row.name || "";
		const time = row.snapshot_time_display || row.snapshot_time || "";
		const source_type = row.source_type || "";
		const document_name = row.document_name || "";
		const app_module = row.app_module || row.app || row.module || "";
		const changed = row.changed_since_last_backup ? "Yes" : "No";

		return `
			<tr>
				<td>${udt_escape(time)}</td>
				<td>${udt_escape(source_type)}</td>
				<td>${udt_escape(document_name)}</td>
				<td>${udt_escape(app_module)}</td>
				<td>${udt_escape(changed)}</td>
				<td>
					<button class="btn btn-xs btn-default" onclick="udt_open_doc('Code Backup Snapshot', '${udt_escape_attr(name)}')">View</button>
				</td>
			</tr>
		`;
	}).join(""));
}

function udt_render_field_differences(rows) {
	const target = $("#field-difference-list");

	if (!rows.length) {
		target.html(`<div class="udt-empty">No field differences found</div>`);
		return;
	}

	target.html(rows.map(row => {
		const name = row.name || "";
		const title = `${row.doctype_name || "Unknown DocType"} → ${row.field_name || "Unknown Field"}`;
		const meta = [
			row.issue_type,
			row.status,
			row.live_value ? `Live: ${row.live_value}` : null,
			row.local_value ? `Local: ${row.local_value}` : null
		].filter(Boolean).join(" · ");

		return `
			<div class="udt-list-item">
				<div class="udt-list-title">${udt_escape(title)}</div>
				<div class="udt-list-meta">${udt_escape(meta)}</div>
				<div style="margin-top: 6px;">
					<button class="btn btn-xs btn-default" onclick="udt_open_doc('Field Difference Log', '${udt_escape_attr(name)}')">View</button>
				</div>
			</div>
		`;
	}).join(""));
}

function udt_render_hooks_summary(rows) {
	const target = $("#hooks-summary-list");

	if (!rows.length) {
		target.html(`<div class="udt-empty">No hooks summary found</div>`);
		return;
	}

	target.html(rows.map(row => {
		const title = row.hook_type || "Hook";
		const meta_parts = [`Count: ${row.count || 0}`];

		if (row.preview) {
			meta_parts.push(row.preview);
		}

		return `
			<div class="udt-list-item">
				<div class="udt-list-title">${udt_escape(title)}</div>
				<div class="udt-list-meta">${udt_escape(meta_parts.join(" · "))}</div>
			</div>
		`;
	}).join(""));
}

function udt_render_activity(rows) {
	const target = $("#activity-list");

	if (!rows.length) {
		target.html(`<div class="udt-empty">No activity found</div>`);
		return;
	}

	target.html(rows.map(row => {
		const title = row.title || row.activity_type || "Developer Activity";
		const meta = [
			row.activity_type,
			row.status,
			row.source,
			row.activity_time_display
		].filter(Boolean).join(" · ");

		return `
			<div class="udt-list-item">
				<div class="udt-list-title">${udt_escape(title)}</div>
				<div class="udt-list-meta">${udt_escape(meta)}</div>
			</div>
		`;
	}).join(""));
}

function udt_render_system_health(health) {
	$("#system-health").html(`
		<div class="udt-health-card">
			<div class="udt-health-label">Bench</div>
			<div class="udt-health-value">${udt_escape(health.bench || "my-bench")}</div>
		</div>

		<div class="udt-health-card">
			<div class="udt-health-label">Site</div>
			<div class="udt-health-value">${udt_escape(health.site || "dev.localhost")}</div>
		</div>

		<div class="udt-health-card">
			<div class="udt-health-label">Environment</div>
			<div class="udt-health-value">${udt_escape(health.environment || "Local Machine")}</div>
		</div>
	`);
}

function udt_escape(value) {
	if (value === null || value === undefined) return "";
	return frappe.utils.escape_html(String(value));
}

function udt_escape_attr(value) {
	if (value === null || value === undefined) return "";
	return String(value)
		.replace(/\\/g, "\\\\")
		.replace(/'/g, "\\'")
		.replace(/"/g, "&quot;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;");
}
