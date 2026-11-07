from decimal import Decimal
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("librelane")
from librelane.state import State
from librelane.steps import StepError

import flow_engine
import flow_pdn_rebuild as pdn


class Config(dict):
    def to_raw_dict(self):
        return dict(self)

    def copy(self, **updates):
        return Config({**self, **updates})


def config():
    return Config(PDN_CORE_RING_CONNECT_TO_PADS=True, DEFAULT_CORNER="nom_corner",
                  DIE_AREA=[0, 0, 100, 100], PDN_VWIDTH=Decimal("1.6"), PDN_HWIDTH=Decimal("1.6"),
                  PDN_CORE_RING_VWIDTH=Decimal("1.6"), PDN_CORE_RING_HWIDTH=Decimal("1.6"))


def power(project):
    path = project / "steps/post_cts_timing_repair/result.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"native_metrics": {"power__total__corner:nom_corner": .04,
                                                   "power__total__corner:old_fast": .5}}))


def test_post_cts_grid_uses_the_producing_default_corner_and_returns_matching_config_state(tmp_path, monkeypatch):
    power(tmp_path)
    original, state = config(), State()
    observed, calls = [], []

    def settings(project, native, span, *, metrics):
        assert metrics == {"power__total__corner:nom_corner": .04}
        return {"PDN_VWIDTH": 2.4, "PDN_CORE_RING_VWIDTH": 2.4}

    class NativeStep:
        id = "Native.Remove"

        def __init__(self, native, incoming):
            calls.append((self.id, native["PDN_VWIDTH"], incoming))

        def start(self, **kwargs):
            return State(metrics={"native_steps": len(calls)})

    class Generate(NativeStep):
        id = "OpenROAD.GeneratePDN"

    monkeypatch.setattr(pdn, "current_settings", settings)
    monkeypatch.setattr(pdn, "RipUpPDN", NativeStep)
    monkeypatch.setattr(pdn, "GeneratePDN", Generate)
    updated, result = pdn.resize(tmp_path, original, state, None, tmp_path / "pdn", observed.append)

    assert original["PDN_VWIDTH"] == Decimal("1.6")
    assert updated["PDN_VWIDTH"] == Decimal("2.4")
    assert result.metrics["native_steps"] == 2
    assert calls[0][2] is state
    assert calls[1][2].metrics["native_steps"] == 1
    assert all(row["exit_code"] == 0 for row in observed)
    assert [value for _, value, _ in calls] == [Decimal("2.4"), Decimal("2.4")]


@pytest.mark.parametrize("pad_connected", [False, True])
def test_unchanged_grid_and_ip_keep_their_original_config_and_state(tmp_path, monkeypatch, pad_connected):
    original, state = config(), State()
    original["PDN_CORE_RING_CONNECT_TO_PADS"] = pad_connected
    monkeypatch.setattr(pdn, "current_settings", lambda *args, **kwargs: {"PDN_VWIDTH": 1.6})
    updated, result = pdn.resize(tmp_path, original, state, None, tmp_path, lambda run: pytest.fail(str(run)))
    assert updated is original
    assert result is state


def test_routing_consumer_keeps_the_new_native_configuration_and_state(tmp_path, monkeypatch):
    import sys

    original, state = config(), State()
    updated, rebuilt = original.copy(PDN_VWIDTH=Decimal("2.4")), State(metrics={"rebuilt": 1})
    monkeypatch.setitem(sys.modules, "flow_pdn_rebuild", SimpleNamespace(resize=lambda *args: (updated, rebuilt)))
    chain = flow_engine.NativeChain(tmp_path, {"delivery_target": "shippable_gds"})
    chain.owner = SimpleNamespace(config=original, gating_config_vars={})
    chain.state, chain.config = state, original.to_raw_dict()
    monkeypatch.setattr(chain, "initialize", lambda: None)

    chain.execute(tmp_path, {"steps": [], "resize_pdn": True})

    assert chain.owner.config["PDN_VWIDTH"] == Decimal("2.4")
    assert chain.config["PDN_VWIDTH"] == Decimal("2.4")
    assert chain.state is rebuilt


def test_failed_generation_does_not_publish_a_partly_removed_state(tmp_path, monkeypatch):
    power(tmp_path)
    original, state = config(), State()
    monkeypatch.setattr(pdn, "current_settings", lambda *args, **kwargs: {"PDN_VWIDTH": 2.4})

    class Remove:
        id = "Native.Remove"

        def __init__(self, *args):
            pass

        def start(self, **kwargs):
            return State(metrics={"removed": 1})

    class FailedGeneration(Remove):
        id = "OpenROAD.GeneratePDN"

        def start(self, **kwargs):
            raise StepError("Native generation failed")

    monkeypatch.setattr(pdn, "RipUpPDN", Remove)
    monkeypatch.setattr(pdn, "GeneratePDN", FailedGeneration)
    chain = flow_engine.NativeChain(tmp_path, {"delivery_target": "shippable_gds"})
    chain.owner = SimpleNamespace(config=original, gating_config_vars={})
    chain.state, chain.config = state, original.to_raw_dict()
    monkeypatch.setattr(chain, "initialize", lambda: None)

    result = chain.execute(tmp_path, {"steps": [], "resize_pdn": True})

    assert result.exit_code == 1
    assert result.native_steps[1]["status"] == "FAIL"
    assert chain.state is state
    assert chain.owner.config is original
