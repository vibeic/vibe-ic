#!/usr/bin/env python3
"""test_score_one_dataset_subset.py — score_one's single-problem dataset subset.

The fix: score_one passes a ONE-RECORD dataset to `run_benchmark.py -f` instead of
the full 302-problem dataset (the full file made the official harness assemble every
design → ~7 min/call, 420s TIMEOUT false-FAILs). extract_one_record pulls exactly the
requested record, with an exact JSON `id` match so a substring collision never selects
the wrong one.
"""
import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
HARNESS = PLUGIN / "benchmark"
sys.path.insert(0, str(HARNESS))
import score_one as S  # noqa: E402


def _write_ds(tmp_path, ids):
    ds = tmp_path / "dataset.jsonl"
    with ds.open("w") as fh:
        for i in ids:
            fh.write(json.dumps({"id": i, "input": {"prompt": f"p_{i}"}}) + "\n")
    return ds


def test_extract_returns_exact_record(tmp_path):
    ds = _write_ds(tmp_path, ["cvdp_copilot_gcd_0003",
                              "cvdp_copilot_cache_lru_0001",
                              "cvdp_copilot_scrambler_0009"])
    line = S.extract_one_record(ds, "cvdp_copilot_cache_lru_0001")
    assert line is not None
    assert json.loads(line)["id"] == "cvdp_copilot_cache_lru_0001"


def test_substring_collision_not_selected(tmp_path):
    # `_0001` must NOT match `_00010`; the exact JSON-id check guards this.
    ds = _write_ds(tmp_path, ["cvdp_copilot_x_00010", "cvdp_copilot_x_0001"])
    assert json.loads(S.extract_one_record(ds, "cvdp_copilot_x_0001"))["id"] == \
        "cvdp_copilot_x_0001"
    assert json.loads(S.extract_one_record(ds, "cvdp_copilot_x_00010"))["id"] == \
        "cvdp_copilot_x_00010"


def test_absent_id_returns_none(tmp_path):
    ds = _write_ds(tmp_path, ["cvdp_copilot_gcd_0003"])
    assert S.extract_one_record(ds, "cvdp_copilot_not_here_0001") is None


def test_subset_is_single_record(tmp_path):
    # What run_benchmark -f receives must be exactly the one requested record.
    ds = _write_ds(tmp_path, [f"cvdp_copilot_fam_{n:04d}" for n in range(1, 51)])
    line = S.extract_one_record(ds, "cvdp_copilot_fam_0027")
    assert line is not None and json.loads(line)["id"] == "cvdp_copilot_fam_0027"
    assert "\n" not in line
