#!/usr/bin/env python3
"""
fpga_async_input_synchronizer_check.py — Verify every external input/inout
on the FPGA top routes through ≥ 2 sequential FFs before reaching clocked
logic.

THE PROBLEM
-----------
On the vendor run, the FPGA top received `KEY_n` and `ID_BUS_PIN` directly
into edge-triggered logic without 2-FF synchronisers. Metastability in the
core FSM produced sporadic glitches that the sim never modelled.

`fpga_pullup_lint` checks the QSF declares pull-ups; `cdc-check` covers
inter-clock crossings. Neither covers the simpler "first-stage sync flop"
case for a single-clock FPGA.

INPUTS
------
- An RTL file or directory.
- ``--top <module>`` — the FPGA top module name (defaults to whichever
  module's port list looks like an FPGA top: external pins like CLK_50M,
  KEY*, LED*, etc.). If the QSF is given, the entity declared by
  ``set_global_assignment -name TOP_LEVEL_ENTITY`` is used.

USAGE
-----
    python3 fpga_async_input_synchronizer_check.py rtl/ --top fpga_top
    python3 fpga_async_input_synchronizer_check.py rtl/ \\
        --qsf fpga/<benchmark>.qsf --json reports/gates/sync.json

EXIT CODES
----------
    0 — every external `input`/`inout` declared in the FPGA top routes
        through ≥ 2 FF stages before its first non-flop reference.
    1 — at least one input has fewer than 2 FF stages.
    2 — IO / argument error.

HEURISTIC
---------
For each input port `<x>` of the top module:
  Find every assignment of the form
      `<sync1>` <= `<x>` (or registered to <x>);
      `<sync2>` <= `<sync1>`;
  If we find that chain of length ≥ 2, the input is synchronised.

"FF" is detected by either:
  - `always @(posedge <clk>) <reg> <= <expr containing input>;`
  - `always_ff @(posedge <clk>) <reg> <= ...;`
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _audit_receipt import emit_receipt  # noqa: E402


@dataclass
class Finding:
    severity: str
    rule: str
    file: str
    line: int
    message: str


def _read(p: Path) -> str:
    try:
        return p.read_text(errors="replace")
    except OSError:
        return ""


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def _resolve_top(qsf: Optional[Path], top_arg: Optional[str]) -> Optional[str]:
    if top_arg:
        return top_arg
    if qsf and qsf.exists():
        for line in qsf.read_text(errors="replace").splitlines():
            m = re.search(r"set_global_assignment\s+-name\s+TOP_LEVEL_ENTITY\s+(\w+)",
                          line, re.IGNORECASE)
            if m:
                return m.group(1)
    return None


def _find_module_text(text: str, module_name: str) -> str:
    m = re.search(r"\bmodule\s+" + re.escape(module_name) + r"\b", text)
    if not m:
        return ""
    end = re.search(r"\bendmodule\b", text[m.start():])
    return text[m.start():m.start() + end.end()] if end else text[m.start():]


def _extract_inputs(module_text: str) -> List[str]:
    """Parse `input ...` and `inout ...` port declarations.

    Strategy: find every position of `input`/`inout` keyword, then walk
    forward until the next `,`, `;`, `)`, or another port-direction
    keyword. The text in between is one declaration spanning one or more
    comma-separated names (after stripping bit ranges and type
    modifiers).
    """
    inputs: Set[str] = set()
    KW = {"wire", "reg", "logic", "signed", "unsigned"}

    starts = [m.end() for m in re.finditer(r"\b(?:input|inout)\b", module_text)]
    for s in starts:
        # Walk to next stop token
        # Stops: ; ) ` newline+input/output/inout/endmodule`
        tail = module_text[s:]
        stop_m = re.search(
            r"[;)]|\b(?:input|output|inout|endmodule|reg|wire|always|assign|initial)\b",
            tail,
        )
        if stop_m:
            chunk = tail[:stop_m.start()]
        else:
            chunk = tail
        # Sometimes the very next token IS a type keyword (wire/reg/logic).
        # We allow it as a leading modifier but stop on a later one.
        # Strip leading whitespace + leading type keyword.
        chunk = chunk.strip()
        chunk = re.sub(r"^(?:wire|reg|logic|signed|unsigned)\s+", "", chunk)
        # Strip leading bit range
        chunk = re.sub(r"^\s*\[[^\]]*\]\s*", "", chunk)
        for piece in chunk.split(","):
            piece = piece.strip()
            if not piece:
                continue
            piece = re.sub(r"\[[^\]]*\]", "", piece).strip()
            parts = re.findall(r"[A-Za-z_]\w*", piece)
            names = [p for p in parts if p not in KW]
            if names:
                inputs.add(names[-1])
    return sorted(inputs)


def _ff_chain_length(module_text: str, signal: str) -> int:
    """Approximate length of the sync-FF chain originating at `signal`.

    Walks one hop at a time:  signal → reg1 → reg2 → ...
    Each hop is a `<reg> <= <prev>;` statement inside an `always_ff` /
    `always @(posedge ...)` block (very roughly: any non-blocking
    assignment whose RHS is exactly the previous name).
    """
    # collect every (lhs, rhs) non-blocking pair in the module
    pairs: List[tuple[str, str, int]] = []
    for m in re.finditer(
        r"\b(\w+)\s*<=\s*([\w\d]+)\s*;",
        module_text,
    ):
        ln = module_text.count("\n", 0, m.start()) + 1
        pairs.append((m.group(1), m.group(2), ln))

    # Walk
    chain = [signal]
    visited: Set[str] = set([signal])
    while True:
        # Find pair where rhs == chain[-1]
        nxt = None
        for lhs, rhs, _ in pairs:
            if rhs == chain[-1] and lhs not in visited:
                nxt = lhs
                break
        if nxt is None:
            break
        chain.append(nxt)
        visited.add(nxt)
    return max(0, len(chain) - 1)  # number of FF stages = len - 1


def rtl_files(rtl_target: Path) -> List[Path]:
    """The files this audit reads, in one place.

    Extracted for #2050 so `main()` can state in the receipt HOW MANY files
    were examined without re-deriving the rule and drifting from it. A verdict
    over zero files is not a clean design; it is an audit of nothing, and the
    receipt has to be able to say which of the two happened.
    """
    if rtl_target.is_file():
        return [rtl_target]
    return sorted(list(rtl_target.rglob("*.v")) + list(rtl_target.rglob("*.sv")))


def audit(rtl_target: Path, top_module: str) -> List[Finding]:
    findings: List[Finding] = []
    files = rtl_files(rtl_target)
    if not files:
        findings.append(Finding(
            "WARN", "no_rtl_files", str(rtl_target), 0,
            f"no .v/.sv under {rtl_target}",
        ))
        return findings

    found_top = False
    for f in files:
        text = _strip_comments(_read(f))
        if not re.search(r"\bmodule\s+" + re.escape(top_module) + r"\b", text):
            continue
        found_top = True
        module_text = _find_module_text(text, top_module)
        inputs = _extract_inputs(module_text)
        for sig in inputs:
            # Skip clock pins (CLK*, *_CLK, CLOCK*)
            if re.match(r"(?i)(?:.*CLK.*|CLOCK.*|CLOCK_50)", sig):
                continue
            # Skip resets — they go through dedicated reset synchroniser
            # (different gate covers reset paths).
            if re.match(r"(?i)(?:RESET|RST_N|RESET_N|RST)$", sig):
                continue
            depth = _ff_chain_length(module_text, sig)
            if depth < 2:
                findings.append(Finding(
                    severity="ERROR",
                    rule="missing_async_synchroniser",
                    file=str(f),
                    line=0,
                    message=(
                        f"FPGA top input {sig!r} reaches clocked logic "
                        f"through only {depth} FF stage(s); ≥ 2 are "
                        f"required for metastability protection. Add "
                        f"`reg [1:0] {sig.lower()}_sync; always @(posedge "
                        f"clk) {sig.lower()}_sync <= {{{sig.lower()}_sync"
                        f"[0], {sig}}};`."
                    ),
                ))
        break
    if not found_top:
        findings.append(Finding(
            "ERROR", "top_module_not_found", str(rtl_target), 0,
            f"module {top_module!r} not found in {rtl_target}.",
        ))
    return findings


WAIVER_KEY = "fpga_async_input_synchronizer_intentional"


def _waived(project_dir: Optional[Path]) -> bool:
    if project_dir is None:
        return False
    w = project_dir / "waivers.json"
    if not w.exists():
        return False
    try:
        d = json.loads(w.read_text())
    except Exception:
        return False
    v = d.get(WAIVER_KEY, "")
    if isinstance(v, dict):
        v = v.get("reason", "") or v.get("justification", "")
    return isinstance(v, str) and len(v.strip()) >= 40


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else "")
    ap.add_argument("rtl", help="RTL file or directory")
    ap.add_argument("--top", default=None, help="FPGA top module name")
    ap.add_argument("--qsf", default=None,
                    help="Quartus .qsf file (TOP_LEVEL_ENTITY auto-extract)")
    ap.add_argument("--project", default=None,
                    help="Project root (for waivers.json lookup)")
    ap.add_argument("--json", nargs='?', const='-', default=None, metavar='PATH')
    args = ap.parse_args(argv)

    top = _resolve_top(Path(args.qsf) if args.qsf else None, args.top)
    if not top:
        print("error: top module not resolved (give --top or --qsf)", file=sys.stderr)
        return 2

    target = Path(args.rtl)
    if not target.exists():
        print(f"error: target not found: {target}", file=sys.stderr)
        return 2

    findings = audit(target, top)
    errors = [f for f in findings if f.severity == "ERROR"]

    project_dir = Path(args.project).resolve() if args.project else None
    if errors and _waived(project_dir):
        print(f"PASS_WITH_WAIVER — {WAIVER_KEY} accepted")
        for f in findings:
            print(f"[{f.severity}] {f.rule} @ {f.file}:{f.line}: {f.message}")
        return 0

    report = {
        "target": str(target),
        "top": top,
        "errors": len(errors),
        "findings": [asdict(f) for f in findings],
        "verdict": "PASS" if not errors else "FAIL",
    }

    if args.json:
        _txt = json.dumps(report, indent=2)
        if args.json == '-':
            print(_txt)
        else:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(_txt + "\n")
            # #2050 — producer-written receipt (programs/_audit_receipt.py).
            # Only on a real path: `--json -` is a print to stdout, which has
            # no directory a sibling receipt could live beside.
            _files = rtl_files(target)
            emit_receipt(
                'fpga_async_input_synchronizer_check', args.json,
                report["verdict"], len(_files), _files,
                extra={'top': top, 'errors': report["errors"]})
    else:
        for f in findings:
            print(f"[{f.severity}] {f.rule} @ {f.file}:{f.line}: {f.message}")
        print(f"\n{len(errors)} error(s); verdict: {report['verdict']}")

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
