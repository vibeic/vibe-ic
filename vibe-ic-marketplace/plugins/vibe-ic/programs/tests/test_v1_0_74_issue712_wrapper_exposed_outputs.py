"""ORGANIC #712 — l9_rtl_pin reconcile had no symmetric path for an RTL-only
struct-flattened reused-IP OUTPUT that is ABSENT from L9.

DEFECT (round-10 v1.0.73 6-IC clean-room; OpenTitan-AES catalog-glue wrapper):
  The existing flattened_buses / prefix-expansion only reconciles an L9-root →
  RTL-pad expansion (an INPUT-with-an-L9-root). A reused-IP wrapper that exposes
  struct-flattened IP OUTPUTS L9 lacks ENTIRELY (e.g. alert_fatal_o / alert_recov_o
  assigned from an alert_tx struct, with ZERO 'alert' token anywhere in L9) had
  NO chip-agnostic reconcile path → forced a per-run waiver on every such SoC.

FIX (chip-AGNOSTIC): reconcile_reused_ip honours a manifest
  `wrapper_exposed_outputs` (alias `flattened_outputs` / `exposed_outputs`) key
  listing the EXACT RTL output names L9 legitimately lacks → dropped from
  residual_rtl (advisory).

§4.05 NO-LEAK: keyed ONLY on the manifest's declared name set under reused_ip=true
  — an undeclared extra RTL port still FAILs; the existing flattened_buses
  prefix-expansion (#659 positive case) is unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import l9_rtl_pin_consistency_check as G  # noqa: E402

_EXPOSED_MF = {
    "reused_ip": True,
    "wrapper_exposed_outputs": ["alert_fatal_o", "alert_recov_o"],
}


def test_exposed_outputs_declared_reconcile():
    """END-STATE: manifest-declared wrapper-exposed outputs leave residual_rtl."""
    res_l9, res_rtl, tied, pm = G.reconcile_reused_ip(
        [], ["alert_fatal_o", "alert_recov_o"], _EXPOSED_MF)
    assert res_rtl == [], res_rtl
    assert any(lbl == "(wrapper-exposed-output)" for lbl, _ in pm)


def test_exposed_outputs_alias_keys():
    """Either alias key (`flattened_outputs` / `exposed_outputs`) is honoured."""
    for key in ("flattened_outputs", "exposed_outputs"):
        mf = {"reused_ip": True, key: ["alert_fatal_o"]}
        _, res_rtl, _, _ = G.reconcile_reused_ip([], ["alert_fatal_o"], mf)
        assert res_rtl == [], (key, res_rtl)


def test_noleak_undeclared_output_still_fails():
    """§4.05: an RTL-only output NOT in the manifest still surfaces as residual."""
    res_l9, res_rtl, tied, pm = G.reconcile_reused_ip(
        [], ["alert_fatal_o", "rogue_undeclared_o"], _EXPOSED_MF)
    assert res_rtl == ["rogue_undeclared_o"], res_rtl


def test_noleak_no_manifest_key_no_relaxation():
    """§4.05: a reused-IP manifest WITHOUT the key gives no relaxation."""
    res_l9, res_rtl, tied, pm = G.reconcile_reused_ip(
        [], ["alert_fatal_o", "alert_recov_o"], {"reused_ip": True})
    assert set(res_rtl) == {"alert_fatal_o", "alert_recov_o"}


def test_659_prefix_expansion_unchanged():
    """Regression: the existing L9-root → RTL-pad prefix-expansion (#659) is not
    affected by the new output-side key."""
    res_l9, res_rtl, tied, pm = G.reconcile_reused_ip(
        ["tl"], ["tl_a_valid", "tl_d_ready"], _EXPOSED_MF)
    assert res_l9 == [] and res_rtl == []
    assert any(root == "tl" for root, _ in pm)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
