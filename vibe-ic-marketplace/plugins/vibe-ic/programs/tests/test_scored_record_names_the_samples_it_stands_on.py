#!/usr/bin/env python3
"""A published pass@1 must name the artefacts it was computed from.

THE MEASUREMENT, on 79d3ebbe8 (v1.16.45), in `benchmark-data/evaluation/verilogeval_v2/`
=========================================================================================
    pass_at_1.json   last written 4c21c22c0 (2026-07-22, clean-room v1.4.81)
                     153/156 = 98.08%
    samples/         last written 86cacb4b6 (v1.0.0 initial public release)
    score_iverilog_tb.py --bench verilogeval-v2 --run <that dir>
                     150/156 = 96.15%
                     fails: Prob062 Prob089 Prob092 Prob093 Prob099 Prob149
                     (the record's fail set is Prob062 Prob093 Prob099)

One directory, one record, one sample set, two different runs, and nothing
saying so. The convention is deliberate — 4c21c22c0 states it: "summary only
(pass_at_1.json / RESULT.md / lessons.md), not the ~27 MB work tree". What it
leaves is a directory that LOOKS re-scorable.

WHY IT MATTERS BEYOND THE NUMBER
================================
Re-running the ORGANIC-20260605 corpus sweep against that directory — the sweep
whose doctrine is "an emit-blocking rule is promoted only when it fires on NONE
of the prior-PASSING samples" — reports three Shape-C rules firing on samples the
record beside them calls PASS:

    Prob089_ece241_2014_q5a    fsm-output-style-mismatch
    Prob092_gatesv100          vector-self-shift-fold
    Prob149_ece241_2013_q4     hysteresis-flag-polarity-mismatch

Read as a corpus result that reads "three rules have started firing on
legitimate designs", and the remedy it implies is to NARROW three rules that are
correct: this repository's own scorer refuses all three of those samples. The
sweep was measuring a stale corpus and had no way to say so.

WHAT IS PINNED HERE
===================
1. The record states what it scored: a sha256 per candidate file, a set digest
   and a count.
2. Replacing a record states how it differs: every problem whose verdict moved,
   by name, on stderr and in the report.
3. The TRISTATE, which is the load-bearing part: a previous record that does NOT
   name its samples yields `samples_digest_matches = None` and an explicit
   "cannot be decided" — not True, and not False. Every record written before
   this change is in that state, and collapsing it either way would be the same
   false certainty this exists to remove.
4. Neither is a refusal. A re-score legitimately moves when the samples are new.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2]
BENCH = PLUGIN / "benchmark"
sys.path.insert(0, str(BENCH))
import score_iverilog_tb as S  # noqa: E402


def _samples(tmp_path: Path, files: dict) -> Path:
    d = tmp_path / "samples"
    d.mkdir(exist_ok=True)
    for name, body in files.items():
        (d / name).write_text(body)
    return d


def _rows(pairs):
    return [{"problem": p, "verdict": v} for p, v in pairs]


# ── 1. the record states what it scored ────────────────────────────────────

def test_provenance_digests_every_candidate_file(tmp_path):
    d = _samples(tmp_path, {"A_sample01.sv": "module A; endmodule\n",
                            "B_sample01.sv": "module B; endmodule\n",
                            "notes.txt": "ignored"})
    prov = S.samples_provenance(d)
    assert prov["count"] == 2
    assert set(prov["files"]) == {"A_sample01.sv", "B_sample01.sv"}
    assert prov["files"]["A_sample01.sv"] == hashlib.sha256(
        b"module A; endmodule\n").hexdigest()
    assert len(prov["set_sha256"]) == 64


def test_provenance_moves_when_one_byte_of_one_sample_moves(tmp_path):
    before = S.samples_provenance(
        _samples(tmp_path, {"A_sample01.sv": "module A; endmodule\n"}))
    after = S.samples_provenance(
        _samples(tmp_path, {"A_sample01.sv": "module A;  endmodule\n"}))
    assert before["set_sha256"] != after["set_sha256"]
    assert before["files"]["A_sample01.sv"] != after["files"]["A_sample01.sv"]


def test_provenance_is_stable_across_two_reads_of_one_tree(tmp_path):
    """Without this the digest could be a timestamp in disguise."""
    d = _samples(tmp_path, {"A_sample01.sv": "module A; endmodule\n",
                            "B_sample01.sv": "module B; endmodule\n"})
    assert S.samples_provenance(d) == S.samples_provenance(d)


def test_provenance_over_an_absent_directory_is_zero_not_a_crash(tmp_path):
    prov = S.samples_provenance(tmp_path / "nope")
    assert prov["count"] == 0 and prov["files"] == {}


# ── 2. replacing a record says how it differs ──────────────────────────────

def test_a_moved_verdict_is_named(tmp_path):
    prov = S.samples_provenance(_samples(tmp_path, {"A_sample01.sv": "x\n"}))
    prev = {"passed": 2, "total": 2,
            "results": _rows([("P1", "PASS"), ("P2", "PASS")])}
    now = _rows([("P1", "PASS"), ("P2", "FAIL")])
    d = S.previous_record_delta(prev, now, "problem", prov)
    assert d["verdict_moved"] == [{"id": "P2", "from": "PASS", "to": "FAIL"}]
    assert d["passed_before"] == 2 and d["passed_now"] == 1


def test_an_unchanged_re_score_reports_no_movement(tmp_path):
    """The must-not-fire-on-legitimate-state half: without it every test above
    would pass for a function that reports movement unconditionally."""
    prov = S.samples_provenance(_samples(tmp_path, {"A_sample01.sv": "x\n"}))
    rows = _rows([("P1", "PASS"), ("P2", "FAIL")])
    prev = {"passed": 1, "total": 2, "results": rows, "scored_samples": prov}
    d = S.previous_record_delta(prev, rows, "problem", prov)
    assert d["verdict_moved"] == []
    assert d["only_in_previous"] == [] and d["only_in_this_run"] == []
    assert d["samples_digest_matches"] is True


def test_membership_changes_are_reported_not_folded_into_the_totals(tmp_path):
    prov = S.samples_provenance(_samples(tmp_path, {"A_sample01.sv": "x\n"}))
    prev = {"passed": 1, "total": 1, "results": _rows([("P1", "PASS")])}
    now = _rows([("P2", "PASS")])
    d = S.previous_record_delta(prev, now, "problem", prov)
    assert d["only_in_previous"] == ["P1"]
    assert d["only_in_this_run"] == ["P2"]


def test_shape_b_rows_are_keyed_by_design_and_the_leaf_is_the_id(tmp_path):
    prov = S.samples_provenance(_samples(tmp_path, {"a.v": "x\n"}))
    prev = {"passed": 1, "total": 1,
            "results": [{"design": "grp/alu", "verdict": "PASS"}]}
    now = [{"design": "grp/alu", "verdict": "FAIL"}]
    d = S.previous_record_delta(prev, now, "design", prov)
    assert d["verdict_moved"] == [{"id": "alu", "from": "PASS", "to": "FAIL"}]


# ── 3. THE TRISTATE ────────────────────────────────────────────────────────

def test_a_previous_record_with_no_provenance_is_undecidable_not_false(tmp_path):
    """THE STATE THE MEASURED CASE IS IN. A record that does not name its
    samples cannot be said to describe them and cannot be said not to."""
    prov = S.samples_provenance(_samples(tmp_path, {"A_sample01.sv": "x\n"}))
    prev = {"passed": 2, "total": 2,
            "results": _rows([("P1", "PASS"), ("P2", "PASS")])}
    d = S.previous_record_delta(prev, _rows([("P1", "PASS"), ("P2", "FAIL")]),
                                "problem", prov)
    assert d["samples_digest_matches"] is None
    assert d["provenance_undecidable"] is True
    assert "cannot be decided" in d["note"]


def test_a_previous_record_from_a_different_sample_set_says_so(tmp_path):
    prov_old = S.samples_provenance(_samples(tmp_path, {"A_sample01.sv": "old\n"}))
    prov_new = S.samples_provenance(_samples(tmp_path, {"A_sample01.sv": "new\n"}))
    prev = {"passed": 1, "total": 1, "results": _rows([("P1", "PASS")]),
            "scored_samples": prov_old}
    d = S.previous_record_delta(prev, _rows([("P1", "FAIL")]), "problem",
                                prov_new)
    assert d["samples_digest_matches"] is False
    assert d["provenance_undecidable"] is False
    assert "DIFFERENT sample set" in d["note"]


@pytest.mark.parametrize("prev", [None, {}, {"results": "not a list"},
                                  {"no": "results"}])
def test_an_unreadable_or_absent_previous_record_is_not_a_delta(prev, tmp_path):
    """A first score has nothing to differ from, and must not invent one."""
    prov = S.samples_provenance(_samples(tmp_path, {"A_sample01.sv": "x\n"}))
    assert S.previous_record_delta(prev, _rows([("P1", "PASS")]),
                                   "problem", prov) is None


# ── 4. the measured case itself, replayed as a fixture ─────────────────────

def test_the_measured_verilogeval_v2_shape_is_reported_as_undecidable(tmp_path):
    """The exact shape found in `benchmark-data/evaluation/verilogeval_v2/`:
    a record with no provenance, three verdicts moved, and one directory."""
    prov = S.samples_provenance(_samples(tmp_path, {
        "Prob089_ece241_2014_q5a_sample01.sv": "module TopModule; endmodule\n",
        "Prob092_gatesv100_sample01.sv": "module TopModule; endmodule\n",
        "Prob149_ece241_2013_q4_sample01.sv": "module TopModule; endmodule\n"}))
    prev = {"passed": 153, "total": 156,
            "results": _rows([("Prob089_ece241_2014_q5a", "PASS"),
                              ("Prob092_gatesv100", "PASS"),
                              ("Prob149_ece241_2013_q4", "PASS")])}
    now = _rows([("Prob089_ece241_2014_q5a", "FAIL"),
                 ("Prob092_gatesv100", "FAIL"),
                 ("Prob149_ece241_2013_q4", "FAIL")])
    d = S.previous_record_delta(prev, now, "problem", prov)
    assert [m["id"] for m in d["verdict_moved"]] == [
        "Prob089_ece241_2014_q5a", "Prob092_gatesv100", "Prob149_ece241_2013_q4"]
    assert all(m["from"] == "PASS" and m["to"] == "FAIL"
               for m in d["verdict_moved"])
    assert d["provenance_undecidable"] is True


# ── 5. END TO END, through the scorer's own main() ─────────────────────────
#
# The unit tests above cannot fail against the pre-fix tree for the right
# reason: the functions do not exist there, so they raise AttributeError and
# observe nothing about behaviour. These two DRIVE THE SCORER, which the pre-fix
# tree runs perfectly well — it simply writes a record with no `scored_samples`
# and no `previous_record`, which is the defect, stated as an assertion the old
# code can reach and answer wrongly.

import shutil                                                   # noqa: E402
import subprocess                                               # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr                                     # noqa: E402

_HAS_IVERILOG = shutil.which("iverilog") is not None
_needs_tool = pytest.mark.skipif(
    not _HAS_IVERILOG,
    reason="drives score_iverilog_tb.py, which compiles the testbench with "
           "iverilog; without it the scorer records compile_error for every "
           "problem and the verdicts under test are not produced")

_TB = """\
module tb;
  reg a; wire y_dut, y_ref;
  integer i; integer mism = 0; integer tot = 0;
  TopModule dut(.a(a), .y(y_dut));
  RefModule  rf(.a(a), .y(y_ref));
  initial begin
    for (i = 0; i < 4; i = i + 1) begin
      a = i[0]; #1;
      tot = tot + 1;
      if (y_dut !== y_ref) mism = mism + 1;
    end
    $display("Mismatches: %0d in %0d samples", mism, tot);
    $finish;
  end
endmodule
"""
_REF = "module RefModule(input a, output y);\n  assign y = a;\nendmodule\n"
_GOOD = "module TopModule(input a, output y);\n  assign y = a;\nendmodule\n"
_BAD = "module TopModule(input a, output y);\n  assign y = ~a;\nendmodule\n"


def _mini_bench(tmp_path: Path, probs):
    ds = tmp_path / "ds"; ds.mkdir()
    run = tmp_path / "run"; (run / "samples").mkdir(parents=True)
    for p in probs:
        (ds / f"{p}_prompt.txt").write_text("Implement TopModule: y = a.\n")
        (ds / f"{p}_test.sv").write_text(_TB)
        (ds / f"{p}_ref.sv").write_text(_REF)
    (run / "problems.list").write_text("\n".join(probs) + "\n")
    return ds, run


def _score(ds: Path, run: Path):
    return _pr.run([sys.executable, str(BENCH / "score_iverilog_tb.py"),
                    "--bench", "verilogeval-v2", "--dataset", str(ds),
                    "--run", str(run)], capture_output=True, text=True)


@_needs_tool
def test_a_first_score_states_what_it_scored(tmp_path):
    ds, run = _mini_bench(tmp_path, ["P1", "P2"])
    (run / "samples" / "P1_sample01.sv").write_text(_GOOD)
    (run / "samples" / "P2_sample01.sv").write_text(_GOOD)
    r = _score(ds, run)
    rec = json.loads((run / "pass_at_1.json").read_text())
    assert rec["passed"] == 2, r.stdout + r.stderr
    prov = rec["scored_samples"]
    assert prov["count"] == 2
    assert set(prov["files"]) == {"P1_sample01.sv", "P2_sample01.sv"}
    assert prov["files"]["P1_sample01.sv"] == hashlib.sha256(
        _GOOD.encode()).hexdigest()
    # A first score has nothing to differ from and must not invent a delta.
    assert "previous_record" not in rec


@_needs_tool
def test_a_re_score_over_swapped_samples_names_every_problem_that_moved(tmp_path):
    """THE MEASURED SHAPE, reproduced end to end: a record beside a sample set
    that is not the one it was computed from. The scorer must say so, name the
    problem, and — because the record it replaces has provenance here — say
    which of the two the previous record described."""
    ds, run = _mini_bench(tmp_path, ["P1", "P2"])
    (run / "samples" / "P1_sample01.sv").write_text(_GOOD)
    (run / "samples" / "P2_sample01.sv").write_text(_GOOD)
    _score(ds, run)
    first = json.loads((run / "pass_at_1.json").read_text())
    assert first["passed"] == 2

    (run / "samples" / "P2_sample01.sv").write_text(_BAD)
    r = _score(ds, run)
    rec = json.loads((run / "pass_at_1.json").read_text())
    assert rec["passed"] == 1, r.stdout + r.stderr
    d = rec["previous_record"]
    assert d["passed_before"] == 2 and d["passed_now"] == 1
    assert d["verdict_moved"] == [{"id": "P2", "from": "PASS", "to": "FAIL"}]
    assert d["samples_digest_matches"] is False
    # …and it is LOUD, not only in the file.
    assert "RECORD REPLACED" in r.stderr, r.stderr
    assert "P2: PASS -> FAIL" in r.stderr, r.stderr


@_needs_tool
def test_a_record_written_without_provenance_re_scores_as_undecidable(tmp_path):
    """The state every record written before this change is in: the scorer must
    report `provenance_undecidable`, not guess either way."""
    ds, run = _mini_bench(tmp_path, ["P1"])
    (run / "samples" / "P1_sample01.sv").write_text(_BAD)
    # A legacy record: the shape 4c21c22c0 wrote — verdicts, no samples named.
    (run / "pass_at_1.json").write_text(json.dumps({
        "passed": 1, "total": 1,
        "results": [{"problem": "P1", "verdict": "PASS"}]}) + "\n")
    r = _score(ds, run)
    rec = json.loads((run / "pass_at_1.json").read_text())
    d = rec["previous_record"]
    assert d["provenance_undecidable"] is True
    assert d["samples_digest_matches"] is None
    assert d["verdict_moved"] == [{"id": "P1", "from": "PASS", "to": "FAIL"}]
    assert "cannot be decided" in r.stderr, r.stderr
