"""vibe-ic#693 — a gate no automatic verdict consults.

The gate under test answers a question nothing in the repo was asking. These
tests drive its REAL entry point over a synthetic tree, so a wiring defect
inside `main` cannot hide behind green unit tests of the helpers.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(PROGRAMS))

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


def _tree(root: Path, *, gates=(), flow_names=(), flow_declared=(),
          skill_names=(), ci_names=()):
    """A minimal plugin+repo: `gates` exist, the others name some of them.

    TWO FLOW SHAPES, because the difference between them is the whole rule
    (vibe-ic#2065). `flow_names` writes a real GATE CLAUSE — a command whose
    entry is the gate — and is an invocation. `flow_declared` writes a
    `programs:` list entry, which is a DECLARATION and runs nothing.
    """
    (root / "programs").mkdir(parents=True, exist_ok=True)
    for g in gates:
        (root / "programs" / f"{g}.py").write_text("# a gate\n")
    (root / "flow").mkdir(exist_ok=True)
    steps = []
    for n in flow_names:
        steps.append(
            f"  - id: s_{n}\n"
            f"    gate:\n"
            f"      all_of:\n"
            f'        - program_exit_zero: "{n} . --json reports/{n}.json"\n')
    for n in flow_declared:
        steps.append(f"  - id: d_{n}\n"
                     f"    programs:\n"
                     f"      - {n}\n")
    (root / "flow" / "phase1_phase2_phase3.yaml").write_text(
        ("steps:\n" + "".join(steps)) if steps else "steps: []\n")
    (root / "skills" / "s").mkdir(parents=True, exist_ok=True)
    (root / "skills" / "s" / "SKILL.md").write_text(
        "".join(f"run `{n}.py`\n" for n in skill_names) or "nothing\n")
    (root / "tools" / "ci").mkdir(parents=True, exist_ok=True)
    (root / "tools" / "ci" / "repo_hygiene_gates.sh").write_text(
        "".join(f'run "x" python3 "$PG/{n}.py"\n' for n in ci_names) or "true\n")
    return root


# --------------------------------------------------------------- what it reads


# ------------------------------------------------------- the blocking behaviour


# ------------------------------------------- absence never renders as a pass


# -------------------------------------------------- against the real repo tree


# ---- the four timing-signoff gates this change wired, on the REAL tree ----

_NEWLY_WIRED = ("arith_ss_corner_risk_check",
                "hold_area_budget_check",
                "hold_corner_coverage_check",
                "pnr_timing_repair_completeness_check")


def _real_plugin():
    plugin = PROGRAMS.parent
    if not (plugin / "flow").is_dir():
        pytest.skip("not running inside the plugin tree")
    return plugin


def _real_repo(plugin):
    """The SAME walk `main()` does. Resolving the repo root differently gives
    a different `tools/ci` sweep and therefore a different unwired set — which
    is exactly how the first draft of the GROW test silently compared 61
    against 60 and concluded the ratchet was gone."""
    repo = plugin
    for _ in range(6):
        if (repo / ".git").exists() or (repo / "tools" / "ci").is_dir():
            break
        repo = repo.parent
    return repo


def test_the_shipped_register_no_longer_holds_the_four_wired_gates():
    """A debt register may only SHRINK, and an entry that describes nothing is
    debt the register is not carrying. These four are now named in the flow
    yaml's gate clauses, so leaving them recorded would have the tool print
    `Re-run with --write-baseline` on every run — a standing instruction
    nobody executes, which is how a ratchet stops being one."""
    plugin = _real_plugin()
    recorded = json.loads(
        (plugin / "programs" / "gate_is_wired_baseline.json").read_text(
            encoding="utf-8"))
    for name in _NEWLY_WIRED:
        assert name not in recorded["unwired"], name
        assert name not in recorded["skill_only"], name


# ---- the rule stamp, and the one door through which the register may GROW ---


# ------------- the corpus the verdict depends on, and saying so (#1467) ------

def _nested(tmp_path: Path, *, marketplace_is_a_checkout: bool,
            repo_tools: bool = True, extra_gates=()):
    """The REAL shape: repo root, plugin three levels down inside it.

    `_tree` puts `tools/ci/` under the plugin, which is the one layout where
    the repo-root walk cannot go wrong. This repo's actual layout is
    `<repo>/vibe-ic-marketplace/plugins/vibe-ic`, with the wiring corpus three
    levels ABOVE the plugin — so the walk is load-bearing, and only a nested
    fixture exercises it.
    """
    repo = tmp_path / "repo"
    plugin = repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    (plugin / "programs").mkdir(parents=True)
    for g in ("a_check",) + tuple(extra_gates):
        (plugin / "programs" / f"{g}.py").write_text("# a gate\n")
    (plugin / "flow").mkdir()
    (plugin / "flow" / "phase1_phase2_phase3.yaml").write_text("steps: []\n")
    (repo / ".git").mkdir(parents=True)
    if repo_tools:
        (repo / "tools" / "ci").mkdir(parents=True)
        (repo / "tools" / "ci" / "repo_hygiene_gates.sh").write_text(
            'run "a" "$ROOT" python3 "$PG/a_check.py"\n')
    if marketplace_is_a_checkout:
        (repo / "vibe-ic-marketplace" / ".git").write_text(
            "gitdir: /elsewhere/.git/worktrees/mkt\n")
    (plugin / "programs" / "gate_is_wired_baseline.json").write_text(
        json.dumps({"unwired": []}))
    return repo, plugin
