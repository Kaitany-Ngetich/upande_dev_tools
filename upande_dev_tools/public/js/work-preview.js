window.upande_dev_tools = window.upande_dev_tools || {};

// Portal scripts share one global scope, so everything here lives in its own.
(function () {
	// A hover preview shared by every view. Anything carrying data-id="Doctype:NAME"
	// gets one, so the board, the list, the timeline and the sheet all behave the
	// same without each knowing about it.
	const HOLD = 420;
	const GAP = 14;

	upande_dev_tools.attach_preview = function (root) {
		if (root.__preview) return;
		root.__preview = true;

		const cache = new Map();
		let card = null;
		let timer = null;
		let current = null;

		function close() {
			clearTimeout(timer);
			current = null;
			if (!card) return;
			card.classList.remove("in");
			const going = card;
			card = null;
			setTimeout(() => going.remove(), 130);
		}

		function place(el) {
			const box = el.getBoundingClientRect();
			const size = card.getBoundingClientRect();
			let left = Math.min(box.left, window.innerWidth - size.width - 12);
			let top = box.bottom + GAP;
			if (top + size.height > window.innerHeight - 12)
				top = Math.max(12, box.top - size.height - GAP);
			card.style.left = `${Math.max(12, left)}px`;
			card.style.top = `${top}px`;
		}

		function show(el, id) {
			const [doctype, name] = id.split(/:(.+)/);
			if (!doctype || !name) return;

			card = document.createElement("div");
			card.className = "dpx-preview";
			card.setAttribute("role", "tooltip");
			card.innerHTML = '<div class="pv-load"><i></i><i></i><i></i></div>';
			document.body.appendChild(card);
			place(el);

			const paint = (data) => {
				if (current !== id || !card) return;
				card.innerHTML = render(data);
				const img = card.querySelector("img");
				if (img) img.addEventListener("load", () => card && place(el), { once: true });
				place(el);
				requestAnimationFrame(() => card && card.classList.add("in"));
			};

			if (cache.has(id)) return paint(cache.get(id));
			requestAnimationFrame(() => card && card.classList.add("in"));

			frappe
				.xcall("upande_dev_tools.api.board.get_preview", { doctype, name })
				.then((data) => {
					cache.set(id, data);
					paint(data);
				})
				.catch(() => close());
		}

		function render(d) {
			const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
			const slug = (v) =>
				String(v || "")
					.toLowerCase()
					.replace(/\s+/g, "-");
			return `
			${d.image ? `<div class="pv-shot"><img src="${esc(d.image)}" alt="" loading="lazy"></div>` : ""}
			<div class="pv-body">
				<div class="pv-top">
					<span class="dpx-bb-src">${esc(SOURCES[d.doctype] || d.doctype)}</span>
					<span class="dpx-bb-chip st-${slug(STATES[d.status] || d.status)}">${esc(d.status)}</span>
					${d.priority ? `<span class="dpx-bb-chip pr-${slug(d.priority)}">${esc(d.priority)}</span>` : ""}
				</div>
				<div class="pv-title">${esc(d.title)}</div>
				${d.summary ? `<p class="pv-sum">${esc(d.summary)}</p>` : ""}
				<div class="pv-meta">
					${d.module ? `<span>${esc(d.module)}</span>` : ""}
					${d.project ? `<span>${esc(d.project)}</span>` : ""}
					${
						d.assignees.length
							? `<span>${esc(d.assignees.join(", "))}</span>`
							: d.by
							? `<span>from ${esc(d.by)}</span>`
							: ""
					}
					<span class="pv-id">${esc(d.name)}</span>
				</div>
			</div>`;
		}

		root.addEventListener("pointerover", (e) => {
			if (e.pointerType === "touch") return;
			const el = e.target.closest("[data-id]");
			const id = el && el.getAttribute("data-id");
			if (!id || id === current) return;
			close();
			current = id;
			timer = setTimeout(() => show(el, id), HOLD);
		});

		root.addEventListener("pointerout", (e) => {
			const el = e.target.closest("[data-id]");
			if (el && el.contains(e.relatedTarget)) return;
			close();
		});
		root.addEventListener("pointerdown", close);
		window.addEventListener("scroll", close, true);
		document.addEventListener("keydown", (e) => e.key === "Escape" && close());
	};

	const SOURCES = { Task: "TASK", Issue: "ISSUE", Request: "REQ" };
	const STATES = {
		Open: "todo",
		Working: "in-progress",
		Replied: "in-progress",
		"Pending Review": "in-review",
		"On Hold": "blocked",
		Completed: "done",
		Resolved: "done",
		Closed: "done",
		"Under Review": "triage",
	};
})();
