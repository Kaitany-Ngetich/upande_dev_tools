(function () {
  "use strict";
  const API = "upande_dev_tools.api.v2.activity_log.";
  const PAGE = 50;
  const d30 = PH.date.preset("30d");
  const n = PH.fmt.num;
  const qs = new URLSearchParams(location.search);
  const st = PH.state({
    tab: "activity", all: "", from: d30[0], to: d30[1], user: "", type: "", status: ["Success", "Warning", "Error", "Info"].includes(qs.get("status")) ? qs.get("status") : "", source: "",
    q: "", sort: "newest", issue: "", dstatus: "", doctype: "",
  });
  const ST = { Success: "good", Warning: "warn", Error: "bad", Info: "outline" };
  const DST = { New: "warn", Reviewed: "good", Ignored: "outline" };
  let sum = null, dsum = null, canDiffs = false;
  let seqS = 0, seqL = 0, seqDS = 0, seqDL = 0;
  const NONE = "__none__";

  PH.bindSelect("#f-user", st, "user");
  PH.bindSelect("#f-type", st, "type");
  PH.bindSelect("#f-status", st, "status");
  PH.bindSelect("#f-source", st, "source");
  PH.bindSelect("#f-sort", st, "sort");
  PH.bindSelect("#f-issue", st, "issue");
  PH.bindSelect("#f-dstatus", st, "dstatus");
  PH.bindSelect("#f-doctype", st, "doctype");
  PH.bindSearch("#f-search", st, "q");
  // Picking a day range leaves "All time"; both changes go out as one update.
  PH.$("#f-preset").addEventListener("click", (e) => {
    const p = e.target.closest("button[data-value]") && PH.date.preset(e.target.closest("button").dataset.value);
    if (p) st.set({ all: "", from: p[0], to: p[1] });
  });
  ["#f-from", "#f-to"].forEach((sel) => PH.$(sel).addEventListener("change", () => {
    const a = PH.$("#f-from").value, b = PH.$("#f-to").value;
    if (a && b) st.set({ all: "", from: a < b ? a : b, to: a < b ? b : a });
  }));
  PH.$("#f-all").addEventListener("click", () => st.set({ all: st.get("all") ? "" : "1" }));
  PH.dateRange({ pills: "#f-preset", from: "#f-from", to: "#f-to", state: st });
  PH.$("#tabs").addEventListener("click", (e) => {
    const b = e.target.closest("[data-tab]");
    if (b) st.set({ tab: b.dataset.tab });
  });

  const tab = () => (st.get("tab") === "diffs" && canDiffs ? "diffs" : "activity");
  let pg = 0;
  const page = () => pg;

  function aArgs() {
    const s = st.get();
    return { all_time: s.all, from_date: s.from, to_date: s.to, user: s.user, activity_type: s.type, status: s.status, source: s.source, search: s.q, sort: s.sort };
  }
  function dArgs() {
    const s = st.get();
    return { all_time: s.all, from_date: s.from, to_date: s.to, issue_type: s.issue, status: s.dstatus, doctype_name: s.doctype, search: s.q };
  }

  function paintTab() {
    const t = tab();
    PH.$$("#tabs .ph-tab").forEach((b) => b.classList.toggle("is-on", b.dataset.tab === t));
    PH.$("#view-activity").hidden = t !== "activity";
    PH.$("#view-diffs").hidden = t !== "diffs";
    PH.$$(".al-a").forEach((x) => { x.hidden = t !== "activity"; });
    PH.$$(".al-d").forEach((x) => { x.hidden = t !== "diffs"; });
    PH.$("#tab-diffs").hidden = !canDiffs;
    if (st.get("all")) PH.$$("#f-preset button").forEach((b) => b.classList.remove("is-on"));
    PH.$("#f-all button").classList.toggle("is-on", !!st.get("all"));
    PH.$("#f-from").disabled = PH.$("#f-to").disabled = !!st.get("all");
    PH.$("#f-search").placeholder = t === "diffs" ? "Search doctype or field name" : "Search title, source, person";
  }

  st.on((s, changed) => {
    paintTab();
    const only = (k) => changed.length === 1 && changed[0] === k;
    if (only("tab")) { pg = 0; refreshCurrent(); return; }
    if (only("sort")) { pg = 0; loadList(); return; }
    pg = 0;
    refreshCurrent();
  });

  function refreshCurrent() {
    if (tab() === "diffs") { if (!dsum) loadDiffSummary(); else renderDiffSummary(); loadDiffList(); paintExport(); }
    else { loadSummary(); loadList(); }
  }
  function reloadAll() { tab() === "diffs" ? (loadDiffSummary(), loadDiffList()) : (loadSummary(), loadList()); }

  PH.kpiSkeleton("#kpis", ["Entries", "Needs a look", "People", "Per busy day", "Last entry"]);

  /* ---------------- bars ---------------- */
  function bars(sel, rows, field, activeKey) {
    const max = Math.max(1, ...rows.map((x) => x.count));
    const el = PH.$(sel);
    el.innerHTML = rows.map((x, i) => {
      const other = x.key === "__other__";
      const label = x.name && x.name !== x.key ? x.name + " (" + x.key + ")" : x.label;
      return `<div class="al-bar${activeKey && activeKey === x.key ? " is-on" : ""}" ${other ? "" : `data-f="${PH.esc(field)}" data-v="${PH.esc(x.key)}"`} title="${PH.esc(label)}: ${n(x.count)}"><span>${PH.esc(label)}</span><b>${n(x.count)}</b><div class="ph-progress"><i class="${x.key === "Error" ? "bad" : x.key === "Warning" ? "warn" : "good"}" style="width:${(100 * x.count) / max}%"></i></div></div>`;
    }).join("") || '<div class="ph-empty">Nothing recorded in this range</div>';
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest(".al-bar[data-f]");
    if (!b) return;
    const k = b.dataset.f, cur = st.get(k);
    st.set({ [k]: cur === b.dataset.v ? "" : b.dataset.v });
  });

  /* ---------------- activity ---------------- */
  function loadSummary() {
    const my = ++seqS;
    PH.loadingKpis("#kpis", true);
    return PH.call(API + "get_activity_summary", aArgs())
      .then((m) => { if (my !== seqS) return; sum = m; canDiffs = !!m.can_see_differences; paintTab(); renderSummary(); PH.markUpdated(); })
      .catch((e) => {
        if (my !== seqS) return;
        PH.loadingKpis("#kpis", false);
        ["#c-trend", "#b-type", "#b-status", "#b-source", "#b-user"].forEach((x) => PH.error(x, e.message, () => loadSummary()));
      });
  }

  const rangeLabel = (r) => (r.all_time ? "All time" : PH.date.label(r.from, r.to));
  function who(v, name) { return v ? (name && name !== v ? name : v) : "Not recorded"; }

  function renderSummary() {
    const m = sum, t = m.totals, s = st.get();
    const o = m.options;
    PH.options("#f-user", [{ value: "", label: "Everyone" }].concat(o.users.map((u) => ({ value: u, label: o.user_names[u] && o.user_names[u] !== u ? o.user_names[u] + " (" + u + ")" : u })), [{ value: NONE, label: "Not recorded" }]), s.user);
    PH.options("#f-type", [{ value: "", label: "All kinds" }].concat(o.types.map((x) => ({ value: x, label: x }))), s.type);
    PH.options("#f-status", [{ value: "", label: "Any outcome" }].concat(["Error", "Warning", "Info", "Success"].map((x) => ({ value: x, label: x }))), s.status);
    PH.options("#f-source", [{ value: "", label: "All sources" }].concat(o.sources.map((x) => ({ value: x, label: x })), [{ value: NONE, label: "Not recorded" }]), s.source);
    const scope = [s.user && who(s.user === NONE ? "" : s.user, (o.user_names || {})[s.user]), s.type, s.status, s.source === NONE ? "No source" : s.source, s.q && "“" + s.q + "”"].filter(Boolean);
    PH.text("#sub", (t.entries ? PH.fmt.plural(t.entries, "entry", "entries") : "No entries") + " · " + rangeLabel(m.range) + (scope.length ? " · " + scope.join(" · ") : ""));
    PH.text("#tc-activity", n(t.entries));
    PH.kpis("#kpis", [
      { label: "Entries", value: t.entries, unit: PH.fmt.plural(t.active_days, "day") + " with activity", dark: true, title: "Rows of the Developer Activity Log that match every filter" },
      { label: "Needs a look", value: t.problems, unit: t.problems ? n(t.errors) + " errors, " + n(t.warnings) + " warn." : "all clear", title: "Entries whose outcome is Error or Warning", onClick: t.errors ? () => st.set({ status: "Error" }) : null },
      { label: "People", value: t.users, unit: "incl. automatic runs" },
      { label: "Per busy day", value: Math.round(t.avg_per_active_day), unit: "days with none skipped" },
      { label: "Last entry", value: t.last_at ? PH.fmt.ago ? PH.fmt.ago(t.last_at) : PH.fmt.datetime(t.last_at) : "—", unit: t.last_at ? PH.fmt.datetime(t.last_at) : "no entries" },
    ]);
    const notes = [];
    if (m.range.all_time) notes.push(`<div class="ph-notice">Counts and the log cover every entry ever recorded. The chart shows the last ${PH.esc(String(m.by_day.length))} days.</div>`);
    if (m.range.clamped) notes.push(`<div class="ph-notice ph-notice--signal">Ranges are limited to ${m.range.max_days} days. Showing ${PH.esc(PH.date.label(m.range.from, m.range.to))}.</div>`);
    PH.set("#notes", notes.join(""));
    bars("#b-type", m.by_type, "type", s.type);
    bars("#b-status", m.by_status, "status", s.status);
    bars("#b-source", m.by_source, "source", s.source);
    bars("#b-user", m.by_user.map((u) => ({ ...u, label: u.key === NONE ? "Not recorded" : u.label })), "user", s.user);
    const days = m.by_day;
    PH.chart("#c-trend", {
      type: "line", labels: days.map((x) => PH.fmt.date(x.date)),
      yFormat: (v) => (Number.isInteger(v) ? PH.fmt.num(v) : ""),
      series: [
        { label: "Entries", data: days.map((x) => x.total), color: PH.statusColor.good, fill: true },
        { label: "Errors and warnings", data: days.map((x) => x.errors + x.warnings), color: PH.statusColor.bad, fill: false },
      ],
      onClick: (i) => { const d = days[i]; if (d) st.set({ all: "", from: d.date, to: d.date }); },
    });
    paintExport();
  }

  const timeCol = { key: "activity_time", label: "When", format: (v) => (v ? PH.fmt.datetime(v) : "—") };
  const tLog = PH.table("#t-log", {
    columns: [
      timeCol,
      { key: "activity_type", label: "Kind", sortable: false },
      { key: "title", label: "What happened", cls: "is-strong is-wrap", sortable: false },
      { key: "status", label: "Outcome", sortable: false, html: (v) => `<span class="ph-badge ph-badge--${ST[v] || "outline"}">${PH.esc(v || "—")}</span>` },
      { key: "source", label: "Source", sortable: false, format: (v) => v || "—" },
      { key: "user_name", label: "Who", sortable: false, format: (v) => v || "Not recorded" },
    ],
    rows: [], compact: true, empty: "No entries match these filters", emptyText: "Widen the date range or clear a filter.",
    onRowClick: (r) => openEntry(r.name),
  });
  let logTotal = 0;
  function pager(sel, total, onPage) {
    const p = page(), from = total ? p * PAGE + 1 : 0, to = Math.min(total, p * PAGE + PAGE);
    const el = PH.$(sel);
    el.innerHTML = total > PAGE ? `<div class="ph-pager"><span>${n(from)}–${n(to)} of ${n(total)}</span><span class="ph-flex"><button class="ph-iconbtn ph-iconbtn--sm" data-pg="-1" ${p === 0 ? "disabled" : ""} aria-label="Previous page">${PH.icon("chevronLeft")}</button><button class="ph-iconbtn ph-iconbtn--sm" data-pg="1" ${to >= total ? "disabled" : ""} aria-label="Next page">${PH.icon("chevronRight")}</button></span></div>` : "";
    el.onclick = (e) => { const b = e.target.closest("[data-pg]"); if (b && !b.disabled) onPage(p + (+b.dataset.pg)); };
  }
  function loadList() {
    if (tab() !== "activity") return;
    const my = ++seqL;
    return PH.call(API + "get_activity_list", { ...aArgs(), start: page() * PAGE, limit: PAGE })
      .then((m) => {
        if (my !== seqL) return;
        logTotal = m.total;
        tLog.update(m.rows);
        pager("#p-log", m.total, (p) => { pg = p; loadList(); });
        PH.text("#log-meta", m.total ? n(m.total) + " matching entries · click one for the full detail" : "Click an entry for the full detail");
      })
      .catch((e) => { if (my === seqL) PH.error("#t-log", e.message, () => loadList()); });
  }

  function openEntry(name) {
    const body = document.createElement("div");
    PH.skeleton(body);
    const m = PH.modal({ title: "Activity entry", sub: name, body, size: "lg" });
    PH.call(API + "get_activity_entry", { name }).then((d) => {
      const e = d.entry;
      body.innerHTML = `<dl class="ph-kv">
        <dt>When</dt><dd>${PH.esc(PH.fmt.datetime(e.activity_time))}</dd>
        <dt>What happened</dt><dd class="ph-strong">${PH.esc(e.title || "—")}</dd>
        <dt>Outcome</dt><dd><span class="ph-badge ph-badge--${ST[e.status] || "outline"}">${PH.esc(e.status || "—")}</span></dd>
        <dt>Kind</dt><dd>${PH.esc(e.activity_type || "—")}</dd>
        <dt>Source</dt><dd>${PH.esc(e.source || "—")}</dd>
        <dt>Who</dt><dd>${PH.esc(e.user_name || "Not recorded")}${e.performed_by && e.user_name !== e.performed_by ? ' <span class="ph-muted">(' + PH.esc(e.performed_by) + ")</span>" : ""}</dd>
        ${e.reference_doctype && e.reference_name ? `<dt>About</dt><dd><a class="ph-link" target="_blank" rel="noopener" href="/app/${encodeURIComponent(e.reference_doctype.toLowerCase().replace(/ /g, "-"))}/${encodeURIComponent(e.reference_name)}">${PH.esc(e.reference_doctype)} ${PH.esc(e.reference_name)}</a></dd>` : ""}
        <dt>Record</dt><dd><a class="ph-link" target="_blank" rel="noopener" href="/app/developer-activity-log/${encodeURIComponent(e.name)}">${PH.esc(e.name)}</a></dd>
      </dl>
      <h4 class="ph-mt">Details</h4><pre class="al-pre">${PH.esc(e.description || "No further detail was recorded.")}</pre>`;
    }).catch((err) => PH.error(body, err.message, () => { m.close(); openEntry(name); }));
  }

  /* ---------------- field differences ---------------- */
  function loadDiffSummary() {
    const my = ++seqDS;
    PH.loadingKpis("#kpis", true);
    return PH.call(API + "get_difference_summary", dArgs())
      .then((m) => { if (my !== seqDS) return; dsum = m; renderDiffSummary(); PH.markUpdated(); })
      .catch((e) => {
        if (my !== seqDS) return;
        PH.loadingKpis("#kpis", false);
        ["#c-dtrend", "#d-issue", "#d-status", "#d-doctype"].forEach((x) => PH.error(x, e.message, () => loadDiffSummary()));
      });
  }
  const ISSUES = ["Missing in Local", "Missing in Live", "Different Type", "Different Property"];
  function renderDiffSummary() {
    if (tab() !== "diffs" || !dsum) return;
    const m = dsum, t = m.totals, s = st.get();
    PH.options("#f-issue", [{ value: "", label: "All kinds of difference" }].concat(ISSUES.map((x) => ({ value: x, label: x }))), s.issue);
    PH.options("#f-dstatus", [{ value: "", label: "Any review status" }].concat(["New", "Reviewed", "Ignored"].map((x) => ({ value: x, label: x }))), s.dstatus);
    PH.options("#f-doctype", [{ value: "", label: "All doctypes" }].concat(m.options.doctypes.map((x) => ({ value: x, label: x }))), s.doctype);
    const scope = [s.issue, s.dstatus, s.doctype, s.q && "“" + s.q + "”"].filter(Boolean);
    PH.text("#sub", (t.differences ? PH.fmt.plural(t.differences, "difference") + " across " + PH.fmt.plural(t.doctypes, "doctype") : "No differences") + " · " + rangeLabel(m.range) + (scope.length ? " · " + scope.join(" · ") : ""));
    PH.text("#tc-diffs", n(t.differences));
    PH.kpis("#kpis", [
      { label: "Differences", value: t.differences, unit: "fields that differ", dark: true },
      { label: "Not reviewed", value: t.new, unit: t.differences ? n(t.differences - t.new) + " reviewed or ignored" : "" },
      { label: "Doctypes", value: t.doctypes, unit: "affected" },
      { label: "Last comparison", value: t.last_at ? (PH.fmt.ago ? PH.fmt.ago(t.last_at) : PH.fmt.datetime(t.last_at)) : "—", unit: t.last_at ? PH.fmt.datetime(t.last_at) : "none in this range" },
    ]);
    PH.set("#notes", [
      m.range.clamped ? `<div class="ph-notice ph-notice--signal">Ranges are limited to ${m.range.max_days} days. Showing ${PH.esc(PH.date.label(m.range.from, m.range.to))}.</div>` : "",
      t.duplicates ? `<div class="ph-notice ph-notice--signal">${n(t.duplicates)} rows repeat the same doctype, field and kind of difference as another row. They are counted as saved.</div>` : "",
    ].join(""));
    bars("#d-issue", m.by_issue_type, "issue", s.issue);
    bars("#d-status", m.by_status, "dstatus", s.dstatus);
    bars("#d-doctype", m.by_doctype, "doctype", s.doctype);
    const days = m.by_day;
    PH.chart("#c-dtrend", {
      type: "line", labels: days.map((x) => PH.fmt.date(x.date)),
      yFormat: (v) => (Number.isInteger(v) ? PH.fmt.num(v) : ""),
      series: [{ label: "Differences found", data: days.map((x) => x.total), color: PH.statusColor.good, fill: true }],
      onClick: (i) => { const d = days[i]; if (d) st.set({ all: "", from: d.date, to: d.date }); },
    });
    paintExport();
  }
  const tDiff = PH.table("#t-diff", {
    columns: [
      { key: "comparison_time", label: "Compared", format: (v) => (v ? PH.fmt.datetime(v) : "—") },
      { key: "doctype_name", label: "DocType", cls: "is-strong", sortable: false },
      { key: "field_name", label: "Field", cls: "ph-mono", sortable: false },
      { key: "issue_type", label: "Kind", sortable: false },
      { key: "status", label: "Review", sortable: false, html: (v) => `<span class="ph-badge ph-badge--${DST[v] || "outline"}">${PH.esc(v || "—")}</span>` },
      { key: "redacted", label: "Values", sortable: false, format: (v) => (v ? "Hidden (secret)" : "Visible") },
    ],
    rows: [], compact: true, empty: "No field differences match these filters", emptyText: "Run a comparison from Desk, or widen the date range.",
    onRowClick: (r) => openDiff(r.name),
  });
  function loadDiffList() {
    if (tab() !== "diffs") return;
    const my = ++seqDL;
    return PH.call(API + "get_difference_list", { ...dArgs(), start: page() * PAGE, limit: PAGE })
      .then((m) => {
        if (my !== seqDL) return;
        tDiff.update(m.rows);
        pager("#p-diff", m.total, (p) => { pg = p; loadDiffList(); });
      })
      .catch((e) => { if (my === seqDL) PH.error("#t-diff", e.message, () => loadDiffList()); });
  }
  function openDiff(name) {
    const body = document.createElement("div");
    PH.skeleton(body);
    const m = PH.modal({ title: "Field difference", sub: name, body, size: "xl" });
    PH.call(API + "get_difference_entry", { name }).then((d) => {
      const e = d.entry;
      const val = (v) => (v == null || v === "" ? '<span class="ph-muted">(empty)</span>' : `<pre class="al-pre">${PH.esc(v)}</pre>`);
      body.innerHTML = `<dl class="ph-kv">
        <dt>DocType</dt><dd class="ph-strong"><a class="ph-link" target="_blank" rel="noopener" href="/app/doctype/${encodeURIComponent(e.doctype_name || "")}">${PH.esc(e.doctype_name || "—")}</a></dd>
        <dt>Field</dt><dd class="ph-mono">${PH.esc(e.field_name || "—")}</dd>
        <dt>Kind</dt><dd>${PH.esc(e.issue_type || "—")}</dd>
        <dt>Review</dt><dd><span class="ph-badge ph-badge--${DST[e.status] || "outline"}">${PH.esc(e.status || "—")}</span></dd>
        <dt>Compared</dt><dd>${PH.esc(e.comparison_time ? PH.fmt.datetime(e.comparison_time) : "—")} by ${PH.esc(e.user_name || "Not recorded")}</dd>
        ${e.source_snapshot ? `<dt>Snapshot</dt><dd><a class="ph-link" target="_blank" rel="noopener" href="/app/code-backup-snapshot/${encodeURIComponent(e.source_snapshot)}">${PH.esc(e.source_snapshot)}</a></dd>` : ""}
        <dt>Record</dt><dd><a class="ph-link" target="_blank" rel="noopener" href="/app/field-difference-log/${encodeURIComponent(e.name)}">${PH.esc(e.name)}</a></dd>
      </dl>
      ${e.redacted ? '<div class="ph-notice ph-notice--signal ph-mt">This field looks like a secret, so its values are hidden here.</div>' : ""}
      <div class="al-ba ph-mt"><div><h4>On the live site (before)</h4>${val(e.live_value)}</div><div><h4>On this site (after)</h4>${val(e.local_value)}</div></div>`;
    }).catch((err) => PH.error(body, err.message, () => { m.close(); openDiff(name); }));
  }

  /* ---------------- export ---------------- */
  function paintExport() {
    const b = PH.$("#export");
    const total = tab() === "diffs" ? dsum && dsum.totals.differences : sum && sum.totals.entries;
    b.disabled = !total;
    b.title = total ? "Download everything that matches the filters (up to 5,000 rows)" : "Nothing to export";
  }
  PH.$("#export").addEventListener("click", () => {
    const diffs = tab() === "diffs", btn = PH.$("#export");
    btn.disabled = true;
    const s = st.get();
    PH.call(API + (diffs ? "get_difference_export" : "get_activity_export"), diffs ? dArgs() : aArgs()).then((d) => {
      const cols = diffs
        ? [["comparison_time", "Compared"], ["doctype_name", "DocType"], ["field_name", "Field"], ["issue_type", "Kind"], ["status", "Review"], ["live_value", "Live value (before)"], ["local_value", "This site value (after)"], ["owner", "Compared by"], ["source_snapshot", "Snapshot"], ["name", "Record"]]
        : [["activity_time", "When"], ["activity_type", "Kind"], ["title", "What happened"], ["status", "Outcome"], ["source", "Source"], ["performed_by", "Who"], ["description", "Details"], ["reference_doctype", "About (doctype)"], ["reference_name", "About (name)"], ["name", "Record"]];
      PH.csv((diffs ? "field_differences_" : "activity_log_") + s.from + "_" + s.to + ".csv", d.rows, cols.map(([key, label]) => ({ key, label })));
      if (d.truncated) PH.toast("Exported the newest " + n(d.row_limit) + " of " + n(d.total) + " rows. Narrow the filters to get the rest.");
    }).catch(() => {}).finally(() => paintExport());
  });

  DevKeys.init({ title: "Activity Log", list: { root: "#ph-main", items: () => PH.$$("#ph-main tbody tr.is-link") } });

  PH.onRefresh(() => reloadAll());
  PH.ready(() => { paintTab(); refreshCurrent(); });
})();
