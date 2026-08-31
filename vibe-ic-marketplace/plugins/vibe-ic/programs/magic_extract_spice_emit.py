"""magic_extract_spice_emit.py — Magic parasitic-RC extraction: emit, validate, audit.

What this is (Bucket-B program extracted from skills/analog-extraction-resim)
=============================================================================

The `analog-extraction-resim` skill embedded a fixed Magic TCL recipe as
prose:

    load <block>
    extract all
    ext2spice lvs
    ext2spice

This recipe is the canonical post-layout *parasitic-RC* extraction used to
re-simulate an analog block (Step A7) — it loads the `.mag` LAYOUT (not a
GDS) and emits an RC-annotated SPICE netlist that is then substituted for
the ideal subcircuit in the existing testbench.

It is FULLY deterministic given (block_cell, out_spice, options) — no LLM
judgment — so per the closed-loop-enhancement-capture-doctrine it belongs
in a program, not skill prose. This mirrors `magic_port_extract_emit.py`
(which is the *different* GDS-read + port-promote recipe for LVS anchoring),
but is a distinct flow:

    magic_port_extract_emit.py  : `gds read` + `port makeall`  -> LVS port anchor
    magic_extract_spice_emit.py : `load` (.mag) + `extract all` -> parasitic-RC resim

Three entry points
==================

1. EMIT (build_extraction_tcl): generate the deterministic TCL.
2. VALIDATE (validate_extraction_tcl / CLI --validate): given an
   already-written extraction TCL, confirm it is a conformant recipe —
   every required command PRESENT **and in an order magic will honour**.
3. AUDIT (audit_extracted_netlist / CLI --audit-netlist): read the netlist
   magic actually WROTE and refuse a parasitic-free one. This is the
   emitter's trailing audit comment turned into an executable check.

Why the order is load-bearing (vibe-ic#1953)
============================================

Measured on Magic 8.3 rev 664 / sky130A (raw transcripts in the issue):

  * ``ext2spice lvs`` RESETS both thresholds to ``infinite``::

        default          cthresh=2.0        rthresh=infinite
        after `cthresh 0` cthresh=0.0       rthresh=infinite
        after `lvs`      cthresh=infinite   rthresh=infinite   <-- reset
        re-asserted      cthresh=0.0        rthresh=0

    ``cthresh=infinite`` drops EVERY capacitance. So thresholds must be
    written AFTER ``ext2spice lvs``, never before it.

  * ``ext2spice rthresh 0.0`` is a parse error —
    ``exttospice: integer value or "infinite" expected.`` — the assignment
    is refused and the old value survives. rthresh takes an INTEGER (or
    ``infinite``); cthresh does take a float.

  * ``extresist all`` reads the ``.ext`` that ``extract all`` writes. Run
    first, it has nothing to read and no ``.res.ext`` is produced at all.

  * ``extresist all`` on its own extracts nothing even in the right place:
    the extractor must be armed (``extract do resistance``), told to write
    (``extresist extout on``), and ext2spice told to splice the result in
    (``ext2spice extresist on``).

  * ``extract style ngspice`` is AMBIGUOUS on magic 8.3 ("The extraction
    styles are: ngspice(), ngspice(orig), ngspice(si), ...") and silently
    leaves the style unchanged. ``ngspice()`` is the unambiguous form.

The recipe this program used to emit had `extresist` before `extract` and
the thresholds before `lvs`, and on a two-device sky130A layout it produced
a netlist with **0 R and 0 C** — precisely the vacuous "0% post-layout
degradation" its own audit comment forbids — while ``--validate`` PASSed it,
because the validator only tested token presence, in any order.

Honest depth (measured, not assumed)
====================================

Even fully armed, magic 8.3 / sky130A emits **0 R** elements: ``.res.ext``
carries ``rnode`` node-splits and node capacitance, no ``resist`` records.
So ``audit_extracted_netlist`` refuses only the genuinely parasitic-FREE
netlist and always DISCLOSES the depth it did achieve (``RC`` / ``C_ONLY``).
A caller that genuinely needs R passes ``require_resistance=True`` and gets
an honest FAIL instead of a silent C-only substitution.

CLI
===
    # emit
    python3 magic_extract_spice_emit.py --block ldo_1v8 --out-spice ldo_1v8_extracted.spice
    python3 magic_extract_spice_emit.py --block ldo --out-spice o.spice --out extract.tcl

    # validate an existing TCL (honest FAIL on missing/garbage/mis-ordered)
    python3 magic_extract_spice_emit.py --validate extract.tcl
    python3 magic_extract_spice_emit.py --validate extract.tcl --json report.json

    # audit what magic wrote (honest FAIL on an R/C-free netlist)
    python3 magic_extract_spice_emit.py --audit-netlist ldo_extracted.spice
    python3 magic_extract_spice_emit.py --audit-netlist o.spice --res-ext o.res.ext

Exit codes:
    0 = PASS (emit succeeded; validate found a conformant recipe;
        audit found a netlist that actually carries parasitics)
    1 = FAIL (non-conformant / mis-ordered recipe, or an R/C-free netlist)
    2 = IO / usage error (missing file, empty arg, etc.)

Unit-tested in `programs/tests/test_magic_extract_spice_emit.py`.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# EMIT
# ---------------------------------------------------------------------------
@dataclass
class MagicResimExtractOptions:
    """Knobs for the parasitic-RC extraction TCL, all deterministic.

    `cthresh`: Magic `ext2spice cthresh` — capacitances below this (fF) are
        dropped. Default 0 keeps ALL of them, the conservative post-layout
        choice (no parasitic silently discarded). Takes a float.
    `rthresh`: Magic `ext2spice rthresh` — resistances below this (ohms) are
        dropped. Default 0 keeps all. **Magic requires an INTEGER here** (or
        the literal `infinite`); `ext2spice rthresh 0.0` is a parse error and
        the assignment is refused, so a non-integral value is rejected here
        rather than emitted for magic to throw away (vibe-ic#1953).
    `ext2spice_scale_off`: emit `ext2spice scale off` so device geometries
        are absolute, matching the PDK SPICE models.
    `extract_style`: argument to `extract style`. Must be an UNAMBIGUOUS
        style name — magic 8.3 rejects the bare `ngspice` as ambiguous
        against `ngspice()`, `ngspice(orig)`, `ngspice(si)`, ... and leaves
        the style unchanged. Set to None/"" to omit the command entirely.
    `extresist`: arm and run magic's separate resistance extractor. When
        True the recipe emits the FULL arming sequence — `extract do
        resistance` before the extract, `extresist extout on` +
        `extresist all` after it, and `ext2spice extresist on` before the
        write. `extresist all` alone extracts nothing.
    `extresist_threshold_mohm`: `extresist threshold` (milliohms). 0 keeps
        every net; magic's default drops all of them on a small block.
    """
    cthresh: float = 0.0
    rthresh: object = 0
    ext2spice_scale_off: bool = True
    extract_style: Optional[str] = "ngspice()"
    extresist: bool = True
    extresist_threshold_mohm: int = 0


def _rthresh_token(value: object) -> str:
    """Render `rthresh` the way magic will actually accept it.

    magic 8.3: `exttospice: integer value or "infinite" expected.` — a float
    is REFUSED and the previous value survives, so emitting `0.0` silently
    leaves rthresh at `infinite` and every resistance is dropped. Refuse a
    non-integral value here instead of shipping one magic will discard.
    """
    if isinstance(value, str):
        tok = value.strip()
        if tok.lower() == "infinite":
            return "infinite"
        try:
            value = float(tok)
        except ValueError:
            raise ValueError(
                f"rthresh must be an integer or 'infinite'; got {value!r} "
                "(magic: 'integer value or \"infinite\" expected')")
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"rthresh must be an integer or 'infinite'; got {value!r}")
    if num != num or num in (float("inf"), float("-inf")):
        raise ValueError(
            f"rthresh must be a finite integer or 'infinite'; got {value!r}")
    if num != int(num):
        raise ValueError(
            f"rthresh must be an integer or 'infinite'; got {value!r} "
            "(magic: 'integer value or \"infinite\" expected' — a float is "
            "refused and the previous threshold survives)")
    if num < 0:
        raise ValueError(f"rthresh must be >= 0; got {value!r}")
    return str(int(num))


def build_extraction_tcl(
    block_cell: str,
    out_spice: str,
    options: Optional[MagicResimExtractOptions] = None,
) -> str:
    """Generate the Magic parasitic-RC extraction TCL for post-layout resim.

    Chip-agnostic: every cell-specific token is a parameter. Returns a
    multi-line string ready to be written to a `.tcl` and fed to magic.
    Raises ValueError on an empty block_cell / out_spice, or on an rthresh
    magic would refuse (honest failure).

    THE ORDER IS THE PRODUCT. See the module docstring: `extract all` before
    `extresist all`, and `ext2spice lvs` before the threshold overrides,
    because magic resets both thresholds on `lvs`.
    """
    if not (block_cell or "").strip():
        raise ValueError("block_cell must be a non-empty cell name")
    if not (out_spice or "").strip():
        raise ValueError("out_spice must be a non-empty output path")
    opts = options or MagicResimExtractOptions()
    rthresh_tok = _rthresh_token(opts.rthresh)

    out: List[str] = []
    out.append(
        "#---------------------------------------------------------------\n"
        "# Vibe-IC plugin — Magic parasitic-RC extraction (post-layout resim)\n"
        "# Loads the .mag LAYOUT and emits an RC-annotated .subckt netlist\n"
        "# for substitution into the existing analog testbench (Step A7).\n"
        "# Generated by programs/magic_extract_spice_emit.py\n"
        "#\n"
        "# THE COMMAND ORDER BELOW IS LOAD-BEARING (vibe-ic#1953). Measured on\n"
        "# magic 8.3: `ext2spice lvs` RESETS cthresh/rthresh to `infinite`,\n"
        "# which drops every parasitic — so the thresholds are asserted AFTER\n"
        "# it. And `extresist` reads the .ext that `extract all` writes, so it\n"
        "# runs AFTER the extract. Reordering this produces an R/C-free\n"
        "# netlist and a false 0% post-layout degradation.\n"
        "#---------------------------------------------------------------"
    )
    out.append(f"load {block_cell}")
    out.append("select top cell")
    if (opts.extract_style or "").strip():
        # A bare `ngspice` is AMBIGUOUS on magic 8.3 and leaves the style
        # unchanged; `ngspice()` is the resolved name.
        out.append(f"extract style {opts.extract_style.strip()}")
    if opts.extresist:
        # Arm resistance extraction BEFORE the extract that has to do it.
        out.append("extract do resistance")
    # `extract all` writes the .ext everything downstream reads.
    out.append("extract all")
    if opts.extresist:
        # ...only now does extresist have something to work on.
        out.append("extresist extout on")
        out.append(f"extresist threshold {int(opts.extresist_threshold_mohm)}")
        out.append("extresist all")
    if opts.ext2spice_scale_off:
        out.append("ext2spice scale off")
    # `ext2spice lvs` wraps the netlist in a .subckt with the block's ports
    # (the resim binds to it) — AND resets cthresh/rthresh to `infinite`.
    # Everything threshold-related must therefore come after it.
    out.append("ext2spice lvs")
    out.append(f"ext2spice cthresh {opts.cthresh}")
    out.append(f"ext2spice rthresh {rthresh_tok}")
    if opts.extresist:
        out.append("ext2spice extresist on")
    out.append(f"ext2spice -o {out_spice}")
    out.append(
        "# Audit: the emitted file MUST contain a non-empty `.subckt {blk}`\n"
        "# with R/C parasitic elements; an R/C-free netlist means the\n"
        "# parasitics were dropped -> the resim would falsely show 0%\n"
        "# degradation. This comment is executable — run:\n"
        "#   magic_extract_spice_emit.py --audit-netlist {out}"
        .replace("{blk}", block_cell).replace("{out}", out_spice)
    )
    out.append(f"puts stdout \"MAGIC_EXTRACT_RESIM_DONE {block_cell} -> {out_spice}\"")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# VALIDATE
# ---------------------------------------------------------------------------
# The commands the parasitic-RC resim recipe REQUIRES, each with the silicon
# reason it is mandatory. A validated TCL must contain every one of these.
# The keys are `_scan_commands` kinds — the matching is structural, not by
# regex, because `ext2spice <word>` means different things depending on
# whether <word> is one of magic's subcommands.
_REQUIRED = [
    ("load",
     "load the .mag layout cell (the source of the parasitics)"),
    ("extract_all",
     "extract all — without it the netlist carries NO R/C parasitics "
     "(vacuous 0% post-layout degradation)"),
    ("ext2spice_lvs",
     "ext2spice lvs — wraps the netlist in a .subckt with ports so the "
     "resim testbench can bind the block (else the ideal subckt runs)"),
    ("ext2spice_out",
     "a bare ext2spice (or ext2spice -o) to actually WRITE the netlist"),
]

# magic 8.3's `ext2spice` SUBCOMMANDS, measured by probing the binary. This
# set is load-bearing for parsing: `ext2spice <anything-else>` is magic's
# WRITE form (it reads the word as a cell name — `ext2spice zzz` answers
# "Cannot read extract file zzz.ext"). Without the set, `ext2spice extresist
# on` misreads as a write and every order rule fires on a correct recipe.
_EXT2SPICE_SUBCOMMANDS = frozenset({
    "blackbox", "cthresh", "default", "extresist", "format", "global",
    "help", "hierarchy", "lvs", "merge", "renumber", "resistor", "rthresh",
    "scale", "short", "subcircuit",
})


@dataclass
class Command:
    """One uncommented magic command line, with its position."""
    index: int          # 0-based line index
    kind: str           # normalised kind, e.g. "ext2spice_lvs"
    args: List[str]
    raw: str


def _scan_commands(lines: List[str]) -> List[Command]:
    """Normalise the TCL into the ordered command stream the rules read.

    Comments are stripped first (a required command that appears only in a
    comment must not satisfy anything).
    """
    cmds: List[Command] = []
    for i, ln in enumerate(lines):
        body = ln.split("#", 1)[0].strip()
        if not body:
            continue
        toks = body.split()
        head = toks[0].lower()
        rest = toks[1:]
        sub = rest[0].lower() if rest else ""
        kind = None
        if head == "load":
            kind = "load"
        elif head == "extract":
            if sub == "all":
                kind = "extract_all"
            elif sub == "style":
                kind = "extract_style"
            elif sub == "do" and len(rest) > 1 and rest[1].lower() in (
                    "resistance", "extresist", "all"):
                kind = "extract_do_resistance"
        elif head == "extresist":
            if sub == "all":
                kind = "extresist_all"
            elif sub:
                kind = "extresist_option"
        elif head == "ext2spice":
            if not rest or rest[0].startswith("-"):
                kind = "ext2spice_out"
            elif sub in _EXT2SPICE_SUBCOMMANDS:
                kind = f"ext2spice_{sub}"
            else:
                # unknown word == cell name == magic's write form
                kind = "ext2spice_out"
        if kind:
            cmds.append(Command(index=i, kind=kind, args=rest, raw=body))
    return cmds


@dataclass
class Finding:
    rule: str
    severity: str
    message: str


@dataclass
class ValidateResult:
    program: str = "magic_extract_spice_emit"
    version: str = "2.0.0"
    mode: str = "validate"
    passed: bool = False
    tcl_file: str = ""
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def _first(cmds: List[Command], kind: str) -> Optional[Command]:
    for c in cmds:
        if c.kind == kind:
            return c
    return None


def _last(cmds: List[Command], kind: str) -> Optional[Command]:
    found = None
    for c in cmds:
        if c.kind == kind:
            found = c
    return found


def validate_extraction_tcl(text: str, tcl_file: str = "") -> ValidateResult:
    """Validate that `text` is a conformant parasitic-RC extraction recipe.

    PRESENCE is necessary but not sufficient. The recipe this program used
    to emit contained every required token and still produced a netlist with
    zero parasitics, because magic's state machine cares about ORDER:

      * `ext2spice lvs` resets cthresh/rthresh to `infinite` (all parasitics
        dropped), so a threshold set BEFORE it is thrown away;
      * `extresist` reads the .ext that `extract all` writes, so run first it
        reads nothing;
      * `ext2spice rthresh <float>` is a parse error — the assignment is
        refused and the old threshold survives.

    Honest failure semantics:
      - empty / whitespace-only text  -> FAIL (EMPTY_TCL)
      - text with none of the required commands -> FAIL (NOT_AN_EXTRACTION_TCL)
      - any single required command missing -> FAIL (MISSING_<cmd>)
      - a required command in an order magic will not honour -> FAIL (ORDER_*)
      - an rthresh magic will refuse -> FAIL (RTHRESH_NOT_INTEGER)
    A vacuous PASS is impossible: PASS requires ALL required commands present
    AND an order that actually delivers parasitics.
    """
    result = ValidateResult(tcl_file=tcl_file)

    if not (text or "").strip():
        result.passed = False
        result.findings.append(Finding(
            "EMPTY_TCL", "ERROR",
            "extraction TCL is empty/whitespace — nothing to extract"))
        result.summary = {"present": [], "missing": [k for k, _ in _REQUIRED],
                          "order_errors": []}
        return result

    lines = text.splitlines()
    cmds = _scan_commands(lines)
    kinds = {c.kind for c in cmds}

    present: List[str] = []
    missing: List[str] = []
    for key, reason in _REQUIRED:
        if key in kinds:
            present.append(key)
        else:
            missing.append(key)
            result.findings.append(Finding(
                f"MISSING_{key.upper()}", "ERROR",
                f"required command missing: {reason}"))

    # If NOTHING matched, this isn't an extraction TCL at all — distinct
    # ERROR so a caller can tell "wrong file" from "incomplete recipe".
    if not present:
        result.findings = [Finding(
            "NOT_AN_EXTRACTION_TCL", "ERROR",
            "no Magic extraction commands found — not a parasitic-RC "
            "extraction recipe")]
        result.passed = False
        result.summary = {"present": [], "missing": missing, "order_errors": []}
        return result

    order_errors = _order_findings(cmds)
    result.findings.extend(order_errors)

    result.passed = not missing and not order_errors
    if result.passed:
        result.findings.append(Finding(
            "EXTRACTION_RECIPE_OK", "INFO",
            "all required parasitic-RC extraction commands present, in an "
            "order magic will honour"))
    result.summary = {
        "present": present,
        "missing": missing,
        "order_errors": [f.rule for f in order_errors],
    }
    return result


def _order_findings(cmds: List[Command]) -> List[Finding]:
    """The ORDER rules — each one a measured magic behaviour, not a style.

    Every rule below fires only when the evidence for the defect is in the
    file; a recipe that never sets a threshold, or never runs extresist, is
    not penalised for it.
    """
    out: List[Finding] = []

    extract_all = _first(cmds, "extract_all")
    last_extract_all = _last(cmds, "extract_all")
    extresist_all = _first(cmds, "extresist_all")
    lvs = _last(cmds, "ext2spice_lvs")
    write = _first(cmds, "ext2spice_out")

    # 1. extresist before extract: nothing to read, no .res.ext written.
    if extresist_all is not None and extract_all is not None:
        if extresist_all.index < extract_all.index:
            out.append(Finding(
                "ORDER_EXTRESIST_BEFORE_EXTRACT", "ERROR",
                f"`{extresist_all.raw}` (line {extresist_all.index + 1}) runs "
                f"before `{extract_all.raw}` (line {extract_all.index + 1}); "
                "extresist reads the .ext that `extract all` writes, so it "
                "reads nothing and no .res.ext is produced"))

    # 2. a threshold set before `ext2spice lvs` and never re-asserted after:
    #    magic resets both to `infinite` on lvs, dropping every parasitic.
    if lvs is not None:
        for sub, unit in (("cthresh", "capacitance"), ("rthresh", "resistance")):
            kind = f"ext2spice_{sub}"
            sets = [c for c in cmds if kind == c.kind and len(c.args) > 1]
            if not sets:
                continue
            before = [c for c in sets if c.index < lvs.index]
            after = [c for c in sets if c.index > lvs.index]
            if before and not after:
                out.append(Finding(
                    "ORDER_THRESHOLD_BEFORE_LVS", "ERROR",
                    f"`{before[-1].raw}` (line {before[-1].index + 1}) is set "
                    f"before `{lvs.raw}` (line {lvs.index + 1}) and never "
                    f"re-asserted after it; magic RESETS {sub} to `infinite` "
                    f"on `ext2spice lvs`, so every {unit} is dropped and the "
                    "resim shows a false 0% degradation"))

    # 3. `ext2spice lvs` after the write: the file is already on disk.
    if lvs is not None and write is not None and lvs.index > write.index:
        out.append(Finding(
            "ORDER_LVS_AFTER_WRITE", "ERROR",
            f"`{lvs.raw}` (line {lvs.index + 1}) comes after the write "
            f"`{write.raw}` (line {write.index + 1}); the netlist was already "
            "emitted without the .subckt port wrapper"))

    # 4. the extract after the write: the write read a stale/absent .ext.
    if write is not None and last_extract_all is not None \
            and last_extract_all.index > write.index:
        out.append(Finding(
            "ORDER_EXTRACT_AFTER_WRITE", "ERROR",
            f"`{last_extract_all.raw}` (line {last_extract_all.index + 1}) "
            f"comes after the write `{write.raw}` "
            f"(line {write.index + 1}); the netlist was emitted from a stale "
            "or absent .ext"))

    # 5. `load` after the extract: nothing was loaded to extract.
    load = _first(cmds, "load")
    if load is not None and extract_all is not None \
            and load.index > extract_all.index:
        out.append(Finding(
            "ORDER_LOAD_AFTER_EXTRACT", "ERROR",
            f"`{load.raw}` (line {load.index + 1}) comes after "
            f"`{extract_all.raw}` (line {extract_all.index + 1})"))

    # 6. rthresh magic will refuse outright.
    for c in cmds:
        if c.kind == "ext2spice_rthresh" and len(c.args) > 1:
            val = c.args[1]
            if val.lower() == "infinite":
                continue
            try:
                num = float(val)
                integral = num == int(num)
            except ValueError:
                integral = False
            if not integral or "." in val or "e" in val.lower():
                out.append(Finding(
                    "RTHRESH_NOT_INTEGER", "ERROR",
                    f"`{c.raw}` (line {c.index + 1}): magic answers "
                    "'exttospice: integer value or \"infinite\" expected' and "
                    "REFUSES the assignment, leaving the previous threshold "
                    "(default `infinite`) in force — every resistance dropped"))

    return out


# ---------------------------------------------------------------------------
# AUDIT — the emitter's trailing audit comment, made executable
# ---------------------------------------------------------------------------
#: A netlist element line: a device letter in column 1, then a name. SPICE
#: continuation lines (`+`), comments (`*`) and directives (`.`) are not
#: elements.
_R_ELEMENT = re.compile(r"^[Rr]\S*\s+\S+\s+\S+")
_C_ELEMENT = re.compile(r"^[Cc]\S*\s+\S+\s+\S+")
_SUBCKT = re.compile(r"^\s*\.subckt\s+(\S+)(.*)$", re.IGNORECASE)


@dataclass
class AuditResult:
    program: str = "magic_extract_spice_emit"
    version: str = "2.0.0"
    mode: str = "audit"
    passed: bool = False
    spice_file: str = ""
    res_ext_file: str = ""
    #: achieved parasitic depth — "RC" | "C_ONLY" | "R_ONLY" | "NONE".
    #: Never inferred from the recipe; always counted off the netlist.
    depth: str = "NONE"
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def _count_elements(text: str) -> tuple:
    """Count R and C elements and collect .subckt names, ignoring comments."""
    resistors = capacitors = 0
    subckts: List[str] = []
    for ln in text.splitlines():
        stripped = ln.rstrip()
        if not stripped or stripped.lstrip().startswith("*"):
            continue
        m = _SUBCKT.match(stripped)
        if m:
            subckts.append(m.group(1))
            continue
        if stripped.lstrip().startswith(("+", ".")):
            continue
        if _R_ELEMENT.match(stripped):
            resistors += 1
        elif _C_ELEMENT.match(stripped):
            capacitors += 1
    return resistors, capacitors, subckts


def _count_res_ext_records(text: Optional[str]) -> int:
    """Records in a magic `.res.ext` past the `scale` header.

    A `.res.ext` that is only its header — the shape `extresist all` leaves
    when it had nothing to work on — has zero records.
    """
    if not text:
        return 0
    n = 0
    for ln in text.splitlines():
        body = ln.strip()
        if not body or body.startswith("#"):
            continue
        if body.split()[0].lower() == "scale":
            continue
        n += 1
    return n


def audit_extracted_netlist(
    spice_text: str,
    res_ext_text: Optional[str] = None,
    spice_file: str = "",
    res_ext_file: str = "",
    require_resistance: bool = False,
    extresist_expected: bool = False,
) -> AuditResult:
    """Refuse a parasitic-free extracted netlist. Disclose the depth achieved.

    This is the emitter's trailing audit comment as an executable check. It
    reads what magic WROTE, not what we asked magic to do — the whole reason
    vibe-ic#1953 survived is that nothing ever read the output.

    The bar is deliberately the one the comment states and no higher: a
    netlist with **no R and no C** is refused, because a re-simulation of it
    is a re-simulation of the pre-layout circuit and reports a false 0%
    degradation. R specifically is NOT required by default — measured, magic
    8.3 / sky130A yields 0 R even with resistance extraction fully armed — so
    demanding it would red every honest run. Instead the achieved depth is
    always reported, and a caller that genuinely needs R asks for it with
    `require_resistance=True` and gets an honest FAIL.

    `extresist_expected` says the recipe ran `extresist`, so an absent or
    header-only `.res.ext` is worth reporting even when `res_ext_text` is
    None (the broken recipe did not create the file at all).
    """
    result = AuditResult(spice_file=spice_file, res_ext_file=res_ext_file)

    if not (spice_text or "").strip():
        result.findings.append(Finding(
            "EMPTY_NETLIST", "ERROR",
            "the extracted netlist is empty — magic wrote nothing, so there "
            "is no post-layout circuit to re-simulate"))
        result.summary = {"resistors": 0, "capacitors": 0, "subckts": [],
                          "res_ext_records": 0}
        result.depth = "NONE"
        result.passed = False
        return result

    resistors, capacitors, subckts = _count_elements(spice_text)
    res_records = _count_res_ext_records(res_ext_text)

    if resistors and capacitors:
        result.depth = "RC"
    elif capacitors:
        result.depth = "C_ONLY"
    elif resistors:
        result.depth = "R_ONLY"
    else:
        result.depth = "NONE"

    if not subckts:
        result.findings.append(Finding(
            "NO_SUBCKT", "ERROR",
            "no `.subckt` wrapper in the extracted netlist — `ext2spice lvs` "
            "did not take, so the resim testbench cannot bind the extracted "
            "block and would silently run the ideal one"))

    if result.depth == "NONE":
        result.findings.append(Finding(
            "NO_PARASITICS", "ERROR",
            "the extracted netlist carries 0 resistors and 0 capacitors — "
            "re-simulating it re-simulates the PRE-layout circuit and reports "
            "a false 0% post-layout degradation. Check the recipe order: "
            "`ext2spice lvs` resets cthresh/rthresh to `infinite`, so the "
            "thresholds must be asserted after it"))
    elif result.depth == "C_ONLY":
        sev = "ERROR" if require_resistance else "WARNING"
        rule = ("RESISTANCE_REQUIRED_BUT_ABSENT" if require_resistance
                else "PARASITIC_DEPTH_C_ONLY")
        result.findings.append(Finding(
            rule, sev,
            f"{capacitors} capacitors and 0 resistors — the extraction reached "
            "CAPACITANCE ONLY. Any post-layout number derived from it carries "
            "no IR / series-R effect and must say so."))
    elif result.depth == "R_ONLY":
        result.findings.append(Finding(
            "PARASITIC_DEPTH_R_ONLY", "WARNING",
            f"{resistors} resistors and 0 capacitors — no capacitive loading "
            "in the post-layout numbers."))

    if res_ext_text is not None or extresist_expected or require_resistance:
        if res_records == 0:
            sev = "ERROR" if require_resistance else "WARNING"
            result.findings.append(Finding(
                "EXTRESIST_PRODUCED_NOTHING", sev,
                "the resistance extractor produced no records "
                + ("(no .res.ext was written at all)" if res_ext_text is None
                   else "(.res.ext holds only its `scale` header)")
                + " — `extresist all` must run AFTER `extract all`, with "
                  "`extract do resistance` and `extresist extout on` armed"))

    if not any(f.severity == "ERROR" for f in result.findings):
        result.findings.append(Finding(
            "EXTRACTED_NETLIST_OK", "INFO",
            f"the extracted netlist carries parasitics (depth={result.depth}, "
            f"R={resistors}, C={capacitors})"))

    result.passed = not any(f.severity == "ERROR" for f in result.findings)
    result.summary = {
        "resistors": resistors,
        "capacitors": capacitors,
        "subckts": subckts,
        "res_ext_records": res_records,
    }
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list = None) -> int:
    p = argparse.ArgumentParser(
        description="Emit, validate OR audit a Magic parasitic-RC extraction "
                    "(deterministic, chip-agnostic).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--validate", metavar="TCL", default=None,
                   help="Validate an existing extraction TCL instead of emitting")
    p.add_argument("--audit-netlist", metavar="SPICE", default=None,
                   help="Audit the netlist magic WROTE: refuse an R/C-free one "
                        "and disclose the parasitic depth achieved")
    p.add_argument("--res-ext", metavar="RES_EXT", default=None,
                   help="Companion .res.ext to read in --audit-netlist mode")
    p.add_argument("--require-resistance", action="store_true",
                   help="Audit mode: treat a capacitance-only extraction as a "
                        "FAILURE (default: pass, but disclose the depth)")
    p.add_argument("--block", default=None, help="Block/cell name (emit mode)")
    p.add_argument("--out-spice", default=None,
                   help="Output SPICE path written by the emitted TCL (emit mode)")
    p.add_argument("--cthresh", type=float, default=0.0)
    p.add_argument("--rthresh", default="0",
                   help="ext2spice rthresh — an INTEGER or 'infinite' "
                        "(magic refuses a float)")
    p.add_argument("--no-scale-off", action="store_true")
    p.add_argument("--extract-style", default="ngspice()",
                   help="argument to `extract style`; empty to omit the command")
    p.add_argument("--no-extresist", action="store_true",
                   help="Do not arm/run magic's resistance extractor "
                        "(capacitance-only extraction, honestly declared)")
    p.add_argument("--out", type=Path, default=None,
                   help="Write the emitted TCL here; default stdout (emit mode)")
    p.add_argument("--json", default=None,
                   help="JSON report path (validate / audit mode)")
    args = p.parse_args(argv)

    # ----- AUDIT MODE -----
    if args.audit_netlist is not None:
        sp = Path(args.audit_netlist)
        if not sp.is_file():
            print(f"ERROR: {sp} is not a file", file=sys.stderr)
            return 2
        try:
            spice_text = sp.read_text(errors="replace")
        except OSError as e:
            print(f"ERROR: cannot read {sp}: {e}", file=sys.stderr)
            return 2
        res_text = None
        res_name = ""
        if args.res_ext is not None:
            rp = Path(args.res_ext)
            if not rp.is_file():
                print(f"ERROR: {rp} is not a file", file=sys.stderr)
                return 2
            try:
                res_text = rp.read_text(errors="replace")
            except OSError as e:
                print(f"ERROR: cannot read {rp}: {e}", file=sys.stderr)
                return 2
            res_name = str(rp)
        audit = audit_extracted_netlist(
            spice_text, res_ext_text=res_text, spice_file=str(sp),
            res_ext_file=res_name,
            require_resistance=args.require_resistance,
        )
        out = json.dumps(asdict(audit), indent=2, ensure_ascii=False)
        if args.json:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(out)
        else:
            status = "PASS" if audit.passed else "FAIL"
            print(f"[{status}] magic_extract_spice_emit --audit-netlist {sp} "
                  f"(depth={audit.depth}, R={audit.summary['resistors']}, "
                  f"C={audit.summary['capacitors']})")
            for f in audit.findings:
                if f.severity in ("ERROR", "WARNING"):
                    print(f"  [{f.severity}] {f.rule}: {f.message}")
        return 0 if audit.passed else 1

    # ----- VALIDATE MODE -----
    if args.validate is not None:
        tcl_path = Path(args.validate)
        if not tcl_path.is_file():
            print(f"ERROR: {tcl_path} is not a file", file=sys.stderr)
            return 2
        try:
            text = tcl_path.read_text(errors="replace")
        except OSError as e:
            print(f"ERROR: cannot read {tcl_path}: {e}", file=sys.stderr)
            return 2
        result = validate_extraction_tcl(text, str(tcl_path))
        out = json.dumps(asdict(result), indent=2, ensure_ascii=False)
        if args.json:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(out)
        else:
            status = "PASS" if result.passed else "FAIL"
            print(f"[{status}] magic_extract_spice_emit --validate {tcl_path}")
            for f in result.findings:
                if f.severity in ("ERROR", "WARNING"):
                    print(f"  [{f.severity}] {f.rule}: {f.message}")
        return 0 if result.passed else 1

    # ----- EMIT MODE -----
    if not args.block or not args.out_spice:
        print("ERROR: emit mode requires --block and --out-spice "
              "(or use --validate <tcl> / --audit-netlist <spice>)",
              file=sys.stderr)
        return 2
    opts = MagicResimExtractOptions(
        cthresh=args.cthresh,
        rthresh=args.rthresh,
        ext2spice_scale_off=not args.no_scale_off,
        extract_style=args.extract_style,
        extresist=not args.no_extresist,
    )
    try:
        tcl = build_extraction_tcl(args.block, args.out_spice, opts)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    if args.out:
        args.out.write_text(tcl, encoding="utf-8")
        print(f"wrote: {args.out}", file=sys.stderr)
    else:
        print(tcl, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
