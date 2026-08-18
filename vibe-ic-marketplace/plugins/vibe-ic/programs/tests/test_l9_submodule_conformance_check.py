"""tests/test_l9_submodule_conformance_check.py

Covers the L9 submodule-conformance gate: cross-checks L9 Integration
Spec against rtl/*.sv|.v module declarations. Six cases (top-level pin
checks live in the sibling Wave 79 gate l9_rtl_pin_consistency_check):

  1. happy path — submodules all present + instantiated             PASS
  2. L9 lists a submodule with no `module` decl in rtl/             FAIL
  3. submodule declared but never instantiated                      FAIL
  4. schema v1 submodule-port direction drift                       FAIL
  5. no L9 at all                                                   VACUOUS
  6. L9 present but empty (no submodules)                           VACUOUS
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from programs.l9_submodule_conformance_check import audit, parse_module_ports


# --- Tiny helpers -----------------------------------------------------------

def _write_l9(project: Path, body: dict) -> None:
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(body))


def _write_rtl(project: Path, name: str, body: str) -> None:
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / name).write_text(body)


CHIP_TOP_RTL = """\
module chip_top (
    input  wire        clk,
    input  wire        reset_n,
    inout  wire        id_bus
);
    rx_phy u_rx (.clk(clk), .rst_n(reset_n), .bus(id_bus));
    tx_phy u_tx (.clk(clk), .rst_n(reset_n), .bus(id_bus));
endmodule
"""

RX_PHY_RTL = """\
module rx_phy (
    input  wire clk,
    input  wire rst_n,
    inout  wire bus
);
endmodule
"""

TX_PHY_RTL = """\
module tx_phy (
    input  wire clk,
    input  wire rst_n,
    inout  wire bus
);
endmodule
"""


# --- 1. happy path ----------------------------------------------------------

def test_happy_path_passes(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _write_rtl(p, "chip_top.sv", CHIP_TOP_RTL)
    _write_rtl(p, "rx_phy.sv", RX_PHY_RTL)
    _write_rtl(p, "tx_phy.sv", TX_PHY_RTL)
    _write_l9(p, {
        "schema_version": 2,
        "submodules": [{"name": "rx_phy"}, {"name": "tx_phy"}],
    })
    verdict, findings = audit(p)
    assert verdict == "PASS", f"unexpected findings: {findings}"


# --- 2. submodule listed in L9 but no RTL file -----------------------------

def test_submodule_file_missing_fails(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _write_rtl(p, "chip_top.sv", CHIP_TOP_RTL)
    _write_rtl(p, "rx_phy.sv", RX_PHY_RTL)
    # tx_phy.sv intentionally omitted
    _write_l9(p, {
        "schema_version": 2,
        "submodules": [{"name": "rx_phy"}, {"name": "tx_phy"}],
    })
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    rules = [f for f in findings if f.rule == "SUBMODULE_FILE_MISSING"]
    assert len(rules) == 1 and rules[0].module == "tx_phy"


# --- 5. submodule declared but not instantiated -----------------------------

DEAD_TOP_RTL = """\
module chip_top (
    input  wire clk,
    input  wire reset_n,
    inout  wire id_bus
);
    rx_phy u_rx (.clk(clk), .rst_n(reset_n), .bus(id_bus));
    // tx_phy not instantiated
endmodule
"""


def test_submodule_not_instantiated_fails(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _write_rtl(p, "chip_top.sv", DEAD_TOP_RTL)
    _write_rtl(p, "rx_phy.sv", RX_PHY_RTL)
    _write_rtl(p, "tx_phy.sv", TX_PHY_RTL)  # exists but never instantiated
    _write_l9(p, {
        "schema_version": 2,
        "submodules": [{"name": "rx_phy"}, {"name": "tx_phy"}],
    })
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    dead = [f for f in findings if f.rule == "SUBMODULE_NOT_INSTANTIATED"]
    assert len(dead) == 1 and dead[0].module == "tx_phy"


# --- 6. schema-v1 submodule port direction drift ----------------------------

def test_schema_v1_submodule_port_drift_fails(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _write_rtl(p, "chip_top.sv", CHIP_TOP_RTL)
    _write_rtl(p, "rx_phy.sv", RX_PHY_RTL)
    _write_rtl(p, "tx_phy.sv", TX_PHY_RTL)
    _write_l9(p, {
        "schema_version": 1,
        "submodules": [
            {"name": "rx_phy", "ports": [
                {"name": "clk", "mode": "input"},
                {"name": "rst_n", "mode": "input"},
                {"name": "bus", "mode": "output"},  # actual is inout
            ]},
            {"name": "tx_phy"},
        ],
    })
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    drift = [f for f in findings if f.rule == "SUBMODULE_PORTS_DRIFT"]
    assert any("rx_phy" in f.module and "bus" in f.message for f in drift), drift


# --- 7. no L9 at all → VACUOUS_PASS -----------------------------------------

def test_no_l9_is_vacuous(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _write_rtl(p, "chip_top.sv", CHIP_TOP_RTL)
    verdict, findings = audit(p)
    assert verdict == "VACUOUS_PASS" and findings == []


# --- 8. empty L9 → VACUOUS_PASS ---------------------------------------------

def test_empty_l9_is_vacuous(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _write_l9(p, {"schema_version": 2})
    _write_rtl(p, "chip_top.sv", CHIP_TOP_RTL)
    verdict, findings = audit(p)
    assert verdict == "VACUOUS_PASS" and findings == []


# --- parser unit tests ------------------------------------------------------

def test_parser_handles_widths_and_comments() -> None:
    src = """
    module foo (
        input  wire        clk,
        // a comment line
        input  wire [7:0]  data,    /* inline block comment */
        output reg  [3:0]  q,
        inout              bus
    );
    endmodule
    """
    out = parse_module_ports(src)
    assert out["foo"] == [
        ("clk", "input"), ("data", "input"),
        ("q", "output"), ("bus", "inout"),
    ]


def test_parser_handles_parameter_block_and_logic_kw() -> None:
    src = """
    module bar #(parameter int W = 8) (
        input  logic           clk,
        output logic [W-1:0]   q
    );
    endmodule
    """
    out = parse_module_ports(src)
    assert out["bar"] == [("clk", "input"), ("q", "output")]


def test_parser_handles_sv_import_clause_in_header() -> None:
    """Real EXAMPLE_CHIP v0117-vendor RTL puts `import example_chip_pkg::*;` between the
    module name and the port-list opening paren. The parser must not get
    confused — original regex skipped these modules silently."""
    src = """
    module rx_phy
      import example_chip_pkg::*;
    (
      input  logic clk,
      input  logic rstn,
      output logic rx_bit
    );
    endmodule

    module mixed #(parameter W=8)
      import pkg_a::*;
      import pkg_b::sym;
    (
      input  logic clk,
      output logic [W-1:0] q
    );
    endmodule
    """
    out = parse_module_ports(src)
    assert out["rx_phy"] == [
        ("clk", "input"), ("rstn", "input"), ("rx_bit", "output"),
    ]
    assert out["mixed"] == [("clk", "input"), ("q", "output")]
