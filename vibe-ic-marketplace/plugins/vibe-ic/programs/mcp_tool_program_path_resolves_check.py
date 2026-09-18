#!/usr/bin/env python3
"""mcp_tool_program_path_resolves_check.py — an MCP tool must be able to
REACH the program it spawns.

THE DEFECT THIS IS THE REGRESSION GUARD FOR
-------------------------------------------
One MCP tool handler built the path to its gate out of a path segment
naming a plugin edition this repo retired::

    const here = path.dirname(new URL(import.meta.url).pathname);
    const gate = path.resolve(here, "..", "..", <retired layout>,
                              "programs", "phase23_...check.py");

The resulting path existed in NEITHER shipped layout — not in the
installed-plugin tree, not in a repo checkout — so the handler never once
executed the program it is named after.  The tool had been registered,
advertised and documented the whole time.

WHAT THIS CHECKER DECIDES — ONE RULE, STATED AS A SCOPE
-------------------------------------------------------
A path expression is IN SCOPE when all EIGHT hold:

  1. It is built ONLY from string literals, template literals, ``+``
     concatenation and calls spelled ``join`` / ``resolve`` over them, plus
     identifiers this file can bind to a definite string (see BINDINGS).
     Anything else evaluates to UNKNOWN.  An expression that NAMES a
     program file literally is still COLLECTED when it cannot be evaluated
     — a call carrying the filename as its own argument
     (``_runPyProgram("gate.py")``, ``R(here, ..., "gate.py")`` after
     ``const {resolve: R} = path``), and a WRITE whose right-hand side
     holds one (``let g = dir + "/gate.py"``, ``{ gate: dir + "/gate.py"
     }``).  Rewriting the builder under another name, spelling the
     declaration with another keyword or none, or burying it in an object
     literal therefore moves the site into the printed undecided list
     instead of deleting it from the report.
  2. Its value ends in ``.py``.
  3. It is not one of SEVERAL program paths written into one list literal
     while a live alternative among them is still possible.  A list of
     paths is a list of ALTERNATIVES and a member that is absent is what
     such a list is written for; a list holding ONE path is a spawn's argv,
     and that one must exist.  When every alternative in a list is decided
     and every one is dead, the probe falls through on every machine and
     each member is judged on its own.
  4. It does not resolve back inside the MCP server's own source directory
     — that is the helper area the server manages, not the program set it
     spawns.
  5. It is ROOTED AT THIS SOURCE FILE'S OWN DIRECTORY — i.e. the value
     changes when ``import.meta.url``'s directory changes.  Rooting is
     decided by evaluating the SAME expression a second time with that
     directory replaced by a marker, so it follows through every
     intermediate binding.
  6. It does not BRANCH, and it is not an operand of a branching
     initialiser.  ``||``, ``??`` and ``? :`` are NEVER resolved, in either
     direction — see NEVER RESOLVE THROUGH A BRANCH below.
  7. Its DIRECTORY is absent from the tree as well.  A file missing from a
     directory the tree DOES hold is undecided, not a finding — see KNOWN
     CONSERVATISM.
  8. It does not descend through a directory an install or a build
     PRODUCES (``vendor/``, ``.venv/``, ``node_modules/``,
     ``build/generated/``, …).  Such a directory is legitimately absent
     from a source checkout, so its absence says nothing.  The names are
     in ``_DERIVED_SEGMENTS``.  That list is NOT complete and is not
     claimed to be: it is the one part of this rule whose blind spot cuts
     BOTH ways.  Adding a name removes sites; a derived directory whose
     name is NOT in it stays decidable, and that is exactly where the
     wrong verdicts on ``vendor/`` and ``.venv/`` came from before this
     conjunct existed.

An in-scope path that names no existing file is a FAIL: the tool that
spawns it can never run.  Everything else is UNDECIDED — printed with its
file, line, expression and reason, never silently dropped and never a FAIL.

NEVER RESOLVE THROUGH A BRANCH
------------------------------
An earlier revision walked ``||`` / ``??`` chains and returned the first
alternative naming an EXISTING path.  That is not what JS computes: ``||``
yields its LEFT operand whenever that operand is truthy and every non-empty
string is truthy, so in ``dead || live`` the path the handler spawns is the
DEAD one.  Three measured consequences, on the real pre-fix source:

  * ``const gate = <dead> || (here + "/../../programs");`` — the chain
    evaluated to a directory, the declaration no longer looked like a
    program path, and the SITE VANISHED from the report.  Not a missed
    finding: one fewer place the run said it had looked, with no signal.
  * ``const gate = <dead> || <live>;`` — the run printed the site as
    DECIDED and RESOLVED to ``<live>``.  A green CERTIFICATE naming a path
    the running code never computes.
  * ``??`` was treated as ``||`` though it takes its right operand only for
    ``null`` / ``undefined`` — a second wrong model of a second operator.

So the evaluation is gone.  A branch evaluates to UNKNOWN, and any site
whose own expression branches, or that sits inside a WRITE whose right-hand
side branches, is UNDECIDED and is printed with that reason.  Both tests are
LEXICAL, taken on the masked source: a ``?`` in a comment or a string is not
there to be seen, and a ``?.`` is optional chaining, not a ternary.
``[c].find(existsSync)`` is still evaluated — it returns the first member
that exists, which is exactly what the runtime computes — but a ``find``
standing in a branching RHS is an operand of that branch and is undecided
with it.  Such an RHS is still COLLECTED on the program name it holds
(pattern 5 in ``collect_sites``), because a branch that deleted the site
from the report would be strictly worse than a disclosed blind spot.

Conjunct 5 is the SCOPE, and it is what keeps this sound.  A path built on a
hard-coded absolute prefix names some OTHER filesystem — a container image
root (``/foss/tools/...openroad...``), a scratch directory
(``/tmp/deck_<n>.py``) — and calling it dead would be a statement about a
machine this checker is not looking at.  Out of bounds BY CONSTRUCTION, not
by an editable list of names; and adding one more ``".."`` climbs further up
but is still rooted here, so it is still judged.

BINDINGS — WHERE A NAME'S VALUE COMES FROM
------------------------------------------
Two sources, both facts about the file rather than guesses:

  * ``import.meta.url``.  A name bound to ``dirname(... import.meta.url
    ...)`` IS this file's directory, wherever in the file that binding is
    written — one file has one URL, so this needs no scope analysis.
  * A WRITE to the name: ``const`` / ``let`` / ``var NAME = <rhs>``, or a
    plain ``NAME = <rhs>``.  Which keyword — or none — stands in front of
    the ``=`` says nothing about what the RHS builds, so one rule reads all
    four.  EVERY write in the file must agree on one definite string, or
    the name is DROPPED and bound to nothing.  That covers the rebindable
    keywords (``let dir = <absent>; if (!existsSync(dir)) dir = <live>;``
    is a layout probe and binds nothing) and the two-handlers case that
    ``const`` alone used to cover: a name a handler reads is written either
    in that handler — in which case this pass sees BOTH writes and drops it
    — or in an enclosing scope, where the single value is the right one.
    A PARAMETER DEFAULT is not one of these writes: a keyword-less ``=``
    closed by a bracket instead of a ``;`` (``({ dir = <x> }) =>``,
    ``f(dir = <x>)``) supplies no value, so a path assembled from an
    argument stays UNKNOWN.  The site is still collected and printed.

WHAT THIS CHECKER DOES **NOT** DECIDE
-------------------------------------
Read this before reading a PASS as an all-clear.  Every item in THIS list
under-reports and none of them can produce a wrong verdict on correct code.
The two places where a wrong verdict is still possible are named in KNOWN
CONSERVATISM below, not here.

  * **COULD-NOT-RUN IS NOT AN EXIT STATUS — NOT COVERED HERE.**  The second
    half of the original defect was the handler answering the could-not-run
    condition with a value in the exit-status domain::

        exitCode = r.error ? 1 : (r.status ?? 1);   // "never started" -> 1
        ...
        phase23_complete: exitCode === 0,           // ...which is now a verdict

    so "the program does not exist on this machine" and "the program ran
    and the project failed" left byte-identical evidence.  A real invariant,
    and this gate DOES NOT CHECK IT.  Deciding it needs dataflow — which
    receiver a spawn bound, what a helper returns, which fields downstream
    read — and every approximation by name heuristic (callee whitelist,
    write-API list, spawn-evidence by spelling) mis-fired on correct code in
    this very tree.  A PASS here says nothing about it.
  * A path that crosses a FUNCTION BOUNDARY.  ``_runPyProgram("gate.py")``
    hands a bare program NAME to a helper that builds the path from its own
    parameter; the name is not a path and the helper's candidates are not
    this call's.  Out of scope, undecided, and the reason is printed.
  * A file that binds ONE name both to its own directory and to something
    else.  Refused (CANNOT-CHECK), not decided: see ``discover_bindings``.
  * A handler PARAMETER, including one carrying a default — the zod form
    (``programs_dir: z.string().default(<module dir>)``) and the JS form
    (``async ({ programs_dir = <module dir> }) =>``) alike.  A parameter is
    not a binding this file declares; modelling one means modelling the
    handler's scope, which is the machinery this rule was cut back from.
    This is the biggest single blind spot by count — on the shipped server
    it is nine of the twenty-two undecided sites, and every one of them is
    printed.
  * A program name that is not statically fixed — assembled from a handler
    parameter, a loop over a runtime list, or ``Date.now()``.  Evaluates to
    UNKNOWN; printed.
  * A path expression that BRANCHES, or that is an operand of a branching
    write.  See NEVER RESOLVE THROUGH A BRANCH above and the first entry
    under KNOWN CONSERVATISM below.
  * A whole COMMAND LINE in one string (``python3 ${DIR}/gate.py --json -``)
    is not read as a path: the value names a command, and splitting shell
    text into arguments is guesswork this checker does not do.
  * A path a handler WRITES rather than spawns.  Telling a generator its own
    output "exists in no shipped layout" is a wrong verdict, and telling
    written from spawned apart needs the dataflow above.  Conjuncts 4, 5 and
    7 put the shapes that occur out of bounds instead: the venue's one
    generated helper goes to a scratch directory (not own-rooted), the
    server's own source tree is excluded outright, and a file created inside
    an existing directory is an absent MEMBER.  Measured on the venue: of
    the thirteen file-writing calls in these sources, none targets a
    ``.py``.
  * A builder spelled under ANOTHER NAME — aliased
    (``const {resolve: R} = path``) or wrapped in a local helper.  The
    value is UNKNOWN, so the site is undecided; conjunct 1 keeps it in the
    printed list rather than dropping it.
  * A path built inside an OBJECT LITERAL or any other RHS this evaluator
    does not read (``const o = { gate: dir + "/gate.py" };``).  The value is
    UNKNOWN and the site is undecided — collected, under conjunct 1, on the
    program name the RHS spells, so it is printed rather than dropped.
  * A list of alternatives in which even ONE member cannot be decided: a
    live alternative cannot be ruled out, so no member is failed.
  * A source file outside the scanned venue — ``*.js`` / ``*.mjs`` / ``*.cjs``
    under the MCP source directory.  A run over a venue holding none of these
    REFUSES; one that finds files but no program paths says so in its own
    denominator (``0 program-path site(s)``).

KNOWN CONSERVATISM — WHAT WAS GIVEN UP, AND WHY
-----------------------------------------------
Most of these are FALSE NEGATIVES the rule accepts on purpose, because the
alternative was a wrong verdict on code that works.  The FOURTH entry is not
one of those: it is the one remaining shape in this file that can still
produce a wrong verdict, and it is written down here rather than patched
because the patch opens a worse hole.  Read the whole list before reading a
PASS.

  * **A BRANCH DISARMS A FINDING, and says so.**  Appending ``|| x`` to a
    dead path, or wrapping it in a ternary, moves the site from FAIL to
    UNDECIDED and rc back to 0.  That is the accepted price of never
    resolving through a branch: the alternative was picking a side, and
    picking the wrong side certified a path the code never runs.  The site
    is still counted and still printed, with the branch named as the
    reason, so the edit shows up in the report rather than deleting the
    site from it.
  * **AN ABSENT MEMBER OF A PRESENT DIRECTORY IS NOT DECIDED** (conjunct 7).
    ``programs/optional_extra.py`` missing while ``programs/`` is right
    there is what an optional program guarded by ``if (!existsSync(p))
    return {skipped:true}`` looks like, what a read inside ``try`` /
    ``catch`` with a working fallback looks like, and what a file produced
    on first use looks like.  Telling those from a defect needs the
    dataflow this checker does not carry, and a guard-detector written
    against the guards that happen to be in this tree would mis-fire on the
    next one.  The cost is real: deleting a program from ``programs/`` is
    now undecided, not a finding.  The defect this gate exists for — a path
    naming a LAYOUT that is not there — is untouched by it, because the
    layout's directory is absent too.
  * **A DERIVED TREE IS NOT DECIDED** (conjunct 8), and that exemption is a
    LIST OF NAMES, not a construction.  Moving a program path under
    ``vendor/`` is therefore a one-line way to make a site undecided.  It
    stays printed.
  * **A BRANCH OVER NAMES WRITTEN ELSEWHERE IS NOT SEEN.**
    ``const A = join(...); const B = join(...); const p = existsSync(A) ? A
    : B;`` — ``A``'s own write does not branch, so if ``A`` names a layout
    that is absent it is still a FINDING.  Writing ``A`` with ``let``
    changes nothing here: the veto is a SECOND write, not the keyword.  This
    is the one shape in this file that can still produce a wrong verdict on
    working code.  It is not closed here because following identifiers INTO
    branches would let a single inserted line — ``const _ = c ? gate :
    gate;`` — silence any finding in the file, which is a worse hole than
    the one it shuts.  The venue writes this probe as an ARRAY
    (``_programsCandidates``), and conjunct 3 covers the array form.
  * **THE SHIPPED TREE CURRENTLY DECIDES NOTHING.**  Every program path in
    it is built from ``VIBE_IC_PROGRAMS_DIR``, chosen at runtime by
    ``process.env.… || <probe> || <fallback>``.  A run over it reports
    ``0 DECIDED``, and the verdict line says so rather than "every program
    path resolves": those paths depend on an environment variable and an
    existence probe, and the earlier "6 resolved" was the branch walk
    guessing.  The defect class this gate guards — a hard-coded climb out of
    this file's own directory into a layout that does not exist — remains
    decidable, which is what the pre-fix regression test measures.

COMMENTS AND STRINGS CANNOT MOVE THIS GATE
------------------------------------------
Every structural decision is taken on a MASKED view of the source in which
comments are blanked and string / template / regex-literal CONTENT is
blanked, with byte offsets and line numbers preserved exactly.  A sentence
in a comment cannot create a finding and cannot clear one; a program name
mentioned in prose is not a call site.  The literal VALUES used to resolve
a path are read back from the original bytes at the offsets the masked scan
identified — i.e. from positions that are code by construction.

There is no suppression comment, no skip list, no per-file opt-out, and no
token that certifies anything.  The only way to change a verdict is to
change the path expression, and a changed path expression is reported at
its own file and line either as a finding or as an undecided site.

Usage:
    python3 mcp_tool_program_path_resolves_check.py <plugin_root> [--json OUT]
                                                    [--src-dir REL]

Exit codes:
    0  PASS        — every in-scope path resolved
    1  FAIL        — at least one in-scope path names no file, each named
    2  CANNOT-CHECK — the input needed was absent or unparseable, OR this
                     checker itself raised.  NOT a pass and NOT a fail: a
                     scanner bug must not impersonate a finding, so an
                     unexpected exception is caught and REFUSED rather than
                     ending the process with the same rc a real FAIL uses.

chip-AGNOSTIC.
"""
from __future__ import annotations

# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` — how
# the gates, the wiring audit and much of the suite load a program — it does
# not, so every bare sibling import below raises ModuleNotFoundError. Restore
# the condition the file is written for. Idempotent, and the same shape the
# sibling programs that already carry it use.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------

import argparse
import json
import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

RC_PASS, RC_FAIL, RC_CANNOT_CHECK = 0, 1, 2

#: How far past a write's `=` the RHS scan will look for its `;`.
_CONST_RHS_SCAN_CAP = 4000

CHECK_NAME = "mcp_tool_program_path_resolves_check"

#: Default venue, relative to the plugin root: the MCP server sources.
DEFAULT_SRC_DIR = "mcp-eda/src"
_SRC_SUFFIXES = (".js", ".mjs", ".cjs")

#: A program is a Python file; that is what these handlers spawn.
_PROGRAM_SUFFIX = ".py"

#: The server's own source directory is where it keeps the helpers it
#: MANAGES — reads at startup, ships beside itself, or generates.  The
#: PROGRAMS it spawns live outside it.  A `.py` resolving back inside the
#: sources is therefore out of this gate's subject: telling a generator that
#: its own output "exists in no shipped layout" is a wrong verdict, and
#: telling them apart needs dataflow this checker does not carry.

#: Functions that join path segments, by the spellings the sources use.
_PATH_JOIN_FNS = frozenset({"join", "resolve", "path.join", "path.resolve",
                            "posix.join", "path.posix.join"})

#: Comparison operators the evaluator knows it cannot fold; an expression
#: containing one becomes UNKNOWN rather than being guessed at.
_COMPARE_OPS = ("===", "!==", "==", "!=", ">=", "<=", ">", "<")

# ===========================================================================
# A JS scanner that masks comments and literal CONTENT, preserving offsets.
# ===========================================================================

class UNKNOWN:
    """Sentinel: this expression is not statically determined."""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<UNKNOWN>"


_UNKNOWN = UNKNOWN()

# A `/` opens a regex literal only where a VALUE may begin.  After an
# identifier, a number, or a closing bracket, it is division.
_REGEX_OK_AFTER = set("(,=:[!&|?{};+-*%^~<>") | {""}
_REGEX_OK_KEYWORDS = frozenset({"return", "typeof", "case", "in", "of",
                                "new", "delete", "void", "instanceof",
                                "do", "else", "yield", "await"})


@dataclass
class ScanResult:
    masked: str
    #: start offset -> decoded value, for plain string literals
    strings: Dict[int, str] = field(default_factory=dict)
    #: start offset -> [("lit", text) | ("expr", (start, end))], for templates
    templates: Dict[int, List[Tuple[str, Any]]] = field(default_factory=dict)
    balanced: bool = True


def _decode(raw: str) -> str:
    """Decode JS string escapes.

    The NUMERIC escapes are decoded, not skipped over.  ``"doc\\x5Fextract.py"``
    is a legal spelling of a path that EXISTS; a decoder that dropped the
    ``\\x`` and kept the digits produced ``docx5Fextract.py``, and this gate
    would then have called a live program dead — a wrong verdict on working
    code, which is the one thing it must never do.  An escape that is still
    unrecognised keeps the character after the backslash, which is exactly
    what JS itself does with ``\\q``.
    """
    out: List[str] = []
    i = 0
    simple = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f",
              "v": "\v", "0": "\0",
              "\\": "\\", "'": "'", '"': '"', "`": "`", "$": "$"}
    while i < len(raw):
        c = raw[i]
        if c != "\\" or i + 1 >= len(raw):
            out.append(c)
            i += 1
            continue
        nxt = raw[i + 1]
        if nxt == "x" and re.fullmatch(r"[0-9a-fA-F]{2}", raw[i + 2:i + 4]):
            out.append(chr(int(raw[i + 2:i + 4], 16)))
            i += 4
            continue
        if nxt == "u" and raw[i + 2:i + 3] == "{":
            close = raw.find("}", i + 3)
            body = raw[i + 3:close] if close > 0 else ""
            if body and re.fullmatch(r"[0-9a-fA-F]{1,6}", body):
                try:
                    out.append(chr(int(body, 16)))
                    i = close + 1
                    continue
                except ValueError:
                    pass
        if nxt == "u" and re.fullmatch(r"[0-9a-fA-F]{4}", raw[i + 2:i + 6]):
            out.append(chr(int(raw[i + 2:i + 6], 16)))
            i += 6
            continue
        out.append(simple.get(nxt, nxt))
        i += 2
    return "".join(out)


def scan_js(src: str) -> ScanResult:
    """Mask comments and literal content; record literal values and offsets.

    The returned ``masked`` string has the same length as ``src`` and the
    same newlines, so every offset and every line number is preserved.  All
    structural matching in this checker runs on ``masked`` — that is the
    whole point: a comment or a prose string can neither create a finding
    nor clear one.
    """
    n = len(src)
    masked = list(src)
    strings: Dict[int, str] = {}
    templates: Dict[int, List[Tuple[str, Any]]] = {}

    def blank(a: int, b: int) -> None:
        for k in range(a, min(b, n)):
            if masked[k] != "\n":
                masked[k] = " "

    # Stack of open template literals.  Each entry:
    #   {"start", "parts", "lit_start", "subst_depth" or None}
    tmpl_stack: List[Dict[str, Any]] = []
    prev_sig = ""        # last significant character emitted into masked
    prev_word = ""       # last identifier-ish word, for regex disambiguation
    depth_paren = 0
    depth_brace = 0
    depth_brack = 0
    i = 0

    while i < n:
        c = src[i]

        # --- inside a template literal's TEXT ------------------------------
        if tmpl_stack and tmpl_stack[-1]["subst_depth"] is None:
            top = tmpl_stack[-1]
            if c == "\\":
                blank(i, i + 2)
                i += 2
                continue
            if c == "`":
                top["parts"].append(("lit", _decode(src[top["lit_start"]:i])))
                templates[top["start"]] = top["parts"]
                tmpl_stack.pop()
                prev_sig = "`"
                prev_word = ""
                i += 1
                continue
            if c == "$" and i + 1 < n and src[i + 1] == "{":
                top["parts"].append(("lit", _decode(src[top["lit_start"]:i])))
                top["subst_depth"] = 0
                top["subst_start"] = i + 2
                prev_sig = "{"
                prev_word = ""
                i += 2
                continue
            if c != "\n":
                masked[i] = " "
            i += 1
            continue

        # --- code (possibly inside a ${...} substitution) ------------------
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            j = n if j < 0 else j
            blank(i, j)
            i = j
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            blank(i, j)
            i = j
            continue
        if c == "/" and (prev_sig in _REGEX_OK_AFTER
                         or prev_word in _REGEX_OK_KEYWORDS):
            # regex literal: blank its body, keep the delimiters
            j = i + 1
            in_class = False
            while j < n:
                d = src[j]
                if d == "\\":
                    j += 2
                    continue
                if d == "\n":
                    break
                if d == "[":
                    in_class = True
                elif d == "]":
                    in_class = False
                elif d == "/" and not in_class:
                    break
                j += 1
            if j < n and src[j] == "/":
                blank(i + 1, j)
                k = j + 1
                while k < n and src[k].isalpha():
                    k += 1
                blank(j + 1, k)
                prev_sig = "/"
                prev_word = ""
                i = k
                continue
            # not a terminated regex after all; fall through as an operator
        if c in ("'", '"'):
            j = i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == c or src[j] == "\n":
                    break
                j += 1
            strings[i] = _decode(src[i + 1:j])
            blank(i + 1, j)
            prev_sig = c
            prev_word = ""
            i = min(j + 1, n)
            continue
        if c == "`":
            tmpl_stack.append({"start": i, "parts": [], "lit_start": i + 1,
                               "subst_depth": None})
            i += 1
            continue
        if c == "{":
            depth_brace += 1
            if tmpl_stack and tmpl_stack[-1]["subst_depth"] is not None:
                tmpl_stack[-1]["subst_depth"] += 1
        elif c == "}":
            if tmpl_stack and tmpl_stack[-1]["subst_depth"] is not None:
                top = tmpl_stack[-1]
                if top["subst_depth"] == 0:
                    # closes the `${`, which was never counted as a brace
                    top["parts"].append(("expr", (top["subst_start"], i)))
                    top["subst_depth"] = None
                    top["lit_start"] = i + 1
                    prev_sig = "}"
                    prev_word = ""
                    i += 1
                    continue
                top["subst_depth"] -= 1
            depth_brace -= 1
        elif c == "(":
            depth_paren += 1
        elif c == ")":
            depth_paren -= 1
        elif c == "[":
            depth_brack += 1
        elif c == "]":
            depth_brack -= 1

        if not c.isspace():
            prev_sig = c
            if c.isalnum() or c in "_$":
                k = i
                while k > 0 and (src[k - 1].isalnum() or src[k - 1] in "_$"):
                    k -= 1
                m = re.match(r"[A-Za-z_$][\w$]*", src[k:i + 1])
                prev_word = m.group(0) if m else ""
            else:
                prev_word = ""
        i += 1

    balanced = (depth_paren == 0 and depth_brace == 0 and depth_brack == 0
                and not tmpl_stack)
    return ScanResult("".join(masked), strings, templates, balanced)


# ===========================================================================
# A tiny JS expression evaluator over the masked source + literal table.
# ===========================================================================

_TOKEN_RE = re.compile(
    r"""
      (?P<ws>\s+)
    | (?P<ident>[A-Za-z_$][\w$]*)
    | (?P<num>0[xX][0-9a-fA-F_]+|\d[\d_]*(?:\.\d[\d_]*)?)
    | (?P<str>'|")
    | (?P<tmpl>`)
    | (?P<punct>\?\?|===|!==|==|!=|>=|<=|&&|\|\||=>|\.\.\.|[-+*/%?:.,()\[\]{};<>!=&|~^])
    """,
    re.VERBOSE,
)


@dataclass
class Tok:
    kind: str
    text: str
    start: int
    end: int
    value: Any = None


def tokenize(scan: ScanResult, lo: int, hi: int) -> List[Tok]:
    """Tokenize ``masked[lo:hi]``.  String / template tokens carry their
    decoded value, looked up by the offset the scan recorded."""
    toks: List[Tok] = []
    s = scan.masked
    i = lo
    while i < hi:
        m = _TOKEN_RE.match(s, i)
        if not m:
            i += 1
            continue
        if m.lastgroup == "ws":
            i = m.end()
            continue
        if m.lastgroup == "str":
            q = s[i]
            j = i + 1
            while j < hi and s[j] != q:
                j += 1
            toks.append(Tok("str", s[i:j + 1], i, j + 1,
                            scan.strings.get(i, _UNKNOWN)))
            i = j + 1
            continue
        if m.lastgroup == "tmpl":
            parts = scan.templates.get(i)
            if parts is None:
                i += 1
                continue
            # find the end: the matching closing backtick recorded by the scan
            j = i + 1
            depth = 0
            while j < hi:
                if s[j] == "{":
                    depth += 1
                elif s[j] == "}":
                    depth -= 1
                elif s[j] == "`" and depth <= 0:
                    break
                j += 1
            toks.append(Tok("tmpl", s[i:j + 1], i, j + 1, parts))
            i = j + 1
            continue
        kind = "ident" if m.lastgroup == "ident" else (
            "num" if m.lastgroup == "num" else "punct")
        val = None
        if kind == "num":
            try:
                txt = m.group().replace("_", "")
                val = int(txt, 16) if txt[:2].lower() == "0x" else float(txt)
            except ValueError:
                val = _UNKNOWN
        toks.append(Tok(kind, m.group(), m.start(), m.end(), val))
        i = m.end()
    return toks


class _Parser:
    """Recursive-descent over the subset of JS these path expressions use.

    Anything outside the subset evaluates to ``_UNKNOWN`` and propagates —
    so an expression this parser does not understand is DISCLOSED as
    unresolved, never reported as a dead path.
    """

    def __init__(self, toks: Sequence[Tok], scan: ScanResult,
                 bindings: Dict[str, Any], resolver: "PathResolver"):
        self.t = list(toks)
        self.i = 0
        self.scan = scan
        self.b = bindings
        self.r = resolver

    # -- token helpers --
    def peek(self, k: int = 0) -> Optional[Tok]:
        j = self.i + k
        return self.t[j] if 0 <= j < len(self.t) else None

    def at(self, text: str) -> bool:
        tk = self.peek()
        return tk is not None and tk.text == text

    def eat(self, text: str) -> bool:
        if self.at(text):
            self.i += 1
            return True
        return False

    # -- grammar --
    def parse(self) -> Any:
        v = self.conditional()
        return v

    def conditional(self) -> Any:
        """``A ? B : C`` — NOT RESOLVED, in either direction.

        Both arms are consumed so the parse stays in step; the value is
        UNKNOWN.  See NEVER RESOLVE THROUGH A BRANCH in the module
        docstring for why picking an arm is worse than declining to.
        """
        cond = self.logical_or()
        if self.eat("?"):
            self.conditional()
            if not self.eat(":"):
                return _UNKNOWN
            self.conditional()
            return _UNKNOWN
        return cond

    def logical_or(self) -> Any:
        """``A || B``, ``A ?? B`` — NOT RESOLVED, in either direction.

        The chain is consumed and the value is UNKNOWN.  See NEVER RESOLVE
        THROUGH A BRANCH in the module docstring for the three measured
        consequences of the walk this replaced.
        """
        v = self.logical_and()
        while self.at("||") or self.at("??"):
            self.i += 1
            self.logical_and()
            v = _UNKNOWN
        return v

    def logical_and(self) -> Any:
        v = self.equality()
        while self.at("&&"):
            self.i += 1
            self.equality()
            v = _UNKNOWN
        return v

    def equality(self) -> Any:
        v = self.additive()
        while self.peek() and self.peek().text in _COMPARE_OPS:
            self.i += 1
            self.additive()
            v = _UNKNOWN
        return v

    def additive(self) -> Any:
        v = self.unary()
        while self.at("+") or self.at("-"):
            op = self.peek().text
            self.i += 1
            rhs = self.unary()
            if op == "+" and isinstance(v, str) and isinstance(rhs, str):
                v = v + rhs
            else:
                v = _UNKNOWN
        return v

    def unary(self) -> Any:
        if self.at("!") or self.at("-") or self.at("~") or self.at("+"):
            self.i += 1
            self.unary()
            return _UNKNOWN
        return self.postfix()

    def postfix(self) -> Any:
        val, name = self.primary()
        while True:
            if self.at("."):
                self.i += 1
                tk = self.peek()
                if tk is None or tk.kind != "ident":
                    return _UNKNOWN
                self.i += 1
                member = tk.text
                if self.at("("):
                    args = self.arglist()
                    val = self.call(name, member, val, args)
                    name = f"{name}.{member}" if name else member
                else:
                    name = f"{name}.{member}" if name else member
                    val = self.b.get(name, _UNKNOWN) if name in self.b \
                        else _UNKNOWN
                continue
            if self.at("("):
                args = self.arglist()
                val = self.call(name, None, val, args)
                name = ""
                continue
            if self.at("["):
                self.i += 1
                idx = self.conditional()
                if not self.eat("]"):
                    return _UNKNOWN
                if isinstance(val, list) and isinstance(idx, float) \
                        and float(idx).is_integer() and 0 <= int(idx) < len(val):
                    val = val[int(idx)]
                else:
                    val = _UNKNOWN
                name = ""
                continue
            return val

    def arglist(self) -> List[Any]:
        assert self.eat("(")
        args: List[Any] = []
        if self.eat(")"):
            return args
        while True:
            args.append(self.conditional())
            if self.eat(","):
                if self.eat(")"):      # trailing comma before the paren
                    return args
                continue
            self.eat(")")
            return args

    def call(self, name: str, member: Optional[str], recv: Any,
             args: List[Any]) -> Any:
        full = f"{name}.{member}" if (name and member) else (member or name)
        if full in _PATH_JOIN_FNS or (member in ("join", "resolve")
                                      and member is not None):
            if not args or any(not isinstance(a, str) for a in args):
                return _UNKNOWN
            joined = posixpath.join(*args)
            return posixpath.normpath(joined)
        if member == "endsWith" and isinstance(recv, str) \
                and len(args) == 1 and isinstance(args[0], str):
            return recv.endswith(args[0])
        if member == "startsWith" and isinstance(recv, str) \
                and len(args) == 1 and isinstance(args[0], str):
            return recv.startswith(args[0])
        if member == "find" and isinstance(recv, list):
            # `candidates.find(existsSync)` — the runtime's own probe.
            for c in recv:
                if isinstance(c, str) and self.r.exists(c):
                    return c
            return _UNKNOWN
        return _UNKNOWN

    def primary(self) -> Tuple[Any, str]:
        tk = self.peek()
        if tk is None:
            return _UNKNOWN, ""
        if tk.kind == "str":
            self.i += 1
            return tk.value, ""
        if tk.kind == "tmpl":
            self.i += 1
            return self.eval_template(tk.value), ""
        if tk.kind == "num":
            self.i += 1
            return tk.value, ""
        if tk.text == "(":
            self.i += 1
            v = self.conditional()
            self.eat(")")
            return v, ""
        if tk.text == "[":
            self.i += 1
            items: List[Any] = []
            if self.eat("]"):
                return items, ""
            while True:
                items.append(self.conditional())
                if self.eat(","):
                    if self.eat("]"):
                        return items, ""
                    continue
                self.eat("]")
                return items, ""
        if tk.kind == "ident":
            self.i += 1
            if tk.text in ("true", "false"):
                return (tk.text == "true"), ""
            if tk.text in self.b:
                return self.b[tk.text], tk.text
            return _UNKNOWN, tk.text
        self.i += 1
        return _UNKNOWN, ""

    def eval_template(self, parts: Sequence[Tuple[str, Any]]) -> Any:
        out: List[str] = []
        for kind, payload in parts:
            if kind == "lit":
                out.append(payload)
                continue
            lo, hi = payload
            sub = _Parser(tokenize(self.scan, lo, hi), self.scan, self.b, self.r)
            v = sub.parse()
            if not isinstance(v, str):
                return _UNKNOWN
            out.append(v)
        return "".join(out)


class PathResolver:
    """Answers 'does this path exist', anchored at the real layout."""

    def __init__(self, plugin_root: Path):
        self.plugin_root = Path(plugin_root)

    def exists(self, p: str) -> bool:
        if not isinstance(p, str) or not p:
            return False
        try:
            q = posixpath.normpath(p)
            # A RELATIVE candidate is relative to the tree being judged, not
            # to whatever directory the caller happened to be standing in.
            # Resolving it against the process CWD made the same tree answer
            # differently from two shells — a verdict must not depend on
            # where it was invoked from.
            here = Path(q) if posixpath.isabs(q) else (self.plugin_root / q)
            return here.exists()
        except OSError:
            return False


def eval_range(scan: ScanResult, lo: int, hi: int, bindings: Dict[str, Any],
               resolver: PathResolver) -> Any:
    return _Parser(tokenize(scan, lo, hi), scan, bindings, resolver).parse()


# ===========================================================================
# Findings
# ===========================================================================


@dataclass
class Finding:
    rule: str
    file: str
    line: int
    message: str

    def as_line(self) -> str:
        return f"{self.file}:{self.line}: [{self.rule}] {self.message}"


@dataclass
class Site:
    file: str
    line: int
    expr: str
    resolved: Any
    #: Why this site carries no verdict, when it carries none.  A site is
    #: only ever DECIDED when this is None.
    undecided: Optional[str] = None



def line_of(src: str, off: int) -> int:
    return src.count("\n", 0, off) + 1


def _balanced_end(masked: str, open_off: int) -> int:
    """Offset just past the bracket opened at ``open_off``."""
    pairs = {"(": ")", "[": "]", "{": "}"}
    opener = masked[open_off]
    closer = pairs[opener]
    depth = 0
    i = open_off
    while i < len(masked):
        if masked[i] == opener:
            depth += 1
        elif masked[i] == closer:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(masked)


# ===========================================================================
# Binding discovery
# ===========================================================================

_DIRNAME_BINDING_RE = re.compile(
    r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=[^;\n]*"
    r"\bdirname\s*\([^;]*import\.meta\.url")
#: The un-named form: `path.dirname(new URL(import.meta.url).pathname)`.
_URL_DIRNAME_RE = re.compile(
    r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
    r"[\w$.]*dirname\s*\(\s*new\s+URL\s*\(\s*import\.meta\.url\s*\)"
    r"\s*\.\s*pathname\s*\)")
#: A WRITE to a name: `const` / `let` / `var NAME = <rhs>`, or an assignment
#: to a name already bound.  ONE regex for all four spellings, because which
#: keyword — or none — stands in front of the `=` says nothing about what the
#: RHS builds.  `==`, `===` and `=>` are not writes, and `o.p = …` writes a
#: PROPERTY, not a name this file binds.
_WRITE_RE = re.compile(r"(?<![.\w$])(?:(const|let|var)\s+)?"
                       r"([A-Za-z_$][\w$]*)\s*[-+*/%&|^?]{0,2}=(?![=>])")
_ARRAY_DECL_RE = re.compile(
    r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*\[")

#: The marker this file's own directory is replaced by when an expression is
#: re-evaluated to ask "is this path rooted in THIS source tree?".  The
#: trailing filler components exist so that a `resolve(here, "..", "..",
#: ...)` chain — which is how every one of these sources climbs out of
#: `mcp-eda/src` — cannot normalise the marker away: without them,
#: `normpath("/marker/../../programs")` is `/programs` and every correctly
#: anchored path in the tree would read as "rooted somewhere else".
_ANCHOR_MARK = "__mcp_own_source_dir_anchor__"
_ANCHOR_SENTINEL = "/" + _ANCHOR_MARK + "/_anchor_pad" * 16


@dataclass
class Decl:
    """One write — `[const|let|var] NAME = <rhs>` — and its RHS's value."""
    name: str
    rhs_lo: int
    rhs_hi: int
    value: Any


def _decl_rhs_span(masked: str, lo: int) -> int:
    """End of a write's RHS: its own depth-0 `;`.

    A newline is NOT a terminator: these sources wrap their `||` chains
    across lines, and cutting at the first newline evaluated only the first
    alternative — which is how a chain whose later alternatives carry the
    real value read as unresolvable.
    """
    hi = lo
    depth = 0
    limit = min(len(masked), lo + _CONST_RHS_SCAN_CAP)
    while hi < limit:
        ch = masked[hi]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0:
                break
            depth -= 1
        elif ch == ";" and depth == 0:
            break
        hi += 1
    return hi


def discover_bindings(scan: ScanResult, src_file: Path,
                      resolver: PathResolver,
                      own_dir: Optional[str] = None) -> Tuple[Dict[str, Any],
                                                              List[Decl],
                                                              List[str]]:
    """Bind the names this file declares, file-wide.  Return (bindings, decls).

    ``import.meta.url`` is not guessed: it IS this file's own location, so
    any identifier bound to ``dirname(... import.meta.url ...)`` is bound to
    the directory the source actually sits in.  Passing ``own_dir`` replaces
    that location with a marker, which is how a second pass answers "is this
    expression ROOTED in this source tree, or in some other filesystem's
    namespace?" without a separate taint analysis.

    A name whose writes do not all agree on one definite string is dropped.
    See BINDINGS in the module docstring for why that replaces scope
    modelling.

    The third return value names any identifier this file binds BOTH to its
    own directory AND to a different definite string.  That is the one
    contradiction this checker cannot resolve without scope analysis, and
    resolving it either way is unacceptable: preferring the anchor can flag
    a path the flagged line never computes, and preferring the literal lets
    ONE inserted write silence a real finding.  It is reported to the
    caller, which REFUSES — CANNOT-CHECK is not a pass and not a fail.
    """
    masked = scan.masked
    own = own_dir if own_dir is not None else str(src_file.parent)

    anchored: Dict[str, Any] = {}
    for rx in (_DIRNAME_BINDING_RE, _URL_DIRNAME_RE):
        for m in rx.finditer(masked):
            anchored[m.group(1)] = own

    bindings: Dict[str, Any] = dict(anchored)
    decls: List[Decl] = []
    # Two passes: enough for the one level of nesting these sources use (an
    # array of paths built from a const declared above it, then a name bound
    # to the first member of that array that exists).
    for _rnd in range(2):
        for m in _ARRAY_DECL_RE.finditer(masked):
            name = m.group(1)
            open_off = masked.find("[", m.end() - 1)
            if open_off < 0:
                continue
            val = eval_range(scan, open_off, _balanced_end(masked, open_off),
                             bindings, resolver)
            if isinstance(val, list):
                bindings[name] = val

        decls = []
        seen: Dict[str, List[Any]] = {}
        for m in _WRITE_RE.finditer(masked):
            name = m.group(2)
            if isinstance(bindings.get(name), list):
                continue
            r_lo = m.end()
            r_hi = _decl_rhs_span(masked, r_lo)
            val = eval_range(scan, r_lo, r_hi, bindings, resolver)
            decls.append(Decl(name, r_lo, r_hi, val))
            # A keyword-less write whose RHS is closed by a BRACKET rather
            # than by `;` is a PARAMETER DEFAULT (`({ dir = <x> }) =>`,
            # `f(dir = <x>)`), not a statement — and a parameter is not a
            # binding this file declares.  It stays in `decls`, so the site
            # is still collected and printed; it just supplies no value.
            if m.group(1) or masked[r_hi:r_hi + 1] == ";":
                seen.setdefault(name, []).append(val)
        for name, vals in seen.items():
            # EVERY write to the name must agree on one definite string.
            # `let` and `var` rebind and `x = …` rebinds anything, so a name
            # written twice — or written once to a value this evaluator
            # could not read — is not a value the flagged line computes.
            agreed = {v for v in vals if isinstance(v, str) and v}
            if len(agreed) == 1 and all(isinstance(v, str) and v
                                        for v in vals):
                bindings[name] = agreed.pop()
            else:
                bindings.pop(name, None)
        # The own-dir anchor is a FACT about this file, so it wins over a
        # declaration the evaluator could not read (`const here =
        # path.dirname(...)` is UNKNOWN to the evaluator, and it must not
        # un-bind the very name the anchor knows).  But a declaration that
        # DOES read, to a different definite value, CONTRADICTS the anchor:
        # the name then means two things in this file and the checker binds
        # it to neither.  Preferring the anchor there would substitute a
        # value the flagged line never computes.
        contradicted = []
        for name, own_val in anchored.items():
            other = [v for v in seen.get(name, ())
                     if isinstance(v, str) and v and v != own_val]
            if other:
                bindings.pop(name, None)
                contradicted.append(f"{name} (also bound to {other[0]!r})")
            else:
                bindings[name] = own_val
    return bindings, decls, contradicted


def _is_own_tree(anchored: Any) -> bool:
    """Did this expression's value come from THIS file's own directory?"""
    if isinstance(anchored, str):
        return _ANCHOR_MARK in anchored
    # Undetermined under the anchor pass.  The real pass will be UNKNOWN too
    # and the site is reported as undecided either way; keeping it here means
    # the reason printed is the accurate one.
    return True


# ===========================================================================
# Site collection: every expression in a source that names a program file
# ===========================================================================

_OUT_OF_SCOPE = ("rooted at a hard-coded absolute prefix, not at this source "
                 "tree — it names a filesystem this checker is not looking at")
_NOT_STATIC = "not statically determined"

#: What a program FILENAME looks like, as opposed to a sentence that happens
#: to mention one.  A tool description saying "runs foo.py" is prose.
_FILENAME_RE = re.compile(r"[\w.@+-]+(?:/[\w.@+-]+)*\.py")
_IN_LIST = ("one of several program paths in a single list literal — a list "
            "that holds MORE THAN ONE path holds ALTERNATIVES, and a member "
            "that is absent is what such a list is written for")
_INSIDE_SOURCES = ("resolves back inside the MCP server's own source "
                   "directory — that is the server's helper area, not the "
                   "program set it spawns, and this gate says nothing "
                   "about what lives there")
_BRANCHED = ("the expression BRANCHES (`||`, `??` or `? :`) — this checker "
             "never resolves through a branch, in either direction, because "
             "the operand that wins is a runtime fact and naming the losing "
             "one would certify a path the code never computes")
_ABSENT_MEMBER = ("names a file that is absent from a directory this tree DOES "
                  "hold — an absent member of a present directory is what an "
                  "optional program, a probed extra and a file produced on "
                  "first use all look like, and telling those from a defect "
                  "needs dataflow this checker does not carry")
_DERIVED = ("crosses a directory that an install or a build PRODUCES, so its "
            "absence from a source checkout says nothing about whether the "
            "tool can reach it on an installed tree")

#: Directory names whose contents are produced by an install or a build rather
#: than committed.  A LIST OF NAMES, not a construction, and NOT exhaustive —
#: it is the one part of this rule whose blind spot cuts both ways.  Adding a
#: name removes sites from the decided set; a derived directory whose name is
#: absent from it stays decidable, and that is where the wrong verdicts on
#: `vendor/` and `.venv/` came from before this existed.  Matched as a whole
#: path SEGMENT, so `vendored_utils/` is not `vendor/`.
_DERIVED_SEGMENTS = frozenset({
    "node_modules", "vendor", "venv", ".venv", "site-packages",
    "build", "dist", "generated", "target", "__pycache__", ".tox", ".cache",
    ".eggs",
})

#: A branch operator in CODE.  `?.` is optional chaining, not a ternary, and
#: `??` is matched as one token so its second `?` is not read as a ternary.
#: Run over the MASKED source, so a `?` inside a comment, a string or a regex
#: body is not there to be seen.
_BRANCH_RE = re.compile(r"\|\||\?\?|\?(?![.?])")


def _branches(masked: str, lo: int, hi: int) -> bool:
    """Does this span contain a branch this checker refuses to resolve?"""
    return _BRANCH_RE.search(masked, lo, hi) is not None


def _crosses_derived(path_value: str) -> bool:
    """Does this path descend through a directory an install or build makes?"""
    return any(seg in _DERIVED_SEGMENTS
               for seg in posixpath.normpath(path_value).split("/"))


def _depth_between(masked: str, open_off: int, off: int) -> int:
    """Bracket nesting at ``off``, counted from the bracket at ``open_off``."""
    depth = 0
    for ch in masked[open_off:off]:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
    return depth


def _list_spans(masked: str) -> List[Tuple[int, int]]:
    """Every `[` ... `]` span in the source, at any depth.

    Used to find lists holding SEVERAL program paths.  Such a list is a list
    of ALTERNATIVES — every candidate list in these sources exists precisely
    because some of its members are expected to be absent on any given
    machine — so calling one member dead is calling the idiom a defect.

    A list holding exactly ONE program path is not an alternation: it is the
    argv of a spawn call (``[script, projectDir, "--json"]``), and that
    script must exist.  Counting is what separates the two, and it needs no
    list of existence-testing function names and no group bookkeeping.  The
    cut can only ever REMOVE a site, never create a finding.
    """
    spans: List[Tuple[int, int]] = []
    stack: List[int] = []
    for i, ch in enumerate(masked):
        if ch == "[":
            stack.append(i)
        elif ch == "]" and stack:
            spans.append((stack.pop(), i + 1))
    return spans


def collect_sites(scan: ScanResult, src: str, rel: str, src_root: str,
                  bindings: Dict[str, Any], anchor: Dict[str, Any],
                  decls: Sequence[Decl], resolver: PathResolver) -> List[Site]:
    masked = scan.masked
    sites: List[Site] = []
    claimed: List[int] = []
    lists = _list_spans(masked)
    # WRITES whose right-hand side BRANCHES.  A path expression nested in one
    # is an OPERAND of that branch — `existsSync(LEGACY) ? LEGACY : CURRENT`
    # is how this venue probes for a layout deliberately absent on most
    # installs — so it is no more decidable than the branch itself.  Read off
    # the masked source rather than off `decls`, which drops names bound to
    # arrays: whether an RHS branches is a fact about the text.
    branch_spans: List[Tuple[int, int]] = []
    for _m in _WRITE_RE.finditer(masked):
        _lo, _hi = _m.end(), _decl_rhs_span(masked, _m.end())
        if _branches(masked, _lo, _hi):
            branch_spans.append((_lo, _hi))

    def add(lo: int, hi: int) -> None:
        if lo in claimed:
            return
        claimed.append(lo)
        # DECIDED on `masked`, DISPLAYED from the original: every offset used
        # here came from the masked scan, so it is code by construction, and
        # showing the real bytes is what makes a finding actionable.
        expr = " ".join(src[lo:hi].split())[:160]
        val = eval_range(scan, lo, hi, bindings, resolver)
        if isinstance(val, str) and val:
            # `join`/`resolve` normalise; a template or a `+` chain does not,
            # so the same path arrived here spelled two ways.  Comparing the
            # UN-normalised spelling against the source directory said a path
            # climbing out of it with `../..` was still inside it, and
            # rewriting the expression as a template bought a green.
            val = posixpath.normpath(val)
        aval = eval_range(scan, lo, hi, anchor, resolver)
        why = None
        if _branches(masked, lo, hi) or any(a <= lo < b
                                            for a, b in branch_spans):
            # Asked FIRST, and lexically rather than from the value: a
            # branching expression has no single value to report, so the
            # accurate reason for the reader is the branch itself, not the
            # UNKNOWN it produced.
            why = _BRANCHED
        elif not isinstance(val, str):
            why = _NOT_STATIC
        elif not _is_own_tree(aval):
            why = _OUT_OF_SCOPE
        elif val == src_root or val.startswith(src_root.rstrip("/") + "/"):
            why = _INSIDE_SOURCES
        elif _crosses_derived(val):
            why = _DERIVED
        elif not resolver.exists(val) \
                and resolver.exists(posixpath.dirname(val)):
            # CONJUNCT 7.  See KNOWN CONSERVATISM in the module docstring.
            # The directory is here and this member of it is not.  That is
            # what an optional program looks like, what a `try`/`catch`
            # around a read looks like, and what a file written on first use
            # looks like.  The defect this gate guards is a path naming a
            # LAYOUT that is not there, and that shape is untouched by this.
            why = _ABSENT_MEMBER
        sites.append(Site(rel, line_of(masked, lo), expr, val, why))

    # 1. Template literals whose value ends in the program suffix.
    for start, parts in sorted(scan.templates.items()):
        tail = parts[-1][1] if parts and parts[-1][0] == "lit" else ""
        if not (isinstance(tail, str) and tail.endswith(_PROGRAM_SUFFIX)):
            continue
        toks = tokenize(scan, start, len(masked))
        if not (toks and toks[0].kind == "tmpl"):
            continue
        add(start, toks[0].end)

    # 2. join()/resolve() calls that BUILD a program path.  The decision is
    #    taken on the EVALUATED value, not on whether a `.py` literal happens
    #    to sit between the parentheses: hoisting the program name into a
    #    `const` one line up — an idiomatic, one-line refactor — would
    #    otherwise make the site vanish from the scan with no signal at all.
    for m in re.finditer(r"\b(?:[A-Za-z_$][\w$]*\s*\.\s*)?(?:join|resolve)\s*\(",
                         masked):
        lo = m.start()
        open_off = m.end() - 1
        end = _balanced_end(masked, open_off)
        v = eval_range(scan, lo, end, bindings, resolver)
        if isinstance(v, str):
            if not v.endswith(_PROGRAM_SUFFIX):
                continue          # a definite path that is not a program
        elif not any(txt.endswith(_PROGRAM_SUFFIX)
                     for off, txt in scan.strings.items()
                     if open_off < off < end):
            continue              # nothing here names a program
        # else: the source names a program HERE but the call does not
        # evaluate.  Keep it, so it is DISCLOSED as undecided.  Dropping it
        # would mean any edit that un-binds a name — a second declaration of
        # `here`, say — deleted the site from the report entirely.
        add(lo, end)

    # 3. Any OTHER call that carries a program FILENAME as a literal
    #    argument.  These never become findings — a call this evaluator does
    #    not model has no value, so the site is always undecided — but they
    #    must be PRINTED.  Without this, aliasing the builder
    #    (`const { resolve: R } = path; R(here, ..., "gate.py")`) or moving
    #    it into a helper (`_mkGate("gate.py")`) deleted the site from the
    #    report with no signal at all, and the run said "every in-scope path
    #    resolves" about a tool it had stopped looking at.
    for m in re.finditer(r"\b([A-Za-z_$][\w$]*)\s*\(", masked):
        if m.group(1) in ("join", "resolve", "if", "for", "while", "switch",
                          "catch", "return", "function", "require", "import"):
            continue
        open_off = m.end() - 1
        end = _balanced_end(masked, open_off)
        # ONLY this call's own arguments.  A filename nested three calls
        # deeper belongs to the inner call, and crediting it to the outer
        # one made a whole `server.tool(...)` registration read as a program
        # path site.
        if not any(_FILENAME_RE.fullmatch(txt)
                   for off, txt in scan.strings.items()
                   if open_off < off < end
                   and _depth_between(masked, open_off, off) == 1):
            continue
        if any(m.start() <= c < end for c in claimed):
            continue
        add(m.start(), end)

    # 4. Any WRITE — declared `const`, `let`, `var` or not declared at all —
    #    whose RHS builds a program path.  This is what covers `DIR +
    #    "/gate.py"`: string concatenation builds a path with no join() and
    #    no template, and patterns 1-3 never look at it.  Decided on the
    #    VALUE where there is one (a bare filename with no directory is a
    #    NAME, not a path), and otherwise on a program FILENAME written
    #    literally in the RHS — the same fallthrough as pattern 2, and for
    #    the same reason: an RHS this evaluator cannot read (an object
    #    literal, a name some other line rebinds) must stay in the printed
    #    list rather than disappear from the report.
    for d in decls:
        if isinstance(d.value, str):
            if not (d.value.endswith(_PROGRAM_SUFFIX) and "/" in d.value):
                continue      # a definite value that is not a program path
        elif not any(txt.endswith(_PROGRAM_SUFFIX)
                     for off, txt in scan.strings.items()
                     if d.rhs_lo <= off < d.rhs_hi):
            continue          # nothing here names a program
        if any(d.rhs_lo <= c < d.rhs_hi for c in claimed):
            continue
        add(d.rhs_lo, d.rhs_hi)

    # 5. Any BRANCHING initialiser that names a program file.  It has no
    #    value — nothing here resolves through a branch — so it is collected
    #    on the literal program name in it and reported as undecided.
    #    Without this the branch deleted the SITE: `const gate = <dead> ||
    #    (dir)` evaluated to a directory, stopped looking like a program
    #    path, and the run reported one fewer place it had looked.  Driven
    #    off `branch_spans`, not `decls`, which drops array-bound names.
    for b_lo, b_hi in branch_spans:
        if not any(txt.endswith(_PROGRAM_SUFFIX)
                   for off, txt in scan.strings.items()
                   if b_lo <= off < b_hi):
            continue
        if any(b_lo <= c < b_hi for c in claimed):
            continue
        add(b_lo, b_hi)

    # A list holding MORE THAN ONE program path holds alternatives; a list
    # holding one holds a spawn's argv (`[script, projectDir, "--json"]`),
    # and that script must exist.  Decided after collection, because "is this
    # member a program path" is the same question the sites answer.
    # `claimed[i]` is the offset of `sites[i]`: `add` appends to both or to
    # neither.
    for a, b in lists:
        inside = [st for off, st in zip(claimed, sites) if a <= b and a <= off < b]
        if len(inside) < 2:
            continue
        decided = [st for st in inside if st.undecided is None]
        # An alternation is out of scope only while a LIVE alternative is
        # still possible: one that exists, or one this checker could not
        # decide and therefore cannot rule out.  When every alternative is
        # decided and every one of them is dead, the probe falls through on
        # every machine and each member is judged on its own — otherwise
        # writing a second dead path beside the first would buy a green.
        if len(decided) < len(inside) or any(resolver.exists(st.resolved)
                                             for st in decided):
            for st in inside:
                if st.undecided is None:
                    st.undecided = _IN_LIST

    return sites


# ===========================================================================
# Audit
# ===========================================================================

@dataclass
class Report:
    files_scanned: int = 0
    sites: int = 0
    resolved: int = 0
    findings: List[Finding] = field(default_factory=list)
    scanned_files: List[str] = field(default_factory=list)
    #: (file, line, expression, resolved path) for every site this run
    #: DECIDED and found present.  A denominator nobody can inspect is a
    #: number to be trusted; this is the list behind `resolved`.
    decided: List[Tuple[str, int, str, str]] = field(default_factory=list)
    #: (file, line, expression, why) for every site this checker looked at
    #: and did NOT decide.  Printed, not merely counted: a blind spot the
    #: reader cannot locate is a blind spot that grows unobserved.
    undecided: List[Tuple[str, int, str, str]] = field(default_factory=list)


def audit(plugin_root: Path,
          src_dir: str = DEFAULT_SRC_DIR) -> Tuple[Report, Optional[str]]:
    """Return (report, cannot_check_reason)."""
    root = Path(plugin_root).resolve()
    if not root.is_dir():
        return Report(), f"plugin root {str(root)!r} is not a directory"
    src_root = root / src_dir
    if not src_root.is_dir():
        return Report(), (f"no MCP source directory at "
                          f"{str(src_root)!r} — nothing to read, so this run "
                          f"says nothing about whether the tools can reach "
                          f"their programs")
    files = sorted(p for p in src_root.rglob("*")
                   if p.is_file() and p.suffix in _SRC_SUFFIXES
                   and "node_modules" not in p.parts)
    if not files:
        return Report(), (f"{str(src_root)!r} holds no "
                          f"{'/'.join(_SRC_SUFFIXES)} source")

    rep = Report()
    resolver = PathResolver(root)

    for f in files:
        rel = str(f.relative_to(root))
        try:
            src = f.read_text(errors="replace")
        except OSError as exc:
            return rep, f"cannot read {rel}: {exc}"
        scan = scan_js(src)
        rep.files_scanned += 1
        rep.scanned_files.append(rel)
        if not scan.balanced:
            return rep, (f"{rel}: the masking scan ended unbalanced — the "
                         f"source was not parsed, so no verdict is offered")
        bindings, decls, clash = discover_bindings(scan, f, resolver)
        if clash:
            return rep, (f"{rel} binds {', '.join(clash)} both to this "
                         f"file's own directory and to something else. Which "
                         f"one a path expression means needs scope analysis "
                         f"this checker does not do, and guessing either way "
                         f"would either flag a path the source never builds "
                         f"or let one declaration silence a real one")
        anchor, _d, _c = discover_bindings(scan, f, resolver,
                                           own_dir=_ANCHOR_SENTINEL)
        for s in collect_sites(scan, src, rel, str(src_root), bindings,
                               anchor, decls, resolver):
            rep.sites += 1
            if s.undecided:
                rep.undecided.append((rel, s.line, s.expr, s.undecided))
            elif resolver.exists(s.resolved):
                rep.resolved += 1
                rep.decided.append((rel, s.line, s.expr, s.resolved))
            else:
                rep.findings.append(Finding(
                    "program-path-does-not-resolve", rel, s.line,
                    f"`{s.expr}` resolves to {s.resolved!r}, which exists in "
                    f"no shipped layout. The tool that spawns it can never "
                    f"run."))

    return rep, None


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("plugin_root", nargs="?", default=".",
                   help="plugin root (the directory holding programs/ and "
                        f"{DEFAULT_SRC_DIR})")
    p.add_argument("--src-dir", default=DEFAULT_SRC_DIR,
                   help=f"MCP source dir relative to the plugin root "
                        f"(default: {DEFAULT_SRC_DIR})")
    p.add_argument("--json", dest="json_out", default=None,
                   help="write the machine-readable report here ('-' = stdout)")
    args = p.parse_args(list(argv) if argv is not None else None)

    # A bug in this checker's own scanner must not impersonate a finding.
    # Letting an exception escape ends the process with rc=1 — the SAME code
    # a real FAIL uses — and prints a traceback instead of a verdict, so a
    # caller reading rc=1 as "FAIL" gets a failure with zero findings.
    # CANNOT-CHECK is not PASS, and it is not FAIL either.
    try:
        rep, cannot = audit(Path(args.plugin_root), args.src_dir)
    except Exception as exc:                      # noqa: BLE001 - deliberate
        tb = exc.__traceback__
        where = ""
        while tb is not None:
            where = f"{Path(tb.tb_frame.f_code.co_filename).name}:{tb.tb_lineno}"
            tb = tb.tb_next
        rep = Report()
        cannot = (f"this checker raised {type(exc).__name__} at {where} while "
                  f"reading the MCP sources ({exc}) — it did not finish "
                  f"looking, so it offers no verdict")

    payload: Dict[str, Any] = {
        "check": CHECK_NAME,
        "files_scanned": rep.files_scanned,
        "program_path_sites": rep.sites,
        "resolved": rep.resolved,
        "unresolved_by_construction": len(rep.undecided),
        "decided": [{"file": d[0], "line": d[1], "expr": d[2],
                     "resolved": d[3]} for d in rep.decided],
        "undecided": [{"file": u[0], "line": u[1], "expr": u[2],
                       "why": u[3]} for u in rep.undecided],
        "findings": [{"rule": f.rule, "file": f.file, "line": f.line,
                      "message": f.message} for f in rep.findings],
    }
    if cannot:
        payload["status"] = "CANNOT_CHECK"
        payload["cannot_check_reason"] = cannot
    else:
        payload["status"] = "FAIL" if rep.findings else "PASS"

    if args.json_out:
        text = json.dumps(payload, indent=2)
        if args.json_out == "-":
            print(text)
        else:
            Path(args.json_out).write_text(text + "\n")

    if cannot:
        print(f"[REFUSE] {CHECK_NAME}: CANNOT-CHECK — {cannot}")
        return RC_CANNOT_CHECK

    decided = rep.resolved + len(rep.findings)
    denom = (f"{rep.sites} program-path site(s) across {rep.files_scanned} "
             f"MCP source file(s); {decided} DECIDED ({rep.resolved} present, "
             f"{len(rep.findings)} missing), {len(rep.undecided)} undecided "
             f"and named above")
    # A blind spot that is only a NUMBER can grow without anyone noticing
    # which tool it swallowed.  Name every site this run did not decide.
    for rel, line, expr, why in rep.undecided:
        print(f"{rel}:{line}: [undecided] `{expr}` — {why}")
    if rep.findings:
        for f in rep.findings:
            print(f.as_line())
        print(f"[FAIL] {CHECK_NAME}: {len(rep.findings)} finding(s); {denom}")
        return RC_FAIL
    # NOT "every program path resolves".  On a tree whose sites are all
    # undecided that sentence is vacuously true and reads as an all-clear.
    # State the DECIDED count first, so a run that decided nothing says so.
    print(f"[PASS] {CHECK_NAME}: no DECIDED program path is missing; {denom}. "
          f"A PASS covers the decided sites and nothing else — see WHAT THIS "
          f"CHECKER DOES NOT DECIDE and KNOWN CONSERVATISM in the module "
          f"docstring")
    return RC_PASS


if __name__ == "__main__":
    raise SystemExit(main())
