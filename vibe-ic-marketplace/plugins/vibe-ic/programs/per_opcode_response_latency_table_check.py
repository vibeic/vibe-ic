#!/usr/bin/env python3
"""
per_opcode_response_latency_table_check.py — gate (LL-33) catching
extractor failures on per-opcode response latency tables.

Why this gate exists
====================
v0.119.30 <benchmark> vendor benchmark (MIN_DIFF_ANALYSIS.md). The vendor
doc `input/docs/20230103-3.txt` lines 8-25 give:

    RSP_70[91]  RSP_74[91]  RSP_78[91]  RSP_7C[91]
    RSP_80[91]  RSP_84[91]  ...
    RSP_E0[15917]            ← long latency for ID-list cmd

These tick values are the per-opcode response latencies the silicon-
PASS reference FPGA uses. Fresh agent emitted L11_OTP_CONTENT.json
without a `response_latency_ticks` dict; downstream RTL had ad-hoc /
constant latency for every command, so the master saw the wrong byte
arrival window for E0 (3.1 ms vs single-byte typical) → silent FAIL.

Rule
----
Trigger condition: any input/docs/ file contains regex
`RSP_[0-9A-Fa-f]+\\s*\\[\\s*\\d+\\s*\\]` at least 3 times. (At least
3 to avoid false alerts on a single sample mention.)

When triggered:
1. Extract the table → dict {opcode_hex_lower: ticks}.
2. Look in L11_OTP_CONTENT.json (or L11.5 / L8 fallback) for either:
   • `response_latency_ticks: {"0x70": 91, ...}`, or
   • `command_table[*].response_latency_ticks: N` per-entry, or
   • Any nested dict whose keys match `0x[0-9a-fA-F]{2}` and whose
     values are integers.
3. If neither found, FAIL with the doc table cited.
4. If found, verify at least 75% of the doc opcodes appear in L11.
   If <75% overlap, FAIL.

Honors waivers.json key `rsp_latency_table_extracted_elsewhere`
(≥20 chars) — for projects where latency lives in a dedicated L8
section, etc.

Usage
-----
python3 per_opcode_response_latency_table_check.py <project_dir>

Returns 0 on PASS / silent-skip / waived, 1 on FAIL.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
import _path_layout as _pl


RSP_PAT = re.compile(
    r"\bRSP_([0-9A-Fa-f]{1,4})\s*\[\s*(\d+)\s*\]",
)
HEX_KEY_PAT = re.compile(r"^0[xX][0-9A-Fa-f]{1,4}$")


def find_input_docs(project: Path) -> list[Path]:
    base = project / "input" / "docs"
    if not base.is_dir():
        return []
    out: list[Path] = []
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() in {
            ".txt", ".md", ".csv", ".tsv", ".log", ".json",
            ".yaml", ".yml", "",
        }:
            out.append(p)
    return out


def extract_doc_table(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for m in RSP_PAT.finditer(text):
        opcode = m.group(1).lower()
        try:
            out[f"0x{opcode}"] = int(m.group(2))
        except ValueError:
            pass
    return out


def find_l_doc(project: Path) -> list[Path]:
    out: list[Path] = []
    for stem in (
        "L11_OTP_CONTENT.json",
        "L11_5_RSP_LATENCY.json",
        "L8_RTL_CONSTANTS.json",
        "L8_TIMING_WAVEFORM.json",
        "L3_PROTOCOL.json",
    ):
        for base in (_pl.generated_docs_dir(project), project / "docs",
                     project):
            p = base / stem
            if p.is_file():
                out.append(p)
    return out


def collect_l_table(node, found: dict[str, int]) -> None:
    if isinstance(node, dict):
        # canonical key
        for k, v in node.items():
            if k.lower() == "response_latency_ticks" and isinstance(v, dict):
                for ck, cv in v.items():
                    if isinstance(cv, (int, float)) and \
                       (HEX_KEY_PAT.match(str(ck))
                        or re.match(r"^[0-9A-Fa-f]{1,4}$", str(ck))):
                        norm = (str(ck).lower() if str(ck).startswith(
                            ("0x", "0X")) else f"0x{str(ck).lower()}")
                        found[norm] = int(cv)
                continue
            # per-entry shape: command_table list
            if k.lower() in ("command_table", "commands") and \
               isinstance(v, list):
                for entry in v:
                    if not isinstance(entry, dict):
                        continue
                    op = (entry.get("opcode") or entry.get("cmd")
                          or entry.get("code"))
                    lat = (entry.get("response_latency_ticks")
                           or entry.get("latency_ticks"))
                    if op is None or lat is None:
                        continue
                    if isinstance(lat, (int, float)):
                        op_str = str(op).lower()
                        if not op_str.startswith("0x"):
                            op_str = f"0x{op_str}"
                        found[op_str] = int(lat)
            # nested generic dict with hex keys
            if isinstance(v, dict):
                hex_kids = {ck: cv for ck, cv in v.items()
                            if HEX_KEY_PAT.match(str(ck))
                            and isinstance(cv, (int, float))}
                if len(hex_kids) >= 2:
                    for ck, cv in hex_kids.items():
                        found[str(ck).lower()] = int(cv)
                collect_l_table(v, found)
            elif isinstance(v, list):
                for item in v:
                    collect_l_table(item, found)
    elif isinstance(node, list):
        for item in node:
            collect_l_table(item, found)


def waived(project: Path) -> bool:
    p = project / "waivers.json"
    if not p.exists():
        return False
    try:
        d = json.loads(p.read_text())
        v = d.get("rsp_latency_table_extracted_elsewhere", "")
        return isinstance(v, str) and len(v.strip()) >= 20
    except Exception:
        return False


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: per_opcode_response_latency_table_check.py "
              "<project_dir>")
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        print(f"FAIL — project dir not found: {project}")
        return 1

    docs = find_input_docs(project)
    doc_table: dict[str, int] = {}
    src_doc: Path | None = None
    for d in docs:
        try:
            text = d.read_text(errors="replace")
        except Exception:
            continue
        cand = extract_doc_table(text)
        if len(cand) >= 3:
            doc_table = cand
            src_doc = d
            break

    if not doc_table:
        print("PASS — no per-opcode RSP_xx[NN] response-latency table "
              "in input/docs/ (gate skipped)")
        return 0

    l_docs = find_l_doc(project)
    l_table: dict[str, int] = {}
    for ldoc in l_docs:
        try:
            data = json.loads(ldoc.read_text())
        except Exception:
            continue
        collect_l_table(data, l_table)

    if not l_table:
        if waived(project):
            print(f"PASS_WITH_WAIVER — RSP_xx table in {src_doc.name} "
                  f"not propagated into L11/L8 (waived)")
            return 0
        print(f"FAIL — per-opcode response-latency table found in "
              f"{src_doc.name} ({len(doc_table)} opcode(s)) but no "
              f"`response_latency_ticks` (or per-entry "
              f"response_latency_ticks) found in L11_OTP_CONTENT / "
              f"L8 docs.")
        print(f"  Doc opcodes: {sorted(doc_table.keys())[:8]}{'...' if len(doc_table) > 8 else ''}")
        print()
        print("Fix: timing-waveform-gen / cmd-protocol-gen must emit")
        print("     `response_latency_ticks: {\"0x70\": 91, ...}` either")
        print("     in L11_OTP_CONTENT.json or per command_table entry.")
        return 1

    overlap = sorted(set(doc_table.keys()) & set(l_table.keys()))
    coverage = len(overlap) / len(doc_table)
    if coverage < 0.75:
        if waived(project):
            print(f"PASS_WITH_WAIVER — RSP_xx coverage {coverage:.0%} "
                  f"({len(overlap)}/{len(doc_table)}) (waived)")
            return 0
        missing = sorted(set(doc_table.keys()) - set(l_table.keys()))
        print(f"FAIL — only {coverage:.0%} ({len(overlap)}/"
              f"{len(doc_table)}) of doc-table opcodes have a latency "
              f"entry in L docs. Need ≥75%.")
        print(f"  Missing: {missing[:10]}{'...' if len(missing) > 10 else ''}")
        return 1

    print(f"PASS — per-opcode RSP_xx table from {src_doc.name} extracted "
          f"into L docs ({len(overlap)}/{len(doc_table)} opcodes covered, "
          f"{coverage:.0%})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
