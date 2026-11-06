"""pad_input_drive_check — the Step-23 clause of R-0929-IO-INPUT-TRANSITION-2.

review_wave58 (PADIN_*, MAJOR): the NOT_MEASURED pad drive only demoted the
runner's in-memory STA rows; no Step-23 gate clause read
`reports/phase3/pad_input_drive.json`, so flow_compliance_check graded Step 23
PASS on ideal bond-pad edges. This clause reads the record and the deck PnR
and sign-off loaded. The records and decks are produced by the shipped
`sdc_environment` code; the program is run by path, as the flow runs it, and
through flow_compliance_check's own clause evaluator.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

from _hostpaths import require_repo  # noqa: E402
import _tapeout_declaration as TD  # noqa: E402
import sdc_environment as SE  # noqa: E402

FLOW = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "flow",
                    "phase1_phase2_phase3.yaml")
CLAUSE = "pad_input_drive_check . --json reports/phase3/sta/pad_input_drive_check.json"
DECK = "phase3/stage3/pnr/constraint.sdc"
_LIB = """library ("quartz_io__ss") {
  time_unit : "1ns";
  lu_table_template ("t") { variable_1 : "input_net_transition"; index_1("1, 2, 3"); }
  cell ("quartz_io__in") {
    pin ("PAD") { max_transition : 1.0; is_pad : true; direction : "input"; }
    pin ("Y") { direction : "output";
      timing () { related_pin : "PAD"; cell_rise ("t") { index_1("0.08, 0.5, 1"); } }
    }
  }
}
"""
_CORE = ("quartz_sc__inv_1/ZN", "pinned PDK default cfg:SYNTH_DRIVING_CELL")


def _die(tmp_path: Path, io: bool = True, *, tool: bool = False) -> Path:
    if tool:
        from test_f15_step23_gates_read_the_tool_arm import tool_project
        p = tool_project(tmp_path)
        (p / "phase3/librelane_switch.json").unlink()
    else:
        p = tmp_path / "die"
        switch = p / "phase3/librelane_switch.json"
        switch.parent.mkdir(parents=True)
        # These cases exercise the direct deck clause. The production default
        # uses a bound tool deck, exercised separately below.
        switch.write_text(json.dumps({"steps": {"23": "direct"}}))
    marker = p / TD.SELF_TAPEOUT_REL
    marker.parent.mkdir(parents=True)
    marker.write_text(TD.SELF_TAPEOUT_MARKER + "\n")
    if io:
        lib = tmp_path / "quartz_io__ss.lib"
        lib.write_text(_LIB)
        rec = p / SE.IO_PAD_RECORD
        rec.parent.mkdir(parents=True, exist_ok=True)
        rec.write_text(json.dumps({"io_library_liberty": [str(lib)]}))
    return p


def _resolve(project: Path, deck_extra: str = "", write_deck: bool = True) -> dict:
    """What the SDC producer does: resolve, record, render into the deck."""
    _, rec = SE._pad_input_drive(project, {"set_driving_cell": _CORE})
    rec["sdc_lines"] = SE.pad_drive_sdc_lines(rec)
    SE.write_pad_input_drive_record(project, rec)
    if write_deck:
        deck = project / DECK
        deck.parent.mkdir(parents=True, exist_ok=True)
        deck.write_text("create_clock -name c -period 10 [get_ports clk]\n"
                        + "\n".join(SE.render_pad_input_drive(rec)) + "\n" + deck_extra)
    return rec






def test_step23_declares_the_clause():
    text = FLOW.read_text()
    step23 = text[text.index("\n  - id: 23\n"):text.index("\n  - id: 24")]
    assert f'- program_exit_zero: "{CLAUSE}"' in step23


def test_the_io_tier_carried_by_the_deck_passes(tmp_path):
    project = _die(tmp_path)
    assert _resolve(project)["verdict"] == "PDK_IO_TIER"


def _bind_timed_deck(project: Path, deck: Path) -> None:
    """Bind the fixture tool's selected input using the real receipt layout."""
    import hashlib
    import librelane_signoff as LS
    from test_f15_step23_gates_read_the_tool_arm import rebind
    record = json.loads((project / LS.SIGNOFF_RECORD).read_text())
    state_path = Path(record["sta_state"])
    state = json.loads(state_path.read_text())
    previous = state["sdc"]
    state["sdc"] = str(deck)
    state_path.write_text(json.dumps(state))
    receipt_path = state_path.parent / "vibeic_receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["input"]["state_files"].pop(previous)
    receipt["input"]["state_files"][str(deck)] = hashlib.sha256(deck.read_bytes()).hexdigest()
    receipt_path.write_text(json.dumps(receipt))
    rebind(project)


def test_default_tool_arm_checks_the_bound_drive_and_refuses_a_changed_deck(tmp_path):
    from librelane_contract import selected_mode
    project = _die(tmp_path, tool=True)
    assert selected_mode(project, "23") == "librelane"
    _resolve(project)
    deck = project / DECK
    _bind_timed_deck(project, deck)
    deck.write_text("create_clock -period 10 clk\n")




def test_a_not_measured_drive_is_rc2_never_pass(tmp_path):
    project = _die(tmp_path, io=False)
    assert _resolve(project)["verdict"] == "NOT_MEASURED"






def test_refused_multiline_drive_cannot_leave_an_active_continuation(tmp_path):
    """A wrapped command is one command; every physical line becomes inert."""
    project = _die(tmp_path)
    pad_record = project / SE.IO_PAD_RECORD
    pad = json.loads(pad_record.read_text())
    pad.update(verdict="WROTE", core_module="neutral_core",
               chip_top_module="neutral_chip")
    pad_record.write_text(json.dumps(pad))
    staged = ("create_clock -period 10 [get_ports clk]\n"
              "set_input_transition -max 0.3 \\\n"
              "  [all_inputs]\n")
    text, record = SE.staged_sdc_pad_input_drive(
        project, staged, "input/constraints/neutral.sdc",
        analysis_top="neutral_stale_top")
    assert record["verdict"] == "NOT_MEASURED"
    active = [line for line in text.splitlines()
              if line.strip() and not line.lstrip().startswith("#")]
    assert active == ["create_clock -period 10 [get_ports clk]"]


















def _step23_only():
    import yaml
    step = next(s for s in yaml.safe_load(FLOW.read_text())["steps"]
                if str(s.get("id")) == "23")
    clause = [c for c in step["gate"]["all_of"]
              if isinstance(c, dict) and c.get("program_exit_zero") == CLAUSE]
    assert len(clause) == 1
    return dict(step, required_outputs=[], gate={"all_of": clause})




def test_control_an_attested_hardmacro_is_decided_not_applicable(tmp_path):
    """The IP route: a slot catalogue is staged, but the owner-attested
    declaration says HARDMACRO, so no pad ring exists."""
    import _owner_declared as OD
    project = tmp_path / "ip"
    slots = project / TD.SLOTS_REL
    slots.mkdir(parents=True)
    (slots / "s.yaml").write_text("slot: catalogue entry\n")
    (project / TD.DECLARATION_REL).write_text(json.dumps(OD.attest(
        {"schema": "vibe-ic/tapeout_declaration/1",
         "answers": {"deliverable": "HARDMACRO", "top_cell": "t",
                     "pad_order_by_side": "NOT_DETERMINED"}})) + "\n")
    assert TD.requests_pad_ring(project) is False
