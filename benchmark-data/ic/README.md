# `benchmark-data/ic/` — what is here, and what was removed

This directory is what the project points at when it says a cell converged. It therefore
carries **only runs whose own machine verdict is `PASS` or `PASS_WITH_WAIVERS`** — the same bar
`programs/benchmark_evidence_publish.py` already enforces at publish time
(`_CONVERGED = ("PASS", "PASS_WITH_WAIVERS")`; it raises otherwise).

## What is here

| path | verdict, from the cell's own `reports/audit/phase23_completion_audit.json` |
|---|---|
| `spm/v1.5.58_ihp-sg13g2` | `PASS_WITH_WAIVERS` |
| `spm/v1.5.65_sky130A` | `PASS_WITH_WAIVERS` |
| `spm/v1.5.66_gf180mcuD` | `PASS_WITH_WAIVERS` |
| `spm/input` | shared design input for the three cells above |
| `<ic>/input` for every removed IC | **kept deliberately** — see below |

**The design `input/` is kept for every removed IC.** It is the *specification*, not the
result: 440 files across the eight, from a 1-file stub to `opentitan_aes`'s 320. A benchmark
whose inputs are gone cannot be re-attempted by anyone, and the point of removing the failed
*results* is to make the remaining claims trustworthy — not to make the failures
un-investigable.

Each cell is verifiable end to end: L-docs → RTL → netlist → DEF → GDS + `GDS_MANIFEST`, with
DRC/LVS/STA reports and a formal evidence record. `spm/v1.5.58_ihp-sg13g2` additionally ships a
SymbiYosys reset-safety proof **with a negative control** under
`phase2/stage1/formal/reset_safety/`.

## What was removed, and why

Eight IC directories were pruned on 2026-07-26 — 2833 tracked files removed, 440 `input/` files kept. Each one's **own**
`reports/audit/phase23_completion_audit.json` reads `FAIL`:

| IC | audit verdict | orchestrator verdict | tracked files |
|---|---|---|---|
| `caravel_user_project` | FAIL | FAIL (halted phase3) | 249 |
| `edge_llm_accel` | FAIL | FAIL (halted phase3) | 326 |
| `edge_llm_matmul_accel` | FAIL | *(no orchestrator record)* | 242 |
| `ibex` | FAIL | FAIL (halted phase2) | 171 |
| `opentitan_aes` | FAIL | FAIL (halted phase2) | 511 |
| `sha256` | FAIL | FAIL (halted phase2) | 888 |
| `subservient` | FAIL | FAIL (halted phase2) | 369 |
| `u_hawaii_adc` | FAIL | **PASS_WITH_WAIVERS** | 517 |

They predate the convergence guard, which is why they were here at all. The publisher would
refuse every one of them today.

### Two things measured before removing, because neither is obvious

**The FAIL verdicts are old, but they are not wrong.** They were produced by plugin
**v0.119.62** — old enough that today's `flow_compliance_check.py` emits a different schema
(`overall`/`steps` rather than `verdict`/`failed_gate_count`). That raised the question of
whether they were stale accounting rather than real failures. They are not: for the five whose
run directories survive off-repo, the **run's own** `vibe_ic_one_shot.json` reads `FAIL` too, at
the source. The verdicts are old; the conclusions hold.

**Re-running the audit against a published cell does not work, and is not a valid check.** A
published cell is a curated subset of its run — `phase3/stage3` (raw PnR) and `steps/` are
deliberately not staged — so the checker reports missing dependencies. Confirmed by running it
against `spm/v1.5.65_sky130A`, a known `PASS_WITH_WAIVERS` cell: it returns `overall: FAIL`. The
audit can only be regenerated from the run directory.

### One exception worth naming

`u_hawaii_adc` is the only removed IC whose two verdict files **disagree**: the audit says
`FAIL`, the orchestrator says `PASS_WITH_WAIVERS` with all four phases accounted for
(`phase3`/`analog` are `SKIPPED`, not failed). The audit's `FAIL` rests on five
`missing_required_artifacts`, and **four of the five are present in the published tree** —
`extraction_coverage_report.{md,json}`, `phase1/generated_docs` (72 files),
`phase1/extraction_patterns.json`. Only `waivers.json` is genuinely absent.

The same contradiction exists in the surviving run directory, so it is not an artefact of
publishing. It is unresolved. It was removed with the rest on the owner's decision; if it is
later shown to have converged, it should come back **through the publisher**, not by reverting
this commit — the point of the bar is that the publisher decides.

## Where the removed data is

Nothing was deleted from disk, and nothing is lost from history.

- **Git history retains every file.** `git log --diff-filter=D -- benchmark-data/ic/<ic>` finds
  the removing commit; `git show <commit>^:<path>` reads any file back.
- **The run directories survive off-repo** for `ibex`, `opentitan_aes`, `sha256`, `subservient`,
  `u_hawaii_adc` and `spm` under a fleet path recorded in the removing commit message. Notably
  `subservient`'s run holds a complete PnR chain — `floorplan → placed → post_cts → post_hold →
  routed → filled` plus a 464 MB `chip_top.gds` — **which was never published**. That is real,
  recoverable evidence; recovering it is tracked in the issue linked from the removing commit,
  and needs the size-routing publisher (`fix(publish): layout artefacts route by SIZE`) because
  464 MB is far past GitHub's 100 MB single-file limit.
- `.gitignore` now ignores these paths so a local working copy cannot silently re-add them.

## If you want to add a cell here

Run it, converge it, and publish it with `programs/benchmark_evidence_publish.py`. The guard
that refuses a non-converged run is the reason this directory means anything.
