window.upande_dev_tools = window.upande_dev_tools || {};

upande_dev_tools.DevDashboard = class DevDashboard {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.data = null;
		this.deployments = [];
		this.tab = "apps";
		this.render_shell();
		this.load();
	}

	load() {
		const icon = $(this.wrapper).find(".dd-reload").addClass("spin");
		if (!this.data) this.skeleton();
		Promise.all([
			frappe.xcall("upande_dev_tools.api.dashboard.get_dashboard_data"),
			frappe
				.xcall("upande_dev_tools.api.deployments.get_recent_deployments")
				.catch(() => null),
		])
			.then(([data, deployments]) => {
				this.data = data || {};
				if (deployments) this.deployments = deployments.recent || [];
				this.stage().removeAttr("aria-busy");
				this.render();
				icon.removeClass("spin");
			})
			.catch((e) => {
				icon.removeClass("spin");
				this.stage().html(
					dd_blank(
						"Could not read the bench",
						String((e && e.message) || e) || "Reload to try again."
					)
				);
			});
		if (!this.deployment_apps) {
			frappe
				.xcall("upande_dev_tools.api.deployments.get_deployment_apps")
				.then((apps) => {
					this.deployment_apps = apps || [];
				})
				.catch(() => {
					this.deployment_apps = [];
				});
		}
		if (!this.deployment_instances) {
			frappe
				.xcall("upande_dev_tools.api.deployments.get_deployment_instances")
				.then((instances) => {
					this.deployment_instances = instances || [];
				})
				.catch(() => {
					this.deployment_instances = [];
				});
		}
	}

	stage() {
		return $(this.wrapper).find(".bb-stage");
	}

	render_shell() {
		$(this.wrapper).html(`
			<div class="dpx-board">
				<div class="dpx-bb-tb">
					<div class="dpx-bb-tb-hd">
						<div class="dpx-bb-tb-title">
							<div class="dpx-bb-tb-row">
								<span class="dpx-bb-mark">${dd_ico("layers", 14)}</span>
								<h2>Bench</h2>
							</div>
							<div class="dpx-bb-tb-sub">What is installed, what has drifted, what changed today</div>
						</div>
						<div class="dpx-bb-tb-act">
							<button class="dpx-bb-btn primary dd-new-deploy" type="button">New deployment request</button>
							<button class="dpx-bb-btn dd-scan" type="button" title="Read each app's git state">Scan bench</button>
							<button class="dpx-bb-ico dd-reload" type="button" title="Refresh">${dd_ico("refresh")}</button>
							<span class="dpx-bb-div"></span>
							<div class="dpx-bb-views dd-tabs" role="tablist">
								<button data-tab="apps" class="on" role="tab">${dd_ico("layers", 12)}<span>Apps</span></button>
								<button data-tab="drift" role="tab">${dd_ico("split", 12)}<span>Drift</span></button>
								<button data-tab="deployments" role="tab">${dd_ico("rocket", 12)}<span>Deployments</span></button>
								<button data-tab="activity" role="tab">${dd_ico("clock", 12)}<span>Activity</span></button>
							</div>
						</div>
					</div>
					<div class="dpx-bb-tb-cmd">
						<span class="dd-summary"></span>
						<span class="dpx-bb-hint"><span class="dpx-bb-kbd">r</span><span>refresh</span></span>
					</div>
				</div>
				<div class="bb-stage"></div>
				<div class="dpx-bb-status"></div>
			</div>
		`);

		const root = $(this.wrapper);
		root.on("click", ".dd-reload", () => this.load());
		root.on("click", ".dd-scan", (e) => {
			const btn = $(e.currentTarget).prop("disabled", true).text("Scanning…");
			frappe
				.xcall("upande_dev_tools.api.version_control.scan_bench")
				.then((r) => {
					frappe.show_alert({
						message: __("Read {0} apps.", [r.checked]),
						indicator: r.failed && r.failed.length ? "orange" : "green",
					});
					this.load();
				})
				.catch(() =>
					frappe.show_alert({
						message: __("Could not read the bench."),
						indicator: "red",
					})
				)
				.then(() => btn.prop("disabled", false).text("Scan bench"));
		});
		root.on("click", ".dd-new-deploy", () => this.new_deployment_request());
		root.on("click", ".dd-duplicate", (e) => {
			const name = $(e.currentTarget).closest("[data-name]").data("name");
			const row = this.deployments.find((d) => d.name === name);
			if (row) this.new_deployment_request(row);
		});
		root.on("click", ".dd-repo", (e) => {
			e.preventDefault();
			const url = $(e.currentTarget).data("url");
			if (!url) return;
			const done = () => upande_dev_tools.toast(__("Repo URL copied."), "green");
			const fail = () => upande_dev_tools.toast(__("Could not copy that."), "red");
			if (navigator.clipboard && navigator.clipboard.writeText) {
				navigator.clipboard.writeText(url).then(done, fail);
			} else {
				fail();
			}
		});
		root.on("click", ".dd-tabs button", (e) => {
			const btn = $(e.currentTarget);
			root.find(".dd-tabs button").removeClass("on");
			btn.addClass("on");
			this.tab = btn.data("tab");
			this.render();
		});
		document.addEventListener("keydown", (e) => {
			if (e.key !== "r" || /^(INPUT|SELECT|TEXTAREA)$/.test((e.target || {}).tagName || ""))
				return;
			this.load();
		});
	}

	skeleton() {
		this.stage()
			.attr("aria-busy", "true")
			.html(
				`<div class="dpx-skel" aria-hidden="true"><div class="dpx-card sk-plain">
				<div class="sk-head">${["w20", "w12", "w8", "w8", "w12"]
					.map((w) => `<i class="sk ${w}"></i>`)
					.join("")}</div>
				${[1, 2, 3, 4, 5, 6, 7, 8]
					.map(
						() => `<div class="sk-line">
							<i class="sk dot"></i><i class="sk" style="width:22%"></i>
							<i class="sk w12"></i><i class="sk w6"></i><i class="sk w6"></i>
							<i class="sk chip right"></i></div>`
					)
					.join("")}
			</div></div>`
			);
	}

	render() {
		const d = this.data;
		const apps = d.apps || [];
		const drift =
			(d.missing_local_count || 0) +
			(d.missing_live_count || 0) +
			(d.different_type_count || 0) +
			(d.different_property_count || 0);

		$(this.wrapper)
			.find(".dd-summary")
			.html(
				`<b>${apps.length}</b> apps<span class="sep">·</span>` +
					`<b>${d.clean_apps || 0}</b> clean<span class="sep">·</span>` +
					(d.stale_apps
						? `<span class="warn">${d.stale_apps} behind</span><span class="sep">·</span>`
						: "") +
					(d.dirty_apps
						? `<span class="late">${d.dirty_apps} uncommitted</span>`
						: "all committed")
			);

		$(this.wrapper)
			.find(".dpx-bb-status")
			.html(
				`Last backup <b>${dd_esc(
					d.last_backup_display || "never"
				)}</b><span class="sep">·</span>` +
					`<b>${d.snapshots_today || 0}</b> snapshots today<span class="sep">·</span>` +
					`<b>${drift}</b> schema differences` +
					`<span class="sp">${(d.recent_errors || []).length} recent errors</span>`
			);

		if (this.tab === "apps") return this.render_apps(apps);
		if (this.tab === "drift") return this.render_drift(d);
		if (this.tab === "deployments") return this.render_deployments();
		return this.render_activity(d);
	}

	render_deployments() {
		if (!this.deployments.length) {
			return this.stage().html(
				dd_blank(
					"No deployment requests yet",
					"Press New deployment request above to ask for one, or duplicate one later once there's history to repeat."
				)
			);
		}

		this.stage().html(
			`<div class="dpx-card"><div class="dpx-card-body dpx-bb-listwrap" style="padding:0 0 4px">
				<table class="dpx-bb-table">
					<colgroup><col><col style="width:150px"><col style="width:110px"><col style="width:120px"><col style="width:104px"><col style="width:120px"><col style="width:80px"></colgroup>
					<thead><tr><th>App</th><th>Instance</th><th>Branch</th><th>Requested by</th><th>Raised</th><th>State</th><th></th></tr></thead>
					<tbody>${this.deployments.map((d) => dd_deploy_row(d)).join("")}</tbody>
				</table>
			</div></div>`
		);
	}

	new_deployment_request(prefill) {
		const apps = (this.deployment_apps || []).map((a) => [a.name, a.name]);
		const instances = (this.deployment_instances || []).map((i) => [
			i.name,
			i.environment_type ? `${i.name} (${i.environment_type})` : i.name,
		]);
		const default_branch = prefill
			? prefill.branch
			: (this.deployment_apps || []).find((a) => a.name === (apps[0] || [])[0])
					?.default_branch;

		upande_dev_tools.open_modal(
			prefill ? __("Duplicate deployment request") : __("New deployment request"),
			[
				{
					name: "app",
					label: __("App"),
					type: "select",
					options: apps,
					value: prefill ? prefill.app : "",
				},
				{
					name: "instance",
					label: __("Instance"),
					type: "select",
					options: instances,
					value: prefill ? prefill.instance : "",
				},
				{
					name: "branch",
					label: __("Branch"),
					type: "text",
					value: default_branch || "",
					placeholder: __("e.g. main"),
				},
				{
					name: "description",
					label: __("Description"),
					type: "textarea",
					value: prefill ? prefill.description || "" : "",
				},
			],
			(values) => {
				if (!values.app || !values.instance) {
					upande_dev_tools.toast(__("Pick an app and an instance first."), "orange");
					return;
				}
				frappe
					.xcall("upande_dev_tools.api.deployments.create_deployment_request", {
						app: values.app,
						instance: values.instance,
						branch: values.branch || null,
						description: values.description || null,
					})
					.then(() => {
						upande_dev_tools.toast(__("Deployment request raised."), "green");
						this.load();
					})
					.catch((e) => {
						upande_dev_tools.toast(
							String((e && e.message) || e) || __("Could not raise that."),
							"red"
						);
					});
			},
			__("Raise it")
		);
	}

	render_apps(apps) {
		if (!apps.length) {
			return this.stage().html(
				dd_blank(
					"No app has been checked yet",
					"Press Scan bench and every installed app will report its branch, how far it has drifted from its remote, and whether it has uncommitted work."
				)
			);
		}

		// Work that needs a decision floats up: uncommitted first, then behind.
		const rank = { Dirty: 0, Stale: 1 };
		const rows = apps.slice().sort((a, b) => (rank[a.status] ?? 2) - (rank[b.status] ?? 2));

		this.stage().html(
			`<div class="dpx-card"><div class="dpx-card-body dpx-bb-listwrap" style="padding:0 0 4px">
				<table class="dpx-bb-table">
					<colgroup><col><col style="width:36px"><col style="width:150px"><col style="width:104px"><col style="width:104px"><col style="width:170px"></colgroup>
					<thead><tr><th>App</th><th></th><th>Branch</th><th>Ahead</th><th>Behind</th><th>State</th></tr></thead>
					<tbody>${rows.map((a) => dd_app_row(a)).join("")}</tbody>
				</table>
			</div></div>`
		);
	}

	render_drift(d) {
		const rows = d.field_differences || [];
		const tiles = [
			[
				"Missing locally",
				d.missing_local_count || 0,
				"On the live site but not in this bench",
			],
			["Missing live", d.missing_live_count || 0, "In this bench but not on the live site"],
			["Different type", d.different_type_count || 0, "Same field, different fieldtype"],
			[
				"Different property",
				d.different_property_count || 0,
				"Same field, different options",
			],
		];

		this.stage().html(
			`<div class="dd-tiles">${tiles
				.map(
					([label, n, note]) => `<div class="rq-stat${n ? " warn" : ""}">
						<div class="lbl">${dd_esc(label)}</div>
						<div class="val">${n}</div>
						<div class="note">${dd_esc(note)}</div>
					</div>`
				)
				.join("")}</div>` +
				(rows.length
					? `<div class="dpx-card"><div class="dpx-card-body dpx-bb-listwrap" style="padding:0 0 4px">
						<table class="dpx-bb-table">
							<colgroup><col style="width:190px"><col><col style="width:180px"></colgroup>
							<thead><tr><th>Doctype</th><th>Field</th><th>Difference</th></tr></thead>
							<tbody>${rows
								.map(
									(r) => `<tr class="dpx-bb-row">
										<td>${dd_esc(r.doctype_name || r.parent_doctype || "—")}</td>
										<td class="subj">${dd_esc(r.field_name || "—")}</td>
										<td><span class="dpx-bb-chip st-blocked">${dd_esc(r.issue_type || "—")}</span></td>
									</tr>`
								)
								.join("")}</tbody>
						</table>
					</div></div>`
					: dd_blank(
							"Local and live agree",
							"No field differences were found the last time the two were compared."
					  ))
		);
	}

	render_activity(d) {
		const acts = d.activity_logs || [];
		const errs = d.recent_errors || [];
		const half = (title, body) =>
			`<div class="dpx-card"><div class="dpx-card-hd"><div class="ttl">${title}</div></div>
				<div class="dpx-card-body" style="padding:6px 0 4px">${body}</div></div>`;

		this.stage().html(
			`<div class="dd-split">
				${half(
					"Recent activity",
					acts.length
						? `<table class="dpx-bb-table"><tbody>${acts
								.map(
									(a) => `<tr class="dpx-bb-row"><td class="subj">${dd_esc(
										a.action_type || a.activity_type || "Change"
									)}</td><td>${dd_esc(
										a.document_name || a.reference_name || ""
									)}</td>
									<td class="num">${dd_esc(a.creation_display || a.creation || "")}</td></tr>`
								)
								.join("")}</tbody></table>`
						: '<div class="dpx-bb-blank"><p>Nothing has been logged yet.</p></div>'
				)}
				${half(
					"Recent errors",
					errs.length
						? `<table class="dpx-bb-table"><tbody>${errs
								.map(
									(e) =>
										`<tr class="dpx-bb-row"><td class="subj">${dd_esc(
											e.method || e.title || "Error"
										)}</td><td class="num late">${dd_esc(
											e.creation_display || e.creation || ""
										)}</td></tr>`
								)
								.join("")}</tbody></table>`
						: '<div class="dpx-bb-blank"><p>No errors logged. That is the good outcome.</p></div>'
				)}
			</div>`
		);
	}
};

function dd_app_row(a) {
	const state = {
		Clean: ["st-done", "clean"],
		Ahead: ["st-in-progress", "not pushed"],
		Stale: ["st-in-review", "behind remote"],
		Dirty: ["st-blocked", "uncommitted changes"],
	}[a.status] || ["st-triage", (a.status || "unknown").toLowerCase()];

	return `
		<tr class="dpx-bb-row">
			<td><div class="subj"><span class="dpx-bb-pri ${
				a.status === "Dirty" ? "p3" : a.status === "Stale" ? "p2" : ""
			}"></span>${dd_esc(a.module_name)}</div></td>
			<td>${
				a.repository_url
					? `<button class="dpx-bb-ico dd-repo" type="button" data-url="${dd_esc(
							a.repository_url
					  )}" title="Copy repo URL: ${dd_esc(a.repository_url)}">${dd_ico(
							"github",
							13
					  )}</button>`
					: ""
			}</td>
			<td class="dd-branch">${dd_esc(a.current_branch || "—")}</td>
			<td class="num">${a.commits_ahead || 0}</td>
			<td class="num${a.commits_behind ? " late" : ""}">${a.commits_behind || 0}</td>
			<td><span class="dpx-bb-chip ${state[0]}">${dd_esc(state[1])}</span></td>
		</tr>`;
}

const DD_DEPLOY_STATE = {
	Requested: "st-triage",
	"In Progress": "st-in-progress",
	Deployed: "st-done",
	Failed: "st-blocked",
};

function dd_deploy_row(d) {
	return `
		<tr class="dpx-bb-row" data-name="${dd_esc(d.name)}">
			<td><a href="/app/deployment-request/${encodeURIComponent(d.name)}">${dd_esc(d.app)}</a></td>
			<td>${dd_esc(d.instance)}</td>
			<td>${dd_esc(d.branch || "—")}</td>
			<td>${dd_esc((d.requested_by_user || "").split("@")[0])}</td>
			<td>${dd_esc(String(d.creation || "").slice(0, 10))}</td>
			<td><span class="dpx-bb-chip ${DD_DEPLOY_STATE[d.workflow_state] || "st-triage"}">${dd_esc(
		d.workflow_state
	)}</span></td>
			<td><button class="dpx-bb-ico dd-duplicate" type="button" title="Duplicate this request">${dd_ico(
				"copy",
				13
			)}</button></td>
		</tr>`;
}

function dd_blank(heading, body) {
	return `<div class="dpx-card"><div class="dpx-bb-blank">
		<h3>${dd_esc(heading)}</h3><p>${dd_esc(body)}</p></div></div>`;
}

const DD_ICONS = {
	layers: '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
	split: '<path d="M16 3h5v5"/><path d="M8 3H3v5"/><path d="M12 22v-8.3a4 4 0 0 0-1.17-2.83L3 3"/><path d="m15 9 6-6"/>',
	clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
	refresh:
		'<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
	github: '<path d="M9 19c-4.3 1.4-4.3-2.5-6-3m12 5v-3.5c0-1 .1-1.4-.5-2 2.8-.3 5.5-1.4 5.5-6a4.6 4.6 0 0 0-1.3-3.2 4.2 4.2 0 0 0-.1-3.2s-1.1-.3-3.5 1.3a12.3 12.3 0 0 0-6.2 0C6.5 2.8 5.4 3.1 5.4 3.1a4.2 4.2 0 0 0-.1 3.2A4.6 4.6 0 0 0 4 9.5c0 4.6 2.7 5.7 5.5 6-.6.6-.6 1.2-.5 2V21"/>',
	rocket: '<path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/><path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/><path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/>',
	copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
};

function dd_ico(name, size) {
	const s = size || 15;
	return `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="currentColor"
		stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${
			DD_ICONS[name] || ""
		}</svg>`;
}

function dd_esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}
