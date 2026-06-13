#!/usr/bin/env python3
"""
fpga_pad_pullup_consistency_check.py — cross-check L5 pad pull-up
declaration against project QSF (Quartus Settings File) pull-up
assignments.

Why this gate exists
====================
Surfaced by ROOT_CAUSE_ANALYSIS Area 5 (<benchmark> fresh agent vs vendor).
The vendor's chip-side pad has no on-chip pull-up; the bus relies on
an external 5.1kΩ pull-up at the host. The fresh agent's QSF added
`set_instance_assignment -name WEAK_PULL_UP_RESISTOR ON -to GPIO_0`,
which inserts the FPGA's ~25kΩ pull-up. That pull-up fights the
host's drive strength when the host pulls low, distorts edges near
the bit-0/bit-1 boundary, and the host receiver mis-classifies bytes
(byte[6]=0x02 fingerprint).

Conversely, if L5 declares `external_pullup: false` (the chip
expects an internal source) but the QSF has no pull-up assignment
either, the bus is left floating — also a FAIL.

Rule
----
For each pad in L5_ADI_SPEC.json `pad_definitions[]` with an
`external_pullup` boolean field:
  Determine the pad's FPGA-pin alias(es). Search every *.qsf for
  WEAK_PULL_UP_RESISTOR / WEAK_PULL_UP / PULLUP / PULL_UP assignments
  to that alias.
  - external_pullup == true  AND QSF has a pull-up assignment → FAIL
  - external_pullup == false AND QSF lacks a pull-up assignment → FAIL
  - external_pullup == true  AND QSF lacks pull-up → PASS
  - external_pullup == false AND QSF has pull-up → PASS

Skips silently when:
  - L5_ADI_SPEC.json absent
  - no `pad_definitions[]` with `external_pullup` declared
  - no .qsf file present (non-FPGA project)

Honors waivers.json key `fpga_pad_pullup_consistency_alternative`
(≥20-char rationale).

Usage
-----
python3 fpga_pad_pullup_consistency_check.py <project_dir>

Returns 0 on PASS / silent-skip / waived, 1 on FAIL.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
import _path_layout as _pl


def _load_json(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _find_l5(project: Path) -> Path | None:
    for base in (project, _pl.generated_docs_dir(project)):
        p = base / "L5_ADI_SPEC.json"
        if p.exists():
            return p
    return None


def _find_qsfs(project: Path) -> list[Path]:
    out = []
    for p in project.rglob("*.qsf"):
        if ".git" in p.parts:
            continue
        out.append(p)
    return sorted(out)


def _pad_aliases_for_pad(pad: dict) -> list[str]:
    """Return the set of FPGA-pin alias strings for a pad. Falls back
    to the canonical pad name if no alias is declared."""
    out: list[str] = []
    aliases = pad.get("fpga_alias") or pad.get("fpga_aliases") or \
              pad.get("fpga_pin")
    if isinstance(aliases, str):
        out.append(aliases.strip())
    elif isinstance(aliases, list):
        for a in aliases:
            if isinstance(a, str) and a.strip():
                out.append(a.strip())
    if not out:
        nm = pad.get("name")
        if isinstance(nm, str) and nm.strip():
            out.append(nm.strip())
    return out


def _qsf_has_pullup_for(qsfs: list[Path], pad_alias: str) -> str | None:
    """Return the first matching QSF assignment line if any *.qsf
    sets WEAK_PULL_UP_RESISTOR / WEAK_PULL_UP / PULLUP / PULL_UP ON
    for the pad. None if no pull-up assignment found."""
    pad_norm = pad_alias.upper()
    pad_base = pad_norm.split("[")[0]
    pat = re.compile(
        r"set_instance_assignment[^\n#]*-name\s+"
        r"(WEAK_PULL_UP_RESISTOR|WEAK_PULL_UP|PULLUP|PULL_UP)"
        r"\s+ON[^\n#]*-to\s+(\S+)",
        re.IGNORECASE,
    )
    for q in qsfs:
        try:
            text = q.read_text(errors="replace")
        except Exception:
            continue
        for m in pat.finditer(text):
            target = m.group(2).strip().strip('"').upper()
            target_base = target.split("[")[0]
            if target == pad_norm or target_base == pad_base:
                return m.group(0).strip()
    return None


def _waived(project: Path) -> bool:
    waivers = project / "waivers.json"
    if not waivers.exists():
        return False
    try:
        d = json.loads(waivers.read_text())
        v = d.get("fpga_pad_pullup_consistency_alternative", "")
        return isinstance(v, str) and len(v.strip()) >= 20
    except Exception:
        return False


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: fpga_pad_pullup_consistency_check.py <project_dir>")
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        print(f"FAIL — not a directory: {project}")
        return 1

    qsfs = _find_qsfs(project)
    if not qsfs:
        print("PASS — no *.qsf present (not an FPGA project; gate "
              "skipped)")
        return 0

    l5_path = _find_l5(project)
    if l5_path is None:
        print("PASS — no L5_ADI_SPEC.json (gate not applicable)")
        return 0
    l5 = _load_json(l5_path)
    pads = l5.get("pad_definitions") or []
    if not isinstance(pads, list) or not pads:
        print("PASS — L5 has no pad_definitions[] (gate not applicable)")
        return 0

    declared_pads: list[tuple[str, bool, list[str]]] = []
    for pad in pads:
        if not isinstance(pad, dict):
            continue
        if "external_pullup" not in pad:
            continue
        ext = pad["external_pullup"]
        if not isinstance(ext, bool):
            continue
        aliases = _pad_aliases_for_pad(pad)
        if not aliases:
            continue
        nm = pad.get("name", "?")
        declared_pads.append((str(nm), ext, aliases))

    if not declared_pads:
        print("PASS — no pad declares external_pullup (gate not "
              "applicable)")
        return 0

    fails: list[tuple[str, bool, str, str]] = []  # name, ext, alias, qsf_line_or_empty
    passes: list[str] = []
    for name, ext, aliases in declared_pads:
        # Use the first alias that has any QSF mention or just first.
        for alias in aliases:
            assign = _qsf_has_pullup_for(qsfs, alias)
            has_pullup = assign is not None
            if ext and has_pullup:
                fails.append((name, ext, alias, assign or ""))
                break
            if (not ext) and (not has_pullup):
                fails.append((name, ext, alias, ""))
                break
        else:
            passes.append(f"{name} → {','.join(aliases)} OK")

    if not fails:
        print(f"PASS — all {len(declared_pads)} pad(s) with "
              "external_pullup declared are consistent with QSF "
              "pull-up assignments")
        for p in passes:
            print(f"  • {p}")
        return 0

    if _waived(project):
        print(f"PASS_WITH_WAIVER — {len(fails)} pad(s) inconsistent "
              "but waiver is set:")
        for name, ext, alias, line in fails:
            tag = "external_pullup=true + QSF pull-up" if ext else \
                  "external_pullup=false + no QSF pull-up"
            print(f"  • {name} ({alias}): {tag}")
        return 0

    print(f"FAIL — {len(fails)} pad(s) inconsistent between L5 "
          "external_pullup and QSF pull-up assignments:")
    for name, ext, alias, line in fails:
        if ext:
            print(f"  • {name} ({alias}): L5 declares external_pullup="
                  "true (chip relies on board pull-up) but QSF has:")
            print(f"      {line}")
            print("    Fix: REMOVE the QSF pull-up assignment so the "
                  "FPGA's internal weak pull-up does not fight the "
                  "host's drive strength.")
        else:
            print(f"  • {name} ({alias}): L5 declares external_pullup="
                  "false (chip needs internal pull-up) but no QSF "
                  "pull-up found.")
            print("    Fix: ADD to *.qsf:")
            print(f"      set_instance_assignment -name "
                  f"WEAK_PULL_UP_RESISTOR ON -to {alias}")
    print()
    print("Why this matters:")
    print("  An FPGA internal weak pull-up (~25kΩ) fights an external")
    print("  bus driver and distorts edges near bit-0/bit-1 boundary;")
    print("  conversely, a floating bus pin without any pull-up source")
    print("  glitches randomly. Both produce silent receive errors")
    print("  invisible to RTL sim — the byte[6]=0x02 fallback symptom.")
    print()
    print("Or document an exception in waivers.json (≥20 chars):")
    print('    {"fpga_pad_pullup_consistency_alternative": "<reason>"}')
    return 1


if __name__ == "__main__":
    sys.exit(main())
