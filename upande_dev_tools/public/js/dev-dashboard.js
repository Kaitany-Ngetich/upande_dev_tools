window.upande_dev_tools = window.upande_dev_tools || {};

upande_dev_tools.DevDashboard = class DevDashboard {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.data = null;
		this.tab = "apps";
		this.render_shell();
		this.load();
	}

	load() {
		const icon = $(this.wrapper).find(".dd-reload").addClass("spin");
		if (!this.data) this.skeleton();
		frappe
			.xcall("upande_dev_tools.api.dashboard.get_dashboard_data")
			.then((data) => {
				this.data = data || {};
				this.stage().removeAttr("aria-busy");
				this.render();
				icon.removeClass("spin");
			})
			.catch((e) => {
				icon.removeClass("spin");
				this.stage().html(
					dd_blank("Could not read the bench", String((e && e.message) || e) || "Reload to try again.")
				);
			});
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
							<button class="dpx-bb-btn dd-scan" type="button" title="Read each app's git state">Scan bench</button>
							<button class="dpx-bb-ico dd-reload" type="button" title="Refresh">${dd_ico("refresh")}</button>
							<span class="dpx-bb-div"></span>
							<div class="dpx-bb-views dd-tabs" role="tablist">
								<button data-tab="apps" class="on" role="tab">${dd_ico("layers", 12)}<span>Apps</span></button>
								<button data-tab="drift" role="tab">${dd_ico("split", 12)}<span>Drift</span></button>
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
				.catch(() => frappe.show_alert({ message: __("Could not read the bench."), indicator: "red" }))
				.then(() => btn.prop("disabled", false).text("Scan bench"));
		});
		root.on("click", ".dd-tabs button", (e) => {
			const btn = $(e.currentTarget);
			root.find(".dd-tabs button").removeClass("on");
			btn.addClass("on");
			this.tab = btn.data("tab");
			this.render();
		});
		document.addEventListener("keydown", (e) => {
			if (e.key !== "r" || /^(INPUT|SELECT|TEXTAREA)$/.test((e.target || {}).tagName || "")) return;
			this.load();
		});
	}

	skeleton() {
		this.stage().attr("aria-busy", "true").html(
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

		$(this.wrapper).find(".dd-summary").html(
			`<b>${apps.length}</b> apps<span class="sep">·</span>` +
				`<b>${d.clean_apps || 0}</b> clean<span class="sep">·</span>` +
				(d.stale_apps ? `<span class="warn">${d.stale_apps} behind</span><span class="sep">·</span>` : "") +
				(d.dirty_apps ? `<span class="late">${d.dirty_apps} uncommitted</span>` : "all committed")
		);

		$(this.wrapper).find(".dpx-bb-status").html(
			`Last backup <b>${dd_esc(d.last_backup_display || "never")}</b><span class="sep">·</span>` +
				`<b>${d.snapshots_today || 0}</b> snapshots today<span class="sep">·</span>` +
				`<b>${drift}</b> schema differences` +
				`<span class="sp">${(d.recent_errors || []).length} recent errors</span>`
		);

		if (this.tab === "apps") return this.render_apps(apps);
		if (this.tab === "drift") return this.render_drift(d);
		return this.render_activity(d);
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
					<colgroup><col><col style="width:150px"><col style="width:104px"><col style="width:104px"><col style="width:170px"></colgroup>
					<thead><tr><th>App</th><th>Branch</th><th>Ahead</th><th>Behind</th><th>State</th></tr></thead>
					<tbody>${rows.map((a) => dd_app_row(a)).join("")}</tbody>
				</table>
			</div></div>`
		);
	}

	render_drift(d) {
		const rows = d.field_differences || [];
		const tiles = [
			["Missing locally", d.missing_local_count || 0, "On the live site but not in this bench"],
			["Missing live", d.missing_live_count || 0, "In this bench but not on the live site"],
			["Different type", d.different_type_count || 0, "Same field, different fieldtype"],
			["Different property", d.different_property_count || 0, "Same field, different options"],
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
					: dd_blank("Local and live agree", "No field differences were found the last time the two were compared."))
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
									)}</td><td>${dd_esc(a.document_name || a.reference_name || "")}</td>
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
									(e) => `<tr class="dpx-bb-row"><td class="subj">${dd_esc(
										e.method || e.title || "Error"
									)}</td><td class="num late">${dd_esc(e.creation_display || e.creation || "")}</td></tr>`
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
			<td class="dd-branch">${dd_esc(a.current_branch || "—")}</td>
			<td class="num">${a.commits_ahead || 0}</td>
			<td class="num${a.commits_behind ? " late" : ""}">${a.commits_behind || 0}</td>
			<td><span class="dpx-bb-chip ${state[0]}">${dd_esc(state[1])}</span></td>
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
	refresh: '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
};

function dd_ico(name, size) {
	const s = size || 15;
	return `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="currentColor"
		stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${DD_ICONS[name] || ""}</svg>`;
}

function dd_esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}
