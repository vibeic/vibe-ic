"""A waiver the runner wrote must not outlive the condition that produced it.

`waivers.json` is auto-generated from the run's WAIVED / ENV_UNAVAILABLE steps,
and each entry it writes carries `_autogen: true`. The emitter's rule was "if
the file exists, do nothing" — so nothing ever read that flag back, and a
waiver the runner would no longer issue kept excusing the design.

Measured: a step waived in one run; the cause was fixed; the next run's step
did not waive and its report contained no waiver — and the compliance gate
still reported

    ~ [WAIVED-DEFERRED] Step 31 ... ENV_UNAVAILABLE waiver applied
      (natural verdict was FAIL/MISSING)

from the stale file. A check that had stopped excusing the design went on
excusing it.

A HAND-AUTHORED file must still win outright; that is what the original rule
was protecting and it is preserved by looking at `_autogen`.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from phase3_one_shot_runner import StepResult, _autogen_waivers_json  # noqa: E402


def _read(p):
    return json.loads((p / "waivers.json").read_text())


def test_it_writes_a_waiver_for_a_waived_step(tmp_path):
    _autogen_waivers_json(
        tmp_path, [StepResult("drc", "ENV_UNAVAILABLE", 0.0, "no engine", [],
                              {"missing_tool": "someengine"})])
    w = _read(tmp_path)["waivers"]
    assert [x["step"] for x in w] == ["drc"]
    assert w[0]["_autogen"] is True


def test_its_own_stale_waiver_is_regenerated_not_kept(tmp_path):
    """Two steps waived, then only one — the file must follow the run."""
    _autogen_waivers_json(
        tmp_path, [StepResult("drc", "ENV_UNAVAILABLE", 0.0, "d", [],
                              {"missing_tool": "a"}),
                   StepResult("lvs", "WAIVED", 0.0, "l", [])])
    assert {x["step"] for x in _read(tmp_path)["waivers"]} == {"drc", "lvs"}
    _autogen_waivers_json(
        tmp_path, [StepResult("drc", "PASS", 0.0, "ran clean", []),
                   StepResult("lvs", "WAIVED", 0.0, "l", [])])
    assert {x["step"] for x in _read(tmp_path)["waivers"]} == {"lvs"}, (
        "the drc waiver must be gone: this run's drc step did not waive")


def test_a_run_that_waives_nothing_retracts_the_file(tmp_path):
    _autogen_waivers_json(
        tmp_path, [StepResult("drc", "ENV_UNAVAILABLE", 0.0, "d", [],
                              {"missing_tool": "a"})])
    assert (tmp_path / "waivers.json").is_file()
    _autogen_waivers_json(tmp_path, [StepResult("drc", "FAIL", 0.0, "15", [])])
    assert not (tmp_path / "waivers.json").exists(), (
        "a run that waives nothing must not leave a waiver behind")


def test_a_hand_authored_waiver_always_wins(tmp_path):
    human = {"_schema_version": "1",
             "waivers": [{"step": "drc", "ticket": "REAL-123",
                          "rationale": "signed off by the PV owner",
                          "review_required": True}]}
    (tmp_path / "waivers.json").write_text(json.dumps(human))
    _autogen_waivers_json(
        tmp_path, [StepResult("lvs", "WAIVED", 0.0, "l", [])])
    assert _read(tmp_path) == human, "a human file must never be rewritten"


def test_a_mixed_file_counts_as_hand_authored(tmp_path):
    """One human entry makes the whole file human-owned — the runner must not
    edit a file a person has curated."""
    mixed = {"_schema_version": "1",
             "waivers": [{"step": "drc", "_autogen": True},
                         {"step": "lvs", "ticket": "REAL-9"}]}
    (tmp_path / "waivers.json").write_text(json.dumps(mixed))
    _autogen_waivers_json(tmp_path, [StepResult("x", "PASS", 0.0, "", [])])
    assert _read(tmp_path) == mixed


def test_an_unreadable_file_is_left_alone(tmp_path):
    (tmp_path / "waivers.json").write_text("{not json")
    _autogen_waivers_json(tmp_path, [StepResult("x", "PASS", 0.0, "", [])])
    assert (tmp_path / "waivers.json").read_text() == "{not json"
