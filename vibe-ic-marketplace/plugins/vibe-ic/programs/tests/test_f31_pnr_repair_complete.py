"""F31: step 17's `pnr_timing_repair_completeness_check` judges timing sessions,
not every file that matches `pnr*.tcl`.

Measured on spm (run23, direct) and on the LibreLane 15->20 chain: the gate ran
in directory mode on `phase3/stage3/pnr` and FAILED on two decks that place and
optimise nothing:

  * `pnr_antenna_isolated_retry.tcl` (v1.24.64, #2626): the scoped antenna ECO.
    It restores the routed pre-repair ODB, runs `repair_antennas` and
    `detailed_route -nets <targets>`, and refuses itself if any existing cell
    moved. It FAILed for missing `set_wire_rc` / `repair_design` /
    `repair_timing -setup`.
  * `pnr_cts_head.tcl` (T98, #2697), when placement was ingested from
    LibreLane: `read_def placed.def`, parasitics, a pre-CTS checkpoint. The
    setup chain runs in `pnr_cts_tail.tcl`, which PASSed.

Every deck that placed or optimised carried the chain (pnr.tcl, the rollback /
SDR / adopt tails, the CTS tail). The decks here are emitted by the REAL
producers (`_antenna_isolated_scoped_retry_tcl`, `librelane_cts_hold.head_deck`
/ `tail_deck`), and the gate is the real `main()`.

The negative controls pin that nothing got weaker: a checkpoint deck that
repairs or places without the chain still FAILs, a routing-only deck that
restores nothing is still audited, a directory holding only non-timing decks is
the disclosed-skip tier (rc 2, never PASS), and a deck named on the command line
is always audited.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import re
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(PROGRAMS / "tests"))
gate = importlib.import_module("pnr_timing_repair_completeness_check")
R = importlib.import_module("phase3_one_shot_runner")
contract = importlib.import_module("librelane_contract")


@pytest.fixture
def real_deck(tmp_path, monkeypatch):
    """pnr.tcl exactly as the runner's own builder emits it (T98's harness:
    the real `step_pnr` with only the process edge substituted)."""
    harness = importlib.import_module("test_librelane_cts_hold")
    real_builder = R._build_pnr_tcl_text
    kwargs = harness._drive_step_pnr(tmp_path / "deck", monkeypatch, None)
    return real_builder(**kwargs)


@pytest.fixture
def ll_consumer(real_deck):
    """The same deck on the steps 15..18 LibreLane seam (T97)."""
    return contract.placement_consumer_tcl(real_deck, "/p/pnr/placed.def",
                                           R._PNR_STAGE_MARKER)


def _strip_setup_chain(text: str) -> str:
    """A negative control: the same deck with every `repair_design` and
    `repair_timing -setup` command line removed."""
    return "\n".join(ln for ln in text.splitlines()
                     if not re.search(r"\brepair_design\b|\brepair_timing\b"
                                      r"[^\n#]*-setup\b", ln)) + "\n"


def _sha(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def _run(d: Path, tmp_path: Path):
    out = tmp_path / "rep.json"
    rc = gate.main([str(d), "--json", str(out)])
    rep = json.loads(out.read_text()) if out.is_file() else None
    return rc, rep


def _isolated_retry_decks():
    """Every shape the runner's isolated-ECO loop writes (trial 0, then the
    diode-moved trials)."""
    yield "pnr_antenna_isolated_retry.tcl", R._antenna_isolated_scoped_retry_tcl(
        "/p/pnr/antenna_isolated_seed.odb", "/p/pnr/antenna_isolated_candidate.odb",
        "DIODE_CELL")
    for trial, steps in enumerate((-1, 1, -4, 4), start=1):
        yield (f"pnr_antenna_isolated_retry_{trial}.tcl",
               R._antenna_isolated_scoped_retry_tcl(
                   "/p/pnr/antenna_isolated_seed.odb",
                   "/p/pnr/antenna_isolated_candidate.odb", "DIODE_CELL",
                   move_net="net7", move_steps=steps,
                   marker_box=(1.0, 2.0, 3.0, 4.0)))


# ---------------------------------------------------------------- the defect

def test_the_scoped_antenna_eco_is_not_judged_as_a_pnr_flow(tmp_path, real_deck):
    d = tmp_path / "pnr"
    d.mkdir()
    (d / "pnr.tcl").write_text(real_deck)
    names = []
    for name, text in _isolated_retry_decks():
        (d / name).write_text(text)
        names.append(name)
    rc, rep = _run(d, tmp_path)
    assert rc == 0, rep
    assert rep["verdict"] == "PASS"
    assert [Path(a["script"]).name for a in rep["audited"]] == ["pnr.tcl"]
    skipped = {Path(n["script"]).name: n for n in rep["not_timing_sessions"]}
    assert sorted(skipped) == sorted(names)
    for name in names:
        assert skipped[name]["sha256"] == _sha(d / name)
        assert skipped[name]["reason"].startswith("NOT_A_TIMING_SESSION")


def test_the_ll_placed_cts_head_is_not_judged_but_its_tail_is(tmp_path, ll_consumer):
    d = tmp_path / "pnr"
    d.mkdir()
    (d / "pnr.tcl").write_text(ll_consumer)
    rc, rep = _run(d, tmp_path)
    assert rc == 0, rep
    audited = {Path(a["script"]).name: a for a in rep["audited"]}
    assert set(audited) == {"pnr.tcl", "pnr_cts_tail.tcl"}
    assert audited["pnr_cts_tail.tcl"]["summary"]["setup_repair_chain_present"]
    assert [Path(n["script"]).name for n in rep["not_timing_sessions"]] == [
        "pnr_cts_head.tcl"]


def test_every_audited_deck_names_its_bytes(tmp_path, ll_consumer):
    d = tmp_path / "pnr"
    d.mkdir()
    (d / "pnr.tcl").write_text(ll_consumer)
    rc, rep = _run(d, tmp_path)
    assert rc == 0
    assert len(rep["audited"]) == 2
    for a in rep["audited"]:
        assert a["sha256"] == _sha(Path(a["script"]))


# ------------------------------------------------- nothing got weaker: controls

def test_a_head_that_places_is_audited_not_skipped(tmp_path, real_deck):
    """The direct deck places and repairs before CTS, so its head is a timing
    session: audited, and it carries the chain."""
    d = tmp_path / "pnr"
    d.mkdir()
    rc, rep = _run(d, tmp_path)
    assert rc == 0, rep
    assert [Path(a["script"]).name for a in rep["audited"]] == ["pnr_cts_head.tcl"]
    assert rep["summary"]["setup_repair_chain_present"]
    assert rep.get("not_timing_sessions", []) == []


def test_a_head_that_places_without_the_chain_still_fails(tmp_path, real_deck):
    d = tmp_path / "pnr"
    d.mkdir()
    rc, rep = _run(d, tmp_path)
    assert rc == 1, rep
    assert rep["verdict"] == "FAIL"


@pytest.mark.parametrize("body", [
    # the sha256 silicon-DOA shape, resumed from a checkpoint
    "read_db /p/pnr/ckpt.odb\ncatch {repair_timing -hold}\ndetailed_route\n",
    # a checkpoint session that re-places without any repair
    "read_def /p/pnr/placed.def\ndetailed_placement\nglobal_route\n"
    "detailed_route\n",
    # a deck that BUILDS the design and reads a floorplan DEF, then only routes
    "read_verilog /p/netlist.v\nlink_design top\nread_def /p/floorplan.def\n"
    "global_route\ndetailed_route\n",
    # a checkpoint session that resizes for DRV only
    "read_db /p/pnr/ckpt.odb\nset_wire_rc -layer Metal1\nrepair_design\n"
    "detailed_route\n",
])
def test_a_checkpoint_deck_that_repairs_or_places_is_still_audited(
        tmp_path, real_deck, body):
    d = tmp_path / "pnr"
    d.mkdir()
    (d / "pnr.tcl").write_text(real_deck)
    (d / "pnr_eco.tcl").write_text(body)
    rc, rep = _run(d, tmp_path)
    assert rc == 1, rep
    assert rep["script"].endswith("pnr_eco.tcl")
    assert rep.get("not_timing_sessions", []) == []


def test_a_routing_deck_that_restores_nothing_is_still_audited(tmp_path, real_deck):
    d = tmp_path / "pnr"
    d.mkdir()
    (d / "pnr.tcl").write_text(real_deck)
    (d / "pnr_route.tcl").write_text("global_route\ndetailed_route\n")
    rc, rep = _run(d, tmp_path)
    assert rc == 1
    assert rep["script"].endswith("pnr_route.tcl")


def test_a_commented_resizer_call_does_not_make_a_timing_session(tmp_path, real_deck):
    """A `# repair_timing -hold` is not a command: the ECO stays out of the
    audited set and the directory still PASSes on the deck that did the work."""
    d = tmp_path / "pnr"
    d.mkdir()
    (d / "pnr.tcl").write_text(real_deck)
    name, text = next(_isolated_retry_decks())
    (d / name).write_text("# repair_timing -hold\n" + text)
    rc, rep = _run(d, tmp_path)
    assert rc == 0, rep
    assert [Path(n["script"]).name for n in rep["not_timing_sessions"]] == [name]


def test_a_directory_of_only_non_timing_decks_is_never_a_pass(
        tmp_path, ll_consumer, capsys):
    d = tmp_path / "pnr"
    d.mkdir()
    for name, text in _isolated_retry_decks():
        (d / name).write_text(text)
    rc, rep = _run(d, tmp_path)
    assert rc == 2
    assert rep is None
    assert "VACUOUS_PASS" in capsys.readouterr().out


def test_a_deck_named_on_the_command_line_is_always_audited(tmp_path):
    name, text = next(_isolated_retry_decks())
    p = tmp_path / name
    p.write_text(text)
    out = tmp_path / "rep.json"
    assert gate.main([str(p), "--json", str(out)]) == 1
    assert json.loads(out.read_text()).get("not_timing_sessions", []) == []
