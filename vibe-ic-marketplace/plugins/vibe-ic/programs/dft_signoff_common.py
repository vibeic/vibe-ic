#!/usr/bin/env python3
"""dft_signoff_common.py — shared helper for the DFT sign-off gates.

ONE pure function, `disclosed_atpg_skip`, shared (DRY) by the three DFT
sign-off gate programs (dft_atpg_coverage_check / bsdl_emit /
dft_signoff_check) so each can HONOR an HONEST disclosed-skip sentinel the
same way flow_compliance_check's `_sibling_self_skip_for_missing` already
does for the formal step.

Background: the OSS Fault ATPG engine is validated on the commercial PDK and
is NOT turnkey on generic / UDP DFF netlist forms — a documented capability
gap where the engine genuinely CANNOT MEASURE sign-off coverage. (This said
"sky130 generic / UDP DFF netlist forms"; the gap is not sky130-specific. It
was measured on an ihp-sg13g2 run whose netlist sniffed as
`generic_unmapped`, and the producer's reason string now names whichever PDK
the run actually detected.)
When that happens, `design_one_shot_runner.step_dft_lec_chain` makes the
canonical step-11 outputs ABSENT and drops a co-located sibling sentinel
`phase2/stage2/dft/dft_atpg_not_run.json` whose top-level `verdict` is
SKIPPED-CONDITION. This helper lets the gates resolve to SKIPPED-CONDITION
(rc=2 → VACUOUS_PASS tier) instead of a hard missing-evidence FAIL — but
ONLY in that honestly-disclosed case.

§4.05 anti-cheat: the caller MUST also confirm its OWN required input
artifact is ABSENT before honoring the skip. A design that actually produced
measurable coverage (or any real input) is judged normally — a real low
coverage still FAILs. This function only reports whether the honest sentinel
exists; it never inspects or weakens the real evidence.

chip-AGNOSTIC: keyed purely on the DFT directory and a sibling JSON whose
`verdict` is a self-skip verdict — no chip, vendor, SKU or class literal.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# Self-skip verdicts that mark an HONEST disclosed-skip. Mirrors
# flow_compliance_check._SELF_SKIP_VERDICTS. Compared after normalising the
# read verdict to UPPER-CASE with underscores→hyphens, so SKIPPED_CONDITION
# and skipped-condition both match.
_SELF_SKIP_VERDICTS = frozenset({"SKIP", "SKIPPED", "SKIPPED-CONDITION"})

# Reason returned when the honest sentinel carries a self-skip verdict but no
# (or an empty) `reason` field — the skip is still honestly disclosed.
_DEFAULT_REASON = ("flow step-11 DFT ATPG disclosed-skipped — OSS Fault "
                   "engine could not measure sign-off coverage")


def disclosed_atpg_skip(project_dir) -> Optional[str]:
    """Return the honest skip reason if flow step-11 was consciously disclosed-
    skipped: a JSON in phase2/stage2/dft/ whose top-level `verdict` is one of
    SKIP / SKIPPED / SKIPPED-CONDITION (e.g. dft_atpg_not_run.json). Else None.
    Pure/deterministic; no side effects. Used by the DFT sign-off gates to
    return rc=2 (SKIPPED-CONDITION) instead of a hard FAIL when the OSS ATPG
    engine could not measure sign-off coverage AND the runner honestly said so.
    """
    dft_dir = Path(project_dir) / "phase2" / "stage2" / "dft"
    try:
        siblings = sorted(dft_dir.glob("*.json"))
    except OSError:
        return None
    for sib in siblings:
        try:
            data = json.loads(sib.read_text(encoding="utf-8"))
        except Exception:
            # Robust to bad JSON — skip it and keep scanning.
            continue
        if not isinstance(data, dict):
            continue
        vd = str(data.get("verdict", "")).upper().replace("_", "-")
        if vd in _SELF_SKIP_VERDICTS:
            reason = data.get("reason")
            if reason is not None and str(reason).strip():
                return str(reason)
            return _DEFAULT_REASON
    return None
