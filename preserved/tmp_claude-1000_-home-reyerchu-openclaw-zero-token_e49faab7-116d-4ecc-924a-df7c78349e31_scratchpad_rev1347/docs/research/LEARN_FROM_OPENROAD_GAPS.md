# What OpenROAD / ORFS enforces that we do not

Read at the versions we actually run:

| thing | version read |
|---|---|
| `openroad` binary in `vibeic-eda` | `26Q3-1392-g3bf15a279a` (`/foss/tools/openroad/SOURCES` -> OpenROAD `4c26918f`) |
| ORFS pinned by the image | `/foss/tools/openroad/ORFS_COMMIT` = `c9c22caf` (2026-06-20) |
| vibe-ic | worktree at `origin/main` `2b93d872` (v1.10.81) |

ORFS flow scripts are NOT installed in the image (only the binary is), so the
ORFS sources were read from a clone pinned to the commit the image records.
Command semantics (`check_placement`, `check_antennas`, `design_is_routed`)
were read out of the INSTALLED binary with `info body`, not from the web.

Class key: **DEAD DIE** > **FAILS-A-CORNER** > **SHIPS-LATE** > **COSMETIC**.

---

## 1. The taped-out netlist's equivalence proof is produced and then not enforced — DEAD DIE

**WHAT THEY CHECK** — `flow/scripts/cts.tcl:60-80`: after `repair_timing`
mutates the netlist inside CTS, ORFS runs `run_lec_test` and the stage DIES on
a difference: `flow/scripts/lec_check.tcl:60` `error "Repair timing output
failed lec test"`. A logic-changing repair cannot leave the CTS stage.

**WHAT WE CHECK** — `programs/lec_post_layout_check.py` exists, is correct, and
is stronger than theirs (a VACUOUS/UNPROVEN proof is a FAIL, not a pass).
`programs/phase3_one_shot_runner.py:31359-31386` emits
`reports/phase3/lec_post_layout.json`. The only consumer that GATES on it is
`signoff_ladder_run.check_tier_lec_post` (`release_gating=True`,
`programs/signoff_ladder_run.py:1358-1382, 1923`) — and
`grep -c signoff_ladder_run flow/phase1_phase2_phase3.yaml` = **0**.
`programs/signoff_audit.py:549` states it in the repo's own words: *"only
signoff_ladder_run.py, which is itself never invoked"*. Step 36's executed gate
is `tapeout_signoff_check` = `signoff_audit --mode tapeout`, whose pillars are
GDS / netlist / timing / DRC / LVS + an SI blocking condition
(`programs/signoff_audit.py:12-46`) — post-layout LEC is not among them.
`programs/tapeout_checklist_gen.py:85` classes the row `"advisory"`, and that
program's verdict is `READY_FOR_TAPEOUT iff blockers_present ==
blockers_total` over file PRESENCE (`tapeout_checklist_gen.py:266-269`).

**THE GAP** — a CTS buffer insertion, a hold-fix, a resizer swap or a bad spare
patch that changes the ROUTED logic passes every gate the flow executes. The
chip is manufactured implementing something other than the netlist Step 13
proved. Silicon is functionally wrong and no report says so.

**Owner** — `signoff_audit.py` (add the pillar) or wire `signoff_ladder_run
--mode tapeout` into step 36. The checker itself already exists; only the
wiring is missing.

---

## 2. The placer's own legality verdict is caught and demoted to a WARN — DEAD DIE

**WHAT THEY CHECK** — `check_placement -verbose` after every placement-mutating
operation: `detail_place.tcl:31`, `cts.tcl:82`, `global_route.tcl:86` and `:106`
(after the detailed placement that `repair_timing` / `repair_antennas` run
internally), `fillcell.tcl:10` (immediately after `filler_placement`). The
command ABORTS — from the installed binary, `info body check_placement`:

> Returns the violation count. Without `-no_abort` a non-zero count raises
> DPL-33 instead of returning, so an illegal placement can never be mistaken
> for a legal one by a caller that ignores the result.

**WHAT WE CHECK** — `programs/placement_legality_check.py` (step 17's gate)
parses `placed.def` and asserts: COMPONENTS > 0, declared count == parsed count,
every instance carries PLACED/FIXED/COVER, and a density in (0,100] *only when
derivable* (otherwise "informational", not a failure). It tests a DEF STATUS
FIELD, not legality: nothing there detects off-site/off-row placement, overlap,
illegal orientation or out-of-core instances. The runner does call the real
command, twice, and swallows it:
`phase3_one_shot_runner.py:14618-14622` (`SPARE_CHECK_PLACEMENT_WARN`) and
`:16969-16973` (`ECO_CHECK_PLACEMENT_WARN`), both commented *"keeps the flow
moving"*. `grep -rn "SPARE_CHECK_PLACEMENT\|ECO_CHECK_PLACEMENT"` outside the
runner: one unit-test string, no gate. Our step-34 fill
(`phase3_one_shot_runner.py:36473-36530`) runs `filler_placement` and does NOT
follow it with `check_placement` — contrast `fillcell.tcl:10` — and step 34 runs
AFTER step 31 physical verification. Searched and found none:
`placement_legality_check`, `def_stage_progression_check`, `erc_density_check`,
`offgrid_drc_classify_check`, `decap_route_short_guard`, `gate_is_wired_check`.

**THE GAP** — a user ships a layout the placer itself declared illegal. An
off-row cell's supply rails do not abut the PDN follow-pins, so the cell is
unpowered; overlapping abutted cells short. The only downstream witness is the
sign-off DRC count — and our own `offgrid_drc_classify_check.py:4-12` records
what that looks like when it happens: **61,324 violations on the first design
to reach GDS, ~74% of them OFFGRID-class**, i.e. discovered at the end of the
flow instead of at the instruction that caused it.

**Owner** — `placement_legality_check.py` must consume the tool's verdict
(exists, wrong input); the two `catch` sites must escalate rather than print;
the fill stage needs the post-fill assertion.

---

## 3. Nothing ever asks the timing engine whether the constraints match the netlist — FAILS-A-CORNER

**WHAT THEY CHECK** — `flow/scripts/floorplan.tcl:37-39` runs OpenSTA
`check_setup` on the linked post-synthesis netlist + SDC, before any placement:
unclocked registers, unconstrained endpoints, ports with no input/output delay,
generated-clock problems.

**WHAT WE CHECK** — nothing. `grep -rn "check_setup"` over `programs/ flow/
mcp-eda/ skills/`: **0 hits**; `all_registers`: 1 hit, in an ATPG program;
`get_clocks`: 1 hit, in an SDC exception correlator. Step 8 validates the SDC as
TEXT against the L8 doc and the RTL (`sdc_syntax_check`, `sdc_validator_check`,
`derived_clock_sdc_required_check`) — never SDC ∘ netlist.

**THE GAP** — a `create_clock` whose object list matches nothing after synthesis
or DFT renaming leaves the design unconstrained. Synthesis, CTS and hold fixing
all "succeed" on an empty path set. The earliest witness is step 23, where
`sta_corner_record_completeness_check.py:455-470` drops the non-negative
summaries of a no-path section as vacuous — a late catch, and only if the corner
record shows it. The chip that gets built is timed against nothing and fails at
frequency.

Honest note: **ORFS does not gate this either** — `check_setup` is printed, not
enforced. The gap is "they look early and cheaply, we never look".

**Owner** — no program exists. Nearest neighbours are `sdc_validator_check` and
`sta_signoff_rigor_check`.

---

## 4. 61 of 62 gate-carrying steps re-parse prose instead of emitting a measurement — SHIPS-LATE (and it is the substrate under every other number)

**WHAT THEY CHECK** — every ORFS stage runs through one 21-line wrapper with
`-metrics "$LOG_DIR/$1.json"` (`flow/scripts/flow.sh:15`), and each stage script
names its namespace on line 1 (`detail_route.tcl:1`:
`utl::set_metrics_stage "detailedroute__{}"`). `util/genMetrics.py:279-289` is a
glob-and-merge with no parser, and `util/checkMetadata.py` compares NAMED
quantities against the design's rules file. The number that is gated is the
number the tool computed.

**WHAT WE CHECK** — `programs/step_metrics.py` is an explicit adoption of this
(its docstring cites `flow.sh:15` and `detail_route.tcl:1`), and states its own
coverage: *"It wires ONE gate (`coverage_metric_check`) as a worked example.
The other 61 gate-carrying steps DO NOT emit yet."* `grep -n '\-metrics '` in
`phase3_one_shot_runner.py` and `mcp-eda/`: no call site — we never ask OpenROAD
for its metrics JSON, though every stage we drive can write one.

**THE GAP** — every physical-design quantity we gate on is a regex over
human-readable text, so a tool wording change silently changes what the gate
measures, and no run-to-run QoR delta exists. Our own
`sta_corner_record_completeness_check.py:290-292` documents living with the
exposure ("so an OpenSTA wording change degrades to ... (loud) rather than to a
silent clean pass").

**Owner** — `step_metrics.py` exists; the emit calls do not.

---

## 5. An empty gate corpus must fail, and ours passes — SHIPS-LATE / false-clean

**WHAT THEY CHECK** — `util/checkMetadata.py:49-51`:

```python
if len(rules) == 0:
    print("No rules")
    sys.exit(1)
```

and `:94-96` — a rule whose metric is absent from `metadata.json` is
`[ERROR] Value not found for {field}` + `sys.exit(1)`. Nothing to check is a
failure, not a pass. (This also catches a SKIPped stage: `SKIP_DETAILED_ROUTE=1`
produces a GDS and `make finish` succeeds, but the missing
`detailedroute__route__drc_errors` fails `make metadata-check`.)

**WHAT WE CHECK** — the flow's own idiom is the opposite: `optional_program_exit_zero`
+ `condition_files_exist`, i.e. no input -> no check -> step PASSES. The yaml
documents the resulting failure at step 8
(`flow/phase1_phase2_phase3.yaml:1363-1377`): a BLOCKING gate silently disarmed
since v1.6.18 because a wrong positional made the program read a directory that
never exists, so it reported `[SKIP] no .sdc files` and exit 0 on EVERY project.
The three-value contract (rc 2 = NOT CHECKED) is the right fix and is partially
adopted.

**THE GAP** — a project missing the artefact a gate consumes passes that step,
and "checked and clean" is indistinguishable from "never asked".

**Owner** — `flow_compliance_check.py` (the `condition_files_exist` semantics),
not any single checker.

---

## Upstream things that are WORSE than ours — adopt selectively

1. **DRC and LVS are not in the default flow.** `make all` =
   `check-yosys check-openroad synth floorplan place cts route finish`
   (`flow/Makefile:770`). `drc` and `lvs` are separate opt-in targets. No CI
   invocation of them exists in the repo (`grep -rn "make drc\|make lvs"` over
   `.github/`, `jenkins/`, `flow/test/`: nothing). ORFS's CI is an external
   shared Jenkins library (`pipelineORFS`), so whether the hosted CI runs them
   is **NOT DETERMINED** from the repo.
2. **No platform sets `CORNERS`.** `grep -rn CORNERS flow/platforms/*/config.mk`:
   nothing, in all 7 platforms. `flow/scripts/read_liberty.tcl` then takes the
   `else` branch and loads a single un-named liberty set. Every ORFS timing
   number, including the CI-gated ones, is single-corner, and no metric records
   the corner count. **No platform ships a `derate.tcl`** either
   (`ls flow/platforms/*/derate.tcl`: none), so there is no OCV derating
   anywhere. We gate this from four directions: `corner_coverage_audit`,
   `sta_corner_record_completeness_check`, `post_route_signoff_corner_check`,
   `hold_corner_coverage_check`, plus `sta_signoff_rigor_check` (OCV derate +
   recovery/removal + min-pulse-width required).
3. **The thresholds are derived from the design's own previous run.**
   `util/genRuleFile.py` generates `rules-<variant>.json` from the reference
   run's metadata with fixed padding — 5% of the clock period on WNS, 20% on
   TNS, 15% on area, **30% on antenna violating nets**, `<=` on router DRC. So
   the gate is a regression detector, never a sign-off: for a shipped reference
   design (`grep -h "timing__setup__ws\|timing__hold__ws"
   flow/designs/*/gcd/rules-base.json`) the accepted values include
   **setup ws >= -1.47 ns and hold ws >= -0.055 ns** — the golden reference
   itself violates timing and keeps passing.
4. **Final STA silently falls back to estimated parasitics.**
   `flow/scripts/final_report.tcl:22,58-62`: with no RCX rules it prints
   "Falling back to global route-based estimates" and then emits the `finish__*`
   metrics under the same names an extracted-parasitics sign-off would use.
5. **IR drop is skipped silently** when the platform declares no net voltages
   (`final_report.tcl:36-56`, "IR drop analysis for power nets is skipped
   because PWR_NETS_VOLTAGES is undefined"), and no rule in `genRuleFile.py`
   gates any IR quantity — it is computed, printed, and never asserted on.
6. **Antenna violations do not fail the stage.** `detail_route.tcl:75` calls
   `check_antennas -report_file ...` and discards the return value;
   `info body check_antennas` (installed binary) shows it RETURNS a count and
   never errors. After `MAX_REPAIR_ANTENNAS_ITER_DRT` iterations, remaining
   violations survive into the GDS, seen only by a per-design rule with 30%
   headroom.
7. **The DRC violation count is an XML tag count.** `flow/Makefile:711`:
   `grep -c "<value>" $@ > 6_drc_count.rpt`, self-labelled "Hacky way of
   getting DRV count". Our `drc_vacuous_pass_check.py` measures the geometry the
   run actually consumed and calls a zero-shape layout DECISIVE VACUOUS.
8. **The clock-count metric cannot parse a legal SDC.**
   `util/genMetrics.py:158-162` does `line.split().index("-name")` for every
   `create_clock` line; `create_clock -period 5 [get_ports clk]` (no `-name`)
   raises an uncaught ValueError and kills `metadata-generate`. Loud, not
   silent — but `constraints__clocks__count` is gated with `==`, so the metric
   the rules trust is produced by a parser that handles one spelling.

Things worth taking from them, beyond the five gaps: the `-failed.odb` written
before re-raising (`global_place.tcl:64-67`, `detail_place.tcl:36-39`) so the
failing state is debuggable; and the two in-session refusals
`if { ![grt::have_routes] } { error ... }` (`detail_route.tcl:5-8`) and
`if { ![design_is_routed] } { error "Design has unrouted nets." }`
(`detail_route.tcl:77-79`) — asked of the database inside the tool, before the
stage artefact is written, rather than of a DEF afterwards. We have neither
symbol anywhere (`grep -rn "design_is_routed\|grt::have_routes"`: 0 hits).

---

## Upstream checks that CANNOT FAIL

1. **DRC and LVS on a platform with no deck.** `flow/Makefile:704-720` and
   `:723-733`: when the deck variable is empty the recipe's `else` branch is
   `echo "DRC not supported on this platform" > $@` (same for LVS) and the
   target SUCCEEDS, producing a file named like a report. The violation count
   that downstream consumers compute — `grep -c "<value>"` — finds no markers in
   that prose, i.e. zero. This is live, not theoretical: **3 of the 7 platforms
   declare no KLayout DRC deck and 4 of 7 declare no LVS deck**, one of them by
   having the LVS line commented out in its config.
2. **The in-flow LEC's verdict is a grep, and a missing log is a pass.**
   `flow/scripts/lec_check.tcl:52-58`:

   ```tcl
   try { set count [exec grep -c "Found difference" $::env(LOG_DIR)/${step}_lec_check.log] }
   trap CHILDSTATUS {results options} { set count 0 }
   if { $count > 0 } { error ... } else { puts "Repair timing output passed lec test" }
   ```

   `grep` exits non-zero both for "no match" (1) and for "file missing" (2), and
   both land in the same `set count 0`. A run whose formal tool produced no log
   reports that the netlist PASSED equivalence. On top of that,
   `lec_check.tcl:1-7` enables the check only when `LEC_CHECK==1` AND the formal
   binary exists AND is executable — otherwise the CTS stage runs identically and
   says nothing about having skipped it.
3. **The default DRC deck is the small one, and the verdict does not say so.**
   The one platform that ships two decks defaults, with `?=`, to a `_minimal`
   deck of 54,010 bytes while a `_maximal` deck of 201,492 bytes sits beside it
   in the same directory. A clean result is reported through the same target,
   the same report file and the same count regardless of which deck ran.
4. **`SKIP_REPORT_METRICS` empties the instrument.**
   `flow/scripts/report_metrics.tcl:10-12` returns before emitting anything, so
   every timing, ERC and power metric for every stage vanishes; the flow still
   completes and still writes a GDS.
5. **A missing warning-count metric is scored as zero warnings.**
   `util/checkMetadata.py:90-93` — documented as intentional, but it means a
   stage that never ran contributes "no warnings" to the gate rather than
   "not measured".

Note the good half of the same file, which is what §5 above proposes we adopt:
an empty rules set and a missing gated metric are both `sys.exit(1)`.

---

## Delta vs the published survey (https://vibeic.ai/similiar_projects.html, checked 2026-08-08)

Re-checked the OpenROAD facts at the commit our image pins (`4c26918`). The
"600+ tapeouts" claim is unchanged — README lines 112 and 259 still say "over
600 silicon-ready tapeouts" / "over 600 tapeouts" on the two open PDKs the page
names. **No drift found.** The versions we actually run, for the record:
OpenROAD `26Q3-1392-g3bf15a279a`, ORFS `c9c22caf` (2026-06-20 — two months old
at time of reading).
