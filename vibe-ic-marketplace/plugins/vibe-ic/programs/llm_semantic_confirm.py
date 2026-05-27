#!/usr/bin/env python3
"""llm_semantic_confirm.py — LLM double-confirm for program-extracted SEMANTIC fields.

System rule: a deterministic program's grasp of MEANING is inferior to an LLM's (and the
LLM keeps improving), so any value a parser extracts from natural-language meaning is only
a CANDIDATE. Before it enters the structured contract it must be re-judged by an LLM:

    program PROPOSES (candidate + the evidence snippet it used)
        -> LLM CONFIRMS / CORRECTS
            -> only the confirmed value is trusted

Scope: prose-inferred scalar spec fields — reset mode/polarity, output latency, FSM output
style (Moore/Mealy). Structurally-certain values (Verilog-header ports, JSON contract
fields) are NOT semantic and are not sent here.

Graceful degradation: on a host with no LLM backend (no ANTHROPIC_API_KEY / anthropic SDK),
this is a no-op that returns the candidate marked `confirmed=False, source=
'unconfirmed-no-backend'` so callers can route it to agent-layer confirmation instead of
silently trusting a deterministic guess. Tests inject a fake client via `client_factory`,
so the confirm path is exercised deterministically and offline.
"""
from __future__ import annotations
import json
import os
import re
from dataclasses import dataclass, asdict
from typing import Any, Callable, List, Optional

DEFAULT_MODEL = "claude-opus-4-7"

# Allowed value sets per semantic field (None = "spec does not declare it").
_ALLOWED = {
    "reset_mode": ["synchronous", "asynchronous", None],
    "reset_polarity": ["active-high", "active-low", None],
    "latency_registered": [True, False, None],
    "fsm_output_style": ["moore", "mealy", None],
}

# Per-field domain facts that keep the confirmer from a known reasoning error. These are
# general truths, not problem-specific hints. (The fsm one is the lesson from a confirm that
# wrongly overrode a correct Moore candidate to Mealy, reasoning "Moore is impossible here".)
_FIELD_NOTE = {
    "fsm_output_style": (
        "Decide ONLY what the spec REQUIRES — do not judge feasibility. A Moore machine is "
        "realizable for ANY sequential function (register the output: z_reg <= f(state)), so "
        "'Moore is impossible for this behavior' is never a valid reason to override a Moore "
        "declaration. If the spec says Moore, keep 'moore'."),
}


@dataclass
class Confirmation:
    field: str
    candidate: Any
    value: Any                 # confirmed / corrected value
    confirmed: bool            # True iff an LLM actually re-judged it
    agree: Optional[bool]      # did the LLM agree with the candidate? (None if not confirmed)
    reason: str
    source: str                # 'llm' | 'unconfirmed-no-backend' | 'error'


def backend_available() -> bool:
    if os.environ.get("VIBE_IC_DISABLE_LLM_CONFIRM"):
        return False
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
        return True
    except Exception:
        return False


def _build_prompt(field: str, candidate: Any, evidence: str) -> str:
    allowed = _ALLOWED.get(field)
    allowed_str = ", ".join("null" if a is None else repr(a) for a in allowed) if allowed else "any"
    return (
        "You are double-checking a deterministic parser that extracts one SEMANTIC fact "
        "from a hardware spec. Re-read the spec evidence and decide the correct value.\n\n"
        f"Field: {field}\n"
        f"Allowed values: {allowed_str}\n"
        f"Parser's candidate: {json.dumps(candidate)}\n\n"
        f"Spec evidence:\n\"\"\"\n{evidence.strip()}\n\"\"\"\n\n"
        + (_FIELD_NOTE[field] + "\n\n" if field in _FIELD_NOTE else "")
        + "Reply with ONLY a JSON object: "
        '{\"value\": <one allowed value>, \"agree\": <true|false>, \"reason\": \"<short>\"}. '
        "If the spec does not clearly declare this field, value must be null."
    )


def _parse_reply(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in LLM reply")
    return json.loads(m.group(0))


def confirm_semantic(field: str, candidate: Any, evidence: str,
                     client_factory: Optional[Callable[[], Any]] = None,
                     model: Optional[str] = None) -> Confirmation:
    """Re-judge one semantic candidate with an LLM. No-op (unconfirmed) if no backend."""
    if client_factory is None and not backend_available():
        return Confirmation(field, candidate, candidate, False, None,
                            "no LLM backend — candidate left unconfirmed for agent-layer review",
                            "unconfirmed-no-backend")
    try:
        if client_factory is not None:
            client = client_factory()
        else:
            import anthropic
            client = anthropic.Anthropic()
        msg = client.messages.create(
            model=model or os.environ.get("VIBE_IC_CONFIRM_MODEL", DEFAULT_MODEL),
            max_tokens=300,
            messages=[{"role": "user", "content": _build_prompt(field, candidate, evidence)}],
        )
        text = "".join(getattr(b, "text", "") for b in msg.content)
        data = _parse_reply(text)
        value = data.get("value", candidate)
        if field in _ALLOWED and value not in _ALLOWED[field]:
            # LLM returned something outside the allowed set — keep candidate, flag it.
            return Confirmation(field, candidate, candidate, False, None,
                                f"LLM returned out-of-range value {value!r}", "error")
        return Confirmation(field, candidate, value, True, bool(data.get("agree")),
                            str(data.get("reason", "")), "llm")
    except Exception as e:  # noqa: BLE001
        return Confirmation(field, candidate, candidate, False, None,
                            f"confirm error: {e}", "error")


# Which SpecContract fields are semantic (need confirmation) + how to find their evidence.
_SEMANTIC_FIELDS = ("reset_mode", "reset_polarity", "latency_registered", "fsm_output_style")


def _sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.\n])", text) if s.strip()]


def evidence_for(field: str, text: str) -> str:
    """Best-effort: the spec sentence(s) that bear on this field."""
    keys = {
        "reset_mode": ("reset",),
        "reset_polarity": ("reset", "active"),
        "latency_registered": ("registered", "clock cycle", "combinational", "cycle"),
        "fsm_output_style": ("moore", "mealy", "state machine", "fsm"),
    }.get(field, ())
    hits = [s for s in _sentences(text) if any(k in s.lower() for k in keys)]
    return "\n".join(hits) if hits else text.strip()[:600]


def confirm_contract(contract, spec_text: str,
                     client_factory: Optional[Callable[[], Any]] = None,
                     model: Optional[str] = None) -> List[Confirmation]:
    """LLM-confirm every semantic field present on `contract`, mutating it in place to the
    confirmed value. Returns the list of Confirmation records (for manifest / provenance).
    Only prose-derived contracts are confirmed — JSON contracts are authoritative."""
    confs: List[Confirmation] = []
    if getattr(contract, "source", "") == "json":
        return confs
    for field in _SEMANTIC_FIELDS:
        candidate = getattr(contract, field, None)
        if candidate is None:
            continue  # nothing declared → nothing to confirm
        c = confirm_semantic(field, candidate, evidence_for(field, spec_text),
                             client_factory=client_factory, model=model)
        if c.confirmed and c.value != candidate:
            setattr(contract, field, c.value)  # adopt the LLM correction
        confs.append(c)
    return confs


def manifest(confs: List[Confirmation]) -> List[dict]:
    return [asdict(c) for c in confs]
