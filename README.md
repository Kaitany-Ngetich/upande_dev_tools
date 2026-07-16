### Upande Dev Tools

Internal developer tools for Upande workflows

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
