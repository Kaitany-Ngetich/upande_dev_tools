let udt_editor = null;
let udt_current_app = null;
let udt_current_file = null;
let udt_file_tree = {};
let udt_open_tabs = {};
let udt_active_tab = null;
let udt_is_switching_tab = false;

frappe.pages["code-editor"].on_page_load = function(wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Code Editor",
		single_column: true
	});

	build_shell(page);
	load_monaco();
};

function build_shell(page) {
	$(page.body).html(`
		<style>
			.udt-shell { height: calc(100vh - 115px); display: flex; flex-direction: column; background: #1e1e1e; color: #cccccc; border: 1px solid #2d2d2d; overflow: hidden; font-size: 13px; }
			.udt-toolbar { height: 46px; display: flex; align-items: center; gap: 12px; padding: 8px 12px; background: #1f1f1f; border-bottom: 1px solid #333; }
			.udt-toolbar label { margin: 0; font-size: 12px; color: #c5c5c5; }
			.udt-toolbar select, .udt-toolbar input { height: 30px; background: #252526; border: 1px solid #3c3c3c; color: #d4d4d4; border-radius: 4px; padding: 5px 9px; }
			.udt-btn { height: 30px; padding: 5px 12px; border-radius: 4px; border: 1px solid #1177bb; background: #0e639c; color: white; cursor: pointer; }
			.udt-btn:disabled { opacity: .55; cursor: not-allowed; }
			.udt-btn.secondary { background: #2d2d2d; border-color: #454545; }
			.udt-btn.run { background: #1f6f3f; border-color: #2ea043; }
			.udt-main { flex: 1; display: grid; grid-template-columns: 48px 310px 1fr 300px; min-height: 0; }
			.udt-activitybar { background: #181818; border-right: 1px solid #333; display: flex; flex-direction: column; align-items: center; padding-top: 12px; gap: 18px; }
			.udt-activity-icon { width: 32px; height: 32px; display: flex; align-items: center; justify-content: center; font-size: 19px; color: #c5c5c5; cursor: pointer; border-left: 2px solid transparent; }
			.udt-activity-icon.active { color: #ffffff; border-left-color: #ffffff; }
			.udt-explorer { background: #252526; border-right: 1px solid #333; overflow: auto; }
			.udt-explorer-header { height: 36px; display: flex; align-items: center; justify-content: space-between; padding: 0 12px; font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: #bbbbbb; }
			.udt-section-title { height: 28px; display: flex; align-items: center; padding: 0 10px; font-weight: 600; color: #ffffff; font-size: 12px; text-transform: uppercase; border-top: 1px solid #333; }
			.udt-tree-item { min-height: 26px; display: flex; align-items: center; gap: 6px; padding: 0 10px; cursor: pointer; white-space: nowrap; color: #d4d4d4; }
			.udt-tree-item:hover, .udt-tree-item.active { background: #37373d; }
			.udt-tree-icon { display: inline-flex; align-items: center; gap: 4px; width: 34px; flex-shrink: 0; }
			.udt-icon { width: 16px; height: 16px; display: inline-block; flex-shrink: 0; vertical-align: middle; }
			.udt-file-name { flex: 1; overflow: hidden; text-overflow: ellipsis; }
			.udt-badge { font-size: 10px; background: #094771; color: white; border-radius: 8px; padding: 1px 6px; margin-left: 6px; }
			.udt-editor-wrap { min-width: 0; display: flex; flex-direction: column; background: #1e1e1e; }
			.udt-tabbar { height: 35px; background: #252526; border-bottom: 1px solid #333; display: flex; align-items: center; overflow-x: auto; }
			.udt-tab { height: 35px; display: flex; align-items: center; gap: 7px; padding: 0 10px; background: #2d2d2d; color: #cccccc; border-right: 1px solid #333; cursor: pointer; max-width: 220px; flex-shrink: 0; }
			.udt-tab.active { background: #1e1e1e; color: #ffffff; }
			.udt-tab-close { margin-left: 6px; opacity: .7; font-size: 16px; }
			.udt-tab-close:hover { opacity: 1; color: #ffffff; }
			.udt-breadcrumb { height: 30px; display: flex; align-items: center; padding: 0 14px; color: #aaaaaa; font-size: 12px; border-bottom: 1px solid #2d2d2d; }
			#editor { flex: 1; min-height: 0; }
			.udt-right { background: #252526; border-left: 1px solid #333; overflow: auto; }
			.udt-right-tabs { height: 36px; display: flex; border-bottom: 1px solid #333; }
			.udt-right-tab { flex: 1; display: flex; align-items: center; justify-content: center; font-size: 11px; cursor: pointer; border-bottom: 2px solid transparent; }
			.udt-right-tab.active { color: #ffffff; border-bottom-color: #007acc; }
			.udt-info-section { padding: 14px; border-bottom: 1px solid #333; }
			.udt-info-section h4 { margin: 0 0 12px; font-size: 12px; color: #ffffff; text-transform: uppercase; }
			.udt-info-row { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 9px; }
			.udt-info-label { color: #aaaaaa; }
			.udt-info-value { color: #ffffff; text-align: right; font-weight: 500; }
			.udt-bottom { height: 155px; display: grid; grid-template-columns: 1fr 360px; background: #1e1e1e; border-top: 1px solid #333; }
			.udt-bottom-panel { overflow: auto; }
			.udt-bottom-panel:first-child { border-right: 1px solid #333; }
			.udt-bottom-title { height: 30px; display: flex; align-items: center; padding: 0 12px; background: #252526; border-bottom: 1px solid #333; font-size: 11px; text-transform: uppercase; color: #ffffff; }
			.udt-terminal-body { padding: 10px 12px; font-family: monospace; font-size: 12px; color: #9cdcfe; line-height: 1.4; }
			.udt-activity-item { padding: 8px 12px; border-bottom: 1px solid #333; font-size: 12px; }
			.udt-statusbar { height: 26px; display: flex; align-items: center; gap: 18px; padding: 0 12px; background: #007acc; color: white; font-size: 12px; }
		</style>

		<div class="udt-shell">
			<div class="udt-toolbar">
				<label>App</label>
				<select id="app-selector"></select>
				<label>Branch</label>
				<select id="branch-selector"><option>develop</option><option>main</option></select>
				<input id="file-search" placeholder="Search files..." style="width: 260px;">
				<div style="flex: 1;"></div>
				<button class="udt-btn" id="save-btn" disabled>Save</button>
				<button class="udt-btn secondary" id="snapshot-btn" disabled>Snapshot</button>
				<button class="udt-btn secondary" id="compare-btn" disabled>Compare</button>
				<button class="udt-btn run" id="run-btn" disabled>Run</button>
			</div>

			<div class="udt-main">
				<div class="udt-activitybar">
					<div class="udt-activity-icon active">📄</div><div class="udt-activity-icon">🔍</div><div class="udt-activity-icon">⑂</div><div class="udt-activity-icon">🐞</div><div class="udt-activity-icon">▦</div>
					<div style="flex: 1;"></div><div class="udt-activity-icon">⚙</div>
				</div>

				<div class="udt-explorer">
					<div class="udt-explorer-header"><span>Explorer</span><span>•••</span></div>
					<div class="udt-section-title">▾ Open Editors <span class="udt-badge" id="open-count">0</span></div>
					<div id="open-editors"><div class="udt-tree-item">No file opened</div></div>
					<div class="udt-section-title" id="workspace-title">▾ Workspace</div>
					<div id="file-tree"><div class="udt-tree-item">Loading...</div></div>
				</div>

				<div class="udt-editor-wrap">
					<div class="udt-tabbar"><div class="udt-tab" id="current-tab">No file opened</div></div>
					<div class="udt-breadcrumb" id="breadcrumb">Select a file from Explorer</div>
					<div id="editor"></div>
				</div>

				<div class="udt-right">
					<div class="udt-right-tabs"><div class="udt-right-tab active">INFO</div><div class="udt-right-tab">GIT</div><div class="udt-right-tab">SNAPSHOTS</div><div class="udt-right-tab">HOOKS</div></div>
					<div class="udt-info-section">
						<h4>Repository</h4>
						<div class="udt-info-row"><span class="udt-info-label">App</span><span class="udt-info-value" id="info-app">-</span></div>
						<div class="udt-info-row"><span class="udt-info-label">Path</span><span class="udt-info-value" id="info-path">-</span></div>
						<div class="udt-info-row"><span class="udt-info-label">Branch</span><span class="udt-info-value" id="info-branch">develop</span></div>
						<div class="udt-info-row"><span class="udt-info-label">Remote</span><span class="udt-info-value">-</span></div>
						<div class="udt-info-row"><span class="udt-info-label">Status</span><span class="udt-info-value">Not checked</span></div>
					</div>
					<div class="udt-info-section">
						<h4>Current File</h4>
						<div class="udt-info-row"><span class="udt-info-label">File</span><span class="udt-info-value" id="info-file">-</span></div>
						<div class="udt-info-row"><span class="udt-info-label">Language</span><span class="udt-info-value" id="info-language">-</span></div>
						<div class="udt-info-row"><span class="udt-info-label">Encoding</span><span class="udt-info-value">UTF-8</span></div>
						<div class="udt-info-row"><span class="udt-info-label">Size</span><span class="udt-info-value" id="info-size">-</span></div>
					</div>
				</div>
			</div>

			<div class="udt-bottom">
				<div class="udt-bottom-panel"><div class="udt-bottom-title">Terminal</div><div class="udt-terminal-body" id="terminal-body">Code Editor ready.<br>Select an app and open a file.</div></div>
				<div class="udt-bottom-panel"><div class="udt-bottom-title">Activity Log</div><div id="activity-log"><div class="udt-activity-item">🚀 Code Editor initialized</div></div></div>
			</div>

			<div class="udt-statusbar">
				<span id="status-branch">⑂ develop</span><span id="status-file">No file</span><span id="status-language">Plain Text</span><span>UTF-8</span><span>LF</span><span>Spaces: 4</span>
				<span style="margin-left:auto;" id="status-position">Ln 1, Col 1</span>
			</div>
		</div>
	`);

	bind_events();
}

function load_monaco() {
	frappe.require("/assets/upande_dev_tools/js/monaco/vs/loader.js", function () {
		require.config({ paths: { vs: "/assets/upande_dev_tools/js/monaco/vs" } });

		require(["vs/editor/editor.main"], function () {
			udt_editor = monaco.editor.create(document.getElementById("editor"), {
				value: "# Welcome to Upande Dev Tools Code Editor\n\nSelect an app from the dropdown.\nThen click a file from Explorer to open it here.\n",
				language: "python",
				theme: "vs-dark",
				automaticLayout: true,
				minimap: { enabled: true },
				fontSize: 14,
				wordWrap: "on"
			});

			udt_editor.onDidChangeCursorPosition(function(e) {
				$("#status-position").text(`Ln ${e.position.lineNumber}, Col ${e.position.column}`);
			});

			udt_editor.onDidChangeModelContent(function() {
				if (udt_is_switching_tab) return;
				if (!udt_active_tab || !udt_open_tabs[udt_active_tab]) return;

				const tab = udt_open_tabs[udt_active_tab];
				tab.content = udt_editor.getValue();
				tab.dirty = tab.content !== tab.original_content;

				$("#save-btn").prop("disabled", !tab.dirty);
				render_tabs();
				render_open_editors();
			});

			load_installed_apps();
		});
	});
}

function bind_events() {
	$(document).off("change", "#app-selector").on("change", "#app-selector", function() {
		udt_current_app = $(this).val();
		udt_current_file = null;
		udt_open_tabs = {};
		udt_active_tab = null;
		reset_editor_state();
		load_file_tree(udt_current_app);
	});

	$(document).off("click", ".real-file").on("click", ".real-file", function() {
		open_file($(this).data("path"));
	});

	$(document).off("click", ".udt-tab").on("click", ".udt-tab", function(e) {
		if ($(e.target).hasClass("udt-tab-close")) return;
		switch_tab($(this).attr("data-path"));
	});

	$(document).off("click", ".udt-tab-close").on("click", ".udt-tab-close", function(e) {
		e.stopPropagation();
		close_tab($(this).attr("data-path"));
	});

	$(document).off("click", ".open-editor-item").on("click", ".open-editor-item", function() {
		switch_tab($(this).attr("data-path"));
	});

	$(document).off("click", "#save-btn").on("click", "#save-btn", function() {
		save_current_file();
	});

	$(document).off("input", "#file-search").on("input", "#file-search", function() {
		const query = ($(this).val() || "").toLowerCase();

		if (!query) {
			render_file_tree(udt_file_tree.children || []);
			return;
		}

		const matches = flatten_tree(udt_file_tree.children || []).filter(file =>
			(file.path || "").toLowerCase().includes(query)
		);

		render_search_results(matches);
	});
}

function load_installed_apps() {
	frappe.call({
		method: "upande_dev_tools.api.code_editor.get_installed_apps",
		callback: function(r) {
			const apps = r.message || [];
			const selector = $("#app-selector");

			selector.empty();

			apps.forEach(app => {
				selector.append(`<option value="${escape_html(app.value)}">${escape_html(app.label)}</option>`);
			});

			udt_current_app = apps.find(app => app.value === "upande_dev_tools")
				? "upande_dev_tools"
				: (apps[0] ? apps[0].value : null);

			if (udt_current_app) {
				selector.val(udt_current_app);
				load_file_tree(udt_current_app);
			}
		}
	});
}

function load_file_tree(app) {
	if (!app) return;

	$("#workspace-title").text("▾ " + app.replaceAll("_", " ").toUpperCase());
	$("#info-app").text(app);
	$("#info-path").text("apps/" + app);
	$("#file-tree").html(`<div class="udt-tree-item">Loading files...</div>`);
	log_activity("📁 Loading files for " + app);

	frappe.call({
		method: "upande_dev_tools.api.code_editor.get_app_tree",
		args: { app: app },
		callback: function(r) {
			udt_file_tree = r.message || {};
			render_file_tree(udt_file_tree.children || []);
			log_activity("✅ Loaded VS Code-style tree for " + app);
		}
	});
}

function render_file_tree(nodes) {
	const tree = $("#file-tree");
	tree.empty();

	if (!nodes || !nodes.length) {
		tree.html(`<div class="udt-tree-item">No editable files found</div>`);
		return;
	}

	render_tree_nodes(nodes, tree, 0);
}

function render_tree_nodes(nodes, container, level) {
	nodes.forEach(node => {
		const is_folder = node.is_folder || node.type === "folder";
		const safe_name = escape_html(node.name || "");
		const safe_path = escape_html(node.path || "");

		const row = $(`
			<div class="udt-tree-item ${is_folder ? "real-folder" : "real-file"}"
				data-path="${safe_path}"
				style="padding-left: ${10 + (level * 14)}px;">
				<span class="udt-tree-icon">
					${is_folder ? `▸ ${icon_img("folder")}` : get_file_icon(node.extension)}
				</span>
				<span class="udt-file-name" title="${safe_path}">${safe_name}</span>
			</div>
		`);

		container.append(row);

		if (is_folder) {
			const children_container = $(`<div class="udt-tree-children" style="display:none;"></div>`);
			container.append(children_container);

			row.on("click", function(e) {
				e.stopPropagation();
				const is_open = children_container.is(":visible");
				children_container.toggle(!is_open);
				row.find(".udt-tree-icon").html(
					is_open ? `▸ ${icon_img("folder")}` : `▾ ${icon_img("folder-open")}`
				);
			});

			if (node.children && node.children.length) {
				render_tree_nodes(node.children, children_container, level + 1);
			}
		} else {
			row.on("click", function(e) {
				e.stopPropagation();
				open_file(node.path);
			});
		}
	});
}

function render_search_results(files) {
	const tree = $("#file-tree");
	tree.empty();

	if (!files.length) {
		tree.html(`<div class="udt-tree-item">No matching files found</div>`);
		return;
	}

	files.forEach(file => {
		const safe_path = escape_html(file.path || "");
		tree.append(`
			<div class="udt-tree-item real-file" data-path="${safe_path}">
				<span class="udt-tree-icon">${get_file_icon(file.extension)}</span>
				<span class="udt-file-name" title="${safe_path}">${safe_path}</span>
			</div>
		`);
	});
}

function flatten_tree(nodes) {
	let files = [];

	(nodes || []).forEach(node => {
		const is_folder = node.is_folder || node.type === "folder";

		if (is_folder) {
			files = files.concat(flatten_tree(node.children || []));
		} else {
			files.push(node);
		}
	});

	return files;
}

function open_file(path) {
	if (!udt_current_app || !path) return;

	if (udt_open_tabs[path]) {
		switch_tab(path);
		return;
	}

	frappe.call({
		method: "upande_dev_tools.api.code_editor.read_file",
		args: {
			app: udt_current_app,
			path: path
		},
		callback: function(r) {
			const file = r.message;

			udt_open_tabs[file.path] = {
				...file,
				original_content: file.content || "",
				content: file.content || "",
				dirty: false,
				view_state: null
			};

			switch_tab(file.path);
			log_activity("📄 Opened file: " + file.path);
		}
	});
}

function switch_tab(path) {
	const tab = udt_open_tabs[path];
	if (!tab || !udt_editor) return;

	if (udt_active_tab && udt_open_tabs[udt_active_tab] && udt_active_tab !== path) {
		udt_open_tabs[udt_active_tab].view_state = udt_editor.saveViewState();
		udt_open_tabs[udt_active_tab].content = udt_editor.getValue();
	}

	udt_active_tab = path;
	udt_current_file = tab;

	udt_is_switching_tab = true;

	udt_editor.setValue(tab.content || "");
	monaco.editor.setModelLanguage(
		udt_editor.getModel(),
		tab.language || "plaintext"
	);

	if (tab.view_state) {
		udt_editor.restoreViewState(tab.view_state);
	}

	udt_is_switching_tab = false;

	$("#save-btn").prop("disabled", !tab.dirty);
	udt_editor.focus();
	update_open_file_ui(tab);
}


function close_tab(path) {
	if (!udt_open_tabs[path]) return;

	const tab = udt_open_tabs[path];

	if (tab.dirty && !confirm(`Close ${tab.file_name} without saving?`)) {
		return;
	}

	delete udt_open_tabs[path];

	const remaining = Object.keys(udt_open_tabs);

	if (udt_active_tab === path) {
		if (remaining.length) {
			switch_tab(remaining[remaining.length - 1]);
		} else {
			udt_active_tab = null;
			udt_current_file = null;
			reset_editor_state();
		}
	} else {
		render_tabs();
		render_open_editors();
	}
}

function save_current_file() {
	if (!udt_active_tab || !udt_open_tabs[udt_active_tab]) return;

	const tab = udt_open_tabs[udt_active_tab];
	tab.content = udt_editor.getValue();

	frappe.call({
		method: "upande_dev_tools.api.code_editor.write_file",
		args: {
			app: udt_current_app,
			path: tab.path,
			content: tab.content
		},
		callback: function(r) {
			tab.original_content = tab.content;
			tab.dirty = false;
			$("#save-btn").prop("disabled", true);
			render_tabs();
			render_open_editors();
			log_activity("💾 Saved file: " + tab.path);
			frappe.show_alert({ message: "File saved successfully", indicator: "green" });
		}
	});
}

function update_open_file_ui(file) {
	render_tabs();
	render_open_editors();

	$("#breadcrumb").text(`${file.app} › ${file.path}`);

	$(".real-file").removeClass("active");
	$(`.real-file[data-path="${css_escape(file.path)}"]`).addClass("active");

	$("#info-file").text(file.file_name);
	$("#info-language").text(file.language);
	$("#info-size").text(format_bytes((file.content || "").length));

	$("#status-file").text(file.file_name);
	$("#status-language").text(file.language);
	$("#terminal-body").html(
		`Opened: ${escape_html(file.path)}<br>` +
		`Language: ${escape_html(file.language)}<br>` +
		`Size: ${format_bytes((file.content || "").length)}`
	);
}

function render_tabs() {
	const tabbar = $(".udt-tabbar");
	tabbar.empty();

	const paths = Object.keys(udt_open_tabs);

	if (!paths.length) {
		tabbar.html(`<div class="udt-tab" id="current-tab">No file opened</div>`);
		return;
	}

	paths.forEach(path => {
		const tab = udt_open_tabs[path];
		const active = path === udt_active_tab ? "active" : "";
		const dirty = tab.dirty ? "● " : "";
		const icon = get_file_icon(tab.extension);

		tabbar.append(`
			<div class="udt-tab ${active}" data-path="${escape_html(path)}">
				<span>${icon}</span>
				<span>${dirty}${escape_html(tab.file_name)}</span>
				<span class="udt-tab-close" data-path="${escape_html(path)}">×</span>
			</div>
		`);
	});
}

function render_open_editors() {
	const paths = Object.keys(udt_open_tabs);

	$("#open-count").text(paths.length);

	if (!paths.length) {
		$("#open-editors").html(`<div class="udt-tree-item">No file opened</div>`);
		return;
	}

	$("#open-editors").empty();

	paths.forEach(path => {
		const tab = udt_open_tabs[path];
		const active = path === udt_active_tab ? "active" : "";
		const dirty = tab.dirty ? "● " : "";
		const icon = get_file_icon(tab.extension);

		$("#open-editors").append(`
			<div class="udt-tree-item open-editor-item ${active}" data-path="${escape_html(path)}">
				<span>${icon}</span>
				<span class="udt-file-name">${dirty}${escape_html(tab.file_name)}</span>
			</div>
		`);
	});
}

function reset_editor_state() {
	$(".udt-tabbar").html(`<div class="udt-tab" id="current-tab">No file opened</div>`);
	$("#breadcrumb").text("Select a file from Explorer");
	$("#open-count").text("0");
	$("#open-editors").html(`<div class="udt-tree-item">No file opened</div>`);
	$("#info-file").text("-");
	$("#info-language").text("-");
	$("#info-size").text("-");
	$("#status-file").text("No file");
	$("#status-language").text("Plain Text");
	$("#save-btn").prop("disabled", true);

	if (udt_editor) {
		udt_editor.setValue("# Select a file from Explorer\n");
		monaco.editor.setModelLanguage(udt_editor.getModel(), "plaintext");
	}
}

function log_activity(message) {
	const now = frappe.datetime.now_time();
	$("#activity-log").prepend(`
		<div class="udt-activity-item">${escape_html(now)} — ${escape_html(message)}</div>
	`);
}

function icon_img(name) {
	return `<img class="udt-icon" src="/assets/upande_dev_tools/icons/material/${name}.svg">`;
}

function get_file_icon(ext) {
	const icons = {
		".py": "python",
		".js": "javascript",
		".jsx": "react",
		".ts": "typescript",
		".tsx": "react_ts",
		".json": "json",
		".html": "html",
		".css": "css",
		".scss": "sass",
		".md": "markdown",
		".yml": "yaml",
		".yaml": "yaml",
		".toml": "settings",
		".c": "c",
		".h": "h",
		".cpp": "cpp",
		".cc": "cpp",
		".hpp": "hpp",
		".java": "java",
		".php": "php",
		".rb": "ruby",
		".go": "go",
		".rs": "rust",
		".r": "r",
		".sql": "database",
		".sh": "console",
		".xml": "xml",
		".dockerfile": "docker"
	};

	return icon_img(icons[ext] || "file");
}

function format_bytes(bytes) {
	if (!bytes) return "0 B";
	if (bytes < 1024) return bytes + " B";
	return (bytes / 1024).toFixed(2) + " KB";
}

function escape_html(value) {
	return String(value || "")
		.replaceAll("&", "&amp;")
		.replaceAll("<", "&lt;")
		.replaceAll(">", "&gt;")
		.replaceAll('"', "&quot;")
		.replaceAll("'", "&#039;");
}

function css_escape(value) {
	if (window.CSS && CSS.escape) {
		return CSS.escape(value);
	}
	return String(value || "").replace(/"/g, '\\"');
}
