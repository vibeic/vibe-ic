#!/usr/bin/env python3
"""The routed-DEF corpus must be REACHABLE by the program that publishes cells.

WHAT THIS PINS, AND WHY IT IS NOT A TEST ABOUT FILE COPYING
===========================================================
`repo_hygiene_gates.sh` declares a BLOCKING loop over the corpus "published
cells carrying a routed DEF", produced by `tools/ci/routed_def_corpus.py`, which
selects on exactly one path shape inside the published tree:

    ic/<design>/<version>/phase3/stage3/pnr/routed.def

The corpus is empty, so the loop reports NOT CHECKED (rc 2) and blocks, with no
exemption -- and `_gate_dispatch.sh` refuses to let one be attached. The
adjudication that state rests on is that the emptiness is TEMPORARY: publish a
cell and the gate starts checking something.

MEASURED, AND THAT PREMISE WAS FALSE. `benchmark_evidence_publish.py` is the
program that publishes a cell, and its `_COPY_SUBTREES` carries `phase3/reports`
and `phase3/analog` -- not `phase3/stage3`. A converged run whose routed DEF is
38 bytes, six orders of magnitude under the 50 MB ceiling, published through the
supported path, produced a cell containing ZERO `.def` files and a
`LAYOUT_ROUTING.txt` line reading:

    phase3/stage3/pnr/routed.def 38B sha256:fee7400... NOT_PUBLISHED source-run-only

So no number of published cells could ever add a member. The gate was not one
publish away from checking something; it was unreachable from every supported
action, which is a different state and calls for a different answer.

THIS IS THE SAME DEFECT THE GDS BLOCK IN `publish()` ALREADY FIXED, ONE
ARTEFACT OVER. Its comment: "`phase3/stage4` is not a copy subtree, so until
this existed the GDS was omitted at EVERY size -- the size routing could not
reach the one artefact the manifest is actually about." `phase3/stage3/pnr` is
not a copy subtree either, and the artefact the post-route geometry gates are
about was omitted at every size for the same reason.

WHAT IS DELIBERATELY NOT WIDENED, AND ARMS B/C EXIST TO KEEP IT THAT WAY
=======================================================================
The repair is ONE NAMED ARTEFACT, routed by size like every other layout blob --
not the `phase3/stage3` tree, which is genuinely PnR scratch and whose exclusion
is an evidence-policy decision this does not reopen.

  ARM A  the routed DEF under the ceiling reaches the cell at the exact path
         the producer selects on, and is recorded STAGED.
  ARM B  CONTROL -- an oversize routed DEF is ROUTED_AWAY, not staged. Without
         this, "stage it" could be satisfied by a copy that ignores the ceiling
         the commit guard enforces.
  ARM C  CONTROL -- every OTHER file under `phase3/stage3`, including other
         `.def` stages of the same flow, stays out of the cell. Without this,
         ARM A could be satisfied by publishing the scratch tree wholesale.
  ARM D  the load-bearing one: `routed_def_corpus.py`, the actual gate
         producer, run against a real git checkout of the published tree,
         COUNTS the cell. A file at a path is not a population member until the
         producer says it is.

chip-AGNOSTIC: synthetic run dirs with generic IC/PDK tokens throughout.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
_REPO = _PROGRAMS.parents[3]
_PUBLISH = _PROGRAMS / "benchmark_evidence_publish.py"
_CORPUS_PRODUCER = _REPO / "tools" / "ci" / "routed_def_corpus.py"

sys.path.insert(0, str(_TESTS))
import _pdk_revision_fixture as _pdk_fixture  # noqa: E402

_RESULT_PASS = "# RESULT\n\n## VERDICT\n\n**PASS_WITH_WAIVERS.** re-derived.\n"
_SMALL_DEF = b"VERSION 5.8 ;\nDESIGN top ;\nEND DESIGN\n"

#: `benchmark_evidence_publish._SIZE_CEILING` / `tracked_blob_size_guard._CEILING`.
_CEILING = 50 * 1000 * 1000


def _make_run(base: Path, routed_def: bytes = _SMALL_DEF) -> Path:
    """A converged run whose PnR stage carries a routed DEF and scratch beside it."""
    run = base / "run"
    (run / "reports" / "audit").mkdir(parents=True)
    (run / "reports" / "audit" / "phase23_completion_audit.json").write_text(
        json.dumps({"verdict": "PASS_WITH_WAIVERS"}))
    (run / "RESULT.md").write_text(_RESULT_PASS)
    (run / "phase1" / "generated_docs").mkdir(parents=True, exist_ok=True)
    (run / "phase1" / "generated_docs" / "L1.json").write_text("{}")
    (run / "phase2" / "stage2" / "synth").mkdir(parents=True, exist_ok=True)
    (run / "phase2" / "stage2" / "synth" / "netlist.v").write_text(
        "module top; endmodule\n")
    (run / "phase3" / "reports").mkdir(parents=True, exist_ok=True)
    (run / "phase3" / "reports" / "drc.rpt").write_text("clean\n")
    (run / "reports" / "phase3").mkdir(parents=True, exist_ok=True)
    (run / "reports" / "phase3" / "sta.json").write_text("{}")
    (run / "provenance.jsonl").write_text('{"tool":"yosys"}\n')
    (run / "input" / "docs").mkdir(parents=True, exist_ok=True)
    (run / "input" / "docs" / "L1.md").write_text("# spec\n")

    pnr = run / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    (pnr / "routed.def").write_bytes(routed_def)
    # ARM C's subjects: the scratch this repair must NOT start publishing.
    (pnr / "placed.def").write_bytes(b"VERSION 5.8 ;\nDESIGN placed ;\n")
    (pnr / "floorplan.def").write_bytes(b"VERSION 5.8 ;\nDESIGN fp ;\n")
    (pnr / "pnr.tcl").write_text("# scratch\n")
    (run / "phase3" / "stage3" / "extracted").mkdir(parents=True, exist_ok=True)
    (run / "phase3" / "stage3" / "extracted" / "top.spef").write_text("*SPEF\n")

    (run / "phase3" / "stage4" / "gds").mkdir(parents=True, exist_ok=True)
    (run / "phase3" / "stage4" / "gds" / "top.gds").write_bytes(b"GDSII-FAKE-" * 64)
    _pdk_fixture.write_run_pdk_revision(run)
    return run


def _publish(run: Path, dest_root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_PUBLISH),
         "--run-dir", str(run), "--ic", "widgetmul", "--pdk", "openpdkx",
         "--plugin-version", "9.9.9", "--dest-root", str(dest_root)],
        capture_output=True, text=True)


def _routing(cell: Path) -> dict:
    """`LAYOUT_ROUTING.txt` as {run-relative path: DECISION}."""
    out = {}
    for line in (cell / "LAYOUT_ROUTING.txt").read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        fields = line.split()
        out[fields[0]] = fields[3]
    return out


def _cell(dest_root: Path) -> Path:
    return dest_root / "ic" / "widgetmul" / "v9.9.9_openpdkx"


# --------------------------------------------------------------------------
# ARM A — the artefact the corpus selects on reaches the published cell.
# --------------------------------------------------------------------------

def test_a_published_cell_carries_its_routed_def(tmp_path):
    run = _make_run(tmp_path)
    dest_root = tmp_path / "benchmark-data"
    result = _publish(run, dest_root)
    assert result.returncode == 0, result.stderr[-3000:]

    cell = _cell(dest_root)
    published = cell / "phase3" / "stage3" / "pnr" / "routed.def"
    assert published.is_file(), (
        "the corpus 'published cells carrying a routed DEF' selects on "
        "ic/<design>/<version>/phase3/stage3/pnr/routed.def, and the program "
        "that publishes cells did not put one there. Cell contains: "
        + repr(sorted(str(p.relative_to(cell)) for p in cell.rglob('*.def'))))
    assert published.read_bytes() == _SMALL_DEF
    assert _routing(cell)["phase3/stage3/pnr/routed.def"] == "STAGED"


# --------------------------------------------------------------------------
# ARM B — CONTROL: the size ceiling still governs it.
# --------------------------------------------------------------------------

def test_b_an_oversize_routed_def_is_routed_away_not_staged(tmp_path):
    run = _make_run(tmp_path, routed_def=b"D" * (_CEILING + 1))
    dest_root = tmp_path / "benchmark-data"
    result = _publish(run, dest_root)
    assert result.returncode == 0, result.stderr[-3000:]

    cell = _cell(dest_root)
    assert not (cell / "phase3" / "stage3" / "pnr" / "routed.def").exists(), (
        "a routed DEF over the commit ceiling must not be staged; the guard "
        "that blocks the commit is a size rule and this cell would not land")
    assert _routing(cell)["phase3/stage3/pnr/routed.def"] == "ROUTED_AWAY"


# --------------------------------------------------------------------------
# ARM C — CONTROL: it is ONE named artefact, not the scratch tree.
# --------------------------------------------------------------------------

def test_c_the_rest_of_pnr_scratch_stays_unpublished(tmp_path):
    run = _make_run(tmp_path)
    dest_root = tmp_path / "benchmark-data"
    assert _publish(run, dest_root).returncode == 0

    cell = _cell(dest_root)
    staged_defs = sorted(p.name for p in cell.rglob("*.def"))
    assert staged_defs == ["routed.def"], (
        "widening published scope to the whole phase3/stage3 tree is an "
        f"evidence-policy change this does not make; staged: {staged_defs}")
    assert not (cell / "phase3" / "stage3" / "pnr" / "pnr.tcl").exists()
    assert not (cell / "phase3" / "stage3" / "extracted").exists()

    routing = _routing(cell)
    assert routing["phase3/stage3/pnr/placed.def"] == "NOT_PUBLISHED"
    assert routing["phase3/stage3/pnr/floorplan.def"] == "NOT_PUBLISHED"
    assert routing["phase3/stage3/extracted/top.spef"] == "NOT_PUBLISHED"


# --------------------------------------------------------------------------
# ARM D — the gate's OWN producer counts the published cell.
# --------------------------------------------------------------------------

def _git(argv, cwd):
    return subprocess.run(["git", "-C", str(cwd)] + argv,
                          capture_output=True, text=True)


@pytest.mark.skipif(not _CORPUS_PRODUCER.is_file(),
                    reason="tools/ci/routed_def_corpus.py is not in this tree")
def test_d_the_corpus_producer_counts_the_published_cell(tmp_path, monkeypatch):
    run = _make_run(tmp_path)
    dest_root = tmp_path / "benchmark-data"
    assert _publish(run, dest_root).returncode == 0

    # The published tree as the corpus repository actually stores it: its ROOT
    # is what used to be `benchmark-data/`, so the cell is at `ic/<design>/...`.
    assert _git(["init", "-q", "-b", "main"], dest_root).returncode == 0
    assert _git(["add", "-A"], dest_root).returncode == 0

    env_free = {k: v for k, v in __import__("os").environ.items()}
    env_free["VIBE_IC_BENCHMARK_DATA"] = str(dest_root)
    env_free.pop("GATEKEEPER_BENCHMARK_DATA_SHA", None)
    env_free["PYTHONDONTWRITEBYTECODE"] = "1"
    produced = subprocess.run(
        [sys.executable, str(_CORPUS_PRODUCER), "--repo", str(_REPO)],
        capture_output=True, text=True, env=env_free)

    assert produced.returncode == 0, (
        f"producer rc {produced.returncode}\n{produced.stderr[-3000:]}")
    items = [line for line in produced.stdout.splitlines() if line.strip()]
    assert len(items) == 1, (
        "the published cell is not a member of the population the BLOCKING "
        f"gate loops over. stdout={items!r} stderr={produced.stderr[-2000:]}")
    assert items[0].endswith(
        "/ic/widgetmul/v9.9.9_openpdkx/phase3/stage3/pnr/routed.def")


# --------------------------------------------------------------------------
# ARM E — CONTROL: a cell that carries it is still a LANDABLE cell.
# --------------------------------------------------------------------------

_STRUCTURE_CHECK = _PROGRAMS / "benchmark_evidence_structure_check.py"


def test_e_a_cell_carrying_its_routed_def_still_validates(tmp_path):
    """Staging an artefact into the cell is worthless if the cell cannot land.

    Green before the repair as well as after — that is what makes it a control
    rather than evidence. It is here because the failure it rules out is
    silent: `benchmark_evidence_structure_check` is what CI runs over a
    published folder, and a repair that made every future cell nonconformant
    would have traded an unreachable corpus for an unpublishable one, which is
    strictly worse and would not have shown up in ARMs A-D at all.
    """
    run = _make_run(tmp_path)
    dest_root = tmp_path / "benchmark-data"
    assert _publish(run, dest_root).returncode == 0
    assert (_cell(dest_root) / "phase3" / "stage3" / "pnr" / "routed.def").is_file()

    import os
    env = {k: v for k, v in os.environ.items()}
    env.pop("VIBE_IC_BENCHMARK_DATA", None)  # validate THIS tree, not a clone
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    checked = subprocess.run(
        [sys.executable, str(_STRUCTURE_CHECK), "--tree", str(dest_root)],
        capture_output=True, text=True, env=env)
    assert checked.returncode == 0, (
        "a cell carrying its routed DEF must still be conformant, or the "
        f"repair produces cells that cannot land:\n{checked.stdout[-3000:]}"
        f"\n{checked.stderr[-2000:]}")
    assert "0 nonconformant" in checked.stdout
