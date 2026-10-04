#!/usr/bin/env python3
"""Source-bound pulse-width timeout/rearm contract extraction.

This module deliberately recognises a narrow, explicit source contract.  A
mention of a pulse, a counter, or a timeout on its own is not enough: the
source must identify the input, an active-width maximum, the timeout action,
and the two rearm conditions (inactive level followed by a new start edge).
The result carries the exact source quote and immutable hashes so downstream
consumers can disclose what they measured.

The parser accepts either a small JSON object (the preferred interchange) or
the same fields in a marked text block.  It also accepts one explicit prose
sentence for source documents that have no structured sidecar.  It never
infers a pulse contract from a signal name or from generic timing vocabulary.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional, Tuple

import _prose_polarity as _pp


_IDENT = r"[A-Za-z_]\w*"
_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)


class DuplicateContractKey(ValueError):
    """A JSON contract cannot let a later duplicate silently replace a field."""


def _reject_duplicate_keys(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise DuplicateContractKey(f"duplicate JSON key: {key}")
        out[key] = value
    return out


@dataclass(frozen=True)
class PulseWidthRearmContract:
    input_signal: str
    accept_output: str
    clock_signal: str
    max_width_cycles: int
    start_edge: str
    timeout_action: str
    rearm_requires_inactive: bool
    rearm_requires_new_start_edge: bool
    source_quote: str
    source_sha256: str
    source_quote_sha256: str
    declared_source_sha256: str = ""
    source_hash_valid: Optional[bool] = None
    source_format: str = "prose"
    reset_signal: str = ""
    reset_active_low: Optional[bool] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ContractParse:
    contract: Optional[PulseWidthRearmContract]
    declared: bool
    reason: str = ""


def _clean_identifier(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip().strip("`'\" ")
    return value if re.fullmatch(_IDENT, value) else ""


def _as_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower().replace("-", "_").replace(" ", "_")
        if low in {"true", "yes", "1", "required", "requires_inactive"}:
            return True
        if low in {"false", "no", "0", "none", "not_required"}:
            return False
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    return None


def _normalise_policy(value: Any) -> Tuple[Optional[bool], Optional[bool]]:
    """Return (inactive-required, new-edge-required) for a declared policy."""
    if isinstance(value, dict):
        inactive = _as_bool(value.get("inactive") if "inactive" in value
                            else value.get("requires_inactive"))
        edge = _as_bool(value.get("new_start_edge") if "new_start_edge" in value
                        else (value.get("requires_new_start_edge") if
                              "requires_new_start_edge" in value else
                              value.get("new_edge")))
        return inactive, edge
    if not isinstance(value, str):
        return None, None
    low = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    # Only an enumerated positive policy is accepted.  Searching for words in
    # free text made phrases such as "not inactive" and "without a rising
    # edge" look like affirmative obligations.
    if low in {"inactive_then_new_start_edge", "inactive_and_new_rising_edge",
               "inactive_then_new_rising_edge"}:
        return True, True
    return None, None


def _source_hashes(source_text: str, quote: str, declared: str) -> Tuple[str, str, Optional[bool]]:
    source_sha = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    quote_sha = hashlib.sha256(quote.encode("utf-8")).hexdigest()
    if declared:
        return source_sha, quote_sha, bool(_SHA256.fullmatch(declared) and
                                          declared.lower() == source_sha)
    return source_sha, quote_sha, None


def _make_contract(source_text: str, data: Dict[str, Any], quote: str,
                   source_format: str) -> ContractParse:
    if source_format == "json":
        required = {
            "source_quote", "input_signal", "accept_output", "clock_signal",
            "max_width_cycles", "start_edge", "timeout_action",
            "rearm_requires_inactive", "rearm_requires_new_start_edge",
        }
        missing = sorted(required - set(data))
        if missing:
            return ContractParse(None, True,
                                 "explicit JSON pulse contract is missing typed field(s): "
                                 + ", ".join(missing))
    inp = _clean_identifier(data.get("input_signal") or data.get("input") or
                            data.get("pulse_input"))
    out = _clean_identifier(data.get("accept_output") or data.get("output") or
                            data.get("capture_output") or data.get("valid_output"))
    clk = _clean_identifier(data.get("clock_signal") or data.get("clock") or
                            data.get("clk"))
    raw_max = (data.get("max_width_cycles") or data.get("max_cycles") or
               data.get("maximum_width_cycles") or data.get("max_width"))
    try:
        max_width = int(raw_max)
    except (TypeError, ValueError):
        max_width = 0
    start_edge = str(data.get("start_edge") or data.get("edge") or "").lower()
    if start_edge not in {"rising"}:
        start_edge = ""
    timeout = str(data.get("timeout_action") or data.get("timeout") or "").lower()
    timeout_ok = timeout.strip() == "reject"
    inactive, edge = _normalise_policy(data.get("rearm") or
                                       data.get("rearm_policy"))
    # Explicit booleans take precedence over a compact policy string.
    for key in ("rearm_requires_inactive", "requires_inactive"):
        if key in data:
            inactive = _as_bool(data[key])
    for key in ("rearm_requires_new_start_edge", "requires_new_start_edge"):
        if key in data:
            edge = _as_bool(data[key])
    quote = (str(data.get("source_quote") or quote).strip())
    reset_signal = _clean_identifier(data.get("reset_signal") or data.get("reset"))
    reset_active_low = _as_bool(data.get("reset_active_low"))
    declared_hash = str(data.get("source_sha256") or data.get("source_hash") or "").strip().lower()
    if (reset_signal and reset_active_low is None):
        return ContractParse(None, True,
                             "explicit pulse contract must state reset_active_low "
                             "when reset_signal is present")
    role_names = [name for name in (inp, out, clk, reset_signal) if name]
    if len(role_names) != len(set(role_names)):
        return ContractParse(None, True,
                             "pulse contract signal roles must be injective")
    if not (inp and out and clk and 1 <= max_width <= 1_000_000 and
            start_edge and timeout_ok and inactive is True and edge is True and quote):
        return ContractParse(None, True,
                             "explicit pulse contract is incomplete; input, clock, "
                             "accept output, max width, reject timeout, source quote, "
                             "and both rearm conditions are required")
    source_sha, quote_sha, hash_valid = _source_hashes(source_text, quote, declared_hash)
    return ContractParse(PulseWidthRearmContract(
        input_signal=inp,
        accept_output=out,
        clock_signal=clk,
        max_width_cycles=max_width,
        start_edge="rising",
        timeout_action="reject",
        rearm_requires_inactive=True,
        rearm_requires_new_start_edge=True,
        source_quote=quote,
        source_sha256=source_sha,
        source_quote_sha256=quote_sha,
        declared_source_sha256=declared_hash,
        source_hash_valid=hash_valid,
        source_format=source_format,
        reset_signal=reset_signal,
        reset_active_low=reset_active_low,
    ), True, "")


def _json_contract(source_text: str) -> Optional[ContractParse]:
    candidates = []
    stripped = source_text.strip()
    if stripped.startswith("{"):
        candidates.append(stripped)
    candidates.extend(m.group(1) for m in re.finditer(
        r"```(?:json|pulse[_ -]?width[_ -]?rearm)?\s*\n(.*?)```",
        source_text, re.IGNORECASE | re.DOTALL))
    for blob in candidates:
        try:
            obj = json.loads(blob, object_pairs_hook=_reject_duplicate_keys)
        except DuplicateContractKey as exc:
            return ContractParse(None, True, str(exc))
        except (TypeError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        data = (obj.get("pulse_width_rearm_contract") or
                obj.get("pulse_width_rearm") or obj.get("contract"))
        if isinstance(data, dict):
            if not isinstance(data.get("source_quote"), str) or not data["source_quote"].strip():
                return ContractParse(None, True,
                                     "explicit pulse contract is missing source_quote")
            return _make_contract(source_text, data,
                                  data.get("source_quote", ""), "json")
    return None


def _marked_contract(source_text: str) -> Optional[ContractParse]:
    if not re.search(r"pulse[_ -]?width[_ -]?rearm|pulse[_ -]?rearm[_ -]?contract",
                     source_text, re.IGNORECASE):
        return None
    data: Dict[str, Any] = {}
    patterns = {
        "input": r"(?:input_signal|pulse_input|input)\s*[:=]\s*[`'\"]?([A-Za-z_]\w*)",
        "output": r"(?:accept_output|capture_output|valid_output|output)\s*[:=]\s*[`'\"]?([A-Za-z_]\w*)",
        "clock": r"(?:clock_signal|clock|clk)\s*[:=]\s*[`'\"]?([A-Za-z_]\w*)",
        "reset": r"(?:reset_signal|reset|rst)\s*[:=]\s*[`'\"]?([A-Za-z_]\w*)",
        "max_width_cycles": r"(?:max_width_cycles|maximum_width_cycles|max_width|max_cycles)\s*[:=]\s*(\d+)",
        "start_edge": r"start_edge\s*[:=]\s*(rising|posedge)",
        "timeout": r"(?:timeout_action|timeout)\s*[:=]\s*([A-Za-z_ -]+)",
        "rearm": r"(?:rearm_policy|rearm)\s*[:=]\s*([^\n,;]+)",
        "source_quote": r"source_quote\s*[:=]\s*[`\"'](.+?)[`\"']",
        "source_sha256": r"(?:source_sha256|source_hash)\s*[:=]\s*([0-9a-fA-F]{64})",
        "reset_active_low": r"reset_active_low\s*[:=]\s*(true|false|yes|no|1|0)",
    }
    for key, pattern in patterns.items():
        m = re.search(pattern, source_text, re.IGNORECASE)
        if m:
            # Marked fields are one-record-per-line declarations.  A denial
            # before the field name is prose that retires the declaration; it
            # must not be inverted into a live contract.  Keep the value side
            # alone: ``reset_active_low: no`` is a valid typed boolean, while
            # ``not reset_active_low: true`` is a denied declaration.
            if key != "source_quote":
                lo, _ = _pp.sentence_scope(
                    source_text, m.start(), m.end(), extra_breaks=("\n",))
                if _pp.is_denied(source_text[lo:m.start()]) is not None:
                    return ContractParse(
                        None, True,
                        "explicit pulse contract contains a denied marked field")
            data[key] = m.group(1).strip()
    # The marked form may state the two booleans separately.
    for key in ("rearm_requires_inactive", "requires_inactive",
                "rearm_requires_new_start_edge", "requires_new_start_edge"):
        m = re.search(rf"{re.escape(key)}\s*[:=]\s*(true|false|yes|no|1|0)",
                      source_text, re.IGNORECASE)
        if m:
            data[key] = m.group(1)
    quote = data.get("source_quote", "")
    if not quote:
        return ContractParse(None, True,
                             "explicit pulse contract is missing source_quote")
    return _make_contract(source_text, data, quote, "marked")


def _prose_contract(source_text: str) -> Optional[ContractParse]:
    # Require a single source clause that contains all load-bearing statements.
    clauses = re.split(r"(?<=[.!?])\s+|\n+", source_text.strip())
    for clause in clauses:
        low = clause.lower()
        if re.search(r"\b(?:not|never|without|does\s+not|must\s+not|shall\s+not)\b",
                     low):
            # A negated mention must never be inverted into a positive contract.
            if re.search(r"timeout|overlong|re[- ]?arm|inactive|rising\s+edge",
                         low):
                return ContractParse(None, True,
                                     "explicit pulse contract contains a negated "
                                     "timeout or rearm condition")
        if not re.search(r"(?:max(?:imum)?|at most|no more than).{0,80}"
                         r"(?:width|duration|length).{0,30}\b\d+\s*"
                         r"(?:cycles?|clocks?)", low):
            continue
        if not re.search(r"re[- ]?arm", low) or not re.search(r"inactive|deassert", low):
            continue
        if not re.search(r"new\s+(?:start\s+)?(?:rising\s+)?edge|rising\s+edge|new\s+start", low):
            continue
        if not re.search(r"timeout|overlong", low) or not re.search(
                r"reject|discard|invalid|drop|error", low):
            continue
        im = re.search(r"(?:input|pulse(?:\s+input)?|active\s+input)\s*[`'\"]?"
                       rf"({_IDENT})[`'\"]?", clause, re.IGNORECASE)
        mm = re.search(r"(?:max(?:imum)?|at most|no more than).{0,80}?"
                       r"(?:width|duration|length)\s*(?:is|of|=|:)?\s*"
                       r"(\d+)\s*(?:cycles?|clocks?)", clause, re.IGNORECASE)
        om = re.search(r"(?:accept|capture|valid)\s+(?:output|signal)?\s*"
                       r"(?:is|=|:)?\s*[`'\"]?"
                       rf"({_IDENT})[`'\"]?", clause, re.IGNORECASE)
        cm = re.search(r"(?:clock|clk)\s+(?:is|=|:)?\s*[`'\"]?"
                       rf"({_IDENT})[`'\"]?", clause, re.IGNORECASE)
        if im and mm and om and cm:
            return _make_contract(source_text, {
                "input": im.group(1), "output": om.group(1), "clock": cm.group(1),
                "max_width_cycles": mm.group(1), "start_edge": "rising",
                "timeout": "reject", "rearm": "inactive_then_new_start_edge",
                "source_quote": clause.strip(),
            }, clause.strip(), "prose")
    return None


def extract_contract(source_text: str) -> ContractParse:
    """Extract one explicit contract; return a disclosed limitation otherwise."""
    for parser in (_json_contract, _marked_contract, _prose_contract):
        result = parser(source_text)
        if result is not None:
            return result
    return ContractParse(None, False,
                         "no explicit source-declared pulse maximum and rearm contract")
