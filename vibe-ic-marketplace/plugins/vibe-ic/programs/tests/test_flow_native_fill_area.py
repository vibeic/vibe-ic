import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

import flow_engine


class Config(dict):
    def copy(self, **changes):
        return Config({**self, **changes})


class State(dict):
    metrics = {}

    def dumps(self):
        return "{}"


def run_filler(tmp_path, monkeypatch, *, delivery="gds", metadata=True, **settings):
    config = Config(CORE_AREA=[214.9, 214.9, 1953.1, 613.1], FP_ASPECT_RATIO=1,
                    FILL_INSERTION_AREA=None, KLAYOUT_DENSITY_RUNSET=None,
                    DECAP_CELLS=["operator_decap"], FILL_CELLS=["native_filler"])
    config.update(settings)
    if metadata:
        path = tmp_path / "work/flow/chip/preparation.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"geometry": {"mapped_cell_area_um2": 11907.7,
                                                "core_utilization_percent": 50}}))
    chain = flow_engine.NativeChain(tmp_path, {"delivery_target": delivery})
    chain.owner = SimpleNamespace(config=config, gating_config_vars={})
    chain.config = dict(config)
    chain.state = State()
    observed = []

    class Filler:
        def __init__(self, config, state):
            observed.append(config)
            self.state = state

        def start(self, **kwargs):
            return self.state

    steps = ModuleType("librelane.steps")
    steps.Step = SimpleNamespace(factory=SimpleNamespace(get=lambda name: Filler))
    steps.StepError = type("StepError", (Exception,), {})
    steps.StepException = type("StepException", (Exception,), {})
    monkeypatch.setitem(sys.modules, "librelane.steps", steps)
    result = chain.execute(tmp_path / "filler", {"steps": ["OpenROAD.FillInsertion"]})
    assert result.exit_code == 0
    assert chain.owner.config is config
    return config, observed[0]


@pytest.mark.parametrize("aspect", [1, 2])
def test_magic_chip_filler_uses_the_retained_area_utilization_and_aspect(tmp_path, monkeypatch, aspect):
    original, consumed = run_filler(tmp_path, monkeypatch, FP_ASPECT_RATIO=aspect)
    x0, y0, x1, y1 = consumed["FILL_INSERTION_AREA"]
    assert (x1 - x0) * (y1 - y0) == pytest.approx(11907.7 / .5)
    assert (y1 - y0) / (x1 - x0) == pytest.approx(aspect)
    assert ((x0 + x1) / 2, (y0 + y1) / 2) == pytest.approx((1084, 414))
    assert original["FILL_INSERTION_AREA"] is None
    assert consumed["CORE_AREA"] == original["CORE_AREA"]
    assert consumed["DECAP_CELLS"] == ["operator_decap"]
    assert consumed["FILL_CELLS"] == ["native_filler"]


@pytest.mark.parametrize("case", ["operator", "klayout", "ip", "no_metadata", "thin_core"])
def test_other_filler_configurations_reach_the_native_step_unchanged(tmp_path, monkeypatch, case):
    settings = {
        "operator": {"FILL_INSERTION_AREA": [300, 300, 500, 500]},
        "klayout": {"KLAYOUT_DENSITY_RUNSET": "/native/density.drc"},
        "ip": {"delivery": "ip_hardmacro"},
        "no_metadata": {"metadata": False},
        "thin_core": {"CORE_AREA": [0, 0, 100, 500]},
    }[case]
    original, consumed = run_filler(tmp_path, monkeypatch, **settings)
    assert consumed is original
