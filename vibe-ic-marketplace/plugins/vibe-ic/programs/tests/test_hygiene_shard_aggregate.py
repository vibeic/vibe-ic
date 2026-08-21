"""`hygiene_shard_aggregate` must refuse a run that lost coverage quietly.

vibe-ic#1144 shards the landing gate across hosts. The program under test exists
for one failure: a RIGHT-LOOKING verdict over fewer gates than the caller
believes ran. Its docstring lists five things it checks, and this file asserts
each one in BOTH directions — the honest input passes, and the damaged input
FAILS. A test that only proves the happy path would let the whole guard be
deleted and still read green, which is the shape #1144 is about.

The program shipped with no tests at all; `plugin_full_audit` D1 caught it
("untested non-synth programs"). These were written from its stated contract, not
from its implementation, so they still mean something if the implementation is
rewritten.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "hygiene_shard_aggregate.py"
LABELS = ["gate a", "gate b", "gate c"]


def _expect(tmp: Path, labels=LABELS) -> Path:
    p = tmp / "expect.txt"
    p.write_text("\n".join(labels) + "\n", encoding="utf-8")
    return p


def _record(tmp: Path, name: str, shard: int, gates, seconds: int = 10) -> Path:
    """One shard's record. `gates` is [(label, state), ...]."""
    p = tmp / f"{name}.json"
    p.write_text(json.dumps({
        "shard": shard,
        "seconds": seconds,
        "gates": [{"label": l, "state": s} for l, s in gates],
    }), encoding="utf-8")
    return p


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG), *[str(a) for a in args]],
                          capture_output=True, text=True, timeout=60)


# ── the honest case ──────────────────────────────────────────────────────────

def test_a_complete_run_is_a_pass_and_states_its_denominator(tmp_path):
    """Every expected label decided exactly once, across the planned shards."""
    r = _run(_record(tmp_path, "s0", 0, [("gate a", "PASS"), ("gate b", "PASS")]),
             _record(tmp_path, "s1", 1, [("gate c", "PASS")]),
             "--expect", _expect(tmp_path), "--shards", 2)
    assert r.returncode == 0, r.stdout + r.stderr
    # The denominator has to be VISIBLE, not merely correct: a reader who cannot
    # see the reach cannot tell this verdict from one over half the gates.
    assert "3" in r.stdout, r.stdout


# ── each guard, in both directions ───────────────────────────────────────────

def test_a_label_nobody_reported_fails_the_run(tmp_path):
    """Nothing dropped. A gate the plan assigned and no shard ran is a FAILURE,
    not a smaller run."""
    ok = _run(_record(tmp_path, "s0", 0, [("gate a", "PASS"), ("gate b", "PASS")]),
              _record(tmp_path, "s1", 1, [("gate c", "PASS")]),
              "--expect", _expect(tmp_path), "--shards", 2)
    assert ok.returncode == 0, "the control arm must pass or the negative proves nothing"

    bad = _run(_record(tmp_path, "b0", 0, [("gate a", "PASS"), ("gate b", "PASS")]),
               _record(tmp_path, "b1", 1, []),          # gate c ran nowhere
               "--expect", _expect(tmp_path), "--shards", 2)
    assert bad.returncode != 0, "a lost gate passed silently:\n" + bad.stdout
    assert "gate c" in bad.stdout, "the missing gate is not named:\n" + bad.stdout


def test_a_label_decided_twice_fails_the_run(tmp_path):
    """Nothing double-run. Two hosts deciding one gate means two trees were
    mutated and only one was read."""
    bad = _run(_record(tmp_path, "d0", 0, [("gate a", "PASS"), ("gate b", "PASS")]),
               _record(tmp_path, "d1", 1, [("gate b", "PASS"), ("gate c", "PASS")]),
               "--expect", _expect(tmp_path), "--shards", 2)
    assert bad.returncode != 0, "a double-decided gate passed:\n" + bad.stdout
    assert "gate b" in bad.stdout, bad.stdout


def test_a_shard_that_never_reported_fails_the_run(tmp_path):
    """A dead host is a failure, not an absence. Two records where three were
    planned must not be read as a complete two-shard run."""
    bad = _run(_record(tmp_path, "m0", 0, [("gate a", "PASS")]),
               _record(tmp_path, "m1", 1, [("gate b", "PASS"), ("gate c", "PASS")]),
               "--expect", _expect(tmp_path), "--shards", 3)
    assert bad.returncode != 0, "a missing shard was tolerated:\n" + bad.stdout


def test_an_unreadable_record_fails_the_run(tmp_path):
    """Truncated or corrupt output is a failed host, never a quiet skip."""
    broken = tmp_path / "trunc.json"
    broken.write_text('{"shard": 1, "gates": [{"label": "gate c",', encoding="utf-8")
    bad = _run(_record(tmp_path, "t0", 0, [("gate a", "PASS"), ("gate b", "PASS")]),
               broken, "--expect", _expect(tmp_path), "--shards", 2)
    assert bad.returncode != 0, "a truncated record was tolerated:\n" + bad.stdout


def test_a_host_that_ran_UNSHARDED_fails_even_though_it_decided_everything(tmp_path):
    """The subtlest one, and the reason the `shard` key is checked at all.

    A host that ignored its plan and ran the whole suite decides every expected
    label — it looks like a complete, successful run. But its verdicts cover a
    different set than the plan assigned, and if it is aggregated as a shard the
    combined answer describes work nobody scheduled."""
    rec = tmp_path / "unsharded.json"
    rec.write_text(json.dumps({
        "seconds": 10,                       # no "shard" key
        "gates": [{"label": l, "state": "PASS"} for l in LABELS],
    }), encoding="utf-8")
    bad = _run(rec, "--expect", _expect(tmp_path), "--shards", 1)
    assert bad.returncode != 0, (
        "a host that ignored the plan passed because its numbers added up:\n" + bad.stdout)


def test_a_FAIL_in_any_shard_reaches_the_union(tmp_path):
    """The verdict itself: one shard's FAIL must not be averaged away."""
    bad = _run(_record(tmp_path, "f0", 0, [("gate a", "PASS"), ("gate b", "FAIL")]),
               _record(tmp_path, "f1", 1, [("gate c", "PASS")]),
               "--expect", _expect(tmp_path), "--shards", 2)
    assert bad.returncode != 0, "a shard's FAIL did not reach the union:\n" + bad.stdout
    assert "gate b" in bad.stdout, bad.stdout


def test_an_empty_expected_set_is_refused(tmp_path):
    """A run over nothing is not a pass — the denominator cannot come from the
    records, or a run that lost a shard would agree with itself."""
    empty = tmp_path / "empty.txt"
    empty.write_text("", encoding="utf-8")
    bad = _run(_record(tmp_path, "e0", 0, [("gate a", "PASS")]),
               "--expect", empty, "--shards", 1)
    assert bad.returncode != 0, "an empty denominator was accepted:\n" + bad.stdout


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
