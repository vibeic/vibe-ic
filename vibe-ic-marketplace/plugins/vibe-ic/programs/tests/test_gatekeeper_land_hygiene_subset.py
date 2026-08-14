#!/usr/bin/env python3
"""The hygiene subset wiring in `tools/gatekeeper-land.sh` (vibe-ic#1498).

The delta PROGRAM is tested in `test_hygiene_finding_delta.py`. This tests the
SHELL, because the defect #1498 describes lived in the shell: a bare `run` that
read an exit code against a base that fails.

IT EXECUTES THE PRODUCTION TEXT. The function body is extracted from the real
`tools/gatekeeper-land.sh` at run time and executed, rather than restated here
— a copy of a shell function is a second definition that drifts, and the whole
point of this gate is that two definitions of one rule disagreed.

Every subprocess below is bounded at 30s, under the 60s ceiling that
`ci_harness_timeout_ceiling_check` derives from the harness `--timeout=180`.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

_BOUND_S = 30
DELTA = (Path(__file__).resolve().parents[1] / "hygiene_finding_delta.py")


def _find_land() -> Path:
    """Locate the real script by WALKING UP, not by counting `parents[n]`.

    A hardcoded index is how this file first skipped all eight of its own tests
    silently — `parents[4]` was one short, the path did not exist, and every
    assertion below was replaced by a skip that reads as green. The plugin also
    sits at a different depth when installed than it does in this repo, so the
    index was never a stable answer.
    """
    for d in Path(__file__).resolve().parents:
        c = d / "tools" / "gatekeeper-land.sh"
        if c.is_file():
            return c
    return Path("tools/gatekeeper-land.sh")


LAND = _find_land()


def _extract(name: str) -> str:
    """Pull one top-level shell function out of the real script."""
    if not LAND.is_file():
        # Inside a git checkout the script is SHIPPED, so absence is a defect
        # and must not be laundered into a skip. Only an installed plugin copy
        # (no repo-root `tools/`) legitimately has nothing to test.
        if (Path(__file__).resolve().parents[5] / ".git").exists():
            pytest.fail(
                f"tools/gatekeeper-land.sh is missing from this checkout "
                f"(looked up from {Path(__file__).parent}) — the hygiene "
                f"subset wiring cannot be verified, which is not a pass")
        pytest.skip("no repo-root tools/ — installed plugin copy")
    src = LAND.read_text(encoding="utf-8")
    m = re.search(rf"^{name}\(\) \{{\n(.*?)^\}}\n", src, re.S | re.M)
    assert m, f"{name}() not found in {LAND} — the wiring moved or was renamed"
    return m.group(0)


def _gates(extra_fail: bool = False):
    g = [
        {"label": "anchor tag points at the anchor version",
         "state": "FAIL", "seconds": 1},
        {"label": "probed gates give a host-independent verdict",
         "state": "FAIL", "seconds": 1},
        {"label": "source guard", "state": "FAIL" if extra_fail else "PASS",
         "seconds": 1},
    ]
    return {"listed_only": False, "declared": len(g), "shard": None,
            "corpora": [], "undisclosed_loops": [], "seconds": 5, "gates": g}


def _harness(tmp_path: Path, candidate: dict, env_extra: dict) -> subprocess.CompletedProcess:
    """Run the real run_hygiene_gates() against a STUB hygiene suite.

    The stub exits 1 and writes the candidate record, which is exactly the shape
    #1498 is about: a suite that legitimately fails while the tree under test
    introduced nothing.
    """
    root = tmp_path / "root"
    (root / "tools" / "ci").mkdir(parents=True)
    cand_json = tmp_path / "candidate.json"
    cand_json.write_text(json.dumps(candidate), encoding="utf-8")

    stub = root / "tools" / "ci" / "repo_hygiene_gates.sh"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "# stub: emits a chosen record and FAILS, like the real suite on main\n"
        'while [ $# -gt 0 ]; do\n'
        '  if [ "$1" = "--summary-json" ]; then cp "%s" "$2"; shift 2; else shift; fi\n'
        "done\n"
        'echo "  [FAIL] a stub finding"\n'
        "exit 1\n" % cand_json,
        encoding="utf-8")
    stub.chmod(0o755)

    script = (
        "set -uo pipefail\n"
        f'ROOT="{root}"\n'
        f'PROGRAMS="{DELTA.parent}"\n'
        "FAILED=0\n"
        + _extract("run_hygiene_gates")
        + "\nrun_hygiene_gates\n"
        'echo "FAILED=$FAILED"\n'
    )
    env = dict(os.environ)
    env.update(env_extra)
    return subprocess.run(["bash", "-c", script], capture_output=True,
                          text=True, timeout=_BOUND_S, env=env)


def _baseline(tmp_path: Path) -> Path:
    p = tmp_path / "baseline.json"
    p.write_text(json.dumps(_gates()), encoding="utf-8")
    return p


HOST = os.uname().nodename


# --- WORKED EXAMPLE: only the base's own findings -> the batch PASSES --------
def test_a_batch_carrying_only_the_bases_findings_passes(tmp_path):
    r = _harness(tmp_path, _gates(), {
        "GATEKEEPER_HYGIENE_BASELINE": str(_baseline(tmp_path)),
        "GATEKEEPER_HYGIENE_BASELINE_HOST": HOST,
    })
    assert "FAILED=0" in r.stdout, r.stdout + r.stderr
    assert "PASS  repo hygiene gates (subset of the base" in r.stdout
    # the tolerated findings are NAMED in the log, not counted away
    assert "anchor tag points at the anchor version" in r.stdout


# --- WORKED EXAMPLE: a NEW finding -> the batch is BLOCKED -------------------
def test_a_batch_introducing_a_finding_is_blocked(tmp_path):
    r = _harness(tmp_path, _gates(extra_fail=True), {
        "GATEKEEPER_HYGIENE_BASELINE": str(_baseline(tmp_path)),
        "GATEKEEPER_HYGIENE_BASELINE_HOST": HOST,
    })
    assert "FAILED=1" in r.stdout, r.stdout + r.stderr
    assert "FAIL  repo hygiene gates" in r.stdout
    assert "source guard" in r.stdout


# --- the default path is UNCHANGED ------------------------------------------
def test_with_no_baseline_the_gate_is_the_old_zero_tolerance_one(tmp_path):
    """A green bought by making the rule apply everywhere would be the bug."""
    r = _harness(tmp_path, _gates(), {})
    assert "FAILED=1" in r.stdout, r.stdout + r.stderr
    assert "FAIL  repo hygiene gates" in r.stdout
    assert "subset" not in r.stdout


# --- a refusal blocks exactly like an introduction ---------------------------
def test_a_baseline_from_another_host_blocks(tmp_path):
    r = _harness(tmp_path, _gates(), {
        "GATEKEEPER_HYGIENE_BASELINE": str(_baseline(tmp_path)),
        "GATEKEEPER_HYGIENE_BASELINE_HOST": "some-other-host",
    })
    assert "FAILED=1" in r.stdout, r.stdout + r.stderr
    assert "REFUSED" in r.stdout


def test_a_baseline_that_does_not_exist_blocks(tmp_path):
    r = _harness(tmp_path, _gates(), {
        "GATEKEEPER_HYGIENE_BASELINE": str(tmp_path / "absent.json"),
        "GATEKEEPER_HYGIENE_BASELINE_HOST": HOST,
    })
    assert "FAILED=1" in r.stdout, r.stdout + r.stderr
    assert "REFUSED" in r.stdout


def test_a_baseline_with_no_host_blocks(tmp_path):
    """The host is required and never inferred."""
    r = _harness(tmp_path, _gates(), {
        "GATEKEEPER_HYGIENE_BASELINE": str(_baseline(tmp_path)),
    })
    assert "FAILED=1" in r.stdout, r.stdout + r.stderr
    assert "REFUSED" in r.stdout


# --- the record is emitted even when the suite fails -------------------------
def test_the_record_is_written_even_when_the_suite_fails(tmp_path):
    """A baseline that only exists when the base was green is useless.

    The base arm's whole purpose is to record a FAILING run's findings.
    """
    out = tmp_path / "emitted.json"
    r = _harness(tmp_path, _gates(), {"GATEKEEPER_HYGIENE_REPORT": str(out)})
    assert "FAILED=1" in r.stdout, r.stdout + r.stderr
    assert out.is_file(), "no record emitted from a failing run"
    assert json.loads(out.read_text())["gates"], "record carries no gates"


def test_the_report_env_var_changes_no_verdict(tmp_path):
    """Exactly like GATEKEEPER_PYTEST_JUNIT: an artefact, never a verdict."""
    with_report = _harness(tmp_path / "a", _gates(),
                           {"GATEKEEPER_HYGIENE_REPORT": str(tmp_path / "r.json")})
    without = _harness(tmp_path / "b", _gates(), {})
    assert ("FAILED=1" in with_report.stdout) == ("FAILED=1" in without.stdout)
