#!/usr/bin/env python3
"""The report-audit gate's OWN diagnostic is not a pass claim BY the report.

THE DEFECT (measured on v1.9.78 and on a deployed 1.9.76 cache)
---------------------------------------------------------------
`result_md_audit_provenance_check` decides whether a RESULT.md claims success,
and only then demands burn provenance. Its own diagnostics quote the very
tokens they detect:

    SKIP — RESULT.md does not claim <phase-2+3 success token> or a successful
    burn — provenance citation is not required for a FAIL report

The anti-fabrication doctrine tells an agent to quote a tool's own output
verbatim as evidence. Doing exactly that, on a report whose verdict line is
FAIL, flipped this gate over the SAME unchanged project:

    without the quotation   ->  SKIP, exit 0
    with the quotation      ->  FAIL — 3 provenance gap(s), exit 1

Nothing about the project changed; the report merely cited the gate.

WHY IT MATTERS
--------------
The cheapest way to clear the new FAIL is to write a burn SHA-256 and an
`audit_verdict: PASS` into a report about a burn that never happened. A rule
meant to make reports verifiable rewarded making them falsely verifiable — the
exact failure mode this program exists to prevent, pointed at itself.

THE FIX, AND THE LIMIT OF ITS SCOPE
-----------------------------------
Two halves, both deliberately narrow:
  1. the emitted sentences no longer contain the token pair their own pattern
     detects, so the gate's output is a FIXED POINT — quoting it reproduces it;
  2. an exact-sentence self-reference guard blanks out only text THIS program
     emits (current and pre-fix wording) before the claim scan.

The reverse controls below are the load-bearing half of this file: they pin
that a genuine claim is STILL caught, including a genuine claim sitting in the
same document as a quoted diagnostic. A guard that suppressed those would have
swallowed the real defect underneath.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PROG = (
    Path(__file__).resolve().parent.parent / "result_md_audit_provenance_check.py"
)

# The gate's own SKIP sentence as emitted BEFORE this fix. Reports written
# against an older plugin still carry this wording verbatim.
PRE_FIX_SKIP_SENTENCE = (
    "SKIP — RESULT.md does not claim Phase 2+3 PASS or a successful burn — "
    "provenance citation is not required for a FAIL report"
)

# The gate's own first failure sentence as emitted BEFORE this fix.
PRE_FIX_FAIL_SENTENCE = (
    "RESULT_MD_MISSING_AUDIT_SHA — RESULT.md claims a successful burn / "
    "Phase 2+3 PASS but does not cite the SHA-256 of "
    "`phase23_completion_audit.json`."
)

HONEST_FAIL_HEADER = (
    "# widget_core — round 3\n"
    "\n"
    "## VERDICT\n"
    "\n"
    "**FAIL.** Not converged. No hardware was programmed and no burn was\n"
    "attempted. The flow compliance gate returned exit 1.\n"
)

# The gate's own pass-claim pattern for the Phase-2+3 shape, duplicated here on
# purpose: these tests must keep working if the program's internals are
# refactored, and a structural assertion that imports the thing it audits is
# weaker than one that restates the rule.
PHASE23_CLAIM_RE = re.compile(
    r"\bPHASE\s*2\s*\+\s*3\b[^\n]{0,40}\bPASS\b", re.IGNORECASE
)


def _write(tmp_path: Path, body: str) -> Path:
    (tmp_path / "RESULT.md").write_text(body, encoding="utf-8")
    return tmp_path


def _run(project: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# THE DEFECT — each of these FAILs against the byte-identical pre-fix file
# ---------------------------------------------------------------------------

def test_quoting_the_gates_own_skip_line_is_not_a_pass_claim(tmp_path):
    """The headline defect: citing the gate's verdict must not become a claim."""
    p = _write(tmp_path, HONEST_FAIL_HEADER + f"\n```\n{PRE_FIX_SKIP_SENTENCE}\n```\n")
    r = _run(p)
    assert r.returncode == 0, r.stdout
    assert "SKIP" in r.stdout, r.stdout


def test_quoting_the_gates_own_failure_line_is_not_a_pass_claim(tmp_path):
    """A report quoting WHY it failed the gate must not thereby claim a pass."""
    p = _write(tmp_path, HONEST_FAIL_HEADER + f"\n```\n{PRE_FIX_FAIL_SENTENCE}\n```\n")
    r = _run(p)
    assert r.returncode == 0, r.stdout
    assert "SKIP" in r.stdout, r.stdout


def test_hard_wrapped_quotation_is_still_recognised(tmp_path):
    """Markdown reflows long lines; the guard matches across whitespace."""
    wrapped = (
        "SKIP — RESULT.md does not claim Phase 2+3\n"
        "PASS or a successful burn — provenance citation is not\n"
        "required for a FAIL report"
    )
    p = _write(tmp_path, HONEST_FAIL_HEADER + f"\n```\n{wrapped}\n```\n")
    r = _run(p)
    assert r.returncode == 0, r.stdout


def test_emitted_skip_message_is_a_fixed_point(tmp_path):
    """Structural: the gate's own SKIP output must not match its own pattern."""
    p = _write(tmp_path, HONEST_FAIL_HEADER)
    r = _run(p)
    assert r.returncode == 0, r.stdout
    assert "SKIP" in r.stdout, r.stdout
    assert not PHASE23_CLAIM_RE.search(r.stdout), (
        "the SKIP message matches the gate's own pass-claim pattern; quoting "
        f"it would re-trigger the gate: {r.stdout!r}"
    )


def test_emitted_failure_message_is_a_fixed_point(tmp_path):
    """Same fixed-point property for the failure text the gate prints."""
    p = _write(
        tmp_path,
        "# widget_core\n\n## VERDICT\n\nPhase 2+3 PASS was achieved.\n",
    )
    r = _run(p)
    assert r.returncode == 1, r.stdout
    # The gate's own prose must not re-trigger. Drop the report's own quoted
    # claim if the gate echoes it, then assert on what the GATE wrote.
    gate_prose = "\n".join(
        ln for ln in r.stdout.splitlines() if "was achieved" not in ln
    )
    assert not PHASE23_CLAIM_RE.search(gate_prose), (
        f"failure message re-triggers the gate when quoted: {gate_prose!r}"
    )


def test_round_trip_of_the_current_skip_message_is_stable(tmp_path):
    """Quote the CURRENT message back in: the verdict must not move."""
    p = _write(tmp_path, HONEST_FAIL_HEADER)
    first = _run(p)
    assert first.returncode == 0, first.stdout
    quoted = first.stdout.strip().splitlines()[0]
    p2 = _write(tmp_path, HONEST_FAIL_HEADER + f"\n```\n{quoted}\n```\n")
    second = _run(p2)
    assert second.returncode == 0, second.stdout
    assert second.stdout.strip().splitlines()[0] == quoted


# ---------------------------------------------------------------------------
# REVERSE CONTROLS — these pass in BOTH directions, pre-fix and post-fix.
# They are what rules out a guard tightened until nothing matches.
# ---------------------------------------------------------------------------

def test_reverse_genuine_phase23_claim_is_still_caught(tmp_path):
    p = _write(
        tmp_path,
        "# widget_core\n\n## VERDICT\n\nPhase 2+3 PASS. Tapeout ready.\n",
    )
    r = _run(p)
    assert r.returncode == 1, r.stdout


def test_reverse_genuine_hardware_claim_is_still_caught(tmp_path):
    p = _write(
        tmp_path,
        "# widget_core\n\n## VERDICT\n\nhardware bring-up PASS on the board.\n",
    )
    r = _run(p)
    assert r.returncode == 1, r.stdout


def test_reverse_genuine_burn_claim_is_still_caught(tmp_path):
    p = _write(
        tmp_path,
        "# widget_core\n\n## VERDICT\n\nThe burn completed and was verified.\n",
    )
    r = _run(p)
    assert r.returncode == 1, r.stdout


def test_reverse_sof_programmed_claim_is_still_caught(tmp_path):
    """A claim shape outside the guard's scope stays live."""
    p = _write(
        tmp_path,
        "# widget_core\n\n## VERDICT\n\nThe SOF was programmed to the board.\n",
    )
    r = _run(p)
    assert r.returncode == 1, r.stdout


def test_reverse_real_claim_BESIDE_a_quoted_diagnostic_is_still_caught(tmp_path):
    """THE load-bearing control against over-tightening.

    A fabricator could paste the gate's own SKIP sentence hoping it launders
    the document. It must not: the guard blanks OUR sentence only, so their
    claim is untouched and still fails.
    """
    p = _write(
        tmp_path,
        HONEST_FAIL_HEADER
        + f"\n```\n{PRE_FIX_SKIP_SENTENCE}\n```\n\n"
        + "Separately, hardware PASS was achieved on the bench.\n",
    )
    r = _run(p)
    assert r.returncode == 1, (
        "a real claim beside a quoted diagnostic must still be caught: "
        + r.stdout
    )


def test_reverse_claim_with_full_provenance_still_passes(tmp_path):
    """The gate must still let a properly-cited success through."""
    p = _write(
        tmp_path,
        "# Phase 2+3 PASS\n\n"
        "## Burn provenance\n"
        "audit_sha256: sha256:" + "0" * 64 + "\n"
        "audit_verdict: PASS\n"
        "program_response: {success: true, guard_invoked: true, "
        "error_code: program_succeeded}\n"
        "Hardware verdict: byte[6]=0xF2 across 5/5 connect_test runs.\n",
    )
    r = _run(p)
    assert r.returncode == 0, r.stdout
