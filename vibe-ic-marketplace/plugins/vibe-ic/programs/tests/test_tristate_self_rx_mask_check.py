"""Unit tests for tristate_self_rx_mask_check.py."""
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "tristate_self_rx_mask_check.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"
sys.path.insert(0, str(SCRIPT.parent))

import tristate_self_rx_mask_check as chk  # noqa: E402


# ---------------------------------------------------------------------------
# PASS paths
# ---------------------------------------------------------------------------
def test_no_inout_passes(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "plain.v").write_text(
        "module plain (input wire clk, output wire y);\n"
        "  assign y = clk;\nendmodule\n"
    )
    findings, summary = chk.audit(rtl)
    assert summary["inouts"] == []
    assert not any(f.severity == "ERROR" for f in findings)


def test_properly_masked_passes(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "pad.v").write_text(
        "module pad (\n"
        "  inout wire id_bus,\n"
        "  input wire id_bus_oe,\n"
        "  output wire id_bus_rx_msk,\n"
        "  input wire id_bus_rx\n"
        ");\n"
        "  assign id_bus_rx_msk = id_bus_oe ? 1'b1 : id_bus_rx;\n"
        "endmodule\n"
    )
    findings, summary = chk.audit(rtl)
    errors = [f for f in findings if f.severity == "ERROR"]
    assert not errors
    assert "id_bus" in summary["inouts"]


def test_inout_with_no_oe_is_skipped(tmp_path):
    """Inout present but no <W>_oe → not a driven bus; skip."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "sense.v").write_text(
        "module sense (\n"
        "  inout wire some_pad,\n"
        "  output wire some_pad_rx\n"
        ");\n"
        "  assign some_pad_rx = some_pad;\n"
        "endmodule\n"
    )
    findings, _ = chk.audit(rtl)
    # No <W>_oe signal, so no check — must not flag.
    assert not any(f.severity == "ERROR" for f in findings)


# ---------------------------------------------------------------------------
# FAIL paths
# ---------------------------------------------------------------------------
def test_raw_tap_assign_fails(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "bad.v").write_text(
        "module bad (\n"
        "  inout wire foo_bus,\n"
        "  input wire foo_bus_oe,\n"
        "  input wire foo_bus_tx,\n"
        "  output wire foo_bus_rx\n"
        ");\n"
        "  assign foo_bus_rx = foo_bus;\n"   # raw — no mask
        "endmodule\n"
    )
    findings, _ = chk.audit(rtl)
    errors = [f for f in findings if f.severity == "ERROR"]
    assert len(errors) == 1
    assert errors[0].category == "RAW_TAP_ASSIGN"
    assert errors[0].signal == "foo_bus_rx"


def test_missing_dir_fails(tmp_path):
    findings, _ = chk.audit(tmp_path / "does_not_exist")
    assert any(f.category == "IO" and f.severity == "ERROR"
               for f in findings)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------
def test_cli_passes_on_ok_rtl(tmp_path, capsys):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "pad.v").write_text(
        "module pad (inout wire b, input wire b_oe,\n"
        "            input wire b_rx, output wire b_rx_msk);\n"
        "  assign b_rx_msk = b_oe ? 1'b1 : b_rx;\n"
        "endmodule\n"
    )
    rc = chk.main(["--rtl-dir", str(rtl)])
    assert rc == 0


def test_cli_fails_on_bad_rtl(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "bad.v").write_text(
        "module bad (inout wire x, input wire x_oe,\n"
        "            output wire x_rx);\n"
        "  assign x_rx = x;\n"
        "endmodule\n"
    )
    rc = chk.main(["--rtl-dir", str(rtl)])
    assert rc == 1


def test_cli_writes_json_report(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "plain.v").write_text("module empty; endmodule\n")
    out = tmp_path / "rep.json"
    rc = chk.main(["--rtl-dir", str(rtl), "--json", str(out)])
    assert rc == 0
    assert out.exists()
    import json as _json
    data = _json.loads(out.read_text())
    assert data["summary"]["pass"] is True
