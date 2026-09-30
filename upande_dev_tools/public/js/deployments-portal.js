window.upande_dev_tools = window.upande_dev_tools || {};

const DP_STATE = {
	Requested: "st-triage",
	"In Progress": "st-in-progress",
	Deployed: "st-done",
	Failed: "st-blocked",
};
const DP_FILTERS = [
	["all", "All"],
	["pending", "Pending approval"],
	["Requested", "Requested"],
	["In Progress", "In Progress"],
	["Deployed", "Deployed"],
	["Failed", "Failed"],
];

upande_dev_tools.DeploymentsPortal = class DeploymentsPortal {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.is_approver = wrapper.dataset.isApprover === "1";
		this.rows = [];
		this.filter = "all";
		this.render_shell();
		this.load();
	}

	load() {
		const icon = $(this.wrapper).find(".dp-reload").addClass("spin");
		frappe
			.xcall("upande_dev_tools.api.deployments.get_recent_deployments", { limit: 50 })
			.then((data) => {
				this.rows = (data && data.recent) || [];
				this.render();
				icon.removeClass("spin");
			})
			.catch((e) => {
				icon.removeClass("spin");
				this.stage().html(dp_blank("Could not load deployments", String((e && e.message) || e)));
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
								<span class="dpx-bb-mark">${dp_ico("upload-cloud", 14)}</span>
								<h2>Deployments</h2>
							</div>
							<div class="dpx-bb-tb-sub">Everything raised, and anything waiting on a peak-hours approval</div>
						</div>
						<div class="dpx-bb-tb-act">
							<button class="dpx-bb-ico dp-reload" type="button" title="Refresh">${dp_ico("refresh")}</button>
						</div>
					</div>
					<div class="dpx-bb-tb-cmd">
						<div class="dpx-bb-grp">
							<div class="dpx-bb-views dp-filter">
								${DP_FILTERS.map(([key, label]) => `<button data-filter="${key}">${dp_esc(label)}</button>`).join("")}
							</div>
						</div>
						<span class="dp-count dpx-bb-hint"></span>
					</div>
				</div>
				<div class="bb-stage"></div>
			</div>
		`);

		const root = $(this.wrapper);
		root.find('.dp-filter button[data-filter="all"]').addClass("on");
		root.on("click", ".dp-reload", () => this.load());
		root.on("click", ".dp-filter button", (e) => {
			this.filter = $(e.currentTarget).data("filter");
			root.find(".dp-filter button").removeClass("on");
			$(e.currentTarget).addClass("on");
			this.render();
		});
		root.on("click", ".dp-approve, .dp-reject", (e) => {
			const btn = $(e.currentTarget);
			const name = btn.closest("[data-name]").data("name");
			const approve = btn.hasClass("dp-approve");
			if (!approve && !confirm(__("Reject this deployment? It will stay held until someone approves it later."))) {
				return;
			}
			btn.closest("tr").find("button").prop("disabled", true);
			frappe
				.xcall(
					approve
						? "upande_dev_tools.api.deployments.approve_deployment_request"
						: "upande_dev_tools.api.deployments.reject_deployment_request",
					{ name }
				)
				.then(() => {
					upande_dev_tools.toast(approve ? __("Approved.") : __("Rejected."), "green");
					this.load();
				})
				.catch((e2) => {
					upande_dev_tools.toast((e2 && e2.message) || __("That did not go through."), "red");
					btn.closest("tr").find("button").prop("disabled", false);
				});
		});
		document.addEventListener("keydown", (e) => {
			if (e.key !== "r" || /^(INPUT|SELECT|TEXTAREA)$/.test((e.target || {}).tagName || "")) return;
			this.load();
		});
	}

	render() {
		const pending = this.rows.filter((r) => r.requires_approval && r.approval_status === "Pending");
		let visible = this.rows;
		if (this.filter === "pending") visible = pending;
		else if (this.filter !== "all") visible = this.rows.filter((r) => r.workflow_state === this.filter);

		$(this.wrapper)
			.find(".dp-count")
			.html(
				`<b>${this.rows.length}</b> total<span class="sep">·</span>` +
					`<b>${pending.length}</b> pending approval`
			);

		if (!this.rows.length) {
			return this.stage().html(dp_blank("No deployment requests yet", "Nothing has been raised."));
		}
		if (!visible.length) {
			return this.stage().html(dp_blank("No matches", "Nothing fits that filter."));
		}

		this.stage().html(
			`<div class="dpx-card"><div class="dpx-card-body dpx-bb-listwrap" style="padding:0 0 4px">
				<table class="dpx-bb-table">
					<colgroup><col><col style="width:150px"><col style="width:110px"><col style="width:120px"><col style="width:104px"><col style="width:150px">${
						this.is_approver ? "<col style=\"width:150px\">" : ""
					}</colgroup>
					<thead><tr><th>App</th><th>Instance</th><th>Branch</th><th>Requested by</th><th>Raised</th><th>State</th>${
						this.is_approver ? "<th></th>" : ""
					}</tr></thead>
					<tbody>${visible.map((r) => dp_row(r, this.is_approver)).join("")}</tbody>
				</table>
			</div></div>`
		);
	}
};

function dp_row(r, is_approver) {
	const pending = r.requires_approval && r.approval_status === "Pending";
	const chip = pending
		? `<span class="dpx-bb-chip st-blocked" title="Raised during peak hours - waiting on a Projects Manager before it can start">Pending approval</span>`
		: `<span class="dpx-bb-chip ${DP_STATE[r.workflow_state] || "st-triage"}">${dp_esc(r.workflow_state)}</span>`;
	return `
		<tr class="dpx-bb-row" data-name="${dp_esc(r.name)}">
			<td><a href="/app/deployment-request/${encodeURIComponent(r.name)}">${dp_esc(r.app)}</a></td>
			<td>${dp_esc(r.instance)}</td>
			<td>${dp_esc(r.branch || "—")}</td>
			<td>${dp_esc((r.requested_by_user || "").split("@")[0])}</td>
			<td>${dp_esc(String(r.creation || "").slice(0, 10))}</td>
			<td>${chip}</td>
			${
				is_approver
					? `<td>${
							pending
								? `<button class="dpx-bb-btn dp-approve" type="button">Approve</button>
									<button class="dpx-bb-btn dp-reject" type="button">Reject</button>`
								: ""
					  }</td>`
					: ""
			}
		</tr>`;
}

function dp_blank(heading, body) {
	return `<div class="dpx-card"><div class="dpx-bb-blank">
		<h3>${dp_esc(heading)}</h3><p>${dp_esc(body)}</p></div></div>`;
}

const DP_ICONS = {
	"upload-cloud":
		'<path d="M12 13v8"/><path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242"/><path d="m8 17 4-4 4 4"/>',
	refresh:
		'<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
};

function dp_ico(name, size) {
	const s = size || 15;
	return `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="currentColor"
		stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${
			DP_ICONS[name] || ""
		}</svg>`;
}

function dp_esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}
