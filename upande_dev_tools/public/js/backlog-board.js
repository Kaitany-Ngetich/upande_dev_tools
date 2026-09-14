window.upande_dev_tools = window.upande_dev_tools || {};

const DAY = 86400000;
const SOURCES = { Task: "TASK", Issue: "ISSUE", Request: "REQ" };
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const ZOOM = { weeks: 13, months: 4 };
const PAGE = 60;

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
		this.limit = PAGE;
		this.filters = { q: "", source: "", assignee: "", priority: "", hide_done: false };
		this.render_shell();
		this.load();
	}

	load() {
		const args = this.project ? { project: this.project } : {};
		frappe.call({ method: "upande_dev_tools.api.board.get_board", args }).then((r) => {
			const data = r.message || { items: [], stages: [], total: 0 };
			this.items = data.items;
			this.stages = data.stages;
			this.total = data.total;
			this.render();
		});
	}

	render_shell() {
		$(this.wrapper).html(`
			<div class="dpx-board">
				<div class="dpx-bb-bar">
					<div class="dpx-bb-views">
						<button data-view="board" class="on">Board</button>
						<button data-view="list">List</button>
						<button data-view="timeline">Timeline</button>
					</div>
					<input type="search" class="dpx-bb-field dpx-bb-search" data-f="q"
						placeholder="Search work items" aria-label="Search work items">
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
					<select class="dpx-bb-field bb-extra" aria-label="Group by"></select>
					<span class="sp"></span>
					<span class="dpx-bb-count"></span>
				</div>
				<div class="bb-stage"></div>
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
		root.on("input change", "[data-f]", (e) => {
			const el = $(e.currentTarget);
			this.filters[el.data("f")] = el.val();
			this.limit = PAGE;
			this.render();
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
		const parts = [`<b>${rows.length}</b> items`, `${rows.length - done} open`];
		if (late) parts.push(`<span class="late">${late} late</span>`);
		if (this.total > this.items.length)
			parts.push(`${this.items.length} of ${this.total} loaded`);
		$(this.wrapper).find(".dpx-bb-count").html(parts.join(" · "));
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
			.map(
				([key, items]) => `
			<div class="dpx-bb-col">
				<div class="dpx-bb-col-hd"><span>${esc(key)}</span><span class="n">${items.length}</span></div>
				<div class="dpx-bb-drop" data-stage="${esc(key)}">
					${items.length
						? items.map((item) => card(item)).join("")
						: '<div class="dpx-bb-col-blank">Nothing in this stage</div>'}
				</div>
			</div>`
			)
			.join("")}</div>`);

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
			.call({
				method: "upande_dev_tools.api.board.set_stage",
				args: { doctype: item.doctype, name: item.name, stage },
			})
			.then((r) => {
				item.status = r.message.status;
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
	const cls = [`dpx-bb-card p${item.rank - 1}`];
	if (!item.movable) cls.push("locked");
	return `
		<div class="${cls.join(" ")}" data-id="${esc(item.doctype)}:${esc(item.name)}"
			${item.movable ? 'draggable="true"' : ""}>
			<span class="dpx-bb-src">${SOURCES[item.doctype]}</span>
			<div class="t">${esc(item.title)}</div>
			<div class="m">
				${people(item)}
				${item.end ? `<span class="d${item.late ? " late" : ""}">${esc(item.end)}</span>` : ""}
			</div>
		</div>`;
}

function list_row(item) {
	const cls = [`dpx-bb-row p${item.rank - 1}`];
	if (item.stage === "Done") cls.push("done");
	return `
		<tr class="${cls.join(" ")}">
			<td><div class="subj"><span class="dpx-bb-src">${SOURCES[item.doctype]}</span>
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
				<div class="dpx-bb-bar ${cls}" style="left:${left}px;width:${bar_w}px"
					title="${esc(item.title)} · ${label}"></div>
				<div class="dpx-bb-span" style="left:${left + bar_w}px">${label}</div>
			</div>
		</div>`;
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
