#!/usr/bin/env python3
"""
tristate_self_rx_mask_check.py — Self-RX masking audit for tristate/open-drain
tristate bus pins.

Rule (derived from v052 rtl/pad_ctrl.v:8):

    When a module drives an inout/tri bus pin ``W`` through an output-enable
    ``W_oe`` companion, the module (or downstream hookup) MUST present a
    masked-RX tap of the form

        assign W_rx_msk = W_oe ? 1'b1 : W_rx;   // or equivalent ternary

    so the RX chain doesn't sample the local drive as an external symbol.

Static check (IC-agnostic):

  1. Scan every ``.v``/``.sv`` file for ``inout`` ports. For each inout port
     name ``W``, look for the triple ``(W, W_oe, W_<tap>)`` across the whole
     RTL set, where ``<tap>`` is one of ``rx``, ``in``, ``din``, ``sample``.
  2. FAIL when all three exist AND every assignment whose LHS matches
     ``W_<tap>`` (or ``W_<tap>_msk``/``W_<tap>_m``) has a direct RHS of
     ``W`` with NO ``W_oe ?`` ternary guard anywhere in the rtl set that
     does carry that guard.

Edge cases:
  * No inout ports found → exit 0 ("no inout ports, nothing to check").
  * Inout present but no ``<W>_oe`` signal → not a driven bus, skip.
  * Masked version present anywhere (``W_oe ? 1'b1 : W_tap``) → PASS.

Outputs:
  * Human-readable findings on stdout.
  * Optional machine-readable ``--json`` report.

Exit codes:
  * 0 = PASS (no findings, or out of scope)
  * 1 = at least one FAIL finding
  * 2 = argument / IO error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Dict, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    severity: str           # ERROR, WARNING, INFO
    category: str           # MISSING_MASK, RAW_TAP_ASSIGN
    message: str
    file: str = ""
    line: int = 0
    signal: str = ""
    details: str = ""


# ---------------------------------------------------------------------------
# Regexes (compiled once)
# ---------------------------------------------------------------------------
_INOUT_RE = re.compile(
    r"\binout\s+(?:wire|reg|logic|tri|tri0|tri1)?\s*(?:\[[^\]]+\]\s*)?([A-Za-z_]\w*)",
    re.IGNORECASE,
)
_IDENT_RE = re.compile(r"\b[A-Za-z_]\w*\b")

# Suffixes we consider as "RX tap" variants.
_TAP_SUFFIXES: Tuple[str, ...] = ("rx", "in", "din", "sample")


def _find_v_files(rtl_dir: Path) -> List[Path]:
    return sorted(
        [p for p in rtl_dir.rglob("*") if p.is_file()
         and p.suffix.lower() in (".v", ".sv", ".vh")]
    )


def _collect_inout_names(texts: Dict[Path, str]) -> List[str]:
    """Collect every identifier declared as an inout in any scanned file."""
    names: List[str] = []
    for t in texts.values():
        for m in _INOUT_RE.finditer(t):
            nm = m.group(1)
            if nm and nm not in names:
                names.append(nm)
    return names


def _has_oe_signal(name: str, texts: Dict[Path, str]) -> bool:
    # An oe signal is any identifier that exactly matches f"{name}_oe"
    # (case-sensitive — Verilog identifiers are case-sensitive).
    pat = re.compile(r"\b" + re.escape(name) + r"_oe\b")
    for t in texts.values():
        if pat.search(t):
            return True
    return False


def _find_tap_assignments(
    name: str, texts: Dict[Path, str]
) -> List[Tuple[Path, int, str, str, str]]:
    """
    Return list of (file, line_no, lhs, rhs, raw_line) for every
    ``assign <lhs> = <rhs>;`` where lhs matches ``name_<suffix>``
    (optionally followed by ``_msk`` / ``_m``).
    """
    suffix_alt = "|".join(_TAP_SUFFIXES)
    lhs_re = re.compile(
        r"^\s*assign\s+(" + re.escape(name) + r"_(" + suffix_alt + r")(?:_msk|_m)?)\s*=\s*(.+?)\s*;",
        re.IGNORECASE,
    )
    out: List[Tuple[Path, int, str, str, str]] = []
    for path, text in texts.items():
        for i, line in enumerate(text.splitlines(), start=1):
            m = lhs_re.match(line)
            if m:
                out.append((path, i, m.group(1), m.group(3), line.rstrip()))
    return out


def _rhs_has_oe_mask(rhs: str, name: str) -> bool:
    """RHS references ``<name>_oe`` and a ternary ``?``."""
    oe_tok = name + "_oe"
    return ("?" in rhs) and (oe_tok in rhs)


def audit(rtl_dir: Path) -> Tuple[List[Finding], Dict]:
    findings: List[Finding] = []

    if not rtl_dir.exists() or not rtl_dir.is_dir():
        findings.append(Finding(
            severity="ERROR",
            category="IO",
            message=f"RTL directory not found: {rtl_dir}",
        ))
        return findings, {"inouts": [], "checked": 0, "skipped": 0}

    v_files = _find_v_files(rtl_dir)
    texts: Dict[Path, str] = {p: p.read_text(errors="replace") for p in v_files}

    inout_names = _collect_inout_names(texts)
    summary = {"inouts": inout_names, "checked": 0, "skipped": 0}

    if not inout_names:
        return findings, summary   # out-of-scope → PASS

    for w in inout_names:
        if not _has_oe_signal(w, texts):
            summary["skipped"] += 1
            continue  # no companion OE → not a driven bus, skip
        summary["checked"] += 1

        taps = _find_tap_assignments(w, texts)
        if not taps:
            # No explicit tap assignment in RTL body; downstream may read the
            # pad directly. We don't have enough info to flag — skip.
            continue

        # Any masked-form present anywhere?  If yes, the design HAS the
        # pattern; we still flag individual raw taps because they may
        # shadow the masked one.
        any_masked = any(_rhs_has_oe_mask(rhs, w) for _, _, _, rhs, _ in taps)

        for path, lno, lhs, rhs, raw in taps:
            if _rhs_has_oe_mask(rhs, w):
                continue
            # RHS is "raw <w>" or something else. Only flag the classic
            # pitfall: `assign W_rx = W;` — i.e. RHS is bare <w>
            # (possibly with whitespace only).
            rhs_ident = rhs.strip().rstrip(";").strip()
            if rhs_ident == w:
                findings.append(Finding(
                    severity="ERROR",
                    category="RAW_TAP_ASSIGN",
                    message=(
                        f"Tap '{lhs}' is assigned directly from inout "
                        f"'{w}' with no '{w}_oe ? 1'b1 : ...' guard "
                        f"(self-RX may sample our own drive)."
                    ),
                    file=str(path),
                    line=lno,
                    signal=lhs,
                    details=raw.strip(),
                ))
            elif not any_masked:
                # RHS is some expression, no masked form exists anywhere.
                # Could still be fine, but warn for manual review.
                findings.append(Finding(
                    severity="WARNING",
                    category="MISSING_MASK",
                    message=(
                        f"Tap '{lhs}' assignment does not include "
                        f"'{w}_oe ?' guard and no masked form was "
                        f"found in the RTL set."
                    ),
                    file=str(path),
                    line=lno,
                    signal=lhs,
                    details=raw.strip(),
                ))

    return findings, summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_report(findings: List[Finding], rtl_dir: Path, summary: Dict) -> Dict:
    return {
        "program": "tristate_self_rx_mask_check",
        "version": "1.0.0",
        "rtl_dir": str(rtl_dir),
        "summary": {
            "inout_ports": summary.get("inouts", []),
            "checked": summary.get("checked", 0),
            "skipped": summary.get("skipped", 0),
            "findings_count": len(findings),
            "pass": not any(f.severity == "ERROR" for f in findings),
        },
        "findings": [asdict(f) for f in findings],
    }


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Flag tristate-bus modules whose RX tap is not masked by "
            "the companion output-enable signal."
        )
    )
    parser.add_argument("--rtl-dir", required=True,
                        help="Directory containing .v / .sv RTL files")
    parser.add_argument("--json", dest="json_out", default=None,
                        help="Optional path to write machine-readable report")
    args = parser.parse_args(argv)

    rtl_dir = Path(args.rtl_dir)
    try:
        findings, summary = audit(rtl_dir)
    except OSError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    report = build_report(findings, rtl_dir, summary)
    report_json = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(report_json)

    print(report_json)

    # IO errors (missing RTL dir etc.) → exit 2 per the vibe-ic-d contract
    # (0 PASS / 1 FAIL / 2 input-missing).
    if any(getattr(f, "category", "") == "IO" for f in findings):
        return 2
    # "no inout ports found" is a hard PASS (not a fail).
    if not summary.get("inouts"):
        return 0
    return 0 if report["summary"]["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
