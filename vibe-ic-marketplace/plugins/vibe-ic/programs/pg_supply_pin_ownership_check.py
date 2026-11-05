#!/usr/bin/env python3
"""pg_supply_pin_ownership_check.py — every supply pin of every instance sits
on a DECLARED supply net of its own kind, read back from the DEF that ships.

THE DEFECT (TF24, measured). `step_signoff_spef_repair` re-opens `routed.def`
in a FRESH OpenROAD session, removes the fillers, runs `repair_design` /
`repair_timing -setup` / `repair_timing -hold`, re-routes, re-fills and writes
`routed_repaired.def`, which the step then PROMOTES over `routed.def`. The
PDN's `add_global_connection` rules are SESSION STATE: a DEF does not carry
them, so the fresh session had none, and `global_connect` never ran in it.
Every instance that session created kept its POWER/GROUND terminals on no net.

    spm x gf180mcuD, vibeic-eda 0.3.79, pure direct flow (lane mig98 arm D):
      routed_base_prerepair.def  VDD ( * VNW ) ( * VDD ) ( * DVDD ) — wildcards,
                                 every instance owned
      routed_repaired.def        VDD ( * DVDD ) + 13,045 explicit terminals;
                                 16 inserted `hold*` buffers and every
                                 re-inserted filler own NO supply terminal

and the LibreLane Netgen LVS on that DEF failed with 4 unmatched nets per such
buffer. A net pointer is what LVS netlists the cell's supply from, so this is a
real LVS and silicon defect, not bookkeeping.

WHAT THIS JUDGES. Nothing but the DEF and the LEFs that define its masters:

  * a pin is a SUPPLY PIN when its master's LEF types it `USE POWER` or
    `USE GROUND`;
  * a net is a DECLARED SUPPLY NET when the DEF itself types it `+ USE POWER`
    or `+ USE GROUND` (SPECIALNETS or NETS);
  * a supply pin is OWNED by the net that names it explicitly `( inst pin )`,
    else by the net that names its pin wildcard `( * pin )` — DEF's own rule;
  * PASS iff every supply pin of every instance is owned by a declared supply
    net OF THE SAME KIND (a POWER pin on a GROUND net is a short, not a pass).

Verdicts: PASS; FAIL with `PG_SUPPLY_PIN_OFF_SUPPLY_NET` (at least one supply
pin proven off its supply); NOT_MEASURED with
`PG_SUPPLY_OWNERSHIP_UNMEASURED` (no instance, no declared supply net, or an
instance whose master no LEF given defines — an unread master is unmeasured,
never clean). A proven FAIL outranks an unmeasured remainder.

SCOPE, stated so it cannot be misquoted: this is NET OWNERSHIP read from the
DEF, the same predicate `_build_pg_reconnect_tcl`'s in-session audit uses. It
is not a conductor test; whether metal reaches the pin is extraction's
question.

chip-AGNOSTIC: no PDK, cell, net or design literal. Every name comes from the
DEF and the LEFs handed in.

USAGE
    pg_supply_pin_ownership_check.py DEF --lef LEF [--lef LEF ...] [--json OUT]
    exit 0 = PASS, 1 = FAIL, 2 = NOT_MEASURED
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _atomic_artefact import write_json as _atomic_write_json  # noqa: E402

GATE = "pg_supply_pin_ownership_check"

#: The refusal: a supply pin proven not to sit on a declared supply net of
#: its own kind.
REFUSE_CODE = "PG_SUPPLY_PIN_OFF_SUPPLY_NET"
#: The honest non-answer: the population could not be judged.
UNMEASURED_CODE = "PG_SUPPLY_OWNERSHIP_UNMEASURED"

_SUPPLY_USES = ("POWER", "GROUND")
_EXAMPLES = 20

_LEF_MACRO_RE = re.compile(r"^\s*MACRO\s+(\S+)", re.M)
_LEF_PIN_RE = re.compile(r"^\s*PIN\s+(\S+)", re.M)


def parse_lef_supply_pins(lef_text: str) -> Dict[str, Dict[str, str]]:
    """``{master: {pin: "POWER"|"GROUND"}}`` for every MACRO in ``lef_text``.

    A master with no supply pin maps to ``{}`` — it is KNOWN (so its instances
    are measured and owe nothing), which is a different fact from a master no
    LEF defines."""
    out: Dict[str, Dict[str, str]] = {}
    lines = (lef_text or "").splitlines()
    macro: Optional[str] = None
    pin: Optional[str] = None
    for raw in lines:
        tok = raw.split()
        if not tok:
            continue
        head = tok[0]
        if head == "MACRO" and len(tok) > 1:
            macro, pin = tok[1], None
            out.setdefault(macro, {})
        elif head == "END" and len(tok) > 1:
            if pin is not None and tok[1] == pin:
                pin = None
            elif macro is not None and tok[1] == macro:
                macro, pin = None, None
        elif macro is not None and head == "PIN" and len(tok) > 1:
            pin = tok[1]
        elif macro is not None and pin is not None and head == "USE" \
                and len(tok) > 1:
            use = tok[1].rstrip(";").upper()
            if use in _SUPPLY_USES:
                out[macro][pin] = use
    return out


def _section(def_text: str, name: str) -> str:
    m = re.search(r"^\s*" + name + r"\s+\d+\s*;(.*?)^\s*END\s+" + name + r"\b",
                  def_text, re.S | re.M)
    return m.group(1) if m else ""


def _statements(body: str) -> Iterable[List[str]]:
    """Token lists of the ``- ... ;`` statements of a DEF section."""
    cur: Optional[List[str]] = None
    for tok in body.split():
        if cur is None:
            if tok == "-":
                cur = []
            continue
        if tok == ";":
            yield cur
            cur = None
            continue
        cur.append(tok)
    if cur:
        yield cur


def parse_def(def_text: str) -> Tuple[Dict[str, str], Dict[str, str],
                                      Dict[Tuple[str, str], str],
                                      Dict[str, List[str]]]:
    """Return (components, net_use, explicit, wildcard).

    * components: ``{instance: master}``
    * net_use:    ``{net: USE}`` for every net in SPECIALNETS and NETS
    * explicit:   ``{(instance, pin): net}``
    * wildcard:   ``{pin: [net, ...]}`` from ``( * pin )``
    """
    comps: Dict[str, str] = {}
    for st in _statements(_section(def_text, "COMPONENTS")):
        if len(st) >= 2:
            comps[st[0]] = st[1]
    net_use: Dict[str, str] = {}
    explicit: Dict[Tuple[str, str], str] = {}
    wildcard: Dict[str, List[str]] = {}
    for sect in ("SPECIALNETS", "NETS"):
        for st in _statements(_section(def_text, sect)):
            if not st:
                continue
            net = st[0]
            use = ""
            # Connections are the parenthesised pairs BEFORE the first `+`
            # attribute; after it come routing points, which are also
            # parenthesised and must never read as a connection.
            i = 1
            while i < len(st):
                tok = st[i]
                if tok == "+":
                    break
                if tok == "(":
                    j = i + 1
                    while j < len(st) and st[j] != ")":
                        j += 1
                    inner = st[i + 1:j]
                    if len(inner) >= 2 and inner[0] != "PIN":
                        inst, pin = inner[0], inner[1]
                        if inst == "*":
                            wildcard.setdefault(pin, []).append(net)
                        else:
                            explicit.setdefault((inst, pin), net)
                    i = j + 1
                    continue
                i += 1
            for k in range(len(st) - 2):
                if st[k] == "+" and st[k + 1] == "USE":
                    use = st[k + 2].upper()
                    break
            if net not in net_use or not net_use[net]:
                net_use[net] = use
    return comps, net_use, explicit, wildcard


def judge(def_text: str, lef_texts: Iterable[str]) -> Dict[str, object]:
    """The verdict record for one DEF. See the module docstring."""
    supply_pins: Dict[str, Dict[str, str]] = {}
    for text in lef_texts:
        for master, pins in parse_lef_supply_pins(text).items():
            supply_pins.setdefault(master, {}).update(pins)
    comps, net_use, explicit, wildcard = parse_def(def_text or "")
    declared = {n: u for n, u in net_use.items() if u in _SUPPLY_USES}
    unknown: Dict[str, int] = {}
    off: List[Dict[str, str]] = []
    off_count = {"no_net": 0, "not_a_supply_net": 0, "wrong_kind": 0}
    checked_pins = 0
    checked_insts = 0
    for inst, master in comps.items():
        pins = supply_pins.get(master)
        if pins is None:
            unknown[master] = unknown.get(master, 0) + 1
            continue
        checked_insts += 1
        for pin, kind in pins.items():
            checked_pins += 1
            net = explicit.get((inst, pin))
            if net is None:
                cands = wildcard.get(pin) or []
                net = cands[0] if cands else None
            if net is None:
                why = "no_net"
            elif net not in declared:
                why = "not_a_supply_net"
            elif declared[net] != kind:
                why = "wrong_kind"
            else:
                continue
            off_count[why] += 1
            if len(off) < _EXAMPLES:
                off.append({"instance": inst, "master": master, "pin": pin,
                            "pin_use": kind, "net": net or "", "why": why})
    n_off = sum(off_count.values())
    if n_off:
        verdict, code = "FAIL", REFUSE_CODE
        reason = (f"{REFUSE_CODE}: {n_off} supply pin(s) of "
                  f"{checked_pins} are not on a declared supply net of their "
                  f"own kind ({off_count['no_net']} on no net, "
                  f"{off_count['not_a_supply_net']} on a non-supply net, "
                  f"{off_count['wrong_kind']} on the other supply kind); "
                  "e.g. " + ", ".join(f"{o['instance']}/{o['pin']}"
                                      for o in off[:5]))
    elif not comps:
        verdict, code = "NOT_MEASURED", UNMEASURED_CODE
        reason = f"{UNMEASURED_CODE}: the DEF declares no COMPONENTS"
    elif not declared:
        verdict, code = "NOT_MEASURED", UNMEASURED_CODE
        reason = (f"{UNMEASURED_CODE}: the DEF declares no net with "
                  "USE POWER or USE GROUND, so no supply pin can be owned")
    elif unknown:
        verdict, code = "NOT_MEASURED", UNMEASURED_CODE
        reason = (f"{UNMEASURED_CODE}: {sum(unknown.values())} instance(s) "
                  f"of {len(unknown)} master(s) no given LEF defines ("
                  + ", ".join(sorted(unknown)[:5]) + ")")
    else:
        verdict, code = "PASS", None
        reason = (f"every one of {checked_pins} supply pin(s) on "
                  f"{checked_insts} instance(s) sits on a declared supply "
                  "net of its own kind")
    return {
        "gate": GATE,
        "verdict": verdict,
        "code": code,
        "reason": reason,
        "declared_supply_nets": dict(sorted(declared.items())),
        "instances": len(comps),
        "instances_checked": checked_insts,
        "supply_pins_checked": checked_pins,
        "off_supply_pins": n_off,
        "off_supply_breakdown": off_count,
        "off_supply_examples": off,
        "unknown_masters": dict(sorted(unknown.items())),
    }


def judge_files(def_path: Path, lef_paths: Iterable[Path]) -> Dict[str, object]:
    lefs = []
    for p in lef_paths:
        lefs.append(Path(p).read_text(errors="replace"))
    rec = judge(Path(def_path).read_text(errors="replace"), lefs)
    rec["def"] = str(def_path)
    return rec


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("def_path", type=Path)
    ap.add_argument("--lef", action="append", type=Path, default=[],
                    help="a LEF defining masters the DEF instantiates "
                         "(repeatable)")
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args(argv)
    try:
        rec = judge_files(a.def_path, a.lef)
    except OSError as exc:
        rec = {"gate": GATE, "verdict": "NOT_MEASURED",
               "code": UNMEASURED_CODE,
               "reason": f"{UNMEASURED_CODE}: unreadable input: {exc}"}
    if a.json:
        _atomic_write_json(a.json, rec)
    print(f"[{rec['verdict']}] {GATE}: {rec['reason']}")
    return {"PASS": 0, "FAIL": 1}.get(str(rec["verdict"]), 2)


if __name__ == "__main__":
    sys.exit(main())
