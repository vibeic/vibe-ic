"""ORGANIC #652 [reporting honesty] — the SOLE-ACCEPTANCE narrative in
final_report_generate.py labelled the ENTIRE SKIPPED-CONDITION bucket as
"manufacturing-skipped", mislabelling mid-flow capability-gap / cascade-
blocked / FPGA-board-absent skips as silicon-stage skips.

Evidence: `final_report_generate.py:1396-1401` printed
`manufacturing-skipped: {snap['skipped']}` where `snap['skipped']` is the
TOTAL SKIPPED-CONDITION rollup (line 605), not just manufacturing-stage
steps; the prose bullet (~:1098) generalised the whole bucket as
"manufacturing steps awaiting silicon". A committed artifact reported
`manufacturing-skipped: 10` while only steps 40-44 (5) are manufacturing.

Fix: split the SKIPPED-CONDITION rollup BY STAGE. Only manufacturing-stage
steps (stage `stage5_manufacturing`, equivalently the documented step-id
range 40-44) count as `manufacturing-skipped`; every earlier
SKIPPED-CONDITION step is reported as `mid-flow-skipped`. The two buckets
are mutually exclusive and sum to the total SKIPPED-CONDITION rollup, so
the report stays honest.

POSITIVE (#652): a snapshot with N mid-flow + M manufacturing
SKIPPED-CONDITION steps → manufacturing bucket == M, mid-flow bucket == N
(NOT N+M), and M + N == total skipped.

NEGATIVE no-leak: a run with ONLY manufacturing skips → manufacturing
bucket equals that count (unchanged) and mid-flow bucket == 0.

chip-AGNOSTIC: classification is structural (the `stage` field, or the
documented numeric step-id range as fallback) — never a chip-specific
step name.
"""
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import final_report_generate as F  # noqa: E402


# ─── synthetic flow + verdict snapshot helpers ───────────────────────────

def _mfg_step(sid):
    """A manufacturing-stage step record (matches what final_report
    consumes: id + stage)."""
    return {"id": sid, "name": f"step {sid}", "stage": "stage5_manufacturing"}


def _midflow_step(sid, stage="stage3"):
    """A non-manufacturing (earlier) step record."""
    return {"id": sid, "name": f"step {sid}", "stage": stage}


def _flow(steps):
    return {"steps": steps}


# ─── _is_manufacturing_step: structural classification ───────────────────

def test_is_manufacturing_step_by_stage_field():
    assert F._is_manufacturing_step(_mfg_step(40)) is True
    assert F._is_manufacturing_step(_mfg_step(44)) is True
    assert F._is_manufacturing_step(_midflow_step(20)) is False
    assert F._is_manufacturing_step(_midflow_step(39, stage="stage4")) is False


def test_is_manufacturing_step_numeric_fallback_when_no_stage():
    # No `stage` field → fall back to the documented 40-44 id range.
    assert F._is_manufacturing_step({"id": 40}) is True
    assert F._is_manufacturing_step({"id": 42}) is True
    assert F._is_manufacturing_step({"id": 44}) is True
    assert F._is_manufacturing_step({"id": 39}) is False
    assert F._is_manufacturing_step({"id": 45}) is False
    # string id without stage still resolves via int()
    assert F._is_manufacturing_step({"id": "41"}) is True
    # non-numeric id without stage → not manufacturing (e.g. analog "A3")
    assert F._is_manufacturing_step({"id": "A3"}) is False


def test_is_manufacturing_step_stage_field_wins_over_id_range():
    # An explicit non-mfg stage on an id that happens to be in 40-44
    # must NOT be classified as manufacturing — the stage field is
    # authoritative when present.
    assert F._is_manufacturing_step({"id": 41, "stage": "stage4"}) is False
    # ...and an explicit mfg stage on an out-of-range id IS manufacturing.
    assert F._is_manufacturing_step(
        {"id": 7, "stage": "stage5_manufacturing"}) is True


# ─── _split_skipped_by_stage: the core split ─────────────────────────────

def test_split_skipped_positive_mixed_midflow_and_manufacturing():
    # N=3 mid-flow SKIPPED-CONDITION + M=2 manufacturing SKIPPED-CONDITION.
    steps = [
        _midflow_step(11, stage="stage1"),  # skipped, mid-flow
        _midflow_step(22, stage="stage3"),  # skipped, mid-flow
        _midflow_step(33, stage="stage4"),  # skipped, mid-flow
        _mfg_step(40),                       # skipped, manufacturing
        _mfg_step(41),                       # skipped, manufacturing
        _midflow_step(5, stage="stage1"),    # PASS — must NOT be counted
        _mfg_step(42),                        # PASS — must NOT be counted
    ]
    verdicts = {
        "11": "SKIPPED-CONDITION",
        "22": "SKIPPED-CONDITION",
        "33": "SKIPPED-CONDITION",
        "40": "SKIPPED-CONDITION",
        "41": "SKIPPED-CONDITION",
        "5": "PASS",
        "42": "PASS",
    }
    mfg, midflow = F._split_skipped_by_stage(_flow(steps), verdicts)
    assert mfg == 2, mfg
    assert midflow == 3, midflow
    # honesty invariant: buckets sum to the total SKIPPED-CONDITION rollup
    total_skipped = sum(1 for v in verdicts.values() if v == "SKIPPED-CONDITION")
    assert mfg + midflow == total_skipped == 5


def test_split_skipped_noleak_only_manufacturing():
    # NO-LEAK: only manufacturing skips → manufacturing bucket equals the
    # count, mid-flow bucket is 0 (unchanged behaviour for pure-silicon).
    steps = [_mfg_step(40), _mfg_step(41), _mfg_step(42),
             _mfg_step(43), _mfg_step(44)]
    verdicts = {str(s["id"]): "SKIPPED-CONDITION" for s in steps}
    mfg, midflow = F._split_skipped_by_stage(_flow(steps), verdicts)
    assert mfg == 5, mfg
    assert midflow == 0, midflow


def test_split_skipped_only_midflow():
    steps = [_midflow_step(10, "stage2"), _midflow_step(20, "stage3")]
    verdicts = {"10": "SKIPPED-CONDITION", "20": "SKIPPED-CONDITION"}
    mfg, midflow = F._split_skipped_by_stage(_flow(steps), verdicts)
    assert mfg == 0
    assert midflow == 2


def test_split_skipped_none():
    steps = [_midflow_step(10, "stage2"), _mfg_step(40)]
    verdicts = {"10": "PASS", "40": "PASS"}
    mfg, midflow = F._split_skipped_by_stage(_flow(steps), verdicts)
    assert (mfg, midflow) == (0, 0)


# ─── _counts_snapshot: the populated buckets the narrative reads ─────────

def _rollup_for(verdicts):
    import collections
    return dict(collections.Counter(verdicts.values()))


def test_counts_snapshot_populates_split_buckets():
    steps = [
        _midflow_step(11, "stage1"),
        _midflow_step(22, "stage3"),
        _midflow_step(33, "stage4"),
        _mfg_step(40),
        _mfg_step(41),
    ]
    verdicts = {
        "11": "SKIPPED-CONDITION",
        "22": "SKIPPED-CONDITION",
        "33": "SKIPPED-CONDITION",
        "40": "SKIPPED-CONDITION",
        "41": "SKIPPED-CONDITION",
    }
    rollup = _rollup_for(verdicts)
    snap = F._counts_snapshot(rollup, total_steps=len(steps),
                              flow=_flow(steps), verdicts=verdicts)
    # The narrative now reads skipped_manufacturing / skipped_midflow,
    # NOT the undifferentiated `skipped` total.
    assert snap["skipped"] == 5                  # honest total preserved
    assert snap["skipped_manufacturing"] == 2    # ONLY steps 40-44
    assert snap["skipped_midflow"] == 3          # mid-flow under own label
    assert (snap["skipped_manufacturing"]
            + snap["skipped_midflow"]) == snap["skipped"]


def test_counts_snapshot_noleak_only_manufacturing():
    steps = [_mfg_step(40), _mfg_step(41), _mfg_step(42)]
    verdicts = {"40": "SKIPPED-CONDITION", "41": "SKIPPED-CONDITION",
                "42": "SKIPPED-CONDITION"}
    rollup = _rollup_for(verdicts)
    snap = F._counts_snapshot(rollup, total_steps=len(steps),
                              flow=_flow(steps), verdicts=verdicts)
    # only-manufacturing case: manufacturing bucket == the count, mid 0.
    assert snap["skipped"] == 3
    assert snap["skipped_manufacturing"] == 3
    assert snap["skipped_midflow"] == 0


def test_counts_snapshot_without_flow_books_as_midflow():
    # Conservative fallback: no per-step context → never silently label a
    # skip as silicon-stage; the whole bucket is booked mid-flow.
    rollup = {"SKIPPED-CONDITION": 4, "PASS": 1}
    snap = F._counts_snapshot(rollup, total_steps=5)
    assert snap["skipped"] == 4
    assert snap["skipped_manufacturing"] == 0
    assert snap["skipped_midflow"] == 4


# ─── the documented regression scenario from the issue body ──────────────

def test_issue652_scenario_no_overreport():
    # Issue body: artifact reported `manufacturing-skipped: 10` while only
    # steps 40-44 (5) are manufacturing → 5 mid-flow were mislabelled.
    steps = (
        [_midflow_step(i, "stage3") for i in (24, 25, 30, 35, 38)]  # 5 mid
        + [_mfg_step(i) for i in (40, 41, 42, 43, 44)]              # 5 mfg
    )
    verdicts = {str(s["id"]): "SKIPPED-CONDITION" for s in steps}
    rollup = _rollup_for(verdicts)
    snap = F._counts_snapshot(rollup, total_steps=len(steps),
                              flow=_flow(steps), verdicts=verdicts)
    assert snap["skipped"] == 10                       # honest total
    assert snap["skipped_manufacturing"] == 5          # NOT 10
    assert snap["skipped_midflow"] == 5                # under its own label
