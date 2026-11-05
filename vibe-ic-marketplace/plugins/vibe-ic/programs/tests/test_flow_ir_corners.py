import json
from decimal import Decimal
from pathlib import Path
import sys

import pytest

pytest.importorskip("librelane")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import flow_ir_corners as ir




class Config(dict):
    def copy(self, **overrides):
        return Config(self, **overrides)


class Toolbox:
    def filter_views(self, config, libraries):
        return [libraries[config["DEFAULT_CORNER"]]]

    def get_lib_voltage(self, library):
        return {"slow.lib": Decimal("4.5"), "typical.lib": Decimal("5"),
                "fast.lib": Decimal("5.5")}[library]


@pytest.fixture
def setup(tmp_path, monkeypatch):
    calls = []

    class Native:
        def __init__(self, config, state):
            self.config, self.state = config, state

        def run(self, state, **kwargs):
            corner = self.config["DEFAULT_CORNER"]
            drop = {"max_ss": Decimal("0.225"), "max_tt": Decimal("0.24"),
                    "max_ff": Decimal("0.25")}[corner]
            return {}, {"ir__drop__worst": drop, "ir__analysed_net__count": 2}

        def start(self, toolbox, step_dir, **kwargs):
            calls.append((self.config, self.state, toolbox, step_dir, Path.cwd()))
            self.run(self.state, **kwargs)

    monkeypatch.setattr(ir.IRDropCorners, "report_class", Native)
    step = object.__new__(ir.IRDropCorners)
    step.config = Config(STA_CORNERS=["min_ss", "max_ss", "max_tt", "max_ff", "nom_tt"],
                         DEFAULT_CORNER="nom_tt", LIB={"max_ss": "slow.lib", "max_tt": "typical.lib",
                                                       "max_ff": "fast.lib"})
    step.toolbox, step.step_dir = Toolbox(), str(tmp_path)
    return step, calls, Native


def test_runs_native_corners_on_same_state_and_uses_corner_voltages(setup, tmp_path):
    step, calls, _ = setup
    state = object()
    original_directory = Path.cwd()
    views, metrics = step.run(state)
    assert views == {}
    assert [call[0]["DEFAULT_CORNER"] for call in calls] == ["max_ss", "max_tt", "max_ff"]
    assert all(call[1] is state and call[2] is step.toolbox for call in calls)
    assert all(Path(call[3]).is_absolute() and Path(call[3]) == call[4] for call in calls)
    assert Path.cwd() == original_directory
    assert step.config["DEFAULT_CORNER"] == "nom_tt"
    assert metrics["ir__drop__worst"] == Decimal("0.25")
    assert metrics["ir__drop__worst__pct"] == pytest.approx(5)
    assert metrics["ir__drop__worst__pct__corner:max_tt"] == pytest.approx(4.8)
    assert metrics["ir__drop__worst__pct__corner:max_ff"] == pytest.approx(100 * .25 / 5.5)
    assert metrics["ir__analysed_net__count__corner:max_ss"] == 2
    summary = json.loads((tmp_path / "ir_corners.json").read_text())
    assert list(summary) == ["max_ss", "max_tt", "max_ff"]
    assert summary["max_ss"]["report"] == str(tmp_path / "max_ss/irdrop.rpt")


def test_configured_single_corner_is_sufficient(setup):
    step, calls, _ = setup
    step.config["STA_CORNERS"] = ["max_tt"]
    assert step.run(object())[1]["ir__drop__worst__pct"] == pytest.approx(4.8)
    assert len(calls) == 1


def test_no_maximum_rc_corner_is_not_measured(setup):
    step, calls, _ = setup
    step.config["STA_CORNERS"] = ["nom_tt"]
    with pytest.raises(ir.StepException, match="NOT_MEASURED.*maximum RC"):
        step.run(object())
    assert not calls


@pytest.mark.parametrize("voltage", [None, Decimal("0"), Decimal("-1"), Decimal("NaN")])
def test_missing_supply_voltage_is_not_measured(setup, monkeypatch, voltage):
    step, calls, _ = setup
    monkeypatch.setattr(step.toolbox, "get_lib_voltage", lambda library: voltage)
    with pytest.raises(ir.StepException, match="NOT_MEASURED.*voltage.*max_ss"):
        step.run(object())
    assert not calls


def test_native_failure_propagates_and_restores_directory(setup, monkeypatch):
    step, _, native = setup
    original_directory = Path.cwd()

    def fail(self, state, **kwargs):
        raise ir.StepException("native tool failure")

    monkeypatch.setattr(native, "run", fail)
    with pytest.raises(ir.StepException, match="native tool failure"):
        step.run(object())
    assert Path.cwd() == original_directory


def test_missing_native_drop_is_not_measured(setup, monkeypatch):
    step, _, native = setup
    monkeypatch.setattr(native, "run", lambda self, state, **kwargs: ({}, {}))
    with pytest.raises(ir.StepException, match="NOT_MEASURED.*worst drop.*max_ss"):
        step.run(object())
