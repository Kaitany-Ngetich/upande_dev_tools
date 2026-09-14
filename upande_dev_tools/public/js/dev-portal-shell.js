(function () {
	const KEY = "dpx-rail";
	const shell = document.querySelector(".dpx");
	const toggle = shell && shell.querySelector(".dpx-rail-toggle");
	if (!toggle) return;

	function apply(collapsed) {
		shell.classList.toggle("rail", collapsed);
		toggle.setAttribute("aria-pressed", String(collapsed));
		toggle.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
	}

	let collapsed = false;
	try {
		collapsed = localStorage.getItem(KEY) === "1";
	} catch (e) {}
	apply(collapsed);

	toggle.addEventListener("click", function () {
		collapsed = !collapsed;
		apply(collapsed);
		try {
			localStorage.setItem(KEY, collapsed ? "1" : "0");
		} catch (e) {}
	});

	document.addEventListener("keydown", function (e) {
		if (e.key === "[" && (e.metaKey || e.ctrlKey)) {
			e.preventDefault();
			toggle.click();
		}
	});
})();
