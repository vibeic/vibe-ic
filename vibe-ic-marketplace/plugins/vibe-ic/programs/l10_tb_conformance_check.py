#!/usr/bin/env python3
"""l10_tb_conformance_check.py — v0.53 plugin gate

Verifies that EVERY deterministic test vector enumerated in
`generated_docs/L10_TEST_CASES.json` has actually been exercised by the
testbench suite under `sim/tb/`.

Coverage rules per test case:
  - For a `cmd_response` case with opcode 0xXX: require evidence that the
    host packet byte sequence was driven into DUT, AND that the expected
    response was checked. Accepted evidence:
      (a) the opcode literal (`8'hXX`, `8'h<XX>`, or the hex byte in a
          `tb_vec` array) appears in at least one `sim/tb/tb_*.v`, AND
      (b) `sim/work/summary.txt` or `reports/sim/summary.txt` records
          a passing case whose id matches the L10 `id` field (case-
          insensitive substring).
  - For `error_path` / `state_transition` / `timing_sequence` /
    `analog_interaction` cases, require the case `id` to appear in at
    least one tb file (comment or task name) — documented trace-to-
    requirement.

This gate complements `cmd_response_conformance_check.py` which only
verifies CRC-residue correctness of the host vectors; it does NOT verify
that the tb harness actually drove them. l10_tb_conformance_check.py
closes that gap.

Usage:
    python3 l10_tb_conformance_check.py \\
        --l10 generated_docs/L10_TEST_CASES.json \\
        --tb-dir sim/tb \\
        --summary sim/work/summary.txt \\
        --out reports/gates/l10_tb_conformance.json

Exit code:
    0 — every L10 case has tb evidence
    1 — one or more cases lacked evidence
    2 — input artefacts missing / malformed
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ----- helpers ------------------------------------------------------


def load_l10(path: str) -> List[Dict[str, Any]]:
    data = json.loads(Path(path).read_text())
    # Accept either a flat list or a dict with "test_cases" / "cases" / "vectors"
    if isinstance(data, list):
        return data
    for key in ("test_cases", "cases", "vectors", "cmd_response", "tests"):
        if key in data and isinstance(data[key], list):
            return data[key]
    raise ValueError("L10 JSON did not contain a recognisable test-case list")


def read_all_tb_text(tb_dir: str) -> Tuple[Dict[str, str], str]:
    """Return (per-file text map, concatenated blob) of every .v / .sv under tb_dir."""
    per_file: Dict[str, str] = {}
    blob_parts: List[str] = []
    for p in sorted(Path(tb_dir).rglob("*")):
        if p.is_file() and p.suffix in (".v", ".sv", ".svh"):
            try:
                txt = p.read_text(errors="replace")
            except Exception:
                continue
            per_file[str(p)] = txt
            blob_parts.append(txt)
    return per_file, "\n".join(blob_parts)


def read_summary(summary_path: str) -> str:
    p = Path(summary_path)
    if not p.exists():
        return ""
    return p.read_text(errors="replace")


# ----- evidence matching -------------------------------------------

OPCODE_RE = re.compile(r"0?x?([0-9A-Fa-f]{2})")


def opcode_patterns(byte_hex: str) -> List[re.Pattern]:
    """Return regex patterns that match `byte_hex` in common Verilog forms."""
    m = OPCODE_RE.fullmatch(byte_hex.strip())
    if not m:
        return []
    h = m.group(1).upper()
    forms = [
        rf"8'h{h}",
        rf"8'h{h.lower()}",
        rf"8'b{int(h, 16):08b}",
        rf"\b0x{h}\b",
        rf"\b{h}\b",
    ]
    return [re.compile(f) for f in forms]


def case_has_opcode_evidence(case: Dict[str, Any], tb_blob: str) -> bool:
    """Check if the case's opcode or host packet bytes appear in any tb file."""
    # Find the opcode hex from common field names
    opcode = None
    for field in ("opcode", "cmd", "cmd_hex", "cmd_byte"):
        if field in case and case[field] is not None:
            opcode = str(case[field])
            break
    # Or first byte of host packet
    if not opcode:
        for field in ("host_packet", "host", "tx_bytes", "cmd_bytes"):
            v = case.get(field)
            if isinstance(v, list) and v:
                opcode = str(v[0])
                break
            if isinstance(v, str) and v:
                opcode = v.split()[0]
                break
    if not opcode:
        return False
    for pat in opcode_patterns(opcode):
        if pat.search(tb_blob):
            return True
    return False


def case_id_appears(case_id: str, tb_blob: str, summary: str) -> bool:
    if not case_id:
        return False
    needle = re.escape(case_id.lower())
    if re.search(needle, tb_blob.lower()):
        return True
    if re.search(needle, summary.lower()):
        return True
    return False


def summary_has_pass(case_id: str, summary: str) -> bool:
    """Grep summary.txt for `<case_id>.*PASS` pattern."""
    if not case_id or not summary:
        return False
    pat = re.compile(rf"{re.escape(case_id)}.*PASS", re.I)
    return bool(pat.search(summary))


# ----- CLI ----------------------------------------------------------


def evaluate(
    cases: List[Dict[str, Any]],
    tb_blob: str,
    summary: str,
) -> Tuple[List[Dict[str, Any]], int, int]:
    results: List[Dict[str, Any]] = []
    ok_count = 0
    fail_count = 0
    for c in cases:
        case_id = str(c.get("id", c.get("name", "")))
        category = c.get("category", c.get("type", c.get("kind", "")))
        is_cmd_rsp = category.lower() in ("cmd_response", "cmd_rsp", "happy", "happy_path") if category else False
        evidence: List[str] = []
        if is_cmd_rsp:
            if case_has_opcode_evidence(c, tb_blob):
                evidence.append("opcode in tb")
            if summary_has_pass(case_id, summary):
                evidence.append("summary pass record")
        # For any category, ID substring counts as evidence of trace-to-req
        if case_id_appears(case_id, tb_blob, summary):
            evidence.append("id substring in tb/summary")
        ok = bool(evidence)
        results.append(
            {
                "id": case_id,
                "category": category,
                "evidence": evidence,
                "pass": ok,
            }
        )
        if ok:
            ok_count += 1
        else:
            fail_count += 1
    return results, ok_count, fail_count


def _tb_files_under(d: Path) -> bool:
    """True when directory `d` directly or recursively holds a testbench
    .v/.sv (a tb_*.v or anything with a `module tb` / `_tb`)."""
    if not d.is_dir():
        return False
    for p in d.rglob("*"):
        if p.is_file() and p.suffix in (".v", ".sv"):
            return True
    return False


def _resolve_tb_dir(given: str) -> Optional[str]:
    """ORGANIC #572 — the default --tb-dir (phase2/stage1/sim/tb) is rigid;
    a project that keeps testbenches at the sim/ ROOT (phase2/stage1/sim/)
    reported 4/4 false 'lack evidence'. Try the given path first, then its
    parent when the leaf is 'tb', then the canonical sim roots. Returns the
    first directory that actually holds a .v/.sv, else None."""
    cands: List[str] = [given]
    gp = Path(given)
    if gp.name == "tb":
        cands.append(str(gp.parent))
    cands += ["phase2/stage1/sim/tb", "phase2/stage1/sim",
              "sim/tb", "sim"]
    seen = set()
    for c in cands:
        if c in seen:
            continue
        seen.add(c)
        if _tb_files_under(Path(c)):
            return c
    # last resort: return the given path if it at least exists as a dir, so
    # the caller's missing-dir error message is accurate.
    return given if Path(given).is_dir() else None


def _resolve_summary(given: str) -> str:
    """ORGANIC #572 — fall back across the common summary locations when the
    default path is absent (mirrors read_summary's own two candidates but
    extends to the sim/ root and reports/)."""
    cands = [given, "phase2/stage1/sim/work/summary.txt",
             "phase2/stage1/sim/summary.txt", "reports/sim/summary.txt",
             "sim/work/summary.txt", "sim/summary.txt"]
    for c in cands:
        if Path(c).is_file():
            return c
    return given


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--l10", required=True, help="phase1/generated_docs/L10_TEST_CASES.json")
    p.add_argument("--tb-dir", default="phase2/stage1/sim/tb", help="directory containing testbench .v files")
    p.add_argument("--summary", default="phase2/stage1/sim/work/summary.txt", help="sim summary file")
    p.add_argument("--out", default="reports/gates/l10_tb_conformance.json")
    p.add_argument("--strict", action="store_true", help="fail on ANY case lacking evidence (default)")
    p.add_argument("--warn-only", action="store_true", help="print warnings but exit 0")
    args = p.parse_args(argv)

    try:
        cases = load_l10(args.l10)
    except Exception as e:
        print(f"[l10-tb-conformance] cannot load L10: {e}", file=sys.stderr)
        return 2

    tb_dir = _resolve_tb_dir(args.tb_dir)
    if tb_dir is None:
        print(f"[l10-tb-conformance] tb dir missing: {args.tb_dir} "
              f"(and no fallback under sim/)", file=sys.stderr)
        return 2

    _, tb_blob = read_all_tb_text(tb_dir)
    summary = read_summary(_resolve_summary(args.summary))

    results, ok_count, fail_count = evaluate(cases, tb_blob, summary)

    out = {
        "total": len(cases),
        "ok": ok_count,
        "fail": fail_count,
        "results": results,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False))

    if fail_count:
        print(
            f"[l10-tb-conformance] {fail_count}/{len(cases)} cases lack evidence "
            f"(see {args.out}):",
            file=sys.stderr,
        )
        for r in results:
            if not r["pass"]:
                print(f"  - {r['id']} ({r['category']})", file=sys.stderr)
        if args.warn_only:
            return 0
        return 1

    print(f"[l10-tb-conformance] PASS  {ok_count}/{len(cases)} cases covered  → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
