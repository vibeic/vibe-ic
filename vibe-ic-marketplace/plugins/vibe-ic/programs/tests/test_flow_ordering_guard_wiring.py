#!/usr/bin/env python3
"""The step-execution ordering guard, pinned AT THE WIRING — not at the library.

`flow_step_execution_coverage_check.analyze()` is well covered by unit tests
that import it and call it directly. Nothing covered the ~20 lines inside
`flow_compliance_check.main()` that actually *invoke* it, which is where the
enforcement lives:

    try:
        import flow_step_execution_coverage_check as _cov
        ...
        if ordering_fail_lines:
            forced_fail = True
    except Exception:
        ordering_fail_lines = []          # <- the whole guard, silently gone

Delete that block, or make anything inside `analyze` raise, and the audit
reported ZERO ordering violations, forced no FAIL, and every test stayed green.
An unavailable guard was indistinguishable from a guard that ran and found
nothing — a falsely-clean result, which is the failure mode this repo is being
cleaned of.

The audit still must not crash on a broken guard, so the exception is still
caught; what changed is that it is now REPORTED (its own `ordering_guard_error`
line + JSON key, kept out of `ordering_violations` so a consumer counting that
list is not told a violation was found) and BLOCKING. A guard that did not run
has certified nothing.
"""
from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
PROG = PROGRAMS / "flow_compliance_check.py"
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))
import flow_compliance_check as fcc  # noqa: E402

# Two stage-3 steps with a real `blocks_on` edge. Names are deliberately
# neutral so the coverage module's NAME-based terminal/sign-off fallback stays
# out of it and the graph edge is the only thing under test. `--stage 3` also
# switches the P0 structural umbrella off, keeping the fixture about the
# ordering wiring and nothing else.
_FLOW = """\
steps:
  - id: 90
    name: "upstream artefact step"
    stage: stage3
    required_outputs:
      - "phase3/stage3/pnr/routed.def"
  - id: 91
    name: "downstream consumer step"
    stage: stage3
    required_outputs:
      - "phase3/stage3/pnr/consumer.flag"
    blocks_on: [90]
"""


def _mk(tmp_path: Path, *, upstream_ran: bool):
    proj = tmp_path / "proj"
    pnr = proj / "phase3/stage3/pnr"
    pnr.mkdir(parents=True)
    (pnr / "consumer.flag").write_text("done\n")
    if upstream_ran:
        (pnr / "routed.def").write_text("DESIGN x ;\nEND DESIGN\n")
    flow = tmp_path / "flow.yaml"
    flow.write_text(_FLOW)
    return proj, flow


def _argv(proj: Path, flow: Path, out: Path):
    return [str(proj), "--flow-def", str(flow), "--stage", "3",
            "--json", str(out)]


def _overall(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("Overall:"):
            return line.split()[1]
    raise AssertionError(f"no Overall line in:\n{text}")


# ── the wiring itself ────────────────────────────────────────────────────────

def test_ordering_guard_is_reached_from_the_audit(tmp_path):
    """A downstream step marked done over a MISSING dependency must surface as
    an ordering violation IN THE AUDIT OUTPUT — not merely be detectable by
    calling `analyze()` in a unit test."""
    proj, flow = _mk(tmp_path, upstream_ran=False)
    out = tmp_path / "r.json"
    r = subprocess.run([sys.executable, str(PROG), *_argv(proj, flow, out)],
                       capture_output=True, text=True)
    assert "Step-execution ordering violations" in r.stdout, r.stdout
    rep = json.loads(out.read_text())
    assert len(rep["ordering_violations"]) == 1, rep["ordering_violations"]
    assert "[91]" in rep["ordering_violations"][0]
    assert "[90]" in rep["ordering_violations"][0]
    # `.get` so this stays a DIRECTION-1 guard that passes on origin/main too,
    # where the key does not exist yet: the point here is that the guard RAN
    # and found the violation, which was already true.
    assert rep.get("ordering_guard_error") is None
    assert _overall(r.stdout) == "FAIL", r.stdout


def test_healthy_chain_produces_no_ordering_violation(tmp_path):
    """DIRECTION 1: the guard must stay quiet when the dependency really ran."""
    proj, flow = _mk(tmp_path, upstream_ran=True)
    out = tmp_path / "r.json"
    r = subprocess.run([sys.executable, str(PROG), *_argv(proj, flow, out)],
                       capture_output=True, text=True)
    rep = json.loads(out.read_text())
    assert rep["ordering_violations"] == []
    assert rep.get("ordering_guard_error") is None
    assert "Step-execution ordering violations" not in r.stdout, r.stdout
    assert "DID NOT RUN" not in r.stdout, r.stdout


# ── a guard that cannot run must not report clean ────────────────────────────

class _Exploding(types.ModuleType):
    def analyze(self, *_a, **_k):  # noqa: D401 - deliberate failure injection
        raise RuntimeError("injected: analyze is broken")


def _run_with_broken_guard(monkeypatch, capsys, proj, flow, out):
    monkeypatch.setitem(
        sys.modules, "flow_step_execution_coverage_check",
        _Exploding("flow_step_execution_coverage_check"))
    rc = fcc.main(_argv(proj, flow, out))
    return rc, capsys.readouterr().out


def test_broken_guard_is_reported_and_blocks(tmp_path, monkeypatch, capsys):
    """THE defect. With `analyze` raising, the audit used to print nothing about
    ordering, leave the verdict unforced, and record `ordering_violations: []` —
    a clean bill of health for an invariant it never evaluated."""
    proj, flow = _mk(tmp_path, upstream_ran=False)
    out = tmp_path / "r.json"
    rc, stdout = _run_with_broken_guard(monkeypatch, capsys, proj, flow, out)
    rep = json.loads(out.read_text())
    assert rep.get("ordering_guard_error"), rep
    assert "injected: analyze is broken" in rep["ordering_guard_error"]
    assert "DID NOT RUN" in stdout, stdout
    assert _overall(stdout) == "FAIL", stdout
    assert rc != 0


def test_broken_guard_does_not_fabricate_a_violation(tmp_path, monkeypatch,
                                                     capsys):
    """"The guard could not run" is NOT a violation. It must not be smuggled
    into `ordering_violations`, where a consumer counting that list would read
    it as a found defect (and a consumer diffing counts would see phantom
    churn)."""
    proj, flow = _mk(tmp_path, upstream_ran=True)   # healthy chain
    out = tmp_path / "r.json"
    rc, stdout = _run_with_broken_guard(monkeypatch, capsys, proj, flow, out)
    rep = json.loads(out.read_text())
    assert rep["ordering_violations"] == [], rep["ordering_violations"]
    assert rep.get("ordering_guard_error"), rep
    assert rc != 0          # unverified is still not certifiable


def test_audit_survives_a_broken_guard(tmp_path, monkeypatch, capsys):
    """DIRECTION 1: blocking must not become crashing — the rest of the audit
    still runs and still reports its per-step verdicts."""
    proj, flow = _mk(tmp_path, upstream_ran=True)
    out = tmp_path / "r.json"
    _rc, stdout = _run_with_broken_guard(monkeypatch, capsys, proj, flow, out)
    rep = json.loads(out.read_text())
    assert {str(s["id"]) for s in rep["steps"]} == {"90", "91"}
    assert "Overall:" in stdout


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
