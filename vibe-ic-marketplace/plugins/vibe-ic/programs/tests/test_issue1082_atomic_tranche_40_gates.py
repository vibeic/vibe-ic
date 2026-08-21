"""The 40-gate tranche of vibe-ic#1082, pinned so it cannot be undone quietly.

PR #1094 built the `_atomic_artefact` helper, PR #1110 built the gate and the
residual ratchet. Neither of those is what the issue asks for on its own — the
issue asks that a declared output appear under its final name only once it is
complete, and after #1110 there were still 565 programs for which that was not
true. This tranche converts 40 of them and pulls the ratchet down to match.

WHY THESE 40. Every one is a `*_check.py` — a verdict-bearing gate whose report
is the artefact a `required_outputs` / `check_step` consumer opens. That is the
population the issue is about: a truncated scratch file lies to nobody, while a
truncated gate report is read downstream as the step's own evidence. Files
whose offending site is `open(..., 'w')` were deliberately left out rather than
converted sloppily; they need the `writing()` context manager and a different
edit shape, and 95 files were skipped on that basis (counted, not hidden).

WHY THE BASELINE MOVES TOO. `--strict` fails only when the residual GREW, so a
converted tree passes whether or not the recorded number follows it down.
Leaving it at 565 would have left a 40-slot hole through which all forty could
return with the ratchet still green. The recorded number has to follow the tree
down or it stops ratcheting.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import atomic_artifact_write_check as G  # noqa: E402

PROGRAMS = Path(__file__).resolve().parent.parent
BASELINE = PROGRAMS / "_atomic_artefact_residual.json"

#: Derived by `atomic_artifact_write_check --json` on PR #1110's tree and
#: pinned here, so a later edit that puts one back fails by NAME rather than
#: only shifting a count someone has to notice.
TRANCHE = [
    "acceptance_control_check", "agent_report_presence_check",
    "agent_report_sha256_attestation_check", "analog_a8_before_floorplan_check",
    "analog_artefact_substance_check", "analog_block_coverage_check",
    "analog_corner_margin_check", "analog_corner_sweep_check",
    "analog_digital_interface_check", "analog_flow_compliance_check",
    "analog_hardmacro_check", "analog_hardmacro_pinname_consistency_check",
    "analog_hil_convergence_log_check", "analog_hil_iteration_cap_check",
    "analog_hil_report_schema_check", "analog_hil_single_knob_check",
    "analog_hw_spice_correlation_check", "analog_hw_tb_de10lite_budget_check",
    "analog_lef_gds_outline_check", "analog_liberty_nonzero_delay_check",
    "analog_netlist_connectivity_check", "analog_netlist_include_order_check",
    "analog_netlist_pdk_check", "analog_per_block_pv_completeness_check",
    "analog_pre_vs_post_layout_check", "analog_tb_supply_pdk_check",
    "arith_ss_corner_risk_check", "assertion_property_check",
    "atomic_artifact_write_check", "backlog_sanitize_check",
    "behavioral_evidence_per_spec_item_check", "benchmark_clean_room_check",
    "bit_count_modulo_check", "bit_level_full_stack_tb_oracle_check",
    "break_framing_vs_l3_check", "break_handler_safety_check",
    "buffer_occupancy_flag_latency_check", "canonical_path_symlink_forbid_check",
    "cdc_async_input_check", "cdc_crossing_check",
]


def test_the_forty_gate_tranche_is_converted():
    """Each named gate writes its declared report destination atomically."""
    still = {s: G.scan_program(PROGRAMS / f"{s}.py") for s in TRANCHE}
    assert not any(still.values()), {k: v for k, v in still.items() if v}


def test_the_gate_itself_is_not_exempt():
    """`atomic_artifact_write_check.py` is in its own residual list on #1110's
    tree. A gate that exempts itself from the rule it enforces is the shape
    this repo keeps paying for, so it is converted with the rest and named
    here rather than left to be noticed."""
    assert "atomic_artifact_write_check" in TRANCHE
    assert not G.scan_program(PROGRAMS / "atomic_artifact_write_check.py")


def test_the_recorded_baseline_followed_the_tree_down():
    """The ratchet tightened. Without this, `--strict` would still pass with a
    40-slot hole in it, because it only ever fails on growth."""
    doc = json.loads(BASELINE.read_text())
    recorded = set(doc["offenders"])
    # MAY ONLY SHRINK, not "is exactly 525". The register states that contract
    # itself ("this list may only get shorter"), and an equality here encodes a
    # MOMENT instead: every sibling PR that converts more programs makes it
    # stale. Measured — this PR closes the `open(..., 'w')` category over 10
    # programs and takes the register 525 -> 515, so the equality failed on the
    # composed chain while every conversion in it was correct.
    #
    # The bound is kept, not dropped. Padding the register still fails here,
    # which is the direction this assertion exists to catch: a 40-slot hole
    # left behind by the tranche would show up as a register that did NOT
    # shrink. The per-name loop below is what proves the tranche's own 40 left.
    assert len(recorded) <= 525, len(recorded)
    for s in TRANCHE:
        assert f"{s}.py" not in recorded, f"{s} converted but still recorded as residual"


def test_no_new_offender_and_the_ratchet_holds():
    assert G.main([str(PROGRAMS)]) == 0
    assert G.main([str(PROGRAMS), "--strict"]) == 0
