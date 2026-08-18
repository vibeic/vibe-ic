"""vibe-ic#1744 — the only external refusal interface must point at a shuttle
that still exists, and its silence must never read as a clean run.

WHAT THESE TESTS DISCRIMINATE
-----------------------------
Every other gate in this tree we wrote, so every other gate can be made to pass
by editing it. The shuttle precheck is the one place an outside party's refusal
is the verdict, and before #1744 it was aimed at a vendor that shut down. These
tests hold three properties that a plausible-looking rewrite would lose:

  * a RETIRED counterparty yields NOT_DETERMINED — never PASS (that would be the
    fabrication) and never FAIL (the vendor did not refuse, the vendor stopped);
  * an unreached counterparty is a NON-ZERO exit, because this repo credits rc 2
    as a pass and reads rc 3 as PASS_WITH_WAIVERS, so either would route "we
    never found out" back into a green light;
  * the checklist STATES the external verdict unconditionally, because an
    inventory that only counts our own artefacts is how "nobody outside has
    looked" came to look identical to "an outside party looked and was fine".

`test_refuses_the_layout_we_actually_published` runs the parser over a REAL run
directory captured from the shuttle operator's own tool (see
`fixtures/shuttle_precheck_refusal/PROVENANCE.md`), not over a fixture written
to match the parser.
"""
import ast
import importlib
import json
import subprocess
from pathlib import Path

import pytest

trc = importlib.import_module("tapeout_readiness_check")
checklist = importlib.import_module("tapeout_checklist_gen")
driver = importlib.import_module("mpw_precheck_driver")

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_REAL_REFUSAL = _FIXTURES / "shuttle_precheck_refusal"
_PROGRAMS = Path(__file__).resolve().parents[1]


def _project(tmp_path, with_layout=True):
    proj = tmp_path / "proj"
    gds = proj / "phase3" / "stage4" / "gds"
    gds.mkdir(parents=True)
    if with_layout:
        (gds / "chip_top.gds").write_bytes(b"HEADER-not-read-by-this-gate")
    return proj


def _never_resolves(image, allow_pull):
    return None


def _resolves(image, allow_pull):
    return image


def _no_op_runner(rc=0, out="", err=""):
    def _run(cmd, timeout):
        return rc, out, err
    return _run


# --------------------------------------------------------------------------- #
# The measurement that settles it
# --------------------------------------------------------------------------- #
def test_refuses_the_layout_we_actually_published(tmp_path):
    """The counterparty's own tool refused a GDS this project already shipped.

    Ladder step 3, `KLayout.CheckSize`, over a missing seal ring — which is the
    gap #1744 predicted for a flow that has only ever built a core, and it is
    the FIRST substantive step, before density, antenna or either DRC deck."""
    proj = _project(tmp_path)
    rep = trc.evaluate(proj, rundir=_REAL_REFUSAL,
                       image_resolver=_resolves, runner=_no_op_runner(rc=1))

    assert rep.verdict == trc.FAIL
    assert rep.failed_steps == ["KLayout.CheckSize"]

    refusal = next(s for s in rep.steps if s.verdict == trc.FAIL)
    assert "seal ring" in refusal.evidence.lower()
    assert "GUARD_RING_MK" in refusal.evidence

    # The two steps the tool got PAST carry passing evidence; the ones it never
    # reached are NOT_DETERMINED, not passed over.
    by_id = {s.step_id: s.verdict for s in rep.steps}
    assert by_id["KLayout.ReadLayout"] == trc.PASS
    assert by_id["KLayout.CheckTopLevel"] == trc.PASS
    assert by_id["Checker.MagicDRC"] == trc.NOT_DETERMINED


def test_the_captured_refusal_is_actually_tracked():
    """The fixture must be IN THE REPO, not merely on the author's disk.

    `.gitignore` carries a `runs/` rule for EDA flow output, and the external
    precheck writes its evidence into exactly that shape. Measured: without the
    #1744 negation, `git add -A` stages this fixture's PROVENANCE.md and
    silently drops all fourteen evidence files — so the tests above would run
    against a directory that exists here and nowhere else, and would go red the
    first time anyone else checked the tree out. This test fails on the machine
    where the fixture is untracked, which is the machine that can still fix it."""
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", str(_REAL_REFUSAL)],
        capture_output=True, text=True, cwd=str(_REAL_REFUSAL))
    if out.returncode != 0:  # not a git checkout (installed plugin) — nothing to assert
        pytest.skip("not a git work tree")
    tracked = {Path(p).name for p in out.stdout.split("\0") if p}
    assert "error.log" in tracked
    assert "state_out.json" in tracked
    assert "klayout-checksize.log" in tracked
    # And the evidence the verdict actually turns on is a tracked file, not a
    # directory git happened to notice.
    on_disk = {p for p in _REAL_REFUSAL.rglob("*") if p.is_file()}
    assert len(tracked) >= 1
    assert len(on_disk) == len([p for p in out.stdout.split("\0") if p])


def test_submission_frame_steps_have_no_counterpart_in_this_tree(tmp_path):
    """The measured gap, recomputed against the real programs/ directory.

    Not an assertion that we have no frame check — a RESOLUTION. If somebody
    lands `die_slot_dimension_check.py` or `frame_marker_check.py` this test
    starts failing and the registry entry, not the claim, is what gets edited."""
    proj = _project(tmp_path)
    rep = trc.evaluate(proj, rundir=_REAL_REFUSAL,
                       image_resolver=_resolves, runner=_no_op_runner(rc=1))
    uncovered = set(rep.uncovered_in_tree)

    # The step that refused is the one with nothing of ours behind it.
    assert "KLayout.CheckSize" in uncovered
    assert "KLayout.GenerateID" in uncovered

    # And the gap is specific, not a blanket "we check nothing": the physical
    # decks DO have in-tree counterparts, so the finding is about the frame.
    assert "Checker.MagicDRC" not in uncovered
    assert "Checker.KLayoutAntenna" not in uncovered
    assert "Checker.KLayoutDensity" not in uncovered


def test_ladder_is_in_submission_failure_order():
    """A user must hit the refusals in the order a real submission would."""
    ids = [s.step_id for s in trc.SHUTTLES[trc.DEFAULT_SHUTTLE].ladder]
    assert ids.index("KLayout.ReadLayout") < ids.index("KLayout.CheckTopLevel")
    assert ids.index("KLayout.CheckTopLevel") < ids.index("KLayout.CheckSize")
    # The frame comes before the physics. This is the whole point of ordering
    # it: a seal-ring refusal stops the submission before any DRC deck runs, so
    # a report that led with DRC would put the reader's attention in the wrong
    # place.
    for later in ("Checker.KLayoutDensity", "Checker.MagicDRC",
                  "Checker.KLayoutDRC", "Checker.KLayoutAntenna"):
        assert ids.index("KLayout.CheckSize") < ids.index(later), later


def test_cob_adds_the_pad_mask_step_exactly_as_the_tool_does(tmp_path):
    proj = _project(tmp_path)
    without = trc.evaluate(proj, image_resolver=_never_resolves)
    with_cob = trc.evaluate(proj, cob=True, image_resolver=_never_resolves)
    plain = [s.step_id for s in without.steps]
    cob = [s.step_id for s in with_cob.steps]
    assert "KLayout.CheckPadMask" not in plain
    assert "KLayout.CheckPadMask" in cob
    assert cob.index("KLayout.CheckPadMask") > cob.index("KLayout.CheckSize")


# --------------------------------------------------------------------------- #
# The retired path: kept, marked, and never a pass
# --------------------------------------------------------------------------- #
def test_retired_shuttle_is_not_determined_even_with_a_perfect_run_dir(tmp_path):
    """A dead vendor's silence is neither a clean run nor a rejection."""
    proj = _project(tmp_path)
    rep = trc.evaluate(proj, shuttle_id="efabless_open_mpw",
                       rundir=_REAL_REFUSAL,
                       image_resolver=_resolves, runner=_no_op_runner(rc=0))
    assert rep.verdict == trc.NOT_DETERMINED
    assert rep.verdict != trc.PASS
    assert rep.verdict != trc.FAIL
    assert rep.shuttle_status == trc.RETIRED
    assert "2025" in rep.reason
    assert all(s.verdict == trc.NOT_DETERMINED for s in rep.steps)


def test_retired_shuttle_is_kept_not_deleted():
    """Deleting it would erase the record that this tree once had an external
    interface, and leave three programs looking orphaned rather than retired."""
    assert "efabless_open_mpw" in trc.SHUTTLES
    retired = trc.SHUTTLES["efabless_open_mpw"]
    assert retired.status == trc.RETIRED
    assert retired.retired_reason
    # And the live one is what a bare invocation asks.
    assert trc.SHUTTLES[trc.DEFAULT_SHUTTLE].status == trc.LIVE


def test_the_programs_still_pointed_at_the_dead_vendor_say_so():
    for name in ("mpw_precheck_driver.py", "mpw_precheck_result_gate.py"):
        text = (_PROGRAMS / name).read_text(encoding="utf-8")
        assert "RETIRED SHUTTLE" in text, name
        assert "tapeout_readiness_check" in text, name


def test_driver_blocked_is_classified_not_determined_not_a_retryable_hiccup():
    """BLOCKED against a retired counterparty is permanent, and an aggregator
    must be able to see that without re-deriving it."""
    assert driver.SHUTTLE_STATUS == "RETIRED"
    assert driver._VERDICT_CLASS["BLOCKED"] == "NOT_DETERMINED"
    assert driver._VERDICT_CLASS["SKIPPED_CONDITION"] == "NOT_DETERMINED"
    assert driver._VERDICT_CLASS["INCOMPLETE"] == "NOT_DETERMINED"
    assert driver._VERDICT_CLASS["PASS"] == "PASS"


# --------------------------------------------------------------------------- #
# Silence is never a pass
# --------------------------------------------------------------------------- #
def test_unreachable_tool_is_not_determined_and_exits_non_zero(tmp_path):
    proj = _project(tmp_path)
    rep = trc.evaluate(proj, image_resolver=_never_resolves)
    assert rep.verdict == trc.NOT_DETERMINED
    assert rep.layouts_found == 1

    rc = trc.main([str(proj), "--image", "no.such/image:never"])
    # NOT rc 0, and deliberately NOT rc 2 or rc 3 either: this repo credits a
    # rc-2 VACUOUS_PASS as a pass and reads rc 3 as PASS_WITH_WAIVERS.
    assert rc == 1


def test_a_project_with_no_layout_refuses_over_the_empty_set(tmp_path):
    proj = _project(tmp_path, with_layout=False)
    rep = trc.evaluate(proj, image_resolver=_resolves)
    assert rep.verdict == trc.NOT_DETERMINED
    assert rep.layouts_found == 0
    assert trc.main([str(proj)]) == 1


def test_every_verdict_line_states_its_denominator(tmp_path):
    proj = _project(tmp_path)
    for rep in (trc.evaluate(proj, image_resolver=_never_resolves),
                trc.evaluate(proj, rundir=_REAL_REFUSAL,
                             image_resolver=_resolves,
                             runner=_no_op_runner(rc=1))):
        line = rep.summary_line()
        assert "layouts_found=" in line
        assert "ladder_steps_required=" in line
        assert "steps_with_evidence=" in line


def test_a_run_that_wrote_nothing_is_not_determined_not_pass(tmp_path):
    proj = _project(tmp_path)
    empty = tmp_path / "empty_run"
    empty.mkdir()
    rep = trc.evaluate(proj, rundir=empty, image_resolver=_resolves,
                       runner=_no_op_runner(rc=0))
    assert rep.verdict == trc.NOT_DETERMINED
    assert rep.steps_with_evidence == 0


def test_a_missing_ladder_step_cannot_be_promoted_to_pass(tmp_path):
    """Every step that ran passed, one never ran — that is NOT_DETERMINED.

    Built by COMPLETING the real refusal (giving the refusing step the
    `state_out.json` it lacked) and then deleting one later step's directory, so
    the only difference from a clean run is the absence."""
    proj = _project(tmp_path)
    run = tmp_path / "run" / "runs" / "RUN_X"
    run.mkdir(parents=True)
    ladder = trc.SHUTTLES[trc.DEFAULT_SHUTTLE].ladder
    for i, st in enumerate(ladder, start=1):
        d = run / f"{i:02d}-{trc._slug(st.step_id)}"
        d.mkdir()
        (d / "state_out.json").write_text("{}")
    full = trc.evaluate(proj, rundir=tmp_path / "run",
                        image_resolver=_resolves, runner=_no_op_runner(rc=0))
    assert full.verdict == trc.PASS, full.reason

    # Now remove exactly one step's evidence.
    victim = run / f"{len(ladder):02d}-{trc._slug(ladder[-1].step_id)}"
    (victim / "state_out.json").unlink()
    victim.rmdir()
    partial = trc.evaluate(proj, rundir=tmp_path / "run",
                           image_resolver=_resolves, runner=_no_op_runner(rc=0))
    assert partial.verdict == trc.NOT_DETERMINED
    assert ladder[-1].step_id in partial.undetermined_steps


def test_a_clean_ladder_with_a_non_zero_tool_exit_is_not_a_pass(tmp_path):
    """We do not resolve a disagreement with the counterparty in our favour."""
    proj = _project(tmp_path)
    run = tmp_path / "run" / "runs" / "RUN_X"
    run.mkdir(parents=True)
    for i, st in enumerate(trc.SHUTTLES[trc.DEFAULT_SHUTTLE].ladder, start=1):
        d = run / f"{i:02d}-{trc._slug(st.step_id)}"
        d.mkdir()
        (d / "state_out.json").write_text("{}")
    rep = trc.evaluate(proj, rundir=tmp_path / "run",
                       image_resolver=_resolves, runner=_no_op_runner(rc=7))
    assert rep.verdict == trc.NOT_DETERMINED


# --------------------------------------------------------------------------- #
# The command is the tool's own, and the tool is not reimplemented
# --------------------------------------------------------------------------- #
def _source_without_docstrings(path: Path) -> str:
    """The file's CODE, with every docstring removed.

    The distinction this draws is the one that matters for #1744. A docstring
    RECORDS what the counterparty said — the measurement section quotes its
    refusal verbatim, and quoting evidence is the opposite of encoding a rule.
    The code is where a rule would have to live to do any harm: a constant, a
    threshold, a geometry, a comparison. So the scan below reads the code and
    lets the prose say what happened.

    This is a narrowing of scope, not of strength: a forbidden token moved out
    of the docstring and into a constant, a default, a comment or a comparison
    is still caught, because none of those is a docstring."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    spans = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            spans.append((first.lineno, first.end_lineno))
    drop = {n for a, b in spans for n in range(a, b + 1)}
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(l for i, l in enumerate(lines, start=1) if i not in drop)


def test_it_wraps_rather_than_reimplements():
    """No slot dimension, density window, DRC rule or pad geometry lives here.

    A reimplementation would be ours again, and could drift into passing. The
    registry may name the upstream STEPS; it may not encode what they enforce."""
    code = _source_without_docstrings(_PROGRAMS / "tapeout_readiness_check.py")
    # The upstream tool's own vocabulary for the things it MEASURES. If any of
    # these turns up in the code, this file has started deciding for itself.
    for forbidden in ("0p5x0p5", "GUARD_RING_MK", "Metal5", "0.001",
                      "dbu", "um2", "density_window"):
        assert forbidden not in code, forbidden

    # And the exclusion above must not be a loophole: prove the scanner still
    # sees ordinary code by checking something that IS there.
    assert "def parse_run_evidence" in code
    assert "SHUTTLES" in code


def test_the_command_is_the_upstream_documented_invocation(tmp_path):
    shuttle = trc.SHUTTLES[trc.DEFAULT_SHUTTLE]
    layout = tmp_path / "design" / "chip_top.gds"
    layout.parent.mkdir(parents=True)
    layout.write_bytes(b"x")
    rundir = tmp_path / "rundir"
    rundir.mkdir()
    cmd = trc.build_command(shuttle, "img:latest", layout, rundir,
                            "chip_top", "1x1", False, "")
    assert cmd[:4] == ["docker", "run", "--rm", "--network=none"]
    # MEASURED, not assumed: `-u` breaks the nix entrypoint (no home / nix db
    # permission) and `-w` breaks flake resolution. Neither may come back.
    assert "-u" not in cmd
    assert "-w" not in cmd
    assert "python" in cmd and "precheck.py" in cmd
    assert "--input" in cmd and "--dir" in cmd


# --------------------------------------------------------------------------- #
# The checklist must STATE the external verdict, not omit it
# --------------------------------------------------------------------------- #
def _blocker_complete_project(tmp_path):
    """A project carrying every BLOCKER row and no shuttle evidence at all."""
    proj = tmp_path / "p"
    for rel in ("phase3/stage4/gds/chip_top.gds",
                "phase2/stage2/synth/top.v",
                "phase3/stage3/pnr/top.def",
                "phase3/stage3/pnr/sta.rpt",
                "reports/phase3/drc_signoff.rpt",
                "reports/phase3/lvs.rpt",
                "phase3/stage4/foundry_handoff/mask_spec.json",
                "phase3/stage4/foundry_handoff/wat_plan.json",
                "phase3/stage4/foundry_handoff/corner_test_vectors.json",
                "reports/phase2/fpga/on_board_pass.json"):
        p = proj / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}")
    return proj


def test_checklist_states_the_external_refusal_even_when_nobody_asked(tmp_path):
    """THE GUARD. Before #1744 this project produced READY_FOR_TAPEOUT and said
    nothing at all about the one verdict that is not ours."""
    proj = _blocker_complete_project(tmp_path)
    assert checklist.main([str(proj)]) == 0
    payload = json.loads(
        (proj / "reports/audit/tapeout_checklist.json").read_text())

    # The block exists UNCONDITIONALLY — a key that only appears when there is
    # good news is a key nobody notices is missing.
    assert "external_refusal" in payload
    ext = payload["external_refusal"]
    assert ext["verdict"] == "NOT_DETERMINED"
    assert ext["present"] is False
    assert ext["gate"] == "tapeout_readiness_check"

    # The retired path is named as retired, in the artefact, not only in a
    # docstring somebody would have to go and read.
    retired = {r["gate"]: r for r in ext["retired_paths"]}
    assert retired["mpw_precheck_result_gate"]["status"] == "RETIRED"

    # And it reaches the reviewer's TODO rather than sitting in a field.
    assert any("EXTERNAL REFUSAL" in t for t in payload["reviewer_todo"])


def test_the_row_the_checklist_watches_is_the_file_the_gate_writes():
    """A row watching a path nothing writes is a row that is always absent, and
    an always-absent advisory row is indistinguishable from a satisfied one."""
    rows = {n: pat for n, pat, _sev, _gate in checklist._CHECKLIST_ITEMS}
    assert rows["shuttle_readiness"] == trc.READINESS_ARTEFACT
    assert checklist._READINESS_ARTEFACT == trc.READINESS_ARTEFACT


def test_the_gate_writes_that_file_by_default(tmp_path):
    proj = _project(tmp_path)
    assert trc.main([str(proj), "--image", "no.such/image:never"]) == 1
    written = proj / trc.READINESS_ARTEFACT
    assert written.is_file()
    assert json.loads(written.read_text())["verdict"] == "NOT_DETERMINED"


def test_checklist_names_the_live_gate_as_a_row():
    gates = {g for _n, _p, _s, g in checklist._CHECKLIST_ITEMS if g}
    assert "tapeout_readiness_check" in gates
    # The retired one is KEPT as a row, not deleted.
    assert "mpw_precheck_result_gate" in gates
    assert "RETIRED" in checklist._GATE_NOTES["mpw_precheck_result_gate"]


@pytest.mark.parametrize("token", ["PASS", "FAIL", "NOT_DETERMINED"])
def test_checklist_reads_back_the_gate_s_own_verdict(tmp_path, token):
    proj = _blocker_complete_project(tmp_path)
    art = proj / "reports/audit/tapeout_readiness.json"
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text(json.dumps({"verdict": token, "reason": "measured"}))
    assert checklist.main([str(proj)]) == 0
    payload = json.loads(
        (proj / "reports/audit/tapeout_checklist.json").read_text())
    assert payload["external_refusal"]["verdict"] == token


def test_an_unrecognised_verdict_token_is_not_promoted_to_a_pass(tmp_path):
    proj = _blocker_complete_project(tmp_path)
    art = proj / "reports/audit/tapeout_readiness.json"
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text(json.dumps({"verdict": "OK"}))
    assert checklist.main([str(proj)]) == 0
    payload = json.loads(
        (proj / "reports/audit/tapeout_checklist.json").read_text())
    assert payload["external_refusal"]["verdict"] == "NOT_DETERMINED"
