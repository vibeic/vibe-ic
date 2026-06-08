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


_PORT_DECL_RE = re.compile(
    r"(input|output|inout)\s+(?:wire|reg|logic)?\s*(\[[^\]]+\])?\s*(\w+)")


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def parse_module_ports(rtl_text: str, module: str) -> List[Tuple[str, str, str]]:
    """Return [(direction, width, name)] for the ANSI port list of
    `module <module>(...)`. Empty list when the module has no ANSI ports."""
    text = _strip_comments(rtl_text)
    m = re.search(rf"module\s+{re.escape(module)}\s*\(\s*(.*?)\s*\)\s*;",
                  text, re.DOTALL)
    if not m:
        return []
    return [(pm.group(1), (pm.group(2) or "").strip(), pm.group(3))
            for pm in _PORT_DECL_RE.finditer(m.group(1))]


def emit_alias_wrapper(leaf_name: str, canonical_name: str,
                       ports: List[Tuple[str, str, str]]) -> str:
    """Render a thin alias wrapper module named `canonical_name` that
    instantiates `leaf_name` and passes every port straight through (1:1)."""
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
        f"module {canonical_name} (",
        ",\n".join(decls),
        ");",
        f"    {leaf_name} u_{leaf_name} (",
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

    ports = parse_module_ports(rtl.read_text(errors="replace"), args.leaf)
    if not ports:
        print(f"error: leaf module {args.leaf!r} not found / no ANSI ports in "
              f"{rtl} — cannot emit a passthrough alias.", file=sys.stderr)
        return 1

    wrapper = emit_alias_wrapper(args.leaf, canonical, ports)
    out = Path(args.out) if args.out else rtl.with_name(f"{canonical}.v")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(wrapper)
    print(f"ok: leaf {args.leaf!r} is a typo of {canonical!r}; wrote alias "
          f"wrapper {out} (ports={len(ports)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
