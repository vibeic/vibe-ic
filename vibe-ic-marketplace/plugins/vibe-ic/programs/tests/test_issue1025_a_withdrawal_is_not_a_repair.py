"""A fall in the ratchet's count is not automatically work someone did. #1025.

WHAT WAS WRONG
==============
`step_internal_fail_bubble_up_check --corpus` ratchets a count that "MAY ONLY
SHRINK", and on any shrink it printed:

    [PASS] 7 -> 5; lower the baseline so the recorded number stops claiming
    debt that is paid.

"debt that is paid" is a claim about WORK. A total can also fall because a run
LEFT THE PUBLISHED CORPUS, and a withdrawal is not a repair — the reports still
say FAIL, nobody examined them, they are merely no longer published.

MEASURED at `a38902d1`, which is exactly that case:

    sha256/clean_run_v1422_20260715   baseline 2 -> now 2   unchanged
    sha256/clean_run_v1427_20260715   baseline 3 -> now 3   unchanged
    u_hawaii_adc/clean_run_v1422...   baseline 1 -> WITHDRAWN
    u_hawaii_adc/clean_run_v1427...   baseline 1 -> WITHDRAWN

7 -> 5, and **zero findings were repaired**. Because the number may only ever
go down, recording that as debt paid would permanently lower the bar on the
strength of a publishing decision.

THE SECOND HALF, AND WHY THE FIRST WAS INVISIBLE
================================================
The baseline file has always carried a `per_run` map and `_load_baseline`
returned `findings_total` ALONE — nothing ever read the map back. So the
ratchet compared one scalar to another and could not have told the two cases
apart even in principle.

And when it is read back, the two sides do not agree on the key spelling: the
committed baseline says `sha256/clean_run_v1422_20260715`, a sweep of
`benchmark-data` emits `ic/sha256/clean_run_v1422_20260715`. Compared verbatim
EVERY baseline run reads as absent from EVERY sweep, so the naive comparison
would have called all seven withdrawn — including the five sitting in the same
output. `_run_key` normalises the corpus component; that it does not go further
and match on a bare tail is pinned below, because that would let one design's
run answer for another's.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLUGIN / "programs"))
import step_internal_fail_bubble_up_check as C  # noqa: E402

PROG = PLUGIN / "programs" / "step_internal_fail_bubble_up_check.py"


# ---------------------------------------------------------------------------
# the key spelling the two sides never agreed on
# ---------------------------------------------------------------------------
def test_the_corpus_component_is_normalised_away():
    assert C._run_key("ic/sha256/clean_run_v1422") == "sha256/clean_run_v1422"
    assert C._run_key("sha256/clean_run_v1422") == "sha256/clean_run_v1422"
    assert C._run_key("/ic/sha256/clean_run_v1422/") == "sha256/clean_run_v1422"


def test_normalisation_does_not_let_one_design_answer_for_another():
    """The relaxation that would have been wrong: matching on a bare tail."""
    assert C._run_key("ic/foo/clean_run_x") != C._run_key("ic/bar/clean_run_x")


# ---------------------------------------------------------------------------
# repaired vs withdrawn
# ---------------------------------------------------------------------------
def _base(per_run, total=None):
    return {"findings_total": total if total is not None else sum(per_run.values()),
            "per_run": dict(per_run)}


def test_a_run_that_left_the_corpus_is_withdrawn_not_repaired():
    base = _base({"sha256/clean_run_a": 2, "u_hawaii_adc/clean_run_b": 1})
    rep = {"per_run": {"ic/sha256/clean_run_a": 2}, "findings_total": 2}
    split = C._decompose_shrink(base, rep)
    assert split["withdrawn"] == {"u_hawaii_adc/clean_run_b": 1}, split
    assert split["repaired"] == {}, split
    assert split["repaired_total"] == 0 and split["withdrawn_total"] == 1


def test_a_run_still_present_with_fewer_findings_is_repaired():
    base = _base({"sha256/clean_run_a": 3})
    rep = {"per_run": {"ic/sha256/clean_run_a": 1}, "findings_total": 1}
    split = C._decompose_shrink(base, rep)
    assert split["repaired"] == {"sha256/clean_run_a": (3, 1)}, split
    assert split["withdrawn"] == {}, split
    assert split["repaired_total"] == 2


def test_a_run_present_and_unchanged_is_neither():
    base = _base({"sha256/clean_run_a": 2})
    rep = {"per_run": {"ic/sha256/clean_run_a": 2}, "findings_total": 2}
    split = C._decompose_shrink(base, rep)
    assert split["repaired"] == {} and split["withdrawn"] == {}, split


def test_the_present_runs_are_not_swept_into_withdrawn_by_the_prefix():
    """The bug this file's docstring records: without `_run_key`, the five
    findings sitting in the sweep's own output would read as withdrawn."""
    base = _base({"sha256/clean_run_a": 2, "sha256/clean_run_b": 3})
    rep = {"per_run": {"ic/sha256/clean_run_a": 2, "ic/sha256/clean_run_b": 3}, "findings_total": 5}
    split = C._decompose_shrink(base, rep)
    assert split["withdrawn"] == {}, (
        f"a present run was reported as withdrawn — the corpus prefix is not "
        f"being normalised: {split}")


# ---------------------------------------------------------------------------
# what the CLI says, which is the part a reader acts on
# ---------------------------------------------------------------------------
def _corpus(tmp_path, runs: dict) -> Path:
    """A corpus of run trees, each with the given number of unacknowledged
    FAIL reports. Built through the real emitter shape the checker scans."""
    root = tmp_path / "benchmark-data"
    for rel, n in runs.items():
        rd = root / "ic" / rel / "reports"
        rd.mkdir(parents=True, exist_ok=True)
        for i in range(n):
            (rd / f"gate_{i}.json").write_text(json.dumps(
                {"program": f"g{i}", "verdict": "FAIL",
                 "findings": [{"rule": "X", "severity": "ERROR",
                               "message": "m"}]}) + "\n")
    return root


def _run(corpus: Path, baseline: Path, *extra):
    return subprocess.run(
        [sys.executable, str(PROG), "--corpus", str(corpus),
         "--baseline", str(baseline), *extra],
        capture_output=True, text=True, timeout=55)


def test_a_shrink_that_is_all_withdrawal_is_not_called_debt_paid(tmp_path):
    corpus = _corpus(tmp_path, {"sha256/clean_run_keep": 2})
    bl = tmp_path / "baseline.json"
    bl.write_text(json.dumps(_base({"sha256/clean_run_keep": 2, "gone/clean_run_gone": 3})) + "\n")

    res = _run(corpus, bl)
    out = res.stdout + res.stderr
    assert "NONE of it is repair" in out, out
    assert "WITHDRAWN gone/clean_run_gone" in out, out
    assert "stops claiming debt that is paid" not in out, (
        "a withdrawal-only shrink was still advertised as debt paid\n" + out)
    assert res.returncode == 0, out


def test_a_real_repair_is_still_called_a_repair(tmp_path):
    """The paired half. If the new branch swallowed every shrink, the check
    would have stopped being able to say that work happened."""
    corpus = _corpus(tmp_path, {"sha256/clean_run_keep": 1})
    bl = tmp_path / "baseline.json"
    bl.write_text(json.dumps(_base({"sha256/clean_run_keep": 3})) + "\n")

    res = _run(corpus, bl)
    out = res.stdout + res.stderr
    assert "REPAIRED  sha256/clean_run_keep: 3 -> 1" in out, out
    assert "NONE of it is repair" not in out, out
    assert res.returncode == 0, out


def test_growth_is_still_a_failure(tmp_path):
    """Untouched by this change, asserted so it stays untouched."""
    corpus = _corpus(tmp_path, {"sha256/clean_run_keep": 4})
    bl = tmp_path / "baseline.json"
    bl.write_text(json.dumps(_base({"sha256/clean_run_keep": 1})) + "\n")
    res = _run(corpus, bl)
    assert res.returncode == 1, res.stdout + res.stderr
    assert "GREW" in res.stdout + res.stderr


def test_write_baseline_carries_the_withdrawal_forward(tmp_path):
    """Rewriting must not drop the record. Otherwise the next reader sees only
    a smaller number, which is indistinguishable from work."""
    corpus = _corpus(tmp_path, {"sha256/clean_run_keep": 2})
    bl = tmp_path / "baseline.json"
    bl.write_text(json.dumps(_base({"sha256/clean_run_keep": 2, "gone/clean_run_gone": 3})) + "\n")

    res = _run(corpus, bl, "--write-baseline")
    assert res.returncode == 0, res.stdout + res.stderr
    doc = json.loads(bl.read_text())
    assert doc["findings_total"] == 2, doc
    assert doc["withdrawn_unexamined"] == {"gone/clean_run_gone": 3}, (
        "the withdrawal was dropped by the rewrite, so the fall in "
        f"findings_total is now indistinguishable from repair: {doc}")


def test_the_withdrawal_ledger_accumulates(tmp_path):
    """A second withdrawal must not erase the first — the ledger is the only
    place the unexamined findings survive at all."""
    bl = tmp_path / "baseline.json"
    bl.write_text(json.dumps(_base({"a/clean_run_x": 1, "b/clean_run_y": 1, "c/clean_run_z": 1})) + "\n")

    _run(_corpus(tmp_path / "s1", {"a/clean_run_x": 1, "b/clean_run_y": 1}), bl, "--write-baseline")
    _run(_corpus(tmp_path / "s2", {"a/clean_run_x": 1}), bl, "--write-baseline")

    doc = json.loads(bl.read_text())
    assert doc["withdrawn_unexamined"] == {"b/clean_run_y": 1, "c/clean_run_z": 1}, doc


def test_an_empty_sweep_still_refuses(tmp_path):
    """#1025 item 2, pinned rather than re-fixed: it was ALREADY rc 2 on main.
    A sweep that examined nothing must not return the same verdict as one that
    examined everything and found nothing."""
    empty = tmp_path / "benchmark-data"
    (empty / "ic").mkdir(parents=True)
    bl = tmp_path / "baseline.json"
    bl.write_text(json.dumps(_base({"a/clean_run_x": 1})) + "\n")
    res = _run(empty, bl)
    assert res.returncode == 2, res.stdout + res.stderr
    assert "VACUOUS_PASS" in res.stdout + res.stderr
