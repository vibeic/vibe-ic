import json

import flow109
import flow109_clock_plan as clock


def _profile():
    return next(item["features"] for item in flow109.load_registry()["reference_profiles"]
                if item["name"] == "Small digital IC without DFT")


def test_missing_sdc_refuses_before_clock_native_launch(tmp_path):
    floorplan = tmp_path / "phase3/stage3/pnr/floorplan.def"
    floorplan.parent.mkdir(parents=True)
    floorplan.write_text("VERSION 5.8 ;\nDESIGN chip_top ;\nEND DESIGN\n")
    pdk = tmp_path / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
    pdk.parent.mkdir(parents=True)
    pdk.write_text(json.dumps({"fields": {"pdk_target": "gf180mcuD"}}))
    plan = flow109.resolve_plan(_profile())
    context = flow109.execution_context(plan, "D34", "D34")

    result = clock.execute(tmp_path, context)

    assert result["component_status"] == "NOT_MEASURED"
    assert result["reason"] == "D34_SDC_ABSENT"
    assert result["native_started"] is False
    assert result["flow109_acceptance"] == "NOT_MEASURED"
    assert not (tmp_path / clock.OUTPUT).exists()
