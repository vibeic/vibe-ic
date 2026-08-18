#!/usr/bin/env python3
"""analog_block_type_classify.py — deterministic name→type taxonomy lookup.

Extracts the block-type classification rule embedded in the
`analog-spec-extract` skill ("Analog block taxonomy" table). The skill
prose listed a name→type mapping table:

    ldo / regulator / vreg          -> LDO
    bgr / bandgap / vref            -> Bandgap
    osc / rc_osc / ring_osc         -> Oscillator
    por / power_on_reset            -> POR
    comp / comparator               -> Comparator
    adc / sar_adc                   -> ADC
    dac                             -> DAC
    pll / dpll                      -> PLL
    cp / charge_pump                -> Charge_pump
    ota / opamp                     -> OTA_OpAmp
    bias / ibias / current_ref      -> Bias
    ls / level_shift                -> Level_shifter
    esd / clamp                     -> ESD
    pull / rpd / rpu / rmpd         -> Pull
    trim                            -> Trim

This is a pure deterministic table lookup — NO inference. Given a block
NAME (or a small free-form descriptor of that block), it returns the
canonical taxonomy type. It does NOT bind numeric spec values (that is
the LLM residual documented in the skill).

Two modes:
  * single name:   classify ONE name, print its type.
  * --block-list:  read an analog/analog_block_list.json and verify that
                   every block's declared `type` is consistent with what
                   the taxonomy lookup derives from its `name`. A block
                   whose declared type contradicts its name FAILs (catches
                   a real mislabel, e.g. name="ldo_1v8" type="Oscillator").

A name that matches NO taxonomy token is classified "UNKNOWN" — in
single mode that is exit 0 (honest "could not classify", an LLM/human
must decide), and in --block-list mode an UNKNOWN-name block is NOT a
FAIL by itself (the declared type is taken as-is) but is reported.

Usage:
    python3 analog_block_type_classify.py <name> [--json out.json]
    python3 analog_block_type_classify.py --block-list <path> [--json out.json]

Exit codes:
    0  classified OK (single mode) / all consistent (block-list mode)
    1  FAIL — a block's declared type contradicts its name (block-list mode)
    2  IO / usage error (missing arg, file absent, unparsable JSON)

chip-AGNOSTIC. No vendor / chip / specific block-name hardcoded —
only generic analog block-CLASS tokens.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple


# Ordered taxonomy: (canonical_type, regex over a NORMALISED name).
# The name is normalised first (camelCase split + all separators →
# single spaces), so multi-word tokens are matched in their spaced form
# ("rc osc", "power on reset", "level shift"). Matching is anchored on
# space/boundary so a token only fires on a real word fragment, not an
# arbitrary substring.
# ORDER MATTERS — more specific tokens are listed before generic ones so
# that e.g. "sar adc" classifies as ADC deterministically.
_BOUND = r"(?:^|\s)"   # left boundary on the normalised (space-padded) name
_BEND = r"(?:\s|$)"    # right boundary
_TAXONOMY: List[Tuple[str, re.Pattern]] = [
    ("ADC",            re.compile(_BOUND + r"(adc|sar\s*adc|sigma\s*delta|analog\s*to\s*digital)" + _BEND)),
    ("DAC",            re.compile(_BOUND + r"(dac|digital\s*to\s*analog)" + _BEND)),
    ("PLL",            re.compile(_BOUND + r"(pll|dpll|dll|phase\s*locked)" + _BEND)),
    ("Bandgap",        re.compile(_BOUND + r"(bandgap|band\s*gap|bgr|bg\s*ref|vref|vbg)" + _BEND)),
    ("LDO",            re.compile(_BOUND + r"(ldo|regulator|vreg|low\s*dropout)" + _BEND)),
    ("Oscillator",     re.compile(_BOUND + r"(osc|oscillator|rc\s*osc|ring\s*osc|crystal|xtal)" + _BEND)),
    ("POR",            re.compile(_BOUND + r"(por|power\s*on\s*reset|brownout|bor)" + _BEND)),
    ("Comparator",     re.compile(_BOUND + r"(comp|comparator)" + _BEND)),
    ("Charge_pump",    re.compile(_BOUND + r"(cp|charge\s*pump)" + _BEND)),
    ("OTA_OpAmp",      re.compile(_BOUND + r"(ota|opamp|op\s*amp|operational\s*amplifier)" + _BEND)),
    ("Level_shifter",  re.compile(_BOUND + r"(ls|level\s*shift(?:er)?|lvls)" + _BEND)),
    ("Bias",           re.compile(_BOUND + r"(bias|ibias|current\s*ref|iref)" + _BEND)),
    ("ESD",            re.compile(_BOUND + r"(esd|clamp\s*diode|clamp)" + _BEND)),
    ("Pull",           re.compile(_BOUND + r"(pull\s*up|pull\s*down|pull|rpd|rpu|rmpd)" + _BEND)),
    ("Trim",           re.compile(_BOUND + r"(trim)" + _BEND)),
]


def classify(name: str) -> str:
    """Return the canonical taxonomy type for ``name``, or "UNKNOWN".

    Deterministic: split camelCase humps, lower-case, then convert every
    run of non-alphanumeric (``_``, ``-``, digits-adjacent punctuation,
    whitespace) to a single space so tokens embedded in identifiers
    (``ldo_1v8`` → ``ldo 1v8``, ``ringOsc`` → ``ring osc``) become
    space-separated words; then test each taxonomy regex in priority
    order. NO inference — pure token lookup.
    """
    if not isinstance(name, str) or not name.strip():
        return "UNKNOWN"
    norm = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    norm = norm.lower()
    # Every non-alnum run → single space (drops _, -, ., /, etc.).
    norm = re.sub(r"[^a-z0-9]+", " ", norm)
    norm = norm.strip()
    for canon, pat in _TAXONOMY:
        if pat.search(norm):
            return canon
    return "UNKNOWN"


# Canonical-type aliases — when comparing a DECLARED type string against
# the name-derived type, accept any string that itself classifies to the
# same canonical type (so declared "RC_oscillator" == derived "Oscillator").
def _declared_to_canon(declared: str) -> str:
    if not isinstance(declared, str) or not declared.strip():
        return "UNKNOWN"
    direct = declared.strip().replace(" ", "_")
    # Exact canonical match (case-insensitive) wins.
    for canon, _ in _TAXONOMY:
        if direct.lower() == canon.lower():
            return canon
    # Otherwise run the same token classifier over the declared string.
    return classify(declared)


def _check_block_list(path: Path) -> Tuple[int, dict]:
    """Verify each block's declared type is consistent with its name.

    Returns (exit_code, report_dict).
    """
    if not path.is_file():
        return 2, {"status": "ERROR",
                   "detail": f"block list not found: {path}"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return 2, {"status": "ERROR",
                   "detail": f"unparsable block list: {exc}"}
    blocks = data.get("blocks") if isinstance(data, dict) else data
    if not isinstance(blocks, list):
        return 2, {"status": "ERROR",
                   "detail": "no `blocks` list in block list JSON"}

    results: List[dict] = []
    conflicts: List[dict] = []
    for entry in blocks:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or entry.get("block") or ""
        declared = entry.get("type") or ""
        derived = classify(name)
        rec = {"name": name, "declared_type": declared,
               "name_derived_type": derived}
        results.append(rec)
        if derived == "UNKNOWN":
            continue  # name un-classifiable → trust declared, just report
        if not declared:
            continue  # nothing declared → not a contradiction
        if _declared_to_canon(declared) != derived:
            rec["conflict"] = True
            conflicts.append(rec)

    if conflicts:
        return 1, {
            "status": "FAIL",
            "blocks_checked": len(results),
            "conflicts": conflicts,
            "detail": (f"{len(conflicts)} block(s) declare a type that "
                       f"contradicts the taxonomy lookup of their name"),
            "blocks": results,
        }
    return 0, {
        "status": "PASS",
        "blocks_checked": len(results),
        "conflicts": [],
        "blocks": results,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="analog_block_type_classify",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("name", nargs="?", default=None,
                    help="single block name to classify")
    ap.add_argument("--block-list", default=None,
                    help="path to analog_block_list.json to verify "
                         "name↔type consistency for every block")
    ap.add_argument("--json", default=None,
                    help="write JSON report to this path")
    args = ap.parse_args(argv)

    if args.block_list:
        rc, report = _check_block_list(Path(args.block_list))
    elif args.name is not None:
        canon = classify(args.name)
        report = {"status": "OK", "name": args.name,
                  "type": canon}
        rc = 0
    else:
        print("usage: analog_block_type_classify.py <name> | "
              "--block-list <path>", file=sys.stderr)
        return 2

    if args.json:
        try:
            outp = Path(args.json)
            outp.parent.mkdir(parents=True, exist_ok=True)
            outp.write_text(json.dumps(report, indent=2,
                                       ensure_ascii=False) + "\n")
        except OSError as exc:
            print(f"error writing --json: {exc}", file=sys.stderr)
            return 2

    if report.get("status") == "OK":
        print(f"[OK] {args.name} -> {report['type']}")
    elif report.get("status") == "PASS":
        print(f"[PASS] analog_block_type_classify: "
              f"{report['blocks_checked']} block(s), all name↔type "
              f"consistent")
    elif report.get("status") == "FAIL":
        for c in report["conflicts"]:
            print(f"  CONFLICT: name={c['name']!r} declared "
                  f"{c['declared_type']!r} but name implies "
                  f"{c['name_derived_type']!r}")
        print(f"[FAIL] analog_block_type_classify: {report['detail']}")
    else:
        print(f"[ERROR] analog_block_type_classify: {report['detail']}",
              file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
