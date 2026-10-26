"""Focused residual evidence for source-width dense A5 terminal access."""
from types import SimpleNamespace

import pytest

import _plugin_tree  # noqa: F401
import analog_a5_layout_emit as layout
import analog_a5_pdk_device_limits as limits


CELL = """magic
magscale 1 1
<< metal1 >>
rect -120 -94 120 -74
rect -120 74 120 94
rect -120 -74 -100 74
rect 100 -74 120 74
<< metal2 >>
rect -54 -22 -34 22
rect 34 -22 54 22
rect -14 32 14 62
<< labels >>
rlabel metal1 0 -84 0 -84 0 B
rlabel metal2 -44 0 -44 0 0 D
rlabel metal2 44 0 44 0 0 S
rlabel metal2 0 47 0 47 0 G
<< end >>
"""


def _geo(metal3_minimum_um: float) -> layout.Geo:
    """Build routing geometry with an explicit source-declared M3 width."""
    widths = {layer: 0.20 for layer in range(1, 8)}
    source = f'width allm3 {int(metal3_minimum_um * 1000)} "Metal3 width"\n'
    widths.update(limits.deck_rules(source)["metal_width_um"])
    rules = {
        "metal_space_um": {layer: 0.21 for layer in range(1, 8)},
        "metal_width_um": widths,
        "metal_area_um2": {2: 0.144, 3: 0.144},
        "via_width_um": {layer: 0.20 for layer in range(1, 7)},
        "via_space_um": {layer: 0.21 for layer in range(1, 7)},
        "via_surround_um": {},
        "via_surround_dir_um": {},
    }
    return layout.Geo(rules, 0.21, 100, 0.60, 0.35)


def _build(monkeypatch: pytest.MonkeyPatch, minimum_um: float) -> layout.Plan:
    """Use the ordinary build_plan producer on the dense native fixture."""
    device = {
        "name": "unit",
        "model": "native_mos",
        "class": "mosfet",
        "nets": ["drain", "gate", "source", "body"],
        "pars": {"w": 0.5, "l": 0.5, "m": 1},
    }
    cell = layout.parse_cell(CELL)
    cell.update(bbox=(-141, -130, 141, 130), delta=(141, 130))
    facts = SimpleNamespace(
        layers=None,
        gencells={"native_mos": {
            "namespace": "provider", "params": ["w", "l", "m", "guard"]}},
    )
    monkeypatch.setattr(layout, "ring_layer_of", lambda _: "metal1")
    monkeypatch.setattr(
        layout, "body_tap_direct_m1_layer", lambda *args: "metal1")
    monkeypatch.setattr(
        layout, "choose_tap", lambda *args: (-80, -84, 100, False))
    return layout.build_plan(
        [device], device["nets"], {layout.config_key(device): cell},
        facts, _geo(minimum_um), 0)


@pytest.mark.parametrize("source_width_um", [0.20, 0.28])
def test_ordinary_producer_consumes_source_width_without_shorting(
        monkeypatch: pytest.MonkeyPatch, source_width_um: float) -> None:
    plan = _build(monkeypatch, source_width_um)

    assert plan.access_necks, "the dense native fixture must exercise a neck"
    assert {record["source_minimum_width_um"] for record in plan.access_necks} \
        == {source_width_um}
    assert {record["actual_width_um"] for record in plan.access_necks} \
        == {source_width_um}
    assert layout.net_shorts(plan) == []


def test_requested_width_counterexample_merges_dense_access() -> None:
    """Requested-width squares merge where source-width squares stay apart."""
    source_width = _geo(0.20).rules["metal_width_um"][3]

    def dense_access(width_um: float) -> layout.Plan:
        half = int(width_um * 100 / 2)
        plan = layout.Plan()
        for net, x, y in (("drain", -44, 0), ("source", 44, 0),
                          ("gate", 0, 47)):
            plan.paint(net, "metal3", x - half, y - half,
                       x + half, y + half)
        return plan

    assert layout.net_shorts(dense_access(source_width)) == []
    shorts = layout.net_shorts(dense_access(0.60))
    assert shorts, "the requested 0.60um access must remain a failing control"
    assert any({"drain", "gate"}.issubset(record["nets"])
               for record in shorts)
