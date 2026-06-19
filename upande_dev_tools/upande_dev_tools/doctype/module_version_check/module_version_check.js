frappe.ui.form.on("Module Version Check", {
    refresh(frm) {
        // Global tool action: can run even from a new/unsaved form
        frm.add_custom_button(__("Scan Installed Apps"), function () {
            frappe.call({
                method: "upande_dev_tools.upande_dev_tools.doctype.module_version_check.module_version_check.scan_installed_apps",
                freeze: true,
                freeze_message: __("Scanning installed apps..."),
                callback: function (r) {
                    if (!r.exc && r.message) {
                        frappe.msgprint(
                            __(
                                "Scan complete.<br><br>Created: {0}<br>Updated: {1}<br>Skipped: {2}<br>Total Apps: {3}",
                                [
                                    r.message.created,
                                    r.message.updated,
                                    r.message.skipped,
                                    r.message.total
                                ]
                            )
                        );

                        frappe.set_route("List", "Module Version Check");
                    }
                }
            });
        });

        // Record-specific action: only show after the document is saved
        if (!frm.is_new()) {
            frm.add_custom_button(__("Run Version Check"), function () {
                if (!frm.doc.module_name) {
                    frappe.msgprint(__("Please enter the Module/App Name first."));
                    return;
                }

                frappe.call({
                    method: "upande_dev_tools.upande_dev_tools.doctype.module_version_check.module_version_check.run_freshness_check",
                    args: {
                        docname: frm.doc.name
                    },
                    freeze: true,
                    freeze_message: __("Checking repository status..."),
                    callback: function (r) {
                        if (!r.exc) {
                            frappe.show_alert({
                                message: __("Version check completed"),
                                indicator: "green"
                            });

                            frm.reload_doc();
                        }
                    }
                });
            }).addClass("btn-primary");
        }
    }
});