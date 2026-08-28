"""A sweep that DECIDED NOTHING must not report success. vibe-ic#1025.

THE DEFECT, MEASURED ON `75776dbbb`
===================================
Six gates, each returning rc 2 under `run_tolerating_uncheckable` with a live
`uncheckable_until` — that is, every refusal properly bought under #584::

    repo_hygiene_gates: 0 of 6 gate(s) passed; 6 NOT CHECKED — this is NOT a
    pass over: gate1 (exempt until 2999-01-01), … (1s)
    $ echo $?
    0
    >>> gatekeeper_review._hygiene_verdict(record, 0).rc
    0

The sentence says "this is NOT a pass" and the exit code says pass. Every
`-ne 0` consumer believes the exit code — `gatekeeper-land.sh` wraps the sweep
in `if out="$(…)"` — and `_hygiene_verdict` returned rc 0, MERGE_OK, with
`6 NOT CHECKED (not a pass)` carried only in its descriptive `where` string,
i.e. as prose beside a passing verdict.

WHY #539 AND #584 DID NOT ALREADY COVER IT
==========================================
#539 fixed the SENTENCE: a run with refusals stopped printing "all gates
passed". #584 made each individual refusal BUY its tolerance with a dated,
reasoned exemption, so the count could no longer creep up unremarked. Neither
asked what happens when the bought set is ALL of them. Both leave the rc-0
branch for refusals in place ON PURPOSE — a maintainer whose tree is dirty by
construction must not face a permanently red script, because a permanently red
gate is a gate that gets skipped.

So the line this file pins is not "any NOT_CHECKED is fatal". It is ZERO
DECIDED: the difference between a result with caveats and no result at all.
The dispatcher already refuses `declared == 0` with rc 2 — a script that wired
nothing cannot certify anything — and a script that wired 63 gates and got a
verdict from none of them is in the same state, arriving through a different
door.

rc 2 AND NOT rc 1: this repo's convention is 1 = found a defect, 2 = could not
determine. A vacuous sweep found no defect; it produced no result. Reporting it
as 1 would announce a finding that does not exist — the mirror of the lie being
removed.

EVERY REFUSAL BELOW HAS A CONTROL ARM. A test that cannot pass in the other arm
proves only that the script is broken, not that it discriminates — and the arm
that matters most here is the one pinning what must NOT change: a sweep with
ONE deciding gate among many refusals still exits 0, loudly, exactly as #539
and #584 left it.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = Path(__file__).resolve().parents[1]
_REPO = _PROGRAMS.parents[3]
_LIB = _REPO / "tools" / "ci" / "_gate_dispatch.sh"

if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


GR = _load("gatekeeper_review")

#: Far enough out that this file does not become a time bomb of its own, and
#: still a real ISO date the dispatcher's comparison treats exactly as it
#: treats a live one.
_FUTURE = "2999-01-01"

# --------------------------------------------------------------------------
# fixtures — a throwaway hygiene script sourcing the REAL dispatch library, so
# these drive the code CI actually runs rather than a copy of it.
# --------------------------------------------------------------------------
def _probes(root: Path) -> None:
    (root / "p_ok.py").write_text('print("PASS (2 item(s) examined)")\n')
    (root / "p_refuse.py").write_text(textwrap.dedent("""\
        import sys
        print("cannot look: the prerequisite is missing")
        sys.exit(2)
        """))
    (root / "p_fail.py").write_text(textwrap.dedent("""\
        import sys
        print("FAIL: found something")
        sys.exit(1)
        """))


def _run(root: Path, gate_lines: str, *args: str):
    """Run a fixture script through the REAL dispatcher; return (proc, record)."""
    (root / "tools" / "ci").mkdir(parents=True, exist_ok=True)
    script = root / "tools" / "ci" / "repo_hygiene_gates.sh"
    script.write_text(textwrap.dedent(f"""\
        set -euo pipefail
        ROOT="{root}"
        . "{_LIB}"
        gate_dispatch_init "$@"
        """) + gate_lines + "\ngate_dispatch_finish\n")
    rec = root / "record.json"
    proc = _pr.run(
        ["bash", str(script), "--summary-json", str(rec), *args],
        cwd=str(root), capture_output=True, text=True)
    doc = json.loads(rec.read_text()) if rec.is_file() else None
    return proc, doc


def _refusing(label: str) -> str:
    """A gate that REFUSES, with its tolerance properly bought under #584."""
    return (f'uncheckable_until {_FUTURE} "the prerequisite is not on this host"\n'
            f'run_tolerating_uncheckable "{label}" "$ROOT" python3 "$ROOT/p_refuse.py"\n')


def _green(label: str) -> str:
    return f'run "{label}" "$ROOT" python3 "$ROOT/p_ok.py"\n'


def _red(label: str) -> str:
    return f'run "{label}" "$ROOT" python3 "$ROOT/p_fail.py"\n'


def _fixture(tmp_path: Path) -> Path:
    root = tmp_path / "r"
    root.mkdir()
    _probes(root)
    return root


# ==========================================================================
# 1. THE DISPATCHER — zero decided is refused; one decided is not
# ==========================================================================
def test_a_sweep_in_which_no_gate_decided_anything_refuses(tmp_path):
    """ARM A. The state main shipped: six bought refusals, suite rc 0."""
    root = _fixture(tmp_path)
    proc, doc = _run(root, "".join(_refusing(f"gate{i}") for i in range(1, 7)))
    text = proc.stdout + proc.stderr

    assert proc.returncode == 2, (
        f"six gates ran, NONE of them reached a verdict, and the sweep exited "
        f"{proc.returncode}. A run that concluded nothing is being reported as "
        f"a pass:\n{text}")
    assert "DECIDED NOTHING" in text, (
        f"the refusal does not SAY what happened, so a reader has to infer it "
        f"from an exit code:\n{text}")
    assert "gate1" in text and "gate6" in text, (
        f"the refusing gates are not NAMED; a bare count cannot answer 'was it "
        f"the one I cared about':\n{text}")
    # Its own denominator, in the sentence, so it cannot be read over a set
    # that silently shrank.
    assert "0 of 6" in text, text
    assert doc["decided"] == 0 and doc["ran"] == 6, doc


def test_one_gate_that_DID_decide_keeps_the_sweep_green(tmp_path):
    """ARM B — the control, and the property the repair must NOT break.

    Same fixture, same six bought refusals, ONE green gate added. #539 and
    #584 both deliberately left this at rc 0: an exempted refusal is loud, not
    fatal, because a permanently red script is a script that gets skipped.

    Without this arm, ARM A above is satisfied by a dispatcher that refuses
    every run with any NOT_CHECKED in it at all — a ban rather than a check.
    """
    root = _fixture(tmp_path)
    proc, doc = _run(root, "".join(_refusing(f"gate{i}") for i in range(1, 7))
                     + _green("a gate that looked"))
    text = proc.stdout + proc.stderr

    assert proc.returncode == 0, (
        f"a sweep in which a gate DID reach a verdict is being refused as "
        f"vacuous — the guard has become a ban on refusals:\n{text}")
    assert "DECIDED NOTHING" not in text, text
    # #539's sentence, intact and still exactly one line.
    rollup = [ln for ln in proc.stdout.splitlines()
              if ln.startswith("repo_hygiene_gates:")]
    assert len(rollup) == 1, proc.stdout
    assert "1 of 7 gate(s) passed" in rollup[0], rollup[0]
    assert "NOT a pass" in rollup[0] and "gate1" in rollup[0], rollup[0]
    assert doc["decided"] == 1, doc


def test_the_refusal_is_the_could_not_determine_tier_and_not_a_finding(tmp_path):
    """rc 2, never rc 1. A vacuous sweep produced no result; it found no defect.

    The control is a sweep that genuinely DID find something: that one is rc 1,
    and the two must not be reported through the same code, or "nothing was
    checked" and "something is broken" become indistinguishable to every
    consumer that branches on the number.
    """
    root = _fixture(tmp_path)
    vacuous, _ = _run(root, _refusing("gate1") + _refusing("gate2"))
    found, _ = _run(root, _red("a gate that found something")
                    + _refusing("gate2"))

    assert vacuous.returncode == 2, vacuous.stdout + vacuous.stderr
    assert found.returncode == 1, found.stdout + found.stderr


def test_a_failing_sweep_states_how_many_gates_reached_a_verdict(tmp_path):
    """The FAIL sentence was the one closing line with no denominator.

    It named `declared` and `notchecked` and never said how many gates actually
    decided, so `at least one gate FAILED (63 declared, 0 NOT CHECKED)` reads
    identically whether one gate failed or forty.
    """
    root = _fixture(tmp_path)
    proc, doc = _run(root, _green("g1") + _red("r1") + _red("r2"))
    text = proc.stdout + proc.stderr

    assert proc.returncode == 1, text
    assert "3 of 3 decided" in text, (
        f"the FAIL sentence still cannot say how many gates reached a "
        f"verdict:\n{text}")
    assert "1 passed, 2 failed" in text, text
    assert doc["decided"] == 3, doc


def test_the_record_separates_RAN_from_DECIDED(tmp_path):
    """`ran` counts gates that executed; `decided` counts verdicts.

    Recorded rather than left derivable so a consumer cannot arrive at a
    different number than the sentence the script printed — the drift shape
    #527/#530/#534/#538 each spent a version removing.
    """
    root = _fixture(tmp_path)
    _, doc = _run(root, _green("g1") + _refusing("gate2") + _refusing("gate3"))

    assert doc["ran"] == 3, doc
    assert doc["decided"] == 1, doc
    assert doc["decided"] == doc["passed"] + doc["failed"], doc


def test_listing_the_gates_is_not_called_a_vacuous_sweep(tmp_path):
    """`--list` decides nothing BY REQUEST and already says so.

    Refusing it here would report a deliberate enumeration as a failure, and
    two other programs parse that enumeration to reconcile their gate lists.
    """
    root = _fixture(tmp_path)
    proc, doc = _run(root, _refusing("gate1") + _refusing("gate2"), "--list")
    text = proc.stdout + proc.stderr

    assert proc.returncode == 0, text
    assert "DECIDED NOTHING" not in text, text
    assert doc["listed_only"] and doc["deferred"] == 2, doc


# ==========================================================================
# 2. THE CONSUMER — `gatekeeper_review` must reach the same answer
# ==========================================================================
def _record(states, **extra):
    doc = {"declared": len(states), "gates": [
        {"label": f"gate{i}", "state": s, "exempt_until": _FUTURE,
         "exemption_expired": False}
        for i, s in enumerate(states, 1)]}
    doc.update(extra)
    return doc


def test_the_merge_gate_refuses_a_record_in_which_nothing_decided(tmp_path):
    """ARM A. `_hygiene_verdict` returned rc 0 — MERGE_OK — over this record.

    This is the half that actually gates a landing: the script's exit code is
    consulted, but the RECORD is what produces the verdict a maintainer reads.
    """
    res = GR._hygiene_verdict(_record(["NOT_CHECKED"] * 6), 2)

    assert res.rc == 2, (
        f"the merge gate answers rc {res.rc} over a sweep that reached no "
        f"verdict at all: {res.summary}")
    assert not res.green, res.summary
    assert "DECIDED NOTHING" in res.summary, res.summary
    # NOT reported as "the script and its summary disagree": the record here is
    # perfectly consistent, and that message points a reader away from the one
    # thing that happened.
    assert "while naming no failing gate" not in res.summary, res.summary


def test_the_merge_gate_still_passes_a_record_that_decided_something(tmp_path):
    """ARM B — the control. One PASS among five refusals is still MERGE_OK."""
    res = GR._hygiene_verdict(_record(["PASS"] + ["NOT_CHECKED"] * 5), 0)

    assert res.rc == 0 and res.green, (
        f"a record in which a gate DID decide is being refused as vacuous: "
        f"{res.summary}")
    assert "DECIDED NOTHING" not in res.summary, res.summary
    # #539/#584's disclosure is still carried, in prose, beside the pass.
    assert "NOT CHECKED (not a pass)" in res.summary, res.summary


def test_an_all_PASS_record_without_rollup_counters_is_not_called_vacuous():
    """`decided` is derived from `gates`, never from an absent counter.

    Several of this repo's fixtures carry `gates` without the top-level
    roll-up. Reading a missing `passed` as 0 would make a wholly GREEN record
    look like it decided nothing — the exact failure this branch exists to
    report, manufactured by the branch itself.
    """
    res = GR._hygiene_verdict(_record(["PASS"] * 4), 0)

    assert res.rc == 0, (
        f"an all-PASS record with no roll-up counters is being read as a "
        f"vacuous sweep: {res.summary}")
    assert "DECIDED NOTHING" not in res.summary, res.summary


def test_a_wholly_deferred_record_is_not_called_vacuous():
    """A `--list` record decided nothing by request, and says so already."""
    res = GR._hygiene_verdict(_record(["LISTED"] * 4, listed_only=True), 0)

    assert "DECIDED NOTHING" not in res.summary, res.summary
    assert res.green, res.summary


def test_a_shard_that_owns_no_gate_is_not_called_vacuous():
    """OTHER_SHARD is not a question this host declined — it is another host's.

    Proving every gate ran exactly once ACROSS shards is
    `hygiene_shard_aggregate`'s job, and it has the records to do it. Refusing
    here would make a legitimately empty shard permanently red.
    """
    res = GR._hygiene_verdict(_record(["OTHER_SHARD"] * 4), 0)

    assert "DECIDED NOTHING" not in res.summary, res.summary


def test_a_corpus_writer_stays_the_headline_over_a_vacuous_sweep():
    """A gate that CHANGED the tree every later gate read must be named first.

    WROTE_CORPUS does not count toward `decided` (its rc is never classified),
    so a record with one writer and nothing else is vacuous AND has a writer.
    The writer wins: any other result in that run may be about the leftovers
    rather than about the change, which is the misattribution that cost hours.
    """
    res = GR._hygiene_verdict(_record(["WROTE_CORPUS"] + ["NOT_CHECKED"] * 3), 1)

    assert res.rc == 1, res.summary
    assert "WROTE INTO the corpus" in res.summary, res.summary
