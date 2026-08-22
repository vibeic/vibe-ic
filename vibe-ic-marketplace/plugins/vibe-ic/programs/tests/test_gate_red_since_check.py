"""An acknowledged red must expire, and the ledger must never buy a green.

vibe-ic#1025. Every assertion below is a PAIR: the arm that must fail, and the
control arm that must pass. A one-arm test here would be worthless in a
specific way — this program's whole job is to distinguish two states of the
same ledger, so a test that only ever sees one state cannot tell a working
adjudicator from one that returns the same answer to everything.

The pairing is spelled out per test rather than parametrised, because the two
arms differ by exactly the field under test and naming that field in the test
name is the documentation.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROG = PLUGIN / "programs" / "gate_red_since_check.py"
ROOT = PLUGIN.parent.parent.parent
LEDGER = ROOT / "tools" / "ci" / "gate_red_since.json"

sys.path.insert(0, str(PLUGIN / "programs"))
import gate_red_since_check as G  # noqa: E402

SHA = "a" * 40


def _record(*gates, declared=None, listed_only=False):
    """A dispatch record in the exact shape `_gate_dispatch.sh` emits."""
    rows = [{"label": lbl, "state": st, "seconds": 0} for lbl, st in gates]
    return {
        "listed_only": listed_only,
        "declared": len(rows) if declared is None else declared,
        "ran": len(rows),
        "passed": sum(1 for _, s in gates if s == "PASS"),
        "failed": sum(1 for _, s in gates if s == "FAIL"),
        "not_checked": sum(1 for _, s in gates if s == "NOT_CHECKED"),
        "wrote_corpus": sum(1 for _, s in gates if s == "WROTE_CORPUS"),
        "deferred": sum(1 for _, s in gates if s == "LISTED"),
        "seconds": 1,
        "gates": rows,
    }


#: A stand-in `since_date`. Every fixture below injects its own age function,
#: so nothing here reads this value as a clock — it is present because a row
#: without it is `incomplete`, which is a different finding from the one under
#: test in each case.
DATE = "2026-01-01T00:00:00+00:00"


def _row(gate="a gate", since=SHA, max_days=3, **kw):
    row = {"gate": gate, "since": since, "since_date": DATE,
           "max_days": max_days, "owner": "vibe-ic#1028", "why": "measured"}
    row.update(kw)
    return row


def _age(n):
    """An age in DAYS for everything, or None to mean 'this repository does not
    contain that commit, or cannot date it'."""
    return lambda sha: n


# ---------------------------------------------------------------------------
# L3 — the deadline. This is the pair the program exists for.
# ---------------------------------------------------------------------------
def test_an_acknowledgement_past_its_bound_is_a_finding():
    findings, _, _ = G.adjudicate(_record(("a gate", "FAIL")),
                                  [_row(max_days=3)], _age(4))
    assert [f.kind for f in findings] == ["expired"]
    assert "4 day(s) ago" in findings[0].detail
    assert "vibe-ic#1028" in findings[0].detail, (
        "an expired row must name its owner — an expiry nobody is addressed to "
        "is the same unowned obligation this program replaces")


def test_the_same_acknowledgement_one_day_inside_its_bound_is_not():
    """The control. Without it, `expired` would be satisfied by a program that
    fails every acknowledged gate, which is a ban and not a deadline."""
    findings, known, new = G.adjudicate(_record(("a gate", "FAIL")),
                                        [_row(max_days=3)], _age(3))
    assert findings == []
    assert known == ["a gate"] and new == []


# ---------------------------------------------------------------------------
# L2 — a row that outlived its truth
# ---------------------------------------------------------------------------
def test_a_row_whose_gate_now_passes_is_stale():
    findings, _, _ = G.adjudicate(_record(("a gate", "PASS")),
                                  [_row()], _age(1))
    assert [f.kind for f in findings] == ["stale"]
    assert "PASSED in this run" in findings[0].detail


def test_a_row_whose_gate_is_still_red_is_not_stale():
    findings, known, _ = G.adjudicate(_record(("a gate", "FAIL")),
                                      [_row()], _age(1))
    assert findings == [] and known == ["a gate"]


def test_a_row_naming_a_gate_absent_from_the_record_is_stale():
    """Label drift. If this passed, renaming a gate would silently orphan its
    acknowledgement and the deadline would stop running."""
    findings, _, _ = G.adjudicate(_record(("some other gate", "FAIL")),
                                  [_row(gate="a gate")], _age(1))
    assert [f.kind for f in findings] == ["stale"]
    assert "no gate by this name ran" in findings[0].detail


def test_the_same_row_with_the_label_it_actually_has_is_accepted():
    findings, known, _ = G.adjudicate(_record(("a gate", "FAIL")),
                                      [_row(gate="a gate")], _age(1))
    assert findings == [] and known == ["a gate"]


# ---------------------------------------------------------------------------
# L1 — an acknowledgement with no deadline cannot be written
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("missing", list(G._REQUIRED_KEYS))
def test_a_row_missing_a_required_field_is_incomplete(missing):
    row = _row()
    del row[missing]
    findings, _, _ = G.adjudicate(_record(("a gate", "FAIL")), [row], _age(1))
    assert [f.kind for f in findings] == ["incomplete"]
    assert missing in findings[0].detail


def test_a_complete_row_is_not_incomplete():
    findings, _, _ = G.adjudicate(_record(("a gate", "FAIL")),
                                  [_row()], _age(1))
    assert findings == []


def test_a_non_integer_bound_is_incomplete_rather_than_crashing():
    findings, _, _ = G.adjudicate(_record(("a gate", "FAIL")),
                                  [_row(max_days="soon")], _age(1))
    assert [f.kind for f in findings] == ["incomplete"]


# ---------------------------------------------------------------------------
# L4 — a deadline that cannot be evaluated is not a deadline that is fine
# ---------------------------------------------------------------------------
def test_a_row_citing_an_unknown_commit_is_a_finding():
    findings, _, _ = G.adjudicate(_record(("a gate", "FAIL")),
                                  [_row()], lambda sha: None)
    assert [f.kind for f in findings] == ["unresolvable"]


def test_the_same_row_with_a_resolvable_commit_is_accepted():
    findings, _, _ = G.adjudicate(_record(("a gate", "FAIL")),
                                  [_row()], _age(1))
    assert findings == []


# ---------------------------------------------------------------------------
# The partition — the visibility half. Reported, deliberately not failed.
# ---------------------------------------------------------------------------
def test_a_new_red_is_separated_from_the_acknowledged_ones():
    findings, known, new = G.adjudicate(
        _record(("old", "FAIL"), ("today", "FAIL"), ("fine", "PASS")),
        [_row(gate="old")], _age(1))
    assert known == ["old"] and new == ["today"]
    assert findings == [], (
        "a NEW red must not be failed HERE — the suite already failed it, and "
        "reporting it twice adds nothing. The value is the partition")


def test_every_non_pass_state_counts_as_red_not_only_FAIL():
    """NOT_CHECKED and WROTE_CORPUS are results a reader must act on too.
    Counting them keeps an acknowledgement alive; it can never retire one."""
    _, _, new = G.adjudicate(
        _record(("refused", "NOT_CHECKED"), ("writer", "WROTE_CORPUS"),
                ("ok", "PASS")), [], _age(1))
    assert new == ["refused", "writer"]


def test_a_listed_gate_is_not_red():
    """`--list` declares without running. Treating LISTED as red would make
    every `--list` invocation look like a wall of failures."""
    _, _, new = G.adjudicate(_record(("a gate", "LISTED"),
                                     ("b gate", "FAIL")), [], _age(1))
    assert new == ["b gate"]


# ---------------------------------------------------------------------------
# The structural property: the ledger can only ADD failures
# ---------------------------------------------------------------------------
def test_adding_a_row_never_reduces_the_findings_of_a_red_run():
    """The anti-baseline property, asserted rather than asserted-in-prose.

    A register that can turn a gate green by gaining a row is a place to hide
    numbers. Here the red gate is reported red with and without the row, and
    the row's only effect is to move it from NEW to acknowledged."""
    rec = _record(("a gate", "FAIL"))
    f_without, known_without, new_without = G.adjudicate(rec, [], _age(1))
    f_with, known_with, new_with = G.adjudicate(rec, [_row()], _age(1))
    assert new_without == ["a gate"] and known_without == []
    assert new_with == [] and known_with == ["a gate"]
    # the red is present in BOTH readings — the row relocated it, not removed it
    assert len(known_without + new_without) == len(known_with + new_with) == 1
    assert f_without == [] and f_with == []


def test_the_suite_rc_is_untouched_by_this_program():
    """The claim that a row grants no leniency is about the DISPATCHER, so it
    is checked against the dispatcher, not against this module's docstring."""
    dispatch = (ROOT / "tools" / "ci" / "_gate_dispatch.sh").read_text()
    assert "gate_red_since" not in dispatch, (
        "this program must not be wired into the dispatcher's own rc decision. "
        "If it ever is, a ledger row could change whether the hygiene suite "
        "exits 0, which is exactly the power this design withholds from it")


# ---------------------------------------------------------------------------
# Vacuity — the rule this program is itself subject to
# ---------------------------------------------------------------------------
def test_a_record_declaring_zero_gates_is_vacuous():
    assert G.record_is_vacuous(_record(declared=0)) is not None


def test_a_record_declaring_one_gate_is_not_vacuous():
    assert G.record_is_vacuous(_record(("a gate", "FAIL"))) is None


def test_a_list_only_record_is_vacuous():
    assert G.record_is_vacuous(
        _record(("a gate", "LISTED"), listed_only=True)) is not None


# ---------------------------------------------------------------------------
# The CLI — exit codes, driven as a subprocess so the real argv path runs
# ---------------------------------------------------------------------------
def _cli(tmp_path, record, ledger_rows, name="r"):
    rec = tmp_path / f"{name}.json"
    rec.write_text(json.dumps(record))
    led = tmp_path / f"{name}_ledger.json"
    led.write_text(json.dumps({"acknowledged": ledger_rows}))
    return subprocess.run(
        [sys.executable, str(PROG), "--record", str(rec), "--ledger", str(led),
         "--repo", str(ROOT)], capture_output=True, text=True, timeout=60)


def test_cli_exits_0_when_every_red_is_new(tmp_path):
    res = _cli(tmp_path, _record(("a gate", "FAIL")), [])
    assert res.returncode == 0, res.stdout + res.stderr
    assert "1 NEW" in res.stdout


def test_cli_exits_1_on_a_stale_row(tmp_path):
    res = _cli(tmp_path, _record(("a gate", "PASS")),
               [_row(since="HEAD", max_days=3)])
    assert res.returncode == 1, res.stdout + res.stderr
    assert "[FAIL]" in res.stdout and "stale" in res.stdout


def test_cli_exits_2_and_announces_vacuous_on_an_empty_record(tmp_path):
    """The program refuses over an empty population for the same reason it
    exists to make other gates refuse over one."""
    res = _cli(tmp_path, _record(declared=0), [])
    assert res.returncode == 2, res.stdout + res.stderr
    assert "VACUOUS_PASS:" in res.stderr
    assert "[VACUOUS]" in res.stdout


def _real(rev="HEAD~5"):
    """A real commit of this repository AND its real date, or (None, None).

    Both are needed together. A row carrying the stub `DATE` against a real
    `since` is a `misdated` finding — the row and its own anchor disagreeing —
    which is the cross-check doing its job and not the clause under test in
    either arm below.
    """
    sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", rev],
                         capture_output=True, text=True).stdout.strip()
    if not sha:
        return None, None
    return sha, G.git_commit_date(ROOT)(sha)


def test_cli_exits_1_on_an_expired_row_against_real_git_history(tmp_path):
    """The one case that uses the REAL clock rather than an injected one, so a
    broken `git_age_days` cannot hide behind the pure-function tests above."""
    head, when = _real()
    if not head:
        pytest.skip("shallow history")
    res = _cli(tmp_path, _record(("a gate", "FAIL")),
               [_row(since=head, since_date=when, max_days=0)])
    assert res.returncode == 1, res.stdout + res.stderr
    assert "expired" in res.stdout


def test_cli_exits_0_for_the_same_history_inside_the_bound(tmp_path):
    head, when = _real()
    if not head:
        pytest.skip("shallow history")
    res = _cli(tmp_path, _record(("a gate", "FAIL")),
               [_row(since=head, since_date=when,
                     max_days=G.MAX_BOUND_DAYS)])
    assert res.returncode == 0, res.stdout + res.stderr


# ---------------------------------------------------------------------------
# The shipped ledger itself
# ---------------------------------------------------------------------------
def test_the_shipped_ledger_parses_and_every_row_is_complete():
    rows = G.load_ledger(LEDGER)
    for row in rows:
        for key in G._REQUIRED_KEYS:
            assert row.get(key) not in (None, ""), (
                f"shipped ledger row {row.get('gate')!r} is missing {key}")
        assert float(row["max_days"]) > 0


def test_an_absent_ledger_reads_as_empty_rather_than_raising(tmp_path):
    assert G.load_ledger(tmp_path / "nope.json") == []


def test_the_verdict_line_itself_carries_the_new_count(tmp_path):
    """`gatekeeper_review` keeps exactly ONE line of this program's output, so
    the partition has to survive on that line or it does not reach the landing
    reader at all — which would defeat the program's whole purpose."""
    res = _cli(tmp_path, _record(("today", "FAIL"), ("old", "FAIL")),
               [_row(gate="old", since="HEAD", max_days=G.MAX_BOUND_DAYS)])
    last = res.stdout.strip().splitlines()[-1]
    assert "1 NEW red" in last and "1 acknowledged" in last, last
    assert "today" in last, last


def test_the_verdict_line_says_zero_when_nothing_is_new(tmp_path):
    """The control: the count must track the record, not be decoration."""
    res = _cli(tmp_path, _record(("old", "FAIL")),
               [_row(gate="old", since="HEAD", max_days=G.MAX_BOUND_DAYS)])
    last = res.stdout.strip().splitlines()[-1]
    assert "0 NEW red" in last and "1 acknowledged" in last, last


# ---------------------------------------------------------------------------
# The cap — a bound that cannot arrive is not a bound
# ---------------------------------------------------------------------------
def test_a_bound_beyond_the_ceiling_is_a_finding():
    """The neutering diff, measured: without this the mechanism is switched off
    by editing the very file it adjudicates, and every other assertion here
    still passes."""
    findings, _, _ = G.adjudicate(_record(("a gate", "FAIL")),
                                  [_row(max_days=9999999)], _age(1))
    assert [f.kind for f in findings] == ["unbounded"]
    assert G._days(G.MAX_BOUND_DAYS) in findings[0].detail


def test_a_bound_exactly_at_the_ceiling_is_accepted():
    """The control. A cap that also rejected the largest legitimate bound would
    be an off-by-one that pushes people to renew a week early forever."""
    findings, known, _ = G.adjudicate(
        _record(("a gate", "FAIL")),
        [_row(max_days=G.MAX_BOUND_DAYS)], _age(1))
    assert findings == [] and known == ["a gate"]


def test_the_shipped_ledger_respects_the_ceiling():
    for row in G.load_ledger(LEDGER):
        assert float(row["max_days"]) <= G.MAX_BOUND_DAYS, row


def test_the_guard_is_in_the_smoke_floor_so_a_ledger_diff_reaches_it():
    """A ledger-only diff selects no test NAMED after the ledger. Measured: 16
    selected, this file not among them, until it joined the smoke floor."""
    sel = (PLUGIN / "programs" / "ci_targeted_test_select.py").read_text()
    assert '"test_gate_red_since_check.py",' in sel, (
        "the diff that switches this mechanism off must be able to select the "
        "test that guards it")
