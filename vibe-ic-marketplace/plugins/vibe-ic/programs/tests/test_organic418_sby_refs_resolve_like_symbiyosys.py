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
import _corpus_guard as CG  # noqa: E402


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
    """End-to-end. The dangling-chain finding that a permissive resolver
    silenced must appear, and it must appear on its OWN — this test's subject
    is the resolver, so the assertion has to be about the resolver's finding
    and not about whatever else the manifest happens to satisfy.

    It used to assert `verdict == "PASS"`. #1974 put a completion contract on
    the same manifest and this cell was published before that contract existed,
    so the verdict is now FAIL on the one obligation the cell genuinely never
    stated — its property denominator. G15 argued that FAIL rather than
    grandfathering it: `property_denominator` is not an alias of any earlier
    field (`property_count` counts .sby TASKS — this cell's 2 are `bmc` and
    `safety`), so a grandfather clause could not READ the denominator, only
    assume one, and "proof evidence without a denominator is a claim about a
    subset nobody stated" is a fact about the manifest, not about its date.
    What G15 DID fix is the other three findings this cell used to carry:
    `bounded_vs_unbounded_scope` / `elaborated_sby` / `proof_transcript` are
    unconditional aliases the emitter derives from `bounded_vs_unbounded` /
    `sby` / `evidence`, and this cell cites all three under the older name.

    So the verdict is pinned FAIL, and pinned to the EXACT #1974 finding it is
    allowed to be FAIL for — which is a stronger control than the bare PASS it
    replaces, because it can now tell the resolver's subject apart from the
    completion contract.
    """
    c = (CG.corpus_root(_PROGRAMS) / "spm" / "v1.5.58_ihp-sg13g2")
    if not (c / "phase2/stage1/formal/reset_safety").is_dir():
        CG.require_corpus(c, "the cell that motivated #417")
        pytest.skip("published cell present but not in its #417 shape")
    rep = F.audit(c)
    dang = [f for f in rep["findings"] if f.startswith("SBY_REFS_DANGLING")]
    assert dang and "spm_reset_safety.sby" in dang[0], rep["findings"]
    assert "spm.v" in dang[0], dang[0]
    assert rep["verdict"] == "FAIL", rep["findings"]
    contract = sorted(f.split(" ")[0] for f in rep["findings"]
                      if "#1974" in f)
    assert contract == ["PROPERTY_DENOMINATOR_MISSING"], rep["findings"]


def test_the_other_published_cells_keep_their_verdicts():
    """The corpus guard, and the place G15's decision is written down.

    A resolver change CAN move verdicts, unlike #417; measured 0 of 27 and
    pinned here so a future loosening has to argue. That is still what this
    test does — but the two cells it named are no longer PASS, and the reason
    is not the resolver.

    #1974 (`2a9d21368d`) added the Step-5 COMPLETION contract and migrated the
    EMITTER in the same commit. It did not migrate, regenerate or grandfather
    what had ALREADY been published, so every published cell with a `formal/`
    began auditing FAIL on four findings. Three of those four were the gate
    reading a NAME: `bounded_vs_unbounded_scope`, `elaborated_sby` and
    `proof_transcript` are aliases the emitter sets unconditionally from
    `bounded_vs_unbounded`, `sby` and `evidence`, so a manifest citing the fact
    under the older name had cited it. G15 fixed that in the gate.

    The fourth is real and stays. `property_denominator` is not an alias of
    anything: it is read from the harness and the obligation contract, and
    nothing before #1974 carried it. Neither disposal the situation offers is
    available to a grandfather clause — the gate cannot READ a denominator the
    manifest never stated, and asserting one on the cell's behalf would invent
    a measurement nobody made, which is the same sin as relabelling in the
    other direction. So these cells are FAIL, and honestly so: they claim
    `all_proved` over a scope they never declared, which is exactly the claim
    #1974 exists to refuse.

    Pinned per-cell to the exact #1974 finding set, so this test now
    distinguishes "the contract is missing" from "the chain is broken" — the
    distinction it could not make when it pinned a bare verdict, and the reason
    the relabelling went two campaigns unnoticed.

    #417's own corpus test refuses to assert a verdict at all, and its reason
    applies here: a published cell's verdict is partly a property of how
    COMPLETE the checkout is (`.gitignore:31 *.log` drops
    `sby_subservient.log`, so `EVIDENCE_MISSING` fires or not depending on
    whether a local run directory sits beside the tree). What is pinned below
    is chosen to be immune to that. FAIL is stable under an incomplete
    checkout because missing files can only ADD findings, never remove
    `PROPERTY_DENOMINATOR_MISSING` — it was the PASS this test used to assert
    that was fragile in exactly the way #417 describes. And the #1974 finding
    set is a pure function of `results.json`'s CONTENT: every clause in (d)
    reads the manifest, none of them dereferences a path, save the expert
    receipt these manifests never request. So neither assertion can be moved
    by a file that is or is not beside the checkout.
    """
    root = CG.require_corpus(CG.corpus_root(_PROGRAMS), "published-cell verdicts")
    seen = {}
    contract = {}
    for f in sorted(root.rglob("phase2/stage1/formal")):
        if f.is_dir():
            rep = F.audit(f.parents[2])
            seen[str(f.parents[2])] = rep["verdict"]
            contract[str(f.parents[2])] = sorted(
                x.split(" ")[0] for x in rep["findings"] if "#1974" in x)
    if not seen:
        pytest.skip("no cells with formal/")
    bad = {k: v for k, v in seen.items() if v not in
           ("PASS", "FAIL", "SKIPPED-CONDITION")}
    assert not bad, bad
    ihp = str(root / "spm" / "v1.5.58_ihp-sg13g2")
    sub = str(root / "subservient")
    assert seen.get(ihp) == "FAIL", seen
    assert seen.get(sub) == "FAIL", seen
    # The denominator, and ONLY the denominator, for the cell whose manifest
    # carries every other obligation under its pre-#1974 name.
    assert contract.get(ihp) == ["PROPERTY_DENOMINATOR_MISSING"], contract
    # subservient's manifest is an older shape again: it states no bounded /
    # unbounded scope under EITHER name, so its scope finding is a genuinely
    # absent fact and must survive the alias fix.
    assert contract.get(sub) == ["PROOF_SCOPE_MISSING",
                                 "PROPERTY_DENOMINATOR_MISSING"], contract
