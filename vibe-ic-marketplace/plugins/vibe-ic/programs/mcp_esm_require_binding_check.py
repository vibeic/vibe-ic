#!/usr/bin/env python3
"""mcp_esm_require_binding_check.py — an ES module that USES ``require``
must BIND the name somewhere in the same file.

THE DEFECT THIS PINS (measured, fixed 2026-09-17)
-------------------------------------------------
The server package declares ``"type": "module"``, so every ``.js`` it owns is
an ES module and the CommonJS free variable ``require`` does not exist in that
scope. ``src/index.js`` called ``require(...)`` at FIVE sites anyway: eight of
the 56 registered tools threw ``ReferenceError: require is not defined`` for
ANY input, for 400+ commits, and two failed SILENTLY — one sat inside ``try {
... } catch { return false }``, so a netlist canonicalisation step stopped
running while synthesis went on reporting success. Every test asserted the tool
was REGISTERED, and a tool that throws the instant it is CALLED is registered.
Registration is a fact about the tool table; reachability is a fact about the
file's scope, and this gate is the second one.

THE RULE — ONE SENTENCE, FILE-SCOPED
------------------------------------
For every file Node loads as an ES MODULE: if the name ``require`` is USED in
CODE, the name ``require`` must be BOUND somewhere in that same file.

That is the whole rule. It does not model scope, does not ask WHERE the binding
sits, and does not ask where the bound value came from. It measures the one
fact separating the pre-fix file from the fixed one: the pre-fix file bound the
name NOWHERE. An earlier revision DID model scope, a span per binding; that
machinery is deleted, not repaired, because a concise-body arrow ``(require) =>
expr`` computed the span ``(0, end-of-file)`` and ONE token certified a whole
file of unbound calls as PASS.

KNOWN CONSERVATISM — documented FALSE NEGATIVES, every one of them allowed
--------------------------------------------------------------------------
  * THE HALF FIX. A binding inside one function does not put the name in scope
    at another function's call site. MEASURED under node v22.22.0: ``const
    require = createRequire(import.meta.url)`` inside ``canonicalize`` with a
    bare ``require("fs")`` in a sibling ``writeManifest`` throws
    ``ReferenceError`` at the sibling — silently, inside the original
    ``catch``. THIS GATE REPORTS THAT FILE AS PASS. Deciding it needs hoisting
    and closure analysis, so it needs a parser.
  * Every binding narrower than the file, for the same reason: a parameter
    named ``require``, a ``catch (require)``, a binding in a block that never
    runs. Excluding parameters was MEASURED and rejected — a nested ``const
    require`` still satisfies any file-scoped rule, so it closes nothing, and
    it turns node-verified dependency injection (``function f(require) {
    require("os") }``) into a false FAIL.
  * A call whose arguments hold an ``=`` before their first literal and is
    followed by a block on the NEXT line — ``require(x = "fs")`` then
    ``{ }`` — reads as a method DEFINITION, exactly the shape of a default
    parameter; separating the two needs the enclosing context (object literal
    or class body versus statement position), so it needs a parser. MEASURED:
    node throws ``ReferenceError`` there, and rejects the SAME-line spelling
    outright (``SyntaxError: Unexpected token '{'`` — no ASI without the
    newline), so reaching this miss means rewriting every call site by hand.

A miss is allowed here; a false FAIL on working code is not, and when the two
trade off this rule misses. What CANNOT silence the gate is the part that
matters: no pragma, comment, annotation, allow-list, environment variable,
filename, or manifest value other than an EXACT ``"commonjs"``, and the
stripper makes sure prose cannot either. What DOES silence it is a real
occurrence of the NAME ``require`` in code — the fix, or one of the three
misses above — or a manifest node itself reads as CommonJS, after which the
file really has a working ``require``, or really stops at load.

WHAT COUNTS AS A USE (measured against the runtime, not a spelling)
------------------------------------------------------------------
A call ``require(...)``, or a dereference ``require.resolve(...)`` /
``require.cache`` / ``require.main`` — MEASURED, each dereference throws the
SAME ``ReferenceError`` as a bare call, the name being evaluated before the
property lookup. NOT a use: ``typeof require``, the one operator in JS safe on
an undeclared name (MEASURED, rc=0); a DEFINITION, since ``function require(id)
{ ... }`` and a method ``require(id) { ... }`` hold a PARAMETER LIST, and a gate
that reads one as a call reports a file with zero calls as one that throws; and
a MEMBER, ``holder.require(...)`` or ``this.#require(...)``, where the object
supplies the binding — including when the ``.`` ends one line and the name
opens the next, MEASURED rc=0.

WHAT COUNTS AS A BINDING (any spelling that really binds the NAME)
-----------------------------------------------------------------
``const|let|var require ...`` initialised or not; a destructuring pattern
binding the name; a function or class declaration named ``require``; a
parameter named ``require`` (``function f(require)``, ``(require) =>``, ``catch
(require)``); an import binding the LOCAL name (``import require from``,
``import { x as require } from``, ``import * as require from`` — but NOT
``import { require as r }``, which binds ``r``); and ``globalThis.require =``,
``global.require =`` or ``globalThis["require"] =``, all three MEASURED to make
every bare ``require(...)`` below them resolve. ``self`` is NOT accepted:
MEASURED, it is not defined in node's ESM scope, so ``self.require = ...`` is a
line that throws, not a binding.

PROVENANCE IS DELIBERATELY NOT CHECKED — a narrowing of the CLAIM, not a hole.
This gate pins the ReferenceError class, the one that fails SILENTLY inside
``catch``; whether the bound value is a real CJS resolver is a different class,
which fails LOUDLY with a ``TypeError`` the first time it runs. Requiring the
binding to come from ``node:module`` was MEASURED to fire on ten legal
spellings node runs with rc=0, ``const { createRequire } = await
import("node:module")`` among them.

WHICH FILES ARE ES MODULES (Node's own resolution, not a guess)
---------------------------------------------------------------
``.mjs`` always is; ``.cjs`` never is, even inside a ``"type":"module"``
package; a ``.js`` is decided by the NEAREST ancestor ``package.json`` —
nearest, not any, because a nested CommonJS package inside an ES-module package
makes its own subtree CJS again. The test is on the CommonJS side, where node
puts it:

  * the manifest says EXACTLY ``"commonjs"`` -> CommonJS, excluded;
  * it says EXACTLY ``"module"`` -> an ES module, whatever the file contains;
  * ANYTHING ELSE — no manifest, no ``"type"``, a misspelling, any other
    string -> node decides by SYNTAX DETECTION, and so does this gate.

Reading that the other way round — "only ``"type":"module"`` opts a file
IN" — was the widest ONE-LINE BUY-GREEN this gate ever had. MEASURED on node
v22.22.0: ``"Module"``, ``"MODULE"``, ``"module "``, ``"esm"``, ``"modules"``,
``""``, ``"true"``, ``"Commonjs"``, ``"commonjs "``, ``"banana"`` and the field
deleted outright — ELEVEN values, every one still loaded as an ES module and
still throwing ``ReferenceError`` at the same sites while the gate went rc=1 ->
rc=0 and printed PASS; a nested ``src/package.json`` holding ``{"type":"esm"}``
did the same. Tested on the CommonJS side, all twelve stay rc=1.

The manifest walk runs to the FILESYSTEM ROOT, as Node's does, so a manifest
ABOVE the scan root still governs the files inside it. Bounding it at the scan
root was MEASURED to turn the real pre-fix tree from ``rc=1, 5 sites`` into
``rc=0 [PASS]`` merely by pointing the checker one directory deeper.

WHY COMMENTS AND STRINGS ARE STRIPPED FIRST (both directions)
-------------------------------------------------------------
The file this was found in embeds prose, shell text and scripts in template
literals, all mentioning ``require``; raw text would make a comment enough to
trip the gate. The same stripped view feeds the BINDING side, so a ``const
require = ...`` in a comment or a string does NOT satisfy it either. The
stripper is a real JS scanner (comments, strings, templates whose ``${...}``
substitutions are kept as CODE, nested templates, regex literals); it blanks
space-for-space and newline-for-newline so line numbers stay real, and it tells
a regex from a division by the last significant token, plus two refinements
each MEASURED to matter: after ``)`` a ``/`` divides UNLESS that ``)`` closed an
``if`` / ``while`` / ``for`` / ``switch`` header (without which ``if (x)
/[`]/.test(x)`` desynchronised on the backtick), and after ``++`` or ``--`` it
divides (without which ``i++ / total`` opened a regex that ate the rest of the
line, binding and all). An UNCLOSED comment or template swallows the rest of
the file, so it is reported as CANNOT-CHECK, never PASS.

DELIBERATE NARROWINGS (each one prevents a false finding)
---------------------------------------------------------
  * ``node_modules/`` is not scanned: third-party code this repo neither
    authors nor can fix, which ships CommonJS shims on purpose. MEASURED with
    the skip lifted, the venue grows from 13 files to 501 and yields exactly
    one "finding" — a deliberate bundler shim reached by a resolver that is not
    Node's ESM loader. Generated output (``dist/``, ``build/``) is NOT skipped:
    a skip list is a list of blind spots.
  * ``require`` inside a longer identifier (``required``, ``createRequire``)
    never matches.
  * A bare mention that is neither a call nor a dereference — ``const r =
    require;`` — is NOT a finding: telling it from a property key, an import
    specifier and a shorthand needs a parser.
  * Venue is ``.js`` / ``.mjs`` / ``.cjs``; TypeScript is not scanned, because
    a ``.ts`` file is not what Node loads. The NAME checked is ``require``
    only: ``__dirname`` / ``__filename`` go the same way, but claiming them
    unmeasured would be unearned scope.

EXIT CODES
----------
  0  PASS         — ES-module files were read, and every one that uses
                    ``require`` also binds the name.
  1  FAIL         — a file USES ``require`` and binds it NOWHERE; each use is
                    named ``file:line``.
  2  CANNOT-CHECK — no such root, a ``package.json`` that will not parse, a
                    source that will not read or will not lex, or NO ES-module
                    file under the root. None is a clean bill; none returns 0.

chip-AGNOSTIC.
"""
from __future__ import annotations

# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` it does
# not. Idempotent, and the same shape the sibling programs carry.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------

import argparse
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

class CannotCheck(Exception):
    """The input needed to answer was absent, unreadable or unlexable."""


TOOL = "mcp_esm_require_binding_check"

RC_PASS, RC_FAIL, RC_CANNOT_CHECK = 0, 1, 2

DENOMINATOR_UNIT = "ES-module source file read and scanned for uses of `require`"

#: Never descended into. A long skip list is a long list of blind spots.
_SKIP_DIRS = frozenset({".git", "node_modules", "__pycache__", ".pytest_cache"})

_ESM_ALWAYS_SUFFIX = ".mjs"
_CJS_ALWAYS_SUFFIX = ".cjs"
_AMBIGUOUS_SUFFIX = ".js"


# ---------------------------------------------------------------------------
# JS source scanner: blank everything that is not code
# ---------------------------------------------------------------------------
_WORD_CHARS = set("abcdefghijklmnopqrstuvwxyz"
                  "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_$")

#: After one of these, a `/` opens a regex literal rather than dividing.
_REGEX_PRECEDING_CHARS = frozenset("(,=:[!&|?{};+-*%^~<>")
_REGEX_PRECEDING_WORDS = frozenset({
    "return", "typeof", "instanceof", "in", "of", "new", "delete", "do",
    "else", "case", "void", "yield", "await", "throw",
})

#: `(` heads that make the parenthesised group a CONDITION, not a parameter
#: list, even though `{` follows the `)`. `catch` is deliberately absent: its
#: group IS a binding position.
_CONDITION_HEAD_WORDS = frozenset({"if", "while", "for", "switch", "with"})


def _regex_can_start(prev_sig: str, prev2_sig: str, prev_token: str,
                     last_close_was_condition: bool) -> bool:
    """Would a `/` here open a regex literal (rather than divide)?"""
    if prev_sig == "":
        return True
    if prev_sig == ")":
        # `if (x) /re/.test(x)` starts a regex; `(a + b) / 2` divides.
        return last_close_was_condition
    if prev_sig in "+-" and prev2_sig == prev_sig:
        # `i++ / total` DIVIDES. Reading `+` as an operator here opened a
        # regex that ate the rest of the line, taking a binding with it.
        return False
    if prev_sig in _REGEX_PRECEDING_CHARS:
        return True
    if prev_sig in _WORD_CHARS:
        return prev_token in _REGEX_PRECEDING_WORDS
    return False


def _scan(text: str) -> Tuple[str, Optional[str]]:
    """`(text with every non-code region blanked, what was left open)`.

    Comments, string literals, the literal spans of template literals and regex
    literals are blanked; `${...}` substitutions ARE code and survive. Blanked
    characters become spaces, newlines stay newlines, so offsets and line
    numbers survive exactly. The second half of the pair reports an UNCLOSED
    comment or template: MEASURED, a lone `/*` — or a lone backtick — swallowed
    the rest of the file and took this gate from rc=1 to rc=0.
    """
    unterminated: Optional[str] = None
    out: List[str] = []
    i, n = 0, len(text)
    mode = "code"
    subs: List[int] = []        # brace depth inside each active `${ }`
    prev_sig = ""               # last non-space code char
    prev2_sig = ""              # the one before it (`++` vs `+`)
    cur_word = ""               # identifier being accumulated right now
    last_word = ""              # last identifier that ended
    paren_heads: List[bool] = []          # was each open paren a condition head?
    last_close_was_condition = False

    def blank(ch: str) -> None:
        out.append("\n" if ch == "\n" else " ")

    def blank_run(start: int, stop: int) -> None:
        for k in range(start, stop):
            blank(text[k])

    while i < n:
        c = text[i]

        if mode == "tmpl":
            if c == "\\":
                blank(c)
                if i + 1 < n:
                    blank(text[i + 1])
                i += 2
                continue
            if c == "`":
                blank(c)
                i += 1
                mode = "code"
                prev2_sig, prev_sig, cur_word, last_word = prev_sig, "`", "", ""
                continue
            if c == "$" and i + 1 < n and text[i + 1] == "{":
                blank(c)
                blank(text[i + 1])
                i += 2
                subs.append(0)
                mode = "code"
                prev2_sig, prev_sig, cur_word, last_word = prev_sig, "{", "", ""
                continue
            blank(c)
            i += 1
            continue

        # --- mode == "code" ------------------------------------------------
        nxt = text[i + 1] if i + 1 < n else ""

        if c == "/" and nxt == "/":
            stop = text.find("\n", i)
            stop = n if stop < 0 else stop
            blank_run(i, stop)
            i = stop
            continue

        if c == "/" and nxt == "*":
            stop = text.find("*/", i + 2)
            if stop < 0:
                unterminated = (f"a block comment opened at line "
                                f"{text.count(chr(10), 0, i) + 1} is never "
                                f"closed")
                stop = n
            else:
                stop += 2
            blank_run(i, stop)
            i = stop
            continue

        if c in ("'", '"'):
            quote = c
            blank(c)
            i += 1
            while i < n:
                ch = text[i]
                if ch == "\\":
                    blank(ch)
                    if i + 1 < n:
                        blank(text[i + 1])
                    i += 2
                    continue
                blank(ch)
                i += 1
                if ch == quote or ch == "\n":
                    break
            prev2_sig, prev_sig, cur_word, last_word = prev_sig, quote, "", ""
            continue

        if c == "`":
            blank(c)
            i += 1
            mode = "tmpl"
            continue

        if c == "/" and _regex_can_start(prev_sig, prev2_sig,
                                         cur_word or last_word,
                                         last_close_was_condition):
            blank(c)
            i += 1
            in_class = False
            while i < n:
                ch = text[i]
                if ch == "\\":
                    blank(ch)
                    if i + 1 < n:
                        blank(text[i + 1])
                    i += 2
                    continue
                if ch == "\n":
                    break       # unterminated — it was not a regex after all
                blank(ch)
                i += 1
                if ch == "[":
                    in_class = True
                elif ch == "]":
                    in_class = False
                elif ch == "/" and not in_class:
                    break
            while i < n and text[i].isalpha():
                blank(text[i])
                i += 1
            prev2_sig, prev_sig, cur_word, last_word = prev_sig, "/", "", ""
            continue

        # plain code character
        if c == "{" and subs:
            subs[-1] += 1
        elif c == "}" and subs:
            if subs[-1] == 0:
                subs.pop()
                blank(c)
                i += 1
                mode = "tmpl"
                continue
            subs[-1] -= 1

        if c == "(":
            paren_heads.append((cur_word or last_word) in _CONDITION_HEAD_WORDS)
        elif c == ")":
            last_close_was_condition = paren_heads.pop() if paren_heads else False

        out.append(c)
        i += 1
        if c in _WORD_CHARS:
            cur_word += c
        else:
            if cur_word:
                last_word = cur_word
            cur_word = ""
        if not c.isspace():
            prev2_sig, prev_sig = prev_sig, c

    if mode == "tmpl" and unterminated is None:
        unterminated = "a template literal is never closed"
    return "".join(out), unterminated


# ---------------------------------------------------------------------------
# The rule, applied to one ES-module file
# ---------------------------------------------------------------------------
#: A USE of the free name `require`: a call `require(`, or a dereference
#: `require.x` / `require?.x`. The lookbehind rejects `myrequire(`; the pattern
#: is case-sensitive, so `createRequire(` cannot match. `typeof require ===`
#: does not match — the next significant character is neither `(` nor `.`. What
#: is to the LEFT is decided by `_prev_significant`, NOT by a lookbehind: a
#: fixed-width one saw whitespace where `holder.` ended the previous line.
_REQUIRE_USE_RE = re.compile(
    r"(?<![A-Za-z0-9_$])require\s*(?:\(|\??\.\s*[A-Za-z_$])")

#: `import <clause> from` — `import{x}from"y"` (minified, no whitespace) must
#: parse too, so the separator is `\s*`, guarded by lookaheads that keep
#: `importFoo` and `fromage` out. The clause cannot cross a `;`.
_IMPORT_CLAUSE_RE = re.compile(
    r"(?<![A-Za-z0-9_$.])import(?![A-Za-z0-9_$])\s*([^;]*?)"
    r"(?<![A-Za-z0-9_$])from(?![A-Za-z0-9_$])")

#: Inside an import clause the name `require` is the LOCAL binding — unless
#: `as` follows it, which makes it the IMPORTED name and something else local
#: (`import { require as r }` binds `r`, not `require`).
_CLAUSE_LOCAL_REQUIRE_RE = re.compile(
    r"(?<![A-Za-z0-9_$.])require(?![A-Za-z0-9_$])(?!\s*as(?![A-Za-z0-9_$]))")

#: `const|let|var require` — initialised or not, in one statement or two.
_DECL_REQUIRE_RE = re.compile(
    r"(?<![A-Za-z0-9_$.])(?:const|let|var)\s+require(?![A-Za-z0-9_$])")

#: `const|let|var {` / `[` — a destructuring pattern; the names inside it are
#: read out with a balanced scan, not a regex.
_DECL_PATTERN_RE = re.compile(
    r"(?<![A-Za-z0-9_$.])(?:const|let|var)\s*([{\[])")

_FUNCTION_REQUIRE_RE = re.compile(
    r"(?<![A-Za-z0-9_$.])function\s*\*?\s*require(?![A-Za-z0-9_$])")

_CLASS_REQUIRE_RE = re.compile(
    r"(?<![A-Za-z0-9_$.])class\s+require(?![A-Za-z0-9_$])")

#: `globalThis.require = ...` binds a real global, so a bare `require` resolves
#: through it. `self` is absent — MEASURED, undefined in node's ESM scope.
_GLOBAL_REQUIRE_RE = re.compile(
    r"(?<![A-Za-z0-9_$.])(?:globalThis|global)\s*\.\s*require\s*=(?!=)")

#: The same binding with a computed key, MEASURED to resolve every bare
#: `require(...)` below it. The key is a STRING, blanked by the stripper, so
#: this one pattern runs against the ORIGINAL text and is confirmed live by
#: checking the offset survived stripping — which is what stops a comment from
#: satisfying it.
_GLOBAL_COMPUTED_REQUIRE_RE = re.compile(
    r"""(?<![A-Za-z0-9_$.])(?:globalThis|global)\s*\[\s*"""
    r"""(['"])require\1\s*\]\s*=(?!=)""")

#: Node's OWN tie-breaker for a `.js` its nearest manifest does not put on one
#: side or the other — see WHICH FILES ARE ES MODULES. Matched on the STRIPPED
#: view, so prose cannot reclassify a file; a dynamic `import(...)` is legal in
#: CommonJS and does not match, nor does `exports.x`.
_MODULE_SYNTAX_RE = re.compile(
    r"(?<![A-Za-z0-9_$.])(?:export(?![A-Za-z0-9_$])"
    r"|import(?![A-Za-z0-9_$])\s*[^;()]*?(?<![A-Za-z0-9_$])from(?![A-Za-z0-9_$])"
    r"|import(?![A-Za-z0-9_$])\s*['\"])")


def has_module_syntax(original: str) -> bool:
    """Does node's syntax detection load this undecided `.js` as ES?"""
    return _MODULE_SYNTAX_RE.search(_scan(original)[0]) is not None


_IDENT_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")

#: Tokens that force what follows into EXPRESSION position, so a `require(`
#: after one of them is a CALL even when a block happens to follow. `,` `;` `{`
#: `}` are deliberately absent — those are exactly the positions a method
#: definition sits in — and `*` is absent so a generator method
#: `*require(id) {}` is not libelled as a throwing call.
_EXPRESSION_FORCING_CHARS = frozenset("=([:?+-!&|~<>^%/")
_EXPRESSION_FORCING_WORDS = frozenset({
    "return", "typeof", "await", "yield", "new", "throw", "case", "delete",
    "void", "in", "of", "instanceof", "do", "else",
})

_MATCHING_CLOSE = {"{": "}", "[": "]", "(": ")"}


@dataclass
class Finding:
    file: str
    line: int
    rule: str
    snippet: str
    reason: str


def _line_of(text: str, idx: int) -> int:
    return text.count("\n", 0, idx) + 1


def _prev_significant(code: str, i: int) -> Tuple[str, str]:
    """The last non-space character before `i`, and the word it ends (if any)."""
    j = i - 1
    while j >= 0 and code[j].isspace():
        j -= 1
    if j < 0:
        return "", ""
    ch = code[j]
    if ch in _WORD_CHARS:
        k = j
        while k >= 0 and code[k] in _WORD_CHARS:
            k -= 1
        return ch, code[k + 1:j + 1]
    return ch, ""


def _skip_ws(text: str, i: int) -> int:
    n = len(text)
    while i < n and text[i].isspace():
        i += 1
    return i


def _bracket_pairs(code: str, opener: str) -> Dict[int, int]:
    """Map every `opener` offset to its matching close offset.

    Run on the BLANKED view, so every bracket is real code; an opener never
    closed maps to end-of-file rather than vanishing.
    """
    closer = _MATCHING_CLOSE[opener]
    stack: List[int] = []
    pairs: Dict[int, int] = {}
    for i, ch in enumerate(code):
        if ch == opener:
            stack.append(i)
        elif ch == closer and stack:
            pairs[stack.pop()] = i
    for leftover in stack:
        pairs[leftover] = len(code)
    return pairs


def _pattern_binds_require(text: str) -> bool:
    """Does this destructuring pattern / parameter list bind the NAME require?

    `{ require }` and `{ x: require }` bind it; `{ require: r }` binds `r`;
    `a = require("x")` is a default-value CALL, not a binding.
    """
    for m in _IDENT_RE.finditer(text):
        if m.group(0) != "require":
            continue
        if m.start() > 0 and text[m.start() - 1] == ".":
            continue
        j = _skip_ws(text, m.end())
        if j < len(text) and text[j] in ":(":
            continue
        return True
    return False


def find_binding(code: str, parens: Dict[int, int],
                 original: str) -> Optional[Tuple[int, str]]:
    """The FIRST binding of the name `require` in this file, or None.

    File-scoped by construction: WHERE it sits is not asked. See KNOWN
    CONSERVATISM — a binding narrower than the file is a documented miss.
    """
    sites: List[Tuple[int, str]] = []

    for m in _IMPORT_CLAUSE_RE.finditer(code):
        if _CLAUSE_LOCAL_REQUIRE_RE.search(m.group(1)):
            sites.append((m.start(), "an import binding the name `require`"))

    for regex, kind in (
            (_DECL_REQUIRE_RE, "a `const|let|var require` declaration"),
            (_FUNCTION_REQUIRE_RE, "a function declaration named `require`"),
            (_CLASS_REQUIRE_RE, "a class declaration named `require`"),
            (_GLOBAL_REQUIRE_RE, "an assignment to the global `require`")):
        for m in regex.finditer(code):
            sites.append((m.start(), kind))

    brackets: Dict[str, Dict[int, int]] = {"{": {}, "[": {}}
    for m in _DECL_PATTERN_RE.finditer(code):
        open_i = m.end() - 1
        opener = code[open_i]
        if not brackets[opener]:
            brackets[opener] = _bracket_pairs(code, opener)
        close_i = brackets[opener].get(open_i, len(code))
        if _pattern_binds_require(code[open_i + 1:close_i]):
            sites.append((m.start(),
                          "a destructuring declaration binding `require`"))

    for open_i in _parameter_lists_binding_require(code, parens):
        sites.append((open_i, "a parameter named `require`"))

    for m in _GLOBAL_COMPUTED_REQUIRE_RE.finditer(original):
        if code[m.start()] == original[m.start()]:      # live code, not prose
            sites.append((m.start(),
                          "a computed-key assignment to the global `require`"))

    return min(sites) if sites else None


def _parameter_lists_binding_require(code: str,
                                     parens: Dict[int, int]) -> List[int]:
    """Offsets of every parameter list that binds `require`.

    A group is a parameter list when its `)` is followed by `{` (a function or
    method body) or by `=>`. An `if` / `while` / `for` / `switch` / `with`
    header is excluded by the word in front of the `(`; `catch` is NOT, because
    `catch (require)` really does bind it.
    """
    n = len(code)
    found: List[int] = []
    for open_i, close_i in parens.items():
        if close_i >= n:
            continue
        j = _skip_ws(code, close_i + 1)
        if j >= n:
            continue
        is_arrow = code.startswith("=>", j)
        if not is_arrow and code[j] != "{":
            continue
        k = open_i - 1
        while k >= 0 and code[k].isspace():
            k -= 1
        end = k + 1
        while k >= 0 and code[k] in _WORD_CHARS:
            k -= 1
        if not is_arrow and code[k + 1:end] in _CONDITION_HEAD_WORDS:
            continue
        if _pattern_binds_require(code[open_i + 1:close_i]):
            found.append(open_i)
    return found


def _holds_an_argument_literal(original: str, code: str,
                               open_i: int, close_i: int) -> bool:
    """Does this group hold a string/template literal AS AN ARGUMENT?

    A PARAMETER LIST may hold a literal only inside a DEFAULT — everything
    between a top-level `=` and the next top-level `,`, an ARBITRARY
    expression, not just a literal against the `=`. MEASURED on node v22.22.0,
    all rc=0: `require(id = A || "fs") {}`, `require(id = x ? "fs" : "p") {}`,
    `require(id = `${x}fs`) {}` — keying on "a literal directly after `=`" read
    every one as a CALL. Anywhere ELSE a literal is a SyntaxError in a
    parameter list, so it settles the ambiguity in favour of CALL. Literals are
    found where the stripper blanked the text, counted only when the original
    starts the run with a quote. The converse — an `=` in real arguments — is a
    documented MISS.
    """
    depth = 0
    in_default = False
    j = open_i + 1
    while j < close_i:
        ch = original[j]
        if code[j] == ch:                          # live code, not a literal
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            elif depth == 0 and ch == ",":
                in_default = False
            elif (depth == 0 and ch == "="
                  and original[j + 1:j + 2] not in ("=", ">")
                  and original[j - 1] not in "=!<>+-*/%&|^"):
                in_default = True
            j += 1
            continue
        start = j
        while j < close_i and code[j] != original[j]:
            j += 1
        if original[start] in "\"'`" and not in_default:
            return True                            # an argument: this is a CALL
    return False


def find_uses(code: str, parens: Dict[int, int],
              original: str) -> List[Dict[str, object]]:
    """Every USE of the free name `require` in CODE — calls and dereferences.

    What is to the LEFT decides free variable versus member: a `.` or a `#`
    before the name — across a newline too — makes it `holder.require(...)` or
    `this.#require(...)`, bound by the object supplying it.

    A DEFINITION is not a use: `function require(id) {` and `require(id) {` in
    an object or class body hold a PARAMETER LIST. That exclusion is keyed on
    `)` followed by `{`, and TWO facts override it, each MEASURED to hide a live
    call: what PRECEDES demands an expression, or the group holds an argument.
    """
    total = len(code)
    uses: List[Dict[str, object]] = []
    for m in _REQUIRE_USE_RE.finditer(code):
        prev_char, prev_word = _prev_significant(code, m.start())
        if prev_char in (".", "#"):     # a TUPLE: `"" in ".#"` is True, and
            continue                    # a file may BEGIN with the call
        is_call = code[m.end() - 1] == "("
        if is_call:
            open_i = m.end() - 1
            close = parens.get(open_i)
            if close is not None and close < total:
                j = _skip_ws(code, close + 1)
                in_expression = (prev_char in _EXPRESSION_FORCING_CHARS
                                 or prev_word in _EXPRESSION_FORCING_WORDS)
                if (j < total and code[j] == "{" and not in_expression
                        and not _holds_an_argument_literal(
                            original, code, open_i, close)):
                    continue
        uses.append({"line": _line_of(code, m.start()),
                     "kind": "call" if is_call else "dereference"})
    return uses


def analyze_source(original: str) -> Dict[str, object]:
    """Analyse one ES-module source. Pure — no I/O, so it is directly testable."""
    code, unterminated = _scan(original)
    parens = _bracket_pairs(code, "(")
    return {"code": code,
            "unterminated": unterminated,
            "uses": find_uses(code, parens, original),
            "binding": find_binding(code, parens, original)}


_REMEDY = ("Bind it with `import { createRequire } from \"node:module\"; "
           "const require = createRequire(import.meta.url);` at MODULE scope, "
           "or replace the use with a top-level `import`.")


def scan_file(rel: str, original: str) -> List[Finding]:
    """Every use in one ES-module file, when the file binds nothing."""
    result = analyze_source(original)
    if result["unterminated"]:
        raise CannotCheck(
            f"{rel} cannot be lexed: {result['unterminated']}, so everything "
            f"after it was never read as code. Nothing here was checked, and "
            f"that is not a clean bill of health.")
    uses: List[Dict[str, object]] = result["uses"]        # type: ignore[assignment]
    if not uses or result["binding"] is not None:
        return []

    lines = original.splitlines()
    findings: List[Finding] = []
    for u in uses:
        lineno = int(u["line"])
        snippet = lines[lineno - 1].strip()[:120] if lineno - 1 < len(lines) else ""
        what = ("this call throws ReferenceError on every invocation"
                if u["kind"] == "call" else
                "evaluating `require` before the property lookup throws "
                "ReferenceError every time this line runs")
        findings.append(Finding(
            file=rel,
            line=lineno,
            rule="ESM-REQUIRE-UNBOUND",
            snippet=snippet,
            reason=(f"`require` is used in a file Node loads as an ES module, "
                    f"where the name is not defined and NOTHING IN THIS FILE "
                    f"binds it — {what}. {_REMEDY}"),
        ))
    return findings


# ---------------------------------------------------------------------------
# Venue discovery: which files does Node load as ES modules?
# ---------------------------------------------------------------------------
def _declared_type(pkg: Path) -> Optional[str]:
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise CannotCheck(
            f"{pkg} does not parse as JSON ({exc.__class__.__name__}), so "
            f"whether its subtree is ES-module or CommonJS is UNKNOWN. A scan "
            f"that skipped it would report on files it never "
            f"classified.") from exc
    if not isinstance(data, dict):
        raise CannotCheck(
            f"{pkg} is valid JSON but not an object, so it declares no "
            f"module type for its subtree.")
    t = data.get("type")
    return t if isinstance(t, str) else None


def _nearest_package_type(directory: Path,
                          cache: Dict[Path, Optional[str]]) -> Optional[str]:
    """Node's own rule: the NEAREST ancestor package.json wins, and the walk
    runs to the FILESYSTEM ROOT as Node's resolver does — bounding it at the
    scan root was MEASURED to turn the real defect into `rc=0 [PASS]` one
    directory deeper."""
    seen: List[Path] = []
    cur = directory
    while True:
        if cur in cache:
            answer = cache[cur]
            break
        seen.append(cur)
        pkg = cur / "package.json"
        if pkg.is_file():
            answer = _declared_type(pkg)
            break
        if cur == cur.parent:
            answer = None
            break
        cur = cur.parent
    for d in seen:
        cache[d] = answer
    return answer


def iter_esm_files(root: Path) -> Tuple[List[Path], List[Path], Dict[str, int]]:
    """Return (certain ES-module files, undecided `.js` candidates, census).

    A `.js` is decided HERE only on an EXACT `"commonjs"` (excluded) or an
    EXACT `"module"` (ES module whatever the file contains). Every other
    manifest — absent, typeless, misspelt, any other string — leaves it where
    node leaves it: a CANDIDATE, decided by SYNTAX DETECTION once read.
    """
    cache: Dict[Path, Optional[str]] = {}
    esm: List[Path] = []
    candidates: List[Path] = []
    census = {"js_seen": 0, "mjs_seen": 0, "cjs_excluded": 0, "js_excluded": 0}

    for dirpath, dirnames, filenames in _os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        here = Path(dirpath)
        for name in sorted(filenames):
            p = here / name
            suffix = p.suffix.lower()
            if suffix == _CJS_ALWAYS_SUFFIX:
                census["cjs_excluded"] += 1
                continue
            if suffix == _ESM_ALWAYS_SUFFIX:
                census["mjs_seen"] += 1
                # `.mjs` is ESM whatever the manifest says, but resolving it
                # anyway means an unparseable package.json GOVERNING a file we
                # scan still raises CannotCheck instead of passing unnoticed.
                _nearest_package_type(here, cache)
                esm.append(p)
                continue
            if suffix != _AMBIGUOUS_SUFFIX:
                continue
            census["js_seen"] += 1
            declared = _nearest_package_type(here, cache)
            if declared == "commonjs":          # node's ONE exact opt-out
                census["js_excluded"] += 1
            elif declared == "module":
                esm.append(p)
            else:                               # absent, misspelt, anything
                candidates.append(p)
    return esm, candidates, census


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def audit(root: str) -> Tuple[List[Finding], Dict[str, int]]:
    """Return (findings, census). Raises CannotCheck when it could not look."""
    base = Path(root).expanduser()
    if not base.is_dir():
        raise CannotCheck(f"not a directory: {base}")

    files, candidates, census = iter_esm_files(base)

    def read_source(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise CannotCheck(
                f"cannot read JavaScript source {path}: "
                f"{exc.__class__.__name__}. It was never scanned.") from exc

    sources: List[Tuple[Path, str]] = [(p, read_source(p)) for p in files]
    for p in candidates:
        text = read_source(p)
        if has_module_syntax(text):
            sources.append((p, text))
        else:
            census["js_excluded"] += 1
    sources.sort(key=lambda pair: str(pair[0]))

    findings: List[Finding] = []
    read = 0
    for p, original in sources:
        read += 1
        try:
            rel = str(p.relative_to(base))
        except ValueError:                       # pragma: no cover - defensive
            rel = str(p)
        findings.extend(scan_file(rel, original))
    census["files_read"] = read
    return findings, census


def _census_line(census: Dict[str, int]) -> str:
    return (
        f"read {census.get('files_read', 0)} ES-module file(s) "
        f"[{census.get('mjs_seen', 0)} .mjs + "
        f"{census.get('js_seen', 0) - census.get('js_excluded', 0)} .js]; "
        f"excluded {census.get('js_excluded', 0)} .js node does not load as "
        f"ES modules (an exact \"type\":\"commonjs\", or no module syntax "
        f"under any other manifest) and "
        f"{census.get('cjs_excluded', 0)} .cjs file(s); "
        f"unit = {DENOMINATOR_UNIT}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", nargs="?", default=".",
                    help="tree to scan (plugin root, repo root, or a package)")
    ap.add_argument("--json", help="write a JSON report to this path")
    args = ap.parse_args(argv)

    try:
        findings, census = audit(args.root)
    except CannotCheck as exc:
        print(f"[REFUSE] {TOOL}: CANNOT-CHECK — {exc}", file=_sys.stderr)
        return RC_CANNOT_CHECK

    read = census.get("files_read", 0)
    verdict = "FAIL" if findings else ("PASS" if read else "CANNOT-CHECK")
    census_line = _census_line(census)

    if args.json:
        try:
            Path(args.json).write_text(json.dumps({
                "tool": TOOL,
                "root": str(Path(args.root).expanduser()),
                "verdict": verdict,
                "count": len(findings),
                "census": census,
                "findings": [asdict(f) for f in findings],
            }, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"[REFUSE] {TOOL}: cannot write --json: {exc}",
                  file=_sys.stderr)
            return RC_CANNOT_CHECK

    for f in findings:
        print(f"{f.file}:{f.line}: [{f.rule}] {f.snippet}")
        print(f"    {f.reason}")

    if findings:
        n_files = len({f.file for f in findings})
        print(f"[FAIL] {TOOL}: {len(findings)} unbound use(s) of `require` "
              f"in {n_files} ES-module file(s); {census_line}")
        return RC_FAIL

    if read == 0:
        print(f"[REFUSE] {TOOL}: CANNOT-CHECK — no ES-module source under "
              f"{Path(args.root).expanduser()}: no .mjs file, and no .js file "
              f"node would load as an ES module (node_modules/ is not "
              f"scanned). Nothing was read, so this run "
              f"is NOT a clean verdict — point the checker at a tree that "
              f"contains the package.", file=_sys.stderr)
        print(f"[REFUSE] {TOOL}: {census_line}")
        return RC_CANNOT_CHECK

    print(f"[PASS] {TOOL}: every ES-module file that uses `require` also binds "
          f"the name; {census_line}")
    return RC_PASS


if __name__ == "__main__":
    raise SystemExit(main())
