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

# `_sidecar` is IMPORTED, not redefined. It is the only place the answer to
# "what does this netlist contain?" exists, and two copies of it in two test
# files is two chances for the fixtures to drift apart on the one field this
# whole change turns on.
from test_a4_consumes_design_netlist import (      # noqa: E402
    _project, _sweep, _record, _decks_on_disk, _sidecar,
    STRUCTURE_ONLY, SIZED)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


def _run(prog: Path, project: Path, *args) -> subprocess.CompletedProcess:
    return _pr.run([sys.executable, str(prog), str(project), *args],
                          capture_output=True, text=True)


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
