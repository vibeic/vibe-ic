"""The DIRECT-PUSH tier of ``landing_merge_verdict`` (the landing gate's judge).

WHY THIS FILE EXISTS
====================
`tools/gatekeeper-land.sh` judged ABSOLUTELY — any red refuses, whether or not
the base tree already carries it — and `tools/git-hooks/pre-push` refuses any
push to `main` without its stamp. Measured 2026-08-17 at origin/main
(f6b0e77dd): the base's OWN tip fails its own gates (`repo tools tests` 9 red,
`repo hygiene gates` 1 of 80 decided), so no stamp is written for it and the
hook refuses main's own tip. A commit that FIXES those reds is refused by the
same rule. That is a deadlock, and a deadlock is what sends an operator to
`gh pr merge` — the bypass the whole battery exists to close.

The repair is to ask the RIGHT QUESTION on the direct-push path: did THIS change
break something that used to work. The rule is not new — it is the one
`gatekeeper-verify-merge.sh` has used on the merge path since vibe-ic#1019, and
the same `decide()` computes it. What is new is the TIER, and a tier is exactly
the kind of addition that can silently buy leniency, so:

  THE TRAP, in the judge's own words (module docstring): "A fallback that passed
  everything would be worse than a gate that refused everything."

Every test below therefore comes in a pair with the deadlock case: the SAME
inputs that are allowed to land when the failure is inherited must still REFUSE
when the failure is the branch's. A file that only asserted the permissive half
would certify the very defect it exists to prevent.

chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process node.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
VERDICT = PROGRAMS / "landing_merge_verdict.py"

# The one land log both arms are given unless a test says otherwise. `FAIL
# targeted tests` is present on purpose: the test tier's own verdict belongs to
# the differential, not to the label, and `_TEST_TIER` exempts it. If that
# exemption ever went away this fixture would start refusing everything, which
# is the direction that is safe to discover.
LAND_LOG = (
    "=== gatekeeper landing gates — base=deadbeef ===\n"
    "  PASS  repo tools tests (31 file(s))\n"
    "  FAIL  targeted tests (2 file(s))\n"
    "=== FAILURES ABOVE — stamp removed; the pre-push hook will refuse ===\n"
)

# The `pytest_aggregate.` prefix is the driver's own namespacing
# (`pytest_per_file_junit._aggregate_copy`), and the judge accepts a testcase as
# authoritative only when it carries it. Spelling it out here rather than
# building it keeps the fixture honest about what the real instrument emits.
CLASSNAME = "pytest_aggregate.programs.tests.test_subject"
FILE = "programs/tests/test_subject.py"
KEY = f"{CLASSNAME}::test_one"


def _junit(outcome: str | None, *, process_rc: str = "1") -> str:
    """One aggregate testcase plus the driver's own process attestation.

    The process suite shape is NOT decoration. `landing_merge_verdict` refuses
    outright when the aggregate session produced no complete record, and it
    authenticates that record by the PARENT suite — a subject testcase can set
    its own classname through pytest's public fixtures, so a self-declared
    process verdict is never trusted. A fixture that omitted it would make every
    case below refuse for the wrong reason and prove nothing.
    """
    if outcome == "absent":
        # A DELETED TEST IS NOT A MISSING FILE. The file must still show up in
        # the aggregate channel or the run reads as incomplete rather than as a
        # deletion, so the file keeps a surviving sibling case.
        case = (f'<testcase classname="{CLASSNAME}" name="test_two" '
                f'file="{FILE}"></testcase>')
    else:
        inner = {"failed": "<failure/>", "errored": "<error/>",
                 "skipped": "<skipped/>",
                 "xfailed": '<skipped type="pytest.xfail"/>',
                 None: ""}[outcome]
        case = (f'<testcase classname="{CLASSNAME}" name="test_one" '
                f'file="{FILE}">{inner}</testcase>')
    return (
        '<?xml version="1.0"?><testsuites>'
        f'<testsuite name="aggregate::selection" tests="1">{case}</testsuite>'
        '<testsuite name="whole_selection::process_exit" tests="1">'
        '<testcase classname="pytest_aggregate_process" '
        'name="whole_selection::process_exit" file="&lt;aggregate&gt;">'
        f'<properties><property name="process_rc" value="{process_rc}"/>'
        '</properties></testcase></testsuite>'
        '</testsuites>')


def _run(tmp_path: Path, *, base: str | None, cand: str | None,
         tier: str = "direct-push", base_junit_written: bool = True,
         land_log: str = LAND_LOG, base_land_log: str | None = LAND_LOG,
         base_selection: bool = True):
    if base_junit_written:
        (tmp_path / "base.xml").write_text(_junit(base))
    (tmp_path / "cand.xml").write_text(_junit(cand))
    (tmp_path / "land.log").write_text(land_log)
    (tmp_path / "sel.txt").write_text(FILE + "\n")
    (tmp_path / "selb.txt").write_text(FILE + "\n" if base_selection else "")
    argv = [sys.executable, str(VERDICT),
            # `--base-tree` is REQUIRED (`landing_merge_verdict.py:1475`).
            # Without it argparse exits before `--json` is ever written and
            # every case here dies on a missing verdict.json — a fixture
            # failure that reads like a program one.
            "--base-sha", "a" * 40, "--base-tree", "c" * 40,
            "--head-sha", "b" * 40,
            "--verified-sha", "b" * 40, "--rebase-status", "ok",
            "--expected-tree", "t" * 40, "--verified-tree", "t" * 40,
            "--land-log", str(tmp_path / "land.log"),
            "--selection", str(tmp_path / "sel.txt"),
            "--base-selection", str(tmp_path / "selb.txt"),
            "--base-junit", str(tmp_path / "base.xml"),
            "--candidate-junit", str(tmp_path / "cand.xml"),
            "--verification-tier", tier,
            "--json", str(tmp_path / "verdict.json")]
    if base_land_log is not None:
        (tmp_path / "base_land.log").write_text(base_land_log)
        argv += ["--base-land-log", str(tmp_path / "base_land.log")]
    cp = subprocess.run(argv, capture_output=True, text=True)
    record = json.loads((tmp_path / "verdict.json").read_text())
    return cp, record


# ---------------------------------------------------------------- the deadlock


def test_a_red_that_the_base_also_carries_no_longer_refuses(tmp_path):
    """THE DEADLOCK, gone: an inherited failure is not this push's."""
    cp, rec = _run(tmp_path, base="failed", cand="failed")
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert rec["verdict"] == "LAND_OK"
    assert KEY in rec["delta"]["preexisting"]


def test_the_inherited_failure_is_named_in_the_record_not_merely_counted(tmp_path):
    """Silence is how a permanent red becomes invisible.

    A landing that passes WITH inherited reds is not the same event as one that
    passes clean, and the record has to be able to tell a reader which it was —
    by NAME, so the red can be chased.
    """
    _, rec = _run(tmp_path, base="failed", cand="failed")
    assert rec["delta"]["preexisting"] == [
        KEY, "pytest_aggregate_process::whole_selection::process_exit"]
    assert rec["base_land"] is not None
    assert rec["base_land"]["fail"], "the base's own failing gates must survive"


# ------------------------------------------- the paired negative controls
# Each of these is the SAME shape as the case above with ONE input changed. If
# the tier ever starts buying leniency, these are what notice.


def test_a_failure_the_base_does_not_have_still_refuses(tmp_path):
    """THE NEGATIVE CONTROL. A genuine regression must still be refused."""
    cp, rec = _run(tmp_path, base=None, cand="failed")
    assert cp.returncode == 1
    assert rec["verdict"] == "REFUSE"
    assert any("NEW FAILURE(S) THIS BRANCH OWNS" in r for r in rec["reasons"])
    assert rec["delta"]["new_failures"] == [KEY]


def test_turning_an_inherited_failure_into_a_skip_refuses(tmp_path):
    """`failed -> skipped` is never an improvement: the failure did not go
    away, the question did. This is the cheat a differential most invites."""
    cp, rec = _run(tmp_path, base="failed", cand="skipped")
    assert cp.returncode == 1
    assert any("SILENCED RATHER THAN FIXED" in r for r in rec["reasons"])


def test_marking_an_inherited_failure_xfail_refuses_too(tmp_path):
    """xfail is in SILENT alongside skipped, and for the same reason."""
    cp, rec = _run(tmp_path, base="failed", cand="xfailed")
    assert cp.returncode == 1
    assert any("SILENCED RATHER THAN FIXED" in r for r in rec["reasons"])


def test_deleting_an_inherited_failing_test_refuses(tmp_path):
    """ABSENT is a first-class outcome. Deleting the test is silencing it."""
    cp, rec = _run(tmp_path, base="failed", cand="absent")
    assert cp.returncode == 1
    assert any("SILENCED RATHER THAN FIXED" in r for r in rec["reasons"])


def test_skipping_a_test_that_passed_on_the_base_refuses(tmp_path):
    cp, rec = _run(tmp_path, base=None, cand="skipped")
    assert cp.returncode == 1
    assert any("WEAKENED" in r for r in rec["reasons"])


def test_errored_and_failed_are_the_same_pre_existing_red(tmp_path):
    """Ordinary pytest reds are interchangeable; only process rc is exact."""
    cp, _ = _run(tmp_path, base="failed", cand="errored")
    assert cp.returncode == 0


# --------------------------------------------- unknown never buys leniency


def test_an_unreadable_base_report_degrades_to_demand_green(tmp_path):
    """Not to 'assume it was red'. The strict direction, and it is disclosed."""
    cp, rec = _run(tmp_path, base=None, cand="failed", base_junit_written=False)
    assert cp.returncode == 1
    assert rec["delta"]["base_total"] == 0
    assert any("NEW FAILURE(S)" in r for r in rec["reasons"])


def test_an_absent_base_gate_log_makes_every_failing_gate_the_branchs(tmp_path):
    cp, rec = _run(
        tmp_path, base="failed", cand="failed", base_land_log=None,
        land_log=LAND_LOG.replace("  PASS  repo tools tests (31 file(s))\n",
                                  "  FAIL  repo tools tests (31 file(s))\n"))
    assert cp.returncode == 1
    assert any("repo tools tests" in r for r in rec["reasons"])


def test_a_gate_red_on_the_base_and_red_here_is_inherited_not_refused(tmp_path):
    """The gate tier gets the same rule as the test tier — subtraction by
    printed LABEL, with the discovery count stripped so a branch that adds a
    test file does not rename the gate and read as having silenced it."""
    red = LAND_LOG.replace("  PASS  repo tools tests (31 file(s))\n",
                           "  FAIL  repo tools tests (31 file(s))\n")
    grown = LAND_LOG.replace("  PASS  repo tools tests (31 file(s))\n",
                             "  FAIL  repo tools tests (32 file(s))\n")
    cp, rec = _run(tmp_path, base="failed", cand="failed",
                   land_log=grown, base_land_log=red)
    assert cp.returncode == 0, cp.stdout
    assert rec["base_land"]["fail"]


def test_silencing_a_base_red_gate_by_skipping_it_refuses(tmp_path):
    """The gate tier's half of `failed -> skipped`."""
    red = LAND_LOG.replace("  PASS  repo tools tests (31 file(s))\n",
                           "  FAIL  repo tools tests (31 file(s))\n")
    skipped = LAND_LOG.replace("  PASS  repo tools tests (31 file(s))\n",
                               "  SKIP  repo tools tests\n")
    cp, rec = _run(tmp_path, base="failed", cand="failed",
                   land_log=skipped, base_land_log=red)
    assert cp.returncode == 1
    assert any("SILENCED RATHER THAN FIXED" in r for r in rec["reasons"])


def test_a_base_arm_that_did_not_finish_is_refused_not_subtracted(tmp_path):
    """vibe-ic#1443 on the direct-push path. A base arm whose failed set is a
    SUBSET makes a silenced failure invisible, which is the permissive
    direction — so it refuses rather than degrading."""
    (tmp_path / "base.xml").write_text(_junit(None))
    (tmp_path / "cand.xml").write_text(_junit("failed"))
    (tmp_path / "land.log").write_text(LAND_LOG)
    (tmp_path / "base_land.log").write_text(LAND_LOG)
    (tmp_path / "sel.txt").write_text(FILE + "\n")
    # Asked for TWO files, the report covers one.
    (tmp_path / "selb.txt").write_text(FILE + "\nprograms/tests/test_other.py\n")
    cp = subprocess.run(
        [sys.executable, str(VERDICT),
         "--base-sha", "a" * 40, "--head-sha", "b" * 40,
         "--verified-sha", "b" * 40, "--rebase-status", "ok",
         "--expected-tree", "t" * 40, "--verified-tree", "t" * 40,
         "--land-log", str(tmp_path / "land.log"),
         "--base-land-log", str(tmp_path / "base_land.log"),
         "--selection", str(tmp_path / "sel.txt"),
         "--base-selection", str(tmp_path / "selb.txt"),
         "--base-junit", str(tmp_path / "base.xml"),
         "--candidate-junit", str(tmp_path / "cand.xml"),
         "--verification-tier", "direct-push",
         "--json", str(tmp_path / "verdict.json")],
        capture_output=True, text=True)
    rec = json.loads((tmp_path / "verdict.json").read_text())
    assert cp.returncode == 1
    assert any("PRODUCED NO TEST CASE ON THE BASE" in r for r in rec["reasons"])


# ------------------------------------------------- what the tier discloses


def test_the_tier_says_not_applicable_and_never_not_performed(tmp_path):
    """`NOT_PERFORMED` names evidence that was LOST; `NOT_APPLICABLE` names
    evidence that never existed. A direct push is not a squash, so there is no
    second computation of the landing tree for a cross-check to compare. A
    reader who cannot tell the two apart cannot tell a complete direct-push
    verdict from a degraded merge one."""
    _, rec = _run(tmp_path, base="failed", cand="failed")
    assert rec["verification_tier"] == "direct-push"
    assert rec["squash_vs_rebase_cross_check"] == "NOT_APPLICABLE"
    assert "SQUASH_VS_REBASE_CROSS_CHECK_NOT_APPLICABLE" in rec["disclosures"]
    assert "SQUASH_VS_REBASE_CROSS_CHECK_NOT_PERFORMED" not in rec["disclosures"]
    assert "VERIFICATION_TIER_DIRECT_PUSH" in rec["disclosures"]


@pytest.mark.parametrize("typo", ["direct_push", "directpush", "direct-pusher", ""])
def test_a_tier_arriving_by_typo_still_fails_closed(tmp_path, typo):
    """Adding a third tier must not make a fourth one inherit its silence."""
    cp, rec = _run(tmp_path, base="failed", cand="failed", tier=typo)
    assert cp.returncode == 2
    assert rec["unmeasurable"] is True
    assert rec["disclosures"] == ["VERIFICATION_TIER_UNKNOWN"]


def test_the_cross_tree_refusals_stay_armed_under_the_new_tier(tmp_path):
    """The direct-push caller keeps them armed by passing the pushed commit's
    tree as BOTH --expected-tree and --verified-tree. A caller that does not is
    caught here rather than trusted."""
    (tmp_path / "base.xml").write_text(_junit("failed"))
    (tmp_path / "cand.xml").write_text(_junit("failed"))
    (tmp_path / "land.log").write_text(LAND_LOG)
    (tmp_path / "sel.txt").write_text(FILE + "\n")
    (tmp_path / "selb.txt").write_text(FILE + "\n")
    cp = subprocess.run(
        [sys.executable, str(VERDICT),
         "--base-sha", "a" * 40, "--head-sha", "b" * 40,
         "--verified-sha", "b" * 40, "--rebase-status", "ok",
         "--expected-tree", "t" * 40, "--verified-tree", "u" * 40,
         "--land-log", str(tmp_path / "land.log"),
         "--selection", str(tmp_path / "sel.txt"),
         "--base-selection", str(tmp_path / "selb.txt"),
         "--base-junit", str(tmp_path / "base.xml"),
         "--candidate-junit", str(tmp_path / "cand.xml"),
         "--verification-tier", "direct-push",
         "--json", str(tmp_path / "verdict.json")],
        capture_output=True, text=True)
    rec = json.loads((tmp_path / "verdict.json").read_text())
    assert cp.returncode == 1
    assert any("VERIFIED THE WRONG TREE" in r for r in rec["reasons"])


def test_the_merge_tiers_are_untouched_by_the_addition(tmp_path):
    """The merge path must keep saying exactly what it said before."""
    _, strong = _run(tmp_path, base="failed", cand="failed", tier="merge-tree")
    assert strong["squash_vs_rebase_cross_check"] == "PERFORMED"
    assert strong["tier_degraded"] is False
    _, weak = _run(tmp_path, base="failed", cand="failed", tier="rebase-replay")
    assert weak["squash_vs_rebase_cross_check"] == "NOT_PERFORMED"
    assert weak["tier_degraded"] is True
