"""A ratchet whose ceiling can be lowered by an argument-free command.

vibe-ic#1704. `step_internal_fail_bubble_up_baseline.json` still described the
13-cell corpus after the v1.10.56 split published 4 cells. Pointed at a clone of
`vibeic/benchmark-data` the three recorded facts all said so::

    the ratchet baseline cites 9 run tree(s) that are not in the corpus
    recorded findings_total=22 but the corpus now carries 1
    recorded denominator (16, 16) != live (4, 4)

WHAT THE INSTRUMENT MEASURED AND WHAT IT CLAIMED. Every guard over that register
compares the recorded numbers against a fresh sweep, and the prescribed repair —
`--write-baseline` — re-derives the recorded numbers FROM that same fresh sweep.
So the pair agree by construction the moment anyone runs the repair: the
instrument measures "the record equals today's sweep" while the register's own
`_comment` claims "MAY ONLY SHRINK UNDER A FIXED POPULATION", i.e. that the
number cannot move without someone stating why. Nothing anywhere held a reason.
MEASURED against the published corpus at v1.10.69, one command with no argument
moved `findings_total` 22 -> 1 and the denominator 16/16 -> 4/4 and every
existing test went green.

AND ONE SMALLER INTEGER HAS THREE DIFFERENT CAUSES, which is the half #1704
names explicitly: "a denominator that drops from 16 to 4 because nine cells were
never published is a different fact from one that drops because nine cells were
deleted, and the record should say which". Before this change `_decompose_shrink`
had two buckets, REPAIRED and WITHDRAWN, and everything not in `examined_runs`
was WITHDRAWN — filed under a register whose comment asserts "These reports still
declare FAIL". That is a present-tense claim about documents the sweep never
opened. What a sweep of ONE corpus can actually see is whether the run tree is
there to be opened; which of removal and never-published happened needs history
it does not have. So the gate now separates the bucket it observes from the
bucket it cannot, and the operator states the rest in `shrink_reason`.

BIDIRECTIONAL THROUGHOUT. A gate that refused every shrink would pass the first
case here and be a ban rather than a ratchet, so each refusal is asserted beside
the write it must still allow, over the same fixture builder.

NOTHING HERE TOUCHES THE REPO'S REGISTER OR ANY CORPUS. Every case builds its
own tree under `tmp_path` and passes `--baseline` explicitly. The two cases that
read the SHIPPED register only read it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
GATE = PROGRAMS / "step_internal_fail_bubble_up_check.py"
SHIPPED = PROGRAMS / "step_internal_fail_bubble_up_baseline.json"

if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))
import _corpus_location as _cloc  # noqa: E402
import step_internal_fail_bubble_up_check as SIFBU  # noqa: E402

#: A reason long enough for the gate's own minimum. Written out rather than
#: generated, so a reader sees the kind of sentence the rule asks for.
REASON = ("the run trees this register named left the published corpus by a "
          "publishing decision recorded upstream; not one of their reports was "
          "re-read, so none of the fall is repair.")


def test_the_gate_still_publishes_the_names_this_module_measures():
    """Pinned FIRST, and as a test rather than an import-time assert.

    Every predicate below is written against `SHRINK_REASON_MIN_CHARS`,
    `_shrink_provenance_defects` and `_register_predates_shrink_ledger`. If the
    fix is reverted or those move, an import-time failure would collapse the
    whole module into one collection error that names none of the properties
    that were lost — the same "I could not look" reported as a single word this
    file exists to argue against. This says which name is gone, and the rest of
    the module then fails on its own subject.
    """
    for name in ("SHRINK_REASON_MIN_CHARS", "_shrink_provenance_defects",
                 "_register_predates_shrink_ledger", "_run_tree_is_in"):
        assert hasattr(SIFBU, name), (
            f"step_internal_fail_bubble_up_check no longer exposes `{name}`; "
            f"the vibe-ic#1704 shrink ledger is not in this tree, so nothing "
            f"below measures what it claims to.")
    assert len(REASON) >= SIFBU.SHRINK_REASON_MIN_CHARS, (
        f"this module's fixture reason is shorter than the gate's own minimum "
        f"({SIFBU.SHRINK_REASON_MIN_CHARS}); every write below would be "
        f"refused for the wrong cause.")


def _run(*args: str) -> subprocess.CompletedProcess:
    """The gate, with any ambient corpus pointer REMOVED.

    Every case here names its own `--corpus`, including the ones that name a
    path deliberately absent. A developer or CI job with
    `$VIBE_IC_BENCHMARK_DATA` set would otherwise have that pointer answer for
    the absent one — the gate is right to follow it, and this module would then
    be measuring the published corpus while claiming to measure a fixture.
    """
    env = {k: v for k, v in os.environ.items()
           if k != _cloc.CORPUS_ENV and k != _cloc.BOUND_SHA_ENV}
    return subprocess.run([sys.executable, str(GATE), *args],
                          capture_output=True, text=True, timeout=60, env=env)


def _mk_run(corpus: Path, rel: str, n_findings: int) -> Path:
    """One published run tree carrying `n_findings` unacknowledged FAILs.

    `n_findings == 0` still builds `reports/`, so the run IS examined and has
    nothing to report — the fixture a repair-to-zero turns on, as distinct from
    a run that stopped being swept.
    """
    d = corpus / rel / "reports" / "phase3"
    d.mkdir(parents=True, exist_ok=True)
    for i in range(1, n_findings + 1):
        (d / f"gate_{i}.json").write_text(json.dumps(
            {"verdict": "FAIL", "detail": f"synthetic unacknowledged fail {i}"}))
    return corpus / rel


def _first_write(corpus: Path, bl: Path) -> dict:
    r = _run("--corpus", str(corpus), "--baseline", str(bl), "--write-baseline")
    assert r.returncode == 0, f"fixture: first write failed\n{r.stdout}{r.stderr}"
    return json.loads(bl.read_text())


# ---------------------------------------------------------------------------
# 1. the write path — a fall needs a written reason, and a stated fall lands
# ---------------------------------------------------------------------------
def test_lowering_the_register_without_a_reason_is_refused(tmp_path):
    """THE DEFECT. `--write-baseline` re-derived every count from the current
    sweep, so the command the shrink branch TELLS the operator to run was also
    the command that lowered the ceiling with nobody on record."""
    corpus, bl = tmp_path / "bd", tmp_path / "bl.json"
    _mk_run(corpus, "ic/alpha/clean_run_A", 3)
    assert _first_write(corpus, bl)["findings_total"] == 3

    _mk_run(corpus, "ic/alpha/clean_run_A", 0)          # findings examined away
    for f in sorted((corpus / "ic/alpha/clean_run_A/reports/phase3").iterdir()):
        f.unlink()

    r = _run("--corpus", str(corpus), "--baseline", str(bl), "--write-baseline")
    assert r.returncode == 1, (
        f"a write that lowers findings_total 3 -> 0 must be refused without a "
        f"stated reason. rc={r.returncode}\n{r.stdout}{r.stderr}")
    assert "refusing to LOWER the register" in r.stderr, r.stderr
    assert "findings_total 3 -> 0" in r.stderr, r.stderr
    assert json.loads(bl.read_text())["findings_total"] == 3, (
        "the refused write must leave the register untouched")


def test_a_stated_reason_lets_the_same_write_through_and_is_recorded(tmp_path):
    """THE INVERSE, and without it the case above is a ban rather than a
    ratchet: the number must still be able to come down, on the record."""
    corpus, bl = tmp_path / "bd", tmp_path / "bl.json"
    _mk_run(corpus, "ic/alpha/clean_run_A", 3)
    _first_write(corpus, bl)
    for f in sorted((corpus / "ic/alpha/clean_run_A/reports/phase3").iterdir()):
        f.unlink()

    r = _run("--corpus", str(corpus), "--baseline", str(bl), "--write-baseline",
             "--shrink-reason", REASON)
    assert r.returncode == 0, f"{r.stdout}{r.stderr}"
    doc = json.loads(bl.read_text())
    assert doc["findings_total"] == 0, doc
    assert doc["previous_findings_total"] == 3, (
        f"the register must record the count it moved FROM: {doc}")
    assert doc["shrink_reason"] == REASON, doc
    # and the re-recorded register is then a line the gate will hold
    assert _run("--corpus", str(corpus), "--baseline", str(bl)).returncode == 0


def test_a_reason_too_short_to_say_anything_is_refused(tmp_path):
    """The length is the only property of free prose a program can check, and
    the two sides read it from one constant so they cannot drift apart."""
    corpus, bl = tmp_path / "bd", tmp_path / "bl.json"
    _mk_run(corpus, "ic/alpha/clean_run_A", 3)
    _first_write(corpus, bl)
    for f in sorted((corpus / "ic/alpha/clean_run_A/reports/phase3").iterdir()):
        f.unlink()
    r = _run("--corpus", str(corpus), "--baseline", str(bl), "--write-baseline",
             "--shrink-reason", "corpus moved")
    assert r.returncode == 1, f"{r.stdout}{r.stderr}"
    assert "refusing to LOWER the register" in r.stderr, r.stderr


def test_a_reason_on_a_write_that_lowers_nothing_is_refused(tmp_path):
    """A reason left standing on a register that fell nowhere is a permanent
    authorisation for whatever drop comes next, which reduces the forgery to a
    single number — the rule `published_record_staleness_check` already holds
    for its own register's growth (vibe-ic#922)."""
    corpus, bl = tmp_path / "bd", tmp_path / "bl.json"
    _mk_run(corpus, "ic/alpha/clean_run_A", 3)
    _first_write(corpus, bl)
    r = _run("--corpus", str(corpus), "--baseline", str(bl), "--write-baseline",
             "--shrink-reason", REASON)
    assert r.returncode == 1, f"{r.stdout}{r.stderr}"
    assert "lowers nothing" in r.stderr, r.stderr
    assert json.loads(bl.read_text())["shrink_reason"] is None


def test_a_reason_with_no_write_authorises_nothing_and_says_so():
    """Accepted silently it would read as "the shrink was justified" to whoever
    typed it while the register on disk is untouched."""
    r = _run("--corpus", "/nonexistent", "--corpus-may-be-absent",
             "--shrink-reason", REASON)
    assert r.returncode == 2, f"{r.stdout}{r.stderr}"
    assert "--shrink-reason is the justification" in r.stderr, r.stderr


def test_the_denominator_is_ratcheted_beside_the_numerator(tmp_path):
    """`findings_total` alone cannot tell "the failures were fixed" from "the
    runs carrying them are no longer swept" — the #1015 point, and exactly what
    a 16 -> 4 population change does to this register. So a fall in
    `runs_swept` / `runs_with_reports` needs the same statement even when the
    numerator does not move."""
    corpus, bl = tmp_path / "bd", tmp_path / "bl.json"
    _mk_run(corpus, "ic/alpha/clean_run_A", 1)
    _mk_run(corpus, "ic/beta/clean_run_B", 0)           # swept, nothing to say
    doc = _first_write(corpus, bl)
    assert (doc["runs_swept"], doc["runs_with_reports"]) == (2, 2), doc

    for p in sorted((corpus / "ic/beta").rglob("*"), reverse=True):
        p.unlink() if p.is_file() else p.rmdir()
    (corpus / "ic/beta").rmdir()

    r = _run("--corpus", str(corpus), "--baseline", str(bl), "--write-baseline")
    assert r.returncode == 1, (
        f"the numerator did not move (1 -> 1) but the population did; that "
        f"must still be stated. rc={r.returncode}\n{r.stdout}{r.stderr}")
    assert "runs_swept 2 -> 1" in r.stderr, r.stderr


# ---------------------------------------------------------------------------
# 2. the read path — the same rule, re-checked against the recorded numbers
# ---------------------------------------------------------------------------
def _hand_edit(bl: Path, **changes) -> None:
    doc = json.loads(bl.read_text())
    doc.update(changes)
    bl.write_text(json.dumps(doc, indent=2) + "\n")


def test_a_register_lowered_by_hand_is_reported_not_ratcheted(tmp_path):
    """A register is a plain JSON file, so the writer was never the only way to
    change it. Without this the whole rule above is one text editor away from
    being optional — the hole vibe-ic#922 closed one register over."""
    corpus, bl = tmp_path / "bd", tmp_path / "bl.json"
    _mk_run(corpus, "ic/alpha/clean_run_A", 2)
    _first_write(corpus, bl)
    _hand_edit(bl, previous_findings_total=9)     # claims a fall nobody stated

    r = _run("--corpus", str(corpus), "--baseline", str(bl))
    assert r.returncode == 1, f"{r.stdout}{r.stderr}"
    assert "no written `shrink_reason`" in r.stdout, r.stdout


def test_a_standing_reason_on_the_read_path_is_reported_too(tmp_path):
    """The other half of "the reason is spent by the write that used it"."""
    corpus, bl = tmp_path / "bd", tmp_path / "bl.json"
    _mk_run(corpus, "ic/alpha/clean_run_A", 2)
    _first_write(corpus, bl)
    _hand_edit(bl, shrink_reason=REASON)

    r = _run("--corpus", str(corpus), "--baseline", str(bl))
    assert r.returncode == 1, f"{r.stdout}{r.stderr}"
    assert "standing authorisation" in r.stdout, r.stdout


def test_a_register_that_states_no_previous_count_is_NOT_DETERMINED(tmp_path):
    """"I cannot tell a re-derivation from a hand-lowered ceiling" is neither a
    pass nor a finding. rc 2, the tier this program already uses, and the repair
    is named. Waving it through as "nothing to check" is the state a hand edit
    produces once someone notices the fields."""
    corpus, bl = tmp_path / "bd", tmp_path / "bl.json"
    _mk_run(corpus, "ic/alpha/clean_run_A", 2)
    bl.write_text(json.dumps({"findings_total": 2,
                              "corpus_population": "bd",
                              "per_run": {"alpha/clean_run_A": 2}}) + "\n")
    r = _run("--corpus", str(corpus), "--baseline", str(bl))
    assert r.returncode == 2, f"{r.stdout}{r.stderr}"
    assert "records none of `previous_findings_total`" in r.stdout, r.stdout


def test_the_register_is_adjudicated_with_no_corpus_at_all(tmp_path):
    """NO_CORPUS excuses the sweep, never the register — the rule
    `_adjudicate_register_without_a_corpus` already applies to the sum, applied
    to the ledger that says why the sum moved. Bidirectional: a consistent
    register still answers rc 0 there."""
    corpus, bl = tmp_path / "bd", tmp_path / "bl.json"
    _mk_run(corpus, "ic/alpha/clean_run_A", 2)
    _first_write(corpus, bl)
    absent = tmp_path / "gone"

    ok = _run("--corpus", str(absent), "--corpus-may-be-absent",
              "--baseline", str(bl))
    assert ok.returncode == 0, f"{ok.stdout}{ok.stderr}"

    _hand_edit(bl, previous_findings_total=9)
    bad = _run("--corpus", str(absent), "--corpus-may-be-absent",
               "--baseline", str(bl))
    assert bad.returncode == 1, f"{bad.stdout}{bad.stderr}"
    assert "no written `shrink_reason`" in bad.stderr, bad.stderr


# ---------------------------------------------------------------------------
# 3. the bucket the sweep can observe, and the one it cannot
# ---------------------------------------------------------------------------
def test_a_tree_that_is_still_there_is_withdrawn_and_one_that_is_not_is_absent(
        tmp_path):
    """THE DISTINCTION #1704 ASKS FOR, in both directions at once.

    `alpha` keeps its run tree and loses `reports/`: the sweep opened the
    directory and can state that it publishes nothing this gate reads.
    `beta`'s run tree is deleted outright: the sweep never opened it, so
    "these reports still declare FAIL" is not a measurement it made. Calling
    both WITHDRAWN, as the gate did, reports for the second what it could only
    see for the first.
    """
    corpus, bl = tmp_path / "bd", tmp_path / "bl.json"
    alpha = _mk_run(corpus, "ic/alpha/clean_run_A", 2)
    _mk_run(corpus, "ic/beta/clean_run_B", 3)
    _mk_run(corpus, "ic/gamma/clean_run_C", 1)          # keeps the sweep alive
    _first_write(corpus, bl)

    for p in sorted((alpha / "reports").rglob("*"), reverse=True):
        p.unlink() if p.is_file() else p.rmdir()
    (alpha / "reports").rmdir()                          # tree stays, reports go
    for p in sorted((corpus / "ic/beta").rglob("*"), reverse=True):
        p.unlink() if p.is_file() else p.rmdir()
    (corpus / "ic/beta").rmdir()                         # whole tree goes

    r = _run("--corpus", str(corpus), "--baseline", str(bl))
    assert r.returncode == 1, f"{r.stdout}{r.stderr}"
    assert "WITHDRAWN alpha/clean_run_A" in r.stdout, r.stdout
    assert "NOT IN CORPUS beta/clean_run_B" in r.stdout, r.stdout
    assert "NOT IN CORPUS alpha/clean_run_A" not in r.stdout, r.stdout
    assert "WITHDRAWN beta/clean_run_B" not in r.stdout, r.stdout
    # AND THE HEADLINE, which is the sentence a reader actually sees, names both
    # populations rather than folding one into the other's word.
    head = [l for l in r.stdout.splitlines() if l.startswith("[FAIL]")]
    assert len(head) == 1, r.stdout
    assert "NONE of it is repair" in head[0], head[0]
    assert "2 finding(s) left because their run stopped being swept" in head[0], \
        head[0]
    assert "3 finding(s) left because their run tree is not in the swept " \
           "corpus at all" in head[0], head[0]

    w = _run("--corpus", str(corpus), "--baseline", str(bl), "--write-baseline",
             "--shrink-reason", REASON)
    assert w.returncode == 0, f"{w.stdout}{w.stderr}"
    doc = json.loads(bl.read_text())
    assert doc["withdrawn_unexamined"] == {"alpha/clean_run_A": 2}, doc
    assert doc["absent_from_corpus"] == {"beta/clean_run_B": 3}, doc


def test_a_repair_is_still_a_repair_and_lands_in_neither_ledger(tmp_path):
    """The bidirectional partner: a fall somebody LOOKED at must keep being
    credited as work, or the new bucket has cost the gate its ability to
    recognise progress."""
    corpus, bl = tmp_path / "bd", tmp_path / "bl.json"
    _mk_run(corpus, "ic/alpha/clean_run_A", 2)
    _mk_run(corpus, "ic/gamma/clean_run_C", 1)
    _first_write(corpus, bl)
    (corpus / "ic/alpha/clean_run_A/reports/phase3/gate_1.json").unlink()

    r = _run("--corpus", str(corpus), "--baseline", str(bl))
    assert r.returncode == 1, f"{r.stdout}{r.stderr}"
    assert "REPAIRED  alpha/clean_run_A: 2 -> 1" in r.stdout, r.stdout
    assert "NOT IN CORPUS" not in r.stdout, r.stdout

    w = _run("--corpus", str(corpus), "--baseline", str(bl), "--write-baseline",
             "--shrink-reason", REASON)
    assert w.returncode == 0, f"{w.stdout}{w.stderr}"
    doc = json.loads(bl.read_text())
    assert doc["withdrawn_unexamined"] == {}, doc
    assert doc["absent_from_corpus"] == {}, doc


# ---------------------------------------------------------------------------
# 4. the shipped register, which is what #1704 was filed about
# ---------------------------------------------------------------------------
def test_the_shipped_register_states_why_its_numbers_fell():
    """THE GUARD ON THE RE-DERIVATION ITSELF.

    #1704 says it in one line: "Do NOT simply lower the numbers to make the
    tests green. The point of a ratchet is that the number cannot move without
    someone stating why." Lowering 22 -> 1 and 16/16 -> 4/4 satisfies every
    other test in this tree by construction; this is the one that does not.
    """
    doc = json.loads(SHIPPED.read_text(encoding="utf-8"))
    for k in ("previous_findings_total", "previous_runs_swept",
              "previous_runs_with_reports"):
        assert k in doc, (
            f"the shipped register does not record `{k}`, so nothing states "
            f"what its numbers moved FROM (vibe-ic#1704).")
    fell = [f"{k} {doc[p]} -> {doc[k]}"
            for k, p in (("findings_total", "previous_findings_total"),
                         ("runs_swept", "previous_runs_swept"),
                         ("runs_with_reports", "previous_runs_with_reports"))
            if isinstance(doc[p], int) and doc[k] < doc[p]]
    assert fell, (
        "the shipped register records no fall at all, which contradicts "
        "vibe-ic#1704 — it was re-derived from 22/16/16 down to the published "
        "corpus. A register that lost the fall lost the reason with it.")
    reason = doc.get("shrink_reason")
    assert isinstance(reason, str) and \
        len(reason.strip()) >= SIFBU.SHRINK_REASON_MIN_CHARS, (
        f"the shipped register lowered {', '.join(fell)} and states no "
        f"`shrink_reason` (>= {SIFBU.SHRINK_REASON_MIN_CHARS} chars): "
        f"{reason!r}")


def test_the_shipped_register_could_have_come_from_its_own_writer():
    """The read-path validator, run against the file CI actually ratchets.

    Deliberately not `@needs_corpus`: this opens no cell, so declining to run
    it where the corpus is absent would be a check refusing a measurement it
    can in fact make.
    """
    doc = SIFBU._load_baseline(SHIPPED)
    assert doc is not None, f"the shipped register is unreadable at {SHIPPED}"
    assert not SIFBU._register_predates_shrink_ledger(doc)
    assert SIFBU._shrink_provenance_defects(doc) == []


def test_the_shipped_register_separates_what_it_saw_from_what_it_did_not():
    """The two ledgers carry different claims, so an entry may sit in one only.

    A run counted in both would be one finding attributed twice, which is the
    double-count these registers exist to prevent.
    """
    doc = json.loads(SHIPPED.read_text(encoding="utf-8"))
    withdrawn = set(doc.get("withdrawn_unexamined", {}))
    absent = set(doc.get("absent_from_corpus", {}))
    live = {SIFBU._run_key(k) for k in doc.get("per_run", {})}
    assert not (withdrawn & absent), (
        f"{sorted(withdrawn & absent)} are recorded as BOTH withdrawn and "
        f"absent from the corpus; those are different claims about the same "
        f"run.")
    for name, ledger in (("withdrawn_unexamined", withdrawn),
                         ("absent_from_corpus", absent)):
        back = {k for k in ledger if SIFBU._run_key(k) in live}
        assert not back, (
            f"{sorted(back)} are in `{name}` and also in `per_run`; a run the "
            f"sweep can reach again is counted once, in `per_run`.")


@pytest.mark.parametrize("key", ["withdrawn_unexamined", "absent_from_corpus"])
def test_each_ledger_ships_the_comment_that_states_its_claim(key):
    """The two registers are told apart by what they assert, so a reader who
    opens the file must find both assertions in it."""
    doc = json.loads(SHIPPED.read_text(encoding="utf-8"))
    assert key in doc, f"the shipped register carries no `{key}`"
    comment = doc.get("_withdrawn_comment" if key == "withdrawn_unexamined"
                      else "_absent_comment")
    assert isinstance(comment, str) and comment.strip(), (
        f"`{key}` ships with no comment saying what it claims")
