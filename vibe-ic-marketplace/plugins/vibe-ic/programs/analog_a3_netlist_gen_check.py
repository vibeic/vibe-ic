#!/usr/bin/env python3
"""analog_a3_netlist_gen_check.py — A3 deterministic gate (v1.6.35).

Verifies that the upstream `analog-netlist-gen` skill has emitted the
canonical per-block A3 artefact:

    analog/<block>/<block>.sp

with substance:

  * file size ≥ 200 bytes (the v1.6.30 substance threshold for .sp;
    a placeholder `* netlist stub\\n.end\\n` is < 50 bytes).
  * contains a `.subckt` / `.SUBCKT` declaration (the canonical
    SPICE module wrapper). Without this, the file is at best a
    raw stimulus file, not a reusable analog block netlist.
  * instantiates at least ONE device card inside a `.subckt` body.
    A `.subckt`/`.ends` shell with a comment where the circuit should
    be is a placeholder, and it clears both rules above: pad it with
    header comments past 200 bytes and it used to PASS A3 outright.

Failure rules:
  A3_NETLIST_MISSING        — <block>.sp absent
  A3_NETLIST_TOO_SMALL      — < 200 bytes
  A3_NETLIST_NO_SUBCKT      — no .subckt declaration
  A3_NETLIST_NO_DEVICES     — .subckt body instantiates no device
  A3_NETLIST_IDEAL_PRIMITIVE_IN_BLOCK
                            — the block subcircuit instantiates an IDEAL SPICE
                              primitive (`V`/`I` source, `R`/`C`/`L` with a
                              literal value, or a controlled/behavioural
                              `E`/`F`/`G`/`H`/`B` source). No PDK declares a
                              drawn device for any of them, so the block cannot
                              reach an LVS match at A6 no matter how well it is
                              laid out. See `_ideal_primitive_cards`.
  A3_DESIGN_CONTENT_UNDECLARED
                            — the netlist is substantive and nothing says what
                              circuit is in it. LAST, behind every value rule.

Note: this is a thin wrapper aligned with
`analog_artefact_substance_check`'s .sp size rule, plus the additional
`.subckt` + device-instantiation semantic checks.

THREE TIERS, not two. A netlist whose producer discloses that its circuit came
from a topology library certifies as `PASS_STRUCTURE_ONLY` — its own tier, with
the `STRUCTURE_ONLY:` sentinel — because an honest ceiling that is failed
teaches the next run to stop being honest. A netlist that declines to say what
is in it certifies as nothing. The ordering, end to end and the same one every
sibling gate uses:

    design-bound  >  structure-only (disclosed)  >  undisclosed

Until this change the gate had the DISCLOSED tier and no UNDISCLOSED one, so a
design-bound tree and a silent tree were byte-identical here — see
`_content_klass` for the measurement.

VACUOUS_PASS when no `analog_block_list.json` exists under
`phase3/analog/` (the analog runner's root) or `phase1/analog/` (the
root every A-step's flow `condition:` names), or it declares no blocks.

INCOMPLETE (rc=1) in project mode when SOME declared blocks have a
netlist and others have none.

Artefact resolution: `phase3/analog/<block>/<block>.sp` (what the analog
runner writes) OR `phase2/analog/<block>/<block>.sp` (what the flow
declares as A3's required_output).

chip-AGNOSTIC.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import List, Optional

from _analog_a_check_common import (
    BLOCK_LIST_ABSENT_REASON,
    CONTENT_STRUCTURE_ONLY, CONTENT_UNDISCLOSED,
    NETLIST_PROVENANCE_ARTEFACT,
    load_block_list, select_blocks, make_argparser, vacuous_pass,
    artefact_missing_for_block, emit_pass, emit_fail, emit_incomplete,
    netlist_content, resolve_block_artefact, structure_only_disclosure,
)
from _analog_stub_marker import is_stub_text
import _analog_producer_common as _pc

GATE = "analog_a3_netlist_gen_check"
#: The producer's sidecar, and the file that answers BOTH questions this gate
#: asks about the deck's origin.
#:
#: `A3_PROVENANCE_REF_MISMATCH` is silent without it, because a skill-authored
#: netlist makes no digest claim and a rule that failed it would punish the
#: ABSENCE OF A CLAIM rather than a false one.
#:
#: `A3_DESIGN_CONTENT_UNDECLARED` is NOT silent without it, and the two are not
#: in tension: that rule refuses to CERTIFY on a claim that was never made.
#: Exempting the missing sidecar there is exactly how silence became cheaper
#: than disclosure — a skill that writes no record would outrank a producer that
#: writes an honest one.
SIDECAR = NETLIST_PROVENANCE_ARTEFACT
SKILL = "analog-netlist-gen"
MIN_BYTES = 200
DECLARED_PHASE = 2

_SUBCKT_RE = re.compile(r"(?im)^\s*\.subckt\s+\S+")

_SUBCKT_START_RE = re.compile(r"(?i)^\.subckt\b")
_SUBCKT_END_RE = re.compile(r"(?i)^\.ends\b")
# SPICE element cards that constitute an actual circuit:
#   X sub-circuit instance   M MOSFET   R/C/L passives   D diode
#   Q BJT   J JFET   Z MESFET/HEMT
#   E/F/G/H controlled sources, B behavioural source (behavioural blocks)
# Deliberately EXCLUDES V and I: a body containing only independent
# sources is stimulus, not a block netlist.
_DEVICE_CARD_RE = re.compile(r"(?i)^[xmrcldqjzefghb]\S")


# ── LAYOUT-REALIZABILITY: an ideal primitive inside the block subcircuit ──
#
# THE RULE, with no tool, PDK or design name in it:
#
#   A block netlist that instantiates a SPICE primitive for which no PDK
#   declares a drawn device has made its own per-block physical verification
#   unreachable, and it must be told so where the netlist is written — not
#   three steps later where the compare fails.
#
# WHY IT BELONGS AT A3 AND NOT AT A6. A6 grades DRC == 0 AND a netgen LVS
# match. The netgen PDK setup declares device classes for the PDK's own
# `res_*`/`cap_*` subcircuits and declares NOTHING that equates an ideal SPICE
# primitive to a drawn one, so a deck carrying one can never match — by
# construction, before anyone draws anything. Measured on a deck built to the
# authoring skill's own worked example (`Vbias nbias VSS 0.8`, `R1 VOUT FB
# 100k`, `Cc nd2 VOUT 3p` inside `.subckt ota`): A3, A4 and A5 all certified
# it, and the ONLY signal was an A6 LVS mismatch three steps downstream, which
# reads as a layout defect. The failure now lands where the defect is
# introduced.
#
# WHAT COUNTS AS IDEAL, as SPICE card grammar rather than as a name list:
#
#   * `V`/`I` — an independent source. There is no drawn voltage source in any
#     PDK, so the CARD LETTER alone decides.
#   * `E`/`F`/`G`/`H`/`B` — controlled and behavioural sources. Same argument,
#     and covering them is what stops the rule being evaded by writing a
#     resistor as a linear VCCS.
#   * `R`/`C`/`L` — ideal ONLY when the value field holds a NUMBER or an
#     expression. `R1 a b 100k` is an ideal resistor; `R1 a b <pdk_res_model>
#     w=1u l=10u` names a model the PDK can (and does) declare a device class
#     for, and is left alone. A SPICE identifier cannot begin with a digit, so
#     the two are separable exactly, with no model-name list.
#
# WHAT IS DELIBERATELY OUT OF SCOPE:
#
#   * TOP-LEVEL cards (outside every `.subckt`). `<block>.sp` is `.include`d by
#     its testbench and the flow's own contract puts stimulus in
#     `tb_<block>.sp`; a card at file scope is not part of the block.
#   * Anything inside a TESTBENCH subcircuit. Sources and loads are CORRECT
#     there — the testbench is where the authoring skill's own remediations
#     send them ("hoist the source to a port", "move the load to the TB"), so a
#     rule that fired on them would push the fix back out again.
#   * `M`/`Q`/`J`/`Z`/`D` — every one of them names a model and IS a drawn
#     device. `X` — a subcircuit instance, which is the form every PDK device
#     takes.
_SUBCKT_DECL_RE = re.compile(r"(?i)^\.subckt\s+(\S+)")

#: Cards whose LETTER alone settles it: no PDK draws a source.
_IDEAL_SOURCE_LETTERS = frozenset("viefghb")
#: Cards that are ideal only when they carry a value rather than a model name.
_IDEAL_PASSIVE_LETTERS = frozenset("rcl")

#: The testbench naming convention, and the ONLY name-shaped input in this
#: rule. It is a SPICE/HDL-wide convention, not a design, chip or vendor
#: token — and it can only ever SUPPRESS a finding, so a deck that does not
#: follow it loses nothing but a false negative on its own stimulus.
_TB_SUBCKT_RE = re.compile(
    r"(?i)^(?:tb|testbench)(?:[_\-].*)?$|^.*[_\-](?:tb|testbench)$")

_IDEAL_LETTER_MEANING = {
    "v": "independent voltage source", "i": "independent current source",
    "e": "VCVS (controlled source)", "f": "CCCS (controlled source)",
    "g": "VCCS (controlled source)", "h": "CCVS (controlled source)",
    "b": "behavioural source",
    "r": "ideal resistor", "c": "ideal capacitor", "l": "ideal inductor",
}


def _is_value_token(tok: str) -> bool:
    """True when `tok` is a VALUE rather than a model name.

    Exact SPICE grammar, no list: an identifier may not begin with a digit, so
    a leading digit / sign / decimal point is a number, and a leading brace or
    quote is an expression. A token carrying `=` is a parameter assignment
    (`R=100k`), which is the parametrised form of the same ideal element."""
    if not tok:
        return True
    if "=" in tok:
        return True
    return tok[0].isdigit() or tok[0] in "+-.{'\"("


def _passive_is_ideal(fields: List[str]) -> bool:
    """`Rname n+ n- <value|model> ...` — ideal iff field 3 is a value.

    A malformed card with no fourth field is treated as ideal: it names no
    model, so nothing downstream can equate it to a drawn device either."""
    if len(fields) < 4:
        return True
    return _is_value_token(fields[3])


def _ideal_primitive_cards(text: str) -> List[dict]:
    """Every ideal-primitive card instantiated inside a non-testbench
    `.subckt` body, as `{subckt, card, letter, line}`.

    Same walk discipline as `_subckt_device_count` — comments (`*`, `;`),
    continuations (`+`) and dot-commands are skipped, and depth is tracked so
    file-scope cards are out of scope. chip-AGNOSTIC: pure SPICE card
    grammar."""
    stack: List[str] = []
    hits: List[dict] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line[0] in "*;+":
            continue
        decl = _SUBCKT_DECL_RE.match(line)
        if decl:
            stack.append(decl.group(1))
            continue
        if _SUBCKT_END_RE.match(line):
            if stack:
                stack.pop()
            continue
        if not stack:
            continue
        if any(_TB_SUBCKT_RE.match(s) for s in stack):
            continue
        fields = line.split()
        letter = fields[0][0].lower()
        ideal = (letter in _IDEAL_SOURCE_LETTERS
                 or (letter in _IDEAL_PASSIVE_LETTERS
                     and _passive_is_ideal(fields)))
        if ideal:
            hits.append({"subckt": stack[-1], "card": fields[0],
                         "letter": letter, "line": lineno})
    return hits


def _ideal_primitive_fail(block: str, rel: str, text: str) -> Optional[dict]:
    """The finding, or None. Named remediations, because every one of them is
    an EDIT SOMEWHERE ELSE — the netlist is the symptom's address, not its
    cure."""
    hits = _ideal_primitive_cards(text)
    if not hits:
        return None
    shown = ", ".join(
        f"`{h['card']}` ({_IDEAL_LETTER_MEANING[h['letter']]}) at "
        f"{rel}:{h['line']} in `.subckt {h['subckt']}`"
        for h in hits[:4])
    more = f" (+{len(hits) - 4} more)" if len(hits) > 4 else ""
    return {
        "block": block, "rule": "A3_NETLIST_IDEAL_PRIMITIVE_IN_BLOCK",
        "rel_path": rel,
        "ideal_cards": hits,
        "detail": (
            f"{len(hits)} ideal SPICE primitive(s) inside the block "
            f"subcircuit: {shown}{more}. No PDK declares a drawn device for "
            f"any of them, so the per-block LVS compare at A6 cannot match "
            f"however well the block is laid out — A6 is unreachable by "
            f"construction, and A4 and A5 will certify the deck on the way "
            f"there. Fix it HERE, before drawing anything: hoist an ideal "
            f"bias source to a block PORT the testbench drives; replace an "
            f"ideal R or C with the PDK's own resistor/capacitor device "
            f"(instantiated as `X<name> ... <pdk_device> w= l=`, or as an "
            f"R/C card naming a PDK model, both of which this rule leaves "
            f"alone); move an ideal LOAD element to `tb_{block}.sp`, where "
            f"it belongs and where this rule does not look. Then RE-RUN A4 "
            f"on the revised deck — a netlist change that was never "
            f"re-simulated is not a fix."),
    }


def _subckt_device_count(text: str) -> int:
    """Number of device cards instantiated inside `.subckt`/`.ends` bodies.

    Comment (`*`, `;`) and continuation (`+`) lines are skipped, as are
    dot-commands — so a `.subckt` shell wrapping nothing but comments
    counts zero. chip-AGNOSTIC: pure SPICE card grammar."""
    depth = 0
    count = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line[0] in "*;+":
            continue
        if _SUBCKT_START_RE.match(line):
            depth += 1
            continue
        if _SUBCKT_END_RE.match(line):
            depth = max(0, depth - 1)
            continue
        if depth > 0 and _DEVICE_CARD_RE.match(line):
            count += 1
    return count


def _check_block(project: Path, block: str
                 ) -> tuple[Optional[str], List[dict]]:
    path, found = resolve_block_artefact(
        project, block, f"{block}.sp", DECLARED_PHASE)
    if not found:
        return "MISSING", [{
            "block": block, "rule": "A3_NETLIST_MISSING",
            "rel_path": str(path.relative_to(project)),
            "detail": f"{block}.sp not found",
        }]
    try:
        size = path.stat().st_size
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return "FAIL", [{
            "block": block, "rule": "A3_NETLIST_TOO_SMALL",
            "rel_path": str(path.relative_to(project)),
            "detail": f"OSError: {exc}",
        }]
    if size < MIN_BYTES:
        return "FAIL", [{
            "block": block, "rule": "A3_NETLIST_TOO_SMALL",
            "rel_path": str(path.relative_to(project)),
            "detail": f"{size}B < min {MIN_BYTES}B (placeholder?)",
        }]
    if not _SUBCKT_RE.search(text):
        return "FAIL", [{
            "block": block, "rule": "A3_NETLIST_NO_SUBCKT",
            "rel_path": str(path.relative_to(project)),
            "detail": "no `.subckt <name>` declaration found",
        }]
    devices = _subckt_device_count(text)
    if devices == 0:
        return "FAIL", [{
            "block": block, "rule": "A3_NETLIST_NO_DEVICES",
            "rel_path": str(path.relative_to(project)),
            "detail": ("`.subckt` body instantiates 0 device cards — an "
                       "empty subcircuit shell is a placeholder, not a "
                       "netlist (a size + `.subckt` pair alone cannot tell "
                       "the two apart)"),
        }]
    stale = _stale_vs_ir_fail(project, block, path, text)
    if stale:
        return "FAIL", [stale]
    ref = _provenance_ref_fail(project, block, path, text)
    if ref is not None:
        return "FAIL", [ref]

    if is_stub_text(text):
        # THE DETERMINISTIC-STUB SHORT-CIRCUIT, identical to the one
        # `analog_hardmacro_check` keeps at A8 and for the same reason: a stub
        # marker is ITSELF a disclosure of what this deck is, and the runner's
        # PASS_WITH_STUB is its own already-disclosed tier. The content question
        # must not reach it and turn a disclosed stub red — that would be the
        # inverted incentive one level up, charging for a disclosure.
        return "PASS", []

    # ── LAYOUT-REALIZABILITY, asked after the stub short-circuit ──────────
    # POSITION IS PART OF THE RULE, and it is not the one the value rules
    # above take. Those fire on a stub too, because a 34-byte file is not a
    # netlist whatever it says about itself. This one must NOT: the runner's
    # own deterministic A3 stub is literally `.subckt <block> ... r_stub vin
    # vout 1k ... .ends`, an ideal resistor inside a block subcircuit, and it
    # already DISCLOSES that it is a placeholder. Failing it here would charge
    # for the disclosure — the same inverted incentive the tier below exists
    # to remove — and would replace an accurate PASS_WITH_STUB with a
    # realizability complaint about a circuit nobody claims is real.
    #
    # And BEFORE the certification question, which is the standing order on
    # this track: a value rule names a deeper cause and answers "what is in
    # it?" as a side effect, never the other way round.
    ideal = _ideal_primitive_fail(block, str(path.relative_to(project)), text)
    if ideal is not None:
        return "FAIL", [ideal]

    # ── the certification question, asked LAST ────────────────────────────
    # Behind every VALUE rule above, each of which names a deeper cause and
    # answers this one as a side effect: a 34-byte file, a `.subckt` shell with
    # no devices, or a digest that does not recompute is diagnosed as itself on
    # a tree that also says nothing about its subject. The reverse is not true —
    # "you did not say what is in it" tells a reader nothing about a netlist
    # that is not a netlist. Same position as A4's, A7's and A8's.
    klass = _content_klass(project, block)
    rel = str(path.relative_to(project))
    if klass == CONTENT_UNDISCLOSED:
        # `sidecar_found` separates "no producer record exists" from "one
        # exists and names no content". Those send a reader to two different
        # places, so the message asks the filesystem instead of inferring.
        _, sidecar_found = resolve_block_artefact(
            project, block, SIDECAR, DECLARED_PHASE)
        said = (f"`{SIDECAR}` beside it records no answer to"
                if sidecar_found else
                f"no `{SIDECAR}` exists beside it to say")
        return "FAIL", [{
            "block": block, "rule": "A3_DESIGN_CONTENT_UNDECLARED",
            "rel_path": rel,
            "detail": (f"the deck is substantive — it clears the size, "
                       f"`.subckt` and device-instantiation rules — and {said} "
                       f"what circuit is in it (`design_content`). A deck "
                       f"rendered from a topology library and a deck sized to "
                       f"this design's spec are indistinguishable in every "
                       f"other field of this file, and everything downstream "
                       f"inherits this record: the corner sweep republishes "
                       f"it, and the hardmacro digital PnR instantiates is "
                       f"graded against it. Declaring "
                       f"`{CONTENT_STRUCTURE_ONLY}` is not a penalty — it "
                       f"certifies, in its own disclosed tier; declining to "
                       f"answer does not, or saying nothing would cost less "
                       f"than saying so."),
        }]
    if klass == CONTENT_STRUCTURE_ONLY:
        return "PASS_STRUCTURE_ONLY", [{
            "block": block, "rule": "A3_NETLIST_STRUCTURE_ONLY",
            "rel_path": rel,
            "detail": ("the deck is substantive and the producer's own record "
                       "says its circuit class came from the topology library "
                       "with no bound spec value reaching any device "
                       "parameter — the netlist is real and it is the "
                       "default's, not this design's"),
        }]
    return "PASS", []


def _block_dir(project: Path, block: str) -> Path:
    """The directory whose record answers for this block's netlist, resolved
    canonical-root-first exactly as `_sidecar` resolves it."""
    path, _ = resolve_block_artefact(project, block, SIDECAR, DECLARED_PHASE)
    return path.parent


def _content_klass(project: Path, block: str) -> str:
    """WHAT this block's netlist contains, through the ONE shared rule.

    Until this call existed, this gate answered the question with a private
    `==` against a single token, which gave it a DISCLOSED tier and no
    UNDISCLOSED one — so a design-bound tree and a silent tree fell through
    together while the tree that disclosed a library default was the only one
    marked down. Measured, run verbatim as the flow runs this gate, on a
    completed benchmark tree: design-bound and silent produced a
    BYTE-IDENTICAL `--json` artefact (sha256 6c3a3a36e0d8...) and the disclosed
    tree was the only one that differed. Meanwhile `analog_one_shot_runner`
    read the SAME sidecar through the shared whitelist. Two consumers, one
    artefact, two rules."""
    return netlist_content(_block_dir(project, block)).klass


def _sidecar(project: Path, block: str) -> Optional[dict]:
    """The producer's own record beside the netlist, or None."""
    path, found = resolve_block_artefact(
        project, block, SIDECAR, DECLARED_PHASE)
    if not found:
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    prov = doc.get("_provenance") if isinstance(doc, dict) else None
    return prov if isinstance(prov, dict) else None


#: `* _provenance: topology_ir=<rel> sha256=<hex>` — the digest A3 stamps of
#: the IR it rendered. Matching it against the IR ON DISK is the only way a
#: reader can tell a current deck from one the producer has since moved past.
_IR_STAMP_RE = re.compile(
    r"_provenance:\s*topology_ir=(\S+)\s+sha256=([0-9a-f]{64})")


def _stale_vs_ir_fail(project: Path, block: str, path: Path,
                      text: str) -> Optional[dict]:
    """FAIL when the deck records an IR digest that the IR beside it no longer
    has — the deck describes a SUPERSEDED topology.

    WHY THIS IS A GATE AND NOT A NOTE. MEASURED on a real project: the checked-in
    `<block>.sp` carried 222 device cards while the `topology.json` in the SAME
    directory declared 238, because the deck was written before an emitter fix
    and the runner had not re-emitted since. Three lanes measured that deck.
    Every gate in the flow passed it, because every one of them asks whether the
    deck is WELL FORMED and none asked whether it is CURRENT. A producer fix a
    measurement cannot see is indistinguishable from no fix, so the flow has to
    be able to say which of the two it is looking at.

    The comparison is between two digests the artefacts already carry — nothing
    is re-derived, no timestamp is trusted (an mtime says when a file was
    written, not what it was written from), and a deck that records no IR stamp
    at all is left alone: this rule can only fire on a stamp that disagrees,
    never on a stamp that is absent."""
    m = _IR_STAMP_RE.search(text)
    if not m:
        return None
    rel, stamped = m.group(1), m.group(2)
    ir = project / rel
    if not ir.is_file():
        return None
    try:
        actual = hashlib.sha256(ir.read_bytes()).hexdigest()
    except OSError:
        return None
    if actual == stamped:
        return None
    return {
        "block": block, "rule": "A3_NETLIST_STALE_VS_IR",
        "rel_path": str(path.relative_to(project)),
        "detail": (f"this netlist records topology_ir sha256={stamped[:12]}… "
                   f"but {rel} is now sha256={actual[:12]}…, so the deck was "
                   f"rendered from a SUPERSEDED topology. Every measurement "
                   f"taken on it describes the older circuit. Re-run "
                   f"`analog_a3_netlist_emit` for this block."),
    }


def _provenance_ref_fail(project: Path, block: str, path: Path,
                         text: str) -> Optional[dict]:
    """The digest a report quotes must be recomputable, HERE, from THIS file.

    A digest published as proof is only proof if the reader can check it, and
    the digests this artefact used to publish could not be checked by anyone:
    they were taken over files carrying a wall-clock stamp and an absolute
    path, so they changed on every run of identical inputs and named neither
    the content nor the run. Five sibling run trees of the same inputs
    published five different digests and nothing said which tree each came
    from. `provenance_ref` names the run tree, the artefact and the content in
    one token; this rule recomputes all three and refuses a mismatch, so a
    digest quoted from a different run cannot survive a single gate run.

    Silent when the netlist carries no producer sidecar — a skill-authored
    netlist makes no such claim, and a rule that failed it would be punishing
    the absence of a claim rather than a false one."""
    prov = _sidecar(project, block)
    if prov is None or "provenance_ref" not in prov:
        return None
    rel = str(path.relative_to(project))
    problem = _pc.verify_provenance_ref(prov.get("provenance_ref"), rel, text)
    if problem is None:
        return None
    return {
        "block": block, "rule": "A3_PROVENANCE_REF_MISMATCH",
        "rel_path": rel,
        "detail": (f"{SIDECAR} publishes a provenance_ref that does not "
                   f"recompute against the artefact beside it: {problem}. A "
                   f"digest quoted as proof of a run must be reproducible "
                   f"from that run's own tree."),
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = make_argparser(GATE, __doc__)
    args = ap.parse_args(argv)
    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"error: not a directory: {project}", file=sys.stderr)
        return 2

    blocks_all = load_block_list(project)
    if blocks_all is None or (not blocks_all and not args.block):
        return vacuous_pass(GATE, args,
                            BLOCK_LIST_ABSENT_REASON)

    blocks = select_blocks(blocks_all or [], args.block)
    if not blocks:
        return vacuous_pass(GATE, args, "no blocks selected.")

    findings: List[dict] = []
    blocks_pass = 0
    missing_seen: List[dict] = []
    so_pass: List[str] = []
    design_bound: List[str] = []
    disclosures: List[dict] = []
    for block in blocks:
        status, fs = _check_block(project, block)
        if status == "PASS":
            blocks_pass += 1
            design_bound.append(block)
        elif status == "PASS_STRUCTURE_ONLY":
            # Certified, in its own tier: the block cleared every value rule,
            # and it is named separately because the deck it cleared them with
            # is a library default's. Never a FAIL — failing an honest ceiling
            # teaches the next run to stop being honest.
            blocks_pass += 1
            so_pass.append(block)
            disclosures.extend(fs)
        elif status == "MISSING":
            missing_seen.extend(fs)
        else:
            findings.extend(fs)

    # WHAT the netlists contain, read from the producer's own record THROUGH
    # THE SHARED RULE and disclosed independently of this gate's verdict — a
    # step can fail for one block and still have produced a library-default
    # deck for another, and a reader needs both facts.
    structure_only = [b for b in blocks
                      if _content_klass(project, b) == CONTENT_STRUCTURE_ONLY]
    # Same ranking as every sibling on this track: the tier reaches the VERDICT
    # WORD only when no block was certified design-bound.
    pass_token = ("PASS_STRUCTURE_ONLY"
                  if (so_pass and not design_bound) else "PASS")
    summary = {
        "blocks_checked": len(blocks),
        "blocks_pass": blocks_pass,
        "blocks_design_bound_pass": len(design_bound),
        "blocks_structure_only_pass": len(so_pass),
        "blocks_missing": len(missing_seen),
        "blocks_fail": len(findings),
        "blocks_structure_only": len(structure_only),
        "structure_only_blocks": structure_only,
    }
    if disclosures:
        summary["structure_only_findings"] = disclosures
    rc = _verdict(args, findings, missing_seen, blocks_pass, summary,
                  pass_token)
    # LAST, and on every path — see `structure_only_disclosure` for why the
    # position is part of the contract.
    structure_only_disclosure(GATE, structure_only, "<block>.sp")
    return rc


def _verdict(args, findings: List[dict], missing_seen: List[dict],
             blocks_pass: int, summary: dict,
             pass_token: str = "PASS") -> int:
    if args.block:
        if findings:
            return emit_fail(GATE, args, findings, summary)
        if missing_seen:
            return artefact_missing_for_block(
                GATE, args, args.block,
                missing_seen[0]["rel_path"], SKILL)
        return emit_pass(GATE, args, summary, pass_token=pass_token)

    if findings:
        return emit_fail(GATE, args, findings, summary)
    if missing_seen and blocks_pass == 0:
        return vacuous_pass(GATE, args,
                            f"all {len(missing_seen)} block(s) missing "
                            f"<block>.sp; defer to skill `{SKILL}`.")
    if missing_seen:
        # Mixed PASS + missing. Until v1.7.36 this fell through to
        # emit_pass, certifying A3 done on partial block coverage.
        return emit_incomplete(GATE, args, missing_seen, summary, SKILL)
    return emit_pass(GATE, args, summary, pass_token=pass_token)


if __name__ == "__main__":
    sys.exit(main())
