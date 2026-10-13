/* Backlog Board v2 - the complete board: Board, List, Timeline and Sheet views over Tasks, Issues
 * and Requests, with drag-and-drop, create, edit, reassign, delete and bulk edit.
 *
 * READS  api.v2.backlog_board (server-side filtering, KPIs, history).
 * WRITES the same whitelisted endpoints the current page calls (api.board.*, api.requests.*), so
 *        permission checks, validation, audit trail and notifications are unchanged. The role flags
 *        read from #bb2 only decide which controls are shown; the endpoints re-check every call.
 * Pure helpers (dates, grouping, payload building) are exported on window.BB2_HELPERS for tests.
 */
(function () {
	"use strict";

	/* ── configuration ─────────────────────────────────────────────── */
	const API = "upande_dev_tools.api.v2.backlog_board.";
	const BOARD = "upande_dev_tools.api.board.";
	const REQ = "upande_dev_tools.api.requests.";
	const MASTER = "upande_dev_tools.api.master_data.get_master_data";

	const NONE = "__none__";
	const DAY = 86400000;
	/** Stages board.set_stage accepts. "Dropped" is a result (cancelled / rejected), not a place to move work to. */
	const STAGES = ["Triage", "Todo", "In Progress", "In Review", "Blocked", "Done"];
	const DROPPED = "Dropped";
	const TASK_STATUSES = ["Open", "Working", "Pending Review", "Overdue", "Completed", "Cancelled"];
	const SOURCE = { Task: "TASK", Issue: "ISSUE", Request: "REQ" };
	const VIEWS = ["board", "list", "timeline", "sheet"];
	const VIEW_KEYS = { 1: "board", 2: "list", 3: "timeline", 4: "sheet" };
	const COLUMN_CAP = 25;
	const LIST_PAGE = 60;
	const SHEET_PAGE = 150;
	const BULK_LIMIT = 200; // board.BULK_LIMIT
	const PREVIEW_HOLD = 420;
	const FLUSH_MS = 140;
	const PREFS_KEY = "dpx-backlog-v2";
	/** Ctrl+wheel walks this ladder a rung at a time; w is the width of one day in px. */
	const ZOOMS = [
		{ key: "closeup", label: "Close-up", w: 110 },
		{ key: "days", label: "Days", w: 34 },
		{ key: "wide", label: "Wide weeks", w: 22 },
		{ key: "weeks", label: "Weeks", w: 15 },
		{ key: "fortnights", label: "Fortnights", w: 9 },
		{ key: "months", label: "Months", w: 5 },
		{ key: "quarters", label: "Quarters", w: 3 },
	];
	const ZOOM_W = Object.fromEntries(ZOOMS.map((z) => [z.key, z.w]));
	const ZOOM_COARSE_FIRST = ZOOMS.map((z) => z.key).reverse();
	const MIN_BAR = 14;
	const EDGE_BAR = 30; // narrower bars cannot hold two edge handles: the whole bar moves
	const EDGE = 7;
	const WHEEL_STEP = 40;
	const GUTTER = 260;
	const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
	const MONTHS_LONG = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
	const DOW = ["S", "M", "T", "W", "T", "F", "S"];
	const FILTERS = [
		["project", "#f-project"], ["kind", "#f-kind"], ["stage", "#f-stage"], ["priority", "#f-priority"],
		["module", "#f-module"], ["assignee", "#f-assignee"], ["tag", "#f-tag"], ["due", "#f-due"],
	];
	const FILTER_KEYS = [...FILTERS.map((f) => f[0]), "q", "from", "to", "linked"];

	const $ = PH.$;
	const esc = PH.esc;
	const n = PH.fmt.num;

	/* ── pure helpers ──────────────────────────────────────────────── */
	const slug = (s) => String(s || "").toLowerCase().replace(/\s+/g, "-");
	const initials = (name) => String(name || "").split(/\s+/).slice(0, 2).map((p) => p[0] || "").join("").toUpperCase();
	const dateOf = (v) => {
		const [y, m, d] = String(v).split("-").map(Number);
		return new Date(Date.UTC(y, m - 1, d));
	};
	const iso = (d) => d.toISOString().slice(0, 10);
	const addDays = (d, k) => new Date(d.getTime() + k * DAY);
	const weekStart = (d) => addDays(d, -((d.getUTCDay() + 6) % 7));
	const dayDiff = (a, b) => Math.round((b - a) / DAY);
	const short = (d) => `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`;
	const docUrl = (kind, name) => "/app/" + slug(kind) + "/" + encodeURIComponent(name);
	const csvList = (arr) => (arr || []).join(",");

	/** Priority dot colour class from the level's name (levels are master data, so unknown names stay neutral). */
	const prioClass = (p) => ({ Low: "is-low", Medium: "is-medium", High: "is-high", Urgent: "is-urgent", Critical: "is-urgent" }[p] || "");

	/** The date span an item occupies on the timeline: start..due, either one standing in for a missing other. */
	function spanOf(item) {
		if (!item.start && !item.due) return null;
		const start = dateOf(item.start || item.due);
		const end = dateOf(item.due || item.start);
		return { item, start, end: end < start ? start : end };
	}

	/** New start/end after dragging a bar `shift` days. mode: "move" | "start" | "end". Never lets the ends cross. */
	function shiftedSpan(start, end, mode, shift) {
		const length = dayDiff(start, end);
		if (mode === "move") return { start: addDays(start, shift), end: addDays(end, shift) };
		if (mode === "start") return { start: addDays(start, Math.min(shift, length)), end };
		return { start, end: addDays(end, Math.max(shift, -length)) };
	}

	/** Which part of a bar a pointer grabbed. */
	function grabMode(offsetX, width) {
		if (width < EDGE_BAR) return "move";
		if (offsetX < EDGE) return "start";
		if (width - offsetX < EDGE) return "end";
		return "move";
	}

	/** update_work payload (only what changed) for an edit dialog. Unchanged fields are left out, so
	 * saving a dialog never rewrites a status it did not touch (e.g. a Cancelled task shown as Done). */
	function changedFields(before, after) {
		const out = {};
		Object.keys(after).forEach((k) => {
			if (String(after[k] == null ? "" : after[k]) !== String(before[k] == null ? "" : before[k])) out[k] = after[k];
		});
		return out;
	}

	/** A Text Editor description can carry images or tables; only plain ones are safe to edit as text. */
	function plainDescription(html) {
		if (!html) return { text: "", rich: false };
		const rich = /<(?!\/?(p|br|div|b|i|em|strong|span)\b)[a-z]/i.test(html);
		const text = String(html)
			.replace(/<\/(p|div)>/gi, "\n").replace(/<br\s*\/?>/gi, "\n").replace(/<[^>]*>/g, "")
			.replace(/&nbsp;/gi, " ").replace(/&amp;/gi, "&").replace(/&lt;/gi, "<").replace(/&gt;/gi, ">").trim();
		return { text, rich };
	}
	const richDescription = (text) => {
		const body = String(text || "").trim();
		return body ? esc(body).replace(/\n/g, "<br>") : "";
	};

	/** Splits rows into [{key, label, items}] by stage, priority, assignee, module or project. */
	function groupItems(items, by, ctx) {
		if (by === "stage") {
			const stages = ctx.stages.filter((s) => s.stage !== DROPPED || s.count > 0 || items.some((i) => i.stage === DROPPED));
			return stages.map((s) => ({ key: s.stage, label: s.stage, count: s.count, late: s.late, items: items.filter((i) => i.stage === s.stage) }));
		}
		if (by === "priority") {
			const keys = [...ctx.priorities, ""];
			return keys.map((k) => ({ key: k, label: k || "No priority", items: items.filter((i) => (i.priority || "") === k) }));
		}
		const blank = { assignee: "Unassigned", module: "No product area", project: "No project" }[by];
		const keyOf = (i) => (by === "assignee" ? (i.assignee_ids.length ? i.assignee_ids : [""]) : [i[by] || ""]);
		const labelOf = (k) => (!k ? blank : by === "assignee" ? ctx.people[k] || k : by === "project" ? ctx.projects[k] || k : k);
		const map = new Map();
		items.forEach((i) => keyOf(i).forEach((k) => (map.has(k) ? map.get(k).push(i) : map.set(k, [i]))));
		return [...map.entries()]
			.map(([key, list]) => ({ key, label: labelOf(key), items: list }))
			.sort((a, b) => (!a.key ? 1 : !b.key ? -1 : a.label.localeCompare(b.label)));
	}

	window.BB2_HELPERS = { spanOf, shiftedSpan, grabMode, changedFields, plainDescription, richDescription, groupItems, dateOf, iso, weekStart };

	/* ── page configuration (role flags; the endpoints re-check every call) ── */
	const root = document.getElementById("bb2");
	if (!root) return;
	const CFG = {
		boardRole: root.dataset.boardRole === "1",
		canCreate: root.dataset.canCreate === "1",
		manager: root.dataset.manager === "1",
		user: root.dataset.user,
	};

	/* ── preferences (view, grouping, zoom, collapsed groups) ──────── */
	const prefs = (() => {
		try {
			return JSON.parse(localStorage.getItem(PREFS_KEY) || "{}") || {};
		} catch (e) {
			return {};
		}
	})();
	const shut = new Set(prefs.shut || []);
	let tlScroll = prefs.tlScroll || null;
	function savePrefs() {
		try {
			const s = st.get();
			localStorage.setItem(PREFS_KEY, JSON.stringify({ view: s.view, group: s.group, zoom: s.zoom, shut: [...shut], tlScroll }));
		} catch (e) {
			// private mode: preferences simply do not persist
		}
	}

	/* ── state ─────────────────────────────────────────────────────── */
	const st = PH.state({
		view: VIEWS.includes(prefs.view) ? prefs.view : "board",
		group: ["stage", "assignee", "module", "priority", "project"].includes(prefs.group) ? prefs.group : "stage",
		zoom: ZOOM_W[prefs.zoom] ? prefs.zoom : "weeks",
		project: "", kind: "", stage: "", priority: "", module: "", assignee: "", tag: "", due: "", from: "", to: "", q: "", linked: "",
	});
	let data = null; // last get_backlog payload
	let seq = 0;
	let listsPromise = null; // people, work tags, modules, active priority levels (lazy)
	/** The loaded lists; empty until loadLists() resolves (it is started at boot). */
	let lists = { people: [], tags: [], modules: [], priorities: [] };
	const caps = {}; // "Show more" counts per board column
	let listLimit = LIST_PAGE;
	let sheetLimit = SHEET_PAGE;
	let justMoved = null;
	const selected = new Set(); // sheet row selection, "Kind:NAME"
	let sheetSort = null;
	let lastPicked = -1;
	const pending = new Map(); // sheet edits waiting for the batch flush
	let flushTimer = null;
	let saveStatus = null; // {state, count} shown in the sheet bar

	const keyOf = (i) => `${i.kind}:${i.name}`;
	const find = (key) => (data ? data.items.find((i) => keyOf(i) === key) : null);
	const canMove = (i) => CFG.boardRole && i.kind !== "Request";
	const canReassign = (i) => CFG.boardRole && i.kind === "Task";
	/** Mirrors board.delete_task / requests.delete_request, which re-check on the server. */
	function canDelete(i) {
		if (!CFG.boardRole) return false;
		if (i.kind === "Task") return CFG.manager || i.assignee_ids.includes(CFG.user);
		if (i.kind === "Request") return CFG.manager || (i.own && i.status === "Under Review");
		return false;
	}
	const ctx = () => ({
		stages: data.stages,
		priorities: data.options.priorities,
		people: Object.fromEntries(data.options.assignees.map((a) => [a.value, a.label])),
		projects: Object.fromEntries(data.options.projects.map((p) => [p.name, p.project_name || p.name])),
	});

	/* ── server calls ──────────────────────────────────────────────── */
	/** A write: errors reject with the server's message (shown by the caller, not toasted twice). */
	const write = (method, args) => PH.call(method, args, { silent: true });

	function loadLists() {
		if (!listsPromise) {
			const safe = (p) => p.catch(() => []);
			listsPromise = Promise.all([
				safe(PH.call(REQ + "get_assignable_users", {}, { silent: true })),
				safe(PH.call(BOARD + "get_work_tags", {}, { silent: true })),
				safe(PH.call(BOARD + "get_modules", {}, { silent: true })),
				safe(PH.call(MASTER, { key: "priority_level" }, { silent: true })),
			]).then(([people, tags, modules, levels]) => ({
				people: people || [],
				tags: tags || [],
				modules: modules || [],
				priorities: (levels || []).filter((p) => !p.disabled).map((p) => p.name),
			}));
		}
		return listsPromise.then((l) => (lists = l));
	}

	function args() {
		const s = st.get();
		return { project: s.project, kind: s.kind, stage: s.stage, priority: s.priority, module: s.module, assignee: s.assignee, tag: s.tag, q: s.q, due: s.due, from_date: s.from, to_date: s.to, include_linked: s.linked };
	}

	function load(opts) {
		const quiet = opts && opts.quiet && data;
		const my = ++seq;
		if (!quiet) {
			PH.loadingKpis("#kpis", true);
			skeleton();
		}
		return PH.call(API + "get_backlog", args(), { silent: true })
			.then((d) => {
				if (my !== seq) return;
				data = d;
				render();
				PH.markUpdated();
			})
			.catch((e) => {
				if (my !== seq) return;
				if (quiet) return PH.toast(e.message, "bad");
				data = null;
				PH.loadingKpis("#kpis", false);
				PH.error("#stage", e.message, () => load());
				$("#export").disabled = true;
			});
	}

	function skeleton() {
		const view = st.get("view");
		if (view === "board") {
			PH.set("#stage", `<div class="bb2-cols">${[3, 2, 2, 1, 1, 1].map((k) => `<div class="bb2-col"><span class="ph-sk" style="height:14px;width:50%"></span>${'<span class="ph-sk" style="height:84px;width:100%"></span>'.repeat(k)}</div>`).join("")}</div>`);
		} else {
			PH.skeleton("#stage", "rows", 8);
		}
	}

	/* ── filter bar ────────────────────────────────────────────────── */
	FILTERS.forEach(([k, sel]) => PH.bindSelect(sel, st, k));
	PH.bindSearch("#f-q", st, "q");
	PH.bindSelect("#f-from", st, "from");
	PH.bindSelect("#f-to", st, "to");
	PH.set("#s-ic", PH.icon("search"));
	const linkedBox = $("#f-linked");
	linkedBox.checked = st.get("linked") === "1";
	linkedBox.addEventListener("change", () => st.set({ linked: linkedBox.checked ? "1" : "" }));
	PH.options("#f-zoom", ZOOMS.map((z) => ({ value: z.key, label: z.label })), st.get("zoom"));
	PH.bindSelect("#f-group", st, "group");
	PH.bindSelect("#f-zoom", st, "zoom");
	$("#tabs").addEventListener("click", (e) => {
		const b = e.target.closest("[data-view]");
		if (b) st.set({ view: b.dataset.view });
	});
	$("#f-toggle").addEventListener("click", () => {
		const open = $("#filters").classList.toggle("is-open");
		$("#f-toggle").setAttribute("aria-expanded", String(open));
	});
	$("#f-clear").addEventListener("click", () => {
		linkedBox.checked = false;
		st.set(Object.fromEntries(FILTER_KEYS.map((k) => [k, ""])));
		$("#f-q").value = "";
	});

	const SERVER_KEYS = new Set(FILTER_KEYS);
	st.on((s, changed) => {
		savePrefs();
		paintChrome();
		if (changed.some((k) => SERVER_KEYS.has(k))) {
			Object.keys(caps).forEach((k) => delete caps[k]);
			listLimit = LIST_PAGE;
			sheetLimit = SHEET_PAGE;
			selected.clear();
			load();
		} else if (data) {
			drawView();
		}
	});

	function fillOptions(d, s) {
		const o = d.options;
		const keep = (arr, cur) => (cur && cur !== NONE && !arr.some((x) => x.value === cur) ? arr.concat([{ value: cur, label: cur }]) : arr);
		if (o.projects.length) {
			$("#f-project").hidden = false;
			PH.options("#f-project", keep(o.projects.map((p) => ({ value: p.name, label: p.project_name || p.name })), s.project), s.project);
		}
		PH.options("#f-priority", [...o.priorities.map((p) => ({ value: p, label: p })), { value: NONE, label: "No priority set" }], s.priority);
		PH.options("#f-module", keep([...o.areas.map((a) => ({ value: a.value, label: `${a.value} (${a.count})` })), { value: NONE, label: "No product area" }], s.module), s.module);
		PH.options("#f-assignee", keep([{ value: NONE, label: "Unassigned" }, ...o.assignees.map((a) => ({ value: a.value, label: `${a.label} (${a.count})` }))], s.assignee), s.assignee);
		PH.options("#f-tag", keep(o.tags.map((t) => ({ value: t.value, label: `${t.value} (${t.count})` })), s.tag), s.tag);
	}

	/** Tabs, zoom/group controls and the clear-filters button: everything that does not need data. */
	function paintChrome() {
		const s = st.get();
		PH.$$("#tabs .ph-tab").forEach((b) => b.classList.toggle("is-on", b.dataset.view === s.view));
		$("#zoom-wrap").hidden = s.view !== "timeline";
		const active = FILTER_KEYS.filter((k) => s[k]).length;
		const clear = $("#f-clear");
		clear.hidden = !active;
		clear.textContent = active === 1 ? "Clear filter" : `Clear ${active} filters`;
		$("#f-toggle").textContent = active ? `Filters (${active})` : "Filters";
		paintTools();
	}

	/* ── page chrome: KPIs, notes, header ──────────────────────────── */
	PH.kpiSkeleton("#kpis", ["Items", "Open work", "Overdue", "Unassigned", "Done"]);
	$("#new").textContent = CFG.canCreate ? "New task" : "Add to backlog";
	$("#new").addEventListener("click", () => openNew());

	function render() {
		const d = data, s = st.get(), k = d.kpis;
		fillOptions(d, s);
		const label = (sel, v) => {
			const o = $(sel);
			const x = o && Array.from(o.options).find((q) => q.value === v);
			return x ? x.textContent.replace(/ \(\d+\)$/, "") : v;
		};
		const scope = FILTERS.filter(([key]) => s[key]).map(([key, sel]) => label(sel, s[key]));
		if (s.q) scope.push("“" + s.q + "”");
		if (s.from || s.to) scope.push("due " + (s.from ? PH.fmt.date(s.from) : "…") + " to " + (s.to ? PH.fmt.date(s.to) : "…"));
		PH.text("#sub", `${PH.fmt.plural(k.total, "item")} · ${n(k.open)} open${k.overdue ? " · " + n(k.overdue) + " overdue" : ""} · as of ${PH.fmt.date(d.today)}${scope.length ? " · " + scope.join(" · ") : ""}`);

		PH.kpis("#kpis", [
			{ label: "Items", value: k.total, unit: [["task", d.kinds.Task], ["issue", d.kinds.Issue], ["request", d.kinds.Request]].filter((x) => x[1]).map((x) => PH.fmt.plural(x[1], x[0])).join(" · ") || "nothing yet", dark: true, title: "Every matching task, issue and request. A request that became a task is counted once, as the task." },
			{ label: "Open work", value: k.open, unit: "not done yet", onClick: () => st.set({ stage: "open" }), active: s.stage === "open" },
			{ label: "Overdue", value: k.overdue, unit: "late and still open", onClick: () => st.set({ due: "overdue" }), active: s.due === "overdue", title: "Has a due date earlier than today and is not Done or Dropped. Requests have no due date." },
			{ label: "Unassigned", value: k.unassigned_open, unit: "open, nobody on it", onClick: () => st.set({ assignee: NONE }), active: s.assignee === NONE },
			{ label: "Done", value: k.done, unit: k.dropped ? n(k.dropped) + " dropped (cancelled, rejected, withdrawn)" : "completed or closed", onClick: () => st.set({ stage: "Done" }), active: s.stage === "Done" },
		]);

		const nt = d.notes, notes = [];
		if (nt.folded_requests > 0) notes.push(`${PH.fmt.plural(nt.folded_requests, "request")} already became tasks and ${nt.folded_requests === 1 ? "is" : "are"} counted once, as the task. <a class="ph-link" href="#" data-linked>Show both</a>`);
		if (nt.no_project_requests > 0 && !s.project) notes.push(`${PH.fmt.plural(nt.no_project_requests, "request")} ${nt.no_project_requests === 1 ? "has" : "have"} no project yet, so ${nt.no_project_requests === 1 ? "it is" : "they are"} not on the board.`);
		if ((nt.unmapped || []).length) notes.push("Some statuses are not mapped to a stage and sit in the first column: " + nt.unmapped.map((u) => `${esc(u.kind)} “${esc(u.status)}” (${u.count})`).join(", ") + ".");
		if (d.truncated) notes.push(`Showing the first ${n(d.row_limit)} of ${n(k.total)} items. The numbers above cover all of them; narrow the filters to see the rest.`);
		if ((s.due || s.from || s.to) && d.kinds.Request === 0 && s.kind !== "Task") notes.push("Requests have no due date, so they are left out while a due-date filter is on.");
		PH.set("#notes", notes.map((t) => `<div class="ph-notice ph-notice--signal ph-mb-0">${t}</div>`).join(""));

		$("#export").disabled = !d.items.length;
		paintChrome();
		drawView();
	}
	$("#notes").addEventListener("click", (e) => {
		if (!e.target.closest("[data-linked]")) return;
		e.preventDefault();
		linkedBox.checked = true;
		st.set({ linked: "1" });
	});

	function exportCsv() {
		if (!data || !data.items.length) return;
		const rows = data.items.map((r) => ({ ...r, assignees: r.assignees.join("; "), tags: (r.tags || []).join("; "), late: r.late ? "Yes" : "No" }));
		PH.csv("backlog_board_" + data.today + ".csv", rows, [
			["name", "ID"], ["title", "Title"], ["kind", "Type"], ["stage", "Stage"], ["status", "Status"], ["priority", "Priority"], ["module", "Product area"],
			["project", "Project"], ["assignees", "Assignee"], ["start", "Start"], ["due", "Due"], ["late", "Overdue"], ["tags", "Tags"], ["linked", "Linked request/task"],
		].map(([key, label]) => ({ key, label })));
		PH.toast(`Exported ${PH.fmt.plural(rows.length, "row")}.`, "good");
	}
	$("#export").addEventListener("click", exportCsv);

	/* ── view toolbar ──────────────────────────────────────────────── */
	function paintTools() {
		const s = st.get();
		const hideOpen = s.stage === "open";
		const tools = {
			board: `<button class="ph-btn ph-btn--ghost ph-btn--sm${hideOpen ? " is-on" : ""}" data-tool="done" type="button">${hideOpen ? "Show done" : "Hide done"}</button>`,
			list: '<button class="ph-btn ph-btn--ghost ph-btn--sm" data-tool="collapse" type="button">Collapse all</button><button class="ph-btn ph-btn--ghost ph-btn--sm" data-tool="expand" type="button">Expand all</button>',
			timeline: '<button class="ph-btn ph-btn--ghost ph-btn--sm" data-tool="today" type="button">Jump to today</button>',
			sheet: "",
		};
		PH.set("#view-tools", tools[s.view] || "");
		const hints = {
			board: CFG.boardRole ? "Drag a card between stages, or use its menu · click a card for details" : "Click a card for details",
			list: "Click a group to collapse it · click a row for details",
			timeline: CFG.boardRole ? "Drag a bar to move it, an edge to change one date · Ctrl + scroll to zoom" : "Ctrl + scroll to zoom · click a bar for details",
			sheet: CFG.boardRole ? "Click a cell to edit it · tick rows to change many at once" : "Click a title for details",
		};
		PH.text("#foot-hint", hints[s.view]);
	}
	$("#view-tools").addEventListener("click", (e) => {
		const b = e.target.closest("[data-tool]");
		if (!b) return;
		const tool = b.dataset.tool;
		if (tool === "done") st.set({ stage: st.get("stage") === "open" ? "" : "open" });
		else if (tool === "collapse") {
			groupItems(data.items, st.get("group"), ctx()).forEach((g) => shut.add(shutKey(g)));
			savePrefs();
			drawView();
		} else if (tool === "expand") {
			shut.clear();
			savePrefs();
			drawView();
		} else if (tool === "today") jumpToToday();
	});

	/* ── view dispatcher ───────────────────────────────────────────── */
	function drawView() {
		const view = st.get("view");
		const stage = $("#stage");
		if (!data.items.length && view !== "board") {
			return PH.empty(stage, "Nothing matches these filters", Object.values(st.get()).some(Boolean) ? "Clear a filter to widen the search." : "Tasks, issues and requests land here as they are raised.");
		}
		({ board: drawBoard, list: drawList, timeline: drawTimeline, sheet: drawSheet })[view](stage);
	}

	/* ── shared fragments ──────────────────────────────────────────── */
	const priDot = (i) => `<span class="bb2-pri ${prioClass(i.priority)}" title="${esc(i.priority || "No priority")}"></span>`;
	const people = (i) => {
		if (!i.assignees.length) return '<span class="bb2-who is-none">Unassigned</span>';
		const [first, ...rest] = i.assignees;
		return `<span class="bb2-who" title="${esc(i.assignees.join(", "))}"><span class="bb2-av">${esc(initials(first))}</span><span class="t">${esc(first)}${rest.length ? ` +${rest.length}` : ""}</span></span>`;
	};
	const stageChip = (s) => `<span class="bb2-chip st-${slug(s)}">${esc(s)}</span>`;
	const dueText = (i) => (i.due ? `<span class="${i.late ? "bb2-late" : ""}">${esc(PH.fmt.date(i.due, true))}</span>` : '<span class="ph-muted">—</span>');
	const rowActions = (i) => {
		const btn = (act, title, icon, extra) => `<button type="button" class="bb2-iconbtn" data-act="${act}" title="${title}" aria-label="${title}"${extra || ""}>${PH.icon(icon, 15)}</button>`;
		return (
			btn("desk", "Open in Desk", "external") +
			(canMove(i) ? btn("edit", "Edit", "edit") : "") +
			(canReassign(i) ? btn("reassign", "Reassign", "arrowRight") : "") +
			(canDelete(i) ? btn("delete", "Delete", "trash") : "")
		);
	};
	const itemAttrs = (i) => `data-key="${esc(keyOf(i))}"`;
	const shutKey = (g) => `${st.get("group")}:${g.key}`;

	/* ── BOARD ─────────────────────────────────────────────────────── */
	function cardHtml(i, draggable) {
		return `<div class="bb2-card${canMove(i) ? "" : " is-locked"}" ${itemAttrs(i)} tabindex="0" role="button"${draggable ? ' draggable="true"' : ""} aria-label="${esc(i.title || i.name)}">
			<div class="bb2-card__hd">${priDot(i)}<span class="bb2-src">${SOURCE[i.kind]}</span><span class="ph-mono ph-muted">${esc(i.name)}</span>
				<button type="button" class="bb2-iconbtn" data-act="menu" aria-label="Actions for ${esc(i.title)}" title="Actions">${PH.icon("more", 15)}</button></div>
			<div class="bb2-card__t">${esc(i.title || i.name)}</div>
			<div class="bb2-card__m">${people(i)}${i.due ? `<span class="${i.late ? "bb2-late" : ""}">${i.late ? "Overdue " : "Due "}${esc(PH.fmt.date(i.due, true))}</span>` : ""}${i.module ? `<span>${esc(i.module)}</span>` : ""}</div>
			${(i.tags || []).length ? `<div class="bb2-tagrow">${i.tags.slice(0, 3).map((t) => `<span class="bb2-tag">${esc(t)}</span>`).join("")}${i.tags.length > 3 ? `<span class="bb2-tag">+${i.tags.length - 3}</span>` : ""}</div>` : ""}
		</div>`;
	}

	function drawBoard(stage) {
		const by = st.get("group");
		const groups = groupItems(data.items, by, ctx());
		const drag = by === "stage" && CFG.boardRole;
		const html = groups.map((g) => {
			const cap = caps[g.key] || COLUMN_CAP;
			const shown = g.items.slice(0, cap);
			const total = g.count != null ? g.count : g.items.length;
			const more = g.items.length > shown.length ? `<button type="button" class="ph-btn ph-btn--ghost ph-btn--sm bb2-more" data-more="${esc(g.key)}">Show ${n(Math.min(COLUMN_CAP * 4, g.items.length - shown.length))} more</button>` : "";
			const droppable = drag && STAGES.includes(g.key);
			return `<section class="bb2-col" aria-label="${esc(g.label)}"><div class="bb2-col__head"><span>${esc(g.label)}</span><small>${n(total)}${g.late ? " · " + n(g.late) + " overdue" : ""}</small></div>
				<div class="bb2-drop"${droppable ? ` data-stage="${esc(g.key)}"` : ""}>${shown.map((i) => cardHtml(i, drag && canMove(i))).join("") || '<div class="bb2-empty-col">Nothing here</div>'}${more}</div></section>`;
		}).join("");
		PH.set(stage, groups.length ? `<div class="bb2-cols">${html}</div>` : "");
		if (!data.items.length) PH.empty(stage, "Nothing matches these filters", "Clear a filter to widen the search.");
	}

	/** Moves a card. The endpoint may land a task on a neighbouring stage (a Task has no Blocked status), so we reload and say so. */
	function moveItem(item, stage) {
		if (!canMove(item) || item.stage === stage) return;
		const before = { stage: item.stage, status: item.status };
		item.stage = stage;
		drawView();
		write(BOARD + "set_stage", { doctype: item.kind, name: item.name, stage })
			.then(() => load({ quiet: true }))
			.then(() => {
				const now = find(keyOf(item));
				if (now && now.stage !== stage) PH.toast(`Saved as “${now.status}”, which sits in ${now.stage} (${item.kind === "Task" ? "tasks" : "issues"} have no ${stage} status).`, "warn");
			})
			.catch((e) => {
				Object.assign(item, before);
				drawView();
				PH.toast(e.message || "Could not move that item.", "bad");
			});
	}

	const stageEl = $("#stage");
	let dragKey = null;
	stageEl.addEventListener("dragstart", (e) => {
		const c = e.target.closest(".bb2-card[draggable=true]");
		if (!c) return;
		dragKey = c.dataset.key;
		e.dataTransfer.setData("text/plain", dragKey);
		e.dataTransfer.effectAllowed = "move";
		c.classList.add("is-dragging");
	});
	stageEl.addEventListener("dragend", () => {
		dragKey = null;
		PH.$$(".is-dragging,.is-over", stageEl).forEach((el) => el.classList.remove("is-dragging", "is-over"));
	});
	stageEl.addEventListener("dragover", (e) => {
		const z = e.target.closest(".bb2-drop[data-stage]");
		if (!z || !dragKey) return;
		e.preventDefault();
		PH.$$(".bb2-drop.is-over", stageEl).forEach((el) => el !== z && el.classList.remove("is-over"));
		z.classList.add("is-over");
	});
	stageEl.addEventListener("drop", (e) => {
		const z = e.target.closest(".bb2-drop[data-stage]");
		if (!z || !dragKey) return;
		e.preventDefault();
		const item = find(dragKey);
		dragKey = null;
		z.classList.remove("is-over");
		if (item) moveItem(item, z.dataset.stage);
	});

	/* ── LIST ──────────────────────────────────────────────────────── */
	function drawList(stage) {
		const groups = groupItems(data.items, st.get("group"), ctx()).filter((g) => g.items.length);
		let shown = 0;
		const body = groups.map((g) => {
			const closed = shut.has(shutKey(g));
			const slice = closed ? [] : g.items.slice(0, Math.max(0, listLimit - shown));
			shown += slice.length;
			return `<tr class="bb2-ghead${closed ? " is-shut" : ""}"><td colspan="7"><button type="button" data-group="${esc(shutKey(g))}"><span class="chev">${PH.icon("chevronDown", 14)}</span>${esc(g.label)} <span class="n">${n(g.items.length)}</span></button></td></tr>` +
				slice.map(listRow).join("");
		}).join("");
		const total = groups.reduce((a, g) => a + g.items.length, 0);
		PH.set(stage, `<section class="ph-card ph-card--flush"><div class="ph-table-wrap"><table class="ph-table ph-table--compact bb2-list">
			<thead><tr><th>Work item</th><th>Stage</th><th>Priority</th><th>Assigned to</th><th>Product area</th><th class="is-num">Due</th><th>Actions</th></tr></thead>
			<tbody>${body}</tbody></table></div>
			${shown < total ? `<button type="button" class="ph-btn ph-btn--ghost ph-btn--sm bb2-showmore" data-listmore>Show more — ${n(total - shown)} remaining</button>` : ""}</section>`);
	}

	function listRow(i) {
		const tags = (i.tags || []).map((t) => `<span class="bb2-tag">${esc(t)}</span>`).join("");
		return `<tr class="is-link" ${itemAttrs(i)}>
			<td class="sub"><div class="bb2-subj">${priDot(i)}<span class="bb2-src">${SOURCE[i.kind]}</span><span class="tt">${esc(i.title)}</span></div>${tags ? `<div class="bb2-tagrow">${tags}</div>` : ""}</td>
			<td>${stageChip(i.stage)}</td>
			<td>${i.priority ? esc(i.priority) : '<span class="ph-muted">—</span>'}</td>
			<td>${people(i)}</td>
			<td class="ph-muted">${esc(i.module || "—")}</td>
			<td class="is-num">${dueText(i)}</td>
			<td><span class="bb2-acts">${rowActions(i)}</span></td></tr>`;
	}

	/* ── TIMELINE ──────────────────────────────────────────────────── */
	function drawTimeline(stage) {
		const spans = data.items.map(spanOf).filter(Boolean);
		if (!spans.length) {
			return PH.empty(stage, "No dates to plot", "Tasks appear here once they have a planned or due date, and issues once they have a resolution date. Set one on a work item and it lands on this timeline.", "calendar");
		}
		spans.sort((a, b) => a.start - b.start || a.end - b.end);
		const dayW = ZOOM_W[st.get("zoom")];
		const first = weekStart(addDays(new Date(Math.min(...spans.map((s) => s.start))), -4));
		const last = addDays(new Date(Math.max(...spans.map((s) => s.end))), 6);
		const days = dayDiff(first, last);
		const width = days * dayW;
		const x = (d) => Math.round(dayDiff(first, d) * dayW);

		// What the header can hold depends on how wide a day is, not on the zoom's name.
		const perDay = dayW >= 24, weekStep = dayW >= 12 ? 1 : dayW >= 7 ? 2 : 4, weekends = dayW >= 8;
		const months = [], ticks = [], rules = [];
		let week = 0;
		for (let i = 0; i <= days; i++) {
			const d = addDays(first, i), at = i * dayW;
			if (d.getUTCDate() === 1) {
				months.push(`<div class="bb2-tl-mo" style="left:${at}px">${MONTHS_LONG[d.getUTCMonth()]} ${d.getUTCFullYear()}</div>`);
				rules.push(`<i class="mo" style="left:${at}px"></i>`);
			} else if (perDay) {
				rules.push(`<i style="left:${at}px"></i>`);
				ticks.push(`<div class="bb2-tl-tk${d.getUTCDay() % 6 === 0 ? " is-dim" : ""}" style="left:${at + dayW / 2}px">${DOW[d.getUTCDay()]}<b>${d.getUTCDate()}</b></div>`);
			} else if (d.getUTCDay() === 1) {
				if (week % weekStep === 0) {
					rules.push(`<i style="left:${at}px"></i>`);
					ticks.push(`<div class="bb2-tl-tk" style="left:${at}px">${d.getUTCDate()}</div>`);
				}
				week++;
			}
			if (weekends && d.getUTCDay() === 6) rules.push(`<i class="we" style="left:${at}px;width:${dayW * 2}px"></i>`);
		}
		const now = dateOf(data.today);
		const inside = now >= first && now <= last;
		if (inside) rules.push(`<i class="today" style="left:${x(now)}px"></i>`);

		const by = st.get("group");
		const rowOf = (s) => tlRow(s, x, width, dayW);
		const body = by === "stage"
			? spans.map(rowOf).join("")
			: groupItems(data.items, by, ctx()).map((g) => {
				const own = spans.filter((s) => g.items.includes(s.item));
				return own.length ? laneHead(g.label, own) + own.map(rowOf).join("") : "";
			}).join("");

		PH.set(stage, `<section class="ph-card bb2-tl"><div class="bb2-tl-scroll" id="tl-scroll"><div class="bb2-tl-inner" style="width:${GUTTER + width}px">
			<div class="bb2-tl-hd"><div class="bb2-tl-gut">${spans.length} scheduled</div><div class="bb2-tl-band" style="width:${width}px">${months.join("")}${ticks.join("")}${inside ? `<div class="bb2-tl-today-tag" style="left:${x(now)}px">Today</div>` : ""}</div></div>
			<div class="bb2-tl-body"><div class="bb2-tl-grid" style="width:${width}px">${rules.join("")}</div>${body}</div></div></div>
			<div class="bb2-tl-legend"><span><i class="prog"></i>In progress</span><span><i class="rev"></i>In review</span><span><i class="tri"></i>Triage</span><span><i></i>Queued</span><span><i class="late"></i>Past due</span><span><i class="done"></i>Done</span><span><i class="today"></i>Today</span>
			<span class="sp">${n(spans.length)} of ${n(data.items.length)} items have dates · <span class="bb2-kbd">Ctrl</span> + scroll to zoom</span></div></section>`);

		const scroll = $("#tl-scroll");
		scroll.style.setProperty("--gut", GUTTER + "px");
		if (tlScroll) {
			scroll.scrollLeft = tlScroll.left;
			scroll.scrollTop = tlScroll.top;
		} else if (inside) {
			scroll.scrollLeft = Math.max(0, x(now) - scroll.clientWidth / 2);
		}
		scroll.addEventListener("scroll", () => {
			tlScroll = { left: scroll.scrollLeft, top: scroll.scrollTop };
			clearTimeout(scrollSaveTimer);
			scrollSaveTimer = setTimeout(savePrefs, 400);
		}, { passive: true });
		scroll.addEventListener("wheel", (e) => zoomWheel(e, scroll, dayW), { passive: false });
		if (justMoved) {
			const bar = scroll.querySelector(`.bb2-tl-bar[data-key="${CSS.escape(justMoved)}"]`);
			if (bar) {
				bar.classList.add("just-moved");
				setTimeout(() => bar.classList.remove("just-moved"), 1400);
			}
			justMoved = null;
		}
		timelineGeometry = { first, dayW };
	}
	let timelineGeometry = null;
	let scrollSaveTimer = null;

	function tlRow({ item, start, end }, x, width, dayW) {
		const left = x(start);
		const barW = Math.max((dayDiff(start, end) + 1) * dayW, MIN_BAR);
		const done = item.stage === "Done" || item.stage === DROPPED;
		const cls = done ? "done" : item.late ? "late" : `st-${slug(item.stage)}`;
		const label = start.getTime() === end.getTime() ? short(start) : `${short(start)} → ${short(end)}`;
		const length = dayDiff(start, end) + 1;
		const movable = canMove(item);
		return `<div class="bb2-tl-row"><div class="bb2-tl-gut" ${itemAttrs(item)}>${priDot(item)}<span class="tt" title="${esc(item.title)}">${esc(item.title)}</span>${stageChip(item.stage)}${item.assignees.length ? `<span class="bb2-av" title="${esc(item.assignees.join(", "))}">${esc(initials(item.assignees[0]))}</span>` : ""}</div>
			<div class="bb2-tl-track" style="width:${width}px"><div class="bb2-tl-bar ${cls}${movable ? " is-movable" : ""}" ${itemAttrs(item)} tabindex="0" role="button" style="left:${left}px;width:${barW}px"
				title="${esc(item.title)} · ${esc(item.stage)} · ${label} · ${length} day${length === 1 ? "" : "s"}${item.assignees.length ? " · " + esc(item.assignees.join(", ")) : ""}">${barW > 70 ? esc(item.title) : ""}</div>
			${barW > 70 ? "" : `<div class="bb2-tl-span" style="left:${left + barW}px">${label}</div>`}</div></div>`;
	}

	/** A lane is a person's (or area's) schedule: how much is on it, not just what. */
	function laneHead(label, spans) {
		const late = spans.filter((s) => s.item.late).length;
		const days = spans.reduce((a, s) => a + dayDiff(s.start, s.end) + 1, 0);
		const load = Math.min(100, Math.round((days / (spans.length * 14 || 1)) * 100));
		return `<div class="bb2-tl-lane"><div class="bb2-tl-lane__in"><span>${esc(label)}</span><span class="n">${PH.fmt.plural(spans.length, "item")}</span>${late ? `<span class="bb2-late">${late} late</span>` : ""}<span class="load" title="${days} days committed across ${spans.length} items"><i style="width:${load}%"></i></span><span class="d">${days}d</span></div></div>`;
	}

	function jumpToToday() {
		const scroll = $("#tl-scroll");
		if (!scroll || !timelineGeometry || !data) return;
		const x = dayDiff(timelineGeometry.first, dateOf(data.today)) * timelineGeometry.dayW;
		scroll.scrollTo({ left: Math.max(0, x - scroll.clientWidth / 2), behavior: "smooth" });
	}

	/** Ctrl + wheel: one gesture is one rung, and the date under the pointer stays put. */
	let wheelAcc = 0;
	function zoomWheel(e, scroll, dayW) {
		if (!e.ctrlKey && !e.metaKey) return;
		e.preventDefault();
		wheelAcc += e.deltaMode === 1 ? e.deltaY * 16 : e.deltaMode === 2 ? e.deltaY * 400 : e.deltaY;
		if (Math.abs(wheelAcc) < WHEEL_STEP) return;
		const step = wheelAcc < 0 ? 1 : -1;
		wheelAcc = 0;
		const cur = st.get("zoom");
		const next = ZOOM_COARSE_FIRST[Math.min(ZOOM_COARSE_FIRST.length - 1, Math.max(0, ZOOM_COARSE_FIRST.indexOf(cur) + step))];
		if (next === cur) return;
		const cursor = e.clientX - scroll.getBoundingClientRect().left - GUTTER;
		const day = (scroll.scrollLeft + cursor) / dayW;
		tlScroll = { left: Math.max(0, day * ZOOM_W[next] - cursor), top: scroll.scrollTop };
		st.set({ zoom: next });
	}

	/** Dragging a bar moves both dates by the same number of days; an edge moves one of them. */
	let tlDrag = null;
	stageEl.addEventListener("pointerdown", (e) => {
		const bar = e.target.closest(".bb2-tl-bar.is-movable");
		if (!bar || e.button !== 0 || !timelineGeometry) return;
		const item = find(bar.dataset.key);
		const span = item && spanOf(item);
		if (!span) return;
		const box = bar.getBoundingClientRect();
		const readout = document.createElement("div");
		readout.className = "bb2-tl-readout";
		bar.parentNode.appendChild(readout);
		tlDrag = { bar, item, span, mode: grabMode(e.clientX - box.left, box.width), fromX: e.clientX, shift: 0, readout, left: bar.offsetLeft, width: bar.offsetWidth, moved: false };
		bar.setPointerCapture(e.pointerId);
		bar.classList.add("is-held");
	});
	stageEl.addEventListener("pointermove", (e) => {
		if (!tlDrag) return;
		const { dayW } = timelineGeometry;
		const dx = e.clientX - tlDrag.fromX;
		if (Math.abs(dx) > 3) tlDrag.moved = true;
		const shift = Math.round(dx / dayW);
		const next = shiftedSpan(tlDrag.span.start, tlDrag.span.end, tlDrag.mode, shift);
		tlDrag.shift = shift;
		tlDrag.next = next;
		const left = Math.round(dayDiff(timelineGeometry.first, next.start) * dayW);
		tlDrag.bar.style.left = left + "px";
		tlDrag.bar.style.width = Math.max((dayDiff(next.start, next.end) + 1) * dayW, MIN_BAR) + "px";
		tlDrag.readout.textContent = `${short(next.start)} → ${short(next.end)}`;
		tlDrag.readout.style.left = left + "px";
	});
	function endTlDrag() {
		if (!tlDrag) return;
		const { bar, item, mode, shift, next, readout, moved } = tlDrag;
		tlDrag = null;
		bar.classList.remove("is-held");
		readout.remove();
		if (!shift) {
			if (!moved) openItem(item);
			return drawView();
		}
		const patch = {};
		if (mode !== "end") patch.start = iso(next.start);
		if (mode !== "start") patch.end = iso(next.end);
		reschedule(item, patch);
	}
	stageEl.addEventListener("pointerup", endTlDrag);
	stageEl.addEventListener("pointercancel", () => {
		if (tlDrag) tlDrag.bar.classList.remove("is-held");
		if (tlDrag) tlDrag.readout.remove();
		tlDrag = null;
		drawView();
	});

	/** One update_work call carries both dates, so a long move cannot trip the start-after-end check halfway. */
	function reschedule(item, patch) {
		const before = { start: item.start, due: item.due };
		if (patch.start) item.start = patch.start;
		if (patch.end) item.due = patch.end;
		justMoved = keyOf(item);
		drawView();
		write(BOARD + "update_work", { doctype: item.kind, name: item.name, values: patch })
			.then(() => {
				PH.toast(`${item.title} moved to ${PH.fmt.date(patch.start || patch.end, true)}`, "good");
				load({ quiet: true });
			})
			.catch((e) => {
				Object.assign(item, before);
				justMoved = null;
				drawView();
				PH.toast(e.message || "Could not move that work.", "bad");
			});
	}

	/* ── SHEET ─────────────────────────────────────────────────────── */
	/** Sheet columns. `field` is the update_work key; `only` restricts a column to one doctype. */
	const SHEET_COLS = [
		{ key: "title", label: "Work item", field: "title", edit: "text", sort: (i) => i.title.toLowerCase() },
		{ key: "stage", label: "Stage", field: "stage", edit: "select", sort: (i) => STAGES.indexOf(i.stage) },
		{ key: "priority", label: "Priority", field: "priority", edit: "select", sort: (i) => (data ? data.options.priorities.indexOf(i.priority) : 0) },
		{ key: "assignee", label: "Assignee", field: "assign_to", edit: "people", only: "Task", sort: (i) => i.assignees.join(", ") },
		{ key: "module", label: "Product area", field: "module", edit: "select", sort: (i) => i.module },
		{ key: "tags", label: "Tags", field: "tags", edit: "tags", sort: (i) => (i.tags || []).join(",") },
		{ key: "due", label: "Due", field: "end", edit: "date", sort: (i) => i.due || "9999" },
		{ key: "start", label: "Start", field: "start", edit: "date", sort: (i) => i.start || "9999" },
		{ key: "status", label: "Status", field: "status", edit: "select", only: "Task", sort: (i) => i.status },
		{ key: "project", label: "Project", field: "project", edit: "select", sort: (i) => i.project || "" },
		{ key: "name", label: "ID", sort: (i) => i.name },
	];

	function cellHtml(col, i) {
		const editable = CFG.boardRole && col.edit && canMove(i) && (!col.only || col.only === i.kind);
		const cls = ["c", col.key === "title" ? "title" : "", editable ? "is-edit" : col.edit ? "is-locked" : ""].join(" ");
		let inner;
		switch (col.key) {
			case "title": inner = `<span class="bb2-subj">${priDot(i)}<span class="bb2-src">${SOURCE[i.kind]}</span><a class="bb2-link tt" href="#" data-act="open">${esc(i.title)}</a></span>`; break;
			case "stage": inner = stageChip(i.stage); break;
			case "assignee": inner = people(i); break;
			case "tags": inner = (i.tags || []).map((t) => `<span class="bb2-tag">${esc(t)}</span>`).join(" "); break;
			case "due": inner = i.due ? `<span class="${i.late ? "bb2-late" : ""}">${esc(i.due)}</span>` : ""; break;
			case "project": inner = esc((data.options.projects.find((p) => p.name === i.project) || {}).project_name || i.project || ""); break;
			case "name": inner = `<span class="ph-mono">${esc(i.name)}</span>`; break;
			default: inner = esc(i[col.key] || "");
		}
		return `<td class="${cls}" data-col="${col.key}">${inner}</td>`;
	}

	function drawSheet(stage) {
		let rows = data.items.slice();
		if (sheetSort) {
			const col = SHEET_COLS.find((c) => c.key === sheetSort.key);
			rows.sort((a, b) => {
				const x = col.sort(a), y = col.sort(b);
				return (x > y ? 1 : x < y ? -1 : 0) * (sheetSort.dir === "desc" ? -1 : 1);
			});
		}
		const shownRows = rows.slice(0, sheetLimit);
		const head = SHEET_COLS.map((c) => `<th data-sort="${c.key}" class="${sheetSort && sheetSort.key === c.key ? "is-sorted" : ""}">${esc(c.label)}${sheetSort && sheetSort.key === c.key ? (sheetSort.dir === "desc" ? " ▾" : " ▴") : ""}</th>`).join("");
		const body = shownRows.map((i) => `<tr ${itemAttrs(i)} class="${selected.has(keyOf(i)) ? "is-sel" : ""}${i.stage === "Done" ? " is-done" : ""}">${CFG.boardRole ? `<td class="chk"><input type="checkbox" data-pick aria-label="Select ${esc(i.title)}" ${selected.has(keyOf(i)) ? "checked" : ""}></td>` : ""}${SHEET_COLS.map((c) => cellHtml(c, i)).join("")}</tr>`).join("");
		PH.set(stage, `<section class="ph-card ph-card--flush"><div class="bb2-sheet-bar" id="sheet-bar"></div>
			<div class="bb2-sheet-wrap"><table class="bb2-sheet"><thead><tr>${CFG.boardRole ? '<th class="chk nosort"><input type="checkbox" data-pick-all aria-label="Select all shown rows"></th>' : ""}${head}</tr></thead><tbody>${body}</tbody></table></div>
			${rows.length > shownRows.length ? `<button type="button" class="ph-btn ph-btn--ghost ph-btn--sm bb2-showmore" data-sheetmore>Show more — ${n(rows.length - shownRows.length)} remaining</button>` : ""}</section>`);
		paintSheetBar();
	}

	/** Selection bar + save status above the grid. */
	function setSaveStatus(state, count) {
		saveStatus = { state, count };
		paintSheetBar();
		if (state === "saved") setTimeout(() => { saveStatus = null; paintSheetBar(); }, 2500);
	}

	function paintSheetBar() {
		const bar = $("#sheet-bar");
		if (!bar) return;
		const { state, count } = saveStatus || {};
		const msg = { saving: `Saving ${PH.fmt.plural(count, "change")}…`, saved: `${PH.fmt.plural(count, "change")} saved`, error: `${PH.fmt.plural(count, "change")} could not be saved` }[state] || "";
		if (state) bar.dataset.state = state; else delete bar.dataset.state;
		const sel = selected.size
			? `<span class="bb2-bulk">${n(selected.size)} selected<button class="ph-btn ph-btn--sm" type="button" data-bulk>Set a field…</button><button class="ph-btn ph-btn--ghost ph-btn--sm" type="button" data-bulk-clear>Clear</button></span>`
			: "";
		bar.innerHTML = `${sel}<span class="bb2-save">${esc(msg)}</span>${selected.size || !CFG.boardRole ? "" : '<span class="ph-muted">Click a cell to edit it · tick rows to change many at once</span>'}<span style="margin-left:auto"><button class="ph-btn ph-btn--sm" type="button" data-csv>Export CSV</button></span>`;
	}

	/** Inline cell editor. Escape cancels, Enter / blur commits. */
	function editCell(td) {
		const tr = td.closest("tr");
		const item = find(tr.dataset.key);
		const col = SHEET_COLS.find((c) => c.key === td.dataset.col);
		if (!item || !col || td.querySelector(".bb2-sheet-ed")) return;
		if (col.edit === "people" || col.edit === "tags") {
			return editorModal(col, [item], (value) => applyEdits([{ item, col, value }]));
		}
		const input = buildEditor(col, valueOf(col, item));
		td.innerHTML = "";
		td.appendChild(input);
		input.focus();
		let done = false;
		const finish = (commit) => {
			if (done) return;
			done = true;
			if (commit) applyEdits([{ item, col, value: input.value }]);
			else drawView();
		};
		input.addEventListener("keydown", (e) => {
			if (e.key === "Enter") finish(true);
			else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); finish(false); }
		});
		input.addEventListener("change", () => input.tagName === "SELECT" && finish(true));
		input.addEventListener("blur", () => finish(true));
	}

	/** Current value of a column, in the form the editor shows it. */
	function valueOf(col, i) {
		return { title: i.title, stage: i.stage, priority: i.priority, module: i.module, due: i.due, start: i.start, status: i.status, project: i.project || "", tags: i.tags || [], assignee: i.assignee_ids }[col.key];
	}

	/** Options for a select column (current value kept selectable so an odd value is not silently changed). */
	function selectOptions(col, current) {
		const opts = {
			stage: STAGES,
			priority: ["", ...lists.priorities],
			module: ["", ...lists.modules],
			status: TASK_STATUSES,
			project: ["", ...data.options.projects.map((p) => p.name)],
		}[col.key].map((v) => ({ v, l: col.key === "project" ? (data.options.projects.find((p) => p.name === v) || {}).project_name || v : v }));
		if (current && !opts.some((o) => o.v === current)) opts.unshift({ v: current, l: current });
		return opts;
	}

	function buildEditor(col, value) {
		let el;
		if (col.edit === "select") {
			el = document.createElement("select");
			el.innerHTML = selectOptions(col, value).map((o) => `<option value="${esc(o.v)}"${o.v === value ? " selected" : ""}>${esc(o.l || "—")}</option>`).join("");
		} else {
			el = document.createElement("input");
			el.type = col.edit === "date" ? "date" : "text";
			el.value = value || "";
		}
		el.className = "bb2-sheet-ed";
		return el;
	}

	/** Local validation, then a debounced bulk_update. edits: [{item, col, value}]. */
	function applyEdits(edits) {
		const problems = new Map();
		let queued = 0;
		edits.forEach(({ item, col, value }) => {
			const problem = validateEdit(item, col, value);
			if (problem === "same") return;
			if (problem) return problems.set(problem, (problems.get(problem) || 0) + 1);
			queueEdit(item, col, value);
			queued++;
		});
		problems.forEach((count, msg) => PH.toast(count > 1 ? `${msg} (${count} rows)` : msg, "warn"));
		drawView();
		return { queued, skipped: [...problems.values()].reduce((a, b) => a + b, 0) };
	}

	function validateEdit(item, col, value) {
		if (col.only && col.only !== item.kind) return `Only tasks can have their ${col.label.toLowerCase()} changed here.`;
		if (!canMove(item)) return "Requests move through their own workflow, not the board.";
		const cur = valueOf(col, item);
		const same = Array.isArray(cur) ? csvList(cur) === csvList(value) : String(cur || "") === String(value || "");
		if (same) return "same";
		if (col.key === "title" && !String(value || "").trim()) return "A work item needs a title.";
		if (col.key === "assignee" && !value.length) return "Pick at least one name. Clearing an assignment is not possible from here.";
		if (col.key === "due" && item.start && value && value < item.start) return "Due date can't be before the start date.";
		if (col.key === "start" && item.due && value && value > item.due) return "Start date can't be after the due date.";
		return "";
	}

	/** Moves the local copy first so the grid answers at once, then batches the write. */
	function queueEdit(item, col, value) {
		const key = keyOf(item);
		const held = pending.get(key) || { item, before: { ...item }, values: {} };
		const names = Object.fromEntries(lists.people.map((p) => [p.name, p.full_name || p.name]));
		if (col.key === "assignee") { item.assignee_ids = value; item.assignees = value.map((e) => names[e] || e); held.values.assign_to = csvList(value); }
		else if (col.key === "tags") { item.tags = value; held.values.tags = csvList(value); }
		else if (col.key === "due") { item.due = value; held.values.end = value; }
		else { item[col.key] = value; held.values[col.field] = value; }
		pending.set(key, held);
		clearTimeout(flushTimer);
		flushTimer = setTimeout(flushEdits, FLUSH_MS);
	}

	function flushEdits() {
		const batch = [...pending.values()];
		pending.clear();
		if (!batch.length) return;
		setSaveStatus("saving", batch.length);
		const chunks = [];
		for (let i = 0; i < batch.length; i += BULK_LIMIT) chunks.push(batch.slice(i, i + BULK_LIMIT));
		Promise.all(chunks.map((c) => write(BOARD + "bulk_update", { changes: c.map(({ item, values }) => ({ doctype: item.kind, name: item.name, values })) })))
			.then((results) => {
				const failed = results.flatMap((r) => (r && r.failed) || []);
				if (failed.length) {
					setSaveStatus("error", failed.length);
					PH.toast(failed.length === 1 ? failed[0].error : `${failed.length} of ${batch.length} rows could not be saved.`, "bad");
				} else setSaveStatus("saved", batch.length);
				return load({ quiet: true });
			})
			.catch((e) => {
				batch.forEach(({ item, before }) => Object.assign(item, before));
				setSaveStatus("error", batch.length);
				drawView();
				PH.toast(e.message || "Could not save those cells.", "bad");
			});
	}

	/** Same editor in a dialog, applied to every selected row. */
	function editorModal(col, items, onApply) {
		loadLists().then((a) => {
			const current = items.length === 1 ? valueOf(col, items[0]) : col.edit === "tags" || col.edit === "people" ? [] : "";
			const field = { name: "v", label: col.label, type: col.edit === "tags" ? "tags" : col.edit === "people" ? "people" : col.edit, value: current, options: col.edit === "select" ? selectOptions(col, "").map((o) => [o.v, o.l]) : undefined, full: true, required: col.edit === "people" };
			formModal({
				title: items.length === 1 ? `${col.label} · ${items[0].name}` : `Set ${col.label.toLowerCase()} on ${items.length} rows`,
				fields: [field], submit: "Apply",
				onSubmit: (v) => { onApply(v.v); },
			});
		});
	}

	stageEl.addEventListener("click", (e) => {
		const t = e.target;
		const sheetCol = t.closest("th[data-sort]");
		if (sheetCol) {
			const key = sheetCol.dataset.sort;
			sheetSort = sheetSort && sheetSort.key === key ? (sheetSort.dir === "asc" ? { key, dir: "desc" } : null) : { key, dir: "asc" };
			return drawView();
		}
		if (t.closest("[data-sheetmore]")) { sheetLimit += SHEET_PAGE * 2; return drawView(); }
		if (t.closest("[data-listmore]")) { listLimit += LIST_PAGE * 4; return drawView(); }
		if (t.closest("[data-csv]")) return exportCsv();
		if (t.closest("[data-bulk]")) return bulkMenu(t.closest("[data-bulk]"));
		if (t.closest("[data-bulk-clear]")) { selected.clear(); return drawView(); }
		const g = t.closest("[data-group]");
		if (g) {
			const k = g.dataset.group;
			shut.has(k) ? shut.delete(k) : shut.add(k);
			savePrefs();
			return drawView();
		}
		const more = t.closest("[data-more]");
		if (more) { caps[more.dataset.more] = (caps[more.dataset.more] || COLUMN_CAP) + COLUMN_CAP * 4; return drawView(); }

		if (t.closest(".bb2-tl-bar.is-movable")) return; // opened by the pointerup that ends the press
		const row = t.closest("[data-key]");
		const item = row && find(row.dataset.key);
		if (t.closest("[data-pick-all]")) {
			const on = t.closest("[data-pick-all]").checked;
			PH.$$("tbody tr[data-key]", stageEl).forEach((tr) => (on ? selected.add(tr.dataset.key) : selected.delete(tr.dataset.key)));
			return drawView();
		}
		if (t.closest("[data-pick]") && item) {
			const rows = PH.$$("tbody tr[data-key]", stageEl).map((tr) => tr.dataset.key);
			const at = rows.indexOf(row.dataset.key);
			const on = t.closest("[data-pick]").checked;
			const [a, b] = e.shiftKey && lastPicked > -1 ? [Math.min(at, lastPicked), Math.max(at, lastPicked)] : [at, at];
			rows.slice(a, b + 1).forEach((k) => (on ? selected.add(k) : selected.delete(k)));
			lastPicked = at;
			return drawView();
		}
		if (!item) return;
		const act = t.closest("[data-act]");
		if (act) {
			e.preventDefault();
			e.stopPropagation();
			return runAction(act.dataset.act, item, act);
		}
		const cell = t.closest("td.c.is-edit");
		if (cell && st.get("view") === "sheet") return loadLists().then(() => editCell(cell));
		if (st.get("view") === "sheet" && !t.closest("td.c.title")) return;
		openItem(item);
	});
	stageEl.addEventListener("keydown", (e) => {
		const c = e.target.closest(".bb2-card,.bb2-tl-bar");
		if (c && c === e.target && (e.key === "Enter" || e.key === " ")) {
			e.preventDefault();
			const item = find(c.dataset.key);
			if (item) openItem(item);
		}
	});

	/** Bulk menu: pick which field to set on the selected rows. */
	function bulkMenu(anchor) {
		const cols = SHEET_COLS.filter((c) => c.edit && c.key !== "title");
		PH.menu(anchor, cols.map((col) => ({
			label: col.label,
			onClick: () => {
				const items = [...selected].map(find).filter(Boolean);
				editorModal(col, items, (value) => {
					const { queued, skipped } = applyEdits(items.map((item) => ({ item, col, value })));
					selected.clear();
					PH.toast(skipped ? `${queued} rows changed. ${skipped} left alone.` : `${queued} rows changed.`, skipped ? "warn" : "good");
				});
			},
		})));
	}

	/* ── row / card actions ────────────────────────────────────────── */
	function runAction(act, item, anchor) {
		if (act === "open") return openItem(item);
		if (act === "desk") return PH.openDoc(item.kind, item.name);
		if (act === "edit") return openEdit(item);
		if (act === "reassign") return openReassign(item);
		if (act === "delete") return confirmDelete(item);
		if (act === "menu") {
			const moves = canMove(item) && st.get("group") === "stage" ? STAGES.filter((s) => s !== item.stage).map((s) => ({ label: "Move to " + s, onClick: () => moveItem(item, s) })) : [];
			PH.menu(anchor, [
				{ label: "Details", icon: "info", onClick: () => openItem(item) },
				...(canMove(item) ? [{ label: "Edit", icon: "edit", onClick: () => openEdit(item) }] : []),
				...moves,
				...(canReassign(item) ? [{ label: "Reassign", icon: "arrowRight", onClick: () => openReassign(item) }] : []),
				{ label: "Open in Desk", icon: "external", onClick: () => PH.openDoc(item.kind, item.name) },
				...(canDelete(item) ? [{ label: "Delete", icon: "trash", danger: true, onClick: () => confirmDelete(item) }] : []),
			]);
		}
	}

	function confirmDelete(item) {
		PH.confirm(`Delete ${item.title || item.name}?`, "This can't be undone.", { danger: true, ok: "Delete" }).then((yes) => {
			if (!yes) return;
			write(item.kind === "Task" ? BOARD + "delete_task" : REQ + "delete_request", { name: item.name })
				.then(() => {
					data.items = data.items.filter((i) => i !== item);
					drawView();
					PH.toast("Deleted.", "good");
					load({ quiet: true });
				})
				.catch((e) => PH.toast(e.message || "Could not delete that.", "bad"));
		});
	}

	/* ── form dialogs ──────────────────────────────────────────────── */
	/** Searchable multi-user picker built on PH.autocomplete. get() returns the emails. */
	function peoplePicker(initial) {
		const chosen = [...(initial || [])];
		const el = document.createElement("div");
		el.className = "bb2-people";
		el.innerHTML = '<div class="bb2-people__chips"></div><input class="ph-control" type="text" placeholder="Search people, pick as many as you need" aria-label="Search people">';
		const chips = el.firstChild, input = el.lastChild;
		const names = () => Object.fromEntries(lists.people.map((p) => [p.name, p.full_name || p.name]));
		const paint = () => {
			const lab = names();
			chips.innerHTML = chosen.map((e) => `<span class="bb2-people__chip">${esc(lab[e] || e)}<button type="button" data-rm="${esc(e)}" aria-label="Remove ${esc(lab[e] || e)}">×</button></span>`).join("");
		};
		chips.addEventListener("click", (ev) => {
			const b = ev.target.closest("[data-rm]");
			if (b) { chosen.splice(chosen.indexOf(b.dataset.rm), 1); paint(); }
		});
		input.addEventListener("keydown", (ev) => {
			if (ev.key === "Backspace" && !input.value && chosen.length) {
				chosen.pop();
				paint();
			}
		});
		PH.autocomplete(input, {
			source: async (q) => {
				const words = q.toLowerCase().split(/\s+/).filter(Boolean);
				return lists.people
					.filter((p) => !chosen.includes(p.name) && words.every((w) => `${p.full_name || ""} ${p.name}`.toLowerCase().includes(w)))
					.slice(0, 30)
					.map((p) => ({ value: p.name, label: p.full_name || p.name, description: p.name }));
			},
			display: () => "",
			onSelect: (it) => { chosen.push(it.value); paint(); },
		});
		paint();
		return { el, get: () => chosen.slice() };
	}

	/** Toggle chips limited to the Work Tag master list. get() returns the chosen tags. */
	function tagPicker(initial) {
		const chosen = new Set(initial || []);
		const el = document.createElement("div");
		el.className = "bb2-tagpick";
		const all = [...new Set([...lists.tags, ...chosen])];
		el.innerHTML = all.length ? all.map((t) => `<button type="button" data-tag="${esc(t)}" aria-pressed="${chosen.has(t)}" class="${chosen.has(t) ? "is-on" : ""}">${esc(t)}</button>`).join("") : '<span class="ph-muted">No tags set up yet - add one in Master Data.</span>';
		el.addEventListener("click", (ev) => {
			const b = ev.target.closest("[data-tag]");
			if (!b) return;
			chosen.has(b.dataset.tag) ? chosen.delete(b.dataset.tag) : chosen.add(b.dataset.tag);
			b.classList.toggle("is-on", chosen.has(b.dataset.tag));
			b.setAttribute("aria-pressed", chosen.has(b.dataset.tag));
		});
		return { el, get: () => [...chosen] };
	}

	/**
	 * A validated form in a PH.modal. fields: [{name,label,type,value,options,required,readonly,hint,full}]
	 * types: text, textarea, select, date, tags, people, note. onSubmit(values) may return a promise; a
	 * rejection is shown in the dialog (which stays open) instead of being lost in a toast.
	 */
	function formModal({ title, sub, fields, submit, onSubmit }) {
		const form = document.createElement("form");
		form.className = "ph-form ph-form--2 bb2-form";
		form.noValidate = true;
		form.innerHTML = '<div class="ph-notice ph-notice--warn bb2-form-err ph-field--full" role="alert" hidden></div>';
		const getters = {};
		fields.forEach((f) => {
			if (f.type === "note") return form.insertAdjacentHTML("beforeend", `<div class="bb2-note ph-field--full">${esc(f.text)}</div>`);
			const wrap = document.createElement("div");
			wrap.className = "ph-field" + (f.full || ["textarea", "tags", "people"].includes(f.type) ? " ph-field--full" : "");
			const id = "bb2-f-" + f.name;
			wrap.innerHTML = `<label for="${id}">${esc(f.label)}${f.required ? " *" : ""}</label>`;
			let control;
			if (f.type === "tags") control = tagPicker(f.value);
			else if (f.type === "people") control = peoplePicker(f.value);
			else {
				const tag = f.type === "select" ? "select" : f.type === "textarea" ? "textarea" : "input";
				const el = document.createElement(tag);
				el.className = "ph-control";
				el.id = id;
				if (tag === "input") el.type = f.type === "date" ? "date" : "text";
				if (tag === "textarea") el.rows = 4;
				if (tag === "select") el.innerHTML = (f.options || []).map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join("");
				el.value = f.value == null ? "" : f.value;
				if (f.readonly) el.readOnly = true;
				control = { el, get: () => el.value };
			}
			wrap.appendChild(control.el);
			if (f.hint) wrap.insertAdjacentHTML("beforeend", `<div class="ph-field__hint">${esc(f.hint)}</div>`);
			wrap.insertAdjacentHTML("beforeend", '<div class="ph-field__error" hidden></div>');
			form.appendChild(wrap);
			getters[f.name] = { f, get: control.get, wrap };
		});

		const banner = form.firstChild;
		const submitNow = async (m) => {
			banner.hidden = true;
			const values = {};
			let ok = true;
			Object.values(getters).forEach(({ f, get, wrap }) => {
				const v = get();
				values[f.name] = v;
				const err = wrap.querySelector(".ph-field__error");
				const empty = Array.isArray(v) ? !v.length : !String(v || "").trim();
				err.hidden = !(f.required && empty);
				err.textContent = f.type === "tags" ? "Pick at least one tag." : f.type === "people" ? "Pick at least one person." : "This is required.";
				if (f.required && empty) ok = false;
			});
			if (!ok) return false;
			try {
				await onSubmit(values);
			} catch (e) {
				banner.textContent = e.message || "Could not save that.";
				banner.hidden = false;
				return false;
			}
		};
		const m = PH.modal({
			title, sub, body: form, size: "lg",
			actions: [{ label: "Cancel" }, { label: submit, primary: true, onClick: submitNow }],
		});
		form.addEventListener("submit", (e) => e.preventDefault());
		// An error is about the value that was there; once the person touches the field it is stale.
		["input", "click"].forEach((type) => form.addEventListener(type, (e) => {
			const err = e.target.closest(".ph-field") && e.target.closest(".ph-field").querySelector(".ph-field__error");
			if (err) err.hidden = true;
		}));
		form.addEventListener("keydown", (e) => {
			if (e.key === "Enter" && !e.defaultPrevented && e.target.tagName !== "TEXTAREA" && e.target.tagName !== "BUTTON") {
				e.preventDefault();
				m.el.querySelector(".ph-btn--primary").click();
			}
		});
		return m;
	}

	const priorityOptions = (a, blank) => [["", blank], ...a.priorities.map((p) => [p, p])];
	const moduleOptions = (a, blank) => [["", blank], ...a.modules.map((p) => [p, p])];
	const projectList = () => (data ? data.options.projects : []);
	const projectOptions = (blank) => [...(blank ? [["", blank]] : []), ...projectList().map((p) => [p.name, p.project_name || p.name])];

	/** New task (trusted: a real Task) or Add to backlog (everyone else: a Request, as the endpoint decides). */
	function openNew() {
		loadLists().then((a) => {
			const trusted = CFG.canCreate;
			const fields = [
				...(trusted ? [{ name: "project", label: "Project", type: "select", options: projectOptions(), value: st.get("project") || (projectList()[0] || {}).name, required: true }] : []),
				{ name: "subject", label: "Title", type: "text", required: true, full: true },
				{ name: "tags", label: "Tags", type: "tags", required: true, value: [] },
				{ name: "description", label: "Description", type: "textarea" },
				...(trusted ? [
					{ name: "priority", label: "Priority", type: "select", options: priorityOptions(a, "No priority"), value: "" },
					{ name: "module", label: "Product area", type: "select", options: moduleOptions(a, "No product area"), value: "" },
					{ name: "complete_by", label: "Due date", type: "date" },
					{ name: "assign_to", label: "Assign to", type: "people", value: [] },
				] : [{ name: "note", type: "note", text: "This goes to a reviewer as a request, not straight onto the board." }]),
			];
			formModal({
				title: trusted ? "New task" : "Add to backlog", fields, submit: "Create",
				onSubmit: async (v) => {
					const payload = { subject: v.subject.trim(), tags: csvList(v.tags) };
					["project", "description", "priority", "module", "complete_by"].forEach((k) => v[k] && (payload[k] = v[k]));
					if (v.assign_to && v.assign_to.length) payload.assign_to = csvList(v.assign_to);
					const r = await write(BOARD + "create_task", payload);
					PH.toast(trusted ? `Task ${r && r.name ? r.name + " " : ""}created.` : "Sent for review.", "good");
					load({ quiet: true });
				},
			});
		});
	}

	/** The edit dialog (Tasks and Issues). Sends only the fields that changed. */
	function openEdit(item) {
		Promise.all([loadLists(), write(BOARD + "get_editable", { doctype: item.kind, name: item.name })]).then(([a, v]) => {
			const desc = plainDescription(v.description);
			const initial = {
				title: v.title || item.title, stage: item.stage, priority: v.priority || "", module: v.module || "", project: v.project || "",
				start: v.start || "", end: v.end || "", tags: csvList(v.tags || []), assign_to: csvList(v.assignees || []),
			};
			const stages = STAGES.includes(item.stage) ? STAGES : [item.stage, ...STAGES];
			const fields = [
				{ name: "title", label: "Title", type: "text", value: initial.title, required: true, full: true },
				{ name: "description", label: desc.rich ? "Description (has formatting, edit it on the item itself)" : "Description", type: "textarea", value: desc.text, readonly: desc.rich },
				{ name: "stage", label: "Stage", type: "select", options: stages.map((s) => [s, s]), value: initial.stage },
				{ name: "priority", label: "Priority", type: "select", options: priorityOptions(a, "No priority"), value: initial.priority },
				{ name: "module", label: "Product area", type: "select", options: moduleOptions(a, "No product area"), value: initial.module },
				{ name: "project", label: "Project", type: "select", options: projectOptions("No project"), value: initial.project },
				{ name: "start", label: "Start", type: "date", value: initial.start },
				{ name: "end", label: "Due date", type: "date", value: initial.end },
				{ name: "tags", label: "Tags", type: "tags", value: v.tags || [] },
				...(item.kind === "Task" ? [{ name: "assign_to", label: "Assigned to", type: "people", value: v.assignees || [] }] : []),
			];
			formModal({
				title: `Edit ${item.name}`, sub: item.kind, fields, submit: "Save changes",
				onSubmit: async (vals) => {
					if (vals.start && vals.end && vals.end < vals.start) throw new Error("Due date can't be before the start date.");
					const after = { ...vals, tags: csvList(vals.tags), assign_to: csvList(vals.assign_to || []) };
					delete after.description; // text only goes back when it is plain and was edited
					const changes = changedFields(initial, after);
					if (!desc.rich && vals.description.trim() !== desc.text) changes.description = richDescription(vals.description);
					if (!Object.keys(changes).length) return PH.toast("Nothing to save.", "warn");
					await write(BOARD + "update_work", { doctype: item.kind, name: item.name, values: changes });
					PH.toast("Saved.", "good");
					load({ quiet: true });
				},
			});
		}).catch((e) => PH.toast(e.message || "Could not open that one.", "bad"));
	}

	function openReassign(item) {
		loadLists().then((a) => {
			formModal({
				title: `Reassign ${item.title}`, sub: item.name,
				fields: [
					{ name: "assign_to", label: "Assign to", type: "people", required: true, value: item.assignee_ids },
					{ name: "complete_by", label: "Complete by", type: "date" },
					{ name: "comment", label: "Comment", type: "text", full: true },
				],
				submit: "Reassign",
				onSubmit: async (v) => {
					const payload = { name: item.name, assign_to: csvList(v.assign_to) };
					if (v.complete_by) payload.complete_by = v.complete_by;
					if (v.comment) payload.comment = v.comment;
					await write(REQ + "reassign_task", payload);
					PH.toast("Reassigned.", "good");
					load({ quiet: true });
				},
			});
		});
	}

	/* ── item drawer ───────────────────────────────────────────────── */
	function openItem(item) {
		const body = document.createElement("div");
		PH.skeleton(body);
		const actions = [
			...(canMove(item) ? [{ label: "Edit", primary: true, onClick: (m) => { m.close(); openEdit(item); return false; } }] : []),
			...(canReassign(item) ? [{ label: "Reassign", onClick: (m) => { m.close(); openReassign(item); return false; } }] : []),
			{ label: "Open in Desk", onClick: () => { PH.openDoc(item.kind, item.name); return false; } },
			...(canDelete(item) ? [{ label: "Delete", danger: true, onClick: (m) => { m.close(); confirmDelete(item); return false; } }] : []),
		];
		const m = PH.modal({ title: item.name, sub: item.kind, body, size: "lg", drawer: true, actions });
		PH.call(API + "get_backlog_item", { doctype: item.kind, name: item.name }, { silent: true }).then((d) => {
			const kv = (k, v) => `<dt>${esc(k)}</dt><dd>${v}</dd>`;
			const plain = (v) => (v ? esc(v) : '<span class="ph-muted">—</span>');
			let h = `<div class="ph-strong ph-mb">${esc(d.title || d.name)}</div><dl class="ph-kv">` +
				kv("Stage", stageChip(d.stage)) + kv("Status", plain(d.status)) + kv("Priority", plain(d.priority)) +
				kv("Project", plain(d.project_name || d.project)) + kv("Product area", plain(d.module)) +
				kv("Assigned to", plain(d.assignees.join(", "))) + kv("Start", plain(d.start && PH.fmt.date(d.start))) +
				kv("Due", d.due ? esc(PH.fmt.date(d.due)) + (d.late ? ' <span class="ph-badge ph-badge--warn">Overdue</span>' : "") : plain("")) +
				kv("Tags", plain((d.tags || []).join(", "))) + kv("Created", esc(PH.fmt.datetime(d.created))) + kv("Last changed", esc(PH.fmt.datetime(d.modified)));
			if (d.detail) {
				h += kv("Raised by", plain(d.raised_by));
				if (d.request_type) h += kv("Request type", esc(d.request_type));
				if (d.source) h += kv("Source", esc(d.source));
			}
			h += "</dl>";
			if (d.detail) {
				if (d.description) h += `<div class="bb2-h">Description</div><div class="bb2-desc">${esc(d.description)}</div>`;
				if (d.resolution_notes) h += `<div class="bb2-h">Resolution notes</div><div class="bb2-desc">${esc(d.resolution_notes)}</div>`;
				if ((d.links || []).length) {
					h += '<div class="bb2-h">Linked work</div><ul class="bb2-hist">' + d.links.map((l) => `<li><span>${esc(l.kind)}</span><span>${l.missing ? esc(l.name) + " (no longer exists)" : `<a class="ph-link" href="${docUrl(l.kind, l.name)}" target="_blank" rel="noopener">${esc(l.name)}</a> ${esc(l.title)} <span class="ph-muted">· ${esc(l.status)}</span>`}</span></li>`).join("") + "</ul>";
				}
				h += '<div class="bb2-h">History and comments</div>' + ((d.history || []).length ? '<ul class="bb2-hist">' + d.history.map((e) => `<li><time>${esc(PH.fmt.datetime(e.when))}</time><span><b>${esc(e.who || "")}</b> ${esc(e.what)}</span></li>`).join("") + "</ul>" : '<div class="ph-muted">No recorded changes.</div>');
			} else {
				h += '<div class="ph-notice ph-mt">Description and history are visible to the Dev Team and Projects Managers.</div>';
			}
			body.innerHTML = h;
		}).catch((e) => PH.error(body, e.message, () => { m.close(); openItem(item); }));
	}

	/* ── hover preview (board roles, same data as board.get_preview) ── */
	const preview = (() => {
		const cache = new Map();
		let card = null, timer = null, current = null;
		const close = () => {
			clearTimeout(timer);
			current = null;
			if (!card) return;
			const going = card;
			card = null;
			going.classList.remove("in");
			setTimeout(() => going.remove(), 130);
		};
		const place = (el) => {
			const box = el.getBoundingClientRect(), size = card.getBoundingClientRect();
			let top = box.bottom + 12;
			if (top + size.height > window.innerHeight - 12) top = Math.max(12, box.top - size.height - 12);
			card.style.left = Math.max(12, Math.min(box.left, window.innerWidth - size.width - 12)) + "px";
			card.style.top = top + "px";
		};
		const html = (d) => `${d.image ? `<img src="${esc(d.image)}" alt="" loading="lazy">` : ""}<div class="bb2-pv__b">
			<div class="bb2-pv__top"><span class="bb2-src">${SOURCE[d.doctype]}</span><span class="bb2-chip">${esc(d.status)}</span>${d.priority ? `<span class="bb2-chip">${esc(d.priority)}</span>` : ""}</div>
			<div class="bb2-pv__t">${esc(d.title)}</div>${d.summary ? `<p class="bb2-pv__s">${esc(d.summary)}</p>` : ""}
			<div class="bb2-pv__m">${d.module ? `<span>${esc(d.module)}</span>` : ""}${d.project ? `<span>${esc(d.project)}</span>` : ""}${d.assignees.length ? `<span>${esc(d.assignees.join(", "))}</span>` : d.by ? `<span>from ${esc(d.by)}</span>` : ""}<span class="ph-mono">${esc(d.name)}</span></div></div>`;
		const show = (el, key) => {
			const item = find(key);
			if (!item) return;
			card = document.createElement("div");
			card.className = "bb2-pv";
			card.setAttribute("role", "tooltip");
			card.innerHTML = '<div class="bb2-pv__b"><span class="ph-sk" style="height:12px;width:60%"></span><span class="ph-sk" style="height:10px;width:90%"></span></div>';
			(document.querySelector(".ph2") || document.body).appendChild(card);
			place(el);
			requestAnimationFrame(() => card && card.classList.add("in"));
			const paint = (d) => {
				if (current !== key || !card) return;
				card.innerHTML = html(d);
				place(el);
			};
			if (cache.has(key)) return paint(cache.get(key));
			PH.call(BOARD + "get_preview", { doctype: item.kind, name: item.name }, { silent: true })
				.then((d) => { cache.set(key, d); paint(d); })
				.catch(close);
		};
		if (CFG.boardRole) {
			stageEl.addEventListener("pointerover", (e) => {
				if (e.pointerType === "touch" || tlDrag) return;
				const el = e.target.closest("[data-key]");
				const key = el && el.dataset.key;
				if (!key || key === current) return;
				close();
				current = key;
				timer = setTimeout(() => show(el, key), PREVIEW_HOLD);
			});
			stageEl.addEventListener("pointerout", (e) => {
				const el = e.target.closest("[data-key]");
				if (el && el.contains(e.relatedTarget)) return;
				close();
			});
			stageEl.addEventListener("pointerdown", close);
			stageEl.addEventListener("dragstart", close);
			window.addEventListener("scroll", close, true);
		}
		return { close };
	})();
	document.addEventListener("keydown", (e) => e.key === "Escape" && preview.close());

	/* ── keyboard shortcuts ────────────────────────────────────────── */
	const viewKey = (k, label) => ({ keys: [k], label, global: true, run: () => st.set({ view: VIEW_KEYS[k] }) });
	DevKeys.init({
		title: "Backlog Board",
		hint: "#kb-hint",
		list: {
			root: "#stage", items: () => PH.$$("#stage .bb2-card, #stage tr.is-link[data-key], #stage tbody tr[data-key], #stage .bb2-tl-gut"), id: (el) => el.dataset.key,
			open: (el) => { const it = find(el.dataset.key); if (it) openItem(it); },
		},
		keys: [viewKey("1", "board view"), viewKey("2", "list view"), viewKey("3", "timeline view"), viewKey("4", "sheet view")],
	});

	/* ── boot ──────────────────────────────────────────────────────── */
	PH.onRefresh(() => load());
	PH.ready(() => {
		paintChrome();
		loadLists();
		load();
	});
})();
