window.upande_dev_tools = window.upande_dev_tools || {};

const RP_STAGE = {
	"": ["st-triage", "Waiting for a decision"],
	"Under Review": ["st-triage", "Waiting for a decision"],
	Approved: ["st-in-progress", "Accepted"],
	Scheduled: ["st-in-progress", "Scheduled"],
	"In Progress": ["st-in-progress", "Being built"],
	Completed: ["st-done", "Done"],
	Rejected: ["st-blocked", "Not going ahead"],
	Deferred: ["st-in-review", "Parked for now"],
	Withdrawn: ["st-blocked", "Withdrawn"],
	Closed: ["st-done", "Closed"],
};

upande_dev_tools.RequestsPortal = class RequestsPortal {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.requests = [];
		this.types = [];
		this.areas = [];
		this.filter = "";
		this.raised_by = "";
		this.assignee = "";
		this.sort_by = "newest";
		this.render_shell();
		this.load();
	}

	load() {
		const icon = $(this.wrapper).find(".rp-reload").addClass("spin");
		if (!this.requests.length) this.skeleton();
		Promise.all([
			frappe.xcall("upande_dev_tools.api.requests.get_my_requests"),
			frappe.xcall("frappe.client.get_list", {
				doctype: "Request Type",
				limit_page_length: 0,
			}),
			frappe.xcall("upande_dev_tools.api.board.get_modules"),
			frappe.xcall("upande_dev_tools.api.requests.get_employees"),
			frappe.xcall("upande_dev_tools.api.requests.get_assignable_users"),
			frappe.xcall("upande_dev_tools.api.board.get_work_tags"),
		])
			.then(([requests, types, areas, employees, people, work_tags]) => {
				this.requests = requests || [];
				this.types = (types || []).map((t) => t.name);
				this.areas = areas || [];
				this.employees = employees || [];
				// A <datalist> is drawn by the browser and cannot be styled, so "Raised for"
				// uses this portal's own combobox instead - it just needs the list under a name.
				// {name, full_name} is the shape that widget searches and labels by; here `name`
				// is the Employee id the form submits, not an email.
				upande_dev_tools.register_link_source(
					"rp-employees",
					this.employees.map((e) => ({ name: e.name, full_name: e.employee_name }))
				);
				this.people = people || [];
				upande_dev_tools.seed_users(this.people);
				this.work_tags = work_tags || [];
				this.stage().removeAttr("aria-busy");
				this.render();
				icon.removeClass("spin");
			})
			.catch((e) => {
				icon.removeClass("spin");
				this.stage().html(
					rp_blank(
						"Could not load your requests",
						String((e && e.message) || e) || "Reload to try again."
					)
				);
			});
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
								<span class="dpx-bb-mark">${rp_ico("inbox", 14)}</span>
								<h2>My requests</h2>
							</div>
							<div class="dpx-bb-tb-sub">What you have asked the dev team for, and where each one stands</div>
						</div>
						<div class="dpx-bb-tb-act">
							<button class="dpx-bb-ico rp-reload" type="button" title="Refresh">${rp_ico("refresh")}</button>
							<span class="dpx-bb-div"></span>
							<button class="dpx-bb-btn primary rp-new" type="button">Raise a request</button>
						</div>
					</div>
					<div class="dpx-bb-tb-cmd">
						<div class="dpx-bb-grp">
							<span class="dpx-bb-grp-lbl">Show</span>
							<select class="dpx-bb-field rp-filter" aria-label="Filter by state">
								<option value="">Everything</option>
								<option value="open">Still open</option>
								<option value="done">Finished</option>
							</select>
							<select class="dpx-bb-field rp-raised-by" aria-label="Raised by">
								<option value="">Anyone raised it</option>
							</select>
							<select class="dpx-bb-field rp-assignee" aria-label="Assigned to">
								<option value="">Anyone assigned</option>
							</select>
						</div>
						<div class="dpx-bb-grp">
							<span class="dpx-bb-grp-lbl">Sort</span>
							<select class="dpx-bb-field rp-sort" aria-label="Sort by">
								<option value="newest">Newest first</option>
								<option value="oldest">Oldest first</option>
								<option value="priority">Priority</option>
								<option value="title">Title</option>
							</select>
						</div>
						<span class="dpx-bb-hint rp-count"></span>
					</div>
				</div>
				<div class="bb-stage"></div>
			</div>
			<div class="rp-sheet" hidden></div>
		`);

		const root = $(this.wrapper);
		root.on("click", ".rp-reload", () => this.load());
		root.on("change", ".rp-filter", (e) => {
			this.filter = $(e.currentTarget).val();
			this.render();
		});
		root.on("change", ".rp-raised-by", (e) => {
			this.raised_by = $(e.currentTarget).val();
			this.render();
		});
		root.on("change", ".rp-assignee", (e) => {
			this.assignee = $(e.currentTarget).val();
			this.render();
		});
		root.on("change", ".rp-sort", (e) => {
			this.sort_by = $(e.currentTarget).val();
			this.render();
		});
		root.on("click", ".rp-new", () => this.open_form());
		root.on("click", ".rp-close, .rp-scrim", () => this.close_form());
		root.on("submit", ".rp-form", (e) => {
			e.preventDefault();
			this.submit();
		});
		root.on("click", ".rp-withdraw", (e) => {
			e.preventDefault();
			e.stopPropagation();
			const name = $(e.currentTarget).closest("[data-name]").data("name");
			// A plain browser confirm() here, not frappe.confirm()'s dialog - guaranteed to
			// work with zero library dependency, for an action simple enough not to need more.
			if (window.confirm(__("Withdraw this request?"))) {
				this.act(name, "withdraw_request", __("Withdrawn."));
			}
		});
		root.on("click", ".rp-confirm-done", (e) => {
			e.preventDefault();
			e.stopPropagation();
			const name = $(e.currentTarget).closest("[data-name]").data("name");
			this.act(name, "confirm_request_complete", __("Confirmed - closed."));
		});
		document.addEventListener("keydown", (e) => {
			if (e.key === "Escape") this.close_form();
		});
	}

	skeleton() {
		this.stage()
			.attr("aria-busy", "true")
			.html(
				`<div class="dpx-skel" aria-hidden="true"><div class="dpx-card sk-plain">
				${[1, 2, 3, 4]
					.map(
						() => `<div class="sk-line" style="padding:13px 14px">
							<i class="sk" style="width:38%"></i><i class="sk chip"></i>
							<i class="sk w10 right"></i></div>`
					)
					.join("")}
			</div></div>`
			);
	}

	visible() {
		let rows = this.requests;
		if (this.filter === "open")
			rows = rows.filter((r) => !["Completed", "Rejected", "Withdrawn", "Closed"].includes(r.workflow_state));
		else if (this.filter === "done")
			rows = rows.filter((r) => ["Completed", "Rejected", "Withdrawn", "Closed"].includes(r.workflow_state));

		if (this.raised_by) rows = rows.filter((r) => r.owner === this.raised_by);
		if (this.assignee) rows = rows.filter((r) => (r.assignees || []).includes(this.assignee));

		const rank = { Urgent: 4, High: 3, Medium: 2, Low: 1 };
		rows = rows.slice();
		if (this.sort_by === "oldest") rows.sort((a, b) => (a.creation < b.creation ? -1 : 1));
		else if (this.sort_by === "priority")
			rows.sort((a, b) => (rank[b.priority] || 0) - (rank[a.priority] || 0));
		else if (this.sort_by === "title") rows.sort((a, b) => a.title.localeCompare(b.title));
		else rows.sort((a, b) => (a.creation > b.creation ? -1 : 1));

		return rows;
	}

	render_filters() {
		const root = $(this.wrapper);
		const raisers = root.find(".rp-raised-by");
		if (raisers.children().length <= 1) {
			const seen = new Map();
			this.requests.forEach((r) => seen.set(r.owner, r.raised_by_name || r.owner));
			raisers.append(
				[...seen.entries()]
					.sort((a, b) => a[1].localeCompare(b[1]))
					.map(([email, name]) => `<option value="${rp_esc(email)}">${rp_esc(name)}</option>`)
					.join("")
			);
		}
		const assignees = root.find(".rp-assignee");
		if (assignees.children().length <= 1) {
			const names = [...new Set(this.requests.flatMap((r) => r.assignees || []))].sort();
			assignees.append(names.map((n) => `<option value="${rp_esc(n)}">${rp_esc(n)}</option>`).join(""));
		}
	}

	render() {
		this.render_filters();
		const rows = this.visible();
		const open = this.requests.filter(
			(r) => !["Completed", "Rejected", "Withdrawn", "Closed"].includes(r.workflow_state)
		).length;

		$(this.wrapper)
			.find(".rp-count")
			.html(
				`<span><b>${this.requests.length}</b> raised · <b>${open}</b> still open</span>`
			);

		if (!rows.length) {
			return this.stage().html(
				rp_blank(
					this.requests.length ? "Nothing here" : "You have not raised anything yet",
					this.requests.length
						? "Change the filter to see your other requests."
						: "Ask for a fix, a feature or a change and it goes to the dev team for a decision. You will see its progress here."
				)
			);
		}

		this.stage().html(`<div class="rp-list">${rows.map((r) => rp_card(r)).join("")}</div>`);
	}

	open_form() {
		const opts = (list) =>
			list.map((v) => `<option value="${rp_esc(v)}">${rp_esc(v)}</option>`).join("");
		$(this.wrapper).find(".rp-sheet").prop("hidden", false).html(`
			<div class="rp-scrim"></div>
			<form class="rp-form" role="dialog" aria-label="Raise a request">
				<div class="rp-form-hd">
					<h3>Raise a request</h3>
					<button class="dpx-bb-ico rp-close" type="button" aria-label="Close">${rp_ico("x")}</button>
				</div>
				<label>What do you need?
					<input class="dpx-bb-field" name="title" required maxlength="140"
						placeholder="Add a supervisor column to the warehouse list"></label>
				<div class="rp-two">
					<label>Kind<select class="dpx-bb-field" name="request_type" required>${opts(
						this.types
					)}</select></label>
					<label>Module<select class="dpx-bb-field" name="product_area">
						<option value="">Not sure</option>${opts(this.areas)}</select></label>
				</div>
				<div class="rp-two">
					<label>Raised for
						${upande_dev_tools.user_link_html({
							name: "raised_by_employee",
							source_key: "rp-employees",
							placeholder: "Me",
						})}</label>
					<label>Who would you like on it?
						${upande_dev_tools.user_link_html({
							name: "requested_assignee",
							placeholder: "No preference",
						})}</label>
				</div>
				<label>Tags <span class="rp-required">*</span>
					${upande_dev_tools.tag_picker_html({ name: "tags", tags: this.work_tags || [] })}</label>
				<label>Anything else we should know?
					<textarea class="dpx-bb-field" name="description" rows="4"
						placeholder="What you are trying to do, and what happens instead."></textarea></label>
				<label>Attach something (optional)
					<input class="dpx-bb-field" name="attachment" type="file"></label>
				<div class="rp-form-ft">
					<button class="dpx-bb-btn rp-close" type="button">Cancel</button>
					<button class="dpx-bb-btn primary" type="submit">Send it</button>
				</div>
			</form>
		`);
		$(this.wrapper).find('[name="title"]').trigger("focus");
	}

	close_form() {
		$(this.wrapper).find(".rp-sheet").prop("hidden", true).empty();
	}

	submit() {
		const form = $(this.wrapper).find(".rp-form");
		const fd = new FormData(form[0]);
		const file = fd.get("attachment");
		const data = Object.fromEntries(fd.entries());
		if (!data.title.trim()) return;
		if (!data.tags) {
			upande_dev_tools.toast(__("Pick at least one tag."), "orange");
			return;
		}

		form.find("button,input,select,textarea").prop("disabled", true);
		frappe
			.xcall("upande_dev_tools.api.requests.create_request", {
				title: data.title.trim(),
				request_type: data.request_type,
				product_area: data.product_area || null,
				description: data.description || null,
				raised_by_employee: data.raised_by_employee || null,
				requested_assignee: data.requested_assignee || null,
				tags: (data.tags || "").split(",").map((t) => t.trim()).filter(Boolean),
				source: "Web Portal",
			})
			.then((created) => {
				if (file && file.size) return rp_upload(file, "Request", created.name);
			})
			.then(() => {
				this.close_form();
				upande_dev_tools.toast(__("Sent. The dev team will pick it up."), "green");
				this.load();
			})
			.catch((e) => {
				form.find("button,input,select,textarea").prop("disabled", false);
				upande_dev_tools.toast(String((e && e.message) || e) || __("That did not send."), "red");
			});
	}

	act(name, method, label) {
		if (!name) {
			console.error("requests-portal: act() called with no request name", method);
			return;
		}
		frappe
			.xcall(`upande_dev_tools.api.requests.${method}`, { name })
			.then(() => {
				upande_dev_tools.toast(label, "green");
				this.load();
			})
			.catch((e) => {
				console.error(`requests-portal: ${method} failed for ${name}`, e);
				upande_dev_tools.toast(String((e && e.message) || e) || __("That did not go through."), "red");
			});
	}
};

const RP_WITHDRAWABLE = ["Under Review", "Approved", "Deferred", "Scheduled", "In Progress"];

function rp_card(r) {
	const [tone, label] = RP_STAGE[r.workflow_state || ""] || ["st-triage", r.workflow_state];
	const raised = String(r.creation || "").slice(0, 10);
	const can_withdraw = RP_WITHDRAWABLE.includes(r.workflow_state);
	const can_confirm = r.workflow_state === "Completed";
	return `
		<div class="rp-card" data-name="${rp_esc(r.name)}">
			<a href="/app/request/${encodeURIComponent(r.name)}" style="display:block">
				<div class="rp-top">
					<span class="t">${rp_esc(r.title)}</span>
					<span class="dpx-bb-chip ${tone}">${rp_esc(label)}</span>
				</div>
				<div class="rp-meta">
					<span class="dpx-bb-src">${rp_esc(r.request_type || "REQ")}</span>
					${r.priority ? `<span>${rp_esc(r.priority)}</span>` : ""}
					<span class="id">${rp_esc(r.name)}</span>
					<span class="when">raised ${rp_esc(raised)}</span>
					${r.linked_task ? `<span class="built">being built</span>` : ""}
				</div>
			</a>
			${
				can_withdraw || can_confirm
					? `<div class="rp-card-act">
						${can_withdraw ? `<button type="button" class="dpx-bb-btn rp-withdraw">Withdraw</button>` : ""}
						${can_confirm ? `<button type="button" class="dpx-bb-btn primary rp-confirm-done">Confirm complete</button>` : ""}
					</div>`
					: ""
			}
		</div>`;
}

function rp_upload(file, doctype, docname) {
	const fd = new FormData();
	fd.append("file", file);
	fd.append("doctype", doctype);
	fd.append("docname", docname);
	fd.append("is_private", "1");
	return fetch("/api/method/upload_file", {
		method: "POST",
		headers: { "X-Frappe-CSRF-Token": frappe.csrf_token },
		body: fd,
	});
}

function rp_blank(heading, body) {
	return `<div class="dpx-card"><div class="dpx-bb-blank">
		<h3>${rp_esc(heading)}</h3><p>${rp_esc(body)}</p></div></div>`;
}

const RP_ICONS = {
	inbox: '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
	refresh:
		'<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
	x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
};

function rp_ico(name, size) {
	const s = size || 15;
	return `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="currentColor"
		stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${
			RP_ICONS[name] || ""
		}</svg>`;
}

function rp_esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}
