---
name: benchmark-enhancement-capture
description: "MANDATORY after any benchmark close-loop or real-case run where AI judgment recovered a previously-failing case. Closes the enhancement loop by turning each AI-judgment recovery into structured candidates for permanent absorption into the plugin: (a) deterministic program rules (rtl_hygiene_lint additions, spec_conformance_check predicates, runner auto-emits), (b) ic-expert-agent skill sections (LLM-judgment patterns that don't reduce to a deterministic rule), or (c) community-backlog entries for larger engineering work. Without this skill, the AI-judgment recoveries stay one-off — they don't propagate to the next benchmark run or to the new user installing the plugin. Triggers on: 'capture enhancements', 'absorb recoveries', 'enhance plugin from this run', '把這次救回的東西寫回 plugin', 'closed-loop enhance', after every /vibe-ic-benchmark close-loop, and after every real-case close-loop in benchmark_clean / vibe-ic-all."
---

# benchmark-enhancement-capture — the plugin's complement-and-codify loop

This skill is what makes Vibe-IC's plugin **complement** (compound returns)
over time. Without it, every AI-judgment recovery is a one-off — the next
benchmark run, the next real-case run, and the next new-plugin-install user
all start from the same baseline. With it, every recovery has a path to
**permanently** improve the plugin so the same fix is automatic next time.

## When to invoke

- **MANDATORY** after every `/vibe-ic-benchmark` close-loop where any
  previously-failing design moved to PASS via AI judgment (not just
  deterministic gate fix).
- **MANDATORY** after every real-case run in `benchmark_clean/` or via
  `/vibe-ic-all` where a close-loop agent applied a chip-agnostic fix that a
  future runner could have applied automatically.
- **STRONGLY ENCOURAGED** at the end of any session where multiple
  AI-judgment fixes accumulated, even if individual fixes were small.

## The three buckets — every recovery goes into ONE

For each `(design, before-RTL, after-RTL, AI-reasoning)` recovery record:

### Bucket A — deterministic program rule
The reasoning reduces to **a structural pattern** that a Python program can
detect and apply without LLM judgment. Examples:
- "Restoring division remainder must be `dividend_width + 1` bits, not
  `dividend_width`" → new `rtl_hygiene_lint.py` rule + auto-`--fix`.
- "Module hardcodes 64-bit width but module name contains 'pipe'/'pipeline'
  → suggest adding `parameter DATA_WIDTH=64`" → new `spec_conformance_check`
  WARN.
- "Output port declared before clk/reset in description order, but TB likely
  uses output-first positional → reorder" → `chip_top_gate_wrapper_gen`
  enhancement.

**Emit**: a patch to the relevant `programs/*.py` file with the new rule,
PLUS a **corpus-sweep verification recipe**: list of repos / sample sets the
new rule must run cleanly against before shipping (zero false-positives).

### Bucket B — ic-expert-agent skill section
The reasoning requires **LLM judgment / pattern recognition** that doesn't
reduce to a deterministic rule. Examples:
- "When TB samples the clock at `t = k·(PERIOD/2)` with blocking statements
  in active region, use NBA toggle so sample lands pre-toggle."
- "Phrase 'whether the result has been consumed' implies a downstream-ready
  input port."
- "RTLLM benchmark family conventionally uses positional output-first
  instantiation."

**Emit**: a new `### Skill: <name>` section appended to
`agents/ic-expert-agent.md`, with the worked example + the general pattern.

### Bucket C — community-backlog entry
The fix is general and important but needs larger engineering work to ship
properly (corpus sweep, new program, new test fixtures). Examples:
- "Ship a deterministic `rtl_gen` for `digital_arithmetic_primitive` IC class"
  — major undertaking; needs spec extraction + template library.
- "Phase1 NL ingester emits 0 facts on free-form RTLLM prompts" — needs
  re-engineering the fact extractor.

**Emit**: a `community/backlogs/ORGANIC-<date>-<slug>.yaml` per the existing
schema (type / severity / component / pattern / suggested_fix / id /
submitted_at / session_context).

### Bucket D — DISCARD (overfit / one-off)
The fix only works for that specific design's quirks or peeks at hidden TB
conventions. Examples:
- "Rename module name from spec-stated `freq_diveven` to dir-name
  `freq_divbyeven`" — works for THIS benchmark's typo but encoding it as a
  general rule would over-fit. Document the *judgment* (description vs dir
  typo handling) as Bucket B if generalizable; otherwise discard.
- "Hardcode the exact 6-state encoding the TB happens to use" — pure
  hidden-TB peek.

**Emit**: nothing to plugin; record in the session's RESULT for honesty.

## Procedure

1. **Collect recovery records**. Input: pairs `(<design>, <prior-fail-sample>, <recovered-pass-sample>, <AI-reasoning>)`. Source = the close-loop agents' final reports + git diff between samples/.

2. **Per record, classify** into Bucket A/B/C/D. The 80/20 heuristic:
   - If the fix is `s/foo/bar/` syntactic or a structural template → A.
   - If the fix requires pattern-recognizing an English phrase or convention → B.
   - If A or B looks right but the engineering effort is large → C.
   - If neither A nor B generalizes → D.

3. **Emit candidates** via `programs/enhancement_emit.py` (the deterministic helper):
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/programs/enhancement_emit.py \
       --records <recoveries.json> \
       --out-skill-section <patch.md> \
       --out-program-rules <patch.py> \
       --out-backlogs <dir>/
   ```

4. **Review the candidates** (Bucket A program rules need corpus-sweep verification BEFORE being applied; Bucket B skills can be appended directly; Bucket C backlogs can be filed immediately).

5. **Apply Bucket A + B**. Commit + push. Bump plugin patch version.

6. **Verify forward**: the NEXT benchmark run should pick up the rule
   automatically. If the same design now passes from a fresh run without
   close-loop, the loop closed correctly.

## Honesty rules

- **NEVER auto-apply a Bucket A rule** that triggers on the corpus-sweep set
  with any false-positives. The rule must be strictly safer than the prior
  state.
- **NEVER add a Bucket B skill section** that names specific benchmark design
  identifiers. Skills are general patterns, not lookup tables.
- **NEVER expand Bucket B into "the AI should just author the right RTL"** —
  that's not a skill, that's wishing the problem away.
- **NEVER discard (Bucket D) without a written reason** in the session
  RESULT. "Why this fix wasn't generalizable" is itself useful signal for
  future benchmark designers.

## This skill is the difference between "we tried RTLLM" and "Vibe-IC ships better"

Every AI-judgment recovery this session was a learning moment. Without this
skill, those learnings stay in this session's RESULT and evaporate. With this
skill, they become plugin code + agent skills + filed backlogs — and the next
new user who installs Vibe-IC gets all of them automatically.

That is the closed loop.
