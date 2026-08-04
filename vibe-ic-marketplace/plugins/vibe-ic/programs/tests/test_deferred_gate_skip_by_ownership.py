#!/usr/bin/env python3
"""A deferred track skips a gate only when the deferral record NAMES it as
owned. Name resemblance must never decide a skip.

MEASURED DEFECT — two sites in `flow_compliance_check`, one rule.

  GATE LEVEL. `_skip_analog_p0_gates()` derived the `--skip-analog`
  suppression set from `_ANALOG_STRUCTURAL_GATE_PREFIXES`, so the question
  "may this deferral silence this gate?" was answered by how the gate was
  SPELLED. On one tree — input docs describing an LDO and a bandgap, with
  `L5_ADI_SPEC.json` carrying `analog_blocks: []`:

      skip_analog=False   analog_content_detected_must_emit_l5_check  FAIL
      skip_analog=True    analog_content_detected_must_emit_l5_check  SKIP
                          ("analog track deferred via --skip-analog")

  That gate does not own the analog deferral. Its subject is the Phase-1 L5
  RECORD — it reads `input/docs` + `generated_docs` and no A-step artefact, so
  deferring A1..A9 leaves it fully answerable — and it is the gate that makes
  an analog deferral REVIEWABLE at all: a deferred track whose content was
  never written down is an open item nobody can cost. Under the prefix rule
  the one run that defers the analog track was the one run that never had to
  admit it had any.

  STEP LEVEL. `check_step` deferred a step when `str(sid).startswith("A")`.
  The flow already RECORDS analog-track membership — every A1..A9 step
  declares `stage: stage_analog` — and the record was not consulted. Any step
  whose id merely begins with "A" was deferred while owning none of that
  deferral.

BIDIRECTIONAL. Two tests here are the negative control (they FAIL against the
byte-identical pre-fix program); the rest are the reverse case and MUST pass
in both directions, because a rule that fires on everything would also score
as a fix. Specifically: a legitimately-deferred analog track must still defer
— every gate the record DOES name stays skipped, every A-step in the shipped
flow stays skipped, and on a project whose L5 honestly records its analog
blocks the newly-un-skipped gate PASSES rather than blocking the deferral.

chip-AGNOSTIC: synthetic generic fixtures; every rule keys on the ownership
record or the flow's own `stage` field, never a chip / vendor / SKU / PDK
literal.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import flow_compliance_check as F  # noqa: E402

_POLICING_GATE = "analog_content_detected_must_emit_l5_check"
_ANALOG_SKIP_REASON = "analog track skipped via --skip-analog"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _digital_rtl(root: Path) -> None:
    rtl = root / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "chip_top.v").write_text(
        "module chip_top(input clk, input rst, output reg [7:0] dout);\n"
        "  always @(posedge clk or posedge rst)\n"
        "    if (rst) dout <= 8'b0; else dout <= dout + 1'b1;\n"
        "endmodule\n")


def _docs_with_analog_content(root: Path) -> None:
    """Generic analog prose — no chip, vendor or part number anywhere."""
    docs = root / "input" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "spec.txt").write_text(
        "Supply section\n"
        "The device integrates an on-chip LDO regulator for the core rail.\n"
        "A bandgap reference provides the trimmed 1.2 V VBG.\n")


def _l5(root: Path, blocks: list) -> None:
    gd = root / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L5_ADI_SPEC.json").write_text(json.dumps({"analog_blocks": blocks}))


def _undeclared_analog_project(root: Path) -> Path:
    """Analog content IN THE DOCS, absent from L5 — the state the policing
    gate exists to catch, and the state the prefix rule hid."""
    _digital_rtl(root)
    _docs_with_analog_content(root)
    _l5(root, [])
    return root


def _declared_analog_project(root: Path) -> Path:
    """THE REVERSE CASE. The same analog content, honestly recorded in L5, and
    no A-step artefacts (the analog track really is deferred). The policing
    gate has nothing to say; the deferral is legitimate and must survive."""
    _digital_rtl(root)
    _docs_with_analog_content(root)
    _l5(root, [
        {"name": "core_ldo", "type": "ldo", "specs": {"vout": 1.2}},
        {"name": "vbg_ref", "type": "bandgap", "specs": {"vbg": 1.2}},
    ])
    analog = root / "analog"
    analog.mkdir(parents=True, exist_ok=True)
    (analog / "analog_block_list.json").write_text(json.dumps(
        {"blocks": [{"name": "core_ldo"}, {"name": "vbg_ref"}]}))
    return root


def _record_for(records: list, gate: str) -> dict:
    hits = [r for r in records if r.get("name") == gate]
    assert len(hits) == 1, f"expected exactly one record for {gate}: {hits}"
    return hits[0]


# ---------------------------------------------------------------------------
# 1. The ownership record itself.
# ---------------------------------------------------------------------------
def test_skip_set_is_the_ownership_record_not_the_name_prefix():
    """`_skip_analog_p0_gates()` == registry ∩ ownership record. Every member
    is NAMED as owned; membership never follows from spelling."""
    skip = F._skip_analog_p0_gates()
    assert skip, "the analog-track deferral must still own gates"
    for g in skip:
        assert g in F._STRUCTURAL_RTL_GATES, f"{g} is not a registered gate"
        assert g in F._ANALOG_TRACK_OWNS, (
            f"{g} is skipped without being named in the ownership record")


def test_analog_named_but_unowned_gate_is_not_skipped():
    """NEGATIVE CONTROL (gate level, set form). The policing gate matches the
    analog naming convention and is NOT owned by the deferral, so it must not
    be in the suppression set. FAILS pre-fix: the prefix rule put it there."""
    assert F._is_analog_structural_gate(_POLICING_GATE), (
        "fixture assumption: the gate does follow the analog naming "
        "convention — that is precisely why resemblance mis-skipped it")
    assert _POLICING_GATE in F._ANALOG_NAMED_NOT_OWNED
    assert _POLICING_GATE not in F._skip_analog_p0_gates()


def test_ownership_record_is_total_over_analog_named_gates():
    """Registry-drift guard. The naming convention is allowed to DEMAND a
    declaration; it is never allowed to supply one. A newly-registered
    analog-named gate with no declaration is loud here instead of silently
    mis-skipped (at runtime it is fail-closed: it runs)."""
    undeclared = F._undeclared_analog_named_gates()
    assert undeclared == (), (
        "these registered analog-named gates declare no ownership — add each "
        "to _ANALOG_TRACK_OWNS (the deferral owns its verdict) or to "
        f"_ANALOG_NAMED_NOT_OWNED with a reason: {undeclared}")


def test_no_digital_gate_is_ever_owned_by_the_analog_deferral():
    """REVERSE CASE. The record must not have grown to swallow the digital
    floor — the failure mode a fix tuned until a count reached zero produces."""
    skip = F._skip_analog_p0_gates()
    for g in ("rig_topology_disclosure_check", "handshake_check",
              "bitwidth_consistency_check", "cdc_async_input_check",
              "crc_completeness_check"):
        assert g not in skip, f"{g} is a digital gate and must always run"
    for g in F._ANALOG_TRACK_OWNS:
        assert F._is_analog_structural_gate(g), (
            f"{g} is claimed by the analog deferral but is not an "
            f"analog-track gate")


# ---------------------------------------------------------------------------
# 2. Gate level, end to end through the P0 umbrella.
# ---------------------------------------------------------------------------
def test_undeclared_analog_content_still_gates_under_skip_analog(tmp_path):
    """NEGATIVE CONTROL (gate level, behavioural). --skip-analog must not
    silence the gate that reports analog content L5 never recorded.

    Pre-fix this record is verdict=SKIP with
    evidence.skip_kind='analog-track-deferred', so this FAILS."""
    proj = _undeclared_analog_project(tmp_path / "undeclared")
    records: list = []
    F._run_structural_rtl_gates(proj, skip_analog=True, records_out=records)
    rec = _record_for(records, _POLICING_GATE)
    assert rec["verdict"] == "FAIL", (
        f"the analog-track deferral does not own {_POLICING_GATE}; under "
        f"--skip-analog it must still run and report. Got: {rec}")
    assert rec["evidence"].get("skip_kind") != "analog-track-deferred"


def test_same_verdict_with_and_without_the_flag_for_an_unowned_gate(tmp_path):
    """NEGATIVE CONTROL, stated as the invariant rather than a literal: a gate
    the deferral does not own answers the SAME on the same tree whether or not
    the track is deferred. Pre-fix: FAIL vs SKIP."""
    proj = _undeclared_analog_project(tmp_path / "invariant")
    on: list = []
    off: list = []
    F._run_structural_rtl_gates(proj, skip_analog=True, records_out=on)
    F._run_structural_rtl_gates(proj, skip_analog=False, records_out=off)
    assert (_record_for(on, _POLICING_GATE)["verdict"]
            == _record_for(off, _POLICING_GATE)["verdict"])


def test_owned_gates_are_still_deferred_on_a_legitimate_deferral(tmp_path):
    """REVERSE CASE — the one that keeps this from being a rule that fires on
    everything. A project whose L5 honestly records its analog blocks, run
    with the analog track deferred: every gate the record NAMES is still
    skipped with the deferred-track reason, and none of them fails the run."""
    proj = _declared_analog_project(tmp_path / "declared")
    records: list = []
    _, fails, _, _ = F._run_structural_rtl_gates(
        proj, skip_analog=True, records_out=records)
    owned = F._skip_analog_p0_gates()
    assert owned, "fixture assumption: the deferral owns at least one gate"
    for g in sorted(owned):
        rec = _record_for(records, g)
        assert rec["verdict"] == "SKIP", (
            f"{g} IS named by the deferral record and must stay deferred "
            f"under --skip-analog. Got: {rec}")
        assert rec["evidence"].get("skip_kind") == "analog-track-deferred"
    for line in fails:
        assert not any(line.startswith(f"FAIL: {g} ") or line == f"FAIL: {g}"
                       for g in owned), (
            f"a deferred analog gate leaked into the fail list: {line}")


def test_unowned_gate_passes_when_the_property_legitimately_holds(tmp_path):
    """REVERSE CASE. Un-skipping the policing gate must not turn every
    deferred-analog run red: on the same deferred track, with L5 honestly
    recording the analog content, the gate RUNS and PASSES."""
    proj = _declared_analog_project(tmp_path / "declared_pass")
    records: list = []
    F._run_structural_rtl_gates(proj, skip_analog=True, records_out=records)
    rec = _record_for(records, _POLICING_GATE)
    assert rec["verdict"] == "PASS", (
        f"a legitimately-deferred analog track whose L5 records its blocks "
        f"must keep passing this gate. Got: {rec}")


# ---------------------------------------------------------------------------
# 3. Step level.
# ---------------------------------------------------------------------------
def _step(sid: str, stage: str) -> dict:
    return {"id": sid, "name": f"synthetic {sid}", "stage": stage}


def test_step_not_on_the_analog_track_is_not_deferred_by_it(tmp_path):
    """NEGATIVE CONTROL (step level). A step whose id merely BEGINS with "A"
    while the flow places it on another stage owns none of the analog
    deferral. Pre-fix `sid.startswith("A")` deferred it, so this FAILS."""
    proj = tmp_path / "steplevel"
    _digital_rtl(proj)
    for sid in ("AXI_LINT", "ATPG1", "AUDIT"):
        r = F.check_step(proj, _step(sid, "stage5_manufacturing"),
                         waivers={}, skip_analog=True)
        assert _ANALOG_SKIP_REASON not in r.reasons, (
            f"step {sid} is on stage5_manufacturing and owns no part of the "
            f"analog deferral, but --skip-analog deferred it: {r.reasons}")


def test_declared_analog_step_is_still_deferred(tmp_path):
    """REVERSE CASE (step level). A step the flow DECLARES on the analog
    track is still deferred — the flag keeps working."""
    proj = tmp_path / "steplevel_ok"
    _digital_rtl(proj)
    r = F.check_step(proj, _step("A5", "stage_analog"),
                     waivers={}, skip_analog=True)
    assert r.status == "SKIPPED-CONDITION"
    assert _ANALOG_SKIP_REASON in r.reasons


def test_step_with_no_declared_stage_is_fail_closed(tmp_path):
    """An absent record is not a claim of ownership: an id-shaped-like-analog
    step that declares no stage runs and gates, rather than being deferred."""
    proj = tmp_path / "steplevel_nostage"
    _digital_rtl(proj)
    r = F.check_step(proj, {"id": "A5", "name": "no stage declared"},
                     waivers={}, skip_analog=True)
    assert _ANALOG_SKIP_REASON not in r.reasons


def test_every_analog_step_in_the_shipped_flow_still_defers(tmp_path):
    """REVERSE CASE, on the real artefact rather than a synthetic one: the
    shipped flow's own stage records must reproduce the previous behaviour for
    every A-step, so this change is byte-identical on the canonical flow."""
    yaml = pytest.importorskip("yaml")
    flow_path = _PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"
    steps = (yaml.safe_load(flow_path.read_text()) or {}).get("steps", [])
    analog_steps = [s for s in steps
                    if str(s.get("stage") or "") == F._ANALOG_TRACK_STAGE]
    assert len(analog_steps) >= 9, (
        f"expected the A1..A9 analog track in the shipped flow, found "
        f"{len(analog_steps)}")
    proj = tmp_path / "shipped_flow"
    _digital_rtl(proj)
    for s in analog_steps:
        r = F.check_step(proj, s, waivers={}, skip_analog=True)
        assert r.status == "SKIPPED-CONDITION", (
            f"step {s.get('id')} declares stage_analog and must still be "
            f"deferred by --skip-analog")
        assert _ANALOG_SKIP_REASON in r.reasons
    # And the old predicate's population is a SUBSET of the declared one on
    # this flow — i.e. nothing that used to defer stops deferring here.
    id_prefixed = {str(s.get("id")) for s in steps
                   if str(s.get("id")).startswith("A")}
    declared = {str(s.get("id")) for s in analog_steps}
    assert id_prefixed == declared, (
        f"shipped flow drift: ids starting with 'A' {sorted(id_prefixed)} vs "
        f"steps declaring stage_analog {sorted(declared)}")
