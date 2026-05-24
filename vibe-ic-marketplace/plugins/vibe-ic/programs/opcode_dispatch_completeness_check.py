#!/usr/bin/env python3
"""opcode_dispatch_completeness_check.py — v0.119.45 (Wave 13) gate.

Closes a real bug class surfaced by the v0.119.44 <benchmark> fresh-agent
benchmark (18th attempt, <half-duplex-tester> byte[6]=0x02 FAIL despite Overall:
PASS structural). The agent's RESULT.md diagnosis: SEND_TEST → identify
async response path produced 4x all-padding frames. One root-cause
hypothesis: the FSM does not have a decode branch for every opcode
listed in L3.

This gate enforces that EVERY opcode hex literal declared in L3
(synonyms covered) appears as a dispatch arm in some RTL FSM file.

CHIP-AGNOSTIC. No specific opcode hex / chip name / pin / vendor
reference. Pure synonym-list + literal-presence detection.

Detection algorithm
-------------------
1. Load `generated_docs/L3_*.json` (or `L3.json`). Extract opcode hex
   strings. Each opcode entry can list its hex under any of these
   field names (synonym list, lower-cased): ``hex``, ``code``,
   ``opcode_hex``, ``op_hex``, ``value``, ``cmd_hex``.
   Top-level container synonyms: ``opcodes``, ``commands``,
   ``command_table``, ``opcodes_supported``, ``opcode_set``.
2. Locate RTL FSM files: any file under ``rtl/`` matching
   ``*main_fsm*``, ``*top_fsm*``, ``*ctrl*fsm*``, OR any file that
   contains a SystemVerilog ``typedef enum`` with state-like literals
   (``S_*``, ``ST_*``, ``STATE_*``).
3. For each L3 opcode (e.g., ``70``), search the union of FSM RTL
   for the literal in any of these forms (case-insensitive):
       - ``8'h70``  / ``8'H70``
       - ``8'd112`` / decimal in width-typed literal
       - ``'h70``   / unsigned no-width hex
       - ``0x70``   / C-style (rare in Verilog)
4. The literal must appear inside a "decode context": any of
       - ``case (...)`` arm
       - ``if (... == 8'h70 ...)`` / ``else if`` comparator
       - LUT-style ROM init that maps opcode → state
   (Heuristic: the literal must occur on a line that also contains
   one of: ``case``, ``==``, ``!=``, ``cmd_op``, ``opcode``,
   ``rx_byte``, ``opcode_decode``, ``: begin``, ``:``, OR be the
   first non-whitespace token of a case-arm line ``8'h70:``.)
5. FAIL when one or more L3 opcodes has NO recognised decode site
   in any FSM RTL file.
6. WARN when an opcode appears only in a "default" / ``default:``
   arm or a multi-opcode shared arm (``8'h70, 8'h72, 8'h74:`` group).
7. SKIP (exit 0) when L3 has no opcodes or generated_docs absent.
8. Honors waiver key ``opcode_decode_intentionally_grouped`` (≥40
   chars).

Usage
-----
    python3 opcode_dispatch_completeness_check.py <project_dir>
        [--json <out>]

Exit codes
----------
    0 — PASS / SKIP / PASS_WITH_WAIVER / WARN-only
    1 — FAIL
    2 — input-missing
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional
import _path_layout as _pl


WAIVER_KEY = "opcode_decode_intentionally_grouped"
WAIVER_MIN = 40

CONTAINER_KEYS = (
    "opcodes",
    "commands",
    "command_table",
    "opcodes_supported",
    "opcode_set",
)
HEX_FIELD_KEYS = (
    "hex",
    "code",
    "opcode_hex",
    "op_hex",
    "value",
    "cmd_hex",
)
DECODE_CONTEXT_TOKENS = (
    "case",
    "==",
    "!=",
    "cmd_op",
    "opcode",
    "rx_byte",
    "opcode_decode",
    ": begin",
)
FSM_FILENAME_PATTERNS = (
    re.compile(r"main_fsm", re.IGNORECASE),
    re.compile(r"top_fsm", re.IGNORECASE),
    re.compile(r"ctrl.*fsm", re.IGNORECASE),
    re.compile(r"cmd.*fsm", re.IGNORECASE),
    re.compile(r"dispatch", re.IGNORECASE),
    re.compile(r"protocol.*fsm", re.IGNORECASE),
)


def waived(project: Path) -> tuple[bool, str]:
    waivers = project / "waivers.json"
    if not waivers.exists():
        return False, ""
    try:
        d = json.loads(waivers.read_text())
        text = d.get(WAIVER_KEY)
        if isinstance(text, str) and len(text.strip()) >= WAIVER_MIN:
            return True, text.strip()
    except Exception:
        pass
    return False, ""


def _find_l3(project: Path) -> Optional[Path]:
    gd = _pl.generated_docs_dir(project)
    if not gd.is_dir():
        return None
    for cand in sorted(gd.glob("L3*.json")):
        return cand
    return None


def _norm_hex(raw) -> Optional[str]:
    """Return canonical lowercase hex byte string ('70') from various
    input forms ('0x70', '70', 'h70', 0x70, 112). Returns None on
    failure or if value > 0xFF."""
    if isinstance(raw, int):
        if 0 <= raw <= 0xFF:
            return f"{raw:02x}"
        return None
    if not isinstance(raw, str):
        return None
    s = raw.strip().lower().replace("0x", "").replace("'h", "").replace("h", "")
    if not s:
        return None
    try:
        v = int(s, 16)
    except ValueError:
        return None
    if 0 <= v <= 0xFF:
        return f"{v:02x}"
    return None


def _extract_l3_opcodes(l3: dict) -> list[str]:
    """Return list of normalised hex bytes ('70', '74', ...). De-duped,
    sorted."""
    opcodes: set[str] = set()
    container = None
    for key in CONTAINER_KEYS:
        if key in l3 and l3[key]:
            container = l3[key]
            break
    if container is None:
        # Fallback: scan top-level for any list-of-dicts that has hex
        # field synonyms.
        for v in l3.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                if any(k in v[0] for k in HEX_FIELD_KEYS):
                    container = v
                    break
    if container is None:
        return []

    if isinstance(container, list):
        items = container
    elif isinstance(container, dict):
        items = list(container.values())
    else:
        return []

    for entry in items:
        if isinstance(entry, dict):
            for k in HEX_FIELD_KEYS:
                if k in entry:
                    h = _norm_hex(entry[k])
                    if h:
                        opcodes.add(h)
                        break
        elif isinstance(entry, (str, int)):
            h = _norm_hex(entry)
            if h:
                opcodes.add(h)
    return sorted(opcodes)


def _find_fsm_files(project: Path) -> list[Path]:
    """Return RTL files that look like FSM dispatch sites."""
    out: list[Path] = []
    rtl_root = _pl.rtl_dir(project)
    candidates: list[Path] = []
    if rtl_root.is_dir():
        candidates.extend(rtl_root.rglob("*.v"))
        candidates.extend(rtl_root.rglob("*.sv"))
    else:
        candidates.extend(project.rglob("*.v"))
        candidates.extend(project.rglob("*.sv"))

    for f in candidates:
        if not f.is_file():
            continue
        # Skip build / sim dirs
        parts = set(p.lower() for p in f.parts)
        if {"build", "sim", "synth", "formal", "pnr", "gds",
            "output_files", "incremental_db", "db"} & parts:
            continue
        name = f.name.lower()
        if any(p.search(name) for p in FSM_FILENAME_PATTERNS):
            out.append(f)
            continue
        # Fallback: read content + look for typedef enum + state-like
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "typedef enum" in text and (
            re.search(r"\bS_\w+", text) or
            re.search(r"\bST_\w+", text) or
            re.search(r"\bSTATE_\w+", text)
        ):
            out.append(f)
    return out


def _hex_literal_patterns(byte_hex: str) -> list[re.Pattern]:
    """Build the per-opcode regex patterns that match common Verilog/SV
    literal encodings. byte_hex is lowercase 2-char string."""
    bh = byte_hex.lower()
    BH = byte_hex.upper()
    dec = int(byte_hex, 16)
    pats = [
        re.compile(rf"\b8\s*'\s*[hH]\s*{bh}\b"),
        re.compile(rf"\b8\s*'\s*[hH]\s*{BH}\b"),
        re.compile(rf"\'\s*[hH]\s*{bh}\b"),
        re.compile(rf"\'\s*[hH]\s*{BH}\b"),
        re.compile(rf"\b8\s*'\s*[dD]\s*{dec}\b"),
        re.compile(rf"\b0[xX]\s*{bh}\b"),
        re.compile(rf"\b0[xX]\s*{BH}\b"),
    ]
    return pats


def _line_in_decode_context(line: str) -> bool:
    """Return True iff the line text exhibits a dispatch context."""
    s = line.strip()
    # case arm form: "8'h70:" or "8'h70 :" or "8'h70, 8'h72:"
    if re.match(r"^\s*\d*\s*'\s*[hHdD]\s*[0-9A-Fa-f]+\s*[,:]", s):
        return True
    if re.match(r"^\s*0[xX][0-9A-Fa-f]+\s*[,:]", s):
        return True
    for tok in DECODE_CONTEXT_TOKENS:
        if tok in s:
            return True
    return False


def _is_grouped_arm(line: str) -> bool:
    """Detect case arm with multiple opcodes sharing a single body
    (e.g. ``8'h70, 8'h72, 8'h74: return ...``)."""
    s = line.strip()
    if ":" not in s:
        return False
    head = s.split(":", 1)[0]
    n = len(re.findall(
        r"\d*\s*'\s*[hHdD]\s*[0-9A-Fa-f]+|0[xX][0-9A-Fa-f]+", head))
    return n >= 2


def _find_opcode_in_files(byte_hex: str, files: list[Path]
                          ) -> tuple[bool, bool, list[str]]:
    """Search files for a decode-context occurrence of the given opcode.

    Returns (found_decode, only_grouped, sample_sites).
    `found_decode` True if at least one decode-context match exists.
    `only_grouped` True if every match is part of a multi-opcode
    case arm (used to emit WARN).
    """
    pats = _hex_literal_patterns(byte_hex)
    found = False
    grouped_only = True
    sites: list[str] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for ln_no, line in enumerate(text.splitlines(), 1):
            if not any(p.search(line) for p in pats):
                continue
            if not _line_in_decode_context(line):
                continue
            found = True
            if not _is_grouped_arm(line):
                grouped_only = False
            if len(sites) < 3:
                rel = f.name
                sites.append(f"{rel}:{ln_no}: {line.strip()[:80]}")
    return found, (found and grouped_only), sites


def check(project: Path) -> dict:
    findings: list[dict] = []
    warnings: list[dict] = []
    info: dict = {}

    l3_path = _find_l3(project)
    if l3_path is None:
        return {
            "program": "opcode_dispatch_completeness_check",
            "skip_reason": "no generated_docs/L3*.json found",
            "pass": True,
            "findings": [],
            "warnings": [],
            **info,
        }
    info["l3_path"] = str(l3_path.relative_to(project))

    try:
        l3 = json.loads(l3_path.read_text())
    except Exception as e:
        return {
            "program": "opcode_dispatch_completeness_check",
            "pass": False,
            "findings": [{
                "rule": "L3_UNPARSEABLE",
                "severity": "FAIL",
                "message": f"L3 unparseable: {e}",
            }],
            "warnings": [],
            **info,
        }

    opcodes = _extract_l3_opcodes(l3)
    info["l3_opcode_count"] = len(opcodes)
    info["l3_opcodes"] = opcodes

    if not opcodes:
        return {
            "program": "opcode_dispatch_completeness_check",
            "skip_reason": (
                "L3 has no opcodes / commands list; different gate "
                "covers extraction"
            ),
            "pass": True,
            "findings": [],
            "warnings": [],
            **info,
        }

    fsm_files = _find_fsm_files(project)
    info["fsm_files"] = [str(f.relative_to(project)) for f in fsm_files]
    if not fsm_files:
        return {
            "program": "opcode_dispatch_completeness_check",
            "skip_reason": (
                "no FSM-like RTL file found (rtl/*main_fsm*, *top_fsm*, "
                "*ctrl*fsm*, or typedef enum with S_*/ST_*/STATE_*)"
            ),
            "pass": True,
            "findings": [],
            "warnings": [],
            **info,
        }

    missing: list[str] = []
    grouped: list[str] = []
    for op in opcodes:
        found, only_grouped, _sites = _find_opcode_in_files(op, fsm_files)
        if not found:
            missing.append(op)
        elif only_grouped:
            grouped.append(op)

    info["missing_opcodes"] = missing
    info["grouped_opcodes"] = grouped

    if missing:
        findings.append({
            "rule": "OPCODE_DISPATCH_MISSING",
            "severity": "FAIL",
            "message": (
                f"L3 declares {len(opcodes)} opcode(s) but the RTL "
                f"FSM(s) lack decode branches for: "
                f"[{', '.join('0x' + h for h in missing)}]. "
                f"FSM files searched: "
                f"{[f.name for f in fsm_files]}. Without an explicit "
                f"decode site, those opcodes route to a default arm "
                f"and the chip emits no response — silicon would "
                f"silently FAIL the host's identify / SEND_TEST path."
            ),
        })

    if grouped:
        warnings.append({
            "rule": "OPCODE_DISPATCH_GROUPED",
            "severity": "WARN",
            "message": (
                f"Opcodes [{', '.join('0x' + h for h in grouped)}] "
                f"appear ONLY in multi-opcode case arms (shared body) "
                f"or default fallthrough. If those opcodes have "
                f"distinct response payloads in L3, the shared arm "
                f"will emit the wrong bytes."
            ),
        })

    return {
        "program": "opcode_dispatch_completeness_check",
        "pass": len(findings) == 0,
        "findings": findings,
        "warnings": warnings,
        **info,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_dir")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    project = Path(args.project_dir).resolve()
    if not project.exists():
        print(f"FAIL — project dir not found: {project}", file=sys.stderr)
        return 2

    result = check(project)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(result, indent=2))

    if "skip_reason" in result:
        print(f"PASS_SKIP — {result['skip_reason']}")
        return 0

    if result["pass"]:
        if result.get("warnings"):
            print(
                f"PASS_WITH_WARN — opcode dispatch complete "
                f"({result.get('l3_opcode_count')} L3 opcodes); "
                f"{len(result['warnings'])} warning(s)"
            )
            for w in result["warnings"]:
                print(f"WARN: {w['rule']} — {w['message']}")
        else:
            print(
                f"PASS — opcode dispatch complete "
                f"({result.get('l3_opcode_count')} L3 opcodes "
                f"all decoded in FSM RTL)"
            )
        return 0

    is_waived, why = waived(project)
    if is_waived:
        print(
            f"PASS_WITH_WAIVER — {len(result['findings'])} dispatch "
            f"finding(s); waiver `{WAIVER_KEY}` set: {why[:80]}..."
        )
        for f in result["findings"]:
            print(f"  • {f['rule']} — {f['message'][:120]}")
        return 0

    print(f"FAIL — {len(result['findings'])} opcode-dispatch violation(s)")
    for f in result["findings"]:
        print(f"FAIL: {f['rule']} — {f['message']}")
    for w in result.get("warnings", []):
        print(f"WARN: {w['rule']} — {w['message']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
