/* Dev Tools v2 keyboard layer. Small shared helper; each page calls DevKeys.init({...}).
 * Same keys, same meanings everywhere: / search, j k move, Enter open, r refresh, ? help, Esc close.
 * Does not touch PH. Adds: list selection (first row auto-selected, kept by id), a visible highlight,
 * a "?" help sheet, <kbd> hints, focus restore after dialogs. */
(function () {
	"use strict";
	if (window.DevKeys) return;
	const TYPING = /^(INPUT|SELECT|TEXTAREA)$/;
	const $ = (s, r) => (r || document).querySelector(s);
	const $$ = (s, r) => [...(r || document).querySelectorAll(s)];
	const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
	const overlay = () => document.querySelector(".ph-overlay");
	const shown = (el) => !!(el.offsetParent || el.getClientRects().length);
	const typingIn = (el) => !!el && (TYPING.test(el.tagName) || el.isContentEditable);

	const css = document.createElement("style");
	css.textContent = `
.ph2 :is(button,a,[tabindex],[role=tab],[role=button],summary):focus-visible{outline:2px solid var(--signal,#228883);outline-offset:2px}
.kb-cur{outline:2px solid var(--signal,#228883);outline-offset:-2px;scroll-margin:56px 0}
tr.kb-cur{outline:0}
tr.kb-cur>td{background:var(--signal-soft,rgba(34,136,131,.14))!important;box-shadow:inset 0 2px 0 var(--signal,#228883),inset 0 -2px 0 var(--signal,#228883)}
tr.kb-cur>td:first-child{box-shadow:inset 4px 0 0 var(--signal,#228883),inset 0 2px 0 var(--signal,#228883),inset 0 -2px 0 var(--signal,#228883)}
.kb-hint{display:flex;flex-wrap:wrap;align-items:center;gap:6px 14px;font-size:12px;color:var(--ink-mute,#777)}
.kb-hint span{white-space:nowrap}
.kb-hint .is-off{opacity:.45}
.kb-hint button{font:inherit;color:inherit;background:none;border:0;padding:0;cursor:pointer;text-decoration:underline}
.kb-hint kbd,.kb-sheet kbd,.kb-help kbd{font:600 11px var(--mono,monospace);background:var(--tint,rgba(0,0,0,.05));border-radius:6px;padding:2px 6px;margin-right:4px;color:var(--ink-3,#444)}
.kb-sheet{display:grid;grid-template-columns:auto 1fr;gap:8px 16px;margin:0;font-size:13px}
.kb-sheet dt{white-space:nowrap}.kb-sheet dd{margin:0}.kb-sheet .is-off{opacity:.5}
.kb-help{min-width:32px}
@media (max-width:700px){.kb-hint{display:none}}`;
	document.head.appendChild(css);

	let cfg = null, cur = "", edge = "", sheet = null;
	const stack = [];

	const searchEl = () => cfg && cfg.search !== false ? $(cfg.search || "#f-q") : null;
	const refreshBtn = () => {
		if (cfg && typeof cfg.refresh === "function") return { click: cfg.refresh };
		const b = document.getElementById("ph-refresh");
		return b && !b.hidden ? b : null;
	};
	const items = () => (cfg && cfg.list ? cfg.list.items().filter(shown) : []);
	const idOf = (el, i) => cfg.list.id ? cfg.list.id(el, i) : el.dataset.name || el.dataset.key || el.dataset.req || el.dataset.path || el.dataset.id || (el.tagName === "TR" && el.cells[0] && el.cells[0].textContent.trim().replace(/\s+/g, " ").slice(0, 120)) || "#" + i;
	const curItem = () => { const a = items(); const i = a.findIndex((el, n) => idOf(el, n) === cur); return i < 0 ? null : a[i]; };
	const toast = (m) => (window.PH ? PH.toast(m) : null);

	function sync() {
		if (!cfg || !cfg.list) return;
		const a = items();
		$$(".kb-cur").forEach((x) => { x.classList.remove("kb-cur"); x.removeAttribute("aria-current"); });
		if (!a.length) { cur = ""; paint(); return; }
		let i = a.findIndex((el, n) => idOf(el, n) === cur);
		if (edge) { i = edge === "last" ? a.length - 1 : 0; edge = ""; }
		if (i < 0) i = 0;
		cur = idOf(a[i], i);
		a[i].classList.add("kb-cur");
		a[i].setAttribute("aria-current", "true");
		paint();
	}
	let raf = 0;
	const later = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(sync); };

	function select(id, scroll) { cur = id; sync(); const el = curItem(); if (el && scroll) el.scrollIntoView({ block: "nearest" }); }
	function move(d) {
		const a = items(); if (!a.length) return;
		let i = a.findIndex((el, n) => idOf(el, n) === cur);
		const to = i < 0 ? 0 : i + d;
		if (to >= a.length || to < 0) {
			const wrap = a[Math.max(0, Math.min(a.length - 1, i))].closest(".ph-table-wrap");
			const pager = wrap && wrap.parentElement.querySelector('.ph-pager [data-pg="' + (d > 0 ? 1 : -1) + '"]:not([disabled])');
			if (pager) { edge = d > 0 ? "first" : "last"; pager.click(); later(); }
			return;
		}
		select(idOf(a[to], to), true);
	}

	/* ---- rows shown in the hint and the sheet ---- */
	function rows() {
		const r = [];
		const it = curItem();
		if (searchEl()) r.push({ keys: ["/"], text: "Search" });
		if (cfg.list) {
			r.push({ keys: ["j", "k"], text: "Move down / up" });
			if (cfg.list.open !== false) r.push({ keys: ["Enter"], text: "Open details" });
		}
		(cfg.keys || []).forEach((k) => {
			if (k.show && !k.show()) return;
			let off = "";
			if (k.check && !k.global) { const c = it ? k.check(it, cur) : "Select a row first"; if (c !== true) off = c || "Not available"; }
			r.push({ keys: k.keys, text: k.label, off });
		});
		(cfg.extra || []).forEach((x) => r.push(x));
		if (cfg.refresh !== false && refreshBtn() && !(cfg.keys || []).some((k) => k.keys.includes("r"))) r.push({ keys: ["r"], text: "Refresh" });
		else if ((cfg.keys || []).some((k) => k.keys.includes("r")) && refreshBtn()) r.push({ keys: [], text: "Refresh: use the refresh button at the top (r is " + cfg.keys.find((k) => k.keys.includes("r")).label + " here)", plain: true });
		r.push({ keys: ["Esc"], text: "Close a dialog, or leave a field" });
		return r;
	}
	const kbds = (k) => k.keys.map((c) => "<kbd>" + esc(c) + "</kbd>").join(k.join || " ");
	function paint() {
		if (!cfg || !cfg.hint) return;
		const host = $(cfg.hint); if (!host) return;
		host.classList.add("kb-hint");
		const html = rows().filter((k) => !k.plain && k.keys[0] !== "Esc").map((k) => '<span class="' + (k.off ? "is-off" : "") + '"' + (k.off ? ' title="' + esc(k.off) + '"' : "") + ">" + kbds(k) + " " + esc(k.text.split(" / ")[0] === "Move down" ? "move" : k.text.toLowerCase()) + "</span>").join("") + '<span><button type="button" data-kb-help><kbd>?</kbd>all keys</button></span>';
		if (host.dataset.kb === html) return;
		host.dataset.kb = html;
		host.innerHTML = html;
		const b = $("[data-kb-help]", host); if (b) b.onclick = help;
	}

	function help() {
		if (!window.PH || overlay()) return;
		const body = '<dl class="kb-sheet">' + rows().map((k) => "<dt class=\"" + (k.off ? "is-off" : "") + "\">" + (k.plain ? "" : kbds(k)) + "</dt><dd class=\"" + (k.off ? "is-off" : "") + "\">" + esc(k.text) + (k.off ? " (" + esc(k.off.toLowerCase()) + ")" : "") + "</dd>").join("") + '<dt><kbd>?</kbd></dt><dd>This list</dd></dl>';
		const m = PH.modal({ title: "Keyboard shortcuts", sub: cfg.title || "", body, actions: [{ label: "Close", primary: true }] });
		setTimeout(() => { const b = $(".ph-modal__foot button", m.el); if (b) b.focus(); }, 60);
	}

	function onKey(e) {
		if (!cfg || e.defaultPrevented || e.isComposing) return;
		if (e.key === "Escape") {
			if (!overlay() && cfg.escBlur !== false && /^(INPUT|TEXTAREA|SELECT)$/.test((e.target || {}).tagName || "")) e.target.blur();
			return;
		}
		if (e.ctrlKey || e.metaKey || e.altKey || overlay() || typingIn(e.target)) return;
		const k = e.key;
		if (k === "?") { e.preventDefault(); return help(); }
		if (k === "/" && searchEl()) { e.preventDefault(); const q = searchEl(); q.focus(); q.select && q.select(); return; }
		const own = (cfg.keys || []).find((x) => x.keys.includes(k));
		if (own) {
			if (own.show && !own.show()) return;
			if (own.global) { e.preventDefault(); own.run(); return; }
			const it = curItem();
			if (!it) { e.preventDefault(); toast("Select a row first (j / k), then press " + k); return; }
			const c = own.check ? own.check(it, cur) : true;
			e.preventDefault();
			if (c !== true) { toast(c || "Not available for this row"); return; }
			own.run(it, cur);
			return;
		}
		if (k === "r" && cfg.refresh !== false) { const b = refreshBtn(); if (b) { e.preventDefault(); b.click(); } return; }
		if (!cfg.list) return;
		if (k === "j" || k === "k") { e.preventDefault(); move(k === "j" ? 1 : -1); }
		else if (k === "Enter" && cfg.list.open !== false && !e.target.closest("button,a,[role=tab],[role=button],[role=link],summary,[tabindex]:not([tabindex='-1'])")) {
			const it = curItem();
			if (it) { e.preventDefault(); if (cfg.list.open) cfg.list.open(it, cur); else it.click(); }
		}
	}

	/* focus back to whatever opened a dialog */
	function watchDialogs() {
		const host = $(".ph2") || document.body;
		new MutationObserver((ms) => ms.forEach((m) => {
			m.addedNodes.forEach((n) => { if (n.classList && n.classList.contains("ph-overlay")) stack.push(document.activeElement); });
			m.removedNodes.forEach((n) => {
				if (!n.classList || !n.classList.contains("ph-overlay")) return;
				const was = stack.pop();
				setTimeout(() => {
					if (overlay()) return;
					if (was && was !== document.body && was.isConnected && shown(was)) was.focus({ preventScroll: true });
					else if (!document.activeElement || document.activeElement === document.body) {
						const root = cfg && cfg.list && $(cfg.list.root || "#ph-main");
						if (root) { if (!root.hasAttribute("tabindex")) root.setAttribute("tabindex", "-1"); root.style.outline = "0"; root.focus({ preventScroll: true }); }
					}
				}, 0);
			});
		})).observe(host, { childList: true });
	}

	function addHelpButton() {
		let tools = $(".ph-head__tools");
		if ($(".kb-help")) return;
		if (!tools) { const head = $(".ph-head"); if (!head) return; tools = document.createElement("div"); tools.className = "ph-head__tools"; head.appendChild(tools); }
		const b = document.createElement("button");
		b.type = "button"; b.className = "ph-btn ph-btn--ghost ph-btn--sm kb-help";
		b.title = "Keyboard shortcuts (?)"; b.setAttribute("aria-label", "Keyboard shortcuts"); b.setAttribute("aria-keyshortcuts", "?");
		b.innerHTML = "<kbd>?</kbd>"; b.onclick = help;
		tools.insertBefore(b, tools.firstChild);
	}

	window.DevKeys = {
		init(c) {
			cfg = c;
			document.addEventListener("keydown", onKey);
			watchDialogs();
			addHelpButton();
			if (c.list) {
				const root = $(c.list.root || "#ph-main") || document.body;
				new MutationObserver((ms) => { if (ms.some((m) => !(cfg.hint && m.target.closest && m.target.closest(cfg.hint)) && !(m.target.closest && m.target.closest('.kb-help')))) later(); }).observe(root, { childList: true, subtree: true, attributes: true, attributeFilter: ["hidden"] });
				document.addEventListener("focusin", (e) => { const a = items(); const i = a.findIndex((el) => el.contains(e.target)); if (i >= 0) { cur = idOf(a[i], i); sync(); } });
				document.addEventListener("click", (e) => { if (e.target.closest(".ph-overlay")) return; const a = items(); const i = a.findIndex((el) => el.contains(e.target)); if (i >= 0) { cur = idOf(a[i], i); later(); } }, true);
				later();
			}
			paint();
		},
		select, sync, current: () => cur, currentItem: curItem, repaint: paint, help,
	};
})();
