#!/usr/bin/env python3
"""
internal_vs_external_timing_check.py — L8 must separate host-side from DUT-side timing.

Problem statement (chip-AGNOSTIC):
  Half-duplex single-wire protocols measure timing at TWO distinct places:
    - HOST->DUT (external): how long the HOST drives low to send symbols
                           (e.g. logic-0, logic-1, break) to the DUT.
    - DUT->HOST (internal): how long the DUT should drive low when
                           responding back to the HOST.
  These two sets of values are NOT equal. Tolerance windows differ, the
  inter-byte time (IBT) is almost always different, and the DUT-side
  values are what the RTL TX state machine must use to drive the bus.

Failure mode caught by this gate:
  When L8_TIMING_WAVEFORM lists only host-side measurements, the
  Phase 2 RTL generator is forced to pick ONE set of numbers and will
  reuse the host-side values on the DUT side. If the host IBT is larger
  than the BR (break) threshold the tester uses, the tester interprets
  every inter-byte gap as a packet-end BR and truncates every response
  to zero usable bytes. End result: connect_test fails on every cycle.

  A gold reference L8 (hardware-PASSed) has both sets:
    rx_counters_at_2p5MHz  : {H1_low [1,9], H0_low [10,30], BR_low [31,65]}
    tx_cycles_at_5MHz      : {H1_low 9, H1_high 41, H0_low 35, H0_high 15,
                              BR_low 69, BR_high 18, IBT_high 60}
  The bad L8 has only the equivalent of the FIRST set (host-side), so this
  gate would have flagged it at generation time.

Rule enforced
-------------
For any protocol layer that does BOTH RX and TX on a shared wire, the
L8_TIMING_WAVEFORM document MUST carry TWO clearly-named groups:
  - An "rx_*" / "host_side_*" / "external_*" group: host-drive widths
    the DUT's RX decoder must tolerate.
  - A "tx_*" / "dut_side_*" / "internal_*" group: widths the DUT's TX
    encoder drives on the wire.
Both groups must cover the same symbol set (H0, H1, BR, IBT minimum).

Additionally, the DUT-side IBT **must** be strictly less than the
RX-side BR minimum threshold (otherwise the far side — which uses the
same RX spec — will misclassify IBT as a packet-end BR, which is the
exact v068 failure mode).

Usage
-----
    internal_vs_external_timing_check.py <L8_TIMING_WAVEFORM.json>
        [--layer L8_RTL_CONSTANTS.json]
        [--json]

If L8_RTL_CONSTANTS is provided, the IBT<BR cross-check also runs
against its numeric values (after unit normalisation to μs).

Exit codes
----------
    0 = both timing groups present with required symbols; IBT < BR
    1 = group missing, symbol missing, or IBT≥BR inversion
    2 = IO / JSON parse error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _structural_absence as _sa   # noqa: E402  the class AND its enumeration

RX_NAME_HINTS = ("rx_", "host_", "external_", "host-side", "host_side",
                 "rx_counters", "detect_", "_tdt", "tHW", "tB_", "tDT",
                 "cmd_recv", "host_tx")
TX_NAME_HINTS = ("tx_", "dut_", "internal_", "dut-side", "dut_side",
                 "tx_cycles", "drive_", "_tdw", "TX_", "dut_tx",
                 "resp_emit", "cmd_resp", "wake_ack")
SYMBOLS_REQUIRED = ("H0", "H1", "BR", "IBT")


@dataclass
class Finding:
    severity: str          # "ERROR" | "WARN"
    rule: str
    field: str
    message: str


def _walk(obj: Any, path: str = ""):
    """Yield (path, value) for every leaf and every dict node."""
    if isinstance(obj, dict):
        yield path, obj
        for k, v in obj.items():
            yield from _walk(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        yield path, obj
    else:
        yield path, obj


def _classify_group(path_or_key: str) -> str | None:
    """Return 'rx' if path/key looks like host-side RX, 'tx' if DUT-side TX, else None."""
    s = path_or_key.lower()
    # Check tx first — "rx" substring may appear inside some tx keys
    for h in TX_NAME_HINTS:
        if h.lower() in s:
            return "tx"
    for h in RX_NAME_HINTS:
        if h.lower() in s:
            return "rx"
    return None


def _symbols_in(d: Any) -> set[str]:
    """Return the symbol set (H0, H1, BR, IBT) covered by a dict or list.

    IDENTIFIER TOKENS (`_identifier_tokens`), not substrings: "LIBRARY", "CALIBRATION"
    and "FABRIC" carry no BR and "CH0" no H0, which the substring reading
    counted as coverage (review of next/ictier1c). `break` is the spelled-out
    BR (`tB_break_us`).
    """
    def _syms(text: Any) -> set[str]:
        return {sym for t in _identifier_tokens(text)
                if (sym := _token_symbol(t)) is not None}

    out: set[str] = set()
    if isinstance(d, dict):
        for k in d.keys():
            out |= _syms(k)
    elif isinstance(d, list):
        for item in d:
            if isinstance(item, dict):
                for k in item.keys():
                    out |= _syms(k)
            elif isinstance(item, str):
                out |= _syms(item)
    return out


def _find_numeric_us(obj: Any, needle: str) -> float | None:
    """Lookup a timing value in μs under any key containing needle.

    Only returns values that can be confidently asserted in μs — either
    the key name contains '_us', OR the value has a '_us' sibling, OR
    a companion 'comment'/'desc' field explicitly names a μs figure.
    Returns None if we can't confirm μs (callers skip the cross-check
    rather than raise a false positive on tick-count values).
    """
    import re

    def _as_scalar(v):
        """Coerce a list/tuple [min, max] to its minimum; pass scalars through."""
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, (list, tuple)) and v and all(isinstance(x, (int, float)) for x in v):
            return float(min(v))
        return None

    # Pass 1: look for keys with _us and matching needle
    for p, v in _walk(obj):
        val = _as_scalar(v)
        if val is None:
            continue
        pu = p.upper()
        if _names_needle(p, needle) and (
                "_US" in pu or "US_" in pu or pu.endswith("US")):
            return val
    # Pass 2: look for dict entries {name: ..., value: ...} where name contains needle
    # and sibling has explicit μs context.
    for p, v in _walk(obj):
        if not isinstance(v, dict):
            continue
        name = str(v.get("name", ""))
        if name and _names_needle(name, needle):
            comment = str(v.get("comment", "")) + " " + str(v.get("desc", ""))
            m = re.search(r'(\d+(?:\.\d+)?)\s*us', comment, re.IGNORECASE)
            if m:
                return float(m.group(1))
    # Pass 3: look for dict keys with min/nom containing μs values inside a
    # {"min_us": x, "nom_us": y, "max_us": z} shape where outer key has needle.
    for p, v in _walk(obj):
        if not isinstance(v, dict):
            continue
        if not _names_needle(p, needle):
            continue
        # pick nom else min else max
        for unit_key in ("nom_us", "nom", "min_us", "min", "max_us"):
            if unit_key in v and isinstance(v[unit_key], (int, float)):
                # Only accept when a sibling key suggests μs
                keys_str = " ".join(v.keys()).lower()
                if "us" in keys_str or p.lower().endswith("_us"):
                    return float(v[unit_key])
    return None


#: Per-symbol names read by check()'s `_symbols_in`, matched against
#: IDENTIFIER TOKENS (`_identifier_tokens`), never as substrings.
_TIMING_SYMBOLS = frozenset({"h0", "h1", "br", "ibt", "break", "brk"})
#: Spellings of BR (the break / packet-end symbol).
_BR_SPELLINGS = frozenset({"br", "break", "brk"})


def _split_caps_run(m: "re.Match[str]") -> str:
    run, tail = m.group(1), m.group(2)
    if _token_symbol(run.lower()) is not None:
        return f"{run} {tail}"
    return f"{run[:-1]} {run[-1]}{tail}"


def _identifier_tokens(text: Any) -> list[str]:
    """Lower-cased tokens of an identifier or phrase: split on anything that is
    not a letter or digit, on lower->Upper (`tIBT` -> t, ibt), on an upper run
    followed by lower (`IBTmin` -> ibt, min), before a Capitalised word that
    follows an acronym (`tBRMin` -> t, br, min) and on digit->letter (`H0low`
    -> h0, low). Letter->digit never splits, so `H0` is `h0` and `CH0` is `ch0`."""
    import re
    out: list[str] = []
    for part in re.split(r"[^A-Za-z0-9]+", str(text)):
        part = re.sub(r"([a-z])([A-Z])", r"\1 \2", part)
        # A capitals run followed by lowercase is AMBIGUOUS by shape: `IBTmin`
        # is IBT+min, `BRMin` is BR+Min (review w0z2lp3a7: tBRMin read as
        # t/brm/in). Prefer the split that names a timing symbol -- the whole
        # run, else the run minus its last capital -- and otherwise the camel
        # convention (an acronym ends before a Capitalised word).
        part = re.sub(r"([A-Z]{2,})([a-z]+)", _split_caps_run, part)
        part = re.sub(r"([0-9])([A-Za-z])", r"\1 \2", part)
        out += [w.lower() for w in part.split() if w]
    return out


def _token_symbol(tok: str) -> str | None:
    """The timing symbol a token names, or None. A leading `t` is the timing-
    parameter prefix (`tIBT`, `TBR_MIN`, `tbreak`); `break` is the spelled-out
    BR."""
    for cand in (tok, tok[1:] if tok.startswith("t") else None):
        if cand in _TIMING_SYMBOLS:
            return "BR" if cand in _BR_SPELLINGS else cand.upper()
    return None


def _names_needle(text: Any, needle: str) -> bool:
    """Does `text` (a key path or a record name) name `needle` -- a symbol
    ("IBT", "BR") or a symbol with qualifiers ("TX_IBT", "BR_MIN")?

    THE ONE READER FOR A SYMBOL (review wd54r7zx6). `_symbols_in` (coverage)
    and `_find_numeric_us` (the IBT<BR number) used to read symbols two ways:
    coverage by token, the number by SUBSTRING, so `BRK_us` was "BR missing"
    to one and the BR threshold to the other. Both now go through
    `_identifier_tokens` / `_token_symbol`: each needle part that is a symbol
    must be a symbol of the text, every other part a token of it."""
    toks = _identifier_tokens(text)
    syms = {sym for t in toks if (sym := _token_symbol(t)) is not None}
    for part in str(needle).split("_"):
        if part.upper() in SYMBOLS_REQUIRED:
            if part.upper() not in syms:
                return False
        elif part.lower() not in toks:
            return False
    return True


def symbol_family_hits(waveform: Any, rtl_constants: Any = None) -> list[str]:
    """Where the L8 speaks the H0/H1/BR/IBT single-wire pulse-symbol family
    this check reads, as paths (R-0915-164).

    Read with the ONE symbol reader (`_identifier_tokens` / `_token_symbol`):
    every key at every depth, every identifier-shaped value under a schema
    record label (`l8_timing_schema.RECORD_LABEL_KEYS`) and every
    identifier-shaped list string of the L8 outside the schema's non-protocol
    keys, plus
    `symbol_directionality` and check()'s own classified RX/TX groups, plus
    the --layer constants read ONLY as check()
    reads them (`_find_numeric_us` TX_IBT / BR_MIN) -- never walked.
    """
    import l8_timing_schema as _schema
    hits: list[str] = []

    def _syms(text: Any) -> bool:
        return any(_token_symbol(t) for t in _identifier_tokens(text))

    def _is_identifier(text: Any) -> bool:
        # A label or list VALUE counts only when it is identifier-shaped: free
        # prose ('line break detection …') and sized literals (4'h1, 8'h0A) are
        # not family identifiers (review w0z2lp3a7).
        return isinstance(text, str) and bool(
            re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", text.strip()))

    def _walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                sub = f"{path}.{k}"
                if _syms(k):
                    hits.append(sub)
                if (k in _schema.RECORD_LABEL_KEYS and _is_identifier(v)
                        and _syms(v)):
                    hits.append(f"{sub}={v}")
                _walk(v, sub)
        elif isinstance(node, list):
            for i, item in enumerate(node):
                if _is_identifier(item) and _syms(item):
                    hits.append(f"{path}[{i}]={item}")
                _walk(item, f"{path}[{i}]")

    if isinstance(waveform, dict):
        if waveform.get("symbol_directionality"):
            hits.append("symbol_directionality")
        # check()'s own RX/TX groups are the family's grouping vocabulary: a
        # classified group that lacks its symbols is a real FAIL of this rule.
        _rx, _tx = classified_groups(waveform)
        hits += [f"rx_group:{k}" for k in _rx] + [f"tx_group:{k}" for k in _tx]
        for k, v in waveform.items():
            if k in _schema.NON_PROTOCOL_KEYS:
                continue
            if _syms(k):
                hits.append(str(k))
            _walk(v, str(k))
    if rtl_constants is not None:
        for needle in ("TX_IBT", "BR_MIN"):
            if _find_numeric_us(rtl_constants, needle) is not None:
                hits.append(f"layer:{needle}")
    return hits


def classified_groups(waveform: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """``(groups_rx, groups_tx)`` exactly as `check()` classifies them.

    THE ONE CLASSIFIER. `check()` and the structural-absence escape in `main()`
    both call this, so the escape can never certify "no RX/TX timing here" on a
    document `check()` would read as carrying (or naming) RX/TX timing. The
    review of next/icspm5-s2 measured the cost of two vocabularies: a
    `timing_groups` pair named `detect_thresholds` / `drive_widths` classified
    RX/TX here and was certified absent by the escape's own token list.

    v1.6.38 — first preference: explicit `timing_groups` field (new canonical
    L8 shape); its sub-keys are classified by name. Fallback: top-level keys.
    Only dicts and lists count as groups (free-form string notes often contain
    "internal"/"external" substrings but carry no per-symbol values); an EMPTY
    dict or list still counts -- a group that is named and empty is a missing-
    symbols finding, not an absence.
    """
    groups_rx: dict[str, Any] = {}
    groups_tx: dict[str, Any] = {}
    tg = waveform.get("timing_groups") if isinstance(waveform, dict) else None
    if isinstance(tg, dict):
        for key, val in tg.items():
            if not isinstance(val, (dict, list)):
                continue
            cls = _classify_group(key)
            if cls == "rx":
                groups_rx[key] = val
            elif cls == "tx":
                groups_tx[key] = val
    if not groups_rx and not groups_tx and isinstance(waveform, dict):
        for key, val in waveform.items():
            if not isinstance(val, (dict, list)):
                continue
            cls = _classify_group(key)
            if cls == "rx":
                groups_rx[key] = val
            elif cls == "tx":
                groups_tx[key] = val
    return groups_rx, groups_tx


def check(waveform: Any, rtl_constants: Any | None) -> list[Finding]:
    findings: list[Finding] = []
    groups_rx, groups_tx = classified_groups(waveform)

    if not groups_rx:
        findings.append(Finding(
            "ERROR", "missing_rx_group", "(root)",
            "No host-side / RX timing group found. L8 must carry a "
            "group with names like 'rx_*', 'host_*', 'external_*' "
            "containing per-symbol LOW-pulse widths the DUT's RX "
            "decoder must tolerate.",
        ))
    if not groups_tx:
        findings.append(Finding(
            "ERROR", "missing_tx_group", "(root)",
            "No DUT-side / TX timing group found. L8 must carry a "
            "group with names like 'tx_*', 'dut_*', 'internal_*' "
            "containing per-symbol pulse widths the DUT emits. "
            "Without this, Phase 2 will re-use host-side numbers for "
            "DUT TX — a known real-silicon FAIL root cause for half-duplex bus ICs.",
        ))

    # (2) Symbol coverage — each group that exists must cover H0,H1,BR,IBT
    # by default. v1.6.38 — for asymmetric half-duplex protocols where
    # one symbol is unidirectional (e.g. some bus protocols restrict
    # the BR / break symbol to host-side emission only), the L8 may
    # carry an explicit `symbol_directionality` map declaring which
    # symbols each side
    # actually emits. When present, only those symbols are required on
    # that side. Default behaviour (full SYMBOLS_REQUIRED on both sides)
    # is preserved when the map is absent.
    sym_dir = (waveform.get("symbol_directionality")
               if isinstance(waveform, dict) else None) or {}
    rx_required = set(sym_dir.get("rx_host_side", SYMBOLS_REQUIRED)) \
        if "rx_host_side" in sym_dir else set(SYMBOLS_REQUIRED)
    tx_required = set(sym_dir.get("tx_dut_side", SYMBOLS_REQUIRED)) \
        if "tx_dut_side" in sym_dir else set(SYMBOLS_REQUIRED)
    for g_name, g_val in groups_rx.items():
        syms = _symbols_in(g_val)
        missing = rx_required - syms
        if missing:
            findings.append(Finding(
                "ERROR", "rx_missing_symbols", g_name,
                f"host-side group missing symbols: {sorted(missing)}",
            ))
    for g_name, g_val in groups_tx.items():
        syms = _symbols_in(g_val)
        missing = tx_required - syms
        if missing:
            findings.append(Finding(
                "ERROR", "tx_missing_symbols", g_name,
                f"DUT-side group missing symbols: {sorted(missing)}",
            ))

    # (3) IBT < BR cross-check. Look in TX group first, fall back to
    #     RX group for BR threshold (RX BR threshold is what the far
    #     side uses to classify our IBT).
    tx_ibt_us = _find_numeric_us(groups_tx, "IBT") if groups_tx else None
    rx_br_us  = _find_numeric_us(groups_rx, "BR")  if groups_rx else None
    # Fall back to RTL constants if provided
    if tx_ibt_us is None and rtl_constants is not None:
        tx_ibt_us = _find_numeric_us(rtl_constants, "TX_IBT")
    if rx_br_us is None and rtl_constants is not None:
        rx_br_us = _find_numeric_us(rtl_constants, "BR_MIN")

    if tx_ibt_us is not None and rx_br_us is not None and tx_ibt_us >= rx_br_us:
        findings.append(Finding(
            "ERROR", "ibt_exceeds_br_threshold", "tx.IBT vs rx.BR",
            f"DUT-side IBT={tx_ibt_us}us is >= host-side BR={rx_br_us}us. "
            "Receiving side will classify our inter-byte gap as a "
            "packet-end BR and truncate the response. This is a real "
            "tester FAIL mode. Rule: IBT < BR minimum with margin.",
        ))

    return findings


# ORGANIC #617 — half-duplex protocol symbol-timing tokens. A `waveforms[]`
# entry carrying any of these references directional (rx/tx/host/dut) timing or
# H0/H1/BR/IBT-style symbol pulses; a generic single-/few-signal WaveDrom
# diagram (clk/addr/data/valid) emitted by doc-extraction carries none.
_WAVEFORM_PROTOCOL_TOKENS = (
    "rx_", "tx_", "host_", "dut_", "external_", "internal_",
    "_low", "_high", "ibt", "break", "_counters", "_cycles",
    "h0_", "h1_", "br_",
)


def _waveforms_carry_protocol_symbols(wfs: Any) -> bool:
    """ORGANIC #617 — True iff a `waveforms[]` value carries half-duplex
    protocol symbol-timing content (directional rx/tx/host/dut tokens or
    H0/H1/BR/IBT symbol pulses), as opposed to a GENERIC WaveDrom diagram
    (clk/addr/data/valid) auto-populated by doc-extraction. Conservative
    substring scan over the serialised value. chip-AGNOSTIC."""
    if not wfs:
        return False
    try:
        blob = json.dumps(wfs).lower()
    except (TypeError, ValueError):
        blob = str(wfs).lower()
    return any(tok in blob for tok in _WAVEFORM_PROTOCOL_TOKENS)


# ORGANIC #655 — half-duplex protocol per-symbol timing tokens for the
# `timing_constants[]` container. Mirrors the #617 `waveforms[]` treatment:
# a `timing_constants[]` entry carrying any of these references directional
# (rx/tx/host/dut) timing or H0/H1/BR/IBT-style symbol pulses; a bare scalar
# clock-frequency constant (e.g. {name:fclk,value:1.0,unit:MHz}) promoted into
# L8 by doc-extraction from an L5/spec clock table carries none. The tokens are
# the SAME protocol symbol-timing vocabulary as #617 — a scalar clk/fclk
# frequency name (clk*/fclk/sysclk/refclk…) with a Hz/MHz/GHz unit is NOT
# symbol-timing and must NOT defeat the VACUOUS_PASS escape.
_TIMING_CONSTANT_PROTOCOL_TOKENS = (
    "rx_", "tx_", "host_", "dut_", "external_", "internal_",
    "_low", "_high", "ibt", "break", "_counters", "_cycles",
    "h0_", "h1_", "br_", "_tdw", "_tdt", "tb_",
)


def _timing_constants_carry_protocol_symbols(tcs: Any) -> bool:
    """ORGANIC #655 — True iff a `timing_constants[]` value carries half-duplex
    protocol symbol-timing content (directional rx/tx/host/dut tokens or
    H0/H1/BR/IBT symbol pulses / per-symbol LOW/HIGH pulse widths), as opposed
    to a bare scalar clock-FREQUENCY constant (name like clk*/fclk, unit
    Hz/MHz/GHz, one numeric value) auto-promoted by doc-extraction from an
    L5/spec clock table. A scalar clock-frequency entry is NOT protocol
    symbol-timing — there is no RX/TX direction to split — so it must count as
    EMPTY for the VACUOUS_PASS escape. Conservative substring scan over the
    serialised value, SAME vocabulary as #617. chip-AGNOSTIC: keyed on the
    protocol symbol-timing token shape, not on any chip or unit."""
    if not tcs:
        return False
    try:
        blob = json.dumps(tcs).lower()
    except (TypeError, ValueError):
        blob = str(tcs).lower()
    return any(tok in blob for tok in _TIMING_CONSTANT_PROTOCOL_TOKENS)


def _resolve_waveform_path(arg: str) -> Path | None:
    """v1.6.38 — accept either an L8 JSON file directly OR a project_dir
    (in which case look up phase1/generated_docs/L8_TIMING_WAVEFORM.json).

    Returns None if neither shape resolves to an existing file.
    """
    p = Path(arg)
    if p.is_file():
        return p
    if p.is_dir():
        cand = p / "phase1" / "generated_docs" / "L8_TIMING_WAVEFORM.json"
        if cand.is_file():
            return cand
    return None


def _read_l2_half_duplex(arg: str) -> bool | None:
    """Return the project's L2 ``protocol_overview.half_duplex`` flag.

    Accepts EITHER a project_dir OR the L8 file path the flow manifest
    passes. When given a file under ``phase1/generated_docs/`` (the
    canonical flow-manifest invocation
    ``... L8_TIMING_WAVEFORM.json --layer ...``) we walk up to the
    project root and read the sibling ``L2_FRS.json``. Without this, the
    half-duplex VACUOUS_PASS escape never fires in the flow-manifest
    path, so every NON-half-duplex IC (memory-mapped register bus,
    pure-digital datapath, parallel bus) false-FAILs the RX/TX-split
    rule that only applies to single-wire half-duplex protocols.
    Returns None only when L2 genuinely cannot be located/parsed.
    Chip-AGNOSTIC.
    """
    p = Path(arg)
    candidates: list[Path] = []
    if p.is_dir():
        candidates.append(p / "phase1" / "generated_docs" / "L2_FRS.json")
    else:
        # arg is a file path — derive the generated_docs dir it lives in
        # and look for the sibling L2 doc. Also handle the project-root
        # form in case a caller passes <project>/phase1/...{L8}.
        gd = p.parent
        candidates.append(gd / "L2_FRS.json")
        # Walk up to a plausible project root (…/phase1/generated_docs/L8…)
        # → <project>/phase1/generated_docs/L2_FRS.json.
        for up in (p.parent, p.parent.parent, p.parent.parent.parent):
            candidates.append(up / "phase1" / "generated_docs" / "L2_FRS.json")
    for l2 in candidates:
        if not l2.is_file():
            continue
        try:
            d = json.loads(l2.read_text())
            po = d.get("protocol_overview") or {}
            if "half_duplex" in po:
                return bool(po["half_duplex"])
        except Exception:
            continue
    return None


def _registry_non_half_duplex(arg: str, resolved: Path) -> dict[str, Any] | None:
    """Return auditable class evidence only for an explicit registry false.

    Phase 1 intentionally leaves L2.protocol_overview null for ICs whose
    interface is not a wire protocol. The project-wide class detector is the
    canonical authority for that applicability decision. Unknown classes,
    unregistered classes, detector failures, and registry values other than
    the literal boolean False all fail closed by returning None.

    An explicit L2 half_duplex=true is handled before this helper is used, so
    a class/declaration conflict never suppresses the timing checks.
    """
    p = Path(arg)
    project: Path | None = p if p.is_dir() else None
    if project is None:
        gd = resolved.parent
        if gd.name == "generated_docs" and gd.parent.name == "phase1":
            project = gd.parent.parent
    if project is None or not project.is_dir():
        return None
    try:
        from ic_class_profile import detect_ic_class, class_verification_flags
        profile = detect_ic_class(project) or {}
        ic_class = str(profile.get("ic_class") or "unknown")
        flags = class_verification_flags(ic_class)
    except Exception:
        return None
    if (flags.get("registry_matched") is not True
            or flags.get("half_duplex_bus") is not False):
        return None
    return {
        "ic_class": ic_class,
        "verification_track": flags.get("verification_track"),
        "half_duplex_bus": False,
        "registry_matched": True,
        "decisive_evidence": profile.get("decisive_evidence", ""),
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Require L8 to separate host-side (RX) and DUT-side (TX) timing groups.",
    )
    ap.add_argument("waveform",
                    help=("L8_TIMING_WAVEFORM.json file path, OR a project "
                          "directory (auto-resolves "
                          "phase1/generated_docs/L8_TIMING_WAVEFORM.json)."))
    ap.add_argument("--layer", help="Optional L8_RTL_CONSTANTS.json for cross-check.")
    ap.add_argument("--json", nargs='?', const='-', default=None, metavar='PATH',
                    help="Emit JSON. With PATH writes to file; bare flag prints to stdout.")
    args = ap.parse_args()

    # v1.6.38 — accept project_dir as well as a direct file path.
    resolved = _resolve_waveform_path(args.waveform)
    if resolved is None:
        print(f"error: file not found: {args.waveform}", file=sys.stderr)
        return 2
    waveform_path = str(resolved)
    half_duplex_l2 = _read_l2_half_duplex(args.waveform)
    registry_non_hd = (
        _registry_non_half_duplex(args.waveform, resolved)
        if half_duplex_l2 is None else None
    )

    try:
        with open(waveform_path, "r") as f:
            waveform = json.load(f)
    except json.JSONDecodeError as e:
        print(f"error: invalid JSON in {waveform_path}: {e}", file=sys.stderr)
        return 2

    rtl_constants = None
    if args.layer:
        try:
            with open(args.layer, "r") as f:
                rtl_constants = json.load(f)
        except Exception as e:
            print(f"warning: could not read {args.layer}: {e}", file=sys.stderr)

    # v1.6.38 — VACUOUS_PASS gate when L2 explicitly declares this is NOT
    # a half-duplex protocol. The RX/TX split rule only applies to
    # half-duplex single-wire shared-direction protocols. Pure-digital
    # ICs and parallel-bus protocols don't have the directional-
    # asymmetry hazard the gate prevents.
    if half_duplex_l2 is False:
        msg = ("VACUOUS_PASS: L2 protocol_overview.half_duplex=false — "
               "RX/TX timing split rule does not apply.")
        if args.json:
            txt = json.dumps({
                "source_file": waveform_path,
                "total_findings": 0,
                "errors": 0,
                "findings": [],
                "verdict": "VACUOUS_PASS",
                # v1.15.45 (sha256 capture): the design's OWN L2 declaration
                # rules the rule out — say so in the vocabulary the audit
                # reads, or a green vacuous record is filed INCOMPLETE.
                "reason_class": "DESIGN_DECLARED_NA",
                "skip_kind": "class-not-applicable",
                "rationale": msg,
            }, indent=2)
            if args.json == "-":
                print(txt)
            else:
                Path(args.json).parent.mkdir(parents=True, exist_ok=True)
                Path(args.json).write_text(txt + "\n")
        else:
            print(msg)
        return 0

    # #3415: non-protocol classes must not be forced to invent an L2
    # half-duplex declaration merely to disable a rule outside their class.
    # This requires a registry match and the literal half_duplex_bus=false.
    # Unknown classes stay INCOMPLETE, and explicit L2 true above prevents
    # the class fact from masking contradictory design input.
    if registry_non_hd is not None:
        msg = (
            "VACUOUS_PASS: canonical IC-class registry declares "
            f"half_duplex_bus=false for {registry_non_hd['ic_class']!r} "
            f"(verification_track="
            f"{registry_non_hd.get('verification_track')!r}) -- RX/TX "
            "single-wire timing split rule does not apply."
        )
        if args.json:
            txt = json.dumps({
                "source_file": waveform_path,
                "total_findings": 0,
                "errors": 0,
                "findings": [],
                "verdict": "VACUOUS_PASS",
                "reason_class": "DESIGN_DECLARED_NA",
                "skip_kind": "class-not-applicable",
                "applicability_evidence": registry_non_hd,
                "rationale": msg,
            }, indent=2)
            if args.json == "-":
                print(txt)
            else:
                Path(args.json).parent.mkdir(parents=True, exist_ok=True)
                Path(args.json).write_text(txt + "\n")
        else:
            print(msg)
        return 0

    # VACUOUS_PASS when the L8 waveform carries NO protocol / symbol timing
    # content at all. The RX/TX-split rule only applies to half-duplex
    # single-wire shared-direction protocols whose L8 records per-symbol
    # pulse widths (timing_windows / timing_constants / waveforms). A
    # pure-digital arithmetic / parallel-bus IC (e.g. an spm multiplier) has
    # only clock_domains and zero symbol timing — there is nothing to split,
    # so demanding rx_*/tx_* groups would FAIL every non-protocol IC. This
    # complements the explicit L2.half_duplex=false escape above for the
    # common case where L2 simply never mentions a protocol. chip-AGNOSTIC:
    # keyed on the absence of symbol-timing content, not on any chip.
    #
    # ORGANIC #617 — a `waveforms[]` entry counts as EMPTY for this escape
    # unless it actually carries half-duplex protocol symbol-timing content
    # (rx_/tx_/host_/dut_ directional tokens or H0/H1/BR/IBT-style symbol
    # pulses). doc-extraction auto-populates `waveforms[]` with a GENERIC
    # single-/few-signal WaveDrom diagram (e.g. a basic memory-transaction or
    # bus diagram from a source .rst) that has zero rx_/tx_ symbol groups; a
    # non-empty `waveforms[]` of that kind previously defeated the
    # all(_empty(...)) short-circuit, so a non-half-duplex compute/CPU IC
    # (whose L2 also has no protocol_overview → half_duplex_l2 is None, not
    # False) ran the hard rx_/tx_ demand and false-FAILed. A genuine
    # half-duplex L8 (rx_/tx_ groups, or symbol pulses in waveforms) is
    # unaffected — its waveforms carry protocol tokens so it is NOT treated
    # as empty.
    #
    # ORGANIC #655 — the SAME content-discriminator must apply to the
    # `timing_constants[]` container. doc-extraction promotes a bare scalar
    # clock-FREQUENCY constant (e.g. {name:fclk,value:1.0,unit:MHz}) into L8
    # from an L5/spec clock table. That single non-protocol entry previously
    # made `_empty('timing_constants')` False → defeated the all(_empty(...))
    # short-circuit → forced the hard half-duplex RX/TX per-symbol-group demand
    # on a non-protocol IC (delta-sigma ADC, CPU core, …) whose L2 also has no
    # protocol_overview (half_duplex_l2 is None, not False), so the gate
    # unconditionally FAILed with missing_rx_group + missing_tx_group. A scalar
    # clock-frequency entry is NOT protocol symbol-timing — there is no RX/TX
    # direction to split — so it counts as EMPTY unless it actually carries
    # directional / per-symbol protocol content (rx_/tx_/host_/dut_ tokens or
    # H0/H1/BR/IBT-style pulse widths). A genuine half-duplex L8 that stores
    # per-symbol counters/cycles in timing_constants[] carries those tokens and
    # is therefore NOT treated empty — the strict split still runs (no-leak).
    def _empty(key):
        v = waveform.get(key)
        if not v:  # None / [] / {} / 0 all count as empty
            return True
        if key == "waveforms" and not _waveforms_carry_protocol_symbols(v):
            return True  # generic WaveDrom diagram, no protocol symbols (#617)
        if key == "timing_constants" and \
                not _timing_constants_carry_protocol_symbols(v):
            return True  # scalar clock-frequency only, no protocol symbols (#655)
        return False
    # R-0915-153 — DECIDED BY THE L8 SCHEMA, NOT BY WORDS. Three rounds of
    # deciding "no protocol timing here" from key-name / content tokens each
    # traded a false FAIL for a false NABS. The escape now fires ONLY when:
    #   * every protocol-timing container the emitter defines
    #     (`l8_timing_schema.PROTOCOL_TIMING_CONTAINERS`) is empty -- the
    #     canonical lists still read through the #617/#655 content
    #     discriminators above, `timing_groups`/`symbol_directionality` empty;
    #   * EVERY other top-level key is one an emitter declares non-protocol
    #     (`l8_timing_schema.NON_PROTOCOL_KEYS`); an UNKNOWN key is not
    #     evidence of absence, so check() runs (fail closed);
    #   * the --layer constants hold neither value check() reads from them
    #     (`_find_numeric_us` TX_IBT / BR_MIN) -- the layer is read ONLY that
    #     way, never walked.
    # No token vocabulary is consulted here.
    import l8_timing_schema as _schema
    _CANONICAL = ("timing_windows", "timing_constants", "waveforms")
    _containers_empty = all(
        _empty(k) if k in _CANONICAL else not waveform.get(k)
        for k in _schema.PROTOCOL_TIMING_CONTAINERS)
    _unknown_keys = sorted(
        str(k) for k in waveform
        if k not in _schema.PROTOCOL_TIMING_CONTAINERS
        and k not in _schema.NON_PROTOCOL_KEYS)
    _layer_timing = rtl_constants is not None and any(
        _find_numeric_us(rtl_constants, needle) is not None
        for needle in ("TX_IBT", "BR_MIN"))
    if (half_duplex_l2 is not True and _containers_empty
            and not _unknown_keys and not _layer_timing):
        # The enumeration is exactly what was decided on: every top-level key
        # of the document, each one either an empty protocol container or a
        # schema-declared non-protocol key.
        _scanned_names = sorted(str(k) for k in waveform)
        if not _scanned_names:
            # Review wd54r7zx6 (LOW 1) — NOTHING WAS WALKED, so nothing can be
            # certified absent: `_structural_absence` refuses scanned=0 and the
            # gate used to die with a traceback (CRASHED -> step FAIL). An empty
            # L8 is "cannot decide": INCOMPLETE, naming it.
            msg = ("INCOMPLETE: internal_vs_external_timing: "
                   f"{waveform_path} (L8_TIMING_WAVEFORM) is empty -- there is "
                   "nothing to walk, so the absence of protocol timing cannot "
                   "be established; regenerate the L8 (Phase 1) or declare "
                   "L2 protocol_overview.half_duplex=false.")
            if args.json:
                txt = json.dumps({
                    "source_file": waveform_path, "total_findings": 0,
                    "errors": 0, "findings": [], "verdict": "INCOMPLETE",
                    "reason_class": "BLOCKED_BY_UPSTREAM",
                    "skip_kind": "missing-upstream-output",
                    "reason": msg}, indent=2)
                if args.json == "-":
                    print(txt)
                else:
                    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
                    Path(args.json).write_text(txt + "\n")
            else:
                print(msg)
            return 2
        _absence = _sa.absence(
            population=("L8_TIMING_WAVEFORM top-level key(s), classified by "
                        "the L8 schema (l8_timing_schema)"),
            scanned=len(_scanned_names),
            found=0,
            names=_scanned_names,
            detail=("every protocol-timing container the L8 schema defines is "
                    "empty, every other key is one the emitters declare "
                    "non-protocol, and the --layer constants carry no TX_IBT / "
                    "BR_MIN value, so there are no two sides to split "
                    "(R-0915-153)"))
        msg = _sa.sentence(_absence, "internal_vs_external_timing")
        if args.json:
            txt = json.dumps({
                "source_file": waveform_path,
                "total_findings": 0,
                "errors": 0,
                "findings": [],
                "verdict": "VACUOUS_PASS",
                # v1.15.45 established that a green vacuous record must state a
                # class the audit reads or be filed INCOMPLETE. That still holds;
                # what changes is WHICH class, because this branch establishes its
                # absence by ENUMERATION rather than by reading a declaration.
                # `attach` writes the class and its evidence where every reader
                # already looks, so the umbrella's guard (i) can VALIDATE the
                # claim instead of taking the token on trust.
                **_sa.attach({}, _absence),
                "skip_kind": "class-not-applicable",
                "rationale": msg,
            }, indent=2)
            if args.json == "-":
                print(txt)
            else:
                Path(args.json).parent.mkdir(parents=True, exist_ok=True)
                Path(args.json).write_text(txt + "\n")
        else:
            # THE TIER STAYS AT LINE START. `_stdout_signals_vacuous` believes a
            # vacuous disclosure only where `VACUOUS_PASS` BEGINS a line, and a
            # clause that invokes this gate WITHOUT `--json` has stdout as its
            # only channel. Printing the structural sentence alone put
            # `[NOT_APPLICABLE_BY_STRUCTURE]` first and silently removed the
            # disclosure, so such a clause would have read a bare PASS -- a
            # fail-open I introduced, caught by one G-arm red.
            #
            # The VERDICT TIER never changed: this branch has always been, and
            # still is, a VACUOUS_PASS (the JSON above says so). What R-0915-124/125
            # made precise is the CLASS. So stdout now carries BOTH -- the tier
            # word the flow reads, then the class and the enumeration a human
            # needs to check the claim.
            print(f"VACUOUS_PASS: {msg}")
        return 0

    # R-0915-156 — THE QUESTION'S OWN DECLARATION IS MISSING: INCOMPLETE, NOT
    # FAIL. Reaching here, the L8 carries protocol timing the schema cannot
    # clear (a non-empty protocol container, an undeclared key, or a TX_IBT /
    # BR_MIN constant). Whether the half-duplex RX/TX split applies to it is
    # the design's own `L2_FRS.json protocol_overview.half_duplex`. With that
    # declaration absent the gate has not read the input it needs: that is
    # "cannot decide", and a FAIL would claim a defect nobody measured. Still
    # fail-closed: never NABS, never PASS, never green. Measured on the corpus
    # (101 real L8s): 27 protocol designs main certified NABS by name-token
    # luck, and 4 it FAILed, read this.
    if half_duplex_l2 is None:
        l2_path = "phase1/generated_docs/L2_FRS.json"
        msg = ("INCOMPLETE: internal_vs_external_timing: the L8 carries "
               "protocol timing, and whether the half-duplex RX/TX split "
               f"applies to it is undeclared -- {l2_path} "
               "protocol_overview.half_duplex is absent. Declare it: false -> "
               "the half-duplex question does not apply (NOT_APPLICABLE, basis "
               "= the declaration); true -> the RX/TX timing split is checked "
               "(PASS/FAIL on the numbers).")
        if args.json:
            txt = json.dumps({
                "source_file": waveform_path,
                "total_findings": 0,
                "errors": 0,
                "findings": [],
                "verdict": "INCOMPLETE",
                # The declaration this check needs is an UPSTREAM (Phase-1)
                # output that was not produced: the taxonomy's
                # BLOCKED_BY_UPSTREAM, an INCOMPLETE class (never skip-eligible).
                "reason_class": "BLOCKED_BY_UPSTREAM",
                "skip_kind": "missing-upstream-output",
                "missing_declaration": {
                    "path": l2_path, "key": "protocol_overview.half_duplex",
                    "if_false": "NOT_APPLICABLE (basis: the declaration)",
                    "if_true": "RX/TX timing split checked (PASS/FAIL)"},
                "reason": msg,
            }, indent=2)
            if args.json == "-":
                print(txt)
            else:
                Path(args.json).parent.mkdir(parents=True, exist_ok=True)
                Path(args.json).write_text(txt + "\n")
        else:
            print(msg)
        return 2

    # R-0915-164 — DECLARED HALF-DUPLEX, BUT NOT IN THIS SYMBOL FAMILY. check()
    # reads ONE single-wire pulse-symbol family (H0/H1/BR/IBT groups,
    # symbol_directionality, TX_IBT/BR_MIN). A design that declares
    # half_duplex=true and expresses its turnaround timing otherwise
    # (MIL-STD-1553 RT response time, DALI forward->backward delay, SD NCR)
    # cannot have its split decided by this checker: INCOMPLETE naming that and
    # listing the candidate keys -- never a FAIL for vocabulary it does not
    # speak. When the family's vocabulary IS present, check() judges it and a
    # missing group or a violated number still FAILs.
    if not symbol_family_hits(waveform, rtl_constants):
        import l8_timing_schema as _schema
        candidates = sorted(
            str(k) for k, v in waveform.items()
            if k not in _schema.NON_PROTOCOL_KEYS and v not in (None, [], {}))
        msg = ("INCOMPLETE: internal_vs_external_timing: L2 declares "
               "half_duplex=true, but turnaround timing is not expressed in "
               "the H0/H1/BR/IBT symbol family this check reads, so the RX/TX "
               "split cannot be decided here. Candidate keys: "
               + (", ".join(candidates) if candidates else "none"))
        if args.json:
            txt = json.dumps({
                "source_file": waveform_path, "total_findings": 0,
                "errors": 0, "findings": [], "verdict": "INCOMPLETE",
                # The checker cannot read the design's timing vocabulary: the
                # taxonomy's EXECUTION_ERROR is wrong (nothing errored) and
                # BLOCKED_BY_UPSTREAM is wrong (the upstream produced it). The
                # INCOMPLETE class for "the population this rule reads is
                # empty" is ZERO_DENOMINATOR.
                "reason_class": "ZERO_DENOMINATOR",
                "candidate_keys": candidates,
                "reason": msg}, indent=2)
            if args.json == "-":
                print(txt)
            else:
                Path(args.json).parent.mkdir(parents=True, exist_ok=True)
                Path(args.json).write_text(txt + "\n")
        else:
            print(msg)
        return 2

    findings = check(waveform, rtl_constants)
    errors = [f for f in findings if f.severity == "ERROR"]

    if args.json:
        _txt = json.dumps({
            "source_file": waveform_path,
            "total_findings": len(findings),
            "errors": len(errors),
            "findings": [asdict(f) for f in findings],
            "verdict": "PASS" if not errors else "FAIL",
        }, indent=2)
        if args.json == '-':
            print(_txt)
        else:
            from pathlib import Path as _P
            _P(args.json).parent.mkdir(parents=True, exist_ok=True)
            _P(args.json).write_text(_txt + "\n")
    else:
        for f in findings:
            print(f"[{f.severity}] {f.rule} @ {f.field}: {f.message}")
        print(f"\n{len(errors)} error(s), {len(findings)-len(errors)} warning(s)")
        print("PASS" if not errors else "FAIL")

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
