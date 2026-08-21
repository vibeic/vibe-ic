"""A sweep must state how many of its own clauses decided. vibe-ic#1025 follow-up.

The single-gate question — "does an empty corpus exit 2 and does the caller act
on it" — was answered in #1056: yes on both counts. This file is one level up,
where the answer was no.

MEASURED on `origin/main` @ `3febf5372`, six gates all returning rc 2 under
`run_tolerating_uncheckable`:

    repo_hygiene_gates: 0 of 6 gate(s) passed; 6 NOT CHECKED —
    this is NOT a pass over: gate1, gate2, … (1s)          <-- SUITE rc 0

    summary.json: declared 6, ran 6, passed 0, failed 0, not_checked 6

Every word of that is true. The sentence even says "this is NOT a pass". The
EXIT CODE says pass, and the exit code is what every consumer reads:
`gatekeeper-land.sh:284` wraps the script in `if out="$(…)"`, so any zero is a
PASS row; and `gatekeeper_review._hygiene_verdict` — with no failing gate and
`script_rc == 0` — fell through to `GateResult(name, 0, where)`, a GREEN gate,
carrying `6 NOT CHECKED (not a pass)` in prose beside a passing verdict.

So a sweep could end with every one of its clauses having concluded nothing and
still report success. That is the empty-tree lie at the sweep level, and it is
worse than the single-gate form because the sweep is where a human forms an
impression of the whole repo.

WHAT IS PINNED
--------------
1. every executed path states `DECIDED n of N`. Not `ran` — a NOT_CHECKED gate
   ran and concluded nothing, and the gap between those two numbers is the
   entire subject here;
2. a sweep that decided NOTHING exits 2. Two (could not determine), not one
   (found a defect): a vacuous sweep found no defect, it produced no result,
   and reporting it as a finding would be the mirror of the lie removed;
3. the three arms that must NOT move, which is what makes (2) a check rather
   than a ban: SOME decided still exits 0 even with vacuous gates alongside; a
   real failure among vacuous gates still exits 1; an all-green sweep is
   byte-unchanged in its verdict sentence. An "always refuse" mutant passes (2)
   and dies on every one of these;
4. `_hygiene_verdict` names the vacuity itself rather than reporting it through
   the `script_rc != 0` branch, whose message is about the record and the exit
   code DISAGREEING. Here they agree perfectly — every gate ran, none decided —
   and that branch would point a reader away from the one thing that happened.
"""
import json
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
ROOT = PLUGIN.parent.parent.parent
DISPATCH = ROOT / "tools" / "ci" / "_gate_dispatch.sh"

sys.path.insert(0, str(PLUGIN / "programs"))
import gatekeeper_review as gr  # noqa: E402

#: What ONE harness invocation may spend. The suite runs under a 180 s
#: pytest-timeout, and `ci_harness_timeout_ceiling_check` requires every inner
#: bound to sit at or under 180 // 3 = 60 s: a bound above the ceiling promises
#: time the harness will not give, and because the harness kills the SESSION
#: rather than the test, a hang here takes the whole run down with NO summary
#: line -- which greps as neither a pass nor a failure (vibe-ic#1181, #1272).
#:
#: MEASURED: the whole file is 14 passed in 8.8 s, so one invocation is well
#: under a second. 30 s is ~3x the entire file and half the ceiling.
_BOUND_S = 30



def _sweep(tmp_path, body, summary=None):
    """Drive the REAL dispatcher over `body` and return (rc, output, record)."""
    for rc in (0, 1, 2):
        stub = tmp_path / f"e{rc}.sh"
        stub.write_text(f"#!/usr/bin/env bash\nexit {rc}\n")
        stub.chmod(0o755)
    rec = summary or (tmp_path / "summary.json")
    harness = tmp_path / "harness.sh"
    harness.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        f"source {DISPATCH}\n"
        f"gate_dispatch_init --summary-json {rec}\n"
        f"{body}\n"
        "gate_dispatch_finish\n")
    proc = subprocess.run(["bash", str(harness)], capture_output=True,
                          text=True, cwd=str(tmp_path), timeout=_BOUND_S)
    doc = json.loads(rec.read_text()) if rec.is_file() else None
    return proc.returncode, proc.stdout + proc.stderr, doc


def _gates(tmp_path, spec):
    """spec: [(wrapper, label, rc), …] -> dispatch lines."""
    return "\n".join(
        f'{w} "{lbl}" "{tmp_path}" bash {tmp_path}/e{rc}.sh'
        for w, lbl, rc in spec)


_VACUOUS = [("run_tolerating_uncheckable", f"v{i}", 2) for i in range(1, 7)]


# ---------------------------------------------------------------------------
# (c) the sweep reports its own vacuity
# ---------------------------------------------------------------------------
def test_every_executed_path_states_how_many_gates_decided(tmp_path):
    """Including the FAIL path, which named `declared` and `NOT CHECKED` but
    never how many gates actually reached a verdict.

    The count is asserted per path with its exact numbers rather than by
    grepping for the word: a check that only asks whether "decided" appears
    somewhere would survive the count being wrong, which is the failure mode
    this whole file is about.
    """
    for name, spec, want in (
            ("green", [("run", "a", 0), ("run", "b", 0)],
             "2 of 2 decided"),
            ("mixed", [("run", "a", 0)] + _VACUOUS,
             "DECIDED 1 of 7"),
            # a failure AND vacuous gates, so `decided` differs from both
            # `declared` and `passed` and cannot be matched by accident
            ("failing", [("run", "a", 1), ("run", "b", 0)] + _VACUOUS,
             "2 of 8 decided"),
            ("vacuous", _VACUOUS,
             "0 of 6 gate(s) reached a verdict")):
        d = tmp_path / name
        d.mkdir()
        _rc, out, _doc = _sweep(d, _gates(d, spec))
        assert want in out, f"[{name}] expected {want!r} in:\n{out}"


def test_the_clean_sentence_never_mentions_not_checked(tmp_path):
    """#539's other half, which the first draft of this change broke: a run in
    which nothing refused must not read as degraded. An accounting line that
    always printed `0 NOT CHECKED` put those words in front of a reader of a
    wholly clean run."""
    _rc, out, _doc = _sweep(tmp_path, _gates(
        tmp_path, [("run", "a", 0), ("run", "b", 0)]))
    assert "NOT CHECKED" not in out, out


def test_the_rollup_stays_exactly_one_line(tmp_path):
    """Also broken by the first draft. #539's guard requires the roll-up to be
    ONE line, so the sentence a reader takes away cannot drift from the caveat
    that qualifies it. An appended accounting line reintroduces that split."""
    for name, spec in (("green", [("run", "a", 0)]),
                       ("mixed", [("run", "a", 0)] + _VACUOUS),
                       ("vacuous", _VACUOUS)):
        d = tmp_path / name
        d.mkdir()
        _rc, out, _doc = _sweep(d, _gates(d, spec))
        rollup = [ln for ln in out.splitlines()
                  if ln.startswith("repo_hygiene_gates:")]
        assert len(rollup) == 1, f"[{name}] expected one roll-up line: {rollup}"


def test_the_record_carries_decided_and_agrees_with_the_printed_line(tmp_path):
    rc, out, doc = _sweep(tmp_path, _gates(
        tmp_path, [("run", "a", 0), ("run", "b", 0)] + _VACUOUS))
    assert rc == 0, out
    assert doc["decided"] == 2, doc
    assert doc["declared"] == 8, doc
    # `ran` counts every gate that executed; `decided` counts those that
    # concluded. A consumer that could only see `ran` would read 8.
    assert doc["ran"] == 8, doc
    assert "DECIDED 2 of 8" in out, out


# ---------------------------------------------------------------------------
# (d) the judgement: a sweep that decided nothing is not a pass
# ---------------------------------------------------------------------------
def test_an_all_vacuous_sweep_exits_2_and_says_so(tmp_path):
    rc, out, doc = _sweep(tmp_path, _gates(tmp_path, _VACUOUS))
    assert rc == 2, (
        f"6 of 6 gates concluded nothing and the sweep exited {rc}. Every "
        f"consumer reads the exit code:\n{out}")
    assert "DECIDED NOTHING" in out, out
    assert "0 of 6 gate(s) reached a verdict" in out, out
    assert doc["decided"] == 0 and doc["not_checked"] == 6, doc


# --- the three arms that make the above a CHECK and not a BAN --------------
def test_a_sweep_where_some_gates_decided_still_exits_0(tmp_path):
    """The reason the line is drawn at ZERO decided and not at "any vacuous".

    The rc-0-with-refusals branch has a measured rationale: a developer whose
    tree is dirty by construction would make this script permanently red, and a
    permanently red gate is one that gets skipped. An "always refuse" mutant
    passes the test above and dies here.
    """
    rc, out, doc = _sweep(tmp_path, _gates(
        tmp_path, [("run", "a", 0), ("run", "b", 0)] + _VACUOUS))
    assert rc == 0, f"a sweep that decided 2 of 8 must not be refused:\n{out}"
    assert "this is NOT a pass over" in out, out
    assert doc["decided"] == 2, doc


def test_a_real_failure_among_vacuous_gates_still_exits_1(tmp_path):
    """A finding stays a finding: rc 1 is `found a defect`, and the vacuity
    refusal must never demote it to `could not determine`."""
    rc, out, _doc = _sweep(tmp_path, _gates(
        tmp_path, [("run", "bad", 1)] + _VACUOUS))
    assert rc == 1, f"expected the failure to remain the verdict:\n{out}"
    assert "at least one gate FAILED" in out, out


def test_an_all_green_sweep_is_unchanged(tmp_path):
    rc, out, _doc = _sweep(tmp_path, _gates(
        tmp_path, [("run", "a", 0), ("run", "b", 0)]))
    assert rc == 0, out
    assert "all 2 gate(s) passed" in out, out


# ---------------------------------------------------------------------------
# the consumer half — gatekeeper_review must NAME the vacuity
# ---------------------------------------------------------------------------
def _doc(declared, states, **extra):
    d = {"declared": declared,
         "gates": [{"label": f"g{i}", "state": s}
                   for i, s in enumerate(states)],
         "passed": sum(1 for s in states if s == "PASS"),
         "failed": sum(1 for s in states if s == "FAIL"),
         "not_checked": sum(1 for s in states if s == "NOT_CHECKED"),
         "seconds": 1}
    d["decided"] = d["passed"] + d["failed"]
    d.update(extra)
    return d


def test_hygiene_verdict_refuses_an_all_vacuous_record():
    res = gr._hygiene_verdict(_doc(6, ["NOT_CHECKED"] * 6), 2)
    assert res.rc == 2, res
    assert not res.green, "a sweep that concluded nothing must not be green"
    assert "DECIDED NOTHING" in res.summary, res.summary
    # NOT through the `naming no failing gate` branch: that message is about
    # the record and the exit code disagreeing, and here they agree exactly.
    assert "naming no failing gate" not in res.summary, res.summary


def test_hygiene_verdict_refuses_it_even_when_the_script_exited_0():
    """The shape that was live before this change: an older dispatcher, or any
    future one that regresses, hands over 6 NOT_CHECKED with rc 0. The verdict
    must not depend on the script having already refused."""
    res = gr._hygiene_verdict(_doc(6, ["NOT_CHECKED"] * 6), 0)
    assert res.rc == 2 and not res.green, res


def test_hygiene_verdict_reads_the_states_not_the_rollup_counters():
    """A record may carry `gates` and no roll-up counters — several fixtures in
    this repo do. Reading an absent `passed` as 0 made an ALL-PASS record look
    like it decided nothing, i.e. this branch manufacturing the exact failure
    it exists to report. Measured: it did, on
    `test_corpus_write_guard.py::test_a_clean_record_is_unaffected`."""
    bare = {"declared": 1, "gates": [{"label": "a reader", "state": "PASS"}],
            "seconds": 1}
    assert gr._hygiene_verdict(bare, 0).rc == 0
    bare_vacuous = {"declared": 2, "seconds": 1,
                    "gates": [{"label": "x", "state": "NOT_CHECKED"},
                              {"label": "y", "state": "NOT_CHECKED"}]}
    assert gr._hygiene_verdict(bare_vacuous, 0).rc == 2


def test_hygiene_verdict_does_not_refuse_a_list_only_record():
    """`--list` decided nothing BY REQUEST and says so. Refusing it would
    report a deliberate listing as a vacuous sweep."""
    listed = {"declared": 3, "seconds": 0, "listed_only": True,
              "gates": [{"label": f"g{i}", "state": "LISTED"}
                        for i in range(3)]}
    assert gr._hygiene_verdict(listed, 0).rc == 0


def test_hygiene_verdict_still_passes_a_partly_vacuous_record():
    """The positive arm on the consumer side — same anti-ban argument."""
    res = gr._hygiene_verdict(_doc(4, ["PASS", "PASS", "NOT_CHECKED",
                                       "NOT_CHECKED"]), 0)
    assert res.rc == 0 and res.green, res
    assert "NOT CHECKED (not a pass)" in res.summary, res.summary


def test_hygiene_verdict_still_reports_a_failing_gate_as_rc_1():
    res = gr._hygiene_verdict(_doc(3, ["PASS", "FAIL", "NOT_CHECKED"]), 1)
    assert res.rc == 1, res
    assert "FAILED" in res.summary, res.summary
