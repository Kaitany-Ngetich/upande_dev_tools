(function () {
  "use strict";
  const API = "upande_dev_tools.api.v2.code_snapshots.";
  const NONE = "__none__", OTHER = "__other__";
  const VIEWS = ["overview", "days", "snapshots", "runs"];
  const d30 = PH.date.preset("30d");
  const st = PH.state({ view: "overview", from: d30[0], to: d30[1], source: "", app: "", kind: "", q: "", all: "", sort: "snapshot_time:1", page: 0 });
  const n = PH.fmt.num;
  let data = null, seq = 0, snaps = null, snapSeq = 0, runs = null, runSeq = 0;
  const PAGE = 50;

  const mb = (b) => (b / 1048576).toFixed(b >= 10485760 ? 0 : 1);
  const size = (b) => (b >= 1048576 ? mb(b) + " MB" : b >= 1024 ? (b / 1024).toFixed(b >= 10240 ? 0 : 1) + " KB" : n(b) + " B");
  const when = (v) => (v ? PH.fmt.date(String(v).slice(0, 10)) + " " + String(v).slice(11, 16) : "—");
  const ago = (h) => (h == null ? "never" : h < 1 ? Math.max(1, Math.round(h * 60)) + " min ago" : h < 48 ? Math.round(h) + " h ago" : Math.round(h / 24) + " days ago");
  const appLabel = (a) => (a === NONE ? "No app recorded" : a === OTHER ? "Other apps" : a || "No app recorded");
  const KIND = { DocType: "DocType", "Server Script": "Server Script", "Client Script": "Client Script" };

  PH.bindSelect("#f-source", st, "source");
  PH.bindSelect("#f-app", st, "app");
  PH.bindSelect("#f-kind", st, "kind");
  PH.bindSearch("#f-q", st, "q");
  // picking a preset or a date leaves "All time"; the pills only show a preset while a range is active
  const rangeState = { get: st.get, on: st.on, set: (patch, o) => st.set({ ...patch, all: "" }, o) };
  PH.dateRange({ pills: "#f-preset", from: "#f-from", to: "#f-to", state: rangeState });
  PH.$("#f-all").addEventListener("click", () => st.set({ all: st.get("all") ? "" : "1" }));
  const paintAll = () => {
    const on = !!st.get("all");
    PH.$("#f-all button").classList.toggle("is-on", on);
    if (on) PH.$$("#f-preset button").forEach((b) => b.classList.remove("is-on"));
    PH.$("#f-from").disabled = PH.$("#f-to").disabled = on;
  };
  st.on(paintAll);
  paintAll();
  PH.$("#f-sort").value = st.get("sort");
  PH.$("#f-sort").addEventListener("change", (e) => st.set({ sort: e.target.value, page: 0 }));
  PH.$("#tabs").addEventListener("click", (e) => {
    const b = e.target.closest("[data-view]");
    if (b) st.set({ view: b.dataset.view });
  });

  function view() { const v = st.get("view"); return VIEWS.includes(v) ? v : "overview"; }
  function paintView() {
    const v = view();
    PH.$$("#tabs .ph-tab").forEach((b) => b.classList.toggle("is-on", b.dataset.view === v));
    VIEWS.forEach((x) => { PH.$("#view-" + x).hidden = x !== v; });
    const rows = csvRows(v);
    PH.$("#export").disabled = !rows || !rows.length;
    PH.$("#export").title = v === "overview" ? "Open By day, Snapshots or Backup runs to export a table" : "Download this table as CSV";
  }
  const filterArgs = () => { const s = st.get(); return { from_date: s.from, to_date: s.to, all_dates: s.all, source_type: s.source, app: s.app, kind: s.kind, search: s.q }; };

  st.on((s, changed) => {
    if (changed.length === 1 && changed[0] === "view") { paintView(); ensureView(); return; }
    if (changed.length === 1 && changed[0] === "sort") { PH.$("#f-sort").value = s.sort; loadSnaps(); return; }
    if (changed.length === 1 && changed[0] === "page") { loadSnaps(); return; }
    if (changed.some((k) => k !== "page" && k !== "sort" && k !== "view") && s.page !== 0) { st.set({ page: 0 }, { silent: true }); }
    snaps = null; runs = null;
    load();
  });

  /* ---- tables ---- */
  const tDays = PH.table("#t-days", {
    rows: [], compact: true, pageSize: 31, empty: "No days in this range", sort: { key: "day", dir: "desc" },
    onRowClick: (r) => { if (r.snapshots) st.set({ from: r.day, to: r.day, view: "snapshots" }); },
    columns: [
      { key: "day", label: "Day", format: (v) => PH.fmt.date(v) },
      { key: "snapshots", label: "Snapshots", num: true, format: (v) => n(v) },
      { key: "new", label: "First copies", num: true, format: (v) => n(v) },
      { key: "changed", label: "Changes", num: true, format: (v) => n(v) },
      { key: "bytes", label: "Size", num: true, format: (v) => size(v) },
      { key: "runs", label: "Backup runs", num: true, format: (v) => n(v) },
      { key: "saved_runs", label: "Runs that saved", num: true, format: (v) => n(v) },
      { key: "failed", label: "Failed", num: true, format: (v) => n(v) },
    ],
  });
  const tSnaps = PH.table("#t-snapshots", {
    rows: [], compact: true, pageSize: false, empty: "No snapshots match these filters",
    emptyText: "Try a wider date range or clear a filter.",
    onRowClick: (r) => openSnapshot(r.name),
    columns: [
      { key: "snapshot_time", label: "Saved", sortable: false, format: (v) => when(v) },
      { key: "document_name", label: "Document", sortable: false, cls: "ph-strong" },
      { key: "source_type", label: "Kind", sortable: false },
      { key: "app", label: "App / Module", sortable: false, format: (v, r) => v || r.module || "—" },
      { key: "changed_flag", label: "Changed", sortable: false, format: (v) => (v ? "Yes" : "No"), title: "Marked as changed since the last backup when it was saved" },
      { key: "version", label: "Version", num: true, sortable: false, format: (v) => (v === 1 ? "1 (first)" : n(v)) },
      { key: "bytes", label: "Size", num: true, sortable: false, format: (v) => size(v) },
      { key: "trigger_by", label: "Saved by", sortable: false, format: (v) => v || "—" },
    ],
  });
  const tRuns = PH.table("#t-runs", {
    rows: [], compact: true, pageSize: 25, empty: "No backup runs in this range",
    columns: [
      { key: "activity_time", label: "When", sortable: false, format: (v) => when(v) },
      { key: "title", label: "Run", sortable: false, cls: "ph-strong" },
      { key: "status", label: "Result", sortable: false, html: (v) => '<span class="ph-badge ph-badge--' + (v === "Success" ? "good" : v === "Error" ? "bad" : "warn") + '">' + PH.esc(v === "Success" ? "Fine" : v || "—") + "</span>" },
      { key: "description", label: "Note", sortable: false, cls: "is-wrap", format: (v) => v || "—" },
    ],
  });

  /* ---- load: overview ---- */
  function load() {
    const my = ++seq;
    PH.loadingKpis("#kpis", true);
    paintView();
    return PH.call(API + "get_overview", filterArgs())
      .then((m) => { if (my !== seq) return; data = m; render(); PH.markUpdated(); ensureView(); })
      .catch((e) => {
        if (my !== seq) return;
        data = null;
        PH.loadingKpis("#kpis", false);
        ["#c-count", "#c-size", "#by-source", "#by-app", "#by-trigger", "#t-days"].forEach((x) => PH.error(x, e.message, () => load()));
        PH.set("#settings", ""); PH.set("#retention", ""); PH.set("#notes", "");
        paintView();
      });
  }
  function ensureView() {
    if (view() === "snapshots" && !snaps) loadSnaps();
    if (view() === "runs" && !runs) loadRuns();
  }

  function loadSnaps() {
    const my = ++snapSeq, s = st.get(), [sort, desc] = s.sort.split(":");
    PH.skeleton("#t-snapshots", "table", 6);
    return PH.call(API + "get_snapshots", { ...filterArgs(), sort, desc, start: s.page * PAGE, limit: PAGE })
      .then((m) => { if (my !== snapSeq) return; snaps = m; tSnaps.update(m.rows); paintPager(); PH.text("#tc-snapshots", n(m.total)); paintView(); })
      .catch((e) => { if (my !== snapSeq) return; snaps = null; PH.error("#t-snapshots", e.message, () => loadSnaps()); PH.set("#pager", ""); });
  }
  function paintPager() {
    const m = snaps, s = st.get(), p = s.page;
    if (!m || !m.total) { PH.set("#pager", ""); return; }
    const from = p * PAGE + 1, to = Math.min(m.total, (p + 1) * PAGE);
    PH.set("#pager", `<span>${n(from)}–${n(to)} of ${n(m.total)}</span><button class="ph-btn ph-btn--sm" data-pg="-1" ${p <= 0 ? "disabled" : ""}>Previous</button><button class="ph-btn ph-btn--sm" data-pg="1" ${to >= m.total ? "disabled" : ""}>Next</button>`);
  }
  PH.$("#pager").addEventListener("click", (e) => {
    const b = e.target.closest("[data-pg]");
    if (b && !b.disabled) st.set({ page: Math.max(0, st.get("page") + +b.dataset.pg) });
  });

  function loadRuns() {
    const my = ++runSeq, s = st.get();
    PH.skeleton("#t-runs", "table", 5);
    return PH.call(API + "get_runs", { from_date: s.from, to_date: s.to, all_dates: s.all, limit: 200 })
      .then((m) => {
        if (my !== runSeq) return;
        runs = m; tRuns.update(m.rows); PH.text("#tc-runs", n(m.total)); paintView();
      })
      .catch((e) => { if (my !== runSeq) return; runs = null; PH.error("#t-runs", e.message, () => loadRuns()); });
  }

  /* ---- render ---- */
  function bars(sel, rows, labelOf, onClick) {
    const max = Math.max(1, ...rows.map((x) => x.snapshots));
    PH.set(sel, rows.map((x, i) =>
      `<div class="cs-bar${onClick ? " is-link" : ""}" data-i="${i}" ${onClick ? 'style="cursor:pointer"' : ""} title="${PH.esc(labelOf(x))}: ${PH.esc(n(x.snapshots))} snapshots, ${PH.esc(size(x.bytes))}"><span class="ph-truncate">${PH.esc(labelOf(x))}</span><b>${n(x.snapshots)}</b><span>${size(x.bytes)}</span><div class="ph-progress"><i class="good" style="width:${(100 * x.snapshots) / max}%"></i></div></div>`
    ).join("") || '<div class="ph-empty">Nothing saved in this range</div>');
    if (onClick) PH.$$(".cs-bar", PH.$(sel)).forEach((el) => el.addEventListener("click", () => onClick(rows[+el.dataset.i])));
  }
  const kv = (rows) => rows.map(([k, v]) => `<dt>${PH.esc(k)}</dt><dd>${PH.esc(v)}</dd>`).join("");
  const yn = (b) => (b ? "Yes" : "No");

  function render() {
    const d = data, s = st.get(), k = d.kpis, f = d.freshness, se = d.settings, rt = d.retention, ru = d.runs;
    PH.options("#f-app", [{ value: "", label: "All apps" }].concat((d.options.apps || []).map((a) => ({ value: a, label: a })), d.options.has_unassigned ? [{ value: NONE, label: "No app recorded" }] : []), s.app);
    const scope = [s.source, s.app && appLabel(s.app), s.kind === "new" ? "first copies" : s.kind === "changed" ? "changes" : "", s.q && `"${s.q}"`].filter(Boolean);
    PH.text("#sub", (k.snapshots ? PH.fmt.plural(k.snapshots, "snapshot") + " · " + size(k.size_bytes) : "No snapshots") + " · " + (d.all_dates ? "all dates" : PH.date.label(s.from, s.to)) + (scope.length ? " · " + scope.join(" · ") : ""));

    const hrs = f.last_check_age_hours;
    const lastAge = hrs == null ? ["—", ""] : hrs < 1 ? [Math.max(1, Math.round(hrs * 60)), "min ago"] : hrs < 48 ? [Math.round(hrs), "h ago"] : [Math.round(hrs / 24), "days ago"];
    PH.kpis("#kpis", [
      { label: "Snapshots saved", value: k.snapshots, unit: PH.fmt.plural(k.documents, "document"), dark: true, title: "Saved versions of code in this range" },
      { label: "Size of code text", value: k.size_bytes >= 1048576 ? mb(k.size_bytes) : Math.round(k.size_bytes / 1024), suffix: k.size_bytes >= 1048576 ? "MB" : "KB", unit: "kept twice in the database", title: "Length of the saved text. The scheduler keeps a second copy of it in another column." },
      { label: "Changes saved", value: k.changed, unit: n(k.first_recorded) + " first copies", title: "A change is a second or later version of the same document" },
      { label: "Last check", value: lastAge[0], suffix: lastAge[1], unit: "planned every " + f.interval_hours + " h", title: f.text },
      { label: "Failures", value: ru.failed, unit: PH.fmt.plural(ru.runs, "run") + " in range", title: "Backup runs that recorded an error. Not narrowed by the kind, app or search filters." },
    ]);

    const notes = [];
    notes.push(`<div class="ph-notice ph-notice--${f.state === "good" ? "good" : f.state === "none" ? "signal" : "warn"}">${PH.esc(f.text)} Last check ${PH.esc(when(f.last_check))} (${PH.esc(ago(f.last_check_age_hours))}); last time code changed and was saved ${PH.esc(when(f.last_snapshot))} (${PH.esc(ago(f.last_snapshot_age_hours))}). Planned every ${f.interval_hours} h.</div>`);
    const days = Math.max(1, d.by_day.length), expected = (24 / f.interval_hours) * days;
    if (ru.runs > expected * 3) notes.push(`<div class="ph-notice ph-notice--warn">${n(ru.runs)} backup checks were recorded in these ${days} days (about ${n(Math.round(ru.runs / days))} a day), against roughly ${n(Math.round(24 / f.interval_hours))} a day for an every-${f.interval_hours}-hour schedule. Checks that find nothing new save nothing, so this only affects how often the scheduler looks.</div>`);
    if (rt.past_snapshots > 0) notes.push(`<div class="ph-notice ph-notice--signal">${n(rt.past_snapshots)} snapshots (${size(rt.past_bytes)} of code text) are older than the ${rt.retention_days}-day retention. Nothing in the app removes old snapshots yet, so they stay until someone clears them.</div>`);
    PH.set("#notes", notes.join(""));

    const bd = d.by_day;
    const labels = bd.map((x) => PH.fmt.date(x.day, true));
    PH.chart("#c-count", {
      type: "line", labels,
      series: [{ label: "Snapshots", data: bd.map((x) => x.snapshots), color: PH.statusColor.good, fill: true }],
      onClick: (i) => { const x = bd[i]; if (x && x.snapshots) st.set({ from: x.day, to: x.day, view: "snapshots" }); },
    });
    PH.chart("#c-size", {
      type: "line", labels,
      series: [{ label: "MB of code text", data: bd.map((x) => +(x.bytes / 1048576).toFixed(2)), color: PH.statusColor.signal, fill: true }],
      yFormat: (v) => v + " MB",
    });
    bars("#by-source", d.by_source, (x) => x.source_type, (x) => st.set({ source: x.source_type }));
    bars("#by-app", d.by_app, (x) => appLabel(x.app) + (x.app === OTHER ? " (" + x.count_apps + ")" : ""), (x) => { if (x.app !== OTHER) st.set({ app: x.app }); });
    bars("#by-trigger", d.by_trigger, (x) => x.trigger, null);

    PH.set("#settings", kv([
      ["Backups switched on", yn(se.enabled)],
      ["Planned every", PH.fmt.plural(se.interval_hours, "hour")],
      ["Keep for", PH.fmt.plural(se.retention_days, "day")],
      ["Includes DocTypes", yn(se.include_doctypes)],
      ["Includes Server Scripts", yn(se.include_server_scripts)],
      ["Includes Client Scripts", yn(se.include_client_scripts)],
      ["Settings saved", se.values_saved ? "Yes" : "Not yet, showing the built-in defaults"],
    ]));
    PH.set("#retention", kv([
      ["Snapshots on record", n(rt.snapshots_all_dates) + " · " + size(rt.size_all_dates_bytes)],
      ["Oldest", rt.oldest ? when(rt.oldest) + " (" + Math.round(rt.oldest_age_days) + " days old)" : "—"],
      ["Retention cut-off", when(rt.cutoff) + " (" + rt.retention_days + " days back)"],
      ["Older than the cut-off", n(rt.past_snapshots) + " · " + size(rt.past_bytes)],
      ["Within the cut-off", n(rt.snapshots_all_dates - rt.past_snapshots) + " · " + size(rt.size_all_dates_bytes - rt.past_bytes)],
      ["Automatic clean-up", "None found in the app"],
    ]));

    tDays.update(bd);
    PH.text("#tc-runs", n(ru.runs));
    if (snaps) PH.text("#tc-snapshots", n(snaps.total)); else PH.text("#tc-snapshots", n(k.snapshots));
    paintView();
  }

  /* ---- drill-down: what is inside one snapshot ---- */
  const chips = (a) => (a && a.length ? '<div class="cs-diff">' + a.map((x) => `<span class="cs-chip">${PH.esc(x)}</span>`).join("") + "</div>" : '<span class="ph-muted">none</span>');
  function openSnapshot(name) {
    const body = document.createElement("div");
    PH.skeleton(body, "table", 5);
    const m = PH.modal({ title: "Snapshot " + name, sub: "What was saved", body, size: "lg" });
    PH.call(API + "get_snapshot", { name }).then((d) => {
      const s = d.snapshot, sm = d.summary, ch = sm.changes;
      m.setTitle && m.setTitle(s.document_name);
      let h = `<div class="ph-strong">${PH.esc(s.document_name)}</div><div class="ph-muted ph-mb">${PH.esc(s.source_type)} · ${PH.esc(s.app || "no app recorded")}${s.module ? " · " + PH.esc(s.module) : ""}</div>`;
      h += '<dl class="ph-kv">' + kv([
        ["Saved", when(s.snapshot_time)],
        ["Version", s.version + " of " + s.versions_total + (s.version === 1 ? " (first saved copy)" : "")],
        ["Size", size(s.bytes)],
        ["Saved by", s.trigger || "—"],
        ["Fingerprint", s.content_hash || "—"],
      ]) + "</dl>";
      h += '<div class="cs-sec">What it contains</div><dl class="ph-kv">' + kv(Object.entries(sm.facts || {}).map(([k, v]) => [k.charAt(0).toUpperCase() + k.slice(1), typeof v === "boolean" ? yn(v) : v == null || v === "" ? "—" : String(v)])) + "</dl>";
      if (sm.unreadable) h += '<div class="ph-notice ph-notice--warn ph-mt">The saved text could not be read as JSON, so no summary is available.</div>';
      if (ch) {
        h += `<div class="cs-sec">What changed since version ${s.version - 1}${s.previous ? " (" + PH.esc(when(s.previous.snapshot_time)) + ")" : ""}</div>`;
        if (ch.too_large) h += '<div class="ph-muted">Too large to compare here.</div>';
        else if (sm.kind === "DocType") {
          h += `<div class="ph-mb">${n(ch.counts.added)} fields added, ${n(ch.counts.removed)} removed, ${n(ch.counts.changed)} changed</div>`;
          h += '<div class="ph-muted">Added</div>' + chips(ch.fields_added) + '<div class="ph-muted ph-mt">Removed</div>' + chips(ch.fields_removed) + '<div class="ph-muted ph-mt">Changed</div>' + chips(ch.fields_changed);
          h += '<div class="ph-muted ph-mt">Other settings changed</div>' + chips(ch.settings_changed);
        } else {
          h += `<div class="ph-mb">${n(ch.lines_added)} lines added, ${n(ch.lines_removed)} lines removed</div><div class="ph-muted">Other settings changed</div>` + chips(ch.settings_changed);
        }
      } else if (s.version === 1) h += '<div class="cs-sec">What changed</div><div class="ph-muted">This is the first saved copy, so there is nothing earlier to compare with.</div>';
      h += '<div class="cs-sec">Other saved versions of this document</div><div id="cs-hist"></div>';
      if (d.can_open_in_desk) h += `<div class="ph-mt"><a class="ph-link" target="_blank" rel="noopener" href="/app/code-backup-snapshot/${encodeURIComponent(s.name)}">Open in Desk</a></div>`;
      body.innerHTML = h;
      PH.table(body.querySelector("#cs-hist"), {
        rows: d.history, compact: true, pageSize: 10, sort: { key: "snapshot_time", dir: "desc" },
        onRowClick: (r) => { if (r.name !== s.name) { m.close(); openSnapshot(r.name); } },
        rowClass: (r) => (r.name === s.name ? "is-on" : ""),
        columns: [
          { key: "snapshot_time", label: "Saved", format: (v) => when(v) },
          { key: "name", label: "Snapshot", cls: "ph-mono" },
          { key: "bytes", label: "Size", num: true, format: (v) => size(v) },
        ],
      });
    }).catch((e) => PH.error(body, e.message, () => { m.close(); openSnapshot(name); }));
  }

  /* ---- CSV ---- */
  const CSVS = {
    days: { file: "code_snapshots_by_day", rows: () => data && data.by_day, cols: [["day", "Day"], ["snapshots", "Snapshots"], ["new", "First copies"], ["changed", "Changes"], ["bytes", "Size (bytes)"], ["runs", "Backup runs"], ["saved_runs", "Runs that saved"], ["failed", "Failed"]] },
    snapshots: { file: "code_snapshots", rows: () => snaps && snaps.rows, cols: [["name", "Snapshot"], ["snapshot_time", "Saved"], ["source_type", "Kind"], ["document_name", "Document"], ["app", "App"], ["module", "Module"], ["changed_flag", "Changed since last backup"], ["version", "Version"], ["bytes", "Size (bytes)"], ["trigger_by", "Saved by"]] },
    runs: { file: "code_backup_runs", rows: () => runs && runs.rows, cols: [["activity_time", "When"], ["title", "Run"], ["status", "Result"], ["description", "Note"]] },
  };
  function csvRows(v) { const c = CSVS[v]; return c ? c.rows() : null; }
  function exportView() {
    const v = view(), c = CSVS[v], rows = csvRows(v), s = st.get();
    if (!c || !rows || !rows.length) return;
    if (v === "snapshots" && snaps && snaps.total > rows.length) {
      const [sort, desc] = s.sort.split(":");
      PH.call(API + "get_snapshots", { ...filterArgs(), sort, desc, start: 0, limit: 200 }).then((m) => {
        PH.csv(c.file + (s.all ? "_all" : "_" + s.from + "_" + s.to) + ".csv", m.rows, c.cols.map(([key, label]) => ({ key, label })));
        if (m.total > m.rows.length) PH.toast("Exported the first " + n(m.rows.length) + " of " + n(m.total) + " snapshots. Narrow the filters to export the rest.");
      });
      return;
    }
    PH.csv(c.file + (s.all ? "_all" : "_" + s.from + "_" + s.to) + ".csv", rows, c.cols.map(([key, label]) => ({ key, label })));
  }
  PH.$("#export").addEventListener("click", exportView);
  PH.$$("[data-csv]").forEach((b) => b.addEventListener("click", exportView));

  DevKeys.init({ title: "Code Snapshots", list: { root: "#ph-main", items: () => PH.$$("#ph-main tbody tr.is-link") } });

  PH.onRefresh(() => { snaps = null; runs = null; load(); });
  PH.ready(() => { paintView(); load(); });
})();
