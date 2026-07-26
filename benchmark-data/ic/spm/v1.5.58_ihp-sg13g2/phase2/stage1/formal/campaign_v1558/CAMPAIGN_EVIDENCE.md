# Formal evidence — the v1.5.58 CAMPAIGN's own run (recovered 2026-07-26)

These five files are the formal artefacts produced by **this cell's own
campaign**, at the path that cell's `reports/orchestrator/phase2_one_shot.json`
names as its `project`:

    /home/reyerchu/campaign_v1558/spm/converge_1.5.58_ihp-sg13g2
        phase2/stage1/formal/

They were never published. `reports/phase2/gates/formal_evidence.json` cited
`phase2/stage1/formal/formal_spm_formal.sby` and its `.sby.log` — the exact
basenames of two files in this directory — and for three published PDK cells
that citation resolved to nothing, because the repo-wide `*.log` ignore rule
dropped the transcript and nobody copied the rest. The rule now carries an
exception for `benchmark-data/**/formal/**/*.sby.log`, which is what makes the
transcript shippable at all.

**This is a recovery, not a re-run.** Nothing here was regenerated; the files
are byte-for-byte what the campaign wrote on 2026-07-23.

## Why a subdirectory rather than the cited path

They are deliberately NOT placed at `phase2/stage1/formal/` directly:

- this cell also ships `phase2/stage1/formal/reset_safety/`, which is a
  **regeneration** performed on 2026-07-26 (review finding F4, commit
  880d1a042). Campaign output and regenerated output must not be mixed in one
  directory where a reader cannot tell them apart;
- `formal/results.json` is the path `design_one_shot_runner` treats as the
  canonical "a proof ran here" manifest. Planting a recovered campaign file
  there would make a historical artefact look like current-run output.

`reports/phase2/gates/formal_evidence.json` cites these files at their real
path. The historic citation string is preserved there under `superseded`.

## What the DUT was

`spm.v` as read by both tasks is sha256
`e7feff2cbbad384aa5fa3011bf23ceecf0bd4e1f711bf1c7544f94cd2f995424` — **byte
identical to the RTL this deliverable ships** at `phase2/stage1/rtl/spm.v`, and
identical to the RTL shipped by the sky130A and gf180mcuD cells. Verified by
hashing both, 2026-07-26.

## What was actually proved — read this before reading `results.json`

The transcript is genuine and its PASS lines are real:

```
SBY [formal_spm_formal_safety] engine_0: Proved output 0 in frame 2.
SBY [formal_spm_formal_safety] engine_0: Property proved.  Time =     0.01 sec
SBY [formal_spm_formal_safety] summary: engine_0 (abc pdr) returned PASS
SBY [formal_spm_formal_safety] DONE (PASS, rc=0)
SBY [formal_spm_formal_bmc]    summary: engine_0 (abc bmc3) returned PASS
SBY [formal_spm_formal_bmc]    DONE (PASS, rc=0)
```

**But `results.json` overstates what that covers, and it is shipped unaltered
rather than corrected, because editing an artefact to read better than the run
it records is the defect this whole review is about.** Three measured caveats:

1. **`"property_count": 2, "proved": 2` is TWO TASKS over ONE assertion — not
   two properties.** `formal_spm.sv` in this directory contains exactly one
   assertion:

   ```verilog
   always @(posedge clk)
       if (f_past_valid && rst_active_q)
           a_reset_safety_1: assert (p == '0);
   ```

   `grep -c assert formal_spm.sv` = 1. Both SymbiYosys tasks (`safety`, mode
   prove, `abc pdr`, depth 20; `bmc`, mode bmc, `abc bmc3`, depth 12) elaborate
   that same single assertion.

2. **`"functional property proved BOUNDED via BMC to depth 12"` is wrong.**
   There is no functional or datapath property anywhere in the harness. That
   line — in `results.json` under `bounded_vs_unbounded`, and repeated in
   `formal_spm_report.md` — describes the `bmc` task, which checks the *same
   reset-safety assertion* to depth 12. **No arithmetic property of the
   multiplier was ever asserted, and no equivalence miter was ever run.**

3. **The two `-D` macros in the `.sby` are dead.** The task scripts read
   `-DSPM_SAFETY_ONLY` and `-DSPM_RESET_AT_T0` respectively, but neither
   identifier appears in `formal_spm.sv` or in `spm.v` (`grep -c` = 0 in both).
   Confirmed at the elaborated source: the two tasks' `src/formal_spm.sv` are
   the same blob, sha256
   `818326ec98b44318d369bd3fdaaee22c8a352611ade205b70efe3013825e548a`, and each
   contains exactly one assertion. The two tasks therefore differ only in
   **mode and depth**, not in what they check.

So the defensible statement is: *one reset-safety property, proved unbounded by
`abc pdr` and additionally checked bounded to depth 12 by `abc bmc3`, against
the exact RTL this deliverable ships.* Everything beyond that in `results.json`
is task bookkeeping mis-worded as property coverage.

## What this evidence does NOT have

**No negative control.** The campaign never ran one, so a reader cannot tell
from these files alone whether a 0.01 s "Property proved" is discriminating or
vacuous. The regenerated evidence in `../reset_safety/` DOES ship one —
deleting `p_reg <= 1'b0;` from the `if (rst)` branch makes the same property
return `FAIL`, rc=16 — and that control applies to the same property against
the same RTL blob. It is cited here because it is the only thing that makes
either PASS meaningful; it is not part of this campaign's own output.

## Reproducing

The `.sby` names `spm.v` in `[files]` as a bare basename. The RTL is
deliberately not duplicated into this directory, so from here:

```sh
cp ../../rtl/spm.v .          # sha256 e7feff2c… — verify before running
sby -f formal_spm_formal.sby
```

Engine availability is recorded in `results.json`: of the solvers probed, only
`abc` was present (`yices-smt2`, `z3`, `boolector`, `bitwuzla`, `btormc`,
`pono`, `avy`, `amulet`, `amulet2` all absent). `aigsmt none` in the `.sby` is
what lets the run proceed without them.
