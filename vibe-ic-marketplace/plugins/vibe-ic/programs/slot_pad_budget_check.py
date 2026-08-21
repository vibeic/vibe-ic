#!/usr/bin/env python3
"""slot_pad_budget_check — does this design's interface FIT the purchased slot?

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
    edge_llm_matmul_accel    107                     52                2.1x

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

VERDICTS AND EXIT CODES
=======================
    FITS               rc 0   the declared interface fits a slot as declared
    FITS_AFTER_FOLD    rc 0   fits only if a named fold is taken; the fold is
                              NOT applied here and the candidates are listed
    DOES_NOT_FIT       rc 1   no slot can bond it, even after folding every
                              same-width in/out pair -- with the shortfall
    UNDECIDED          rc 2   no slots ingested, or no port list could be read.
                              A question that could not be asked has not passed.

rc 2 is the flow's "could not measure" tier. It is NEVER returned for a design
that simply does not fit: that is an answer, and it is rc 1.

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
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _atomic_artefact import write_json  # noqa: E402  vibe-ic#1082
import _gate_usage_exit as _usage  # noqa: E402  vibe-ic#712

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
        tok = tok.strip().strip("`")
        # a bare literal
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
        return None

    a, b = _val(lo), _val(hi)
    if a is None or b is None:
        return None
    return abs(a - b) + 1


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
                 "", src, flags=re.M)
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
    # Which port NAMES sat inside a conditional block, read off the ORIGINAL
    # text (the directives were stripped above so the parse would not lose
    # them). Reported, never guessed at.
    conditional: set = set()
    raw_no_comment = stripped
    depth_cond = 0
    for line in raw_no_comment.splitlines():
        # Stripped again HERE, on the value the scan actually reads. The
        # whole-text pass above already cleared it; this call is what makes
        # that true LOCALLY, so a later change to where `raw_no_comment` comes
        # from cannot quietly re-open the hole. `_DIR_RE` must never see a
        # character a stripper has not looked at.
        s = _strip_hdl_attributes(_strip_hdl_comments(line)).strip()
        if re.match(r"^`(?:ifdef|ifndef)\b", s):
            depth_cond += 1
            continue
        if re.match(r"^`endif\b", s):
            depth_cond = max(0, depth_cond - 1)
            continue
        if depth_cond > 0:
            dm2 = _DIR_RE.match(s)
            if dm2:
                toks2 = dm2.group(2).replace(")", " ").split()
                if toks2:
                    conditional.add(toks2[-1].strip(";,"))

    ports: List[Dict[str, Any]] = []
    unparsed: List[str] = []
    for decl in rest[open_i + 1:close_i].split(","):
        # Same rule as the conditional scan above: the chunk that reaches
        # `_DIR_RE` is stripped on its own account, not on a sibling's.
        decl = _strip_hdl_attributes(_strip_hdl_comments(decl)).strip()
        if not decl:
            continue
        dm = _DIR_RE.match(decl)
        if not dm:
            # A chunk that is not a port declaration is usually a continuation
            # of a packed type; record a bounded sample rather than discarding
            # silently, so a parse that is losing ports is VISIBLE.
            if len(unparsed) < 12:
                unparsed.append(decl[:60])
            continue
        direction, tail = dm.group(1), dm.group(2)
        toks = tail.replace(")", " ").split()
        if not toks:
            continue
        name = toks[-1].strip(";,")
        ports.append({"dir": direction, "name": name,
                      "width": _width(tail, params),
                      "conditional": name in conditional})
    if ports:
        ports[0]["_unparsed_chunks"] = unparsed
    return ports


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
            "reason": "the width of "
                      f"{len(budget['unresolved_width_ports'])} port(s) is "
                      "parameterised and no value was supplied: "
                      + ", ".join(budget["unresolved_width_ports"][:12])
                      + " — supply them with --param NAME=VALUE; a width this "
                        "gate invented would be a pad count nobody chose",
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
    every remaining file arrives as an extra positional. argparse rejects
    that with **exit 2** -- and exit 2 is this flow's VACUOUS_PASS tier. The
    gate would report a disclosed skip on every multi-file design, forever,
    and the skip would look like the ordinary "no slots ingested" one.

    So the clause carries no glob and the expansion happens here, where a
    directory that does not exist is an ANSWER (`[]` -> rc 2 UNDECIDED with a
    reason naming the directory) rather than a usage error wearing the same
    exit code as a skip.
    """
    d = os.path.join(project, *_RTL_DIR_REL)
    if not os.path.isdir(d):
        return []
    return [os.path.join(d, fn) for fn in sorted(os.listdir(d))
            if fn.lower().endswith((".v", ".sv"))]


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

    slots = _load_slots(a.project)
    # An explicit --rtl always wins; discovery is the fallback the flow uses.
    rtl_files = list(a.rtl) or _discover_rtl(a.project)
    ports: Optional[List[Dict[str, Any]]] = None
    for f in rtl_files:
        try:
            with open(f, "r", encoding="utf-8", errors="replace") as fh:
                ports = parse_top_ports(fh.read(), a.top, params)
        except OSError:
            ports = None
        if ports:
            break

    if not slots or not ports:
        why = ("no slot files under input/submission_template/slots — step "
               "0.5ic has not run" if not slots else
               f"top module '{a.top}' not found in "
               f"{rtl_files or '(no --rtl given and no RTL under ' + os.path.join(*_RTL_DIR_REL) + ')'}")
        rep = {"check": "slot_pad_budget", "verdict": "UNDECIDED", "rc": 2,
               "reason": why,
               "note": "a question that could not be asked has not passed"}
        rc = 2
    else:
        rep = evaluate(slots, ports)
        rc = int(rep["rc"])

    if a.out_json:
        # vibe-ic#1082 — a declared report destination is written through
        # `_atomic_artefact`, never a bare `open(..., 'w')`: a reader that finds
        # the file half-written cannot tell a truncated report from a short one.
        write_json(a.out_json, rep, indent=2, sort_keys=True)
    print(f"slot_pad_budget_check: {rep['verdict']}")
    if rep["verdict"] == "UNDECIDED":
        print(f"  {rep.get('reason', 'no reason recorded')}")
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
