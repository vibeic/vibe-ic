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
degenerates to a DETERMINISTIC scaling of the static drop. Measured over the
tracked corpus (8 `dynamic_ir.json`; 5 carry a capacitance model, all of them
`quasi-static`, 3 carry none):

  dynamic_static_ratio — the tool's OWN printed Dynamic/static figure —
  is 2.0 in 5 of 5, across different designs, PDKs, supplies and periods:

    caravel_user_project/v1.9.43_sky130A   ratio 2.0   0.0728 mv / 0.0364 mv
    spm/v1.5.66_gf180mcuD                  ratio 2.0   14.3   mv / 7.15   mv
    spm/v1.5.58_ihp-sg13g2                 ratio 2.0   2.21   mv / 1.1    mv
    spm/v1.5.65_sky130A                    ratio 2.0   (no static_from_transient_mv)
    sha256/clean_run_v1461_0223            ratio 2.0   48.6   mv / 0.0243 mv

A constant to three significant figures across that spread is the signature of
a fixed multiplier, not a di/dt solve — a real transient droop's ratio varies
with the RC network, decap and activity. So the number answers the STATIC
question scaled by a constant; a reader taking it as a transient result is
taking a scaled static result. The artefact's disclosure pre-excused exactly
that ratio ("a quasi-static solve yields ~2x") while asserting the number was
"not a static echo".

Stated precisely because the last two rows do NOT support the stronger claim.
`max_dynamic_drop_mv` equals 2.00x `static_from_transient_mv` in 3 of the 5:
one row carries no `static_from_transient_mv` at all, and one is 2000x, not
2x — its two fields plainly do not come from the same solve. That is a
separate, unrelated defect in what the emitter writes into those two keys, and
this file does not claim to have fixed it. The evidence that the quasi-static
tier is a scaling of the static solve is the tool's own constant ratio field,
which is 2.0 in all 5.

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

WHAT REMAINS UNMEASURED (disclosed, not fixed)
----------------------------------------------
The branch that still CLAIMS genuineness — `cap_model.startswith("on-die-cap")`
— has 0 of 8 tracked artefacts behind it. Nothing in the corpus has ever run
decap-aware: 5 artefacts declare `quasi-static`, 3 declare no capacitance model
at all, and none declares an on-die-cap model. So the surviving genuineness
assertion is the one no real run has ever exercised, and the tests below drive
it only through a synthetic `cap_model` string.

That is the honest shape of this change: it removes an unconditional claim that
was measurably false on every artefact that exists, and leaves a conditional
claim whose condition has never yet been true. Should a decap-aware solve ever
land, whether ITS number is a genuine di/dt result is a separate question this
file does not answer.

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
# THE DEFECT (bidirectional negative control) — a quasi-static payload must NOT
# claim genuineness, and must be flagged as a bound.
#
# ASSERT ORDER IS LOAD-BEARING HERE AND IN EVERY TEST BELOW. The substantive
# assertion — the false prose — comes FIRST; the new-key assertion comes
# second. Reversed, every one of these tests died pre-fix on
# `KeyError: 'scaled_static_bound'`, which demonstrates only that a key was
# added. A missing-attribute death is not a demonstration of the defect: it
# would look identical if the prose had never been wrong at all. In this order
# the pre-fix failure is `assert not _asserts_genuine(r)`, i.e. the artefact
# caught in the act of calling a scaled static number genuine.
# --------------------------------------------------------------------------
def test_quasi_static_is_flagged_and_not_called_genuine():
    r = _mk("quasi-static")
    assert not _asserts_genuine(r), (
        "the artefact still claims the quasi-static number is a genuine "
        "dynamic droop / 'not a static echo' — the exact misrepresentation "
        f"measured on caravel and spm. payload strings: {_string_values(r)!r}"
    )
    assert r["scaled_static_bound"] is True, (
        "a quasi-static (no-decap) transient number is a fixed scaling of the "
        "static solve; the payload must flag it as a scaled-static bound"
    )


# --------------------------------------------------------------------------
# THE REVERSE CASE — a genuine decap-aware solve must STAY genuine. If the fix
# over-corrects into "flag everything as a bound", this flips.
# --------------------------------------------------------------------------
def test_reverse_decap_aware_solve_stays_genuine():
    """PASSES IN BOTH DIRECTIONS, deliberately.

    An over-correction guard that dies on `KeyError` against the pre-fix
    source guards nothing: it cannot distinguish "the fix over-corrected"
    from "the fix is not applied yet". So both assertions are written to hold
    pre-fix AND post-fix, and to fail ONLY on the over-correction:

      * pre-fix  — the disclosure said "genuine" unconditionally, and
        `scaled_static_bound` did not exist, so `.get()` is None;
      * post-fix — the decap branch says "genuine", and the flag is False;
      * over-corrected (flag everything / strip "genuine" everywhere) —
        the flag is True and/or the word is gone. Both assertions fire.

    `is not True` rather than `is False` is what buys the pre-fix direction;
    the strict `is False` pin lives in
    `test_two_tiers_are_machine_distinguishable`, which is a post-fix
    assertion by construction.

    The prose assertion is `_asserts_genuine`, not a bare `"genuine" in ...`:
    the undetermined branch's own text contains the substring "genuine" inside
    the words "not a genuine di/dt result", so a bare substring test would have
    read an explicit DENIAL of genuineness as an assertion of it. Measured —
    under the over-correction mutation the bare form passed and only the flag
    assertion fired.
    """
    r = _mk("on-die-cap 1e-12F")
    assert _asserts_genuine(r), (
        "the decap-aware payload dropped its genuine-di/dt presentation: "
        f"{_string_values(r)!r}"
    )
    assert r.get("scaled_static_bound") is not True, (
        "a decap-aware transient solve is genuine; flagging it as a "
        "scaled-static bound fabricates a caveat and understates the tool"
    )


def test_undetermined_cap_model_is_conservatively_a_bound():
    """capacitance model unreadable -> genuineness cannot be asserted -> the
    conservative direction is to label a bound, never to claim genuine."""
    r = _mk(None)
    assert not _asserts_genuine(r), _string_values(r)
    assert r["scaled_static_bound"] is True


# --------------------------------------------------------------------------
# Consumer distinguishability — the two tiers must be told apart by a
# MACHINE-READABLE field, not by parsing prose.
# --------------------------------------------------------------------------
def test_two_tiers_are_machine_distinguishable():
    quasi = _mk("quasi-static")
    decap = _mk("on-die-cap 1e-12F")
    # Behavioural first, and it is the whole defect in one line: pre-fix the
    # disclosure was a CONSTANT, so these two payloads were indistinguishable
    # in every string they carried. That assertion fails pre-fix on a real
    # comparison, not on a missing key.
    assert quasi["disclosure"] != decap["disclosure"], (
        "both tiers carry the identical disclosure string; a reader cannot "
        "tell a scaled static bound from a genuine di/dt solve at all")
    # ... and the tiers must be told apart by a MACHINE-READABLE field, not by
    # parsing that prose. Strict values, post-fix.
    assert quasi["scaled_static_bound"] is True
    assert decap["scaled_static_bound"] is False


# --------------------------------------------------------------------------
# The measured captures — the real caravel / spm numbers must be flagged.
# dynamic == 2.00 x static under quasi-static is exactly the escape.
# --------------------------------------------------------------------------
def test_measured_caravel_capture_is_flagged():
    r = _mk("quasi-static", worst_dyn_mv=0.0728, static_tr_mv=0.0364, vdd_v=1.8)
    # sanity: this IS the 2.00x relationship, i.e. a scaled static echo
    assert abs(r["max_dynamic_drop_mv"] / r["static_from_transient_mv"] - 2.0) < 1e-6
    assert not _asserts_genuine(r), _string_values(r)
    assert r["scaled_static_bound"] is True


def test_measured_spm_capture_is_flagged():
    r = _mk("quasi-static", worst_dyn_mv=14.3, static_tr_mv=7.15, vdd_v=5.0)
    assert abs(r["max_dynamic_drop_mv"] / r["static_from_transient_mv"] - 2.0) < 1e-6
    assert not _asserts_genuine(r), _string_values(r)
    assert r["scaled_static_bound"] is True


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
