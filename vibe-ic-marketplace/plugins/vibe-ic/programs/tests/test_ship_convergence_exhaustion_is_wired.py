"""The convergence-exhaustion checker had to actually see a real log.

`ship_postroute_convergence_exhaustion_check` landed as a STANDALONE
DIAGNOSTIC, deliberately not wired into any phase-3 verdict — a correct
scope declaration, since calling a gate BLOCKING needs a proven-by-run
demonstration nobody had. `checker_execution_wiring_audit` then flagged it,
and it is right for a different reason: a checker nothing ever invokes has
zero coverage of real inputs. Its unit tests prove the logic on a fixture
its author wrote; they prove nothing about production artefacts.

So it is invoked where the log it reads is produced — `signoff_spef_repair`
writes `signoff_spef_repair.log`, and the diagnostic runs on it — while
still deciding nothing. What it reaches is recorded, not acted on.

MEASURED through the runner's own function, not by reading source:

    bound exhausted, still improving   verdict=FAIL   findings=1  terminal=None
    plateaued (loop said so)           verdict=PASS   findings=1  terminal=SHIP_CVG_PLATEAU
    junk                               verdict=ERROR  findings=0

TWO DEFECTS WERE FOUND BY WRITING THIS, both of the file's recurring shape:

  * the first version called `_pl.report_path(project, "phase3/…")`, which
    auto-routes by FILENAME, does not know this one, and landed the report in
    `reports/audit/` — where no reader of a phase-3 run looks. The probe said
    "no report written" while the function was working.
  * the first version ended in `except Exception: pass`, which makes a
    diagnostic that COULD NOT RUN indistinguishable from one that found
    nothing to report. It now records ERROR.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

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

_REPORT = "reports/phase3/ship_convergence_exhaustion.json"


def _log(wns, drv, terminal=None, postroute=None):
    out = []
    for i, (w, d) in enumerate(zip(wns, drv)):
        out.append(f"SHIP_WNS_CVG_PASS{i}: {w:.3f}")
        out.append(f"SHIP_CVG_DRV{i}: {d}")
    if terminal:
        out.append(terminal)
    if postroute is not None:
        out.append(f"SHIP_WNS_POSTROUTE: {postroute:.3f}")
    return "\n".join(out) + "\n"


def _run(tmp_path, log):
    P._ship_convergence_exhaustion_report(tmp_path, log)
    f = tmp_path / _REPORT
    return json.loads(f.read_text()) if f.is_file() else None


# ── it runs, and it lands where a reader looks ────────────────────────────
def test_the_report_lands_under_reports_phase3(tmp_path):
    """LOAD-BEARING. `_pl.report_path` would put it in reports/audit/, which is
    the cross-phase fallback for names the taxonomy does not know — a report
    nobody reads is the same as no report."""
    r = _run(tmp_path, _log([-8.0, -6.5], [200, 140]))
    assert r is not None, "no report written"
    assert (tmp_path / _REPORT).is_file()
    assert not (tmp_path / "reports/audit/ship_convergence_exhaustion.json").is_file()


def test_bound_exhausted_while_still_improving_is_the_finding(tmp_path):
    """The state the checker exists to name: no terminal marker, WNS still
    moving, DRV still collapsing. The published number is a backstop artefact,
    and the actionable change is the constant — not the design."""
    r = _run(tmp_path, _log([-8.0, -6.5, -5.0, -3.5, -2.0, -0.5, 0.0, 0.5],
                            [200, 140, 80, 40, 20, 10, 4, 0],
                            postroute=-1.5))
    assert r["verdict"] == "FAIL"
    assert r["summary"]["terminal_marker"] is None
    assert r["findings"]


def test_a_loop_that_announced_its_plateau_is_not_the_finding(tmp_path):
    """THE ACCEPT CASE, and the one that decides whether this is usable: the
    loop's own break fired, so raising the bound buys nothing and a residual
    violation is the design's. If this went FAIL too, the diagnostic would say
    the same thing about every run and mean nothing."""
    r = _run(tmp_path, _log([-2.00, -2.01, -2.02, -2.03], [3, 3, 3, 3],
                            terminal="SHIP_CVG_PLATEAU", postroute=-2.07))
    assert r["verdict"] == "PASS"
    assert r["summary"]["terminal_marker"] == "SHIP_CVG_PLATEAU"


def test_a_closed_loop_is_not_the_finding(tmp_path):
    r = _run(tmp_path, _log([-4.0, -1.0, 0.1], [50, 10, 0],
                            terminal="SHIP_CVG_CLOSED", postroute=0.1))
    assert r["verdict"] == "PASS"


# ── it must not decide anything ───────────────────────────────────────────
def test_it_is_recorded_as_non_blocking(tmp_path):
    """The scope declaration has to travel with the artefact. A reader who finds
    `verdict: FAIL` must be able to see, from the same file, that nothing was
    gated on it."""
    r = _run(tmp_path, _log([-8.0, -6.5, -5.0, -3.5, -2.0, -0.5, 0.0, 0.5],
                            [200, 140, 80, 40, 20, 10, 4, 0]))
    assert r["verdict"] == "FAIL" and r["blocking"] is False


def test_the_step_calls_it_where_the_log_is_written():
    """WIRING, not logic: the diagnostic must be invoked on the log the step
    just produced. Asserting only that the function behaves correctly would
    leave it disconnectable — which is the finding that started this."""
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    i = body.index('(pnr_out / "signoff_spef_repair.log").write_text(log)')
    j = body.index("_parse_ship_repair_log(log)", i)
    assert "_ship_convergence_exhaustion_report(project, log)" in body[i:j]


# ── a diagnostic that cannot run must say so ──────────────────────────────
def test_a_log_with_no_markers_is_error_not_pass(tmp_path):
    """An absence rendering as a pass is the defect this whole area is about.
    A log the checker cannot read is not a converged run."""
    r = _run(tmp_path, "openroad finished\nnothing to see here\n")
    assert r["verdict"] == "ERROR"
    assert r["findings"] == []


def test_a_failure_inside_the_checker_is_recorded_not_swallowed(tmp_path,
                                                               monkeypatch):
    """MUTATION-DRIVEN — the first version of this function ended in
    `except Exception: pass`, so a checker that raised produced no file at all,
    identical to a run nobody diagnosed."""
    import ship_postroute_convergence_exhaustion_check as cvg

    def boom(*a, **k):
        raise RuntimeError("engineered")

    monkeypatch.setattr(cvg, "audit", boom)
    r = _run(tmp_path, _log([-1.0], [1]))
    assert r is not None, "the failure produced no record at all"
    assert r["verdict"] == "ERROR"
    assert "engineered" in r["summary"]["error"]


def test_it_never_raises_into_the_step(tmp_path, monkeypatch):
    """A diagnostic that can fail the step it is diagnosing is worse than the
    ambiguity it reports."""
    import ship_postroute_convergence_exhaustion_check as cvg
    monkeypatch.setattr(cvg, "audit",
                        lambda *a, **k: (_ for _ in ()).throw(ValueError("x")))
    P._ship_convergence_exhaustion_report(tmp_path, "anything")
