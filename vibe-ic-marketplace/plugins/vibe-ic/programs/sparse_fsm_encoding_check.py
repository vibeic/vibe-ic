#!/usr/bin/env python3
"""sparse_fsm_encoding_check.py — did synthesis KEEP the sparse FSM encoding?

WHY (#2067). `synth`'s `fsm_recode` pass re-assigns the state encoding of
every FSM it extracts, by default to one-hot. For a design that declares
SPARSE FSMs (Hamming-distance-separated state codes chosen for
fault-injection resistance) that silently destroys the property the encoding
exists for. The netlist stays functionally equivalent — LEC proves the key
points — so no existing gate could see it: port equivalence says the FUNCTION
is preserved, not the fault-injection property.

This is the reporter. It answers ONE question by name, never by count:

    fsm_recoded: []                 nothing the design declared sparse was
                                    re-encoded — the required answer for a
                                    design that declares sparse FSMs
    FSM_SPARSE_ENCODING_LOST        named refusal, LISTING the registers
                                    whose encoding synthesis replaced

TWO INDEPENDENT OBSERVABLES, so the gate cannot be defeated by the absence of
either one:

  (a) the FSM ENCODING TABLE `fsm_recode` itself writes (`synth -encfile`,
      `lec_run.FSM_ENCFILE_NAME`): a `.fsm <module> <register>` stanza for a
      register the detector called sparse IS the re-encoding, stated by the
      tool that did it;
  (b) the STATE-REGISTER WIDTH in the emitted netlist: one-hot recoding of an
      N-code, W-bit sparse register emits an N-bit register, so a width that
      differs from the RTL's is re-encoding even when no table was written.

It reads the design INPUT (RTL) and the flow's OWN synthesis outputs. Never an
oracle, a golden or a reference flow (§4.05).

Usage:
    python3 sparse_fsm_encoding_check.py --rtl-dir <dir> [--rtl-dir ...]
        [--encfile <fsm_encoding.enc>] [--netlist <netlist.v>]
        [--json <report.json>]

Exit codes:
    0 = PASS — no declared-sparse register was re-encoded (includes the
        honest case "this design declares no sparse FSM": nothing to keep)
    1 = FAIL — FSM_SPARSE_ENCODING_LOST, registers named in the report
    2 = NOT_MEASURED — the design DOES declare sparse FSMs but neither
        observable was readable. "Could not read it" is not "read it and it
        was clean", so this is never reported as a PASS.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

from _atomic_artefact import write_text as atomic_write_text  # #1082

import sparse_fsm_detect as _sfd

REFUSAL = "FSM_SPARSE_ENCODING_LOST"

# `fsm_recode -encfile` writes:   .fsm <module> <register>
#                                 .map <old-code> <new-code>
_ENC_FSM_RE = re.compile(r"(?m)^\s*\.fsm\s+(?P<module>\S+)\s+(?P<reg>\S+)\s*$")
_ENC_MAP_RE = re.compile(r"(?m)^\s*\.map\s+(?P<old>\S+)\s+(?P<new>\S+)\s*$")


def parse_encfile(text: str) -> List[dict]:
    """[{module, register, map:[(old,new)]}] from an `-encfile` table. PURE."""
    out: List[dict] = []
    for m in _ENC_FSM_RE.finditer(text):
        seg = text[m.end():]
        nxt = _ENC_FSM_RE.search(seg)
        if nxt:
            seg = seg[:nxt.start()]
        out.append({
            "module": m.group("module").lstrip("\\"),
            "register": m.group("reg").lstrip("\\"),
            "map": [(mm.group("old"), mm.group("new"))
                    for mm in _ENC_MAP_RE.finditer(seg)],
        })
    return out


def netlist_reg_widths(text: str) -> Dict[str, int]:
    """{signal: bit width} for every wire/reg declaration in a netlist. PURE.
    A scalar declaration is width 1."""
    out: Dict[str, int] = {}
    for m in re.finditer(
            r"(?m)^\s*(?:wire|reg)\s*(?:\[\s*(\d+)\s*:\s*(\d+)\s*\])?\s*"
            r"([\\]?[\w$.\[\]]+)\s*;", text):
        hi, lo, name = m.group(1), m.group(2), m.group(3).lstrip("\\")
        out[name.split(".")[-1]] = (abs(int(hi) - int(lo)) + 1
                                    if hi is not None else 1)
    return out


def check(rtl_paths: List[Path], encfile: Optional[Path],
          netlist: Optional[Path]) -> dict:
    """The whole verdict as data. Callers decide the exit code."""
    det = _sfd.detect_paths(rtl_paths)
    sparse = det["sparse_state_registers"]
    rep: dict = {
        "tool": "sparse_fsm_encoding_check",
        "declares_sparse_fsm": det["declares_sparse_fsm"],
        "sparse_state_registers": det["register_names"],
        "fsm_recoded": [],
        "observables_read": [],
        "observables_unreadable": [],
        "verdict": "PASS",
        "refusal": None,
        "detail": "",
    }
    if not det["declares_sparse_fsm"]:
        rep["detail"] = ("the design declares no sparse FSM, so no encoding "
                         "had to be preserved; fsm_recode's normal "
                         "optimisation is correct here")
        return rep

    by_name = {r["register"]: r for r in sparse}
    # The register `fsm_recode` names is not always the one the RTL names.
    # MEASURED on opentitan_aes/aes_ctr_fsm: the recoded register was
    # `u_state_regs.u_state_flop.q_o` — the sparse FLOP's own output — while
    # the RTL calls the state `aes_ctr_cs`. An entry whose path contains a
    # declared sparse-flop INSTANCE name is therefore the same FSM.
    instances = {r["flop_instance"]: r for r in sparse if r.get("flop_instance")}
    recoded: Dict[str, dict] = {}

    # (a) the table fsm_recode wrote about itself
    if encfile is not None:
        try:
            entries = parse_encfile(encfile.read_text(errors="replace"))
            rep["observables_read"].append(f"encfile:{encfile}")
            for e in entries:
                hit = None
                if e["register"] in by_name:
                    hit = e["register"]
                else:
                    for inst, info in instances.items():
                        if inst in e["register"].split("."):
                            hit = info["register"]
                            break
                if hit:
                    recoded[hit] = {
                        "register": e["register"],
                        "module": e["module"],
                        "observable": "encfile",
                        "map": e["map"][:8],
                    }
        except OSError as e:
            rep["observables_unreadable"].append(f"encfile:{encfile}: {e}")
    else:
        rep["observables_unreadable"].append("encfile: not given")

    # (b) the state-register width the netlist actually carries
    if netlist is not None:
        try:
            widths = netlist_reg_widths(netlist.read_text(errors="replace"))
            rep["observables_read"].append(f"netlist:{netlist}")
            for name, info in by_name.items():
                states = info.get("states") or {}
                if not states or name not in widths:
                    continue
                rtl_w = len(next(iter(states.values())))
                if widths[name] != rtl_w:
                    recoded.setdefault(name, {
                        "register": name,
                        "module": info.get("module", ""),
                        "observable": "netlist_width",
                    })
                    recoded[name]["rtl_width"] = rtl_w
                    recoded[name]["netlist_width"] = widths[name]
        except OSError as e:
            rep["observables_unreadable"].append(f"netlist:{netlist}: {e}")
    else:
        rep["observables_unreadable"].append("netlist: not given")

    if not rep["observables_read"]:
        rep["verdict"] = "NOT_MEASURED"
        rep["detail"] = (
            "the design DOES declare sparse FSMs but neither the encoding "
            "table nor the netlist could be read, so whether the encoding "
            "survived was not measured: " +
            "; ".join(rep["observables_unreadable"]))
        return rep

    rep["fsm_recoded"] = [recoded[k] for k in sorted(recoded)]
    if rep["fsm_recoded"]:
        rep["verdict"] = "FAIL"
        rep["refusal"] = REFUSAL
        rep["detail"] = (
            f"{REFUSAL}: synthesis replaced the declared sparse encoding of " +
            ", ".join(sorted(recoded)) +
            " — the netlist is functionally equivalent but no longer carries "
            "the Hamming separation the encoding exists for")
    else:
        rep["detail"] = ("every declared sparse state register kept its RTL "
                         "encoding (read: " +
                         ", ".join(rep["observables_read"]) + ")")
    return rep


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rtl-dir", action="append", default=[], required=True)
    ap.add_argument("--encfile")
    ap.add_argument("--netlist")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    rtl = [Path(p) for p in a.rtl_dir]
    missing = [str(p) for p in rtl if not p.exists()]
    if missing:
        print("error: does not exist: " + ", ".join(missing), file=sys.stderr)
        return 2
    enc = Path(a.encfile) if a.encfile and Path(a.encfile).is_file() else None
    net = Path(a.netlist) if a.netlist and Path(a.netlist).is_file() else None
    rep = check(rtl, enc, net)
    txt = json.dumps(rep, indent=2, sort_keys=True)
    if a.json:
        atomic_write_text(Path(a.json), txt + "\n")
    print(txt)
    print(f"Overall: {rep['verdict']}", file=sys.stderr)
    return {"PASS": 0, "FAIL": 1, "NOT_MEASURED": 2}[rep["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
