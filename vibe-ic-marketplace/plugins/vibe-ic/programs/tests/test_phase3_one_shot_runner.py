#!/usr/bin/env python3
"""Tests for phase3_one_shot_runner.py — Phase 3 (synth → GDS) orchestrator.

Wave 83 — coverage for previously untested orchestrator.

The runner shells out to Yosys / OpenROAD / KLayout inside an vibeic-eda
Docker container. The test environment has no Docker, so we exercise
the orchestrator's control-flow paths only:

  1. POSITIVE_FAIL_MISSING_PROJECT — non-existent project dir → exit 2.
  2. POSITIVE_FAIL_NO_RTL — project exists but rtl/ empty → synth step
                              FAILs (no RTL to synthesise) → exit 1 +
                              report emitted under reports/.
  3. INTEGRATION_REPORT_SHAPE — emitted phase3_one_shot.json must contain
                                  project / pdk / top / steps / verdict.
  4. EDGE_INVALID_PDK_OVERRIDE — `--pdk thispdkdoesnotexist` falls back
                                   to sky130A (current behaviour).
  5. STEPS_INCLUDE_DRC_AND_LVS — even on FAIL the steps array contains
                                   drc + lvs entries (always reported).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

#: EVERY test here launches `phase3_one_shot_runner.py`, and that launch does
#: not fit the harness's 180 s item bound reliably. MEASURED: quiet, the six
#: tests are `6 passed in 103.05 s` with a worst single call of 21.04 s; under
#: ordinary fleet contention the SAME call ran past 60 s. So the two numbers
#: this file must declare are different from the defaults:
#:
#:   * the ITEM bound, here: 600 s, a CEILING and not a target, so a slow run
#:     completes or fails on its own instead of taking every other file's
#:     verdict down with it (`--timeout-method=thread` kills the SESSION);
#:   * the INNER bound, `_run` below: 150 s, which `ci_harness_timeout_ceiling_
#:     check` holds to 600 // 3 = 200 s.
#:
#: WHY `pytestmark` AND NOT A PER-TEST DECORATOR: the bound being declared
#: lives in `_run`, a module-level helper all six tests share. A decorator on
#: one test cannot govern a helper the other five also call; a module-level
#: mark bounds every item in the file, so every call in it really does run
#: inside a 600 s item. Verified rather than assumed --
#: `pytestmark = pytest.mark.timeout(30)` under `--timeout=2
#: --timeout-method=thread` yields `2 passed`, not a killed session.
#:
#: WHY NOT SIMPLY LOWER `_run` TO 60: measured, that is a FALSE RED under
#: contention -- the trade `test_matrix_63x8_census_freshness.py` already
#: refused for the same reason.
pytestmark = pytest.mark.timeout(600)

PROG = Path(__file__).resolve().parent.parent / \
    "phase3_one_shot_runner.py"


# v1.4.62 — these control-flow tests exercise the DEFAULT (`--pdk auto`)
# resolution, which lands on the container's OSS enablement. On a host that has
# a commercial PDK configured, `commercial_pdk_fallback_guard` now REFUSES that
# silent fallback (it would emit VOID sign-off reports under a false PDK
# belief). These tests are about orchestrator control flow, not PDK intent, so
# they acknowledge the OSS fallback explicitly — which also makes them
# deterministic regardless of the host's private commercial-PDK config.
_ACK_OSS = "--allow-oss-pdk-fallback"


#: 150 s against the 600 s item bound `pytestmark` declares above (ceiling
#: 600 // 3 = 200). The old 90 s was measured against the wrong denominator:
#: it was chosen when the item bound was the harness's 180 s, where 90 s is
#: half the budget and two calls in one test would end the SESSION.
#: Invisible to `ci_harness_timeout_ceiling_check` until vibe-ic#1277 --
#: the bound is a parameter default, which the gate could not read.
# 90 s, not 150 s. The file's `@pytest.mark.timeout(600)` does NOT buy a 200 s
# ceiling: the driver classifies a session hung after 300 s with no validated
# pytest lifecycle event, and a blocking call emits none, so the applicable bound
# is min(600, 300) // 3 = 100. Measured: the slowest call in this file is 34.6 s
# and the whole file runs in 147 s, so 90 s is ~2.6x headroom over the worst case.
def _run(args: list, timeout: int = 90) -> subprocess.CompletedProcess:
    if args and not args[0].startswith("-") and _ACK_OSS not in args:
        args = args + [_ACK_OSS]
    return subprocess.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True, timeout=timeout,
    )


def test_positive_fail_missing_project(tmp_path):
    missing = tmp_path / "no_such"
    cp = _run([str(missing)])
    assert cp.returncode == 2
    assert "not a directory" in cp.stderr


def test_positive_fail_no_rtl(tmp_path):
    """Empty project → synth step FAIL → orchestrator exits 1."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project)])
    # synth FAIL → verdict FAIL → exit 1.
    assert cp.returncode == 1
    assert "verdict: FAIL" in cp.stdout
    rep = project / "reports" / "orchestrator" / "phase3_one_shot.json"
    assert rep.is_file()


def test_integration_report_shape(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project)])
    rep = project / "reports" / "orchestrator" / "phase3_one_shot.json"
    body = json.loads(rep.read_text())
    for k in ("project", "pdk", "top", "steps", "verdict"):
        assert k in body, f"missing key {k}"
    assert body["top"] == "chip_top"
    assert isinstance(body["steps"], list)
    assert len(body["steps"]) >= 1


def test_edge_custom_top_name(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project), "--top-name", "tst_chip_top"])
    body = json.loads(
        (project / "reports" / "orchestrator" / "phase3_one_shot.json").read_text())
    assert body["top"] == "tst_chip_top"


def test_steps_include_drc_and_lvs(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project)])
    body = json.loads(
        (project / "reports" / "orchestrator" / "phase3_one_shot.json").read_text())
    step_names = {s["name"] for s in body["steps"]}
    # DRC + LVS are always run regardless of synth result.
    assert "drc" in step_names
    assert "lvs" in step_names


def test_edge_explicit_pdk_sky130a(tmp_path):
    """Explicit --pdk sky130A is accepted (uses container paths)."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project), "--pdk", "sky130A"])
    body = json.loads(
        (project / "reports" / "orchestrator" / "phase3_one_shot.json").read_text())
    assert body["pdk"] == "sky130A"
