#!/usr/bin/env python3
"""A routed DEF the publisher could not find must not be recorded as one it
deliberately excluded.

THE COLLAPSE THIS CLOSES
========================
Since the repair in `test_routed_def_corpus_is_reachable_by_publishing.py`,
`phase3/stage3/pnr/routed.def` is IN published scope: the publisher stages it,
size-routed like the GDS, because it is the one path
`tools/ci/routed_def_corpus.py` builds the corpus population from.

That makes "the run has a routed DEF somewhere else" a DIFFERENT fact from "the
publisher excludes this artefact by policy" — and until this file, both were
written into `LAYOUT_ROUTING.txt` with the same word:

    phase3/phase3/stage3/pnr/routed.def  ...  NOT_PUBLISHED  source-run-only
    phase3/stage3/pnr/placed.def         ...  NOT_PUBLISHED  source-run-only

MEASURED before the repair, on a run carrying the doubled `phase3/phase3/`
shape: `publish rc 0`, cell created, `published .def files: []`, the run's
routed DEF recorded `NOT_PUBLISHED` exactly like the scratch beside it, and
NOTHING on stdout or stderr naming it. The cell reads as one whose run had no
post-route geometry.

AND THE SHAPE IS COMMITTED, NOT HYPOTHETICAL. The published corpus
(`vibeic/benchmark-data` @ `3b58ccd42`) carries 52 files under a doubled
`phase3/phase3/` prefix -- `protocol_parity/lpc/phase3/phase3/stage3/pnr/`
holds `routed.drc.rpt`, `spare_cells.json`, `pnr.tcl` and 25 more, and
`protocol_parity/usb_pd` doubles `reports/phase3/phase3/`. A run tree of that
shape is a shape real runs have had.

WHY IT MATTERS TO THE BLOCKING ROW
==================================
`routed_def_corpus.py` answers rc 0 with an empty population for a corpus that
holds no countable routed DEF -- byte-for-byte what it answers when nothing was
ever published (pinned in
`test_routed_def_population_is_depth_exact.py`). So a cell published from a
doubled run tree adds nothing to the corpus, the blocking row keeps saying
`is EMPTY -- nothing was checked over it`, and no artefact anywhere says the
artefact existed and was dropped for a reason nobody chose.

`CITATION_ROUTING.txt`, the sibling record, already argues this exact
distinction for citations: "a directory that ships its neighbours and not this
file is a HOLE ... the wrong word here retires a finding instead of reporting
one." `OFF_CANONICAL_PATH` is that word for blobs.

WHAT THIS IS NOT
================
It is NOT a widening of published scope: nothing new is staged, the cell is
byte-identical, and the corpus stays empty. It is not a refusal either -- the
run may be converged and the cell worth publishing; what changes is that the
record stops asserting a policy decision that was never made.

  ARM A  the off-canonical routed DEF is recorded OFF_CANONICAL_PATH, and the
         publisher says so on stderr naming both paths.       (RED before)
  ARM B  CONTROL -- a canonical routed DEF is STAGED and NO row anywhere is
         OFF_CANONICAL_PATH. The new word cannot fire on the healthy case.
  ARM C  CONTROL -- a run with no routed DEF at all emits no OFF_CANONICAL_PATH
         row. An absence cannot manufacture the finding.
  ARM D  CONTROL -- an OVERSIZE canonical routed DEF stays ROUTED_AWAY. The
         size decision is untouched, and a present-but-too-big DEF is not
         "missing".
  ARM E  CONTROL -- a `steps/` symlink back to the canonical DEF is not a
         second, off-canonical artefact. Converged runs alias their outputs.

chip-AGNOSTIC: synthetic run dirs with generic IC/PDK tokens throughout.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_REACH = _TESTS / "test_routed_def_corpus_is_reachable_by_publishing.py"

pytestmark = pytest.mark.skipif(
    not _REACH.is_file(), reason=f"scaffold not present at {_REACH}")

_spec = importlib.util.spec_from_file_location("_reach_scaffold", _REACH)
_reach = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_reach)

OFF = "OFF_CANONICAL_PATH"
CANONICAL = "phase3/stage3/pnr/routed.def"
DOUBLED = "phase3/phase3/stage3/pnr/routed.def"


def _move_off_canonical(run: Path, rel: str = DOUBLED) -> None:
    """Reproduce the doubled shape the published corpus actually carries."""
    target = run / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(run / CANONICAL), str(target))


def _published(tmp_path: Path, mutate=None, routed_def=None):
    kwargs = {} if routed_def is None else {"routed_def": routed_def}
    run = _reach._make_run(tmp_path, **kwargs)
    if mutate is not None:
        mutate(run)
    dest_root = tmp_path / "dest"
    result = _reach._publish(run, dest_root)
    assert result.returncode == 0, result.stdout + result.stderr
    return result, _reach._cell(dest_root)


# --------------------------------------------------------------------------
# ARM A — the finding. RED before the repair: the row read NOT_PUBLISHED.
# --------------------------------------------------------------------------

def test_a_an_off_canonical_routed_def_is_not_recorded_as_out_of_scope(tmp_path):
    result, cell = _published(tmp_path, _move_off_canonical)
    routing = _reach._routing(cell)

    assert routing.get(DOUBLED) == OFF, (
        "the run's routed DEF was recorded with the same word as the scratch "
        "the publisher excludes on purpose, so the record asserts a policy "
        f"decision nobody made: {routing}")
    # The scratch beside it must keep the word that IS true of it, or ARM A is
    # satisfied by renaming every exclusion.
    assert routing.get("phase3/stage3/pnr/placed.def") == "NOT_PUBLISHED", routing

    text = result.stdout + result.stderr
    assert DOUBLED in text and CANONICAL in text, (
        "the publisher dropped the one artefact the post-route gates are "
        "about and said nothing naming it or the path it was looked for at:\n"
        + text)


# --------------------------------------------------------------------------
# ARM B — CONTROL. The healthy case must be untouched.
# --------------------------------------------------------------------------

def test_b_a_canonical_routed_def_is_staged_and_never_off_canonical(tmp_path):
    _result, cell = _published(tmp_path)
    routing = _reach._routing(cell)

    assert routing.get(CANONICAL) == "STAGED", routing
    assert OFF not in routing.values(), (
        f"the new decision fired on a run whose DEF is exactly where the "
        f"corpus producer selects on it: {routing}")
    assert (cell / CANONICAL).is_file(), "the cell stopped carrying its DEF"


# --------------------------------------------------------------------------
# ARM C — CONTROL. Absence must not manufacture the finding.
# --------------------------------------------------------------------------

def test_c_a_run_with_no_routed_def_emits_no_off_canonical_row(tmp_path):
    def _remove(run: Path) -> None:
        (run / CANONICAL).unlink()

    _result, cell = _published(tmp_path, _remove)
    routing = _reach._routing(cell)

    assert OFF not in routing.values(), (
        f"a run that never produced a routed DEF was reported as having one "
        f"in the wrong place: {routing}")
    # The rest of the record must still be there — this arm must not be
    # satisfied by a publisher that stopped recording anything.
    assert routing.get("phase3/stage3/pnr/placed.def") == "NOT_PUBLISHED", routing


# --------------------------------------------------------------------------
# ARM D — CONTROL. The size decision is a different decision.
# --------------------------------------------------------------------------

def test_d_an_oversize_canonical_routed_def_stays_routed_away(tmp_path):
    big = b"X" * (_reach._CEILING + 1)
    _result, cell = _published(tmp_path, routed_def=big)
    routing = _reach._routing(cell)

    assert routing.get(CANONICAL) == "ROUTED_AWAY", routing
    assert OFF not in routing.values(), (
        "a DEF that is present at the canonical path and merely too big was "
        f"reported as being in the wrong place: {routing}")


# --------------------------------------------------------------------------
# ARM E — CONTROL. Converged runs alias their outputs.
# --------------------------------------------------------------------------

def test_e_a_symlink_back_to_the_canonical_def_is_not_a_second_artefact(tmp_path):
    def _alias(run: Path) -> None:
        steps = run / "steps" / "30_route"
        steps.mkdir(parents=True, exist_ok=True)
        os.symlink(os.path.relpath(run / CANONICAL, steps),
                   steps / "routed.def")

    _result, cell = _published(tmp_path, _alias)
    routing = _reach._routing(cell)

    assert routing.get(CANONICAL) == "STAGED", routing
    assert OFF not in routing.values(), (
        "a steps/ symlink pointing back at the STAGED canonical DEF was "
        f"counted as a second artefact in the wrong place: {routing}")


# --------------------------------------------------------------------------
# ARM F — CONTROL, and the one the first draft of the repair failed.
# --------------------------------------------------------------------------

def test_f_a_routed_def_inside_a_published_subtree_gets_exactly_one_line(tmp_path):
    """ONE LINE PER BLOB — the invariant `LAYOUT_ROUTING.txt`'s header states.

    A `routed.def` under a copy subtree has already been decided about by
    `_copy_tree`: STAGED under the ceiling, ROUTED_AWAY over it. The first
    draft of this repair rglobbed for the basename without asking what was
    already recorded, and emitted a SECOND row for the same blob —
    `ROUTED_AWAY` and `OFF_CANONICAL_PATH` for one file. Caught by
    `test_organic419b_...::test_an_oversized_artefact_is_absent_but_recorded_with_its_hash`,
    which read 2 lines where it requires 1. Pinned here as well, because that
    test is about the GDS block and would not have to keep covering this one.
    """
    big = b"Y" * (_reach._CEILING + 1)

    def _in_published_subtree(run: Path) -> None:
        (run / CANONICAL).unlink()
        target = run / "reports" / "phase3" / "routed.def"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(big)

    _result, cell = _published(tmp_path, _in_published_subtree)
    lines = [ln for ln in (cell / "LAYOUT_ROUTING.txt").read_text().splitlines()
             if ln.startswith("reports/phase3/routed.def ")]

    assert len(lines) == 1, (
        "one blob produced more than one routing line, which is the invariant "
        f"this file's own header states it keeps: {lines}")
    assert lines[0].split()[3] == "ROUTED_AWAY", (
        "an artefact the size rule DID look at and decide about was relabelled "
        f"as one the publisher could not find: {lines[0]}")
