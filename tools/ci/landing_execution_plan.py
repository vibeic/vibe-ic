#!/usr/bin/env python3
"""Approved landing execution declaration, shared by dispatcher and completion.

This is runtime authority, not candidate evidence or a new gate. The controller
must include this file in its approved runtime tuple. Unit bodies live in
gatekeeper-land.sh; this declaration determines which bodies execute and their
order. Missing/duplicate/unexpected execution is BLOCKING in the existing
completion path. No CLI input can replace this population.
"""
from __future__ import annotations

import hashlib
import json
import shlex
import sys


# (unit, execution phase, concurrent lane). Serial phases have no lane.
STEPS = (
    ("cheap:nda-messages", "cheap", ""),
    ("cheap:nda-content", "cheap", ""),
    ("cheap:version", "cheap", ""),
    ("cheap:agent-scope", "cheap", ""),
    ("cheap:benchmark-structure", "cheap", ""),
    ("cheap:git-prohibition", "cheap", ""),
    ("cheap:prose-polarity", "cheap", ""),
    ("cheap:nested-progress-pin", "cheap", ""),
    ("cheap:competing-claims-report", "cheap", ""),
    ("cheap:worktree-clean", "cheap", ""),
    ("cheap:scratch-report", "cheap", ""),
    ("cheap:hygiene-ratchet", "cheap", ""),
    ("full:write-guard-baseline", "before_window", ""),
    ("full:targeted-tests", "window", "targeted"),
    ("full:repo-tools-tests", "window", "corpus"),
    ("full:unselectable-tests", "window", "corpus"),
    ("full:census-freshness", "window", "corpus"),
    ("full:repo-hygiene", "window", "hygiene"),
    ("full:gatekeeper-review", "after_window", ""),
    ("full:write-guard-final", "after_window", ""),
    ("full:worktree-fingerprint-final", "after_window", ""),
    ("full:completion-record", "after_window", ""),
)
UNITS = tuple(row[0] for row in STEPS)
WINDOW_UNITS = tuple(unit for unit, phase, _ in STEPS if phase == "window")
LANES = tuple(dict.fromkeys(lane for _, _, lane in STEPS if lane))
PLAN_SHA256 = hashlib.sha256(json.dumps(
    {"schema": 1, "steps": STEPS}, sort_keys=True,
    separators=(",", ":")).encode("utf-8")).hexdigest()


def shell() -> str:
    """Render fixed, quoted Bash declarations; accepts no subject inputs."""
    q = shlex.quote
    lines = [f"readonly LANDING_PLAN_SHA256={q(PLAN_SHA256)}"]
    for name, values in (("LANDING_PLAN_UNITS", UNITS),
                         ("LANE_WINDOW_UNITS", WINDOW_UNITS),
                         ("LANDING_PLAN_LANES", LANES)):
        lines.append(f"declare -ar {name}=(" + " ".join(map(q, values)) + ")")
    for name, index in (("PHASE", 1), ("LANE", 2)):
        lines.append(f"declare -Ar LANDING_PLAN_{name}=(" + " ".join(
            f"[{q(row[0])}]={q(row[index])}" for row in STEPS) + ")")
    return "\n".join(lines)


if __name__ == "__main__":
    if sys.argv[1:] != ["shell"]:
        raise SystemExit("usage: landing_execution_plan.py shell")
    print(shell())
