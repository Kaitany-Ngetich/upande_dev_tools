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
const ZOOM = { days: 34, weeks: 15, months: 5 };
const PAGE = 60;
const PREFS = "dpx-backlog";

function read_prefs() {
	try {
		return JSON.parse(localStorage.getItem(PREFS) || "{}") || {};
	} catch (e) {
		return {};
	}
}
const COLUMN_CAP = 25;
const VIEW_KEYS = { 1: "board", 2: "list", 3: "timeline", 4: "sheet" };
const SHEET_FIELDS = { 2: "stage", 3: "priority", 5: "module", 6: "end", 7: "start" };
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
	board: "Drag a card between stages to move it",
	list: "Click a group to collapse it",
	timeline: "Bars run from start to due date",
	sheet: "Editable: Stage · Priority · Start · Due",
};
const ICONS = {
	board: '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>',
	list: '<path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M3 6h.01"/><path d="M3 12h.01"/><path d="M3 18h.01"/>',
	clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
	table: '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/><path d="M3 15h18"/><path d="M9 3v18"/><path d="M15 3v18"/>',
	trello: '<rect width="18" height="18" x="3" y="3" rx="2"/><rect width="3" height="9" x="7" y="7"/><rect width="3" height="5" x="14" y="7"/>',
	refresh:
		'<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
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
	} else if (x === 6 || x === 7) {
		cell.classList.add("bb-mono");
		if (x === 6 && item.late) cell.classList.add("bb-late");
	} else if (x === 8 || x === 9) {
		cell.classList.add("bb-quiet");
	} else if (x === 10) {
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

upande_dev_tools.BacklogBoard = class BacklogBoard {
	constructor(wrapper, project) {
		this.wrapper = wrapper;
		this.project = project;
		this.items = [];
		this.stages = [];
		this.total = 0;
		this.modules = [];
		const kept = read_prefs();
		this.view = kept.view || "board";
		this.group_by = kept.group_by || "stage";
		this.zoom = kept.zoom || "weeks";
		this.shut = new Set();
		this.caps = {};
		this.hide_done = false;
		this.limit = PAGE;
		this.filters = { q: "", source: "", assignee: "", module: "", priority: "" };
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
				this.modules = ["", ...(m || [])];
				if (this.items.length) this.render();
			})
			.catch(() => {});
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
				JSON.stringify({ view: this.view, group_by: this.group_by, zoom: this.zoom })
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
								<option value="Urgent">Urgent</option>
								<option value="High">High</option>
								<option value="Medium">Medium</option>
								<option value="Low">Low</option>
							</select>
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
								<option value="days">Days</option>
								<option value="weeks">Weeks</option>
								<option value="months">Months</option>
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
		root.on("input change", "[data-f]", (e) => {
			const el = $(e.currentTarget);
			this.filters[el.data("f")] = el.val();
			this.limit = PAGE;
			this.caps = {};
			clearTimeout(this.typing);
			this.typing = setTimeout(() => this.render(), e.type === "input" ? 180 : 0);
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
			this.render();
		});
		root.on("click", ".dpx-bb-more", () => {
			this.limit += PAGE * 4;
			this.render();
		});

		root.on("click", ".bb-tool", (e) => this.tool($(e.currentTarget).data("tool")));

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
			if (this.hide_done && item.stage === "Done") return false;
			if (q && !item.title.toLowerCase().includes(q) && !item.name.toLowerCase().includes(q))
				return false;
			return true;
		});
	}

	render() {
		const rows = this.visible();
		this.render_assignees();
		this.render_extra();
		this.render_tools();
		this.render_count(rows);

		const stage = $(this.wrapper).find(".bb-stage");
		if (this.view === "board") this.render_board(stage, rows);
		else if (this.view === "list") this.render_list(stage, rows);
		else if (this.view === "sheet") this.render_sheet(stage, rows);
		else this.render_timeline(stage, rows);
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

	tool(name) {
		if (name === "collapse") {
			this.group(this.visible()).forEach(([key]) => this.shut.add(key));
			return this.render();
		}
		if (name === "expand") {
			this.shut.clear();
			return this.render();
		}
		if (name === "done") {
			this.hide_done = !this.hide_done;
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
		frappe.show_alert({
			message: __("Exported {0} rows.", [body.length]),
			indicator: "green",
		});
	}

	render_extra() {
		const root = $(this.wrapper);
		root.find(".bb-extra").val(this.group_by);
		root.find(".bb-zoom").val(this.zoom);
		root.find(".bb-zoom-grp").prop("hidden", this.view !== "timeline");
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
				frappe.show_alert({ message: __("Could not move that item."), indicator: "red" });
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
					`<tr class="dpx-bb-ghd${shut ? " shut" : ""}"><td colspan="6">
						<button data-group="${esc(key)}"><i class="chev"></i>${esc(key)}
						<span class="n">${items.length}</span></button></td></tr>` +
					slice.map((item) => list_row(item)).join("")
				);
			})
			.join("");

		stage.html(`
			<div class="dpx-card"><div class="dpx-card-body dpx-bb-listwrap" style="padding:0 0 4px">
				<table class="dpx-bb-table">
					<colgroup><col><col style="width:128px"><col style="width:104px"><col class="opt" style="width:158px"><col class="opt" style="width:132px"><col style="width:104px"></colgroup>
					<thead><tr><th>Work item</th><th>Stage</th><th>Priority</th><th class="opt">Assigned to</th>
						<th class="opt">Module</th><th style="text-align:right">Due</th></tr></thead>
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
					.html('<div class="dpx-bb-sheet"><div class="host"></div></div>');
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
			item.assignees.join(", "),
			item.module || "",
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
				{ type: "text", title: "Work item", width: 372, ...locked },
				{ type: "dropdown", title: "Stage", width: 124, source: this.stages },
				{
					type: "dropdown",
					title: "Priority",
					width: 104,
					source: ["", "Low", "Medium", "High", "Urgent"],
				},
				{ type: "text", title: "Assignee", width: 142, ...locked },
				{ type: "dropdown", title: "Module", width: 130, source: this.modules },
				{ type: "calendar", title: "Due", width: 100, options: { format: "YYYY-MM-DD" } },
				{
					type: "calendar",
					title: "Start",
					width: 100,
					options: { format: "YYYY-MM-DD" },
				},
				{ type: "text", title: "Status", width: 104, ...locked },
				{ type: "text", title: "Project", width: 102, ...locked },
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
			updateTable: (_el, cell, x, y) => paint_cell(cell, Number(x), order[Number(y)]),
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

	watch_clicks(host) {
		host.addEventListener("click", (e) => {
			const td = e.target.closest("td[data-x]");
			if (!td || td.classList.contains("editor")) return;

			const x = Number(td.getAttribute("data-x"));
			const y = Number(td.getAttribute("data-y"));
			if (!SHEET_FIELDS[x]) return;

			const item = this.sheet_rows[y];
			if (!item || !item.movable) return;

			clearTimeout(this.opening);
			this.opening = setTimeout(() => {
				const cell = this.sheet.getCellFromCoords(x, y);
				if (cell && !cell.classList.contains("editor")) this.sheet.openEditor(cell);
			}, 0);
		});
	}

	guard_cell(y, value) {
		const item = this.sheet_rows[Number(y)];
		if (item && !item.movable) {
			frappe.show_alert({
				message: __("Requests move through their own workflow, not the board."),
				indicator: "orange",
			});
			return false;
		}
		return value;
	}

	sheet_changed(x, y, value) {
		const item = this.sheet_rows[y];
		if (!item || !item.movable) return;

		const field = SHEET_FIELDS[x];
		if (!field) return;

		const current = field === "stage" ? item.stage : item[field] || "";
		if (String(value || "") === String(current || "")) return;

		this.save_cell(item, field, value || "");
	}

	save_cell(item, field, value) {
		const previous = { ...item };
		if (field === "stage") item.stage = value;
		else item[field] = value;
		if (field === "priority") item.rank = RANK[value] || 0;

		const [method, args] =
			field === "stage"
				? ["set_stage", { doctype: item.doctype, name: item.name, stage: value }]
				: ["set_field", { doctype: item.doctype, name: item.name, field, value }];

		frappe
			.xcall(`upande_dev_tools.api.board.${method}`, args)
			.then(() => this.load())
			.catch(() => {
				Object.assign(item, previous);
				this.render();
				frappe.show_alert({ message: __("Could not save that cell."), indicator: "red" });
			});
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

		const months = [];
		const ticks = [];
		const rules = [];
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
			} else if (this.zoom === "days") {
				rules.push(`<div class="wk" style="left:${at}px"></div>`);
				ticks.push(
					`<div class="dpx-bb-tk${d.getUTCDay() % 6 === 0 ? " dim" : ""}" style="left:${
						at + day_w / 2
					}px">${DOW[d.getUTCDay()]}<b>${d.getUTCDate()}</b></div>`
				);
			} else if (d.getUTCDay() === 1) {
				rules.push(`<div class="wk" style="left:${at}px"></div>`);
				ticks.push(`<div class="dpx-bb-tk" style="left:${at}px">${d.getUTCDate()}</div>`);
			}
			if (d.getUTCDay() === 6)
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
			});
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

			const box = bar.getBoundingClientRect();
			const edge =
				e.clientX - box.left < 7 ? "start" : box.right - e.clientX < 7 ? "end" : "move";
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
				frappe.show_alert({
					message: __("{0} moved to {1}", [item.title, item.start]),
					indicator: "green",
				})
			)
			.catch(() => {
				Object.assign(item, before);
				this.moved = null;
				this.render();
				frappe.show_alert({ message: __("Could not move that work."), indicator: "red" });
			});
	}
};

function card(item) {
	const cls = ["dpx-bb-card"];
	if (!item.movable) cls.push("locked");
	return `
		<div class="${cls.join(" ")}" data-id="${esc(item.doctype)}:${esc(item.name)}"
			${item.movable ? 'draggable="true"' : ""}>
			<div class="hd">${pri(item)}<span class="dpx-bb-src">${SOURCES[item.doctype]}</span></div>
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
	return `
		<tr class="${cls.join(" ")}" data-id="${esc(item.doctype)}:${esc(item.name)}">
			<td><div class="subj">${pri(item)}<span class="dpx-bb-src">${SOURCES[item.doctype]}</span>
				<a href="${link(item)}">${esc(item.title)}</a></div></td>
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
		</tr>`;
}

function tl_row({ item, start, end }, x, width) {
	const left = x(start);
	const bar_w = Math.max(x(end) - left + 4, 6);
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
		<div class="dpx-bb-tl-row${done ? " done" : ""}">
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

function esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}
