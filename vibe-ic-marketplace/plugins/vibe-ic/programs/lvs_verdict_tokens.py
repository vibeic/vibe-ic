#!/usr/bin/env python3
"""lvs_verdict_tokens.py — single source of truth for netgen LVS terminal-
verdict classification (ORGANIC #524, extends #507/#477).

WHY THIS MODULE EXISTS
----------------------
#507 added the terminal-verdict gate to `eda_report_audit._check_lvs` with the
explicit goal "gate and runner never disagree" — but the token list was
duplicated by hand across FOUR Python sites and drifted immediately:
`phase3_one_shot_runner.step_lvs` and `mixed_signal_top_lvs_run.run` never
received the `failed pin matching` token, so a report whose only terminal line
is `Final result: Top level cell failed pin matching.` (a CONCLUSIVE netgen
FAIL) was mis-classified as INCOMPLETE ("netgen produced no terminal verdict
token") by the runner while the Step-31 gate called it MISMATCH. #524 is that
drift. This module is the one place the tokens live; every Python consumer
imports it.

The semantics mirror the empirically-validated MCP-EDA classifier
(`mcp-eda/src/lib/netgen_verdict.mjs`), which confirmed in-container
(netgen 1.5.316) that:
  * `Top level cell failed pin matching.` is a terminal FAIL verdict;
  * `Property errors were found.` / `match uniquely with property errors` is a
    REAL FAIL even though netgen ALSO prints `Final result: Circuits match
    uniquely.` on the topology line (a transistor-property delta is an LVS
    fail);
  * a mismatch token is AUTHORITATIVE over any `match uniquely` token.

JSON-AUTHORITATIVE VERDICT (the wording gate is CLOSED)
------------------------------------------------------
Classifying an LVS sign-off by REGEXING netgen's English is a false-clean
generator: a mismatch phrased in wording the regex does not enumerate, next to
any `match uniquely` line (per-subcell lines print by the hundreds), used to
return MATCH. Measured on this very module before the fix — a transcript
reading `Result: Netlists are NOT equivalent.` / `Netlist comparison FAILED
(2 discrepancies).` classified **MATCH**. An LVS false-clean ships a broken
chip as verified; it is the defect class that reaches silicon.

The fix follows the house pattern (`verilogeval_tier_pipeline` gates on the
observable `Mismatches: N in M samples` line, not on the word "TIMEOUT"):
decide on an observable OUTCOME, use wording only to EXPLAIN.

Our netgen fork emits that observable. Fork enhancement E1 (`vibeic fork (LVS
fidelity, E1)`) makes `-json` a top-level OBJECT carrying a machine verdict:

    {"verdict": "match"|"mismatch"|"unknown", "verdict_reason": "...",
     "summary": {"devices": {...}, "nets": {...}, "unmatched_nets": {...},
                 "unmatched_devices": {...}, "property_error_count": K, ...},
     "cells": [...]}

`verdict` is derived from netgen's OWN numeric verify() result (1 unique match,
-3 property error, -1 nothing to compare, 0/-2/-4 not a unique match) — the
SAME engine state that drives the `Final result:` text, never re-parsed from
it. So JSON and text can never disagree, and the JSON is the observable.

PRECEDENCE
  1. E1 JSON verdict, when present, is AUTHORITATIVE (passed in, or found
     embedded in the blob). `mismatch` wins even if the text looks matchy.
     The ONE exception is fail-safe-only: a JSON `match` alongside a text
     mismatch token yields MISMATCH — the authoritative source may never be
     used to UPGRADE a failing text into a pass.
  2. Text tokens ONLY when no JSON is present (older netgen), and then
     FAIL-SAFE: MATCH requires POSITIVE evidence — a terminal `Final result:`
     line that ITSELF reads as a unique match, with no other terminal line
     dissenting. Unrecognized terminal wording is INCOMPLETE or MISMATCH,
     NEVER MATCH. Absence of a known failure phrase is not evidence of a pass.

CLASSES
-------
  MATCH      — POSITIVE evidence of a clean compare: an E1 JSON
               `verdict == "match"`, or (no JSON) every terminal
               `Final result:` line reading `Circuits/Netlists match uniquely`.
  MISMATCH   — an E1 JSON `verdict == "mismatch"`, any terminal mismatch
               token, or a terminal line carrying negative wording
               (authoritative over any `match uniquely` line).
  INCOMPLETE — no conclusive evidence either way: the compare did not run to
               completion (netgen killed mid-run / truncated report), or it
               ended in wording we do not recognize. Never upgraded to MATCH
               (#477 honesty: an incomplete run is not a conclusive result in
               either direction — and an UNREADABLE one is not a pass).

chip-AGNOSTIC: pure netgen verdict/phrase classification; no design/cell
literal.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# ── E1 structured machine verdict (the OBSERVABLE) ─────────────────────────
# netgen's own numeric verify() result, mapped to this module's classes.
# Anything not in this map — a verdict string a future fork adds, a non-string,
# a missing key — is INCOMPLETE, never MATCH (fail-safe by construction).
_E1_VERDICT_MAP = {
    "match": "MATCH",
    "mismatch": "MISMATCH",
    "unknown": "INCOMPLETE",
}

# The E1 report is identified STRUCTURALLY (all three keys), not by a filename
# or a lone "verdict" key some other tool might also emit.
_E1_REQUIRED_KEYS = ("verdict", "verdict_reason", "summary")
_VERDICT_KEY_RE = re.compile(r'"verdict"\s*:')

JsonSource = Union[None, str, Path, Dict[str, Any]]

# Genuine clean-match phrases — netgen's "match uniquely" wording, never the
# bare substring "match" (which also appears inside FAIL phrases like
# "failed pin matching").
MATCHED_RE = re.compile(
    r"Circuits?\s+match\s+uniquely|Netlists?\s+match\s+uniquely", re.I)

# Terminal mismatch phrases — ANY present means a real compare ran and FAILED,
# even if sub-cells (or the topology line) also printed "match uniquely".
MISMATCHED_RE = re.compile(
    r"do\s+not\s+match"
    r"|NET\s+MISMATCH"
    r"|failed\s+pin\s+matching"            # #524: netgen top-level pin FAIL
    r"|property\s+errors?\s+were\s+found"  # #524: netgen property FAIL
    r"|match\s+uniquely\s+with\s+property\s+errors"
    r"|失配", re.I)

# Pin-mismatch evidence lines netgen prints in the pin-correspondence table,
# e.g. `(no pin, node is o_sram_data[7])           |o_sram_wdata[7]`
# or    `o_data[3]                                 |(no matching pin)`.
# The `(no pin, node is …)` shape appears ONLY in the top-level failing table;
# the `(no matching pin)` shape ALSO appears as benign subcell power-pin rows
# (VGND/VPB/… absent from LEF abstracts) by the hundreds in clean reports.
_PIN_NODE_RE = re.compile(r"^.*\(no pin, node is [^)]*\).*$", re.M)
_PIN_NOMATCH_RE = re.compile(r"^.*\(no matching pin\).*$", re.M)

# A COMPLETED netgen compare always ends with a `Final result:` line; a
# `match uniquely` token without it is a per-subcell line of a hierarchical
# run that was killed before the top-level compare (mirrors the
# netgen_verdict.mjs guard).
#
# The terminal verdict text — the text fallback's POSITIVE evidence. Captures
# only what follows `Final result:`, NOT the whole line: a `match uniquely`
# printed BEFORE the colon (or on a per-subcell line elsewhere) must not be
# able to carry the top-level verdict.
_FINAL_RESULT_LINE_RE = re.compile(r"Final result\s*:(.*)$", re.M | re.I)

# netgen prints the verdict on ONE line in the report file but across TWO on
# stdout:
#     report : "Final result: Circuits match uniquely."
#     stdout : "Final result: \nCircuits match uniquely."
# Callers classify `transcript + report`, so the blob carries BOTH forms and the
# bare `Final result: ` from stdout is an unreadable terminal line. Under the
# unanimity rule below that blocks MATCH — while a MISMATCH still classifies
# correctly, because its token is matched anywhere in the blob. The result is a
# ONE-SIDED failure: a genuinely clean LVS can never be reported as MATCH.
# Measured on spm @ v1.4.74 (fresh run, instrumented):
#     classify(report)              -> MATCH
#     classify(transcript + report) -> INCOMPLETE
#         finals = ['Final result: ', 'Final result: Circuits match uniquely.']
# Joining the continuation before extraction makes the two forms identical.
# Fail-safe is untouched: if the joined text is still unrecognized wording it
# stays INCOMPLETE/MISMATCH — this only removes an artefact of line-wrapping,
# it never invents positive evidence.
_FINAL_RESULT_CONTINUATION_RE = re.compile(
    r"(Final result\s*:)[ \t]*\r?\n[ \t]*(?=\S)", re.I)


def _join_wrapped_final_result(blob: str) -> str:
    """Fold netgen's two-line stdout `Final result:` back onto one line."""
    return _FINAL_RESULT_CONTINUATION_RE.sub(r"\1 ", blob or "")

# The verdict phrase ANCHORED to where netgen actually writes it: immediately
# after `Final result:`. Slicing after the marker is NOT sufficient on its own —
# the sliced region still carries tool- and DESIGN-supplied DATA (paths, cell and
# net names), and a token sitting inside that data can impersonate the structural
# token. Measured, both returned a FALSE MATCH before anchoring:
#   Final result: comparison ended for cell \circuits match uniquely
#       — a SystemVerilog ESCAPED identifier legally contains SPACES, so
#         `Circuits\s+match\s+uniquely` matches a DESIGN-chosen name;
#   Final result: read from /work/circuits match uniquely/top.spice
#       — same, via an environment-chosen PATH.
# The design names its own nets; it must never be able to name its way to a pass.
# (Credit: the sibling synth-frontend fix hit the same class — a pass ARGUMENT
# path containing "frontend" impersonating the pass-CLASS token.)
_TERMINAL_MATCH_RE = re.compile(
    r"^\s*(?:Circuits?|Netlists?)\s+match\s+uniquely", re.I)

# Unambiguous negative wording for phrasings MISMATCHED_RE does not enumerate.
# Deliberately COUNT-FREE: every phrase here is one no clean netgen report can
# print, so broadening the failure net cannot manufacture a false alarm (the
# count-bearing words like "discrepancies" are scoped to the terminal line
# only, via _TERMINAL_NEGATIVE_RE, where a clean report never lands).
_NEGATIVE_HINT_RE = re.compile(
    r"not\s+equivalent"
    r"|comparison\s+failed"
    r"|LVS\s+FAILED"
    r"|failed\s+to\s+match"
    r"|(?:netlists?|circuits?)\s+differ", re.I)

# Negative wording judged ONLY against a terminal `Final result:` line.
_TERMINAL_NEGATIVE_RE = re.compile(
    r"\bfail(?:ed|ure|s)?\b"
    r"|\bmismatch(?:e[sd])?\b"
    r"|\bdiscrepanc(?:y|ies)\b"
    r"|\bnot\b"
    r"|\bno\b"
    r"|\berror", re.I)


def _looks_like_e1(obj: Any) -> bool:
    """True iff `obj` is an E1 structured LVS report (all required keys, and a
    STRING verdict). Identified structurally so a stray `"verdict"` key from
    some other tool can never be mistaken for the authoritative source."""
    return (isinstance(obj, dict)
            and all(k in obj for k in _E1_REQUIRED_KEYS)
            and isinstance(obj.get("verdict"), str))


# Worst-wins precedence when a transcript embeds more than one E1 report: we
# are a guard, so the most adverse verdict present decides.
_E1_SEVERITY = {"MISMATCH": 2, "INCOMPLETE": 1, "MATCH": 0}


def _find_embedded_e1(blob: str) -> Optional[Dict[str, Any]]:
    """Find an E1 report embedded in a transcript blob (runners commonly cat
    the `-json` output into the log). Cheap: only the `"verdict"` key sites are
    probed, walking back to the enclosing `{` — E1 emits `verdict` first.

    A non-E1 object at one site does not end the search (another tool may emit
    its own `verdict` key earlier in the log), and when several E1 reports are
    present the most ADVERSE verdict wins — a guard never averages."""
    if not blob or '"verdict"' not in blob:
        return None
    dec = json.JSONDecoder()
    best: Optional[Dict[str, Any]] = None
    best_sev = -1
    for km in _VERDICT_KEY_RE.finditer(blob):
        start, tries = blob.rfind("{", 0, km.start()), 0
        while start != -1 and tries < 4:
            try:
                obj, _ = dec.raw_decode(blob, start)
            except ValueError:
                start, tries = blob.rfind("{", 0, start), tries + 1
                continue
            if _looks_like_e1(obj):
                sev = _E1_SEVERITY.get(
                    _E1_VERDICT_MAP.get(obj["verdict"].strip().lower(),
                                        "INCOMPLETE"), 1)
                if sev > best_sev:
                    best, best_sev = obj, sev
            break  # decoded here; move to the next "verdict" site
    return best


# netgen's own fingerprints. A blob carrying these is a netgen report, and its
# verdict belongs to THIS module — a tool-generic phrase list must not be
# allowed to read a match out of a netgen transcript this module refused.
_NETGEN_SHAPE_RE = re.compile(
    r"Final result\s*:"
    r"|Circuits?\s+match\s+uniquely"
    r"|Netlists?\s+match\s+uniquely"
    r"|Subcircuit summary"
    r"|failed\s+pin\s+matching", re.I)


def is_netgen_report(blob: str) -> bool:
    """True iff `blob` looks like a netgen LVS transcript/report. Callers with
    tool-generic phrase lists (calibre/other evidence shapes) use this to yield
    netgen verdicts to `classify()` instead of re-deriving them from text."""
    return bool(_NETGEN_SHAPE_RE.search(blob or ""))


def has_terminal_verdict(blob: str) -> bool:
    """True iff `blob` carries netgen's completion marker — a terminal
    `Final result:` line. A COMPLETED netgen compare ALWAYS ends with one
    (whether match or mismatch); its ABSENCE means the report is empty, partial,
    or the run was killed before the top-level compare. Used by report readers
    to know a `Final result:` verdict has actually flushed to the report file
    before classifying it (netgen writes this line LAST). chip-AGNOSTIC."""
    return bool(_FINAL_RESULT_LINE_RE.search(blob or ""))


def load_json_report(source: JsonSource) -> Optional[Dict[str, Any]]:
    """Resolve an E1 report from a dict, a file path, or a directory holding
    one. Returns None when there is no readable E1 report — callers then fall
    back to the (fail-safe) text path. Never raises: an unreadable/corrupt
    report is ABSENT, and absence can only ever cost us a MATCH, never grant
    one."""
    if source is None:
        return None
    if isinstance(source, dict):
        return source if _looks_like_e1(source) else None
    p = Path(source)
    try:
        if p.is_dir():
            for cand in sorted(p.glob("*.json")):
                obj = load_json_report(cand)
                if obj is not None:
                    return obj
            return None
        if not p.is_file():
            return None
        obj = json.loads(p.read_text(errors="replace"))
    except (OSError, ValueError):
        return None
    return obj if _looks_like_e1(obj) else None


def _resolve_report(blob: str, json_report: JsonSource) -> Optional[Dict[str, Any]]:
    """The E1 report to classify on: the caller's, else one embedded in blob."""
    obj = load_json_report(json_report)
    return obj if obj is not None else _find_embedded_e1(blob or "")


def _classify_text(blob: str) -> str:
    """FAIL-SAFE text fallback — used ONLY when no E1 JSON report exists.

    MATCH requires POSITIVE evidence and is the NARROWEST outcome: every
    terminal `Final result:` line must itself read as a unique match. The
    absence of a known failure phrase is NOT evidence of a pass, so wording we
    do not recognize resolves to MISMATCH (terminal line reads negative) or
    INCOMPLETE (unreadable), never to MATCH."""
    if MISMATCHED_RE.search(blob) or _NEGATIVE_HINT_RE.search(blob):
        return "MISMATCH"
    finals = _FINAL_RESULT_LINE_RE.findall(_join_wrapped_final_result(blob))
    if not finals:
        # No terminal line at all: a truncated hierarchical run whose
        # per-subcell `match uniquely` lines printed before the top-level
        # compare was reached.
        return "INCOMPLETE"
    # UNANIMITY, not first-or-last: EVERY terminal line must read clean. yosys is
    # known to re-enter a frontend deep in a flow, and netgen can print more than
    # one terminal line in a hierarchical run — so any "take the first/last
    # occurrence" rule is one re-entry away from reading the wrong verdict.
    if all(_TERMINAL_MATCH_RE.match(ln) for ln in finals):
        return "MATCH"
    # The compare terminated, but in wording we cannot read as a clean match.
    dissenting = [ln for ln in finals if not _TERMINAL_MATCH_RE.match(ln)]
    if any(_TERMINAL_NEGATIVE_RE.search(ln) for ln in dissenting):
        return "MISMATCH"
    return "INCOMPLETE"


def classify(blob: str, json_report: JsonSource = None) -> str:
    """Classify a netgen LVS result → MATCH / MISMATCH / INCOMPLETE.

    The E1 structured report (`json_report`, or one embedded in `blob`) is
    AUTHORITATIVE when present — it carries netgen's own numeric verdict, so a
    reworded transcript cannot move it. Text tokens are consulted only in its
    absence, and then only fail-safely (see `_classify_text`).

    The single exception to JSON authority runs in the SAFE direction: a JSON
    `match` contradicted by a text mismatch token returns MISMATCH. The fork
    guarantees the two agree; if they ever do not, we refuse the sign-off
    rather than grant it."""
    obj = _resolve_report(blob, json_report)
    if obj is not None:
        verdict = _E1_VERDICT_MAP.get(obj["verdict"].strip().lower(), "INCOMPLETE")
        if verdict == "MATCH" and MISMATCHED_RE.search(blob or ""):
            return "MISMATCH"
        return verdict
    return _classify_text(blob or "")


# ── ORGANIC (GAP-E2E-9) — sub-classify a MISMATCH: benign OSS power-pin-only
# vs a real signal-net mismatch. The 7-IC end-to-end sweep showed netgen prints
# `Top level cell failed pin matching` (→ MISMATCH) on EVERY sky130 OSS run
# because the yosys gate netlist has NO power ports (VPWR/VGND/VPB/VNB) while the
# extracted layout carries per-cell power pins — a universal power-unaware-netlist
# vs power-extracted-layout SETUP artifact, NOT a design connectivity defect
# (measured: caravel + subservient LVS reports carry ONLY power-pin rows, 0
# signal-net rows). This sub-class lets the sign-off DISCLOSE that benign class
# for a reviewed waiver WITHOUT touching the authoritative MATCH/MISMATCH verdict.
#
# §4.05 NO-LEAK (load-bearing): `POWER_PIN_ONLY` is asserted ONLY when the mismatch
# evidence is EXCLUSIVELY power/tie nets. ANY signal-net evidence — a `(no pin,
# node is …)` row, a NON-power `(no matching pin)` port, or a property error —
# classifies `SIGNAL_NET_MISMATCH` and is NEVER waved through (measured: aes 517 +
# ibex 256 `(no pin, node is …)` rows collapse many top ports onto one node — an
# ambiguous tie-off/short that MUST stay a real mismatch, not a benign waiver).
# The verdict from classify() is UNCHANGED; this is triage metadata only.
_POWER_NET_RE = re.compile(
    r"^(?:VGND|VNB|VPB|VPWR|VCCD\d*|VSSD\d*|VDD[A-Z0-9]*|VSS[A-Z0-9]*"
    r"|VCC[A-Z0-9]*|GND[A-Z0-9]*|HI|LO|TIE_?HI|TIE_?LO)$", re.I)
_PROPERTY_ERR_RE = re.compile(r"property\s+errors?\s+were\s+found", re.I)

# POSITIVE evidence that the mismatch IS the pin-correspondence failure whose
# benign power-only variant we are willing to disclose as a waiver candidate.
# Without this shape the mismatch is some OTHER failure and stays REAL — the
# benign bucket is never reachable by elimination.
_PIN_MATCH_FAIL_RE = re.compile(r"failed\s+pin\s+matching", re.I)


def _is_power_token(tok: str) -> bool:
    """True iff `tok` names a power/ground/tie net (sky130 VPWR/VGND/VPB/VNB,
    core/io VCCD*/VSSD*, generic VDD*/VSS*/GND*, or a tie-HI/LO net)."""
    return bool(_POWER_NET_RE.match((tok or "").strip()))


def _e1_says_real_defect(obj: Dict[str, Any]) -> bool:
    """True iff the E1 report carries STRUCTURED evidence of a real defect —
    any property error, any unmatched device, any unmatched net, or a D5 ranked
    `property_mismatches` entry.

    Fail-safe by construction: a malformed / partial summary returns True. The
    benign bucket must be EARNED from counts we could actually read; we never
    infer 'benign' from a field we failed to parse."""
    s = obj.get("summary")
    if not isinstance(s, dict):
        return True
    prop = s.get("property_error_count")
    if not isinstance(prop, int) or prop > 0:
        return True
    for grp in ("unmatched_devices", "unmatched_nets"):
        g = s.get(grp)
        if not isinstance(g, dict):
            return True
        for side in ("ckt1", "ckt2"):
            v = g.get(side)
            if not isinstance(v, int) or v > 0:
                return True
    # D5 ranked property mismatches — present means real, ranked deltas exist.
    return bool(obj.get("property_mismatches") or s.get("property_error_cells"))


def mismatch_class(blob: str, json_report: JsonSource = None) -> str:
    """Sub-classify a netgen report → for triage ONLY (the classify() verdict is
    authoritative and unchanged). Returns:
      * 'NONE'                 — not a MISMATCH (MATCH / INCOMPLETE).
      * 'SIGNAL_NET_MISMATCH'  — a MISMATCH with real signal-net evidence
                                 (a `(no pin, node is …)` row, a NON-power
                                 `(no matching pin)` port, or a property error).
                                 NEVER a benign class — a reviewed waiver must not
                                 wave this through.
      * 'POWER_PIN_ONLY'       — a MISMATCH whose evidence is EXCLUSIVELY power/tie
                                 nets (the universal power-unaware-netlist OSS
                                 SETUP artifact) — a reviewed-waiver CANDIDATE, not
                                 a silent pass.
    POSITIVE-EVIDENCE INVERSION (the demotion gate is CLOSED): `POWER_PIN_ONLY`
    is now REACHABLE ONLY by earning it — the E1 structured counts must show no
    real defect (when a report exists) AND the transcript must carry BOTH the
    pin-correspondence failure shape (`failed pin matching`) AND power/tie-net
    evidence. A mismatch we cannot positively recognize as that artifact — any
    reworded failure, any unparsed summary — stays `SIGNAL_NET_MISMATCH`. The
    benign bucket is never reached by elimination, so a real connectivity
    defect can no longer be demoted into a waivable class by wording drift.

    chip-AGNOSTIC: pure netgen verdict + phrase + power-net-name classification."""
    obj = _resolve_report(blob, json_report)
    if classify(blob, json_report=obj) != "MISMATCH":
        return "NONE"
    # Structured evidence is authoritative and checked FIRST — §4.05 no-leak.
    if obj is not None and _e1_says_real_defect(obj):
        return "SIGNAL_NET_MISMATCH"
    # Real signal-net evidence → NOT benign (checked FIRST — §4.05 no-leak). The
    # RELIABLE top-level-real-mismatch signatures are the `(no pin, node is …)`
    # rows (netgen's top-level failure-table shape, per this module's established
    # semantics) and a device `property errors` line. A bare `(no matching pin)`
    # row is NOT signal evidence — it is dominated by BENIGN sub-cell abstraction
    # rows (power pins AND standard-cell pins like `Y`/`A`/`B`, absent from LEF
    # abstracts by the hundreds), so it must NOT drive the class.
    if _PROPERTY_ERR_RE.search(blob):
        return "SIGNAL_NET_MISMATCH"
    if _PIN_NODE_RE.search(blob):                 # `(no pin, node is …)` rows
        return "SIGNAL_NET_MISMATCH"
    # POSITIVE evidence that this mismatch is the pin-correspondence failure at
    # all. Any OTHER failure — including one worded in tokens we do not know —
    # is REAL, not a waiver candidate.
    if not _PIN_MATCH_FAIL_RE.search(blob):
        return "SIGNAL_NET_MISMATCH"
    # No top-level signal-failure rows. Confirm the mismatch carries the
    # power-unaware-netlist SETUP evidence (a power/tie `(no matching pin)` row OR
    # a `disconnected node: V*` line) before calling it the benign class; a
    # MISMATCH with no recognizable benign shape stays conservative (real).
    saw_power_row = bool(re.search(
        r"(?im)^\s*(?:VGND|VNB|VPB|VPWR|VCCD\d*|VSSD\d*|VDD[A-Z0-9]*|VSS[A-Z0-9]*"
        r"|VCC[A-Z0-9]*|GND[A-Z0-9]*|HI|LO)\s+\|\(no matching pin\)", blob))
    saw_power_row = saw_power_row or bool(re.search(
        r"disconnected node:\s*(?:VGND|VNB|VPB|VPWR|VCC|VSS|VDD|GND)",
        blob, re.I))
    return "POWER_PIN_ONLY" if saw_power_row else "SIGNAL_NET_MISMATCH"


def pin_mismatch_evidence(blob: str, max_lines: int = 8) -> List[str]:
    """Extract the netgen pin-correspondence mismatch lines (the readable
    evidence of WHICH pins failed matching) — at most `max_lines`, stripped.

    Prefers the `(no pin, node is …)` rows (top-level-failure-only shape) and
    takes them from the report TAIL, where the top-level table sits — the
    front of a big report is hundreds of benign subcell `(no matching pin)`
    power-pin rows that would otherwise drown the real evidence."""
    node_rows = [m.group(0).strip() for m in _PIN_NODE_RE.finditer(blob)]
    if node_rows:
        return node_rows[-max_lines:]
    nomatch_rows = [m.group(0).strip()
                    for m in _PIN_NOMATCH_RE.finditer(blob)]
    return nomatch_rows[-max_lines:]


# ── #203 — short / open / pin LOCALIZATION from netgen's `-json` output ────────
# netgen records WHERE two netlists diverge — which nets short, which pins fail
# to match, which devices are unmatched — ONLY when `netgen -batch lvs ... -json`
# is passed. The plain text report records only WHETHER they match. So every
# `lvs.rpt` we ship today can say "not a match" but never name the offending net;
# triage then re-runs netgen by hand to get it. Passing `-json` writes a SIDECAR
# array (the text report is byte-identical — verified: same md5 with/without the
# flag), and this parser turns that array into a flat localization so an LVS FAIL
# names the offending net the FIRST time.
#
# PURELY ADDITIVE — LOAD-BEARING: the result NEVER feeds `classify()` /
# `mismatch_class()`. The LVS verdict is unchanged; the #189 classifier and the
# Step-31 gate both read only the (byte-identical) text report. netgen's `-json`
# is a top-level ARRAY, never the E1 verdict dict `_looks_like_e1` accepts, so it
# can never be mistaken for an authoritative verdict source. FAIL-SAFE: an absent
# / unreadable / non-array json yields ``available=False`` and never raises — a
# missing localization can only cost triage detail, never move a verdict.
# chip-AGNOSTIC: pure structural parse, no design/cell literal.
_NET_PLACEHOLDER_RE = re.compile(
    r"^\(no matching net\)$|^\(no pin\b|^\(none\)$", re.I)


def _load_netgen_json_array(source: JsonSource) -> Optional[List[Any]]:
    """Resolve netgen's `-json` output (a top-level ARRAY of per-cell records)
    from a list, a file, or a directory holding one. Returns None for anything
    that is not a netgen `-json` array — including an E1 verdict DICT, which is a
    different, authoritative artifact this parser must never touch."""
    if source is None or isinstance(source, dict):
        return None
    if isinstance(source, list):
        return source
    p = Path(source)
    try:
        if p.is_dir():
            for cand in sorted(p.glob("*.json")):
                arr = _load_netgen_json_array(cand)
                if arr is not None:
                    return arr
            return None
        if not p.is_file():
            return None
        obj = json.loads(p.read_text(errors="replace"))
    except (OSError, ValueError):
        return None
    return obj if isinstance(obj, list) else None


def _dedupe(items: List[str]) -> List[str]:
    """Order-preserving de-duplication."""
    seen: Dict[str, None] = {}
    for it in items:
        if it not in seen:
            seen[it] = None
    return list(seen.keys())


def _harvest_net_names(node: Any, out: List[str]) -> None:
    """Recursively collect real net/device-name strings from a netgen
    ``badnets`` / ``badelements`` subtree, skipping the ``(no matching net)`` /
    ``(no pin …)`` placeholders and the ``[subcell, pin, count]`` fanout triples
    (whose leading strings are subcell/pin names, NOT nets)."""
    if isinstance(node, str):
        s = node.strip()
        if s and not _NET_PLACEHOLDER_RE.match(s):
            out.append(s)
    elif isinstance(node, list):
        # a [subcell, pin, count] fanout triple: its first two strings name a
        # SUBCELL and a PIN, never a net — do not harvest them.
        if (len(node) == 3 and isinstance(node[2], int)
                and all(isinstance(x, str) for x in node[:2])):
            return
        for item in node:
            _harvest_net_names(item, out)


def _cell_name(n: Any) -> str:
    """netgen names a cell ``[layout, source]``; render the common name, or
    ``layout vs source`` when they differ."""
    if isinstance(n, list) and n:
        parts = [str(x) for x in n if isinstance(x, str) and x]
        if not parts:
            return ""
        return parts[0] if len(set(parts)) == 1 else " vs ".join(parts)
    return str(n) if n else ""


def _pin_mismatches(pins: Any) -> List[Dict[str, str]]:
    """From netgen's per-cell ``pins`` = ``[[layout pins…], [source pins…]]``
    (position-aligned after netgen reorders them to match), the positions where
    the two sides disagree — each names the offending pin on whichever side is
    not a ``(no matching pin)`` placeholder."""
    out: List[Dict[str, str]] = []
    if not (isinstance(pins, list) and len(pins) == 2
            and all(isinstance(s, list) for s in pins)):
        return out
    lay, src = pins[0], pins[1]
    for i in range(max(len(lay), len(src))):
        lp = str(lay[i]).strip() if i < len(lay) else ""
        sp = str(src[i]).strip() if i < len(src) else ""
        if lp != sp:
            out.append({"layout": lp, "source": sp})
    return out


def localize(json_source: JsonSource) -> Dict[str, Any]:
    """Parse netgen's ``-batch lvs … -json`` structured output into a flat
    short / open / pin LOCALIZATION for triage — the offending nets (netgen's
    ``badnets``), the per-cell net-count delta, the offending devices
    (``badelements``), and the pin-correspondence mismatches (``pins``).

    Returns::

        {"available": bool,                 # False = no netgen -json to read
         "cells": [{"cell","nets","net_delta","offending_nets",
                    "offending_devices","pin_mismatches"}, ...],  # dirty cells
         "offending_nets": [str, ...],       # flat, de-duplicated
         "offending_devices": [str, ...],
         "pin_mismatches": [{"layout","source"}, ...]}

    Read-only, FAIL-SAFE, PURELY ADDITIVE (see the module note above): it never
    participates in the verdict. chip-AGNOSTIC."""
    empty = {"available": False, "cells": [], "offending_nets": [],
             "offending_devices": [], "pin_mismatches": []}
    arr = _load_netgen_json_array(json_source)
    if arr is None:
        return empty
    cells: List[Dict[str, Any]] = []
    all_nets: List[str] = []
    all_devs: List[str] = []
    all_pins: List[Dict[str, str]] = []
    for cell in arr:
        if not isinstance(cell, dict):
            continue
        nets = cell.get("nets")
        net_delta = (abs(nets[0] - nets[1])
                     if isinstance(nets, list) and len(nets) == 2
                     and all(isinstance(n, int) for n in nets) else None)
        bad_nets: List[str] = []
        _harvest_net_names(cell.get("badnets"), bad_nets)
        bad_devs: List[str] = []
        _harvest_net_names(cell.get("badelements"), bad_devs)
        pin_mm = _pin_mismatches(cell.get("pins"))
        if not (bad_nets or bad_devs or pin_mm or net_delta):
            continue                      # clean cell — nothing to localize
        cells.append({
            "cell": _cell_name(cell.get("name")),
            "nets": nets if isinstance(nets, list) else None,
            "net_delta": net_delta,
            "offending_nets": _dedupe(bad_nets),
            "offending_devices": _dedupe(bad_devs),
            "pin_mismatches": pin_mm,
        })
        all_nets += bad_nets
        all_devs += bad_devs
        all_pins += pin_mm
    return {"available": True, "cells": cells,
            "offending_nets": _dedupe(all_nets),
            "offending_devices": _dedupe(all_devs),
            "pin_mismatches": all_pins}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Classify a netgen LVS report's terminal verdict (#524).")
    ap.add_argument("report", help="netgen lvs report / transcript file")
    ap.add_argument("--json", default=None, help="write JSON verdict here")
    ap.add_argument("--json-report", default=None,
                    help="netgen -json structured E1 report (file or dir). "
                         "AUTHORITATIVE when present; defaults to one embedded "
                         "in the transcript, else the fail-safe text path.")
    ap.add_argument("--localize-json", default=None,
                    help="netgen `-batch lvs … -json` output (the per-cell "
                         "ARRAY — file or dir). Adds short/open/pin "
                         "LOCALIZATION (#203); defaults to the report's sibling "
                         "`<stem>.json`. Triage-only — never moves the verdict.")
    args = ap.parse_args(argv)
    p = Path(args.report)
    if not p.is_file():
        print(f"ERROR: report not found: {p}", file=sys.stderr)
        return 2
    blob = p.read_text(errors="replace")
    obj = _resolve_report(blob, args.json_report)
    verdict = classify(blob, json_report=obj)
    # #203 — the netgen `-json` sidecar sits next to the report as `<stem>.json`
    # (e.g. lvs.rpt → lvs.json); use the explicit override when given.
    _loc_src = args.localize_json if args.localize_json else p.with_suffix(".json")
    out = {
        "report": str(p),
        "verdict": verdict,
        "verdict_source": "netgen-json" if obj is not None else "text-fallback",
        "mismatch_class": mismatch_class(blob, json_report=obj),
        "pin_mismatch_evidence": pin_mismatch_evidence(blob),
        "localization": localize(_loc_src),
    }
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(text + "\n")
    print(text)
    # exit semantics: 0 only on a conclusive clean MATCH; 1 otherwise
    # (MISMATCH and INCOMPLETE both refuse sign-off — but the verdict string
    # distinguishes them for triage).
    return 0 if verdict == "MATCH" else 1


if __name__ == "__main__":
    sys.exit(main())
