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
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
# THE ONE NEGATION VOCABULARY (vibe-ic#712). See `_denied_latency` below for
# which of this module's typed keys are governed by it and, just as
# deliberately, which are not.
from _prose_polarity import (  # type: ignore  # noqa: E402
    is_denied as _is_denied, sentence_scope as _sentence_scope)

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

#: Category stamped on every README usage sequence (v1.15.45, sha256 capture).
#: A numbered host-side procedure is DOCUMENTATION of how software drives the
#: register interface: it is implemented by the design's register / command
#: path as a whole, never by a dedicated RTL module named after the sequence.
#: Consumers that ask "which module implements this sequence?"
#: (`l12_sequence_implementation_check`) skip this category with a stated
#: reason; consumers that ask "is each step checkable?"
#: (`l12_sequences_in_consumed_layer_check`) read the typed details that
#: `type_step_action` derives below. MEASURED 2026-09-02 on the sha256 corpus
#: IC (v1.15.33 and v1.15.44): the two README usage sequences were emitted as
#: bare prose with no category, so BOTH consumers refused — one for a missing
#: `usage_sequence_1` module, the other for untyped steps — and D1 + P0 failed
#: on documentation that was correct.
HOST_USAGE_CATEGORY = "host_usage_sequence"

_TRAILING_COMMENT_RE = re.compile(r"\s*(?://|#|;)\s*(.*)$")
_CYCLES_RE = re.compile(r"~?\s*(\d+)\s*(?:clk|clock)?\s*cycles?", re.I)
_TIME_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(us|µs|ms|ns)\b", re.I)
_OPTIONAL_RE = re.compile(r"^\(?\s*optional\s*\)?\s*[:\-]?\s*", re.I)
_WRITE_RE = re.compile(
    r"^write\s+([A-Za-z_][\w./\[\]:]*)\s*((?:bit|bits|field)\s*[\w:\[\]]+)?\s*=\s*(.+)$",
    re.I)
_READ_RE = re.compile(
    r"^read\s+([A-Za-z_][\w./\[\]:]*)(?:\s*=\s*(.+?))?(?:\s+to\s+(.+))?$", re.I)
_POLL_RE = re.compile(
    r"^(?:poll|wait(?:\s+for)?)\s+(.+?)(?:\s+until\s+(.+))?$", re.I)
_CHECK_RE = re.compile(r"^(?:check|verify|confirm|assert)\s+(.+)$", re.I)
_REPEAT_RE = re.compile(
    r"^(?:for\s+(.+?)\s*:\s*)?repeat\s+(?:steps?\s*)?(\d+)\s*[-–]\s*(\d+)(.*)$",
    re.I)


#: WHY ONLY THE LATENCY KEYS (vibe-ic#712, and this function is the answer to
#: `prose_polarity_consulted_check`). This module derives seven kinds of typed
#: detail from a README step, and they are not the same kind of claim:
#:
#:   * `value`, `expected_response`, `wait_for`, `expected_signal`, `check`,
#:     `condition`, `variant` are SPANS COPIED VERBATIM out of the step. A
#:     denial inside one of them travels with the text — "Verify ready is not
#:     asserted" becomes `check: "ready is not asserted"`, which is the step's
#:     own sentence and still says what it said. Consulting polarity there
#:     would DELETE a legitimately negative instruction, which is a worse
#:     reader than the one that copies it.
#:
#:   * `latency_cycles` and `latency_<unit>` are INTERPRETED: a number is
#:     lifted out of the sentence, its words are discarded, and what is
#:     published is a typed figure a consumer reads as a declaration. That is
#:     exactly #711's shape — a document saying the old value "has NO meaning
#:     here and is REMOVED" re-declared that exact number as a mandate — and
#:     it is reachable here because these two are the only UNANCHORED searches
#:     in this module: `_CYCLES_RE`/`_TIME_RE` run over the step text PLUS its
#:     trailing comment, which is where a human writes "not ~10 cycles, it is
#:     level-sensitive". Every other shape is anchored at `^<verb>`, so a step
#:     that opens with a denial ("Do not write ctrl = 1") matches nothing and
#:     publishes nothing.
#:
#: The window is `sentence_scope`, both directions, so a denial in the
#: NEIGHBOURING sentence of a two-sentence comment does not retract this one.
#:
#: THE CONSULT IS INLINE IN `type_step_action`, not in a module-level helper it
#: calls. `prose_polarity_consulted_check._consults_polarity` walks the
#: extractor's own AST for a name from the vocabulary, so a helper one call away
#: leaves the extractor reading as polarity-blind — correctly: the register is a
#: list of FUNCTIONS that read prose, and "some other function checks" is the
#: shape the gate exists to refuse.


def type_step_action(action: str) -> dict:
    """Derive the typed, checkable detail a README step carries.

    Pure text → dict; returns {} when the step is prose only. The keys are
    the ones `l12_sequences_in_consumed_layer_check._STEP_DETAIL_KEYS`
    already reads (`expected_signal`, `expected_response`, `wait_for`,
    `check`, `next_state`, `latency_*`), so a typed step is checkable by the
    consumer that exists rather than by a new vocabulary. Chip-AGNOSTIC:
    only the imperative verb and the `<target> = <value>` / `until` /
    `~N cycles` shapes of a host procedure are read; no register name or
    value is interpreted.
    """
    if not isinstance(action, str):
        return {}
    text = action.strip()
    out: dict = {}
    note = ""
    m = _TRAILING_COMMENT_RE.search(text)
    if m and m.start() > 0:
        note = m.group(1).strip()
        text = text[:m.start()].strip()
    if _OPTIONAL_RE.match(text) and _OPTIONAL_RE.match(text).end() > 0:
        out["optional"] = True
        text = text[_OPTIONAL_RE.match(text).end():].strip()
    probe = f"{text} {note}".strip()
    def _denied(match) -> "Optional[str]":
        """The denial word governing this lifted number, or None. See the note
        above `type_step_action` for why the latency keys are consulted and the
        copied-span keys are deliberately not."""
        lo, hi = _sentence_scope(probe, match.start(), match.end())
        return _is_denied(probe[lo:hi])

    mc = _CYCLES_RE.search(probe)
    if mc and not _denied(mc):
        out["latency_cycles"] = int(mc.group(1))
    mt = _TIME_RE.search(probe)
    if mt and not _denied(mt):
        unit = mt.group(2).lower().replace("µs", "us")
        try:
            out[f"latency_{unit}"] = float(mt.group(1))
        except ValueError:
            pass
    m = _WRITE_RE.match(text)
    if m:
        target = m.group(1)
        field = (m.group(2) or "").strip()
        value = m.group(3).strip()
        out.update({"action_type": "write", "target": target,
                    "value": value,
                    "expected_signal": f"{target}{(' ' + field) if field else ''} = {value}"})
        if field:
            out["field"] = field
        return out
    m = _READ_RE.match(text)
    if m:
        target = m.group(1)
        out.update({"action_type": "read", "target": target, "observe": target})
        if m.group(2):
            out["expected_response"] = m.group(2).strip()
        elif m.group(3):
            out["expected_response"] = m.group(3).strip()
        return out
    m = _POLL_RE.match(text)
    if m:
        target = m.group(1).strip()
        cond = (m.group(2) or "").strip()
        wait_for = f"{target} until {cond}" if cond else target
        out.update({"action_type": "poll", "target": target,
                    "wait_for": wait_for, "expected_signal": cond or target})
        return out
    m = _CHECK_RE.match(text)
    if m:
        out.update({"action_type": "check", "check": m.group(1).strip()})
        return out
    m = _REPEAT_RE.match(text)
    if m:
        out.update({"action_type": "repeat",
                    "next_state": f"step {m.group(2)}",
                    "repeat_steps": f"{m.group(2)}-{m.group(3)}"})
        if m.group(1):
            out["condition"] = m.group(1).strip()
        if m.group(4) and m.group(4).strip():
            out["variant"] = m.group(4).strip(" ,;:")
        return out
    return out


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
            "category": "host_usage_sequence",
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
                    "name":     f"usage_sequence_{idx}",
                    "trigger":  "host_initiates",
                    "category": HOST_USAGE_CATEGORY,
                    "steps":    list(current_steps),
                    "source":   "readme_usage_sequence",
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
        step_rec = {
            "step": len(current_steps) + 1,
            "action": action,
            "evidence_line": line_num,
        }
        step_rec.update(type_step_action(action))
        current_steps.append(step_rec)
        last_num = num

    _flush()
    return sequences


__all__ = [
    "HOST_USAGE_CATEGORY",
    "extract_usage_sequence_from_readme",
    "type_step_action",
]
