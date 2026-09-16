window.upande_dev_tools = window.upande_dev_tools || {};

// A self-contained toast with zero dependency on frappe.ui's desk-only widgets - some of
// those (frappe.prompt, frappe.confirm's field rendering) turned out not to be loaded on
// these portal pages at all (they need frappe.ui.form.make_control, which isn't in the web
// bundle), so every user-facing response in this app's portal pages goes through this
// instead of frappe.show_alert, to guarantee it's actually visible regardless of what else
// is or isn't bundled.
(function () {
	let host = null;

	function ensure_host() {
		if (host && document.body.contains(host)) return host;
		host = document.createElement("div");
		host.className = "dpx-toast-host";
		document.body.appendChild(host);
		return host;
	}

	upande_dev_tools.toast = function (message, kind) {
		const root = ensure_host();
		const el = document.createElement("div");
		el.className = `dpx-toast dpx-toast-${kind || "info"}`;
		el.textContent = message == null ? "" : String(message);
		root.appendChild(el);
		setTimeout(() => el.classList.add("in"), 0);

		const remove = () => {
			el.classList.remove("in");
			setTimeout(() => el.remove(), 180);
		};
		const timer = setTimeout(remove, kind === "red" ? 5000 : 3200);
		el.addEventListener("click", () => {
			clearTimeout(timer);
			remove();
		});
	};
})();
