/* Master Data v2: the "Duty types" card. Reads and writes through upande_dev_tools.api.duty (all_duty_types,
   save_duty_type); the server lets only project managers edit and re-checks every field. */
(function () {
  "use strict";
  const API = "upande_dev_tools.api.duty.";
  const CADENCES = ["Weekly", "Daily", "Custom"];
  let rows = [];

  async function load() {
    PH.skeleton("#dt-main", "rows", 3);
    try {
      rows = (await PH.call(API + "all_duty_types", {}, { type: "GET", silent: true })) || [];
    } catch (e) {
      return PH.error("#dt-main", e.message, load);
    }
    paint();
  }

  function paint() {
    if (!rows.length) return PH.empty("#dt-main", "No duty types yet", "Add the first one, for example Support.");
    const body = rows
      .map(
        (r) =>
          '<tr data-name="' + PH.esc(r.name) + '"><td class="is-strong">' + PH.esc(r.duty_name) + "</td><td>" + PH.esc(r.description || "") +
          "</td><td>" + PH.esc(r.default_cadence || "") + '</td><td class="ph-num">' + PH.esc(r.people_per_slot) + '</td><td class="ph-num">' + PH.esc(r.slots) +
          "</td><td>" + (r.is_active ? '<span class="ph-badge ph-badge--good">Active</span>' : '<span class="ph-badge ph-badge--outline">Inactive</span>') +
          '</td><td><button class="ph-btn ph-btn--sm ph-btn--ghost" data-edit>Edit</button></td></tr>'
      )
      .join("");
    PH.set(
      "#dt-main",
      '<div class="ph-table-wrap"><table class="ph-table"><thead><tr><th>Duty</th><th>What the people on duty do</th><th>Cadence</th><th class="ph-num">People per slot</th><th class="ph-num">Slots</th><th>Status</th><th></th></tr></thead><tbody>' +
        body + "</tbody></table></div>"
    );
    PH.$$("#dt-main [data-edit]").forEach((b) => (b.onclick = () => edit(rows.find((r) => r.name === b.closest("tr").dataset.name))));
  }

  function edit(row) {
    const r = row || { name: "", duty_name: "", description: "", default_cadence: "Weekly", people_per_slot: 2, is_active: 1 };
    PH.modal({
      title: row ? "Edit " + row.duty_name : "New duty type",
      body:
        '<div class="ph-form ph-form--2">' +
        '<div class="ph-field"><label for="dt-name">Name *</label><input class="ph-input" id="dt-name" maxlength="140" value="' + PH.esc(r.duty_name) + '"' + (row ? " disabled" : "") + "></div>" +
        '<div class="ph-field"><label for="dt-cad">Usual cadence</label><select class="ph-select" id="dt-cad">' +
        CADENCES.map((c) => "<option" + (c === r.default_cadence ? " selected" : "") + ">" + c + "</option>").join("") + "</select></div>" +
        '<div class="ph-field"><label for="dt-pps">People per slot</label><input class="ph-input" id="dt-pps" type="number" min="0" max="30" value="' + PH.esc(r.people_per_slot) + '"><div class="ph-field__hint">A suggestion; fewer only warns</div></div>' +
        '<div class="ph-field"><label class="ph-check"><input type="checkbox" id="dt-act"' + (r.is_active ? " checked" : "") + "> Active</label></div>" +
        '<div class="ph-field ph-field--full"><label for="dt-desc">What the people on duty do</label><textarea class="ph-input" id="dt-desc" rows="2">' + PH.esc(r.description || "") + "</textarea></div>" +
        '<div class="ph-field__error ph-field--full" id="dt-err" role="alert"></div></div>',
      actions: [
        { label: "Cancel" },
        {
          label: "Save",
          primary: true,
          onClick: async (m) => {
            const $ = (id) => m.body.querySelector(id);
            const name = $("#dt-name").value.trim();
            if (!name) {
              $("#dt-err").textContent = "A duty type needs a name.";
              return false;
            }
            await PH.call(API + "save_duty_type", {
              duty_type: JSON.stringify({
                name: row ? row.name : undefined,
                duty_name: row ? row.name : name,
                default_cadence: $("#dt-cad").value,
                people_per_slot: +$("#dt-pps").value || 0,
                is_active: $("#dt-act").checked ? 1 : 0,
                description: $("#dt-desc").value.trim(),
              }),
            });
            PH.toast("Duty type saved", "good");
            load();
          },
        },
      ],
    });
  }

  PH.ready(() => {
    if (!PH.$("#dt-main")) return;
    // Master Data opens only to people holding Dev Team + Projects Manager + System Manager, so a manager role is
    // always there; the server re-checks anyway.
    const add = PH.$("#dt-new");
    add.hidden = false;
    add.onclick = () => edit(null);
    load();
  });
})();
