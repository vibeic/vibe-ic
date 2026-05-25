#!/usr/bin/env python3
"""
toggle_divider_hierarchical_clock_check.py — gate (LL-31) extending
LL-27 (`fpga_clock_divider_antipattern_check`) across module
boundaries.

Why this gate exists
====================
LL-27 catches `clk_div <= ~clk_div` followed by `always_ff @(posedge
clk_div)` when both occur in the same RTL file. v0.119.30 <benchmark> vendor
benchmark caught a hierarchical variant LL-27 misses:

    // toplevel.v
    always_ff @(posedge MAX10_CLK1_50) clk_div <= ~clk_div;
    chip_top u_chip ( .clk(clk_div), ... );

    // chip_top.v
    always_ff @(posedge clk) ...    // posedge of toggle-derived signal,
                                    // but invisible when scanning per-file.

The toggle-derived signal IS used as a posedge clock — just one module
boundary away — and Quartus still routes it through general fabric
without an SDC `create_generated_clock`. This gate follows the
instance port mapping and treats `posedge X` inside the submodule as
posedge of the toggle-derived signal at the wrapper.

Rule
----
1. Find FPGA project markers (`.qsf` / `.qpf` / `.xdc`). Skip silently
   for ASIC.
2. Find every toggle assignment `<sig> <= ~<sig>` in any RTL file.
   Build set TOGGLES.
3. For each module instantiation, parse `.<port>(<arg>)` mappings.
   For each (port, arg) where arg ∈ TOGGLES, find the submodule's
   declaration and check if any `always_ff @(posedge <port>)` exists
   inside it. If yes, this is a hierarchical posedge use.
4. If a matching `create_generated_clock` SDC entry exists for the
   wrapper signal, PASS.
5. Otherwise FAIL with the offending signal + module + port.

Honors waivers.json key `toggle_divider_hierarchical_intentional`
(≥20 chars).

Note: chip-agnostic — the check operates on RTL syntax + SDC presence,
no chip names hardcoded.

Usage
-----
python3 toggle_divider_hierarchical_clock_check.py <project_dir>

Returns 0 on PASS / silent-skip / waived, 1 on FAIL.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
import _path_layout as _pl


def strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def find_rtl_files(project: Path) -> list[Path]:
    rtl = _pl.rtl_dir(project)
    if not rtl.is_dir():
        return []
    return sorted(list(rtl.glob("*.sv")) + list(rtl.glob("*.v"))
                  + list(rtl.glob("*.svh")))


def has_fpga_artifacts(project: Path) -> bool:
    for pat in ("*.qsf", "*.qpf", "*.xdc"):
        for p in project.rglob(pat):
            if ".git" in p.parts:
                continue
            return True
    return False


def find_sdc_xdc(project: Path) -> list[Path]:
    out: list[Path] = []
    for pat in ("*.sdc", "*.xdc"):
        for p in project.rglob(pat):
            if "output_files" in p.parts or ".git" in p.parts:
                continue
            out.append(p)
    return out


TOGGLE_PAT = re.compile(r"\b(\w+)\s*<=\s*~\s*\1\b", re.MULTILINE)

# Match a Verilog/SV module declaration: `module <name> ( ... );`
MODULE_DECL_PAT = re.compile(
    r"\bmodule\s+(\w+)\s*[#(]",
)

# Match a module instantiation: `<modname> <instname> (...)` — but NOT
# `module <name> (...)`. Heuristic: first token (modname) is followed
# by an identifier (instname), then `(`. We exclude the `module`
# keyword and a few other reserved words.
INST_PAT = re.compile(
    r"\b(?!module\b|function\b|task\b|begin\b|if\b|else\b|case\b|"
    r"casez\b|casex\b|endmodule\b|endfunction\b|endtask\b|always\b|"
    r"always_ff\b|always_comb\b|always_latch\b|assign\b|wire\b|reg\b|"
    r"logic\b|input\b|output\b|inout\b|parameter\b|localparam\b|"
    r"generate\b|endgenerate\b|initial\b|forever\b|repeat\b|"
    r"while\b|for\b|return\b|fork\b|join\b)"
    r"(\w+)(?:\s*#\s*\([^)]*\))?\s+(\w+)\s*\(",
)

# Inside a port-map, find `.<port>(<arg>)` — arg is an identifier.
PORT_MAP_PAT = re.compile(
    r"\.\s*(\w+)\s*\(\s*(\w+)\s*\)",
)

POSEDGE_PAT = re.compile(
    r"\balways(?:_ff|_latch)?\s*@\s*\(\s*posedge\s+(\w+)",
    re.IGNORECASE,
)


def parse_module_bodies(src: str) -> dict[str, str]:
    """Return {module_name: body_text}. Crude bracket-matching."""
    out: dict[str, str] = {}
    cursor = 0
    while True:
        m = MODULE_DECL_PAT.search(src, cursor)
        if not m:
            break
        name = m.group(1)
        end_kw = re.search(r"\bendmodule\b", src[m.end():])
        if not end_kw:
            break
        body = src[m.end():m.end() + end_kw.start()]
        out[name] = body
        cursor = m.end() + end_kw.end()
    return out


def find_module_instances(body: str) -> list[tuple[str, str, str]]:
    """Return list of (modname, instname, paren_block_text)."""
    out: list[tuple[str, str, str]] = []
    for m in INST_PAT.finditer(body):
        modname = m.group(1)
        instname = m.group(2)
        # Find balanced `(` ... `);` from m.end() - 1
        start = m.end() - 1
        depth = 0
        i = start
        while i < len(body):
            c = body[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    out.append((modname, instname, body[start:i + 1]))
                    break
            i += 1
    return out


def has_create_generated_clock(sdc_files: list[Path], sig: str) -> bool:
    pat_name = re.compile(
        r"create_generated_clock[^\n#]*-name\s+" + re.escape(sig) + r"\b",
        re.IGNORECASE,
    )
    pat_pin = re.compile(
        r"create_generated_clock[^\n#]*get_(?:pins|nets|registers)[^\n#]*"
        + re.escape(sig),
        re.IGNORECASE,
    )
    for p in sdc_files:
        try:
            text = p.read_text(errors="replace")
        except Exception:
            continue
        if pat_name.search(text) or pat_pin.search(text):
            return True
    return False


def waived(project: Path) -> bool:
    p = project / "waivers.json"
    if not p.exists():
        return False
    try:
        d = json.loads(p.read_text())
        v = d.get("toggle_divider_hierarchical_intentional", "")
        return isinstance(v, str) and len(v.strip()) >= 20
    except Exception:
        return False


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: toggle_divider_hierarchical_clock_check.py "
              "<project_dir>")
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        print(f"FAIL — project dir not found: {project}")
        return 1

    rtl_files = find_rtl_files(project)
    if not rtl_files:
        print("PASS — no rtl/ files (gate skipped)")
        return 0

    if not has_fpga_artifacts(project):
        print("PASS — no FPGA artifacts (.qsf/.xdc/.qpf); not an FPGA "
              "project (gate skipped)")
        return 0

    sources: dict[str, str] = {}
    all_src = ""
    for f in rtl_files:
        try:
            text = strip_comments(f.read_text())
        except Exception:
            continue
        sources[f.name] = text
        all_src += "\n" + text

    toggles = {m.group(1) for m in TOGGLE_PAT.finditer(all_src)}
    if not toggles:
        print("PASS — no toggle-divider assignments found (gate skipped)")
        return 0

    modules = parse_module_bodies(all_src)
    sdc_files = find_sdc_xdc(project)

    findings: list[tuple[str, str, str, str]] = []
    # (toggle_sig, submod_name, port, evidence)

    for parent_body in modules.values():
        for modname, instname, block in find_module_instances(parent_body):
            if modname not in modules:
                continue
            sub_body = modules[modname]
            sub_posedge_sigs = {
                m.group(1) for m in POSEDGE_PAT.finditer(sub_body)
            }
            if not sub_posedge_sigs:
                continue
            for port, arg in PORT_MAP_PAT.findall(block):
                if arg in toggles and port in sub_posedge_sigs:
                    if has_create_generated_clock(sdc_files, arg):
                        continue
                    findings.append(
                        (arg, modname, port,
                         f"{modname} {instname} (.{port}({arg}))")
                    )

    if not findings:
        print(f"PASS — no hierarchical toggle-divider clock crossings "
              f"({len(toggles)} toggle signal(s) scanned)")
        return 0

    if waived(project):
        print(f"PASS_WITH_WAIVER — {len(findings)} hierarchical toggle "
              f"clock crossing(s), waiver set")
        for sig, mod, port, ev in findings:
            print(f"  • {ev}")
        return 0

    print(f"FAIL — {len(findings)} toggle-derived signal(s) used as "
          f"posedge clock through a submodule port (no create_generated"
          f"_clock SDC entry):")
    for sig, mod, port, ev in findings:
        print(f"  • {ev}")
        print(f"      `{sig}` is toggle-divided AND fed into "
              f"`{mod}` port `.{port}` which has "
              f"`always_ff @(posedge {port})`")
    print()
    print("Why this matters:")
    print("  LL-27 only checks intra-module use. Splitting the divider")
    print("  across a submodule boundary lets Quartus still route the")
    print("  toggling register output through general logic fabric.")
    print("  Effective freq is half intended; clock tree skew is")
    print("  unconstrained because no SDC create_generated_clock binds")
    print("  the derived clock.")
    print()
    print("Fix: PLL-derived clock + create_generated_clock for `<sig>`,")
    print("     OR reshape the divider into an *enable* (clk_en) signal")
    print("     and clock the submodule from the master clock.")
    print()
    print('Or document the intentional case in waivers.json (>=20 chars):')
    print('    {"toggle_divider_hierarchical_intentional": "<reason>"}')
    return 1


if __name__ == "__main__":
    sys.exit(main())
