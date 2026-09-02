#!/usr/bin/env python3
"""analog_topology_behaviour_check.py — "it renders and simulates" is not
"it works", and nothing in this flow measured the difference.

ENFORCEMENT: blocking
    Invoked by `analog_one_shot_runner` after the block's netlist exists,
    and by the acceptance audit. rc 1 refuses the block.

WHY THIS EXISTS, MEASURED
=========================
The A2 topology library's standing claim is that every entry "has been
rendered and simulated end-to-end". For a converter that claim is not the
one that matters. MEASURED (u_hawaii_adc, ihp-sg13g2, 2026-09-02): the
`delta_sigma` entry — a complete CIFB modulator, loop filter + clocked
quantiser + 1-bit feedback DAC — renders, passes every static netlist
check, converges in ngspice, and drives its declared `bit_out` rail to rail
at a bitstream density of 0.51. It also does not convert: sweeping the input
across 0.40 / 0.60 / 0.80 V, against a 0.6 V common mode and a 1.0 V
declared reference span whose ideal densities are 0.30 / 0.50 / 0.70, moved
the measured density by 0.0012. Eight structural arms, one variable at a
time, either sat in that 0.5 limit cycle or latched at a rail.

Every gate downstream of A3 would have passed that block. A5 lays it out, A6
proves the layout matches the netlist, A8 packages it, LVS matches the macro
against the same netlist, and the post-layout LEC compares two views of the
same non-converter. Each of those gates answers its own question correctly.
NONE of them asks whether the circuit does what its own topology says it is
for — and a flow that never asks will sign off a die around a block that
converts nothing, with every light green.

WHAT IT CHECKS
==============
For each declared analog block that has a `topology.json`:

  * no `behaviour_record` in the IR  -> the block is not making a behavioural
    claim; SKIPPED by name, and the verdict is unaffected. Every entry in the
    shipped library except one is in this state, so no other design's block
    changes verdict.
  * `behaviour_record.verified` true -> PASS, and the claim and the
    measurement that supports it are printed, so a reader sees what was
    shown rather than a bare green.
  * `behaviour_record.verified` false -> FAIL, printing the claim, the
    diagnosis and what would close it, VERBATIM from the library entry. The
    gate never restates them: an entry author writes the words a reader acts
    on.

It performs NO simulation. The measurement belongs to whoever authored the
entry, in the entry, with its arms; this gate is the thing that stops the
flow from walking past it. That split is deliberate — a gate that re-measures
would make the record decorative, and a record with no gate is a comment.

Exit codes: 0 PASS (or nothing claims anything, disclosed), 1 FAIL (a block
states a behavioural claim its own author records as not shown), 2
VACUOUS/argument error.
chip-AGNOSTIC: no chip, vendor, PDK or signal-name literal.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

PROGRAMS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROGRAMS_DIR))

import _vacuous_exit as _vx  # noqa: E402
from _atomic_artefact import write_json  # noqa: E402 - vibe-ic#1082

GATE = "analog_topology_behaviour_check"

#: The IR key an entry uses to state what its circuit must be shown to do.
#: Named here rather than imported so this gate can read an IR written by any
#: producer, including one that never loads the A2 library.
BEHAVIOUR_RECORD_KEY = "behaviour_record"

#: Where a block's topology IR is looked for, in order.
_TOPOLOGY_BASES = ("phase3/analog", "phase2/analog")


def _read_json(p: Path) -> Optional[dict]:
    try:
        d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None
    return d if isinstance(d, dict) else None


def topology_ir(project: Path, block: str) -> Optional[dict]:
    """The block's topology IR, from whichever phase directory carries it."""
    for base in _TOPOLOGY_BASES:
        d = _read_json(project / base / block / "topology.json")
        if d is not None:
            return d
    return None


def check_block(project: Path, block: str) -> Dict:
    ir = topology_ir(project, block)
    if ir is None:
        return {"block": block, "claimed": False,
                "reason": "no topology.json for this block"}
    rec = ir.get(BEHAVIOUR_RECORD_KEY)
    if not isinstance(rec, dict):
        return {"block": block, "claimed": False,
                "reason": ("the topology states no behavioural claim "
                           f"(`{BEHAVIOUR_RECORD_KEY}` absent)")}
    return {"block": block, "claimed": True,
            "verified": bool(rec.get("verified")),
            "claim": rec.get("claim"),
            "measured_on": rec.get("measured_on"),
            "how": rec.get("how"),
            "arms": list(rec.get("arms") or []),
            "diagnosis": rec.get("diagnosis"),
            "next": rec.get("next")}


def _print_block(r: Dict) -> None:
    if not r.get("claimed"):
        print(f"  [{r['block']}] SKIP — {r['reason']}")
        return
    if r["verified"]:
        print(f"  [{r['block']}] BEHAVIOUR_DEMONSTRATED")
        print(f"      claim: {r.get('claim')}")
        if r.get("measured_on"):
            print(f"      measured on: {r['measured_on']}")
        if r.get("how"):
            print(f"      how: {r['how']}")
        return
    print(f"  [{r['block']}] BEHAVIOUR_NOT_DEMONSTRATED")
    print(f"      claim: {r.get('claim')}")
    if r.get("measured_on"):
        print(f"      measured on: {r['measured_on']}")
    if r.get("how"):
        print(f"      how: {r['how']}")
    for a in r.get("arms") or []:
        print(f"      arm: {a}")
    if r.get("diagnosis"):
        print(f"      diagnosis: {r['diagnosis']}")
    if r.get("next"):
        print(f"      what would close it: {r['next']}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project")
    ap.add_argument("--block", action="append")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    project = Path(a.project)
    from _analog_a_check_common import load_block_list
    blocks = a.block or (load_block_list(project) or [])
    if not blocks:
        print("VACUOUS: no analog block declared — no topology to read")
        _vx.announce_vacuous(GATE, "no_analog_block_declared")
        return _vx.RC_VACUOUS
    results = [check_block(project, b) for b in blocks]
    for r in results:
        _print_block(r)
    claimed = [r for r in results if r.get("claimed")]
    bad = [r for r in claimed if not r["verified"]]
    if not claimed:
        # NOT a vacuous pass and NOT a defect: no entry in play states a
        # behavioural claim, which is the state every library entry but one
        # is in. Say so, and pass — this gate must never turn "nobody
        # claimed anything" into an alarm.
        print(f"PASS: {len(results)} block(s), none states a behavioural "
              f"claim — nothing for this gate to hold anyone to")
        verdict, rc = "PASS", _vx.RC_PASS
    elif bad:
        print(f"FAIL: {len(bad)}/{len(claimed)} block(s) state a behavioural "
              f"claim their own topology record says is NOT demonstrated")
        verdict, rc = "FAIL", _vx.RC_FAIL
    else:
        print(f"PASS: {len(claimed)}/{len(claimed)} block(s) with a "
              f"behavioural claim have it demonstrated")
        verdict, rc = "PASS", _vx.RC_PASS
    if a.json:
        write_json(a.json, {"gate": GATE, "verdict": verdict,
                            "blocks": results, "rc": rc})
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
