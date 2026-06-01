#!/usr/bin/env python3
"""
derived_clock_sdc_required_check.py — Verify any register-divided clock
in the RTL has a matching `create_generated_clock` entry in the SDC.

THE PROBLEM
-----------
RTL like::

    always @(posedge ext_clk) core_clk <= ~core_clk;

creates a divide-by-2 clock named `core_clk`. Without a corresponding
`create_generated_clock -divide_by 2 -source [get_ports ext_clk]
[get_pins core_clk_reg/Q]` in the SDC, STA reports zero-slack on every
path crossing into core_clk's domain (because there is no clock
declared on it), and OpenROAD CTS will not balance the divider's tree.

USAGE
-----
    python3 derived_clock_sdc_required_check.py rtl/ \\
        --sdc constraints/<benchmark>.sdc \\
        --json reports/gates/derived_clock_sdc.json

EXIT CODES
----------
    0 — every detected register-divided clock has a matching
        create_generated_clock entry.
    1 — at least one is missing.
    2 — IO / argument error.

HEURISTIC (RTL side)
--------------------
Detect both forms:

  Form A — combinational toggle:
      always @(posedge SRC_CLK) DIV_CLK <= ~DIV_CLK;
  Form B — counter divide:
      always @(posedge SRC_CLK)
        if (cnt == N-1) begin DIV_CLK <= ~DIV_CLK; cnt <= 0; end
        else cnt <= cnt + 1;

We capture (SRC_CLK, DIV_CLK) pairs and check the SDC.

HEURISTIC (SDC side)
--------------------
A `create_generated_clock` entry is acceptable if its name OR target
pin includes the DIV_CLK identifier. We scan the SDC text for
``create_generated_clock`` lines containing the divider name.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class Finding:
    severity: str
    rule: str
    file: str
    line: int
    message: str


def _strip_comments_v(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def _strip_comments_sdc(text: str) -> str:
    return re.sub(r"#[^\n]*", "", text)


def _autodiscover_sdc_text(target: Path) -> str:
    """When the check is invoked on a project directory with no explicit
    --sdc (as flow_compliance_check.py does — it passes only the project
    root), auto-discover every *.sdc under the project so a valid
    create_generated_clock emitted by sdc_gen.py is honoured.  Without
    this, the gate FALSE-FAILed any RTL with a register-divided clock even
    though the runner had already written a correct generated-clock SDC.
    Chip-AGNOSTIC: globs all *.sdc, concatenates their comment-stripped
    text. Returns "" if the target is a single file or no SDC exists.
    """
    if not target.is_dir():
        return ""
    parts: List[str] = []
    for sdc in sorted(target.rglob("*.sdc")):
        try:
            parts.append(_strip_comments_sdc(sdc.read_text(errors="replace")))
        except OSError:
            continue
    return "\n".join(parts)


def find_derived_clocks(rtl_text: str) -> List[Tuple[str, str, int]]:
    """Return list of (src_clk, div_clk, line_no) tuples."""
    out: List[Tuple[str, str, int]] = []
    # Match an `always @(posedge SRC)` block and look for `<DIV> <= ~<DIV>;`
    # inside (Form A or B).
    block_re = re.compile(
        r"always(?:_ff|_comb)?\s*@\s*\(\s*(?:posedge|negedge)\s+(\w+)[^)]*\)"
        r"\s*((?:begin|[^a])(?:.*?)(?:end\s*$|^[\s\S]{0,2000}?\Z))",
        re.MULTILINE | re.DOTALL,
    )
    for blk_m in re.finditer(
        r"always(?:_ff|_comb)?\s*@\s*\(\s*posedge\s+(\w+)[^)]*\)",
        rtl_text,
    ):
        src = blk_m.group(1)
        # Walk forward until we hit `endmodule` or another `always` block;
        # accept up to ~8000 chars.
        start = blk_m.end()
        # crude end: next `always` or `endmodule`
        end_m = re.search(r"\b(?:always(?:_ff|_comb)?|endmodule)\b",
                          rtl_text[start + 1:])
        end = start + 1 + end_m.start() if end_m else start + 8000
        body = rtl_text[start:end]

        for tog_m in re.finditer(
            r"(\w+)\s*<=\s*~\s*\1\s*;",
            body,
        ):
            div_name = tog_m.group(1)
            if div_name == src:
                continue
            ln = rtl_text.count("\n", 0, start + tog_m.start()) + 1
            out.append((src, div_name, ln))
    return out


def sdc_has_generated_clock(sdc_text: str, div_name: str) -> bool:
    for line in sdc_text.splitlines():
        if "create_generated_clock" in line and re.search(
            r"\b" + re.escape(div_name) + r"\b", line):
            return True
    return False


def _is_pdk_shim_file(path: Path, text: str) -> bool:
    """v1.6.228 — skip PDK std-cell shim files. These are auto-
    transformed PDK libraries (`udp_*` primitives turned into modules
    via pdk_udp_synth_shim_gen). Their `udp_jkff` / `udp_tff` toggle
    behaviour `out <= ~out` (under `if (j&&k)` guard) triggers a
    false-positive on the derived-clock check, which is meant for
    user RTL clock dividers like `divclk <= ~divclk` in always blocks.
    chip-AGNOSTIC.
    """
    name_markers = ("synth_shim", "_neg.v", "_neg.sv", "pdk_shim",
                     "yosys_flatten", "stdcell_lib", "_cells.v",
                     "/cells/", "_flat.v", "_flat_clean.v", "_flat_otpinit")
    s = str(path).replace("\\", "/")
    if any(m in s for m in name_markers):
        return True
    # Content-based: a PDK lib defines `udp_*` modules
    if re.search(r"^\s*module\s+udp_\w+", text, re.MULTILINE):
        return True
    return False


def audit(rtl_target: Path, sdc_path: Optional[Path]) -> List[Finding]:
    findings: List[Finding] = []
    if rtl_target.is_file():
        files = [rtl_target]
    else:
        files = sorted(list(rtl_target.rglob("*.v")) + list(rtl_target.rglob("*.sv")))
    if not files:
        findings.append(Finding(
            "WARN", "no_rtl_files", str(rtl_target), 0,
            f"no .v/.sv under {rtl_target}",
        ))
        return findings

    pairs: List[Tuple[str, str, str, int]] = []  # (src, div, file, line)
    for f in files:
        try:
            text = _strip_comments_v(f.read_text(errors="replace"))
        except OSError:
            continue
        # v1.6.228 — skip PDK std-cell shims and post-flatten netlists
        if _is_pdk_shim_file(f, text):
            continue
        for src, div, ln in find_derived_clocks(text):
            pairs.append((src, div, str(f), ln))

    if not pairs:
        findings.append(Finding(
            "INFO", "no_derived_clocks_found", str(rtl_target), 0,
            "no register-divided clocks detected; nothing to check.",
        ))
        return findings

    sdc_text = ""
    if sdc_path and sdc_path.exists():
        sdc_text = _strip_comments_sdc(sdc_path.read_text(errors="replace"))
    elif sdc_path is None:
        # No explicit --sdc: auto-discover under the project directory so
        # the gate works when invoked as `<check>.py <project>` (the
        # flow_compliance_check.py call shape).
        sdc_text = _autodiscover_sdc_text(rtl_target)

    for src, div, fpath, ln in pairs:
        if sdc_has_generated_clock(sdc_text, div):
            continue
        findings.append(Finding(
            severity="ERROR",
            rule="derived_clock_sdc_missing",
            file=fpath,
            line=ln,
            message=(
                f"register-divided clock {div!r} from {src!r} (line {ln}) "
                f"has no matching `create_generated_clock` entry in the "
                f"SDC. Add: `create_generated_clock -name {div} "
                f"-divide_by 2 -source [get_ports {src}] "
                f"[get_pins {div}_reg/Q]`."
            ),
        ))
    return findings


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else "")
    ap.add_argument("rtl", help="RTL file or directory")
    ap.add_argument("--sdc", help="SDC constraint file (optional but expected)")
    ap.add_argument("--json", nargs='?', const='-', default=None, metavar='PATH')
    args = ap.parse_args(argv)

    target = Path(args.rtl)
    if not target.exists():
        print(f"error: target not found: {target}", file=sys.stderr)
        return 2

    findings = audit(target, Path(args.sdc) if args.sdc else None)
    errors = [f for f in findings if f.severity == "ERROR"]

    report = {
        "target": str(target),
        "sdc": args.sdc,
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
    else:
        for f in findings:
            print(f"[{f.severity}] {f.rule} @ {f.file}:{f.line}: {f.message}")
        print(f"\n{len(errors)} error(s); verdict: {report['verdict']}")

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
