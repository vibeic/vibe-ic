#!/usr/bin/env python3
"""slot_pad_budget_check — does this design's interface FIT the purchased slot?

ENFORCEMENT: blocking
=====================
A DOES_NOT_FIT verdict (rc 1) FAILs the step that guards it. The declaration
opens this line deliberately: `flow_gate_enforcement_audit` reads it anchored,
and a mention inside a sentence is not a declaration (#886).

Blocking is only true because `design_one_shot_runner.step_slot_pad_budget`
SPAWNS this program and maps its exit status to the step verdict. The
`program_exit_zero` clause in the flow definition is not, by itself, enough:
those clauses are evaluated by `flow_compliance_check`, which the runner
invokes as `final_audit` -- the LAST step, after every artefact is written.
That is the measured #306 defect, and a gate wired only in the YAML can
describe a run that already happened but cannot refuse one.

WHAT BLOCKING DOES NOT YET MEAN. The FAIL reddens the step and the run's
aggregate verdict; it does not itself skip Phase 3. Making a pad-budget
refusal cascade into "do not place and route this" is a policy change to the
runner's step plan and is left to the maintainer, named here rather than
implied.

WHY THIS EXISTS
===============
MEASURED (gf180mcuD chip-path campaign, 2026-08-20). Nine benchmark ICs were
taken down the chip path. Five of them cannot be bonded out on ANY purchasable
slot, and every one of those five was discovered by running a build until it hit
a wall — hours of synthesis, placement and routing to learn an arithmetic fact
that was decidable in two seconds from files the flow had ALREADY ingested at
step 0.5ic.

    IC                       declared signal bits    largest slot     ratio
    caravel_user_project     637                     52               12.2x
    opentitan_aes            515                     52                9.9x
    ibex                     262                     52                5.0x
    edge_llm_accel           120                     52                2.3x
    edge_llm_matmul_accel    109                     52                2.1x

THE LAST ROW READ 107 UNTIL IT WAS RE-MEASURED. It is 109, and the two bits are
worth the paragraph because they are a rule, not a typo. That design declares
TWO clocks and TWO resets -- its own `clk`/`rst_n` and a bus-side pair. A slot
publishes ONE dedicated clock pad and ONE dedicated reset pad, so exactly one of
each rides for free and the SECOND pair must consume signal budget like any
other port. Counting them is what makes 109.

Do not "fix" the clk/rst recogniser to match the bus-side spellings. Excluding a
port declares that a dedicated pad exists for it, which SHRINKS the budget, and
a smaller interface is how a design that cannot be bonded out reads as FITS.
Over-counting a clock can only refuse a design that would have fitted; the
inverse silently ships one that cannot be bonded. There is a test pinning the
second pair as counted.

THOSE ARE ELABORATED COUNTS, and saying so costs one line and saves a reader an
hour. Every figure above assumes the design's width parameters were SUPPLIED.
Run the same design without them and this program does not return a smaller
number -- it returns UNDECIDED, because a width nobody supplied is not a pad
count it may invent. Re-measured on the published corpus: the first row sums to
502 of its elaborated total with four widths unresolved, and the verdict is
UNDECIDED, not a 502-bit refusal. A reader who compares an unelaborated run
against this table and finds it short has found that rule, not a defect.

The pad inventory is not a guess and not a constant written into this file: step
0.5ic ingests the shuttle operator's own slot files, and each one LISTS ITS PADS
BY INSTANCE, per die side. This gate counts them.

THE OTHER HALF — A FIT THAT NEEDS A BOND-OUT DECISION, NAMED NOT TAKEN
=======================================================================
`sha256` declares 75 signal bits against 52 pads and LOOKS unbuildable by the
arithmetic above. It fits, and it now has silicon-shaped evidence that it fits,
because `write_data[31:0]` and `read_data[31:0]` are never live in the same
transaction and bond onto ONE 32-bit bidirectional bus turned around by the
design's own `cs & ~we`:

    75 declared  ->  32 (shared bus) + cs + we + address[7:0] + error  =  43   <= 52

So the arithmetic alone would have REFUSED a design that a competent bond-out
fits. This gate therefore reports FOLD CANDIDATES — a same-width input bus and
output bus that could share one bidirectional group — and it does NOT apply
them and does NOT assert that any particular pair is safe to fold. Whether two
buses are ever simultaneously active is a PROTOCOL fact about the design; the
candidate list is decidable, the safety is not, and this program does not
pretend otherwise. A candidate is an invitation to a human decision, recorded
with the enable signals that could drive it.

WHAT IS DECIDED, AND WHAT IS NOT
================================
    DECIDED    the pad inventory of every ingested slot, by role, by counting
               the operator's own per-side pad instance lists
    DECIDED    the design's declared top-level signal-bit count
    DECIDED    fits / does not fit / does not fit but has fold candidates
    NOT DECIDED whether a fold candidate is protocol-safe
    NOT DECIDED anything about area, timing or routability -- a design can fit
               the pads and still not fit the die

VERDICTS AND EXIT CODES
=======================
    FITS               rc 0   the declared interface fits a slot as declared
    FITS_AFTER_FOLD    rc 0   fits only if a named fold is taken; the fold is
                              NOT applied here and the candidates are listed
    DOES_NOT_FIT       rc 1   no slot can bond it, even after folding every
                              same-width in/out pair -- with the shortfall
    UNDECIDED          rc 2   no slots ingested, or no port list could be read.
                              A question that could not be asked has not passed.
    (usage error)      rc 3   the COMMAND LINE was rejected -- an unknown flag,
                              a missing positional, a `--param` value that is
                              not an integer, or a `--json` destination that
                              climbs out of the project. NOTHING was examined,
                              and that is a verdict about the CALLER, not about
                              the design.

rc 2 is the flow's "could not measure" tier. It is NEVER returned for a design
that simply does not fit: that is an answer, and it is rc 1.

rc 3 AND rc 2 ARE DIFFERENT ON PURPOSE (#712). argparse exits 2 by default, and
2 is the vacuous tier here, so a mistyped invocation would have reported "I
examined nothing" -- indistinguishable from the honest skip a cell/IP design
gets. `_gate_usage_exit.GateArgumentParser` moves it to 3, which the flow reads
as a FAIL rather than folding into a pass. `--help` still exits 0: that is a
successful invocation and must not read as a failure to a wrapper.

Chip-, PDK-, operator- and vendor-AGNOSTIC. Every number comes from the ingested
slot files and the design's own RTL at runtime. No slot geometry, pad count,
cell name or design identifier is written into this file.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _atomic_artefact import write_json  # noqa: E402  vibe-ic#1082
import _gate_usage_exit as _usage  # noqa: E402  vibe-ic#712
import _l_doc_pad_placement as _LPP  # noqa: E402  R-0915-101
import _flow_reason_taxonomy as _reason_taxonomy  # noqa: E402
import _submission_template as _ST  # noqa: E402  vibe-ic#2277
import _tapeout_declaration as _TD  # noqa: E402  vibe-ic#2277
import submission_template_check as _stc  # noqa: E402  vibe-ic#2277

# --------------------------------------------------------------------------- #
# pad roles -- derived from the operator's OWN instance names, never assumed
# --------------------------------------------------------------------------- #
# A slot file names each pad by the INSTANCE that carries it, e.g. a generate
# block's `bidir[7].pad`. The role is the identifier the operator chose for the
# group. These patterns read that identifier; anything that matches none of them
# is counted as UNCLASSIFIED and REPORTED -- an unclassified pad silently
# dropped would inflate or deflate the budget and nobody would see it.
_ROLE_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("bidir",  re.compile(r"^(?:bidir|inout|io|bidi)\b", re.I)),
    ("input",  re.compile(r"^(?:inputs?|in)\b", re.I)),
    ("analog", re.compile(r"^(?:analog|analogue|asig)\b", re.I)),
    ("power",  re.compile(r"^(?:d?v(?:dd|ss|cc|ee)|vpwr|vgnd|gnd|power|ground)\w*", re.I)),
    ("clock",  re.compile(r"^(?:clk|clock)\b", re.I)),
    ("reset",  re.compile(r"^(?:rst|reset)\w*", re.I)),
    ("corner", re.compile(r"^(?:corner|cor)\b", re.I)),
    ("filler", re.compile(r"^(?:fill|filler)\w*", re.I)),
)

#: Ports that ride a dedicated pad the slot provides anyway, so they never
#: consume signal-pad budget. Matched on the WHOLE port name.
_CLK_RST_RE = re.compile(
    r"^(?:i_)?(?:clk|clock|rst|reset)(?:_?[a-z0-9]{0,4})?(?:_[nip])?$", re.I)

_SIDE_KEYS = ("PAD_SOUTH", "PAD_EAST", "PAD_NORTH", "PAD_WEST")


def _pad_entries(slot_obj: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """Every pad instance in one slot file, and the side keys they came from.

    TWO SHAPES, because there are two, and assuming one was a measured zero:

      * the INGESTED shape that `submission_template_ingest` writes -- the pad
        lists normalised under ``pads.lists[] = {key, raw[], count}``. This is
        the shape a real project on the chip path has, because 0.5ic put it
        there, and reading it is what makes this gate operator-AGNOSTIC: the
        ingester already did the normalisation.
      * the RAW operator shape -- top-level ``PAD_<SIDE>`` keys -- so the gate
        can also be pointed straight at an un-ingested template.

    Measured the hard way: reading only the raw shape against a real ingested
    project returned ZERO pads, and the verdict came back DOES_NOT_FIT with
    ``largest slot digital signal pads: 0``. An unmeasured thing had become a
    measured zero and the answer looked authoritative. Hence both shapes here,
    and the explicit zero-guard in :func:`evaluate`.
    """
    entries: List[str] = []
    sides: List[str] = []
    pads = slot_obj.get("pads")
    if isinstance(pads, dict) and isinstance(pads.get("lists"), list):
        for lst in pads["lists"]:
            if not isinstance(lst, dict):
                continue
            raw = lst.get("raw") or []
            if raw:
                sides.append(str(lst.get("key")))
                entries.extend(str(x) for x in raw)
    if not entries:
        for key in _SIDE_KEYS:
            raw = slot_obj.get(key) or []
            if raw:
                sides.append(key)
                entries.extend(str(x) for x in raw)
    return entries, sides


def _pad_role(instance: str) -> str:
    """The role of one pad instance name, or ``unclassified``."""
    # Strip the operator's escaping and the trailing member selector: a name
    # like `bidir\[7\].pad` is the 7th member of the `bidir` group.
    head = re.sub(r"\\", "", str(instance)).strip()
    head = re.split(r"[\[.]", head, 1)[0]
    # An operator names the INSTANCE, and the instance usually carries the
    # word "pad": `clk_pad`, `dvdd_pads`. Strip that suffix before matching --
    # `_` is a word character, so a `\b` anchor after `clk` does NOT match
    # `clk_pad`, and `clk_pad` came back UNCLASSIFIED on the first run.
    head = re.sub(r"_pads?$", "", head)
    for role, pat in _ROLE_PATTERNS:
        if pat.match(head):
            return role
    return "unclassified"


def slot_pad_inventory(slot_obj: Dict[str, Any]) -> Dict[str, Any]:
    """Count one slot's pads by role from its own per-side instance lists."""
    counts: Dict[str, int] = {}
    unclassified: List[str] = []
    entries, sides = _pad_entries(slot_obj)
    total = 0
    for entry in entries:
        total += 1
        role = _pad_role(entry)
        counts[role] = counts.get(role, 0) + 1
        if role == "unclassified" and len(unclassified) < 24:
            unclassified.append(str(entry))
    digital = counts.get("bidir", 0) + counts.get("input", 0)
    return {
        "pads_total": total,
        "by_role": counts,
        "digital_signal_pads": digital,
        "analog_pads": counts.get("analog", 0),
        "unclassified_examples": unclassified,
        "sides_present": sides,
    }


# --------------------------------------------------------------------------- #
# the design's declared interface
# --------------------------------------------------------------------------- #
def _strip_hdl_comments(text: str) -> str:
    """Verilog comments removed in ONE left-to-right pass.

    WHY A PASS AND NOT TWO SUBSTITUTIONS (vibe-ic#731)
    --------------------------------------------------
    This was `re.sub("//[^\\n]*")` followed by `re.sub("/\\*.*?\\*/")`. Two
    independent passes cannot express the one rule Verilog actually has:
    whichever introducer opens FIRST owns the text after it. The `//` pass
    runs with no idea a block comment is open, so a `*/` that happens to sit
    behind a `//` is deleted with the line that carries it -- and the block
    comment it terminated then has no terminator left for the second pass to
    find, so the whole block survives into the scanned text.

    MEASURED, on legal Verilog whose real ports are exactly `clk` and `done`:

        input wire clk,   /* disabled,
        output wire phantom,
        // end of the disabled block */
        output wire done

    `phantom` is inside the block comment and does not exist. The two-pass
    strip minted it as an output and counted its bit in the pad budget. That
    is this gate's own founding defect -- a comment sentence minting a
    declaration that is not there -- one level in, and it lands on the number
    the budget verdict is computed from.

    It cuts the other way too, which is the direction that matters more: the
    same orphaned block glues itself to the front of the NEXT real port, the
    chunk no longer starts with a direction keyword, and the port is dropped.
    A dropped port is a smaller interface, and a smaller interface is how a
    design that does not fit its slot reads as FITS.

    Line geometry is preserved -- a block comment is replaced by the newlines
    it spanned -- because the conditional-compilation scan below is
    line-oriented and counts `ifdef`/`endif` nesting by line.

    HONEST LIMIT: string literals are not tracked, so a `//` inside a string
    opens a comment here. That is inherited from the two-pass form this
    replaces, it cannot affect an ANSI port list (which admits no string
    literal), and naming it is better than a lexer this file does not need.
    """
    out: List[str] = []
    i, n = 0, len(text)
    while i < n:
        two = text[i:i + 2]
        if two == "//":
            j = text.find("\n", i)
            if j < 0:
                break
            i = j                      # the newline itself is kept
        elif two == "/*":
            j = text.find("*/", i + 2)
            if j < 0:
                # Unterminated: everything from here on is comment body.
                out.append("\n" * text.count("\n", i))
                break
            out.append("\n" * text.count("\n", i, j + 2))
            i = j + 2
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _strip_hdl_attributes(text: str) -> str:
    """Verilog ATTRIBUTE instances `(* ... *)` removed.

    NOT A COMMENT, and that is exactly why it needed its own repair. An
    attribute is live source that a synthesiser reads, but it is not part of a
    port DECLARATION, and `_DIR_RE` anchors with `^`. So a perfectly ordinary
    port carrying one:

        (* keep = "true" *) input wire clk,

    reaches the scan as a chunk beginning `(*`, matches no direction keyword,
    and is discarded as an unparsable continuation. MEASURED on the two-port
    module above: `clk` vanishes and the interface reads as one port.

    That is the DROPPING direction again -- a smaller interface than the design
    really has -- and it is the one that produces a false FITS. It predates the
    comment repair (identical on the commit before it) and is fixed here
    because it lands on the same number by the same mechanism: text nobody
    stripped reaching a declaration scan.

    `(*` begins an attribute unambiguously in Verilog, and removing the region
    leaves the parenthesis DEPTH of the port list unchanged because the `*)`
    that balanced it goes with it. Newlines are preserved for the same reason
    as in `_strip_hdl_comments`: the conditional scan counts by line.
    """
    out: List[str] = []
    i, n = 0, len(text)
    while i < n:
        if text[i:i + 2] == "(*" and text[i:i + 3] != "(*)":
            j = text.find("*)", i + 2)
            if j < 0:
                out.append(text[i]); i += 1; continue
            out.append("\n" * text.count("\n", i, j + 2))
            i = j + 2
        else:
            out.append(text[i]); i += 1
    return "".join(out)


_DIR_RE = re.compile(r"^(input|output|inout)\b(.*)$", re.S)
_RANGE_RE = re.compile(r"\[\s*([^\]:]+?)\s*:\s*([^\]]+?)\s*\]")


def _token_value(tok: str, params: Optional[Dict[str, int]]) -> Optional[int]:
    """A dimension token's value, or None when it cannot be resolved WITHOUT
    GUESSING. Shared by the packed-range reader and the unpacked-array reader
    so the two cannot disagree about what `BDW-1` means."""
    tok = tok.strip().strip("`")
    try:
        return int(tok, 0)
    except ValueError:
        pass
    # NAME, NAME-1, NAME+1 -- resolved ONLY from caller-supplied values
    mm = re.match(r"^`?([A-Za-z_]\w*)\s*([-+])\s*(\d+)$", tok)
    if mm and params and mm.group(1) in params:
        base = params[mm.group(1)]
        return base - int(mm.group(3)) if mm.group(2) == "-" else base + int(mm.group(3))
    if params and tok in params:
        return params[tok]
    # Use the shared bounded Verilog integer evaluator for compound bounds such
    # as $clog2(memsize)-1. Unknown names still produce None, never a width.
    try:
        from register_bus_driver_gen import _int_expr
        value = _int_expr(re.sub(r"`(?=[A-Za-z_])", "", tok), dict(params or {}))
    except (ImportError, ValueError, TypeError):
        return None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


#: A port INITIALISER -- `output reg rvfi_valid = 1'b0`. Legal, and it sits
#: after the name, so a last-token read returns the literal instead.
_PORT_INIT_RE = re.compile(r"=\s*[^=].*$", re.S)
#: Trailing UNPACKED dimensions -- `csr_pmp_addr_i [PMPNumRegions]`. Also after
#: the name, and unlike a packed range they MULTIPLY the port's bit count.
_UNPACKED_RE = re.compile(r"((?:\s*\[[^\]]*\])+)\s*$")
_DIM_RE = re.compile(r"\[([^\]]*)\]")
#: A packed range written with NO SPACE around it -- `output reg [3:0]one`, or
#: `input wire[7:0]bus` with the type glued on too. Both legal.
#: Legal Verilog, and the range then arrives glued to the identifier as one
#: token, so a last-token read returns `[3:0]one` as the port's name. The WIDTH
#: is unaffected (the range reader searches, it does not tokenise); this is a
#: name-only defect, and a wrong name mis-fires the clk/rst exclusion and the
#: fold-candidate match, both of which key on it. Measured on 4 real ports.
_GLUED_NAME_RE = re.compile(
    r"^(?:[A-Za-z_]\w*(?:::[A-Za-z_]\w*)*)?(?:\[[^\]]*\])+([A-Za-z_]\w*)$")


def split_port_tail(tail: str) -> Tuple[str, List[str]]:
    """`(tail_without_suffixes, unpacked_dimension_texts)`.

    MEASURED over 6,760 module headers of published RTL: 174 ports came back
    named `1'b0`, `64'd0` or `[PMPNumRegions]`. Both causes sit AFTER the port
    name, where a last-token read finds them instead of the name.

    The unpacked case is the one that moves a NUMBER, and it moves it the
    dangerous way. `input logic [33:0] csr_pmp_addr_i [PMPNumRegions]` is
    4 x 34 bits; reading only the packed range reports 34. A smaller interface
    than the design has is how a design that cannot be bonded out reads as
    FITS -- the exact verdict this program exists to refuse.
    """
    t = tail
    m = _UNPACKED_RE.search(t)
    dims: List[str] = []
    if m and t[:m.start()].strip():          # never strip the ONLY token
        dims = _DIM_RE.findall(m.group(1))
        t = t[:m.start()]
    t = _PORT_INIT_RE.sub("", t)
    return t, dims


def unpacked_count(dims: List[str],
                   params: Optional[Dict[str, int]] = None) -> Optional[int]:
    """How many elements the unpacked dimensions describe, or None.

    None is the honest answer for `[PMPNumRegions]` with no supplied value,
    and None reaches the verdict as UNDECIDED rather than as a number this
    program invented -- the same rule `_width` already follows for a
    parameterised packed range.
    """
    total = 1
    for d in dims:
        d = d.strip()
        if ":" in d:
            lo, hi = d.split(":", 1)
            a, b = _token_value(lo, params), _token_value(hi, params)
            if a is None or b is None:
                return None
            total *= abs(a - b) + 1
        else:
            n = _token_value(d, params)
            if n is None:
                return None
            total *= n
    return total


def _width(rest: str, params: Optional[Dict[str, int]] = None) -> Optional[int]:
    """Declared bit width, or None when it cannot be resolved WITHOUT GUESSING.

    A parameterised width (``[BDW-1:0]``, ``[`MPRJ_IO_PADS-1:0]``) resolves only
    if the caller SUPPLIED the parameter value -- the same value the chip_top
    instantiation supplies. Otherwise None, and None must reach the verdict as
    UNDECIDED, because a width this program invented would be a pad count nobody
    chose.

    MEASURED, and this is why the rule is written down: the first draft returned
    None here and then DROPPED those ports from the sum. A design whose entire
    datapath is parameterised (`host_wdata[BDW-1:0]` etc., 120 real bits) summed
    to 31 and the gate answered **FITS**. That is the same unmeasured-reads-as-
    zero failure this file exists to prevent, one level further in, and it is
    the direction that matters: it produced a false PASS.
    """
    m = _RANGE_RE.search(rest)
    if not m:
        return 1
    lo, hi = m.group(1), m.group(2)

    def _val(tok: str) -> Optional[int]:
        return _token_value(tok, params)

    a, b = _val(lo), _val(hi)
    if a is None or b is None:
        return None
    return abs(a - b) + 1


_PARAM_DEFAULT_RE = re.compile(
    r"\bparameter\b(?:\s+(?:integer|int|signed|unsigned|logic|bit))?"
    r"(?:\s*\[[^\]]*\])?\s+([A-Za-z_]\w*)\s*=\s*"
    r"((?:\d+'[dD])?\d+|0[xX][0-9a-fA-F]+)\s*(?=[,)])")


def top_parameter_defaults(text: str, top: str) -> Dict[str, int]:
    """The TOP module's own `#( parameter NAME = <integer literal> )` defaults.

    WHY THEY ARE NOT A GUESS. A module elaborated as the top has no parent to
    override its parameters, so its header defaults ARE the elaboration values
    synthesis builds — the same role `--param` plays for a core a chip_top
    instantiates with overrides. MEASURED on subservient x gf180mcuD (r34, a
    DIE whose top is the core itself): `output wire [AW-1:0] o_sram_addr` with
    `parameter integer AW = 10` answered UNDECIDED, so a die's pad budget was
    never asked, while L9 and the synthesised netlist both carry 10 bits.

    Only plain integer literals are read (`10`, `32'd10`, `0x10`); an
    expression default (`AW = $clog2(MEMSIZE)`) stays unresolved, so the
    UNDECIDED path still owns every width this reader cannot state exactly.
    """
    stripped = _strip_hdl_attributes(_strip_hdl_comments(text))
    m = re.search(r"\bmodule\s+" + re.escape(top) + r"\b\s*(?:import[^;]*;\s*)*#\s*\(",
                  stripped)
    if not m:
        return {}
    depth, end = 1, None
    for n, ch in enumerate(stripped[m.end():], m.end()):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end = n
                break
    if end is None:
        return {}
    block = stripped[m.end():end] + ")"
    out: Dict[str, int] = {}
    for name, lit in _PARAM_DEFAULT_RE.findall(block):
        lit = re.sub(r"^\d+'[dD]", "", lit)
        try:
            out[name] = int(lit, 0)
        except ValueError:
            continue
    return out


_PARAM_EXPR_DEFAULT_RE = re.compile(
    r"\bparameter\b(?:\s+(?:integer|int|signed|unsigned|logic|bit))?"
    r"(?:\s*\[[^\]]*\])?\s+([A-Za-z_]\w*)\s*=\s*"
    r"(\$clog2\s*\(\s*([A-Za-z_]\w*|\d+)\s*\)|[A-Za-z_]\w*)\s*(?=[,)])")


def _clog2(n: int) -> int:
    """IEEE 1800-2017 20.8.1 `$clog2`: ceil(log2(n)); 0 for n = 0 and 1."""
    return 0 if n <= 1 else (n - 1).bit_length()


def top_parameter_derived_defaults(text: str, top: str,
                                   known: Dict[str, int]
                                   ) -> Dict[str, Dict[str, Any]]:
    """The TOP's expression defaults whose elaboration value is EXACT.

    `top_parameter_defaults` reads integer literals only, and that stays its
    contract. This is a separate, narrower reader for the two expression
    shapes elaboration answers without any choice once the operand is known:
    another parameter's NAME, and `$clog2(<name or literal>)`. ``known`` is
    what elaboration would use for the operand (the header's literals, then the
    declaration / `--param` values over them). Every value is returned with the
    expression it came from, so the report shows the arithmetic.

    MEASURED on subservient x gf180mcuD (D9, v1.25.64): `parameter memsize =
    512, parameter aw = $clog2(memsize)` left `[aw-1:0] o_sram_waddr`
    unresolved, and step 2 answered UNDECIDED (ZERO_DENOMINATOR) on a width the
    synthesised netlist carries as 9 bits. Any other expression stays
    unresolved, so the UNDECIDED path still owns every width not stated
    exactly.
    """
    stripped = _strip_hdl_attributes(_strip_hdl_comments(text))
    m = re.search(r"\bmodule\s+" + re.escape(top) + r"\b\s*(?:import[^;]*;\s*)*#\s*\(",
                  stripped)
    if not m:
        return {}
    depth, end = 1, None
    for n, ch in enumerate(stripped[m.end():], m.end()):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end = n
                break
    if end is None:
        return {}
    block = stripped[m.end():end] + ")"
    exprs = [(name, expr, operand) for name, expr, operand
             in _PARAM_EXPR_DEFAULT_RE.findall(block) if name not in known]
    out: Dict[str, Dict[str, Any]] = {}
    for _ in range(len(exprs)):
        progressed = False
        for name, expr, operand in exprs:
            if name in out:
                continue
            env = {**known, **{k: v["value"] for k, v in out.items()}}
            ref = operand or expr
            val = int(ref) if ref.isdigit() else env.get(ref)
            if val is None:
                continue
            out[name] = {"value": _clog2(val) if operand else val,
                         "expression": re.sub(r"\s+", "", expr),
                         "operand": {ref: val}}
            progressed = True
        if not progressed:
            break
    return out


def parse_top_ports(text: str, top: str,
                    params: Optional[Dict[str, int]] = None
                    ) -> Optional[List[Dict[str, Any]]]:
    """`[{dir,name,width}]` for ``top``'s port list, or None if not found.

    Handles the ANSI header form every generated `chip_top` in this repo uses,
    with or without a parameter block.
    """
    stripped = _strip_hdl_attributes(_strip_hdl_comments(text))
    src = stripped
    # CONDITIONAL COMPILATION. A port list may be bracketed by `ifdef/`endif.
    # Leaving the directive lines in place GLUES them to the neighbouring
    # declaration, and the glued chunk no longer starts with a direction
    # keyword, so it is silently discarded. MEASURED: that dropped `vdda1`
    # (first port after `ifdef) and `wb_clk_i` (first port after `endif) from a
    # real wrapper and published a port count two ports light. Directives are
    # removed here so no port is lost; WHICH ports were conditional is recorded
    # separately, because whether they exist depends on a define this gate does
    # not know.
    src = re.sub(r"^[ \t]*`(?:ifdef|ifndef|elsif|else|endif|define|undef)\b[^\n]*$",
                 lambda m: " " * len(m.group(0)), src, flags=re.M)
    m = re.search(r"\bmodule\s+" + re.escape(top) + r"\b", src)
    if not m:
        return None
    rest = src[m.end():]
    # Skip a `#( ... )` parameter block, counting nesting.
    idx = 0
    if re.match(r"\s*(?:import[^;]*;\s*)*#", rest):
        h = rest.find("#")
        k = rest.find("(", h)
        if k < 0:
            return None
        depth = 0
        for n, ch in enumerate(rest[k:], k):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    idx = n + 1
                    break
    open_i = rest.find("(", idx)
    if open_i < 0:
        return None
    depth = 0
    close_i = -1
    for n, ch in enumerate(rest[open_i:], open_i):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                close_i = n
                break
    if close_i < 0:
        return None
    # Keep the actual declarator's source position: an ANSI continuation may
    # share a line with its predecessor, or start after an `endif. Inferring
    # conditionality from the previous name would attribute the wrong port.
    conditional_spans: List[Tuple[int, int]] = []
    conditional_events: List[Tuple[int, str]] = []
    depth_cond = 0
    offset = 0
    for line in stripped.splitlines(keepends=True):
        s = line.strip()
        directive = re.match(r"^`(ifdef|ifndef|elsif|else|endif)\b", s)
        if directive:
            conditional_events.append((offset, directive.group(1)))
        if re.match(r"^`(?:ifdef|ifndef)\b", s):
            depth_cond += 1
        elif re.match(r"^`endif\b", s):
            depth_cond = max(0, depth_cond - 1)
        elif depth_cond > 0:
            conditional_spans.append((offset, offset + len(line)))
        offset += len(line)

    from module_port_audit import split_top_level
    ports: List[Dict[str, Any]] = []
    unparsed: List[str] = []
    direction: Optional[str] = None
    offset = m.end() + open_i + 1
    # Keep the possible inherited direction/packed-width contexts at each
    # branch join. A textual last declaration is not authority for a branch
    # that may be absent. Each branch starts from its entry context; explicit
    # declarations reset it. This does not select defines or preprocess RTL.
    type_states = {(None, 1)}
    branch_stack: List[Dict[str, Any]] = []
    events = iter((pos, kind) for pos, kind in conditional_events
                  if offset <= pos < m.end() + close_i)
    event = next(events, None)
    for raw_decl in split_top_level(rest[open_i + 1:close_i]):
        chunk_start = offset
        offset += len(raw_decl) + 1
        # Same rule as the conditional scan above: the chunk that reaches
        # `_DIR_RE` is stripped on its own account, not on a sibling's.
        decl = _strip_hdl_attributes(_strip_hdl_comments(raw_decl)).strip()
        if not decl:
            continue
        dm = _DIR_RE.match(decl)
        tail = dm.group(2) if dm else decl
        # An initialiser and an unpacked array both sit AFTER the name, so the
        # last token is not the name until they are removed. See
        # `split_port_tail` for the measurement that found this.
        head, unpacked = split_port_tail(tail)
        name_match = re.search(r"([A-Za-z_]\w*)\s*$", head)
        name_pos = (chunk_start + raw_decl.find(decl)
                    + (dm.start(2) if dm else 0)
                    + (name_match.start(1) if name_match else 0))
        while event is not None and event[0] <= name_pos:
            kind = event[1]
            if kind in ("ifdef", "ifndef"):
                branch_stack.append({"entry": set(type_states),
                                     "exits": set(), "has_else": False})
            elif branch_stack:
                frame = branch_stack[-1]
                frame["exits"].update(type_states)
                if kind in ("elsif", "else"):
                    type_states = set(frame["entry"])
                    frame["has_else"] |= kind == "else"
                else:  # endif: include the absent arm when there is no else.
                    if not frame["has_else"]:
                        frame["exits"].update(frame["entry"])
                    type_states = frame["exits"]
                    branch_stack.pop()
            event = next(events, None)
        # A continuation is just its own declarator, not a second type. Keep
        # unsupported chunks visible and invalidate a partial budget below.
        if (not name_match or (not dm and
                (direction is None or head.strip() != name_match.group(1)))):
            if len(unparsed) < 12:
                unparsed.append(decl[:60])
            continue
        name = name_match.group(1)
        if dm:
            direction = dm.group(1)
            type_states = {(direction, _width(head[:name_match.start(1)], params))}
        directions = {d for d, _ in type_states}
        widths = {w for _, w in type_states}
        # Equal known widths/directions remain decidable even when the type
        # spelling differs. Otherwise the existing unresolved-width consumer
        # must refuse a partial sum, including across else/elsif/endif.
        width = (next(iter(widths)) if len(widths) == len(directions) == 1
                 and None not in directions else None)
        if len(directions) == 1 and None not in directions:
            direction = next(iter(directions))
        if unpacked:
            n = unpacked_count(unpacked, params)
            # None x anything stays None: an array whose length nobody supplied
            # is UNDECIDED, never a guessed pad count.
            width = None if (width is None or n is None) else width * n
        ports.append({"dir": direction, "name": name,
                      "width": width,
                      "conditional": any(a <= name_pos < b
                                         for a, b in conditional_spans)})
    if ports:
        ports[0]["_unparsed_chunks"] = unparsed
    return ports


def _incomplete_port_parse(ports: Optional[List[Dict[str, Any]]]
                           ) -> Optional[Dict[str, Any]]:
    chunks = [c for p in ports or [] for c in p.get("_unparsed_chunks", [])]
    if not chunks:
        return None
    return {"check": "slot_pad_budget", "verdict": "UNDECIDED", "rc": 2,
            "reason_class": _reason_taxonomy.EXECUTION_ERROR,
            "rule": "TOP_PORT_PARSE_INCOMPLETE",
            "reason": "top-level port declarations could not be fully parsed: "
                      + "; ".join(chunks)
                      + " — a partial interface cannot establish a pad budget",
            "unparsed_port_chunks": chunks}


def interface_budget(ports: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Signal bits the design needs, split by direction, excluding clk/rst."""
    bits = {"input": 0, "output": 0, "inout": 0}
    unresolved: List[str] = []
    dedicated: List[str] = []
    for p in ports:
        if _CLK_RST_RE.match(p["name"]):
            dedicated.append(p["name"])
            continue
        if p["width"] is None:
            unresolved.append(p["name"])
            continue
        bits[p["dir"]] += int(p["width"])
    return {
        "bits_by_direction": bits,
        "signal_bits": bits["input"] + bits["output"] + bits["inout"],
        "on_dedicated_pads": dedicated,
        "unresolved_width_ports": unresolved,
    }


def fold_candidates(ports: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Same-width input/output bus pairs that COULD share one bidir group.

    Deterministic DETECTION only. Whether a pair is ever simultaneously active
    is a protocol fact this program cannot decide, so nothing here is applied
    and nothing is asserted to be safe. Every 1-bit input is offered as a
    possible direction control, named, without a claim about which one.
    """
    ins = [p for p in ports if p["dir"] == "input" and (p["width"] or 0) >= 2
           and not _CLK_RST_RE.match(p["name"])]
    outs = [p for p in ports if p["dir"] == "output" and (p["width"] or 0) >= 2
            and not _CLK_RST_RE.match(p["name"])]
    enables = [p["name"] for p in ports
               if p["width"] == 1 and p["dir"] == "input"
               and not _CLK_RST_RE.match(p["name"])]
    out: List[Dict[str, Any]] = []
    used_out = set()
    for i in ins:
        for o in outs:
            if o["name"] in used_out or o["width"] != i["width"]:
                continue
            used_out.add(o["name"])
            out.append({
                "input_bus": i["name"], "output_bus": o["name"],
                "width": i["width"], "pads_saved": i["width"],
                "possible_direction_controls": enables,
                "safety": "NOT DECIDED HERE — folding is valid only if the two "
                          "buses are never live in the same transaction; that "
                          "is a protocol fact about this design",
            })
            break
    return out


# --------------------------------------------------------------------------- #
def evaluate(slots: Dict[str, Dict[str, Any]], ports: List[Dict[str, Any]]
             ) -> Dict[str, Any]:
    incomplete = _incomplete_port_parse(ports)
    if incomplete:
        return incomplete
    budget = interface_budget(ports)
    folds = fold_candidates(ports)
    foldable_bits = sum(f["pads_saved"] for f in folds)
    need = budget["signal_bits"]
    need_after_fold = need - foldable_bits

    per_slot = {}
    best_direct: Optional[str] = None
    best_folded: Optional[str] = None
    best_cap = -1
    for name, obj in sorted(slots.items()):
        inv = slot_pad_inventory(obj)
        cap = inv["digital_signal_pads"]
        fits = need <= cap
        fits_folded = need_after_fold <= cap
        per_slot[name] = {**inv, "fits_as_declared": fits,
                          "fits_after_fold": fits_folded}
        if cap > best_cap:
            best_cap = cap
        if fits and best_direct is None:
            best_direct = name
        if fits_folded and best_folded is None:
            best_folded = name

    # CONDITIONAL PORTS: if the verdict FLIPS depending on whether a `ifdef
    # block is compiled in, the gate does not know the answer and says so.
    cond_bits = sum(int(p["width"] or 0) for p in ports
                    if p.get("conditional") and not _CLK_RST_RE.match(p["name"]))

    # A PORT WHOSE WIDTH IS UNRESOLVED MAKES THE SUM A LIE, so the sum is not
    # reported as a verdict. Dropping such ports is what produced a FITS for a
    # 120-bit design that summed to 31. Pass the elaboration values with
    # --param NAME=VALUE (the same ones the chip_top instantiation supplies).
    if budget["unresolved_width_ports"]:
        return {
            "check": "slot_pad_budget", "verdict": "UNDECIDED", "rc": 2,
            "reason_class": _reason_taxonomy.ZERO_DENOMINATOR,
            "reason": "the width of "
                      f"{len(budget['unresolved_width_ports'])} port(s) is "
                      "not uniquely resolved from its declared type and "
                      "supplied values: "
                      + ", ".join(budget["unresolved_width_ports"][:12])
                      + " — supply missing parameters with --param NAME=VALUE "
                        "or resolve conditional types in the elaborated top; "
                        "a width this gate invented would be a pad count nobody chose",
            "unresolved_width_ports": budget["unresolved_width_ports"],
            "partial_signal_bits_EXCLUDING_UNRESOLVED": need,
            "note": "the partial sum is NOT a verdict and must not be read as one",
        }

    # A slot set that yielded NO countable pads has not answered the question.
    # Without this the report reads `largest slot digital signal pads: 0` and
    # returns DOES_NOT_FIT — which is what it did on its first run against a
    # real ingested project, and it looked exactly like a verdict.
    if best_cap <= 0:
        return {
            "check": "slot_pad_budget", "verdict": "UNDECIDED", "rc": 2,
            "reason_class": _reason_taxonomy.ZERO_DENOMINATOR,
            "reason": "no pad instances could be counted in any slot file — "
                      "0 pads is not a slot, it is a parse that found nothing",
            "slots": per_slot,
            "declared_signal_bits": need,
        }
    if best_direct is not None:
        verdict, rc = "FITS", 0
    elif best_folded is not None:
        verdict, rc = "FITS_AFTER_FOLD", 0
    else:
        verdict, rc = "DOES_NOT_FIT", 1

    if cond_bits:
        need_min = need - cond_bits
        fits_min = any(need_min <= slot_pad_inventory(o)["digital_signal_pads"]
                       for o in slots.values())
        fits_max = best_direct is not None or best_folded is not None
        if fits_min != fits_max:
            return {
                "check": "slot_pad_budget", "verdict": "UNDECIDED", "rc": 2,
                "reason_class": _reason_taxonomy.ZERO_DENOMINATOR,
                "reason": f"{cond_bits} interface bit(s) are inside a "
                          "conditional-compilation block, and the verdict "
                          f"differs with them ({need}) and without them "
                          f"({need_min}) — supply the design's defines, or "
                          "point this gate at the elaborated top",
                "signal_bits_with_conditional": need,
                "signal_bits_without_conditional": need_min,
            }

    return {
        "check": "slot_pad_budget",
        "verdict": verdict,
        "rc": rc,
        "conditional_interface_bits": cond_bits,
        "declared_signal_bits": need,
        "signal_bits_after_folding_every_candidate": need_after_fold,
        "largest_digital_signal_pad_count": best_cap,
        "over_by_ratio": (round(need / best_cap, 2) if best_cap > 0 else None),
        "over_by_ratio_after_fold": (round(need_after_fold / best_cap, 2)
                                     if best_cap > 0 else None),
        "slot_that_fits_as_declared": best_direct,
        "slot_that_fits_after_fold": best_folded,
        "interface": budget,
        "fold_candidates": folds,
        "slots": per_slot,
        "does_not_decide": [
            "whether a fold candidate is protocol-safe",
            "die area, timing or routability — a design can fit the pads and "
            "still not fit the die",
        ],
    }


#: Where the flow's own step 1 writes the RTL this gate reads. Declared here
#: rather than in the gate clause on purpose -- see `_discover_rtl`.
_RTL_DIR_REL = ("phase2", "stage1", "rtl")


def _discover_rtl(project: str) -> List[str]:
    """The step-1 RTL of `project`, when the caller named no `--rtl`.

    WHY THE PROGRAM GLOBS AND NOT THE GATE CLAUSE (vibe-ic#1347)
    -----------------------------------------------------------
    The obvious wiring is `--rtl phase2/stage1/rtl/*.v` in the flow clause.
    It is a trap. `flow_compliance_check._resolve_program_cmd` expands globs
    in a clause into SEPARATE argv tokens, `--rtl` consumes exactly one, and
    every remaining file arrives as an extra positional, which is rejected.

    THE TRAP WAS SILENT AND IS NOW LOUD, and both halves are worth keeping.
    Until this program adopted the rc-3 usage tier (#712), that rejection was
    argparse's default **exit 2** -- this flow's VACUOUS_PASS -- so the gate
    would have reported a disclosed skip on every multi-file design, forever,
    looking exactly like the ordinary "no slots ingested" one. It is rc 3 now,
    which the flow reads as FAIL, so the same mistake breaks the step visibly.

    The clause still carries no glob: a loud break is still a break. The
    expansion happens here instead, where a directory that does not exist is an
    ANSWER (`[]` -> rc 2 UNDECIDED with a reason naming the directory) and not
    a usage error at all.
    """
    d = os.path.join(project, *_RTL_DIR_REL)
    if not os.path.isdir(d):
        return []
    return [os.path.join(d, fn) for fn in sorted(os.listdir(d))
            if fn.lower().endswith((".v", ".sv"))]


# --------------------------------------------------------------------------- #
# 37.5self — THE DIE IS ITS OWN OPERATOR  (R-0915, 2026-09-20)
# --------------------------------------------------------------------------- #
#: Where the design records its own free choices (parameter values included).
DESIGN_DECLARATION_REL = os.path.join("plugin_output", "declaration.json")

#: The step that BUILDS this die's ring, and the gate that measures the
#: design's pins against it. NAMED HERE, NEVER READ: this gate runs at step 2,
#: in phase 2, and `reports/phase3/padring.json` is step 15.5ic's declared
#: required_output. Reading it here is the dependency `test_matrix_d5_deps_-
#: correct` refuses and cannot repair -- 15.5ic already has step 2 in its own
#: ancestry, so the edge "step 2 blocks_on 15.5ic" is CIRCULAR (D5-MISSING-EDGE,
#: would-cycle). The measurement is not lost and is not duplicated:
#: `pad_bterm_coincidence_check` at 15.5ic already proves, per net and
#: geometrically, that each top-level port's BTerm lands on its pad's bond
#: terminal -- the die's own budget, measured where its ring exists.
OWN_RING_STEP = "15.5ic"
OWN_RING_GATE = "pad_bterm_coincidence_check"
#: The same step's unconditional half: `pad_ring_check` refuses
#: BTERM_WITHOUT_PAD on the ring it checks, with or without a tech LEF.
OWN_RING_GATE_ALWAYS = "pad_ring_check (BTERM_WITHOUT_PAD)"
OWN_RING_EVIDENCE_REL = os.path.join("reports", "phase3",
                                     "pad_bterm_coincidence.json")
#: The die's OWN slot file: its declaration, written at step 0.5ic, which IS
#: in step 2's blocks_on closure.
DECLARED_RING_KEYS = ("pad_signal_map", "pad_order_by_side")


def _operator_template_is_bound(project: str) -> bool:
    """Has the design named an operator template or slot of its own?

    The same two fields `submission_template_check.slot_rules_are_owed` reads,
    read here for the DIE branch, which needs the binding and not the
    hardmacro question that predicate answers. Unreadable degrades towards
    BOUND: an external operator we cannot rule out is one we do not overrule."""
    doc = _json_at(project, _ST.DESIGN_ANSWERS_REL)
    if doc is None:
        return True
    operator = doc.get("operator_template")
    if not isinstance(operator, dict):
        return False
    return any(str(operator.get(k) or "").strip() for k in ("path", "slot"))


def _json_at(project: str, rel: str) -> Optional[Dict[str, Any]]:
    """That project-relative JSON as a dict, or None. Never a default."""
    try:
        with open(os.path.join(project, rel), "r", encoding="utf-8",
                  errors="replace") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _geometry_only_operator(project: str, slots: Dict[str, Dict[str, Any]]) -> Optional[dict]:
    """Classify the bound source contract, never infer a pad capacity from zero.

    The ordinary ingester's source/hash and rectangle are reread. A declared
    pad key, even malformed, remains a fixed-roster question. Unclaimed lists
    and missing or stale source/geometry cannot establish geometry-only scope.
    """
    answers = _json_at(project, _ST.DESIGN_ANSWERS_REL) or {}
    binding = answers.get("operator_template") or {}
    if not isinstance(binding, dict):
        return None
    selected = binding.get("slot")
    if selected is not None and not isinstance(selected, str):
        return None
    candidates = [(name, obj) for name, obj in slots.items()
                  if not selected or name == selected or obj.get("slot") == selected]
    if not candidates:
        return None
    records = []
    for name, obj in candidates:
        raw_path = obj.get("source_file")
        source_hash = obj.get("source_sha256")
        if not isinstance(raw_path, str) or not source_hash:
            return None
        path = Path(raw_path)
        if not path.is_absolute():
            path = Path(project) / path
        if _ST.sha256_file(path) != source_hash:
            return None
        mapping, error = _ST._load_mapping(path)
        if error or not isinstance(mapping, dict) or any(
                _ST.PAD_LIST_KEY_RE.fullmatch(str(key).strip()) for key in mapping):
            return None
        actual = _ST.slot_record(path, mapping, path.parent)
        rect = _ST.parse_rect((actual.get("die_area") or {}).get("rect"))
        if (rect is None or not all(v.is_finite() for v in rect)
                or any(v <= 0 for v in _ST.rect_wh(rect))
                or obj.get("die_area") != actual.get("die_area")
                or actual["pads"]["unmatched_list_keys"]):
            return None
        records.append({"slot": name, "source_sha256": source_hash,
                        "die_area": actual["die_area"], "ring": actual["ring"],
                        "non_pad_lists": actual["pads"]["non_pad_lists"]})
    return {"kind": "GEOMETRY_ONLY", "slots": records,
            "scope": "design-owned pad roster; bound operator geometry/mask limits retained"}


def declared_own_ring(doc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The pad ring THE DESIGN DECLARED for itself, from its own declaration.

    A die binds no operator, so the file that plays the operator slot's part
    is the design's own `tapeout_declaration.json`: `pad_signal_map`
    ({instance: port}) is the die's pad list, and `pad_order_by_side` is the
    side order. Both are step 0.5ic's declared outputs, and 0.5ic is in step
    2's blocks_on closure -- so this is a budget a phase-2 step may measure.

    BY SIGNAL NAME, NOT BY A COUNT. `pad_order_by_side` alone names INSTANCES,
    and a ring with the right number of pads bonded to the wrong nets is not a
    ring that carries this design's pins: a count cannot tell the two apart.
    So a side order without a signal map is reported as `measurable=False`,
    with which key was present, rather than budgeted.
    """
    out: Dict[str, Any] = {"measurable": False, "signal_map": {},
                           "instances": [], "keys_present": []}
    if not isinstance(doc, dict):
        return out
    smap = _TD.answer(doc, "pad_signal_map")
    if isinstance(smap, dict):
        out["signal_map"] = {str(k): str(v).strip() for k, v in smap.items()
                             if isinstance(v, str) and str(v).strip()}
    sides = _TD.answer(doc, "pad_order_by_side")
    if isinstance(sides, dict):
        for _side in sorted(sides):
            lst = sides[_side]
            if isinstance(lst, list):
                out["instances"].extend(str(x) for x in lst)
    out["keys_present"] = [k for k, v in (("pad_signal_map", out["signal_map"]),
                                          ("pad_order_by_side", out["instances"]))
                           if v]
    out["measurable"] = bool(out["signal_map"])
    return out


#: THE MINIMUM COMPLETE SUPPLY PAIR a ring must also carry: one external
#: POWER pad and one external GROUND pad. The COUNT is a topology fact and is
#: stated here; WHICH MACRO plays each part is the IO cell library's answer,
#: read from the PDK by `io_pad_chip_top_gen._derive_supply_pad_pair` at step
#: 15.5ic. This gate reports the obligation and does NOT let it move the
#: verdict -- a supply pad it cannot see selected is not a supply pad it may
#: call missing.
SUPPLY_PADS_MINIMUM_PAIR = 2
SUPPLY_PAD_SELECTION_STEP = OWN_RING_STEP
SUPPLY_PAD_SELECTION_PROGRAM = "io_pad_chip_top_gen"


def derived_own_ring(project: str, ports: List[Dict[str, Any]]
                     ) -> Dict[str, Any]:
    """The die's own ring, DERIVED from the design's own pad-placement section.

    R-0915-101. A die binds no operator template, so its budget is its own pad
    ring -- and a design that left `pad_signal_map` NOT_DETERMINED has usually
    not left the ring unstated: it stated it in prose, in the pad-placement
    section of its own L-documents, which is exactly where
    `io_pad_chip_top_gen` derives `pad_order_by_side` and `SIGNAL_MAP` from at
    step {step}. Read through the SAME function, `_l_doc_pad_placement
    .derive_own_ring`, so a phase-2 budget and a phase-3 ring cannot disagree
    about which pad carries which net.

    NO NEW DEPENDENCY, AND NO CIRCULAR ONE. The documents this reads are
    design INPUT (`input/docs`, `phase1/`), which are in step 2's own
    `blocks_on` closure; step {step}'s generated DEF is what this gate still
    does not read.

    `ports` is this gate's OWN port list, parsed from the staged RTL -- the
    IMPLEMENTED interface. It is used only to resolve the document's
    design-owned GROUP rows ("SRAM data bus") against identifiers the design
    itself chose, never to add a port to a side the document does not name.
    Returned in the same shape `declared_own_ring` returns, so ONE inventory
    counts both rings.
    """.format(step=OWN_RING_STEP)
    try:
        ring = _LPP.derive_own_ring(Path(project), ports or [])
    except (OSError, ValueError, TypeError) as exc:
        # "Could not read it" is not "read it and it was empty".
        return {"measurable": False, "signal_map": {}, "instances": [],
                "keys_present": [], "unreadable": str(exc),
                "documents_scanned": [], "documents_unreadable": []}
    return ring


def declared_ring_inventory(ring: Dict[str, Any],
                            ports: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The die's declared ring, counted AGAINST THE PINS THE DESIGN DECLARES.

    Bus bits are matched per bit (`x[7]`), which is how a signal map names
    them; a map that brings out the whole bus under its base name counts for
    every bit of it, because that is what it says."""
    bonded = set(ring["signal_map"].values())
    need: List[str] = []
    for port in ports:
        if _CLK_RST_RE.match(port["name"]):
            continue                      # dedicated clock/reset pads
        width = port.get("width")
        if width is None:
            continue                      # refused earlier; never counted here
        if int(width) <= 1:
            need.append(port["name"])
        else:
            need.extend(f"{port['name']}[{i}]" for i in range(int(width)))
    missing = [n for n in need
               if n not in bonded and n.split("[", 1)[0] not in bonded]
    return {
        "declared_pads_total": len(ring["instances"] or ring["signal_map"]),
        "declared_ring_signals": sorted(bonded),
        "declared_signal_bits": len(need),
        "bonded_declared_bits": len(need) - len(missing),
        "unbonded_declared_bits": missing[:24],
        "unbonded_count": len(missing),
        "declared_by": ring["keys_present"],
    }


def _design_declared_params(project: str) -> Dict[str, int]:
    """Integer parameter values the DESIGN declared for itself.

    `spec_declaration_emit` writes the design's free choices to
    `plugin_output/declaration.json`; a width that file has already decided is
    not a width this gate has to be told twice. Accepts `size` and
    `size_param` spellings, integers only. MEASURED on spm x gf180mcuD: the
    declaration carries `size_param: 32` while the clause the auditor runs
    passes no `--param`, so every re-run refused a design that had answered."""
    doc = _json_at(project, DESIGN_DECLARATION_REL) or {}
    out: Dict[str, int] = {}
    for key, value in doc.items():
        if not isinstance(value, bool) and isinstance(value, int):
            name = str(key)
            out[name] = value
            if name.endswith("_param"):
                out[name[: -len("_param")]] = value
    # A core's elaboration choices are recorded under core_parameters in the
    # same declaration. Keep the actual RTL parameter names; memsize_bytes is
    # a different field and must not be guessed to mean memsize.
    core = doc.get("core_parameters")
    if isinstance(core, dict):
        for key, value in core.items():
            if (re.fullmatch(r"[A-Za-z_]\w*", str(key))
                    and isinstance(value, int) and not isinstance(value, bool)):
                out[str(key)] = value
    return out


def _declared_top_cell(doc: Optional[Dict[str, Any]]) -> Optional[str]:
    """The top cell the design DECLARED, from step 0.5ic's own output.

    The clause the auditor re-runs passes no `--top`, so the gate takes its
    default and can refuse a design that has answered. The declaration is the
    run's own answer to exactly this question and is a required_output of
    0.5ic, which IS in step 2's closure -- so reading it adds no dependency
    the flow does not already declare."""
    if not isinstance(doc, dict):
        return None
    top = _TD.answer(doc, "top_cell")
    return str(top).strip() or None if isinstance(top, str) and top != _TD.NOT_DETERMINED else None


#: The design's own integration spec, whose `top_module` is the CORE the
#: staged RTL carries. `io_pad_chip_top_gen` reads the same field for the same
#: purpose (its `core_module`), from the same file.
L9_INTEGRATION_SPEC_REL = os.path.join("phase1", "generated_docs",
                                       "L9_INTEGRATION_SPEC.json")


def _declared_core_module(project: str) -> Optional[str]:
    """The CORE module the design declares, from its own integration spec.

    MEASURED on subservient x gf180mcuD r46 (a DIE): the tape-out declaration
    answers `top_cell: chip_top` -- the chip-level wrapper, which step 15.5ic
    GENERATES -- while the RTL staged at step 2 carries the core,
    `subservient`. Both answers are right about different modules, and a gate
    that tries only the first reports "the design declares NO top-level port"
    about a design that declares eight. The integration spec's `top_module` is
    the design's own answer to which module the RTL is, read from the file
    `io_pad_chip_top_gen` reads it from, and it is consulted only AFTER the
    command line and the declaration have both failed to name a module that is
    in the staged RTL.
    """
    doc = _json_at(project, L9_INTEGRATION_SPEC_REL)
    if doc is None:
        return None
    top = doc.get("top_module")
    if not isinstance(top, str) or not top.strip():
        return None
    return top.strip()


def _load_slots(project: str) -> Dict[str, Dict[str, Any]]:
    d = os.path.join(project, "input", "submission_template", "slots")
    out: Dict[str, Dict[str, Any]] = {}
    if not os.path.isdir(d):
        return out
    try:
        import yaml  # type: ignore
    except ImportError:
        yaml = None  # type: ignore
    for fn in sorted(os.listdir(d)):
        if not fn.lower().endswith((".yaml", ".yml", ".json")):
            continue
        p = os.path.join(d, fn)
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as fh:
                raw = fh.read()
            obj = (json.loads(raw) if fn.lower().endswith(".json")
                   else (yaml.safe_load(raw) if yaml else None))
        except Exception:
            obj = None
        if isinstance(obj, dict):
            out[os.path.splitext(fn)[0]] = obj
    return out


def main(argv: Optional[List[str]] = None) -> int:
    # `GateArgumentParser`, not the stdlib one. argparse exits 2 on a rejected
    # command line, and 2 is THIS FLOW'S VACUOUS_PASS tier -- so a malformed
    # gate clause would report "I examined nothing" and the step would go green
    # over a gate that never ran. That collision is not hypothetical here: it
    # is the reason the flow clause for this program carries no glob (a glob
    # expands into surplus positionals, which argparse rejects). Routing around
    # the trap left it armed for the next editor; rc 3 disarms it, and the flow
    # reads an unsentinelled 3 as FAIL -- loud, which is the whole point.
    ap = _usage.GateArgumentParser(
        description="Decide whether a design's declared interface fits a "
                    "purchased shuttle slot, from the slot files step 0.5ic "
                    "already ingested. Front-door arithmetic, not a build.")
    ap.add_argument("project")
    ap.add_argument("--rtl", action="append", default=[],
                    help="RTL file holding the top module; repeatable.")
    ap.add_argument("--top", default="chip_top")
    ap.add_argument("--param", action="append", default=[], metavar="NAME=VALUE",
                    help="Elaboration value for a parameterised port width, "
                         "e.g. --param BDW=39. Repeatable. Nothing is ever "
                         "assumed: an unsupplied parameter yields UNDECIDED.")
    ap.add_argument("--json", dest="out_json", default=None)
    a = ap.parse_args(argv)

    params: Dict[str, int] = {}
    for kv in a.param:
        if "=" in kv:
            k, v = kv.split("=", 1)
            try:
                params[k.strip()] = int(v.strip(), 0)
            except ValueError:
                # A value this program cannot read is the CALLER being
                # wrong, not this program examining nothing. Same tier as any
                # other rejected command line (#712).
                _usage.usage_error("slot_pad_budget_check",
                                   f"--param {kv} is not an integer")
                return _usage.RC_USAGE

    # THE DESIGN DECLARED IT IS NOT GOING THROUGH AN OPERATOR (vibe-ic#2277).
    #
    # MEASURED on spm x gf180mcuD, live main 79506306d (2026-09-15): since the
    # 0.5ic fetch was wired, a PDK with a LIVE shuttle in the registry has the
    # operator's whole CATALOGUE ingested into
    # `input/submission_template/slots/*.yaml` whether or not the design bought
    # a slot. So `slots` is non-empty for a design that declared
    # `deliverable=HARDMACRO` and named no slot, the `not slots and
    # _declared_no_slot` path below is unreachable, and this gate budgets the
    # design's pins against four slots it never purchased.
    #
    # A CATALOGUE IS NOT A PURCHASE, and the route is the DESIGN'S to declare.
    # It declares it in two files the flow already owns: the merged
    # `tapeout_declaration.json` answers `deliverable`, and the design's own
    # `input/step_0_5ic_answers.json` names (or does not name) an
    # `operator_template.path` / `.slot`. That predicate is already written
    # ONCE, in `submission_template_check.slot_rules_are_owed`, and it is
    # CALLED here rather than re-implemented: two readers of one route that can
    # drift is how a design got two answers about itself in the first place.
    # It degrades TOWARDS owing the budget -- an unreadable declaration, a
    # NOT_DETERMINED deliverable, a DIE, or ANY affirmative operator binding
    # all keep this gate live, which is the negative control.
    #
    # COMPUTED BEFORE the port parse and CHECKED FIRST below, because a
    # hardmacro that buys no slot owes no pad budget whatever its top module is
    # called. Answering "top module 'chip_top' not found" -- the
    # EXECUTION_ERROR this run actually booked -- is a question that was never
    # owed being reported as one that could not be asked.
    # THE DELIVERY AND THE BINDING, read once — both branches below need them
    # and two readers of one route is how a design gets two answers about
    # itself. `answer` reports an un-attested `deliverable` as NOT_DETERMINED
    # (vibe-ic#2369), so only the owner's word reaches either branch.
    _decl_doc, _decl_err = _TD.load(Path(a.project) / _TD.DECLARATION_REL)
    _route_deliverable = (_TD.answer(_decl_doc, "deliverable")
                          if _decl_err is None and isinstance(_decl_doc, dict)
                          else _TD.NOT_DETERMINED)
    _operator_bound = _operator_template_is_bound(str(a.project))
    # THE DECLARED WORD SELECTS THE BASIS — attestation gates a STAND-DOWN,
    # not a measurement (R-0915-98(2)). `answer` withholds an un-attested
    # `deliverable` (vibe-ic#2369) and that is right for a step that would be
    # skipped; here the question is WHICH budget to measure, and a design that
    # says DIE is measured as a die whoever wrote the word. The raw field is
    # consulted only after `answer` declines, and the report says which.
    _raw_deliverable = ""
    if isinstance(_decl_doc, dict):
        _raw = (_decl_doc.get("answers") or {}).get("deliverable")
        _raw_deliverable = str(_raw).strip() if isinstance(_raw, str) else ""
    _declared_die = (_route_deliverable == _TD.DELIVERABLE_DIE
                     or _raw_deliverable.upper() == _TD.DELIVERABLE_DIE)
    _die_word_source = ("answers.deliverable (owner-attested)"
                        if _route_deliverable == _TD.DELIVERABLE_DIE
                        else "answers.deliverable (declared, not attested)")
    _route_na: Optional[Dict[str, Any]] = None
    try:
        _owed, _why_not = _stc.slot_rules_are_owed(Path(a.project), None)
    except (OSError, ValueError, TypeError):  # degrade towards owing it
        _owed, _why_not = True, None
    # A DIE IS NEVER "NOT APPLICABLE" HERE, and ONE place decides that: the
    # die branch below is consulted first and owns every outcome a die can
    # have, including the two that cannot measure. This branch is the
    # HARDMACRO answer — nobody's slot, so no budget — and since
    # `slot_rules_are_owed` learned to say the same of a die that binds no
    # operator, a die was taking it and the landed contract
    # (`test_a_DIE_against_the_same_catalogue_still_gets_a_real_verdict`) was
    # red: a die still gets a REAL verdict, measured against its own ring.
    if not _owed and _why_not:
        _route_doc, _route_error = _TD.load(Path(a.project) / _TD.DECLARATION_REL)
        _route_deliverable = _TD.answer(_route_doc, "deliverable")
        _route_na = {
            "check": "slot_pad_budget",
            "program": "slot_pad_budget_check",
            "verdict": "NOT_APPLICABLE",
            "rc": 2,
            "reason_class": _reason_taxonomy.DESIGN_DECLARED_NA,
            "skip_kind": "class-not-applicable",
            "reason": (
                f"the design declares deliverable={_route_deliverable} and binds no "
                "operator slot, so no purchased pad budget exists for its "
                "interface to fit; the slot files on disk are the PDK's live "
                "catalogue, which is information, not a purchase. " + _why_not),
            # The shape `flow_compliance_check._report_proves_executed_design_na`
            # validates: a project-relative declaration, the population fields
            # that must be empty, the zero, and a typed assertion re-read from
            # the same bytes. A reason token alone is not evidence.
            "applicability_evidence": {
                "kind": "design-declared-zero-population",
                "declaration_path": _ST.DESIGN_ANSWERS_REL,
                "population_paths": ["operator_template.path",
                                     "operator_template.slot"],
                "declared_population": 0,
                "assertions": [
                    {"path": "answers.deliverable",
                     "equals": _route_deliverable},
                ],
            },
            "note": "a design-declared route, not an unanswered question",
        }

    slots = _load_slots(a.project)
    # THE ARGUMENTS THE AUDITOR'S CLAUSE DOES NOT PASS, taken from the run's
    # OWN records rather than defaulted (R-0915, 2026-09-20). The runner
    # invokes this program with `--top <the design's top>`; step 2's yaml
    # clause carries neither `--top` nor `--param`, and
    # `flow_compliance_check` re-runs that clause and OVERWRITES the runner's
    # report. MEASURED on spm x gf180mcuD (v1.22.10, run7): the shipped report
    # read `top module 'chip_top' not found in [...spm.v]` and, with `--top`
    # supplied, `the width of 1 port(s) is parameterised` — two refusals about
    # arguments, on a design whose own records answer both. Neither read
    # invents anything: an explicit flag still wins, and when the records are
    # silent the behaviour is exactly what it was.
    _declared_params = _design_declared_params(str(a.project))
    _params_from_declaration = {k: v for k, v in _declared_params.items()
                                if k not in params}
    _param_conflicts: Dict[str, Dict[str, int]] = {}
    _top_source = "--top"
    _core_top = _declared_top_cell(_decl_doc)
    # An explicit --rtl always wins; discovery is the fallback the flow uses.
    rtl_files = list(a.rtl) or _discover_rtl(a.project)
    ports: Optional[List[Dict[str, Any]]] = None
    defaults_used: Dict[str, int] = {}
    derived_used: Dict[str, Dict[str, Any]] = {}
    _l9_core = _declared_core_module(str(a.project))
    _tops_to_try: List[str] = []
    for _cand in (a.top, _core_top, _l9_core):
        if _cand and _cand not in _tops_to_try:
            _tops_to_try.append(_cand)
    for _top_try in _tops_to_try:
        for f in rtl_files:
            try:
                with open(f, "r", encoding="utf-8", errors="replace") as fh:
                    _text = fh.read()
                _rtl_defaults = top_parameter_defaults(_text, _top_try)
                defaults_used = {k: v for k, v in _rtl_defaults.items()
                                 if k not in params}
                # TWO ANSWERS ABOUT ONE DESIGN ARE NOT AN ANSWER. Where the
                # RTL's own parameter default and the design's declaration
                # disagree, this gate picks neither and says so below.
                for _k, _v in _params_from_declaration.items():
                    if _k in _rtl_defaults and _rtl_defaults[_k] != _v:
                        _param_conflicts[_k] = {
                            "rtl_default": _rtl_defaults[_k],
                            "declared": _v}
                _known = {**_rtl_defaults, **_params_from_declaration, **params}
                derived_used = {
                    k: v for k, v in top_parameter_derived_defaults(
                        _text, _top_try, _known).items() if k not in params
                    and k not in _params_from_declaration}
                ports = parse_top_ports(
                    _text, _top_try,
                    {**defaults_used,
                     **{k: v["value"] for k, v in derived_used.items()},
                     **_params_from_declaration, **params})
            except OSError:
                ports = None
            if ports:
                break
        if ports:
            if _top_try != a.top:
                _top_source = (
                    (f"{L9_INTEGRATION_SPEC_REL}:top_module — the design's own "
                     f"answer for which module the staged RTL is"
                     if _top_try == _l9_core and _top_try != _core_top
                     else f"{_TD.DECLARATION_REL}:answers.top_cell — "
                          f"the design's own answer")
                    + f"; {a.top!r} is not in the staged RTL")
                a.top = _top_try
            break

    # v1.15.45 (sha256 capture) — "no slot files" has TWO different owners.
    # Step 0.5ic writes exactly one router file: a slot list (shuttle route),
    # NO_TEMPLATE.txt, or SELF_TAPEOUT.txt. When the router present is one of
    # the last two, the design DECLARED that no operator slot exists, so there
    # is no pad budget to fit — a design-declared N/A, not "step 0.5ic has not
    # run" (which was false on every self-tape-out run and read as
    # BLOCKED_BY_UPSTREAM → step 2 INCOMPLETE).
    _routers = (
        ("SELF_TAPEOUT.txt", "the design declared its own tape-out "
                             "(input/submission_template/SELF_TAPEOUT.txt)"),
        ("NO_TEMPLATE.txt", "the design declared that no operator template "
                            "applies (input/submission_template/NO_TEMPLATE.txt)"),
    )
    _declared_no_slot = None
    for _name, _why in _routers:
        if os.path.isfile(os.path.join(str(a.project), "input",
                                       "submission_template", _name)):
            _declared_no_slot = _why
            break
    # 37.5self — THE DIE IS ITS OWN OPERATOR (R-0915-98(2), 2026-09-20).
    # A die binds no operator template, so there is no external slot to
    # measure against and the catalogue on disk is information, not a
    # purchase. What plays the slot file's part is the design's OWN
    # declaration, written at step 0.5ic: the pad ring it declares for itself,
    # measured by signal name against the pins it declares. Where the design
    # declared no ring and left it to the flow to generate, that ring is
    # step 15.5ic's output and this step neither reads it (the edge would be
    # circular) nor repeats the measurement 15.5ic already makes -- it says
    # so, and does not pass.
    #
    # A DIE OUTRANKS THE ROUTE-N/A. `_route_na` below is the HARDMACRO answer
    # — "nobody's slot, so no budget" — and since `slot_rules_are_owed` learned
    # to say the same of an owner-attested DIE that binds no operator, a die
    # was taking it too. A die is not exempt from a pad budget; it is its own
    # operator, and its budget is the ring below.
    _geometry_operator = (_geometry_only_operator(str(a.project), slots)
                          if _declared_die and _operator_bound else None)
    _die_is_its_own_operator = _declared_die and (not _operator_bound or bool(_geometry_operator))
    _declared_ring = (declared_own_ring(_decl_doc) if _die_is_its_own_operator
                      else None)
    # TWO ANSWERS ABOUT ONE WIDTH FIRST, for every route. A contradiction in
    # the design's own records is not made smaller by the branch that would
    # have read it, and a deferral printed over it would hide it.
    if _param_conflicts:
        rep = {"check": "slot_pad_budget", "verdict": "UNDECIDED", "rc": 2,
               "reason_class": _reason_taxonomy.ZERO_DENOMINATOR,
               "reason": ("the design's own "
                          f"{DESIGN_DECLARATION_REL} and the RTL's parameter "
                          "default disagree, so the width this budget would "
                          "sum is not established: "
                          + "; ".join(f"{k}: declared {v['declared']} vs RTL "
                                      f"default {v['rtl_default']}"
                                      for k, v in sorted(_param_conflicts.items()))),
               "parameter_conflicts": _param_conflicts,
               "note": "a question with two answers has not been answered"}
        rc = 2
    elif (_die_is_its_own_operator or _route_na is None) and _incomplete_port_parse(ports):
        rep = _incomplete_port_parse(ports)
        rc = 2
    elif _die_is_its_own_operator and not ports:
        # A DIE THAT DECLARES NO TOP PORTS AT ALL is the one undecidable case
        # R-0915-101 leaves, and it is a DESIGN-INPUT GAP NAMED AS ONE, not an
        # upstream step to wait for and not an error in this gate. Nothing
        # downstream will supply a port list the design never wrote: a die
        # with no interface has no pads to budget, and the thing to fix is the
        # input.
        rep = {"check": "slot_pad_budget", "verdict": "UNDECIDED", "rc": 2,
               "reason_class": _reason_taxonomy.ZERO_DENOMINATOR,
               "reason": (f"this delivery is a DIE and binds no operator "
                          f"template, so its budget is its own pad ring "
                          f"measured against the pins it declares — and the "
                          f"design declares NO top-level port: top module "
                          f"'{a.top}' was not found in "
                          f"{rtl_files or '(no --rtl given and no RTL under ' + os.path.join(*_RTL_DIR_REL) + ')'}"
                          f". A die with no declared interface has no pad to "
                          f"budget; the incomplete input is named here and no "
                          f"later step supplies it"),
               "findings": [{"severity": "ERROR",
                             "rule": "DIE_DECLARES_NO_TOP_PORT",
                             "message": (f"no top-level port list could be "
                                         f"read for top module '{a.top}' from "
                                         f"{rtl_files or 'no staged RTL'}"),
                             "owner": "design input"}],
               "budget_basis": "37.5self:own_pad_ring",
               "deliverable_source": _die_word_source,
               "note": ("a design-input gap, named — not a question blocked "
                        "on an upstream step")}
        rc = 2
    elif _die_is_its_own_operator:
        _budget = interface_budget(ports)
        # THE RING THE DESIGN DECLARES, FROM EITHER PLACE IT DECLARES IT
        # (R-0915-101). `pad_signal_map` in the tape-out declaration is the
        # typed spelling; the pad-placement section of the design's own
        # L-documents is the prose one, and it is the spelling every design
        # measured so far actually used. Both are the DESIGN's own word about
        # its own ring, both are design INPUT in step 2's `blocks_on` closure,
        # and both are read here through the reader step 15.5ic's producer
        # already uses — so this step and that one cannot disagree about which
        # pad carries which net. The typed spelling wins when present; nothing
        # about the declared path changes.
        _ring = _declared_ring
        _ring_source = "declaration:pad_signal_map"
        _derived: Optional[Dict[str, Any]] = None
        if not _ring["measurable"]:
            _derived = derived_own_ring(str(a.project), ports)
            if _derived["measurable"]:
                _ring = _derived
                _ring_source = "l_doc:pad_placement"
        if _budget["unresolved_width_ports"]:
            rep = {"check": "slot_pad_budget", "verdict": "UNDECIDED", "rc": 2,
                   "reason_class": _reason_taxonomy.ZERO_DENOMINATOR,
                   "reason": ("the width of "
                              f"{len(_budget['unresolved_width_ports'])} "
                              "port(s) is not uniquely resolved from its "
                              "declared type and supplied values: "
                              + ", ".join(_budget["unresolved_width_ports"][:12])
                              + " — a width this gate invented would be a pad "
                                "count nobody chose"),
                   "unresolved_width_ports": _budget["unresolved_width_ports"],
                   "budget_basis": "37.5self:own_pad_ring",
                   "deliverable_source": _die_word_source}
            rc = 2
        elif not _ring["measurable"]:
            # NEITHER SPELLING. The design declares a die, declares pins, and
            # states its pad ring NOWHERE — not typed, not in prose. That is a
            # DESIGN-INPUT GAP NAMED AS ONE (R-0915-101), not BLOCKED_BY_UPSTREAM:
            # the ring step 15.5ic generates is generated FROM this same
            # declaration, so waiting for it would be waiting for the design to
            # answer a question only the design can answer.
            _scanned = (_derived or {}).get("documents_scanned") or []
            _unread = (_derived or {}).get("documents_unreadable") or []
            _unresolved_tok = (_derived or {}).get("unresolved_tokens") or []
            _sides_only = bool(_declared_ring["instances"])
            rep = {
                "check": "slot_pad_budget",
                "verdict": "UNDECIDED",
                "rc": 2,
                "reason_class": _reason_taxonomy.ZERO_DENOMINATOR,
                "budget_basis": "37.5self:own_pad_ring",
                "deliverable_source": _die_word_source,
                "reason": (
                    "this delivery is a DIE and binds no operator template, so "
                    "the die is its own operator and its budget is its own pad "
                    "ring — and the design states that ring in neither place it "
                    "may be stated: "
                    + ("`pad_order_by_side` names "
                       f"{len(_declared_ring['instances'])} pad instance(s) but "
                       "`pad_signal_map` is NOT_DETERMINED, so which SIGNAL each "
                       "pad brings out is unstated and a pad count cannot tell a "
                       "ring that carries these pins from one that does not"
                       if _sides_only else
                       f"{', '.join(DECLARED_RING_KEYS)} are NOT_DETERMINED in "
                       f"{_TD.DECLARATION_REL}")
                    + "; and no pad-placement section was read out of the "
                      f"{len(_scanned)} design document(s) scanned"
                    + (f" (a token in it did not resolve from a declared "
                       f"parameter: {', '.join(_unresolved_tok[:8])})"
                       if _unresolved_tok else "")
                    + (f" ({len(_unread)} document(s) could not be read: "
                       + "; ".join(f"{u.get('file')}: {u.get('reason')}"
                                   for u in _unread[:4]) + ")"
                       if _unread else "")
                    + ". The ring step "
                    + OWN_RING_STEP
                    + " generates is generated FROM this same declaration, so "
                      "this is not a question an upstream step answers — the "
                      "incomplete input is named here"),
                "findings": [{"severity": "ERROR",
                              "rule": "DIE_DECLARES_NO_PAD_RING",
                              "message": (
                                  "neither "
                                  f"{'/'.join(DECLARED_RING_KEYS)} in "
                                  f"{_TD.DECLARATION_REL} nor a pad-placement "
                                  "section in the design's own documents "
                                  "states which pad carries which net"),
                              "owner": "design input"}],
                "declared_ring": _declared_ring,
                "derived_ring": _derived,
                "documents_scanned": _scanned,
                "documents_unreadable": _unread,
                "note": ("a design-input gap, named — not a question blocked "
                         "on an upstream step"),
            }
            rc = 2
        else:
            _inv = declared_ring_inventory(_ring, ports)
            # D2: the same answers step 15.5ic refuses on, stated here first,
            # from the same reader. A net the ring puts on two edges is
            # PORT_ON_TWO_SIDES there; a group row no implemented port (and
            # no accepted declared rename) resolves is PAD_GROUP_UNRESOLVED
            # there, whether or not it also leaves an RTL bit unbonded (its
            # family may have no implemented port at all).
            _two_sides = list(_ring.get("nets_on_two_sides") or [])
            _groups_unresolved = list(_ring.get("groups_unresolved") or [])
            _renames_rejected = list(
                _ring.get("renamed_interfaces_rejected") or [])
            _splits_rejected = list(
                _ring.get("exposed_output_splits_rejected") or [])
            _fits = (_inv["unbonded_count"] == 0 and not _two_sides
                     and not _groups_unresolved and not _splits_rejected)
            # THE ARITHMETIC, STATED (R-0915-101): pads owed, pads the ring
            # places, and the supply pair the ring must also carry. The supply
            # COUNT is an obligation this gate states and does NOT decide on:
            # which macro plays each polarity is the IO cell library's answer,
            # made at step 15.5ic, and a pad this gate cannot see selected is
            # not a pad it may call missing.
            _arith = {
                "signal_pads_owed": _inv["declared_signal_bits"],
                "signal_pads_placed_by_the_ring":
                    _inv["bonded_declared_bits"],
                "signal_pads_owed_with_no_pad": _inv["unbonded_count"],
                "ring_capacity_pads": _inv["declared_pads_total"],
                "supply_pads_owed_minimum": SUPPLY_PADS_MINIMUM_PAIR,
                "supply_pads_selected": None,
                "supply_pads_selected_by": {
                    "step": SUPPLY_PAD_SELECTION_STEP,
                    "program": SUPPLY_PAD_SELECTION_PROGRAM,
                    "why_not_here": (
                        "one external POWER pad and one external GROUND pad is "
                        "the minimum complete pair and is a topology fact; "
                        "WHICH macro plays each polarity is read from the PDK "
                        "IO cell library's LEF pin roles, which this step does "
                        "not open. Stated as an obligation, and it does not "
                        "move this verdict"),
                },
                "ring_geometric_capacity_pads": None,
                "ring_geometric_capacity_why_not": (
                    "how many pads FIT on the die edges needs the die "
                    "rectangle and the pad master widths; this gate counts the "
                    "ring the design declares and does not size it"),
            }
            rep = {
                "check": "slot_pad_budget",
                "verdict": "FITS" if _fits else "DOES_NOT_FIT",
                "rc": 0 if _fits else 1,
                "budget_basis": "37.5self:own_pad_ring",
                "ring_source": _ring_source,
                "basis": (
                    "this delivery is a DIE and binds no operator template, so "
                    "the die is its own operator: the budget is the pad ring "
                    "the design declares for itself ("
                    + (f"{_TD.DECLARATION_REL}, "
                       if _ring_source == "declaration:pad_signal_map"
                       else f"{_ring.get('source')}, ")
                    + f"{_inv['declared_pads_total']} pad(s) from "
                    f"{'+'.join(_inv['declared_by'])}) against the "
                    f"{_inv['declared_signal_bits']} signal bit(s) it declares "
                    f"on top module {a.top!r}. No external slot exists to "
                    "measure against; the operator catalogue on disk is "
                    "information, not a purchase"),
                "own_ring": _inv,
                "own_ring_arithmetic": _arith,
                "own_ring_measured_by": {"step": OWN_RING_STEP,
                                         "gate": OWN_RING_GATE,
                                         "gate_always": OWN_RING_GATE_ALWAYS,
                                         "evidence": OWN_RING_EVIDENCE_REL},
                "interface_budget": _budget,
                "top": a.top,
                "top_source": _top_source,
                "deliverable_source": _die_word_source,
            }
            if _derived is not None and _derived.get("measurable"):
                rep["derived_ring"] = {
                    k: _derived[k] for k in
                    ("source", "heading", "by_side", "groups",
                     "groups_unresolved", "renamed_interfaces",
                     "renamed_interfaces_rejected",
                     "exposed_output_splits", "exposed_output_splits_rejected",
                     "nets_on_two_sides", "documents_scanned",
                     "documents_unreadable", "parameter_defaults")
                    if k in _derived}
            if not _fits:
                _why = []
                if _inv["unbonded_count"]:
                    _why.append(
                        f"{_inv['unbonded_count']} declared signal bit(s) "
                        f"have no pad in the ring this design declares: "
                        + ", ".join(_inv["unbonded_declared_bits"]))
                if _two_sides:
                    _why.append(
                        f"the ring puts {len(_two_sides)} net(s) on two "
                        f"edges (PORT_ON_TWO_SIDES at step {OWN_RING_STEP}): "
                        + ", ".join(_two_sides[:12]))
                if _groups_unresolved:
                    _why.append(
                        f"pad-placement group row(s) on side(s) "
                        f"{', '.join(_groups_unresolved)} resolve to no "
                        f"implemented port (PAD_GROUP_UNRESOLVED at step "
                        f"{OWN_RING_STEP}). A reused IP whose ports were "
                        f"renamed from the document's illustrative names "
                        f"declares each rename in phase2/stage1/rtl/"
                        f"SOURCE_MANIFEST.json renamed_interfaces, one pair "
                        f"per placement group (catalog-glue-author)"
                        + (f"; {len(_renames_rejected)} declared pair(s) were "
                           f"rejected by the rename acceptance rule: "
                           + "; ".join(
                               f"{r['l9']}->{r['rtl']}: "
                               + ", ".join(r["reasons"])
                               for r in _renames_rejected[:4])
                           if _renames_rejected else ""))
                if _splits_rejected:
                    _why.append(
                        f"{len(_splits_rejected)} declared exposed output "
                        "split(s) were rejected by the selected-core and L9 "
                        "interface check (EXPOSED_OUTPUT_SPLIT_INVALID at step "
                        f"{OWN_RING_STEP}): "
                        + "; ".join(str(row.get("reasons"))
                                    for row in _splits_rejected[:4]))
                rep["reason"] = "; ".join(_why)
            rc = rep["rc"]

    elif _route_na is not None:
        rep = _route_na
        rc = 2
    elif not slots and _declared_no_slot:
        rep = {"check": "slot_pad_budget", "verdict": "NOT_APPLICABLE", "rc": 2,
               "reason_class": _reason_taxonomy.DESIGN_DECLARED_NA,
               "skip_kind": "class-not-applicable",
               "reason": (_declared_no_slot + " — no operator slot exists to "
                          "budget the top-level signal pads against; the die "
                          "sizes its own pad ring at step 15.5ic"),
               "note": "a design-declared route, not an unanswered question"}
        rc = 2
    elif not slots or not ports:
        why = ("no slot files under input/submission_template/slots — step "
               "0.5ic has not run" if not slots else
               f"top module '{a.top}' not found in "
               f"{rtl_files or '(no --rtl given and no RTL under ' + os.path.join(*_RTL_DIR_REL) + ')'}")
        reason_class = (_reason_taxonomy.BLOCKED_BY_UPSTREAM if not slots
                        else _reason_taxonomy.EXECUTION_ERROR)
        rep = {"check": "slot_pad_budget", "verdict": "UNDECIDED", "rc": 2,
               "reason_class": reason_class,
               "reason": why,
               "note": "a question that could not be asked has not passed"}
        rc = 2
    else:
        rep = evaluate(slots, ports)
        rc = int(rep["rc"])
    if defaults_used:
        rep["params_from_top_module_defaults"] = defaults_used
    if derived_used:
        rep["params_from_top_module_exact_expressions"] = derived_used

    if _geometry_operator:
        rep["operator_template_contract"] = _geometry_operator
        rep["budget_basis"] = "operator_geometry:design_pad_ring"
        rep["physical_fit_verdict"] = "NOT_MEASURED"
        # The existing ring arithmetic is a connectivity budget. Operator
        # geometry, mask/layer restrictions and later native fit remain owed.
        for label in ("reason", "basis"):
            if isinstance(rep.get(label), str):
                rep[label] = rep[label].replace(
                    "binds no operator template", "binds geometry-only operator constraints").replace(
                    "die is its own operator", "design supplies its own pad roster").replace(
                    "No external slot exists to measure against; the operator catalogue on disk is information, not a purchase",
                    "The operator geometry/mask restrictions remain binding; it declares no fixed pad roster")

    if a.out_json:
        # WHERE A RELATIVE --json LANDS (#712). It used to land wherever the
        # CALLER happened to be standing, because nothing resolved it against
        # the project. Both wirings run with `cwd=<project>` so they were
        # unaffected, but the contract was loose enough that
        # `--json ../../x.json` wrote outside the project entirely. MEASURED
        # while testing exactly that: a probe put a report in the repository
        # root and another in the invoking user's home directory.
        #
        # A relative destination is now resolved against the PROJECT, which is
        # what both callers already meant, and one that climbs out of it is a
        # rejected command line (rc 3) rather than a silent write somewhere
        # nobody will look. An ABSOLUTE path is left alone: that is an explicit
        # choice by the caller, not an accident.
        #
        # HONEST LIMIT: containment is checked on the LOGICAL path. A symlink
        # inside the project that points out of it still leads out. That is a
        # layout its owner chose, and refusing it would break projects that
        # legitimately share a reports tree.
        out_path = a.out_json
        if not os.path.isabs(out_path):
            proj = os.path.abspath(a.project)
            cand = os.path.normpath(os.path.join(proj, out_path))
            if cand != proj and not cand.startswith(proj + os.sep):
                _usage.usage_error(
                    "slot_pad_budget_check",
                    f"--json {a.out_json} climbs out of the project")
                return _usage.RC_USAGE
            out_path = cand
        # vibe-ic#1082 — a declared report destination is written through
        # `_atomic_artefact`, never a bare `open(..., 'w')`: a reader that finds
        # the file half-written cannot tell a truncated report from a short one.
        write_json(out_path, rep, indent=2, sort_keys=True)
    # `[CANNOT CHECK]` on the UNDECIDED line, per the house convention recorded
    # in docs/PPA_INTERFACES.md §1: "print a marker ... so a 2 can never be read
    # as a silent skip". This program is not a `ppa_*` module and that section
    # does not formally bind it, but rc 2 here IS the silent-skip shape — no
    # slots ingested, or no port list found — and a bracketed marker makes the
    # disclosed skip greppable beside every other gate that discloses one.
    _mark = ("[CANNOT CHECK] " if rep["verdict"] == "UNDECIDED" else
             "[N/A] " if rep["verdict"] == "NOT_APPLICABLE" else "")
    print(f"{_mark}slot_pad_budget_check: {rep['verdict']}")
    if rep["verdict"] in ("UNDECIDED", "NOT_APPLICABLE"):
        print(f"  {rep.get('reason', 'no reason recorded')}")
    elif rep.get("budget_basis") in {"37.5self:own_pad_ring", "operator_geometry:design_pad_ring"}:
        # The die's own ring is a different measurement from an operator
        # slot's inventory and says so in its own words, not in the slot
        # report's field names.
        _inv_p = rep.get("own_ring") or {}
        _ar = rep.get("own_ring_arithmetic") or {}
        print(f"  basis                          : {rep['budget_basis']}")
        print(f"  ring the design declares       : {rep.get('ring_source')} "
              f"({(rep.get('derived_ring') or {}).get('source') or _TD.DECLARATION_REL})")
        print(f"  declared signal bits           : "
              f"{_inv_p.get('declared_signal_bits')}")
        print(f"  signal pads owed vs placed     : "
              f"{_ar.get('signal_pads_owed')} owed / "
              f"{_ar.get('signal_pads_placed_by_the_ring')} placed "
              f"({_ar.get('signal_pads_owed_with_no_pad')} with no pad)")
        print(f"  ring capacity (declared pads)  : "
              f"{_ar.get('ring_capacity_pads')}")
        print(f"  supply pads owed (minimum pair): "
              f"{_ar.get('supply_pads_owed_minimum')} — selection is step "
              f"{SUPPLY_PAD_SELECTION_STEP}'s "
              f"({SUPPLY_PAD_SELECTION_PROGRAM}); does not move this verdict")
        if rep["verdict"] != "FITS":
            print(f"  with no pad                    : "
                  f"{', '.join(_inv_p.get('unbonded_declared_bits') or [])}")
    else:
        print(f"  declared signal bits           : {rep['declared_signal_bits']}")
        print(f"  largest slot digital signal pads: "
              f"{rep['largest_digital_signal_pad_count']}")
        if rep["verdict"] != "FITS":
            print(f"  over by                        : "
                  f"{rep['over_by_ratio']}x  "
                  f"(after folding every candidate: "
                  f"{rep['over_by_ratio_after_fold']}x)")
        for f in rep["fold_candidates"]:
            print(f"  fold candidate                 : {f['input_bus']} / "
                  f"{f['output_bus']} ({f['width']} bits) — NOT applied; "
                  f"safety is a protocol fact this gate does not decide")
    return rc


if __name__ == "__main__":
    sys.exit(main())
