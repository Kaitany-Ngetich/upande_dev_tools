window.upande_dev_tools = window.upande_dev_tools || {};

const PM_PREFS = "dpx-portfolio";

upande_dev_tools.PmDashboard = class PmDashboard {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.data = null;
		const url = new URLSearchParams(location.search);
		const kept = pm_prefs();
		this.days = Number(url.get("days")) || kept.days || 30;
		this.scope = url.get("scope") || kept.scope || "";
		this.render_shell();
		this.load();
	}

	load() {
		const icon = $(this.wrapper).find(".pm-reload").addClass("spin");
		if (!this.data) this.skeleton();
		Promise.all([
			frappe.xcall("upande_dev_tools.api.portfolio.get_portfolio", {
				days: this.days,
				scope: this.scope || null,
			}),
			frappe
				.xcall("upande_dev_tools.api.deployments.get_recent_deployments")
				.catch(() => null),
		])
			.then(([data, deployments]) => {
				this.data = data;
				this.deployments = deployments;
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
				</div>
				<div class="bb-stage"></div>
				<div class="dpx-bb-status pm-foot"></div>
			</div>
		`);

		const root = $(this.wrapper);
		root.find(`.pm-days button[data-days="${this.days}"]`).addClass("on");
		root.find(".pm-scope").val(this.scope);
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
			localStorage.setItem(PM_PREFS, JSON.stringify({ days: this.days, scope: this.scope }));
		} catch (e) {}
		const url = new URL(location.href);
		url.searchParams.set("days", this.days);
		if (this.scope) url.searchParams.set("scope", this.scope);
		else url.searchParams.delete("scope");
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
			row("Person", "Open", "Overdue", "Shipped (30d)"),
			...d.people.map((p) => row(p.name, p.open, p.overdue, p.delivered)),
			row(""),
			row("Module", "Delivered", "Open", "Overdue"),
			...d.modules.map((m) => row(m.module, m.delivered, m.open, m.late)),
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

		$(this.wrapper).find(".bb-stage").html(`
			${pm_hero(by.delivered, d.flow, d.period)}
			${pm_measures([by.cycle, by.on_time, by.net])}
			<div class="pm-grid">
				${pm_risks(d.risks, by.waiting, by.risk)}
				${pm_people(d.people)}
			</div>
			<div class="pm-grid">
				${pm_wins(d.wins)}
				${pm_modules(d.modules)}
			</div>
			<div class="pm-grid">
				${pm_ageing(d.ageing, d.period)}
				${pm_requests(d.requests)}
			</div>
			${pm_projects(d.projects)}
			${pm_stalled(d.stalled)}
			${this.deployments ? pm_deployments(this.deployments) : ""}
		`);
	}
};

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

function pm_measures(list) {
	return `
		<div class="dpx-card pm-measures">
			${list
				.map(
					(k) => `<div class="m" title="${pm_esc(k.note)}">
						<span class="lbl">${pm_esc(k.label)}</span>
						<span class="val">${pm_esc(pm_value(k))}<em>${pm_esc(k.unit)}</em></span>
						<span class="chg ${k.direction}">${pm_esc(pm_change(k, "before"))}</span>
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
										${p.delivered ? `<span class="tag ok">${p.delivered} shipped</span>` : ""}
										${p.overdue ? `<span class="tag bad">${p.overdue} late</span>` : ""}
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

// A dot per task. Size and mix read at once, where a bar makes you decode
// proportions - and a module with forty open items should look like forty.
function pm_modules(modules) {
	if (!modules.length) return "";
	const dots = (n, cls) => Array.from({ length: n }, () => `<i class="${cls}"></i>`).join("");
	return `
		<div class="dpx-card">
			<div class="dpx-card-hd"><div class="ttl">Where the work is</div>
				<span class="pm-tally"><b>${modules.length}</b> modules</span></div>
			<div class="dpx-card-body">
				<div class="pm-units">
					${modules
						.map((m) => {
							const cap = 48;
							const total = m.total;
							const scale = total > cap ? cap / total : 1;
							const at = (n) => Math.round(n * scale);
							return `<div class="u" title="${pm_esc(m.module)}: ${
								m.delivered
							} delivered, ${m.open} open, ${m.late} overdue">
								<span class="nm">${pm_esc(m.module)}</span>
								<span class="dots">${dots(at(m.delivered), "done")}${dots(at(m.open), "open")}${dots(
								at(m.late),
								"late"
							)}</span>
								<span class="n">${total > cap ? `${total}` : ""}</span>
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

// What happens to what people ask for. A team that rejects nothing is not
// triaging; one that answers nothing is a black hole.
function pm_requests(r) {
	const decided = r.accepted + r.rejected + r.deferred;
	const share = (n) => (r.total ? Math.round((n / r.total) * 100) : 0);
	return `
		<div class="dpx-card">
			<div class="dpx-card-hd"><div class="ttl">What people asked for</div>
				<span class="pm-tally"><b>${r.total}</b> raised</span></div>
			<div class="dpx-card-body">
				<div class="pm-req">
					${[
						["Accepted", r.accepted, "ok"],
						["Deferred", r.deferred, "warn"],
						["Turned down", r.rejected, "bad"],
						["Still waiting", r.waiting, "calm"],
					]
						.map(
							([label, n, tone]) => `<div class="r ${tone}">
								<span class="n">${n}</span>
								<span class="l">${pm_esc(label)}</span>
								<span class="bar"><i style="width:${share(n)}%"></i></span>
							</div>`
						)
						.join("")}
				</div>
				<p class="pm-note">${
					r.waiting
						? `Longest wait is ${r.oldest_wait} days.`
						: decided
						? "Everything raised has had an answer."
						: "Nothing has been raised yet."
				}</p>
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

const PM_DEPLOY_STATE = {
	Requested: "st-triage",
	"In Progress": "st-in-progress",
	Deployed: "st-done",
	Failed: "st-blocked",
};

function pm_deployments(d) {
	const rows = d.recent || [];
	const counts = d.counts_by_state || {};
	if (!rows.length) return "";
	return `
		<div class="dpx-card">
			<div class="dpx-card-hd"><div class="ttl">Deployments</div>
				<span class="pm-tally">${Object.entries(counts)
					.map(([state, n]) => `<b>${n}</b> ${pm_esc(state.toLowerCase())}`)
					.join("<i></i>")}</span></div>
			<div class="dpx-card-body dpx-bb-listwrap" style="padding:0 0 4px">
				<table class="dpx-bb-table">
					<colgroup><col><col style="width:160px"><col style="width:120px"><col style="width:120px"><col style="width:104px"><col style="width:130px"></colgroup>
					<thead><tr><th>App</th><th>Instance</th><th>Branch</th><th>Requested by</th><th>Raised</th><th>State</th></tr></thead>
					<tbody>${rows
						.map(
							(r) => `<tr class="dpx-bb-row">
								<td><a href="/app/deployment-request/${encodeURIComponent(r.name)}">${pm_esc(r.app)}</a></td>
								<td>${pm_esc(r.instance)}</td>
								<td>${pm_esc(r.branch || "—")}</td>
								<td>${pm_esc((r.requested_by_user || "").split("@")[0])}</td>
								<td>${pm_esc(String(r.creation || "").slice(0, 10))}</td>
								<td><span class="dpx-bb-chip ${PM_DEPLOY_STATE[r.workflow_state] || "st-triage"}">${pm_esc(
								r.workflow_state
							)}</span></td>
							</tr>`
						)
						.join("")}</tbody>
				</table>
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
