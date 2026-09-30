window.upande_dev_tools = window.upande_dev_tools || {};

const PM_PREFS = "dpx-portfolio";
const PM_TABS = [
	["pulse", "Pulse"],
	["pipeline", "Pipeline"],
	["people", "People & Modules"],
	["releases", "Releases"],
	["forecast", "Forecast & Risk"],
];

upande_dev_tools.PmDashboard = class PmDashboard {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.data = null;
		const url = new URLSearchParams(location.search);
		const kept = pm_prefs();
		this.days = Number(url.get("days")) || kept.days || 30;
		this.scope = url.get("scope") || kept.scope || "";
		this.tab = url.get("tab") || kept.tab || "pulse";
		if (!PM_TABS.some(([key]) => key === this.tab)) this.tab = "pulse";
		this.render_shell();
		this.load();
	}

	load() {
		const icon = $(this.wrapper).find(".pm-reload").addClass("spin");
		if (!this.data) this.skeleton();
		frappe
			.xcall("upande_dev_tools.api.portfolio.get_portfolio", {
				days: this.days,
				scope: this.scope || null,
			})
			.then((data) => {
				this.data = data;
				$(this.wrapper).find(".bb-stage").removeAttr("aria-busy");
				this.render();
				icon.removeClass("spin");
			})
			.catch((e) => {
				icon.removeClass("spin");
				$(this.wrapper)
					.find(".bb-stage")
					.html(
						pm_blank(
							"Could not read the portfolio",
							String((e && e.message) || e) || "Reload to try again."
						)
					);
			});
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
							<div class="dpx-bb-tb-sub">What the team shipped, how fast, and what needs you</div>
						</div>
						<div class="dpx-bb-tb-act">
							<button class="dpx-bb-btn pm-export" type="button">Export</button>
							<button class="dpx-bb-btn pm-print" type="button">Print</button>
							<button class="dpx-bb-btn pm-share" type="button">Copy link</button>
							<span class="dpx-bb-div"></span>
							<button class="dpx-bb-ico pm-reload" type="button" title="Refresh">${pm_ico("refresh")}</button>
						</div>
					</div>
					<div class="dpx-bb-tb-cmd">
						<div class="dpx-bb-grp">
							<span class="dpx-bb-grp-lbl">Period</span>
							<div class="dpx-bb-views pm-days">
								${[7, 30, 90].map((d) => `<button data-days="${d}">${d} days</button>`).join("")}
							</div>
						</div>
						<span class="dpx-bb-sep"></span>
						<div class="dpx-bb-grp">
							<span class="dpx-bb-grp-lbl">Scope</span>
							<select class="dpx-bb-field pm-scope" aria-label="Project scope">
								<option value="">All projects</option>
								<option value="Internal">Internal</option>
								<option value="External">Client</option>
							</select>
						</div>
						<span class="dpx-bb-hint pm-window"></span>
					</div>
					<div class="pm-statusline"></div>
					<div class="pm-tabs" role="tablist">
						${PM_TABS.map(([key, label]) => `<button data-tab="${key}" role="tab">${pm_esc(label)}</button>`).join("")}
					</div>
				</div>
				<div class="bb-stage"></div>
				<div class="dpx-bb-status pm-foot"></div>
			</div>
		`);

		const root = $(this.wrapper);
		root.find(`.pm-days button[data-days="${this.days}"]`).addClass("on");
		root.find(".pm-scope").val(this.scope);
		root.find(`.pm-tabs button[data-tab="${this.tab}"]`).addClass("on");
		root.on("click", ".pm-tabs button", (e) => {
			this.tab = $(e.currentTarget).data("tab");
			root.find(".pm-tabs button").removeClass("on");
			$(e.currentTarget).addClass("on");
			this.save();
			if (this.data) this.render();
		});
		root.on("click", ".pm-reload", () => this.load());
		if (upande_dev_tools.attach_preview) upande_dev_tools.attach_preview(root[0]);
		root.on("click", ".pm-print", () => window.print());
		root.on("click", ".pm-export", () => this.export());
		root.on("click", ".pm-share", () => {
			const share = () =>
				frappe.show_alert({ message: __("Link copied."), indicator: "green" });
			if (navigator.clipboard)
				navigator.clipboard.writeText(location.href).then(share, () => {});
			else share();
		});
		root.on("click", ".pm-days button", (e) => {
			this.days = Number($(e.currentTarget).data("days"));
			root.find(".pm-days button").removeClass("on");
			$(e.currentTarget).addClass("on");
			this.save();
			this.load();
		});
		root.on("change", ".pm-scope", (e) => {
			this.scope = $(e.currentTarget).val();
			this.save();
			this.load();
		});
		document.addEventListener("keydown", (e) => {
			if (e.key !== "r" || /^(INPUT|SELECT|TEXTAREA)$/.test((e.target || {}).tagName || ""))
				return;
			this.load();
		});
	}

	save() {
		try {
			localStorage.setItem(PM_PREFS, JSON.stringify({ days: this.days, scope: this.scope, tab: this.tab }));
		} catch (e) {}
		const url = new URL(location.href);
		url.searchParams.set("days", this.days);
		if (this.scope) url.searchParams.set("scope", this.scope);
		else url.searchParams.delete("scope");
		url.searchParams.set("tab", this.tab);
		history.replaceState(null, "", url);
	}

	// A board pack wants a file, not a screenshot of a browser tab.
	export() {
		const d = this.data;
		if (!d) return;
		const cell = (v) => `"${String(v == null ? "" : v).replace(/"/g, '""')}"`;
		const row = (...v) => v.map(cell).join(",");
		const lines = [
			row("Upande dev portfolio"),
			row("Period", `${d.period.from} to ${d.period.to}`, `${d.period.days} days`),
			row("Scope", this.scope || "All projects"),
			row(""),
			row("Measure", "Value", "Previous", "Change"),
			...d.kpis.map((k) => row(k.label, k.value, k.was, k.delta)),
			row(""),
			row("Week", "Raised", "Delivered"),
			...d.flow.map((w) => row(w.label, w.raised, w.delivered)),
			row(""),
			row("Person", "Open", "Working", "Overdue", "Shipped (30d)"),
			...d.people.map((p) => row(p.name, p.open, p.working, p.overdue, p.delivered)),
			row(""),
			row("Module", "Delivered", "Open", "Overdue", "Bug share"),
			...d.modules.map((m) => row(m.module, m.delivered, m.open, m.late, m.bug_share)),
			row(""),
			row("Shipped", "Module", "By", "On"),
			...d.wins.map((w) => row(w.subject, w.custom_module, w.by.join("; "), w.completed_on)),
		];

		const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
		const a = document.createElement("a");
		a.href = URL.createObjectURL(blob);
		a.download = `portfolio-${d.period.from}-to-${d.period.to}.csv`;
		document.body.appendChild(a);
		a.click();
		a.remove();
		setTimeout(() => URL.revokeObjectURL(a.href), 1000);
		frappe.show_alert({ message: __("Exported the report."), indicator: "green" });
	}

	skeleton() {
		$(this.wrapper)
			.find(".bb-stage")
			.attr("aria-busy", "true")
			.html(
				`<div class="dpx-skel" aria-hidden="true">
				<div class="dpx-card sk-plain pm-hero">
					<div class="pm-hero-fig"><i class="sk w50"></i>
						<i class="sk" style="width:70%;height:38px;margin-top:8px"></i>
						<i class="sk w90" style="margin-top:10px"></i></div>
					<i class="sk" style="height:118px"></i>
				</div>
				<div class="dpx-card sk-plain pm-measures">
					${[1, 2, 3]
						.map(
							() => `<div class="m"><i class="sk w50"></i>
								<i class="sk" style="width:40%;height:18px"></i><i class="sk w70"></i></div>`
						)
						.join("")}
				</div>
				<div class="pm-grid">
					${[1, 2]
						.map(
							() =>
								`<div class="dpx-card sk-plain" style="padding:14px">${[1, 2, 3, 4]
									.map(() => '<i class="sk w90" style="margin-bottom:9px"></i>')
									.join("")}</div>`
						)
						.join("")}
				</div>
			</div>`
			);
	}

	render() {
		const d = this.data;
		$(this.wrapper).find(".pm-window").text(`${d.period.from} to ${d.period.to}`);

		$(this.wrapper)
			.find(".pm-foot")
			.html(
				`Measured from work that belongs to a project` +
					(d.period.excluded
						? `<span class="sep">·</span><b>${d.period.excluded.toLocaleString()}</b> tasks sit outside every project and are not counted`
						: "") +
					`<span class="sp">${d.wins.length} shipped in this window</span>`
			);

		const by = Object.fromEntries(d.kpis.map((k) => [k.key, k]));
		const overloaded = d.people.filter((p) => p.over_capacity);

		$(this.wrapper).find(".pm-statusline").html(pm_statusline(by, d, overloaded));

		const panels = {
			pulse: () => pm_tab_pulse(d, by),
			pipeline: () => pm_tab_pipeline(d),
			people: () => pm_tab_people(d),
			releases: () => pm_tab_releases(d),
			forecast: () => pm_tab_forecast(d),
		};
		$(this.wrapper)
			.find(".bb-stage")
			.html((panels[this.tab] || panels.pulse)());
	}
};

function pm_statusline(by, d, overloaded) {
	const chip = (label, value, tone) =>
		`<span>${pm_esc(label)}: <b${tone ? ` class="${tone}"` : ""}>${pm_esc(value)}</b></span>`;
	return [
		chip("Delivered", by.delivered.value ?? "—", by.delivered.value ? "" : "bad"),
		chip("Backlog Δ", by.net.value > 0 ? `+${by.net.value}` : by.net.value, by.net.value > 0 ? "bad" : ""),
		chip("Over capacity", `${overloaded.length} ${overloaded.length === 1 ? "person" : "people"}`, overloaded.length ? "warn" : ""),
		chip("Due ≤7d still open", d.due_soon.total, d.due_soon.total ? "bad" : ""),
		chip("At risk now", by.risk.value, by.risk.value ? "warn" : ""),
	].join("");
}

// ========== TAB PANELS ==========

function pm_tab_pulse(d, by) {
	return `
		${pm_needs_you(d.needs_you)}
		${pm_measures([by.delivered, by.cycle, by.request_lead, by.on_time, by.net, by.risk], "pm-measures6")}
		<div class="pm-grid">
			${pm_plan_vs_reality(d.plan_vs_reality)}
			${pm_data_trust(d.data_trust)}
		</div>
		<div class="pm-grid">
			${pm_risks(d.risks, by.waiting, by.risk)}
			${pm_requests(d.requests)}
		</div>
		${pm_hero(by.delivered, d.flow, d.period)}
		${pm_wins(d.wins)}
	`;
}

function pm_tab_pipeline(d) {
	const p = d.pipeline;
	return `
		${pm_stage_bar(p.stages)}
		<div class="pm-grid">
			${pm_funnel(p.funnel)}
			${pm_demand_by_area(p.demand)}
		</div>
		<div class="pm-grid">
			${pm_bug_share(d.modules)}
			${pm_deferred(p.deferred)}
		</div>
		${pm_intake_source(p.intake_source)}
	`;
}

function pm_tab_people(d) {
	return `
		<div class="pm-grid">
			${pm_people(d.people)}
			${pm_delivered_chart(d.people)}
		</div>
		${pm_modules(d.modules)}
		${pm_knowledge(d.modules)}
		${pm_projects(d.projects)}
	`;
}

function pm_tab_releases(d) {
	const r = d.releases;
	if (!r.total) return pm_blank("No deployments recorded", "Nothing to report on yet.");
	return `
		${pm_measures(
			[
				{ key: "total", label: "Deployments", value: r.total, unit: "", note: `over the last ${r.week_labels.length} weeks` },
				{
					key: "fail",
					label: "Change failure rate",
					value: r.failure_rate,
					unit: "%",
					note: `${r.failed} of ${r.total} attempts marked Failed`,
					direction: r.failure_rate ? "bad" : "good",
				},
			],
			"pm-measures2"
		)}
		${pm_release_frequency(r)}
		${pm_failure_hotspots(r.hotspots)}
		<p class="pm-note" style="margin-top:-4px">Ship lag, approval wait and time-to-recover aren't shown here yet - they depend on a Deployment Request linking back to the Request it came from, which isn't populated in practice today (see the system reference). They'll appear once that link is actually used.</p>
	`;
}

function pm_tab_forecast(d) {
	return `
		${pm_forecast_chart(d.forecast, d.due_soon)}
		${pm_ageing(d.ageing, d.period)}
		<div class="pm-grid">
			${pm_due_soon(d.due_soon)}
			${pm_stalled(d.stalled)}
		</div>
	`;
}

// ========== PULSE ==========

function pm_needs_you(items) {
	if (!items.length) {
		return `<div class="dpx-card"><div class="dpx-bb-blank"><h3>Nothing needs you right now</h3>
			<p>No decision, approval or confirmation is waiting on you at the moment.</p></div></div>`;
	}
	return `
		<div class="dpx-card">
			<div class="dpx-card-hd"><div class="ttl">Needs you</div>
				<span class="pm-tally"><b>${items.reduce((n, i) => n + i.n, 0)}</b> items</span></div>
			<div class="dpx-card-body">
				<div class="pm-needs">
					${items
						.map(
							(i) => `<a class="pm-need" href="${i.href}">
								<span class="n">${i.n}</span>
								<span class="title">${pm_esc(i.title)}</span>
								<span class="sub">${pm_esc(i.sub)}</span>
							</a>`
						)
						.join("")}
				</div>
			</div>
		</div>`;
}

function pm_plan_vs_reality(pvr) {
	if (!pvr.total) {
		return `<div class="dpx-card"><div class="dpx-card-hd"><div class="ttl">Plan vs reality</div></div>
			<div class="dpx-bb-blank"><p>Nothing was completed in this period yet.</p></div></div>`;
	}
	return `
		<div class="dpx-card">
			<div class="dpx-card-hd"><div class="ttl">Plan vs reality</div></div>
			<div class="dpx-card-body">
				<div class="pm-big"><span class="num ${pvr.pct ? "warn" : ""}">${pvr.pct}%</span>
					<span>of completed work never went through intake</span></div>
				<div class="pm-track pm-track--lg">
					<i class="fill" style="width:${100 - pvr.pct}%"></i><i class="fill warn" style="width:${pvr.pct}%"></i>
				</div>
				<p class="pm-note">${pvr.off_books} of ${pvr.total} completed tasks have no linked Request.</p>
				${
					pvr.items.length
						? `<div class="pm-off-books">${pvr.items
								.map(
									(t) => `<div class="row"><span class="t">${pm_esc(t.subject)}</span>
										<span class="mod">${t.custom_module ? pm_esc(t.custom_module) : "—"}</span>
										<span class="d">${t.days_since}d since done</span></div>`
								)
								.join("")}</div>`
						: ""
				}
			</div>
		</div>`;
}

function pm_data_trust(dt) {
	const meter = (label, pct) => `
		<div class="pm-meter">
			<div class="top"><span>${pm_esc(label)}</span><span class="num">${pct}%</span></div>
			<div class="pm-track"><i class="fill${pct < 60 ? " warn" : ""}" style="width:${pct}%"></i></div>
		</div>`;
	return `
		<div class="dpx-card">
			<div class="dpx-card-hd"><div class="ttl">Can you trust these numbers?</div></div>
			<div class="dpx-card-body">
				<div class="pm-big"><span class="num">${dt.total_open}</span><span>open tasks measured</span></div>
				${meter("Open tasks with a due date", dt.with_due_date)}
				${meter("Open tasks with an assignee", dt.with_assignee)}
				${meter("Open tasks with a module", dt.with_module)}
			</div>
		</div>`;
}

// ========== PIPELINE ==========

function pm_stage_bar(stagesData) {
	const stages = stagesData.stages.filter((s) => s.sample_size);
	if (!stages.length) {
		return `<div class="dpx-card"><div class="dpx-bb-blank"><h3>Not enough history yet</h3>
			<p>Stage timing needs requests that have actually moved through the workflow - check back once a few have.</p></div></div>`;
	}
	const total = stages.reduce((n, s) => n + (s.median_days || 0), 0) || 1;
	return `
		<div class="dpx-card">
			<div class="dpx-card-hd">
				<div class="ttl">Where a request spends its time</div>
				${stagesData.median_total_days != null ? `<span>Idea to closed: <b class="pm-num">${stagesData.median_total_days}d</b> median (${stagesData.sample_size} closed)</span>` : ""}
			</div>
			<div class="dpx-card-body">
				<div class="pm-stages">
					${stages
						.map(
							(s) => `<div class="pm-stage" style="width:${((s.median_days || 0) / total) * 100}%"
								title="${pm_esc(s.label)}: ${s.median_days}d median (${s.sample_size} sample${s.sample_size === 1 ? "" : "s"})">${s.median_days}d</div>`
						)
						.join("")}
				</div>
				<div class="pm-stages-labels">
					${stages.map((s) => `<div class="lbl"><strong>${pm_esc(s.label)}</strong><span class="pm-note">${s.sample_size} sample${s.sample_size === 1 ? "" : "s"}</span></div>`).join("")}
				</div>
			</div>
		</div>`;
}

function pm_funnel(f) {
	const top = Math.max(1, f.raised);
	const rows = [
		["Raised", f.raised],
		["Accepted", f.accepted],
		["Delivered", f.delivered],
		["Closed by raiser", f.closed],
	];
	return `
		<div class="dpx-card">
			<div class="dpx-card-hd"><div class="ttl">Funnel</div></div>
			<div class="dpx-card-body">
				${rows
					.map(
						([label, n]) => `<div class="pm-meter">
							<div class="top"><span>${label}</span><span class="num">${n}</span></div>
							<div class="pm-track pm-track--md"><i class="fill" style="width:${(n / top) * 100}%"></i></div>
						</div>`
					)
					.join("")}
				<p class="pm-note" style="border-top:1px solid var(--rule-soft);padding-top:10px;margin-top:2px">
					Not accepted: <b>${f.rejected}</b> rejected, <b>${f.deferred}</b> deferred,
					<b>${f.withdrawn}</b> withdrawn, <b>${f.still_deciding}</b> still deciding.
				</p>
			</div>
		</div>`;
}

function pm_demand_by_area(rows) {
	if (!rows.length) return `<div class="dpx-card"><div class="dpx-bb-blank"><p>Nothing raised in this period.</p></div></div>`;
	const top = Math.max(1, ...rows.map((r) => r.raised));
	return `
		<div class="dpx-card">
			<div class="dpx-card-hd"><div class="ttl">Demand by product area</div></div>
			<div class="dpx-card-body dpx-bb-listwrap" style="padding:0 0 4px">
				<table class="dpx-bb-table">
					<colgroup><col><col style="width:150px"><col style="width:80px"><col style="width:90px"><col style="width:70px"></colgroup>
					<thead><tr><th>Area</th><th>Raised</th><th>Accepted</th><th>Median wait</th><th>Open</th></tr></thead>
					<tbody>${rows
						.map(
							(r) => `<tr class="dpx-bb-row">
								<td><div class="subj">${pm_esc(r.area)}</div></td>
								<td><div class="pm-prog"><span class="bar"><i style="width:${(r.raised / top) * 100}%"></i></span><span class="pct">${r.raised}</span></div></td>
								<td class="num">${r.accepted_pct}%</td>
								<td class="num${r.median_wait != null && r.median_wait > 20 ? " late" : ""}">${r.median_wait != null ? r.median_wait + "d" : "—"}</td>
								<td class="num">${r.open}</td>
							</tr>`
						)
						.join("")}</tbody>
				</table>
			</div>
		</div>`;
}

function pm_bug_share(modules) {
	const rows = modules.filter((m) => m.bug_share != null).sort((a, b) => b.bug_share - a.bug_share);
	if (!rows.length) {
		return `<div class="dpx-card"><div class="dpx-card-hd"><div class="ttl">Bug share by product area</div></div>
			<div class="dpx-bb-blank"><p>No requests with a product area and a Bug/Feature type raised in the last 90 days.</p></div></div>`;
	}
	return `
		<div class="dpx-card">
			<div class="dpx-card-hd"><div class="ttl">Bug share by product area</div>
				<span class="pm-note">last 90 days</span></div>
			<div class="dpx-card-body">
				${rows
					.map(
						(m) => `<div class="pm-bugrow">
							<span class="nm">${pm_esc(m.module)}</span>
							<div class="pm-track pm-track--lg"><i class="fill warn" style="width:${m.bug_share}%"></i></div>
							<span class="num">${m.bug_share}%</span>
						</div>`
					)
					.join("")}
				<p class="pm-note">Share of that area's requests raised as a Bug rather than a Feature/Chore/etc.</p>
			</div>
		</div>`;
}

function pm_deferred(rows) {
	if (!rows.length) return `<div class="dpx-card"><div class="dpx-bb-blank"><p>Nothing is currently deferred.</p></div></div>`;
	return `
		<div class="dpx-card">
			<div class="dpx-card-hd"><div class="ttl">Deferred and forgotten</div></div>
			<div class="dpx-card-body" style="padding:4px 0 6px">
				${rows
					.map(
						(r) => `<a class="pm-win" href="/app/request/${encodeURIComponent(r.name)}">
							<span class="t">${pm_esc(r.title)}</span>
							<span class="mod">${r.area ? pm_esc(r.area) : "—"}</span>
							<span class="on ${r.days > 60 ? "warn" : ""}">${r.days}d ago</span>
						</a>`
					)
					.join("")}
			</div>
		</div>`;
}

function pm_intake_source(rows) {
	if (!rows.length) return "";
	return `
		<div class="dpx-card">
			<div class="dpx-card-hd"><div class="ttl">Median wait by intake source</div></div>
			<div class="dpx-card-body">
				<div class="pm-grid pm-grid--3">
					${rows
						.map(
							(r) => `<div class="pm-source">
								<span class="strong">${pm_esc(r.source)}</span>
								<span class="pm-note">${r.share}% of requests</span>
								<span class="num big${r.median_wait != null && r.median_wait > 30 ? " warn" : ""}">${r.median_wait != null ? r.median_wait + "d" : "—"}</span>
							</div>`
						)
						.join("")}
				</div>
			</div>
		</div>`;
}

// ========== PEOPLE & MODULES ==========

function pm_knowledge(modules) {
	const rows = modules.filter((m) => m.top_owner).sort((a, b) => b.top_owner.share - a.top_owner.share);
	if (!rows.length) {
		return `<div class="dpx-card"><div class="dpx-card-hd"><div class="ttl">Who holds the knowledge</div></div>
			<div class="dpx-bb-blank"><p>Not enough completed work per module in this period to tell yet.</p></div></div>`;
	}
	return `
		<div class="dpx-card">
			<div class="dpx-card-hd"><div class="ttl">Who holds the knowledge</div></div>
			<div class="pm-note" style="padding:0 22px 8px">Share of each module's completed tasks in this period done by one person</div>
			<div class="dpx-card-body">
				${rows
					.map(
						(m) => `<div class="pm-meter">
							<div class="top"><span><b>${pm_esc(m.module)}</b> <span class="pm-note">· ${pm_esc(m.top_owner.name)}</span></span>
								<span class="num${m.top_owner.share >= 70 ? " warn" : ""}">${m.top_owner.share}%</span></div>
							<div class="pm-track"><i class="fill${m.top_owner.share >= 70 ? " warn" : ""}" style="width:${m.top_owner.share}%"></i></div>
						</div>`
					)
					.join("")}
			</div>
		</div>`;
}

// ========== RELEASES ==========

function pm_release_frequency(r) {
	if (!r.frequency.length) return "";
	const top = Math.max(1, ...r.frequency.flatMap((row) => row.counts));
	const level = (n) => (n === 0 ? 0 : n <= top * 0.33 ? 1 : n <= top * 0.66 ? 2 : 3);
	return `
		<div class="dpx-card">
			<div class="dpx-card-hd"><div class="ttl">Deployments per instance, by week</div>
				<span class="pm-note">Darker means more deployments</span></div>
			<div class="dpx-card-body dpx-bb-listwrap">
				<table class="dpx-bb-table pm-heat">
					<thead><tr><th>Instance</th>${r.week_labels.map((w) => `<th class="num">${pm_esc(w)}</th>`).join("")}</tr></thead>
					<tbody>${r.frequency
						.map(
							(row) => `<tr class="dpx-bb-row">
								<td>${pm_esc(row.instance)}</td>
								${row.counts.map((n) => `<td class="pm-cell" data-level="${level(n)}">${n}</td>`).join("")}
							</tr>`
						)
						.join("")}</tbody>
				</table>
			</div>
		</div>`;
}

function pm_failure_hotspots(rows) {
	if (!rows.length) {
		return `<div class="dpx-card"><div class="dpx-bb-blank"><p>No failed deployments in this window - nothing to flag.</p></div></div>`;
	}
	return `
		<div class="dpx-card">
			<div class="dpx-card-hd"><div class="ttl">Failure hotspots</div>
				<span class="pm-note">Failed attempts ÷ attempts, per app and instance</span></div>
			<div class="dpx-card-body" style="padding:4px 0 6px">
				${rows
					.map(
						(h) => `<div class="pm-win">
							<span class="t">${pm_esc(h.app)}</span>
							<span class="mod">${pm_esc(h.instance)}</span>
							<span class="on warn">${h.failed} of ${h.total} failed (${h.rate}%)</span>
						</div>`
					)
					.join("")}
			</div>
		</div>`;
}

// ========== FORECAST ==========

// A real, measured backlog-size line, plus a probabilistic completion range built by
// resampling actual weekly throughput (Monte Carlo) instead of one average - this
// replaced an earlier version that projected forward using a due-date "hit rate" that
// could exceed 100% and silently excluded undated/overdue tasks from the forecast
// entirely. This version counts every open task and says plainly when there isn't
// enough completed history yet to forecast from.
function pm_forecast_chart(fc, due_soon) {
	if (fc.done) {
		return `<div class="dpx-card"><div class="dpx-bb-blank"><h3>Nothing open right now</h3>
			<p>There's no backlog left to forecast.</p></div></div>`;
	}
	const hist = fc.history;
	const maxY = Math.max(1, ...hist.map((p) => p.open));
	const W = 680,
		H = 170,
		padL = 30,
		padR = 10,
		padT = 10,
		padB = 34;
	const plotW = W - padL - padR,
		plotH = H - padT - padB;
	const xAt = (i) => padL + (i / (hist.length - 1)) * plotW;
	const yAt = (v) => padT + plotH - (Math.min(v, maxY) / maxY) * plotH;
	const histPath = hist.map((p, i) => `${i === 0 ? "M" : "L"}${xAt(i).toFixed(1)},${yAt(p.open).toFixed(1)}`).join(" ");
	const todayX = xAt(hist.length - 1);
	const todayY = yAt(hist[hist.length - 1].open);

	const gridTicks = 3;
	const gridlines = Array.from({ length: gridTicks + 1 }, (_, i) => {
		const v = Math.round((maxY / gridTicks) * i);
		const y = yAt(v);
		return `<line x1="${padL}" y1="${y.toFixed(1)}" x2="${W - padR}" y2="${y.toFixed(1)}" class="grid"></line>
			<text x="${padL - 6}" y="${(y + 3).toFixed(1)}" class="ax" text-anchor="end">${v}</text>`;
	}).join("");
	const xLabels = hist
		.map((p, i) => (i % 2 === 0 ? `<text x="${xAt(i).toFixed(1)}" y="${H - 8}" class="ax" text-anchor="middle">${pm_esc(p.label)}</text>` : ""))
		.join("");

	let projection = "";
	let dateLine = "";
	if (fc.insufficient) {
		dateLine = `<p class="pm-note">${pm_esc(fc.note)}</p>`;
	} else {
		const spanWeeks = Math.max(fc.p85_weeks, 1);
		const pxPerWeek = plotW / (hist.length - 1);
		const p50x = todayX + fc.p50_weeks * pxPerWeek;
		const p85x = todayX + fc.p85_weeks * pxPerWeek;
		const rightEdge = W - padR;
		const clampX = (x) => Math.min(x, rightEdge + 60);
		projection = `
			<line x1="${todayX.toFixed(1)}" y1="${todayY.toFixed(1)}" x2="${clampX(p85x).toFixed(1)}" y2="${padT}" class="line proj85"></line>
			<line x1="${todayX.toFixed(1)}" y1="${todayY.toFixed(1)}" x2="${clampX(p50x).toFixed(1)}" y2="${padT}" class="line proj50"></line>
			<circle cx="${todayX.toFixed(1)}" cy="${todayY.toFixed(1)}" r="3.5" class="today-dot"></circle>`;
		dateLine = fc.capped
			? `<p class="pm-note">At the pace of the last 12 weeks, there isn't a reliable date - the simulation ran past 5 years without clearing the backlog most of the time.</p>`
			: `<p class="pm-note">50% of simulated outcomes clear the current backlog by <b>${pm_esc(fc.p50_date)}</b> (${fc.p50_weeks}w); 85% clear it by <b>${pm_esc(fc.p85_date)}</b> (${fc.p85_weeks}w). Built by resampling the last ${hist.length} weeks' real completion counts 2,000 times, not by averaging them.</p>`;
	}

	return `
		<div class="dpx-card">
			<div class="dpx-card-hd"><div class="ttl">Backlog forecast</div>
				<span class="pm-tally">
					<span class="key"><i class="hist"></i>measured</span>
					${!fc.insufficient ? `<span class="key"><i class="proj"></i>50% / 85% likely</span>` : ""}
				</span></div>
			<div class="dpx-card-body">
				<svg class="pm-burn" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
					${gridlines}
					${projection}
					<path d="${histPath}" class="line hist"></path>
					${xLabels}
				</svg>
				${dateLine}
			</div>
		</div>`;
}

function pm_signed(v) {
	if (v == null) return "—";
	return v > 0 ? `+${v}` : `${v}`;
}

// The headline number and the history behind it belong together; splitting them
// into a tile and a chart makes a reader carry the figure across the page.
function pm_hero(k, flow, period) {
	return `
		<div class="dpx-card pm-hero">
			<div class="pm-hero-fig">
				<div class="lbl">Delivered</div>
				<div class="val">${pm_esc(k.value === null ? "—" : k.value)}</div>
				<div class="sub">${pm_esc(pm_change(k, `in the previous ${period.days} days`))}</div>
				${
					period.clears_on
						? `<div class="fore">At this rate the ${period.open} open clear around
							<b>${pm_esc(period.clears_on)}</b></div>`
						: ""
				}
				<div class="key"><span><i class="out"></i>delivered</span><span><i class="in"></i>raised</span></div>
			</div>
			${pm_flow(flow)}
		</div>`;
}

function pm_measures(list, extraClass) {
	const cls = extraClass || "";
	return `
		<div class="dpx-card pm-measures${cls ? ` ${cls}` : ""}">
			${list
				.map(
					(k) => `<div class="m" title="${pm_esc(k.note)}">
						<span class="lbl">${pm_esc(k.label)}</span>
						<span class="val">${pm_esc(pm_value(k))}<em>${pm_esc(k.unit)}</em></span>
						<span class="chg ${k.direction || ""}">${pm_esc(k.was !== undefined ? pm_change(k, "before") : k.note || "")}</span>
					</div>`
				)
				.join("")}
		</div>`;
}

function pm_value(k) {
	if (k.value === null || k.value === undefined) return "—";
	return k.signed && k.value > 0 ? `+${k.value}` : k.value;
}

function pm_change(k, tail) {
	if (k.delta === null || k.delta === undefined) return "measured right now";
	if (!k.delta) return `unchanged ${tail}`;
	const arrow = k.delta > 0 ? "▲" : "▼";
	return `${arrow} ${Math.abs(k.delta)}${k.unit} against ${k.was}${k.unit} ${tail}`;
}

function pm_flow(weeks) {
	const top = Math.max(1, ...weeks.map((w) => Math.max(w.raised, w.delivered)));
	return `
		<div class="pm-flow-wrap">
				<div class="pm-flow">
					${weeks
						.map(
							(w) => `<div class="col" title="Week of ${pm_esc(w.label)}: ${
								w.raised
							} raised, ${w.delivered} delivered">
								<div class="pair">
									<i class="in" style="height:${Math.round((w.raised / top) * 100)}%"></i>
									<i class="out" style="height:${Math.round((w.delivered / top) * 100)}%"></i>
								</div>
								<span class="lbl">${pm_esc(w.label)}</span>
							</div>`
						)
						.join("")}
				</div>
		</div>`;
}

function pm_risks(risks, waiting, risk) {
	return `
		<div class="dpx-card">
			<div class="dpx-card-hd"><div class="ttl">Needs attention</div>
				<span class="pm-tally">${waiting && waiting.value ? `<b>${waiting.value}</b> awaiting you` : ""}${
		waiting && waiting.value && risk && risk.value ? "<i></i>" : ""
	}${risk && risk.value ? `<b>${risk.value}</b> at risk` : ""}</span></div>
			<div class="dpx-card-body" style="padding:4px 0 6px">
				${
					risks.length
						? risks
								.map(
									(
										r
									) => `<a class="pm-risk" href="/app/${r.doctype.toLowerCase()}/${encodeURIComponent(
										r.name
									)}">
										<span class="dpx-bb-chip ${
											{
												"On hold": "st-in-review",
												"Awaiting you": "st-triage",
											}[r.kind] || "st-blocked"
										}">${pm_esc(r.kind)}</span>
										${r.priority ? `<span class="dpx-bb-chip pr-${r.priority.toLowerCase()}">${pm_esc(r.priority)}</span>` : ""}
										<span class="t">${pm_esc(r.title)}</span>
										<span class="who">${pm_esc(r.who.join(", ") || "Unassigned")}</span>
										<span class="days">${r.days}d</span>
									</a>`
								)
								.join("")
						: '<div class="dpx-bb-blank"><p>Nothing is overdue or on hold.</p></div>'
				}
			</div>
		</div>`;
}

function pm_people(people) {
	const real = people.filter((p) => p.name !== "Unassigned");
	const nobody = people.find((p) => p.name === "Unassigned");
	const most = Math.max(1, ...real.map((p) => p.open));
	return `
		<div class="dpx-card">
			<div class="dpx-card-hd"><div class="ttl">Who is carrying what</div></div>
			<div class="dpx-card-body" style="padding:4px 0 6px">
				${
					real.length
						? real
								.map(
									(p) => `<div class="pm-person">
										<span class="dpx-bb-av">${pm_esc(pm_initials(p.name))}</span>
										<span class="who">${pm_esc(p.name)}</span>
										<span class="bar"><i class="${p.overdue ? "bad" : ""}" style="width:${Math.round(
										(p.open / most) * 100
									)}%"></i></span>
										<span class="n">${p.open} open</span>
										${p.working ? `<span class="tag grey">${p.working} WIP</span>` : ""}
										${p.delivered ? `<span class="tag ok">${p.delivered} shipped</span>` : ""}
										${p.overdue ? `<span class="tag bad">${p.overdue} late</span>` : ""}
										${p.idle ? `<span class="tag grey" title="No open work, nothing delivered in 30 days">Idle</span>` : ""}
										${p.over_capacity ? `<span class="tag cap" title="Carrying more than the team can sustain">Over capacity</span>` : ""}
									</div>`
								)
								.join("")
						: '<div class="dpx-bb-blank"><p>Nobody has open work.</p></div>'
				}
				${
					nobody && nobody.open
						? `<a class="pm-orphans" href="/backlog-board"><span class="n">${nobody.open}</span>
							<span class="txt">open tasks have nobody on them</span>
							<span class="cta">Assign them</span></a>`
						: ""
				}
			</div>
		</div>`;
}

// "Who is carrying what" (open + overdue) is load. This is output - a different
// axis on the same people, not a re-cut of the same numbers, so it earns its
// place next to it rather than repeating it as a second shape.
function pm_delivered_chart(people) {
	const real = people.filter((p) => p.name !== "Unassigned" && p.delivered > 0).sort((a, b) => b.delivered - a.delivered);
	if (!real.length) return "";
	const most = Math.max(1, ...real.map((p) => p.delivered));
	return `
		<div class="dpx-card">
			<div class="dpx-card-hd"><div class="ttl">Who is delivering</div>
				<span class="pm-tally">last 30 days</span></div>
			<div class="dpx-card-body" style="padding:4px 0 6px">
				${real
					.map(
						(p) => `<div class="pm-person">
							<span class="dpx-bb-av">${pm_esc(pm_initials(p.name))}</span>
							<span class="who">${pm_esc(p.name)}</span>
							<span class="bar"><i style="width:${Math.round((p.delivered / most) * 100)}%"></i></span>
							<span class="n">${p.delivered} shipped</span>
						</div>`
					)
					.join("")}
			</div>
		</div>`;
}

function pm_due_soon(due_soon) {
	const rows = due_soon.items;
	return `
		<div class="dpx-card">
			<div class="dpx-card-hd"><div class="ttl">Due in the next 7 days</div>
				<span class="pm-tally"><b>${due_soon.total}</b> still open</span></div>
			<div class="dpx-card-body" style="padding:4px 0 6px">
				${
					rows.length
						? rows
								.map(
									(r) => `<a class="pm-risk" href="/app/task/${encodeURIComponent(r.name)}">
										<span class="dpx-bb-chip st-in-review">${pm_esc(String(r.exp_end_date).slice(0, 10))}</span>
										<span class="t">${pm_esc(r.subject)}</span>
										<span class="who">${pm_esc(r.who.join(", "))}</span>
									</a>`
								)
								.join("")
						: '<div class="dpx-bb-blank"><p>Nothing is due in the next 7 days.</p></div>'
				}
			</div>
		</div>`;
}

// A backlog that is merely large is one thing. A backlog that is old is another.
function pm_ageing(bands, period) {
	const total = bands.reduce((n, b) => n + b.count, 0) || 1;
	const stale = bands.slice(2).reduce((n, b) => n + b.count, 0);
	return `
		<div class="dpx-card">
			<div class="dpx-card-hd"><div class="ttl">How old the open work is</div>
				<span class="pm-tally"><b>${period.open}</b> open</span></div>
			<div class="dpx-card-body">
				<div class="pm-age-bar">
					${bands
						.map(
							(b, i) =>
								`<i class="b${i}" style="width:${(b.count / total) * 100}%"
									title="${pm_esc(b.label)}: ${b.count}"></i>`
						)
						.join("")}
				</div>
				<div class="pm-age-key">
					${bands
						.map(
							(b, i) =>
								`<span><i class="b${i}"></i>${pm_esc(b.label)}<b>${
									b.count
								}</b></span>`
						)
						.join("")}
				</div>
				<p class="pm-note">${
					stale
						? `${stale} ${
								stale === 1 ? "item has" : "items have"
						  } been open longer than a fortnight.`
						: "Nothing has been sitting longer than a fortnight."
				}</p>
			</div>
		</div>`;
}

// A part-of-whole breakdown reads faster as a donut than as four bars - this is
// exactly the shape (categories that sum to one total) a pie chart is for.
function pm_requests(r) {
	if (!r.total) return `<div class="dpx-card"><div class="dpx-bb-blank"><p>Nothing has been raised yet.</p></div></div>`;
	return `
		<div class="dpx-card">
			<div class="dpx-card-hd"><div class="ttl">What people asked for</div>
				<span class="pm-tally"><b>${r.total}</b> raised</span></div>
			<div class="dpx-card-body">
				${pm_donut(
					[
						{ label: "Accepted", value: r.accepted, color: "var(--bb-solid-green)" },
						{ label: "Deferred", value: r.deferred, color: "var(--bb-solid-amber)" },
						{ label: "Turned down", value: r.rejected, color: "var(--bb-solid-red)" },
						{ label: "Still waiting", value: r.waiting, color: "#c9c7bd" },
					],
					{ center: r.total, centerSub: "raised" }
				)}
				${r.waiting ? `<p class="pm-note">Longest wait is ${r.oldest_wait} days.</p>` : ""}
			</div>
		</div>`;
}

// Generic donut: an SVG ring built from stroke-dasharray segments, plus a legend.
// Nothing here is chart-library output - it's the same hand-rolled convention as
// every bar on this page, just a shape better suited to a share-of-total question.
function pm_donut(segments, opts) {
	opts = opts || {};
	const total = segments.reduce((n, s) => n + s.value, 0) || 1;
	const r = 34,
		cx = 44,
		cy = 44,
		circumference = 2 * Math.PI * r;
	let offset = 0;
	const arcs = segments
		.filter((s) => s.value > 0)
		.map((s) => {
			const len = (s.value / total) * circumference;
			const arc = `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${s.color}"
				stroke-width="14" stroke-dasharray="${len} ${circumference - len}"
				stroke-dashoffset="${-offset}" transform="rotate(-90 ${cx} ${cy})"></circle>`;
			offset += len;
			return arc;
		})
		.join("");
	return `
		<div class="pm-donut-wrap">
			<svg class="pm-donut" viewBox="0 0 88 88" width="112" height="112">
				<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="var(--rule)" stroke-width="14"></circle>
				${arcs}
				${
					opts.center != null
						? `<text x="${cx}" y="${cy - 3}" class="num" text-anchor="middle">${pm_esc(opts.center)}</text>
							<text x="${cx}" y="${cy + 11}" class="sub" text-anchor="middle">${pm_esc(opts.centerSub || "")}</text>`
						: ""
				}
			</svg>
			<div class="pm-donut-legend">
				${segments
					.map(
						(s) => `<div class="row">
							<i style="background:${s.color}"></i>
							<span class="l">${pm_esc(s.label)}</span>
							<span class="n">${s.value}</span>
						</div>`
					)
					.join("")}
			</div>
		</div>`;
}

function pm_stalled(rows) {
	if (!rows.length) return "";
	return `
		<div class="dpx-card">
			<div class="dpx-card-hd"><div class="ttl">Started and gone quiet</div>
				<span class="pm-tally"><b>${rows.length}</b> untouched for a fortnight</span></div>
			<div class="dpx-card-body" style="padding:4px 0 6px">
				${rows
					.map(
						(r) => `<a class="pm-win pm-stall" href="/app/task/${encodeURIComponent(
							r.name
						)}"
							data-id="Task:${pm_esc(r.name)}">
							<span class="dpx-bb-chip st-${String(r.status).toLowerCase().replace(/\s+/g, "-")}">${pm_esc(
							r.status
						)}</span>
							<span class="t">${pm_esc(r.subject)}</span>
							${r.custom_module ? `<span class="mod">${pm_esc(r.custom_module)}</span>` : ""}
							<span class="by">${pm_esc(r.who.join(", "))}</span>
							<span class="on">${r.quiet}d quiet</span>
						</a>`
					)
					.join("")}
			</div>
		</div>`;
}

// One bar per module, all scaled to the same largest-module width - so a module's
// bar length shows its size relative to the others at a glance, and the three
// segments inside it show the delivered/open/overdue mix.
function pm_modules(modules) {
	if (!modules.length) return "";
	const maxTotal = Math.max(1, ...modules.map((m) => m.total));
	const seg = (n, total) => (total ? (n / total) * 100 : 0);
	return `
		<div class="dpx-card">
			<div class="dpx-card-hd"><div class="ttl">Module health</div>
				<span class="pm-tally"><b>${modules.length}</b> modules</span></div>
			<div class="dpx-card-body">
				<div class="pm-modbars">
					${modules
						.map((m) => {
							const barWidth = (m.total / maxTotal) * 100;
							return `<div class="pm-modbar" title="${pm_esc(m.module)}: ${m.delivered} delivered, ${
								m.open
							} open, ${m.late} overdue${m.bug_share != null ? `, ${m.bug_share}% bug share` : ""}">
								<span class="nm">${pm_esc(m.module)}</span>
								<span class="track"><span class="bar" style="width:${barWidth}%">
									<i class="done" style="width:${seg(m.delivered, m.total)}%"></i>
									<i class="open" style="width:${seg(m.open, m.total)}%"></i>
									<i class="late" style="width:${seg(m.late, m.total)}%"></i>
								</span></span>
								<span class="n">${m.total}</span>
								${m.bug_share != null ? `<span class="dpx-bb-chip tiny${m.bug_share >= 40 ? " st-blocked" : ""}">${m.bug_share}% bug</span>` : ""}
							</div>`;
						})
						.join("")}
				</div>
				<div class="pm-units-key">
					<span><i class="done"></i>delivered this period</span>
					<span><i class="open"></i>open</span>
					<span><i class="late"></i>overdue</span>
				</div>
			</div>
		</div>`;
}

function pm_projects(rows) {
	if (!rows.length) return "";
	return `
		<div class="dpx-card">
			<div class="dpx-card-hd"><div class="ttl">By project</div></div>
			<div class="dpx-card-body dpx-bb-listwrap" style="padding:0 0 4px">
				<table class="dpx-bb-table">
					<colgroup><col><col style="width:104px"><col style="width:220px"><col style="width:94px"><col style="width:104px"></colgroup>
					<thead><tr><th>Project</th><th>Scope</th><th>Finished</th><th>Overdue</th><th>Open requests</th></tr></thead>
					<tbody>${rows
						.map((p) => {
							const pct = p.total ? Math.round((p.done / p.total) * 100) : 0;
							return `<tr class="dpx-bb-row">
								<td><div class="subj"><a href="/app/project/${encodeURIComponent(p.name)}">${pm_esc(
								p.project_name || p.name
							)}</a></div></td>
								<td>${
									p.custom_project_scope
										? `<span class="dpx-bb-chip ${
												p.custom_project_scope === "External"
													? "st-triage"
													: "st-todo"
										  }">${pm_esc(
												p.custom_project_scope === "External"
													? "Client"
													: "Internal"
										  )}</span>`
										: '<span class="muted">—</span>'
								}</td>
								<td><div class="pm-prog"><span class="bar"><i style="width:${pct}%"></i></span>
									<span class="pct">${pct}%</span><span class="of">${p.done}/${p.total}</span></div></td>
								<td class="num${p.overdue ? " late" : ""}">${p.overdue}</td>
								<td class="num">${p.requests}</td>
							</tr>`;
						})
						.join("")}</tbody>
				</table>
			</div>
		</div>`;
}

function pm_wins(wins) {
	return `
		<div class="dpx-card">
			<div class="dpx-card-hd"><div class="ttl">Shipped</div><span class="md-n">${
				wins.length
			}</span></div>
			<div class="dpx-card-body" style="padding:4px 0 6px">
				${
					wins.length
						? wins
								.slice(0, 8)
								.map(
									(w) => `<a class="pm-win" href="/app/task/${encodeURIComponent(
										w.name
									)}">
										<span class="tick">${pm_ico("check", 11)}</span>
										<span class="t">${pm_esc(w.subject)}</span>
										${w.custom_module ? `<span class="mod">${pm_esc(w.custom_module)}</span>` : ""}
										<span class="by">${pm_esc(w.by.join(", "))}</span>
										<span class="on">${pm_esc(w.completed_on)}</span>
									</a>`
								)
								.join("")
						: '<div class="dpx-bb-blank"><p>Nothing finished in this window yet.</p></div>'
				}
				${
					wins.length > 8
						? `<a class="pm-more" href="/backlog-board">and ${
								wins.length - 8
						  } more</a>`
						: ""
				}
			</div>
		</div>`;
}

function pm_initials(name) {
	return String(name || "?")
		.split(/\s+/)
		.slice(0, 2)
		.map((p) => p[0] || "")
		.join("")
		.toUpperCase();
}

function pm_prefs() {
	try {
		return JSON.parse(localStorage.getItem(PM_PREFS) || "{}") || {};
	} catch (e) {
		return {};
	}
}

function pm_blank(heading, body) {
	return `<div class="dpx-card"><div class="dpx-bb-blank">
		<h3>${pm_esc(heading)}</h3><p>${pm_esc(body)}</p></div></div>`;
}

const PM_ICONS = {
	gauge: '<path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/>',
	check: '<path d="M20 6 9 17l-5-5"/>',
	refresh:
		'<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
};

function pm_ico(name, size) {
	const s = size || 15;
	return `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="currentColor"
		stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${
			PM_ICONS[name] || ""
		}</svg>`;
}

function pm_esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}
