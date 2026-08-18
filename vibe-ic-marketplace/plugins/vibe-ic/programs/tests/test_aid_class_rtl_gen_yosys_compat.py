"""tests/test_aid_class_rtl_gen_yosys_compat.py — v1.6.18 regression guard.

Yosys 0.33's `read_verilog -sv` cannot resolve `import <pkg>::*;` across
separate files; the previous generator emitted that import in every
synthesisable module and Phase-2b synth aborted at byte_assembler.sv:2
with "syntax error, unexpected TOK_ID" before any RTL was processed
(see phase2+3_v10617 run on 2026-05-07).

Fix: every synthesisable module embeds a Verilog-2005-compatible
`localparam` block at a `{rtl_constants}` placeholder, removing the
need for SV package import. The package file is still emitted (some
SV simulators consume it) but no module references it.

These regressions guarantee:
  1. `import rtl_constants_pkg::*;` is removed from every synthesisable
     module emitted into rtl/.
  2. Each emitted module that uses pkg-named timing constants (e.g.
     T_FRAME_END_TICKS) defines them locally as `localparam int`.
  3. Numeric literals in localparams match the values from L8.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

PROGRAM = (
    Path(__file__).resolve().parent.parent / "aid_class_rtl_gen.py"
)


def _write(project: Path, rel: str, body) -> None:
    p = project / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(body))


def _build_aid_fixture(project: Path) -> None:
    """Minimal example_protocol-class fixture so __main__ guard accepts and gen() runs."""
    project.mkdir(parents=True, exist_ok=True)
    ev = {"extraction_evidence": {
        "vendor.pdf": [{"literal": "sentinel", "label": "fix"}]
    }}
    _write(project, "phase1/generated_docs/L1_DATASHEET.json", {**ev, "ic_name": "EXAMPLE_PROTOCOL"})
    _write(project, "phase1/generated_docs/L2_FRS.json", {
        **ev, "ic_name": "EXAMPLE_PROTOCOL", "protocol_type": "half_duplex_single_wire",
    })
    _write(project, "phase1/generated_docs/L3_CMD_PROTOCOL.json", {
        **ev,
        "crc_parameters": {
            "polynomial_hex": "0x31",
            "polynomial_reflected_hex": "8'h8C",
            "init_hex": "8'hFF",
        },
        "opcodes": [],
    })
    _write(project, "phase1/generated_docs/L4_REGMAP.json", ev)
    _write(project, "phase1/generated_docs/L5_ADI_SPEC.json", ev)
    _write(project, "phase1/generated_docs/L6_CONTROL_LOGIC.json", ev)
    _write(project, "phase1/generated_docs/L7_TEST_DEBUG.json", ev)
    _write(project, "phase1/generated_docs/L8_RTL_CONSTANTS.json", {
        **ev,
        "rx_classifier_ticks": {
            "h1_min": 1, "h1_max": 192, "h0_min": 193, "h0_max": 612,
            "br_min": 613, "br_max": 1272, "ibt_min": 274, "ibt_max": 2000,
            "wkp_min": 750,
        },
        "timing_constants": [
            {"name": "T_BIT0_LOW_TICKS", "value": 355},
            {"name": "T_BIT1_LOW_TICKS", "value": 90},
            {"name": "T_BIT_CELL_TX_TICKS", "value": 440},
            {"name": "T_WAKE_PULSE_TICKS", "value": 1120},
            {"name": "T_TSRS_MIN_TICKS", "value": 1000},
            {"name": "T_TSRS_MAX_TICKS", "value": 5000},
            {"name": "T_FRAME_END_TICKS", "value": 2000},
            {"name": "T_BIT_HIGH_TICKS", "value": 100},
            {"name": "T_WAKE_PERIOD_TICKS", "value": 250000},
            {"name": "T_LONG_LOW_RESET_TICKS", "value": 25000000},
        ],
    })
    _write(project, "phase1/generated_docs/L9_INTEGRATION_SPEC.json", ev)
    # rtl/ stub with `inout id_bus` so __main__ class-guard accepts.
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "stub.sv").write_text(
        "module stub (input wire clk, inout wire id_bus); endmodule\n"
    )


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROGRAM), str(project)],
        capture_output=True, text=True, timeout=60,
    )


# Modules that previously had `import rtl_constants_pkg::*;` and must
# no longer carry it. byte_assembler / chip_top_pad_wrapper / de10lite_top
# are also expected clean.
SYNTHESISABLE_MODULES = [
    "rx_phy.sv", "byte_assembler.sv", "tx_phy.sv", "wake_gen.sv",
    "main_fsm.sv", "chip_top.sv", "chip_top_asic.sv",
    "chip_top_pad_wrapper.sv", "de10lite_top.sv",
]


def test_no_sv_package_import_in_emitted_rtl(tmp_path: Path) -> None:
    project = tmp_path / "fix_proj"
    _build_aid_fixture(project)
    cp = _run(project)
    assert cp.returncode == 0, f"gen failed:\n{cp.stdout}\n{cp.stderr}"
    rtl = project / "phase2" / "stage1" / "rtl"
    bad: list[tuple[str, int, str]] = []
    for f in SYNTHESISABLE_MODULES:
        p = rtl / f
        assert p.is_file(), f"missing emitted file {f}"
        for i, line in enumerate(p.read_text().splitlines(), start=1):
            if "import rtl_constants_pkg" in line:
                bad.append((f, i, line))
    assert not bad, (
        "Yosys 0.33 cannot parse cross-file SV `import pkg::*;` — "
        "every synthesisable module must use inline localparams instead. "
        f"Found leftover imports:\n  " +
        "\n  ".join(f"{f}:{i}: {ln}" for f, i, ln in bad)
    )


def test_localparams_inlined_in_modules_using_timing_constants(tmp_path: Path) -> None:
    """Modules that reference T_* / *_MIN / *_MAX must define them locally."""
    project = tmp_path / "fix_proj"
    _build_aid_fixture(project)
    cp = _run(project)
    assert cp.returncode == 0, f"gen failed:\n{cp.stdout}\n{cp.stderr}"
    rtl = project / "phase2" / "stage1" / "rtl"
    # Symbols expected in the inlined localparam block (sample subset; if
    # any of these is absent in a module that uses it we'll fail synth).
    must_define = {
        "T_FRAME_END_TICKS", "T_TSRS_MIN_TICKS", "T_TSRS_MAX_TICKS",
        "T_BIT_HIGH_TICKS", "T_BIT0_LOW_TICKS", "T_BIT1_LOW_TICKS",
        "T_BIT_CELL_TX_TICKS", "T_WAKE_PERIOD_TICKS", "T_WAKE_PULSE_TICKS",
        "T_LONG_LOW_RESET_TICKS",
    }
    pat_localparam = re.compile(r"localparam\s+int\s+(\w+)\s*=")
    missing: list[tuple[str, set[str]]] = []
    for f in ("rx_phy.sv", "tx_phy.sv", "wake_gen.sv", "main_fsm.sv",
              "chip_top.sv", "chip_top_asic.sv"):
        text = (rtl / f).read_text()
        # Symbols actually referenced (not in comments) — best-effort: scan
        # non-comment lines for the symbol.
        used = set()
        for line in text.splitlines():
            stripped = line.split("//", 1)[0]
            for sym in must_define:
                if re.search(rf"\b{sym}\b", stripped):
                    used.add(sym)
        defined = set(pat_localparam.findall(text))
        gap = used - defined
        if gap:
            missing.append((f, gap))
    assert not missing, (
        "Modules reference timing constants without inline `localparam` "
        "definition (will fail yosys parse): " +
        "; ".join(f"{f}: missing {sorted(g)}" for f, g in missing)
    )


def test_localparam_values_match_l8(tmp_path: Path) -> None:
    """Sanity-check values flow through .format()."""
    project = tmp_path / "fix_proj"
    _build_aid_fixture(project)
    cp = _run(project)
    assert cp.returncode == 0, f"gen failed:\n{cp.stdout}\n{cp.stderr}"
    text = (project / "phase2" / "stage1" / "rtl" / "rx_phy.sv").read_text()
    # T_FRAME_END_TICKS = 2000 from fixture
    assert re.search(r"localparam\s+int\s+T_FRAME_END_TICKS\s*=\s*2000\b", text), (
        f"T_FRAME_END_TICKS not inlined as 2000 in rx_phy.sv:\n{text[:600]}"
    )
    # T_LONG_LOW_RESET_TICKS = 25000000 large literal must be preserved
    text_wake = (project / "phase2" / "stage1" / "rtl" / "wake_gen.sv").read_text()
    assert re.search(
        r"localparam\s+int\s+T_LONG_LOW_RESET_TICKS\s*=\s*25000000\b", text_wake
    ), f"T_LONG_LOW_RESET_TICKS literal mismatch in wake_gen.sv"


def test_pkg_localparam_template_drift_detector() -> None:
    """v1.6.19 — drift detector for the two timing-constant templates.

    `RTL_CONSTANTS_PKG` (kept for SV simulators) and
    `RTL_CONSTANTS_LOCALPARAMS` (inlined into every Yosys-synthesisable
    module) are .format()-rendered from the same L8 dict. They MUST
    declare the same set of identifiers AND wire each identifier to the
    same placeholder name, otherwise a single L8 input renders different
    values in simulation vs synthesis — silent drift that the existing
    end-to-end tests cannot detect because they only exercise one
    template per module.

    Catches at least these regression classes:
      * adding a new constant to pkg without mirroring to inline template
      * removing a constant from inline template without removing pkg
      * typo-swap such as `H1_MIN={h1_min}` in pkg vs `H1_MIN={h0_min}`
        in inline (identifier sets match but mapping diverges)
    """
    from programs.aid_class_rtl_gen import (
        RTL_CONSTANTS_PKG, RTL_CONSTANTS_LOCALPARAMS,
    )

    # `parameter int H1_MIN={h1_min}, H1_MAX={h1_max};` packs two pairs.
    pkg_pat = re.compile(r"\b([A-Z][A-Z0-9_]*)\s*=\s*\{(\w+)\}")
    inl_pat = re.compile(r"localparam\s+int\s+(\w+)\s*=\s*\{(\w+)\}")

    pkg_pairs = pkg_pat.findall(RTL_CONSTANTS_PKG)
    inl_pairs = inl_pat.findall(RTL_CONSTANTS_LOCALPARAMS)
    assert pkg_pairs, "regex found no parameters in RTL_CONSTANTS_PKG"
    assert inl_pairs, "regex found no localparams in RTL_CONSTANTS_LOCALPARAMS"

    pkg_map = dict(pkg_pairs)
    inl_map = dict(inl_pairs)
    assert len(pkg_map) == len(pkg_pairs), (
        f"duplicate identifier in pkg template: {pkg_pairs}"
    )
    assert len(inl_map) == len(inl_pairs), (
        f"duplicate identifier in inline template: {inl_pairs}"
    )

    pkg_only = sorted(set(pkg_map) - set(inl_map))
    inl_only = sorted(set(inl_map) - set(pkg_map))
    assert not pkg_only, (
        "pkg declares identifiers absent from inline localparam template: "
        f"{pkg_only}. Adding a constant to rtl_constants_pkg without "
        "mirroring to RTL_CONSTANTS_LOCALPARAMS makes simulation see the "
        "value but Yosys-synthesised RTL not — silent sim/synth drift."
    )
    assert not inl_only, (
        "Inline localparam template declares identifiers absent from pkg: "
        f"{inl_only}. The pkg is the canonical declaration; mirror back."
    )

    mismatched = {
        ident: (pkg_map[ident], inl_map[ident])
        for ident in pkg_map if pkg_map[ident] != inl_map[ident]
    }
    assert not mismatched, (
        "Identifier→placeholder mapping diverges between pkg and inline "
        "localparam templates (catches typo swaps): "
        f"{mismatched}. A single L8 dict will assign different values "
        "in simulation vs Yosys synthesis."
    )
