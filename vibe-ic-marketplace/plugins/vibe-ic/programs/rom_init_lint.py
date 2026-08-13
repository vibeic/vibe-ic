#!/usr/bin/env python3
"""
rom_init_lint.py — Detect Quartus-unsafe ROM initialization patterns.

Learned from <chip-class> FPGA BIST debug (2026-04-21):

  `initial begin for (integer i = 0; i < N; i = i + 1) rom[i] = ...; end`

Quartus MAX10 (and most Altera/Intel families) silently drops this pattern,
defaulting the ROM to all-zero in hardware. Simulation passes, FPGA is broken.
The only symptoms are two easy-to-miss warnings in the .map.rpt:

    Warning (10030): Net "rom" has no driver or initial value
    Warning (10855): initial value for variable rom should be constant

This program statically scans RTL and flags any `initial` block that:
  - declares an `integer` loop index
  - uses that index inside a `for` loop
  - assigns into a `reg [..] rom [...]` style memory

Preferred replacements (both Quartus-safe):
  A. Combinational `case` that returns the ROM value (synthesized as LUTs).
  B. `$readmemh("rom.hex", rom);` with an external hex/mif file.

Usage:
    python3 rom_init_lint.py <files.v|.sv ...>
    python3 rom_init_lint.py --json <out.json> <files.v|.sv ...>

Exit codes:
    0 = no findings
    1 = findings issued
    2 = usage / io error
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)


@dataclass
class Finding:
    file: str
    line: int
    snippet: str
    rule: str
    severity: str  # "error" — always blocking
    fix_hint: str


# Strip line comments and block comments so patterns don't false-match inside comments.
_LINE_CMT = re.compile(r"//[^\n]*")
_BLOCK_CMT = re.compile(r"/\*.*?\*/", re.DOTALL)

# Memory decl: `reg [7:0] rom [0:N];` or `reg [7:0] rom [N];`
_MEM_DECL = re.compile(
    r"\breg\s*(\[[^\]]+\])?\s*(\w+)\s*\[[^\]]+\]\s*;"
)

# initial block body
_INITIAL = re.compile(r"\binitial\b\s*begin(.*?)\bend\b", re.DOTALL)

# `$readmemh("file", mem)` / `$readmemb(...)`. The FIRST argument is deliberately
# unconstrained — in real designs it is often a parameter or a macro, not a literal —
# because what decides the question is the TARGET MEMORY, not where the data lives.
_READMEM = re.compile(r"\$readmem[hb]\s*\(\s*[^,]+,\s*([A-Za-z_]\w*)")


def scan_file(path: Path) -> List[Finding]:
    try:
        raw = path.read_text(errors="replace")
    except OSError as exc:
        raise SystemExit(f"rom_init_lint: cannot read {path}: {exc}")

    # Keep line-number mapping after comment strip
    def strip_comments(src: str) -> str:
        src = _BLOCK_CMT.sub(lambda m: "\n" * m.group(0).count("\n"), src)
        src = _LINE_CMT.sub("", src)
        return src

    clean = strip_comments(raw)

    # Collect declared memories (name set) — allows us to be precise about what
    # counts as "writing into a ROM/LUT array".
    mems = {m.group(2) for m in _MEM_DECL.finditer(clean)}
    if not mems:
        return []

    # Collect integer declarations at ANY scope (module-level OR inside initial).
    # In practice the broken pattern often has `integer i;` at module scope and
    # uses it inside the `initial` for-loop.
    module_ints = {m.group(1) for m in re.finditer(r"\binteger\s+(\w+)\s*;", clean)}

    findings: List[Finding] = []
    for m in _INITIAL.finditer(clean):
        body = m.group(1)
        body_start_line = clean[: m.start()].count("\n") + 1

        # Try integer declared inside the initial block first; fall back to module scope.
        idx = None
        int_decl = re.search(r"\binteger\s+(\w+)\s*;", body)
        if int_decl:
            idx = int_decl.group(1)
        else:
            # Any integer index used in a for-header inside this body?
            for cand in module_ints:
                if re.search(rf"\bfor\s*\(\s*{re.escape(cand)}\s*=", body):
                    idx = cand
                    break
        if idx is None:
            continue

        # `for (idx = ... ; idx ... ; idx = idx + ...)` or similar
        for_hdr = re.search(
            rf"\bfor\s*\(\s*{re.escape(idx)}\s*=.*?;\s*{re.escape(idx)}\b.*?;\s*{re.escape(idx)}\s*=.*?\)",
            body,
            re.DOTALL,
        )
        if not for_hdr:
            continue

        # Any assignment into a declared memory using the loop index?
        hit = None
        for mem in mems:
            ass = re.search(
                rf"\b{re.escape(mem)}\s*\[\s*{re.escape(idx)}\s*\]\s*=",
                body,
            )
            if ass:
                hit = (mem, ass)
                break
        if not hit:
            continue

        mem_name, ass_match = hit

        # NOT A DEFECT when this same initial body then loads the SAME memory from an
        # external file: the zeroing loop is a benign prologue and the array's real
        # contents come from `$readmem*`, which IS remediation (B) that this program's
        # own fix_hint recommends. Measured on a real design: the flagged code already
        # did exactly what the hint asks for, and the gate failed the whole cell for it.
        #
        # Deliberately narrow — keyed on the SAME memory, not on the mere PRESENCE of a
        # `$readmem*` call. A body that zeroes `mem` and loads `other` is still the
        # defect and must still fire; so is a body with no `$readmem*` at all. Both are
        # regression-pinned in programs/tests/test_rom_init_lint.py.
        loaded = {m.group(1) for m in _READMEM.finditer(body)}
        if mem_name in loaded:
            continue

        # Compute line number of the offending assignment
        off_line = body_start_line + body[: ass_match.start()].count("\n")

        findings.append(
            Finding(
                file=str(path),
                line=off_line,
                snippet=body[ass_match.start() : ass_match.end() + 40].strip(),
                rule="quartus-unsafe-rom-init",
                severity="error",
                fix_hint=(
                    f"Quartus MAX10 cannot synthesize `initial begin for ({idx}=...) "
                    f"{mem_name}[{idx}] = ...`. It silently defaults {mem_name} to 0 "
                    f"and emits only Warning (10030)+(10855). Replace with a "
                    f"combinational `case` returning the ROM value, or use "
                    f"`$readmemh(\"{mem_name}.hex\", {mem_name});` with an external "
                    f"hex file. See LL memory: feedback_quartus_init_for_loop.md"
                ),
            )
        )

    return findings


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("files", nargs="+", help="RTL files (.v / .sv)")
    p.add_argument("--json", help="Write findings as JSON to this path")
    args = p.parse_args(argv)

    all_findings: List[Finding] = []
    for f in args.files:
        path = Path(f)
        if not path.exists():
            print(f"rom_init_lint: missing file: {f}", file=sys.stderr)
            return 2
        all_findings.extend(scan_file(path))

    if args.json:
        atomic_write_text(Path(args.json), json.dumps([asdict(x) for x in all_findings], indent=2))

    if not all_findings:
        print("rom_init_lint: OK — no Quartus-unsafe ROM initializers found")
        return 0

    for f in all_findings:
        print(
            f"{f.file}:{f.line}: ERROR [{f.rule}] {f.snippet}\n"
            f"    fix: {f.fix_hint}",
            file=sys.stderr,
        )
    print(
        f"\nrom_init_lint: {len(all_findings)} finding(s)",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
