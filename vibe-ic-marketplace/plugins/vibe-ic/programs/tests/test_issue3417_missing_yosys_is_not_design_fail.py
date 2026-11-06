"""Regression controls for #3417: tool absence is not a design verdict."""
import importlib
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

H = importlib.import_module("rtl_hygiene_lint")


LEAF = "module leaf(input a, output y); assign y = a; endmodule\n"
TOP = """module top(input source, output result);
wire routed;
leaf u_leaf(.a(source), .y(routed));
assign result = routed;
endmodule
"""


def test_missing_host_yosys_is_blocking_not_measured(tmp_path, monkeypatch, capsys):
    leaf, top = tmp_path / "leaf.v", tmp_path / "top.v"
    leaf.write_text(LEAF)
    top.write_text(TOP)
    report = tmp_path / "rtl_hygiene.json"

    monkeypatch.delenv("VIBEIC_EDA_IMAGE", raising=False)
    monkeypatch.delenv("IIC_EDA_IMAGE", raising=False)
    monkeypatch.setattr(
        H._pr, "run",
        lambda *a, **k: (_ for _ in ()).throw(
            FileNotFoundError("COMMAND_NOT_FOUND: 'yosys'")))
    monkeypatch.setattr(sys, "argv", [
        str(PROGRAMS / "rtl_hygiene_lint.py"), str(leaf), str(top),
        "--top", "top", "--severity", "ERROR", "--json", str(report)])

    rc = H.main()
    stdout = capsys.readouterr().out
    findings = json.loads(report.read_text())
    context = json.loads(next(tmp_path.glob(
        "native-elaboration-*/context.json")).read_text())

    assert rc == 2
    assert "NOT_MEASURED [EXECUTION_ERROR]" in stdout
    assert "NATIVE_TOOL_ABSENT: Yosys" in stdout
    assert context["status"] == "NOT_MEASURED"
    assert context["reason_class"] == "tool_absent"
    assert context["capability"] == "yosys"
    assert {f["rule"] for f in findings} <= {
        "native-elaboration-unresolved",
        "instance-driver-analysis-unresolved",
    }






def test_real_undriven_wire_still_returns_design_fail(tmp_path, monkeypatch):
    top = tmp_path / "top.v"
    top.write_text("module top(output result); wire missing; assign result=missing; endmodule\n")
    report = tmp_path / "rtl_hygiene.json"
    monkeypatch.setattr(
        H, "_native_driver_view",
        lambda *a, **k: (_ for _ in ()).throw(
            H.NativeElaborationCapabilityAbsent(
                "NATIVE_TOOL_ABSENT: Yosys test control")))
    monkeypatch.setattr(sys, "argv", [
        str(PROGRAMS / "rtl_hygiene_lint.py"), str(top),
        "--top", "top", "--severity", "ERROR", "--json", str(report)])

    assert H.main() == 1
    findings = json.loads(report.read_text())
    assert any(f["rule"] == "undriven-wire" for f in findings)
