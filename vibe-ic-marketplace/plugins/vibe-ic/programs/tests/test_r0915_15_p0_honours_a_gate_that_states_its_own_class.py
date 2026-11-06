"""P0 honours a gate that STATES its own reason class, instead of reading its
sentence.

MEASURED 2026-09-15 (lane icspm3, R-0915-15) on `spm` x gf180mcuD.
`_flow_reason_taxonomy.infer_nonverdict_reason` says branch-owned evidence
outranks prose, and `report_reason_class` reads `summary.reason_class` before
any recogniser runs. The P0 umbrella could honour neither, because it invoked
these gates with **no `--json` at all**: there was no report, so a gate that
KNEW its own class had nowhere to say so. Both gates below were changed to
state it, and the record still read::

    waiver_staleness_check — reason_class=EXECUTION_ERROR

off the prose, on an rc=2 the arm labels `skip_kind: input-missing` — an
ASSUMPTION about every rc=2, and simply wrong for a gate whose input was there
and whose subject was not.

BOTH DIRECTIONS: a declaring gate's class is used; a gate that declares
nothing, or writes an unreadable report, keeps exactly the reading it had.

chip-AGNOSTIC: paths derive from the project root and a scratch dir.
"""
from __future__ import annotations

import json
import subprocess  # nosec B404 — declared flow programs
import sys
import tempfile
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import pytest  # noqa: E402

import _flow_reason_taxonomy as R  # noqa: E402


#: What each declaring gate says about THE FIXTURE BELOW — a project with a
#: reports/ dir, an ic_class declaring no analog, an auto-synthesized waiver,
#: and nothing else.
#:
#: R-0915-52 (lane icsub4): this used to be one blanket
#: `== DESIGN_DECLARED_NA`, which held only because both gates registered at
#: the time read that fixture as "the design declares nothing". It is not a
#: property of the registry — `l24_signoff_evidence_backed_check` reads the
#: same fixture as ASKED_BEFORE_PRODUCER, and correctly so: the fixture has no
#: `L24_SIGNOFF.json` because phase 1 never ran, which is a different fact
#: from a design that declares no sign-off. The expectation is therefore
#: stated per gate and the registry coverage is asserted, so a newly
#: registered gate must SAY what it declares here rather than inherit a class
#: it does not mean.
_CLASS_ON_THE_EMPTY_FIXTURE = {
    # This conditional leaf receives its valid, claim-free subject below.
    "deliverable_verdict_consistency_check": R.DESIGN_DECLARED_NA,
    "waiver_staleness_check": R.DESIGN_DECLARED_NA,
    "analog_flow_compliance_check": R.DESIGN_DECLARED_NA,
    "l24_signoff_evidence_backed_check": R.ASKED_BEFORE_PRODUCER,
}


# ── the conservative direction ────────────────────────────────────────────


def test_the_taxonomy_reads_branch_evidence_before_the_prose():
    """The contract this whole channel rests on, asserted directly."""
    assert R.infer_nonverdict_reason(
        verdict="SKIP",
        message="no RTL files found",
        evidence={"reason_class": R.DESIGN_DECLARED_NA,
                  "skip_kind": "declared-by-gate"}) == R.DESIGN_DECLARED_NA
    # and without the declaration the same sentence keeps its old reading
    assert R.infer_nonverdict_reason(
        verdict="SKIP", message="no RTL files found",
        evidence={"exit_code": 2, "skip_kind": "input-missing"}) \
        != R.DESIGN_DECLARED_NA
