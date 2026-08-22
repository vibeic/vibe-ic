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

# Kimi-scale fix — this gate audits AUTHORED RTL SOURCE. The *.v/*.sv
# collection routes through the shared collector (canonical phase2/stage1/rtl
# preferred; generated netlist/sim/verify outputs + >8MB files excluded on
# fallback) so a 342 MB emitted netlist can never enter the comment strip /
# divider scan again (see _specrtl_common.rtl_source_files for the full scale
# rationale). The SDC side is deliberately UNTOUCHED: --sdc file-or-dir reads
# and the project-wide *.sdc auto-discovery are legitimate non-RTL inputs.
try:
    from _specrtl_common import rtl_source_files
except ImportError:                      # packaged relative import
    from ._specrtl_common import rtl_source_files


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


def _read_sdc_arg(sdc_path: Path) -> str:
    """ORGANIC #572 — accept either a single SDC FILE or a DIRECTORY of
    *.sdc for --sdc (the flow yaml passes `--sdc phase2/stage2/constraints`,
    a directory; the old `read_text()` raised IsADirectoryError and the
    step could only be waived). Mirrors the rtl argument's file-or-dir
    semantics. Returns the comment-stripped concatenation; "" when nothing
    is found."""
    if sdc_path is None or not sdc_path.exists():
        return ""
    if sdc_path.is_dir():
        parts: List[str] = []
        for sdc in sorted(sdc_path.rglob("*.sdc")):
            try:
                parts.append(_strip_comments_sdc(
                    sdc.read_text(errors="replace")))
            except OSError:
                continue
        return "\n".join(parts)
    try:
        return _strip_comments_sdc(sdc_path.read_text(errors="replace"))
    except OSError:
        return ""


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


def find_clock_consumers(rtl_text: str) -> Set[str]:
    """ORGANIC #569 — return the set of identifiers that are actually USED
    as a clock: a sequential sensitivity-list edge (`@(posedge X)` /
    `@(negedge X)`) OR a clock-pin connection on an instance
    (`.clk(X)`, `.clock(X)`, `.CLK(X)`, `.clk_i(X)`...). A register that
    merely toggles (`phase_q <= ~phase_q`) but whose net clocks NOTHING is
    a shadow/phase bit, NOT a derived clock, and must not be forced to
    carry a create_generated_clock. chip-AGNOSTIC: pure Verilog grammar."""
    consumers: Set[str] = set()
    for m in re.finditer(r"@\s*\(\s*(?:posedge|negedge)\s+(\w+)", rtl_text):
        consumers.add(m.group(1))
    # clock-pin connections: .<clkpin>(<ident>) where the pin name looks
    # like a clock (clk / clock, with optional _i/_in/_p suffix or prefix).
    for m in re.finditer(
            r"\.\s*(\w*cl(?:k|ock)\w*)\s*\(\s*(\w+)\s*\)", rtl_text,
            re.IGNORECASE):
        consumers.add(m.group(2))
    return consumers


def find_output_ports(rtl_text: str) -> Set[str]:
    """ORGANIC #569 — identifiers declared as output / inout ports. A
    divided net that LEAVES the module as an output may be consumed as a
    clock externally, so it is NOT exempted from the create_generated_clock
    requirement even when no in-design consumer is visible (conservative —
    avoids a no-leak hole for exported derived clocks).

    Adversarial-review hardening: capture ALL identifiers in a
    comma-separated output list (`output logic [1:0] x, y;` → x AND y) and
    tolerate an initializer (`output wire core_clk = 0;`)."""
    ports: Set[str] = set()
    # match the whole declaration body up to the terminating ; , or )
    for m in re.finditer(
            r"\b(?:output|inout)\b\s*(?:reg|wire|logic|var)?\s*"
            r"(?:signed\s*)?(?:\[[^\]]*\]\s*)?(?P<body>[^;)]*?)\s*[;)]",
            rtl_text):
        body = m.group("body")
        # split a comma-separated list; each part may carry a leading
        # direction/type keyword (ANSI lists repeat `output reg ...`),
        # a width bracket, and a trailing `= <init>`.
        for part in body.split(","):
            ident = part.strip().split("=")[0].strip()
            # strip leading direction/type/sign keywords and width brackets
            prev = None
            while ident != prev:
                prev = ident
                ident = re.sub(
                    r"^(?:output|inout|input|reg|wire|logic|var|signed|"
                    r"unsigned)\b\s*", "", ident).strip()
                ident = re.sub(r"^\[[^\]]*\]\s*", "", ident).strip()
            # take the first bare identifier token
            mm = re.match(r"([A-Za-z_]\w*)", ident)
            if mm:
                ports.add(mm.group(1))
    return ports


def find_instance_pin_nets(rtl_text: str) -> Set[str]:
    """ORGANIC #569 (adversarial-review hardening) — nets connected to ANY
    instance pin `.<pin>(<net>)`. A toggle net fed into an instance pin may
    be clocking that instance through a non-`clk`-named pin (`.ck`, `.phi`,
    `.c`...), so a divided net connected to any pin is treated as POTENTIALLY
    consumed and is NOT exempted (conservative — closes the non-clk-pin
    leak). chip-AGNOSTIC."""
    nets: Set[str] = set()
    for m in re.finditer(r"\.\s*\w+\s*\(\s*([A-Za-z_]\w*)\s*\)", rtl_text):
        nets.add(m.group(1))
    return nets


def find_assign_aliases(rtl_text: str):
    """ORGANIC #569 (adversarial-review hardening) — map net → set of nets it
    is aliased TO via `assign alias = net;`. Used so a consumer of an ALIAS
    of a divided clock counts as a consumer of the divided clock itself
    (`assign gated = div; always @(posedge gated)` no longer leaks)."""
    aliases: dict = {}
    for m in re.finditer(
            r"\bassign\s+([A-Za-z_]\w*)\s*=\s*([A-Za-z_]\w*)\s*;", rtl_text):
        alias, src = m.group(1), m.group(2)
        aliases.setdefault(src, set()).add(alias)
    return aliases


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
        # Kimi-scale fix: shared authored-RTL collector (*.v/*.sv).
        files = rtl_source_files(rtl_target)
    if not files:
        findings.append(Finding(
            "WARN", "no_rtl_files", str(rtl_target), 0,
            f"no .v/.sv under {rtl_target}",
        ))
        return findings

    pairs: List[Tuple[str, str, str, int]] = []  # (src, div, file, line)
    clock_consumers: Set[str] = set()
    output_ports: Set[str] = set()
    instance_pin_nets: Set[str] = set()
    assign_aliases: Dict[str, Set[str]] = {}
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
        # ORGANIC #569 — accumulate the corpus-wide clock-consumer set so a
        # toggle whose net clocks nothing is not forced to carry an SDC.
        clock_consumers |= find_clock_consumers(text)
        output_ports |= find_output_ports(text)
        instance_pin_nets |= find_instance_pin_nets(text)
        for k, v in find_assign_aliases(text).items():
            assign_aliases.setdefault(k, set()).update(v)

    def _is_consumed(div: str) -> bool:
        # direct clock use, exported as a port, fed to ANY instance pin, or a
        # downstream alias of div that is GENUINELY consumed (transitive,
        # depth-bounded). Conservative for the direct net: any of these → NOT
        # a shadow bit.
        if (div in clock_consumers or div in output_ports
                or div in instance_pin_nets):
            return True
        # ORGANIC #658 — the alias frontier must NOT count a downstream net
        # that is *merely re-exported* as an output port. The #569 alias walk
        # treated ANY `assign <out> = <toggle>` (out an output port) as a clock
        # consumer, conservatively assuming an exported toggle could be an
        # external clock — but a 1-bit DATA/status flag exported via
        # `assign phase = phase_q;` with NO `posedge phase` / clock-pin
        # consumer anywhere is never used as a clock, so it must keep the #569
        # `derived_clock_no_consumer` INFO classification (not a false ERROR).
        # An aliased net counts ONLY when it is GENUINELY consumed as a clock
        # (`posedge/negedge <alias>` or a clock-named pin) or fed to ANY
        # instance pin (a real structural connection). KEEP no-leak: if the
        # exported net IS actually used as a clock edge somewhere, it lands in
        # `clock_consumers` and still gates (real exported derived clock → SDC
        # required → ERROR). The DIRECT-export path above is unchanged: a net
        # that is ITSELF the output port (`output reg core_clk; core_clk<=~`)
        # stays conservatively gated.
        seen = set()
        frontier = list(assign_aliases.get(div, ()))
        while frontier:
            a = frontier.pop()
            if a in seen:
                continue
            seen.add(a)
            if a in clock_consumers or a in instance_pin_nets:
                return True
            frontier.extend(assign_aliases.get(a, ()))
        return False

    if not pairs:
        findings.append(Finding(
            "INFO", "no_derived_clocks_found", str(rtl_target), 0,
            "no register-divided clocks detected; nothing to check.",
        ))
        return findings

    sdc_text = _read_sdc_arg(sdc_path) if sdc_path is not None else \
        _autodiscover_sdc_text(rtl_target)

    for src, div, fpath, ln in pairs:
        # ORGANIC #569 — clock-usage confirmation: a divided net is a
        # shadow/phase bit (not a derived clock) ONLY when it is genuinely
        # NOT consumed (_is_consumed covers direct posedge/clk-pin use, any
        # instance-pin connection, an output/inout export, or a downstream
        # assign-alias of any of those). Internal toggle that clocks nothing
        # → INFO, never FAIL. Anything consumed → still gated (no-leak).
        if not _is_consumed(div):
            findings.append(Finding(
                "INFO", "derived_clock_no_consumer", fpath, ln,
                f"toggle net {div!r} (from {src!r}, line {ln}) is not used "
                f"as a clock by any sequential block or clock pin — treated "
                f"as a shadow/phase register, no create_generated_clock "
                f"required."))
            continue
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
