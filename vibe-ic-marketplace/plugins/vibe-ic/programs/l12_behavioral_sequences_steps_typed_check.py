#!/usr/bin/env python3
"""
l12_behavioral_sequences_steps_typed_check.py — Wave 38 / B6

Audit item (PHASE2A_FULL_AUDIT_v0119.67.md, line 29 + line 75):
behavioral sequences (wake handshake step-by-step, engineer-mode
entry sequence, factory-test entry) usually live as a free-form
``description`` paragraph in L12 / L11 instead of a typed
``steps[]`` array. spec-to-rtl cannot replay a paragraph; it
needs an ordered list of (action, expected_signal, latency)
tuples.

Trigger: L12_BEHAVIORAL_SEQUENCES.json has a ``sequences[]``
(or alias) array.

Required typed shape: each sequence entry MUST have:
  - ``name`` / ``id``
  - ``steps`` (list of dicts) with each step having
    ``action`` (string) and at least one of
    {``expected_signal``, ``latency_us``, ``next_state``,
    ``check``}.
  - ``trigger`` (the entry condition / opcode / handshake start)
    OR ``entry`` / ``initiator``.

The gate is chip-AGNOSTIC: schema-only.

Usage:
    python3 l12_behavioral_sequences_steps_typed_check.py <project_dir>

Exit codes:
    0 = PASS (no sequences OR each has typed steps[])
    1 = FAIL (sequences exist but lack typed steps)
    2 = input-missing (skip)

Honors waiver ``l12_behavioral_sequences_intentional_prose`` (>=40
chars).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ic_class_profile import detect_ic_class  # noqa: E402


# Wave 43 (v0.119.75) — explicit ic_class_profile guard.
# Typed behavioral_sequences[].steps[] is required for protocol-
# driven ICs (digital_cmd_driven / aid_class_half_duplex /
# mixed_signal_otp). Pure-analog parts have no behavioural protocol
# to replay, only DC operating-point sweeps from A1-A8.
_SKIP_CLASSES = ("pure_analog",)


_L12_GLOBS = (
    "phase1/generated_docs/L12_BEHAVIORAL_SEQUENCES.json",
    "phase1/generated_docs/L12*.json",
    "**/L12_BEHAVIORAL_SEQUENCES.json",
)

_SEQ_KEYS = ("sequences", "behavioral_sequences", "scenarios",
             "flows", "handshakes", "behavioral_flows",
             "test_sequences")

_STEP_KEYS = ("steps", "phases", "stages", "transitions",
              "actions", "sequence_steps")

_STEP_DETAIL_KEYS = ("expected_signal", "latency_us", "latency_ms",
                     "next_state", "check", "wait_for", "duration_us",
                     "duration_ms", "expected", "expected_response",
                     "after", "before", "timing")

_TRIGGER_KEYS = ("trigger", "entry", "initiator", "start_condition",
                 "entry_condition", "preconditions",
                 "entry_sequence", "entry_pattern")

_NAME_KEYS = ("name", "id", "scenario", "sequence", "title")


def _find_l12(project: Path) -> Optional[Path]:
    for pat in _L12_GLOBS:
        for hit in project.glob(pat):
            if hit.is_file():
                return hit
    return None


def _collect_sequences(node, out: List[dict]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k in _SEQ_KEYS and isinstance(v, list):
                for it in v:
                    if isinstance(it, dict):
                        out.append(it)
            else:
                _collect_sequences(v, out)
    elif isinstance(node, list):
        for it in node:
            _collect_sequences(it, out)


def _has_steps(seq: dict) -> Optional[list]:
    for k in _STEP_KEYS:
        v = seq.get(k)
        if isinstance(v, list) and v:
            return v
    return None


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: l12_behavioral_sequences_steps_typed_check "
              "<project_dir>", file=sys.stderr)
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        return 2

    profile = detect_ic_class(project)
    ic_class = profile.get("ic_class", "unknown")
    if ic_class in _SKIP_CLASSES:
        print(f"[SKIP] l12_behavioral_sequences_steps_typed_check: "
              f"ic_class={ic_class} (pure-analog parts have no "
              f"behavioural protocol; only DC sweeps in A1-A8)")
        return 2

    l12 = _find_l12(project)
    if l12 is None:
        print("[SKIP] l12_behavioral_sequences_steps_typed_check: "
              "L12_BEHAVIORAL_SEQUENCES.json not found")
        return 2

    try:
        data = json.loads(l12.read_text())
    except Exception as exc:
        print(f"[FAIL] l12_behavioral_sequences_steps_typed_check: "
              f"cannot parse {l12.relative_to(project)}: {exc}")
        return 1

    seqs: List[dict] = []
    _collect_sequences(data, seqs)
    if not seqs:
        print("[SKIP] l12_behavioral_sequences_steps_typed_check: "
              "no sequences[]/scenarios[] array in L12")
        return 2

    bad: List[str] = []
    for i, s in enumerate(seqs):
        label = (s.get("name") or s.get("id")
                 or s.get("scenario") or f"seq[{i}]")
        if not any(k in s for k in _NAME_KEYS):
            bad.append(f"{label}: missing name/id")
        steps = _has_steps(s)
        if steps is None:
            bad.append(f"{label}: missing typed steps[] array")
            continue
        # validate at least one step has detail key
        step_detail_count = 0
        for st in steps:
            if isinstance(st, dict) and (
                "action" in st or "step" in st or "do" in st
            ):
                if any(k in st for k in _STEP_DETAIL_KEYS):
                    step_detail_count += 1
        if step_detail_count == 0:
            bad.append(
                f"{label}: steps[] has no step with action+"
                f"expected_signal/latency_us/next_state typed details"
            )
        if not any(k in s for k in _TRIGGER_KEYS):
            bad.append(f"{label}: missing trigger/entry/entry_sequence")

    if bad:
        print(f"[FAIL] l12_behavioral_sequences_steps_typed_check: "
              f"{len(bad)} issue(s) across {len(seqs)} sequences. "
              f"Examples: {'; '.join(bad[:5])}")
        return 1

    print(f"[PASS] l12_behavioral_sequences_steps_typed_check: "
          f"{len(seqs)} sequences with typed steps[] + trigger")
    return 0


if __name__ == "__main__":
    sys.exit(main())
