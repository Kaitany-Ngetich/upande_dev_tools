window.upande_dev_tools = window.upande_dev_tools || {};

const DAY = 86400000;
const SOURCES = { Task: "TASK", Issue: "ISSUE", Request: "REQ" };
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const ZOOM = { weeks: 13, months: 4 };
const PAGE = 60;
const COLUMN_CAP = 25;
const SHEET_FIELDS = { 4: "stage", 5: "priority", 6: "start", 7: "end" };
const LIB = "/assets/upande_dev_tools/lib/jspreadsheet";
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
	refresh: '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
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
	cell.classList.toggle("bb-done", item.stage === "Done");
	if (x === 1) cell.classList.add("bb-mono");
	if (x === 2 || x === 6 || x === 7) cell.classList.add("bb-mono");
	if (x === 7 && item.late) cell.classList.add("bb-late");
	if (x >= 4 && x <= 7) cell.classList.add(item.movable ? "bb-pick" : "bb-locked");
}

function ico(name, size) {
	const s = size || 15;
	return `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="currentColor"
		stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ""}</svg>`;
}
const RANK = { Low: 1, Medium: 2, High: 3, Urgent: 4 };

upande_dev_tools.BacklogBoard = class BacklogBoard {
	constructor(wrapper, project) {
		this.wrapper = wrapper;
		this.project = project;
		this.items = [];
		this.stages = [];
		this.total = 0;
		this.view = "board";
		this.group_by = "stage";
		this.zoom = "weeks";
		this.shut = new Set();
		this.caps = {};
		this.limit = PAGE;
		this.filters = { q: "", source: "", assignee: "", priority: "", hide_done: false };
		this.render_shell();
		this.load();
	}

	load() {
		const args = this.project ? { project: this.project } : {};
		frappe
			.xcall("upande_dev_tools.api.board.get_board", args)
			.then((data) => {
				this.items = data.items;
				this.stages = data.stages;
				this.total = data.total;
				this.render();
			})
			.catch((e) => this.fail(e));
	}

	fail(e) {
		$(this.wrapper)
			.find(".bb-stage")
			.html(blank("Could not load the board", String(e && e.message ? e.message : e) || "Reload the page to try again."));
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
							<button class="dpx-bb-ico bb-reload" type="button" title="Refresh" aria-label="Refresh">${ico("refresh")}</button>
							<span class="dpx-bb-div"></span>
							<div class="dpx-bb-views" role="tablist">
								<button data-view="board" class="on" role="tab" title="Board">${ico("board", 13)}<span>Board</span></button>
								<button data-view="list" role="tab" title="List">${ico("list", 13)}<span>List</span></button>
								<button data-view="timeline" role="tab" title="Timeline">${ico("clock", 13)}<span>Timeline</span></button>
								<button data-view="sheet" role="tab" title="Sheet">${ico("table", 13)}<span>Sheet</span></button>
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
							<select class="dpx-bb-field" data-f="assignee" aria-label="Assignee"></select>
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
							<span class="dpx-bb-grp-lbl bb-extra-lbl">Group</span>
							<select class="dpx-bb-field bb-extra" aria-label="Group by"></select>
						</div>
						<span class="dpx-bb-hint"></span>
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
			const value = $(e.currentTarget).val();
			if (this.view === "timeline") this.zoom = value;
			else this.group_by = value;
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
	}

	visible() {
		const q = (this.filters.q || "").toLowerCase();
		return this.items.filter((item) => {
			if (this.filters.source && item.doctype !== this.filters.source) return false;
			if (this.filters.priority && item.priority !== this.filters.priority) return false;
			if (this.filters.assignee) {
				if (this.filters.assignee === "__none") {
					if (item.assignees.length) return false;
				} else if (!item.assignees.includes(this.filters.assignee)) return false;
			}
			if (q && !item.title.toLowerCase().includes(q) && !item.name.toLowerCase().includes(q))
				return false;
			return true;
		});
	}

	render() {
		const rows = this.visible();
		this.render_assignees();
		this.render_extra();
		this.render_count(rows);

		const stage = $(this.wrapper).find(".bb-stage");
		if (this.view === "board") this.render_board(stage, rows);
		else if (this.view === "list") this.render_list(stage, rows);
		else if (this.view === "sheet") this.render_sheet(stage, rows);
		else this.render_timeline(stage, rows);
	}

	render_assignees() {
		const select = $(this.wrapper).find('[data-f="assignee"]');
		if (select.children().length) return;
		const people = [...new Set(this.items.flatMap((item) => item.assignees))].sort();
		select.html(
			['<option value="">Anyone</option>', '<option value="__none">Unassigned</option>']
				.concat(people.map((p) => `<option value="${esc(p)}">${esc(p)}</option>`))
				.join("")
		);
	}

	render_extra() {
		const select = $(this.wrapper).find(".bb-extra");
		$(this.wrapper)
			.find(".bb-extra-lbl")
			.text(this.view === "timeline" ? "Zoom" : "Group");
		if (this.view === "timeline") {
			select.html(
				`<option value="weeks">Weeks</option><option value="months">Months</option>`
			).val(this.zoom);
		} else {
			select.html(
				`<option value="stage">Group by stage</option>
				 <option value="assignee">Group by assignee</option>
				 <option value="priority">Group by priority</option>
				 <option value="project">Group by project</option>`
			).val(this.group_by);
		}
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
		$(this.wrapper).find(".dpx-bb-hint").text(HINTS[this.view] || "");
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
		const keys = new Set();
		rows.forEach((item) => {
			if (this.group_by === "assignee") {
				item.assignees.length ? item.assignees.forEach((a) => keys.add(a)) : keys.add("Unassigned");
			} else {
				keys.add(item.project || "No project");
			}
		});
		return [...keys].sort().map((key) => [
			key,
			rows.filter((item) =>
				this.group_by === "assignee"
					? key === "Unassigned"
						? !item.assignees.length
						: item.assignees.includes(key)
					: (item.project || "No project") === key
			),
		]);
	}

	render_board(stage, rows) {
		if (!rows.length) return stage.html(blank("Nothing here yet", empty_hint(this.filters)));

		const groups = this.group(rows);
		stage.html(`<div class="dpx-bb-cols">${groups
			.map(([key, items]) => {
				const cap = this.caps[key] || COLUMN_CAP;
				const shown = items.slice(0, cap);
				return `
			<div class="dpx-bb-col">
				<div class="dpx-bb-col-hd"><span>${esc(key)}</span><span class="n">${items.length}</span></div>
				<div class="dpx-bb-drop" data-stage="${esc(key)}">
					${items.length
						? shown.map((item) => card(item)).join("")
						: '<div class="dpx-bb-col-blank">Nothing in this stage</div>'}
					${items.length > shown.length
						? `<button class="dpx-bb-colmore" data-col="${esc(key)}">${items.length - shown.length} more</button>`
						: ""}
				</div>
			</div>`;
			})
			.join("")}</div>`);

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
					<colgroup><col><col style="width:116px"><col class="opt" style="width:96px"><col class="opt" style="width:150px"><col style="width:96px"></colgroup>
					<thead><tr><th>Work item</th><th>Stage</th><th class="opt">Priority</th><th class="opt">Assigned to</th><th style="text-align:right">Due</th></tr></thead>
					<tbody>${body}</tbody>
				</table>
				${shown < rows.length ? `<button class="dpx-bb-more">Show more — ${rows.length - shown} remaining</button>` : ""}
			</div></div>
		`);
	}

	render_sheet(stage, rows) {
		if (!rows.length) return stage.html(blank("Nothing here yet", empty_hint(this.filters)));

		stage.html('<div class="dpx-bb-sheet"><div class="host"></div></div>');
		const host = stage.find(".host")[0];

		load_jspreadsheet()
			.then(() => this.mount_sheet(host, rows))
			.catch(() => stage.html(blank("Sheet could not load", "The spreadsheet library did not load. Reload the page, or use the List view.")));
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
		const data = order.map((item) => [
			`${item.doctype}:${item.name}`,
			SOURCES[item.doctype],
			item.name,
			item.title,
			item.stage,
			item.priority || "",
			item.start || "",
			item.end || "",
			item.assignees.join(", "),
			item.project || "",
			item.status,
			item.late ? "Late" : "",
		]);

		const locked = { readOnly: true };
		this.sheet = jspreadsheet(host, {
			data,
			columns: [
				{ type: "hidden", title: "id" },
				{ type: "text", title: "Type", width: 62, ...locked },
				{ type: "text", title: "ID", width: 132, ...locked },
				{ type: "text", title: "Work item", width: 320, ...locked },
				{ type: "dropdown", title: "Stage", width: 118, source: this.stages },
				{ type: "dropdown", title: "Priority", width: 96, source: ["", "Low", "Medium", "High", "Urgent"] },
				{ type: "calendar", title: "Start", width: 104, options: { format: "YYYY-MM-DD" } },
				{ type: "calendar", title: "Due", width: 104, options: { format: "YYYY-MM-DD" } },
				{ type: "text", title: "Assigned to", width: 170, ...locked },
				{ type: "text", title: "Project", width: 130, ...locked },
				{ type: "text", title: "Status", width: 118, ...locked },
				{ type: "text", title: "Flag", width: 64, ...locked },
			],
			columnSorting: true,
			columnDrag: false,
			tableOverflow: true,
			tableHeight: "calc(100vh - 292px)",
			tableWidth: "100%",
			lazyLoading: true,
			loadingSpin: true,
			freezeColumns: 4,
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
		this.watch_clicks(host);
	}

	// Google Sheets opens a picker on one click; jspreadsheet waits for a second.
	// This has to run after the click has finished bubbling to document - jsuites
	// closes an open dropdown from its own document handler, so opening any earlier
	// (on selection, which fires at mousedown) opens and shuts it in one gesture.
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
					"Tasks show here once they have a planned or due date, and issues once they have a resolution date. Set one on a work item and it lands on this timeline."
				)
			);
		}

		const day_w = ZOOM[this.zoom];
		const spans = dated.map((item) => {
			const start = date_of(item.start || item.end);
			const end = date_of(item.end || item.start);
			return { item, start, end: end < start ? start : end };
		});
		spans.sort((a, b) => a.start - b.start);

		const first = new Date(Math.min(...spans.map((s) => s.start)) - 3 * DAY);
		const last = new Date(Math.max(...spans.map((s) => s.end)) + 4 * DAY);
		const days = Math.round((last - first) / DAY);
		const width = days * day_w;
		const x = (d) => Math.round(((d - first) / DAY) * day_w);

		const ticks = [];
		const rules = [];
		const months = [];
		for (let i = 0; i <= days; i++) {
			const d = new Date(first.getTime() + i * DAY);
			if (d.getUTCDate() === 1) {
				months.push(
					`<div class="dpx-bb-mo" style="left:${i * day_w}px">${MONTHS[d.getUTCMonth()]} ${String(
						d.getUTCFullYear()
					).slice(2)}</div>`
				);
				rules.push(`<div class="mo" style="left:${i * day_w}px"></div>`);
			} else if (d.getUTCDay() === 1) {
				rules.push(`<div class="wk" style="left:${i * day_w}px"></div>`);
				if (day_w >= 9)
					ticks.push(`<div class="dpx-bb-tk" style="left:${i * day_w}px">${d.getUTCDate()}</div>`);
			}
		}

		const now = date_of(today());
		const today_line =
			now >= first && now <= last
				? `<div class="dpx-bb-today" style="left:${x(now)}px"></div>`
				: "";

		stage.html(`
			<div class="dpx-bb-tl"><div class="dpx-bb-tl-scroll"><div class="dpx-bb-tl-inner">
				<div class="dpx-bb-tl-hd">
					<div class="corner">${spans.length} scheduled</div>
					<div class="band" style="width:${width}px">${months.join("")}${ticks.join("")}</div>
				</div>
				<div class="dpx-bb-tl-body">
					<div class="dpx-bb-grid" style="width:${width}px">${rules.join("")}${today_line}</div>
					${spans.map((span) => tl_row(span, x, width)).join("")}
				</div>
			</div></div>
			<div class="dpx-bb-legend">
				<span><i></i>In flight</span>
				<span><i class="done"></i>Done</span>
				<span><i class="late"></i>Past due</span>
				<span><i class="today"></i>Today</span>
			</div></div>
		`);
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
		<tr class="${cls.join(" ")}">
			<td><div class="subj">${pri(item)}<span class="dpx-bb-src">${SOURCES[item.doctype]}</span>
				<a href="${link(item)}">${esc(item.title)}</a></div></td>
			<td><span class="dpx-bb-dot st-${slug(item.stage)}"></span>${esc(item.stage)}</td>
			<td class="opt">${esc(item.priority || "—")}</td>
			<td class="opt">${people(item)}</td>
			<td class="num${item.late ? " late" : ""}">${esc(item.end || "—")}</td>
		</tr>`;
}

function tl_row({ item, start, end }, x, width) {
	const left = x(start);
	const bar_w = Math.max(x(end) - left + 4, 5);
	const done = item.stage === "Done";
	const cls = done ? "done" : item.late ? "late" : "";
	const label = start.getTime() === end.getTime() ? fmt(start) : `${fmt(start)} → ${fmt(end)}`;
	return `
		<div class="dpx-bb-tl-row${done ? " done" : ""}">
			<div class="name"><span class="dpx-bb-src">${SOURCES[item.doctype]}</span>
				<a href="${link(item)}" title="${esc(item.title)}">${esc(item.title)}</a></div>
			<div class="track" style="width:${width}px">
				<div class="dpx-bb-tlbar ${cls}" style="left:${left}px;width:${bar_w}px"
					title="${esc(item.title)} · ${label}"></div>
				<div class="dpx-bb-span" style="left:${left + bar_w}px">${label}</div>
			</div>
		</div>`;
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
