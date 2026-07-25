#!/usr/bin/env python3
"""nvm_program_supply_check.py — Phase-1 gate: a design that intends to PROGRAM
an on-chip non-volatile memory must have a terminal that can carry the
programming supply.

ENFORCEMENT: blocking

Why blocking, and why here
--------------------------
The programming supply of any field-programmable NVM is externally sourced and
above the core rail (see `nvm_program_supply_intent` for the convention and its
corroboration). If the design's boundary has no terminal for it, the design
cannot perform the operation its own RTL is built to perform.

No downstream gate asks this question. The digital logic is well-formed:
it simulates, lints, synthesises, routes, and passes DRC and LVS. Unlike #309
— where the same family of defect eventually manifests as a routing abort —
this one produces a completely clean flow and a green sign-off. The first
observation is at bring-up, on silicon, on an array that will not take a burn.

There is no later gate to defer to, so deferring means never catching it. #306
measured that 62 of 72 gates in this flow can only describe a run afterwards;
adding a 63rd would be pointless. This one blocks.

Escape hatch (the same one #309 uses, from the same field)
----------------------------------------------------------
A design that KNOWS it has this gap declares it:

    L21_POWER_INTENT.fields.hard_macro_supplies:
      - {master: <macro>, pin: <supply pin>, integration_gap: true}

A known, owned gap is disclosure, not silence — and sharing #309's field means
a design that discloses once is disclosed to both gates, which is what keeps
the two from drifting apart.

Verdicts / exit codes
---------------------
    0  PASS               every supply of every instantiated programmable-NVM
                          macro has a boundary terminal or a declared gap
    0  VACUOUS_PASS (rc 2) no programmable-NVM macro to ask about — by far the
                          common case; prints the VACUOUS_PASS sentinel
    0  INCONCLUSIVE       a programmable-NVM macro IS instantiated with
                          programming-control logic, but the design records no
                          supply terminals at its boundary AT ALL, so the
                          question cannot be answered. NOT silent: a named
                          finding is printed and written. Not blocking either,
                          because the actual defect is a missing pinout, which
                          is a different gate's subject.
    1  FAIL               a supply pin with no path in and no declared gap
    2  (also) SKIP        nothing to assess

chip-AGNOSTIC. LEF `USE POWER` grammar, the design's own RTL, and the design's
own boundary inventory. No macro name, no PDK literal, no pin-name allowlist.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import nvm_program_supply_intent as _nps  # noqa: E402

PROGRAM = "nvm_program_supply_check"
VERSION = "1.0.0"

RULE_MISSING = "NVM_PROGRAM_SUPPLY_NO_EXTERNAL_PATH"
RULE_BOUNDARY_UNKNOWN = "NVM_PROGRAM_SUPPLY_BOUNDARY_NOT_STATED"


def audit(project: Path) -> dict:
    rep = _nps.assess(project)

    if rep.get("inconclusive"):
        intent = rep.get("program_intent", {})
        return {
            "verdict": "INCONCLUSIVE",
            "rc": 0,
            "blocking": False,
            "findings": [{
                "severity": "WARNING",
                "rule": RULE_BOUNDARY_UNKNOWN,
                "message": (
                    f"{', '.join(rep['instantiated'])} is a programmable-NVM "
                    f"macro (it declares two or more distinct LEF USE POWER "
                    f"pins) and the RTL carries programming-control logic "
                    f"({', '.join(intent.get('role_categories', []))}), but "
                    f"not one of its supply or ground pins appears in the "
                    f"design's boundary inventory. The inventory records no "
                    f"supply terminals at all, so whether the programming "
                    f"supply has a pin cannot be decided here. State the "
                    f"pinout (L1.pinout / L5.pads / L9.top_level_ports) and "
                    f"this gate becomes decidable."),
            }],
            "assessment": rep,
        }

    if not rep.get("applicable"):
        return {"verdict": "SKIP", "rc": 2, "blocking": False,
                "reason": rep.get("reason", ""), "findings": [],
                "assessment": rep}

    findings = []
    for g in rep.get("gaps", []):
        findings.append({
            "severity": "ERROR",
            "rule": RULE_MISSING,
            "master": g["master"],
            "pin": g["pin"],
            "message": (
                f"{g['master']}/{g['pin']} is a LEF-typed USE POWER pin of a "
                f"programmable non-volatile memory this design instantiates "
                f"AND drives with programming-control logic, but {g['detail']}. "
                f"A programming supply is sourced OUTSIDE the die and sits "
                f"above the core rail, so no on-die rail can produce it: "
                f"without a package pin or a wafer-probe pad the array can "
                f"never be burned, and nothing later in the flow will say so "
                f"— the digital logic is entirely well-formed. Add the "
                f"terminal to the design's boundary, or declare the gap as "
                f"L21.fields.hard_macro_supplies[{{master, pin, "
                f"integration_gap: true}}]."),
        })

    return {
        "verdict": "FAIL" if findings else "PASS",
        "rc": 1 if findings else 0,
        "blocking": True,
        "findings": findings,
        "assessment": rep,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    if not args.project_dir.is_dir():
        print(f"ERROR: not a directory: {args.project_dir}", file=sys.stderr)
        return 1

    rep = audit(args.project_dir.resolve())
    rc = rep.pop("rc")
    rep = {"program": PROGRAM, "version": VERSION, **rep}
    out = json.dumps(rep, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)

    # The one-line human verdict comes FIRST so it survives log truncation.
    if rep["verdict"] == "SKIP":
        print(f"VACUOUS_PASS: {PROGRAM} — {rep.get('reason', '')}")
    else:
        print(f"{PROGRAM}: {rep['verdict']} "
              f"({len(rep.get('findings', []))} finding(s))")
        for f in rep.get("findings", []):
            print(f"  [{f['severity']}] {f['rule']}: {f['message']}")
    print(out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
