"""v0.2.71 — #442: PVT matrix substance + single-corner disclosure.

Pins:
  * pvt_matrix.json with corners=[] FAILs pvt_matrix_check (an empty
    list is not a PVT matrix);
  * exactly 1 corner → exit 0 with verdict SINGLE_CORNER_ONLY (honest,
    never presented as multi-corner);
  * a self-contradictory multi_corner:true claim with <2 corners FAILs;
  * the runner stamps corner_count / multi_corner / coverage into the
    emitted matrix (source pin);
  * eda_report_audit STA mode discloses STA_SINGLE_CORNER_ONLY when no
    >=2-distinct per-corner evidence exists (advisory, not a FAIL).

chip-AGNOSTIC: structural JSON shape only.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import eda_report_audit as ERA   # noqa: E402
import pvt_matrix_check as PMC   # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent.parent
_P3_SRC = (PLUGIN / "programs" / "phase3_one_shot_runner.py").read_text()


def _matrix(tmp_path, payload):
    d = tmp_path / "phase2" / "stage2" / "constraints"
    d.mkdir(parents=True, exist_ok=True)
    (d / "pvt_matrix.json").write_text(json.dumps(payload))
    return tmp_path


def test_empty_corners_fail(tmp_path):
    _matrix(tmp_path, {"corners": [], "primary_corner": "TT"})
    rep = PMC.audit(tmp_path)
    assert rep["rc"] == 1 and rep["verdict"] == "FAIL"


def test_single_corner_disclosed_not_multi(tmp_path):
    _matrix(tmp_path, {"corners": [{"name": "lib_tt", "label": "TT"}]})
    rep = PMC.audit(tmp_path)
    assert rep["rc"] == 0
    assert rep["verdict"] == "SINGLE_CORNER_ONLY"


def test_contradictory_multi_corner_claim_fails(tmp_path):
    _matrix(tmp_path, {"corners": [{"name": "lib_tt", "label": "TT"}],
                       "multi_corner": True})
    rep = PMC.audit(tmp_path)
    assert rep["rc"] == 1


def test_three_corners_is_multi(tmp_path):
    _matrix(tmp_path, {"corners": [
        {"name": "a", "label": "SS"}, {"name": "b", "label": "TT"},
        {"name": "c", "label": "FF"}]})
    rep = PMC.audit(tmp_path)
    assert rep["rc"] == 0 and rep["verdict"] == "MULTI_CORNER"


def test_no_matrix_is_vacuous_rc2(tmp_path):
    assert PMC.audit(tmp_path)["rc"] == 2


def _runner():
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location(
        "phase3_one_shot_runner", PLUGIN / "programs" / "phase3_one_shot_runner.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["phase3_one_shot_runner"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_runner_stamps_corner_count_and_coverage():
    """DRIVEN, not scanned. The first version took a +-window of SOURCE around
    the FIRST `pvt["corner_count"]` and looked for the token in it — which
    measures DISTANCE, not behaviour.

    The distance it measured was real, though: this runner writes
    `pvt_matrix.json` from TWO places, #442's disclosure was added to only one
    of them, and the token sat 8738 characters away beside the other. The
    omitting writer was the Step-7c one, which runs FIRST and is therefore the
    one that creates the file when it does not exist.
    """
    R = _runner()
    for corners, want_cov in (([], "NO_CORNERS"),
                              ([{"name": "a", "label": "TT"}],
                               "SINGLE_CORNER_ONLY")):
        pvt = R.stamp_pvt_corner_coverage({}, corners)
        assert pvt["corner_count"] == len(corners)
        assert pvt["multi_corner"] is False
        assert pvt["coverage"] == want_cov, (corners, pvt)
        assert "#442" in pvt["note"]


def test_two_corners_carry_no_shortfall_disclosure():
    """THE ACCEPT CASE. A real matrix must not be labelled as failing to
    substantiate one."""
    R = _runner()
    pvt = R.stamp_pvt_corner_coverage(
        {}, [{"name": "a", "label": "SS"}, {"name": "b", "label": "TT"}])
    assert pvt["multi_corner"] is True
    assert "coverage" not in pvt and "note" not in pvt


def test_both_writers_go_through_the_one_stamper():
    """The defect was a disclosure present at one of two writers of the same
    artefact. Neither may stamp the census on its own again."""
    src = _P3_SRC
    code = "\n".join(l for l in src.splitlines()
                      if not l.lstrip().startswith("#"))
    assert code.count("stamp_pvt_corner_coverage(pvt, corners)") == 2, (
        "a writer stopped calling the shared stamper")
    # EXACTLY ONCE in the whole file — inside the stamper. Slicing "everything
    # after the stamper's `def`" cannot tell the stamper's own body from a
    # writer's, which is what the first version of this assertion did.
    assert code.count('pvt["corner_count"] = len(corners)') == 1, (
        "the census is stamped somewhere other than the shared stamper, so "
        "the two writers can diverge again")


def test_sta_single_corner_disclosure(tmp_path):
    sta = tmp_path / "phase3" / "stage3" / "sta"
    sta.mkdir(parents=True)
    (sta / "post_route_timing.rpt").write_text(
        "Startpoint: a\nPath Type: max\nslack (MET)\nOpenSTA\n")
    r = ERA._check_sta(tmp_path)
    assert r.summary["multi_corner_executed"] is False
    disc = [f for f in r.findings if f.rule == "STA_SINGLE_CORNER_ONLY"]
    assert disc and disc[0].severity == "WARNING"  # advisory, not ERROR
    assert r.summary["multi_corner_claim_not_broken"] is True  # no broken claim


def test_sta_two_distinct_corners_no_disclosure(tmp_path):
    sta = tmp_path / "phase3" / "stage3" / "sta"
    pc = sta / "per_corner"
    pc.mkdir(parents=True)
    (sta / "post_route_timing.rpt").write_text(
        "Startpoint: a\nPath Type: max\nslack (MET)\nOpenSTA\n")
    (pc / "sta_SS.rpt").write_text("Path Type: max\nslack (MET) 1.2\n")
    (pc / "sta_FF.rpt").write_text("Path Type: max\nslack (MET) 3.4\n")
    r = ERA._check_sta(tmp_path)
    assert r.summary["multi_corner_executed"] is True
    assert not any(f.rule == "STA_SINGLE_CORNER_ONLY" for f in r.findings)
