"""Regression coverage for per-port authoritative reset preservation.

The reset/clock alias transform is ADVISORY: it may rescue an alternate public
spelling, but it must not replace a reset spelling explicitly named by the
authoritative top-port contract merely because generated RTL has gained another
legitimate port.  The controls below exercise both directions: preserve a
contract spelling on an evolved interface, while retaining the alias rescue
when the contract actually requests the canonical variant.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import design_one_shot_runner as R  # noqa: E402
import reset_clock_variant_alias as V  # noqa: E402


_RTL_WITH_EVOLVED_OUTPUT = """module dut (
    input wire clk,
    input wire reset,
    input wire [7:0] data_in,
    output wire [7:0] data_out,
    output wire ready
);
  assign data_out = reset ? 8'd0 : data_in;
  assign ready = !reset;
endmodule
"""


def _stage_project(project: Path, contract_reset: str, *, evolved: bool) -> Path:
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    source = rtl / "dut.v"
    source.write_text(
        _RTL_WITH_EVOLVED_OUTPUT if evolved else
        _RTL_WITH_EVOLVED_OUTPUT.replace(",\n    output wire ready", "")
        .replace("\n  assign ready = !reset;", "")
    )
    docs = project / "phase1" / "generated_docs"
    docs.mkdir(parents=True)
    names = ["clk", contract_reset, "data_in", "data_out"]
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "dut",
        "top_ports": [{"name": name} for name in names],
    }))
    return source


def _top_ports(source: Path, top: str) -> set[str]:
    return {port[2].lower()
            for port in V.parse_module_ports(source.read_text(), top)}


def test_evolved_interface_preserves_authoritative_reset_byte_for_byte(tmp_path):
    source = _stage_project(tmp_path, "reset", evolved=True)
    before = source.read_bytes()

    result = R.step_reset_clock_variant_aliases(tmp_path, "dut")

    assert result.status == "SKIP", (result.status, result.detail)
    assert source.read_bytes() == before
    assert _top_ports(source, "dut") == {
        "clk", "reset", "data_in", "data_out", "ready"}
    assert "authoritative" in result.detail.lower()
    assert "reset" in result.detail.lower()
    assert "preserv" in result.detail.lower()


def test_contract_requesting_true_variant_still_gets_alias(tmp_path):
    source = _stage_project(tmp_path, "rst", evolved=False)

    result = R.step_reset_clock_variant_aliases(tmp_path, "dut")

    assert result.status == "PASS", (result.status, result.detail)
    assert "aliased to canonical" in result.detail
    assert "dut__rcvar_inner" in source.read_text()
    assert _top_ports(source, "dut") == {"clk", "rst", "data_in", "data_out"}


def test_checked_in_fixture_sweep_keeps_authoritative_reset_ports(tmp_path):
    """Small real-artifact sweep over every paired L9/RTL test fixture."""
    fixture_root = Path(__file__).resolve().parent / "fixtures"
    exercised = []
    for l9_path in sorted(fixture_root.rglob("L9_INTEGRATION_SPEC.json")):
        project = l9_path.parents[2]
        rtl = project / "phase2" / "stage1" / "rtl"
        if not rtl.is_dir():
            continue
        data = json.loads(l9_path.read_text())
        top = data.get("top_module")
        declared = {
            item.get("name", "").lower()
            for item in data.get("top_ports", []) if isinstance(item, dict)
        }
        declared_resets = {name for name in declared if V.classify_reset(name)}
        if not top or not declared_resets:
            continue
        destination = tmp_path / f"fixture_{len(exercised)}"
        shutil.copytree(project, destination)
        bodies_before = R._rcvar_module_bodies(
            destination / "phase2" / "stage1" / "rtl", V)
        if top not in bodies_before:
            continue
        before_ports = _top_ports(bodies_before[top][0], top)
        present = declared_resets & before_ports
        if not present:
            continue

        result = R.step_reset_clock_variant_aliases(destination, top)
        bodies_after = R._rcvar_module_bodies(
            destination / "phase2" / "stage1" / "rtl", V)
        assert top in bodies_after, (l9_path, result.status, result.detail)
        assert present <= _top_ports(bodies_after[top][0], top), (
            l9_path, present, result.status, result.detail)
        exercised.append(l9_path.relative_to(fixture_root).as_posix())

    assert exercised, "real in-repo fixture sweep reached no eligible project"
