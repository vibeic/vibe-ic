#!/usr/bin/env python3
"""sta_assumed_clock_disclosure_check.py — a timing sign-off that was measured
against a clock the DESIGN NEVER STATED must say so, in the record.

THE DEFECT (measured, vibe-ic#2091, opentitan_aes x sky130A)
============================================================
The input states no target clock period for the sky130A build.  The run signed
off post-route timing against 10 ns anyway and reported WNS -42.140 ns.  Every
artefact of that sign-off — the SDC, the STA reports, the corner record — is
phrased as a verdict about a specification.  None of them contains a line
saying the specification does not exist.

That is not a timing bug; it is a PROVENANCE bug with a timing consequence.
A reader cannot tell "this design missed its target" from "this design was
never given a target and the flow supplied one".  The two demand opposite
actions: the first is a closure problem, the second is a Phase-1 question.

WHAT THIS GATE ASSERTS
======================
When `clock_target_provenance` reports ``assumed: true`` for this run, the
post-route sign-off record must carry BOTH:

  1. a machine-readable ``clock_period_assumed: true``, so a downstream
     consumer can branch on it without parsing English; and
  2. the disclosure SENTENCE — `clock_target_provenance.ASSUMED_DISCLOSURE`,
     imported, never re-typed here, so the emitter and this checker cannot
     drift into asserting different strings.

Both, deliberately.  A flag with no sentence is invisible in every report a
human reads; a sentence with no flag cannot be enforced anywhere else.

WHAT IT DOES NOT DO
===================
It never inspects slack, never compares a period against anything, and never
turns a timing FAIL into a PASS or the reverse.  A run whose period IS design-
owned passes this gate unconditionally — the gate has an opinion about
disclosure only.

EXIT CODES
==========
  0  PASS       — either the period is design-owned, or it is assumed AND
                  fully disclosed.
  1  FAIL       — the period is assumed and the record does not disclose it.
  2  NOT CHECKED— no provenance report and/or no sign-off record on disk.
                  Absence of an input is NOT a pass (vibe-ic#1140): a gate that
                  reports 0 on an empty project certifies nothing.

STEP 23 ON THE TOOL (F15)
=========================
When step 23 runs `librelane` or `dual`, the sign-off is STAPostPNR's, and its
record (`librelane_signoff.SIGNOFF_RECORD`, bound to the tool state it names)
is one of the records that must disclose an assumed period; the records the
step's other gates write still must too. A tool sign-off that cannot be read
(`librelane_signoff.step23_tool_arm`) REFUSES (rc 1): the disclosure is about
a sign-off, and an unreadable sign-off is not one that needed no disclosure.

Chip / PDK-AGNOSTIC: no chip, vendor, PDK or library literal appears here.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _atomic_artefact import write_text as atomic_write_text  # noqa: E402
import _gate_authorship as _ga
# The paths and the sentence come from the WRITER, never re-typed here: a
# checker that spells its subject itself can drift into asserting about a file
# nobody writes and pass forever.
from clock_target_provenance import (  # noqa: E402
    ASSUMED_DISCLOSURE, PROVENANCE_REL as _PROVENANCE_REL,
    SIGNOFF_RELS as _SIGNOFF_RELS)
import librelane_signoff as _ls  # noqa: E402 — step 23 on the tool (F15)
from librelane_contract import Refusal  # noqa: E402


def _load(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(errors="replace"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def check(project: Path) -> Dict[str, object]:
    rep: Dict[str, object] = {
        "program": "sta_assumed_clock_disclosure_check",
        "project": str(project),
        "verdict": "NOT_CHECKED",
        "assumed": None,
        "provenance": None,
        "signoff_records": [],
        "missing": [],
        "reason": "",
    }
    try:
        arm = _ls.step23_tool_arm(project)
    except Refusal as exc:
        rep["verdict"] = "REFUSED"
        rep["refusal"] = exc.code
        rep["reason"] = (f"step 23 runs on the tool and its sign-off cannot be "
                         f"read: {exc}")
        return rep
    rels = _SIGNOFF_RELS + ((_ls.SIGNOFF_RECORD,) if arm is not None else ())
    if arm is not None:
        rep["basis"] = _ls.tool_arm_basis(arm)
    prov_path = project / _PROVENANCE_REL
    prov = _load(prov_path)
    if prov is None:
        rep["reason"] = (f"NOT CHECKED — no readable {_PROVENANCE_REL}; this "
                         "gate has no input, which is not a pass")
        return rep
    rep["provenance"] = str(prov_path)
    rep["assumed"] = bool(prov.get("assumed"))
    if not prov.get("assumed"):
        rep["verdict"] = "PASS"
        rep["reason"] = (
            f"the clock period is design-owned (tier '{prov.get('tier')}'"
            + (f" at {prov.get('cite')}" if prov.get("cite") else "")
            + "); nothing to disclose")
        return rep

    present: List[Path] = [project / r for r in rels
                           if (project / r).is_file()]
    rep["signoff_records"] = [str(p) for p in present]
    if not present:
        rep["reason"] = ("NOT CHECKED — the period is ASSUMED but no "
                         "post-route sign-off record exists to carry the "
                         "disclosure; nothing was signed off")
        return rep

    missing: List[str] = []
    for p in present:
        data = _load(p)
        blob = p.read_text(errors="replace")
        if not (isinstance(data, dict) and data.get("clock_period_assumed") is True):
            missing.append(f"{p}: no machine-readable clock_period_assumed=true")
        if ASSUMED_DISCLOSURE not in blob:
            missing.append(f"{p}: the disclosure sentence is absent "
                           f"({ASSUMED_DISCLOSURE!r})")
    rep["missing"] = missing
    if missing:
        rep["verdict"] = "FAIL"
        rep["reason"] = (
            "the run signed off timing against a period the design never "
            f"stated ({prov.get('period_ns')} ns, tier "
            f"'{prov.get('tier')}') and the sign-off record does not say so: "
            + "; ".join(missing))
        return rep
    rep["verdict"] = "PASS"
    rep["reason"] = ("the period is ASSUMED and every sign-off record on disk "
                     "declares it as an assumption")
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="A timing sign-off measured against an ASSUMED clock "
                    "period must declare the assumption in its record.")
    ap.add_argument("project")
    ap.add_argument("--json", help="write the structured report here")
    args = ap.parse_args(argv)
    rep = check(Path(args.project))
    if args.json:
        atomic_write_text(Path(args.json), json.dumps(_ga.stamp(rep), indent=2) + "\n")
    print(f"[{rep['verdict']}] sta_assumed_clock_disclosure_check — "
          f"{rep['reason']}")
    print(json.dumps(rep, indent=2))
    return {"PASS": 0, "FAIL": 1, "REFUSED": 1}.get(str(rep["verdict"]), 2)


if __name__ == "__main__":
    sys.exit(main())
