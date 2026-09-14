window.upande_dev_tools = window.upande_dev_tools || {};

const PRIORITIES = ["Low", "Medium", "High", "Urgent"];

upande_dev_tools.ReviewQueue = class ReviewQueue {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.requests = [];
		this.projects = [];
		this.people = [];
		this.q = "";
		this.render_shell();
		this.load();
	}

	load() {
		Promise.all([
			frappe.xcall("upande_dev_tools.api.requests.get_review_queue"),
			frappe.xcall("frappe.client.get_list", {
				doctype: "Project",
				fields: ["name", "project_name"],
				order_by: "project_name asc",
				limit_page_length: 0,
			}),
			frappe.xcall("upande_dev_tools.api.requests.get_assignable_users"),
		])
			.then(([requests, projects, people]) => {
				this.requests = requests || [];
				this.projects = projects || [];
				this.people = people || [];
				this.render();
			})
			.catch((e) =>
				this.stage().html(
					blank("Could not load the queue", String((e && e.message) || e) || "Reload to try again.")
				)
			);
	}

	stage() {
		return $(this.wrapper).find(".bb-stage");
	}

	render_shell() {
		$(this.wrapper).html(`
			<div class="dpx-board">
				<div class="dpx-bb-tb">
					<div class="dpx-bb-tb-hd">
						<div class="dpx-bb-tb-title">
							<div class="dpx-bb-tb-row">
								<span class="dpx-bb-mark">${rq_ico("inbox", 14)}</span>
								<h2>Requests</h2>
							</div>
							<div class="dpx-bb-tb-sub">Decide what gets built, and who builds it</div>
						</div>
						<div class="dpx-bb-tb-act">
							<button class="dpx-bb-ico rq-reload" type="button" title="Refresh">${rq_ico("refresh")}</button>
						</div>
					</div>
					<div class="dpx-bb-tb-cmd">
						<div class="dpx-bb-grp">
							<input type="search" class="dpx-bb-field dpx-bb-search rq-q"
								placeholder="Search requests" aria-label="Search requests">
						</div>
						<span class="dpx-bb-hint">
							<span>Set a project, pick who takes it, then accept</span>
							<span class="dpx-bb-kbd">/</span><span>search</span>
						</span>
					</div>
				</div>
				<div class="rq-stats"></div>
				<div class="bb-stage"></div>
				<div class="dpx-bb-status"></div>
			</div>
		`);

		const root = $(this.wrapper);
		root.on("click", ".rq-reload", () => this.load());
		document.addEventListener("keydown", (e) => {
			if (e.key !== "/" || /^(INPUT|SELECT|TEXTAREA)$/.test((e.target || {}).tagName || "")) return;
			e.preventDefault();
			root.find(".rq-q").trigger("focus").trigger("select");
		});
		root.on("input", ".rq-q", (e) => {
			this.q = $(e.currentTarget).val().toLowerCase();
			clearTimeout(this.typing);
			this.typing = setTimeout(() => this.render(), 180);
		});
		root.on("click", ".rq-act", (e) => this.act($(e.currentTarget)));
	}

	visible() {
		if (!this.q) return this.requests;
		return this.requests.filter((r) =>
			[r.title, r.name, r.product_area, r.raised_by_user, r.request_type]
				.filter(Boolean)
				.some((v) => String(v).toLowerCase().includes(this.q))
		);
	}

	render() {
		const rows = this.visible();
		this.render_stats(rows);

		if (!rows.length) {
			return this.stage().html(
				blank(
					this.q ? "No request matches that search" : "Nothing waiting",
					this.q
						? "Clear the search to see the whole queue."
						: "Requests raised from the portal land here for a decision. When one arrives you can set its project, pick who takes it, and accept in a single row."
				)
			);
		}

		this.stage().html(
			`<div class="dpx-card"><div class="dpx-card-body dpx-bb-listwrap" style="padding:0 0 4px">
				<table class="dpx-bb-table rq-table">
					<colgroup><col><col style="width:104px"><col style="width:74px"><col style="width:158px"><col style="width:132px"><col style="width:150px"><col style="width:132px"></colgroup>
					<thead><tr>
						<th>Request</th><th>Raised by</th><th>Waiting</th>
						<th>Project</th><th>Priority</th><th>Assign to</th><th>Decision</th>
					</tr></thead>
					<tbody>${rows.map((r) => this.row(r)).join("")}</tbody>
				</table>
			</div></div>`
		);
	}

	render_stats(rows) {
		const ages = rows.map((r) => age_days(r.creation));
		const oldest = ages.length ? Math.max(...ages) : 0;
		const stale = ages.filter((d) => d >= 7).length;
		const types = {};
		rows.forEach((r) => (types[r.request_type || "Other"] = (types[r.request_type || "Other"] || 0) + 1));
		const spread = Object.entries(types)
			.sort((a, b) => b[1] - a[1])
			.slice(0, 3)
			.map(([k, n]) => `${rq_esc(k)} ${n}`)
			.join(" · ");

		$(this.wrapper).find(".rq-stats").html(
			[
				stat("Awaiting review", rows.length, rows.length ? "" : "Queue is clear"),
				stat("Longest wait", oldest ? `${oldest}d` : "today", oldest >= 7 ? "Past a week" : "Within a week", oldest >= 7),
				stat("Waiting over 7 days", stale, stale ? "Needs a decision" : "None", stale > 0),
				stat("Mix", spread || "—", "By request type", false, true),
			].join("")
		);

		$(this.wrapper)
			.find(".dpx-bb-status")
			.html(
				`<b>${rows.length}</b> awaiting review<span class="sep">·</span><b>${this.people.length}</b> ${
					this.people.length === 1 ? "person" : "people"
				} to assign<span class="sp">Rejecting asks twice</span>`
			);
	}

	row(r) {
		const days = age_days(r.creation);
		const opts = (list, selected, blankLabel) =>
			[blankLabel ? `<option value="">${rq_esc(blankLabel)}</option>` : ""]
				.concat(
					list.map(
						([value, label]) =>
							`<option value="${rq_esc(value)}"${value === selected ? " selected" : ""}>${rq_esc(label)}</option>`
					)
				)
				.join("");

		return `
			<tr class="dpx-bb-row" data-name="${rq_esc(r.name)}">
				<td><div class="rq-subj">
					<a href="/app/request/${encodeURIComponent(r.name)}">${rq_esc(r.title)}</a>
					<div class="rq-meta"><span class="dpx-bb-src">${rq_esc(r.request_type || "REQ")}</span>
						${r.product_area ? `<span>${rq_esc(r.product_area)}</span>` : ""}
						<span class="rq-id">${rq_esc(r.name)}</span></div>
				</div></td>
				<td class="rq-from">${rq_esc((r.raised_by_user || "—").split("@")[0])}</td>
				<td><span class="rq-age${days >= 7 ? " hot" : ""}">${days === 0 ? "today" : days + "d"}</span></td>
				<td><select class="dpx-bb-field rq-project">${opts(
					this.projects.map((p) => [p.name, p.project_name || p.name]),
					r.project,
					"Pick a project"
				)}</select></td>
				<td><select class="dpx-bb-field rq-priority">${opts(
					PRIORITIES.map((p) => [p, p]),
					r.priority || "Medium",
					null
				)}</select></td>
				<td><select class="dpx-bb-field rq-assignee">${opts(
					this.people.map((p) => [p.name, p.full_name || p.name]),
					null,
					"Unassigned"
				)}</select></td>
				<td class="rq-decide">
					<button class="rq-btn accept rq-act" data-act="accept" title="Accept and assign"
						aria-label="Accept and assign">${rq_ico("check", 14)}</button>
					<button class="rq-btn rq-act" data-act="Defer" title="Defer for now"
						aria-label="Defer">${rq_ico("clock", 14)}</button>
					<button class="rq-btn reject rq-act" data-act="Reject" title="Reject"
						aria-label="Reject">${rq_ico("x", 14)}</button>
				</td>
			</tr>`;
	}

	act(btn) {
		const tr = btn.closest("tr");
		const name = tr.data("name");
		const action = btn.data("act");
		const project = tr.find(".rq-project").val();
		const priority = tr.find(".rq-priority").val();
		const assign_to = tr.find(".rq-assignee").val();

		if (action === "Reject" && !btn.hasClass("armed")) {
			btn.addClass("armed").attr("title", "Click again to reject");
			clearTimeout(this.arming);
			this.arming = setTimeout(() => btn.removeClass("armed").attr("title", "Reject"), 2600);
			return;
		}

		if (action === "accept" && !project) {
			frappe.show_alert({ message: __("Pick a project first."), indicator: "orange" });
			return tr.find(".rq-project").trigger("focus");
		}

		tr.find("button,select").prop("disabled", true);
		tr.addClass("rq-busy");

		const call =
			action === "accept"
				? frappe.xcall("upande_dev_tools.api.requests.accept_request", {
						name,
						project,
						priority,
						assign_to: assign_to || null,
					})
				: frappe.xcall("upande_dev_tools.api.requests.triage_request", {
						name,
						action,
						project: project || null,
						priority,
					});

		call
			.then((r) => {
				this.requests = this.requests.filter((row) => row.name !== name);
				this.render();
				frappe.show_alert({
					message:
						action === "accept"
							? __("Accepted. {0} created{1}.", [
									r.task || "Task",
									assign_to ? ` for ${tr.find(".rq-assignee option:selected").text()}` : "",
								])
							: __("{0} marked {1}.", [name, action.toLowerCase() + "red"]),
					indicator: "green",
				});
			})
			.catch((e) => {
				tr.find("button,select").prop("disabled", false);
				tr.removeClass("rq-busy");
				frappe.show_alert({
					message: String((e && e.message) || e) || __("That decision did not save."),
					indicator: "red",
				});
			});
	}
};

function stat(label, value, note, warn, small) {
	return `<div class="rq-stat${warn ? " warn" : ""}">
		<div class="lbl">${rq_esc(label)}</div>
		<div class="val${small ? " text" : ""}">${rq_esc(value)}</div>
		<div class="note">${rq_esc(note || "")}</div>
	</div>`;
}

function age_days(creation) {
	if (!creation) return 0;
	const then = new Date(String(creation).replace(" ", "T"));
	return Math.max(0, Math.floor((Date.now() - then.getTime()) / 86400000));
}

function blank(heading, body) {
	return `<div class="dpx-card"><div class="dpx-bb-blank">
		<h3>${rq_esc(heading)}</h3><p>${rq_esc(body)}</p></div></div>`;
}

const RQ_ICONS = {
	check: '<path d="M20 6 9 17l-5-5"/>',
	x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
	clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
	inbox: '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
	refresh: '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
};

function rq_ico(name, size) {
	const s = size || 15;
	return `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="currentColor"
		stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${RQ_ICONS[name] || ""}</svg>`;
}

function rq_esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}
