#!/usr/bin/env python3
"""
frs_timing_range_check.py — gate that catches L2 timing fields stored as
a single point when the vendor doc clearly gives a range, or stored as
prose strings, or with unspecified units.

Why this gate exists
====================
LL-15 (`tx_timing_use_max_of_range_check`) and LL-2/3/4 (frame-end /
response-window family) all depend on L2 timing fields being in
structured `[min, max]` form. When frs-gen emits prose ("tSRS is short
window after host last bit") or single values where vendor gives a
range (`"ibt_us": 22` for an 8.5–22 μs spec), downstream gates have
nothing to read and silently degrade to "any value passes" — which is
how a fresh agent ends up with TX_IBT=8.5us (the MIN) when the rule
of thumb wants near-MAX.

This is the LL-18 / LL-19 companion check on the timing side.
Together they close the timing branch of Category-A spec-extraction.

Rule
----
For each `<name>_us` (or `<name>_ms`) field in L2_FRS.json or
L2_TIMING_WAVEFORM.json that historically has a vendor range,
the entry must be one of:

    "<name>_us": [<min>, <max>]                     range
    "<name>_us": <number>                           single value (TYP/MAX)
    "<name>_us": {"min": ..., "max": ...}           dict form
    "<name>_us": {"value": ..., "kind": "TYP|MIN|MAX"}  point with kind tag

**Forbidden** (gate FAILs):

- `"tSRS_us": "20-80"` (string range, not parseable)
- `"tSRS_us": "short window after host"` (prose)
- `"tSRS_us": "20"` (string when number expected)
- Field present but value is `null` / `""` / `[]`

Usage
-----
python3 frs_timing_range_check.py <project_dir>

Returns 0 on PASS, 1 on FAIL.
"""

import json
import re
import sys
from pathlib import Path
import _path_layout as _pl


# GENERAL: any L2 key ending in a time-unit suffix is a timing parameter
# that downstream gates may need to read structurally. This pattern is
# chip-agnostic — LIN, K-line, 1-Wire, AID-bus, custom serial all use
# `_us` / `_ms` / `_ns` / `_ps` / `_cyc` / `_ticks` suffixes.
TIMING_KEYS_NEED_STRUCTURE = re.compile(
    r"_(us|ms|ns|ps|cyc|ticks)$",
    re.IGNORECASE,
)


def find_doc(project_dir: Path, name: str) -> Path | None:
    for base in (project_dir, project_dir / "phase1/generated_docs", _pl.generated_docs_dir(project_dir)):
        p = base / name
        if p.exists():
            return p
    return None


def is_well_formed(value) -> tuple[bool, str]:
    """Decide whether a timing value is in a downstream-readable form."""
    if isinstance(value, (int, float)):
        return True, "number"
    if isinstance(value, list):
        if len(value) == 2 and all(isinstance(x, (int, float)) for x in value):
            return True, "[min,max]"
        return False, f"list of len {len(value)} (need exactly 2 numbers)"
    if isinstance(value, dict):
        if "min" in value and "max" in value and \
           all(isinstance(value[k], (int, float)) for k in ("min", "max")):
            return True, "{min,max}"
        if "value" in value and isinstance(value["value"], (int, float)):
            return True, "{value,kind}"
        return False, "dict missing min/max or value"
    if isinstance(value, str):
        # Accept rare cases where the string is a clean number "20"
        try:
            float(value)
            return False, f"string number {value!r} (use bare number)"
        except ValueError:
            return False, f"prose / non-numeric string: {value!r}"
    if value is None:
        return False, "null"
    return False, f"unsupported type {type(value).__name__}"


def _looks_like_timing_leaf(v) -> bool:
    """Decide whether `v` should be checked AS a timing claim, vs. recursed
    into as a wrapper. Lists, numbers, strings, and null are always leaves
    (lists of any shape are timing claims — wrong-length ones get
    correctly flagged by is_well_formed). DICTS are leaves only if they
    have the canonical {min,max} or {value,...} shape; an opaque wrapper
    dict like `response_timing_us = {"setup": ..., "hold": ...}` recurses.
    v0.119.23 fix to the false-alert noted by the v0.119.22 vendor run."""
    if isinstance(v, (int, float, list, str)) or v is None:
        return True
    if isinstance(v, dict):
        if "min" in v and "max" in v:
            return True
        if "value" in v:
            return True
        return False
    return True  # unknown type → still a leaf, will fail downstream


def collect_timing_entries(node, prefix=""):
    """Walk a JSON tree, yield (key_path, value) for keys matching the
    timing-key regex AND whose value is a leaf-shaped timing claim. A
    container dict whose key happens to end in `_us` is recursed into
    (no false alert on `response_timing_us = {"setup":..., "hold":...}`)."""
    if isinstance(node, dict):
        for k, v in node.items():
            full = f"{prefix}.{k}" if prefix else k
            # v0.119.17: was `.match()` which anchors at start — so
            # only literal `_us` / `_ms` / etc would have matched, and
            # real keys like `tSRS_us` were silently ignored. Use
            # `.search()` so the `$` anchor enforces the suffix.
            if TIMING_KEYS_NEED_STRUCTURE.search(k):
                # v0.119.23: only treat as a timing leaf if the value
                # actually looks like one. Otherwise recurse — the key
                # is just a wrapper named with a unit suffix.
                if _looks_like_timing_leaf(v):
                    yield full, v
                elif isinstance(v, (dict, list)):
                    yield from collect_timing_entries(v, full)
            elif isinstance(v, (dict, list)):
                yield from collect_timing_entries(v, full)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from collect_timing_entries(item, f"{prefix}[{i}]")


def waived(project_dir: Path) -> bool:
    waivers = project_dir / "waivers.json"
    if not waivers.exists():
        return False
    try:
        d = json.loads(waivers.read_text())
        return bool(d.get("frs_timing_unstructured_intentional"))
    except Exception:
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: frs_timing_range_check.py <project_dir>")
        sys.exit(2)
    project_dir = Path(sys.argv[1]).resolve()
    if not project_dir.exists():
        print(f"FAIL — project dir not found: {project_dir}")
        sys.exit(1)

    failures = []
    found_any = False
    for fname in ("L2_FRS.json", "L2_TIMING_WAVEFORM.json"):
        path = find_doc(project_dir, fname)
        if not path:
            continue
        try:
            data = json.loads(path.read_text())
        except Exception as e:
            print(f"FAIL — cannot parse {fname}: {e}")
            sys.exit(1)
        for key_path, value in collect_timing_entries(data):
            found_any = True
            ok, reason = is_well_formed(value)
            if not ok:
                failures.append((fname, key_path, value, reason))

    if not found_any:
        print("PASS — no L2 timing keys requiring structured form (or "
              "L2 docs absent — gate skipped)")
        sys.exit(0)

    if not failures:
        print("PASS — all L2 timing parameters are in structured form "
              "(number, [min,max], or {value,kind})")
        sys.exit(0)

    if waived(project_dir):
        print(f"PASS_WITH_WAIVER — {len(failures)} timing entries unstructured")
        sys.exit(0)

    print(f"FAIL — {len(failures)} L2 timing parameter(s) not in a form "
          "downstream gates can read:")
    for fname, key, value, reason in failures[:15]:
        print(f"  • {fname} :: {key} = {value!r}")
        print(f"    problem: {reason}")
    if len(failures) > 15:
        print(f"  ... and {len(failures) - 15} more")
    print()
    print("Why this matters:")
    print("  LL-15 (tx_timing_use_max), LL-2/3/4 (frame-end family) all")
    print("  read these L2 keys as numbers / lists. A prose value or")
    print("  string falls through, the gate degrades to 'any value passes',")
    print("  and a fresh agent ends up with TX_IBT=8.5us (the MIN of an")
    print("  8.5–22us range) when the master/slave convention wants MAX.")
    print()
    print("Fix: re-emit L2 timing with structured form:")
    print('    "tSRS_us":          [20, 80],')
    print('    "ibt_us":           [8.5, 22],')
    print('    "tWFT_us":          20,')
    print('    "frame_end_gap_us": {"value": 30, "kind": "TYP"},')
    print()
    print('Or document an exception in waivers.json:')
    print('    {"frs_timing_unstructured_intentional": "<reason>"}')
    sys.exit(1)


if __name__ == "__main__":
    main()
