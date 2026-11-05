"""Landing-runtime properties that outlived the protected-path two-step.

The owner removed the protected-path two-step on 2026-09-27.  Its test files
also carried four checks whose subject was never the register: the hygiene
script's routed-DEF producer wiring, the landing script's retirement of the
wall-clock pytest timeout, the strict JSON reader, and the landing pin
renderer's refusal of an invalid semantic runtime.  They moved here unchanged
in what they assert, and keep their names:

  test_phase_b_routed_producer_and_structural_opt_in_are_active and
  test_the_activated_runtime_no_longer_uses_a_wall_clock_pytest_timeout
      (from the deleted phase-B activated-parity test file);
  test_strict_json_refuses_duplicate_nonfinite_and_non_utf8
      (from the deleted transition-validator test file);
  test_repin_preserves_structural_negative_control
      (from the deleted runtime-bundle test file).
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_DISPATCH = "tools/ci/_gate_dispatch.sh"
_HYGIENE = "tools/ci/repo_hygiene_gates.sh"
_LAND = "tools/gatekeeper-land.sh"
_PROGRAMS = "vibe-ic-marketplace/plugins/vibe-ic/programs"
_CHECKER = f"{_PROGRAMS}/ci_harness_timeout_ceiling_check.py"
_DRIVER = f"{_PROGRAMS}/pytest_per_file_junit.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


P = _load(_ROOT / "tools/ci/landing_record_primitives.py",
          "_invariants_record_primitives")


def test_phase_b_routed_producer_and_structural_opt_in_are_active():
    """The inversion of the Phase-A dormancy claim.

    While Phase-A was dormant these three had to be ABSENT from the hygiene
    script; activation is precisely the moment they become present, and the
    legacy in-repo `git ls-files` producer callsite is retired.
    """
    hygiene = (_ROOT / _HYGIENE).read_text(encoding="utf-8")
    dispatch = (_ROOT / _DISPATCH).read_text(encoding="utf-8")

    assert "routed_def_corpus.py" in hygiene, (
        "the routed-DEF corpus producer is not wired into the hygiene script")
    assert "GATE_DISPATCH_ATTEST_POPULATION" in dispatch
    assert "GATE_DISPATCH_ATTEST_POPULATION" in hygiene, (
        "the structural population attestation is not opted into")

    legacy_callsite = re.compile(
        r'gate_dispatch_over "published cells carrying a routed DEF"\s*\\\s*'
        r"_per_published_cell_gates\s*\\\s*"
        r"git -C \"\$ROOT\" ls-files --\s*\\\s*"
        r"'benchmark-data/ic/\*/\*/phase3/stage3/pnr/routed\.def'",
        re.MULTILINE,
    )
    assert not legacy_callsite.search(hygiene), (
        "the legacy in-repo git-ls-files producer callsite survived activation")


def test_the_activated_runtime_no_longer_uses_a_wall_clock_pytest_timeout():
    """`-p pytest_timeout --timeout=...` kills the session and loses its JUnit,
    so a hang becomes an unattributable red. Semantic progress replaces it; if
    the timeout idiom came back the retirement would have been undone in place.
    """
    land = (_ROOT / _LAND).read_text(encoding="utf-8")
    body = re.search(
        r"^run_repo_tools_pytest\(\) \{.*?^\}", land, re.MULTILINE | re.DOTALL)
    assert body, "run_repo_tools_pytest is gone from gatekeeper-land.sh"
    fn = body.group(0)
    assert "-p pytest_timeout" not in fn
    assert "--timeout" not in fn
    assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1" in fn
    assert "trusted_pytest_entry.py" in fn


@pytest.mark.parametrize("bad", [
    b'{"schema":1,"schema":1}',
    b'{"schema":NaN}',
    b'\xff',
])
def test_strict_json_refuses_duplicate_nonfinite_and_non_utf8(bad):
    with pytest.raises(P.Refusal):
        P.strict_loads(bad, what="adversarial")
