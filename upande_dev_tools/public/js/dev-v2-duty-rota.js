/* Duty Rota page script. Every call goes to upande_dev_tools.api.duty (the same API the Dev Tools app uses); the
   server re-checks every rule, the checks here only catch mistakes before sending. */
(function () {
  "use strict";
  const API = "upande_dev_tools.api.duty.";
  const caps = PH.$("#dr-caps").dataset;
  const CAN_MANAGE = caps.canManage === "1";
  const ME = caps.me;
  const st = PH.state({ view: "rota", type: "", past: "", mine: "", status: "", layout: "calendar", month: "" });
  const MAX_LANES = 4;
  // Soft fills that read like holidays on a wall calendar; a slot keeps its colour (hash of its name).
  const TONES = ["teal", "amber", "violet", "rose", "sky", "lime"];
  const STATUS_BADGE = { Pending: "warn", Approved: "good", Rejected: "bad", Cancelled: "outline" };
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  let types = [], rota = null, requests = [], people = null, seq = 0;

  /* ── Dates (plain YYYY-MM-DD; a duty day is a calendar day, no time zone) ── */
  const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;
  function validDate(s) {
    const m = DATE_RE.exec(String(s || "").trim());
    if (!m) return false;
    const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
    return d.getUTCFullYear() === +m[1] && d.getUTCMonth() === +m[2] - 1 && d.getUTCDate() === +m[3];
  }
  function parts(s) {
    const m = DATE_RE.exec(s);
    return [+m[1], +m[2], +m[3]];
  }
  function range(a, b) {
    if (!validDate(a)) return "";
    const [y1, m1, d1] = parts(a);
    if (!validDate(b) || a === b) return d1 + " " + MONTHS[m1 - 1] + " " + y1;
    const [y2, m2, d2] = parts(b);
    if (y1 !== y2) return d1 + " " + MONTHS[m1 - 1] + " " + y1 + " – " + d2 + " " + MONTHS[m2 - 1] + " " + y2;
    if (m1 !== m2) return d1 + " " + MONTHS[m1 - 1] + " – " + d2 + " " + MONTHS[m2 - 1] + " " + y2;
    return d1 + " – " + d2 + " " + MONTHS[m2 - 1] + " " + y2;
  }
  function weekday(s) {
    const [y, m, d] = parts(s);
    return DAYS[new Date(Date.UTC(y, m - 1, d)).getUTCDay()];
  }
  const title = (s) => (s.label && s.label.trim()) || range(s.start_date, s.end_date);
  const isOn = (s, u) => s.assignees.some((a) => a.user === u);
  const when = (s, t) => (s.end_date < t ? "past" : s.start_date > t ? "upcoming" : "current");
  const nameOf = (u) => {
    const p = (people || []).find((x) => x.user === u);
    return p ? p.full_name : u;
  };
  const badge = (s) => '<span class="ph-badge ph-badge--' + (STATUS_BADGE[s] || "outline") + '">' + PH.esc(s) + "</span>";

  /* ── Filters and tabs ── */
  PH.$("#tabs").addEventListener("click", (e) => {
    const b = e.target.closest("[data-view]");
    if (b) st.set({ view: b.dataset.view });
  });
  PH.$("#f-type").addEventListener("change", (e) => st.set({ type: e.target.value }));
  PH.$("#f-past").addEventListener("change", (e) => st.set({ past: e.target.checked ? "1" : "" }));
  PH.$("#f-mine").addEventListener("change", (e) => st.set({ mine: e.target.checked ? "1" : "" }));
  PH.bindSelect("#f-status", st, "status");
  if (CAN_MANAGE) PH.$("#new-slot").onclick = () => editSlot(null);

  st.on((state, changed) => {
    if (changed.includes("type") || changed.includes("month")) return load();
    paint();
  });
  PH.pills("#f-layout", st, "layout");
  PH.$("#cal-prev").onclick = () => st.set({ month: shiftMonth(month(), -1) });
  PH.$("#cal-next").onclick = () => st.set({ month: shiftMonth(month(), 1) });
  PH.$("#cal-today").onclick = () => st.set({ month: PH.date.today().slice(0, 7) });

  /* ── Month maths (weeks start on Monday) ── */
  const month = () => (/^\d{4}-\d{2}$/.test(st.get().month) ? st.get().month : PH.date.today().slice(0, 7));
  function shiftMonth(m, n) {
    const [y, mo] = m.split("-").map(Number);
    const d = new Date(y, mo - 1 + n, 1);
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0");
  }
  function grid(m) {
    const first = m + "-01";
    const dow = (PH.date.parse(first).getDay() + 6) % 7; // 0 = Monday
    const start = PH.date.add(first, -dow);
    const last = PH.date.add(shiftMonth(m, 1) + "-01", -1);
    const weeks = Math.ceil((dow + PH.date.diff(first, last) + 1) / 7);
    return { start, end: PH.date.add(start, weeks * 7 - 1), weeks };
  }
  const shortDate = (d) => +d.slice(8) + " " + MONTHS[+d.slice(5, 7) - 1];
  const firstName = (a) => String(a.full_name || a.user).trim().split(/\s+/)[0];
  function tone(name) {
    let h = 0;
    for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0;
    return TONES[h % TONES.length];
  }

  /* ── Loading ── */
  async function boot() {
    // The app's deep link shape (/duty?tab=requests) works here too.
    if (new URLSearchParams(location.search).get("tab") === "requests") st.set({ view: "requests" }, { silent: true });
    PH.kpiSkeleton("#kpis", ["Your next duty", "On duty now", "Slots ahead", "Pending requests"]);
    try {
      types = await PH.call(API + "duty_types", {}, { type: "GET" });
    } catch (e) {
      return PH.error("#rota", e.message, boot);
    }
    if (!types.length) {
      PH.$("#view-rota").hidden = false;
      return PH.empty("#rota", "No duty types yet", CAN_MANAGE ? "Add one under Master Data → Duty types." : "Ask a project manager to set one up.");
    }
    if (!types.some((t) => t.name === st.get().type)) st.set({ type: types[0].name }, { silent: true });
    PH.options("#f-type", types.map((t) => ({ value: t.name, label: t.duty_name })), st.get().type);
    PH.call(API + "people", {}, { type: "GET", silent: true }).then((p) => (people = p || [])).catch(() => (people = []));
    load();
  }

  /** The calendar's month plus the list's usual window (4 weeks back, 26 ahead), in one call. */
  function window_(type) {
    const g = grid(month()), t = PH.date.today();
    const back = PH.date.add(t, -28), ahead = PH.date.add(t, 182);
    return { duty_type: type, start: g.start < back ? g.start : back, end: g.end > ahead ? g.end : ahead };
  }

  async function load() {
    const my = ++seq;
    const type = st.get().type;
    PH.skeleton("#rota", "rows", 6);
    try {
      const [r, q] = await Promise.all([
        PH.call(API + "rota", window_(type), { type: "GET" }),
        PH.call(API + "change_requests", { duty_type: type }, { type: "GET" }),
      ]);
      if (my !== seq) return;
      rota = r;
      requests = q || [];
      paint();
    } catch (e) {
      if (my === seq) PH.error("#rota", e.message, load);
    }
  }

  /* ── Painting ── */
  function paint() {
    if (!rota) return;
    const s = st.get(), t = PH.date.today();
    PH.$("#f-past").checked = !!s.past;
    PH.$("#f-mine").checked = !!s.mine;
    PH.$$("#tabs .ph-tab").forEach((b) => b.classList.toggle("is-on", b.dataset.view === s.view));
    PH.$("#view-rota").hidden = s.view !== "rota";
    PH.$("#view-requests").hidden = s.view !== "requests";
    const pending = requests.filter((r) => r.status === "Pending");
    const next = rota.slots.find((x) => x.end_date >= t && isOn(x, ME));
    const now = rota.slots.filter((x) => when(x, t) === "current");
    PH.kpis("#kpis", [
      // Short values: the KPI figure is large type; the detail goes underneath.
      { label: "Your next duty", value: next ? shortDate(next.start_date) : "None", unit: next ? title(next) + (next.start_date !== next.end_date ? " · until " + shortDate(next.end_date) : "") : "Nothing planned for you", onClick: next ? () => st.set({ view: "rota", layout: "calendar", month: next.start_date.slice(0, 7) }) : null },
      (() => {
        const names = now.flatMap((x) => x.assignees.map(firstName)).filter((v, i, a) => a.indexOf(v) === i);
        return { label: "On duty now", value: names.length, unit: names.length ? names.join(", ") : "Nobody today" };
      })(),
      { label: "Slots ahead", value: rota.slots.filter((x) => x.start_date > t).length },
      { label: "Pending requests", value: pending.length, onClick: () => st.set({ view: "requests", status: "Pending" }) },
    ]);
    PH.text("#tc-requests", pending.length);
    paintRota(s, t, pending);
    paintRequests(s);
  }

  function paintRota(s, t, pending) {
    const cal = s.layout !== "list";
    PH.$("#cal-nav").hidden = !cal;
    PH.$("#f-past").closest("label").hidden = cal;
    PH.$("#rota-meta").textContent = cal ? "Click a slot for details and actions" + (CAN_MANAGE ? ", or an empty day to add one" : "") : "4 weeks back to 26 weeks ahead";
    if (cal) return paintCalendar(s, t, pending);
    let slots = rota.slots;
    if (!s.past) slots = slots.filter((x) => x.end_date >= t);
    if (s.mine) slots = slots.filter((x) => isOn(x, ME));
    PH.text("#tc-rota", slots.length);
    if (!slots.length) return PH.empty("#rota", "No slots to show", s.past ? "" : "Tick “Show past slots” to see earlier ones.");
    const busy = new Set(pending.flatMap((r) => [r.slot, r.swap_slot]).filter(Boolean));
    const rows = slots
      .map((x) => {
        const w = when(x, t);
        const daily = x.start_date === x.end_date;
        const chips = x.assignees.length
          ? x.assignees.map((a) => '<span class="dr-person' + (a.user === ME ? " is-me" : "") + '">' + PH.esc(a.full_name) + "</span>").join("")
          : '<span class="ph-muted">Nobody yet</span>';
        const acts = [];
        if (w !== "past" && (isOn(x, ME) || CAN_MANAGE) && x.assignees.length) acts.push('<button class="ph-btn ph-btn--sm" data-act="request">Request change</button>');
        if (CAN_MANAGE) {
          acts.push('<button class="ph-btn ph-btn--sm ph-btn--ghost" data-act="edit">Edit</button>');
          acts.push('<button class="ph-btn ph-btn--sm ph-btn--ghost" data-act="delete">Delete</button>');
        }
        return (
          '<tr class="dr-row--' + w + '" data-slot="' + PH.esc(x.name) + '">' +
          '<td class="dr-when"><strong>' + PH.esc(range(x.start_date, x.end_date)) + "</strong>" + (daily ? "<small>" + weekday(x.start_date) + "</small>" : "") + "</td>" +
          "<td>" + PH.esc(x.label || "") + (w === "current" ? ' <span class="ph-badge ph-badge--signal">Now</span>' : "") + (busy.has(x.name) ? ' <span class="ph-badge ph-badge--warn">Change pending</span>' : "") +
          (x.notes ? '<div class="dr-reason">' + PH.esc(x.notes) + "</div>" : "") + "</td>" +
          '<td><div class="dr-people">' + chips + "</div></td>" +
          '<td><div class="dr-actions">' + acts.join("") + "</div></td></tr>"
        );
      })
      .join("");
    PH.set("#rota", '<div class="ph-table-wrap"><table class="ph-table"><thead><tr><th>When</th><th>Slot</th><th>People</th><th></th></tr></thead><tbody>' + rows + "</tbody></table></div>");
    PH.$$("#rota [data-act]").forEach((b) => {
      const slot = rota.slots.find((x) => x.name === b.closest("tr").dataset.slot);
      b.onclick = () => ({ request: requestChange, edit: editSlot, delete: deleteSlot })[b.dataset.act](slot);
    });
  }

  /* ── Calendar ── */
  function paintCalendar(s, t, pending) {
    const m = month(), g = grid(m);
    const [y, mo] = m.split("-").map(Number);
    PH.text("#cal-title", MONTHS[mo - 1] + " " + y);
    const busy = new Set(pending.flatMap((r) => [r.slot, r.swap_slot]).filter(Boolean));
    let slots = rota.slots.filter((x) => x.end_date >= g.start && x.start_date <= g.end);
    if (s.mine) slots = slots.filter((x) => isOn(x, ME));
    PH.text("#tc-rota", slots.length);
    let html = '<div class="dr-cal" role="grid"><div class="dr-cal__dow">' + ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => "<div>" + d + "</div>").join("") + "</div>";
    for (let w = 0; w < g.weeks; w++) {
      const ws = PH.date.add(g.start, w * 7), we = PH.date.add(ws, 6);
      // Segments of every slot touching this week, longest first, packed into lanes.
      const segs = slots
        .filter((x) => x.end_date >= ws && x.start_date <= we)
        .map((x) => {
          const a = x.start_date > ws ? x.start_date : ws, b = x.end_date < we ? x.end_date : we;
          return { x, c0: PH.date.diff(ws, a), c1: PH.date.diff(ws, b), head: x.start_date >= ws, tail: x.end_date <= we };
        })
        .sort((p, q) => q.c1 - q.c0 - (p.c1 - p.c0) || p.c0 - q.c0);
      const lanes = [];
      segs.forEach((sg) => {
        let i = lanes.findIndex((l) => l.every((o) => o.c1 < sg.c0 || o.c0 > sg.c1));
        if (i === -1) i = lanes.push([]) - 1;
        lanes[i].push(sg);
        sg.lane = i;
      });
      html += '<div class="dr-cal__week" style="--lanes:' + Math.min(lanes.length, MAX_LANES) + '">';
      for (let d = 0; d < 7; d++) {
        const day = PH.date.add(ws, d);
        const hidden = segs.filter((sg) => sg.lane >= MAX_LANES && sg.c0 <= d && sg.c1 >= d).length;
        html +=
          '<div class="dr-cal__day' + (day.slice(0, 7) !== m ? " is-out" : "") + (day === t ? " is-today" : "") + (d > 4 ? " is-weekend" : "") +
          '" style="grid-column:' + (d + 1) + '" data-day="' + day + '"><span class="dr-cal__num">' + +day.slice(8) + "</span>" +
          (hidden ? '<button class="dr-cal__more" data-more="' + day + '">+' + hidden + " more</button>" : "") + "</div>";
      }
      segs
        .filter((sg) => sg.lane < MAX_LANES)
        .forEach((sg) => {
          const x = sg.x;
          // One-day pieces list the people one per line (like names on a holiday calendar); longer bars stay on one line.
          const oneDay = sg.c0 === sg.c1;
          const names = x.assignees.length
            ? x.assignees.map((a) => PH.esc(firstName(a))).join(oneDay ? "<br>" : " · ")
            : "Nobody yet";
          const label = x.label ? "<b>" + PH.esc(x.label) + "</b>" + (oneDay ? "<br>" : " ") : "";
          html +=
            '<button class="dr-ev dr-ev--' + tone(x.name) + (isOn(x, ME) ? " is-me" : "") + (x.end_date < t ? " is-past" : "") +
            (sg.head ? " is-head" : "") + (sg.tail ? " is-tail" : "") + (oneDay ? " dr-ev--day" : "") + '" data-slot="' + PH.esc(x.name) +
            '" style="grid-column:' + (sg.c0 + 1) + " / " + (sg.c1 + 2) + ";grid-row:" + (sg.lane + 2) +
            '" title="' + PH.esc(title(x) + " · " + range(x.start_date, x.end_date) + "\n" + x.assignees.map((a) => a.full_name).join(", ")) + '">' +
            (busy.has(x.name) ? '<i class="dr-ev__dot" aria-label="Change pending"></i>' : "") +
            '<span class="dr-ev__text">' + label + names + "</span></button>";
        });
      html += "</div>";
    }
    html += "</div>";
    html += '<div class="dr-cal__legend"><span><i class="dr-ev dr-ev--teal is-me"></i> You are on it</span><span><i class="dr-ev__dot"></i> Change pending</span>' +
      (slots.length ? "" : '<span class="ph-muted">No slots this month</span>') + "</div>";
    PH.set("#rota", html);
    PH.$$("#rota .dr-ev[data-slot]").forEach((b) => (b.onclick = (e) => {
      e.stopPropagation();
      slotDetails(rota.slots.find((x) => x.name === b.dataset.slot), busy);
    }));
    PH.$$("#rota [data-more]").forEach((b) => (b.onclick = (e) => {
      e.stopPropagation();
      dayList(b.dataset.more, slots, busy);
    }));
    if (CAN_MANAGE)
      PH.$$("#rota .dr-cal__day").forEach((c) => {
        c.classList.add("is-editable");
        c.onclick = () => newSlotOn(c.dataset.day);
      });
  }

  function newSlotOn(day) {
    const type = types.find((x) => x.name === st.get().type) || {};
    // A weekly duty starts as the week from that day; anything else as that one day. Both can be changed.
    editSlot(null, { start_date: day, end_date: type.default_cadence === "Weekly" ? PH.date.add(day, 6) : day });
  }

  function slotDetails(slot, busy) {
    const t = PH.date.today();
    const people = slot.assignees.length
      ? '<div class="dr-people">' + slot.assignees.map((a) => '<span class="dr-person' + (a.user === ME ? " is-me" : "") + '">' + PH.esc(a.full_name) + "</span>").join("") + "</div>"
      : '<span class="ph-muted">Nobody yet</span>';
    const pend = requests.filter((r) => r.status === "Pending" && (r.slot === slot.name || r.swap_slot === slot.name));
    const actions = [{ label: "Close" }];
    if (CAN_MANAGE) actions.unshift({ label: "Delete", danger: true, onClick: () => { deleteSlot(slot); } });
    if (CAN_MANAGE) actions.push({ label: "Edit", onClick: () => { editSlot(slot); } });
    if (slot.end_date >= t && slot.assignees.length && (isOn(slot, ME) || CAN_MANAGE))
      actions.push({ label: "Request change", primary: true, onClick: () => { requestChange(slot); } });
    PH.modal({
      title: title(slot),
      sub: range(slot.start_date, slot.end_date) + (slot.start_date === slot.end_date ? " · " + weekday(slot.start_date) : "") + " · " + slot.duty_type,
      body:
        '<div class="ph-stack"><div><div class="ph-label">On duty</div>' + people + "</div>" +
        (slot.notes ? '<div><div class="ph-label">Notes</div><div>' + PH.esc(slot.notes) + "</div></div>" : "") +
        (pend.length ? '<div class="ph-notice ph-notice--warn">' + pend.map((r) => PH.esc(summary(r))).join("<br>") + "</div>" : "") +
        "</div>",
      actions,
    });
  }

  function dayList(day, slots, busy) {
    const list = slots.filter((x) => x.start_date <= day && x.end_date >= day);
    const m = PH.modal({
      title: range(day, day) + " · " + weekday(day),
      body: '<div class="ph-list">' + list.map((x) =>
        '<button class="dr-daylist ph-list__row" data-slot="' + PH.esc(x.name) + '"><span class="dr-ev dr-ev--' + tone(x.name) + ' dr-ev--swatch"></span><span><b>' +
        PH.esc(title(x)) + "</b><br><small>" + PH.esc(x.assignees.map((a) => a.full_name).join(", ") || "Nobody yet") + "</small></span></button>").join("") + "</div>",
      actions: [{ label: "Close" }],
    });
    PH.$$("[data-slot]", m.body).forEach((b) => (b.onclick = () => {
      m.close();
      slotDetails(rota.slots.find((x) => x.name === b.dataset.slot), busy);
    }));
  }

  function summary(r) {
    const slot = r.slot_label || range(r.slot_start, r.slot_end) || "a deleted slot";
    if (r.request_type === "Swap") {
      const other = r.swap_slot_label || (r.swap_slot_start ? range(r.swap_slot_start, r.swap_slot_end || r.swap_slot_start) : "");
      return r.from_user_name + " swaps " + slot + " with " + r.to_user_name + (other ? " (" + other + ")" : "");
    }
    return r.to_user_name + " covers " + r.from_user_name + " on " + slot;
  }

  function paintRequests(s) {
    const list = s.status ? requests.filter((r) => r.status === s.status) : requests;
    PH.text("#req-meta", CAN_MANAGE ? "Every request for this duty type" : "Requests you raised or that name you");
    if (!list.length) return PH.empty("#requests", "No requests", "");
    const rows = list
      .map((r) => {
        const acts = [];
        if (r.status === "Pending" && CAN_MANAGE) {
          acts.push('<button class="ph-btn ph-btn--sm ph-btn--primary" data-act="approve">Approve</button>');
          acts.push('<button class="ph-btn ph-btn--sm ph-btn--ghost" data-act="reject">Reject</button>');
        }
        if (r.status === "Pending" && (r.requested_by === ME || CAN_MANAGE)) acts.push('<button class="ph-btn ph-btn--sm ph-btn--ghost" data-act="cancel">Cancel</button>');
        const decided = r.decided_by ? r.status + " by " + (r.decided_by_name || r.decided_by) + (r.decision_note ? ": " + r.decision_note : "") : "";
        return (
          '<tr data-req="' + PH.esc(r.name) + '"><td>' + badge(r.status) + "</td>" +
          "<td><strong>" + PH.esc(summary(r)) + "</strong>" + (r.reason ? '<div class="dr-reason">' + PH.esc(r.reason) + "</div>" : "") + (decided ? '<div class="dr-reason">' + PH.esc(decided) + "</div>" : "") + "</td>" +
          "<td>" + PH.esc(r.requested_by_name) + '<div class="dr-reason">' + PH.esc(PH.fmt.date(String(r.creation || "").slice(0, 10))) + "</div></td>" +
          '<td class="ph-mono">' + PH.esc(r.name) + "</td>" +
          '<td><div class="dr-actions">' + acts.join("") + "</div></td></tr>"
        );
      })
      .join("");
    PH.set("#requests", '<div class="ph-table-wrap"><table class="ph-table"><thead><tr><th>Status</th><th>Change</th><th>Asked by</th><th>Request</th><th></th></tr></thead><tbody>' + rows + "</tbody></table></div>");
    PH.$$("#requests [data-act]").forEach((b) => {
      const name = b.closest("tr").dataset.req;
      b.onclick = () => ({ approve: () => decide(name, true), reject: () => decide(name, false), cancel: () => cancel(name) })[b.dataset.act]();
    });
  }

  /* ── Actions ── */
  async function decide(name, approve) {
    if (approve) {
      if (!(await PH.confirm("Approve this change?", "The rota is updated straight away and everyone involved is told."))) return;
      await PH.call(API + "decide", { name, approve: 1 });
      PH.toast("Approved", "good");
      return load();
    }
    PH.modal({
      title: "Reject this request",
      body: '<div class="ph-form ph-form--1"><div class="ph-field"><label for="dr-note">Note for the requester</label><textarea class="ph-input" id="dr-note" rows="3"></textarea></div></div>',
      actions: [
        { label: "Cancel" },
        {
          label: "Reject",
          danger: true,
          onClick: async (m) => {
            await PH.call(API + "decide", { name, approve: 0, note: m.body.querySelector("#dr-note").value });
            PH.toast("Rejected", "good");
            load();
          },
        },
      ],
    });
  }

  async function cancel(name) {
    if (!(await PH.confirm("Cancel this request?", "Nothing on the rota changes.", { ok: "Cancel request", cancel: "Keep it", danger: true }))) return;
    await PH.call(API + "cancel_request", { name });
    PH.toast("Cancelled", "good");
    load();
  }

  async function deleteSlot(slot) {
    if (!(await PH.confirm("Delete " + title(slot) + "?", "The people on it are told. Slots with a pending request cannot be deleted.", { ok: "Delete", danger: true }))) return;
    await PH.call(API + "delete_slot", { name: slot.name });
    PH.toast("Slot deleted", "good");
    load();
  }

  function personOptions(list, selected) {
    return list.map((p) => '<option value="' + PH.esc(p.user) + '"' + (p.user === selected ? " selected" : "") + ">" + PH.esc(p.full_name) + "</option>").join("");
  }

  function editSlot(slot, preset) {
    const t = PH.date.today();
    const s = slot || Object.assign({ duty_type: st.get().type, label: "", start_date: t, end_date: t, notes: "", assignees: [] }, preset || {});
    const on = new Set(s.assignees.map((a) => a.user));
    const pool = (people || []).slice();
    s.assignees.forEach((a) => !pool.some((p) => p.user === a.user) && pool.push({ user: a.user, full_name: a.full_name }));
    const body =
      '<div class="ph-form ph-form--2">' +
      '<div class="ph-field"><label for="ds-start">Start date *</label><input class="ph-input" id="ds-start" type="date" value="' + PH.esc(s.start_date) + '"></div>' +
      '<div class="ph-field"><label for="ds-end">End date *</label><input class="ph-input" id="ds-end" type="date" value="' + PH.esc(s.end_date) + '"><div class="ph-field__hint">Same as the start for a daily slot</div></div>' +
      '<div class="ph-field"><label for="ds-label">Label</label><input class="ph-input" id="ds-label" type="text" maxlength="140" placeholder="e.g. Week 47" value="' + PH.esc(s.label) + '"></div>' +
      '<div class="ph-field"><label for="ds-type">Duty type</label><select class="ph-select" id="ds-type">' + types.map((x) => '<option value="' + PH.esc(x.name) + '"' + (x.name === s.duty_type ? " selected" : "") + ">" + PH.esc(x.duty_name) + "</option>").join("") + "</select></div>" +
      '<div class="ph-field ph-field--full"><label>People</label><div class="dr-picklist">' +
      pool.map((p) => '<label class="ph-check"><input type="checkbox" value="' + PH.esc(p.user) + '"' + (on.has(p.user) ? " checked" : "") + "> " + PH.esc(p.full_name) + "</label>").join("") +
      "</div></div>" +
      '<div class="ph-field ph-field--full"><label for="ds-notes">Notes</label><textarea class="ph-input" id="ds-notes" rows="2">' + PH.esc(s.notes) + "</textarea></div>" +
      '<div class="ph-field__error ph-field--full" id="ds-err" role="alert"></div></div>';
    PH.modal({
      title: slot ? "Edit " + title(slot) : "New slot",
      size: "lg",
      body,
      actions: [
        { label: "Cancel" },
        {
          label: "Save",
          primary: true,
          onClick: async (m) => {
            const $ = (id) => m.body.querySelector(id);
            const draft = {
              name: slot ? slot.name : undefined,
              duty_type: $("#ds-type").value,
              label: $("#ds-label").value.trim(),
              start_date: $("#ds-start").value,
              end_date: $("#ds-end").value,
              notes: $("#ds-notes").value.trim(),
              assignees: PH.$$("input[type=checkbox]:checked", m.body).map((c) => c.value),
            };
            const problem = !validDate(draft.start_date)
              ? "Start date must be a real date."
              : !validDate(draft.end_date)
              ? "End date must be a real date."
              : draft.end_date < draft.start_date
              ? "The end date is before the start date."
              : null;
            if (problem) {
              $("#ds-err").textContent = problem;
              return false;
            }
            await PH.call(API + "save_slot", { slot: JSON.stringify(draft) });
            PH.toast("Slot saved", "good");
            load();
          },
        },
      ],
    });
  }

  function requestChange(slot) {
    const others = rota.slots.filter((x) => x.name !== slot.name && x.end_date >= PH.date.today() && x.assignees.length);
    const fromList = CAN_MANAGE ? slot.assignees : slot.assignees.filter((a) => a.user === ME);
    const covers = (people || []).filter((p) => !isOn(slot, p.user));
    const body =
      '<div class="ph-form ph-form--1">' +
      '<div class="ph-field"><label>What kind of change</label><div class="ph-pills" id="rq-type"><button data-value="Swap" class="is-on">Swap with someone</button><button data-value="Replace">Someone covers</button></div></div>' +
      '<div class="ph-field"><label for="rq-from">Who leaves ' + PH.esc(title(slot)) + "</label><select class=\"ph-select\" id=\"rq-from\"" + (CAN_MANAGE ? "" : " disabled") + ">" + personOptions(fromList, CAN_MANAGE ? "" : ME) + "</select></div>" +
      '<div class="ph-field" data-for="Swap"><label for="rq-swap">The slot taken in return</label><select class="ph-select" id="rq-swap"><option value="">Pick a slot</option>' +
      others.map((x) => '<option value="' + PH.esc(x.name) + '">' + PH.esc(title(x) + " · " + range(x.start_date, x.end_date)) + "</option>").join("") + "</select></div>" +
      '<div class="ph-field" data-for="Swap"><label for="rq-swap-to">Swap with</label><select class="ph-select" id="rq-swap-to"><option value="">Pick the slot first</option></select></div>' +
      '<div class="ph-field" data-for="Replace" hidden><label for="rq-cover">Who covers</label><select class="ph-select" id="rq-cover"><option value="">Pick someone</option>' + personOptions(covers, "") + "</select></div>" +
      '<div class="ph-field"><label for="rq-reason">Reason</label><textarea class="ph-input" id="rq-reason" rows="2"></textarea></div>' +
      '<div class="ph-field__error" id="rq-err" role="alert"></div></div>';
    let type = "Swap";
    const m = PH.modal({
      title: "Request a change",
      sub: title(slot) + " · " + range(slot.start_date, slot.end_date),
      body,
      actions: [
        { label: "Cancel" },
        {
          label: "Send request",
          primary: true,
          onClick: async (md) => {
            const $ = (id) => md.body.querySelector(id);
            const from = $("#rq-from").value || ME;
            const swap = type === "Swap" ? rota.slots.find((x) => x.name === $("#rq-swap").value) : null;
            const to = type === "Swap" ? $("#rq-swap-to").value : $("#rq-cover").value;
            let problem = null;
            if (!isOn(slot, from)) problem = "That person is not on this slot.";
            else if (!to) problem = type === "Swap" ? "Pick who to swap with." : "Pick who covers.";
            else if (to === from) problem = "Pick someone else.";
            else if (isOn(slot, to)) problem = "They are already on this slot.";
            else if (type === "Swap" && !swap) problem = "Pick the slot taken in return.";
            else if (type === "Swap" && isOn(swap, from)) problem = "They are already on that slot.";
            if (problem) {
              $("#rq-err").textContent = problem;
              return false;
            }
            await PH.call(API + "request_change", {
              slot: slot.name,
              request_type: type,
              from_user: from,
              to_user: to,
              swap_slot: swap ? swap.name : undefined,
              reason: $("#rq-reason").value.trim(),
            });
            PH.toast("Request sent to the project manager", "good");
            st.set({ view: "requests" });
            load();
          },
        },
      ],
    });
    const body$ = (id) => m.body.querySelector(id);
    body$("#rq-type").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-value]");
      if (!b) return;
      type = b.dataset.value;
      PH.$$("#rq-type button", m.body).forEach((x) => x.classList.toggle("is-on", x === b));
      PH.$$("[data-for]", m.body).forEach((f) => (f.hidden = f.dataset.for !== type));
    });
    body$("#rq-swap").addEventListener("change", (e) => {
      const target = rota.slots.find((x) => x.name === e.target.value);
      body$("#rq-swap-to").innerHTML = target
        ? '<option value="">Pick someone</option>' + personOptions(target.assignees.filter((a) => !isOn(slot, a.user)), "")
        : '<option value="">Pick the slot first</option>';
    });
  }

  PH.ready(boot);
})();
