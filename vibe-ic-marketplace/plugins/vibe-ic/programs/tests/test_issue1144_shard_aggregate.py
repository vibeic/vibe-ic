"""vibe-ic#1144 step 4 — the aggregator, and the ways a sharded run can lie.

THE TWO-ARM THIS FILE IS BUILT AROUND
=====================================
The brief's requirement is that **a sharded run and a full serial run produce
the same verdict on the same tree**, proven on a tree that PASSES and on a tree
that FAILS — "a sharded gate that cannot redden is worse than the slow one".

That equivalence is a property of the RECORDS, not of the 57-minute run, so it
is proven here deterministically: take one serial record, partition its gates
into shards, and require the aggregate verdict to equal the serial verdict.
Both directions, so a partition cannot pass by being unable to fail.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

import pytest

_ROOT = Path(__file__).resolve().parents[5]
_AGG = _ROOT / "tools" / "ci" / "shard_aggregate.py"

RC_OK, RC_NOT_CLEAN, RC_UNESTABLISHED = 0, 1, 2


def _gate(label: str, state: str) -> Dict:
    return {"label": label, "state": state, "seconds": 1}


def _doc(gates: List[Dict], listed_only: bool = False, **extra) -> Dict:
    d = {"listed_only": listed_only, "declared": len(gates), "gates": gates}
    d.update(extra)
    return d


def _write(p: Path, doc: Dict) -> Path:
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(_AGG), *args],
                          capture_output=True, text=True, timeout=60)


@pytest.fixture
def roster(tmp_path: Path) -> Path:
    return _write(tmp_path / "roster.json",
                  _doc([_gate(f"gate{i}", "LISTED") for i in range(6)],
                       listed_only=True))


def _shards(tmp_path: Path, *groups: List[Dict]) -> List[str]:
    out = []
    for i, g in enumerate(groups):
        p = _write(tmp_path / f"shard{i}.json", _doc(g))
        out += ["--shard", str(p)]
    return out


# --- the happy path, and its denominator ---------------------------------
def test_a_complete_partition_passes_and_states_its_denominator(tmp_path, roster):
    got = _run("--roster", str(roster),
               *_shards(tmp_path,
                        [_gate(f"gate{i}", "PASS") for i in range(3)],
                        [_gate(f"gate{i}", "PASS") for i in range(3, 6)]))
    assert got.returncode == RC_OK, got.stdout + got.stderr
    assert "6 of 6 gate(s) ran across 2 shard(s)" in got.stdout, got.stdout
    assert "0 NOT CHECKED" in got.stdout, got.stdout


# --- THE TWO-ARM: sharded verdict == serial verdict, both directions ------
@pytest.mark.parametrize("states,expect", [
    (["PASS"] * 6, RC_OK),
    (["PASS", "PASS", "FAIL", "PASS", "PASS", "PASS"], RC_NOT_CLEAN),
    (["PASS", "NOT_CHECKED", "PASS", "PASS", "PASS", "PASS"], RC_NOT_CLEAN),
    (["PASS", "PASS", "PASS", "WROTE_CORPUS", "PASS", "PASS"], RC_NOT_CLEAN),
])
def test_the_sharded_verdict_equals_the_serial_verdict(tmp_path, roster,
                                                       states, expect):
    """Same gates, same states — once as one record, once split in two."""
    gates = [_gate(f"gate{i}", s) for i, s in enumerate(states)]

    serial = _write(tmp_path / "serial.json", _doc(gates))
    got_serial = _run("--roster", str(roster), "--shard", str(serial))

    got_sharded = _run("--roster", str(roster),
                       *_shards(tmp_path, gates[:3], gates[3:]))

    assert got_serial.returncode == expect, got_serial.stdout + got_serial.stderr
    assert got_sharded.returncode == got_serial.returncode, (
        f"sharded {got_sharded.returncode} != serial {got_serial.returncode}\n"
        f"{got_sharded.stdout}{got_sharded.stderr}")


# --- a dead shard must FAIL the run, never shrink the population ----------
def test_a_missing_shard_file_is_unestablished_not_a_smaller_pass(tmp_path, roster):
    got = _run("--roster", str(roster),
               "--shard", str(tmp_path / "never-written.json"))
    assert got.returncode == RC_UNESTABLISHED, got.stdout + got.stderr
    assert "does not exist" in got.stderr, got.stderr
    assert "NOT a pass" in got.stderr, got.stderr


def test_a_truncated_shard_record_is_unestablished(tmp_path, roster):
    bad = tmp_path / "half.json"
    bad.write_text('{"gates": [{"label": "gate0",', encoding="utf-8")
    got = _run("--roster", str(roster), "--shard", str(bad))
    assert got.returncode == RC_UNESTABLISHED, got.stdout + got.stderr


def test_a_shard_that_reported_nothing_leaves_its_gates_unclaimed(tmp_path, roster):
    """The headline case: five of six gates reported, and the run must NOT
    say '5 of 5 passed'."""
    got = _run("--roster", str(roster),
               *_shards(tmp_path, [_gate(f"gate{i}", "PASS") for i in range(5)]))
    assert got.returncode == RC_UNESTABLISHED, got.stdout + got.stderr
    assert "claimed by NO shard" in got.stderr, got.stderr
    assert "gate5" in got.stderr, got.stderr


def test_expect_shards_catches_a_host_that_was_never_asked(tmp_path, roster):
    d = tmp_path / "sh"
    d.mkdir()
    _write(d / "a.json", _doc([_gate(f"gate{i}", "PASS") for i in range(6)]))
    got = _run("--roster", str(roster), "--shards-dir", str(d),
               "--expect-shards", "2")
    assert got.returncode == RC_UNESTABLISHED, got.stdout + got.stderr
    assert "expected 2 shard record(s), found 1" in got.stderr, got.stderr


def test_a_shards_dir_without_an_expected_count_is_refused(tmp_path, roster):
    d = tmp_path / "sh"
    d.mkdir()
    _write(d / "a.json", _doc([_gate(f"gate{i}", "PASS") for i in range(6)]))
    got = _run("--roster", str(roster), "--shards-dir", str(d))
    assert got.returncode == RC_UNESTABLISHED, got.stdout + got.stderr
    assert "would aggregate whatever happens to be on disk" in got.stderr


# --- a broken split must not satisfy the arithmetic ----------------------
def test_a_gate_claimed_by_two_shards_fails_even_though_the_count_reaches_six(
        tmp_path, roster):
    """gate0 twice and gate5 never still totals six claims. Accepting that
    would let a broken partition satisfy the denominator."""
    got = _run("--roster", str(roster),
               *_shards(tmp_path,
                        [_gate(f"gate{i}", "PASS") for i in range(3)],
                        [_gate("gate0", "PASS"), _gate("gate3", "PASS"),
                         _gate("gate4", "PASS")]))
    assert got.returncode == RC_UNESTABLISHED, got.stdout + got.stderr
    assert "MORE THAN ONE" in got.stderr, got.stderr


def test_a_label_the_roster_does_not_know_fails(tmp_path, roster):
    got = _run("--roster", str(roster),
               *_shards(tmp_path,
                        [_gate(f"gate{i}", "PASS") for i in range(6)],
                        [_gate("a gate from another tree", "PASS")]))
    assert got.returncode == RC_UNESTABLISHED, got.stdout + got.stderr
    assert "not in the roster" in got.stderr, got.stderr


def test_a_list_record_is_not_accepted_as_a_run(tmp_path, roster):
    """A `--list` record declares every gate and executes none. Aggregating it
    would report full coverage over a run that never happened."""
    listed = _write(tmp_path / "listed.json",
                    _doc([_gate(f"gate{i}", "LISTED") for i in range(6)],
                         listed_only=True))
    got = _run("--roster", str(roster), "--shard", str(listed))
    assert got.returncode == RC_UNESTABLISHED, got.stdout + got.stderr
    assert "listed_only" in got.stderr, got.stderr


def test_an_empty_roster_is_refused_rather_than_trivially_satisfied(tmp_path):
    empty = _write(tmp_path / "roster.json", _doc([], listed_only=True))
    shard = _write(tmp_path / "s.json", _doc([]))
    got = _run("--roster", str(empty), "--shard", str(shard))
    assert got.returncode == RC_UNESTABLISHED, got.stdout + got.stderr
    assert "empty roster" in got.stderr, got.stderr


# --- loop denominators survive aggregation (vibe-ic#957) -----------------
def test_a_loop_corpus_that_expanded_to_zero_is_still_reported(tmp_path, roster):
    p = _write(tmp_path / "s.json",
               _doc([_gate(f"gate{i}", "PASS") for i in range(6)],
                    corpora=[{"name": "published cells", "items": 0,
                              "gates": 0, "expansion": "EXPANDED"}]))
    got = _run("--roster", str(roster), "--shard", str(p))
    assert got.returncode == RC_OK, got.stdout + got.stderr
    assert "expanded over 0 item(s)" in got.stdout, got.stdout
    assert "NOTHING was checked over it" in got.stdout, got.stdout


def test_the_real_roster_is_produced_by_the_script_it_shards():
    """The roster is not a hand-written list. If `--list` ever stops emitting a
    summary the aggregator's denominator has no source, and that must be a
    visible failure rather than an empty set."""
    script = _ROOT / "tools" / "ci" / "repo_hygiene_gates.sh"
    if not script.is_file():
        pytest.skip("CI script not present")
    assert "--list" in script.read_text(encoding="utf-8")
    assert "--summary-json" in (_ROOT / "tools" / "ci" / "_gate_dispatch.sh"
                                ).read_text(encoding="utf-8")
