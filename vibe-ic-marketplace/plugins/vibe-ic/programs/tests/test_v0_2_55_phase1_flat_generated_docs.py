"""v0.2.55 phase1 prompt-mode flat generated_docs regressions.

Pins the #424 fix (ORGANIC-20260606-phase1-prompt-mode-nested-generated-docs):
the one-shot runner passes the CANONICAL generated-docs dir
(<project>/phase1/generated_docs) as the engine's out dir, but the engine's
`run-all` re-joined the basename (`out_dir / "generated_docs"`) — layer docs
landed one level too deep (generated_docs/generated_docs/), phase2's
precheck saw 0/13, and the spec-to-rtl handoff never fired on ANY
prompt-mode design. Fix: the engine resolves the docs dir ONCE — when the
out dir already IS a generated_docs dir it writes flat into it (human docs
at the canonical sibling); a plain work root keeps the
<out>/generated_docs contract the Shape-C gates depend on. phase2's
precheck additionally names the nested path explicitly when it finds one
(pre-fix artefacts).

chip-AGNOSTIC: fixtures use a generic clock-divider prompt only.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"

# repo root that carries tools/phase1_engine (walk up from the plugin)
_ENGINE = None
for anc in (PLUGIN, *PLUGIN.parents):
    cand = anc / "tools" / "phase1_engine" / "cli.py"
    if cand.is_file():
        _ENGINE = cand
        break

import pytest  # noqa: E402

pytestmark = pytest.mark.skipif(
    _ENGINE is None, reason="tools/phase1_engine not present in this checkout")

_PROMPT = ("Build a module named pulse_div with the following interface.\n"
           " - input  clk\n - input  rst_n\n - output tick\n"
           "The module divides the input clock by 10: assert tick for one\n"
           "cycle every 10 clk cycles. Reset is asynchronous and active low.\n")


def _run_engine(src: Path, out_dir: Path):
    pkg_parent = _ENGINE.parent.parent          # .../tools
    repo_root = pkg_parent.parent               # repo root (has vibe-ic-marketplace/)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(pkg_parent) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "phase1_engine.cli", "run-all",
         str(src), str(out_dir), "--ic-name", "pulse_div"],
        capture_output=True, text=True, timeout=60,
        cwd=str(repo_root), env=env)


def _mk_docs(tmp_path: Path) -> Path:
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "design_description.md").write_text(_PROMPT)
    return docs


# ── engine: canonical generated_docs out dir → FLAT emit ──────────────────

def test_engine_writes_flat_into_canonical_generated_docs(tmp_path):
    docs = _mk_docs(tmp_path)
    out = tmp_path / "phase1" / "generated_docs"
    r = _run_engine(docs, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert list(out.glob("L*.json")), "L docs must land FLAT in the out dir"
    assert not (out / "generated_docs").exists(), \
        "no nested generated_docs/generated_docs"
    # human docs at the canonical SIBLING, not inside generated_docs
    assert (out.parent / "human_docs").is_dir()


def test_engine_work_root_contract_unchanged(tmp_path):
    # the Shape-C gates contract: a plain work root keeps <out>/generated_docs
    docs = _mk_docs(tmp_path)
    out = tmp_path / "wd" / "out"
    r = _run_engine(docs, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert list((out / "generated_docs").glob("L*.json"))
    assert (out / "human_docs").is_dir()


# ── one-shot runner integration: prompt-mode project end-to-end ───────────

def test_runner_prompt_mode_emits_flat_and_precheck_passes(tmp_path):
    proj = tmp_path / "proj"
    (proj / "input").mkdir(parents=True)
    (proj / "input" / "phase1_prompt.md").write_text(_PROMPT)
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "phase1_one_shot_runner.py"),
         str(proj), "--ic-name", "pulse_div"],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    gd = proj / "phase1" / "generated_docs"
    n = len(list(gd.glob("L*.json")))
    assert n >= 13, f"expected >=13 flat L docs, got {n}"
    assert not (gd / "generated_docs").exists(), \
        "no nested generated_docs/generated_docs"
    # phase2's precheck must count them (dry-run stops after the plan print)
    r2 = subprocess.run(
        [sys.executable, str(PROGRAMS / "design_one_shot_runner.py"),
         str(proj), "--dry-run"],
        capture_output=True, text=True, timeout=60)
    assert f"{n}/13 L docs present" in r2.stdout, r2.stdout + r2.stderr


# ── phase2 precheck names the nested layout on pre-fix artefacts ──────────

def test_precheck_names_nested_path_explicitly(tmp_path):
    proj = tmp_path / "nestproj"
    nested = proj / "phase1" / "generated_docs" / "generated_docs"
    nested.mkdir(parents=True)
    for i in (1, 2, 3):
        (nested / f"L{i}_X.json").write_text("{}")
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "design_one_shot_runner.py"),
         str(proj)],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 1
    rpt = json.loads(
        (proj / "reports" / "orchestrator" / "phase2_one_shot.json").read_text())
    pc = [s for s in rpt["steps"] if s["name"] == "phase1_precheck"][0]
    assert pc["status"] == "FAIL"
    assert "NESTED" in pc["detail"]
    assert str(nested) in pc["detail"]
