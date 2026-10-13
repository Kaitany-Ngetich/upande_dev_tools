/* Data Seeder v2 (www/data-seeder-v2.html).
 *
 * Reads : api.v2.data_seeder (get_overview, get_job, get_progress, test_connection).
 * Writes: the EXISTING endpoints in api/seeder.py (start_seed_job, resume_seed_job, pause_seed_job,
 *         cancel_seed_job, retry_doctype, dry_run) and the job editor (get_job_form, save_seed_job,
 *         duplicate_seed_job, delete_seed_job, search_doctypes, populate_children). They enforce the access rule and the state
 *         rules themselves; this page only hides buttons that would be refused.
 * Secrets never reach the browser: the server returns only "set / not set".
 * Polling runs only while the job is Queued or Running and stops by itself when it is idle.
 */
(function () {
  "use strict";
  const READ = "upande_dev_tools.api.v2.data_seeder.";
  const WRITE = "upande_dev_tools.api.seeder.";
  const POLL_MS = 3000;
  const st = PH.state({ job: "", level: "", dt: "", q: "" });
  const n = PH.fmt.num;
  const esc = PH.esc;
  let data = null, seq = 0, timer = null, busy = false, tDocs = null;

  const when = (v) => (v ? String(v).slice(0, 16).replace("T", " ") : "—");
  const BADGE = { done: "good", failed: "bad", running: "signal", paused: "warn", interrupted: "warn", waiting: "outline" };
  const JOB_BADGE = { Completed: "good", Failed: "bad", Running: "signal", Queued: "warn", Paused: "warn", Cancelled: "outline", Draft: "outline" };
  const badge = (cls, text) => '<span class="ph-badge ph-badge--' + cls + '">' + esc(text) + "</span>";
  const ago = (m) => (m == null ? "" : m < 1 ? "just now" : m < 60 ? m + " min ago" : Math.round(m / 60) + " h ago");

  /* ── Calls ─────────────────────────────────────────────────────── */
  const write = (method, args) => PH.call(WRITE + method, args);

  function showList() {
    stopPoll();
    PH.$("#ds-list").hidden = false;
    PH.$("#ds-job").hidden = true;
    PH.$("#sub").textContent = "Copy records from another Frappe site into this one, for development and testing";
    PH.skeleton("#t-jobs", "rows", 4);
    return PH.call(READ + "get_overview", {}, { silent: true })
      .then((m) => {
        if (st.get("job")) return;
        PH.markUpdated();
        PH.kpis("#kpis", [
          { label: "Seed Jobs", value: m.jobs.length, unit: "Saved" },
          { label: "Active now", value: m.active, unit: "Queued or running" },
          { label: "Failed", value: m.jobs.filter((j) => j.status === "Failed").length, unit: "Need a look" },
        ]);
        PH.table("#t-jobs", {
          rows: m.jobs, compact: true, pageSize: 25, empty: "No Seed Jobs yet",
          emptyText: "Use New Seed Job to set up the source site and the DocTypes to copy, then come back here to run it.",
          onRowClick: (r) => st.set({ job: r.name }),
          columns: [
            { key: "name", label: "Job", cls: "ph-strong" },
            { key: "host", label: "Source", format: (v, r) => v || r.source },
            { key: "status", label: "Status", html: (v, r) => badge(JOB_BADGE[v] || "outline", r.stale ? "Stalled" : r.label) },
            { key: "doctypes", label: "DocTypes done", num: true, sortValue: (r) => r.doctypes.done, format: (v) => v.done + " of " + v.total },
            { key: "imported", label: "Records", num: true, format: (v, r) => n(v) + (r.expected ? " of " + n(r.expected) : "") },
            { key: "last_heartbeat", label: "Last activity", format: (v, r) => when(v || r.started_at) },
          ],
        });
      })
      .catch((e) => PH.error("#t-jobs", e.message, showList));
  }

  function load(first) {
    const name = st.get("job");
    if (!name) return showList();
    const my = ++seq;
    PH.$("#ds-list").hidden = true;
    PH.$("#ds-job").hidden = false;
    const s = st.get();
    const args = { name, level: s.level, doctype_name: s.dt, q: s.q, limit: 100 };
    const req = first ? PH.call(READ + "get_job", args, { silent: true }) : PH.call(READ + "get_progress", args, { silent: true });
    if (first) { PH.skeleton("#t-doctypes", "rows", 3); PH.kpiSkeleton("#j-kpis", ["Status", "Records", "DocTypes", "Last activity"]); }
    return req.then((m) => {
      if (my !== seq) return;
      data = Object.assign({}, first || !data ? {} : data, m);
      PH.markUpdated();
      paint();
      schedule();
    }).catch((e) => {
      if (my !== seq) return;
      stopPoll();
      PH.error("#t-doctypes", e.message, () => load(true));
    });
  }

  /* ── Polling: only while the job is active ─────────────────────── */
  function stopPoll() { if (timer) { clearTimeout(timer); timer = null; } }
  function schedule() {
    stopPoll();
    if (!data || data.job.idle || !st.get("job")) return;
    timer = setTimeout(() => { if (document.hidden) schedule(); else load(false); }, POLL_MS);
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden && data && !data.job.idle) load(false); });

  /* ── Painting ──────────────────────────────────────────────────── */
  function paint() {
    const { job, doctypes, config } = data;
    PH.text("#j-name", job.name);
    PH.text("#j-source", (config ? config.source : job.source) + " · " + (config ? config.auth_type : job.auth_type));
    paintNotes(job);
    PH.kpis("#j-kpis", [
      { label: "Status", value: job.stale ? "Stalled" : (JOB_LABEL(job.status)), unit: statusHint(job) },
      { label: "Records", value: n(job.imported), unit: job.expected ? "of " + n(job.expected) + " counted" : "Not counted yet" },
      { label: "DocTypes done", value: job.doctypes_done + " of " + job.doctypes_total, unit: job.doctypes_failed ? job.doctypes_failed + " failed" : "None failed" },
      { label: "Last activity", value: job.last_heartbeat || job.started_at ? PH.fmt.ago(new Date(String(job.last_heartbeat || job.started_at).replace(" ", "T"))) : "Never", unit: job.stale ? "No progress for " + job.stale_minutes + " min" : when(job.last_heartbeat || job.started_at) },
    ]);
    const pct = job.expected ? Math.min(100, Math.round((job.imported * 100) / job.expected)) : 0;
    PH.set("#j-overall", '<div class="ph-progress"><i style="width:' + pct + '%"></i></div><div class="ds-bar"><span>' + esc(statusHint(job)) + "</span><span>" + n(job.imported) + (job.expected ? " / " + n(job.expected) + " records (" + pct + "%)" : " records") + "</span></div>");
    if (!tDocs) tDocs = PH.table("#t-doctypes", docTableCfg());
    tDocs.update(doctypes);
    paintActions();
    if (config) { paintChecks(); paintConfig(); }
    paintLog();
  }
  const JOB_LABEL = (s) => ({ Draft: "Not started", Queued: "Waiting for a worker", Completed: "Done" }[s] || s);

  function statusHint(job) {
    return {
      Draft: "Nothing has been copied yet",
      Queued: "Waiting for a background worker to pick it up",
      Running: "Copying now. This page updates by itself",
      Paused: "Stopped by you. Resume continues where it left off",
      Completed: "Every DocType is done",
      Failed: "At least one DocType failed",
      Cancelled: "Stopped. Start continues after the last saved record",
    }[job.status] || "";
  }

  function paintNotes(job) {
    const out = [];
    if (job.stale) out.push('<div class="ph-notice ph-notice--warn">No progress has been saved for ' + job.stale_minutes + " minutes, so the background worker has probably stopped. Use <b>Mark as stopped</b>, then <b>Resume</b>. Nothing already copied is lost or duplicated.</div>");
    if (job.status === "Failed" && job.error) out.push('<div class="ph-notice ph-notice--bad">' + esc(job.error) + "</div>");
    if (job.status === "Completed") out.push('<div class="ph-notice ph-notice--good">Finished. To pick up records added on the source later, use Retry on a DocType.</div>');
    PH.set("#j-notes", out.join(""));
  }

  function docTableCfg() {
    return {
      rows: [], compact: true, pageSize: false, empty: "No DocTypes on this job",
      onRowClick: (r) => openDoctype(r),
      columns: [
        { key: "idx", label: "#", num: true, sortable: false },
        { key: "doctype", label: "DocType", sortable: false, cls: "ph-strong" },
        { key: "state", label: "State", sortable: false, html: (v, r) => badge(BADGE[v] || "outline", r.label) },
        { key: "imported", label: "Records", num: true, sortable: false, format: (v, r) => n(v) + (r.counted ? " of " + n(r.expected) : "") },
        { key: "pct", label: "Progress", sortable: false, html: (v) => '<div class="ph-progress"><i style="width:' + v + '%"></i></div>' },
        { key: "note", label: "What happened", sortable: false, cls: "is-wrap", format: (v) => v },
      ],
    };
  }

  function openDoctype(r) {
    const kv = [["State", r.label], ["Records read", n(r.imported)], ["Counted on source", r.counted ? n(r.expected) : "Not counted yet"],
      ["Already on this site", r.local_count == null ? "—" : n(r.local_count)], ["Speed", r.rows_per_sec ? r.rows_per_sec + " records/sec" : "—"],
      ["Page", r.page + (r.total_pages ? " of " + r.total_pages : "")], ["Continues after", r.cursor || "the start"], ["Last page saved", when(r.last_page_at)], ["Failures", n(r.error_count)]];
    const cfg = (data.config && data.config.doctypes.find((d) => d.row === r.row)) || null;
    const body = '<div class="ds-detail"><dl class="ph-kv">' + kv.map((p) => "<dt>" + esc(p[0]) + "</dt><dd>" + esc(p[1]) + "</dd>").join("") + "</dl>" +
      '<div>' + esc(r.note) + "</div>" +
      (cfg ? "<div class=\"ph-muted\">Filters</div><pre>" + esc(cfg.filters) + "</pre><div class=\"ph-muted\">Fields</div><pre>" + esc(cfg.fields) + "</pre>" : "") + "</div>";
    const actions = [{ label: "Close" }];
    if (canRetry() && canPopulate(r.row)) actions.push({ label: "Populate child tables", onClick: () => { populateKids(r.row, r.doctype); } });
    if (r.state === "failed" && canRetry()) actions.push({ label: "Retry this DocType", primary: true, onClick: () => retryDoctype(r) });
    PH.modal({ title: r.doctype, sub: "Row " + r.idx + " of " + data.job.name, body, actions });
  }

  function paintChecks() {
    const col = { ok: "good", warn: "warn", bad: "bad" };
    PH.set("#checks", data.preflight.map((c) => '<li><span class="ph-dot ph-dot--' + col[c.level] + '"></span><span>' + esc(c.text) + "</span></li>").join(""));
  }

  function paintConfig() {
    const c = data.config;
    const rows = c.site ? [["Site", c.site], ["Address", c.source], ["Sign in with", c.auth_type]] : [["Source", c.source], ["Sign in with", c.auth_type]];
    if (c.auth_type === "API Key") rows.push(["API key", c.api_key_set ? "Set" : "Missing"], ["API secret", c.api_secret_set ? "Set" : "Missing"]);
    else rows.push(["User", c.source_user || "Missing"], ["Password", c.password_set ? "Set" : "Missing"]);
    rows.push(["Page size", n(c.page_size)], ["Anonymised fields", c.anonymise.length ? c.anonymise.join(", ") : "None"]);
    PH.set("#config", rows.map((p) => "<dt>" + esc(p[0]) + "</dt><dd>" + esc(p[1]) + "</dd>").join(""));
    const names = [...new Set(data.doctypes.map((d) => d.doctype))];
    PH.options("#f-dt", [{ value: "", label: "All DocTypes" }].concat(names.map((x) => ({ value: x, label: x }))), st.get("dt"));
  }

  function paintLog() {
    const l = data.log;
    PH.text("#log-meta", l.total ? "Showing the newest " + n(l.rows.length) + " of " + n(l.total) : "No entries match");
    PH.set("#log", l.rows.map((r) => '<div class="ds-log-row lvl-' + esc((r.level || "Info").toLowerCase()) + '"><span>' + esc(when(r.creation)) + "</span><span>" + esc(r.doctype_name || "") + "</span><span>" + esc(r.level) + '</span><span class="ds-msg">' + esc(r.message) + "</span></div>").join("") || '<div class="ph-muted">No log entries.</div>');
    PH.$$("#f-level button").forEach((b) => b.classList.toggle("is-on", b.dataset.value === st.get("level")));
  }

  /* ── Actions ───────────────────────────────────────────────────── */
  const canPopulate = (row) => data && data.config && data.config.doctypes.some((d) => d.include_children && d.child_tables.length && (!row || d.row === row));
  const canRetry = () => data && !["Queued", "Running"].includes(data.job.status);

  function paintActions() {
    const j = data.job, s = j.status, a = [];
    const btn = (id, label, cls) => '<button class="ph-btn ' + (cls || "") + '" data-act="' + id + '" type="button"' + (busy ? " disabled" : "") + ">" + esc(label) + "</button>";
    a.push(btn("test", "Test connection"));
    a.push(btn("edit", "Edit"), btn("copy", "Duplicate"));
    if (!["Queued", "Running"].includes(s) && canPopulate()) a.push(btn("kids", "Populate child tables"));
    if (!["Queued", "Running"].includes(s)) a.push(btn("count", "Count records"));
    if (s === "Paused") a.push(btn("resume", "Resume", "ph-btn--primary"));
    else if (["Draft", "Failed", "Cancelled"].includes(s)) a.push(btn("start", s === "Draft" ? "Start" : s === "Failed" ? "Retry" : "Start again", "ph-btn--primary"));
    if (s === "Running") a.push(btn("pause", j.stale ? "Mark as stopped" : "Pause"));
    if (s === "Queued") a.push(btn("pause", "Take off the queue"));
    if (["Queued", "Running", "Paused"].includes(s)) a.push(btn("cancel", "Cancel", "ph-btn--danger"));
    else a.push(btn("delete", "Delete", "ph-btn--danger"));
    PH.set("#actions", a.join(""));
  }

  function describe(verb) {
    const c = data.config, j = data.job;
    const todo = data.doctypes.filter((d) => d.state !== "done");
    const max = j.remaining_max;
    const parts = ["<div class=\"ds-confirm\"><div>" + verb + " <b>" + esc(j.name) + "</b> will read records from <b>" + esc(c.source) + "</b> and write them straight into this site's database (no validation, no hooks).</div>",
      "<div>DocTypes, in this order:</div><ol>" + todo.map((d) => "<li>" + esc(d.doctype) + (d.counted ? " (" + n(Math.max(d.expected - d.imported, 0)) + " left)" : " (not counted)") + "</li>").join("") + "</ol>",
      "<div>" + (max == null ? "<b>At most: unknown.</b> Some DocTypes have not been counted. Run Count records first to see the number." : "<b>At most " + n(max) + " records.</b> Records that already exist here are skipped, not overwritten.") + "</div>"];
    if (c.anonymise.length) parts.push("<div>These fields will be replaced: " + esc(c.anonymise.join(", ")) + ".</div>");
    parts.push("</div>");
    return parts.join("");
  }

  function run(label, fn, okMsg) {
    busy = true; paintActions();
    return fn().then((m) => { if (okMsg) PH.toast(okMsg, "good"); return m; })
      .catch(() => {}).finally(() => { busy = false; return load(false).then(() => { if (data) paintActions(); }); });
  }

  function confirmRun(title, verb, okLabel, fn, okMsg) {
    const bad = data.preflight.filter((c) => c.level === "bad");
    if (bad.length) { PH.toast("Fix first: " + bad[0].text, "bad", 7000); return; }
    PH.modal({ title, body: describe(verb), actions: [{ label: "Not now" }, { label: okLabel, primary: true, onClick: () => { run(title, fn, okMsg); } }] });
  }

  function populateKids(row, doctype) {
    const names = data.config.doctypes.filter((d) => d.include_children && d.child_tables.length && (!row || d.row === row));
    PH.modal({
      title: "Populate child tables?",
      body: '<p class="ph-muted">Asks <b>' + esc(data.config.source) + "</b> for the child rows (" + names.map((d) => esc(d.doctype + ": " + d.child_tables.join(", "))).join("; ") + ") of records already on this site. Only records with no child rows yet are asked for, so it is safe to run again. Parent records are not touched.</p>",
      actions: [{ label: "Not now" }, { label: "Populate", primary: true, onClick: () => { run("kids", () => write("populate_children", { name: data.job.name, row_name: row || null }), "Filling child tables. Progress is in the log"); } }],
    });
    void doctype;
  }

  function retryDoctype(r) {
    PH.modal({
      title: "Retry " + r.doctype + "?",
      body: '<p class="ph-muted">The job will start again from ' + esc(r.cursor ? "after " + r.cursor : "the beginning of this DocType") + ". Records already copied are kept.</p>",
      actions: [{ label: "Not now" }, { label: "Retry", primary: true, onClick: () => { run("retry", () => write("retry_doctype", { name: data.job.name, row_name: r.row }), "Queued again"); } }],
    });
  }

  function testConnection() {
    busy = true; paintActions();
    PH.toast("Testing the connection to " + data.config.host + "…");
    return PH.call(READ + "test_connection", { name: data.job.name }, { silent: true })
      .then((m) => PH.toast("Connected to " + m.host + " as " + m.user + " in " + m.ms + " ms", "good"))
      .catch((e) => PH.toast("Connection failed. " + e.message, "bad", 9000))
      .finally(() => { busy = false; paintActions(); });
  }

  const ACTIONS = {
    test: testConnection,
    edit: editJob,
    kids: () => populateKids(null),
    copy() {
      PH.modal({
        title: "Duplicate this job?",
        body: '<p class="ph-muted">Makes a new Draft with the same source, sign-in and DocTypes. Progress is not copied.</p>',
        actions: [{ label: "Not now" }, { label: "Duplicate", primary: true, onClick: () => write("duplicate_seed_job", { name: data.job.name }).then((r) => { PH.toast("Created " + r.name, "good"); st.set({ job: r.name }); }) }],
      });
    },
    delete() {
      PH.modal({
        title: "Delete " + data.job.name + "?",
        body: '<p class="ph-muted">Removes the job and its log. Records already copied into this site stay where they are.</p>',
        actions: [{ label: "Keep it" }, { label: "Delete the job", danger: true, onClick: () => write("delete_seed_job", { name: data.job.name }).then(() => { PH.toast("Deleted", "good"); data = null; tDocs = null; st.set({ job: "", level: "", dt: "", q: "" }); }) }],
      });
    },
    count() {
      PH.modal({
        title: "Count records?",
        body: '<p class="ph-muted">This asks <b>' + esc(data.config.source) + "</b> how many records match each of the " + data.doctypes.length + " DocTypes. Nothing is copied.</p>",
        actions: [{ label: "Not now" }, { label: "Count", primary: true, onClick: () => { run("count", () => write("dry_run", { name: data.job.name }), "Counted"); } }],
      });
    },
    start: () => confirmRun(data.job.status === "Failed" ? "Retry this job?" : "Start this job?", "Starting", "Start", () => write("start_seed_job", { name: data.job.name }), "Queued"),
    resume: () => confirmRun("Resume this job?", "Resuming", "Resume", () => write("resume_seed_job", { name: data.job.name }), "Queued"),
    pause: () => run("pause", () => write("pause_seed_job", { name: data.job.name }), "Stopped. Use Resume to continue."),
    cancel() {
      PH.modal({
        title: "Cancel this job?",
        body: '<p class="ph-muted">The job stops after the page it is on. Records already copied stay. Start again continues after the last saved record.</p>',
        actions: [{ label: "Keep running" }, { label: "Cancel the job", danger: true, onClick: () => { run("cancel", () => write("cancel_seed_job", { name: data.job.name }), "Cancelled"); } }],
      });
    },
  };


  /* ── Job editor ────────────────────────────────────────────────── */
  const BLANK_ROW = { row: "", doctype_name: "", filters: "[]", fields: '["*"]', include_children: 1, order_by: "name asc" };
  const BLANK = { name: "", source_url: "", auth_type: "API Key", api_key: "", api_secret_set: false, source_user: "", source_password_set: false, page_size: 500, ignore_permissions: 1, ignore_links: 1, ignore_mandatory: 1, anonymise_fields: "{}", doctypes: [Object.assign({}, BLANK_ROW)] };

  const fld = (label, control, o) => '<div class="ph-field' + (o && o.full ? " ph-field--full" : "") + '"><label class="ph-label">' + esc(label) + "</label>" + control + (o && o.hint ? '<div class="ph-field__hint">' + esc(o.hint) + "</div>" : "") + "</div>";
  const inp = (k, v, o) => '<input class="ph-input" data-k="' + k + '" type="' + ((o && o.type) || "text") + '" value="' + esc(v == null ? "" : v) + '"' + (o && o.ph ? ' placeholder="' + esc(o.ph) + '"' : "") + (o && o.auto ? ' autocomplete="' + o.auto + '"' : ' autocomplete="off"') + ">";
  const chk = (k, v, label) => '<label class="ph-check"><input type="checkbox" data-k="' + k + '"' + (v ? " checked" : "") + "> " + esc(label) + "</label>";

  /* Filter builder: Frappe list-view style (field, operator, value). Stored as [[doctype, field, op, value]]. */
  const OPS = [["=", "Equals"], ["!=", "Not Equals"], ["like", "Like"], ["not like", "Not Like"], ["in", "In"], ["not in", "Not In"], ["is", "Is"], [">", "Greater Than"], ["<", "Less Than"], [">=", "Greater Than Or Equal To"], ["<=", "Less Than Or Equal To"], ["between", "Between"]];
  const FCACHE = {};
  const loadFields = (dt) => {
    if (!dt) return Promise.resolve(null);
    if (!FCACHE[dt]) FCACHE[dt] = write("get_doctype_fields", { doctype: dt }).catch((e) => { delete FCACHE[dt]; throw e; });
    return FCACHE[dt];
  };
  const opt = (v, l, sel) => '<option value="' + esc(v) + '"' + (sel ? " selected" : "") + ">" + esc(l) + "</option>";
  const NUMERIC = ["Int", "Float", "Currency", "Percent", "Long Int", "Rating"];
  const DATES = ["Date", "Datetime"];

  function valueHtml(fd, op, v) {
    const t = fd ? fd.fieldtype : "Data";
    const one = (val, extra) => {
      if (op === "is") return '<select class="ph-select ds-fv">' + opt("set", "Set", val === "set") + opt("not set", "Not Set", val === "not set") + "</select>";
      if (t === "Check" && !["in", "not in", "like", "not like"].includes(op)) return '<select class="ph-select ds-fv">' + opt("1", "Yes", String(val) === "1") + opt("0", "No", String(val) === "0") + "</select>";
      if (t === "Select" && ["=", "!="].includes(op)) return '<select class="ph-select ds-fv">' + opt("", "", false) + String(fd.options || "").split("\n").filter((x) => x).map((x) => opt(x, x, x === val)).join("") + "</select>";
      const type = DATES.includes(t) && !["like", "not like", "in", "not in"].includes(op) ? "date" : NUMERIC.includes(t) && !["like", "not like", "in", "not in"].includes(op) ? "number" : "text";
      return '<input class="ph-input ds-fv" type="' + type + '" value="' + esc(val == null ? "" : val) + '"' + (extra || "") + ' autocomplete="off">';
    };
    if (op === "between") { const a = Array.isArray(v) ? v : ["", ""]; return one(a[0]) + '<span class="ph-muted">and</span>' + one(a[1]); }
    return one(Array.isArray(v) ? v.join(", ") : v, op === "in" || op === "not in" ? ' placeholder="comma, separated"' : "");
  }

  function filterRowHtml(fields, f) {
    const fd = fields.find((x) => x.fieldname === f.field);
    return '<div class="ds-f">' +
      '<div class="ds-combo"><input class="ph-input" data-fq type="text" placeholder="Search field…" autocomplete="off" role="combobox" aria-expanded="false" value="' + esc(fd ? fd.label + " (" + fd.fieldname + ")" : f.field || "") + '">' +
      '<input type="hidden" data-f="field" value="' + esc(f.field || "") + '"><div class="ds-combo__list" role="listbox" hidden></div></div>' +
      '<select class="ph-select" data-f="op">' + OPS.map((o) => opt(o[0], o[1], o[0] === f.op)).join("") + "</select>" +
      '<span class="ds-f__val" data-f="val">' + valueHtml(fd, f.op, f.value) + "</span>" +
      '<button type="button" class="ph-iconbtn ph-iconbtn--flat ph-iconbtn--sm" data-frm aria-label="Remove filter">' + PH.icon("close") + "</button></div>";
  }

  /* Old rows may hold filters the builder cannot express (OR groups, dict form). They are kept as-is and shown read-only. */
  function parseFilters(text, dt) {
    let arr; try { arr = JSON.parse(text || "[]"); } catch (e) { return { raw: text }; }
    if (!Array.isArray(arr)) return { raw: text };
    const out = [];
    for (const f of arr) {
      if (Array.isArray(f) && (f.length === 4 || f.length === 3)) {
        const [field, op, value] = f.length === 4 ? [f[1], f[2], f[3]] : f;
        const o = String(op).toLowerCase();
        if (!OPS.some((x) => x[0] === o)) return { raw: text };
        out.push({ field, op: o, value: (o === "like" || o === "not like") && typeof value === "string" ? value.replace(/^%|%$/g, "") : value });
      } else return { raw: text };
    }
    return { list: out };
  }

  function serialiseFilters(rowEl, dt) {
    if (rowEl.dataset.raw != null) return rowEl.dataset.raw;
    const out = [];
    PH.$$(".ds-f", rowEl).forEach((el) => {
      const field = el.querySelector('[data-f="field"]').value, op = el.querySelector('[data-f="op"]').value;
      if (!field) return;
      const vals = PH.$$(".ds-fv", el).map((x) => x.value.trim());
      let value = vals[0];
      if (op === "between") value = vals.slice(0, 2);
      else if (op === "in" || op === "not in") value = value.split(",").map((x) => x.trim()).filter((x) => x);
      else if ((op === "like" || op === "not like") && value && value.indexOf("%") < 0) value = "%" + value + "%";
      out.push([dt, field, op, value]);
    });
    return JSON.stringify(out);
  }

  function paintFilters(rowEl, dt, list) {
    const box = rowEl.querySelector("[data-filters]");
    if (rowEl.dataset.raw != null) { box.innerHTML = '<div class="ph-muted">These filters use a form the builder cannot show, so they are kept exactly as saved: <code>' + esc(rowEl.dataset.raw) + '</code> <button type="button" class="ph-link" data-fclear>Clear and use the builder</button></div>'; return; }
    if (!dt) { box.innerHTML = '<div class="ph-muted">Choose a DocType first.</div>'; return; }
    box.innerHTML = '<div class="ph-muted">Loading fields…</div>';
    loadFields(dt).then((fields) => {
      rowEl._fields = fields;
      box.innerHTML = '<div class="ds-fl">' + (list || []).map((f) => filterRowHtml(fields, f)).join("") + '</div><button type="button" class="ph-btn ph-btn--ghost" data-fadd>Add a filter</button>';
    }).catch((e) => { box.innerHTML = '<div class="ph-field__error">' + esc(e.message) + "</div>"; });
  }

  function rowHtml(r, i, n) {
    return '<div class="ds-rowedit" data-i="' + i + '" data-row="' + esc(r.row || "") + '" data-dt="' + esc(r.doctype_name) + '">' +
      '<div class="ds-rowedit__head"><b>' + (i + 1) + '.</b>' +
      '<input class="ph-input" data-r="doctype_name" value="' + esc(r.doctype_name) + '" placeholder="Pick a DocType" autocomplete="off" role="combobox" aria-expanded="false">' +
      '<button type="button" class="ph-btn ph-btn--ghost" data-mv="-1"' + (i === 0 ? " disabled" : "") + ' aria-label="Move up">↑</button>' +
      '<button type="button" class="ph-btn ph-btn--ghost" data-mv="1"' + (i === n - 1 ? " disabled" : "") + ' aria-label="Move down">↓</button>' +
      '<button type="button" class="ph-btn ph-btn--ghost" data-rm aria-label="Remove">Remove</button></div>' +
      '<div class="ds-sug" data-sug role="listbox" hidden></div>' +
      '<div class="ph-field__error" data-dterr hidden></div>' +
      '<div class="ds-rowedit__body">' +
      '<div><div class="ph-label">Filters</div><div data-filters></div></div>' +
      '<div><div class="ph-label">Fields to copy</div><div data-fieldpick></div>' +
      fld("Order by", '<input class="ph-input" data-r="order_by" value="' + esc(r.order_by) + '" autocomplete="off">', { hint: "Keep name asc unless you know why" }) +
      chk("r:include_children", r.include_children, "Include child tables") + "</div></div></div>";
  }

  function paintFieldPick(rowEl, dt, json) {
    const box = rowEl.querySelector("[data-fieldpick]");
    let sel = null; try { const a = JSON.parse(json || '["*"]'); if (Array.isArray(a) && !(a.length === 1 && a[0] === "*")) sel = a; } catch (e) { sel = null; }
    box.innerHTML = '<label class="ph-check"><input type="checkbox" data-allf' + (sel ? "" : " checked") + "> All fields</label>" +
      '<input class="ph-input ds-fsearch" type="search" data-fieldsearch placeholder="Search fields…" autocomplete="off"' + (sel ? "" : " hidden") + ">" +
      '<select class="ph-select ds-fsel" data-fsel multiple size="6"' + (sel ? "" : " hidden") + "></select>";
    if (!dt) return;
    loadFields(dt).then((fields) => {
      const s = box.querySelector("[data-fsel]");
      s.innerHTML = fields.map((x) => opt(x.fieldname, x.label + " (" + x.fieldname + ")", sel && sel.includes(x.fieldname))).join("");
    }).catch(() => {});
  }

  function readFields(rowEl) {
    if (rowEl.querySelector("[data-allf]").checked) return '["*"]';
    const v = Array.from(rowEl.querySelector("[data-fsel]").selectedOptions).map((o) => o.value);
    return JSON.stringify(v.length ? v : ["*"]);
  }

  function formHtml(f, sites, mode) {
    const key = f.auth_type === "API Key";
    return '<div class="ds-form">' +
      '<div class="ph-form">' +
      fld("Site to copy from", '<select class="ph-select" data-k="site">' + opt("", "Choose a site…", mode === "") +
        sites.map((x) => opt("inst:" + x.name, x.name + (x.environment_type ? " · " + x.environment_type : "") + (x.site_url ? " · " + x.site_url.replace(/^https?:\/\//, "") : ""), mode === "inst:" + x.name)).join("") +
        (mode === "__legacy" ? opt("__legacy", "Current address (not saved to a site)", true) : "") +
        opt("__new", "+ Add a new site", mode === "__new") + "</select>", { full: true, hint: "Saved sites are shared with Deployments. Nothing is ever written to the source." }) +
      '<div class="ph-field--full ds-sitebox" data-sm="new"><div class="ph-form">' +
      fld("Site name", inp("new_name", "", { ph: "e.g. Kaitet Production" }), { hint: "How it appears in the list" }) +
      fld("Environment", '<select class="ph-select" data-k="new_env">' + ["Production", "Staging", "Local Development"].map((x) => opt(x, x, false)).join("") + "</select>") + "</div></div>" +
      '<div class="ph-field--full ds-sitebox" data-sm="url">' + fld("Site address", inp("source_url", f.source_url, { type: "url", ph: "https://kaitet-group.upande.com" })) + "</div>" +
      '<div class="ph-field--full ds-sitebox" data-sm="saved"><div class="ds-signin" data-signin></div>' + chk("diff_signin", 0, "Use a different sign-in for this job") + "</div>" +
      fld("Page size", inp("page_size", f.page_size, { type: "number" }), { hint: "Records per request. Halves itself when the source is slow." }) +
      '<div class="ph-field--full ds-authblock"><div class="ph-form">' +
      fld("Sign in with", '<select class="ph-select" data-k="auth_type"><option' + (key ? " selected" : "") + '>API Key</option><option' + (key ? "" : " selected") + ">Password</option></select>") +
      '<div class="ph-field--full ds-auth" data-auth="API Key"' + (key ? "" : " hidden") + '><div class="ph-form">' +
      fld("API key", inp("api_key", f.api_key)) +
      fld("API secret", inp("api_secret", "", { type: "password", auto: "new-password", ph: f.api_secret_set ? "Saved. Leave blank to keep it" : "" })) + "</div></div>" +
      '<div class="ph-field--full ds-auth" data-auth="Password"' + (key ? " hidden" : "") + '><div class="ph-form">' +
      fld("User", inp("source_user", f.source_user, { auto: "off" })) +
      fld("Password", inp("source_password", "", { type: "password", auto: "new-password", ph: f.source_password_set ? "Saved. Leave blank to keep it" : "" })) + "</div></div>" +
      '<div class="ph-field--full" data-sm-upd hidden>' + chk("update_site", 0, "Also save this sign-in on the site") + "</div></div></div>" +
      '<div class="ph-field--full ds-checkrow">' + chk("ignore_permissions", f.ignore_permissions, "Skip permission checks") + chk("ignore_links", f.ignore_links, "Skip link checks") + chk("ignore_mandatory", f.ignore_mandatory, "Skip mandatory checks") + "</div>" +
      fld("Anonymise fields (JSON object)", '<textarea class="ph-input ds-code" rows="2" data-k="anonymise_fields">' + esc(f.anonymise_fields) + "</textarea>", { full: true, hint: 'Field name to replacement, applied to every DocType, e.g. {"email_id": "***"}' }) +
      "</div>" +
      '<div class="ds-rows-head"><h3 class="ds-h3">DocTypes</h3><span class="ph-muted">Copied top to bottom. Put masters (Item, Customer) above what links to them.</span></div>' +
      '<div id="ds-rows"></div><button type="button" class="ph-btn" id="ds-addrow">Add a DocType</button></div>';
  }

  function openEditor(f, title, sites) {
    sites = sites || [];
    const form = JSON.parse(JSON.stringify(f));
    const mode0 = form.instance && sites.some((x) => x.name === form.instance) ? "inst:" + form.instance : form.source_url ? "__legacy" : sites.length ? "" : "__new";
    let m = null, rows = form.doctypes.length ? form.doctypes : [Object.assign({}, BLANK_ROW)];
    const root = () => m.el;
    const readRows = () => PH.$$(".ds-rowedit", root()).map((el) => {
      const g = (k) => el.querySelector('[data-r="' + k + '"]').value;
      const dt = el.dataset.dt;
      return { row: el.dataset.row, doctype_name: dt, filters: serialiseFilters(el, dt), fields: readFields(el), order_by: g("order_by"), include_children: el.querySelector('[data-k="r:include_children"]').checked ? 1 : 0 };
    });
    const drawRows = () => {
      PH.set("#ds-rows", rows.map((r, i) => rowHtml(r, i, rows.length)).join(""), root());
      PH.$$(".ds-rowedit", root()).forEach((el, i) => {
        const r = rows[i], pf = parseFilters(r.filters, r.doctype_name);
        if (pf.raw != null && pf.raw.trim() !== "" && pf.raw.trim() !== "[]") el.dataset.raw = pf.raw;
        paintFilters(el, r.doctype_name, pf.list || []);
        paintFieldPick(el, r.doctype_name, r.fields);
      });
    };
    const read = () => {
      const g = (k) => { const e = root().querySelector('[data-k="' + k + '"]'); return e ? (e.type === "checkbox" ? (e.checked ? 1 : 0) : e.value) : ""; };
      const site = g("site"), inst = site.startsWith("inst:") ? sites.find((x) => x.name === site.slice(5)) : null;
      const authOn = !PH.$(".ds-authblock", root()).hidden;
      const sx = authOn ? {} : { api_key: "", api_secret: "", source_user: "", source_password: "" };
      return Object.assign({ instance: inst ? inst.name : "", new_site: site === "__new" ? { name: g("new_name"), environment: g("new_env") } : null, update_site: g("update_site"), site_choice: site, source_url: inst ? (inst.site_url || g("source_url")) : g("source_url"), auth_type: authOn ? g("auth_type") : (inst ? inst.seeder_auth_type : g("auth_type")), api_key: g("api_key"), api_secret: g("api_secret"), source_user: g("source_user"), source_password: g("source_password"), page_size: g("page_size"), ignore_permissions: g("ignore_permissions"), ignore_links: g("ignore_links"), ignore_mandatory: g("ignore_mandatory"), anonymise_fields: g("anonymise_fields"), doctypes: readRows() }, sx);
    };
    let tm = null;
    m = PH.modal({
      title, size: "lg", sub: form.name ? form.name : "Saved as a Draft. Nothing is copied until you press Start.",
      body: formHtml(form, sites, mode0),
      actions: [{ label: "Cancel" }, {
        label: form.name ? "Save changes" : "Create job", primary: true,
        onClick: () => {
          if (!PH.$('[data-k="site"]', root()).value) { PH.toast("Choose a site, or add a new one.", "bad"); return false; }
          const bad = PH.$$(".ds-rowedit", root()).find((x) => !x.dataset.dt);
          if (bad) { PH.toast("Pick a valid DocType in every row.", "bad"); return false; }
          return write("save_seed_job", { data: JSON.stringify(read()), name: form.name || null }).then((r) => {
          PH.toast(form.name ? "Saved" : "Created " + r.name, "good");
          if (form.name) { load(false); return; }
          st.set({ job: r.name });
          }).catch((e) => { PH.toast(e.message, "bad", 8000); return false; });
        },
      }],
    });
    drawRows();
    const el = root();
    const syncSite = () => {
      const site = PH.$('[data-k="site"]', el).value, inst = site.startsWith("inst:") ? sites.find((x) => x.name === site.slice(5)) : null;
      const diff = PH.$('[data-k="diff_signin"]', el).checked;
      const show = (k, on) => { PH.$$('[data-sm="' + k + '"]', el).forEach((d) => { d.hidden = !on; }); };
      show("new", site === "__new"); show("url", site === "__new" || site === "__legacy"); show("saved", !!inst);
      const saved = inst && inst.has_signin;
      PH.$("[data-signin]", el).innerHTML = inst ? '<div><b>' + esc(inst.site_url || "No address saved") + '</b></div><div class="ph-muted">' + (saved ? "Sign-in saved on this site (" + esc(inst.seeder_auth_type) + "). Nothing to type." : "No sign-in saved on this site yet. Enter it below and it is saved for next time.") + "</div>" : "";
      PH.$('[data-sm="saved"] .ph-check', el).hidden = !saved;
      PH.$(".ds-authblock", el).hidden = !site || (!!inst && saved && !diff);
      PH.$("[data-sm-upd]", el).hidden = !(inst && saved && diff);
    };
    syncSite();
    el.addEventListener("change", (e) => {
      if (e.target.dataset.k === "site" || e.target.dataset.k === "diff_signin") syncSite();
      if (e.target.dataset.k === "auth_type") PH.$$(".ds-auth", el).forEach((d) => { d.hidden = d.dataset.auth !== e.target.value; });
    });
    const dtChosen = (inp) => {
      const rowEl = inp.closest(".ds-rowedit"), err = rowEl.querySelector("[data-dterr]"), v = inp.value.trim();
      if (v === rowEl.dataset.dt) return;
      err.hidden = true;
      if (!v) { rowEl.dataset.dt = ""; delete rowEl.dataset.raw; paintFilters(rowEl, "", []); paintFieldPick(rowEl, "", '["*"]'); return; }
      loadFields(v).then(() => {
        rowEl.dataset.dt = v; delete rowEl.dataset.raw; inp.classList.remove("is-bad");
        paintFilters(rowEl, v, []); paintFieldPick(rowEl, v, '["*"]');
      }).catch(() => {
        rowEl.dataset.dt = ""; inp.classList.add("is-bad");
        err.textContent = "\u201c" + v + "\u201d is not a DocType. Pick one from the list."; err.hidden = false;
        paintFilters(rowEl, "", []); paintFieldPick(rowEl, "", '["*"]');
      });
    };
    el.addEventListener("change", (e) => {
      if (e.target.dataset.r === "doctype_name") return dtChosen(e.target);
      const rowEl = e.target.closest(".ds-rowedit");
      if (e.target.matches("[data-allf]")) { rowEl.querySelector("[data-fsel]").hidden = e.target.checked; rowEl.querySelector("[data-fieldsearch]").hidden = e.target.checked; }
      const fe = e.target.closest(".ds-f");
      if (fe && rowEl && (e.target.dataset.f === "field" || e.target.dataset.f === "op")) {
        const fd = (rowEl._fields || []).find((x) => x.fieldname === fe.querySelector('[data-f="field"]').value);
        fe.querySelector('[data-f="val"]').innerHTML = valueHtml(fd, fe.querySelector('[data-f="op"]').value, "");
      }
    });
    /* Suggestions sit in the page flow under the input (no floating popup to misplace). */
    const sugFor = (inp) => inp.closest(".ds-rowedit").querySelector("[data-sug]");
    const hideSug = (inp) => { const b = sugFor(inp); b.hidden = true; b.innerHTML = ""; inp.setAttribute("aria-expanded", "false"); };
    const showSug = (inp) => {
      clearTimeout(tm);
      tm = setTimeout(() => PH.call(WRITE + "search_doctypes", { txt: inp.value }, { silent: true }).then((names) => {
        if (document.activeElement !== inp) return;
        const b = sugFor(inp);
        b.innerHTML = names.length ? names.map((x) => '<button type="button" role="option" tabindex="-1" data-pick="' + esc(x) + '">' + esc(x) + "</button>").join("") : '<div class="ph-muted">No DocType matches</div>';
        b.hidden = false; inp.setAttribute("aria-expanded", "true");
      }).catch(() => {}), 200);
    };
    el.addEventListener("input", (e) => { if (e.target.dataset.r === "doctype_name") showSug(e.target); });
    el.addEventListener("focusin", (e) => { if (e.target.dataset.r === "doctype_name") showSug(e.target); });
    el.addEventListener("focusout", (e) => { if (e.target.dataset.r === "doctype_name") setTimeout(() => hideSug(e.target), 150); });
    el.addEventListener("mousedown", (e) => {
      const pick = e.target.closest("[data-pick]");
      if (!pick) return;
      e.preventDefault();
      const inp = pick.closest(".ds-rowedit").querySelector('[data-r="doctype_name"]');
      inp.value = pick.dataset.pick; hideSug(inp); dtChosen(inp);
    });
    el.addEventListener("keydown", (e) => {
      const inp = e.target.closest && e.target.closest('[data-r="doctype_name"]');
      if (!inp) return;
      const box = sugFor(inp), items = Array.from(box.querySelectorAll("[data-pick]")), cur = items.findIndex((x) => x.classList.contains("is-on"));
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault(); if (!items.length) return;
        const nx = (cur + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
        items.forEach((x, i) => x.classList.toggle("is-on", i === nx)); items[nx].scrollIntoView({ block: "nearest" });
      } else if (e.key === "Enter" && cur >= 0) { e.preventDefault(); inp.value = items[cur].dataset.pick; hideSug(inp); dtChosen(inp); }
      else if (e.key === "Escape" && !box.hidden) { e.preventDefault(); hideSug(inp); }
    });
    /* Searchable field picker for filters */
    const comboList = (inp) => inp.parentElement.querySelector(".ds-combo__list");
    const comboClose = (inp) => { comboList(inp).hidden = true; inp.setAttribute("aria-expanded", "false"); };
    const comboOpen = (inp) => {
      const rowEl = inp.closest(".ds-rowedit"), q = inp.dataset.typed ? inp.value.trim().toLowerCase() : "";
      const hits = (rowEl._fields || []).filter((x) => !q || x.label.toLowerCase().includes(q) || x.fieldname.toLowerCase().includes(q)).slice(0, 60);
      const l = comboList(inp);
      l.innerHTML = hits.length ? hits.map((x) => '<button type="button" role="option" tabindex="-1" data-fpick="' + esc(x.fieldname) + '"><span>' + esc(x.label) + '</span><small>' + esc(x.fieldname + " · " + x.fieldtype) + "</small></button>").join("") : '<div class="ph-muted">No field matches</div>';
      l.hidden = false; inp.setAttribute("aria-expanded", "true");
    };
    const comboPick = (inp, name) => {
      const rowEl = inp.closest(".ds-rowedit"), fd = (rowEl._fields || []).find((x) => x.fieldname === name);
      const hid = inp.parentElement.querySelector('[data-f="field"]');
      inp.value = fd ? fd.label + " (" + fd.fieldname + ")" : ""; delete inp.dataset.typed;
      hid.value = name; comboClose(inp);
      hid.dispatchEvent(new Event("change", { bubbles: true }));
    };
    el.addEventListener("focusin", (e) => { if (e.target.matches("[data-fq]")) { delete e.target.dataset.typed; e.target.select(); comboOpen(e.target); } });
    el.addEventListener("input", (e) => {
      if (e.target.matches("[data-fq]")) { e.target.dataset.typed = "1"; comboOpen(e.target); }
      if (e.target.matches("[data-fieldsearch]")) {
        const q = e.target.value.trim().toLowerCase();
        PH.$$("option", e.target.closest("[data-fieldpick]")).forEach((o) => { o.hidden = !!q && !o.textContent.toLowerCase().includes(q); });
      }
    });
    el.addEventListener("focusout", (e) => {
      if (!e.target.matches("[data-fq]")) return;
      const inp = e.target;
      setTimeout(() => {
        comboClose(inp);
        const rowEl = inp.closest(".ds-rowedit"), cur = inp.parentElement.querySelector('[data-f="field"]').value;
        const fd = (rowEl._fields || []).find((x) => x.fieldname === cur);
        inp.value = fd ? fd.label + " (" + fd.fieldname + ")" : ""; delete inp.dataset.typed;
      }, 150);
    });
    el.addEventListener("mousedown", (e) => {
      const pick = e.target.closest("[data-fpick]");
      if (!pick) return;
      e.preventDefault();
      comboPick(pick.closest(".ds-combo").querySelector("[data-fq]"), pick.dataset.fpick);
    });
    el.addEventListener("keydown", (e) => {
      const inp = e.target.matches && e.target.matches("[data-fq]") ? e.target : null;
      if (!inp) return;
      const l = comboList(inp), items = Array.from(l.querySelectorAll("[data-fpick]")), cur = items.findIndex((x) => x.classList.contains("is-on"));
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault(); if (l.hidden) comboOpen(inp);
        const its = Array.from(l.querySelectorAll("[data-fpick]")); if (!its.length) return;
        const nx = (cur + (e.key === "ArrowDown" ? 1 : -1) + its.length) % its.length;
        its.forEach((x, i) => x.classList.toggle("is-on", i === nx)); its[nx].scrollIntoView({ block: "nearest" });
      } else if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); comboPick(inp, (items[cur >= 0 ? cur : 0] || {}).dataset ? items[cur >= 0 ? cur : 0].dataset.fpick : ""); }
      else if (e.key === "Escape" && !l.hidden) { e.preventDefault(); e.stopPropagation(); comboClose(inp); }
    });
    el.addEventListener("click", (e) => {
      const i = e.target.closest(".ds-rowedit") ? +e.target.closest(".ds-rowedit").dataset.i : -1;
      if (e.target.closest("#ds-addrow")) { rows = readRows(); rows.push(Object.assign({}, BLANK_ROW)); drawRows(); return; }
      if (i < 0) return;
      const rowEl = e.target.closest(".ds-rowedit");
      if (e.target.closest("[data-fadd]")) { rowEl.querySelector(".ds-fl").insertAdjacentHTML("beforeend", filterRowHtml(rowEl._fields || [], { field: "", op: "=", value: "" })); return; }
      if (e.target.closest("[data-frm]")) { e.target.closest(".ds-f").remove(); return; }
      if (e.target.closest("[data-fclear]")) { delete rowEl.dataset.raw; paintFilters(rowEl, rowEl.dataset.dt, []); return; }
      const mv = e.target.closest("[data-mv]");
      if (mv) { rows = readRows(); const j = i + +mv.dataset.mv; [rows[i], rows[j]] = [rows[j], rows[i]]; drawRows(); }
      else if (e.target.closest("[data-rm]")) { rows = readRows(); rows.splice(i, 1); if (!rows.length) rows.push(Object.assign({}, BLANK_ROW)); drawRows(); }
    });
    const first = el.querySelector("input"); if (first) first.focus();
  }

  function editJob() {
    if (["Queued", "Running"].includes(data.job.status)) { PH.toast("Pause or cancel the job before changing it.", "warn"); return; }
    Promise.all([write("get_job_form", { name: data.job.name }), write("list_sites", {})]).then(([f, sites]) => openEditor(f, "Edit Seed Job", sites)).catch(() => {});
  }

  /* ── Wiring ────────────────────────────────────────────────────── */
  PH.$("#actions").addEventListener("click", (e) => {
    const b = e.target.closest("[data-act]");
    if (b && !b.disabled && ACTIONS[b.dataset.act]) ACTIONS[b.dataset.act]();
  });
  PH.$("#new-job").addEventListener("click", () => write("list_sites", {}).then((sites) => openEditor(BLANK, "New Seed Job", sites)).catch(() => {}));
  PH.$("#back").addEventListener("click", () => { data = null; tDocs = null; st.set({ job: "", level: "", dt: "", q: "" }); });
  PH.pills("#f-level", st, "level");
  PH.bindSelect("#f-dt", st, "dt");
  PH.bindSearch("#f-q", st, "q", 400);
  st.on((s, changed) => {
    if (changed.length && changed.every((k) => ["level", "dt", "q"].includes(k)) && data) { load(false); return; }
    data = null; tDocs = null;
    load(true);
  });
  PH.onRefresh(() => load(!data));
  load(true);
})();
