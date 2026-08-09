#!/usr/bin/env python3
"""wake_pulse_implementation_check.py — LL-11 / Wake-pulse value gate.

For protocol-IC projects whose L2 spec mandates a chip-driven wake
pulse (e.g. accessory ID-bus protocols where the chip pulls the bus
low for a fixed window so the host's BIT0 classifier can detect
presence), the RTL must:

  (a) actually contain a state machine / counter that drives the pulse
      (the structural check that has existed since the gate was first
      introduced), AND
  (b) produce a pulse whose width FALLS INSIDE the host RX BIT0
      classifier window (the value-based check added in Wave 9 /
      v0.119.41).

Why the value check matters
===========================
The v0.119.40 fresh-agent benchmark proved that step (a) alone is not
enough. That run shipped a `wake_pulse_gen.sv` with the right FSM and
counters but TWK_PULSE = 5 clk × 200 ns/clk = 1 µs — far below the
host's BIT0 minimum LOW of ~3.6 µs — so the host's RX classified the
pulse as BIT1 / noise and the connect test reported "DUT silent".
The original gate skipped the project because its L2 schema lookup
expected only the abbreviated key `tWK_us`.

Behaviour summary
=================
1. **Resolve wake-pulse width** under any of a chip-AGNOSTIC list of
   synonym key paths in L2 / L8 (`wake_pulse_width_us`, `tWK_us`,
   `tWAKE_us`, `t_wake_us`, `TWK_PULSE`, `wake.pulse.width`,
   `timing.wake_pulse_us`, `rtl_constants.TWK_PULSE`, …). Counter
   values found in L8 are converted to µs using the clock period.
2. **Resolve host BIT0 LOW-min** under any of `H0_min`, `H0_MIN`,
   `bit0_low_min_tick`, `bit0_low_min_us`, `rx.bit0.low_min`, …
   from L8 / L2 / `vendor_fpga_reference_table` /
   `rx_classifier_ticks`. Tick values are converted to µs using the
   clock period.
3. **Resolve clock period** from `clock_period_ns` / `tick_ns` /
   `internal_clock_MHz` / `clock_MHz`. Default 20 ns (50 MHz) with a
   WARN if nothing resolves.
4. **Verdict**:
     - FAIL if `wake_pulse_us < bit0_low_min_us` (BIT0 misclassify).
     - WARN if `wake_pulse_us` is within ±20% of either edge of the
       BIT0 window (boundary risk).
     - PASS otherwise.
5. **Missing inputs**:
     - If neither pulse nor classifier resolves AND no waiver →
       FAIL (previously SKIP — Wave-9 fix; SKIP let v0.119.40 slip
       through). The gate emits a clear "synonyms searched" listing
       so an honest project can ship a waiver with rationale, but
       silent skip is no longer the default.
6. **Waivers**:
     - `wake_pulse_alternative_implementation` (legacy) — silences
       the structural-only branch when the wake pulse comes from an
       external block.
     - `wake_pulse_width_skipped_intentional` (Wave 9, ≥40 chars
       rationale) — silences the value-based branch when the project
       legitimately has no host-side BIT0 classifier (e.g. async
       protocols).
     - `wake_pulse_classifier_mode_override` (Wave 10, ≥40 chars
       rationale) — silences the value branch for protocols where
       neither WKP nor BIT0 mode applies cleanly (custom symbol
       classes documented in a project-specific note).

WKP-vs-BIT0 mode (Wave 10 / v0.119.42)
======================================
Some half-duplex single-wire protocols define a SEPARATE wake-pulse
classifier symbol (`WKP`) whose minimum width is strictly longer
than `BIT0` LOW-max. When the host's RX classifier has three
distinct symbol classes (BIT0 / BIT1 / WKP), the wake pulse must
satisfy `wake_pulse_us ≥ wkp_min_us`, NOT the BIT0 LOW window.
The gate auto-detects this when it can resolve `wkp_min` (or
synonym) AND `wkp_min_tick > bit0_low_max_tick`, in which case:
  - the BIT0 upper-edge check is dropped entirely;
  - a wake pulse inside the BIT0 window FAILs (it would be
    classified as BIT0 by the host, never as a wake event).
For protocols where only the BIT0 window resolves (no WKP
classifier symbol), the original Wave-9 behaviour is preserved.

Generality
==========
The synonym lists are protocol-class generic (single-wire half-duplex
ID-bus accessory protocols). They do NOT name any chip / tester / PDK.

THE FAIL VERDICT WAS UNREACHABLE IN PRODUCTION (fix landed here)
===============================================================
Everything above describes verdicts this gate could not emit where it
runs. Two defects held each other up, and each hid the other:

1. ``main`` returned ``1 if args.strict else 0``. The ONLY production
   caller is the P0 structural umbrella in ``flow_compliance_check``
   (``_structural_gate_argv`` -> ``_eval_gate_worker``), and that
   builds ``[python, <gate>.py, <project>]`` — this gate is in neither
   ``_STRUCTURAL_GATE_ARGV_ADAPTERS`` nor ``_STRUCTURAL_GATE_BARE_FLAGS``,
   so ``--strict`` is never supplied. Every ERROR above printed
   ``FAIL — ...`` on stdout and exited 0, and the worker records rc 0 as
   PASS without reading stdout. This gate's own tests all passed
   ``--strict``, i.e. they exercised an argv production never builds.

2. The value branch treated "neither the wake-pulse width NOR any host
   classifier window resolved" as an ERROR. MEASURED over the 117
   project directories in the tracked corpus that carry L docs and/or an
   RTL directory: 105 produced an ERROR finding, 99 of them
   ``WAKE_PULSE_VALUES_UNRESOLVED`` on projects whose L docs say nothing
   about a wake pulse at all. That is not a verdict about a design; it
   is the gate reporting its own empty denominator as a design defect.

Defect 1 alone is why nobody noticed defect 2, and fixing 1 alone would
have turned ~105 of 117 corpus projects red for a reason none of them
has anything to do with. Both are fixed together:

* The exit code is now routed from the gate's OWN conclusion through
  ``_vacuous_exit`` — the plugin-wide rc convention the umbrella already
  reads (rc 0 PASS / rc 1 FAIL / rc 2 VACUOUS -> SKIP with a named
  reason). ``--strict`` is accepted for backwards compatibility and
  IGNORED; no caller has to learn a flag for the gate to be able to fail.
* "Examined nothing" is now VACUOUS, not FAIL and not PASS. A project
  whose L docs declare no wake pulse and no host classifier window gets
  rc 2 plus the ``VACUOUS_PASS:`` disclosure line — which is strictly
  MORE honest than the plain PASS it used to be credited with, and is
  not a red.
* Applicability is decided from STRUCTURED evidence (a resolvable
  wake-pulse width / WKP minimum / BIT0 window, or a declared WAKE
  symbol class carrying timing fields), not from the substring "wake"
  appearing anywhere in any L doc. The old sniff matched a bare
  ``{"name": "wake", "kind": "upper_ident"}`` row in an auto-extracted
  identifier list and an unrelated ``twakeup`` sideband signal, which
  would have turned six corpus projects red on a keyword.

Severity: ERROR.
Exit codes: 0 PASS / 1 FAIL / 2 VACUOUS (examined nothing) or
invalid-input.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

import _vacuous_exit as _vx
from gate_utils import find_rtl_files, read_text


@dataclass
class Finding:
    severity: str
    rule: str
    message: str
    file: str = ""


# ---------------------------------------------------------------------
# Synonym tables — chip/protocol AGNOSTIC. Every name here is a generic
# protocol-engineering term (`wake`, `pulse`, `bit0`, `H0`, `low`,
# `min`, `tick`, …); none names a particular chip, tester, or PDK.
# ---------------------------------------------------------------------

# Wake-pulse width, expressed directly in µs.
_WAKE_US_KEYS: tuple[str, ...] = (
    "wake_pulse_width_us",
    "wake_pulse_us",
    "wake_pulse_us_typ",
    "twk_us", "twake_us", "t_wake_us",
    "wake.pulse.width", "wake.pulse.width_us",
    "timing.wake_pulse_us",
    "wake.width_us",
)

# Wake-pulse width, expressed in clock ticks (counter constants).
_WAKE_TICK_KEYS: tuple[str, ...] = (
    "twk_pulse", "twk_ticks",
    "twake_pulse", "twake_ticks",
    "wake_pulse_ticks", "wake_pulse_clk",
    "wake_pulse_cnt",
    "rtl_constants.twk_pulse", "rtl_constants.twk_ticks",
    "rtl_constants.twake_pulse",
)

# Host RX BIT0 LOW-minimum, in µs.
_BIT0_US_KEYS: tuple[str, ...] = (
    "bit0_low_min_us", "h0_min_us",
    "rx.bit0.low_min_us", "rx.bit0.min_us",
    "rx_classifier.bit0_low_min_us",
)

# Host RX BIT0 LOW-minimum, in ticks.
_BIT0_TICK_KEYS: tuple[str, ...] = (
    "h0_min", "h0_min_tick", "h0_min_ticks",
    "bit0_low_min_tick", "bit0_low_min_ticks",
    "rx_classifier_ticks.h0_min",
    "rx_classifier_ticks.bit0_low_min",
    "vendor_fpga_reference_table.h0_min",
    "vendor_fpga_reference_table.bit0_low_min_tick",
)

# Host RX BIT0 LOW-MAX (used for upper-edge boundary WARN).
_BIT0_MAX_US_KEYS: tuple[str, ...] = (
    "bit0_low_max_us", "h0_max_us",
    "rx.bit0.low_max_us", "rx.bit0.max_us",
)
_BIT0_MAX_TICK_KEYS: tuple[str, ...] = (
    "h0_max", "h0_max_tick", "h0_max_ticks",
    "bit0_low_max_tick", "bit0_low_max_ticks",
    "rx_classifier_ticks.h0_max",
    "rx_classifier_ticks.bit0_low_max",
    "vendor_fpga_reference_table.h0_max",
    "vendor_fpga_reference_table.bit0_low_max_tick",
)

# Host RX dedicated WKP (wake-pulse) classifier minimum.
# When this resolves AND the resolved value exceeds bit0_low_max,
# the host has a SEPARATE WKP symbol class — wake pulse must satisfy
# `wake_pulse >= wkp_min` and the BIT0 upper-edge check no longer
# applies (Wave 10 / v0.119.42).
_WKP_US_KEYS: tuple[str, ...] = (
    "wkp_min_us", "wake_pulse_min_us",
    "wake_classifier_min_us", "wake_min_us",
    "rx.wkp.min_us", "rx_classifier.wkp_min_us",
    "rx.wake.min_us",
)
_WKP_TICK_KEYS: tuple[str, ...] = (
    "wkp_min", "wkp_min_tick", "wkp_min_ticks",
    "wake_classifier_min_tick", "wake_classifier_min_ticks",
    "wake_pulse_min_tick", "wake_pulse_min_ticks",
    "wake_min_tick", "wake_min_ticks",
    "rx_classifier_ticks.wkp_min",
    "rx_classifier_ticks.wake_pulse_min",
    "rx_classifier_ticks.wake_min",
    "vendor_fpga_reference_table.wkp_min",
    "vendor_fpga_reference_table.wake_pulse_min_tick",
)

# Clock period.
_CLOCK_NS_KEYS: tuple[str, ...] = (
    "clock_period_ns", "clk_period_ns", "tick_ns",
    "rtl_constants.clock_period_ns",
)
_CLOCK_MHZ_KEYS: tuple[str, ...] = (
    "internal_clock_mhz", "clock_mhz", "clk_mhz",
    "rtl_constants.internal_clock_mhz",
    "rtl_constants.clock_mhz",
)

DEFAULT_CLOCK_NS = 20.0  # 50 MHz fallback; emits WARN when used.


# ---------------------------------------------------------------------
# Generic recursive key lookup.
# ---------------------------------------------------------------------

def _walk(data: Any, path: tuple[str, ...]) -> Optional[Any]:
    """Walk `data` along path tokens (case-insensitive)."""
    cur = data
    for tok in path:
        tok_l = tok.lower()
        if isinstance(cur, dict):
            match = None
            for k in cur:
                if isinstance(k, str) and k.lower() == tok_l:
                    match = k
                    break
            if match is None:
                return None
            cur = cur[match]
        else:
            return None
    return cur


def _scan_synonyms(data: Any, keys: Iterable[str]) -> Optional[tuple[str, Any]]:
    """Return (matched_synonym, value) for the first synonym hit."""
    if not isinstance(data, dict):
        return None
    for key in keys:
        path = tuple(p for p in key.split(".") if p)
        v = _walk(data, path)
        if v is None:
            # Also try recursive scan: find any sub-dict whose path
            # ends with this token, useful for deeply nested L docs.
            v = _recursive_find(data, path)
        if v is not None:
            return key, v
    return None


def _recursive_find(data: Any, path: tuple[str, ...]) -> Optional[Any]:
    """Look for `path` starting at any depth in `data`."""
    if not path:
        return None
    head = path[0].lower()
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(k, str) and k.lower() == head:
                if len(path) == 1:
                    return v
                deeper = _walk(v, path[1:])
                if deeper is not None:
                    return deeper
        for v in data.values():
            r = _recursive_find(v, path)
            if r is not None:
                return r
    elif isinstance(data, list):
        for it in data:
            r = _recursive_find(it, path)
            if r is not None:
                return r
    return None


def _coerce_number(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        m = re.match(r"\s*([-+]?\d+(?:\.\d+)?)", v)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None
    return None


# ---------------------------------------------------------------------
# Doc loading.
# ---------------------------------------------------------------------

def _load_l_docs(project: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for sub in ("phase1/generated_docs", "generated_docs", "input/docs"):
        d = project / sub
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.json")):
            try:
                out[p.name] = json.loads(read_text(p) or "{}")
            except json.JSONDecodeError:
                continue
    return out


def _resolve_clock_ns(docs: dict[str, dict]) -> tuple[Optional[float], list[str]]:
    """Return (clock_ns, evidence). evidence empty when defaulted."""
    evidence: list[str] = []
    for doc_name, data in docs.items():
        hit = _scan_synonyms(data, _CLOCK_NS_KEYS)
        if hit:
            n = _coerce_number(hit[1])
            if n is not None and n > 0:
                evidence.append(f"{doc_name}.{hit[0]}={n}")
                return n, evidence
        hit = _scan_synonyms(data, _CLOCK_MHZ_KEYS)
        if hit:
            n = _coerce_number(hit[1])
            if n is not None and n > 0:
                ns = 1000.0 / n
                evidence.append(f"{doc_name}.{hit[0]}={n}MHz→{ns:.2f}ns")
                return ns, evidence
    return None, evidence


def _resolve_value(docs: dict[str, dict],
                   us_keys: Iterable[str],
                   tick_keys: Iterable[str],
                   clock_ns: float) -> tuple[Optional[float], list[str]]:
    """Resolve a wake-pulse / classifier value in µs.

    Tries µs synonyms first, then tick synonyms (×clock_ns/1000).
    Returns (value_us, evidence_list).
    """
    evidence: list[str] = []
    for doc_name, data in docs.items():
        hit = _scan_synonyms(data, us_keys)
        if hit:
            n = _coerce_number(hit[1])
            if n is not None:
                evidence.append(f"{doc_name}.{hit[0]}={n}us")
                return n, evidence
    for doc_name, data in docs.items():
        hit = _scan_synonyms(data, tick_keys)
        if hit:
            n = _coerce_number(hit[1])
            if n is not None:
                us = n * clock_ns / 1000.0
                evidence.append(
                    f"{doc_name}.{hit[0]}={n}tk×{clock_ns}ns→{us:.3f}us")
                return us, evidence
    return None, evidence


# ---------------------------------------------------------------------
# Structural detection (preserved from earlier waves).
# ---------------------------------------------------------------------

_WAKE_STATE_RE = re.compile(
    r"\b(S_WAKE\w*|WAKE_DRIVE\w*|WAKE_PULSE\w*)\b"
)
_WAKE_SIGNAL_RE = re.compile(
    r"\b(wake_drv|wake_pulse_drv|wake_pulse_drive|wake_active|"
    r"tx_wake|wake_drive|wake_low_drv)\b"
)
_TITO_REF_RE = re.compile(r"\b(TITO_TICKS|tito_cnt|ito_cnt|wake_period_cnt)\b")
_TWK_REF_RE = re.compile(r"\b(TWK_PULSE|TWK_TICKS|twk_cnt|wake_pulse_cnt)\b")


def _strip_verilog_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def _rtl_implements_wake(rtl_files: list[Path]) -> tuple[bool, list[str]]:
    state_hits: list[str] = []
    signal_hits: list[str] = []
    counter_hits: dict[str, list[str]] = {"tito": [], "twk": []}
    for f in rtl_files:
        text = _strip_verilog_comments(read_text(f))
        for m in _WAKE_STATE_RE.finditer(text):
            state_hits.append(f"{f.name}: {m.group(0)}")
        for m in _WAKE_SIGNAL_RE.finditer(text):
            signal_hits.append(f"{f.name}: {m.group(0)}")
        if _TITO_REF_RE.search(text):
            counter_hits["tito"].append(f.name)
        if _TWK_REF_RE.search(text):
            counter_hits["twk"].append(f.name)
    impl = (
        bool(state_hits) or
        bool(signal_hits) or
        (bool(counter_hits["tito"]) and bool(counter_hits["twk"]))
    )
    evidence: list[str] = state_hits + signal_hits + (
        [f"counters: tito@{counter_hits['tito']}, twk@{counter_hits['twk']}"]
        if (counter_hits["tito"] or counter_hits["twk"]) else []
    )
    return impl, evidence


#: Key-name TOKENS that make a dict entry a TIMING declaration. Compared as
#: whole tokens, never as substrings: `"us" in "bus"` and `"min" in "terminal"`
#: are both true, and a substring test is how a keyword sniff becomes a verdict.
#:
#: `len` is deliberately ABSENT. It was in the first draft, and MEASURED it
#: turned one corpus project red on its own: an opcode table row
#: `{"hex": "0x11", "name": "wake", "rx_len": "var", "tx_len": "var"}` — a
#: PAYLOAD LENGTH, not a pulse duration. The set is durations only.
_TIMING_KEY_TOKENS: frozenset = frozenset({
    "us", "ns", "ms", "usec", "nsec", "tick", "ticks", "clk", "clocks",
    "min", "max", "width", "duration", "period", "low", "high",
})

#: Normalised spellings of the WAKE / WKP symbol class.
_WAKE_CLASS_NAMES: frozenset = frozenset({
    "wake", "wkp", "wakepulse", "wake_pulse", "wakeup_pulse",
})

#: Key names that carry a symbol / class / state IDENTIFIER.
_CLASS_NAME_TOKENS: frozenset = frozenset({
    "class", "classname", "symbol", "state", "name", "id", "pulse", "kind",
})


def _key_tokens(key: str) -> set:
    """Split a JSON key into lowercase word tokens.

    `class_name` -> {class, name}; `min_us` -> {min, us}; `tWK_us` ->
    {t, wk, us}; `classNameSpelling` -> {class, name, spelling}. Splitting
    on non-alphanumerics AND on camelCase boundaries is what lets the
    caller ask "does this key CARRY the token `us`" instead of "does the
    string `us` occur inside it" — the second question is true of `bus`.
    """
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", key)
    return {t for t in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if t}


def _normalise_class_name(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[^a-z0-9_]+", "", value.strip().lower())


def _declares_wake_symbol_class(data: Any) -> Optional[str]:
    """Evidence that a doc declares a WAKE / WKP *symbol class*, or None.

    WHY THIS REPLACED A SUBSTRING SNIFF. The predecessor
    (`_l2_or_l8_mentions_wake`) serialised each L doc to JSON, lowercased
    it, and returned True on any of `twk` / `twake` / `wake_pulse` /
    `"wake"`. That decided whether the STRUCTURAL branch — "the spec
    mandates a wake pulse but no RTL implements it" — applied to a
    project. MEASURED over the tracked corpus, six projects satisfied it
    on evidence that is not a mandate for anything:

      * a bare ``{"name": "wake", "kind": "upper_ident"}`` row in an L1
        auto-extracted identifier list (four projects);
      * an unrelated ``twakeup`` low-power sideband signal on a
        source-synchronous parallel bus, which is not a chip-driven
        pulse at all;
      * a prose sentence under a key literally named ``wake``.

    Once the exit code stopped being pinned to 0 (see module docstring),
    every one of those became a FAIL naming a pulse the design was never
    asked for. The gate's subject is a wake pulse with a WIDTH, so the
    predicate now demands a declaration that has one: a dict that both
    NAMES the wake symbol class and carries at least one timing field.
    `{"class_name": "WAKE", "min_us": 22.0, "max_us": 28.0}` qualifies;
    `{"name": "wake", "kind": "upper_ident"}` does not, and neither does
    `{"hex": "0x11", "name": "wake", "rx_len": "var"}`.

    Returns a short evidence string (so the summary can say WHY the gate
    considered itself applicable) or None.
    """
    if isinstance(data, dict):
        named = ""
        for k, v in data.items():
            if not isinstance(k, str):
                continue
            if (_key_tokens(k) & _CLASS_NAME_TOKENS
                    and _normalise_class_name(v) in _WAKE_CLASS_NAMES):
                named = f"{k}={v}"
                break
        if named:
            for k in data:
                if isinstance(k, str) and (_key_tokens(k)
                                           & _TIMING_KEY_TOKENS):
                    return f"{{{named}, {k}=...}}"
        for v in data.values():
            hit = _declares_wake_symbol_class(v)
            if hit:
                return hit
    elif isinstance(data, list):
        for item in data:
            hit = _declares_wake_symbol_class(item)
            if hit:
                return hit
    return None


def _wake_class_evidence(docs: dict[str, dict]) -> list[str]:
    """Every doc that declares a WAKE / WKP symbol class, with evidence."""
    out: list[str] = []
    for doc_name, data in docs.items():
        hit = _declares_wake_symbol_class(data)
        if hit:
            out.append(f"{doc_name}:{hit}")
    return out


# ---------------------------------------------------------------------
# Waiver lookup.
# ---------------------------------------------------------------------

def _waiver_rationale(project: Path, waiver_id: str,
                      *, min_chars: int = 1) -> str:
    for cand in (project / "waivers.json",
                 *project.glob("**/waivers.json")):
        if not cand.exists():
            continue
        try:
            data = json.loads(read_text(cand) or "{}")
        except json.JSONDecodeError:
            continue
        entries = data if isinstance(data, list) else (
            data.get("waivers") or data.get("waived_steps") or []
        )
        if not isinstance(entries, list):
            continue
        for e in entries:
            if not isinstance(e, dict):
                continue
            if e.get("id") == waiver_id:
                rat = e.get("rationale") or e.get("reason") or ""
                if isinstance(rat, str) and len(rat.strip()) >= min_chars:
                    return rat.strip()
    return ""


# ---------------------------------------------------------------------
# Main inspection.
# ---------------------------------------------------------------------

def inspect(project: Path) -> tuple[list[Finding], dict]:
    findings: list[Finding] = []
    summary: dict = {
        "spec_mandates_wake": False,
        "rtl_implements_wake": False,
        "rtl_evidence": [],
        "wake_pulse_us": None,
        "wake_pulse_evidence": [],
        "bit0_low_min_us": None,
        "bit0_low_min_evidence": [],
        "bit0_low_max_us": None,
        "bit0_low_max_evidence": [],
        "wkp_min_us": None,
        "wkp_min_evidence": [],
        "classifier_mode": None,  # "WKP" / "BIT0" / None
        "clock_ns": None,
        "clock_evidence": [],
        "synonyms_searched": {
            "wake_pulse_us": list(_WAKE_US_KEYS),
            "wake_pulse_ticks": list(_WAKE_TICK_KEYS),
            "bit0_low_min_us": list(_BIT0_US_KEYS),
            "bit0_low_min_ticks": list(_BIT0_TICK_KEYS),
            "wkp_min_us": list(_WKP_US_KEYS),
            "wkp_min_ticks": list(_WKP_TICK_KEYS),
        },
        "warnings": [],
        "skipped_reason": "",
        # ---- the `_vacuous_exit` contract -----------------------------
        # `skipped` and `reason` are the two fields `_vacuous_exit` reads
        # to route this gate's exit code. They are set from `examined`
        # below — the gate's own record of what it actually looked at —
        # so the printed verdict and the exit code cannot disagree.
        "skipped": False,
        "reason": "",
        "examined": {"structural": False, "value": False},
        "wake_class_evidence": [],
    }

    docs = _load_l_docs(project)
    if not docs:
        summary["skipped_reason"] = "no L*.json under generated_docs/"
        summary["skipped"] = True
        summary["reason"] = "no_l_docs"
        return findings, summary

    # --- Clock period ---
    clock_ns, clock_ev = _resolve_clock_ns(docs)
    if clock_ns is None:
        clock_ns = DEFAULT_CLOCK_NS
        summary["warnings"].append(
            f"clock period defaulted to {DEFAULT_CLOCK_NS} ns "
            "(no clock_period_ns / internal_clock_MHz / tick_ns "
            "resolved); tick→µs conversions are approximate.")
    summary["clock_ns"] = clock_ns
    summary["clock_evidence"] = clock_ev

    # --- Wake pulse value ---
    wake_us, wake_ev = _resolve_value(
        docs, _WAKE_US_KEYS, _WAKE_TICK_KEYS, clock_ns)
    summary["wake_pulse_us"] = wake_us
    summary["wake_pulse_evidence"] = wake_ev

    # --- BIT0 classifier window ---
    bit0_min_us, bit0_min_ev = _resolve_value(
        docs, _BIT0_US_KEYS, _BIT0_TICK_KEYS, clock_ns)
    summary["bit0_low_min_us"] = bit0_min_us
    summary["bit0_low_min_evidence"] = bit0_min_ev
    bit0_max_us, bit0_max_ev = _resolve_value(
        docs, _BIT0_MAX_US_KEYS, _BIT0_MAX_TICK_KEYS, clock_ns)
    summary["bit0_low_max_us"] = bit0_max_us
    summary["bit0_low_max_evidence"] = bit0_max_ev

    # --- Dedicated WKP classifier window (Wave 10) ---
    wkp_min_us, wkp_min_ev = _resolve_value(
        docs, _WKP_US_KEYS, _WKP_TICK_KEYS, clock_ns)
    summary["wkp_min_us"] = wkp_min_us
    summary["wkp_min_evidence"] = wkp_min_ev

    # Classifier mode detection. WKP mode wins ONLY when wkp_min
    # actually dominates bit0_low_max — i.e. the host's classifier
    # genuinely treats WKP as a longer-than-BIT0 symbol class. If
    # wkp resolves but is ≤ bit0_low_max, the spec is internally
    # ambiguous and we fall back to BIT0 mode (the safer historic
    # behaviour).
    wkp_mode = (
        wkp_min_us is not None
        and bit0_max_us is not None
        and wkp_min_us > bit0_max_us
    )
    if wkp_mode:
        summary["classifier_mode"] = "WKP"
    elif bit0_min_us is not None or bit0_max_us is not None:
        summary["classifier_mode"] = "BIT0"

    # ---- Applicability, from STRUCTURED evidence only ------------------
    #
    # Two separate subjects, kept separate because they license different
    # branches:
    #
    #   wake_subject       the design is asked to DRIVE a wake pulse — a
    #                      resolvable wake-pulse width, a resolvable WKP
    #                      classifier minimum, or a declared WAKE symbol
    #                      class carrying timing fields. This is what
    #                      licenses the STRUCTURAL branch to say "the spec
    #                      mandates a wake pulse but no RTL implements it".
    #   classifier_subject the HOST declares a receive window the pulse has
    #                      to land in. This is what licenses the VALUE
    #                      branch to say a declared width is out of range.
    #
    # Neither is a keyword sniff any more; see `_declares_wake_symbol_class`
    # for the six corpus projects the sniff would have turned red.
    wake_class_ev = _wake_class_evidence(docs)
    summary["wake_class_evidence"] = wake_class_ev
    wake_subject = bool(
        wake_us is not None or wkp_min_us is not None or wake_class_ev)
    classifier_subject = bool(
        bit0_min_us is not None or bit0_max_us is not None
        or wkp_min_us is not None)
    summary["spec_mandates_wake"] = bool(wake_subject or classifier_subject)

    # --- Waiver short-circuits ---
    waiver_alt = _waiver_rationale(
        project, "wake_pulse_alternative_implementation")
    waiver_skip = _waiver_rationale(
        project, "wake_pulse_width_skipped_intentional", min_chars=40)
    waiver_mode_override = _waiver_rationale(
        project, "wake_pulse_classifier_mode_override", min_chars=40)
    if waiver_mode_override:
        summary.setdefault("warnings", []).append(
            "value-based wake-pulse mode-override waived: "
            f"{waiver_mode_override[:80]}")
    if waiver_alt and waiver_skip:
        summary["skipped_reason"] = (
            "waivers wake_pulse_alternative_implementation + "
            "wake_pulse_width_skipped_intentional present")
        return findings, summary

    # --- Structural branch (preserved) ---
    rtl_files = find_rtl_files(project)
    if rtl_files and wake_subject and not waiver_alt:
        summary["examined"]["structural"] = True
        impl, rtl_evidence = _rtl_implements_wake(rtl_files)
        summary["rtl_implements_wake"] = impl
        summary["rtl_evidence"] = rtl_evidence
        if not impl:
            findings.append(Finding(
                severity="ERROR",
                rule="WAKE_PULSE_NOT_IMPLEMENTED",
                message=(
                    "L2 / L8 spec mandates a wake pulse but no RTL "
                    "file implements it. Expected: an FSM state "
                    "(e.g. `S_WAKE`), a dedicated wake-drive signal "
                    "(e.g. `wake_drv`), or both `TITO_TICKS` + "
                    "`TWK_PULSE` counters in a sequential block "
                    "driving the bus low."
                ),
            ))

    # --- Value-based branch (Wave 9 + Wave 10 WKP mode) ---
    if waiver_skip:
        summary.setdefault("warnings", []).append(
            "value-based wake-pulse check waived: "
            f"{waiver_skip[:80]}")
    elif waiver_mode_override:
        # Mode-override waiver silences the value branch entirely
        # for protocols where neither WKP nor BIT0 mode applies.
        pass
    elif wkp_mode:
        # ============================================================
        # WKP mode — host has a SEPARATE wake-pulse classifier symbol
        # whose minimum is strictly greater than BIT0 LOW-max. Wake
        # pulse must be ≥ wkp_min; the BIT0 upper-edge check no
        # longer applies (pulses inside the BIT0 window would be
        # classified as BIT0 by the host, NOT as a wake event).
        # ============================================================
        summary["examined"]["value"] = True
        if wake_us is None:
            findings.append(Finding(
                severity="ERROR",
                rule="WAKE_PULSE_WIDTH_UNRESOLVED",
                message=(
                    "WKP mode: host wkp_min resolved "
                    f"({wkp_min_us:.3f} µs, > "
                    f"bit0_low_max_us={bit0_max_us:.3f}) but the "
                    "chip's wake-pulse width is not declared in any "
                    "L doc. Searched synonyms: "
                    f"{list(_WAKE_US_KEYS) + list(_WAKE_TICK_KEYS)}."
                ),
            ))
        else:
            ratio = wake_us / wkp_min_us if wkp_min_us > 0 else float("inf")
            if wake_us < wkp_min_us:
                findings.append(Finding(
                    severity="ERROR",
                    rule="WAKE_PULSE_BELOW_WKP_MIN",
                    message=(
                        f"FAIL — WKP mode: wake_pulse_us="
                        f"{wake_us:.3f} < wkp_min_us="
                        f"{wkp_min_us:.3f} "
                        f"(ratio={ratio:.2f}). Host has a dedicated "
                        "WKP classifier (wkp_min > bit0_low_max), so "
                        "wake pulse must be ≥ wkp_min_us. Below this "
                        "threshold the host's RX classifier will read "
                        "the pulse as BIT0 / noise and never emit a "
                        "wake event — connect_test reports 'DUT "
                        "silent'. Increase the wake-pulse counter so "
                        "the LOW window is at least "
                        f"{wkp_min_us:.3f} µs (target wkp_min_us)."
                    ),
                ))
            elif wkp_min_us <= 0:
                # A declared floor of zero is degenerate, not a verdict:
                # every width clears it and no relative margin exists.
                # Guarded because the margin below divided by it — an
                # uncaught ZeroDivisionError, i.e. a crash where a verdict
                # was owed. Reported as a WARN so the degenerate spec is
                # visible; the comparison above still stands.
                summary["warnings"].append(
                    f"wkp_min_us={wkp_min_us:.3f} is not positive; no "
                    "relative PVT margin can be computed against it. "
                    "Fix the declared WKP classifier minimum in the L docs."
                )
            else:
                margin = (wake_us - wkp_min_us) / wkp_min_us
                if margin < 0.20:
                    summary["warnings"].append(
                        f"PASS — WKP mode: wake_pulse_us="
                        f"{wake_us:.3f} ≥ wkp_min_us="
                        f"{wkp_min_us:.3f} but only "
                        f"+{margin * 100:.1f}% margin; consider "
                        "widening for PVT margin (≥20%)."
                    )
    else:
        # ============================================================
        # BIT0 mode — host classifier window is the BIT0 LOW window.
        # Wake pulse must be inside [bit0_low_min, bit0_low_max].
        # This is the historic Wave-9 behaviour, preserved for
        # protocols without a separate WKP symbol class.
        # ============================================================
        if wake_us is None and bit0_min_us is None:
            # NEITHER number is in hand. Whether that is a DESIGN DEFECT or
            # simply "this gate has no subject here" is decided by the
            # applicability evidence, not by the absence itself:
            #
            #   wake_subject or classifier_subject  -> the project DOES
            #       declare a wake pulse / classifier somewhere structured,
            #       but the numbers this gate needs are missing. A real
            #       finding about a real design. ERROR, as Wave 9 intended.
            #
            #   neither                             -> the gate examined
            #       nothing. Wave 9 made this an ERROR to stop it being a
            #       silent SKIP, and that was the right instinct aimed at
            #       the wrong tier: MEASURED, it fires on 99 of the 117
            #       corpus projects, none of which is a wake-pulse design.
            #       The plugin already has the tier this belongs in —
            #       VACUOUS (rc 2), which the umbrella records as a NAMED
            #       skip and which `_vacuous_exit` refuses to render as a
            #       plain PASS. That is strictly stronger than the rc-0
            #       PASS these projects were credited with before, so the
            #       Wave-9 concern is honoured, not reverted.
            if wake_subject or classifier_subject:
                summary["examined"]["value"] = True
                findings.append(Finding(
                    severity="ERROR",
                    rule="WAKE_PULSE_VALUES_UNRESOLVED",
                    message=(
                        "Could not resolve EITHER wake-pulse width OR "
                        "host BIT0 LOW-min from L2/L8 docs, although the "
                        "spec declares a wake pulse / classifier "
                        f"({'; '.join(wake_class_ev) or 'value evidence'}"
                        "). Searched synonyms include "
                        f"{list(_WAKE_US_KEYS)[:4]}... and "
                        f"{list(_BIT0_US_KEYS)[:4]}.... Add one of these "
                        "fields to the relevant L doc, OR ship a "
                        "`wake_pulse_width_skipped_intentional` waiver "
                        "(rationale ≥40 chars) to suppress this gate "
                        "for protocols without a host BIT0 classifier."
                    ),
                ))
            else:
                summary["skipped_reason"] = (
                    "no wake-pulse width, no host classifier window and no "
                    "declared WAKE symbol class in any L doc — this gate "
                    "has no subject in this project. Searched synonyms: "
                    f"{list(_WAKE_US_KEYS)[:4]}... / "
                    f"{list(_BIT0_US_KEYS)[:4]}...")
        elif wake_us is None:
            summary["examined"]["value"] = True
            findings.append(Finding(
                severity="ERROR",
                rule="WAKE_PULSE_WIDTH_UNRESOLVED",
                message=(
                    "BIT0 mode: host BIT0 LOW-min resolved "
                    f"({bit0_min_us:.3f} µs) but the chip's wake-"
                    "pulse width is not declared in any L doc. "
                    "Searched synonyms: "
                    f"{list(_WAKE_US_KEYS) + list(_WAKE_TICK_KEYS)}."
                ),
            ))
        elif bit0_min_us is None:
            # WARN only — protocol may legitimately have no host
            # classifier (e.g. async). Surface it for the user.
            summary["warnings"].append(
                f"wake_pulse_us={wake_us:.3f} resolved but no host "
                "BIT0 classifier window found; cannot value-check. "
                "Ship a `wake_pulse_width_skipped_intentional` "
                "waiver if intentional."
            )
        else:
            # Both numbers in hand — compare.
            summary["examined"]["value"] = True
            ratio_low = wake_us / bit0_min_us if bit0_min_us > 0 else float("inf")
            if wake_us < bit0_min_us:
                findings.append(Finding(
                    severity="ERROR",
                    rule="WAKE_PULSE_BELOW_BIT0_MIN",
                    message=(
                        f"FAIL — BIT0 mode: wake_pulse_us="
                        f"{wake_us:.3f} < bit0_low_min_us="
                        f"{bit0_min_us:.3f} "
                        f"(ratio={ratio_low:.2f}). The host RX will "
                        "classify the chip's wake pulse as BIT1 / "
                        "noise and report 'DUT silent'. Increase the "
                        "wake-pulse counter so the LOW window is at "
                        f"least {bit0_min_us:.3f} µs (≥1.0× "
                        "bit0_low_min_us)."
                    ),
                ))
            else:
                # PASS — but flag boundary risk.
                if bit0_min_us <= 0:
                    # `wake_us >= bit0_min_us` is trivially true against a
                    # floor of zero, and the relative margin below divided
                    # by it: an uncaught ZeroDivisionError on
                    # `bit0_low_min_us == 0`, i.e. a CRASH where a verdict
                    # was owed. Guarded here; the crash and the unreachable
                    # verdict are separate defects and this fixes only the
                    # crash — the comparison's outcome is unchanged.
                    summary["warnings"].append(
                        f"bit0_low_min_us={bit0_min_us:.3f} is not "
                        "positive; every wake-pulse width clears it and no "
                        "relative PVT margin can be computed against it. "
                        "Fix the declared BIT0 LOW-min in the L docs."
                    )
                else:
                    margin_low = (wake_us - bit0_min_us) / bit0_min_us
                    if margin_low < 0.20:
                        summary["warnings"].append(
                            f"wake_pulse_us={wake_us:.3f} is within "
                            f"+{margin_low * 100:.1f}% of "
                            f"bit0_low_min_us={bit0_min_us:.3f}; "
                            "consider widening for PVT margin (≥20%)."
                        )
                if bit0_max_us is not None:
                    if wake_us > bit0_max_us:
                        # Over the upper edge — also a misclassify.
                        findings.append(Finding(
                            severity="ERROR",
                            rule="WAKE_PULSE_ABOVE_BIT0_MAX",
                            message=(
                                f"FAIL — BIT0 mode: wake_pulse_us="
                                f"{wake_us:.3f} > bit0_low_max_us="
                                f"{bit0_max_us:.3f}. Pulse exceeds "
                                "the BIT0 LOW window and will be "
                                "classified as a longer frame "
                                "symbol. Reduce wake pulse to "
                                f"≤{bit0_max_us:.3f} µs."
                            ),
                        ))
                    elif bit0_max_us <= 0:
                        # Same guard, upper edge.
                        summary["warnings"].append(
                            f"bit0_low_max_us={bit0_max_us:.3f} is not "
                            "positive; no relative PVT margin can be "
                            "computed against it. Fix the declared BIT0 "
                            "LOW-max in the L docs."
                        )
                    else:
                        margin_hi = (bit0_max_us - wake_us) / bit0_max_us
                        if margin_hi < 0.20:
                            summary["warnings"].append(
                                f"wake_pulse_us={wake_us:.3f} is "
                                f"within {margin_hi * 100:.1f}% of "
                                f"bit0_low_max_us={bit0_max_us:.3f}; "
                                "consider tightening for PVT margin."
                            )

    # ---- the gate's OWN statement of what it examined ------------------
    #
    # `skipped` is DERIVED from `examined`, never authored twice: a branch
    # that looked at something sets its own flag as it runs, and nothing
    # can announce a skip it did not take. This is the field `main` routes
    # the exit code from, so "printed a verdict" and "exited with a code"
    # come from one place.
    #
    # A WAIVER IS NOT A VACUUM, and is deliberately excluded here. Waived
    # projects keep the rc-0 they have always had: a waiver is an authored,
    # reviewable statement (the value-branch one demands ≥40 chars of
    # rationale) that the gate does not apply, which is a judgement someone
    # made — not a run that read nothing. `_vacuous_exit.verdict_line` makes
    # the same distinction in its own docstring.
    _waived_any = bool(waiver_skip or waiver_mode_override or waiver_alt)
    if not _waived_any and not (
            summary["examined"]["structural"] or summary["examined"]["value"]):
        summary["skipped"] = True
        if not summary["reason"]:
            summary["reason"] = "no_wake_pulse_subject_in_l_docs"
        if not summary["skipped_reason"]:
            summary["skipped_reason"] = (
                "nothing to examine: the L docs declare no wake-pulse "
                "width and no host classifier window, and no RTL was "
                "checked for a wake-pulse implementation.")

    return findings, summary


def main() -> int:
    ap = argparse.ArgumentParser(prog="wake_pulse_implementation_check")
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    ap.add_argument(
        "--strict", action="store_true",
        help=("DEPRECATED and IGNORED. The exit code is routed from the "
              "gate's own conclusion (see _vacuous_exit), so an ERROR "
              "finding is rc 1 whether or not this flag is passed. It used "
              "to be the ONLY way to reach rc 1, and the P0 structural "
              "umbrella — the only production caller — never supplied it, "
              "which made every FAIL verdict unreachable in production. "
              "Still accepted so existing command lines keep working."))
    args = ap.parse_args()

    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"[error] project not found: {project}", file=sys.stderr)
        return 2
    findings, summary = inspect(project)
    has_error = any(f.severity == "ERROR" for f in findings)
    passed = not has_error
    # FAIL beats VACUOUS: a gate cannot both have found a violation and have
    # examined nothing. `_vacuous_exit.exit_code` enforces that ordering, and
    # is the single site the rc comes from.
    skipped = _vx.summary_is_skipped(summary) and passed
    rc = _vx.exit_code(passed, skipped)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps({
            "program": "wake_pulse_implementation_check",
            "passed": passed,
            "skipped": skipped,
            "exit_code": rc,
            "summary": summary,
            "findings": [f.__dict__ for f in findings],
        }, indent=2))

    print(f"=== wake_pulse_implementation_check ({project.name}) ===")
    if summary.get("skipped_reason"):
        print(f"skipped: {summary['skipped_reason']}")
        if skipped:
            # rc 2 alone is a number; the sentinel is the second,
            # rc-INDEPENDENT disclosure channel, and it says in words that
            # this is NOT a pass over the design. Written to stderr by
            # `_vacuous_exit` so the stdout report stays parseable.
            _vx.announce_vacuous("wake_pulse_implementation_check",
                                 _vx.skip_reason(summary))
        return rc
    if summary.get("clock_ns") is not None:
        print(f"clock: {summary['clock_ns']:.2f} ns "
              f"({summary['clock_evidence'] or 'defaulted'})")
    print(f"wake_pulse_us: {summary['wake_pulse_us']} "
          f"({summary['wake_pulse_evidence']})")
    print(f"bit0_low_min_us: {summary['bit0_low_min_us']} "
          f"({summary['bit0_low_min_evidence']})")
    if summary.get("bit0_low_max_us") is not None:
        print(f"bit0_low_max_us: {summary['bit0_low_max_us']} "
              f"({summary['bit0_low_max_evidence']})")
    if summary.get("wkp_min_us") is not None:
        print(f"wkp_min_us: {summary['wkp_min_us']} "
              f"({summary['wkp_min_evidence']})")
    if summary.get("classifier_mode"):
        print(f"classifier_mode: {summary['classifier_mode']}")
    for w in summary.get("warnings", []):
        print(f"[WARN] {w}")
    for f in findings:
        print(f"[{f.severity}] {f.rule}: {f.message}")
    if not findings:
        mode = summary.get("classifier_mode")
        wp = summary.get("wake_pulse_us")
        if mode == "WKP" and wp is not None and summary.get("wkp_min_us") is not None:
            print(f"PASS — WKP mode: wake_pulse_us={wp:.3f} ≥ "
                  f"wkp_min_us={summary['wkp_min_us']:.3f}")
        elif mode == "BIT0" and wp is not None and summary.get("bit0_low_min_us") is not None:
            lo = summary["bit0_low_min_us"]
            hi = summary.get("bit0_low_max_us")
            if hi is not None:
                print(f"PASS — BIT0 mode: wake_pulse_us={wp:.3f} ∈ "
                      f"[{lo:.3f}, {hi:.3f}]")
            else:
                print(f"PASS — BIT0 mode: wake_pulse_us={wp:.3f} ≥ "
                      f"bit0_low_min_us={lo:.3f}")
        else:
            print("PASS — wake pulse value-checked vs host classifier")
        if skipped:
            _vx.announce_vacuous("wake_pulse_implementation_check",
                                 _vx.skip_reason(summary))
        return rc
    return rc


if __name__ == "__main__":
    sys.exit(main())
