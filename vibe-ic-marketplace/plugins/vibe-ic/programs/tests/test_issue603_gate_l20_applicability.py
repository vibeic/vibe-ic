"""#603 items 2+3 — the ATPG coverage gate judges TEST coverage and applies L20.

Two things this gate must now do, each with a bidirectional control:

  * PREFER test coverage. When coverage.json carries both the raw
    ``coverage_pct`` and the sign-off ``test_coverage_pct``, the verdict is
    computed on the TEST number and the RAW number is reported alongside — never
    collapsed into one (#603 item 2). Old runs with only ``coverage_pct`` are
    unaffected.

  * APPLY L20 (item 3). A design whose OWN L20 declares NO DFT requirement has
    its coverage reported as INFORMATIONAL, not FAILed at the foundry floor; a
    design that DECLARES DFT keeps the floor. The downgrade is one-directional
    (FAIL→INFORMATIONAL only) — the control proves a DFT-declaring design still
    FAILs below the floor.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


G = _load("dft_atpg_coverage_check")


def _project(tmp_path, coverage: dict, l20_fields=None, l20_applic="APPLICABLE"):
    dft = tmp_path / "reports" / "phase2" / "dft"
    dft.mkdir(parents=True)
    (dft / "coverage.json").write_text(json.dumps(coverage))
    if l20_fields is not None:
        gd = tmp_path / "phase1" / "generated_docs"
        gd.mkdir(parents=True)
        (gd / "L20_DFT_SCAN_TOPOLOGY.json").write_text(json.dumps({
            "doc_id": "L20", "applicability": l20_applic,
            "fields": l20_fields,
            "extraction_status": "NOT_YET_EXTRACTED", "extraction_evidence": {},
        }))
    return tmp_path


_NO_DFT_L20 = {"scan_chains": [], "test_compression": None, "bist_mbist": [],
               "jtag_tap": None, "dft_present": False}
_DFT_L20 = {"scan_chains": [{"name": "c0", "length": 33, "scan_in": "sin",
                             "scan_out": "sout", "clock": "clk"}],
            "test_compression": None, "bist_mbist": [], "jtag_tap": None,
            "dft_present": True}
# raw below floor, test below floor too — the design whose testable logic is
# covered but whose raw ratio is dragged down by an unused frame.
_COV = {"tool": "fault", "coverage_pct": 60.53, "test_coverage_pct": 89.59,
        "test_coverage_measured": True, "target_pct": 95.0}


def test_prefers_test_coverage_over_raw(tmp_path):
    proj = _project(tmp_path, _COV, l20_fields=_DFT_L20)
    r = G.audit(proj)
    assert r["measured_coverage_pct"] == 89.59
    assert r["measured_is_test_coverage"] is True
    assert r["raw_coverage_pct"] == 60.53   # raw still reported, never dropped


def test_unextracted_no_dft_skeleton_is_unknown_and_keeps_the_floor(tmp_path):
    """RETARGETED — this test used to pin the defect it was written to avoid.

    `_project` stamps every fixture `extraction_status: NOT_YET_EXTRACTED`, so
    the tree this test built was the emitter's untouched SKELETON: APPLICABLE,
    never extracted, every field at its default. Its `dft_present: false` is a
    FIELD DEFAULT, not a decision, and the assertion below used to be
    `verdict == "INFORMATIONAL"` — i.e. it required the gate to read the
    ABSENCE of a stated DFT requirement as a DECLARATION that none exists, and
    to switch off the foundry floor on that basis.

    That is precisely the conflation fixed in `l20_dft_applicability` (rationale
    and the full bidirectional control in
    test_dft_floor_unextracted_l20_is_unknown.py). An un-extracted layer carries
    no more information than an absent one, and `test_no_l20_keeps_the_floor`
    directly above already pins that an absent L20 keeps the floor — so before
    the fix these two tests demanded OPPOSITE verdicts for strictly-ordered
    evidence states, with the LESS informative one treated more leniently.

    The design's genuine no-DFT declaration is still honoured, on the channel
    that is actually a declaration: `test_not_applicable_l20_is_informational`
    below is unchanged and still passes.
    """
    proj = _project(tmp_path, _COV, l20_fields=_NO_DFT_L20)
    r = G.audit(proj)
    assert r["verdict"] == "FAIL"
    assert r["floor_enforced"] is True
    assert r["l20_applicability"]["asserts_dft"] is None
    assert "UNKNOWN" in (r["l20_applicability"]["reason"] or "")
    # both numbers still survive into the record — degrade loudly, not silently
    assert r["measured_coverage_pct"] == 89.59 and r["raw_coverage_pct"] == 60.53
    assert G.main([str(proj), "--json", str(tmp_path / "o.json")]) == 1


def test_dft_declaring_design_still_fails_below_floor(tmp_path):
    # the load-bearing control: the downgrade is one-directional. A design that
    # DECLARES DFT and sits below the floor FAILs, informational path or not.
    proj = _project(tmp_path, _COV, l20_fields=_DFT_L20)
    r = G.audit(proj)
    assert r["verdict"] == "FAIL"
    assert r["floor_enforced"] is True
    assert G.main([str(proj), "--json", str(tmp_path / "o.json")]) == 1


def test_no_l20_keeps_the_floor(tmp_path):
    # absence of L20 is NOT an excuse to skip the floor.
    proj = _project(tmp_path, _COV, l20_fields=None)
    r = G.audit(proj)
    assert r["verdict"] == "FAIL"
    assert r["floor_enforced"] is True
    assert r["l20_applicability"]["asserts_dft"] is None


def test_not_applicable_l20_is_informational(tmp_path):
    proj = _project(tmp_path, _COV, l20_fields=_NO_DFT_L20, l20_applic="NOT_APPLICABLE")
    r = G.audit(proj)
    assert r["verdict"] == "INFORMATIONAL"
    assert r["l20_applicability"]["asserts_dft"] is False


def test_test_coverage_at_floor_passes_regardless(tmp_path):
    cov = dict(_COV, test_coverage_pct=96.0)
    proj = _project(tmp_path, cov, l20_fields=_DFT_L20)
    r = G.audit(proj)
    assert r["verdict"] == "PASS"          # 96 >= 95, DFT-declaring, floor met
    assert r["measured_is_test_coverage"] is True
