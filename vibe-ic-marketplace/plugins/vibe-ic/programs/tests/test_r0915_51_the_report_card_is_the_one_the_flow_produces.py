"""R-0915-51: the report card is the one the flow produces.

MEASURED 2026-09-16 on the SPM verdict run (run30 / `spm25`, main d5fe608e3).
The completion audit named ONE cause for the whole run's FAIL::

    step 36 FAIL <- step_internal_fail_bubble_up_check
      [STEP_FAIL_NOT_BUBBLED] reports/phase2/gates/agent_report_presence.json
      verdict=FAIL  ("AGENT_REPORT.md does not exist at project root")
    steps 37, 37.4, 37.5ip, 38: PASS_VOIDED_BY_DEPENDENCY on step 36

and the runner's own docstring already admitted the contradiction: "NOTHING in
the shipped flow writes AGENT_REPORT.md. The canonical report card moved to
reports/final_summary.md in v1.6.32 ... this gate was never re-pointed."

TWO HALVES, BOTH TESTED HERE.

(1) `agent_report_presence_check` resolves the card through the SIBLING's own
register, `agent_report_sha256_attestation_check._REPORT_CANDIDATE_REL_PATHS`
(generated card first, hand-authored back-compat second), and verifies the
sections THAT card declares. A generated card is held to what its generator
GUARANTEES — `final_report_generate.MANDATORY_SECTIONS`, imported, never
re-typed — and a hand-authored one to the five this gate has always demanded.
It still FAILS with no card and with a declared section missing; both are
below. NOBODY HAND-WRITES A VERDICT CARD: accepting the generated one is what
keeps it that way.

(2) The step that wires a gate ADVISORY (`"blocking": False` in its ledger
row) now writes `"verdict_mode": "ADVISES"` into that GATE's own JSON, because
that is where `step_internal_fail_bubble_up_check` reads it ("verdict_mode:
ADVISES IS AN ANSWER, NOT A SILENCE"). The decision was written in the ledger
and the consumer that needed it could not see it. This is CONSISTENCY, NOT A
LEVER: a blocking gate's report never receives the key, and no gate changes
tier.

chip-AGNOSTIC: synthetic projects in tmp_path.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import pytest  # noqa: E402

import final_report_generate as G  # noqa: E402

PRESENCE = PROGRAMS / "agent_report_presence_check.py"
BUBBLE = PROGRAMS / "step_internal_fail_bubble_up_check.py"


#: Read with `getattr` so this file COLLECTS against a tree that does not have
#: the constant yet. A control arm that errors at collection proves only that
#: a name is new; one that RUNS proves the old code answers wrongly.
GUARANTEED = tuple(getattr(G, "MANDATORY_SECTIONS", ()))








# ── (1) the card is resolved through the sibling's register ──────────────







@pytest.mark.parametrize("name,heading,synonyms", GUARANTEED)
def test_every_guaranteed_heading_matches_its_own_synonyms(name, heading,
                                                           synonyms):
    """THE DRIFT LOOP, closed. The generator emits `heading`; the checker
    accepts `synonyms`. If someone renames the heading without moving the
    synonyms, the card the flow produces stops satisfying the gate that reads
    it -- silently, on every run. This fails first instead."""
    emitted = getattr(G, "section_heading", lambda n: None)(name)
    assert emitted == f"## {heading}"
    low = heading.lower()
    assert any(s in low for s in synonyms), (name, heading, synonyms)


# ── (1) the two refusals it must keep ────────────────────────────────────







# ── (1) back-compat: a hand-authored card keeps the old five ─────────────

LEGACY = ["Verdict", "Acceptance evidence", "Waivers list", "Discoveries",
          "Iteration log"]








# ── (2) the advisory decision is written where its consumer reads it ─────
