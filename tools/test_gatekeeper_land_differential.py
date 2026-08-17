"""`tools/gatekeeper-land-differential.sh` — the direct-push landing gate.

WHAT THIS FILE IS FOR
=====================
The differential is the thing standing between `main` and a deadlock, and it is
ALSO the thing standing between `main` and a gate that accepts everything. Both
failure modes look like a green run from the outside, so every behavioural test
below is a PAIR: the same synthetic repo, one input changed, opposite verdicts.

  "A fallback that passed everything would be worse than a gate that refused
   everything."  — landing_merge_verdict.py, module docstring

The repository under test is SYNTHETIC and tiny, with stub arms, because the
real arms are ~31 minutes each. What the stubs must not be allowed to fake is
the DECISION: the verdict program copied in is the REAL
`landing_merge_verdict.py`, so the decision table these tests exercise is the
shipped one and not a re-implementation.

chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process node.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DIFFERENTIAL = REPO / "tools" / "gatekeeper-land-differential.sh"
LAND = REPO / "tools" / "gatekeeper-land.sh"
PLUGIN_REL = "vibe-ic-marketplace/plugins/vibe-ic"
REAL_VERDICT = REPO / PLUGIN_REL / "programs" / "landing_merge_verdict.py"

SELECTED = "programs/tests/test_subject.py"


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), check=True,
                          capture_output=True, text=True).stdout.strip()


def _junit_stub(outcome: str) -> str:
    """The driver's aggregate report shape, as `pytest_per_file_junit` writes it."""
    inner = {"failed": "<failure/>", "passed": "", "skipped": "<skipped/>"}[outcome]
    return (
        '<?xml version="1.0"?><testsuites>'
        '<testsuite name="aggregate::selection" tests="1">'
        '<testcase classname="pytest_aggregate.programs.tests.test_subject" '
        f'name="test_one" file="{SELECTED}">{inner}</testcase></testsuite>'
        '<testsuite name="whole_selection::process_exit" tests="1">'
        '<testcase classname="pytest_aggregate_process" '
        'name="whole_selection::process_exit" file="&lt;aggregate&gt;">'
        '<properties><property name="process_rc" value="'
        + ("1" if outcome == "failed" else "0")
        + '"/></properties></testcase></testsuite></testsuites>')


def _write_stub_tree(root: Path) -> None:
    """The files the differential actually invokes, and nothing else.

    EVERY behaviour these stubs have is chosen at RUN TIME from the
    environment, never baked into the file. Two reasons, both load-bearing:
    the base commit and the candidate commit must be able to carry the SAME
    stub (a differential over stubs that differ by construction proves
    nothing), and rewriting a file after the commit would make the pushing
    worktree dirty — which the driver correctly refuses before any arm runs.
    """
    prog = root / PLUGIN_REL / "programs"
    prog.mkdir(parents=True, exist_ok=True)
    (root / "tools").mkdir(parents=True, exist_ok=True)

    (prog / "landing_worktree_is_clean_check.py").write_text(
        "import subprocess, sys\n"
        "out = subprocess.run(['git','-C',sys.argv[1],'status','--porcelain',\n"
        "                      '--untracked-files=no'],\n"
        "                     capture_output=True, text=True).stdout\n"
        "print(out)\n"
        "raise SystemExit(1 if out.strip() else 0)\n")

    (prog / "ci_targeted_test_select.py").write_text(
        f"print({SELECTED!r})\n")

    # The test arm. It records WHEN it ran, so concurrency is MEASURED rather
    # than assumed, and writes the junit the real driver would write.
    (prog / "pytest_per_file_junit.py").write_text(
        "import os, sys, time, pathlib\n"
        "arm = os.environ.get('GATEKEEPER_VERIFY_ARM', '?')\n"
        "junit = sys.argv[sys.argv.index('--junit') + 1]\n"
        "probe = os.environ.get('ARM_PROBE_DIR')\n"
        "start = time.time()\n"
        "time.sleep(float(os.environ.get('ARM_DWELL', '0')))\n"
        "if probe:\n"
        "    pathlib.Path(probe, arm).write_text(f'{start} {time.time()}\\n')\n"
        "pathlib.Path(junit).write_text(\n"
        "    os.environ['CAND_JUNIT_TEXT'] if arm == 'B1'\n"
        "    else os.environ['BASE_JUNIT_TEXT'])\n"
        "print('=== pytest junit summary')\n"
        "print('AGGREGATE_COMPLETE rc=0')\n")

    # The gate arm. It is named `gatekeeper-land.sh` because that is exactly
    # what the differential invokes inside each worktree.
    (root / "tools" / "gatekeeper-land.sh").write_text(
        "#!/usr/bin/env bash\n"
        'arm="${GATEKEEPER_VERIFY_ARM:-?}"\n'
        "start=$(date +%s.%N)\n"
        'sleep "${ARM_DWELL:-0}"\n'
        '[ -n "${ARM_PROBE_DIR:-}" ] && printf \'%s %s\\n\' "$start" '
        '"$(date +%s.%N)" > "$ARM_PROBE_DIR/$arm"\n'
        # A MINIMAL BUT VALID `--summary-json` record. `hygiene_finding_delta`
        # refuses anything that is not one, so a `{}` here would make every
        # case below refuse as UNMEASURABLE and prove nothing about the rule
        # under test. `${ARM_HYGIENE_FINDING}` lets a test introduce one.
        '[ -n "${GATEKEEPER_HYGIENE_REPORT:-}" ] && cat > '
        '"$GATEKEEPER_HYGIENE_REPORT" <<JSON\n'
        '{"shard": null, "today": "fixed", "listed_only": false,\n'
        ' "wiring_errors": [], "corpora": [], "exemptions_expired": [],\n'
        ' "gates": [{"label": "stub gate", "corpus": "", "state":\n'
        '   "${ARM_HYGIENE_STATE:-PASS}", "exemption_expired": false}]}\n'
        "JSON\n" 
        "echo '=== gatekeeper landing gates — base=stub ==='\n"
        'if [ "$arm" = A2 ]; then\n'
        '  echo "  ${ARM_A2_RANGE_LINE:-SKIP  range is empty — nothing new to land}"\n'
        '  echo "  ${ARM_A2_GATE_LINE:-PASS  repo tools tests (3 file(s))}"\n'
        "else\n"
        "  echo '  SKIP  range is empty — nothing new to land'\n"
        '  echo "  ${ARM_B2_GATE_LINE:-PASS  repo tools tests (3 file(s))}"\n'
        "fi\n"
        "echo '  PASS  worktree carries no uncommitted change'\n"
        # THE TERMINAL SENTINEL IS PART OF THE EVIDENCE, not decoration: the
        # verdict refuses a gate arm that printed lines but never proved it
        # reached its normal end ("its silence is not a pass"). The stub
        # therefore emits the same two terminals the real script does, chosen
        # the same way.
        "if [ -n \"${ARM_GATE_FAIL:-}\" ]; then\n"
        "  echo '=== FAILURES ABOVE — stamp removed; the pre-push hook will refuse ==='\n"
        "  exit 1\n"
        "fi\n"
        "echo '=== ALL NON-TARGET GATES COMPLETE — stamp withheld for composite verdict ==='\n"
        "exit 0\n")

    # THE SELECTED FILE MUST EXIST AT THE BASE TOO, or the base selection is
    # empty and arm A1 is never launched — which the verdict then correctly
    # degrades to "demand green". A fixture that hit that path would be testing
    # the degradation, not the differential.
    (prog / "tests").mkdir(exist_ok=True)
    (prog / "tests" / "test_subject.py").write_text("def test_one():\n    pass\n")
    shutil.copy(REAL_VERDICT, prog / "landing_merge_verdict.py")
    # `landing_merge_verdict` imports the finding differential from beside
    # itself; without it the hygiene tier is UNMEASURABLE and every case below
    # would refuse for that reason instead of the one it is about.
    for mod in ("hygiene_finding_delta.py", "_atomic_artefact.py"):
        shutil.copy(REPO / PLUGIN_REL / "programs" / mod, prog / mod)


@pytest.fixture()
def synthetic(tmp_path):
    """A repo with a base commit and one candidate commit on top of it."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    _write_stub_tree(root)
    _git(root, "add", "-f", ".")
    _git(root, "commit", "-q", "-m", "base")
    base = _git(root, "rev-parse", "HEAD")
    (root / "candidate_marker").write_text("x\n")
    _git(root, "add", "-f", "candidate_marker")
    _git(root, "commit", "-q", "-m", "candidate")
    return root, base


def _run(root: Path, base: str, *, cand_test="passed", base_test="passed",
         gate_line=None, a2_gate_line=None, a2_range_line=None, dwell=0.0,
         hygiene_state=None, probe: Path | None = None, extra=()):
    env = dict(os.environ)
    env["BASE_JUNIT_TEXT"] = _junit_stub(base_test)
    env["CAND_JUNIT_TEXT"] = _junit_stub(cand_test)
    env["ARM_DWELL"] = str(dwell)
    if gate_line:
        env["ARM_B2_GATE_LINE"] = gate_line
        if gate_line.startswith("FAIL"):
            env["ARM_GATE_FAIL"] = "1"
    if a2_gate_line:
        env["ARM_A2_GATE_LINE"] = a2_gate_line
    if a2_range_line:
        env["ARM_A2_RANGE_LINE"] = a2_range_line
    if hygiene_state:
        env["ARM_HYGIENE_STATE"] = hygiene_state
    if probe:
        probe.mkdir(exist_ok=True)
        env["ARM_PROBE_DIR"] = str(probe)
    started = time.time()
    cp = subprocess.run(
        ["bash", str(DIFFERENTIAL), "--repo", str(root), "--base", base, *extra],
        capture_output=True, text=True, env=env, cwd=str(root))
    return cp, time.time() - started


# ------------------------------------------------------------- the deadlock


def test_a_failure_the_base_also_has_lands_and_is_named_as_inherited(synthetic):
    """THE WHOLE POINT. Red on both arms is not this push's regression — and it
    is still PRINTED, because silence is how a permanent red becomes
    invisible."""
    root, base = synthetic
    cp, _ = _run(root, base, cand_test="failed", base_test="failed")
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "INHERITED  test   pytest_aggregate.programs.tests.test_subject::test_one" \
        in cp.stdout
    assert "SUBSET-CLEAN AGAINST" in cp.stdout
    assert "subset-clean, NOT green" in cp.stdout


def test_a_gate_red_on_the_base_is_named_as_inherited_too(synthetic):
    """The gate tier, not only the test tier."""
    root, base = synthetic
    # Red on the candidate and GREEN on the base: the branch's, and refused.
    cp, _ = _run(root, base, gate_line="FAIL  repo tools tests (3 file(s))")
    assert cp.returncode == 1
    assert "LANDING GATE FAILED, AND PASSED ON THE BASE" in cp.stdout
    # Red on BOTH: inherited, named, and landable.
    cp, _ = _run(root, base, gate_line="FAIL  repo tools tests (3 file(s))",
                 a2_gate_line="FAIL  repo tools tests (3 file(s))")
    assert cp.returncode == 0, cp.stdout
    assert "INHERITED  gate   repo tools tests (3 file(s))" in cp.stdout


# --------------------------------------------------- the negative controls


def test_a_failure_the_base_does_not_have_is_still_refused(synthetic):
    """THE TRAP. Unlocking `main` by accepting more is not the job."""
    root, base = synthetic
    cp, _ = _run(root, base, cand_test="failed", base_test="passed")
    assert cp.returncode == 1
    assert "NEW FAILURE(S) THIS BRANCH OWNS" in cp.stdout
    assert "SUBSET-CLEAN" not in cp.stdout


def test_silencing_an_inherited_failure_is_still_refused(synthetic):
    root, base = synthetic
    cp, _ = _run(root, base, cand_test="skipped", base_test="failed")
    assert cp.returncode == 1
    assert "SILENCED RATHER THAN FIXED" in cp.stdout


def test_a_refusal_removes_the_stamp_and_a_pass_writes_it(synthetic):
    root, base = synthetic
    head = _git(root, "rev-parse", "HEAD")
    stamp = Path(_git(root, "rev-parse", "--absolute-git-dir")) / "gatekeeper-stamp"
    stamp.write_text("stale\n")

    cp, _ = _run(root, base, cand_test="failed", base_test="passed")
    assert cp.returncode == 1
    assert not stamp.exists(), "a refusal must not leave a stamp behind"

    cp, _ = _run(root, base, cand_test="failed", base_test="failed")
    assert cp.returncode == 0, cp.stdout
    lines = stamp.read_text().splitlines()
    # LINE 1 IS THE COMMIT AND ONLY THE COMMIT, so an older `pre-push` that
    # reads the whole file refuses rather than accepting a stamp it cannot
    # interpret. The base travels on its own line.
    assert lines[0] == head
    assert f"base={base}" in lines
    assert "tier=direct-push" in lines


def test_no_stamp_is_written_with_no_stamp(synthetic):
    root, base = synthetic
    stamp = Path(_git(root, "rev-parse", "--absolute-git-dir")) / "gatekeeper-stamp"
    cp, _ = _run(root, base, extra=("--no-stamp",))
    assert cp.returncode == 0, cp.stdout
    assert not stamp.exists()


# ---------------------------------------------------------- absolute checks


def test_a_dirty_pushing_worktree_refuses_before_any_arm_runs(synthetic):
    """ABSOLUTE, and it has no base-side analogue: the arms measure COMMITS in
    throwaway checkouts, so the operator's own tree is asked about here or
    nowhere."""
    root, base = synthetic
    (root / "candidate_marker").write_text("edited\n")
    cp, _ = _run(root, base)
    assert cp.returncode == 1
    assert "the pushing worktree carries uncommitted change" in cp.stdout
    assert "arms launched" not in cp.stdout, "it must refuse BEFORE paying for arms"


def test_a_head_that_does_not_descend_from_the_base_is_refused(synthetic):
    root, base = synthetic
    candidate = _git(root, "rev-parse", "HEAD")
    _git(root, "checkout", "-q", "--detach", base)
    _git(root, "commit", "-q", "--allow-empty", "-m", "divergent")
    other = _git(root, "rev-parse", "HEAD")
    _git(root, "checkout", "-q", "--detach", candidate)
    cp = subprocess.run(
        ["bash", str(DIFFERENTIAL), "--repo", str(root), "--base", other],
        capture_output=True, text=True, cwd=str(root))
    assert cp.returncode == 2
    assert "does not descend" in cp.stdout + cp.stderr


def test_a_range_scoped_gate_that_fails_on_the_empty_base_range_refuses(synthetic):
    """THE LAUNDERING HOLE, checked rather than asserted.

    `gatekeeper-land.sh:202-208`: a range-scoped gate asked over `X..X` sees
    ZERO commits. If it answers FAIL instead of SKIP it enters the base's
    failing set and is excused on EVERY candidate thereafter — including a real
    NDA or collateral-revert violation. So the base arm's own log is inspected
    for exactly that, every run.
    """
    root, base = synthetic
    cp, _ = _run(root, base, a2_range_line="FAIL  NDA — commit messages")
    assert cp.returncode == 1, cp.stdout
    assert "A RANGE-SCOPED GATE FAILED ON THE EMPTY BASE RANGE" in cp.stdout


def test_the_same_gate_passing_on_the_empty_base_range_does_not_refuse(synthetic):
    """The paired control: the check must be able to NOT fire, or it says
    nothing when it does."""
    root, base = synthetic
    cp, _ = _run(root, base)
    assert cp.returncode == 0, cp.stdout
    assert "A RANGE-SCOPED GATE FAILED" not in cp.stdout


# ------------------------------------------------------------- concurrency


def test_the_four_arms_overlap_in_time(synthetic, tmp_path):
    """Two arms is two ~31-minute runs. Serialised, that is an hour, and an
    hour-long gate is a bypassed gate. Measured from the arms' own clocks, not
    from the script's structure."""
    root, base = synthetic
    probe = tmp_path / "probe"
    cp, elapsed = _run(root, base, dwell=3.0, probe=probe)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    spans = {}
    for name in ("A1", "A2", "B1", "B2"):
        s, e = (probe / name).read_text().split()
        spans[name] = (float(s), float(e))
    latest_start = max(s for s, _ in spans.values())
    earliest_end = min(e for _, e in spans.values())
    assert earliest_end > latest_start, (
        f"the arms did not overlap: {spans}")
    # Four 3-second arms serialised would be >= 12s; overlapped they are ~3.
    assert elapsed < 10, f"the arms look serialised ({elapsed:.1f}s)"


def test_base_arm_only_publishes_a_bundle_and_skips_the_candidate_arms(
        synthetic, tmp_path):
    """The two-host split: the base arm can be measured on a second machine
    while this one measures the candidate."""
    root, base = synthetic
    out = tmp_path / "evidence"
    probe = tmp_path / "probe2"
    cp, _ = _run(root, base, dwell=0.2, probe=probe,
                 extra=("--base-arm-only", str(out)))
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert (out / "base_sha").read_text().strip() == base
    assert (out / "host").read_text().strip()
    assert (out / "base.xml").exists() and (out / "base_land.log").exists()
    assert not (probe / "B1").exists() and not (probe / "B2").exists(), \
        "--base-arm-only must not pay for the candidate arms"


def test_base_evidence_for_another_base_is_refused(synthetic, tmp_path):
    root, base = synthetic
    out = tmp_path / "evidence"
    out.mkdir()
    (out / "base_sha").write_text("f" * 40 + "\n")
    cp, _ = _run(root, base, extra=("--base-evidence", str(out)))
    assert cp.returncode == 2
    assert "the base evidence is for" in cp.stdout + cp.stderr


def test_a_cross_host_base_bundle_is_never_subtracted(tmp_path, synthetic):
    """A RED BASELINE IS NOT PORTABLE — measured, not assumed.

    Same base commit, same 90-file selection, same driver, 2026-08-18:
    8HD-8 reported 2176 test ids and 6 red; 8HD-4 reported 2118 and 9. Three of
    the extra reds are an environment-dependent family and 58 ids did not exist
    on the second host at all. Subtracting that baseline from a candidate
    measured here would excuse three failures this host calls NEW — the
    laundering direction. So a foreign bundle degrades the run to DEMAND GREEN
    and the hygiene tier to ABSOLUTE, and excuses nothing.
    """
    root, base = synthetic
    out = tmp_path / "evidence"
    # A bundle whose base arm was red in BOTH tiers. On this host that would
    # excuse the same reds on the candidate; from another host it must not.
    _run(root, base, base_test="failed", a2_gate_line="FAIL  repo hygiene gates",
         extra=("--base-arm-only", str(out)))
    (out / "host").write_text("some-other-host\n")

    cp, _ = _run(root, base, cand_test="failed",
                 gate_line="FAIL  repo hygiene gates",
                 extra=("--base-evidence", str(out)))
    assert cp.returncode == 1, cp.stdout
    assert "A RED BASELINE IS NOT PORTABLE" in cp.stdout
    # The test tier degraded to demand green rather than subtracting.
    assert "NEW FAILURE(S) THIS BRANCH OWNS" in cp.stdout
    # The hygiene tier went absolute rather than falling back to per-label.
    assert "THE HYGIENE TIER FAILED AND COULD NOT BE DIFFERENCED" in cp.stdout
    # And the foreign evidence is still SHOWN, because a cross-check a reader
    # cannot see is not a cross-check.
    assert "foreign-base-FAIL" in cp.stdout


def test_a_same_host_bundle_is_subtracted(tmp_path, synthetic):
    """The paired control. Without it the test above would pass on a driver
    that simply ignored `--base-evidence` entirely."""
    root, base = synthetic
    out = tmp_path / "evidence"
    _run(root, base, base_test="failed", extra=("--base-arm-only", str(out)))
    cp, _ = _run(root, base, cand_test="failed",
                 extra=("--base-evidence", str(out)))
    assert cp.returncode == 0, cp.stdout
    assert "INHERITED  test" in cp.stdout


# ---------------------------------------------- the arms' declared contract
# Structural, and deliberately so: these are the settings whose loss would not
# make any test above fail, but would silently change what the differential
# measures.


def _driver_text():
    return DIFFERENTIAL.read_text()


def test_neither_test_arm_is_ever_truncated():
    """`gatekeeper-verify-merge.sh:737-738` — arm A must produce the COMPLETE
    pre-existing failed set, and a truncated base makes a new failure look
    pre-existing. The mirror is the fatal one: `silenced` is read off what was
    RED on the base, so an unmeasured base failure is one the branch may delete
    for free."""
    code = "\n".join(l for l in _driver_text().splitlines()
                     if not l.lstrip().startswith("#"))
    assert "--stop-after-failures 0" in code
    assert "--maxfail" not in code, \
        "a --maxfail in this driver's CODE truncates an arm"


def test_the_base_gate_arm_forces_an_empty_range():
    """That is what makes the range-scoped gates SKIP, which is what makes them
    ABSOLUTE."""
    text = _driver_text()
    assert re.search(r"GATEKEEPER_VERIFY_ARM=A2 GATEKEEPER_BASE=", text)


def test_the_candidate_arm_does_not_defer_the_version_gate():
    """`GATEKEEPER_VERSION_BY_GATEKEEPER` is the authoring-PR deferral. On the
    PUSH path the bump is the pusher's, and version monotonicity is one of the
    absolute-by-nature checks a differential must not launder."""
    text = _driver_text()
    b2 = text[text.index("GATEKEEPER_VERIFY_ARM=B2"):]
    b2 = b2[:b2.index("gatekeeper-land.sh")]
    assert "GATEKEEPER_VERSION_BY_GATEKEEPER" not in b2


def test_both_land_arms_withhold_the_stamp():
    """Only the composite verdict may stamp; an arm that stamped would
    authorise a push on half the evidence."""
    text = _driver_text()
    assert text.count("GATEKEEPER_NO_STAMP=1") == 2


def test_land_sh_offers_the_differential_and_says_which_question_it_asked():
    """A gate that refuses must name the question it answered, or the operator
    re-runs the same absolute round forever."""
    land = LAND.read_text()
    assert "--differential" in land
    assert "gatekeeper-land-differential.sh" in land
    assert "judged ABSOLUTELY" in land


# ---------------------------------------------- the hook that reads the stamp
# The stamp gained lines. `pre-push` is the only reader, and getting this wrong
# in either direction is a landing bug: too strict and nothing lands, too loose
# and a stale verdict authorises a push. Both directions are exercised against
# the REAL hook, in a synthetic repo whose gate programs are stubs — the stamp
# block is what is under test, not the eight gates ahead of it.

HOOK = REPO / "tools" / "git-hooks" / "pre-push"
_HOOK_PROGRAMS = (
    "agent_checkin_scope_guard.py", "commit_msg_nda_check.py",
    "git_prohibition_guard.py", "landing_collateral_revert_check.py",
    "marketplace_version_sync_check.py", "nda_diff_scan_check.py",
    "plugin_full_audit.py", "version_bump_monotonic_check.py",
)


@pytest.fixture()
def hook_repo(tmp_path):
    root = tmp_path / "hookrepo"
    prog = root / PLUGIN_REL / "programs"
    prog.mkdir(parents=True)
    for name in _HOOK_PROGRAMS:
        (prog / name).write_text("raise SystemExit(0)\n")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-f", ".")
    _git(root, "commit", "-q", "-m", "base")
    base = _git(root, "rev-parse", "HEAD")
    (root / "later").write_text("x\n")
    _git(root, "add", "-f", "later")
    _git(root, "commit", "-q", "-m", "head")
    head = _git(root, "rev-parse", "HEAD")
    stamp = Path(_git(root, "rev-parse", "--absolute-git-dir")) / "gatekeeper-stamp"
    return root, base, head, stamp


def _push(root: Path, head: str, remote_sha: str):
    """Exactly the stdin git feeds `pre-push` for `git push origin main`."""
    return subprocess.run(
        ["bash", str(HOOK), "origin", "git@example.invalid:x/y.git"],
        input=f"refs/heads/main {head} refs/heads/main {remote_sha}\n",
        capture_output=True, text=True, cwd=str(root))


def test_the_hook_accepts_the_old_single_line_stamp_unchanged(hook_repo):
    """The absolute tier still writes one line and claims nothing about a base;
    a repair for the differential must not break the path that already worked."""
    root, base, head, stamp = hook_repo
    stamp.write_text(head + "\n")
    cp = _push(root, head, base)
    assert cp.returncode == 0, cp.stdout + cp.stderr


def test_the_hook_accepts_a_pair_stamp_whose_base_is_still_the_remote_tip(hook_repo):
    root, base, head, stamp = hook_repo
    stamp.write_text(f"{head}\nbase={base}\ntier=direct-push\n")
    cp = _push(root, head, base)
    assert cp.returncode == 0, cp.stdout + cp.stderr


def test_the_hook_refuses_a_pair_stamp_whose_base_has_moved(hook_repo):
    """THE STALENESS HOLE the single-SHA stamp could not express. A differential
    verdict is about a (base, candidate) PAIR: if `main` moved in between, "this
    breaks nothing new" was decided about a tree nobody is about to create."""
    root, base, head, stamp = hook_repo
    # SOMEBODY ELSE LANDED. The remote tip is a real commit off the same base
    # and not in this branch's history, which is exactly the shape a concurrent
    # landing produces — and it must be a REAL object: `pre-push` computes its
    # range with `git rev-list --count ... || echo 0` and treats an
    # UNRESOLVABLE range as "nothing to push", skipping every gate including
    # the stamp block. A fake sha would make this test pass for the wrong
    # reason and assert nothing.
    _git(root, "checkout", "-q", "--detach", base)
    _git(root, "commit", "-q", "--allow-empty", "-m", "somebody else landed")
    moved = _git(root, "rev-parse", "HEAD")
    _git(root, "checkout", "-q", "--detach", head)
    stamp.write_text(f"{head}\nbase={base}\ntier=direct-push\n")
    cp = _push(root, head, moved)
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "measured against a base that has moved" in cp.stderr


def test_the_hook_still_refuses_a_stamp_for_another_commit(hook_repo):
    root, base, head, stamp = hook_repo
    stamp.write_text(f"{base}\nbase={base}\n")
    cp = _push(root, head, base)
    assert cp.returncode == 1
    assert "stamp is for a different commit" in cp.stderr


def test_the_hook_still_refuses_when_there_is_no_stamp(hook_repo):
    root, base, head, stamp = hook_repo
    assert not stamp.exists()
    cp = _push(root, head, base)
    assert cp.returncode == 1
    assert "the full suites have not been run" in cp.stderr
