window.upande_dev_tools = window.upande_dev_tools || {};

// A plain HTML form in an overlay, reusing the .rp-sheet/.rp-form styling that already ships
// with this app - frappe.prompt's Dialog needs frappe.ui.form.make_control to render its
// fields, and that isn't loaded on any of these portal pages at all (only the full desk
// bundle has it), so every field-collecting dialog on any portal page is built this way
// instead. Shared here (not just backlog-board.js's own copy) so any page - Dev Dashboard's
// "New deployment request" included - can pop the same kind of dialog without depending on
// backlog-board.js being loaded too.
(function () {
	function modal_esc(value) {
		return frappe.utils.escape_html(value == null ? "" : String(value));
	}

	function modal_close_icon() {
		return `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
			stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
			<path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>`;
	}

	upande_dev_tools.open_modal = function (title, fields, onSubmit, submitLabel) {
		const esc = modal_esc;
		const field_html = fields
			.map((f) => {
				const id = `bb-modal-${f.name}`;
				let input;
				if (f.type === "select") {
					input = `<select class="dpx-bb-field" id="${id}" name="${f.name}">${(f.options || [])
						.map(
							([v, l]) =>
								`<option value="${esc(v)}"${v === f.value ? " selected" : ""}>${esc(l)}</option>`
						)
						.join("")}</select>`;
				} else if (f.type === "textarea") {
					input = `<textarea class="dpx-bb-field" id="${id}" name="${f.name}" rows="3">${esc(
						f.value || ""
					)}</textarea>`;
				} else if (f.type === "tagpicker") {
					input = upande_dev_tools.tag_picker_html({
						name: f.name,
						tags: f.tags || [],
						selected: f.selected || [],
					});
				} else {
					const listAttr = f.datalist ? ` list="${id}-list"` : "";
					const datalist = f.datalist
						? `<datalist id="${id}-list">${f.datalist.map((v) => `<option value="${esc(v)}">`).join("")}</datalist>`
						: "";
					input = `<input class="dpx-bb-field" id="${id}" name="${f.name}" type="${f.type || "text"}"
						value="${esc(f.value || "")}"${f.required ? " required" : ""}${listAttr}
						${f.placeholder ? `placeholder="${esc(f.placeholder)}"` : ""}>${datalist}`;
				}
				return `<label for="${id}">${esc(f.label)}${input}</label>`;
			})
			.join("");

		const overlay = document.createElement("div");
		overlay.className = "rp-sheet";
		overlay.innerHTML = `
			<div class="rp-scrim"></div>
			<form class="rp-form" role="dialog" aria-label="${esc(title)}">
				<div class="rp-form-hd"><h3>${esc(title)}</h3>
					<button type="button" class="dpx-bb-ico bb-modal-close" aria-label="Close">${modal_close_icon()}</button></div>
				${field_html}
				<div class="rp-form-ft">
					<button type="button" class="dpx-bb-btn bb-modal-close">${__("Cancel")}</button>
					<button type="submit" class="dpx-bb-btn primary">${esc(submitLabel || __("Save"))}</button>
				</div>
			</form>`;
		// Mounted inside .dpx, not document.body: every .rp-sheet/.rp-form/.dpx-bb-field style is
		// deliberately scoped under .dpx (see dev-portal.css) so this portal's CSS never leaks
		// onto the rest of the site - appending straight to body would render completely
		// unstyled, since .dpx is fixed/full-viewport and doesn't use transform, so a
		// position:fixed child still positions against the real viewport either way.
		(document.querySelector(".dpx") || document.body).appendChild(overlay);

		const close = () => {
			overlay.remove();
			document.removeEventListener("keydown", on_key);
		};
		function on_key(e) {
			if (e.key === "Escape") close();
		}
		document.addEventListener("keydown", on_key);
		overlay.querySelectorAll(".bb-modal-close").forEach((b) => b.addEventListener("click", close));
		overlay.querySelector(".rp-scrim").addEventListener("click", close);
		overlay.querySelector("form").addEventListener("submit", (e) => {
			e.preventDefault();
			// A hidden input's own `required` attribute is a no-op in every browser (an element
			// that isn't rendered is exempt from constraint validation) - so a tagpicker's
			// required-ness has to be checked by hand here instead.
			for (const f of fields) {
				if (f.type !== "tagpicker" || !f.required) continue;
				const hidden = overlay.querySelector(`input[name="${f.name}"]`);
				if (!hidden || !hidden.value) {
					upande_dev_tools.toast(__("Pick at least one {0}.", [f.label]), "orange");
					return;
				}
			}
			const data = Object.fromEntries(new FormData(e.target).entries());
			close();
			onSubmit(data);
		});
		const first = overlay.querySelector("input,select,textarea");
		if (first) first.focus();
	};
})();
