#!/usr/bin/env python3
"""
nvm_program_supply_pin_check.py — a design that intends to PROGRAM a
non-volatile memory must have a physical way to bring the programming supply
in from outside.

ENFORCEMENT: blocking

The domain convention
---------------------
Any PROGRAMMABLE non-volatile memory (one-time-programmable, fuse-based,
multiple-time-programmable, antifuse — the whole family) needs, for its
PROGRAMMING operation, a supply that is EXTERNALLY supplied and ABOVE the
digital core voltage, delivered through a dedicated terminal: a package pin
for in-field programming, or a wafer-probe pad for programming before the part
ships. READING such a memory generally needs only the core supply — which is
exactly why a read-only integration looks complete while a programming
integration is not.

This is physics, not vendor preference. Corroboration: within one process, two
INDEPENDENT programmable-memory IP families — one native to the process, one
third-party — both specify their programming supply as externally supplied,
both at a voltage window above that process's core supply. Two unrelated
vendors converge because the cell cannot be written at core voltage.

What this gate decides
----------------------
The triad, every term read from the design's OWN inputs:

  A  the design INSTANTIATES a macro whose OWN LEF types a pin `USE POWER`
     that is not the core rail — a supply the internal PDN cannot provide;
  B  the design shows PROGRAMMING INTENT — the macro master name, the macro's
     own pin names, or the RTL nets bound to that instance carry generic
     fuse-programming vocabulary;
  C  NO top-level port and NO declared package pin or probe pad carries that
     supply to the outside.

A + B + C  =>  `NVM_PROGRAM_SUPPLY_PIN_ABSENT` (ERROR, exit 1). The design
cannot perform the programming step it is built to perform, and no digital
check downstream will say so: the digital logic is entirely correct.

A + C without B is NOT a finding. A part programmed by the IP vendor before
delivery carries no programming logic, needs no programming pin, and is a
legitimate design. It is recorded as `NVM_NO_PROGRAM_INTENT` in the report so
the assumption is visible rather than silent.

Why this exists SEPARATELY from the #309 gate
---------------------------------------------
#309 blocks a SYMPTOM before detailed routing: synthesis tie-cells an
unbindable macro supply pin, a signal net lands on a power terminal, and
TritonRoute aborts every net in the design. This gate names the CAUSE, one step
earlier: the design was never given a way to bring that supply in. The two
share `hardmacro_supply_intent` as their single decision module, so the
judgement cannot drift — but they answer different questions. #309 asks whether
the pin is DECLARED in the power-intent layer; a pin can be perfectly declared
there and still have no package pin, because that layer describes INTERNAL
rails and an internal rail can never be the answer for a supply that is above
core voltage by definition.

chip-AGNOSTIC
-------------
No macro name, pin name, vendor, PDK or SKU appears in this file. Which pin is
a supply comes from the macro's own LEF USE record; which supply is the core
rail comes from the design's own declared rails; which names reach the outside
comes from the design's own top-level ports and pad declarations. The only
literals are generic English/EDA words for the ACT of programming a fuse-type
memory (`hardmacro_supply_intent.PROGRAM_INTENT_TOKENS`) — they classify
intent, they never identify a part.

§4.05: reads design INPUT only (rtl/, input/pdk_local/, input/pdk/,
phase1/generated_docs/). Never an oracle or golden artefact.

Usage:
    nvm_program_supply_pin_check.py <project> [--top NAME]
                                    [--rail NAME ...] [--json OUT]

Exit codes:
    0  PASS / SKIP (nothing to decide) / recorded no-programming-intent
    1  FAIL — NVM_PROGRAM_SUPPLY_PIN_ABSENT
    2  argument or I/O error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import hardmacro_supply_intent as _hmsi  # noqa: E402
import _path_layout as _pl  # noqa: E402

_RTL_EXTS = (".v", ".sv")


# ---------------------------------------------------------------------------
# Design inputs
# ---------------------------------------------------------------------------
def load_macros(project: Path,
                extra_lefs: Optional[List[str]] = None
                ) -> Dict[str, List[Dict[str, str]]]:
    """``{master: [{"pin","use"}, ...]}`` from every macro LEF the design
    stages. The LEF's USE record is the AUTHORITATIVE statement that a pin is a
    supply terminal — the same record the router honours."""
    texts = list(extra_lefs or []) or _hmsi.load_macro_lefs(project)
    macros: Dict[str, List[Dict[str, str]]] = {}
    for txt in texts:
        for p in _hmsi.lef_all_pins(txt):
            if not p["master"]:
                continue
            bucket = macros.setdefault(p["master"], [])
            if not any(e["pin"] == p["pin"] for e in bucket):
                bucket.append({"pin": p["pin"], "use": p["use"]})
    return macros


def _rtl_modules(project: Path):
    """Parse rtl/ into ``{module_name: ModuleDef}`` using the shipped RTL
    parser. Returns ``{}`` when there is no rtl/ to read."""
    rtl = _pl.rtl_dir(project)
    if not rtl.is_dir():
        return {}
    if not any(rtl.rglob(f"*{e}") for e in _RTL_EXTS):
        return {}
    try:
        import module_port_audit as _mpa
        return _mpa.scan_rtl_directory(rtl)
    except Exception:  # noqa: BLE001 — an unparsable tree must SKIP, not FAIL
        return {}


def _bare_net(expr: str) -> str:
    """The identifier a connection expression names, stripped of bit-selects,
    concatenation braces and whitespace. `{a, b}` has no single identifier."""
    s = (expr or "").strip()
    m = re.match(r"^([A-Za-z_]\w*)\s*(\[[^\]]*\])?$", s)
    return m.group(1) if m else ""


def instantiated_masters(modules, macros) -> Set[str]:
    """Macro masters the RTL actually instantiates. A macro staged in
    input/pdk_local/ but never instantiated is not this design's problem."""
    used: Set[str] = set()
    for mod in (modules or {}).values():
        for inst in mod.instances:
            if inst.module_name in macros:
                used.add(inst.module_name)
    return used


def rtl_nets_by_master(modules, macros) -> Dict[str, List[str]]:
    """Every RTL net bound to each macro master's instances — the design's own
    statement of what it wires that macro to."""
    out: Dict[str, List[str]] = {}
    for mod in (modules or {}).values():
        for inst in mod.instances:
            if inst.module_name not in macros:
                continue
            bucket = out.setdefault(inst.module_name, [])
            for c in inst.connections:
                for name in (c.port_name, _bare_net(c.wire_expr)):
                    if name and name not in bucket:
                        bucket.append(name)
    return out


def resolve_top(modules, explicit: Optional[str]) -> Optional[str]:
    """The top module: the caller's name when it IS a module, else the single
    instantiation-graph root. None when ambiguous (0 or >1 roots) — an
    ambiguous top means an unknowable port list, which must SKIP, not guess."""
    if not modules:
        return None
    if explicit and explicit in modules:
        return explicit
    instantiated = {i.module_name for m in modules.values() for i in m.instances}
    roots = sorted(set(modules) - instantiated)
    return roots[0] if len(roots) == 1 else None


def _doc_json(project: Path, stem: str) -> Dict[str, Any]:
    for rel in (f"phase1/generated_docs/{stem}.json",
                f"generated_docs/{stem}.json",
                f"input/generated_docs/{stem}.json"):
        p = project / rel
        if p.is_file():
            try:
                return json.loads(p.read_text(errors="replace"))
            except (OSError, ValueError):
                return {}
    return {}


def _declared_pad_names(project: Path) -> List[str]:
    """Package pins and probe pads the design DECLARES in its own Phase-1 docs.

    A wafer-probe pad used to program the part before it ships is a legitimate
    programming-supply entry that need not be an RTL port — so the pinout (L1)
    and pad list (L5) count as external entries alongside the top-level ports.
    """
    names: List[str] = []
    pinout = (_doc_json(project, "L1_DATASHEET").get("pinout") or {})
    if isinstance(pinout, dict):
        for k, v in pinout.items():
            names.append(str(k))
            if isinstance(v, dict):
                for key in ("name", "pin", "signal", "pad"):
                    if isinstance(v.get(key), str):
                        names.append(v[key])
            elif isinstance(v, str):
                names.append(v)
    elif isinstance(pinout, list):
        for e in pinout:
            if isinstance(e, dict):
                for key in ("name", "pin", "signal", "pad"):
                    if isinstance(e.get(key), str):
                        names.append(e[key])
            elif isinstance(e, str):
                names.append(e)
    for pad in (_doc_json(project, "L5_ADI_SPEC").get("pads") or []):
        if isinstance(pad, dict):
            for key in ("name", "pad", "pin", "signal"):
                if isinstance(pad.get(key), str):
                    names.append(pad[key])
        elif isinstance(pad, str):
            names.append(pad)
    return [n for n in names if n]


def _cell_lef_rails(project: Path) -> List[str]:
    """Core supply rails, discovered from the standard-cell LEF the design
    stages: the names its own cells type `USE POWER`. Nothing is hardcoded —
    the literal comes from the PDK the design brought with it."""
    rails: List[str] = []
    for base in (project / "input" / "pdk" / "lef", project / "input" / "pdk"):
        if not base.is_dir():
            continue
        for lef in sorted(base.rglob("*.lef"))[:8]:
            try:
                txt = lef.read_text(errors="replace")
            except OSError:
                continue
            for p in _hmsi.lef_pg_pins(txt):
                if p["use"] == "POWER" and p["pin"] not in rails:
                    rails.append(p["pin"])
        if rails:
            break
    return rails


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------
def _finding_message(r: Dict[str, Any]) -> str:
    """State exactly what was established, and no more.

    When the design's declared rails identify the macro's core supply pin by
    name, the remaining POWER pins ARE extra supplies and can be named as such.
    When they do not (the design and the macro vendor name the same rail
    differently — routine), all that is established is that at most one of the
    macro's POWER pins can be the core rail, so at least one of the others has
    no way in. Claiming more than that would be a fabricated diagnosis.
    """
    intent = ", ".join(f"{e['source']} {e['name']!r}"
                       for e in r["program_intent"][:3])
    if r["core_rail_identified"]:
        what = (f"supply pin(s) {r['uncarried']} are LEF-typed USE POWER and "
                f"are not the core rail {r['core_rail_identified']}, so they "
                f"must be supplied from OUTSIDE the die — but no top-level "
                f"port and no declared package pin or probe pad carries them")
    else:
        what = (f"POWER pins {r['power_pins']} are LEF-typed supplies and none "
                f"corresponds to a rail this design declares, so which one is "
                f"the core supply cannot be said — but a die has ONE core "
                f"rail, and {len(r['uncarried'])} of them "
                f"({r['uncarried']}) have no top-level port, package pin or "
                f"probe pad, so at least one supply has no way in")
    return (
        f"{r['master']}: {what}. This design shows programming intent "
        f"({intent}), so it intends to program a non-volatile memory it has "
        f"no way to deliver programming voltage to. A programmable "
        f"non-volatile memory is written at a voltage ABOVE core, supplied "
        f"externally through a dedicated terminal — no internal rail can "
        f"answer for it. Every digital check will pass; the part cannot be "
        f"programmed. Declare the programming supply pin/pad at the top "
        f"level, or state that the memory is programmed before delivery and "
        f"remove the programming control logic.")


def check(project: Path,
          top: Optional[str] = None,
          rails: Optional[List[str]] = None,
          macro_lef_texts: Optional[List[str]] = None) -> Dict[str, Any]:
    macros = load_macros(project, macro_lef_texts)
    if not macros:
        return _skip("no macro LEF staged — this design instantiates no hard "
                     "macro, so there is no programmable memory to supply")
    modules = _rtl_modules(project)
    if not modules:
        return _skip("no parsable RTL — instantiation and programming intent "
                     "are both unreadable, so nothing can be decided honestly")
    used = instantiated_masters(modules, macros)
    if not used:
        return _skip("no staged macro is instantiated by the RTL")
    top_name = resolve_top(modules, top)
    if not top_name:
        return _skip("top module is ambiguous (no single instantiation-graph "
                     "root) — the top-level port list is unknowable")

    external = list(modules[top_name].ports.keys()) + _declared_pad_names(project)
    known_rails = list(rails or []) \
        or _hmsi.declared_rails(_hmsi.load_l21(project)) \
        or _cell_lef_rails(project)

    report = _hmsi.assess_program_supply(
        {m: macros[m] for m in used},
        known_rails, external,
        rtl_nets_by_master(modules, macros))

    findings = [{
        "severity": "ERROR",
        "rule": "NVM_PROGRAM_SUPPLY_PIN_ABSENT",
        "master": r["master"],
        "pins": r["uncarried"],
        "program_intent": r["program_intent"],
        "message": _finding_message(r),
    } for r in report["findings"]]

    notes = [{
        "severity": "INFO",
        "rule": "NVM_NO_PROGRAM_INTENT",
        "master": r["master"],
        "pins": r["uncarried"],
        "message": (
            f"{r['master']}: supply pin(s) {r['uncarried']} have no external "
            f"entry, but no programming control logic is visible either — "
            f"recorded as an assumption that this memory is read-only in "
            f"this design, or programmed before delivery."),
    } for r in report["notes"]]

    return {
        "program": "nvm_program_supply_pin_check",
        "verdict": "FAIL" if findings else (
            "PASS_WITH_REVIEW" if notes else "PASS"),
        "pass": not findings,
        "top_module": top_name,
        "instantiated_macros": sorted(used),
        "declared_rails": report["declared_rails"],
        "rails_known": bool(known_rails),
        "external_entries": external,
        "macros": report["macros"],
        "findings": findings,
        "notes": notes,
    }


def _skip(reason: str) -> Dict[str, Any]:
    return {"program": "nvm_program_supply_pin_check", "verdict": "SKIP",
            "pass": True, "skip_reason": reason,
            "findings": [], "notes": [], "macros": []}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project", type=Path)
    ap.add_argument("--top", default=None,
                    help="Top module name (default: instantiation-graph root)")
    ap.add_argument("--rail", action="append", default=[], metavar="NAME",
                    help="A core supply rail this design declares (repeatable). "
                         "Default: the design's L21 power intent, else the "
                         "staged standard-cell LEF's USE POWER pin names.")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args()

    project = args.project.resolve()
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2
    try:
        rep = check(project, args.top, args.rail)
    except OSError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rep, indent=2) + "\n")

    if rep["verdict"] == "SKIP":
        print(f"[SKIP] nvm_program_supply_pin_check: {rep['skip_reason']}")
        return 0
    for n in rep["notes"]:
        print(f"[INFO] {n['rule']}: {n['message']}")
    for f in rep["findings"]:
        print(f"[ERROR] {f['rule']}: {f['message']}", file=sys.stderr)
    print(f"[{rep['verdict']}] nvm_program_supply_pin_check: "
          f"{len(rep['instantiated_macros'])} instantiated macro(s), "
          f"{len(rep['findings'])} finding(s)")
    return 1 if rep["findings"] else 0


if __name__ == "__main__":
    sys.exit(main())
