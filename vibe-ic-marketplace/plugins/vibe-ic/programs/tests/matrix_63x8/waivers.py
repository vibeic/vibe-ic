"""matrix_63x8.waivers — the accepted-gap registry.

A waiver is a public, dated admission that one cell of the 504 is NOT enforced
and WHY. It is not a way to make a red test green; it is a way to make an
unenforced cell *visible and machine-checkable* instead of silently absent.

====================================================================
HOW A WAIVER IS CONSUMED
====================================================================
A waived cell's test is marked::

    @pytest.mark.xfail(strict=True, reason=waiver.reason)

``strict=True`` is REQUIRED and is the entire anti-rot mechanism: the moment
the underlying gap is fixed and the predicate starts passing, the suite goes
**red** on XPASS and forces the waiver's removal. A non-strict xfail rots
silently forever, which is the same silent-absence disease in a different
costume.

====================================================================
WHAT COUNTS AS A REASON
====================================================================
``reason`` must say what a program *cannot decide* and why, in terms someone
who has never seen the cell can check. ``evidence`` must be independently
verifiable: a ``path:line``, a measured value with the command that produced
it, or a decision reference.

    GOOD  reason:   "The gate dispatches through __import__(f'{name}_protocol_synth');
                     the set of reachable names is data-dependent on L3_CMD_PROTOCOL
                     at runtime, so no static predicate can enumerate the call sites."
          evidence: "programs/rtl_dispatch.py:214 — __import__(f'{proto}_protocol_synth')"

    GOOD  reason:   "Deciding this needs a real converged project tree; the
                     required artefact is produced only by a tool absent from CI."
          evidence: "`which verilator` -> rc=1 on 192.168.1.120; measured 2026-07-25"

    BAD   "not implemented yet"          - says nothing checkable
    BAD   "too hard"                     - says nothing checkable
    BAD   "flaky"                        - names a symptom, not a cause
    BAD   "covered elsewhere"            - then point at it in `evidence`, or
                                           it is not covered

====================================================================
THIS TUPLE STARTS EMPTY AND IS APPLIED CENTRALLY
====================================================================
The eight dimension modules share this worktree. A sibling that needs a waiver
**reports it to the orchestrator in its return value** and does NOT edit this
file — concurrent edits to a shared registry lose entries. The orchestrator
applies them in one pass.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, Union

from . import flowref
from .flowref import StepId


@dataclass(frozen=True)
class Waiver:
    """One accepted, evidence-backed gap in the 504-cell matrix."""

    step_id: Union[str, int]
    dim: int
    reason: str
    evidence: str

    @property
    def key(self) -> Tuple[str, int]:
        return (flowref.normalize_id(self.step_id), self.dim)

    @property
    def label(self) -> str:
        return f"{flowref.normalize_id(self.step_id)}/d{self.dim}"

    @property
    def xfail_reason(self) -> str:
        """The string to hand ``pytest.mark.xfail(strict=True, reason=...)``."""
        return f"WAIVED {self.label}: {self.reason} [evidence: {self.evidence}]"


#: Phrases that are NOT reasons. Matched with WORD BOUNDARIES, not as bare
#: substrings — a naive ``"later" in reason`` also fires on "related" and
#: "translated", which is the same false-positive-by-adjacent-measurement error
#: this whole package exists to avoid. Checked by the meta-test so a
#: placeholder can never be smuggled in as an accepted gap.
FORBIDDEN_REASON_SUBSTRINGS: Tuple[str, ...] = (
    "not implemented",
    "todo",
    "tbd",
    "fixme",
    "too hard",
    "will fix later",
    "unknown",
)

_FORBIDDEN_RE = tuple(
    (phrase, re.compile(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", re.IGNORECASE))
    for phrase in FORBIDDEN_REASON_SUBSTRINGS
)

#: Minimum lengths. A one-word reason cannot be evidence-backed.
MIN_REASON_LEN = 40
MIN_EVIDENCE_LEN = 8


#: Applied 2026-07-27 by the close-out pass, from the eight dimension agents'
#: reported ``waiver_requests``. Every entry names a SPECIFIC obstacle with
#: independently checkable evidence; generic reasons ("needs a real run", "hard
#: to test") were rejected and are carried as residual gaps instead.
#:
#: THIS IS THE ONLY REGISTRY. The dimension modules used to keep local mirrors
#: of their own entries, and the two copies drifted unnoticed (#527, #530). No
#: dimension module may define one; ``waiver_for`` reads this tuple and nothing
#: else.
#:
#: 2026-07-28: the ten dimension-4 entries and the five dimension-5 entries are
#: gone, and so are five of the nine dimension-7 entries — every one of them
#: because the defect it named was FIXED in the flow definition or in the gate
#: program, each with a mutation control showing the cell red on the old code.
#: The two that used to be described here as "ONE-LINE REPO DEFECTS we are not
#: fixing because it edits the production flow" (4/step 2's ``--json`` vs
#: ``--out`` mismatch, 4/P0's unregisterable gate name) are among them: the
#: flow WAS edited, and verified.
WAIVERS: Tuple[Waiver, ...] = (
    # ── dimension 3 — are the declared outputs actually produced? ──────
    #
    # #527 — A WAIVER'S PREMISE MUST BE A STATEMENT ABOUT THIS COMMIT.
    # The four entries this block used to hold were premised on `find ~`.
    # "`find ~ -maxdepth 10 -name '*.sof'` -> 0 hits (measured 2026-07-27)" is
    # a count over a directory OUTSIDE the repository. It was true the day it
    # was written and false a fortnight later — the same command returns 203
    # today, every hit untracked, one of them in the user's Trash — and nothing
    # in the repository could notice, because the repository was never what the
    # claim was about. A waiver whose premise expires on its own is a waiver
    # nobody can audit. Every premise below is now a statement `git ls-tree -r
    # HEAD` answers identically for everyone who has the commit, re-executed on
    # every run by
    # `test_d3_waived_unproven_entries_have_no_committed_artefact`.
    #
    # 2026-07-28: A8's waiver is NARROWED, not closed. Its `.gds` had no
    # producer anywhere in the plugin — `magic_port_extract_emit
    # .build_gds_write_tcl` shipped in v0.1.114 with a unit test and no caller
    # — so `programs/analog_hardmacro_gds_emit.py` was written, DECLARED in
    # A8's `programs:` and invoked by
    # `analog_one_shot_runner.step_for_block("A8_hardmacro_gen")`. It is
    # deliberately NOT a clause of A8's gate: `flow_compliance_check` is the
    # acceptance auditor and an auditor that writes a declared
    # `required_output` into the project it audits certifies its own output
    # (`test_d3_the_compliance_audit_does_not_create_declared_outputs` holds
    # that line). What did NOT change is the cell's state: the producer needs
    # Magic in the EDA container to stream anything, so on CI and on a fresh
    # clone the entry is UNMEASURED, and a cell that is green only where a
    # container runs is the host-dependence #527 removed.
    #
    # STEPS 6 AND 39 STAY WAIVED — the NA_TOOLCHAIN_ABSENT reclassification was
    # REFUTED BY ITS OWN ASSERTION. The proposal was to move both cells out of
    # this registry and call them NA because Intel Quartus, the sole producer
    # of their bitstream entries, "is reachable from nowhere this suite can
    # run", asserted live through the flow's own locator
    # (`design_one_shot_runner._find_host_quartus_sh`). Re-measured 2026-07-28
    # on the maintainer host, that locator returns a real, executable
    # `quartus_sh` under an external mount, so the NA's self-invalidating
    # assertion FIRES and both cells go red. The premise is a property of the
    # machine, which is the exact host-dependence #527 removed from this
    # dimension; the premises below are properties of the COMMIT and are true
    # everywhere. A8 stays waived for the same class of reason, narrowed: its
    # producer now exists, and what is still out of reach is the evidence.
    Waiver(
        step_id="6",
        dim=3,
        reason=(
            "Two of the three entries are Intel Quartus outputs — a .sof "
            "bitstream and a .map.rpt — and no program in this repository "
            "synthesises an FPGA bitstream, so nothing here can produce them "
            "and no archived run tree carries one either. The dimension-3 "
            "manifest records no producer for either entry, which is the same "
            "fact from the other side: there is no command this suite could "
            "run to close the gap. NOTE (2026-07-28): a host having Quartus "
            "installed does NOT close this. The claim is about the "
            "repository, and a cell whose colour depends on whether the "
            "operator's machine has a vendor toolchain is the host-dependence "
            "#527 was written to remove."
        ),
        evidence=(
            "`git ls-tree -r --name-only HEAD` matches ZERO paths against "
            "either entry — 0 tracked '*.sof' and 0 tracked '*.map.rpt' in the "
            "whole repository, and 0 under any of the 7 admissible in-repo run "
            "roots. The sibling entry reports/phase2/fpga/"
            "quartus_map_audit.json IS produced (263 B in benchmark-data/ic/"
            "spm/v1.5.66_gf180mcuD), so the step runs and only the bitstream "
            "half is missing; programs/fpga_board_capability.py:8 names 'no "
            "Quartus on host' as the expected disclosed gap. Re-executed live "
            "by programs/tests/test_matrix_d3_outputs_produced.py::"
            "test_d3_waived_unproven_entries_have_no_committed_artefact"
        ),
    ),
    Waiver(
        step_id="39",
        dim=3,
        reason=(
            "The entry phase2/stage1/fpga/final/*.sof is the recompiled Intel "
            "Quartus bitstream for on-board sign-off; the same missing "
            "producer as step 6 applies, so nothing in this repository can "
            "write it, while the sibling on_board_pass.json is produced "
            "normally."
        ),
        evidence=(
            "`git ls-tree -r --name-only HEAD` matches ZERO paths against "
            "phase2/stage1/fpga/final/*.sof anywhere in the repository or "
            "under any admissible in-repo run root; the sibling entry "
            "reports/phase2/fpga/on_board_pass.json resolves at 732 B in "
            "benchmark-data/ic/spm/v1.5.66_gf180mcuD. Re-executed live by "
            "programs/tests/test_matrix_d3_outputs_produced.py::"
            "test_d3_waived_unproven_entries_have_no_committed_artefact"
        ),
    ),
    Waiver(
        step_id="A8",
        dim=3,
        reason=(
            "NARROWED 2026-07-28, and the narrowing is a real repair: the "
            "producer is no longer missing. Until this change the .gds entry "
            "was emitted by NOTHING — magic_port_extract_emit."
            "build_gds_write_tcl shipped in v0.1.114 with a unit test and no "
            "caller — and programs/analog_hardmacro_gds_emit.py now streams "
            "each block's A5 layout.mag to GDS, is declared in A8's "
            "`programs:` and is dispatched by analog_one_shot_runner."
            "step_for_block('A8_hardmacro_gen'). What is still unreachable is "
            "the EVIDENCE, not the producer: Magic writes the stream inside "
            "the EDA container, the producer's documented rc=2 names the gap, "
            "and neither CI (a plain runner with pytest and no docker) nor a "
            "fresh clone has that container — so this dimension cannot decide "
            "the entry from the commit alone. Deliberately NOT closed by "
            "committing a produced .gds into a run tree: that would be a "
            "benchmark-data write made to turn a test green. Closing this "
            "needs a published analog run whose A8 actually streamed the "
            "layout."
        ),
        evidence=(
            "`git ls-tree -r --name-only HEAD` matches ZERO paths against "
            "phase3/analog/hardmacro/*/*.gds while matching 2 for the sibling "
            "*.lef (benchmark-data/ic/u_hawaii_adc/phase3/analog/hardmacro/"
            "{ldo,delta_sigma}/*.lef) — the step ran and only the .gds is "
            "absent. Producer wiring is asserted live by "
            "test_d3_a8_producer_is_reachable_from_a_flow_path (the runner "
            "dispatch, with subprocess recorded) and the emitter itself by "
            "programs/tests/test_analog_hardmacro_gds_emit.py (14 tests). "
            "Capability gap re-measured 2026-07-28: `python3 programs/"
            "analog_hardmacro_gds_emit.py .` on a copy of benchmark-data/ic/"
            "u_hawaii_adc returns rc=2 A8GDS_NO_STAGE naming the absent EDA "
            "container. Whatever a run root DOES carry at that path is still "
            "checked to be a real layout defining the block's own structure "
            "(test_d3_a8_gds_in_a_run_root_is_a_real_hardmacro_layout). "
            "Re-executed live by programs/tests/"
            "test_matrix_d3_outputs_produced.py::"
            "test_d3_waived_unproven_entries_have_no_committed_artefact"
        ),
    ),
    Waiver(
        step_id="M1",
        dim=3,
        reason=(
            "NARROWED 2026-07-28. The producer is NOT missing: "
            "mixed_signal_top_lvs_run.py writes phase3/mixed_signal/"
            "top_merged.gds (KLayout merge), ships, and is invoked twice — "
            "M1's own advisory gate clause and vibe_ic_one_shot_runner:813. "
            "What is unreachable is an INPUT SET: the merge needs a digital "
            "sign-off GDS and analog hardmacro GDS in the SAME project, and "
            "no admissible run root is a mixed-signal project that got that "
            "far, so the producer returns its documented rc=2 'inputs "
            "missing' skip everywhere it can run. Closing this needs a "
            "published mixed-signal run tree, not a code change."
        ),
        evidence=(
            "programs/mixed_signal_top_lvs_run.py:184-199 writes top_merged."
            "gds; :152-161 returns SKIP rc=2 naming the absent inputs. Asked "
            "DIRECTLY (mixed_signal_top_lvs_run.run, tool probe stubbed) on "
            "all 12 admissible run roots, 2026-07-28: 12/12 return 'inputs "
            "missing'. Three lack only 'hardmacro GDS (A8)' (the spm-class "
            "digital runs, which have a sign-off GDS and no analog blocks at "
            "all) and the one root with hardmacro GDS lacks 'digital GDS, "
            "gate netlist' — intersection empty. The 2026-07-27 evidence for "
            "this waiver quoted 'Top-level GDS merge tool not shipped.' from "
            "an ARCHIVED merge.json; that string exists nowhere in the plugin "
            "today (mixed_signal_merge_check.py:57 now reads 'Top-level "
            "merge+LVS not runnable in this environment'), so the old reason "
            "was stale. Re-measured live by "
            "test_d3_m1_merge_inputs_are_absent_from_every_run_root."
        ),
    ),

    # ── dimension 6 — skip discipline (the ARITHMETIC half) ───────────
    # EMPTY, and that is the point. This block used to hold THREE waivers
    # (FS1, 30, 14) charged by leg L3c of test_matrix_d6_skip_discipline:
    # each landed on the VACUOUS_PASS tier — its own label, its own counter
    # — while `flow_compliance_check` folded the tier straight back into the
    # published `X/Y executed PASS` numerator
    # (`pass_count = counts['PASS'] + counts['VACUOUS_PASS']`), so the number
    # a reviewer reads was unchanged by the disclosure. A fourth cell (step
    # 4) is charged by the same leg on hosts where its gate resolves to
    # VACUOUS_PASS rather than FAIL, and had no waiver at all — that is the
    # cell that turned main red.
    #
    # All four are CLOSED by the fix, not by a waiver: the owner ruled
    # VACUOUS_PASS out of the numerator. `pass_count = counts['PASS']`, the
    # tier stays in `total_required` (it is an unmet requirement, not an
    # inapplicable step), and every rendering of the numerator moved with it
    # — the checker headline, `final_report_generate._counts_snapshot`, its
    # prose bullet, its stage-breakdown PASS column and its resource log.
    #
    # MEASURED on this host over all 12 tracked run roots of
    # programs/tests/fixtures/matrix_d3_output_manifest.json, each COPIED
    # and re-run with the shipped checker, full flow, --strict: 12/12 roots
    # move their headline numerator and 37 step-instances leave X on the
    # numerator ruling alone. That half changes NO verdict, and the reason is
    # structural rather than a property of this corpus: `pass_count` is
    # assigned once and read once, in the headline `print`, and feeds none of
    # `failing` / `missing` / `setup_required_skipped` / `oss_blocked_skipped`
    # / `ok`. #01 4/7->3/7, #02 3/39->2/39, #03 11/26->6/26,
    # #04 18/39->13/39, #05 7/53->4/53, #06 14/30->11/30, #07 20/42->16/42,
    # #08 19/32->16/32, #09 15/53->11/53, #10 5/10->4/10, #11 7/41->4/41,
    # #12 31/42->27/42.
    #
    # AS SHIPPED, the same sweep run against the whole commit — which also
    # carries the dimension-7 declaration on step 27 — reads: 12/12 headlines
    # move, 40 step-instances leave X (37 vacuous + 3 from step 27), 3 of 756
    # per-step verdicts change and 0 of 12 Overall verdicts change (all 12
    # FAIL before and after). The three are all step 27, on the three roots
    # that carry a crosstalk report and no MCF report: #03 PASS ->
    # DEFERRED-BY-UPSTREAM (a cascade, which is also why its denominator
    # moves 26 -> 25), #04 and #09 PASS -> MISSING. Combined headlines:
    # #03 11/26->5/25, #04 18/39->12/39, #09 15/53->10/53; the other nine are
    # the numbers above.

    # ── dimension 6 — skip discipline (the CONDITION half) ────────────
    Waiver(
        step_id="DT2",
        dim=6,
        reason=(
            "RE-OPENED 2026-07-28 at the convergence merge, with a sharper "
            "reason than it carried before. DT2's step-level condition is "
            "ALL-of over three paths, two of which "
            "(phase2/stage2/dft/cut_netlist.v and phase3/stage3/pnr/*_pnr.v) "
            "are artefacts whose absence DT2 exists to detect, so the step "
            "disappears in the scenario it was written for. The repo AGREES: "
            "flow_condition_reachability_check classifies it 'self-disabling' "
            "and it is carried in flow_condition_reachability_baseline.json as "
            "a known-open hole owned by vibe-ic#235. WHAT IS NEW, and why the "
            "cell is not enforced-clean by the obvious repair: re-arming the "
            "condition on the PRODUCER'S OWN OUTPUTS (any-of over "
            "reports/phase2/dft/path_delay_coverage.json or "
            "phase2/stage2/dft/path_delay_atpg_not_run.json) was tried, "
            "measured, and WITHDRAWN — it moves the self-disable from the "
            "input side to the output side, where it is strictly worse: "
            "deleting the one artefact DT2 exists to report on turns the step "
            "from MISSING/rc 1 into SKIPPED-CONDITION/rc 0 and removes it from "
            "the executed-PASS denominator, because total_required subtracts "
            "SKIPPED-CONDITION. Closing this cell needs a flow-level non-fatal "
            "verdict for 'ran, disclosed, could not measure' that COSTS the "
            "denominator; no spelling of the condition alone can do it."
        ),
        evidence=(
            "flow/flow_condition_reachability_baseline.json (owner: "
            "vibe-ic#235). Reproduce the hole: `python3 "
            "programs/flow_condition_reachability_check.py .` -> 'KNOWN-OPEN: "
            "1 self-disabling condition(s)' naming step DT2. Reproduce the "
            "withdrawn repair, on a project holding cut_netlist.v + *.spef + "
            "*_pnr.v and NO at-speed grade and NO not-run record, with a "
            "single-step DT2 flow lifted from each yaml: ALL-of condition -> "
            "'MISSING=1' / 'Overall: FAIL (strict=True)' / rc 1; "
            "producer-outputs condition -> 'SKIPPED=2' / 'Steps: 1 total "
            "(0/-1 executed PASS)' / 'Overall: PASS' / rc 0. Measured "
            "2026-07-28 with programs/flow_compliance_check.py from this tree "
            "on both flow definitions."
        ),
    ),

    # ── dimension 7 — is the required_outputs list complete? ───────────
    # Five of the nine original entries were CLOSED on 2026-07-28 by declaring
    # the artefact (D1, 21, 25, 28, 31). The four below are the residue and
    # they are blocked on three different things. Two (7, 23) share one:
    # `required_outputs` is ALL-of-N with no conditional spelling, so an
    # artefact the flow emits only on one branch of a genuine design/PDK
    # condition cannot be declared without failing the other branch. M1 is
    # blocked on evidence: the artefact exists in no published run root, so
    # declaring it would move the gap from dimension 7 to dimension 3. FS1 is
    # blocked on WIRING, and its entry below is the one that was briefly closed
    # and reopened the same day — the closure rested on the compliance checker
    # accepting an artefact it had created itself.
    Waiver(
        step_id="FS1",
        dim=7,
        reason=(
            "FS1 declares no required_outputs key at all while its gate writes "
            "two real JSON artefacts, so there is no list for the flow's "
            "presence checks to key off. REOPENED 2026-07-28 with the reason "
            "sharpened from 'adding one is a yaml change nobody has made yet' "
            "to the thing that actually blocks it: FS1's artefacts have NO "
            "producer anywhere in the plugin except the first command of its "
            "own gate, so a declaration cannot be satisfied by a run — only by "
            "the auditor. flow_compliance_check returns MISSING before the "
            "gate runs when every declared entry is absent, so declaring both "
            "paths makes FS1 a permanent red (MEASURED: two consecutive "
            "check_step runs on a fixture holding only phase2/stage1/rtl both "
            "report MISSING and leave no file under reports/). The withdrawn "
            "closure removed that early return for this step SHAPE so the gate "
            "would run and a post-gate probe would find what the gate had just "
            "written; the same suppression turned step 8 from a correct "
            "MISSING into PASS on benchmark-data/ic/ibex, certifying it on "
            "reports/phase2/sdc_check.json which the audit itself created and "
            "12 other tracked roots really do carry. WHAT CLOSES THIS, exactly "
            "one thing: wire fmeda_fault_injection_coverage into a runner the "
            "way phase3_one_shot_runner._DECLARED_SIGNOFF_GATES wired the four "
            "sign-off gates on 2026-07-27, so the artefact exists BEFORE the "
            "audit looks; then declare both paths."
        ),
        evidence=(
            "flow/phase1_phase2_phase3.yaml FS1 step has no required_outputs "
            "key while its gate runs 'fmeda_fault_injection_coverage ... "
            "--json reports/phase2/safety/fmeda_coverage.json' and "
            "'fmeda_coverage_check ... --json "
            "reports/phase2/safety/fmeda_coverage_gate.json'. NO OTHER "
            "PRODUCER: `grep -rn fmeda_fault_injection_coverage programs/ "
            "flow/` reaches only the program itself, fmeda_coverage_check.py:"
            "3,45 (docstring + library import) and that one yaml gate line. "
            "All 7 tracked roots carrying reports/phase2/safety/"
            "fmeda_coverage.json hold the auditor's vacuous-skip document "
            "({'program': 'fmeda_fault_injection_coverage', 'verdict': "
            "'NOT_APPLICABLE'}), i.e. compliance-gate output committed "
            "alongside a run, not a fault-injection measurement."
        ),
    ),
    Waiver(
        step_id="7",
        dim=7,
        reason=(
            "reports/phase3/single_corner_stance.json is emitted ONLY on the "
            "single-corner branch — phase3_one_shot_runner writes it under "
            "`if len(corners) < 2 and not pvt.get('multi_corner')` — and a "
            "multi-corner run legitimately produces none, so an unconditional "
            "required_outputs entry converts every honest multi-corner run "
            "into MISSING. required_outputs is ALL-of-N and its only any-of "
            "spelling is ' OR ' between paths; every alternative that would "
            "cover the multi-corner branch (pvt_matrix.json, the gate's own "
            "reports/phase2/gates/pvt_matrix.json) is present on EVERY run, "
            "so the entry could never fail and would be a declaration that "
            "measures nothing. Closing this needs a producer change that "
            "emits a corner-stance disclosure on BOTH branches, plus a "
            "re-publish of the affected roots — a flow change with its own "
            "verification, not a declaration change."
        ),
        evidence=(
            "producer programs/phase3_one_shot_runner.py:20321-20344 (the "
            "`len(corners) < 2` guard around `rpt_phase3 / "
            "'single_corner_stance.json'`); consumer "
            "programs/pvt_matrix_check.py:44-45 then :105. MEASURED "
            "2026-07-28 with flow_compliance_check.check_step over the nine "
            "tracked roots holding phase2/stage2/constraints/pvt_matrix.json: "
            "adding the entry moves benchmark-data/ic/spm/v1.5.58_ihp-sg13g2, "
            "v1.5.65_sky130A and v1.5.66_gf180mcuD from PASS to MISSING "
            "('required_outputs missing: "
            "[reports/phase3/single_corner_stance.json]') — three "
            "multi-corner runs failed for producing no single-corner "
            "disclosure. The other six are FAIL/PASS-unchanged."
        ),
    ),
    Waiver(
        step_id="M1",
        dim=7,
        reason=(
            "reports/analog/mixed_signal/top_lvs.json is the artefact that "
            "substantiates M1's PASS — mixed_signal_top_lvs_run writes it and "
            "mixed_signal_merge_check's PASS branch is contingent on reading "
            "it — yet M1's required_outputs names only top_merged.gds and "
            "merge.json, so nothing independently verifies its presence. "
            "Declaring it was PREPARED and then withdrawn on evidence: the "
            "artefact exists in NONE of the twelve admissible run roots and "
            "its producer needs KLayout + Magic + netgen in a container, so "
            "it cannot be shown produced live here either. Declaring it would "
            "add a second UNPROVEN entry to M1's dimension-3 waiver — moving "
            "the gap between dimensions rather than closing it. What closes "
            "this: publish one run root in which mixed_signal_top_lvs_run "
            "actually executed, then declare the artefact and record it."
        ),
        evidence=(
            "producer programs/mixed_signal_top_lvs_run.py:256 "
            "((rpt_dir / 'top_lvs.json').write_text(...), in the same block "
            "as the already-declared merge.json); consumer "
            "programs/mixed_signal_merge_check.py:88-90 then :107. MEASURED "
            "2026-07-28 with test_matrix_d3_outputs_produced.resolve_anywhere("
            "'reports/analog/mixed_signal/top_lvs.json') -> None over all 12 "
            "run roots, while the sibling merge.json resolves at "
            "AI_IC_design/4th_benchmark/U_Hawaii_EE628_DeltaSigma_ADC_e2e "
            "(497 B). Mutation check that the declaration WOULD be live: with "
            "mixed_signal_merge_check's MERGE_NOT_LVS_SUBSTANTIATED branch "
            "flipped to its historical PASS-on-presence stub, M1 reports PASS "
            "without the declaration and MISSING with it."
        ),
    ),
    Waiver(
        step_id="23",
        dim=7,
        reason=(
            "Fourteen artefacts remain undeclared after "
            "reports/phase3/sta/sta_corner_record_completeness.json was "
            "declared on 2026-07-28 (that one is the step's own unconditional "
            "gate --json target, so it closed with no verdict change on any "
            "published root). The residue splits in two and BOTH halves are "
            "conditional-by-design. (a) The two multi-corner STANCE files are "
            "written only when the post-route DEF exists, and six of the "
            "eight tracked roots carrying this step's already-declared "
            "post_route_timing.rpt predate that emitter; five of them PASS "
            "today and go MISSING if the stance files are declared. (b) The "
            "three sign-off .rpt files are each emitted on one branch of a "
            "real PDK condition — sta_mcorner_ocv.rpt only when the ss and ff "
            "process libraries genuinely differ, sta_spef_multicorner.rpt "
            "only with two or more corner SPEFs, sta_spef_based.rpt only with "
            "a non-empty SPEF — and their absence is DISCLOSED in the stance "
            "files (`report: null`, `multicorner_sta_report: null`). Pairing "
            "each .rpt with its stance file via ' OR ' would declare the "
            "name, but with the stance ALSO declared the pair could never "
            "fail on its own, so it would be decoration. Closing this needs "
            "the (a) decision — re-publish the six roots, or add a "
            "conditional/disclosed-skip spelling to required_outputs — taken "
            "first; then (b) follows as OR-pairs that can actually fail."
        ),
        evidence=(
            "producers programs/phase3_one_shot_runner.py:20549 and :20638 "
            "(sta_out / 'sta_spef_based.rpt', sta_out / "
            "'sta_mcorner_ocv.rpt') with mirrors at :20555 and :20668, and "
            "the two stance writes at :20567 and :20639 both guarded by "
            "`if primary_def.is_file() and _signoff_regen(...)`; consumer "
            "programs/sta_corner_record_completeness_check.py:195-215 "
            "(_PROCESS_STANCE_CANDIDATES / _RC_STANCE_CANDIDATES / "
            "_MULTICORNER_CANDIDATES / _MCORNER_OCV_CANDIDATES / "
            "_NOMINAL_SPEF_CANDIDATES). MEASURED 2026-07-28 with "
            "flow_compliance_check.check_step over the eight tracked roots "
            "holding phase3/stage3/sta/post_route_timing.rpt: declaring the "
            "two stance files moves phase1_parity/{espi,lpc/phase3,mdio,"
            "sgmii} and benchmark-data/ic/caravel_user_project from PASS to "
            "MISSING (5 of 8); the other three are FAIL before and after."
        ),
    ),
)


_BY_KEY: Dict[Tuple[str, int], Waiver] = {w.key: w for w in WAIVERS}


def waiver_for(step_id: StepId, dim: int) -> Optional[Waiver]:
    """The waiver at ``(step_id, dim)``, or ``None``. Accepts int or str ids."""
    return _BY_KEY.get((flowref.normalize_id(step_id), int(dim)))


def waivers_for_dim(dim: int) -> Tuple[Waiver, ...]:
    """Every waiver of one dimension, in registry order."""
    return tuple(w for w in WAIVERS if w.dim == int(dim))


def is_waived(step_id: StepId, dim: int) -> bool:
    return waiver_for(step_id, dim) is not None


def validate(waiver: Waiver) -> Tuple[str, ...]:
    """Return the list of problems with *waiver*; empty tuple means valid.

    Used by the meta-test. Kept as a function (not an ``__post_init__``) so a
    bad waiver produces a readable aggregate failure instead of an import-time
    explosion that hides every other problem.
    """
    problems = []
    if waiver.dim not in range(1, 9):
        problems.append(f"dim {waiver.dim!r} is not in 1..8")
    if not flowref.has_step(waiver.step_id):
        problems.append(f"step {waiver.step_id!r} is not declared in the flow yaml")
    reason = (waiver.reason or "").strip()
    evidence = (waiver.evidence or "").strip()
    if not reason:
        problems.append("reason is empty")
    elif len(reason) < MIN_REASON_LEN:
        problems.append(
            f"reason is {len(reason)} chars, under the {MIN_REASON_LEN}-char "
            f"floor — say what a program cannot decide and why"
        )
    for bad, rx in _FORBIDDEN_RE:
        if rx.search(reason):
            problems.append(f"reason contains the non-reason phrase {bad!r}")
    if not evidence:
        problems.append("evidence is empty")
    elif len(evidence) < MIN_EVIDENCE_LEN:
        problems.append(
            f"evidence is {len(evidence)} chars — needs a path:line, a measured "
            f"value, or a decision reference"
        )
    return tuple(problems)


def xfail_mark(step_id: StepId, dim: int):
    """The pytest mark for ``(step_id, dim)``, or ``None`` when not waived.

    Exists so that ``strict=True`` is decided HERE, once, instead of eight
    times by eight agents. A non-strict ``xfail`` rots silently forever: the
    gap gets fixed, the test starts passing, and nobody is told the waiver is
    now a lie. With ``strict=True`` an XPASS turns the suite red and forces the
    waiver's removal — that is the entire anti-rot mechanism, and it is not a
    per-module style choice.

    Usage::

        mark = waivers.xfail_mark(sid, 4)
        if mark:
            request.applymarker(mark)

    or at collection time::

        pytest.param(sid, marks=[m] if (m := waivers.xfail_mark(sid, 4)) else [])
    """
    import pytest  # local import: the substrate stays importable without pytest

    w = waiver_for(step_id, dim)
    if w is None:
        return None
    return pytest.mark.xfail(strict=True, reason=w.xfail_reason)


__all__ = [
    "Waiver",
    "WAIVERS",
    "xfail_mark",
    "waiver_for",
    "waivers_for_dim",
    "is_waived",
    "validate",
    "FORBIDDEN_REASON_SUBSTRINGS",
    "MIN_REASON_LEN",
    "MIN_EVIDENCE_LEN",
]
