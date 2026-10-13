/* Code Editor v2 (www/code-editor-v2.html).
 *
 * Every read and write goes through the existing api/code_editor.py endpoints, which own all
 * path guards (is_safe_path / is_blocked / allowed extensions) and the Dev Team check. The tree
 * is the endpoint's own tree, so the page only ever offers files the endpoints will accept.
 */
(function () {
	"use strict";

	const API = "upande_dev_tools.api.code_editor.";
	const MONACO_BASE = "/assets/upande_dev_tools/js/monaco/vs";
	const ICON_BASE = "/assets/upande_dev_tools/icons/material/";
	const DEFAULT_APP = "upande_dev_tools";
	const SEARCH_DELAY_MS = 250;
	const PREVIEW_CHARS = 4000;
	const LOG_LIMIT = 30;
	const STORE = { theme: "ce.theme", explorer: "ce.explorer", details: "ce.details" };
	const PANE_LIMITS = { explorer: [180, 560], details: [200, 480] };

	/** File extension -> Material icon file name (same icon set as the current page). */
	const FILE_ICONS = {
		".py": "python", ".js": "javascript", ".json": "json", ".html": "html", ".css": "css",
		".scss": "sass", ".md": "markdown", ".yml": "yaml", ".yaml": "yaml", ".toml": "settings",
	};
	const LANGUAGE_LABELS = {
		python: "Python", javascript: "JavaScript", json: "JSON", html: "HTML", css: "CSS", scss: "SCSS",
		markdown: "Markdown", plaintext: "Plain text", yaml: "YAML", toml: "TOML",
	};

	/* ── Pure helpers (also exported for tests) ───────────────────── */

	/** "1.5 KB" style size; 0 -> "0 B". */
	function formatBytes(bytes) {
		if (!bytes) return "0 B";
		if (bytes < 1024) return bytes + " B";
		if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
		return (bytes / 1048576).toFixed(1) + " MB";
	}

	/** Identity of an open file: the same relative path can exist in two apps. */
	function tabKey(app, path) {
		return app + "::" + path;
	}

	/** Icon file name for an extension; folders use folder / folder-open. */
	function iconName(extension, isFolder, isOpen) {
		if (isFolder) return isOpen ? "folder-open" : "folder";
		return FILE_ICONS[extension] || "file";
	}

	/** Clamp a pane width into its allowed range. */
	function clampWidth(pane, px) {
		const [lo, hi] = PANE_LIMITS[pane];
		return Math.min(hi, Math.max(lo, Math.round(px)));
	}

	if (typeof module !== "undefined" && module.exports) {
		module.exports = { formatBytes, tabKey, iconName, clampWidth };
		return;
	}

	/* ── State ────────────────────────────────────────────────────── */

	const $ = (id) => document.getElementById(id);
	const root = $("ce");
	const state = {
		app: null,
		tabs: new Map(), // key -> {key, app, path, name, extension, language, size, modified, model, savedVersion, dirty, viewState}
		active: null,
		monaco: null,
		editor: null,
		theme: store(STORE.theme) === "vs-dark" ? "vs-dark" : "vs",
		saving: false,
		searchToken: 0,
	};

	function store(key, value) {
		try {
			if (value === undefined) return localStorage.getItem(key);
			localStorage.setItem(key, value);
		} catch (e) {
			return null; // storage blocked: the page works without remembering
		}
		return value;
	}

	function activeTab() {
		return state.tabs.get(state.active) || null;
	}

	function dirtyTabs() {
		return [...state.tabs.values()].filter((t) => t.dirty);
	}

	function setState(name, title, text) {
		root.dataset.state = name;
		const box = $("editor-empty");
		box.innerHTML = name === "ready" ? "" : `<b>${PH.esc(title)}</b><span>${PH.esc(text || "")}</span>`;
	}

	function log(message) {
		const list = $("log");
		if (!list.dataset.used) list.innerHTML = "";
		list.dataset.used = "1";
		const li = document.createElement("li");
		li.textContent = `${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}  ${message}`;
		list.prepend(li);
		while (list.children.length > LOG_LIMIT) list.lastElementChild.remove();
	}

	function icon(extension, isFolder, isOpen) {
		return `<img class="ce__ico" alt="" src="${ICON_BASE}${iconName(extension, isFolder, isOpen)}.svg">`;
	}

	/* ── Monaco ───────────────────────────────────────────────────── */

	function loadMonaco() {
		return new Promise((resolve, reject) => {
			const s = document.createElement("script");
			s.src = MONACO_BASE + "/loader.js";
			s.onerror = () => reject(new Error("The editor library could not be loaded"));
			s.onload = () => {
				window.require.config({ paths: { vs: MONACO_BASE } });
				window.require(["vs/editor/editor.main"], () => resolve(window.monaco), reject);
			};
			document.head.appendChild(s);
		});
	}

	function createEditor(monaco) {
		state.monaco = monaco;
		state.editor = monaco.editor.create($("editor"), {
			model: null,
			theme: state.theme,
			automaticLayout: true,
			minimap: { enabled: window.innerWidth > 900 },
			fontSize: 13,
			wordWrap: "on",
			scrollBeyondLastLine: false,
			fontFamily: "'JetBrains Mono', ui-monospace, monospace",
		});
		state.editor.onDidChangeCursorPosition((e) => {
			$("st-pos").textContent = `Ln ${e.position.lineNumber}, Col ${e.position.column}`;
		});
	}

	/* ── Tree ─────────────────────────────────────────────────────── */

	function nodeRow(node, level) {
		const row = document.createElement("button");
		row.type = "button";
		row.className = "ce__row";
		row.style.paddingLeft = 10 + level * 14 + "px";
		row.title = node.path;
		return row;
	}

	/** Render nodes into container; a folder's children are only built when it is first opened. */
	function renderNodes(container, nodes, level) {
		nodes.forEach((node) => {
			const row = nodeRow(node, level);
			if (node.is_folder) {
				const group = document.createElement("div");
				group.setAttribute("role", "group");
				group.hidden = true;
				let built = false;
				row.setAttribute("role", "treeitem");
				row.setAttribute("aria-expanded", "false");
				row.innerHTML = `<span class="ce__chev">▶</span>${icon("", true, false)}<span class="ce__name">${PH.esc(node.name)}</span>`;
				row.onclick = () => {
					const open = group.hidden;
					if (open && !built) {
						built = true;
						renderNodes(group, node.children || [], level + 1);
						if (!group.children.length) group.innerHTML = '<div class="ce__note">No editable files</div>';
					}
					group.hidden = !open;
					row.setAttribute("aria-expanded", String(open));
					row.querySelector(".ce__chev").classList.toggle("is-open", open);
					row.querySelector(".ce__ico").src = ICON_BASE + iconName("", true, open) + ".svg";
				};
				container.append(row, group);
			} else {
				fileRow(row, node, node.name);
				container.append(row);
			}
		});
	}

	function fileRow(row, node, label, sub) {
		row.dataset.path = node.path;
		row.setAttribute("role", "treeitem");
		row.classList.toggle("is-on", state.active === tabKey(state.app, node.path));
		row.innerHTML = `<span class="ce__chev"></span>${icon(node.extension)}<span class="ce__name">${PH.esc(label)}${
			sub ? `<span class="ce__sub">${PH.esc(sub)}</span>` : ""
		}</span><button type="button" class="ce__peek" aria-label="Quick look at ${PH.esc(node.name || label)}">Peek</button>`;
		row.onclick = () => openFile(state.app, node.path);
		row.onkeydown = (e) => {
			if (e.key === "ArrowRight" && row.getAttribute("aria-expanded") === "false") row.click();
		};
		row.querySelector(".ce__peek").onclick = (e) => {
			e.stopPropagation();
			quickLook(node.path);
		};
	}

	function showTree(tree) {
		const box = $("tree");
		box.innerHTML = "";
		const nodes = (tree && tree.children) || [];
		if (!nodes.length) {
			box.innerHTML = '<div class="ce__note">No editable files found</div>';
			return;
		}
		renderNodes(box, nodes, 0);
	}

	function loadTree(app) {
		$("tree-title").textContent = app.replaceAll("_", " ");
		$("tree").innerHTML = '<div class="ce__note">Loading files…</div>';
		return PH.call(API + "get_app_tree", { app }, { type: "GET", silent: true })
			.then((tree) => {
				if (app !== state.app) return;
				showTree(tree);
				log(`Loaded ${app}`);
			})
			.catch((e) => {
				$("tree").innerHTML = "";
				PH.error($("tree"), e.message, () => loadTree(app));
			});
	}

	/* ── Search (server side: api.code_editor.search_files) ────────── */

	function runSearch(query) {
		const token = ++state.searchToken;
		if (!query) return loadTree(state.app);
		$("tree").innerHTML = '<div class="ce__note">Searching…</div>';
		return PH.call(API + "search_files", { app: state.app, query }, { type: "GET", silent: true })
			.then((files) => {
				if (token !== state.searchToken) return;
				const box = $("tree");
				box.innerHTML = "";
				if (!files.length) return (box.innerHTML = '<div class="ce__note">No matching files</div>');
				files.forEach((f) => {
					const row = document.createElement("button");
					row.type = "button";
					row.className = "ce__row";
					row.title = f.path;
					fileRow(row, { path: f.path, name: f.file_name, extension: f.extension }, f.file_name, f.folder);
					box.append(row);
				});
			})
			.catch((e) => {
				if (token === state.searchToken) PH.error($("tree"), e.message, () => runSearch(query));
			});
	}

	/* ── Open files / tabs ────────────────────────────────────────── */

	function openFile(app, path) {
		const key = tabKey(app, path);
		if (state.tabs.has(key)) return activate(key);
		if (!state.editor) return PH.toast("The editor is still loading", "warn");
		return PH.call(API + "read_file", { app, path }, { type: "GET" }).then((file) => {
			const model = state.monaco.editor.createModel(file.content || "", file.language || "plaintext");
			const tab = {
				key, app, path: file.path, name: file.file_name, extension: file.extension, language: file.language,
				size: file.size, modified: file.modified, model, savedVersion: model.getAlternativeVersionId(),
				dirty: false, viewState: null,
			};
			model.onDidChangeContent(() => {
				const dirty = model.getAlternativeVersionId() !== tab.savedVersion;
				if (dirty === tab.dirty) return;
				tab.dirty = dirty;
				renderChrome();
			});
			state.tabs.set(key, tab);
			log(`Opened ${file.path}`);
			activate(key);
		}, () => null); // PH.call already told the user why the file was refused
	}

	function activate(key) {
		const current = activeTab();
		if (current) current.viewState = state.editor.saveViewState();
		state.active = key;
		const tab = activeTab();
		state.editor.setModel(tab.model);
		if (tab.viewState) state.editor.restoreViewState(tab.viewState);
		setState("ready");
		state.editor.focus();
		renderChrome();
		syncUrl();
	}

	function closeTab(key) {
		const tab = state.tabs.get(key);
		if (!tab) return Promise.resolve();
		const ask = tab.dirty
			? PH.confirm(`Close ${tab.name}?`, "It has changes that are not saved. They will be lost.", { ok: "Discard changes", danger: true })
			: Promise.resolve(true);
		return ask.then((ok) => {
			if (!ok) return;
			const keys = [...state.tabs.keys()];
			const next = keys[keys.indexOf(key) + 1] || keys[keys.indexOf(key) - 1] || null;
			if (state.active === key) {
				state.active = null;
				state.editor.setModel(null);
			}
			state.tabs.delete(key);
			tab.model.dispose();
			if (next && !state.active) activate(next);
			else renderChrome();
			if (!state.tabs.size) {
				setState("empty", "No file open", "Choose a file from the list to start reading or editing.");
				syncUrl();
			}
		});
	}

	/* ── Save ─────────────────────────────────────────────────────── */

	/** Ask whether to overwrite when the file changed on disk after it was opened. */
	function confirmNoConflict(tab) {
		return PH.call(API + "preview_file", { app: tab.app, path: tab.path, max_chars: 1 }, { type: "GET", silent: true })
			.then((disk) => {
				if (disk.modified === tab.modified) return true;
				return PH.confirm(
					`${tab.name} changed on disk`,
					"Someone or something else saved this file after you opened it. Saving now replaces their version with yours.",
					{ ok: "Overwrite", danger: true }
				);
			})
			.catch(() => true); // the write below reports the real error
	}

	function save() {
		const tab = activeTab();
		if (!tab || !tab.dirty || state.saving) return;
		state.saving = true;
		renderChrome();
		const content = tab.model.getValue();
		const version = tab.model.getAlternativeVersionId();
		confirmNoConflict(tab)
			.then((go) => go && PH.call(API + "write_file", { app: tab.app, path: tab.path, content }))
			.then((saved) => {
				if (!saved) return;
				tab.savedVersion = version;
				tab.dirty = tab.model.getAlternativeVersionId() !== version;
				tab.modified = saved.modified;
				tab.size = saved.size;
				log(`Saved ${tab.path}`);
				PH.toast(`${tab.name} saved`, "good");
			})
			.catch(() => log(`Could not save ${tab.path}`))
			.finally(() => {
				state.saving = false;
				renderChrome();
			});
	}

	/* ── Quick look (api.code_editor.preview_file) ─────────────────── */

	function quickLook(path) {
		PH.call(API + "preview_file", { app: state.app, path, max_chars: PREVIEW_CHARS }, { type: "GET" }).then((p) => {
			const pre = document.createElement("pre");
			pre.className = "ce__peekbox";
			pre.textContent = p.preview;
			PH.modal({
				title: p.file_name,
				sub: `${state.app} › ${p.path} · ${formatBytes(p.size)}${p.truncated ? ` · first ${PREVIEW_CHARS} characters` : ""}`,
				size: "lg",
				body: pre,
				actions: [{ label: "Open to edit", primary: true, onClick: () => void openFile(state.app, p.path) }, { label: "Close" }],
			});
		});
	}

	/* ── Chrome: tabs, open list, details, status ──────────────────── */

	function renderChrome() {
		const tabs = [...state.tabs.values()];
		const bar = $("tabs");
		bar.innerHTML = "";
		tabs.forEach((t) => {
			const el = document.createElement("div");
			el.className = "ce__tab";
			el.setAttribute("role", "tab");
			el.setAttribute("aria-selected", String(t.key === state.active));
			el.tabIndex = 0;
			el.title = `${t.app} › ${t.path}`;
			el.innerHTML = `${icon(t.extension)}<span class="ce__name">${PH.esc(t.name)}</span>${
				t.dirty ? '<span class="ce__dot" title="Unsaved changes"></span>' : ""
			}<button type="button" class="ce__x" aria-label="Close ${PH.esc(t.name)}">×</button>`;
			el.onclick = () => activate(t.key);
			el.onkeydown = (e) => tabKeys(e, t.key, tabs);
			el.querySelector(".ce__x").onclick = (e) => {
				e.stopPropagation();
				closeTab(t.key);
			};
			bar.append(el);
		});
		renderOpenList(tabs);
		renderDetails();
		const tab = activeTab();
		$("save").disabled = !tab || !tab.dirty || state.saving;
		$("save").textContent = state.saving ? "Saving…" : "Save";
		$("crumb").textContent = tab ? `${tab.app} › ${tab.path}` : "Select a file from the list";
		$("st-file").textContent = tab ? tab.name : "No file";
		$("st-lang").textContent = tab ? LANGUAGE_LABELS[tab.language] || tab.language : "Plain text";
		const n = dirtyTabs().length;
		$("st-dirty").textContent = n ? `${n} unsaved` : "";
		$("st-dirty").className = n ? "ce__warn" : "";
		document.querySelectorAll("#tree .ce__row[data-path]").forEach((r) => r.classList.toggle("is-on", state.active === tabKey(state.app, r.dataset.path)));
	}

	function tabKeys(e, key, tabs) {
		const i = tabs.findIndex((t) => t.key === key);
		const move = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
		if (move) {
			const next = tabs[(i + move + tabs.length) % tabs.length];
			activate(next.key);
			$("tabs").children[tabs.indexOf(next)].focus();
		} else if (e.key === "Enter" || e.key === " ") {
			e.preventDefault();
			activate(key);
		}
	}

	function renderOpenList(tabs) {
		$("open-count").textContent = tabs.length;
		const box = $("open-editors");
		box.innerHTML = tabs.length ? "" : '<div class="ce__note">No file open</div>';
		tabs.forEach((t) => {
			const row = document.createElement("button");
			row.type = "button";
			row.className = "ce__row" + (t.key === state.active ? " is-on" : "");
			row.innerHTML = `${icon(t.extension)}<span class="ce__name">${t.dirty ? "● " : ""}${PH.esc(t.name)}${
				t.app !== state.app ? `<span class="ce__sub">${PH.esc(t.app)}</span>` : ""
			}</span>`;
			row.onclick = () => activate(t.key);
			box.append(row);
		});
	}

	function dl(el, pairs) {
		el.innerHTML = pairs.map(([k, v]) => `<dt>${PH.esc(k)}</dt><dd>${PH.esc(v)}</dd>`).join("");
	}

	function renderDetails() {
		dl($("d-app"), [["App", state.app || "-"], ["Folder", state.app ? "apps/" + state.app : "-"]]);
		const t = activeTab();
		dl($("d-file"), t
			? [["File", t.name], ["Language", LANGUAGE_LABELS[t.language] || t.language], ["Size", formatBytes(t.size)],
			   ["Saved on disk", new Date(t.modified * 1000).toLocaleString()], ["Encoding", "UTF-8"], ["Changes", t.dirty ? "Not saved" : "Saved"]]
			: [["File", "-"]]);
	}

	/* ── Page wiring ──────────────────────────────────────────────── */

	function syncUrl() {
		const t = activeTab();
		const q = new URLSearchParams();
		q.set("app", state.app);
		if (t && t.app === state.app) q.set("file", t.path);
		history.replaceState(null, "", "?" + q.toString());
	}

	function switchApp(app) {
		state.app = app;
		$("f-q").value = "";
		renderChrome();
		syncUrl();
		return loadTree(app);
	}

	function applyTheme() {
		const dark = state.theme === "vs-dark";
		if (state.monaco) state.monaco.editor.setTheme(state.theme);
		$("theme").textContent = dark ? "Light editor" : "Dark editor";
	}

	/** Make a splitter drag/arrow-key resize one pane via a CSS variable on the root. */
	function resizable(sepId, pane, sign) {
		const sep = $(sepId);
		const set = (px) => {
			const w = clampWidth(pane, px);
			root.style.setProperty("--ce-" + pane, w + "px");
			store(STORE[pane], String(w));
			return w;
		};
		const width = () => parseInt(getComputedStyle(root).getPropertyValue("--ce-" + pane), 10) || 280;
		const saved = parseInt(store(STORE[pane]), 10);
		if (saved) set(saved);
		sep.onpointerdown = (e) => {
			e.preventDefault();
			const x0 = e.clientX;
			const w0 = width();
			sep.classList.add("is-drag");
			sep.setPointerCapture(e.pointerId);
			sep.onpointermove = (m) => set(w0 + sign * (m.clientX - x0));
			sep.onpointerup = () => {
				sep.classList.remove("is-drag");
				sep.onpointermove = sep.onpointerup = null;
			};
		};
		sep.onkeydown = (e) => {
			const d = { ArrowLeft: -20, ArrowRight: 20 }[e.key];
			if (d) {
				e.preventDefault();
				set(width() + sign * d);
			}
		};
	}

	function toggleExplorer() {
		if (window.innerWidth <= 900) root.classList.toggle("explorer-open");
		else root.classList.toggle("no-explorer");
		$("toggle-explorer").setAttribute("aria-expanded", String(root.classList.contains("explorer-open")));
	}

	function bindGlobal() {
		document.addEventListener("keydown", (e) => {
			const mod = e.ctrlKey || e.metaKey;
			const key = e.key.toLowerCase();
			if (mod && key === "s") {
				e.preventDefault();
				save();
			} else if (mod && key === "p") {
				e.preventDefault();
				$("f-q").focus();
			} else if (mod && key === "b") {
				e.preventDefault();
				toggleExplorer();
			} else if (e.altKey && key === "w" && state.active) {
				e.preventDefault();
				closeTab(state.active);
			}
		});
		const chord = (keys, text) => ({ keys, join: "+", text });
		DevKeys.init({
			title: "Code Editor", refresh: false, escBlur: false, search: false,
			extra: [chord(["Ctrl", "S"], "Save the open file"), chord(["Ctrl", "P"], "Find a file"), chord(["Alt", "W"], "Close the open tab"), chord(["Ctrl", "B"], "Show or hide the files panel"), { keys: ["←", "→"], text: "Switch tab (when a tab has focus)" }],
		});
		window.addEventListener("beforeunload", (e) => {
			if (dirtyTabs().length) {
				e.preventDefault();
				e.returnValue = "";
			}
		});
		$("save").onclick = save;
		$("theme").onclick = () => {
			state.theme = state.theme === "vs-dark" ? "vs" : "vs-dark";
			store(STORE.theme, state.theme);
			applyTheme();
		};
		$("toggle-explorer").onclick = toggleExplorer;
		$("toggle-details").onclick = () => {
			const off = root.classList.toggle("no-details");
			$("toggle-details").setAttribute("aria-pressed", String(!off));
		};
		$("f-app").onchange = (e) => switchApp(e.target.value);
		const search = PH.debounce((q) => runSearch(q), SEARCH_DELAY_MS);
		$("f-q").oninput = (e) => search(e.target.value.trim());
		$("f-q").onkeydown = (e) => {
			if (e.key === "Escape") {
				e.target.value = "";
				runSearch("");
			} else if (e.key === "Enter") {
				const first = document.querySelector("#tree .ce__row[data-path]");
				if (first) first.click();
			}
		};
		resizable("sep-explorer", "explorer", 1);
		resizable("sep-details", "details", -1);
	}

	function denied(e) {
		root.querySelectorAll("button,select,input").forEach((el) => (el.disabled = true));
		$("save").disabled = $("f-app").disabled = $("f-q").disabled = true;
		setState("error", "The Code Editor is unavailable", e.message || "It needs the Dev Team role.");
	}

	function init() {
		bindGlobal();
		applyTheme();
		const params = new URLSearchParams(location.search);
		setState("loading", "Loading the editor…", "");
		PH.call(API + "get_installed_apps", {}, { type: "GET", silent: true })
			.then((apps) => {
				PH.options($("f-app"), apps.map((a) => ({ value: a.value, label: a.label })), null);
				const wanted = params.get("app");
				const app = [wanted, DEFAULT_APP].find((a) => apps.some((x) => x.value === a)) || (apps[0] && apps[0].value);
				if (!app) throw new Error("No apps are installed");
				$("f-app").value = app;
				return Promise.all([switchApp(app), loadMonaco().then(createEditor)]);
			})
			.then(() => {
				applyTheme();
				setState("empty", "No file open", "Choose a file from the list to start reading or editing.");
				const file = params.get("file");
				if (file) openFile(state.app, file);
			})
			.catch(denied);
	}

	PH.ready(init);
})();
