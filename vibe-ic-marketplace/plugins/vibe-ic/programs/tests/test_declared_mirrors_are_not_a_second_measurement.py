#!/usr/bin/env python3
"""One measurement arrived as two records, so every timing group collided.

MEASURED DEFECT
===============
The flow publishes each sign-off STA report into TWO of the directories
`_ppa/timing._STA_DIRS` reads:

    sha256(phase3/stage3/sta/sta_spef_based.rpt)
        == sha256(reports/phase3/sta_spef_based.rpt)
    sha256(phase3/stage3/sta/sta_mcorner_ocv.rpt)
        == sha256(reports/phase3/sta_mcorner_ocv.rpt)
    sha256(phase3/stage3/sta/sta_spef_multicorner.rpt)
        == sha256(reports/phase3/sta_spef_multicorner.rpt)

Measured on one real run tree: `56` rows, `20` (metric, scope) groups, and
ALL `20` holding more than one record — refused as CONFLICTING_RECORD.
Correctly: two numbers claiming to be the same fact IS a conflict. One fact
was arriving as two records.

WHERE IT IS FIXED, AND WHY
==========================
NOT in the emitter. Both locations are load-bearing: five shipped checkers
read the `reports/phase3/` copy (`achieved_period_recorded_check`,
`sta_corner_record_completeness_check`, `drv_promotion_corroboration_check`,
`post_route_signoff_corner_check`, `postroute_timing_repair_status_gen`) and the step writes the
`phase3/stage3/sta/` one. Dropping either breaks a consumer.

NOT by content hash either. A genuine SECOND measurement that happens to agree
to the byte is a real reading of a real artefact, and collapsing it by digest
would erase evidence — the same silence this lane exists to remove. Identical
bytes are not proof of a copy.

So the collapse is driven by the run's OWN declaration. The step that makes
the copy is the only thing that knows it is a copy, and now records it in
`reports/phase3/artefact_mirrors.json` with the digest at copy time. The
reader collapses a pair ONLY when the run declared it and both files still
match that digest.

MEASURED with the fix, on the same real tree: `56` rows -> `28`, colliding
groups `20` -> `4`. The residual 4 are a DIFFERENT finding — one
`worst_path_slack_ns` per reported path under one scope, three paths per view
— which no mirror collapse can or should touch.

WHAT IS ASSERTED
================
1. FORWARD (fails pre-fix): a declared mirror contributes no second row.
2. THE CONSTRAINT (fails a content-hash de-duplication): two byte-identical
   artefacts that were NOT declared mirrors both still produce rows.
3. NO MANIFEST (must pass pre-fix AND post-fix): with nothing declared,
   nothing is collapsed. An old run tree keeps exactly today's answer.
4. DIVERGED (fails a naive implementation): a declared mirror whose content
   no longer matches the digest recorded at copy time is NOT collapsed, and
   the note says why — two contents are two facts.
5. SOURCE OUT OF SCOPE: a declared mirror whose source is not among the
   artefacts read is KEPT; it is the only reading present.
6. THE EMITTER: the copy is byte-exact, the entry is recorded, and a re-run
   replaces the entry rather than growing the list.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))

from _ppa import timing  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "phase3_one_shot_runner_mirrors", _PROGRAMS / "phase3_one_shot_runner.py")
p3 = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = p3
_SPEC.loader.exec_module(p3)

BODY = """# report
STA_BASIS: POST_ROUTE_SPEF
STA_BASIS_LIBERTY: /foss/pdks/x/lib/cells_tt_025C_1v80.lib
worst slack max 1.98
tns max 0.00
"""
MANIFEST = "reports/phase3/artefact_mirrors.json"
PRIMARY = "phase3/stage3/sta/sta_spef_based.rpt"
MIRROR = "reports/phase3/sta_spef_based.rpt"


def _write(project: Path, rel: str, body: str) -> Path:
    f = project / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body)
    return f


def _digest(p: Path) -> str:
    import hashlib
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def _manifest(project: Path, entries):
    _write(project, MANIFEST, json.dumps(
        {"schema": "vibeic.artefact_mirrors.v1", "mirrors": entries},
        indent=2) + "\n")


def _measure(project: Path):
    rows, notes = timing.timing_rows(project)
    opened = [n for n in notes if n.startswith("opened ")][0]
    return rows, notes, opened


# ---------------------------------------------------------------- FORWARD ---
def test_a_declared_mirror_contributes_no_second_row(tmp_path):
    """FAILS pre-fix: both copies were read and every row was emitted twice."""
    a = _write(tmp_path, PRIMARY, BODY)
    b = _write(tmp_path, MIRROR, BODY)
    _manifest(tmp_path, [{"mirror": MIRROR, "of": PRIMARY,
                          "sha256": _digest(a), "declared_by": "_emit_spef_sta"}])
    rows, notes, opened = _measure(tmp_path)

    only = [r for r in rows]
    assert "opened 1 STA artefact" in opened, opened
    assert MIRROR not in opened
    assert any("collapsed declared mirror" in n for n in notes), notes
    # and the same tree without the declaration reads twice as much
    (tmp_path / MANIFEST).unlink()
    twice, _, opened2 = _measure(tmp_path)
    assert "opened 2 STA artefact" in opened2
    assert len(twice) == 2 * len(only) > 0
    assert b.read_text() == BODY          # nothing was deleted, only not read


# ------------------------------------------------------------- CONSTRAINT ---
def test_two_identical_artefacts_that_are_not_declared_mirrors_both_count(tmp_path):
    """The rule a content-hash de-duplication cannot satisfy.

    Two DIFFERENT sign-off reports whose bytes happen to agree are two
    measurements. Collapsing them by digest would delete evidence, so the
    collapse must be driven by the producer's declaration, never by equality.
    """
    _write(tmp_path, PRIMARY, BODY)
    other = "phase3/stage3/sta/sta_spef_second_run.rpt"
    _write(tmp_path, other, BODY)
    _manifest(tmp_path, [])          # declared: nothing
    rows, _, opened = _measure(tmp_path)
    assert "opened 2 STA artefact" in opened, opened
    assert len(rows) > 0


# -------------------------------------------------------------- NO MANIFEST --
# Must pass BOTH pre-fix and post-fix: an older run tree, which declares
# nothing, must keep exactly the answer it had.
def test_without_a_manifest_nothing_is_collapsed(tmp_path):
    _write(tmp_path, PRIMARY, BODY)
    _write(tmp_path, MIRROR, BODY)
    rows, notes, opened = _measure(tmp_path)
    assert "opened 2 STA artefact" in opened, opened
    assert not any("collapsed" in n for n in notes), notes


# ----------------------------------------------------------------- DIVERGED --
def test_a_mirror_that_has_diverged_is_not_collapsed(tmp_path):
    """The digest is recorded at copy time for exactly this case. If the two
    files no longer agree, they are two contents and therefore two facts, and
    silently keeping one would publish a number the other contradicts."""
    a = _write(tmp_path, PRIMARY, BODY)
    _write(tmp_path, MIRROR, BODY.replace("1.98", "0.11"))
    _manifest(tmp_path, [{"mirror": MIRROR, "of": PRIMARY,
                          "sha256": _digest(a), "declared_by": "_emit_spef_sta"}])
    _, notes, opened = _measure(tmp_path)
    assert "opened 2 STA artefact" in opened, opened
    assert any("NOT collapsed" in n and "two facts" in n for n in notes), notes


# ------------------------------------------------------------ OUT OF SCOPE ---
def test_a_mirror_whose_source_is_not_read_is_kept(tmp_path):
    """A copy is the only reading present when its source is not in scope.
    Dropping it there would turn a measurement into nothing at all."""
    b = _write(tmp_path, MIRROR, BODY)
    _manifest(tmp_path, [{"mirror": MIRROR, "of": PRIMARY,
                          "sha256": _digest(b), "declared_by": "_emit_spef_sta"}])
    rows, notes, opened = _measure(tmp_path)
    assert "opened 1 STA artefact" in opened and MIRROR in opened, opened
    assert len(rows) > 0
    assert any("is not among the artefacts read" in n for n in notes), notes


# ---------------------------------------------------------------- EMITTER ---
def test_the_step_records_the_copy_it_makes(tmp_path):
    """FAILS pre-fix: the step copied the file and declared nothing."""
    a = _write(tmp_path, PRIMARY, BODY)
    dst = tmp_path / MIRROR
    written = p3._publish_artefact_mirror(a, dst, tmp_path, "_emit_spef_sta")

    assert dst.read_bytes() == a.read_bytes()
    assert str(tmp_path / MANIFEST) in written
    doc = json.loads((tmp_path / MANIFEST).read_text())
    assert doc["schema"] == "vibeic.artefact_mirrors.v1"
    (entry,) = doc["mirrors"]
    assert entry["mirror"] == MIRROR and entry["of"] == PRIMARY
    assert entry["sha256"] == _digest(a), (
        "the recorded digest must be the spelling `opensta.file_digest` "
        "publishes, or the consumer compares a prefixed hash with a bare one "
        "and never collapses anything")
    assert entry["declared_by"] == "_emit_spef_sta"


def test_re_running_the_step_replaces_its_entry_rather_than_growing_the_list(tmp_path):
    a = _write(tmp_path, PRIMARY, BODY)
    dst = tmp_path / MIRROR
    p3._publish_artefact_mirror(a, dst, tmp_path, "_emit_spef_sta")
    a.write_text(BODY.replace("1.98", "2.50"))
    p3._publish_artefact_mirror(a, dst, tmp_path, "_emit_spef_sta")
    doc = json.loads((tmp_path / MANIFEST).read_text())
    assert len(doc["mirrors"]) == 1
    assert doc["mirrors"][0]["sha256"] == _digest(a)


def test_a_second_mirror_joins_the_same_manifest(tmp_path):
    a = _write(tmp_path, PRIMARY, BODY)
    c = _write(tmp_path, "phase3/stage3/sta/sta_mcorner_ocv.rpt", BODY)
    p3._publish_artefact_mirror(a, tmp_path / MIRROR, tmp_path, "_emit_spef_sta")
    p3._publish_artefact_mirror(
        c, tmp_path / "reports/phase3/sta_mcorner_ocv.rpt", tmp_path,
        "_emit_mcorner_ocv_sta")
    doc = json.loads((tmp_path / MANIFEST).read_text())
    assert [e["mirror"] for e in doc["mirrors"]] == sorted(
        [MIRROR, "reports/phase3/sta_mcorner_ocv.rpt"])


def test_an_unparseable_manifest_does_not_lose_the_new_entry(tmp_path):
    a = _write(tmp_path, PRIMARY, BODY)
    _write(tmp_path, MANIFEST, "{ not json")
    p3._publish_artefact_mirror(a, tmp_path / MIRROR, tmp_path, "_emit_spef_sta")
    doc = json.loads((tmp_path / MANIFEST).read_text())
    assert [e["mirror"] for e in doc["mirrors"]] == [MIRROR]
