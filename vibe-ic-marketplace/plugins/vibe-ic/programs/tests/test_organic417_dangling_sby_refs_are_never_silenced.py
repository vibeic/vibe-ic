#!/usr/bin/env python3
"""ORGANIC #417 — one intact proof chain silenced a true finding about a
different `.sby`.

`SBY_CHAIN_BROKEN` quantifies over ALL `.sby` ("no .sby whose referenced
files all exist"), and the loop that computed it `break`ed at the first
intact chain. So a second `.sby` with dangling references was never even
examined, and there was no finding that could carry the fact.

HOW IT SURFACED. On `ff93c70a7` the gate named TWO broken chains in
`spm/v1.5.58_ihp-sg13g2`. #415 restored the DUT for one of them and the other
went silent — without having changed. A gate that stops saying something true
because something else got fixed is a gate you cannot read a PASS from.

MEASURED on the published corpus after the fix: 27 cells carrying a
`formal/`, ZERO verdict changes (structurally guaranteed — `sby_ok` is set by
the same first intact chain either way; the fix only adds a finding), and one
real case that had been silent all along: `subservient` PASSes on
`subservient.sby` while `constraints.sby` references `rtl/*.sv`, which
resolves to nothing.

THE VERDICT QUANTIFIER IS DELIBERATELY UNCHANGED. What the gate answers is
whether `results.json`'s `all_proved` stands up, and it stands up on the
chain `results.json` cites. Making every `.sby` under `formal/` load-bearing
would fail cells for artefacts their own manifest never claimed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import formal_proof_evidence_check as F  # noqa: E402

_LOG = "SBY [x] engine_0: smtbmc\nSBY [x] DONE (PASS, rc=0)\n"


def _cell(tmp_path: Path, sbys: dict) -> Path:
    """A minimal cell whose proof chain is intact except for `sbys`."""
    d = tmp_path / "phase2" / "stage1" / "formal"
    d.mkdir(parents=True)
    (d / "dut.v").write_text("module dut; endmodule\n")
    (d / "results.json").write_text(json.dumps({"all_proved": True}))
    (d / "run.sby.log").write_text(_LOG)
    for name, body in sbys.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return tmp_path


_INTACT = "[files]\ndut.v\n"
_BROKEN = "[files]\nnot_here.v\n"


def _dangling(rep):
    return [f for f in rep["findings"] if f.startswith("SBY_REFS_DANGLING")]


def test_a_broken_sby_beside_an_intact_one_is_reported(tmp_path):
    rep = F.audit(_cell(tmp_path, {"a_good.sby": _INTACT,
                                   "b_bad.sby": _BROKEN}))
    assert rep["verdict"] == "PASS"
    assert len(_dangling(rep)) == 1
    assert "b_bad.sby: not_here.v" in _dangling(rep)[0]


def test_it_does_not_depend_on_which_one_git_sorts_first(tmp_path):
    """The `break` made the outcome depend on iteration order. With the
    broken chain FIRST the old code reported it (as SBY_CHAIN_BROKEN, having
    not yet found an intact one); with it second, nothing. Both orders must
    now report, and both must PASS."""
    rep = F.audit(_cell(tmp_path, {"a_bad.sby": _BROKEN,
                                   "b_good.sby": _INTACT}))
    assert rep["verdict"] == "PASS"
    assert len(_dangling(rep)) == 1
    assert "a_bad.sby: not_here.v" in _dangling(rep)[0]


def test_every_broken_sby_is_counted_not_just_the_first(tmp_path):
    rep = F.audit(_cell(tmp_path, {"good.sby": _INTACT,
                                   "bad1.sby": _BROKEN,
                                   "bad2.sby": "[files]\nalso_absent.v\n"}))
    assert rep["verdict"] == "PASS"
    assert "2 other .sby reference file(s)" in _dangling(rep)[0]


def test_the_paired_half_all_chains_intact_says_nothing(tmp_path):
    """A finding that fires on a correct cell is how a gate gets ignored."""
    rep = F.audit(_cell(tmp_path, {"a.sby": _INTACT, "b.sby": _INTACT}))
    assert rep["verdict"] == "PASS"
    assert _dangling(rep) == []


def test_no_intact_chain_still_reports_the_original_finding_only(tmp_path):
    """SBY_CHAIN_BROKEN keeps its meaning, and the new finding must not
    double-report the same fact."""
    rep = F.audit(_cell(tmp_path, {"a.sby": _BROKEN, "b.sby": _BROKEN}))
    assert rep["verdict"] == "FAIL"
    assert any(f.startswith("SBY_CHAIN_BROKEN") for f in rep["findings"])
    assert _dangling(rep) == []


def test_a_nested_broken_sby_is_reachable_at_all(tmp_path):
    """#412 made discovery recursive; this pins that the new finding follows
    it down rather than only seeing the top level."""
    rep = F.audit(_cell(tmp_path, {"good.sby": _INTACT,
                                   "deeper/bad.sby": "[files]\nabsent.v\n"}))
    assert rep["verdict"] == "PASS"
    assert "bad.sby: absent.v" in _dangling(rep)[0]


def test_the_verdict_is_not_downgraded_by_the_new_finding(tmp_path):
    """The load-bearing half of the design decision. A separate .sby that the
    manifest never claimed must not fail the cell."""
    before = F.audit(_cell(tmp_path / "one", {"good.sby": _INTACT}))
    after = F.audit(_cell(tmp_path / "two", {"good.sby": _INTACT,
                                             "extra_bad.sby": _BROKEN}))
    assert before["verdict"] == after["verdict"] == "PASS"
    assert before["rc"] == after["rc"] == 0


def test_the_real_previously_silent_case_on_published_data():
    """`subservient` ships two top-level .sby; `constraints.sby` references
    `rtl/*.sv`, which resolves to nothing. Both files predate this change —
    the gate simply had no way to say so.

    THE VERDICT IS DELIBERATELY NOT ASSERTED HERE, and the first version of
    this test asserting `PASS` is what turned main red. It passed on my
    machine and failed in CI, because this cell's `formal_evidence.json`
    cites `phase2/stage1/formal/sby_subservient.log` and that file is NOT
    TRACKED — `.gitignore:31 *.log` drops it, and the #411 rescue only
    negates `*.sby.log`, which is not how this runner names it. So the
    verdict here is a property of how complete the checkout is, not of the
    behaviour under test. Pinning it made a test that could only pass beside
    a local run directory. What #417 is about is the FINDING, which is
    present either way.
    """
    cell = _PROGRAMS.parents[3] / "benchmark-data" / "ic" / "subservient"
    if not (cell / "phase2/stage1/formal/constraints.sby").is_file():
        pytest.skip("published cell not present")
    rep = F.audit(cell)
    assert _dangling(rep), (
        "the pre-existing dangling chain must be named", rep["findings"])
    assert "constraints.sby" in _dangling(rep)[0]
    # It must be reported as the non-verdict finding it is — i.e. the gate
    # DID find an intact chain and reported the other one anyway. Without
    # this, the assertion above would also be satisfied by the old
    # all-chains-broken path, which is a different fact.
    assert rep.get("sby", "").endswith("subservient.sby"), rep
    assert not any(f.startswith("SBY_CHAIN_BROKEN") for f in rep["findings"])
