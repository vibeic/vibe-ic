"""Step 2 NAMES the producer of the pad-budget report, and promises nothing.

MEASURED 2026-09-15 (lane icspm3). Dimension 7 refused step 2's declared-output
list::

    step 2: required_outputs is INCOMPLETE — 1 load-bearing artefact(s) it
    never declares.
      * [W1:gate_output_read_elsewhere] 'reports/phase2/gates/slot_pad_budget.json'
        (written by slot_pad_budget_check; read by program:design_one_shot_runner)
        — gate-designated output that something other than its own writer reads

and both census-freshness cases then failed as NORECORD on that FOREIGN red —
which is why this one finding blocked every `flow_matrix_coverage` measurement,
not only step 2's row.

BOTH SIDES OF THE RELATION ARE OLD: `design_one_shot_runner.py` reads that path
and step 2's own gate clause writes it, and both date from 2026-08-21
(`da02c143f`, `b0ff3babf`). What was missing is the DECLARATION of who produces
it.

`program_outputs:` IS THE CHANNEL AND `required_outputs:` IS NOT, and d7's own
case states both halves: an anchor must be DECLARED so W2's "declared by
nobody" is answered, and must NOT be promised in `required_outputs`, which is
unconditional ALL-of-N. A design that buys no operator slot legitimately never
writes this file, and an entry there would report every such run MISSING — the
same trap step 1's yaml records for `phase2/stage1/lessons.md`.

chip-AGNOSTIC: every assertion reads the shipped yaml and the d7 graph.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import pytest  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))

PATH = "reports/phase2/gates/slot_pad_budget.json"
PRODUCER = "slot_pad_budget_check"


def _step2():
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(
        (PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml").read_text(
            errors="replace"))

    def walk(n):
        if isinstance(n, dict):
            if "id" in n and ("required_outputs" in n or "gate" in n):
                yield n
            for v in n.values():
                yield from walk(v)
        elif isinstance(n, list):
            for v in n:
                yield from walk(v)
    for s in walk(doc):
        if str(s.get("id")) == "2":
            return s
    raise AssertionError("step 2 is not in the shipped flow")


# ── direction 1: the producer is NAMED ────────────────────────────────────





def test_the_row_states_the_verdict_field_the_report_actually_carries():
    """READ, not assumed: the gate's own `--json` report carries a top-level
    `verdict` (measured on this lane's runs: check, note, rc, reason,
    reason_class, verdict)."""
    row = next(r for r in (_step2().get("program_outputs") or [])
               if r.get("path") == PATH)
    assert row["program"] == PRODUCER
    assert row.get("verdict_field") == "verdict"
    src = (PROGRAMS / f"{PRODUCER}.py").read_text(errors="replace")
    assert '"verdict"' in src or "'verdict'" in src


# ── direction 2: and NOTHING is promised ──────────────────────────────────



def test_step_2_required_outputs_is_unchanged():
    # DEPARTED 2026-09-24: "reports/phase1/gates/stage_phase1_compliance.json",
    # by R-0915-141, the step-38 half, lane ictier1 (spm run23: "AUDIT-CREATED OUTPUT REFUSED: ['reports/phase1/gates/stage_phase1_compliance.json']"). It is
    # the nested stage_phase1 clause's own --json verdict target and left the
    # declared set; the pad-budget document this file guards is still NOT
    # promised here, which is what this pin exists to hold.
    assert [str(o) for o in _step2()["required_outputs"]] == [
        "reports/phase2/lint/rtl_hygiene.json",
        "reports/phase2/lint/rom_init_lint.json",
        "reports/crosslayer/rewrite_equivalence_check.json",
    ]
