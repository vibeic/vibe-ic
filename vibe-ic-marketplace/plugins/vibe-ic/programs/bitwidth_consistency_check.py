#!/usr/bin/env python3
"""bitwidth_consistency_check.py — flag Verilog bit-selects that exceed the
register's declared width.

Catches the <chip-class> v042 fresh-agent bug: `reg [4:0] resp_data_idx;` indexed as
`resp_data_idx[6:0]` — a 5-bit register being used as a 7-bit value. Quartus
synthesis does catch this as an elaboration error, but early lint saves a
full compile iteration.

Exit: 0 = PASS, 1 = FAIL.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Tuple

# Kimi-scale fix — this gate audits AUTHORED RTL SOURCE. Directory arguments
# route through the shared collector (canonical phase2/stage1/rtl preferred;
# generated netlist/sim/verify outputs + >8MB files excluded on fallback) so a
# 342 MB emitted netlist_yosys.v can never enter the char-level scan again
# (see _specrtl_common.rtl_source_files for the full scale rationale).
try:
    from _specrtl_common import rtl_source_files
except ImportError:                      # packaged relative import
    from ._specrtl_common import rtl_source_files


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0


@dataclass
class AuditResult:
    passed: bool
    findings: List[Finding]
    stats: dict

    def to_json(self) -> str:
        return json.dumps(
            {
                "passed": self.passed,
                "findings": [asdict(f) for f in self.findings],
                "stats": self.stats,
            },
            indent=2,
        )


# Match `reg [HI:LO] name;` or `reg [HI:LO] name = expr;` or `wire [HI:LO] name;`
REG_DECL_RE = re.compile(
    r"\b(?:reg|wire|logic)\s*\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*(\w+)\s*(?:=|;|,)",
)
# Match `name[HI:LO]` bit-select
BITSELECT_RE = re.compile(r"\b(\w+)\s*\[\s*(\d+)\s*:\s*(\d+)\s*\]")
# ORGANIC #584 — module boundary markers for per-MODULE scoping.
MODULE_RE = re.compile(r"^\s*module\s+([A-Za-z_]\w*)", re.M)
ENDMODULE_RE = re.compile(r"^\s*endmodule\b", re.M)
# ORGANIC #584 round-2 — function/task bodies are NESTED scopes: an sv2v
# package-function gets inlined per-module as `function automatic …` whose
# locals (`reg [1:0] a;`) must not shadow the module-level declaration
# (`input wire [7:0] a;`) for module-body index expressions.
FUNC_RE = re.compile(r"^\s*(function|task)\b", re.M)
ENDFUNC_RE = re.compile(r"^\s*(endfunction|endtask)\b", re.M)


def _module_regions(text: str) -> List[Tuple[int, int, str]]:
    """ORGANIC #584 — return [(start, end, module_name)] character ranges
    of every module…endmodule region in the file. sv2v emits one .v per
    source .sv but each file routinely holds MULTIPLE modules; the
    declaration→index pairing must be scoped per module or two modules
    using the same short signal name (a, b, q) at different widths
    cross-match into false bitselect-out-of-range errors. Text outside
    any region (none in legal Verilog) falls back to a whole-file region.
    """
    starts = [(m.start(), m.group(1)) for m in MODULE_RE.finditer(text)]
    if not starts:
        return [(0, len(text), "")]
    ends = [m.end() for m in ENDMODULE_RE.finditer(text)]
    regions: List[Tuple[int, int, str]] = []
    for i, (s, name) in enumerate(starts):
        nxt = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        # First endmodule after this module's start (and before the next
        # module's start) closes the region; fall back to next start.
        e = next((x for x in ends if s < x <= nxt), nxt)
        regions.append((s, e, name))
    return regions


def _function_regions(region: str) -> List[Tuple[int, int]]:
    """ORGANIC #584 r2 — [(start, end)] ranges of function…endfunction /
    task…endtask bodies WITHIN one module region (offsets relative to the
    region). Verilog-2005 functions don't nest, so a flat first-end-after-
    start pairing suffices."""
    starts = [m.start() for m in FUNC_RE.finditer(region)]
    if not starts:
        return []
    ends = [m.end() for m in ENDFUNC_RE.finditer(region)]
    out: List[Tuple[int, int]] = []
    for i, s in enumerate(starts):
        nxt = starts[i + 1] if i + 1 < len(starts) else len(region)
        e = next((x for x in ends if s < x <= nxt), nxt)
        out.append((s, e))
    return out


def analyze_file(path: Path) -> List[Finding]:
    findings: List[Finding] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        findings.append(
            Finding(
                rule="read-error",
                severity="error",
                message=f"Could not read: {e}",
                file=str(path),
            )
        )
        return findings

    # ORGANIC #584 — scope declaration→index pairing PER MODULE (the old
    # per-FILE symbol table cross-matched same-name signals of different
    # widths across the multiple modules sv2v packs into one file).
    line_starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            line_starts.append(i + 1)

    def _lineno(pos: int) -> int:
        import bisect
        return bisect.bisect_right(line_starts, pos)

    for r_start, r_end, _mod in _module_regions(text):
        region = text[r_start:r_end]
        # ORGANIC #584 r2 — function/task bodies are nested scopes whose
        # locals (`reg [1:0] a;` inside an sv2v-inlined package function)
        # must not shadow the module-level declaration (`input wire [7:0]
        # a;`) for module-body index expressions. Build the module table
        # from decls OUTSIDE function bodies; per-function tables chain to
        # the module table (a Verilog function can read module signals).
        func_regions = _function_regions(region)

        def _scope_of(pos: int) -> int:
            for fi, (fs, fe) in enumerate(func_regions):
                if fs <= pos < fe:
                    return fi
            return -1

        widths: Dict[str, Tuple[int, int]] = {}  # module-level: name -> (hi, lo)
        func_widths: List[Dict[str, Tuple[int, int]]] = [
            {} for _ in func_regions]
        for m in REG_DECL_RE.finditer(region):
            hi, lo, name = int(m.group(1)), int(m.group(2)), m.group(3)
            fi = _scope_of(m.start())
            if fi >= 0:
                func_widths[fi][name] = (hi, lo)
            else:
                widths[name] = (hi, lo)

        # Scan this module's lines for out-of-range bit-selects
        for lm in BITSELECT_RE.finditer(region):
            abs_pos = r_start + lm.start()
            lineno = _lineno(abs_pos)
            line = text[line_starts[lineno - 1]:
                        line_starts[lineno] - 1 if lineno < len(line_starts)
                        else len(text)]
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("*"):
                continue
            name, sel_hi, sel_lo = (lm.group(1), int(lm.group(2)),
                                    int(lm.group(3)))
            fi = _scope_of(lm.start())
            if fi >= 0 and name in func_widths[fi]:
                decl = func_widths[fi][name]   # function-local shadows
            elif name in widths:
                decl = widths[name]
            else:
                continue
            decl_hi, decl_lo = decl
            # Both [hi:lo] ordering assumed LSB-first (lo < hi)
            decl_width = abs(decl_hi - decl_lo) + 1
            sel_width = abs(sel_hi - sel_lo) + 1
            if sel_hi > max(decl_hi, decl_lo) or sel_lo < min(decl_hi, decl_lo):
                findings.append(
                    Finding(
                        rule="bitselect-out-of-range",
                        severity="error",
                        message=(
                            f"Register {name!r} declared [{decl_hi}:{decl_lo}] "
                            f"({decl_width}-bit) but indexed as [{sel_hi}:{sel_lo}] "
                            f"({sel_width}-bit). Fix: widen declaration or use "
                            f"concatenation e.g. `{{{sel_width - decl_width}'b0, {name}}}`."
                        ),
                        file=str(path),
                        line=lineno,
                    )
                )

    return findings


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+", help="RTL file(s) or directory")
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args(argv)

    files: List[Path] = []
    for p in args.paths:
        pp = Path(p)
        if pp.is_dir():
            # Authored-RTL-source collection via the shared helper (an
            # explicit FILE argument is still honoured verbatim below).
            files.extend(rtl_source_files(pp))
        elif pp.is_file():
            files.append(pp)

    all_findings: List[Finding] = []
    for f in files:
        all_findings.extend(analyze_file(f))

    errors = [f for f in all_findings if f.severity == "error"]
    result = AuditResult(
        passed=(len(errors) == 0),
        findings=all_findings,
        stats={
            "files_scanned": len(files),
            "errors": len(errors),
            "warnings": len(all_findings) - len(errors),
        },
    )

    if args.json:
        print(result.to_json())
    else:
        for f in all_findings:
            loc = f"{f.file}:{f.line}" if f.line else f.file
            print(f"[{f.severity.upper()}] {f.rule}: {f.message} ({loc})")
        print(
            f"\nFiles: {result.stats['files_scanned']}  "
            f"Errors: {result.stats['errors']}  "
            f"Warnings: {result.stats['warnings']}  "
            f"Result: {'PASS' if result.passed else 'FAIL'}"
        )

    # Zero files scanned is not a clean project (#564). `passed` is true
    # because nothing contradicted the rule, and rc 0 is what the P0 umbrella
    # aggregates — so a path with no RTL under it would be certified as having
    # no bitwidth consistency defect.
    #
    # Measured over 40 tracked corpus projects before landing: every one
    # scanned at least 1 file (counts 1..2, tracking the project), so no real
    # project moves. rc 2 is "could not check", which the CI dispatcher
    # already separates from a finding.
    if result.stats.get("files_scanned", 0) == 0:
        print(f"VACUOUS_PASS: bitwidth_consistency_check examined nothing "
              f"(reason: 0 files scanned) — this is not a clean result",
              file=sys.stderr)
        return 2

    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
