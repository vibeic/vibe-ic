#!/usr/bin/env python3
"""Bidirectional control for the pre-flight wiring of the OTHER TWO runners.

`test_step_preflight.py` controls the wiring in `design_one_shot_runner` and
`phase3_one_shot_runner`. Measured at 855504f5, `grep -c step_preflight` was 13
and 16 there — and **0** in `analog_one_shot_runner` and
`phase1_one_shot_runner`. So the whole A1-A9 / D1 line dispatched every step
with no check that its inputs existed, and a starved analog track was recorded
as a track that had merely been waived.

Each control below FAILS against the byte-identical pre-change tree and PASSES
after, and each carries a REVERSE case that must STILL pass — so none of them
can be satisfied by a gate that simply refuses everything.

  ANALOG FORWARD   a synthetic analog project missing exactly ONE declared
                   input (D1's `L5_ADI_SPEC.json`) has A1 REFUSED: the step
                   function is never entered and the row is BLOCKED.
  ANALOG REVERSE   the SAME tree with that one file restored dispatches A1.
  PHASE1 FORWARD   a project with nothing staged has D1 REFUSED.
  PHASE1 REVERSE   the same project with one staged prompt runs it.
  THE D1 DECLARATION ITSELF. `flow/…yaml` used to declare D1's external input
                   as `phase1/input_prompt/* OR phase1/input_doc/*` — BOTH of
                   which this step WRITES (`phase1_doc_one_shot_runner`
                   extracts `input/docs/*` into `_path_layout.input_doc_dir()`).
                   Wiring the gate to that declaration would have REFUSED every
                   pristine run through either front door. The control pins the
                   staged entry points instead of the derived ones.
  WAIVED IS PROBED a waived span member's inputs are probed and RECORDED, and
                   NEVER refuse. Both halves are asserted, because either one
                   alone is a defect.
  BLOCKED IS NEVER GREEN in all FOUR runners' `_aggregate_verdict`.
  THE PUBLISHED CELLS still validate: no site refuses on any of them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))





# WHERE THE PUBLISHED CELLS ARE, AND THE WALK THAT WENT LOOKING FOR THEM OFF THE
# END OF THE CHECKOUT
# ---------------------------------------------------------------------------
# This used to be a local `_bench_ic()` that walked `PLUGIN` and EVERY ONE of its
# parents for a `benchmark-data/ic`, reasoning that the corpus "lives at the REPO
# root, not under the plugin". The reasoning was right in v1.10.55 and the walk
# was never bounded by it: `PLUGIN.parents` does not stop at the repo root, it
# runs to `/`.
#
# The corpus then left this repository (c5d7f2d00, v1.10.56), so inside any
# checkout the walk finds nothing and keeps climbing. MEASURED on this fleet,
# 2026-08-22, from a worktree at `$HOME/_jredmisc/base`:
#
#     .../plugins/vibe-ic/benchmark-data/ic      no
#     .../vibe-ic-marketplace/benchmark-data/ic  no
#     <repo root>/benchmark-data/ic              no
#     $HOME/benchmark-data/ic                    HIT   <- a DIFFERENT repository
#
# The hit is a separate clone of the published-corpus repo that happens to sit in
# a developer home directory, with the corpus pointer UNSET — nobody aimed
# anything at it. Its `ic/spm/v1.9.96_gf180mcuD` still exists as a directory but
# has held only `reports/` since the cells were withdrawn on 2026-08-20, so
# `root.is_dir()` was true, the parametrised cases below did NOT skip, and
# `phase1_one_shot_runner/doc_extract` was REFUSED for want of a
# `phase1/input_prompt/*` that a husk cannot have:
#
#     AssertionError: REFUSED TO RUN: 1 declared input(s) ABSENT
#     assert 'REFUSED' == 'READY'
#
# Both ids in this file were red on `origin/main` a4caccefe on THAT machine and
# green on a machine without that directory. The subject under test never entered
# into it, which is the whole reason the walk had to go.
#
# Resolution is handed to `_published_corpus`, this repository's ONE answer to
# "where is the corpus, and may it be absent": the pointer when it is set (and a
# RAISE, never a skip, when it is set and broken), else this repo's own
# `benchmark-data` while it still carries cells, else None — and never a
# directory reached by climbing out of the checkout. An absent corpus is then a
# NAMED skip that says it could not look, which is what these controls should
# always have said on a machine that has no corpus.

L_DOCS = (
    "L1_DATASHEET", "L2_FRS", "L3_CMD_PROTOCOL", "L4_REGMAP", "L5_ADI_SPEC",
    "L6_CONTROL_LOGIC", "L7_TEST_DEBUG", "L8_TIMING_WAVEFORM",
    "L8_RTL_CONSTANTS", "L9_INTEGRATION_SPEC", "L10_TEST_CASES",
    "L11_OTP_CONTENT", "L12_BEHAVIORAL_SEQUENCES", "L13_ANALOG",
)
L5 = "phase1/generated_docs/L5_ADI_SPEC.json"


def _analog_project(root: Path, with_l5: bool) -> Path:
    """A project the analog runner would drive: one declared block, a full L-doc
    set, and NOTHING produced yet. `with_l5` is the ONE variable."""
    p = root / "run"
    (p / "phase1/generated_docs").mkdir(parents=True, exist_ok=True)
    (p / "phase3/analog").mkdir(parents=True, exist_ok=True)
    for name in L_DOCS:
        if name == "L5_ADI_SPEC" and not with_l5:
            continue
        (p / "phase1/generated_docs" / f"{name}.json").write_text(
            json.dumps({"fields": {}}))
    (p / "phase3/analog/analog_block_list.json").write_text(json.dumps(
        {"blocks": [{"name": "blk_a", "type": "ldo"}]}))
    return p






# --------------------------------------------------------------------------- #
# ANALOG — forward / reverse / differ-by-one
# --------------------------------------------------------------------------- #




def test_analog_forward_and_reverse_differ_only_in_that_one_file(tmp_path):
    a = _analog_project(tmp_path / "a", with_l5=False)
    b = _analog_project(tmp_path / "b", with_l5=True)
    ra = {str(f.relative_to(a)) for f in a.rglob("*") if f.is_file()}
    rb = {str(f.relative_to(b)) for f in b.rglob("*") if f.is_file()}
    assert rb - ra == {L5}
    assert ra - rb == set()




# --------------------------------------------------------------------------- #
# PHASE 1 — forward / reverse
# --------------------------------------------------------------------------- #






# --------------------------------------------------------------------------- #
# BLOCKED is never green — in ALL FOUR runners now
# --------------------------------------------------------------------------- #


def test_the_analog_ladder_keeps_every_tier_it_had(tmp_path):
    """The BLOCKED tier is an ADDITION. Every pre-existing tier must still be
    reachable, or this would be a rewrite wearing a refactor's clothes."""
    import analog_one_shot_runner as A

    def row(status, **extra):
        return A.StepResult("A1_spec_extract", "blk_a", status, 0.0, "x",
                            **extra)

    assert A._aggregate_verdict([row("FAIL")]) == "FAIL"
    assert A._aggregate_verdict(
        [row("NOT_MEASURED", reason_class="not_executed")]) == "NOT_MEASURED"
    # A run whose ONLY row is N/A has an empty numerator, and an empty
    # numerator is not a pass: `run_verdict` answers NOT_MEASURED. N/A itself
    # still contributes nothing — one applicable step beside forty N/A ones is
    # exactly as good as its one step, which the next two lines show.
    assert A._aggregate_verdict(
        [row("NOT_APPLICABLE",
             declared_by="the input declares no analog block")]
    ) == "NOT_MEASURED"
    assert A._aggregate_verdict(
        [row("NOT_APPLICABLE",
             declared_by="the input declares no analog block"),
         row("PASS")]) == "PASS"
    assert A._aggregate_verdict(
        [row("PASS_WITH_WAIVERS", attribution="the sign-off engineer")]
    ) == "PASS_WITH_WAIVERS"
    assert A._aggregate_verdict(
        [row("PASS_WITH_WAIVERS", attribution="the sign-off engineer"),
         row("PASS")]) == "PASS_WITH_WAIVERS"
    assert A._aggregate_verdict([row("PASS")]) == "PASS"


# --------------------------------------------------------------------------- #
# DID THE WIRING REACH THE CODE THAT RUNS? — observed, not grepped
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# A WAIVED STEP IS STILL PRE-FLIGHTED — and still never refused
# --------------------------------------------------------------------------- #










# --------------------------------------------------------------------------- #
# BACKWARD COMPATIBILITY — the published cells must still validate
# --------------------------------------------------------------------------- #
# 2026-08-12, vibe-ic#905: the first entry was `u_hawaii_adc` — the IC ROOT, not
# a published cell. Three of these four name a `v<ver>_<PDK>` cell; that one named
# the directory the cells live in, and it validated only because a stray IC-level
# `phase1/generated_docs/` made the root LOOK like a runnable project. That stray
# tree is exactly what #905 reports and what this branch retires, so the entry
# stopped satisfying `A1` the moment its accident was removed:
#
#   u_hawaii_adc                  A1 REFUSED — L1_DATASHEET.json, L5_ADI_SPEC.json absent
#   u_hawaii_adc/v1.9.86_sky130A  A1 READY, no site refused, D1 READY
#
# Repointed at the published cell. This is not a baseline being moved to absorb a
# failure: the cell is what the section header ("the published cells must still
# validate") always meant, and it validates on BOTH sides of the retirement.
_PUBLISHED = ("u_hawaii_adc/v1.9.86_sky130A", "spm/v1.5.65_sky130A",
              "spm/v1.9.96_gf180mcuD", "spm/v1.5.58_ihp-sg13g2")
