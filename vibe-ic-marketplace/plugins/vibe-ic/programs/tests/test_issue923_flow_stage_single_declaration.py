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
import re
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

yaml = pytest.importorskip("yaml")

_PLUGIN = Path(__file__).resolve().parents[2]
_PROG = _PLUGIN / "programs" / "flow_stage_membership_single_declaration_check.py"
_CONSUMER = _PLUGIN / "programs" / "phase1_planned_consumer_starved_check.py"
_FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"

def _run(flow: Path, out: Path):
    """The program, as CI runs it. Returns (CompletedProcess, record|None)."""
    r = _pr.run(
        [sys.executable, str(_PROG), "--flow", str(flow), "--json", str(out)],
        capture_output=True, text=True)
    rec = json.loads(out.read_text()) if out.is_file() else None
    return r, rec


@pytest.fixture(scope="module")
def shipped(tmp_path_factory):
    out = tmp_path_factory.mktemp("shipped") / "rec.json"
    return _run(_FLOW, out)


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
def test_the_program_and_the_flow_are_both_present():
    assert _PROG.is_file(), f"premise: {_PROG} must ship"
    assert _FLOW.is_file(), f"premise: {_FLOW} must ship"


# ── DISCRIMINATOR ───────────────────────────────────────────────────────────
def test_shipped_flow_declares_membership_exactly_once(shipped):
    """Against origin/main's flow this program exits 2 and names eight rosters.

    The assertion is on the PROGRAM's verdict over the SHIPPED file, so it
    cannot pass unless the committed data actually carries one declaration.
    """
    r, rec = shipped
    assert r.returncode == 0, (
        f"flow_stage_membership_single_declaration_check exited "
        f"{r.returncode} on the shipped flow:\n{r.stdout}\n{r.stderr}")
    assert rec is not None
    assert rec["second_declarations"] == [], (
        "stages[] carries a membership roster besides the per-step `stage:` "
        f"field: {rec['second_declarations']}")
    assert rec["findings"] == 0, rec


def test_the_guard_fires_when_a_roster_reappears_under_any_name(tmp_path):
    """The acceptance criterion: a SECOND declaration must be impossible, not
    merely noisy. Key name is not the discriminator — naming step ids is."""
    for key in ("steps", "members", "step_ids", "contains"):
        p = _mutate(tmp_path, lambda d, k=key: _restore_roster(d, k),
                    name=f"roster_{key}.yaml")
        r, rec = _run(p, tmp_path / f"rec_{key}.json")
        assert r.returncode == 2, (
            f"a roster re-added under `{key}:` was accepted (rc={r.returncode}):"
            f"\n{r.stdout}")
        assert rec is not None and rec["second_declarations"], rec
        assert key in {d["key"] for d in rec["second_declarations"]}, rec


def test_the_reintroduced_roster_would_carry_the_same_four_contradictions(tmp_path):
    """Not a rule — the RECORD of what was reconciled. The roster this test
    puts back is origin/main's, and against the surviving per-step fields it
    still disagrees about exactly steps 14, 32, 38 and 39."""
    p = _mutate(tmp_path, _restore_roster, name="asmain.yaml")
    r, rec = _run(p, tmp_path / "asmain.json")
    assert r.returncode == 2
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    field = {str(s["id"]): str(s.get("stage")) for s in doc["steps"]}
    clash = sorted(
        str(sid) for st in doc["stages"] for sid in st.get("steps", [])
        if str(sid) in field and field[str(sid)] != st["id"])
    assert clash == ["14", "32", "38", "39"], clash


# ── PAIRED GUARDS — true on BOTH arms ───────────────────────────────────────
def _membership_from_program(rec):
    return rec["declared_stage_ids"], rec["membership"]


def _numeric_runs(declared_ids, membership):
    """Read out of the PROGRAM's record; no local re-derivation of the rule."""
    runs = []
    for sid in declared_ids:
        nums = sorted(int(x) for x in membership.get(sid, [])
                      if re.fullmatch(r"[0-9]+", str(x)))
        if nums:
            runs.append((sid, nums))
    return runs


@pytest.mark.parametrize("arm", ["roster_free", "roster_carrying"])
def test_numeric_backbone_is_contiguous_and_follows_declared_stage_order(
        arm, tmp_path, shipped):
    """GUARD. The numeric steps must form gapless, non-overlapping runs in the
    order the stages are declared. It held before the roster was deleted and it
    holds after, so it cannot be traded away to satisfy the discriminator: a
    'fix' that scattered steps to make one declaration true would break it.
    """
    if arm == "roster_free":
        _, rec = shipped
    else:
        p = _mutate(tmp_path, _restore_roster, name="guard.yaml")
        _, rec = _run(p, tmp_path / "guard.json")
    declared_ids, membership = _membership_from_program(rec)
    runs = _numeric_runs(declared_ids, membership)
    assert len(runs) >= 4, f"too few numeric stages to be the backbone: {runs}"
    prev_end = 0
    for sid, nums in runs:
        assert nums == list(range(nums[0], nums[-1] + 1)), (
            f"stage {sid} numeric members are not contiguous: {nums}")
        assert nums[0] == prev_end + 1, (
            f"stage {sid} starts at {nums[0]}, expected {prev_end + 1} — the "
            f"numeric backbone has a gap or an overlap")
        prev_end = nums[-1]


def test_every_step_resolves_to_a_declared_stage(shipped):
    """GUARD (P2). Deleting the roster left the field as the ONLY declaration;
    a step without a resolvable one now belongs to no stage at all."""
    _, rec = shipped
    assert rec["dangling_stage_refs"] == [], rec["dangling_stage_refs"]
    assert rec["steps_examined"] > 0
    assert sum(len(v) for v in rec["membership"].values()) == rec["steps_examined"]


def test_no_declared_stage_is_left_without_members(shipped):
    """GUARD (P3)."""
    _, rec = shipped
    assert rec["stages_with_no_members"] == [], rec["stages_with_no_members"]
    assert rec["stages_examined"] == len(rec["declared_stage_ids"]) > 0


def test_deleting_the_surviving_declaration_is_also_a_failure(tmp_path):
    """GUARD, and the anti-laundering one. 'One declaration' must not be
    reachable by deleting the per-step field — that would leave ZERO."""
    def drop_a_field(doc):
        doc["steps"][10].pop("stage", None)
    p = _mutate(tmp_path, drop_a_field, name="nofield.yaml")
    r, rec = _run(p, tmp_path / "nofield.json")
    assert r.returncode == 2, r.stdout
    assert rec["dangling_stage_refs"], rec

    def point_nowhere(doc):
        doc["steps"][10]["stage"] = "stage_that_is_not_declared"
    p2 = _mutate(tmp_path, point_nowhere, name="dangling.yaml")
    r2, rec2 = _run(p2, tmp_path / "dangling.json")
    assert r2.returncode == 2, r2.stdout
    assert rec2["dangling_stage_refs"], rec2


def test_a_stage_no_step_names_is_a_failure(tmp_path):
    def add_orphan(doc):
        doc["stages"].append({"id": "stage_nobody_joins", "name": "orphan"})
    p = _mutate(tmp_path, add_orphan, name="orphan.yaml")
    r, rec = _run(p, tmp_path / "orphan.json")
    assert r.returncode == 2, r.stdout
    assert rec["stages_with_no_members"] == ["stage_nobody_joins"], rec


def test_a_zero_denominator_refuses_rather_than_passing(tmp_path):
    p = tmp_path / "empty.yaml"
    p.write_text("stages: []\nsteps: []\n", encoding="utf-8")
    r, _ = _run(p, tmp_path / "empty.json")
    assert r.returncode == 2, r.stdout
    assert "NOT CHECKED" in r.stdout

    missing = tmp_path / "does_not_exist.yaml"
    r2 = _pr.run([sys.executable, str(_PROG), "--flow", str(missing)],
                        capture_output=True, text=True)
    assert r2.returncode == 2 and "NOT CHECKED" in r2.stdout, r2.stdout


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
