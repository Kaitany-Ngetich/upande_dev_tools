window.upande_dev_tools = window.upande_dev_tools || {};

const MB_STATUSES = [
	"Open",
	"Working",
	"Pending Review",
	"Overdue",
	"Template",
	"Completed",
	"Cancelled",
];

upande_dev_tools.MyBacklog = class MyBacklog {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.tasks = [];
		this.meetings = [];
		this.render_shell();
		this.load();
	}

	load() {
		const icon = $(this.wrapper).find(".mb-reload").addClass("spin");
		if (!this.tasks.length) this.skeleton();
		frappe
			.xcall("upande_dev_tools.api.requests.get_my_backlog")
			.then((data) => {
				this.tasks = (data && data.tasks) || [];
				this.meetings = (data && data.meetings) || [];
				this.stage().removeAttr("aria-busy");
				this.render();
				icon.removeClass("spin");
			})
			.catch((e) => {
				icon.removeClass("spin");
				this.stage().html(
					mb_blank(
						"Could not load your backlog",
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
								<span class="dpx-bb-mark">${mb_ico("list", 14)}</span>
								<h2>My Backlog</h2>
							</div>
							<div class="dpx-bb-tb-sub">Everything open, nearest deadline first</div>
						</div>
						<div class="dpx-bb-tb-act">
							<button class="dpx-bb-ico mb-reload" type="button" title="Refresh">${mb_ico("refresh")}</button>
						</div>
					</div>
					<div class="dpx-bb-tb-cmd">
						<span class="mb-count"></span>
						<span class="dpx-bb-hint"><span class="dpx-bb-kbd">r</span><span>refresh</span></span>
					</div>
				</div>
				<div class="md-alerts"></div>
				<div class="bb-stage"></div>
			</div>
		`);

		const root = $(this.wrapper);
		root.on("click", ".mb-reload", () => this.load());
		root.on("change", ".mb-status", (e) => this.set_status($(e.currentTarget)));
		if (upande_dev_tools.attach_preview) upande_dev_tools.attach_preview(root[0]);
		document.addEventListener("keydown", (e) => {
			if (e.key !== "r" || /^(INPUT|SELECT|TEXTAREA)$/.test((e.target || {}).tagName || ""))
				return;
			this.load();
		});
	}

	skeleton() {
		this.stage()
			.attr("aria-busy", "true")
			.html(
				`<div class="dpx-skel" aria-hidden="true"><div class="dpx-card sk-plain">${[
					1, 2, 3, 4, 5,
				]
					.map(
						() => `<div class="sk-line"><i class="sk" style="width:52%"></i>
							<i class="sk w10"></i><i class="sk chip sm right"></i></div>`
					)
					.join("")}</div></div>`
			);
	}

	render() {
		const today = frappe.datetime.get_today();
		const overdue = this.tasks.filter((t) => t.exp_end_date && t.exp_end_date < today);
		const open_today = this.tasks.filter((t) => t.status !== "Completed").length;

		$(this.wrapper)
			.find(".mb-count")
			.html(
				`<b>${open_today}</b> open<span class="sep">·</span>` +
					`<b>${overdue.length}</b> overdue<span class="sep">·</span>` +
					`<b>${this.meetings.length}</b> meeting${
						this.meetings.length === 1 ? "" : "s"
					}`
			);

		$(this.wrapper)
			.find(".md-alerts")
			.html(
				overdue.length
					? `<a class="pm-alert bad" href="/backlog-board"><span class="dot"></span>
					<span class="txt">${overdue.length} of your task${
							overdue.length === 1 ? " is" : "s are"
					  } past due</span><span class="cta">See them</span></a>`
					: ""
			);

		if (!this.tasks.length) {
			return this.stage().html(
				mb_blank(
					"Nothing on your backlog",
					"Pick up work from the backlog board when you're ready."
				)
			);
		}

		this.stage().html(
			`<div class="dpx-card"><div class="dpx-card-body" style="padding:4px 0 6px">
				${this.tasks.map((t) => mb_task(t, today)).join("")}
			</div></div>
			${
				this.meetings.length
					? `<div class="dpx-card" style="margin-top:12px">
						<div class="dpx-card-hd"><div class="ttl">Schedule</div></div>
						<div class="dpx-card-body" style="padding:4px 0 6px">
							${this.meetings.map((m) => mb_meeting(m)).join("")}
						</div>
					</div>`
					: ""
			}`
		);
	}

	set_status(select) {
		const row = select.closest("[data-name]");
		const name = row.data("name");
		const task = this.tasks.find((t) => t.name === name);
		if (!task) return;

		const status = select.val();
		const before = task.status;
		task.status = status;
		select.prop("disabled", true);

		frappe
			.xcall("upande_dev_tools.api.requests.update_task_status", { name, status })
			.then(() => {
				upande_dev_tools.toast(__("{0} is now {1}", [task.subject, status]), "green");
				this.render();
			})
			.catch(() => {
				task.status = before;
				select.val(before).prop("disabled", false);
				upande_dev_tools.toast(__("Could not update that status."), "red");
			});
	}
};

function mb_task(t, today) {
	const overdue = t.exp_end_date && t.exp_end_date < today && t.status !== "Completed";
	return `
		<div class="md-task" data-name="${mb_esc(t.name)}" data-id="Task:${mb_esc(t.name)}">
			<select class="dpx-bb-field mb-status" style="width:132px">
				${MB_STATUSES.map(
					(s) =>
						`<option value="${mb_esc(s)}"${s === t.status ? " selected" : ""}>${mb_esc(
							s
						)}</option>`
				).join("")}
			</select>
			<a class="t" href="/app/task/${encodeURIComponent(t.name)}">${mb_esc(t.subject)}</a>
			${
				t.exp_end_date
					? `<span class="dpx-bb-chip${overdue ? " st-blocked" : ""}">${mb_esc(
							t.exp_end_date
					  )}</span>`
					: ""
			}
			${
				t.priority && t.priority !== "Low"
					? `<span class="dpx-bb-chip pr-${t.priority.toLowerCase()}">${mb_esc(
							t.priority
					  )}</span>`
					: ""
			}
		</div>`;
}

function mb_meeting(m) {
	const at = new Date(String(m.starts_on).replace(" ", "T"));
	const hhmm = isNaN(at)
		? ""
		: at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
	return `
		<div class="md-meet">
			<span class="at">${mb_esc(hhmm)}</span>
			<span class="body"><span class="t">${mb_esc(m.subject)}</span></span>
			${
				m.google_meet_link
					? `<a class="md-join" href="${mb_esc(
							m.google_meet_link
					  )}" target="_blank" rel="noopener">Join</a>`
					: ""
			}
		</div>`;
}

function mb_blank(heading, body) {
	return `<div class="dpx-card"><div class="dpx-bb-blank">
		<h3>${mb_esc(heading)}</h3><p>${mb_esc(body)}</p></div></div>`;
}

const MB_ICONS = {
	list: '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
	refresh:
		'<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
};

function mb_ico(name, size) {
	const s = size || 15;
	return `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="currentColor"
		stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${
			MB_ICONS[name] || ""
		}</svg>`;
}

function mb_esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}
