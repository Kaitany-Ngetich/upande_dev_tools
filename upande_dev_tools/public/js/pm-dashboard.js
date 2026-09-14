window.upande_dev_tools = window.upande_dev_tools || {};

upande_dev_tools.PmDashboard = class PmDashboard {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.health = null;
		this.team = null;
		this.scope = "";
		this.tab = "people";
		this.render_shell();
		this.load();
	}

	load() {
		const icon = $(this.wrapper).find(".pm-reload").addClass("spin");
		if (!this.health) this.skeleton();
		Promise.all([
			frappe.xcall("upande_dev_tools.api.project_health.get_project_health", {
				scope: this.scope || null,
			}),
			frappe.xcall("upande_dev_tools.api.project_health.get_team_workload"),
		])
			.then(([health, team]) => {
				this.health = health || {};
				this.team = team || {};
				this.render();
				icon.removeClass("spin");
			})
			.catch((e) => {
				icon.removeClass("spin");
				this.stage().html(
					pm_blank("Could not read the portfolio", String((e && e.message) || e) || "Reload to try again.")
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
								<span class="dpx-bb-mark">${pm_ico("gauge", 14)}</span>
								<h2>Portfolio</h2>
							</div>
							<div class="dpx-bb-tb-sub">Who is loaded, what is slipping, what is waiting on you</div>
						</div>
						<div class="dpx-bb-tb-act">
							<button class="dpx-bb-ico pm-reload" type="button" title="Refresh">${pm_ico("refresh")}</button>
							<span class="dpx-bb-div"></span>
							<div class="dpx-bb-views pm-tabs" role="tablist">
								<button data-tab="people" class="on" role="tab">${pm_ico("users", 12)}<span>People</span></button>
								<button data-tab="projects" role="tab">${pm_ico("folder", 12)}<span>Projects</span></button>
							</div>
						</div>
					</div>
					<div class="dpx-bb-tb-cmd">
						<div class="dpx-bb-grp">
							<span class="dpx-bb-grp-lbl">Scope</span>
							<select class="dpx-bb-field pm-scope" aria-label="Project scope">
								<option value="">All projects</option>
								<option value="Internal">Internal</option>
								<option value="External">Client</option>
							</select>
						</div>
						<span class="dpx-bb-hint"><span class="dpx-bb-kbd">r</span><span>refresh</span></span>
					</div>
				</div>
				<div class="pm-alerts"></div>
				<div class="bb-stage"></div>
				<div class="dpx-bb-status"></div>
			</div>
		`);

		const root = $(this.wrapper);
		root.on("click", ".pm-reload", () => this.load());
		root.on("change", ".pm-scope", (e) => {
			this.scope = $(e.currentTarget).val();
			this.load();
		});
		root.on("click", ".pm-tabs button", (e) => {
			const btn = $(e.currentTarget);
			root.find(".pm-tabs button").removeClass("on");
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
		this.stage().html(
			`<div class="dpx-card"><div class="dpx-bb-skel">${[84, 70, 92, 62]
				.map((w) => `<i style="width:${w}%"></i>`)
				.join("")}</div></div>`
		);
	}

	render() {
		const h = this.health;
		const t = this.team;
		const done = t.closed_tasks || 0;
		const open = t.open_tasks || 0;
		const total = open + done || 1;

		// What needs a decision leads. A number nobody has to act on is not an alert.
		const alerts = [
			h.total_overdue_tasks
				? ["bad", `${h.total_overdue_tasks} task${h.total_overdue_tasks === 1 ? "" : "s"} past due`, "/backlog-board", "Open the board"]
				: null,
			h.total_open_requests
				? ["warn", `${h.total_open_requests} request${h.total_open_requests === 1 ? "" : "s"} waiting on a decision`, "/review-queue", "Review them"]
				: null,
		].filter(Boolean);

		$(this.wrapper).find(".pm-alerts").html(
			alerts.length
				? alerts
						.map(
							([tone, text, href, cta]) => `<a class="pm-alert ${tone}" href="${href}">
								<span class="dot"></span><span class="txt">${pm_esc(text)}</span>
								<span class="cta">${pm_esc(cta)}</span></a>`
						)
						.join("")
				: `<div class="pm-alert calm"><span class="dot"></span>
					<span class="txt">Nothing overdue and no request waiting. The queue is yours.</span></div>`
		);

		$(this.wrapper).find(".dpx-bb-status").html(
			`<b>${h.project_count || 0}</b> active projects<span class="sep">·</span>` +
				`<b>${open}</b> open tasks<span class="sep">·</span><b>${done}</b> closed` +
				`<span class="sp">${Math.round((done / total) * 100)}% of all work is finished</span>`
		);

		if (this.tab === "people") return this.render_people(t);
		return this.render_projects(h);
	}

	render_people(t) {
		const all = (t.developers || []).filter((d) => d.open_tasks);
		// Unassigned is not a person. Left in the list it is always the longest bar
		// and every real workload reads as a hairline beside it.
		const nobody = all.find((d) => d.full_name === "Unassigned");
		const devs = all.filter((d) => d !== nobody);

		if (!devs.length && !nobody) {
			return this.stage().html(
				pm_blank("Nobody has open work", "Every task is either finished or waiting to be assigned.")
			);
		}

		const most = devs.length ? Math.max(...devs.map((d) => d.open_tasks)) : 0;
		this.stage().html(
			(devs.length
				? `<div class="dpx-card"><div class="dpx-card-body" style="padding:4px 0">
						${devs.map((d) => pm_person(d, most)).join("")}
					</div></div>`
				: pm_blank("Nothing is assigned", "Every open task is still waiting for someone to take it.")) +
				(nobody
					? `<a class="pm-orphans" href="/backlog-board">
							<span class="n">${nobody.open_tasks.toLocaleString()}</span>
							<span class="txt">open tasks have nobody on them${
								nobody.overdue ? `, and ${nobody.overdue} are already overdue` : ""
							}</span>
							<span class="cta">Assign them</span>
						</a>`
					: "")
		);
	}

	render_projects(h) {
		const rows = h.projects || [];
		if (!rows.length) {
			return this.stage().html(
				pm_blank("No project in this scope", "Change the scope, or create a project to plan work against.")
			);
		}

		this.stage().html(
			`<div class="dpx-card"><div class="dpx-card-body dpx-bb-listwrap" style="padding:0 0 4px">
				<table class="dpx-bb-table">
					<colgroup><col><col style="width:110px"><col style="width:190px"><col style="width:96px"><col style="width:104px"></colgroup>
					<thead><tr><th>Project</th><th>Scope</th><th>Progress</th><th>Overdue</th><th>Requests</th></tr></thead>
					<tbody>${rows.map((p) => pm_project(p)).join("")}</tbody>
				</table>
			</div></div>`
		);
	}
};

function pm_person(d, most) {
	const share = Math.round((d.open_tasks / (most || 1)) * 100);
	const tone = d.overdue ? "bad" : d.due_today ? "warn" : "ok";
	return `
		<div class="pm-person">
			<span class="dpx-bb-av">${pm_esc(pm_initials(d.full_name))}</span>
			<span class="who">${pm_esc(d.full_name)}</span>
			<span class="bar"><i class="${tone}" style="width:${share}%"></i></span>
			<span class="n">${d.open_tasks} open</span>
			${d.due_today ? `<span class="tag warn">${d.due_today} due today</span>` : ""}
			${d.overdue ? `<span class="tag bad">${d.overdue} overdue</span>` : ""}
			${d.incoming_requests ? `<span class="tag calm">${d.incoming_requests} incoming</span>` : ""}
		</div>`;
}

function pm_project(p) {
	const pct = p.total_tasks ? Math.round((p.completed_tasks / p.total_tasks) * 100) : 0;
	return `
		<tr class="dpx-bb-row">
			<td><div class="subj"><a href="/app/project/${encodeURIComponent(p.name)}">${pm_esc(
				p.project_name || p.name
			)}</a></div></td>
			<td>${
				p.custom_project_scope
					? `<span class="dpx-bb-chip ${
							p.custom_project_scope === "External" ? "st-triage" : "st-todo"
						}">${pm_esc(p.custom_project_scope === "External" ? "Client" : "Internal")}</span>`
					: "—"
			}</td>
			<td><div class="pm-prog"><span class="bar"><i style="width:${pct}%"></i></span>
				<span class="pct">${pct}%</span>
				<span class="of">${p.completed_tasks}/${p.total_tasks}</span></div></td>
			<td class="num${p.overdue_tasks ? " late" : ""}">${p.overdue_tasks || 0}</td>
			<td class="num">${p.open_requests || 0}</td>
		</tr>`;
}

function pm_initials(name) {
	return String(name || "?")
		.split(/\s+/)
		.slice(0, 2)
		.map((part) => part[0] || "")
		.join("")
		.toUpperCase();
}

function pm_blank(heading, body) {
	return `<div class="dpx-card"><div class="dpx-bb-blank">
		<h3>${pm_esc(heading)}</h3><p>${pm_esc(body)}</p></div></div>`;
}

const PM_ICONS = {
	gauge: '<path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/>',
	users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
	folder: '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
	refresh: '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
};

function pm_ico(name, size) {
	const s = size || 15;
	return `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="currentColor"
		stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${PM_ICONS[name] || ""}</svg>`;
}

function pm_esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}
