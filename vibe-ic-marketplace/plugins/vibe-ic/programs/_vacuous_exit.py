#!/usr/bin/env python3
"""Route a gate's exit code from the gate's OWN structured conclusion (#515).

WHY THIS MODULE EXISTS
======================
``flow_compliance_check`` defines a three-way exit-code convention and builds a
whole verdict tier on top of it:

    rc 0 -> PASS            the gate examined the design and found it correct
    rc 1 -> FAIL            the gate examined the design and found a violation
    rc 2 -> VACUOUS_PASS    the gate examined NOTHING — the artefact it audits
                            does not exist / does not apply to this project

Membership of the vacuous tier is decided **purely by the exit code** — by
``_run_structural_rtl_gates`` (rc 2 -> a ``SKIP`` gate record with
``skip_kind: input-missing``) and by ``_check_program_exit_zero`` (rc 2 -> the
``__VACUOUS_HINT__`` prefix that promotes the step to ``VACUOUS_PASS``).

Measured at v1.7.77, five gates announced a skip in their own stdout and exited
0 anyway, so they were credited in the plain PASS tier — indistinguishable, to
every automated consumer, from a gate that examined the design and found it
correct. Four other gates in the same tree (``analog_flow_compliance_check``,
``analog_netlist_include_order_check``, ``mixed_signal_cosim_check``,
``assertion_covers_l3_constraints_check``) already exited 2 for the identical
situation. Both conventions were live at once.

WHAT THIS MODULE IS, AND WHAT IT DELIBERATELY IS NOT
====================================================
It is a router from a gate's already-computed structured result to an exit
code. Every one of those gates ALREADY knew it had skipped — they set
``summary["skipped"] = True`` (or a top-level ``skipped`` key) and then never
read it back. The fix is to read it.

It is NOT a text classifier. Deciding the tier by grepping a gate's stdout for
the word "SKIP" would be the same defect one layer up: a verdict derived from
prose rather than from the conclusion the gate actually reached. Nothing here
looks at any message. ``announce_vacuous`` WRITES a line; no function READS one.

THE SENTINEL GOES TO STDERR
===========================
``announce_vacuous`` emits the ``VACUOUS_PASS:`` token
``flow_compliance_check._stdout_signals_vacuous`` matches at line start, as a
second, rc-INDEPENDENT disclosure channel (the same shape
``analog_flow_compliance_check`` and ``si_mcf_sta_check`` use). It is written to
**stderr** for a concrete reason: these gates support ``--json -``, which puts
the report document on stdout, and a sentinel line mixed into that stream would
make the document unparseable. ``_check_program_exit_zero`` concatenates stdout
and stderr before scanning, so the token is found either way.

FAIL BEATS VACUOUS
==================
``exit_code`` reports rc 1 whenever the gate did not pass, even if the result
also carries ``skipped``. A gate cannot both have found a violation and have
examined nothing; if the two flags ever disagree, surfacing the violation is
the only safe direction. Silencing a real finding behind a skip is the failure
mode this whole convention exists to prevent.

rc 3 IS NOT OURS
================
rc 3 is ``PASS_WITH_WAIVERS`` (#651) and is honoured only together with a
matching ``PASS_WITH_WAIVERS`` stdout sentinel. ``exit_code`` never returns 3
and nothing here emits that sentinel, so the two conventions cannot collide.

#521 ADDED THE MISSING SHARED SITE, AND WHY
===========================================
``gate_discloses_denominator_check`` recorded, with a measurement, that
fourteen analog / SPICE gates answered a bare ``[PASS] <gate>`` over a project
with nothing in it, and that "there is no shared site to fix": each one
carried its OWN inline ``print(f"[{status}] <name>")``, so the convention was
COPIED fifteen times rather than shared once. ``verdict_line`` is that site.
It renders the same three-way conclusion ``exit_code`` routes, from the SAME
two booleans, so a gate cannot print one verdict and exit with another — which
is the drift that let a skip be announced in prose and credited as a pass.

It still cannot INVENT a denominator: what each gate examined is per-gate work.
What it CAN do, and does, is refuse to render a bare ``PASS`` for a result the
gate itself marked skipped, and name the gate's own reason token when it does.
"""
from __future__ import annotations

import sys
from typing import Any, Optional, TextIO

__all__ = [
    "RC_PASS",
    "RC_FAIL",
    "RC_VACUOUS",
    "VACUOUS_STDOUT_SENTINEL",
    "exit_code",
    "summary_is_skipped",
    "skip_reason",
    "verdict_line",
    "announce_vacuous",
]

RC_PASS, RC_FAIL, RC_VACUOUS = 0, 1, 2

#: Line-start token ``flow_compliance_check._stdout_signals_vacuous`` matches.
VACUOUS_STDOUT_SENTINEL = "VACUOUS_PASS:"


def exit_code(passed: bool, skipped: bool) -> int:
    """Map a gate's own (passed, skipped) conclusion onto the rc convention.

    ``passed`` is the gate's verdict; ``skipped`` is the gate's own statement
    that it had nothing to examine. FAIL wins over VACUOUS — see module
    docstring.
    """
    if not passed:
        return RC_FAIL
    return RC_VACUOUS if skipped else RC_PASS


def summary_is_skipped(summary: Any) -> bool:
    """True iff a gate's ``summary`` dict self-reports the vacuous case.

    Tolerant of a missing / non-dict summary so a gate that has not populated
    it yet is treated as "examined something" (never as a silent skip) — the
    fail-safe direction for a helper that can only ever REMOVE a plain PASS.
    """
    return bool(isinstance(summary, dict) and summary.get("skipped"))


def skip_reason(summary: Any, default: str = "unspecified") -> str:
    """The gate's OWN machine-readable skip-reason token from its summary.

    Same fail-safe shape as ``summary_is_skipped``: a missing / non-dict
    summary, or a reason that is absent or empty, yields ``default`` rather
    than raising, because this is only ever used to LABEL a conclusion the
    gate already reached — it never decides one.
    """
    if isinstance(summary, dict):
        reason = summary.get("reason")
        if reason:
            return str(reason)
    return default


def verdict_line(gate: str, passed: bool, skipped: bool, reason: str,
                 pass_token: str = "PASS") -> str:
    """The one-line verdict a gate prints in its human (non ``--json``) mode.

    Derived from the SAME ``(passed, skipped)`` pair ``exit_code`` routes, so
    the printed word and the exit code cannot disagree. FAIL beats VACUOUS
    here for the same reason it does there.

    ``pass_token`` exists for the gates that already distinguish ``PASS`` from
    ``PASS_WITH_WAIVERS`` on this line; it applies ONLY to a genuine pass. A
    waiver is a judgement about findings the gate made over artefacts it read,
    so it can never describe a run that read nothing.
    """
    if not passed:
        return f"[FAIL] {gate}"
    if skipped:
        return (f"[VACUOUS] {gate} — examined nothing (reason: {reason}); "
                f"this is NOT a pass over the design")
    return f"[{pass_token}] {gate}"


def announce_vacuous(gate: str, reason: str,
                     stream: Optional[TextIO] = None) -> None:
    """Emit the rc-independent ``VACUOUS_PASS:`` disclosure line.

    ``reason`` is the gate's OWN machine-readable skip reason (the
    ``summary["reason"]`` token), not a re-description of it, so the printed
    line and the exit code are derived from the same field.
    """
    print(f"{VACUOUS_STDOUT_SENTINEL} {gate} examined nothing "
          f"(reason: {reason}) — this is NOT a pass over the design",
          file=stream if stream is not None else sys.stderr)
