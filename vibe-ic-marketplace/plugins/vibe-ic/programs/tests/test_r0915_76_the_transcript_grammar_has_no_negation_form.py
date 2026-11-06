"""R-0915-76 — the polarity argument for `sdf_gate_sim::_run_l10_suite`, measured.

`prose_polarity_consulted_check` flagged `_run_l10_suite` as a prose extractor
that reads a value out of a sentence and writes it as a declaration without
asking whether the sentence DENIES it.  What it actually reads out of a
gate-level transcript is SIMULATOR AND SHELL DIAGNOSTIC GRAMMAR:

    RC=(\\d+)                                  the deck's own `echo RC=$?`
    Created a vpiInterModPath                 Icarus `-sdf-info`
    ^SDF INFO: ... Putting delay              Icarus `-sdf-info`, one per delay
    ^SDF ERROR: ... Unable to match ModPath   Icarus `-sdf-info`, one per arc
    ^\\s*\\[TB <id>\\] PASS                      the case's own marker

None of it has a negation form.  The `-sdf-info` channel emits ONE LINE PER
EVENT; there is no line saying a delay was NOT applied, and absence is already
how these readers answer.

THIS FILE IS THE MEASUREMENT BEHIND THAT CLAIM, and it is a measurement rather
than a restatement because it CORRECTED the claim: 84 of 399 trials really do
move a published answer.  Every one of them is a prefix — the markers are
anchored under `re.M` and text in front of one displaces it off the line start —
and every one moves the SAME WAY, toward reporting LESS.  Not one of the 399
makes a reader report a fact the transcript does not carry, which is the
question the gate asks.
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

import pytest

import _prose_polarity as PP
import sdf_gate_sim as SG


# A six-line transcript in the exact shapes the readers look for.
_BASE_LINES: Tuple[str, ...] = (
    "SDF INFO: /p/x.sdf:18: Created a vpiInterModPath\n",
    "SDF INFO: /p/x.sdf:18: Putting delay: 0.113000 for index 0\n",
    "SDF INFO: /p/x.sdf:19: Putting delay: 0.098000 for index 1\n",
    "SDF ERROR: /p/x.sdf:31014: Unable to match ModPath A -> Y in tb.u._08841_\n",
    "[TB case] PASS - 12 oracle check(s) executed, 0 mismatch(es)\n",
    "case_sdf_gate.v:261: $finish called at 33996340000 (1ps)\n",
)
_BASE = "".join(_BASE_LINES)


def _vocabulary() -> List[str]:
    """Every token of `_prose_polarity`'s own denial vocabulary, both tiers.

    Taken from the module rather than retyped: a vocabulary that grows must grow
    this measurement too, which is the whole point of consulting it.
    """
    out: List[str] = []
    for pattern in (PP._DENIAL_CORE, PP._DENIAL_RETIRED):
        for alt in pattern.split("|"):
            tok = alt.replace(r"\b", "").replace(r"\w*", "").replace("-?", "")
            tok = tok.strip()
            if tok:
                out.append(tok)
    return sorted(set(out))


def _answers(text: str, rc_text: str = "RC=0\n") -> Dict[str, object]:
    """Every published answer `_run_l10_suite` takes out of a transcript."""
    census = SG.sdf_annotation_census(text)
    parsed = SG.parse_l10_case_stdout(text)
    m = re.search(r"RC=(\d+)", rc_text)
    return {
        "delays_applied": census["delays_applied"],
        "modpath_unmatched": census["modpath_unmatched"],
        "annotated": census["annotated"],
        "verdict": parsed.get("verdict"),
        "intermodpaths": len(SG._ANNOT_RE.findall(text)),
        "rc": int(m.group(1)) if m else None,
    }


_BASE_ANSWERS = {
    "delays_applied": 2, "modpath_unmatched": 1, "annotated": True,
    "verdict": "PASS", "intermodpaths": 1, "rc": 0,
}


def _trials() -> List[Tuple[str, str, int, str]]:
    """(kind, token, index, transcript) for every position a sentence can take."""
    out = []
    for tok in _vocabulary():
        payload = (f"[TB case] the delay is {tok} applied and the arc is "
                   f"{tok} matched")
        for i in range(len(_BASE_LINES) + 1):
            out.append(("line", tok, i,
                        "".join(_BASE_LINES[:i]) + payload + "\n"
                        + "".join(_BASE_LINES[i:])))
        for i, ln in enumerate(_BASE_LINES):
            out.append(("suffix", tok, i,
                        "".join(_BASE_LINES[:i]) + ln.rstrip("\n") + " -- "
                        + payload + "\n" + "".join(_BASE_LINES[i + 1:])))
        for i, ln in enumerate(_BASE_LINES):
            out.append(("prefix", tok, i,
                        "".join(_BASE_LINES[:i]) + payload + " " + ln
                        + "".join(_BASE_LINES[i + 1:])))
    return out


def test_the_instrument_reads_the_clean_transcript_correctly():
    """A falsifier that cannot see the clean case measures nothing."""
    assert _answers(_BASE) == _BASE_ANSWERS


def test_the_vocabulary_is_the_whole_of_prose_polaritys_own():
    vocab = _vocabulary()
    assert len(vocab) == 21, vocab
    for cjk in ("非", "无", "無", "不", "否"):
        assert cjk in vocab
    for core in ("not", "no", "never", "without", "none"):
        assert core in vocab


def test_the_trial_set_is_every_position_a_sentence_can_occupy():
    trials = _trials()
    # 7 line boundaries + 6 suffixes + 6 prefixes, per token
    assert len(trials) == 21 * (7 + 6 + 6) == 399


def test_the_moves_are_exactly_the_84_prefixes_and_they_all_lose_a_positive():
    """The correction this measurement made to its own argument, pinned. An
    earlier draft claimed 0 of 399 move; 84 do, and the reason is the `re.M`
    anchors, not the polarity."""
    moved = [(k, t, i) for k, t, i, x in _trials()
             if _answers(x) != _BASE_ANSWERS]
    assert len(moved) == 84, len(moved)
    assert {k for k, _, _ in moved} == {"prefix"}
    # and only on the four anchored lines — the unanchored marker is untouched
    assert {i for _, _, i in moved} == {1, 2, 3, 4}


def test_a_prefix_costs_exactly_the_line_it_displaces():
    """Named per line, so the robustness limit is a record and not a shrug."""
    pay = "[TB case] the delay is not applied"

    def pre(i: int) -> Dict[str, object]:
        return _answers("".join(_BASE_LINES[:i]) + pay + " " + _BASE_LINES[i]
                        + "".join(_BASE_LINES[i + 1:]))

    assert pre(1)["delays_applied"] == 1        # one SDF INFO displaced
    assert pre(2)["delays_applied"] == 1
    assert pre(3)["modpath_unmatched"] == 0     # the SDF ERROR displaced
    assert pre(4)["verdict"] is None            # the TB marker displaced
    # and never the other way
    assert pre(1)["annotated"] is True
    assert pre(4)["verdict"] != "FAIL"


def test_a_zero_delay_run_cannot_be_talked_into_looking_annotated():
    """The direction that would matter: no sentence turns an UNannotated run
    into an annotated one."""
    bare = ("SDF ERROR: /p/x.sdf:31014: Unable to match ModPath A -> Y in "
            "tb.u._1_\n[TB case] PASS - 1 oracle check(s) executed\n")
    assert SG.sdf_annotation_census(bare)["annotated"] is False
    for tok in _vocabulary():
        for text in (f"the delay is {tok} applied\n" + bare,
                     bare + f"the delay is {tok} applied\n"):
            assert SG.sdf_annotation_census(text)["annotated"] is False, tok
