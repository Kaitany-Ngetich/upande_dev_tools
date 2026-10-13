/* My Backlog v2 (www/my-backlog-v2.html).
 *
 * Reads: upande_dev_tools.api.v2.my_backlog (scoped to the signed-in user, no user argument).
 * Writes: the SAME endpoint the current page uses, api.requests.update_task_status, which
 * only accepts Dev Team / Projects Manager / System Manager - so the controls that call it
 * are shown only when the read model says `can_change_status`. */
(function () {
	"use strict";

	const API = "upande_dev_tools.api.v2.my_backlog.";
	const STATUS_WRITE = "upande_dev_tools.api.requests.update_task_status";
	const PREFS_KEY = "dpx-my-backlog-v2";
	const VIEWS = ["overview", "tasks", "meetings", "done", "requests"];
	const LAYOUTS = ["board", "list"];
	const FILTERS = ["due", "status", "priority", "project", "module", "q", "from", "to"];
	const BOARD_COLUMNS = ["Overdue", "Open", "Working", "Pending Review"];
	const BOARD_COLUMN_LIMIT = 40;
	const EXPECTED_LIMIT = 6;
	const DUE_LABEL = { overdue: "Overdue", today: "Due today", week: "Due this week", later: "Due later", none: "No due date" };
	const PRIORITY_TONE = { Urgent: "bad", High: "warn" };
	const STATUS_TONE = { Overdue: "warn", Working: "good", "Pending Review": "signal", Open: "outline" };
	const REQ_TONE = { Completed: "good", Closed: "good", "In Progress": "good", Approved: "signal", Scheduled: "signal", Rejected: "outline", Withdrawn: "outline", Deferred: "outline" };
	const REQ_LABEL = { "": "Waiting for a decision", "Under Review": "Waiting for a decision", Approved: "Accepted", Scheduled: "Scheduled", "In Progress": "Being built", Completed: "Done", Rejected: "Not going ahead", Deferred: "Parked for now", Withdrawn: "Withdrawn", Closed: "Closed" };

	function readPrefs() {
		try {
			return JSON.parse(localStorage.getItem(PREFS_KEY) || "{}") || {};
		} catch (e) {
			return {};
		}
	}
	function writePrefs(patch) {
		try {
			localStorage.setItem(PREFS_KEY, JSON.stringify(Object.assign(readPrefs(), patch)));
		} catch (e) {
			// private mode: preferences simply do not stick
		}
	}

	const prefs = readPrefs();
	const st = PH.state({
		view: VIEWS.includes(prefs.view) ? prefs.view : "overview",
		layout: LAYOUTS.includes(prefs.layout) ? prefs.layout : "board",
		due: "", status: "", priority: "", project: "", module: "", q: "", from: "", to: "",
	});
	const n = PH.fmt.num;
	let data = null;
	let seq = 0;

	const view = () => (VIEWS.includes(st.get("view")) ? st.get("view") : "overview");
	const layout = () => (LAYOUTS.includes(st.get("layout")) ? st.get("layout") : "board");
	const canWrite = () => !!(data && data.can_change_status);

	const badge = (txt, tone) => `<span class="ph-badge ph-badge--${tone || "outline"}">${PH.esc(txt)}</span>`;
	const priorityCell = (v) => (v ? badge(v, PRIORITY_TONE[v] || "outline") : '<span class="ph-muted">-</span>');
	const docLink = (dt, name, label) => `<a class="ph-link" target="_blank" rel="noopener" href="/app/${dt}/${encodeURIComponent(name)}">${PH.esc(label || name)}</a>`;

	function dueText(r) {
		if (r.due_date == null) return r.bucket === "overdue" ? "Marked overdue, no date" : "No due date";
		const d = r.days_to_due;
		if (d === 0) return "Today";
		if (d === 1) return "Tomorrow";
		if (d === -1) return "1 day overdue";
		if (d < 0) return -d + " days overdue";
		if (d <= 6) return "In " + d + " days";
		return PH.fmt.date(r.due_date);
	}
	const dueCell = (v, r) =>
		`<span class="${r.bucket === "overdue" ? "mb2-late" : r.bucket === "today" ? "ph-strong" : ""}">${PH.esc(dueText(r))}</span>` +
		(r.due_date ? `<span class="mb2-sub">${PH.esc(PH.fmt.date(r.due_date))}</span>` : "");

	/* ---- status control (writers only) ---- */
	function statusSelect(task) {
		const opts = data.status_options.map((s) => `<option${s === task.status ? " selected" : ""}>${PH.esc(s)}</option>`).join("");
		return `<select class="ph-select mb2-status" data-status-for="${PH.esc(task.name)}" aria-label="Status of ${PH.esc(task.subject)}">${opts}</select>`;
	}
	const statusCell = (v, r) => (canWrite() ? statusSelect(r) : badge(v, STATUS_TONE[v]));

	/** Change a task's status through the existing endpoint, then re-read so every count follows. */
	function setStatus(name, status) {
		const task = data.tasks.find((t) => t.name === name);
		if (!task || task.status === status) return Promise.resolve();
		return PH.call(STATUS_WRITE, { name, status }, { silent: true })
			.then(() => {
				PH.toast(task.subject + " is now " + status, "good");
				return load();
			})
			.catch((e) => {
				PH.toast("Could not update that status. " + (e.message || ""), "bad");
				paintTasks();
			});
	}
	document.addEventListener("change", (e) => {
		const sel = e.target.closest("[data-status-for]");
		if (sel) setStatus(sel.dataset.statusFor, sel.value);
	});

	/* ---- tables ---- */
	const tTasks = PH.table("#t-tasks", {
		rows: [], compact: true, pageSize: 25, empty: "Nothing open matches these filters", onRowClick: (r) => taskDetail(r.name),
		sort: { key: "due_date", dir: "asc" },
		columns: [
			{ key: "subject", label: "Task", cls: "is-strong is-wrap", html: (v, r) => PH.esc(v) + `<span class="mb2-sub">${PH.esc(r.name)}${r.assignees > 1 ? " · shared with " + (r.assignees - 1) + " other" + (r.assignees > 2 ? "s" : "") : ""}</span>` },
			{ key: "effective_status", label: "Status", html: statusCell },
			{ key: "priority", label: "Priority", html: priorityCell },
			{ key: "due_date", label: "Due", html: dueCell },
			{ key: "project", label: "Project", format: (v) => v || "-" },
			{ key: "module", label: "Module", format: (v) => v || "-" },
			{ key: "age_days", label: "Age (days)", num: true },
		],
	});
	const tDone = PH.table("#t-done", {
		rows: [], compact: true, pageSize: 25, empty: "Nothing completed in the last 14 days", onRowClick: (r) => taskDetail(r.name),
		sort: { key: "done_on", dir: "desc" },
		columns: [
			{ key: "subject", label: "Task", cls: "is-strong is-wrap", html: (v, r) => PH.esc(v) + `<span class="mb2-sub">${PH.esc(r.name)}</span>` },
			{ key: "done_on", label: "Completed", html: (v, r) => PH.esc(PH.fmt.date(v)) + (r.approx ? '<span class="mb2-sub">approx. (last updated)</span>' : "") },
			{ key: "priority", label: "Priority", html: priorityCell },
			{ key: "project", label: "Project", format: (v) => v || "-" },
			{ key: "module", label: "Module", format: (v) => v || "-" },
		],
	});
	const tReq = PH.table("#t-requests", {
		rows: [], compact: true, pageSize: 25, empty: "You have not raised any requests that match", onRowClick: (r) => requestDetail(r.name),
		sort: { key: "created", dir: "desc" },
		columns: [
			{ key: "title", label: "Request", cls: "is-strong is-wrap", html: (v, r) => PH.esc(v) + `<span class="mb2-sub">${PH.esc(r.name)}</span>` },
			{ key: "state", label: "Where it is", html: (v) => badge(REQ_LABEL[v] || v, REQ_TONE[v] || "warn") },
			{ key: "request_type", label: "Type", format: (v) => v || "-" },
			{ key: "priority", label: "Priority", html: priorityCell },
			{ key: "project", label: "Project", format: (v) => v || "-" },
			{ key: "created", label: "Raised", format: (v) => PH.fmt.date(v) },
		],
	});

	/* ---- board ---- */
	function cardHtml(t, writable) {
		return `<div class="mb2-card" tabindex="0" role="button" data-name="${PH.esc(t.name)}"${writable ? ' draggable="true"' : ""}>` +
			`<div class="mb2-card__m">${t.module ? badge(t.module) : ""}${t.priority && t.priority !== "Low" ? badge(t.priority, PRIORITY_TONE[t.priority]) : ""}</div>` +
			`<div class="mb2-card__t">${PH.esc(t.subject)}</div>` +
			`<div class="mb2-card__m">${t.project ? `<span>${PH.esc(t.project)}</span>` : ""}${t.due_date ? `<span class="${t.bucket === "overdue" ? "mb2-late" : ""}">${PH.esc(dueText(t))}</span>` : ""}</div></div>`;
	}
	function paintBoard() {
		const writable = canWrite();
		const host = PH.$("#board");
		host.innerHTML = '<div class="mb2-cols">' + BOARD_COLUMNS.map((status) => {
			const items = data.tasks.filter((t) => t.effective_status === status);
			const shown = items.slice(0, BOARD_COLUMN_LIMIT).map((t) => cardHtml(t, writable)).join("");
			const more = items.length > BOARD_COLUMN_LIMIT ? `<div class="mb2-col__blank">+ ${items.length - BOARD_COLUMN_LIMIT} more, see the List</div>` : "";
			// "Overdue" is decided by the due date, so a card cannot be dropped into it.
			const drop = writable && status !== "Overdue";
			return `<div class="mb2-col${status === "Overdue" ? " is-bad" : ""}"><div class="mb2-col__hd"><span>${PH.esc(status)}</span><span>${items.length}</span></div>` +
				`<div class="mb2-col__body"${drop ? ` data-drop="${PH.esc(status)}"` : ""}>${shown || '<div class="mb2-col__blank">Nothing here</div>'}${more}</div></div>`;
		}).join("") + "</div>";
	}
	const boardEl = PH.$("#board");
	boardEl.addEventListener("click", (e) => {
		const card = e.target.closest(".mb2-card");
		if (card) taskDetail(card.dataset.name);
	});
	boardEl.addEventListener("keydown", (e) => {
		const card = e.target.closest(".mb2-card");
		if (card && (e.key === "Enter" || e.key === " ")) {
			e.preventDefault();
			taskDetail(card.dataset.name);
		}
	});
	boardEl.addEventListener("dragstart", (e) => {
		const card = e.target.closest(".mb2-card");
		if (!card) return;
		e.dataTransfer.setData("text/plain", card.dataset.name);
		card.classList.add("is-dragging");
	});
	boardEl.addEventListener("dragend", (e) => {
		const card = e.target.closest(".mb2-card");
		if (card) card.classList.remove("is-dragging");
	});
	boardEl.addEventListener("dragover", (e) => {
		const zone = e.target.closest("[data-drop]");
		if (!zone) return;
		e.preventDefault();
		zone.classList.add("is-over");
	});
	boardEl.addEventListener("dragleave", (e) => {
		const zone = e.target.closest("[data-drop]");
		if (zone) zone.classList.remove("is-over");
	});
	boardEl.addEventListener("drop", (e) => {
		const zone = e.target.closest("[data-drop]");
		if (!zone) return;
		e.preventDefault();
		zone.classList.remove("is-over");
		const name = e.dataTransfer.getData("text/plain");
		const card = PH.$('.mb2-card[data-name="' + CSS.escape(name) + '"]', boardEl);
		if (card) card.classList.add("is-busy");
		setStatus(name, zone.dataset.drop);
	});

	/* ---- drill-down ---- */
	function kv(rows) {
		return '<dl class="ph-kv">' + rows.filter((r) => r[1] != null && r[1] !== "").map((r) => `<dt>${PH.esc(r[0])}</dt><dd>${r[2] ? r[1] : PH.esc(r[1])}</dd>`).join("") + "</dl>";
	}
	function detail(title, sub, method, name, build) {
		const body = document.createElement("div");
		PH.skeleton(body);
		const m = PH.modal({ title, sub, body, size: "lg" });
		PH.call(API + method, { name }, { silent: true })
			.then((d) => { body.innerHTML = build(d); })
			.catch((e) => PH.error(body, e.message, () => { m.close(); detail(title, sub, method, name, build); }));
	}
	function taskDetail(name) {
		detail(name, "Task", "get_task_detail", name, (d) => {
			const t = d.task;
			const status = canWrite() ? statusSelect(t) : badge(t.status, STATUS_TONE[t.status]);
			const dueInfo = { due_date: t.due_date, days_to_due: t.days_to_due, bucket: t.days_to_due != null && t.days_to_due < 0 ? "overdue" : "" };
			return `<h3 class="ph-strong ph-mb">${PH.esc(t.subject)}</h3>` + kv([
				["Status", status, 1], ["Priority", t.priority], ["Project", t.project], ["Module", t.module],
				["Due", t.due_date ? PH.fmt.date(t.due_date) + " (" + dueText(dueInfo) + ")" : "No due date"],
				["Starts", t.start_date ? PH.fmt.date(t.start_date) : ""], ["Raised", t.created ? PH.fmt.date(t.created) : ""], ["Completed", t.completed_on ? PH.fmt.date(t.completed_on) : ""],
				["Last changed", t.modified], ["Parent task", t.parent_task], ["People on it", t.assignees],
				["Requests", t.requests.map((r) => docLink("request", r.name, r.title)).join("<br>"), 1],
			]) + (t.description ? `<p class="ph-mt ph-muted" style="white-space:pre-wrap">${PH.esc(t.description)}</p>` : "") +
				`<p class="ph-mt">${docLink("task", t.name, "Open the task in the desk")}</p>`;
		});
	}
	function requestDetail(name) {
		detail(name, "Request", "get_request_detail", name, (d) => {
			const r = d.request;
			return `<h3 class="ph-strong ph-mb">${PH.esc(r.title)}</h3>` + kv([
				["Where it is", badge(REQ_LABEL[r.state] || r.state, REQ_TONE[r.state] || "warn"), 1], ["Type", r.request_type], ["Priority", r.priority], ["Project", r.project],
				["Linked task", r.linked_task ? docLink("task", r.linked_task) : "", 1], ["Source", r.source], ["Raised", r.created ? PH.fmt.date(r.created) : ""], ["Last changed", r.modified],
				["Outcome notes", r.resolution_notes],
			]) + (r.description ? `<p class="ph-mt ph-muted" style="white-space:pre-wrap">${PH.esc(r.description)}</p>` : "") +
				`<p class="ph-mt">${docLink("request", r.name, "Open the request in the desk")} · <a class="ph-link" href="/requests-v2" target="_blank" rel="noopener">Requests</a></p>`;
		});
	}
	function meetingDetail(m) {
		PH.modal({
			title: m.subject, sub: "Meeting",
			body: kv([["Starts", PH.fmt.datetime(m.starts_on)], ["Ends", m.ends_on ? PH.fmt.datetime(m.ends_on) : ""], ["Where", m.location], ["Category", m.category],
				["Join", m.link ? `<a class="ph-link" href="${PH.esc(m.link)}" target="_blank" rel="noopener">Open the meeting link</a>` : "", 1]]) +
				`<p class="ph-mt">${docLink("event", m.name, "Open the event in the desk")}</p>`,
		});
	}

	/* ---- render ---- */
	function bars(sel, rows, onClick) {
		const max = Math.max(1, ...rows.map((x) => x.count));
		PH.set(sel, rows.map((x, i) =>
			`<div class="mb2-bar${onClick ? " is-link" : ""}" data-i="${i}" title="${PH.esc(x.label)}: ${x.count}"><span>${PH.esc(x.label)}</span><b>${n(x.count)}</b><div class="ph-progress"><i class="good" style="width:${(100 * x.count) / max}%"></i></div></div>`
		).join("") || '<div class="ph-empty">Nothing here</div>');
		if (onClick) PH.$$(".mb2-bar", PH.$(sel)).forEach((el) => el.addEventListener("click", () => onClick(rows[+el.dataset.i])));
	}

	function paintExpected() {
		const groups = [
			["Overdue", data.tasks.filter((t) => t.bucket === "overdue"), "is-bad", { due: "overdue" }],
			["Today", data.tasks.filter((t) => t.bucket === "today"), "", { due: "today" }],
			["Tomorrow", data.tasks.filter((t) => t.days_to_due === 1), "", { due: "week" }],
		];
		PH.set("#expected", '<div class="mb2-tl">' + groups.map(([label, rows, tone], g) => {
			const items = rows.slice(0, EXPECTED_LIMIT).map((t) =>
				`<div class="mb2-tl__item" data-name="${PH.esc(t.name)}" role="button" tabindex="0"><span class="mb2-tl__t">${PH.esc(t.subject)}${t.project ? `<span class="mb2-sub">${PH.esc(t.project)}</span>` : ""}</span>` +
				(t.bucket === "overdue" && t.days_to_due != null ? `<span class="mb2-late">${-t.days_to_due}d</span>` : "") + "</div>").join("");
			const more = rows.length > EXPECTED_LIMIT ? `<div class="mb2-tl__more"><a class="ph-link" data-group="${g}">+ ${rows.length - EXPECTED_LIMIT} more</a></div>` : "";
			return `<div class="mb2-tl__group ${tone}"><div class="mb2-tl__hd">${label}<span>${rows.length || ""}</span></div>` +
				(rows.length ? items + more : `<div class="mb2-tl__none">${tone ? "Nothing overdue." : "Nothing here. Clear."}</div>`) + "</div>";
		}).join("") + "</div>");
		const host = PH.$("#expected");
		host.onclick = (e) => {
			const more = e.target.closest("[data-group]");
			if (more) return st.set(Object.assign({ view: "tasks" }, groups[+more.dataset.group][3]));
			const row = e.target.closest("[data-name]");
			if (row) taskDetail(row.dataset.name);
		};
		host.onkeydown = (e) => {
			const row = e.target.closest("[data-name]");
			if (row && e.key === "Enter") taskDetail(row.dataset.name);
		};
	}

	function meetingRows(list, withDays) {
		let html = "", day = "";
		list.forEach((m, i) => {
			if (withDays && m.date !== day) { day = m.date; html += `<div class="mb2-day">${m.is_today ? "Today · " : ""}${PH.esc(PH.fmt.date(day))}</div>`; }
			html += `<div class="mb2-meet" data-i="${i}"><div class="ph-strong">${m.all_day ? "All day" : PH.esc(m.starts_on.slice(11))}${m.started ? "<small>already started</small>" : ""}</div>` +
				`<div><span class="ph-strong">${PH.esc(m.subject)}</span><small>${PH.esc([m.category, m.location].filter(Boolean).join(" · "))}</small></div>` +
				(m.link ? `<a class="ph-btn ph-btn--sm" href="${PH.esc(m.link)}" target="_blank" rel="noopener" data-join>Join</a>` : "<span></span>") + "</div>";
		});
		return html;
	}
	function paintMeetings(sel, list, withDays, emptyTitle, emptyText) {
		if (!list.length) return PH.empty(sel, emptyTitle, emptyText);
		PH.set(sel, meetingRows(list, withDays));
		PH.$$(".mb2-meet", PH.$(sel)).forEach((el) => el.addEventListener("click", (e) => { if (!e.target.closest("[data-join]")) meetingDetail(list[+el.dataset.i]); }));
	}

	function paintTasks() {
		if (!data) return;
		const board = layout() === "board";
		PH.$("#board").hidden = !board;
		PH.$("#t-tasks").hidden = board;
		if (board) paintBoard();
		else tTasks.update(data.tasks);
		PH.text("#tasks-note", board
			? (canWrite() ? "Most urgent first. Drag a card to change its status; click for details." : "Most urgent first. Click a task for details.")
			: "Most urgent first. Click a task for details.");
	}

	function rowsFor(v) {
		if (!data) return [];
		return { tasks: data.tasks, meetings: data.meetings, done: data.completed, requests: data.requests }[v === "overview" ? "tasks" : v] || [];
	}

	function paintView() {
		const v = view();
		PH.$$("#tabs .ph-tab").forEach((b) => b.classList.toggle("is-on", b.dataset.view === v));
		VIEWS.forEach((x) => { PH.$("#view-" + x).hidden = x !== v; });
		const rows = rowsFor(v);
		const exp = PH.$("#export");
		exp.disabled = !rows.length;
		exp.title = rows.length ? "Download the " + v + " list as CSV" : "Nothing to export here";
		PH.$("#f-clear").hidden = !FILTERS.some((k) => st.get(k));
		paintTasks();
	}

	function redrawCharts() {
		const due = data.due_chart, done = data.done_chart;
		PH.chart("#c-due", {
			type: "bar", labels: due.map((x) => PH.fmt.date(x.date, true)),
			series: [{ label: "Tasks due", data: due.map((x) => x.count), color: PH.palette[0] }], options: { scales: { y: { ticks: { precision: 0 } } } },
			onClick: (i) => { const d = due[i]; if (d) st.set({ view: "tasks", from: d.date, to: d.date, due: "" }); },
		});
		PH.chart("#c-done", {
			type: "line", labels: done.map((x) => PH.fmt.date(x.date, true)),
			series: [{ label: "Tasks completed", data: done.map((x) => x.count), color: PH.statusColor.good, fill: true }], options: { scales: { y: { ticks: { precision: 0 } } } },
		});
	}

	function render() {
		const d = data, k = d.kpis, s = st.get();
		PH.options("#f-priority", d.options.priorities, s.priority);
		PH.options("#f-project", d.options.projects, s.project);
		PH.options("#f-module", d.options.modules, s.module);
		const scope = [DUE_LABEL[s.due], s.status, s.priority, s.project, s.module, s.q && "“" + s.q + "”", (s.from || s.to) && "due " + (s.from ? PH.fmt.date(s.from, true) : "…") + " to " + (s.to ? PH.fmt.date(s.to, true) : "…")].filter(Boolean);
		PH.text("#sub", PH.fmt.plural(k.open, "open task") + (k.overdue ? " · " + k.overdue + " overdue" : "") + " · today is " + PH.fmt.date(d.today) + (scope.length ? " · " + scope.join(" · ") : " · all my work"));

		const tr = k.completed_week - k.completed_prev_week;
		PH.kpis("#kpis", [
			{ label: "Open tasks", value: k.open, unit: "assigned to me", dark: true, title: "Tasks assigned to you that are not completed, cancelled or templates", onClick: () => st.set({ view: "tasks", due: "" }) },
			{ label: "Overdue", value: k.overdue, unit: k.overdue ? "past due date" : "none, nice", onClick: () => st.set({ view: "tasks", due: "overdue" }), title: "Due date before today (site date)" },
			{ label: "Due today", value: k.due_today, unit: "+" + k.due_week + " this week", onClick: () => st.set({ view: "tasks", due: "today" }) },
			{ label: "Done, 7 days", value: k.completed_week, unit: "last 7 days", trend: k.completed_week || k.completed_prev_week ? { dir: tr > 0 ? "up" : tr < 0 ? "down" : "flat", text: tr > 0 ? "+" + tr : String(tr), note: "vs the 7 days before" } : null, title: "Completed date is the recorded date, else the last-updated date" },
			{ label: "Requests open", value: k.requests_in_flight, unit: "of " + k.requests_total + " raised", onClick: () => st.set({ view: "requests" }) },
			{ label: "Meetings today", value: k.meetings_today, unit: k.meetings + " in 7 days", onClick: () => st.set({ view: "meetings" }) },
		]);

		const notes = [];
		if (k.overdue) notes.push(`<div class="ph-notice ph-notice--warn">${k.overdue} of your tasks ${k.overdue === 1 ? "is" : "are"} past due.<button class="ph-btn ph-btn--sm" data-show-overdue type="button">Show them</button></div>`);
		if (d.truncated) notes.push(`<div class="ph-notice ph-notice--signal">Showing the first ${n(d.row_limit)} open tasks only; narrow the filters to see the rest.</div>`);
		if (k.no_due_date) notes.push(`<div class="ph-notice ph-notice--signal">${n(k.no_due_date)} of your open tasks have no due date, so they cannot show as late. They sit last in the list.</div>`);
		PH.set("#notes", notes.join(""));

		tDone.update(d.completed);
		tReq.update(d.requests);
		paintMeetings("#l-meetings", d.meetings, true, "No meetings coming up", "Nothing in the next 7 days where you are a participant.");
		paintMeetings("#l-today-meetings", d.meetings.filter((m) => m.is_today), false, "No meetings today", "Nothing on your calendar today.");
		paintExpected();
		PH.text("#tc-tasks", n(k.open));
		PH.text("#tc-meetings", n(k.meetings));
		PH.text("#tc-done", n(d.completed_total));
		PH.text("#tc-requests", n(d.requests.length));
		PH.text("#c-done-meta", k.completed_week + k.completed_prev_week + " in total");
		PH.text("#done-note", d.completed.some((c) => c.approx) ? "Dated by the recorded completion date, or the last-updated date where none was recorded." : "");
		bars("#by-bucket", d.buckets, (b) => st.set({ view: "tasks", due: b.key }));
		bars("#by-status", d.by_status, (b) => st.set({ view: "tasks", status: b.label }));
		bars("#by-module", d.by_module.slice(0, 8), (b) => { if (b.label !== "No module") st.set({ view: "tasks", module: b.label }); });
		bars("#by-priority", d.by_priority, (b) => { if (b.label !== "No priority") st.set({ view: "tasks", priority: b.label }); });
		bars("#by-age", d.age_bands);
		redrawCharts();
		paintView();
	}

	function load() {
		const s = st.get(), my = ++seq;
		PH.loadingKpis("#kpis", true);
		const args = { due: s.due, status: s.status, priority: s.priority, project: s.project, module: s.module, q: s.q, from_date: s.from, to_date: s.to };
		return PH.call(API + "get_my_backlog", args, { silent: true })
			.then((m) => { if (my !== seq) return; data = m; render(); PH.markUpdated(); })
			.catch((e) => {
				if (my !== seq) return;
				PH.loadingKpis("#kpis", false);
				["#expected", "#l-today-meetings", "#c-due", "#c-done", "#by-bucket", "#by-status", "#by-module", "#by-priority", "#by-age", "#t-tasks", "#l-meetings", "#t-done", "#t-requests"].forEach((x) => PH.error(x, e.message, () => load()));
				PH.error("#board", e.message, () => load());
				paintView();
			});
	}

	/* ---- export ---- */
	const CSVS = {
		tasks: ["my_open_tasks", [["name", "Task"], ["subject", "Subject"], ["effective_status", "Status"], ["priority", "Priority"], ["due_date", "Due date"], ["days_to_due", "Days to due (negative = overdue)"], ["project", "Project"], ["module", "Module"], ["created", "Raised"], ["age_days", "Age (days)"]]],
		meetings: ["my_meetings", [["subject", "Meeting"], ["starts_on", "Starts"], ["ends_on", "Ends"], ["location", "Where"], ["category", "Category"], ["link", "Link"]]],
		done: ["my_completed_tasks", [["name", "Task"], ["subject", "Subject"], ["done_on", "Completed"], ["priority", "Priority"], ["project", "Project"], ["module", "Module"]]],
		requests: ["my_requests", [["name", "Request"], ["title", "Title"], ["state", "State"], ["request_type", "Type"], ["priority", "Priority"], ["project", "Project"], ["created", "Raised"]]],
	};
	PH.$("#export").addEventListener("click", () => {
		const v = view() === "overview" ? "tasks" : view(), c = CSVS[v], rows = rowsFor(v);
		if (c && rows.length) PH.csv(c[0] + "_" + (data ? data.today : "") + ".csv", rows, c[1].map(([key, label]) => ({ key, label })));
	});

	/* ---- wiring ---- */
	PH.$("#f-search-ico").innerHTML = PH.icon("search", 14);
	PH.pills("#f-due", st, "due");
	PH.pills("#f-layout", st, "layout");
	PH.bindSelect("#f-status", st, "status");
	PH.bindSelect("#f-priority", st, "priority");
	PH.bindSelect("#f-project", st, "project");
	PH.bindSelect("#f-module", st, "module");
	PH.bindSearch("#f-q", st, "q");
	PH.dateRange({ from: "#f-from", to: "#f-to", state: st });
	PH.$("#f-clear").addEventListener("click", () => st.set(Object.fromEntries(FILTERS.map((k) => [k, ""]))));
	PH.$("#tabs").addEventListener("click", (e) => {
		const b = e.target.closest("[data-view]");
		if (b) st.set({ view: b.dataset.view });
	});
	document.addEventListener("click", (e) => {
		const link = e.target.closest("[data-view-link]");
		if (link) { e.preventDefault(); st.set({ view: link.dataset.viewLink }); }
		if (e.target.closest("[data-show-overdue]")) st.set({ view: "tasks", due: "overdue" });
	});
	// Shared keyboard layer (dev-v2-keys.js): / search, j k move, Enter open, r refresh, ? help.
	DevKeys.init({
		title: "My Backlog",
		list: { root: "#ph-main", items: () => PH.$$("#expected [data-name], #board .mb2-card, #t-tasks tbody tr, .mb2-meet, #t-done tbody tr, #t-requests tbody tr") },
	});

	st.on((s, changed) => {
		if (changed.includes("view")) writePrefs({ view: s.view });
		if (changed.includes("layout")) writePrefs({ layout: s.layout });
		paintView();
		if (changed.every((k) => k === "view" || k === "layout")) return;
		load();
	});
	PH.kpiSkeleton("#kpis", ["Open tasks", "Overdue", "Due today", "Done, 7 days", "Requests open", "Meetings today"]);
	PH.onRefresh(() => load());
	PH.ready(() => { paintView(); load(); });
})();
