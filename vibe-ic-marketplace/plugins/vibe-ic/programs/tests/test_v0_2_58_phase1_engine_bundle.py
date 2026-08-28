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
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
BUNDLED = PLUGIN / "tools" / "phase1_engine"

sys.path.insert(0, str(PROGRAMS))
import phase1_one_shot_runner as p1r  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

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


#: THE ONE FILE THAT CANNOT BE MIRRORED, and it is not an escape hatch — it is
#: a file whose CONTENT names its own location, so a byte-identical copy of it
#: at a second path is invalid by the schema of the gate that reads it.
#:
#: `tools/phase1_engine/INVARIANTS.json` (added 8adebfc4e) declares
#: `"package": "tools/phase1_engine"`, and `package_invariants_check` refuses a
#: file whose `package` is not the package's own repo-relative path:
#:
#:     [SCHEMA] vibe-ic-marketplace/plugins/vibe-ic/tools/phase1_engine:
#:     'package' must be the package's own repo-relative path,
#:     got 'tools/phase1_engine'
#:
#: MEASURED on this tree: a plain `rsync -a --exclude=__pycache__` — the remedy
#: this test used to print — turns `test_package_invariants_check` from
#: `24 passed` into two failures, first `[UNENROLLED] ... exists but ... is not
#: named in package_invariants_enrolled.json` and then, once enrolled, the
#: SCHEMA refusal above. There is no spelling of the mirror that satisfies both
#: gates, because the two gates are asking about different things: this one asks
#: that the shipped ENGINE is the master engine, and that one asks that a
#: package's rule file names the package it binds.
#:
#: So the exclusion is DECLARED here rather than discovered, it is asserted to be
#: exactly this one name below, and the remedy printed on failure is the rsync
#: that actually produces a tree both gates accept.
_NOT_MIRRORED = ("INVARIANTS.json",)

_RSYNC = ("rsync -a --exclude=__pycache__ "
          + " ".join(f"--exclude={n}" for n in _NOT_MIRRORED)
          + " tools/phase1_engine/ "
          + "vibe-ic-marketplace/plugins/vibe-ic/tools/phase1_engine/")


@pytest.mark.skipif(_MASTER is None, reason="repo-root master not present "
                    "(installed cache layout)")
def test_bundle_does_not_drift_from_master():
    def _digest(root: Path) -> dict:
        out = {}
        for f in sorted(root.rglob("*")):
            if (f.is_file() and "__pycache__" not in f.parts
                    and f.name not in _NOT_MIRRORED):
                out[str(f.relative_to(root))] = hashlib.sha256(
                    f.read_bytes()).hexdigest()
        return out
    master, bundle = _digest(_MASTER), _digest(BUNDLED)
    assert master == bundle, (
        "bundled engine drifted from tools/phase1_engine — re-run "
        f"`{_RSYNC}`")


def test_the_unmirrored_set_is_exactly_the_self_naming_rule_file():
    """The exclusion above may not quietly grow.

    An excluded name is a file the drift guard stops comparing, so every entry
    is a hole. This pins the set to one, and pins WHY that one is there: it
    exists in the master, it names its own package path, and it is absent from
    the bundle. A second entry, or this one silently reappearing in the bundle,
    fails here rather than widening the guard's blind spot in silence.
    """
    assert _NOT_MIRRORED == ("INVARIANTS.json",)
    if _MASTER is None:                                 # installed cache layout
        pytest.skip("repo-root master not present (installed cache layout)")
    src = _MASTER / "INVARIANTS.json"
    assert src.is_file(), (
        "the excluded name does not exist in the master, so the exclusion "
        "guards nothing — delete it from _NOT_MIRRORED")
    assert json.loads(src.read_text())["package"] == "tools/phase1_engine", (
        "the reason for the exclusion is that this file names its own package "
        "path; if it no longer does, the exclusion has lost its justification")
    assert not (BUNDLED / "INVARIANTS.json").exists(), (
        "the bundle carries a copy of the master's INVARIANTS.json — "
        "`package_invariants_check` refuses it (UNENROLLED, then SCHEMA). "
        f"Re-mirror with `{_RSYNC}`")


def test_bundled_class_kb_resolves_self_anchored():
    # importing the BUNDLED gap_detect must resolve class_kb to the
    # plugin's own agents/class_kb without any cwd assumption
    r = _pr.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, %r); "
         "from phase1_engine import gap_detect; "
         "print(gap_detect.DEFAULT_CLASS_KB)" % str(PLUGIN / "tools")],
        capture_output=True, text=True, cwd="/")
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
    r = _pr.run(
        [sys.executable, str(cache / "programs" / "phase1_one_shot_runner.py"),
         str(proj), "--ic-name", "pulse_div"],
        capture_output=True, text=True, cwd=str(tmp_path),
        env=env)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-1500:]
    gd = proj / "phase1" / "generated_docs"
    assert len(list(gd.glob("L*.json"))) >= 13, \
        "bare-cache phase1 must emit the full flat L-doc set"
    assert not (gd / "generated_docs").exists()
