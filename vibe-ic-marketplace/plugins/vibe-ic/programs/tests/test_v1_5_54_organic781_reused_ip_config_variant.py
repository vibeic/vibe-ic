#!/usr/bin/env python3
"""ORGANIC #781 — reused-IP CONFIG-VARIANT surface reconciliation for
l9_rtl_pin_consistency_check.py.

A catalog-glue / reused-IP wrapper faithfully instantiates a SPECIFIC
configured vendor module and passes that module's REAL ports through to
chip_top 1:1. The L9 integration spec is extracted from the input datasheet
and frequently describes a DIFFERENT (fuller) variant of the same IP. The
resulting diff (config-gated L9 pins + IP-passthrough chip_top ports) is NOT a
wrapper defect. The gate reconciles it against the ACTUAL declared port surface
of the instantiated reused-IP module (chip-AGNOSTIC, no-leak):

  * PASS  — every residual L9-only pin is absent from the instantiated IP
            surface (config-gated) AND every residual chip_top port is a real
            declared IP port (passthrough).
  * FAIL  — an L9-only pin the instantiated IP DOES expose is missing from
            chip_top (a genuinely dropped IP port).
  * FAIL  — a chip_top port sourced from NO instantiated IP (invented port).

Chip-AGNOSTIC fixture: generic `core_ip` / `chip_top` names, no vendor literal.
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

PROG = (
    Path(__file__).resolve().parent.parent / "l9_rtl_pin_consistency_check.py"
)


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


# The instantiated IP core: a small config that exposes only a subset of the
# fuller variant the L9 doc documents.
_CORE_IP_SV = """\
module core_ip (
    input  wire        clk_i,
    input  wire        rst_ni,
    input  wire [31:0] data_i,
    output wire [31:0] data_o,
    output wire        alert_o,
    output wire        done_o
);
endmodule
"""


def _write_reused_ip_project(project: Path, chip_top_sv: str,
                             l9_ports: list[dict]) -> None:
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "core_ip.sv").write_text(_CORE_IP_SV)
    (rtl / "chip_top.sv").write_text(chip_top_sv)
    (rtl / "SOURCE_MANIFEST.json").write_text(json.dumps({
        "reused_ip": True,
        "ip_list": ["core_ip"],
        "rtl_strategy": "catalog_lookup_plus_ai_glue",
        "generated_by": "test_fixture",
        "renamed_interfaces": [],
        "flattened_buses": [],
    }, indent=2))
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "layer": "L9",
        "ic_name": "TEST",
        "top_module": "chip_top",
        "top_level_ports": l9_ports,
    }, indent=2))


# chip_top faithfully wraps core_ip (subset config). L9 documents the FULLER
# variant (extra secure/shadow ports the chosen config parameterises away, and
# a split-name alert the config replaced with a plain `alert_o`).
_CHIP_TOP_FAITHFUL = """\
module chip_top (
    input  wire        clk_i,
    input  wire        rst_ni,
    input  wire [31:0] data_i,
    output wire [31:0] data_o,
    output wire        alert_o,
    output wire        done_o
);
    core_ip u_core_ip (
        .clk_i(clk_i), .rst_ni(rst_ni), .data_i(data_i),
        .data_o(data_o), .alert_o(alert_o), .done_o(done_o)
    );
endmodule
"""

# L9 = fuller variant: has config-gated `shadow_data_o`, `integ_i`,
# `lockstep_o`, `alert_bus_o` (none are core_ip ports), and split alert names
# instead of `alert_o`.
_L9_FULLER = [
    {"name": "clk_i", "direction": "input"},
    {"name": "rst_ni", "direction": "input"},
    {"name": "data_i", "direction": "input"},
    {"name": "data_o", "direction": "output"},
    {"name": "done_o", "direction": "output"},
    {"name": "alert_bus_o", "direction": "output"},     # config-gated
    {"name": "shadow_data_o", "direction": "output"},   # config-gated
    {"name": "integ_i", "direction": "input"},          # config-gated
    {"name": "lockstep_o", "direction": "output"},      # config-gated
]


def test_pass_config_variant_reused_ip(tmp_path):
    """Faithful reused-IP wrapper of a subset config PASSes: L9-only pins are
    config-gated (not core_ip ports) and `alert_o` is a real IP passthrough."""
    project = tmp_path / "p"; project.mkdir()
    _write_reused_ip_project(project, _CHIP_TOP_FAITHFUL, _L9_FULLER)
    r = _run(project)
    assert r.returncode == 0, f"expected PASS, got:\n{r.stdout}\n{r.stderr}"
    assert "PASS" in r.stdout
    assert "CONFIG-GATED" in r.stdout
    # the split-alert / passthrough `alert_o` must be classified passthrough
    assert "alert_o" in r.stdout


def test_noleak_dropped_real_ip_port_still_fails(tmp_path):
    """NO-LEAK: if chip_top DROPS a real core_ip port (`done_o`) that L9
    requires, the gate still FAILs — `done_o` IS in the instantiated IP
    surface, so it is a genuinely dropped pin, not config-gated."""
    chip_top = _CHIP_TOP_FAITHFUL.replace(
        "    output wire        done_o\n", "", 1
    ).replace(", .done_o(done_o)", "")
    project = tmp_path / "p"; project.mkdir()
    _write_reused_ip_project(project, chip_top, _L9_FULLER)
    r = _run(project)
    assert r.returncode == 1, f"expected FAIL, got:\n{r.stdout}"
    assert "done_o" in r.stdout
    assert "missing from RTL" in r.stdout


def test_noleak_invented_port_still_fails(tmp_path):
    """NO-LEAK: a chip_top port sourced from NO instantiated IP (`bogus_o`)
    and absent from L9 still FAILs — it is an invented port, not IP
    passthrough."""
    chip_top = _CHIP_TOP_FAITHFUL.replace(
        "    output wire        done_o\n)",
        "    output wire        done_o,\n    output wire        bogus_o\n)",
    )
    project = tmp_path / "p"; project.mkdir()
    _write_reused_ip_project(project, chip_top, _L9_FULLER)
    r = _run(project)
    assert r.returncode == 1, f"expected FAIL, got:\n{r.stdout}"
    assert "bogus_o" in r.stdout
    assert "not in L9" in r.stdout


def test_non_reused_ip_gets_no_relaxation(tmp_path):
    """A design with NO SOURCE_MANIFEST (non-reused-IP) gets NO config-variant
    relaxation: an L9 pin absent from the RTL top still FAILs. Guards against
    the relaxation leaking into the from-scratch authoring path."""
    project = tmp_path / "p"; project.mkdir()
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "chip_top.sv").write_text(_CHIP_TOP_FAITHFUL)
    (rtl / "core_ip.sv").write_text(_CORE_IP_SV)
    # NOTE: no SOURCE_MANIFEST.json → not a reused-IP path.
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "layer": "L9", "ic_name": "TEST", "top_module": "chip_top",
        "top_level_ports": _L9_FULLER,
    }, indent=2))
    r = _run(project)
    assert r.returncode == 1, f"expected FAIL (no relaxation), got:\n{r.stdout}"
    assert "missing from RTL" in r.stdout


if __name__ == "__main__":
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", "-q",
                              str(Path(__file__))]))
