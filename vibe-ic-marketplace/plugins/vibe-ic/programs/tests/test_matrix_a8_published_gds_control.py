"""BIDIRECTIONAL CONTROL for the A8/d3 waiver removal (2026-08-06).

WHAT WENT WRONG, AND WHAT CAUGHT IT
===================================
``matrix_63x8.waivers`` carried a waiver for cell A8 / dimension 3 whose
``evidence`` field asserted, verbatim::

    "`git ls-tree -r --name-only HEAD` matches ZERO paths against
     phase3/analog/hardmacro/*/*.gds"

Commit b1665ec8 published
``benchmark-data/ic/u_hawaii_adc/v1.9.86_sky130A/phase3/analog/hardmacro/
{delta_sigma,ldo}/*.gds`` — 111096 B and 641262 B — so the same command matches
2, and ``test_matrix_d3_outputs_produced.py::
test_d3_waived_unproven_entries_have_no_committed_artefact`` turned the suite
red with exactly the right sentence: *the premise is false and the waiver must
be re-argued or removed*. That is the anti-rot mechanism working. The waiver
was REMOVED, not re-argued, because it had written down its own closing
condition — "Closing this needs a published analog run whose A8 actually
streamed the layout" — and b1665ec8 is that publication.

WHY THIS FILE EXISTS SEPARATELY
===============================
A fix like this has two ways to go wrong and they pull in opposite directions:

* it can fail to actually close the gap (the waiver goes but the cell is red,
  or green only on a host with an EDA container), and
* it can close it by ADMITTING TOO MUCH — "any directory under
  benchmark-data/ic counts as evidence" would make this cell green and quietly
  make the whole dimension unfalsifiable.

So the forward case and the reverse cases are asserted here together, and the
reverse cases are written so they hold on the PRE-FIX tree as well: they are
what must not have changed.

  FORWARD  ``test_control_a8_gds_is_produced_and_evidenced_from_the_commit``
           ``test_control_the_published_root_is_named_in_the_manifest_and_is_in_repo``
           ``test_control_a_published_cell_must_show_a_converged_verdict``
           All three FAIL on the byte-identical pre-fix ``matrix_63x8/
           waivers.py`` + ``fixtures/matrix_d3_output_manifest.json`` (the
           waiver is present, the entry is recorded UNPROVEN and the published
           root is not registered, so the resolver reports the entry
           unproduced) and PASS after. The third also asserts the new rule's
           own both-directions behaviour, so "admit everything" cannot pass it.

  REVERSE  ``test_reverse_the_other_dimension3_waiver_premises_are_still_true``
           ``test_reverse_admissibility_still_refuses_what_it_refused``
           GREEN BEFORE AND AFTER. Steps 6, 39 and M1 stay waived on premises
           that are still true (re-executed against ``git ls-tree``, the same
           question A8's premise failed), and a 0-byte, symlinked or untracked
           match on A8's own glob is still refused while the identical bytes,
           once committed, are still accepted.

WHEN THE PUBLISHED CELL IS NOT IN THIS CHECKOUT
===============================================
The two FORWARD controls read ``benchmark-data/ic/u_hawaii_adc/v1.9.86_sky130A``
— a PUBLISHED CELL, and published cells now live in
https://github.com/vibeic/benchmark-data. Where that corpus is not here they
SKIP, naming it (``_published_corpus.needs_corpus``), because "the layouts are
not in this tree" is *I could not look*, not *the layouts were never published*
— and a failure would assert the second. Point ``VIBE_IC_BENCHMARK_DATA`` at a
clone and they run exactly as before, red included.

The claims they made that DO NOT need the cell — A8 still declares the ``.gds``,
and dimension 3's accepted-gap registry is exactly ``{6, 39}`` — moved into
``test_control_a8_still_declares_the_gds_and_keeps_no_waiver_for_it`` so the
corpus's absence cannot quietly stop enforcing them. The third FORWARD control
and both REVERSE ones build their own throwaway trees and are unaffected.
"""
from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from matrix_63x8 import flowref as F
from matrix_63x8 import waivers as W

import _plugin_tree

from _published_corpus import needs_corpus

import test_matrix_d3_outputs_produced as D3

#: A8's declared GDS entry, spelled once.
A8_GDS = "phase3/analog/hardmacro/*/*.gds"


def _repo() -> Path:
    repo = _plugin_tree.repo_root()
    if repo is None:
        pytest.skip(f"needs the source tree: {_plugin_tree.NOT_SHIPPED_REASON}")
    return repo


def _tracked_matching(repo: Path, pattern: str):
    """Paths tracked at HEAD anywhere in the repo that match *pattern*.

    The same two-form match the waiver-premise guard uses (anchored, and
    ``*/``-prefixed for a pattern that is relative to a run root), so this
    control and the guard cannot disagree about what "the commit carries it"
    means.
    """
    tracked = D3.tracked_under(repo)
    return sorted(
        t for t in tracked
        if fnmatch.fnmatch(t, pattern) or fnmatch.fnmatch(t, f"*/{pattern}")
    )


# ──────────────────────────────────────────────────────────────────────
# FORWARD — red before the fix, green after
# ──────────────────────────────────────────────────────────────────────
def test_control_a8_still_declares_the_gds_and_keeps_no_waiver_for_it():
    """The half of the FORWARD control that is about THIS repository.

    Split out of ``test_control_a8_gds_is_produced_and_evidenced_from_the_commit``
    when the published cells moved to ``vibeic/benchmark-data``. That control
    reads a published artefact and therefore has to skip where there is none —
    but two of its claims never read one: A8 still DECLARES the ``.gds`` entry,
    and dimension 3's accepted-gap registry is exactly ``{6, 39}``. Both are
    facts about ``matrix_63x8``, they are checkable in any checkout, and letting
    them travel inside the corpus-dependent test would have made the corpus's
    absence quietly stop enforcing them — the registry could be emptied or grown
    and nothing here would notice.
    """
    assert A8_GDS in F.required_outputs("A8"), (
        f"A8 no longer declares {A8_GDS!r}; this control is stale and must be "
        f"re-pointed rather than deleted")

    assert W.waiver_for("A8", 3) is None, (
        "A8/d3 was closed by a published artefact, so an accepted-gap entry for "
        "it would be a waiver for a gap that is closed — the exact rot "
        "`strict=True` and the premise re-check exist to prevent.")

    # And the registry lost EXACTLY that one entry. Stated as an equality
    # because "A8 is gone" is also true of a registry somebody emptied.
    # M1 REMOVED 2026-08-14. vibe-ic#1159 (`bcd444425`) unpublished the
    # mixed-signal steps: M1's dimension-3 entry stopped being an accepted GAP
    # and became NA_DORMANT_CONDITION -- its condition is met nowhere, so there
    # is no gap left to disclose.
    waived = {W.flowref.normalize_id(w.step_id) for w in W.waivers_for_dim(3)}
    assert waived == {"6", "39"}, (
        f"dimension 3's waived set is {sorted(waived)}; after A8's removal "
        f"and #1159's unpublishing of M1 it must be exactly 6 and 39. A "
        f"missing entry means an accepted gap "
        f"stopped being disclosed; an extra one means a new gap arrived "
        f"without review.")


@needs_corpus
def test_control_a8_gds_is_produced_and_evidenced_from_the_commit():
    """A8's ``.gds`` is produced, the commit proves it, and no waiver survives.

    Four claims, in the order a reviewer would want them:

    1. the flow still DECLARES the entry (otherwise the rest is about nothing);
    2. the COMMIT carries at least one artefact matching it — the fact that
       made the old waiver's premise false;
    3. every such artefact is a real hardmacro layout for the block directory
       it sits in, checked with the plugin's own GDSII parsers, so "the commit
       carries a file with the right name" is not mistaken for evidence; and
    4. the dimension's own resolver reaches it LIVE, from a root inside this
       repository — and therefore no waiver for A8/d3 may exist.

    Pre-fix this fails at (4) on both halves: the manifest records the entry
    ``UNPROVEN`` and no admissible run root carries it, and
    ``matrix_63x8.waivers`` still holds the A8/d3 entry.
    """
    repo = _repo()

    # (1)
    assert A8_GDS in F.required_outputs("A8"), (
        f"A8 no longer declares {A8_GDS!r}; this control is stale and must be "
        f"re-pointed rather than deleted")

    # (2)
    hits = _tracked_matching(repo, A8_GDS)
    assert hits, (
        f"no path tracked at HEAD matches {A8_GDS!r}. This control asserts the "
        f"CLOSED state of A8/d3, which rests on commit b1665ec8 having "
        f"published the layouts. If they were removed, the honest move is to "
        f"restore the publication or re-open the waiver with a premise that is "
        f"true — not to delete this test.")

    # (3)
    problems = []
    for rel in hits:
        p = repo / rel
        raw = p.read_bytes()
        block = p.parent.name
        defined, _referenced, valid_header = D3.parse_structures(raw)
        if p.is_symlink():
            problems.append(f"{rel} is a symlink -> {os.readlink(p)}")
            continue
        if not valid_header:
            problems.append(f"{rel} ({len(raw)} B) has no GDSII HEADER record")
            continue
        if D3._gds_geometry_count(raw) <= 0:
            problems.append(
                f"{rel} ({len(raw)} B) carries no BOUNDARY/PATH/SREF/AREF/BOX "
                f"record — padding or an empty library, not a layout")
        if block not in defined:
            problems.append(
                f"{rel} defines {defined[:6]} and none of them is {block!r}, "
                f"the block directory it sits in")
    assert not problems, (
        "a tracked artefact matching A8's declared .gds is not a hardmacro "
        "layout:\n  " + "\n  ".join(problems))

    # (4)
    rec = D3.step_record("A8")["entries"][A8_GDS]
    verdict = D3.check_entry("A8", A8_GDS, rec)
    assert verdict.produced, (
        f"A8's {A8_GDS!r} is carried by this commit at {hits} and every match "
        f"is a real hardmacro layout, yet dimension 3 reports it unproduced: "
        f"{verdict.detail}")
    assert verdict.mode == D3.LIVE, (
        f"A8's {A8_GDS!r} was decided from the committed manifest "
        f"({verdict.mode}) rather than by looking at the artefact: "
        f"{verdict.detail}. The artefact is in the commit; there is nothing to "
        f"stand in for.")
    root = D3.run_roots().get(rec.get("run"))
    assert root is not None, (
        f"the manifest cites run root {rec.get('run')!r} for A8's .gds and it "
        f"does not resolve; the cell would be green on a fixture record")
    assert repo.resolve() in root.path.resolve().parents, (
        f"A8's evidence root {root.path} is not inside this repository (#527)")

    assert W.waiver_for("A8", 3) is None, (
        "A8/d3 resolves live from a committed artefact, so an accepted-gap "
        "entry for it would be a waiver for a gap that is closed — the exact "
        "rot `strict=True` and the premise re-check exist to prevent.")

    # And the registry lost EXACTLY that one entry. Stated as an equality
    # because "A8 is gone" is also true of a registry somebody emptied.
    # M1 REMOVED 2026-08-14. vibe-ic#1159 (`bcd444425`) unpublished the
    # mixed-signal steps: M1's dimension-3 entry stopped being an accepted GAP
    # and became NA_DORMANT_CONDITION -- its condition is met nowhere, so there
    # is no gap left to disclose. That commit moved `waivers.py`, the manifest
    # and `test_matrix_63x8_ledger.py`; it did not move this file.
    waived = {W.flowref.normalize_id(w.step_id) for w in W.waivers_for_dim(3)}
    assert waived == {"6", "39"}, (
        f"dimension 3's waived set is {sorted(waived)}; after A8's removal "
        f"and #1159's unpublishing of M1 it must be exactly 6 and 39. A "
        f"missing entry means an accepted gap "
        f"stopped being disclosed; an extra one means a new gap arrived "
        f"without review.")


@needs_corpus
def test_control_the_published_root_is_named_in_the_manifest_and_is_in_repo():
    """The new evidence root is registered, in-repo, and reachable by everyone.

    FORWARD case (red before the fix: the manifest does not name this root).
    #527's rule is that a verdict may not depend on the machine, and a
    published cell is admitted here only because the repository carries it —
    so that is asserted rather than assumed.
    """
    repo = _repo()
    label = "benchmark-data/ic/u_hawaii_adc/v1.9.86_sky130A"
    meta = D3.manifest()["run_roots"].get(label)
    assert meta is not None, (
        f"{label} is not registered in the dimension-3 manifest, so A8's "
        f"evidence would resolve by accident of directory layout")
    assert meta["kind"] == D3._PUBLISHED_KIND, meta
    root = D3.run_roots().get(label)
    assert root is not None, f"{label} is registered but does not resolve"
    assert root.path == repo / meta["rel"]
    assert (repo / meta["rel"] / "phase3" / "analog" / "hardmacro" / "ldo"
            / "ldo.gds").is_file()

    # The published root resolves A8's entry to the committed layout, and the
    # hit clears every admissibility rule in its own right.
    hit, rejected = D3.resolve(root.path, A8_GDS)
    assert hit is not None, (
        f"the published cell resolves as a run root but yields nothing for "
        f"{A8_GDS!r}; rejected: {rejected}")
    assert hit.size_bytes > 0 and not (root.path / hit.path).is_symlink()
    assert D3.is_tracked(root.path, hit.path), (
        f"{hit.path} is not tracked at HEAD, so it is a local build product "
        f"and must never have been accepted (#527)")


def test_control_a_published_cell_must_show_a_converged_verdict():
    """The NEW rule, in both directions, on trees built here.

    ``_is_published_cell`` is what let A8's evidence in. If it answered True
    for any directory, dimension 3 would have gained an unfalsifiable evidence
    source and this cell's green would mean nothing. Two admissions and three
    refusals, each differing from its neighbour in ONE property.
    """
    import tempfile

    def _cell(base: Path, name: str, verdict) -> Path:
        d = base / name
        (d / "reports" / "audit").mkdir(parents=True)
        if verdict is not None:
            (d / "reports" / "audit" / "phase23_completion_audit.json").write_text(
                json.dumps({"schema_version": 1, "verdict": verdict}),
                encoding="utf-8")
        return d

    with tempfile.TemporaryDirectory(prefix="d3_pubcell_") as td:
        base = Path(td)
        assert D3._is_published_cell(_cell(base, "v1.9.86_sky130A", "PASS")), (
            "a canonically named cell carrying a PASS convergence verdict was "
            "refused; the rule admits nothing and the fix is inert")
        assert D3._is_published_cell(
            _cell(base, "v2.0.0_gf180mcuD", "PASS_WITH_WAIVERS")), (
            "PASS_WITH_WAIVERS is in benchmark_evidence_publish._CONVERGED and "
            "must be admitted for the same reason publish() stages it")
        assert not D3._is_published_cell(_cell(base, "v1.0.0_sky130A", "FAIL")), (
            "a cell whose own convergence audit says FAIL was admitted as "
            "evidence; publish() REFUSES that run and so must this")
        assert not D3._is_published_cell(_cell(base, "v1.0.1_sky130A", None)), (
            "a cell with NO reports/audit/phase23_completion_audit.json was "
            "admitted; 'convergence unverifiable' is not a converged verdict")
        assert not D3._is_published_cell(_cell(base, "clean_run_20260806", "PASS")), (
            "a non-canonical folder name was admitted; the publish contract's "
            "own _NAME_RE is what distinguishes a published cell from any "
            "other directory somebody left under benchmark-data/ic")

    # And the OTHER kind's rule is unchanged: a directory with no runner marker
    # is still not a run tree, whatever else is true of it.
    with tempfile.TemporaryDirectory(prefix="d3_repokind_") as td:
        plain = Path(td) / "v1.9.86_sky130A"
        (plain / "reports" / "audit").mkdir(parents=True)
        (plain / "reports" / "audit" / "phase23_completion_audit.json").write_text(
            json.dumps({"verdict": "PASS"}), encoding="utf-8")
        assert not D3._is_flow_run(plain), (
            "the published-cell rule leaked into the run-tree rule: a tree with "
            "no provenance.jsonl and no reports/orchestrator/ is still not a "
            "flow run, and `repo` roots must keep being held to that")
        (plain / "provenance.jsonl").write_text("{}\n", encoding="utf-8")
        assert D3._is_flow_run(plain), "the run-tree rule stopped admitting a marker"


# ──────────────────────────────────────────────────────────────────────
# REVERSE — green before the fix and after; these must not move
# ──────────────────────────────────────────────────────────────────────
def test_reverse_the_other_dimension3_waiver_premises_are_still_true():
    """Removing A8's waiver must not weaken anybody else's.

    The cheap way to make a premise-checking guard green is to thin the
    registry, so the three surviving waivers are re-checked here against the
    very question A8's premise failed — ``git ls-tree -r HEAD`` — rather than
    trusted. GREEN BEFORE THE FIX AND AFTER: nothing about steps 6, 39 or M1
    changed, and if this ever goes red it is a NEW defect of the same shape,
    not a consequence of this one.
    """
    repo = _repo()
    # DERIVED, not re-typed. This tuple used to read ("6", "39", "M1") and went
    # stale the moment vibe-ic#1159 unpublished M1 -- and the stale form fails
    # for the WRONG reason, reporting M1's manifest verdict rather than any
    # weakened premise. Deleting "M1" by hand would restore the green and leave
    # the next reader the identical trap, which is the "thin the registry"
    # shortcut this test's own docstring names. Reading the registry keeps the
    # question ("is every SURVIVING waiver still premised on a real absence?")
    # answered about whatever actually survives.
    survivors = sorted({W.flowref.normalize_id(w.step_id)
                        for w in W.waivers_for_dim(3)})
    assert survivors, (
        "dimension 3's waiver registry is EMPTY, so this premise re-check has "
        "nothing to re-check and would pass by iterating nothing. An empty "
        "registry is exactly the 'thin it until the guard is green' outcome "
        "this test exists to catch, so it is a failure here, not a pass.")
    still_absent = []
    for sid in survivors:
        rec = D3.manifest()["steps"][sid]
        assert rec["verdict"] == "WAIVED", (
            f"step {sid} is waived in the registry but the manifest records "
            f"{rec['verdict']!r}")
        for entry in rec.get("unproven") or ():
            for alt in F.split_any_of(entry):
                hits = _tracked_matching(repo, alt)
                if hits:
                    still_absent.append(f"{sid} {entry!r}: {hits[:3]}")
    assert not still_absent, (
        "these waivers' premises have ALSO become false and must be re-argued "
        "or removed — the same defect A8 had, not something this change may "
        "absorb:\n  " + "\n  ".join(still_absent))


def test_reverse_admissibility_still_refuses_what_it_refused():
    """Admitting a published cell must not admit a 0-byte / alias / build product.

    GREEN BEFORE THE FIX AND AFTER, on purpose: it exercises ``resolve`` on a
    throwaway repository, so it depends on nothing this change added and its
    whole job is to show that what used to be refused still is. Exercised on
    A8's OWN glob, because that is the entry whose evidence rule moved: if
    "the hardmacro GDS is produced" had been closed by loosening the artefact
    rules instead of by finding a real artefact, these are the three legs that
    would have had to give.

    The 0-byte and symlink legs reuse one path, so the rule is shown to reject
    the artefact's PROPERTY rather than its name; the trackedness leg uses a
    fresh path (replacing tracked bits does not make a tracked path untracked)
    and asserts BOTH directions on the same 512 bytes.
    """
    with D3._probe_run_root("d3_a8_reverse_") as (probe, commit):
        d = probe / "phase3" / "analog" / "hardmacro" / "blk"
        d.mkdir(parents=True)

        empty = d / "blk.gds"
        empty.touch()
        commit("phase3/analog/hardmacro/blk/blk.gds")
        h, rej = D3.resolve(probe, A8_GDS)
        assert h is None and rej.empty, (
            f"a 0-byte hardmacro GDS was accepted: {h} / {rej}")

        empty.unlink()
        real = probe / "real.gds"
        real.write_bytes(b"x" * 512)
        os.symlink("../../../../real.gds", empty)
        commit("real.gds", "phase3/analog/hardmacro/blk/blk.gds")
        h, rej = D3.resolve(probe, A8_GDS)
        assert h is None and rej.symlinked, (
            f"a symlinked hardmacro GDS was accepted: {h} / {rej}")

        # A NEW path for the trackedness pair: `blk/blk.gds` is already carried
        # by the commit above (as a symlink), and replacing tracked bits does
        # not make the PATH untracked — which would have made this leg pass
        # for the wrong reason.
        empty.unlink()
        d2 = probe / "phase3" / "analog" / "hardmacro" / "blk2"
        d2.mkdir(parents=True)
        fresh = d2 / "blk2.gds"
        fresh.write_bytes(b"x" * 512)  # real bits, deliberately NOT committed
        D3.tracked_under.cache_clear()
        h, rej = D3.resolve(probe, A8_GDS)
        assert h is None and rej.untracked, (
            f"an UNTRACKED hardmacro GDS was accepted: {h} / {rej}")

        commit("phase3/analog/hardmacro/blk2/blk2.gds")
        h, rej = D3.resolve(probe, A8_GDS)
        assert h is not None and h.size_bytes == 512, (
            f"the same bytes, once committed, must be accepted — otherwise the "
            f"rule refuses the path or the glob, not the un-committedness: "
            f"{h} / {rej}")

