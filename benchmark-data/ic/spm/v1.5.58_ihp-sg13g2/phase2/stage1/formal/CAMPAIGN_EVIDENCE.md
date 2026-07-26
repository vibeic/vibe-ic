# Formal evidence — the v1.5.58 CAMPAIGN's own run (recovered 2026-07-26)

The six files in **this directory** (`phase2/stage1/formal/`, excluding the
`reset_safety/` subdirectory) are the formal artefacts produced by **this cell's
own campaign**, at the path that cell's `reports/orchestrator/phase2_one_shot.json`
names as its `project`:

    /home/reyerchu/campaign_v1558/spm/converge_1.5.58_ihp-sg13g2
        phase2/stage1/formal/

    formal_spm_formal.sby        the SymbiYosys task
    formal_spm_formal.sby.log    the transcript
    formal_spm.sv                the harness
    spm.v                        the DUT as the tasks read it
    results.json                 the runner's machine-readable verdict
    formal_spm_report.md         the runner's human-readable report

They were never published. `reports/phase2/gates/formal_evidence.json` cited the
task file and its transcript by these exact names, and for three published PDK
cells that citation resolved to nothing, because the repo-wide `*.log` ignore
rule dropped the transcript and nobody copied the rest. The rule now carries an
exception for `benchmark-data/**/formal/**/*.sby.log`, which is what makes the
transcript shippable at all.

**This is a recovery, not a re-run.** Nothing here was regenerated; the files are
byte-for-byte what the campaign wrote on 2026-07-23.

They sit at exactly the path that was cited, so the citation now resolves. The
SEPARATE, later evidence set lives one level down in `reset_safety/` and is
labelled there: it is a **regeneration** performed on 2026-07-26 (review finding
F4, commit 880d1a042), not campaign output. Campaign output and regenerated
output must not be mistaken for one another; that is why they are in different
places and why both are described here.

## What the DUT was

`spm.v` in this directory is sha256
`e7feff2cbbad384aa5fa3011bf23ceecf0bd4e1f711bf1c7544f94cd2f995424` — **byte
identical to the RTL this deliverable ships** at `phase2/stage1/rtl/spm.v`, and
identical to the RTL shipped by the sky130A and gf180mcuD cells. Verified by
hashing all of them, 2026-07-26. It is present here as well as under `rtl/`
because the task file names it in its `[files]` section as a bare basename, so
the proof is only re-runnable from this directory if it is here.

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
rather than corrected, because editing an artefact to read better than the run it
records is the defect this whole review is about.** Three measured caveats:

1. **`"property_count": 2, "proved": 2` is TWO TASKS over ONE assertion — not two
   properties.** `formal_spm.sv` in this directory contains exactly one
   assertion:

   ```verilog
   always @(posedge clk)
       if (f_past_valid && rst_active_q)
           a_reset_safety_1: assert (p == '0);
   ```

   `grep -c assert formal_spm.sv` = 1. Both SymbiYosys tasks (`safety`, mode
   prove, `abc pdr`, depth 20; `bmc`, mode bmc, `abc bmc3`, depth 12) elaborate
   that same single assertion.

2. **`"functional property proved BOUNDED via BMC to depth 12"` is wrong.** There
   is no functional or datapath property anywhere in the harness. That line — in
   `results.json` under `bounded_vs_unbounded`, and repeated in
   `formal_spm_report.md` — describes the `bmc` task, which checks the *same
   reset-safety assertion* to depth 12. **No arithmetic property of the
   multiplier was ever asserted, and no equivalence miter was ever run.**

3. **The two `-D` macros in the task file are dead.** The task scripts read
   `-DSPM_SAFETY_ONLY` and `-DSPM_RESET_AT_T0` respectively, but neither
   identifier appears in `formal_spm.sv` or in `spm.v` (`grep -c` = 0 in both).
   Confirmed at the elaborated source: the two tasks' `src/formal_spm.sv` are the
   same blob, sha256
   `818326ec98b44318d369bd3fdaaee22c8a352611ade205b70efe3013825e548a`, and each
   contains exactly one assertion. The two tasks therefore differ only in **mode
   and depth**, not in what they check.

So the defensible statement is: *one reset-safety property, proved unbounded by
`abc pdr` and additionally checked bounded to depth 12 by `abc bmc3`, against the
exact RTL this deliverable ships.* Everything beyond that in `results.json` is
task bookkeeping mis-worded as property coverage.

## What this evidence does NOT have

**No negative control.** The campaign never ran one, so a reader cannot tell from
these files alone whether a 0.01 s "Property proved" is discriminating or
vacuous. The regenerated evidence in `reset_safety/` DOES ship one — deleting
`p_reg <= 1'b0;` from the `if (rst)` branch makes the same property return
`FAIL`, rc=16 — and that control applies to the same property against the same
RTL blob. It is cited here because it is the only thing that makes either PASS
meaningful; it is not part of this campaign's own output.

## Reproducing

Everything the task file names is in this directory, so from here:

```sh
sby -f formal_spm_formal.sby
```

Engine availability is recorded in `results.json`: of the solvers probed, only
`abc` was present (`yices-smt2`, `z3`, `boolector`, `bitwuzla`, `btormc`, `pono`,
`avy`, `amulet`, `amulet2` all absent). The `aigsmt none` option in the task file
is what lets the run proceed without them.

## Gate status

With these files restored, `formal_proof_evidence_check` run against this
deliverable returns:

```
"findings": ["PROOF_CHAIN_OK: all_proved substantiated by an elaboratable task + SymbiYosys PASS transcript"],
"verdict": "PASS"
```

Read that for exactly what it says: the proof CHAIN is intact — task file,
transcript and manifest agree and all resolve. It is **not** a statement that the
multiplier is functionally correct. See the three caveats above for what the
chain actually covers.
