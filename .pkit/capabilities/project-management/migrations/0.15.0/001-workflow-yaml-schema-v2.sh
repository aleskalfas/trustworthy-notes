#!/usr/bin/env bash
# project-management 0.15.0 — workflow.yaml schema_version 1 → 2.
#
# DEC-026 introduces seven verb-subject workflow-wrapper commands that
# compose over `move-issue`. The schema bump adds two fields to every
# transition entry — `command:` (naming the owning wrapper) and
# `pr_state_effect:` (the PR-state effect) — plus two new no-issue-
# transition rows that model the PR sub-lifecycle (`create-draft`,
# `back-to-draft`).
#
# The kit-shipped `workflow.yaml` under `.pkit/capabilities/project-
# management/schemas/` is propagated by sync (it lives in the kit-owned
# tree). Adopters who haven't customised the file will get the new
# version directly from sync — no migration action needed on their part.
#
# The migration's job: detect the case where an adopter has overridden
# the kit-shipped `workflow.yaml` (e.g., to extend `applies_to` on a
# specific transition or add a project-specific row) and surface a
# warning so the adopter can update their override to add the
# `command:` and `pr_state_effect:` fields. The migration does NOT
# modify project-owned overrides — that would silently clobber
# adopter intent.
#
# Idempotent: re-runs on already-migrated state are no-ops.
#
# Run via the upgrade runtime with ROOT=<adopter root>.

set -euo pipefail

: "${ROOT:?ROOT must be set by the upgrade runtime}"

CAP_DIR="$ROOT/.pkit/capabilities/project-management"
PROJECT_OVERRIDES_DIR="$CAP_DIR/project/schema-overrides"
WORKFLOW_OVERRIDE="$PROJECT_OVERRIDES_DIR/workflow.yaml"
KIT_WORKFLOW="$CAP_DIR/schemas/workflow.yaml"

if [ ! -d "$CAP_DIR" ]; then
    echo "  [skip] project-management capability not installed at $CAP_DIR"
    exit 0
fi

# Kit-shipped workflow.yaml is updated by sync; we only need to verify
# the bump landed.
if [ ! -f "$KIT_WORKFLOW" ]; then
    echo "  [warn] kit-shipped workflow.yaml not found at $KIT_WORKFLOW; sync may not have completed"
    exit 0
fi

current_kit_version=$(grep -E '^schema_version:' "$KIT_WORKFLOW" | head -1 | awk '{print $2}')
if [ "$current_kit_version" != "2" ]; then
    echo "  [warn] kit-shipped workflow.yaml schema_version is $current_kit_version (expected 2); sync may not have completed"
    exit 0
fi

# Detect adopter override (the only place project-owned customisation
# lives is the schema-overrides subdir; this directory may not exist on
# adopters who haven't customised anything — that's the dominant case).
if [ ! -f "$WORKFLOW_OVERRIDE" ]; then
    echo "  [ok] no adopter override of workflow.yaml; nothing to migrate"
    exit 0
fi

# Adopter has an override. Check whether it's already at schema_version 2.
override_version=$(grep -E '^schema_version:' "$WORKFLOW_OVERRIDE" | head -1 | awk '{print $2}')
if [ "$override_version" = "2" ]; then
    echo "  [ok] adopter override at $WORKFLOW_OVERRIDE already at schema_version 2"
    exit 0
fi

# Print a structured warning. The adopter must hand-edit their override
# to add `command:` and `pr_state_effect:` to every transition row and
# add the two no-issue-transition rows (`create-draft`, `back-to-draft`).
# We do NOT auto-edit project-owned overrides — that's the no-shared-
# files invariant + the COR-010 migration discipline (project-owned
# state belongs to the adopter).
cat <<EOF
  [warn] adopter override of workflow.yaml needs manual migration:

    File: $WORKFLOW_OVERRIDE
    Current schema_version: $override_version
    Required schema_version: 2

  Required changes per DEC-026:

    1. Bump \`schema_version\` to 2.

    2. Add \`command:\` + \`pr_state_effect:\` to every \`transitions:\` row.
       Kit-default values (match by \`(from, to)\` tuple):

         todo → backlog         command: promote-issue   pr_state_effect: "none → none"
         backlog → in-progress  command: start-work      pr_state_effect: "none → none"
         in-progress → review   command: review-work     pr_state_effect: "none → ready | draft → ready"
         review → done          command: done-work       pr_state_effect: "ready → merged"
         in-progress → done     command: close-issue     pr_state_effect: "none → none"
         backlog → done         command: close-issue     pr_state_effect: "none → none"
         todo → done            command: close-issue     pr_state_effect: "none → none"

    3. Add two new no-issue-transition rows for PR sub-lifecycle:

         in-progress → in-progress  command: create-draft  pr_state_effect: "none → draft"
         review → review            command: back-to-draft pr_state_effect: "ready → draft"

  See:
    - $CAP_DIR/decisions/DEC-026-work-ownership-lifecycle.md (full schema)
    - $KIT_WORKFLOW (the kit-shipped reference)

  Migration cannot auto-edit project-owned overrides without risking
  silently clobbering adopter intent. Re-run \`pkit upgrade\` after
  editing the file; this migration becomes a no-op on subsequent runs
  once your override declares schema_version: 2.
EOF

exit 0
