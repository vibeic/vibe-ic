#!/usr/bin/env python3
"""ORGANIC #659 ROUND-2 — reused-IP reconciliation must not require every
internally-driven interface to be pre-enumerated in SOURCE_MANIFEST tie_offs.

Field-agent reopen (v1.0.40 partial): `reconcile_reused_ip` narrowed the
mismatch on the round-3 opentitan_aes catalog-glue artifact but the gate STILL
FAILed (exit 1) — residual L9-only=[clk_edn_i, edn, edn_o], RTL-only=[rst_ni].
Two line-level gaps:

  (1) The reconciliation recognised an internally-driven interface ONLY if it
      was listed in SOURCE_MANIFEST.json tie_offs. The opentitan_aes manifest
      OMITS clk_edn_i (chip_top binds `.clk_edn_i(clk_i)`) and edn_o (binds
      `.edn_o(edn_req_unused)`); the abstract root `edn` is IP-split into
      edn_i/edn_o with no `edn` pad. The manifest dict is NOT guaranteed
      exhaustive.
  (2) `_is_implicit_pin`'s reset pattern did not match `rst_ni` (glued `_n`+`i`)
      — a near-universal OpenTitan/comportable reset spelling — so it survived
      the implicit-strip as an RTL-only false-FAIL.

Round-2 fix:
  (1) STRUCTURAL tie-off detection — a residual L9 root that the chip_top
      instantiation actually BINDS (`.root(net)` or an IP-split child
      `.root_i`/`.root_o`/`.root_*`) is a legitimate internal-drive → advisory
      tie-off, not FAIL. No-leak: a root bound NOWHERE stays a residual FAIL.
  (2) reset pattern accepts a glued active-low+direction suffix (rst_ni/rst_no).

chip-AGNOSTIC: SV named-port-connection grammar `.<ident>(...)` + the
rst/reset/por stem; no chip/vendor literal.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (
    Path(__file__).resolve().parent.parent / "l9_rtl_pin_consistency_check.py"
)
sys.path.insert(0, str(PROG.parent))
import l9_rtl_pin_consistency_check as G  # noqa: E402
from _hostpaths import require_corpus  # noqa: E402


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG), str(project)],
                          capture_output=True, text=True)


def _write_l9(project: Path, top_module: str, ports: list[dict]) -> None:
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "schema_version": 2, "ic_name": "TESTCHIP",
        "top_module": top_module, "top_level_ports": ports}, indent=2))


def _write_rtl(project: Path, body: str) -> None:
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "chip_top.sv").write_text(body)


def _write_manifest(project: Path, data: dict) -> None:
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "SOURCE_MANIFEST.json").write_text(json.dumps(data, indent=2))


# A reused-IP wrapper: L9 lists interfaces `clk_x_i` and root `edn` that have
# NO chip_top pad; the chip_top INSTANTIATION binds them internally
# (`.clk_x_i(clk_i)`, `.edn_i(...)`, `.edn_o(...)`) but the manifest tie_offs
# OMITS them (only lists `keymgr_key_i`).
_RTL = (
    "module chip_top (\n"
    "  input  wire clk_i,\n"
    "  input  wire rst_ni,\n"
    "  input  wire        tl_a_valid_i,\n"
    "  output wire        tl_d_valid_o\n"
    ");\n"
    "  inner_ip u_ip (\n"
    "    .clk_i      (clk_i),\n"
    "    .clk_x_i    (clk_i),\n"          # glue-tied, NOT in manifest
    "    .keymgr_key_i (KEYMGR_DEFAULT),\n"
    "    .edn_i      (edn_rsp_tied),\n"    # IP-split child, NOT in manifest
    "    .edn_o      (edn_req_unused),\n"  # IP-split child, NOT in manifest
    "    .tl_a_valid_i (tl_a_valid_i),\n"
    "    .tl_d_valid_o (tl_d_valid_o)\n"
    "  );\n"
    "endmodule\n"
)
_L9 = [
    {"name": "clk_i", "direction": "input"},
    {"name": "rst_ni", "direction": "input"},
    {"name": "tl", "direction": "inout"},            # flatten root
    {"name": "clk_x_i", "direction": "input"},        # structural tie-off
    {"name": "keymgr_key_i", "direction": "input"},   # manifest tie-off
    {"name": "edn", "direction": "inout"},            # IP-split root
]
_MANIFEST = {"reused_ip": True, "tie_offs": ["keymgr_key_i"],
             "flattened_buses": ["tl"]}


# ── ACCEPTANCE: structural tie-off (manifest not exhaustive) → PASS ──────────
def test_structural_tieoff_not_in_manifest_passes(tmp_path):
    p = tmp_path / "p"
    _write_l9(p, "chip_top", _L9)
    _write_rtl(p, _RTL)
    _write_manifest(p, _MANIFEST)
    r = _run(p)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout
    # clk_x_i (direct bind) + edn (IP-split child bind) recognised as tie-offs
    assert "clk_x_i" in r.stdout and "edn" in r.stdout


# ── reset rst_ni is implicit-stripped (no RTL-only false-FAIL) ───────────────
def test_rst_ni_implicit_stripped(tmp_path):
    p = tmp_path / "p"
    # L9 omits rst_ni (relies on canonical fallback); RTL has it. Pre-fix it
    # survived the strip → RTL-only FAIL. Now stripped → PASS.
    _write_l9(p, "chip_top", [d for d in _L9 if d["name"] != "rst_ni"])
    _write_rtl(p, _RTL)
    _write_manifest(p, _MANIFEST)
    r = _run(p)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "rst_ni" not in r.stdout.split("WARN")[0]  # not in the FAIL findings


# ── NO-LEAK 1: reused-IP L9 root bound NOWHERE still FAILs ───────────────────
def test_noleak_unbound_l9_root_still_fails(tmp_path):
    p = tmp_path / "p"
    l9 = _L9 + [{"name": "ghost_iface", "direction": "input"}]  # bound nowhere
    _write_l9(p, "chip_top", l9)
    _write_rtl(p, _RTL)
    _write_manifest(p, _MANIFEST)
    r = _run(p)
    assert r.returncode == 1, r.stdout
    assert "ghost_iface" in r.stdout


# ── NO-LEAK 2: non-reused-IP (no manifest) → no structural relaxation ────────
def test_noleak_no_manifest_no_structural_relaxation(tmp_path):
    p = tmp_path / "p"
    _write_l9(p, "chip_top", _L9)
    _write_rtl(p, _RTL)   # NO manifest written
    r = _run(p)
    assert r.returncode == 1, r.stdout  # clk_x_i/edn/tl exact-name mismatch


# ── helper units ────────────────────────────────────────────────────────────
def test_chip_top_bound_ports_extracts_bindings(tmp_path):
    f = tmp_path / "chip_top.sv"
    f.write_text(_RTL)
    bound = G._chip_top_bound_ports(f)
    assert {"clk_x_i", "edn_i", "edn_o", "keymgr_key_i"} <= bound


def test_is_structurally_bound_matrix():
    bp = {"clk_x_i", "edn_i", "edn_o"}
    assert G._is_structurally_bound("clk_x_i", bp) is True   # direct
    assert G._is_structurally_bound("edn", bp) is True       # IP-split child
    assert G._is_structurally_bound("spi", bp) is False      # unbound
    assert G._is_structurally_bound("edn", set()) is False   # no bindings


def test_reset_pattern_glued_suffix():
    for n in ("rst_ni", "rst_no", "reset_ni", "por_n", "rst_ni0"):
        assert G._is_implicit_pin(n) is True, n
    for n in ("data_o", "spi_csb", "wb_ack_o", "irq", "edn_o"):
        assert G._is_implicit_pin(n) is False, n


def test_reconcile_unbound_root_stays_residual():
    r_l9, r_rtl, tied, pm = G.reconcile_reused_ip(
        ["bound_x", "ghost"], [], {"reused_ip": True},
        bound_ports={"bound_x"})
    assert r_l9 == ["ghost"]      # bound nowhere → residual FAIL
    assert tied == ["bound_x"]    # structurally bound → advisory


# ── the REAL reopen artifact (skips off-monorepo) ───────────────────────────
def test_real_opentitan_aes_round3_artifact_passes():
    art = require_corpus("_bench6_v100_r3/opentitan_aes")
    if not (art / "phase2" / "stage1" / "rtl" / "chip_top.sv").is_file():
        import pytest
        pytest.skip("round-3 opentitan_aes artifact not on disk")
    r = _run(art)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout
    # PASS ⇒ no FAIL findings at all (the field-agent's residual
    # L9-only=[clk_edn_i,edn,edn_o] / RTL-only=[rst_ni] are reconciled).
    assert "declares pins missing from RTL" not in r.stdout
    assert "has ports not in L9" not in r.stdout
    # clk_edn_i / edn recognised as advisory tie-offs (in the WARN section)
    assert "clk_edn_i" in r.stdout


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
