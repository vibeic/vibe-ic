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
import sys
import tempfile
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DIFFERENTIAL = REPO / "tools" / "gatekeeper-land-differential.sh"
LAND = REPO / "tools" / "gatekeeper-land.sh"
PLUGIN_REL = "vibe-ic-marketplace/plugins/vibe-ic"
REAL_VERDICT = REPO / PLUGIN_REL / "programs" / "landing_merge_verdict.py"

# The protected-landing-transition tuple this synthetic repository has to carry
# before `landing_merge_verdict` can be answered at all. See that module's
# docstring for why the refusal it satisfies is correct and stays.
sys.path.insert(0, str(REPO / PLUGIN_REL / "programs" / "tests"))
import _protected_transition_fixture as protected  # noqa: E402

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


#: THE AGGREGATE HYGIENE RECORD, in the shape the dispatcher really writes.
#:
#: `hygiene_finding_delta._validate_record` accepts nothing less than a
#: COMPLETE one: redundant counters that agree with the gate array, one process
#: attestation per gate that agrees with that gate's state, and a measurement
#: DAY it can parse. Anything short of that is REFUSED as unmeasurable — which
#: is correct, and which makes every differential case below refuse for the
#: record's shape instead of for the rule it is about.
_HYGIENE_RECORD = r"""# Write the one-gate aggregate hygiene record for this stub arm.
import json
import os
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path.cwd() / "vibe-ic-marketplace/plugins/vibe-ic" / "programs"))
import gate_process_attestation as attest

# THE TWO ARMS MUST AGREE ON THE DAY. `hygiene_finding_delta.delta` refuses a
# pair measured on different days, because `exemption_expired` is computed
# against it and a promise coming due is the calendar's doing rather than the
# branch's. A stub that read the clock could straddle midnight between the arms
# and turn this file's whole battery red for a reason no test is about.
TODAY = "2026-08-15"
LABEL = "stub gate"
ARGV = ["python3", "stub_gate.py", LABEL]
OUTPUT = {"PASS": "[PASS] checked\n",
          "FAIL": "[FAIL] named finding\n",
          "NOT_CHECKED": "[NOT_CHECKED] unavailable\n"}
RETURNCODE = {"PASS": 0, "FAIL": 1, "NOT_CHECKED": 2}

state = os.environ.get("ARM_HYGIENE_STATE") or "PASS"
gate = {"label": LABEL, "state": state, "seconds": 1, "corpus": None,
        "exempt_until": None, "exempt_reason": None,
        "exemption_expired": False, "scope": None}
record = {
    "shard": None, "today": TODAY, "listed_only": False,
    "declared": 1, "ran": 1,
    "decided": int(state in ("PASS", "FAIL")),
    "passed": int(state == "PASS"),
    "failed": int(state == "FAIL"),
    "not_checked": int(state == "NOT_CHECKED"),
    "wrote_corpus": int(state == "WROTE_CORPUS"),
    "deferred": 0, "other_shard": 0, "out_of_scope": 0,
    "not_checked_unexempted": [LABEL] if state == "NOT_CHECKED" else [],
    "exemptions_expired": [], "wiring_errors": [], "corpora": [],
    "gates": [gate],
    "process_attestations": [attest.process_attestation(
        LABEL, OUTPUT[state], RETURNCODE[state], ARGV, state=state)],
}
Path(sys.argv[1]).write_text(json.dumps(record), encoding="utf-8")
"""


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
        # A COMPLETE `--summary-json` record, written by the helper beside
        # this stub. `hygiene_finding_delta._validate_record` refuses anything
        # that is not one — a sketch of the shape makes every case below refuse
        # as UNMEASURABLE and prove nothing about the rule under test.
        '[ -n "${GATEKEEPER_HYGIENE_REPORT:-}" ] && python3 '
        'tools/stub_hygiene_record.py "$GATEKEEPER_HYGIENE_REPORT"\n'
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
    # `gate_process_attestation` is what the record helper below builds its
    # process attestations with — the same module the real dispatcher uses, so
    # the stub cannot attest in a dialect the validator would never see.
    for mod in ("hygiene_finding_delta.py", "_atomic_artefact.py",
                "gate_process_attestation.py"):
        shutil.copy(REPO / PLUGIN_REL / "programs" / mod, prog / mod)

    (root / "tools" / "stub_hygiene_record.py").write_text(_HYGIENE_RECORD)


@pytest.fixture()
def synthetic():
    """A repo with a base commit and one candidate commit on top of it.

    DELIBERATELY NOT under pytest's `tmp_path`, and that is measured rather
    than stylistic. `trusted_worktree_attest` reads a linked worktree's `.git`
    control file as ONE canonical ASCII line, and pytest roots its temporaries
    at `pytest-of-$USER`; in the landing image `$USER` is literally
    `'1000\ndesigner'`, so every path under `tmp_path` carries an EMBEDDED
    NEWLINE. The attester then refuses the worktree — correctly, and about the
    harness's own path rather than about the protected tuple under test.
    """
    holder = Path(tempfile.mkdtemp(prefix="gk_synthetic_repo."))
    root = holder / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    # THE HOST DOES NOT GET A VOTE ON THE BYTES. `trusted_worktree_attest`
    # compares the worktree's raw bytes against the blob, so a global
    # `core.autocrlf`/`core.eol`/attributes-file on the machine running this
    # test would make every case below refuse as UNMEASURED — about the
    # harness's own checkout filters rather than about the tuple under test.
    # Same reason this fixture is not under `tmp_path`. See
    # `_protected_transition_fixture.BYTE_TRANSFORM_OFF` for the measurement.
    protected.harden(root)
    _write_stub_tree(root)
    # THE PROTECTED TUPLE BELONGS TO THE BASE COMMIT, because the manifest is
    # BASE-owned policy: `protected_landing_transition.build_receipt` reads it
    # out of the base commit's own object database and a candidate never
    # supplies it. Without it `landing_merge_verdict` refuses every case here
    # as PROTECTED LANDING SOURCE TRANSITION IS UNMEASURED — correctly, since
    # a landing gate that cannot measure the protected tuple must not pretend
    # it did. The manifest is written after the staging pass because it
    # describes the very object ids that pass creates.
    protected.install(root)
    _git(root, "add", "-f", ".")
    protected.write_manifest(root)
    _git(root, "add", "-f", protected.MANIFEST_REL)
    _git(root, "commit", "-q", "-m", "base")
    base = _git(root, "rev-parse", "HEAD")
    (root / "candidate_marker").write_text("x\n")
    _git(root, "add", "-f", "candidate_marker")
    _git(root, "commit", "-q", "-m", "candidate")
    try:
        yield root, base
    finally:
        shutil.rmtree(holder, ignore_errors=True)


def _run(root: Path, base: str, *, cand_test="passed", base_test="passed",
         gate_line=None, a2_gate_line=None, a2_range_line=None, dwell=0.0,
         hygiene_state=None, probe: Path | None = None, extra=(),
         env_extra: dict | None = None):
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
    if env_extra:
        env.update(env_extra)
    started = time.time()
    cp = subprocess.run(
        ["bash", str(DIFFERENTIAL), "--repo", str(root), "--base", base, *extra],
        capture_output=True, text=True, env=env, cwd=str(root))
    return cp, time.time() - started


# ------------------------------------------------------------- the deadlock


def test_a_host_that_rewrites_checked_out_bytes_cannot_unmeasure_the_tuple(
        synthetic):
    """NEGATIVE CONTROL FOR THE FIXTURE, not a relaxation of the gate.

    `trusted_worktree_attest` compares the worktree's RAW BYTES against the
    blob, deliberately, so that a clean/smudge filter cannot swap the
    population out from under an attestation. A host whose GLOBAL git config
    transforms bytes on checkout therefore breaks the receipt for every case in
    this file — and the failure reads "PROTECTED LANDING SOURCE TRANSITION IS
    UNMEASURED", which says nothing about the host.

    MEASURED: eleven of this file's cases were red on a maintainer's host and
    all twenty-five green on two others (an interactive shell at git 2.55.0 and
    the pinned landing image at git 2.43.0, the second also under
    --read-only with a noexec /tmp). The whole difference was one line of
    `~/.gitconfig`, and `core.autocrlf = true` reproduces it first try.

    So this drives the real driver with exactly that hostile config exported,
    and requires the receipt to be built anyway. It FAILS against the fixture
    as it was, because `harden()` did not exist. It does not make any assertion
    tolerant of a REFUSE: the run must still pass, for the ordinary reason, and
    the receipt must still be REAL — built by the shipped builder out of the
    shipped validator.
    """
    root, base = synthetic
    # NOT under `tmp_path`, for the reason the `synthetic` fixture documents:
    # in the landing image `$USER` carries an embedded newline, and a
    # `GIT_CONFIG_GLOBAL` path with a newline in it is its own separate bug.
    hostile = root.parent / "hostile-gitconfig.ini"
    hostile.write_text("[core]\n\tautocrlf = true\n\teol = crlf\n",
                       encoding="utf-8")
    cp, _ = _run(root, base,
                 env_extra={"GIT_CONFIG_GLOBAL": str(hostile)})
    out = cp.stdout + cp.stderr
    assert "raw bytes differ from expected blob" not in out, out
    assert "PROTECTED LANDING SOURCE TRANSITION IS UNMEASURED" not in out, out
    assert "protected landing transition: STEADY" in out, out
    assert cp.returncode == 0, out


def test_a_receipt_that_cannot_be_built_is_named_and_not_merely_absent(
        synthetic):
    """The DIAGNOSABILITY half, and it is a separate property.

    When the receipt cannot be built the verdict refuses as UNMEASURED — right,
    and unchanged. But the driver used to decide that in a bare `if`, so its own
    log carried no statement that a receipt had been ATTEMPTED and refused;
    "the transition is bad" and "this host could not look at it" reached the
    reader as the same sentence. That is the one thing this repository refuses
    to let a check do.

    Driven by taking the manifest away from the base commit, so the builder
    genuinely cannot answer — no test-only flag in the shipped driver, because
    a switch that only a test throws proves the switch, not the driver.
    """
    root, base = synthetic
    _git(root, "rm", "-q", "--cached", protected.MANIFEST_REL)
    (root / protected.MANIFEST_REL).unlink()
    _git(root, "commit", "-q", "-m", "no manifest")
    unmeasurable = _git(root, "rev-parse", "HEAD")
    (root / "after_marker").write_text("y\n")
    _git(root, "add", "-f", "after_marker")
    _git(root, "commit", "-q", "-m", "candidate without a measurable base")
    cp, _ = _run(root, unmeasurable)
    out = cp.stdout + cp.stderr
    assert "protected-source transition receipt: NOT BUILT" in out, out
    # The heading alone would be satisfied by a driver that printed a heading
    # and swallowed the cause. What must survive is the BUILDER'S OWN sentence,
    # replayed under it.
    assert "[NORECORD] protected landing transition:" in out, out
    assert "PROTECTED LANDING SOURCE TRANSITION IS UNMEASURED" in out, out
    assert cp.returncode != 0, out


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
