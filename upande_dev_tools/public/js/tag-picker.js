window.upande_dev_tools = window.upande_dev_tools || {};

// Tags are Master Data page-editable (Work Tag) now, not free text - so picking one is a
// click, never typing, and a stray typo can't create a tag nobody will ever filter by again.
// Self-contained and delegated at the document level (same reasoning as toast.js): the forms
// that use this get rebuilt from scratch on every open, and this way a single binding here
// keeps working regardless of which page or overlay the picker ends up mounted in.
(function () {
	upande_dev_tools.tag_picker_html = function (opts) {
		opts = opts || {};
		const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
		const name = opts.name || "tags";
		const selected = new Set(opts.selected || []);
		const tags = opts.tags || [];
		const chips = tags
			.map(
				(t) =>
					`<button type="button" class="dpx-bb-chip dpx-tagpick-opt${
						selected.has(t) ? " on" : ""
					}" data-tag="${esc(t)}" aria-pressed="${selected.has(t)}">${esc(t)}</button>`
			)
			.join("");
		return `<div class="dpx-tagpick" data-name="${esc(name)}">
			<div class="dpx-tagpick-opts">${
				chips || `<span class="dpx-tagpick-empty">No tags set up yet - add one in Master Data.</span>`
			}</div>
			<input type="hidden" name="${esc(name)}" value="${esc([...selected].join(","))}">
		</div>`;
	};

	if (upande_dev_tools._tag_picker_wired) return;
	upande_dev_tools._tag_picker_wired = true;

	document.addEventListener("click", (e) => {
		const btn = e.target.closest(".dpx-tagpick-opt");
		if (!btn) return;
		const wrap = btn.closest(".dpx-tagpick");
		if (!wrap) return;
		const on = !btn.classList.contains("on");
		btn.classList.toggle("on", on);
		btn.setAttribute("aria-pressed", String(on));
		const chosen = [...wrap.querySelectorAll(".dpx-tagpick-opt.on")].map((el) => el.dataset.tag);
		const hidden = wrap.querySelector('input[type="hidden"]');
		if (hidden) hidden.value = chosen.join(",");
	});
})();
