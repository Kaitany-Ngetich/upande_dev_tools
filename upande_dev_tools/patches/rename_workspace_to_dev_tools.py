# Copyright (c) 2026, Upande LTD and contributors
# For license information, please see license.txt

from upande_dev_tools.setup import rename_legacy_workspace


def execute():
	"""Workspace.label carries a unique index, and the pre-rename row is already labelled
	"Dev Tools", so importing workspace/dev_tools/dev_tools.json inserts a second row and dies on
	that index. Runs pre_model_sync: sync_all imports the file during run_schema_updates, before
	any after_migrate hook could rename the docname."""
	rename_legacy_workspace()
