(function () {
  "use strict";
  const API = "upande_dev_tools.api.v2.hooks_explorer.";
  const VIEWS = ["overview", "hooks", "doctypes", "app", "checks"];
  const DEFAULT_RAW_APP = "upande_kaitet";
  const st = PH.state({ view: "overview", app: "", cat: "", hook: "", dt: "", status: "", q: "", raw: "", rq: "" });
  let data = null, seq = 0, raw = null, rawLoaded = "", rawSeq = 0;
  const n = PH.fmt.num;
  const plural = PH.fmt.plural;

  PH.bindSelect("#f-app", st, "app");
  PH.bindSelect("#f-cat", st, "cat");
  PH.bindSelect("#f-hook", st, "hook");
  PH.bindSelect("#f-dt", st, "dt");
  PH.bindSelect("#f-status", st, "status");
  PH.bindSearch("#f-q", st, "q");
  PH.$("#raw-app").addEventListener("change", (e) => st.set({ raw: e.target.value }));  // no default in the URL: the page picks one
  PH.bindSearch("#raw-q", st, "rq");
  PH.$("#tabs").addEventListener("click", (e) => {
    const b = e.target.closest("[data-view]");
    if (b) st.set({ view: b.dataset.view });
  });
  PH.$("#clear").addEventListener("click", () => st.set({ app: "", cat: "", hook: "", dt: "", status: "", q: "" }));

  const FILTER_KEYS = ["app", "cat", "hook", "dt", "status", "q"];
  function currentView() { const v = st.get("view"); return VIEWS.includes(v) ? v : "overview"; }
  function paintView() {
    const v = currentView();
    PH.$$("#tabs .ph-tab").forEach((b) => b.classList.toggle("is-on", b.dataset.view === v));
    VIEWS.forEach((x) => { PH.$("#view-" + x).hidden = x !== v; });
    const exp = PH.$("#export");
    exp.disabled = !data || !CSV_OF[v];
    exp.title = CSV_OF[v] ? "Download this table as CSV" : "Open a table tab to export it";
    PH.$("#clear").hidden = !FILTER_KEYS.some((k) => st.get(k));
    if (v === "app" && data && rawLoaded !== rawApp()) loadRaw();
  }
  const RAW_KEYS = ["raw", "rq"];
  st.on((s, changed) => {
    paintView();
    if (changed.every((k) => k === "view" || RAW_KEYS.includes(k))) {
      if (changed.includes("rq")) renderRaw();
      return;
    }
    if (changed.length === 1 && changed[0] === "q" && PH.$("#f-q") !== document.activeElement) PH.$("#f-q").value = s.q;
    load();
  });

  PH.kpiSkeleton("#kpis", ["Hooks registered", "Apps with hooks", "On every doctype", "Doctypes touched", "Worth a look"]);

  const kindBadge = (r) => r.found === false ? '<span class="ph-badge ph-badge--warn">not found</span>'
    : r.overridden ? '<span class="ph-badge ph-badge--warn">replaced</span>'
    : r.duplicate_of_count > 1 ? '<span class="ph-badge ph-badge--warn">listed twice</span>'
    : r.found === true ? '<span class="ph-badge ph-badge--outline">found</span>' : "";

  const CSVS = {
    apps: { file: "hooks_per_app", cols: [["order", "Run order"], ["app", "App"], ["count", "Hooks"]] },
    hooks: { file: "hooks", cols: [["app", "App"], ["app_order", "Run order"], ["category", "Hook type"], ["hook", "Hook name"], ["scope", "For"], ["event", "Event"], ["handler", "Handler"], ["found", "Handler found"]] },
    doctypes: { file: "hooks_by_doctype", cols: [["label", "Document type"], ["handlers", "Hooks"], ["events_text", "Events"], ["apps_text", "Apps"]] },
  };
  const CSV_OF = { overview: "apps", hooks: "hooks", doctypes: "doctypes" };

  function copyText(text, what) {
    const done = () => PH.toast(what + " copied", "good");
    const fallback = () => {
      const ta = document.createElement("textarea");
      ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); done(); } catch (e) { PH.toast("Could not copy", "bad"); }
      ta.remove();
    };
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done, fallback);
    else fallback();
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-copy]");
    if (b) copyText(b.dataset.copy, b.dataset.what || "Text");
  });

  const tHooks = PH.table("#t-hooks", {
    columns: [
      { key: "app", label: "App", cls: "is-strong" },
      { key: "category", label: "Type" },
      { key: "hook", label: "Hook", cls: "ph-mono" },
      { key: "scope", label: "For", format: (v) => v === "*" ? "Every document type" : (v || "—") },
      { key: "event", label: "Event", format: (v) => v || "—" },
      { key: "handler", label: "Handler", cls: "is-wrap hx-path" },
      { key: "found", label: "", sortable: false, html: (v, r) => kindBadge(r) },
    ],
    rows: [], compact: true, pageSize: 25, empty: "No hooks match these filters",
    sort: { key: "app", dir: "asc" },
    onRowClick: (r) => detail(r),
  });
  const tDt = PH.table("#t-doctypes", {
    columns: [
      { key: "label", label: "Document type", cls: "is-strong" },
      { key: "handlers", label: "Hooks", num: true, total: true },
      { key: "events_text", label: "Events", cls: "is-wrap" },
      { key: "apps_text", label: "Apps", cls: "is-wrap" },
    ],
    rows: [], compact: true, pageSize: 25, empty: "No document-type hooks match these filters",
    sort: { key: "handlers", dir: "desc" },
    onRowClick: (r) => st.set({ dt: r.doctype === "*" ? "" : r.doctype, hook: r.doctype === "*" ? "doc_events" : "", view: "hooks" }),
  });
  const tChecks = PH.table("#t-checks", {
    columns: [
      { key: "hook", label: "Hook", cls: "ph-mono is-strong" },
      { key: "per_app_total", label: "Added up from each app", num: true },
      { key: "merged_total", label: "Frappe merged", num: true },
      { key: "ok", label: "", sortable: false, html: (v, r) => r.per_app_total === r.merged_total ? '<span class="ph-badge ph-badge--good">matches</span>' : '<span class="ph-badge ph-badge--warn">differs</span>' },
    ],
    rows: [], compact: true, empty: "No checks",
  });

  /* ---- detail drill-down ---- */
  function detail(r) {
    const body = document.createElement("div");
    PH.skeleton(body);
    const m = PH.modal({ title: r.hook + (r.event ? " · " + r.event : ""), sub: r.app + " · " + r.category, body, size: "lg" });
    PH.call(API + "get_hook_detail", { app: r.app, id: r.id }).then((d) => {
      const e = d.entry, loc = d.location || {}, ap = d.app || {};
      const kv = [
        ["App", e.app + (ap.title && ap.title !== e.app ? " (" + ap.title + ")" : "") + " · app #" + e.app_order + " in run order"],
        ["Hook", e.hook + " (" + e.category + ")"],
        ["For", e.scope === "*" ? "Every document type" : (e.scope || "—")],
        ["Event", e.event || "—"],
      ];
      let h = '<dl class="ph-kv">' + kv.map(([k, v]) => "<dt>" + PH.esc(k) + "</dt><dd>" + PH.esc(v) + "</dd>").join("");
      h += "<dt>Handler</dt><dd class=\"hx-path\">" + PH.esc(e.handler) + "</dd>";
      if (loc.file) h += "<dt>File</dt><dd class=\"hx-path\">" + PH.esc(loc.file) + (loc.line ? ":" + loc.line : "") + "</dd>";
      if (loc.doc) h += "<dt>What it says</dt><dd>" + PH.esc(loc.doc) + "</dd>";
      if (e.kind === "python") {
        h += "<dt>Status</dt><dd>" + (loc.found ? '<span class="ph-badge ph-badge--good">found in the app folder</span>' : '<span class="ph-badge ph-badge--warn">not found</span> ' + PH.esc(loc.reason || "")) + "</dd>";
      } else if (e.kind === "file" && loc.found != null) {
        h += "<dt>Status</dt><dd>" + (loc.found ? '<span class="ph-badge ph-badge--good">file exists</span>' : '<span class="ph-badge ph-badge--warn">file not found</span>') + "</dd>";
      }
      if (e.duplicate_of_count > 1) h += "<dt>Note</dt><dd>This exact handler is listed " + e.duplicate_of_count + " times for the same event, so it runs that many times.</dd>";
      if (e.overridden) h += "<dt>Note</dt><dd>A later app registers the same override, so this one is replaced.</dd>";
      h += "</dl>";
      h += '<p class="ph-mt ph-flex ph-flex--wrap">' +
        '<button class="ph-btn ph-btn--sm" type="button" data-copy="' + PH.esc(e.handler) + '" data-what="Handler">Copy handler</button> ' +
        '<button class="ph-btn ph-btn--sm" type="button" id="hx-raw-open">Show ' + PH.esc(e.app) + " hooks.py data</button></p>";
      if (e.doctype) h += '<p class="ph-mt"><a class="ph-link" target="_blank" rel="noopener" href="/app/doctype/' + encodeURIComponent(e.doctype) + '">Open the ' + PH.esc(e.doctype) + " DocType</a></p>";
      if (d.same_event && d.same_event.length > 1) {
        h += '<h3 class="ph-card__title ph-mt">Run order for this ' + (e.hook === "doc_events" ? "event" : "hook") + '</h3><div class="hx-order">' +
          d.same_event.map((x, i) => '<div class="' + (x.id === e.id ? "is-me" : "") + '"><span>' + (i + 1) + "</span><span>" + PH.esc(x.app) + "</span><span class=\"hx-path\">" + PH.esc((x.scope === "*" ? "(every doctype) " : "") + x.handler + (x.overridden ? "  (replaced)" : "")) + "</span></div>").join("") + "</div>";
      }
      body.innerHTML = h;
      PH.$("#hx-raw-open", body).addEventListener("click", () => { m.close(); st.set({ raw: e.app, rq: e.hook, view: "app" }); });
    }).catch((err) => { PH.error(body, err.message, () => { m.close(); detail(r); }); });
  }

  /* ---- load + render ---- */
  function args(extra) {
    const s = st.get();
    return Object.assign({ app: s.app, category: s.cat, hook: s.hook, doctype: s.dt, status: s.status, q: s.q }, extra || {});
  }
  function load() {
    const my = ++seq;
    PH.loadingKpis("#kpis", true);
    return PH.call(API + "get_hooks_overview", args())
      .then((m) => { if (my !== seq) return; data = m; render(); PH.markUpdated(); })
      .catch((e) => {
        if (my !== seq) return;
        PH.loadingKpis("#kpis", false);
        ["#t-apps", "#by-cat", "#by-hook", "#t-hooks", "#t-doctypes", "#t-checks"].forEach((x) => PH.error(x, e.message, () => load()));
        PH.set("#notes", ""); PH.set("#c-look", "");
        paintView();
      });
  }

  function bars(sel, rows, onClick) {
    const max = Math.max(1, ...rows.map((x) => x.count));
    PH.set(sel, rows.map((x, i) =>
      `<div class="hx-bar" data-i="${i}" title="${PH.esc(x.label)}: ${PH.esc(n(x.count))}"><span>${PH.esc(x.label)}</span><b>${n(x.count)}</b><div class="ph-progress"><i class="good" style="width:${(100 * x.count) / max}%"></i></div></div>`
    ).join("") || '<div class="ph-empty">No hooks match these filters</div>');
    PH.$$(".hx-bar", PH.$(sel)).forEach((el) => el.addEventListener("click", () => onClick(rows[+el.dataset.i])));
  }

  function render() {
    const d = data, s = st.get(), t = d.totals;
    PH.options("#f-app", d.by_app.map((a) => ({ value: a.app, label: a.app })), s.app);
    PH.options("#f-cat", d.categories, s.cat);
    PH.options("#f-hook", d.hooks.filter((x) => !s.cat || x[0] === s.cat).map((x) => x[1]), s.hook);
    PH.options("#f-dt", d.doctype_options, s.dt);

    const scope = [s.app, s.cat, s.hook, s.dt, s.status && PH.$("#f-status").selectedOptions[0].textContent, s.q && '"' + s.q + '"'].filter(Boolean);
    PH.text("#sub", (t.entries ? plural(t.entries, "hook", "hooks") + " in " + plural(t.apps_with_hooks, "app", "apps") : "No hooks found") +
      " · " + t.installed_apps + " apps installed" + (scope.length ? " · " + scope.join(" · ") : ""));

    const look = t.missing_handlers + t.listed_twice + t.overridden;
    PH.kpis("#kpis", [
      { label: "Hooks registered", value: t.entries, unit: t.entries === t.all_entries ? "across all apps" : "of " + n(t.all_entries) + " in total", dark: true, title: "Each registration counted once: one per doctype, event and handler for document events" },
      { label: "Apps with hooks", value: t.apps_with_hooks, unit: "of " + t.installed_apps + " installed" },
      { label: "On every doctype", value: t.on_every_doctype, unit: 'events with "*"', title: "Document events registered for every document type (*). Counted once here, not once per document type", onClick: () => st.set({ hook: "doc_events", dt: "", q: "", view: "hooks", status: "" }) },
      { label: "Doctypes touched", value: t.doctypes_touched, unit: "have a hook" },
      { label: "Worth a look", value: look, unit: look ? t.missing_handlers + " missing · " + t.listed_twice + " repeated" : "nothing flagged", onClick: () => st.set({ view: "checks" }) },
    ]);

    const notes = [];
    if (t.missing_handlers) notes.push(`<div class="ph-notice ph-notice--signal">${n(t.missing_handlers)} handlers named in hooks.py could not be found in the app folders. The hook is skipped or fails when its event happens. See the Checks tab.</div>`);
    PH.set("#notes", notes.join(""));

    // overview: apps x types matrix
    const cats = d.categories;
    const appRows = d.by_app.map((a) => Object.assign({ app: a.app, order: a.order, count: a.count }, a.by_category));
    PH.table("#t-apps", {
      columns: [
        { key: "order", label: "#", num: true, width: 40 },
        { key: "app", label: "App", cls: "is-strong" },
        { key: "count", label: "Total", num: true, total: true, cls: "is-strong" },
      ].concat(cats.map((c) => ({ key: c, label: c, num: true, total: true, format: (v) => (v ? n(v) : "·") }))),
      rows: appRows, compact: true, pageSize: 40, empty: "No apps", sort: { key: "order", dir: "asc" },
      onRowClick: (r) => st.set({ app: r.app, view: "hooks" }),
    });
    bars("#by-cat", d.by_category.filter((c) => c.count).map((c) => ({ label: c.category, count: c.count, cat: c.category })), (r) => st.set({ cat: r.cat, hook: "" }));
    bars("#by-hook", d.by_hook.slice(0, 12).map((h) => ({ label: h.hook, count: h.count, hook: h.hook, cat: h.category })), (r) => st.set({ cat: r.cat, hook: r.hook, view: "hooks" }));

    // all hooks
    tHooks.update(d.rows);
    PH.text("#tc-hooks", n(t.entries));
    PH.text("#hooks-meta", d.truncated ? "Showing the first " + n(d.row_limit) + " of " + n(t.entries) + " hooks (in run order). Narrow the filters, or export CSV for all of them." : "Click a row to see the handler and where it lives");

    // doctypes
    const dts = d.doctypes.map((r) => Object.assign({}, r, { events_text: r.events.join(", "), apps_text: r.apps.join(", ") }));
    d.doctypes = dts;
    tDt.update(dts);
    PH.text("#tc-doctypes", n(dts.length));

    // checks
    tChecks.update(d.checks);
    const look2 = (k, label, text, status) => `<div class="ph-flex ph-flex--between ph-flex--wrap ph-mb"><div><div class="ph-strong">${PH.esc(label)}: ${n(k)}</div><div class="ph-muted">${PH.esc(text)}</div></div>${k ? `<button class="ph-btn ph-btn--sm" data-status="${status}" type="button">Show them</button>` : ""}</div>`;
    PH.set("#c-look", [
      look2(t.missing_handlers, "Handlers not found", "Named in hooks.py but no function or class with that name was found in the app folder. Usually a leftover from an older version.", "missing"),
      look2(t.listed_twice, "Listed more than once", "The same handler registered twice for the same event (for example by two apps), so it runs twice.", "duplicate"),
      look2(t.overridden, "Replaced by a later app", "Two apps override the same method or class; only the last app's version is used.", "overridden"),
      '<div class="ph-muted">Handlers are found by reading the files as text. Nothing is imported or run.</div>',
    ].join(""));
    PH.$$("#c-look [data-status]").forEach((b) => b.addEventListener("click", () => st.set({ status: b.dataset.status, view: "hooks" })));
    paintView();
  }

  /* ---- one app's hooks.py data (the current page's view) ---- */
  function rawApp() {
    const apps = data ? data.by_app.map((a) => a.app) : [];
    return st.get("raw") || (apps.includes(DEFAULT_RAW_APP) ? DEFAULT_RAW_APP : apps[0] || "");
  }
  function loadRaw() {
    const app = rawApp(), my = ++rawSeq;
    if (!app) return;
    raw = null;
    rawLoaded = app;
    PH.options("#raw-app", data.by_app.map((a) => ({ value: a.app, label: a.app })), app);
    PH.$("#raw-q").value = st.get("rq");
    PH.skeleton("#raw-out");
    PH.call(API + "get_app_hooks_raw", { app_name: app }).then((m) => {
      if (my !== rawSeq) return;
      raw = m; renderRaw();
    }).catch((e) => { if (my === rawSeq) PH.error("#raw-out", e.message, loadRaw); });
  }
  function renderRaw() {
    if (!raw) return;
    const q = st.get("rq").toLowerCase().trim(), out = [];
    if (PH.$("#raw-q") !== document.activeElement) PH.$("#raw-q").value = st.get("rq");
    raw.order.forEach((k, i) => {
      const json = JSON.stringify(raw.hooks[k], null, 2);
      if (q && !(k + " " + json).toLowerCase().includes(q)) return;
      out.push('<div class="hx-sec"><div class="hx-sec__head"><span class="ph-mono ph-strong">' + PH.esc(k) + "</span>" +
        '<button class="ph-btn ph-btn--ghost ph-btn--sm" type="button" data-copy="' + PH.esc(json) + '" data-what="' + PH.esc(k) + '">Copy</button></div>' +
        '<pre class="hx-pre">' + PH.esc(json) + "</pre></div>");
    });
    PH.set("#raw-out", out.join("") || (raw.order.length
      ? '<div class="ph-empty">Nothing in ' + PH.esc(raw.app_name) + ' matches "' + PH.esc(q) + '"</div>'
      : '<div class="ph-empty">No hooks found for this app</div>'));
  }
  PH.$("#raw-copy").addEventListener("click", () => { if (raw) copyText(JSON.stringify(raw.hooks, null, 2), raw.app_name + " hooks"); });

  function exportView() {
    const v = currentView(), c = CSVS[CSV_OF[v]];
    if (!data || !c) return;
    const stamp = new Date().toISOString().slice(0, 10);
    const finish = (rows) => {
      if (!rows.length) return;
      PH.csv(c.file + "_" + stamp + ".csv", rows, c.cols.map(([key, label]) => ({ key, label })));
    };
    if (v === "hooks") {
      PH.call(API + "get_hooks_overview", args({ limit: 5000 })).then((m) => finish(m.rows.map((r) => Object.assign({}, r, { found: r.found === true ? "yes" : r.found === false ? "no" : "" }))));
    } else if (v === "doctypes") {
      finish(data.doctypes);
    } else {
      finish(data.by_app);
    }
  }
  PH.$("#export").addEventListener("click", exportView);
  PH.$$("[data-csv]").forEach((b) => b.addEventListener("click", exportView));

  DevKeys.init({ title: "Hooks Explorer", list: { root: "#ph-main", items: () => PH.$$("#ph-main tbody tr.is-link") } });

  PH.onRefresh(() => load());
  PH.ready(() => { paintView(); load(); });
})();
