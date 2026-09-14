const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");
let JSDOM, jquery;
try {
	({ JSDOM } = require("jsdom"));
	jquery = require("jquery");
} catch (e) {
	if (e.code !== "MODULE_NOT_FOUND") throw e;
	console.log("backlog-board: skipped, run `yarn install` in this app first");
	process.exit(0);
}

const SOURCE = path.join(__dirname, "../../public/js/backlog-board.js");
const STYLES = path.join(__dirname, "../../public/css/dev-portal.css");

// jsdom does not cascade, so a class defined twice with incompatible layout
// silently breaks the page and passes every render assertion. Catch it here:
// the timeline bar and the toolbar were both .dpx-bb-bar, which turned the
// toolbar into an absolutely positioned 14px strip.
function assert_no_layout_collisions() {
	const css = fs.readFileSync(STYLES, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
	const seen = {};
	let block = 0;
	for (const [, selectors, body] of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
		block += 1;
		if (selectors.includes("@")) continue;
		const absolute = /(?:^|;)\s*position\s*:\s*(?:absolute|fixed)/.test(body);
		const flow = /(?:^|;)\s*display\s*:\s*(?!none)[\w-]+/.test(body);
		if (!absolute && !flow) continue;
		for (const selector of selectors.split(",")) {
			const parts = selector.trim().split(/\s+/);
			const last = parts[parts.length - 1];
			if (!/^\.[\w-]+$/.test(last)) continue;
			const rec = (seen[last] = seen[last] || { absolute: new Set(), flow: new Set() });
			if (absolute) rec.absolute.add(block);
			if (flow) rec.flow.add(block);
		}
	}
	for (const [cls, rec] of Object.entries(seen)) {
		const clash = [...rec.absolute].some((b) => [...rec.flow].some((o) => o !== b));
		assert.ok(
			!clash,
			`${cls} is taken out of flow in one rule and laid out in another - two components share the class`
		);
	}
}

const ITEMS = [
	{
		doctype: "Task",
		name: "TASK-01",
		title: "Bucket reject reconciliation",
		status: "Working",
		stage: "In Progress",
		rank: 4,
		priority: "Urgent",
		project: "PROJ-1",
		module: "Coffee",
		start: "2026-09-07",
		end: "2026-09-19",
		movable: true,
		assignees: ["Teddy Kaitany"],
		late: false,
	},
	{
		doctype: "Issue",
		name: "ISS-02",
		title: "Label PDF prints blank pages",
		status: "Open",
		stage: "Triage",
		rank: 2,
		priority: "Medium",
		project: "PROJ-1",
		module: "Coffee",
		start: "2026-08-28",
		end: "2026-09-02",
		movable: true,
		assignees: [],
		late: true,
	},
	{
		doctype: "Request",
		name: "REQ-03",
		title: "Add vase life to quality report",
		status: "Under Review",
		stage: "Triage",
		rank: 1,
		priority: "Low",
		project: null,
		module: null,
		start: "",
		end: "",
		movable: false,
		assignees: ["Jane Doe", "Sam Otieno"],
		late: false,
	},
	{
		doctype: "Task",
		name: "TASK-04",
		title: "Ship picker fairness view",
		status: "Completed",
		stage: "Done",
		rank: 3,
		priority: "High",
		project: "PROJ-2",
		module: "QC",
		start: "2026-10-05",
		end: "2026-10-09",
		movable: true,
		assignees: ["Teddy Kaitany"],
		late: false,
	},
];

function boot() {
	const dom = new JSDOM(`<!doctype html><body><div id="root"></div></body>`, {
		pretendToBeVisual: true,
		runScripts: "outside-only",
	});
	const { window } = dom;
	const $ = jquery(window);

	const calls = [];
	window.$ = $;

	// The page loads this file before frappe-web.bundle.js, so nothing may touch
	// `frappe` at load time.
	vm.runInContext(fs.readFileSync(SOURCE, "utf8"), dom.getInternalVMContext(), {
		filename: SOURCE,
	});
	assert.ok(
		window.upande_dev_tools && window.upande_dev_tools.BacklogBoard,
		"board must define itself without frappe on the page yet"
	);

	window.frappe = {
		// website.js gives portal pages xcall (a real promise resolving to the
		// message). frappe.call there is a jqXHR posting to "/" and is not usable.
		xcall(method, args) {
			calls.push({ method, args });
			if (method.endsWith("get_modules"))
				return Promise.resolve(["Coffee", "QC", "Sales", "Stores"]);
			if (method.endsWith("get_board"))
				return Promise.resolve({
					items: ITEMS,
					total: 9,
					stages: ["Triage", "Todo", "In Progress", "In Review", "Blocked", "Done"],
				});
			return Promise.resolve({
				name: (args || {}).name,
				status: "Working",
				stage: (args || {}).stage,
			});
		},
		show_alert() {},
		utils: {
			escape_html: (v) =>
				String(v)
					.replace(/&/g, "&amp;")
					.replace(/</g, "&lt;")
					.replace(/>/g, "&gt;")
					.replace(/"/g, "&quot;"),
		},
		router: { slug: (v) => v.toLowerCase().replace(/ /g, "-") },
		datetime: { get_today: () => "2026-09-14" },
	};
	window.__ = (v) => v;

	// the sheet is jspreadsheet; record the config rather than loading 770KB of it
	window.jspreadsheet = (host, config) => {
		window.__sheet = { host, config };
		return { destroy() {} };
	};
	return { window, $, calls };
}

const settle = () => new Promise((r) => setTimeout(r, 260));

(async () => {
	assert_no_layout_collisions();

	const { window, $, calls } = boot();
	const root = window.document.getElementById("root");
	const board = new window.upande_dev_tools.BacklogBoard(root, null);

	assert.ok(
		calls.some((c) => c.method === "upande_dev_tools.api.board.get_board"),
		"the board loads its items"
	);
	assert.ok(
		!window.frappe.call,
		"the board must not use frappe.call, which portal pages do not provide"
	);
	await Promise.resolve();
	await new Promise((r) => setTimeout(r, 0));

	// ── Board view ──
	const cols = $(root).find(".dpx-bb-col");
	assert.strictEqual(cols.length, 6, "one column per stage");
	assert.strictEqual($(root).find('.dpx-bb-drop[data-stage="Triage"] .dpx-bb-card').length, 2);
	assert.strictEqual(
		$(root).find('.dpx-bb-drop[data-stage="Todo"] .dpx-bb-col-blank').length,
		1,
		"empty stage still drawn"
	);
	assert.strictEqual(
		$(root).find('.dpx-bb-card[data-id="Request:REQ-03"]').attr("draggable"),
		undefined,
		"workflow-governed requests are not draggable"
	);
	assert.strictEqual(
		$(root).find('.dpx-bb-card[data-id="Task:TASK-01"]').attr("draggable"),
		"true"
	);
	assert.strictEqual(
		$(root).find('.dpx-bb-card[data-id="Task:TASK-01"] .dpx-bb-pri.p3').length,
		1,
		"urgent reads as a filled dot, not a left rule"
	);
	assert.ok($(root).find('.dpx-bb-card[data-id="Issue:ISS-02"] .d').hasClass("late"));
	const status = $(root).find(".dpx-bb-status").text();
	assert.ok(status.includes("4 items"), "counts live in the status bar, not the header");
	assert.ok(status.includes("1 late"));
	assert.ok(status.includes("4 of 9 loaded"), "load cap is stated");
	assert.strictEqual(
		$(root).find(".dpx-bb-tb-hd .dpx-bb-badge").length,
		0,
		"the header carries no counts"
	);

	// ── Search ──
	$(root).find('[data-f="q"]').val("label").trigger("input");
	await settle();
	assert.strictEqual($(root).find(".dpx-bb-card").length, 1);
	$(root).find('[data-f="q"]').val("").trigger("input");
	await settle();

	// ── Module filter ──
	assert.ok(
		$(root).find('[data-f="module"] option').length > 1,
		"modules come from master data, not only what is on screen"
	);
	$(root).find('[data-f="module"]').val("QC").trigger("change");
	await settle();
	assert.strictEqual(
		$(root).find(".dpx-bb-card").length,
		1,
		"filtering by module narrows the board"
	);
	$(root).find('[data-f="module"]').val("").trigger("change");
	await settle();

	// ── Source filter ──
	$(root).find('[data-f="source"]').val("Issue").trigger("change");
	await settle();
	assert.strictEqual($(root).find(".dpx-bb-card").length, 1);
	$(root).find('[data-f="source"]').val("").trigger("change");
	await settle();

	// ── List view ──
	$(root).find('.dpx-bb-views button[data-view="list"]').trigger("click");
	assert.strictEqual($(root).find("tbody .dpx-bb-row").length, 4);
	assert.ok($(root).find('.dpx-bb-row:contains("Ship picker fairness")').hasClass("done"));
	assert.ok(
		$(root).find('tbody a[href="/app/issue/ISS-02"]').length === 1,
		"list links into the desk form"
	);

	// ── Per-view tools: each view carries the controls that view needs ──
	$(root).find('.dpx-bb-views button[data-view="board"]').trigger("click");
	assert.strictEqual(
		$(root).find('.bb-tool[data-tool="done"]').length,
		1,
		"board can hide done work"
	);
	$(root).find('.bb-tool[data-tool="done"]').trigger("click");
	assert.strictEqual($(root).find('.dpx-bb-drop[data-stage="Done"] .dpx-bb-card').length, 0);
	assert.strictEqual($(root).find('.bb-tool[data-tool="done"]').text(), "Show done");
	$(root).find('.bb-tool[data-tool="done"]').trigger("click");

	$(root).find('.dpx-bb-views button[data-view="list"]').trigger("click");
	assert.strictEqual(
		$(root).find('.bb-tool[data-tool="collapse"]').length,
		1,
		"list can fold its groups"
	);
	$(root).find('.bb-tool[data-tool="collapse"]').trigger("click");
	assert.strictEqual(
		$(root).find("tbody .dpx-bb-row").length,
		0,
		"collapse all folds every group"
	);
	$(root).find('.bb-tool[data-tool="expand"]').trigger("click");
	assert.ok($(root).find("tbody .dpx-bb-row").length > 0);
	$(root).find('.dpx-bb-views button[data-view="board"]').trigger("click");

	// ── Sheet ──
	$(root).find('.dpx-bb-views button[data-view="sheet"]').trigger("click");
	await new Promise((r) => setTimeout(r, 30));
	const sheet = window.__sheet;
	assert.ok(sheet, "sheet view hands its rows to jspreadsheet");
	assert.strictEqual(sheet.config.data.length, 4);
	assert.strictEqual(
		sheet.config.freezeColumns,
		2,
		"work item and stage stay pinned while you scroll"
	);
	assert.ok(sheet.config.columnSorting, "columns sort");
	assert.ok(sheet.config.lazyLoading, "only the visible rows render");
	assert.strictEqual(
		$(root).find('.bb-tool[data-tool="csv"]').length,
		1,
		"the sheet can export"
	);
	assert.strictEqual(
		sheet.config.defaultColAlign,
		"left",
		"cells read left aligned, not centred"
	);
	assert.ok(
		window.document.body.classList.contains("dpx-menu-skin"),
		"jsuites appends its menus to body, so body carries the class that styles them"
	);

	// What the work is comes first; identifiers are reference material and go last.
	assert.strictEqual(
		sheet.config.columns.map((c) => c.title).join(),
		"id,Work item,Stage,Priority,Assignee,Module,Due,Start,Status,Project,ID"
	);
	const editable = sheet.config.columns
		.map((c, i) => (c.readOnly ? null : i))
		.filter((i) => i !== null && i > 0);
	assert.strictEqual(
		editable.join(),
		"2,3,5,6,7",
		"stage, priority, module, due and start take an edit"
	);
	assert.strictEqual(
		sheet.config.columns[2].source.join(),
		"Triage,Todo,In Progress,In Review,Blocked,Done"
	);

	// Cells render their own content: chips for stage and priority, a titled
	// first column carrying the priority dot and source tag.
	const td = () => window.document.createElement("td");
	const rowOf = (id) => sheet.config.data.findIndex((r) => r[0] === id);

	const titleCell = td();
	sheet.config.updateTable(null, titleCell, 1, rowOf("Task:TASK-01"));
	assert.ok(titleCell.classList.contains("bb-title"));
	assert.strictEqual(
		titleCell.querySelectorAll(".dpx-bb-pri.p3").length,
		1,
		"urgent dot rides the title"
	);
	assert.ok(titleCell.textContent.includes("Bucket reject"));

	const stageCell = td();
	sheet.config.updateTable(null, stageCell, 2, rowOf("Task:TASK-01"));
	assert.strictEqual(
		stageCell.querySelectorAll(".dpx-bb-chip.st-in-progress").length,
		1,
		"stage reads as a chip, not a filled cell"
	);
	assert.ok(stageCell.classList.contains("bb-pick"), "editable cells show a picker chevron");

	const priCell = td();
	sheet.config.updateTable(null, priCell, 3, rowOf("Task:TASK-01"));
	assert.strictEqual(priCell.querySelectorAll(".dpx-bb-chip.pr-urgent").length, 1);

	const whoCell = td();
	sheet.config.updateTable(null, whoCell, 4, rowOf("Task:TASK-01"));
	assert.ok(whoCell.querySelector(".dpx-bb-av"), "assignee shows an avatar");

	const lockedCell = td();
	sheet.config.updateTable(null, lockedCell, 2, rowOf("Request:REQ-03"));
	assert.ok(lockedCell.classList.contains("bb-locked"));

	// a request is workflow governed, so its cells refuse the edit
	const requestRow = sheet.config.data.findIndex((r) => r[0] === "Request:REQ-03");
	assert.strictEqual(sheet.config.onbeforechange(null, null, 2, requestRow, "Done"), false);
	const taskRow = sheet.config.data.findIndex((r) => r[0] === "Task:TASK-01");
	assert.strictEqual(sheet.config.onbeforechange(null, null, 2, taskRow, "Done"), "Done");

	// ── Timeline ──
	$(root).find('.dpx-bb-views button[data-view="timeline"]').trigger("click");
	const rows = $(root).find(".dpx-bb-tl-row");
	assert.strictEqual(rows.length, 3, "only dated items are plotted");
	assert.strictEqual(
		$(root).find(".dpx-bb-today").length,
		1,
		"today is marked inside the range"
	);
	assert.ok($(root).find(".dpx-bb-mo").length >= 2, "month bands span Aug through Oct");

	// Geometry: first row starts left of the second, and bars never run backwards.
	const lefts = rows.toArray().map((r) => parseInt($(r).find(".dpx-bb-tlbar").css("left"), 10));
	const widths = rows
		.toArray()
		.map((r) => parseInt($(r).find(".dpx-bb-tlbar").css("width"), 10));
	assert.deepStrictEqual(
		lefts,
		[...lefts].sort((a, b) => a - b),
		"rows sorted by start date"
	);
	assert.ok(
		widths.every((w) => w >= 5),
		"every bar has a visible width"
	);
	assert.ok($(root).find(".dpx-bb-tl-row .dpx-bb-tlbar.done").length === 1);
	assert.ok($(root).find(".dpx-bb-tl-row .dpx-bb-tlbar.late").length === 1);

	// ── Empty state when the filter excludes everything ──
	$(root).find('[data-f="q"]').val("zzzz").trigger("input");
	await settle();
	assert.ok($(root).find(".dpx-bb-blank h3").text().length > 0);

	// ── Drag moves an item optimistically ──
	$(root).find('[data-f="q"]').val("").trigger("input");
	await settle();
	$(root).find('.dpx-bb-views button[data-view="board"]').trigger("click");
	board.move("Task:TASK-01", "Blocked");
	assert.strictEqual(board.items.find((i) => i.name === "TASK-01").stage, "Blocked");
	assert.strictEqual(calls[calls.length - 1].method, "upande_dev_tools.api.board.set_stage");

	// ── Dragging a bar reschedules it ──
	$(root).find('.dpx-bb-views button[data-view="timeline"]').trigger("click");
	await settle();
	const bar = $(root).find('.dpx-bb-tlbar[data-id="Task:TASK-01"]');
	assert.strictEqual(bar.length, 1);
	assert.ok(bar.attr("data-movable") !== undefined, "task bars can be moved");
	assert.strictEqual(
		$(root).find('.dpx-bb-tlbar[data-id="Request:REQ-03"]').attr("data-movable"),
		undefined,
		"requests are not dragged around the plan"
	);

	// grab the middle of the bar and push it four days right
	const held = bar[0];
	held.getBoundingClientRect = () => ({ left: 100, right: 200, top: 0, bottom: 17 });
	Object.defineProperty(held, "offsetLeft", { value: 100, configurable: true });
	Object.defineProperty(held, "offsetWidth", { value: 100, configurable: true });
	const ZOOM_W = 15;
	bar.trigger($.Event("pointerdown", { button: 0, clientX: 150 }));
	const move = new window.MouseEvent("pointermove", { clientX: 150 + 4 * ZOOM_W });
	window.document.dispatchEvent(move);
	window.document.dispatchEvent(new window.MouseEvent("pointerup"));
	await settle();

	const moved = calls.filter(
		(c) => c.method.endsWith("set_field") && ["start", "end"].includes(c.args.field)
	);
	assert.strictEqual(moved.length, 2, "moving a bar writes both dates");
	assert.strictEqual(moved[0].args.value, "2026-09-11", "start shifts by the days dragged");
	assert.strictEqual(moved[1].args.value, "2026-09-23", "and so does due, by the same amount");

	// ── Editing a sheet cell saves (mutates state, so it runs last) ──
	$(root).find('.dpx-bb-views button[data-view="sheet"]').trigger("click");
	await new Promise((r) => setTimeout(r, 30));
	const cfg = window.__sheet.config;
	const row = cfg.data.findIndex((r) => r[0] === "Task:TASK-04");
	cfg.onchange(null, null, 3, row, "Low");
	assert.strictEqual(calls[calls.length - 1].method, "upande_dev_tools.api.board.set_field");
	assert.strictEqual(calls[calls.length - 1].args.field, "priority");
	assert.strictEqual(calls[calls.length - 1].args.value, "Low");

	// an unchanged value must not fire a save
	const before = calls.length;
	cfg.onchange(null, null, 2, row, cfg.data[row][2]);
	assert.strictEqual(calls.length, before, "re-entering the same value saves nothing");

	console.log("backlog-board: all checks passed");
})().catch((e) => {
	console.error(e);
	process.exit(1);
});
