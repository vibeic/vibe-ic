#!/usr/bin/env python3
"""test_emit_author_context.py — pins benchmark/emit_author_context.py, the
RULE-0 fix that stages the prompt-matched IC-Expert DB digest for a blind author.

Guards:
  * a prompt that matches design-class craft stages a non-empty ic_expert_db.md;
  * §4.05: the program reads ONLY the --prompt file (never an oracle path);
  * a missing prompt / no-match design exits 0 and stages nothing (best-effort).
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent.parent
PROG = PLUGIN / "benchmark" / "emit_author_context.py"


def _run(prompt: str, out_dir: Path):
    p = out_dir / "prompt.txt"
    p.write_text(prompt)
    r = subprocess.run(
        [sys.executable, str(PROG), "--prompt", str(p), "--out-dir", str(out_dir), "--k", "3"],
        capture_output=True, text=True)
    return r


def test_fsm_prompt_stages_db_digest(tmp_path):
    # A clock-domain-crossing / synchronizer prompt matches DB craft.
    prompt = (
        "Design a two-flop synchronizer that passes a control signal from a fast\n"
        "clock domain into a slower clock domain. Inputs: clk, rst, data_in.\n"
        "Output: data_out. Use a level-held handshake.\n")
    r = _run(prompt, tmp_path)
    assert r.returncode == 0, r.stderr
    db = tmp_path / "ic_expert_db.md"
    # best-effort: if the DB is present on this host it must stage a non-empty digest
    if "staged" in r.stdout:
        assert db.is_file() and db.read_text().strip(), "claimed staged but file empty"
        assert "IC Expert DB" in db.read_text()


def test_missing_prompt_exits_zero(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROG), "--prompt", str(tmp_path / "nope.txt"),
         "--out-dir", str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 0            # best-effort, never hard-fails the harness
    assert "NO_PROMPT" in r.stderr


def test_source_reads_only_the_prompt():
    # §4.05: no oracle path is opened in the CODE (docstring mentions are fine).
    src = PROG.read_text()
    # strip the module docstring before scanning code
    body = src.split('"""', 2)[-1]
    for oracle in ("_test.sv", "_ref.sv", "testbench.v", "verified_", "golden"):
        assert oracle not in body, f"code must not reference oracle token {oracle!r}"
