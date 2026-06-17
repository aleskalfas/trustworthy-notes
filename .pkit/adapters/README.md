---
variant: adapter-umbrella
---

# Adapters

Each AI harness — Claude Code, Codex, Cursor, etc. — has its own way of loading skills, agents, and configuration. The kit's own content (skills, agents, decisions, workflow) is harness-agnostic by design (per COR-006), but at some point the kit's content has to be **translated** for the harness an adopter is using: settings ported into the harness's expected file format and location, skills symlinked to the harness's expected directory, and so on.

That translation work lives here. Each harness has its own adapter directory, self-contained: `.pkit/adapters/<harness-name>/`.

## Layout

```
.pkit/adapters/
├── README.md                        # this file
└── <harness-name>/                  # one directory per supported harness
    ├── README.md                    # what this adapter handles, how to deploy it
    └── (harness-specific content)   # settings, deploy scripts, runtime artifacts
```

Per COR-005's bundle/adapter pattern: each adapter is an alternative implementation of "translate kit content for a specific harness." Adopters install the adapter that matches their AI tooling.

## Currently shipped

- **`claude-code/`** — the Claude Code adapter. Ships permissions baseline (settings/), a deploy script for skills (deploy-skills.sh), and the runtime conventions Claude Code expects.

## Adding a new harness

1. Create `.pkit/adapters/<new-harness-name>/`.
2. Add a `README.md` describing what the harness expects and how this adapter satisfies that.
3. Author the harness-specific content — typically some combination of settings/config files (matching the harness's format), deploy scripts (translating kit-shipped skills/agents to the harness's expected paths), and any runtime artifacts the harness needs.
4. Update this README's "Currently shipped" list.

The structural rule is light because adapters are heterogeneous by nature — Codex's settings format differs from Claude Code's; Cursor may not need a deploy script at all if it loads skills from canonical paths directly. Each adapter ships what's needed; the README of the adapter explains.
