#!/usr/bin/env python3
"""
tx_timing_use_max_of_range_check.py — structural-RTL gate that catches
"TX inter-byte gap is too short" errors.

Why this gate exists
====================
For half-duplex protocol ICs, the chip's TX inter-byte gap (IBT) must
give the master enough time to re-arm its bit receiver between
incoming bytes. A universal rule of thumb across half-duplex serial
protocols (Apple Lightning ID-bus, K-line, LIN, etc.):

    IBT_chip ≥ tSRS_min × 0.5

i.e. the chip-side inter-byte gap should be at least half the master's
spec'd minimum response window. Anything significantly shorter and
the master loses byte alignment on real silicon, even though byte-
level sim passes.

A common fresh-agent failure: the agent confuses IBT with the host's
BR threshold (e.g. "BR_max = 9.4 us, so IBT must be < 9.4 us" — wrong;
BR is a LOW pulse, IBT is a HIGH gap, they share no constraint), and
picks IBT ≈ 8 us. Result: BFM 12/12 PASS, <half-duplex-tester> connect_test FAIL.

This gate scans L8_RTL_CONSTANTS.json for TX_IBT* (or similar inter-
byte timing) and a master-recovery reference (tSRS, tWFT, tRECOVERY,
etc.). If IBT < 0.5 × master-recovery-min, FAIL with a fix template.

The rule is GENERAL — chip-agnostic. It applies to any half-duplex
protocol IC where L8 captures both IBT and a master-recovery
parameter.

Usage
-----
python3 tx_timing_use_max_of_range_check.py <project_dir>

Honors waivers.json with key "tx_ibt_short_intentional".
Returns 0 on PASS, 1 on FAIL.
"""

import json
import re
import sys
from pathlib import Path
import _path_layout as _pl


def find_l_jsons(project_dir: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for base in [project_dir, project_dir / "phase1/generated_docs", _pl.generated_docs_dir(project_dir)]:
        if not base.exists():
            continue
        for p in base.glob("L*.json"):
            found.setdefault(p.name, p)
    return found


def load_json(path: Path) -> dict:
    if not path or not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def is_half_duplex(l2: dict, l3: dict, l8: dict) -> bool:
    if l3.get("command_table"):
        return True
    keys = ("tSRS_us", "ibt_us", "tSRS_min_us", "tSRS_max_us",
            "frame_end_gap_us")
    for d in (l2, l8):
        if any(_search_key(d, k) is not None for k in keys):
            return True
    return False


def _search_key(node, target_key_lower: str):
    """Recursively find any value whose dict-key (case-insensitive) matches."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k.lower() == target_key_lower.lower():
                return v
            r = _search_key(v, target_key_lower)
            if r is not None:
                return r
    elif isinstance(node, list):
        for item in node:
            r = _search_key(item, target_key_lower)
            if r is not None:
                return r
    return None


def find_us_value(node, name_fragment: str, value_field: str = "physical_value_us"):
    """
    Walk node looking for entries that look like
        {"name": "<contains name_fragment>", "physical_value_us": X}
    Return X (float) of the first match, else None.
    """
    if isinstance(node, dict):
        # Match entry directly
        nm = str(node.get("name", "")).lower()
        if name_fragment.lower() in nm and isinstance(
                node.get(value_field), (int, float)):
            return float(node[value_field])
        for v in node.values():
            r = find_us_value(v, name_fragment, value_field)
            if r is not None:
                return r
    elif isinstance(node, list):
        for item in node:
            r = find_us_value(item, name_fragment, value_field)
            if r is not None:
                return r
    return None


def _direct_us_key(node: dict, fragment: str):
    """v0.119.27: walk a JSON tree looking for any dict key that ends in
    `_us` AND contains `fragment` (case-insensitive). Returns the
    numeric value (number, [min,max]→min, {min,max}→min). Closes the
    schema-mismatch vendor-benchmark gap where L2 stored
    `tIBT_us: 22.7` directly instead of as a `name`/`physical_value_us`
    record.

    v0.119.28 docstring clarification — recursion semantics:

    The walk is **fully recursive** through nested dicts (depth-first,
    first-match wins). It does NOT recurse into list items, only into
    dict values. So a value buried at any depth (`a.b.c.tIBT_us = 22`)
    will be found, but `a.b[0].tIBT_us = 22` will NOT.

    Lists of numbers DO match at the leaf level (`tIBT_us: [8.5, 22]`
    → 8.5), but a list of records (`timing_table: [{name: tIBT,
    value_us: 22}]`) is opaque to this helper. For that schema, the
    higher-level `find_l2_min_us(... "table")` path handles the lookup
    instead. Callers extending L2 with deeper nesting should either
    (a) place timing leaves in dict keys ending `_us`, OR (b) use the
    canonical `name`/`physical_value_us` record form which goes
    through `find_l2_min_us`."""
    if not isinstance(node, dict):
        return None
    target = fragment.lower()
    for k, v in node.items():
        if not isinstance(k, str):
            continue
        if not k.lower().endswith("_us"):
            continue
        if target not in k.lower():
            continue
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, list) and len(v) == 2 \
           and all(isinstance(x, (int, float)) for x in v):
            return float(min(v))
        if isinstance(v, dict) and isinstance(v.get("min"), (int, float)):
            return float(v["min"])
    # Depth-first recursion into nested dict values (no depth limit).
    for v in node.values():
        if isinstance(v, dict):
            r = _direct_us_key(v, fragment)
            if r is not None:
                return r
    return None


def find_pkg_const(project_dir: Path, name_fragment: str):
    """
    Scan rtl/*.sv localparams for any constant whose name contains
    `name_fragment` (case-insensitive). Return (const_name, ticks, comment)
    of the first match.
    """
    # v0.119.27: type qualifier is OPTIONAL — `localparam TIBT_TICKS = 1135;`
    # is valid SystemVerilog (defaults to logic [31:0]), and the v0.119.25
    # vendor run wrote constants in that form. Earlier required-type regex
    # silently missed them and the gate fell back to L8/L2 → wrong values.
    pat = re.compile(
        r"localparam\s+"
        r"(?:(?:int|integer|byte|shortint|longint|logic\s*\[\d+:\d+\]|"
        r"reg\s*\[\d+:\d+\]|bit\s*\[\d+:\d+\])\s+)?"
        r"(\w+)"
        r"\s*=\s*(\d+)\s*;([^\n]*)",
        re.IGNORECASE,
    )
    rtl_dir = _pl.rtl_dir(project_dir)
    if not rtl_dir.exists():
        return None
    for p in sorted(list(rtl_dir.glob("*.sv")) + list(rtl_dir.glob("*.v"))):
        try:
            src = p.read_text()
        except Exception:
            continue
        for m in pat.finditer(src):
            n = m.group(1)
            if name_fragment.lower() in n.lower():
                return n, int(m.group(2)), m.group(3).lower()
    return None


def waived(project_dir: Path) -> bool:
    waivers = project_dir / "waivers.json"
    if not waivers.exists():
        return False
    try:
        d = json.loads(waivers.read_text())
        return bool(d.get("tx_ibt_short_intentional"))
    except Exception:
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: tx_timing_use_max_of_range_check.py <project_dir>")
        sys.exit(2)

    project_dir = Path(sys.argv[1]).resolve()
    if not project_dir.exists():
        print(f"FAIL — project dir not found: {project_dir}")
        sys.exit(1)

    l_jsons = find_l_jsons(project_dir)
    l2 = load_json(l_jsons.get("L2_FRS.json", Path()))
    l3 = load_json(l_jsons.get("L3_CMD_PROTOCOL.json", Path()))
    l8 = load_json(l_jsons.get("L8_RTL_CONSTANTS.json", Path()))

    if not is_half_duplex(l2, l3, l8):
        print("PASS — project not half-duplex (gate not applicable)")
        sys.exit(0)

    # The actual silicon value is whatever the rtl/*.sv localparams
    # encode (that is what Quartus / iverilog will compile). L8 is the
    # spec doc — it can disagree with rtl/ and the rtl/ wins for real
    # behavior. So we read the pkg.sv first and only fall back to L8
    # if the constant cannot be located in rtl/.
    def from_pkg(fragment):
        pkg = find_pkg_const(project_dir, fragment)
        if not pkg:
            return None
        # Prefer the comment's microsecond value (e.g. "// 22.7 us"),
        # since the localparam is in clock ticks and we'd need the
        # exact clock period to convert. The agent always writes the
        # us value alongside.
        m = re.search(r"([\d.]+)\s*us", pkg[2])
        return float(m.group(1)) if m else None

    # Prefer the TX-prefixed constant (it's the chip-TX value, not the
    # spec's RX-side accept-range). Fall back to plain IBT only if no
    # TX_-prefixed one exists. v0.119.27: also accept direct `_us`
    # keys in L2 (e.g. `tIBT_us`, `tSRS_us`) since real-world L2 docs
    # often store timing as flat keys, not as nested `name`/
    # `physical_value_us` records.
    ibt_us = (from_pkg("TX_IBT") or from_pkg("IBT") or
              find_us_value(l8, "ibt") or
              find_us_value(l8, "inter_byte") or
              _direct_us_key(l2, "ibt") or
              _direct_us_key(l8, "ibt"))
    tsrs_us = (from_pkg("TSRS_MIN") or from_pkg("TSRS") or
               find_us_value(l8, "tsrs") or
               find_us_value(l8, "tWFT") or
               find_us_value(l8, "tWAKE") or
               find_us_value(l8, "recovery") or
               _direct_us_key(l2, "tsrs") or
               _direct_us_key(l8, "tsrs"))

    if ibt_us is None or tsrs_us is None:
        print("PASS — could not locate IBT and tSRS reference values "
              "(gate skipped)")
        sys.exit(0)

    threshold = tsrs_us * 0.5
    if ibt_us >= threshold:
        print(f"PASS — IBT={ibt_us:.2f}us ≥ 0.5×tSRS_min={threshold:.2f}us")
        sys.exit(0)

    if waived(project_dir):
        print(f"PASS_WITH_WAIVER — IBT={ibt_us:.2f}us < threshold "
              f"{threshold:.2f}us but waiver set")
        sys.exit(0)

    print(f"FAIL — chip TX inter-byte gap (IBT={ibt_us:.2f}us) is too "
          "short for the master's recovery window")
    print(f"  L8 reports tSRS_min ≈ {tsrs_us:.2f}us;")
    print(f"  rule of thumb: IBT_chip ≥ 0.5×tSRS_min "
          f"= {threshold:.2f}us")
    print()
    pkg = find_pkg_const(project_dir, "IBT")
    if pkg and re.search(r"\bbr\b|host\s+br|9\.4|18\.4", pkg[2]):
        print("  NOTE: the localparam comment in rtl/ suggests the agent")
        print("  derived IBT from the BR threshold. IBT and BR are")
        print("  different parameters — they share no constraint.")
        print(f"  Comment was: '{pkg[2].strip()}'")
        print()
    print("Why this matters:")
    print("  Half-duplex protocol convention: between two response bytes,")
    print("  the chip must give the master at least ~half the spec'd")
    print("  master-recovery time so the master can re-arm its bit")
    print("  receiver. With IBT << tSRS_min/2, the master loses byte")
    print("  alignment on real silicon. Symptom: BFM passes byte-exact,")
    print("  HW connect-test silently FAILs, scope shows correct bit")
    print("  pattern but the master never recognises the frame.")
    print()
    print("Fix: regenerate L8 setting the inter-byte gap field to "
          f"≥ {threshold:.2f}us. Or document an exception in waivers.json:")
    print('    {"tx_ibt_short_intentional": "<reason>"}')
    sys.exit(1)


if __name__ == "__main__":
    main()
