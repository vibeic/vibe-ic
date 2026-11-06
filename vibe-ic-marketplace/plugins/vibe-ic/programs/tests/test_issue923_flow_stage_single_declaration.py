#!/usr/bin/env python3
"""vibe-ic#923 — stage membership is declared once, and the guard says so.

TWO ARMS, AND WHICH IS WHICH
============================
Everything here runs the SHIPPED PROGRAM as a subprocess and reads its exit
code and its ``--json`` record. Nothing recomputes the rule locally, because a
test that re-derives the answer answers itself and passes against an unfixed
tree.

DISCRIMINATOR — must FAIL before the data fix, PASS after:

    test_shipped_flow_declares_membership_exactly_once

    measured with `git checkout origin/main -- flow/phase1_phase2_phase3.yaml`:
        rc=2, 8 second membership declaration(s) in stages[]

PAIRED GUARDS — must hold on BOTH the roster-carrying flow and the roster-free
one, so a future "fix" cannot satisfy the discriminator by moving steps or by
deleting the surviving declaration instead of the duplicate:

    test_numeric_backbone_is_contiguous_and_follows_declared_stage_order
    test_the_only_stages_consumer_is_indifferent_to_the_roster
    test_deleting_the_surviving_declaration_is_also_a_failure
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402
# Imported, not only driven by subprocess: `analyze()` is the predicate, and an
# import edge is also what makes this file SELECTABLE when the checker changes.

yaml = pytest.importorskip("yaml")

_PLUGIN = Path(__file__).resolve().parents[2]
_PROG = _PLUGIN / "programs" / "flow_stage_membership_single_declaration_check.py"
_CONSUMER = _PLUGIN / "programs" / "phase1_planned_consumer_starved_check.py"
_FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"





def _mutate(tmp_path: Path, fn, name="mutant.yaml") -> Path:
    doc = yaml.safe_load(_FLOW.read_text(encoding="utf-8"))
    fn(doc)
    p = tmp_path / name
    p.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
                 encoding="utf-8")
    return p


def _restore_roster(doc, key="steps"):
    """Put back the roster exactly as origin/main carried it — including the
    four cut points it disagreed with the step fields about (14, 32, 38, 39)."""
    roster = {
        "stage_phase1": ["D1"],
        "stage1": [1, 2, 3, 4, 5, 6],
        "stage2": [7, 8, 9, 10, 11, 12, 13],
        "stage_analog": ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9"],
        "stage3": list(range(14, 32)),
        "stage_mixed_signal": ["M1", "M2", "M3", "M4"],
        "stage4": [32, 33, 34, 35, 36, 37],
        "stage5_manufacturing": [38, 39, 40, 41],
    }
    for st in doc["stages"]:
        if st["id"] in roster:
            st[key] = roster[st["id"]]


# ── the premise ─────────────────────────────────────────────────────────────


# ── DISCRIMINATOR ───────────────────────────────────────────────────────────








#: The four cut points #923 reconciled: where origin/main's roster and the
#: per-step fields disagreed about a stage BOUNDARY on the day it landed.
_RECONCILED_AT_923 = ["14", "32", "38", "39"]




# ── PAIRED GUARDS — true on BOTH arms ───────────────────────────────────────
















# ── the load-bearing claim of the fix, tested on the real consumer ──────────
def test_the_only_stages_consumer_is_indifferent_to_the_roster(tmp_path):
    """GUARD, and the reason the roster is what lost.

    `phase1_planned_consumer_starved_check` is the ONLY shipped program that
    loads `flow['stages']` at all. Run it against a substantive project with
    the roster present and with it absent: byte-identical record. The roster
    was inert, so removing it moved no step for any consumer.
    """
    if not _CONSUMER.is_file():
        pytest.skip(f"{_CONSUMER.name} not present in this tree")
    empty = {"doc_class": "behavioral_sequences", "sequences": [],
             "state_machines": [], "extraction_evidence": {}}
    full = {"doc_class": "timing_waveform",
            "timing_windows": [{"name": "t_setup", "min_ns": 5}],
            "timing_constants": [], "waveforms": [], "extraction_evidence": {}}

    with_roster = _mutate(tmp_path, _restore_roster, name="withroster.yaml")

    records = {}
    for tag, flow in (("with", with_roster), ("without", _FLOW)):
        proj = tmp_path / f"proj_{tag}"
        shutil.rmtree(proj, ignore_errors=True)
        gd = proj / "phase1" / "generated_docs"
        gd.mkdir(parents=True)
        (gd / "L12_behavioral_sequences.json").write_text(json.dumps(empty))
        (gd / "L8_timing_waveform.json").write_text(json.dumps(full))
        out = tmp_path / f"consumer_{tag}.json"
        r = _pr.run(
            [sys.executable, str(_CONSUMER), str(proj),
             "--flow", str(flow), "--json", str(out)],
            capture_output=True, text=True)
        assert out.is_file(), f"{tag}: no record written\n{r.stdout}\n{r.stderr}"
        body = out.read_text().replace(f"proj_{tag}", "PROJ")
        records[tag] = json.loads(body)

    assert records["with"]["declared_consumers"] == \
        records["without"]["declared_consumers"], (
        "removing the roster changed how many layer consumers the flow "
        "declares — it was not inert after all")
    assert json.dumps(records["with"], sort_keys=True) == \
        json.dumps(records["without"], sort_keys=True), (
        "the only program that loads flow['stages'] produced a different "
        "record with and without the roster")


# ── P1: a ROSTER is a collection; a BACK-POINTER is a scalar ──────────────
# The reading landed with the `dispatched_by` fix. Before it, `_flatten` walked
# the whole `on_pass_review` sub-tree and collected the single scalar
# `dispatched_by: '7'`, so the flow went red on P1 at the moment it obeyed
# `on_pass_review_declared_command_runs_check` P3 ("a pointer nobody checks is a
# comment"). There was no state of the flow in which both gates were green.
#
# These arms are the falsification in BOTH directions: every roster SHAPE the
# predicate is supposed to catch must still be caught, and the one shape it is
# supposed to let through must pass. A rule that only ever sees the passing arm
# is a mute button, not a reading.
