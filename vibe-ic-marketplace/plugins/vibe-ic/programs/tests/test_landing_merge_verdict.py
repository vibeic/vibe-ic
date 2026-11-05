"""A red suite survived five merges because `gh pr merge` runs no gate at all.

`tools/gatekeeper-land.sh` runs the tests and stamps the commit it verified;
`tools/git-hooks/pre-push` refuses a push whose commit has no matching stamp.
The enforcement is attached to `git push` — and a server-side squash merge
pushes nothing from a local clone, so neither ever fires. Measured on
2026-08-12: Actions `{"enabled": false}` at the account level, `main` `404
Branch not protected`, no required status check exists. There is no
server-side check to fall back on and none can be created.

`tools/gatekeeper-verify-merge.sh` puts the existing gates on the path that
lands code. This file gates the DECISION that script defers to
(`landing_merge_verdict.decide`) and the plumbing that feeds it.

WHAT THIS FILE REFUSES
======================
1. **A gate that cannot refuse.** Nine independent refusal reasons, each
   asserted on the VERDICT rather than on the printed text, so the mutant that
   neuters only the decision line kills them.
2. **A gate that refuses everything.** :func:`test_a_known_good_pr_shape_is_allowed`
   and the end-to-end paired guard: a landing that broke nothing must LAND OK.
   PR #1020 lost a whole corpus's one true finding to an always-fires mutant
   hours before #1019 was filed; a landing gate that refuses every landing is a
   ban, not a check.
3. **Crediting a silenced failure as a fix.** `failed -> skipped` and
   `failed -> absent` are refusals. Without that row the differential rewards
   the cheat it exists to catch: delete the red test and the failed set shrinks.
4. **A permissive degradation.** Every way the differential can lose
   information — empty base, no overlap, a truncated candidate run, a selected
   file that produced no test case — is asserted to go STRICTER, never softer.
   That list was asked of the CANDIDATE arm only. The BASE arm's completeness
   is the one that goes SOFTER (vibe-ic#1443): `silenced` and `weakened` are
   read off what was red or passing ON THE BASE, so a base failure that never
   got measured is a base failure the branch may delete for free. Measured on
   `3d13e2c59`, one selected file missing from the base report turned
   `REFUSE 1 FAILING TEST(S) WERE SILENCED` into `LAND OK` with every other
   input byte-identical.
5. **A verdict about the wrong tree.** `gh pr merge --squash` creates the
   forge's merge tree. A rebase that produces a different tree, or a forge that
   disagrees with the local merge, is refused before any suite is run.
"""
from __future__ import annotations

import ast
import json
import hashlib
import importlib.util
import os
import re
import signal
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import _watchdog  # noqa: E402
import _hermetic_engine_capability as _CAP  # noqa: E402

import _progress_run as _pr  # noqa: E402
import _outcome_states as states  # noqa: E402

_PROGRAMS = Path(__file__).resolve().parents[1]
_PROG = _PROGRAMS / "landing_merge_verdict.py"
_REPO_ROOT = _PROGRAMS.parents[3]
_VERIFY = _REPO_ROOT / "tools" / "gatekeeper-verify-merge.sh"
_LAND = _REPO_ROOT / "tools" / "gatekeeper-land.sh"
_GATEKEEPER_SKILL = Path(os.environ.get(
    "GATEKEEPER_SKILL_UNDER_TEST",
    _REPO_ROOT / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "skills"
    / "gatekeeper-loop" / "SKILL.md"))
_T = 55


def _service_program():
    return Path(os.environ.get("GATEKEEPER_SERVICE_UNDER_TEST", str(_PROG)))

# THE FILES THE MERGE VERIFIER EXECUTES OUT OF THE BASE SNAPSHOT, which the
# miniature repository below must carry as the real bytes.  This set used to be
# derived from the protected-path transition validator's two path registers;
# the owner removed that two-step mechanism on 2026-09-27, and the set it
# described is kept here, minus the two removed modules and plus the three the
# survivors now run (`landing_execution_plan.py`,
# `landing_record_primitives.py`, `landing_push_preflight.py`).
_VERIFIER_CLOSURE = frozenset({
    "tools/ci/_gate_dispatch.sh",
    "tools/ci/benchmark_data_landing_checkout.py",
    "tools/ci/hermetic_candidate_runner.py",
    "tools/ci/hermetic_git_subject.py",
    "tools/ci/hermetic_landing_arm_receipt.py",
    "tools/ci/hermetic_progress_emit.py",
    "tools/ci/hermetic_test_arm_entry.sh",
    "tools/ci/landing_completion_record.py",
    "tools/ci/landing_execution_plan.py",
    "tools/ci/landing_push_preflight.py",
    "tools/ci/landing_record_primitives.py",
    "tools/ci/owned_command.py",
    "tools/ci/repo_hygiene_gates.sh",
    "tools/ci/routed_def_corpus.py",
    "tools/ci/trusted_test_selection.py",
    "tools/ci/trusted_worktree_attest.py",
    "tools/gatekeeper-land.sh",
    "tools/gatekeeper-verify-merge.sh",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_atomic_artefact.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_corpus_location.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_crash_safe_scratch.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_gate_usage_exit.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_owned_process_supervisor.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_progress_run.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_prose_polarity.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_pytest_progress_plugin.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_routed_checker_progress.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_semantic_child_progress.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_vacuous_exit.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/_watchdog.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/ci_harness_timeout_ceiling_check.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/ci_targeted_test_select.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/drc_vacuous_pass_check.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/gate_process_attestation.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/generated_test_list_min_guard.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/hygiene_finding_delta.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/landing_merge_verdict.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/landing_noop_verdict_check.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/macro_obs_geometry_intersect_check.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/matrix_mutation_ledger.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/pytest_per_file_junit.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/repo_hygiene_parallel.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/step_internal_fail_bubble_up_check.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/step_metrics.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_flow_matrix_census_freshness.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_flow_matrix_coverage.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_artefact_mutation_channel.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_mutation_ledger.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tool_diagnostic_id_acceptance.json",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tool_diagnostic_id_gate.py",
    "vibe-ic-marketplace/plugins/vibe-ic/programs/trusted_pytest_entry.py",
})
_SELECT_CONTROL_TESTS = (
    "programs/tests/test_ci_harness_timeout_ceiling_check.py",
    "programs/tests/test_gate_process_attestation.py",
    "programs/tests/test_landing_merge_verdict.py",
    "programs/tests/test_pytest_per_file_junit.py",
)

TREE = "a" * 40
OTHER_TREE = "b" * 40
SHA = "c" * 40

_GOOD_LOG = """=== gatekeeper landing gates — base=origin/main ===
--- cheap tier (also enforced by the pre-push hook) ---
  PASS  NDA — added content/paths
  PASS  version monotonic (assigned at merge — deferred)
  REPORT  untracked scratch paths in this checkout
--- full tier (minutes; stamps the tree on success) ---
  PASS  targeted tests (21 file(s))
  PASS  repo hygiene gates
=== ALL GATES PASS — stamped %s ===
""" % SHA[:9]

_RED_TEST_TIER_LOG = """=== gatekeeper landing gates — base=origin/main ===
  PASS  NDA — added content/paths
  PASS  version monotonic (assigned at merge — deferred)
  FAIL  targeted tests (21 file(s))
  PASS  repo hygiene gates
=== FAILURES ABOVE — stamp removed; the pre-push hook will refuse ===
"""






# ============================================================ THE PAIRED GUARD












# ==================================================== THE NINE REFUSAL REASONS
















# ==================================== THE GATE TIER GETS THE SAME DIFFERENTIAL
#
# Measured at `e4880703b`: `flow_gate_enforcement_audit` and the 63x8 census
# freshness check are BOTH red on the base. An absolute rule would have refused
# every landing — the ban this program exists to avoid — so the gate tier is
# compared, not asserted.




















# ============================= ARM A'S COMPLETENESS IS ALSO A REFUSAL (#1443)








# ================================================= UNMEASURABLE IS NOT A PASS




























# ======================================== EVERY DEGRADATION GOES STRICTER
















# ================================================== THE DECISION TABLE, EXACTLY






# ============================================================= JUNIT + THE LOG
























# ==================================================================== THE CLI




_SEL = ["programs/tests/test_thing.py"]
_CASE_OK = [("programs.tests.test_thing", "a", "passed", None)]
_CASE_RED = [("programs.tests.test_thing", "a", "failed", None)]










_SEL2 = ["programs/tests/test_alpha.py", "programs/tests/test_beta.py"]
# The candidate turned a base failure into a SKIP — the exact cheat the
# differential exists to catch.
_CASE_SILENCED_CAND = [
    ("programs.tests.test_alpha", "t_red", "skipped", "programs/tests/test_alpha.py"),
    ("programs.tests.test_beta", "t_ok", "passed", "programs/tests/test_beta.py"),
]
_CASE_BASE_WHOLE = [
    ("programs.tests.test_alpha", "t_red", "failed", "programs/tests/test_alpha.py"),
    ("programs.tests.test_beta", "t_ok", "passed", "programs/tests/test_beta.py"),
]
# The SAME base arm, stopped before `test_alpha.py` was reached.
_CASE_BASE_PARTIAL = [
    ("programs.tests.test_beta", "t_ok", "passed", "programs/tests/test_beta.py"),
]


# ============================ PER-FILE NORECORD, FROM THE REPORT (vibe-ic#1709)
#
# `pytest_per_file_junit.py` keeps a file whose session died ABSENT from the
# merged report and names it on stdout as NORECORD. Until #1709 the ONLY thing
# carrying that fact to this verdict was `gatekeeper-land.sh`'s
# `grep -qa '^NORECORD'` over the driver's combined driver/subject stdout —
# `missing_process_files` was declared in `decide`, initialised to `[]` in
# `main`, and never populated, and `junit_per_file_process_files` had no caller.
#
# These tests hold the structured path in BOTH directions: a complete candidate
# must LAND (the fix is not a ban) and an incomplete one must REFUSE and NAME
# the file (the fix is not a check that cannot fail).




_PER_FILE_NORECORD_LOG = _GOOD_LOG.replace(
    "=== ALL GATES PASS",
    "  FAIL  targeted per-file session produced no complete record\n"
    "=== ALL GATES PASS")





























# ======================================= THE SHELL SCRIPT HAS NO OWN OPINION






def test_the_forge_cross_check_is_dropped_when_the_forge_merged_another_base():
    """A FALSE REFUSAL IS THE SAME DEFECT AS A FALSE PASS, and this one was found
    by running the script against a real open PR.

    `refs/pull/<n>/merge` is the merge of the PR head into the tip of the branch
    the PR TARGETS. Asked about any other base it is not a second opinion, it is a
    different question — and the first real run printed a confident
    `THE FORGE DISAGREES` about a PR that was fine. The cross-check now applies
    only when the forge's own first parent IS the base being verified, and says so
    when it does not."""
    src = _VERIFY.read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert 'rev-parse "$MERGE_REF^1"' in body, \
        "the forge's own base is never read, so it cannot be compared"
    assert '[ "$FORGE_BASE" = "$BASE_SHA" ]' in body, \
        "the forge tree is used without checking which base it is about"
    assert "answers a different question" in src, \
        "the drop is silent; a cross-check that did not happen must say so"




def test_the_base_gate_cache_is_disabled_at_the_adversarial_boundary():
    """A candidate that learns RUN must not plant baseline evidence in a cache.

    Reuse can return only after cache bundles are authenticated outside the
    subject's writable lifetime.  Until then the base is intentionally measured
    after both candidate containers have exited and been removal-proved.
    """
    src = _VERIFY.read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert 'base-gate cache disabled for adversarial differential ownership' in body
    assert 'BASE_GATE_CACHE=""' in body
    assert 'CACHED_MANIFEST' not in body
    assert 'A2_CACHE_LOCK_FD' not in body
    assert body.index('wait "$B2_PID"') < body.index('\n  prepare_base_wave\n')


def test_the_critical_path_does_not_run_targeted_tests_inside_a2_again():
    src = _VERIFY.read_text(encoding="utf-8")
    body = "\n".join(line for line in src.splitlines()
                     if not line.lstrip().startswith("#"))
    runner = (_REPO_ROOT / "tools/ci/hermetic_candidate_runner.py").read_text()
    assert '"GATEKEEPER_SKIP_TARGETED_TESTS": "1"' in runner
    assert '"GATEKEEPER_NO_STAMP": "1"' in runner
    assert body.count("launch_hermetic_test_arm") >= 3  # definition + A1/B1
    assert body.count("launch_hermetic_land_arm") >= 3  # definition + A2/B2




def test_neither_arm_can_read_the_others_scratch_file():
    """Running `gatekeeper-land.sh` for the BASE and the CANDIDATE at the same
    time made two pre-existing fixed `/tmp` names live: the targeted SELECTION
    and the commit-message dump. Two arms sharing either one would each have
    answered about the other's tree — a gate quietly measuring the wrong thing,
    which is the defect class this file is about."""
    land = _LAND.read_text(encoding="utf-8")
    body = "\n".join(l for l in land.splitlines() if not l.lstrip().startswith("#"))
    assert "/tmp/gk_sel.txt" not in body
    assert "/tmp/gk_commit_text.txt" not in body
    assert "mktemp" in body
    verify = _VERIFY.read_text(encoding="utf-8")
    vbody = "\n".join(l for l in verify.splitlines()
                      if not l.lstrip().startswith("#"))
    assert 'HEAD_REF="refs/gk-verify/$RUN_ID/head"' in vbody, \
        "two concurrent verifications would fetch over one another's head ref"


def _shell_function(source: str, name: str) -> str:
    """The exact text of one top-level `name() { ... }` shell function."""
    opening = f"{name}() {{\n"
    start = source.index(opening)
    end = source.index("\n}\n", start)
    return source[start:end + len("\n}\n")]


def test_a_missing_receipt_quotes_the_arms_own_refusal_not_only_the_symptom(
        tmp_path):
    """THREE DIFFERENT CAUSES REDUCED TO ONE SENTENCE, measured in one evening.

    When an arm writes no receipt, the validator can only say `cannot resolve
    runner receipt: [Errno 2] No such file or directory`, and that same line
    was what a reader saw for `subject would expose the host HOME to the
    candidate` (TMPDIR under $HOME), for `cannot start Docker CLI` (a runtime
    with no engine), and for `candidate ended without the exact semantic
    terminal record` (the progress-scan defect). The runner's own log holds the
    distinguishing line and is deleted with the run directory, so it has to be
    quoted at the refusal or it is gone.

    Asserted against the script's OWN function text, and both ways: a log that
    exists must be quoted, and a log that does not exist must be NAMED as
    absent -- "I could not run it" may not read the same as "I ran it and it
    failed"."""
    driver = tmp_path / "driver.sh"
    driver.write_text(
        "set -uo pipefail\n"
        'RUN="$1"\n'
        + _shell_function(_VERIFY.read_text(encoding="utf-8"),
                          "arm_norecord_diagnosis")
        + 'arm_norecord_diagnosis B1 "$2"\n')
    run = tmp_path / "run"
    run.mkdir()
    record_log = tmp_path / "record.log"
    record_log.write_text(
        "[NORECORD] hermetic landing arm receipt: cannot resolve runner "
        "receipt: [Errno 2] No such file or directory\n")

    absent = _pr.run(
        ["bash", str(driver), str(run), str(record_log)],
        capture_output=True, text=True)
    assert "b1-runner.log" in absent.stderr, absent.stderr
    assert "did not even start" in absent.stderr, absent.stderr

    (run / "b1-runner.log").write_text(
        "[NORECORD] hermetic candidate: subject would expose the host HOME "
        "to the candidate\n")
    quoted = _pr.run(
        ["bash", str(driver), str(run), str(record_log)],
        capture_output=True, text=True)
    assert "would expose the host HOME" in quoted.stderr, quoted.stderr
    assert "cannot resolve runner receipt" in quoted.stderr, quoted.stderr


def test_reading_one_arms_exit_code_cannot_byte_compile_the_shared_runtime(
        tmp_path):
    """THE INSTRUMENT WROTE INTO THE THING IT WAS MEASURING.

    `validated_arm_exit` imports the arm-receipt helper OUT OF the BASE
    runtime snapshot, and that snapshot's TREE DIGEST is what every later arm's
    receipt is re-checked against.  It is invoked with
    `PYTHONDONTWRITEBYTECODE=1 python3 -I`, which reads as belt and braces and
    is neither: `-I` implies `-E`, so the interpreter IGNORES every PYTHON*
    variable including that one.  The first call therefore byte-compiled the
    helper into `<runtime>/tools/ci/__pycache__/`, the runtime grew by a file,
    and the NEXT validation refused with "receipt runtime digest differs from
    the current input" -> "B2 arm receipt is NORECORD".  B1 validates first, so
    on main every branch lost its B2, A1 and A2 arms to the act of reading B1's
    exit code.  Measured on the fixture: runtime files 57 -> 58.

    Asserted BEHAVIOURALLY, against the script's own function text: a flag
    assertion would pass on `-B` written into a comment, and the property that
    matters is that the tree the reader imported from is byte-identical
    afterwards.  The call is expected to FAIL here (there is no valid record);
    the pollution happens during the import, before the record is ever read.
    """
    runtime = tmp_path / "runtime" / "tools" / "ci"
    runtime.mkdir(parents=True)
    for name in ("hermetic_landing_arm_receipt.py",
                 "landing_record_primitives.py"):
        shutil.copy2(_REPO_ROOT / "tools" / "ci" / name, runtime / name)
    before = sorted(path.name for path in runtime.iterdir())

    driver = tmp_path / "driver.sh"
    driver.write_text(
        "set -uo pipefail\n"
        + _shell_function(_VERIFY.read_text(encoding="utf-8"),
                          "validated_arm_exit")
        + 'validated_arm_exit "$1" "$2"\n')
    _pr.run(
        ["bash", str(driver), str(runtime / "hermetic_landing_arm_receipt.py"),
         str(tmp_path / "no-such-record.json")],
        capture_output=True, text=True)

    assert sorted(path.name for path in runtime.iterdir()) == before, \
        "reading an arm's exit code changed the runtime tree it read from"
    assert not list(runtime.rglob("__pycache__")), \
        "the arm-exit reader byte-compiled the BASE runtime snapshot"


def test_the_candidate_arm_runs_without_a_maxfail_bound():
    """FOUND BY RUNNING AGAINST A REAL OPEN PR. `--maxfail=10` is right for the
    push path — stop early, the answer is "go fix it" — and WRONG for a
    differential, which needs the whole failed set and not a prefix of one.

    Measured on PR #1028 (137 selected files, 3242 tests at the base, which is
    itself 47 red): the bound stopped the candidate at 1437 tests and the verdict
    correctly refused as unmeasurable. A landing gate that cannot answer for a
    wide PR is a landing gate nobody uses, so the verify script lifts the bound
    for its own arm and the push path keeps it."""
    land = _LAND.read_text(encoding="utf-8")
    lbody = "\n".join(l for l in land.splitlines() if not l.lstrip().startswith("#"))
    assert 'GATEKEEPER_PYTEST_MAXFAIL:-10' in lbody, \
        "the default is no longer 10, so the push path changed"
    assert '"${GATEKEEPER_PYTEST_MAXFAIL:-10}" = "0" ] && maxfail=()' in lbody
    entry = (_REPO_ROOT / "tools/ci/hermetic_test_arm_entry.sh").read_text()
    driver = (_PROGRAMS / "pytest_per_file_junit.py").read_text()
    assert "--aggregate-only" in entry
    assert "--stop-after-failures" not in entry
    assert 'add_argument("--stop-after-failures", type=int, default=0' in driver, \
        "the candidate aggregate arm still truncates, so the differential cannot be computed"


def test_the_junit_hook_in_the_landing_script_changes_no_verdict():
    """`GATEKEEPER_PYTEST_JUNIT` may only ADD a report. If it ever gated
    anything, the merge path and the push path would stop agreeing."""
    src = _LAND.read_text(encoding="utf-8")
    assert "GATEKEEPER_PYTEST_JUNIT" in src
    for line in src.splitlines():
        if "GATEKEEPER_PYTEST_JUNIT" in line and not line.lstrip().startswith("#"):
            assert "FAILED=1" not in line, line


def test_the_version_deferral_still_refuses_a_backwards_version():
    """The deferral is `--version-by-gatekeeper`, which the program already
    ships: no-change PASSes, BACKWARDS still FAILs. Turning the gate OFF would
    have traded an unsatisfiable gate for an unguarded one."""
    src = _LAND.read_text(encoding="utf-8")
    assert "--version-by-gatekeeper" in src
    r = _pr.run(
        [sys.executable, str(_PROGRAMS / "version_bump_monotonic_check.py"),
         "--current", "1.0.0", "--previous", "2.0.0", "--version-by-gatekeeper"],
        capture_output=True, text=True)
    assert r.returncode != 0, r.stdout + r.stderr


# ============================================ END TO END, ON A REAL GIT REPO
#
# The negative control #1019 asks for by name: a branch whose DIFF is innocuous
# and which leaves a test red. That is the shape that got through five times —
# nothing in the diff looks like a test change, and no gate ran the tests.


_STUB_SELECT = """#!/usr/bin/env python3
MODE_IMPORT_EDGE = "import-edge"

def select_tests(changed_paths, plugin_root, plugin_rel, *, mode):
    assert mode == MODE_IMPORT_EDGE
    return ["programs/tests/test_thing.py"]

if __name__ == "__main__":
    print("programs/tests/test_thing.py")
"""

_STUB_LAND = r"""#!/usr/bin/env bash
# A minimal stand-in for gatekeeper-land.sh with the same OBSERVABLE contract:
# the sentinel, `  PASS  ` / `  FAIL  ` lines, a junit report when asked, and a
# stamp only when everything passed.
#
# SINCE v1.10.69 THAT CONTRACT INCLUDES THE SEMANTIC LANDING RECORD, and this
# stub carried none of it.  When the hermetic runner hands a landing arm
# VIBEIC_LANDING_PROGRESS/VIBEIC_LANDING_COMPLETION, the real
# `tools/gatekeeper-land.sh` publishes, in this exact order: one `start`
# progress row, then for each parent-owned `landing:<ARM>` unit one journal row
# AND one relayed checkpoint, then the completion record, then one `terminal`
# row — and it exits with its own FAILED flag so the receipt's exit code and
# the record's `returncode` agree.  A stub that emits none of that makes EVERY
# arm die inside the runner with "candidate ended without the exact semantic
# terminal record", which is a property of this fixture and not of the subject
# under test, so no test in this file could reach any arm at all.
#
# The unit population is READ FROM `/input/progress-plan.json`, the same
# parent-owned plan the runner validates the relay against, rather than
# hard-coded here: a stub with its own copy of the list would drift from the
# plan silently and fail as "differs from the parent-owned FSM".
set -uo pipefail
ROOT="$(git rev-parse --show-toplevel)"
PLUGIN="$ROOT/vibe-ic-marketplace/plugins/vibe-ic"
RUNTIME_ROOT="${GATEKEEPER_RUNTIME_ROOT:-$ROOT}"
FAILED=0
LANDING_RECORD_ENABLED=0
LANDING_RECORD_TOOL="$RUNTIME_ROOT/tools/ci/landing_completion_record.py"
LANDING_PROGRESS_TOOL="$RUNTIME_ROOT/tools/ci/hermetic_progress_emit.py"
LANDING_JOURNAL="${VIBEIC_LANDING_PROGRESS:-}"
LANDING_COMPLETION="${VIBEIC_LANDING_COMPLETION:-}"
LANDING_UNITS=()
if [ -n "$LANDING_JOURNAL" ] || [ -n "$LANDING_COMPLETION" ]; then
  if [ -z "$LANDING_JOURNAL" ] || [ -z "$LANDING_COMPLETION" ]; then
    echo "[NORECORD] stub landing completion environment is partial" >&2
    exit 2
  fi
  mapfile -t LANDING_UNITS < <(python3 -I -c '
import json
with open("/input/progress-plan.json", "rb") as handle:
    for unit in json.load(handle)["units"]:
        print(unit)
') || { echo "[NORECORD] stub cannot read the parent progress plan" >&2; exit 2; }
  [ "${#LANDING_UNITS[@]}" -gt 0 ] \
    || { echo "[NORECORD] parent progress plan declared no unit" >&2; exit 2; }
  python3 "$LANDING_PROGRESS_TOOL" start \
    || { echo "[NORECORD] stub landing progress could not start" >&2; exit 2; }
  LANDING_RECORD_ENABLED=1
fi

landing_record() {                  # landing_record <unit> <state> <rc>
  [ "$LANDING_RECORD_ENABLED" = "1" ] || return 0
  local unit="$1" state="$2" rc="$3" digest
  digest="$(printf 'stub-land:%s:%s:%s' "$unit" "$state" "$rc" \
            | sha256sum | awk '{print $1}')" \
    || { echo "[NORECORD] cannot digest stub landing stage $unit" >&2; exit 2; }
  python3 "$LANDING_RECORD_TOOL" append --journal "$LANDING_JOURNAL" \
    --label "$unit" --state "$state" --returncode "$rc" \
    --output-sha256 "$digest" \
    || { echo "[NORECORD] cannot attest stub landing stage $unit" >&2; exit 2; }
  python3 "$LANDING_PROGRESS_TOOL" checkpoint "$unit" \
    || { echo "[NORECORD] cannot relay stub landing stage $unit" >&2; exit 2; }
}

# The one unit whose state this stub actually MEASURES is the targeted-test
# tier; `full:repo-hygiene` follows the routed-transition branch below when it
# runs.  Everything else is a cheap gate this fixture does not model, recorded
# PASS so the journal carries the exact parent-owned population in order — the
# population is what the runner checks, and a partial journal is refused.
STUB_TARGETED_STATE=PASS
STUB_TARGETED_RC=0
STUB_HYGIENE_STATE=PASS
STUB_HYGIENE_RC=0

landing_publish() {
  [ "$LANDING_RECORD_ENABLED" = "1" ] || return 0
  local unit state rc
  for unit in "${LANDING_UNITS[@]}"; do
    state=PASS
    rc=0
    case "$unit" in
      full:targeted-tests) state="$STUB_TARGETED_STATE"; rc="$STUB_TARGETED_RC" ;;
      full:repo-hygiene)   state="$STUB_HYGIENE_STATE";  rc="$STUB_HYGIENE_RC" ;;
    esac
    [ "$state" = "FAIL" ] && FAILED=1
    landing_record "$unit" "$state" "$rc"
  done
  python3 "$LANDING_RECORD_TOOL" finish --journal "$LANDING_JOURNAL" \
    --record "$LANDING_COMPLETION" --failed "$FAILED" \
    || { echo "[NORECORD] stub landing completion is incomplete" >&2; exit 2; }
  python3 "$LANDING_PROGRESS_TOOL" terminal \
    || { echo "[NORECORD] stub landing terminal is incomplete" >&2; exit 2; }
}
# FOUR STIMULUS BRANCHES USED TO SIT HERE AND NONE OF THEM COULD EVER FIRE.
# They wrote `<ARM>.started` into GATEKEEPER_CONCURRENCY_PROBE_DIR, appended to
# the corpus under GATEKEEPER_MUTATE_BENCHMARK_ARM, pre-wrote the base wave
# under GATEKEEPER_PREWRITE_BASE_ARTIFACTS and relinked the selection under
# GATEKEEPER_RELINK_SELECTION.  MEASURED on a4caccefe: not one of those four
# names is on the hermetic launcher's `--env` allow-list, so inside an arm each
# is EMPTY and the branch is skipped; and the three that reach for the parent's
# run directory do it through GATEKEEPER_BENCHMARK_MEASUREMENT_RECORD, a name
# that occurs ZERO times in the verifier AND ZERO times in the real
# tools/gatekeeper-land.sh, so it expands to `.` — the container's read-only
# /subject.  Their four tests are rewritten against channels that exist; this
# code is deleted rather than left, because unreachable stimulus code reads to
# the next person exactly like coverage.  GATEKEEPER_STUB_ROUTED_TRANSITION
# below is NOT of that class: _routed_activation_repo rewrites that branch to
# key on committed subject content, which does reach an arm.
if [ "${GATEKEEPER_STUB_ROUTED_TRANSITION:-0}" = "1" ] \
   && { [ "${GATEKEEPER_VERIFY_ARM:-}" = "A2" ] \
        || [ "${GATEKEEPER_VERIFY_ARM:-}" = "B2" ]; }; then
  rm -f "${GATEKEEPER_HYGIENE_REPORT}.attest"
  export GATE_DISPATCH_ATTESTATION_HELPER="$PLUGIN/programs/gate_process_attestation.py"
  export GATE_DISPATCH_ATTESTATION_FILE="${GATEKEEPER_HYGIENE_REPORT}.attest"
  (
    . "$ROOT/tools/ci/_gate_dispatch.sh"
    gate_dispatch_init --summary-json "$GATEKEEPER_HYGIENE_REPORT"
    _per_routed() {
      local def="$1" cell design
      cell="${def%/phase3/stage3/pnr/routed.def}"
      verdir="$(basename "$cell")"
      design="$(basename "$(dirname "$cell")")/${verdir#*_}"
      uncheckable_until 2027-02-28 "fixture has no macro LEF"
      run_tolerating_uncheckable "macro OBS not crossed ($design)" \
        "$PLUGIN" python3 programs/macro_obs_geometry_intersect_check.py "$cell"
      uncheckable_until 2027-02-28 "fixture may have no DRC evidence"
      run_tolerating_uncheckable "DRC PASS is not vacuous ($design)" \
        "$ROOT" python3 "$PLUGIN/programs/drc_vacuous_pass_check.py" "$cell"
      uncheckable_until 2027-02-28 "fixture may have no step reports"
      run_tolerating_uncheckable "inner FAILs reach the verdict ($design)" \
        "$ROOT" python3 "$PLUGIN/programs/step_internal_fail_bubble_up_check.py" "$cell"
      uncheckable_until 2027-02-28 "fixture has no preceding same-PDK run"
      run_tolerating_uncheckable "new tool diagnostic id ($design)" \
        "$PLUGIN" python3 programs/tool_diagnostic_id_gate.py "$cell"
    }
    if [ "$GATEKEEPER_VERIFY_ARM" = "A2" ] \
       && [ "${GATEKEEPER_STUB_BASE_EXPANDED:-0}" != "1" ]; then
      gate_dispatch_over "published cells carrying a routed DEF" \
        _per_routed true
    else
      GATE_DISPATCH_ATTEST_POPULATION=1 \
      gate_dispatch_over "published cells carrying a routed DEF" \
        _per_routed python3 "$ROOT/tools/ci/routed_def_corpus.py" --repo "$ROOT"
    fi
    gate_dispatch_finish
  ) >/dev/null 2>&1 || true
  if [ ! -s "${GATEKEEPER_HYGIENE_REPORT:-}" ]; then
    echo "  FAIL  repo hygiene gates"
    echo "=== FAILURES ABOVE — no routed transition record ==="
    exit 2
  fi
  # The gate LINE is emitted with the others, after the opening sentinel: a
  # `  FAIL  ` line printed before the sentinel is outside the record the
  # verifier parses, and an arm whose log closes with ALL GATES PASS while it
  # exits 1 is refused as "no complete terminal record for rc=1".  Nothing had
  # ever run this branch under the semantic landing record to notice.
  STUB_HYGIENE_STATE=FAIL
  STUB_HYGIENE_RC=1
fi
# THE HYGIENE SUMMARY IS PART OF A LANDING ARM'S OUTPUT, always — the verifier
# seals `hygiene.json` out of both A2 and B2 with
# `publish_validated_arm_artifact`, requires `corpus_inputs.benchmark_data_sha`
# to bind the corpus it measured, and the completion record digests that exact
# file.  Only the routed-transition branch above ever wrote one, so every other
# arm had no hygiene artifact to seal.  Emit the ordinary one through the real
# dispatcher (never a hand-written JSON blob: the digest must come from the
# same emitter production uses) whenever that branch did not.
if [ -n "${GATEKEEPER_HYGIENE_REPORT:-}" ] \
   && [ ! -s "${GATEKEEPER_HYGIENE_REPORT}" ]; then
  rm -f "${GATEKEEPER_HYGIENE_REPORT}.attest"
  (
    export GATE_DISPATCH_ATTESTATION_HELPER="$PLUGIN/programs/gate_process_attestation.py"
    export GATE_DISPATCH_ATTESTATION_FILE="${GATEKEEPER_HYGIENE_REPORT}.attest"
    . "$ROOT/tools/ci/_gate_dispatch.sh"
    gate_dispatch_init --summary-json "$GATEKEEPER_HYGIENE_REPORT"
    # One real dispatched gate, not zero: `hygiene_finding_delta` requires an
    # exact bijection between the gates in PROCESS states and the process
    # attestations, so a summary with a gate and no attestation is REFUSED and
    # the verdict cannot compute the differential at all.
    run "a cheap gate" "$ROOT" true
    gate_dispatch_finish
  ) >/dev/null 2>&1 || true
  [ -s "${GATEKEEPER_HYGIENE_REPORT}" ] \
    || { echo "[NORECORD] stub hygiene summary was not produced" >&2; exit 2; }
fi
echo "=== gatekeeper landing gates — base=${GATEKEEPER_BASE:-origin/main} ==="
echo "  PASS  a cheap gate"
if [ "$STUB_HYGIENE_STATE" = "FAIL" ]; then
  echo "  FAIL  repo hygiene gates"
fi
SEL="$(mktemp -t stub_sel.XXXXXX)"
JOUT="${GATEKEEPER_PYTEST_JUNIT:-$(mktemp -t stub_junit.XXXXXX)}"
( cd "$PLUGIN" && python3 programs/ci_targeted_test_select.py --base "${GATEKEEPER_BASE:-HEAD}" ) > "$SEL"
STUB_STAMP=0
if [ "${GATEKEEPER_SKIP_TARGETED_TESTS:-0}" = "1" ]; then
  echo "  SKIP  targeted tests — measured by the independent aggregate test arm"
  STUB_TARGETED_STATE=SKIP
  STUB_TARGETED_RC=0
elif ( cd "$PLUGIN" && python3 programs/pytest_per_file_junit.py \
       --selection "$SEL" --junit "$JOUT" --stall-after 10 \
       --aggregate-check --aggregate-only --aggregate-stall-after 10 \
       -- python3 -m pytest -q --maxfail=10 >/dev/null 2>&1 ); then
  echo "  PASS  targeted tests (1 file(s))"
  echo "  REPORT  targeted test process verdicts embedded in junit"
  echo "  REPORT  targeted aggregate session completed"
  STUB_TARGETED_STATE=PASS
  STUB_TARGETED_RC=0
  STUB_STAMP=1
else
  echo "  FAIL  targeted tests (1 file(s))"
  echo "  REPORT  targeted test process verdicts embedded in junit"
  echo "  REPORT  targeted aggregate session completed"
  STUB_TARGETED_STATE=FAIL
  STUB_TARGETED_RC=1
fi
# BEFORE the closing sentinel and before any stamp, exactly where the real
# script publishes it: the journal, the completion record and the terminal
# progress row are what make this arm's evidence readable at all, and a stamp
# minted before them would claim a landing whose record does not exist.
# `landing_publish` also sets FAILED from the journal it wrote.
landing_publish
if [ "$STUB_TARGETED_STATE" = "SKIP" ] \
   && [ "${GATEKEEPER_NO_STAMP:-0}" = "1" ] \
   && [ "$FAILED" = "0" ]; then
  echo "  REPORT  merge verifier owns the independent targeted-test evidence"
  echo "=== ALL NON-TARGET GATES COMPLETE — stamp withheld for composite verdict ==="
elif [ "$FAILED" != "0" ]; then
  echo "=== FAILURES ABOVE — stamp removed; the pre-push hook will refuse ==="
else
  [ "$STUB_STAMP" = "1" ] \
    && git rev-parse HEAD > "$(git rev-parse --absolute-git-dir)/gatekeeper-stamp"
  echo "=== ALL GATES PASS — stamped $(git rev-parse --short HEAD) ==="
fi
rm -f "$SEL"
# The receipt binds the arm's natural exit code to the completion record's
# `returncode`, and the verifier refuses any pair other than 0:0 or 1:1.  The
# stub therefore has to exit with the same FAILED flag it just attested rather
# than always 0.
exit "$FAILED"
"""

# `thing.py` is ORDINARY SOURCE and `test_thing.py` pins it. The negative
# control's diff therefore touches no test file at all — which is the whole
# point: what got through five times looked like a normal source change.
_THING_SRC = "VALUE = {v}\n"
_THING_TEST = """import pathlib


# The cross-arm rendezvous that used to be here waited for `<ARM>.started`
# markers its siblings could not write: an arm is a container with network none
# and no shared writable surface, so it cannot observe another arm at all. The
# wave property is asserted host-side instead, in
# test_end_to_end_candidate_wave_precedes_parallel_isolated_base_wave.


def test_value_is_one():
    src = (pathlib.Path(__file__).resolve().parents[1] / "thing.py").read_text()
    assert "VALUE = 1" in src
"""


def _import_time_siblings(staged_file, programs):
    """The `programs/*.py` modules `staged_file` imports AT IMPORT TIME.

    Only the imports an arm actually executes on `import`: module level, plus
    the bodies of a module-level `if`/`try`, which is how the tree spells an
    optional dependency.  An import inside a function is NOT one of these — it
    runs when that function is called, and staging on it would drag
    `flow_compliance_check` and its whole phase-1 chain into a fixture that
    calls none of it.  MEASURED over this fixture's 36 staged programs at
    parent 9dff42ceb: 2 files by this rule, 202 by the indiscriminate one.

    The STAGED bytes are parsed, never the upstream ones: the fixture replaces
    some programs with deliberately tiny stubs, and what the arm imports is
    what is in the miniature repository, not what this checkout ships.
    """
    names = set()

    def scan(body):
        for node in body:
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    names.add(node.module.split(".")[0])
            elif isinstance(node, (ast.If, ast.Try)):
                scan(node.body)
                scan(node.orelse)
                for handler in getattr(node, "handlers", ()):
                    scan(handler.body)
                scan(getattr(node, "finalbody", ()))

    scan(ast.parse(staged_file.read_text(encoding="utf-8", errors="replace")).body)
    return sorted(n for n in names if (programs / f"{n}.py").is_file())


def _stage_program_import_closure(staged, programs):
    """Complete the staged programs to a CLOSURE, derived from the tree.

    THE LIST ABOVE NAMES GATES; A GATE ALSO HAS DEPENDENCIES, and nothing was
    deriving those.  A program that grows one `import <sibling>` line arrives
    in the miniature repository without it, and inside an arm the gate does not
    report a defect — it dies at import, `_gate_dispatch.sh` reads rc 1 as a
    FINDING rather than rc 2 "could not check", and the finding is present on
    the candidate and absent from the base, so the landing gate refuses a
    branch that broke nothing.

    MEASURED on 9dff42ceb, in the pinned image, with the engine reachable:

        macro_obs_geometry_intersect_check.py -> _flow_reason_taxonomy
            ModuleNotFoundError -> rc 1 -> `[FAIL] macro OBS not crossed
            (tiny/openpdkx)` -> REFUSE 1 HYGIENE FINDING(S) INTRODUCED
        matrix_mutation_ledger.py             -> _run_isolation
            the same defect, one gate that this fixture does not yet dispatch

    Neither name was omitted on purpose; both were added upstream by a commit
    that had no way to know this fixture existed.  So the closure is COMPUTED
    from what is staged instead of typed here — a hand-written list is exactly
    the artefact that produced the two above, and it would produce the third.

    A file already in `staged` is never overwritten: the stubs this fixture
    installs on purpose (`ci_targeted_test_select.py`, `thing.py`) are the
    subject, not a dependency to be repaired.
    """
    pending = sorted(path.name for path in staged.glob("*.py"))
    seen = set(pending)
    while pending:
        current = staged / pending.pop()
        for dependency in _import_time_siblings(current, programs):
            name = f"{dependency}.py"
            if name in seen:
                continue
            seen.add(name)
            shutil.copy2(programs / name, staged / name)
            pending.append(name)


def _git(repo, *args, **kw):
    return _pr.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, **kw)


_BENCHMARK_TEST: dict[str, Path] = {}


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    """A real git repo with the shape `gatekeeper-verify-merge.sh` expects."""
    if shutil.which("git") is None:                       # pragma: no cover
        pytest.skip("no git")
    repo = tmp_path_factory.mktemp("gkverify_repo")
    benchmark_root = tmp_path_factory.mktemp("gkverify_benchmark")
    benchmark_remote = benchmark_root / "benchmark-data.git"
    benchmark_seed = benchmark_root / "seed"
    benchmark_checkout = benchmark_root / "canonical"
    _git(benchmark_root, "init", "-q", "--bare", str(benchmark_remote))
    _git(benchmark_remote, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(benchmark_root, "init", "-q", "-b", "main", str(benchmark_seed))
    _git(benchmark_seed, "config", "user.email", "t@localhost")
    _git(benchmark_seed, "config", "user.name", "t")
    corpus_file = (benchmark_seed /
                   "ic/tiny/v1_openpdkx/phase3/stage3/pnr/routed.def")
    corpus_file.parent.mkdir(parents=True)
    corpus_file.write_text("VERSION 5.8 ;\nEND DESIGN\n")
    _git(benchmark_seed, "add", "-A")
    _git(benchmark_seed, "commit", "-qm", "benchmark fixture")
    _git(benchmark_seed, "remote", "add", "origin", str(benchmark_remote))
    _git(benchmark_seed, "push", "-q", "-u", "origin", "main")
    _git(benchmark_root, "clone", "-q", str(benchmark_remote),
         str(benchmark_checkout))
    _BENCHMARK_TEST.update(
        checkout=benchmark_checkout.resolve(), remote=benchmark_remote.resolve())
    plugin = repo / "vibe-ic-marketplace/plugins/vibe-ic"
    (plugin / "programs/tests").mkdir(parents=True)
    (repo / "tools/ci").mkdir(parents=True)
    # Phase 1's verifier may execute only an exact base-owned judge and process
    # supervisor.  The miniature repository therefore carries those exact
    # infrastructure bytes in its base commit; copying only the subject-facing
    # stub gate would correctly refuse before either arm starts.
    shutil.copy2(_VERIFY, repo / "tools/gatekeeper-verify-merge.sh")
    os.chmod(repo / "tools/gatekeeper-verify-merge.sh", 0o755)
    for name in (
        "benchmark_data_landing_checkout.py",
        "owned_command.py",
        "landing_record_primitives.py",
        "_gate_dispatch.sh",
        "routed_def_corpus.py",
        "trusted_worktree_attest.py",
    ):
        shutil.copy2(_REPO_ROOT / "tools/ci" / name,
                     repo / "tools/ci" / name)
    (repo / "tools/gatekeeper-land.sh").write_text(_STUB_LAND)
    os.chmod(repo / "tools/gatekeeper-land.sh", 0o755)
    (plugin / "programs/ci_targeted_test_select.py").write_text(_STUB_SELECT)
    shutil.copy2(_PROG, plugin / "programs/landing_merge_verdict.py")
    shutil.copy2(_PROGRAMS / "pytest_per_file_junit.py",
                 plugin / "programs/pytest_per_file_junit.py")
    shutil.copy2(_PROGRAMS / "_watchdog.py",
                 plugin / "programs/_watchdog.py")
    # `_progress_run` is imported by trusted-closure members staged below, so
    # the miniature repository has to carry it for the same reason it carries
    # `_watchdog`: a base commit that cannot import its own judge refuses
    # before either arm starts, and the refusal says nothing about the subject.
    shutil.copy2(_PROGRAMS / "_progress_run.py",
                 plugin / "programs/_progress_run.py")
    shutil.copy2(_PROGRAMS / "_pytest_progress_plugin.py",
                 plugin / "programs/_pytest_progress_plugin.py")
    shutil.copy2(_PROGRAMS / "ci_harness_timeout_ceiling_check.py",
                 plugin / "programs/ci_harness_timeout_ceiling_check.py")
    for name in (
        "_atomic_artefact.py",
        "_commercial_pdk.py",
        "_crash_safe_scratch.py",
        "_owned_process_supervisor.py",
        "_semantic_child_progress.py",
        "gate_process_attestation.py",
        "git_prohibition_guard.py",
        "hygiene_finding_delta.py",
        "_corpus_location.py",
        "nda_diff_scan_check.py",
        "_prose_polarity.py",
        "drc_vacuous_pass_check.py",
        "macro_obs_geometry_intersect_check.py",
        "repo_hygiene_parallel.py",
        "step_internal_fail_bubble_up_check.py",
        "step_metrics.py",
        "tool_diagnostic_id_gate.py",
        # The hermetic runner and the landing transition verifier both resolve
        # the EDA image through the plugin's resolver in the BASE runtime
        # (R-0915-96); without it the arm dies on `No module named _eda_pin`.
        "_eda_pin.py",
    ):
        shutil.copy2(_PROGRAMS / name, plugin / "programs" / name)
    # Keep the fixture's deliberately tiny subject-facing stubs, but copy the
    # rest of the exact BASE-owned authority closure generically.  A newly
    # imported authority file must therefore be present before the manifest is
    # written instead of being silently omitted by this test repository.
    for rel in sorted(_VERIFIER_CLOSURE):
        destination = repo / rel
        if destination.exists():
            continue
        source = _REPO_ROOT / rel
        assert source.is_file(), f"fixture authority source is absent: {rel}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    (plugin / "programs/thing.py").write_text(_THING_SRC.format(v=1))
    (plugin / "programs/tests/test_thing.py").write_text(_THING_TEST)
    for rel in _SELECT_CONTROL_TESTS:
        control = plugin / rel
        control.parent.mkdir(parents=True, exist_ok=True)
        control.write_text("def test_fixture_control():\n    assert True\n")
    (plugin / "pytest.ini").write_text("[pytest]\ntestpaths = programs/tests\n")
    (repo / "contended.txt").write_text("base\n")
    # LAST, so it sees every program the lines above staged, stubs included.
    _stage_program_import_closure(plugin / "programs", _PROGRAMS)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@localhost")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")

    # THE NEGATIVE CONTROL. An ordinary source edit; NO test file in the diff.
    # The suite goes red because the value the test pins moved.
    _git(repo, "checkout", "-q", "-b", "innocuous_red")
    (plugin / "programs/thing.py").write_text(_THING_SRC.format(v=2))
    (repo / "notes_red.txt").write_text("a harmless-looking note\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "an innocuous-looking change")

    # THE PAIRED GUARD. Same files, same shape, still green.
    _git(repo, "checkout", "-q", "main")
    _git(repo, "checkout", "-q", "-b", "innocuous_green")
    (plugin / "programs/thing.py").write_text("# a comment\nVALUE = 1\n")
    (repo / "notes_green.txt").write_text("an equally harmless note\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "an equally innocuous change")

    # A CONFLICT against a base that moved under the branch. `contended.txt` is
    # touched by nothing else, so the OTHER branches keep rebasing cleanly.
    _git(repo, "checkout", "-q", "main")
    _git(repo, "checkout", "-q", "-b", "conflicting")
    (repo / "contended.txt").write_text("mine\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "mine")
    _git(repo, "checkout", "-q", "main")
    (repo / "contended.txt").write_text("theirs\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "theirs")

    # Same gate bytes as phase 1; the fixture-only arm switch above models the
    # first candidate whose routed producer is activated under the already
    # trusted verifier/HDF infrastructure.
    _git(repo, "checkout", "-q", "-b", "routed_transition")
    (repo / "routed-transition-note.txt").write_text("activate routed corpus\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "activate routed corpus")
    _git(repo, "checkout", "-q", "main")
    # A new-branch push is measured as `<head> --not --remotes`.  Give the
    # fixture the same already-published main boundary a real clone has, so the
    # push preflight does not accidentally include the synthetic repository's
    # whole history in its question.
    _git(repo, "update-ref", "refs/remotes/origin/main", "main")
    return repo


# ── NORECORD HAS TO REACH THE VERDICT (rlmv) ────────────────────────────────
#
# The 23 end-to-end tests below DRIVE the container engine: they run
# `tools/gatekeeper-verify-merge.sh` for real, and it launches the B1/B2/A1/A2
# arms through `tools/ci/hermetic_candidate_runner.py`. Where there is no engine
# the runner says so, by name, in the verifier's own log:
#
#     [NORECORD] hermetic candidate: cannot execute Docker CLI:
#         [Errno 2] No such file or directory: 'docker'
#     gatekeeper-verify-merge: B1 arm receipt is NORECORD
#
# and the script exits 2. MEASURED on 88a8bcdf4d inside the digest-pinned
# runtime `ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2…`, which carries no Docker
# CLI: 23 failed, 115 passed. Every one of the 23 died on `assert
# r.returncode == 0` or `== 1` — that is, on a disclosure that said "I did not
# measure this" being read as "this code is broken". The gate was already
# honest; nothing downstream could hear it.
#
# `_judgeable` is that missing segment and NOTHING MORE. It is not a
# `which("docker")` guard: see `_hermetic_engine_capability` for why the marker
# alone is refused and why a run that blames an engine this process CAN start
# stays red. Where the engine is reachable this function does nothing at all,
# so the arms run, and a branch that deserves a refusal still gets one.
def _judgeable(*chunks):
    """Skip as NOT_MEASURED — with the cause named — if the arms never ran."""
    status, reason = _CAP.classify("".join(c or "" for c in chunks))
    if status == _CAP.NOT_MEASURED:
        pytest.skip("NOT_MEASURED \u2014 " + reason)


def _verify(repo, ref, tmp_path, *extra, env_extra=None):
    out = tmp_path / f"v_{ref}.json"
    r = _pr.run(
        ["bash", str(_VERIFY), "--ref", ref, "--base", "main",
         "--repo", str(repo), "--no-fetch", "--json", str(out), *extra],
        capture_output=True, text=True, env={**os.environ, "GIT_DIR": "", "GIT_WORK_TREE": "",
             "VIBE_IC_BENCHMARK_DATA": str(_BENCHMARK_TEST["checkout"]),
             "VIBEIC_BENCHMARK_CHECKOUT_TEST_OVERRIDE": "1",
             "VIBEIC_BENCHMARK_CHECKOUT_TEST_ORIGIN":
                 str(_BENCHMARK_TEST["remote"]),
             **(env_extra or {})})
    _judgeable(r.stdout, r.stderr)
    doc = json.loads(out.read_text()) if out.is_file() else None
    return r, doc






_ROUTED_GATE_MARKER = "routed-corpus-gate.enabled"
_ROUTED_ACTIVATION_MARKER = "routed-corpus-producer.activated"
















def test_end_to_end_every_arm_of_both_waves_actually_ran(sandbox, tmp_path):
    """All four arms produce their record. NOT an ordering guard — see below.

    This used to assert `A2.started`/`B1.started`/`B2.started` in a probe
    directory the stub wrote from inside the arm. Since the arms became
    hermetic that could never work: `GATEKEEPER_CONCURRENCY_PROBE_DIR` is not
    on `_LAND_REVIEWED_ENV_NAMES`, so the arm never saw it, and the directory
    is a host path no arm can write to anyway. The probe held exactly the three
    `cleanup.*` files the VERIFIER writes on the host, and nothing else.

    The verdict document already carries per-arm evidence, and the line below
    was already asserting one of them. Use it for all four. This is stronger
    than the marker it replaces: a marker proved an arm STARTED, a record
    proves it COMPLETED.

    NOT GUARDED, and it was not guarded before either: the old name promised
    "B1/B2 finish before A artifacts exist; A1/A2 then run in parallel", but
    marker existence never showed ordering, and the verdict document carries no
    timestamps. Renamed to what is actually asserted rather than leaving a name
    that over-promises. A real ordering guard needs a per-arm completion record
    with times, which `landing_completion_record.py` could carry but does not
    surface to the verdict today.
    """
    r, doc = _verify(sandbox, "innocuous_green", tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


# ── waiting for the verifier by PROGRESS, not by a clock ────────────────────
#
# `proc.communicate(timeout=_T)` asked "has it been 55 seconds", which is a
# different question from "is it still working". This is an END-TO-END verifier
# driving four arms through a hermetic runner, on a host that routinely carries
# other work; a healthy wave outlives any constant somebody picks, and when it
# did, three tests called `pytest.fail("the verifier never finished")` — a red
# about the verifier, manufactured by the load on the machine.
#
# The verifier's own run directory IS the progress signal, and this file already
# relies on that: TMPDIR is pointed at a caller-owned directory, so the
# `mktemp -d -t gkverify.XXXXXX` tree and every arm artefact in it are visible
# under a known name WHILE the run is going. Files appearing, bytes growing and
# mtimes advancing are forward progress. A run that is still writing is never
# killed, however long it legitimately takes. A run that has written nothing for
# the whole grace, with its process still alive, is genuinely wedged — and that
# still FAILS these tests, which is the half that must not move.

class _WhileProgressing:
    """`while watcher.alive():` — the loop condition the watchers below need.

    They used `proc.poll() is None and time.monotonic() < deadline` with the
    same 55 s constant, and that is the SAME defect one level up from the
    handler. On a slow host the watcher gave up while the verifier was still
    producing the very artefacts the test then asserts about, so the assertion
    failed about a run that was working — and it failed with a message about the
    ARTEFACTS, which is the worst version: the reader is pointed at the wave
    ordering when the real answer is that nobody watched long enough.

    Alive means: the process has not exited AND its run tree has moved at some
    point within the grace. A verifier that is producing files is watched for as
    long as it keeps producing them; one that has gone completely quiet with the
    process still up is not watched forever.
    """

    def __init__(self, proc, run_root: Path):
        self._proc = proc
        self._root = run_root
        self._grace = _stall_grace_s()
        self._score = None
        self._moved = time.monotonic()

    def alive(self) -> bool:
        if self._proc.poll() is not None:
            return False
        now = time.monotonic()
        try:
            score = _run_dir_progress(self._root)
        except OSError:
            # A probe that could not read is "no reading", never "no progress":
            # treating an unreadable tree as a stall would kill a healthy run
            # for a reason that is about the prober.
            return True
        if score != self._score:
            self._score = score
            self._moved = now
            return True
        return (now - self._moved) <= self._grace


def _run_dir_progress(run_root: Path) -> float:
    """A monotonic score over the verifier's run tree: file count, total bytes,
    and the newest mtime. Any one of them advancing is progress; none of them
    can advance without the verifier doing something."""
    files = 0
    total = 0.0
    newest = 0.0
    # `os.walk`, not `Path.rglob`. THE TREE IS BEING WRITTEN AND DELETED WHILE
    # THIS WALKS IT — `_first_seen_wave_artefacts` says so in as many words
    # ("cleanup removes the run directory and `publish_validated_arm_artifact`
    # consumes receipts") — and on 3.10 `rglob` raises FileNotFoundError out of
    # its own scandir when a directory vanishes mid-walk. MEASURED: it did,
    # inside the progress probe, and failed the test it was added to protect.
    # `os.walk` ignores such errors by default and returns what it could see.
    #
    # A score that goes DOWN because a directory was removed is still MOVEMENT,
    # which is the right reading: cleanup running is the verifier working.
    try:
        roots = list(run_root.glob("gkverify.*"))
    except OSError:
        return 0.0
    for run in roots:
        for dirpath, _dirs, names in os.walk(run):
            for name in names:
                try:
                    st = os.stat(os.path.join(dirpath, name))
                except OSError:
                    continue
                files += 1
                total += st.st_size
                newest = max(newest, st.st_mtime)
    return float(files) + total + newest


def _stall_grace_s() -> float:
    """Measured on THIS host in THIS session, not hard-coded.

    A grace below the cost of simply LAUNCHING a process is how a supervisor
    kills its child during boot. The floor here is the observed cost of starting
    and reaping a trivial subprocess, scaled generously: the verifier's quietest
    legitimate stretch is a container step producing no file for a while, which
    is many multiples of a bare launch. 30 s is the lower bound so an
    unrealistically fast measurement cannot shrink it to nothing.
    """
    t0 = time.monotonic()
    subprocess.run([sys.executable, "-c", "pass"], capture_output=True)
    launch = time.monotonic() - t0
    return max(30.0, launch * 200.0)


def _finish_by_progress(proc, run_root: Path):
    """(stdout, stderr) once the verifier exits. Fails the test only if it is
    STALLED — no movement in its run tree across the whole grace — never merely
    because it has been slow."""
    meter = _watchdog.ProgressMeter(size_fn=lambda: _run_dir_progress(run_root))
    outcome, _rc = _watchdog.supervise(
        proc, meter.sample, lambda p, _why: p.kill(),
        poll_s=0.5, stall_grace_s=_stall_grace_s(),
        hard_ceiling_s=3600.0)
    stdout, stderr = proc.communicate()
    if outcome != "natural":
        pytest.fail(
            f"the verifier was {outcome}: its run directory did not change at "
            f"all for the whole stall grace, so it was not working — this is "
            f"NOT the same as it having been slow:\n{stdout}\n{stderr}")
    return stdout, stderr


_WAVE_ARTEFACTS = (
    "b1-runner.log", "b2-runner.log",
    "b1-hermetic-receipt.json", "b2-hermetic-receipt.json",
    "base-subject",
    "a1-runner.log", "a2-runner.log",
    "a1-hermetic-receipt.json", "a2-hermetic-receipt.json",
)






def _first_seen_wave_artefacts(proc, run_root, interval=0.02):
    """When each wave artefact FIRST appeared in the verifier's run directory.

    The run directory is `mktemp -d -t gkverify.XXXXXX`, so pointing the
    verifier's TMPDIR at a caller-owned directory makes every arm artefact
    host-visible under a known name while the run is still going.  First-seen
    times are recorded rather than live set membership because cleanup removes
    the run directory and `publish_validated_arm_artifact` consumes receipts:
    a "does it exist now" reading flickers back to False at the end of the run,
    and the ORDER things appeared in is what the wave property is about.
    """
    seen: dict[str, float] = {}
    start = time.monotonic()
    watcher = _WhileProgressing(proc, run_root)
    while watcher.alive():
        runs = sorted(run_root.glob("gkverify.*"))
        if runs:
            for name in _WAVE_ARTEFACTS:
                if name not in seen and (runs[0] / name).exists():
                    seen[name] = round(time.monotonic() - start, 3)
        time.sleep(interval)
    return seen






def test_end_to_end_candidate_wave_precedes_parallel_isolated_base_wave(
        sandbox, tmp_path):
    """B1/B2 finish before A artifacts exist; A1/A2 then run in parallel.

    REWRITTEN AGAINST THIS REPOSITORY'S DESIGN (v1.11.69+). THE PROPERTY IS
    UNCHANGED, word for word; only the vantage point it is observed from has
    moved, and the reason it had to move is the property next door.

    It used to be observed from INSIDE the arms: the stub landing gate wrote
    `<ARM>.started` into `GATEKEEPER_CONCURRENCY_PROBE_DIR`, and the fixture's
    own test file waited for its siblings' markers to appear.  A cross-arm
    rendezvous through a shared host directory is exactly what the hermetic
    launcher exists to make impossible — each arm is a container with
    `network: none` whose only writable surface is a private tmpfs and a
    private evidence volume — and MEASURED on a4caccefe the name is not on the
    launcher's `--env` allow-list either, so inside an arm the variable is
    EMPTY, the stub's branch never fires and no marker is ever written. The
    only thing that directory received was `cleanup.*`, written host-side by
    `cleanup_event`. An arm CANNOT see another arm, by design; asserting the
    wave structure through an inter-arm channel therefore cannot be repaired,
    it can only be moved.

    So it is observed where the parallelism actually lives: the parent shell,
    which launches B1/B2, `wait`s for both, rebuilds the base wave, and only
    then launches A1/A2 and waits for those.  Every arm's runner log is created
    by the launch redirection and every arm's receipt is sealed at its exit, so
    the order those files appear in IS the wave structure, observed from
    outside without asking any arm to cooperate.

    MARGINS, measured on this host: B receipts at 5.2s/7.7s, the base subject
    at 9.3s, the A logs at 10.59s/10.61s, the first A receipt at 12.1s. The
    wave boundary this test asserts has 2.9s of daylight and the A overlap
    window is 1.5s, both sampled every 20ms. A poller that misses a phase
    collapses two first-seen times together and the strict `<` below FAILS —
    the failure mode is loud, not a quiet pass.
    """
    run_root = tmp_path / "verifier-tmp"
    run_root.mkdir()
    out = tmp_path / "wave.json"
    proc = subprocess.Popen(
        ["bash", str(_VERIFY), "--ref", "innocuous_green", "--base", "main",
         "--repo", str(sandbox), "--no-fetch", "--json", str(out)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env={**os.environ, "GIT_DIR": "", "GIT_WORK_TREE": "",
             "TMPDIR": str(run_root),
             "VIBE_IC_BENCHMARK_DATA": str(_BENCHMARK_TEST["checkout"]),
             "VIBEIC_BENCHMARK_CHECKOUT_TEST_OVERRIDE": "1",
             "VIBEIC_BENCHMARK_CHECKOUT_TEST_ORIGIN":
                 str(_BENCHMARK_TEST["remote"])})
    seen = _first_seen_wave_artefacts(proc, run_root)
    stdout, stderr = _finish_by_progress(proc, run_root)
    _judgeable(stdout, stderr)
    doc = json.loads(out.read_text()) if out.is_file() else None

    assert proc.returncode == 0, stdout + stderr
    # NON-VACUITY FIRST. Every arm has to have been WATCHED, or the ordering
    # below is a comparison between two absences. This is the assertion that
    # would have caught the defect this test was blind to for four days: the
    # old body read a probe directory that was never written to, and could
    # only say the markers were missing, never that no arm had ever run.
    missing = [name for name in _WAVE_ARTEFACTS if name not in seen]
    assert not missing, (f"never observed {missing}; the poller saw {seen}")

    # THE CANDIDATE WAVE PRECEDES. No base-wave artefact exists until BOTH
    # candidate receipts are sealed -- the base subject is not even
    # materialized while candidate code is running, which is what makes the
    # base wave isolated from it rather than merely later.
    candidate_wave_done = max(seen["b1-hermetic-receipt.json"],
                              seen["b2-hermetic-receipt.json"])
    base_wave_started = min(seen["base-subject"], seen["a1-runner.log"],
                            seen["a2-runner.log"])
    assert candidate_wave_done < base_wave_started, seen

    # THE BASE WAVE IS PARALLEL. Both A arms are launched before either has
    # sealed a receipt, so they were in flight at the same time.
    assert max(seen["a1-runner.log"], seen["a2-runner.log"]) < min(
        seen["a1-hermetic-receipt.json"],
        seen["a2-hermetic-receipt.json"]), seen
    # ... and so was the candidate wave, which is the same launch shape one
    # wave earlier and is why the base wave is not simply the whole run.
    assert max(seen["b1-runner.log"], seen["b2-runner.log"]) < min(
        seen["b1-hermetic-receipt.json"],
        seen["b2-hermetic-receipt.json"]), seen


# Every A-only artefact `clear_base_wave_artifacts` names, in its own words.
_BASE_WAVE_ARTEFACTS = (
    "base.xml",
    "base_hygiene.json",
    "base_land.log",
    "base_tests.log",
    "base_hygiene_progress.jsonl",
    "selection_base.txt",
    "selection_base.after",
)
_FORGED = b"candidate planted this base artefact\n"


def test_end_to_end_candidate_cannot_prewrite_base_wave_artifacts(
        sandbox, tmp_path):
    """PROPERTY (unchanged): a candidate cannot pre-write the base wave's
    artefacts and have them counted as base evidence.

    REWRITTEN, AND THIS ONE WAS GREEN — WHICH IS WORSE THAN RED. It set
    `GATEKEEPER_PREWRITE_BASE_ARTIFACTS=1` and asserted that a planted line was
    absent from the output. MEASURED on a4caccefe, TWO independent reasons that
    assertion could never have failed:

      1. the name occurs ZERO times in `tools/gatekeeper-verify-merge.sh` and
         is not on the hermetic launcher's `--env` allow-list, so inside an arm
         the switch is EMPTY and the stub's branch never runs; and
      2. even if it ran, the branch writes to
         `$(dirname "$GATEKEEPER_BENCHMARK_MEASUREMENT_RECORD")`, and that name
         occurs ZERO times in the verifier AND ZERO times in the real
         `tools/gatekeeper-land.sh` — so inside the arm it expands to `.`, the
         container's read-only `/subject`. The candidate cannot NAME the
         parent's run directory, let alone write in it.

    Two layers of prevention, and the test was reading the absence of a line
    nobody had tried to print. "Unchanged" and "nobody tried" are the same
    bytes; this one had been the second for four days while reading as the
    first.

    SO WHAT DOES MAIN ACTUALLY DO, and what can still be observed? Prevention
    is layer one and is asserted by the measurement above rather than by a
    stimulus that cannot exist. Layer two is `clear_base_wave_artifacts`, which
    deletes every A-only artefact after both candidate process groups reach a
    terminal census and before the base wave is prepared -- its own comment
    says the names are "discoverable from the measurement-record path handed to
    B2", i.e. it is written for a candidate that DOES somehow get a path. That
    layer is testable, so this test drives it: the artefacts are planted from
    the host, in the parent's own run directory, while the candidate wave is in
    flight, and the base wave must start with not one of those bytes left.

    One of them is planted as a DIRECTORY where a file belongs, which is what
    the old stub did too: `rm -f` cannot remove that, `rm -rf` can, and the
    difference between those two is a mutation somebody could make.
    """
    run_root = tmp_path / "verifier-tmp"
    run_root.mkdir(parents=True)
    out = tmp_path / "verdict.json"
    proc = subprocess.Popen(
        ["bash", str(_VERIFY), "--ref", "innocuous_green", "--base", "main",
         "--repo", str(sandbox), "--no-fetch", "--json", str(out)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env={**os.environ, "GIT_DIR": "", "GIT_WORK_TREE": "",
             "TMPDIR": str(run_root),
             "VIBE_IC_BENCHMARK_DATA": str(_BENCHMARK_TEST["checkout"]),
             "VIBEIC_BENCHMARK_CHECKOUT_TEST_OVERRIDE": "1",
             "VIBEIC_BENCHMARK_CHECKOUT_TEST_ORIGIN":
                 str(_BENCHMARK_TEST["remote"])})

    planted: list[str] = []
    survivors: list[str] | None = None
    watcher = _WhileProgressing(proc, run_root)
    while watcher.alive():
        runs = sorted(run_root.glob("gkverify.*"))
        if not runs:
            time.sleep(0.02)
            continue
        run = runs[0]
        if not planted and (run / "b1-runner.log").exists():
            for name in _BASE_WAVE_ARTEFACTS:
                path = run / name
                if path.is_dir():
                    shutil.rmtree(path)
                elif path.exists() or path.is_symlink():
                    path.unlink()
                if name == "base_hygiene_progress.jsonl":
                    path.mkdir()
                    (path / "forged").write_bytes(_FORGED)
                else:
                    path.write_bytes(_FORGED)
                planted.append(name)
            # NON-VACUITY: the forgery is READ BACK before anything is claimed
            # about its removal, so "no forged byte survives" cannot be
            # satisfied by never having written one.
            assert sorted(_leaked_forgeries(run)) == sorted(planted), (
                "the plant did not take")
        if planted and (run / "a1-runner.log").exists():
            survivors = _leaked_forgeries(run)
            break
        time.sleep(0.02)
    stdout, stderr = _finish_by_progress(proc, run_root)
    _judgeable(stdout, stderr)
    doc = json.loads(out.read_text()) if out.is_file() else None

    assert planted == list(_BASE_WAVE_ARTEFACTS), (
        f"the candidate wave was never observed; planted {planted}")
    assert survivors is not None, "the base wave never started"
    # THE PROPERTY. Not one candidate-written byte is present in the parent's
    # run directory when the base wave begins.
    assert survivors == [], survivors

    assert proc.returncode == 0, stdout + stderr
    assert "candidate planted this base" not in stdout


def _leaked_forgeries(run):
    """Top-level run-directory entries still carrying the planted bytes."""
    found = []
    for path in sorted(run.iterdir()):
        try:
            if path.is_dir():
                if path.name in _BASE_WAVE_ARTEFACTS:
                    found.append(path.name)
                continue
            if path.is_file() and _FORGED in path.read_bytes():
                found.append(path.name)
        except OSError:                                   # pragma: no cover
            continue
    return found












def test_end_to_end_the_caller_checkout_is_never_touched(sandbox, tmp_path):
    """It rebases in a THROWAWAY worktree. A gate that mutates the operator's
    checkout to answer a question is a gate that gets turned off."""
    before = _git(sandbox, "rev-parse", "HEAD").stdout.strip()
    status = _git(sandbox, "status", "--porcelain").stdout
    _verify(sandbox, "innocuous_green", tmp_path)
    assert _git(sandbox, "rev-parse", "HEAD").stdout.strip() == before
    assert _git(sandbox, "status", "--porcelain").stdout == status
    assert _git(sandbox, "worktree", "list").stdout.count("\n") == 1


def _assert_interruption_cleans_every_parallel_arm(
        sandbox, tmp_path, hung_arm, pid_only_term):
    """Parallel speed must not trade an interrupt for leaked gate processes.

    A private clone's selected arm deliberately ignores TERM forever.  Both a
    process-group SIGINT and the common PID-only SIGTERM service-stop path must
    run bounded cleanup, escalate every dedicated group to KILL, reap it, and
    remove all four temporary worktrees.
    """
    repo = tmp_path / "interrupt-repo"
    cloned = _pr.run(
        ["git", "clone", "-q", str(sandbox), str(repo)],
        capture_output=True, text=True)
    assert cloned.returncode == 0, cloned.stderr
    _git(repo, "config", "user.email", "t@localhost")
    _git(repo, "config", "user.name", "t")
    _git(repo, "checkout", "-q", "main")

    land = repo / "tools/gatekeeper-land.sh"
    text = land.read_text()
    needle = 'echo "=== gatekeeper landing gates — base=${GATEKEEPER_BASE:-origin/main} ==="\n'
    # KEYED ONLY ON `GATEKEEPER_VERIFY_ARM`, and that is the whole repair. This
    # block used to require `GATEKEEPER_CONCURRENCY_PROBE_DIR` as well, and to
    # announce itself by writing `<ARM>.pid` into it. MEASURED on a4caccefe: the
    # hermetic launcher forwards an explicit `--env` allow-list and that name is
    # not on it, so inside the arm the variable is EMPTY, the branch never
    # fired, nothing ever hung, and this test failed waiting for a pid file that
    # could not be written. `GATEKEEPER_VERIFY_ARM` IS forwarded, so keying on
    # it alone makes the arm hang for real under this repository's design.
    hang = r'''if [ "${GATEKEEPER_VERIFY_ARM:-}" = "__HUNG_ARM__" ]; then
  trap '' TERM
  while :; do sleep 30; done
fi
'''.replace("__HUNG_ARM__", hung_arm)
    assert needle in text
    land.write_text(text.replace(needle, hang + needle))
    _git(repo, "add", "tools/gatekeeper-land.sh")
    assert _git(repo, "commit", "-qm", "make interrupt control").returncode == 0
    _git(repo, "checkout", "-q", "-b", "probe")
    (repo / "probe.txt").write_text("candidate\n")
    _git(repo, "add", "probe.txt")
    assert _git(repo, "commit", "-qm", "candidate").returncode == 0

    probe = tmp_path / "interrupt-probe"
    out = tmp_path / "interrupt.json"
    proc = subprocess.Popen(
        ["bash", str(_VERIFY), "--ref", "probe", "--base", "main",
         "--repo", str(repo), "--no-fetch", "--json", str(out)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        start_new_session=True,
        # The same hermetic benchmark-data checkout `_verify` publishes. Without
        # it the script falls back to `$HOME/_matrix_benchmark_data` — a host
        # path this suite neither creates nor owns — so on any machine that does
        # not happen to have the gatekeeper's canonical corpus checked out, the
        # run died at "benchmark-data canonical checkout produced NORECORD"
        # before either arm existed, and the test read that as "the arm never
        # started".
        env={**os.environ, "GIT_DIR": "", "GIT_WORK_TREE": "",
             "GATEKEEPER_CONCURRENCY_PROBE_DIR": str(probe),
             "VIBE_IC_BENCHMARK_DATA": str(_BENCHMARK_TEST["checkout"]),
             "VIBEIC_BENCHMARK_CHECKOUT_TEST_OVERRIDE": "1",
             "VIBEIC_BENCHMARK_CHECKOUT_TEST_ORIGIN":
                 str(_BENCHMARK_TEST["remote"])},
    )
    # WAIT FOR THE ARM PHASE THE WAY THE HOST CAN SEE IT. This used to wait for
    # `probe / f"{hung_arm}.pid"`, and that file can never appear:
    # GATEKEEPER_CONCURRENCY_PROBE_DIR is not on the hermetic launcher's
    # `--env` allow-list, so inside the arm the variable is EMPTY and nothing
    # writes there. The arm cannot signal out -- that is the point of the
    # containment -- so what is polled is the verifier's own worktrees
    # appearing in the subject repository, which is host-side and is what
    # "the arms are set up and running" looks like from outside.
    # Wait on the same suite ceiling the cleanup wait below uses. The old bound
    # here was a 12s wall-clock estimate, which the verifier outlives on a cold
    # cache purely by doing its honest work.
    def _arms_are_up():
        return _git(repo, "worktree", "list").stdout.count("\n") > 1

    deadline = time.monotonic() + _T
    while time.monotonic() < deadline and not _arms_are_up():
        if proc.poll() is not None:
            break
        time.sleep(0.05)
    if not _arms_are_up():
        # NEVER evaluate the diagnosis inside the assert message. Against a
        # verifier that is still running, `proc.communicate(timeout=2)` raises
        # TimeoutExpired, and that exception REPLACES the AssertionError: the
        # failure then reads "timed out after 2 seconds", which points at the
        # verifier as the thing that hung. That is the exact inverse of the
        # common case, where the verifier ran to completion and it is the
        # CONTROL ARM that never existed. It also leaks the verifier, because
        # nothing ever reaps it. Settle the process first, then report which of
        # the two distinguishable things actually happened.
        still_running = proc.poll() is None
        # The host's load is read HERE, at the ceiling, before the kill below
        # changes what the host is doing (R-0929-ENV-AT-RUNTIME).
        at_ceiling = states.run_conditions()
        if still_running:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        stdout, stderr = proc.communicate()
        if still_running:
            why = (f"the verifier was still running after {_T}s and no "
                   f"verifier worktree ever appeared in the subject "
                   f"repository, so the {hung_arm} control arm never started")
            # THIS branch is the suite ceiling, a wall clock, and nothing at it
            # shows where the verifier is (no worktree, no event): slow and
            # wedged look the same from here. So it is NOT_MEASURED only when
            # the host was MEASURABLY loaded at the ceiling -- never for the
            # xdist worker count alone -- and on a quiet host it is the FAIL
            # below, serial or parallel. The EXITED branch is never a clock.
            states.skip_if_not_measurable(
                why, progress=states.PROGRESS_UNOBSERVABLE,
                conditions=at_ceiling)
        else:
            why = (f"the verifier EXITED rc={proc.returncode} without ever "
                   f"running the {hung_arm} control arm: the injected hang was "
                   f"unreachable, so this test measured NOTHING about "
                   f"interrupt cleanup")
        pytest.fail(f"{why}\n=== verifier stdout ===\n{stdout}\n"
                    f"=== verifier stderr ===\n{stderr}")
    if pid_only_term:
        os.kill(proc.pid, signal.SIGTERM)
    else:
        os.killpg(proc.pid, signal.SIGINT)
    # WHAT THE VERIFIER HAD BUILT WHEN THE INTERRUPT LANDED, read right after
    # it. Bash runs a trapped signal once the command in flight returns, and
    # that one command can register at most one more worktree; every later
    # worktree is a later COMMAND, i.e. the script went on as if never
    # interrupted. That is the progress evidence the ceiling branch below needs
    # (R-0929-ENV-AT-RUNTIME): it tells a verifier still inside its step from
    # one that ignored the signal.
    def _worktree_paths():
        out = _git(repo, "worktree", "list", "--porcelain").stdout
        return {line[len("worktree "):] for line in out.splitlines()
                if line.startswith("worktree ")}

    worktrees_at_signal = _worktree_paths()
    # Wait on the cleanup protocol, not on a wall-clock estimate of how fast a
    # loaded host can remove four worktrees.  `_T` is only the suite's final
    # dead-process safety ceiling; the success path is the atomic `done` event.
    cleanup_started = probe / "cleanup.started"
    cleanup_reaped = probe / "cleanup.reaped"
    cleanup_done = probe / "cleanup.done"
    deadline = time.monotonic() + _T
    while time.monotonic() < deadline and not cleanup_done.is_file():
        if proc.poll() is not None:
            break
        time.sleep(0.05)
    if not cleanup_done.is_file():
        # FOUR different things end the wait above, and they used to share one
        # message:
        #   * the verifier EXITED without the event -- a behaviour, always FAIL;
        #   * it was still running at the `_T` ceiling AFTER `cleanup.started`
        #     -- cleanup began and never reached `reaped`/`done`. That IS the
        #     never-reaped arm this deadline exists to catch, and the events
        #     are the progress evidence: cleanup was seen to start and then do
        #     nothing observable. A hang, FAIL on any host at any load.
        #     (Reverse mutation M9b -- cleanup() blocks right after
        #     `cleanup_event started` -- read NOT_MEASURED at -n 2 on a host at
        #     0.14 load per core while this branch keyed on the worker count.)
        #   * it was still running at the ceiling and cleanup NEVER STARTED,
        #     yet it had created later worktrees after the signal: it IGNORED
        #     the interrupt and carried on -- a behaviour, FAIL at any load;
        #   * it was still running, cleanup never started, and no later step
        #     had begun: the interrupt was still deferred behind the step in
        #     flight (bash runs a trapped signal only once that child
        #     returns). Nothing here tells slow from wedged, so this one branch
        #     is NOT_MEASURED when the host was MEASURABLY loaded at the
        #     ceiling (R-0929-ENV-AT-RUNTIME), and a FAIL on a quiet host.
        still_running = proc.poll() is None
        # Read at the ceiling, before the kill below changes the host or lets
        # a late event land: the verdict is about what was true AT `_T`.
        at_ceiling = states.run_conditions()
        started = cleanup_started.is_file()
        reaped = cleanup_reaped.is_file()
        after_signal = sorted(_worktree_paths() - worktrees_at_signal)
        # A failed cleanup test must clean up its own control process; leaving
        # the intentionally TERM-ignoring arm behind would contaminate every
        # later timing measurement in the same suite.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = proc.communicate()
        if still_running and started:
            stuck = ("removing the worktrees never finished (cleanup.reaped "
                     "present, cleanup.done absent)" if reaped else
                     "an arm process group was never reaped (cleanup.started "
                     "present, cleanup.reaped absent)")
            pytest.fail(
                f"cleanup STARTED and the verifier was still running at the "
                f"suite safety ceiling ({_T}s): {stuck} -- a hang, not a slow "
                f"host:\n{stdout}\n{stderr}")
        if still_running and len(after_signal) >= 2:
            # MEASURED 2026-09-29 on 8HD-6 (process tree at the ceiling): the
            # verifier was not inside any step -- bash sat in `wait` on the
            # hung base arm, which it had LAUNCHED ~25 s after the SIGINT, the
            # whole candidate wave having run in between. A lost interrupt is
            # the behaviour under test failing, not a slow host.
            pytest.fail(
                f"the verifier IGNORED the interrupt: cleanup never started, "
                f"and {len(after_signal)} worktree(s) were created AFTER the "
                f"signal ({', '.join(Path(w).name for w in after_signal)}), so "
                f"the script went on as if never interrupted -- a behaviour, "
                f"not a slow host:\n{stdout}\n{stderr}")
        if still_running:
            why = (f"verifier still running at the suite safety ceiling "
                   f"({_T}s) and cleanup never STARTED (no cleanup.started), "
                   f"with no later step begun after the signal: the interrupt "
                   f"was still deferred behind the step in flight")
            states.skip_if_not_measurable(
                why, progress=states.PROGRESS_UNOBSERVABLE,
                conditions=at_ceiling)
            pytest.fail(f"{why}:\n{stdout}\n{stderr}")
        pytest.fail(
            f"verifier exited rc={proc.returncode} without the cleanup.done "
            f"event:\n{stdout}\n{stderr}")
    stdout, stderr = proc.communicate()
    assert proc.returncode != 0, stdout + stderr
    assert cleanup_started.is_file(), "cleanup never announced its start"
    assert cleanup_reaped.is_file(), "cleanup did not reap its process groups"
    assert _git(repo, "worktree", "list").stdout.count("\n") == 1
    # `cleanup.reaped` IS the proof that the TERM-ignoring arm died, and it is a
    # stronger one than polling a pid the arm had to publish for itself: the
    # parent writes that event only after WAITING on every arm process group it
    # started. An arm that ignored TERM and was never escalated would leave that
    # wait outstanding for ever, the event would never appear, and this test
    # fails on the deadline above rather than passing quietly.


def test_interruption_kills_a_term_ignoring_parallel_arm_and_removes_worktrees(
        sandbox, tmp_path):
    """Keep the original A2/SIGINT nodeid stable across the differential."""
    _assert_interruption_cleans_every_parallel_arm(
        sandbox, tmp_path, "A2", False)


def test_pid_only_term_kills_a_term_ignoring_b2_and_removes_worktrees(
        sandbox, tmp_path):
    """The service-stop path also owns the newly independent B2 group."""
    _assert_interruption_cleans_every_parallel_arm(
        sandbox, tmp_path, "B2", True)


def _reassert(sandbox, path, head=None):
    doc = json.loads(path.read_text())
    head = head or doc["head_sha"]
    return _pr.run(
        ["bash", str(_VERIFY), "--reassert", str(path), "--base", "main",
         "--reassert-head", head, "--repo", str(sandbox), "--no-fetch"],
        capture_output=True, text=True)


def _clone_for_reassert(sandbox, tmp_path):
    repo = tmp_path / "reassert-repo"
    cloned = _pr.run(["git", "clone", "-q", str(sandbox), str(repo)],
                     capture_output=True, text=True)
    assert cloned.returncode == 0, cloned.stderr
    _git(repo, "config", "user.email", "t@localhost")
    _git(repo, "config", "user.name", "t")
    _git(repo, "checkout", "-q", "main")
    return repo


def _advance_main(repo, rel, content):
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    _git(repo, "add", "--", rel)
    assert _git(repo, "commit", "-qm", f"advance {rel}").returncode == 0


def _write_reassert_receipt(repo, path, verdict="LAND_OK"):
    dependency = ("vibe-ic-marketplace/plugins/vibe-ic/"
                  "programs/tests/test_thing.py")
    doc = {
        "receipt_schema": "vibeic.landing-acceptance.v1",
        "verdict": verdict,
        "base_sha": _git(repo, "rev-parse", "main").stdout.strip(),
        "head_sha": _git(repo, "rev-parse", "innocuous_green").stdout.strip(),
        "selected_files": [dependency],
        "base_selected_files": [dependency],
        "gate_edited": [],
    }
    doc["receipt_sha256"] = hashlib.sha256(json.dumps(
        doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    path.write_text(json.dumps(doc))
    return doc


def test_reassert_reuses_unchanged_receipt_without_rerun(sandbox, tmp_path):
    good = tmp_path / "v_innocuous_green.json"
    _write_reassert_receipt(sandbox, good)
    reused = _reassert(sandbox, good)
    assert reused.returncode == 0, reused.stdout + reused.stderr
    assert "REASSERT: REUSED" in reused.stdout
    assert "rerun" not in reused.stderr.lower()


def test_reassert_reuses_receipt_after_unrelated_base_landing(sandbox, tmp_path):
    good = tmp_path / "v_innocuous_green.json"
    _write_reassert_receipt(sandbox, good)
    repo = _clone_for_reassert(sandbox, tmp_path)
    _advance_main(repo, "unrelated-owner.txt", "independent landing\n")
    reused = _reassert(repo, good)
    assert reused.returncode == 0, reused.stdout + reused.stderr
    assert "only through unrelated paths" in reused.stdout


def test_reassert_changed_candidate_input_requests_bounded_revalidation(
        sandbox, tmp_path):
    good = tmp_path / "v_innocuous_green.json"
    _write_reassert_receipt(sandbox, good)
    repo = _clone_for_reassert(sandbox, tmp_path)
    _advance_main(repo, "notes_green.txt", "main changed candidate bytes\n")
    changed = _reassert(repo, good)
    assert changed.returncode == 1, changed.stdout + changed.stderr
    assert "REASSERT: REVALIDATE" in changed.stderr
    assert "notes_green.txt\tcandidate-bytes" in changed.stderr
    assert "full verify" not in changed.stderr.lower()


@pytest.mark.parametrize("selection_namespace", ["repo", "plugin"])
def test_reassert_changed_named_dependency_blocks_reuse(sandbox, tmp_path, selection_namespace):
    good = tmp_path / "v_innocuous_green.json"
    doc = _write_reassert_receipt(sandbox, good)
    assert doc["base_selected_files"]
    repo = _clone_for_reassert(sandbox, tmp_path)
    dependency = doc["base_selected_files"][0]
    if selection_namespace == "plugin":
        # The real verdict producer stores pytest selection paths relative to
        # the plugin root; git diff reports them relative to the repository.
        prefix = "vibe-ic-marketplace/plugins/vibe-ic/"
        doc["selected_files"] = [dependency.removeprefix(prefix)]
        doc["base_selected_files"] = [dependency.removeprefix(prefix)]
        doc.pop("receipt_sha256")
        doc["receipt_sha256"] = hashlib.sha256(json.dumps(
            doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        good.write_text(json.dumps(doc))
    _advance_main(repo, dependency, "def test_changed_dependency():\n    assert True\n")
    changed = _reassert(repo, good)
    assert changed.returncode == 1, changed.stdout + changed.stderr
    assert "named-evidence/dependency" in changed.stderr
    assert dependency in changed.stderr


def test_reassert_rejects_tampered_or_mismatched_receipt(sandbox, tmp_path):
    good = tmp_path / "v_innocuous_green.json"
    doc = _write_reassert_receipt(sandbox, good)

    tampered = tmp_path / "tampered.json"
    doc["selected_files"].append("forged.py")
    tampered.write_text(json.dumps(doc))
    refused = _reassert(sandbox, tampered)
    assert refused.returncode == 2, refused.stdout + refused.stderr
    assert "receipt digest mismatch" in refused.stderr

    mismatch = _reassert(sandbox, good, head="main")
    assert mismatch.returncode == 2, mismatch.stdout + mismatch.stderr
    assert "candidate head mismatch" in mismatch.stderr


def test_reassert_refuses_a_record_that_was_not_a_pass(sandbox, tmp_path):
    receipt = tmp_path / "v_innocuous_red.json"
    doc = _write_reassert_receipt(sandbox, receipt, verdict="REFUSE")
    bad = _reassert(sandbox, receipt,
                    head=doc["head_sha"])
    assert bad.returncode == 1, bad.stdout + bad.stderr
    assert "not LAND_OK" in bad.stderr




# ================================================ THE TWO VERIFICATION TIERS
#
# `git merge-tree --write-tree` needs git >= 2.38. FOUR OF SIX HOSTS in this
# fleet run 2.34.1, INCLUDING the orchestrator where every `gh pr merge` is run,
# and on those the strong path never starts: `--write-tree` is read as a rev
# (`fatal: unknown rev --write-tree`), so the tree came back empty and the gate
# refused EVERY landing with THE MERGE TREE COULD NOT BE COMPUTED. Fail-closed
# and correct; a ban rather than a check.
#
# The fallback verifies the REBASE REPLAY and DISCLOSES that the squash-vs-rebase
# cross-check was not performed. What these tests refuse:
#
#   * a fallback that passes everything — worse than a gate that refuses
#     everything, so the negative control is re-run UNDER THE FALLBACK;
#   * a fallback that is disclosed only in prose — a downstream that cannot key
#     on the tier cannot act on the weakness;
#   * a fallback that is only exercised where it is needed. Forcing it with
#     `GATEKEEPER_FORCE_REBASE_REPLAY=1` runs this branch on EVERY host, so the
#     untested path is removed rather than moved;
#   * a tier that can change an answer rather than only report what it checked.


_FALLBACK = {"GATEKEEPER_FORCE_REBASE_REPLAY": "1"}




# ------------------------------------------------- the decision, both tiers














# ------------------------------------------------------ the record, both tiers








# ------------------------------------------- the detection, on THIS host






# ------------------------------- THE PAIRED GUARD, end to end, UNDER THE FALLBACK









# Actual one-shot receipt consumer; no acceptance arm/forge/network in fixtures.
@pytest.fixture()
def ready_service(tmp_path):
    import os
    import shutil
    root = tmp_path / "ready-repo"
    root.mkdir()
    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()
    git("init", "-q", "-b", "main")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "test")
    (root / "tools").mkdir()
    verifier = _VERIFY
    shutil.copyfile(verifier, root / "tools/gatekeeper-verify-merge.sh")
    (root / "dependency.py").write_text("initial dependency\n")
    git("add", "."); git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    git("checkout", "-qb", "candidate")
    (root / "feature.py").write_text("candidate\n")
    git("add", "."); git("commit", "-qm", "candidate")
    head = git("rev-parse", "HEAD")
    git("checkout", "-q", "main")
    receipt = tmp_path / "accepted.json"
    doc = {"receipt_schema": "vibeic.landing-acceptance.v1", "verdict": "LAND_OK",
           "base_sha": base, "head_sha": head,
           "selected_files": ["dependency.py"], "base_selected_files": [], "gate_edited": []}
    doc["receipt_sha256"] = hashlib.sha256(json.dumps(
        doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    receipt.write_text(json.dumps(doc))
    entry = {"id": "ready", "head": head, "receipt": str(receipt),
             "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest()}
    manifest = tmp_path / "admission.json"
    final_marker = tmp_path / "final.json"
    program = _service_program()
    final = [sys.executable, "-c", "import os,json,pathlib; pathlib.Path(" + repr(str(final_marker))
             + ").write_text(json.dumps({'id':os.environ['GATEKEEPER_READY_ID'],"
               "'head':os.environ['GATEKEEPER_READY_HEAD']}))"]
    def run(entries=None, writer="root", final_command=None, base="main"):
        manifest.write_text(json.dumps({"writer": "root", "candidates": entries or [entry]}))
        result = subprocess.run([sys.executable, str(program), "--service-ready", str(manifest),
            "--repo", str(root), "--base", base, "--writer", writer,
            "--final-command", *(final if final_command is None else final_command)],
            capture_output=True, text=True)
        return result, json.loads(result.stdout)
    return root, git, entry, receipt, run, final_marker


def test_ready_service_skips_unrelated_conflict_and_reuses_without_acceptance(ready_service):
    root, git, entry, receipt, run, marker = ready_service
    first = dict(entry, id="earlier", shared_conflicts=["other live source owner"], number=1)
    entry.update(number=999, mergeable="UNKNOWN", author="another-owner", waited_days=30)
    rc, result = run([first, entry])
    assert rc.returncode == 0 and result["id"] == "ready"
    assert result["receipt_reused"] is True and result["impacted_checks"] == []
    assert json.loads(marker.read_text())["head"] == entry["head"]
    assert result["refused"][0]["id"] == "earlier"


def test_ready_service_unrelated_base_movement_does_not_rerun(ready_service):
    root, git, entry, receipt, run, marker = ready_service
    (root / "unrelated.txt").write_text("independent landing")
    git("add", "."); git("commit", "-qm", "unrelated")
    rc, result = run()
    assert rc.returncode == 0 and result["receipt_reused"] is True
    assert result["affected_paths"] == [] and result["impacted_checks"] == []


def test_ready_service_named_dependency_runs_only_impacted_check_outside_lock(ready_service):
    root, git, entry, receipt, run, marker = ready_service
    (root / "dependency.py").write_text("changed dependency\n")
    git("add", "."); git("commit", "-qm", "dependency")
    impacted = root.parent / "impacted"
    check = [sys.executable, "-c", "import fcntl,pathlib; "
             "f=open('.git/gatekeeper-final.lock','a'); "
             "fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB); "
             "pathlib.Path(" + repr(str(impacted)) + ").write_text('measured')"]
    entry["checks"] = {"dependency.py": [{"id": "dependency-consumer", "argv": check}],
                       "unrelated.txt": [{"id": "must-not-run", "argv": ["false"]}]}
    rc, result = run()
    assert rc.returncode == 0 and impacted.read_text() == "measured"
    assert result["impacted_checks"] == ["dependency-consumer"]
    assert result["affected_paths"] == ["dependency.py"]


@pytest.mark.parametrize("kind", ["missing", "tampered", "forged-resealed", "head-mismatch"])
def test_ready_service_invalid_receipt_refuses_without_final_write(ready_service, kind):
    root, git, entry, receipt, run, marker = ready_service
    if kind == "missing":
        receipt.unlink()
    elif kind == "head-mismatch":
        entry["head"] = "main"
    else:
        doc = json.loads(receipt.read_text())
        doc["selected_files"] = []
        if kind == "forged-resealed":
            doc.pop("receipt_sha256")
            doc["receipt_sha256"] = hashlib.sha256(json.dumps(
                doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        receipt.write_text(json.dumps(doc))
    rc, result = run()
    assert rc.returncode != 0 and result["status"] == "BLOCKED_NO_ACCEPTED_CANDIDATE"
    assert not marker.exists()


@pytest.mark.parametrize("blocker", ["holds", "shared_conflicts", "failed_gates", "dependencies"])
def test_ready_service_real_hold_dependency_or_shared_owner_still_blocks(ready_service, blocker):
    root, git, entry, receipt, run, marker = ready_service
    entry[blocker] = [entry["head"] if blocker == "dependencies" else "named actual blocker"]
    rc, result = run()
    assert rc.returncode != 0 and not marker.exists()
    assert result["status"] == "BLOCKED_NO_ACCEPTED_CANDIDATE"


def test_ready_service_missing_impacted_check_refuses_no_broad_fallback(ready_service):
    root, git, entry, receipt, run, marker = ready_service
    (root / "dependency.py").write_text("changed\n")
    git("add", "."); git("commit", "-qm", "dependency")
    rc, result = run()
    assert rc.returncode != 0 and not marker.exists()
    assert "no impacted check" in result["refused"][0]["reason"]


def test_ready_service_enforces_writer_and_short_serial_final_lock(ready_service):
    import fcntl
    root, git, entry, receipt, run, marker = ready_service
    rc, result = run(writer="source-prep")
    assert rc.returncode != 0 and result["status"] == "BLOCKED_ADMISSION_INPUT"
    with (root / ".git/gatekeeper-final.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        rc, result = run()
        assert rc.returncode != 0 and result["status"] == "BLOCKED_SOLE_WRITER_LOCK"
        assert not marker.exists()
    rc, result = run()
    assert rc.returncode == 0 and marker.exists()


def test_ready_service_prefers_reusable_receipt_before_unrelated_impacted_checks(ready_service):
    root, git, entry, receipt, run, marker = ready_service
    (root / "dependency.py").write_text("changed named input\n")
    git("add", "."); git("commit", "-qm", "changed input")
    current_base = git("rev-parse", "HEAD")
    impacted = root.parent / "earlier-impacted-marker"
    candidate_a = dict(entry, id="A", checks={"dependency.py": [{
        "id": "A-impacted", "argv": [sys.executable, "-c",
        "import pathlib; pathlib.Path(" + repr(str(impacted)) + ").write_text('ran')"]}]})
    git("checkout", "-qb", "independent")
    (root / "independent.py").write_text("independent candidate\n")
    git("add", "."); git("commit", "-qm", "independent candidate")
    independent_head = git("rev-parse", "HEAD")
    git("checkout", "-q", "main")
    doc = json.loads(receipt.read_text())
    doc.update(base_sha=current_base, head_sha=independent_head)
    doc.pop("receipt_sha256")
    doc["receipt_sha256"] = hashlib.sha256(json.dumps(
        doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    independent_receipt = root.parent / "independent-accepted.json"
    independent_receipt.write_text(json.dumps(doc))
    candidate_b = {"id": "B", "head": independent_head,
                   "receipt": str(independent_receipt),
                   "receipt_sha256": hashlib.sha256(independent_receipt.read_bytes()).hexdigest()}
    rc, result = run([candidate_a, candidate_b])
    assert rc.returncode == 0 and result["id"] == "B"
    assert result["receipt_reused"] is True and result["impacted_checks"] == []
    assert json.loads(marker.read_text())["head"] == independent_head
    assert not impacted.exists()


def _fake_gh(tmp_path, monkeypatch, *, number, head, base="main",
             base_oid=None, final_state="MERGED"):
    calls = tmp_path / "gh-calls.jsonl"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text("""#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
record = pathlib.Path(os.environ['FAKE_GH_CALLS'])
prior = record.read_text().splitlines() if record.exists() else []
with record.open('a') as stream:
    stream.write(json.dumps(args) + '\\n')
if args[:2] == ['pr', 'view']:
    merged = any(json.loads(line)[:2] == ['pr', 'merge'] for line in prior)
    state = os.environ['FAKE_GH_FINAL_STATE'] if merged else 'OPEN'
    print(json.dumps({'number': int(os.environ['FAKE_GH_NUMBER']),
                      'headRefOid': os.environ['FAKE_GH_HEAD'],
                      'baseRefName': os.environ['FAKE_GH_BASE'],
                      'baseRefOid': os.environ['FAKE_GH_BASE_OID'],
                      'isDraft': False, 'state': state,
                      'mergeCommit': {'oid': os.environ['FAKE_GH_MERGE_OID']}
                                     if state == 'MERGED' else None}))
    raise SystemExit(0)
if args[:2] == ['pr', 'merge']:
    raise SystemExit(0)
raise SystemExit(2)
""")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("FAKE_GH_CALLS", str(calls))
    monkeypatch.setenv("FAKE_GH_NUMBER", str(number))
    monkeypatch.setenv("FAKE_GH_HEAD", head)
    monkeypatch.setenv("FAKE_GH_BASE", base)
    monkeypatch.setenv("FAKE_GH_BASE_OID", base_oid or head)
    monkeypatch.setenv("FAKE_GH_FINAL_STATE", final_state)
    monkeypatch.setenv("FAKE_GH_MERGE_OID", "a" * 40)
    return calls


def test_canonical_gatekeeper_loop_calls_service_and_bound_final_writer(
        ready_service, tmp_path, monkeypatch):
    skill = _GATEKEEPER_SKILL.read_text()
    cron = skill.split("## Cron-invocation template", 1)[1].split("## Reference", 1)[0]
    for required in (
            "gatekeeper-ready-receipts", "root-admission.json",
            "--writer repo-gatekeeper", "--receipt-root", "--candidates-json",
            "receipt_sha256", "os.fsync",
            "os.replace", "--service-ready", "--service-final-write",
            "GATEKEEPER_READY_ID", "GATEKEEPER_READY_HEAD",
            "GATEKEEPER_READY_BASE", "--match-head-commit"):
        assert required in skill, required
    assert not re.search(r"(?m)^\s*gh pr merge <num>", cron)
    assert "RE-RUN required checks" not in cron
    assert cron.index("--service-ready") < cron.index("bounded preparation")

    root, git, entry, receipt, run, marker = ready_service
    entry["id"] = "47"
    main = git("rev-parse", "main")
    git("update-ref", "refs/remotes/origin/main", main)
    calls = _fake_gh(tmp_path, monkeypatch, number=47, head=entry["head"],
                     base_oid=main)
    receipt_root = root / ".git" / "gatekeeper-ready-receipts"
    receipt_root.mkdir(mode=0o700)
    installed_receipt = receipt_root / "verify-47.json"
    shutil.copyfile(receipt, installed_receipt)
    entry.update(receipt=str(installed_receipt),
                 receipt_sha256=hashlib.sha256(
                     installed_receipt.read_bytes()).hexdigest())
    manifest = receipt_root / "root-admission.json"
    slow_marker = tmp_path / "unaccepted-preparation-ran"
    actionable = [{"id": "46", "accepted": False,
                   "prepare_argv": [sys.executable, "-c",
                       "import pathlib; pathlib.Path(" + repr(str(slow_marker))
                       + ").write_text('slow')"]}, entry]
    accepted = [row for row in actionable if row.get("accepted", True)]
    final = [sys.executable, str(_service_program()), "--service-final-write",
             "--repo", str(root), "--base", "origin/main"]
    rc = subprocess.run(
        [sys.executable, str(_service_program()), "--service-ready", str(manifest),
         "--repo", str(root), "--base", "origin/main",
         "--writer", "repo-gatekeeper", "--receipt-root", str(receipt_root),
         "--candidates-json", json.dumps(accepted),
         "--final-command", *final],
        cwd=root, capture_output=True, text=True)
    assert rc.returncode == 0, rc.stdout + rc.stderr
    result = json.loads(rc.stdout.splitlines()[-1])
    published = json.loads(manifest.read_text())

    assert result["status"] == "DELIVERED"
    if result["status"] != "DELIVERED":
        subprocess.run(actionable[0]["prepare_argv"], check=True)
    assert not slow_marker.exists()
    assert result["id"] == "47" and result["receipt_reused"] is True
    assert published == {"writer": "repo-gatekeeper",
                         "receipt_root": str(receipt_root),
                         "candidates": [entry]}
    assert manifest.stat().st_mode & 0o777 == 0o600
    bound = json.loads(result["stdout"])
    assert bound == {"base": main, "final_rc": 0, "head": entry["head"],
                     "id": "47", "status": "FINAL_WRITE_COMPLETE",
                     "merge_commit": "a" * 40, "stderr": "", "stdout": ""}
    observed = [json.loads(line) for line in calls.read_text().splitlines()]
    assert observed == [
        ["pr", "view", "47", "--json",
         "number,headRefOid,baseRefName,baseRefOid,isDraft,state,mergeCommit"],
        ["pr", "merge", "47", "--squash", "--delete-branch",
         "--match-head-commit", entry["head"]],
        ["pr", "view", "47", "--json",
         "number,headRefOid,baseRefName,baseRefOid,isDraft,state,mergeCommit"]]


def test_service_final_writer_refuses_a_different_pr_head_without_merge(
        ready_service, tmp_path, monkeypatch):
    root, git, entry, receipt, run, marker = ready_service
    entry["id"] = "48"
    main = git("rev-parse", "main")
    git("update-ref", "refs/remotes/origin/main", main)
    calls = _fake_gh(tmp_path, monkeypatch, number=48, head=main,
                     base_oid=main)
    final = [sys.executable, str(_service_program()), "--service-final-write",
             "--repo", str(root), "--base", "origin/main"]
    rc, result = run(final_command=final, base="origin/main")

    assert rc.returncode != 0 and result["status"] == "BLOCKED_FINAL_WRITE"
    bound = json.loads(result["stdout"])
    assert bound["status"] == "BLOCKED_FINAL_WRITE_BINDING"
    assert "id/head/base/state no longer match" in bound["reason"]
    observed = [json.loads(line) for line in calls.read_text().splitlines()]
    assert observed == [["pr", "view", "48", "--json",
                         "number,headRefOid,baseRefName,baseRefOid,isDraft,state,mergeCommit"]]


def test_service_final_writer_refuses_rc0_while_remote_is_still_open(
        ready_service, tmp_path, monkeypatch):
    root, git, entry, receipt, run, marker = ready_service
    entry["id"] = "49"
    main = git("rev-parse", "main")
    git("update-ref", "refs/remotes/origin/main", main)
    calls = _fake_gh(tmp_path, monkeypatch, number=49, head=entry["head"],
                     base_oid=main, final_state="OPEN")
    final = [sys.executable, str(_service_program()), "--service-final-write",
             "--repo", str(root), "--base", "origin/main"]
    rc, result = run(final_command=final, base="origin/main")

    assert rc.returncode != 0 and result["status"] == "BLOCKED_FINAL_WRITE"
    bound = json.loads(result["stdout"])
    assert bound["status"] == "BLOCKED_FINAL_WRITE"
    assert bound["final_rc"] == 0 and bound["merge_commit"] is None
    observed = [json.loads(line) for line in calls.read_text().splitlines()]
    assert [row[:2] for row in observed] == [
        ["pr", "view"], ["pr", "merge"], ["pr", "view"]]


def test_service_final_writer_refuses_a_moved_remote_base_without_merge(
        ready_service, tmp_path, monkeypatch):
    root, git, entry, receipt, run, marker = ready_service
    entry["id"] = "51"
    main = git("rev-parse", "main")
    git("update-ref", "refs/remotes/origin/main", main)
    calls = _fake_gh(tmp_path, monkeypatch, number=51, head=entry["head"],
                     base_oid="b" * 40)
    final = [sys.executable, str(_service_program()), "--service-final-write",
             "--repo", str(root), "--base", "origin/main"]
    rc, result = run(final_command=final, base="origin/main")

    assert rc.returncode != 0 and result["status"] == "BLOCKED_FINAL_WRITE"
    bound = json.loads(result["stdout"])
    assert bound["status"] == "BLOCKED_FINAL_WRITE_BINDING"
    assert "id/head/base/state no longer match" in bound["reason"]
    observed = [json.loads(line) for line in calls.read_text().splitlines()]
    assert observed == [["pr", "view", "51", "--json",
                         "number,headRefOid,baseRefName,baseRefOid,isDraft,state,mergeCommit"]]


def test_canonical_gatekeeper_entry_has_no_legacy_unbound_writer_or_rerun():
    skill = _GATEKEEPER_SKILL.read_text()
    frontmatter = skill.split("---", 2)[1]
    description = re.search(r"(?m)^description: (.*)$", frontmatter).group(1)
    top_loop = skill.split(
        "Every cron wake-up is a fresh, independent tick:", 1)[1].split(
            "The loop is **chip-AGNOSTIC**", 1)[0]
    cron = skill.split("## Cron-invocation template", 1)[1].split(
        "## Reference", 1)[0]
    historical = re.findall(
        r"<!-- HISTORICAL_NON_EXECUTABLE_START -->.*?"
        r"<!-- HISTORICAL_NON_EXECUTABLE_END -->", skill, re.DOTALL)
    assert len(historical) <= 1
    current_instructions = re.sub(
        r"<!-- HISTORICAL_NON_EXECUTABLE_START -->.*?"
        r"<!-- HISTORICAL_NON_EXECUTABLE_END -->", "", skill,
        flags=re.DOTALL)

    assert not re.search(r"(?m)^\s*gh pr merge\b", current_instructions)
    for stale in (".merge.lock", "serialized re-test-on-rebase",
                  "RE-RUN the required checks on the REBASED tree",
                  "RE-RUN gatekeeper_review.py", "rebased-tree re-run",
                  "rebase onto current origin/main", "on the rebased tree",
                  "rebase 到最新 origin/main", "在 rebase 樹上重跑"):
        assert stale not in current_instructions, stale
    assert len(historical) == 1
    for required in ("ready-first", "accepted receipt", "bounded",
                     "READY-bound", "holds", "dependencies",
                     "shared conflicts"):
        assert required in current_instructions, required
    top_order = {
        "service_ready": top_loop.index("--service-ready"),
        "machine_gates": top_loop.index("machine gates"),
    }
    assert top_order["service_ready"] < top_order["machine_gates"], top_order
    assert "BLOCKED_NO_ACCEPTED_CANDIDATE" in top_loop
    assert "no immediately deliverable READY candidate" in " ".join(
        top_loop.split())
    assert description in current_instructions
    assert "--service-ready" in cron
    assert "--service-final-write" in cron
    assert "BLOCKED_NO_ACCEPTED_CANDIDATE" in cron


@pytest.mark.parametrize("kind", ["missing-outer-pin", "forged-outer-pin"])
def test_actual_cli_publisher_refuses_invalid_outer_pin_before_final_writer(
        ready_service, tmp_path, monkeypatch, kind):
    root, git, entry, receipt, run, marker = ready_service
    entry["id"] = "50"
    receipt_root = root / ".git" / "gatekeeper-ready-receipts"
    receipt_root.mkdir(mode=0o700)
    installed_receipt = receipt_root / "verify-50.json"
    shutil.copyfile(receipt, installed_receipt)
    entry["receipt"] = str(installed_receipt)
    if kind == "missing-outer-pin":
        entry.pop("receipt_sha256")
    else:
        entry["receipt_sha256"] = "0" * 64
    manifest = receipt_root / "root-admission.json"
    calls = _fake_gh(tmp_path, monkeypatch, number=50, head=entry["head"])
    final = [sys.executable, str(_service_program()), "--service-final-write",
             "--repo", str(root), "--base", "origin/main"]
    result = subprocess.run(
        [sys.executable, str(_service_program()), "--service-ready", str(manifest),
         "--repo", str(root), "--base", "origin/main",
         "--writer", "repo-gatekeeper", "--receipt-root", str(receipt_root),
         "--candidates-json", json.dumps([entry]),
         "--final-command", *final],
        cwd=root, capture_output=True, text=True)

    report = json.loads(result.stdout)
    assert result.returncode != 0
    assert report["status"] == "BLOCKED_ADMISSION_INPUT"
    assert not manifest.exists() and not calls.exists()
