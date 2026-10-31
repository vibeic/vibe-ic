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



def _d47_inputs(project):
    """Candidate inputs only: no later stream-out record or D60 helper."""
    import hashlib
    import math
    import analog_pdk_availability as resolver
    import analog_a7_post_layout_emit as a7
    from analog_hardmacro_gds_emit import tech_of, _MAG_USE_RE
    from flow109_analog_floorplan import bound_file
    from declared_pdk_is_the_pdk_used_check import declared_target
    project = Path(project).resolve(strict=True)
    records = {}
    def remember(path):
        path = Path(path)
        if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
            raise ValueError('D47_INPUT_ABSENT_OR_SYMLINK: ' + str(path))
        records[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        return path
    config_path = remember(project / 'input/flow109/D47.json')
    config = json.loads(config_path.read_text())
    if not isinstance(config, dict):
        raise ValueError('D47_INPUT_INVALID')
    layout = remember(bound_file(project, config.get('layout')))
    logical = remember(bound_file(project, config.get('logical_netlist')))
    top = config.get('top')
    if not isinstance(top, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]*', top) or layout.stem != top:
        raise ValueError('D47_CANDIDATE_TOP_INVALID')
    if _count_elements(logical.read_text())[2].count(top) != 1:
        raise ValueError('D47_LOGICAL_TOP_ABSENT_OR_AMBIGUOUS')
    ports = a7.subckt_ports(logical.read_text(), top)
    if ports is None:
        raise ValueError('D47_LOGICAL_INTERFACE_ABSENT')
    options = config.get('options')
    if not isinstance(options, dict) or set(options) != set(MagicResimExtractOptions.__dataclass_fields__):
        raise ValueError('D47_EXTRACTION_SETTINGS_ABSENT')
    if (type(options['cthresh']) not in (int, float) or not math.isfinite(options['cthresh'])
            or options['cthresh'] < 0 or type(options['extresist_threshold_mohm']) is not int
            or options['extresist_threshold_mohm'] < 0
            or any(type(options[k]) is not bool for k in ('extresist', 'ext2spice_scale_off'))
            or type(config.get('require_resistance')) is not bool):
        raise ValueError('D47_EXTRACTION_SETTINGS_INVALID')
    _rthresh_token(options['rthresh'])
    tech = tech_of(layout)
    target, target_source = declared_target(project)
    if not isinstance(target_source, str):
        raise ValueError('D47_PDK_DECLARATION_SOURCE_ABSENT')
    relative = Path(target_source.rsplit(':', 1)[0])
    declarations = [base / relative for base in (project, project / 'run')
                    if (base / relative).is_file()]
    if not declarations:
        raise ValueError('D47_PDK_DECLARATION_SOURCE_UNBOUND')
    for declaration in declarations:
        remember(declaration)
    if resolver.families_agree(target, tech) is not True:
        raise ValueError('D47_DECLARED_TECHNOLOGY_MISMATCH')
    facts = resolver.resolve_pdk(target, project=project)
    if facts.get('source') != 'container_installed' or not facts.get('available'):
        raise ValueError('D47_INSTALLED_TECHNOLOGY_UNAVAILABLE')
    directory = (Path(facts['pdk_root']) / 'libs.tech/magic').resolve(strict=True)
    rcfile, techfile = directory / (tech + '.magicrc'), directory / (tech + '.tech')
    remember(rcfile); remember(techfile)
    styles = a7.extraction_styles(techfile)
    if options['extract_style'] not in styles:
        raise ValueError('D47_STYLE_NOT_DECLARED_BY_TECHNOLOGY')
    total = 0
    technology_files = sorted(directory.rglob('*'))
    for path in technology_files:
        if path.is_symlink():
            raise ValueError('D47_TECHNOLOGY_SYMLINK')
        if path.is_file():
            total += path.stat().st_size
            remember(path)
    if len(technology_files) > 512 or total > 67108864:
        raise ValueError('D47_TECHNOLOGY_POPULATION_UNSUPPORTED')
    cells = {}
    pending = [layout]
    while pending:
        path = pending.pop()
        if path.stem in cells:
            continue
        if len(cells) >= 512:
            raise ValueError('D47_CANDIDATE_HIERARCHY_UNSUPPORTED')
        remember(path)
        if tech_of(path) != tech:
            raise ValueError('D47_CHILD_TECHNOLOGY_MISMATCH')
        cells[path.stem] = str(path)
        for cell in _MAG_USE_RE.findall(path.read_text()):
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]*', cell):
                raise ValueError('D47_CHILD_IDENTITY_UNSUPPORTED')
            child = layout.parent / (cell + '.mag')
            if not child.is_file():
                raise ValueError('D47_REQUIRED_CHILD_ABSENT: ' + cell)
            pending.append(child)
    return dict(top=top, ports=ports, logical=str(logical), cells=cells,
                options=options, require_resistance=config['require_resistance'],
                rcfile=str(rcfile), tech=tech, pdk_root=str(Path(facts['pdk_root']).parent),
                summed_models=sorted(a7.summed_device_models(a7._tech_text(techfile))), inputs=records)


def _d47_audit(data, spice, res_ext):
    """Use the existing output audit, port and device consumers on real bytes."""
    import analog_a7_post_layout_emit as a7
    text = spice.read_text() if spice.is_file() else ''
    audit = audit_extracted_netlist(text,
        res_ext.read_text() if res_ext.is_file() else None,
        spice_file=str(spice), res_ext_file=str(res_ext),
        require_resistance=data['require_resistance'],
        extresist_expected=data['options']['extresist'])
    if (not audit.passed or audit.summary['subckts'].count(data['top']) != 1
            or a7.subckt_ports(text, data['top']) != data['ports']):
        return {'status': 'FAIL', 'reason': 'D47_NATIVE_PARASITIC_OR_INTERFACE_AUDIT_FAILED', 'audit': asdict(audit)}
    inventory = a7.device_inventory(
        a7.device_instances(Path(data['logical']).read_text(), data['top']),
        a7.device_instances(text, data['top']), set(data['summed_models']))
    return {'status': 'PASS' if inventory['result'] == 'MATCH' else 'FAIL',
            'reason': 'D47_NATIVE_EXTRACTION_AUDITED' if inventory['result'] == 'MATCH' else 'D47_SOURCE_DEVICE_INVENTORY_MISMATCH',
            'audit': asdict(audit), 'device_inventory': inventory,
            'inventory_scope': 'existing A7 top-level external X-model inventory, not LVS or complete net coverage'}


def execute(project, context):
    """D47 native candidate extraction; actual depth never implies row PASS."""
    import hashlib
    import shlex
    import shutil
    import uuid
    import librelane_contract as launch
    from analog_hardmacro_gds_emit import Stage
    from flow109_admission import require_launch_admission, AdmissionRefusal
    project = Path(project).resolve(strict=True)
    output = project / 'reports/flow109/D47' / uuid.uuid4().hex
    output.mkdir(parents=True)
    record = dict(step_id='D47', context_sha256=context.get('context_sha256'),
                  component_status='NOT_MEASURED', default_row_status='NOT_MEASURED',
                  completed=False, native_started=False, outputs=[], executions=[],
                  flow109_acceptance='NOT_MEASURED', whole_flow_acceptance='NOT_MEASURED',
                  delivery_accepted=False, qualification='NOT_CLAIMED')
    stage = Stage('host', output / 'work')
    try:
        if (context.get('requested_step') != 'D47' or context.get('native_step_id') != 'flow109.D47'
                or context.get('resolved_row', {}).get('profile', {}).get('id') != 'analog_die'):
            raise ValueError('D47_CONTEXT_INVALID')
        record['launch_admission'] = require_launch_admission(project, 'flow109.D47', {'flow109_context': context})
        record['native_launch'] = launch.local_image_attestation()
        data = _d47_inputs(project)
        record['inputs'] = data['inputs']
        record['metric_sources'] = _d47_metric_sources()
        record['settings'] = data['options']
        record['require_resistance'] = data['require_resistance']
        tool = shutil.which('magic')
        if not tool:
            raise ValueError('D47_MAGIC_UNAVAILABLE')
        record['tool'] = {'path': tool, 'sha256': hashlib.sha256(Path(tool).resolve().read_bytes()).hexdigest()}
        if not stage.open()[0]:
            raise ValueError('D47_STAGING_UNAVAILABLE')
        for name, path in data['cells'].items():
            if not stage.put(Path(path), name + '.mag')[0]:
                raise ValueError('D47_STAGING_FAILED')
        recipe = build_extraction_tcl(data['top'], 'candidate.spice', MagicResimExtractOptions(**data['options'])) + 'quit -noprompt\n'
        validation = validate_extraction_tcl(recipe)
        record['recipe_validation'] = asdict(validation)
        if not validation.passed or not stage.put_text(recipe, 'extract.tcl')[0]:
            raise ValueError('D47_EXTRACTION_RECIPE_REFUSED')
        command = (f"export PDK={shlex.quote(data['tech'])} PDK_ROOT={shlex.quote(data['pdk_root'])} && "
                   f"cd {shlex.quote(stage.path)} && {shlex.quote(tool)} -noconsole -dnull "
                   f"-rcfile {shlex.quote(data['rcfile'])} extract.tcl")
        record['native_started'] = True
        rc, stdout, stderr = stage.sh(command)
        log = output / 'magic.log'; log.write_text(stdout + stderr)
        record['executions'].append(dict(command=command, returncode=rc,
            log=str(log.relative_to(project)), log_sha256=hashlib.sha256(log.read_bytes()).hexdigest()))
        spice = Path(stage.path) / 'candidate.spice'
        res_ext = Path(stage.path) / (data['top'] + '.res.ext')
        if (rc or 'MAGIC_EXTRACT_RESIM_DONE ' + data['top'] + ' ->' not in stdout
                or re.search(r'(?im)(?:unknown|unrecognized)\s+layer|failure to read|error in writing', stdout + stderr)):
            record['component_status'] = 'FAIL'
            raise ValueError('D47_NATIVE_EXTRACTION_REJECTED')
        extracted_sha = hashlib.sha256(spice.read_bytes()).hexdigest() if spice.is_file() else None
        companions = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(stage.path).glob('*.ext')}
        answer = _d47_audit(data, spice, res_ext)
        record['measurements'] = answer
        audit_path = output / 'audit.json'; audit_path.write_text(json.dumps(answer, indent=2) + '\n')
        if answer['status'] != 'PASS':
            record['component_status'] = 'FAIL'
            raise ValueError(answer['reason'])
        if (_d47_inputs(project) != data or _d47_audit(data, spice, res_ext) != answer
                or hashlib.sha256(spice.read_bytes()).hexdigest() != extracted_sha
                or any(not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != h for p, h in companions.items())
                or launch.local_image_attestation() != record['native_launch']):
            raise ValueError('D47_INPUT_OUTPUT_OR_LAUNCH_CHANGED')
        record['component_status'] = 'PASS'
        record['extraction_depth'] = answer['audit']['depth']
        record['settings'] = data['options']
        record['require_resistance'] = data['require_resistance']
        record['outputs'] = [{'path': str(p.relative_to(project)), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                             for p in (spice, audit_path, Path(stage.path) / 'extract.tcl', *companions)]
        record['reason'] = 'Native candidate extraction depth=' + record['extraction_depth'] + '; coverage, RC corner, SI and row/signoff acceptance unmeasured'
    except (ValueError, OSError, KeyError, TypeError, AdmissionRefusal, launch.Refusal) as exc:
        record['reason'] = str(exc)
    finally:
        stage.close()
    (output / 'component.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


def _d47_metric_sources():
    """Current candidate extraction, native audit and device/interface readers."""
    import hashlib
    here = Path(__file__).resolve().parent
    return {name: hashlib.sha256((here / name).read_bytes()).hexdigest()
            for name in ('magic_extract_spice_emit.py', 'analog_a7_post_layout_emit.py',
                'analog_hardmacro_gds_emit.py', 'declared_pdk_is_the_pdk_used_check.py',
                'analog_pdk_availability.py', 'analog_lvs_comparison_prep.py')}


def _d47_metric_values(data, spice, res_ext):
    """Re-run the existing native-output audit; expose its exact measured depth.

    The existing top-level external-device inventory is useful evidence. It
    cannot stand for a complete net/corner or SI-applicability population.
    """
    result = _d47_audit(data, spice, res_ext)
    return {'status': result['status'], 'reason': result['reason'],
            'audit': result['audit'], 'device_inventory': result.get('device_inventory'),
            'extraction_depth': result['audit']['depth'],
            'required_logical_ports': list(data['ports']),
            'required_nets_and_corners': None, 'si_applicability': 'NOT_MEASURED',
            'inventory_scope': result.get('inventory_scope', 'native parasitic/interface audit only')}


def _d47_metric_observation(project, context, component):
    """Consume a normal candidate extraction; never rerun Magic or upgrade C_ONLY."""
    import hashlib
    import shlex
    import flow109
    from flow109_analog_floorplan import bound_file
    current = flow109.validate_execution_context(context)
    if (current['requested_step'] != 'D47' or current['resolved_row']['profile']['id'] != 'analog_die'
            or component.get('step_id') != 'D47' or
            component.get('context_sha256') != current['context_sha256']):
        raise ValueError('D47_METRIC_CONTEXT_MISMATCH')
    if component.get('metric_sources') != _d47_metric_sources():
        raise ValueError('D47_METRIC_SOURCE_CHANGED_OR_UNRECORDED')
    data = _d47_inputs(project)
    if (component.get('inputs') != data['inputs'] or component.get('settings') != data['options']
            or component.get('require_resistance') != data['require_resistance']):
        raise ValueError('D47_METRIC_INPUT_OR_SETTINGS_CHANGED')
    outputs = component.get('outputs')
    if not isinstance(outputs, list) or not outputs:
        raise ValueError('D47_METRIC_OUTPUTS_ABSENT')
    paths = [bound_file(project, ref) for ref in outputs]
    if len(set(paths)) != len(paths):
        raise ValueError('D47_METRIC_OUTPUT_POPULATION_AMBIGUOUS')
    audits = [p for p in paths if p.name == 'audit.json']
    if len(audits) != 1:
        raise ValueError('D47_METRIC_NATIVE_AUDIT_ABSENT')
    work = audits[0].parent
    if work.parent != project / 'reports/flow109/D47' or any(not p.is_relative_to(work) for p in paths):
        raise ValueError('D47_METRIC_OUTPUT_FOREIGN')
    raw = work / 'component.json'
    if any(p.is_symlink() for p in (raw, *raw.parents)) or json.loads(raw.read_text()) != component:
        raise ValueError('D47_METRIC_ORIGINAL_COMPONENT_MISMATCH')
    spice, recipe, res_ext = work / 'work/candidate.spice', work / 'work/extract.tcl', work / 'work' / (data['top'] + '.res.ext')
    if spice not in paths or recipe not in paths or res_ext.is_file() and res_ext not in paths:
        raise ValueError('D47_METRIC_NATIVE_OUTPUT_UNRECORDED')
    expected_recipe = build_extraction_tcl(data['top'], 'candidate.spice',
                        MagicResimExtractOptions(**data['options'])) + 'quit -noprompt\n'
    if recipe.read_text() != expected_recipe:
        raise ValueError('D47_METRIC_EXECUTED_RECIPE_CHANGED')
    tool = component['tool']
    if hashlib.sha256(Path(tool['path']).resolve(strict=True).read_bytes()).hexdigest() != tool.get('sha256'):
        raise ValueError('D47_METRIC_NATIVE_TOOL_CHANGED')
    executions = component.get('executions')
    if (component.get('native_started') is not True or not isinstance(executions, list) or len(executions) != 1
            or type(executions[0].get('returncode')) is not int or executions[0]['returncode'] != 0):
        raise ValueError('D47_METRIC_NATIVE_EXECUTION_INCOMPLETE')
    command = (f"export PDK={shlex.quote(data['tech'])} PDK_ROOT={shlex.quote(data['pdk_root'])} && "
               f"cd {shlex.quote(str(work / 'work'))} && {shlex.quote(tool['path'])} -noconsole -dnull "
               f"-rcfile {shlex.quote(data['rcfile'])} extract.tcl")
    if executions[0].get('command') != command:
        raise ValueError('D47_METRIC_NATIVE_COMMAND_CHANGED')
    log_ref = {'path': executions[0]['log'], 'sha256': executions[0]['log_sha256']}
    log = bound_file(project, log_ref)
    if log != work / 'magic.log' or 'MAGIC_EXTRACT_RESIM_DONE ' + data['top'] + ' ->' not in log.read_text():
        raise ValueError('D47_METRIC_NATIVE_COMPLETION_ABSENT')
    result = _d47_metric_values(data, spice, res_ext)
    original = _d47_audit(data, spice, res_ext)
    if json.loads(audits[0].read_text()) != original or component.get('measurements') != original:
        raise ValueError('D47_METRIC_PRINTED_AUDIT_DISAGREES')
    if component.get('extraction_depth') != result['extraction_depth']:
        raise ValueError('D47_METRIC_PRINTED_DEPTH_DISAGREES')
    if _d47_inputs(project) != data or component['metric_sources'] != _d47_metric_sources():
        raise ValueError('D47_METRIC_CONSUMED_BASIS_CHANGED_DURING_READ')
    for ref in [*outputs, log_ref]:
        bound_file(project, ref)
    result['readset'] = {'inputs': data['inputs'], 'outputs': outputs, 'native_log': log_ref,
        'sources': component['metric_sources'], 'tool': tool, 'settings': data['options'],
        'original_execution': executions[0], 'original_native_launch': component.get('native_launch'),
        'component': {'path': str(raw.relative_to(project)),
                      'sha256': hashlib.sha256(raw.read_bytes()).hexdigest()},
        'context_sha256': current['context_sha256']}
    return result


def accept_d47(project, context, component):
    """BLOCKING candidate audit metrics, with RC depth and missing populations explicit."""
    import flow109
    import flow109_metric_acceptance as metrics
    result = {'schema': metrics.SCHEMA, 'row_id': 'D47', 'status': 'NOT_MEASURED',
              'metric_status': 'NOT_MEASURED', 'qualification': 'NOT_MEASURED',
              'delivery_blocked': True, 'obligations': []}
    ids = ['base_29.candidate_parasitic_coverage', 'base_29.rc_corner_mapping', 'base_29.si_applicability_evidence']
    try:
        current = flow109.validate_execution_context(context)
        if current['requested_step'] != 'D47' or [r['id'] for r in current['resolved_row']['obligations']] != ids:
            raise ValueError('D47_METRIC_OBLIGATIONS_UNREGISTERED')
        observed = _d47_metric_observation(Path(project).resolve(strict=True), current, component)
        result['observation'] = observed
        failed = observed['status'] == 'FAIL'
        result['obligations'] = [{'id': ids[0], 'status': 'FAIL' if failed else 'NOT_MEASURED',
            'measurement_status': observed['status'], 'extraction_depth': observed['extraction_depth'],
            'reason': observed['reason'] if failed else 'D47_COMPLETE_SOURCE_NET_CORNER_POPULATION_UNPROVEN'},
            {'id': ids[1], 'status': 'NOT_MEASURED', 'reason': 'D47_ADOPTED_RC_CORNER_MAPPING_UNBOUND'},
            {'id': ids[2], 'status': 'NOT_MEASURED', 'reason': 'D47_INDEPENDENT_SI_APPLICABILITY_POPULATION_UNBOUND'}]
        result.update(metric_status='FAIL' if failed else 'NOT_MEASURED',
                      reason='D47_NATIVE_PARASITIC_AUDIT_REOPENED_REQUIRED_POPULATIONS_PENDING')
    except (ValueError, OSError, KeyError, TypeError, AttributeError, flow109.Flow109Error) as exc:
        result.update(reason='D47_METRIC_EVIDENCE_UNAVAILABLE', detail=str(exc))
        result['obligations'] = [{'id': oid, 'status': 'NOT_MEASURED', 'reason': str(exc)} for oid in ids]
    if component.get('component_status') == 'FAIL' or result['metric_status'] == 'FAIL':
        result.update(status='FAIL', reason='D47_MEASURED_FAILURE_PRESERVED')
    return result


def consume_default_row_completion(project, context, component):
    """Use the existing completion seam without treating an audit as whole-net RC proof."""
    accepted = accept_d47(project, context, component)
    previous = component.get('metric_acceptance')
    previous = previous if isinstance(previous, dict) else {}
    metric_failed = (component.get('metric_acceptance_status') == 'FAIL' or
                     previous.get('status') == 'FAIL' or previous.get('metric_status') == 'FAIL')
    if metric_failed or component.get('default_row_status') == 'FAIL':
        accepted = {**accepted, 'status': 'FAIL', 'delivery_blocked': True,
            'metric_status': 'FAIL' if metric_failed else accepted['metric_status'],
            'reason': 'D47_PRIOR_MEASURED_FAILURE_PRESERVED'}
        prior = previous.get('obligations', [])
        prior = prior if isinstance(prior, list) else []
        failed_ids = {item.get('id') for item in prior if isinstance(item, dict) and item.get('status') == 'FAIL'}
        accepted['prior_failed_obligation_ids'] = sorted(oid for oid in failed_ids if isinstance(oid, str))
        accepted['obligations'] = [
            {**item, 'status': 'FAIL', 'reason': 'D47_PRIOR_MEASURED_FAILURE_PRESERVED'}
            if item.get('id') in failed_ids and item.get('status') == 'NOT_MEASURED' else item
            for item in accepted['obligations']]
    return {**component, 'step_id': 'D47', 'context_sha256': context['context_sha256'],
        'metric_acceptance': accepted, 'metric_acceptance_status': accepted['metric_status'],
        'default_row_status': accepted['status'], 'flow109_acceptance': accepted['status'],
        'completed': False, 'qualification': 'NOT_MEASURED',
        'whole_flow_acceptance': 'NOT_MEASURED', 'delivery_accepted': False}

if __name__ == "__main__":
    sys.exit(main())
