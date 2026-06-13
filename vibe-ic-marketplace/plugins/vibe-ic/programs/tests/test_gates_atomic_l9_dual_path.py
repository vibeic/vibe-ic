"""Tests for the gates_atomic.py L9 dual-path probe (clean-install self-containment).

Packaging fix (ORGANIC-20260603-ingest-engine-cli-missing-from-plugin-cache):
tools/phase1_engine is NOT shipped in the plugin — it is a dev-only symlink to
the monorepo. On a clean machine the primary `tools.phase1_engine.cli` path is
dead and the bundled fallback `phase1_one_shot_runner.py` runs instead, writing
L9 to <wd>/phase1_proj/phase1/generated_docs/ rather than <wd>/out/generated_docs/.
The gate's phase1 hard step must accept EITHER location so a clean install passes
self-contained. These are pure-python tests of the _l9_rendered helper.
"""
import importlib.util
from pathlib import Path

GATES = (Path(__file__).resolve().parents[2]
         / "benchmark" / "gates_atomic.py")


def _load():
    spec = importlib.util.spec_from_file_location("gates_atomic", GATES)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_l9(d: Path):
    d.mkdir(parents=True, exist_ok=True)
    (d / "L9_INTEGRATION_SPEC.json").write_text('{"module_name": "TopModule"}')


def test_l9_in_primary_out_dir(tmp_path):
    """Primary engine path: L9 in <wd>/out/generated_docs/ -> True."""
    mod = _load()
    _write_l9(tmp_path / "out" / "generated_docs")
    assert mod._l9_rendered(tmp_path) is True


def test_l9_in_fallback_phase1proj_dir(tmp_path):
    """Bundled fallback path (clean install): L9 in
    <wd>/phase1_proj/phase1/generated_docs/ -> True. This is the case that was
    FAILing before the fix (gate only probed out/)."""
    mod = _load()
    _write_l9(tmp_path / "phase1_proj" / "phase1" / "generated_docs")
    assert mod._l9_rendered(tmp_path) is True


def test_l9_absent_both_dirs(tmp_path):
    """No L9 anywhere -> False (a genuine phase1 failure still fails the gate)."""
    mod = _load()
    (tmp_path / "out" / "generated_docs").mkdir(parents=True)
    assert mod._l9_rendered(tmp_path) is False


def test_l9_dir_exists_but_no_l9_file(tmp_path):
    """generated_docs/ exists but holds no L9*.json -> False."""
    mod = _load()
    d = tmp_path / "phase1_proj" / "phase1" / "generated_docs"
    d.mkdir(parents=True)
    (d / "L1.json").write_text("{}")  # other layer doc, not L9
    assert mod._l9_rendered(tmp_path) is False
