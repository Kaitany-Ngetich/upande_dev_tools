/* Deployments v2 page script. Reads: api.v2.deployments; writes: the existing api.deployments endpoints. */
(function () {
  "use strict";
  const API = "upande_dev_tools.api.v2.deployments.";
  const WRITE_API = "upande_dev_tools.api.deployments.";
  const VIEWS = ["overview", "queue", "requests", "instances", "mine"];
  const WORKFLOW_STATES = ["Requested", "In Progress", "Deployed", "Failed"];
  const caps = PH.$("#dp-caps").dataset;
  const CAN_CREATE = caps.canCreate === "1";
  const IS_APPROVER = caps.isApprover === "1";
  const CAN_CHANGE_STATE = caps.canChangeState === "1";
  /* The workflow's own next steps per state. `action` is what update_deployment_status expects;
     `field` is the optional detail worth asking for on the way (null fires immediately). */
  const STATE_ACTIONS = {
    "Requested": [{ action: "Start Deployment", label: "Start", field: null }],
    "In Progress": [
      { action: "Mark Deployed", label: "Mark deployed", field: "commit_hash" },
      { action: "Mark Failed", label: "Mark failed", field: "errors" },
    ],
    "Failed": [{ action: "Retry", label: "Retry", field: "fix_notes" }],
  };
  const FIELD_PROMPT = {
    commit_hash: { label: "Commit hash", type: "text", placeholder: "e.g. abc1234", hint: "Optional. The commit that went live." },
    errors: { label: "What went wrong", type: "textarea", hint: "Optional." },
    fix_notes: { label: "What was fixed", type: "textarea", hint: "Optional." },
  };
  const d90 = PH.date.add(PH.date.today(), -89);
  const st = PH.state({ view: "overview", from: d90, to: PH.date.today(), stage: "", instance: "", app: "", requester: "", q: "", group: "stage", mstatus: "" });
  let data = null, seq = 0, iseq = 0, mseq = 0, inst = null, instKey = "";
  const n = PH.fmt.num;
  const STAGE_BADGE = { "Deployed": "good", "Failed": "bad", "In Progress": "signal", "Requested": "ink", "Waiting approval": "warn", "Declined": "outline" };
  const STAGE_COLOR = { "Deployed": PH.statusColor.good, "Failed": PH.statusColor.bad, "In Progress": PH.statusColor.signal, "Requested": PH.statusColor.ink, "Waiting approval": PH.statusColor.warn, "Declined": PH.statusColor.mute };
  const badge = (s) => '<span class="ph-badge ph-badge--' + (STAGE_BADGE[s] || "outline") + '">' + PH.esc(s) + "</span>";
  const dur = (h) => (h == null ? "—" : h < 1 ? Math.max(1, Math.round(h * 60)) + " min" : h < 48 ? (Math.round(h * 10) / 10) + " h" : (Math.round(h / 24 * 10) / 10) + " days");
  const age = (d) => (d == null ? "—" : d < 2 ? Math.round(d * 24) + " h" : Math.round(d) + " days");
  const when = (s) => (s ? PH.fmt.date(String(s).slice(0, 10)) + " " + String(s).slice(11, 16) : "—");
  const dayOnly = (s) => (s ? PH.fmt.date(String(s).slice(0, 10)) : "—");
  const docLink = (dt, name) => '<a class="ph-link ph-mono" target="_blank" rel="noopener" href="/app/' + dt + "/" + encodeURIComponent(name) + '">' + PH.esc(name) + "</a>";
  const rate = (v) => (v == null ? "—" : v + "%");

  PH.$("#dp-search-ico").innerHTML = PH.icon("search", 16);
  PH.bindSelect("#f-stage", st, "stage");
  PH.bindSelect("#f-instance", st, "instance");
  PH.bindSelect("#f-app", st, "app");
  PH.bindSelect("#f-requester", st, "requester");
  PH.bindSearch("#f-q", st, "q");
  PH.options("#f-mine", [{ value: "", label: "All statuses" }].concat(WORKFLOW_STATES.map((x) => ({ value: x, label: x }))), st.get("mstatus"));
  PH.bindSelect("#f-mine", st, "mstatus");
  PH.pills("#f-group", st, "group");
  PH.dateRange({ state: st, from: "#f-from", to: "#f-to" });
  const presets = () => {
    const t = PH.date.today();
    return { "30d": [PH.date.add(t, -29), t], "90d": [PH.date.add(t, -89), t], "1y": [PH.date.add(t, -364), t], all: ["", ""] };
  };
  PH.$("#f-preset").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-value]");
    if (!b) return;
    const p = presets()[b.dataset.value];
    st.set({ from: p[0], to: p[1] });
  });
  function paintPresets() {
    const s = st.get(), P = presets();
    PH.$$("#f-preset button").forEach((b) => b.classList.toggle("is-on", P[b.dataset.value][0] === s.from && P[b.dataset.value][1] === s.to));
  }
  PH.$("#tabs").addEventListener("click", (e) => {
    const b = e.target.closest("[data-view]");
    if (b) st.set({ view: b.dataset.view });
  });
  PH.kpiSkeleton("#kpis", ["Requests raised", "Open now", "Success rate", "Time to deploy", "Waiting approval"]);

  const stageCol = { key: "stage", label: "Status", html: (v) => badge(v), sortValue: (r) => ["Failed", "Waiting approval", "In Progress", "Requested", "Deployed", "Declined"].indexOf(r.stage) };
  const reqLink = { key: "name", label: "Request", cls: "ph-mono is-strong" };
  const reqCols = [
    reqLink,
    { key: "app", label: "App" },
    { key: "instance", label: "Instance" },
    { key: "branch", label: "Branch", format: (v) => v || "—" },
    stageCol,
    { key: "requested_by_name", label: "Requested by", format: (v) => v || "—" },
    { key: "creation", label: "Raised", format: (v, r) => dayOnly(v) + (r.future_dated ? " (future date)" : "") },
  ];
  const openRow = (r) => drill(r.name);
  const actionsCol = { key: "actions", label: "", sortable: false, html: (v, r) => PH.raw(actionButtons(r)) };
  const withActions = (cols) => {
    if (!(CAN_CHANGE_STATE || IS_APPROVER || CAN_CREATE)) return cols;
    const at = cols.indexOf(stageCol) + 1;
    return cols.slice(0, at).concat([actionsCol], cols.slice(at));
  };
  const tQueue = PH.table("#t-queue", { columns: withActions(reqCols.concat([{ key: "age_days", label: "Age", num: true, format: (v) => age(v) }])), rows: [], compact: true, pageSize: 25, empty: "Nothing is waiting. Every request in this filter is closed.", onRowClick: openRow, sort: { key: "age_days", dir: "desc" } });
  const tReq = PH.table("#t-requests", { columns: withActions(reqCols.concat([{ key: "lead_hours", label: "Time to deploy", num: true, format: (v) => dur(v) }])), rows: [], compact: true, pageSize: 25, empty: "No requests match these filters", onRowClick: openRow, sort: { key: "creation", dir: "desc" } });
  const mineCols = [
    { key: "name", label: "Request", cls: "ph-mono is-strong" },
    { key: "app", label: "App" },
    { key: "instance", label: "Instance" },
    { key: "branch", label: "Branch", format: (v) => v || "—" },
    { key: "workflow_state", label: "Status", html: (v, r) => badge(r.requires_approval && r.approval_status === "Pending" ? "Waiting approval" : v) },
    { key: "creation", label: "Raised", format: (v) => dayOnly(v) },
  ];
  const tMine = PH.table("#t-mine", { columns: mineCols, rows: [], compact: true, pageSize: 25, empty: "You have not raised any deployment request", onRowClick: openRow, sort: { key: "creation", dir: "desc" } });
  const sumCols = (label) => [
    { key: "label", label, cls: "is-strong" },
    { key: "raised", label: "Raised", num: true, total: true },
    { key: "deployed", label: "Deployed", num: true, total: true },
    { key: "failed", label: "Failed", num: true, total: true },
    { key: "open", label: "Open", num: true, total: true },
    { key: "success_rate", label: "Success", num: true, format: (v) => rate(v), sortValue: (r) => r.success_rate },
  ];
  const tInst = PH.table("#t-instance", { columns: sumCols("Instance"), rows: [], compact: true, pageSize: 10, empty: "No requests", onRowClick: (r) => st.set({ instance: r.key }), sort: { key: "raised", dir: "desc" } });
  const tApp = PH.table("#t-app", { columns: sumCols("App"), rows: [], compact: true, pageSize: 10, empty: "No requests", onRowClick: (r) => st.set({ app: r.key }), sort: { key: "raised", dir: "desc" } });

  const CSVS = {
    queue: { file: "deployments_open_queue", key: "open_queue", cols: [["name", "Request"], ["app", "App"], ["instance", "Instance"], ["branch", "Branch"], ["commit_hash", "Commit"], ["stage", "Status"], ["requested_by_name", "Requested by"], ["creation", "Raised"], ["age_days", "Age (days)"]] },
    requests: { file: "deployments_requests", key: "requests", cols: [["name", "Request"], ["app", "App"], ["instance", "Instance"], ["branch", "Branch"], ["commit_hash", "Commit"], ["stage", "Status"], ["requested_by_name", "Requested by"], ["creation", "Raised"], ["lead_hours", "Hours to deploy"]] },
  };
  function currentView() { const v = st.get("view"); return VIEWS.includes(v) ? v : "overview"; }
  function paintView() {
    const v = currentView();
    PH.$$("#tabs .ph-tab").forEach((b) => b.classList.toggle("is-on", b.dataset.view === v));
    VIEWS.forEach((x) => { PH.$("#view-" + x).hidden = x !== v; });
    const rows = data && CSVS[v] ? data[CSVS[v].key] || [] : [];
    const exp = PH.$("#export");
    exp.disabled = !rows.length;
    exp.title = CSVS[v] ? "Download this table as CSV" : "Open the Open queue or All requests tab to export";
  }
  let lastKey = "";
  st.on((s, changed) => {
    paintView();
    paintPresets();
    if (changed.every((k) => k === "view" || k === "mstatus")) {
      if (currentView() === "overview") redrawChart();
      if (currentView() === "instances") loadInstances();
      if (currentView() === "mine") loadMine();
      return;
    }
    load();
    if (currentView() === "instances") loadInstances();
  });

  function args() {
    const s = st.get();
    return { from_date: s.from, to_date: s.to, stage: s.stage, instance: s.instance, app: s.app, requester: s.requester, q: s.q, group_by: s.group };
  }
  function load() {
    const my = ++seq;
    PH.loadingKpis("#kpis", true);
    return PH.call(API + "get_deployments", args(), { silent: true })
      .then((m) => { if (my !== seq) return; data = m; render(); PH.markUpdated(); })
      .catch((e) => {
        if (my !== seq) return;
        PH.loadingKpis("#kpis", false);
        ["#c-trend", "#by-stage", "#top-apps", "#top-requesters", "#t-instance", "#t-app", "#t-queue", "#t-requests"].forEach((x) => PH.error(x, e.message, () => load()));
        PH.set("#notes", "");
        paintView();
      });
  }

  function bars(sel, rows, valueOf, labelOf, onClick, color) {
    const max = Math.max(1, ...rows.map(valueOf));
    PH.set(sel, rows.map((x, i) =>
      `<div class="dp-bar" data-i="${i}" title="${PH.esc(labelOf(x))}: ${PH.esc(n(valueOf(x)))}"><span>${PH.esc(labelOf(x))}</span><b>${n(valueOf(x))}</b><div class="ph-progress"><i class="${color(x)}" style="width:${(100 * valueOf(x)) / max}%"></i></div></div>`
    ).join("") || '<div class="ph-empty"><div class="ph-empty__text">Nothing in this filter</div></div>');
    PH.$$(".dp-bar", PH.$(sel)).forEach((el) => el.addEventListener("click", () => onClick(rows[+el.dataset.i])));
  }

  function redrawChart() {
    if (!data) return;
    const t = data.trend, holder = PH.$("#c-trend");
    if (!t.series.length) { PH.empty(holder, "No requests in this range", "Try a wider date range or clear a filter."); return; }
    const unit = { day: "day", week: "week (Monday)", month: "month" }[t.unit];
    PH.text("#trend-meta", "requests raised per " + unit + ", by the day they were raised");
    PH.chart(holder, {
      type: "line", labels: t.labels, legend: true,
      series: t.series.map((x, i) => ({
        label: x.label + " (" + n(x.total) + ")", data: x.data, fill: false,
        color: t.group_by === "stage" ? STAGE_COLOR[x.key] : (x.key === "__other__" ? PH.statusColor.mute : undefined),
      })),
      yFormat: (v) => (Number.isInteger(v) ? v : ""),
    });
  }

  function render() {
    const d = data, s = st.get(), t = d.totals, o = d.options;
    PH.options("#f-stage", [{ value: "", label: "All statuses" }].concat(o.stages.map((x) => ({ value: x, label: x }))), s.stage);
    PH.options("#f-instance", [{ value: "", label: "All instances" }].concat(o.instances), s.instance);
    PH.options("#f-app", [{ value: "", label: "All apps" }].concat(o.apps), s.app);
    PH.options("#f-requester", [{ value: "", label: "Anyone" }].concat(o.requesters), s.requester);
    const range = s.from || s.to ? PH.date.label(s.from || "", s.to || "") : "all time";
    const scope = [s.stage, s.instance, o.apps.find((a) => a.value === s.app)?.label, o.requesters.find((a) => a.value === s.requester)?.label, s.q && "“" + s.q + "”"].filter(Boolean);
    PH.text("#sub", (t.raised ? PH.fmt.plural(t.raised, "request") : "No requests") + " · " + range + (scope.length ? " · " + scope.join(" · ") : ""));

    const lt = d.lead_time;
    PH.kpis("#kpis", [
      { label: "Requests raised", value: t.raised, unit: n(t.deployed) + " deployed", dark: true, title: "Requests raised in the range, whatever their status. " + n(t.in_flight) + " are still in flight." },
      { label: "Open now", value: t.open, unit: t.open ? "oldest " + age(t.oldest_open_days) : "nothing waiting", title: "Waiting approval, requested, in progress or failed", onClick: () => st.set({ view: "queue" }) },
      { label: "Success rate", value: t.success_rate == null ? "—" : t.success_rate, suffix: t.success_rate == null ? "" : "%", unit: t.finished ? n(t.deployed) + " of " + n(t.finished) + " finished" : "none finished yet", title: "Deployed / (Deployed + Failed). Requests still in flight and declined ones are not counted." },
      { label: "Time to deploy", value: lt.median_hours == null ? "—" : dur(lt.median_hours), unit: lt.measured ? "median · " + n(lt.measured) + " of " + n(lt.deployed) : "no timing recorded", title: "Raised to Deployed, from the change log. Only " + n(lt.measured) + " of " + n(lt.deployed) + " deployed requests have a deployed time on record; the rest are left out." },
      { label: "Waiting approval", value: t.waiting_approval, unit: t.declined ? n(t.declined) + " declined" : "peak hours", onClick: () => st.set({ stage: "Waiting approval", view: "queue" }) },
    ]);

    const notes = [], nt = d.notes;
    if (nt.stale_waiting_approval > 0) notes.push(`<div class="ph-notice ph-notice--warn">${PH.fmt.plural(nt.stale_waiting_approval, "request")} ${nt.stale_waiting_approval === 1 ? "has" : "have"} been waiting for approval for more than ${nt.stale_days} days.</div>`);
    if (nt.stale_in_progress > 0) notes.push(`<div class="ph-notice ph-notice--warn">${PH.fmt.plural(nt.stale_in_progress, "request")} ${nt.stale_in_progress === 1 ? "has" : "have"} been In Progress for more than ${nt.stale_days} days. They may have finished without being marked.</div>`);
    if (nt.future_dated.length) notes.push(`<div class="ph-notice ph-notice--signal">${PH.fmt.plural(nt.future_dated.length, "request")} ${nt.future_dated.length === 1 ? "is" : "are"} dated in the future (${PH.esc(nt.future_dated.map((x) => x.name + " " + x.creation.slice(0, 10)).join(", "))}). They are counted on that date, so a date range ending today leaves them out. Worth correcting on the record.</div>`);
    if (nt.deployed_without_commit > 0) notes.push(`<div class="ph-notice ph-notice--signal">${PH.fmt.plural(nt.deployed_without_commit, "deployed request")} ${nt.deployed_without_commit === 1 ? "has" : "have"} no commit recorded, so the version on the instance is unknown for ${nt.deployed_without_commit === 1 ? "it" : "them"}.</div>`);
    if (o.duplicate_registry_apps.length) notes.push(`<div class="ph-notice ph-notice--signal">${o.duplicate_registry_apps.length} apps are registered under two spellings (${PH.esc(o.duplicate_registry_apps.slice(0, 3).map((x) => x.join(" / ")).join(", "))}${o.duplicate_registry_apps.length > 3 ? ", …" : ""}). Here they are counted as one app.</div>`);
    if (d.truncated) notes.push(`<div class="ph-notice ph-notice--signal">All requests lists the latest ${n(d.row_limit)} of ${n(t.raised)}. Every figure above covers all of them.</div>`);
    PH.set("#notes", notes.join(""));

    PH.text("#tc-queue", n(t.open));
    PH.text("#tc-requests", n(t.raised));
    tQueue.update(d.open_queue);
    tReq.update(d.requests);
    tInst.update(d.by_instance);
    tApp.update(d.by_app);
    bars("#by-stage", d.by_stage.filter((x) => x.count || !s.stage), (x) => x.count, (x) => x.stage, (x) => st.set({ stage: x.stage }), (x) => ({ Deployed: "good", Failed: "bad", "Waiting approval": "warn" }[x.stage] || ""));
    bars("#top-apps", d.by_app.slice(0, 8), (x) => x.raised, (x) => x.label, (x) => st.set({ app: x.key }), () => "good");
    bars("#top-requesters", d.by_requester.slice(0, 8), (x) => x.raised, (x) => x.label, (x) => st.set({ requester: x.key }), () => "good");
    redrawChart();
    paintView();
    paintPresets();
  }

  /* ---- my requests: same endpoint as the current page's own-requests list ---- */
  function loadMine() {
    const my = ++mseq, box = PH.$("#t-mine");
    if (!tMine.rows().length) PH.skeleton(box);
    return PH.call(WRITE_API + "get_my_deployment_requests", { status: st.get("mstatus") }, { silent: true })
      .then((rows) => { if (my !== mseq) return; PH.text("#tc-mine", n(rows.length)); tMine.update(rows); })
      .catch((e) => { if (my === mseq) PH.error(box, e.message, () => loadMine()); });
  }

  /* ---- instances: current state ---- */
  function loadInstances() {
    const s = st.get(), key = s.instance + "|" + s.app, my = ++iseq;
    const box = PH.$("#instances");
    if (!inst || key !== instKey) PH.skeleton(box);
    return PH.call(API + "get_deployment_instances", { instance: s.instance, app: s.app }, { silent: true })
      .then((m) => { if (my !== iseq) return; inst = m.instances; instKey = key; renderInstances(); })
      .catch((e) => { if (my === iseq) PH.error(box, e.message, () => loadInstances()); });
  }
  function renderInstances() {
    PH.text("#tc-instances", n(inst.length));
    const box = PH.$("#instances");
    if (!inst.length) { PH.empty(box, "No instances", "No instance matches this filter."); return; }
    PH.set(box, '<div class="dp-inst">' + inst.map((i) => {
      const last = i.last_deployed;
      const apps = i.apps.length
        ? '<table class="dp-apps"><thead><tr><th>App</th><th>Branch</th><th>Commit</th><th>Latest deploy</th></tr></thead><tbody>' + i.apps.map((a) =>
          `<tr data-req="${PH.esc(a.latest.name)}" style="cursor:pointer"><td class="ph-strong">${PH.esc(a.app)}${a.deployed_count > 1 ? ' <span class="ph-muted">×' + a.deployed_count + "</span>" : ""}</td><td>${PH.esc(a.latest.branch || "—")}</td><td class="ph-mono">${PH.esc(a.latest.commit_hash || "not recorded")}</td><td>${PH.esc(dayOnly(a.latest.creation))}${a.latest.future_dated ? " (future date)" : ""}</td></tr>`).join("") + "</tbody></table>"
        : '<div class="ph-muted">Nothing deployed here yet</div>';
      const dup = i.duplicate_spellings.length ? `<div class="ph-notice ph-notice--signal ph-mt">Same app recorded under two spellings here: ${PH.esc(i.duplicate_spellings.map((x) => x.join(" / ")).join("; "))}.</div>` : "";
      return `<section class="ph-card"><div class="ph-card__head"><div><h2 class="ph-card__title">${PH.esc(i.name)}</h2><div class="ph-card__meta">${PH.esc(i.environment || "")}</div></div>${i.open ? '<span class="ph-badge ph-badge--warn">' + n(i.open) + " open</span>" : ""}</div>
        <div class="dp-stats ph-mb"><div><small class="ph-muted">Requests</small><b>${n(i.requests)}</b></div><div><small class="ph-muted">Deployed</small><b>${n(i.deployed)}</b></div><div><small class="ph-muted">Failed</small><b>${n(i.failed)}</b></div></div>
        <div class="ph-mb ph-muted">${last ? "Last deployment: <b class=\"ph-strong\">" + PH.esc(last.app) + "</b> on " + PH.esc(dayOnly(last.creation)) + (last.future_dated ? " (future date)" : "") : "No deployment yet"}</div>
        ${apps}${dup}</section>`;
    }).join("") + "</div>");
    PH.$$("[data-req]", box).forEach((tr) => tr.addEventListener("click", () => drill(tr.dataset.req)));
  }

  /* ---- drill-down: one request ---- */
  let drillModal = null;
  function drill(name) {
    const body = document.createElement("div");
    PH.skeleton(body);
    const m = drillModal = PH.modal({ title: name, sub: "Deployment request", body, size: "lg" });
    PH.call(API + "get_deployment_request", { name }, { silent: true }).then((d) => {
      const r = d.request;
      const kv = (k, v) => `<dt>${PH.esc(k)}</dt><dd>${v}</dd>`;
      const txt = (k, v) => (v ? `<div class="ph-mt"><div class="ph-muted">${PH.esc(k)}</div><pre class="dp-pre">${PH.esc(v)}</pre></div>` : "");
      const appLink = r.app ? PH.esc(r.app) + (r.app_default_branch ? ' <span class="ph-muted">(default branch ' + PH.esc(r.app_default_branch) + ")</span>" : "") : "—";
      PH.set(body,
        `<div class="ph-flex ph-flex--between ph-flex--wrap ph-mb"><div>${badge(r.stage)}${r.future_dated ? ' <span class="ph-badge ph-badge--outline">dated in the future</span>' : ""}</div><div class="ph-flex"><a class="ph-link" target="_blank" rel="noopener" href="/app/deployment-request/${encodeURIComponent(r.name)}">Open in Desk</a></div></div>
        ${actionButtons(r) ? '<div class="ph-mb">' + actionButtons(r) + "</div>" : ""}
        <dl class="ph-kv">
          ${kv("App", appLink)}${kv("Instance", PH.esc(r.instance || "—") + (r.environment ? ' <span class="ph-muted">(' + PH.esc(r.environment) + ")</span>" : ""))}
          ${kv("Branch", PH.esc(r.branch || "—"))}${kv("Commit", '<span class="ph-mono">' + PH.esc(r.commit_hash || "not recorded") + "</span>")}
          ${kv("Requested by", PH.esc(r.requested_by || "—"))}${kv("Deployed by", PH.esc(r.deployed_by || "not recorded"))}
          ${kv("Raised", PH.esc(when(r.creation)))}${kv(r.stage === "Deployed" ? "Time to deploy" : "Open for", PH.esc(r.stage === "Deployed" ? dur(r.lead_hours) + (r.lead_hours == null ? " (no timing history)" : "") : r.stage === "Declined" ? "—" : age(r.age_days)))}
          ${r.linked_request ? kv("Linked request", docLink("request", r.linked_request.name) + " " + PH.esc(r.linked_request.title || "") + ' <span class="ph-muted">(' + PH.esc(r.linked_request.workflow_state || "") + ")</span>") : r.linked_request_name ? kv("Linked request", PH.esc(r.linked_request_name) + ' <span class="ph-muted">(not found)</span>') : ""}
          ${r.requires_approval ? kv("Approval", PH.esc(r.approval_status || "Pending")) : ""}
        </dl>
        ${txt("Description", r.description)}${txt("What went wrong", r.errors)}${txt("What was fixed", r.fix_notes)}
        <div class="ph-strong ph-mt ph-mb">Timeline</div>
        <ul class="dp-tl">${d.timeline.map((e) => `<li><span class="ph-muted">${PH.esc(when(e.when))}</span><span><b>${PH.esc(e.what)}</b>${e.by ? " · " + PH.esc(e.by) : ""}${e.note ? '<div class="ph-muted">' + PH.esc(e.note) + "</div>" : ""}</span></li>`).join("")}</ul>
        ${d.history_known ? "" : '<div class="ph-muted">No status changes are on record for this request, so only the dates above are known.</div>'}
        ${d.same_app_on_instance.length ? '<div class="ph-strong ph-mt ph-mb">Other ' + PH.esc(r.app) + " requests on this instance</div><ul class=\"dp-tl\">" + d.same_app_on_instance.map((x) => `<li><span class="ph-muted">${PH.esc(dayOnly(x.creation))}</span><span>${docLink("deployment-request", x.name)} ${badge(x.stage)} <span class="ph-muted">${PH.esc(x.branch || "")} ${PH.esc(x.commit_hash || "")}</span></span></li>`).join("") + "</ul>" : ""}`);
    }).catch((e) => PH.error(body, e.message, () => { m.close(); drill(name); }));
  }

  function exportView() {
    const v = currentView(), c = CSVS[v];
    if (!data || !c) return;
    const rows = data[c.key] || [];
    if (!rows.length) return;
    const s = st.get();
    PH.csv(c.file + "_" + (s.from || "start") + "_" + (s.to || "now") + ".csv", rows, c.cols.map(([key, label]) => ({ key, label })));
  }
  PH.$("#export").addEventListener("click", exportView);
  PH.$$("[data-csv]").forEach((b) => b.addEventListener("click", exportView));

  /* ---- actions: every write goes through the existing api.deployments endpoints, which
     re-check the roles; the controls below are only drawn for the roles that may use them ---- */
  function actionButtons(r) {
    const btn = (cls, act, label, extra) => `<button class="ph-btn ph-btn--sm ${cls}" type="button" data-act="${act}" data-name="${PH.esc(r.name)}"${extra || ""}>${PH.esc(label)}</button>`;
    const out = [];
    if (IS_APPROVER && r.pending_approval) out.push(btn("", "approve", "Approve"), btn("ph-btn--ghost", "reject", "Reject"));
    if (CAN_CHANGE_STATE) {
      (STATE_ACTIONS[r.workflow_state] || []).forEach((a) => {
        const held = a.action === "Start Deployment" && (r.pending_approval || r.stage === "Declined");
        out.push(btn("", "state", a.label, ` data-action="${PH.esc(a.action)}" data-field="${a.field || ""}"` + (held ? ' disabled title="Needs a peak-hours approval first"' : "")));
      });
    }
    if (CAN_CREATE) out.push(btn("ph-btn--ghost", "duplicate", "Duplicate"));
    return out.length ? '<div class="dp-actions">' + out.join("") + "</div>" : "";
  }

  function afterWrite(message) {
    PH.toast(message, "good");
    load();
    if (currentView() === "mine") loadMine();
    if (currentView() === "instances") loadInstances();
  }

  /** Modal with labelled fields, inline validation and Enter-to-submit.
      fields: [{name, label, type: text|textarea|select, options: [{value,label}], value, hint, required}]
      onSubmit(values) -> Promise; a rejection keeps the modal open (PH.call already toasted it). */
  function formModal({ title, sub, fields, submit, onSubmit }) {
    const body = document.createElement("form");
    body.className = "ph-form ph-form--1";
    body.noValidate = true;
    body.innerHTML = fields.map((f) => {
      const id = "dpf-" + f.name;
      const ctl = f.type === "textarea" ? `<textarea class="ph-control" id="${id}" name="${f.name}" rows="4"></textarea>`
        : f.type === "select" ? `<select class="ph-control" id="${id}" name="${f.name}"><option value="">Select…</option>${f.options.map((o) => `<option value="${PH.esc(o.value)}">${PH.esc(o.label)}</option>`).join("")}</select>`
        : `<input class="ph-control" id="${id}" name="${f.name}" type="text" autocomplete="off" placeholder="${PH.esc(f.placeholder || "")}">`;
      return `<div class="ph-field"><label for="${id}">${PH.esc(f.label)}${f.required ? " *" : ""}</label>${ctl}<div class="ph-field__hint">${PH.esc(f.hint || "")}</div><div class="ph-field__error" data-err="${f.name}" role="alert"></div></div>`;
    }).join("");
    fields.forEach((f) => { body.elements[f.name].value = f.value || ""; });
    const values = () => Object.fromEntries(fields.map((f) => [f.name, body.elements[f.name].value.trim()]));
    const modal = PH.modal({
      title, sub, body, size: "lg",
      actions: [
        { label: "Cancel" },
        {
          label: submit, primary: true,
          onClick: async () => {
            const v = values();
            let bad = false;
            fields.forEach((f) => {
              const missing = !!f.required && !v[f.name];
              body.querySelector(`[data-err="${f.name}"]`).textContent = missing ? f.label + " is required." : "";
              body.elements[f.name].classList.toggle("is-invalid", missing);
              bad = bad || missing;
            });
            if (bad) { body.querySelector(".is-invalid").focus(); return false; }
            try { await onSubmit(v); } catch (e) { return false; }
          },
        },
      ],
    });
    body.addEventListener("submit", (e) => e.preventDefault());
    body.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && e.target.tagName !== "TEXTAREA") {
        e.preventDefault();
        modal.el.querySelector(".ph-btn--primary").click();
      }
    });
    return { modal, form: body };
  }

  let pickLists = null;
  const loadPickLists = () => pickLists || (pickLists = Promise.all([
    PH.call(WRITE_API + "get_deployment_apps", {}, { silent: true }),
    PH.call(WRITE_API + "get_deployment_instances", {}, { silent: true }),
  ]).catch((e) => { pickLists = null; throw e; }));

  /** New deployment request, optionally prefilled from an existing one (Duplicate). */
  function raiseRequest(prefill) {
    return loadPickLists().then(([apps, instances]) => {
      const defaults = Object.fromEntries(apps.map((a) => [a.name, a.default_branch || ""]));
      const p = prefill || {};
      const { form } = formModal({
        title: prefill ? "Duplicate deployment request" : "New deployment request",
        sub: prefill ? "Based on " + prefill.name : "Raised in your name. During peak hours it waits for a Projects Manager's approval.",
        submit: "Raise it",
        fields: [
          { name: "app", label: "App", type: "select", required: true, value: p.app, options: apps.map((a) => ({ value: a.name, label: a.name })) },
          { name: "instance", label: "Instance", type: "select", required: true, value: p.instance, options: instances.map((i) => ({ value: i.name, label: i.environment_type ? i.name + " (" + i.environment_type + ")" : i.name })) },
          { name: "branch", label: "Branch", type: "text", required: true, placeholder: "e.g. main", value: p.branch, hint: "Filled from the app's default branch when you pick one." },
          { name: "description", label: "Description", type: "textarea", value: p.description },
        ],
        onSubmit: (v) => PH.call(WRITE_API + "create_deployment_request", { app: v.app, instance: v.instance, branch: v.branch || null, description: v.description || null })
          .then((doc) => afterWrite(doc && doc.requires_approval ? "Deployment request raised. It needs a peak-hours approval before it can start." : "Deployment request raised.")),
      });
      let branchTouched = !!p.branch;
      form.elements.branch.addEventListener("input", () => { branchTouched = true; });
      form.elements.app.addEventListener("change", () => { if (!branchTouched) form.elements.branch.value = defaults[form.elements.app.value] || ""; });
    }).catch((e) => PH.toast(e.message, "bad"));
  }

  function runStateAction(name, action, field) {
    const send = (extra) => PH.call(WRITE_API + "update_deployment_status", Object.assign({ name, action }, extra)).then(() => afterWrite(action + " done."));
    if (!field) return send({}).catch(() => {});
    const f = FIELD_PROMPT[field];
    formModal({
      title: action, sub: name, submit: "Confirm",
      fields: [Object.assign({ name: field, value: "" }, f)],
      onSubmit: (v) => send({ [field]: v[field] || null }),
    });
  }

  function decide(name, approve) {
    const go = () => PH.call(WRITE_API + (approve ? "approve_deployment_request" : "reject_deployment_request"), { name })
      .then(() => afterWrite(approve ? "Approved." : "Rejected."));
    if (approve) return go().catch(() => {});
    return PH.confirm("Reject this deployment?", "It will stay held until someone approves it later.", { ok: "Reject", danger: true })
      .then((yes) => yes && go().catch(() => {}));
  }

  function duplicate(name) {
    return PH.call(API + "get_deployment_request", { name }, { silent: true })
      .then((d) => raiseRequest(d.request))
      .catch((e) => PH.toast(e.message, "bad"));
  }

  document.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-act]");
    if (!b || b.disabled) return;
    const { act, name } = b.dataset;
    if (drillModal && drillModal.el.contains(b)) drillModal.close();
    b.disabled = true;
    const pending = act === "approve" ? decide(name, true)
      : act === "reject" ? decide(name, false)
      : act === "state" ? runStateAction(name, b.dataset.action, b.dataset.field)
      : duplicate(name);
    Promise.resolve(pending).finally(() => { b.disabled = false; });
  });
  const newBtn = PH.$("#new-request");
  if (newBtn) newBtn.addEventListener("click", () => raiseRequest());
  DevKeys.init({ title: "Deployments", list: { root: "#ph-main", items: () => PH.$$("#ph-main tbody tr.is-link") } });

  function refreshAll() {
    load();
    if (currentView() === "instances") loadInstances();
    if (currentView() === "mine") loadMine();
  }
  PH.onRefresh(refreshAll);
  PH.ready(() => { paintView(); paintPresets(); load(); loadInstances(); loadMine(); });
})();
