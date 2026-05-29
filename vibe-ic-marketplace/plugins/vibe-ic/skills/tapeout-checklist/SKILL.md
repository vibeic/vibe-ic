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
python3 plugins/vibe-ic-d/programs/flow_compliance_check.py \
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
```

**Refuse to claim tape-out-ready if any of these returns non-zero or
FAIL.** Only after ALL pass can the narrative proceed.

## ⛔ PHASE 2+3 SOLE ACCEPTANCE CRITERION (READ FIRST)

This skill produces `tapeout_signoff_check.json`. **That gate alone is NOT sufficient to claim Phase 2+3 complete.**

The **ONLY** valid completion signal for the full design flow is:

```
python3 vibe-ic-d/programs/flow_compliance_check.py <project_dir> --strict
```

returning ONE of three verdict states:

- `Overall: PASS` — every canonical step actually executed. Tape-out ready.
- `Overall: PASS_WITH_WAIVERS` — structurally complete BUT N step(s) DEFERRED. **NOT tape-out ready in the foundry sense.** Foundry-side sign-off must close every waiver on the commercial PDK + commercial sign-off deck before fab takes the GDS.
- `Overall: FAIL` — incomplete.

`flow_compliance_check` covers what `tapeout_signoff_check` does NOT: SPEF parasitic extraction, post-route MCMM STA, IR/EM/antenna/SI sign-off, post-layout gate-sim, SPICE correlation, ECO, metal fill, FPGA final recompile, and analog A1-A8. Skipping these and claiming "tapeout signoff PASS" because the 4-item gate is green is a process violation.

**Waiver semantics**: a waiver is `DEFERRED open work` not `PASS`. When summarising a `PASS_WITH_WAIVERS` run to a user, never say "all N steps PASS". Always disambiguate `executed PASS` from `deferred via waiver`.

Before declaring tape-out ready, **always** end with:

```
python3 vibe-ic-d/programs/flow_compliance_check.py <project_dir> --strict 2>&1 | tail -10
```

and paste the output into `FINAL_REPORT.md`. If `PASS_WITH_WAIVERS`, also enumerate every waiver (id, reason, ticket) inline in the report — do not bury them in the JSON file.

## When to use

- Final 1–2 weeks before GDS release
- After the final ECO
- As a nightly regression item for any design in the "tapeout window"

## Checklist categories (must all be green or waived)

1. **Functional**
   - RTL regression 100% pass
   - Coverage ≥ target (code, functional, assertion)
   - Formal properties all proven or bounded
   - LEC RTL↔netlist clean
2. **Timing**
   - STA setup/hold/recovery/removal clean across all MCMM corners
   - Min-pulse-width, max-transition, max-capacitance clean
3. **Power integrity**
   - Static IR-drop < budget (typical 5–10% Vdd)
   - Dynamic IR-drop clean
   - EM current density < library limit
4. **Physical**
   - DRC 0 errors (or waivers signed)
   - LVS clean
   - Antenna DRC clean
   - Density rules clean (min/max metal density)
   - ERC (electrical rule check) clean
5. **Test** (DFT data missing = FAIL, not SKIP — v0.100 K3)
   - Scan ATPG coverage ≥ 99% stuck-at (if no DFT report exists, this category is FAIL)
   - MBIST integrated and simulated
   - Boundary scan BSDL file generated
6. **Power intent**
   - UPF consistency across synth / P&R / STA / sim
   - All isolation + level-shifter cells in place
7. **Documentation**
   - Pin list frozen
   - Package / bond diagram matches pad ring
   - Release notes, change log, and waiver log complete
8. **Release**
   - GDS stream-out tested in both Calibre and KLayout
   - Md5 checksum recorded
   - Fab-specific deliverables (IP blocks, fill, cell list) bundled

## Workflow

1. Pull latest results for every item
2. Red/yellow/green each row with evidence link
3. Block tape-out if any red without waiver
4. Produce sign-off packet for management review

## Output format

- `tapeout/checklist.md` — the table above with status + evidence links
- `tapeout/waivers.md` — every waiver with owner, rationale, risk assessment
- `tapeout/release.md` — GDS release note

## Technical basis

Standard pre-tapeout flows at commercial foundries (TSMC, Samsung, GF) require this category of checklist. Open reference: Efabless tapeout docs for shuttle runs (https://efabless.com/).

## Handoff

- Any red item routes back to its owning skill (`/sta-review`, `/drc-fix`, etc.)
- After full green → GDS release

## Compliance gate (vibe-ic-d - mandatory when deterministic edition is installed)

If you have the `vibe-ic-d` plugin installed alongside `vibe-ic`,
after producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/tapeout-checklist/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding vibe-ic-d skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
