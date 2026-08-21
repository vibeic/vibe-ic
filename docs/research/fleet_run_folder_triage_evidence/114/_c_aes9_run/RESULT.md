# RESULT — _c_aes9_run (opentitan_aes × sky130A), Round 9

**Round scope (from the brief):** the number exists and the gate cannot see it. The fault
engine writes `coverage.yml` carrying `ratio: 5.073e-1` (50.73 % stuck-at), but
`dft_signoff_check` looks for `coverage.json` / `atpg_coverage.rpt`, finds neither, and reports
"no coverage evidence." Establish which side is wrong — the producer for not emitting what the
contract names, or the gate for naming files the producer never promised — and **fix THAT side**
(no decoy file). Then take a full `flow_compliance_check --strict` verdict and report the failure
**NAME SET**.

**Environment (verified, not inherited):**
- Plugin: fresh clone of `vibeic/vibe-ic`, `origin/main` @ `a7513461` = **v1.9.27**
  (`.claude-plugin/plugin.json` → `"version": "1.9.27"`). Round 8's PR2 (fmeda SV-`logic`-port
  parse) **landed** as this commit — confirmed below by FS1 moving VACUOUS-PASS → real FAIL.
  Working clone at `/home/reyerchu/_c_aes9_scratch/plugin`.
- `gh`: **2.96.0** at `~/.local/bin/gh` (authenticated as `reyerchu`). The OS `/usr/bin/gh` is
  the broken **2.4.0** — I used the `~/.local/bin` one for every `gh`/push operation.
- Tests run natively (pure-Python programs; no container needed for the parse/transcode/gate
  path). The `fault atpg` SAT engine (`ghcr.io/vibeic/vibeic-eda:0.2.51`) was **not** re-run —
  the 50.73 % measurement already exists on disk in round 5's `coverage.yml` (5.1 MB, full
  `faultPoints` + `sa0/sa1Covered/Uncovered` enumeration), and this round's defect is entirely
  in how that measurement reaches the gate, which is a native-Python producer/consumer concern.

---

## Headline

**The producer is the wrong side, and it is now fixed. → vibe-ic#610.**

The gate (`dft_signoff_check`) names `reports/phase2/dft/coverage.json` and
`phase2/stage2/dft/atpg_coverage.rpt`. Both are **declared in `fault_atpg_run.py`'s own module
docstring as its outputs** (lines 15–19: *"`<project>/dft/atpg_coverage.rpt` … `<project>/reports/dft/coverage.json` machine-readable"*). So the gate is faithful to the contract; it does **not**
name files the producer never promised. The producer is the side that failed to emit them
reliably:

- `fault atpg` writes `coverage.yml` (its **native** machine-readable metadata) the moment
  stuck-at is measured.
- The Vibe-IC producer transcodes that into the contract-named files, but wrote them only
  **(a)** *after* the second, long-running **transition (at-speed) fault pass** (`atpg_coverage.rpt`),
  and **(b)** only in the **CLI `main()`** (`coverage.json`).

So a completed stuck-at measurement sitting in `coverage.yml` is lost to the gate if the
transition pass is interrupted (wall-budget kill / OOM — exactly the DT1 at-speed timeout r8
root-caused) or if a caller drives `run_fault()` in-process. The gate then reports **"no coverage
evidence"** — *a measurement that exists reads identically to a tool that never ran.* That is the
campaign shape, verbatim.

I did **not** paper over it by writing a second file to be found, and I did **not** teach the
consumer to read `coverage.yml` directly — that raw file is freshness-unmanaged (round 5's is
correctly quarantined in `_aes5_stale/`), so a consumer reading it would resurrect stale numbers.
The producer transcodes into the freshness-managed `coverage.json`; the fix keeps that ownership.

---

## The fix (vibe-ic#610, producer side)

`run_fault()` now emits **both** contract-named artefacts in a **DURABLE STUCK-AT SNAPSHOT the
moment the stuck-at ratio is parsed** — before the transition pass and independent of the CLI
wrapper — then re-writes them with the complete result once transition resolves. A `json_out`
parameter lets any caller (and the CLI `--json`) target the canonical
`reports/phase2/dft/coverage.json`; `main()` keeps an idempotent safety-net write for the
early-return error stubs.

**Files:** `programs/fault_atpg_run.py` (+ helpers `_write_coverage_rpt`, `_write_coverage_json`,
`_assemble_report`) and `programs/tests/test_step11_coverage_json_durable_snapshot.py`. 2 files,
+307 / −70. Version-less (gatekeeper assigns at merge). English-only. chip-/PDK-AGNOSTIC — no
design or PDK literal; keyed only on the fixed two-fault-model ordering.

### Effect — demonstrated on the REAL `coverage.yml` (the actual 50.73 %)

Feeding round 5's `coverage.yml` (`ratio: 5.07315576076508e-1`, `faults_total 136490`) through the
producer's own parser + transcode, then running `dft_signoff_check.audit()`:

| | `stuck_at.measured_pct` | `stuck_at.reasons` (tool's own line) |
|---|---|---|
| **before** (coverage.yml only, no coverage.json — the interrupted-transition state) | `None` | *"no DFT/ATPG coverage evidence found: neither coverage.json … nor atpg_coverage.rpt … exists — Step 11 cannot pass without a real stuck-at coverage measurement"* |
| **after** (durable snapshot transcodes it) | `50.7316` | *"measured stuck-at coverage 50.73% < effective target 95.00% (written 95.00%, foundry floor 95.00%) — DFT/ATPG coverage below required foundry floor (untestable silicon)"* |

Both remain `FAIL`, but the character flips from **absence** (reads as "tool never ran") to a
**real below-floor number**. The producer's parser reads the same file identically both ways
(`coverage_pct 50.73, faults_total 136490, coverage_measured True`) — proving the number was
always there and only the emission was broken.

### Bidirectional negative control (flow-change-acceptance)

`test_step11_coverage_json_durable_snapshot.py` — three tests:
- `test_stuckat_snapshot_survives_transition_interruption` — stuck-at measured, then the
  transition helper **raises** (stands in for a wall-budget kill); asserts `coverage.json` +
  `atpg_coverage.rpt` exist with the real number. **RED on origin/main** — fails on the exact
  assertion `AssertionError: coverage.json is absent after the transition pass was interrupted`;
  **GREEN** here.
- `test_run_fault_writes_coverage_json_in_process` — the CLI-vs-library asymmetry.
- `test_json_out_honours_custom_destination` — mirrors the orchestrator's `--json` path.

**Regression sweep, 0 failures:** 78 (`test_fault_atpg_run` + mapped-netlist + medlow) → 1210
(full DFT/signoff/step11/atpg cluster, 14 skip) → 139 (chip-agnostic + source guards) → 993
(flow_compliance + matrix + step11 + capability-gap, 9 xfail). ~2400 tests total.

---

## Second deliverable — full `flow_compliance_check.py --strict` verdict + NAME SET

Run on the opentitan_aes design snapshot (`/home/reyerchu/_c_aes9_run/design`, copied read-only
from r5 seed) against **v1.9.27 + this fix**. JSON: `flow_compliance_current.json`.

```
Overall: FAIL  (strict=True)
counts: PASS=5  FAIL=3  MISSING=4  VACUOUS_PASS=2  WAIVED=4
        SKIPPED-CONDITION=21  DEFERRED-BY-UPSTREAM=24
```

**Failure NAME SET (not a count):**

| Bucket | Step NAMES |
|--------|-----------|
| **FAIL (3)** | **P0** Structural-RTL gates (umbrella; 207 of 243 checkers returned a verdict) · **11** DFT insertion (scan + ATPG + at-speed + BSDL) · **FS1** ISO-26262 FMEDA diagnostic-coverage |
| **MISSING (4)** | **7** Constraint setup (SDC + PVT matrix) · **8** SDC validation · **10** Pre-layout STA (multi-corner) · **DT1** Transition-delay-fault (at-speed LOC) ATPG |
| **VACUOUS_PASS (2)** | **D1** Phase-1 Doc Extraction · **14** Synthesis handoff gate (pre-PnR Yosys script + netlist audit) |

**What moved vs r8** (which reported, on v1.9.11+PR2, `FAIL=3 / VACUOUS-PASS=3`): **FS1 is now a
real FAIL, VACUOUS-PASS dropped 3→2** — because r8's PR2 (SV `output logic [W:0]` port parse)
**landed as v1.9.27**, so the FMEDA gate now sees the SEC-DED ECC decoder and grades it instead
of vacuously skipping. The r8 prediction is confirmed on main.

**Step 11 on THIS snapshot is FAIL, and my fix does not change that here** — honestly. The
snapshot's current netlist is technology-**generic** (`dffunmap; abc -g cmos2`), so ATPG refuses
with `unsupported pdk: unmapped` and genuinely measures nothing (`coverage.unmeasured.json`,
`dft_atpg_not_run.json`). There is no live measurement on this snapshot for the durable snapshot
to preserve; the 50.73 % is round 5's, measured on a sky130-mapped netlist that is not in this
tree and correctly quarantined in `_aes5_stale/`. My fix bites on the **measuring** path (mapped
netlist + interrupted transition), which is the path the demonstration above exercises.

---

## Not duplicated (per brief)

Raw-vs-TESTABLE coverage (#603 — untestable I/O-frame faults dragging the raw number below floor)
is owned on the caravel cell. **It does not apply here:** opentitan_aes is a bare core with no pad
ring (`dft_signoff.json bsdl: SKIP "bare core / no pad ring"`), so raw ≈ testable-logic coverage.
The 50.73 % is **pattern-count-limited** (default `--tv-count 100` on a 2922-flop masked AES
datapath), not an untestable-frame artefact. I did **not** build any AU-fault exclusion here.

---

## Verdict per phase (this round's two targets)

| Target | Verdict | Evidence |
|--------|---------|----------|
| **Producer/consumer mismatch — which side, and fix it** | **DONE** — producer side, fixed in #610 | Producer docstring declares `coverage.json`/`atpg_coverage.rpt` → gate is faithful → producer must emit; `run_fault()` now emits a durable stuck-at snapshot pre-transition. Before/after: `measured_pct None → 50.7316`. |
| **Full `flow_compliance_check --strict` verdict + NAME SET** | **DONE** — Overall FAIL | NAME SET table above; `flow_compliance_current.json`. FS1 VACUOUS→FAIL confirms PR2 landed. |

## What I filed / pushed
- **vibe-ic#610** `fix/dft-step11-coverage-json-durable-snapshot` — the producer fix + negative
  control. Pushed to `vibeic/vibe-ic`, PR open, version-less. **Not merged** (I am not the
  gatekeeper). Pre-push discipline honoured: `git fetch origin` + `git diff --stat origin/main
  HEAD` = exactly the 2 intended files, HEAD in sync with origin/main, no stale-base collateral.

## Program-first distillation (next blind run recovers this with no agent)
A stuck-at coverage measurement now reaches `dft_signoff_check` in the contract-named
`coverage.json` **the moment it is measured**, independent of whether the at-speed transition
pass finishes and independent of whether the producer is driven by CLI or in-process. The
"measurement exists in coverage.yml but the gate says nothing was measured" failure mode is
closed deterministically by the producer, and the negative-control test keeps origin/main from
regressing it.

## What remains (out of this round's scope, honestly)
- Step 11 → PASS still needs real ATPG coverage ≥ 95 % (more test patterns) on a **mapped**
  netlist; the runner emits a generic netlist for this cell, so ATPG cannot measure on this
  snapshot at all — a separate producer-plumbing item (mapped-sibling resolution), not this fix.
- DT1 (transition ATPG) is still MISSING — its at-speed budget/timeout bookkeeping is r8's #608
  territory, not re-litigated here.
- P0 umbrella (36 of 243 checkers NOT INVOKED), Steps 7/8/10 MISSING (pre-layout signoff, #606),
  D1/Step-14 VACUOUS — all pre-existing, untouched.
- I landed nothing (not the gatekeeper).
