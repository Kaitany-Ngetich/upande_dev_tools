/* Copyright (c) 2026, Upande and contributors
 *
 * PM Console (www/pm-dashboard-v2.html). One idea: every number opens a list, every list row has an
 * action. A panel with no decision or action does not exist.
 *
 * READS  : api.v2.pm_dashboard (manager roles only, enforced there): get_pm_console (every list, one
 *          read), get_pm_person_tasks, get_pm_item. Each row carries `actions`, what the caller may do.
 * WRITES : the same whitelisted endpoints the Review Queue and the Backlog use, unchanged, so the role
 *          rules, validation, audit trail and notifications stay exactly as they are:
 *            api.requests.accept_request    Accept (approve + schedule + assign; creates the Task)
 *            api.requests.triage_request    Defer / Reject (a reason is required)
 *            api.requests.promote_to_task   Assign an approved request (then reassign_task names people)
 *            api.requests.reassign_task     Reassign, new due date (current people + complete_by)
 *            api.requests.update_task_status  Mark done (Completed), Move to Pending (Pending Review)
 * After every action the whole page is read again; nothing is cached across actions.
 */
(function () {
	"use strict";
	const API = "upande_dev_tools.api.v2.pm_dashboard.";
	const REQ = "upande_dev_tools.api.requests.";
	const TABS = [
		["decide", "Decide"],
		["late", "Late"],
		["no_owner", "No owner"],
		["stuck", "Stuck"],
		["people", "People"],
		["projects", "Projects"],
	];
	const STRIP = [
		["decide", "Waiting for a decision"],
		["late", "Overdue"],
		["no_owner", "No owner"],
		["stuck", "Gone quiet"],
	];
	const EMPTY = {
		decide: ["Nothing waiting for a decision", "Every request has an answer."],
		late: ["Nothing is overdue", "No open task is past its due date."],
		no_owner: ["Everything has an owner", "No open task or approved request is waiting for a person."],
		stuck: ["Nothing has gone quiet", "Every task in progress has moved recently."],
		people: ["No assigned work", "Nobody holds an open task in this view."],
		projects: ["No projects", "There are no projects in this view."],
	};
	const DEFINITIONS = {
		decide: "Every request under review, with or without a project, oldest first. Age is whole days since it was raised.",
		late: "Open tasks whose due date is before today, grouped by the first person on the task. A task due today is not late.",
		no_owner: "Open tasks with nobody assigned, plus approved requests that no one has scheduled yet.",
		stuck: "Tasks in progress with no change for 14 days or more, plus issues on hold.",
		people: "A shared task counts for each person on it. Carrying a lot means more than twice the team median of open tasks.",
		projects: "Worth a look: more than 20% of open tasks are overdue, or nothing changed for 14 days. Click a project to open its board.",
	};
	const FILTER_KEYS = ["project", "area", "priority", "assignee"];
	const DEFAULT_DAYS = "30";
	const DAY_CHOICES = [7, 30, 90]; // same set the server accepts for "delivered in the last N days"
	const FALLBACK_PRIORITY = "Medium";
	const QUICK_DUE_DAYS = [["In a week", 7], ["In two weeks", 14], ["In a month", 30]];
	const ERRORS = {
		project: "Pick a project first.",
		assign: "Pick who this goes to first.",
		due: "Set a due date first.",
		comment: "Give a reason first.",
	};
	const BOARD = "/backlog-board-v2?project=";

	const st = PH.state({ tab: "decide", project: "", area: "", priority: "", assignee: "", q: "", days: DEFAULT_DAYS });
	const $ = PH.$;
	const esc = PH.esc;
	const plural = (n, w) => n + " " + w + (n === 1 ? "" : "s");
	let data = null;
	let seq = 0;
	const selected = new Set();

	/* ------------------------------------------------------------------ rows and lookups */
	const listOf = (tab) => (tab === "people" ? data.people.rows : data[tab]);
	const itemRows = () => ["decide", "late", "no_owner", "stuck"].flatMap((t) => data[t]);
	const keyOf = (r) => r.kind + ":" + r.name;
	const find = (key) => itemRows().find((r) => keyOf(r) === key);
	const hay = (r) => [r.name, r.title, r.requester, r.project_label, r.area, r.type, (r.assignees || []).join(" "), r.label, r.owner, r.user].join(" ").toLowerCase();
	function visible(tab) {
		const q = st.get("q").toLowerCase();
		return listOf(tab).filter((r) => !q || hay(r).includes(q));
	}
	/** The selected tasks, each once (a task can be on more than one list). */
	const selectedTasks = () => [...new Map(itemRows().filter((r) => r.kind === "task" && selected.has(r.name)).map((r) => [r.name, r])).values()];
	const docType = (r) => (r.kind === "task" ? "Task" : r.kind === "issue" ? "Issue" : "Request");

	/* ------------------------------------------------------------------ load */
	function args() {
		const s = st.get();
		return { project: s.project, area: s.area, priority: s.priority, assignee: s.assignee, days: s.days };
	}
	function load() {
		const my = ++seq;
		if (!data) PH.skeleton("#body", "rows", 6);
		return PH.call(API + "get_pm_console", args(), { silent: true })
			.then((d) => {
				if (my !== seq) return;
				data = d;
				const names = new Set(d.late.concat(d.no_owner, d.stuck).map((r) => r.name));
				[...selected].forEach((n) => names.has(n) || selected.delete(n));
				fillOptions();
				render();
				PH.markUpdated();
			})
			.catch((e) => {
				if (my !== seq) return;
				PH.error("#body", e.message || "The console could not be loaded.", load);
			});
	}
	function fillOptions() {
		const o = data.options;
		PH.options("#f-project", o.projects, st.get("project"));
		PH.options("#f-area", o.areas, st.get("area"));
		PH.options("#f-priority", o.priorities, st.get("priority"));
		PH.options("#f-assignee", o.assignees, st.get("assignee"));
	}

	/* ------------------------------------------------------------------ painting */
	function render() {
		if (!data) return;
		paintStrip();
		paintTabs();
		paintSpark();
		paintBody();
		const filtered = FILTER_KEYS.some((k) => st.get(k)) || st.get("q");
		$("#f-clear").hidden = !filtered;
		$("#foot").textContent = "As of " + PH.fmt.date(data.today) + ". " + DEFINITIONS[st.get("tab")] + (data.truncated.length ? " Showing the first 1000 of " + data.truncated.join(", ") + "." : "");
	}
	function paintStrip() {
		PH.set("#strip", STRIP.map(([tab, label]) => {
			const n = data.counts[tab];
			return '<button type="button" class="pm-count' + (n ? "" : " is-zero") + (st.get("tab") === tab ? " is-on" : "") + '" data-tab="' + tab + '"><b>' + n + "</b><span>" + esc(label) + "</span></button>";
		}).join(""));
	}
	function paintTabs() {
		const cur_ = st.get("tab");
		PH.set("#tabs", TABS.map(([tab, label]) => '<button class="ph-tab' + (tab === cur_ ? " is-on" : "") + '" role="tab" aria-selected="' + (tab === cur_) + '" data-tab="' + tab + '">' + esc(label) + ' <span class="ph-tab__count">' + data.counts[tab] + "</span></button>").join(""));
	}
	function paintSpark() {
		const w = data.weekly;
		const max = Math.max(1, ...w.map((x) => Math.max(x.raised, x.delivered)));
		const pts = (k) => w.map((x, i) => (i * (200 / (w.length - 1))).toFixed(1) + "," + (38 - (x[k] / max) * 34).toFixed(1)).join(" ");
		const sum = (k) => w.reduce((a, x) => a + x[k], 0);
		PH.set("#spark", '<svg viewBox="0 0 200 42" width="200" height="42" role="img" aria-label="Weekly tasks raised and finished, last 12 weeks"><polyline class="pm-spark__raised" points="' + pts("raised") + '"/><polyline class="pm-spark__done" points="' + pts("delivered") + '"/></svg><span><b>' + sum("delivered") + "</b> finished and <b>" + sum("raised") + "</b> raised in 12 weeks</span>");
	}
	function paintBody() {
		const tab = st.get("tab");
		const rows = visible(tab);
		paintBulk();
		if (!rows.length) {
			const [t, x] = EMPTY[tab];
			PH.empty("#body", listOf(tab).length ? "Nothing matches the search" : t, listOf(tab).length ? "Try a different word." : x, "inbox");
			return;
		}
		const html = { decide: decideHtml, late: lateHtml, no_owner: plainHtml, stuck: plainHtml, people: peopleHtml, projects: projectsHtml }[tab](rows);
		PH.set("#body", html);
	}

	/* a row's buttons: only what the server says the caller may do */
	const btn = (act, key, label, cls) => '<button type="button" class="ph-btn ph-btn--sm' + (cls ? " " + cls : "") + '" data-act="' + act + '" data-key="' + esc(key) + '">' + esc(label) + "</button>";
	function actions(r, tab) {
		const can = (a) => r.actions.includes(a);
		const key = keyOf(r);
		const out = [];
		if (r.kind === "request") {
			if (can("accept")) out.push(btn("accept", key, "Accept", "ph-btn--primary"));
			if (can("defer")) out.push(btn("defer", key, "Defer"));
			if (can("reject")) out.push(btn("reject", key, "Reject"));
		} else if (r.kind === "approved") {
			if (can("schedule")) out.push(btn("schedule", key, "Assign", "ph-btn--primary"));
		} else if (r.kind === "task") {
			const none = !r.assignee_ids.length;
			if (can("reassign")) out.push(btn("reassign", key, none ? "Assign" : "Reassign", none ? "ph-btn--primary" : ""));
			if (can("due") && !none && tab !== "stuck") out.push(btn("due", key, "New due date"));
			if (can("done") && tab === "late") out.push(btn("done", key, "Mark done"));
			if (can("pending") && tab === "stuck") out.push(btn("pending", key, "Move to Pending"));
		}
		out.push(btn("open", key, "Open", "ph-btn--ghost"));
		return '<div class="pm-acts">' + out.join("") + "</div>";
	}
	const titleLink = (r) => '<button type="button" class="pm-title" data-act="open" data-key="' + esc(keyOf(r)) + '">' + esc(r.title || r.name) + "</button>";
	const sub = (parts) => '<div class="pm-sub">' + parts.filter(Boolean).map(esc).join(" · ") + "</div>";
	const fact = (text, warn) => '<div class="pm-fact' + (warn ? " is-warn" : "") + '">' + text + "</div>";
	const check = (r) => (r.kind === "task" && r.actions.includes("reassign") ? '<input type="checkbox" class="ph-check" data-sel="' + esc(r.name) + '" aria-label="Select ' + esc(r.name) + '"' + (selected.has(r.name) ? " checked" : "") + ">" : '<span class="pm-nocheck"></span>');
	const row = (r, tab, lead, main, right) => '<div class="pm-row" data-key="' + esc(keyOf(r)) + '">' + lead + '<div class="pm-main">' + main + "</div>" + right + actions(r, tab) + "</div>";

	function decideHtml(rows) {
		return rows.map((r) => row(r, "decide", "", titleLink(r) + sub([r.name, "from " + r.requester, r.type, r.area, r.project_label]), fact("<b>" + plural(r.age_days, "day") + "</b> waiting", r.age_days >= 14))).join("");
	}
	function lateHtml(rows) {
		const groups = new Map();
		rows.forEach((r) => {
			const k = r.assignee_ids[0] || "";
			if (!groups.has(k)) groups.set(k, { name: r.assignees[0] || "Nobody", rows: [] });
			groups.get(k).rows.push(r);
		});
		return [...groups.values()].map((g) => {
			const names = g.rows.map((r) => r.name);
			const all = names.every((n) => selected.has(n));
			return '<div class="pm-group"><label class="pm-group__head"><input type="checkbox" class="ph-check" data-selgroup="' + esc(names.join("|")) + '"' + (all ? " checked" : "") + ' aria-label="Select all for ' + esc(g.name) + '"><b>' + esc(g.name) + "</b><span>" + plural(g.rows.length, "late task") + ", the oldest " + plural(g.rows[0].days_late, "day") + " late</span></label>"
				+ g.rows.map((r) => row(r, "late", check(r), titleLink(r) + sub([r.name, r.project_label, r.priority, r.assignees.length > 1 ? "with " + r.assignees.slice(1).join(", ") : ""]), fact("<b>" + plural(r.days_late, "day") + "</b> late<small>due " + PH.fmt.date(r.due, true) + "</small>", true))).join("") + "</div>";
		}).join("");
	}
	function plainHtml(rows) {
		const tab = st.get("tab");
		return rows.map((r) => {
			let right;
			if (r.kind === "approved") right = fact("<b>" + plural(r.age_days, "day") + "</b> approved, not scheduled");
			else if (tab === "stuck") right = fact("<b>" + plural(r.quiet_days, "day") + "</b> no change<small>" + esc(r.status) + "</small>", true);
			else right = fact(r.due ? "due " + PH.fmt.date(r.due, true) : "no due date", r.days_late > 0);
			const who = r.kind === "approved" ? "from " + r.requester : r.assignees.join(", ");
			return row(r, tab, check(r), titleLink(r) + sub([r.name, r.kind === "approved" ? "approved request" : r.kind === "issue" ? "issue on hold" : "", who, r.project_label, r.priority]), right);
		}).join("");
	}
	function peopleHtml(rows) {
		const days = st.get("days");
		const head = '<div class="pm-phead"><span>Delivered in the last <select class="ph-select pm-days" id="f-days" aria-label="Delivered range">' + DAY_CHOICES.map((d) => '<option value="' + d + '"' + (String(d) === days ? " selected" : "") + ">" + d + "</option>").join("") + "</select> days</span></div>";
		const cols = '<div class="pm-prow pm-prow--head"><span>Person</span><span>Open</span><span>Overdue</span><span>Due in 7 days</span><span>Delivered</span><span></span></div>';
		return head + cols + rows.map((p) => '<div class="pm-prow" data-key="person:' + esc(p.user) + '"><span class="pm-pname"><button type="button" class="pm-title" data-act="person" data-user="' + esc(p.user) + '">' + esc(p.name) + "</button>" + (p.heavy ? '<span class="ph-badge ph-badge--warn" title="More than twice the team median of ' + data.people.median_open + ' open tasks">Carrying a lot</span>' : "") + '</span><span data-l="Open"><b>' + p.open + '</b></span><span data-l="Overdue" class="' + (p.overdue ? "pm-late" : "") + '"><b>' + p.overdue + '</b></span><span data-l="Due in 7 days"><b>' + p.due_soon + '</b></span><span data-l="Delivered"><b>' + p.delivered + '</b></span><span class="pm-acts"><button type="button" class="ph-btn ph-btn--sm" data-act="person" data-user="' + esc(p.user) + '">View tasks</button></span></div>').join("");
	}
	function projectsHtml(rows) {
		return '<div class="pm-jrow pm-jrow--head"><span>Project</span><span>Open</span><span>Overdue</span><span>Done</span><span>Next due</span><span>Owner</span></div>'
			+ rows.map((p) => '<a class="pm-jrow" data-key="project:' + esc(p.project) + '" href="' + BOARD + encodeURIComponent(p.project) + '"><span class="pm-pname"><b>' + esc(p.label) + '</b><span class="ph-badge ph-badge--' + (p.health.level === "watch" ? "warn" : "good") + '">' + (p.health.level === "watch" ? "Worth a look" : "On track") + '</span><small>' + esc(p.health.reason) + '</small></span><span data-l="Open"><b>' + p.open + '</b></span><span data-l="Overdue" class="' + (p.overdue ? "pm-late" : "") + '"><b>' + p.overdue + '</b></span><span data-l="Done"><b>' + p.done + '</b></span><span data-l="Next due">' + (p.next_due ? PH.fmt.date(p.next_due, true) : "none") + '</span><span data-l="Owner">' + esc(p.owner) + "</span></a>").join("");
	}
	function paintBulk() {
		const bar = $("#bulk");
		bar.hidden = !selected.size || !["late", "no_owner", "stuck"].includes(st.get("tab"));
		if (bar.hidden) return;
		PH.set(bar, "<b>" + selected.size + "</b> selected " + btn("bulk", "", "Reassign selected", "ph-btn--primary") + btn("clear", "", "Clear selection", "ph-btn--ghost"));
	}

	/* ------------------------------------------------------------------ dialogs */
	const isoDay = (n) => {
		const d = new Date(data.today + "T00:00:00");
		d.setDate(d.getDate() + n);
		return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
	};
	const field = (key, label, required, inner, hint) => '<div class="ph-field" data-f="' + key + '"><label for="pm-' + key + '">' + esc(label) + (required ? '<i aria-hidden="true"> *</i>' : "") + "</label>" + inner + (hint ? '<div class="ph-field__hint">' + esc(hint) + "</div>" : "") + '<div class="ph-field__error" role="alert" hidden></div></div>';
	const optionList = (items, selectedValue) => items.map(([v, l]) => '<option value="' + esc(v) + '"' + (v === selectedValue ? " selected" : "") + ">" + esc(l) + "</option>").join("");

	/** Who can be picked: the same list the Review Queue offers (api.requests.get_assignable_users). */
	const loadPeople = () => PH.call(REQ + "get_assignable_users", {}, { silent: true, type: "GET" });
	/** Projects a decision may choose: the same call the Review Queue makes. */
	const loadProjects = () => PH.call("frappe.client.get_list", { doctype: "Project", fields: ["name", "project_name"], order_by: "project_name asc", limit_page_length: 0 }, { silent: true, type: "GET" });

	/** Chips + search; `multi` false keeps one person. */
	function picker(host, people, initial, multi) {
		let chosen = initial.slice();
		const labelOf = (e) => ((people.find((x) => x.name === e) || {}).full_name || e);
		host.innerHTML = '<div class="pm-chips"></div><input class="ph-control" id="pm-assign" type="text" placeholder="Type a name to find people" autocomplete="off" aria-label="Assign to">';
		const chips = host.querySelector(".pm-chips");
		const paint = () => {
			chips.innerHTML = chosen.map((e) => '<span class="pm-chip">' + esc(labelOf(e)) + '<button type="button" data-rm="' + esc(e) + '" aria-label="Remove ' + esc(labelOf(e)) + '">×</button></span>').join("");
		};
		const pick = (email) => {
			chosen = multi ? (chosen.includes(email) ? chosen.filter((x) => x !== email) : chosen.concat(email)) : [email];
			paint();
		};
		PH.autocomplete(host.querySelector("input"), {
			minChars: 1,
			display: () => "",
			onSelect: (it) => pick(it.value),
			source: async (q) => {
				const words = q.toLowerCase().split(/\s+/).filter(Boolean);
				return people.filter((p) => !chosen.includes(p.name) && words.every((w) => (p.full_name + " " + p.name).toLowerCase().includes(w))).slice(0, 50).map((p) => ({ value: p.name, label: p.full_name || p.name, description: p.name }));
			},
		});
		chips.addEventListener("click", (e) => {
			const b = e.target.closest("[data-rm]");
			if (b) pick(b.dataset.rm);
		});
		paint();
		return { ids: () => chosen.slice(), labels: () => chosen.map(labelOf) };
	}

	/**
	 * One decision dialog. def: {title, sub, note, fields, need, commentLabel, keepBlank, submit, danger,
	 * single, people (initial emails), project, priority, due, send(values) -> Promise<message>}.
	 * Resolves nothing; a success toasts and reloads the page.
	 */
	function decide(def) {
		const opener = document.activeElement;
		const wants = (k) => def.fields.includes(k);
		Promise.all([wants("assign") ? loadPeople() : [], wants("project") ? loadProjects() : []]).then(([people, projects]) => {
			const levels = data.options.priorities;
			const body = document.createElement("div");
			const blank = (l) => [["", l]];
			const projOpts = (projects || []).map((p) => [p.name, p.project_name || p.name]);
			if (def.project && !projOpts.some(([v]) => v === def.project)) projOpts.push([def.project, def.project]);
			const prio = def.keepBlank ? def.priority || "" : levels.includes(def.priority) ? def.priority : levels.includes(FALLBACK_PRIORITY) ? FALLBACK_PRIORITY : levels[0] || "";
			const parts = {
				project: () => field("project", "Project", def.need.includes("project"), '<select class="ph-control" id="pm-project">' + optionList(blank(def.keepBlank ? "Leave as it is" : "Pick a project").concat(projOpts), def.project || "") + "</select>"),
				priority: () => field("priority", "Priority", false, '<select class="ph-control" id="pm-priority">' + optionList((def.keepBlank ? blank("Leave as it is") : []).concat(levels.map((l) => [l, l])), prio) + "</select>"),
				assign: () => field("assign", def.single ? "Reassign to" : "Assign to", true, '<div id="pm-assign-host"></div>', def.single ? "" : "Pick as many people as the work needs."),
				due: () => field("due", "Due date", def.need.includes("due"), '<input class="ph-control" id="pm-due" type="date" value="' + esc(def.due || "") + '"><div class="pm-quick">' + QUICK_DUE_DAYS.map(([l, d]) => '<button type="button" data-due="' + isoDay(d) + '">' + l + "</button>").join("") + "</div>"),
				comment: () => field("comment", def.commentLabel || "Comment (optional)", def.need.includes("comment"), '<textarea class="ph-control" id="pm-comment" rows="3"></textarea>'),
			};
			body.innerHTML = (def.note ? '<p class="ph-muted ph-mb">' + esc(def.note) + "</p>" : "") + '<div class="ph-notice ph-notice--bad pm-formerr" role="alert" hidden></div><div class="pm-form">' + def.fields.map((f) => parts[f]()).join("") + "</div>";
			const pk = wants("assign") ? picker(body.querySelector("#pm-assign-host"), people || [], def.people || [], !def.single) : null;
			const get = (id) => (body.querySelector("#pm-" + id) || {}).value || "";
			const showError = (key, msg) => {
				const wrap = body.querySelector('[data-f="' + key + '"]');
				const err = wrap.querySelector(".ph-field__error");
				err.textContent = msg;
				err.hidden = false;
			};
			body.addEventListener("click", (e) => {
				const q = e.target.closest("[data-due]");
				if (q) body.querySelector("#pm-due").value = q.dataset.due;
			});
			PH.modal({
				title: def.title,
				sub: def.sub,
				body,
				onClose: () => opener && document.contains(opener) && opener.focus(),
				actions: [
					{ label: "Cancel" },
					{
						label: def.submit,
						primary: !def.danger,
						danger: !!def.danger,
						onClick: () => {
							PH.$$(".ph-field__error", body).forEach((x) => (x.hidden = true));
							body.querySelector(".pm-formerr").hidden = true;
							const v = { project: get("project"), priority: get("priority"), due: get("due"), comment: get("comment").trim(), assign: pk ? pk.ids() : [], labels: pk ? pk.labels() : [] };
							const missing = def.need.filter((k) => (k === "assign" ? !v.assign.length : !v[k]));
							if (def.pastDue && v.due && v.due < data.today) missing.push("duePast");
							if (missing.length) {
								missing.forEach((k) => (k === "duePast" ? showError("due", "Pick today or a later date.") : showError(k, ERRORS[k])));
								return false;
							}
							return def.send(v).then(
								(msg) => finish(msg, "good"),
								(e) => {
									if (e.partial) return finish(e.message, "warn");
									const box = body.querySelector(".pm-formerr");
									box.textContent = e.message || "That did not save.";
									box.hidden = false;
									return false;
								}
							);
						},
					},
				],
			});
		}).catch((e) => PH.toast("Could not load what this needs: " + (e.message || "try again."), "bad"));
	}
	/** After an action: say what happened, then read everything again so every count follows it. */
	function finish(message, kind) {
		PH.toast(message, kind);
		selected.clear();
		return load();
	}

	const call = (m, a) => PH.call(REQ + m, a, { silent: true });
	const reassign = (name, v) => call("reassign_task", { name, assign_to: v.assign.join(","), complete_by: v.due || null, comment: v.comment || null });
	const triage = (r, action, v) => call("triage_request", { name: r.name, action, project: v.project || null, priority: v.priority || null, reason: v.comment || null });
	const holders = (r) => r.assignee_ids || [];

	const ACTIONS = {
		accept: (r) => decide({
			title: "Accept and schedule", sub: r.name + " · " + r.title, fields: ["project", "priority", "assign", "due", "comment"], need: ["project", "assign", "due"],
			note: "Creates the task, assigns it and sets its due date in one step.", submit: "Accept and schedule", project: r.project, priority: r.priority, people: r.requested_for ? [r.requested_for] : [],
			send: (v) => call("accept_request", { name: r.name, project: v.project, priority: v.priority, complete_by: v.due, assign_to: v.assign.join(","), comment: v.comment || null }).then((res) => "Accepted. " + (res.task || "Task") + " created for " + v.labels.join(", ") + "."),
		}),
		defer: (r) => decide({
			title: "Defer for now", sub: r.name + " · " + r.title, fields: ["project", "priority", "comment"], need: ["comment"], commentLabel: "Reason", keepBlank: true,
			note: "Parks the request. It can be reopened from the Review Queue.", submit: "Defer request", project: r.project, priority: r.priority,
			send: (v) => triage(r, "Defer", v).then(() => r.name + " deferred."),
		}),
		reject: (r) => decide({
			title: "Reject request", sub: r.name + " · " + r.title, fields: ["comment"], need: ["comment"], commentLabel: "Reason", danger: true,
			note: "Rejecting is final: the person who raised it sees it as rejected.", submit: "Reject request",
			send: (v) => triage(r, "Reject", v).then(() => r.name + " rejected."),
		}),
		schedule: (r) => decide({
			title: "Schedule and assign", sub: r.name + " · " + r.title, fields: ["assign", "due", "comment"], need: ["assign", "due"],
			note: "Creates the task for this approved request and hands it to the people you pick.", submit: "Schedule and assign", people: r.requested_for ? [r.requested_for] : [],
			send: (v) => call("promote_to_task", { name: r.name }).then((res) => {
				if (!res.linked_task) throw Object.assign(new Error(r.name + " was scheduled, but no task was found to assign. Use the Review Queue."), { partial: true });
				return reassign(res.linked_task, v).then(
					() => "Scheduled. " + res.linked_task + " created for " + v.labels.join(", ") + ".",
					(e) => {
						throw Object.assign(new Error("Scheduled as " + res.linked_task + ", but assigning it failed: " + e.message), { partial: true });
					}
				);
			}),
		}),
		reassign: (r) => decide({
			title: r.assignee_ids.length ? "Reassign" : "Assign", sub: r.name + " · " + r.title, fields: ["assign", "due", "comment"], need: ["assign"],
			note: "Anyone you remove is taken off the task; people already on it keep their work. Leave the due date empty to keep it.", submit: "Save assignment", people: holders(r),
			send: (v) => reassign(r.name, v).then(() => r.name + " handed to " + v.labels.join(", ") + "."),
		}),
		due: (r) => decide({
			title: "New due date", sub: r.name + " · " + r.title, fields: ["due"], need: ["due"], pastDue: true, submit: "Save due date", due: r.due || "",
			note: "The people on the task stay the same.",
			send: (v) => reassign(r.name, { assign: holders(r), due: v.due }).then(() => r.name + " is now due " + PH.fmt.date(v.due, true) + "."),
		}),
		done: (r) => PH.confirm("Mark as done?", r.name + " · " + r.title + " will be marked Completed.", { ok: "Mark done" }).then((ok) => ok && status([r], "Completed", "marked done")),
		pending: (r) => PH.confirm("Move to Pending?", r.name + " · " + r.title + " will move to Pending Review and leave this list.", { ok: "Move to Pending" }).then((ok) => ok && status([r], "Pending Review", "moved to Pending")),
	};

	/** Runs `fn` for every row one after another; resolves {ok, failed} where a failure is named, not hidden. */
	function each(rows, fn) {
		const out = { ok: 0, failed: [] };
		return rows.reduce((p, r) => p.then(() => fn(r).then(() => out.ok++, (e) => out.failed.push(r.name + " (" + (e.message || "failed") + ")"))), Promise.resolve()).then(() => out);
	}
	const outcome = (res, said) => plural(res.ok, "task") + " " + said + "." + (res.failed.length ? " Not done: " + res.failed.join("; ") + "." : "");
	function status(rows, to, said) {
		return each(rows, (r) => call("update_task_status", { name: r.name, status: to })).then((res) => finish(outcome(res, said), res.failed.length ? "warn" : "good"));
	}
	function bulkReassign(rows) {
		decide({
			title: "Reassign " + plural(rows.length, "task"), sub: "Everyone now on these tasks is replaced by the person you pick.", fields: ["assign", "due", "comment"], need: ["assign"], single: true, submit: "Reassign",
			send: (v) => each(rows, (r) => reassign(r.name, v)).then((res) => {
				const msg = outcome(res, "handed to " + v.labels[0]);
				if (res.failed.length) throw Object.assign(new Error(msg), { partial: true });
				return msg;
			}),
		});
	}

	/* ------------------------------------------------------------------ drawers */
	function openItem(r) {
		const body = document.createElement("div");
		PH.skeleton(body, "rows", 5);
		const m = PH.modal({ title: r.title || r.name, sub: docType(r) + " " + r.name, body, drawer: true, actions: [{ label: "Close" }] });
		PH.call(API + "get_pm_item", { doctype: docType(r), name: r.name }, { silent: true }).then((d) => {
			const board = d.project ? '<a class="ph-link" href="' + BOARD + encodeURIComponent(d.project) + '">Backlog Board</a> · ' : "";
			PH.set(body, '<dl class="pm-facts">' + d.facts.map(([k, v]) => "<dt>" + esc(k) + "</dt><dd>" + esc(v) + "</dd>").join("") + "</dl>"
				+ (d.description ? '<p class="pm-desc">' + esc(d.description) + "</p>" : "")
				+ '<p class="pm-links">' + board + '<a class="ph-link" href="' + PH.docUrl(d.doctype, d.name) + '" target="_blank" rel="noopener">Open in Desk</a></p>'
				+ '<h3 class="ph-section-title">History</h3><ul class="pm-hist">' + d.history.map((h) => "<li><span>" + esc(PH.fmt.date(h.at.slice(0, 10), true)) + "</span> " + esc(h.text) + (h.by ? " <small>" + esc(h.by) + "</small>" : "") + "</li>").join("") + "</ul>");
		}).catch((e) => PH.error(body, e.message));
		return m;
	}
	function openPerson(user) {
		const p = data.people.rows.find((x) => x.user === user);
		if (!p) return;
		const body = document.createElement("div");
		const picked = new Set();
		let rows = [];
		const paint = () => {
			PH.set(body, '<div class="pm-bulk pm-bulk--in"><label><input type="checkbox" class="ph-check" data-all' + (rows.length && picked.size === rows.length ? " checked" : "") + '> Select all</label> <b>' + picked.size + "</b> selected " + btn("reassign-sel", "", "Reassign selected", "ph-btn--primary") + "</div>"
				+ rows.map((r) => '<div class="pm-row"><input type="checkbox" class="ph-check" data-p="' + esc(r.name) + '"' + (picked.has(r.name) ? " checked" : "") + '><div class="pm-main"><button type="button" class="pm-title" data-open="' + esc(r.name) + '">' + esc(r.title) + "</button>" + sub([r.name, r.project_label, r.priority, r.status]) + "</div>" + fact(r.days_late ? "<b>" + plural(r.days_late, "day") + "</b> late" : r.due ? "due " + PH.fmt.date(r.due, true) : "no due date", r.days_late > 0) + "</div>").join(""));
			body.querySelector("[data-act]").disabled = !picked.size;
		};
		const m = PH.modal({ title: p.name, sub: plural(p.open, "open task") + ", " + p.overdue + " overdue", body, drawer: true, size: "lg", actions: [{ label: "Close" }] });
		const reload = () => PH.call(API + "get_pm_person_tasks", { person: user, project: st.get("project"), area: st.get("area"), priority: st.get("priority") }, { silent: true }).then((d) => {
			rows = d.rows;
			picked.forEach((n) => rows.some((r) => r.name === n) || picked.delete(n));
			paint();
		}).catch((e) => PH.error(body, e.message, reload));
		body.addEventListener("change", (e) => {
			if (e.target.dataset.all !== undefined) rows.forEach((r) => (e.target.checked ? picked.add(r.name) : picked.delete(r.name)));
			else if (e.target.dataset.p) e.target.checked ? picked.add(e.target.dataset.p) : picked.delete(e.target.dataset.p);
			paint();
		});
		body.addEventListener("click", (e) => {
			const o = e.target.closest("[data-open]");
			if (o) openItem(rows.find((r) => r.name === o.dataset.open));
			if (e.target.closest('[data-act="reassign-sel"]')) {
				m.close();
				bulkReassign(rows.filter((r) => picked.has(r.name)));
			}
		});
		PH.skeleton(body, "rows", 5);
		reload();
	}

	/* ------------------------------------------------------------------ events */
	$("#body").addEventListener("click", (e) => {
		const t = e.target.closest("[data-act]");
		if (!t) return;
		if (t.dataset.act === "person") return openPerson(t.dataset.user);
		const r = find(t.dataset.key);
		if (!r) return;
		DevKeys.select(t.dataset.key);
		if (t.dataset.act === "open") openItem(r);
		else ACTIONS[t.dataset.act](r);
	});
	$("#body").addEventListener("change", (e) => {
		const t = e.target;
		if (t.id === "f-days") return st.set({ days: t.value });
		if (t.dataset.sel) t.checked ? selected.add(t.dataset.sel) : selected.delete(t.dataset.sel);
		else if (t.dataset.selgroup) t.dataset.selgroup.split("|").forEach((n) => (t.checked ? selected.add(n) : selected.delete(n)));
		else return;
		paintBody();
	});
	$("#bulk").addEventListener("click", (e) => {
		const t = e.target.closest("[data-act]");
		if (!t) return;
		if (t.dataset.act === "clear") {
			selected.clear();
			paintBody();
		} else bulkReassign(selectedTasks());
	});
	document.addEventListener("click", (e) => {
		const t = e.target.closest("#strip [data-tab], #tabs [data-tab]");
		if (t) {
			st.set({ tab: t.dataset.tab });
		}
	});
	$("#refresh").addEventListener("click", load);
	$("#f-clear").addEventListener("click", () => st.set({ project: "", area: "", priority: "", assignee: "", q: "" }));
	FILTER_KEYS.forEach((k) => PH.bindSelect("#f-" + k, st, k));
	PH.bindSearch("#f-q", st, "q");
	st.on((s, changed) => {
		const reads = changed.some((k) => FILTER_KEYS.includes(k) || k === "days");
		if (changed.includes("q") && !s.q) $("#f-q").value = "";
		if (changed.includes("tab")) selected.clear();
		return reads ? load() : render();
	});

	/* keyboard (shared layer, dev-v2-keys.js): / search, j k move, Enter opens, r refreshes, ? help */
	DevKeys.init({
		title: "PM Dashboard",
		refresh: () => $("#refresh").click(),
		list: {
			root: "#body", items: () => PH.$$("#body .pm-row, #body .pm-prow, #body .pm-jrow"), id: (el) => el.dataset.key,
			open: (x) => {
				const k = x.dataset.key;
				if (k.startsWith("person:")) openPerson(k.slice(7));
				else if (k.startsWith("project:")) location.href = x.getAttribute("href");
				else { const r = find(k); if (r) openItem(r); }
			},
		},
	});

	PH.onRefresh(load);
	PH.ready(load);
})();
