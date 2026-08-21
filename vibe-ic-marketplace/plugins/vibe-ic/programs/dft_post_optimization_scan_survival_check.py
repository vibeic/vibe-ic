#!/usr/bin/env python3
"""dft_post_optimization_scan_survival_check.py — does post-DFT optimization
(Step 12, "resynth / buffering") actually PRESERVE the scan chain Step 11
inserted, or did the netlist it emits quietly lose it?

THE DEFECT THIS CLOSES
-----------------------
Step 12's gate was ``files_exist: [phase2/stage2/synth/post_dft_netlist.v]``
only — satisfied by an empty file, by the PRE-DFT netlist copied over
verbatim, or by a netlist that genuinely carries zero scan cells. Step 13's
LEC (RTL == post-DFT netlist) does NOT catch any of these: scan insertion is
designed to be functionally transparent (scan mode is not exercised in
mission-mode simulation), so a post-DFT netlist with its scan chain silently
dropped is STILL functionally equivalent to the RTL — LEC has nothing to
disagree with. This is a different property than LEC checks, not a
duplicate of it.

WHAT THIS CHECKS, chip- and PDK-AGNOSTIC
-----------------------------------------
Reuses ``fault_atpg_run``'s existing, chip-agnostic DFF-instantiation
detector (the same one ATPG relies on to find the flops it must cut around)
rather than inventing a second, driftable pattern — see
``fault_atpg_run._DFF_INST_RE`` / ``detect_dff_cells``.

FAILs (rc=1) iff any of the three named failure modes is measured:

  1. ``post_dft_netlist.v`` is missing or empty.
  2. ``post_dft_netlist.v`` is byte-identical to the PRE-DFT netlist
     (``phase2/stage2/synth/netlist.v``) — the "pre-DFT netlist copied
     over" substitution named in the flow's own dimension-2 audit.
  3. Step 11's own ``scan_netlist.v`` instantiates at least one DFF-family
     cell (i.e. scan insertion genuinely ran) but ``post_dft_netlist.v``
     instantiates ZERO — the scan chain vanished between Step 11 and
     Step 12.

Deliberately does NOT compare flop COUNTS beyond zero-vs-nonzero: resynthesis
legitimately may retime, balance or otherwise change register count by a
small, benign margin, and a fuzzy percentage threshold would be a second,
driftable definition of "how much loss is too much". The three failure
modes above are the ones actually named as satisfying the old files_exist
gate; this check closes exactly those, no more.

SKIPPED-CONDITION (rc=2), never a silent PASS:
  * ``scan_netlist.v`` (Step 11's own output) is missing — nothing to
    compare survival AGAINST, so failure mode 3 is unmeasurable. This is a
    disclosed skip, not a pass on absence: the caller's condition_files_exist
    on the gate clause is what actually decides whether Step 12 runs this
    check at all (a project with no DFT declares no scan_netlist.v and the
    clause is condition-gated off).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from fault_atpg_run import _DFF_INST_RE  # noqa: E402 — the shared, chip-agnostic detector


def _read(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def _dff_instance_count(netlist_text: str) -> int:
    return sum(1 for _ in _DFF_INST_RE.finditer(netlist_text or ""))


def assess(project: Path) -> dict:
    post_dft = project / "phase2" / "stage2" / "synth" / "post_dft_netlist.v"
    pre_dft = project / "phase2" / "stage2" / "synth" / "netlist.v"
    scan = project / "phase2" / "stage2" / "dft" / "scan_netlist.v"

    if not scan.is_file() or not scan.stat().st_size:
        return {"verdict": "SKIPPED-CONDITION", "rc": 2,
                "reason": "phase2/stage2/dft/scan_netlist.v (Step 11's own "
                          "output) is absent — nothing to measure scan-chain "
                          "survival against"}

    post_text = _read(post_dft)
    if not post_dft.is_file() or not post_text.strip():
        return {"verdict": "FAIL", "rc": 1,
                "reason": "phase2/stage2/synth/post_dft_netlist.v is missing "
                          "or empty"}

    pre_text = _read(pre_dft) if pre_dft.is_file() else None
    if pre_text is not None and post_text == pre_text:
        return {"verdict": "FAIL", "rc": 1,
                "reason": "phase2/stage2/synth/post_dft_netlist.v is "
                          "byte-identical to the PRE-DFT netlist "
                          "(phase2/stage2/synth/netlist.v) — the DFT/scan "
                          "insertion step's output was never actually "
                          "carried forward into this file"}

    scan_dffs = _dff_instance_count(_read(scan))
    post_dffs = _dff_instance_count(post_text)

    if scan_dffs > 0 and post_dffs == 0:
        return {"verdict": "FAIL", "rc": 1,
                "reason": (f"scan_netlist.v instantiates {scan_dffs} "
                           f"DFF-family cell(s) (scan insertion ran), but "
                           f"post_dft_netlist.v instantiates 0 — the scan "
                           f"chain did not survive post-DFT optimization"),
                "scan_netlist_dff_count": scan_dffs,
                "post_dft_netlist_dff_count": post_dffs}

    return {"verdict": "PASS", "rc": 0,
            "reason": (f"post_dft_netlist.v is non-empty, differs from the "
                       f"pre-DFT netlist, and instantiates "
                       f"{post_dffs} DFF-family cell(s) "
                       f"(scan_netlist.v had {scan_dffs})"),
            "scan_netlist_dff_count": scan_dffs,
            "post_dft_netlist_dff_count": post_dffs}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project_dir")
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    result = assess(project)

    if args.json:
        out = project / args.json
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2))

    verdict = result["verdict"]
    print(f"verdict: {verdict}")
    print(f"  {result['reason']}")
    if verdict == "SKIPPED-CONDITION":
        print("SKIPPED-CONDITION: " + result["reason"])
    return result["rc"]


if __name__ == "__main__":
    raise SystemExit(main())
