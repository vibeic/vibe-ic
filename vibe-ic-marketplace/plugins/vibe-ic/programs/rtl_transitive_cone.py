#!/usr/bin/env python3
"""Deterministic transitive-cone reduction for a staged RTL source tree.

Problem this solves (chip-AGNOSTIC, measured on a reused-IP bundle):
  A reused-IP / vendor package is frequently shipped as a whole LIBRARY — every
  module of the IP block plus a large pool of shared primitives, of which any one
  design instantiates only a fraction. When such a bundle is staged FLAT into
  ``phase2/stage1/rtl/`` in its entirety, three failure modes follow that a
  single-top authored design never hits:

    1. ORPHAN files unrelated to the declared top drag in their own unmet
       dependencies — an unstaged macro / package / include the top's real cone
       never needed (an "unknown macro" error raised inside a primitive file the
       top does not instantiate).
    2. DUPLICATE module definitions — a shim / stub file and the real module both
       define the same module name → ``DUPLICATE definition`` under a
       single-unit frontend.
    3. The single-unit elaboration cannot even reach the top because packages are
       presented out of dependency order.

  Reducing the staged set to the TRANSITIVE CONE of the declared top removes the
  orphans (1) outright, removes every out-of-cone duplicate (2), and lets the
  packages be emitted in dependency order (fixed by ``topological_package_first``
  here / the runner's ``_v682_topological_package_order``).

THE FLOOR IS "STAGE EVERYTHING" (vibe-ic#781, rounds 1-3)
  The unreduced flow stages the whole package. That produces a LOUD
  ``already been declared`` error on a duplicate — unmissable, and never a wrong
  answer. Two rounds of this reducer instead moved the IMPLEMENTATION aside,
  kept a STUB, and returned a GREEN step running a stubbed-out design. That is
  strictly worse. So the floor is: reduce only where reduction is PROVABLY safe,
  and degrade every other case to "stage everything and say why" — never to
  "pick one and continue".

  Concretely, this program NEVER resolves a duplicate module definition. When
  >1 file declares a needed module, EVERY candidate stays in the cone and the
  collision is reported by name (`ConeResult.duplicate_definers`). Both
  tie-breaks that have been tried are refuted by measurement — byte-shortest
  keeps the shim, and file-stem-is-module-name keeps the stub whenever the
  canonical-stem file IS the black-box stub. There is no third one.

  And whenever the FILE INVENTORY or the DIRECTIVE GRAMMAR cannot be trusted —
  RTL in a subdirectory, an ```include`` whose path is not a literal string —
  `ConeResult.unreducible` is set, NOTHING is dropped, and the staged set is
  byte-identical to what the unreduced flow produces.

  A module the top INSTANTIATES but that NO staged file defines (a dataset-
  excluded variant selected by a parameter default — e.g. a masked S-box variant
  the package dropped) is reported as an UNRESOLVED reference rather than silently
  dropped, so the operator is told by name. Choosing a *different* present
  variant would silently rewrite a security-relevant parameter, so that is
  explicitly NOT done here.

chip-AGNOSTIC: pure SystemVerilog/Verilog structural grammar (module / package /
interface / primitive declarations, module-instantiation heads, ``import pkg::``,
``pkg::sym``, ```include``, ```define`` / ```MACRO``). No chip / vendor / IP /
SKU / parameter literal from any design appears anywhere in this file.

The public entry point is :func:`transitive_cone`, which takes a top module name
and a directory of staged sources and returns a :class:`ConeResult`. It is the
general core; the runner supplies the thin adapter that resolves *which* top to
pass (the emitted ``chip_top`` wrapper, else the instantiation-graph root).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

_RTL_EXTS = (".v", ".sv")
_HDR_EXTS = (".vh", ".svh")

#: Written into the out-of-cone sidecar so the move is undoable by program.
RESTORE_MANIFEST_NAME = "CONE_RESTORE.json"
#: The sidecar directory `prune_to_cone` moves out-of-cone files into. Exported
#: so scan-scope exclusion lists can name it instead of hard-coding the string
#: (vibe-ic#781 L8 — project-root RTL gates were still linting the moved files
#: as authoritative RTL, contradicting "moved out of the build set").
SIDECAR_SUFFIX = "_out_of_cone"

# ---- structural grammar (comment/string-masked text) -----------------------

_RE_MODULE_DEF = re.compile(r"(?<![\w$])module\s+([A-Za-z_]\w*)")
_RE_PACKAGE_DEF = re.compile(r"(?<![\w$])package\s+([A-Za-z_]\w*)")
_RE_INTERFACE_DEF = re.compile(r"(?<![\w$])interface\s+([A-Za-z_]\w*)")
_RE_PRIMITIVE_DEF = re.compile(r"(?<![\w$])primitive\s+([A-Za-z_]\w*)")
_RE_MACRO_DEF = re.compile(r"(?<![\w$])`define\s+([A-Za-z_]\w*)")

# A module INSTANTIATION head:  `<type> [#(params)] <instance> [range] (`
#   group(1) = instantiated module TYPE.
# The type and the instance name MUST be separated by EITHER a `#(params)`
# override OR at least one whitespace char — a plain function call `foo(` has the
# name flush against `(` and so never matches (this is the difference between a
# module instantiation and a call). `#(...)` carries ONE level of nested parens
# (the common case); a deeper-nested override that this misses only DROPS an edge
# — the textual keep-scan below still retains a defined submodule appearing by
# name, so the cone is never UNDER-approximated. The instantiation scan's precise
# job is UNRESOLVED detection, which stays sound: it can only fail to flag, never
# mis-flag a function call as a module.
_RE_INST_HEAD = re.compile(
    r"(?m)^[ \t]*([A-Za-z_]\w*)"
    r"(?:\s*#\s*\((?:[^()]|\([^()]*\))*\)\s*|\s+)"
    r"[A-Za-z_]\w*\s*(?:\[[^\]]*\]\s*)?\(")

_RE_IMPORT_PKG = re.compile(r"(?<![\w$])import\s+([A-Za-z_]\w*)\s*::")
_RE_SCOPE_PKG = re.compile(r"(?<![\w$])([A-Za-z_]\w*)\s*::")

# The ```include`` DIRECTIVE, matched as "the token `include (not a longer macro
# name), then THE REST OF ITS LINE". The argument is classified afterwards by
# :func:`_classify_include` rather than by a second, narrower regex — because a
# form that matched NEITHER of two narrow regexes was SILENTLY DROPPED.
#
# NOTE (vibe-ic#781 H2): this MUST be applied to text whose STRING LITERALS are
# still intact. `_strip_comments_and_strings` blanks string bodies, which blanks
# the include PATH too — applying this to that text matched nothing and made the
# whole header closure dead code. `parse_unit` therefore keeps a second,
# strings-PRESERVED rendering (`blank_strings=False`) just for the directives.
#
# NOTE 2 (vibe-ic#781 H2, ROUND 3): the round-2 pair required ``\s+`` after
# ```include``. ``\`include"defs.svh"`` — NO whitespace — is accepted by BOTH
# ``iverilog -g2012`` and ``yosys read_verilog -sv`` (measured) and matched
# NEITHER pattern, so the header was moved aside with an EMPTY `unresolved` and
# an EMPTY `unparseable` — no diagnostic at all, and the staged tree then failed
# ``Include file ... not found`` where the UNREDUCED tree built clean. That is
# strictly worse than not reducing, so the grammar is now "match every
# ```include`` and classify", and anything not classified as a literal path
# makes the whole reduction fail closed (see `transitive_cone`).
_RE_INCLUDE_DIRECTIVE = re.compile(r"(?<![\w$])`include(?![\w$])([^\n]*)")
#: The one argument form that is statically resolvable: a double-quoted path.
_RE_INCLUDE_QUOTED = re.compile(r'^[ \t]*"([^"\n]+)"')

# Conditional-compilation directives. A declaration inside one of these regions
# is NOT unconditionally present in the compilation unit, so two files declaring
# the same module under MUTUALLY EXCLUSIVE guards are the standard vendor
# technology-variant pattern, NOT a duplicate-definition defect (vibe-ic#781 H3).
_RE_COND_DIRECTIVE = re.compile(
    r"(?<![\w$])`(ifdef|ifndef|elsif|else|endif)(?![\w$])")
_RE_DEFINE_DIRECTIVE = re.compile(r"(?<![\w$])`define(?![\w$])")

_RE_MACRO_USE = re.compile(r"(?<![\w$])`([A-Za-z_]\w*)")
_RE_WORD = re.compile(r"[A-Za-z_]\w*")

# ESCAPED IDENTIFIERS (IEEE 1800 §5.6.1): a backslash, then any non-whitespace
# characters, terminated by whitespace — e.g. ``\esc.mod ``. NO regex in this
# module's `[A-Za-z_]\w*` grammar can see one, so a file declaring an escaped
# module is invisible as a definer AND its instantiation is invisible as a
# reference: the definer would be dropped with no `unresolved` entry at all —
# a build break with zero diagnostic (vibe-ic#781 H5). Detected here so the
# situation is both LOUD and FAIL-SAFE (see `transitive_cone`).
_RE_ESC_ID = re.compile(r"\\(\S+)")
_RE_ESC_DECL = re.compile(
    r"(?<![\w$])(?:module|package|interface|primitive)\s+\\(\S+)")

# Verilog compiler directives are not user macros — never "unresolved".
_COMPILER_DIRECTIVES = frozenset({
    "define", "undef", "ifdef", "ifndef", "elsif", "else", "endif", "include",
    "timescale", "default_nettype", "resetall", "celldefine", "endcelldefine",
    "line", "begin_keywords", "end_keywords", "unconnected_drive",
    "nounconnected_drive", "pragma", "__FILE__", "__LINE__",
})

# Keywords that can appear in instantiation-head position but are NOT modules.
_INST_HEAD_KEYWORDS = frozenset({
    "if", "else", "for", "while", "case", "casex", "casez", "endcase",
    "begin", "end",
    "generate", "endgenerate", "assign", "always", "always_ff", "always_comb",
    "always_latch", "initial", "final", "module", "endmodule", "function",
    "endfunction", "task", "endtask", "package", "endpackage", "import",
    "export", "typedef", "localparam", "parameter", "logic", "wire", "reg",
    "input", "output", "inout", "assert", "assume", "cover", "return", "unique",
    "unique0", "priority", "foreach", "repeat", "forever", "do", "wait",
    "disable", "posedge", "negedge", "or", "and", "not", "buf", "signed",
    "unsigned", "const", "automatic", "static", "virtual", "class", "endclass",
    "interface", "endinterface", "modport", "clocking", "property",
    "endproperty", "sequence", "endsequence", "covergroup", "endgroup",
    "randcase", "with", "new", "super", "this", "null", "void", "int",
    "integer", "bit", "byte", "real", "string", "struct", "union", "enum",
    "expect", "restrict", "bind", "table", "endtable", "specify", "endspecify",
    # A UDP declaration head `primitive mux_udp(o, a, b, s);` parses as
    # type=`primitive`, instance=`mux_udp` — without these the reducer reported
    # a phantom unresolved module named "primitive" on every design shipping a
    # UDP (measured while re-probing vibe-ic#781).
    "primitive", "endprimitive", "specparam", "config", "endconfig",
    "generate", "let", "checker", "endchecker", "program", "endprogram",
    "genvar", "defparam", "force", "release", "fork", "join", "join_any",
    "join_none", "typedef", "chandle", "event", "time", "shortint", "longint",
    "shortreal", "tri", "triand", "trior", "tri0", "tri1", "wand", "wor",
    "supply0", "supply1", "uwire", "wait_order", "type",
    # Verilog built-in GATE primitives — instantiated as `and u1 (o,a,b)` etc.
    # (must never be read as an unresolved user module).
    "and", "nand", "or", "nor", "xor", "xnor", "not", "buf", "bufif0",
    "bufif1", "notif0", "notif1", "nmos", "pmos", "cmos", "rnmos", "rpmos",
    "rcmos", "tran", "tranif0", "tranif1", "rtran", "rtranif0", "rtranif1",
    "pullup", "pulldown", "pmos", "nmos",
})


def _strip_comments_and_strings(text: str, blank_strings: bool = True) -> str:
    """Return `text` with line + block comments blanked (length preserved) so no
    declaration scan can mint a module out of a comment sentence.

    `blank_strings` (default True) additionally blanks STRING-LITERAL bodies, so
    a module name inside a ``$display`` never reads as a declaration either. Pass
    ``blank_strings=False`` when the scan needs the literal back — the only such
    consumer is the ```include "path"`` directive scan, whose whole payload IS a
    string literal (blanking it silently disabled the header closure entirely;
    vibe-ic#781 H2). Comments are stripped in BOTH modes, so a commented-out
    ```include`` is still never followed.

    Named for what it does: the repo's `hdl_declaration_scan_strips_comments`
    gate reads DATAFLOW, and a helper called `_mask` told a reader nothing about
    whether the text reaching a `module\\s+(\\w+)` scan had been stripped."""
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                out.append(" ")
                i += 1
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            out.append("  ")
            i += 2
            while i < n and not (text[i] == "*" and i + 1 < n
                                 and text[i + 1] == "/"):
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            out.append("  ")
            i += 2
        elif c == '"':
            if not blank_strings:
                out.append(c)
                i += 1
                while i < n and text[i] != '"':
                    if text[i] == "\\" and i + 1 < n:
                        out.append(text[i:i + 2])
                        i += 2
                        continue
                    out.append(text[i])
                    i += 1
                if i < n:
                    out.append('"')
                    i += 1
                continue
            out.append(" ")
            i += 1
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    out.append("  ")
                    i += 2
                    continue
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            # Guarded exactly like the strings-PRESERVED branch above: an
            # UNTERMINATED literal must not emit a closing char that was never
            # in the input, because the two renderings are compared OFFSET BY
            # OFFSET (see `parse_unit`) and that requires equal length.
            if i < n:
                out.append(" ")
                i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _conditional_spans(code: str) -> List[Tuple[int, int]]:
    """``[start, end)`` byte spans of every region under ```ifdef`` / ```ifndef``
    nesting (including the ```else`` / ```elsif`` arms, which are part of the
    same construct).

    Used ONLY to classify a declaration as conditional, never to evaluate the
    condition — this program does no preprocessing. An unterminated ```ifdef``
    conservatively extends to end-of-file, so a truncated file reads as MORE
    conditional, never less."""
    spans: List[Tuple[int, int]] = []
    depth = 0
    start = 0
    for m in _RE_COND_DIRECTIVE.finditer(code):
        kw = m.group(1)
        if kw in ("ifdef", "ifndef"):
            if depth == 0:
                start = m.start()
            depth += 1
        elif kw == "endif":
            if depth > 0:
                depth -= 1
                if depth == 0:
                    spans.append((start, m.end()))
    if depth > 0:
        spans.append((start, len(code)))
    return spans


def _macro_body_spans(code: str) -> List[Tuple[int, int]]:
    """``[start, end)`` spans of every ```define`` macro BODY (the directive line
    plus every backslash-continued line).

    A ``module`` keyword inside a macro body declares nothing until the macro is
    expanded — ``\\`define MK(N) module N; endmodule`` mints no module named
    ``N``. Such a declaration is therefore classified conditional, so it can
    never be read as half of a duplicate-definition defect."""
    spans: List[Tuple[int, int]] = []
    n = len(code)
    for m in _RE_DEFINE_DIRECTIVE.finditer(code):
        i = m.end()
        while True:
            nl = code.find("\n", i)
            if nl < 0:
                i = n
                break
            j = nl - 1
            while j >= 0 and code[j] in " \t\r":
                j -= 1
            if j >= 0 and code[j] == "\\":
                i = nl + 1
                continue
            i = nl
            break
        spans.append((m.start(), i))
    return spans


def _in_spans(offset: int, spans: List[Tuple[int, int]]) -> bool:
    return any(a <= offset < b for a, b in spans)


def _classify_include(rest_of_line: str) -> Optional[str]:
    """Return the BASENAME an ```include`` argument resolves to, or ``None`` when
    the argument is not a statically resolvable literal path.

    ``None`` is the fail-closed answer for EVERY form this program cannot read —
    a macro-valued path (``\\`include \\`HDR``), the angle-bracket form, an
    argument continued onto the next line, a truncated directive. The caller
    turns any ``None`` into "do not reduce at all", because the target could be
    any staged file and dropping the wrong one produces a build that no longer
    compiles (vibe-ic#781 H2 / L-macro-include)."""
    q = _RE_INCLUDE_QUOTED.match(rest_of_line)
    if not q:
        return None
    return Path(q.group(1)).name


@dataclass(eq=False)
class Unit:
    """The structural facts of ONE source file. Identity-hashed (eq=False) so it
    can live in the cone `set`."""
    path: Path
    modules: Set[str] = field(default_factory=set)
    packages: Set[str] = field(default_factory=set)
    interfaces: Set[str] = field(default_factory=set)
    primitives: Set[str] = field(default_factory=set)
    macros: Set[str] = field(default_factory=set)
    inst_types: Set[str] = field(default_factory=set)      # instantiated types
    ref_pkgs: Set[str] = field(default_factory=set)        # import / :: scope
    includes: Set[str] = field(default_factory=set)        # basenames
    #: `include directives whose argument is NOT a resolvable literal path —
    #: macro-valued, angle-bracket, next-line, truncated. Any of these makes the
    #: reduction fail closed (nothing is dropped).
    unparsed_includes: Set[str] = field(default_factory=set)
    #: modules declared under `ifdef nesting or inside a `define macro body —
    #: NOT unconditionally present in the compilation unit.
    conditional_modules: Set[str] = field(default_factory=set)
    used_macros: Set[str] = field(default_factory=set)
    words: Set[str] = field(default_factory=set)           # all bare idents
    esc_ids: Set[str] = field(default_factory=set)         # \escaped\ idents
    esc_defs: Set[str] = field(default_factory=set)        # escaped DECLs
    raw: str = ""

    @property
    def is_header(self) -> bool:
        return self.path.suffix in _HDR_EXTS

    @property
    def defines(self) -> Set[str]:
        return (self.modules | self.packages | self.interfaces
                | self.primitives)


def parse_unit(path: Path) -> Unit:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return Unit(path=path)
    # Declaration/instantiation grammar runs over comment- AND string-stripped
    # text.  The ``\`include`` directive scan runs over comment-stripped text
    # with the STRING LITERAL PRESERVED — its payload is the literal, so the
    # string-blanking rendering makes it match nothing (vibe-ic#781 H2).
    code = _strip_comments_and_strings(text)
    directives = _strip_comments_and_strings(text, blank_strings=False)
    # The two renderings blank comments identically and differ ONLY inside
    # string-literal bodies, so equal length makes them comparable offset by
    # offset. If that ever stops holding, the string filter below is simply not
    # applied — which can only make MORE directives unparsed, i.e. fail closed.
    offset_comparable = len(code) == len(directives)
    u = Unit(path=path, raw=code)
    # A module DECLARATION is recorded with its offset so it can be classified
    # against the conditional-compilation / macro-body spans below.
    cond_spans = _conditional_spans(code) + _macro_body_spans(code)
    for m in _RE_MODULE_DEF.finditer(code):
        u.modules.add(m.group(1))
        if _in_spans(m.start(), cond_spans):
            u.conditional_modules.add(m.group(1))
    u.packages = set(_RE_PACKAGE_DEF.findall(code))
    u.interfaces = set(_RE_INTERFACE_DEF.findall(code))
    u.primitives = set(_RE_PRIMITIVE_DEF.findall(code))
    u.macros = set(_RE_MACRO_DEF.findall(code))
    u.inst_types = {m for m in _RE_INST_HEAD.findall(code)
                    if m not in _INST_HEAD_KEYWORDS}
    u.ref_pkgs = set(_RE_IMPORT_PKG.findall(code)) \
        | set(_RE_SCOPE_PKG.findall(code))
    for m in _RE_INCLUDE_DIRECTIVE.finditer(directives):
        # BOTH renderings preserve length and blank comments identically, and
        # differ ONLY inside string-literal bodies. So a position where they
        # disagree is inside a literal — which is how the word `include in a
        # ``$display("try `include ...")`` is told apart from a directive
        # WITHOUT re-lexing. Without this, that string forced the whole
        # reduction to fail closed on a file that has no include at all.
        if offset_comparable and code[m.start()] != directives[m.start()]:
            continue
        target = _classify_include(m.group(1))
        if target is None:
            u.unparsed_includes.add(
                ("`include" + m.group(1).rstrip())[:80])
        else:
            u.includes.add(target)
    u.used_macros = {m for m in _RE_MACRO_USE.findall(code)
                     if m not in _COMPILER_DIRECTIVES}
    u.words = set(_RE_WORD.findall(code))
    u.esc_defs = set(_RE_ESC_DECL.findall(code))
    # A line continuation inside a `define body is a lone trailing backslash and
    # so never matches `\\(\S+)`; only genuine escaped identifiers do.
    u.esc_ids = set(_RE_ESC_ID.findall(code))
    return u


@dataclass
class ConeResult:
    top: str
    cone_files: List[Path]                # staged (kept) files, topo-ordered
    dropped_files: List[Path]             # out-of-cone files removed
    unresolved_modules: List[str]         # instantiated, defined by NO file
    #: ``(module, [every file that declares it])`` for every module in the cone
    #: with MORE THAN ONE declaring file. This program NEVER picks one: every
    #: candidate stays in `cone_files`. Reported so the caller can say which
    #: files collide, by name.
    duplicate_definers: List[Tuple[str, List[str]]] = field(
        default_factory=list)
    #: the subset of `duplicate_definers` where at least one declaration is
    #: CONDITIONAL (``\`ifdef``-guarded technology variants, or a ``\`define``
    #: macro body). Those are the normal vendor pattern and compile fine.
    conditional_duplicates: List[str] = field(default_factory=list)
    #: ``\`include`` targets named by a cone file that NO staged file provides.
    #: The build will fail ``Include file ... not found`` whether or not we
    #: reduce, so this is advisory — but it is no longer silent.
    unresolved_includes: List[str] = field(default_factory=list)
    # References this grammar structurally cannot read (escaped identifiers).
    # Advisory, never silent.
    unparseable_refs: List[str] = field(default_factory=list)
    #: non-empty => NOTHING was dropped and this says why. The fail-closed
    #: degradation: whenever the file inventory or the directive grammar cannot
    #: be trusted, the answer is "stage everything", which is exactly what the
    #: unreduced flow does — never "guess and continue".
    unreducible: str = ""
    reason: str = ""

    @property
    def reduced(self) -> bool:
        return bool(self.dropped_files)

    @property
    def hard_duplicates(self) -> List[Tuple[str, List[str]]]:
        """Duplicate definers where EVERY declaration is unconditional — the
        ones a single-unit frontend will reject with ``already been declared``.
        Still not resolved here; named so the caller can name them."""
        cond = set(self.conditional_duplicates)
        return [(m, c) for m, c in self.duplicate_definers if m not in cond]


def _collect_units(rtl_dir: Path) -> Tuple[List[Unit], str]:
    """Parse every source DIRECTLY in `rtl_dir`. Returns ``(units, unreducible)``.

    The scan is deliberately NON-recursive because the staged tree is flat. If
    RTL nevertheless exists in a SUBDIRECTORY the inventory is incomplete — the
    subtree's definitions, duplicates and includes are all invisible — so the
    second element is a non-empty reason and the caller must not drop anything
    (vibe-ic#781 L-nested)."""
    files: List[Path] = []
    for ext in _RTL_EXTS + _HDR_EXTS:
        files.extend(sorted(rtl_dir.glob(f"*{ext}")))
    nested: List[str] = []
    for ext in _RTL_EXTS + _HDR_EXTS:
        for p in sorted(rtl_dir.rglob(f"*{ext}")):
            if p.parent != rtl_dir:
                nested.append(str(p.relative_to(rtl_dir)))
    units = [parse_unit(f) for f in sorted(set(files), key=lambda p: p.name)]
    if nested:
        return units, (
            f"{len(nested)} RTL source(s) live in SUBDIRECTORIES of the staged "
            f"tree (e.g. {sorted(nested)[:3]}); this reducer's inventory is the "
            f"flat directory only, so their definitions/duplicates/includes "
            f"are invisible to it — nothing was dropped")
    return units, ""


def transitive_cone(top: str, rtl_dir: Path) -> ConeResult:
    """Compute the transitive cone of module `top` over the sources in `rtl_dir`.

    A file is KEPT when it is reachable from the file(s) defining `top` by
    following:
      * module instantiations (`inst_types`) resolved to the file defining that
        module,
      * ANY defined module / package / interface / primitive name that appears as
        a bare word in a cone file (a SAFE over-approximation — it can only KEEP
        an extra file, never wrongly drop one, so a missed instantiation-head
        parse cannot under-stage the cone),
      * `import pkg::` / `pkg::sym` package references,
      * ``include "<file>"` — ANY staged file, header or ``.v``/``.sv`` body
        fragment, matched by basename and then traversed itself,
      * ``MACRO` uses resolved to the file that ``define`s them.

    DUPLICATE DEFINITIONS ARE NEVER RESOLVED HERE (vibe-ic#781 H1, rounds 1-3).
    When >1 file declares the same needed module, EVERY candidate stays in the
    cone and the collision is reported in `duplicate_definers`. Two tie-breaks
    have already been refuted by measurement:

      * ``min(definers, key=len(raw))`` — "a shim is thin, keep the shortest".
        Inverted: it kept the SHIM and moved the IMPLEMENTATION aside.
      * "exactly one candidate whose file STEM is the module name". Refuted by
        the case where the canonical-stem file IS the black-box stub and the
        implementation lives in a multi-module vendor bundle — the exact shape
        this reducer exists for. Measured end-to-end (correct answer RESULT=1):

            origin/main    3 staged, iverilog rc=2 'adapter' has already been
                           declared                       <- loud, unmissable
            stem rule      impl moved aside, rc=0, vvp RESULT=0, step PASS
                                                          <- WRONG, and GREEN

        The ``-y <dir>`` ``+libext`` justification does NOT hold: every staged
        file is passed EXPLICITLY on the command line, and library search only
        applies to modules still unresolved AFTER all command-line files are
        read. The stem convention governs nothing in this flow.

    A green run of a stubbed design is strictly worse than the loud
    ``already been declared`` error that staging everything produces, so the
    floor is: stage everything and SAY WHY. No naming convention will do; only
    a structural proof would, and none is available from the text.

    FAIL CLOSED — whenever the inventory or the grammar cannot be trusted,
    `unreducible` is set and NOTHING is dropped (identical to the unreduced
    flow): RTL in subdirectories, or any ```include`` argument in the cone that
    is not a resolvable literal path (macro-valued, angle-bracket, continued).
    A file declaring an ESCAPED identifier (``module \\esc.mod ;``) is invisible
    to this grammar, so it is kept unconditionally and reported."""
    units, nested_reason = _collect_units(rtl_dir)
    unreducible = nested_reason
    if not units:
        return ConeResult(top, [], [], [],
                          reason="no RTL sources to reduce")

    # symbol -> defining unit(s)
    mod_def: Dict[str, List[Unit]] = {}
    pkg_def: Dict[str, List[Unit]] = {}
    other_def: Dict[str, List[Unit]] = {}     # interfaces + primitives
    macro_def: Dict[str, List[Unit]] = {}
    by_basename: Dict[str, Unit] = {}
    for u in units:
        by_basename.setdefault(u.path.name, u)
        for m in u.modules:
            mod_def.setdefault(m, []).append(u)
        for p in u.packages:
            pkg_def.setdefault(p, []).append(u)
        for s in u.interfaces | u.primitives:
            other_def.setdefault(s, []).append(u)
        for mac in u.macros:
            macro_def.setdefault(mac, []).append(u)

    # every DEFINED module/pkg/iface/prim name — the vocabulary the safe
    # textual keep-scan resolves against.
    defined_named: Dict[str, str] = {}   # name -> kind
    for name in mod_def:
        defined_named[name] = "module"
    for name in pkg_def:
        defined_named.setdefault(name, "package")
    for name in other_def:
        defined_named.setdefault(name, "other")

    if top not in mod_def:
        # cannot anchor the cone — signal the caller to skip pruning (no regress)
        return ConeResult(
            top, [u.path for u in units], [], [],
            unreducible=f"top '{top}' is not declared by any staged source",
            reason=f"top '{top}' not defined among staged sources; "
                   f"cone reduction skipped (no pruning)")

    cone: Set[Unit] = set()
    duplicates: Dict[str, List[str]] = {}
    conditional_dupes: Set[str] = set()
    unresolved: Set[str] = set()
    unparseable: Set[str] = set()
    unreadable_includes: Set[str] = set()
    missing_includes: Set[str] = set()

    def _resolve_module(name: str) -> List[Unit]:
        """EVERY file that declares `name` — never a chosen one.

        Returning all definers is what makes the reduction never-worse than
        staging everything: the implementation can never be the file moved
        aside, because no file that declares a needed module is ever moved
        aside."""
        definers = mod_def.get(name)
        if not definers:
            return []
        if len(definers) > 1 and name not in duplicates:
            duplicates[name] = sorted(u.path.name for u in definers)
            # `ifdef-guarded technology variants (and `define macro bodies) are
            # not simultaneously present in the compilation unit, so they are
            # NOT a duplicate-definition defect — failing on them fabricated a
            # FAIL on a tree that elaborates and computes the right answer
            # (vibe-ic#781 H3). This program evaluates no condition; it only
            # observes that at least one declaration is conditional.
            if any(name in u.conditional_modules for u in definers):
                conditional_dupes.add(name)
        return list(definers)

    work: List[Unit] = []

    def _add(u: Optional[Unit]) -> None:
        if u is not None and u not in cone:
            cone.add(u)
            work.append(u)

    def _add_all(us: List[Unit]) -> None:
        for u in us:
            _add(u)

    # FAIL-SAFE anchor (vibe-ic#781 H5): a file DECLARING an escaped identifier
    # is invisible to every `[A-Za-z_]\w*` regex here, so it can be neither
    # resolved as a definer nor flagged as unresolved — it would just vanish
    # from the build with no diagnostic. Never drop such a file, and say so.
    for u in units:
        if u.esc_defs:
            _add(u)
            unparseable |= {f"\\{e} (escaped declaration in {u.path.name})"
                            for e in sorted(u.esc_defs)}

    _add_all(_resolve_module(top))
    while work:
        u = work.pop()
        # module instantiations — precise edges + unresolved detection
        for t in u.inst_types:
            if t in mod_def:
                _add_all(_resolve_module(t))
            elif t in other_def:
                for d in other_def[t]:
                    _add(d)
            elif t not in pkg_def and t not in defined_named:
                # an instantiation head naming nothing we define. A HEADER is
                # never a module body — an "instantiation head" inside a `define
                # macro body is not a resolvable reference, so headers only
                # contribute EDGES here, never unresolved findings.
                if not u.is_header:
                    unresolved.add(t)
        # references this grammar structurally cannot read — advisory, never
        # silent (a `\esc.mod` instantiation matches no regex above).
        for e in sorted(u.esc_ids - u.esc_defs):
            unparseable.add(f"\\{e} (escaped reference in {u.path.name})")
        for inc in sorted(u.unparsed_includes):
            unreadable_includes.add(f"{inc}  (in {u.path.name})")
        # `include "<file>" — pull the included file in BY BASENAME (header or
        # body fragment) and traverse it, so an included `.v` body or a
        # define-less typedef header is never dropped.
        for inc_name in sorted(u.includes):
            target = by_basename.get(inc_name)
            if target is None:
                # The design includes a file NOTHING staged provides. The build
                # breaks the same way with or without reduction, so this is not
                # a reduction defect — but reporting nothing at all left the
                # operator with a bare `Include file ... not found` and no clue
                # that the reducer had already seen the reference.
                missing_includes.add(f"{inc_name} (included by {u.path.name})")
            else:
                _add(target)
        # package references
        for p in u.ref_pkgs:
            for d in pkg_def.get(p, []):
                _add(d)
        # macro uses -> defining file
        for mac in u.used_macros:
            for d in macro_def.get(mac, []):
                _add(d)
        # SAFE textual over-approximation: any DEFINED module/pkg/iface/prim
        # name appearing as a bare word pulls its definer in. Never drops.
        for w in u.words:
            if w in u.defines:
                continue
            if w in mod_def:
                _add_all(_resolve_module(w))
            elif w in pkg_def:
                for d in pkg_def[w]:
                    _add(d)
            elif w in other_def:
                for d in other_def[w]:
                    _add(d)

    # FAIL CLOSED on an ```include`` this grammar could not read (macro-valued
    # path, angle-bracket form, argument continued onto the next line, truncated
    # directive). The target could be ANY staged file — header or `.v` body
    # fragment — so "keep every header" is not a fail-safe, it is a guess that
    # happens to cover one extension pair. The only answer that cannot break a
    # build is the unreduced one: stage everything and say why.
    if unreadable_includes and not unreducible:
        unreducible = (
            f"{len(unreadable_includes)} `include directive(s) in the cone have "
            f"no statically resolvable path "
            f"({sorted(unreadable_includes)[:3]}); the target could be any "
            f"staged file, so nothing was dropped")

    if nested_reason:
        # The inventory is KNOWN INCOMPLETE, so "no staged file defines M" is a
        # claim this run cannot make — a/M.sv may define it perfectly well. An
        # advisory drawn from an admittedly partial scan is worse than none.
        unresolved.clear()
        missing_includes.clear()

    if unreducible:
        cone = set(units)

    cone_paths = sorted((u.path for u in cone), key=lambda p: p.name)
    dropped = sorted((u.path for u in units if u not in cone),
                     key=lambda p: p.name)
    ordered = topological_package_first(cone_paths)
    dupes = sorted((m, duplicates[m]) for m in duplicates)
    cond = sorted(conditional_dupes)
    hard = [m for m, _ in dupes if m not in conditional_dupes]
    return ConeResult(
        top=top,
        cone_files=ordered,
        dropped_files=dropped,
        unresolved_modules=sorted(unresolved),
        duplicate_definers=dupes,
        conditional_duplicates=cond,
        unresolved_includes=sorted(missing_includes),
        unparseable_refs=sorted(unparseable | unreadable_includes),
        unreducible=unreducible,
        reason=(f"cone of '{top}' = {len(cone_paths)} file(s); "
                f"dropped {len(dropped)} out-of-cone; "
                f"{len(hard)} unconditional duplicate definition(s) "
                f"(all candidates KEPT, never resolved); "
                f"{len(cond)} conditional-variant duplicate(s); "
                f"{len(unresolved)} unresolved instantiation(s); "
                f"{len(missing_includes)} unresolved include(s); "
                f"{len(unparseable | unreadable_includes)} unparseable "
                f"reference(s)"
                + (f"; NOT REDUCED: {unreducible}" if unreducible else "")))


def _read_manifest(man: Path) -> Tuple[Optional[dict], str]:
    """``(manifest_dict, problem)``. A manifest that is valid JSON but not an
    OBJECT — ``["a.sv"]`` — used to reach ``.get`` on a list and raise an
    uncaught ``AttributeError`` through BOTH `prune_to_cone` and
    `restore_from_sidecar`; the runner then reported a FABRICATED half-moved
    tree on a tree that was complete and consistent (vibe-ic#781 M3). Every
    malformed shape now degrades to a NAMED problem."""
    import json as _json
    if not man.is_file():
        return None, ""
    try:
        data = _json.loads(man.read_text())
    except (OSError, ValueError) as exc:
        return None, f"{man.name} is not readable JSON ({exc})"
    if not isinstance(data, dict):
        return None, (f"{man.name} is JSON but not an object "
                      f"(got {type(data).__name__}) — it names no files to "
                      f"restore")
    return data, ""


def _manifest_entries(data: Optional[dict]) -> List[Tuple[str, str]]:
    """``[(original basename, filename inside the sidecar)]`` from a manifest."""
    if not data:
        return []
    out: List[Tuple[str, str]] = []
    for e in data.get("entries", []) or []:
        if isinstance(e, dict) and e.get("name"):
            out.append((str(e["name"]), str(e.get("stored") or e["name"])))
    for n in data.get("moved", []) or []:
        if isinstance(n, str) and not any(n == a for a, _ in out):
            out.append((n, n))
    return out


def _is_plain_basename(name: str) -> bool:
    """True only for a bare filename — no separator, no ``..``, not absolute.

    CONTAINMENT (vibe-ic#781 L-escape). A manifest entry ``"../VICTIM.sv"`` made
    `restore_from_sidecar` MOVE a file from OUTSIDE the project INTO it. The
    shipped CLI never reached it (the default sidecar shares rtl_dir's parent,
    so src and dst resolved to the same path), i.e. the only thing preventing it
    was an accident of layout. A manifest is data; it does not get to name a
    path."""
    if not name or name in (".", ".."):
        return False
    if "/" in name or "\\" in name:
        return False
    return Path(name).name == name


def prune_to_cone(rtl_dir: Path, result: ConeResult,
                  sidecar: Optional[Path] = None) -> List[str]:
    """MOVE every out-of-cone file in `rtl_dir` into a sidecar directory (default
    ``<rtl_dir>_out_of_cone/``) so the staged synth/sim set is exactly the cone.

    REVERSIBLE + AUDITABLE (never deletes, never overwrites): the sidecar sits
    OUTSIDE ``rtl_dir`` so neither a ``glob`` nor an ``rglob`` under ``rtl_dir``
    sees the moved files. A no-op when nothing is out of cone (which includes
    every ``result.unreducible`` case). Returns the moved basenames. The
    SOURCE_MANIFEST.json keystone is never moved (it is not an RTL source).

    A same-named file ALREADY in the sidecar — from an earlier run over a
    re-authored tree — is NOT overwritten: the incoming file is stored under a
    free ``<stem>.conflict<N><suffix>`` name and the manifest records the
    mapping, so "never deletes" holds for the sidecar's contents too
    (vibe-ic#781 L-clobber; ``shutil.move`` onto an existing path replaces it).

    A RESTORE MANIFEST (``CONE_RESTORE.json``) is written beside the moved files
    recording the top, the reason and every basename, so the move is undoable by
    PROGRAM (:func:`restore_from_sidecar`, ``--restore`` on the CLI) and not only
    by a human noticing the sidecar. Without it the reduction was one-way and
    STICKY: a second run SKIPs (``rtl/`` is no longer empty), so a wrongly-moved
    file stayed moved until somebody moved it back by hand (vibe-ic#781 L7)."""
    import json as _json
    import shutil
    if not result.dropped_files:
        return []
    if sidecar is None:
        sidecar = rtl_dir.parent / (rtl_dir.name + SIDECAR_SUFFIX)
    sidecar.mkdir(parents=True, exist_ok=True)
    man = sidecar / RESTORE_MANIFEST_NAME
    prior_data, prior_problem = _read_manifest(man)
    prior = _manifest_entries(prior_data)
    taken = {stored for _, stored in prior}
    cone_names = {p.name for p in result.cone_files}
    moved: List[str] = []
    new_entries: List[Tuple[str, str]] = []
    for f in result.dropped_files:
        if f.name in cone_names or not f.is_file():
            continue
        stored = f.name
        if stored in taken or (sidecar / stored).exists():
            k = 1
            while (sidecar / f"{f.stem}.conflict{k}{f.suffix}").exists() \
                    or f"{f.stem}.conflict{k}{f.suffix}" in taken:
                k += 1
            stored = f"{f.stem}.conflict{k}{f.suffix}"
        try:
            shutil.move(str(f), str(sidecar / stored))
        except OSError:
            continue
        taken.add(stored)
        moved.append(f.name)
        new_entries.append((f.name, stored))
    if moved:
        entries = prior + new_entries
        payload = {
            "top": result.top,
            "rtl_dir": str(rtl_dir),
            "reason": result.reason,
            "entries": [{"name": n, "stored": s} for n, s in entries],
            "moved": sorted({n for n, _ in entries}),
            "restore": ("rtl_transitive_cone.py --restore <rtl_dir>  "
                        "(or move these files back into rtl_dir)"),
        }
        if prior_problem:
            # Never silently discard a manifest we could not read: say that the
            # prior one was unreadable and that its entries are not tracked.
            payload["prior_manifest_problem"] = prior_problem
        try:
            man.write_text(_json.dumps(payload, indent=2))
        except OSError:
            pass
    return sorted(moved)


@dataclass
class RestoreResult:
    """The outcome of an undo. ``problems`` is why this is not a bare list: a
    truncated / malformed / absent manifest used to print "restored 0 file(s)"
    and exit 0, which reads exactly like "there was nothing to undo"
    (vibe-ic#781 L-silent-restore)."""
    restored: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def restore_from_sidecar(rtl_dir: Path,
                         sidecar: Optional[Path] = None) -> RestoreResult:
    """Move every file :func:`prune_to_cone` set aside back into ``rtl_dir``.

    The inverse of `prune_to_cone`, so a wrong reduction is undoable without a
    human editing the tree by hand. Only files named in the restore manifest are
    moved back (never an unrelated file somebody parked in the sidecar), a name
    already present in ``rtl_dir`` is left alone rather than clobbered, and an
    entry that is not a plain basename is REFUSED (see `_is_plain_basename`)."""
    import json as _json
    import shutil
    if sidecar is None:
        sidecar = rtl_dir.parent / (rtl_dir.name + SIDECAR_SUFFIX)
    man = sidecar / RESTORE_MANIFEST_NAME
    out = RestoreResult()
    if not man.is_file():
        if sidecar.is_dir():
            out.problems.append(
                f"sidecar {sidecar} exists but has no {RESTORE_MANIFEST_NAME} — "
                f"nothing can be restored by program")
        return out
    data, problem = _read_manifest(man)
    if problem:
        out.problems.append(problem)
        return out
    entries = _manifest_entries(data)
    if not entries:
        out.problems.append(
            f"{RESTORE_MANIFEST_NAME} names no files to restore")
        return out
    rtl_dir.mkdir(parents=True, exist_ok=True)
    left: List[Tuple[str, str]] = []
    for name, stored in entries:
        if not (_is_plain_basename(name) and _is_plain_basename(stored)):
            out.problems.append(
                f"refusing manifest entry {name!r} -> {stored!r}: a restore "
                f"target must be a plain filename inside the staged tree")
            left.append((name, stored))
            continue
        src = sidecar / stored
        dst = rtl_dir / name
        if not src.is_file():
            out.problems.append(
                f"{stored} is named by the manifest but is not in the sidecar")
            continue
        if dst.exists():
            out.skipped.append(name)
            left.append((name, stored))
            continue
        try:
            shutil.move(str(src), str(dst))
        except OSError as exc:
            out.problems.append(f"could not restore {name}: {exc}")
            left.append((name, stored))
            continue
        out.restored.append(name)
    if out.restored:
        try:
            if left:
                man.write_text(_json.dumps({
                    "entries": [{"name": n, "stored": s} for n, s in left],
                    "moved": sorted({n for n, _ in left}),
                }, indent=2))
            else:
                man.unlink()
        except OSError:
            pass
    out.restored.sort()
    out.skipped.sort()
    return out


# ---- package topological ordering (dependency-first) -----------------------

_RE_PKG_IMPORT = re.compile(r"(?<![\w$])import\s+([A-Za-z_]\w*)\s*::")


def _pkg_symbol(path: Path) -> str:
    """The package name the file declares (first ``package <name>``), else the
    file stem. Read structurally — the file need not be named ``*pkg*``."""
    try:
        masked = _strip_comments_and_strings(
            path.read_text(errors="replace"))
    except OSError:
        return path.stem
    m = _RE_PACKAGE_DEF.search(masked)
    return m.group(1) if m else path.stem


def _declares_package(path: Path) -> bool:
    """True when the file actually declares a ``package`` — read structurally.

    NOT ``"pkg" in path.name`` (vibe-ic#781 L-pkgname): a package declared in a
    file the vendor called ``defs.sv`` was then ordered AFTER its importer,
    which is the ordering bug this function exists to prevent."""
    try:
        return bool(_RE_PACKAGE_DEF.search(_strip_comments_and_strings(
            path.read_text(errors="replace"))))
    except OSError:
        return False


def topological_package_first(files: List[Path]) -> List[Path]:
    """Order `files` so every package precedes any package that imports it, and
    all packages/headers precede non-package RTL (single-unit elaboration needs
    a package declared before use). Non-package order is preserved; import
    cycles degrade to stable alphabetical order. chip-AGNOSTIC import grammar.

    SCOPE, HONESTLY: the phase-2 runner consumes `ConeResult.cone_files` for its
    NAMES and COUNT only — it globs `rtl/` itself when it builds a filelist — so
    this ordering is currently advisory for that caller. It is still computed
    (and tested) because it is the correct answer for any caller that does
    consume the order, and because emitting a knowingly wrong order would be a
    trap for the next one."""
    hdrs = [f for f in files if f.suffix in _HDR_EXTS]
    bodies = [f for f in files if f.suffix in _RTL_EXTS]
    is_pkg = {f: _declares_package(f) for f in bodies}
    pkgs = [f for f in bodies if is_pkg[f]]
    rest = [f for f in bodies if not is_pkg[f]]

    if len(pkgs) > 1:
        by_name: Dict[str, Path] = {}
        name_of: Dict[Path, str] = {}
        for p in pkgs:
            nm = _pkg_symbol(p)
            name_of[p] = nm
            by_name.setdefault(nm, p)
        deps: Dict[Path, Set[Path]] = {p: set() for p in pkgs}
        for p in pkgs:
            try:
                text = _strip_comments_and_strings(
                    p.read_text(errors="replace"))
            except OSError:
                continue
            for dep_name in _RE_PKG_IMPORT.findall(text):
                dep = by_name.get(dep_name)
                if dep is not None and dep is not p:
                    deps[p].add(dep)
        order: List[Path] = []
        state: Dict[Path, int] = {}
        for root in pkgs:
            if state.get(root, 0) == 2:
                continue
            stack = [(root, iter(sorted(deps[root], key=lambda q: name_of[q])))]
            state[root] = 1
            while stack:
                node, it = stack[-1]
                advanced = False
                for child in it:
                    st = state.get(child, 0)
                    if st == 2:
                        continue
                    if st == 1:
                        continue
                    state[child] = 1
                    stack.append((child, iter(sorted(deps[child],
                                                     key=lambda q: name_of[q]))))
                    advanced = True
                    break
                if not advanced:
                    state[node] = 2
                    order.append(node)
                    stack.pop()
        pkgs = order

    # headers first (macros/typedefs), then packages, then the rest
    return hdrs + pkgs + rest


def main(argv: List[str]) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(
        description="Transitive-cone reduction of a staged RTL tree.")
    ap.add_argument("rtl_dir")
    ap.add_argument("top", nargs="?",
                    help="top module (omit with --restore)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--restore", action="store_true",
                    help="undo a previous reduction: move every file in the "
                         "out-of-cone sidecar back into rtl_dir")
    ns = ap.parse_args(argv)
    rtl_dir = Path(ns.rtl_dir).resolve()
    if ns.restore:
        rr = restore_from_sidecar(rtl_dir)
        if ns.json:
            print(json.dumps({"restored": rr.restored, "skipped": rr.skipped,
                              "problems": rr.problems}, indent=2))
        else:
            print(f"restored {len(rr.restored)} file(s): {rr.restored}")
            if rr.skipped:
                print(f"  skipped (already present): {rr.skipped}")
            for p in rr.problems:
                print(f"  PROBLEM: {p}")
        # A truncated / malformed / missing manifest used to print
        # "restored 0 file(s)" and exit 0 — indistinguishable from "there was
        # nothing to undo" (vibe-ic#781 L-silent-restore).
        return 1 if rr.problems else 0
    if not ns.top:
        ap.error("top is required unless --restore is given")
    res = transitive_cone(ns.top, rtl_dir)
    if ns.json:
        print(json.dumps({
            "top": res.top,
            "cone_files": [p.name for p in res.cone_files],
            "dropped_files": [p.name for p in res.dropped_files],
            "unresolved_modules": res.unresolved_modules,
            "duplicate_definers": res.duplicate_definers,
            "conditional_duplicates": res.conditional_duplicates,
            "unconditional_duplicates": res.hard_duplicates,
            "unresolved_includes": res.unresolved_includes,
            "unparseable_refs": res.unparseable_refs,
            "unreducible": res.unreducible,
            "reason": res.reason,
        }, indent=2))
    else:
        print(res.reason)
        print(f"  cone           : {len(res.cone_files)}")
        print(f"  dropped        : {len(res.dropped_files)}")
        print(f"  unresolved     : {res.unresolved_modules}")
        print(f"  duplicates     : {res.duplicate_definers}")
        print(f"  ..conditional  : {res.conditional_duplicates}")
        print(f"  unresolved-inc : {res.unresolved_includes}")
        print(f"  unparseable    : {res.unparseable_refs}")
        print(f"  NOT REDUCED    : {res.unreducible or '(reduced)'}")
    # rc=1 states a FACT about the staged set, not a verdict on the design: an
    # UNCONDITIONAL duplicate definition WILL be rejected by a single-unit
    # frontend, and this program deliberately did not resolve it. Nothing is
    # dropped on account of it, so the tree is exactly what the unreduced flow
    # would have staged; the exit code only stops a script reading silence as
    # success.
    return 1 if res.hard_duplicates else 0


if __name__ == "__main__":
    import sys as _sys
    raise SystemExit(main(_sys.argv[1:]))
