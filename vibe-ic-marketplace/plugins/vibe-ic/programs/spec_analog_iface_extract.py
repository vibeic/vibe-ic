#!/usr/bin/env python3
"""spec_analog_iface_extract.py — PROGRAM-FIRST structural extractor for the L5
ANALOG/DIGITAL INTERFACE (ADI) facet of a design doc / prompt (chip-AGNOSTIC,
§4.05 no-leak).

WHY THIS EXISTS
---------------
A design that crosses the analog<->digital boundary states that boundary
EXPLICITLY: a data converter (an N-bit ADC / DAC, an M-channel mux, a sample
rate), a reference voltage (a Vref value or a named Vref pin), and the analog
pads / front-end signals that carry the analog quantity in or out of the chip.
The hidden scoring testbench — and the silicon — exercise exactly those stated
converter widths, reference levels, and analog pins, so a missed ADI fact is,
per the spec-coverage doctrine, one of OUR OWN extraction gaps, not a floor.

The COARSE prose-heuristic checklists elsewhere answer "is the word `ADC`
MENTIONED?". They do NOT record the STRUCTURE the author must implement: the
converter's RESOLUTION / CHANNEL-COUNT / SAMPLE-RATE, the reference VALUE or
named pin, or the specific analog SIGNAL/PAD. This module is that structural
extension: it reads the explicit number+unit grammar and the named-signal /
named-pad anchors and emits one richer item per stated ADI fact.

WHAT COUNTS (the §4.05 no-leak boundary)
----------------------------------------
Every emitted item is anchored to an EXPLICIT token PLUS a structural qualifier
in the prose. There is NO bare-keyword emission:

  * kind="analog_converter" — an ADC or DAC token AND a structural qualifier:
        an N-bit RESOLUTION, an N-CHANNEL count, OR a SAMPLE RATE (S/s, SPS,
        MSPS, Hz sampling). "12-bit ADC", "8-channel ADC", "1 MSPS DAC" qualify.
        A bare "ADC" with no resolution/channel/rate yields NOTHING.

  * kind="reference_voltage" — a Vref / V_REF / VREF / "reference voltage" token
        AND a qualifier: a VALUE (1.2 V, 2.5V, 800 mV) OR a named pin (a
        backtick/explicit signal name). A bare "voltage" yields NOTHING.

  * kind="analog_pad" — an analog input / output / pin / pad / sense pad / bias
        pin / PHY-analog / analog-front-end token tied to a named SIGNAL or an
        explicit PAD. A bare "analog" alone yields NOTHING.

`extract("design a digital filter")` returns `[]`. chip-AGNOSTIC: pure analog
vocabulary + structural number/unit grammar; NO chip / vendor / SKU / problem-id
literal (enforced by `programs/source_chip_agnostic_check.py .`).

CONTRACT
--------
    def extract(prompt_text: str) -> List[dict]
Each emitted dict has keys:
    {
      "kind":            "analog_converter" | "reference_voltage" | "analog_pad",
      "requirement":     human-readable testable requirement,
      "evidence":        the EXACT prose fragment it came from,
      "coverage_tokens": [tokens a TB / reviewer must touch to cover it],
      "provenance":      "STRUCTURAL"  (default),
      "block_eligible":  True,
      # plus kind-specific structured fields (e.g. converter/resolution/...).
    }

CLI
    python3 spec_analog_iface_extract.py <prompt.txt> [--json]
    cat prompt.txt | python3 spec_analog_iface_extract.py -
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Dict, List, Optional, Tuple


# ===========================================================================
# (1) ANALOG DATA CONVERTER (ADC / DAC) + structural qualifier
# ===========================================================================
# The converter TOKEN: ADC / DAC and their spelled-out forms. chip-AGNOSTIC —
# generic data-converter vocabulary, no design literal. We capture the kind so
# the requirement can name "ADC" vs "DAC".
_CONVERTER_TOKEN_RE = re.compile(
    r"\b(ADC|DAC|analog[ \-]?to[ \-]?digital(?:\s+converter)?|"
    r"digital[ \-]?to[ \-]?analog(?:\s+converter)?|"
    # named converter ARCHITECTURES — each is an ADC/DAC by definition, so a
    # datasheet that names the topology (without the literal "ADC") still states a
    # converter. chip-AGNOSTIC (generic data-converter vocabulary).
    r"delta[ \-–]?sigma|sigma[ \-–]?delta|SAR|successive[ \-]?approximation|"
    r"pipelined?(?:\s+(?:ADC|converter))?|dual[ \-]?slope|incremental(?:\s+"
    r"(?:delta[ \-–]?sigma|converter|ADC))?|delta[ \-–]?sigma\s+modulator)\b",
    re.IGNORECASE)

# RESOLUTION qualifier: "12-bit", "12 bit", "12bit" — an N-bit width. A
# resolution is a small-to-moderate positive integer; we keep 1..512 to admit
# real converter widths while rejecting an accidental huge token. §4.05: only a
# stated N-bit number qualifies a converter.
_RESOLUTION_RE = re.compile(r"\b(\d{1,4})[ \-]?bit\b", re.IGNORECASE)

# CHANNEL-COUNT qualifier: "8-channel", "8 channels", "8 ch", and the datasheet
# array form "6 … modulator channels" / "6 identical … copies" where descriptive
# words sit between the count and the noun. Bounded non-greedy gap (no clause
# terminator) keeps it within one converter clause; the converter-clause gate in
# _detect_converters prevents a stray count elsewhere from minting a converter.
_CHANNEL_RE = re.compile(
    r"\b(\d{1,4})\b[^.;\n|]{0,40}?\b(?:channels?|copies|ch)\b", re.IGNORECASE)

# SAMPLE-RATE qualifier: "1 MSPS", "500 kSPS", "2 GS/s", "1 MS/s", "100 kHz
# sampling", "sampling rate of 1 MHz", "samples at 1 MHz". The unit makes it a
# rate (vs a plain frequency). chip-AGNOSTIC.
_SAMPLE_RATE_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*"
    r"(?:([kKmMgG])?(?:SPS|S/s|Sa/s|samples?\s*(?:per|/)\s*s(?:econd)?)"     # rate units
    r"|([kKmMgG])?Hz\s*(?:sampl\w*|sample\s+rate)"                          # "100 kHz sampling"
    r")", re.IGNORECASE)
# A "sampling/sample rate of <N> <unit>Hz" / "samples at <N> <unit>Hz" form
# (the rate word precedes the frequency). chip-AGNOSTIC.
_SAMPLE_RATE_PRE_RE = re.compile(
    r"\b(?:sampl\w*\s+(?:rate|frequency)\s+of|samples?\s+at|"
    r"sample\s+rate\s*[:=]?)\s*"
    r"(\d+(?:\.\d+)?)\s*([kKmMgG])?Hz\b", re.IGNORECASE)


# A clause-terminating "." is a sentence period (followed by whitespace / EOL),
# NOT a decimal point inside a number ("2.5 V") — so a value never gets split
# away from its token. We split on sentence-ending . / ; / newline / list dashes.
# A clause-terminating "." must not be a decimal point (`2.5 V`) NOR part of a
# `..` / `...` RANGE-or-ellipsis (`IN1..IN6`, a common pin-range datasheet form) —
# splitting inside the range would sever the analog token from its pad names.
_CLAUSE_SPLIT_RE = re.compile(r"(?<!\d)(?<!\.)\.(?!\d)(?!\.)|[;\n]|\s-\s|•|·|—")


def _clauses(text: str) -> List[str]:
    """Split into clauses on sentence / list / line boundaries so a qualifier is
    matched in the SAME local context as its token (a no-leak guard: a `12-bit`
    two paragraphs away must not qualify a bare `ADC`). A "." between two digits
    is a decimal point, not a clause boundary (keeps "2.5 V" intact)."""
    return [c for c in _CLAUSE_SPLIT_RE.split(text) if c and c.strip()]


def _converter_kind(tok: str) -> str:
    """Normalize a converter token to 'ADC' or 'DAC'. chip-AGNOSTIC."""
    t = tok.upper()
    if t.startswith("ADC") or "ANALOG" in t and "DIGITAL" in t \
            and t.index("ANALOG") < t.index("DIGITAL"):
        return "ADC"
    if t.startswith("DAC") or ("DIGITAL" in t and "ANALOG" in t):
        return "DAC"
    return "ADC"


def _norm_rate(num: str, mult: str) -> str:
    """Human-readable sample-rate string, e.g. ('1','M') -> '1 MSPS'."""
    mult = (mult or "").upper()
    return f"{num} {mult}SPS" if mult else f"{num} SPS"


def _detect_converters(text: str) -> List[Dict[str, object]]:
    """Return one structured converter dict per clause that has BOTH a converter
    token AND at least one structural qualifier (resolution / channels / rate).
    §4.05: a converter token with no qualifier yields nothing."""
    out: List[Dict[str, object]] = []
    seen: set = set()
    for clause in _clauses(text):
        cm = _CONVERTER_TOKEN_RE.search(clause)
        if not cm:
            continue
        kind = _converter_kind(cm.group(0))

        resolution: Optional[int] = None
        rm = _RESOLUTION_RE.search(clause)
        if rm:
            try:
                resolution = int(rm.group(1))
            except ValueError:
                resolution = None

        channels: Optional[int] = None
        chm = _CHANNEL_RE.search(clause)
        if chm:
            try:
                channels = int(chm.group(1))
            except ValueError:
                channels = None

        rate: Optional[str] = None
        sm = _SAMPLE_RATE_RE.search(clause)
        if sm:
            rate = _norm_rate(sm.group(1), sm.group(2) or sm.group(3) or "")
        else:
            sp = _SAMPLE_RATE_PRE_RE.search(clause)
            if sp:
                mult = (sp.group(2) or "").upper()
                rate = f"{sp.group(1)} {mult}Hz sampling".replace("  ", " ")

        # §4.05 HARD GATE: at least ONE structural qualifier must be present.
        if resolution is None and channels is None and rate is None:
            continue

        key = (kind, resolution, channels, rate)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "kind": kind,
            "resolution": resolution,
            "channels": channels,
            "rate": rate,
            "evidence": clause.strip()[:140],
        })
    return out


# ===========================================================================
# (2) REFERENCE VOLTAGE (Vref) + value or named pin
# ===========================================================================
# The reference TOKEN: Vref / V_REF / VREF / "reference voltage" / "bandgap"
# (a bandgap IS a voltage reference). chip-AGNOSTIC.
_VREF_TOKEN_RE = re.compile(
    r"\b(V[_ ]?REF\w*|reference\s+voltage|band[\s-]?gap(?:\s+reference)?)\b",
    re.IGNORECASE)
# unit-only volt cell for a markdown reference-table row (`| Vref | 2.048 | … | V |`)
_CELL_VOLT_ONLY_RE = re.compile(r"^(mV|V|volts?)$", re.IGNORECASE)
_CELL_NUM_ONLY_RE = re.compile(r"^[±+-]?\s*(\d+(?:\.\d+)?)$")

# A VOLTAGE VALUE qualifier: "1.2 V", "2.5V", "800 mV", "1.8 volts". The unit
# (V / mV / volts) makes it a voltage; a bare number does not qualify.
_VOLTAGE_VALUE_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(mV|millivolts?|V|volts?)\b")

# A NAMED PIN qualifier: a backtick-quoted signal name (`vref_pin`) OR an
# explicit "pin/pad/signal/port named/called <name>" / "<name> pin". The pin
# name is a generic identifier — chip-AGNOSTIC (no literal hard-coded). We
# require the reference token to be in the same clause (see _detect_vref).
_BACKTICK_NAME_RE = re.compile(r"`([A-Za-z_]\w*)`")
_NAMED_PIN_RE = re.compile(
    r"\b(?:pin|pad|signal|port)\s+(?:named|called|labell?ed\s+)?"
    r"`?([A-Za-z_]\w*)`?"                       # "pin named X" / "pin X"
    r"|`?([A-Za-z_]\w*)`?\s+(?:pin|pad)\b",     # "X pin"
    re.IGNORECASE)


def _detect_vref(text: str) -> List[Dict[str, object]]:
    """Return one structured reference dict per clause that has BOTH a Vref token
    AND a qualifier (a voltage value OR a named pin). §4.05: a bare "voltage"
    yields nothing; a bare "Vref" with no value/pin yields nothing."""
    out: List[Dict[str, object]] = []
    seen: set = set()
    for clause in _clauses(text):
        vm = _VREF_TOKEN_RE.search(clause)
        if not vm:
            continue

        value: Optional[str] = None
        val_m = _VOLTAGE_VALUE_RE.search(clause)
        if val_m:
            unit = val_m.group(2)
            value = f"{val_m.group(1)} {unit}".strip()

        pin: Optional[str] = None
        # Prefer a backtick-quoted name (most explicit), else a "pin/pad" anchor.
        # The reference token text itself (e.g. "VREF") must NOT be mistaken for
        # the pin name, so we skip a backtick/pin name equal to the token.
        tok_low = re.sub(r"[ _]", "", vm.group(0).lower())
        bt = _BACKTICK_NAME_RE.search(clause)
        if bt and re.sub(r"[ _]", "", bt.group(1).lower()) != tok_low:
            pin = bt.group(1)
        if pin is None:
            pm = _NAMED_PIN_RE.search(clause)
            if pm:
                cand = pm.group(1) or pm.group(2)
                if cand and re.sub(r"[ _]", "", cand.lower()) != tok_low:
                    pin = cand

        # §4.05 HARD GATE: require a VALUE or a NAMED PIN.
        if value is None and pin is None:
            continue

        key = (value, pin)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "value": value,
            "pin": pin,
            "evidence": clause.strip()[:140],
        })

    # MARKDOWN reference-table row: `| Vref (internal) | 2.048 | — | V |` — the
    # value and the unit live in SEPARATE cells, so the clause/prose value pass
    # above misses them. A row whose NAME cell carries a Vref token + a numeric
    # cell + a volt-unit cell is a stated reference voltage. §4.05: requires all
    # three (ref-name + number + unit).
    for line in text.splitlines():
        if line.count("|") < 2:
            continue
        cells = [c.strip().strip("`* ") for c in line.strip().strip("|").split("|")]
        name = cells[0] if cells else ""
        if not _VREF_TOKEN_RE.search(name):
            continue
        num = next((m.group(1) for c in cells
                    for m in [_CELL_NUM_ONLY_RE.match(c)] if m), None)
        has_v = any(_CELL_VOLT_ONLY_RE.match(c) for c in cells)
        if num is None or not has_v:
            continue
        value = num + " V"
        if (value, None) in seen:
            continue
        seen.add((value, None))
        out.append({"value": value, "pin": None, "evidence": line.strip()[:140]})
    return out


# ===========================================================================
# (3) ANALOG PAD / FRONT-END + named signal or explicit pad
# ===========================================================================
# The analog-pad TOKEN family: an explicit analog input/output/pin/pad, a sense
# pad, a bias pin, a PHY-analog, or an analog front-end. chip-AGNOSTIC — generic
# analog-boundary vocabulary. A BARE "analog" (no input/output/pin/pad/front-end
# qualifier) is NOT in this set, so it cannot fire alone.
# Trailing `s?` on the boundary nouns so the PLURAL datasheet form ("Analog
# inputs IN1..IN6", "sense pads") fires as well as the singular. chip-AGNOSTIC.
_ANALOG_PAD_TOKEN_RE = re.compile(
    r"\b(analog\s+inputs?|analog\s+outputs?|analog\s+pins?|analog\s+pads?|"
    r"analog\s+front[ \-]?ends?|sense\s+pads?|bias\s+pins?|PHY\s+analog|"
    r"analog\s+I/O|analog\s+io)\b", re.IGNORECASE)

# A NAMED SIGNAL / PAD anchor near the analog token. Either a backtick-quoted
# name, or a "pin/pad/signal/port named|called <name>" / "<name> pin|pad" form.
# chip-AGNOSTIC (the name is a generic identifier, not a literal).
# Three independent forms for a named analog signal/pad. Searched as SEPARATE
# passes (not one alternation) so an "<deny-word> pin" hit — e.g. "input pin" —
# does not consume the "pin <name>" that follows it ("pin ain"). chip-AGNOSTIC.
# A backtick pad name, allowing a RANGE inside one pair (`AIN0..AIN3`): capture
# the leading identifier (AIN0) even when a `..hi` range follows before the close.
_PAD_BACKTICK_RE = re.compile(r"`([A-Za-z_]\w*)(?:\.\.[A-Za-z0-9_]+)?`")
_PAD_PIN_THEN_NAME_RE = re.compile(
    r"\b(?:pin|pad|signal|port)\s+(?:named|called|labell?ed\s+)?"
    r"`?([A-Za-z_]\w*)`?", re.IGNORECASE)                # "pin [named] X"
_PAD_NAME_THEN_PIN_RE = re.compile(
    r"\b([A-Za-z_]\w*)\s+(?:pin|pad)\b", re.IGNORECASE)  # "X pin"

# Generic words that, if captured as the "named signal", are NOT real signal
# names — they are the analog vocabulary itself. chip-AGNOSTIC deny-set so e.g.
# "analog input pin" does not mint a signal called "input". Kept lower-case.
_PAD_NON_SIGNAL_WORDS = {
    "analog", "input", "output", "pin", "pad", "signal", "port", "sense",
    "bias", "phy", "front", "end", "the", "a", "an", "io",
}


def _detect_analog_pads(text: str) -> List[Dict[str, object]]:
    """Return one structured pad dict per clause that has BOTH an analog-pad
    token AND a named signal / explicit pad. §4.05: a bare "analog" yields
    nothing; an analog-pad token with no named signal/pad yields nothing."""
    out: List[Dict[str, object]] = []
    seen: set = set()
    for clause in _clauses(text):
        am = _ANALOG_PAD_TOKEN_RE.search(clause)
        if not am:
            continue
        token = re.sub(r"\s+", " ", am.group(0).strip())

        # Gather EVERY candidate name (each alternation arm can match a different
        # token); the FIRST that is not an analog-vocabulary deny-word is the real
        # signal. We scan per-arm so an "<deny> pin" hit (e.g. "input pin") does
        # not swallow the following "pin <name>" hit ("pin ain").
        signal: Optional[str] = None
        cands: List[Tuple[int, str]] = []
        for rx in (_PAD_BACKTICK_RE, _PAD_PIN_THEN_NAME_RE,
                   _PAD_NAME_THEN_PIN_RE):
            for sm in rx.finditer(clause):
                cands.append((sm.start(), sm.group(1)))
        for _, cand in sorted(cands):
            if not cand or cand.lower() in _PAD_NON_SIGNAL_WORDS:
                continue
            signal = cand
            break

        # §4.05 HARD GATE: require a named signal / explicit pad name.
        if signal is None:
            continue

        key = (token.lower(), signal.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "token": token,
            "signal": signal,
            "evidence": clause.strip()[:140],
        })
    return out


# ===========================================================================
# Public API
# ===========================================================================
def extract(prompt_text: str) -> List[dict]:
    """Extract the stated ANALOG/DIGITAL INTERFACE facets from `prompt_text`.

    Returns a list of dicts, one per EXPLICIT ADI fact, of kinds:
        analog_converter | reference_voltage | analog_pad

    §4.05 no-leak: every item is anchored to an explicit token PLUS a structural
    qualifier (resolution/channels/rate for a converter; value/named-pin for a
    reference; named-signal/pad for an analog pad). A prompt with no such anchor
    returns []. chip-AGNOSTIC: pure analog vocabulary + number/unit grammar,
    never a problem id."""
    if not prompt_text or not isinstance(prompt_text, str) \
            or not prompt_text.strip():
        return []

    text = prompt_text
    items: List[dict] = []

    # --- (1) Analog data converters (ADC / DAC) ---
    for c in _detect_converters(text):
        kind = c["kind"]
        quals: List[str] = []
        tokens: List[str] = [str(kind).lower()]
        if c["resolution"] is not None:
            quals.append(f"{c['resolution']}-bit resolution")
            tokens.append(str(c["resolution"]))
        if c["channels"] is not None:
            quals.append(f"{c['channels']} channel(s)")
            tokens.append(str(c["channels"]))
        if c["rate"]:
            quals.append(f"sample rate {c['rate']}")
            tokens.append(str(c["rate"]).split()[0])
        req = (f"{kind} converter with " + ", ".join(quals)
               + "; the design must implement it and the TB / silicon must "
               + "exercise the stated converter interface.")
        items.append({
            "kind": "analog_converter",
            "requirement": req,
            "evidence": c["evidence"],
            "coverage_tokens": tokens,
            "converter": str(kind),
            "resolution": c["resolution"],
            "channels": c["channels"],
            "rate": c["rate"],
            "provenance": "STRUCTURAL",
            "block_eligible": True,
        })

    # --- (2) Reference voltage(s) ---
    for v in _detect_vref(text):
        quals = []
        tokens = ["vref"]
        if v["value"]:
            quals.append(f"value {v['value']}")
            tokens.append(str(v["value"]).split()[0])
        if v["pin"]:
            quals.append(f"pin {v['pin']}")
            tokens.append(str(v["pin"]))
        req = ("reference voltage (" + ", ".join(quals)
               + "); the design must provide / consume it and the TB must "
               + "drive the stated reference.")
        items.append({
            "kind": "reference_voltage",
            "requirement": req,
            "evidence": v["evidence"],
            "coverage_tokens": tokens,
            "value": v["value"],
            "pin": v["pin"],
            "provenance": "STRUCTURAL",
            "block_eligible": True,
        })

    # --- (3) Analog pads / front-end signals ---
    for p in _detect_analog_pads(text):
        req = (f"analog pad: {p['token']} on signal `{p['signal']}`; the design "
               + "must expose this analog boundary signal and the TB / silicon "
               + "must drive / observe it.")
        items.append({
            "kind": "analog_pad",
            "requirement": req,
            "evidence": p["evidence"],
            "coverage_tokens": [str(p["signal"]), str(p["token"]).split()[0].lower()],
            "pad_token": p["token"],
            "signal": p["signal"],
            "provenance": "STRUCTURAL",
            "block_eligible": True,
        })

    return items


# ===========================================================================
# CLI
# ===========================================================================
def _main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="PROGRAM-FIRST structural extractor for the L5 "
                    "analog/digital interface facet (converters / reference "
                    "voltage / analog pads). chip-AGNOSTIC, §4.05 no-leak.")
    ap.add_argument("prompt", help="prompt file ('-' for stdin)")
    ap.add_argument("--json", action="store_true",
                    help="emit the raw checklist-item list as JSON")
    args = ap.parse_args(argv)

    try:
        if args.prompt == "-":
            text = sys.stdin.read()
        else:
            with open(args.prompt, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
    except OSError as e:
        print("error: cannot read prompt: " + str(e), file=sys.stderr)
        return 2

    items = extract(text)
    if args.json:
        print(json.dumps(items, indent=2))
        return 0

    if not items:
        print("NO STATED ANALOG/DIGITAL INTERFACE (no converter+qualifier / "
              "Vref+value-or-pin / analog-pad+named-signal) -> [] (no "
              "fabrication)")
        return 0

    for it in items:
        print("- [" + it["kind"] + "] " + it["requirement"][:90])
        print("    evidence: " + it["evidence"][:100])
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
