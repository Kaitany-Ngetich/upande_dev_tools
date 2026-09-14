window.upande_dev_tools = window.upande_dev_tools || {};

const MD_STAGES = ["Open", "Working", "Pending Review", "Completed"];

upande_dev_tools.MyDay = class MyDay {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.day = null;
		this.backlog = [];
		this.render_shell();
		this.load();
	}

	load() {
		const icon = $(this.wrapper).find(".md-reload").addClass("spin");
		if (!this.day) this.skeleton();
		Promise.all([
			frappe.xcall("upande_dev_tools.api.requests.get_my_day"),
			frappe.xcall("upande_dev_tools.api.requests.get_developer_backlog"),
		])
			.then(([day, backlog]) => {
				this.day = day || { tasks: [], meetings: [] };
				this.backlog = backlog || [];
				this.stage().removeAttr("aria-busy");
				this.render();
				icon.removeClass("spin");
			})
			.catch((e) => {
				icon.removeClass("spin");
				this.stage().html(
					md_blank("Could not load your day", String((e && e.message) || e) || "Reload to try again.")
				);
			});
	}

	stage() {
		return $(this.wrapper).find(".bb-stage");
	}

	render_shell() {
		const today = new Date();
		const long = today.toLocaleDateString(undefined, {
			weekday: "long",
			day: "numeric",
			month: "long",
		});

		$(this.wrapper).html(`
			<div class="dpx-board">
				<div class="dpx-bb-tb">
					<div class="dpx-bb-tb-hd">
						<div class="dpx-bb-tb-title">
							<div class="dpx-bb-tb-row">
								<span class="dpx-bb-mark">${md_ico("sun", 14)}</span>
								<h2>${md_esc(long)}</h2>
							</div>
							<div class="dpx-bb-tb-sub">What you planned for today, and what else is on you</div>
						</div>
						<div class="dpx-bb-tb-act">
							<button class="dpx-bb-ico md-reload" type="button" title="Refresh">${md_ico("refresh")}</button>
						</div>
					</div>
					<div class="dpx-bb-tb-cmd">
						<span class="md-count"></span>
						<span class="dpx-bb-hint"><span class="dpx-bb-kbd">r</span><span>refresh</span></span>
					</div>
				</div>
				<div class="md-alerts"></div>
				<div class="bb-stage"></div>
			</div>
		`);

		const root = $(this.wrapper);
		root.on("click", ".md-reload", () => this.load());
		root.on("click", ".md-check", (e) => this.advance($(e.currentTarget)));
		document.addEventListener("keydown", (e) => {
			if (e.key !== "r" || /^(INPUT|SELECT|TEXTAREA)$/.test((e.target || {}).tagName || "")) return;
			this.load();
		});
	}

	skeleton() {
		this.stage().attr("aria-busy", "true").html(
			`<div class="dpx-skel" aria-hidden="true"><div class="md-split">
				<div class="dpx-card sk-plain">${[1, 2, 3, 4]
					.map(
						() => `<div class="sk-line"><i class="sk dot" style="width:16px;height:16px"></i>
							<i class="sk" style="width:58%"></i><i class="sk chip sm right"></i></div>`
					)
					.join("")}</div>
				<div class="dpx-card sk-plain">${[1, 2]
					.map(
						() => `<div class="sk-line"><i class="sk w12"></i><i class="sk" style="width:54%"></i></div>`
					)
					.join("")}</div>
			</div></div>`
		);
	}

	render() {
		const today = this.day.tasks || [];
		const meetings = this.day.meetings || [];
		const due = (t) => String(t.exp_end_date || "").slice(0, 10);
		const overdue = this.backlog.filter((t) => due(t) && due(t) < this.day.date);
		const later = this.backlog.filter(
			(t) => !today.some((d) => d.name === t.name) && !overdue.includes(t)
		);
		const left = today.filter((t) => t.status !== "Completed").length;

		$(this.wrapper).find(".md-count").html(
			`<b>${left}</b> still to do today<span class="sep">·</span>` +
				`<b>${meetings.length}</b> meeting${meetings.length === 1 ? "" : "s"}<span class="sep">·</span>` +
				`<b>${this.backlog.length}</b> open in total`
		);

		$(this.wrapper).find(".md-alerts").html(
			overdue.length
				? `<a class="pm-alert bad" href="/backlog-board"><span class="dot"></span>
					<span class="txt">${overdue.length} of your task${
						overdue.length === 1 ? " is" : "s are"
					} past due</span><span class="cta">See them</span></a>`
				: ""
		);

		this.stage().html(`
			<div class="md-split">
				<div class="dpx-card">
					<div class="dpx-card-hd"><div class="ttl">Planned for today</div></div>
					<div class="dpx-card-body" style="padding:4px 0 6px">
						${
							today.length
								? today.map((t) => md_task(t)).join("")
								: `<div class="dpx-bb-blank"><p>Nothing is planned for today. Pick work from the
									<a href="/backlog-board">backlog</a> and set a planned date.</p></div>`
						}
					</div>
				</div>
				<div class="md-side">
					<div class="dpx-card">
						<div class="dpx-card-hd"><div class="ttl">Schedule</div></div>
						<div class="dpx-card-body" style="padding:4px 0 6px">
							${
								meetings.length
									? meetings.map((m) => md_meeting(m)).join("")
									: '<div class="dpx-bb-blank"><p>No meetings in the next day.</p></div>'
							}
						</div>
					</div>
					<div class="dpx-card">
						<div class="dpx-card-hd"><div class="ttl">Also on you</div>
							<span class="md-n">${later.length}</span></div>
						<div class="dpx-card-body" style="padding:4px 0 6px">
							${
								later.length
									? later.slice(0, 8).map((t) => md_small(t)).join("")
									: '<div class="dpx-bb-blank"><p>Nothing else is assigned to you.</p></div>'
							}
						</div>
					</div>
				</div>
			</div>
		`);
	}

	// The point of a day page is to close things on it, so a task moves a stage
	// from here rather than sending you to the board to do it.
	advance(btn) {
		const name = btn.closest("[data-name]").data("name");
		const task = (this.day.tasks || []).find((t) => t.name === name);
		if (!task) return;

		const next = MD_STAGES[Math.min(MD_STAGES.indexOf(task.status) + 1, MD_STAGES.length - 1)];
		if (next === task.status) return;

		const before = task.status;
		task.status = next;
		this.render();

		frappe
			.xcall("upande_dev_tools.api.board.set_stage", {
				doctype: "Task",
				name,
				stage: next === "Completed" ? "Done" : next === "Working" ? "In Progress" : "In Review",
			})
			.then(() =>
				frappe.show_alert({ message: __("{0} is now {1}", [task.subject, next]), indicator: "green" })
			)
			.catch(() => {
				task.status = before;
				this.render();
				frappe.show_alert({ message: __("Could not move that task."), indicator: "red" });
			});
	}
};

function md_task(t) {
	const done = t.status === "Completed";
	return `
		<div class="md-task${done ? " done" : ""}" data-name="${md_esc(t.name)}">
			<button class="md-check" type="button" title="${done ? "Done" : "Move to the next stage"}"
				aria-label="Advance ${md_esc(t.subject)}">${done ? md_ico("check", 11) : ""}</button>
			<a class="t" href="/app/task/${encodeURIComponent(t.name)}">${md_esc(t.subject)}</a>
			<span class="dpx-bb-chip st-${md_slug(t.status)}">${md_esc(t.status)}</span>
			${
				t.priority && t.priority !== "Low"
					? `<span class="dpx-bb-chip pr-${t.priority.toLowerCase()}">${md_esc(t.priority)}</span>`
					: ""
			}
		</div>`;
}

function md_meeting(m) {
	const at = new Date(String(m.starts_on).replace(" ", "T"));
	const to = new Date(String(m.ends_on || "").replace(" ", "T"));
	const hhmm = (d) =>
		isNaN(d) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
	const soon = !isNaN(at) && at - Date.now() < 15 * 60000 && to - Date.now() > 0;

	return `
		<div class="md-meet${soon ? " soon" : ""}">
			<span class="at">${md_esc(hhmm(at))}${to && !isNaN(to) ? `<em>${md_esc(hhmm(to))}</em>` : ""}</span>
			<span class="body">
				<span class="t">${md_esc(m.subject)}</span>
				${
					m.location && !m.google_meet_link
						? `<span class="where">${md_esc(m.location)}</span>`
						: ""
				}
			</span>
			${
				m.google_meet_link
					? `<a class="md-join" href="${md_esc(m.google_meet_link)}" target="_blank" rel="noopener">
						${MEET_MARK}<span>${soon ? "Join now" : "Join"}</span></a>`
					: ""
			}
		</div>`;
}

// Google Meet's own mark, so a meeting on the schedule is recognisable at a glance.
const MEET_MARK = `<svg viewBox="0 0 87 72" width="15" height="13" aria-hidden="true">
	<path fill="#00832d" d="M49.5 36l8.53 9.75 11.47 7.33 2-17.02-2-16.64-11.69 6.44z"/>
	<path fill="#0066da" d="M0 51.5V66c0 3.315 2.685 6 6 6h14.5l3-10.96-3-9.54-9.95-3z"/>
	<path fill="#e94235" d="M20.5 0L0 20.5l10.55 3 9.95-3 2.95-9.41z"/>
	<path fill="#2684fc" d="M20.5 20.5H0v31h20.5z"/>
	<path fill="#00ac47" d="M82.6 8.68L69.5 19.42v33.66l13.16 10.79c1.97 1.54 4.85.135 4.85-2.37V11c0-2.535-2.945-3.925-4.91-2.32zM49.5 36v15.5h-29V72h43c3.315 0 6-2.685 6-6V53.08z"/>
	<path fill="#ffba00" d="M63.5 0h-43v20.5h29V36l20-16.57V6c0-3.315-2.685-6-6-6z"/>
</svg>`;

function md_small(t) {
	return `
		<a class="md-small" href="/app/task/${encodeURIComponent(t.name)}">
			<span class="dpx-bb-dot st-${md_slug(t.status)}"></span>
			<span class="t">${md_esc(t.subject)}</span>
			${t.exp_end_date ? `<span class="d">${md_esc(String(t.exp_end_date).slice(0, 10))}</span>` : ""}
		</a>`;
}

function md_slug(status) {
	return (
		{ Open: "todo", Working: "in-progress", "Pending Review": "in-review", Completed: "done" }[status] ||
		"todo"
	);
}

function md_blank(heading, body) {
	return `<div class="dpx-card"><div class="dpx-bb-blank">
		<h3>${md_esc(heading)}</h3><p>${md_esc(body)}</p></div></div>`;
}

const MD_ICONS = {
	sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
	check: '<path d="M20 6 9 17l-5-5"/>',
	refresh: '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
};

function md_ico(name, size) {
	const s = size || 15;
	return `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="currentColor"
		stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${MD_ICONS[name] || ""}</svg>`;
}

function md_esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}
