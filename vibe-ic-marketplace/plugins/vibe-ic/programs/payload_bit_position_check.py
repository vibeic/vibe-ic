#!/usr/bin/env python3
"""
payload_bit_position_check.py — Cross-reference spec doc bit-layout
statements with RTL bit-indexing to catch payload-bit misreads.

THE PROBLEM
-----------
On the vendor run, the spec said "byte1 bit3 = RD5K, bit7 = OUT1" but the
agent's RTL stored RD5K at bit 6 and PT at bit 3. Lint, formal, and CRC
all PASS — the bug is purely positional, the gate has to be told what
the canonical positions are.

INPUTS
------
A bit-position spec — one of:
  a. ``--bitmap <bitmap.json>`` ::
        {
          "byte1": {
            "bit7": "OUT1",
            "bit3": "RD5K"
          }
        }
     (Optionally with module-name + signal-name hints.)

  b. Embedded in L3_CMD_PROTOCOL.json or L4_REGMAP.json under
     ``bit_layouts``.

USAGE
-----
    python3 payload_bit_position_check.py rtl/ \\
        --bitmap generated_docs/spec_bitmap.json \\
        --module dispatcher
    python3 payload_bit_position_check.py rtl/ \\
        --layer-l3 generated_docs/L3_CMD_PROTOCOL.json \\
        --json reports/gates/bitmap.json

EXIT CODES
----------
    0 — every spec bit position is referenced at the matching RTL bit
        index.
    1 — at least one mismatch.
    2 — IO / argument error.

HEURISTIC
---------
For each (signal, bit_index) declared in the spec, scan the RTL for
occurrences and verify each occurrence indexes the same bit:

   spec: byte1 bit3 = RD5K
   RTL: assign rd5k = byte1[3];   ✓ PASS
   RTL: assign rd5k = byte1[6];   ✗ FAIL ("RD5K is at bit 6 in RTL but
                                          spec says bit 3")
   RTL: rd5k_q <= payload_byte1[3];  ✓ PASS

The check is name-sensitive: the spec signal name must appear in RTL
adjacent to a [N] index. Rename mismatches surface as
"spec_signal_not_found" and don't fail by default (use
``--strict-name`` to upgrade them to errors).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _source_record_merge import merge_source_records  # noqa: E402


@dataclass
class Finding:
    severity: str
    rule: str
    file: str
    line: int
    message: str


def _load_bitmap_from_layer(path: Path) -> Dict[str, Dict[str, str]]:
    try:
        d = json.loads(path.read_text())
    except Exception:
        return {}
    # Look at top-level "bit_layouts", then "byte" / "field_map" subkeys.
    layouts = d.get("bit_layouts") if isinstance(d, dict) else None
    if isinstance(layouts, dict):
        return layouts
    return {}


def parse_bitmap(bitmap_arg: Optional[str],
                 l3_path: Optional[Path],
                 l4_path: Optional[Path]) -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}
    if bitmap_arg:
        try:
            out.update(json.loads(Path(bitmap_arg).read_text()))
        except Exception as e:
            raise SystemExit(2) from e
    # L3 and L4 are PEER sources -- neither is an override of the other -- so a
    # byte both of them name must not be resolved by which one this loop reads
    # last. `_load_bitmap_from_layer` returns `{byte: {}}` for a byte declared
    # with no bit rows, and `audit()` then extracts zero (signal, bit) pairs for
    # it: that byte's positions are simply never checked, and with other bytes
    # still populated the `empty_bitmap` WARN does not fire either. Silent
    # under-check, decided by argument order.
    merged, _conflicts = merge_source_records(
        (_load_bitmap_from_layer(p) for p in (l3_path, l4_path)
         if p and p.exists()),
        on_conflict="richer")
    for byte_name, bits in merged.items():
        # Layer-over-`--bitmap` precedence is UNCHANGED: a layer that DESCRIBES
        # the byte still wins, exactly as before. Only a layer that merely NAMES
        # it no longer does. Narrowing this to the empty case is deliberate --
        # whether an explicit `--bitmap` should outrank a layer doc is a real
        # question, and it is not this rule's to answer.
        if bits or byte_name not in out:
            out[byte_name] = bits
    return out


def _extract_bit_index(bit_name: str) -> Optional[int]:
    m = re.match(r"bit\s*[_-]?(\d+)", bit_name, re.IGNORECASE)
    if m:
        return int(m.group(1))
    if bit_name.isdigit():
        return int(bit_name)
    return None


def audit(rtl_target: Path, bitmap: Dict[str, Dict[str, str]],
          module_filter: Optional[str] = None,
          strict_name: bool = False) -> List[Finding]:
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

    # Build (sig_name, expected_bit) pairs.
    expected: List[Tuple[str, int]] = []
    for byte_name, bits in bitmap.items():
        if not isinstance(bits, dict):
            continue
        for bit_label, sig_name in bits.items():
            idx = _extract_bit_index(bit_label)
            if idx is not None and isinstance(sig_name, str) and sig_name.strip():
                expected.append((sig_name.strip(), idx))

    if not expected:
        findings.append(Finding(
            "WARN", "empty_bitmap", "(none)", 0,
            "no signal/bit pairs extracted from --bitmap or layer files; "
            "nothing to check",
        ))
        return findings

    sigs_seen: Dict[str, List[Tuple[str, int, int]]] = {sig: [] for sig, _ in expected}
    # Per-line: find any "<signal>... [N]" pattern. Allow underscores
    # and dots between signal and the index (e.g. payload_byte1[3] or
    # payload.byte1[3]).
    for f in files:
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        # Optional module filter
        if module_filter:
            mtext = ""
            for m in re.finditer(r"module\s+(\w+)", text):
                if m.group(1) == module_filter:
                    start = m.start()
                    end_m = re.search(r"\bendmodule\b", text[start:])
                    end = start + end_m.end() if end_m else len(text)
                    mtext = text[start:end]
                    break
            scan = mtext
        else:
            scan = text
        scan = re.sub(r"//[^\n]*", "", scan)
        scan = re.sub(r"/\*.*?\*/", "", scan, flags=re.DOTALL)

        # Split scan into statements at `;`.
        statements: List[Tuple[int, str]] = []  # (line_no_start, text)
        cur_text = ""
        cur_line = 1
        for ch in scan:
            cur_text += ch
            if ch == ";":
                statements.append((cur_line, cur_text))
                cur_line += cur_text.count("\n")
                cur_text = ""
        if cur_text.strip():
            statements.append((cur_line, cur_text))

        bit_idx_re = re.compile(r"\b\w+\s*\[\s*(\d+)\s*\]")

        for sig, exp_bit in expected:
            sig_re = re.compile(r"\b" + re.escape(sig) + r"\w*\b", re.IGNORECASE)
            for line_start, stmt in statements:
                if not sig_re.search(stmt):
                    continue
                # Find any [N] index inside this statement only
                bit_match = bit_idx_re.search(stmt)
                if bit_match is None:
                    continue
                got_bit = int(bit_match.group(1))
                # Resolve approximate line of signal occurrence
                sig_pos = sig_re.search(stmt).start()
                line_no = line_start + stmt[:sig_pos].count("\n")
                sigs_seen[sig].append((str(f), line_no, got_bit))

    for sig, exp_bit in expected:
        hits = sigs_seen[sig]
        if not hits:
            findings.append(Finding(
                "ERROR" if strict_name else "WARN",
                "spec_signal_not_found",
                "(none)", 0,
                f"signal {sig!r} (spec bit {exp_bit}) not found in RTL — "
                f"either renamed in implementation or missing entirely.",
            ))
            continue
        for fpath, ln, got in hits:
            if got != exp_bit:
                findings.append(Finding(
                    "ERROR", "bit_position_mismatch",
                    fpath, ln,
                    f"{sig!r} indexed at bit {got} in RTL but spec declares "
                    f"bit {exp_bit}.",
                ))
    return findings


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else "")
    ap.add_argument("rtl", help="RTL file or directory")
    ap.add_argument("--bitmap", help="JSON: {byte: {bit_n: signal_name}}")
    ap.add_argument("--layer-l3", default=None)
    ap.add_argument("--layer-l4", default=None)
    ap.add_argument("--module", default=None,
                    help="Restrict scan to a single module name")
    ap.add_argument("--strict-name", action="store_true",
                    help="Treat spec_signal_not_found as ERROR (default WARN)")
    ap.add_argument("--json", nargs='?', const='-', default=None, metavar='PATH')
    args = ap.parse_args(argv)

    try:
        bitmap = parse_bitmap(
            args.bitmap,
            Path(args.layer_l3) if args.layer_l3 else None,
            Path(args.layer_l4) if args.layer_l4 else None,
        )
    except SystemExit:
        print("error: cannot parse bitmap", file=sys.stderr)
        return 2

    if not bitmap:
        print("error: empty bitmap (give --bitmap or --layer-l3/--layer-l4)",
              file=sys.stderr)
        return 2

    target = Path(args.rtl)
    if not target.exists():
        print(f"error: target not found: {target}", file=sys.stderr)
        return 2

    findings = audit(target, bitmap, args.module, args.strict_name)
    errors = [f for f in findings if f.severity == "ERROR"]

    report = {
        "target": str(target),
        "module_filter": args.module,
        "checked_pairs": sum(len(v) for v in bitmap.values() if isinstance(v, dict)),
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
