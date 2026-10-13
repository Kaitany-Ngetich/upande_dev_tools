/* Version Check v2 (www/version-check-v2.html).
 *
 * Reads come from api/v2/version_check.py (read-only). Every write calls the SAME whitelisted
 * endpoint the Dev Dashboard or the Desk form of "Module Version Check" already calls (EP below),
 * so validation, permission checks and side effects are unchanged. The controls only appear
 * when the server says the user may use them (`data.can`, from frappe.has_permission).
 */
(function () {
	"use strict";

	const READ = "upande_dev_tools.api.v2.version_check.";
	const MODULE =
		"upande_dev_tools.upande_dev_tools.doctype.module_version_check.module_version_check.";
	const DOCTYPE = "Module Version Check";
	const EP = {
		scanBench: "upande_dev_tools.api.version_control.scan_bench",
		scanInstalled: MODULE + "scan_installed_apps",
		check: MODULE + "run_freshness_check",
		checkWithFetch: MODULE + "run_freshness_check_with_fetch",
		insert: "frappe.client.insert",
		setValue: "frappe.client.set_value",
		rename: "frappe.client.rename_doc",
		remove: "frappe.client.delete",
	};
	const VIEWS = ["apps", "overview", "checks"];
	// Needs-attention order for the default sort: local changes and divergence first.
	const STATE_RANK = {
		diverged: 0,
		dirty: 1,
		behind: 2,
		ahead: 3,
		no_remote: 4,
		never_checked: 5,
		in_sync: 6,
	};
	const VER = {
		same: ["Match", "good"],
		code_newer: ["Code is newer", "warn"],
		code_older: ["Code is older", "warn"],
		unknown: ["Can't compare", "outline"],
	};
	const VER_EXPLAIN = {
		same: "The version recorded when the site was last updated is the same as the version in the code.",
		code_newer:
			"The code is a newer version than the one recorded. The site probably has not been updated (migrated) since the code changed.",
		code_older:
			"The code is an older version than the one recorded. A different branch or an older checkout may be in use.",
		unknown:
			"One of the two versions is missing or is a placeholder, so they cannot be compared reliably.",
	};
	const STATE_BADGE = {
		in_sync: "good",
		behind: "warn",
		ahead: "signal",
		diverged: "warn",
		dirty: "warn",
		no_remote: "outline",
		never_checked: "outline",
	};
	const RISK_BADGE = { Low: "good", Medium: "outline", High: "warn", Critical: "warn" };
	const STATE_COLOR = {
		in_sync: PH.statusColor.good,
		behind: PH.statusColor.warn,
		ahead: PH.statusColor.signal,
		diverged: PH.statusColor.ink,
		dirty: "#8a8a80",
		no_remote: PH.statusColor.mute,
		never_checked: "#d9d7cf",
	};
	const SCOPE_SELECTS = ["#f-app", "#f-status", "#f-version", "#f-recorded", "#f-risk", "#f-safe"];

	const st = PH.state({
		view: "apps",
		app: "",
		status: "",
		version: "",
		recorded: "",
		risk: "",
		safe: "",
		q: "",
		from: "",
		to: "",
		open: "",
	});
	const n = PH.fmt.num;
	const e = PH.esc;
	const selected = new Set();
	let data = null;
	let seq = 0;

	const can = () => (data && data.can) || {};
	const dash = (v) => (v === null || v === undefined || v === "" ? "—" : v);
	const ageText = (d) => (d == null ? "never" : d < 1 ? "today" : Math.round(d) + " d ago");
	const badge = (cls, text) => `<span class="ph-badge ph-badge--${cls}">${e(text)}</span>`;
	const verBadge = (r) => {
		const [text, cls] = VER[r.version_result] || VER.unknown;
		return badge(cls, text);
	};
	const stateBadge = (r) => badge(STATE_BADGE[r.state] || "outline", r.state_label);
	const riskBadge = (r) =>
		r.stored_risk ? badge(RISK_BADGE[r.stored_risk] || "outline", r.stored_risk) : "—";
	const rowFor = (app) => (data ? data.rows.find((r) => r.app === app) : null);
	const repoShort = (r) => (r.repository_name || r.repo_url || "").replace(/^https?:\/\//, "");

	/* ---- filters, tabs ---- */
	PH.bindSelect("#f-app", st, "app");
	PH.bindSelect("#f-status", st, "status");
	PH.bindSelect("#f-version", st, "version");
	PH.bindSelect("#f-recorded", st, "recorded");
	PH.bindSelect("#f-risk", st, "risk");
	PH.bindSelect("#f-safe", st, "safe");
	PH.bindSearch("#f-q", st, "q");
	PH.dateRange({ pills: "#f-preset", from: "#f-from", to: "#f-to", state: st });
	PH.$("#f-preset").addEventListener("click", (ev) => {
		if (ev.target.closest("button[data-value='all']")) st.set({ from: "", to: "" });
	});
	PH.$("#tabs").addEventListener("click", (ev) => {
		const b = ev.target.closest("[data-view]");
		if (b) st.set({ view: b.dataset.view });
	});

	const currentView = () => (VIEWS.includes(st.get("view")) ? st.get("view") : "apps");
	function paintView() {
		const v = currentView();
		PH.$$("#tabs .ph-tab").forEach((b) => b.classList.toggle("is-on", b.dataset.view === v));
		VIEWS.forEach((x) => {
			PH.$("#view-" + x).hidden = x !== v;
		});
		const none = !data || !data.rows.length;
		PH.$("#export").disabled = none;
		PH.$("#export2").disabled = none;
		const noDates = !st.get("from") && !st.get("to");
		PH.$$("#f-preset button").forEach((b) =>
			b.classList.toggle(
				"is-on",
				b.dataset.value === "all" ? noDates : b.classList.contains("is-on") && !noDates
			)
		);
	}
	st.on((s, changed) => {
		paintView();
		if (changed.every((k) => k === "view" || k === "open")) {
			if (currentView() === "overview") redrawCharts();
			return;
		}
		load();
	});

	PH.kpiSkeleton("#kpis", [
		"Apps shown",
		"In step",
		"Code differs",
		"Versions differ",
		"Last refreshed",
	]);

	/* ---- table ---- */
	const tApps = PH.table("#t-apps", {
		columns: [
			{
				key: "record",
				label: "",
				sortable: false,
				html: (v) =>
					v && can().delete
						? `<input type="checkbox" data-sel="${e(v)}" aria-label="Select ${e(v)}" ${
								selected.has(v) ? "checked" : ""
						  }>`
						: "",
			},
			{ key: "app", label: "App", cls: "is-strong" },
			{ key: "recorded_version", label: "Version on record", cls: "vc-ver", format: dash },
			{ key: "code_version", label: "Version in code", cls: "vc-ver", format: dash },
			{ key: "version_result", label: "Versions", html: (v, r) => verBadge(r) },
			{
				key: "state",
				label: "Code vs remote",
				sortValue: (r) => STATE_RANK[r.state],
				html: (v, r) =>
					stateBadge(r) +
					(r.dirty && r.state !== "dirty" ? " " + badge("outline", "+ local changes") : ""),
			},
			{ key: "stored_risk", label: "Risk", html: (v, r) => riskBadge(r) },
			{ key: "behind", label: "Behind", num: true, total: true },
			{ key: "ahead", label: "Ahead", num: true, total: true },
			{ key: "branch", label: "Branch", cls: "ph-mono", format: dash },
			{
				key: "repository_name",
				label: "Repository",
				sortValue: repoShort,
				html: (v, r) =>
					repoShort(r)
						? `<button type="button" class="vc-repo" data-copy="${e(r.app)}" title="Copy repository URL">${e(
								repoShort(r)
						  )}</button>`
						: "—",
			},
			{ key: "age_days", label: "Last checked", format: ageText },
		],
		rows: [],
		compact: true,
		pageSize: 25,
		empty: "No apps match these filters",
		emptyText:
			"Press Scan bench and every installed app will report its branch, how far it has drifted from its remote, and whether it has uncommitted work.",
		sort: { key: "state", dir: "asc" },
		onRowClick: (r) => openApp(r.app),
	});

	/* ---- selection (bulk delete) ---- */
	function paintSelection() {
		const on = can().delete && data && data.rows.some((r) => r.record);
		PH.$("#selbar").hidden = !on || !selected.size;
		PH.text("#sel-count", PH.fmt.plural(selected.size, "record") + " selected");
	}
	PH.$("#t-apps").addEventListener("change", (ev) => {
		const box = ev.target.closest("input[data-sel]");
		if (!box) return;
		box.checked ? selected.add(box.dataset.sel) : selected.delete(box.dataset.sel);
		paintSelection();
	});
	PH.$("#sel-all").addEventListener("click", () => {
		data.rows.forEach((r) => r.record && selected.add(r.record));
		tApps.render();
		paintSelection();
	});
	PH.$("#sel-none").addEventListener("click", () => {
		selected.clear();
		tApps.render();
		paintSelection();
	});
	PH.$("#sel-delete").addEventListener("click", async () => {
		const names = [...selected];
		const ok = await PH.confirm(
			"Delete " + PH.fmt.plural(names.length, "record") + "?",
			"This removes the stored check records (not the apps). Scan bench can create them again.",
			{ ok: "Delete", danger: true }
		);
		if (!ok) return;
		let done = 0;
		const failed = [];
		for (const name of names) {
			try {
				await PH.call(EP.remove, { doctype: DOCTYPE, name }, { silent: true });
				done++;
			} catch (err) {
				failed.push(name + ": " + err.message);
			}
		}
		selected.clear();
		PH.toast(
			"Deleted " + done + (failed.length ? "; could not delete " + failed.join(", ") : ""),
			failed.length ? "bad" : "good"
		);
		load();
	});

	PH.$("#t-apps").addEventListener("click", (ev) => {
		const b = ev.target.closest("button[data-copy]");
		if (b) copyRepo(rowFor(b.dataset.copy));
	});
	function copyRepo(r) {
		const url = r && (r.repo_url || r.repository_name);
		if (!url) return;
		const done = () => PH.toast("Repository URL copied", "good");
		const fail = () => PH.toast("Could not copy that", "bad");
		if (navigator.clipboard && navigator.clipboard.writeText)
			navigator.clipboard.writeText(url).then(done, fail);
		else fail();
	}

	/* ---- record form (detail) ---- */
	function kvRows(r) {
		const kv = (k, v) => `<dt>${e(k)}</dt><dd>${v}</dd>`;
		const flag = (on, text) => (on ? " " + badge("warn", text) : "");
		const yn = (v) => (v ? "Yes" : "No");
		const link = (url) =>
			url && /^https?:\/\//.test(url)
				? `<a class="ph-link" target="_blank" rel="noopener" href="${e(url)}">${e(url)}</a>`
				: e(dash(url));
		const recorded = r.stored_status ? data.recorded_labels[r.stored_status] || r.stored_status : "Not Checked";
		return [
			kv("Module/App name", e(r.record || r.app)),
			kv("App folder", e(dash(r.record ? r.app : ""))),
			kv("GitHub repository", e(dash(r.repository_name))),
			kv("Repository URL", link(r.repo_url)),
			kv("Environment", e(dash(r.environment))),
			kv("Current commit", e(dash(r.commit))),
			kv("Active branch", e(dash(r.branch)) + flag(r.branch_differs, "differs from the branch on record")),
			kv("Upstream branch", e(dash(r.upstream))),
			kv("Status", e(recorded) + flag(r.label_differs, "differs from the counts")),
			kv("Commits ahead / behind", e(n(r.ahead) + " / " + n(r.behind))),
			kv("Has uncommitted changes", yn(r.dirty)),
			kv("Safe to deploy", yn(r.safe_to_deploy)),
			kv("Risk level", e(dash(r.stored_risk)) + flag(r.risk_differs, "differs from the Desk check's rule")),
			kv(
				"Last checked",
				r.last_checked_at
					? e(PH.fmt.datetime(r.last_checked_at)) +
							" (" +
							e(ageText(r.age_days)) +
							")" +
							(r.last_checked_by ? " by " + e(r.last_checked_by) : "")
					: "never"
			),
			kv("Status message", `<span class="vc-msg">${e(dash(r.message))}</span>`),
			kv("Version on record (site)", e(dash(r.recorded_version))),
			kv("Version in code now", e(dash(r.code_version))),
			kv("Branch on record (site)", e(dash(r.recorded_branch))),
			kv("Created / modified", r.created ? e(PH.fmt.datetime(r.created)) + " / " + e(PH.fmt.datetime(r.modified)) + " · " + e(r.owner) : "—"),
		].join("");
	}

	function actionButtons(r) {
		const c = can();
		const btn = (act, label, cls) => `<button type="button" class="ph-btn ph-btn--sm ${cls || ""}" data-act="${act}">${label}</button>`;
		const out = [];
		if (r.record) {
			if (c.read) {
				out.push(btn("check", "Run version check", "ph-btn--primary"));
				out.push(btn("fetch", "Fetch remote updates"));
			}
			if (c.write) out.push(btn("edit", "Edit"), btn("rename", "Rename"));
			if (c.delete) out.push(btn("delete", "Delete", "ph-btn--danger"));
		} else if (c.create) {
			out.push(btn("create", "Create record for this app", "ph-btn--primary"));
		}
		if (r.repo_url || r.repository_name) out.push(btn("copy", "Copy repository URL"));
		if (r.record && c.read) out.push(`<a class="ph-btn ph-btn--sm" target="_blank" rel="noopener" href="${e(PH.docUrl(DOCTYPE, r.record))}">Open in Desk</a>`);
		return out.join("");
	}

	function openApp(app) {
		const body = document.createElement("div");
		PH.skeleton(body);
		const m = PH.modal({ title: app, sub: "The stored record and the live version comparison", body, size: "lg" });
		PH.call(READ + "get_version_check_detail", { app }, { silent: true })
			.then((d) => {
				const r = d.row;
				body.innerHTML = `
					<div class="ph-flex ph-flex--wrap ph-mb">${verBadge(r)} ${stateBadge(r)}${r.dirty ? " " + badge("warn", "Local changes") : ""} ${riskBadge(r)}</div>
					<p class="ph-muted">${e(VER_EXPLAIN[r.version_result])}</p>
					<div class="ph-flex ph-flex--wrap ph-mb">${actionButtons(r)}</div>
					<dl class="ph-kv ph-mb">${kvRows(r)}</dl>
					<div class="ph-strong ph-mb-0">Recorded changes</div>
					<div id="vc-changes" class="ph-muted"></div>`;
				const ch = body.querySelector("#vc-changes");
				if (!d.changes.length) ch.textContent = "None. Changes to this record are not tracked, so there is no earlier state to show.";
				else ch.innerHTML = d.changes.map((c) => `<div>${e(PH.fmt.datetime(c.when))} · ${e(c.by)}: ${c.fields.map((f) => e(f.field + " " + dash(f.from) + " → " + dash(f.to))).join("; ")}</div>`).join("");
				body.addEventListener("click", (ev) => {
					const b = ev.target.closest("button[data-act]");
					if (b) recordAction(b.dataset.act, r, m, b);
				});
			})
			.catch((err) => PH.error(body, err.message, () => { m.close(); openApp(app); }));
		return m;
	}

	/** Run a write, reload the list, and reopen the record (or just close when it is gone). */
	async function afterWrite(m, app) {
		m.close();
		await load();
		if (app) openApp(app);
	}

	function recordAction(act, r, m, button) {
		if (act === "copy") return copyRepo(r);
		if (act === "check" || act === "fetch") return runCheck(act === "fetch", r, m, button);
		if (act === "edit") return editRecord(r, m);
		if (act === "rename") return renameRecord(r, m);
		if (act === "create") return createRecord(r.app, m);
		if (act === "delete") return deleteRecord(r, m);
	}

	async function runCheck(withFetch, r, m, button) {
		const label = button.textContent;
		m.el.querySelectorAll("button[data-act]").forEach((b) => (b.disabled = true));
		button.textContent = withFetch ? "Fetching…" : "Checking…";
		try {
			const doc = await PH.call(withFetch ? EP.checkWithFetch : EP.check, { docname: r.record });
			PH.toast(
				(withFetch ? "Remote fetch check completed: " : "Version check completed: ") + doc.status,
				doc.status === "Clean" ? "good" : ""
			);
			await afterWrite(m, r.app);
		} catch (err) {
			button.textContent = label;
			m.el.querySelectorAll("button[data-act]").forEach((b) => (b.disabled = false));
		}
	}

	/** Small form modal: fields [{key, label, value, required, hint}] -> onSave(values). */
	function formModal(title, sub, fields, saveLabel, onSave) {
		const body = document.createElement("form");
		body.className = "ph-form ph-form--1";
		body.noValidate = true;
		body.innerHTML = fields
			.map(
				(f) => `<div class="ph-field"><label for="vc-f-${f.key}">${e(f.label)}</label>
					<input class="ph-input" id="vc-f-${f.key}" name="${f.key}" value="${e(f.value || "")}" autocomplete="off">
					${f.hint ? `<div class="ph-field__hint">${e(f.hint)}</div>` : ""}
					<div class="ph-field__error" data-err="${f.key}" hidden></div></div>`
			)
			.join("");
		const save = (modal) => {
			const values = {};
			let bad = false;
			fields.forEach((f) => {
				values[f.key] = body.elements[f.key].value.trim();
				const err = body.querySelector(`[data-err="${f.key}"]`);
				err.hidden = !(f.required && !values[f.key]);
				err.textContent = err.hidden ? "" : f.label + " is required";
				bad = bad || !err.hidden;
			});
			return bad ? false : onSave(values, modal);
		};
		const modal = PH.modal({
			title,
			sub,
			body,
			actions: [{ label: "Cancel" }, { label: saveLabel, primary: true, onClick: save }],
		});
		body.addEventListener("submit", (ev) => {
			ev.preventDefault();
			modal.el.querySelector(".ph-btn--primary").click();
		});
		return modal;
	}

	function editRecord(r, parent) {
		formModal(
			"Edit " + r.record,
			"Only the name and the GitHub repository are editable; the rest is filled in by the checks.",
			[
				{ key: "module_name", label: "Module/App name", value: r.record, required: true },
				{ key: "repository_name", label: "GitHub repository", value: r.repository_name },
			],
			"Save",
			async (v) => {
				const changed = {};
				if (v.module_name !== r.record) changed.module_name = v.module_name;
				if (v.repository_name !== r.repository_name) changed.repository_name = v.repository_name;
				if (Object.keys(changed).length) {
					await PH.call(EP.setValue, { doctype: DOCTYPE, name: r.record, fieldname: JSON.stringify(changed) });
					PH.toast("Saved", "good");
				}
				parent.close();
				await load();
				openApp(r.app);
			}
		);
	}

	function renameRecord(r, parent) {
		formModal(
			"Rename " + r.record,
			"Changes the record's name only; use Edit to change the app name it checks.",
			[{ key: "name", label: "New name", value: r.record, required: true }],
			"Rename",
			async (v) => {
				if (v.name !== r.record)
					await PH.call(EP.rename, { doctype: DOCTYPE, old_name: r.record, new_name: v.name });
				PH.toast("Renamed", "good");
				parent.close();
				await load();
				if (rowFor(v.name)) openApp(v.name);
			}
		);
	}

	function createRecord(prefill, parent) {
		formModal(
			"New version check record",
			"One record per app. Run a check on it afterwards to fill in the git state.",
			[
				{ key: "module_name", label: "Module/App name", value: prefill, required: true, hint: "Must be the name of an app folder in the bench's apps directory for checks to work." },
				{ key: "repository_name", label: "GitHub repository", value: "" },
			],
			"Create",
			async (v) => {
				const doc = { doctype: DOCTYPE, module_name: v.module_name };
				if (v.repository_name) doc.repository_name = v.repository_name;
				const made = await PH.call(EP.insert, { doc: JSON.stringify(doc) });
				PH.toast("Created " + made.name, "good");
				if (parent) parent.close();
				await load();
				openApp(made.name);
			}
		);
	}

	async function deleteRecord(r, m) {
		const ok = await PH.confirm("Delete " + r.record + "?", "This removes the stored check record (not the app). Scan bench can create it again.", { ok: "Delete", danger: true });
		if (!ok) return;
		await PH.call(EP.remove, { doctype: DOCTYPE, name: r.record });
		PH.toast("Deleted " + r.record, "good");
		await afterWrite(m, null);
	}

	/* ---- header actions ---- */
	function scanBench() {
		const body = document.createElement("div");
		body.innerHTML = `<p class="ph-muted">Reads the git state of every installed app and stores it. By default it compares with the remote as last fetched.</p>
			<label class="ph-check"><input type="checkbox" id="vc-fetch"> Fetch from every remote first (slow, needs the network)</label>`;
		PH.modal({
			title: "Scan bench",
			body,
			actions: [
				{ label: "Cancel" },
				{
					label: "Scan",
					primary: true,
					onClick: async () => {
						const args = body.querySelector("#vc-fetch").checked ? { fetch: 1 } : {};
						const r = await PH.call(EP.scanBench, args);
						PH.toast("Read " + r.checked + " apps" + (r.failed.length ? "; could not read " + r.failed.join(", ") : ""), r.failed.length ? "bad" : "good");
						load();
					},
				},
			],
		});
	}
	async function scanInstalled() {
		const ok = await PH.confirm("Scan installed apps?", "Creates a record for each installed app that has none, and fills in each app's repository URL. It does not run the git checks.", { ok: "Scan" });
		if (!ok) return;
		const r = await PH.call(EP.scanInstalled, {});
		PH.toast(`Scan complete. Created ${r.created}, updated ${r.updated}, skipped ${r.skipped}, total apps ${r.total}.`, r.errors.length ? "bad" : "good");
		load();
	}
	PH.$("#scan-bench").addEventListener("click", scanBench);
	PH.$("#scan-installed").addEventListener("click", () => scanInstalled().catch(() => {}));
	PH.$("#new").addEventListener("click", () => createRecord("", null));

	/* ---- load + render ---- */
	function args() {
		const s = st.get();
		const a = { from_date: s.from, to_date: s.to };
		["app", "status", "version", "recorded", "risk", "safe", "q"].forEach((k) => (a[k] = s[k]));
		return a;
	}
	function load() {
		const my = ++seq;
		PH.loadingKpis("#kpis", true);
		return PH.call(READ + "get_version_check", args(), { silent: true })
			.then((m) => {
				if (my !== seq) return;
				data = m;
				render();
				PH.markUpdated();
				const open = st.get("open");
				if (open) {
					st.set({ open: "" }, { silent: true });
					openApp(open);
				}
			})
			.catch((err) => {
				if (my !== seq) return;
				PH.loadingKpis("#kpis", false);
				["#t-apps", "#c-states", "#behind-bars", "#history", "#checks"].forEach((x) => PH.error(x, err.message, () => load()));
				PH.set("#notes", "");
				paintView();
			});
	}

	function setState(status) {
		st.set({ status: st.get("status") === status ? "" : status, view: "apps" });
	}

	function redrawCharts() {
		if (!data) return;
		const t = data.totals;
		const keys = Object.keys(data.state_labels).filter((k) => t.states[k] > 0);
		if (!keys.length) return PH.empty("#c-states", "No apps to show", "Nothing matches the filters.");
		PH.chart("#c-states", {
			type: "doughnut",
			labels: keys.map((k) => data.state_labels[k]),
			legend: true,
			series: [{ label: "Apps", data: keys.map((k) => t.states[k]), colors: keys.map((k) => STATE_COLOR[k]) }],
			onClick: (i) => keys[i] && setState(keys[i]),
		});
	}

	function renderFilters(d, s) {
		const opt = (items, any) => [{ value: "", label: any }].concat(items);
		PH.options("#f-app", opt(d.options.apps.map((a) => ({ value: a, label: a })), "All apps"), s.app);
		PH.options(
			"#f-status",
			opt([{ value: "differs", label: "Code differs from remote" }].concat(Object.keys(d.state_labels).map((k) => ({ value: k, label: d.state_labels[k] + " (" + d.state_counts[k] + ")" }))), "Any code state"),
			s.status
		);
		PH.options("#f-recorded", opt(d.options.recorded, "Any recorded status"), s.recorded);
		PH.options("#f-risk", opt(d.options.risks.map((x) => ({ value: x, label: x })), "Any risk"), s.risk);
	}

	function renderHeader(d, s) {
		const t = d.totals;
		const scope = SCOPE_SELECTS.map((sel) => PH.$(sel))
			.filter((el) => el.value)
			.map((el) => el.selectedOptions[0].textContent);
		if (s.q) scope.push("“" + s.q + "”");
		PH.text(
			"#sub",
			PH.fmt.plural(t.apps, "app") +
				` · ${n(t.in_sync)} in step · ${n(t.states.behind + t.states.diverged)} behind remote · ${n(t.with_local_changes)} with local changes` +
				(s.from || s.to ? " · checked " + PH.date.label(s.from, s.to) : "") +
				(scope.length ? " · " + scope.join(" · ") : "")
		);
		PH.$("#scan-installed").hidden = !d.can.read;
		PH.$("#new").hidden = !d.can.create;
	}

	function renderKpis(d, s) {
		const t = d.totals;
		const f = d.freshness;
		PH.kpis("#kpis", [
			{ label: "Apps shown", value: t.apps, unit: "on this site", dark: true },
			{ label: "In step", value: t.in_sync, unit: t.apps ? Math.round((100 * t.in_sync) / t.apps) + "% of apps" : "", title: "No commits behind or ahead of the remote, and no local changes", onClick: () => setState("in_sync"), active: s.status === "in_sync" },
			{ label: "Code differs", value: t.differs, unit: n(t.commits_behind) + " commits behind", onClick: () => setState("differs"), active: s.status === "differs", title: "Behind, ahead, both, or only local changes (" + n(t.with_local_changes) + " apps have local changes)" },
			{ label: "Versions differ", value: t.version_differs, unit: t.version_unknown ? n(t.version_unknown) + " can't compare" : "record vs code", onClick: () => st.set({ version: s.version === "differs" ? "" : "differs", view: "apps" }), active: s.version === "differs" },
			{ label: "Last refreshed", value: f.last_checked_at ? ageText(f.age_days) : "never", unit: f.last_checked_at ? PH.fmt.datetime(f.last_checked_at) : "no checks stored", title: "When the stored git checks were last run. This page only runs a check when you press a scan or check button." },
		]);
	}

	function renderNotes(d) {
		const f = d.freshness;
		const notes = [`<div class="ph-notice ph-notice--signal">These are the stored results${f.last_checked_at ? ", last refreshed " + e(PH.fmt.datetime(f.last_checked_at)) + " (" + e(ageText(f.age_days)) + ")" : ""}. Loading this page never runs a check; use Scan bench, or Run version check on an app, to refresh. Versions on record were last written ${f.versions_recorded_at ? e(PH.fmt.datetime(f.versions_recorded_at)) : "—"}.</div>`];
		if (f.age_days != null && f.age_days > f.old_after_days) notes.push(`<div class="ph-notice ph-notice--warn">The stored checks are over ${f.old_after_days} days old, so the code state may no longer match what is on disk.</div>`);
		if (d.truncated) notes.push(`<div class="ph-notice ph-notice--signal">Showing ${n(d.row_limit)} of ${n(d.totals.apps)} apps. The figures above cover all of them.</div>`);
		PH.set("#notes", notes.join(""));
	}

	function renderOverview(d) {
		const max = Math.max(1, ...d.behind_chart.map((x) => x.behind));
		PH.set("#behind-bars", d.behind_chart.map((x, i) => `<div class="vc-bar" data-i="${i}" title="${e(x.app)}: ${e(n(x.behind))} commits behind"><span>${e(x.app)}</span><b>${n(x.behind)}</b><div class="ph-progress"><i class="warn" style="width:${(100 * x.behind) / max}%"></i></div></div>`).join("") || '<div class="ph-empty">No app is behind its remote</div>');
		PH.$$(".vc-bar", PH.$("#behind-bars")).forEach((el) => el.addEventListener("click", () => openApp(d.behind_chart[+el.dataset.i].app)));
		PH.empty("#history", "History is not kept yet", d.history.reason + " A line of how many apps differ will appear once checks are logged over time. Today: " + n(d.totals.differs) + " of " + n(d.totals.apps) + " differ.", "clock");
	}

	function renderChecks(d) {
		PH.set("#checks", d.checks.map((c) => `
			<div class="vc-check">
				<div class="vc-check__top"><b>${e(c.label)}</b>${badge(c.count ? "warn" : "good", c.count ? n(c.count) : "None")}</div>
				<div class="vc-check__hint">${e(c.hint)}</div>
				${c.apps.length ? `<div class="vc-chips">${c.apps.map((a) => `<button type="button" class="ph-badge ph-badge--outline vc-chip" data-app="${e(a)}">${e(a)}</button>`).join("")}</div>` : ""}
			</div>`).join(""));
		PH.$$("#checks [data-app]").forEach((b) => b.addEventListener("click", () => openApp(b.dataset.app)));
	}

	function render() {
		const d = data;
		const s = st.get();
		renderFilters(d, s);
		renderHeader(d, s);
		renderKpis(d, s);
		renderNotes(d);
		tApps.update(d.rows);
		PH.text("#tc-apps", n(d.totals.apps));
		PH.text("#tc-checks", n(d.checks.filter((c) => c.count > 0).length));
		renderOverview(d);
		renderChecks(d);
		if (currentView() === "overview") redrawCharts();
		paintView();
		paintSelection();
	}

	function exportCsv() {
		if (!data || !data.rows.length) return;
		const yn = (v) => (v ? "Yes" : "No");
		const cols = [
			["app", "App"], ["recorded_version", "Version on record"], ["code_version", "Version in code"],
			["version_result", "Version result"], ["state_label", "Code vs remote"], ["stored_status", "Recorded status"],
			["stored_risk", "Risk"], ["safe_to_deploy", "Safe to deploy", yn], ["behind", "Commits behind"], ["ahead", "Commits ahead"],
			["dirty", "Local changes", yn], ["branch", "Branch"], ["upstream", "Remote branch"], ["repository_name", "GitHub repository"],
			["repo_url", "Repository URL"], ["last_checked_at", "Last checked"],
		].map(([key, label, csv]) => ({ key, label, csv }));
		const s = st.get();
		PH.csv("version_check" + (s.from ? "_" + s.from + "_" + s.to : "") + ".csv", data.rows, cols);
	}
	PH.$("#export").addEventListener("click", exportCsv);
	PH.$("#export2").addEventListener("click", exportCsv);

	PH.onRefresh(() => load());
	DevKeys.init({ title: "Version Check", list: { root: "#ph-main", items: () => PH.$$("#ph-main tbody tr.is-link") } });
	PH.ready(() => {
		paintView();
		load();
	});
})();
