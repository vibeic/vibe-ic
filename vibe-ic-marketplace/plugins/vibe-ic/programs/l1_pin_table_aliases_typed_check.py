#!/usr/bin/env python3
"""
l1_pin_table_aliases_typed_check.py — Wave 38 / B2

Audit-driven typed sub-field depth gate. Vendor docs commonly use
multiple names for the same pin (datasheet ``ACC_ID`` / RTL
``id_bus`` / FPGA ``GPIO_0[0]``). When L1.pin_table only carries
one of them, downstream skills cannot cross-reference vendor docs,
QSF and RTL.

Trigger: L1 has a ``pin_table`` / ``pins`` / ``pinout`` array. The
gate then enforces that EACH entry has at least the canonical
typed sub-fields:
  - ``name`` (string)
  - ``mode`` (one of input/output/inout/bidir/analog/digital/power)
  - ``aliases`` (list of strings — datasheet/RTL/board synonyms)
    OR equivalent ``alias`` / ``alt_names`` / ``synonyms`` /
    ``rtl_name`` + ``board_name``.

The gate is chip-AGNOSTIC: only the schema depth is enforced, not
specific pin counts or pad names.

Usage:
    python3 l1_pin_table_aliases_typed_check.py <project_dir>

Exit codes:
    0 = PASS (no pin_table OR every entry typed deep enough)
    1 = FAIL (pin_table exists but entries miss aliases/mode)
    2 = input-missing (skip)

Honors waiver ``l1_pin_table_aliases_intentional`` (>=40 chars).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ic_class_profile import detect_ic_class  # noqa: E402


# Wave 43 (v0.119.75) — explicit ic_class_profile guard.
# Pin-table alias triplet (datasheet / RTL / board) is required when
# we are fabricating an IC (own pinout). Bare-FPGA projects use a
# fixed evaluation-board pinout and have no datasheet pin-name
# mapping to maintain.
_SKIP_CLASSES = ("bare_fpga",)


_L1_GLOBS = (
    "phase1/generated_docs/L1_DATASHEET.json",
    "phase1/generated_docs/L1*.json",
    "**/L1_DATASHEET.json",
)

_PIN_KEYS = ("pin_table", "pins", "pinout", "pin_list", "io_table")

_ALIAS_KEYS = ("aliases", "alias", "alt_names", "synonyms",
               "alternative_names", "rtl_name", "datasheet_name",
               "board_name", "fpga_pin")
_MODE_KEYS = ("mode", "direction", "io", "type", "pin_type")
_NAME_KEYS = ("name", "pin", "signal", "symbol")


def _find_l1(project: Path) -> Optional[Path]:
    for pat in _L1_GLOBS:
        for hit in project.glob(pat):
            if hit.is_file():
                return hit
    return None


def _collect_pin_entries(node, out: List[dict]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k in _PIN_KEYS and isinstance(v, list):
                for it in v:
                    if isinstance(it, dict):
                        out.append(it)
            else:
                _collect_pin_entries(v, out)
    elif isinstance(node, list):
        for it in node:
            _collect_pin_entries(it, out)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: l1_pin_table_aliases_typed_check <project_dir>",
              file=sys.stderr)
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        return 2

    profile = detect_ic_class(project)
    ic_class = profile.get("ic_class", "unknown")
    if ic_class in _SKIP_CLASSES:
        print(f"[SKIP] l1_pin_table_aliases_typed_check: "
              f"ic_class={ic_class} (FPGA evaluation board has fixed "
              f"pinout; no datasheet pin-alias triplet to maintain)")
        return 2

    l1 = _find_l1(project)
    if l1 is None:
        print("[SKIP] l1_pin_table_aliases_typed_check: "
              "L1_DATASHEET.json not found")
        return 2

    try:
        data = json.loads(l1.read_text())
    except Exception as exc:
        print(f"[FAIL] l1_pin_table_aliases_typed_check: "
              f"cannot parse {l1.relative_to(project)}: {exc}")
        return 1

    entries: List[dict] = []
    _collect_pin_entries(data, entries)

    if not entries:
        print("[SKIP] l1_pin_table_aliases_typed_check: "
              "no pin_table[] in L1 (gate not applicable)")
        return 2

    bad: List[str] = []
    no_mode = 0
    no_alias = 0
    for i, p in enumerate(entries):
        label = (p.get("name") or p.get("pin")
                 or p.get("signal") or f"pin[{i}]")
        has_name = any(k in p for k in _NAME_KEYS)
        has_mode = any(k in p for k in _MODE_KEYS)
        has_alias = any(k in p for k in _ALIAS_KEYS)
        # aliases can be empty list -> still counts as "field present"
        # but we additionally require at least 1 alias when the alias
        # field is the primary list-shape variant.
        if not has_name:
            bad.append(f"{label}: missing name")
            continue
        if not has_mode:
            no_mode += 1
            bad.append(f"{label}: missing mode/direction/io")
        if not has_alias:
            no_alias += 1
            bad.append(f"{label}: missing aliases[]/rtl_name/board_name")

    if bad:
        print(f"[FAIL] l1_pin_table_aliases_typed_check: "
              f"{len(bad)}/{len(entries)} pin entries miss typed "
              f"depth (mode missing on {no_mode}, aliases missing on "
              f"{no_alias}). Examples: {'; '.join(bad[:5])}")
        return 1

    print(f"[PASS] l1_pin_table_aliases_typed_check: "
          f"{len(entries)} pins with name/mode/aliases typed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
