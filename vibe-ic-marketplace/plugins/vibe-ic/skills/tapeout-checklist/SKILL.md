---
name: tapeout-checklist
description: Run the final pre-tapeout gate — confirm DRC, LVS, STA, IR-drop, EM, antenna, ERC, LEC, DFT coverage, and documentation are all green or explicitly waived before GDS hand-off. Use when the user says "tapeout", "tape-out", "sign-off checklist", "GDS release", "ready for fab".
---

# Tapeout Checklist

> **Doctrine (v0.1.50):** 把修法寫進工具，而非寫進 prompt。
> Mandatory program preflight first; AI is the backstop, not the lead.

Tape-out is a one-way door. This skill is the last-mile gate: every
signoff item must be accounted for, with either a green status or a
documented waiver approved by a named engineer.

## Mandatory Deterministic Preflight

Run all four programs and read their JSON outputs BEFORE narrating any
tape-out readiness verdict:

```bash
# 1. The flow-compliance gate is the SOLE final criterion (see § next):
python3 plugins/vibe-ic/programs/flow_compliance_check.py \
    <project_dir> --strict

# 2. Tapeout checklist generation:
python3 plugins/vibe-ic/programs/tapeout_checklist_gen.py <project>

# 3. Signoff audit aggregates DRC/LVS/STA verdicts:
python3 plugins/vibe-ic/programs/signoff_audit.py <project>

# 4. Foundry signoff plan + (if analog) mixed-signal signoff:
python3 plugins/vibe-ic/programs/foundry_signoff_plan_check.py <project>
python3 plugins/vibe-ic/programs/mixed_signal_signoff_check.py <project>
```

Plus, for chipignite-style submissions, the signoff-waiver pair from
the v0.1.49 doctrine sweep:

```bash
# 5. Waiver schema + content gate (HONESTY: refuses 'ai'/'agent' approver):
python3 plugins/vibe-ic/programs/signoff_waiver_emit.py \
    --validate-only --strict < signoff/waivers/*.json

# 6. Static IR-drop numeric BUDGET gate (max drop < pct*Vdd):
python3 plugins/vibe-ic/programs/ir_drop_budget_check.py \
    <ir_report_or_dir> --vdd <V> --budget-pct 10
```

**Refuse to claim tape-out-ready if any of these returns non-zero or
FAIL.** Only after ALL pass can the narrative proceed.

## ⛔ PHASE 2+3 SOLE ACCEPTANCE CRITERION (READ FIRST)

This skill produces `tapeout_signoff_check.json`. **That gate alone is NOT sufficient to claim Phase 2+3 complete.**

The **ONLY** valid completion signal for the full design flow is:

```
python3 vibe-ic/programs/flow_compliance_check.py <project_dir> --strict
```

returning ONE of three verdict states:

- `Overall: PASS` — every canonical step actually executed. Tape-out ready.
- `Overall: PASS_WITH_WAIVERS` — structurally complete BUT N step(s) DEFERRED. **NOT tape-out ready in the foundry sense.** Foundry-side sign-off must close every waiver on the commercial PDK + commercial sign-off deck before fab takes the GDS.
- `Overall: FAIL` — incomplete.

`flow_compliance_check` covers what `tapeout_signoff_check` does NOT: SPEF parasitic extraction, post-route MCMM STA, IR/EM/antenna/SI sign-off, post-layout gate-sim, SPICE correlation, ECO, metal fill, FPGA final recompile, and analog A1-A8. Skipping these and claiming "tapeout signoff PASS" because the 4-item gate is green is a process violation.

**Waiver semantics**: a waiver is `DEFERRED open work` not `PASS`. When summarising a `PASS_WITH_WAIVERS` run to a user, never say "all N steps PASS". Always disambiguate `executed PASS` from `deferred via waiver`.

Before declaring tape-out ready, **always** end with:

```
python3 vibe-ic/programs/flow_compliance_check.py <project_dir> --strict 2>&1 | tail -10
```

and paste the output into `FINAL_REPORT.md`. If `PASS_WITH_WAIVERS`, also enumerate every waiver (id, reason, ticket) inline in the report — do not bury them in the JSON file.

## When to use

- Final 1–2 weeks before GDS release
- After the final ECO
- As a nightly regression item for any design in the "tapeout window"

## Checklist categories (must all be green or waived)

Every mechanical row below is a **deterministic program** — the integer
counts, numeric thresholds, corner-slack comparisons and file-presence
assertions are NOT re-judged in prose. Run the program; read its JSON.

1. **Functional**
   - RTL regression 100% pass + coverage ≥ target (code/functional/assertion)
     — *enforced by* `programs/coverage_metric_check.py` (and the analog/
     state variants) + `programs/signoff_audit.py`.
   - Formal properties all proven or bounded — *enforced by* `programs/
     assertion_property_check.py`.
   - LEC RTL↔netlist clean — *enforced by* `programs/lec_equivalence_check.py`.
2. **Timing**
   - STA setup/hold/recovery/removal + min-pulse-width / max-transition /
     max-cap clean across all MCMM corners — *enforced by* `programs/
     sta_report_check.py` (+ `programs/corner_coverage_audit.py` for MCMM
     completeness).
3. **Power integrity**
   - Static IR-drop < budget (typical 5–10% Vdd) — *enforced by* `programs/
     ir_drop_budget_check.py` (numeric `max_drop < pct·Vdd` gate; presence/
     authenticity by `programs/ir_drop_report_check.py`; hotspot causes by
     `programs/ir_drop_triage_classify.py`).
   - EM current density < library limit — *enforced by* `programs/
     em_report_check.py`.
4. **Physical**
   - DRC 0 errors (or waivers signed) — *enforced by* `programs/
     drc_report_check.py`.
   - LVS clean — *enforced by* `programs/lvs_report_check.py` /
     `programs/lvs_signoff_guard.py`.
   - Antenna DRC clean — *enforced by* `programs/antenna_report_check.py`.
   - Density rules clean (min/max metal density) — *enforced by* `programs/
     metal_fill_density_check.py`.
   - ERC clean — *enforced by* `programs/erc_density_check.py`.
5. **Test** (DFT data missing = FAIL, not SKIP — v0.100 K3) — FOUNDRY / ATE bar
   - Scan ATPG **stuck-at** coverage ≥ **foundry floor (95 %, up to 98 %)**;
     a lenient written target is clamped UP to the floor; **missing DFT
     report = FAIL** — *enforced by* `programs/dft_atpg_coverage_check.py`
     (no SKIP path; recomputed, never a trusted self-asserted boolean).
   - **Transition (at-speed / launch-off-capture)** coverage ≥ target, OR a
     DOCUMENTED OSS-engine limitation (Fault is stuck-at-only — never a
     fabricated at-speed number) — *emitted by* `programs/fault_atpg_run.py`
     (`transition` block + `transition_atpg_plan.md`).
   - MBIST integrated/simulated + **boundary-scan BSDL present for a padded
     design** (bare core → honest N/A) — *emitted + gated by*
     `programs/bsdl_emit.py` (BSDL + boundary-scan-cell-per-pad plan).
   - The three roll up into `programs/dft_signoff_check.py` (aggregate DFT
     sign-off: stuck-at + transition + BSDL; absent evidence FAILs honestly).
6. **Power intent**
   - UPF consistency across synth / P&R / STA / sim
   - All isolation + level-shifter cells in place
7. **Documentation**
   - Pin list frozen; package / bond diagram matches pad ring; release notes,
     change log, waiver log complete — file-presence inventory *enforced by*
     `programs/tapeout_checklist_gen.py`.
8. **Release**
   - GDS stream-out (Calibre + KLayout), md5 checksum recorded, fab-specific
     deliverables bundled — *enforced by* `programs/signoff_audit.py` +
     `programs/foundry_handoff_package_check.py`.

## Workflow

The mechanical green/red verdict for every row above is produced by the
programs (run them first). The AI's residual job — the part that stays
**judgment**, not a program — is:

1. **Waiver risk assessment.** The waiver *schema/honesty* gate (id +
   reason + ticket present, approver not `ai`/`agent`/`self`) is the
   program `waiver_legitimacy_check.py` / `signoff_waiver_emit.py`. Whether
   a waiver's *mitigation is technically credible* and the *residual risk
   is acceptable for fab* is a substantive engineering judgment that no
   regex can make — assess it here.
2. **Route each red item** back to its owning sub-skill (`/sta-review`,
   `/drc-fix`, `/ir-drop-triage`, `/lvs-triage`, …) and decide ordering.
3. **Author the management-facing go/no-go narrative** that synthesizes
   the heterogeneous program JSON into one sign-off recommendation.
4. Block tape-out if any red without an accepted waiver.

## Output format

- `tapeout/checklist.md` — the table above with status + evidence links
- `tapeout/waivers.md` — every waiver with owner, rationale, risk assessment
- `tapeout/release.md` — GDS release note

## Technical basis

Standard pre-tapeout flows at commercial foundries (TSMC, Samsung, GF) require this category of checklist. Open reference: Efabless tapeout docs for shuttle runs (https://efabless.com/).

## Handoff

- Any red item routes back to its owning skill (`/sta-review`, `/drc-fix`, etc.)
- After full green → GDS release

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/tapeout-checklist/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
