window.upande_dev_tools = window.upande_dev_tools || {};

const MB_STATUSES = ["Open", "Working", "Pending Review", "Overdue", "Template", "Completed", "Cancelled"];
const MB_KANBAN_STATUSES = ["Overdue", "Open", "Working", "Pending Review"];
const MB_DAY_MS = 86400000;
const MB_PREFS = "dpx-my-backlog";
const MB_TABS = [
	["today", "Today"],
	["tasks", "Tasks"],
	["requests", "Requests"],
	["progress", "Progress"],
];

// Same tones/labels as the Requests portal (RP_STAGE) - a request looks the same
// wherever a developer runs into it.
const MB_STAGE = {
	"": ["st-triage", "Waiting for a decision"],
	"Under Review": ["st-triage", "Waiting for a decision"],
	Approved: ["st-in-progress", "Accepted"],
	Scheduled: ["st-in-progress", "Scheduled"],
	"In Progress": ["st-in-progress", "Being built"],
	Completed: ["st-done", "Done"],
	Rejected: ["st-blocked", "Not going ahead"],
	Deferred: ["st-in-review", "Parked for now"],
	Withdrawn: ["st-blocked", "Withdrawn"],
	Closed: ["st-done", "Closed"],
};
const MB_REQUEST_OPEN_STATES = ["", "Under Review", "Approved", "Scheduled", "In Progress", "Deferred"];

function mb_read_prefs() {
	try {
		return JSON.parse(localStorage.getItem(MB_PREFS) || "{}") || {};
	} catch (e) {
		return {};
	}
}
function mb_write_prefs(patch) {
	try {
		localStorage.setItem(MB_PREFS, JSON.stringify({ ...mb_read_prefs(), ...patch }));
	} catch (e) {
		/* private mode etc - preferences just won't stick */
	}
}

upande_dev_tools.MyBacklog = class MyBacklog {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.tasks = [];
		this.meetings = [];
		this.requests = [];
		this.progress = { completed_this_week: 0, completed_prev_week: 0 };
		this.module = "";
		this.project = "";
		this.overdue_only = false;
		this.undated_only = false;
		this.view = mb_read_prefs().view === "kanban" ? "kanban" : "list";
		const kept_tab = mb_read_prefs().tab;
		this.tab = MB_TABS.some(([key]) => key === kept_tab) ? kept_tab : "today";
		this.render_shell();
		this.load();
	}

	load() {
		const icon = $(this.wrapper).find(".mb-reload").addClass("spin");
		if (!this.tasks.length) this.skeleton();
		frappe
			.xcall("upande_dev_tools.api.requests.get_my_backlog")
			.then((data) => {
				this.tasks = (data && data.tasks) || [];
				this.meetings = (data && data.meetings) || [];
				this.requests = (data && data.requests) || [];
				this.progress = (data && data.progress) || { completed_this_week: 0, completed_prev_week: 0 };
				this.stage().removeAttr("aria-busy");
				this.render();
				icon.removeClass("spin");
			})
			.catch((e) => {
				icon.removeClass("spin");
				this.stage().html(
					mb_blank(
						"Could not load your backlog",
						String((e && e.message) || e) || "Reload to try again."
					)
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
								<span class="dpx-bb-mark">${mb_ico("list", 14)}</span>
								<h2>My Backlog</h2>
							</div>
							<div class="dpx-bb-tb-sub">What's due, what's yours, and how it's going</div>
						</div>
						<div class="dpx-bb-tb-act">
							<button class="dpx-bb-ico mb-reload" type="button" title="Refresh">${mb_ico("refresh")}</button>
						</div>
					</div>
					<div class="pm-tabs" role="tablist">
						${MB_TABS.map(([key, label]) => `<button data-tab="${key}" role="tab">${mb_esc(label)}</button>`).join("")}
					</div>
				</div>
				<div class="md-alerts"></div>
				<div class="bb-stage"></div>
			</div>
		`);

		const root = $(this.wrapper);
		root.find(`.pm-tabs button[data-tab="${this.tab}"]`).addClass("on");
		root.on("click", ".pm-tabs button", (e) => {
			this.tab = $(e.currentTarget).data("tab");
			root.find(".pm-tabs button").removeClass("on");
			$(e.currentTarget).addClass("on");
			mb_write_prefs({ tab: this.tab });
			this.render();
		});
		root.on("click", ".mb-reload", () => this.load());
		root.on("click", ".mb-status", (e) => e.stopPropagation());
		root.on("change", ".mb-status", (e) => this.set_status($(e.currentTarget)));
		root.on("change", ".mb-module", (e) => {
			this.module = $(e.currentTarget).val();
			this.render();
		});
		root.on("change", ".mb-project", (e) => {
			this.project = $(e.currentTarget).val();
			this.render();
		});
		root.on("click", ".mb-quick button", (e) => {
			const btn = $(e.currentTarget);
			const key = btn.data("filter") === "overdue" ? "overdue_only" : "undated_only";
			this[key] = !this[key];
			btn.toggleClass("on", this[key]);
			this.render();
		});
		root.on("click", ".mb-view button", (e) => {
			this.view = $(e.currentTarget).data("view");
			mb_write_prefs({ view: this.view });
			this.render();
		});
		if (upande_dev_tools.attach_preview) upande_dev_tools.attach_preview(root[0]);
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
				`<div class="dpx-skel" aria-hidden="true"><div class="dpx-card sk-plain">${[
					1, 2, 3, 4, 5,
				]
					.map(
						() => `<div class="sk-line"><i class="sk" style="width:52%"></i>
							<i class="sk w10"></i><i class="sk chip sm right"></i></div>`
					)
					.join("")}</div></div>`
			);
	}

	/** Distinct modules/projects across the WHOLE backlog (not the filtered subset), so a
	 *  filter option never disappears out from under someone just because they picked
	 *  another filter first. A no-op if the Tasks tab isn't the one on screen. */
	fill_filter_options() {
		const root = $(this.wrapper);
		const moduleSel = root.find(".mb-module");
		if (!moduleSel.length) return;
		const modules = Array.from(new Set(this.tasks.map((t) => t.custom_module).filter(Boolean))).sort();
		const projects = Array.from(new Set(this.tasks.map((t) => t.project).filter(Boolean))).sort();
		const projectSel = root.find(".mb-project");
		moduleSel.find("option:not(:first)").remove();
		modules.forEach((m) => moduleSel.append(`<option value="${mb_esc(m)}">${mb_esc(m)}</option>`));
		moduleSel.val(this.module);
		projectSel.find("option:not(:first)").remove();
		projects.forEach((p) => projectSel.append(`<option value="${mb_esc(p)}">${mb_esc(p)}</option>`));
		projectSel.val(this.project);
		root.find('.mb-quick button[data-filter="overdue"]').toggleClass("on", this.overdue_only);
		root.find('.mb-quick button[data-filter="undated"]').toggleClass("on", this.undated_only);
		root.find(`.mb-view button[data-view="${this.view}"]`).addClass("on");
		root.find(`.mb-view button:not([data-view="${this.view}"])`).removeClass("on");
	}

	render() {
		const today = frappe.datetime.get_today();
		const tomorrow = frappe.datetime.add_days(today, 1);

		const is_overdue = (t) =>
			t.status === "Overdue" ||
			(t.exp_end_date && t.exp_end_date < today && t.status !== "Completed" && t.status !== "Cancelled");
		const is_open = (t) => t.status !== "Completed" && t.status !== "Cancelled";

		const overdue_all = this.tasks.filter(is_overdue);
		const open_all = this.tasks.filter(is_open);
		const due_today = open_all.filter((t) => t.exp_end_date === today && !is_overdue(t));
		const due_tomorrow = open_all.filter((t) => t.exp_end_date === tomorrow);
		const requests_open = this.requests.filter((r) => MB_REQUEST_OPEN_STATES.includes(r.workflow_state || ""));

		$(this.wrapper)
			.find(".md-alerts")
			.html(
				overdue_all.length
					? `<a class="pm-alert bad" href="/backlog-board"><span class="dot"></span>
					<span class="txt">${overdue_all.length} of your task${
							overdue_all.length === 1 ? " is" : "s are"
					  } past due</span><span class="cta">See them</span></a>`
					: ""
			);

		const ctx = { today, tomorrow, is_overdue, is_open, overdue_all, open_all, due_today, due_tomorrow, requests_open };
		const panels = {
			today: () => this.render_today(ctx),
			tasks: () => this.render_tasks(ctx),
			requests: () => mb_requests_tab(this.requests),
			progress: () => mb_progress_tab(this.tasks, this.progress, ctx.is_overdue),
		};
		this.stage().html((panels[this.tab] || panels.today)());

		if (this.tab === "tasks") {
			this.fill_filter_options();
			if (this.view === "kanban") this.bind_kanban_drag();
		}
	}

	render_today(ctx) {
		return [
			mb_week_ahead(this.tasks, ctx.today),
			mb_due_hero(ctx.due_today, ctx.due_tomorrow, ctx.overdue_all, ctx.today),
			mb_measures(ctx.open_all, ctx.overdue_all, ctx.requests_open, this.progress),
			this.meetings.length
				? `<div class="dpx-card">
					<div class="dpx-card-hd"><div class="ttl">Schedule</div></div>
					<div class="dpx-card-body" style="padding:4px 0 6px">
						${this.meetings.map((m) => mb_meeting(m)).join("")}
					</div>
				</div>`
				: "",
		].join("");
	}

	render_tasks(ctx) {
		let visible = this.tasks;
		if (this.module) visible = visible.filter((t) => t.custom_module === this.module);
		if (this.project) visible = visible.filter((t) => t.project === this.project);
		if (this.overdue_only) visible = visible.filter(ctx.is_overdue);
		if (this.undated_only) visible = visible.filter((t) => !t.exp_end_date);

		const toolbar = `
			<div class="dpx-bb-tb mb-tasks-tb">
				<div class="dpx-bb-tb-cmd" style="border-top:0;padding:0 0 12px">
					<div class="dpx-bb-grp">
						<span class="dpx-bb-grp-lbl">Module</span>
						<select class="dpx-bb-field mb-module" aria-label="Filter by module">
							<option value="">All modules</option>
						</select>
					</div>
					<div class="dpx-bb-grp">
						<span class="dpx-bb-grp-lbl">Project</span>
						<select class="dpx-bb-field mb-project" aria-label="Filter by project">
							<option value="">All projects</option>
						</select>
					</div>
					<span class="dpx-bb-sep"></span>
					<div class="dpx-bb-grp">
						<div class="dpx-bb-views mb-quick">
							<button data-filter="overdue">Overdue only</button>
							<button data-filter="undated">No due date</button>
						</div>
					</div>
					<span class="dpx-bb-sep"></span>
					<div class="dpx-bb-grp">
						<div class="dpx-bb-views mb-view" role="tablist">
							<button data-view="list" role="tab">${mb_ico("list", 12)}<span>List</span></button>
							<button data-view="kanban" role="tab">${mb_ico("grid", 12)}<span>Kanban</span></button>
						</div>
					</div>
					<span class="mb-count dpx-bb-hint">
						<b>${ctx.open_all.length}</b> open<span class="sep">·</span>
						<b>${ctx.overdue_all.length}</b> overdue
					</span>
				</div>
			</div>`;

		if (!this.tasks.length) {
			return toolbar + mb_blank("Nothing on your backlog", "Pick up work from the backlog board when you're ready.");
		}
		if (!visible.length) {
			return toolbar + mb_blank("No matches", "Nothing on your backlog fits that filter.");
		}
		if (this.view === "kanban") {
			return toolbar + this.render_kanban(visible, ctx.today, ctx.is_overdue);
		}
		const overdue = visible.filter(ctx.is_overdue);
		const rest = visible.filter((t) => !ctx.is_overdue(t));
		const working = rest.filter((t) => t.status === "Working");
		const review = rest.filter((t) => t.status === "Pending Review");
		const open = rest.filter((t) => t.status !== "Working" && t.status !== "Pending Review");
		return (
			toolbar +
			[
				mb_section("Overdue", overdue, ctx.today, "bad"),
				mb_section("Working", working, ctx.today),
				mb_section("Pending Review", review, ctx.today),
				mb_section("Open", open, ctx.today),
			].join("")
		);
	}

	render_kanban(visible, today, is_overdue) {
		const rest = visible.filter((t) => !is_overdue(t));
		const cols = MB_KANBAN_STATUSES.map((status) => [
			status,
			status === "Overdue" ? visible.filter(is_overdue) : rest.filter((t) => t.status === status),
		]);
		return `<div class="dpx-bb-cols">${cols
			.map(
				([status, items]) => `
			<div class="dpx-bb-col">
				<div class="dpx-bb-col-hd"><span>${mb_esc(status)}</span><span class="n">${items.length}</span></div>
				<div class="dpx-bb-drop" data-status="${mb_esc(status)}">
					${
						items.length
							? items.map((t) => mb_kanban_card(t, today)).join("")
							: '<div class="dpx-bb-col-blank">Nothing here</div>'
					}
				</div>
			</div>`
			)
			.join("")}</div>`;
	}

	bind_kanban_drag() {
		const stage = this.stage();
		stage.find(".dpx-bb-card[draggable=true]").on("dragstart", (e) => {
			const card = $(e.currentTarget);
			e.originalEvent.dataTransfer.setData("text/plain", card.data("name"));
			card.addClass("dragging");
		});
		stage.find(".dpx-bb-card").on("dragend", (e) => $(e.currentTarget).removeClass("dragging"));
		stage.find(".dpx-bb-drop").on("dragover", (e) => {
			e.preventDefault();
			$(e.currentTarget).addClass("over");
		});
		stage.find(".dpx-bb-drop").on("dragleave", (e) => $(e.currentTarget).removeClass("over"));
		stage.find(".dpx-bb-drop").on("drop", (e) => {
			e.preventDefault();
			const drop = $(e.currentTarget);
			drop.removeClass("over");
			const name = e.originalEvent.dataTransfer.getData("text/plain");
			const status = drop.data("status");
			this.move_task(name, status);
		});
	}

	move_task(name, status) {
		const task = this.tasks.find((t) => t.name === name);
		if (!task || task.status === status) return;
		const before = task.status;
		task.status = status;
		this.render();
		frappe
			.xcall("upande_dev_tools.api.requests.update_task_status", { name, status })
			.then(() => upande_dev_tools.toast(__("{0} is now {1}", [task.subject, status]), "green"))
			.catch(() => {
				task.status = before;
				this.render();
				upande_dev_tools.toast(__("Could not update that status."), "red");
			});
	}

	set_status(select) {
		const row = select.closest("[data-name]");
		const name = row.data("name");
		const task = this.tasks.find((t) => t.name === name);
		if (!task) return;

		const status = select.val();
		const before = task.status;
		task.status = status;
		select.prop("disabled", true);

		frappe
			.xcall("upande_dev_tools.api.requests.update_task_status", { name, status })
			.then(() => {
				upande_dev_tools.toast(__("{0} is now {1}", [task.subject, status]), "green");
				this.render();
			})
			.catch(() => {
				task.status = before;
				select.val(before).prop("disabled", false);
				upande_dev_tools.toast(__("Could not update that status."), "red");
			});
	}
};

// The shape of the week ahead, not just today/tomorrow counted out - a short bar
// per day answers "when does it get busy" at a glance, which two numbers cannot.
function mb_week_ahead(tasks, today) {
	const days = Array.from({ length: 7 }, (_, i) => frappe.datetime.add_days(today, i));
	const counts = days.map(
		(d) => tasks.filter((t) => t.exp_end_date === d && t.status !== "Completed" && t.status !== "Cancelled").length
	);
	const max = Math.max(1, ...counts);
	const dow = (d) => {
		const parsed = new Date(`${d}T00:00:00`);
		return isNaN(parsed) ? "" : parsed.toLocaleDateString(undefined, { weekday: "short" });
	};
	return `<div class="dpx-card">
		<div class="dpx-card-hd"><div class="ttl">The week ahead</div></div>
		<div class="dpx-card-body">
			<div class="mb-week">
				${days
					.map(
						(d, i) => `<div class="col${i === 0 ? " today" : ""}">
							<div class="track"><div class="fill" style="height:${(counts[i] / max) * 100}%"></div></div>
							<div class="n">${counts[i] || ""}</div>
							<div class="lbl">${i === 0 ? "Today" : mb_esc(dow(d))}</div>
						</div>`
					)
					.join("")}
			</div>
		</div>
	</div>`;
}

// What's due today/tomorrow, spelled out - not just counted. This is the section meant
// to answer "what's expected of me" without a developer having to scan the whole list.
function mb_due_hero(due_today, due_tomorrow, overdue_all, today) {
	const col = (title, tasks, tone) => `
		<div class="mb-due-col">
			<div class="mb-due-hd">${mb_esc(title)}<span class="dpx-bb-hint">${tasks.length}</span></div>
			${
				tasks.length
					? tasks.map((t) => mb_task(t, today)).join("")
					: `<div class="dpx-bb-col-blank">${tone === "bad" ? "Nothing overdue." : "Nothing here. Clear."}</div>`
			}
		</div>`;
	return `<div class="dpx-card mb-due">
		<div class="dpx-card-hd"><div class="ttl">What's expected of you</div></div>
		<div class="dpx-card-body mb-due-grid" style="padding:4px 22px 16px">
			${col("Overdue", overdue_all, "bad")}
			${col("Due today", due_today)}
			${col("Due tomorrow", due_tomorrow)}
		</div>
	</div>`;
}

function mb_measures(open_all, overdue_all, requests_open, progress) {
	const diff = progress.completed_this_week - progress.completed_prev_week;
	const trend =
		progress.completed_prev_week === 0 && progress.completed_this_week === 0
			? ["", "No completions yet this week or last"]
			: diff > 0
			? ["good", `+${diff} vs last week`]
			: diff < 0
			? ["bad", `${diff} vs last week`]
			: ["", "Same as last week"];
	return `<div class="dpx-card pm-measures mb-measures4">
		<div class="m"><span class="lbl">Open</span><span class="val">${open_all.length}</span>
			<span class="chg">across your backlog</span></div>
		<div class="m"><span class="lbl">Overdue</span><span class="val">${overdue_all.length}</span>
			<span class="chg ${overdue_all.length ? "bad" : "good"}">${
		overdue_all.length ? "needs attention" : "none - nice"
	}</span></div>
		<div class="m"><span class="lbl">Completed this week</span><span class="val">${
			progress.completed_this_week
		}</span><span class="chg ${trend[0]}">${mb_esc(trend[1])}</span></div>
		<div class="m"><span class="lbl">Requests in flight</span><span class="val">${requests_open.length}</span>
			<span class="chg">raised by you, awaiting a decision</span></div>
	</div>`;
}

function mb_requests_tab(requests) {
	if (!requests.length) return mb_blank("No requests yet", "Anything you raise, approved or not, shows up here.");
	return `<div class="dpx-card">
		<div class="dpx-card-hd"><div class="ttl">Your requests</div>
			<span class="dpx-bb-hint">${requests.length}</span></div>
		<div class="dpx-card-body" style="padding:4px 0 6px">
			${requests.map((r) => mb_request(r)).join("")}
		</div>
	</div>`;
}

function mb_progress_tab(tasks, progress, is_overdue) {
	if (!tasks.length) return mb_blank("Nothing to show yet", "Charts fill in once you have work on your backlog.");
	const open_or_working = tasks.filter((t) => t.status !== "Completed" && t.status !== "Cancelled");

	const by_module = {};
	open_or_working.forEach((t) => {
		const key = t.custom_module || "No module";
		by_module[key] = (by_module[key] || 0) + 1;
	});
	const module_total = open_or_working.length || 1;
	const module_rows = Object.entries(by_module)
		.sort((a, b) => b[1] - a[1])
		.slice(0, 5);

	return `
		<div class="pm-grid">
			<div class="dpx-card">
				<div class="dpx-card-hd"><div class="ttl">Status mix</div></div>
				<div class="dpx-card-body">
					${mb_donut(
						[
							{ label: "Open", value: open_or_working.filter((t) => t.status === "Open" && !is_overdue(t)).length, color: "#c9c7bd" },
							{ label: "Working", value: open_or_working.filter((t) => t.status === "Working").length, color: "var(--bb-solid-green)" },
							{ label: "Pending Review", value: open_or_working.filter((t) => t.status === "Pending Review").length, color: "var(--bb-solid-amber)" },
							{ label: "Overdue", value: open_or_working.filter(is_overdue).length, color: "var(--bb-solid-red)" },
						],
						{ center: open_or_working.length, centerSub: "open" }
					)}
				</div>
			</div>
			<div class="dpx-card">
				<div class="dpx-card-hd"><div class="ttl">Top modules</div></div>
				<div class="dpx-card-body">
					<div class="pm-req">${
						module_rows.length
							? module_rows
									.map(
										([l, n]) => `<div class="r">
											<span class="n">${n}</span><span class="l">${mb_esc(l)}</span>
											<span class="bar"><i style="width:${Math.round((n / module_total) * 100)}%"></i></span>
										</div>`
									)
									.join("")
							: `<p class="pm-note">No modules tagged yet.</p>`
					}</div>
				</div>
			</div>
		</div>
		<div class="dpx-card">
			<div class="dpx-card-hd"><div class="ttl">Completed, this week vs last</div></div>
			<div class="dpx-card-body">
				${mb_trend(progress)}
			</div>
		</div>
		<div class="dpx-card">
			<div class="dpx-card-hd"><div class="ttl">How old your open work is</div></div>
			<div class="dpx-card-body">
				${mb_age_bands(open_or_working)}
			</div>
		</div>`;
}

function mb_trend(progress) {
	const max = Math.max(1, progress.completed_this_week, progress.completed_prev_week);
	const row = (label, n, cls) => `<div class="mb-trend-row">
		<span class="l">${mb_esc(label)}</span>
		<span class="track"><span class="fill ${cls}" style="width:${(n / max) * 100}%"></span></span>
		<span class="n">${n}</span>
	</div>`;
	return `<div class="mb-trend">
		${row("This week", progress.completed_this_week, "now")}
		${row("Last week", progress.completed_prev_week, "prev")}
	</div>`;
}

const MB_AGE_BANDS = [
	["Under a week", 7],
	["1-2 weeks", 14],
	["2-4 weeks", 30],
	["Over a month", null],
];

function mb_age_bands(tasks) {
	const bands = MB_AGE_BANDS.map(([label]) => ({ label, count: 0 }));
	tasks.forEach((t) => {
		const age = Math.floor((Date.now() - new Date(String(t.creation).replace(" ", "T"))) / MB_DAY_MS);
		const index = MB_AGE_BANDS.findIndex(([, max]) => max == null || age < max);
		bands[index === -1 ? bands.length - 1 : index].count++;
	});
	const total = tasks.length || 1;
	return `
		<div class="pm-age-bar">
			${bands.map((b, i) => `<i class="b${i}" style="width:${(b.count / total) * 100}%" title="${mb_esc(b.label)}: ${b.count}"></i>`).join("")}
		</div>
		<div class="pm-age-key">
			${bands.map((b, i) => `<span><i class="b${i}"></i>${mb_esc(b.label)}<b>${b.count}</b></span>`).join("")}
		</div>`;
}

// Same hand-rolled SVG donut convention as the PM dashboard (pm_donut) - kept as its
// own small copy here rather than shared, matching how every other per-page helper
// (mb_esc, mb_ico, ...) is already self-contained rather than imported.
function mb_donut(segments, opts) {
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
						? `<text x="${cx}" y="${cy - 3}" class="num" text-anchor="middle">${mb_esc(opts.center)}</text>
							<text x="${cx}" y="${cy + 11}" class="sub" text-anchor="middle">${mb_esc(opts.centerSub || "")}</text>`
						: ""
				}
			</svg>
			<div class="pm-donut-legend">
				${segments
					.map(
						(s) => `<div class="row">
							<i style="background:${s.color}"></i>
							<span class="l">${mb_esc(s.label)}</span>
							<span class="n">${s.value}</span>
						</div>`
					)
					.join("")}
			</div>
		</div>`;
}

function mb_request(r) {
	const [tone, label] = MB_STAGE[r.workflow_state || ""] || ["st-triage", r.workflow_state];
	return `
		<div class="md-task" data-id="Request:${mb_esc(r.name)}">
			<span class="dpx-bb-chip ${tone}">${mb_esc(label)}</span>
			<a class="t" href="/requests">${mb_esc(r.title)}</a>
			<span class="dpx-bb-chip">${mb_esc(r.request_type)}</span>
			${r.project ? `<span class="dpx-bb-chip">${mb_esc(r.project)}</span>` : ""}
			${
				r.priority && r.priority !== "Low"
					? `<span class="dpx-bb-chip pr-${r.priority.toLowerCase()}">${mb_esc(r.priority)}</span>`
					: ""
			}
		</div>`;
}

function mb_section(title, tasks, today, tone) {
	if (!tasks.length) return "";
	return `<div class="dpx-card">
		<div class="dpx-card-hd"><div class="ttl"${tone ? ` style="color:var(--bb-solid-red)"` : ""}>${mb_esc(
		title
	)}</div><span class="dpx-bb-hint">${tasks.length}</span></div>
		<div class="dpx-card-body" style="padding:4px 0 6px">
			${tasks.map((t) => mb_task(t, today)).join("")}
		</div>
	</div>`;
}

function mb_task(t, today) {
	const overdue = t.exp_end_date && t.exp_end_date < today && t.status !== "Completed";
	return `
		<div class="md-task" data-name="${mb_esc(t.name)}" data-id="Task:${mb_esc(t.name)}">
			<select class="dpx-bb-field mb-status" style="width:132px">
				${MB_STATUSES.map(
					(s) =>
						`<option value="${mb_esc(s)}"${s === t.status ? " selected" : ""}>${mb_esc(
							s
						)}</option>`
				).join("")}
			</select>
			<a class="t" href="/app/task/${encodeURIComponent(t.name)}">${mb_esc(t.subject)}</a>
			${t.custom_module ? `<span class="dpx-bb-chip">${mb_esc(t.custom_module)}</span>` : ""}
			${t.project ? `<span class="dpx-bb-chip">${mb_esc(t.project)}</span>` : ""}
			${
				t.exp_end_date
					? `<span class="dpx-bb-chip${overdue ? " st-blocked" : ""}">${mb_esc(t.exp_end_date)}</span>`
					: `<span class="dpx-bb-chip">No due date</span>`
			}
			${
				t.priority && t.priority !== "Low"
					? `<span class="dpx-bb-chip pr-${t.priority.toLowerCase()}">${mb_esc(
							t.priority
					  )}</span>`
					: ""
			}
		</div>`;
}

function mb_kanban_card(t, today) {
	const overdue = t.exp_end_date && t.exp_end_date < today && t.status !== "Completed";
	return `
		<a class="dpx-bb-card" draggable="true" data-name="${mb_esc(t.name)}" data-id="Task:${mb_esc(t.name)}"
			href="/app/task/${encodeURIComponent(t.name)}">
			<div class="hd">
				${t.custom_module ? `<span class="dpx-bb-chip tiny">${mb_esc(t.custom_module)}</span>` : ""}
				${
					t.priority && t.priority !== "Low"
						? `<span class="dpx-bb-chip tiny pr-${t.priority.toLowerCase()}">${mb_esc(t.priority)}</span>`
						: ""
				}
			</div>
			<div class="t">${mb_esc(t.subject)}</div>
			<div class="m">
				${t.project ? `<span>${mb_esc(t.project)}</span>` : ""}
				${t.exp_end_date ? `<span class="d${overdue ? " late" : ""}">${mb_esc(t.exp_end_date)}</span>` : ""}
			</div>
		</a>`;
}

function mb_meeting(m) {
	const at = new Date(String(m.starts_on).replace(" ", "T"));
	const hhmm = isNaN(at)
		? ""
		: at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
	return `
		<div class="md-meet">
			<span class="at">${mb_esc(hhmm)}</span>
			<span class="body"><span class="t">${mb_esc(m.subject)}</span></span>
			${
				m.google_meet_link
					? `<a class="md-join" href="${mb_esc(
							m.google_meet_link
					  )}" target="_blank" rel="noopener">Join</a>`
					: ""
			}
		</div>`;
}

function mb_blank(heading, body) {
	return `<div class="dpx-card"><div class="dpx-bb-blank">
		<h3>${mb_esc(heading)}</h3><p>${mb_esc(body)}</p></div></div>`;
}

const MB_ICONS = {
	list: '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
	refresh:
		'<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
	grid: '<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>',
};

function mb_ico(name, size) {
	const s = size || 15;
	return `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="currentColor"
		stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${
			MB_ICONS[name] || ""
		}</svg>`;
}

function mb_esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}
