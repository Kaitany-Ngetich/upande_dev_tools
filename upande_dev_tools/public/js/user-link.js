window.upande_dev_tools = window.upande_dev_tools || {};

// A searchable Link-to-User control. Frappe's own Link field is frappe.ui.form.ControlLink,
// which needs frappe.ui.form.make_control - not in the web bundle these portal pages load
// (same reason modal.js and tag-picker.js exist), so the combobox is built by hand here.
//
// Every control shares one cached user list rather than embedding its own copy: the Review
// Queue renders an assignee picker per row, and inlining 440 people 385 times would be tens
// of megabytes of markup. Document-level delegation for the same reason tag-picker.js uses
// it - these tables and dialogs are torn down and rebuilt wholesale on every render, and a
// single binding here keeps working across all of them.
(function () {
	const MAX_RENDER = 50;
	let users = [];
	let loading = null;
	let search_timer = null;

	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const label_of = (u) => u.full_name || u.name;

	function ensure_users() {
		if (users.length) return Promise.resolve(users);
		if (loading) return loading;
		loading = frappe
			.xcall("upande_dev_tools.api.requests.get_assignable_users")
			.then((rows) => {
				users = rows || [];
				return users;
			})
			.catch(() => []);
		return loading;
	}

	// Pages that already fetch the list for their own filters hand it over so the first
	// keystroke doesn't wait on a round trip.
	upande_dev_tools.seed_users = function (rows) {
		if (rows && rows.length) users = rows;
	};

	upande_dev_tools.user_link_html = function (opts) {
		opts = opts || {};
		const value = opts.value || "";
		const label = opts.label || (value ? lookup_label(value) : "");
		return `<span class="udt-ul" data-udt-ul>
			<input type="hidden" name="${esc(opts.name || "assign_to")}" value="${esc(value)}"
				class="udt-ul-value${opts.value_class ? " " + esc(opts.value_class) : ""}">
			<input type="text" class="dpx-bb-field udt-ul-search" value="${esc(label)}"
				placeholder="${esc(opts.placeholder || __("Search people"))}"
				role="combobox" aria-expanded="false" aria-autocomplete="list" aria-haspopup="listbox"
				autocomplete="off" spellcheck="false"${opts.title ? ` title="${esc(opts.title)}"` : ""}>
			<button type="button" class="udt-ul-x" tabindex="-1" aria-label="${esc(__("Clear"))}"
				${value ? "" : "hidden"}>
				<svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor"
					stroke-width="2.2" stroke-linecap="round" aria-hidden="true">
					<path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
			</button>
			<div class="udt-ul-menu" role="listbox" hidden></div>
		</span>`;
	};

	function lookup_label(email) {
		const hit = users.find((u) => u.name === email);
		return hit ? label_of(hit) : email;
	}

	function match(list, txt) {
		if (!txt) return list;
		// Every word has to appear somewhere in the name or the email, so "mark up" finds
		// "Mark Judah <judah@upande.com>" and word order never matters.
		const words = txt.toLowerCase().split(/\s+/).filter(Boolean);
		return list.filter((u) => {
			const hay = `${u.full_name || ""} ${u.name}`.toLowerCase();
			return words.every((w) => hay.includes(w));
		});
	}

	function render_menu(box, txt) {
		const menu = box.querySelector(".udt-ul-menu");
		const chosen = box.querySelector(".udt-ul-value").value;
		const hits = match(users, txt);

		if (!users.length) {
			menu.innerHTML = `<div class="udt-ul-note">${esc(__("Loading people…"))}</div>`;
			return;
		}
		if (!hits.length) {
			menu.innerHTML = `<div class="udt-ul-note">${esc(__("No one matches “{0}”.", [txt]))}</div>`;
			return;
		}

		const shown = hits.slice(0, MAX_RENDER);
		menu.innerHTML =
			shown
				.map(
					(u, i) =>
						`<div class="udt-ul-opt${u.name === chosen ? " on" : ""}${i === 0 ? " active" : ""}"
							role="option" aria-selected="${u.name === chosen}" data-email="${esc(u.name)}">
							<span class="nm">${esc(label_of(u))}</span>
							<span class="em">${esc(u.name)}</span>
						</div>`
				)
				.join("") +
			(hits.length > shown.length
				? `<div class="udt-ul-note">${esc(
						__("Showing {0} of {1} — keep typing to narrow.", [shown.length, hits.length])
				  )}</div>`
				: "");
	}

	function open(box) {
		const menu = box.querySelector(".udt-ul-menu");
		const search = box.querySelector(".udt-ul-search");
		close_all(box);
		box.classList.add("open");
		menu.hidden = false;
		search.setAttribute("aria-expanded", "true");
		render_menu(box, current_query(box));
		ensure_users().then(() => {
			if (box.classList.contains("open")) render_menu(box, current_query(box));
		});
	}

	function current_query(box) {
		const search = box.querySelector(".udt-ul-search");
		const chosen = box.querySelector(".udt-ul-value").value;
		// A freshly focused control still shows the chosen person's name; treat that as "no
		// query" so the whole list opens rather than the one row that name matches.
		return search.value === lookup_label(chosen) ? "" : search.value;
	}

	function close(box, restore) {
		if (!box) return;
		box.classList.remove("open");
		const menu = box.querySelector(".udt-ul-menu");
		const search = box.querySelector(".udt-ul-search");
		menu.hidden = true;
		menu.innerHTML = "";
		search.setAttribute("aria-expanded", "false");
		if (restore !== false) {
			const chosen = box.querySelector(".udt-ul-value").value;
			search.value = chosen ? lookup_label(chosen) : "";
		}
	}

	function close_all(except) {
		document.querySelectorAll(".udt-ul.open").forEach((b) => {
			if (b !== except) close(b);
		});
	}

	function pick(box, email) {
		const hidden = box.querySelector(".udt-ul-value");
		hidden.value = email || "";
		box.querySelector(".udt-ul-search").value = email ? lookup_label(email) : "";
		box.querySelector(".udt-ul-x").hidden = !email;
		close(box, false);
		// Anything bound to the real field (a form, a row handler) sees a normal change event.
		hidden.dispatchEvent(new Event("change", { bubbles: true }));
	}

	function active_opt(box) {
		return box.querySelector(".udt-ul-opt.active");
	}

	function move(box, step) {
		const opts = [...box.querySelectorAll(".udt-ul-opt")];
		if (!opts.length) return;
		const at = opts.indexOf(active_opt(box));
		const next = opts[Math.min(opts.length - 1, Math.max(0, (at < 0 ? -1 : at) + step))];
		opts.forEach((o) => o.classList.remove("active"));
		next.classList.add("active");
		next.scrollIntoView({ block: "nearest" });
	}

	document.addEventListener("focusin", (e) => {
		const search = e.target.closest && e.target.closest(".udt-ul-search");
		if (search) open(search.closest(".udt-ul"));
		else if (!e.target.closest || !e.target.closest(".udt-ul")) close_all();
	});

	document.addEventListener("input", (e) => {
		const search = e.target.closest && e.target.closest(".udt-ul-search");
		if (!search) return;
		const box = search.closest(".udt-ul");
		if (!box.classList.contains("open")) open(box);
		// Typing over a chosen person clears the choice until a new one is picked, so a
		// half-typed name can never be submitted as if it were still the old selection.
		const hidden = box.querySelector(".udt-ul-value");
		if (hidden.value && search.value !== lookup_label(hidden.value)) {
			hidden.value = "";
			box.querySelector(".udt-ul-x").hidden = true;
			hidden.dispatchEvent(new Event("change", { bubbles: true }));
		}
		clearTimeout(search_timer);
		const txt = search.value;
		search_timer = setTimeout(() => render_menu(box, txt), 60);
	});

	document.addEventListener("keydown", (e) => {
		const search = e.target.closest && e.target.closest(".udt-ul-search");
		if (!search) return;
		const box = search.closest(".udt-ul");
		if (e.key === "ArrowDown" || e.key === "ArrowUp") {
			e.preventDefault();
			if (!box.classList.contains("open")) return open(box);
			move(box, e.key === "ArrowDown" ? 1 : -1);
		} else if (e.key === "Enter") {
			const opt = box.classList.contains("open") && active_opt(box);
			if (opt) {
				// Only swallow Enter when it is actually choosing someone - otherwise it
				// still submits the dialog the control sits in.
				e.preventDefault();
				pick(box, opt.dataset.email);
			}
		} else if (e.key === "Escape") {
			if (box.classList.contains("open")) {
				// stopImmediatePropagation, not stopPropagation: modal.js binds its own Escape
				// handler to document too, and stopPropagation only blocks listeners on nodes
				// ABOVE this one - the dialog would still close out from under the menu. This
				// file is loaded at page load and the dialog binds on open, so this listener
				// is always registered first and therefore always wins.
				e.stopImmediatePropagation();
				close(box);
			}
		} else if (e.key === "Tab") {
			close(box);
		}
	});

	document.addEventListener("mousedown", (e) => {
		const opt = e.target.closest && e.target.closest(".udt-ul-opt");
		if (opt) {
			// mousedown, not click: the input's blur would tear the menu down first.
			e.preventDefault();
			pick(opt.closest(".udt-ul"), opt.dataset.email);
			return;
		}
		const clear = e.target.closest && e.target.closest(".udt-ul-x");
		if (clear) {
			e.preventDefault();
			pick(clear.closest(".udt-ul"), "");
			return;
		}
		if (!e.target.closest || !e.target.closest(".udt-ul")) close_all();
	});
})();
