#!/usr/bin/env python3
"""
fpga_clock_divider_antipattern_check.py — gate that catches the FPGA
toggle-divider antipattern: deriving a clock by writing to a register
(usually `clk_X <= ~clk_X` or `clk_X <= cnt[N]`) and then using that
register output as a clock for `always_ff @(posedge clk_X)`.

Why this gate exists
====================
Caught against the v0.119.22 vendor benchmark. The fresh agent emitted:

    logic clk_5m;
    always_ff @(posedge MAX10_CLK1_50) begin
        if (clk_div_cnt == 9) begin
            clk_5m <= ~clk_5m;          // toggle-divider antipattern
        end
    end
    always_ff @(posedge clk_5m or negedge rstn) ...   // use as clock

Quartus emits the diagnostic:

    Node `clk_5m` was determined to be a clock but was found without
    an associated clock assignment.

…and routes the toggling register output through general-purpose logic
fabric instead of a dedicated clock tree. The result on real silicon:

  • Every flop on the divided clock is half the intended frequency
    (a toggle once per N cycles is f_master / (2*N), not f_master / N
    as the agent intends).
  • The clock tree has uncontrolled skew because there's no
    `create_generated_clock` SDC entry for STA to constrain.
  • Combinational logic on the toggling-register output sees glitches.

For the <chip-class> <benchmark> design the chip core ran at 2.5 MHz instead of
5 MHz, every TX bit pulse came out 2× width, and <half-duplex-tester> re-classified
all chip TX as bus-resets — byte[6]=0x02 deterministic FAIL.

The fix is general: use a real PLL/MMCM IP block and add a
`create_generated_clock` constraint. Or keep the divider and use it
as an *enable* signal driven from the master clock, not as a clock.

Rule
----
For every signal `S` used in an `always_ff @(posedge S)` or
`always @(posedge S)` block:

  1. If `S` is also the LHS of an assignment of the form `S <= ~S`
     (toggle) OR `S <= <counter_bit>` (cnt[N] form), AND
  2. The project is an FPGA project (has `.qsf` / `.xdc` / `.qpf`),
     AND
  3. No `.sdc` / `.xdc` file contains
     `create_generated_clock -name <S>` (or implicit equivalents
     like `create_generated_clock -source <master> [get_pins ... <S>]`),

then the gate FAILs with a pointer to the offending RTL line.

The gate is GENERAL — chip-agnostic, vendor-agnostic. Quartus, Vivado,
Lattice all penalise this pattern the same way.

Skip path (no false alerts):
  • Pure ASIC project (no .qsf/.xdc/.qpf) → silent skip.
  • Top-level input ports used as `posedge` — not derived clocks.
  • Signals with a matching `create_generated_clock` SDC entry — the
    constraint is in place, designer knows what they're doing.

Honors waivers.json key `clock_divider_antipattern_intentional` for
the rare legitimate use case (≥20 char reason).

Usage
-----
python3 fpga_clock_divider_antipattern_check.py <project_dir>

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


def find_rtl_files(project_dir: Path) -> list[Path]:
    rtl = _pl.rtl_dir(project_dir)
    if not rtl.is_dir():
        return []
    return sorted(list(rtl.glob("*.sv")) + list(rtl.glob("*.v"))
                  + list(rtl.glob("*.svh")))


def find_sdc_xdc_files(project_dir: Path) -> list[Path]:
    """Locate SDC / XDC timing constraint files, including under standard
    Quartus / Vivado output directories."""
    out: list[Path] = []
    for pat in ("*.sdc", "*.xdc"):
        out.extend(project_dir.rglob(pat))
    # Avoid scanning huge git objects / output_files copies of vendor decks
    return [p for p in out if "output_files" not in p.parts
            and ".git" not in p.parts
            and "node_modules" not in p.parts]


def has_fpga_artifacts(project_dir: Path) -> bool:
    """FPGA-flow detection: any of these markers means the project is
    targeting a real FPGA where derived clocks need explicit constraints."""
    for pat in ("*.qsf", "*.qpf", "*.xdc", "*.tcl"):
        for p in project_dir.rglob(pat):
            if ".git" in p.parts:
                continue
            return True
    return False


# Match `always_ff @(posedge X)` and `always @(posedge X)` — capture X.
POSEDGE_USE_RE = re.compile(
    r"\balways(?:_ff|_latch)?\s*@\s*\(\s*posedge\s+(\w+)",
    re.IGNORECASE,
)


def collect_posedge_signals(src: str) -> set[str]:
    return set(m.group(1) for m in POSEDGE_USE_RE.finditer(src))


# Toggle assignment: S <= ~S
def is_toggled(src: str, sig: str) -> tuple[bool, int]:
    pat = re.compile(
        r"\b" + re.escape(sig) + r"\s*<=\s*~\s*" + re.escape(sig) + r"\b",
        re.IGNORECASE,
    )
    m = pat.search(src)
    if not m:
        return False, 0
    line = src[:m.start()].count("\n") + 1
    return True, line


# Counter-bit assignment: S <= cnt[N], S = cnt[N]
def is_counter_bit_assigned(src: str, sig: str) -> tuple[bool, int]:
    pat = re.compile(
        r"\bassign\s+" + re.escape(sig) + r"\s*=\s*\w+\s*\[\s*\d+\s*\]",
        re.IGNORECASE,
    )
    m = pat.search(src)
    if m:
        line = src[:m.start()].count("\n") + 1
        return True, line
    pat = re.compile(
        r"\b" + re.escape(sig) + r"\s*<=\s*\w+\s*\[\s*\d+\s*\]",
        re.IGNORECASE,
    )
    m = pat.search(src)
    if m:
        line = src[:m.start()].count("\n") + 1
        return True, line
    return False, 0


def is_top_level_input(src: str, sig: str) -> bool:
    """Detect when `sig` is declared as a module input port (so it's a real
    clock input from the package pin, not a derived signal)."""
    pat = re.compile(
        r"\binput\b(?:\s+(?:wire|logic|reg))?\s+(?:\[[^\]]+\]\s+)?"
        + re.escape(sig) + r"\b",
        re.IGNORECASE,
    )
    return bool(pat.search(src))


def has_create_generated_clock(sdc_files: list[Path], sig: str) -> bool:
    """Look for `create_generated_clock` referencing the signal. Match
    common forms: -name <sig>, [get_pins ... <sig>], [get_nets <sig>]."""
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


def waived(project_dir: Path) -> bool:
    waivers = project_dir / "waivers.json"
    if not waivers.exists():
        return False
    try:
        d = json.loads(waivers.read_text())
        v = d.get("clock_divider_antipattern_intentional", "")
        if isinstance(v, str) and len(v.strip()) >= 20:
            return True
    except Exception:
        pass
    return False


def main():
    if len(sys.argv) < 2:
        print("Usage: fpga_clock_divider_antipattern_check.py <project_dir>")
        sys.exit(2)
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        print(f"FAIL — project dir not found: {project}")
        sys.exit(1)

    rtl_files = find_rtl_files(project)
    if not rtl_files:
        print("PASS — no rtl/ directory or no Verilog/SV files (gate skipped)")
        sys.exit(0)

    if not has_fpga_artifacts(project):
        print("PASS — no FPGA artifacts (.qsf/.xdc/.qpf); not an FPGA project "
              "(gate skipped)")
        sys.exit(0)

    sdc_files = find_sdc_xdc_files(project)

    # Build a global view of all RTL: posedge signals, toggle assigns,
    # counter-bit assigns, top-level inputs.
    full_src_per_file: dict[Path, str] = {}
    for f in rtl_files:
        try:
            full_src_per_file[f] = strip_comments(f.read_text())
        except Exception:
            pass

    all_src = "\n".join(full_src_per_file.values())
    posedge_sigs = collect_posedge_signals(all_src)

    findings = []
    for sig in sorted(posedge_sigs):
        # Skip if it's a top-level input port (real package pin)
        if is_top_level_input(all_src, sig):
            continue
        # Find toggle / counter-bit derivation in any RTL file
        derived = False
        derive_evidence = ""
        for f, src in full_src_per_file.items():
            t, line = is_toggled(src, sig)
            if t:
                derived = True
                derive_evidence = f"{f.name}:{line}: {sig} <= ~{sig}"
                break
            t, line = is_counter_bit_assigned(src, sig)
            if t:
                derived = True
                derive_evidence = (f"{f.name}:{line}: {sig} <= "
                                   "<counter_bit>")
                break
        if not derived:
            continue
        # Derived clock found. Check for SDC constraint.
        if has_create_generated_clock(sdc_files, sig):
            continue
        findings.append((sig, derive_evidence))

    if not findings:
        print(f"PASS — no FPGA toggle-divider clock antipatterns detected "
              f"({len(posedge_sigs)} posedge signal(s) scanned)")
        sys.exit(0)

    if waived(project):
        print(f"PASS_WITH_WAIVER — {len(findings)} derived clock(s) lack "
              f"create_generated_clock SDC entry, but waiver is set:")
        for sig, ev in findings:
            print(f"  • {sig}: {ev}")
        sys.exit(0)

    print(f"FAIL — {len(findings)} FPGA derived-clock antipattern(s) "
          f"without matching create_generated_clock constraint:")
    for sig, ev in findings:
        print(f"  • {ev}")
        print(f"    used as clock in always_ff @(posedge {sig} ...)")
        print(f"    no `create_generated_clock -name {sig}` found in any "
              "*.sdc / *.xdc")
    print()
    print("Why this matters:")
    print("  Quartus / Vivado / Lattice all detect this as 'clock without")
    print("  associated clock assignment'. The toggling register output is")
    print("  routed through general-purpose logic, NOT a dedicated clock")
    print("  tree:")
    print("    1. Effective frequency is f_master / (2*N), not f_master / N")
    print("       — the divider toggles once per N cycles, so each phase")
    print("       lasts N cycles. Your TX/RX timing is silently 2× spec.")
    print("    2. STA cannot constrain the derived clock without an SDC")
    print("       create_generated_clock entry → uncontrolled skew.")
    print("    3. Every downstream flop sees clock-tree glitches.")
    print()
    print("Fix options:")
    print("  1. Replace the toggle divider with a real PLL/MMCM/IP block")
    print("     (Altera ALTPLL, Xilinx MMCME, Lattice PLL) and add:")
    print("        create_generated_clock -source <master> -divide_by N \\")
    print("            -name <derived> [get_pins <pll>/clkout]")
    print("  2. Keep the counter and use it as an *enable* signal, not a")
    print("     clock:")
    print("        always_ff @(posedge master_clk) begin")
    print("          if (counter == N-1) counter <= 0;")
    print("          else                 counter <= counter + 1;")
    print("          tx_tick <= (counter == N-1);  // ENABLE, not CLOCK")
    print("        end")
    print("        always_ff @(posedge master_clk) if (tx_tick) ...")
    print("  3. Add an explicit create_generated_clock for the derived")
    print("     signal in the SDC if the toggle is intentional and you've")
    print("     verified the clock-tree route on the FPGA.")
    print()
    print('Or document an exception in waivers.json (>=20 chars):')
    print('    {"clock_divider_antipattern_intentional": "<reason>"}')
    sys.exit(1)


if __name__ == "__main__":
    main()
