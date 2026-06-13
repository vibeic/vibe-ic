#!/usr/bin/env python3
"""
sv_compat_check.py — Check if Verilog files require the -sv flag for Yosys synthesis.

Scans RTL files for SystemVerilog constructs that Yosys cannot parse without
the `-sv` flag on `read_verilog`. This prevents the common failure mode where
Yosys silently misparses SV constructs in Verilog-2001 mode, producing wrong
netlists or cryptic errors.

Detected constructs:
  1. `logic` type in module ports or declarations
  2. `always_ff`, `always_comb`, `always_latch` keywords
  3. `unique case`, `priority case` keywords
  4. Local declarations inside always/initial blocks (integer/logic/reg/int
     declared inside a begin..end scope, not at module level)
  5. Interface / modport usage
  6. `typedef`, `enum`, `struct`, `union` keywords
  7. `import` package statements

Usage:
    python3 sv_compat_check.py --rtl-dir ./rtl/ --out-dir /tmp/check
    python3 sv_compat_check.py --rtl-dir ./rtl/ --out-dir /tmp/check --verbose

Exit codes:
    0 = Plain Verilog OK (no SV constructs found)
    1 = Needs -sv flag (SV constructs detected)
    2 = Usage / file error

Generality: works for ANY Verilog/SystemVerilog design. No IC-specific logic.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional


@dataclass
class SVConstruct:
    file: str
    line: int
    construct: str
    snippet: str


# ---------------------------------------------------------------------------
# v0.119.41 (Wave 9, gap #4) — unpacked-array port detection.
#
# Yosys 0.64 chokes on SystemVerilog unpacked-array ports such as
#     output logic [7:0] foo [0:3]
# even when invoked with -sv. The remedy is either to flatten to a packed
# array `[7:0][0:3] foo` (or `[0:3][7:0] foo`) or split into N scalar ports.
# This is checked at the MODULE PORT LIST level only — internal unpacked
# arrays inside the module body are fine for synthesis flows that use
# Yosys + custom techmaps.
# ---------------------------------------------------------------------------

# Match: optional direction + optional logic/wire/reg + packed dim(s)
# + ident + UNPACKED dim immediately before `,` or `)`.
# Generality: protocol-AGNOSTIC; this is a Verilog grammar pattern.
_PORT_TYPE_KEYWORDS = (
    "reg", "wire", "logic", "bit", "byte", "integer", "int",
    "signed", "unsigned",
)


def _looks_like_unpacked_port(token_seq: List[str]) -> bool:
    """Given a port-fragment split by whitespace, return True iff
    the fragment ends with `<ident> [...]` (one or more unpacked
    dimensions AFTER the identifier).

    Works on a fragment terminated by `,` or `)`.
    """
    if not token_seq:
        return False
    # Identify the bracket runs and identifiers.
    # Strategy: walk tokens; record the position of the last identifier
    # that is NOT a type keyword and NOT a bracket. Anything after that
    # which is bracketed counts as unpacked.
    last_ident_idx = -1
    for i, tok in enumerate(token_seq):
        if tok.startswith("["):
            continue
        if tok.lower() in _PORT_TYPE_KEYWORDS:
            continue
        if tok.lower() in ("input", "output", "inout"):
            continue
        if re.match(r"^\w+$", tok):
            last_ident_idx = i
    if last_ident_idx < 0:
        return False
    after = token_seq[last_ident_idx + 1:]
    return any(t.startswith("[") for t in after)


# Match: optional direction + free-form middle tokens + ident + UNPACKED dim
# immediately before `,` or `)`. The "free-form middle" is what makes it
# easier than a dense single-regex (which mis-binds when the optional
# type keyword is absent and the first bracket gets consumed as a packed
# dim before the ident).
_PORT_FRAGMENT_RE = re.compile(
    r"(?P<dir>\b(?:input|output|inout)\b)"
    r"(?P<body>[^,()]*?)"
    r"(?=,|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_TOKEN_RE = re.compile(r"\[[^\]]+\]|\w+")


def detect_unpacked_array_ports(filepath: Path) -> List[SVConstruct]:
    """Detect SystemVerilog unpacked-array ports on the module port list.

    Returns a SVConstruct entry per offending port. Internal unpacked
    arrays (declared inside the module body, NOT in the port list)
    are NOT reported — Yosys handles those via its own elaboration.
    """
    findings: List[SVConstruct] = []
    try:
        text = filepath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return findings
    fpath_str = str(filepath)

    no_block = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    no_line_comments = re.sub(r"//[^\n]*", "", no_block)
    for mod_m in re.finditer(
            r"\bmodule\s+\w+\s*(?:#\s*\([^)]*\)\s*)?\(",
            no_line_comments):
        depth = 1
        i = mod_m.end()
        port_text_start = i
        while i < len(no_line_comments) and depth > 0:
            ch = no_line_comments[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        port_text = no_line_comments[port_text_start:i]
        base_line = no_line_comments[:mod_m.start()].count("\n") + 1
        # Tokenise port_text by `,` (top-level only — matches our crude
        # extraction since the parameter list was already chewed by the
        # module header regex).
        for frag_m in _PORT_FRAGMENT_RE.finditer(port_text):
            frag = frag_m.group(0)
            tokens = _TOKEN_RE.findall(frag)
            if _looks_like_unpacked_port(tokens):
                line_off = port_text[:frag_m.start()].count("\n")
                findings.append(SVConstruct(
                    file=fpath_str,
                    line=base_line + line_off,
                    construct="unpacked_array_port_yosys_unfriendly",
                    snippet=frag.strip().replace("\n", " ")[:160],
                ))
    return findings


def waiver_present(rtl_dir: Path,
                   waiver_id: str,
                   *, min_chars: int = 40) -> bool:
    """Return True iff `<rtl_dir>` (or any ancestor up to project root)
    has a waivers.json with an entry whose id == `waiver_id` AND whose
    rationale is at least `min_chars` long. Generic, chip-AGNOSTIC."""
    here = rtl_dir.resolve()
    seen = set()
    candidates: List[Path] = []
    for d in (here, *here.parents):
        if d in seen:
            break
        seen.add(d)
        candidates.append(d / "waivers.json")
        if d.parent == d:
            break
    for cand in candidates:
        if not cand.is_file():
            continue
        try:
            data = json.loads(cand.read_text())
        except Exception:
            continue
        entries = data if isinstance(data, list) else (
            data.get("waivers") or data.get("waived_steps") or []
        )
        if not isinstance(entries, list):
            continue
        for e in entries:
            if not isinstance(e, dict):
                continue
            if e.get("id") == waiver_id:
                rat = e.get("rationale") or e.get("reason") or ""
                if isinstance(rat, str) and len(rat.strip()) >= min_chars:
                    return True
    return False


# ---------------------------------------------------------------------------
# Detection patterns
# ---------------------------------------------------------------------------

# Top-level patterns (can appear anywhere in the file)
_TOP_LEVEL_PATTERNS: List[tuple] = [
    # logic type: "logic", "logic [7:0]", "input logic", "output logic"
    (r'\blogic\b(?:\s*\[|\s+\w)', 'logic_type'),
    # always_ff / always_comb / always_latch
    (r'\balways_ff\b', 'always_ff'),
    (r'\balways_comb\b', 'always_comb'),
    (r'\balways_latch\b', 'always_latch'),
    # unique case / priority case
    (r'\bunique\s+case\b', 'unique_case'),
    (r'\bpriority\s+case\b', 'priority_case'),
    # interface / modport
    (r'^\s*interface\b', 'interface_decl'),
    (r'\bmodport\b', 'modport'),
    # typedef / enum / struct / union
    (r'\btypedef\b', 'typedef'),
    (r'\benum\b', 'enum'),
    (r'\bstruct\b', 'struct'),
    (r'\bunion\b', 'union'),
    # import statements (package imports)
    (r'\bimport\b\s+\w+\s*::', 'import_package'),
    # v0.76: iverilog 14.0 anti-patterns (surface alongside Yosys -sv warnings)
    # `package <name>;` declarations — iverilog 14.0 syntax errors on this even with -g2012
    (r'^\s*package\s+\w+\s*;', 'package_decl_iverilog_14'),
    # `parameter int unsigned X = ...;` — iverilog 14.0 doesn't accept type-qualified params
    (r'\bparameter\s+(?:int|integer|byte|shortint|longint|bit|logic)\s+(?:un)?signed\b', 'parameter_typed_iverilog_14'),
]

# Compiled top-level patterns
_COMPILED_TOP = [(re.compile(pat, re.IGNORECASE), name)
                 for pat, name in _TOP_LEVEL_PATTERNS]


def _is_comment_line(line: str) -> bool:
    """Check if the line is a single-line comment."""
    stripped = line.strip()
    return stripped.startswith('//') or stripped.startswith('/*')


def _detect_local_declarations(lines: List[str], filepath: str) -> List[SVConstruct]:
    """Detect local variable declarations inside always/initial blocks.

    In Verilog-2001, variable declarations must be at module scope. Declaring
    `integer i;` or `reg [7:0] temp;` inside an always/initial block is a
    SystemVerilog feature that requires -sv.
    """
    findings: List[SVConstruct] = []
    in_block = False
    block_depth = 0
    # Track module-level vs block-level scope
    module_depth = 0

    local_decl_re = re.compile(
        r'^\s*(integer|int|logic|reg|wire|bit|byte|shortint|longint|real|'
        r'time|realtime|string)\b\s+\w+',
        re.IGNORECASE
    )
    block_start_re = re.compile(r'\b(always|always_ff|always_comb|always_latch|initial)\b')
    begin_re = re.compile(r'\bbegin\b')
    end_re = re.compile(r'\bend\b')

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if _is_comment_line(stripped):
            continue

        # Track entry into always/initial blocks
        if block_start_re.search(stripped):
            in_block = True
            # The begin may be on the same line
            if begin_re.search(stripped):
                block_depth += 1
            continue

        if in_block:
            # Count begin/end nesting
            begins = len(begin_re.findall(stripped))
            ends = len(end_re.findall(stripped))
            block_depth += begins - ends

            if block_depth <= 0:
                in_block = False
                block_depth = 0
                continue

            # Inside a block — check for local declarations
            if local_decl_re.match(stripped):
                # Distinguish: `integer` inside always block is SV-only
                # `reg` at module level is fine, but `reg` inside begin..end
                # after always is also fine in Verilog-2001 for some tools.
                # Focus on `integer`, `int`, `logic`, `bit`, `byte`, etc.
                match = local_decl_re.match(stripped)
                decl_type = match.group(1).lower()
                # In strict Verilog-2001, only `reg` and `integer` are legal
                # inside named blocks. `logic`, `int`, `bit`, etc. always need -sv.
                if decl_type in ('logic', 'int', 'bit', 'byte', 'shortint',
                                 'longint', 'real', 'string'):
                    findings.append(SVConstruct(
                        file=filepath,
                        line=i,
                        construct=f'local_{decl_type}_in_block',
                        snippet=stripped[:120]
                    ))

    return findings


def scan_file(filepath: Path) -> List[SVConstruct]:
    """Scan a single Verilog file for SystemVerilog constructs."""
    try:
        text = filepath.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return []

    lines = text.splitlines()
    findings: List[SVConstruct] = []
    fpath_str = str(filepath)

    # Remove block comments for pattern matching
    # (but keep line numbers by replacing comment content with spaces)
    in_block_comment = False
    clean_lines = []
    for line in lines:
        clean = line
        if in_block_comment:
            end_idx = clean.find('*/')
            if end_idx >= 0:
                clean = ' ' * (end_idx + 2) + clean[end_idx + 2:]
                in_block_comment = False
            else:
                clean = ''
        # Remove inline block comments
        while '/*' in clean:
            start = clean.find('/*')
            end = clean.find('*/', start + 2)
            if end >= 0:
                clean = clean[:start] + ' ' * (end + 2 - start) + clean[end + 2:]
            else:
                clean = clean[:start]
                in_block_comment = True
                break
        # Remove single-line comments
        comment_idx = clean.find('//')
        if comment_idx >= 0:
            clean = clean[:comment_idx]
        clean_lines.append(clean)

    # Top-level pattern matching
    for i, clean in enumerate(clean_lines, 1):
        if not clean.strip():
            continue
        for regex, construct_name in _COMPILED_TOP:
            if regex.search(clean):
                findings.append(SVConstruct(
                    file=fpath_str,
                    line=i,
                    construct=construct_name,
                    snippet=clean.strip()[:120]
                ))

    # Local declaration detection (uses original lines for context)
    findings.extend(_detect_local_declarations(clean_lines, fpath_str))

    return findings


def scan_directory(rtl_dir: Path) -> List[SVConstruct]:
    """Scan all .v and .sv files in a directory tree."""
    all_findings: List[SVConstruct] = []
    patterns = ['**/*.v', '**/*.sv']
    files_found = set()
    for pat in patterns:
        for f in rtl_dir.glob(pat):
            if f not in files_found:
                files_found.add(f)
                all_findings.extend(scan_file(f))
                # v0.119.41 Wave 9 — module-port-level unpacked array
                # detection. Reported alongside other SV constructs but
                # surfaced separately in build_report() so the caller
                # can fail the flow specifically on port-level hits.
                all_findings.extend(detect_unpacked_array_ports(f))
    return all_findings


def build_report(findings: List[SVConstruct]) -> dict:
    """Build the JSON report from findings."""
    needs_sv = len(findings) > 0
    unpacked_port_hits = [
        f for f in findings
        if f.construct == "unpacked_array_port_yosys_unfriendly"
    ]
    return {
        'needs_sv': needs_sv,
        'sv_constructs_found': [asdict(f) for f in findings],
        'recommendation': 'Use read_verilog -sv' if needs_sv else 'Plain Verilog OK',
        'total_constructs': len(findings),
        # v0.119.41 Wave 9: separate counter for the Yosys-fatal subset.
        'unpacked_array_port_hits': [asdict(f) for f in unpacked_port_hits],
        'unpacked_array_port_count': len(unpacked_port_hits),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description='Check if Verilog files require -sv flag for Yosys synthesis')
    parser.add_argument('--rtl-dir', required=True,
                        help='Directory containing Verilog files')
    parser.add_argument('--out-dir', required=True,
                        help='Output directory for report JSON')
    parser.add_argument('--verbose', action='store_true',
                        help='Print findings to stdout')
    args = parser.parse_args(argv)

    rtl_dir = Path(args.rtl_dir)
    out_dir = Path(args.out_dir)

    if not rtl_dir.is_dir():
        print(f"ERROR: RTL directory does not exist: {rtl_dir}", file=sys.stderr)
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)

    findings = scan_directory(rtl_dir)
    report = build_report(findings)

    report_path = out_dir / 'sv_compat_report.json'
    report_path.write_text(json.dumps(report, indent=2))

    if args.verbose:
        for f in findings:
            print(f"  {f.file}:{f.line}  [{f.construct}]  {f.snippet}")

    # v0.119.41 Wave 9 — port-level unpacked-array hits are a hard FAIL
    # (Yosys 0.64 chokes even with -sv). Honors waiver
    # `yosys_unpacked_port_acceptable` (≥40 chars).
    waived = waiver_present(rtl_dir, "yosys_unpacked_port_acceptable")
    if report['unpacked_array_port_count'] > 0 and not waived:
        print(f"FAIL_UNPACKED_PORTS: {report['unpacked_array_port_count']} "
              "unpacked-array port(s) on module port lists — Yosys 0.64 "
              "chokes on these even with -sv. Flatten to a packed array "
              "(e.g. `[0:3][7:0] foo`) or split into N scalar ports. "
              "(Waiver: id=`yosys_unpacked_port_acceptable`, ≥40 chars "
              "rationale.)")
        for f in report['unpacked_array_port_hits']:
            print(f"  {f['file']}:{f['line']}  {f['snippet']}")
        return 1
    if waived and report['unpacked_array_port_count'] > 0:
        print(f"WAIVED_UNPACKED_PORTS: {report['unpacked_array_port_count']} "
              "unpacked-array port(s) waived via "
              "`yosys_unpacked_port_acceptable`.")

    if report['needs_sv']:
        print(f"NEEDS_SV: {report['total_constructs']} SystemVerilog construct(s) found. "
              f"Use read_verilog -sv in Yosys.")
        return 1
    else:
        print("PLAIN_VERILOG_OK: No SystemVerilog constructs detected.")
        return 0


if __name__ == '__main__':
    sys.exit(main())
