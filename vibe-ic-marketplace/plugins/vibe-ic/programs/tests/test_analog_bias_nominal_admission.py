"""An independently reproduced fixed-reference case must retain nominal refusal."""
import json

from _analog_producer_fixture import A1, A2, run_prog, make_project, block, bdir
from test_analog_a2_delta_sigma_spec_bound import ds_specs


def test_declared_anchor_with_unmet_nominal_settling_is_not_admitted(tmp_path):
    root = tmp_path / "nominal"
    root.mkdir()
    make_project(root, [block("mod_alpha", "delta_sigma", ds_specs(vref=.5))])
    first = run_prog(A1, root)
    assert first.returncode == 0, first.stdout + first.stderr
    directory = bdir(root, "mod_alpha")
    directory.mkdir(parents=True, exist_ok=True)
    declaration = {
        "reference": {"resistor_length_um": 900.},
        "stages": {"1": {"output_load_ff": 400.}},
        "channel_current_budget_a": .0009,
        "fixed_current_a": 0.,
        "citation": "Independent review: fixed reference with a declared heavy load; retain nominal settling refusal",
    }
    (directory / "bias_network_inputs.json").write_text(json.dumps(declaration))
    result = run_prog(A2, root, "--pdk", "ihp-sg13g2")
    evidence = {"rc": result.returncode, "stdout": result.stdout,
                "stderr": result.stderr, "declaration": declaration}
    for name in ("topology_gap.json", "topology.json"):
        path = directory / name
        if path.exists():
            evidence[name] = json.loads(path.read_text())
    (tmp_path / "nominal-counter.json").write_text(json.dumps(evidence, indent=2))
    assert result.returncode == 2, result.stdout + result.stderr
    gap = json.loads((directory / "topology_gap.json").read_text())
    assert gap["status"] == "ENTRY_REQUIREMENTS_NOT_MET"
    refusals = [r for r in gap["admission_refusals"]
                if r.get("field") == "settling_time_constants"]
    assert refusals
    assert all(r["value"] < r["min"] for r in refusals)
    assert not (directory / "topology.json").exists()
