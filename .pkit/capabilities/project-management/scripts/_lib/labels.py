"""Shared label-reconciliation helper for project-management scripts.

Close-issue and move-issue both need to reconcile ``state:*`` labels after a
state change.  This module exports :func:`reconcile_state_labels_to_done` so
that ``close-issue`` can apply the same logic that ``move-issue`` uses without
duplicating the ``gh issue edit`` machinery.

The non-terminal state labels that a closing operation must remove are the
four states that precede ``done`` in the workflow state machine declared in
``workflow.yaml``: ``todo``, ``backlog``, ``in-progress``, ``review``.

``state:done`` is always added; the call is idempotent if the label is already
present (GitHub's ``gh issue edit --add-label`` is a no-op for a label the
issue already carries).
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _lib.gh import gh_run as _gh_run_type  # pragma: no cover

# Labels that must be removed on any terminal close.  Kept as a module-level
# constant so callers can reference it for diagnostics without hardcoding the
# list themselves.
NON_TERMINAL_STATE_LABELS: tuple[str, ...] = (
    "state:todo",
    "state:backlog",
    "state:in-progress",
    "state:review",
)

TERMINAL_STATE_LABEL = "state:done"


def reconcile_state_labels_to_done(
    issue_number: int,
    current_labels: list[str],
    config: dict,
    *,
    gh_run,
) -> bool:
    """Remove all non-terminal ``state:*`` labels and ensure ``state:done``.

    This is the shared reconcile routine reused by ``close-issue`` on both the
    wont-do and pr-merge close paths.  ``move-issue`` uses :func:`_compute_plan`
    + ``_gh_apply_state_label`` for the general case; this helper is the
    specialised terminal variant that handles *all* stale labels in one call.

    Parameters
    ----------
    issue_number:
        GitHub issue number to edit.
    current_labels:
        The label names currently on the issue (as returned by ``gh issue view
        --json labels``).  The function derives which non-terminal labels are
        present from this list.
    config:
        Adopter config dict (threaded to :func:`gh_run` for host/owner
        routing per DEC-023).
    gh_run:
        The ``gh_run`` callable from ``_lib.gh``.  Passed explicitly so this
        module stays importable without a circular dependency (both
        ``close-issue`` and this helper import from ``_lib.gh``; passing the
        function avoids a module-level import of ``_lib.gh`` here which would
        create an implicit dependency cycle on the ``sys.path`` insertion order
        used by the PEP 723 scripts).

    Returns
    -------
    bool
        ``True`` on success (or when no gh call was needed), ``False`` on gh
        failure.
    """
    stale = [lbl for lbl in current_labels if lbl in NON_TERMINAL_STATE_LABELS]
    has_done = TERMINAL_STATE_LABEL in current_labels

    if not stale and has_done:
        # Already correctly labelled — nothing to do.
        return True

    cmd = ["gh", "issue", "edit", str(issue_number), "--add-label", TERMINAL_STATE_LABEL]
    for stale_label in stale:
        cmd.extend(["--remove-label", stale_label])

    try:
        proc = gh_run(cmd, config, check=False)
    except FileNotFoundError:
        print("error: `gh` not on PATH.", file=sys.stderr)
        return False

    if proc.returncode != 0:
        print(
            f"error: gh issue edit (label reconcile) failed (exit {proc.returncode}).\n"
            f"stderr: {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return False

    return True
