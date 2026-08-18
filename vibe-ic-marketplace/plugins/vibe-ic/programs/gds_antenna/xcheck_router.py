#!/usr/bin/env python3
"""xcheck_router.py — cross-check the GDS antenna deck against the router's own count.

The deck (``antenna_check.py``) is an INDEPENDENT GDS-geometry count. The router
(OpenROAD ``check_antennas``) produces its own count on the routed DB. A trustworthy
sign-off requires the two independent numbers to AGREE — that is the point of having a
second, geometry-level check at all.

The two engines use different exact models (the deck reports nets-over-limit per metal
layer; the router reports net+pin violations on the routed graph with diode credit), so
the counts are not required to be bit-identical. The HARD cross-check is the
clean/dirty AGREEMENT: if the router says 0, the geometry deck must also say 0, and
vice versa. A disagreement there means one of the two is wrong and MUST be surfaced, not
averaged away. The numeric proximity is reported as advisory.

Pure Python — no KLayout dependency, so it runs anywhere the two report files land.

    xcheck_router.py --deck antenna.json --router antenna.rpt [--json out.json]
    verdict: AGREE (rc 0) / DISAGREE (rc 1) / ERROR (rc 2)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# OpenROAD check_antennas idiom (same regex family as eda_report_audit._check_antenna).
_FOUND_RE = re.compile(r"Found\s+(\d+)\s+(?:net|pin|antenna)\s+violation", re.I)
_PAIR_RE = re.compile(r"(\d+)\s+net\s+violations?,?\s+(\d+)\s+pin\s+violations?", re.I)
_CLEAN_RE = re.compile(r"antenna\s+clean\s*:\s*(YES|NO|TRUE|FALSE)", re.I)


def router_count(report: Path):
    """Return (count, clean_flag) parsed from an OpenROAD-style antenna report."""
    text = report.read_text(errors="replace")
    clean = None
    m = _CLEAN_RE.search(text)
    if m:
        clean = m.group(1).upper() in ("YES", "TRUE")
    found = list(_FOUND_RE.finditer(text))
    if found:
        return sum(int(mm.group(1)) for mm in found), clean
    total = 0
    seen = False
    for mm in _PAIR_RE.finditer(text):
        total += int(mm.group(1)) + int(mm.group(2))
        seen = True
    return (total if seen else None), clean


def deck_count(deck_json: Path):
    d = json.loads(deck_json.read_text())
    return int(d.get("violations", 0)), d.get("verdict")


def cross_check(deck_json: Path, router_rpt: Path):
    dc, dverdict = deck_count(deck_json)
    rc, rclean = router_count(router_rpt)
    router_viol = None
    if rc is not None:
        router_viol = rc
    elif rclean is not None:
        router_viol = 0 if rclean else 1  # clean:YES -> 0, clean:NO -> at least 1
    if router_viol is None:
        return {"verdict": "ERROR",
                "error": "no antenna violation count/clean-status in router report",
                "deck_violations": dc}
    deck_dirty = dc > 0
    router_dirty = router_viol > 0
    agree = deck_dirty == router_dirty
    res = {"verdict": "AGREE" if agree else "DISAGREE",
           "deck_violations": dc, "router_violations": router_viol,
           "deck_verdict": dverdict,
           "clean_agreement": agree}
    if not agree:
        res["detail"] = (f"clean/dirty MISMATCH: geometry deck says "
                         f"{'DIRTY' if deck_dirty else 'CLEAN'} "
                         f"({dc}), router says "
                         f"{'DIRTY' if router_dirty else 'CLEAN'} ({router_viol})")
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description="Cross-check GDS antenna deck vs router.")
    ap.add_argument("--deck", required=True, help="antenna_check.py JSON output")
    ap.add_argument("--router", required=True, help="OpenROAD antenna report")
    ap.add_argument("--json", dest="json_out", default=None)
    ns = ap.parse_args(argv)
    deck, router = Path(ns.deck), Path(ns.router)
    if not deck.is_file() or not router.is_file():
        sys.stderr.write("xcheck_router: --deck and --router must both exist.\n")
        return 2
    res = cross_check(deck, router)
    text = json.dumps(res, indent=2)
    if ns.json_out:
        Path(ns.json_out).write_text(text)
    print(text)
    if res["verdict"] == "ERROR":
        return 2
    return 0 if res["verdict"] == "AGREE" else 1


if __name__ == "__main__":
    sys.exit(main())
