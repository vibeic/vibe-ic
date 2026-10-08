"""Focused A4 Controller input closure contract."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import execution_adapters_analog_front as front
from programs.tests._analog_producer_fixture import block, make_project


def test_a4_front_arm_stages_stimulus_and_provenance_sidecars(tmp_path, monkeypatch):
    project = make_project(tmp_path / "project", [block("alpha", "amplifier")])
    # Registry validation has its own source-closure controls. This test owns
    # only the input-contract census, so capture the Adapter before registration.
    monkeypatch.setattr(front, "_source_files", lambda _sha: {})
    class Capture:
        def __init__(self): self.adapters = []
        def register(self, adapter): self.adapters.append(adapter)
    registry = Capture()
    front.register_front_adapters(registry, project=project, source_sha="test-source")
    arm = next(item for item in registry.adapters if item.step_id == "A4")
    assert "phase3/analog/*/tb_*.sp" in arm.input_contract
    assert "phase2/analog/*/tb_*.sp" in arm.input_contract
    assert "phase3/analog/*/netlist_provenance.json" in arm.input_contract
    assert "phase2/analog/*/netlist_provenance.json" in arm.input_contract
