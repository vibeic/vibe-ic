#!/usr/bin/env python3
"""vibe-ic#1181 — the CI sweep is bounded in aggregate, and a truncated sweep
is never a pass.

THE DEFECT. `audit_ci` drives every gate `tools/ci/repo_hygiene_gates.sh`
declares, each under its own `timeout` — and nothing bounded the SUM. Measured
on an idle host at `a38902d1`: 74 declared, 50 driven, **192.9s**, slowest
single gate 35.1s. That is already past the suite's `--timeout=180`, and the
worst case is 50 x 120s.

WHY THE HARNESS COULD NOT SAVE IT. The wait is inside `subprocess.run`.
`pytest-timeout --timeout-method=thread` cannot interrupt a blocking syscall,
so the timeout fired, dumped its stack, and the invocation still never
finished — the whole pytest run produced NO SUMMARY LINE. That greps as
neither pass nor fail, and it silently unmeasured every other file in the
selection. It removed a file from a real landing measurement twice in one day.

The fixture below is synthetic and chip-AGNOSTIC: a scratch repo whose
`repo_hygiene_gates.sh` declares gates that `sleep`, so the aggregate can be
driven past a budget in a second or two without depending on the real gate set.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import gate_discloses_denominator_check as G  # noqa: E402

_PROG = PROGRAMS / "gate_discloses_denominator_check.py"

#: Every bound in this file — the per-gate `timeout=` handed to `audit_ci` and
#: the CLI subprocesses below (vibe-ic#1241).
#:
#: WHY NOT 120, WHICH IS WHAT THIS FILE SHIPPED WITH. `--timeout-method=thread`
#: takes the SESSION down rather than the test, so a bound above the harness's
#: own can never fire: pytest ends the run at 180s first and every other file in
#: the subset loses its verdict. `ci_harness_timeout_ceiling_check` resolves the
#: per-call ceiling as `180 // 3` = 60s, and 120 is double it.
#:
#: THE IRONY IS THE POINT. This file was added by the PR that fixed the CI sweep
#: for overrunning that same harness, and it did so with nine bounds of its own
#: above the ceiling — two of them judged (`subprocess.run`) and seven only
#: advisory, because the gate cannot follow a bound into `audit_ci`. Advisory is
#: not absolution: `audit_ci(timeout=120)` genuinely gives each gate 120s.
#:
#: 30 IS MEASURED, not lowered until the gate went quiet. Every gate this file
#: drives is a synthetic `sleep`, the whole 11-test file runs in 22.73s, and its
#: slowest single test is 3.42s — so 30s is ~9x the slowest measured test and
#: half the ceiling, leaving room for a test that makes two bounded calls.
_BOUND_S = 30


def _repo(tmp_path: Path, n_gates: int, sleep_s: float) -> Path:
    """A scratch repo declaring `n_gates` gates that each sleep `sleep_s`.

    Each gate DISCLOSES its denominator, so nothing here is a finding — the
    only thing under test is how long the loop is allowed to take.
    """
    root = tmp_path / "repo"
    (root / "tools" / "ci").mkdir(parents=True)
    (root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs").mkdir(
        parents=True)
    prog = root / "sleeper.py"
    prog.write_text(
        "import sys, time\n"
        "time.sleep(float(sys.argv[1]))\n"
        "print('examined 0 item(s): nothing to look at')\n")
    lines = ["#!/usr/bin/env bash\n"]
    for i in range(n_gates):
        lines.append(
            f'run "sleepy gate {i}" "$ROOT" python3 "{prog}" {sleep_s}\n')
    (root / "tools" / "ci" / "repo_hygiene_gates.sh").write_text("".join(lines))
    return root


def test_the_sweep_stops_at_its_budget(tmp_path):
    """THE BOUND. 20 gates x 1s cannot run inside a 3s budget; the loop stops."""
    root = _repo(tmp_path, n_gates=20, sleep_s=1.0)
    t0 = time.monotonic()
    res = G.audit_ci(root, timeout=_BOUND_S, budget=3.0)
    elapsed = time.monotonic() - t0

    assert res.truncated, "a 20s sweep inside a 3s budget was not truncated"
    assert elapsed < 20, (
        f"the budget did not bound the loop: {elapsed:.1f}s for a 3s budget")
    assert res.probed < res.declared, (res.probed, res.declared)


def test_a_truncated_sweep_is_NOT_CHECKED_and_never_PASS(tmp_path):
    """"I could not look" must not arrive as "I looked and it was clean"."""
    root = _repo(tmp_path, n_gates=20, sleep_s=1.0)
    res = G.audit_ci(root, timeout=_BOUND_S, budget=3.0)
    assert res.findings == [], "the fixture's gates all disclose; no finding"
    assert res.verdict == "NOT_CHECKED", res.verdict
    assert res.verdict != "PASS"


def test_the_dropped_gates_are_NAMED_not_merely_counted(tmp_path):
    root = _repo(tmp_path, n_gates=20, sleep_s=1.0)
    res = G.audit_ci(root, timeout=_BOUND_S, budget=3.0)
    dropped = [g for g, w in res.not_driven if "aggregate budget" in w]
    assert dropped, res.not_driven
    assert all(g.startswith("sleepy gate") for g in dropped), dropped


def test_an_untruncated_sweep_still_PASSES(tmp_path):
    """The false-positive control. A budget the sweep fits inside must leave
    the verdict exactly as it was before this change."""
    root = _repo(tmp_path, n_gates=3, sleep_s=0.05)
    res = G.audit_ci(root, timeout=_BOUND_S, budget=60.0)
    assert not res.truncated
    assert res.verdict == "PASS", res.findings
    assert res.probed == res.declared == 3


def test_no_budget_is_the_previous_behaviour(tmp_path):
    """`budget=None` is unbounded — the shape every existing caller has."""
    root = _repo(tmp_path, n_gates=3, sleep_s=0.05)
    res = G.audit_ci(root, timeout=_BOUND_S, budget=None)
    assert not res.truncated and res.verdict == "PASS"


def test_a_FINDING_outranks_truncation(tmp_path):
    """A violation seen over a partial view is still a violation.

    Same rule `flow_step_execution_coverage_check` applies to its own partial
    sweeps: FAIL wins over NOT-CHECKED, because the finding is a fact about a
    gate and the truncation is a fact about the loop.
    """
    root = _repo(tmp_path, n_gates=20, sleep_s=1.0)
    # Prepend a gate that passes SILENTLY — the defect this program hunts.
    silent = root / "silent.py"
    silent.write_text("print('')\n")
    script = root / "tools" / "ci" / "repo_hygiene_gates.sh"
    body = script.read_text().split("\n")
    body.insert(1, f'run "silent gate" "$ROOT" python3 "{silent}"')
    script.write_text("\n".join(body))

    res = G.audit_ci(root, timeout=_BOUND_S, budget=3.0)
    assert res.findings, "the silent gate should have been caught"
    assert res.truncated, "and the sweep should still have run out of budget"
    assert res.verdict == "FAIL", (
        f"a finding must outrank truncation; got {res.verdict}")


def test_the_cli_exits_2_on_a_truncated_sweep(tmp_path):
    """rc 0 from this program is read by the tier as 'every CI gate discloses
    what it examined'. Over a truncated sweep that is a claim about how far the
    loop got."""
    root = _repo(tmp_path, n_gates=20, sleep_s=1.0)
    r = subprocess.run(
        [sys.executable, str(_PROG), str(root), "--budget", "3"],
        capture_output=True, text=True, timeout=_BOUND_S)
    assert r.returncode == 2, (r.returncode, r.stderr[-400:])
    assert "NOT CHECKED" in r.stderr
    assert "aggregate budget" in r.stderr or "NOT PROBED" in r.stderr


def test_the_json_record_discloses_truncation(tmp_path):
    import json
    root = _repo(tmp_path, n_gates=20, sleep_s=1.0)
    out = tmp_path / "rec.json"
    subprocess.run(
        [sys.executable, str(_PROG), str(root), "--budget", "3",
         "--json", str(out)], capture_output=True, text=True, timeout=_BOUND_S)
    rec = json.loads(out.read_text())
    assert rec["truncated"] is True, rec
    assert rec["gates_probed"] < rec["gates_declared"], rec


def test_one_slow_gate_cannot_outlive_the_budget(tmp_path):
    """The per-gate timeout is CLAMPED to what is left.

    Without the clamp a single gate declaring a 20s wait would carry the loop
    20s past a 3s budget — the bound would exist and not hold.
    """
    # sleep_s 30 -> 20 so the per-gate bound (30s) still strictly EXCEEDS
    # what the gate would take. At 30/30 a failure could mean the
    # subprocess hit its own timeout rather than the budget clamping it,
    # and those are different mechanisms. 20s against a 3s budget still
    # overruns the `elapsed < 15` assertion if the clamp is removed.
    root = _repo(tmp_path, n_gates=1, sleep_s=20.0)
    t0 = time.monotonic()
    res = G.audit_ci(root, timeout=_BOUND_S, budget=3.0)
    elapsed = time.monotonic() - t0
    assert elapsed < 15, (
        f"one gate ran {elapsed:.1f}s against a 3s budget — the per-gate "
        f"timeout is not clamped to the remaining budget")
    assert res.probed <= res.declared


# ===========================================================================
# THE FAN-OUT'S ISOLATION, PINNED (vibe-ic#1268)
#
# The fresh scratch per gate is NOT justified by these gates writing today:
# driving all 50 real CI gates serially against one shared tree and
# fingerprinting after each gives 42 entries before, 42 after, WRITERS: 0. The
# next person to measure that has an argument for sharing one tree and saving
# 50 `git init`s (~1s of 38).
#
# It is justified by what being wrong COSTS once the loop is concurrent: a gate
# that starts writing corrupts the population in a different order every run,
# which reads as flakiness and gets waived rather than diagnosed. So the
# property is pinned here, and removing it has to be a decision rather than a
# tidy-up.
# ===========================================================================
def _repo_recording_cwd(tmp_path: Path, n_gates: int, ledger: Path) -> Path:
    """A scratch repo whose gates each append the cwd they were driven in."""
    root = tmp_path / "repo_cwd"
    (root / "tools" / "ci").mkdir(parents=True)
    prog = root / "whereami.py"
    prog.write_text(
        "import os, sys\n"
        "with open(sys.argv[1], 'a') as fh:\n"
        "    fh.write(os.getcwd() + '\\n')\n"
        "print('examined 0 item(s): nothing to look at')\n")
    lines = ["#!/usr/bin/env bash\n"]
    for i in range(n_gates):
        lines.append(
            f'run "cwd gate {i}" "$ROOT" python3 "{prog}" "{ledger}"\n')
    (root / "tools" / "ci" / "repo_hygiene_gates.sh").write_text("".join(lines))
    return root


def test_the_fan_out_gives_every_gate_its_own_scratch(tmp_path):
    """Each driven gate must be driven in a scratch NO other gate can see.

    Asserted by having every gate record the directory it actually ran in, so
    this measures the isolation the implementation delivers rather than the
    presence of a `TemporaryDirectory` call.
    """
    ledger = tmp_path / "cwds.txt"
    root = _repo_recording_cwd(tmp_path, 6, ledger)
    res = G.audit_ci(root)

    assert res.verdict == "PASS", (res.verdict, res.findings)
    seen = [ln for ln in ledger.read_text().splitlines() if ln.strip()]
    assert len(seen) == 6, (
        f"expected all 6 gates to be driven; the ledger recorded "
        f"{len(seen)}: {seen}")
    assert len(set(seen)) == 6, (
        f"two or more gates were driven in the SAME scratch tree, so one "
        f"gate's writes can become another's input and — under the fan-out — "
        f"in a different order every run.\n  distinct: "
        f"{len(set(seen))} of {len(seen)}\n  {sorted(set(seen))}")


def test_PAIRED_the_isolation_check_can_SEE_a_shared_scratch(tmp_path):
    """THE TWIN. Without it, the assertion above could be trivially true.

    Drives the same six gates through ONE shared tree — the pre-fan-out shape
    — and requires the distinctness test to fail on it. If this ever stops
    failing, the check above has stopped measuring isolation.
    """
    import tempfile

    ledger = tmp_path / "cwds_shared.txt"
    root = _repo_recording_cwd(tmp_path, 6, ledger)
    gates = G.parse_declarations(root / "tools" / "ci" / "repo_hygiene_gates.sh")
    assert len(gates) == 6, gates

    with tempfile.TemporaryDirectory() as td:
        shared = G._scratch_repo(Path(td))
        for decl in gates:
            argv = G._expand(decl.cmd, root, shared)
            assert G._driveable(argv) is None, (decl.label, argv)
            subprocess.run(argv, cwd=str(shared), capture_output=True,
                           text=True, timeout=30)

    seen = [ln for ln in ledger.read_text().splitlines() if ln.strip()]
    assert len(seen) == 6, seen
    assert len(set(seen)) == 1, (
        "the shared-scratch control did not actually share a tree, so it "
        f"cannot show the isolation check has teeth: {sorted(set(seen))}")
