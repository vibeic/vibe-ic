"""score_one.py — single-design official-harness scorer helper.

Tests the deterministic, docker-free surface: the CVDP result-semantics parser
(result==0 = PASS), the NO_DRAFT / NO_RESULT honesty paths, and main()'s setup
validation. The actual gate+cocotb run needs the OSS sim image and is exercised
by the convergence loop, not in CI.
"""
import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
HARNESS = PLUGIN / "benchmark"
sys.path.insert(0, str(HARNESS))
import score_one as S  # noqa: E402


def _raw(tmp_path, payload):
    p = tmp_path / "raw_result.json"
    p.write_text(json.dumps(payload))
    return p


def test_parse_result_pass(tmp_path):
    r = _raw(tmp_path, {"d": {"tests": [{"result": 0}, {"result": 0}]}})
    assert S.parse_result(r, "d") == ("PASS", [])


def test_parse_result_fail_returns_logs(tmp_path):
    r = _raw(tmp_path, {"d": {"tests": [
        {"result": 0, "log": "/x/0.txt"},
        {"result": 1, "log": "/x/1.txt"}]}})
    verdict, logs = S.parse_result(r, "d")
    assert verdict == "FAIL"
    assert logs == ["/x/1.txt"]


def test_parse_result_no_tests_is_no_result(tmp_path):
    r = _raw(tmp_path, {"d": {"tests": []}})
    assert S.parse_result(r, "d")[0] == "NO_RESULT"


def test_parse_result_string_zero_is_pass(tmp_path):
    # Step-2.7: the CVDP harness can record `result` as the string "0" (the
    # in-repo schema authority verify_fail_triage.py treats it as passing). Strict
    # `== 0` would FALSE-FAIL a genuinely-passing design and loop the re-author.
    r = _raw(tmp_path, {"d": {"tests": [{"result": "0"}, {"result": "0"}]}})
    assert S.parse_result(r, "d") == ("PASS", [])
    # a real fail mixed in still FAILs
    r2 = _raw(tmp_path, {"d": {"tests": [
        {"result": "0"}, {"result": 1, "log": "/x/1.txt"}]}})
    assert S.parse_result(r2, "d") == ("FAIL", ["/x/1.txt"])


def test_parse_result_wrong_shape_degrades_to_no_result(tmp_path):
    # Step-2.7: valid-JSON-but-wrong-shape raw_result.json (a crashed/partial
    # harness can write these) must degrade to NO_RESULT (could-not-score),
    # NEVER crash → exit 1 (mislabeled FAIL) and NEVER a fabricated PASS.
    for payload in (None, 42, "PASS", [{"d": 1}],
                    {"d": {"tests": {"result": 0}}},   # tests is a dict
                    {"d": {"tests": ["passed"]}}):      # a non-dict test entry
        r = _raw(tmp_path, payload)
        assert S.parse_result(r, "d")[0] == "NO_RESULT", payload


def test_parse_result_missing_id_is_no_result(tmp_path):
    r = _raw(tmp_path, {"other": {"tests": [{"result": 0}]}})
    assert S.parse_result(r, "d")[0] == "NO_RESULT"


def test_parse_result_missing_file_is_no_result(tmp_path):
    assert S.parse_result(tmp_path / "nope.json", "d")[0] == "NO_RESULT"


def test_score_one_no_draft(tmp_path):
    verdict, logs, detail = S.score_one(
        "d", tmp_path / "absent.sv", tmp_path / "ds.jsonl", tmp_path)
    assert verdict == "NO_DRAFT"


def test_main_missing_dataset_returns_2(tmp_path, capsys):
    draft = tmp_path / "d.sv"
    draft.write_text("module d; endmodule")
    rc = S.main(["--id", "d", "--draft", str(draft),
                 "--dataset", str(tmp_path / "absent.jsonl"),
                 "--bench", str(tmp_path)])
    assert rc == 2


def test_main_missing_run_benchmark_returns_2(tmp_path):
    draft = tmp_path / "d.sv"
    draft.write_text("module d; endmodule")
    ds = tmp_path / "ds.jsonl"
    ds.write_text(json.dumps({"id": "d", "input": {"prompt": "x"}}) + "\n")
    rc = S.main(["--id", "d", "--draft", str(draft),
                 "--dataset", str(ds), "--bench", str(tmp_path / "nobench")])
    assert rc == 2
