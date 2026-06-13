#!/usr/bin/env python3
"""
clock_cascade_synthesis_check.py — refuse a top-level RTL that ties
every submodule's clock port to a single wire when L9
`clock_binding` declares ≥2 distinct clocks for ≥2 modules.

Why this gate exists
====================
Surfaced by ROOT_CAUSE_ANALYSIS Area 2 (<benchmark> fresh agent vs vendor).
The vendor design has a divider chain (5MHz → 2.5MHz → 1.25MHz →
312.5kHz) and binds different submodules to different divisor outputs
(RX_PHY at 5MHz, TX_PHY at 2.5MHz, GEN_WAKE at 312.5kHz). The fresh
agent collapsed the cascade into a single 5MHz clock and routed
every submodule's `clk` port to the same wire `clk_sys`. Per-block
counters then over/underflow against the spec'd window widths and the
host receiver mis-classifies bytes.

Rule
----
1. Read L9_INTEGRATION_SPEC.json `clock_binding` (or `clock_bindings`).
2. Filter to entries where the clock name is a string. Build the set
   of distinct clock-name targets.
3. If the set size < 2, gate does not apply (silent skip).
4. Otherwise inspect every top-level RTL file (rtl/dtop*.v / *.sv /
   project_top*.v / fpga_top*.v / de10*top*.v):
   - For each submodule instance whose name appears as a key in
     `clock_binding`, find its `.clk(...)` / `.<port>(...)` actual.
     If every binding-listed module is wired to the same actual wire,
     FAIL.
5. Skip silently when L9 has no clock_binding, when no top-level RTL
   is found, or when no submodule in clock_binding is instantiated.

Honors waivers.json key `clock_cascade_synthesis_alternative`
(≥20-char rationale).

Usage
-----
python3 clock_cascade_synthesis_check.py <project_dir>

Returns 0 on PASS / silent-skip / waived, 1 on FAIL.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
import _path_layout as _pl


CLOCK_PORT_NAMES = (
    "clk", "clock", "sys_clk", "core_clk",
    "clk_sys", "sys_clock", "clkin", "clk_in",
)


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def _load_json(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _find_l_jsons(project: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for base in (project, _pl.generated_docs_dir(project)):
        if not base.exists():
            continue
        for p in base.glob("L*.json"):
            out.setdefault(p.name, p)
    return out


def _find_top_rtl_files(project: Path) -> list[Path]:
    out: list[Path] = []
    for root in (_pl.rtl_dir(project), project / "src", project / "hdl",
                 _pl.fpga_early_dir(project)):
        if not root.is_dir():
            continue
        for ext in ("*.v", "*.sv"):
            for p in root.rglob(ext):
                low = p.name.lower()
                if any(t in low for t in
                       ("dtop", "project_top", "fpga_top", "de10",
                        "_top.", "top_top.")):
                    out.append(p)
    return sorted(set(out))


def _collect_instantiations(src: str) -> list[tuple[str, str, str]]:
    """Return [(module_type, instance_name, port_block_text)] for
    every Verilog instantiation `module_type [#(...)] inst_name (
        .port(actual), ... );`. Crude but covers ~all real RTL."""
    src = _strip_comments(src)
    out: list[tuple[str, str, str]] = []
    pat = re.compile(
        r"\b([A-Za-z_]\w*)\s+"            # module_type
        r"(?:#\s*\([^()]*\)\s*)?"          # optional parameter block
        r"([A-Za-z_]\w*)\s*"               # instance_name
        r"\(([^;]*?)\)\s*;",               # port block
        re.DOTALL,
    )
    # Verilog reserved words to NOT mistake for module types.
    reserved = {
        "module", "endmodule", "input", "output", "inout", "reg",
        "wire", "logic", "assign", "always", "initial", "begin",
        "end", "if", "else", "case", "endcase", "for", "while",
        "function", "endfunction", "task", "endtask", "parameter",
        "localparam", "generate", "endgenerate", "genvar", "integer",
        "return", "default", "posedge", "negedge", "or", "and",
        "not", "xor", "buf", "tri", "supply0", "supply1", "typedef",
        "struct", "enum", "package", "endpackage", "import",
    }
    for m in pat.finditer(src):
        mtype = m.group(1)
        iname = m.group(2)
        if mtype.lower() in reserved or iname.lower() in reserved:
            continue
        out.append((mtype, iname, m.group(3)))
    return out


def _find_clock_actual(port_block: str) -> str | None:
    """Inside a port-binding block, find the actual wire bound to a
    clock-class port (`.clk(actual)` / `.clock(actual)` / etc.).
    Returns the actual wire name (no whitespace), or None."""
    for port in CLOCK_PORT_NAMES:
        pat = re.compile(
            rf"\.\s*{re.escape(port)}\s*\(\s*([^),]+?)\s*\)",
            re.IGNORECASE,
        )
        m = pat.search(port_block)
        if m:
            return re.sub(r"\s+", "", m.group(1))
    return None


def _l9_clock_binding(l9: dict) -> dict[str, str]:
    """Normalise `clock_binding` to lowercase-key dict of strings."""
    if not isinstance(l9, dict):
        return {}
    cb = l9.get("clock_binding") or l9.get("clock_bindings") or {}
    if not isinstance(cb, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in cb.items():
        if isinstance(k, str) and isinstance(v, str):
            out[k.lower()] = v
    return out


def _waived(project: Path) -> bool:
    waivers = project / "waivers.json"
    if not waivers.exists():
        return False
    try:
        d = json.loads(waivers.read_text())
        v = d.get("clock_cascade_synthesis_alternative", "")
        return isinstance(v, str) and len(v.strip()) >= 20
    except Exception:
        return False


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: clock_cascade_synthesis_check.py <project_dir>")
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        print(f"FAIL — not a directory: {project}")
        return 1

    l_jsons = _find_l_jsons(project)
    l9 = _load_json(l_jsons.get("L9_INTEGRATION_SPEC.json", Path()))
    binding = _l9_clock_binding(l9)
    if not binding:
        print("PASS — L9 has no clock_binding (gate not applicable)")
        return 0

    distinct_clocks = {v for v in binding.values()}
    if len(distinct_clocks) < 2:
        print(f"PASS — L9.clock_binding declares only {len(distinct_clocks)} "
              "distinct clock(s); cascade not required (gate skipped)")
        return 0

    top_files = _find_top_rtl_files(project)
    if not top_files:
        print("PASS — no top-level RTL file found (gate skipped)")
        return 0

    # Collect every instance of every binding-listed module from all
    # top files; map instance → actual clock wire.
    seen: list[tuple[str, str, str, str]] = []  # (top_file, mtype, iname, actual)
    for f in top_files:
        try:
            src = f.read_text()
        except Exception:
            continue
        for mtype, iname, ports in _collect_instantiations(src):
            mtype_l = mtype.lower()
            iname_l = iname.lower()
            if mtype_l in binding or iname_l in binding:
                actual = _find_clock_actual(ports)
                if actual:
                    seen.append((f.name, mtype, iname, actual))

    if not seen:
        print("PASS — no binding-listed submodule found in top RTL "
              "(gate not applicable)")
        return 0

    # Distinct actuals across the binding-listed instances.
    actual_set = {a for _, _, _, a in seen}
    if len(actual_set) >= 2:
        print(f"PASS — top RTL routes binding-listed submodules to "
              f"{len(actual_set)} distinct clock wire(s) "
              f"(L9 declares {len(distinct_clocks)} clocks)")
        for f, mtype, iname, actual in seen:
            print(f"  • {iname} ({mtype}) ← {actual}    [{f}]")
        return 0

    only_actual = next(iter(actual_set))
    if _waived(project):
        print(f"PASS_WITH_WAIVER — top RTL ties all {len(seen)} "
              f"binding-listed submodule(s) to single wire "
              f"`{only_actual}` but waiver is set")
        return 0

    print(f"FAIL — L9.clock_binding declares {len(distinct_clocks)} "
          f"distinct clocks for the listed submodules:")
    for k, v in binding.items():
        print(f"    {k} → {v}")
    print(f"  but top RTL ties every binding-listed submodule clock "
          f"to a single wire `{only_actual}`:")
    for f, mtype, iname, actual in seen:
        print(f"    {iname} ({mtype}) ← {actual}    [{f}]")
    print()
    print("Why this matters:")
    print("  When the spec mandates a divider cascade, the per-block")
    print("  counters in each submodule are sized to overflow at the")
    print("  spec'd window width FOR THAT BLOCK'S CLOCK. Tying every")
    print("  submodule to a single fast clock makes those counters")
    print("  hit the wrong threshold, and the host's receiver mis-")
    print("  classifies bit-cell pulse widths or frame boundaries.")
    print()
    print("Fix: regenerate the top module so each binding-listed")
    print("  submodule receives its declared divided clock (typically")
    print("  via a dclk_div / DCLK module). Or document an explicit")
    print("  exception in waivers.json (≥20 chars):")
    print('    {"clock_cascade_synthesis_alternative": "<reason>"}')
    return 1


if __name__ == "__main__":
    sys.exit(main())
