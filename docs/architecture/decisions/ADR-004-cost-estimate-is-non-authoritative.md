# ADR-004: Cost estimate is a convenience figure, not an accounting record

- Status: Accepted
- Date: 2026-06-20

**In one minute:** the tool shows a per-run cost figure, but Anthropic publishes no pricing API, so the rates must be hardcoded and will drift. We resolve the tension by declaring the figure **non-authoritative**: it is an estimate (labelled with an as-of date), the real spend guardrail is the server-side workspace cap, and a stale price table is therefore a UX annoyance rather than a correctness defect. Token *usage* is read accurately from the provider; only the *prices* are estimates.

## Context

Extraction runs cost money, and showing the user a per-action / per-run cost is genuinely useful. Token **usage** is reported accurately by the provider in `response.usage` (input, output, cache-creation, cache-read), so the *quantities* are trustworthy. The **prices**, however, are not available from any Anthropic programmatic endpoint — there is no pricing API to query — so the per-token rates must be hardcoded in the tool.

This creates an unavoidable drift problem: a hardcoded price table baked into a tagged-release binary (see ADR-001) goes stale on a schedule the vendor controls and we do not. A released exe cannot self-correct its rates, and we are not going to chase Anthropic's price changes with a release each time. The honest question is therefore not "how do we keep the table current" but "what is this number allowed to mean, given that it will be wrong sometimes."

## Decision

**Pricing lives in one dedicated leaf module, stamped with an as-of date.** `pricing.py` holds per-model, per-token-type constants (input / output / cache-write at 5-minute and 1-hour tiers / cache-read), with a `PRICING_AS_OF` date constant that is bumped whenever a rate changes. The displayed figure is **labelled an estimate carrying that date**, so the user can see how current it is. The module is a pure leaf: it is depended on, never depends — in particular it imports no pipeline code.

**Unknown models degrade gracefully.** A model id not in the table returns `None` ("estimate unavailable"), never a misleading `$0`, and never a crash (`estimate_cost`). A new model the user points at produces an honest "we can't price this," not a wrong number.

**The figure is a convenience estimate, not an accounting record.** The authoritative spend limit is the **server-side Anthropic workspace spend cap** — a control that cannot be wrong because it is enforced where the money is actually spent. The local estimate exists to give the user a sense of cost, not to bound it. This reframing is the load-bearing decision: it makes a stale price table a **UX annoyance, not a correctness defect**, because no decision with financial consequences depends on the local number being exact.

## Consequences

- **Refreshing prices is routine maintenance, not a hotfix.** When Anthropic changes pricing, someone edits the constants and bumps `PRICING_AS_OF` in the next ordinary release. Because the figure is non-authoritative, a lag between a vendor price change and our release ships a slightly-wrong estimate — visibly dated — not a defect.
- **The server-side cap must actually exist and be set.** This ADR leans on it as the real guardrail; if no workspace spend cap is configured, the safety story collapses to "trust a hardcoded table," which it explicitly is not. Provisioning the cap is an operational precondition of this decision.
- **The estimate must always read as an estimate.** Its as-of date and "estimate" framing in the UI are part of the contract, not decoration — they are what keep the user from mistaking it for a bill. Dropping the label would quietly promote a non-authoritative number to an authoritative-looking one.
- **`pricing.py` must stay a leaf.** Its value as a tiny, swappable price sheet depends on having no pipeline coupling. A future feature that reaches *from* pricing into the pipeline (or vice versa) erodes that and should be resisted.
- **Usage accuracy and price accuracy are separate guarantees.** The token counts are exact (from the provider); only the rates are estimates. A future maintainer debugging a "wrong cost" should look at the price table and its date first — the usage side is not the suspect.
