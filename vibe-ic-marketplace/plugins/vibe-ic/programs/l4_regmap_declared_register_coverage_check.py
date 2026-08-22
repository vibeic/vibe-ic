#!/usr/bin/env python3
"""l4_regmap_declared_register_coverage_check.py — L4's DENOMINATOR (#507).

BLOCKS (exit 1). Rationale for blocking rather than advising
=============================================================
The defect this gate exists for is not a wrong number in L4; it is the
ABSENCE of a number. Measured on a real Phase-1 output whose staged HDL
package declares 145 ``CSR_<NAME> = 12'h<addr>`` register address
bindings, L4 carried 61 of them and
``l4_regmap_enumerated_values_typed_check`` reported::

    [PASS] 2 multi-bit enum-eligible fields all carry typed
           code->meaning enumerated_values

That gate was not wrong. It audits the fields that are PRESENT, and it
has no view of whether the register set is complete against the input,
so 84 declared addresses were absent while the layer reported clean. A
numerator with no denominator reads as coverage and is not.

Advising would not help: every consumer downstream of L4 — the register
block emitter, the address decoder, the CSR access tests — works from
the registers L4 carries. A register the input declares and L4 drops is
a decode that is never generated, and the flow cannot tell the
difference between "the design has no such register" and "we lost it".
So: FAIL blocks.

The contract this gate enforces
===============================
    A layer that carries a SUBSET of what its input declares must be
    able to state the size of both sides.

  D1  Both sides are re-derived HERE, independently:

        declared — every address-valued ``typedef enum`` in the staged
                   HDL inputs, harvested from ``input/docs`` by
                   ``_hdl_enum``. Never read from a number Phase 1
                   wrote: a denominator its own producer computes can
                   only ever confirm itself, which is the shape that let
                   a document be dropped without the coverage metric
                   falling.

        carried  — the register records L4 actually holds, matched by
                   the declared NAME and by the declared ADDRESS. Either
                   match counts: a prose walker that captured the
                   address under its own lowercase name is carrying the
                   binding, and demanding the declared spelling as well
                   would be a naming rule, not a coverage rule.

  D2  The verdict always states its denominator, in the shape
      ``_gate_denominator.Denominator`` enforces — unit, examined,
      considered, and a written reason whenever nothing was examined.

Chip-AGNOSTIC
=============
Nothing here reads a type name, a vendor, a part or a register
spelling. What makes an enum an address map is decided by
``_hdl_enum.route_enum`` from the member set's SHAPE — a set of names
each bound to a distinct code in a space far wider than the set itself.
``csr_num_e`` is one design's name for a shape every CPU-class design
has under a different name.

Usage:
    python3 l4_regmap_declared_register_coverage_check.py <project_dir> \
        [--json <out.json>]

Exit codes:
    0 = PASS / PASS_WITH_WAIVER
    1 = FAIL (blocks) — the input declares register bindings L4 does not
        carry
    2 = NOT APPLICABLE — no staged HDL input declares an address-valued
        enum, or L4 is absent. The denominator says so explicitly.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _hdl_enum as _hdlenum  # noqa: E402
import _path_layout as _pl  # noqa: E402
from _gate_denominator import Denominator, attach  # noqa: E402

GATE = "l4_regmap_declared_register_coverage_check"
WAIVER_KEY = "l4_regmap_declared_register_coverage_intentional"
WAIVER_MIN_LEN = 40

# Same key list the emitter contract gate reads, for the same reason:
# these are the keys a consumer looks under for an address.
_ADDR_KEYS = ("address_int", "address", "offset", "addr", "addr_hex",
              "offset_hex", "base_address")

_HEX_RE = re.compile(r"^\s*0[xX]([0-9a-fA-F_]+)\s*$")
_SIZED_RE = re.compile(r"^\s*\d+\s*'\s*[hH]([0-9a-fA-F_]+)\s*$")
_BIN_RE = re.compile(r"^\s*0[bB]([01_]+)\s*$")
_DEC_RE = re.compile(r"^\s*(\d+)\s*$")


def _as_int(value: Any) -> Optional[int]:
    """An address a consumer could decode, or None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    for rx, base in ((_HEX_RE, 16), (_SIZED_RE, 16), (_BIN_RE, 2),
                     (_DEC_RE, 10)):
        m = rx.match(value)
        if m:
            try:
                return int(m.group(1).replace("_", ""), base)
            except ValueError:
                return None
    return None


def find_staged_hdl(project: Path) -> Dict[str, str]:
    """``{filename: text}`` for every HDL document staged under input/.

    Reads the ORIGINAL staged sources rather than Phase 1's converted
    ``input_doc/*.txt``: the conversion drops the ``.sv`` suffix, and the
    harvester keys on the suffix so a datasheet quoting a ``typedef
    enum`` in prose cannot be mistaken for a declaration.
    """
    out: Dict[str, str] = {}
    for base in (project / "input" / "docs", project / "input_doc",
                 project / "input"):
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            if p.suffix.lower() not in _hdlenum.HDL_SUFFIXES:
                continue
            if p.name in out:
                continue
            try:
                out[p.name] = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
    return out


def declared_bindings(project: Path) -> List[Dict[str, Any]]:
    """Every register address binding the staged HDL inputs DECLARE."""
    out: List[Dict[str, Any]] = []
    for enum in _hdlenum.address_map_enums(find_staged_hdl(project)):
        type_name = str(enum.get("type_name") or "")
        src = str(enum.get("source_file") or "")
        for binding in enum.get("bindings") or []:
            out.append({
                "name": str(binding.get("name") or ""),
                "value": binding.get("value"),
                "type_name": type_name,
                "source_file": src,
            })
    return out


def find_l4(project: Path) -> Optional[Path]:
    for cand in (_pl.generated_docs_dir(project) / "L4_REGMAP.json",
                 project / "generated_docs" / "L4_REGMAP.json",
                 project / "L4_REGMAP.json"):
        if cand.is_file():
            return cand
    return None


def carried_registers(l4: Dict[str, Any]) -> Tuple[set, set]:
    """``(names, addresses)`` L4's registers[] actually carries."""
    names: set = set()
    addrs: set = set()
    regs = l4.get("registers")
    if not isinstance(regs, list):
        return names, addrs
    for reg in regs:
        if not isinstance(reg, dict):
            continue
        for key in ("name", "declared_name", "register", "reg_name"):
            v = reg.get(key)
            if isinstance(v, str) and v.strip():
                names.add(v.strip())
        for key in _ADDR_KEYS:
            iv = _as_int(reg.get(key))
            if iv is not None:
                addrs.add(iv)
    return names, addrs


def _waived(project: Path) -> Tuple[bool, str]:
    p = project / "waivers.json"
    if not p.is_file():
        return False, ""
    try:
        d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return False, ""
    raw = d.get(WAIVER_KEY)
    if isinstance(raw, str) and len(raw.strip()) >= WAIVER_MIN_LEN:
        return True, raw.strip()
    if isinstance(raw, dict):
        r = raw.get("rationale") or raw.get("reason") or ""
        if isinstance(r, str) and len(r.strip()) >= WAIVER_MIN_LEN:
            return True, r.strip()
    return False, ""


def evaluate(project: Path) -> Tuple[int, Dict[str, Any]]:
    """``(exit_code, summary)``. Pure: writes nothing, prints nothing."""
    summary: Dict[str, Any] = {"gate": GATE, "project": str(project)}

    declared = declared_bindings(project)
    l4_path = find_l4(project)

    if not declared:
        attach(summary, Denominator(
            unit="register address bindings declared by a staged HDL input",
            examined=0,
            considered=0,
            not_applicable_reason=(
                "no staged HDL input declares an address-valued typedef "
                "enum, so the input states no register-map denominator "
                "for L4 to be measured against")))
        summary["verdict"] = "NOT_APPLICABLE"
        return 2, summary

    if l4_path is None:
        attach(summary, Denominator(
            unit="register address bindings declared by a staged HDL input",
            examined=0,
            considered=len(declared),
            not_applicable_reason=(
                f"the input declares {len(declared)} register address "
                f"binding(s) but no L4_REGMAP.json was emitted, so there "
                f"is nothing to measure them against")))
        summary["verdict"] = "NOT_APPLICABLE"
        summary["declared"] = len(declared)
        return 2, summary

    try:
        l4 = json.loads(l4_path.read_text(encoding="utf-8",
                                          errors="replace"))
    except Exception as exc:
        summary["verdict"] = "FAIL"
        summary["error"] = f"cannot parse {l4_path.name}: {exc}"
        attach(summary, Denominator(
            unit="register address bindings declared by a staged HDL input",
            examined=0,
            considered=len(declared),
            not_applicable_reason=f"L4 did not parse: {exc}"))
        return 1, summary

    names, addrs = carried_registers(l4)
    absent: List[Dict[str, Any]] = []
    for b in declared:
        if b["name"] and b["name"] in names:
            continue
        if isinstance(b["value"], int) and b["value"] in addrs:
            continue
        absent.append(b)

    carried = len(declared) - len(absent)
    attach(summary, Denominator(
        unit="register address bindings declared by a staged HDL input",
        examined=len(declared),
        considered=len(declared),
        details={
            "carried_in_l4": carried,
            "absent_from_l4": len(absent),
            "l4_registers": len(l4.get("registers") or []),
            "declaring_types": sorted({b["type_name"] for b in declared}),
        }))
    summary["declared"] = len(declared)
    summary["carried"] = carried
    summary["absent"] = [
        {"name": b["name"], "address": (f"0x{b['value']:x}"
                                        if isinstance(b["value"], int)
                                        else None),
         "declared_by": b["type_name"], "source_file": b["source_file"]}
        for b in absent[:64]
    ]
    summary["absent_total"] = len(absent)

    if not absent:
        summary["verdict"] = "PASS"
        return 0, summary

    waived, rationale = _waived(project)
    if waived:
        summary["verdict"] = "PASS_WITH_WAIVER"
        summary["waiver_rationale"] = rationale
        return 0, summary

    summary["verdict"] = "FAIL"
    return 1, summary


def render(summary: Dict[str, Any]) -> List[str]:
    """Human lines for the verdict — the denominator on every path."""
    den = summary.get("denominator") or {}
    verdict = summary.get("verdict")
    lines: List[str] = []
    if verdict == "NOT_APPLICABLE":
        lines.append(f"[SKIP] {GATE}: "
                     f"{den.get('not_applicable_reason', '')}")
        return lines
    declared = summary.get("declared", 0)
    carried = summary.get("carried", 0)
    if verdict == "PASS":
        lines.append(f"[PASS] {GATE}: the input declares {declared} "
                     f"register address binding(s) and L4 carries all "
                     f"{carried}")
        return lines
    if verdict == "PASS_WITH_WAIVER":
        lines.append(f"[PASS] {GATE}: waived by waivers.{WAIVER_KEY} "
                     f"({summary.get('absent_total', 0)} of {declared} "
                     f"declared binding(s) absent from L4): "
                     f"{str(summary.get('waiver_rationale', ''))[:70]}…")
        return lines
    if summary.get("error"):
        lines.append(f"[FAIL] {GATE}: {summary['error']}")
        return lines
    lines.append(
        f"[FAIL] {GATE}: the input declares {declared} register address "
        f"binding(s); L4 carries {carried} and is missing "
        f"{summary.get('absent_total', 0)}. Every consumer of L4 builds "
        f"its decode from the registers L4 carries, so a declared "
        f"binding that is absent here is a decode that is never "
        f"generated — and nothing downstream can tell that apart from a "
        f"register the design does not have.")
    for a in (summary.get("absent") or [])[:6]:
        lines.append(f"  • {a['name']} = {a['address']} "
                     f"(declared by {a['declared_by']} in "
                     f"{a['source_file']})")
    lines.append("")
    lines.append("  Fix in Phase 1, not by hand: the address-valued enum "
                 "the input declares must reach L4.registers[].")
    lines.append(f"  Or document the alternative in waivers.json under "
                 f'"{WAIVER_KEY}" (>={WAIVER_MIN_LEN} chars).')
    return lines


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog=GATE, description=__doc__)
    ap.add_argument("project_dir")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[SKIP] {GATE}: {project} is not a directory")
        return 2

    rc, summary = evaluate(project)
    for line in render(summary):
        print(line)
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return rc


if __name__ == "__main__":
    sys.exit(main())
