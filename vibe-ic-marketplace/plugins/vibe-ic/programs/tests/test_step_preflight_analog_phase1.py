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

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import step_preflight as SP                                    # noqa: E402


PLUGIN = PROGRAMS.parent

import _published_corpus as PC                                 # noqa: E402

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
def _cell_root(cell: str):
    """The published cell `cell` under the resolved corpus, or None."""
    return PC.named_cell(*cell.split("/"))

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


class _Spy:
    """Stands in for `step_for_block` / `step_ingest_render`."""

    def __init__(self):
        self.calls = 0

    def __call__(self, *a, **kw):
        self.calls += 1

        class R:
            name = "spy"
            status = "PASS"
            detail = "spy ran"
        return R()


def _refusal_factory(name):
    def _mk(detail, extras):
        class R:
            pass
        r = R()
        r.name = name
        r.status = SP.REFUSAL_STATUS
        r.detail = detail
        r.extras = extras
        return r
    return _mk


# --------------------------------------------------------------------------- #
# ANALOG — forward / reverse / differ-by-one
# --------------------------------------------------------------------------- #
def test_analog_forward_absent_l5_refuses_a1_before_the_step_runs(tmp_path):
    p = _analog_project(tmp_path, with_l5=False)
    spy = _Spy()

    r = SP.gate(p, "analog_one_shot_runner", "A1",
                _refusal_factory("A1_spec_extract"),
                spy, p, {"name": "blk_a"}, "A1_spec_extract",
                _preflight_note="block=blk_a")

    assert spy.calls == 0, "A1 was DISPATCHED despite its declared input being absent"
    assert r.status == SP.REFUSAL_STATUS
    assert r.extras["finding"] == SP.REFUSAL_FINDING
    assert L5 in r.detail and "owed by step D1" in r.detail

    led = json.loads(SP.ledger_path(p).read_text())
    assert led["counts"]["REFUSED"] == 1
    assert led["refused"][0]["site"] == "A1"
    # the block the decision was about is IN the record, not inferable from it
    assert "block=blk_a" in led["decisions"][0]["notes"]


def test_analog_reverse_same_tree_with_l5_dispatches_a1(tmp_path):
    p = _analog_project(tmp_path, with_l5=True)
    spy = _Spy()

    r = SP.gate(p, "analog_one_shot_runner", "A1",
                _refusal_factory("A1_spec_extract"),
                spy, p, {"name": "blk_a"}, "A1_spec_extract")

    assert spy.calls == 1, "A1 was refused even though its declared inputs are present"
    assert r.status == "PASS"
    led = json.loads(SP.ledger_path(p).read_text())
    assert led["decisions"][0]["verdict"] == "READY"


def test_analog_forward_and_reverse_differ_only_in_that_one_file(tmp_path):
    a = _analog_project(tmp_path / "a", with_l5=False)
    b = _analog_project(tmp_path / "b", with_l5=True)
    ra = {str(f.relative_to(a)) for f in a.rglob("*") if f.is_file()}
    rb = {str(f.relative_to(b)) for f in b.rglob("*") if f.is_file()}
    assert rb - ra == {L5}
    assert ra - rb == set()


def test_analog_chain_refuses_at_the_step_whose_producer_never_ran(tmp_path):
    """The point of a per-step gate rather than one gate for the track: with
    every L-doc present, A1 is READY and A2 is REFUSED, because A1's artefact
    does not exist yet. The two answers must be different."""
    p = _analog_project(tmp_path, with_l5=True)
    assert SP.decide(p, "analog_one_shot_runner", "A1").verdict == "READY"
    d2 = SP.decide(p, "analog_one_shot_runner", "A2")
    assert d2.verdict == "REFUSED" and d2.allow is False
    assert any(i["from"] == "A1" and i["state"] == "absent" for i in d2.inputs)


# --------------------------------------------------------------------------- #
# PHASE 1 — forward / reverse
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("staged", [
    "input/docs/spec.md",
    "input/phase1_prompt.md",
    "input/phase1_structured.yaml",
    "phase1/input_doc/L1.txt",
    "phase1/input_prompt/dialogue.md",
])
def test_phase1_reverse_every_real_front_door_is_ready(tmp_path, staged):
    """THE DECLARATION CONTROL. Before this change the flow declared D1's input
    as the two DERIVED paths only, so a pristine tree entered through
    `input/docs/` or `input/phase1_prompt.md` was REFUSED — the gate would have
    bricked every first run. Each staged entry point must be enough on its own."""
    p = tmp_path / staged.split("/")[0]
    f = tmp_path / staged
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("a 4-bit counter\n")
    d = SP.decide(tmp_path, "phase1_one_shot_runner", "doc_extract")
    assert d.verdict == "READY", f"{staged} does not satisfy D1's declaration"
    assert d.allow is True
    assert p.exists()


def test_phase1_forward_nothing_staged_refuses_before_the_track_runs(tmp_path):
    (tmp_path / "input").mkdir()
    spy = _Spy()
    r = SP.gate(tmp_path, "phase1_one_shot_runner", "doc_extract",
                _refusal_factory("phase1_ingest_render"), spy, tmp_path, "IC")
    assert spy.calls == 0
    assert r.status == SP.REFUSAL_STATUS
    led = json.loads(SP.ledger_path(tmp_path).read_text())
    assert led["decisions"][0]["verdict"] == "REFUSED"


def test_phase1_a_refusal_is_never_green_end_to_end(tmp_path):
    """The row must also SURVIVE the runner's own verdict ladder. Measured at
    855504f5: an empty project reported `PASS_WITH_WAIVERS` and exit 0."""
    import phase1_one_shot_runner as P1
    row = P1.StepResult("phase1_ingest_render", SP.REFUSAL_STATUS, 0.0, "refused")
    assert P1._aggregate_verdict([row]) == "FAIL"
    ok = P1.StepResult("phase1_human_docs", "WAIVED", 0.0, "no MD")
    assert P1._aggregate_verdict([ok]) == "PASS_WITH_WAIVERS"   # reverse case
    assert P1._aggregate_verdict([ok, row]) == "FAIL"


# --------------------------------------------------------------------------- #
# BLOCKED is never green — in ALL FOUR runners now
# --------------------------------------------------------------------------- #
def test_blocked_is_never_green_in_the_two_newly_wired_runners():
    import analog_one_shot_runner as A
    import phase1_one_shot_runner as P1

    a_row = A.StepResult("A1_spec_extract", "blk_a", SP.REFUSAL_STATUS, 0.0, "x")
    assert A._aggregate_verdict([a_row]) == "FAIL"
    a_ok = A.StepResult("A1_spec_extract", "blk_a", "PASS", 0.0, "x")
    assert A._aggregate_verdict([a_ok]) == "PASS"               # reverse case
    assert A._aggregate_verdict([a_ok, a_row]) == "FAIL"

    p_row = P1.StepResult("x", SP.REFUSAL_STATUS, 0.0, "x")
    assert P1._aggregate_verdict([p_row]) == "FAIL"
    assert P1._aggregate_verdict([P1.StepResult("y", "PASS", 0.0, "x")]) == "PASS"


def test_the_analog_ladder_keeps_every_tier_it_had(tmp_path):
    """The BLOCKED tier is an ADDITION. Every pre-existing tier must still be
    reachable, or this would be a rewrite wearing a refactor's clothes."""
    import analog_one_shot_runner as A

    def row(status):
        return A.StepResult("A1_spec_extract", "blk_a", status, 0.0, "x")

    assert A._aggregate_verdict([row("FAIL")]) == "FAIL"
    assert A._aggregate_verdict([row("VACUOUS_PASS")]) == "VACUOUS_PASS"
    assert A._aggregate_verdict([row("PASS_STRUCTURE_ONLY")]) == "PASS_STRUCTURE_ONLY"
    assert A._aggregate_verdict([row("WAIVED"), row("PASS")]) == "PASS_WITH_WAIVERS"
    assert A._aggregate_verdict([row("PASS")]) == "PASS"


# --------------------------------------------------------------------------- #
# DID THE WIRING REACH THE CODE THAT RUNS? — observed, not grepped
# --------------------------------------------------------------------------- #
def test_the_analog_runner_gates_every_a_step_of_every_block(tmp_path,
                                                             monkeypatch):
    """The nine call sites are written out, so drift between them,
    `_AI_STEP_NAMES` and `RUNNER_PLANS` is possible. This observes the DISPATCH
    rather than the source text: every A-step of every block must pass through
    `gate`, at its own site, in `_AI_STEP_NAMES` order."""
    import analog_one_shot_runner as A

    p = _analog_project(tmp_path, with_l5=True)
    (p / "phase3/analog/analog_block_list.json").write_text(json.dumps(
        {"blocks": [{"name": "blk_a", "type": "ldo"},
                    {"name": "blk_b", "type": "bandgap"}]}))

    seen = []

    def _spy_gate(project, runner, site, refusal, fn, *a, **kw):
        seen.append((runner, site, a[2] if len(a) > 2 else None,
                     kw.get("_preflight_note")))
        return A.StepResult(a[2], a[1].get("name"), "PASS", 0.0, "spy")

    monkeypatch.setattr(A._spf, "gate", _spy_gate)
    monkeypatch.setattr(sys, "argv", ["analog_one_shot_runner", str(p)])
    A.main()

    sites = [s for _r, s, _n, _b in seen]
    steps = [n for _r, _s, n, _b in seen]
    declared = [s for s, _ in SP.RUNNER_PLANS["analog_one_shot_runner"].sites]
    assert sites == declared * 2, (
        "an A-step was dispatched outside the gate, or out of order")
    assert steps == list(A._AI_STEP_NAMES) * 2
    assert {b for _r, _s, _n, b in seen} == {"block=blk_a", "block=blk_b"}
    assert {r for r, _s, _n, _b in seen} == {"analog_one_shot_runner"}


# --------------------------------------------------------------------------- #
# A WAIVED STEP IS STILL PRE-FLIGHTED — and still never refused
# --------------------------------------------------------------------------- #
def _waive_a2(project: Path) -> None:
    """A REAL `waivers.json`, not a monkeypatched loader.

    `step_preflight.decide` imports `flow_compliance_check` LOCALLY, and a
    monkeypatch on this module's own reference to it is only the same object
    while nothing else in the session has re-imported or reloaded it. Measured:
    these three cases passed standalone and FAILED inside a 176-file run.
    Writing the file exercises the real loader and cannot drift."""
    (project / "waivers.json").write_text(json.dumps({
        "_schema_version": "1",
        "waived_steps": [{
            "id": "A2",
            "reason": ("no simulator on this host — the A2 topology selector "
                       "cannot be exercised here; DEFERRED to a host with "
                       "ngspice [ticket=unit-test, review_required=True]"),
            "approver": "unit-test",
            "ticket": "unit-test",
            "verdict_tier": "ENV_UNAVAILABLE",
            "review_required": True,
            "evidence": ["reports/phase3/analog_one_shot.json"],
        }],
    }))


def test_a_waived_step_has_its_inputs_probed_and_recorded(tmp_path):
    p = _analog_project(tmp_path, with_l5=True)
    _waive_a2(p)
    d = SP.decide(p, "analog_one_shot_runner", "A2")

    # (1) it may NEVER refuse — a waiver only ever EXCUSES, so authoring one
    #     must not newly BLOCK a step that runs today.
    assert d.allow is True
    assert d.verdict == "WAIVED-ONLY"
    # (2) …and it must NOT read as "there is nothing to be starved of": the
    #     absent input is named, with its producer, in the record.
    absent = [i for i in d.inputs if i["state"] == "absent-under-waiver"]
    assert absent, "a waived step's inputs were never probed"
    assert absent[0]["from"] == "A1"
    assert absent[0]["waived"] is True
    assert "A1" in d.detail or "waived" in d.detail.lower()


def test_a_waived_step_whose_inputs_are_present_says_so(tmp_path):
    """REVERSE half: the probe must be able to come back clean, or `absent-
    under-waiver` is a label nothing can avoid."""
    p = _analog_project(tmp_path, with_l5=True)
    _waive_a2(p)
    (p / "phase3/analog/blk_a").mkdir(parents=True, exist_ok=True)
    (p / "phase3/analog/blk_a/spec.json").write_text(json.dumps({"block": "blk_a"}))
    d = SP.decide(p, "analog_one_shot_runner", "A2")
    assert d.verdict == "WAIVED-ONLY" and d.allow is True
    assert not [i for i in d.inputs if i["state"] == "absent-under-waiver"]
    assert [i for i in d.inputs if i["state"] == "present-under-waiver"]


def test_condition_unmet_is_not_the_same_verdict_as_waived(tmp_path):
    """A step that will not run AT ALL and a step that runs under a waiver are
    different facts; one NOT-JUDGED for both is how the second one hid."""
    p = tmp_path / "digital"
    (p / "phase1/generated_docs").mkdir(parents=True)
    d = SP.decide(p, "analog_one_shot_runner", "A2")
    assert d.verdict == "NOT-JUDGED"
    assert "unmet condition" in d.detail


def test_a_malformed_waivers_file_does_not_kill_the_run(tmp_path):
    """`_load_waivers` exits the process on a bad waivers.json — correct in the
    acceptance auditor, a brand-new way to brick a run if it happened at the
    FIRST DISPATCH of one. A real truncated file, not a stubbed raiser."""
    p = _analog_project(tmp_path, with_l5=True)
    (p / "waivers.json").write_text("{not json")
    d = SP.decide(p, "analog_one_shot_runner", "A1")
    assert d.verdict == "UNAVAILABLE"
    assert d.allow is True
    assert "waivers.json" in d.detail
    # REVERSE: the same tree with a VALID waivers.json is decided normally, so
    # UNAVAILABLE is a statement about the file and not about this code path.
    _waive_a2(p)
    assert SP.decide(p, "analog_one_shot_runner", "A1").verdict == "READY"


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


@pytest.mark.parametrize("cell", _PUBLISHED)
def test_no_published_cell_is_refused_at_any_newly_wired_site(cell):
    root = _cell_root(cell)
    if root is None:
        pytest.skip(f"{cell}: {PC.SKIP_REASON}")
    refused = []
    for runner, sites in (("phase1_one_shot_runner", ("doc_extract",)),
                          ("analog_one_shot_runner",
                           tuple(s for s, _ in
                                 SP.RUNNER_PLANS["analog_one_shot_runner"].sites))):
        for site in sites:
            d = SP.decide(root, runner, site)
            if d.verdict == "REFUSED":
                refused.append((runner, site, d.detail[:160]))
    assert not refused, f"{cell} would now be refused at {refused}"


@pytest.mark.parametrize("cell", _PUBLISHED)
def test_every_published_cell_still_satisfies_d1s_declaration(cell):
    root = _cell_root(cell)
    if root is None:
        pytest.skip(f"{cell}: {PC.SKIP_REASON}")
    d = SP.decide(root, "phase1_one_shot_runner", "doc_extract")
    assert d.verdict == "READY", d.detail
