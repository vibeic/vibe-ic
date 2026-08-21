from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "tools" / "ci" / "hermetic_test_arm_entry.sh"


def test_entry_is_one_fixed_runtime_only_aggregate_invocation():
    body = ENTRY.read_text(encoding="utf-8")
    assert body.startswith("#!/usr/bin/env bash\n")
    assert 'GATEKEEPER_RUNTIME_ROOT:-}" = "/runtime"' in body
    assert 'A1|B1)' in body
    assert "--aggregate-check" in body
    assert "--aggregate-only" in body
    assert "--hermetic-progress" in body
    assert "--timeout" not in body
    assert "pytest_timeout" not in body
    assert 'python3 -I "$PROGRAMS/trusted_pytest_entry.py"' in body
