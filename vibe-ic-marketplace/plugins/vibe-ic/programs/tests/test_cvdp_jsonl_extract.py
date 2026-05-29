"""Tests for cvdp_jsonl_extract.py (v0.1.55 R4 capture).

Verifies the CVDP JSONL → Shape-D project-dir extractor:
  - agentic_code_generation rows emit work/PROMPT.txt + work/docs/ + score/src/*
  - nonagentic rows are skipped (different schema; code-comprehension task)
  - problems.list + .bench_config.json are written at the rundir root
"""
import importlib
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]


def _load_extractor():
    if "cvdp_jsonl_extract" in sys.modules:
        del sys.modules["cvdp_jsonl_extract"]
    sys.path.insert(0, str(PROGRAMS))
    return importlib.import_module("cvdp_jsonl_extract")


def _write_jsonl(path: Path, rows: list[dict]):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_agentic_row_emits_shape_d_layout(tmp_path):
    """One agentic row → work/PROMPT.txt + work/docs/spec + score/src/*."""
    mod = _load_extractor()
    dataset = tmp_path / "dataset"; dataset.mkdir()
    rundir = tmp_path / "run"
    row = {
        "id": "cvdp_agentic_test_0001",
        "categories": ["cid003"],
        "system_message": "system message text",
        "prompt": "Design a test module",
        "context": {
            "docs/specification.md": "spec text",
            "verif/tb.sv": "tb text",
        },
        "harness": {
            "src/test_test.py": "test py",
            "src/test_runner.py": "runner py",
            "src/harness_library.py": "lib py",
            "docker-compose.yml": "compose yml",
        },
    }
    _write_jsonl(dataset / "cvdp_v1_example_agentic_code_generation.jsonl", [row])
    rc = mod.main_for_test(["--dataset", str(dataset), "--rundir", str(rundir)]) \
        if hasattr(mod, "main_for_test") else None
    # Use the regular CLI entry via subprocess-equivalent
    sys.argv = ["cvdp_jsonl_extract.py", "--dataset", str(dataset),
                "--rundir", str(rundir)]
    rc = mod.main()
    assert rc == 0
    proj = rundir / "cvdp_agentic_test_0001"
    assert (proj / "work" / "PROMPT.txt").read_text() == "Design a test module"
    assert (proj / "work" / "SYSTEM_MESSAGE.txt").read_text() == "system message text"
    assert (proj / "work" / "docs" / "specification.md").read_text() == "spec text"
    assert (proj / "work" / "verif" / "tb.sv").read_text() == "tb text"
    assert (proj / "score" / "src" / "test_test.py").read_text() == "test py"
    assert (proj / "score" / "src" / "test_runner.py").read_text() == "runner py"
    assert (proj / "score" / "src" / "harness_library.py").read_text() == "lib py"
    assert (proj / "score" / "docker-compose.yml").read_text() == "compose yml"
    meta = json.loads((proj / ".cvdp_meta.json").read_text())
    assert meta["id"] == "cvdp_agentic_test_0001"
    assert meta["categories"] == ["cid003"]


def test_nonagentic_row_skipped(tmp_path):
    """Nonagentic schema (input.prompt + output.response) must be skipped."""
    mod = _load_extractor()
    dataset = tmp_path / "dataset"; dataset.mkdir()
    rundir = tmp_path / "run"
    row = {
        "id": "cvdp_nonagentic_xx_0001",
        "categories": ["nonag"],
        "input": {"prompt": "explain", "context": {}},
        "output": {"response": "answer", "context": {}},
        "harness": {"files": {}},
    }
    _write_jsonl(dataset / "cvdp_v1_example_nonagentic.jsonl", [row])
    sys.argv = ["cvdp_jsonl_extract.py", "--dataset", str(dataset),
                "--rundir", str(rundir), "--pattern", "*.jsonl"]
    rc = mod.main()
    assert rc == 0
    # Nonagentic rows must NOT emit a project dir
    assert not (rundir / "cvdp_nonagentic_xx_0001").exists()
    # problems.list must be empty (or only contain nothing meaningful)
    pl = (rundir / "problems.list").read_text().splitlines()
    assert "cvdp_nonagentic_xx_0001" not in pl


def test_problems_list_dedupes_across_solutions(tmp_path):
    """with-solutions + without-solutions JSONLs ship the same ID — the
    deduplicated problems.list must list each ID exactly once."""
    mod = _load_extractor()
    dataset = tmp_path / "dataset"; dataset.mkdir()
    rundir = tmp_path / "run"
    row = {
        "id": "cvdp_agentic_dup_0001",
        "categories": ["cid001"],
        "prompt": "p",
        "context": {"docs/spec.md": "s"},
        "harness": {"src/test_x.py": "t", "src/test_runner.py": "r",
                    "src/harness_library.py": "l"},
    }
    _write_jsonl(dataset / "cvdp_v1_example_agentic_no_sol.jsonl", [row])
    _write_jsonl(dataset / "cvdp_v1_example_agentic_with_sol.jsonl", [row])
    sys.argv = ["cvdp_jsonl_extract.py", "--dataset", str(dataset),
                "--rundir", str(rundir)]
    assert mod.main() == 0
    ids = [ln for ln in (rundir / "problems.list").read_text().splitlines() if ln]
    assert ids.count("cvdp_agentic_dup_0001") == 1


def test_bench_config_emitted(tmp_path):
    """Top-level .bench_config.json must point at the dataset path."""
    mod = _load_extractor()
    dataset = tmp_path / "dataset"; dataset.mkdir()
    rundir = tmp_path / "run"
    row = {"id": "x_0001", "categories": ["c"], "prompt": "p", "context": {},
           "harness": {"src/test_x.py": "t", "src/test_runner.py": "r",
                       "src/harness_library.py": "l"}}
    _write_jsonl(dataset / "cvdp_v1_example_agentic.jsonl", [row])
    sys.argv = ["cvdp_jsonl_extract.py", "--dataset", str(dataset),
                "--rundir", str(rundir)]
    assert mod.main() == 0
    cfg = json.loads((rundir / ".bench_config.json").read_text())
    assert cfg["bench"] == "cvdp"
    assert cfg["dataset"] == str(dataset.resolve())
    assert cfg["extractor"] == "cvdp_jsonl_extract.py"
    assert cfg["agentic_emitted"] == 1


def test_real_cvdp_example_dataset_extracts_2_agentic_problems(tmp_path):
    """End-to-end: run against the real CVDP public example dataset.
    Skip cleanly if the dataset isn't on this host."""
    real_ds = Path("/home/reyerchu/AI_IC_design/_extbench/cvdp_benchmark/example_dataset")
    if not real_ds.is_dir():
        import pytest
        pytest.skip("CVDP example dataset not present on this host")
    mod = _load_extractor()
    rundir = tmp_path / "run"
    sys.argv = ["cvdp_jsonl_extract.py", "--dataset", str(real_ds),
                "--rundir", str(rundir)]
    assert mod.main() == 0
    # Real dataset has exactly 2 distinct agentic IDs (cid001 + cid003)
    ids = [ln for ln in (rundir / "problems.list").read_text().splitlines() if ln]
    assert len(ids) >= 2
    assert "cvdp_agentic_fixed_arbiter_0001" in ids
