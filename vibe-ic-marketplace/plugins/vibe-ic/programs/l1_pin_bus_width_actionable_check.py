#!/usr/bin/env python3
"""l1_pin_bus_width_actionable_check.py — L1 consumer-contract gate.

VERDICT SEMANTICS: **BLOCKS** (exit 1 on FAIL).
------------------------------------------------------------------
Why blocking and not advisory: the artefact this gate protects is the
*top-module port list*. Phase2 (`programs/_specrtl_common.py`,
`programs/phase2_scaffold_gen.py`) derives every port DECLARATION from
`L1.pin_table[]`, and `l9_rtl_pin_consistency_check` later diffs that
emitted RTL back against the same table. A pin whose width is not
resolvable to an integer is emitted as a 1-bit scalar port. Nothing
downstream errors at that moment — the failure surfaces many steps
later as a width-mismatch, a truncated datapath, or an
`l9_rtl_pin_consistency` diff with an opaque cause. Advising here
would reproduce the documented failure mode where a layer gate said
FAIL and the flow continued anyway. So: FAIL => rc 1.

The principle it embodies
------------------------------------------------------------------
A layer is complete when the requirement is present IN THE LAYER THAT
CONSUMES IT, IN AN ACTIONABLE FORM — not when a token appears
somewhere.

The pre-existing L1 gates are token/typed-schema shaped:
  * `l1_pin_table_aliases_typed_check` — asserts the KEYS
    name/mode/aliases EXIST per entry.
  * `l1_electrical_specs_typed_depth_check` — same shape for
    electrical_specs[].
Neither asks whether the VALUE in the width field is something a port
declaration can be emitted from. Measured on real Phase-1 output
(campaign_v1544..v1578, `spm`, 13 independent runs) L1 carried:

    {"name": "x", "width": "N-bit(`[size-1:0]`,parameter `size` ...)",
     "msb": null, "lsb": null}

`width` is PRESENT — a presence-shaped check reports CAPTURED — but it
is a prose sentence. `int(width)` is impossible, so phase2 emits a
1-bit `x` for what the design's own interface table declares as an
N-bit multiplicand bus.

What is derived, and from what
------------------------------------------------------------------
NOTHING about which pins are buses is hardcoded. No design name, PDK
name, vendor part number or pin literal appears in this file. For each
pin name that L1 itself declares, the gate scans the design's OWN
machine-readable inputs under `input/` (its RTL/SV, LEF, constraint
and doc files) for that pin name followed by a bit range, and derives:

Both orderings are recognised, because the two input dialects differ:
HDL sources declare `output logic [31:0] name` (range BEFORE name)
while doc interface tables and part-selects write `name[31:0]` (range
AFTER name).

  NUMERIC bus evidence   `name[31:0]`, `[23:0] name`
      Bit ranges also appear as PART-SELECTS of a wider bus
      (`boot_addr_i[31:8]` slices a 32-bit port), so a numeric range
      is treated as a LOWER BOUND only: the port must be at least
      `max(msb)+1` bits. Requiring equality here was measured to
      false-positive on a real run and was dropped.

  SYMBOLIC bus evidence  `name[size-1:0]`, `[DEPTH-1:0] name`
      Parameterised bus: proves multi-bit, gives no number. The gate
      then requires only that L1 resolve SOME positive integer width.

  SELF evidence          L1's own width/msb/lsb value is a string that
      contains a bit range. The extractor saw a bus and stored prose.

Pins with no bus evidence in the design's own inputs are NOT asserted
on at all. That is deliberate: a scalar interrupt line or an analog
supply pad legitimately has no width, and firing on those was measured
to produce 25/47 (ibex) and 22/22 (an analog ADC) false hits.

Verdicts
------------------------------------------------------------------
  PASS         every bus-confirmed pin resolves to an actionable width
  VACUOUS_PASS no pin_table, or no pin is bus-confirmed by the inputs
  FAIL         a bus-confirmed pin has no integer width, or its
               integer width is below a bound the inputs prove
  rc 2         L1 absent / unparseable / project dir absent

Waiver: `waivers.json` key `l1_pin_bus_width_unresolvable` (>= 40
chars of justification) downgrades FAIL to PASS_WITH_WAIVER.

Usage:
    python3 l1_pin_bus_width_actionable_check.py <project_dir> [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _path_layout as _pl  # noqa: E402

GATE = "l1_pin_bus_width_actionable_check"
WAIVER_KEY = "l1_pin_bus_width_unresolvable"
WAIVER_MIN_LEN = 40

# Text-bearing machine-readable design inputs. Binary formats (pdf,
# pptx, gds) are skipped — their extracted text already lands in
# input/docs as .txt/.md by the time phase1 runs.
_TEXT_SUFFIXES = frozenset({
    ".v", ".sv", ".vh", ".svh", ".vhd", ".vhdl",
    ".rst", ".md", ".txt", ".csv", ".tsv", ".json", ".yaml", ".yml",
    ".lef", ".def", ".xdc", ".sdc", ".qsf", ".tcl", ".cfg", ".ini",
    ".h", ".c", ".py", "",
})
_MAX_INPUT_BYTES = 8 * 1024 * 1024   # skip pathological blobs
_MAX_PIN_NAMES = 4096                # regex-explosion guard

# A bit range: `[ <a> : <b> ]` with short, bracket-free endpoints.
_RANGE_BODY = r"\[\s*([^\]\[:]{1,48}?)\s*:\s*([^\]\[:]{1,48}?)\s*\]"
_RANGE_ANY = re.compile(_RANGE_BODY)
# HDL declaration ordering: `[31:0] name`. One global regex; the captured
# identifier is then filtered against the pin-name set, so a range that
# precedes an unrelated token contributes nothing. Only spaces/tabs may
# separate the two — allowing a newline would bind a range at the end of
# one declaration to the identifier starting the next.
_RANGE_THEN_NAME = re.compile(_RANGE_BODY + r"[ \t]*([A-Za-z_]\w*)")

# Characters that, immediately before a pin name, mean the token is NOT a
# standalone signal reference. Measured false positive: a real design's L8
# doc writes the shorthand `io_in/out/oeb[37:0]` to mean "io_in, io_out and
# io_oeb are all [37:0]". Matching the bare tail `oeb` there invented a
# 38-bit bus for an unrelated stub row. `.` is excluded for the same reason
# (`struct.field[3:0]` / `pkg::x.y[3:0]` is a member, not the port).
_LEFT_BOUNDARY = r"(?<![A-Za-z0-9_/.\\-])"

# HDL keywords can never be soundly matched by this derivation: the text
# `output [Width-1:0]` is the DECLARATION SYNTAX of some other port, not a
# reference to a signal named `output`. When an upstream extractor emits a
# junk pin_table row named after a keyword (measured on a real run: rows
# literally named `output`, `logic` and `input`), matching it against every
# port declaration in the design invents buses that do not exist. Skipping
# these names is chip-AGNOSTIC — it is a property of the HDL grammar, not
# of any design, PDK or vendor.
_HDL_KEYWORDS = frozenset({
    "input", "output", "inout", "ref", "logic", "wire", "reg", "bit",
    "byte", "int", "integer", "shortint", "longint", "time", "real",
    "signed", "unsigned", "tri", "wand", "wor", "supply0", "supply1",
    "parameter", "localparam", "genvar", "var", "type", "struct", "union",
    "enum", "packed", "const", "static", "automatic", "assign", "port",
    "signal", "std_logic", "std_logic_vector", "downto", "upto", "bus",
})


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _resolved_width(pin: Dict[str, Any]) -> Optional[int]:
    """Bit width the port-list consumer can actually emit, or None.

    Accepts an integer `width`, an integer `msb`/`lsb` pair, or a
    pure-numeric string (`"32"`) — phase2 int()s that successfully.
    A prose string is NOT actionable and returns None.
    """
    w = pin.get("width")
    if _is_int(w) and w > 0:
        return w
    if isinstance(w, str) and re.fullmatch(r"\s*\d+\s*", w):
        n = int(w.strip())
        if n > 0:
            return n
    msb, lsb = pin.get("msb"), pin.get("lsb")
    if _is_int(msb) and _is_int(lsb):
        return abs(msb - lsb) + 1
    return None


def _pin_names(pin_table: List[Any]) -> List[str]:
    out: List[str] = []
    for p in pin_table:
        if isinstance(p, dict):
            n = p.get("name")
            if isinstance(n, str) and n.strip():
                out.append(n.strip())
    return out


def _iter_input_files(project: Path):
    root = project / "input"
    if not root.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in {".git", "node_modules", "__pycache__"}]
        for fn in filenames:
            p = Path(dirpath) / fn
            if p.suffix.lower() not in _TEXT_SUFFIXES:
                continue
            try:
                if p.stat().st_size > _MAX_INPUT_BYTES:
                    continue
            except OSError:
                continue
            yield p


def derive_bus_evidence(
    project: Path, names: List[str]
) -> Tuple[Dict[str, int], Set[str], int]:
    """Scan the design's own inputs for `<pin>[a:b]` occurrences.

    Returns (numeric_lower_bound_by_pin, symbolic_bus_pins, files_read).
    `numeric_lower_bound_by_pin[n] = max(msb)+1` over every numeric
    range seen for that pin — a LOWER BOUND, because the occurrence may
    be a part-select of a wider bus rather than a declaration.
    """
    numeric: Dict[str, int] = {}
    symbolic: Set[str] = set()
    if not names:
        return numeric, symbolic, 0
    wanted = {n for n in names[:_MAX_PIN_NAMES]
              if n.lower() not in _HDL_KEYWORDS}
    by_name = {n: re.compile(
        _LEFT_BOUNDARY + re.escape(n) + r"\s*" + _RANGE_BODY)
        for n in wanted}

    def _record(name: str, a: str, b: str) -> None:
        a, b = a.strip().strip("`"), b.strip().strip("`")
        if a.isdigit() and b.isdigit():
            hi = max(int(a), int(b))
            if hi + 1 > numeric.get(name, 0):
                numeric[name] = hi + 1
        else:
            symbolic.add(name)

    files = 0
    for path in _iter_input_files(project):
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        files += 1
        # `name[a:b]` — doc interface tables, part-selects.
        for name, pat in by_name.items():
            if name not in text:      # cheap prefilter
                continue
            for m in pat.finditer(text):
                _record(name, m.group(1), m.group(2))
        # `[a:b] name` — HDL port/net declarations.
        for m in _RANGE_THEN_NAME.finditer(text):
            name = m.group(3)
            if name in wanted:
                _record(name, m.group(1), m.group(2))
    return numeric, symbolic, files


def _self_declares_bus(pin: Dict[str, Any]) -> bool:
    """L1's own width/msb/lsb value is prose carrying a bit range."""
    for key in ("width", "msb", "lsb"):
        v = pin.get(key)
        if isinstance(v, str) and _RANGE_ANY.search(v):
            return True
    return False


def _waived(project: Path) -> bool:
    p = project / "waivers.json"
    if not p.is_file():
        return False
    try:
        v = json.loads(p.read_text()).get(WAIVER_KEY, "")
    except Exception:
        return False
    return isinstance(v, str) and len(v.strip()) >= WAIVER_MIN_LEN


def evaluate(project: Path) -> Dict[str, Any]:
    l1_path = _pl.generated_docs_dir(project) / "L1_DATASHEET.json"
    if not l1_path.is_file():
        return {"gate": GATE, "verdict": "SILENT_SKIP", "rc": 2,
                "reason": f"{l1_path.name} not found (phase1 hasn't run?)"}
    try:
        l1 = json.loads(l1_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"gate": GATE, "verdict": "ERROR", "rc": 2,
                "reason": f"cannot parse {l1_path.name}: {exc}"}

    pin_table = l1.get("pin_table")
    if not isinstance(pin_table, list) or not pin_table:
        return {"gate": GATE, "verdict": "VACUOUS_PASS", "rc": 0,
                "reason": "L1.pin_table empty/absent — no port set to "
                          "derive a top module from.",
                "pins": 0, "bus_confirmed": 0, "violations": []}

    names = _pin_names(pin_table)
    numeric, symbolic, files_read = derive_bus_evidence(project, names)

    violations: List[Dict[str, Any]] = []
    bus_confirmed = 0
    for pin in pin_table:
        if not isinstance(pin, dict):
            continue
        name = pin.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        name = name.strip()
        got = _resolved_width(pin)
        lower = numeric.get(name)

        if lower is not None and lower > 1:
            bus_confirmed += 1
            if got is None:
                violations.append({
                    "pin": name, "kind": "bus_width_unresolvable",
                    "derived_from": "numeric bit range in design inputs",
                    "required_min_bits": lower,
                    "l1_width": pin.get("width"),
                    "detail": (
                        f"the design's own inputs index bit {lower - 1} of "
                        f"`{name}`, so it is at least {lower} bits wide, but "
                        f"L1 carries width={pin.get('width')!r} / "
                        f"msb={pin.get('msb')!r} / lsb={pin.get('lsb')!r} — "
                        f"phase2 emits a 1-bit port."),
                })
            elif got < lower:
                violations.append({
                    "pin": name, "kind": "bus_width_below_input_bound",
                    "derived_from": "numeric bit range in design inputs",
                    "required_min_bits": lower, "l1_width": got,
                    "detail": (
                        f"the design's own inputs index bit {lower - 1} of "
                        f"`{name}` (>= {lower} bits) but L1 declares "
                        f"{got} bits."),
                })
        elif name in symbolic or _self_declares_bus(pin):
            bus_confirmed += 1
            if got is None:
                src = ("parameterised bit range in design inputs"
                       if name in symbolic
                       else "L1's own width field carries a bit range as prose")
                violations.append({
                    "pin": name, "kind": "bus_width_unresolvable",
                    "derived_from": src, "required_min_bits": None,
                    "l1_width": pin.get("width"),
                    "detail": (
                        f"`{name}` is declared as a multi-bit bus ({src}) but "
                        f"L1 carries width={pin.get('width')!r} / "
                        f"msb={pin.get('msb')!r} / lsb={pin.get('lsb')!r}, "
                        f"which no port declaration can be emitted from."),
                })

    report: Dict[str, Any] = {
        "gate": GATE,
        "pins": len(pin_table),
        "input_files_scanned": files_read,
        "bus_confirmed": bus_confirmed,
        "violations": violations,
    }
    if not violations:
        if bus_confirmed == 0:
            report.update(verdict="VACUOUS_PASS", rc=0, reason=(
                f"no pin in L1.pin_table ({len(pin_table)} entries) is "
                f"bus-confirmed by the design's own inputs "
                f"({files_read} file(s) scanned) — nothing to assert."))
        else:
            report.update(verdict="PASS", rc=0, reason=(
                f"{bus_confirmed} bus-confirmed pin(s) all resolve to an "
                f"actionable integer bit width."))
        return report
    if _waived(project):
        report.update(verdict="PASS_WITH_WAIVER", rc=0, reason=(
            f"{len(violations)} unactionable bus width(s) waived via "
            f"waivers.json:{WAIVER_KEY}."))
        return report
    report.update(verdict="FAIL", rc=1, reason=(
        f"{len(violations)}/{bus_confirmed} bus-confirmed pin(s) carry no "
        f"width phase2 can emit a port declaration from."))
    return report


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog=GATE, description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None, help="write JSON verdict here")
    args = ap.parse_args(argv)

    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2

    report = evaluate(project)
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")

    rc = int(report.get("rc", 2))
    line = f"{report['verdict']}: {report['reason']}"
    if rc == 1:
        print(f"FAIL: {report['reason']}", file=sys.stderr)
        for v in report.get("violations", [])[:8]:
            print(f"  - {v['pin']}: {v['detail']}", file=sys.stderr)
    elif rc == 2:
        print(line, file=sys.stderr)
    else:
        print(line)
    return rc


if __name__ == "__main__":
    sys.exit(main())
