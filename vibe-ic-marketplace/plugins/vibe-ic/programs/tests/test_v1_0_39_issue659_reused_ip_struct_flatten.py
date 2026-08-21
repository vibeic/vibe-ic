#!/usr/bin/env python3
"""ORGANIC #659 — l9_rtl_pin_consistency_check must reconcile a reused-IP
catalog-glue wrapper's struct-flatten + documented tie-offs against
phase2/stage1/rtl/SOURCE_MANIFEST.json before flagging a pin-set mismatch.

Bug (issue #659): for a reused-IP wrapper (SOURCE_MANIFEST.json
reused_ip=true) the chip_top legitimately (a) flattens an L9-declared
struct-typed bus port `tl` into prefix-expanded scalar pads `tl_a_*` /
`tl_d_*`, and (b) omits struct interfaces the manifest documents as
tie-offs (`keymgr_key_i`/`edn_i`, driven to a constant internally, no pad).
The gate compared the L9 pin-set against the RTL top pin-set by EXACT name
with no SOURCE_MANIFEST awareness, so it reported the bus root `tl` as "L9
declares pins missing from RTL", every `tl_a_*`/`tl_d_*` pad as "RTL has
ports not in L9", and every tie-off as a missing pin — three false FAILs.

The #631 fix (anchor the parser to the L9-named top) is working correctly
here — the parser extracts all flattened pads; this is a NEW downstream
semantic facet, NOT a regression of #631 (named-top anchoring) or #641
(field-count floors).

Fix: when phase2/stage1/rtl/SOURCE_MANIFEST.json exists with reused_ip=true,
run a structural reconciliation BEFORE flagging — (1) each remaining L9-only
root P whose RTL-only pads are all `P_`-prefixed is matched (prefix-
expansion), and (2) each L9-only root listed in SOURCE_MANIFEST tie-offs is
dropped (advisory WARN, not FAIL). Only genuinely-unmatched, non-tied,
non-prefix-covered pins FAIL.

Coverage:
  ACCEPTANCE (the bug)  — reused_ip=true wrapper, L9 root `tl` + tie-offs
                          `keymgr_key_i`/`edn_i`, RTL `tl_a_*`/`tl_d_*` pads
                          -> PASS (prefix + tie-off reconciled). Pre-fix:
                          false FAIL with all three findings.
  NO-LEAK 1 (no manifest)
                        — the SAME L9 + RTL but WITHOUT SOURCE_MANIFEST.json
                          -> exact-name comparison preserved -> FAIL.
  NO-LEAK 2 (reused_ip!=true)
                        — manifest present but reused_ip=false -> no
                          relaxation -> FAIL.
  NO-LEAK 3 (genuine residual on reused-IP)
                        — reused_ip=true but an L9 root is NEITHER tied-off
                          NOR prefix-covered -> still FAIL.
  NO-LEAK 4 (genuine extra RTL pad on reused-IP)
                        — reused_ip=true, an RTL pad belongs to NO L9 root
                          prefix and is not a tie-off -> still FAIL.
  NO-LEAK 5 (prefix-boundary)
                        — a root `tl` must NOT swallow an unrelated pad
                          `tlx_q` (underscore boundary); residual stays.
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


def _write_l9(project: Path, top_module: str, ports: list[dict]) -> None:
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "schema_version": 2,
        "ic_name": "TESTCHIP",
        "top_module": top_module,
        "top_level_ports": ports,
    }, indent=2))


def _write_rtl_file(project: Path, filename: str, body: str) -> None:
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / filename).write_text(body)


def _write_manifest(project: Path, data: dict) -> None:
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "SOURCE_MANIFEST.json").write_text(json.dumps(data, indent=2))


# L9 declares the struct-bus ROOT `tl` plus three struct interfaces that
# the manifest documents as tie-offs (driven internally, no pad).
_L9_PORTS = [
    {"name": "clk_i", "direction": "input"},
    {"name": "rst_ni", "direction": "input"},
    {"name": "tl", "direction": "inout"},          # struct-bus root
    {"name": "keymgr_key_i", "direction": "input"},  # tie-off
    {"name": "edn_i", "direction": "input"},         # tie-off
]

# chip_top flattens the `tl` struct into prefix-expanded scalar pads and
# ties off keymgr/edn internally (no pads for them).
_RTL_BODY = (
    "module chip_top (\n"
    "  input  wire clk_i,\n"
    "  input  wire rst_ni,\n"
    "  input  wire        tl_a_valid_i,\n"
    "  input  wire [31:0] tl_a_address_i,\n"
    "  input  wire [31:0] tl_a_data_i,\n"
    "  output wire        tl_d_valid_o,\n"
    "  output wire [31:0] tl_d_data_o\n"
    ");\n"
    "  // keymgr_key_i / edn_i are tied off internally.\n"
    "endmodule\n"
)

_MANIFEST = {
    "reused_ip": True,
    "tie_offs": ["keymgr_key_i", "edn_i"],
    "flattened_buses": ["tl"],
}


# ── ACCEPTANCE: the bug — reused-IP reconcile -> PASS ──────────────
def test_reused_ip_struct_flatten_and_tieoffs_pass(tmp_path):
    """reused_ip=true wrapper: L9 root `tl` + tie-offs keymgr_key_i/edn_i,
    RTL tl_a_*/tl_d_* pads. Pre-fix: false FAIL (3 findings). After the
    fix: prefix-expansion + tie-off reconciled -> PASS (exit 0)."""
    project = tmp_path / "p"
    project.mkdir(parents=True, exist_ok=True)
    _write_l9(project, "chip_top", _L9_PORTS)
    _write_rtl_file(project, "chip_top.sv", _RTL_BODY)
    _write_manifest(project, _MANIFEST)
    r = _run(project)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout, r.stdout
    # The struct-bus root must NOT appear as a missing/extra finding.
    assert "missing from RTL" not in r.stdout, r.stdout
    assert "has ports not in L9" not in r.stdout, r.stdout
    # Advisory evidence — the reconciliation is surfaced, not silent.
    assert "tie-off" in r.stdout, r.stdout
    assert "flatten reconciled" in r.stdout, r.stdout


# ── NO-LEAK 1: no SOURCE_MANIFEST -> exact-name FAIL preserved ─────
def test_no_manifest_exact_name_fail_preserved(tmp_path):
    """The SAME L9 + RTL but WITHOUT SOURCE_MANIFEST.json: no relaxation,
    exact-name comparison stands -> FAIL (root tl + tie-offs missing,
    pads extra)."""
    project = tmp_path / "p"
    project.mkdir(parents=True, exist_ok=True)
    _write_l9(project, "chip_top", _L9_PORTS)
    _write_rtl_file(project, "chip_top.sv", _RTL_BODY)
    # No manifest written.
    r = _run(project)
    assert r.returncode == 1, r.stdout
    assert "FAIL" in r.stdout, r.stdout
    assert "missing from RTL" in r.stdout, r.stdout


# ── NO-LEAK 2: reused_ip != true -> no relaxation -> FAIL ──────────
def test_manifest_present_but_not_reused_ip_fails(tmp_path):
    """Manifest present but reused_ip=false: load_source_manifest returns
    None, no reconciliation, exact-name FAIL preserved."""
    project = tmp_path / "p"
    project.mkdir(parents=True, exist_ok=True)
    _write_l9(project, "chip_top", _L9_PORTS)
    _write_rtl_file(project, "chip_top.sv", _RTL_BODY)
    _write_manifest(project, {
        "reused_ip": False,
        "tie_offs": ["keymgr_key_i", "edn_i"],
        "flattened_buses": ["tl"],
    })
    r = _run(project)
    assert r.returncode == 1, r.stdout
    assert "FAIL" in r.stdout, r.stdout


# ── NO-LEAK 3: genuine residual L9 root on reused-IP -> FAIL ───────
def test_reused_ip_genuine_unmatched_l9_root_fails(tmp_path):
    """reused_ip=true but L9 declares a root `spi` that is NEITHER tied-off
    NOR prefix-covered by any RTL pad -> must still FAIL (relaxation is
    surgical, never a blanket pass)."""
    project = tmp_path / "p"
    project.mkdir(parents=True, exist_ok=True)
    ports = _L9_PORTS + [{"name": "spi", "direction": "inout"}]
    _write_l9(project, "chip_top", ports)
    _write_rtl_file(project, "chip_top.sv", _RTL_BODY)  # no spi_* pads
    _write_manifest(project, _MANIFEST)
    r = _run(project)
    assert r.returncode == 1, r.stdout
    assert "FAIL" in r.stdout, r.stdout
    assert "spi" in r.stdout, r.stdout
    # tl + tie-offs still reconciled; only spi is the residual finding.
    assert "missing from RTL" in r.stdout, r.stdout


# ── NO-LEAK 4: genuine extra RTL pad on reused-IP -> FAIL ──────────
def test_reused_ip_genuine_extra_rtl_pad_fails(tmp_path):
    """reused_ip=true but the RTL top carries a pad `rogue_q` that belongs
    to NO L9-root prefix and is not a documented tie-off -> still FAIL."""
    project = tmp_path / "p"
    project.mkdir(parents=True, exist_ok=True)
    body = _RTL_BODY.replace(
        "  output wire [31:0] tl_d_data_o\n",
        "  output wire [31:0] tl_d_data_o,\n"
        "  output wire        rogue_q\n",
    )
    _write_l9(project, "chip_top", _L9_PORTS)
    _write_rtl_file(project, "chip_top.sv", body)
    _write_manifest(project, _MANIFEST)
    r = _run(project)
    assert r.returncode == 1, r.stdout
    assert "FAIL" in r.stdout, r.stdout
    assert "rogue_q" in r.stdout, r.stdout
    assert "has ports not in L9" in r.stdout, r.stdout


# ── NO-LEAK 5: prefix-boundary — root must not swallow `tlx_q` ─────
def test_prefix_boundary_does_not_overmatch(tmp_path):
    """A root `tl` claims `tl_*` pads via the underscore boundary, but must
    NOT swallow an unrelated pad `tlx_q`. With no L9 root for `tlx_q` and
    no tie-off, that pad stays a residual -> FAIL."""
    project = tmp_path / "p"
    project.mkdir(parents=True, exist_ok=True)
    body = _RTL_BODY.replace(
        "  output wire [31:0] tl_d_data_o\n",
        "  output wire [31:0] tl_d_data_o,\n"
        "  output wire        tlx_q\n",
    )
    _write_l9(project, "chip_top", _L9_PORTS)
    _write_rtl_file(project, "chip_top.sv", body)
    _write_manifest(project, _MANIFEST)
    r = _run(project)
    assert r.returncode == 1, r.stdout
    assert "tlx_q" in r.stdout, r.stdout
    assert "has ports not in L9" in r.stdout, r.stdout


# ── Unit: reconcile_reused_ip direct, structure-only ──────────────
def _load_mod():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_l9pin_659", PROG)
    m = importlib.util.module_from_spec(spec)
    sys.modules["_l9pin_659"] = m
    spec.loader.exec_module(m)
    return m


def test_reconcile_unit_prefix_and_tieoff():
    m = _load_mod()
    only_l9 = ["tl", "keymgr_key_i", "edn_i"]
    only_rtl = ["tl_a_valid_i", "tl_a_address_i", "tl_d_valid_o"]
    res_l9, res_rtl, tied, matched = m.reconcile_reused_ip(
        only_l9, only_rtl, _MANIFEST)
    assert res_l9 == []          # tl prefix-matched, tie-offs dropped
    assert res_rtl == []         # all pads claimed by tl
    assert sorted(tied) == ["edn_i", "keymgr_key_i"]
    roots = [r for r, _ in matched]
    assert "tl" in roots


def test_reconcile_unit_residual_survives():
    m = _load_mod()
    only_l9 = ["tl", "spi"]      # spi has no pads, no tie-off
    only_rtl = ["tl_a_valid_i", "rogue_q"]
    res_l9, res_rtl, tied, matched = m.reconcile_reused_ip(
        only_l9, only_rtl, {"reused_ip": True, "flattened_buses": ["tl"]})
    assert res_l9 == ["spi"]
    assert res_rtl == ["rogue_q"]
    assert tied == []


def test_load_manifest_requires_reused_ip_true(tmp_path):
    m = _load_mod()
    project = tmp_path / "p"
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    # Absent -> None.
    assert m.load_source_manifest(project) is None
    # reused_ip false -> None.
    (rtl / "SOURCE_MANIFEST.json").write_text(json.dumps({"reused_ip": False}))
    assert m.load_source_manifest(project) is None
    # reused_ip true -> dict.
    (rtl / "SOURCE_MANIFEST.json").write_text(json.dumps({"reused_ip": True}))
    assert m.load_source_manifest(project) == {"reused_ip": True}
    # truthy-but-not-True (string) -> None (strict boolean).
    (rtl / "SOURCE_MANIFEST.json").write_text(
        json.dumps({"reused_ip": "true"}))
    assert m.load_source_manifest(project) is None
