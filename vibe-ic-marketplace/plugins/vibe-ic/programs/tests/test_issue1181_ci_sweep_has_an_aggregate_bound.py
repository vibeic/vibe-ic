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
    res = G.audit_ci(root, timeout=60, budget=3.0)
    elapsed = time.monotonic() - t0

    assert res.truncated, "a 20s sweep inside a 3s budget was not truncated"
    assert res.probed < res.declared, (res.probed, res.declared)
    # THE BOUND FIRED, READ FROM THE RECORD IT WRITES rather than from a
    # stopwatch. `audit_ci` names every gate the budget stopped and WHY, so the
    # loop being cut short is a fact in `not_driven`, not an inference from how
    # long the call took on this host.
    why = [w for _label, w in res.not_driven]
    assert any("aggregate budget" in w for w in why), why
    assert len(res.not_driven) > 0, (
        f"nothing was recorded as not-driven, so the truncation flag has "
        f"nothing behind it (observed {elapsed:.1f}s)")


def test_a_truncated_sweep_is_NOT_CHECKED_and_never_PASS(tmp_path):
    """"I could not look" must not arrive as "I looked and it was clean"."""
    root = _repo(tmp_path, n_gates=20, sleep_s=1.0)
    res = G.audit_ci(root, timeout=60, budget=3.0)
    assert res.findings == [], "the fixture's gates all disclose; no finding"
    assert res.verdict == "NOT_CHECKED", res.verdict
    assert res.verdict != "PASS"


def test_the_dropped_gates_are_NAMED_not_merely_counted(tmp_path):
    root = _repo(tmp_path, n_gates=20, sleep_s=1.0)
    res = G.audit_ci(root, timeout=60, budget=3.0)
    dropped = [g for g, w in res.not_driven if "aggregate budget" in w]
    assert dropped, res.not_driven
    assert all(g.startswith("sleepy gate") for g in dropped), dropped


def test_an_untruncated_sweep_still_PASSES(tmp_path):
    """The false-positive control. A budget the sweep fits inside must leave
    the verdict exactly as it was before this change."""
    root = _repo(tmp_path, n_gates=3, sleep_s=0.05)
    res = G.audit_ci(root, timeout=60, budget=60.0)
    assert not res.truncated
    assert res.verdict == "PASS", res.findings
    assert res.probed == res.declared == 3


def test_no_budget_is_the_previous_behaviour(tmp_path):
    """`budget=None` is unbounded — the shape every existing caller has."""
    root = _repo(tmp_path, n_gates=3, sleep_s=0.05)
    res = G.audit_ci(root, timeout=60, budget=None)
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

    res = G.audit_ci(root, timeout=60, budget=3.0)
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
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 2, (r.returncode, r.stderr[-400:])
    assert "NOT CHECKED" in r.stderr
    assert "aggregate budget" in r.stderr or "NOT PROBED" in r.stderr


def test_the_json_record_discloses_truncation(tmp_path):
    import json
    root = _repo(tmp_path, n_gates=20, sleep_s=1.0)
    out = tmp_path / "rec.json"
    subprocess.run(
        [sys.executable, str(_PROG), str(root), "--budget", "3",
         "--json", str(out)], capture_output=True, text=True, timeout=60)
    rec = json.loads(out.read_text())
    assert rec["truncated"] is True, rec
    assert rec["gates_probed"] < rec["gates_declared"], rec


def test_one_slow_gate_cannot_outlive_the_budget(tmp_path):
    """The per-gate timeout is CLAMPED to what is left.

    Without the clamp a single gate declaring a 120s wait would carry the loop
    120s past a 3s budget — the bound would exist and not hold.
    """
    root = _repo(tmp_path, n_gates=1, sleep_s=30.0)
    t0 = time.monotonic()
    res = G.audit_ci(root, timeout=60, budget=3.0)
    elapsed = time.monotonic() - t0
    # THE CLAMP, ASSERTED WHERE IT IS OBSERVABLE. `_probe` distinguishes its
    # two budget outcomes in the reason it records: a gate stopped BEFORE it was
    # launched says "exhausted before this gate was launched", and a gate whose
    # per-gate timeout was CUT DOWN to the remaining budget says "ran out while
    # this gate was running". Only the second can happen when the clamp works,
    # and with one gate declared there is nothing else it could be.
    #
    # Without the clamp the single 30 s gate runs its full per-gate `timeout=60`
    # and comes back "unrunnable", not "budget" — so this assertion fails for
    # the exact defect the stopwatch was aimed at, and passes on a loaded host.
    assert res.truncated, res
    why = [w for _label, w in res.not_driven]
    assert any("ran out while this gate was running" in w for w in why), (
        f"the per-gate timeout was not clamped to the remaining budget: {why} "
        f"(observed {elapsed:.1f}s)")
    assert res.probed <= res.declared
