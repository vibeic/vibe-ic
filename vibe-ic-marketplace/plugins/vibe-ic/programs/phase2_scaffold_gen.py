"""phase2_scaffold_gen.py — Phase 1 L docs → Phase 2 Verilog scaffolding.

v0.1.88 — bridges Phase 1 protocol coverage (39 families, ~51 KLoC of L docs)
into deterministic Phase 2 RTL scaffolding. Reads `phase1/generated_docs/L*.json`
and emits a synthesizable Verilog skeleton at `phase2/stage1/scaffold/`.

Doctrine: this generator is GENERAL across all 39 (and future) protocols.
It uses the L-doc schema as the contract — it does NOT key off protocol
names. Each output file is a SKELETON: ports declared and tied to TODO
stubs, FSM states enumerated, registers laid out. The user/LLM fills in
behavior; the harness enforces that ports/widths/states match the spec.

Outputs (per protocol benchmark project):

    phase2/stage1/scaffold/
      ├── <top>_top.v                — module + port list + sub-module instances
      ├── <top>_regs.v               — register file skeleton (L4 derived)
      ├── <top>_fsm.v                — FSM state enum + transition skeleton (L6)
      ├── <top>_tb.v                 — testbench scaffold (clk/reset/stimulus from L10)
      └── compliance_vectors.txt     — checkable spec properties (L10/L16/L22)

The generator is fail-open per file: failure to derive one scaffold does
not block the others.

Usage (CLI):

    python3 phase2_scaffold_gen.py <project>
        --skip-tb    # skip testbench scaffold
        --skip-regs  # skip register-file scaffold
        --force      # overwrite existing scaffold/
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load(p: Path) -> dict:
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _unwrap_fields(d: dict) -> dict:
    """Some L docs (L14-L23) wrap content under d['fields']. Normalize."""
    if isinstance(d, dict) and "fields" in d and isinstance(d["fields"], dict):
        merged = dict(d)
        merged.update(d["fields"])
        return merged
    return d


def _sanitize_id(s: str) -> str:
    """Convert an arbitrary string to a valid Verilog identifier."""
    s = re.sub(r"[^A-Za-z0-9_]", "_", s.strip())
    # collapse repeated underscores, strip trailing only (not leading; we
    # need leading _ to be preserved when first char is a digit)
    s = re.sub(r"_+", "_", s).rstrip("_")
    if not s:
        return "unnamed"
    if not (s[0].isalpha() or s[0] == "_"):
        s = "sig_" + s.lstrip("_")
    return s


def _list_or_empty(v: Any) -> list:
    if isinstance(v, list):
        return v
    return []


def _dict_or_empty(v: Any) -> dict:
    if isinstance(v, dict):
        return v
    return {}


# ---------------------------------------------------------------------------
# Top-module derivation (L9 + L17)
# ---------------------------------------------------------------------------

def derive_top_module_name(l1: dict, l9: dict, ic_name: str | None) -> str:
    """Choose a Verilog-valid top-module name from L1/L9.

    Priority: L9.top_module → L1.ic_name → "dut".
    """
    cand = ""
    for src in (l9.get("top_module"), l1.get("ic_name"), ic_name):
        if isinstance(src, str) and src.strip():
            cand = src.strip()
            break
    if not cand:
        cand = "dut"
    # Strip parenthesized suffixes like "(ARM IHI 0033C ...)"
    cand = re.sub(r"\s*\(.*\)\s*$", "", cand)
    return _sanitize_id(cand)


def derive_signals(l17: dict, l9: dict) -> list[dict]:
    """Return a deduplicated list of {name, direction, width, comment} dicts.

    Sources, in priority order:
      1. L17.channels (list of {name, direction_master, direction_slave, purpose})
      2. L9.top_ports (if structured as list of port dicts)
      3. L9.ports

    For each channel we default to master-side direction. Width defaults to 1
    bit unless we can parse a [N:0] hint from the name/purpose.
    """
    signals: list[dict] = []
    seen: set[str] = set()

    def _normalize_dir(d: str | None) -> str:
        if not d:
            return "inout"
        d = d.lower()
        if "out" in d and "in" not in d:
            return "output"
        if "in" in d and "out" not in d:
            return "input"
        if "bidirectional" in d or "i/o" in d:
            return "inout"
        return "input"

    def _add(name: str, direction: str, width: int = 1,
             comment: str = "") -> None:
        if not name:
            return
        clean = _sanitize_id(name)
        if clean in seen:
            return
        seen.add(clean)
        signals.append({
            "name": clean,
            "direction": direction,
            "width": width,
            "comment": comment.strip(),
        })

    # L17 channels
    for ch in _list_or_empty(l17.get("channels")):
        if not isinstance(ch, dict):
            continue
        name = ch.get("name") or ""
        direction = _normalize_dir(ch.get("direction_master")
                                   or ch.get("direction") or "")
        purpose = ch.get("purpose") or ch.get("description") or ""
        # Attempt to parse a width hint from name (e.g., "DQ[7:0]")
        width = 1
        m = re.search(r"\[(\d+):0\]", str(name))
        if m:
            width = int(m.group(1)) + 1
            name = re.sub(r"\[\d+:0\]", "", str(name))
        _add(name, direction, width, comment=purpose)

    # L17 global_signals (clock, reset, power, etc.)
    for sig in _list_or_empty(l17.get("global_signals")):
        if not isinstance(sig, dict):
            continue
        name = sig.get("name") or ""
        purpose = sig.get("purpose") or sig.get("description") or ""
        direction = _normalize_dir(sig.get("direction") or "input")
        _add(name, direction, 1, comment=purpose)

    # L9 top_ports / ports fallback
    for src_key in ("top_ports", "ports"):
        for port in _list_or_empty(l9.get(src_key)):
            if not isinstance(port, dict):
                continue
            name = port.get("name") or ""
            direction = _normalize_dir(port.get("direction") or "input")
            width = port.get("width", 1)
            if isinstance(width, str) and width.isdigit():
                width = int(width)
            if not isinstance(width, int) or width < 1:
                width = 1
            comment = port.get("description") or port.get("purpose") or ""
            _add(name, direction, width, comment=comment)

    # Ensure we have at least a clock + reset stub
    if not any(s["name"].lower().startswith("clk")
               or s["name"].lower() == "clock" for s in signals):
        _add("clk", "input", 1, comment="System clock (auto-added by scaffold)")
    if not any("rst" in s["name"].lower() or "reset" in s["name"].lower()
               for s in signals):
        _add("rst_n", "input", 1, comment="Active-low reset (auto-added)")

    return signals


# ---------------------------------------------------------------------------
# Output: <top>_top.v
# ---------------------------------------------------------------------------

def emit_top_v(top: str, signals: list[dict], l1_ic_name: str) -> str:
    lines: list[str] = [
        "// Auto-generated by phase2_scaffold_gen.py — DO NOT EDIT THE PORT",
        "// LIST manually; fill in the BODY (marked TODO) with module logic.",
        f"// Protocol: {l1_ic_name}",
        f"// Top module: {top}",
        "",
        "`timescale 1ns/1ps",
        "",
        f"module {top} (",
    ]
    # Port declarations
    n = len(signals)
    for i, s in enumerate(signals):
        width = "" if s["width"] == 1 else f"[{s['width']-1}:0] "
        comma = "," if i < n - 1 else ""
        comment = f"  // {s['comment']}" if s["comment"] else ""
        lines.append(f"    {s['direction']:<6} {width}{s['name']}{comma}{comment}")
    lines += [
        ");",
        "",
        "    // -----------------------------------------------------------",
        "    // TODO — protocol behavior (registers + FSM + datapath).",
        "    // The generated scaffold pins ports, widths, and",
        "    // sub-module hierarchy. Functional logic must be written by",
        "    // hand or by the spec-to-rtl skill.",
        "    // -----------------------------------------------------------",
        "",
    ]
    # If we have a clk port, emit a register skeleton; if outputs are present,
    # tie them low to avoid synthesis errors at this stage.
    for s in signals:
        if s["direction"] == "output":
            zero = "1'b0" if s["width"] == 1 else f"{s['width']}'b0"
            lines.append(f"    assign {s['name']} = {zero}; // TODO drive")
    lines += [
        "",
        "endmodule",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Output: <top>_regs.v
# ---------------------------------------------------------------------------

def derive_registers(l4: dict, l8: dict) -> list[dict]:
    """Return a normalized [{name, offset, width, access, fields}, ...]."""
    out: list[dict] = []
    raw = _list_or_empty(l4.get("registers"))
    for r in raw:
        if not isinstance(r, dict):
            continue
        name = _sanitize_id(str(r.get("name") or r.get("abbrev") or "REG"))
        off = r.get("offset") or r.get("address") or ""
        width = r.get("width") or r.get("width_bits") or 8
        if isinstance(width, str):
            m = re.search(r"\d+", width)
            width = int(m.group(0)) if m else 8
        access = r.get("access") or r.get("attribute") or "rw"
        out.append({
            "name": name,
            "offset": str(off),
            "width": int(width),
            "access": str(access).lower(),
            "fields": _list_or_empty(r.get("fields")),
        })
    return out


def emit_regs_v(top: str, regs: list[dict]) -> str:
    if not regs:
        # Protocols without a register file get a stub
        return (
            "// Auto-generated — protocol has no addressable register file.\n"
            "// This file is intentionally empty.\n"
            f"// Top module: {top}\n"
        )
    lines = [
        "// Auto-generated register-file skeleton.",
        "// Address decode + read/write hooks are stubbed; behavior is TODO.",
        f"// Top module: {top}",
        "",
        "`timescale 1ns/1ps",
        "",
        f"module {top}_regs (",
        "    input         clk,",
        "    input         rst_n,",
        "    input  [31:0] reg_addr,",
        "    input         reg_we,",
        "    input  [31:0] reg_wdata,",
        "    output reg [31:0] reg_rdata",
        ");",
        "",
        "    // Register declarations",
    ]
    for r in regs:
        w = r["width"]
        wdecl = "" if w == 1 else f"[{w-1}:0] "
        lines.append(f"    reg {wdecl}{r['name']}; // offset {r['offset']} ({r['access']})")
    lines += [
        "",
        "    // Reset",
        "    always @(posedge clk or negedge rst_n) begin",
        "        if (!rst_n) begin",
    ]
    for r in regs:
        w = r["width"]
        zero = "1'b0" if w == 1 else f"{w}'b0"
        lines.append(f"            {r['name']} <= {zero};")
    lines += [
        "        end else if (reg_we) begin",
        "            // TODO — address decode (per L4 offsets)",
        "        end",
        "    end",
        "",
        "    // Read mux (TODO — match the offsets above)",
        "    always @(*) begin",
        "        reg_rdata = 32'b0;",
        "    end",
        "",
        "endmodule",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Output: <top>_fsm.v
# ---------------------------------------------------------------------------

def derive_fsm_states(l6: dict) -> list[str]:
    out: list[str] = []
    for src_key in ("fsm_states", "fsm_hints",
                    "fsm_hints_transmitter",
                    "fsm_hints_receiver",
                    "fsm_hints_master",
                    "fsm_hints_slave"):
        raw = l6.get(src_key)
        for st in _list_or_empty(raw):
            if isinstance(st, dict):
                nm = st.get("name") or st.get("state") or ""
                if nm:
                    out.append(_sanitize_id(str(nm)))
            elif isinstance(st, str):
                out.append(_sanitize_id(st))
    # Dedup preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for s in out:
        if s in seen:
            continue
        seen.add(s)
        uniq.append(s)
    return uniq[:32]  # cap at 32 to keep enum widths sane


def emit_fsm_v(top: str, states: list[str]) -> str:
    if not states:
        return (
            "// Auto-generated — protocol has no enumerable FSM in L6.\n"
            "// This file is intentionally empty.\n"
            f"// Top module: {top}\n"
        )
    n = len(states)
    w = max(1, (n - 1).bit_length())
    lines = [
        "// Auto-generated FSM skeleton.",
        f"// {n} states — transitions are TODO; only state enum + reset path are generated.",
        f"// Top module: {top}",
        "",
        "`timescale 1ns/1ps",
        "",
        f"module {top}_fsm (",
        "    input  clk,",
        "    input  rst_n,",
        f"    output reg [{w-1}:0] state",
        ");",
        "",
        "    // State encoding",
    ]
    for i, s in enumerate(states):
        lines.append(f"    localparam [{w-1}:0] S_{s.upper()} = {w}'d{i};")
    lines += [
        "",
        "    always @(posedge clk or negedge rst_n) begin",
        "        if (!rst_n) begin",
        f"            state <= S_{states[0].upper()};",
        "        end else begin",
        "            // TODO — transition logic per L6.fsm_transitions",
        "        end",
        "    end",
        "",
        "endmodule",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Output: <top>_tb.v
# ---------------------------------------------------------------------------

def emit_tb_v(top: str, signals: list[dict]) -> str:
    inputs = [s for s in signals if s["direction"] == "input"]
    outputs = [s for s in signals if s["direction"] == "output"]
    inouts = [s for s in signals if s["direction"] == "inout"]
    lines = [
        "// Auto-generated testbench scaffold.",
        "// Stimulus + checks are TODO; the scaffold provides clock, reset,",
        "// DUT instantiation, and waveform dump.",
        f"// Top module: {top}",
        "",
        "`timescale 1ns/1ps",
        "",
        f"module {top}_tb;",
        "",
    ]
    # Declare DUT signals
    for s in signals:
        w = "" if s["width"] == 1 else f"[{s['width']-1}:0] "
        if s["direction"] == "input":
            lines.append(f"    reg  {w}{s['name']};")
        elif s["direction"] == "output":
            lines.append(f"    wire {w}{s['name']};")
        else:
            lines.append(f"    wire {w}{s['name']}; // inout")
    lines += [
        "",
        "    // DUT instance",
        f"    {top} u_dut (",
    ]
    n = len(signals)
    for i, s in enumerate(signals):
        comma = "," if i < n - 1 else ""
        lines.append(f"        .{s['name']}({s['name']}){comma}")
    lines += [
        "    );",
        "",
        "    // Clock generation — defaults to 100 MHz; override per protocol.",
    ]
    clk_name = next((s["name"] for s in inputs
                     if "clk" in s["name"].lower() or "clock" in s["name"].lower()),
                    None)
    if clk_name:
        lines += [
            f"    initial {clk_name} = 1'b0;",
            f"    always #5 {clk_name} = ~{clk_name};",
        ]
    lines += [
        "",
        "    // Reset + waveform + minimal scenario",
        "    initial begin",
        "        $dumpfile(\"" + top + "_tb.vcd\");",
        f"        $dumpvars(0, {top}_tb);",
    ]
    # Default all inputs to 0
    for s in inputs:
        if s["name"] == clk_name:
            continue
        zero = "1'b0" if s["width"] == 1 else f"{s['width']}'b0"
        lines.append(f"        {s['name']} = {zero};")
    # Release reset after 30 ns if a reset-like input is present
    rst_name = next((s["name"] for s in inputs
                     if "rst" in s["name"].lower() or "reset" in s["name"].lower()),
                    None)
    if rst_name:
        active_low = "n" in rst_name.lower()
        if active_low:
            lines.append(f"        {rst_name} = 1'b0;")
            lines.append("        #30;")
            lines.append(f"        {rst_name} = 1'b1;")
        else:
            lines.append(f"        {rst_name} = 1'b1;")
            lines.append("        #30;")
            lines.append(f"        {rst_name} = 1'b0;")
    lines += [
        "        // TODO — protocol stimulus + assertions per L10 test cases.",
        "        #1000;",
        "        $finish;",
        "    end",
        "",
        "endmodule",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Output: compliance_vectors.txt
# ---------------------------------------------------------------------------

def emit_compliance_vectors(l10: dict, l16: dict, l22: dict) -> str:
    lines = [
        "# Auto-generated compliance vector catalog.",
        "# One requirement per line; format: <source-L-doc>: <description>",
        "",
    ]
    # L10 test_cases
    for src in (l10.get("test_cases"),
                l10.get("derived_compliance_test_categories"),
                l10.get("annex_c_normative_fsms"),
                l10.get("annex_d_typical_examples")):
        for item in _list_or_empty(src):
            txt = str(item.get("name") if isinstance(item, dict) else item)
            if txt:
                lines.append(f"L10: {txt[:120]}")
    # L16 must-have compliance
    for src in (l16.get("must_have_properties"),
                l16.get("must_have_compliance"),
                l16.get("compliance_properties")):
        for item in _list_or_empty(src):
            txt = str(item if isinstance(item, str) else item.get("text") or
                      item.get("description") or item)
            if txt and len(txt) > 1:
                lines.append(f"L16: {txt[:120]}")
    # L22 verification plan
    for src in (l22.get("verification_categories"),
                l22.get("verification_plan")):
        for item in _list_or_empty(src):
            txt = str(item if isinstance(item, str) else item.get("text") or
                      item.get("description") or item)
            if txt and len(txt) > 1:
                lines.append(f"L22: {txt[:120]}")
    if len(lines) == 3:
        lines.append("# (no extractable compliance properties found in L10/L16/L22)")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------

def emit_scaffold(project: Path,
                  *,
                  skip_tb: bool = False,
                  skip_regs: bool = False,
                  force: bool = False) -> dict:
    """Emit scaffold for one benchmark project. Returns a report dict."""
    gd = project / "phase1" / "generated_docs"
    if not gd.is_dir():
        return {"project": str(project), "status": "skipped",
                "reason": "phase1/generated_docs missing"}
    out_dir = project / "phase2" / "stage1" / "scaffold"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load the relevant L docs (unwrap fields where applicable)
    l1 = _unwrap_fields(_load(gd / "L1_DATASHEET.json"))
    l4 = _unwrap_fields(_load(gd / "L4_REGMAP.json"))
    l6 = _unwrap_fields(_load(gd / "L6_CONTROL_LOGIC.json"))
    l8 = _unwrap_fields(_load(gd / "L8_RTL_CONSTANTS.json"))
    l9 = _unwrap_fields(_load(gd / "L9_INTEGRATION_SPEC.json"))
    l10 = _unwrap_fields(_load(gd / "L10_TEST_CASES.json"))
    l16 = _unwrap_fields(_load(gd / "L16_COMPLIANCE_PROPERTIES.json"))
    l17 = _unwrap_fields(_load(gd / "L17_CHANNEL_SIGNAL_CATALOG.json"))
    l22 = _unwrap_fields(_load(gd / "L22_VERIFICATION_PLAN.json"))

    ic_name = l1.get("ic_name") or "unknown"
    top = derive_top_module_name(l1, l9, ic_name)
    signals = derive_signals(l17, l9)

    written: list[str] = []

    def _write(name: str, content: str) -> None:
        path = out_dir / name
        if path.is_file() and not force and path.read_text() == content:
            return
        path.write_text(content)
        written.append(name)

    # Always emit top + fsm + compliance
    _write(f"{top}_top.v", emit_top_v(top, signals, ic_name))
    fsm_states = derive_fsm_states(l6)
    _write(f"{top}_fsm.v", emit_fsm_v(top, fsm_states))
    _write("compliance_vectors.txt", emit_compliance_vectors(l10, l16, l22))

    if not skip_regs:
        regs = derive_registers(l4, l8)
        _write(f"{top}_regs.v", emit_regs_v(top, regs))

    if not skip_tb:
        _write(f"{top}_tb.v", emit_tb_v(top, signals))

    return {
        "project": str(project),
        "status": "ok",
        "ic_name": ic_name,
        "top_module": top,
        "signals_count": len(signals),
        "registers_count": (
            len(derive_registers(l4, l8)) if not skip_regs else None),
        "fsm_states_count": len(fsm_states),
        "files_emitted": written,
        "out_dir": str(out_dir),
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
    )
    ap.add_argument("project", type=Path,
                    help="Benchmark project root (contains phase1/, phase2/)")
    ap.add_argument("--skip-tb", action="store_true",
                    help="Skip testbench scaffold")
    ap.add_argument("--skip-regs", action="store_true",
                    help="Skip register-file scaffold")
    ap.add_argument("--force", action="store_true",
                    help="Re-emit even if content matches")
    args = ap.parse_args()

    proj = args.project.resolve()
    if not proj.is_dir():
        print(f"ERROR: project not a directory: {proj}", file=sys.stderr)
        return 2

    report = emit_scaffold(proj,
                           skip_tb=args.skip_tb,
                           skip_regs=args.skip_regs,
                           force=args.force)
    print(json.dumps(report, indent=2))
    return 0 if report.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
