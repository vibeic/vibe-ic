#!/usr/bin/env python3
"""no_protocol_consistency_check.py — v0.56 plugin gate

Verifies that a Phase-1 doc set declaring the **no-protocol sentinel**
in L3 (added v0.56 for memory-access / register-pointer / analog-
front-end ICs) is internally consistent across L3 / L4 / L8R / class
template. The sentinel:

    L3_CMD_PROTOCOL.json
    {
      "protocol_present": false,
      "reason": "register-pointer access only — analog front-end",
      ...
    }

When this sentinel is present, the IC has no command-byte protocol,
no protocol CRC, and no opcode list. This gate verifies the rest of
the doc stack agrees:

  Rule 1  L3 sentinel must include a non-empty `reason` field
          (downstream gates surface it; an empty reason makes the
          skip silent).
  Rule 2  L3 must NOT also carry `command_set` / `opcode_table` /
          `crc` fields — those are protocol-IC-only fields and their
          presence alongside `protocol_present: false` is a
          contradiction.
  Rule 3  L8R must NOT declare `crc8_polynomial` / `crc8_init` /
          `crc16_*`. These constants are derived from L3.crc;
          without an L3 protocol they are by definition unsourced.
  Rule 4  Class template's `spec_floor:` must NOT carry
          `L3_opcode_count_min` or `L3_crc_poly_allowed`. If present,
          the floor will spuriously fail the IC. (Discovered as
          structural failure in the v0.55 multi-IC validation:
          24LC256 + ADS1115 hit <chip-class>-default floor and both
          failed 6-8 L3-specific rules.)

Conversely, if L3 has `protocol_present: true` (or omits the field
entirely — the legacy default), this gate is a no-op (returns
PASS). It only fires when the sentinel is in use.

Usage:
    python3 no_protocol_consistency_check.py <docs_dir>
        [--class-kb <path>]
        [--json <out>]

Exit codes:
    0 — sentinel absent (N/A) OR all 4 rules pass
    1 — at least one inconsistency found
    2 — input path error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


_FORBIDDEN_L3_FIELDS = ("command_set", "opcode_table", "commands", "crc")
_FORBIDDEN_L8R_FIELDS = ("crc8_polynomial", "crc8_init", "crc8_refin",
                          "crc8_refout", "crc8_xorout",
                          "crc16_polynomial", "crc16_init")


def _load_l3(docs_dir: Path) -> Optional[Dict[str, Any]]:
    p = docs_dir / "L3_CMD_PROTOCOL.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _load_l8r(docs_dir: Path) -> Optional[Dict[str, Any]]:
    # Try both common spellings (L8R = constants; L8 = timing)
    for name in ("L8_RTL_CONSTANTS.json", "L8R_RTL_CONSTANTS.json",
                 "L8R_CONSTANTS.json"):
        p = docs_dir / name
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:
                return None
    return None


def _resolve_class_path_from_l1(docs_dir: Path) -> Optional[str]:
    p = docs_dir / "L1_DATASHEET.json"
    if not p.exists():
        return None
    try:
        text = p.read_text()
        text_fixed = re.sub(
            r'(?P<p>[:\[\,\s])0x([0-9a-fA-F]+)',
            lambda m: m.group("p") + str(int(m.group(2), 16)),
            text,
        )
        l1 = json.loads(text_fixed)
    except Exception:
        return None
    cp = l1.get("class_path", "")
    if isinstance(cp, str) and cp.strip():
        return cp.split(">")[-1].strip().lower()
    return None


def _load_class_floor(class_path: Optional[str], class_kb: Path) -> Dict[str, Any]:
    """Tiny stdlib YAML reader for the `spec_floor:` block of a class
    template. Returns {} if the template doesn't ship a floor."""
    if not class_path:
        return {}
    p = class_kb / "templates" / f"{class_path}.yaml"
    if not p.exists():
        return {}
    floor: Dict[str, Any] = {}
    in_floor = False
    for raw in p.read_text().splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if not raw.startswith(" "):
            in_floor = (line.strip().rstrip(":") == "spec_floor")
            continue
        if not in_floor:
            continue
        s = line.strip()
        if ":" in s and not s.startswith("-"):
            k, _, v = s.partition(":")
            v = re.sub(r"\s+#.*$", "", v).strip()
            if v:
                floor[k.strip()] = v
            else:
                # list-valued key — peek next lines (best-effort: just
                # mark the key as present with empty value).
                floor[k.strip()] = "<list>"
    return floor


def check(docs_dir: Path, class_kb: Path) -> Tuple[int, Dict[str, Any]]:
    if not docs_dir.is_dir():
        return 2, {"error": f"docs_dir {docs_dir} does not exist"}

    l3 = _load_l3(docs_dir)
    if l3 is None or l3.get("protocol_present") is not False:
        # Sentinel absent — gate is N/A.
        return 0, {
            "applies": False,
            "reason": "L3 either missing or does not declare protocol_present=false",
            "findings": [],
        }

    findings: List[Dict[str, Any]] = []

    # Rule 1 — non-empty reason
    reason = l3.get("reason", "")
    if not isinstance(reason, str) or not reason.strip():
        findings.append({
            "rule": "no_protocol_reason_required",
            "severity": "FAIL",
            "message": ("L3 sentinel must include a non-empty `reason` "
                        "field so downstream readers know WHY the protocol "
                        "is absent (memory access / register pointer / "
                        "analog front-end / pure logic)."),
        })

    # Rule 2 — no contradicting L3 fields
    for f in _FORBIDDEN_L3_FIELDS:
        if f in l3 and l3[f] not in (None, [], {}):
            findings.append({
                "rule": "no_protocol_l3_contradiction",
                "severity": "FAIL",
                "field": f,
                "message": (f"L3 has `{f}` populated AND `protocol_present: false`. "
                            "Either remove the sentinel (the IC does have a "
                            "protocol) or drop the contradicting field."),
            })

    # Rule 3 — no CRC constants in L8R
    l8r = _load_l8r(docs_dir)
    if l8r:
        for f in _FORBIDDEN_L8R_FIELDS:
            if f in l8r and l8r[f] not in (None, "", 0):
                findings.append({
                    "rule": "no_protocol_l8r_contradiction",
                    "severity": "FAIL",
                    "field": f,
                    "message": (f"L8R declares `{f}` but L3 has no protocol. "
                                "CRC constants must be sourced from L3.crc; "
                                "with no L3 protocol they are unsourced."),
                })

    # Rule 4 — class floor must not require L3 things
    class_path = _resolve_class_path_from_l1(docs_dir)
    floor = _load_class_floor(class_path, class_kb)
    for forbidden_floor_key in ("L3_opcode_count_min", "L3_crc_poly_allowed"):
        if forbidden_floor_key in floor:
            findings.append({
                "rule": "no_protocol_class_floor_mismatch",
                "severity": "FAIL",
                "class_path": class_path,
                "field": forbidden_floor_key,
                "message": (f"Class template `{class_path}.yaml` declares "
                            f"spec_floor.{forbidden_floor_key} but the IC "
                            "uses the no-protocol sentinel. Either remove "
                            "the floor (this class supports protocol-less "
                            "ICs) or pick a class that has a protocol."),
            })

    rc = 1 if findings else 0
    return rc, {
        "applies": True,
        "reason": l3.get("reason", ""),
        "class_path": class_path,
        "class_floor_keys": sorted(floor.keys()) if floor else [],
        "findings": findings,
        "pass": rc == 0,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("docs_dir")
    ap.add_argument("--class-kb", default=None,
                    help="path to plugins/vibe-ic/agents/class_kb "
                         "(autodetected if omitted)")
    ap.add_argument("--json", default=None, help="output JSON report path")
    args = ap.parse_args(argv)

    docs_dir = Path(args.docs_dir)
    if args.class_kb:
        class_kb = Path(args.class_kb)
    else:
        here = Path(__file__).resolve().parent
        class_kb = here.parent / "agents" / "class_kb"

    rc, report = check(docs_dir, class_kb)
    payload = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(payload)
    print(payload)
    return rc


if __name__ == "__main__":
    sys.exit(main())
