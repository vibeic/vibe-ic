"""v1.6.114 — for #36 Bug 2: README "usage sequence" / numbered-step picker.

Many crypto / register-driven IPs document their host-side usage as
an ordered markdown list, e.g. (verbatim from the field-agent's #36
deferred-bug list):

    1. Load key into key registers
    2. Set length bit in ctrl
    3. Write init bit
    4. Wait for ready
    5. Read digest

These numbered steps are unambiguous evidence of the host→device
sequence the IP expects. When the L3 layer has no `opcodes` (the
case for AES / SHA-1 / SHA-256 / ChaCha — register-driven, not
opcode-driven), the L12 generator emits an empty
``behavioral_sequences`` and flags ``no_behavioral_sequences_in_input``
even though the README literally spells out the sequence.

This module scans README markdown for sufficiently long sequences
of consecutively-numbered list items that look like imperative
host commands, and surfaces them as structured steps.

Chip-AGNOSTIC. Pure regex + structural heuristics. Defensive against
false positives via:

  * minimum-length floor (≥3 consecutive items),
  * monotone-increasing numbers (1, 2, 3, ...) — a number reset
    starts a NEW sequence,
  * imperative-verb floor (≥half of the items must begin with a
    capitalised imperative verb from a generic vocabulary —
    Load / Set / Write / Read / Wait / Send / Configure / etc.),
  * minimum item-text length (≥6 chars after the `N.` prefix).
"""
from __future__ import annotations

import re
from typing import List, Optional

# Markdown numbered-list line.
_NUMBERED_LINE_RE = re.compile(
    r"^\s*(\d+)[.)]\s+(.+?)\s*$",
    re.MULTILINE,
)

# Generic imperative verbs that mark a step as a host action.
# Chip-AGNOSTIC: these are common across crypto / register-driven /
# protocol IPs. The check is "first whitespace-delimited word
# capitalised AND in this set" — bare prose lines like "1. The IP
# performs ..." don't match.
_IMPERATIVE_VERBS = frozenset({
    "load", "loads", "set", "sets", "write", "writes", "read", "reads",
    "wait", "waits", "send", "sends", "configure", "configures",
    "initialize", "initialise", "init", "trigger", "triggers",
    "start", "starts", "stop", "stops", "reset", "resets",
    "clear", "clears", "assert", "asserts", "deassert", "deasserts",
    "poll", "polls", "check", "checks", "verify", "verifies",
    "issue", "issues", "select", "selects", "enable", "enables",
    "disable", "disables", "fetch", "fetches", "drive", "drives",
    "apply", "applies", "release", "releases", "perform", "performs",
    "compute", "computes", "compare", "compares", "store", "stores",
    "fill", "fills", "push", "pushes", "pop", "pops",
    "request", "requests", "acknowledge", "acknowledges",
    "transmit", "transmits", "receive", "receives",
})

_MIN_STEPS = 3
_MIN_ACTION_LEN = 6  # chars after "<N>. "
_MIN_IMPERATIVE_FRACTION = 0.5


def _first_word_lower(text: str) -> str:
    m = re.match(r"\s*([A-Za-z]+)", text)
    return m.group(1).lower() if m else ""


def extract_usage_sequence_from_readme(
    readme_text: Optional[str],
) -> List[dict]:
    """Return a list of usage-sequence dicts found in the README.

    Each dict is shaped like the existing L12.behavioral_sequences
    entries:

        {
            "name":     "usage_sequence_<index>",
            "trigger":  "host_initiates",
            "steps":    [
                {"step": 1, "action": "Load key into key registers",
                 "evidence_line": L},
                ...
            ],
            "source":   "readme_usage_sequence",
        }

    Multiple disjoint numbered lists in a README each become a
    separate sequence (consecutive lists separated by reset of the
    counter or by ≥1 non-list line break).

    Empty list when the README has no qualifying sequence.

    Chip-AGNOSTIC.
    """
    if not readme_text:
        return []

    lines = readme_text.split("\n")
    sequences: List[dict] = []
    current_steps: List[dict] = []
    last_num: int = 0

    def _flush() -> None:
        nonlocal current_steps, last_num
        if len(current_steps) >= _MIN_STEPS:
            # Imperative-verb fraction floor.
            imperative_count = sum(
                1 for s in current_steps
                if _first_word_lower(s["action"]) in _IMPERATIVE_VERBS
            )
            if imperative_count / len(current_steps) >= _MIN_IMPERATIVE_FRACTION:
                idx = len(sequences) + 1
                sequences.append({
                    "name":    f"usage_sequence_{idx}",
                    "trigger": "host_initiates",
                    "steps":   list(current_steps),
                    "source":  "readme_usage_sequence",
                })
        current_steps = []
        last_num = 0

    for line_num, line in enumerate(lines, start=1):
        m = _NUMBERED_LINE_RE.match(line)
        if not m:
            # A non-numbered line ends the current sequence iff it
            # is non-blank prose (blank lines are tolerated inside
            # markdown lists).
            if line.strip():
                _flush()
            continue
        num = int(m.group(1))
        action = m.group(2).strip()
        # Strip surrounding markdown emphasis from the action text.
        action = re.sub(r"^[`*_]+|[`*_]+$", "", action).strip()
        if len(action) < _MIN_ACTION_LEN:
            _flush()
            continue
        if num != last_num + 1:
            # Counter reset → flush previous, start new.
            _flush()
        current_steps.append({
            "step": len(current_steps) + 1,
            "action": action,
            "evidence_line": line_num,
        })
        last_num = num

    _flush()
    return sequences


__all__ = [
    "extract_usage_sequence_from_readme",
]
