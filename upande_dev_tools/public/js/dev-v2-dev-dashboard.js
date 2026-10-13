/* Dev Dashboard v2: bench health (live git), schema differences, deployments, activity.
 * Reads: api.v2.dev_dashboard. Actions use the same endpoints as the current page:
 * api.version_control.scan_bench, api.deployments.get_deployment_apps / get_deployment_instances /
 * create_deployment_request. */
(function () {
  "use strict";
  const API = "upande_dev_tools.api.v2.dev_dashboard.";
  const SCAN_API = "upande_dev_tools.api.version_control.scan_bench";
  const DEPLOY_API = "upande_dev_tools.api.deployments.";
  const VIEWS = ["apps", "drift", "deployments", "activity"];
  const d7 = PH.date.preset("7d");
  const st = PH.state({ view: "apps", from: d7[0], to: d7[1], q: "", state: "", dstate: "", astatus: "" });
  const n = PH.fmt.num;
  let data = null, seq = 0, forceRefresh = false, deployLists = null;

  PH.bindSearch("#f-q", st, "q");
  PH.bindSelect("#f-state", st, "state");
  PH.bindSelect("#f-dstate", st, "dstate");
  PH.bindSelect("#f-astatus", st, "astatus");
  PH.dateRange({ pills: "#f-preset", from: "#f-from", to: "#f-to", state: st });
  PH.$("#tabs").addEventListener("click", (e) => {
    const b = e.target.closest("[data-view]");
    if (b) st.set({ view: b.dataset.view });
  });

  const SYNC = {
    synced: ["good", "In step with remote"],
    behind: ["warn", "Behind remote"],
    ahead: ["signal", "Not pushed"],
    diverged: ["warn", "Behind and not pushed"],
    no_upstream: ["outline", "No remote to compare"],
  };
  const SYNC_NAME = Object.fromEntries(Object.entries(SYNC).map(([k, v]) => [k, v[1]]));
  const RECORDED_NAME = { Clean: "Clean", Dirty: "Uncommitted", Ahead: "Not pushed", Stale: "Behind", Diverged: "Diverged", "No Upstream": "No remote", Error: "Could not read" };
  const DEP = { Requested: "outline", "In Progress": "signal", Deployed: "good", Failed: "bad" };
  const ACT = { Success: "good", Warning: "warn", Error: "bad", Info: "outline" };
  const syncBadge = (r) => r.error
    ? '<span class="ph-badge ph-badge--outline">Could not read</span>'
    : '<span class="ph-badge ph-badge--' + SYNC[r.sync][0] + '">' + PH.esc(SYNC[r.sync][1]) + "</span>";
  const badge = (map, v, label) => '<span class="ph-badge ph-badge--' + (map[v] || "outline") + '">' + PH.esc(label || v || "—") + "</span>";
  const link = (href, text, cls) => '<a class="ph-link' + (cls ? " " + cls : "") + '" target="_blank" rel="noopener" href="' + href + '">' + PH.esc(text) + "</a>";
  const dt = (v) => (v ? PH.fmt.date(v.slice(0, 10)) + " " + v.slice(11, 16) : "—");
  const iconBtn = (action, icon, title, key) => '<button class="ph-iconbtn ph-iconbtn--flat ph-iconbtn--sm" type="button" data-act="' + action +
    '" data-key="' + PH.esc(key) + '" title="' + PH.esc(title) + '" aria-label="' + PH.esc(title) + '">' + PH.icon(icon, 15) + "</button>";
  const recordedText = (rec) => rec ? (RECORDED_NAME[rec.status] || rec.status || "—") + " · " + dt(rec.checked_at).replace(/ \d\d:\d\d$/, "") : "Never scanned";

  /* ---- tables ---- */
  const mk = (sel, cols, onRowClick, sort, empty, emptyText) => PH.table(sel, {
    columns: cols, rows: [], compact: true, pageSize: 25, empty, emptyText, onRowClick, sort,
  });
  const tApps = mk("#t-apps", [
    { key: "app", label: "App", cls: "is-strong" },
    { key: "branch", label: "Branch", format: (v) => v || "—" },
    { key: "sync", label: "Against remote", html: (v, r) => syncBadge(r), sortValue: (r) => ["diverged", "behind", "ahead", "no_upstream", "synced"].indexOf(r.sync) },
    { key: "ahead", label: "Not pushed", num: true, format: (v, r) => (r.error ? "—" : n(v)) },
    { key: "behind", label: "Behind", num: true, format: (v, r) => (r.error ? "—" : n(v)) },
    { key: "changes", label: "Uncommitted", num: true, format: (v, r) => (r.error ? "—" : n(v)) },
    { key: "recorded", label: "Last scan", sortValue: (r) => (r.recorded && r.recorded.checked_at) || "", format: (v, r) => recordedText(r.recorded) },
    { key: "repo_url", label: "", sortable: false, cls: "dd-act", html: (v, r) => (v ? iconBtn("copy-repo", "copy", "Copy repository link", r.app) : "") },
  ], (r) => appModal(r), { key: "changes", dir: "desc" }, "No apps match", "Clear the search or the state filter.");
  const tRecorded = mk("#t-recorded", [
    { key: "app", label: "App", cls: "is-strong" },
    { key: "branch", label: "Branch", format: (v) => v || "—" },
    { key: "status", label: "Recorded state", format: (v) => RECORDED_NAME[v] || v || "—" },
    { key: "ahead", label: "Not pushed", num: true },
    { key: "behind", label: "Behind", num: true },
    { key: "checked_at", label: "Scanned", format: (v) => dt(v) },
  ], null, { key: "app", dir: "asc" }, "None", "");
  const tDrift = mk("#t-drift", [
    { key: "doctype_name", label: "DocType", cls: "is-strong", format: (v) => v || "—" },
    { key: "field_name", label: "Field", format: (v) => v || "—" },
    { key: "issue_type", label: "Difference", format: (v) => v || "—" },
    { key: "status", label: "Review status", format: (v) => v || "New" },
    { key: "comparison_time", label: "Compared", format: (v) => dt(v) },
  ], null, { key: "comparison_time", dir: "desc" }, "Local and live agree", "No field differences were found the last time the two were compared.");
  const tDep = mk("#t-deployments", [
    { key: "name", label: "Request", cls: "ph-mono", html: (v) => link("/app/deployment-request/" + encodeURIComponent(v), v), sortable: false },
    { key: "app", label: "App", cls: "is-strong" },
    { key: "instance", label: "Instance" },
    { key: "branch", label: "Branch", format: (v) => v || "—" },
    { key: "requested_by_user", label: "Requested by", format: (v) => (v || "").split("@")[0] || "—" },
    { key: "creation", label: "Raised", format: (v) => dt(v) },
    { key: "workflow_state", label: "State", html: (v, r) => (r.requires_approval && r.approval_status === "Pending") ? badge({}, "", "Waiting for PM approval") : badge(DEP, v) },
    { key: "_dup", label: "", sortable: false, cls: "dd-act", html: (v, r) => (data.permissions.raise_deployment ? iconBtn("duplicate", "copy", "Duplicate this request", r.name) : "") },
  ], null, { key: "creation", dir: "desc" }, "No deployment requests", "None were raised in this date range with these filters. Use New deployment request to raise one.");
  const activityCols = [
    { key: "activity_time", label: "When", format: (v) => dt(v) },
    { key: "activity_type", label: "Type", format: (v) => v || "—" },
    { key: "title", label: "What", cls: "is-strong", format: (v) => v || "—" },
    { key: "source", label: "Source", format: (v) => v || "—" },
    { key: "status", label: "Outcome", html: (v) => badge(ACT, v) },
  ];
  const tAct = mk("#t-activity", activityCols, (r) => activityModal(r), { key: "activity_time", dir: "desc" }, "No activity", "Nothing was logged in this date range with these filters.");
  const tErr = mk("#t-errors", activityCols, (r) => activityModal(r), { key: "activity_time", dir: "desc" }, "No errors logged", "That is the good outcome.");

  /* ---- drill-downs ---- */
  const kv = (pairs) => '<dl class="ph-kv">' + pairs.map(([k, v]) => "<dt>" + PH.esc(k) + "</dt><dd>" + v + "</dd>").join("") + "</dl>";
  const appByName = (name) => data.apps.rows.find((r) => r.app === name);

  function copyRepo(row) {
    if (!row || !row.repo_url) return;
    const ok = () => PH.toast("Repository link copied.", "good");
    const fail = () => PH.toast("Could not copy that.", "bad");
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(row.repo_url).then(ok, fail);
    else fail();
  }

  function appModal(r) {
    const body = document.createElement("div");
    const rec = r.recorded;
    let html = "";
    if (r.error) html += '<div class="ph-notice ph-notice--warn">' + PH.esc(r.error) + "</div>";
    const pairs = [
      ["Branch", PH.esc(r.branch || "—")],
      ["Tracks", PH.esc(r.upstream || "nothing (no upstream branch)")],
      ["Against remote", syncBadge(r)],
      ["Commits not pushed", n(r.ahead)],
      ["Commits behind", n(r.behind)],
      ["Uncommitted: changed files", n(r.tracked_changes)],
      ["Uncommitted: new files", n(r.untracked)],
      ["Commit", '<span class="ph-mono">' + PH.esc(r.commit || "—") + "</span>" + (r.tag ? " · tag " + PH.esc(r.tag) : "")],
      ["Commit date", PH.esc(dt(r.commit_date))],
      ["Remote last fetched", PH.esc(dt(r.fetched_at))],
    ];
    if (r.repo_url) pairs.push(["Repository", link(PH.esc(r.repo_url), r.repo_url)]);
    html += kv(pairs);
    html += '<h3 class="ph-card__title ph-mt">Last recorded scan</h3>';
    html += rec
      ? '<p class="dd-dim">' + PH.esc(dt(rec.checked_at)) + ": " + PH.esc(RECORDED_NAME[rec.status] || rec.status || "—") +
        (rec.branch ? " on " + PH.esc(rec.branch) : "") + ", " + n(rec.ahead) + " not pushed, " + n(rec.behind) + " behind" +
        (rec.uncommitted ? ", uncommitted changes" : "") + ". It may be out of date; the figures above were read just now.</p>" +
        "<p>" + link("/app/module-version-check/" + encodeURIComponent(r.app), "Open the recorded scan") + "</p>"
      : '<p class="dd-dim">This app has not been recorded by a scan yet.' + (data.permissions.scan ? " Use Scan bench to record it." : "") + "</p>";
    body.innerHTML = html;
    const actions = r.repo_url ? [{ label: "Copy repository link", onClick: () => { copyRepo(r); return false; } }] : [];
    PH.modal({ title: r.app, sub: "Read from git" + (data && data.apps.cached ? " (cached for up to a minute)" : ""), body, actions });
  }

  function activityModal(r) {
    const body = document.createElement("div");
    body.innerHTML = kv([
      ["When", PH.esc(dt(r.activity_time))], ["Type", PH.esc(r.activity_type || "—")], ["Source", PH.esc(r.source || "—")], ["Outcome", badge(ACT, r.status)],
    ]) + '<h3 class="ph-card__title ph-mt">Details</h3><p class="dd-desc">' + PH.esc(r.description || "No details were logged.") + "</p>" +
      '<p class="dd-dim ph-mt">Long text is shortened and anything that looks like a password or token is hidden.</p>' +
      "<p>" + link("/app/developer-activity-log/" + encodeURIComponent(r.name), "Open in Desk") + "</p>";
    PH.modal({ title: r.title || "Activity", sub: dt(r.activity_time), body });
  }

  /* ---- actions ---- */
  function scanBench() {
    PH.confirm("Scan the bench?", "Reads every installed app's git state from this machine (no network) and records it as the last scan, which the Version Check page and the comparison column use. The figures on this page are always read live.", { ok: "Scan bench" })
      .then((yes) => {
        if (!yes) return null;
        const btn = PH.$("#scan");
        btn.disabled = true;
        btn.textContent = "Scanning…";
        return PH.call(SCAN_API, {})
          .then((r) => {
            PH.toast("Read " + n(r.checked) + " apps." + (r.failed && r.failed.length ? " Could not read: " + r.failed.join(", ") + "." : ""), r.failed && r.failed.length ? "warn" : "good");
            forceRefresh = true;
            return load();
          })
          .catch(() => {})
          .then(() => { btn.disabled = false; btn.textContent = "Scan bench"; });
      });
  }

  function loadDeployLists() {
    if (deployLists) return Promise.resolve(deployLists);
    return Promise.all([PH.call(DEPLOY_API + "get_deployment_apps"), PH.call(DEPLOY_API + "get_deployment_instances")])
      .then(([apps, instances]) => (deployLists = { apps: apps || [], instances: instances || [] }));
  }

  /** The New / Duplicate deployment request form. `prefill` = {app, instance, branch, description}. */
  function deploymentForm(prefill) {
    loadDeployLists().then(({ apps, instances }) => {
      const opt = (v, l, sel) => '<option value="' + PH.esc(v) + '"' + (sel ? " selected" : "") + ">" + PH.esc(l) + "</option>";
      const body = document.createElement("form");
      body.noValidate = true;
      body.innerHTML = '<div class="ph-form ph-form--2">' +
        '<div class="ph-field"><label for="dd-app">App</label><select class="ph-control" id="dd-app" required><option value="">Choose an app</option>' +
        apps.map((a) => opt(a.name, a.name, prefill && prefill.app === a.name)).join("") + '</select><div class="dd-err" data-err="app"></div></div>' +
        '<div class="ph-field"><label for="dd-instance">Instance</label><select class="ph-control" id="dd-instance" required><option value="">Choose an instance</option>' +
        instances.map((i) => opt(i.name, i.environment_type ? i.name + " (" + i.environment_type + ")" : i.name, prefill && prefill.instance === i.name)).join("") + '</select><div class="dd-err" data-err="instance"></div></div>' +
        '<div class="ph-field ph-field--full"><label for="dd-branch">Branch</label><input class="ph-control" id="dd-branch" type="text" placeholder="e.g. main" autocomplete="off"></div>' +
        '<div class="ph-field ph-field--full"><label for="dd-desc">Description</label><textarea class="ph-control" id="dd-desc" rows="4"></textarea></div></div>' +
        '<button type="submit" hidden></button>';
      const f = (id) => body.querySelector("#" + id);
      f("dd-branch").value = prefill ? prefill.branch || "" : "";
      f("dd-desc").value = prefill ? prefill.description || "" : "";
      const invalid = (key, msg) => {
        body.querySelector('[data-err="' + key + '"]').textContent = msg || "";
        f("dd-" + key).classList.toggle("is-invalid", !!msg);
      };
      let branchTouched = !!prefill;
      f("dd-branch").addEventListener("input", () => { branchTouched = true; });
      ["app", "instance"].forEach((key) => f("dd-" + key).addEventListener("change", () => invalid(key, "")));
      f("dd-app").addEventListener("change", () => {
        const app = apps.find((a) => a.name === f("dd-app").value);
        if (!branchTouched) f("dd-branch").value = (app && app.default_branch) || "";
      });
      const submit = () => {
        const app = f("dd-app").value, instance = f("dd-instance").value;
        invalid("app", app ? "" : "Pick an app.");
        invalid("instance", instance ? "" : "Pick an instance.");
        if (!app || !instance) return Promise.resolve(false);
        return PH.call(DEPLOY_API + "create_deployment_request", {
          app, instance, branch: f("dd-branch").value.trim() || null, description: f("dd-desc").value.trim() || null,
        }).then(() => {
          PH.toast("Deployment request raised.", "good");
          load();
          return true;
        });
      };
      const m = PH.modal({
        title: prefill ? "Duplicate deployment request" : "New deployment request",
        sub: "Raised requests can be seen on the Deployments tab",
        body,
        actions: [{ label: "Cancel" }, { label: "Raise it", primary: true, onClick: () => submit().then((ok) => (ok ? undefined : false)) }],
      });
      body.addEventListener("submit", (e) => {
        e.preventDefault();
        m.el.querySelector(".ph-btn--primary").click();
      });
    }).catch(() => {});
  }

  function duplicate(name) {
    PH.call(API + "get_deployment_for_duplicate", { name }).then((row) => deploymentForm(row)).catch(() => {});
  }

  PH.$("#scan").addEventListener("click", scanBench);
  PH.$("#new-deploy").addEventListener("click", () => deploymentForm(null));
  PH.$("#view-apps").addEventListener("click", (e) => {
    const b = e.target.closest('[data-act="copy-repo"]');
    if (b) copyRepo(appByName(b.dataset.key));
  });
  PH.$("#view-deployments").addEventListener("click", (e) => {
    const b = e.target.closest('[data-act="duplicate"]');
    if (b) duplicate(b.dataset.key);
  });
  DevKeys.init({ title: "Dev Dashboard", list: { root: "#ph-main", items: () => PH.$$("#ph-main tbody tr.is-link") } });

  /* ---- load + render ---- */
  PH.kpiSkeleton("#kpis", ["Apps", "Up to date", "Behind remote", "Uncommitted", "Errors"]);
  const currentView = () => (VIEWS.includes(st.get("view")) ? st.get("view") : "apps");
  const CSVS = {
    apps: { file: "bench_apps", get: () => data.apps.rows.map((r) => ({ ...r, state: r.error ? "Could not read" : SYNC_NAME[r.sync], scan: recordedText(r.recorded) })), cols: [["app", "App"], ["branch", "Branch"], ["upstream", "Tracks"], ["state", "Against remote"], ["ahead", "Not pushed"], ["behind", "Behind"], ["tracked_changes", "Changed files"], ["untracked", "New files"], ["commit", "Commit"], ["tag", "Tag"], ["commit_date", "Commit date"], ["fetched_at", "Remote last fetched"], ["scan", "Last scan"], ["repo_url", "Repository"]] },
    drift: { file: "schema_differences", get: () => data.drift.rows, cols: [["doctype_name", "DocType"], ["field_name", "Field"], ["issue_type", "Difference"], ["status", "Review status"], ["comparison_time", "Compared"]] },
    deployments: { file: "deployments", get: () => data.deployments.rows, cols: [["name", "Request"], ["app", "App"], ["instance", "Instance"], ["branch", "Branch"], ["commit_hash", "Commit"], ["workflow_state", "State"], ["approval_status", "Approval"], ["requested_by_user", "Requested by"], ["creation", "Raised"]] },
    activity: { file: "activity", get: () => data.activity.rows, cols: [["activity_time", "When"], ["activity_type", "Type"], ["title", "What"], ["source", "Source"], ["status", "Outcome"], ["description", "Details"]] },
  };
  function paintView() {
    const v = currentView();
    PH.$$("#tabs .ph-tab").forEach((b) => b.classList.toggle("is-on", b.dataset.view === v));
    VIEWS.forEach((x) => { PH.$("#view-" + x).hidden = x !== v; });
    PH.$("#f-state").hidden = v !== "apps";
    PH.$("#f-dstate").hidden = v !== "deployments";
    PH.$("#f-astatus").hidden = v !== "activity";
    PH.$("#export").disabled = !(data && CSVS[v].get().length);
  }
  st.on((s, changed) => {
    paintView();
    if (changed.length === 1 && changed[0] === "view") return;
    load();
  });

  function load() {
    const s = st.get(), my = ++seq;
    PH.loadingKpis("#kpis", true);
    const args = { search: s.q, state: s.state, from_date: s.from, to_date: s.to, deploy_state: s.dstate, activity_status: s.astatus, refresh: forceRefresh ? 1 : 0 };
    forceRefresh = false;
    return PH.call(API + "get_dev_dashboard", args)
      .then((m) => { if (my !== seq) return; data = m; render(); PH.markUpdated(); })
      .catch((e) => {
        if (my !== seq) return;
        PH.loadingKpis("#kpis", false);
        ["#t-apps", "#t-drift", "#t-deployments", "#t-activity", "#t-errors"].forEach((x) => PH.error(x, e.message, () => load()));
        PH.set("#notes", "");
        paintView();
      });
  }

  function render() {
    const d = data, s = st.get(), t = d.apps.totals, a = d.activity, sn = d.snapshots;
    const errors = a.by_status.Error || 0;
    const behind = t.behind + t.diverged;
    const setState = (v) => () => st.set({ state: st.get("state") === v ? "" : v, view: "apps" });
    PH.$("#scan").hidden = !d.permissions.scan;
    PH.$("#new-deploy").hidden = !d.permissions.raise_deployment;
    PH.text("#sub", n(t.apps) + " apps · " + n(t.up_to_date) + " up to date · last backup " + dt(sn.last_backup) + " · " + n(sn.today) + " snapshots today · " + PH.date.label(s.from, s.to) +
      (s.q ? ' · "' + s.q + '"' : "") + (s.state ? " · " + (PH.$("#f-state").selectedOptions[0] || {}).text : ""));
    PH.kpis("#kpis", [
      { label: "Apps", value: t.apps, unit: t.needs_attention ? n(t.needs_attention) + " need a look" : "all up to date", dark: true, onClick: setState(""), title: "Apps installed on this site, read from git now. Up to date + need a look = apps." },
      { label: "Up to date", value: t.up_to_date, unit: "fully in step", onClick: setState("clean"), active: s.state === "clean" },
      { label: "Behind remote", value: behind, unit: t.diverged ? n(t.diverged) + " also not pushed" : "apps to pull", onClick: setState("behind"), active: s.state === "behind", title: "Behind remote only + behind and not pushed. Compared with each remote's last fetch." },
      { label: "Uncommitted", value: t.uncommitted, unit: "apps with local edits", onClick: setState("uncommitted"), active: s.state === "uncommitted", title: "Independent of the remote state: an app can be both behind and uncommitted." },
      { label: "Errors", value: errors, unit: "in the activity log", onClick: () => st.set({ view: "activity", astatus: "Error" }) },
    ]);

    const notes = [];
    const old = d.apps.rows.map((r) => r.fetched_at).filter(Boolean).sort()[0];
    notes.push('<div class="ph-notice ph-notice--signal">App state is read from git just now (kept for up to a minute) and compared with each remote as last fetched' +
      (old ? ", the oldest fetch being " + PH.esc(dt(old)) : "") + ". Nothing is fetched from this page, so \"behind\" may grow once you fetch.</div>");
    if (t.no_upstream) notes.push('<div class="ph-notice ph-notice--signal">' + PH.esc(PH.fmt.plural(t.no_upstream, "app")) + " have no remote branch to compare with (a local branch or a detached checkout), so they cannot show as behind.</div>");
    if (t.unreadable) notes.push('<div class="ph-notice ph-notice--warn">' + PH.esc(PH.fmt.plural(t.unreadable, "app")) + " could not be read.</div>");
    if (!d.deployments.allowed) notes.push('<div class="ph-notice">Deployment requests are not available for your role.</div>');
    PH.set("#notes", notes.join(""));

    tApps.update(d.apps.rows);
    PH.text("#apps-meta", n(d.apps.rows.length) + " shown of " + n(t.apps) + " · state read " + dt(d.apps.read_at) + (d.apps.recorded_last_scan ? " · last scan " + dt(d.apps.recorded_last_scan) : " · never scanned") + " · click an app for its details");
    PH.text("#tc-apps", n(t.apps));
    PH.$("#recorded-card").hidden = !d.apps.recorded_not_installed.length;
    tRecorded.update(d.apps.recorded_not_installed);

    const dr = d.drift;
    PH.kpis("#drift-kpis", ["Missing in Local", "Missing in Live", "Different Type", "Different Property"].map((k) => ({
      label: { "Missing in Local": "Missing locally", "Missing in Live": "Missing live", "Different Type": "Different type", "Different Property": "Different property" }[k],
      value: dr.by_type[k] || 0,
      unit: { "Missing in Local": "on live, not in this bench", "Missing in Live": "in this bench, not on live", "Different Type": "same field, other fieldtype", "Different Property": "same field, other options" }[k],
    })));
    tDrift.update(dr.rows);
    PH.text("#tc-drift", n(dr.total));

    const dp = d.deployments;
    PH.options("#f-dstate", Object.keys(dp.by_state).filter(Boolean).sort().map((k) => ({ value: k, label: k + " (" + dp.by_state[k] + ")" })), s.dstate);
    tDep.update(dp.rows);
    PH.text("#dep-meta", n(dp.total) + " raised in the range" + (dp.pending_approval ? " · " + n(dp.pending_approval) + " waiting for approval" : "") + (dp.truncated ? " · showing the latest " + n(d.row_limit) : "") + ".");
    PH.text("#tc-deployments", n(dp.total));

    PH.set("#snap-kv", [["Last backup", PH.esc(dt(sn.last_backup))], ["Snapshots today", n(sn.today)], ["Snapshots in range", n(sn.in_range)], ["Changed since the previous backup, in range", n(sn.changed_in_range)], ["Snapshots in total", n(sn.total)]]
      .map(([k, v]) => "<dt>" + PH.esc(k) + "</dt><dd>" + v + "</dd>").join(""));
    tAct.update(a.rows);
    tErr.update(a.recent_errors);
    PH.text("#act-meta", n(a.total) + " in the range (" + Object.entries(a.by_status).map(([k, v]) => n(v) + " " + k.toLowerCase()).join(", ") + ")" + (a.truncated ? " · showing the latest " + n(d.row_limit) : "") + " · click a row for its details");
    PH.text("#tc-activity", n(a.total));
    paintView();
  }

  function exportView() {
    const c = CSVS[currentView()];
    if (!data) return;
    const rows = c.get();
    if (!rows.length) return;
    const s = st.get();
    PH.csv(c.file + "_" + s.from + "_" + s.to + ".csv", rows, c.cols.map(([key, label]) => ({ key, label })));
  }
  PH.$("#export").addEventListener("click", exportView);
  PH.$$("[data-csv]").forEach((b) => b.addEventListener("click", exportView));

  PH.onRefresh(() => { forceRefresh = true; return load(); });
  PH.ready(() => { paintView(); load(); });
})();
