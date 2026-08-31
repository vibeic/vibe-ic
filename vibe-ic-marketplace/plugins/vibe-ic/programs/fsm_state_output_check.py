#!/usr/bin/env python3
"""Prompt-derived FSM state-output and generated-strobe timing check.

Issue #1950 captured two related, chip-agnostic protocol timing contracts:

* when prose explicitly says a one-cycle output is asserted in/during a NAMED
  state, that state owns the output.  A pulse stored in the transition arm that
  enters the state is not ownership; NBA scheduling can make an edge-sampling
  observer see it one phase late.  The deterministic form is a Moore decode of
  CURRENT state, which also provides the required default deassertion outside
  the owner state;
* when a generated strobe/clock edge makes data or status externally observable,
  those signals must be prepared before the edge.  Updating them with
  nonblocking assignments in the same state arm that raises/toggles the strobe
  is observably late/racy; use a PREPARE state/cycle before the STROBE state.

The checker reads only the prompt and candidate RTL.  It is intentionally
under-flagging: an output contract is admitted only by spec_fsm_extract's
explicit named-state/one-cycle grammar, and a finding is emitted only when a
clocked state arm structurally proves the conflicting transition/strobe shape.
Unparseable or ambiguous code SKIPs rather than guessing (§4.05 no-leak).

CLI:
    python3 fsm_state_output_check.py --rtl dut.sv --spec prompt.txt [--json]

Exit codes: 0 = PASS / not applicable, 1 = finding, 2 = input error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from fsm_transition_completeness_check import (  # single-source RTL grammar
    _split_case_arms,
    _strip_comments,
    parse_states,
)
import spec_fsm_extract


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str
    signal: str
    state: str
    message: str


_CASE_RE = re.compile(
    r"\bcase\s*\(\s*([A-Za-z_]\w*)\s*\)\s*(.*?)\bendcase\b",
    re.DOTALL,
)
_ASSIGN_RE = re.compile(
    r"\b([A-Za-z_]\w*)\s*(<=|(?<![<>=!])=(?!=))\s*([^;]+);",
    re.DOTALL,
)
_ONE_RE = re.compile(r"^\s*(?:1|1\s*'\s*[bBdDhH]\s*1|'\s*1)\s*$")
_ZERO_RE = re.compile(r"^\s*(?:0|1\s*'\s*[bBdDhH]\s*0|'\s*0)\s*$")


def _clocked_before(body: str, case_start: int) -> bool:
    """Whether the nearest enclosing always header before a case is edge-based."""
    aidx = max(body.rfind("always", 0, case_start),
               body.rfind("always_ff", 0, case_start))
    if aidx < 0:
        return False
    header = body[aidx:case_start]
    # A completed earlier always/end region is not the owner of this case.
    if re.search(r"\bend\b", header) and "begin" not in header:
        return False
    return bool(re.search(r"@\s*\([^)]*\b(?:posedge|negedge)\b", header))


def _state_aliases(prompt_state: str, declared: Sequence[str]) -> Set[str]:
    """RTL state constants that unambiguously spell a prompt state.

    Direct case-insensitive equality and conventional S_/ST_/STATE_ prefixes are
    admitted.  A generic substring is not: ``DONE`` must not match
    ``NOT_DONE_YET``.
    """
    target = prompt_state.lower()
    out: Set[str] = set()
    for name in declared:
        low = name.lower()
        stripped = re.sub(r"^(?:s|st|state)_", "", low)
        if low == target or stripped == target:
            out.add(name)
    return out or {prompt_state}


def _arm_assignments(arm: str, signal: Optional[str] = None):
    for m in _ASSIGN_RE.finditer(arm):
        if signal is None or m.group(1) == signal:
            yield m.group(1), m.group(2), m.group(3).strip()


def _continuous_owner_decode(body: str, signal: str,
                             owners: Set[str]) -> bool:
    """True for ``assign signal = state == OWNER [|| ...]``.

    Requiring a real equality against an owner (not merely the owner token in a
    comment/ternary) is what makes default deassertion structural: equality is
    false everywhere outside the owner state.
    """
    for m in re.finditer(
            rf"\bassign\s+{re.escape(signal)}\s*=\s*([^;]+);", body,
            re.DOTALL):
        expr = m.group(1)
        for owner in owners:
            if re.search(
                    rf"(?:\b[A-Za-z_]\w*\b\s*==\s*\b{re.escape(owner)}\b|"
                    rf"\b{re.escape(owner)}\b\s*==\s*\b[A-Za-z_]\w*\b)",
                    expr):
                return True
    return False


def _state_output_findings(body: str, prompt_text: str) -> Tuple[List[Finding], int]:
    contracts = [item for item in spec_fsm_extract.extract(prompt_text)
                 if item.get("kind") == "fsm_state_output"]
    if not contracts:
        return [], 0

    declared = parse_states(body)
    cases = list(_CASE_RE.finditer(body))
    findings: List[Finding] = []
    checked = 0
    for contract in contracts:
        signal = str(contract.get("signal") or "")
        state = str(contract.get("state") or "")
        if not signal or not state:
            continue
        # The candidate must actually expose/assign the prompt signal before a
        # structural ownership verdict is possible.  Missing-port coverage is
        # owned by the interface gate; do not duplicate it here.
        if not re.search(rf"\b{re.escape(signal)}\b", body):
            continue
        checked += 1
        owners = _state_aliases(state, declared)
        if _continuous_owner_decode(body, signal, owners):
            continue

        # High-confidence defect: a CLOCKED source-state arm asserts the pulse
        # and assigns a state variable to the named owner in that same arm.  This
        # proves the pulse is owned by the TRANSITION, not by the destination
        # state.  Other sequential shapes remain under-flagged rather than
        # guessed.
        found = False
        for cm in cases:
            if not _clocked_before(body, cm.start()):
                continue
            for label, arm in _split_case_arms(cm.group(2)):
                labels = {part.strip() for part in label.split(",")}
                if labels & owners:
                    continue
                active = any(_ONE_RE.fullmatch(rhs)
                             for _lhs, _op, rhs in _arm_assignments(arm, signal))
                if not active:
                    continue
                enters_owner = any(
                    rhs in owners
                    and re.search(r"state", lhs, re.IGNORECASE)
                    for lhs, _op, rhs in _arm_assignments(arm))
                if not enters_owner:
                    continue
                findings.append(Finding(
                    "fsm-state-output-transition-owned", "ERROR", signal, state,
                    f"output {signal!r} is asserted in transition arm {label!r} "
                    f"that enters {state!r}; drive it from CURRENT state "
                    f"{state!r} with default deassertion outside that state, "
                    "then sample before entry, the owned cycle, and the "
                    "following cycle."))
                found = True
                break
            if found:
                break
    return findings, checked


def _quoted_names(text: str) -> List[str]:
    return list(dict.fromkeys(re.findall(r"`([A-Za-z_]\w*)`", text)))


def _strobe_contracts(prompt_text: str) -> Dict[str, Set[str]]:
    """Return generated-strobe -> externally sampled data/status identifiers.

    Three explicit prompt forms are admitted: ``sample X on rising edge of S``,
    ``toggle S to latch X externally``, and ``X must be stable before ... S``.
    All identifiers must be backtick-quoted.  The grammar is structural and
    chip-agnostic; a vague mention of a clock or data does not create a contract.
    """
    out: Dict[str, Set[str]] = {}

    sampled = re.compile(
        r"(?:external(?:ly)?\s+(?:logic|observer|device)?\s*)?"
        r"(?:samples?|latches?|captures?)\s+(.{1,180}?)\s+on\s+(?:the\s+)?"
        r"(?:observable\s+)?rising\s+edge\s+of\s+`([A-Za-z_]\w*)`",
        re.IGNORECASE | re.DOTALL,
    )
    for m in sampled.finditer(prompt_text or ""):
        strobe = m.group(2)
        names = [n for n in _quoted_names(m.group(1)) if n != strobe]
        if names:
            out.setdefault(strobe, set()).update(names)

    toggle = re.compile(
        r"\b(?:toggle|raise|assert)\s+`([A-Za-z_]\w*)`\s+"
        r"(?:[^.;\n]{0,50}?\s+)?to\s+(?:latch|sample|capture)\s+"
        r"([^.;\n]{1,220})",
        re.IGNORECASE,
    )
    for m in toggle.finditer(prompt_text or ""):
        strobe = m.group(1)
        names = [n for n in _quoted_names(m.group(2)) if n != strobe]
        if names:
            out.setdefault(strobe, set()).update(names)

    stable = re.compile(
        r"((?:`[A-Za-z_]\w*`(?:\s*(?:,|and)\s*)?){1,})\s+"
        r"must\s+be\s+stable\s+before\s+(?:the\s+)?(?:observable\s+)?"
        r"(?:rising\s+)?edge\s+of\s+`([A-Za-z_]\w*)`",
        re.IGNORECASE,
    )
    for m in stable.finditer(prompt_text or ""):
        strobe = m.group(2)
        names = [n for n in _quoted_names(m.group(1)) if n != strobe]
        if names:
            out.setdefault(strobe, set()).update(names)
    return out


def _is_strobe_raise(rhs: str, signal: str) -> bool:
    compact = re.sub(r"\s+", "", rhs)
    return bool(_ONE_RE.fullmatch(rhs) or compact in {
        "~" + signal, "!" + signal,
    })


def _strobe_findings(body: str, prompt_text: str) -> Tuple[List[Finding], int]:
    contracts = _strobe_contracts(prompt_text)
    if not contracts:
        return [], 0
    cases = list(_CASE_RE.finditer(body))
    findings: List[Finding] = []
    checked = 0
    seen: Set[Tuple[str, str, str]] = set()
    for strobe, observed in contracts.items():
        if not re.search(rf"\b{re.escape(strobe)}\b", body):
            continue
        checked += 1
        for cm in cases:
            if not _clocked_before(body, cm.start()):
                continue
            for label, arm in _split_case_arms(cm.group(2)):
                strobe_rises = any(
                    op == "<=" and _is_strobe_raise(rhs, strobe)
                    for _lhs, op, rhs in _arm_assignments(arm, strobe))
                if not strobe_rises:
                    continue
                for signal in sorted(observed):
                    same_nba = any(op == "<="
                                   for _lhs, op, _rhs
                                   in _arm_assignments(arm, signal))
                    key = (strobe, signal, label)
                    if not same_nba or key in seen:
                        continue
                    seen.add(key)
                    findings.append(Finding(
                        "generated-strobe-data-not-prepared", "ERROR", signal,
                        label,
                        f"{signal!r} is updated by NBA in the same state arm "
                        f"{label!r} that raises generated strobe {strobe!r}; "
                        "prepare data/status in an earlier state or cycle so it "
                        "is stable before the observable rising edge."))
    return findings, checked


def check_text(rtl_text: str, prompt_text: str) -> Tuple[List[Finding], str]:
    """Check candidate RTL against explicit prompt-derived timing contracts."""
    if not (rtl_text or "").strip() or not (prompt_text or "").strip():
        return [], "SKIP-missing-input"
    body = _strip_comments(rtl_text)
    state_findings, state_checked = _state_output_findings(body, prompt_text)
    strobe_findings, strobe_checked = _strobe_findings(body, prompt_text)
    if state_checked + strobe_checked == 0:
        return [], "SKIP-no-contract"
    return state_findings + strobe_findings, "CHECKED"


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rtl", required=True)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        rtl = Path(args.rtl).read_text(errors="replace")
        spec = Path(args.spec).read_text(errors="replace")
    except OSError as exc:
        print(f"fsm_state_output_check: input error: {exc}", file=sys.stderr)
        return 2
    findings, status = check_text(rtl, spec)
    if args.json:
        print(json.dumps({"status": status,
                          "findings": [asdict(f) for f in findings]}, indent=2))
    else:
        verdict = "FAIL" if findings else "PASS"
        print(f"fsm_state_output_check: {verdict} ({status}) — "
              f"{len(findings)} finding(s)")
        for finding in findings:
            print(f"  [{finding.severity}] {finding.rule}: {finding.message}")
    return 1 if any(f.severity == "ERROR" for f in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
