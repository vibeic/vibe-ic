"""Extract crypto architecture parameters from README/text docs.

v1.6.106 — addresses GitHub issue #36 Bug 4 (P1).

v1.6.108 — addresses GitHub issue #40 Bug 4A (P1):

  * `_MESSAGE_BLOCK_RE` no longer matches "64-bit block counter"
    (chacha README says exactly that and v1.6.106 picked up
    `message_block_bits=64` from it). New ±20-char context window
    rejects the match when "counter" appears nearby.
  * `_ROUNDS_*` scan now prefers values adjacent to ``default``,
    ``standard``, ``recommended`` or ``fixed`` over ``up to`` /
    ``maximum`` / ``settable``. ChaCha "default 8, settable up to
    32 rounds" now extracts 8 (not 32).
  * Added `key_bits` and `nonce_bits` patterns (chacha README
    mentions both prosely; today they were missing).

v1.6.110 — addresses GitHub issue #42 (P2 follow-up to #40 Bug 4A):

  * `_ROUNDS_DEFAULT_RE` now accepts English number words (one..
    twenty + twenty-four / twenty-eight / thirty-two / forty /
    sixty-four) in addition to digits. ChaCha README writes
    "the default number of rounds is **eight**" and v1.6.108's
    digit-only Pass 1 missed it.
  * `_ROUNDS_RANGE_OR_UPPER_BOUND_RE` extends v1.6.108's narrower
    `_ROUNDS_UPPER_BOUND_RE` with range phrasing ("from N to M",
    "between N and M", "in steps of", "supports any number of").
    ChaCha README writes "supports any number of rounds from two
    to 32 in steps of two" — v1.6.108 didn't reject this shape so
    Pass 3 grabbed "32 rounds".
  * `_word_or_digit_to_int` helper converts the captured token
    uniformly; unrecognized words return None (not 0, not crash).

Class-conditional default fallbacks (state_bits=512, key_bits=256
for chacha when no prose match) — deferred per #40 4A part (b).

Patterns target prose like:

  "256-bit digest"            → digest_width_bits=256
  "512-bit message block"     → message_block_bits=512
  "256-bit state"             → state_bits=256
  "10 rounds" / "8/20 rounds" → rounds=10  (default-aware)
  "66 cycles per block"       → latency_cycles_per_block=66
  "256-bit key"               → key_bits=256
  "96-bit nonce"              → nonce_bits=96

Each successfully extracted field gets a sibling ``<field>_evidence``
dict carrying source / line / matched_token / extraction_strategy.

First-match-wins per field — never aggregates, never overwrites later
mentions. This keeps the output stable on README files that mention
"rounds" several times in different contexts.

Class-conditional gating happens at the call site (crypto_block_cipher,
crypto_stream_cipher, crypto_hash) — saves cycles + avoids false
positives in unrelated prose for non-crypto chips.
"""

from __future__ import annotations

import re
from typing import Dict, Optional, Tuple


_DIGEST_WIDTH_RE = re.compile(
    r"\b(\d+)\s*[-\s]?bit\s+digest\b", re.IGNORECASE)
_MESSAGE_BLOCK_RE = re.compile(
    r"\b(\d+)\s*[-\s]?bit\s+(?:message\s+)?block\b", re.IGNORECASE)
_STATE_BITS_RE = re.compile(
    r"\b(\d+)\s*[-\s]?bit\s+state\b", re.IGNORECASE)
_LATENCY_CYCLES_RE = re.compile(
    r"\b(\d+)\s+cycles?(?:\s+per\s+block)?\b", re.IGNORECASE)

# v1.6.108 — key/nonce patterns
_KEY_BITS_RE = re.compile(
    r"\b(\d+)\s*[-\s]?bit\s+key\b", re.IGNORECASE)
_NONCE_BITS_RE = re.compile(
    r"\b(\d+)\s*[-\s]?bit\s+(?:nonce|iv|initialization\s+vector)\b",
    re.IGNORECASE)

# v1.6.110 — English number-word lookup for default-rounds extraction.
# Sorted-by-length-desc when used in regex alternation so "twenty-four"
# wins over "twenty" etc.
_NUM_WORD_TO_INT = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "twenty-four": 24,
    "twenty-eight": 28, "thirty-two": 32, "forty": 40, "sixty-four": 64,
}
_NUM_WORD_OR_DIGIT_PATTERN = (
    r"(\d+|"
    + "|".join(
        re.escape(w) for w in sorted(
            _NUM_WORD_TO_INT.keys(), key=len, reverse=True
        )
    )
    + r")"
)


def _word_or_digit_to_int(s: str) -> Optional[int]:
    """v1.6.110 — convert a token captured by `_NUM_WORD_OR_DIGIT_PATTERN`
    into an int. Returns None for unrecognized tokens (defensive — never
    raises, never returns 0 for unknown words).
    """
    if s is None:
        return None
    s_lower = s.lower()
    if s_lower in _NUM_WORD_TO_INT:
        return _NUM_WORD_TO_INT[s_lower]
    try:
        return int(s)
    except ValueError:
        return None


# v1.6.108 — rounds: default/standard preferred, upper-bound rejected.
# v1.6.110 — Extension A: accept English number words for the default
# value (chacha README: "the default number of rounds is eight").
_ROUNDS_DEFAULT_RE = re.compile(
    r"(?:default|standard|recommended|fixed)\s+"
    r"(?:number\s+of\s+)?"
    r"rounds?\s+"
    r"(?:is|=|to)?\s*"
    + _NUM_WORD_OR_DIGIT_PATTERN
    + r"\b",
    re.IGNORECASE,
)
# v1.6.108 — original narrow upper-bound regex.
# Kept for back-compat: external callers importing _ROUNDS_UPPER_BOUND_RE
# from v1.6.108 still see the same name.
_ROUNDS_UPPER_BOUND_RE = re.compile(
    r"(?:up\s+to|max(?:imum)?|settable\s+(?:up\s+)?to|at\s+most)"
    r"\s+(\d+)\s+rounds?",
    re.IGNORECASE)
# v1.6.110 — Extension B: detect range/upper-bound phrasing anywhere
# in the line. v1.6.108 only handled "up to|max|at most|settable to";
# chacha README uses "from two to 32 rounds in steps of two" + "supports
# any number of rounds" which fall through. When ANY of these match we
# treat the entire line as range-talk (not a default value).
#
# Two regex flavours:
#   * `_ROUNDS_BOUND_PHRASE_RE` — line-level detector (presence test).
#     Matches range-phrasing keywords whether or not they immediately
#     touch "rounds" (e.g. "in steps of two" sits separately from the
#     rounds token).
#   * `_ROUNDS_BOUND_NEAR_ROUNDS_RE` — narrow form for sub-stripping
#     the "X rounds" / "from N to M rounds" / "up to M rounds" mention,
#     so a remaining default value on the same line can still win.
_ROUNDS_BOUND_PHRASE_RE = re.compile(
    r"(?:up\s+to|max(?:imum)?|at\s+most|settable\s+(?:up\s+)?to|"
    r"from\s+\S+\s+to\s+\S+|between\s+\S+\s+and\s+\S+|"
    r"in\s+steps\s+of|supports\s+any\s+(?:number\s+of\s+)?)",
    re.IGNORECASE,
)
_ROUNDS_BOUND_NEAR_ROUNDS_RE = re.compile(
    r"(?:up\s+to|max(?:imum)?|at\s+most|settable\s+(?:up\s+)?to|"
    r"from\s+\S+\s+to|between\s+\S+\s+and|"
    r"supports\s+any\s+(?:number\s+of\s+)?)"
    r"\s+(?:\S+\s+)*?rounds?",
    re.IGNORECASE,
)
# Back-compat alias — preserves the v1.6.108 name but points at the
# broader v1.6.110 detector. Anything that imported the old name now
# rejects the broader set.
_ROUNDS_RANGE_OR_UPPER_BOUND_RE = _ROUNDS_BOUND_NEAR_ROUNDS_RE
_ROUNDS_GENERIC_RE = re.compile(
    r"\b(\d+)(?:\s*/\s*(\d+))?\s+rounds?\b", re.IGNORECASE)

# Back-compat alias — keeps any external caller importing _ROUNDS_RE
# from v1.6.106 still importable.
_ROUNDS_RE = _ROUNDS_GENERIC_RE


def _scan(text: str, pattern, group_idx: int = 1
          ) -> Optional[Tuple[int, int, str]]:
    """Return (value_int, line_no, matched_str) on first match.

    Returns ``None`` if no line matches.
    """
    for lineno, line in enumerate(text.split("\n"), start=1):
        m = pattern.search(line)
        if m:
            try:
                val = int(m.group(group_idx))
                return val, lineno, m.group(0)
            except (ValueError, IndexError):
                continue
    return None


def _scan_message_block(text: str
                        ) -> Optional[Tuple[int, int, str]]:
    """v1.6.108 (#40 Bug 4A) — match ``N-bit (message) block`` but
    REJECT when "counter" appears within ±20 chars of the match
    (chacha README: "64-bit block counter").
    """
    for lineno, line in enumerate(text.split("\n"), start=1):
        m = _MESSAGE_BLOCK_RE.search(line)
        if not m:
            continue
        start = max(0, m.start() - 20)
        end = min(len(line), m.end() + 20)
        context = line[start:end].lower()
        if "counter" in context:
            continue  # "block counter", not message block
        try:
            return int(m.group(1)), lineno, m.group(0)
        except (ValueError, IndexError):
            continue
    return None


def _scan_rounds(text: str
                 ) -> Optional[Tuple[int, int, str]]:
    """v1.6.108 (#40 Bug 4A) + v1.6.110 (#42) — prefer default-adjacent
    rounds over range / upper-bound mentions.

    Order:
      1. ``default|standard|recommended|fixed [number of] rounds [is|=|to]
         <digit-or-word>`` (any line) → take it immediately. v1.6.110
         accepts English number words (eight, twelve, thirty-two, ...).
      2. Otherwise iterate lines; on each:
         * if the line contains a range / upper-bound phrase
           ("up to N rounds" / "from two to 32 rounds" / "in steps of"
           / "supports any number of"), strip the rounds-mention and
           try the generic regex on the remainder. If a default-style
           number is left over, take it; else skip the line entirely.
         * else apply the generic regex.
    """
    # Pass 1 — explicit default (digit OR English number word).
    for lineno, line in enumerate(text.split("\n"), start=1):
        m = _ROUNDS_DEFAULT_RE.search(line)
        if m:
            val = _word_or_digit_to_int(m.group(1))
            if val is not None:
                return val, lineno, m.group(0)
            # Unrecognized word → fall through; keep scanning.

    # Pass 2 — generic, with range/upper-bound deny.
    for lineno, line in enumerate(text.split("\n"), start=1):
        # First filter: does this line contain ANY range-phrase
        # marker? If yes, treat it as range-talk.
        if _ROUNDS_BOUND_PHRASE_RE.search(line):
            stripped = _ROUNDS_BOUND_NEAR_ROUNDS_RE.sub(" ", line)
            # If, after stripping the bounded "X rounds" mention, a
            # plain "<N> rounds" still survives in the same line, take
            # that. Otherwise skip (line was pure range-talk).
            m_alt = _ROUNDS_GENERIC_RE.search(stripped)
            if m_alt:
                try:
                    return int(m_alt.group(1)), lineno, m_alt.group(0)
                except (ValueError, IndexError):
                    continue
            continue  # pure range/upper-bound mention — skip line
        m = _ROUNDS_GENERIC_RE.search(line)
        if m:
            try:
                return int(m.group(1)), lineno, m.group(0)
            except (ValueError, IndexError):
                continue
    return None


def extract_crypto_arch(readme_text: str) -> Dict:
    """Return dict with keys for each successfully extracted field
    plus per-field evidence in ``<field>_evidence``.

    Empty dict when ``readme_text`` is empty or no patterns match.
    """
    out: Dict = {}
    if not readme_text:
        return out

    # Spec table — (field, scanner). Bespoke scanners run for
    # message_block (counter-aware) and rounds (default-aware);
    # others use the generic _scan helper.
    field_specs = [
        ("digest_width_bits", lambda t: _scan(t, _DIGEST_WIDTH_RE)),
        ("message_block_bits", _scan_message_block),
        ("state_bits", lambda t: _scan(t, _STATE_BITS_RE)),
        ("rounds", _scan_rounds),
        ("latency_cycles_per_block",
         lambda t: _scan(t, _LATENCY_CYCLES_RE)),
        # v1.6.108 — added per #40 Bug 4A
        ("key_bits", lambda t: _scan(t, _KEY_BITS_RE)),
        ("nonce_bits", lambda t: _scan(t, _NONCE_BITS_RE)),
    ]

    for field, scanner in field_specs:
        result = scanner(readme_text)
        if result is not None:
            val, lineno, matched = result
            out[field] = val
            out[f"{field}_evidence"] = {
                "source": "input/docs/README.md",
                "line": lineno,
                "matched_token": matched,
                "extraction_strategy": "crypto_arch_pattern_match",
            }

    # TODO(#40 Bug 4A part b): class-conditional default fallbacks
    # (state_bits=512, key_bits=256 for chacha-class when no prose
    # match) — deferred to a future release; per issue body this is
    # explicitly out of scope for v1.6.108 to keep the patch lean
    # and free of "domain-knowledge baked-in" defaults.

    return out
