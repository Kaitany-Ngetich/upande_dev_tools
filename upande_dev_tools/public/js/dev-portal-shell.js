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

	// These are server rendered pages, so a nav click sits on the old page until
	// the next one paints. Move the highlight and start a progress bar the moment
	// it is pressed, so the click is answered even though the page has not turned.
	const bar = document.createElement("div");
	bar.className = "dpx-progress";
	document.body.appendChild(bar);

	let timer;
	shell.querySelectorAll(".dpx-side .nav-item").forEach(function (link) {
		link.addEventListener("click", function (e) {
			if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
			if (link.classList.contains("active")) return;

			shell.querySelectorAll(".dpx-side .nav-item").forEach(function (other) {
				other.classList.remove("active");
			});
			link.classList.add("active", "going");

			const title = shell.querySelector(".dpx-topbar h1");
			const label = link.querySelector(".lbl");
			if (title && label) title.textContent = label.textContent;

			const main = shell.querySelector(".dpx-content");
			if (main) main.setAttribute("aria-busy", "true");

			bar.classList.add("on");
			let at = 0;
			clearInterval(timer);
			timer = setInterval(function () {
				at = Math.min(at + (90 - at) * 0.12, 90);
				bar.style.width = at + "%";
			}, 90);
		});
	});

	window.addEventListener("pageshow", function () {
		clearInterval(timer);
		bar.classList.remove("on");
		bar.style.width = "0%";
	});
})();
