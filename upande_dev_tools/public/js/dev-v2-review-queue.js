/* Review Queue v2 - the full replacement of /review-queue.
 *
 * READS  : api.v2.review_queue (rows, counts, filter options, request detail).
 * WRITES : the same whitelisted endpoints the current page calls, unchanged, so validation,
 *          permissions, audit trail and side effects stay exactly as they are:
 *            accept_request   Accept  = approve + schedule + assign (creates the Task)
 *            triage_request   Approve (schedule later) / Defer / Reject / Reopen
 *            promote_to_task  Schedule an approved request, reassign_task then names the people
 *            reassign_task    Change who does a scheduled task / its complete-by date
 * Each row carries `actions`: what the caller's roles may do with it (server-side
 * allowed_actions); a control that is not in that list is never drawn.
 */
(function () {
	"use strict";
	const READ = "upande_dev_tools.api.v2.review_queue.";
	const REQ = "upande_dev_tools.api.requests.";
	const NONE = "__none__";
	const VIEWS = ["waiting", "approved", "deferred", "scheduled"];
	const VIEW_NAME = {
		waiting: "waiting for a decision",
		approved: "approved and waiting to be scheduled",
		deferred: "deferred",
		scheduled: "scheduled or in progress",
	};
	const VIEW_SHORT = { waiting: "waiting", approved: "approved", deferred: "deferred", scheduled: "scheduled" };
	const FILTERS = ["q", "type", "area", "project", "priority", "tag", "by", "for", "age"];
	const FALLBACK_PRIORITY = "Medium";
	const QUICK_DUE_DAYS = [
		["In a week", 7],
		["In two weeks", 14],
		["In a month", 30],
	];

	/**
	 * One entry per decision. fields: form fields in order; need: fields that must be filled;
	 * optionalFields: project/priority offered on Defer only as "leave as it is".
	 */
	const ACTIONS = {
		accept: {
			title: "Accept and schedule",
			submit: "Accept and schedule",
			fields: ["project", "priority", "assign", "due", "comment"],
			need: ["project", "assign", "due"],
			note: "Creates the task, assigns it and sets its complete-by date in one step.",
		},
		approve: {
			title: "Approve for scheduling",
			submit: "Approve",
			fields: ["project", "priority", "comment"],
			need: ["project"],
			note: "Approves the request now. It waits on the Approved tab until someone schedules it.",
		},
		defer: {
			title: "Defer for now",
			submit: "Defer request",
			fields: ["project", "priority", "comment"],
			need: ["comment"],
			commentLabel: "Reason",
			keepBlank: true,
			note: "Parks the request. It can be reopened from the Deferred tab.",
		},
		reject: {
			title: "Reject request",
			submit: "Reject request",
			danger: true,
			fields: ["comment"],
			need: ["comment"],
			commentLabel: "Reason",
			note: "Rejecting is final: the person who raised it sees it as rejected.",
		},
		schedule: {
			title: "Schedule and assign",
			submit: "Schedule and assign",
			fields: ["assign", "due", "comment"],
			need: ["assign", "due"],
			note: "Creates the task for this approved request and hands it to the people you pick.",
		},
		reopen: {
			title: "Reopen for review",
			submit: "Reopen",
			fields: ["comment"],
			need: [],
			commentLabel: "Note",
			note: "Puts the request back on the Waiting tab for a new decision.",
		},
		reassign: {
			title: "Reassign",
			submit: "Save assignment",
			fields: ["assign", "due", "comment"],
			need: ["assign"],
			note: "Anyone you remove is taken off the task; people already on it keep their work.",
		},
	};
	const ROW_BUTTONS = {
		waiting: ["accept", "defer", "reject"],
		approved: ["schedule"],
		deferred: ["reopen"],
		scheduled: ["reassign"],
	};
	const KEY_ACTIONS = {
		a: ["accept", "schedule", "reassign"],
		p: ["approve"],
		d: ["defer"],
		r: ["reject"],
		o: ["reopen"],
	};
	const ERRORS = {
		project: "Pick a project first.",
		assign: "Pick who this goes to first.",
		due: "Set a due date first.",
		comment: "Give a reason first.",
	};

	const st = PH.state({ view: "waiting", q: "", type: "", area: "", project: "", priority: "", tag: "", by: "", for: "", age: "" });
	const n = PH.fmt.num;
	let data = null;
	let seq = 0;
	let table = null;
	let tableView = null;
	let refsPromise = null;

	/* ---- filters, tabs and URL state ---- */
	PH.bindSearch("#f-q", st, "q");
	[["#f-type", "type"], ["#f-area", "area"], ["#f-project", "project"], ["#f-priority", "priority"], ["#f-tag", "tag"], ["#f-by", "by"], ["#f-for", "for"], ["#f-age", "age"]]
		.forEach(([sel, key]) => PH.bindSelect(sel, st, key));
	PH.$("#tabs").addEventListener("click", (e) => {
		const b = e.target.closest("[data-view]");
		if (b) st.set({ view: b.dataset.view });
	});
	PH.$("#f-clear").addEventListener("click", () => {
		const cleared = {};
		FILTERS.forEach((k) => (cleared[k] = ""));
		st.set(cleared);
		PH.$("#f-q").value = "";
	});

	const view = () => (VIEWS.includes(st.get("view")) ? st.get("view") : "waiting");
	const hasFilters = () => FILTERS.some((k) => st.get(k));
	const args = () => {
		const s = st.get();
		return { view: view(), search: s.q, request_type: s.type, product_area: s.area, project: s.project, priority: s.priority, tag: s.tag, raised_by: s.by, requested_for: s.for, min_age_days: s.age };
	};
	st.on(() => {
		paintChrome();
		load();
	});

	function paintChrome() {
		PH.$$("#tabs .ph-tab").forEach((b) => {
			const on = b.dataset.view === view();
			b.classList.toggle("is-on", on);
			b.setAttribute("aria-selected", on ? "true" : "false");
		});
		PH.$("#f-clear").hidden = !hasFilters();
	}

	PH.kpiSkeleton("#kpis", ["Requests", "Longest wait", "A week or more", "Average wait", "No priority yet"]);

	/* ---- cell renderers ---- */
	const dayText = (d) => (d <= 0 ? "today" : d === 1 ? "1 day" : n(d) + " days");
	const ageBadge = (r) => {
		const cls = r.age_days >= 14 ? "ph-badge--warn" : r.age_days >= 7 ? "ph-badge--signal" : "ph-badge--outline";
		return '<span class="ph-badge ' + cls + '" title="Raised ' + PH.esc(PH.fmt.date(r.creation.slice(0, 10))) + '">' + PH.esc(r.age_label) + "</span>";
	};
	const prioBadge = (p) => (p ? '<span class="ph-badge ' + (p === "Urgent" ? "ph-badge--ink" : "ph-badge--outline") + '">' + PH.esc(p) + "</span>" : '<span class="ph-muted">Not set</span>');
	const tagsHtml = (tags) => (tags && tags.length ? '<div class="rq-tags">' + tags.map((t) => '<span class="ph-badge ph-badge--outline">' + PH.esc(t) + "</span>").join("") + "</div>" : '<span class="ph-muted">—</span>');
	const who = (r) => PH.esc(r.raised_by_name) + (r.raised_for ? '<div class="rq-sub">for ' + PH.esc(r.raised_for) + "</div>" : "");

	function actionButtons(r) {
		const wanted = ROW_BUTTONS[view()].filter((a) => r.actions.includes(a));
		const rest = r.actions.filter((a) => !wanted.includes(a));
		const btns = wanted.map((a, i) => {
			const cls = i === 0 ? "ph-btn--primary" : a === "reject" ? "ph-btn--danger-ghost ph-btn--ghost" : "ph-btn--ghost";
			const label = a === "accept" ? "Accept" : ACTIONS[a].title.split(" ")[0];
			return '<button type="button" class="ph-btn ph-btn--sm ' + cls + '" data-act="' + a + '" data-name="' + PH.esc(r.name) + '" aria-label="' + PH.esc(ACTIONS[a].title + ": " + r.title) + '">' + PH.esc(label) + "</button>";
		});
		if (rest.length) btns.push('<button type="button" class="ph-iconbtn ph-iconbtn--sm" data-more="' + PH.esc(r.name) + '" aria-label="More actions for ' + PH.esc(r.title) + '" title="More actions">' + PH.icon("more") + "</button>");
		return '<div class="rq-acts">' + btns.join("") + "</div>";
	}

	function columns(v) {
		const cols = [
			{ key: "title", label: "Request", cls: "rq-title", html: (x, r) => '<a class="rq-link" href="#" data-open="' + PH.esc(r.name) + '">' + PH.esc(x) + '</a><div class="rq-sub"><span class="ph-mono">' + PH.esc(r.name) + "</span> · " + PH.esc(r.request_type || "No type") + (r.product_area ? " · " + PH.esc(r.product_area) : "") + "</div>" + (r.tags.length ? tagsHtml(r.tags) : "") },
			{ key: "priority_rank", label: "Priority", html: (x, r) => prioBadge(r.priority) },
			{ key: "raised_by_name", label: "Raised by", html: (x, r) => who(r) },
			{ key: "age_days", label: "Waiting", sortValue: (r) => r.age_days, html: (x, r) => ageBadge(r) },
		];
		if (v !== "waiting") cols.push({ key: "stage_since", label: "In this stage since", format: (x) => (x ? PH.fmt.date(x.slice(0, 10)) : "Not recorded") });
		if (v === "scheduled") {
			cols.push({ key: "status", label: "Stage" });
			cols.push({ key: "due", label: "Complete by", format: (x) => (x ? PH.fmt.date(x) : "Not set") });
			cols.push({ key: "assignees", label: "Assigned to", sortValue: (r) => r.assignees.join(", "), format: (x) => (x && x.length ? x.join(", ") : "—") });
		} else {
			cols.push({ key: "requested_for_name", label: "Requested for", format: (x) => x || "Nobody named" });
		}
		cols.push({ key: "project_name", label: "Project", format: (x) => x || "None yet" });
		if (data && data.rows.some((r) => r.actions.length)) cols.push({ key: "actions", label: "Decide", sortable: false, html: (x, r) => actionButtons(r) });
		return cols;
	}

	function mountTable(rows) {
		const v = view();
		const withActions = rows.some((r) => r.actions.length);
		if (!table || tableView !== v + withActions) {
			tableView = v + withActions;
			table = PH.table("#t-rows", {
				columns: columns(v), rows, pageSize: 25, compact: true, empty: "Nothing here",
				emptyText: hasFilters() ? "No request matches these filters. Clear a filter to see more." : "No requests in this stage right now.",
				sort: { key: "age_days", dir: "desc" }, onRowClick: (r) => detail(r.name),
			});
		} else table.update(rows);
	}

	function bars(sel, rows, field) {
		const max = Math.max(1, ...rows.map((x) => x.count));
		const valueOf = (x) => (field === "age" ? String(x.min_days) : x.key);
		PH.set(sel, rows.map((x, i) => {
			const on = st.get(field) === valueOf(x);
			return '<div class="rq-bar' + (on ? " is-on" : "") + '" data-i="' + i + '" role="button" tabindex="0" title="' + PH.esc(x.label) + ": " + x.count + '"><span>' + PH.esc(x.label) + "</span><b>" + n(x.count) + '</b><div class="ph-progress"><i class="' + (field === "age" && x.min_days >= 7 ? "warn" : "good") + '" style="width:' + (100 * x.count) / max + '%"></i></div></div>';
		}).join("") || '<div class="ph-empty">Nothing to show</div>');
		PH.$$(".rq-bar", PH.$(sel)).forEach((el) => {
			const pick = () => {
				const x = rows[+el.dataset.i];
				if (field === "age" && !x.min_days) return;
				st.set({ [field]: st.get(field) === valueOf(x) ? "" : valueOf(x) });
			};
			el.addEventListener("click", pick);
			el.addEventListener("keydown", (e) => {
				if (e.key === "Enter" || e.key === " ") {
					e.preventDefault();
					pick();
				}
			});
		});
	}

	function fillOptions(o) {
		const s = st.get();
		const withNone = (items, label) => items.concat([{ value: NONE, label }]);
		PH.options("#f-type", o.request_types, s.type);
		PH.options("#f-area", withNone(o.product_areas.map((x) => ({ value: x, label: x })), "No product area"), s.area);
		PH.options("#f-project", withNone(o.projects, "No project yet"), s.project);
		PH.options("#f-priority", withNone(o.priorities.map((x) => ({ value: x, label: x })), "Not set"), s.priority);
		PH.options("#f-tag", o.tags, s.tag);
		PH.options("#f-by", o.raised_by, s.by);
		PH.options("#f-for", withNone(o.requested_for, "Nobody named"), s.for);
	}

	let canDecideNow = false;

	/* ---- list ---- */
	function render() {
		const d = data, t = d.totals, v = view();
		VIEWS.forEach((k) => PH.text("#tc-" + k, n(d.counts[k])));
		const scope = [];
		const s = st.get();
		if (s.q) scope.push('"' + s.q + '"');
		if (s.type) scope.push(s.type);
		if (s.area) scope.push(s.area === NONE ? "No product area" : s.area);
		if (s.priority) scope.push(s.priority === NONE ? "No priority" : s.priority + " priority");
		if (s.tag) scope.push("tag " + s.tag);
		if (s.age) scope.push(s.age + "+ days waiting");
		if (s.project) scope.push("one project");
		if (s.by || s.for) scope.push("one person");
		PH.text("#sub", (t.count ? PH.fmt.plural(t.count, "request") + " " + VIEW_NAME[v] : "Nothing " + VIEW_NAME[v]) + " · " + n(d.open_total) + " open in all · as of " + d.as_of.slice(0, 16).replace(" ", " at ") + (scope.length ? " · " + scope.join(" · ") : ""));

		PH.kpis("#kpis", [
			{ label: "Requests", value: t.count, unit: VIEW_SHORT[v], dark: true, title: "Open requests in this stage that match the filters" },
			{ label: "Longest wait", value: t.count ? dayText(t.longest_days) : "—", unit: t.longest_days >= 14 ? "worth a look" : "since it was raised", title: "Time since the oldest of these was raised" },
			{ label: "A week or more", value: t.over_week, unit: t.count ? "of " + n(t.count) : "", onClick: t.over_week ? () => st.set({ age: "7" }) : null },
			{ label: "Average wait", value: t.count ? t.average_days : "—", unit: t.count ? "days since raised" : "" },
			{ label: v === "waiting" ? "No priority yet" : "No project", value: v === "waiting" ? t.no_priority : t.no_project, unit: v === "waiting" ? PH.fmt.plural(t.no_project, "has no project", "have no project") : "" },
		]);

		const notes = [];
		if (t.scheduled_without_task > 0) notes.push('<div class="ph-notice ph-notice--signal">' + PH.fmt.plural(t.scheduled_without_task, "scheduled request has", "scheduled requests have") + " no task linked to it yet, so there is no complete-by date to show.</div>");
		if (d.truncated) notes.push('<div class="ph-notice ph-notice--signal">Showing the oldest ' + n(d.row_limit) + " of " + n(t.count) + " requests. The numbers above cover all of them; narrow the filters to see the rest.</div>");
		PH.set("#notes", notes.join(""));

		bars("#by-age", d.by_age_band, "age");
		bars("#by-priority", d.by_priority, "priority");
		bars("#by-type", d.by_type, "type");
		PH.text("#t-title", "Requests " + VIEW_NAME[v]);
		canDecideNow = !!d.can_decide;
		mountTable(d.rows);
		DevKeys.repaint();
		PH.$("#export").disabled = !d.rows.length;
	}

	function load() {
		const my = ++seq;
		PH.loadingKpis("#kpis", true);
		PH.skeleton("#t-rows");
		return PH.call(READ + "get_review_queue", args(), { silent: true })
			.then((m) => {
				if (my !== seq) return;
				data = m;
				render();
				PH.markUpdated();
			})
			.catch((e) => {
				if (my !== seq) return;
				PH.loadingKpis("#kpis", false);
				table = null;
				PH.error("#t-rows", e.message || "The queue could not be loaded.", () => load());
				["#by-age", "#by-priority", "#by-type"].forEach((x) => PH.set(x, ""));
			});
	}

	function loadOptions() {
		return PH.call(READ + "get_review_queue_options", {}, { silent: true })
			.then((o) => {
				refsPromise = null;
				fillOptions(o);
				return o;
			})
			.catch(() => null);
	}

	/* ---- lists a decision needs: projects the user may read (same call as the current page),
	 * people to assign (api.requests.get_assignable_users) and the enabled priority levels ---- */
	function loadRefs() {
		if (!refsPromise) {
			refsPromise = Promise.all([
				PH.call("frappe.client.get_list", { doctype: "Project", fields: ["name", "project_name"], order_by: "project_name asc", limit_page_length: 0 }, { silent: true, type: "GET" }),
				PH.call(REQ + "get_assignable_users", {}, { silent: true, type: "GET" }),
				PH.call(READ + "get_review_queue_options", {}, { silent: true }),
			]).then(([projects, people, o]) => ({ projects: projects || [], people: people || [], priorities: o.decision_priorities }))
				.catch((e) => {
					refsPromise = null;
					throw e;
				});
		}
		return refsPromise;
	}

	/* ---- the one place a row or the drawer becomes a decision subject ---- */
	const subjectOfRow = (r) => ({ name: r.name, title: r.title, project: r.project, priority: r.priority, requested_for: r.requested_for, task: r.task, due: r.due, assignee_ids: r.assignee_ids });
	const rowByName = (name) => (data ? data.rows.find((r) => r.name === name) : null);

	/* ---- people picker (multi-select, searchable, chips) ---- */
	function peoplePicker(host, people, initial) {
		let chosen = initial.slice();
		const labelOf = (email) => {
			const p = people.find((x) => x.name === email);
			return p ? p.full_name || p.name : email;
		};
		host.innerHTML = '<div class="rq-chips"></div><input class="ph-control" id="rq-assign" type="text" placeholder="Type a name to find people - pick as many as you need" autocomplete="off" aria-label="Assign to">';
		const chips = host.querySelector(".rq-chips");
		const input = host.querySelector("input");
		const paint = () => {
			chips.innerHTML = chosen.map((e) => '<span class="rq-chip">' + PH.esc(labelOf(e)) + '<button type="button" data-rm="' + PH.esc(e) + '" aria-label="Remove ' + PH.esc(labelOf(e)) + '">×</button></span>').join("");
		};
		const toggle = (email) => {
			chosen = chosen.includes(email) ? chosen.filter((x) => x !== email) : chosen.concat(email);
			paint();
			host.dispatchEvent(new Event("change", { bubbles: true }));
		};
		PH.autocomplete(input, {
			minChars: 1,
			display: () => "",
			onSelect: (it) => toggle(it.value),
			source: async (q) => {
				const words = q.toLowerCase().split(/\s+/).filter(Boolean);
				return people
					.filter((p) => !chosen.includes(p.name) && words.every((w) => (p.full_name + " " + p.name).toLowerCase().includes(w)))
					.slice(0, 50)
					.map((p) => ({ value: p.name, label: p.full_name || p.name, description: p.name }));
			},
		});
		input.addEventListener("keydown", (e) => {
			if (e.key === "Backspace" && !input.value && chosen.length) toggle(chosen[chosen.length - 1]);
		});
		chips.addEventListener("click", (e) => {
			const b = e.target.closest("[data-rm]");
			if (b) toggle(b.dataset.rm);
		});
		paint();
		return { ids: () => chosen.slice(), labels: () => chosen.map(labelOf) };
	}

	/* ---- decision dialog ---- */
	const isoDay = (offsetDays) => {
		const d = new Date();
		d.setDate(d.getDate() + offsetDays);
		return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
	};
	const field = (key, label, required, inner, hint) =>
		'<div class="ph-field" data-f="' + key + '"><label for="rq-' + key + '">' + PH.esc(label) + (required ? '<i aria-hidden="true"> *</i>' : "") + "</label>" + inner + (hint ? '<div class="ph-field__hint">' + PH.esc(hint) + "</div>" : "") + '<div class="ph-field__error" role="alert" hidden></div></div>';
	const optionList = (items, selected) => items.map(([v, l]) => '<option value="' + PH.esc(v) + '"' + (v === selected ? " selected" : "") + ">" + PH.esc(l) + "</option>").join("");

	function formHtml(def, sub, refs) {
		const need = new Set(def.need);
		const blank = (label) => [["", label]];
		const projects = refs.projects.map((p) => [p.name, p.project_name || p.name]);
		if (sub.project && !projects.some(([v]) => v === sub.project)) projects.push([sub.project, sub.project]);
		const levels = refs.priorities.map((p) => [p, p]);
		const prioDefault = def.keepBlank ? sub.priority || "" : refs.priorities.includes(sub.priority) ? sub.priority : refs.priorities.includes(FALLBACK_PRIORITY) ? FALLBACK_PRIORITY : refs.priorities[0] || "";
		const parts = {
			project: () => field("project", "Project", need.has("project"), '<select class="ph-control" id="rq-project">' + optionList(blank(def.keepBlank ? "Leave as it is" : "Pick a project").concat(projects), sub.project || "") + "</select>"),
			priority: () => field("priority", "Priority", false, '<select class="ph-control" id="rq-priority">' + optionList((def.keepBlank ? blank("Leave as it is") : []).concat(levels), prioDefault) + "</select>"),
			assign: () => field("assign", "Assign to", need.has("assign"), '<div class="rq-picker" id="rq-assign-host"></div>', sub.requested_for && !sub.task ? "Pre-filled with the person the requester asked for." : ""),
			due: () => field("due", "Complete by", need.has("due"), '<input class="ph-control" id="rq-due" type="date" value="' + PH.esc(sub.due || "") + '"><div class="rq-quick">' + QUICK_DUE_DAYS.map(([l, d]) => '<button type="button" data-due="' + isoDay(d) + '">' + l + "</button>").join("") + "</div>"),
			comment: () => field("comment", def.commentLabel || "Comment (optional)", need.has("comment"), '<textarea class="ph-control" id="rq-comment" rows="3" placeholder="' + (need.has("comment") ? "Why? The requester can read this." : "Add a comment") + '"></textarea>'),
		};
		return (def.note ? '<p class="ph-muted ph-mb">' + PH.esc(def.note) + "</p>" : "") + '<div class="ph-notice ph-notice--bad rq-formerr" role="alert" hidden></div><div class="rq-form">' + def.fields.map((f) => parts[f]()).join("") + "</div>";
	}

	/** The request body each decision sends; the result is the success message. */
	const SEND = {
		accept: (sub, v) => PH.call(REQ + "accept_request", { name: sub.name, project: v.project, priority: v.priority, complete_by: v.due, assign_to: v.assign.join(","), comment: v.comment || null }, { silent: true })
			.then((r) => "Accepted. " + (r.task || "Task") + " created for " + v.assignLabels.join(", ") + "."),
		approve: (sub, v) => triage(sub, "Approve", v).then(() => sub.name + " approved for scheduling."),
		defer: (sub, v) => triage(sub, "Defer", v).then(() => sub.name + " deferred."),
		reject: (sub, v) => triage(sub, "Reject", v).then(() => sub.name + " rejected."),
		reopen: (sub, v) => triage(sub, "Reopen", v).then(() => sub.name + " reopened for review."),
		reassign: (sub, v) => reassign(sub.task, v).then(() => sub.task + " reassigned to " + v.assignLabels.join(", ") + "."),
		schedule: (sub, v) => PH.call(REQ + "promote_to_task", { name: sub.name }, { silent: true })
			.then((r) => r.linked_task || PH.call(READ + "get_request_detail", { name: sub.name }, { silent: true }).then((d) => d.task && d.task.name))
			.then((task) => reassign(task, v).then(
				() => "Scheduled. " + task + " created for " + v.assignLabels.join(", ") + ".",
				(e) => {
					throw Object.assign(new Error("Scheduled as " + task + ", but assigning it failed: " + e.message + " Use Reassign on the Scheduled tab."), { partial: true });
				}
			)),
	};
	const triage = (sub, action, v) => PH.call(REQ + "triage_request", { name: sub.name, action, project: v.project || null, priority: v.priority || null, reason: v.comment || null }, { silent: true });
	const reassign = (task, v) => PH.call(REQ + "reassign_task", { name: task, assign_to: v.assign.join(","), complete_by: v.due || null, comment: v.comment || null }, { silent: true });

	function decide(sub, action) {
		const opener = document.activeElement;
		const def = ACTIONS[action];
		loadRefs().then((refs) => {
			const body = document.createElement("div");
			body.innerHTML = formHtml(def, sub, refs);
			let picker = null;
			const host = body.querySelector("#rq-assign-host");
			if (host) {
				const start = action === "reassign" ? sub.assignee_ids || [] : sub.requested_for && !sub.task ? [sub.requested_for] : [];
				picker = peoplePicker(host, refs.people, start);
			}
			const get = (id) => (body.querySelector("#rq-" + id) || {}).value || "";
			const showError = (key, msg) => {
				const wrap = body.querySelector('[data-f="' + key + '"]');
				const err = wrap.querySelector(".ph-field__error");
				err.textContent = msg;
				err.hidden = false;
				const ctl = wrap.querySelector("input,select,textarea");
				if (ctl) ctl.classList.add("is-invalid");
			};
			const clearErrors = () => {
				PH.$$(".ph-field__error", body).forEach((e) => (e.hidden = true));
				PH.$$(".is-invalid", body).forEach((e) => e.classList.remove("is-invalid"));
				body.querySelector(".rq-formerr").hidden = true;
			};
			body.addEventListener("click", (e) => {
				const q = e.target.closest("[data-due]");
				if (q) body.querySelector("#rq-due").value = q.dataset.due;
			});
			body.addEventListener("input", (e) => {
				const wrap = e.target.closest("[data-f]");
				if (wrap) {
					wrap.querySelector(".ph-field__error").hidden = true;
					e.target.classList && e.target.classList.remove("is-invalid");
				}
			});

			const m = PH.modal({
				title: def.title,
				sub: sub.name + " · " + sub.title,
				body,
				onClose: () => {
					if (opener && document.contains(opener)) opener.focus();
				},
				actions: [
					{ label: "Cancel" },
					{
						label: def.submit,
						primary: !def.danger,
						danger: !!def.danger,
						onClick: () => {
							clearErrors();
							const v = { project: get("project"), priority: get("priority"), due: get("due"), comment: get("comment").trim(), assign: picker ? picker.ids() : [], assignLabels: picker ? picker.labels() : [] };
							const missing = def.need.filter((k) => (k === "assign" ? !v.assign.length : !v[k]));
							if (missing.length) {
								missing.forEach((k) => showError(k, ERRORS[k]));
								const first = body.querySelector('[data-f="' + missing[0] + '"] input,[data-f="' + missing[0] + '"] select,[data-f="' + missing[0] + '"] textarea');
								if (first) first.focus();
								return false;
							}
							return SEND[action](sub, v).then(
								(msg) => finish(msg, "good", sub),
								(e) => {
									if (e.partial) return finish(e.message, "warn", sub);
									const box = body.querySelector(".rq-formerr");
									box.textContent = e.message || "That did not save.";
									box.hidden = false;
									return false;
								}
							);
						},
					},
				],
			});
			trapFocus(m);
		}).catch((e) => PH.toast("Could not load the lists a decision needs: " + (e.message || "try again."), "bad"));
	}

	/** After a decision: say what happened, then reload so every count follows it. */
	function finish(message, kind, sub) {
		PH.toast(message, kind);
		const rows = data ? data.rows : [];
		const at = rows.findIndex((r) => r.name === sub.name);
		const next = rows[at + 1] || rows[at - 1];
		if (next) DevKeys.select(next.name);
		load();
		loadOptions();
	}

	/** Keep Tab inside the dialog and let Enter (or Ctrl/Cmd+Enter in the comment) submit it. */
	function trapFocus(m) {
		const primary = () => m.el.querySelector(".ph-modal__foot .ph-btn:last-child");
		m.el.addEventListener("keydown", (e) => {
			if (e.key === "Tab") {
				const items = PH.$$("a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled])", m.el).filter((x) => x.offsetParent);
				if (!items.length) return;
				const first = items[0], last = items[items.length - 1];
				if (e.shiftKey && document.activeElement === first) {
					e.preventDefault();
					last.focus();
				} else if (!e.shiftKey && document.activeElement === last) {
					e.preventDefault();
					first.focus();
				}
			} else if (e.key === "Enter" && !e.defaultPrevented && !e.isComposing) {
				const tag = e.target.tagName;
				if ((tag === "INPUT" && e.target.type !== "button") || ((e.ctrlKey || e.metaKey) && tag === "TEXTAREA")) {
					e.preventDefault();
					primary().click();
				}
			}
		});
	}

	/* ---- row clicks, menu ---- */
	PH.$("#t-rows").addEventListener("click", (e) => {
		const open = e.target.closest("[data-open]");
		if (open) {
			e.preventDefault();
			return detail(open.dataset.open);
		}
		const btn = e.target.closest("[data-act]");
		if (btn) {
			const r = rowByName(btn.dataset.name);
			DevKeys.select(btn.dataset.name);
			return r && decide(subjectOfRow(r), btn.dataset.act);
		}
		const more = e.target.closest("[data-more]");
		if (more) {
			const r = rowByName(more.dataset.more);
			const shown = ROW_BUTTONS[view()];
			PH.menu(more, r.actions.filter((a) => !shown.includes(a)).map((a) => ({ label: ACTIONS[a].title, danger: !!ACTIONS[a].danger, onClick: () => decide(subjectOfRow(r), a) })));
		}
	});

	/* ---- request detail drawer ---- */
	function detail(name) {
		const opener = document.activeElement;
		const listed = rowByName(name);
		const body = document.createElement("div");
		PH.skeleton(body);
		const m = PH.modal({
			title: "Request " + name, body, size: "lg", drawer: true,
			onClose: () => opener && document.contains(opener) && opener.focus(),
			actions: ((listed && listed.actions) || []).map((a, i) => ({
				label: ACTIONS[a].title, primary: i === 0, danger: !!ACTIONS[a].danger,
				onClick: () => {
					m.close();
					decide(subjectOfRow(listed), a);
					return false;
				},
			})),
		});
		PH.call(READ + "get_request_detail", { name }, { silent: true }).then((d) => {
			const r = d.request, t = d.task;
			m.el.querySelector(".ph-modal__title").textContent = r.title;
			const kv = [
				["Number", '<a class="ph-link ph-mono" target="_blank" rel="noopener" href="/app/request/' + encodeURIComponent(r.name) + '">' + PH.esc(r.name) + "</a>"],
				["Stage", PH.esc(r.status)],
				["Type", PH.esc(r.request_type || "—")],
				["Priority", prioBadge(r.priority)],
				["Product area", PH.esc(r.product_area || "—")],
				["Project", PH.esc(r.project_name || "Not chosen yet")],
				["Raised by", PH.esc(r.raised_by_name) + (r.raised_for ? " (for " + PH.esc(r.raised_for) + ")" : "")],
				["Requested for", PH.esc(r.requested_for_name || "Nobody named")],
				["Raised", PH.esc(PH.fmt.datetime(r.creation)) + " · " + PH.esc(r.age_label) + " ago"],
				["Source", PH.esc(r.source || "—")],
				["Tags", r.tags.length ? r.tags.map((x) => PH.esc(x)).join(", ") : "—"],
			];
			let h = '<dl class="ph-kv">' + kv.map(([k, v]) => "<dt>" + k + "</dt><dd>" + v + "</dd>").join("") + "</dl>";
			h += '<div class="rq-h">What was asked</div><p class="rq-desc">' + (r.description ? PH.esc(r.description) : '<span class="ph-muted">No description was given.</span>') + "</p>";
			if (t) {
				h += '<div class="rq-h">Task</div><dl class="ph-kv"><dt>Task</dt><dd><a class="ph-link ph-mono" target="_blank" rel="noopener" href="/app/task/' + encodeURIComponent(t.name) + '">' + PH.esc(t.name) + "</a></dd>" +
					"<dt>Status</dt><dd>" + PH.esc(t.status === "Overdue" ? "Past its complete-by date" : t.status) + "</dd><dt>Complete by</dt><dd>" + PH.esc(t.due ? PH.fmt.date(t.due) : "Not set") + "</dd>" +
					"<dt>Assigned to</dt><dd>" + PH.esc(t.assignees.length ? t.assignees.join(", ") : "Nobody yet") + "</dd>" +
					(t.completed_on ? "<dt>Completed</dt><dd>" + PH.esc(PH.fmt.date(t.completed_on)) + "</dd>" : "") + "</dl>";
			}
			h += '<div class="rq-h">History and decisions</div>';
			h += d.history.map((e) => '<div class="rq-ev"><b>' + PH.esc(e.title) + "</b><small>" + PH.esc(PH.fmt.datetime(e.at)) + (e.by_name ? " · " + PH.esc(e.by_name) : "") + "</small>" + (e.text ? "<p>" + PH.esc(e.text) + "</p>" : "") + "</div>").join("");
			if (d.history.length <= 1) h += '<div class="ph-muted" style="font-size:13px">No decisions or notes recorded yet.</div>';
			PH.set(body, h);
		}).catch((e) => PH.error(body, e.message || "This request could not be loaded.", () => { m.close(); detail(name); }));
		trapFocus(m);
	}

	/* ---- keyboard (shared layer, dev-v2-keys.js): / search, j k move, Enter details, a p d r o decide ---- */
	const rowOf = (el) => ((PH.$("#t-rows")._view || [])[+el.dataset.i]) || null;
	const KEY_LABEL = { a: "accept", p: "approve", d: "defer", r: "reject", o: "reopen" };
	const decideKey = (k) => ({
		keys: [k], label: KEY_LABEL[k], show: () => canDecideNow,
		check: (el) => {
			const r = rowOf(el);
			if (!r) return "Select a row first";
			return KEY_ACTIONS[k].some((a) => r.actions.includes(a)) ? true : "You cannot " + KEY_LABEL[k] + " this request at this stage";
		},
		run: (el) => {
			const r = rowOf(el);
			decide(subjectOfRow(r), KEY_ACTIONS[k].find((a) => r.actions.includes(a)));
		},
	});
	DevKeys.init({
		title: "Review Queue",
		hint: "#hint",
		refresh: true,
		list: { root: "#t-rows", items: () => PH.$$("#t-rows tbody tr"), id: (el) => (rowOf(el) || {}).name || "#" + el.dataset.i, open: (el) => { const r = rowOf(el); if (r) detail(r.name); } },
		keys: ["a", "p", "d", "r", "o"].map(decideKey),
	});

	/* ---- CSV ---- */
	PH.$("#export").addEventListener("click", () => {
		if (!data || !data.rows.length) return;
		const rows = data.rows.map((r) => ({ ...r, tags: r.tags.join("; "), assignees: r.assignees.join("; ") }));
		PH.csv("review_queue_" + view() + "_" + data.as_of.slice(0, 10) + ".csv", rows, [
			["name", "Request"], ["title", "Title"], ["status", "Stage"], ["request_type", "Type"], ["priority", "Priority"], ["product_area", "Product area"],
			["project_name", "Project"], ["raised_by_name", "Raised by"], ["raised_for", "Raised for"], ["requested_for_name", "Requested for"],
			["creation", "Raised"], ["age_days", "Days waiting"], ["stage_since", "In this stage since"], ["task", "Task"], ["due", "Complete by"], ["assignees", "Assigned to"], ["tags", "Tags"],
		].map(([key, label]) => ({ key, label })));
	});

	PH.onRefresh(() => {
		loadOptions();
		return load();
	});
	PH.ready(() => {
		paintChrome();
		loadOptions().then(paintChrome);
		load();
	});
})();
