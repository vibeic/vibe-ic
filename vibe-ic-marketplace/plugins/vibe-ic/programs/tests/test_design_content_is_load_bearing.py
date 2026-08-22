"""test_design_content_is_load_bearing.py — a field nobody reads is silence.

WHAT WAS ALREADY TRUE, AND WHY IT WAS NOT ENOUGH
================================================
The netlist producer already recorded, accurately, that a netlist's circuit
class came from a topology library and that NO bound spec value reached any
device parameter (`design_content: structure_only`). It wrote that down and
nothing downstream read it. So a corner result rendered from a library
topology was byte-indistinguishable, in every field a consumer grades, from
one rendered from a design sized against its spec — and the summary line a
reviewer actually reads could not tell them apart at all.

That is the same defect one layer up. Before, `_provenance: real_ngspice` was
true of the simulator and silent about the subject. A field nobody reads is
that silence with more words.

THE RULE UNDER TEST, with no tool, step or block name in it:

    An artefact derived from another artefact inherits the upstream record of
    what that artefact CONTAINS, and republishes it. A step that produced its
    declared artefact from a library default, because no bound input
    determined its content, is neither complete nor absent: it is
    dispositioned in its own tier, never counted as a pass, never counted as
    missing, and its count is printed on the one summary line a reader reads.

Every assertion is on bytes on disk, on the rc of a shipped gate, or on the
LINE a shipped gate prints. Fixtures are synthetic throughout.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

A4_GATE = PROGRAMS / "analog_a4_corner_sweep_check.py"
A3_GATE = PROGRAMS / "analog_a3_netlist_gen_check.py"
ANALOG_COMPLIANCE = PROGRAMS / "analog_flow_compliance_check.py"
FLOW_COMPLIANCE = PROGRAMS / "flow_compliance_check.py"

# `_sidecar` is IMPORTED, not redefined. It is the only place the answer to
# "what does this netlist contain?" exists, and two copies of it in two test
# files is two chances for the fixtures to drift apart on the one field this
# whole change turns on.
from test_a4_consumes_design_netlist import (      # noqa: E402
    _project, _sweep, _record, _decks_on_disk, _sidecar,
    STRUCTURE_ONLY, SIZED)


def _run(prog: Path, project: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(prog), str(project), *args],
                          capture_output=True, text=True, timeout=60)


# ═══ 1. the sweep republishes what its netlist said it contained ═══════════

@pytest.mark.parametrize("declared", [STRUCTURE_ONLY, SIZED])
def test_the_corner_result_republishes_the_design_content_of_its_netlist(
        tmp_path, monkeypatch, declared):
    """Parametrised on purpose: a field that is always the same string is not
    carrying information. The two runs differ ONLY in the upstream record."""
    S = _sweep(monkeypatch)
    project = _project(tmp_path, [("blk_alpha", "ldo")],
                       netlist=("blk_alpha",), testbench=("blk_alpha",))
    _sidecar(project, "blk_alpha", declared)

    assert S.run_block(project, "blk_alpha", "fake", "sky130", "auto") == 0, (
        "PRECONDITION: the sweep must have completed over the delivered "
        "netlist, or every assertion below is also true of a tree where "
        "nothing ran")

    rec = _record(project, "blk_alpha")
    assert rec.get("design_content") == declared, (
        f"the corner result records design_content="
        f"{rec.get('design_content')!r} while the netlist it was rendered "
        f"from records {declared!r}. A corner result that does not carry it "
        f"reads as design-traceable-and-sized whatever the netlist was.")
    assert rec.get("design_content_meaning"), (
        "the value is a token; a reader needs the sentence too")
    assert (rec.get("design_content_source") or "").endswith(
        "netlist_provenance.json"), (
        "the record must name WHERE it inherited the answer from, or a "
        "reader cannot check it")


def test_every_deck_on_disk_says_what_circuit_it_carries(
        tmp_path, monkeypatch):
    """A deck read on its own, years later, out of context."""
    S = _sweep(monkeypatch)
    project = _project(tmp_path, [("blk_alpha", "ldo")],
                       netlist=("blk_alpha",), testbench=("blk_alpha",))
    _sidecar(project, "blk_alpha", STRUCTURE_ONLY)
    assert S.run_block(project, "blk_alpha", "fake", "sky130", "auto") == 0

    decks = _decks_on_disk(project, "blk_alpha")
    assert decks, "PRECONDITION: no deck reached disk"
    for d in decks:
        head = d.read_text()[:1200]
        assert f"* design_content: {STRUCTURE_ONLY}" in head, (
            f"{d.name} says where its circuit came from and not what is in "
            f"it:\n{head[:400]}")


def test_the_sizing_loop_record_carries_it_too(tmp_path, monkeypatch):
    """Every artefact derived from the deck, not only the headline one."""
    S = _sweep(monkeypatch)
    project = _project(tmp_path, [("blk_alpha", "ldo")],
                       netlist=("blk_alpha",), testbench=("blk_alpha",))
    _sidecar(project, "blk_alpha", STRUCTURE_ONLY)
    assert S.run_block(project, "blk_alpha", "fake", "sky130", "auto") == 0
    sl = json.loads((project / "phase3" / "analog" / "blk_alpha"
                     / "sizing_loop" / "results.json").read_text())
    assert sl.get("design_content") == STRUCTURE_ONLY, sl


def test_a_refusal_records_no_design_content_rather_than_omitting_the_field(
        tmp_path, monkeypatch):
    """The negative control for the field itself: a run that measured nothing
    must SAY it contains nothing, not leave the field absent — an absent field
    is exactly the silence this change closes."""
    S = _sweep(monkeypatch)
    project = _project(tmp_path, [("blk_alpha", "ldo")])   # no netlist at all
    assert S.run_block(project, "blk_alpha", "fake", "sky130", "auto") == 2
    rec = _record(project, "blk_alpha")
    assert rec["status"] == "BLOCKED", "PRECONDITION: expected a refusal"
    assert rec.get("design_content") == "none", rec


# ═══ 2. the gate refuses to certify an artefact that will not say ═════════

def test_a4_will_not_certify_a_deck_that_declines_to_say_what_it_contains(
        tmp_path, monkeypatch):
    """`netlist_provenance: a3_netlist` says WHERE the deck came from. Silence
    about WHAT IS IN IT is not evidence of design content."""
    S = _sweep(monkeypatch)
    project = _project(tmp_path, [("blk_alpha", "ldo")],
                       netlist=("blk_alpha",), testbench=("blk_alpha",))
    _sidecar(project, "blk_alpha", STRUCTURE_ONLY)
    assert S.run_block(project, "blk_alpha", "fake", "sky130", "auto") == 0

    # PRECONDITION — the gate certifies this artefact as it stands.
    ok = _run(A4_GATE, project, "--block", "blk_alpha")
    assert ok.returncode == 0, ok.stdout + ok.stderr

    # Now remove ONLY the statement of content. Nothing else changes.
    crp = project / "phase3" / "analog" / "blk_alpha" / "corner_results.json"
    rec = json.loads(crp.read_text())
    rec.pop("design_content", None)
    rec.pop("design_content_meaning", None)
    crp.write_text(json.dumps(rec, indent=2))

    cp = _run(A4_GATE, project, "--block", "blk_alpha")
    assert cp.returncode == 1, (
        f"the gate certified a corner result that claims a design-derived "
        f"deck and refuses to say what is in it (rc={cp.returncode})")
    assert "A4_DESIGN_CONTENT_UNDECLARED" in (cp.stdout + cp.stderr)


def test_structure_only_is_not_a_failure(tmp_path, monkeypatch):
    """The disposition, from the side that would be easy to get wrong. A
    library default is the honest ceiling where the bounded inputs do not
    determine the content; failing it would teach the next run to stop being
    honest."""
    S = _sweep(monkeypatch)
    project = _project(tmp_path, [("blk_alpha", "ldo")],
                       netlist=("blk_alpha",), testbench=("blk_alpha",))
    _sidecar(project, "blk_alpha", STRUCTURE_ONLY)
    assert S.run_block(project, "blk_alpha", "fake", "sky130", "auto") == 0
    cp = _run(A4_GATE, project, "--block", "blk_alpha")
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "STRUCTURE_ONLY:" in cp.stdout, (
        "the gate passed and said nothing about what it certified")


# ═══ 3. THE LINE — the proof a reader needs no JSON file ══════════════════

def _matrix_project(tmp_path, design_content: str,
                    waive_rest: bool = False) -> Path:
    """One declared block with A3 + A4 artefacts present, differing ONLY in
    the recorded design content. `waive_rest` waives the A-steps this fixture
    does not produce, so the gate reaches its PASS tier and the VERDICT WORD
    itself becomes observable."""
    root = tmp_path / f"proj_{design_content}_{int(waive_rest)}"
    adir = root / "phase3" / "analog" / "blk_alpha"
    adir.mkdir(parents=True, exist_ok=True)
    (root / "phase3" / "analog" / "analog_block_list.json").write_text(
        json.dumps({"blocks": [{"name": "blk_alpha", "type": "ldo"}]}))
    (adir / "spec.json").write_text(json.dumps({"block": "blk_alpha"}))
    (adir / "topology.md").write_text("# topology\n")
    (adir / "blk_alpha.sp").write_text(
        "* blk_alpha — synthetic block netlist for this fixture\n"
        "* every geometry below is a library nominal, on purpose\n"
        ".option scale=1u\n"
        ".lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice tt\n"
        ".subckt blk_alpha vdd vss vref vout\n"
        "xm1 vout vref vss vss sky130_fd_pr__nfet_01v8 w=5 l=2\n"
        "xm2 vout vref vdd vdd sky130_fd_pr__pfet_01v8 w=9 l=2\n"
        ".ends blk_alpha\n")
    _sidecar(root, "blk_alpha", design_content)
    (adir / "corner_results.json").write_text(json.dumps({
        "block": "blk_alpha", "netlist_provenance": "a3_netlist",
        "design_traceable": True, "design_content": design_content,
        "_provenance": "real_ngspice",
        "corners": [{"name": "tt_27C", "simulator_run": True, "vout": 1.8}],
        "spec_results": [{"name": "vout", "status": "PASS", "target": None}],
    }, indent=2))
    if waive_rest:
        (root / "phase3" / "analog" / "waivers.json").write_text(json.dumps({
            "analog_waivers": [{"block": "blk_alpha", "step": s,
                                "reason": "not produced by this fixture"}
                               for s in ("A5", "A6", "A7", "A8", "A9")]}))
    return root


def test_the_matrix_gives_a_library_default_its_own_cell(tmp_path):
    """Not PASS (a pass would say the artefact is design-bound), not MISSING
    (it exists and re-running produces the same one)."""
    root = _matrix_project(tmp_path, STRUCTURE_ONLY)
    out = tmp_path / "m.json"
    _run(ANALOG_COMPLIANCE, root, "--json", str(out))
    m = json.loads(out.read_text())["summary"]["matrix"]["blk_alpha"]
    assert m["A3"] == "PASS_STRUCTURE_ONLY", m
    assert m["A4"] == "PASS_STRUCTURE_ONLY", m
    assert m["A5"] == "MISSING", (
        "PRECONDITION: an obligation that really is unmet must still read "
        "MISSING, or the new cell has simply replaced the old one")


def test_a_reader_of_the_line_alone_can_tell_the_two_apart(tmp_path):
    """THE NEGATIVE CONTROL, and the proof the task asks for.

    Two trees identical in every artefact except the one recorded value. If
    the two printed LINES are equal, the distinction does not exist for anyone
    who does not open a JSON file."""
    so = _run(ANALOG_COMPLIANCE, _matrix_project(tmp_path, STRUCTURE_ONLY))
    sized = _run(ANALOG_COMPLIANCE, _matrix_project(tmp_path, SIZED))

    line_so = so.stdout.splitlines()[0]
    line_sized = sized.stdout.splitlines()[0]
    assert line_so != line_sized, (
        f"a structure-only A3 and a designed A3 print the SAME compliance "
        f"line:\n  {line_so}")
    assert "STRUCTURE-ONLY=2" in line_so, line_so
    assert "STRUCTURE-ONLY" not in line_sized, line_sized


def test_the_verdict_word_on_the_line_is_not_a_bare_pass(tmp_path):
    """Same two trees with the unproduced steps waived, so the gate reaches
    its PASS tier. `PASS` alone would say the artefacts are design-bound."""
    so = _run(ANALOG_COMPLIANCE,
              _matrix_project(tmp_path, STRUCTURE_ONLY, waive_rest=True))
    sized = _run(ANALOG_COMPLIANCE,
                 _matrix_project(tmp_path, SIZED, waive_rest=True))
    line_so = so.stdout.splitlines()[0]
    line_sized = sized.stdout.splitlines()[0]
    assert line_sized.startswith("[PASS]"), line_sized     # PRECONDITION
    assert line_so.startswith("[PASS_STRUCTURE_ONLY]"), line_so
    # ...and it is still not a failure: an honest ceiling must not score
    # below a run that invented content to fill the gap.
    assert so.returncode == 0, so.stdout + so.stderr


def test_the_flow_compliance_line_carries_the_tier(tmp_path):
    """The same proof one layer up, on the line the 63-step gate prints."""
    root = _matrix_project(tmp_path, STRUCTURE_ONLY)
    (root / "phase1" / "analog").mkdir(parents=True, exist_ok=True)
    (root / "phase1" / "analog" / "analog_block_list.json").write_text(
        (root / "phase3" / "analog" / "analog_block_list.json").read_text())
    cp = _run(FLOW_COMPLIANCE, root)
    tally = [l for l in cp.stdout.splitlines() if l.startswith("  PASS=")]
    assert tally, cp.stdout[:2000]
    assert "STRUCTURE-ONLY=" in tally[0], (
        f"the 63-step compliance line cannot tell a step that produced a "
        f"library default from one that produced a design-bound artefact:\n"
        f"  {tally[0]}")
    step = [l for l in cp.stdout.splitlines() if "Step A3:" in l]
    assert step and "STRUCTURE-ONLY" in step[0], step
