import json

from flow_engine import choose_tool, design_features, predicate
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def table():
    return json.loads((ROOT / "flow/steps.json").read_text())


def test_ic_keeps_native_spare_floor_and_zero_defects(tmp_path):
    generated = table()
    features = design_features(tmp_path, {"delivery_target": "shippable_gds"}, generated)
    row = next(row for row in generated["steps"] if row["name"] == "spare_cells_and_eco_preparation")
    assert features["requires_spares"] is True
    assert predicate(row["when"], features)
    assert choose_tool(row["tool"], features)["steps"] == ["VibeIC.SpareCells"]
    active = {c["metric"]: c for c in row["checks"] if predicate(c.get("when", "always"), features)}
    assert active["spare_density_fraction"]["limit"] == 0.02
    assert all(c["limit"] == 0 for name, c in active.items() if name != "spare_density_fraction")


def test_non_ic_explicit_spares_keep_their_engineering_checks(tmp_path):
    docs = tmp_path / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L1.json").write_text(json.dumps({"features": {"requires_spares": True}}))
    generated = table()
    features = design_features(tmp_path, {"delivery_target": "ip_hardmacro"}, generated)
    row = next(row for row in generated["steps"] if row["name"] == "spare_cells_and_eco_preparation")
    active = {c["metric"] for c in row["checks"] if predicate(c.get("when", "always"), features)}
    assert active == {"required_spare_distribution", "spare_tie_connectivity_errors"}
