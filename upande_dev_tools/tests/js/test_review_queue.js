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
	console.log("review-queue: skipped, run `yarn install` in this app first");
	process.exit(0);
}

const SOURCE = path.join(__dirname, "../../public/js/review-queue.js");

const REQUESTS = [
	{
		name: "REQ-01",
		title: "Add a supervisor column",
		request_type: "Feature",
		product_area: "Stores",
		raised_by_user: "jimmy@upande.com",
		priority: "Medium",
		project: null,
		creation: new Date(Date.now() - 9 * 86400000).toISOString().replace("T", " ").slice(0, 19),
	},
	{
		name: "REQ-02",
		title: "Weekly quality digest",
		request_type: "Chore",
		product_area: "QC",
		raised_by_user: "judah@upande.com",
		priority: "Low",
		project: "PROJ-1",
		creation: new Date().toISOString().replace("T", " ").slice(0, 19),
	},
];
const PROJECTS = [{ name: "PROJ-1", project_name: "Dev Tools Demo" }];
const PEOPLE = [{ name: "dev@upande.com", full_name: "Mark" }];

function boot() {
	const dom = new JSDOM(`<!doctype html><body><div id="root"></div></body>`, {
		pretendToBeVisual: true,
		runScripts: "outside-only",
	});
	const { window } = dom;
	const $ = jquery(window);
	const calls = [];
	window.$ = $;

	vm.runInContext(fs.readFileSync(SOURCE, "utf8"), dom.getInternalVMContext(), {
		filename: SOURCE,
	});
	assert.ok(
		window.upande_dev_tools && window.upande_dev_tools.ReviewQueue,
		"page must define itself before frappe loads"
	);

	window.frappe = {
		xcall(method, args) {
			calls.push({ method, args });
			if (method.endsWith("get_review_queue")) return Promise.resolve(REQUESTS);
			if (method.endsWith("get_list")) return Promise.resolve(PROJECTS);
			if (method.endsWith("get_assignable_users")) return Promise.resolve(PEOPLE);
			return Promise.resolve({
				name: args.name,
				task: "TASK-9",
				workflow_state: "Scheduled",
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
	};
	window.__ = (v, args) => String(v).replace(/\{(\d+)\}/g, (_, i) => (args || [])[i]);
	return { window, $, calls };
}

(async () => {
	const { window, $, calls } = boot();
	const root = window.document.getElementById("root");
	new window.upande_dev_tools.ReviewQueue(root);
	await new Promise((r) => setTimeout(r, 40));

	// Every row must actually render - a method lost in an edit shows up here.
	assert.strictEqual(
		$(root).find(".rq-table tbody tr").length,
		2,
		"one row per pending request"
	);
	assert.strictEqual($(root).find("select.rq-project").length, 2);
	assert.strictEqual($(root).find("select.rq-assignee").length, 2);
	assert.strictEqual($(root).find(".rq-btn.accept").length, 2);
	assert.strictEqual($(root).find(".dpx-bb-blank").length, 0, "no failure state on a good load");

	// A queue is about waiting: age is shown, and a long wait is flagged.
	const ages = $(root)
		.find(".rq-age")
		.toArray()
		.map((el) => $(el).text());
	assert.ok(ages.includes("today"), "a request raised today reads as today");
	assert.ok(
		ages.some((a) => a.endsWith("d")),
		"older requests read in days"
	);
	assert.strictEqual($(root).find(".rq-age.hot").length, 1, "a wait past a week is flagged");
	// both the longest-wait and the over-a-week tiles turn on for a 9 day old request
	assert.strictEqual($(root).find(".rq-stat.warn").length, 2, "and surfaces in the stats");
	assert.ok($(root).find(".rq-stats").text().includes("9d"), "longest wait is stated");

	// Accept needs a project; the first request has none selected.
	const firstRow = $(root).find('tr[data-name="REQ-01"]');
	firstRow.find(".rq-btn.accept").trigger("click");
	assert.strictEqual(
		calls.filter((c) => c.method.endsWith("accept_request")).length,
		0,
		"accepting without a project does not call the server"
	);

	// With a project chosen it accepts, and carries the assignee.
	firstRow.find(".rq-project").val("PROJ-1");
	firstRow.find(".rq-assignee").val("dev@upande.com");
	firstRow.find(".rq-btn.accept").trigger("click");
	const accept = calls[calls.length - 1];
	assert.strictEqual(accept.method, "upande_dev_tools.api.requests.accept_request");
	assert.strictEqual(accept.args.project, "PROJ-1");
	assert.strictEqual(accept.args.assign_to, "dev@upande.com");

	await new Promise((r) => setTimeout(r, 20));
	assert.strictEqual(
		$(root).find(".rq-table tbody tr").length,
		1,
		"an accepted request leaves the queue"
	);

	// Reject is destructive, so the first click only arms it.
	const second = $(root).find('tr[data-name="REQ-02"]');
	const before = calls.length;
	second.find(".rq-btn.reject").trigger("click");
	assert.strictEqual(calls.length, before, "one click arms, it does not reject");
	assert.ok(second.find(".rq-btn.reject").hasClass("armed"));
	second.find(".rq-btn.reject").trigger("click");
	assert.strictEqual(
		calls[calls.length - 1].method,
		"upande_dev_tools.api.requests.triage_request"
	);
	assert.strictEqual(calls[calls.length - 1].args.action, "Reject");

	console.log("review-queue: all checks passed");
})().catch((e) => {
	console.error(e);
	process.exit(1);
});
