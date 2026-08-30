"""A hygiene gate that FAILED is a verdict, not a shard that produced no record.

vibe-ic#1892.  `hygiene_shard_aggregate` answers a COVERAGE question — "can this
run state its own reach against the plan?" — and, because it holds the union, it
also reports the VERDICT it finds there.  Both refusals returned 1.
`repo_hygiene_parallel` asked the first question and read the answer to the
second: `if coverage_rc != 0: problems.append("… refused the run's coverage …")`.

A `problems` row becomes a `wiring_errors` row in `_merge`, `_summary_rc` returns
2 over it, and `gatekeeper_review._hygiene_verdict` prints it as

    ERROR — the hygiene set produced NO RECORD for 1 of its own shards, so it
    certifies nothing.  This is a SUPERVISION failure …

MEASURED on 7203d6fce (v1.13.39), one full set through
`gatekeeper_review.repo_hygiene_gate`, 501 s, this host:

    146/146 gate(s) ran · 9 of 9 shard records present · every planned label
    decided exactly once by its owning shard · 6 gates FAILED
      aggregate -> [FAIL] hygiene_shard_aggregate: 6 gate(s) FAILED: …   rc 1
                   and NOT ONE [COVERAGE] line, because there was no coverage
                   problem to print
      review    -> ERROR — … NO RECORD for 1 of its own shards …          rc 2

Nothing was lost.  Six honest reds were upgraded to UNKNOWN, and the reader was
sent to look for a missing shard that never existed, at "[COVERAGE] lines above"
that were never printed — and which `repo_hygiene_gate` discards in any case.
The consequence is the blocker: the hygiene set could not report a red AT ALL,
because any gate going FAIL collapsed the whole run to "certifies nothing".

THE HALF THAT MATTERS MOST IS THE SECOND ONE.  Everything under "the supervision
check still bites" below is a shard that GENUINELY disappears — a planned gate no
shard ran, a record that never arrived, a host that ignored its assignment, an
unreadable record, a gate decided twice — and every one of them must still refuse
to certify.  A guard that stopped refusing would not be a fix.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

_spec = importlib.util.spec_from_file_location(
    "_rhp_under_test", PROGRAMS / "repo_hygiene_parallel.py")
assert _spec and _spec.loader
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)

import hygiene_shard_aggregate as A  # noqa: E402
from gate_process_attestation import process_attestation  # noqa: E402

LABELS = ["gate a", "gate b"]

# THE CONTRACT, WRITTEN HERE AS LITERALS AND NOT READ OFF THE SUBJECT.
#
# Naming `COVERAGE_UNACCOUNTABLE` at import time makes this whole module fail
# to COLLECT against a tree that does not export it, and a collection error is
# not a red — it is rc 2, "the question could not be put", which is exactly the
# state this repo keeps mistaking for a result. The revert arm has to produce
# real assertion failures naming the real disagreement, so the two numbers this
# file asserts are stated here and the exports are checked BY a test.
#
#   2 — the run cannot state its own reach (UNKNOWN, and it must still refuse)
#   1 — the reach is accountable and the verdict over it is FAIL
COVERAGE_UNACCOUNTABLE = 2
VERDICT_FAILED = 1


# ── record fixtures ──────────────────────────────────────────────────────────

def _expect(tmp: Path, labels=LABELS) -> Path:
    p = tmp / "expect.txt"
    p.write_text("\n".join(labels) + "\n", encoding="utf-8")
    return p


def _record(tmp: Path, name: str, gates, shard=0) -> Path:
    doc = {"seconds": 3, "gates": [{"label": l, "state": s} for l, s in gates]}
    if shard is not None:
        doc["shard"] = shard
    p = tmp / f"{name}.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _ask(tmp: Path, records, *, expect=None, shards=None):
    """Exactly what `main` asks: the real aggregate, through the real reader."""
    argv = [*(str(r) for r in records),
            "--expect", str(expect or _expect(tmp)),
            "--shards", str(len(records) if shards is None else shards)]
    return P.coverage_problems(A, argv, tmp / "coverage.json")


def _rc(tmp: Path, records, *, expect=None, shards=None) -> int:
    """The aggregate's own exit code for the same input."""
    return A.main([*(str(r) for r in records),
                   "--expect", str(expect or _expect(tmp)),
                   "--shards", str(len(records) if shards is None else shards)])


# ── the control: green in both arms ──────────────────────────────────────────

def test_CONTROL_complete_coverage_and_no_red_is_a_pass(tmp_path):
    """GREEN IN BOTH ARMS, and it touches nothing this change adds.

    A clean sharded run was rc 0 before and is rc 0 after. If this ever goes red
    the subject is broken in a way none of the negatives below would separate
    from the fix, so it is what stops this file being "the tests the change
    happens to satisfy"."""
    records = [_record(tmp_path, "s0", [("gate a", "PASS"),
                                        ("gate b", "OTHER_SHARD")], shard=0),
               _record(tmp_path, "s1", [("gate a", "OTHER_SHARD"),
                                        ("gate b", "PASS")], shard=1)]
    assert _rc(tmp_path, records) == 0


def test_a_clean_run_files_no_coverage_problem(tmp_path):
    """The reader's half of the control: rc 0 must produce no row either."""
    records = [_record(tmp_path, "s0", [("gate a", "PASS"),
                                        ("gate b", "OTHER_SHARD")], shard=0),
               _record(tmp_path, "s1", [("gate a", "OTHER_SHARD"),
                                        ("gate b", "PASS")], shard=1)]
    assert _ask(tmp_path, records) == []


# ── the fix: a verdict is not a coverage refusal ─────────────────────────────

def test_a_FAILED_gate_over_complete_coverage_files_no_coverage_problem(tmp_path):
    """THE FIX.  Coverage is byte-identical to the control — every planned gate
    decided exactly once, both records present, both sharded — and the only
    difference is that one gate FAILED.  That is a verdict this module already
    computes from these same records; it must not arrive as a lost shard."""
    records = [_record(tmp_path, "s0", [("gate a", "PASS"),
                                        ("gate b", "OTHER_SHARD")], shard=0),
               _record(tmp_path, "s1", [("gate a", "OTHER_SHARD"),
                                        ("gate b", "FAIL")], shard=1)]
    assert _rc(tmp_path, records) == VERDICT_FAILED
    assert _ask(tmp_path, records) == [], (
        "a gate that FAILED was reported as a coverage/NO RECORD problem")


def test_a_corpus_writer_over_complete_coverage_files_no_coverage_problem(tmp_path):
    """The other verdict this program reports.  WROTE_CORPUS is a real refusal
    and `_summary_rc` already returns 1 for it; it is not a lost shard either."""
    records = [_record(tmp_path, "s0", [("gate a", "PASS"),
                                        ("gate b", "OTHER_SHARD")], shard=0),
               _record(tmp_path, "s1", [("gate a", "OTHER_SHARD"),
                                        ("gate b", "WROTE_CORPUS")], shard=1)]
    assert _rc(tmp_path, records) == VERDICT_FAILED
    assert _ask(tmp_path, records) == []


def test_the_red_still_blocks_it_is_reported_as_FAILED_not_as_UNKNOWN(tmp_path):
    """Nothing is silenced: the run still refuses, at rc 1 with the gate NAMED,
    instead of rc 2 with nothing attributed.  This is the whole delta a reader
    of the tier sees."""
    reference = {"gates": [_g("gate a", "LISTED"), _g("gate b", "LISTED")],
                 "corpora": [], "corpus_inputs": {"benchmark_data_sha": None},
                 "undisclosed_loops": [], "today": "2026-08-30"}
    a = _doc(reference, [("gate a", "FAIL"), ("gate b", "OTHER_SHARD")], "0/2")
    b = _doc(reference, [("gate a", "OTHER_SHARD"), ("gate b", "PASS")], "1/2")
    attest = [process_attestation("gate a", "[FAIL] x", 1, ["false"]),
              process_attestation("gate b", "", 0, ["true"])]
    problems: list[str] = []
    doc = P.merge_records(reference, [(Path("a"), a), (Path("b"), b)],
                          attest, 9, problems)
    assert problems == []
    assert doc["wiring_errors"] == []
    assert P._summary_rc(doc) == 1
    assert doc["failed"] == 1


# ── the supervision check still bites ────────────────────────────────────────

def test_a_planned_gate_no_shard_ran_still_refuses_and_is_NAMED(tmp_path):
    records = [_record(tmp_path, "s0", [("gate a", "PASS"),
                                        ("gate b", "OTHER_SHARD")], shard=0),
               _record(tmp_path, "s1", [("gate a", "OTHER_SHARD"),
                                        ("gate b", "OTHER_SHARD")], shard=1)]
    assert _rc(tmp_path, records) == COVERAGE_UNACCOUNTABLE
    rows = _ask(tmp_path, records)
    assert rows, "a gate no shard ran certified silently"
    assert any("gate b" in r for r in rows), rows


def test_a_shard_record_that_never_arrived_still_refuses(tmp_path):
    """The literal case in the tier's sentence: a shard produced no record."""
    records = [_record(tmp_path, "s0", [("gate a", "PASS"),
                                        ("gate b", "OTHER_SHARD")], shard=0)]
    assert _rc(tmp_path, records, shards=2) == COVERAGE_UNACCOUNTABLE
    rows = _ask(tmp_path, records, shards=2)
    assert any("shard(s) planned" in r for r in rows), rows


def test_a_host_that_ignored_its_shard_assignment_still_refuses(tmp_path):
    records = [_record(tmp_path, "u", [("gate a", "PASS"), ("gate b", "PASS")],
                       shard=None)]
    assert _rc(tmp_path, records, shards=1) == COVERAGE_UNACCOUNTABLE
    assert any("UNSHARDED" in r for r in _ask(tmp_path, records, shards=1))


def test_an_unreadable_shard_record_still_refuses(tmp_path):
    broken = tmp_path / "trunc.json"
    broken.write_text('{"shard": 1, "gates": [{"label": "gate b",',
                      encoding="utf-8")
    records = [_record(tmp_path, "s0", [("gate a", "PASS"),
                                        ("gate b", "OTHER_SHARD")], shard=0),
               broken]
    assert _rc(tmp_path, records) == COVERAGE_UNACCOUNTABLE
    assert _ask(tmp_path, records), "a truncated record certified silently"


def test_a_gate_decided_by_two_shards_still_refuses(tmp_path):
    records = [_record(tmp_path, "s0", [("gate a", "PASS"),
                                        ("gate b", "PASS")], shard=0),
               _record(tmp_path, "s1", [("gate a", "OTHER_SHARD"),
                                        ("gate b", "PASS")], shard=1)]
    assert _rc(tmp_path, records) == COVERAGE_UNACCOUNTABLE
    assert any("MORE THAN ONE" in r for r in _ask(tmp_path, records))


def test_an_empty_denominator_still_refuses(tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_text("", encoding="utf-8")
    records = [_record(tmp_path, "s0", [("gate a", "PASS")], shard=0)]
    assert _rc(tmp_path, records, expect=empty) == COVERAGE_UNACCOUNTABLE
    assert _ask(tmp_path, records, expect=empty), (
        "a run over no denominator certified silently")


def test_a_coverage_refusal_reaches_the_verdict_as_rc_2(tmp_path):
    """End to end inside this module: a coverage row still makes the whole set
    uncertifiable, which is the property the tier's sentence is about."""
    reference = {"gates": [_g("gate a", "LISTED")], "corpora": [],
                 "corpus_inputs": {"benchmark_data_sha": None},
                 "undisclosed_loops": [], "today": "2026-08-30"}
    a = _doc(reference, [("gate a", "PASS")], "0/2")
    attest = [process_attestation("gate a", "", 0, ["true"])]
    problems = ["hygiene_shard_aggregate: 1 record(s) given, 2 shard(s) planned"]
    doc = P.merge_records(reference, [(Path("a"), a)], attest, 9, problems)
    assert doc["wiring_errors"], doc["wiring_errors"]
    assert all(w.startswith("parallel coverage: ") for w in doc["wiring_errors"])
    assert P._summary_rc(doc) == 2


# ── fail-closed on the instrument itself ─────────────────────────────────────

class _Stub:
    """An aggregate that behaves exactly as told.  The real program cannot
    produce these states, and a reader that trusted it blindly would be blind
    precisely when its coverage police had stopped working."""

    COVERAGE_UNACCOUNTABLE = 2
    VERDICT_FAILED = 1

    def __init__(self, rc, payload):
        self.rc, self.payload = rc, payload

    def main(self, argv):
        out = Path(argv[argv.index("--json") + 1])
        if self.payload is not None:
            out.write_text(self.payload, encoding="utf-8")
        return self.rc


def test_an_absent_coverage_record_is_itself_a_coverage_problem(tmp_path):
    rows = P.coverage_problems(_Stub(0, None), ["x"], tmp_path / "c.json")
    assert rows and "no readable coverage record" in rows[0], rows


@pytest.mark.parametrize("payload", [
    "{not json",                       # unreadable
    '{"decided": 1}',                  # no `problems` key at all
    '{"problems": "lost a shard"}',    # not a list
    '{"problems": [7]}',               # not a list of strings
])
def test_a_malformed_coverage_record_is_itself_a_coverage_problem(
        tmp_path, payload):
    rows = P.coverage_problems(_Stub(0, payload), ["x"], tmp_path / "c.json")
    assert rows and "no readable coverage record" in rows[0], rows


def test_an_unenumerated_exit_code_is_itself_a_coverage_problem(tmp_path):
    rows = P.coverage_problems(_Stub(199, '{"problems": []}'), ["x"],
                               tmp_path / "c.json")
    assert any("unenumerated exit code 199" in r for r in rows), rows


def test_a_coverage_refusal_that_names_no_row_cannot_be_attributed(tmp_path):
    rows = P.coverage_problems(
        _Stub(COVERAGE_UNACCOUNTABLE, '{"problems": []}'), ["x"],
        tmp_path / "c.json")
    assert any("named no row" in r for r in rows), rows


def test_a_verdict_rc_that_names_no_row_files_nothing(tmp_path):
    """rc 1 with an accountable denominator is the whole point: no row."""
    assert P.coverage_problems(
        _Stub(VERDICT_FAILED, '{"problems": []}'), ["x"],
        tmp_path / "c.json") == []


def test_the_reader_no_longer_defers_to_output_it_cannot_see(tmp_path):
    """The row this branch used to append pointed at `[COVERAGE]` lines that
    `gatekeeper_review.repo_hygiene_gate` captures and discards.  Every row it
    files now carries its own reason."""
    records = [_record(tmp_path, "s0", [("gate a", "PASS"),
                                        ("gate b", "OTHER_SHARD")], shard=0)]
    rows = _ask(tmp_path, records, shards=2)
    assert rows
    assert not any("lines above" in r for r in rows), rows


# ── shared record helpers ────────────────────────────────────────────────────

def _g(label, state):
    return {"label": label, "state": state, "seconds": 1,
            "exempt_until": None, "exempt_reason": None,
            "exemption_expired": False}


def _doc(reference, gates, shard):
    return {"listed_only": False, "shard": shard,
            "gates": [_g(l, s) for l, s in gates],
            "corpora": reference["corpora"],
            "corpus_inputs": reference["corpus_inputs"],
            "undisclosed_loops": reference["undisclosed_loops"],
            "today": reference["today"], "wiring_errors": []}


def test_the_two_exit_codes_are_EXPORTED_and_distinct():
    """The split has to be a declared contract, not an implementation detail a
    caller re-derives.  `repo_hygiene_parallel` reads these names."""
    assert A.COVERAGE_UNACCOUNTABLE == COVERAGE_UNACCOUNTABLE
    assert A.VERDICT_FAILED == VERDICT_FAILED
    assert A.COVERAGE_UNACCOUNTABLE != A.VERDICT_FAILED


# ── the whole chain, with a shard that genuinely disappeared ─────────────────

def test_a_LOST_SHARD_still_reaches_the_reader_as_SUPERVISION_at_rc_2(tmp_path):
    """END TO END through every real link, with nothing stubbed.

    A guard that stops refusing is not a fix, so this drives the case the
    tier's sentence is actually about — a shard record that never arrived —
    from the aggregate all the way to the sentence a maintainer reads:

        hygiene_shard_aggregate  -> rc 2 + a named [COVERAGE] row
        coverage_problems        -> that row, carrying its own reason
        merge_records            -> `parallel coverage: …` in wiring_errors
        _summary_rc              -> 2
        _hygiene_verdict         -> rc 2, "produced NO RECORD … SUPERVISION"

    and asserts the refusal survives every one of them.
    """
    import importlib.util as _il
    # The spec name must BE `gatekeeper_review`: `@dataclass` resolves the
    # defining module through `sys.modules[cls.__module__]`, so a private alias
    # makes `GateResult` unconstructable. Same shape as
    # `test_a_shard_that_produced_no_record_is_not_a_wiring_error.py`.
    _s = _il.spec_from_file_location("gatekeeper_review",
                                     PROGRAMS / "gatekeeper_review.py")
    GR = _il.module_from_spec(_s)
    sys.modules["gatekeeper_review"] = GR       # @dataclass needs it importable
    _s.loader.exec_module(GR)

    # Two shards were planned. Only shard 0 ever reported.
    survivor = _record(tmp_path, "s0", [("gate a", "PASS"),
                                        ("gate b", "OTHER_SHARD")], shard=0)
    rows = _ask(tmp_path, [survivor], shards=2)
    assert rows, "a shard that never reported was tolerated"
    assert any("shard(s) planned" in r for r in rows), rows
    assert any("gate b" in r for r in rows), rows

    reference = {"gates": [_g("gate a", "LISTED"), _g("gate b", "LISTED")],
                 "corpora": [], "corpus_inputs": {"benchmark_data_sha": None},
                 "undisclosed_loops": [], "today": "2026-08-30"}
    a = _doc(reference, [("gate a", "PASS"), ("gate b", "OTHER_SHARD")], "0/2")
    attest = [process_attestation("gate a", "", 0, ["true"])]
    problems = list(rows)
    doc = P.merge_records(reference, [(Path("a"), a)], attest, 9, problems)

    assert doc["parallel"]["complete"] is False
    assert any(w.startswith("parallel coverage: ") for w in doc["wiring_errors"])
    assert P._summary_rc(doc) == 2

    verdict = GR._hygiene_verdict(doc, 2)
    assert verdict.rc == 2, verdict.summary
    assert "NO RECORD" in verdict.summary, verdict.summary
    assert "SUPERVISION" in verdict.summary, verdict.summary
    assert "certifies nothing" in verdict.summary, verdict.summary
