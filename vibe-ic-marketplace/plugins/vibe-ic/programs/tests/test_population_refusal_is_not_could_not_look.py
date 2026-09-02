"""Two opposite facts must not share one exit code.

WHAT THIS FILE PINS
===================
`gate_dispatch_over` can end in two states that read almost the same in prose
and mean opposite things:

    I LOOKED       the corpus was opened, the producer succeeded, and the
                   population it yielded was ZERO. That is a finding ABOUT THE
                   REPOSITORY. It is BLOCKING and un-exemptible -- a population
                   refusal must not be purchasable with a date (#1769).
    I COULD NOT    no corpus was resolved, so NOTHING WAS OPENED and no
    LOOK           population was measured. That is a fact ABOUT THIS RUN. It is
                   UNDETERMINED and it must NAME what it could not read.

2026-09-03 -- THE OWNER RULED ON THE SECOND HALF OF THAT SENTENCE. It used to
end "and it is never blocking-because-unreadable". It no longer does: an empty
result is "I cannot see" and never "there is no problem", so a corpus nobody
opened may not close the hygiene DAG green. UNDETERMINED now exits 2 -- a
VISIBLE third state, not folded into PASS and not folded into FAIL (rc 1 would
redden every checkout without a corpus for a reason about the ENVIRONMENT and
not about the code).

WHAT THAT COSTS, STATED RATHER THAN GLOSSED. This file was written because the
two facts SHARED AN EXIT CODE and a lander could not tell them apart from it.
After the ruling they share one again -- deliberately, because the ruling is
that both are non-green. So the distinction has been RE-HOMED, not dropped:
`state` (UNDETERMINED vs NOT_CHECKED), `expansion` (NO_CORPUS vs EXPANDED), and
the two separate label channels (`undetermined_labels` vs
`not_checked_unexempted`). The anti-collapse test below now asserts it there,
and asserts the shared rc explicitly so a future reader sees it was decided
rather than lost.

MEASURED BEFORE THE SEPARATION: both dispatched `_dispatch 2 0`, so both
recorded `NOT_CHECKED` with `blocking_refusal=1` and both drove
`gate_dispatch_finish` into the same un-exemptible `exit 2`. The two had
DIFFERENT SENTENCES already -- vibe-ic#1764 gave the absent case its own text --
but a sentence is not what a `-ne 0` consumer reads. A lander whose corpus was
merely unbound got the same refusal as a repository whose published cells had
genuinely gone missing, and could not tell which from the exit code.

NOTHING WAS DROPPED FROM EITHER SIDE. The empty arm keeps every property #1769
built into it; the absent arm gets the shape the standing ruling requires. The
defect was only the shared rc.

BOTH DIRECTIONS ARE FALSIFIED HERE, because a change that only moved the absent
arm could pass a one-sided test while quietly unblocking the empty one:

    empty-but-readable  -> still refuses, still un-exemptible   (must NOT go quiet)
    absent              -> named could-not-look, refuses through its OWN door
                           and its OWN channel (must NOT be mistaken for the
                           other, and must NOT close green)

Driven through the REAL `tools/ci/_gate_dispatch.sh`: the verdicts are read out
of a live shell, not reasoned about from the source.

chip-AGNOSTIC: pure dispatcher plumbing. No design, PDK, vendor or SKU literal.
"""
from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_REPO = _PROGRAMS.parents[3]
_LIB = _REPO / "tools" / "ci" / "_gate_dispatch.sh"

_CORPUS = "a corpus under test"

#: Natural completion is the evidence; a clock expiry would prove nothing about
#: which state the structural row reached.
pytestmark = pytest.mark.timeout(0)


def _run(root: Path, body: str):
    """Drive the real dispatcher over `body` and return (proc, record)."""
    (root / "tools" / "ci").mkdir(parents=True, exist_ok=True)
    script = root / "tools" / "ci" / "gates.sh"
    script.write_text(textwrap.dedent(f"""\
        set -euo pipefail
        ROOT="{root}"
        . "{_LIB}"
        gate_dispatch_init "$@"
        """) + body + "\ngate_dispatch_finish\n")
    rec = root / "record.json"
    env = os.environ.copy()
    env["GATE_DISPATCH_ATTEST_POPULATION"] = "1"
    proc = subprocess.run(
        ["bash", str(script), "--summary-json", str(rec)],
        cwd=str(root), env=env, capture_output=True, text=True)
    doc = (json.loads(rec.read_text(encoding="utf-8"))
           if rec.is_file() and rec.stat().st_size else None)
    return proc, doc


#: A producer that SUCCEEDS and yields nothing: the corpus was opened and the
#: population really is zero.
_EMPTY = ('_body() { run "per item ($1)" "$ROOT" true; }\n'
          f'gate_dispatch_over "{_CORPUS}" _body printf ""\n')

#: A producer that exits `GATE_DISPATCH_ABSENT_RC` (3): no corpus was resolved,
#: nothing was opened. Spelled as the literal the library pins so this test
#: fails loudly if that contract number ever moves.
_ABSENT = ('_body() { run "per item ($1)" "$ROOT" true; }\n'
           '_producer() { echo "looked for a corpus and found none" >&2; '
           'exit "$GATE_DISPATCH_ABSENT_RC"; }\n'
           f'gate_dispatch_over "{_CORPUS}" _body _producer\n')

#: A control gate that decides. Present in both arms so neither arm is a run
#: with nothing in it, and so a change that broke ordinary gates would show up
#: here rather than as a confusing structural result.
_CONTROL = 'run "an ordinary gate that decides" "$ROOT" true\n'


def _structural_row(doc, needle):
    assert doc is not None, "the dispatcher wrote no summary record"
    rows = [g for g in (doc.get("gates") or [])
            if _CORPUS in str(g.get("label", ""))
            and needle in str(g.get("label", ""))]
    assert len(rows) == 1, json.dumps(doc.get("gates"), indent=1)
    return rows[0]


def _control_row(doc):
    rows = [g for g in (doc.get("gates") or [])
            if g.get("label") == "an ordinary gate that decides"]
    assert len(rows) == 1, json.dumps(doc.get("gates"), indent=1)
    return rows[0]


# ---------------------------------------------------------------- DIRECTION 1
def test_an_empty_but_readable_corpus_still_refuses_and_is_blocking(tmp_path):
    """I LOOKED and there was nothing there -- that stays a blocking refusal.

    This is the arm a careless separation would break: moving `absent` out of
    the blocking path is only correct if `empty` stays in it.
    """
    proc, doc = _run(tmp_path, _CONTROL + _EMPTY)
    text = proc.stdout + proc.stderr

    row = _structural_row(doc, "EMPTY")
    assert row["state"] == "NOT_CHECKED", (
        f"a MEASURED empty population stopped being a refusal: {row}")
    assert row["blocking_refusal"] is True, (
        f"the empty-corpus row is no longer blocking: {row}")
    assert proc.returncode != 0, (
        "the sweep certified a run whose declared population was measured at "
        "zero and never examined\n" + text)
    assert doc["not_checked_unexempted"], (
        "the empty row left the FAIL-SAFE list a landing consumer reads: "
        f"{json.dumps(doc)[:400]}")

    # The evidence entitling it to block: the read SUCCEEDED.
    assert "[READ_OK]" in text, (
        "a blocking population refusal must carry evidence that the corpus "
        "was actually opened -- without it there is nothing distinguishing it "
        "from a could-not-look\n" + text)
    assert "opened=yes" in text and "measured_items=0" in text, text


def test_an_empty_population_refusal_still_cannot_be_bought_with_a_date(tmp_path):
    """The un-exemptibility #1769 built is untouched by the separation."""
    proc, doc = _run(
        tmp_path,
        _CONTROL
        + 'uncheckable_until 2999-01-01 "the corpus is empty right now"\n'
        + _EMPTY)
    text = proc.stdout + proc.stderr
    assert any("population refusal" in ln and "uncheckable exemption" in ln
               for ln in text.splitlines() if "WIRING ERROR" in ln), (
        "an empty-population refusal became purchasable with a date\n" + text)
    assert proc.returncode != 0, text


# ---------------------------------------------------------------- DIRECTION 2
def test_an_absent_corpus_is_a_named_could_not_look_and_does_not_close_green(
        tmp_path):
    """I COULD NOT LOOK -- named, not a finding about the tree, and NOT a pass.

    Renamed with the ruling. The old name ended `_does_not_refuse`, and after
    2026-09-03 that sentence is false: a corpus nobody opened does not close
    the hygiene DAG green. Everything else this test asserted is unchanged and
    is exactly what the ruling requires -- the row is UNDETERMINED, it NAMES
    what it could not read, and it stays OUT of the refusal channel a landing
    consumer reads.
    """
    proc, doc = _run(tmp_path, _CONTROL + _ABSENT)
    text = proc.stdout + proc.stderr

    row = _structural_row(doc, "NOT FOUND")
    assert row["state"] == "UNDETERMINED", (
        f"an unresolvable corpus is still being recorded as a refusal: {row}")
    assert row["blocking_refusal"] is True, (
        f"the run exits 2 on this row and the record says it does not block; "
        f"a record that disagrees with the exit code is the defect this "
        f"cluster is about: {row}")

    assert proc.returncode == 2, (
        "the hygiene DAG closed GREEN over a corpus that was never opened. "
        "rc 2 is could-not-determine, NOT rc 1 (found a defect) -- the host "
        "could not resolve a corpus, which is still not a statement about "
        "the commit\n" + text)

    # It must NAME what it could not read, or it is a shrug.
    assert "[COULD_NOT_READ]" in text, text
    assert _CORPUS in text and "opened=no" in text, (
        "the could-not-look did not name the corpus it could not read\n" + text)
    assert "COULD NOT LOOK" in text, text

    # Counted and named in the record, and kept OUT of the refusal channels.
    assert doc["undetermined"] == 1, json.dumps(doc)[:400]
    assert any(_CORPUS in lbl for lbl in doc["undetermined_labels"]), doc
    assert not doc["not_checked_unexempted"], (
        "a could-not-look leaked into the list landing consumers refuse on: "
        f"{json.dumps(doc)[:400]}")


def test_an_absent_corpus_alone_does_not_trip_the_zero_decided_refusal(tmp_path):
    """The second door. `gate_dispatch_finish` refuses a run that DECIDED
    NOTHING, and that branch is guarded on `ran`. If a could-not-look counted
    as having run, an unbound corpus would refuse through this branch instead
    and the separation would buy nothing."""
    proc, doc = _run(tmp_path, _ABSENT)
    text = proc.stdout + proc.stderr
    assert "DECIDED NOTHING" not in text, (
        "an unresolvable corpus was refused by the ZERO DECIDED branch. It "
        "must refuse through its OWN door: DECIDED NOTHING means gates that "
        "COULD have decided and did not, which is a different fact and a "
        "different remedy\n" + text)
    # It DOES refuse (owner ruling) -- but as itself, and the sentence a
    # reader gets must be the could-not-look one.
    assert proc.returncode == 2, text
    assert "UNDETERMINED" in text and "NOTHING WAS SCANNED" in text, text


# ------------------------------------------------------- THE ANTI-COLLAPSE ---
def test_the_two_facts_do_not_share_a_state_or_a_channel(tmp_path):
    """The property, stated directly: same driver, one variable, two answers.

    Renamed: the two now SHARE an exit code, by ruling, because both are
    non-green. That is the one discriminator this file was originally written
    to create, so losing it silently would be the collapse it exists to
    refuse -- and it is therefore asserted here EXPLICITLY, beside the three
    channels that still tell the two apart. A reader who arrives at this file
    after the next change must be able to see that the shared rc was decided.
    """
    empty_proc, empty_doc = _run(tmp_path / "empty", _CONTROL + _EMPTY)
    absent_proc, absent_doc = _run(tmp_path / "absent", _CONTROL + _ABSENT)

    e = _structural_row(empty_doc, "EMPTY")
    a = _structural_row(absent_doc, "NOT FOUND")

    # STILL TWO STATES -- this is where the distinction lives now.
    assert e["state"] != a["state"], (
        f"both facts still record one state: {e['state']}")
    assert (e["state"], a["state"]) == ("NOT_CHECKED", "UNDETERMINED"), (e, a)

    # STILL TWO CHANNELS. A landing consumer reading the refusal list must be
    # reading refusals; a could-not-look must not be in it.
    assert any("EMPTY" in lbl for lbl in empty_doc["not_checked_unexempted"]), \
        empty_doc
    assert absent_doc["not_checked_unexempted"] == [], absent_doc
    assert absent_doc["undetermined"] == 1 and empty_doc["undetermined"] == 0, (
        empty_doc, absent_doc)

    # STILL TWO EXPANSIONS.
    exp = {c["name"]: c["expansion"] for c in empty_doc["corpora"]}
    exp_a = {c["name"]: c["expansion"] for c in absent_doc["corpora"]}
    assert exp[_CORPUS] == "EXPANDED" and exp_a[_CORPUS] == "NO_CORPUS", (
        exp, exp_a)

    # AND THEY SHARE AN EXIT CODE, deliberately (owner ruling, 2026-09-03):
    # both are non-green, so rc alone can no longer separate them. Asserted so
    # the sharing is a recorded decision rather than a regression nobody read.
    assert empty_proc.returncode == absent_proc.returncode == 2, (
        f"empty={empty_proc.returncode} absent={absent_proc.returncode}")


# -------------------------------------------------------------- CONTROL ------
def test_an_ordinary_gate_decides_in_both_arms(tmp_path):
    """CONTROL, green in BOTH arms and across the separation.

    If this ever goes red the change has reached ordinary gates, and every
    verdict above is about something other than what it claims.
    """
    for name, body in (("empty", _CONTROL + _EMPTY),
                       ("absent", _CONTROL + _ABSENT)):
        _proc, doc = _run(tmp_path / name, body)
        row = _control_row(doc)
        assert row["state"] == "PASS", (name, row)
        assert doc["decided"] >= 1, (name, json.dumps(doc)[:300])
