"""Tests for the GENERAL agentic-JSONL → Shape-D extractor.

The extractor MUST be benchmark-name-agnostic: it qualifies rows by schema
(id + prompt + harness-as-dict), not by hardcoded benchmark names. These
tests use synthetic JSONL rows with fictional IDs.
"""
import importlib
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]


def _load():
    if "agentic_jsonl_to_shape_d" in sys.modules:
        del sys.modules["agentic_jsonl_to_shape_d"]
    sys.path.insert(0, str(PROGRAMS))
    return importlib.import_module("agentic_jsonl_to_shape_d")


def _write_jsonl(path: Path, rows: list[dict]):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


# ── _is_agentic_row schema gate ──────────────────────────────────────────

def test_schema_gate_accepts_minimum_agentic_row():
    mod = _load()
    row = {"id": "x_001", "prompt": "p", "harness": {"src/t.py": "code"}}
    assert mod._is_agentic_row(row)


def test_schema_gate_rejects_missing_id():
    mod = _load()
    assert not mod._is_agentic_row({"prompt": "p", "harness": {"a": "b"}})


def test_schema_gate_rejects_empty_prompt():
    mod = _load()
    assert not mod._is_agentic_row({"id": "x", "prompt": "", "harness": {"a": "b"}})


def test_schema_gate_rejects_missing_harness():
    mod = _load()
    assert not mod._is_agentic_row({"id": "x", "prompt": "p"})


def test_schema_gate_rejects_empty_harness():
    mod = _load()
    assert not mod._is_agentic_row({"id": "x", "prompt": "p", "harness": {}})


def test_schema_gate_rejects_nonagentic_input_output_shape():
    """The nonagentic code-comprehension shape (input.prompt / output.response)
    must NOT qualify — that's a different task class."""
    mod = _load()
    row = {"id": "x", "input": {"prompt": "explain"},
           "output": {"response": "answer"}, "harness": {"a": "b"}}
    assert not mod._is_agentic_row(row)


# ── End-to-end extraction ────────────────────────────────────────────────

def test_extract_row_emits_shape_d_layout(tmp_path):
    """One agentic row → work/PROMPT.txt + work/<ctx-relpaths> + score/<harness>."""
    mod = _load()
    rundir = tmp_path / "run"
    row = {
        "id": "bench_x_problem_001",
        "categories": ["cat-a"],
        "system_message": "you are…",
        "prompt": "Design module foo",
        "context": {
            "docs/spec.md": "spec body",
            "verif/tb.sv": "tb body",
        },
        "harness": {
            "src/test_foo.py": "tcode",
            "src/test_runner.py": "rcode",
            "docker-compose.yml": "compose",
        },
    }
    proj = mod.extract_row(row, rundir)
    assert proj == rundir / "bench_x_problem_001"
    assert (proj / "work" / "PROMPT.txt").read_text() == "Design module foo"
    assert (proj / "work" / "SYSTEM_MESSAGE.txt").read_text() == "you are…"
    assert (proj / "work" / "docs" / "spec.md").read_text() == "spec body"
    assert (proj / "work" / "verif" / "tb.sv").read_text() == "tb body"
    assert (proj / "score" / "src" / "test_foo.py").read_text() == "tcode"
    assert (proj / "score" / "src" / "test_runner.py").read_text() == "rcode"
    assert (proj / "score" / "docker-compose.yml").read_text() == "compose"
    meta = json.loads((proj / ".row_meta.json").read_text())
    assert meta["id"] == "bench_x_problem_001"
    assert meta["categories"] == ["cat-a"]
    # Content keys MUST be stripped from meta (so meta is metadata-only)
    assert "prompt" not in meta
    assert "context" not in meta
    assert "harness" not in meta


def test_extract_dataset_dedupes_across_jsonl_files(tmp_path):
    """Same id in two JSONL files (e.g. with-solutions + without-solutions) →
    one entry in the deduped problems list."""
    mod = _load()
    dataset = tmp_path / "ds"; dataset.mkdir()
    rundir = tmp_path / "run"
    row = {"id": "shared_id_001", "prompt": "p",
           "harness": {"src/t.py": "c", "src/test_runner.py": "r"}}
    _write_jsonl(dataset / "split_a.jsonl", [row])
    _write_jsonl(dataset / "split_b.jsonl", [row])
    stats = mod.extract_dataset(dataset, rundir, "*.jsonl")
    assert stats["agentic_emitted"] == 1
    assert stats["ids"] == ["shared_id_001"]
    assert stats["rows_seen"] == 2


def test_extract_dataset_skips_nonagentic(tmp_path):
    """Mixed JSONL: agentic rows emit, nonagentic rows count but don't emit."""
    mod = _load()
    dataset = tmp_path / "ds"; dataset.mkdir()
    rundir = tmp_path / "run"
    agentic = {"id": "a_001", "prompt": "p", "harness": {"src/t.py": "c"}}
    nonagentic = {"id": "n_001", "input": {"prompt": "explain"},
                   "output": {"response": "x"}, "harness": {"f": {}}}
    _write_jsonl(dataset / "mixed.jsonl", [agentic, nonagentic])
    stats = mod.extract_dataset(dataset, rundir, "*.jsonl")
    assert stats["agentic_emitted"] == 1
    assert stats["non_agentic_skipped"] == 1
    assert (rundir / "a_001").exists()
    assert not (rundir / "n_001").exists()


def test_main_writes_bench_config_and_problems_list(tmp_path, monkeypatch):
    """Top-level manifests (problems.list + .bench_config.json) get emitted."""
    mod = _load()
    dataset = tmp_path / "ds"; dataset.mkdir()
    rundir = tmp_path / "run"
    _write_jsonl(dataset / "x.jsonl", [
        {"id": "p_001", "prompt": "p", "harness": {"src/t.py": "c"}},
    ])
    monkeypatch.setattr(sys, "argv", ["x", "--dataset", str(dataset),
                                       "--rundir", str(rundir)])
    assert mod.main() == 0
    pl = (rundir / "problems.list").read_text().splitlines()
    assert "p_001" in pl
    cfg = json.loads((rundir / ".bench_config.json").read_text())
    # Config MUST NOT name any specific benchmark — extractor is general
    assert cfg["extractor"] == "agentic_jsonl_to_shape_d.py"
    assert "bench" not in cfg, "extractor must not bake a bench name into its output"
    assert cfg["agentic_emitted"] == 1


def test_main_pattern_restricts_jsonl_set(tmp_path, monkeypatch):
    """--pattern selects which JSONL splits to read."""
    mod = _load()
    dataset = tmp_path / "ds"; dataset.mkdir()
    rundir = tmp_path / "run"
    _write_jsonl(dataset / "want.jsonl", [
        {"id": "yes_001", "prompt": "p", "harness": {"a": "b"}}])
    _write_jsonl(dataset / "skip.jsonl", [
        {"id": "no_001", "prompt": "p", "harness": {"a": "b"}}])
    monkeypatch.setattr(sys, "argv", ["x", "--dataset", str(dataset),
                                       "--rundir", str(rundir),
                                       "--pattern", "want*.jsonl"])
    assert mod.main() == 0
    ids = (rundir / "problems.list").read_text().splitlines()
    assert "yes_001" in ids
    assert "no_001" not in ids


# ── Anti-keyword regression: code must not name benchmarks ────────────────

def test_program_does_not_mention_any_benchmark_name():
    """Per memory 'enhancements must be general, not keyword': this extractor
    must NOT contain hardcoded benchmark names (cvdp, rtllm, verilogeval, ...)
    in its code path. Mentions in the module docstring (as examples of what
    benchmarks the schema applies to) are OK; logic branches are NOT."""
    src = (PROGRAMS / "agentic_jsonl_to_shape_d.py").read_text()
    # The module IS allowed to mention these in comments / docstrings (it
    # explains the schema). It must NOT branch on them in code:
    forbidden_branches = [
        'bench == "cvdp"', "bench == 'cvdp'",
        'bench == "rtllm"', "bench == 'rtllm'",
        'bench == "verilogeval"', "bench == 'verilogeval'",
    ]
    for s in forbidden_branches:
        assert s not in src, f"Found benchmark-name branch {s!r} in general extractor"
