"""Legacy diagnostic tail: measure a failed route without admitting release.

The single-project Default path now stops at the failed canonical row.
These controls retain the existing Ultra diagnostic tail's assertions;
test_default_pnr_row_boundaries exercises the Default stopping path.

MEASURED (IC_BLOCKER_AUDIT 2026-09-29, spm #2; subservient IC run
`subic_ic_20260928` on 8hd-3, read-only): `_chain_ok` in `main()` was
`row.status == "PASS"` for every Step-32 producer, and a pre-stream gate FAIL
set it False. On subservient the pre-stream gate measured FAIL (sta_signoff,
sta_corner, sta_record, em_authority, antenna), and then gds, drc, lvs and
canonicalize_artefacts all read NOT_MEASURED "sign-off skipped: pre-stream gate
failed". On spm a measured Step-32 DRV FAIL did the same. So no run has measured
the tail (GDS, DRC, LVS, fill, precheck, handoff), and the tail's own blockers
stay hidden. The flow also declared 32 `blocks_on [23..30]`, the reverse of the
runner's order, so the audit could never attribute a gap to 32.

The rule now:
  * a measured FAIL at Step 32 or at the pre-stream gate is RECORDED and keeps
    the run FAIL (rc != 0);
  * stream-out and the tail still run on the shipped route;
  * only a missing/unusable route stops them, NOT_MEASURED naming the upstream;
  * a stream after a non-PASS pre-stream gate is measurement-only: never
    admitted, never packaged, and its release receipt is not eligible.

chip-, PDK- and vendor-AGNOSTIC: synthetic fixtures; only EDA writes are faked.
"""
from __future__ import annotations

from pathlib import Path

import yaml

import phase3_one_shot_runner as R

FLOW = Path(R.__file__).resolve().parent.parent / "flow" / "phase1_phase2_phase3.yaml"


# ── the declared order matches the runner's data flow ─────────────────────

def _ancestors(sid, bo):
    out, stack = set(), [sid]
    while stack:
        for p in bo.get(stack.pop(), []):
            if p not in out:
                out.add(p)
                stack.append(p)
    return out


def test_signoff_steps_are_downstream_of_step32():
    """RED on main: 32 blocks_on [23, 24, 25, 26, 27, 29, 30]."""
    doc = yaml.safe_load(FLOW.read_text())
    bo = {str(s["id"]): [str(p) for p in (s.get("blocks_on") or [])]
          for s in doc["steps"] if isinstance(s, dict) and "id" in s}
    for sid in ("23", "24", "25", "26", "27", "28", "29", "30"):
        assert "32" in _ancestors(sid, bo), f"step {sid} is not downstream of 32"
        assert sid not in _ancestors("32", bo), f"32 still waits on {sid}"
    # Repair the routed checkpoint first, then extract its final parasitics.
    # The provisional repair estimate is not the final Step-22 product.
    assert "21" in _ancestors("32", bo)
    assert "32" in _ancestors("22", bo)
    assert "22" not in _ancestors("32", bo)


# ── review wave 58: the tape-out tail keeps sign-off 23-30 as ancestors ───

#: The tail as the flow declares it: 34 (fill, where stream-out enters) and
#: everything downstream of it. Measured with the audit's own
#: `flow_step_execution_coverage_check.analyze` on main 9dc7bb35e (before the
#: flip): a step-23 FAIL voided exactly these, plus 30/31/33/36 and 32.
_TAIL = ("34", "35", "37", "37.3", "37.4", "37.5ic", "37.5ip", "38", "39",
         "40", "41", "42", "43", "44", "M1", "M2", "M3", "M4")
_SIGNOFF = ("23", "24", "25", "26", "27", "29", "30")
