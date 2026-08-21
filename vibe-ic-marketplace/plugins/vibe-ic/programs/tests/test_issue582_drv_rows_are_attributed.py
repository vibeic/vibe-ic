"""#582 — a DRV total that cannot say which rows are the ECO spare pool's.

`_build_spare_postfix_tcl` (ORGANIC #563 round 2) deliberately ties every
unconnected spare INPUT to one `spare_tielo` net, and the reason is not
optional: floating spare inputs make netgen wire their pins to a neighbour's
pseudo-net while the schematic side declares them unconnected, and LVS
mismatches. Undoing it reintroduces that defect.

But it puts every spare input on ONE net, and a net with hundreds of sinks has
an enormous transition, so those pins land in the max-slew table looking exactly
like design violations. The issue measured 602 of 1767 — 34 %.

`extract_drv` counted rows and discarded their text, so the total could be SIZED
and not ATTRIBUTED. It now keeps the instance each row belongs to.

WHY `spare_cells.json` AND NOT A NAME. The producer already states `tied_off`
and lists every instance, so no heuristic is needed. A `spare_`-prefix rule
would be exactly the keyword a differently-named pool escapes — this repo has
removed several of those, and the tie-driver predicate three lines from the
problem is itself structural ("any master with ZERO signal INPUT terminals and
at least one signal OUTPUT terminal … derived from the master's own MTerm
directions, never a name").

DISCLOSED, NEVER SUBTRACTED. A DC-constant net's slew is meaningless, but a
total that quietly shrinks by a third is the shape this repo keeps removing.
Both numbers are published and their sum is still the total.

THE CORPUS CANNOT EXERCISE THIS. Every tracked `sha256` STA report carries 1-4
violated rows and zero spare rows, because those artefacts PREDATE #563 r2 —
`spare_tielo` appears 0 times in `sha256_pnr.v` and the spares there are
instantiated with empty port lists. Measured, and the reason the fixtures below
carry the load.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
_REPO = _PROGRAMS.parents[3]


def _load():
    spec = importlib.util.spec_from_file_location(
        "sta_corner_record_completeness_check",
        _PROGRAMS / "sta_corner_record_completeness_check.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sta_corner_record_completeness_check"] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load()

_RPT = """
max slew

Pin                                    Limit    Slew   Slack
------------------------------------------------------------
_07014_/A2                              1.50   27.34  -25.84 (VIOLATED)
spare_inverter_0/A                      1.50   99.10  -97.60 (VIOLATED)
spare_inverter_1/A                      1.50   99.10  -97.60 (VIOLATED)
"""


def _project(tmp_path, tied_off=True, names=("spare_inverter_0", "spare_inverter_1")):
    d = tmp_path / "phase3" / "stage3" / "pnr"
    d.mkdir(parents=True)
    (d / "spare_cells.json").write_text(json.dumps({
        "count": len(names), "tied_off": tied_off,
        "instances": [{"name": n, "cell": "x"} for n in names]}), encoding="utf-8")
    return tmp_path


# ── the row identifier ───────────────────────────────────────────────────────
def test_the_instance_is_everything_before_the_last_slash():
    """OpenSTA prints `<instance>/<pin>`, and a hierarchical instance name
    contains slashes too — so the PIN is the last segment, not the first."""
    assert M._row_instance("top/blk/u_reg/D  1.5 9.9 -8.4 (VIOLATED)") == "top/blk/u_reg"
    assert M._row_instance("_07014_/A2  1.50 27.34 -25.84 (VIOLATED)") == "_07014_"


def test_a_row_with_no_identifier_is_empty_not_guessed():
    assert M._row_instance("   1.50   27.34  -25.84 (VIOLATED)") == ""


def test_rows_are_kept_alongside_the_counts():
    d = M.extract_drv(_RPT)
    assert d["violations"] == {"max_slew": 3}
    assert d["rows"]["max_slew"] == ["_07014_", "spare_inverter_0", "spare_inverter_1"]


# ── the attribution ──────────────────────────────────────────────────────────
def test_a_tied_off_pool_splits_the_total(tmp_path):
    d = M.extract_drv(_RPT)
    got = M.attribute_drv(d["rows"], M.spare_instances(_project(tmp_path)))
    assert got["design"] == 1
    assert got["constant_net"] == 2
    assert got["total"] == 3, "the sum must still be the total — nothing is dropped"


def test_a_pool_that_is_NOT_tied_off_attributes_nothing(tmp_path):
    """Its inputs are floating, not sinks on one net, so none of this applies
    and every row is a design row."""
    d = M.extract_drv(_RPT)
    got = M.attribute_drv(d["rows"], M.spare_instances(_project(tmp_path, tied_off=False)))
    assert got["design"] == 3 and got["constant_net"] == 0


def test_no_spare_record_reports_NOT_ATTRIBUTED_rather_than_zero(tmp_path):
    """LOAD-BEARING. "no spare rows" and "I could not tell" are different
    claims, and reporting the second as the first is the defect this file is
    part of removing."""
    d = M.extract_drv(_RPT)
    got = M.attribute_drv(d["rows"], M.spare_instances(tmp_path))
    assert got["attributed"] is False
    assert "spare_cells.json" in got["reason"]


def test_an_unreadable_spare_record_is_not_read_as_absent_cells(tmp_path):
    p = tmp_path / "phase3" / "stage3" / "pnr"
    p.mkdir(parents=True)
    (p / "spare_cells.json").write_text("{not json", encoding="utf-8")
    assert M.spare_instances(tmp_path) is None


def test_a_design_instance_whose_name_merely_starts_with_spare_is_not_excluded(tmp_path):
    """The reason this reads `spare_cells.json` instead of a prefix. A design
    cell called `spare_ram_ctrl` is not in the pool and must stay a design
    row."""
    rpt = _RPT + "spare_ram_ctrl/A   1.50  9.9  -8.4 (VIOLATED)\n"
    d = M.extract_drv(rpt)
    got = M.attribute_drv(d["rows"], M.spare_instances(_project(tmp_path)))
    assert got["constant_net"] == 2, "only the recorded instances count"
    assert got["design"] == 2


# ── the existing consumers must not move ─────────────────────────────────────
def test_the_counts_and_total_are_unchanged_by_carrying_rows():
    """`rows` is additive. A consumer reading `violations`/`total` sees exactly
    what it saw before."""
    d = M.extract_drv(_RPT)
    assert d["total"] == sum(d["violations"].values()) == 3


def test_a_real_corpus_report_still_extracts_the_same_totals():
    """The artefacts predate #563 r2, so attribution is 0 there — which is the
    honest answer for them, not a failure of the rule."""
    rpt = (_REPO / "benchmark-data/ic/sha256/clean_run_v1427_20260715"
           / "phase3/stage3/sta/sta_mcorner_ocv.rpt")
    if not rpt.is_file():
        pytest.skip("corpus report absent")
    d = M.extract_drv(rpt.read_text(errors="replace"))
    assert d["total"] == sum(d["violations"].values())
    got = M.attribute_drv(d["rows"], M.spare_instances(_REPO / "benchmark-data/ic/sha256"))
    assert got["attributed"] is True
    assert got["constant_net"] == 0
    assert got["design"] == d["total"]

# ── THE WIRING, which is where the value actually is ────────────────────────
#
# v1.9.15 landed `attribute_drv` and NEVER CALLED IT. Every unit test above
# passed, the corpus test passed, and no artefact carried the answer — the
# issue's acceptance asks for the excluded count "reported separately and
# visibly in the SAME artefact", and nothing wrote it there. A gate can be
# perfectly correct and wired into a place where it answers nothing; these
# tests are the part that would have caught that.
_RPT_REL = "phase3/stage3/sta/sta_mcorner_ocv.rpt"


def _axis_project(tmp_path, with_spares=True):
    d = tmp_path / "phase3" / "stage3" / "sta"
    d.mkdir(parents=True)
    (d / "sta_mcorner_ocv.rpt").write_text(_RPT, encoding="utf-8")
    if with_spares:
        _project(tmp_path)
    return tmp_path


def test_the_emitted_axis_evidence_carries_the_attribution(tmp_path):
    ax = M.read_axis_evidence(_axis_project(tmp_path), {})
    drv = [a["drv"] for a in ax if a.get("drv")]
    assert drv, "no axis produced DRV evidence — the fixture stopped exercising this"
    att = drv[0].get("attribution")
    assert att is not None, (
        "`attribute_drv` is not called at the emit site, so the artefact "
        "states a DRV total it cannot attribute — the v1.9.15 half-landing")
    assert att["attributed"] is True
    assert att["constant_net"] == 2 and att["design"] == 1


def test_nothing_is_subtracted_from_the_published_total(tmp_path):
    """LOAD-BEARING. The issue flags reducing a violation count as the change
    deserving the most scrutiny. The sum must still be the total."""
    ax = M.read_axis_evidence(_axis_project(tmp_path), {})
    drv = [a["drv"] for a in ax if a.get("drv")][0]
    assert drv["total"] == 3
    assert drv["attribution"]["total"] == drv["total"]
    assert sum(drv["violations"].values()) == drv["total"]


def test_a_project_with_no_spare_record_says_so_in_the_artefact(tmp_path):
    """"no tie-off rows" and "I could not tell" must not arrive as the same
    number in the published evidence."""
    ax = M.read_axis_evidence(_axis_project(tmp_path, with_spares=False), {})
    att = [a["drv"] for a in ax if a.get("drv")][0]["attribution"]
    assert att["attributed"] is False
    assert "spare_cells.json" in att["reason"]


def test_the_r5_finding_discloses_the_split():
    """Pinned on the source: the number a human reads is the finding text, not
    the JSON, so the split has to reach that too."""
    src = (_PROGRAMS / "sta_corner_record_completeness_check.py").read_text(
        encoding="utf-8")
    assert "DISCLOSED, not subtracted" in src
    assert 'att.get("attributed")' in src, (
        "the R5 finding no longer reads the attribution")


def test_attribute_drv_is_actually_called(tmp_path):
    """The single assertion that would have caught the half-landing."""
    src = (_PROGRAMS / "sta_corner_record_completeness_check.py").read_text(
        encoding="utf-8")
    calls = [l for l in src.splitlines()
             if "attribute_drv(" in l and not l.lstrip().startswith("def ")]
    assert calls, "attribute_drv is defined and never called"
