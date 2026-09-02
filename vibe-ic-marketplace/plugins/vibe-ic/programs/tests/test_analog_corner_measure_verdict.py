#!/usr/bin/env python3
"""Tests for the corner-sweep MEASUREMENT verdict in analog_real_corner_sweep.

Which corner metrics are NULLED and which are kept as real measured data used
to be decided by matching ngspice error PROSE (_ERR_MARKER_RE / _FAILED_MEAS_RE
/ _FAILED_MEAS_SHORT_RE / an inline "no such vector as gain"). A failed `.meas`
still echoes a BOGUS scalar through the `$&` summary line, so a missed phrase
wrote 0.0 into corner_results.json as REAL measured data with full provenance —
worse than a crash, because it silently poisons analog sign-off.

The verdict now rests on the simulator's own structured per-.measure record
(ngspice fork #29 `--json-measure`) when available, and on a FAIL-SAFE text
fallback when not. The negatives are load-bearing.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import analog_real_corner_sweep as A  # noqa: E402


# --------------------------------------------------------------------------- #
# fixtures — a dead simulation vs a healthy one
# --------------------------------------------------------------------------- #
# The live reproducer (delta_sigma corner deck): the transient aborts, the AC
# analysis never runs, and ngspice STILL echoes `ugbw = 0.0`. A 0 Hz unity-gain
# bandwidth is pure garbage, but it is a well-formed scalar on the meas-echo
# line — exactly the value that must never reach corner_results.json.
_DEAD_SIM = """doAnalyses: TRAN: Timestep too small
tran simulation(s) aborted
Error: no such vector as gain.
meas ac dcgain find gain at=1 failed!
MEAS ugbw=0.00000e+00 vstep=1.2
"""
_HEALTHY = "dcgain = 4.5e+01\nugbw = 1.2e+06\nvstep = 1.2e+00\n"

_SIDECAR_FAILED = (
    '[{"name":"dcgain","analysis":"ac","type":"find","unit":"V",'
    '"pass":false,"value":null},'
    '{"name":"ugbw","analysis":"ac","type":"when","unit":"Hz",'
    '"pass":false,"value":null}]'
)
_SIDECAR_OK = (
    '[{"name":"dcgain","analysis":"ac","type":"find","unit":"V",'
    '"pass":true,"value":4.5e+01},'
    '{"name":"ugbw","analysis":"ac","type":"when","unit":"Hz",'
    '"pass":true,"value":1.2e+06}]'
)


def _run(monkeypatch, sim_out, sidecar, rc=0, supports=True):
    """Drive _run_ngspice with a mocked container."""
    A._JSON_MEASURE_SUPPORT.clear()

    # ROUND 18: `_run_ngspice` now passes an explicit per-deck `timeout` —
    # the deadline scales with the transient the deck asks for, because an
    # incremental converter's measurement unit is one conversion window and
    # the window is the design's declared OSR. The stub takes it and ignores
    # it; what this module measures is the verdict logic, not the clock.
    def _docker(container, cmd, timeout=None):
        r = types.SimpleNamespace(stdout="", returncode=0)
        if "--json-measure=/dev/null" in cmd:          # the capability probe
            r.stdout = ("" if supports else
                        "ngspice: unrecognized option '--json-measure=/dev/null'")
        elif cmd.startswith("cat "):                    # sidecar read-back
            r.stdout = sidecar or ""
        else:                                           # the simulation
            r.stdout, r.returncode = sim_out, rc
        return r

    monkeypatch.setattr(A, "_docker", _docker)
    monkeypatch.setattr(A, "_resolve_ngspice", lambda c: "ngspice")
    return A._run_ngspice("c", "/tmp/deck.sp")


# --------------------------------------------------------------------------- #
# (A) the STRUCTURED sidecar is authoritative
# --------------------------------------------------------------------------- #
def test_sidecar_failed_measure_nulls_despite_bogus_echoed_zero(monkeypatch):
    """PROVEN-NEGATIVE: the simulator says the measure FAILED; the echo summary
    says `ugbw=0.0`. The structured verdict wins and the metric is NULL."""
    _ok, meas, _t, ss = _run(monkeypatch, "MEAS ugbw=0.00000e+00\n",
                             _SIDECAR_FAILED)
    assert meas.get("ugbw") is None, "a bogus 0.0 survived a failed measure"
    assert ss["measure_source"] == "json_sidecar"
    assert ss["measures_structurally_verified"] is True


def test_sidecar_verdict_ignores_wording_entirely(monkeypatch):
    """The sidecar decides even when the log carries NO recognisable error
    phrase at all — no prose is consulted on this path."""
    _ok, meas, _t, ss = _run(monkeypatch,
                             "simulation finished\nMEAS ugbw=0.00000e+00\n",
                             _SIDECAR_FAILED)
    assert meas.get("ugbw") is None
    assert "ugbw" in ss["nulled_metrics"]


def test_sidecar_passing_measures_are_kept(monkeypatch):
    """POSITIVE GATE: a genuinely successful measure is KEPT — no over-nulling."""
    _ok, meas, _t, ss = _run(monkeypatch, _HEALTHY, _SIDECAR_OK)
    assert meas.get("ugbw") == pytest.approx(1.2e6)
    assert meas.get("dcgain") == pytest.approx(45.0)
    assert ss["nulled_metrics"] == []


@pytest.mark.parametrize("blob", ["", "   ", "not json", "{}", "[1,2,3]"])
def test_unparseable_sidecar_is_not_evidence_of_success(blob):
    """FAIL-SAFE: an absent/garbled sidecar yields None ('no structured
    verdict'), never a claim that measurements succeeded."""
    assert A.parse_json_measure_sidecar(blob) in (None, {}) or \
        all(v == (False, None) for v in A.parse_json_measure_sidecar(blob).values())


def test_sidecar_never_yields_a_bogus_zero():
    """A failed record carries value:null, so no 0.0 can enter through it."""
    got = A.parse_json_measure_sidecar(_SIDECAR_FAILED)
    assert got == {"dcgain": (False, None), "ugbw": (False, None)}


# --------------------------------------------------------------------------- #
# (B) the TEXT fallback is FAIL-SAFE
# --------------------------------------------------------------------------- #
def test_text_fallback_used_only_when_sidecar_absent(monkeypatch):
    """A stock ngspice rejects the flag; we must fall back, and say so."""
    _ok, _m, _t, ss = _run(monkeypatch, _HEALTHY, None, supports=False)
    assert ss["measure_source"] == "text_scrape"
    assert ss["measures_structurally_verified"] is False


def test_text_fallback_keeps_a_clean_run(monkeypatch):
    """POSITIVE GATE: no failures in the log -> metrics kept. The fail-safe
    must not turn every stock-ngspice run into nulls."""
    _ok, meas, _t, ss = _run(monkeypatch, _HEALTHY, None, supports=False)
    assert meas.get("ugbw") == pytest.approx(1.2e6)
    assert ss["nulled_metrics"] == []


def test_text_fallback_nulls_echo_only_metric_on_a_dead_sim(monkeypatch):
    """PROVEN-NEGATIVE: the live reproducer. `ugbw=0.0` arrives ONLY via the
    `$&` echo summary with no native meas result while the run reported
    failures — it has no evidence of being measured, so it is nulled."""
    _ok, meas, _t, ss = _run(monkeypatch, _DEAD_SIM, None, supports=False)
    assert meas.get("ugbw") is None, "the bogus 0 Hz UGBW survived"
    assert "ugbw" in ss["nulled_metrics"]


def test_text_fallback_nonzero_exit_nulls_everything(monkeypatch):
    """PROVEN-NEGATIVE: a non-zero ngspice exit cannot yield measured data,
    however healthy the transcript looks."""
    _ok, meas, _t, ss = _run(monkeypatch, _HEALTHY, None, rc=1, supports=False)
    assert meas.get("ugbw") is None and meas.get("dcgain") is None
    assert ss["partial"] is True


# --------------------------------------------------------------------------- #
# the de-hardcoded "no such vector as <name>"
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("metric,analysis", [
    ("gain", "ac"), ("dcgain", "ac"), ("ugbw", "ac"),
    ("vstep", "tran"), ("vsettle", "tran"),
])
def test_no_such_vector_generalized_to_any_metric(metric, analysis):
    """The inline check used to be hardcoded to the literal name `gain`, so it
    missed every other metric. It now keys on the CAPTURED name and attributes
    the owning analysis."""
    fa, fk, _w = A._scan_analysis_failures(f"Error: no such vector as {metric}.\n")
    assert metric in fk
    assert analysis in fa
