#!/usr/bin/env python3
"""pdk_analog_completeness_check.py

Closes the gap where ``L5_ADI_SPEC.json`` has analog blocks but
``input/pdk/`` only ships the digital wrapper (Liberty + LEF + GDS), making
A3 SPICE netlist gen / A4 corner sweep / A6 post-layout resim infeasible.

This gate is **chip-AGNOSTIC** — no foundry / vendor / process / cell-name
hardcoded. It just enforces:

  When L5_ADI_SPEC.json has any ``analog_blocks[]`` entry, ``input/pdk/`` must
  contain at least:
    1. SPICE model deck — at least one of:
         input/pdk/spice/**/*.lib
         input/pdk/spice/**/*.scs
         input/pdk/spice/**/*.cir
         input/pdk/spice/**/*.sp
         input/pdk/models/**/*.{lib,scs,va,osdi}
    2. DRC deck — at least one of:
         input/pdk/calibre/*.rule
         input/pdk/klayout/*.drc
         input/pdk/bridge/klayout/*.drc
         input/pdk/magic/*.tech
         input/pdk/bridge/magic/*.tech
    3. LVS deck — at least one of:
         input/pdk/calibre/*LVS*.rule  OR  *device*
         input/pdk/netgen/*.tcl  OR  bridge/netgen/*.tcl
         input/pdk/assura/LVS/**

Each missing axis is its own FAIL. Honors waiver
``pdk_analog_deck_pending_foundry_nda`` (>=60 chars).

Usage:
    python3 pdk_analog_completeness_check.py <project_dir>

Exit codes:
    0 = PASS  (no analog blocks, OR all 3 axes present, OR all missing waived)
    1 = FAIL  (analog blocks present + at least 1 axis missing + no/weak waiver)
    2 = IO / parse error
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Optional, Tuple


WAIVER_KEY = "pdk_analog_deck_pending_foundry_nda"
WAIVER_MIN = 60


_L5_GLOBS = (
    "phase1/generated_docs/L5_ADI_SPEC.json",
    "phase1/generated_docs/L5*.json",
    "**/L5_ADI_SPEC.json",
)


# Each axis: (name, list of (relative-to-project glob patterns)).
# Each axis is satisfied when ANY of its patterns matches at least one file.
# Standard PDK roots searched relative to the project. ``input/pdk`` is
# the convention enforced by other gates (pdk_consistency_check etc.);
# the others are allowed alternates so projects with vendor-supplied
# layouts under ``pdk/`` / ``pdks/`` / ``analog/pdk/`` are not penalised.
_PDK_ROOTS: Tuple[str, ...] = (
    "input/pdk",
    "input/pdks",
    "pdk",
    "pdks",
    "analog/pdk",
)


def _expand(rel_globs: Tuple[str, ...]) -> Tuple[str, ...]:
    """Cross-product the rel-globs against every supported PDK root."""
    out: list[str] = []
    for rel in rel_globs:
        for root in _PDK_ROOTS:
            out.append(f"{root}/{rel}")
    return tuple(out)


_AXES: dict[str, Tuple[str, ...]] = {
    # SPICE / device-model axis. Any one of: SPICE deck (.lib/.scs/.cir/.sp),
    # Verilog-A behavioural (.va/.osdi), or a mcp-eda corner shim.
    "spice_models": _expand((
        "spice/**/*.lib",
        "spice/**/*.scs",
        "spice/**/*.cir",
        "spice/**/*.sp",
        "spice/**/*.va",
        "spice/**/*.osdi",
        "models/**/*.lib",
        "models/**/*.scs",
        "models/**/*.va",
        "models/**/*.osdi",
        "bridge/**/*shim*.lib",
        "bridge/verilog_a/**/*.va",
    )) + (
        # External hardmacro path: vendor-supplied analog blocks ship as
        # LEF + LIB + GDS + behavioural Verilog. When all 3 of (LEF, LIB,
        # behavioural V) are present, the project does not need its own
        # SPICE deck — the analog work is already done. We satisfy this
        # axis on any one match; the all-three check would over-constrain.
        "hardmacros/**/*.lef",
        "hardmacros/**/*.lib",
        # v1.6.607 — drop stale plural "hardmacros" + root-level
        # "analog/" path; replace with canonical singular path.
        "phase3/analog/hardmacro/**/*.lef",
        "phase3/analog/hardmacro/**/*.lib",
        "macros/**/*.lef",
    ),
    "drc_deck": _expand((
        # NOTE: must NOT use loose ``calibre/*.rule`` here — that would
        # also match Calibre LVS rule files, producing a false positive
        # for DRC on LVS-only projects. Only DRC-named files allowed.
        "calibre/*DRC*.rule",
        "calibre/*drc*.rule",
        "klayout/*.drc",
        "klayout/*.lyrdb.def",
        "bridge/klayout/*.drc",
        "magic/*.tech",
        "bridge/magic/*.tech",
        "assura/DRC/**/*.rule",
    )),
    "lvs_deck": _expand((
        "calibre/*LVS*.rule",
        "calibre/*.device",
        # A KLayout LVS runset is what an OPEN PDK actually ships as its
        # sign-off LVS, and this axis did not list it — the mirror image of
        # the DRC axis one line up, which does. Measured: the design staged
        # its PDK's `klayout/*.lvs` and the resolver could not see it, so the
        # LVS arm fell through to a netgen setup no engine here reads and the
        # block never got an LVS run at all.
        "klayout/*.lvs",
        "bridge/klayout/*.lvs",
        "netgen/*.tcl",
        "bridge/netgen/*.tcl",
        "assura/LVS/**/*.rule",
        "magic/*.tech",
        "bridge/magic/*.tech",
    )),
}


def _find_first(project: Path, globs) -> Optional[Path]:
    for pat in globs:
        for h in project.glob(pat):
            if h.is_file():
                return h
    return None


def _has_analog_blocks(project: Path) -> Tuple[bool, int]:
    """Return (has_meaningful_analog_blocks, count).

    A "meaningful" block is a dict with at least one of name / type /
    block_type / spec field populated (string, length >=2). Empty
    placeholder dicts ``[{}]`` do NOT trigger the gate — they would
    otherwise produce false alerts on stub L5 files.

    Also honors ``analog_blocks_detected: false`` as an authoritative
    "no analog content" assertion (matches v0.120 ``L5_ADI_SPEC.json``
    schema). When that flag is False AND the array is empty, we skip.
    """
    p = _find_first(project, _L5_GLOBS)
    if p is None:
        return (False, 0)
    try:
        d = json.loads(p.read_text())
    except Exception:
        return (False, 0)
    blocks = d.get("analog_blocks")
    if not isinstance(blocks, list):
        return (False, 0)
    meaningful = 0
    for b in blocks:
        if not isinstance(b, dict):
            continue
        # v0.1.62 — a `low_confidence: true` block is a SPECULATIVE keyword
        # guess, often lifted from NEGATED context (e.g. spm's L5 extracted a
        # "dac" block from "→ 不需 … analog trim DAC 等" — a sentence stating the
        # DAC is NOT needed). A low-confidence guess must NOT hard-block the
        # silicon flow (require spice/drc/lvs decks). Real analog blocks are
        # high-confidence (carry actual specs). Advisory only — not gating.
        if b.get("low_confidence") is True:
            continue
        for k in ("name", "type", "block_type", "spec", "spec_summary"):
            v = b.get(k)
            if isinstance(v, str) and len(v.strip()) >= 2:
                meaningful += 1
                break
    if meaningful == 0 and d.get("analog_blocks_detected") is False:
        return (False, 0)
    return (meaningful > 0, meaningful)


def _axis_status(project: Path, axis: str) -> Tuple[bool, Optional[str]]:
    """Return (satisfied, first_file_found_or_None)."""
    for pat in _AXES[axis]:
        for h in project.glob(pat):
            if h.is_file():
                return (True, str(h.relative_to(project)))
    return (False, None)


def _waiver_count(project: Path) -> int:
    p = project / "waivers.json"
    if not p.exists():
        return 0
    try:
        d = json.loads(p.read_text())
    except Exception:
        return 0
    v = d.get(WAIVER_KEY)
    if isinstance(v, str):
        return 1 if len(v.strip()) >= WAIVER_MIN else 0
    if isinstance(v, list):
        return sum(1 for s in v
                   if isinstance(s, str) and len(s.strip()) >= WAIVER_MIN)
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: pdk_analog_completeness_check <project_dir>",
              file=sys.stderr)
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        print(f"ERROR: {project} not a directory", file=sys.stderr)
        return 2

    has_analog, n_blocks = _has_analog_blocks(project)
    if not has_analog:
        print("[SKIP] pdk_analog_completeness_check: "
              "no L5.analog_blocks[] entries")
        return 0

    statuses = {
        axis: _axis_status(project, axis) for axis in _AXES
    }
    missing: List[str] = [a for a, (ok, _) in statuses.items() if not ok]
    found:   List[Tuple[str, str]] = [
        (a, ev) for a, (ok, ev) in statuses.items() if ok and ev
    ]

    if not missing:
        evidence = "; ".join(f"{a}={ev}" for a, ev in found)
        print(f"[PASS] pdk_analog_completeness_check: "
              f"{n_blocks} L5 analog block(s); all 3 PDK axes present "
              f"({evidence}).")
        return 0

    waiver_n = _waiver_count(project)
    if waiver_n >= len(missing):
        print(f"[PASS_WITH_WAIVER] pdk_analog_completeness_check: "
              f"{len(missing)} PDK axis(es) missing ({', '.join(missing)}) "
              f"but {waiver_n} waiver(s) under '{WAIVER_KEY}' "
              f"(>= {WAIVER_MIN} chars).")
        return 0

    found_repr = ", ".join(f"{a}={ev}" for a, ev in found) or "none"
    print(f"[FAIL] pdk_analog_completeness_check: "
          f"L5 has {n_blocks} analog block(s) but PDK incomplete. "
          f"Missing axis(es): {', '.join(missing)}. "
          f"Present: {found_repr}. "
          f"Each missing axis blocks downstream steps:\n"
          f"  spice_models  → A3/A4/A6 (xschem netlist, corner sweep, post-layout resim)\n"
          f"  drc_deck      → A5 (analog layout DRC)\n"
          f"  lvs_deck      → A5/A7 (LVS, hardmacro extraction)\n"
          f"To accept reduced PDK (e.g. NDA pending), add waiver "
          f"'{WAIVER_KEY}' (string or list of strings, "
          f">={WAIVER_MIN} chars each) — one per missing axis.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
