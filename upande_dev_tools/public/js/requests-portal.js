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
};

upande_dev_tools.RequestsPortal = class RequestsPortal {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.requests = [];
		this.types = [];
		this.areas = [];
		this.filter = "";
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
		])
			.then(([requests, types, areas]) => {
				this.requests = requests || [];
				this.types = (types || []).map((t) => t.name);
				this.areas = areas || [];
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
		root.on("click", ".rp-new", () => this.open_form());
		root.on("click", ".rp-close, .rp-scrim", () => this.close_form());
		root.on("submit", ".rp-form", (e) => {
			e.preventDefault();
			this.submit();
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
		if (this.filter === "open")
			return this.requests.filter(
				(r) => !["Completed", "Rejected"].includes(r.workflow_state)
			);
		if (this.filter === "done")
			return this.requests.filter((r) =>
				["Completed", "Rejected"].includes(r.workflow_state)
			);
		return this.requests;
	}

	render() {
		const rows = this.visible();
		const open = this.requests.filter(
			(r) => !["Completed", "Rejected"].includes(r.workflow_state)
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
				<label>Anything else we should know?
					<textarea class="dpx-bb-field" name="description" rows="4"
						placeholder="What you are trying to do, and what happens instead."></textarea></label>
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
		const data = Object.fromEntries(new FormData(form[0]).entries());
		if (!data.title.trim()) return;

		form.find("button,input,select,textarea").prop("disabled", true);
		frappe
			.xcall("upande_dev_tools.api.requests.create_request", {
				title: data.title.trim(),
				request_type: data.request_type,
				product_area: data.product_area || null,
				description: data.description || null,
				source: "Web Portal",
			})
			.then(() => {
				this.close_form();
				frappe.show_alert({
					message: __("Sent. The dev team will pick it up."),
					indicator: "green",
				});
				this.load();
			})
			.catch((e) => {
				form.find("button,input,select,textarea").prop("disabled", false);
				frappe.show_alert({
					message: String((e && e.message) || e) || __("That did not send."),
					indicator: "red",
				});
			});
	}
};

function rp_card(r) {
	const [tone, label] = RP_STAGE[r.workflow_state || ""] || ["st-triage", r.workflow_state];
	const raised = String(r.creation || "").slice(0, 10);
	return `
		<a class="rp-card" href="/app/request/${encodeURIComponent(r.name)}">
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
		</a>`;
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
