frappe.listview_settings["Module Version Check"] = {
    get_indicator: function (doc) {
        if (doc.status === "Stale") {
            return [__("Stale Code"), "orange", "status,=,Stale"];
        }

        if (doc.status === "Clean") {
            return [__("Clean / Up-to-Date"), "green", "status,=,Clean"];
        }

        if (doc.status === "Ahead") {
            return [__("Ahead of Remote"), "blue", "status,=,Ahead"];
        }

        if (doc.status === "Dirty") {
            return [__("Uncommitted Changes"), "yellow", "status,=,Dirty"];
        }

        if (doc.status === "Error") {
            return [__("Check Failed"), "red", "status,=,Error"];
        }

        return [__("Not Checked"), "gray", "status,=,"];
    }
};