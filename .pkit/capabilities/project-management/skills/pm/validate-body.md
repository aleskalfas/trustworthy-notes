# pm validate-body — check an issue body against the methodology

Sub-procedure of the pm composite skill (`pm.md` in this folder). Per [project-management:DEC-020-methodology-as-executable-commands], this sub-procedure has thinned to an intent-to-command router: the methodology's body rules live in `body-format.yaml` + `titles.yaml` + `classification.yaml` + `issue-types.yaml`; the deterministic `validate-issue.py` script reads them and surfaces findings; this file maps user intent to the script invocation.

## When to use this operation

- Just before re-stamping an issue body after an edit (e.g., the user supplied new acceptance criteria — validate the result before pushing).
- Before transitioning an issue to Done — the close-gate from [project-management:DEC-007-checkbox-validation] is checked here.
- On first interaction with an inherited issue (filed before the capability was installed, or filed in a different repo) — surfaces every rule violation as a starting point for the operator to fix.
- As a CI gate when the adopter wires the script into a PR check (the script's `--json` output is designed for that).

This operation **does not mutate** the issue. It reports findings; the caller decides whether to edit the body (then re-validate), bypass (with audit; not yet automated in v0.3.x), or accept the warnings.

## What the script enforces

The deterministic enforcement lives in `scripts/validate-issue.py`. It reads `issue-types.yaml` (structural-type inference from title prefix), `titles.yaml` (per-type title regex), `body-format.yaml` (per-type required sections + universal body rules), `classification.yaml` (axes presence + mutual exclusion), and the adopter's `project/config.yaml` (substrate mode).

Behaviour summary (the script is the source of truth):

- **Membership gate** (per [project-management:DEC-021-team-membership-gate]) — closed mode refuses non-members.
- **Title format** — validates `[Type] ...` prefix against the per-type regex.
- **Required body sections** — checks every `## Heading` listed in `body-format.yaml`'s `required_sections` for the inferred type.
- **Parent-ref first line** — checks the first non-empty body line matches the `parent_ref_form` for the type (when `parent_ref_optional: false`).
- **Classification axes** — `type:*` label required and mutually exclusive; `priority:*` and `workstream:*` required only in label-fallback mode.
- **Mandatory assignment** (per [project-management:DEC-019-mandatory-issue-state]) — surfaces as a warning at validate-time; would be hard-reject at filing.
- **Universal body rules** — h1 (`# ...`) headings forbidden (the issue title is the h1); `file:line` references emit a warning (line numbers go stale).

Findings are tagged by the severity token read from the relevant schema entry: `[validation-severity:hard-reject]`, `[validation-severity:bypassable-with-audit]`, or `[validation-severity:warning]`. The script's output groups by severity and the exit code carries the gate:

- Exit `0` — every check passed, or only warning-level findings.
- Exit `1` — one or more `hard-reject` or `bypassable-with-audit` findings.
- Exit `2` — usage error (issue not found; `gh` failure).

## How to invoke

Dispatch via the kit-level capability-command dispatcher (per [pkit:COR-021]):

```
pkit project-management validate-issue <issue-number> [--json] [--capability-root <path>]
```

Direct-path is equivalent:

```
.pkit/capabilities/project-management/scripts/validate-issue.py 42 --json
```

`--json` is the canonical surface for CI integration; the JSON shape carries the issue number, title, and findings array (each with `severity`, `label`, `detail`).

## Handling the script's output

- **No findings** — surface "no findings" cleanly. The body is valid against every rule the methodology mandates.
- **Findings present** — surface the script's output verbatim. Do not re-summarise or re-order; the severity grouping + `summary:` line are the contract.
- For each blocking finding, recommend the remediation: edit the body to add missing sections, fix the title prefix, etc. After the user edits, re-run the script.
- For warning-level findings, mention them but do not block — the user decides whether to address now or defer.

## Intent recognition

The LLM's only judgment before invoking is which issue to validate. Everything downstream is the script's job — pass the issue number through and surface the result.

## Forward-looking note — bypass flag

`bypassable-with-audit` severity findings (per [project-management:DEC-014-validation-severity-model]) are recognised by the script today but the `--bypass "<reason>"` invocation form is a follow-up. When it lands, this sub-procedure walks the audit-comment ceremony before the bypassing mutation runs.
