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
    for module in ("step_write_ledger.py", "vibe_ic_entry_guard.py"):
        text = (PROGRAMS / module).read_text(errors="replace")
        for rel in declared:
            if rel in text:
                break
        else:
            pytest.fail(f"{module} no longer names any legacy spelling the resolver knows")


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


def test_the_second_pass_carries_a_pass_one_written_at_the_flat_path(tmp_path,
                                                                    monkeypatch):
    """The HIGH, driven through `run_second_pass_only` itself.

    Everything the second pass does BESIDE carrying the record is stubbed -- the expert
    consumption, the steps view and the route -- because what is under test is whether the
    pass-1 record is found at all. Its own publication still goes to the routed path.
    """
    import phase1_one_shot_runner as P1

    project = _project_whose_pass_one_is_at_the_flat_path(tmp_path)

    monkeypatch.setattr(P1._pl, "emit_steps_view", lambda *a, **k: {"stubbed": True},
                        raising=False)
    monkeypatch.setattr(P1, "_consume_expert_answer",
                        lambda *a, **k: (0, {"consumed": True}), raising=False)

    rc = P1.run_second_pass_only(project, "zzdie", route="ic")

    published = project / ROUTED
    assert published.is_file(), (
        f"the second pass published nothing at the routed path (rc={rc})")
    doc = json.loads(published.read_text())

    assert "UNREADABLE" not in json.dumps(doc), (
        "pass 1 was not carried forward, so this pass reports the earlier pass as missing "
        "and the front door halts at phase 1 on a project that had run it")
    assert doc.get("pass1_marker") == "written by the pre-R-0915-151 producer", (
        "the carried record is not the one the flat path held")

    # and the legacy layout is DISCLOSED rather than quietly accepted
    assert doc.get("pass1_record_layout", "").startswith("LEGACY"), (
        doc.get("pass1_record_layout"))
    assert doc.get("pass1_record_read_from") == LEGACY, doc.get("pass1_record_read_from")


def test_a_second_pass_over_a_routed_project_says_nothing_about_legacy(tmp_path,
                                                                      monkeypatch):
    """The disclosure fires only when it is true."""
    import phase1_one_shot_runner as P1

    project = tmp_path / "proj"
    (project / "input").mkdir(parents=True)
    (project / "input" / "spec.md").write_text("# a counter\n")
    # owner route rule 2026-09-28 (ICROUTE)
    stage_owner_route(project, "ic")
    routed = project / ROUTED
    routed.parent.mkdir(parents=True, exist_ok=True)
    routed.write_text(json.dumps({"phase": 1, "verdict": "PASS",
                                  "pass1_marker": "routed"}) + "\n")

    monkeypatch.setattr(P1._pl, "emit_steps_view", lambda *a, **k: {"stubbed": True},
                        raising=False)
    monkeypatch.setattr(P1, "_consume_expert_answer",
                        lambda *a, **k: (0, {"consumed": True}), raising=False)
    P1.run_second_pass_only(project, "zzdie", route="ic")

    doc = json.loads(routed.read_text())
    assert doc.get("pass1_marker") == "routed"
    assert "pass1_record_layout" not in doc, doc.get("pass1_record_layout")


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


def test_pass_one_names_the_sidecar_it_wrote(tmp_path):
    """THE PRODUCER HALF, at the site that is entitled to mint the name.

    D1 ran and left a sidecar, so the record names it by content. No clock is consulted: the
    entitlement is that D1 ran in THIS pass.
    """
    import hashlib

    import phase1_one_shot_runner as P1

    project = tmp_path / "proj"
    side = _pl.coverage_only_sidecar_path(project)
    side.parent.mkdir(parents=True, exist_ok=True)
    side.write_text(json.dumps({"coverage_only_failure": True}) + "\n")

    summary: dict = {}
    P1._name_the_sidecar_this_pass_wrote(project, summary, d1_ran=True)
    named = summary.get("pass1_coverage_sidecar")
    assert isinstance(named, dict), summary
    assert named["rel"] == _pl.COVERAGE_ONLY_SIDECAR_REL
    assert named["sha256"] == hashlib.sha256(side.read_bytes()).hexdigest()


def test_a_pass_whose_d1_was_refused_names_nothing(tmp_path):
    """THE ENTITLEMENT, in the direction that matters. D1 is the only thing that writes the
    sidecar, so a pass in which D1 was REFUSED wrote none and must name none -- naming it would
    hand an earlier run's exemption to this one."""
    import phase1_one_shot_runner as P1

    project = tmp_path / "proj"
    side = _pl.coverage_only_sidecar_path(project)
    side.parent.mkdir(parents=True, exist_ok=True)
    side.write_text(json.dumps({"coverage_only_failure": True}) + "\n")

    summary: dict = {}
    P1._name_the_sidecar_this_pass_wrote(project, summary, d1_ran=False)
    assert "pass1_coverage_sidecar" not in summary, summary
    assert "REFUSED" in (summary.get("pass1_coverage_sidecar_refused") or ""), summary


def test_pass_one_forgets_an_earlier_runs_sidecar_before_it_starts(tmp_path):
    """What makes the naming above structural rather than temporal. Without this, a pass whose D1
    never reached its own classifier would find a previous run's sidecar and name it."""
    import phase1_one_shot_runner as P1

    project = tmp_path / "proj"
    side = _pl.coverage_only_sidecar_path(project)
    side.parent.mkdir(parents=True, exist_ok=True)
    side.write_text(json.dumps({"coverage_only_failure": True}) + "\n")
    assert side.is_file()

    P1._forget_any_earlier_coverage_sidecar(project)
    assert not side.exists(), (
        "an earlier run's coverage-only sidecar survived into this pass, so a pass that wrote "
        "none could still name one")
    P1._forget_any_earlier_coverage_sidecar(project)     # and it is idempotent


def test_the_second_pass_carries_the_name_pass_one_gave_it(tmp_path, monkeypatch):
    """THE REGRESSION, in the real write order.

    At r7 this arm's subject named the sidecar only when `sidecar.mtime >= record.mtime`. With the
    sidecar written FIRST -- as it really is -- that test is false, no name was carried, and the
    front door read 'NOT demoting': a `--skip-phase3` coverage-only project that was
    PASS_WITH_WAIVERS flipped to FAIL and halted at phase 1. The second pass now CARRIES the name
    and computes nothing.
    """
    import hashlib

    import phase1_one_shot_runner as P1

    project = _pass_one_as_it_really_leaves_a_project(tmp_path)
    assert (project / SIDECAR_REL).stat().st_mtime < _pl.report_path(
        project, NAME).stat().st_mtime, (
        "the fixture must stage the REAL order (sidecar first); otherwise it reproduces nothing")

    monkeypatch.setattr(P1._pl, "emit_steps_view", lambda *a, **k: {"stubbed": True},
                        raising=False)
    monkeypatch.setattr(P1, "_consume_expert_answer",
                        lambda *a, **k: (0, {"consumed": True}), raising=False)
    P1.run_second_pass_only(project, "zzdie", route="ic")

    doc = json.loads(_pl.report_path(project, NAME).read_text())
    named = doc.get("pass1_coverage_sidecar")
    assert isinstance(named, dict), doc.get("pass1_coverage_sidecar_refused") or doc.keys()
    assert named["rel"] == SIDECAR_REL
    assert named["sha256"] == hashlib.sha256(
        (project / SIDECAR_REL).read_bytes()).hexdigest()


def test_a_sidecar_the_carried_record_does_not_name_stays_refused(tmp_path, monkeypatch):
    """The half that keeps this from laundering a stale file.

    A sidecar on disk that the carried pass-1 record says nothing about has nothing saying which
    pass wrote it. It is not named, and the refusal is recorded so a reader can see why the
    demotion was unavailable rather than wondering where the sidecar went.
    """
    import phase1_one_shot_runner as P1

    project = _pass_one_as_it_really_leaves_a_project(tmp_path, names_the_sidecar=False)
    monkeypatch.setattr(P1._pl, "emit_steps_view", lambda *a, **k: {"stubbed": True},
                        raising=False)
    monkeypatch.setattr(P1, "_consume_expert_answer",
                        lambda *a, **k: (0, {"consumed": True}), raising=False)
    P1.run_second_pass_only(project, "zzdie", route="ic")

    doc = json.loads(_pl.report_path(project, NAME).read_text())
    assert "pass1_coverage_sidecar" not in doc, doc.get("pass1_coverage_sidecar")
    assert "does not name it" in (
        doc.get("pass1_coverage_sidecar_refused") or ""), doc.keys()


def test_the_second_pass_orders_nothing_by_mtime(tmp_path):
    """THE MUTATION NO FIXTURE CAN CATCH ONCE IT IS STAGED CORRECTLY.

    An mtime comparison between the sidecar and the record is wrong in a direction no arm can
    detect unless the arm happens to stage the real order -- which the previous fixture did not,
    for exactly this reason. So the ordering is pinned OUT of the function by AST: nothing in
    `run_second_pass_only` may read the sidecar's mtime.
    """
    import ast as _ast

    src = (PROGRAMS / "phase1_one_shot_runner.py").read_text()
    fn = next((n for n in _ast.walk(_ast.parse(src))
               if isinstance(n, _ast.FunctionDef) and n.name == "run_second_pass_only"), None)
    assert fn is not None, "run_second_pass_only is gone; re-pin this arm on its replacement"
    body = _ast.unparse(fn)
    for spelling in ("st_mtime", "getmtime"):
        assert spelling not in body, (
            f"run_second_pass_only reads {spelling} again; the sidecar's name is CARRIED from "
            f"pass 1, and ordering it against the record it belongs to is backwards on every "
            f"real re-invocation")


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

def test_the_real_pass_one_main_forgets_then_names(tmp_path, monkeypatch):
    """BOTH WIRED CALLS, DRIVEN, not asserted about.

    Every arm above exercises `_forget_any_earlier_coverage_sidecar` and
    `_name_the_sidecar_this_pass_wrote` DIRECTLY, which proves the helpers and says nothing about
    whether `main()` calls them -- the same gap that let r7's reader arm pass on a branch that could
    not fire. So this one runs the real `phase1_one_shot_runner.main()` through the docs door and
    watches the two things only the wiring can do:

      * an EARLIER run's sidecar is gone by the time the record is written (the forget, wired below
        the second-pass short-circuit);
      * the published record names the sidecar THIS pass's D1 wrote -- proven by sha, which is the
        NEW bytes and not the old ones.

    Only D1 itself and the two heavy neighbours are stubbed. `_run_docs_mode` stands in for the doc
    runner and writes the sidecar exactly where `phase1_doc_one_shot_runner` writes it, in the same
    position in the pass: in-process, before the record.
    """
    import hashlib

    import phase1_one_shot_runner as P1

    project = tmp_path / "proj"
    (project / "input" / "docs").mkdir(parents=True)
    (project / "input" / "docs" / "spec.md").write_text("# a counter\n")
    # owner route rule 2026-09-28 (ICROUTE)
    stage_owner_route(project, "ic")

    side = _pl.coverage_only_sidecar_path(project)
    side.parent.mkdir(parents=True, exist_ok=True)
    side.write_text(json.dumps({"coverage_only_failure": True, "run": "AN EARLIER ONE"}) + "\n")
    stale_sha = hashlib.sha256(side.read_bytes()).hexdigest()

    fresh_payload = json.dumps({"coverage_only_failure": True, "run": "this one"}) + "\n"

    def fake_docs_mode(project_, ic_name, extras):
        # what D1 does, where and when it does it: the sidecar first, in-process.
        assert not side.exists(), (
            "main() reached D1 with an earlier run's sidecar still on disk, so a pass that wrote "
            "none could name one")
        side.parent.mkdir(parents=True, exist_ok=True)
        side.write_text(fresh_payload)
        return 1                                        # coverage-only phase-1 failure

    monkeypatch.setattr(P1, "_run_docs_mode", fake_docs_mode, raising=True)
    monkeypatch.setattr(P1, "_run_step_0_5ic", lambda *a, **k: 0, raising=True)
    monkeypatch.setattr(P1, "run_phase1_second_track", lambda p, rc: rc, raising=True)
    monkeypatch.setattr(P1, "_expert_track_summary", lambda *a, **k: "stubbed", raising=True)
    monkeypatch.setattr(P1._pl, "emit_steps_view", lambda *a, **k: {"stubbed": True},
                        raising=False)
    monkeypatch.setattr(sys, "argv",
                        ["phase1_one_shot_runner", str(project), "--mode", "docs",
                         "--ic-name", "zzdie"])
    P1.main()

    doc = json.loads(_pl.report_path(project, NAME).read_text())
    named = doc.get("pass1_coverage_sidecar")
    assert isinstance(named, dict), (
        f"the real main() published a record that names no sidecar, so the second pass has "
        f"nothing to carry: {doc.get('pass1_coverage_sidecar_refused')} / {sorted(doc)}")
    assert named["sha256"] == hashlib.sha256(fresh_payload.encode()).hexdigest()
    assert named["sha256"] != stale_sha, (
        "the record named the EARLIER run's sidecar; the forget did not happen before D1")


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
