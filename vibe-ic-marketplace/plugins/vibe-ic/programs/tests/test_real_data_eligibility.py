#!/usr/bin/env python3
"""vibe-ic#1037 — "real" must be a CHECKED property, not a hope.

WHAT WENT WRONG
===============
`test_si_signoff_timing_aware._real_spef()` — whose whole contract is "return
REAL extraction output, from a published run" — fell back to an unbounded
`root.rglob("*.spef")` when its three named `benchmark-data/` candidates were
missing. Those candidates sit under run roots being withdrawn from publication
(#1015/#1010), so the fallback became the only live branch — and the only
`*.spef` under that walk root are THIS SUITE'S OWN FIXTURES.

THE RED WAS LUCK
================
Two tests named `test_real_spef_*` went red, but only because the nearest
fixture is zero-coupling by construction and the assertion is
`len(pair_cc) > 0`. That is a coincidence, not a check, and this module exists
because the coincidence was one walk-order away from not happening:
`test_the_luck_was_real_and_thin` MEASURES that a fixture already in this tree
satisfies every assertion in both tests.

WHAT IS PINNED HERE
===================
1. THE TRAP IS LIVE. The planted decoy — and the pre-existing `si_mcf` coupled
   fixture — satisfy every assertion the two real-data tests make. A control
   that a fixture happens to fail would prove nothing.
2. THE DECOY IS REFUSED ANYWAY, and refused by the `benchmark-data/` shape rule
   rather than by a fixture-directory name, so the rule does not depend on
   guessing what the next fixture tree will be called.
3. A ZERO DENOMINATOR REFUSES. With nothing eligible, selection returns no path
   and a reason naming the absence — never "use whatever the walk yields".
   (`gate_zero_denominator_refuses_check` is the house rule.)
4. THE PAIRED GUARD. A genuinely published artefact is ACCEPTED. A selector
   that refuses everything is a ban, not a check, so acceptance is proved
   against a synthetic published tree — which keeps the guard true even if the
   real corpus is withdrawn all the way to zero.
5. THE INDEX IS THE CANDIDATE SET. A file at a perfectly published-shaped path
   that is not in the git index is refused, so nothing a test writes at runtime
   can ever be selected (#1029).

chip-AGNOSTIC: path shape and git index only; no design, PDK or vendor token.
"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

import _real_data as rd
import si_signoff_timing_aware as m
from _hostpaths import REPO_ROOT

_TESTS = Path(__file__).resolve().parent

#: The planted control (see fixtures/real_data_decoy/README.md): published
#: directory shape, published filename, git-tracked, non-empty, and carrying a
#: coupling pair — everything the two real-data tests require. Refused solely
#: because it is not under `benchmark-data/`.
DECOY = _TESTS / "fixtures" / "real_data_decoy" / "phase3" / "stage3" / \
    "extracted" / "chip_top.spef"

#: The fixture that was ALREADY in this tree when #1037 was filed, and that the
#: old `rglob` fallback yielded third. `pair_cc == 1`.
INTREE_COUPLED = _TESTS / "fixtures" / "si_mcf_zero_coupling" / "coupled" / \
    "design.spef"


# ===========================================================================
# helpers
# ===========================================================================
def _assertions_of_the_real_spef_tests(p: Path) -> dict:
    """Every assertion `test_real_spef_parses_and_attributes` and
    `test_real_spef_scores_with_synthetic_windows` make, evaluated on *p*.

    Kept literal rather than imported so this control states, in one place,
    exactly what "would have passed" means.
    """
    sp = m.parse_spef(p.read_text(errors="replace"))
    real_nets = (set(sp["cg"]) | set(sp["net_driver_pins"])
                 | set(sp["net_load_pins"]))
    leaked = [n for pr in sp["pair_cc"] for n in pr if n not in real_nets]
    pins = {}
    for drivers in sp["net_driver_pins"].values():
        for d in drivers:
            pins[d] = {"arr_rise_min": 0.0, "arr_rise_max": 1.0,
                       "arr_fall_min": 0.0, "arr_fall_max": 1.0,
                       "slew_rise_max": 0.05, "slew_fall_max": 0.05}
    v = m.score_si_timing_aware(p.read_text(errors="replace"), {"pins": pins},
                                vdd_v=1.8, noise_margin_mv=100.0)
    return {
        "pair_cc_nonempty": len(sp["pair_cc"]) > 0,
        "name_map_nonempty": len(sp["name_map"]) > 0,
        "drivers_nonempty": len(sp["net_driver_pins"]) > 0,
        "no_leaked_nets": leaked == [],
        "verdict_is_the_advisory": v["verdict"] == "SI_TIMING_AWARE_SCREEN",
        "nets_analyzed_positive": v["nets_analyzed"] > 0,
        "coupling_pairs_positive": v["coupling_pairs"] > 0,
        "noise_bound_holds":
            0.0 <= v["max_gated_noise_mv"] <= v["max_base_noise_mv"] + 1e-6,
        "watchlist_partition_consistent":
            v["watchlist_count"] == v["watchlist_high_count"]
            + v["watchlist_low_count"],
    }


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


@pytest.fixture
def synthetic_repo(tmp_path, monkeypatch):
    """A real git repo standing in for the monorepo root.

    Returns ``(root, add)`` where ``add(rel, text, *, track=True)`` writes and
    optionally commits a file. Repointing ``_real_data.REPO_ROOT`` (and busting
    the index cache) is what lets the rule be exercised on trees this repo does
    not, and must not, contain.
    """
    root = tmp_path / "monorepo"
    (root / "vibe-ic-marketplace").mkdir(parents=True)
    _git(root.parent, "init", "-q", str(root))
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")

    def add(rel: str, text: str = "x\n", *, track: bool = True) -> Path:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        if track:
            _git(root, "add", "-f", "--", rel)
            _git(root, "commit", "-q", "-m", f"add {rel}")
        return p

    monkeypatch.setattr(rd, "REPO_ROOT", root)
    rd._tracked.cache_clear()
    yield root, add
    # defensive: a test may itself have replaced `_tracked` (see the
    # unreadable-index leg), and teardown must not depend on that not happening.
    getattr(rd._tracked, "cache_clear", lambda: None)()


# ===========================================================================
# 1 — the trap is LIVE: a fixture that would have passed
# ===========================================================================
def test_the_luck_was_real_and_thin(record_property):
    """The coincidence that produced the red was one walk-order away.

    #1037 says a fixture carrying coupling pairs "would have made both tests
    PASS while examining nothing real". It is not hypothetical: the fixture was
    already in the tree, third in the very walk the old fallback used. This
    measures it, so the control cannot quietly stop being a control.
    """
    results = _assertions_of_the_real_spef_tests(INTREE_COUPLED)
    record_property("intree_fixture", rd.provenance(INTREE_COUPLED))
    record_property("assertions", results)
    failing = [k for k, ok in results.items() if not ok]
    assert failing == [], (
        f"{rd.provenance(INTREE_COUPLED)} no longer satisfies "
        f"{failing} — this fixture is the measured proof that the old "
        f"fallback's red was walk-order luck. If the fixture legitimately "
        f"changed, re-derive the claim in #1037's record; do not delete it."
    )


def test_the_planted_decoy_would_have_passed_both_real_spef_tests(record_property):
    """The planted decoy is a live trap, not a straw man.

    A negative control that a selector rejects for the wrong reason — because
    it happens to be unsuitable — proves nothing. This one is suitable.
    """
    assert DECOY.is_file(), f"the planted control is missing: {DECOY}"
    results = _assertions_of_the_real_spef_tests(DECOY)
    record_property("decoy", rd.provenance(DECOY))
    record_property("assertions", results)
    failing = [k for k, ok in results.items() if not ok]
    assert failing == [], (
        f"the decoy fixture stopped satisfying {failing}; it must keep "
        f"satisfying EVERY assertion the real-data tests make, or refusing it "
        f"proves nothing. See fixtures/real_data_decoy/README.md."
    )


# ===========================================================================
# 2 — and it is refused anyway, by the SHAPE rule
# ===========================================================================
def test_the_planted_decoy_is_refused(record_property):
    why = rd.why_not_published(DECOY)
    record_property("refusal", why)
    assert why is not None, (
        "the planted decoy was accepted as published run output. It is a "
        "hand-authored fixture; accepting it is exactly the defect #1037 "
        "records — a real-data selector with no rule forbidding it from "
        "selecting non-real data."
    )
    assert rd.PUBLICATION_ROOT in why, (
        f"the decoy was refused, but not by the publication-root rule: {why!r}. "
        f"The allow-list is the load-bearing rule; if a fixture-name backstop "
        f"is doing the work, the next fixture path defeats it."
    )


def test_the_decoy_is_not_refused_by_a_fixture_NAME():
    """The rule must not depend on guessing what fixtures get called.

    `real_data_decoy` is deliberately absent from `TEST_OWNED_NAMES`, and the
    components that ARE in it (`tests`, `fixtures`) are never reached, because
    the `benchmark-data/` rule refuses the path first. So this decoy proves the
    allow-list works on a directory name the deny-list has never heard of.
    """
    parts = DECOY.resolve().relative_to(REPO_ROOT.resolve()).parts
    assert "real_data_decoy" not in rd.TEST_OWNED_NAMES
    assert any(p in rd.TEST_OWNED_NAMES for p in parts), (
        "precondition changed: the decoy no longer lives under a test-owned "
        "component, which weakens what this test demonstrates"
    )
    assert rd.PUBLICATION_ROOT in rd.why_not_published(DECOY)


def test_every_intree_spef_fixture_is_refused(record_property):
    """No `*.spef` under any test tree is eligible — measured over the index,
    not argued from one example."""
    tracked = rd._index_candidates(".spef")
    assert tracked, "zero tracked '*.spef' — refusing to report a green run " \
                    "over an empty population"
    fixtures = [p for p in tracked
                if "fixtures" in rd.provenance(p).split("/")]
    record_property("tracked_spef", len(tracked))
    record_property("fixture_spef", len(fixtures))
    assert fixtures, "no fixture SPEF in the index — this check has no teeth"
    accepted = [rd.provenance(p) for p in fixtures if rd.is_published(p)]
    assert accepted == [], f"fixture SPEFs accepted as published output: {accepted}"


# ===========================================================================
# 3 — the selector at the defect site never leaves benchmark-data/
# ===========================================================================
def test_the_si_selector_returns_published_output_or_refuses(record_property):
    """The one invariant, independent of how big the corpus is.

    Two outcomes are allowed and there is no third: a path under
    `benchmark-data/`, or a refusal that names the absence. "Whatever the walk
    yields" is not an outcome.
    """
    tsa = pytest.importorskip("test_si_signoff_timing_aware")
    sel = tsa._real_spef()
    record_property("selection", sel.reason)
    if sel.path is None:
        assert ("REAL-DATA ANCHOR LOST" in sel.reason
                or "no '.spef' artefact is published" in sel.reason
                or "REAL-DATA REQUIREMENT UNMET" in sel.reason), (
            f"a refusal must name WHICH absence occurred: {sel.reason!r}")
        return
    rel = rd.provenance(sel.path)
    assert rel.startswith(rd.PUBLICATION_ROOT + "/"), (
        f"the real-SPEF selector returned {rel}, which is not published run "
        f"output")
    assert rd.is_published(sel.path)
    assert len(m.parse_spef(sel.path.read_text(errors="replace"))["pair_cc"]) > 0


# ===========================================================================
# 4 — PAIRED GUARD: a published artefact IS accepted
# ===========================================================================
def test_a_published_artefact_is_accepted(synthetic_repo):
    """A selector that refuses everything is a ban, not a check.

    Proved against a synthetic published tree so the guard survives the corpus
    being withdrawn to zero (#1015/#1010) — the acceptance property belongs to
    the RULE, not to whatever happens to still be committed today.
    """
    root, add = synthetic_repo
    good = add("benchmark-data/ic/x/v1.0_p/phase3/stage3/extracted/x.spef")
    assert rd.why_not_published(good) is None, rd.why_not_published(good)
    assert rd.published_artifacts(".spef") == [good]
    sel = rd.select(".spef", lambda p: True, "any", label="paired-guard")
    assert sel.path == good


def test_the_real_corpus_still_contains_an_accepted_artefact(record_property):
    """The same guard against TODAY'S real tree, disclosed rather than assumed.

    If the withdrawal campaign eventually empties this, the honest outcome is a
    skip naming the absence — not a green run over nothing, and not a deletion
    of the guard.
    """
    eligible = rd.published_artifacts(".spef")
    tracked = rd._index_candidates(".spef")
    record_property("eligible", [rd.provenance(p) for p in eligible])
    record_property("eligible_of_tracked", f"{len(eligible)}/{len(tracked)}")
    if not eligible:
        pytest.skip(
            "no published '*.spef' survives in this checkout: "
            f"{len(tracked)} tracked path(s), 0 eligible. If the withdrawal "
            "campaign (#1015/#1010) has taken the last one, that is the "
            "permanent answer and this leg is correctly inert — the RULE's "
            "acceptance property is guarded by "
            "test_a_published_artefact_is_accepted, which needs no corpus.")
    assert all(rd.provenance(p).startswith(rd.PUBLICATION_ROOT + "/")
               for p in eligible)


# ===========================================================================
# 5 — a zero denominator REFUSES, and names the absence
# ===========================================================================
def test_zero_eligible_refuses_and_names_the_lost_anchor(synthetic_repo):
    """Fixtures present, published output absent — the exact #1037 state."""
    root, add = synthetic_repo
    decoy = add("vibe-ic-marketplace/plugins/vibe-ic/programs/tests/"
                "fixtures/f/phase3/stage3/extracted/chip_top.spef")
    sel = rd.select(".spef", lambda p: True, "any", label="zero-denominator")
    assert sel.path is None, (
        f"selection fell back to {sel.path} instead of refusing — this is the "
        f"defect verbatim")
    assert "REAL-DATA ANCHOR LOST" in sel.reason
    assert "fixtures/f/phase3/stage3/extracted/chip_top.spef" in sel.reason, (
        "a refusal must NAME the path it refused, so the reader can see the "
        f"premise rather than infer it: {sel.reason!r}")
    assert sel.eligible == 0 and sel.considered == 1


def test_the_refused_fixture_survives_truncation(synthetic_repo):
    """A refusal that lists "the first 8 by path" hides its own point.

    Refused paths sort by name, so `benchmark-data/...` fills the list and the
    refused FIXTURE — the thing the reader most needs to see — falls off under
    "and N more". Grouping by REASON means every distinct reason gets a line,
    so "a fixture was refused" is always visible however large the population.
    """
    root, add = synthetic_repo
    for i in range(12):
        add(f"benchmark-data/ic/x/v/phase3/.phase3_held/s/w{i:02d}.spef")
    add("vibe-ic-marketplace/plugins/vibe-ic/programs/tests/fixtures/"
        "decoy/phase3/stage3/extracted/chip_top.spef")
    sel = rd.select(".spef", lambda p: True, "any", label="truncation")
    assert sel.path is None
    assert "fixtures/decoy/phase3/stage3/extracted/chip_top.spef" in sel.reason, (
        f"the refused fixture was truncated out of the refusal:\n{sel.reason}")


def test_a_withdrawn_artefact_is_named_as_withdrawn(synthetic_repo):
    """"Tracked but gone" is the withdrawal signature (#1015/#1010/#1028) and
    must not be reported as the same absence as "never published here"."""
    root, add = synthetic_repo
    p = add("benchmark-data/ic/x/v/phase3/stage3/extracted/x.spef")
    p.unlink()
    why = rd.why_not_published(p)
    assert why is not None and "ABSENT from the working tree" in why, why


def test_an_empty_index_says_so_differently(synthetic_repo):
    """"Nothing was ever here" and "what was here is gone" are different
    absences and must not share one message."""
    root, add = synthetic_repo
    sel = rd.select(".spef", lambda p: True, "any", label="empty-index")
    assert sel.path is None
    assert "REAL-DATA ANCHOR LOST" not in sel.reason
    assert "no '.spef' artefact is published in this checkout" in sel.reason


def test_eligible_but_requirement_unmet_is_its_own_refusal(synthetic_repo):
    """Selection states its requirement; it does not hand the caller a file and
    let the assertion discover the mismatch."""
    root, add = synthetic_repo
    add("benchmark-data/ic/x/v/phase3/stage3/extracted/x.spef")
    sel = rd.select(".spef", lambda p: False, "carries coupling pairs",
                    label="requirement")
    assert sel.path is None
    assert "REAL-DATA REQUIREMENT UNMET" in sel.reason
    assert "carries coupling pairs" in sel.reason
    assert sel.eligible == 1


def test_a_requirement_that_raises_is_unmet_not_selected(synthetic_repo):
    root, add = synthetic_repo
    add("benchmark-data/ic/x/v/phase3/stage3/extracted/x.spef")

    def boom(_p):
        raise ValueError("unparseable")

    sel = rd.select(".spef", boom, "parses", label="raises")
    assert sel.path is None
    assert "ValueError" in sel.reason


# ===========================================================================
# 6 — the allow-list, leg by leg
# ===========================================================================
def test_the_index_is_the_candidate_set(synthetic_repo):
    """A runtime write at a perfectly published-shaped path is NOT published.

    Publication in this repo IS the commit (#1029: the suite wrote into the
    tree the next gate reads). Shape alone must not be enough.
    """
    root, add = synthetic_repo
    untracked = add("benchmark-data/ic/x/v/phase3/stage3/extracted/w.spef",
                    track=False)
    why = rd.why_not_published(untracked)
    assert why is not None and "git-tracked" in why, why
    assert rd.published_artifacts(".spef") == []


def test_a_held_tree_is_not_published(synthetic_repo):
    """`phase3/.phase3_held/` is a backup tree, excluded from publication —
    the same exclusion `_path_layout` documents for the clock-plan sweep."""
    root, add = synthetic_repo
    held = add("benchmark-data/ic/x/v/phase3/.phase3_held/stage3/"
               "extracted/x.spef")
    why = rd.why_not_published(held)
    assert why is not None and ".phase3_held" in why, why


def test_loose_data_outside_a_phase_is_not_run_output(synthetic_repo):
    root, add = synthetic_repo
    loose = add("benchmark-data/ic/x/notes/x.spef")
    why = rd.why_not_published(loose)
    assert why is not None and "flow-phase" in why, why


def test_a_fixture_smuggled_under_benchmark_data_hits_the_backstop(synthetic_repo):
    """The subordinate backstop, doing the job it is actually for.

    It is not the load-bearing rule — nothing can reach it without already
    satisfying the publication root and the phase rule — but when something
    does, the reason should say `test-owned`, not something vaguer.
    """
    root, add = synthetic_repo
    smuggled = add("benchmark-data/ic/x/v/phase3/tests/fixtures/x.spef")
    why = rd.why_not_published(smuggled)
    assert why is not None and "test-owned" in why, why


def test_an_empty_published_file_is_not_a_usable_artefact(synthetic_repo):
    root, add = synthetic_repo
    empty = add("benchmark-data/ic/x/v/phase3/stage3/extracted/x.spef", "")
    why = rd.why_not_published(empty)
    assert why is not None and "empty" in why, why


def test_a_path_outside_the_monorepo_is_refused(tmp_path):
    outside = tmp_path / "elsewhere.spef"
    outside.write_text("x")
    why = rd.why_not_published(outside)
    assert why is not None and "outside the source monorepo" in why, why


def test_an_unreadable_index_refuses_rather_than_accepts(synthetic_repo,
                                                         monkeypatch):
    """Unverifiable is not verified.

    If the tracked set cannot be read (no git, a tarball export), the rule must
    refuse rather than fall through to shape alone — falling through is how a
    premise silently degrades from "real" to "any".
    """
    root, add = synthetic_repo
    good = add("benchmark-data/ic/x/v/phase3/stage3/extracted/x.spef")
    assert rd.why_not_published(good) is None
    rd._tracked.cache_clear()
    monkeypatch.setattr(rd, "_tracked", lambda: None)
    why = rd.why_not_published(good)
    assert why is not None and "git index is unreadable" in why, why


# ===========================================================================
# 7 — provenance is disclosed
# ===========================================================================
def test_every_selection_is_recorded_for_the_terminal_summary(synthetic_repo):
    """The suite must say which file it used. `conftest.pytest_terminal_summary`
    prints this ledger on EVERY run, so the next reader sees the premise."""
    root, add = synthetic_repo
    good = add("benchmark-data/ic/x/v/phase3/stage3/extracted/x.spef")
    before = len(rd.LEDGER)
    rd.select(".spef", lambda p: True, "any", label="disclosure-probe")
    new = rd.ledger_lines()[before:]
    assert any("disclosure-probe" in ln and "USED" in ln
               and "benchmark-data/ic/x/v/phase3/stage3/extracted/x.spef" in ln
               for ln in new), new


def test_a_refusal_is_recorded_too(synthetic_repo):
    root, add = synthetic_repo
    before = len(rd.LEDGER)
    rd.select(".spef", lambda p: True, "any", label="refusal-probe")
    new = rd.ledger_lines()[before:]
    assert any("refusal-probe" in ln and "REFUSED" in ln for ln in new), new


# ===========================================================================
# 8 — the defect site keeps no unbounded walk
# ===========================================================================
def test_the_si_selector_owns_no_unbounded_walk():
    """Source-pinned: the shape that caused #1037 must not come back.

    Selecting real data by walking the filesystem is the defect at the level of
    mechanism — the walk cannot distinguish the data the test was written to
    examine from the data the harness manufactured to stand in for it.
    """
    target = _TESTS / "test_si_signoff_timing_aware.py"
    tree = ast.parse(target.read_text())
    names = {n.name for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "_real_spef" in names, (
        "the selector under audit is gone; re-point this test rather than "
        "deleting it")
    walks = [
        f"{node.lineno}:{node.func.attr}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("glob", "rglob", "walk", "iterdir", "scandir")
    ]
    # AST, not text search: the module's own PROSE quotes the offending call
    # deliberately, and a grep that cannot tell a comment from a call is the
    # same category of mistake this issue is about.
    assert walks == [], (
        f"{target.name} regained a filesystem walk at {walks} — real-data "
        f"selection must come from the git index, not from a walk (#1037)")
