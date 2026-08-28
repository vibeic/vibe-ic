#!/usr/bin/env python3
"""tests/test_v0_2_102_issue490_491_l9_ports.py
ORGANIC-20260606 #490 + #491 — L9 port layer.

ISSUE #490 (schema-key fragmentation)
=====================================
L9_INTEGRATION_SPEC.json carries multiple port keys (`top_ports` /
`ports` / `top_level_ports` / `top_module_pins`). full_stack_tb_gen +
the L9 promoter populate the CANONICAL `top_ports`, but
`l9_rtl_pin_consistency_check.extract_l9_ports()` historically read ONLY
`top_level_ports` / `top_module_pins` / `dtop_top_level.ports`. A correct
RTL top therefore got NO verification (silent SKIP) whenever the promoted
set landed in `top_ports` — and a field run had to dual-write the SAME
pins into BOTH keys to clear the gate.

FIX: extract_l9_ports() now reads the UNION of every known key; the
promoter documents `top_ports` as canonical and mirrors the SAME list
object into the legacy aliases it populates.

ISSUE #491 (promoter under-extraction + gate implicit-pin pattern)
==================================================================
(a) The L9 top-port promoter must extract ALL L3/L1 pin_table rows
    (every direction-bearing row), not just the first / SRAM-style group.
(b) `_IMPLICIT_PINS` was an EXACT-name set `{"clk","reset_n"}`, so when
    L9 carries `i_clk`/`rst_n` but the RTL emitter declares the OTHER
    conventional spelling (`clk`/`reset`) the asymmetric pair survived
    the strip and false-FAILed. Widen to a NAME-PATTERN set over the
    clock + reset families. #475's SDC-token / library-prefix rejection
    must still hold; a genuinely undeclared port must still FAIL.

ACCEPTANCE (narrative → end-to-end):
  * L3 pin table with clock/reset/GPIO rows + a block-pin group, run the
    REAL promoter (gen_l9 path) → L9 contains ALL rows under the
    canonical key;
  * run the REAL l9_rtl_pin_consistency_check against a matching RTL top
    → PASS;
  * a fixture where ports land ONLY in `top_ports` → the gate still
    reads them (no dual-write needed);
  * RTL with a genuinely undeclared port still FAILs.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN_ROOT / "programs"
for _p in (str(PROGRAMS), str(PLUGIN_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import l9_rtl_pin_consistency_check as GATE  # noqa: E402
from programs.phase1_one_shot_runner import (  # noqa: E402
    gen_l9_integration_spec,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

GATE_PROG = PROGRAMS / "l9_rtl_pin_consistency_check.py"
RUNNER = PROGRAMS / "phase1_one_shot_runner.py"
_GEN = Path("phase1") / "generated_docs"
_RTL = Path("phase2") / "stage1" / "rtl"


# ── helpers ────────────────────────────────────────────────────────
def _run_gate(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GATE_PROG), str(project)],
        capture_output=True, text=True,
    )


def _write_l9(project: Path, doc: dict) -> None:
    gd = project / _GEN
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(doc, indent=2))


def _write_rtl_top(project: Path, name: str, port_lines: list[str]) -> None:
    rtl = project / _RTL
    rtl.mkdir(parents=True, exist_ok=True)
    body = ",\n  ".join(port_lines)
    (rtl / f"{name}.sv").write_text(
        f"module {name} (\n  {body}\n);\nendmodule\n"
    )


def _seed_l1(project: Path, pin_table, ic_name="DEMO_TOP") -> None:
    gd = project / _GEN
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L1_DATASHEET.json").write_text(
        json.dumps({"ic_name": ic_name, "pin_table": pin_table})
    )


def _read_l9(project: Path) -> dict:
    return json.loads(
        (project / _GEN / "L9_INTEGRATION_SPEC.json").read_text())


# ════════════════════════════════════════════════════════════════════
# #490 — extract_l9_ports reads the UNION of every known port key
# ════════════════════════════════════════════════════════════════════
def test_490_extract_reads_top_ports_key():
    """The CANONICAL `top_ports` key — the one the promoter writes and
    the gate historically did NOT read — is now seen."""
    ports = GATE.extract_l9_ports({
        "top_ports": [
            {"name": "o_gpio_0", "direction": "output"},
            {"name": "data_in", "direction": "input"},
        ]
    })
    assert {p["name"] for p in ports} == {"o_gpio_0", "data_in"}


def test_490_extract_reads_ports_alias_key():
    ports = GATE.extract_l9_ports({
        "ports": [{"name": "sram_addr", "direction": "input"}]
    })
    assert {p["name"] for p in ports} == {"sram_addr"}


def test_490_extract_reads_legacy_keys_still():
    """Old keys must still be honoured (back-compat)."""
    a = GATE.extract_l9_ports(
        {"top_level_ports": [{"name": "leg_a", "direction": "input"}]})
    b = GATE.extract_l9_ports(
        {"top_module_pins": [{"name": "leg_b", "direction": "output"}]})
    c = GATE.extract_l9_ports(
        {"dtop_top_level": {"ports": [{"name": "leg_c", "dir": "inout"}]}})
    assert {p["name"] for p in a} == {"leg_a"}
    assert {p["name"] for p in b} == {"leg_b"}
    assert {p["name"] for p in c} == {"leg_c"}


def test_490_union_dedupes_dual_write():
    """The dual-write field runs used to apply (same pins under BOTH
    `top_ports` AND `top_module_pins`) yields the SAME single set as a
    singly-keyed doc — no duplicate port entries."""
    doc = {
        "top_ports": [
            {"name": "clk_pin", "direction": "input"},
            {"name": "data", "direction": "output"},
        ],
        "top_module_pins": [
            {"name": "clk_pin", "direction": "input"},
            {"name": "data", "direction": "output"},
        ],
    }
    ports = GATE.extract_l9_ports(doc)
    names = [p["name"] for p in ports]
    assert sorted(names) == ["clk_pin", "data"]
    assert len(names) == len(set(names)), f"dup entries: {names}"


def test_490_union_backfills_missing_direction():
    """If one key carries the direction and the other does not, the
    union backfills so the direction is not lost."""
    doc = {
        "top_ports": [{"name": "id_bus"}],                 # no dir
        "top_module_pins": [{"name": "id_bus", "direction": "inout"}],
    }
    ports = GATE.extract_l9_ports(doc)
    assert len(ports) == 1
    assert ports[0]["direction"] == "inout"


def test_490_gate_no_longer_skips_when_ports_only_in_top_ports(tmp_path):
    """END-TO-END #490: ports land ONLY in `top_ports` (no dual-write).
    Pre-fix the gate SKIPped ('L9 declares no top_level_ports[]'); now it
    runs a full PASS comparison against a matching RTL top."""
    project = tmp_path / "p"
    project.mkdir(parents=True, exist_ok=True)
    _write_l9(project, {
        "schema_version": 2,
        "top_module": "chip_top",
        "top_ports": [
            {"name": "o_gpio_0", "direction": "output"},
            {"name": "o_gpio_1", "direction": "output"},
            {"name": "data_in", "direction": "input"},
        ],
        # NOTE: deliberately NO top_level_ports / top_module_pins / ports.
    })
    _write_rtl_top(project, "chip_top", [
        "output wire o_gpio_0",
        "output wire o_gpio_1",
        "input  wire data_in",
    ])
    r = _run_gate(project)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout, r.stdout
    assert "SKIP" not in r.stdout, (
        "gate SKIPped — top_ports key was not read (#490 regression)")
    assert "agree on 3/" in r.stdout, r.stdout  # #591 format: N/TOTAL


def test_490_promoter_mirrors_canonical_into_legacy_keys(tmp_path):
    """The promoter (gen_l9 path) writes the canonical `top_ports` AND
    mirrors the SAME set into `ports` + `top_module_pins`, so no consumer
    is orphaned regardless of which alias it inspects."""
    _seed_l1(tmp_path, [
        {"name": "clk", "mode": "input"},
        {"name": "o_data", "mode": "output",
         "extraction_strategy": "markdown_pipe_table"},
    ], ic_name="MIRROR_TOP")
    gen_l9_integration_spec(tmp_path, {}, l3={})
    l9 = _read_l9(tmp_path)
    want = {"clk", "o_data"}
    for key in ("top_ports", "ports", "top_module_pins"):
        got = {p.get("name") for p in (l9.get(key) or [])}
        assert got == want, f"alias {key!r} mismatch: got {got}, want {want}"


# ════════════════════════════════════════════════════════════════════
# #491 (b) — _IMPLICIT_PINS widened from exact names to NAME-PATTERN
# ════════════════════════════════════════════════════════════════════
def test_491b_implicit_pattern_matches_clock_family():
    for n in ("clk", "i_clk", "o_clk", "clk_i", "clk_o", "clock",
              "sys_clk", "core_clk", "pixel_clk", "clk0"):
        assert GATE._is_implicit_pin(n), n


def test_491b_implicit_pattern_matches_reset_family():
    for n in ("rst", "i_rst", "rst_n", "rstn", "reset", "reset_n",
              "i_reset_n", "por", "por_n", "por_rst_n", "soft_reset"):
        assert GATE._is_implicit_pin(n), n


def test_491b_implicit_pattern_does_not_overmatch_real_ports():
    """Real functional ports that merely START with clk/reset/por must
    NOT be stripped — otherwise a genuine dropped port hides."""
    for n in ("clk_en", "clk_div", "clk_sel", "clock_enable",
              "clkmux", "clocker", "reset_done", "reset_req",
              "reset_value", "restart", "restore", "reseller", "porch",
              "o_gpio_0", "sram_addr", "data"):
        assert not GATE._is_implicit_pin(n), n


def test_491b_asymmetric_clock_reset_spelling_passes(tmp_path):
    """END-TO-END #491(b): L9 carries `i_clk`/`rst_n` (the spelling the
    promoter emitted) while the RTL emitter declares `clk`/`reset` (its
    own canonical spelling). The exact-name strip used to false-FAIL
    'RTL has ports not in L9'. With the pattern strip BOTH families fall
    away and the real port matches → PASS."""
    project = tmp_path / "p"
    project.mkdir(parents=True, exist_ok=True)
    _write_l9(project, {
        "schema_version": 2,
        "top_module": "chip_top",
        "top_ports": [
            {"name": "i_clk", "direction": "input"},
            {"name": "rst_n", "direction": "input"},
            {"name": "o_gpio_0", "direction": "output"},
        ],
    })
    _write_rtl_top(project, "chip_top", [
        "input  wire clk",
        "input  wire reset",
        "output wire o_gpio_0",
    ])
    r = _run_gate(project)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout, r.stdout
    assert "agree on 1/" in r.stdout, r.stdout  # #591 format: N/TOTAL


def test_491b_genuinely_undeclared_port_still_fails(tmp_path):
    """A real (non-implicit, non-debug) port present in RTL but absent
    from L9 must STILL FAIL — the widened strip must not swallow real
    pin-set discrepancies."""
    project = tmp_path / "p"
    project.mkdir(parents=True, exist_ok=True)
    _write_l9(project, {
        "schema_version": 2,
        "top_module": "chip_top",
        "top_ports": [
            {"name": "clk", "direction": "input"},
            {"name": "o_gpio_0", "direction": "output"},
        ],
    })
    _write_rtl_top(project, "chip_top", [
        "input  wire clk",
        "output wire o_gpio_0",
        "output wire customer_facing_pin",   # genuinely undeclared
    ])
    r = _run_gate(project)
    assert r.returncode == 1, r.stdout
    assert "FAIL" in r.stdout
    assert "customer_facing_pin" in r.stdout, r.stdout


# ════════════════════════════════════════════════════════════════════
# #491 (a) — promoter extracts ALL pin_table rows (every group), and
# CORPUS-SWEEP: #475 SDC-token / library-prefix rejection still holds.
# ════════════════════════════════════════════════════════════════════
def test_491a_promoter_extracts_all_rows_both_groups(tmp_path):
    """The promoter must keep EVERY direction-bearing row — the
    clock/reset/GPIO top-level group AND the SRAM block-pin group — not
    just the first group."""
    pin_table = [
        # explicit top-level rows
        {"name": "i_clk", "mode": "input",
         "extraction_strategy": "rst_grid_interface_table"},
        {"name": "i_rst_n", "mode": "input",
         "extraction_strategy": "rst_grid_interface_table"},
        {"name": "o_gpio_0", "mode": "output",
         "extraction_strategy": "rst_grid_interface_table"},
        {"name": "o_gpio_1", "mode": "output",
         "extraction_strategy": "rst_grid_interface_table"},
        # second (block / SRAM) group
        {"name": "sram_addr", "mode": "input",
         "extraction_strategy": "rst_grid_interface_table"},
        {"name": "sram_wdata", "mode": "input",
         "extraction_strategy": "rst_grid_interface_table"},
        {"name": "sram_rdata", "mode": "output",
         "extraction_strategy": "rst_grid_interface_table"},
        {"name": "sram_we", "mode": "input",
         "extraction_strategy": "rst_grid_interface_table"},
    ]
    _seed_l1(tmp_path, pin_table, ic_name="TWO_GROUP_TOP")
    gen_l9_integration_spec(tmp_path, {}, l3={})
    l9 = _read_l9(tmp_path)
    names = {p.get("name") for p in (l9.get("top_ports") or [])}
    want = {"i_clk", "i_rst_n", "o_gpio_0", "o_gpio_1",
            "sram_addr", "sram_wdata", "sram_rdata", "sram_we"}
    assert names == want, f"promoter dropped rows: missing {want - names}"


def test_491a_corpus_sweep_475_guards_still_hold(tmp_path):
    """CORPUS-SWEEP guard: the #491 changes must NOT weaken #475 — SDC
    directive tokens + a stdcell-library-prefix token interleaved with
    real rows must still be rejected, real rows kept."""
    pin_table = [
        {"name": "set_input_delay", "mode": "input",
         "evidence": "promoted from L1.pin_table"},
        {"name": "i_clk", "mode": "input",
         "extraction_strategy": "markdown_pipe_table"},
        {"name": "create_clock", "mode": "input",
         "evidence": "promoted from L1.pin_table"},
        {"name": "demo_fd_sc_hdll", "mode": "input",
         "evidence": "promoted from L1.pin_table"},
        {"name": "o_gpio_0", "mode": "output",
         "extraction_strategy": "markdown_pipe_table"},
    ]
    _seed_l1(tmp_path, pin_table, ic_name="GUARD_TOP")
    gen_l9_integration_spec(tmp_path, {}, l3={})
    l9 = _read_l9(tmp_path)
    names = {p.get("name") for p in (l9.get("top_ports") or [])}
    assert names == {"i_clk", "o_gpio_0"}, names
    assert not (names & {"set_input_delay", "create_clock",
                         "demo_fd_sc_hdll"}), names


# ════════════════════════════════════════════════════════════════════
# FULL END-TO-END — the issue's 場景 driven through the REAL runner:
# L3 pin table (clock/reset/GPIO rows + a block-pin group) → real
# promoter (gen_l9) → L9 carries ALL rows under canonical key → real
# gate vs matching RTL top → PASS.
# ════════════════════════════════════════════════════════════════════
_L3_DOC = """# External Interface Specification

Top-level ports:

| Port | Dir | Width | Description |
|------|-----|-------|-------------|
| i_clk | input | 1 | system clock |
| i_rst_n | input | 1 | async reset active low |
| o_gpio_0 | output | 1 | gpio out 0 |
| o_gpio_1 | output | 1 | gpio out 1 |

SRAM block ports:

| Signal | Dir | Width | Description |
|--------|-----|-------|-------------|
| sram_addr | input | 8 | address bus |
| sram_wdata | input | 32 | write data |
| sram_rdata | output | 32 | read data |
| sram_we | input | 1 | write enable |
"""


def test_full_e2e_l3_table_to_l9_canonical_key_then_gate_pass(tmp_path):
    proj = tmp_path / "proj"
    docs = proj / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "L3_external_interface.md").write_text(_L3_DOC)

    # 1) REAL promoter via the runner (gen_l9 path).
    r = _pr.run(
        [sys.executable, str(RUNNER), str(proj), "--ic-name", "blk32"],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-1500:]

    l9 = json.loads(
        (proj / _GEN / "L9_INTEGRATION_SPEC.json").read_text())
    want = {"i_clk", "i_rst_n", "o_gpio_0", "o_gpio_1",
            "sram_addr", "sram_wdata", "sram_rdata", "sram_we"}
    # ALL rows under the CANONICAL key.
    got = {p.get("name") for p in (l9.get("top_ports") or [])}
    assert got == want, f"canonical top_ports != all rows: missing {want - got}"

    # 2) REAL gate vs a matching RTL top → PASS.
    rtl = proj / _RTL
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "chip_top.sv").write_text(
        "module chip_top (\n"
        "  input  wire i_clk,\n"
        "  input  wire i_rst_n,\n"
        "  output wire o_gpio_0,\n"
        "  output wire o_gpio_1,\n"
        "  input  wire [7:0]  sram_addr,\n"
        "  input  wire [31:0] sram_wdata,\n"
        "  output wire [31:0] sram_rdata,\n"
        "  input  wire sram_we\n"
        ");\nendmodule\n"
    )
    # Point the gate at the L9 top_module so it finds chip_top.sv.
    l9["top_module"] = "chip_top"
    (proj / _GEN / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps(l9, indent=2))

    g = _run_gate(proj)
    assert g.returncode == 0, g.stdout
    assert "PASS" in g.stdout, g.stdout
    assert "SKIP" not in g.stdout, g.stdout
    # i_clk / i_rst_n are implicit-stripped; the 6 functional pins remain.
    assert "agree on 6/" in g.stdout, g.stdout  # #591 format: N/TOTAL
