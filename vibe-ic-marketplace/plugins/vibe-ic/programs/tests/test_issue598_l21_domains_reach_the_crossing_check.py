"""#598 — L21 and its consumer never agreed on a key, so no voltage arrived.

TWO SEPARABLE DEFECTS, both of the family this repo keeps finding: an absence
rendering as a pass.

1. THE KEY NOBODY SHARED. `parse_l21` read `voltage` / `nominal_voltage` /
   `supply_voltage`. Measured across the plugin, FOUR producers write the L21
   domain voltage and every one of them writes `voltage_v`:

       l21_doc_supply_rail_synth      voltage_v
       l21_macro_supply_rail_synth    voltage_v
       phase1_layer_demand_probe      voltage_v
       phase1_doc_one_shot_runner     voltage_v
       ---
       readers                        voltage / nominal_voltage / supply_voltage

   Nothing crossed. So every domain arrived with `voltage: null`, and

       needs_ls = abs(va - vb) > 1e-9   only when both are not None

   could never once be True. The 1.2 V and 1.8 V the layer DID state were
   dropped between the file and the check, and the level-shifter half of an M2
   blocking gate was inert on every design that reached it.

2. A RAIL DECLARATION IS NOT A DOMAIN. `l21_macro_supply_rail_synth` emits one
   entry per macro GROUND pin so the Phase-3 consumer can bind it, and pairs it
   with the design's primary `power_net` because that consumer requires one —
   a trade the program measured end-to-end (a null power net swaps an L21-1
   failure for an L21-2 failure, so it is NOT undone here). Read back as a
   power domain it becomes a phantom named after a ground pin, holding the
   1.2 V core rail at 0.0 V. The entry now says `is_power_domain: false` and
   the consumer skips it.

WHY FIXTURES CARRY THIS. The corpus cannot re-adjudicate it: 16 M2 step
artefacts are tracked and every one is a wrapper — `status: "na"`, `outputs:
[]`. The gate's own JSON was never committed, so 0 published reports change.
Measured, and stated rather than left as an implied clean sweep.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROG = Path(__file__).parent.parent
sys.path.insert(0, str(PROG))

import pytest  # noqa: E402

import power_domain_signal_crossing_check as pdsc  # noqa: E402


@pytest.fixture(autouse=True)
def _restore_module_global():
    """`parse_l21` SETS the module-level `_L21_STATED_PROTECTION`, and every
    call here leaves it False (these fixtures declare no isolation or
    level-shifter list). Without this, the next FILE's end-to-end tests read a
    flag this one wrote and take the PROTECTION_UNSTATED branch instead of
    flagging — which is exactly what happened: two e2e tests in
    `test_power_domain_signal_crossing_check.py` failed together and passed in
    isolation.

    Benign in production, where one process audits one design. Recorded rather
    than only worked around, because a gate whose verdict depends on what ran
    before it is a real fragility even when the current caller cannot hit it.
    """
    saved = pdsc._L21_STATED_PROTECTION
    yield
    pdsc._L21_STATED_PROTECTION = saved


# ── 1. the key every producer actually writes ────────────────────────────────
def test_voltage_v_is_read():
    """The whole defect in one assertion."""
    dom, _iso, _ls = pdsc.parse_l21(
        {"power_domains": [{"name": "CORE", "voltage_v": 1.2},
                           {"name": "IOVDD", "voltage_v": 1.8}]})
    assert dom["core"]["voltage"] == 1.2
    assert dom["iovdd"]["voltage"] == 1.8


def test_the_older_key_names_still_work():
    """`voltage_v` is preferred, not exclusive — the 6 voltage-bearing entries
    in the tracked corpus use `voltage`, with a STRING value."""
    dom, _i, _l = pdsc.parse_l21(
        {"power_domains": [{"name": "core", "voltage": "1.8V"},
                           {"name": "io", "nominal_voltage": 3.3},
                           {"name": "aux", "supply_voltage": 5}]})
    assert dom["core"]["voltage"] == 1.8
    assert dom["io"]["voltage"] == 3.3
    assert dom["aux"]["voltage"] == 5.0


def test_a_level_shifter_is_now_derivable_at_all():
    """LOAD-BEARING, and the reason the key mattered. With every voltage null,
    `needs_ls` was False for every pair on every design."""
    dom, _i, _l = pdsc.parse_l21(
        {"power_domains": [{"name": "CORE", "voltage_v": 1.2},
                           {"name": "IOVDD", "voltage_v": 1.8}]})
    _iso, needs_ls = pdsc.required_protection("core", "iovdd", dom)
    assert needs_ls is True
    # ... and equal voltages still must NOT ask for one
    dom2, _i, _l = pdsc.parse_l21(
        {"power_domains": [{"name": "A", "voltage_v": 1.8},
                           {"name": "B", "voltage_v": 1.8}]})
    assert pdsc.required_protection("a", "b", dom2)[1] is False


def test_an_unknown_voltage_is_still_not_treated_as_a_difference():
    """The refusal must not overshoot into inventing a crossing."""
    dom, _i, _l = pdsc.parse_l21(
        {"power_domains": [{"name": "A", "voltage_v": 1.8}, {"name": "B"}]})
    assert dom["b"]["voltage"] is None
    assert pdsc.required_protection("a", "b", dom)[1] is False


# ── 2. a ground rail declaration is not a power domain ───────────────────────
def test_a_rail_declaration_is_not_built_into_a_domain():
    """The phantom from the issue, verbatim: named after a GROUND pin, carrying
    the design's 1.2 V core rail, at 0.0 V."""
    dom, _i, _l = pdsc.parse_l21({"power_domains": [
        {"name": "CORE", "power_net": "CORE", "voltage_v": 1.2},
        {"name": "vss", "power_net": "CORE", "ground_net": "vss",
         "is_power_domain": False, "voltage_v": 0.0,
         "derived_from": {"macro_lef_pin_use": "GROUND"}}]})
    assert "vss" not in dom
    assert set(dom) == {"core"}


def test_an_entry_without_the_marker_is_unchanged():
    """Absence of the flag must not silently drop a real domain — every L-doc
    written before this change has no such key."""
    dom, _i, _l = pdsc.parse_l21(
        {"power_domains": [{"name": "PD_SW", "voltage_v": 1.0},
                           {"name": "AON", "voltage_v": 1.8}]})
    # `_norm` strips a leading `pd_`, which is pre-existing and deliberate —
    # noted here because the first version of this test asserted `pd_sw` and
    # failed on the normaliser rather than on anything #598 changed.
    assert set(dom) == {"sw", "aon"}


def test_the_l21_synth_marks_its_ground_entries():
    """The producer half. Asserted on the SOURCE because the emitter needs a
    macro LEF corpus to run; the pairing it keeps is deliberate and measured,
    so what is pinned is that the entry declares what it is."""
    src = (PROG / "l21_macro_supply_rail_synth.py").read_text(encoding="utf-8")
    assert '"is_power_domain": False' in src, (
        "ground rail entries no longer declare that they are not domains, so "
        "the consumer rebuilds the 0.0 V phantom on the 1.2 V rail")


# ── 3. nothing examined is not everything protected ──────────────────────────
def _domains(n=2, with_elements=True):
    d = {}
    for i in range(n):
        d[f"d{i}"] = {"voltage": 1.0 + i, "off_capable": False,
                      "elements": {f"u{i}"} if with_elements else set()}
    return d


def test_zero_crossings_examined_does_not_claim_protection():
    """`audit` over an empty crossing list returns no findings and n_inter 0 —
    the caller used to append ALL_CROSSINGS_PROTECTED on top of that, which is
    a claim about a denominator that was never established."""
    findings, n_inter, n_unprot = pdsc.audit(_domains(), set(), set(), [])
    assert (n_inter, n_unprot) == (0, 0)
    assert findings == []


def test_the_new_rule_names_the_absent_basis():
    """Pinned on the source: the branch must exist and must be reachable only
    when no crossing could be derived."""
    src = (PROG / "power_domain_signal_crossing_check.py").read_text(
        encoding="utf-8")
    assert "NO_CROSSINGS_DERIVED" in src
    assert "elif not crossings:" in src, (
        "the vacuous case is no longer split out from the protected case")
    assert src.index("elif not crossings:") < src.index(
        '"rule": "ALL_CROSSINGS_PROTECTED"'), (
        "the empty-basis branch must be taken BEFORE the protected claim")


def test_an_all_unknown_voltage_model_is_disclosed():
    src = (PROG / "power_domain_signal_crossing_check.py").read_text(
        encoding="utf-8")
    assert "VOLTAGE_UNSTATED" in src


def test_a_real_protected_crossing_still_passes(tmp_path):
    """The accept case. A fix that refused everywhere would satisfy every
    assertion above and destroy the gate."""
    dom = _domains()
    crossings = [{"net": "n0", "driver_domain": "d0", "receiver_domain": "d1"}]
    findings, n_inter, n_unprot = pdsc.audit(
        dom, {"d1"}, {"d0", "d1"}, crossings)
    assert n_inter == 1
    assert n_unprot == 0, [f["rule"] for f in findings]
