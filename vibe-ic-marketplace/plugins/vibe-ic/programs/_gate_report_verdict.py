#!/usr/bin/env python3
"""The CONTRACT for "this gate examined nothing", stated once (vibe-ic#901).

WHY THIS MODULE EXISTS. A gate may disclose that it had nothing to examine
through three channels, and the third is the only one a project-path length
cannot truncate (the bar #887 set, because a consumer sees at most the last few
hundred bytes of stdout):

    rc 2                            the input-missing skip
    a `VACUOUS_PASS:` stdout line   the printed disclosure, rc 0
    `{"verdict": "NOT_APPLICABLE"}` in the gate's OWN `--json` report, rc 0

#901 was filed against the third: six gates exited 0 on an empty project having
written exactly that verdict into a report the consumer never opened, and were
scored as substantive passes. `vacuous_testbench_check` was one of them — the
gate against vacuous passes, consumed as one.

WHY IT IS A MODULE AND NOT A METHOD ON ONE CONSUMER. The first fix taught
`flow_compliance_check` to open that report. It was correct and it was not
enough, and the measurement that says so is in the issue: a SECOND consumer,
`phase3_one_shot_runner`'s declared-sign-off roll-up, maps rc 0 straight to
`PASS`, so on a run where a declared sign-off gate reported NOT_APPLICABLE the
headline still read `4 of 5 declared sign-off gate(s) PASSED` and the one field
that exists to carry "this gate checked nothing" — `not_checked` — stayed
empty. A SEVENTH producer (`post_route_signoff_corner_check`) was also outside
the six the issue enumerated. Both facts point the same way: this is a property
of the gate/consumer CONTRACT, not a bug in whichever consumer was found first.
Patching the consumer you happened to find first is how this defect survives its
own fix.

So the predicate lives here, both consumers import it, and the test that
enumerates the consumers drives each one end-to-end and reads its emitted
verdict — a list of consumers that is checked by RUNNING them, not by reading
the source for a call.

WHAT THIS MODULE DOES NOT DECIDE. It answers one question — did the gate
disclose that it examined nothing? — and says nothing about what that should
COST. The two consumers are different vocabularies and deliberately answer
differently: `flow_compliance_check` counts the disclosure against the step's
other clauses (#901's census), while the phase-3 runner routes it out of
`passed` and into `not_checked`. Putting a tier in here would force one
vocabulary onto both, which is the mistake `_aggregate_verdict`'s own comment
records having tried and rejected.

chip/PDK-AGNOSTIC: reads verdict words and JSON structure only. No design name,
no vendor, no part number.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

#: Verdict words a gate writes into its OWN `--json` report that mean "I
#: examined nothing". Read from the FILE, never from stdout.
#:
#: Every entry is a spelling this repo's gates actually emit; the set is
#: deliberately not extended with near-synonyms, because a consumer that treats
#: an unrecognised word as a disclosure would silently downgrade substantive
#: passes, and one that treats it as substantive keeps #901 open. A gate adding
#: a new spelling is a producer change, and it belongs in this one line.
NO_CHECK_VERDICTS = frozenset({
    "NOT_APPLICABLE", "SKIPPED", "SKIP", "VACUOUS", "VACUOUS_PASS",
    "NO_BUILD", "NOT_RUN",
})

#: The keys a gate report may state its verdict under. Both are in live use.
_VERDICT_KEYS = ("verdict", "status")


def payload_declares_no_check(payload: Any) -> bool:
    """True iff an already-parsed gate report declares it examined nothing.

    Non-dict payloads are False, not an error: a gate is free to write a list
    or a scalar, and a consumer must not crash on a report shape it did not
    expect while auditing something else.
    """
    if not isinstance(payload, dict):
        return False
    for key in _VERDICT_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip().upper() in NO_CHECK_VERDICTS:
            return True
    return False


def report_declares_no_check(path: Optional[Path]) -> bool:
    """True iff the gate report at `path` declares it examined nothing.

    An absent, empty or unparseable report is NOT a disclosure. That direction
    matters: reading "no readable report" as "the gate examined nothing" would
    convert every write failure into a silent downgrade, and a report the
    consumer cannot read is a fault to surface elsewhere, not a verdict.
    """
    if path is None:
        return False
    try:
        p = Path(path)
        if not (p.is_file() and p.stat().st_size > 0):
            return False
        return payload_declares_no_check(
            json.loads(p.read_text(errors="replace")))
    except (OSError, ValueError, TypeError):
        return False


def report_path_in_command(project: Path, cmd: str) -> Optional[Path]:
    """The `--json <path>` a gate command writes its report to, if any.

    The consumer already knows this path — it is in the command string it just
    ran — so reading the report asks nothing new of the gate, and covers gates
    written LATER, which patching a list of emitters would not.
    """
    m = re.search(r"--json[= ]+(\S+)", cmd or "")
    if not m:
        return None
    p = Path(m.group(1).strip("'\""))
    return p if p.is_absolute() else project / p


def command_report_declares_no_check(project: Path, cmd: str) -> bool:
    """True iff the report written by `cmd`'s `--json` declares no check."""
    return report_declares_no_check(report_path_in_command(project, cmd))
