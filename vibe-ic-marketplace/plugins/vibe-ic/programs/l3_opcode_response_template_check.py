#!/usr/bin/env python3
"""
l3_opcode_response_template_check.py — Wave 37 / A2

When the project ships a vendor opcode-detail / opcode-override doc
(e.g. ``70指令控制說明.txt``, ``opcode_detail_*.txt``,
``*_command_detail.txt``, ``cmd_*.txt`` with byte-pattern templates
``XX YY 00 ZZ``), L3_CMD_PROTOCOL.json MUST contain a
``response_payload_template`` array per overridden opcode so RTL
gen can emit the literal byte sequence.

Detection is OPCODE-AGNOSTIC:
  - any extracted doc whose filename contains 指令控制說明 / 指令說明 /
    opcode_detail / cmd_detail / command_detail / cmd_override
  - that doc references >= 1 opcode with response shape
    ``HH HH 00 HH ...`` (byte-pattern template)

L3 schema accepted (canonical OR alias OR nested under opcodes[]):
    opcodes: [
      {hex: "0x73", name: "GET_STATE_RESP",
       response_payload_template: [
         {byte_offset: 0, value: "0x73", description: "..."},
         {byte_offset: 1, source: "state_register_high", ...},
         ...
       ]}
    ]

Usage:
    python3 l3_opcode_response_template_check.py <project_dir>

Exit codes:
    0 = PASS (no override doc OR template populated for >= 1 opcode)
    1 = FAIL (override doc exists, no response_payload_template found)
    2 = input-missing (skip)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple


_OVERRIDE_DOC_PATTERNS = (
    "**/input_doc/*指令控制說明*.txt",
    "**/input_doc/*指令說明*.txt",
    "**/input_doc/*opcode_detail*.txt",
    "**/input_doc/*cmd_detail*.txt",
    "**/input_doc/*command_detail*.txt",
    "**/input_doc/*cmd_override*.txt",
    "**/input/**/*指令控制說明*.txt",
    "**/input/**/*opcode_detail*.txt",
    "**/input/**/*command_detail*.txt",
)

_L3_GLOBS = (
    "phase1/generated_docs/L3_CMD_PROTOCOL.json",
    "phase1/generated_docs/L3*.json",
    "**/L3_CMD_PROTOCOL.json",
)

_TEMPLATE_KEYS = ("response_payload_template", "response_template",
                  "response_byte_template", "tx_payload_template",
                  "response_payload", "response_bytes")

# byte-pattern: 2+ hex bytes separated by space
_HEX_PATTERN = re.compile(r"\b([0-9A-Fa-f]{2}\s+){2,}[0-9A-Fa-f]{2}\b")


def _find_override_doc(project: Path) -> Optional[Path]:
    for pat in _OVERRIDE_DOC_PATTERNS:
        for hit in project.glob(pat):
            if hit.is_file():
                return hit
    return None


def _find_l3(project: Path) -> Optional[Path]:
    for pat in _L3_GLOBS:
        for hit in project.glob(pat):
            if hit.is_file():
                return hit
    return None


def _has_byte_pattern(doc: Path) -> bool:
    try:
        text = doc.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False
    return bool(_HEX_PATTERN.search(text))


def _walk_find_templates(node, out: List[Tuple[str, list]]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k in _TEMPLATE_KEYS and isinstance(v, list) and v:
                # also try to capture context name
                out.append((k, v))
            else:
                _walk_find_templates(v, out)
    elif isinstance(node, list):
        for item in node:
            _walk_find_templates(item, out)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: l3_opcode_response_template_check <project_dir>",
              file=sys.stderr)
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        return 2

    override_doc = _find_override_doc(project)
    if override_doc is None:
        print("[SKIP] l3_opcode_response_template_check: "
              "no opcode override doc found")
        return 2

    if not _has_byte_pattern(override_doc):
        print("[SKIP] l3_opcode_response_template_check: "
              f"override doc {override_doc.name} carries no byte-pattern "
              "templates")
        return 2

    l3 = _find_l3(project)
    if l3 is None:
        print(f"[FAIL] l3_opcode_response_template_check: "
              f"override doc {override_doc.relative_to(project)} present "
              f"but L3_CMD_PROTOCOL.json missing")
        return 1

    try:
        data = json.loads(l3.read_text())
    except Exception as exc:
        print(f"[FAIL] l3_opcode_response_template_check: "
              f"cannot parse {l3.relative_to(project)}: {exc}")
        return 1

    found: List[Tuple[str, list]] = []
    _walk_find_templates(data, found)

    if not found:
        print(f"[FAIL] l3_opcode_response_template_check: "
              f"vendor override doc {override_doc.relative_to(project)} "
              f"defines byte-pattern response template(s), but L3 has zero "
              f"opcode response_payload_template entries. Each overridden "
              f"opcode must carry response_payload_template with byte_offset "
              f"+ value/source per byte.")
        return 1

    # Validate at least one template has structured byte entries.
    structured_ok = False
    for k, tpl in found:
        if isinstance(tpl, list) and tpl:
            for ent in tpl:
                if isinstance(ent, dict) and (
                    "byte_offset" in ent or "offset" in ent or "byte" in ent
                ):
                    structured_ok = True
                    break
        if structured_ok:
            break

    if not structured_ok:
        print(f"[FAIL] l3_opcode_response_template_check: "
              f"response_payload_template found ({len(found)} entries) "
              f"but no entry carries structured byte_offset / offset / byte "
              f"field. Templates must be byte-typed, not free strings.")
        return 1

    print(f"[PASS] l3_opcode_response_template_check: "
          f"{len(found)} response_payload_template(s) populated "
          f"(override doc: {override_doc.relative_to(project)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
