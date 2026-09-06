#!/usr/bin/env python3
"""l1_pin_bus_width_actionable_check.py — L1 consumer-contract gate.

VERDICT SEMANTICS: **BLOCKS** (exit 1 on FAIL).
------------------------------------------------------------------
Why blocking and not advisory: the artefact this gate protects is the
*top-module port list*. A pin recorded here reaches that list
THROUGH L9 — `phase1_doc_one_shot_runner` promotes each L1 pin's
`{width, msb, lsb, width_symbolic, optional}` into the matching L9 entry, and
`phase2_scaffold_gen.derive_signals` reads `L17.channels[]` then
`L9.top_ports` / `L9.ports`. It never reads `pin_table` (ORGANIC #404
measured `grep -c pin_table` = 0 in both `phase2_scaffold_gen.py` and
`_specrtl_common.py`). The earlier wording here said phase2 derived every
port declaration FROM `L1.pin_table[]` directly; that sent the next author
to the wrong file, which is how #404 cost a day. The gate itself is
unchanged and still correct — L1 is where the width must become actionable.
`l9_rtl_pin_consistency_check` later diffs the emitted RTL back against the
same table.

`phase2_scaffold_gen.derive_signals` is a CONTRACT ORACLE, not a flow step
(#509): no runner and no step of `flow/phase1_phase2_phase3.yaml` calls it,
at any version. It is the executable statement of the derivation a
conforming phase 2 owes, and this gate names it for that reason. So a pin
whose width is not resolvable to an integer is a pin any conforming phase 2
would emit as a 1-bit scalar port — and nothing errors at that moment. The
failure surfaces many steps later as a width-mismatch, a truncated
datapath, or an `l9_rtl_pin_consistency` diff with an opaque cause.
Advising here would reproduce the documented failure mode where a layer
gate said FAIL and the flow continued anyway. So: FAIL => rc 1.

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
is a prose sentence. `int(width)` is impossible, so a conforming phase 2
would emit a 1-bit `x` for what the design's own interface table
declares as an N-bit multiplicand bus.

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


def _resolved_width(
    pin: Dict[str, Any],
    params: Optional[Dict[str, Tuple[int, str]]] = None,
) -> Optional[int]:
    """Bit width the port-list contract can actually be met with, or None.

    Accepts an integer `width`, an integer `msb`/`lsb` pair, or a
    pure-numeric string (`"32"`) — the oracle int()s that successfully.
    A prose string is NOT actionable and returns None.

    Finally, a STRUCTURED symbolic width (`width_symbolic`) is resolved
    against parameter defaults recovered from the design's own inputs.
    See `_symbolic_width_bits` for why that is a different state from
    prose, and for what still fails.
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
    if params:
        bits, _src = _symbolic_width_bits(pin, params)
        if bits is not None:
            return bits
    return None


# --------------------------------------------------------------------
# Structured symbolic width  (`width_symbolic`)
# --------------------------------------------------------------------
# MEASURED, on the three published spm cells and on caravel_user_project:
# this gate was collapsing two OPPOSITE states into one FAIL.
#
#   extraction FAILED     caravel `irq`:
#       width=None, width_symbolic=None, msb=None, lsb=None
#       The design's own inputs index bit 2, so it is >= 3 bits, and
#       nothing in L1 says so. A conforming phase 2 really would emit a
#       1-bit port. This is a real defect and MUST keep failing.
#
#   extraction SUCCEEDED  spm `x`:
#       width='N-bit(`[size-1:0]`,parameter `size` ...)'   <- prose
#       width_symbolic='size-1:0'                          <- STRUCTURED
#       The width is not missing; it is legitimately PARAMETERISED,
#       which is what the design's own interface table declares.
#
# The second was reported with the first's words ("no port declaration
# can be emitted from") while the cell's own committed artefacts show
# one was: phase2 emitted `input wire [size-1:0] x` and the synthesised
# netlist carries `input [31:0] x`, through to signed-off GDS.
#
# `width_symbolic` was merged by the extractor (see the module docstring)
# but no code path here ever read it. Requiring an integer on this shape
# also asks L1 to hard-code the one thing the spec declares parametric.
#
# The teeth are preserved by resolving rather than excusing: the symbolic
# range must name parameters whose DEFAULTS are recoverable from the
# design's own inputs. A `width_symbolic` naming a parameter nobody
# defines still yields None, and still FAILs — otherwise "has a
# width_symbolic" would become a new rubber stamp.

# `parameter size = 32`, `localparam int W = 8`, `parameter logic [3:0] N = 4`
_HDL_PARAM_DEF = re.compile(
    r"\b(?:parameter|localparam)\b[^=;\n]*?"
    r"(?<![A-Za-z0-9_])([A-Za-z_]\w*)\s*=\s*(\d+)")
# A doc table row whose first cell is the parameter name and whose next
# cell is a bare integer:  | `size` | 32 | typical 8/16/32 ... |
_DOC_PARAM_ROW = re.compile(
    r"^\s*\|\s*`?([A-Za-z_]\w*)`?\s*\|\s*`?(\d+)`?\s*\|", re.MULTILINE)
# One identifier with an optional integer offset: `size-1`, `W`, `N+1`.
_SYM_TERM = re.compile(r"^\s*([A-Za-z_]\w*)\s*(?:([+-])\s*(\d+)\s*)?$")


def derive_parameter_defaults(
    project: Path,
) -> Dict[str, Tuple[int, str]]:
    """Parameter -> (default, dialect) from the design's OWN inputs.

    Two dialects, because the input corpus differs: HDL sources declare
    `parameter size = 32`; docs-only designs (no RTL staged) carry the
    same fact as an interface-table row. Nothing about any design, PDK
    or vendor is hardcoded — both patterns are grammar, not literals.

    HDL wins over a doc row when both name the same parameter: a
    declaration is stronger evidence than a table cell, whose column
    could in principle be a minimum rather than a default. The dialect
    is returned with the value so the report can disclose which was
    used and a reader can audit the weaker one.
    """
    out: Dict[str, Tuple[int, str]] = {}
    for path in _iter_input_files(project):
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        for m in _DOC_PARAM_ROW.finditer(text):
            name, val = m.group(1), int(m.group(2))
            if name.lower() in _HDL_KEYWORDS:
                continue
            out.setdefault(name, (val, "doc-table"))
        for m in _HDL_PARAM_DEF.finditer(text):
            name, val = m.group(1), int(m.group(2))
            if name.lower() in _HDL_KEYWORDS:
                continue
            prev = out.get(name)
            if prev is None or prev[1] != "hdl-declaration":
                out[name] = (val, "hdl-declaration")
    return out


def _eval_term(term: str, params: Dict[str, Tuple[int, str]]) -> Optional[int]:
    """`32` / `size` / `size-1` -> int, using ONLY known parameters.

    Deliberately not an expression evaluator: one identifier with an
    optional integer offset covers the port-declaration grammar, and
    anything richer is left unresolved rather than guessed.
    """
    term = term.strip().strip("`").strip()
    if re.fullmatch(r"\d+", term):
        return int(term)
    m = _SYM_TERM.match(term)
    if not m:
        return None
    hit = params.get(m.group(1))
    if hit is None:
        return None
    val = hit[0]
    if m.group(2):
        off = int(m.group(3))
        val = val + off if m.group(2) == "+" else val - off
    return val


def _symbolic_width_bits(
    pin: Dict[str, Any], params: Dict[str, Tuple[int, str]]
) -> Tuple[Optional[int], Optional[str]]:
    """Resolve `width_symbolic` ("size-1:0") to a bit count, or None."""
    ws = pin.get("width_symbolic")
    if not isinstance(ws, str) or ":" not in ws:
        return None, None
    hi_s, _, lo_s = ws.strip().strip("[]").partition(":")
    hi, lo = _eval_term(hi_s, params), _eval_term(lo_s, params)
    if hi is None or lo is None:
        return None, None
    bits = abs(hi - lo) + 1
    if bits <= 0:
        return None, None
    used = sorted({m.group(1) for m in (_SYM_TERM.match(hi_s.strip()),
                                        _SYM_TERM.match(lo_s.strip())) if m}
                  & set(params))
    dialects = sorted({params[n][1] for n in used}) or ["literal"]
    src = "%s via %s" % (
        ", ".join("%s=%d" % (n, params[n][0]) for n in used) or ws,
        "+".join(dialects))
    return bits, src


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
        # A PUBLISHED CELL has no `input/` of its own — the design input is
        # shared once per IC at `ic/<IC>/input/`, one level up from
        # `ic/<IC>/v<ver>_<PDK>/`. Without this the symbolic resolution can
        # never find the parameter in the layout the repository actually
        # publishes: measured on `spm/v1.5.58_ihp-sg13g2`, the resolver saw
        # no inputs at all and the cell still FAILed, while `size = 32` sits
        # in `ic/spm/input/docs/L3_external_interface.md` line 31. A fix that
        # only reaches source run directories leaves the deliverable — the
        # thing this repo points at — exactly as it was.
        root = project.parent / "input"
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


def _declared_range_covers(pin: Dict[str, Any], index: int) -> bool:
    """Does the pin's DECLARED bit range contain the index the design uses?

    `lower` above is a minimum WIDTH derived from the highest index the design's
    own text touches, and that derivation silently assumes lsb 0. A spec that
    writes `A[32:1]: 32-bit input operand A` states a 32-bit port whose bits run
    1..32 — it indexes bit 32 and is NOT 33 bits wide, and reading its width
    against a 0-based bound reported "the design's own inputs index bit 32 of A
    (>= 33 bits) but L1 declares 32 bits" about a row that came verbatim from
    that same sentence. When the row carries real msb/lsb integers the honest
    test is containment, not a width count. A row that declares no range still
    falls through to the width test, and a declared range that does NOT reach
    the index (`[30:1]` against bit 32) still violates.
    """
    msb, lsb = pin.get("msb"), pin.get("lsb")
    if (not isinstance(msb, int) or not isinstance(lsb, int)
            or isinstance(msb, bool) or isinstance(lsb, bool)):
        return False
    return min(msb, lsb) <= index <= max(msb, lsb)


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
    params = derive_parameter_defaults(project)

    violations: List[Dict[str, Any]] = []
    resolved_symbolically: List[Dict[str, Any]] = []
    bus_confirmed = 0
    for pin in pin_table:
        if not isinstance(pin, dict):
            continue
        name = pin.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        name = name.strip()
        got = _resolved_width(pin, params)
        lower = numeric.get(name)
        # Disclose every width that came from a resolved parameter rather
        # than from an integer L1 already carried: it is the weaker of the
        # two provenances and a reader must be able to audit the number.
        if got is not None and _resolved_width(pin) is None:
            _bits, _src = _symbolic_width_bits(pin, params)
            if _bits is not None:
                resolved_symbolically.append({
                    "pin": name, "bits": _bits,
                    "width_symbolic": pin.get("width_symbolic"),
                    "resolved_from": _src,
                })

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
                        f"a conforming phase 2 would emit a 1-bit port."),
                })
            elif got < lower and not _declared_range_covers(pin, lower - 1):
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
        "symbolic_widths_resolved": resolved_symbolically,
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
        f"width a conforming phase 2 could emit a port declaration from."))
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
