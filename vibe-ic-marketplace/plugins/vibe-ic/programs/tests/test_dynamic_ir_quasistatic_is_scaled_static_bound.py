#!/usr/bin/env python3
"""Regression — the transient (dynamic) IR artefact must not label a
QUASI-STATIC solve (no on-die decap) as a genuine di/dt result.

Defect (measured on the caravel_user_project round; captured in-repo)
--------------------------------------------------------------------
`dynamic_ir_vectored_emit.build_result` stamped EVERY payload with the
disclosure "... The number is a genuine dynamic droop, not a static echo (a
quasi-static solve yields ~2x the static drop)." — unconditionally, including
the quasi-static (no-decap) case.

But under the fork's `quasi-static` capacitance model the transient solve
degenerates to a DETERMINISTIC scaling of the static drop. The tool itself
prints `Dynamic/static ratio : 2.00`, and in every captured run the dynamic
number is EXACTLY 2.00x the static one:

  benchmark-data/ic/caravel_user_project/v1.9.43_sky130A/reports/phase3/
      dynamic_ir.json : max_dynamic_drop_mv 0.0728 = 2.00 x 0.0364  (sky130A, 1.8V, 25ns)
  benchmark-data/ic/spm/v1.5.66_gf180mcuD/reports/phase3/
      dynamic_ir.json : max_dynamic_drop_mv 14.3   = 2.00 x 7.15    (gf180,  5.0V, 10ns)

The SAME 2.00 to three significant figures across two different designs, PDKs,
supplies and clock periods is the signature of a fixed multiplier, not a di/dt
solve — a real transient droop's ratio varies with the RC network, decap and
activity. So the number answers the STATIC question scaled by a constant; a
reader taking it as a transient result is taking a scaled static result. The
artefact's disclosure pre-excused exactly that ratio ("a quasi-static solve
yields ~2x") while asserting the number was "not a static echo".

The observable property
-----------------------
A payload built from a quasi-static (no-decap) solve must:
  * carry a machine-readable flag marking it as a scaled-static bound
    (`scaled_static_bound is True`), and
  * NOT assert, in ANY of its string values, that the number is genuine /
    "not a static echo".
A payload built from a decap-aware (on-die-cap) solve must NOT be flagged as a
bound and MAY keep the genuine-di/dt presentation.

These are properties of the emitted payload, independent of the exact
disclosure wording — a different correct fix satisfies them too.

REVERSE case (the one that matters — catches over-correction)
-------------------------------------------------------------
The tempting over-correction is to flag EVERYTHING as a scaled-static bound
(or strip the genuine label everywhere), which would FABRICATE a "this is only
a bound" caveat on a genuine decap-aware transient solve and understate the
tool's real capability. `test_reverse_decap_aware_solve_stays_genuine` fails if
that happens.

chip-AGNOSTIC: keyed on the tool's own capacitance-model string; no design,
PDK, vendor, SKU, process-node or part-number literal.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import dynamic_ir_vectored_emit as E  # noqa: E402
import dynamic_ir_drop_check as G     # noqa: E402


# Phrases that assert genuineness. A quasi-static bound must not carry any of
# them in any string value; scanned over the WHOLE payload so the test does not
# depend on which key holds the prose.
_GENUINE_CLAIM_MARKERS = (
    "not a static echo",
    "genuine dynamic droop",
    "genuine dynamic",
)


def _string_values(payload):
    return [v for v in payload.values() if isinstance(v, str)]


def _asserts_genuine(payload) -> bool:
    blob = " ".join(_string_values(payload)).lower()
    return any(m in blob for m in _GENUINE_CLAIM_MARKERS)


def _mk(cap_model, worst_dyn_mv=106.0, static_tr_mv=53.0, vdd_v=1.8, ratio=2.0):
    return E.build_result(
        worst_dyn_mv=worst_dyn_mv, vdd_v=vdd_v, static_tr_mv=static_tr_mv,
        ratio=ratio, package_droop_mv=None, power_net="VDD", period_ns=8.0,
        period_source="sdc_create_clock", steps=100, timestep_s=1e-11,
        current_model="vectorless", cap_model=cap_model)


# --------------------------------------------------------------------------
# THE DEFECT (bidirectional negative control) — a quasi-static payload must be
# flagged as a bound and must NOT claim genuineness. Pre-fix, build_result
# emitted "genuine dynamic droop, not a static echo" here and carried no
# scaled_static_bound key, so BOTH asserts fail against the byte-identical
# pre-fix source.
# --------------------------------------------------------------------------
def test_quasi_static_is_flagged_and_not_called_genuine():
    r = _mk("quasi-static")
    assert r["scaled_static_bound"] is True, (
        "a quasi-static (no-decap) transient number is a fixed scaling of the "
        "static solve; the payload must flag it as a scaled-static bound"
    )
    assert not _asserts_genuine(r), (
        "the artefact still claims the quasi-static number is a genuine "
        "dynamic droop / 'not a static echo' — the exact misrepresentation "
        f"measured on caravel and spm. payload strings: {_string_values(r)!r}"
    )


# --------------------------------------------------------------------------
# THE REVERSE CASE — a genuine decap-aware solve must STAY genuine. If the fix
# over-corrects into "flag everything as a bound", this flips.
# --------------------------------------------------------------------------
def test_reverse_decap_aware_solve_stays_genuine():
    r = _mk("on-die-cap 1e-12F")
    assert r["scaled_static_bound"] is False, (
        "a decap-aware transient solve is genuine; flagging it as a "
        "scaled-static bound fabricates a caveat and understates the tool"
    )
    assert "genuine" in " ".join(_string_values(r)).lower(), (
        "the decap-aware payload dropped its genuine-di/dt presentation"
    )


def test_undetermined_cap_model_is_conservatively_a_bound():
    """capacitance model unreadable -> genuineness cannot be asserted -> the
    conservative direction is to label a bound, never to claim genuine."""
    r = _mk(None)
    assert r["scaled_static_bound"] is True
    assert not _asserts_genuine(r)


# --------------------------------------------------------------------------
# Consumer distinguishability — the two tiers must be told apart by a
# MACHINE-READABLE field, not by parsing prose.
# --------------------------------------------------------------------------
def test_two_tiers_are_machine_distinguishable():
    quasi = _mk("quasi-static")
    decap = _mk("on-die-cap 1e-12F")
    assert quasi["scaled_static_bound"] != decap["scaled_static_bound"]


# --------------------------------------------------------------------------
# The measured captures — the real caravel / spm numbers must be flagged.
# dynamic == 2.00 x static under quasi-static is exactly the escape.
# --------------------------------------------------------------------------
def test_measured_caravel_capture_is_flagged():
    r = _mk("quasi-static", worst_dyn_mv=0.0728, static_tr_mv=0.0364, vdd_v=1.8)
    # sanity: this IS the 2.00x relationship, i.e. a scaled static echo
    assert abs(r["max_dynamic_drop_mv"] / r["static_from_transient_mv"] - 2.0) < 1e-6
    assert r["scaled_static_bound"] is True
    assert not _asserts_genuine(r)


def test_measured_spm_capture_is_flagged():
    r = _mk("quasi-static", worst_dyn_mv=14.3, static_tr_mv=7.15, vdd_v=5.0)
    assert abs(r["max_dynamic_drop_mv"] / r["static_from_transient_mv"] - 2.0) < 1e-6
    assert r["scaled_static_bound"] is True
    assert not _asserts_genuine(r)


# --------------------------------------------------------------------------
# The fix must not disturb what the gate reads, or the honest-real-solve
# language the existing test pins.
# --------------------------------------------------------------------------
def test_gate_still_consumes_the_payload():
    r = _mk("quasi-static")
    droop, vdd = G._extract_from_json(r)
    assert droop == 106.0 and vdd == 1.8


def test_solver_mechanics_still_disclosed():
    for cm in ("quasi-static", "on-die-cap 1e-12F", None):
        assert "backward-Euler" in _mk(cm)["disclosure"]
