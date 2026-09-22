### Dev Tools

Developer portal for Upande benches: request intake, backlog and deployment
tracking, code snapshots, and Frappe customization tooling.

The app installs a set of portal pages on top of a handful of DocTypes, so
developers, project managers and the people raising work all use the same
records. `/dev-tools` is the entry point — it redirects to whichever dashboard
the signed-in user's roles resolve to.

**Work intake and planning**

- `/requests-portal` — raise a Request against a project, typed by Request Type,
  Priority Level, Product Area and tags.
- `/backlog-board` — Requests grouped by workflow state, plus the Task backlog in
  list, Kanban (drag to set status) or Gantt view.
- `/my-backlog` — a single developer’s open work, sorted by deadline.
- `/review-queue` — what is waiting on a reviewer.
- `/pm-dashboard` — team workload, open vs. closed totals and project health
  across every project at once; `/dev-dashboard` is the per-developer equivalent.

**Deployments**

Deployment Request records track what is being released, to which Deployment
Instance, for which Deployment App, with the queue and full history exposed on
the dashboards.

**Code and customization tooling**

- `/code-editor` — in-browser Monaco editor.
- `/code-snapshots` — Code Backup Snapshot records, taken on the interval set in
  Code Backup Settings, covering DocTypes, Server Scripts and Client Scripts with
  a configurable retention window.
- `/hooks-explorer` — what every installed app registers for each Frappe hook,
  which is how hook collisions get found.
- `/master-data` — master records across apps in one place.
- Module Version Check — runs git against each app's repo (branch, upstream,
  commits ahead/behind, uncommitted changes) and reports a `safe_to_deploy` flag
  and risk level before a release.
- Field Difference Log — field-level drift between a snapshot's values and what
  is live, so a customization that was changed outside the app is visible.

**Access control**

Dev Portal Page records gate each route by role, editable at
`/dev-portal-settings`. A page can require any one of its roles or all of them.

### Selective Customization Export

In developer mode, **Customize Form → Actions → Export Customizations** opens a
dialog to bulk-select custom fields / field-level property setters (parent and
child tables) and write them to a chosen app's `custom/*.json`. Optional
checkboxes add DocType Links, DocType-level property settings, and custom
permissions. Existing customizations in the target files are preserved (merge,
not overwrite), so you can split a DocType's fields across multiple apps without
duplication. Output is byte-for-byte compatible with Frappe's native
`export_customizations`, so `bench migrate` syncs it identically.

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app upande_dev_tools
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/upande_dev_tools
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade
### CI

This app can use GitHub Actions for CI. The following workflows are configured:

- CI: Installs this app and runs unit tests on every push to `develop` branch.
- Linters: Runs [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and [pip-audit](https://pypi.org/project/pip-audit/) on every pull request.


### License

mit
