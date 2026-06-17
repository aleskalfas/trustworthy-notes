
# Validating evidence citations

This skill runs the **evidence** capability's validator against a scope — a directory holding an `evidence.yaml` plus the prose that cites it (per [evidence:DEC-002-evidence-record-schema]). The validator's contract is fixed by [evidence:DEC-003-validation-model]. The skill is shipped as part of an installable capability per COR-017.

## When this skill applies

Run the validator:

- Before committing changes to prose that cites `[ev:<slug>]` tokens. Catch typos, missing records, and dropped citations locally.
- As a CI gate. The exit code (`0` clean, `1` violations) plugs directly into any pipeline.
- After moving prose between scopes. Citations resolve against the *new* scope's `evidence.yaml`; the validator surfaces any that no longer resolve.
- After updating `evidence.yaml` (renaming a slug, removing a record). The validator surfaces every cite that needs to migrate.

## Procedure

### 1. Pick the scope

The scope is the directory containing the `evidence.yaml` to validate against. The validator walks **that directory and its sub-tree** (per [evidence:DEC-002-evidence-record-schema]):

```sh
.pkit/capabilities/evidence/scripts/validate.py <scope-dir>
```

Example: validating a research scope rooted at `research/api-survey/`:

```sh
.pkit/capabilities/evidence/scripts/validate.py research/api-survey/
```

If no `evidence.yaml` exists at the scope root, the validator surfaces the absence as an error — see [evidence:DEC-003-validation-model]'s "What counts as a failure" table.

### 2. Read the output

The validator prints to stderr. Two shapes:

**Clean run:**

```
evidence: 12 citations validated against research/api-survey/evidence.yaml — all resolved.
```

Exit code: `0`.

**Violations:**

```
research/api-survey/overview.md:14 — cited slug 'auth-token-ttl' has no record
research/api-survey/overview.md:23 — cited slug 'webhook-retry-policy' has no record

evidence: 2 violation(s); see above.
```

Exit code: `1`.

### 3. Resolve the violations

For each `cited slug has no record` finding:

- **Typo in the slug:** fix the prose to match the slug in `evidence.yaml`.
- **Record genuinely missing:** capture it via the `evidence-add` skill, then re-run the validator.
- **Citation belongs elsewhere:** if the fact lives in a different scope, move the prose to that scope (or the record to this one) — citations don't cross scopes in v1 (per [evidence:DEC-003-validation-model]).

### 4. Multi-scope validation

The validator handles one scope per invocation. For a tree with multiple `evidence.yaml` files, wrap it:

```sh
find . -name evidence.yaml -print | while read f; do
  scope="$(dirname "$f")"
  echo "=== $scope ==="
  .pkit/capabilities/evidence/scripts/validate.py "$scope" || true
done
```

Drop the `|| true` if you want the loop to halt on the first failing scope.

### 5. Strict mode

`--strict` elevates orphan records (records in `evidence.yaml` not cited by any prose) from "soft" to "error" per [evidence:DEC-003-validation-model]:

```sh
.pkit/capabilities/evidence/scripts/validate.py --strict <scope-dir>
```

Use this in mature scopes where orphans are unexpected. In active authoring, orphans are common (records captured before the prose that cites them); skip `--strict` until the scope settles.

## Common pitfalls

- **Citation inside a fenced code block is missed.** Intentional — the validator strips fenced blocks before scanning per [evidence:DEC-003-validation-model]. If you want a code block to be validated, the prose around it should carry the citation.
- **Citation inside an `excerpt:` field is missed.** Intentional. Excerpts may quote citation-shaped tokens from upstream content; the validator strips them.
- **`evidence.yaml` parse error.** The validator can't proceed against a malformed file. Fix the YAML syntax first — the error message points at the line.
- **Mixed scopes in one validation run.** If your scope-dir contains a sub-directory with its own `evidence.yaml`, the validator does not descend into it (the sub-directory is its own scope). Validate each scope separately.

## Variations

- **Pre-commit hook.** Wire `validate.py` into a git pre-commit hook for the scopes you actively author in. The exit code does the rest.
- **CI integration.** Add a job that walks every `evidence.yaml` in the repo and runs the validator per scope. Fail the build on any non-zero exit.
