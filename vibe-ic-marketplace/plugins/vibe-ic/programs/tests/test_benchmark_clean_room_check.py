"""Tests for benchmark_clean_room_check.py (ORGANIC-20260604 clean-room guard).

Doctrine: every "run <benchmark>" is a clean-room full re-run — no inherited
samples / memory / prior storage (user directive 2026-06-04, binding,
supersedes the 2026-05-29 re-attempt-FAILing-set default).
"""
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import benchmark_clean_room_check as clr  # noqa: E402


def _mk_run(tmp_path, cfg=None):
    run = tmp_path / "run"
    (run / "samples").mkdir(parents=True)
    (run / "work").mkdir(parents=True)
    if cfg is not None:
        (run / ".bench_config.json").write_text(json.dumps(cfg))
    return run


def test_clean_room_empty_samples_passes(tmp_path):
    run = _mk_run(tmp_path, {"bench": "x", "clean_room": True,
                             "floor_only": False, "inherited_from": None,
                             "seed_run": None})
    verdict, findings = clr.audit(run)
    assert verdict == "PASS", findings
    assert findings == []


def test_freshly_authored_sample_passes(tmp_path):
    run = _mk_run(tmp_path, {"bench": "x", "clean_room": True})
    # authored AFTER the config marker → newer mtime → clean-room OK
    time.sleep(0.01)
    (run / "samples" / "Prob001.sv").write_text("module m; endmodule\n")
    verdict, findings = clr.audit(run)
    assert verdict == "PASS", findings


def test_seed_config_fails(tmp_path):
    run = _mk_run(tmp_path, {"bench": "x", "inherited_from": "../old_run"})
    verdict, findings = clr.audit(run)
    assert verdict == "FAIL"
    assert any(f.rule == "SEED_CONFIG" for f in findings)


def test_reused_samples_from_fails_even_floor_only(tmp_path):
    # Partial evaluation and inherited samples are independently forbidden.
    run = _mk_run(tmp_path, {"bench": "x", "floor_only": True,
                             "reused_samples_from": "../old_run/samples"})
    verdict, findings = clr.audit(run)
    assert verdict == "FAIL"
    assert any(f.rule == "SEED_CONFIG" for f in findings)


def test_floor_only_inherited_from_is_rejected(tmp_path):
    run = _mk_run(tmp_path, {"bench": "x", "floor_only": True,
                             "inherited_from": "../seed_run"})
    time.sleep(0.01)
    (run / "samples" / "Prob001.sv").write_text("module m; endmodule\n")
    verdict, findings = clr.audit(run)
    assert verdict == "FAIL"
    assert any(f.rule == "PARTIAL_DATASET" for f in findings)
    assert any(f.rule == "SEED_CONFIG" for f in findings)


def test_general_diagnostic_limit_is_not_a_canonical_run(tmp_path):
    run = _mk_run(tmp_path, {
        "schema": "vibeic.benchmark.general_run.v1",
        "bench": "x", "clean_room": True, "full_dataset": False,
    })
    verdict, findings = clr.audit(run)
    assert verdict == "FAIL"
    assert any(f.rule == "PARTIAL_DATASET" for f in findings)


def test_predated_sample_fails(tmp_path):
    run = _mk_run(tmp_path, {"bench": "x"})
    stale = run / "samples" / "Prob001.sv"
    stale.write_text("module m; endmodule\n")
    old = time.time() - 86400  # one day before the config marker
    os.utime(stale, (old, old))
    verdict, findings = clr.audit(run)
    assert verdict == "FAIL"
    assert any(f.rule == "PREDATED_SAMPLE" for f in findings)


def test_external_symlink_sample_fails(tmp_path):
    run = _mk_run(tmp_path, {"bench": "x"})
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "Prob001.sv"
    target.write_text("module m; endmodule\n")
    link = run / "samples" / "Prob001.sv"
    os.symlink(target, link)
    verdict, findings = clr.audit(run)
    assert verdict == "FAIL"
    assert any(f.rule == "EXTERNAL_SYMLINK" for f in findings)


def test_prior_score_read_in_log_fails(tmp_path):
    run = _mk_run(tmp_path, {"bench": "x"})
    (run / "harness.log").write_text(
        "loading previous results from ../old/pass_at_1.json to decide what to author\n")
    verdict, findings = clr.audit(run)
    assert verdict == "FAIL"
    assert any(f.rule == "PRIOR_SCORE_READ" for f in findings)


def test_cli_exit_codes(tmp_path, capsys):
    run = _mk_run(tmp_path, {"bench": "x", "clean_room": True})
    assert clr.main([str(run)]) == 0
    bad = _mk_run(tmp_path / "b", {"bench": "x", "seed_run": "old"})
    assert clr.main([str(bad)]) == 1
    assert clr.main([str(tmp_path / "does_not_exist")]) == 2
