#!/usr/bin/env python3
"""Regression for the two run_v1239_converge scoring-robustness absorptions.

② cocotb sim-hang watchdog (eda_image_preflight.recommended_scoring_env +
   `--print-scoring-env`): a deterministic DOCKER_TIMEOUT/TASK_TIMEOUT env so a
   hung cocotb sim becomes an UNATTENDED timeout-FAIL instead of a manual
   `docker kill` stall. This is a ROBUSTNESS fix, NOT a score lever — the values
   are the harness's own generous defaults, chosen to be VERDICT-NEUTRAL (they
   only bound a non-advancing sim; a passing sim finishes well under budget). A
   hung DUT is a genuine bug and still scores FAIL.

③ cheaper-model default for blind authoring (doc): the CVDP blind-authoring
   instructions DEFAULT to a cheaper model + low reasoning effort, reserving Opus
   for hard triage — a cost policy, gated by the same deterministic emit gate.

Run:  python3 -m pytest test_v1_2_cvdp_scoring_robustness.py -q
"""
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLUGIN / "benchmark"))
import eda_image_preflight as E  # noqa: E402

BLIND_CVDP = PLUGIN / "benchmark" / "blind_instructions_shape_cvdp.md"


# ── ② sim-hang watchdog env ─────────────────────────────────────────────────
def test_recommended_scoring_env_has_both_timeouts():
    env = E.recommended_scoring_env()
    assert "DOCKER_TIMEOUT" in env, "DOCKER_TIMEOUT must be pinned"
    assert "TASK_TIMEOUT" in env, "TASK_TIMEOUT must be pinned"


def test_watchdog_values_are_verdict_neutral_generous():
    """The timeouts must be GENEROUS (the harness defaults), so the watchdog only
    bounds an already-hung sim and changes ZERO existing pass/fail verdicts. A
    real cocotb functional test finishes in seconds; these are minutes."""
    env = E.recommended_scoring_env()
    # match the official ConfigManager defaults (DOCKER_TIMEOUT=600, TASK_TIMEOUT=300)
    assert int(env["DOCKER_TIMEOUT"]) >= 600
    assert int(env["TASK_TIMEOUT"]) >= 300
    # sanity: a per-container cap at least as large as the per-task cap.
    assert int(env["DOCKER_TIMEOUT"]) >= int(env["TASK_TIMEOUT"])


def test_recommended_scoring_env_returns_fresh_copy():
    """Caller may mutate the result without corrupting the module constant."""
    a = E.recommended_scoring_env()
    a["DOCKER_TIMEOUT"] = "1"
    b = E.recommended_scoring_env()
    assert b["DOCKER_TIMEOUT"] != "1", "must hand back a fresh dict each call"


def test_print_scoring_env_cli_emits_exportable_lines():
    """`--print-scoring-env` prints `export K=V` lines a scoring driver can eval,
    and exits 0 WITHOUT requiring --image/--problem-dir."""
    r = subprocess.run(
        [sys.executable, str(PLUGIN / "programs" / "eda_image_preflight.py"),
         "--print-scoring-env"],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "export DOCKER_TIMEOUT=" in out
    assert "export TASK_TIMEOUT=" in out
    # every emitted line is a shell-safe `export K=V`
    for line in out.strip().splitlines():
        assert line.startswith("export ") and "=" in line


def test_preflight_still_requires_args_without_the_flag():
    """The new flag must not relax the existing front door: with neither
    --image/--problem-dir nor --print-scoring-env, the tool still errors (rc 2)."""
    r = subprocess.run(
        [sys.executable, str(PLUGIN / "programs" / "eda_image_preflight.py")],
        capture_output=True, text=True)
    assert r.returncode == 2


# ── ③ cheaper-model default doc ─────────────────────────────────────────────
def test_blind_cvdp_worklist_doc_is_the_one_the_dispatcher_names():
    """The policy below is only policy while the dispatcher sends the blind
    worklist author to THIS file.

    Added with the cost-policy restoration: that section was lost because a
    rewrite of this document dropped it and nothing tied the document to its
    reader, so the only surviving trace of the policy was a red test. A rename
    or a re-point that orphans the doc must be red here, not discovered later.
    """
    dispatch = (PLUGIN / "programs" / "benchmark_dispatch.py").read_text()
    assert BLIND_CVDP.name in dispatch, (
        f"benchmark_dispatch.py no longer names {BLIND_CVDP.name}; the blind "
        f"worklist instructions this file pins are not the ones an author is "
        f"sent to")


def test_blind_cvdp_instructions_default_to_cheaper_model():
    txt = BLIND_CVDP.read_text()
    low = txt.lower()
    # a model-selection / cost section exists
    assert "model selection" in low or "cost policy" in low
    # it names the cheaper default AND reserves Opus for triage
    assert "haiku" in low, "cheaper default model not named"
    assert "opus" in low, "Opus-for-triage reservation not stated"
    assert "low reasoning effort" in low or "low effort" in low
    # framed honestly as a COST policy, not a quality claim
    assert "cost" in low


def test_blind_cvdp_model_ids_are_current():
    """Guard against stale model IDs drifting into the instructions."""
    txt = BLIND_CVDP.read_text()
    # if a concrete id is cited it must be a current one (no legacy claude-3*/2*)
    import re
    ids = re.findall(r"claude-[a-z0-9-]+", txt)
    for mid in ids:
        assert not re.match(r"claude-(2|3|instant|1)", mid), f"stale model id: {mid}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
