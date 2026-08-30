#!/usr/bin/env python3
"""The outer landing arm must not expire before an inner gate can answer."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "tools" / "gatekeeper-verify-merge.sh"
LAND = ROOT / "tools" / "gatekeeper-land.sh"


def _integer_assignment(text: str, name: str) -> int:
    match = re.search(rf"^{re.escape(name)}=(\d+)$", text, re.MULTILINE)
    assert match, f"{name} is not one literal integer assignment"
    return int(match.group(1))


def _integer_environment_default(text: str, name: str) -> int:
    match = re.search(
        rf'^{re.escape(name)}="\$\{{[A-Za-z_][A-Za-z0-9_]*:-(\d+)\}}"$',
        text,
        re.MULTILINE,
    )
    assert match, f"{name} is not one bounded integer environment default"
    return int(match.group(1))


def test_landing_arm_lease_encloses_the_longest_inner_no_verdict_budget():
    verify = VERIFY.read_text(encoding="utf-8")
    land = LAND.read_text(encoding="utf-8")
    outer = _integer_assignment(
        verify, "LANDING_ARM_SEMANTIC_STALL_GRACE")
    review = _integer_environment_default(land, "GK_REVIEW_BUDGET_S")

    # The parent starts its lease before the inner instrument and must leave
    # time for the latter's bounded shutdown and terminal receipt publication.
    # A smaller outer value turns a healthy long-running gate into NORECORD at
    # the parent even though the inner gate has not exhausted its own budget.
    assert outer >= review + 30


def test_landing_arm_silence_lease_is_not_the_old_300_second_value():
    verify = VERIFY.read_text(encoding="utf-8")
    assert _integer_assignment(
        verify, "LANDING_ARM_SEMANTIC_STALL_GRACE") > 300
    assert "expiry remains NORECORD" in verify
