"""#655's checker shipped with nothing but its own test invoking it.

`declared_pdk_is_the_pdk_used_check` exists because a run whose staged PDK went
missing did not stop: it used the open PDK baked into the EDA image and
completed four rounds on a process the design does not target, and a reported
"PASS 4 -> 27" improvement was measured against a different process than the one
before it. Its own docstring is about a guard that never ran —
`pdk_consistency_check` takes `--pdk-lib` as REQUIRED, so with no PDK staged
there is nothing to pass it and it never fires. "A guard that is switched off by
the very condition it exists to catch has never been able to catch it."

Shipping it unwired would have been a second instance of that. It now runs at
the end of phase 3, on the run that just finished, and records its verdict.

VERIFIED BY RUNNING IT, not by reading the source — on an empty run directory,
exactly as the runner invokes it:

    rc=2   report written=True   verdict="NOT CHECKED"

rc 2 and NOT CHECKED, rather than a green report on a run it could not read.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

_spec = importlib.util.spec_from_file_location(
    "phase3_one_shot_runner", _PROGRAMS / "phase3_one_shot_runner.py")
P = importlib.util.module_from_spec(_spec)
sys.modules["phase3_one_shot_runner"] = P
try:
    _spec.loader.exec_module(P)
except SystemExit:
    pass


def test_the_checker_is_registered_as_a_post_run_audit():
    progs = [p for p, _rel, _k in P._POST_RUN_AUDITS]
    assert "declared_pdk_is_the_pdk_used_check.py" in progs


def test_every_registered_audit_exists_on_disk():
    """A registry entry naming a program that is not there runs nothing and
    says nothing — the absence this whole area keeps producing."""
    for prog, _rel, _k in P._POST_RUN_AUDITS:
        assert (_PROGRAMS / prog).is_file(), prog


def test_the_runner_actually_invokes_the_registry():
    """WIRING. A registry nothing iterates leaves the checker exactly as
    unwired as it was."""
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert "for prog, rel_json, kind in _POST_RUN_AUDITS:" in body


def test_it_runs_and_writes_a_report(tmp_path):
    """RUN, not read. Invoked exactly as the runner does."""
    prog, rel, _kind = P._POST_RUN_AUDITS[0]
    out = P._pl.reports_phase3_dir(tmp_path) / rel.rsplit("/", 1)[-1]
    out.parent.mkdir(parents=True, exist_ok=True)
    r = _pr.run(
        [sys.executable, str(_PROGRAMS / prog), str(tmp_path),
         "--json", str(out)],
        capture_output=True, text=True)
    assert out.is_file(), r.stdout[-400:] + r.stderr[-400:]
    assert r.returncode in (0, 1, 2)


def test_an_unreadable_run_is_not_a_green_report(tmp_path):
    """An empty run must not produce a PASS. `verdict: NOT CHECKED` and rc 2 —
    an absence that says so, rather than one wearing a pass."""
    prog, rel, _kind = P._POST_RUN_AUDITS[0]
    out = P._pl.reports_phase3_dir(tmp_path) / rel.rsplit("/", 1)[-1]
    out.parent.mkdir(parents=True, exist_ok=True)
    r = _pr.run(
        [sys.executable, str(_PROGRAMS / prog), str(tmp_path),
         "--json", str(out)],
        capture_output=True, text=True)
    assert r.returncode == 2
    assert json.loads(out.read_text()).get("verdict") == "NOT CHECKED"


def test_the_inner_bound_fits_the_harness_ceiling():
    """The audit's own subprocess bound must stay under 60s: the harness dies at
    180, so a longer bound kills the SESSION instead of the call. This batch
    landed a 120s one three PRs earlier."""
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text(encoding="utf-8")
    i = src.index("for prog, rel_json, kind in _POST_RUN_AUDITS:")
    seg = src[i:i + 1400]
    assert "timeout=55," in seg
