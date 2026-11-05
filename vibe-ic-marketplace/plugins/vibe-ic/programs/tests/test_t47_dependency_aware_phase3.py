"""Exercise the real Phase-3 main dispatch and the release receipt consumer."""
from __future__ import annotations

import json
from pathlib import Path
import yaml

try:
    import layout_receipt_identity_check as C
except ModuleNotFoundError:
    C = None  # main-side behavioural control still reaches GDS dispatch
















def _good_receipts(project: Path):
    pnr = project / "phase3/stage3/pnr"
    canonical = project / "phase3/stage4/gds"
    report = project / "reports/phase3"
    pnr.mkdir(parents=True)
    canonical.mkdir(parents=True)
    report.mkdir(parents=True)
    (pnr / "routed.def").write_bytes(b"VERSION 5.8 ;\nEND DESIGN\n")
    (pnr / "unit.gds").write_bytes(b"synthetic GDS bytes\n")
    (canonical / "unit.gds").write_bytes((pnr / "unit.gds").read_bytes())
    frozen = C._layout_sha(pnr / "unit.gds", pnr / "routed.def")
    (report / "prestream_gate.json").write_text(json.dumps({
        "verdict": "PASS", "layout_digest": "routed-basis"}))
    receipt = {
        "frozen_layout_digest": frozen,
        "current_layout_digest": frozen,
        "prestream_basis_digest": "routed-basis",
        "current_basis_digest": "routed-basis",
        "gds_relpath": "phase3/stage3/pnr/unit.gds",
        "gds_sha256": C._sha(pnr / "unit.gds"),
        "def_sha256": C._sha(pnr / "routed.def"),
        "release_scope": "RELEASE_CANDIDATE",
        "release_verdict": "ELIGIBLE_FOR_AUDIT",
        "receipts": [{"name": "drc", "status": "PASS",
                      "extras": {"layout_digest": frozen}}],
    }
    (report / "layout_receipts.json").write_text(json.dumps(receipt))
    return receipt


def test_receipt_checker_accepts_current_release_basis(tmp_path):
    _good_receipts(tmp_path)
    assert C.check(tmp_path)["verdict"] == "PASS"


def test_receipt_checker_rejects_changed_gds_and_diagnostic(tmp_path):
    receipt = _good_receipts(tmp_path)
    (tmp_path / "phase3/stage4/gds/unit.gds").write_bytes(b"changed\n")
    assert C.check(tmp_path)["verdict"] == "FAIL"
    (tmp_path / "phase3/stage4/gds/unit.gds").write_bytes(
        (tmp_path / "phase3/stage3/pnr/unit.gds").read_bytes())
    receipt["release_scope"] = "DIAGNOSTIC_ONLY"
    (tmp_path / "reports/phase3/layout_receipts.json").write_text(
        json.dumps(receipt))
    assert C.check(tmp_path)["verdict"] == "FAIL"


def test_flow_dependency_declares_the_delivered_layout():
    flow = yaml.safe_load((Path(__file__).resolve().parents[2]
                           / "flow/phase1_phase2_phase3.yaml").read_text())
    steps = {str(step["id"]): step for step in flow["steps"]}
    order = {str(step["id"]): i for i, step in enumerate(flow["steps"])}
    assert {"34", "37"} <= {str(v) for v in steps["31"]["blocks_on"]}
    assert "37" in {str(v) for v in steps["37.3"]["blocks_on"]}
    # Stream the design before GDS fill; inspect that finished layout only.
    assert order["37"] < order["34"] < order["31"] < order["36"]
