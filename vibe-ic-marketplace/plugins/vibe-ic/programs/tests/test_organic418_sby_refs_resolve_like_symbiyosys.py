#!/usr/bin/env python3
"""ORGANIC #418 — `_resolve` was more permissive than SymbiYosys, so a `.sby`
that `sby -f` could not run was reported as elaboratable.

The function's docstring already said "relative to the .sby dir". The code had
never used the .sby dir; it resolved against `formal_dir`. For a `.sby` at the
top of `formal/` those are the same directory, so the difference was
unobservable — until #412 made NESTED `.sby` files discoverable. After that,
`reset_safety/spm_reset_safety.sby` naming a bare `spm.v` (which SymbiYosys
reads as `reset_safety/spm.v`, absent) resolved to `formal/spm.v` one level
up. That is why #417's new dangling-chain finding did not fire on the very
cell that motivated it.

MEASURED across every `.sby` in the published corpus before changing
anything: 7 references resolve from the `.sby`'s own directory, 3 from the
#550(a) staging fallback, 1 only from `formal_dir` — the false clean — 2 are
genuinely unresolved, and ZERO used the unrestricted `rglob(basename)` last
resort. So that last resort could go; the staging fallback could not.

AFTER: 27 cells, ZERO verdict changes, exactly one findings change — the ihp
cell gains the true dangling-chain finding it should have had.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import formal_proof_evidence_check as F  # noqa: E402


@pytest.fixture
def cell(tmp_path):
    d = tmp_path / "phase2" / "stage1" / "formal"
    (d / "nested").mkdir(parents=True)
    return tmp_path


def _r(cell, sby_dir, token):
    formal = cell / "phase2" / "stage1" / "formal"
    return F._resolve(sby_dir, formal, cell, token)


def test_a_bare_name_does_not_reach_one_level_up(cell):
    """THE DEFECT. SymbiYosys resolves `[files]` relative to the .sby's own
    directory, so this reference names `nested/dut.v` and there is none."""
    formal = cell / "phase2" / "stage1" / "formal"
    (formal / "dut.v").write_text("module dut; endmodule\n")
    assert _r(cell, formal / "nested", "dut.v") is None


def test_the_paired_half_a_bare_name_beside_the_sby_resolves(cell):
    formal = cell / "phase2" / "stage1" / "formal"
    (formal / "nested" / "dut.v").write_text("module dut; endmodule\n")
    got = _r(cell, formal / "nested", "dut.v")
    assert got is not None and got.parent.name == "nested"


def test_a_top_level_sby_is_unaffected(cell):
    """The shape that was always right must stay right — for a .sby at the
    top of formal/, its own directory IS formal/."""
    formal = cell / "phase2" / "stage1" / "formal"
    (formal / "dut.v").write_text("x\n")
    assert _r(cell, formal, "dut.v") is not None


def test_the_550a_staging_fallback_survives(cell):
    """Three references in the corpus depend on this: after a real run the
    original source can be gone and the evidence lives only where SymbiYosys
    staged it. Removing it would false-FAIL genuinely proved cells."""
    formal = cell / "phase2" / "stage1" / "formal"
    staged = formal / "task" / "src"
    staged.mkdir(parents=True)
    (staged / "dut.v").write_text("module dut; endmodule\n")
    got = _r(cell, formal, "dut.v")
    assert got is not None and got.parent.name == "src"


def test_an_unrelated_same_named_file_no_longer_satisfies_a_reference(cell):
    """The removed last resort: ANY file of the right name anywhere beneath
    formal/ used to count. A name match in an unrelated directory is not
    evidence that the .sby could elaborate."""
    formal = cell / "phase2" / "stage1" / "formal"
    other = formal / "some_other_proof"
    other.mkdir()
    (other / "dut.v").write_text("a different dut\n")
    assert _r(cell, formal, "dut.v") is None


def test_a_project_relative_reference_still_resolves(cell):
    """`constraints.sby: rtl/*.sv` in the corpus is this shape; the project
    base is what it is for."""
    (cell / "rtl").mkdir()
    (cell / "rtl" / "top.v").write_text("x\n")
    formal = cell / "phase2" / "stage1" / "formal"
    assert _r(cell, formal, "rtl/top.v") is not None


def test_a_glob_resolves_from_the_sby_dir_not_the_formal_root(cell):
    formal = cell / "phase2" / "stage1" / "formal"
    (formal / "up.sv").write_text("x\n")
    assert _r(cell, formal / "nested", "*.sv") is None
    (formal / "nested" / "here.sv").write_text("x\n")
    got = _r(cell, formal / "nested", "*.sv")
    assert got is not None and got.name == "here.sv"


def test_the_cell_that_motivated_417_now_reports_its_dangling_chain():
    """End-to-end. The verdict must NOT move — the claim results.json makes
    is still substantiated by the chain it cites — while the finding that was
    silenced by a permissive resolver appears."""
    c = (_PROGRAMS.parents[3] / "benchmark-data" / "ic" / "spm"
         / "v1.5.58_ihp-sg13g2")
    if not (c / "phase2/stage1/formal/reset_safety").is_dir():
        pytest.skip("published cell not present")
    rep = F.audit(c)
    assert rep["verdict"] == "PASS", rep["findings"]
    dang = [f for f in rep["findings"] if f.startswith("SBY_REFS_DANGLING")]
    assert dang and "spm_reset_safety.sby" in dang[0], rep["findings"]
    assert "spm.v" in dang[0], dang[0]


def test_the_other_published_cells_keep_their_verdicts():
    """The corpus guard. A resolver change CAN move verdicts, unlike #417;
    measured 0 of 27 and pinned here so a future loosening has to argue."""
    root = _PROGRAMS.parents[3] / "benchmark-data" / "ic"
    if not root.is_dir():
        pytest.skip("corpus not present")
    seen = {}
    for f in sorted(root.rglob("phase2/stage1/formal")):
        if f.is_dir():
            seen[str(f.parents[2])] = F.audit(f.parents[2])["verdict"]
    if not seen:
        pytest.skip("no cells with formal/")
    bad = {k: v for k, v in seen.items() if v not in
           ("PASS", "FAIL", "SKIPPED-CONDITION")}
    assert not bad, bad
    # the three that are not SKIPPED-CONDITION are the ones this touches
    assert seen.get(str(root / "spm" / "v1.5.58_ihp-sg13g2")) == "PASS"
    assert seen.get(str(root / "subservient")) == "PASS"
