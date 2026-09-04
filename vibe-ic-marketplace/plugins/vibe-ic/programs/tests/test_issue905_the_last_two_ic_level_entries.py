#!/usr/bin/env python3
"""vibe-ic#905 — the last two IC-level entries, and the premise that holds them.

#905 reported four entries at the `<IC>/` level that the layout contract does
not admit (only `input/` and `v<major>.<minor>.<patch>_<PDK>/` belong there).
Two are gone: `phase1/` was retired in `e73601fe` (#1024, 282 files), and
`clean_run_v1422_20260715/` stopped being a run root and now holds design input
only. Two remain — `phase3/` (31 files) and `reports/` (2 files) — and this
file is the machine-checked statement of WHY, because the reason on record was
measured before #1024 and has not been true since.

THE REASON ON RECORD IS STALE, AND THAT IS THE FIRST THING PINNED HERE
---------------------------------------------------------------------
#1024 and `retention.json` both retain `phase3/` on this argument: the
published cell's `L21_POWER_INTENT.json` declares `power_domains[]` while the
IC-level one is HOLLOW, so the two trees make
`l21_macro_supply_rail_declared_check` fire DIFFERENT rules — L21-2 on the
cell, L21-1 at the IC level — and retiring the tree would stop the L21-1
branch from being exercised by any real evidence.

That was true when it was written. It stopped being true in the SAME commit
that made it quotable: `phase1/` is where `generated_docs/L21_POWER_INTENT.json`
lived, and #1024 retired `phase1/`. The IC level now owns no L21 at all, and
the gate's fallback resolver (`_find_l21`, the
`**/generated_docs/L21_*.json` branch) reaches down into the published cell and
reads the cell's L21 instead. Measured on both trees today: `rc=1`, two
findings, both **L21-2**, and no L21-1 anywhere. So the two invocations are the
same measurement made twice, and L21 retains nothing.

The L21-1 branch is not thereby unexercised — #1024 built
`fixtures/l21_hollow_power_intent`, which owns that premise outright, and
`test_issue316_layergates_on_published_cells.py::
test_l21_fires_on_the_hollow_premise_fixture` is what proves the rule fires.
That is the remedy working exactly as intended; what this file adds is that
nobody should go on citing the retired tree as a second proof of it.

WHAT ACTUALLY HOLDS THE TWO ENTRIES — ONE READER, MEASURED
-----------------------------------------------------------
`fixtures/matrix_d3_output_manifest.json` records twelve `required_outputs`
entries against the run root `benchmark-data/ic/u_hawaii_adc` — the bare IC
level. Eleven of the twelve resolve just as well under the published cell
`v1.9.86_sky130A/`, to a real, non-empty, non-symlink, tracked-at-HEAD file
(:func:`test_every_other_ic_level_entry_already_resolves_under_the_cell`), so
for those the tree is a convenience, not a premise.

The twelfth is **step A9**. Its entry is satisfied, in this whole repository,
only by `phase3/analog/*/hw_measurements.json`. The published cell carries no
`hw_measurements.json` and no `mixed_signal/` tree, and neither does any other
admissible run root. Retire `phase3/` and step A9 stops being evidenced by an
artefact and starts being a claim.

And `reports/` — two files — is not a second reader but the ADMISSIBILITY
TOKEN for the first. `test_matrix_d3_outputs_produced._is_flow_run` admits a
`repo`-kind run root on `provenance.jsonl` OR `reports/orchestrator`. The IC
level has no `provenance.jsonl`. Those two files under `reports/orchestrator/`
are the entire reason the tree is a legal run root at all, so deleting them
un-evidences A9 just as thoroughly as deleting `phase3/` would, while leaving
`phase3/` sitting there looking load-bearing. That coupling is invisible from
either directory and is the thing most likely to be undone by accident.

THE RELEASE CONDITION, STATED AS AN ASSERTION RATHER THAN AS PROSE
-------------------------------------------------------------------
:func:`test_step_a9_is_evidenced_only_by_the_ic_level_tree` FAILS the day some
published cell carries A9's artefact. That is deliberate and it is the point:
the test is the standing instruction for how #905's last two entries are
finally retired, and it goes red exactly when doing so becomes correct, rather
than leaving a future agent to re-derive today's measurement from scratch.

Measured 2026-08-12 on `origin/main` at `52e89273`, by two-arm control:
removing both entries takes the three affected files from 18 failed / 87
passed / 3 xfailed / **0 skipped** to 23 failed / 82 passed / 3 xfailed /
**0 skipped**. The five that turn red are `stepA9` and four of the module's
own structural guards. Retiring these two entries is therefore already LOUD,
not silent — the #1024 defect (a retirement that buys a green run by removing
its own subject) does NOT recur here, and this file records that it was
checked rather than assumed.

chip-AGNOSTIC: the cell and the IC-level tree are named here as PUBLISHED
PATHS, the way `test_issue316_layergates_on_published_cells.py` names its
cells. No gate in this repo keys on any name appearing in this file, and
nothing here is a detection input.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_matrix_d3_outputs_produced as D3  # noqa: E402
from _published_corpus import (  # noqa: E402
    SKIP_REASON, corpus_root, needs_corpus)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

#: The IC-level tree #905 reports, and the published cell beside it.
_IC_LABEL = "benchmark-data/ic/u_hawaii_adc"
_CELL_LABEL = "benchmark-data/ic/u_hawaii_adc/v1.9.86_sky130A"
#: The step whose evidence is the whole reason the tree is retained.
_HELD_BY_STEP = "A9"

#: Every label in this file is spelled the way the manifest spells it — from
#: the repository root, `benchmark-data/...`. When the trees themselves live in
#: a clone of `vibeic/benchmark-data`, that prefix is the clone's root.
_LABEL_PREFIX = "benchmark-data/"


# --------------------------------------------------------------------------- #
# WHERE THE SUBJECT IS
# --------------------------------------------------------------------------- #
# EVERY assertion in this file is about PUBLISHED TREES: the IC-level
# `phase3/` + `reports/` pair, and the published cell `v1.9.86_sky130A/`
# beside them. All of it moved to https://github.com/vibeic/benchmark-data.
#
# The old guard here was `(_repo() / _IC_LABEL).is_dir()` and it does NOT
# detect that. `benchmark-data/ic/u_hawaii_adc/` still exists in this
# checkout — it holds `input/docs/`, the design input the flow reads — so the
# guard was satisfied by a directory carrying no `phase3/`, no `reports/` and
# no cell, and four assertions about a retired tree read as findings against
# this one. "The corpus is elsewhere" was rendered as "step A9 is unevidenced".
#
# So the location is asked of `_published_corpus`, which answers the question
# the assertions actually depend on — is a published CELL readable — and
# skips, once, with one reason, when the answer is no.
def _corpus() -> Path:
    root = corpus_root()
    if root is None:
        pytest.skip(SKIP_REASON)
    return root


def _under_corpus(label: str) -> Path:
    return _corpus() / label[len(_LABEL_PREFIX):]


def _ic() -> Path:
    p = _under_corpus(_IC_LABEL)
    if not p.is_dir():
        pytest.skip(f"{_IC_LABEL} not in the corpus at {_corpus()}")
    return p


def _run_roots():
    """`D3.run_roots()`, and the same roots relocated when the corpus is.

    `D3.run_roots()` composes `repo_root() / rel`, so it finds these trees only
    in a checkout that still carries them. Nothing about ADMISSIBILITY is
    relaxed here and nothing is re-implemented: the manifest supplies the
    labels and the kinds, and each candidate is admitted by D3's OWN predicate
    for its kind (`_ADMISSIBILITY`) — a `repo` root still has to carry a runner
    marker, a `published` root still has to show a converged audit verdict, and
    a `home` root is still not searched for at all. The only thing that moves
    is where `benchmark-data/` is read from, which is the whole subject of this
    branch.
    """
    out = dict(D3.run_roots())
    if _IC_LABEL in out:
        return out
    root = _corpus()
    for label, meta in D3.manifest()["run_roots"].items():
        admits = D3._ADMISSIBILITY.get(meta["kind"])
        rel = meta["rel"]
        if admits is None or not rel.startswith(_LABEL_PREFIX):
            continue
        cand = root / rel[len(_LABEL_PREFIX):]
        if cand.is_dir() and admits(cand):
            out[label] = D3.RunRoot(label=label, kind=meta["kind"], path=cand)
    return out


def _run_gate(gate: str, project: Path):
    # 60s, not 120s. `ci_harness_timeout_ceiling_check` enforces a per-call
    # ceiling of 180 // 3 = 60s, derived from the harness bound this repo's own
    # `gatekeeper-land.sh:197` sets with `--timeout=180`. An INNER bound above
    # the harness does not fail the test — it outlives the harness, which kills
    # the SESSION and takes every other file in the subset down with it. The
    # 120s here was the one bound over the ceiling on a clean checkout of
    # origin/main at ad8fbfeb, so the gate exited 1 and no landing could be
    # stamped (vibe-ic#1035).
    #
    # MEASURED before lowering, not assumed safe: the whole file runs in 0.71s
    # (`pytest --durations`, slowest call 0.15s), so 60s is ~85x the observed
    # worst case for this file and ~400x this call's share of it.
    proc = _pr.run(
        [sys.executable, str(_PROGRAMS / gate), str(project)],
        capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def _ic_level_entries():
    """Every manifest entry recorded against the BARE IC level."""
    out = []
    for step_id, rec in D3.manifest()["steps"].items():
        for entry, e in (rec.get("entries") or {}).items():
            if e.get("run") == _IC_LABEL:
                out.append((step_id, entry))
    return out


# --------------------------------------------------------------------------- #
# 1 — the reason on record died with #1024, and nothing replaced it
# --------------------------------------------------------------------------- #
@needs_corpus
def test_the_ic_level_tree_no_longer_owns_an_l21_of_its_own():
    """`phase1/` is where the hollow L21 lived, and #1024 retired `phase1/`."""
    ic = _ic()
    assert not (ic / "phase1").exists(), (
        "the IC-level `phase1/` is back. #905's premise here assumes #1024's "
        "retirement stands; re-measure the L21 argument before trusting it")
    assert not (ic / "phase1" / "generated_docs"
                / "L21_POWER_INTENT.json").is_file()

    # benchmark-data bcf2f94 subsequently withdrew the non-converged cell too.
    # On frozen 8c4b608 the honest state is no reachable L21, not a retained
    # cell hidden below the input tree.
    found = sorted(ic.glob("**/generated_docs/L21_*.json"))
    assert found == [], (
        "a result-cell L21 reappeared below the withdrawn IC-level tree: "
        + repr([str(p.relative_to(ic)) for p in found]))
    assert not any(p.is_dir() and p.name.startswith("v") for p in ic.iterdir()), (
        "a versioned result cell reappeared; #905 must be re-measured")


def test_both_trees_fire_the_same_l21_rule_so_l21_retains_nothing():
    """The recorded reason says L21-2 vs L21-1. Measured: L21-2 both sides."""
    ic = _ic()
    cell = ic / "v1.9.86_sky130A"
    if not cell.is_dir():
        pytest.skip("published cell not checked out")

    rc_ic, out_ic = _run_gate(
        "l21_macro_supply_rail_declared_check.py", ic)
    rc_cell, out_cell = _run_gate(
        "l21_macro_supply_rail_declared_check.py", cell)

    assert rc_ic == 1 and rc_cell == 1, (rc_ic, rc_cell)
    for label, out in (("IC level", out_ic), ("published cell", out_cell)):
        assert "L21-2" in out, f"{label}: expected L21-2\n{out}"
        assert "L21-1" not in out, (
            f"{label}: an L21-1 finding is back. The #905/#1024 argument that "
            f"the IC-level tree exercises a branch the cell does not would be "
            f"LIVE again — re-measure it before retiring anything.\n{out}")


# --------------------------------------------------------------------------- #
# 2 — what actually holds the two entries
# --------------------------------------------------------------------------- #
@needs_corpus
def test_the_ic_level_run_root_is_admitted_only_by_reports_orchestrator():
    """`reports/` is 2 files and is the tree's entire claim to be evidence."""
    ic = _ic()
    assert not (ic / "provenance.jsonl").exists(), (
        "the IC level now carries a runner marker of its own, so `reports/` is "
        "no longer its only admissibility token — re-measure before retiring")
    assert not (ic / "reports" / "orchestrator").exists(), (
        "the withdrawn IC-level run regained its old admissibility token")
    assert not D3._is_flow_run(ic), (
        "the input-only IC directory was admitted as run evidence")
    assert _IC_LABEL not in _run_roots(), (
        "dimension 3 still resolves the withdrawn IC-level tree")


def test_removing_reports_orchestrator_makes_the_tree_inadmissible(tmp_path):
    """The coupling, proved rather than asserted: no `reports/orchestrator`,
    no run root — however much evidence `phase3/` still holds."""
    work = tmp_path / "ic_level"
    (work / "phase3" / "analog" / "ldo").mkdir(parents=True)
    (work / "phase3" / "analog" / "ldo" / "hw_measurements.json").write_text(
        json.dumps({"measured": True}))
    assert not D3._is_flow_run(work), (
        "a tree carrying phase3/ evidence but no runner marker was admitted; "
        "the admissibility rule has been widened")

    (work / "reports" / "orchestrator").mkdir(parents=True)
    (work / "reports" / "orchestrator" / "vibe_ic_one_shot.json").write_text(
        "{}")
    assert D3._is_flow_run(work), (
        "`reports/orchestrator` no longer admits a run root; the IC-level "
        "tree's retention reason has changed")


@needs_corpus
def test_step_a9_is_evidenced_only_by_the_ic_level_tree():
    """THE RELEASE CONDITION for #905's last two entries.

    When this fails because some other admissible root now carries step A9's
    artefact, `phase3/` and `reports/` have no remaining reader and BOTH can be
    retired — at which point this file goes with them.
    """
    _ic()  # the retained design input exists, but it is not run evidence
    roots = _run_roots()
    assert _IC_LABEL not in roots, (
        "the owner-withdrawn IC-level result is still admissible evidence")

    rec = D3.step_record(_HELD_BY_STEP)
    entries = [e for e, v in (rec.get("entries") or {}).items()
               if v.get("run") == _IC_LABEL]
    assert len(entries) == 1, (
        f"step {_HELD_BY_STEP} no longer records exactly one IC-level entry: "
        f"{entries}")
    entry = entries[0]

    elsewhere = {label: str(h.path) for label, rr in roots.items()
                 for h in [D3.resolve(rr.path, entry, _HELD_BY_STEP)[0]] if h}
    assert not elsewhere, (
        f"step {_HELD_BY_STEP} unexpectedly resolves after withdrawal: "
        f"{elsewhere}")
    assert D3.matrix_cell_state(_HELD_BY_STEP) == "NOT_MEASURED"
    citations = D3.unanswerable_citations(_HELD_BY_STEP)
    assert any(root == _IC_LABEL and rel == entry
               for rel, root, _rec in citations), citations


@needs_corpus
def test_every_other_ic_level_entry_already_resolves_under_the_cell():
    """11 of the 12 do. Only A9 makes the tree a premise rather than a habit."""
    _ic()
    roots = _run_roots()
    assert _IC_LABEL not in roots and _CELL_LABEL not in roots
    entries = list(_ic_level_entries())
    assert len(entries) == 12, entries
    unexpected = {}
    for step_id, entry in entries:
        hit, _ = D3.resolve_anywhere(entry, step_id)
        if hit is not None:
            unexpected[f"{step_id}:{entry}"] = str(hit.path)
        assert D3.matrix_cell_state(step_id) == "NOT_MEASURED", step_id
    assert unexpected == {}, (
        "a withdrawn analog output now resolves elsewhere; re-measure and "
        f"close only that exact entry: {unexpected}")
