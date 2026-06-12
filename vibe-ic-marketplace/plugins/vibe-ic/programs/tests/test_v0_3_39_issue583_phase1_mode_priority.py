"""ORGANIC #583 — two halves:

(a) the orchestrator's `_phase1_decision` picked NL-prompt mode even when
    a full vendor docs/ tree was staged alongside input/phase1_prompt.md
    (the prompt is a SUMMARY, not the richer source) — L9 extraction then
    collapsed to a glossary term with 6 width-less pins;
(b) the NL-mode path dropped the forwarded --ic-name: phase1_engine's
    run-all never created an L1.ic_name fact for a prompt-bridged docs/
    (no L*.json to reverse-extract), so L1 rendered without the explicit
    name the orchestrator forwarded (the #541 override only existed in
    the docs-mode runner).

Fixes: docs-populated outranks the prompt file in `_phase1_decision`
(structured YAML still wins — a deliberately-authored fact graph);
`run-all` force-upserts graph.ic_name + the L1.ic_name fact when
--ic-name is given (CLI > docs per #541).
"""
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import vibe_ic_one_shot_runner as ORCH  # noqa: E402

ENGINE_PARENT = PROG.parent / "tools"


# ── (a) mode decision priority ──────────────────────────────────────────────

def _stage(tmp_path, *, prompt=False, docs=False, struct=False,
           input_doc=False):
    inp = tmp_path / "input"
    inp.mkdir(parents=True, exist_ok=True)
    if prompt:
        (inp / "phase1_prompt.md").write_text("# my chip\nA crypto block.\n")
    if struct:
        (inp / "phase1_structured.yaml").write_text("ic_name: x\n")
    if docs:
        d = inp / "docs"
        d.mkdir(exist_ok=True)
        (d / "datasheet.md").write_text("# Vendor datasheet\n47 ports.\n")
    if input_doc:
        d = tmp_path / "phase1" / "input_doc"
        d.mkdir(parents=True, exist_ok=True)
        (d / "corpus.txt").write_text("vendor corpus\n")
    return tmp_path


def test_docs_outrank_prompt(tmp_path):
    """The issue's exact shape: BOTH phase1_prompt.md and a populated
    docs/ tree staged → docs mode must win."""
    proj = _stage(tmp_path, prompt=True, docs=True)
    run, mode = ORCH._phase1_decision(proj, force_skip=False)
    assert run is True
    assert mode == "docs"


def test_input_doc_corpus_outranks_prompt(tmp_path):
    proj = _stage(tmp_path, prompt=True, input_doc=True)
    run, mode = ORCH._phase1_decision(proj, force_skip=False)
    assert (run, mode) == (True, "docs")


def test_prompt_only_still_prompt_mode(tmp_path):
    proj = _stage(tmp_path, prompt=True)
    run, mode = ORCH._phase1_decision(proj, force_skip=False)
    assert (run, mode) == (True, "prompt")


def test_structured_yaml_still_wins_over_docs(tmp_path):
    """A deliberately-authored structured fact graph is the strongest
    Path-A signal — docs do not displace it (regression guard)."""
    proj = _stage(tmp_path, struct=True, docs=True)
    run, mode = ORCH._phase1_decision(proj, force_skip=False)
    assert (run, mode) == (True, "prompt")


def test_docs_only_still_docs_mode(tmp_path):
    proj = _stage(tmp_path, docs=True)
    run, mode = ORCH._phase1_decision(proj, force_skip=False)
    assert (run, mode) == (True, "docs")


def test_no_inputs_no_run(tmp_path):
    run, mode = ORCH._phase1_decision(tmp_path, force_skip=False)
    assert (run, mode) == (False, "")


def test_gitkeep_only_docs_does_not_displace_prompt(tmp_path):
    """Adversarial guard: an empty docs/ holding only a .gitkeep
    placeholder must NOT flip a prompt-only project into docs mode."""
    proj = _stage(tmp_path, prompt=True)
    d = proj / "input" / "docs"
    d.mkdir()
    (d / ".gitkeep").write_text("")
    run, mode = ORCH._phase1_decision(proj, force_skip=False)
    assert (run, mode) == (True, "prompt")


# ── (b) run-all honors --ic-name (the NL/prompt-bridged path) ───────────────

def test_run_all_honors_ic_name_end_state(tmp_path):
    """End-state via the real engine CLI: a prompt-bridged docs/ (no
    L*.json inside) + --ic-name must render L1_DATASHEET.json carrying
    the explicit name (pre-fix: no L1.ic_name fact was ever created)."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "design_description.md").write_text(
        "# my crypto block\nIt accelerates a cipher.\n")
    out = tmp_path / "out"
    result = subprocess.run(
        [sys.executable, "-m", "phase1_engine.cli", "run-all",
         str(docs), str(out), "--ic-name", "crypto_periph",
         "--allow-underspec"],
        capture_output=True, text=True, timeout=300,
        cwd=str(ENGINE_PARENT.parent.parent.parent.parent),
        env={**__import__("os").environ,
             "PYTHONPATH": str(ENGINE_PARENT)},
    )
    assert result.returncode == 0, result.stderr[-2000:]
    l1 = out / "generated_docs" / "L1_DATASHEET.json"
    assert l1.is_file(), sorted(p.name for p in out.iterdir())
    import json
    data = json.loads(l1.read_text())
    assert data.get("ic_name") == "crypto_periph", data
