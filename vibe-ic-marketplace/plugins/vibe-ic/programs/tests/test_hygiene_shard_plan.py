"""`hygiene_shard_plan` must partition by MEASURED time, and say what it cannot fix.

vibe-ic#1144. The program's own docstring states the trap it exists to avoid: an
even split BY COUNT hands one host the 2440s gate and everyone else ~230s, so the
critical path is unchanged and the sharding buys nothing. These tests assert the
properties it claims, each in both directions where a direction exists.

The program shipped with no tests; `plugin_full_audit` D1 caught it. Written from
the stated contract rather than the implementation, so they survive a rewrite.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROG = Path(__file__).resolve().parent.parent / "hygiene_shard_plan.py"


def _profile(tmp: Path, gates: dict) -> Path:
    p = tmp / "profile.json"
    p.write_text(json.dumps({"gates": [{"label": k, "seconds": v}
                                       for k, v in gates.items()]}), encoding="utf-8")
    return p


def _run(*args) -> subprocess.CompletedProcess:
    return _pr.run([sys.executable, str(PROG), *[str(a) for a in args]],
                          capture_output=True, text=True)


# One gate dominating the total is the real fleet's shape, not a corner case:
# `gates are host-independent` is 2440s of a measured 3747s.
DOMINATED = {"giant": 2000, "big": 500, "a": 20, "b": 15, "c": 10, "d": 5}


def test_the_dominant_gate_gets_a_shard_to_itself(tmp_path):
    """LPT puts the largest item alone first. If it shared a shard, the critical
    path would be longer than the item that cannot be split — pure waste."""
    r = _run("--profile", _profile(tmp_path, DOMINATED), "--shards", 4)
    assert r.returncode == 0, r.stdout + r.stderr
    s0 = _run("--profile", _profile(tmp_path, DOMINATED), "--shards", 4, "--shard", 0)
    assert s0.stdout.strip() == "giant", (
        "the dominant gate is not alone on its shard:\n" + s0.stdout)


def test_the_critical_path_cannot_go_below_the_largest_single_gate(tmp_path):
    """The honest ceiling, and the number a reader must not be allowed to miss.
    Adding shards past this point buys nothing, and the plan should say so rather
    than implying more hosts means more speed."""
    prof = _profile(tmp_path, DOMINATED)
    for shards in (2, 4, 8):
        r = _run("--profile", prof, "--shards", shards)
        assert r.returncode == 0, r.stdout
        assert "2000" in r.stdout, (
            f"with {shards} shards the plan does not state the 2000s floor:\n" + r.stdout)


def test_every_gate_is_assigned_exactly_once(tmp_path):
    """Neither dropped nor duplicated: a dropped gate is coverage lost silently,
    a duplicated one means two hosts mutate two trees and one is read."""
    prof = _profile(tmp_path, DOMINATED)
    seen = []
    for i in range(4):
        r = _run("--profile", prof, "--shards", 4, "--shard", i)
        assert r.returncode == 0, r.stdout
        seen += [l for l in r.stdout.splitlines() if l.strip()]
    assert sorted(seen) == sorted(DOMINATED), (
        f"assignment is not a partition: {sorted(seen)}")


def test_the_partition_is_deterministic(tmp_path):
    """Determinism is a correctness property here, not a convenience: two hosts
    handed different plans for the same input would each run a set the other did
    not, and the aggregate would describe neither."""
    prof = _profile(tmp_path, DOMINATED)
    a = _run("--profile", prof, "--shards", 3).stdout
    b = _run("--profile", prof, "--shards", 3).stdout
    assert a == b, "same input, two different plans"


def test_a_gate_absent_from_the_profile_is_REPORTED_not_silently_placed(tmp_path):
    """The docstring's own words: a new gate silently inheriting shard 0 would be
    the profile deciding coverage by omission. It must be visible."""
    prof = _profile(tmp_path, DOMINATED)
    labels = tmp_path / "labels.txt"
    labels.write_text("\n".join(list(DOMINATED) + ["brand_new_gate"]) + "\n",
                      encoding="utf-8")
    r = _run("--profile", prof, "--labels", labels, "--shards", 4)
    assert "brand_new_gate" in r.stdout, (
        "an unprofiled gate was placed without being named:\n" + r.stdout)


def test_it_refuses_a_missing_profile_rather_than_falling_back_to_a_count(tmp_path):
    """Refusing is the whole point: a count-based fallback is the failure mode the
    program was written to prevent, and it would look like success."""
    r = _run("--profile", tmp_path / "does_not_exist.json", "--shards", 4)
    assert r.returncode != 0, (
        "a missing profile was tolerated — a count-based split is exactly the "
        "silent no-op this program exists to refuse:\n" + r.stdout + r.stderr)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
