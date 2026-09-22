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
//
// `multiple: true` turns it into a multi-select: the chosen people show as removable chips
// and the hidden input carries a comma-separated list of emails instead of one. Everything
// downstream - FormData, `.val()` readers, the whitelisted endpoints - therefore sees a
// plain string either way, and a single-value control is just the one-element case.
(function () {
	const MAX_RENDER = 50;
	let users = [];
	let loading = null;
	let search_timer = null;

	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const label_of = (u) => u.full_name || u.name;
	const split = (v) =>
		String(v == null ? "" : v)
			.split(",")
			.map((e) => e.trim())
			.filter(Boolean);

	const is_multi = (box) => box.dataset.multiple === "1";
	const chosen_of = (box) => split(box.querySelector(".udt-ul-value").value);

	// A control can list something other than users - the Requests form's "Raised for" picks
	// an Employee. Sources are registered by name rather than handed to each control, so a
	// table that re-renders its rows hundreds of times never accumulates copies of the list.
	const sources = new Map();
	upande_dev_tools.register_link_source = function (key, rows) {
		sources.set(key, rows || []);
		render_all_chips();
	};
	function list_of(box) {
		const key = box && box.dataset.source;
		return (key && sources.get(key)) || users;
	}

	function ensure_users() {
		if (users.length) return Promise.resolve(users);
		if (loading) return loading;
		loading = frappe
			.xcall("upande_dev_tools.api.requests.get_assignable_users")
			.then((rows) => {
				users = rows || [];
				render_all_chips();
				return users;
			})
			.catch(() => []);
		return loading;
	}

	// Pages that already fetch the list for their own filters hand it over so the first
	// keystroke doesn't wait on a round trip.
	upande_dev_tools.seed_users = function (rows) {
		if (!rows || !rows.length) return;
		users = rows;
		render_all_chips();
	};

	function x_icon(size) {
		return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor"
				stroke-width="2.2" stroke-linecap="round" aria-hidden="true">
				<path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>`;
	}

	function chips_html(emails, list) {
		return emails
			.map(
				(email) => `<span class="udt-ul-chip" data-email="${esc(email)}">
					<span class="nm">${esc(lookup_label(email, list))}</span>
					<button type="button" class="udt-ul-chip-x" tabindex="-1"
						aria-label="${esc(__("Remove {0}", [lookup_label(email, list)]))}">${x_icon(9)}</button>
				</span>`
			)
			.join("");
	}

	// Chips are labelled from the cached user list, which may still be in flight when the
	// markup is built - so they render with the email as a placeholder label and get redrawn
	// once the names arrive (see seed_users/ensure_users below).
	function render_chips(box) {
		const holder = box.querySelector(".udt-ul-chips");
		if (holder) holder.innerHTML = chips_html(chosen_of(box), list_of(box));
	}

	function render_all_chips() {
		document.querySelectorAll(".udt-ul[data-multiple='1']").forEach(render_chips);
	}

	upande_dev_tools.user_link_html = function (opts) {
		opts = opts || {};
		const multiple = !!opts.multiple;
		const list = opts.source_key ? sources.get(opts.source_key) : null;
		const values = multiple ? split(opts.value) : [opts.value || ""].filter(Boolean);
		const value = values.join(",");
		const label = multiple ? "" : opts.label || (value ? lookup_label(value, list) : "");
		return `<span class="udt-ul${multiple ? " udt-ul-multi" : ""}" data-udt-ul${
			multiple ? ' data-multiple="1"' : ""
		}${opts.source_key ? ` data-source="${esc(opts.source_key)}"` : ""}>
			<input type="hidden" name="${esc(opts.name || "assign_to")}" value="${esc(value)}"
				class="udt-ul-value${opts.value_class ? " " + esc(opts.value_class) : ""}">
			${multiple ? `<span class="udt-ul-chips">${chips_html(values, list)}</span>` : ""}
			<input type="text" class="dpx-bb-field udt-ul-search" value="${esc(label)}"
				placeholder="${esc(
					opts.placeholder || (multiple ? __("Search people — pick as many as you need") : __("Search people"))
				)}"
				role="combobox" aria-expanded="false" aria-autocomplete="list" aria-haspopup="listbox"
				${multiple ? 'aria-multiselectable="true" ' : ""}autocomplete="off" spellcheck="false"${
					opts.title ? ` title="${esc(opts.title)}"` : ""
				}>
			<button type="button" class="udt-ul-x" tabindex="-1" aria-label="${esc(
				multiple ? __("Clear all") : __("Clear")
			)}"
				${value ? "" : "hidden"}>${x_icon(11)}</button>
			<div class="udt-ul-menu" role="listbox" hidden></div>
		</span>`;
	};

	function lookup_label(email, list) {
		const hit = (list || users).find((u) => u.name === email);
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
		const chosen = new Set(chosen_of(box));
		const list = list_of(box);
		const hits = match(list, txt);

		if (!list.length) {
			menu.innerHTML = `<div class="udt-ul-note">${esc(__("Loading…"))}</div>`;
			return;
		}
		if (!hits.length) {
			menu.innerHTML = `<div class="udt-ul-note">${esc(__("Nothing matches “{0}”.", [txt]))}</div>`;
			return;
		}

		const shown = hits.slice(0, MAX_RENDER);
		menu.innerHTML =
			shown
				.map(
					(u, i) =>
						`<div class="udt-ul-opt${chosen.has(u.name) ? " on" : ""}${i === 0 ? " active" : ""}"
							role="option" aria-selected="${chosen.has(u.name)}" data-email="${esc(u.name)}">
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
		if (box.dataset.source) return;
		ensure_users().then(() => {
			if (box.classList.contains("open")) render_menu(box, current_query(box));
		});
	}

	function current_query(box) {
		const search = box.querySelector(".udt-ul-search");
		// A multi control shows its picks as chips, so the search box is only ever a query.
		if (is_multi(box)) return search.value;
		const chosen = box.querySelector(".udt-ul-value").value;
		// A freshly focused control still shows the chosen person's name; treat that as "no
		// query" so the whole list opens rather than the one row that name matches.
		return search.value === lookup_label(chosen, list_of(box)) ? "" : search.value;
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
			if (is_multi(box)) {
				search.value = "";
				return;
			}
			const chosen = box.querySelector(".udt-ul-value").value;
			search.value = chosen ? lookup_label(chosen, list_of(box)) : "";
		}
	}

	function close_all(except) {
		document.querySelectorAll(".udt-ul.open").forEach((b) => {
			if (b !== except) close(b);
		});
	}

	function pick(box, email) {
		const hidden = box.querySelector(".udt-ul-value");
		const search = box.querySelector(".udt-ul-search");

		if (is_multi(box)) {
			const chosen = chosen_of(box);
			// A pick toggles: clicking someone already chosen takes them off again, which is
			// what the ✓ on the option is telling you it will do.
			const at = chosen.indexOf(email);
			if (!email) chosen.length = 0;
			else if (at > -1) chosen.splice(at, 1);
			else chosen.push(email);

			hidden.value = chosen.join(",");
			render_chips(box);
			box.querySelector(".udt-ul-x").hidden = !chosen.length;
			// Stay open and clear the query: picking three people should be three clicks,
			// not three rounds of reopening the menu and retyping.
			search.value = "";
			if (box.classList.contains("open")) render_menu(box, "");
			hidden.dispatchEvent(new Event("change", { bubbles: true }));
			return;
		}

		hidden.value = email || "";
		search.value = email ? lookup_label(email, list_of(box)) : "";
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
		// A multi control keeps its picks in chips, so typing there is only ever a query.
		const hidden = box.querySelector(".udt-ul-value");
		if (!is_multi(box) && hidden.value && search.value !== lookup_label(hidden.value, list_of(box))) {
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
		} else if (e.key === "Backspace" && is_multi(box) && !search.value) {
			const chosen = chosen_of(box);
			if (chosen.length) {
				e.preventDefault();
				pick(box, chosen[chosen.length - 1]);
			}
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
		const chip_x = e.target.closest && e.target.closest(".udt-ul-chip-x");
		if (chip_x) {
			e.preventDefault();
			const chip = chip_x.closest(".udt-ul-chip");
			pick(chip.closest(".udt-ul"), chip.dataset.email);
			return;
		}
		const clear = e.target.closest && e.target.closest(".udt-ul-x");
		if (clear) {
			e.preventDefault();
			// "" empties a multi control and clears a single one alike.
			pick(clear.closest(".udt-ul"), "");
			return;
		}
		if (!e.target.closest || !e.target.closest(".udt-ul")) close_all();
	});
})();
