#!/usr/bin/env python3
"""Shared fixture: the SI crosstalk-delay verdict a tape-out now requires.

`signoff_audit --mode tapeout` refuses to certify unless the SI gate
(`si_mcf_sta_check`) actually PROVED something — see the "Tape-out SI" section
of `signoff_audit.py`. Every pre-existing tape-out fixture in this suite built
the five artefact pillars and no SI verdict at all, which is now the ABSENT
state and blocks.

This helper writes the PROVED shape, so those fixtures keep testing what they
were written to test (GDS ranking, DRC classification, LVS tiers, waiver exit
codes) instead of accidentally re-testing the SI condition. Tests that mean to
exercise the SI condition write their own report — see
`test_si_vacuity_must_be_waived_at_tapeout.py`.

Deliberately NOT a helper that "makes the tapeout pass": it writes one specific
artefact in the shape the real gate emits, and nothing else.
"""
from __future__ import annotations

import json
from pathlib import Path

#: Where `si_mcf_sta_check` writes its report, and where the tape-out gate
#: looks for it. Imported from the gate itself where possible so a path change
#: cannot silently desynchronise the fixtures from the consumer.
try:  # pragma: no cover - import shape depends on sys.path setup by the test
    import signoff_audit as _sa
    SI_REPORT_REL = _sa._SI_REPORT_REL
except Exception:  # pragma: no cover
    SI_REPORT_REL = "reports/phase3/si_mcf_sta_check.json"


def write_proved_si_report(project: Path, folds_proved: int = 12) -> Path:
    """Write an SI report in the shape a genuinely-proved run produces.

    `folds_proved` is the denominator: how many victim-net MCF folds the gate
    re-derived and proved against the bounded SPEF. It must be > 0 — a PASS
    over a zero denominator is the false-clean the gate was fixed for, and the
    tape-out gate refuses it.
    """
    if folds_proved <= 0:
        raise ValueError("a PROVED SI fixture needs a non-zero denominator")
    p = Path(project) / SI_REPORT_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "program": "si_mcf_sta_check",
        "version": "1.0.0",
        "verdict": "PASS",
        "summary": {
            "pass": True,
            "vacuous": False,
            # `build_report` writes these two in the SAME dict literal as
            # `findings`, from the same list, in every version of the emitter.
            # A fixture claiming to be "the shape a genuinely-proved run
            # produces" has to carry them, or it measures a report no run can
            # produce — and consumers that audit the defect channel would then
            # be tuned against a shape that does not exist.
            "errors_count": 0,
            "findings_count": 0,
            "denominator": {
                "unit": "victim-net MCF folds re-derived and PROVED against "
                        "the bounded SPEF",
                "examined": folds_proved,
                "considered": folds_proved,
                "not_applicable_reason": "",
                "details": {"vacuity_code": ""},
            },
        },
        "findings": [],
    }, indent=2) + "\n")
    return p
