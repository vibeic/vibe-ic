"""ORGANIC #570, #556, #562 — phase3_one_shot_runner new helpers:
  #570: _docker_timeout_isolate renames partial outputs on rc=124
  #556: _sdc_period_ps reads smallest create_clock period from SDC files
  #562: _build_spare_postfix_tcl emits FIRM lock + check_placement catch
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402


# ── #570 ──────────────────────────────────────────────────────────────────────

def test_570_rename_partial_on_timeout(tmp_path):
    f = tmp_path / "routed.def"
    f.write_text("partial content")
    R._docker_timeout_isolate([f])
    assert not f.exists()
    partial = f.with_suffix(".def.timeout.partial")
    assert partial.is_file()
    assert partial.read_text() == "partial content"


def test_570_skip_nonexistent_file(tmp_path):
    missing = tmp_path / "does_not_exist.def"
    # Must not raise
    R._docker_timeout_isolate([missing])
    assert not missing.exists()


def test_570_multiple_outputs(tmp_path):
    files = [tmp_path / f"out{i}.def" for i in range(3)]
    for f in files:
        f.write_text("data")
    R._docker_timeout_isolate(files)
    for f in files:
        assert not f.exists()
        assert f.with_suffix(".def.timeout.partial").is_file()


# ── #556 ──────────────────────────────────────────────────────────────────────









# ── #562 ──────────────────────────────────────────────────────────────────────
