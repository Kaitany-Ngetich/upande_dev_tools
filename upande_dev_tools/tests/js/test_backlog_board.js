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

const ITEMS = [
	{
		doctype: "Task", name: "TASK-01", title: "Bucket reject reconciliation", status: "Working",
		stage: "In Progress", rank: 4, priority: "Urgent", project: "PROJ-1",
		start: "2026-09-07", end: "2026-09-19", movable: true, assignees: ["Teddy Kaitany"], late: false,
	},
	{
		doctype: "Issue", name: "ISS-02", title: "Label PDF prints blank pages", status: "Open",
		stage: "Triage", rank: 2, priority: "Medium", project: "PROJ-1",
		start: "2026-08-28", end: "2026-09-02", movable: true, assignees: [], late: true,
	},
	{
		doctype: "Request", name: "REQ-03", title: "Add vase life to quality report", status: "Under Review",
		stage: "Triage", rank: 1, priority: "Low", project: null,
		start: "", end: "", movable: false, assignees: ["Jane Doe", "Sam Otieno"], late: false,
	},
	{
		doctype: "Task", name: "TASK-04", title: "Ship picker fairness view", status: "Completed",
		stage: "Done", rank: 3, priority: "High", project: "PROJ-2",
		start: "2026-10-05", end: "2026-10-09", movable: true, assignees: ["Teddy Kaitany"], late: false,
	},
];

function boot() {
	const dom = new JSDOM(`<!doctype html><body><div id="root"></div></body>`, { pretendToBeVisual: true, runScripts: "outside-only" });
	const { window } = dom;
	const $ = jquery(window);

	const calls = [];
	window.$ = $;
	window.frappe = {
		provide(namespace) {
			namespace.split(".").reduce((obj, key) => (obj[key] = obj[key] || {}), window);
		},
		call(opts) {
			calls.push(opts);
			return Promise.resolve({ message: { items: ITEMS, total: 9, stages: ["Triage", "Todo", "In Progress", "In Review", "Blocked", "Done"] } });
		},
		show_alert() {},
		utils: { escape_html: (v) => String(v).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;") },
		router: { slug: (v) => v.toLowerCase().replace(/ /g, "-") },
		datetime: { get_today: () => "2026-09-14" },
	};
	window.__ = (v) => v;

	vm.runInContext(fs.readFileSync(SOURCE, "utf8"), dom.getInternalVMContext(), { filename: SOURCE });
	return { window, $, calls };
}

(async () => {
	const { window, $, calls } = boot();
	const root = window.document.getElementById("root");
	const board = new window.upande_dev_tools.BacklogBoard(root, null);

	assert.strictEqual(calls[0].method, "upande_dev_tools.api.board.get_board");
	await Promise.resolve();
	await new Promise((r) => setTimeout(r, 0));

	// ── Board view ──
	const cols = $(root).find(".dpx-bb-col");
	assert.strictEqual(cols.length, 6, "one column per stage");
	assert.strictEqual($(root).find('.dpx-bb-drop[data-stage="Triage"] .dpx-bb-card').length, 2);
	assert.strictEqual($(root).find('.dpx-bb-drop[data-stage="Todo"] .dpx-bb-col-blank').length, 1, "empty stage still drawn");
	assert.strictEqual($(root).find('.dpx-bb-card[data-id="Request:REQ-03"]').attr("draggable"), undefined, "workflow-governed requests are not draggable");
	assert.strictEqual($(root).find('.dpx-bb-card[data-id="Task:TASK-01"]').attr("draggable"), "true");
	assert.ok($(root).find('.dpx-bb-card[data-id="Task:TASK-01"]').hasClass("p3"), "urgent gets the heaviest rule");
	assert.ok($(root).find('.dpx-bb-card[data-id="Issue:ISS-02"] .d').hasClass("late"));
	assert.ok($(root).find(".dpx-bb-count").text().includes("4 of 9 loaded"), "load cap is stated");

	// ── Search ──
	$(root).find('[data-f="q"]').val("label").trigger("input");
	assert.strictEqual($(root).find(".dpx-bb-card").length, 1);
	$(root).find('[data-f="q"]').val("").trigger("input");

	// ── Source filter ──
	$(root).find('[data-f="source"]').val("Issue").trigger("change");
	assert.strictEqual($(root).find(".dpx-bb-card").length, 1);
	$(root).find('[data-f="source"]').val("").trigger("change");

	// ── List view ──
	$(root).find('.dpx-bb-views button[data-view="list"]').trigger("click");
	assert.strictEqual($(root).find("tbody .dpx-bb-row").length, 4);
	assert.ok($(root).find('.dpx-bb-row:contains("Ship picker fairness")').hasClass("done"));
	assert.ok(
		$(root).find('tbody a[href="/app/issue/ISS-02"]').length === 1,
		"list links into the desk form"
	);

	// ── Timeline ──
	$(root).find('.dpx-bb-views button[data-view="timeline"]').trigger("click");
	const rows = $(root).find(".dpx-bb-tl-row");
	assert.strictEqual(rows.length, 3, "only dated items are plotted");
	assert.strictEqual($(root).find(".dpx-bb-today").length, 1, "today is marked inside the range");
	assert.ok($(root).find(".dpx-bb-mo").length >= 2, "month bands span Aug through Oct");

	// Geometry: first row starts left of the second, and bars never run backwards.
	const lefts = rows.toArray().map((r) => parseInt($(r).find(".dpx-bb-bar").css("left"), 10));
	const widths = rows.toArray().map((r) => parseInt($(r).find(".dpx-bb-bar").css("width"), 10));
	assert.deepStrictEqual(lefts, [...lefts].sort((a, b) => a - b), "rows sorted by start date");
	assert.ok(widths.every((w) => w >= 5), "every bar has a visible width");
	assert.ok($(root).find(".dpx-bb-tl-row .dpx-bb-bar.done").length === 1);
	assert.ok($(root).find(".dpx-bb-tl-row .dpx-bb-bar.late").length === 1);

	// ── Empty state when the filter excludes everything ──
	$(root).find('[data-f="q"]').val("zzzz").trigger("input");
	assert.ok($(root).find(".dpx-bb-blank h3").text().length > 0);

	// ── Drag moves an item optimistically ──
	$(root).find('[data-f="q"]').val("").trigger("input");
	$(root).find('.dpx-bb-views button[data-view="board"]').trigger("click");
	board.move("Task:TASK-01", "Blocked");
	assert.strictEqual(board.items.find((i) => i.name === "TASK-01").stage, "Blocked");
	assert.strictEqual(calls[calls.length - 1].method, "upande_dev_tools.api.board.set_stage");

	console.log("backlog-board: all checks passed");
})().catch((e) => {
	console.error(e);
	process.exit(1);
});
