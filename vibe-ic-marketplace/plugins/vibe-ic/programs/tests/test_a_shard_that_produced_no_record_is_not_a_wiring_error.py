"""A hygiene set that could not record part of itself must say THAT.

`repo_hygiene_parallel._merge` folds its coverage `problems` into the record's
`wiring_errors` list under a `parallel coverage: ` prefix. `_hygiene_verdict`
then reported the whole list as "N wiring error(s) in the hygiene gate
DECLARATIONS" — which is false for those rows and false in the expensive
direction: it sends the reader to the gate wiring to look for a defect that is
not there.

MEASURED on pristine main 6c798ce4be, one full `gatekeeper_review.py` run, the
only BLOCKING line in it:

    ERROR — 75 wiring error(s) in the hygiene gate declarations, so the set
    certifies nothing: parallel coverage: arm A shard 0:
    OWNED_SUPERVISOR_NORECORD: private supervisor channel failed before a
    terminal record; atomic cleanup=shutdown_complete/final_descendants=[];
    parallel coverage: arm A shard 0: no summary (rc=2); … [145/145 gate(s)
    ran in 289s; 35 NOT CHECKED (not a pass)]

Every named row is a shard NORECORD, and each carries its own cleanup proof —
`final_descendants=[]`, nothing left running. The shard did not mis-declare a
gate; it could not certify what it measured.

THE VERDICT DOES NOT MOVE, and these tests pin that as hard as they pin the
wording: rc 2 ERROR either way, every row still present in the record, and a
clean record still rc 0. What changes is only that the reason is true.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

_spec = importlib.util.spec_from_file_location(
    "gatekeeper_review", _PROGRAMS / "gatekeeper_review.py")
GR = importlib.util.module_from_spec(_spec)
sys.modules["gatekeeper_review"] = GR       # required: @dataclass needs it
_spec.loader.exec_module(GR)

_COVER = "parallel coverage: "
_SHARD_NORECORD = (
    _COVER + "arm A shard 0: OWNED_SUPERVISOR_NORECORD: private supervisor "
    "channel failed before a terminal record; atomic cleanup="
    "shutdown_complete/final_descendants=[]")
_SHARD_NO_SUMMARY = _COVER + "arm A shard 0: no summary (rc=2)"
_REAL_WIRING = ("'uncheckable_until': an exemption was declared and no gate "
                "consumed it")


def _record(wiring, *, declared=3, passed=3):
    """A record of the shape `_hygiene_verdict` reads."""
    gates = [{"label": f"g{i}", "state": "PASS"} for i in range(passed)]
    return {
        "listed_only": False, "declared": declared, "ran": passed,
        "decided": passed, "passed": passed, "failed": 0,
        "not_checked": 0, "not_checked_unexempted": [],
        "exemptions_expired": [], "wiring_errors": list(wiring),
        "wrote_corpus": 0, "deferred": 0, "other_shard": 0,
        "out_of_scope": 0, "seconds": 289, "gates": gates,
    }


def _verdict(wiring, script_rc=2):
    return GR._hygiene_verdict(_record(wiring), script_rc)


def test_a_shard_norecord_is_not_reported_as_a_declaration_defect():
    """THE FIX. Coverage rows alone must name SUPERVISION, and must not accuse
    the gate declarations of anything."""
    r = _verdict([_SHARD_NORECORD, _SHARD_NO_SUMMARY])
    assert r.rc == 2, f"the verdict moved; it must stay ERROR: {r.rc}"
    assert "produced NO RECORD for 2 of its own shards" in r.summary, r.summary
    assert "SUPERVISION failure" in r.summary, r.summary
    assert "wiring error(s) in the hygiene gate declarations" not in r.summary, (
        "a shard that produced no record is still being reported as a defect "
        "in the gate declarations — the false sentence this test exists for:\n"
        + r.summary)


def test_the_rows_are_still_all_there_nothing_is_silenced():
    """A record that carries these rows still certifies NOTHING, and the rows
    themselves are untouched in the record every other consumer reads."""
    rec = _record([_SHARD_NORECORD, _SHARD_NO_SUMMARY])
    r = GR._hygiene_verdict(rec, 2)
    assert r.rc == 2
    assert rec["wiring_errors"] == [_SHARD_NORECORD, _SHARD_NO_SUMMARY], (
        "the verdict mutated the record it was handed")
    assert "certifies nothing" in r.summary, r.summary


def test_a_real_declaration_error_still_says_declarations():
    """THE NEGATIVE CONTROL for the wording. If the new branch swallowed the
    old one, a genuine wiring error would stop naming the declarations — and
    the fix would have traded one false sentence for another."""
    r = _verdict([_REAL_WIRING])
    assert r.rc == 2
    assert "1 wiring error(s) in the hygiene gate declarations" in r.summary, \
        r.summary
    assert "SUPERVISION failure" not in r.summary, r.summary


def test_both_kinds_together_are_both_counted():
    """The mixed case is the one a single headline cannot serve, so it names
    both counts rather than picking a winner."""
    r = _verdict([_REAL_WIRING, _SHARD_NORECORD])
    assert r.rc == 2
    assert "1 wiring error(s) in the hygiene gate declarations AND 1 shard(s)" \
        in r.summary, r.summary


@pytest.mark.parametrize("wiring", [
    [_SHARD_NORECORD],
    [_REAL_WIRING],
    [_REAL_WIRING, _SHARD_NORECORD, _SHARD_NO_SUMMARY],
])
def test_every_shape_still_refuses(wiring):
    """The load-bearing half: whatever the wording, a set that reports either
    kind certifies nothing and must return rc 2. A rename that bought a green
    would be the defect, not the fix."""
    assert _verdict(wiring).rc == 2


def test_control_a_clean_record_is_still_a_pass():
    """THE CONTROL GREEN. With no rows of either kind the verdict is unchanged
    — the fix may only re-describe a refusal, never create or remove one."""
    r = _verdict([], script_rc=0)
    assert r.rc == 0, f"a clean hygiene record stopped passing: {r.summary}"
    assert "certifies nothing" not in r.summary, r.summary
