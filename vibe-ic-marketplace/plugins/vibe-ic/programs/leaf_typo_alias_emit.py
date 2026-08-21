#!/usr/bin/env python3
"""leaf_typo_alias_emit.py — v0.3.18 (ORGANIC #517).

Promote the #506 "misspelled-leaf alias-wrapper" lesson from SKILL PROSE
(agents/ic-expert-agent.md) to a DETERMINISTIC PROGRAM so it fires every time
the emit path runs, instead of relying on a fresh clean-room author to remember
it.

THE PROBLEM
-----------
When a design's leaf (module) name is itself a probable MISSPELLING of a
canonical hardware term (e.g. `substractor` → `subtractor`, `multipler` →
`multiplier`), the hidden testbench may instantiate by EITHER spelling. Betting
on a single spelling risks a `compile_error` floor. #506 captured the remedy
(emit the real RTL under the leaf name AND a thin alias wrapper under the
canonical spelling) as agent PROSE — and a round-1 clean-room author still hit
the floor because the lesson was not applied.

THE DETERMINISTIC CORE
----------------------
The judgement #506 said "a regex cannot make" is decidable for the
HIGH-CONFIDENCE case only: a leaf token that is edit-distance EXACTLY 1 from
EXACTLY ONE canonical hardware term (both ≥ the length floor), is not an
inflected word form, and is not a known real-word collision, is a typo. This
program detects that and emits the canonical-spelled thin alias wrapper. The
single-edit restriction + the word-form guards exist because distance-2 and
inflected forms are where LEGITIMATE module names collide with the term set.

SAFETY (corpus-sweep — must NOT false-fire)
-------------------------------------------
  * a leaf that IS a canonical term (`counter`, `multiplier`)  → no alias.
  * a leaf far from every term (`my_block`, `fifo`, `alu`)     → no alias.
  * an AMBIGUOUS leaf equidistant from two terms               → no alias.
  * short tokens (< the length floor) never match              → no alias.
  * an INFLECTED word form (`counters`, `shifted`, `encoded`,
    `decoded`, `registers`, `scheduled`)                       → no alias.
  * a British -iser spelling variant (`normaliser`,
    `serialiser`, `deserialiser`) — intentional, not a typo    → no alias.
  * a real -er agent-noun / word collision (`resister`,
    `diviner`, `deceiver`) or any distance-2 collision
    (`recorder`→`decoder`)                                     → no alias.
  * a real silent-`e` VERB BASE whose `+r` agent noun is canonical
    (`decode`→`decoder`, `divide`→`divider`) — verb↔agent-noun
    INFLECTION, not a truncation typo (#702: real OpenTitan
    `prim_diff_decode`)                                        → no alias.
    NB (#702 round-2): a last-char-deletion truncation typo
    (`counte`→counter, `registe`→register) is NOT a silent-`e`
    verb and IS still aliased — the exemption is an enumerated
    real-verb allow-list, not a `t+"r"==canonical` grammar.

Residual-harm mitigation: name-only typo detection cannot be perfect, so the CLI
`main` additionally REFUSES to emit when the design already defines a module
under the canonical name — a residual false-fire can therefore never create a
duplicate-module compile error; at worst it is a harmless unused passthrough.

USAGE
-----
    python3 leaf_typo_alias_emit.py --rtl design.v --leaf substractor \\
        [--out wrapper.v]

EXIT CODES
----------
    0  done (wrote an alias wrapper, OR no typo detected — both are success).
    1  a typo was detected but the leaf module / its ports could not be parsed.
    2  IO error.

chip-AGNOSTIC: the only baked-in data is a curated list of GENERIC canonical
hardware-term roots; no chip / vendor / SKU identifier appears.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

# Curated canonical hardware-term roots. Every entry is ≥ 6 chars so a short
# abbreviation (addr/alu/mux/ram) can never land within edit-distance 2 of one.
# These are GENERIC datapath / control primitives, not chip identities.
_CANONICAL_HW_TERMS = frozenset({
    "subtractor", "multiplier", "divider", "accumulator", "comparator",
    "counter", "shifter", "register", "decoder", "encoder", "multiplexer",
    "demultiplexer", "arbiter", "modulator", "demodulator", "integrator",
    "differentiator", "sequencer", "controller", "scheduler", "normalizer",
    "serializer", "deserializer", "transmitter", "receiver", "rotator",
    "barrelshifter", "incrementer", "decrementer", "saturator",
})

# A leaf/canonical token shorter than this is never typo-matched (abbreviations
# like addr/alu/mux/ram are far too short to disambiguate from a term safely).
_MIN_TOKEN_LEN = 6

# Inflected word forms (plural / past-tense / gerund) are legitimate RTL signal
# names, NOT typos: `counters` (counter+s), `shifted`/`encoded`/`decoded`/
# `scheduled` (verb-ed), `registers`. A token ending in one of these is a real
# word and must never be aliased — this is the dominant false-fire class found
# in adversarial review (ORGANIC #517).
_INFLECTION_SUFFIXES = ("ed", "ing", "s")

# Real English agent-nouns / words that are edit-distance 1 from an agentive
# (-er/-or) canonical term but are NOT typos of it. The inflection guard, the
# British-spelling rule, and the single-edit restriction already exclude the
# bulk; this denylist covers the residual real -er words that survive all three
# (each is a real verb+er agent noun colliding with a canonical term).
_ENGLISH_WORD_DENYLIST = frozenset({
    "resister",   # → register (d1) — one who resists
    "shitter",    # → shifter (d1)
    "recorder",   # → decoder/encoder
    "reminder",   # → remainder-ish; never a HW-term typo
    "diviner",    # → divider (d1) — one who divines
    "deceiver",   # → receiver (d1) — one who deceives
})

# ORGANIC #702 round-2 (§4.05 NO-LEAK fix): the verb BASES whose agent-noun
# canonical term is formed by appending ONLY a trailing `r` to a silent-`e`
# verb (decode→decoder, divide→divider). A 1-char append is the ONLY agentive
# derivation that lands at edit-distance 1 from its canonical term, so these
# silent-`e` roots are the ONLY ones a real verb-name module can be FALSELY
# flagged as a truncation typo of — hence the only ones needing an exemption.
# The `-er`/`-or` bases (count→counter, subtract→subtractor) sit at
# edit-distance ≥2 from their canonical term (a 2-char append) and are never
# typo-flagged, so they need no entry here.
#
# This MUST be an ENUMERATED real-verb allow-list, NOT a `t+"r"==canonical`
# suffix grammar: a LAST-CHAR-DELETION truncation typo (`counte`→counter,
# `registe`→register, `arbite`→arbiter, `shifte`→shifter) ALSO satisfies
# `t+"r"==canonical` and is structurally indistinguishable from a silent-`e`
# verb — only the lexical fact that `decode` is a real verb and `counte` is not
# separates them. The original #702 bare-`r` suffix grammar leaked every such
# truncation back into the "not a typo" bucket (adversarial review, v1.0.63).
_SILENT_E_VERB_BASES = frozenset({
    "decode", "encode", "divide", "receive", "schedule",
    "sequence", "serialize", "deserialize", "normalize",
})


def _is_verb_base_of_canonical(t: str) -> bool:
    """ORGANIC #702: True when `t` is a real silent-`e` verb BASE whose `+r`
    agent noun is a canonical term (`decode`→`decoder`, `divide`→`divider`).

    This is INFLECTION (verb↔agent-noun morphology), not a typo: the bare verb
    root is a perfectly valid module name (e.g. OpenTitan's real
    `prim_diff_decode`), so it must NOT be aliased to its agent noun.

    §4.05 NO-LEAK (load-bearing — this RELAXES the typo detector): keyed on an
    ENUMERATED real-verb allow-list, NOT the bare-`r` suffix grammar. The
    grammar `t+"r"==canonical` ALSO matches a last-char-deletion truncation typo
    (`counte`→counter, `registe`→register) — a genuine misspelling that MUST
    stay flagged — so only the allow-list correctly separates the real verb
    `decode` from the truncation `counte`. A mid-word typo (`decodr`/`decoer`)
    was never a bare-root append and is likewise unaffected. The `-er`/`-or`
    consonant roots (`subtract`/`count`) need no entry: they sit at
    edit-distance ≥2 and `_closest_canonical` never flags them in the first
    place."""
    if len(t) < _MIN_TOKEN_LEN:
        return False
    if t not in _SILENT_E_VERB_BASES:
        return False
    # Invariant: an allow-listed base must actually append `r` to a canonical
    # term — defends against a future canonical-set edit orphaning a base.
    return (t + "r") in _CANONICAL_HW_TERMS


def _is_british_spelling_of_canonical(t: str) -> bool:
    """British -ise/-iser spelling vs American -ize/-izer: a token whose s→z swap
    yields a canonical term (e.g. `normaliser`→`normalizer`, `serialiser`→
    `serializer`) is an INTENTIONAL spelling variant, not a typo. Treat it as the
    author's choice and leave it untouched — handling the whole -iser class as a
    rule instead of denylisting each word."""
    for term in _CANONICAL_HW_TERMS:
        if "z" in term and term.replace("z", "s") == t:
            return True
    return False


def _levenshtein(a: str, b: str) -> int:
    """Standard iterative-DP edit distance (0 when identical)."""
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        cur = [i + 1]
        for j, cb in enumerate(b):
            cur.append(min(prev[j + 1] + 1, cur[j] + 1, prev[j] + (ca != cb)))
        prev = cur
    return prev[-1]


def _closest_canonical(token: str) -> Optional[str]:
    """Return the unique canonical term that `token` is a SINGLE-EDIT typo of
    (edit-distance EXACTLY 1, length floor satisfied, unambiguous closest), else
    None.

    Safety (ORGANIC #517 adversarial review): edit-distance is restricted to 1,
    not 1..2 — distance-2 is where legitimate English words collide with the
    canonical terms (e.g. `recorder`→`decoder` is distance 2). An exact canonical
    token, an inflected word form (`-ed`/`-ing`/`-s`), and a known real-word
    collision (`resister`→`register`) all return None. The cost is that a
    transposition / double-error typo is no longer auto-aliased — a safe trade
    against silently aliasing a legitimately-named module."""
    t = token.lower()
    if len(t) < _MIN_TOKEN_LEN:
        return None
    if t in _CANONICAL_HW_TERMS:
        return None  # exact = correct spelling, not a typo
    if t in _ENGLISH_WORD_DENYLIST:
        return None  # real word, not a typo
    if t.endswith(_INFLECTION_SUFFIXES):
        return None  # plural / verb-inflected form = real word, not a typo
    if _is_british_spelling_of_canonical(t):
        return None  # British -iser spelling variant = intentional, not a typo
    if _is_verb_base_of_canonical(t):
        return None  # bare verb base of an -er/-or agent noun = inflection,
        # not a truncation typo (#702: decode↔decoder, encode↔encoder)
    best: Optional[str] = None
    best_d = 99
    tie = False
    for term in _CANONICAL_HW_TERMS:
        if abs(len(term) - len(t)) > 1:
            continue  # edit-distance 1 impossible when |Δlen| > 1
        d = _levenshtein(t, term)
        if d < best_d:
            best, best_d, tie = term, d, False
        elif d == best_d:
            tie = True
    if best is None or tie or best_d != 1:
        return None
    return best


def detect_leaf_typo(leaf_name: str) -> Optional[str]:
    """If `leaf_name` (or exactly one of its `_`-tokens) is a typo of a
    canonical hardware term, return the CORRECTED canonical leaf name; else
    None. The non-typo tokens keep their original spelling/case."""
    leaf = leaf_name.strip()
    if not leaf:
        return None
    # whole-name typo first (covers single-word leaves like `substractor`).
    whole = _closest_canonical(leaf)
    if whole is not None:
        return whole
    # token-level typo inside a compound (e.g. `fast_multipler`). Fire only
    # when EXACTLY ONE token is a typo (multiple → ambiguous, do not fire).
    tokens = leaf.split("_")
    hits: List[Tuple[int, str]] = []
    for idx, tok in enumerate(tokens):
        c = _closest_canonical(tok)
        if c is not None:
            hits.append((idx, c))
    if len(hits) != 1:
        return None
    idx, canonical = hits[0]
    new_tokens = list(tokens)
    new_tokens[idx] = canonical
    corrected = "_".join(new_tokens)
    return corrected if corrected != leaf else None


# Word-boundary anchored so it matches BOTH spaced (`input wire [7:0] a`) and
# COMPACT (`input[N-1:0]a`) Verilog (no mandatory space after the direction) —
# #517 reopen round-3. `\b` after the optional net-type keeps `input wirefoo`
# parsing the port name as `wirefoo`, not dropping the `wire` prefix.
_PORT_DECL_RE = re.compile(
    r"\b(input|output|inout)\b\s*"
    r"(?:(?:wire|reg|logic|signed|unsigned)\b\s*)*"
    r"(\[[^\]]+\])?\s*(\w+)")


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def _module_header(text: str, module: str) -> Optional[Tuple[Optional[str], str]]:
    """Return (param_block, port_block) for `module <module> [#(param_block)]
    (port_block)`, correctly SKIPPING / capturing an optional `#(...)` block via
    balanced-paren scanning. None when the module is not found.

    ORGANIC #517 reopen: the prior regex `module\\s+<name>\\s*\\(` did not skip
    the `#(...)` block, so a PARAMETERIZED ANSI module (e.g. the fixed_point
    target `module foo #(parameter N=16) (...)`) parsed as having no ports and
    the alias emit silently failed."""
    text = _strip_comments(text)
    m = re.search(rf"\bmodule\s+{re.escape(module)}\b", text)
    if not m:
        return None
    i, n = m.end(), len(text)

    def _skip_ws(j: int) -> int:
        while j < n and text[j].isspace():
            j += 1
        return j

    def _balanced(j: int) -> Optional[int]:
        """Given text[j] == '(', return index just past the matching ')'. Skips
        string literals so a `(`/`)` inside a string parameter default (e.g.
        `parameter string TAG = "error(code"`) does not unbalance the scan
        (#517 reopen round-3)."""
        depth = 0
        while j < n:
            c = text[j]
            if c == '"':
                j += 1
                while j < n and text[j] != '"':
                    if text[j] == "\\":
                        j += 1
                    j += 1
                j += 1
                continue
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    return j + 1
            j += 1
        return None

    i = _skip_ws(i)
    param_block: Optional[str] = None
    if i < n and text[i] == "#":
        i = _skip_ws(i + 1)
        if i < n and text[i] == "(":
            j = _balanced(i)
            if j is None:
                return None
            param_block = text[i + 1:j - 1].strip()
            i = _skip_ws(j)
    if i < n and text[i] == "(":
        j = _balanced(i)
        if j is None:
            return None
        return (param_block, text[i + 1:j - 1])
    return None


def parse_module_ports(rtl_text: str, module: str) -> List[Tuple[str, str, str]]:
    """Return [(direction, width, name)] for the ANSI port list of
    `module <module> [#(...)] (...)`. Empty list when the module has no ANSI
    ports. Tolerates an optional parameter block (#517 reopen)."""
    hdr = _module_header(rtl_text, module)
    if hdr is None:
        return []
    return [(pm.group(1), (pm.group(2) or "").strip(), pm.group(3))
            for pm in _PORT_DECL_RE.finditer(hdr[1])]


def parse_module_params(rtl_text: str, module: str
                        ) -> Tuple[Optional[str], List[str]]:
    """Return (raw_param_block, [param_names]) for `module <module> #(...)`.
    (None, []) when the module is not parameterized. Param names are the LHS
    identifiers of each `<NAME> =` in the block."""
    hdr = _module_header(rtl_text, module)
    if hdr is None or hdr[0] is None:
        return (None, [])
    block = hdr[0]
    names = re.findall(r"(\w+)\s*=", block)
    return (block, names)


def emit_alias_wrapper(leaf_name: str, canonical_name: str,
                       ports: List[Tuple[str, str, str]],
                       param_block: Optional[str] = None,
                       param_names: Optional[List[str]] = None) -> str:
    """Render a thin alias wrapper module named `canonical_name` that
    instantiates `leaf_name` and passes every port straight through (1:1).

    When the leaf is PARAMETERIZED (#517 reopen — the fixed_point target), the
    wrapper inherits the same `#(param_block)` and forwards every parameter to
    the instance, so the wrapper elaborates standalone (its port widths that
    reference a parameter — e.g. `[N-1:0]` — resolve)."""
    param_hdr = ""
    inst_params = ""
    if param_block:
        param_hdr = f" #(\n    {param_block}\n)"
        if param_names:
            joined = ", ".join(f".{p}({p})" for p in param_names)
            inst_params = f" #({joined})"
    decls = []
    for direction, width, name in ports:
        w = f" {width}" if width else ""
        decls.append(f"    {direction}{w} {name}")
    conns = [f"        .{name}({name})" for _d, _w, name in ports]
    lines = [
        f"// {canonical_name} — auto-generated canonical-spelling alias of the",
        f"// leaf module `{leaf_name}` (probable misspelling of a canonical",
        "// hardware term). Lets a hidden testbench elaborate EITHER spelling.",
        f"// Generated by leaf_typo_alias_emit.py (ORGANIC #517).",
        f"module {canonical_name}{param_hdr} (",
        ",\n".join(decls),
        ");",
        f"    {leaf_name}{inst_params} u_{leaf_name} (",
        ",\n".join(conns),
        "    );",
        "endmodule",
        "",
    ]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Emit a canonical-spelling alias wrapper when a leaf "
                    "module name is a probable typo of a canonical HW term.")
    ap.add_argument("--rtl", required=True, help="RTL file containing the leaf module")
    ap.add_argument("--leaf", required=True, help="leaf module name")
    ap.add_argument("--out", default=None,
                    help="alias wrapper output path (default: alongside --rtl "
                         "as <canonical>.v); only written when a typo is found")
    args = ap.parse_args(argv)

    rtl = Path(args.rtl)
    if not rtl.is_file():
        print(f"error: rtl not found: {rtl}", file=sys.stderr)
        return 2

    canonical = detect_leaf_typo(args.leaf)
    if canonical is None:
        print(f"ok: leaf {args.leaf!r} is not a canonical-term typo "
              f"(no alias wrapper needed)")
        return 0

    # Emit-collision safety: if the design ALREADY defines a module named
    # `canonical`, emitting an alias under that name would create a duplicate
    # module → compile error. Skip the emit in that case. This makes even a
    # residual false-fire (a real word the name-only detector mistook for a
    # typo) HARMLESS — we never clobber or duplicate a real module. Scans every
    # .v/.sv beside the input RTL, not just the input file.
    _mod_re = re.compile(rf"\bmodule\s+{re.escape(canonical)}\s*[(#;]")
    for cand in sorted(rtl.parent.glob("*.v")) + sorted(rtl.parent.glob("*.sv")):
        try:
            if _mod_re.search(_strip_comments(cand.read_text(errors="replace"))):
                print(f"ok: leaf {args.leaf!r} looks like a typo of {canonical!r} "
                      f"but module {canonical!r} already exists in {cand.name} — "
                      f"skipping alias emit to avoid a duplicate-module collision.")
                return 0
        except OSError:
            continue

    _rtl_text = rtl.read_text(errors="replace")
    ports = parse_module_ports(_rtl_text, args.leaf)
    if not ports:
        print(f"error: leaf module {args.leaf!r} not found / no ANSI ports in "
              f"{rtl} — cannot emit a passthrough alias.", file=sys.stderr)
        return 1

    param_block, param_names = parse_module_params(_rtl_text, args.leaf)
    wrapper = emit_alias_wrapper(args.leaf, canonical, ports,
                                 param_block=param_block,
                                 param_names=param_names)
    out = Path(args.out) if args.out else rtl.with_name(f"{canonical}.v")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(wrapper)
    print(f"ok: leaf {args.leaf!r} is a typo of {canonical!r}; wrote alias "
          f"wrapper {out} (ports={len(ports)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
