/* Settings v2 (www/dev-portal-settings-v2.html).
 *
 * Reads: api.v2.dev_portal_settings (get_settings, preview_access) - or, for a Projects Manager,
 * the existing get_peak_hours_settings.
 * Writes: the EXISTING endpoints in api/dev_portal_settings.py (update_page_roles,
 * update_peak_hours_settings). Their permission rule, lock-out guard and validation are unchanged;
 * this page only mirrors them so it never offers a choice the server refuses.
 */
(function () {
  "use strict";
  const READ = "upande_dev_tools.api.v2.dev_portal_settings.";
  const WRITE = "upande_dev_tools.api.dev_portal_settings.";
  const PREVIEW_DELAY_MS = 250;

  const app = PH.$("#st-app");
  const CAN_MANAGE = app.dataset.canManage === "1";
  const CAN_PEAK = app.dataset.canPeak === "1";
  const VIEWS = [CAN_MANAGE && "access", CAN_PEAK && "peak"].filter(Boolean);
  const st = PH.state({ view: "", group: "", show: "", q: "", edit: "" });
  const n = PH.fmt.num;
  const esc = PH.esc;
  let data = null, seq = 0, opened = false;

  /* ── Pure helpers (mirror the server rules) ───────────────────── */

  /** Why the server would refuse this rule for the Settings page itself ("" when accepted).
   *  Server rule (update_page_roles): OR mode needs both settings roles listed; AND mode needs
   *  the list to be a subset of them. */
  function refusal(route, roles, requireAll) {
    if (!data || route !== data.settings_route) return "";
    const need = data.settings_roles;
    const have = new Set(roles);
    if (requireAll ? [...have].some((r) => !need.includes(r)) : need.some((r) => !have.has(r)))
      return "This page must always stay reachable by " + need.join(" and ") + ".";
    return "";
  }
  const sameSet = (a, b) => a.size === b.size && [...a].every((x) => b.has(x));
  const clock = (v) => (v ? String(v).slice(0, 5) : "");

  /** "Anyone with Dev Team or System Manager" / "Only people with every one of ..." */
  function ruleText(roles, requireAll) {
    if (!roles.length) return "Nobody";
    if (roles.includes("All") && !requireAll) return "Everyone signed in";
    if (roles.length === 1) return "People with " + roles[0];
    return (requireAll ? "People with every one of " : "People with any one of ") + roles.join(", ");
  }

  function roleBadges(page) {
    const roles = page.allowed_roles;
    if (!roles.length) return '<span class="ph-badge ph-badge--warn" title="No role is listed, so nobody can open this page">Nobody can open</span>';
    const shown = roles.slice(0, 3).map((r) => '<span class="ph-badge ph-badge--outline">' + esc(r) + "</span>").join("");
    const more = roles.length > 3 ? '<span class="ph-badge ph-badge--outline" title="' + esc(roles.slice(3).join(", ")) + '">+' + (roles.length - 3) + "</span>" : "";
    const mode = roles.length > 1
      ? '<span class="st-mode">' + (page.require_all_roles ? "needs every role" : "any one role") + "</span>"
      : "";
    return '<div class="st-badges">' + shown + more + mode + "</div>";
  }

  /* ── Page ──────────────────────────────────────────────────────── */

  function view() {
    const v = st.get("view");
    return VIEWS.includes(v) ? v : VIEWS[0];
  }

  function paintView() {
    const v = view();
    PH.$$("#tabs .ph-tab").forEach((b) => b.classList.toggle("is-on", b.dataset.view === v));
    ["access", "peak"].forEach((k) => {
      const el = PH.$("#v-" + k);
      if (el) el.hidden = k !== v;
    });
  }

  function normalizePeak(p) {
    return { enabled: !!p.peak_hours_enabled, start: p.peak_start_time, end: p.peak_end_time, inside_now: null };
  }

  function load() {
    const my = ++seq;
    if (!VIEWS.length) {
      PH.empty("#kpis", "Nothing to show", "Your roles do not allow changing or reading any setting here.", "lock");
      return Promise.resolve();
    }
    PH.kpiSkeleton("#kpis", CAN_MANAGE ? ["Pages", "Open to everyone", "Nobody can open", "Peak hours"] : ["Peak hours"]);
    if (CAN_MANAGE) PH.skeleton("#t-main", "table");
    if (CAN_PEAK) PH.skeleton("#c-peak", "block", 4);
    const req = CAN_MANAGE
      ? PH.call(READ + "get_settings", {}, { silent: true })
      : PH.call(WRITE + "get_peak_hours_settings", {}, { silent: true }).then((p) => ({ pages: [], roles: [], peak: normalizePeak(p) }));
    return req.then((d) => {
      if (my !== seq) return;
      data = d;
      PH.markUpdated();
      paint();
      if (!opened && st.get("edit")) openEditor(st.get("edit"));
      opened = true;
    }).catch((e) => {
      if (my !== seq) return;
      PH.error(CAN_MANAGE ? "#t-main" : "#c-peak", e.message, load);
      PH.set("#kpis", "");
    });
  }

  function paint() {
    paintKpis();
    paintView();
    if (CAN_MANAGE) paintPages();
    if (CAN_PEAK) paintPeak();
  }

  function paintKpis() {
    const p = data.peak;
    const peak = { label: "Peak hours", value: p.enabled ? "On" : "Off", unit: p.enabled ? clock(p.start) + " to " + clock(p.end) : "Deployments are not held by time" };
    if (!CAN_MANAGE) return PH.kpis("#kpis", [peak]);
    const everyone = data.pages.filter((x) => data.people_total && x.people === data.people_total).length;
    const nobody = data.pages.filter((x) => !x.allowed_roles.length).length;
    PH.kpis("#kpis", [
      { label: "Registered pages", value: data.pages.length, unit: "With an access rule" },
      { label: "Open to everyone", value: everyone, unit: "Every person can open", title: "Pages that all " + n(data.people_total) + " active people can open" },
      { label: "Nobody can open", value: nobody, unit: nobody ? "Worth a look" : "None", title: "Pages with no role listed" },
      peak,
    ]);
  }

  /* ── Page access: list ─────────────────────────────────────────── */

  function filtered() {
    const s = st.get();
    const q = (s.q || "").toLowerCase();
    return data.pages.filter((p) => {
      if (s.group && p.nav_group !== s.group) return false;
      if (s.show === "nobody" && p.allowed_roles.length) return false;
      if (s.show === "everyone" && !(data.people_total && p.people === data.people_total)) return false;
      if (s.show === "all" && !p.require_all_roles) return false;
      return !q || [p.title, p.route, p.nav_group, ...p.allowed_roles].join(" ").toLowerCase().includes(q);
    });
  }

  function paintPages() {
    PH.options("#f-group", PH.uniq(data.pages.map((p) => p.nav_group)).sort(), st.get("group"));
    const rows = filtered();
    PH.text("#t-meta", PH.fmt.plural(rows.length, "page") + (rows.length !== data.pages.length ? " of " + n(data.pages.length) : "") + " · choose a page to change who can open it");
    PH.table("#t-main", {
      rows,
      empty: "No page matches",
      emptyText: "Clear a filter or the search to see every page.",
      onRowClick: (r) => openEditor(r.route),
      columns: [
        { key: "title", label: "Page", html: (v, r) => '<div class="ph-strong">' + esc(r.title) + '</div><div class="st-route">/' + esc(r.route) + "</div>" },
        { key: "nav_group", label: "Menu group" },
        { key: "who", label: "Who can open it", sortValue: (r) => r.allowed_roles.join(","), html: (v, r) => roleBadges(r) },
        { key: "people", label: "People", num: true, format: (v) => n(v) },
        {
          key: "v2", label: "Also opens", sortable: false,
          html: (v, r) => r.also_opens.map((a) => '<a class="st-link" href="' + esc(a.href) + '">' + esc(a.label) + " (v2)</a>").join("") || '<span class="ph-muted">—</span>',
        },
        { key: "act", label: "", sortable: false, html: (v, r) => '<button class="ph-btn ph-btn--sm" type="button" data-edit="' + esc(r.route) + '">Change access</button>' },
      ],
    });
  }

  PH.$("#t-main").addEventListener("click", (e) => {
    const b = e.target.closest("[data-edit]");
    if (b) openEditor(b.dataset.edit);
  });
  PH.bindSelect("#f-group", st, "group");
  PH.bindSelect("#f-show", st, "show");
  PH.bindSearch("#f-q", st, "q");
  PH.$("#tabs").addEventListener("click", (e) => {
    const b = e.target.closest("[data-view]");
    if (b) st.set({ view: b.dataset.view });
  });
  st.on((s, changed) => {
    if (!data) return;
    if (changed.includes("view")) paintView();
    if (CAN_MANAGE && changed.some((k) => ["group", "show", "q"].includes(k))) paintPages();
  });

  /* ── Page access: editor (change, review, save) ────────────────── */

  function openEditor(route) {
    const page = data && data.pages.find((p) => p.route === route);
    if (!CAN_MANAGE || !page) {
      st.set({ edit: "" }, { silent: true });
      return;
    }
    st.set({ edit: route }, { silent: true });
    const draft = { roles: new Set(page.allowed_roles), all: !!page.require_all_roles };
    const saved = { roles: new Set(page.allowed_roles), all: !!page.require_all_roles };
    const isSettings = route === data.settings_route;
    const locked = new Set(isSettings ? data.settings_roles : []);
    const known = new Set(data.roles.map((r) => r.name));
    // A role that is listed on the page but disabled in the system stays visible so saving cannot drop it unseen.
    const roles = data.roles.concat(page.allowed_roles.filter((r) => !known.has(r)).map((r) => ({ name: r, people: 0, disabled: true })));
    let effect = null, effectErr = "", search = "", timer = null, token = 0;

    const body = document.createElement("div");
    body.className = "st-editor";
    body.innerHTML =
      '<div class="st-step" data-step="edit">' +
        '<div class="ph-notice ph-notice--signal st-now"></div>' +
        (isSettings ? '<div class="ph-notice ph-notice--warn">This is the page you are on. It must always stay reachable by ' + esc(data.settings_roles.join(" and ")) + ", so those roles are fixed" + '.</div>' : "") +
        '<div class="ph-form ph-form--1">' +
          '<div class="ph-field"><label for="st-rsearch">Roles that can open this page</label>' +
            '<div class="st-chips" id="st-chips" aria-live="polite"></div>' +
            '<input class="ph-control" id="st-rsearch" type="search" placeholder="Search roles" autocomplete="off">' +
            '<div class="st-roles" id="st-roles" role="group" aria-label="Roles"></div>' +
            '<div class="ph-field__error" id="st-err" role="alert"></div></div>' +
          '<div class="ph-field"><label class="ph-switch"><input type="checkbox" id="st-all"><i></i><span>Require every listed role</span></label>' +
            '<div class="ph-field__hint" id="st-allhint"></div></div>' +
        "</div>" +
        '<div class="st-effect" id="st-effect" aria-live="polite"></div>' +
        '<div class="st-foot"><button class="ph-btn ph-btn--ghost" type="button" data-act="cancel">Cancel</button><button class="ph-btn ph-btn--primary" type="button" data-act="review" disabled>Review changes</button></div>' +
      "</div>" +
      '<div class="st-step" data-step="confirm" hidden></div>';
    const m = PH.modal({ title: page.title, sub: "/" + route + " · change who can open this page", body, size: "lg", onClose: () => { clearTimeout(timer); token++; st.set({ edit: "" }, { silent: true }); } });
    const $ = (s) => PH.$(s, body);
    $(".st-now").textContent = "Right now: " + ruleText(page.allowed_roles, saved.all) + " (" + PH.fmt.plural(page.people, "person", "people") + ").";

    const changed = () => !sameSet(draft.roles, saved.roles) || draft.all !== saved.all;
    const err = () => refusal(route, [...draft.roles], draft.all);
    const isLocked = (r) => locked.has(r) || (isSettings && draft.all && !locked.has(r));

    function paintChips() {
      const list = [...draft.roles].sort();
      PH.set($("#st-chips"), list.length
        ? list.map((r) => '<span class="st-chip">' + esc(r) + (isLocked(r) ? "" : '<button type="button" data-rm="' + esc(r) + '" aria-label="Remove ' + esc(r) + '">×</button>') + "</span>").join("")
        : '<span class="ph-badge ph-badge--warn">No role selected: nobody can open this page</span>');
    }
    function paintRoles() {
      const q = search.toLowerCase();
      PH.set($("#st-roles"), roles.filter((r) => !q || r.name.toLowerCase().includes(q)).map((r) =>
        '<label class="ph-check st-role"><input type="checkbox" data-role="' + esc(r.name) + '"' + (draft.roles.has(r.name) ? " checked" : "") + (isLocked(r.name) && (draft.roles.has(r.name) ? locked.has(r.name) : true) ? " disabled" : "") + ">" +
        "<span>" + esc(r.name) + (r.disabled ? ' <em class="ph-muted">(disabled role)</em>' : "") + '</span><small class="ph-muted">' + (r.name === "All" ? "everyone" : PH.fmt.plural(r.people, "person", "people")) + "</small></label>"
      ).join("") || '<div class="ph-muted st-none">No role matches</div>');
    }
    function paintMode() {
      $("#st-all").checked = draft.all;
      $("#st-allhint").textContent = draft.all
        ? "People need every one of the selected roles. Adding roles makes the page harder to reach."
        : "People need at least one of the selected roles. Adding roles makes the page easier to reach.";
    }
    function paintForm() {
      const e = err();
      PH.text($("#st-err"), e);
      $("#st-err").hidden = !e;
      $('[data-act="review"]').disabled = !changed() || !!e;
      paintChips();
    }
    function paintEffect() {
      const el = $("#st-effect");
      if (!changed()) return PH.set(el, '<div class="ph-muted">Change the roles to see who would be affected.</div>');
      if (effectErr) return PH.set(el, '<div class="ph-notice ph-notice--warn ph-mb-0">' + esc(effectErr) + "</div>");
      if (!effect) return PH.set(el, '<div class="ph-muted">Checking who would be affected…</div>');
      PH.set(el, effectHtml(effect, draft, page));
    }
    function refreshEffect() {
      clearTimeout(timer);
      effect = null; effectErr = "";
      paintEffect();
      if (!changed() || err()) return;
      const my = ++token;
      timer = setTimeout(() => preview(draft).then((r) => { if (my === token) { effect = r; paintEffect(); } }).catch((e) => { if (my === token) { effectErr = "Could not work out who is affected: " + e.message; paintEffect(); } }), PREVIEW_DELAY_MS);
    }
    function preview(d) {
      return PH.call(READ + "preview_access", { route, roles: [...d.roles], require_all_roles: d.all ? 1 : 0 }, { silent: true });
    }
    function update() { paintForm(); paintRoles(); paintMode(); refreshEffect(); }

    body.addEventListener("change", (e) => {
      const t = e.target;
      if (t.dataset.role) {
        if (t.checked) draft.roles.add(t.dataset.role); else draft.roles.delete(t.dataset.role);
        update();
      } else if (t.id === "st-all") {
        draft.all = t.checked;
        if (isSettings && draft.all) {
          const extra = [...draft.roles].filter((r) => !locked.has(r));
          extra.forEach((r) => draft.roles.delete(r));
          if (extra.length) PH.toast("Other roles were removed: with every role required, this page only allows " + data.settings_roles.join(" and ") + ".");
        }
        update();
      }
    });
    body.addEventListener("input", (e) => {
      if (e.target.id === "st-rsearch") { search = e.target.value.trim(); paintRoles(); }
    });
    body.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && e.target.id === "st-rsearch") e.preventDefault();
    });
    body.addEventListener("click", (e) => {
      const rm = e.target.closest("[data-rm]");
      if (rm) { draft.roles.delete(rm.dataset.rm); update(); return; }
      const a = e.target.closest("[data-act]");
      if (!a) return;
      if (a.dataset.act === "cancel") m.close();
      else if (a.dataset.act === "review") review();
      else if (a.dataset.act === "back") step("edit");
      else if (a.dataset.act === "save") save(a);
    });

    function step(name) {
      PH.$$(".st-step", body).forEach((s) => (s.hidden = s.dataset.step !== name));
      const f = body.querySelector('.st-step:not([hidden]) button.ph-btn--primary, .st-step:not([hidden]) button.ph-btn--danger');
      if (f) f.focus();
    }
    function review() {
      const b = $('[data-act="review"]');
      b.disabled = true;
      (effect ? Promise.resolve(effect) : preview(draft)).then((r) => {
        effect = r;
        const risky = !draft.roles.size || !r.you_after;
        PH.set($('[data-step="confirm"]'),
          "<h3 class=\"st-h\">Save this change to " + esc(page.title) + "?</h3>" +
          '<dl class="st-diff"><dt>Now</dt><dd>' + esc(ruleText([...saved.roles], saved.all)) + "</dd><dt>After saving</dt><dd><b>" + esc(ruleText([...draft.roles].sort(), draft.all)) + "</b></dd></dl>" +
          effectHtml(r, draft, page) +
          '<div class="st-foot"><button class="ph-btn ph-btn--ghost" type="button" data-act="back">Back</button><button class="ph-btn ' + (risky ? "ph-btn--danger" : "ph-btn--primary") + '" type="button" data-act="save">Save access change</button></div>');
        step("confirm");
      }).catch((e) => { PH.toast("Could not work out who is affected: " + e.message, "bad"); }).finally(() => paintForm());
    }
    function save(btn) {
      btn.disabled = true;
      PH.call(WRITE + "update_page_roles", { route, roles: [...draft.roles], require_all_roles: draft.all ? 1 : 0 }).then(() => {
        PH.toast("Access for " + page.title + " saved", "good");
        m.close();
        load();
      }).catch(() => { btn.disabled = false; });
    }
    update();
  }

  /** The "who is affected" block, shared by the editor and the confirm step. */
  function effectHtml(r, draft, page) {
    const names = (list, total) => list.map((u) => esc(u.name || u.user)).join(", ") + (total > list.length ? " and " + n(total - list.length) + " more" : "");
    let h = '<div class="st-effect__row"><b>' + n(r.after) + "</b> of " + n(data.people_total) + " active people could open this page <span class=\"ph-muted\">(now " + n(r.before) + ")</span></div>";
    if (r.lose_n) h += '<div class="st-effect__row st-effect__row--lose"><b>' + PH.fmt.plural(r.lose_n, "person", "people") + " would lose access:</b> " + names(r.lose, r.lose_n) + "</div>";
    if (r.gain_n) h += '<div class="st-effect__row"><b>' + PH.fmt.plural(r.gain_n, "person", "people") + " would gain access:</b> " + names(r.gain, r.gain_n) + "</div>";
    if (!r.lose_n && !r.gain_n) h += '<div class="st-effect__row ph-muted">No one’s access changes.</div>';
    if (!draft.roles.size) h += '<div class="ph-notice ph-notice--warn">With no role listed, nobody can open ' + esc(page.title) + " (including its v2 page) until a role is added again.</div>";
    else if (r.you_before && !r.you_after) h += '<div class="ph-notice ph-notice--warn">You would lose access to this page yourself.</div>';
    if (page.also_opens.length) h += '<div class="st-effect__row ph-muted">Also applies to: ' + page.also_opens.map((a) => esc(a.label) + " (v2)").join(", ") + ".</div>";
    return '<div class="st-effect__box">' + h + "</div>";
  }

  /* ── Peak hours ────────────────────────────────────────────────── */

  function paintPeak() {
    const saved = { enabled: !!data.peak.enabled, start: clock(data.peak.start), end: clock(data.peak.end) };
    const draft = Object.assign({}, saved);
    const el = PH.$("#c-peak");
    const dis = CAN_MANAGE ? "" : " disabled";
    el.innerHTML =
      '<div class="ph-card__head"><div><h2 class="ph-card__title">Peak hours</h2><div class="ph-card__meta">Controls when deployment requests are held for a Projects Manager</div></div><div id="pk-now"></div></div>' +
      '<div class="ph-form ph-form--1 st-peak">' +
        '<div class="ph-field"><label class="ph-switch"><input type="checkbox" id="pk-on"' + (draft.enabled ? " checked" : "") + dis + "><i></i><span>Hold deployment requests raised during peak hours</span></label>" +
          '<div class="ph-field__hint">When on, a deployment request created inside the window is held until a Projects Manager approves it. Requests already created are not changed.</div></div>' +
        '<div class="ph-form ph-form--2"><div class="ph-field"><label for="pk-start">Window starts</label><input class="ph-control" type="time" id="pk-start" value="' + esc(draft.start) + '"' + dis + '></div>' +
        '<div class="ph-field"><label for="pk-end">Window ends</label><input class="ph-control" type="time" id="pk-end" value="' + esc(draft.end) + '"' + dis + "></div></div>" +
        '<div class="ph-field__error" id="pk-err" role="alert"></div><div class="ph-field__hint" id="pk-sum"></div>' +
        (CAN_MANAGE
          ? '<div class="st-foot st-foot--inline"><button class="ph-btn" type="button" id="pk-reset">Undo changes</button><button class="ph-btn ph-btn--primary" type="button" id="pk-save">Save peak hours</button></div>'
          : '<div class="ph-notice ph-notice--signal ph-mb-0">Read only. Changing peak hours needs both Dev Team and System Manager.</div>') +
      "</div>";
    const $ = (s) => PH.$(s, el);

    function problem() {
      return draft.enabled && (!draft.start || !draft.end) ? "Set both a start and an end time before turning this on." : "";
    }
    function summary() {
      if (!draft.enabled) return "Off: deployment requests are never held because of the time of day.";
      if (!draft.start || !draft.end) return "";
      if (draft.start === draft.end) return "Start and end are the same time, which means every request is held, at any hour.";
      const wrap = draft.start > draft.end ? " (crosses midnight, ending the next morning)" : "";
      return "Requests created from " + draft.start + " to " + draft.end + wrap + " are held, using the site’s clock.";
    }
    function paint() {
      const p = problem();
      PH.text($("#pk-err"), p);
      $("#pk-err").hidden = !p;
      PH.text($("#pk-sum"), summary());
      $("#pk-start").disabled = $("#pk-end").disabled = !CAN_MANAGE || !draft.enabled;
      if (CAN_MANAGE) {
        const dirty = JSON.stringify(draft) !== JSON.stringify(saved);
        $("#pk-save").disabled = !dirty || !!p;
        $("#pk-reset").disabled = !dirty;
      }
      const now = data.peak.inside_now;
      PH.set($("#pk-now"), !saved.enabled ? '<span class="ph-badge ph-badge--outline">Off</span>'
        : now == null ? "" : now ? '<span class="ph-badge ph-badge--warn">Right now: inside the window, new requests are held</span>' : '<span class="ph-badge ph-badge--good">Right now: outside the window</span>');
    }
    $("#pk-on").addEventListener("change", (e) => { draft.enabled = e.target.checked; paint(); });
    $("#pk-start").addEventListener("input", (e) => { draft.start = e.target.value; paint(); });
    $("#pk-end").addEventListener("input", (e) => { draft.end = e.target.value; paint(); });
    if (CAN_MANAGE) {
      $("#pk-reset").addEventListener("click", paintPeak);
      $("#pk-save").addEventListener("click", () => savePeak(draft, summary()));
    }
    paint();
  }

  function savePeak(draft, sentence) {
    const m = PH.modal({
      title: "Save peak hours?",
      body: '<p>' + esc(sentence) + '</p><p class="ph-muted">Deployment requests are flagged once, when they are created. This changes only requests created from now on.</p>',
      actions: [
        { label: "Cancel" },
        {
          label: "Save peak hours", primary: true,
          onClick: () => PH.call(WRITE + "update_peak_hours_settings", {
            peak_hours_enabled: draft.enabled ? 1 : 0,
            peak_start_time: draft.start ? draft.start + ":00" : null,
            peak_end_time: draft.end ? draft.end + ":00" : null,
          }).then(() => { PH.toast("Peak hours saved", "good"); load(); }),
        },
      ],
    });
    return m;
  }

  /* ── Start ─────────────────────────────────────────────────────── */
  PH.$("#f-q").value = st.get("q");
  DevKeys.init({ title: "Settings", list: { root: "#ph-main", items: () => PH.$$("#ph-main tbody tr.is-link") } });
  PH.onRefresh(load);
  load();
})();
