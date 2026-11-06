"""Pass 1 written before the report moved is still carried forward.

R-0915-160. R-0915-151 moved `phase1_one_shot.json` onto `_path_layout`'s router, because the
flat `reports/phase1_one_shot.json` is a location the repo's own
`reports_subfolder_taxonomy_check` calls a stray file. That is the right answer for WHERE TO
WRITE, and it is not the whole question: every project produced before that landing still has
its pass-1 record at the flat path.

MEASURED cost of conflating the two questions: `run_second_pass_only` read ONLY the routed
path, so on such a project pass 1 was not carried forward -- `carried=False`, a second pass
publishing "UNREADABLE -- the pass-1 record could not be carried forward", and the front door
halting at phase 1 on a project that had in fact completed it. Main passed the same project.

The write is still the router's single answer. The READ goes through one shared resolver,
`_path_layout.report_path_for_reading`, which the other legacy readers use too -- this file
held the routed-and-legacy pair in six places across four modules before that.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import _path_layout as _pl                   # noqa: E402
from _route_fixture import stage_owner_route  # noqa: E402

ROUTED = "reports/orchestrator/phase1_one_shot.json"
LEGACY = "reports/phase1_one_shot.json"
NAME = "phase1_one_shot.json"


# ── the resolver itself ──────────────────────────────────────────────────────

def test_the_routed_path_wins_when_it_exists(tmp_path):
    for rel in (ROUTED, LEGACY):
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"at": rel}) + "\n")
    got, legacy = _pl.report_path_for_reading(tmp_path, NAME)
    assert got == tmp_path / ROUTED and legacy is False


def test_the_legacy_path_is_found_and_flagged(tmp_path):
    f = tmp_path / LEGACY
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"verdict": "PASS"}) + "\n")
    got, legacy = _pl.report_path_for_reading(tmp_path, NAME)
    assert got == tmp_path / LEGACY, got
    assert legacy is True, "the legacy hit was not flagged, so no caller can disclose it"


def test_with_nothing_on_disk_the_canonical_place_is_named(tmp_path):
    got, legacy = _pl.report_path_for_reading(tmp_path, NAME)
    assert got == tmp_path / ROUTED and legacy is False, (
        "a not-found message must name the place a reader should look")


def test_a_report_with_no_legacy_spelling_is_unaffected(tmp_path):
    """The tolerance is PER FILENAME, never a blanket second location.

    My first spelling of this arm used phase2's and phase3's reports as the examples, on the
    assumption that only phase1 had ever moved. That was wrong and it cost a regression: old
    `run_status` accepted the flat spelling for ALL SIX of its phase reports, so when I replaced
    its hand-built pairs with this resolver, five tolerances vanished and
    `test_issue590_auto_picks_the_furthest_phase` -- which stages every report flat -- got
    "UNKNOWN ... there is no run here to report on". The table now names all six; the property
    this arm is really about is that a name NOT in the table gets no second location at all.
    """
    for name in ("synth_netlist.json", "drc_signoff.json"):
        assert name not in _pl.LEGACY_REPORT_PATHS, name
        f = tmp_path / "reports" / name          # a flat spelling nothing ever wrote
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("{}")
        got, legacy = _pl.report_path_for_reading(tmp_path, name)
        assert got == _pl.report_path(tmp_path, name), (name, got)
        assert legacy is False, name




def test_the_resolver_never_decides_where_to_write():
    """`report_path` stays the one answer for writing; this only tolerates reading."""
    import inspect
    src = inspect.getsource(_pl.report_path_for_reading)
    assert "mkdir" not in src and "write" not in src, src


def test_the_legacy_spellings_are_the_resolvers_own():
    """Every module that tolerates an old spelling must name the SAME one.

    Before this there were six hand-built pairs across four modules. Any that remain must
    agree with `LEGACY_REPORT_PATHS`, or the layouts diverge again where nobody is looking.
    """
    declared = {rel for rels in _pl.LEGACY_REPORT_PATHS.values() for rel in rels}
    assert LEGACY in declared, sorted(declared)


# ── the second pass, which is where it bit ───────────────────────────────────

def _project_whose_pass_one_is_at_the_flat_path(tmp_path: Path) -> Path:
    """A project as the PRE-LANDING producer left it, plus a delivered expert answer."""
    p = tmp_path / "proj"
    (p / "input").mkdir(parents=True)
    (p / "input" / "spec.md").write_text("# a counter\n")
    # owner route rule 2026-09-28 (ICROUTE)
    stage_owner_route(p, "ic")

    flat = p / LEGACY
    flat.parent.mkdir(parents=True, exist_ok=True)
    flat.write_text(json.dumps({
        "phase": 1, "project": str(p), "verdict": "PASS",
        "pass1_marker": "written by the pre-R-0915-151 producer",
        "steps": [{"id": "1", "status": "PASS"}],
    }, indent=2) + "\n")
    assert not (p / ROUTED).exists()
    return p






# ── (2) the D1 re-invocation's coverage-only sidecar ─────────────────────────

SIDECAR_REL = _pl.COVERAGE_ONLY_SIDECAR_REL


def _pass_one_as_it_really_leaves_a_project(
        tmp_path: Path, *, names_the_sidecar: bool = True,
        d1_refused: bool = False) -> Path:
    """A project as a real pass 1 leaves it, IN THE REAL WRITE ORDER.

    THE ORDER IS THE WHOLE POINT, and the previous fixture had it backwards. Pass 1 writes the
    sidecar FIRST -- `phase1_doc_one_shot_runner` emits it in-process from inside D1 -- and its
    record LAST, after the expert track and the steps view. The old fixture staged the sidecar at
    `record + 10s`, so the producer's `sidecar.mtime >= record.mtime` test passed here and was
    false on every real re-invocation: the defect lived entirely in the gap between this fixture
    and the write order it claimed to reproduce.

    Both files are back-dated so they predate any later invocation's phase-1 start, which is the
    situation the second pass is actually in.
    """
    import os
    import time

    p = tmp_path / "proj"
    (p / "input").mkdir(parents=True)
    (p / "input" / "spec.md").write_text("# a counter\n")
    # owner route rule 2026-09-28 (ICROUTE)
    stage_owner_route(p, "ic")

    # 1. D1 writes the sidecar, in-process, before anything else is published.
    side = p / SIDECAR_REL
    side.parent.mkdir(parents=True, exist_ok=True)
    side.write_text(json.dumps({"coverage_only_failure": True}) + "\n")

    # 2. pass 1 publishes its record LAST, naming the sidecar it wrote.
    record = _pl.report_path(p, NAME)
    record.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "phase": 1, "mode": "docs", "verdict": "FAIL",
        "steps": [{"name": "doc_extract", "status": "FAIL"}],
    }
    if names_the_sidecar and not d1_refused:
        import hashlib
        doc["pass1_coverage_sidecar"] = {
            "rel": SIDECAR_REL,
            "sha256": hashlib.sha256(side.read_bytes()).hexdigest(),
            "named_by": "pass 1, which wrote it",
        }
    record.write_text(json.dumps(doc) + "\n")

    base = time.time() - 5000
    os.utime(side, (base, base))                    # sidecar first ...
    os.utime(record, (base + 10, base + 10))        # ... record last. The real order.
    return p














# ── the READER half is not here, and that is deliberate ──────────────────────
#
# r7 ended this file with an arm called
# `test_the_front_door_demotes_on_a_named_sidecar_and_refuses_an_unnamed_one`, and a review was
# right that it proved nothing about the front door: it asserted two SOURCE SUBSTRINGS
# (`"pass1_coverage_sidecar" in src`, and the sha comparison spelled exactly as written) and never
# called `main()`. A source-substring arm goes green on code that is never reached, which is what
# happened -- the producer half never named the sidecar, so the branch those substrings live in
# could not fire, and this file still passed.
#
# The reader half is therefore driven END TO END, through the real `main()`, where the harness for
# that already exists: `test_the_front_door_rollup_edges.py`, section H5 -- invocation A demotes,
# invocation B's second pass still demotes, and a sidecar swapped after A is refused.


# ── the wiring itself, through the REAL phase-1 main() ───────────────────────



# ── one location, asked by everyone who touches it ───────────────────────────

def test_the_coverage_only_sidecar_has_exactly_one_spelling():
    """THE FIVE COPIES, AND THE ARM THAT KEEPS THEM FROM COMING BACK.

    The sidecar is an EXEMPTION -- it is what lets the front door demote a coverage-only phase-1
    FAIL instead of halting -- so three programs care about where it is: the producer
    (`phase1_doc_one_shot_runner`, which writes it and withdraws it), the front door
    (`vibe_ic_one_shot_runner`, twice: the coverage predicate and the demotion branch) and
    `phase1_one_shot_runner`, which names its digest in the record it publishes. Each spelled the
    path for itself: five hand-written copies of one location.

    That is the shape R-0915-151 closed for the phase reports and R-0915-168 for the auditor's temp
    and lock. This closes it for this file: the path is declared once and every site ASKS. The
    sweep is over `programs/*.py` source, because the failure mode is a NEW copy appearing in a
    program that never read the declaration -- exactly how the five accumulated.
    """
    hits = []
    for py in sorted(PROGRAMS.glob("*.py")):
        if py.name == "_path_layout.py":
            continue                            # the declaration itself, and its own commentary
        src = py.read_text(errors="replace")
        for lineno, line in enumerate(src.splitlines(), 1):
            if "phase1_exit_reason" in line:
                hits.append(f"{py.name}:{lineno}: {line.strip()[:110]}")
    assert not hits, (
        "the coverage-only sidecar's path is spelled outside `_path_layout` again -- ask "
        "`_path_layout.coverage_only_sidecar_path(project)` / `COVERAGE_ONLY_SIDECAR_REL` "
        "instead of rebuilding it:\n  " + "\n  ".join(hits))


def test_the_declared_sidecar_location_is_pinned():
    """THE OTHER HALF, and it is why the fixtures may safely ask the declaration.

    Every fixture now stages the sidecar through `coverage_only_sidecar_path`, which means no
    fixture can catch the path MOVING any more -- they would move with it. So the literal is
    pinned here, once. A move is then a deliberate two-line change (this arm and the constant)
    rather than something that happens quietly, and every project that already carries a sidecar
    at the old place keeps being read.

    NOT ROUTED, AND THE ARM SAYS SO: `report_path` sends an unrecognised report name to
    `reports/audit/`, which is NOT where this file is or has ever been. Asserting the difference
    keeps someone from "tidying" the constant into a routing call and moving the file by accident.
    """
    assert _pl.COVERAGE_ONLY_SIDECAR_REL == "reports/phase1/phase1_exit_reason.json"
    project = Path("/nonexistent-project")
    assert _pl.coverage_only_sidecar_path(project) == (
        project / "reports" / "phase1" / "phase1_exit_reason.json")
    routed = _pl.report_path(project, "phase1_exit_reason.json")
    assert routed != _pl.coverage_only_sidecar_path(project), (
        "the router now agrees with the sidecar's real location; if that is deliberate, move the "
        "producer and give the reader a legacy tolerance -- do not let this arm pass by accident")
    assert routed.parent.name == "audit", routed


def test_the_producer_asks_the_declaration_too():
    """A declaration the WRITER ignores is a comment. `phase1_doc_one_shot_runner` is the only
    thing that creates this file, so it is the site whose silence would cost most: readers asking a
    constant the producer does not use is precisely how a path acquires two locations."""
    src = (PROGRAMS / "phase1_doc_one_shot_runner.py").read_text(errors="replace")
    assert "coverage_only_sidecar_path" in src, (
        "the sidecar's producer builds its own path again, so the declaration the readers ask is "
        "no longer a contract with the writer")
