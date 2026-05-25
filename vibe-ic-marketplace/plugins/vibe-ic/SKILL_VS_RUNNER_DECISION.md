# Skill vs Runner — AI Decision Guide (4-tier)

**Principle**: deterministic programs are the main line. Skills exist in 4 specific tiers to *complement* programs — **verify** their output, **judge** subjective quality, **debug** their failures, or handle **NL-only** tasks programs cannot replicate.

If a skill's content is *replicable* by deterministic code, it gets ported into a program and the skill is removed.

## Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│  Programs (main line) — *_one_shot_runner.py + gen + check + reg  │
└──────────────────────┬─────────────────────────────────────────────┘
                       │  PASS / FAIL / WAIVED
                       ↓
   ┌───────────────────┼─────────────────────────┐
   ↓                   ↓                         ↓
┌──────┐  ┌────────┐  ┌──────┐  ┌────────┐  ┌────────┐
│Verify│  │ Judge  │  │Debug │  │NL Prim │  │  ...   │
└──────┘  └────────┘  └──────┘  └────────┘  └────────┘
After     Subjective  When      NL-only
PASS      reading     FAIL      tasks
spot-     (PPA/STA    close-    (Phase 1
check     /tapeout)   loop      dialogue /
                                analog)
```

## Tier 1 — VERIFICATION (5 skills)

Run AFTER program PASS to spot-check the deterministic output for false-PASS / gameability / completeness gaps.

| Skill | Pairs with | Verifies |
|---|---|---|
| `phase2a-output-verify`         | phase2a_one_shot_runner | L docs schema + `__TODO__` cleanness + cross-doc consistency + anti-fabrication |
| `phase2b-rtl-verify`            | phase2b_one_shot_runner | RTL ↔ L9 contract + dead-state/dead-reg + Wave-34 device-BR + self-RX mask + reference TB scenario coverage |
| `phase3-backend-verify`         | phase3_one_shot_runner  | Synth quality + util sweet-spot + multi-corner STA + DRC violations + LVS clean + GDS sanity |
| `analog-output-verify`          | analog_one_shot_runner  | A1..A8 corner sweep + A6/A8 vs A4 deltas + LEF/lib completeness |
| `compliance-gate-spot-check`    | flow_compliance_check   | Random sample of PASS gates against gameable patterns; waiver rationale quality |

**AI MUST invoke verify skill after every program PASS, before reporting "PASS" to the user.**

## Tier 2 — JUDGMENT (6 skills)

Programs cannot determine subjective quality. AI invokes when output needs domain interpretation.

| Skill | Trigger |
|---|---|
| `ppa-predict`               | Synth/PnR done — is the area / power / timing acceptable? |
| `sta-review`                | Slack 0.1ns is "PASS" but is robustness enough for spread + Vt skew? |
| `rtl-review`                | RTL lint clean but is it readable / maintainable? |
| `spec-review`               | L docs complete but are design choices sound? |
| `tapeout-checklist`         | All PASS but who signs off? Subjective sign-off responsibility |
| `architecture-explore`      | Multiple valid topologies — which is best for the constraints? |

## Tier 3 — DEBUG (12 skills)

Programs FAIL → AI close-loops via debug skill. Triggered automatically when runner returns FAIL with a fix-related step name.

| Skill | Triggered by program |
|---|---|
| `rtl-repair`                  | step_reference_tb FAIL after ECO budget exhausted |
| `synth-doctor`                | step_yosys_synth or step_fpga_compile FAIL |
| `hw-debug-loop`               | step_md905_verify FAIL |
| `drc-fix`                     | DRC violation count >0 |
| `hold-fix`                    | STA hold violation |
| `lvs-triage`                  | LVS report mismatch |
| `ir-drop-triage`              | IR drop hot-spot |
| `yield-diagnostic`            | silicon FAIL post-tapeout |
| `eco-plan`                    | late-stage change impact analysis |
| `fpga-signaltap`              | on-board debug needs internal sig probe |
| `fpga-led-probe-allocation`   | debug pin fan-out |
| `fpga-hps-bridge`             | HPS-FPGA debug pathway |

## Tier 4 — NL PRIMARY (~25 skills)

No deterministic equivalent exists. AI invokes directly when user intent matches.

### Phase 1 NL entry
```
phase1, spec-validator, checkpoint-gate, community-backlog-submit
```

### Analog domain expertise (14)
```
analog-spec-extract, analog-topology-select, analog-netlist-gen,
analog-sizing, analog-sizing-loop, analog-layout, analog-extraction-resim,
analog-hardmacro-gen, analog-hw-testbench-gen, analog-hw-measure,
analog-hw-tuning-loop, analog-flow-orchestrate, ams-sim, mixed-signal-cosim
```

### Open-ended verification
```
hls-c2rtl, formal-verify, equivalence-check
```

### Specialised verification
```
protocol-timeline-assert, protocol-turnaround-audit, scope-pattern-attestation
```

### Cross-cutting
```
atpg-name-harmonize, regression-manage
```

## Decision tree

```
user intent
  │
  ├─ matches /vibe-ic-* command?
  │   ├─ YES → run runner (Bash)
  │   │      ↓
  │   │      read reports/<phase>_one_shot.json
  │   │      ↓
  │   │      verdict?
  │   │      ├─ PASS                → Tier 1 verify skill spot-check
  │   │      │                          ├─ verify clean → done
  │   │      │                          └─ verify finds issue → Tier 3 debug skill
  │   │      ├─ PASS_WITH_WAIVERS    → Tier 2 judgment skill review waivers
  │   │      └─ FAIL                 → Tier 3 debug skill close-loop, then re-run
  │   │
  │   └─ NO  → matches Tier 4 NL_PRIMARY skill?
  │            ├─ YES → invoke skill directly
  │            └─ NO  → ask user / general engineering judgement
```

## Forbidden patterns

❌ Running runner, getting PASS, claiming "all done" without invoking the paired verify skill
❌ Re-implementing in conversation what a runner does deterministically
❌ Invoking a doc-gen skill (datasheet-gen / frs-gen / etc.) when phase2a runner exists — that path is being migrated INTO phase2a, skill should be SKIP/FALLBACK only

## Anti-pattern: "skill content equals program logic"

If a skill's content is essentially a deterministic checklist that programs already execute, the skill is REDUNDANT and should be deleted (its logic ported into program). See ongoing migration in `MIGRATION_LOG.md`.

A skill belongs in Tier 1-4 only if its task involves at least one of:
- AI judgement (subjective)
- Cross-artifact correlation that programs miss
- NL parsing of free-text input
- Pattern recognition over heterogeneous failure modes

If none of those apply → port to program, delete skill.
