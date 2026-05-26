---
name: synth-doctor
description: "Automatically diagnose and fix EDA tool failures. Parses Yosys synthesis and OpenROAD P&R logs, classifies errors into known patterns, and provides actionable fix commands. Triggers when: synthesis fails, P&R fails, 'why did synth fail', 'fix synthesis error', 'DRC violation', or any EDA tool error during Phase 2. Proactively suggest this when any Phase 2 tool returns non-zero exit code."
---

# Synth Doctor — EDA Error Classifier + Auto-Fix

Automatically diagnose EDA tool failures and provide actionable fix suggestions.

## Tools

### synth_doctor.py — Yosys Synthesis Errors
```bash
python3 tools/vibe_ic_tools/synth_doctor.py synth.log          # diagnosis
python3 tools/vibe_ic_tools/synth_doctor.py synth.log --fix     # with fix code
python3 tools/vibe_ic_tools/synth_doctor.py synth.log --json    # machine output
```

10 known patterns from 135-IC campaign:
| Pattern | Frequency | Auto-fixable |
|---------|:---------:|:------------:|
| UNPACKED_ARRAY | Common | Yes — flatten to packed |
| MULTI_DRIVER | Common | Yes — merge to single always_ff |
| RETURN_IN_FUNC | Occasional | Yes — use func name assignment |
| PAST_IN_COMB | Occasional | Yes — shadow register |
| AUTOMATIC_IN_FF | Occasional | Yes — module-level wire |
| LATCH_INFERENCE | Common | Yes — add default assignments |
| SYNTAX_ERROR | Varies | Manual review needed |
| MODULE_NOT_FOUND | Rare | Yes — add source file |
| WIDTH_MISMATCH | Common | Yes — explicit sizing |
| UNKNOWN | Rare | Manual review needed |

### pnr_doctor.py — OpenROAD P&R Errors
```bash
python3 tools/vibe_ic_tools/pnr_doctor.py pnr.log              # diagnosis
python3 tools/vibe_ic_tools/pnr_doctor.py pnr.log --drc drc.rpt # with DRC
```

10 known patterns:
| Pattern | Auto-fixable |
|---------|:------------:|
| GPL_DIVERGE | Skip (trivial design) |
| DRT_POWER_NET | Use global route only |
| FLOORPLAN_FAIL | Fix site name |
| DRC_SPACING | Reduce utilization |
| TIMING_FAIL | Relax clock period |
| NO_CLOCK | Add virtual clock |
| CONGESTION | Reduce density |

## Integration with flow-orchestrate

When flow-orchestrate detects a tool failure:
1. Run synth_doctor or pnr_doctor on the log
2. If auto-fixable: apply fix and retry
3. If manual: present diagnosis to user with suggested fix
4. Log all diagnoses to phase2_eda.log

## ⛔ ECO spare-cell preservation (mandatory)

> ⛔ **ECO spare-cell preservation:** cells/gates/pads carrying the `dont_touch` /
> `keep` attribute (or otherwise tagged spare/ECO) are RESERVED for a future
> metal-only ECO. NEVER delete, resize, re-purpose, or optimize them away. When
> fixing a synthesis/PnR failure, do **not** emit `opt_clean` / `clean -purge` /
> `remove_buffers` / area-recovery passes that act on keep-marked instances — a
> "remove unused logic" fix must explicitly exclude the spare pool. After any
> fix you apply, `spare_cell_preservation_check.py` MUST still PASS (spare set +
> keep attrs intact, 0 removed); if your fix drops a spare it is a regression —
> restore it and re-run the checker. See the `design-for-eco` skill.

## Compliance gate (mandatory — not optional)

After producing your output, save it to a file and run:

```bash
python3 ../../_shared/skill_compliance_check.py \
    --requirements ./compliance.yaml <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with the specific missing elements listed.
`compliance.yaml` (in this skill's directory) enumerates every required
element of your output — section headers, metadata fields, handoff lines,
tool invocations.

**Your task is not complete until the audit returns PASS.** If it fails,
re-read the listed missing elements, patch your output, and re-run the
audit. This guarantees that different agents executing this same SKILL.md
produce reports containing the same required elements, even when the prose
inside each element differs. Missing elements are the single largest
source of skill-execution non-determinism.
