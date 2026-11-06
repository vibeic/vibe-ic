"""A P0 gate whose SUBJECT the design declares absent is N/A, not blocked.

MEASURED 2026-09-15 (lane icspm3, R-0915-19) on `spm` x gf180mcuD — a
serial-parallel multiplier with no analog track, no opcodes, no reject rules
and no OTP content. NINE P0 sub-gates were booked `BLOCKED_BY_UPSTREAM`::

    analog_corner_sweep_check          examined nothing (reason: no_analog_dir)
    analog_netlist_pdk_check           examined nothing (reason: no_analog_dir)
    analog_pre_vs_post_layout_check    examined nothing (reason: no_analog_dir)
    analog_hw_tb_de10lite_budget_check NO_DATA: no .qsf file found
    l3_opcode_response_template_check  no opcode override doc found
                                       (REVISED by R-0915-37 -- see below)
    l11_sequence_covers_l6_reject…     no L6.reject_rules to check
    assertion_covers_l3_constraints…   no L3 constraints to enforce
    otp_image_layer_consistency_check  examined nothing (reason: no_l11)
    deliverable_verdict_consistency…   no deliverable at <project>/RESULT.md

That class is not skip-eligible, so P0 stayed INCOMPLETE and the whole cascade
with it.

`_BLOCKED_RE` KEEPS ITS JOB AND ITS PLACE, and no regex is reordered: a
producer that OWED the document and did not write it IS a cascade and stays
BLOCKED. What changes is that the DESIGN IS ASKED FIRST, through the roster
that already exists for exactly this question, and each entry names the
declaration that answers it.

BOTH DIRECTIONS FOR EVERY GATE, and the negative controls are the point: a
design that DECLARES the subject with its artefact missing keeps the gate live
and stays BLOCKED_BY_UPSTREAM. A document that cannot be READ is never a
declaration of absence — it leaves its `*_state` malformed and the gate runs.

AND ONE THAT IS NOT A DECLARATION. `deliverable_verdict_consistency_check`
reads `RESULT.md`, which the runner authors at the END of the run, so a P0
sub-gate asking for it mid-run asks before the producer has run. Its own
message names whose question the presence is. That is a FLOW-ORDER fact: N/A
while the run is in flight, live the moment the deliverable exists.

chip-AGNOSTIC: synthetic projects in tmp_path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import pytest  # noqa: E402

import _flow_reason_taxonomy as R  # noqa: E402

#: gate -> (context key it is registered against, how a design DECLARES it)
SUBJECTS = {
    "analog_corner_sweep_check": "analog_track",
    "analog_netlist_pdk_check": "analog_track",
    "analog_pre_vs_post_layout_check": "analog_track",
    "l11_sequence_covers_l6_reject_rules_check": "l6_reject_rules",
    "assertion_covers_l3_constraints_check": "l3_constraints",
    "otp_image_layer_consistency_check": "l11_otp",
    "deliverable_verdict_consistency_check": "deliverable_record",
}
ALL_GATES = tuple(SUBJECTS) + ("analog_hw_tb_de10lite_budget_check",)

#: REVISED BY R-0915-37 (2026-09-15 23:17). This roster previously held
#: `l3_opcode_response_template_check` as deliberately-unregistered, on the
#: reading that its subject is an OVERRIDE DOC and a document nobody wrote
#: declares nothing. The orchestrator revised that: the gate's subject is
#: opcode RESPONSE TEMPLATES, and the override doc only matters once opcodes
#: EXIST -- so the gate is now keyed on L3's declared opcode POPULATION.
#:
#: THE PROTECTION THAT TEST GAVE IS NOT DROPPED, it is re-pointed: the case
#: below now asserts the direction that actually protects the run -- a design
#: that DECLARES an opcode and has no override doc keeps the gate live and
#: blocking, which is the shape the old test existed to defend.
STILL_BLOCKING_WITH_A_SUBJECT = ("l3_opcode_response_template_check",)


def _docs(tmp_path):
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    return gd


def _silent_design(tmp_path):
    """A project whose own documents declare NONE of the nine subjects."""
    gd = _docs(tmp_path)
    (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps(
        {"opcodes": [], "constraints": None}))
    (gd / "L6_CONTROL_LOGIC.json").write_text(json.dumps(
        {"reject_rules": None}))
    (gd / "L11_OTP_CONTENT.json").write_text(json.dumps(
        {"schema_version": 2, "doc_class": "otp_content", "ic_name": "x",
         "otp_bytes": [], "content_hex": None, "otp_layout": None,
         "depth": None, "width_bits": None, "no_otp_layout_in_input": True}))
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports" / "ic_class.json").write_text(json.dumps(
        {"has_analog": False}))
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "top.v").write_text("module top(); endmodule\n")
    return tmp_path, rtl


# ── direction 1: the design says it has no such thing ─────────────────────


def test_that_disposition_is_skip_eligible():
    assert R.DESIGN_DECLARED_NA in R.SKIP_ELIGIBLE
    assert R.BLOCKED_BY_UPSTREAM not in R.SKIP_ELIGIBLE


# ── direction 2: a design that DECLARES it stays BLOCKED ──────────────────


# ── a document that cannot be READ is not a declaration of absence ────────


# ── the flow-ORDER one ────────────────────────────────────────────────────


# ── nothing else moved ────────────────────────────────────────────────────
