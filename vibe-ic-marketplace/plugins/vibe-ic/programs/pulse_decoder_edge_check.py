#!/usr/bin/env python3
"""
pulse_decoder_edge_check.py — Enforce rising-edge-driven classification in
LOW-pulse decoders (PPM/PWM/AID/DALI/1-Wire/NEC-IR/UART-break style).

Rule (derived from v052 rtl/rx_phy.v:35-50):

    In any module that classifies LOW-pulse width into multiple buckets,
    the classifier MUST fire on the RISING edge of the input (end of the
    LOW pulse) — not merely on ``low_cnt >= MIN``. Without edge gating,
    the classifier re-emits while the bus stays LOW, producing phantom
    symbols.

Static check (IC-agnostic):

  A file is considered a "LOW-pulse decoder" iff it contains BOTH:

    * at least one identifier matching ``\\bw*low_cnt\\w*\\b`` (generic
      low-pulse counter), AND
    * at least TWO classification predicates against that counter —
      i.e. 2+ lines matching ``low_cnt\\w*\\s*(>=|<=|==|<|>)``.

  For any such file, require at least ONE of:

    1. A delay-chain pattern ``<sig>_q`` + ``<sig>_qq`` (two regs with
       names ending ``_q`` and ``_qq``), AND a rising-edge expression
       ``_qq == 1'b0 && _q == 1'b1`` or ``_q && !_qq`` / ``_qq && !_q``.
    2. An explicit ``posedge <sig>`` in an always/always_ff block where
       the classifier lives.
    3. Any expression of the form ``(<x> && !<x>_q)`` (generic one-stage
       edge detector).

  If none match, FAIL.

Outputs a per-file finding; exit 0 on clean, 1 on any finding, 2 on IO err.

#496 — TWO EXTRACTION BUGS, WHICH ONLY CANCEL EACH OTHER OUT
-----------------------------------------------------------
``files_checked: 0`` on all 107 tracked ``rtl`` directories under
``benchmark-data``. The corpus is NOT free of the design class this gate
audits: ``benchmark-data/evaluation/phase1_parity/sent/phase2/stage1/rtl/
sent_rx.v`` is a SENT (SAE J2716) receiver, i.e. a textbook multi-bucket
pulse-period classifier — it measures falling-edge-to-falling-edge periods and
decodes each into one of sixteen nibble values plus a calibration pulse.

BUG 1 — the "is this a pulse decoder?" test keyed on the LITERAL token
``low_cnt``. SENT spells its counter ``period_cnt`` and its measurement
``last_period`` / ``ticks_meas``, so the file was never selected. One spelling
of one signal name decided whether the gate had any subject at all.

BUG 2 — and this is why fixing Bug 1 alone would have been worse than leaving
it: ``_has_edge_detector`` only recognises RISING-edge idioms with the negation
on the SECOND operand (``sig && !sig_q``). A decoder of LOW pulses measures
FALLING edges, and SENT writes the standard form
``wire falling = (~sin_s) & sin_s_d;`` — negation on the FIRST operand, stage
suffix ``_d``. None of the four existing patterns matches it. Widening the
selector without widening the recognizer would have made this gate emit a
NO_EDGE_DETECTOR error against a design whose edge detector is right there on
line 111 — trading a silent gate for a confidently wrong one.

Both are fixed together, and the SENT file is the regression witness: it must
be SELECTED (``files_checked`` 0 -> 1) and must PASS, and it must FAIL once its
edge detector is removed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Tuple

import _gate_denominator as GD

# #496 — one unit of this gate's denominator, in the gate's own terms.
_DENOM_UNIT = "pulse-width / pulse-period classifier files"


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    severity: str
    category: str
    message: str
    file: str = ""
    details: str = ""


# ---------------------------------------------------------------------------
# Regexes
# ---------------------------------------------------------------------------
_LOW_CNT_NAME_RE = re.compile(r"\b\w*low_cnt\w*\b")

# #496 — a pulse-measurement COUNTER. `low_cnt` is one spelling of one signal;
# a decoder that measures the LOW phase, the HIGH phase, the mark/space, the
# pulse width or the full falling-to-falling PERIOD is the same design class
# and the rule applies identically to all of them.
_PULSE_COUNTER_RE = re.compile(
    r"\b\w*(?:low|lo|high|hi|pulse|period|width|mark|space|tlow|thigh)"
    r"_?(?:cnt|count|counter|timer|len|dur)\w*\b",
    re.IGNORECASE,
)

# Only comparison operators — NOT `<=` (which is Verilog's non-blocking
# assignment and would false-positive on ``low_cnt <= 0``).
_CLASSIFY_RE = re.compile(
    r"\b\w*low_cnt\w*\s*(?:>=|==|!=|<|>)\s*[`\w']"
)

# #496 — a CLASSIFICATION predicate is a comparison whose left side is the
# measurement, which is frequently a signal DERIVED from the counter rather
# than the counter itself: SENT compares `ticks_meas` and `last_period`, not
# `period_cnt`. Tying the predicate to the counter's own name is what made two
# distinct spellings both have to be right for the file to be selected.
_PULSE_CLASSIFY_RE = re.compile(
    r"\b\w*(?:low|lo|high|hi|pulse|period|width|mark|space|ticks|meas|dur)"
    r"\w*\s*(?:>=|==|!=|<|>)\s*[`\w']",
    re.IGNORECASE,
)

# rising-edge patterns
_QQ_PAIR_RE = re.compile(r"\b(\w+)_qq\b")
_Q_SINGLE_RE = re.compile(r"\b(\w+)_q\b")
_POSEDGE_ANY_RE = re.compile(r"\bposedge\s+(\w+)\b")

# Match classic "(x_qq == 1'b0 && x_q == 1'b1)" / reversed order too.
# v0.121: accept optional parens around each predicate — RTL like
#   wire id_rising = (id_qq == 1'b0) && (id_q == 1'b1);
# is logically identical to the bare form but the strict regex rejected
# it. \(? \)? at boundaries are optional; \s+ tolerates whitespace.
_RISING_FROM_QQ_RE = re.compile(
    r"\(?\s*(\w+)_qq\s*==\s*1'b0\s*\)?\s*&&\s*\(?\s*\1_q\s*==\s*1'b1\s*\)?",
)
# v0.119.29: accept BOTH logical (`&&` / `!`) AND bitwise (`&` / `~`)
# rising-edge forms. They're logically equivalent for 1-bit signals,
# and both are common in real RTL — the agent on v0.119.27 vendor wrote
# `(sig & ~sig_q)` and was false-flagged. We use \s*&\s*&? in regex to
# match either single or double `&`; same for `!` vs `~`.
_RISING_FROM_Q_RE = re.compile(
    r"(\w+)\s*&&?\s*[!~]\s*\1_q\b"
)
_RISING_BANG_QQ_RE = re.compile(
    r"(\w+)_q\s*&&?\s*[!~]\s*\1_qq\b"
)

# #496 — FALLING edge, negation on the FIRST operand: `(~sig) & sig_d`, and the
# mirrored `sig_d & ~sig`. Every pattern above puts the `!`/`~` on the SECOND
# operand, so a LOW-pulse decoder — which by definition triggers on the falling
# edge — had no matching pattern at all. The stage suffix set matches
# `_RISING_FUZZY_RE`'s, and the same `_is_fuzzy_edge_pair` predicate gates it,
# so `(~food) & foo_d` is still rejected.
_STAGE_SUFFIX_ALT = r"(?:q\d*|d|r|reg|ff|sync|synced|dly|del|prev|last)"
_FALLING_FROM_D_RE = re.compile(
    r"[!~]\s*\(?\s*(\w+)\s*\)?\s*&&?\s*\(?\s*(\w+)_" + _STAGE_SUFFIX_ALT + r"\b"
)
_FALLING_FROM_D_REV_RE = re.compile(
    r"\b(\w+)_" + _STAGE_SUFFIX_ALT + r"\s*&&?\s*[!~]\s*\(?\s*(\w+)\b"
)

# v0.119.25 fuzzy variant: (X && !Y) where Y ends in a register suffix
# AND Y's stem and X share enough common prefix. Catches the
# vendor-benchmark case `id_bus_rx_eff && !id_bus_rx_q` where the strict
# `\1_q` form rejected because the names differ. v0.119.26 tightened the
# pairing predicate (see `_is_fuzzy_edge_pair`) so adversarial cases
# like `(food && !foo_q)` and `(data_rx_eff && !data_tx_q)` no longer
# count.
_RISING_FUZZY_RE = re.compile(
    # v0.119.29: also accept bitwise `&` / `~` (logically equivalent
    # to `&&` / `!` for 1-bit signals; both forms appear in real RTL).
    r"(\w+)\s*&&?\s*[!~]\s*(\w+)_(?:q\d*|d|r|reg|ff|sync|synced)\b"
)


# v0.119.26: bracket the prefix-shortcut with a whitelist of typical
# staged-signal suffixes so unrelated names like (food, foo) — where
# `foo` is mechanically a prefix of `food` — no longer count as a pair.
# Real Vibe-IC RTL uses these to denote a derived/effective form of a
# raw signal: `_eff` (effective post-mask), `_d` (delayed), `_pre`
# (pre-stage), `_sync`/`_synced` (CDC-aligned), `_int` (internal),
# `_n` (negated). A stem `foo` becoming `food` is not on this list.
_STAGED_SUFFIXES = ("_eff", "_d", "_pre", "_sync", "_synced",
                    "_int", "_n", "_r", "_reg")


def _is_fuzzy_edge_pair(x: str, y: str, min_common: int = 6) -> bool:
    """Decide whether `x` and `y_<reg>` are a plausible edge-detector
    pair.

    A pair qualifies if EITHER:
      (a) one name is a prefix of the other AND the longer name's
          extra suffix is in `_STAGED_SUFFIXES` (rules out `food` vs
          `foo` where the extra is just `d`); OR
      (b) they share a common prefix of `>=min_common` chars AND that
          prefix does NOT end at an underscore boundary (rules out
          `data_rx_eff` vs `data_tx_q` sharing only `data_` — that's
          a module/group prefix, not a related signal stem).

    v0.119.26: tightened from v0.119.25's `min_common=4` + bare
    `startswith` shortcut, which let two adversarial cases through."""
    xl, yl = x.lower(), y.lower()
    if xl == yl:
        return True
    # Prefix shortcut — only when the extra suffix is a known stage tag.
    if xl.startswith(yl):
        extra = xl[len(yl):]
        return extra in _STAGED_SUFFIXES
    if yl.startswith(xl):
        extra = yl[len(xl):]
        return extra in _STAGED_SUFFIXES
    # Common-prefix path — require enough chars AND that the boundary
    # falls inside a token (not at an underscore — those are usually
    # module/scope group prefixes, not signal stems).
    n = 0
    for a, b in zip(xl, yl):
        if a != b:
            break
        n += 1
    if n < min_common:
        return False
    if xl[n - 1] == "_":
        return False
    return True


def _find_v_files(rtl_dir: Path) -> List[Path]:
    return sorted(
        [p for p in rtl_dir.rglob("*")
         if p.is_file() and p.suffix.lower() in (".v", ".sv")]
    )


def _is_pulse_decoder(text: str) -> bool:
    """True iff the file measures a pulse and classifies it into 2+ buckets.

    #496 — the original form required the literal token ``low_cnt`` for BOTH
    halves. Kept as the first branch (unchanged behaviour for files that spell
    it that way), with the generalised form as the second.
    """
    if _LOW_CNT_NAME_RE.search(text) and len(_CLASSIFY_RE.findall(text)) >= 2:
        return True
    if not _PULSE_COUNTER_RE.search(text):
        return False
    return len(_PULSE_CLASSIFY_RE.findall(text)) >= 2


def _has_edge_detector(text: str) -> bool:
    """True iff the file contains evidence of a rising-edge detector."""
    # Pattern 1: dual delay-chain (X_q AND X_qq for same prefix)
    q_prefixes = {m.group(1) for m in _Q_SINGLE_RE.finditer(text)}
    qq_prefixes = {m.group(1) for m in _QQ_PAIR_RE.finditer(text)}
    dual = q_prefixes & qq_prefixes
    if dual:
        # Must also see an actual rising-edge expression involving one of them.
        if _RISING_FROM_QQ_RE.search(text):
            return True
        if _RISING_BANG_QQ_RE.search(text):
            return True

    # Pattern 2: posedge on ANY signal (not just clk) inside an always block.
    # Any `posedge <sig>` beyond the expected clock counts as edge-driven.
    if _POSEDGE_ANY_RE.search(text):
        # Heuristic: if there is more than one distinct signal under
        # `posedge`, this file clearly samples an edge of a non-clock input.
        distinct = {m.group(1) for m in _POSEDGE_ANY_RE.finditer(text)}
        if len(distinct) >= 2:
            return True

    # Pattern 3: one-stage (sig && !sig_q) — strict same-name pairing.
    if _RISING_FROM_Q_RE.search(text):
        return True

    # Pattern 4 (v0.119.25): fuzzy pairing — (X && !Y_<reg>) where X
    # and Y share a common prefix. Closes the vendor-benchmark gap
    # where `id_bus_rx_eff && !id_bus_rx_q` was rejected by the strict
    # form even though it IS a valid one-stage edge detector.
    for m in _RISING_FUZZY_RE.finditer(text):
        if _is_fuzzy_edge_pair(m.group(1), m.group(2)):
            return True

    # Pattern 5 (#496): FALLING edge — `(~sig) & sig_d` / `sig_d & ~sig`.
    # A LOW-pulse decoder fires at the END of the low phase, which is a
    # falling-to-rising transition of the pulse it just measured and a
    # FALLING edge of the line for period-measuring protocols. Gated by the
    # same pairing predicate as Pattern 4, so unrelated names do not count.
    for rx in (_FALLING_FROM_D_RE, _FALLING_FROM_D_REV_RE):
        for m in rx.finditer(text):
            a, b = m.group(1), m.group(2)
            if _is_fuzzy_edge_pair(a, b):
                return True

    return False


def audit(rtl_dir: Path) -> Tuple[List[Finding], Dict]:
    findings: List[Finding] = []
    if not rtl_dir.exists() or not rtl_dir.is_dir():
        findings.append(Finding(
            severity="ERROR",
            category="IO",
            message=f"RTL directory not found: {rtl_dir}",
        ))
        return findings, {"decoders": [], "checked": 0, "files_scanned": 0}

    v_files = _find_v_files(rtl_dir)
    decoders: List[str] = []
    checked = 0
    files_scanned = 0

    for p in v_files:
        try:
            text = p.read_text(errors="replace")
        except OSError as e:
            findings.append(Finding(
                severity="ERROR",
                category="IO",
                message=f"Cannot read file: {e}",
                file=str(p),
            ))
            continue
        files_scanned += 1

        if not _is_pulse_decoder(text):
            continue
        decoders.append(str(p))
        checked += 1

        if not _has_edge_detector(text):
            findings.append(Finding(
                severity="ERROR",
                category="NO_EDGE_DETECTOR",
                message=(
                    "File looks like a LOW-pulse classifier (contains "
                    "'low_cnt' and 2+ classification predicates) but has "
                    "no rising-edge detector (no <sig>_q/<sig>_qq pair "
                    "with (qq==0 && q==1), no (sig && !sig_q), and no "
                    "extra `posedge <sig>` beyond the clock). "
                    "Classifier may re-fire every cycle while LOW."
                ),
                file=str(p),
            ))

    return findings, {"decoders": decoders, "checked": checked,
                      "files_scanned": files_scanned}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _denominator(summary: Dict) -> GD.Denominator:
    checked = summary.get("checked", 0)
    files = summary.get("files_scanned", 0)
    details = {"files_scanned": files, "decoder_files": summary.get("decoders", [])}
    if checked:
        return GD.Denominator(unit=_DENOM_UNIT, examined=checked,
                              considered=files, details=details)
    if files == 0:
        reason = "no readable .v/.sv file in this directory."
    else:
        reason = (
            f"{files} RTL file(s) read, none of which measures a pulse and "
            "classifies the measurement into 2+ buckets. A file qualifies "
            "when it names a pulse/period/width/mark/space counter AND makes "
            "2+ comparison predicates against a pulse measurement. This "
            "design decodes no pulse-width-encoded line, so the rising-edge "
            "gating rule has no subject here.")
    return GD.Denominator(unit=_DENOM_UNIT, examined=0, considered=files,
                          not_applicable_reason=reason, details=details)


def build_report(findings: List[Finding], rtl_dir: Path, summary: Dict) -> Dict:
    return {
        "program": "pulse_decoder_edge_check",
        "version": "1.0.0",
        "rtl_dir": str(rtl_dir),
        "summary": GD.attach({
            "decoder_files": summary["decoders"],
            "files_checked": summary["checked"],
            "files_scanned": summary.get("files_scanned", 0),
            "findings_count": len(findings),
            "pass": not any(f.severity == "ERROR" for f in findings),
        }, _denominator(summary)),
        "findings": [asdict(f) for f in findings],
    }


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(
        description=("Flag LOW-pulse decoders that classify without a "
                     "rising-edge gate.")
    )
    parser.add_argument("--rtl-dir", required=True,
                        help="Directory containing .v / .sv RTL files")
    parser.add_argument("--json", dest="json_out", default=None,
                        help="Optional path to write machine-readable report")
    args = parser.parse_args(argv)

    rtl_dir = Path(args.rtl_dir)
    try:
        findings, summary = audit(rtl_dir)
    except OSError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    report = build_report(findings, rtl_dir, summary)
    report_json = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(report_json)

    print(report_json)
    # IO errors (missing RTL dir etc.) → exit 2 per the gate exit-code contract
    # (0 PASS / 1 FAIL / 2 input-missing).
    if any(getattr(f, "category", "") == "IO" for f in findings):
        return 2
    return 0 if report["summary"]["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
