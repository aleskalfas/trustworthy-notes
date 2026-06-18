---
variant: specialized
---

# Rules

Operational rules and tool hygiene patterns the kit ships for any project that adopts it. The kit-shipped content is the single file `core.md`; adopters' own rules live in their root `CLAUDE.md` (or whichever agent-instruction file the adopter uses) rather than within this area, since `CLAUDE.md` is the natural composition point for cross-cutting rules.

## Layout

```
.pkit/rules/
├── README.md                             # this file
└── core.md                               # kit's universal hard rules + tool hygiene
```

`core.md` is **kit-owned** (propagation per COR-001): refreshed on every sync, not editable by adopters. To extend the rules in your project, add them to your root `CLAUDE.md` directly — `CLAUDE.md` already includes `@.pkit/rules/core.md` at the top, so kit and project rules compose naturally without needing a `.pkit/rules/project.md` slot.

## What goes in `core.md`

Two categories:

- **Hard rules** — invariants whose violation breaks the methodology. The no-shared-files invariant, the acceptance gate, paired-skill / `pkit new` for kit-shipped artifacts, migrations idempotency, etc.
- **Tool hygiene** — operational practices that keep work consistent. Run `pkit` from project root, pause for destructive ops, conventional commits, surface-change → version-bump, validate before assuming state.

Each rule is terse — one statement plus a pointer to the COR / area README that owns the rationale. The rules file is read by every agent at session start (via `CLAUDE.md`'s `@<path>` include); it is operational, not expository.

`core.md` itself follows rule 13 (the `@`-include authoring convention): no top-level heading, opens with an italic preface, sections start at H2. The host `CLAUDE.md` owns the H1 and places the `@<path>` line after its intro paragraph, so the included sections become natural sub-sections of the host. This pattern applies to any future kit-shipped file intended for `@`-include.

## What does NOT go in `core.md`

- **Rationale.** That lives in the cited COR / PRJ / area README. The rules file points; it does not re-state.
- **Project-kit-internal mechanics.** Things like the project-kit's own version-bump policy (PRJ-002) belong in the project's own records and CLAUDE.md, not in the kit-shipped rules adopters receive. The rules file uses project-neutral phrasing — adopters never see project-kit-specific content there.
- **Adopter-specific rules.** Those go in the adopter's root `CLAUDE.md`.
