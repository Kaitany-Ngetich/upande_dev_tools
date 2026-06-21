frappe.ui.form.on("Module Version Check", {
    refresh(frm) {
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
                        if (r.exc) {
                            frappe.msgprint(__("Version check failed. Please check the error logs."));
                            return;
                        }

                        if (r.message) {
                            frm.set_value("status", r.message.status);
                            frm.set_value("status_message", r.message.status_message);
                            frm.set_value("repository_url", r.message.repository_url);
                            frm.set_value("repository_name", r.message.repository_name);
                            frm.set_value("current_commit", r.message.current_commit);
                            frm.set_value("current_branch", r.message.current_branch);
                            frm.set_value("upstream_branch", r.message.upstream_branch);
                            frm.set_value("commits_ahead", r.message.commits_ahead);
                            frm.set_value("commits_behind", r.message.commits_behind);
                            frm.set_value("has_uncommitted_changes", r.message.has_uncommitted_changes);
                            frm.set_value("safe_to_deploy", r.message.safe_to_deploy);
                            frm.set_value("risk_level", r.message.risk_level);
                            frm.set_value("last_checked_at", r.message.last_checked_at);
                            frm.set_value("last_checked_by", r.message.last_checked_by);

                            frm.refresh_fields();

                            frappe.show_alert({
                                message: __("Version check completed: {0}", [r.message.status]),
                                indicator: r.message.status === "Clean" ? "green" : "orange"
                            });

                            setTimeout(function () {
                                frm.reload_doc();
                            }, 700);
                        }
                    }
                });
            }).addClass("btn-primary");

            frm.add_custom_button(__("Fetch Remote Updates"), function () {
                frappe.call({
                    method: "upande_dev_tools.upande_dev_tools.doctype.module_version_check.module_version_check.run_freshness_check_with_fetch",
                    args: {
                        docname: frm.doc.name
                    },
                    freeze: true,
                    freeze_message: __("Fetching remote repository updates..."),
                    callback: function (r) {
                        if (r.exc) {
                            frappe.msgprint(__("Remote fetch check failed. Please check the error logs."));
                            return;
                        }

                        if (r.message) {
                            frm.reload_doc();

                            frappe.show_alert({
                                message: __("Remote fetch check completed: {0}", [r.message.status]),
                                indicator: r.message.status === "Clean" ? "green" : "blue"
                            });
                        }
                    }
                });
            });
        }
    }
});