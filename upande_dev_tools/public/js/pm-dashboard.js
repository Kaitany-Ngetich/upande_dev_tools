window.upande_dev_tools = window.upande_dev_tools || {};

const PM_PREFS = "dpx-portfolio";

upande_dev_tools.PmDashboard = class PmDashboard {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.data = null;
		const kept = pm_prefs();
		this.days = kept.days || 30;
		this.scope = kept.scope || "";
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
					.html(pm_blank("Could not read the portfolio", String((e && e.message) || e) || "Reload to try again."));
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
			if (e.key !== "r" || /^(INPUT|SELECT|TEXTAREA)$/.test((e.target || {}).tagName || "")) return;
			this.load();
		});
	}

	save() {
		try {
			localStorage.setItem(PM_PREFS, JSON.stringify({ days: this.days, scope: this.scope }));
		} catch (e) {}
	}

	skeleton() {
		$(this.wrapper).find(".bb-stage").attr("aria-busy", "true").html(
			`<div class="dpx-skel" aria-hidden="true">
				<div class="pm-kpis">${Array.from({ length: 6 }, () =>
					`<div class="pm-kpi"><i class="sk w50"></i>
						<i class="sk" style="width:46%;height:20px;margin-top:9px"></i>
						<i class="sk w70" style="margin-top:8px"></i></div>`
				).join("")}</div>
				<div class="pm-grid">
					<div class="dpx-card sk-plain" style="padding:14px">
						<i class="sk w30"></i><i class="sk" style="height:120px;margin-top:12px"></i></div>
					<div class="dpx-card sk-plain" style="padding:14px">
						${[1, 2, 3, 4].map(() => '<i class="sk w90" style="margin-bottom:9px"></i>').join("")}</div>
				</div>
			</div>`
		);
	}

	render() {
		const d = this.data;
		$(this.wrapper)
			.find(".pm-window")
			.text(`${d.period.from} to ${d.period.to}`);

		$(this.wrapper).find(".pm-foot").html(
			`Measured from work that belongs to a project` +
				(d.period.excluded
					? `<span class="sep">·</span><b>${d.period.excluded.toLocaleString()}</b> tasks sit outside every project and are not counted`
					: "") +
				`<span class="sp">${d.wins.length} shipped in this window</span>`
		);

		$(this.wrapper).find(".bb-stage").html(`
			<div class="pm-kpis">${d.kpis.map((k) => pm_kpi(k)).join("")}</div>
			<div class="pm-grid wide">
				${pm_flow(d.flow)}
				${pm_risks(d.risks)}
			</div>
			<div class="pm-grid">
				${pm_people(d.people)}
				${pm_wins(d.wins)}
			</div>
			${pm_modules(d.modules)}
		`);
	}
};

function pm_kpi(k) {
	const value = k.value === null || k.value === undefined ? "—" : k.value;
	const shown = k.signed && typeof value === "number" && value > 0 ? `+${value}` : value;
	const arrow = k.delta > 0 ? "▲" : k.delta < 0 ? "▼" : "";
	return `
		<div class="pm-kpi ${k.direction}" title="${pm_esc(k.note)}">
			<div class="lbl">${pm_esc(k.label)}</div>
			<div class="val">${pm_esc(shown)}<span class="unit">${pm_esc(k.unit)}</span></div>
			<div class="foot">
				${
					k.delta === null || k.delta === undefined || k.delta === 0
						? `<span class="flat">${k.was === null || k.was === undefined ? "right now" : "no change"}</span>`
						: `<span class="delta">${arrow} ${pm_esc(Math.abs(k.delta))}${pm_esc(k.unit)}</span>
							<span class="vs">vs previous ${pm_esc(k.was)}${pm_esc(k.unit)}</span>`
				}
			</div>
		</div>`;
}

function pm_flow(weeks) {
	const top = Math.max(1, ...weeks.map((w) => Math.max(w.raised, w.delivered)));
	return `
		<div class="dpx-card">
			<div class="dpx-card-hd"><div class="ttl">Raised against delivered</div>
				<span class="pm-key"><i class="in"></i>raised<i class="out"></i>delivered</span></div>
			<div class="dpx-card-body">
				<div class="pm-flow">
					${weeks
						.map(
							(w) => `<div class="col" title="Week of ${pm_esc(w.label)}: ${w.raised} raised, ${
								w.delivered
							} delivered">
								<div class="pair">
									<i class="in" style="height:${Math.round((w.raised / top) * 100)}%"></i>
									<i class="out" style="height:${Math.round((w.delivered / top) * 100)}%"></i>
								</div>
								<span class="lbl">${pm_esc(w.label)}</span>
							</div>`
						)
						.join("")}
				</div>
			</div>
		</div>`;
}

function pm_risks(risks) {
	return `
		<div class="dpx-card">
			<div class="dpx-card-hd"><div class="ttl">Needs attention</div>
				<span class="md-n">${risks.length}</span></div>
			<div class="dpx-card-body" style="padding:4px 0 6px">
				${
					risks.length
						? risks
								.map(
									(r) => `<a class="pm-risk" href="/app/${r.doctype.toLowerCase()}/${encodeURIComponent(
										r.name
									)}">
										<span class="dpx-bb-chip ${
											{ "On hold": "st-in-review", "Awaiting you": "st-triage" }[r.kind] ||
											"st-blocked"
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
			<div class="dpx-card-hd"><div class="ttl">Shipped</div><span class="md-n">${wins.length}</span></div>
			<div class="dpx-card-body" style="padding:4px 0 6px">
				${
					wins.length
						? wins
								.slice(0, 8)
								.map(
									(w) => `<a class="pm-win" href="/app/task/${encodeURIComponent(w.name)}">
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
						? `<a class="pm-more" href="/backlog-board">and ${wins.length - 8} more</a>`
						: ""
				}
			</div>
		</div>`;
}

function pm_modules(modules) {
	if (!modules.length) return "";
	const top = Math.max(1, ...modules.map((m) => m.open + m.delivered));
	return `
		<div class="dpx-card">
			<div class="dpx-card-hd"><div class="ttl">Where the work is</div></div>
			<div class="dpx-card-body">
				<div class="pm-mods">
					${modules
						.map(
							(m) => `<div class="mod">
								<span class="nm">${pm_esc(m.module)}</span>
								<span class="bar">
									<i class="out" style="width:${Math.round((m.delivered / top) * 100)}%"
										title="${m.delivered} delivered"></i>
									<i class="in" style="width:${Math.round((m.open / top) * 100)}%"
										title="${m.open} open"></i>
								</span>
								<span class="n">${m.delivered} / ${m.open + m.delivered}</span>
							</div>`
						)
						.join("")}
				</div>
			</div>
		</div>`;
}

function pm_initials(name) {
	return String(name || "?").split(/\s+/).slice(0, 2).map((p) => p[0] || "").join("").toUpperCase();
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
	refresh: '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
};

function pm_ico(name, size) {
	const s = size || 15;
	return `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="currentColor"
		stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${PM_ICONS[name] || ""}</svg>`;
}

function pm_esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}
