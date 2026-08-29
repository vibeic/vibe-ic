from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "tools" / "ci" / "hermetic_test_arm_entry.sh"
VERIFIER = ROOT / "tools" / "gatekeeper-verify-merge.sh"
RUNNER = ROOT / "tools" / "ci" / "hermetic_candidate_runner.py"


def _retains_only_failed_tmp_paths(body: str) -> bool:
    return (
        body.count("-o tmp_path_retention_policy=failed") == 1
        and "-o tmp_path_retention_policy=all" not in body
        and "-o tmp_path_retention_policy=none" not in body
    )


def test_entry_is_one_fixed_runtime_only_aggregate_invocation():
    body = ENTRY.read_text(encoding="utf-8")
    assert body.startswith("#!/usr/bin/env bash\n")
    assert 'GATEKEEPER_RUNTIME_ROOT:-}" = "/runtime"' in body
    assert 'A1|B1)' in body
    assert "--aggregate-check" in body
    assert "--aggregate-only" in body
    assert "--hermetic-progress" in body
    assert 'grace=${VIBEIC_PYTEST_SEMANTIC_STALL_GRACE:-}' in body
    assert '--stall-after "$grace"' in body
    assert '--aggregate-stall-after "$grace"' in body
    assert "--stall-after 300" not in body
    assert "--aggregate-stall-after 300" not in body
    assert "--timeout" not in body
    assert "pytest_timeout" not in body
    # `-B` is not decoration: `-I` implies `-E`, so the isolated child does not
    # see PYTHONDONTWRITEBYTECODE and writes bytecode into the subject bind.
    assert 'python3 -I -B "$PROGRAMS/trusted_pytest_entry.py"' in body
    assert _retains_only_failed_tmp_paths(body)


def test_test_arm_does_not_retain_successful_tmp_path_trees():
    body = ENTRY.read_text(encoding="utf-8")
    required = "-o tmp_path_retention_policy=failed"
    assert required in body
    mutant = body.replace(required, "-o tmp_path_retention_policy=all", 1)
    assert not _retains_only_failed_tmp_paths(mutant)


def _lease_bindings(body: str) -> tuple[list[str], list[str]]:
    selector = re.findall(
        r'--(?:base|candidate)-progress-plan "\$[^\"]+" \\\n'
        r'\s+--stall-grace-seconds "\$(\w+)"',
        body,
    )
    landing = re.findall(
        r'--scope landing:[AB]2 \\\n'
        r'\s+--stall-grace-seconds "\$(\w+)"',
        body,
    )
    return selector, landing


def test_inner_and_outer_semantic_leases_are_fixed_and_have_shutdown_margin():
    body = VERIFIER.read_text(encoding="utf-8")
    runner = RUNNER.read_text(encoding="utf-8")
    assert '"VIBEIC_PYTEST_SEMANTIC_STALL_GRACE": "600"' in runner
    assert "PYTEST_SEMANTIC_STALL_GRACE=" not in body
    assert "TEST_ARM_SEMANTIC_STALL_GRACE=630" in body
    assert "LANDING_ARM_SEMANTIC_STALL_GRACE=300" in body
    assert "${GATEKEEPER_SEMANTIC_STALL_GRACE" not in body
    assert '--env "VIBEIC_PYTEST_SEMANTIC_STALL_GRACE=' not in body
    # Bind the lease to every exact plan-producing call site.  Merely finding
    # both variable names somewhere in the script let the primary selector be
    # mutated back to 300 while this test stayed green.
    assert _lease_bindings(body) == (
        ["TEST_ARM_SEMANTIC_STALL_GRACE", "TEST_ARM_SEMANTIC_STALL_GRACE"],
        ["LANDING_ARM_SEMANTIC_STALL_GRACE", "LANDING_ARM_SEMANTIC_STALL_GRACE"],
    )


def test_mutating_the_primary_test_plan_back_to_300_is_detected():
    body = VERIFIER.read_text(encoding="utf-8")
    old = '--candidate-progress-plan "$B1_PROGRESS_PLAN" \\\n' \
          '      --stall-grace-seconds "$TEST_ARM_SEMANTIC_STALL_GRACE"'
    mutant = '--candidate-progress-plan "$B1_PROGRESS_PLAN" \\\n' \
             '      --stall-grace-seconds "$LANDING_ARM_SEMANTIC_STALL_GRACE"'
    assert old in body
    mutated = body.replace(old, mutant, 1)
    assert _lease_bindings(mutated) != _lease_bindings(body)
