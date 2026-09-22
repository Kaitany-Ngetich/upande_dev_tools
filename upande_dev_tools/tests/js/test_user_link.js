const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

let JSDOM;
try {
	({ JSDOM } = require("jsdom"));
} catch (e) {
	if (e.code !== "MODULE_NOT_FOUND") throw e;
	console.log("user-link: skipped, run `yarn install` in this app first");
	process.exit(0);
}

const SOURCE = path.join(__dirname, "../../public/js/user-link.js");

// Two people deliberately share a display name. Picking by label cannot tell them apart,
// which is the whole reason this control round-trips the email instead.
const PEOPLE = [
	{ name: "brian@upande.com", full_name: "Brian" },
	{ name: "brian.k@upande.com", full_name: "Brian" },
	{ name: "judah@upande.com", full_name: "Mark Judah" },
	{ name: "teresia@upande.com", full_name: "Tess" },
];

function boot() {
	const dom = new JSDOM(`<!doctype html><body><div id="root"></div></body>`, {
		pretendToBeVisual: true,
		runScripts: "outside-only",
	});
	const { window } = dom;
	// jsdom has no layout, so it ships no scrollIntoView; every real browser does.
	window.Element.prototype.scrollIntoView = function () {};
	window.frappe = {
		utils: { escape_html: (v) => String(v).replace(/[&<>"]/g, (c) => `&#${c.charCodeAt(0)};`) },
		xcall: () => Promise.resolve(PEOPLE),
	};
	window.__ = (v, args) => String(v).replace(/\{(\d+)\}/g, (_, i) => (args || [])[i]);
	vm.runInContext(fs.readFileSync(SOURCE, "utf8"), dom.getInternalVMContext(), { filename: SOURCE });
	window.upande_dev_tools.seed_users(PEOPLE);
	return window;
}

function mount(window, opts) {
	const root = window.document.getElementById("root");
	root.innerHTML = window.upande_dev_tools.user_link_html(opts || { name: "assign_to" });
	return {
		box: root.querySelector(".udt-ul"),
		search: root.querySelector(".udt-ul-search"),
		hidden: root.querySelector(".udt-ul-value"),
		opts: () => [...root.querySelectorAll(".udt-ul-opt")],
	};
}

// The control debounces its filtering, so every caller has to wait it out.
async function type(window, search, text) {
	search.value = text;
	search.dispatchEvent(new window.Event("input", { bubbles: true }));
	await new Promise((r) => setTimeout(r, 90));
}

function key(window, search, k) {
	const e = new window.KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true });
	search.dispatchEvent(e);
	return e;
}

(async () => {
	const window = boot();

	// ── Opening shows everyone, not a filtered-down subset ──
	let ui = mount(window);
	ui.search.dispatchEvent(new window.Event("focusin", { bubbles: true }));
	assert.strictEqual(ui.opts().length, PEOPLE.length, "focus lists every person");
	assert.strictEqual(ui.box.className.includes("open"), true, "focus opens the menu");
	assert.strictEqual(
		ui.search.getAttribute("aria-expanded"),
		"true",
		"screen readers are told it expanded"
	);

	// ── Searching matches the name and the email, in any word order ──
	await type(window, ui.search, "judah");
	assert.strictEqual(ui.opts().length, 1, "a name substring narrows to one");
	await type(window, ui.search, "tere");
	assert.strictEqual(
		ui.opts()[0].dataset.email,
		"teresia@upande.com",
		"an email substring finds someone whose name shares nothing with it"
	);
	await type(window, ui.search, "brian");
	assert.strictEqual(ui.opts().length, 2, "both people sharing a name stay listed separately");
	await type(window, ui.search, "zzz-nobody");
	assert.strictEqual(ui.opts().length, 0, "no matches renders no options");
	assert.ok(
		ui.box.querySelector(".udt-ul-note"),
		"and says so rather than showing an empty box"
	);

	// ── Keyboard: arrow to the second Brian, Enter picks that exact person ──
	await type(window, ui.search, "brian");
	key(window, ui.search, "ArrowDown");
	assert.strictEqual(
		ui.opts()[1].className.includes("active"),
		true,
		"arrow moves the highlight"
	);
	const enter = key(window, ui.search, "Enter");
	assert.strictEqual(enter.defaultPrevented, true, "Enter is swallowed while choosing");
	assert.strictEqual(
		ui.hidden.value,
		"brian.k@upande.com",
		"the SECOND Brian is stored - by email, so a shared display name cannot pick the wrong one"
	);
	assert.strictEqual(ui.search.value, "Brian", "the box reads back the person's name");
	assert.strictEqual(ui.box.className.includes("open"), false, "choosing closes the menu");

	// Enter with nothing highlighted must stay unswallowed, or it could never submit a form.
	await type(window, ui.search, "zzz-nobody");
	assert.strictEqual(
		key(window, ui.search, "Enter").defaultPrevented,
		false,
		"Enter still submits when it is not choosing anyone"
	);

	// ── Typing over a choice clears it, so a half-typed name is never submitted as the old one ──
	ui = mount(window, { name: "assign_to", value: "judah@upande.com" });
	assert.strictEqual(ui.search.value, "Mark Judah", "an existing value renders as the name");
	assert.strictEqual(ui.hidden.value, "judah@upande.com", "…while the email stays underneath");
	ui.search.dispatchEvent(new window.Event("focusin", { bubbles: true }));
	await type(window, ui.search, "Mark Jud");
	assert.strictEqual(ui.hidden.value, "", "editing the text drops the stale selection");

	// ── change fires on the real field, so form/row handlers see it ──
	ui = mount(window);
	let fired = 0;
	ui.hidden.addEventListener("change", () => (fired += 1));
	ui.search.dispatchEvent(new window.Event("focusin", { bubbles: true }));
	await type(window, ui.search, "tess");
	const md = new window.MouseEvent("mousedown", { bubbles: true, cancelable: true });
	ui.opts()[0].dispatchEvent(md);
	assert.strictEqual(ui.hidden.value, "teresia@upande.com", "clicking an option picks it");
	assert.strictEqual(md.defaultPrevented, true, "mousedown is swallowed so blur cannot race it");
	assert.strictEqual(fired, 1, "a change event is dispatched on the hidden field");

	// ── Escape closes the menu without clearing, and without reaching the dialog behind it ──
	// modal.js binds its Escape handler to document as well, so this is the real check: a
	// later document listener must not see the key, or the whole dialog closes with the menu.
	let dialog_saw_escape = 0;
	window.document.addEventListener("keydown", (e) => {
		if (e.key === "Escape") dialog_saw_escape += 1;
	});
	ui.search.dispatchEvent(new window.Event("focusin", { bubbles: true }));
	key(window, ui.search, "Escape");
	assert.strictEqual(ui.box.className.includes("open"), false, "Escape closes the menu");
	assert.strictEqual(dialog_saw_escape, 0, "the dialog behind it never sees that Escape");
	assert.strictEqual(ui.hidden.value, "teresia@upande.com", "Escape keeps the chosen person");

	// A second Escape, with the menu already shut, has to reach the dialog so it can close.
	key(window, ui.search, "Escape");
	assert.strictEqual(dialog_saw_escape, 1, "once the menu is shut, Escape passes through");

	console.log("user-link: all checks passed");
})();
