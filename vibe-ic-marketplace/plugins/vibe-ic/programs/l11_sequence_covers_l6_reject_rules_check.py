#!/usr/bin/env python3
"""l11_sequence_covers_l6_reject_rules_check.py — Wave 39 / D2

Spec to enforce (chip-AGNOSTIC):

Every L6.reject_rules[] entry MUST have at least one corresponding
behavioral_sequence in L11 OR L12 that exercises the rejection
pathway (negative test sequence — DUT silent / no response /
discard).

Detection:
  1. Parse L6.reject_rules[] -> set of rule {condition, name}.
  2. Parse L11.behavioral_sequences[] AND L12.behavioral_sequences[]
     (or L12.sequences[]).
  3. For each rule, search any sequence whose `expected_behavior` /
     `expect` field is dut_silent / no_response / discard / drop /
     silent / reject AND whose condition / steps text mentions a
     keyword from the rule condition (chip-AGNOSTIC substring).
  4. FAIL when any rule lacks coverage.

Honors waiver `l11_reject_rule_coverage_partial_intentional` (>=40).

Usage:
    python3 l11_sequence_covers_l6_reject_rules_check.py <project_dir>
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

WAIVER_KEY = "l11_reject_rule_coverage_partial_intentional"
WAIVER_MIN = 40


def _waived(project: Path) -> tuple[bool, str]:
    p = project / "waivers.json"
    if not p.exists():
        return False, ""
    try:
        d = json.loads(p.read_text())
        v = d.get(WAIVER_KEY)
        if isinstance(v, str) and len(v.strip()) >= WAIVER_MIN:
            return True, v.strip()
    except Exception:
        pass
    return False, ""


def _find_doc(project: Path, prefix: str) -> Optional[Path]:
    for pat in (f"phase1/generated_docs/{prefix}_*.json",
                f"phase1/generated_docs/{prefix}*.json",
                f"**/{prefix}*.json"):
        for h in project.glob(pat):
            if h.is_file():
                return h
    return None


_SILENT_TOKENS = (
    "dut_silent", "no_response", "expect_silent", "discard",
    "drop", "silent", "rejected", "reject", "no_reply", "expect_drop",
    "expect_no_response",
    # Wave 43 (v0.119.75) — synonym extension. Any of these tokens in
    # the JSON-serialised L11/L12 sequence body classify it as a
    # "silent / negative-coverage" sequence.
    "abort", "cancel", "ignore", "ignored", "timeout",
    "tx_silent", "no_tx", "stay_idle", "stay_silent",
    # Traditional Chinese synonyms — chip-AGNOSTIC behavioural verbs.
    "靜音", "丟棄", "忽略", "拒絕", "中止", "不回應", "無回應",
)


# Wave 43 (v0.119.75) — canonical reject-rule -> synonym table.
# Maps each canonical reject-rule concept to a list of substring
# tokens (chip-AGNOSTIC) that may appear in an L11/L12 sequence's
# `name`, `trigger`, or `condition` field. Glob `*` is treated as
# "match any non-empty suffix" — collapsed to substring matching
# of the rule prefix at scan time.
_REJECT_RULE_NORMALIZATION: dict[str, list[str]] = {
    # CRC family
    "crc_mismatch": [
        "crc_mismatch", "crc_error", "crc_invalid",
        "checksum_fail", "checksum_mismatch", "checksum_error",
        "bad_crc", "wrong_crc",
    ],
    # Pre-wake-required family — opcode arrives before awake_latch.
    "pre_wake_*": [
        "pre_wake", "before_wake", "not_awake",
        "wake_required", "awake_latch", "wake_gating",
        "no_wake_yet", "pre-wake",
    ],
    # Bit-count / 9-bit / framing family.
    "bit_count_*": [
        "bit_count", "bit_misalign", "ninth_bit",
        "byte_overflow", "extra_bit", "9_bit", "9-bit",
        "9bit", "frame_bit_overflow", "bit_idx_overflow",
    ],
    # Frame / IBT / RX timeout family.
    "frame_timeout": [
        "frame_timeout", "ibt_timeout", "rx_timeout",
        "frame_abort", "frame_break", "tof_timeout",
        "inter_byte_timeout", "ibt_expire",
    ],
    # Address-out-of-range family.
    "addr_out_of_range": [
        "addr_out_of_range", "addr_overflow", "address_invalid",
        "addr_too_large", "addr_too_high", "addr_exceed",
        "address_overflow", "addr_oob",
    ],
    # Length-out-of-range family.
    "len_out_of_range": [
        "len_out_of_range", "length_overflow", "size_too_large",
        "len_too_large", "len_overflow", "len_exceed",
        "length_invalid", "len_oob",
    ],
    # layergate-2 — TARGET-NOT-READY family. A transaction rejected
    # because the target cannot accept it right now (busy / not ready /
    # backpressured / FIFO full) is one of the most common reject-rule
    # concepts in a command-driven or bus-attached IC, and the table had
    # no entry for it: such a rule produced ZERO keywords, which sent
    # this gate down its `if not kws` branch and made the coverage check
    # vacuous for that rule. Found by
    # l6_fsm_scaffold_actionable_check, which asserts that every L6
    # reject_rule is machine-matchable by THIS extractor — the gate
    # measured the vocabulary gap rather than blaming the layer.
    # chip-AGNOSTIC: pure protocol-state vocabulary, no design tokens.
    "target_not_ready": [
        "target_not_ready", "not_ready", "notready", "busy",
        "core_busy", "device_busy", "backpressure", "back_pressure",
        "fifo_full", "buffer_full", "queue_full", "overrun",
        "nak", "nack", "retry", "stall", "wait_state",
        "write_while_busy", "req_while_busy",
    ],
}


def _gather_sequences(project: Path) -> List[dict]:
    seqs: List[dict] = []
    for prefix in ("L11", "L12"):
        p = _find_doc(project, prefix)
        if p is None:
            continue
        try:
            d = json.loads(p.read_text())
        except Exception:
            continue
        for k in ("behavioral_sequences", "sequences"):
            v = d.get(k)
            if isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        seqs.append(item)
    return seqs


def _seq_is_silent(seq: dict) -> bool:
    blob = json.dumps(seq, ensure_ascii=False).lower()
    return any(tok in blob for tok in _SILENT_TOKENS)


def _rule_keywords(rule: dict) -> List[str]:
    """Extract chip-AGNOSTIC keyword tokens from a reject rule.

    Wave 43 (v0.119.75): consult `_REJECT_RULE_NORMALIZATION` to
    resolve a rule's canonical concept to its synonym list. This
    closes the residual narrow-keyword false-FAILs surfaced by the
    audit (e.g. an L11 sequence calling itself ``checksum_fail`` was
    not recognised as covering an L6 ``crc_mismatch`` rule).
    """
    text = " ".join(
        (rule.get(k) or "") for k in
        ("condition", "name", "trigger", "rule", "description")
    ).lower()
    toks: List[str] = []
    # Legacy direct substring tokens — preserved for backward compat.
    for tok in ("br", "9-bit", "9 bit", "nine", "bit count",
                "odd opcode", "even opcode", "crc",
                "awake", "pre-wake", "pre wake", "pre_wake",
                "len", "length", "addr", "address", "out of range",
                "ibt", "framing", "timeout", "invalid"):
        if tok in text:
            toks.append(tok)
    # Wave 43 — canonical-concept lookup.
    for canonical, synonyms in _REJECT_RULE_NORMALIZATION.items():
        # An L6 rule matches this canonical concept iff at least
        # one synonym (or the canonical name itself, glob-stripped)
        # appears in any of (condition / name / trigger / rule /
        # description).
        canonical_prefix = canonical.replace("*", "").rstrip("_")
        all_probes = [canonical_prefix] + list(synonyms)
        for probe in all_probes:
            probe_norm = probe.replace("*", "").rstrip("_").lower()
            if probe_norm and probe_norm in text:
                toks.extend(s.lower() for s in synonyms)
                # Also expose the canonical-prefix to the matcher so
                # an L11 sequence carrying the canonical name itself
                # is recognised.
                if canonical_prefix:
                    toks.append(canonical_prefix.lower())
                break
    # De-duplicate while preserving order.
    seen: set[str] = set()
    out: List[str] = []
    for t in toks:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: l11_sequence_covers_l6_reject_rules_check "
              "<project_dir>", file=sys.stderr)
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        return 2

    waiver_ok, waiver_text = _waived(project)

    l6p = _find_doc(project, "L6")
    if l6p is None:
        print("[SKIP] l11_sequence_covers_l6_reject_rules_check: "
              "no L6 file")
        return 2
    try:
        l6 = json.loads(l6p.read_text())
    except Exception as exc:
        print(f"[FAIL] l11_sequence_covers_l6_reject_rules_check: "
              f"parse L6: {exc}")
        return 1

    rules = l6.get("reject_rules") or l6.get("rx_reject_rules") or []
    rules = [r for r in rules if isinstance(r, dict)]
    if not rules:
        print("[SKIP] l11_sequence_covers_l6_reject_rules_check: "
              "no L6.reject_rules to check")
        return 2

    seqs = _gather_sequences(project)
    silent_seqs = [s for s in seqs if _seq_is_silent(s)]

    issues: List[str] = []
    for rule in rules:
        kws = _rule_keywords(rule)
        if not kws:
            # generic rule — accept any silent sequence
            if not silent_seqs:
                issues.append(
                    f"rule '{rule.get('condition','?')[:60]}' "
                    f"has no covering silent sequence")
            continue
        # Find a silent sequence mentioning >=1 keyword.
        matched = False
        for s in silent_seqs:
            blob = json.dumps(s, ensure_ascii=False).lower()
            if any(kw in blob for kw in kws):
                matched = True
                break
        if not matched:
            issues.append(
                f"rule '{rule.get('condition','?')[:60]}' "
                f"(keywords {kws[:3]}) — no silent sequence "
                f"in L11/L12 covers it")

    if issues:
        msg = (f"[FAIL] l11_sequence_covers_l6_reject_rules_check: "
               f"{len(issues)}/{len(rules)} reject_rule(s) lack "
               f"L11/L12 silent-sequence coverage:\n  - " +
               "\n  - ".join(issues[:6]))
        if waiver_ok:
            print(f"[PASS] l11_sequence_covers_l6_reject_rules_check: "
                  f"waived ({WAIVER_KEY}; {len(issues)} suppressed)")
            return 0
        print(msg)
        return 1

    print(f"[PASS] l11_sequence_covers_l6_reject_rules_check: "
          f"{len(rules)} reject_rule(s) covered by "
          f"{len(silent_seqs)} silent-sequence(s) across L11/L12")
    return 0


if __name__ == "__main__":
    sys.exit(main())
