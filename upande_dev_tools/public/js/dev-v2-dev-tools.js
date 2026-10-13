(function () {
  "use strict";
  const API = "upande_dev_tools.api.v2.overview.";
  const t = PH.date.today();
  const d90 = [PH.date.add(t, -89), t];
  const st = PH.state({ from: d90[0], to: d90[1], area: "", priority: "", q: "" });
  const FIGURE_KEYS = ["from", "to", "area", "priority"];
  let data = null, seq = 0;
  const n = PH.fmt.num;

  PH.bindSelect("#f-area", st, "area");
  PH.bindSelect("#f-priority", st, "priority");
  const qBox = PH.$("#f-q");
  qBox.value = st.get("q");
  qBox.addEventListener("input", () => st.set({ q: qBox.value.trim() }));
  PH.dateRange({ pills: "#f-preset", from: "#f-from", to: "#f-to", state: st });

  /* presets the shared runtime does not know: 90 days, this year */
  const EXTRA = {
    "90d": () => [PH.date.add(PH.date.today(), -89), PH.date.today()],
    ytd: () => [new Date().getFullYear() + "-01-01", PH.date.today()],
  };
  PH.$("#f-preset").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-value]");
    const f = b && EXTRA[b.dataset.value];
    if (f) { const p = f(); st.set({ from: p[0], to: p[1] }); }
  });
  function paintExtra() {
    const s = st.get();
    Object.keys(EXTRA).forEach((k) => {
      const p = EXTRA[k](), b = PH.$('#f-preset [data-value="' + k + '"]');
      if (b && s.from === p[0] && s.to === p[1]) {
        PH.$$("#f-preset button").forEach((x) => x.classList.remove("is-on"));
        b.classList.add("is-on");
      }
    });
  }
  st.on((_s, changed) => {
    paintExtra();
    if (changed.some((k) => FIGURE_KEYS.includes(k))) load();
    else if (data) renderNav(data);
  });

  PH.kpiSkeleton("#kpis", ["Open requests", "Awaiting review", "Overdue work", "Blocked work"]);
  PH.skeleton("#attention", "rows", 4);

  const ico = (name) => '<span class="dov-ico">' + ((window.DOV_ICONS || {})[name] || "") + "</span>";
  const filterText = () => {
    const s = st.get();
    return [s.area, s.priority && s.priority + " priority"].filter(Boolean);
  };

  /* ---- drill-down: the records behind a card ---- */
  function drill(k) {
    const s = st.get();
    const body = document.createElement("div");
    PH.skeleton(body, "rows", 6);
    const m = PH.modal({ title: k.label, sub: k.unit + " · " + PH.date.label(s.from, s.to), body, size: "xl" });
    PH.call(API + "get_overview_items", { kpi: k.key, from_date: s.from, to_date: s.to, product_area: s.area, priority: s.priority })
      .then((d) => {
        body.innerHTML = '<div class="dov-dr-head"><div class="ph-strong">' + PH.esc(n(d.total)) + " in total</div><div>" +
          (k.route ? '<a class="ph-btn ph-btn--sm" href="' + PH.esc(k.route) + '">Open the page</a> ' : "") +
          '<button class="ph-btn ph-btn--sm" type="button" data-dl>Export CSV</button></div></div>' +
          (d.truncated ? '<div class="ph-notice ph-notice--signal">Showing the first ' + PH.esc(n(d.row_limit)) + " of " + PH.esc(n(d.total)) + ". The figure on the card counts all of them.</div>" : "") +
          '<div id="dov-rows"></div>';
        PH.table(body.querySelector("#dov-rows"), {
          rows: d.rows, compact: true, pageSize: 25, empty: "Nothing to list for these filters",
          columns: [
            { key: "title", label: "Item", cls: "is-strong", html: (v, r) => '<a class="ph-link" target="_blank" rel="noopener" href="' + PH.esc(r.url) + '">' + PH.esc(v || r.name) + "</a>" },
            { key: "name", label: "Reference", cls: "ph-mono", format: (v) => String(v) },
            { key: "status", label: "Status" },
            { key: "priority", label: "Priority", format: (v) => v || "—" },
            { key: "detail", label: "Detail", format: (v) => v || "—" },
            { key: "date", label: "Date" },
          ],
        });
        body.querySelector("[data-dl]").addEventListener("click", () =>
          PH.csv("dev_tools_" + k.key + "_" + s.from + "_" + s.to + ".csv", d.rows, [
            { key: "name", label: "Reference" }, { key: "title", label: "Item" }, { key: "status", label: "Status" },
            { key: "priority", label: "Priority" }, { key: "detail", label: "Detail" }, { key: "date", label: "Date" },
          ]));
      })
      .catch((e) => PH.error(body, e.message, () => { m.close(); drill(k); }));
  }

  /* ---- render ---- */
  function renderKpis(d) {
    const s = st.get(), filtered = !!(s.area || s.priority);
    PH.kpis("#kpis", d.kpis.map((k, i) => ({
      label: k.label,
      value: k.value == null ? "—" : k.value,
      suffix: k.suffix || "",
      unit: k.unit,
      title: k.title,
      onClick: () => drill(k),
    })));
    PH.$$("#kpis .ph-kpi").forEach((el, i) => {
      const k = d.kpis[i];
      if (k.tone) el.classList.add(k.tone === "good" ? "dov-good" : "dov-warn");
      const extra = [];
      if (k.detail) extra.push(k.detail);
      if (k.note && (filtered || /current state/.test(k.note))) extra.push(k.note);
      if (extra.length) el.insertAdjacentHTML("beforeend", '<div class="dov-note">' + PH.esc(extra.join(" · ")) + "</div>");
    });
  }

  function renderAttention(d) {
    if (!d.attention.length) {
      PH.empty("#attention", "Nothing needs attention", "No slow reviews, overdue work, failed deployments or app issues for these filters.", "check");
      return;
    }
    PH.set("#attention", '<div class="ph-list">' + d.attention.map((a, i) =>
      '<div class="ph-list__row is-link" data-i="' + i + '" role="link" tabindex="0"><span class="ph-dot ph-dot--warn"></span><div><div class="ph-list__name">' +
      PH.esc(a.text) + '</div><div class="ph-list__meta">' + PH.esc(a.detail || "") + "</div></div><span class=\"ph-muted\">" + PH.icon("arrowRight", 14) + "</span></div>"
    ).join("") + "</div>");
    PH.$$("#attention [data-i]").forEach((el) => {
      const go = () => { window.location.href = d.attention[+el.dataset.i].route; };
      el.addEventListener("click", go);
      el.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
    });
  }

  function bucketLabel(iso, mode) {
    const dt = PH.date.parse(iso);
    if (mode === "month") return dt.toLocaleDateString("en-GB", { month: "short", year: "numeric" });
    const base = dt.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
    return mode === "week" ? "Week of " + base : base;
  }

  function renderChart(d) {
    const c = d.chart, any = c.opened_total + c.closed_total > 0;
    const unit = { day: "per day", week: "per week (Monday to Sunday)", month: "per month" }[c.granularity];
    PH.text("#chart-meta", "Counted " + unit + " · closed means Completed, Rejected, Withdrawn or Closed");
    PH.text("#chart-sum", n(c.opened_total) + " opened and " + n(c.closed_total) + " closed in this range. Requests are counted by the day they were opened and the day they reached a closed state.");
    PH.$("#chart-csv").disabled = !any;
    if (!any) { PH.empty("#c-trend", "No requests in this range", "Nothing was opened or closed for these filters.", "inbox"); return; }
    PH.chart("#c-trend", {
      type: "line", legend: true,
      labels: c.labels.map((l) => bucketLabel(l, c.granularity)),
      series: [
        { label: "Opened", data: c.opened, color: PH.statusColor.ink, fill: false },
        { label: "Closed", data: c.closed, color: PH.statusColor.good, fill: false },
      ],
      yFormat: (v) => (Number.isInteger(v) ? n(v) : ""),
      options: { elements: { line: { cubicInterpolationMode: "monotone" } } },
    });
  }

  const tileHtml = (p, desk) => {
    const foot = desk
      ? '<span class="ph-badge">Desk list</span>'
      : p.beta
        ? ""
        : '<span class="ph-badge ph-badge--signal">No new version yet</span>';
    return '<div class="ph-tile is-link dov-tile"><a class="dov-tile__link" href="' + PH.esc(p.href) + '"><div class="ph-tile__head">' + ico(p.icon) +
      '<div><div class="ph-tile__name">' + PH.esc(p.label) + '</div></div></div><div class="ph-tile__sub">' + PH.esc(p.blurb) + "</div></a>" +
      '<div class="dov-tile__foot">' + foot + "</div></div>";
  };

  function renderStart(d) {
    const l = d.landing, chips = [];
    if (l.last) chips.push('<a class="ph-btn ph-btn--primary" href="' + PH.esc(l.last.href) + '">Continue: ' + PH.esc(l.last.label) + "<small>where you left off</small></a>");
    if (l.home) chips.push('<a class="ph-btn' + (l.last ? "" : " ph-btn--primary") + '" href="' + PH.esc(l.home.href) + '">' + PH.esc(l.home.label) + "<small>your home page</small></a>");
    d.quick.forEach((q) => chips.push('<a class="ph-btn" href="' + PH.esc(q.href) + '">' + (window.DOV_ICONS[q.icon] || "") + PH.esc(q.label) + "</a>"));
    PH.set("#start", chips.join(""));
  }

  /** Tiles whose label or description contains every word typed in the search box. */
  function renderNav(d) {
    const words = st.get("q").toLowerCase().split(/\s+/).filter(Boolean);
    const hit = (p) => { const t = (p.label + " " + p.blurb).toLowerCase(); return words.every((w) => t.includes(w)); };
    const block = (groups, desk) => groups.map((g) => ({ group: g.group, pages: g.pages.filter(hit) })).filter((g) => g.pages.length).map((g) =>
      '<div class="dov-group"><h2>' + PH.esc(g.group) + '</h2><div class="ph-tiles ph-tiles--sm">' + g.pages.map((p) => tileHtml(p, desk)).join("") + "</div></div>").join("");
    const html = block(d.nav, false) + block(d.desk, true);
    if (html) PH.set("#nav", html);
    else PH.empty("#nav", "No page matches", "Nothing you may open matches \u201c" + st.get("q") + "\u201d.", "inbox");
  }

  function render() {
    const d = data, s = st.get();
    PH.options("#f-area", [{ value: "", label: "All product areas" }].concat(d.options.product_areas.map((a) => ({ value: a, label: a }))), s.area);
    PH.options("#f-priority", [{ value: "", label: "All priorities" }].concat(d.options.priorities.map((a) => ({ value: a, label: a }))), s.priority);
    const r = d.requests, ft = filterText();
    PH.text("#sub", n(r.open) + " of " + PH.fmt.plural(r.opened, "request") + " still open · " + PH.date.label(s.from, s.to) + (ft.length ? " · " + ft.join(" · ") : ""));
    renderKpis(d);
    renderAttention(d);
    renderChart(d);
    renderStart(d);
    renderNav(d);
    PH.$("#export").disabled = !d.kpis.length;
  }

  function load() {
    const s = st.get(), my = ++seq;
    PH.loadingKpis("#kpis", true);
    return PH.call(API + "get_overview", { from_date: s.from, to_date: s.to, product_area: s.area, priority: s.priority })
      .then((m) => { if (my !== seq) return; data = m; render(); PH.markUpdated(); })
      .catch((e) => {
        if (my !== seq) return;
        PH.loadingKpis("#kpis", false);
        ["#kpis", "#attention", "#c-trend", "#nav"].forEach((x) => PH.error(x, e.message, () => load()));
      });
  }

  PH.$("#export").addEventListener("click", () => {
    if (!data) return;
    const s = st.get();
    const rows = data.kpis.map((k) => ({
      figure: k.label, value: k.value == null ? "" : k.value + (k.suffix ? " " + k.suffix : ""), detail: [k.unit, k.detail].filter(Boolean).join(" · "),
      filters: k.note || "all filters applied", definition: k.title,
    }));
    PH.csv("dev_tools_overview_" + s.from + "_" + s.to + ".csv", rows, [
      { key: "figure", label: "Figure" }, { key: "value", label: "Value" }, { key: "detail", label: "Detail" },
      { key: "filters", label: "Filters" }, { key: "definition", label: "Definition" },
    ]);
  });
  PH.$("#chart-csv").addEventListener("click", () => {
    if (!data) return;
    const c = data.chart, s = st.get();
    PH.csv("requests_opened_closed_" + s.from + "_" + s.to + ".csv",
      c.labels.map((l, i) => ({ from: l, opened: c.opened[i], closed: c.closed[i] })),
      [{ key: "from", label: c.granularity === "day" ? "Day" : c.granularity === "week" ? "Week starting" : "Month starting" }, { key: "opened", label: "Opened" }, { key: "closed", label: "Closed" }]);
  });

  DevKeys.init({ title: "Dev Tools Overview", list: { root: "#ph-main", items: () => PH.$$("#ph-main .ph-list__row.is-link, #ph-main tbody tr.is-link") } });

  PH.onRefresh(() => load());
  PH.ready(() => { paintExtra(); load(); });
})();
