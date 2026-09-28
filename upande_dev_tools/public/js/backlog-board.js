window.upande_dev_tools = window.upande_dev_tools || {};

const DAY = 86400000;
const SOURCES = { Task: "TASK", Issue: "ISSUE", Request: "REQ" };
const MONTHS = [
	"Jan",
	"Feb",
	"Mar",
	"Apr",
	"May",
	"Jun",
	"Jul",
	"Aug",
	"Sep",
	"Oct",
	"Nov",
	"Dec",
];
const SHORT = {
	"In Progress": "WIP",
	"In Review": "Review",
	Triage: "Triage",
	Todo: "Todo",
	Blocked: "Blocked",
	Done: "Done",
};
const DOW = ["S", "M", "T", "W", "T", "F", "S"];
const MONTHS_LONG = [
	"January",
	"February",
	"March",
	"April",
	"May",
	"June",
	"July",
	"August",
	"September",
	"October",
	"November",
	"December",
];
// A schedule with three widths is unreadable at both ends: a quarter of work at a
// day per 34px is a kilometre of scrolling, and a one-day task at a month is a
// sliver nobody can grab. Ctrl+wheel walks this ladder a rung at a time.
const ZOOMS = [
	{ key: "closeup", label: "Close-up", w: 110 },
	{ key: "days", label: "Days", w: 34 },
	{ key: "wide", label: "Wide weeks", w: 22 },
	{ key: "weeks", label: "Weeks", w: 15 },
	{ key: "fortnights", label: "Fortnights", w: 9 },
	{ key: "months", label: "Months", w: 5 },
	{ key: "quarters", label: "Quarters", w: 3 },
];
const ZOOM = {};
ZOOMS.forEach((z) => (ZOOM[z.key] = z.w));
// Coarse to fine, which is the direction a wheel pushed away from you should travel.
const ZOOM_KEYS = ZOOMS.map((z) => z.key).reverse();
// Below this a bar cannot be grabbed at all, and below EDGE_BAR there is no room
// for two edge handles and a middle - so the whole bar moves and the dialog or the
// sheet is where one end gets changed on its own.
const MIN_BAR = 14;
const EDGE_BAR = 30;
const EDGE = 7;
const WHEEL_STEP = 40;
const PAGE = 60;
const PREFS = "dpx-backlog";
const VIEWS = ["board", "list", "timeline", "sheet"];
const BLANK_FILTERS = { q: "", source: "", assignee: "", module: "", priority: "", tag: "" };

function read_prefs() {
	try {
		return JSON.parse(localStorage.getItem(PREFS) || "{}") || {};
	} catch (e) {
		return {};
	}
}
const COLUMN_CAP = 25;
const VIEW_KEYS = { 1: "board", 2: "list", 3: "timeline", 4: "sheet" };
const SHEET_FIELDS = {
	1: "title",
	2: "stage",
	3: "priority",
	4: "assignee",
	5: "module",
	6: "tags",
	7: "end",
	8: "start",
	9: "status",
	10: "project",
};
const LIB = "/assets/upande_dev_tools/lib/jspreadsheet";
// Each of these mirrors the real markup of its view, so the switch from
// skeleton to content does not move anything on the page.
const SKELETON = {
	board: () => {
		const card = (n) =>
			`<div class="sk-card">${`<i class="sk w40"></i><i class="sk w90"></i><i class="sk w70"></i>`}
				<div class="sk-row"><i class="sk dot"></i><i class="sk w30"></i><i class="sk w20 right"></i></div></div>`;
		return `<div class="dpx-skel" aria-hidden="true"><div class="dpx-bb-cols">${[
			3, 4, 2, 3, 1, 2,
		]
			.map(
				(n) => `<div class="dpx-bb-col">
					<div class="sk-colhd"><i class="sk w50"></i><i class="sk w10 right"></i></div>
					<div class="sk-drop">${Array.from({ length: n }, card).join("")}</div>
				</div>`
			)
			.join("")}</div></div>`;
	},

	list: () =>
		`<div class="dpx-skel" aria-hidden="true"><div class="dpx-card sk-plain">
			<div class="sk-head">${["w20", "w10", "w10", "w14", "w10", "w8"]
				.map((w) => `<i class="sk ${w}"></i>`)
				.join("")}</div>
			${[1, 2]
				.map(
					(g) =>
						`<div class="sk-group"><i class="sk w16"></i></div>` +
						[88, 74, 92, 66, 80]
							.map(
								(w) => `<div class="sk-line">
									<i class="sk dot"></i><i class="sk tag"></i><i class="sk" style="width:${w / 3}%"></i>
									<i class="sk chip"></i><i class="sk chip sm"></i><i class="sk w12 right"></i>
								</div>`
							)
							.join("")
				)
				.join("")}
		</div></div>`,

	timeline: () => {
		const bar = (left, width, tone) =>
			`<div class="sk-tlrow"><div class="sk-gutter"><i class="sk dot"></i><i class="sk w70"></i></div>
				<div class="sk-track"><i class="sk bar ${tone}" style="left:${left}%;width:${width}%"></i></div></div>`;
		const plan = [
			[8, 18, ""],
			[14, 26, "a"],
			[22, 14, ""],
			[18, 32, "b"],
			[34, 20, "a"],
			[30, 12, ""],
			[42, 24, "b"],
			[38, 16, ""],
			[50, 28, "a"],
			[46, 14, ""],
			[58, 22, "b"],
			[64, 18, ""],
		];
		return `<div class="dpx-skel" aria-hidden="true"><div class="dpx-bb-tl sk-plain">
			<div class="sk-tlhead"><div class="sk-gutter"><i class="sk w40"></i></div>
				<div class="sk-track">${[10, 30, 50, 70, 90]
					.map((l) => `<i class="sk w6" style="position:absolute;left:${l}%"></i>`)
					.join("")}</div></div>
			${plan.map(([l, w, t]) => bar(l, w, t)).join("")}
		</div></div>`;
	},

	sheet: () =>
		`<div class="dpx-skel" aria-hidden="true"><div class="dpx-bb-sheet sk-plain">
			<div class="sk-grid">${Array.from(
				{ length: 14 },
				(_, r) =>
					`<div class="sk-grow${r === 0 ? " head" : ""}">${[30, 11, 9, 13, 11, 9, 9, 10]
						.map((w) => `<i class="sk" style="width:${w}%"></i>`)
						.join("")}</div>`
			).join("")}</div>
		</div></div>`,
};

const HINTS = {
	board: "Drag a card between stages · hover one to edit it",
	list: "Click a group to collapse it · hover a row to edit it",
	timeline: "Drag a bar to move it · Ctrl + scroll to zoom",
	sheet: "Click a cell to edit it · funnel in a header to filter",
};
const ICONS = {
	board: '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>',
	list: '<path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M3 6h.01"/><path d="M3 12h.01"/><path d="M3 18h.01"/>',
	clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
	table: '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/><path d="M3 15h18"/><path d="M9 3v18"/><path d="M15 3v18"/>',
	trello: '<rect width="18" height="18" x="3" y="3" rx="2"/><rect width="3" height="9" x="7" y="7"/><rect width="3" height="5" x="14" y="7"/>',
	refresh:
		'<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
	assign: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 11h-6"/><path d="M19 8v6"/>',
	trash: '<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
	more: '<circle cx="12" cy="12" r="1"/><circle cx="12" cy="5" r="1"/><circle cx="12" cy="19" r="1"/>',
	x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
	edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
};

function load_jspreadsheet() {
	if (window.jspreadsheet) return Promise.resolve();
	const css = (href) =>
		new Promise((ok) => {
			if (document.querySelector(`link[href="${href}"]`)) return ok();
			const l = document.createElement("link");
			l.rel = "stylesheet";
			l.href = href;
			l.onload = l.onerror = ok;
			document.head.appendChild(l);
		});
	const js = (src) =>
		new Promise((ok, fail) => {
			if (document.querySelector(`script[src="${src}"]`)) return ok();
			const el = document.createElement("script");
			el.src = src;
			el.onload = ok;
			el.onerror = fail;
			document.head.appendChild(el);
		});
	return Promise.all([css(`${LIB}/jsuites.css`), css(`${LIB}/jspreadsheet.css`)])
		.then(() => js(`${LIB}/jsuites.js`))
		.then(() => js(`${LIB}/jspreadsheet.js`));
}

function paint_cell(cell, x, item) {
	if (!item) return;
	if (item.stage === "Done") cell.classList.add("bb-done");
	if (SHEET_FIELDS[x]) cell.classList.add(item.movable ? "bb-pick" : "bb-locked");

	if (x === 1) {
		cell.classList.add("bb-title");
		cell.setAttribute("data-id", `${item.doctype}:${item.name}`);
		cell.innerHTML = `<span class="cellwrap"><span class="dpx-bb-pri p${item.rank - 1}"
			title="${esc(item.priority || "No priority")}"></span><span class="dpx-bb-src">${
			SOURCES[item.doctype]
		}</span><span class="txt">${esc(item.title)}</span></span>`;
	} else if (x === 2) {
		cell.innerHTML = `<span class="cellwrap"><span class="dpx-bb-chip st-${slug(
			item.stage
		)}">${esc(item.stage)}</span></span>`;
	} else if (x === 3) {
		cell.innerHTML = item.priority
			? `<span class="cellwrap"><span class="dpx-bb-chip pr-${slug(item.priority)}">${esc(
					item.priority
			  )}</span></span>`
			: "";
	} else if (x === 4) {
		cell.innerHTML = item.assignees.length
			? `<span class="cellwrap"><span class="dpx-bb-av">${esc(
					initials(item.assignees[0])
			  )}</span><span class="txt">${esc(item.assignees[0])}${
					item.assignees.length > 1 ? ` +${item.assignees.length - 1}` : ""
			  }</span></span>`
			: '<span class="cellwrap" style="color:var(--ink-faint)">Unassigned</span>';
	} else if (x === 5) {
		cell.classList.add("bb-quiet");
	} else if (x === 6) {
		cell.innerHTML = (item.tags || []).length
			? `<span class="cellwrap">${(item.tags || [])
					.map((t) => `<span class="dpx-bb-chip">${esc(t)}</span>`)
					.join(" ")}</span>`
			: "";
	} else if (x === 7 || x === 8) {
		cell.classList.add("bb-mono");
		if (x === 7 && item.late) cell.classList.add("bb-late");
	} else if (x === 9 || x === 10) {
		cell.classList.add("bb-quiet");
	} else if (x === 11) {
		cell.classList.add("bb-mono");
	}
}

function ico(name, size) {
	const s = size || 15;
	return `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="currentColor"
		stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${
			ICONS[name] || ""
		}</svg>`;
}
const RANK = { Low: 1, Medium: 2, High: 3, Urgent: 4 };
const TASK_QUICK_STATUSES = [
	"Open",
	"Working",
	"Pending Review",
	"Overdue",
	"Completed",
	"Cancelled",
];

upande_dev_tools.BacklogBoard = class BacklogBoard {
	constructor(wrapper, project) {
		this.wrapper = wrapper;
		this.project = project;
		this.items = [];
		this.stages = [];
		this.total = 0;
		this.modules = [];
		// Where you left off, and how you had it set up. A board you have to re-filter
		// and re-arrange every morning is a board people stop arranging at all.
		const kept = read_prefs();
		this.view = VIEWS.includes(kept.view) ? kept.view : "board";
		this.group_by = kept.group_by || "stage";
		this.zoom = ZOOM[kept.zoom] ? kept.zoom : "weeks";
		this.shut = new Set(kept.shut || []);
		this.caps = {};
		this.hide_done = !!kept.hide_done;
		this.limit = PAGE;
		this.filters = { ...BLANK_FILTERS, ...(kept.filters || {}) };
		this.tl_scroll = kept.tl_scroll || null;
		this.render_shell();
		this.load();
	}

	load() {
		const args = this.project ? { project: this.project } : {};
		const icon = $(this.wrapper).find(".bb-reload").addClass("spin");
		if (!this.items.length) this.skeleton();
		frappe
			.xcall("upande_dev_tools.api.board.get_modules")
			.then((m) => {
				this.modules = ["", ...(Array.isArray(m) ? m : [])];
				if (this.items.length) this.render();
			})
			.catch(() => {});
		if (!this.people) {
			frappe
				.xcall("upande_dev_tools.api.requests.get_assignable_users")
				.then((people) => {
					this.people = Array.isArray(people) ? people : [];
					// Guarded: this .then has a .catch that blanks the list, so an undefined
					// helper here would silently cost the board every assignee it knows.
					if (upande_dev_tools.seed_users) upande_dev_tools.seed_users(this.people);
					// Same re-render the modules fetch does: the sheet's assignee dropdown is
					// built from this list, so arriving after the first paint would otherwise
					// leave that column with nothing to pick from until the next render.
					if (this.items.length) this.render();
				})
				.catch(() => {
					this.people = [];
				});
		}
		if (!this.projects) {
			frappe
				.xcall("upande_dev_tools.api.board.get_projects")
				.then((projects) => {
					this.projects = Array.isArray(projects) ? projects : [];
				})
				.catch(() => {
					this.projects = [];
				});
		}
		if (!this.work_tags) {
			// Work Tag is Master Data page-editable - the New Task picker needs the full valid
			// set, not just whatever tags happen to be in use on the board already.
			frappe
				.xcall("upande_dev_tools.api.board.get_work_tags")
				.then((tags) => {
					this.work_tags = Array.isArray(tags) ? tags : [];
				})
				.catch(() => {
					this.work_tags = [];
				});
		}
		if (!this.priority_levels) {
			// Priority Level is Master Data page-editable - the Sheet's edit dropdown needs
			// the full valid set, not just what's already in use on the board.
			frappe
				.xcall("upande_dev_tools.api.master_data.get_master_data", {
					key: "priority_level",
				})
				.then((levels) => {
					this.priority_levels = (Array.isArray(levels) ? levels : [])
						.filter((p) => !p.disabled)
						.map((p) => p.name);
				})
				.catch(() => {
					this.priority_levels = [];
				});
		}
		frappe
			.xcall("upande_dev_tools.api.board.get_board", args)
			.then((data) => {
				this.items = data.items;
				this.stages = data.stages;
				this.total = data.total;
				this.settled();
				this.render();
				icon.removeClass("spin");
			})
			.catch((e) => {
				icon.removeClass("spin");
				this.settled();
				this.fail(e);
			});
	}

	// A skeleton should be the shape of what is coming, not a stack of grey bars.
	// Each view draws its own, so the page does not rearrange itself on arrival.
	save_prefs() {
		try {
			localStorage.setItem(
				PREFS,
				JSON.stringify({
					view: this.view,
					group_by: this.group_by,
					zoom: this.zoom,
					filters: this.filters,
					hide_done: this.hide_done,
					shut: [...this.shut],
					tl_scroll: this.tl_scroll,
				})
			);
		} catch (e) {}
	}

	skeleton() {
		const stage = $(this.wrapper).find(".bb-stage");
		stage
			.attr("aria-busy", "true")
			.html(SKELETON[this.view] ? SKELETON[this.view]() : SKELETON.list());

		clearTimeout(this.slow);
		this.slow = setTimeout(() => {
			stage.find(".dpx-skel").addClass("slow");
		}, 6000);
	}

	settled() {
		clearTimeout(this.slow);
		$(this.wrapper).find(".bb-stage").removeAttr("aria-busy");
	}

	fail(e) {
		$(this.wrapper)
			.find(".bb-stage")
			.html(
				blank(
					"Could not load the board",
					String(e && e.message ? e.message : e) || "Reload the page to try again."
				)
			);
	}

	render_shell() {
		$(this.wrapper).html(`
			<div class="dpx-board">
				<div class="dpx-bb-tb">
					<div class="dpx-bb-tb-hd">
						<div class="dpx-bb-tb-title">
							<div class="dpx-bb-tb-row">
								<span class="dpx-bb-mark">${ico("trello", 14)}</span>
								<h2>Backlog</h2>
							</div>
							<div class="dpx-bb-tb-sub">Tasks, issues and requests in one pipeline</div>
						</div>
						<div class="dpx-bb-tb-act">
							<button class="dpx-bb-ico bb-reload" type="button" title="Refresh" aria-label="Refresh">${ico(
								"refresh"
							)}</button>
							<button class="dpx-bb-btn primary bb-new-task" type="button">New task</button>
							<span class="dpx-bb-div"></span>
							<div class="dpx-bb-views" role="tablist">
								<button data-view="board" class="${
									this.view === "board" ? "on" : ""
								}" role="tab" title="Board">${ico(
			"board",
			13
		)}<span>Board</span></button>
								<button data-view="list" class="${this.view === "list" ? "on" : ""}" role="tab" title="List">${ico(
			"list",
			13
		)}<span>List</span></button>
								<button data-view="timeline" class="${
									this.view === "timeline" ? "on" : ""
								}" role="tab" title="Timeline">${ico(
			"clock",
			13
		)}<span>Timeline</span></button>
								<button data-view="sheet" class="${
									this.view === "sheet" ? "on" : ""
								}" role="tab" title="Sheet">${ico(
			"table",
			13
		)}<span>Sheet</span></button>
							</div>
						</div>
					</div>
					<div class="dpx-bb-tb-cmd">
						<div class="dpx-bb-grp">
							<input type="search" class="dpx-bb-field dpx-bb-search" data-f="q"
								placeholder="Search work items" aria-label="Search work items">
						</div>
						<span class="dpx-bb-sep"></span>
						<div class="dpx-bb-grp">
							<span class="dpx-bb-grp-lbl">Filter</span>
							<select class="dpx-bb-field" data-f="source" aria-label="Source">
								<option value="">All sources</option>
								<option value="Task">Tasks</option>
								<option value="Issue">Issues</option>
								<option value="Request">Requests</option>
							</select>
							<select class="dpx-bb-field" data-f="assignee" aria-label="Assignee">
								<option value="">Anyone</option>
							</select>
							<select class="dpx-bb-field" data-f="module" aria-label="Module">
								<option value="">All modules</option>
							</select>
							<select class="dpx-bb-field" data-f="priority" aria-label="Priority">
								<option value="">Any priority</option>
							</select>
							<select class="dpx-bb-field" data-f="tag" aria-label="Tag">
								<option value="">Any tag</option>
							</select>
							<button type="button" class="dpx-bb-btn bb-clear" hidden>Clear</button>
						</div>
						<span class="dpx-bb-sep"></span>
						<div class="dpx-bb-grp">
							<span class="dpx-bb-grp-lbl">Group</span>
							<select class="dpx-bb-field bb-extra" aria-label="Group by">
								<option value="stage">Stage</option>
								<option value="assignee">Assignee</option>
								<option value="module">Module</option>
								<option value="priority">Priority</option>
								<option value="project">Project</option>
							</select>
						</div>
						<div class="dpx-bb-grp bb-zoom-grp" hidden>
							<span class="dpx-bb-grp-lbl">Zoom</span>
							<select class="dpx-bb-field bb-zoom" aria-label="Zoom">
								${ZOOMS.map(
									(z) => `<option value="${z.key}">${z.label}</option>`
								).join("")}
							</select>
						</div>
						<span class="dpx-bb-sep bb-tools-sep" hidden></span>
						<div class="dpx-bb-grp bb-tools"></div>
						<span class="dpx-bb-hint">
							<span class="bb-hint-txt"></span>
							<span class="dpx-bb-kbd">/</span><span>search</span>
							<span class="dpx-bb-kbd">1</span><span>–</span><span class="dpx-bb-kbd">4</span><span>views</span>
						</span>
					</div>
				</div>
				<div class="bb-stage"></div>
				<div class="dpx-bb-status"></div>
			</div>
		`);

		const root = $(this.wrapper);
		root.on("click", ".dpx-bb-views button", (e) => {
			const btn = $(e.currentTarget);
			root.find(".dpx-bb-views button").removeClass("on");
			btn.addClass("on");
			this.view = btn.data("view");
			this.limit = PAGE;
			this.save_prefs();
			this.render();
		});
		root.on("click", ".bb-reload", () => this.load());
		root.on("click", ".bb-new-task", () => this.new_task());
		root.on("input change", "[data-f]", (e) => {
			const el = $(e.currentTarget);
			this.filters[el.data("f")] = el.val();
			this.limit = PAGE;
			this.caps = {};
			this.save_prefs();
			clearTimeout(this.typing);
			this.typing = setTimeout(() => this.render(), e.type === "input" ? 180 : 0);
		});
		root.on("click", ".bb-clear", () => {
			this.filters = { ...BLANK_FILTERS };
			this.limit = PAGE;
			this.caps = {};
			this.save_prefs();
			this.render();
		});
		root.on("change", ".bb-extra", (e) => {
			this.group_by = $(e.currentTarget).val();
			this.save_prefs();
			this.render();
		});
		root.on("change", ".bb-zoom", (e) => {
			this.zoom = $(e.currentTarget).val();
			this.save_prefs();
			this.render();
		});
		root.on("click", ".dpx-bb-ghd button", (e) => {
			const key = $(e.currentTarget).data("group");
			this.shut.has(key) ? this.shut.delete(key) : this.shut.add(key);
			this.save_prefs();
			this.render();
		});
		root.on("click", ".dpx-bb-more", () => {
			this.limit += PAGE * 4;
			this.render();
		});

		root.on("click", ".bb-tool", (e) => this.tool($(e.currentTarget).data("tool")));
		root.on("click", ".bb-delete", (e) => this.delete_item($(e.currentTarget)));
		root.on("click", ".bb-reassign", (e) => this.reassign_item($(e.currentTarget)));
		// One dialog, reachable from every view - a card, a list row, a bar on the
		// timeline. Editing work should not depend on which way you happen to be
		// looking at it.
		root.on("click", ".bb-edit", (e) => {
			e.preventDefault();
			e.stopPropagation();
			this.edit_item($(e.currentTarget));
		});

		if (upande_dev_tools.attach_preview) upande_dev_tools.attach_preview(root[0]);

		this.bind_keys(root);
	}

	bind_keys(root) {
		const search = root.find(".dpx-bb-search");
		document.addEventListener("keydown", (e) => {
			const typing = /^(INPUT|SELECT|TEXTAREA)$/.test((e.target || {}).tagName || "");
			if (e.key === "Escape" && typing) return e.target.blur();
			if (typing || e.metaKey || e.ctrlKey || e.altKey) return;

			if (e.key === "/") {
				e.preventDefault();
				return search.trigger("focus").trigger("select");
			}
			const view = VIEW_KEYS[e.key];
			if (view) {
				e.preventDefault();
				root.find(`.dpx-bb-views button[data-view="${view}"]`).trigger("click");
			}
			if (e.key === "r") {
				e.preventDefault();
				this.load();
			}
		});
	}

	visible() {
		const q = (this.filters.q || "").toLowerCase();
		return this.items.filter((item) => {
			if (this.filters.source && item.doctype !== this.filters.source) return false;
			if (this.filters.priority && item.priority !== this.filters.priority) return false;
			if (this.filters.module && (item.module || "") !== this.filters.module) return false;
			if (this.filters.assignee) {
				if (this.filters.assignee === "__none") {
					if (item.assignees.length) return false;
				} else if (!item.assignees.includes(this.filters.assignee)) return false;
			}
			if (this.filters.tag && !(item.tags || []).includes(this.filters.tag)) return false;
			if (this.hide_done && item.stage === "Done") return false;
			if (q && !item.title.toLowerCase().includes(q) && !item.name.toLowerCase().includes(q))
				return false;
			return true;
		});
	}

	render() {
		this.render_assignees();
		this.render_priorities();
		this.render_tags();
		// render_extra drops a stored filter whose option no longer exists, so it has
		// to run before the rows are worked out rather than after - otherwise the first
		// paint is still filtered by a choice the toolbar has already given up on.
		this.render_extra();

		const rows = this.visible();
		this.render_tools();
		this.render_count(rows);

		const stage = $(this.wrapper).find(".bb-stage");
		if (this.view === "board") this.render_board(stage, rows);
		else if (this.view === "list") this.render_list(stage, rows);
		else if (this.view === "sheet") this.render_sheet(stage, rows);
		else this.render_timeline(stage, rows);
	}

	render_priorities() {
		const root = $(this.wrapper);
		const field = root.find('[data-f="priority"]');
		if (field.children().length <= 1) {
			// Priority Level is Master Data page-editable - list whatever's actually in use
			// rather than a hardcoded set, so a level added there shows up here too.
			const rank = {};
			this.items.forEach((i) => {
				if (i.priority) rank[i.priority] = i.rank;
			});
			const names = Object.keys(rank).sort((a, b) => rank[b] - rank[a]);
			field.append(
				names.map((p) => `<option value="${esc(p)}">${esc(p)}</option>`).join("")
			);
		}
	}

	render_tags() {
		const root = $(this.wrapper);
		const field = root.find('[data-f="tag"]');
		if (field.children().length <= 1) {
			const names = [...new Set(this.items.flatMap((item) => item.tags || []))].sort();
			field.html(
				['<option value="">Any tag</option>']
					.concat(names.map((t) => `<option value="${esc(t)}">${esc(t)}</option>`))
					.join("")
			);
		}
	}

	render_assignees() {
		const root = $(this.wrapper);
		const people = root.find('[data-f="assignee"]');
		if (people.children().length <= 1) {
			const names = [...new Set(this.items.flatMap((item) => item.assignees))].sort();
			people.html(
				['<option value="">Anyone</option>', '<option value="__none">Unassigned</option>']
					.concat(names.map((p) => `<option value="${esc(p)}">${esc(p)}</option>`))
					.join("")
			);
		}

		// Modules come from master data so you can filter to one that has nothing
		// in it yet and see that it is empty, rather than not see it at all.
		const modules = root.find('[data-f="module"]');
		const names = this.modules.length
			? this.modules.filter(Boolean)
			: [...new Set(this.items.map((item) => item.module).filter(Boolean))].sort();
		if (modules.children().length !== names.length + 1) {
			const held = modules.val();
			modules.html(
				['<option value="">All modules</option>']
					.concat(names.map((m) => `<option value="${esc(m)}">${esc(m)}</option>`))
					.join("")
			);
			if (held) modules.val(held);
		}
	}

	render_tools() {
		const root = $(this.wrapper);
		const tools = {
			list: `<button class="dpx-bb-btn bb-tool" data-tool="collapse">Collapse all</button>
				<button class="dpx-bb-btn bb-tool" data-tool="expand">Expand all</button>`,
			timeline: `<button class="dpx-bb-btn bb-tool" data-tool="today">Jump to today</button>`,
			sheet: `<button class="dpx-bb-btn bb-tool" data-tool="csv">Export CSV</button>
				<button class="dpx-bb-btn bb-tool" data-tool="fit">Fit columns</button>`,
			board: `<button class="dpx-bb-btn bb-tool" data-tool="done">${
				this.hide_done ? "Show done" : "Hide done"
			}</button>`,
		};
		root.find(".bb-tools").html(tools[this.view] || "");
		root.find(".bb-tools-sep").prop("hidden", !tools[this.view]);
	}

	new_task() {
		const projects = (this.projects || []).map((p) => [p.name, p.project_name || p.name]);
		const priorities = [
			["", __("No priority")],
			...(this.priority_levels || []).map((p) => [p, p]),
		];
		const modules = [
			["", __("No module")],
			...(this.modules || []).filter(Boolean).map((m) => [m, m]),
		];

		upande_dev_tools.open_modal(
			__("New task"),
			[
				{
					name: "project",
					label: __("Project"),
					type: "select",
					options: projects,
					value: this.project || "",
					required: true,
				},
				{ name: "subject", label: __("Title"), type: "text", required: true },
				{
					name: "tags",
					label: __("Tags"),
					type: "tagpicker",
					required: true,
					tags: this.work_tags || [],
				},
				{ name: "description", label: __("Description"), type: "textarea" },
				{ name: "priority", label: __("Priority"), type: "select", options: priorities },
				{ name: "module", label: __("Module"), type: "select", options: modules },
				{ name: "complete_by", label: __("Due date"), type: "date" },
				{
					name: "assign_to",
					label: __("Assign to"),
					type: "userlink",
					multiple: true,
					placeholder: __("Leave blank for unassigned"),
				},
			],
			(values) => {
				frappe
					.xcall("upande_dev_tools.api.board.create_task", values)
					.then(() => {
						upande_dev_tools.toast(__("Task created."), "green");
						this.load();
					})
					.catch((e) => {
						upande_dev_tools.toast(
							String((e && e.message) || e) || __("Could not create that task."),
							"red"
						);
					});
			},
			__("Create")
		);
	}

	edit_item(btn) {
		const row = btn.closest("[data-doctype]");
		const doctype = row.data("doctype");
		const name = row.data("name");
		const item = this.items.find((i) => i.doctype === doctype && i.name === name);
		if (!item) return;

		// The board carries no descriptions - thousands of rows of rich text that no
		// view renders - so the one item being edited fetches its own current values.
		btn.addClass("spin");
		frappe
			.xcall("upande_dev_tools.api.board.get_editable", { doctype, name })
			.then((values) => {
				btn.removeClass("spin");
				this.edit_form(item, values || {});
			})
			.catch((e) => {
				btn.removeClass("spin");
				upande_dev_tools.toast(
					String((e && e.message) || e) || __("Could not open that one."),
					"red"
				);
			});
	}

	edit_form(item, values) {
		const pairs = (list) => (list || []).map((v) => [v, v]);
		const desc = plain_description(values.description);
		const fields = [
			{
				name: "title",
				label: __("Title"),
				type: "text",
				value: values.title || item.title,
				required: true,
			},
			{
				name: "description",
				label: desc.rich
					? __("Description — has formatting, edit it on the item itself")
					: __("Description"),
				type: "textarea",
				value: desc.text,
				readonly: desc.rich,
			},
			{
				name: "stage",
				label: __("Stage"),
				type: "select",
				options: pairs(this.stages),
				value: values.stage || item.stage,
			},
			{
				name: "priority",
				label: __("Priority"),
				type: "select",
				options: [["", __("No priority")], ...pairs(this.priority_levels)],
				value: values.priority || "",
			},
			{
				name: "module",
				label: __("Module"),
				type: "select",
				options: [["", __("No module")], ...pairs((this.modules || []).filter(Boolean))],
				value: values.module || "",
			},
			{
				name: "project",
				label: __("Project"),
				type: "select",
				options: [
					["", __("No project")],
					...(this.projects || []).map((p) => [p.name, p.project_name || p.name]),
				],
				value: values.project || "",
			},
			{ name: "start", label: __("Start"), type: "date", value: values.start || "" },
			{ name: "end", label: __("Due date"), type: "date", value: values.end || "" },
			{
				name: "tags",
				label: __("Tags"),
				type: "tagpicker",
				tags: this.work_tags || [],
				selected: values.tags || [],
			},
		];
		if (item.doctype === "Task") {
			fields.push({
				name: "assign_to",
				label: __("Assigned to"),
				type: "userlink",
				multiple: true,
				value: (values.assignees || []).join(","),
				placeholder: __("Nobody yet"),
			});
		}

		upande_dev_tools.open_modal(
			__("Edit {0}", [item.name]),
			fields,
			(v) => {
				if (v.start && v.end && v.end < v.start) {
					upande_dev_tools.toast(
						__("Due date can't be before the start date."),
						"orange"
					);
					return;
				}
				// Leaving the key out entirely is what tells the server to keep what is
				// already there - sending the flattened text back would drop the markup.
				if (desc.rich) delete v.description;
				else v.description = rich_description(v.description);

				frappe
					.xcall("upande_dev_tools.api.board.update_work", {
						doctype: item.doctype,
						name: item.name,
						values: v,
					})
					.then(() => {
						upande_dev_tools.toast(__("Saved."), "green");
						this.load();
					})
					.catch((e) => {
						upande_dev_tools.toast(
							String((e && e.message) || e) || __("Could not save that."),
							"red"
						);
					});
			},
			__("Save changes")
		);
	}

	delete_item(btn) {
		const row = btn.closest("[data-doctype]");
		const doctype = row.data("doctype");
		const name = row.data("name");
		const item = this.items.find((i) => i.doctype === doctype && i.name === name);

		if (!window.confirm(__("Delete {0}? This can't be undone.", [item ? item.title : name])))
			return;

		const method =
			doctype === "Task"
				? "upande_dev_tools.api.board.delete_task"
				: "upande_dev_tools.api.requests.delete_request";
		frappe
			.xcall(method, { name })
			.then(() => {
				this.items = this.items.filter((i) => !(i.doctype === doctype && i.name === name));
				this.render();
				upande_dev_tools.toast(__("Deleted."), "green");
			})
			.catch((e) => {
				upande_dev_tools.toast(
					String((e && e.message) || e) || __("Could not delete that."),
					"red"
				);
			});
	}

	reassign_item(btn) {
		const row = btn.closest("[data-doctype]");
		const name = row.data("name");
		const item = this.items.find((i) => i.doctype === "Task" && i.name === name);
		upande_dev_tools.open_modal(
			__("Reassign {0}", [item ? item.title : name]),
			[
				{
					name: "assign_to",
					label: __("Assign to"),
					type: "userlink",
					multiple: true,
					required: true,
				},
				{ name: "complete_by", label: __("Complete by"), type: "date" },
				{ name: "comment", label: __("Comment"), type: "text" },
			],
			(values) => {
				frappe
					.xcall("upande_dev_tools.api.requests.reassign_task", { name, ...values })
					.then(() => {
						upande_dev_tools.toast(__("Reassigned."), "green");
						this.load();
					})
					.catch((e) => {
						upande_dev_tools.toast(
							String((e && e.message) || e) || __("Could not reassign that."),
							"red"
						);
					});
			},
			__("Reassign")
		);
	}

	tool(name) {
		if (name === "collapse") {
			this.group(this.visible()).forEach(([key]) => this.shut.add(key));
			this.save_prefs();
			return this.render();
		}
		if (name === "expand") {
			this.shut.clear();
			this.save_prefs();
			return this.render();
		}
		if (name === "done") {
			this.hide_done = !this.hide_done;
			this.save_prefs();
			return this.render();
		}
		if (name === "today") {
			const scroll = $(this.wrapper).find(".dpx-bb-tl-scroll")[0];
			const mark = $(this.wrapper).find(".dpx-bb-today")[0];
			if (scroll && mark)
				scroll.scrollTo({
					left: Math.max(0, mark.offsetLeft - scroll.clientWidth / 2),
					behavior: "smooth",
				});
			return;
		}
		if (name === "fit" && this.sheet)
			return this.render_sheet($(this.wrapper).find(".bb-stage"), this.visible());
		if (name === "csv") return this.export_csv();
	}

	export_csv() {
		const head = [
			"Type",
			"ID",
			"Work item",
			"Stage",
			"Priority",
			"Assignee",
			"Module",
			"Start",
			"Due",
			"Project",
			"Status",
		];
		const cell = (v) => `"${String(v == null ? "" : v).replace(/"/g, '""')}"`;
		const body = this.visible().map((i) =>
			[
				i.doctype,
				i.name,
				i.title,
				i.stage,
				i.priority,
				i.assignees.join("; "),
				i.module,
				i.start,
				i.end,
				i.project,
				i.status,
			]
				.map(cell)
				.join(",")
		);
		const blob = new Blob([[head.map(cell).join(","), ...body].join("\n")], {
			type: "text/csv;charset=utf-8",
		});
		const a = document.createElement("a");
		a.href = URL.createObjectURL(blob);
		a.download = `backlog-${today()}.csv`;
		document.body.appendChild(a);
		a.click();
		a.remove();
		setTimeout(() => URL.revokeObjectURL(a.href), 1000);
		upande_dev_tools.toast(__("Exported {0} rows.", [body.length]), "green");
	}

	render_extra() {
		const root = $(this.wrapper);
		root.find(".bb-extra").val(this.group_by);
		root.find(".bb-zoom").val(this.zoom);
		root.find(".bb-zoom-grp").prop("hidden", this.view !== "timeline");

		// Filters come back from storage, so the controls have to show what is actually
		// being applied - a board quietly hiding half its rows is a bug report. A stored
		// choice whose option no longer exists (the last task on someone left the board)
		// drops itself rather than filtering to nothing invisibly.
		let on = 0;
		Object.keys(BLANK_FILTERS).forEach((key) => {
			const el = root.find(`[data-f="${key}"]`);
			if (!el.length) return;
			const held = this.filters[key];
			if (held && el.is("select") && ![...el[0].options].some((o) => o.value === held)) {
				this.filters[key] = "";
			}
			if (this.filters[key]) on++;
			if (!el.is(":focus") && el.val() !== this.filters[key]) el.val(this.filters[key]);
		});
		root.find(".bb-clear")
			.prop("hidden", !on)
			.text(on === 1 ? __("Clear filter") : __("Clear {0} filters", [on]));
	}

	render_count(rows) {
		const late = rows.filter((item) => item.late).length;
		const done = rows.filter((item) => item.stage === "Done").length;
		const parts = [
			`<b>${rows.length}</b> items`,
			`<b>${rows.length - done}</b> open`,
			`<b>${done}</b> done`,
		];
		if (late) parts.push(`<span class="late">${late} late</span>`);
		if (this.total > this.items.length)
			parts.push(`<span class="sp">${this.items.length} of ${this.total} loaded</span>`);

		$(this.wrapper).find(".dpx-bb-status").html(parts.join("<span>·</span>"));
		$(this.wrapper)
			.find(".bb-hint-txt")
			.text(HINTS[this.view] || "");
	}

	group(rows) {
		if (this.group_by === "stage") {
			return this.stages.map((stage) => [
				stage,
				rows.filter((item) => item.stage === stage),
			]);
		}
		if (this.group_by === "priority") {
			return ["Urgent", "High", "Medium", "Low", "None"].map((p) => [
				p,
				rows.filter((item) => (item.priority || "None") === p),
			]);
		}
		const blank = { assignee: "Unassigned", module: "No module", project: "No project" }[
			this.group_by
		];
		const keys = new Set();
		rows.forEach((item) => {
			if (this.group_by === "assignee")
				item.assignees.length
					? item.assignees.forEach((a) => keys.add(a))
					: keys.add(blank);
			else keys.add(item[this.group_by] || blank);
		});
		const has = (item, key) =>
			this.group_by === "assignee"
				? key === blank
					? !item.assignees.length
					: item.assignees.includes(key)
				: (item[this.group_by] || blank) === key;
		// the unassigned or unscoped bucket sits last, not alphabetically
		return [...keys]
			.sort((a, b) => (a === blank ? 1 : b === blank ? -1 : a.localeCompare(b)))
			.map((key) => [key, rows.filter((item) => has(item, key))]);
	}

	render_board(stage, rows) {
		if (!rows.length) return stage.html(blank("Nothing here yet", empty_hint(this.filters)));

		const groups = this.group(rows);
		stage.html(
			`<div class="dpx-bb-cols">${groups
				.map(([key, items]) => {
					const cap = this.caps[key] || COLUMN_CAP;
					const shown = items.slice(0, cap);
					return `
			<div class="dpx-bb-col">
				<div class="dpx-bb-col-hd"><span>${esc(key)}</span><span class="n">${items.length}</span></div>
				<div class="dpx-bb-drop" data-stage="${esc(key)}">
					${
						items.length
							? shown.map((item) => card(item)).join("")
							: '<div class="dpx-bb-col-blank">Nothing in this stage</div>'
					}
					${
						items.length > shown.length
							? `<button class="dpx-bb-colmore" data-col="${esc(key)}">${
									items.length - shown.length
							  } more</button>`
							: ""
					}
				</div>
			</div>`;
				})
				.join("")}</div>`
		);

		stage.find(".dpx-bb-colmore").on("click", (e) => {
			const key = $(e.currentTarget).data("col");
			this.caps[key] = (this.caps[key] || COLUMN_CAP) + COLUMN_CAP * 4;
			this.render();
		});

		if (this.group_by === "stage") this.bind_drag(stage);
	}

	bind_drag(stage) {
		stage.find(".dpx-bb-card[draggable=true]").on("dragstart", (e) => {
			const card = $(e.currentTarget);
			e.originalEvent.dataTransfer.setData("text/plain", card.data("id"));
			card.addClass("dragging");
		});
		stage
			.find(".dpx-bb-card")
			.on("dragend", (e) => $(e.currentTarget).removeClass("dragging"));

		stage.find(".dpx-bb-drop").on("dragover", (e) => {
			e.preventDefault();
			$(e.currentTarget).addClass("over");
		});
		stage.find(".dpx-bb-drop").on("dragleave", (e) => $(e.currentTarget).removeClass("over"));
		stage.find(".dpx-bb-drop").on("drop", (e) => {
			e.preventDefault();
			const drop = $(e.currentTarget);
			drop.removeClass("over");
			this.move(e.originalEvent.dataTransfer.getData("text/plain"), drop.data("stage"));
		});
	}

	move(id, stage) {
		const item = this.items.find((row) => `${row.doctype}:${row.name}` === id);
		if (!item || item.stage === stage) return;

		const previous = { stage: item.stage, status: item.status };
		item.stage = stage;
		this.render();

		frappe
			.xcall("upande_dev_tools.api.board.set_stage", {
				doctype: item.doctype,
				name: item.name,
				stage,
			})
			.then((r) => {
				item.status = r.status;
				this.render();
			})
			.catch(() => {
				Object.assign(item, previous);
				this.render();
				upande_dev_tools.toast(__("Could not move that item."), "red");
			});
	}

	render_list(stage, rows) {
		if (!rows.length) return stage.html(blank("Nothing here yet", empty_hint(this.filters)));

		let shown = 0;
		const body = this.group(rows)
			.filter(([, items]) => items.length)
			.map(([key, items]) => {
				const shut = this.shut.has(key);
				const slice = shut ? [] : items.slice(0, Math.max(0, this.limit - shown));
				shown += slice.length;
				return (
					`<tr class="dpx-bb-ghd${shut ? " shut" : ""}"><td colspan="7">
						<button data-group="${esc(key)}"><i class="chev"></i>${esc(key)}
						<span class="n">${items.length}</span></button></td></tr>` +
					slice.map((item) => list_row(item)).join("")
				);
			})
			.join("");

		stage.html(`
			<div class="dpx-card"><div class="dpx-card-body dpx-bb-listwrap" style="padding:0 0 4px">
				<table class="dpx-bb-table">
					<colgroup><col><col style="width:128px"><col style="width:104px"><col class="opt" style="width:158px"><col class="opt" style="width:132px"><col style="width:104px"><col style="width:150px"></colgroup>
					<thead><tr><th>Work item</th><th>Stage</th><th>Priority</th><th class="opt">Assigned to</th>
						<th class="opt">Module</th><th style="text-align:right">Due</th><th>Actions</th></tr></thead>
					<tbody>${body}</tbody>
				</table>
				${
					shown < rows.length
						? `<button class="dpx-bb-more">Show more — ${
								rows.length - shown
						  } remaining</button>`
						: ""
				}
			</div></div>
		`);
	}

	render_sheet(stage, rows) {
		if (!rows.length) return stage.html(blank("Nothing here yet", empty_hint(this.filters)));

		stage.attr("aria-busy", "true").html(SKELETON.sheet());
		load_jspreadsheet()
			.then(() => {
				stage
					.removeAttr("aria-busy")
					.html(
						'<div class="dpx-bb-sheet"><div class="bb-sheet-bar"><span class="bb-save-status"></span></div><div class="host"></div></div>'
					);
				this.mount_sheet(stage.find(".host")[0], rows);
			})
			.catch(() =>
				stage.html(
					blank(
						"Sheet could not load",
						"The spreadsheet library did not load. Reload the page, or use the List view."
					)
				)
			);
	}

	mount_sheet(host, rows) {
		if (this.sheet) {
			try {
				this.sheet.destroy();
			} catch (e) {}
			this.sheet = null;
		}

		const order = rows.slice();
		this.sheet_rows = order;
		// What a person needs to read first sits first: what the work is, where
		// it stands, how urgent, who has it, when it is due. Identifiers are
		// reference material and go to the far right.
		const data = order.map((item) => [
			`${item.doctype}:${item.name}`,
			item.title,
			item.stage,
			item.priority || "",
			// jspreadsheet joins a multi-dropdown's values with ";" - see the Assignee column.
			(item.assignee_ids || []).join(";"),
			item.module || "",
			(item.tags || []).join(";"),
			item.end || "",
			item.start || "",
			item.status,
			item.project || "",
			item.name,
		]);

		const locked = { readOnly: true };
		this.sheet = jspreadsheet(host, {
			data,
			columns: [
				{ type: "hidden", title: "id" },
				{ type: "text", title: "Work item", width: 372 },
				{ type: "dropdown", title: "Stage", width: 124, source: this.stages },
				{
					type: "dropdown",
					title: "Priority",
					width: 104,
					source: ["", ...(this.priority_levels || [])],
				},
				{
					type: "dropdown",
					title: "Assignee",
					width: 142,
					// {id, name} pairs, not bare labels: the cell stores the email and shows the
					// person's name, so the two Brians on this bench never collapse into one. Typing
					// filters the list, which a 440-name dropdown is unusable without.
					autocomplete: true,
					// A Task can be on more than one person, same as the Reassign dialog. The cell
					// value is then a ";"-joined list of emails, which is jspreadsheet's own format.
					multiple: true,
					source: (this.people || []).map((p) => ({
						id: p.name,
						name: p.full_name || p.name,
					})),
				},
				{ type: "dropdown", title: "Module", width: 130, source: this.modules },
				{
					type: "dropdown",
					title: "Tags",
					width: 150,
					autocomplete: true,
					multiple: true,
					// Work Tag is the whole vocabulary, not just what is already in use -
					// the same list the New task and Edit dialogs pick from.
					source: this.work_tags || [],
				},
				{ type: "calendar", title: "Due", width: 100, options: { format: "YYYY-MM-DD" } },
				{
					type: "calendar",
					title: "Start",
					width: 100,
					options: { format: "YYYY-MM-DD" },
				},
				{ type: "dropdown", title: "Status", width: 104, source: TASK_QUICK_STATUSES },
				{
					type: "dropdown",
					title: "Project",
					width: 140,
					autocomplete: true,
					source: (this.projects || []).map((p) => ({
						id: p.name,
						name: p.project_name || p.name,
					})),
				},
				{ type: "text", title: "ID", width: 118, ...locked },
			],
			defaultColAlign: "left",
			columnSorting: true,
			columnDrag: false,
			tableOverflow: true,
			tableHeight: "calc(100vh - 268px)",
			tableWidth: "100%",
			lazyLoading: true,
			loadingSpin: true,
			freezeColumns: 2,
			filters: true,
			search: false,
			pagination: false,
			allowInsertRow: false,
			allowInsertColumn: false,
			allowDeleteRow: false,
			allowDeleteColumn: false,
			contextMenu: () => false,
			onbeforechange: (_el, cell, x, y, value) => this.guard_cell(y, value),
			onchange: (_el, _cell, x, y, value) => this.sheet_changed(Number(x), Number(y), value),
			updateTable: (_el, cell, x, y) => paint_cell(cell, Number(x), this.row_item(y)),
		});

		document.body.classList.add("dpx-menu-skin");
		this.label_filters(host);
		this.watch_clicks(host);
	}

	// Google Sheets opens a picker on one click; jspreadsheet waits for a second.
	// This has to run after the click has finished bubbling to document - jsuites
	// closes an open dropdown from its own document handler, so opening any earlier
	// (on selection, which fires at mousedown) opens and shuts it in one gesture.
	// jspreadsheet draws its filter row as bare inputs with no placeholder and no
	// affordance, so nobody discovers them. Name them after their column.
	// A filter belongs to its column, not to a row of its own. jspreadsheet draws
	// the filters as a second header row; that row is folded away and each header
	// grows a funnel that opens the filter cell underneath it.
	label_filters(host) {
		const titles = this.sheet.options.columns.map((c) => c.title);
		const filters = {};
		host.querySelectorAll("td.jexcel_column_filter").forEach((td) => {
			filters[td.getAttribute("data-x")] = td;
		});

		host.querySelectorAll("thead tr:first-child > td[data-x]").forEach((head) => {
			const x = head.getAttribute("data-x");
			const cell = filters[x];
			if (!cell || !titles[x] || head.style.display === "none") return;

			const btn = document.createElement("button");
			btn.className = "dpx-bb-funnel";
			btn.type = "button";
			btn.title = `Filter by ${titles[x]}`;
			btn.setAttribute("aria-label", `Filter by ${titles[x]}`);
			btn.addEventListener("mousedown", (e) => {
				e.stopPropagation();
				e.preventDefault();
				host.classList.remove("filters-folded");
				cell.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
				cell.dispatchEvent(new MouseEvent("click", { bubbles: true }));
				const input = cell.querySelector("input");
				if (input) input.focus();
			});
			head.appendChild(btn);
			head.classList.add("has-funnel");
		});

		host.classList.add("filters-folded");

		// Fold the row away again once you are done with it, unless a filter is set.
		host.addEventListener("focusout", () => {
			setTimeout(() => {
				if (host.contains(document.activeElement)) return;
				const active = [...host.querySelectorAll("td.jexcel_column_filter input")].some(
					(i) => i.value
				);
				if (!active) host.classList.add("filters-folded");
			}, 120);
		});
	}

	// jspreadsheet's columnSorting physically reorders its own row data, but this.sheet_rows
	// (built once at mount, in fetch order) never gets re-sorted to match - looking rows up by
	// y-index after any client-side sort silently applies the edit to the WRONG task. The
	// hidden id column (x=0) is what jspreadsheet itself keeps in sync with the visual row, so
	// reading it back and matching against this.items (never reordered) is the only safe way
	// to know which item row y actually is right now.
	row_item(y) {
		const id =
			this.sheet && typeof this.sheet.getValueFromCoords === "function"
				? this.sheet.getValueFromCoords(0, Number(y))
				: null;
		if (id) {
			const [doctype, name] = String(id).split(/:(.+)/);
			const found = this.items.find((i) => i.doctype === doctype && i.name === name);
			if (found) return found;
		}
		return this.sheet_rows[y];
	}

	// Opening a picker on one click is what makes this feel like Sheets, but it was
	// also eating every gesture that starts with a press on a cell: dragging across a
	// range, and the fill handle. So the editor now opens only on a click that stayed
	// still, carried no modifier, and left exactly one cell selected.
	watch_clicks(host) {
		host.addEventListener(
			"pointerdown",
			(e) => {
				this.press = {
					x: e.clientX,
					y: e.clientY,
					held: e.shiftKey || e.ctrlKey || e.metaKey,
					corner: !!e.target.closest(".jexcel_corner"),
				};
			},
			true
		);

		host.addEventListener("click", (e) => {
			const press = this.press;
			this.press = null;
			if (!press || press.held || press.corner) return;
			// A drag, not a click. 4px is about the wobble of a real finger or mouse.
			if (Math.abs(e.clientX - press.x) > 4 || Math.abs(e.clientY - press.y) > 4) return;

			const td = e.target.closest("td[data-x]");
			if (!td || td.classList.contains("editor")) return;

			const x = Number(td.getAttribute("data-x"));
			const y = Number(td.getAttribute("data-y"));
			// The title is a plain text cell and also the thing you click to read a row,
			// so it keeps the normal double-click. The pickers open on one.
			if (!SHEET_FIELDS[x] || x === 1) return;
			if (this.spans_a_range()) return;

			const item = this.row_item(y);
			if (!item || !item.movable) return;

			clearTimeout(this.opening);
			this.opening = setTimeout(() => {
				if (this.spans_a_range()) return;
				const cell = this.sheet.getCellFromCoords(x, y);
				if (cell && !cell.classList.contains("editor")) this.sheet.openEditor(cell);
			}, 0);
		});
	}

	spans_a_range() {
		const at = this.sheet && this.sheet.selectedCell;
		if (!at) return false;
		return Number(at[0]) !== Number(at[2]) || Number(at[1]) !== Number(at[3]);
	}

	guard_cell(y, value) {
		const item = this.row_item(y);
		if (item && !item.movable) {
			upande_dev_tools.toast(
				__("Requests move through their own workflow, not the board."),
				"orange"
			);
			return false;
		}
		return value;
	}

	sheet_changed(x, y, value) {
		const item = this.row_item(y);
		if (!item || !item.movable) return;

		const field = SHEET_FIELDS[x];
		if (!field) return;

		if ((field === "assignee" || field === "status") && item.doctype !== "Task") {
			this.render();
			upande_dev_tools.toast(
				__("Only tasks can have their {0} changed here.", [field]),
				"orange"
			);
			return;
		}

		if (field === "title" && !String(value || "").trim()) {
			this.render();
			upande_dev_tools.toast(__("A work item needs a title."), "orange");
			return;
		}

		// The assignee cell holds an email, which lives on assignee_ids - not item.assignee,
		// which has never existed, so this comparison used to never short-circuit.
		const current =
			field === "stage"
				? item.stage
				: field === "assignee"
				? (item.assignee_ids || []).join(";")
				: field === "tags"
				? (item.tags || []).join(";")
				: item[field] || "";
		if (String(value || "") === String(current || "")) return;

		if (field === "end" && item.start && value && value < item.start) {
			this.render();
			upande_dev_tools.toast(__("Due date can't be before the start date."), "orange");
			return;
		}
		if (field === "start" && item.end && value && value > item.end) {
			this.render();
			upande_dev_tools.toast(__("Start date can't be after the due date."), "orange");
			return;
		}

		this.queue_cell(item, field, value || "");
	}

	// A fill dragged down a column, or a paste, fires onchange once per cell. Saving each
	// one on its own meant a request and a whole board reload per cell - twenty rows was
	// twenty reloads, and the last one always won the race. They are collected here and
	// sent as a single call instead.
	queue_cell(item, field, value) {
		this.pending = this.pending || new Map();
		const key = `${item.doctype}:${item.name}`;
		const held = this.pending.get(key) || { item, before: { ...item }, values: {} };

		const change = this.apply_locally(item, field, value);
		if (!change) return;

		Object.assign(held.values, change);
		this.pending.set(key, held);

		clearTimeout(this.flushing);
		this.flushing = setTimeout(() => this.flush_cells(), 140);
	}

	// Moves the board's own copy first so the sheet answers immediately, and returns what
	// the server needs for that field - or nothing at all if the value cannot be used.
	apply_locally(item, field, value) {
		if (field === "assignee") {
			const emails = String(value || "")
				.split(";")
				.map((e) => e.trim())
				.filter(Boolean);
			const people = emails.map((email) =>
				(this.people || []).find((p) => p.name === email)
			);
			// An empty cell would mean "take this off everyone", which reassign_task refuses -
			// clearing an assignment is what the Reassign dialog is for.
			if (!people.length || people.some((p) => !p)) {
				this.set_save_status("error");
				this.render();
				upande_dev_tools.toast(
					people.length ? __("Pick names from the list.") : __("Pick at least one name."),
					"orange"
				);
				return null;
			}
			item.assignee_ids = people.map((p) => p.name);
			item.assignees = people.map((p) => p.full_name || p.name);
			return { assign_to: item.assignee_ids };
		}

		if (field === "tags") {
			item.tags = String(value || "")
				.split(";")
				.map((t) => t.trim())
				.filter(Boolean);
			return { tags: item.tags };
		}

		item[field] = value;
		if (field === "priority") item.rank = RANK[value] || 0;
		return { [field]: value };
	}

	flush_cells() {
		const batch = [...(this.pending || new Map()).values()];
		this.pending = null;
		if (!batch.length) return;

		this.set_save_status("saving", batch.length);
		frappe
			.xcall("upande_dev_tools.api.board.bulk_update", {
				changes: batch.map(({ item, values }) => ({
					doctype: item.doctype,
					name: item.name,
					values,
				})),
			})
			.then((result) => {
				const failed = (result && result.failed) || [];
				if (failed.length) {
					// Rows are independent on the server, so the ones that saved stay saved
					// and only the rest are named.
					this.set_save_status("error", failed.length);
					upande_dev_tools.toast(
						failed.length === 1
							? failed[0].error
							: __("{0} of {1} rows could not be saved.", [
									failed.length,
									batch.length,
							  ]),
						"red"
					);
				} else {
					this.set_save_status("saved", batch.length);
				}
				// One reload for the whole batch, not one per cell.
				this.load();
			})
			.catch((e) => {
				batch.forEach(({ item, before }) => Object.assign(item, before));
				this.set_save_status("error", batch.length);
				this.render();
				upande_dev_tools.toast(
					String((e && e.message) || e) || __("Could not save those cells."),
					"red"
				);
			});
	}

	set_save_status(state, n) {
		const el = $(this.wrapper).find(".bb-save-status");
		if (!el.length) return;
		clearTimeout(this._save_status_timer);
		const rows = n > 1 ? __("{0} changes", [n]) : __("1 change");
		if (state === "saving")
			return el.text(__("Saving {0}…", [rows])).attr("data-state", "saving");
		if (state === "error")
			return el.text(__("{0} could not be saved", [rows])).attr("data-state", "error");
		el.text(__("{0} saved", [rows])).attr("data-state", "saved");
		this._save_status_timer = setTimeout(() => el.text("").removeAttr("data-state"), 2500);
	}

	render_timeline(stage, rows) {
		const dated = rows.filter((item) => item.start || item.end);
		if (!dated.length) {
			return stage.html(
				blank(
					"No dates to plot",
					"Tasks appear here once they have a planned or due date, and issues once they have a resolution date. Set one on a work item and it lands on this timeline."
				)
			);
		}

		const day_w = ZOOM[this.zoom];
		const spans = dated.map((item) => {
			const start = date_of(item.start || item.end);
			const end = date_of(item.end || item.start);
			return { item, start, end: end < start ? start : end };
		});
		spans.sort((a, b) => a.start - b.start || a.end - b.end);

		const first = week_start(new Date(Math.min(...spans.map((s) => s.start)) - 4 * DAY));
		const last = new Date(Math.max(...spans.map((s) => s.end)) + 6 * DAY);
		const days = Math.round((last - first) / DAY);
		const width = days * day_w;
		const x = (d) => Math.round(((d - first) / DAY) * day_w);

		// What the header can hold depends on how wide a day is, not on what the zoom
		// level happens to be called - there are seven rungs on the ladder now, and a
		// weekly gridline every 21px is noise rather than scale.
		const per_day = day_w >= 24;
		const week_step = day_w >= 12 ? 1 : day_w >= 7 ? 2 : 4;
		const weekends = day_w >= 8;

		const months = [];
		const ticks = [];
		const rules = [];
		let week = 0;
		for (let i = 0; i <= days; i++) {
			const d = new Date(first.getTime() + i * DAY);
			const at = i * day_w;
			if (d.getUTCDate() === 1) {
				months.push(
					`<div class="dpx-bb-mo" style="left:${at}px">${
						MONTHS_LONG[d.getUTCMonth()]
					} ${d.getUTCFullYear()}</div>`
				);
				rules.push(`<div class="mo" style="left:${at}px"></div>`);
			} else if (per_day) {
				rules.push(`<div class="wk" style="left:${at}px"></div>`);
				ticks.push(
					`<div class="dpx-bb-tk${d.getUTCDay() % 6 === 0 ? " dim" : ""}" style="left:${
						at + day_w / 2
					}px">${DOW[d.getUTCDay()]}<b>${d.getUTCDate()}</b></div>`
				);
			} else if (d.getUTCDay() === 1) {
				if (week % week_step === 0) {
					rules.push(`<div class="wk" style="left:${at}px"></div>`);
					ticks.push(
						`<div class="dpx-bb-tk" style="left:${at}px">${d.getUTCDate()}</div>`
					);
				}
				week++;
			}
			if (weekends && d.getUTCDay() === 6)
				rules.push(`<div class="we" style="left:${at}px;width:${day_w * 2}px"></div>`);
		}

		const now = date_of(today());
		const inside = now >= first && now <= last;
		const marker = inside ? `<div class="dpx-bb-today" style="left:${x(now)}px"></div>` : "";
		const tag = inside
			? `<div class="dpx-bb-todaytag" style="left:${x(now)}px">Today</div>`
			: "";

		const lanes = this.group_by === "stage" ? null : this.group(dated);
		const body = lanes
			? lanes
					.filter(([, items]) => items.length)
					.map(([key, items]) => {
						const own = spans.filter((s) => items.includes(s.item));
						if (!own.length) return "";
						return (
							lane_head(key, own) +
							own.map((span) => tl_row(span, x, width)).join("")
						);
					})
					.join("")
			: spans.map((span) => tl_row(span, x, width)).join("");

		stage.html(`
			<div class="dpx-bb-tl"><div class="dpx-bb-tl-scroll"><div class="dpx-bb-tl-inner">
				<div class="dpx-bb-tl-hd">
					<div class="corner">${spans.length} scheduled</div>
					<div class="band" style="width:${width}px">${months.join("")}${ticks.join("")}${tag}</div>
				</div>
				<div class="dpx-bb-tl-body">
					<div class="dpx-bb-grid" style="width:${width}px">${rules.join("")}${marker}</div>
					${body}
				</div>
			</div></div>
			<div class="dpx-bb-legend">
				<span><i class="prog"></i>In progress</span>
				<span><i class="rev"></i>In review</span>
				<span><i class="tri"></i>Triage</span>
				<span><i></i>Queued</span>
				<span><i class="late"></i>Past due</span>
				<span><i class="done"></i>Done</span>
				<span><i class="today"></i>Today</span>
				<span class="sp"><span class="dpx-bb-kbd">Ctrl</span> + scroll to zoom</span>
				<span class="sp">${spans.length} of ${rows.length} items have dates</span>
			</div></div>
		`);

		const scroll = stage.find(".dpx-bb-tl-scroll")[0];
		if (scroll) {
			if (this.tl_scroll) {
				scroll.scrollLeft = this.tl_scroll.left;
				scroll.scrollTop = this.tl_scroll.top;
			} else if (inside) {
				scroll.scrollLeft = Math.max(0, x(now) - scroll.clientWidth / 2);
			}
			scroll.addEventListener("scroll", () => {
				this.tl_scroll = { left: scroll.scrollLeft, top: scroll.scrollTop };
				clearTimeout(this.tl_keep);
				this.tl_keep = setTimeout(() => this.save_prefs(), 400);
			});

			// Ctrl + wheel is what every timeline in this category does. The date under
			// the pointer is what has to stay put while the scale changes underneath it -
			// zooming that re-anchors on the left edge throws you somewhere else entirely.
			scroll.addEventListener(
				"wheel",
				(e) => {
					if (!e.ctrlKey && !e.metaKey) return;
					e.preventDefault();

					// One gesture is one rung. A wheel notch arrives as several events
					// and a trackpad as dozens, so stepping per event walks the whole
					// ladder from a single flick.
					// deltaMode: 0 pixels, 1 lines, 2 pages - a mouse reports one notch
					// as about 100px, a trackpad as a stream of small ones.
					const delta =
						e.deltaMode === 1 ? e.deltaY * 16 : e.deltaMode === 2 ? e.deltaY * 400 : e.deltaY;
					this.wheel = (this.wheel || 0) + delta;
					if (Math.abs(this.wheel) < WHEEL_STEP) return;
					const step = this.wheel < 0 ? 1 : -1;
					this.wheel = 0;

					const at = ZOOM_KEYS.indexOf(this.zoom);
					const next = ZOOM_KEYS[Math.min(ZOOM_KEYS.length - 1, Math.max(0, at + step))];
					if (!next || next === this.zoom) return;

					const cursor = e.clientX - scroll.getBoundingClientRect().left;
					const day = (scroll.scrollLeft + cursor) / day_w;
					this.zoom = next;
					this.tl_scroll = {
						left: Math.max(0, day * ZOOM[next] - cursor),
						top: scroll.scrollTop,
					};
					this.save_prefs();
					this.render();
				},
				{ passive: false }
			);
		}

		if (this.moved) {
			const bar = stage.find(`.dpx-bb-tlbar[data-id="${this.moved}"]`);
			bar.addClass("just-moved");
			if (bar[0] && bar[0].scrollIntoView)
				bar[0].scrollIntoView({ block: "nearest", inline: "nearest" });
			setTimeout(() => bar.removeClass("just-moved"), 1400);
			this.moved = null;
		}

		this.bind_drag_bars(stage, day_w, first);
	}

	// A schedule you can only read is a report. Grabbing a bar moves both dates by
	// the same number of days; grabbing an edge moves one of them.
	bind_drag_bars(stage, day_w, first) {
		let drag = null;

		const onMove = (e) => {
			if (!drag) return;
			e.preventDefault();
			const shift = Math.round((e.clientX - drag.fromX) / day_w);
			if (shift === drag.shift) return;
			drag.shift = shift;

			const start = drag.mode === "end" ? 0 : shift;
			const end = drag.mode === "start" ? 0 : shift;
			let left = drag.left + start * day_w;
			let width = drag.width + (end - start) * day_w;
			if (width < day_w) {
				width = day_w;
				if (drag.mode === "start") left = drag.left + drag.width - day_w;
			}
			drag.bar.style.left = `${left}px`;
			drag.bar.style.width = `${width}px`;
			drag.readout.textContent = `${fmt(add_days(drag.start, start))} → ${fmt(
				add_days(drag.end, end)
			)}`;
			drag.readout.style.left = `${left}px`;
		};

		const onUp = () => {
			if (!drag) return;
			const { item, mode, shift, start, end } = drag;
			document.removeEventListener("pointermove", onMove);
			document.removeEventListener("pointerup", onUp);
			stage.find(".dpx-bb-tl").removeClass("dragging");
			drag.bar.classList.remove("held");
			drag.readout.remove();
			drag = null;

			if (!shift) return this.render();
			const moves = [];
			if (mode !== "end") moves.push(["start", iso(add_days(start, shift))]);
			if (mode !== "start") moves.push(["end", iso(add_days(end, shift))]);
			this.reschedule(item, moves);
		};

		stage.find(".dpx-bb-tlbar[data-movable]").on("pointerdown", (e) => {
			if (e.button !== 0) return;
			e.preventDefault();
			const bar = e.currentTarget;
			const item = this.items.find((i) => `${i.doctype}:${i.name}` === $(bar).data("id"));
			if (!item) return;

			// A narrow bar has no room for two handles and a middle: grabbing anywhere on
			// it moves the whole thing, and one end gets changed from the sheet or the
			// edit dialog instead of by a 3px target nobody can hit.
			const box = bar.getBoundingClientRect();
			const edge =
				box.width < EDGE_BAR
					? "move"
					: e.clientX - box.left < EDGE
					? "start"
					: box.right - e.clientX < EDGE
					? "end"
					: "move";
			const readout = document.createElement("div");
			readout.className = "dpx-bb-readout";
			bar.parentNode.appendChild(readout);

			drag = {
				bar,
				item,
				mode: edge,
				fromX: e.clientX,
				shift: 0,
				left: bar.offsetLeft,
				width: bar.offsetWidth,
				start: date_of(item.start || item.end),
				end: date_of(item.end || item.start),
				readout,
			};
			readout.style.left = `${drag.left}px`;
			readout.textContent = `${fmt(drag.start)} → ${fmt(drag.end)}`;
			bar.classList.add("held");
			stage.find(".dpx-bb-tl").addClass("dragging");
			document.addEventListener("pointermove", onMove);
			document.addEventListener("pointerup", onUp);
		});
	}

	reschedule(item, moves) {
		const before = { start: item.start, end: item.end };
		moves.forEach(([field, value]) => (item[field] = value));
		this.moved = `${item.doctype}:${item.name}`;
		this.render();

		Promise.all(
			moves.map(([field, value]) =>
				frappe.xcall("upande_dev_tools.api.board.set_field", {
					doctype: item.doctype,
					name: item.name,
					field,
					value,
				})
			)
		)
			// The board is already showing the new dates, so there is nothing to fetch.
			// Reloading here was what threw you to a different part of the schedule.
			.then(() =>
				upande_dev_tools.toast(__("{0} moved to {1}", [item.title, item.start]), "green")
			)
			.catch(() => {
				Object.assign(item, before);
				this.moved = null;
				this.render();
				upande_dev_tools.toast(__("Could not move that work."), "red");
			});
	}
};

function card(item) {
	const cls = ["dpx-bb-card"];
	if (!item.movable) cls.push("locked");
	return `
		<div class="${cls.join(" ")}" data-id="${esc(item.doctype)}:${esc(item.name)}"
			data-doctype="${esc(item.doctype)}" data-name="${esc(item.name)}"
			${item.movable ? 'draggable="true"' : ""}>
			<div class="hd">${pri(item)}<span class="dpx-bb-src">${SOURCES[item.doctype]}</span>
				${
					item.movable
						? `<button type="button" class="dpx-bb-ico bb-edit" title="Edit"
							aria-label="Edit ${esc(item.title)}">${ico("edit", 13)}</button>`
						: ""
				}</div>
			<div class="t">${esc(item.title)}</div>
			<div class="m">
				${people(item)}
				${item.end ? `<span class="d${item.late ? " late" : ""}">${esc(item.end)}</span>` : ""}
			</div>
		</div>`;
}

function list_row(item) {
	const cls = ["dpx-bb-row"];
	if (item.stage === "Done") cls.push("done");
	const tags = (item.tags || [])
		.map((t) => `<span class="dpx-bb-chip">${esc(t)}</span>`)
		.join(" ");
	const can_reassign = item.doctype === "Task";
	const can_delete = item.doctype === "Task" || item.doctype === "Request";
	return `
		<tr class="${cls.join(" ")}" data-id="${esc(item.doctype)}:${esc(item.name)}"
			data-doctype="${esc(item.doctype)}" data-name="${esc(item.name)}">
			<td><div class="subj">${pri(item)}<span class="dpx-bb-src">${SOURCES[item.doctype]}</span>
				<a href="${link(item)}">${esc(item.title)}</a></div>${
		tags ? `<div class="bb-tags">${tags}</div>` : ""
	}</td>
			<td><span class="dpx-bb-chip st-${slug(item.stage)}">${esc(item.stage)}</span></td>
			<td>${
				item.priority
					? `<span class="dpx-bb-chip pr-${slug(item.priority)}">${esc(
							item.priority
					  )}</span>`
					: '<span class="muted">—</span>'
			}</td>
			<td class="opt">${people(item)}</td>
			<td class="opt muted">${esc(item.module || "—")}</td>
			<td class="num${item.late ? " late" : ""}">${esc(item.end || "—")}</td>
			<td class="bb-row-act">
				${
					item.movable
						? `<button type="button" class="dpx-bb-ico bb-edit" title="Edit"
							aria-label="Edit ${esc(item.title)}">${ico("edit")}</button>`
						: ""
				}
				${
					can_reassign
						? `<button type="button" class="dpx-bb-ico bb-reassign" title="Reassign">${ico(
								"assign"
						  )}</button>`
						: ""
				}
				${
					can_delete
						? `<button type="button" class="dpx-bb-ico bb-delete" title="Delete">${ico(
								"trash"
						  )}</button>`
						: ""
				}
			</td>
		</tr>`;
}

function tl_row({ item, start, end }, x, width) {
	const left = x(start);
	const bar_w = Math.max(x(end) - left + 4, MIN_BAR);
	const done = item.stage === "Done";
	const cls = done ? "done" : item.late ? "late" : `st-${slug(item.stage)}`;
	const label = start.getTime() === end.getTime() ? fmt(start) : `${fmt(start)} → ${fmt(end)}`;
	const days = Math.round((end - start) / DAY) + 1;
	// The bar carries its own name once it is wide enough to hold one, so the
	// eye reads the schedule without travelling back to the gutter.
	const inside = bar_w > 70 ? `<span class="lb">${esc(item.title)}</span>` : "";
	const outside =
		bar_w > 70 ? "" : `<div class="dpx-bb-span" style="left:${left + bar_w}px">${label}</div>`;

	return `
		<div class="dpx-bb-tl-row${done ? " done" : ""}"
			data-doctype="${esc(item.doctype)}" data-name="${esc(item.name)}">
			<div class="name">
				<span class="dpx-bb-pri p${item.rank - 1}" title="${esc(item.priority || "No priority")}"></span>
				<a href="${link(item)}" title="${esc(item.title)}">${esc(item.title)}</a>
				<span class="dpx-bb-chip st-${slug(item.stage)} tiny">${esc(
		SHORT[item.stage] || item.stage
	)}</span>
				${
					item.assignees.length
						? `<span class="dpx-bb-av" title="${esc(item.assignees.join(", "))}">${esc(
								initials(item.assignees[0])
						  )}</span>`
						: ""
				}
				${
					item.movable
						? `<button type="button" class="dpx-bb-ico bb-edit" title="Edit"
							aria-label="Edit ${esc(item.title)}">${ico("edit", 12)}</button>`
						: ""
				}
			</div>
			<div class="track" style="width:${width}px">
				<a class="dpx-bb-tlbar ${cls}" href="${link(item)}" data-id="${esc(item.doctype)}:${esc(
		item.name
	)}"
					${item.movable ? "data-movable" : ""} style="left:${left}px;width:${bar_w}px"
					title="${esc(item.title)} · ${esc(item.stage)} · ${label} · ${days} day${days === 1 ? "" : "s"}${
		item.assignees.length ? ` · ${esc(item.assignees.join(", "))}` : ""
	}">${inside}</a>
				${outside}
			</div>
		</div>`;
}

// A lane is a person's week. It says how much is on them, not just what.
function lane_head(key, spans) {
	const late = spans.filter((s) => s.item.late).length;
	const days = spans.reduce((n, s) => n + Math.round((s.end - s.start) / DAY) + 1, 0);
	const load = Math.min(100, Math.round((days / (spans.length * 14 || 1)) * 100));
	return `
		<div class="dpx-bb-tl-lane">
			<span class="who">${esc(key)}</span>
			<span class="n">${spans.length} item${spans.length === 1 ? "" : "s"}</span>
			${late ? `<span class="late">${late} late</span>` : ""}
			<span class="load" title="${days} days committed across ${spans.length} items">
				<i style="width:${load}%"></i>
			</span>
			<span class="days">${days}d</span>
		</div>`;
}

function add_days(date, n) {
	const d = new Date(date.getTime());
	d.setUTCDate(d.getUTCDate() + n);
	return d;
}

function iso(date) {
	return date.toISOString().slice(0, 10);
}

function week_start(date) {
	const d = new Date(date.getTime());
	const shift = (d.getUTCDay() + 6) % 7;
	d.setUTCDate(d.getUTCDate() - shift);
	return d;
}

function pri(item) {
	const label = item.priority || "No priority";
	return `<span class="dpx-bb-pri p${item.rank - 1}" title="${esc(label)}"></span>`;
}

function people(item) {
	if (!item.assignees.length) return '<span class="dpx-bb-who none">Unassigned</span>';
	const [first, ...rest] = item.assignees;
	return `<span class="dpx-bb-who" title="${esc(item.assignees.join(", "))}">
		<span class="dpx-bb-av">${esc(initials(first))}</span>${esc(first)}${
		rest.length ? ` +${rest.length}` : ""
	}</span>`;
}

function blank(heading, body) {
	return `<div class="dpx-card"><div class="dpx-bb-blank">
		<h3>${esc(heading)}</h3><p>${esc(body)}</p></div></div>`;
}

function empty_hint(filters) {
	return Object.values(filters).some(Boolean)
		? "No work item matches these filters. Clear one to widen the search."
		: "Tasks, issues and requests land here as they are raised.";
}

function link(item) {
	return `/app/${slug(item.doctype)}/${encodeURIComponent(item.name)}`;
}

function initials(name) {
	return name
		.split(/\s+/)
		.slice(0, 2)
		.map((part) => part[0] || "")
		.join("")
		.toUpperCase();
}

function slug(stage) {
	return stage.toLowerCase().replace(/\s+/g, "-");
}

function today() {
	if (frappe.datetime && frappe.datetime.get_today) return frappe.datetime.get_today();
	return new Date().toISOString().slice(0, 10);
}

function date_of(value) {
	const [y, m, d] = value.split("-").map(Number);
	return new Date(Date.UTC(y, m - 1, d));
}

function fmt(date) {
	return `${MONTHS[date.getUTCMonth()]} ${date.getUTCDate()}`;
}

// A description is a Text Editor field. Flattening one that carries a screenshot or
// a table into a textarea and saving it back would quietly destroy it, so only the
// plain ones are editable here and the rest say where to go instead.
function plain_description(html) {
	if (!html) return { text: "", rich: false };
	const rich = /<(?!\/?(p|br|div|b|i|em|strong|span)\b)[a-z]/i.test(html);
	const text = String(html)
		.replace(/<\/(p|div)>/gi, "\n")
		.replace(/<br\s*\/?>/gi, "\n")
		.replace(/<[^>]*>/g, "")
		.replace(/&nbsp;/gi, " ")
		.replace(/&amp;/gi, "&")
		.replace(/&lt;/gi, "<")
		.replace(/&gt;/gi, ">")
		.trim();
	return { text, rich };
}

function rich_description(text) {
	const body = String(text || "").trim();
	return body ? esc(body).replace(/\n/g, "<br>") : "";
}

function esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}
