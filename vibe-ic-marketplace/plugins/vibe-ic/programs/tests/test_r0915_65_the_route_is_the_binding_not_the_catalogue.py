"""R-0915-65: the publication route is the BINDING, not the catalogue.

MEASURED 2026-09-16 on the SPM verdict run (run34, `spm29`, main 845ef5247).
`benchmark_evidence_publish` refused to publish a PASS_WITH_WAIVERS run::

    REFUSED: release documentation INVARIANT (#2017) — a IC cell is
    incomplete: must carry step 37.5ic's 9 declared output(s), carries
    nothing matching 8 of them; and has NO release directory under
    phase3/stage4/documentation/ic/

because `design_kind(spm29)` answered **IC**, "route SHUTTLE — an operator
slot file was ingested". It globbed `input/submission_template/slots/*.yaml`
and found four — the operator's whole CATALOGUE, which step 0.5ic fetches for
any design whose PDK has a live shuttle, bought or not.

THE RUN'S OWN FLOW SAID THE OPPOSITE. Step 37.5ic sat at SKIPPED-CONDITION:
"design-declared NOT_APPLICABLE: … answers.deliverable='HARDMACRO' and no
operator slot is bound". Step 37.5ip PASSED with 11/11 outputs and wrote all
seven documents. Two parts of the platform disagreed about one design's route,
and the publisher's answer contradicted the design's own declaration.

THE FLOW HAD ALREADY SETTLED IT, in the same words, for step 37.5ic's own
condition (vibe-ic#2277): "a live shuttle in the registry, on the PDK the
design names, is INFORMATION, not a requirement". So `design_kind` now asks
the SAME READER the run and the audit use —
`submission_template_check.slot_rules_are_owed` — rather than keeping a second
predicate that can disagree with them.

chip-AGNOSTIC: synthetic runs in tmp_path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import pytest  # noqa: E402

import _tapeout_declaration as TD  # noqa: E402
import _owner_declared as _OD                              # noqa: E402


def _run(tmp_path, deliverable="HARDMACRO", catalogue=True, slot=None,
         answers=True):
    st = tmp_path / "input" / "submission_template"
    st.mkdir(parents=True, exist_ok=True)
    # Built from the module's OWN `blank_declaration()`, so the fixture is a
    # VALID declaration rather than my idea of one. It matters: an invalid
    # declaration makes `slot_rules_are_owed` degrade towards OWING, and a
    # hand-typed stub would have tested that fallback instead of the route.
    doc = TD.blank_declaration()
    doc.setdefault("answers", {})["deliverable"] = deliverable
    doc["answers"]["top_cell"] = "x"
    _OD.attest(doc)
    (st / "tapeout_declaration.json").write_text(json.dumps(doc))
    if catalogue:
        slots = st / "slots"
        slots.mkdir(exist_ok=True)
        for name in ("0p5x0p5", "0p5x1", "1x0p5", "1x1"):
            (slots / f"{name}.yaml").write_text("slot: {}\n")
    if answers:
        # `answers` must be a VALID merged declaration agreeing with the
        # tapeout declaration: `slot_rules_are_owed` re-merges and re-validates
        # it, and anything it cannot read degrades towards OWING the slot
        # contract. A stub without it tests that fallback, not the route.
        (tmp_path / "input" / "step_0_5ic_answers.json").write_text(
            json.dumps({"schema": 1,
                        "answers": dict(doc["answers"]),
                        "operator_template":
                        {"path": None, "slot": slot,
                         "absent_reason": "no operator applies"}}))
    return tmp_path


# ── the positive: SPM's exact shape ──────────────────────────────────────


# ── the negative controls the ruling names ───────────────────────────────


def test_the_reader_is_the_flows_own(tmp_path):
    """Not a second predicate: the same function step 37.5ic's condition
    reaches through `flow_compliance_check._delivery_declares_absence`."""
    import submission_template_check as STC
    run = _run(tmp_path)
    owed, _why = STC.slot_rules_are_owed(run, None)
    assert owed is False
    owed_bound, _ = STC.slot_rules_are_owed(run, "1x1")
    assert owed_bound is True
