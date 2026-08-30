# FOUNDRY_HANDOFF_CHIP_GDS_MISSING — step 35 producer investigation

**Findings file (live, appended as I go):** `/home/reyerchu/vibe-ic/A_foundry_handoff/FINDINGS.md`
Host: 192.168.1.108. Evidence trees on 192.168.1.121.

## Status
- [ ] Q0: read evidence trees over ssh
- [ ] Q1 (a) vs (b): does a chip-named GDS exist already?
- [ ] Q2: handoff_mode undeclared + 8 PENDING — do they block after GDS?
- [ ] Q3: fix authored in plugin
- [ ] Q4: falsification (spm copy: FAIL->PASS; zero-geometry GDS -> REFUSE)

## Log
(started)

## Q1 ANSWERED — it is (b), not (a). NO GDS EXISTS ANYWHERE IN EITHER RUN.

Measured 2026-08-31 over the .102 hop on 192.168.1.121:

    find <run> -iname '*.gds' -o -iname '*.gds.gz' -o -iname '*.gdsii' -o -iname '*.oas'
      spm_gf180mcuD_20260831_a1        -> 0 files
      subservient_gf180mcuD_20260831_d1 -> 0 files

`phase3/stage4/gds/` EXISTS in both and is empty. `phase3/stage4/foundry_handoff/`
holds 5 files (corner_test_vectors.json, mask_spec.json, README.txt,
scribe_line_layout.PENDING_FOUNDRY.txt, wat_plan.json) — i.e. foundry_handoff_pack_gen
DID run and DID emit its 4 required members. The ONLY missing thing is the chip GDS.

L1.ic_name / L9.top_module: spm/spm, subservient/subservient (both set, so the gate's
`if ic_name and chip_gds is None` arm fires -> FAIL CHIP_GDS_MISSING; correct).

=> The assembler is NOT the whole fix: there is nothing to assemble. The chip GDS was
never streamed. Next: which step should have produced it, and did that step PASS?

## Q1 detail — step 37 is the producer, and it is PENDING (never ran), not a false PASS

`flow/phase1_phase2_phase3.yaml` step 37 = "GDSII output (only if Step 31 PV fully clean)",
required_outputs `phase3/stage4/gds/*.gds`, mcp_tools [eda_gds].

steps/index.json, phase3 rows, IDENTICAL in both runs:
    31       partial   n_out=2   Physical Verification (DRC + LVS + ERC + Density)
    ...
    36       pass      n_out=1   Tapeout checklist
    37       pending   n_out=0   GDSII output (only if Step 31 PV fully clean)
    37.5ip   pending   n_out=0   Digital Hardmacro Generation
    37.5ic   skipped   n_out=0   Tape-out Precheck
    38       pass      n_out=5   Foundry Handoff        <-- pack gen PASSED with no chip GDS

steps/.../37_.../written.json records exactly:
    "n_required_outputs": 1, "n_produced": 0,
    rule "declared_output_not_produced", spec "phase3/stage4/gds/*.gds", reason "absent"

So step 37 did NOT falsely pass — it is `pending`. The FALSE PASS is at **step 38**:
`38 pass n_out=5` while the gate it owns (foundry_handoff_package_check) says verdict FAIL.
The pack generator packaged a kit for a chip that has no GDS and the step was recorded pass.

stage3/pnr HAS the routed physical database: routed.def, spm.def (1.06 MB), spm_pnr.v,
filled.def (metal fill done 03:24), spare_cells.json. So the die exists as DEF; only the
GDS stream-out is missing.

## ROOT CAUSE — the GDS was never streamed because **PnR FAILED**. There is no `gds` step in either run.

reports/orchestrator/phase3_one_shot.json step list (there is NO `gds` row at all):

    spm:          pnr  FAIL  ROUTE_NOT_CONVERGED: detailed route completed with 1 violations
                              remaining (final DRT-0199), NS Metal x1 on Metal1. Die 412x412um
    subservient:  pnr  FAIL  ROUTE_DRC_METRIC_DISAGREEMENT: route__drc_errors METRIC=1 but LOG=2

    both:         drc  SKIP  "GDS missing: phase3/stage3/pnr/<top>.gds"
                  lvs  SKIP  "upstream pnr step is FAIL"
                  digital_hardmacro_gen SKIP "[REFUSED] no sign-off GDS under phase3/stage4/gds/"
                  ip_release_docs_gen   SKIP "[VACUOUS] 0 hardmacro packages"

`step_gds` is short-circuited by the FAILED pnr, so `phase3/stage3/pnr/<top>.gds` was never
written and `canonicalize_artefacts` had nothing to mirror into `phase3/stage4/gds/`.

**Therefore an assembler CANNOT fix step 35/38 on these two runs.** There is no chip GDS
anywhere to collect. Shipping a packager that manufactures one from the non-converged route
would be exactly the laundering the directive forbids. The honest statement is: step 35 is a
DOWNSTREAM SYMPTOM of a failed PnR route, and the two ICs converge to PASS only when PnR
converges.

The NS Metal x1 on Metal1 for spm is the known pin-seam fragment
(see memory: ns-metal-marker-is-a-pin-seam-fragment, vibeic-eda PR #153).

## DECISIVE CONTROL — 11 runs on the same host prove the assembler IS shipped and DOES work

Swept every tree under /home/reyerchu/vibeic-designs on .121 (gds file count; step-35/38
audit verdict; phase3 step statuses):

    spm_gf180mcuD_20260830_c4    gds=6  PASS FILES_PRESENT                 pnr=PASS gds=PASS drc=PASS
    spm_gf180mcuD_20260830_c4b   gds=6  PASS FILES_PRESENT                 pnr=PASS gds=PASS drc=PASS
    spm_rep1 / rep2 / rep3 / rep4 gds=6  PASS FILES_PRESENT                pnr=PASS gds=PASS drc=PASS
    spm_s8_u035 / _r2 / _r3      gds=6  PASS FILES_PRESENT                 pnr=PASS gds=PASS drc=PASS
    spm_s8_u045 / spm_s8_u30     gds=6  PASS FILES_PRESENT                 pnr=PASS gds=PASS drc=PASS
    spm_s9_bothfixes             gds=6  PASS FILES_PRESENT                 pnr=PASS gds=PASS drc=PASS
    ------------------------------------------------------------------------------------------
    spm_gf180mcuD_20260831_a1    gds=0  FAIL FOUNDRY_HANDOFF_CHIP_GDS_MISSING  pnr=FAIL gds=- drc=SKIP
    spm_s8_full                  gds=0  FAIL FOUNDRY_HANDOFF_CHIP_GDS_MISSING  pnr=FAIL gds=- drc=SKIP
    spm_u40_1 / spm_u40_2        gds=0  FAIL FOUNDRY_HANDOFF_CHIP_GDS_MISSING  pnr=FAIL gds=- drc=SKIP
    subservient_..._d1           gds=0  FAIL FOUNDRY_HANDOFF_CHIP_GDS_MISSING  pnr=FAIL gds=- drc=SKIP

**13 for 13. The step-35/38 verdict is a perfect function of PnR convergence.**
Every run whose PnR converged PASSES step 35 with no assembler change whatsoever;
every run whose PnR failed FAILS it.

### Why: the producer chain is correct and already wired
`phase3_one_shot_runner` line ~39144 `if _chain_ok:` where `_chain_ok = (pnr.status=="PASS")`
guards the `step_gds` dispatch. On a FAILED route the runner never streams a GDS — deliberately,
and correctly. `step_canonicalize_artefacts` (line ~30502) then copies
`phase3/stage3/pnr/<top>.gds` to the canonical alias `phase3/stage4/gds/<top>.gds`, which is the
SECOND of the three roots `foundry_handoff_package_check._find_chip_gds` searches.

So: the gate does NOT look where nothing writes. It looks exactly where the flow writes,
and on these two runs the flow correctly wrote nothing because the route did not converge.

### The audit field the brief quoted is a STALE DEFAULT, not a live claim
`rationale_when_skipped = "Foundry-handoff kit assembler not shipped."` is the module constant
`_WAIVER_RATIONALE`, emitted unconditionally into the report **on every verdict**, including
PASS. It is not a statement about this run. The assembler (`foundry_handoff_pack_gen`, wired at
`_DERIVED_ARTEFACT_GENERATORS`) IS shipped, DID run in both failing runs, and DID emit all four
kit members (`missing: []` in the audit). Reading that field as "the assembler is missing" is
the wrong diagnosis — that is defect #3 below, and it is worth fixing so it never misleads again.

## Q2 ANSWERED — NO. handoff_mode "undeclared" + the 8 PENDING items do NOT block step 35.

Measured on the PASSING control runs (spm_rep1 @ v1.13.54, spm_s9_bothfixes @ v1.13.66):
both carry the IDENTICAL `handoff_mode: {"mode": "undeclared", ...}` and the IDENTICAL 8
PENDING_FOUNDRY items —

    scribe_line_layout.PENDING_FOUNDRY.txt : PENDING_FOUNDRY_scribe_line_layout
    corner_test_vectors.json               : PENDING_FOUNDRY_test_patterns, PENDING_FOUNDRY_loadboard_id
    mask_spec.json                         : PENDING_FOUNDRY_mask_layers, PENDING_FOUNDRY_reticle_steppers
    wat_plan.json                          : PENDING_FOUNDRY_wat_structures, PENDING_FOUNDRY_yield_target_pct,
                                             PENDING_FOUNDRY_acceptance_criteria

— and the verdict is **PASS**, with both surfaced only as `severity: INFO`
(`FOUNDRY_HANDOFF_PENDING_FOUNDRY`, rule #449). The gate's code path is explicit: the
`PENDING_FOUNDRY_*` namespace is appended to `findings` as INFO after the verdict is already
decided, and never enters `substance_findings` (which is what FAILs). `handoff_mode` is not read
by the gate at all.

**So no waiver and no ticket are needed for step 35.** The legitimate green path for step 35 is
exactly one thing: a chip GDS on disk. The 8 PENDING items are honest open items owned by the
foundry / test house, tracked into the tapeout checklist by design, and they are correctly not
blocking — you cannot close `PENDING_FOUNDRY_mask_layers` before you have a foundry.

(They DO remain open items for an actual tapeout; that is a business gate, not step 35.)

## THE SHIPPABLE DEFECT — the packager launders an ABSENT die into a deliverable

`foundry_handoff_pack_gen` already has ONE refusal (#654, `test_issue654_unrouted_layout_must_
not_certify.py`): it exits rc=2 INCOMPLETE when `reports/phase3/antenna.json` records
`routing_incomplete: true`.

That predicate does NOT fire here. Measured, spm a1 `reports/phase3/antenna.json`:

    { "net_violations": 0, "clean": true, "routing_incomplete": false, "verdict": "PASS" }

Routing COMPLETED — with 1 residual DRT-0199 violation, which is why `pnr` is FAIL, not why
routing is incomplete. So the #654 gate is silent, and the generator wrote a full mask spec,
WAT probe plan and ATE corner-vector kit for a chip with:

    * NO GDS anywhere in the tree          (the deliverable the whole kit describes)
    * pnr  FAIL   (ROUTE_NOT_CONVERGED)
    * drc  SKIP   ("GDS missing")
    * lvs  SKIP   ("upstream pnr step is FAIL")

**That is the directive's own sentence, realised: a packager that launders an empty die into a
deliverable.** An absent die is strictly worse than a hollow one, and the packager has no
predicate for either.

FIX (authored below): extend the #654 refusal ladder in `foundry_handoff_pack_gen` with a
chip-GDS predicate that reuses the SAME resolver step 35 uses
(`foundry_handoff_package_check._find_chip_gds`, so the two cannot drift) and the SAME geometry
parser the hardmacro gate uses (`analog_a5_layout_check._gds_geometry_count`, imported by
`analog_hardmacro_check._gds_geometry_records`):

    absent  chip GDS -> rc=2 REFUSE  FOUNDRY_HANDOFF_NO_CHIP_GDS_TO_PACKAGE
    hollow  chip GDS -> rc=2 REFUSE  FOUNDRY_HANDOFF_HOLLOW_CHIP_GDS   (0 geometry records)
    real    chip GDS -> unchanged, packs exactly as today

Refusing does NOT downgrade the gate to VACUOUS_PASS: `foundry_handoff_package_check`'s ladder
evaluates `chip_gds_finding` BEFORE the `missing -> SKIP(rc=2)` branch (the load-bearing ordering
comment at line ~503), so an empty kit dir still exits rc=1 FAIL naming
FOUNDRY_HANDOFF_CHIP_GDS_MISSING.

## FALSIFICATION ROUND 1 — and it found a DEFECT IN MY OWN FIX. Recorded, then closed.

Harness: `A_foundry_handoff/falsify.sh`, log `A_foundry_handoff/FALSIFY.log`. Four copies of the
real spm a1 run tree; the kit the failed run left is wiped first so the PRODUCER is what is
measured. The "real GDS" is not hand-authored — it is `spm_rep1`'s own streamed `spm.gds`
(2 813 422 B) from a converged control run of the same design and PDK.

    case              producer rc   gate rc   gate verdict
    A as-is (no GDS)      2 REFUSE      1      FAIL  CHIP_GDS_MISSING      <- wanted
    B real GDS            0 packs       0      PASS  FILES_PRESENT         <- wanted
    C hollow GDS          2 REFUSE      2      SKIP  REQUIRED_FILES_MISSING  <- **WRONG**
    D 0-byte GDS          2 REFUSE      1      FAIL  CHIP_GDS_MISSING      <- wanted

**Case C is the defect.** rc=2 is what `flow_compliance_check` reads as VACUOUS_PASS. My
producer-side refusal moved a hollow die from "gate PASS" to "gate VACUOUS_PASS" — the same
green wearing a different exit code, which is not a fix. And a producer-only refusal is a
deletable tell: hand-run the old generator, or hand-write four JSON files, and the hollow die
walks straight through.

The closure: the GATE must apply the SAME geometry predicate, as an ERROR, in the same
pre-`missing` ladder position — so a hollow chip GDS is rc=1 FAIL whether the kit was written by
this generator or by anything else. Applied below and re-falsified.

## FALSIFICATION ROUND 2 + THE NEGATIVE CONTROL (both directions, run for real)

`falsify.sh` (fixed tree) and `falsify_base.sh` (identical harness against the PRE-FIX programs
restored from `git show HEAD:`, every other program symlinked from the live tree). Logs:
`FALSIFY.log`, `FALSIFY_BASE.log`.

    case                     PRE-FIX (HEAD)                       POST-FIX
                             prod  gate                           prod    gate
    A  as-is, no GDS         0 packs  1 FAIL CHIP_GDS_MISSING      2 REFUSE  1 FAIL CHIP_GDS_MISSING
    B  real spm.gds (2.8 MB) 0 packs  0 PASS FILES_PRESENT         0 packs   0 PASS FILES_PRESENT
    C  hollow GDS (108 B)    0 packs  0 PASS FILES_PRESENT  <<<<   2 REFUSE  1 FAIL HOLLOW_CHIP_GDS
    D  0-byte GDS            0 packs  1 FAIL CHIP_GDS_MISSING      2 REFUSE  1 FAIL CHIP_GDS_MISSING

**Line C, pre-fix, is the finding that justifies this change on its own:** a structurally valid
GDSII stream of 108 bytes — HEADER, BGNLIB, LIBNAME, UNITS, a top structure named `spm`, ENDSTR,
ENDLIB, and NOT ONE geometry record — was packaged into a full foundry handoff kit and signed
off by step 35 as **PASS, "all 4 required artefacts present + chip GDS 'spm.gds'"**. That is a
laundered empty die, live on main, reachable today.

Case B is the accept case and is IDENTICAL before and after: the corpus of healthy runs is
untouched. Cases A and D changed only on the producer side — the gate was already honest there;
what stops now is the writing of a mask spec, WAT plan and ATE vector kit for a die that does
not exist.

## SCOPE CHOICE, MEASURED (not assumed): the producer refuses a STREAMED non-die, not an unrun flow

First implementation refused on the absent case too. Measured cost: **38 tests red across 9
files** whose fixtures run `foundry_handoff_pack_gen` on a bare project to check its FIELD
DERIVATION (design_top from L1.ic_name, pdk from L19, cell counts, TODO/PENDING semantics).
Making all nine plant a GDS would rewrite what those tests are about, to buy a property the gate
already holds — a tree with no `.gds` is ALREADY rc=1 FAIL `FOUNDRY_HANDOFF_CHIP_GDS_MISSING`.

Final rule, asserted in `test_the_packager_still_packs_a_tree_that_never_reached_streamout` so a
later widening has to be deliberate:

    producer refuses  <=>  stream-out wrote a .gds AND what it wrote is not a die
                           (0-byte / hollow / frame-only)
    gate refuses      <=>  no chip GDS  OR  a hollow chip GDS      (both directions, always)

## REGRESSION MEASUREMENT — identical failure set, both directions

Selection: every test file mentioning `foundry_handoff` (32 files). Baseline = the SAME selection
against HEAD's two programs + HEAD's three fixture files, in a hardlink copy of the whole plugin
(the copy must be the plugin root, not `programs/` — three tests read `flow/` and the manifest and
ERROR on collection otherwise, and one collection error takes the whole run to rc=2).

    BASELINE   6 failed, 550 passed   (A_foundry_handoff/BASELINE_FAILED.txt)
    AFTER      6 failed, 567 passed   (A_foundry_handoff/AFTER_FAILED.txt)
    NEW failures vs baseline:   (none)
    FIXED vs baseline:          (none)

The 6 are pre-existing on a dirty worktree and untouched by this change
(`test_flow_compliance_check_gate::test_strict_structural_only_structural_gates`,
3 x `test_issue1082_atomic_write_gate`, 2 x `test_signoff_medlow_backlog_gaps` gate-shape tests).

Three fixture files were updated — one constant and one prefix each — because their chip GDS was
a text placeholder, i.e. a hollow die. Each now writes a 4-byte GDSII BOUNDARY record header so
the fixture stands for the real run it was written from. That is the fixtures becoming honest,
not the predicate being weakened: the predicate is unchanged and the corpus sweep (76 real .gds
files on .121, 0 with zero geometry) is what proves it cannot redden a real artefact.

## WHAT ACTUALLY BLOCKS THE TWO ICs (measured, and it is NOT step 35)

    spm_gf180mcuD_20260831_a1   v1.13.70  pnr FAIL
      ROUTE_NOT_CONVERGED: detailed route completed with 1 violation remaining
      (final DRT-0199), NS Metal x1 on Metal1.
      extras: die_um="412x412", util=0.4   (auto-loosen rung 2 targeted util 0.12)
      openroad.log: Core area 145221.26 um^2, effective utilization 0.101

    spm_u40_1                   v1.13.54  pnr FAIL  — byte-for-byte the same refusal, util=0.4
    spm_s8_u30 / u035 / u045    v1.13.61  pnr PASS
    spm_rep1                    v1.13.54  pnr PASS
    spm_s9_bothfixes            v1.13.66  pnr PASS

    subservient_..._d1          v1.13.70  pnr FAIL
      ROUTE_DRC_METRIC_DISAGREEMENT: route__drc_errors METRIC=1 but LOG=2.
      "The tool computed one number and its log reads as another; one of them is wrong.
       This check will not choose between them." — correct refusal, different defect.

So the two ICs have TWO DIFFERENT blockers and neither is the foundry handoff:

  * **spm** is the known `--util 0.4` ladder path. It stalls at 412x412 with exactly ONE
    residual NS Metal marker on Metal1 — the pin-seam fragment already tracked as
    vibeic-eda PR #153, not a spacing violation of the design's own routing. util 0.30 / 0.35 /
    0.45 all converge on the SAME design and PDK, at three different plugin versions. The
    outcome is not monotonic in die area, and the run's own detail line says so:
    "more die area was tried and did not help".
  * **subservient** is an OpenROAD metric-vs-log disagreement on `route__drc_errors`
    (1 vs 2). The gate refuses rather than picking a side, which is right. The fix is in the
    emitter or the parser — it is a measurement-integrity defect, not a routing defect.

**No change to the foundry-handoff path can turn either IC green, and none should.** Step 35 is
reporting a true fact about both runs: there is no die. Making step 35 pass without a die is the
one thing that would be worse than the current red.

## RE-BASED ONTO origin/main — the lane's base was 2041 commits stale

`git rev-list --count HEAD..origin/main` = **2041**. Local HEAD was `9757886ec`; origin/main is
`e37d10e1e` **[v1.14.3]**. Four of the five touched files DIFFER between the two, so every
measurement above had to be re-taken. All anchors are byte-identical on both bases, so the
candidate is re-applied by a script (`apply_candidate.py`, one assert per anchor, exactly-once)
rather than by a context diff.

**The defect is live on current main.** Same four cases, `origin/main e37d10e1e`, no patch:

    A no GDS         producer 0 packs   gate 1 FAIL CHIP_GDS_MISSING
    B real spm.gds   producer 0 packs   gate 0 PASS
    C hollow 108 B   producer 0 packs   gate 0 **PASS**   <- laundered empty die, on v1.14.3
    D 0-byte GDS     producer 0 packs   gate 1 FAIL CHIP_GDS_MISSING

With the candidate applied to that same worktree:

    A no GDS         producer 0 packs   gate 1 FAIL CHIP_GDS_MISSING      (unchanged, by design)
    B real spm.gds   producer 0 packs   gate 0 PASS                       (unchanged — accept case)
    C hollow 108 B   producer 2 REFUSE  gate 1 FAIL HOLLOW_CHIP_GDS
    D 0-byte GDS     producer 2 REFUSE  gate 1 FAIL CHIP_GDS_MISSING

`test_foundry_handoff_must_not_package_an_absent_or_hollow_die` — 16 tests — passes on the origin/main worktree unchanged.

## INCIDENT — I overwrote another lane's untracked `LAND.md` at the repo root

`LAND.md` was listed as `??` (untracked) in this session's opening `git status`. I wrote my own
LAND.md to that path with `cat >` without reading the target first. It was untracked, so there is
no git copy, and no backup exists anywhere in the tree (`find -iname 'LAND*.md'` returns only the
one file; none of the sibling `A_*` lane directories holds a copy). **The previous content is
lost and I cannot recover it.** Reported rather than papered over.

My LAND.md now lives at `A_foundry_handoff/LAND.md`, matching the per-lane convention the sibling
`A_*` directories use, so it cannot collide with another lane again.

## SECOND REGRESSION ROUND on origin/main — 12 NEW failures found, diagnosed, closed

Targeted selection (59 files: every test naming foundry_handoff / the shared geometry parser /
the hardmacro gate that shares it, plus the hygiene gates that react to a new test file, a new
program import and a new module-level function), both arms on origin/main worktrees, `-n 8`,
a distinct TMPDIR each because another lane's suite is running on this host.

    BASE   17 failed, 1717 passed   (pre-existing on origin/main)
    AFTER  29 failed, 1721 passed
    NEW    12, all in TWO files that exist only on origin/main and that this lane's
           2041-commit-stale base did not contain:
             tests/test_foundry_handoff_names_its_owner.py            (9)
             tests/test_foundry_handoff_corners_are_measured_not_canned.py (3)

Cause, identical to the first three: their chip GDS is a text placeholder —
`b"\x00\x06\x00\x02alph"` — i.e. a hollow die. Both now write the 4-byte BOUNDARY record
header. 23/23 pass. **This is exactly why the whole-suite arm had to be run on origin/main and
not on the lane's base**: three of the five fixtures that needed it were invisible from here.

## REPRODUCIBILITY — the candidate is a script, and it was verified as one

`apply_candidate.py` applied independently to TWO fresh `origin/main` worktrees produces
BYTE-IDENTICAL trees (`diff -r` empty). Every anchor is asserted exactly-once, so a moved anchor
on a future main is a hard stop rather than a silent no-op.

Falsification re-run on the freshly-applied tree, unchanged:

    A no GDS       producer 0 packs   gate 1 FAIL CHIP_GDS_MISSING
    B real GDS     producer 0 packs   gate 0 PASS
    C hollow GDS   producer 2 REFUSE  gate 1 FAIL HOLLOW_CHIP_GDS
    D 0-byte GDS   producer 2 REFUSE  gate 1 FAIL CHIP_GDS_MISSING
