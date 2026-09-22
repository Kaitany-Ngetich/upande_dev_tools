window.upande_dev_tools = window.upande_dev_tools || {};

// A real Frappe Date control (air-datepicker) everywhere this portal asks for a date,
// instead of the browser's native <input type="date"> - which renders a different widget
// in every browser and ignores the site's date format entirely.
//
// frappe.ui.form.make_control is NOT in frappe-web.bundle.js; it lives in
// controls.bundle.js, which each portal page rendering a date field pulls in through
// `context.web_include_js` (see www/*.py). That bundle loads after frappe-web.bundle.js
// and before frappe.ready fires, so mounting from inside frappe.ready is safe. The
// picker's stylesheet is already on every website page - website.bundle.scss ->
// website/index.scss -> common/controls -> common/datepicker - so there is nothing extra
// to load for the CSS.
//
// The control shows the user's date format but writes the system format (yyyy-mm-dd) into
// a hidden input that carries the field's name and classes. FormData and existing
// `.val()` readers therefore keep seeing an ISO date and need no changes - the same shape
// the tagpicker and userlink widgets in this portal already use.
(function () {
	function esc(value) {
		return frappe.utils.escape_html(value == null ? "" : String(value));
	}

	// `cls` lands on the hidden input, not the wrapper: callers select by it to read a value.
	upande_dev_tools.date_field_html = function ({ name, value, cls, placeholder, id } = {}) {
		return `<span class="udt-date" data-udt-date${
			placeholder ? ` data-placeholder="${esc(placeholder)}"` : ""
		}${id ? ` data-input-id="${esc(id)}"` : ""}><input type="hidden"${
			name ? ` name="${esc(name)}"` : ""
		} class="${esc(cls || "")}" value="${esc(value || "")}"></span>`;
	};

	// Without controls.bundle.js there is no control to make, and a lone hidden input would
	// leave the field invisible - so fall back to a native date input, which at least still
	// collects a yyyy-mm-dd value under the same name and class.
	function fall_back(holder, hidden) {
		console.warn(
			"upande_dev_tools: controls.bundle.js is not on this page " +
				'(set context.web_include_js = ["controls.bundle.js"] in its get_context) - ' +
				"falling back to a native date input"
		);
		const native = document.createElement("input");
		native.type = "date";
		native.className = `dpx-bb-field ${(hidden && hidden.className) || ""}`.trim();
		if (hidden) {
			native.name = hidden.name;
			native.value = hidden.value;
			hidden.remove();
		}
		if (holder.dataset.inputId) native.id = holder.dataset.inputId;
		holder.appendChild(native);
	}

	upande_dev_tools.mount_date_fields = function (root) {
		const scope = root || document;
		const can_make_control = !!(frappe.ui && frappe.ui.form && frappe.ui.form.make_control);
		scope.querySelectorAll("[data-udt-date]").forEach((holder) => {
			if (holder.dataset.udtDateMounted) return;
			holder.dataset.udtDateMounted = "1";

			const hidden = holder.querySelector('input[type="hidden"]');
			if (!can_make_control) return fall_back(holder, hidden);
			const control = frappe.ui.form.make_control({
				parent: holder,
				render_input: true,
				only_input: true,
				df: {
					fieldtype: "Date",
					fieldname: (hidden && hidden.name) || "date",
					placeholder: holder.dataset.placeholder || "",
				},
			});
			control.$input.addClass("dpx-bb-field");
			if (holder.dataset.inputId) control.$input.attr("id", holder.dataset.inputId);
			if (hidden && hidden.value) control.set_value(hidden.value);

			// ControlDate fires `change` on its input both on a pick and on a typed date,
			// after parse() has turned the user format into yyyy-mm-dd.
			control.$input.on("change", () => {
				if (hidden) hidden.value = control.get_value() || "";
			});
			holder.udt_date_control = control;
		});
	};

	// Focusing a hidden input is a silent no-op, so send focus to the visible control.
	upande_dev_tools.focus_date_field = function (el) {
		const holder = el && (el.closest ? el.closest("[data-udt-date]") : null);
		if (!holder) return;
		if (holder.udt_date_control) return holder.udt_date_control.$input.trigger("focus");
		const native = holder.querySelector('input[type="date"]');
		if (native) native.focus();
	};
})();
