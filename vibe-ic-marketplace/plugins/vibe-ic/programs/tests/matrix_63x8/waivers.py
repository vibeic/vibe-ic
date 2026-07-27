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
#: to test") were rejected and are carried as residual gaps instead. Reason and
#: evidence text is verbatim from the reporting agent so the local mirrors in
#: the dimension modules compare equal and go inert.
#:
#: Two of these are ONE-LINE REPO DEFECTS rather than limits of mechanisation
#: (4/step 2's ``--json`` vs ``--out`` flag mismatch, and 4/P0's wrong example
#: gate name in the flow's own notes). They are waived rather than fixed here
#: because fixing them edits the production flow definition, which is not a
#: test-coverage change and needs its own verification. ``strict=True`` means
#: the day either is fixed this suite goes red and the waiver must be removed.
WAIVERS: Tuple[Waiver, ...] = (
    # ── dimension 3 — are the declared outputs actually produced? ──────
    Waiver(
        step_id="6",
        dim=3,
        reason=(
            "Two of the three entries are Intel Quartus outputs — a .sof "
            "bitstream and a .map.rpt — and Quartus is installed on no host "
            "this suite can reach, so no run can produce them and no program "
            "in the plugin synthesises an FPGA bitstream itself."
        ),
        evidence=(
            "`command -v quartus quartus_sh quartus_map quartus_fit "
            "quartus_asm` -> all absent, and `find ~ -maxdepth 10 -name "
            "'*.sof'` -> 0 hits across 108 candidate run trees (measured "
            "2026-07-27); programs/fpga_board_capability.py:8 names 'no "
            "Quartus on host' as the expected disclosed gap"
        ),
    ),
    Waiver(
        step_id="39",
        dim=3,
        reason=(
            "The entry phase2/stage1/fpga/final/*.sof is the recompiled Intel "
            "Quartus bitstream for on-board sign-off; the same tool gap as "
            "step 6 applies, so this entry has no producer on any reachable "
            "host while the sibling on_board_pass.json is produced normally."
        ),
        evidence=(
            "`find ~ -maxdepth 10 -name '*.sof'` -> 0 hits (measured "
            "2026-07-27); the sibling entry "
            "reports/phase2/fpga/on_board_pass.json resolves in "
            "benchmark-data/ic/spm/v1.5.66_gf180mcuD"
        ),
    ),
    Waiver(
        step_id="A8",
        dim=3,
        reason=(
            "Three of A8's four entries (.lef/.lib/.v) are produced by a real "
            "analog run, so the step demonstrably executes; the .gds entry "
            "alone is produced by nothing. Every matching file on the host is "
            "a stub written by a throwaway seeding script into an agent "
            "scratch tree, and admitting a seeded INPUT as a produced OUTPUT "
            "is the false pass this campaign removes."
        ),
        evidence=(
            "`find ~ -maxdepth 10 -path '*analog/hardmacro/*' -name '*.gds'` "
            "-> only backlog_medlow_mixed_scratch/{ba_mixed,ba_pristine,"
            "m1proj}, all written by backlog_medlow_mixed_scratch/mkgds.py (a "
            "12-line pya script), none carrying provenance.jsonl or "
            "reports/orchestrator; the sibling .lef/.lib/.v resolve in "
            "AI_IC_design/4th_benchmark/U_Hawaii_EE628_DeltaSigma_ADC_e2e/"
            "phase3/analog/hardmacro/{ldo,delta_sigma}/; measured 2026-07-27"
        ),
    ),
    Waiver(
        step_id="M1",
        dim=3,
        reason=(
            "The step's own gate output records that the merge tool which "
            "would write phase3/mixed_signal/top_merged.gds does not ship, so "
            "a run that reaches M1 emits merge.json (the sibling entry, which "
            "IS produced) while the merged GDS is never written. No flow-run "
            "tree on the host carries one."
        ),
        evidence=(
            "AI_IC_design/4th_benchmark/U_Hawaii_EE628_DeltaSigma_ADC_e2e/"
            "reports/analog/mixed_signal/merge.json -> {\"verdict\": \"SKIP\", "
            "\"rationale_when_skipped\": \"Top-level GDS merge tool not "
            "shipped.\", \"missing\": [\"phase3/mixed_signal/top_merged.gds\"]}"
            " (measured 2026-07-27)"
        ),
    ),

    # ── dimension 4 — does the gate measure what its name claims? ──────
    Waiver(
        step_id="2",
        dim=4,
        reason=(
            "The flow's own gate command passes --json, but the program it "
            "names declares --out and no --json, so its parser REJECTS the "
            "declared invocation: argparse exits 2, and flow_compliance_check "
            "maps rc==2 onto VACUOUS_PASS, so the clause banks a step PASS "
            "while auditing nothing and never writing the audit trail the "
            "yaml names."
        ),
        evidence=(
            "programs/rtl_bug_report_schema_check.py:260 declares --out (no "
            "--json); running the yaml's exact command in an empty project "
            "gives rc=2 + 'rtl_bug_report_schema_check.py: error: "
            "unrecognized arguments: --json "
            "reports/phase2/gates/rtl_bug_schema.json' and no file written; "
            "programs/flow_compliance_check.py:2157 returns True for rc==2"
        ),
    ),
    Waiver(
        step_id="9",
        dim=4,
        reason=(
            "Step 9 declares 'phase2/stage2/synth/area.rpt OR "
            "phase2/stage2/synth/stats.json' but neither gate program ever "
            "opens an area or stats artefact, so the synthesis step's own area "
            "claim is gated by nothing; the gate measures cell accounting and "
            "provenance only."
        ),
        evidence=(
            "programs/synth_netlist_check.py:281 reads only the --netlist "
            "path; programs/provenance_check.py reads provenance.jsonl; "
            "grep -n 'area\\.rpt\\|stats\\.json' over both files and their "
            "direct local imports yields 0 executable hits (2026-07-27)"
        ),
    ),
    Waiver(
        step_id="11",
        dim=4,
        reason=(
            "Step 11 declares 'phase2/stage2/dft/transition_atpg_plan.md' as a "
            "required output, but none of the three gate programs names that "
            "artefact anywhere in executable code, so the at-speed transition "
            "plan the step claims to deliver is unmeasured by the step's gate."
        ),
        evidence=(
            "grep -n transition_atpg_plan programs/dft_atpg_coverage_check.py "
            "programs/bsdl_emit.py programs/dft_signoff_check.py -> 0 hits "
            "(2026-07-27); the separate DT1 step has its own "
            "transition_coverage_check gate"
        ),
    ),
    Waiver(
        step_id="14",
        dim=4,
        reason=(
            "Step 14 is the synthesis HANDOFF gate and declares "
            "'phase2/stage2/synth/netlist.v', but both gate programs audit the "
            "Yosys *.ys SCRIPT only and never open the netlist that script is "
            "supposed to have produced — the artefact handed to PnR is not the "
            "artefact the gate inspects."
        ),
        evidence=(
            "programs/yosys_script_template_check.py:201 ys_globs = "
            "['phase2/stage2/synth/*.ys', 'phase2/stage2/synth/**/*.ys', ...]; "
            "programs/yosys_hilomap_required_check.py reads --ys-file / *.ys "
            "only; 'netlist.v' appears in both files exclusively in prose"
        ),
    ),
    Waiver(
        step_id="25",
        dim=4,
        reason=(
            "Step 25 declares 'reports/phase3/em.json' but the EM mode of the "
            "wrapped auditor discovers report files by .rpt-family globs only, "
            "so the JSON half of the step's declared electromigration evidence "
            "is never opened by the gate that signs the step off."
        ),
        evidence=(
            "programs/eda_report_audit.py:848 _check_em -> _discover(project, "
            "['*em*.rpt', '*electromigration*', '*EM*.rpt', '*ir*.rpt']) — no "
            ".json pattern; programs/em_report_check.py forwards argv into it"
        ),
    ),
    Waiver(
        step_id="28",
        dim=4,
        reason=(
            "Step 28 declares three artefacts but its gate opens exactly one "
            "of them: the human-readable PERC report and the sign-off memo are "
            "declared deliverables that no gate program reads, so a step named "
            "'PERC / Reliability sign-off' verifies a third of what it "
            "declares."
        ),
        evidence=(
            "programs/perc_signoff_check.py:35 src = project / 'reports' / "
            "'phase3' / 'perc_equivalent.json' is the only artefact opened; "
            "'perc_equivalent.rpt' and 'PERC_SIGNOFF_MEMO.md' appear nowhere "
            "in that file's executable code (2026-07-27)"
        ),
    ),
    Waiver(
        step_id="32",
        dim=4,
        reason=(
            "Step 32 declares 'phase3/stage3/eco/eco_trigger_decision.json' — "
            "the record of WHY an ECO was or was not run — but the ECO audit "
            "gate opens the eco log only, so the trigger decision the step "
            "exists to justify is never cross-checked by the step's own gate."
        ),
        evidence=(
            "programs/eco_loop_audit.py:40 data = "
            "json.loads(eco_log.read_text()) is its only artefact read; grep "
            "-n eco_trigger_decision programs/eco_loop_audit.py -> 0 hits "
            "(2026-07-27)"
        ),
    ),
    Waiver(
        step_id="33",
        dim=4,
        reason=(
            "Step 33 declares 'reports/phase3/power.json' but the power mode "
            "of the wrapped auditor discovers .rpt/.log only, so the "
            "machine-readable half of the declared power evidence is never "
            "opened; the gate reports on power from the text report alone."
        ),
        evidence=(
            "programs/eda_report_audit.py:793 _check_power -> "
            "_discover(project, ['*power*.rpt', '*power*.log', '*Power*.rpt', "
            "'*Power*.log']) — no .json pattern; "
            "programs/power_report_check.py forwards argv into it"
        ),
    ),
    Waiver(
        step_id="39",
        dim=4,
        reason=(
            "The gate DOES hash the bitstream, but it reaches it through a "
            "report key read at runtime — the path comes from the attestation "
            "JSON's bitstream_path field, not from any literal in the source — "
            "so no static predicate can bind it to the yaml's declared "
            "'phase2/stage1/fpga/final/*.sof'. This is a limit of the "
            "mechanization, not a demonstrated gap in the gate."
        ),
        evidence=(
            "programs/fpga_on_board_attestation_check.py:139 bp = "
            "data.get('bitstream_path'); :147 disk_sha = _sha256(abs_bp) — the "
            "only .sof mentions in the file are in its docstring (lines 14-22) "
            "and a comment (line 271)"
        ),
    ),
    Waiver(
        step_id="P0",
        dim=4,
        reason=(
            "P0's own notes name cdc_async_input_check as one of the gate "
            "names that appear in the audit JSON's gates[] array, but that "
            "array is built exclusively from the structural-RTL registry and "
            "cdc_async_input_check is not a member of it — it is a Step-3 gate "
            "program. The step's prose therefore advertises a checker its "
            "mechanism cannot emit."
        ),
        evidence=(
            "python3 -c \"import flow_compliance_check as f; "
            "print('cdc_async_input_check' in f._STRUCTURAL_RTL_GATES)\" -> "
            "False (241 members; nearest is "
            "fpga_async_input_synchronizer_check); "
            "programs/flow_compliance_check.py:7621 builds per_gate only from "
            "the P0 result and :7687 stores it as the audit's 'gates' array"
        ),
    ),

    # ── dimension 5 — are the declared dependencies correct? ───────────
    Waiver(
        step_id="8",
        dim=5,
        reason=(
            "LIVE DEFECT, reproduced: step 8's gate program "
            "sdc_exception_correlation_check reads "
            "reports/phase2/cdc/crossing.json — step 3's declared "
            "required_output — to decide whether each set_false_path is "
            "justified, but step 8 declares blocks_on:[7] whose closure is "
            "{7, 1, D1} and does not reach step 3. The read is wrapped in "
            "`except (OSError, ValueError): pass`, so a missing or STALE "
            "crossing.json does not fail the step; it silently empties the "
            "known-async-pair set and every legitimate CDC false_path is then "
            "reported SDC_EXCEPTION_UNJUSTIFIED. Step 3 is declared EARLIER in "
            "the yaml, so this is a plainly addable edge, not a structural "
            "conflict."
        ),
        evidence=(
            "programs/sdc_exception_correlation_check.py:46 `cdc = project / "
            "\"reports\" / \"phase2\" / \"cdc\" / \"crossing.json\"`; producer "
            "flow/phase1_phase2_phase3.yaml:401 (step 3 required_outputs); "
            "consumer flow/phase1_phase2_phase3.yaml:766 (step 8, blocks_on:[7])"
        ),
    ),
    Waiver(
        step_id="DT2",
        dim=5,
        reason=(
            "LIVE DEFECT, reproduced: DT2's own condition.files_exist names "
            "phase3/stage3/extracted/*.spef, which is step 22's declared "
            "required_output, but DT2 declares blocks_on:[DT1] and step 22 is "
            "not in its closure. The condition makes DT2 self-skip when the "
            "SPEF is absent, which prevents a crash but NOT a stale read: on a "
            "resumed project a SPEF from a previous run makes DT2 run at-speed "
            "path-delay ATPG against last run's parasitics. The edge cannot "
            "simply be added — step 22 is declared at yaml index 34 and DT2 at "
            "index 14, so DT2 -> 22 would be a forward edge; the real fix is a "
            "flow-ordering decision (DT2 belongs after Phase-3 extraction), "
            "not a one-line blocks_on edit."
        ),
        evidence=(
            "flow/phase1_phase2_phase3.yaml:1128-1152 (DT2: condition line "
            "1135 lists phase3/stage3/extracted/*.spef; blocks_on:[DT1]); "
            "producer flow/phase1_phase2_phase3.yaml:1728,1735 (step 22 "
            "required_outputs)"
        ),
    ),
    Waiver(
        step_id="A5",
        dim=5,
        reason=(
            "LIVE DEFECT, reproduced, and CIRCULAR: A5's wired gate program "
            "analog_a5_layout_check builds and reads <block>/drc_clean.flag "
            "and <block>/lvs_match.flag and requires both to carry a clean "
            "verdict before A5 can PASS — but those two are A6's declared "
            "required_outputs, and A6 declares blocks_on:[A5]. So the true "
            "data dependency runs A5 -> A6 while the declared ordering runs "
            "A6 -> A5. No blocks_on edit fixes this: adding A5 -> A6 closes a "
            "cycle. One of the two sides is wrong and a program cannot decide "
            "which without the design intent (either A5 must stop requiring PV "
            "evidence, or the A5/A6 split is misdrawn)."
        ),
        evidence=(
            "programs/analog_a5_layout_check.py:237-238 `drc_flag = bdir / "
            "\"drc_clean.flag\"` / `lvs_flag = bdir / \"lvs_match.flag\"` "
            "(gate at flow/phase1_phase2_phase3.yaml:1323, blocks_on:[A4]); "
            "producer A6 at flow/phase1_phase2_phase3.yaml:2526, blocks_on:[A5]"
        ),
    ),
    Waiver(
        step_id="18",
        dim=5,
        reason=(
            "LIVE DEFECT, reproduced, and UNSATISFIABLE BY EDGE: step 18's "
            "gate program spare_cell_preservation_check resolves the DEF it "
            "audits by preferring phase3/stage3/pnr/filled.def (step 34's "
            "declared output) and falling back to routed.def (step 21's), "
            "neither of which is in step 18's closure (blocks_on:[17]). On a "
            "resumed project both files survive from the previous run, so step "
            "18 — spare-cell insertion, which runs BEFORE routing and metal "
            "fill — audits last run's final DEF and reports spare-cell "
            "survival that this run never established. The dependency cannot "
            "be declared: 21 and 34 are both downstream of 18, so the edge "
            "would close a cycle. The fix belongs in the program (the caller "
            "must name the stage-appropriate DEF), which is why no blocks_on "
            "value can make this cell green."
        ),
        evidence=(
            "programs/spare_cell_preservation_check.py:314-320 `for fname in "
            "(\"filled.def\", \"routed.def\")`; producers "
            "flow/phase1_phase2_phase3.yaml:1673 (step 21 routed.def) and "
            ":2295 (step 34 filled.def); consumer "
            "flow/phase1_phase2_phase3.yaml:1582 (step 18, blocks_on:[17])"
        ),
    ),
    Waiver(
        step_id="A7",
        dim=5,
        reason=(
            "LIVE DEFECT, reproduced: A7 declares blocks_on:[A6] but A6 is "
            "declared at yaml index 52 — after step 39 — while A7 sits at "
            "index 23, so this is the flow's only FORWARD edge. "
            "flow_compliance_check evaluates steps in canonical declaration "
            "order and its #503 cascade attribution walks each track in that "
            "same order taking the first FAIL as the cut point, so an A6 FAIL "
            "is positioned after A7 and can never be attributed as A7's root "
            "cause; A7 reports an independent gap instead of a downstream "
            "consequence. Fixing it means MOVING A6's yaml block between A5 "
            "and A7, an edit to the shared flow document that this module must "
            "not make."
        ),
        evidence=(
            "flow/phase1_phase2_phase3.yaml:1365 (A7, blocks_on:[A6]) vs :2526 "
            "(A6) — A6's declaration index is 52, A7's is 23, measured by "
            "`[str(s['id']) for s in yaml.safe_load(open(flow))['steps']]`; "
            "consumer flow_compliance_check.py:6672-6690 (`for sid in order:`)"
        ),
    ),

    # ── dimension 6 — skip discipline ─────────────────────────────────
    Waiver(
        step_id="FS1",
        dim=6,
        reason=(
            "Both mandatory gate programs self-declare inapplicability and the "
            "step still resolves to a plain PASS. fmeda_fault_injection_"
            "coverage writes verdict='NOT_APPLICABLE' and fmeda_coverage_check "
            "writes verdict='VACUOUS_PASS' into their own --json reports, but "
            "each exits 0 and neither prints a line STARTING with "
            "'VACUOUS_PASS' (fmeda_coverage_check's line starts '[PASS] "
            "fmeda_coverage_check: VACUOUS_PASS ...'), which is the only rc=0 "
            "disclosure channel _check_program_exit_zero reads. "
            "flow_compliance_check's own comment names a JSON top-level "
            "verdict of VACUOUS_PASS as a disclosure channel, but no consumer "
            "ever opens the report file, so the disclosure cannot reach the "
            "tier. FS1's condition is files_exist ['phase2/stage1/rtl'], "
            "satisfied by every design, so a plain PASS on an unmeasured FMEDA "
            "is the DEFAULT outcome for every non-safety chip, not a corner "
            "case."
        ),
        evidence=(
            "programs/flow_compliance_check.py:2182-2196 (the three declared "
            "disclosure channels) vs :2255-2264 (_stdout_signals_vacuous "
            "requires the token at LINE START) and :4796-4816 (no report file "
            "is read). Reproduce: mkdir -p P/phase2/stage1/rtl && python3 "
            "programs/flow_compliance_check.py P --flow-def <one-step FS1 "
            "yaml> --json r.json -> step FS1 status 'PASS'; "
            "P/reports/phase2/safety/fmeda_coverage_gate.json carries "
            "verdict='VACUOUS_PASS'. Measured 2026-07-27 on v1.7.68."
        ),
    ),
    Waiver(
        step_id="30",
        dim=6,
        reason=(
            "spice_correlation_check self-declares summary.skipped=true with "
            "reason='no_spef' and exits 0 with no stdout at all, so step 30 "
            "resolves to a plain PASS. The step's only other gate leg is an "
            "any-of files_exist over SPICE decks (phase3/stage3/spice/*.sp OR "
            "*.spice OR sim_spice/*.sp) — a DIFFERENT artefact from the SPEF "
            "the checker skips on — so the T4 hard-gate backstop that "
            "legitimately protects the structurally identical A3 and A7 skips "
            "does not apply here. A project that ships SPICE decks but no "
            "extracted SPEF passes post-layout SPICE correlation with no "
            "correlation having been measured."
        ),
        evidence=(
            "flow/phase1_phase2_phase3.yaml step 30 gate.all_of[0].files_exist "
            "names the .sp decks, not the .spef. Reproduce: mkdir -p "
            "P/phase3/stage3/spice && touch P/phase3/stage3/spice/x.sp && "
            "python3 programs/flow_compliance_check.py P --flow-def <one-step "
            "30 yaml> --json r.json -> status 'PASS' while "
            "P/reports/phase2/gates/spice_correlation.json carries "
            "{'summary': {'skipped': true, 'reason': 'no_spef'}}. Measured "
            "2026-07-27 on v1.7.68."
        ),
    ),
    Waiver(
        step_id="DT2",
        dim=6,
        reason=(
            "DT2's step-level condition is ALL-of over three paths, two of "
            "which (phase2/stage2/dft/cut_netlist.v and "
            "phase3/stage3/pnr/*_pnr.v) are the very artefacts whose absence "
            "DT2 exists to detect, so the step disappears in exactly the "
            "scenario it was written for. The repo AGREES: "
            "flow_condition_reachability_check classifies it 'self-disabling' "
            "and it is carried in flow_condition_reachability_baseline.json as "
            "a known-open hole owned by vibe-ic#235. That baseline is a proper "
            "machine-readable, owner-attributed disclosure — which is why this "
            "is a waiver and not a silent gap — but a disclosed self-disabling "
            "condition is still a skip that hides its own subject, so the cell "
            "is not enforced-clean."
        ),
        evidence=(
            "flow/flow_condition_reachability_baseline.json (owner: "
            "vibe-ic#235 — 'PRODUCER + CONSUMER halves LANDED; flow-YAML wire "
            "BLOCKED'). Reproduce: python3 "
            "programs/flow_condition_reachability_check.py --json r.json -> "
            "r.json['known_open_holes'][0]['step'] == 'DT2', verdict "
            "'self-disabling', detail names cut_netlist.v and *_pnr.v as the "
            "non-surviving triggers. Measured 2026-07-27 on v1.7.68."
        ),
    ),

    # ── dimension 7 — is the required_outputs list complete? ───────────
    # Six of the nine original entries were CLOSED on 2026-07-28 by declaring
    # the artefact (D1, 21, 25, 28, 31) and, for FS1, by first fixing the
    # flow_compliance_check ordering defect that made declaring impossible.
    # The three below are the residue. Two (7, 23) are blocked on the same
    # thing: `required_outputs` is ALL-of-N with no conditional spelling, so an
    # artefact the flow emits only on one branch of a genuine design/PDK
    # condition cannot be declared without failing the other branch. The third
    # (M1) is blocked on evidence: the artefact exists in no published run root,
    # so declaring it would move the gap from dimension 7 to dimension 3.
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
