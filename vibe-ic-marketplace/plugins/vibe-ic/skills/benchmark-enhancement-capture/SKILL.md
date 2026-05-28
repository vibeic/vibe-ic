---
name: benchmark-enhancement-capture
description: "MANDATORY after ANY close-loop or real-case run where AI judgment recovered a previously-failing case — not just RTL authoring. Applies to EVERY step in the Vibe-IC flow: Phase 1 NL ingestion, Phase 2 spec-to-RTL / chip_top / synth / TB / eco_loop / lint / conformance / audit, Phase 3 synth / PnR / CTS / DRC / LVS / STA / IR-drop, Analog A1-A9, Mixed-Signal M1-M4, MCP-EDA tools, and benchmark harness itself. The skill turns each AI-judgment recovery into structured candidates for permanent absorption: (a) deterministic program rules patching the RIGHT program file per step, (b) skill section appended to the RIGHT skill file per step (ic-expert-agent for design judgment / sta-review for timing / drc-fix for DRC / analog-topology-select for analog topology / etc., per CAPTURE_ROUTING.json), (c) community-backlog entries for larger engineering work, or (d) honest discard. Without this loop, every recovery — RTL authoring, PnR closure, DRC waiver classification, analog topology authoring, MCP tool behavior — stays per-session and the plugin never compounds. Triggers on: 'capture enhancements', 'absorb recoveries', 'enhance plugin from this run', '把這次救回的東西寫回 plugin', 'closed-loop enhance', after every /vibe-ic-benchmark close-loop, after every real-case close-loop in benchmark_clean / /vibe-ic-all, after a phase3 timing close-loop, after an analog A2/A4/A6 close-loop, after an MCP tool gap surfaces."
---

# benchmark-enhancement-capture — the plugin's complement-and-codify loop

This skill is what makes Vibe-IC's plugin **compound** over time. Without it,
every AI-judgment recovery — at ANY step in the flow — is a one-off that
evaporates with the session. With it, every recovery has a path to permanently
improve the plugin so the same fix is automatic next time.

## Applies to EVERY step, not just RTL authoring

The first time this skill landed (v0.1.34) it captured 9 RTLLM spec-to-RTL
recoveries into the `ic-expert-agent` skill. But the SAME mechanism applies
to every step in the Vibe-IC flow — each step has its own canonical target
program (Bucket A) and target skill (Bucket B), declared in
`benchmark-harness/CAPTURE_ROUTING.json`:

| Step domain | Bucket A target (program) | Bucket B target (skill) |
|---|---|---|
| Phase 1 NL ingestion | `phase1_one_shot_runner.py`, `phase1_engine/ingest.py` | `agents/ic-expert-agent.md` |
| Phase 2 spec→RTL | `rtl_hygiene_lint.py`, `chip_top_gate_wrapper_gen.py`, `spec_conformance_check.py` | `agents/ic-expert-agent.md` |
| Phase 2 yosys / eco_loop | `phase2_one_shot_runner.py` | `synth-doctor`, `rtl-repair`, `phase2-rtl-verify` |
| Phase 3 synth / PnR | `phase3_one_shot_runner.py` | `synth-doctor`, `sta-review` |
| Phase 3 CTS / hold | `phase3_one_shot_runner.py` | `hold-fix`, `sta-review` |
| Phase 3 DRC | `phase3_one_shot_runner.py` | `drc-fix` |
| Phase 3 LVS | `phase3_one_shot_runner.py` | `lvs-triage` |
| Phase 3 IR-drop | `phase3_one_shot_runner.py` | `ir-drop-triage` |
| Analog A2 topology | `analog_a2_topology_select_check.py` | `analog-topology-select` |
| Analog A4 corner sweep | `analog_real_corner_sweep.py` | `ams-sim` |
| Analog A6 post-layout resim | `analog_a6_post_layout_resim_check.py` | `analog-extraction-resim` |
| Mixed-signal M1-M4 | `mixed_signal_m1_top_merge_check.py` | `mixed-signal-cosim` |
| MCP-EDA tool behavior | `mcp-eda-server/src/tools/*.js` | per-skill (`synth-doctor`, etc.) |
| Benchmark harness | `benchmark-harness/score_*.py` | `open-benchmark-methodology` |

The routing table is consulted by `programs/enhancement_emit.py` to put each
recovery in the right place.

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


## Compliance gate (vibe-ic-d - mandatory when deterministic edition is installed)

If you have the `vibe-ic-d` plugin installed alongside `vibe-ic-core`,
after producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/SKILL_NAME/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in this skill directory enumerates every required
element of your output: section headers, handoff lines, summary blocks.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
