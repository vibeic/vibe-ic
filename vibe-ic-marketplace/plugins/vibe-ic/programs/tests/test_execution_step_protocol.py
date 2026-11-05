"""Behavioral coverage for source-bound requests and explicit factory routing."""
from argparse import Namespace
from dataclasses import dataclass
import json
from pathlib import Path


import execution_step_protocol as protocol








@dataclass
class _Options:
    root: Path
    enabled: bool


def test_parameters_round_trip_nested_paths_dataclasses_and_namespaces(tmp_path):
    parameters = {"options": _Options(tmp_path, True),
                  "namespace": Namespace(inputs=(tmp_path / "source.v", None)),
                  7: [1, 2.5, "text", False]}
    encoded = protocol.json_parameters(parameters)
    assert json.loads(json.dumps(encoded)) == {
        "options": {"root": str(tmp_path), "enabled": True},
        "namespace": {"inputs": [str(tmp_path / "source.v"), None]},
        "7": [1, 2.5, "text", False],
    }
    assert parameters["namespace"].inputs == (tmp_path / "source.v", None)


















def test_imported_result_carries_consumer_values_without_execution_claim():
    assert protocol.imported_result(step_id="9", outputs=["netlist.v"]) == {
        "status": "IMPORTED", "step_id": "9", "outputs": ["netlist.v"]}
