#!/usr/bin/env python3
"""v1.7.64 — Step 27 (d5): SI advisory disclosure is FAIL-CLOSED.

Reproduced on v1.7.36 against the real converged run's artefact
``reports/phase3/si_crosstalk.json``:

    {"tool": "openroad-wire-rc-screen", "verdict": "SCREEN_PASS",
     "method": "decoupled-C wire-RC screen ... needs a SPEF ...",
     "note": "... this is a structural screen, not a full SI sign-off."}

`si_crosstalk_check` allow-listed exactly two emitter verdict strings
("ADVISORY_SCREEN_ONLY", "SI_SPEF_SCREEN_PASS") plus the substring "advisory"
in `method`. The no-SPEF fallback emitter writes a THIRD string, "SCREEN_PASS",
and its method/note never contain the word "advisory" — so the #437
anti-laundering logic did not fire on its own sibling path and the gate
reported ``verdict: PASS``, ``advisory_screen_only: false``, zero findings.
The run with the LEAST SI evidence produced the CLEANEST verdict.

The predicate is now inverted: ADVISORY unless the artefact POSITIVELY
declares timing-window SI sign-off. The producer is aligned to one vocabulary
so the two ends cannot drift apart again.

Exit code is deliberately UNCHANGED — the disclosure is a WARNING, not an
ERROR. Making it an ERROR would newly hard-FAIL Step 27 on every SPEF-less
run and is a separate owner decision.

chip-AGNOSTIC: structural JSON / report markers only.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS_DIR = Path(__file__).resolve().parent.parent
if str(_PROGRAMS_DIR) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS_DIR))

import si_crosstalk_check as SI  # noqa: E402

_PROG = _PROGRAMS_DIR / "si_crosstalk_check.py"
_P3_SRC = (_PROGRAMS_DIR / "phase3_one_shot_runner.py").read_text()


# The measured real-run artefact, verbatim in shape (paths/strings are the
# emitter's own; no chip identity in it).
_REAL_NO_SPEF_FALLBACK = {
    "tool": "openroad-wire-rc-screen",
    "mode": "signal_integrity_crosstalk_screen",
    "max_crosstalk_noise": 0.0,
    "violations_count": 0,
    "method": ("decoupled-C wire-RC screen on routed DB; full coupling-cap "
               "crosstalk needs a SPEF with coupling caps — none was produced "
               "for this run (e.g. routing-less DEF). When a SPEF IS present "
               "the runner uses the real coupling-cap screen instead "
               "(v0.2.6)."),
    "verdict": "SCREEN_PASS",
    "note": ("No SPEF coupling caps available for this run; this is a "
             "structural screen, not a full SI sign-off."),
}


def _proj(tmp_path: Path, payload: dict) -> Path:
    d = tmp_path / "reports" / "phase3"
    d.mkdir(parents=True, exist_ok=True)
    (d / "si_crosstalk.json").write_text(json.dumps(payload))
    return tmp_path


def _proj_rpt(tmp_path: Path, text: str) -> Path:
    d = tmp_path / "reports" / "phase3"
    d.mkdir(parents=True, exist_ok=True)
    (d / "si_crosstalk.rpt").write_text(text)
    return tmp_path


def _run_cli(project: Path):
    out = project / "gate.json"
    proc = subprocess.run(
        [sys.executable, str(_PROG), str(project), "--json", str(out)],
        capture_output=True, text=True)
    payload = json.loads(out.read_text()) if out.is_file() else {}
    return proc.returncode, payload


# ===========================================================================
# The defect
# ===========================================================================
def test_real_no_spef_fallback_artifact_is_disclosed(tmp_path):
    """The exact artefact the real run produced must be named as an advisory
    screen, not reported as a clean sign-off PASS."""
    proj = _proj(tmp_path, _REAL_NO_SPEF_FALLBACK)
    rc, rep = _run_cli(proj)
    assert rc == 0, "disclosure is a WARNING; rc must stay 0"
    assert rep["verdict"] == "ADVISORY_SCREEN_ONLY", (
        "an artefact whose own note says 'not a full SI sign-off' must not "
        f"headline as {rep['verdict']}"
    )
    assert rep["summary"]["advisory_screen_only"] is True
    assert any(f["category"] == "SI_ADVISORY_SCREEN_ONLY"
               for f in rep["findings"])
    assert rep["summary"]["errors_count"] == 0


def test_unlabelled_si_json_defaults_to_advisory(tmp_path):
    """An SI artefact that says NOTHING about its own tier cannot be assumed
    to be sign-off. Fail-closed means silence reads as advisory."""
    proj = _proj(tmp_path, {"max_crosstalk_noise": 0.02,
                            "violations_count": 0})
    rc, rep = _run_cli(proj)
    assert rc == 0
    assert rep["summary"]["advisory_screen_only"] is True
    assert rep["verdict"] == "ADVISORY_SCREEN_ONLY"


def test_novel_emitter_string_cannot_buy_a_clean_pass(tmp_path):
    """The whole failure mode was an allow-list miss. A brand-new emitter
    verdict string must not restore the laundering."""
    proj = _proj(tmp_path, {
        "max_crosstalk_noise": 0.0, "violations_count": 0,
        "verdict": "WIRE_RC_QUICK_CHECK_OK",
        "method": "structural pre-route estimate"})
    rc, rep = _run_cli(proj)
    assert rc == 0
    assert rep["summary"]["advisory_screen_only"] is True


def test_rpt_only_screen_is_disclosed(tmp_path):
    """The .rpt form must get the same treatment, otherwise the JSON
    tightening is bypassed by emitting only the text report."""
    proj = _proj_rpt(tmp_path,
                     "# Signal-integrity / crosstalk screen\n"
                     "max_crosstalk_noise: 0.0 mV\n"
                     "violations_count: 0\n"
                     "crosstalk screen: PASS (decoupled-C; SPEF-based SI "
                     "deferred)\n")
    rc, rep = _run_cli(proj)
    assert rc == 0
    assert rep["summary"]["advisory_screen_only"] is True
    assert rep["verdict"] == "ADVISORY_SCREEN_ONLY"
    assert any(f["category"] == "SI_ADVISORY_SCREEN_ONLY"
               for f in rep["findings"])


def test_producer_no_spef_fallback_uses_the_advisory_vocabulary():
    """Producer/checker alignment pin: the weaker no-SPEF fallback must not
    emit a verdict string its strictly-stronger SPEF sibling does not use."""
    assert '"verdict": "SCREEN_PASS"' not in _P3_SRC, (
        "the no-SPEF fallback must emit ADVISORY_SCREEN_ONLY like the SPEF "
        "path, not a third unlisted string"
    )
    assert _P3_SRC.count('"verdict": "ADVISORY_SCREEN_ONLY",') >= 2


# ===========================================================================
# DIRECTION-1 GUARDS — behaviour that must NOT change
# ===========================================================================
def test_guard_declared_timing_window_signoff_stays_plain_pass(tmp_path):
    """A real timing-window SI sign-off must still headline PASS with no
    advisory finding — the tightening must not swallow genuine sign-off."""
    proj = _proj(tmp_path, {
        "method": "timing-window SI analysis",
        "max_crosstalk_noise": 12.0, "violations_count": 0,
        "verdict": "PASS"})
    rc, rep = _run_cli(proj)
    assert rc == 0
    assert rep["verdict"] == "PASS"
    assert rep["summary"]["advisory_screen_only"] is False
    assert not any(f["category"] == "SI_ADVISORY_SCREEN_ONLY"
                   for f in rep["findings"])


def test_guard_explicit_signoff_boolean_is_honoured(tmp_path):
    """An emitter may declare sign-off with an explicit boolean instead of
    prose. That must be accepted."""
    proj = _proj(tmp_path, {
        "max_crosstalk_noise": 12.0, "violations_count": 0,
        "verdict": "PASS", "timing_window_signoff": True})
    rc, rep = _run_cli(proj)
    assert rc == 0
    assert rep["summary"]["advisory_screen_only"] is False


def test_guard_violations_without_waiver_stay_a_hard_error(tmp_path):
    """violations_count > 0 with no waiver is still an ERROR / rc=1 — the
    advisory tier must not absorb real violations."""
    proj = _proj(tmp_path, {"max_crosstalk_noise": 0.15,
                            "violations_count": 3,
                            "verdict": "SCREEN_PASS"})
    rc, rep = _run_cli(proj)
    assert rc == 1
    assert rep["verdict"] == "FAIL"
    assert any(f["category"] == "SI_VIOLATIONS" for f in rep["findings"])


def test_guard_violations_with_waiver_still_rc0(tmp_path):
    proj = _proj(tmp_path, {"max_crosstalk_noise": 0.15,
                            "violations_count": 3})
    (proj / "waivers.json").write_text(json.dumps(
        {"waivers": [{"step": "si_crosstalk", "reason": "accepted"}]}))
    rc, rep = _run_cli(proj)
    assert rc == 0
    assert rep["summary"]["errors_count"] == 0


def test_guard_missing_report_still_fails(tmp_path):
    rc, rep = _run_cli(tmp_path)
    assert rc == 1
    assert any(f["category"] == "NO_REPORT" for f in rep["findings"])


def test_guard_missing_required_fields_still_error(tmp_path):
    proj = _proj(tmp_path, {"foo": "bar"})
    rc, rep = _run_cli(proj)
    assert rc == 1
    assert any(f["category"] == "MISSING_FIELD" for f in rep["findings"])


def test_guard_empty_rpt_still_error(tmp_path):
    proj = _proj_rpt(tmp_path, "")
    rc, rep = _run_cli(proj)
    assert rc == 1
    assert any(f["category"] == "EMPTY_RPT" for f in rep["findings"])


def test_guard_spef_sibling_verdict_still_recognised(tmp_path):
    """The pre-existing recognised strings must keep behaving identically."""
    for verdict in ("ADVISORY_SCREEN_ONLY", "SI_SPEF_SCREEN_PASS"):
        findings, stats = SI.audit(_proj(
            tmp_path / verdict,
            {"method": "x", "max_crosstalk_noise": 1.0,
             "violations_count": 0, "verdict": verdict}))
        assert stats["advisory_screen_only"] is True, verdict


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
