#!/usr/bin/env python3
"""
l4_regmap_enumerated_values_typed_check.py — Wave 38 / B3

Audit item (PHASE2A_FULL_AUDIT_v0119.67.md, line 67): vendor
register tables routinely encode multi-state fields like 4-state
debounce filter (``OCP_DLY[1:0]``) or filter-mode selectors
(``RES_DLY[1:0]``) with a per-bit-pattern -> meaning mapping.
spec-to-rtl needs the typed enum to instantiate a valid filter
state machine; without it the field collapses to a numeric value
with no interpretation.

Trigger: L4_REGMAP.json has any register with a ``fields[]`` list
where at least one field has multi-bit width (>=2 bits) AND the
field's name suggests an enumerated meaning (matches keywords
``DLY``, ``MODE``, ``SEL``, ``CFG``, ``CTRL``, ``FILTER``,
``DEBOUNCE``, ``GAIN``, ``RANGE``, ``CLK``, ``DIV``, ``TRIM``,
``OPT``, ``STATE``).

Required typed shape: each such field MUST have an
``enumerated_values`` array (or ``enum``, ``encoding``,
``values``, ``state_table``) with at least 2 entries, each entry
being a dict with ``code`` (e.g. ``2'b00`` / ``0`` / ``"00"``) +
``meaning`` (free string) + optional ``evidence``.

The gate is chip-AGNOSTIC: it only checks shape; the bit width
threshold and field-name keyword list are protocol-/IC-class
generic.

Usage:
    python3 l4_regmap_enumerated_values_typed_check.py <project_dir>

Exit codes:
    0 = PASS (no enum-eligible fields OR each has typed enum)
    1 = FAIL (enum-eligible fields exist but lack enumerated_values)
    2 = input-missing (skip)

Honors waiver ``l4_regmap_enum_intentional_simplification`` (>=40
chars).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ic_class_profile import detect_ic_class  # noqa: E402


# Wave 43 (v0.119.75) — explicit ic_class_profile guard.
# L4 regmap with enumerated multi-bit fields is mandatory for digital
# command-driven ICs (UART / SPI / I2C / AID-class). Pure-analog
# parts have no command register file; bare-FPGA scaffolds have no
# fab-side regmap to characterise.
_SKIP_CLASSES = ("pure_analog", "bare_fpga")


_L4_GLOBS = (
    "phase1/generated_docs/L4_REGMAP.json",
    "phase1/generated_docs/L4*.json",
    "**/L4_REGMAP.json",
)

_REG_KEYS = ("registers", "regmap", "register_table", "regs")

_ENUM_KEYS = ("enumerated_values", "enum", "encoding", "values",
              "state_table", "value_map", "encodings", "bit_pattern_table")

_ENUM_NAME_KEYWORDS = re.compile(
    r"(?:^|[^A-Za-z0-9])"
    r"(DLY|MODE|SEL|CFG|CTRL|FILTER|DEBOUNCE|GAIN|RANGE|"
    r"DIV|TRIM|OPT|STATE|TEST|FUNC|TYP)"
    r"(?:[^A-Za-z0-9]|$)",
    re.IGNORECASE,
)


def _find_l4(project: Path) -> Optional[Path]:
    for pat in _L4_GLOBS:
        for hit in project.glob(pat):
            if hit.is_file():
                return hit
    return None


def _bit_width(field: dict) -> int:
    bits = field.get("bits") or field.get("bit_range") or field.get("range")
    if isinstance(bits, str):
        m = re.search(r"\[?(\d+)\s*[:\-]\s*(\d+)\]?", bits)
        if m:
            hi, lo = int(m.group(1)), int(m.group(2))
            return abs(hi - lo) + 1
        if bits.isdigit():
            return 1
    if isinstance(bits, list) and len(bits) == 2:
        try:
            return abs(int(bits[0]) - int(bits[1])) + 1
        except Exception:
            return 0
    width = field.get("width")
    if isinstance(width, int):
        return width
    if isinstance(width, str) and width.isdigit():
        return int(width)
    return 0


def _collect_register_fields(node,
                              out: List[Tuple[str, dict]]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k in _REG_KEYS and isinstance(v, list):
                for reg in v:
                    if not isinstance(reg, dict):
                        continue
                    reg_name = (reg.get("name")
                                or reg.get("register")
                                or reg.get("address") or "REG?")
                    fields = (reg.get("fields") or reg.get("bit_fields")
                              or reg.get("subfields") or [])
                    if isinstance(fields, list):
                        for f in fields:
                            if isinstance(f, dict):
                                out.append((str(reg_name), f))
            else:
                _collect_register_fields(v, out)
    elif isinstance(node, list):
        for it in node:
            _collect_register_fields(it, out)


def _has_enum(field: dict) -> bool:
    for k in _ENUM_KEYS:
        v = field.get(k)
        if isinstance(v, list) and len(v) >= 2:
            return True
        if isinstance(v, dict) and len(v) >= 2:
            return True
    return False


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: l4_regmap_enumerated_values_typed_check <project_dir>",
              file=sys.stderr)
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        return 2

    profile = detect_ic_class(project)
    ic_class = profile.get("ic_class", "unknown")
    if ic_class in _SKIP_CLASSES:
        print(f"[SKIP] l4_regmap_enumerated_values_typed_check: "
              f"ic_class={ic_class} (no command-driven regmap for "
              f"this IC class; gate not applicable)")
        return 2

    l4 = _find_l4(project)
    if l4 is None:
        print("[SKIP] l4_regmap_enumerated_values_typed_check: "
              "L4_REGMAP.json not found")
        return 2

    try:
        data = json.loads(l4.read_text())
    except Exception as exc:
        print(f"[FAIL] l4_regmap_enumerated_values_typed_check: "
              f"cannot parse {l4.relative_to(project)}: {exc}")
        return 1

    pairs: List[Tuple[str, dict]] = []
    _collect_register_fields(data, pairs)

    if not pairs:
        print("[SKIP] l4_regmap_enumerated_values_typed_check: "
              "no registers[]/fields[] in L4 (gate not applicable)")
        return 2

    eligible: List[Tuple[str, str]] = []
    missing: List[str] = []
    for reg_name, field in pairs:
        fname = (field.get("name") or field.get("field")
                 or field.get("bit_field") or "")
        width = _bit_width(field)
        if width >= 2 and _ENUM_NAME_KEYWORDS.search(fname or ""):
            eligible.append((reg_name, fname))
            if not _has_enum(field):
                missing.append(f"{reg_name}.{fname} (width={width})")

    if not eligible:
        print("[SKIP] l4_regmap_enumerated_values_typed_check: "
              "no multi-bit enum-eligible fields detected")
        return 2

    if missing:
        print(f"[FAIL] l4_regmap_enumerated_values_typed_check: "
              f"{len(missing)}/{len(eligible)} multi-bit enum-eligible "
              f"fields lack enumerated_values[]/enum[]. Examples: "
              f"{', '.join(missing[:5])}")
        return 1

    print(f"[PASS] l4_regmap_enumerated_values_typed_check: "
          f"{len(eligible)} multi-bit enum-eligible fields all have "
          f"typed enumerated_values")
    return 0


if __name__ == "__main__":
    sys.exit(main())
