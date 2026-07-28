"""v0.2.58 phase1-engine bundling regressions.

Pins the #429 fix (ORGANIC-20260606-plugin-cache-missing-phase1-engine):
the installed plugin cache shipped WITHOUT tools/phase1_engine, so the
one-shot runner's engine lookup resolved to a null engine and every
prompt-mode project FAILed on a clean cache until the user hand-made a
marketplace symlink. Three things shipped:

  1. the engine is BUNDLED in the plugin payload at
     <plugin>/tools/phase1_engine (drift-guarded against the repo-root
     master copy below);
  2. the runner resolves the engine via an explicit fallback chain
     (bundled -> $CLAUDE_PLUGIN_ROOT -> repo walk-up -> sibling guesses)
     and emits a HARD, NAMED error listing every searched location when
     none resolves — never a silent null engine;
  3. gap_detect.DEFAULT_CLASS_KB resolves anchored to ITS OWN file
     (bundled sibling agents/class_kb first), not to a cwd-relative path
     that only a repo checkout satisfies.

The install-smoke test runs phase1 on a one-line prompt fixture from a
BARE cache-shaped layout (plugin dir only, no repo-root tools/).
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
BUNDLED = PLUGIN / "tools" / "phase1_engine"

sys.path.insert(0, str(PROGRAMS))
import phase1_one_shot_runner as p1r  # noqa: E402

# repo-root master copy (absent on an installed cache — tests then skip
# the drift comparison, which only matters in the checkout)
_MASTER = None
for anc in PLUGIN.parents:
    cand = anc / "tools" / "phase1_engine"
    if (cand / "cli.py").is_file():
        _MASTER = cand
        break


def test_engine_is_bundled_in_plugin_payload():
    assert (BUNDLED / "cli.py").is_file(), \
        "plugin payload must bundle tools/phase1_engine (cache installs " \
        "have no repo-root tools/)"
    assert (BUNDLED / "gap_detect.py").is_file()


@pytest.mark.skipif(_MASTER is None, reason="repo-root master not present "
                    "(installed cache layout)")
def test_bundle_does_not_drift_from_master():
    def _digest(root: Path) -> dict:
        out = {}
        for f in sorted(root.rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts:
                out[str(f.relative_to(root))] = hashlib.sha256(
                    f.read_bytes()).hexdigest()
        return out
    master, bundle = _digest(_MASTER), _digest(BUNDLED)
    assert master == bundle, (
        "bundled engine drifted from tools/phase1_engine — re-run "
        "`rsync -a --exclude=__pycache__ tools/phase1_engine/ "
        "vibe-ic-marketplace/plugins/vibe-ic/tools/phase1_engine/`")


def test_bundled_class_kb_resolves_self_anchored():
    # importing the BUNDLED gap_detect must resolve class_kb to the
    # plugin's own agents/class_kb without any cwd assumption
    r = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, %r); "
         "from phase1_engine import gap_detect; "
         "print(gap_detect.DEFAULT_CLASS_KB)" % str(PLUGIN / "tools")],
        capture_output=True, text=True, cwd="/", timeout=60)
    assert r.returncode == 0, r.stderr
    kb = Path(r.stdout.strip())
    assert kb == PLUGIN / "agents" / "class_kb"
    assert (kb / "class-tree.yaml").is_file()


def test_runner_resolves_bundled_engine_first():
    cli, tried = p1r._find_phase1_engine()
    assert cli is not None and cli.is_file()
    assert tried[0] == str(PLUGIN / "tools" / "phase1_engine" / "cli.py")
    assert cli == Path(tried[0])  # bundle wins the chain


def test_named_error_lists_searched_locations(tmp_path, monkeypatch):
    # simulate "nothing resolves": point PROGRAMS_DIR into an empty tree
    # and clear the env hint; the step must FAIL naming every location.
    monkeypatch.setattr(p1r, "PROGRAMS_DIR", tmp_path / "nowhere" / "programs")
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    monkeypatch.setattr(p1r.Path, "is_file",
                        lambda self: False)  # no guesses resolve either
    proj = tmp_path / "proj"
    (proj / "input").mkdir(parents=True)
    (proj / "input" / "phase1_prompt.md").write_text("a divider.")
    res = p1r.step_ingest_render(proj, "x")
    assert res.status == "FAIL"
    assert "NOT FOUND" in res.detail
    assert "Searched (in order)" in res.detail
    assert "tools/phase1_engine/cli.py" in res.detail


def test_install_smoke_bare_cache_layout(tmp_path):
    # BARE cache shape: copy ONLY the plugin payload pieces the runner
    # needs (programs/, tools/phase1_engine/, agents/class_kb/) into an
    # isolated root with NO repo-root tools/ anywhere above it (/tmp).
    cache = tmp_path / "cache" / "vibe-ic"
    import shutil
    shutil.copytree(PROGRAMS, cache / "programs",
                    ignore=shutil.ignore_patterns("__pycache__", "tests"))
    shutil.copytree(PLUGIN / "tools" / "phase1_engine",
                    cache / "tools" / "phase1_engine",
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(PLUGIN / "agents" / "class_kb",
                    cache / "agents" / "class_kb")
    proj = tmp_path / "proj"
    (proj / "input").mkdir(parents=True)
    (proj / "input" / "phase1_prompt.md").write_text(
        "Build a module named pulse_div: input clk, input rst_n, output "
        "tick. Divide the clock by 10; tick asserts one cycle in ten. "
        "Reset is asynchronous active low.\n")
    env = dict(os.environ)
    env.pop("CLAUDE_PLUGIN_ROOT", None)
    r = subprocess.run(
        [sys.executable, str(cache / "programs" / "phase1_one_shot_runner.py"),
         str(proj), "--ic-name", "pulse_div"],
        capture_output=True, text=True, timeout=60, cwd=str(tmp_path),
        env=env)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-1500:]
    gd = proj / "phase1" / "generated_docs"
    assert len(list(gd.glob("L*.json"))) >= 13, \
        "bare-cache phase1 must emit the full flat L-doc set"
    assert not (gd / "generated_docs").exists()
