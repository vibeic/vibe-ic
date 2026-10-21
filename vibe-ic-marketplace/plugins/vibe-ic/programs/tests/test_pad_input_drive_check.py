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


def _run(project: Path):
    out = subprocess.run([sys.executable, str(PROGRAMS / "pad_input_drive_check.py"),
                          str(project), "--json", "reports/phase3/sta/pad_input_drive_check.json"],
                         capture_output=True, text=True, timeout=120)
    doc = json.loads((project / "reports/phase3/sta/pad_input_drive_check.json").read_text())
    return out.returncode, doc


def _stage_drive(project: Path, analysis_top: str, *, record_state: str = "full",
                 with_drive: bool = True):
    """Stage a design SDC and exercise the exact Step-23 consumer."""
    import flow_compliance_check as FC

    pad_record = project / SE.IO_PAD_RECORD
    if record_state == "absent":
        pad_record.unlink(missing_ok=True)
    else:
        pad = json.loads(pad_record.read_text())
        if record_state in ("full", "stale"):
            pad.update(verdict="WROTE", core_module="neutral_core",
                       chip_top_module="neutral_chip")
        elif record_state != "sparse":
            raise AssertionError(f"unknown pad record state {record_state}")
        pad_record.write_text(json.dumps(pad))
    staged = "create_clock -name c -period 10 [get_ports clk]\n"
    if with_drive:
        staged += "set_input_transition 0.3 [all_inputs]\n"
    text, record = SE.staged_sdc_pad_input_drive(
        project, staged, "input/constraints/neutral.sdc",
        analysis_top=analysis_top)
    SE.write_pad_input_drive_record(project, record)
    deck = project / DECK
    deck.parent.mkdir(parents=True, exist_ok=True)
    deck.write_text(text)
    if record_state == "stale":
        changed = json.loads(pad_record.read_text())
        changed["chip_top_module"] = "different_chip"
        pad_record.write_text(json.dumps(changed))
    rc, gate = _run(project)
    step23 = FC.check_step(project, _step23_only(), {})
    return text, record, rc, gate, step23


def test_step23_declares_the_clause():
    text = FLOW.read_text()
    step23 = text[text.index("\n  - id: 23\n"):text.index("\n  - id: 24")]
    assert f'- program_exit_zero: "{CLAUSE}"' in step23


def test_the_io_tier_carried_by_the_deck_passes(tmp_path):
    project = _die(tmp_path)
    assert _resolve(project)["verdict"] == "PDK_IO_TIER"
    rc, doc = _run(project)
    assert (rc, doc["verdict"]) == (0, "PASS"), doc


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
    rc, doc = _run(project)
    assert (rc, doc["verdict"]) == (0, "PASS"), doc
    assert doc["tool_arm"]
    deck.write_text("create_clock -period 10 clk\n")
    rc, doc = _run(project)
    assert (rc, doc["verdict"]) == (1, "REFUSED")
    assert doc["refusal"] == "LL_STA_INPUT_STALE"


def test_default_tool_arm_cannot_use_a_good_local_deck_for_its_bad_timed_deck(tmp_path):
    project = _die(tmp_path, tool=True)
    _resolve(project)
    timed = project / "phase3/tool_timed.sdc"
    timed.write_text("create_clock -period 10 clk\n")
    _bind_timed_deck(project, timed)
    rc, doc = _run(project)
    assert (rc, doc["verdict"]) == (1, "FAIL"), doc
    assert doc["deck"] == str(timed)
    assert doc["lines_missing"]


def test_a_not_measured_drive_is_rc2_never_pass(tmp_path):
    project = _die(tmp_path, io=False)
    assert _resolve(project)["verdict"] == "NOT_MEASURED"
    rc, doc = _run(project)
    assert (rc, doc["verdict"]) == (2, "NOT_MEASURED")
    assert doc["reason_class"] == "BLOCKED_BY_UPSTREAM"
    assert doc["reason"].startswith("off-chip input drive NOT_MEASURED:")


def test_staged_drive_cannot_override_a_stale_analysis_boundary(tmp_path):
    """Neutral counterexample: an SDC command cannot identify which boundary
    the stale analysis top represents, so actual Step 23 must stay unresolved."""
    text, record, rc, gate, step23 = _stage_drive(
        _die(tmp_path), "neutral_stale_top")
    assert gate["verdict"] == "NOT_MEASURED", gate
    assert record["verdict"] == "NOT_MEASURED", record
    assert rc == 2
    assert step23.status == "NOT_MEASURED"
    assert record["boundary"]["classification"] == "UNKNOWN"
    assert record["refused_staged_sdc_lines"] == [
        "set_input_transition 0.3 [all_inputs]"]
    assert "set_input_transition 0.3 [all_inputs]" not in [
        line.strip() for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")]
    assert "# NOT_MEASURED: OFFCHIP_INPUT_DRIVE" in text


def test_staged_drive_is_declared_at_the_recorded_chip_top(tmp_path):
    """Positive control: the same declaration is admissible at the producer's
    recorded chip boundary and the actual Step-23 gate passes."""
    text, record, rc, gate, step23 = _stage_drive(
        _die(tmp_path), "neutral_chip")
    assert (record["verdict"], rc, gate["verdict"], step23.status) == (
        "DECLARED", 0, "PASS", "PASS")
    assert "set_input_transition 0.3 [all_inputs]" in [
        line.strip() for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")]


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


def test_declared_drive_refuses_a_changed_pad_boundary_record(tmp_path):
    """#3269: a DECLARED line cannot outlive the DIE boundary record whose
    recorded chip top made that declaration applicable."""
    _, record, rc, gate, step23 = _stage_drive(
        _die(tmp_path), "neutral_chip", record_state="stale")
    assert record["verdict"] == "DECLARED"
    assert gate["verdict"] == "NOT_MEASURED", gate
    assert rc == 2
    assert step23.status == "NOT_MEASURED"
    assert "different" in gate["reason"]


@pytest.mark.parametrize("record_state", ["absent", "sparse", "full", "stale"])
@pytest.mark.parametrize("with_drive", [False, True], ids=["no-sdc", "sdc"])
@pytest.mark.parametrize("analysis_top", ["neutral_core", "neutral_chip"],
                         ids=["core", "chip"])
def test_pad_drive_boundary_identity_matrix(
        tmp_path, record_state, with_drive, analysis_top):
    """#3269 invariant matrix over producer identity, SDC tier, and boundary.

    Only a full, unchanged chip identity admits DECLARED/PDK_IO_TIER. A core
    identity is explicitly not a pad boundary; absent, sparse, and stale
    identities remain unresolved at the actual Step-23 consumer.
    """
    _, record, rc, gate, step23 = _stage_drive(
        _die(tmp_path), analysis_top, record_state=record_state,
        with_drive=with_drive)
    complete = record_state in ("full", "stale")
    if not complete:
        producer_verdict = "NOT_MEASURED"
    elif analysis_top == "neutral_core":
        producer_verdict = "NOT_APPLICABLE"
    elif with_drive:
        producer_verdict = "DECLARED"
    else:
        producer_verdict = "PDK_IO_TIER"
    gate_verdict = ("PASS" if record_state == "full"
                    and producer_verdict in ("DECLARED", "PDK_IO_TIER")
                    else "NOT_MEASURED")
    assert gate["verdict"] == gate_verdict, gate
    assert rc == {"PASS": 0, "NOT_MEASURED": 2}[gate_verdict]
    assert step23.status == gate_verdict
    assert record["verdict"] == producer_verdict, record


def test_an_absent_record_on_a_die_is_rc2(tmp_path):
    rc, doc = _run(_die(tmp_path))
    assert (rc, doc["verdict"]) == (2, "NOT_MEASURED")


def test_a_deck_without_the_resolved_drive_fails(tmp_path):
    """The step-7 ideal-edge deck reused after the ring exists (the BLOCKER
    shape): the record says PDK_IO_TIER, the deck carries no drive."""
    project = _die(tmp_path)
    _resolve(project)
    (project / DECK).write_text("create_clock -name c -period 10 [get_ports clk]\n")
    rc, doc = _run(project)
    assert (rc, doc["verdict"]) == (1, "FAIL")
    assert len(doc["lines_missing"]) == len(json.loads(
        (project / SE.PAD_INPUT_DRIVE_REPORT).read_text())["sdc_lines"])


def test_a_deck_that_drives_pads_with_the_core_cell_fails(tmp_path):
    project = _die(tmp_path)
    _resolve(project, "set_driving_cell -lib_cell quartz_sc__inv_1 -pin ZN [all_inputs]\n")
    rc, doc = _run(project)
    assert (rc, doc["verdict"]) == (1, "FAIL")
    assert doc["core_driving_cell_lines"]


def test_a_drive_resolved_from_an_older_pad_ring_record_is_rc2(tmp_path):
    project = _die(tmp_path)
    _resolve(project)
    rec = project / SE.IO_PAD_RECORD
    rec.write_text(rec.read_text().replace("]}", "], \"verdict\": \"WROTE\"}"))
    rc, doc = _run(project)
    assert (rc, doc["verdict"]) == (2, "NOT_MEASURED")
    assert "different" in doc["reason"]


def test_an_absent_signoff_deck_is_rc2(tmp_path):
    project = _die(tmp_path)
    _resolve(project, write_deck=False)
    rc, doc = _run(project)
    assert (rc, doc["verdict"]) == (2, "NOT_MEASURED")


def _step23_only():
    import yaml
    step = next(s for s in yaml.safe_load(FLOW.read_text())["steps"]
                if str(s.get("id")) == "23")
    clause = [c for c in step["gate"]["all_of"]
              if isinstance(c, dict) and c.get("program_exit_zero") == CLAUSE]
    assert len(clause) == 1
    return dict(step, required_outputs=[], gate={"all_of": clause})


def test_control_a_core_top_is_decided_not_applicable(tmp_path):
    """No pad ring requested anywhere: NOT_APPLICABLE_BY_STRUCTURE with the
    enumeration the route predicate consulted, which Step 23 counts as
    decided (an IP/core run must not be blocked by this clause)."""
    import flow_compliance_check as FC
    project = tmp_path / "core"
    project.mkdir()
    rc, doc = _run(project)
    assert (rc, doc["verdict"]) == (0, "NOT_APPLICABLE")
    assert doc["reason_class"] == "NOT_APPLICABLE_BY_STRUCTURE"
    assert doc["structural_absence"]["scanned"] == 2
    assert FC.check_step(project, _step23_only(), {}).status == "PASS"


def test_control_an_attested_hardmacro_is_decided_not_applicable(tmp_path):
    """The IP route: a slot catalogue is staged, but the owner-attested
    declaration says HARDMACRO, so no pad ring exists."""
    import _owner_declared as OD
    import flow_compliance_check as FC
    project = tmp_path / "ip"
    slots = project / TD.SLOTS_REL
    slots.mkdir(parents=True)
    (slots / "s.yaml").write_text("slot: catalogue entry\n")
    (project / TD.DECLARATION_REL).write_text(json.dumps(OD.attest(
        {"schema": "vibe-ic/tapeout_declaration/1",
         "answers": {"deliverable": "HARDMACRO", "top_cell": "t",
                     "pad_order_by_side": "NOT_DETERMINED"}})) + "\n")
    assert TD.requests_pad_ring(project) is False
    rc, doc = _run(project)
    assert (rc, doc["verdict"]) == (0, "NOT_APPLICABLE")
    assert doc["structural_absence"]["scanned_names"] == [TD.DECLARATION_REL]
    assert FC.check_step(project, _step23_only(), {}).status == "PASS"


def test_flow_compliance_grades_step23_on_the_clause(tmp_path):
    """flow_compliance_check.check_step over Step 23 as the yaml declares it,
    reduced to this clause (the other clauses need a routed run): an
    unresolved drive leaves Step 23 NOT_MEASURED, never PASS; a resolved one
    carried by the deck lets the clause pass."""
    import flow_compliance_check as FC
    bad = _die(tmp_path / "a", io=False)
    _resolve(bad)
    assert FC.check_step(bad, _step23_only(), {}).status == "NOT_MEASURED"
    good = _die(tmp_path / "b")
    _resolve(good)
    res = FC.check_step(good, _step23_only(), {})
    assert res.status == "PASS", res.reasons
