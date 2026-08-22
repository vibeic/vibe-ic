"""ADVERSARIAL: does an UNKNOWN base arm buy the candidate leniency?

The driver claims (gatekeeper-land-differential.sh:104-109):
    "UNKNOWN NEVER BUYS LENIENCY. Every degradation in this design is toward
     STRICTER."

Every case below breaks the BASE arm's record in a different way and asks
whether a candidate that WOULD HAVE BEEN REFUSED against a healthy base is
still refused. The stub tree is the author's own, extended with knobs that
kill / corrupt / truncate the base arm's outputs. The verdict program copied
in is the REAL one.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DIFFERENTIAL = REPO / "tools" / "gatekeeper-land-differential.sh"
PLUGIN_REL = "vibe-ic-marketplace/plugins/vibe-ic"
REAL_VERDICT = REPO / PLUGIN_REL / "programs" / "landing_merge_verdict.py"
SELECTED = "programs/tests/test_subject.py"


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), check=True,
                          capture_output=True, text=True).stdout.strip()


def _junit(outcome: str, *, process=True, with_case=True) -> str:
    inner = {"failed": "<failure/>", "passed": "", "skipped": "<skipped/>"}[outcome]
    case = ('<testsuite name="aggregate::selection" tests="1">'
            '<testcase classname="pytest_aggregate.programs.tests.test_subject" '
            f'name="test_one" file="{SELECTED}">{inner}</testcase></testsuite>'
            ) if with_case else ""
    proc = ('<testsuite name="whole_selection::process_exit" tests="1">'
            '<testcase classname="pytest_aggregate_process" '
            'name="whole_selection::process_exit" file="&lt;aggregate&gt;">'
            '<properties><property name="process_rc" value="'
            + ("1" if outcome == "failed" else "0")
            + '"/></properties></testcase></testsuite>') if process else ""
    return '<?xml version="1.0"?><testsuites>' + case + proc + '</testsuites>'


def _write_stub_tree(root: Path) -> None:
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

    (prog / "ci_targeted_test_select.py").write_text(f"print({SELECTED!r})\n")

    # THE TEST ARM, with an A1 kill switch. `ARM_A1_MODE`:
    #   ok       -> write BASE_JUNIT_TEXT (healthy)
    #   nofile   -> write nothing and die (the arm was killed before its report)
    #   empty    -> write a 0-byte report
    #   corrupt  -> write unparseable bytes
    (prog / "pytest_per_file_junit.py").write_text(
        "import os, sys, pathlib\n"
        "arm = os.environ.get('GATEKEEPER_VERIFY_ARM', '?')\n"
        "junit = sys.argv[sys.argv.index('--junit') + 1]\n"
        "if arm == 'B1':\n"
        "    pathlib.Path(junit).write_text(os.environ['CAND_JUNIT_TEXT'])\n"
        "else:\n"
        "    mode = os.environ.get('ARM_A1_MODE', 'ok')\n"
        "    if mode == 'nofile':\n"
        "        print('killed'); raise SystemExit(137)\n"
        "    if mode == 'empty':\n"
        "        pathlib.Path(junit).write_text('')\n"
        "        raise SystemExit(137)\n"
        "    if mode == 'corrupt':\n"
        "        pathlib.Path(junit).write_text('<testsuites><testsuite un')\n"
        "        raise SystemExit(137)\n"
        "    pathlib.Path(junit).write_text(os.environ['BASE_JUNIT_TEXT'])\n"
        "print('=== pytest junit summary')\n"
        "print('AGGREGATE_COMPLETE rc=0')\n")

    # THE GATE ARM, with an A2 kill switch. `ARM_A2_MODE`:
    #   ok       -> full log + terminal sentinel + hygiene report
    #   silent   -> no output at all, no hygiene report (killed before it spoke)
    #   partial  -> gate lines but NO terminal sentinel, no hygiene report
    #   nohyg    -> full log, but the hygiene report was never written
    (root / "tools" / "gatekeeper-land.sh").write_text(
        "#!/usr/bin/env bash\n"
        'arm="${GATEKEEPER_VERIFY_ARM:-?}"\n'
        'mode=ok\n'
        '[ "$arm" = A2 ] && mode="${ARM_A2_MODE:-ok}"\n'
        'if [ "$mode" = silent ]; then exit 137; fi\n'
        'if [ "$mode" != nohyg ] && [ "$mode" != partial ] '
        '&& [ -n "${GATEKEEPER_HYGIENE_REPORT:-}" ]; then cat > '
        '"$GATEKEEPER_HYGIENE_REPORT" <<JSON\n'
        '{"shard": null, "today": "fixed", "listed_only": false,\n'
        ' "wiring_errors": [], "corpora": [], "exemptions_expired": [],\n'
        ' "gates": [{"label": "stub gate", "corpus": "", "state":\n'
        '   "${ARM_HYGIENE_STATE:-PASS}", "exemption_expired": false}]}\n'
        "JSON\n"
        "fi\n"
        "echo '=== gatekeeper landing gates — base=stub ==='\n"
        'if [ "$arm" = A2 ]; then\n'
        '  echo "  ${ARM_A2_RANGE_LINE:-SKIP  range is empty — nothing new to land}"\n'
        '  echo "  ${ARM_A2_GATE_LINE:-PASS  repo tools tests (3 file(s))}"\n'
        "else\n"
        "  echo '  SKIP  range is empty — nothing new to land'\n"
        '  echo "  ${ARM_B2_GATE_LINE:-PASS  repo tools tests (3 file(s))}"\n'
        "fi\n"
        "echo '  PASS  worktree carries no uncommitted change'\n"
        'if [ "$mode" = partial ]; then exit 137; fi\n'
        "if [ -n \"${ARM_GATE_FAIL:-}\" ] && [ \"$arm\" != A2 ]; then\n"
        "  echo '=== FAILURES ABOVE — stamp removed; the pre-push hook will refuse ==='\n"
        "  exit 1\n"
        "fi\n"
        "if [ -n \"${ARM_A2_FAIL:-}\" ] && [ \"$arm\" = A2 ]; then\n"
        "  echo '=== FAILURES ABOVE — stamp removed; the pre-push hook will refuse ==='\n"
        "  exit 1\n"
        "fi\n"
        "echo '=== ALL NON-TARGET GATES COMPLETE — stamp withheld for composite verdict ==='\n"
        "exit 0\n")

    (prog / "tests").mkdir(exist_ok=True)
    (prog / "tests" / "test_subject.py").write_text("def test_one():\n    pass\n")
    shutil.copy(REAL_VERDICT, prog / "landing_merge_verdict.py")
    for mod in ("hygiene_finding_delta.py", "_atomic_artefact.py"):
        shutil.copy(REPO / PLUGIN_REL / "programs" / mod, prog / mod)


@pytest.fixture()
def synthetic(tmp_path):
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


def _run(root: Path, base: str, *, cand_junit=None, base_junit=None,
         a1_mode="ok", a2_mode="ok", gate_line=None, a2_gate_line=None,
         a2_fail=False, hygiene_state=None, extra=()):
    env = dict(os.environ)
    env["CAND_JUNIT_TEXT"] = cand_junit if cand_junit is not None else _junit("passed")
    env["BASE_JUNIT_TEXT"] = base_junit if base_junit is not None else _junit("passed")
    env["ARM_A1_MODE"] = a1_mode
    env["ARM_A2_MODE"] = a2_mode
    if gate_line:
        env["ARM_B2_GATE_LINE"] = gate_line
        if gate_line.startswith("FAIL"):
            env["ARM_GATE_FAIL"] = "1"
    if a2_gate_line:
        env["ARM_A2_GATE_LINE"] = a2_gate_line
    if a2_fail:
        env["ARM_A2_FAIL"] = "1"
    if hygiene_state:
        env["ARM_HYGIENE_STATE"] = hygiene_state
    cp = subprocess.run(
        ["bash", str(DIFFERENTIAL), "--repo", str(root), "--base", base, *extra],
        capture_output=True, text=True, env=env, cwd=str(root))
    stamp = Path(_git(root, "rev-parse", "--absolute-git-dir")) / "gatekeeper-stamp"
    return cp, stamp


# ---------------------------------------------------------------- CONTROLS
# Every refusal below must be paired with the run that PASSES, or "it refused"
# proves nothing about the input under test.


def test_control_healthy_base_and_clean_candidate_lands(synthetic):
    root, base = synthetic
    cp, stamp = _run(root, base)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert stamp.exists()


def test_control_silencing_is_refused_against_a_healthy_base(synthetic):
    """The probe that every UNKNOWN case below must keep firing."""
    root, base = synthetic
    cp, stamp = _run(root, base, base_junit=_junit("failed"),
                     cand_junit=_junit("skipped"))
    assert cp.returncode == 1, cp.stdout
    assert "SILENCED RATHER THAN FIXED" in cp.stdout
    assert not stamp.exists()


# ------------------------------------- A1: the base test arm produced nothing


@pytest.mark.parametrize("mode", ["nofile", "empty", "corrupt"])
def test_a1_without_a_record_refuses_a_silencing_candidate(synthetic, mode):
    """THE LENS. Against a healthy base this candidate is REFUSED for silencing
    a red test. If killing / emptying / corrupting the base report turns that
    into a pass, unknown bought leniency."""
    root, base = synthetic
    cp, stamp = _run(root, base, a1_mode=mode, cand_junit=_junit("skipped"))
    assert cp.returncode != 0, (
        f"A1 mode={mode}: a broken base report LANDED a candidate that "
        f"silences a test\n{cp.stdout}")
    assert not stamp.exists(), f"A1 mode={mode}: stamp written on a broken base"


@pytest.mark.parametrize("mode", ["nofile", "empty", "corrupt"])
def test_a1_without_a_record_refuses_a_clean_candidate_too(synthetic, mode):
    """Even a GREEN candidate must not land on an unmeasured base: `silenced`
    and `weakened` are read off the base's red set, so an unmeasured base is a
    set of failures the branch may delete for free."""
    root, base = synthetic
    cp, stamp = _run(root, base, a1_mode=mode)
    assert cp.returncode != 0, f"A1 mode={mode} landed on no base record\n{cp.stdout}"
    assert not stamp.exists()


def test_a1_truncated_report_is_refused(synthetic):
    """The base arm answered for the process but not for the selected file."""
    root, base = synthetic
    cp, stamp = _run(root, base, base_junit=_junit("passed", with_case=False),
                     cand_junit=_junit("skipped"))
    assert cp.returncode != 0, cp.stdout
    assert "PRODUCED NO TEST CASE ON THE BASE" in cp.stdout
    assert not stamp.exists()


def test_a1_norecord_aggregate_is_refused(synthetic):
    """The per-file suites survived, the aggregate session record did not."""
    root, base = synthetic
    cp, stamp = _run(root, base, base_junit=_junit("failed", process=False),
                     cand_junit=_junit("skipped"))
    assert cp.returncode != 0, cp.stdout
    assert not stamp.exists()


# --------------------------------- A2: the base gate arm produced no record


@pytest.mark.parametrize("mode", ["silent", "partial"])
def test_a2_without_a_record_still_refuses_a_candidate_gate_failure(
        synthetic, mode):
    """A gate red on the candidate may only be excused by a base gate log that
    exists AND reached its end."""
    root, base = synthetic
    cp, stamp = _run(root, base, a2_mode=mode,
                     gate_line="FAIL  repo tools tests (3 file(s))")
    assert cp.returncode != 0, f"A2 mode={mode}\n{cp.stdout}"
    assert not stamp.exists()


@pytest.mark.parametrize("mode", ["silent", "partial", "nohyg"])
def test_a2_without_a_hygiene_record_still_refuses_a_hygiene_failure(
        synthetic, mode):
    """The hygiene tier must go ABSOLUTE when it cannot be differenced."""
    root, base = synthetic
    cp, stamp = _run(root, base, a2_mode=mode,
                     gate_line="FAIL  repo hygiene gates",
                     a2_gate_line="FAIL  repo hygiene gates", a2_fail=True)
    assert cp.returncode != 0, f"A2 mode={mode}\n{cp.stdout}"
    assert not stamp.exists()


def test_control_a_hygiene_failure_red_on_both_arms_lands_when_differenced(
        synthetic):
    """The paired control for the three above: with BOTH hygiene records
    present the tier is differenced and an inherited hygiene failure lands."""
    root, base = synthetic
    cp, stamp = _run(root, base, gate_line="FAIL  repo hygiene gates",
                     a2_gate_line="FAIL  repo hygiene gates", a2_fail=True)
    assert cp.returncode == 0, cp.stdout
    assert stamp.exists()


# ------------------------------------------- the base-evidence consumption


def test_a_stripped_same_host_bundle_is_refused(synthetic, tmp_path):
    """`--base-evidence` copies every artefact with `2>/dev/null` and checks
    none of them. A bundle carrying only `base_sha` and this host's name leaves
    the base junit, the base gate log, the base hygiene record AND the base
    selection all absent — and `base_selection_supplied` is what arms every
    base-side completeness refusal."""
    root, base = synthetic
    out = tmp_path / "stripped"
    out.mkdir()
    (out / "base_sha").write_text(base + "\n")
    (out / "host").write_text(subprocess.run(
        ["uname", "-n"], capture_output=True, text=True).stdout)
    cp, stamp = _run(root, base, cand_junit=_junit("skipped"),
                     extra=("--base-evidence", str(out)))
    assert cp.returncode != 0, (
        "a bundle with NO base evidence in it landed a candidate that silences "
        "a test\n" + cp.stdout)
    assert not stamp.exists()


def test_a_bundle_without_a_base_selection_still_checks_completeness(
        synthetic, tmp_path):
    """A bundle that carries a TRUNCATED base junit but no `selection_base.txt`
    disarms the completeness check, and the truncated base is then subtracted
    as though whole (vibe-ic#1443's own defect)."""
    root, base = synthetic
    out = tmp_path / "nosel"
    _run(root, base, base_junit=_junit("failed"),
         extra=("--base-arm-only", str(out)))
    (out / "selection_base.txt").unlink()
    # The base report now says nothing about the selected file.
    (out / "base.xml").write_text(_junit("passed", with_case=False))
    cp, stamp = _run(root, base, cand_junit=_junit("skipped"),
                     extra=("--base-evidence", str(out)))
    assert cp.returncode != 0, (
        "a truncated base report with no base selection was subtracted as "
        "though whole\n" + cp.stdout)
    assert not stamp.exists()
