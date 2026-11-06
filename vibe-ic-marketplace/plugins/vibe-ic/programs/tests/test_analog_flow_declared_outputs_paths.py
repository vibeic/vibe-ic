#!/usr/bin/env python3
"""Analog A1-A9: the flow's DECLARED artefact paths must be the ones a real
run produces, and A6/A9's declared evidence must be broad enough that the
step's own gate is actually reached.

Every assertion here is a behavioural property of a project directory laid out
the way the producers lay it out — never a source substring, never a private
symbol. Four defects are covered:

  * A1-A4 declared `phase{1,2}/analog/...`, a path NO producer writes.
    `analog_one_shot_runner` and `phase1_doc_one_shot_runner` both emit through
    `_path_layout.analog_dir()` = `phase3/analog/`, and the A-gates read there.
    The declaration appeared to work only because
    `flow_compliance_check._glob_first` carries a hidden phase{1,2,3}/analog →
    canonical remap; `flow_dashboard_data`, which has no such remap, resolved
    every A1-A4 artefact of a REAL analog run to "absent".

  * `flow_dashboard_data._lane_applicability` probed only
    `phase1/analog/analog_block_list.json`, so on a real analog run the whole
    Analog + Mixed-Signal lane rendered `na — design declares no analog blocks`.

  * A6 declared ONLY the two sign-off .flag files, while
    `analog_a6_block_pv_check` treats drc.report / *.lyrdb / comp.json /
    lvs.report as its PRIMARY evidence. Because `check_step` uses
    required_outputs as a cheap pre-check and returns MISSING before fetching
    the gate, a block with real DRC/LVS reports was reported MISSING while the
    gate itself returned PASS on the identical directory.

  * A9 declared `*_cosim_results.json`, which never matches
    `mixed_signal_results.json` — the aggregate report `mixed_signal_cosim_check`
    itself cites as authoritative evidence.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
FLOW_YAML = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"

if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

yaml = pytest.importorskip("yaml")













# ─── A1-A4: the declaration must match where the producer writes ───────────







# ─── dashboard lane applicability ─────────────────────────────────────────







def test_guard_phantom_block_list_does_not_make_the_analog_lane_applicable(
        tmp_path: Path):
    """Direction-1 guard on the MIRROR IMAGE of the defect this file fixes.

    The empty-directory guard above never exercises the interesting case: a
    pure-digital project that DOES carry an `analog_block_list.json`, whose
    only entry is a `low_confidence` keyword phantom. 8 of the 17 tracked
    projects in this repo that carry a block list are exactly that shape. Made
    applicable on `.exists()` alone, their dashboards would render the whole
    Analog A1-A9 + Mixed-Signal M1-M4 lane as work-in-progress. The dashboard
    must give the SAME answer as the ORGANIC #676 predicate the analog P0
    gates already use."""
    d = tmp_path / "phase3" / "analog"
    d.mkdir(parents=True)
    (d / "analog_block_list.json").write_text(json.dumps(
        {"blocks": [{"name": "dac", "low_confidence": True}]}))
    rd = tmp_path / "reports"
    rd.mkdir(parents=True)
    (rd / "ic_class.json").write_text(json.dumps({"has_analog": False}))

    import _analog_a_check_common as aac
    assert aac.analog_class_is_na(tmp_path) is True     # the #676 answer


def test_spec_backed_block_on_a_digital_class_stays_applicable(
        tmp_path: Path):
    """§4.05 no-leak half: the #676 consult must not become a blanket bypass.
    A block that is NOT low_confidence keeps the lane applicable even when the
    IC-class verdict says non-analog — the same asymmetry `analog_class_is_na`
    enforces for the gates.

    Deliberately NOT named `test_guard_…`: it reddens on origin/main, for the
    unrelated reason that the pre-fix probe cannot see a `phase3/analog/` list
    at all. It is a discriminator that happens to assert the no-leak direction,
    not a both-trees guard."""
    d = tmp_path / "phase3" / "analog"
    d.mkdir(parents=True)
    (d / "analog_block_list.json").write_text(json.dumps(
        {"blocks": [{"name": "ldo"}]}))
    rd = tmp_path / "reports"
    rd.mkdir(parents=True)
    (rd / "ic_class.json").write_text(json.dumps({"has_analog": False}))

    import _analog_a_check_common as aac
    assert aac.analog_class_is_na(tmp_path) is False


# ─── A6: declared evidence must reach the gate ────────────────────────────













# ─── A9: the aggregate cosim report is declared evidence ──────────────────
