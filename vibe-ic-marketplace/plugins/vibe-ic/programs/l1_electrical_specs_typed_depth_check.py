#!/usr/bin/env python3
"""
l1_electrical_specs_typed_depth_check.py — Wave 38 / B1

Audit-driven typed sub-field depth gate. Closes the residual ~70
missed items category surfaced in
``docs/design/PHASE2A_FULL_AUDIT_v0119.67.md`` (line 75–77):
electrical limits (V/I/T) are usually captured as free-form strings
inside L1.description, never as typed min/typ/max/unit/conditions
records that spec-to-rtl, lab-calibration and analog-spec-extract
can lookup.

Trigger: when extracted vendor docs contain an electrical-table
mention (``VDD``, ``VDDA``, ``IDD``, ``Typ.``, ``Min.``, ``Max.``,
explicit ``\\d+\\.?\\d*\\s*(V|mV|mA|μA|uA)``) or the L1 doc has an
``electrical_specs``-shaped field of any depth.

Required typed shape (any of these aliases): ``electrical_specs``,
``electrical_limits``, ``electrical_characteristics``,
``operating_conditions``, ``dc_specs``, ``absolute_max_ratings``.
Each entry MUST have at least ``name`` + ``unit`` + one of
{``min``, ``typ``, ``max``, ``min_typ_max``} + ``evidence``
(``<file>:<line>``).

The gate is chip-AGNOSTIC: only the schema depth is enforced, not
specific voltage/current values.

Usage:
    python3 l1_electrical_specs_typed_depth_check.py <project_dir>

Exit codes:
    0 = PASS (no electrical mention OR typed sub-field depth OK)
    1 = FAIL (electrical mentions present but no/shallow typed entries)
    2 = input-missing (skip)

Honors waiver ``l1_electrical_specs_depth_intentional`` (>=40 chars).
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
# L1 electrical_specs are MANDATORY for digital / mixed-signal /
# EXAMPLE_PROTOCOL-class digital ICs. Pure-analog blocks have their own A1-A8
# analog-spec deck (different shape, different units), so this gate
# becomes noise on a pure-analog project.
_SKIP_CLASSES = ("pure_analog",)


_DOC_GLOBS = (
    "**/input_doc/*.txt",
    "**/input/docs/*.txt",
    "**/input/input_doc/*.txt",
)

_L1_GLOBS = (
    "phase1/generated_docs/L1_DATASHEET.json",
    "phase1/generated_docs/L1*.json",
    "**/L1_DATASHEET.json",
)

_RE_ELEC = re.compile(
    r"\b(VDD|VDDA|VSS|VDDIO|IDD|IDDQ|VTH|VOH|VOL|VIH|VIL|VBG|VREF)"
    r"|(?:\d+\.?\d*)\s*(?:V|mV|mA|μA|uA|kΩ|Ω)\b"
    r"|\b(?:Typ\.|Min\.|Max\.)\b",
    re.IGNORECASE,
)

_SPEC_KEYS = (
    "electrical_specs", "electrical_limits",
    "electrical_characteristics", "operating_conditions",
    "dc_specs", "absolute_max_ratings", "ac_specs",
)

_REQUIRED_VALUE_KEYS = ("min", "typ", "max", "min_typ_max",
                         "value", "nominal", "limit")
_REQUIRED_NAME_KEYS = ("name", "param", "parameter", "symbol")
_REQUIRED_UNIT_KEYS = ("unit", "units")
_REQUIRED_EVIDENCE_KEYS = ("evidence", "evidence_path", "source")


def _find_l1(project: Path) -> Optional[Path]:
    for pat in _L1_GLOBS:
        for hit in project.glob(pat):
            if hit.is_file():
                return hit
    return None


def _scan_docs(project: Path) -> List[Tuple[Path, int]]:
    hits: List[Tuple[Path, int]] = []
    seen = set()
    for pat in _DOC_GLOBS:
        for doc in project.glob(pat):
            if not doc.is_file() or doc in seen:
                continue
            seen.add(doc)
            try:
                text = doc.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                if _RE_ELEC.search(line):
                    hits.append((doc, i))
                    if len(hits) >= 50:
                        return hits
    return hits


def _collect_spec_entries(node, out: List[dict]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k in _SPEC_KEYS and isinstance(v, list):
                for it in v:
                    if isinstance(it, dict):
                        out.append(it)
            else:
                _collect_spec_entries(v, out)
    elif isinstance(node, list):
        for it in node:
            _collect_spec_entries(it, out)


def _entry_typed_ok(entry: dict) -> Tuple[bool, str]:
    has_name = any(k in entry for k in _REQUIRED_NAME_KEYS)
    has_value = any(k in entry for k in _REQUIRED_VALUE_KEYS)
    has_unit = any(k in entry for k in _REQUIRED_UNIT_KEYS)
    has_evidence = any(k in entry for k in _REQUIRED_EVIDENCE_KEYS)
    missing: List[str] = []
    if not has_name:
        missing.append("name")
    if not has_value:
        missing.append("min/typ/max/value")
    if not has_unit:
        missing.append("unit")
    if not has_evidence:
        missing.append("evidence")
    return (not missing, ",".join(missing))


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: l1_electrical_specs_typed_depth_check <project_dir>",
              file=sys.stderr)
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        return 2

    profile = detect_ic_class(project)
    ic_class = profile.get("ic_class", "unknown")
    if ic_class in _SKIP_CLASSES:
        print(f"[SKIP] l1_electrical_specs_typed_depth_check: "
              f"ic_class={ic_class} (analog blocks carry their own "
              f"A1-A8 spec deck, not L1.electrical_specs[])")
        return 2

    hits = _scan_docs(project)
    l1 = _find_l1(project)
    if not hits and l1 is None:
        print("[SKIP] l1_electrical_specs_typed_depth_check: "
              "no electrical mention in docs and no L1 to inspect")
        return 2

    if l1 is None:
        print(f"[FAIL] l1_electrical_specs_typed_depth_check: "
              f"{len(hits)} electrical mention(s) in extracted docs "
              f"but L1_DATASHEET.json missing")
        return 1

    try:
        data = json.loads(l1.read_text())
    except Exception as exc:
        print(f"[FAIL] l1_electrical_specs_typed_depth_check: "
              f"cannot parse {l1.relative_to(project)}: {exc}")
        return 1

    entries: List[dict] = []
    _collect_spec_entries(data, entries)

    if not entries:
        if hits:
            print(f"[FAIL] l1_electrical_specs_typed_depth_check: "
                  f"{len(hits)} electrical mention(s) (e.g. "
                  f"{hits[0][0].name}:{hits[0][1]}) but L1 has no typed "
                  f"electrical_specs[] / electrical_limits[] / "
                  f"electrical_characteristics[] array. Add typed "
                  f"entries with name/min_typ_max/unit/conditions/evidence.")
            return 1
        # No mentions and no entries => silent skip.
        print("[SKIP] l1_electrical_specs_typed_depth_check: "
              "no electrical entries to validate")
        return 2

    bad: List[str] = []
    for i, e in enumerate(entries):
        ok, miss = _entry_typed_ok(e)
        if not ok:
            label = (e.get("name") or e.get("param")
                     or e.get("symbol") or f"entry[{i}]")
            bad.append(f"{label}: missing {miss}")
    if bad:
        print(f"[FAIL] l1_electrical_specs_typed_depth_check: "
              f"{len(bad)}/{len(entries)} entries are too shallow. "
              f"Examples: {'; '.join(bad[:5])}")
        return 1

    print(f"[PASS] l1_electrical_specs_typed_depth_check: "
          f"{len(entries)} typed electrical entries with "
          f"name/min_typ_max/unit/evidence")
    return 0


if __name__ == "__main__":
    sys.exit(main())
