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
import shutil
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


def test_the_remaining_gap_is_exactly_the_operator_specific_steps(tmp_path):
    """The measured gap, recomputed against the real programs/ directory.

    Not an assertion — a RESOLUTION, and it has already moved once. When this
    test was written it pinned `KLayout.CheckSize` and `KLayout.GenerateID` as
    UNCOVERED and said: "if somebody lands `die_slot_dimension_check.py` this
    test starts failing and the registry entry, not the claim, is what gets
    edited." `general_precheck` landed, the registry entry was edited, and the
    claim this file pins is now the NARROWER and more useful one.

    WHAT THE GAP IS NOW, and why it is the right shape to be left at. The
    operator's precheck is a LibreLane SequentialFlow whose custom steps are
    mostly general; exactly two of them are the OPERATOR's own:

        KLayout.CheckPadMask   their pad mask, published per purchasable slot
        KLayout.GenerateID     their die-id fixtures and their ID encoding

    Those two CANNOT have an in-tree counterpart, because a counterpart would
    be a mask and an encoding we invented pretending to be theirs — and this
    gate exists precisely because an outside party's rule is not ours to
    write. Every other ladder step now resolves. So the assertion below is not
    "the gap shrank"; it is "the gap is now exactly the part that must stay a
    gap", which is a claim that can fail in both directions:

      * if a general step regresses to UNCOVERED, the first block fails;
      * if somebody lands a `pad_ring_mask_check` or a `die_id_marker_check`
        that claims to check somebody else's mask or encoding, the second
        block fails and that program gets read very carefully.
    """
    proj = _project(tmp_path)
    rep = trc.evaluate(proj, rundir=_REAL_REFUSAL,
                       image_resolver=_resolves, runner=_no_op_runner(rc=1))
    uncovered = set(rep.uncovered_in_tree)
    # The steps THIS RUN evaluated, not the whole registry: `CheckPadMask` is
    # cob-only and is in the ladder only when --cob was set, so intersecting
    # against the registry would demand a step this run never had.
    evaluated = {s.step_id for s in rep.steps}

    operator_specific = {"KLayout.CheckPadMask", "KLayout.GenerateID"}
    assert uncovered == (operator_specific & evaluated), (
        "the uncovered set must be exactly the operator-specific steps; "
        f"got {sorted(uncovered)}")

    # The two that moved, named so the change is legible rather than implied.
    assert "KLayout.CheckSize" not in uncovered
    assert "Checker.KLayoutZeroAreaPolygons" not in uncovered
    # And the physical decks still resolve, as they always did.
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
    ladder = _stages()
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
    for i, st in enumerate(_stages(), start=1):
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
# THE IMAGE IS PINNED BY DIGEST — because a verdict nobody can re-run is not a
# verdict. Everything in this section is about one question: if this gate
# refuses a layout today, does it refuse the same layout tomorrow?
# --------------------------------------------------------------------------- #
def _pinned_image_present():
    """Is the pinned image on this host? Asked WITHOUT this program's help.

    The tests below check whether `tapeout_readiness_check` can see an image
    that is there, so their precondition may not be established by asking
    `tapeout_readiness_check` whether it can see it — that turns a broken
    resolver into a skipped test instead of a failing one, which is how a guard
    stops guarding. `docker image inspect` is the daemon's own answer."""
    if not shutil.which("docker"):
        return False
    image = trc.SHUTTLES[trc.DEFAULT_SHUTTLE].default_image
    try:
        q = subprocess.run(["docker", "image", "inspect", image,
                            "--format", "{{.Id}}"],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return q.returncode == 0 and bool(q.stdout.strip())


def test_the_live_shuttle_image_is_pinned_by_digest_not_by_a_tag():
    """A tag is a mutable pointer; a digest names bytes.

    `:main` and `:latest` resolve to whatever the operator pushed most
    recently, so the same layout could be refused today and accepted tomorrow
    with nothing in this tree having changed. The tag is KEPT in its own field,
    because `docker pull <tag>` is what an operator types — but only
    `default_image` ever reaches an argv."""
    live = trc.SHUTTLES[trc.DEFAULT_SHUTTLE]
    assert live.status == trc.LIVE
    assert "@sha256:" in live.default_image, live.default_image
    assert trc.pin_kind(live.default_image) == "digest"
    # A 64-hex digest, not a prefix somebody trimmed for readability.
    digest = live.default_image.split("@sha256:")[1]
    assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)
    # And the moving tag it was resolved from is recorded, not run.
    assert trc.pin_kind(live.image_tag) == "tag"
    assert live.image_tag.split(":")[0] == live.default_image.split("@")[0]


def test_the_digest_is_the_thing_that_gets_run(tmp_path):
    """The pin has to reach the argv, or it is a comment."""
    shuttle = trc.SHUTTLES[trc.DEFAULT_SHUTTLE]
    proj = _project(tmp_path)
    rep = trc.evaluate(proj, image_resolver=_resolves,
                       runner=_no_op_runner(rc=0),
                       rundir=_complete_run(tmp_path))
    assert shuttle.default_image in rep.command
    assert shuttle.image_tag not in rep.command
    assert rep.image_pinned_by == "digest"


def test_a_tag_override_is_honoured_and_recorded_as_unpinned(tmp_path):
    """`--image some:tag` still runs — and the report says it was a tag.

    Refusing the override outright would break the operator's ability to test
    a candidate image, and this gate is not the place to take that away. What
    it must not do is let the resulting verdict LOOK as reproducible as a
    pinned one, so the distinction is recorded in a field an aggregator can
    read instead of being left in the shape of a string."""
    proj = _project(tmp_path)
    rep = trc.evaluate(proj, image="some.registry/precheck:nightly",
                       image_resolver=_resolves, runner=_no_op_runner(rc=0),
                       rundir=_complete_run(tmp_path))
    assert rep.image == "some.registry/precheck:nightly"
    assert rep.image_pinned_by == "tag"


def test_docker_images_dash_q_cannot_see_a_digest_pinned_image():
    """The bug the resolver fix exists for, proven against the real daemon.

    `docker images -q` matches on repository:TAG. Given a DIGEST reference it
    prints nothing and exits 0 — indistinguishable from an image that is not
    there. So the moment this gate was pinned by digest, the old probe reported
    IMAGE_ABSENT on every host that had the image and the counterparty stopped
    being asked at all.

    This runs against the real docker daemon, because the claim is about that
    daemon's behaviour and a mock of it would only assert what the author
    already believed. Skipped where there is no daemon or the image is not
    present locally — a skip says "not measured here", which is the honest
    thing for a test that cannot reach its subject."""
    image = trc.SHUTTLES[trc.DEFAULT_SHUTTLE].default_image
    if not _pinned_image_present():
        pytest.skip("the pinned precheck image is not present on this host")

    # The image IS here — and the program's own probe has to agree.
    #
    # THE SKIP GUARD ABOVE DELIBERATELY DOES NOT CALL `_image_is_local`.
    # Measured: when it did, reverting the fix made this test SKIP rather than
    # FAIL, because the guard asked the very function under test whether its
    # subject was reachable. A guard that goes quiet exactly when the thing it
    # guards is broken has not been shown to check anything, so presence is
    # established independently and the program's answer is then ASSERTED.
    assert trc._image_is_local(image) is True, (
        "the pinned image is present on this host (established above without "
        "asking this program) and default_image_resolver cannot see it — a "
        "digest-pinned gate that reports IMAGE_ABSENT never asks the "
        "counterparty anything")

    # And the probe it used to use says nothing at all, with rc 0.
    q = subprocess.run(["docker", "images", "-q", image],
                       capture_output=True, text=True, timeout=60)
    assert q.returncode == 0
    assert q.stdout.strip() == "", (
        "docker images -q resolved a digest reference on this host; if that is "
        "now true generally the comment in default_image_resolver is stale, but "
        "`image inspect` is still the correct probe and nothing here changes")


def test_the_report_names_the_bytes_that_answered(tmp_path):
    """Which content produced this verdict, read back from the daemon.

    Not the string the caller typed: `--image` lets that be anything. Against
    the real image, the recorded repo digest must be the pin."""
    image = trc.SHUTTLES[trc.DEFAULT_SHUTTLE].default_image
    if not _pinned_image_present():
        pytest.skip("the pinned precheck image is not present on this host")
    ident, digests = trc.image_identity(image)
    assert ident.startswith("sha256:")
    assert image in digests, digests


# --------------------------------------------------------------------------- #
# IMAGE ABSENT / CONTAINER FAILED TO START — each its own state, each a FAIL,
# and NEITHER may ever read as "no refusals found".
# --------------------------------------------------------------------------- #
def _docker_start_failure_runner(rc):
    """A runner standing in for docker refusing to create the container.

    Real shape: docker writes its own diagnostic to stderr, exits 125/126/127,
    and NOTHING is written to the run directory — the tool inside never ran, so
    there is no per-stage evidence and no error.log of its own."""
    def _run(cmd, timeout):
        return rc, "", ("docker: Error response from daemon: failed to create "
                        "task for container: OCI runtime create failed.")
    return _run


def test_image_absent_is_its_own_state_and_fails_the_gate(tmp_path):
    proj = _project(tmp_path)
    rep = trc.evaluate(proj, image_resolver=_never_resolves)
    assert rep.state == trc.STATE_IMAGE_ABSENT
    assert rep.verdict == trc.NOT_DETERMINED
    assert trc.verdict_for_state(rep.state) != trc.PASS
    assert rep.state not in trc.ACCEPT_STATES


def test_a_container_that_would_not_start_is_a_different_state(tmp_path):
    """Broken host, not missing config — different cause, different fix.

    Docker's own exit codes for "the container never started" are 125/126/127,
    and they are disjoint from the upstream precheck's own exits (it leaves via
    0 or 1). Merging the two into one tidier "tool unavailable" would hand a
    broken daemon and an unpulled image to the same person with the same
    sentence."""
    proj = _project(tmp_path)
    for rc in (125, 126, 127):
        rep = trc.evaluate(proj, image_resolver=_resolves,
                           runner=_docker_start_failure_runner(rc),
                           rundir=tmp_path / f"empty{rc}")
        assert rep.state == trc.STATE_CONTAINER_FAILED_TO_START, rc
        assert rep.verdict == trc.NOT_DETERMINED, rc
        assert rep.state != trc.STATE_IMAGE_ABSENT

    # A tool that DID start and merely wrote nothing is the other state: same
    # verdict, different diagnosis, and the report must not conflate them.
    other = trc.evaluate(proj, image_resolver=_resolves,
                         runner=_no_op_runner(rc=1),
                         rundir=tmp_path / "empty_ok")
    assert other.state == trc.STATE_NO_EVIDENCE


@pytest.mark.parametrize("case", ["image_absent", "container_failed"])
def test_a_never_asked_run_can_never_read_as_no_refusals_found(case, tmp_path):
    """THE DEFECT THIS GATE EXISTS FOR, NOT RE-CREATED INSIDE IT.

    On both paths no stage refused — because no stage was asked. An aggregator
    that counted `failed_steps` would see 0 for both, exactly as it would for a
    clean run, and a human skimming `failed=0` reads an all-clear.

    So three things are required of every never-asked path: the summary line
    says so in words, every stage is listed under `stages_never_ran`, and the
    process exits 1. A count of zero is only safe next to a denominator, and
    this asserts the denominator is there."""
    proj = _project(tmp_path)
    if case == "image_absent":
        rep = trc.evaluate(proj, image_resolver=_never_resolves)
    else:
        rep = trc.evaluate(proj, image_resolver=_resolves,
                           runner=_docker_start_failure_runner(125),
                           rundir=tmp_path / "empty")

    assert rep.state in trc.NEVER_ASKED_STATES
    assert rep.failed_steps == []            # nothing refused ...
    assert rep.stages_attempted == 0         # ... because nothing was asked
    assert len(rep.stages_never_ran) == rep.upstream_stages_total > 0
    assert rep.stages_never_ran == [s.step_id for s in rep.steps]

    line = rep.summary_line()
    assert "THE COUNTERPARTY WAS NEVER ASKED" in line
    assert f"0 of {rep.upstream_stages_total} stage(s) ran" in line
    assert "no refusals" not in line.lower()

    # And it exits the way a refusal exits.
    rc = trc.main([str(proj), "--image", "no.such/image:never",
                   "--json", str(tmp_path / "out.json")])
    assert rc == 1


def test_every_terminal_path_names_a_state_and_only_one_of_them_accepts(
        tmp_path):
    """No path may leave `state` unset, and only LADDER_PASSED is an accept."""
    proj = _project(tmp_path)
    seen = {
        trc.evaluate(proj, shuttle_id="nope").state,
        trc.evaluate(proj, shuttle_id="efabless_open_mpw").state,
        trc.evaluate(_project(tmp_path / "empty", with_layout=False)).state,
        trc.evaluate(proj, image_resolver=_never_resolves).state,
        trc.evaluate(proj, image_resolver=_resolves,
                     runner=_no_op_runner(rc=1),
                     rundir=tmp_path / "nothing").state,
        trc.evaluate(proj, image_resolver=_resolves, runner=_no_op_runner(rc=1),
                     rundir=_REAL_REFUSAL).state,
        trc.evaluate(proj, image_resolver=_resolves, runner=_no_op_runner(rc=0),
                     rundir=_complete_run(tmp_path)).state,
        trc.evaluate(proj, image_resolver=_resolves, runner=_no_op_runner(rc=7),
                     rundir=_complete_run(tmp_path, "run7")).state,
    }
    assert "" not in seen
    assert seen & trc.ACCEPT_STATES == {trc.STATE_LADDER_PASSED}
    for state in seen:
        if state != trc.STATE_LADDER_PASSED:
            assert trc.verdict_for_state(state) != trc.PASS, state
    # An unrecognised state is a decision nobody made, and no verdict is claimed
    # for a decision nobody made.
    assert trc.verdict_for_state("SOMETHING_NEW") == trc.NOT_DETERMINED


# --------------------------------------------------------------------------- #
# The stage sequence is hard-coded, so it has to be able to go stale OUT LOUD
# --------------------------------------------------------------------------- #
def test_a_flow_that_grew_a_stage_is_not_determined_rather_than_passed(
        tmp_path):
    """A denominator we cannot trust is not one we may pass on.

    The sequence comes from one pinned image. Upstream can add, rename or
    reorder a stage, and a gate that kept counting against the old list would
    report a confident `16 of 16` for a flow that now has seventeen — a PASS
    over a stage nobody looked at."""
    proj = _project(tmp_path)
    root = _complete_run(tmp_path)
    run = root / "runs" / "RUN_X"
    extra = run / "17-klayout-somethingnew"
    extra.mkdir()
    (extra / "state_out.json").write_text("{}")

    rep = trc.evaluate(proj, rundir=root, image_resolver=_resolves,
                       runner=_no_op_runner(rc=0))
    assert rep.state == trc.STATE_STAGE_MAP_STALE
    assert rep.verdict == trc.NOT_DETERMINED
    assert "somethingnew" in rep.reason


def test_a_renumbered_stage_is_detected_too(tmp_path):
    """Reordering is the drift that a per-name check alone would miss."""
    proj = _project(tmp_path)
    root = _complete_run(tmp_path)
    run = root / "runs" / "RUN_X"
    stages = _stages()
    a = run / f"01-{trc._slug(stages[0].step_id)}"
    a.rename(run / f"09-{trc._slug(stages[0].step_id)}_moved")
    (run / f"09-{trc._slug(stages[0].step_id)}_moved").rename(
        run / f"09-{trc._slug(stages[0].step_id)}")
    rep = trc.evaluate(proj, rundir=root, image_resolver=_resolves,
                       runner=_no_op_runner(rc=0))
    assert rep.state == trc.STATE_STAGE_MAP_STALE
    assert rep.verdict == trc.NOT_DETERMINED


def test_the_declared_sequence_is_the_one_the_real_tool_writes():
    """Sixteen stages, and the slugs the counterparty's own run directory used.

    Captured from a REAL run of the pinned image that reached every stage (a
    synthetic die built to the operator's own slot geometry, which gets past the
    seal-ring refusal our published layout stops at). This is what makes the
    denominator a measurement rather than a memory."""
    observed = [
        "01-klayout-readlayout", "02-klayout-checktoplevel",
        "03-klayout-checksize", "04-klayout-generateid", "05-klayout-render",
        "06-klayout-density", "07-checker-klayoutdensity",
        "08-klayout-zeroareapolygons", "09-checker-klayoutzeroareapolygons",
        "10-klayout-antenna", "11-checker-klayoutantenna", "12-magic-drc",
        "13-checker-magicdrc", "14-klayout-drc", "15-checker-klayoutdrc",
        "16-klayout-writelayout",
    ]
    declared = _stages()
    assert len(declared) == 16
    for name, step in zip(observed, declared):
        head, _, slug = name.partition("-")
        assert int(head) == declared.index(step) + 1
        assert trc._flat(slug) == trc._flat(trc._slug(step.step_id)), name

    # And `--cob` inserts the pad-mask stage at 4, renumbering the rest —
    # measured on a real `--cob` run of the same die, which wrote
    # `04-klayout-checkpadmask`.
    cob = _stages(cob=True)
    assert len(cob) == 17
    assert cob[3].step_id == "KLayout.CheckPadMask"
    assert trc._slug(cob[3].step_id) == "klayout-checkpadmask"
    assert trc.stage_map_drift(cob, [(4, "klayoutcheckpadmask", False)]) == []
    # ... and that same directory is DRIFT against the non-cob sequence, which
    # is what stops a cob run being scored on the wrong denominator.
    assert trc.stage_map_drift(declared, [(4, "klayoutcheckpadmask", False)])

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


# --------------------------------------------------------------------------- #
# THE FLOW STEP — step 37.5ic, the gate as the flow ACTUALLY invokes it
#
# Everything above drives `evaluate()`, the library call. The flow never makes
# that call. `flow_compliance_check._check_program_exit_zero` runs
#
#     tapeout_readiness_check . --json reports/phase3/shuttle_precheck.json
#
# with `cwd` set to the PROJECT ROOT, and reads exactly two things back: the
# process exit STATUS, and whether the declared artefact appeared. Three
# properties live in that gap and in no test above.
#
#   * The project argument is `.` and the `--json` path is RELATIVE, so the
#     artefact lands where the step declares only if both resolve against the
#     same directory. No test above ever ran the CLI from a project root.
#
#   * The artefact is written on EVERY path, including the ones that determined
#     nothing. So the step's `required_outputs` check is SATISFIED by a run that
#     never reached the counterparty, and the exit status is the only thing
#     separating "the shuttle looked and was fine" from "nobody asked". A
#     presence check over this file is the exact defect this gate exists for,
#     one directory further down.
#
#   * That exit status is read by a classifier which credits rc 2 as
#     VACUOUS_PASS and rc 3 as PASS_WITH_WAIVERS — both of which aggregate as
#     PASSES. "`main` returns non-zero" is therefore not the property that
#     matters; it has to be the ONE non-zero this classifier reads as a failure,
#     and that is asserted here THROUGH the classifier rather than restated.
# --------------------------------------------------------------------------- #
import shlex

import yaml

import _hostpaths

fcc = importlib.import_module("flow_compliance_check")
enforcement = importlib.import_module("flow_gate_enforcement_audit")

#: The step this program was written for, and the argv its declared gate
#: command reduces to. `test_the_flow_declares_this_gate_...` re-derives both
#: from the checked-in flow definition, so a yaml edit that moves the artefact
#: turns THAT test red and tells the author the cases below are now driving a
#: command the flow no longer issues.
_STEP_ID = "37.5ic"
_DECLARED_OUT = "reports/phase3/shuttle_precheck.json"
_DECLARED_ARGV = [".", "--json", _DECLARED_OUT]


def _flow_yaml():
    """The checked-in flow definition — the one the flow engine itself reads."""
    p = _hostpaths.require_repo("vibe-ic-marketplace", "plugins", "vibe-ic",
                                "flow", "phase1_phase2_phase3.yaml")
    # Not merely A copy of the flow: the SAME file `flow_compliance_check`
    # resolves for itself. A test that read a second copy would keep passing
    # while the engine read something else.
    assert p.resolve() == Path(fcc.DEFAULT_FLOW_DEF).resolve()
    return p


def _stages(cob=False):
    """The stage sequence a run with these options actually has.

    NOT the whole registry: `KLayout.CheckPadMask` is inserted only under
    `--cob`, and the upstream tool renumbers everything after it when it is.
    Building a non-cob fixture from the cob-inclusive list produced directories
    whose ordinals disagreed with the sequence by one from stage 5 on, which
    `stage_map_drift` correctly reports as a stale stage map. Getting this wrong
    in a fixture is cheap; getting it wrong in the registry would make the gate
    refuse to judge every real run, so the drift check earning its keep here is
    the point rather than an inconvenience."""
    return tuple(s for s in trc.SHUTTLES[trc.DEFAULT_SHUTTLE].ladder
                 if cob or not s.cob_only)


def _complete_run(tmp_path, name="run", cob=False):
    """A run directory in which every stage COMPLETED.

    Built the way the upstream tool builds one — a numbered directory per stage
    carrying `state_out.json` — because that file is the discriminator the
    parser turns on. EVERY stage, not only the ones that can refuse: a real
    complete run writes all sixteen, and a fixture that wrote nine would be
    asserting that a run which skipped Render and WriteLayout is clean."""
    run = tmp_path / name / "runs" / "RUN_X"
    run.mkdir(parents=True)
    for i, st in enumerate(_stages(cob), start=1):
        d = run / f"{i:02d}-{trc._slug(st.step_id)}"
        d.mkdir()
        (d / "state_out.json").write_text("{}")
    return tmp_path / name


def _run_as_the_flow_step(monkeypatch, proj, *extra):
    """Drive the CLI exactly as the flow does: cwd = the project, project `.`,
    and the declared RELATIVE --json path. Returns (rc, artefact, payload)."""
    monkeypatch.chdir(proj)
    rc = trc.main(_DECLARED_ARGV + list(extra))
    art = proj / _DECLARED_OUT
    payload = json.loads(art.read_text()) if art.is_file() else None
    return rc, art, payload


def _flow_gate(proj, cmd):
    """Run one gate the way `flow_compliance_check` runs it, and return
    (ok, snippet, ledger_row). This spawns the REAL program in a subprocess —
    no seam is injected, because the seam is not there when the flow runs."""
    before = len(fcc._GATE_LEDGER)
    ok, snippet = fcc._check_program_exit_zero(proj, cmd)
    row = fcc._GATE_LEDGER[before:][-1]
    return ok, snippet, row


# ─────────────────────────────────── the declaration, re-derived from the yaml
def test_the_flow_declares_this_gate_with_the_path_this_program_writes():
    """The step, its slot, its command and its declared output — from the file.

    Read rather than restated: the point of the step is that the artefact the
    flow will look for is the artefact the gate command writes, and those are
    two different lines in two different files."""
    flow = yaml.safe_load(_flow_yaml().read_text())
    steps = {str(s.get("id")): s for s in flow.get("steps", [])}
    assert _STEP_ID in steps, (
        f"step {_STEP_ID} is not declared in the flow definition; the cases "
        f"below drive a gate no step invokes")
    step = steps[_STEP_ID]

    # THE BLOCKING SLOT, NOT THE ADVISORY ONE. A shuttle refusal recorded and
    # continued past is not an external bar, it is a note.
    #
    # The step's gate is an `all_of` of `program_exit_zero` clauses, and every
    # clause of an all_of is blocking, so the requirement is that this gate be
    # reachable through one of them — not that it be the only one. It used to be
    # the direct clause; the step now runs TWO arms on the same layout and it is
    # `tapeout_precheck` that issues this gate's command. Asserting the old
    # shape kept this test red on a tree where the wiring was correct, which
    # taught nobody anything, so what is asserted now is the property that
    # actually has to hold: a blocking clause, and a real chain from it to this
    # program.
    gate = step["gate"]
    clauses = gate.get("all_of", [gate])
    cmds = [c["program_exit_zero"] for c in clauses if "program_exit_zero" in c]
    assert cmds, sorted(gate)
    assert len(cmds) == len(clauses), (
        "every clause of this step's gate must be blocking; a non-blocking "
        f"clause would let one arm's refusal be recorded and walked past: {clauses}")

    # Each blocking command resolves to a program that exists — the same
    # resolution the flow engine performs, so "program not found" cannot hide
    # behind a name.
    for cmd in cmds:
        assert fcc._resolve_program_cmd(cmd, cwd=None), cmd

    # THE CHAIN FROM THE BLOCKING CLAUSE TO THIS PROGRAM, re-derived rather than
    # asserted. `tapeout_precheck` is the merge of the two arms; the operator's
    # arm IS this gate, invoked with the argv the cases below drive and writing
    # the artefact the step declares. Read out of that program so a refactor
    # that stops invoking this one turns THIS test red rather than leaving a
    # section of dead cases quietly driving a command nobody issues.
    entry = importlib.import_module("tapeout_precheck")
    src = Path(entry.__file__).read_text(encoding="utf-8")
    assert any(shlex.split(c)[0] == "tapeout_precheck" for c in cmds), cmds
    assert "tapeout_readiness_check.py" in src, (
        "the blocking gate no longer reaches tapeout_readiness_check")
    assert entry.THEIR_ARM_ARTEFACT == _DECLARED_OUT, entry.THEIR_ARM_ARTEFACT
    assert _DECLARED_ARGV[1] == "--json"

    # And the artefact the step will be judged on is among the ones this chain
    # writes. The step declares more than one output now (the merge, our arm,
    # theirs, the release documents); the one THIS program owns must be there.
    assert _DECLARED_OUT in step["required_outputs"], step["required_outputs"]


# ───────────────────────────── every outcome writes exactly the declared file
#: (case, expected verdict, expected rc). NOT_DETERMINED and FAIL deliberately
#: share rc 1 — the distinction lives in the `verdict` field, where an
#: aggregator must read it on purpose. Only a real clean ladder is rc 0.
_FLOW_CASES = (
    ("absent_gds", trc.NOT_DETERMINED, 1),
    ("unreachable", trc.NOT_DETERMINED, 1),
    ("refusal", trc.FAIL, 1),
    ("pass", trc.PASS, 0),
)


def _arrange(case, tmp_path, monkeypatch):
    """Put the tree and the seams into the state `case` names."""
    if case == "absent_gds":
        return _project(tmp_path, with_layout=False), ()
    proj = _project(tmp_path)
    if case == "unreachable":
        monkeypatch.setattr(trc, "default_image_resolver", _never_resolves)
        return proj, ()
    monkeypatch.setattr(trc, "default_image_resolver", _resolves)
    if case == "refusal":
        # The counterparty's OWN run directory, captured from its own tool.
        monkeypatch.setattr(trc, "default_runner", _no_op_runner(rc=1))
        return proj, ("--rundir", str(_REAL_REFUSAL))
    monkeypatch.setattr(trc, "default_runner", _no_op_runner(rc=0))
    return proj, ("--rundir", str(_complete_run(tmp_path)))


@pytest.mark.parametrize("case,verdict,rc", _FLOW_CASES)
def test_the_declared_artefact_is_written_on_every_flow_step_outcome(
        case, verdict, rc, tmp_path, monkeypatch):
    """Presence is NOT the signal, and the relative paths resolve together.

    The artefact appears for all four outcomes — including the two that
    determined nothing — so a step check that only asks whether
    `reports/phase3/shuttle_precheck.json` exists passes a run in which the
    counterparty was never asked. What separates them is the exit status and
    the `verdict` field, and both are asserted here."""
    proj, extra = _arrange(case, tmp_path, monkeypatch)
    got_rc, art, payload = _run_as_the_flow_step(monkeypatch, proj, *extra)

    assert art.is_file(), (
        f"[{case}] the step declares {_DECLARED_OUT} as a required output and "
        f"the gate wrote nothing there")
    assert payload["verdict"] == verdict, f"[{case}] {payload['reason']}"
    assert got_rc == rc, f"[{case}] {payload['reason']}"
    # rc 2 and rc 3 are the two non-zeros this repo credits as passes.
    if verdict != trc.PASS:
        assert got_rc not in (0, 2, 3), (
            f"[{case}] rc {got_rc} is read as a PASS tier by "
            f"flow_compliance_check._check_program_exit_zero")


# ───────────────────────────── the one that matters: silence through the FLOW
def test_an_unreachable_counterparty_is_a_flow_step_FAIL_not_a_vacuous_pass():
    """THE case this gate exists for, asserted through the flow's OWN classifier.

    A `main() == 1` assertion measures the program. It does not measure what
    the flow does with that 1, and the flow is where the damage would be:
    `_check_program_exit_zero` maps rc 2 to VACUOUS_PASS and rc 3 to
    PASS_WITH_WAIVERS, and both aggregate as passes. So the property is stated
    where it is consumed — the classifier is run for real, on a real subprocess,
    and its own verdict word is read back out of its own ledger.

    Deterministic without a network: the image name cannot resolve locally, and
    `--pull` is off, so `default_image_resolver` returns None on any host."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        proj = _project(Path(td))
        cmd = ("tapeout_readiness_check . --json " + _DECLARED_OUT
               + " --image no.such.registry.invalid/never:never")
        ok, snippet, row = _flow_gate(proj, cmd)

        assert ok is False, snippet
        assert row["rc"] == 1, row
        assert row["verdict"] == "FAIL", row
        assert not snippet.startswith(fcc._VACUOUS_HINT_PREFIX), snippet
        assert not snippet.startswith(fcc._WAIVER_HINT_PREFIX), snippet
        assert not snippet.startswith(fcc._CRASH_HINT_PREFIX), snippet

        # The declared artefact IS there — which is the whole point. A step
        # check that stopped at presence would have called this run complete.
        payload = json.loads((proj / _DECLARED_OUT).read_text())
        assert payload["verdict"] == trc.NOT_DETERMINED
        assert payload["layouts_found"] == 1
        assert payload["steps_with_evidence"] == 0
        assert len(payload["undetermined_steps"]) == payload["required_steps"]


def test_a_project_with_no_layout_is_a_flow_step_FAIL_not_a_vacuous_pass():
    """Nothing to check is not a pass, asserted through the same classifier.

    Step 37.5ic declares `phase3/stage4/gds/*.gds` as its required input. When
    that input is absent the honest answers are all non-zero; the one that must
    NOT come back is rc 2, because `_check_program_exit_zero` turns rc 2 into
    the VACUOUS_PASS tier, which is precisely "there was nothing here, carry
    on"."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        proj = _project(Path(td), with_layout=False)
        ok, snippet, row = _flow_gate(
            proj, "tapeout_readiness_check . --json " + _DECLARED_OUT)

        assert ok is False, snippet
        assert row["rc"] == 1, row
        assert row["verdict"] == "FAIL", row
        payload = json.loads((proj / _DECLARED_OUT).read_text())
        assert payload["verdict"] == trc.NOT_DETERMINED
        assert payload["layouts_found"] == 0


# ───────────────────────────────────────── the run directory and the artefact
def test_the_tools_run_directory_does_not_displace_the_declared_artefact(
        tmp_path, monkeypatch):
    """`reports/phase3/shuttle_precheck/` and `…/shuttle_precheck.json` share a
    stem, and the gate writes BOTH when it is left to its own default rundir.

    Measured on the real tool: the run root is a directory the precheck fills
    with `runs/<tag>/NN-<step>/`, while the step's declared output is a file one
    suffix away. If either default ever moved onto the other, the flow would
    read a directory as its verdict or the tool would fail to make its run root
    — and the first symptom of both is an artefact that is present and wrong."""
    proj = _project(tmp_path)
    monkeypatch.setattr(trc, "default_image_resolver", _resolves)
    monkeypatch.setattr(trc, "default_runner", _no_op_runner(rc=1))
    rc, art, payload = _run_as_the_flow_step(monkeypatch, proj)

    rundir = proj / "reports" / "phase3" / "shuttle_precheck"
    assert rundir.is_dir(), "the tool's run root was not created"
    assert art.is_file() and art != rundir
    assert payload["rundir"] == str(rundir.resolve())
    # The verdict survived being written next to its own run directory.
    assert payload["verdict"] == trc.NOT_DETERMINED
    assert rc == 1


# ──────────────────────────────────────────────── the retired path, via the CLI
def test_the_retired_shuttle_stays_selectable_from_the_flow_step_command(
        tmp_path, monkeypatch):
    """RETIRED is reachable through the same command the flow issues, and it is
    NOT_DETERMINED there too — never PASS (a fabrication) and never FAIL (the
    vendor did not refuse, the vendor stopped answering).

    Asserted at the CLI because that is where a `choices=` list can quietly drop
    an option: deleting the registry entry would make this argv a usage error,
    which is a different failure from the one the docstring promises."""
    proj = _project(tmp_path)
    # Selectable — and not by being the default.
    assert trc.DEFAULT_SHUTTLE != "efabless_open_mpw"
    rc, art, payload = _run_as_the_flow_step(
        monkeypatch, proj, "--shuttle", "efabless_open_mpw")

    assert rc == 1
    assert payload["verdict"] == trc.NOT_DETERMINED
    assert payload["shuttle_status"] == trc.RETIRED
    assert payload["shuttle"] == "efabless_open_mpw"
    # Not one ladder step is credited, and the reason names why nobody answered.
    assert payload["failed_steps"] == []
    assert len(payload["undetermined_steps"]) == payload["required_steps"]
    assert payload["steps_with_evidence"] == 0
    assert "ceased operating" in payload["reason"]


# ─────────────────────────────── the refusal, end to end, at the declared path
def test_the_counterpartys_refusal_survives_the_flow_step_path(
        tmp_path, monkeypatch):
    """The captured refusal, driven through the CLI the flow issues.

    Reproduced on the live tool against a published layout, most recently on
    2026-08-21 against the DIGEST-PINNED image: verdict FAIL, rc 1, refused at
    stage 3 of 16, 3 stages attempted, 13 that NEVER RAN. Those numbers are the
    assertion — a parser change that credited an incomplete stage, or a registry
    edit that changed the denominator, moves them."""
    proj = _project(tmp_path)
    monkeypatch.setattr(trc, "default_image_resolver", _resolves)
    monkeypatch.setattr(trc, "default_runner", _no_op_runner(rc=1))
    rc, art, payload = _run_as_the_flow_step(
        monkeypatch, proj, "--rundir", str(_REAL_REFUSAL))

    assert rc == 1
    assert payload["verdict"] == trc.FAIL
    assert payload["state"] == trc.STATE_LADDER_REFUSED
    assert payload["failed_steps"] == ["KLayout.CheckSize"]
    assert payload["required_steps"] == 16
    assert payload["steps_with_evidence"] == 3
    assert "the shuttle refused at stage 3 of 16" in payload["reason"]

    refused = next(s for s in payload["steps"] if s["verdict"] == trc.FAIL)
    assert "GUARD_RING_MK" in refused["evidence"]
    # The steps after the refusal are NOT_DETERMINED, not passed over.
    assert payload["undetermined_steps"] == [
        s["step_id"] for s in payload["steps"][3:]]


def test_a_refusal_states_the_stage_it_stopped_at_and_the_stages_that_never_ran(
        tmp_path, monkeypatch):
    """"3 of 16", not "1 failure" — and the thirteen named, not implied.

    THE DIFFERENCE THIS TEST DEFENDS. The counterparty's flow exits at its first
    refusal, so our published layout produced a verdict on stage 3 and NOTHING
    AT ALL on stages 4 through 16. A report that says `failed=1` has converted
    thirteen stages of silence into an implied all-clear — and those thirteen
    include the pad openings and the die-id cells, which this same layout also
    lacks and which the counterparty simply never got far enough to say so
    about.

    So the arithmetic is asserted, and so is the phrasing of the one line most
    readers will ever see."""
    proj = _project(tmp_path)
    rep = trc.evaluate(proj, rundir=_REAL_REFUSAL,
                       image_resolver=_resolves, runner=_no_op_runner(rc=1))

    assert rep.upstream_stages_total == 16
    assert rep.stages_attempted == 3
    assert rep.refused_at_stage == {
        "order": 3, "step_id": "KLayout.CheckSize", "label": "Check Slot Size"}
    assert len(rep.stages_never_ran) == 13
    # NEVER RAN and PASSED are different facts, carried per stage.
    ran = {s.step_id: s.ran for s in rep.steps}
    assert ran["KLayout.ReadLayout"] and ran["KLayout.CheckSize"]
    assert not ran["Checker.KLayoutDRC"]
    assert not ran["KLayout.WriteLayout"]

    line = rep.summary_line()
    assert "REFUSED at stage 3 of 16" in line
    assert "13 NEVER RAN" in line


def test_the_four_refusals_this_layout_earns_are_all_named(tmp_path):
    """One observed, three still queued behind it — and all four in the report.

    The measured gap is four refusals: the seal ring, the die size against the
    slot, the pad openings and the die-id cells. Exactly ONE of them can be
    quoted, because `check_size.py` exits on its first failing predicate and the
    flow exits with it. A report that named only what was quoted would tell a
    reader they have one problem when they have four.

    The other three are named where they honestly live: in the `refuses_on`
    clause of the stage that refused (which carries the die-size predicate
    behind the seal-ring one), and in the two stages that NEVER RAN."""
    proj = _project(tmp_path)
    rep = trc.evaluate(proj, rundir=_REAL_REFUSAL, cob=True,
                       image_resolver=_resolves, runner=_no_op_runner(rc=1))
    by_id = {s.step_id: s for s in rep.steps}

    # 1. the seal ring — QUOTED, from the counterparty's own run directory.
    seal = by_id["KLayout.CheckSize"]
    assert seal.verdict == trc.FAIL and seal.ran
    assert "GUARD_RING_MK" in seal.evidence and "seal ring" in seal.evidence

    # 2. the die size against the purchased slot — same stage, still untested,
    #    and named in that stage's clause so the reader knows it is queued.
    assert "die dimensions do not match the purchased slot" in seal.refuses_on
    assert "exits on the FIRST" in seal.refuses_on

    # 3. the pad openings, and 4. the die-id cells — stages that NEVER RAN.
    for step_id, phrase in (("KLayout.CheckPadMask", "pad opening"),
                            ("KLayout.GenerateID", "id cells")):
        st = by_id[step_id]
        assert not st.ran, step_id
        assert st.verdict == trc.NOT_DETERMINED, step_id
        assert step_id in rep.stages_never_ran, step_id
        assert phrase in st.refuses_on, step_id

    # And neither of those two has an in-tree counterpart, which is the whole
    # reason an outside party has to be the one asked.
    assert set(rep.uncovered_in_tree) == {"KLayout.CheckPadMask",
                                          "KLayout.GenerateID"}


def test_only_a_clean_ladder_earns_the_flow_step_rc_zero(tmp_path, monkeypatch):
    """The single rc-0 path: the tool ran, every ladder step it ran completed.

    The counterweight to the three above — without it every assertion in this
    section is satisfied by a gate that can only ever fail, which is not a gate
    either."""
    proj = _project(tmp_path)
    monkeypatch.setattr(trc, "default_image_resolver", _resolves)
    monkeypatch.setattr(trc, "default_runner", _no_op_runner(rc=0))
    rc, art, payload = _run_as_the_flow_step(
        monkeypatch, proj, "--rundir", str(_complete_run(tmp_path)))

    assert rc == 0, payload["reason"]
    assert payload["verdict"] == trc.PASS
    assert payload["state"] == trc.STATE_LADDER_PASSED
    assert payload["failed_steps"] == []
    assert payload["undetermined_steps"] == []
    assert payload["stages_never_ran"] == []
    assert payload["steps_with_evidence"] == payload["required_steps"] == 16


# --------------------------------------------------------------------------- #
# THE DECLINE SHAPE — borrowed from LibreLane, and where we deliberately differ
#
# MEASURED in the pinned image (librelane 3.1.0.dev1,
# /usr/local/lib/python3.12/dist-packages/librelane), not remembered.
#
# `KLayout.SealRing` is upstream's canonical unsupported-configuration decline
# (steps/klayout.py:933). It does three things and no more:
#
#     self.warn(f"KLAYOUT_SEALRING_SCRIPT is unset. KLayout.SealRing may not be "
#               f"supported for the {self.config['PDK']} PDK. This step will be "
#               f"skipped.")
#     return views_updates, {}
#
#   1. it NAMES the thing that was unsupported — the variable AND the PDK;
#   2. it says plainly that the step is being skipped;
#   3. it neither passes silently nor crashes.
#
# Two things we take, one we deliberately do not:
#
#   TAKEN — the decline must name what was unsupported. A decline that says only
#     "not supported" is a decline nobody can act on.
#   BETTER — upstream's decline is a `self.warn` into a log and an EMPTY metrics
#     dict; nothing machine-readable records that it happened. Ours is a field in
#     the artefact its own gate declares, so a decline is a datum.
#   NOT TAKEN — upstream returns normally and the flow carries on, which is right
#     for one optional step among forty. Here the decline IS the verdict: there is
#     no other party to ask, so a continue would publish "nobody refused this" for
#     a layout nobody looked at. Ours is rc 1.
#
# UPSTREAM HAS NO ANALOGUE FOR THE STEP ITSELF, and that was measured rather than
# searched for. Over the whole installed librelane tree: `precheck` 0 files,
# `shuttle` 0, `wafer_space` 0, `mpw_precheck` 0 — against a POSITIVE CONTROL on
# the same tree in which `SealRing` is 2 files, `PadRing` 2 and `KLayoutDensity`
# 2, so the search demonstrably finds what is there. The 151 `efabless` hits are
# 149 copyright headers plus a `--save-views-to` output FORMAT "compatible with
# Caravel User Project"; and `librelane/steps/*.py` contains no network client
# and no container spawn at all. Upstream can write files in the shuttle's
# expected layout. It never asks anyone whether they would be accepted.
# --------------------------------------------------------------------------- #
#: (case, the token the record MUST name, extra argv). Both of this gate's
#: decline paths, because a shape held by one of two is not a shape.
_DECLINE_CASES = (
    ("retired shuttle", "efabless_open_mpw", ("--shuttle", "efabless_open_mpw")),
    ("unreachable tool", "no.such.registry.invalid/never:never",
     ("--image", "no.such.registry.invalid/never:never")),
)


@pytest.mark.parametrize("label,must_name,extra", _DECLINE_CASES)
def test_a_decline_names_what_was_unsupported_in_its_own_record(
        label, must_name, extra, tmp_path, monkeypatch):
    """The SealRing shape, confirmed on both decline paths rather than assumed.

    `self.warn(...)` upstream names the unset variable and the PDK. The same
    obligation, discharged into the artefact instead of a log: whatever could
    not be reached is named IN the record, in prose a human reads and in fields
    a program reads, and the run is not credited."""
    proj = _project(tmp_path)
    rc, art, payload = _run_as_the_flow_step(monkeypatch, proj, *extra)

    # 1. it names the thing — in the prose, the way upstream's warn does.
    assert must_name in payload["reason"], f"[{label}] {payload['reason']}"

    # 2. and it is a DATUM, not only prose: a reader never has to parse the
    #    sentence to learn who was asked or what tool would have answered.
    for key in ("shuttle", "shuttle_status", "tool", "upstream", "verdict"):
        assert payload[key], f"[{label}] empty field {key!r}"

    # 3. the decline is not credited, on either channel.
    assert payload["verdict"] == trc.NOT_DETERMINED, label
    assert rc == 1, label
    assert payload["steps_with_evidence"] == 0, label
    assert payload["failed_steps"] == [], (
        f"[{label}] nobody refused this layout — a decline must not be dressed "
        f"as a refusal any more than as a pass")
