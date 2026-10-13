/* Requests v2 (www/requests-v2.html): raise a request, follow every request, and the tracker views.
 *
 * Reads : upande_dev_tools.api.v2.requests (overview + list rows, one request's detail, the form's choices).
 * Writes: the SAME endpoints the current /requests-portal page calls, in upande_dev_tools.api.requests
 *         (create_request, update_request, withdraw_request, confirm_request_complete) plus Frappe's
 *         upload_file for the attachment. Nothing here re-implements their validation or permissions;
 *         the page only hides the buttons the endpoint would refuse (flags can_edit / can_withdraw /
 *         can_confirm / triage_fields come from the server).
 */
(function () {
	"use strict";

	const API = "upande_dev_tools.api.v2.requests.";
	const WRITE = "upande_dev_tools.api.requests.";
	const ALL_TIME_FROM = "2000-01-01";
	const PAGE_SIZE = 30;
	const NONE = "__none__";
	const PICKER_LIMIT = 50;
	const TITLE_MAX = 140;
	const PRIORITY_RANK = { Urgent: 4, High: 3, Medium: 2, Low: 1 };
	// workflow state -> [badge class, plain-language label]; same wording as the current page.
	const STAGE = {
		"Under Review": ["ph-badge--signal", "Waiting for a decision"],
		Approved: ["ph-badge--ink", "Accepted"],
		Scheduled: ["ph-badge--ink", "Scheduled"],
		"In Progress": ["ph-badge--ink", "Being built"],
		Completed: ["ph-badge--good", "Done"],
		Rejected: ["ph-badge--outline", "Not going ahead"],
		Deferred: ["ph-badge--warn", "Parked for now"],
		Withdrawn: ["ph-badge--outline", "Withdrawn"],
		Closed: ["ph-badge--good", "Closed"],
	};
	const KPI_LABELS = ["Raised", "Still open", "Closed out", "First response", "Time to close"];
	const FILTERS = [
		["status", "status"],
		["scope", "scope"],
		["request_type", "type"],
		["priority", "priority"],
		["product_area", "area"],
		["requester", "requester"],
		["assignee", "assignee"],
		["project", "project"],
		["tag", "tag"],
		["mine", "mine"],
		["q", "q"],
	];
	const VIEWS = ["requests", "overview", "table"];

	const today = PH.date.today();
	const presets = {
		"30d": () => [PH.date.add(today, -29), today],
		"90d": () => [PH.date.add(today, -89), today],
		ytd: () => [today.slice(0, 4) + "-01-01", today],
		all: () => [ALL_TIME_FROM, today],
	};
	const st = PH.state({
		view: "requests",
		from: ALL_TIME_FROM,
		to: today,
		scope: "",
		status: "",
		type: "",
		priority: "",
		area: "",
		requester: "",
		assignee: "",
		project: "",
		tag: "",
		mine: "",
		q: "",
		sort: "newest",
	});
	let data = null;
	let seq = 0;
	let shown = PAGE_SIZE;
	let formOptions = null;

	/* ---------- small helpers ---------- */

	const stageLabel = (s) => (STAGE[s] ? STAGE[s][1] : s || "—");
	const badge = (s) => `<span class="ph-badge ${(STAGE[s] || [""])[0]}">${PH.esc(stageLabel(s))}</span>`;
	const dshort = (v) => (v ? PH.fmt.date(String(v).slice(0, 10)) : "—");
	const when = (v) => (v ? PH.fmt.datetime(v) : "—");
	const plural = (n, a, b) => PH.fmt.num(n) + " " + (n === 1 ? a : b || a + "s");
	const message = (e, fallback) => (e && e.message) || fallback;

	function dur(h) {
		if (h == null) return "—";
		if (h < 1) return "under 1 hour";
		if (h < 48) return (h < 10 ? h.toFixed(1) : Math.round(h)) + " hours";
		return (h / 24).toFixed(1) + " days";
	}
	function durParts(h) {
		if (h == null) return ["—", ""];
		if (h < 1) return ["<1", "hour"];
		if (h < 48) return [h < 10 ? h.toFixed(1) : String(Math.round(h)), "hours"];
		return [(h / 24).toFixed(1), "days"];
	}
	function args() {
		const s = st.get();
		const a = { from_date: s.from, to_date: s.to };
		FILTERS.forEach(([k, sk]) => {
			if (s[sk]) a[k] = s[sk];
		});
		return a;
	}

	/* ---------- filter bar ---------- */

	PH.kpiSkeleton("#kpis", KPI_LABELS);
	PH.set("#s-icon", PH.icon("search", 16));
	PH.pills("#f-scope", st, "scope");
	PH.pills("#f-mine", st, "mine");
	[
		["#f-status", "status"],
		["#f-type", "type"],
		["#f-priority", "priority"],
		["#f-area", "area"],
		["#f-requester", "requester"],
		["#f-assignee", "assignee"],
		["#f-project", "project"],
		["#f-tag", "tag"],
		["#f-sort", "sort"],
	].forEach(([sel, key]) => PH.bindSelect(sel, st, key));
	PH.bindSearch("#f-q", st, "q");
	PH.dateRange({ from: "#f-from", to: "#f-to", state: st });

	function paintPresets() {
		const s = st.get();
		PH.$$("#f-preset button").forEach((b) => {
			const p = presets[b.dataset.value]();
			b.classList.toggle("is-on", p[0] === s.from && p[1] === s.to);
		});
	}
	PH.$("#f-preset").addEventListener("click", (e) => {
		const b = e.target.closest("button[data-value]");
		if (b) {
			const p = presets[b.dataset.value]();
			st.set({ from: p[0], to: p[1] });
		}
	});
	PH.$("#tabs").addEventListener("click", (e) => {
		const b = e.target.closest("[data-view]");
		if (b) st.set({ view: b.dataset.view });
	});

	/* ---------- breakdown tables (overview) ---------- */

	function agg(sel, label, onClick, labelOf) {
		return PH.table(sel, {
			compact: true,
			pageSize: 10,
			empty: "Nothing raised in this period",
			rows: [],
			columns: [
				{
					key: "label",
					label,
					cls: "is-strong",
					html: (v, r) => PH.esc(labelOf ? labelOf(v) : v) + (r.disabled ? " (retired)" : ""),
				},
				{ key: "total", label: "All", num: true },
				{ key: "open", label: "Open", num: true },
				{ key: "closed", label: "Closed", num: true },
			],
			onRowClick: onClick,
		});
	}
	const toggle = (k) => (r) => st.set({ [k]: st.get(k) === r.key ? "" : r.key });
	const tStatus = agg("#by-status", "Status", toggle("status"), stageLabel);
	const tType = agg("#by-type", "Kind", toggle("type"));
	const tPrio = agg("#by-priority", "Priority", toggle("priority"));
	const tArea = agg("#by-area", "Module", toggle("area"));
	const tReq = agg("#by-requester", "Raised by", toggle("requester"));
	const tDup = PH.table("#dups", {
		compact: true,
		pageSize: 8,
		empty: "No repeated titles in this view",
		rows: [],
		columns: [
			{ key: "title", label: "Title", cls: "is-wrap is-strong" },
			{ key: "count", label: "Times raised", num: true },
			{
				key: "ids",
				label: "Requests",
				html: (v, r) =>
					r.requests
						.map((x) => `<a href="#" data-open="${PH.esc(x.name)}">${PH.esc(x.name.replace("REQ-", ""))}</a>`)
						.join(", "),
			},
		],
	});

	/* ---------- table view ---------- */

	const tList = PH.table("#t-list", {
		pageSize: 25,
		sort: { key: "creation", dir: "desc" },
		empty: "No requests match",
		emptyText: "Try widening the dates or clearing a filter.",
		rows: [],
		columns: [
			{ key: "name", label: "Request", cls: "ph-mono is-strong" },
			{
				key: "title",
				label: "Title",
				cls: "is-wrap",
				html: (v, r) =>
					PH.esc(v) +
					(r.reopened ? ' <span class="ph-badge ph-badge--warn" title="Went back to review">Reopened</span>' : "") +
					(r.duplicates
						? ' <span class="ph-badge ph-badge--outline" title="Another request has the same title">Same title ×' +
						  (r.duplicates + 1) +
						  "</span>"
						: ""),
			},
			{ key: "request_type", label: "Kind" },
			{ key: "workflow_state", label: "Status", html: (v) => badge(v) },
			{ key: "priority", label: "Priority" },
			{ key: "raised_by_name", label: "Raised by" },
			{ key: "creation", label: "Raised", format: dshort },
			{
				key: "age_days",
				label: "Open / closed in",
				num: true,
				sortValue: (r) => (r.is_open ? r.age_days : r.close_hours == null ? null : r.close_hours / 24),
				format: (v, r) =>
					r.is_open
						? plural(r.age_days, "day") + " open"
						: r.close_hours == null
						? "—"
						: dur(r.close_hours) + (r.resolved_estimated ? " (est.)" : ""),
			},
			{
				key: "assignees",
				label: "Assigned to",
				sortValue: (r) => (r.assignees || []).join(),
				format: (v) => (v && v.length ? v.join(", ") : "—"),
			},
		],
		onRowClick: (r) => openDetail(r.name),
	});

	/* ---------- cards view ---------- */

	function sortedRows() {
		const rows = (data ? data.rows : []).slice();
		const by = st.get("sort");
		if (by === "oldest") rows.sort((a, b) => (a.creation < b.creation ? -1 : 1));
		else if (by === "priority") rows.sort((a, b) => (PRIORITY_RANK[b.priority] || 0) - (PRIORITY_RANK[a.priority] || 0));
		else if (by === "title") rows.sort((a, b) => a.title.localeCompare(b.title));
		return rows;
	}

	function cardHtml(r) {
		const esc = PH.esc;
		const acts = [
			r.can_edit && `<button type="button" class="ph-btn ph-btn--ghost ph-btn--sm" data-act="edit">Edit</button>`,
			r.can_withdraw && `<button type="button" class="ph-btn ph-btn--ghost ph-btn--sm" data-act="withdraw">Withdraw</button>`,
			r.can_confirm && `<button type="button" class="ph-btn ph-btn--primary ph-btn--sm" data-act="confirm">Confirm complete</button>`,
		].filter(Boolean);
		return `<article class="rq-card" data-name="${esc(r.name)}" tabindex="0" role="button" aria-label="${esc(r.name + ": " + r.title)}">
			<div class="rq-card__top"><h3 class="rq-card__title">${esc(r.title)}</h3>${badge(r.workflow_state)}</div>
			<div class="rq-card__meta">
				<span class="ph-badge ph-badge--outline">${esc(r.request_type || "REQ")}</span>
				${r.priority ? `<span>${esc(r.priority)}</span>` : ""}
				<span class="ph-mono">${esc(r.name)}</span>
				<span>raised ${esc(dshort(r.creation))} by ${esc(r.raised_by_name)}</span>
				${r.has_task ? "<span>being built</span>" : ""}
			</div>
			${r.tags.length ? `<div class="rq-tags">${r.tags.map((t) => `<span class="rq-tag rq-tag--static">${esc(t)}</span>`).join("")}</div>` : ""}
			${r.assignees.length ? `<div class="rq-card__meta">Assigned to ${esc(r.assignees.join(", "))}</div>` : ""}
			${acts.length ? `<div class="rq-card__acts">${acts.join("")}</div>` : ""}
		</article>`;
	}

	function renderCards() {
		const rows = sortedRows();
		const holder = PH.$("#cards");
		const more = PH.$("#more");
		if (!rows.length) {
			more.hidden = true;
			PH.empty(holder, "Nothing here", "No request matches these filters. Widen the dates or clear a filter to see more.");
			return;
		}
		const view = rows.slice(0, shown);
		holder.innerHTML = `<div class="rq-cards">${view.map(cardHtml).join("")}</div>`;
		more.hidden = rows.length <= shown;
		more.textContent = `Show more (${PH.fmt.num(rows.length - shown)} left)`;
	}

	PH.$("#more").addEventListener("click", () => {
		shown += PAGE_SIZE;
		renderCards();
	});
	const cardsEl = PH.$("#cards");
	cardsEl.addEventListener("click", (e) => {
		const card = e.target.closest(".rq-card");
		if (!card) return;
		const act = e.target.closest("[data-act]");
		if (act) return runAction(act.dataset.act, card.dataset.name);
		openDetail(card.dataset.name);
	});
	cardsEl.addEventListener("keydown", (e) => {
		if (e.key === "Enter" && e.target.classList.contains("rq-card")) openDetail(e.target.dataset.name);
	});

	/* ---------- load / render ---------- */

	function load() {
		const my = ++seq;
		PH.loadingKpis("#kpis", true);
		PH.set("#notice", "");
		if (!data) PH.skeleton("#cards", "rows", 4);
		return PH.call(API + "get_requests_overview", args())
			.then((m) => {
				if (my !== seq) return;
				data = m;
				shown = PAGE_SIZE;
				render();
				PH.markUpdated();
			})
			.catch((e) => {
				if (my !== seq) return;
				data = null;
				PH.kpis("#kpis", KPI_LABELS.map((l) => ({ label: l, value: "—" })));
				["#cards", "#c-flow", "#by-status", "#by-type", "#by-priority", "#by-area", "#by-requester", "#dups", "#t-list"].forEach((x) =>
					PH.error(x, e.message, () => load())
				);
				PH.$("#more").hidden = true;
				paintView();
			});
	}

	function paintView() {
		const v = VIEWS.includes(st.get("view")) ? st.get("view") : VIEWS[0];
		PH.$$("#tabs .ph-tab").forEach((b) => b.classList.toggle("is-on", b.dataset.view === v));
		VIEWS.forEach((x) => (PH.$("#view-" + x).hidden = x !== v));
		PH.$("#f-sort").hidden = v !== "requests";
		PH.$("#export").disabled = !data || !data.rows.length;
	}

	st.on((s, changed) => {
		paintPresets();
		paintView();
		if (changed.every((k) => k === "view")) return;
		if (changed.every((k) => k === "sort")) {
			shown = PAGE_SIZE;
			return renderCards();
		}
		load();
	});

	function fillOptions(o) {
		const s = st.get();
		PH.options("#f-status", o.statuses.map((v) => ({ value: v, label: stageLabel(v) })), s.status);
		PH.options("#f-type", o.request_types, s.type);
		PH.options("#f-priority", o.priorities.map((p) => ({ value: p, label: p })).concat([{ value: NONE, label: "Not set" }]), s.priority);
		PH.options("#f-requester", o.requesters, s.requester);
		PH.options("#f-assignee", o.assignees, s.assignee);
		PH.options("#f-project", o.projects.concat([{ value: NONE, label: "No project" }]), s.project);
		PH.options("#f-tag", o.tags, s.tag);
		PH.$("#f-area").hidden = !data.privileged;
		if (data.privileged) PH.options("#f-area", o.product_areas.concat([{ value: NONE, label: "Not set" }]), s.area);
	}

	function render() {
		const d = data;
		const k = d.kpis;
		const s = st.get();
		const n = PH.fmt.num;
		fillOptions(d.options);
		const chosen = [
			s.scope === "open" ? "still open" : s.scope === "closed" ? "finished" : "",
			s.status && stageLabel(s.status),
			s.type,
			s.priority === NONE ? "no priority" : s.priority,
			s.area === NONE ? "no module" : s.area,
			s.project && s.project !== NONE ? s.project : "",
			s.tag && "tag " + s.tag,
			s.mine ? "mine" : "",
			s.q ? "“" + s.q + "”" : "",
		].filter(Boolean);
		PH.text("#sub", plural(k.raised, "request") + " raised · " + (s.from === ALL_TIME_FROM ? "all time" : PH.date.label(s.from, s.to)) + (chosen.length ? " · " + chosen.join(" · ") : ""));

		const fr = durParts(k.median_first_response_hours);
		const tc = durParts(k.median_close_hours);
		PH.kpis("#kpis", [
			{ label: "Raised", value: k.raised, unit: n(k.open) + " open · " + n(k.closed_out) + " closed", dark: true, title: "Requests raised in this period that match the filters" },
			{
				label: "Still open",
				value: k.open,
				unit: k.oldest_open_days != null ? "oldest " + plural(k.oldest_open_days, "day") : "none waiting",
				title:
					"Anything not yet Done, Not going ahead, Withdrawn or Closed. Parked requests count as open." +
					(k.waiting_first_response ? " " + n(k.waiting_first_response) + " have not been looked at yet." : ""),
				onClick: () => st.set({ scope: s.scope === "open" ? "" : "open" }),
				active: s.scope === "open",
			},
			{
				label: "Closed out",
				value: k.closed_out,
				unit: n(k.completed + k.closed) + " done · " + n(k.rejected + k.withdrawn) + " declined",
				title:
					"Done: Completed " + n(k.completed) + ", Closed " + n(k.closed) + ". Declined: Not going ahead " + n(k.rejected) + ", Withdrawn " + n(k.withdrawn) +
					(k.awaiting_signoff ? ". " + n(k.awaiting_signoff) + " finished ones await the raiser's confirmation." : ""),
				onClick: () => st.set({ scope: s.scope === "closed" ? "" : "closed" }),
				active: s.scope === "closed",
			},
			{
				label: "First response",
				value: fr[0],
				suffix: fr[1],
				unit: "median · " + n(k.first_response_known) + " of " + n(k.raised),
				title: "Typical (median) time from raising to the first status change or reply from someone other than the raiser. Only requests with a recorded history count: " + n(k.first_response_known) + " of " + n(k.raised) + ".",
			},
			{
				label: "Time to close",
				value: tc[0],
				suffix: tc[1],
				unit: "median · " + n(k.close_known) + " closed",
				title: "Typical (median) time from raising to the date the request was closed out. " + (k.close_estimated ? n(k.close_estimated) + " of " + n(k.close_known) + " use the last update date because the change was not recorded." : ""),
			},
		]);

		const notes = [];
		if (k.reopened_requests) notes.push(plural(k.reopened_requests, "request") + " in this view went back to review after being deferred (" + plural(k.reopened_times, "time") + " in all).");
		if (k.awaiting_signoff) notes.push(n(k.awaiting_signoff) + " finished " + (k.awaiting_signoff === 1 ? "request has" : "requests have") + " not yet been confirmed by the person who raised " + (k.awaiting_signoff === 1 ? "it." : "them."));
		if (k.close_estimated) notes.push("Withdrawn and confirmed requests leave no change history, so their closing date is the last update date.");
		if (d.notes && d.notes.scheduled_without_task) notes.push(n(d.notes.scheduled_without_task) + " requests that are scheduled or further along have no linked task.");
		if (d.notes && d.notes.tasks_pointing_nowhere) notes.push(n(d.notes.tasks_pointing_nowhere) + " tasks point to requests that no longer exist.");
		if (d.truncated) notes.push("The cards and table show the newest " + n(d.row_limit) + " of " + n(d.total_rows) + " requests; every figure covers all of them.");
		PH.set("#notice", notes.length ? PH.html`<div class="ph-notice">${notes.join(" ")}</div>` : "");

		const sr = d.series;
		PH.text("#m-chart", n(sr.opened_total) + " raised · " + n(sr.closed_total) + " closed in this period (by " + sr.unit + "; closed counts requests of any age)");
		PH.chart("#c-flow", {
			type: "line",
			labels: sr.labels.map((l) => PH.fmt.date(l, true)),
			legend: true,
			yFormat: (v) => (Number.isInteger(v) ? n(v) : ""),
			series: [
				{ label: "Raised", data: sr.opened, color: PH.statusColor.ink, fill: false },
				{ label: "Closed", data: sr.closed, color: PH.statusColor.good, fill: true },
			],
			options: { elements: { line: { cubicInterpolationMode: "monotone" } } },
		});
		tStatus.update(d.by_status);
		tType.update(d.by_type);
		tPrio.update(d.by_priority);
		PH.$("#card-area").hidden = !d.by_product_area;
		if (d.by_product_area) tArea.update(d.by_product_area);
		tReq.update(d.by_requester);
		PH.text("#m-req", d.requesters_total > d.by_requester.length ? "top " + d.by_requester.length + " of " + d.requesters_total : plural(d.requesters_total, "person", "people"));
		tDup.update(d.duplicates.groups);

		PH.text("#tc-requests", n(d.total_rows));
		PH.text("#m-cards", n(k.raised) + " raised · " + n(k.open) + " still open");
		PH.text("#m-list", d.truncated ? "newest " + n(d.row_limit) + " of " + n(d.total_rows) : plural(d.total_rows, "request") + " · click one for its timeline");
		tList.update(d.rows);
		renderCards();
		paintView();
	}

	/* ---------- actions on an existing request ---------- */

	function runAction(act, name) {
		if (act === "edit") return openEdit(name);
		if (act === "withdraw") return withdraw(name);
		return confirmDone(name);
	}

	function write(method, name, done) {
		return PH.call(WRITE + method, { name }, { silent: true })
			.then(() => {
				PH.toast(done, "good");
				load();
			})
			.catch((e) => PH.toast(message(e, "That did not go through."), "bad"));
	}
	function withdraw(name) {
		return PH.confirm("Withdraw this request?", "It will be closed as withdrawn and the dev team will stop working on it.", { ok: "Withdraw", danger: true }).then(
			(yes) => yes && write("withdraw_request", name, "Withdrawn.")
		);
	}
	function confirmDone(name) {
		return write("confirm_request_complete", name, "Confirmed - closed.");
	}

	/* ---------- raise / edit form ---------- */

	function loadFormOptions() {
		if (!formOptions)
			formOptions = PH.call(API + "get_form_options", {}, { silent: true }).catch((e) => {
				formOptions = null;
				throw e;
			});
		return formOptions;
	}

	const field = (label, control, o) => {
		o = o || {};
		return `<div class="ph-field${o.full ? " ph-field--full" : ""}">
			<label${o.id ? ` for="${o.id}"` : ""}>${PH.esc(label)}${o.required ? ' <span class="rq-req" aria-hidden="true">*</span>' : ""}</label>
			${control}${o.hint ? `<div class="ph-field__hint">${PH.esc(o.hint)}</div>` : ""}
			<div class="ph-field__error" data-err="${o.err || ""}" role="alert" hidden></div></div>`;
	};
	const selectHtml = (id, name, items, blank) =>
		`<select class="ph-control" id="${id}" name="${name}"><option value="">${PH.esc(blank)}</option>${items
			.map((v) => `<option value="${PH.esc(v)}">${PH.esc(v)}</option>`)
			.join("")}</select>`;
	const tagsHtml = (tags, selected) =>
		`<div class="rq-tags" id="rq-tags" role="group" aria-label="Tags">${tags
			.map((t) => `<button type="button" class="rq-tag" data-tag="${PH.esc(t)}" aria-pressed="${selected.includes(t)}">${PH.esc(t)}</button>`)
			.join("")}</div>`;

	function setError(form, key, text) {
		const box = form.querySelector(`[data-err="${key}"]`);
		if (!box) return;
		box.textContent = text || "";
		box.hidden = !text;
		const ctl = box.parentNode.querySelector(".ph-control");
		if (ctl) ctl.classList.toggle("is-invalid", !!text);
	}
	function pickedTags(form) {
		return PH.$$('#rq-tags [aria-pressed="true"]', form).map((b) => b.dataset.tag);
	}
	function wireForm(m, form) {
		// An inline message goes away as soon as its field is touched.
		const clear = (e) => {
			const box = e.target.closest(".ph-field") && e.target.closest(".ph-field").querySelector("[data-err]");
			if (box && box.dataset.err) setError(form, box.dataset.err, "");
		};
		form.addEventListener("input", clear);
		form.addEventListener("change", clear);
		form.addEventListener("click", (e) => {
			const b = e.target.closest(".rq-tag");
			if (b) {
				b.setAttribute("aria-pressed", b.getAttribute("aria-pressed") !== "true");
				setError(form, "tags", "");
			}
		});
		// Enter in a single-line field sends the form, unless it just chose from a dropdown.
		form.addEventListener("keydown", (e) => {
			if (e.key === "Enter" && e.target.tagName === "INPUT" && e.target.type !== "file" && !e.defaultPrevented) {
				e.preventDefault();
				m.el.querySelector(".ph-btn--primary").click();
			}
		});
	}
	function checkRequired(form, title, tags, kind) {
		setError(form, "title", title.trim() ? "" : "Tell us what you need.");
		if (kind !== undefined) setError(form, "request_type", kind ? "" : "Choose a kind.");
		setError(form, "tags", tags.length ? "" : "Pick at least one tag.");
		return !!title.trim() && (kind === undefined || !!kind) && tags.length > 0;
	}

	/** Searchable pick-one box over a local list; the typed text is never submitted, only a pick. */
	function picker(input, items) {
		const chosen = { value: "", label: "" };
		PH.autocomplete(input, {
			display: (it) => it.label,
			onSelect: (it) => Object.assign(chosen, { value: it.value, label: it.label }),
			source: async (q) => {
				const t = q.toLowerCase();
				return items
					.filter((x) => !t || x.label.toLowerCase().includes(t) || x.value.toLowerCase().includes(t))
					.slice(0, PICKER_LIMIT)
					.map((x) => ({ value: x.value, label: x.label, description: x.value }));
			},
		});
		input.addEventListener("input", () => {
			if (input.value !== chosen.label) chosen.value = "";
		});
		input.addEventListener("blur", () => {
			input.value = chosen.label;
		});
		return () => chosen.value;
	}

	function upload(file, docname) {
		const fd = new FormData();
		fd.append("file", file, file.name);
		fd.append("doctype", "Request");
		fd.append("docname", docname);
		fd.append("is_private", "1");
		return fetch("/api/method/upload_file", {
			method: "POST",
			headers: { "X-Frappe-CSRF-Token": frappe.csrf_token },
			credentials: "same-origin",
			body: fd,
		}).then((r) => {
			if (!r.ok) throw new Error("upload failed");
		});
	}

	function openRaise() {
		loadFormOptions().then(buildRaise, (e) => PH.toast(message(e, "Could not open the form."), "bad"));
	}

	function buildRaise(o) {
		const form = document.createElement("form");
		form.className = "ph-form ph-form--2";
		form.noValidate = true;
		form.innerHTML =
			field("What do you need?", `<input class="ph-control" id="rq-title" name="title" maxlength="${TITLE_MAX}" placeholder="Add a supervisor column to the warehouse list" autocomplete="off">`, { full: true, required: true, id: "rq-title", err: "title" }) +
			field("Kind", selectHtml("rq-kind", "request_type", o.request_types, "Choose a kind"), { required: true, id: "rq-kind", err: "request_type" }) +
			(o.triage_fields ? field("Module", selectHtml("rq-area", "product_area", o.product_areas, "Not sure"), { id: "rq-area" }) : "") +
			field("Raised for", '<input class="ph-control" id="rq-for" placeholder="Me" aria-label="Raised for">', { id: "rq-for", hint: "Leave empty to raise it for yourself." }) +
			field("Who would you like on it?", '<input class="ph-control" id="rq-assignee" placeholder="No preference">', { id: "rq-assignee", hint: "A suggestion only; the dev team decides." }) +
			(o.triage_fields
				? field("Priority", selectHtml("rq-prio", "priority", o.priorities, "Not set"), { id: "rq-prio" })
				: '<p class="rq-note ph-field--full">A reviewer sets the module and priority when they take this on.</p>') +
			field("Tags", tagsHtml(o.tags, []), { full: true, required: true, err: "tags" }) +
			field("Anything else we should know?", '<textarea class="ph-control" id="rq-desc" name="description" rows="4" placeholder="What you are trying to do, and what happens instead."></textarea>', { full: true, id: "rq-desc" }) +
			field("Attach something (optional)", '<input class="ph-control" id="rq-file" type="file">', { full: true, id: "rq-file" });
		const employee = picker(form.querySelector("#rq-for"), o.employees);
		const assignee = picker(form.querySelector("#rq-assignee"), o.users);
		const val = (id) => (form.querySelector(id) ? form.querySelector(id).value : "");
		const m = PH.modal({
			title: "Raise a request",
			size: "lg",
			body: form,
			actions: [
				{ label: "Cancel" },
				{
					label: "Send it",
					primary: true,
					onClick: async () => {
						const tags = pickedTags(form);
						const title = val("#rq-title");
						if (!checkRequired(form, title, tags, val("#rq-kind"))) return false;
						const created = await PH.call(
							WRITE + "create_request",
							{
								title: title.trim(),
								request_type: val("#rq-kind"),
								product_area: val("#rq-area") || null,
								priority: val("#rq-prio") || null,
								description: val("#rq-desc") || null,
								raised_by_employee: employee() || null,
								requested_assignee: assignee() || null,
								tags,
								source: "Web Portal",
							},
							{ silent: true }
						);
						const file = form.querySelector("#rq-file").files[0];
						let attached = true;
						if (file) await upload(file, created.name).catch(() => (attached = false));
						PH.toast(
							attached ? "Sent. The dev team will pick it up." : "Sent, but the attachment could not be uploaded. Open the request to add it again.",
							attached ? "good" : "warn"
						);
						load();
					},
				},
			],
		});
		wireForm(m, form);
	}

	/** Edit title, tags and description: the fields api.requests.update_request saves. */
	function openEdit(name) {
		Promise.all([PH.call(API + "get_request_detail", { name }, { silent: true }), loadFormOptions()]).then(
			([r, o]) => buildEdit(r, o),
			(e) => PH.toast(message(e, "Could not open this request."), "bad")
		);
	}
	function buildEdit(r, o) {
		const form = document.createElement("form");
		form.className = "ph-form ph-form--1";
		form.noValidate = true;
		form.innerHTML =
			field("What do you need?", `<input class="ph-control" id="rq-title" maxlength="${TITLE_MAX}" value="${PH.esc(r.title)}" autocomplete="off">`, { required: true, id: "rq-title", err: "title" }) +
			field("Tags", tagsHtml(o.tags, r.tags), { required: true, err: "tags" }) +
			field("Anything else we should know?", `<textarea class="ph-control" id="rq-desc" rows="4">${PH.esc(r.description_raw || "")}</textarea>`, { id: "rq-desc" });
		const m = PH.modal({
			title: "Edit " + r.name,
			body: form,
			actions: [
				{ label: "Cancel" },
				{
					label: "Save",
					primary: true,
					onClick: async () => {
						const title = form.querySelector("#rq-title").value;
						const tags = pickedTags(form);
						if (!checkRequired(form, title, tags)) return false;
						await PH.call(
							WRITE + "update_request",
							{ name: r.name, title: title.trim(), description: form.querySelector("#rq-desc").value || null, tags },
							{ silent: true }
						);
						PH.toast("Saved.", "good");
						load();
					},
				},
			],
		});
		wireForm(m, form);
	}

	/* ---------- detail ---------- */

	document.addEventListener("click", (e) => {
		const a = e.target.closest("[data-open]");
		if (a) {
			e.preventDefault();
			openDetail(a.dataset.open);
		}
	});

	function openDetail(name) {
		const holder = document.createElement("div");
		PH.skeleton(holder, "rows", 6);
		const m = PH.modal({
			title: name,
			size: "lg",
			body: holder,
			actions: [
				{
					label: "Open in Desk",
					onClick: () => {
						PH.openDoc("Request", name);
						return false;
					},
				},
			],
		});
		PH.call(API + "get_request_detail", { name }, { silent: true })
			.then((r) => {
				PH.set(holder, detailHtml(r));
				[
					["can_edit", "Edit", "ph-btn--ghost", () => openEdit(name)],
					["can_withdraw", "Withdraw", "ph-btn--ghost", () => withdraw(name)],
					["can_confirm", "Confirm complete", "ph-btn--primary", () => confirmDone(name)],
				].forEach(([flag, label, cls, fn]) => {
					if (!r[flag]) return;
					const b = document.createElement("button");
					b.className = "ph-btn " + cls;
					b.textContent = label;
					b.onclick = () => {
						m.close();
						fn();
					};
					m.el.querySelector(".ph-modal__foot").appendChild(b);
				});
			})
			.catch((e) => PH.error(holder, e.message, () => {
				m.close();
				openDetail(name);
			}));
	}

	function detailHtml(r) {
		const esc = PH.esc;
		const stats = [
			["Status", badge(r.workflow_state)],
			["Kind", esc(r.request_type || "—")],
			["Priority", esc(r.priority || "Not set")],
			["First response", r.first_response_hours == null ? "not recorded" : dur(r.first_response_hours)],
			[r.is_open ? "Open for" : "Time to close", r.is_open ? plural(r.age_days || 0, "day") : dur(r.close_hours) + (r.resolved_estimated ? " (from last update)" : "")],
		];
		let h = `<div class="ph-stats">${stats.map(([l, v]) => `<div class="ph-stat"><small>${esc(l)}</small><b style="font-size:15px">${v}</b></div>`).join("")}</div>`;
		if (r.reopened) h += `<div class="ph-notice ph-mt">Sent back to review ${plural(r.reopened, "time")}.</div>`;
		h += `<div class="rq-sec">What was asked</div><p class="ph-strong ph-mb-0">${esc(r.title)}</p><p class="rq-desc ph-mt">${esc(r.description || "No description.")}</p>`;
		const kv = [
			["Raised by", r.raised_by],
			r.raised_for && ["Raised for", r.raised_for],
			["Raised", when(r.raised_at)],
			r.source && ["Raised from", r.source],
			r.product_area && ["Module", r.product_area],
			r.project && ["Project", r.project_name || r.project],
			r.tags && r.tags.length && ["Tags", r.tags.join(", ")],
			r.requested_assignee && ["Suggested assignee", r.requested_assignee],
			["Assigned to", r.assignees.length ? r.assignees.join(", ") : "—"],
			r.resolved_at && ["Closed out", when(r.resolved_at) + (r.resolved_estimated ? " (last update)" : "")],
		].filter(Boolean);
		h += `<dl class="ph-kv ph-mt">${kv.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>`;

		h += `<div class="rq-sec">Decision</div>`;
		if (r.decision) {
			h += `<p class="ph-mb-0">${badge(r.decision.to)} <span class="ph-muted">${esc(when(r.decision.at))}${r.decision.by ? " · " + esc(r.decision.by) : ""}</span></p>`;
			if (r.decision_reason) h += `<p class="rq-desc ph-mt">${esc(r.decision_reason)}</p>`;
		} else h += `<p class="ph-muted">${r.is_open && r.workflow_state === "Under Review" ? "Waiting for a decision." : "No decision recorded."}</p>`;
		if (r.resolution_notes) h += `<p class="rq-desc ph-mt"><b>Resolution notes:</b> ${esc(r.resolution_notes)}</p>`;

		h += `<div class="rq-sec">Timeline</div><ul class="rq-tl">${r.events
			.map(
				(ev) =>
					`<li class="is-${esc(ev.kind)}"><i></i><div><div class="rq-tl__when">${esc(when(ev.at))}${ev.by ? " · " + esc(ev.by) : ""}${ev.after_hours != null ? " · after " + esc(dur(ev.after_hours)) : ""}</div><div class="rq-tl__text">${
						ev.kind === "comment" ? esc(ev.text) : "<b>" + esc(ev.kind === "state" ? "Moved to " + stageLabel(ev.to) : ev.text) + "</b>"
					}</div></div></li>`
			)
			.join("")}</ul>`;
		if (!r.full_detail) h += `<p class="ph-muted">Names and comments are shown to the person who raised this and to the dev team.</p>`;
		else if (!r.events.some((x) => x.kind === "comment")) h += `<p class="ph-muted">No comments.</p>`;
		if (r.events.length === 1 && r.workflow_state !== "Under Review") h += `<p class="ph-muted">The earlier status changes were not recorded in the change history.</p>`;

		h += `<div class="rq-sec">Linked work</div>`;
		if (r.task)
			h += `<p class="ph-mb-0"><a href="/app/task/${encodeURIComponent(r.task.name)}" target="_blank" rel="noopener">${esc(r.task.name)}</a> · ${esc(r.task.subject || "")}</p><p class="ph-muted">${esc(r.task.status || "")}${r.task.due ? " · due " + esc(dshort(r.task.due)) : ""}${r.task.project ? " · " + esc(r.task.project) : ""}</p>`;
		else if (r.linked_task_missing) h += `<p class="ph-muted">The linked task no longer exists.</p>`;
		else h += `<p class="ph-muted">${r.has_task ? "A task is being built for this request." : "No task yet."}</p>`;

		if (r.duplicates.length)
			h += `<div class="rq-sec">Same title</div><ul class="rq-dups ph-mb-0" style="padding-left:18px">${r.duplicates
				.map((x) => `<li><a href="#" data-open="${esc(x.name)}">${esc(x.name)}</a> ${badge(x.status)} <span class="ph-muted">${esc(dshort(x.raised))}</span></li>`)
				.join("")}</ul>`;
		return h;
	}

	/* ---------- CSV ---------- */

	PH.$("#export").addEventListener("click", () => {
		if (!data || !data.rows.length) return;
		const s = st.get();
		PH.csv(
			"requests_" + s.from + "_" + s.to + ".csv",
			data.rows,
			[
				{ key: "name", label: "Request" },
				{ key: "title", label: "Title" },
				{ key: "request_type", label: "Kind" },
				{ key: "workflow_state", label: "Status", csv: stageLabel },
				{ key: "priority", label: "Priority" },
				{ key: "raised_by_name", label: "Raised by" },
				{ key: "creation", label: "Raised" },
				{ key: "age_days", label: "Days open (open requests)" },
				{ key: "resolved_at", label: "Closed out" },
				{ key: "close_hours", label: "Hours to close" },
				{ key: "first_response_hours", label: "Hours to first response" },
				{ key: "reopened", label: "Times reopened" },
				{ key: "duplicates", label: "Other requests with same title" },
				{ key: "assignees", label: "Assigned to", csv: (v) => (v || []).join("; ") },
				{ key: "tags", label: "Tags", csv: (v) => (v || []).join("; ") },
			].concat(data.privileged ? [{ key: "product_area", label: "Module" }, { key: "project", label: "Project" }] : [])
		);
	});
	PH.$("#raise").addEventListener("click", openRaise);

	DevKeys.init({ title: "Requests", list: { root: "#ph-main", items: () => PH.$$("#ph-main .rq-card, #ph-main tbody tr.is-link") } });

	PH.onRefresh(() => load());
	PH.ready(() => {
		paintPresets();
		paintView();
		loadFormOptions().catch(() => null);
		load().then(() => {
			const q = new URLSearchParams(location.search);
			const r = q.get("req");
			if (!r) return;
			q.delete("req"); // a deep link opens once; it should not reopen on every later reload
			history.replaceState(history.state, "", location.pathname + (q.toString() ? "?" + q : "") + location.hash);
			openDetail(r);
		});
	});
})();
