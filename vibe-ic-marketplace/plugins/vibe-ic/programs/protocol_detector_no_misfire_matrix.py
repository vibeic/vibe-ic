#!/usr/bin/env python3
"""Bidirectional protocol-detector no-misfire + gold cross-contamination matrix.

Promoted from benchmark_phase1/_no_misfire_matrix.py (v0.2.13) into a first-class
plugin program. Runs EVERY module-level ``is_<stem>`` detector exported by a
``<stem>_protocol_synth.py`` against EVERY benchmark's content blob and asserts
each detector fires ONLY on its own benchmark (modulo the documented
DERIVED_SIBLING_CROSS_FIRES allowlist).

This single program serves two close-loop purposes via ``--blob``:

  --blob generated   (default) : detector vs each benchmark's generated L1-L3.
  --blob superset              : detector vs input_doc + ALL generated L-docs
                                 (the strictest blob; matches the pytest guard).
  --blob input_doc             : detector vs the raw source spec only.
  --blob gold                  : detector vs each benchmark's claude_extracted
                                 L1-L3 (the GOLD). A FOREIGN detector firing on a
                                 gold flags likely CROSS-CONTAMINATION of that
                                 gold — e.g. the Tier-G batch left SENT content
                                 in the io_link gold and Ethernet content in the
                                 mdio docs, which gated-parity-0 cannot see
                                 (v0.1.89 lesson, applied to benchmark-data
                                 fidelity).

Both DIRECTIONS of cross-fire are covered automatically because every detector
is run against every benchmark: FORWARD (new detector on an existing benchmark)
and REVERSE (existing detector on a new benchmark) are the same matrix.

Exit 0 = clean (only own-fires + allowlisted derived siblings); exit 1 = at
least one un-allowlisted foreign fire (a misfire / contamination).
"""
from __future__ import annotations

import argparse
import glob
import importlib
import json
import sys
from pathlib import Path

PROGRAMS_DIR = Path(__file__).resolve().parent
# repo root: .../vibe-ic-marketplace/plugins/vibe-ic/programs -> up 4
REPO_ROOT = PROGRAMS_DIR.parents[3]
DEFAULT_BP = REPO_ROOT / "benchmark_phase1"

try:
    from protocol_detector_lib import DERIVED_SIBLING_CROSS_FIRES
except Exception:  # pragma: no cover
    DERIVED_SIBLING_CROSS_FIRES = {}

# Gold-blob ONLY: (sub_clause_detector, parent_benchmark) pairs where the
# parent benchmark's spec is a LARGER STANDARD that genuinely CONTAINS the
# sub-clause protocol, so a faithful gold legitimately carries the sub-clause's
# content. This is NOT contamination — it is correct extraction of the bigger
# spec. Distinguished from real contamination (e.g. SENT in the io_link gold)
# by the fact that the parent's gold ic_name names the parent standard and the
# sub-clause appears as a documented clause of it. RUNTIME is unaffected: the
# generated/superset matrix is ALL_PASS because the parent's GENERATED head
# leads with the parent subject, so subject-dominance defers the sub-clause
# detector at dispatch time (no clobber).
ACCEPTABLE_GOLD_SUBCLAUSE_FIRES = {
    # IEEE 802.3 (ethernet / 800G ethernet) genuinely defines MDIO management
    # in Clause 22/45 — the ethernet gold ic_name is literally
    # "IEEE 802.3 ... (Clauses 4 / 22 / 35 / 45)".
    ("mdio", "ethernet"),
    ("mdio", "ethernet_800g"),
    # The ace_chi benchmark's GOLD subject is the ACE coherency protocol itself
    # (its gold carries the full AMBA AXI 5-channel baseline + ACE coherency:
    # ReadShared/ReadUnique/snoop AC-CR-CD, MOESI), so is_ace fires CORRECTLY —
    # this is detection of the gold's true subject, not contamination. In the
    # GENERATED/superset model the ace_chi input_doc is the comprehensive AMBA
    # AXI Protocol Specification, so is_ace's AXI-spec-primary defer (added v0.2.34)
    # correctly suppresses it there; only the ACE-subject gold legitimately fires.
    ("ace", "ace_chi"),
}


def discover_detectors():
    """{stem: callable} for every <stem>_protocol_synth.py exposing is_<stem>."""
    found = {}
    for p in sorted(PROGRAMS_DIR.glob("*_protocol_synth.py")):
        stem = p.name[: -len("_protocol_synth.py")]
        try:
            mod = importlib.import_module(f"{stem}_protocol_synth")
        except Exception:
            continue
        fn = getattr(mod, f"is_{stem}", None)
        if callable(fn):
            found[stem] = fn
    return found


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def blob_for(bp: Path, b: str, source: str) -> str:
    """Build a benchmark's detection blob from the chosen source.

    Mirrors the runner's auto-dispatch ([14e2b/15]) ordering: input_doc FIRST,
    then the generated/gold L-docs, so a subject-dominance head check sees the
    source spec's title exactly as it does at dispatch time.
    """
    parts = []
    idir = bp / b / "phase1" / "input_doc"
    if source in ("input_doc", "superset") and idir.is_dir():
        for f in sorted(idir.glob("*.txt")) + sorted(idir.glob("*.md")):
            parts.append(_read(f))
    docdir_name = "claude_extracted" if source == "gold" else "generated_docs"
    if source != "input_doc":
        gd = bp / b / "phase1" / docdir_name
        names = (sorted(gd.glob("*.json")) if source == "superset"
                 else [gd / n for n in ("L1_DATASHEET.json", "L2_FRS.json",
                                        "L3_CMD_PROTOCOL.json")])
        for f in names:
            if f.is_file():
                parts.append(_read(f))
    return "\n".join(parts)


def run_matrix(bp: Path, source: str):
    detectors = discover_detectors()
    benches = sorted(d.name for d in bp.iterdir()
                     if d.is_dir() and (d / "phase1").is_dir())
    blobs = {b: blob_for(bp, b, source) for b in benches}
    rows, misfires = [], []
    own_fires = set()
    for stem, fn in detectors.items():
        fired = []
        for b in benches:
            if not blobs.get(b):
                continue
            try:
                hit = bool(fn(blobs[b]))
            except Exception:
                hit = False
            if hit:
                if b == stem:
                    own_fires.add(stem)
                elif (stem, b) in DERIVED_SIBLING_CROSS_FIRES:
                    pass  # documented derived-sibling, resolved by synth order
                elif source == "gold" and (stem, b) in ACCEPTABLE_GOLD_SUBCLAUSE_FIRES:
                    pass  # parent standard genuinely contains this sub-clause
                else:
                    fired.append(b)
        if fired:
            misfires.extend((stem, b) for b in fired)
        rows.append({"detector": stem, "own_fire": stem in own_fires,
                     "foreign_fires": fired})
    return detectors, benches, rows, misfires, own_fires


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--blob", choices=["generated", "superset", "input_doc", "gold"],
                    default="generated")
    ap.add_argument("--benchmark-dir", type=Path, default=DEFAULT_BP)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(argv)

    if not args.benchmark_dir.is_dir():
        print(f"ERROR: benchmark dir not found: {args.benchmark_dir}",
              file=sys.stderr)
        return 2
    sys.path.insert(0, str(PROGRAMS_DIR))
    detectors, benches, rows, misfires, own_fires = run_matrix(
        args.benchmark_dir, args.blob)

    label = ("CROSS-CONTAMINATION" if args.blob == "gold" else "no-misfire")
    print(f"[{label}] blob={args.blob}  detectors={len(detectors)}  "
          f"benchmarks={len(benches)}")
    for r in rows:
        if r["foreign_fires"]:
            print(f"  [FAIL] is_{r['detector']}: foreign_fires={r['foreign_fires']}")
    if args.json:
        args.json.write_text(json.dumps(
            {"blob": args.blob, "misfires": misfires, "rows": rows}, indent=2))
    if misfires:
        kind = ("gold cross-contamination" if args.blob == "gold"
                else "detector mis-fire")
        print(f"\n{len(misfires)} {kind} finding(s): {misfires}")
        return 1
    print("\nALL_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
