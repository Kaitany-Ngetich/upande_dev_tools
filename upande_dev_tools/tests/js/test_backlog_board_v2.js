// Pure helpers of public/js/dev-v2-backlog-board.js. Run: node tests/js/test_backlog_board_v2.js
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const sandbox = {
	window: {},
	document: { getElementById: () => null }, // no #bb2: the page script only exports its helpers
	PH: { $: () => null, esc: (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"), fmt: { num: (v) => v } },
};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../../public/js/dev-v2-backlog-board.js"), "utf8"), sandbox);
const H = sandbox.window.BB2_HELPERS;
const day = (s) => H.dateOf(s);
const iso = (d) => H.iso(d);
const plain = (v) => JSON.parse(JSON.stringify(v)); // objects built inside the vm have another Object prototype

// spanOf: start..due, one standing in for a missing other, never inverted
assert.strictEqual(H.spanOf({ start: "", due: "" }), null);
assert.strictEqual(iso(H.spanOf({ start: "", due: "2026-10-12" }).start), "2026-10-12");
assert.strictEqual(iso(H.spanOf({ start: "2026-10-12", due: "" }).end), "2026-10-12");
assert.strictEqual(iso(H.spanOf({ start: "2026-10-20", due: "2026-10-10" }).end), "2026-10-20");

// shiftedSpan: whole bar moves; edges cannot cross
const a = day("2026-10-10"), z = day("2026-10-15");
let r = H.shiftedSpan(a, z, "move", 40);
assert.deepStrictEqual(plain([iso(r.start), iso(r.end)]), ["2026-11-19", "2026-11-24"]);
r = H.shiftedSpan(a, z, "start", 30);
assert.deepStrictEqual(plain([iso(r.start), iso(r.end)]), ["2026-10-15", "2026-10-15"]);
r = H.shiftedSpan(a, z, "end", -30);
assert.deepStrictEqual(plain([iso(r.start), iso(r.end)]), ["2026-10-10", "2026-10-10"]);

// grabMode: narrow bars move whole; wide bars have edge handles
assert.strictEqual(H.grabMode(2, 20), "move");
assert.strictEqual(H.grabMode(2, 100), "start");
assert.strictEqual(H.grabMode(97, 100), "end");
assert.strictEqual(H.grabMode(50, 100), "move");

// weekStart: Monday
assert.strictEqual(iso(H.weekStart(day("2026-10-14"))), "2026-10-12");
assert.strictEqual(iso(H.weekStart(day("2026-10-18"))), "2026-10-12");

// changedFields: only what differs, so an untouched status is never rewritten
assert.deepStrictEqual(plain(H.changedFields({ a: "1", b: "", c: null }, { a: "1", b: "x", c: "" })), { b: "x" });

// plainDescription: formatted text is flagged rich and left alone
assert.deepStrictEqual(plain(H.plainDescription("<p>one</p><p>two &amp; three</p>")), { text: "one\ntwo & three", rich: false });
assert.strictEqual(H.plainDescription('<p>x</p><img src="a.png">').rich, true);
assert.strictEqual(H.richDescription("a\nb<"), "a<br>b&lt;");

// groupItems
const ctx = {
	stages: [{ stage: "Todo", count: 3, late: 1 }, { stage: "Dropped", count: 0, late: 0 }],
	priorities: ["Low", "High"],
	people: { "a@x": "Ann" },
	projects: { P1: "Project One" },
};
const items = [
	{ stage: "Todo", priority: "High", assignee_ids: ["a@x"], module: "CRM", project: "P1" },
	{ stage: "Todo", priority: "", assignee_ids: [], module: "", project: "" },
	{ stage: "Todo", priority: "High", assignee_ids: ["a@x", "b@x"], module: "CRM", project: "P1" },
];
let g = H.groupItems(items, "stage", ctx);
assert.deepStrictEqual(plain(g.map((x) => [x.key, x.count, x.items.length])), [["Todo", 3, 3]]); // empty Dropped column is not shown
g = H.groupItems(items, "priority", ctx);
assert.deepStrictEqual(plain(g.map((x) => [x.label, x.items.length])), [["Low", 0], ["High", 2], ["No priority", 1]]);
g = H.groupItems(items, "assignee", ctx);
assert.deepStrictEqual(plain(g.map((x) => [x.label, x.items.length])), [["Ann", 2], ["b@x", 1], ["Unassigned", 1]]); // an item with two assignees is in both lanes
g = H.groupItems(items, "module", ctx);
assert.deepStrictEqual(plain(g.map((x) => [x.label, x.items.length])), [["CRM", 2], ["No product area", 1]]);
g = H.groupItems(items, "project", ctx);
assert.deepStrictEqual(plain(g.map((x) => x.label)), ["Project One", "No project"]);

console.log("backlog-board-v2 helpers: ok");
