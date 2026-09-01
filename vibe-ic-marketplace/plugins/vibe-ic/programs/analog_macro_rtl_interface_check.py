#!/usr/bin/env python3
"""analog_macro_rtl_interface_check.py — the digital side of an analog macro's
interface, which nothing compared.

ENFORCEMENT: blocking
    A8 gate clause in `flow/phase1_phase2_phase3.yaml` (the acceptance audit)
    AND invoked inline by `analog_one_shot_runner.step_for_block` at
    A8_hardmacro_gen, where rc 1 turns the block's A8 step into FAIL
    (vibe-ic#2010 items 1-2: it shipped run by nothing but its own test).

WHY THIS EXISTS, MEASURED. `analog_hardmacro_pinname_consistency_check` asserts
LEF == macro `.v` == `spec.json` — all three on the ANALOG side, and it passes.
Nothing compares those pins against the module the DIGITAL netlist actually
instantiates, and on this campaign's design the two sides disagree about every
block. OpenROAD says so, but only once the LEF masters resolve, i.e. only after
A8 has run and ORD-2013 is out of the way — and it says it as a WARNING:

    STA-0201 instance \\g_channel[0].u_delta_sigma port bit_out not found
    STA-0201 instance \\g_channel[0].u_delta_sigma port clk not found
    STA-0201 instance \\g_channel[0].u_delta_sigma port vrefn / vrefp not found
    STA-0201 instance u_ldo port vin not found

The disagreements are not one kind:

  * BOTH blocks' RTL blackboxes declare no ground at all, while the macro's
    LEF carries `vss` as a PG pin. A power pin the digital top never connects
    is not a naming slip; it is a macro that will float in silicon.
  * One block's supply is called `vin` on the RTL side (from an L5 line that
    reads "Vin = 1.8 V") and `vdd` on the analog side. Same net, two names,
    two producers, never reconciled.
  * The modulator disagrees about its FUNCTION, not its spelling: the RTL
    instantiates a clocked 1-bit modulator (`clk`, `bit_out`, `vrefp/vrefn`)
    and the analog block implements the forward path only — its own topology
    provenance says "NO DAC feedback branch yet (that arrives with the
    quantiser)", so it has `vout`, `rst` and `vcm` instead. Renaming those to
    match would be a lie; the gate's job is to say so, not to paper over it.

So this gate reports the disagreement BY NAME, in both directions, and refuses.
It never renames anything and never decides which side is right — which side is
right is a design question, and two of the three cases above have different
answers.

Exit codes: 0 PASS (every block's two sides agree, or nothing to compare and
that is recorded), 1 FAIL (a named disagreement), 2 VACUOUS/argument error.
chip-AGNOSTIC: no chip, vendor or signal-name literal.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

PROGRAMS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROGRAMS_DIR))

import _hdl_code_text  # noqa: E402 - offset-preserving comment blanker (#731)
import _vacuous_exit as _vx  # noqa: E402
from _atomic_artefact import write_json  # noqa: E402 - vibe-ic#1082

GATE = "analog_macro_rtl_interface_check"

#: `module <name> ( … );` — both the ANSI form (directions inline) and the
#: bare-list form a synthesis writer emits.
_MODULE_RE = re.compile(
    r"(?ms)^\s*module\s+(\\?\S+?)\s*(?:#\s*\([^)]*\)\s*)?\((.*?)\)\s*;")
_PIN_RE = re.compile(r"^\s*PIN\s+(\S+)", re.M)
_PGPIN_RE = re.compile(r"^\s*PIN\s+(\S+)(?=(?:.(?!^\s*PIN\s))*?USE\s+(?:POWER|GROUND)\s*;)",
                       re.M | re.S)


def module_ports(text: str, module: str) -> Optional[List[str]]:
    """Port NAMES of `module` in a Verilog source, or None when absent.

    Reads the header only: a blackbox has nothing else, and a port list is the
    whole of the interface claim being compared.

    THE SCAN RUNS OVER COMMENT-BLANKED TEXT, NOT THE RAW FILE (vibe-ic#2010,
    item 3). `_MODULE_RE` is anchored at line start, and a block comment that
    quotes a stale header — `/* the old\n module blk (a, b);\n was retired */`
    — puts `module blk (` at a line start too. Scanning the raw text returned
    the RETIRED port list for `blk`, because the first match wins and the
    comment precedes the header it describes. Blanking the SIBLING variable
    (the old code stripped comments out of `m.group(2)` only) does not make
    the header scan safe, which is why `hdl_declaration_scan_strips_comments
    _check` reads dataflow and flagged this site by name. The blanker keeps
    offsets, so nothing else in this function changes.
    """
    code = _hdl_code_text.strip_hdl_comments_and_strings(text)
    for m in _MODULE_RE.finditer(code):
        name = m.group(1).lstrip("\\").strip()
        if name != module:
            continue
        body = m.group(2)
        out: List[str] = []
        for item in body.split(","):
            # Strip bit-selects and ranges FIRST: the port NAME is what is
            # left. Splitting on the brackets instead made `\\a[0]` parse as
            # the port `0` — the last token, and a number.
            item = re.sub(r"\[[^\]]*\]", " ", item)
            toks = [t for t in item.split() if t]
            if not toks:
                continue
            out.append(toks[-1].lstrip("\\"))
        return out
    return None


def lef_pins(text: str) -> Tuple[List[str], List[str]]:
    """(all pins, PG pins) of the single MACRO in a LEF."""
    allp = [p for p in _PIN_RE.findall(text or "")]
    pg = [p for p in _PGPIN_RE.findall(text or "")]
    return allp, pg


def block_ports_from_topology(topo: Dict) -> Tuple[List[str], List[str]]:
    """(ports, rails) as the analog block's own topology IR declares them."""
    ports = [str(p) for p in (topo.get("ports") or [])]
    rails = {str(v) for v in (topo.get("rails") or {}).values()}
    return ports, [p for p in ports if p in rails]


def compare(macro_pins: List[str], rtl_ports: List[str], rails: List[str]
            ) -> Dict[str, List[str]]:
    """The two directions, plus the rails singled out.

    A rail missing on the digital side is called out separately because it is
    the one case with no legitimate reading: a PG pin the top never connects
    floats in silicon whatever the two producers meant.
    """
    m, r = set(macro_pins), set(rtl_ports)
    return {
        "missing_in_rtl": sorted(m - r),
        "extra_in_rtl": sorted(r - m),
        "rails_missing_in_rtl": sorted(set(rails) - r),
    }


def _find_rtl(project: Path) -> List[Path]:
    out: List[Path] = []
    for pat in ("phase2/stage1/rtl/*.v", "phase2/stage1/rtl/*.sv",
                "rtl/*.v", "rtl/*.sv", "phase2/stage2/synth/netlist.v"):
        out += sorted(project.glob(pat))
    return out


def check_block(project: Path, block: str) -> Dict:
    bdir = project / "phase3" / "analog" / block
    hdir = project / "phase3" / "analog" / "hardmacro" / block
    topo = bdir / "topology.json"
    lef = hdir / f"{block}.lef"
    macro_pins: List[str] = []
    rails: List[str] = []
    source = None
    if lef.is_file():
        macro_pins, _pg = lef_pins(lef.read_text(errors="replace"))
        source = "lef"
    if topo.is_file():
        ports, rls = block_ports_from_topology(json.loads(topo.read_text()))
        rails = rls
        if not macro_pins:
            macro_pins, source = ports, "topology"
    if not macro_pins:
        return {"block": block, "compared": False,
                "reason": "no hardmacro LEF and no topology port list"}
    rtl_ports = None
    for f in _find_rtl(project):
        got = module_ports(f.read_text(errors="replace"), block)
        if got is not None:
            rtl_ports, rtl_file = got, str(f.relative_to(project))
            break
    if rtl_ports is None:
        return {"block": block, "compared": False,
                "reason": f"no module `{block}` in any RTL / netlist source"}
    d = compare(macro_pins, rtl_ports, rails)
    ok = not (d["missing_in_rtl"] or d["extra_in_rtl"])
    return {"block": block, "compared": True, "agree": ok,
            "macro_pin_source": source, "rtl_source": rtl_file,
            "macro_pins": sorted(macro_pins), "rtl_ports": sorted(rtl_ports),
            **d}


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
        print("VACUOUS: no analog block declared — no macro interface to check")
        _vx.announce_vacuous(GATE, "no_analog_block_declared")
        return _vx.RC_VACUOUS
    results = [check_block(project, b) for b in blocks]
    compared = [r for r in results if r.get("compared")]
    bad = [r for r in compared if not r["agree"]]
    for r in results:
        if not r.get("compared"):
            print(f"  [{r['block']}] SKIP — {r['reason']}")
            continue
        if r["agree"]:
            print(f"  [{r['block']}] agree ({len(r['macro_pins'])} pin(s))")
            continue
        print(f"  [{r['block']}] MACRO_RTL_INTERFACE_DISAGREES "
              f"(macro pins from {r['macro_pin_source']}, "
              f"RTL from {r['rtl_source']})")
        if r["rails_missing_in_rtl"]:
            print(f"      supply pin(s) the digital side never connects: "
                  f"{', '.join(r['rails_missing_in_rtl'])}")
        if r["missing_in_rtl"]:
            print(f"      on the macro, absent from the module: "
                  f"{', '.join(r['missing_in_rtl'])}")
        if r["extra_in_rtl"]:
            print(f"      on the module, absent from the macro: "
                  f"{', '.join(r['extra_in_rtl'])}")
    if not compared:
        # Nothing to compare is a DESIGN absence (no packaged macro yet, or
        # no digital module instantiates the block), not a pass: the flow
        # auditor promotes rc 2 to VACUOUS_PASS and the sentinel below is the
        # rc-independent disclosure `_vacuous_exit` documents.
        print("VACUOUS: nothing could be compared")
        _vx.announce_vacuous(GATE, "no_comparable_macro_rtl_pair")
        verdict, rc = "VACUOUS_PASS", _vx.RC_VACUOUS
    elif bad:
        print(f"FAIL: {len(bad)}/{len(compared)} block(s) disagree")
        verdict, rc = "FAIL", _vx.RC_FAIL
    else:
        print(f"PASS: {len(compared)}/{len(compared)} block(s) agree")
        verdict, rc = "PASS", _vx.RC_PASS
    if a.json:
        # Atomic (vibe-ic#1082): the declared report destination appears
        # under its final name only once it is complete, so a reader that
        # races this gate sees the previous report or the new one, never a
        # truncated document.
        write_json(a.json, {"gate": GATE, "verdict": verdict,
                            "blocks": results, "rc": rc})
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
