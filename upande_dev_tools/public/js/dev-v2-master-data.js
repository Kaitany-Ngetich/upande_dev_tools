/* Master Data v2: the four master lists with usage, and the add / rename / reorder / disable /
 * delete actions. Every write calls the existing api/master_data.py endpoint, so its validation
 * and in-use rules are the ones that apply; reads come from api/v2/master_data.py. */
(function () {
	"use strict";
	const READ = "upande_dev_tools.api.v2.master_data.";
	const WRITE = "upande_dev_tools.api.master_data.";
	const NONE = "__none__";
	const KINDS = ["request_type", "priority_level", "product_area", "tag"];
	const SINGULAR = { request_type: "request type", priority_level: "priority level", product_area: "product area", tag: "tag" };
	const DOC = { Request: "request", Task: "task", Issue: "issue" };
	const st = PH.state({ kind: "request_type", source: "", show: "", q: "", from: "", to: "" });
	const n = PH.fmt.num;
	let data = null;
	let seq = 0;

	const kind = () => (KINDS.includes(st.get("kind")) ? st.get("kind") : "request_type");
	const isPriority = () => kind() === "priority_level";
	const sourceLabel = (key) => (data.sources.find((x) => x.key === key) || {}).label || key;

	/* ── filters and tabs ─────────────────────────────────────────── */
	PH.bindSelect("#f-source", st, "source");
	PH.bindSelect("#f-show", st, "show");
	PH.bindSearch("#f-q", st, "q");
	PH.dateRange({ pills: "#f-preset", from: "#f-from", to: "#f-to", state: st });
	PH.$("#f-preset").addEventListener("click", (e) => {
		if (e.target.closest("button[data-value='all']")) st.set({ from: "", to: "" });
	});
	const paintAllTime = () => {
		const s = st.get();
		PH.$("#f-preset [data-value='all']").classList.toggle("is-on", !s.from && !s.to);
	};
	const paintTabs = () => PH.$$("#tabs .ph-tab").forEach((b) => b.classList.toggle("is-on", b.dataset.kind === kind()));
	PH.$("#tabs").addEventListener("click", (e) => {
		const b = e.target.closest("[data-kind]");
		if (b && b.dataset.kind !== kind()) st.set({ kind: b.dataset.kind, source: "", show: "", q: "" });
	});
	PH.$("#f-q").value = st.get("q");
	st.on((s, changed) => {
		paintAllTime();
		paintTabs();
		if (changed.includes("kind")) {
			PH.$("#f-q").value = "";
			PH.$("#f-show").value = "";
			resetAddForm();
		}
		load();
	});

	/* ── writes (existing endpoints) ──────────────────────────────── */
	/** Call one of the existing write endpoints. Uses frappe.call with `silent` because PH.call does
	 * not pass it on, and a refused write would then also open Frappe's own message dialog over
	 * the inline refusal. Rejects with the server's message. */
	const write = (method, args) =>
		new Promise((resolve, reject) => {
			let settled = false;
			const fail = (r) => {
				if (settled) return;
				settled = true;
				reject(new Error(PH.serverError(r) || "Could not reach the server"));
			};
			const req = frappe.call({
				method: WRITE + method, args, type: "POST", silent: true,
				callback: (r) => { if (!settled) { settled = true; resolve(r.message); } },
				error: fail,
			});
			if (req && typeof req.fail === "function") req.fail((xhr) => fail((xhr && xhr.responseJSON) || xhr));
		});
	const refresh = () => Promise.all([load(), loadCounts()]);

	/** Enter in any field of the modal's form presses its primary button (a form with two
	 * fields and no submit button would otherwise not submit). */
	function submitOnEnter(modal) {
		modal.el.querySelector("form").addEventListener("keydown", (e) => {
			if (e.key !== "Enter") return;
			e.preventDefault();
			modal.el.querySelector(".ph-btn--primary").click();
		});
	}

	/** Show an endpoint / validation message inside a modal and return focus to a control in
	 * it (the busy state blurs the pressed button, and Esc then needs focus inside the dialog). */
	function setError(root, msg) {
		root.querySelector("[data-err]").textContent = msg || "";
		if (!msg) return;
		const modal = root.closest(".ph-modal");
		const target = root.querySelector("input") || (modal && modal.querySelector(".ph-modal__foot button"));
		if (target) setTimeout(() => target.focus(), 0);
	}

	const norm = (s) => String(s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
	/** Master values (other than `except`) that read the same apart from capitals / punctuation. */
	function lookAlikes(value, except) {
		const v = norm(value);
		if (!v) return [];
		return data.rows.filter((r) => r.in_master && r.name !== except && norm(r.name) === v).map((r) => r.name);
	}

	function usageHtml(u) {
		if (!u.total) return '<p class="ph-muted">Nothing uses this value yet.</p>';
		const rows = u.sources.filter((s) => u.counts[s.key]).map((s) => '<div class="md-usage__row"><span>' + PH.esc(s.label) + "</span><b>" + n(u.counts[s.key]) + "</b></div>");
		return '<div class="md-usage">' + rows.join("") + "</div>";
	}

	function usageBlock(value) {
		const box = document.createElement("div");
		PH.skeleton(box, "table", 2);
		PH.call(READ + "get_value_usage", { kind: kind(), value }, { silent: true })
			.then((u) => { box.innerHTML = '<div class="ph-label">Used by (all time)</div>' + usageHtml(u); box._usage = u; })
			.catch(() => { box.innerHTML = '<p class="ph-muted">Usage could not be loaded.</p>'; });
		return box;
	}

	function valueForm(row) {
		const form = document.createElement("form");
		form.className = "ph-form ph-form--1";
		form.noValidate = true;
		form.innerHTML =
			'<div class="ph-field"><label for="md-value">' + PH.esc(SINGULAR[kind()]) + ' name</label>' +
			'<input class="ph-input" id="md-value" type="text" autocomplete="off" value="' + PH.esc(row.name) + '"></div>' +
			(isPriority() ? '<div class="ph-field"><label for="md-sort">Order</label><input class="ph-input" id="md-sort" type="number" value="' + PH.esc(row.sort_order || 0) + '"><span class="ph-field__hint">Lower numbers come first in pick lists.</span></div>' : "") +
			'<div class="ph-field__hint" data-hint></div><div class="ph-field__error" data-err role="alert"></div>';
		return form;
	}

	function editRow(row) {
		const body = document.createElement("div");
		const form = valueForm(row);
		body.appendChild(form);
		const usage = usageBlock(row.name);
		body.appendChild(usage);
		const input = form.querySelector("#md-value");
		const hint = form.querySelector("[data-hint]");
		input.addEventListener("input", () => {
			const alike = lookAlikes(input.value, row.name);
			hint.textContent = alike.length ? "Reads the same as: " + alike.join(", ") : "";
			setError(form, "");
		});
		const m = PH.modal({
			title: "Edit " + SINGULAR[kind()], sub: row.name, body,
			actions: [
				{ label: "Cancel" },
				{
					label: "Save", primary: true,
					onClick: async () => {
						const value = input.value.trim();
						if (!value) { setError(form, "A value is required."); input.focus(); return false; }
						const sortEl = form.querySelector("#md-sort");
						try {
							await write("update_master_data", { key: kind(), name: row.name, value, sort_order: sortEl ? parseInt(sortEl.value, 10) || 0 : 0 });
						} catch (e) { setError(form, e.message); return false; }
						PH.toast(value === row.name ? "Saved" : "Renamed to " + value + (usage._usage && usage._usage.total ? "; existing items now use the new name" : ""), "ok");
						refresh();
					},
				},
			],
		});
		submitOnEnter(m);
	}

	function deleteRow(row) {
		const body = document.createElement("div");
		body.innerHTML = '<form><p class="ph-muted">Delete “' + PH.esc(row.name) + '” for good? This cannot be undone.</p><div data-usage></div><div class="ph-field__error" data-err role="alert"></div></form>';
		const usage = usageBlock(row.name);
		body.querySelector("[data-usage]").appendChild(usage);
		const actions = [{ label: "Cancel" }];
		if (!row.disabled) {
			actions.push({
				label: "Disable instead",
				onClick: async () => {
					try { await write("set_master_data_disabled", { key: kind(), name: row.name, disabled: 1 }); } catch (e) { setError(body, e.message); return false; }
					PH.toast(row.name + " disabled", "ok");
					refresh();
				},
			});
		}
		actions.push({
			label: "Delete", danger: true,
			onClick: async () => {
				try { await write("delete_master_data", { key: kind(), name: row.name }); } catch (e) { setError(body, e.message); return false; }
				PH.toast("Deleted " + row.name, "ok");
				refresh();
			},
		});
		const m = PH.modal({ title: "Delete " + SINGULAR[kind()], body, actions });
		m.el.querySelector("form").addEventListener("submit", (e) => e.preventDefault());
	}

	function toggleDisabled(row, input) {
		input.disabled = true;
		write("set_master_data_disabled", { key: kind(), name: row.name, disabled: input.checked ? 0 : 1 })
			.then(() => { PH.toast(row.name + (input.checked ? " enabled" : " disabled"), "ok"); refresh(); })
			.catch((e) => { input.checked = !input.checked; input.disabled = false; PH.toast(e.message, "bad"); });
	}

	/** Priority levels in list order, listed values only. */
	const ordered = () => data.rows.filter((r) => r.in_master).sort((a, b) => (a.sort_order - b.sort_order) || a.name.localeCompare(b.name));

	/** Swap a level with its neighbour; equal sort orders are split so the move is visible. */
	function moveRow(row, dir) {
		const list = ordered(), i = list.findIndex((r) => r.name === row.name), other = list[i + dir];
		if (!other) return;
		const mine = row.sort_order || 0, theirs = other.sort_order || 0;
		const save = (r, order) => write("update_master_data", { key: kind(), name: r.name, value: r.name, sort_order: order });
		const jobs = mine === theirs ? [save(row, theirs + dir)] : [save(row, theirs), save(other, mine)];
		Promise.all(jobs).then(refresh).catch((e) => PH.toast(e.message, "bad"));
	}

	function addOrphan(row) {
		write("add_master_data", { key: kind(), value: row.name, sort_order: 0 })
			.then(() => { PH.toast("Added " + row.name + " to the list", "ok"); refresh(); })
			.catch((e) => PH.toast(e.message, "bad"));
	}

	/* add form */
	const addForm = PH.$("#add-form");
	function resetAddForm() {
		PH.$("#add-value").value = "";
		PH.$("#add-sort").value = "";
		PH.$("#add-error").textContent = "";
	}
	addForm.addEventListener("submit", (e) => {
		e.preventDefault();
		const value = PH.$("#add-value").value.trim(), err = PH.$("#add-error");
		err.textContent = "";
		if (!value) { err.textContent = "A value is required."; return; }
		const alike = lookAlikes(value);
		if (alike.length) { err.textContent = "Reads the same as " + alike.join(", ") + " already in the list."; return; }
		const sort = PH.$("#add-sort").value;
		PH.$("#add-btn").disabled = true;
		write("add_master_data", { key: kind(), value, sort_order: sort ? parseInt(sort, 10) : 0 })
			.then(() => { PH.toast("Added " + value, "ok"); resetAddForm(); refresh(); })
			.catch((e) => { err.textContent = e.message; })
			.finally(() => { PH.$("#add-btn").disabled = false; });
	});

	/* ── table ────────────────────────────────────────────────────── */
	function badges(r) {
		const b = [];
		if (!r.in_master) b.push('<span class="ph-badge ph-badge--warn" title="Found on requests or tasks but not in the master list">Not in the list</span>');
		if (r.disabled) b.push('<span class="ph-badge ph-badge--outline" title="Hidden from pick lists">Disabled</span>');
		if (r.disabled && r.total > 0) b.push('<span class="ph-badge ph-badge--warn" title="Disabled but still on existing items">Still in use</span>');
		if (r.in_master && r.total === 0 && !r.disabled) b.push('<span class="ph-badge ph-badge--outline">Not used</span>');
		if (r.similar_to.length) b.push('<span class="ph-badge ph-badge--warn" title="Same wording apart from capitals, spacing or an abbreviation">May match: ' + PH.esc(r.similar_to.join(", ")) + "</span>");
		return '<div class="md-badges">' + b.join("") + "</div>";
	}

	/** Up / down arrows for one priority level; disabled at the ends of the list. */
	function arrowsHtml(r) {
		const list = ordered(), i = list.findIndex((x) => x.name === r.name), a = PH.esc(r.name);
		const btn = (act, label, off) => '<button class="ph-iconbtn ph-iconbtn--sm" type="button" data-act="' + act + '" data-name="' + a + '" aria-label="' + label + '"' + (off ? " disabled" : "") + ">" + PH.icon("chevronDown") + "</button>";
		return '<span class="md-order">' + btn("up", "Move up", i <= 0) + btn("down", "Move down", i === list.length - 1) + "</span>";
	}

	function actionsHtml(r) {
		const a = PH.esc(r.name);
		if (!r.in_master) return '<div class="md-acts"><button class="ph-btn ph-btn--sm" type="button" data-act="adopt" data-name="' + a + '">Add to list</button></div>';
		return '<div class="md-acts">' +
			'<label class="ph-switch" title="Enabled values can be picked for new items"><input type="checkbox" data-act="toggle" data-name="' + a + '"' + (r.disabled ? "" : " checked") + ' aria-label="Enabled"><i></i></label>' +
			'<button class="ph-btn ph-btn--sm" type="button" data-act="edit" data-name="' + a + '">Edit</button>' +
			'<button class="ph-btn ph-btn--sm ph-btn--ghost" type="button" data-act="delete" data-name="' + a + '">Delete</button></div>';
	}

	function columns() {
		const d = data, tag = d.kind === "tag", s = st.get();
		const canMove = isPriority() && d.can_edit && !s.show && !s.q;
		const cols = [{ key: "name", label: tag ? "Tag" : d.label.replace(/s$/, ""), cls: "is-strong", format: (v) => v }];
		if (isPriority()) cols.push({ key: "sort_order", label: "Order", num: true, html: (v, r) => '<span class="md-orderval">' + (v == null ? "—" : PH.esc(v)) + "</span>" + (canMove && r.in_master ? arrowsHtml(r) : "") });
		d.sources.filter((x) => d.active_sources.includes(x.key)).forEach((x) => cols.push({ key: "c_" + x.key, label: x.label, num: true, total: true, html: (v) => (v ? n(v) : '<span class="md-zero">0</span>') }));
		cols.push({ key: "total", label: tag ? "Tag uses" : d.active_sources.length > 1 ? "All items" : "Items", num: true, cls: "is-strong", total: true, format: (v) => n(v) });
		cols.push({ key: "last_used", label: "Latest item", format: (v) => (v ? PH.fmt.date(v) : "—"), sortValue: (r) => r.last_used || "" });
		cols.push({ key: "notes", label: "Notes", sortable: false, html: (v, r) => badges(r) });
		if (d.can_edit) cols.push({ key: "actions", label: "", sortable: false, html: (v, r) => actionsHtml(r) });
		return cols;
	}

	function render() {
		const d = data, s = st.get(), k = d.kpis, tag = d.kind === "tag";
		PH.options("#f-source", [{ value: "", label: "Used on: everything" }].concat(d.sources.map((x) => ({ value: x.key, label: "Used on: " + x.label }))), s.source);
		PH.$("#f-source").hidden = d.sources.length < 2;
		PH.$("#f-show").value = s.show || "";
		addForm.hidden = !d.can_edit;
		PH.$("#add-sort").hidden = !isPriority();
		PH.$("#add-value").placeholder = "New " + SINGULAR[d.kind];

		const scope = [s.source ? sourceLabel(s.source) : "", s.show ? PH.$("#f-show").selectedOptions[0].text : "", s.q ? "“" + s.q + "”" : ""].filter(Boolean);
		const when = s.from || s.to ? PH.date.label(s.from, s.to) : "all time";
		PH.text("#sub", PH.fmt.plural(k.values, SINGULAR[d.kind]) + " · " + n(k.items_total) + " items checked · " + when + (scope.length ? " · " + scope.join(" · ") : ""));

		const none = k.no_value_total;
		PH.kpis("#kpis", [
			{ label: d.label, value: k.values, unit: k.disabled ? n(k.disabled) + " disabled" : "in the list", dark: true, title: "Values in the master list" },
			{ label: "In use", value: k.in_use, unit: tag ? "on at least one item" : "used at least once", bar: k.values ? Math.round((100 * k.in_use) / k.values) : 0, active: s.show === "used", onClick: () => st.set({ show: s.show === "used" ? "" : "used" }) },
			{ label: "Not used", value: k.unused, unit: "no items in this view", active: s.show === "unused", onClick: () => st.set({ show: s.show === "unused" ? "" : "unused" }) },
			{ label: "Similar names", value: k.similar_groups, unit: k.similar_groups ? "groups to look at" : "none found", active: s.show === "similar", onClick: k.similar_groups ? () => st.set({ show: s.show === "similar" ? "" : "similar" }) : null },
			{ label: tag ? "No tag set" : "No value set", value: none, unit: "of " + n(k.items_total), onClick: none ? () => drill({ name: NONE }) : null, title: "Requests or tasks where this field is empty" },
		]);

		const notes = [];
		if (k.orphans) notes.push('<div class="ph-notice ph-notice--warn"><div>' + PH.fmt.plural(k.orphans, "value is", "values are") + " on requests or tasks but not in the master list" + (tag ? " (for example a tag whose Work Tag was removed)" : "") + ". Use “Not in the list” to see them" + (d.can_edit ? ", then “Add to list” to bring one back" : "") + ".</div></div>");
		if (k.disabled_in_use) notes.push('<div class="ph-notice ph-notice--signal"><div>' + PH.fmt.plural(k.disabled_in_use, "disabled value is", "disabled values are") + " still on existing items. That is fine; they just can’t be picked for new ones.</div></div>");
		if (d.similar_groups.length) notes.push('<div class="ph-notice ph-notice--signal"><div>Names that may mean the same thing: ' + d.similar_groups.map((g) => PH.esc(g.join(" / "))).join(" · ") + ". Worth a look if you would rather have one.</div></div>");
		if (isPriority()) notes.push('<div class="ph-notice"><div>Requests link to a priority level. Tasks (a fixed Low / Medium / High / Urgent list) and issues are matched by wording only. New tasks start at Low, so Low is high on tasks. Renaming a level updates the requests that use it, not tasks or issues.</div></div>');
		if (tag) notes.push('<div class="ph-notice"><div>An item with several tags counts once under each tag, so the total can be larger than the number of tagged items. “No tag” items are not in any row. Deleting a tag does not remove it from items that already carry it.</div></div>');
		PH.set("#notes", notes.join(""));

		const rows = d.rows.map((r) => {
			const o = { ...r };
			d.active_sources.forEach((key) => { o["c_" + key] = r.counts[key] || 0; });
			return o;
		});
		PH.table("#t-main", {
			columns: columns(), rows, compact: true, pageSize: 50,
			sort: isPriority() ? { key: "sort_order", dir: "asc" } : { key: "total", dir: "desc" },
			empty: "No values match these filters", onRowClick: (r) => drill(r),
		});
		PH.text("#t-title", d.label);
		PH.text("#t-meta", PH.fmt.plural(rows.length, "value") + " listed · click a value to see the requests and tasks that use it");
		PH.$("#export").disabled = !rows.length;
		paintTabs();
	}

	PH.$("#t-main").addEventListener("click", (e) => {
		const b = e.target.closest("[data-act]");
		if (!b || b.dataset.act === "toggle" || !data) return;
		const row = data.rows.find((r) => r.name === b.dataset.name);
		if (!row) return;
		({ edit: editRow, delete: deleteRow, adopt: addOrphan, up: (r) => moveRow(r, -1), down: (r) => moveRow(r, 1) })[b.dataset.act](row);
	});
	PH.$("#t-main").addEventListener("change", (e) => {
		const b = e.target.closest("[data-act='toggle']");
		const row = b && data.rows.find((r) => r.name === b.dataset.name);
		if (row) toggleDisabled(row, b);
	});

	/* ── drill-down ───────────────────────────────────────────────── */
	function drill(row) {
		const s = st.get(), k = kind(), none = row.name === NONE;
		const body = document.createElement("div");
		PH.skeleton(body, "table");
		const m = PH.modal({
			title: none ? "No " + SINGULAR[k] + " set" : row.name,
			sub: SINGULAR[k] + " · " + PH.date.label(s.from, s.to) + (s.source ? " · " + sourceLabel(s.source) : ""),
			body, size: "xl",
		});
		PH.call(READ + "get_value_items", { kind: k, value: row.name, source: s.source, from_date: s.from, to_date: s.to }).then((d) => {
			const parts = Object.keys(d.per_source).map((key) => n(d.per_source[key]) + " " + sourceLabel(key).toLowerCase()).join(" · ");
			body.innerHTML = '<div class="ph-flex ph-flex--between ph-flex--wrap ph-mb"><div class="ph-strong">' + PH.esc(PH.fmt.plural(d.total, "item")) + (parts ? ' <span class="ph-muted">(' + PH.esc(parts) + ")</span>" : "") +
				'</div><button class="ph-btn ph-btn--sm" type="button" data-dl>Export CSV</button></div>' +
				(d.truncated ? '<div class="ph-notice ph-notice--signal ph-mb">Showing the newest ' + n(d.row_limit) + " of each kind. The counts above cover all of them.</div>" : "") +
				'<div id="md-items"></div>';
			PH.table(body.querySelector("#md-items"), {
				rows: d.items, compact: true, pageSize: 25, empty: "Nothing uses this value in the current filters", sort: { key: "created", dir: "desc" },
				columns: [
					{ key: "source_label", label: "Kind", sortable: true },
					{ key: "name", label: "Document", cls: "ph-mono", html: (v, r) => '<a class="ph-link" target="_blank" rel="noopener" href="/app/' + DOC[r.doctype] + "/" + encodeURIComponent(v) + '">' + PH.esc(v) + "</a>" },
					{ key: "title", label: "Title", cls: "is-wrap", format: (v) => v || "—" },
					{ key: "status", label: "Status", format: (v) => v || "—" },
					{ key: "priority", label: "Priority", format: (v) => v || "—" },
					{ key: "created", label: "Created", format: (v) => PH.fmt.date(v) },
				],
			});
			body.querySelector("[data-dl]").addEventListener("click", () => {
				PH.csv("master_data_" + k + "_" + (none ? "no_value" : row.name.replace(/\W+/g, "_")) + ".csv", d.items,
					[["source_label", "Kind"], ["name", "Document"], ["title", "Title"], ["status", "Status"], ["priority", "Priority"], ["created", "Created"], ["owner", "Created by"]].map(([key, label]) => ({ key, label })));
			});
		}).catch((e) => PH.error(body, e.message, () => { m.close(); drill(row); }));
	}

	/* ── load ─────────────────────────────────────────────────────── */
	function load() {
		const s = st.get(), my = ++seq;
		PH.loadingKpis("#kpis", true);
		return PH.call(READ + "get_master_usage", { kind: kind(), source: s.source, show: s.show, q: s.q, from_date: s.from, to_date: s.to })
			.then((m) => { if (my === seq) { data = m; render(); PH.markUpdated(); } })
			.catch((e) => {
				if (my !== seq) return;
				PH.loadingKpis("#kpis", false);
				PH.error("#t-main", e.message, load);
				PH.set("#notes", "");
				PH.$("#export").disabled = true;
			});
	}

	function loadCounts() {
		return PH.call(READ + "get_master_summary", {}, { silent: true })
			.then((m) => KINDS.forEach((k) => PH.text("#tc-" + k, n(m.counts[k]))))
			.catch(() => {});
	}

	PH.$("#export").addEventListener("click", () => {
		if (!data || !data.rows.length) return;
		const d = data, active = d.sources.filter((x) => d.active_sources.includes(x.key));
		const rows = d.rows.map((r) => {
			const o = { name: r.name, in_master: r.in_master ? "yes" : "no", disabled: r.disabled ? "yes" : "no", total: r.total, last_used: r.last_used || "", similar_to: r.similar_to.join("; ") };
			d.active_sources.forEach((key) => { o["c_" + key] = r.counts[key] || 0; });
			return o;
		});
		const cols = [{ key: "name", label: "Value" }, { key: "in_master", label: "In master list" }, { key: "disabled", label: "Disabled" }]
			.concat(active.map((x) => ({ key: "c_" + x.key, label: x.label })))
			.concat([{ key: "total", label: "Total" }, { key: "last_used", label: "Latest item" }, { key: "similar_to", label: "Similar to" }]);
		PH.csv("master_data_" + d.kind + ".csv", rows, cols);
	});

	PH.kpiSkeleton("#kpis", ["Values", "In use", "Not used", "Similar names", "No value set"]);
	PH.skeleton("#t-main", "table");
	DevKeys.init({ title: "Master Data", list: { root: "#ph-main", items: () => PH.$$("#ph-main tbody tr.is-link") } });
	PH.onRefresh(load);
	PH.ready(() => { paintTabs(); paintAllTime(); load(); loadCounts(); });
})();
