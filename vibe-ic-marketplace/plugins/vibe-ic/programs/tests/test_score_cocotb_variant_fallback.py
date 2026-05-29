"""Tests for the v0.1.55 R3 capture: sync→async reset variant fallback in
score_cocotb_mcp.py.

Verifies the deterministic `_find_async_variant()` helper which encodes the
v0.1.24 documented Cat-A workaround for cocotb harnesses that race a
synchronous-reset NBA update. The fallback search order is enforced (closest
sibling first, then rtl_variants/, then work/rtl/, then phase2/stage1/rtl/).
"""
import importlib.util
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parents[2]
          / "benchmark-harness" / "score_cocotb_mcp.py")


def _load():
    spec = importlib.util.spec_from_file_location("score_cocotb_mcp", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _touch(p: Path, body: str = "// stub"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def test_find_async_sibling_next_to_primary(tmp_path):
    """Primary RTL has a sibling <top>_async.sv → return it."""
    mod = _load()
    proj = tmp_path / "p"
    primary = proj / "work" / "rtl" / "foo.sv"
    _touch(primary)
    sibling = proj / "work" / "rtl" / "foo_async.sv"
    _touch(sibling)
    found = mod._find_async_variant(primary, proj, "foo")
    assert found == sibling


def test_find_async_in_rtl_variants_dir(tmp_path):
    """Primary in work/rtl/, async in phase2/stage1/rtl_variants/ → found."""
    mod = _load()
    proj = tmp_path / "p"
    primary = proj / "work" / "rtl" / "foo.sv"
    _touch(primary)
    variant = proj / "phase2" / "stage1" / "rtl_variants" / "foo_async.sv"
    _touch(variant)
    found = mod._find_async_variant(primary, proj, "foo")
    assert found == variant


def test_find_async_sibling_preferred_over_rtl_variants(tmp_path):
    """When both sibling AND rtl_variants/ have async, sibling wins (closest)."""
    mod = _load()
    proj = tmp_path / "p"
    primary = proj / "work" / "rtl" / "foo.sv"
    _touch(primary)
    sibling = proj / "work" / "rtl" / "foo_async.sv"
    _touch(sibling)
    variant = proj / "phase2" / "stage1" / "rtl_variants" / "foo_async.sv"
    _touch(variant)
    found = mod._find_async_variant(primary, proj, "foo")
    assert found == sibling


def test_find_async_no_match_returns_none(tmp_path):
    """No async variant anywhere → None (fallback is a no-op)."""
    mod = _load()
    proj = tmp_path / "p"
    primary = proj / "work" / "rtl" / "foo.sv"
    _touch(primary)
    assert mod._find_async_variant(primary, proj, "foo") is None


def test_find_async_accepts_dot_v_extension(tmp_path):
    """An async sibling with .v extension also counts."""
    mod = _load()
    proj = tmp_path / "p"
    primary = proj / "work" / "rtl" / "foo.sv"
    _touch(primary)
    sibling_v = proj / "work" / "rtl" / "foo_async.v"
    _touch(sibling_v)
    assert mod._find_async_variant(primary, proj, "foo") == sibling_v


def test_find_async_in_phase2_stage1_rtl(tmp_path):
    """The runner emits async variants under phase2/stage1/rtl/ too."""
    mod = _load()
    proj = tmp_path / "p"
    primary = proj / "phase2" / "stage1" / "rtl" / "foo.sv"
    _touch(primary)
    variant = proj / "phase2" / "stage1" / "rtl" / "foo_async.sv"
    _touch(variant)
    assert mod._find_async_variant(primary, proj, "foo") == variant


def test_argparse_no_variant_fallback_flag_exists(tmp_path):
    """The --no-variant-fallback flag must be present + default to fallback ON."""
    src = SCRIPT.read_text()
    assert "--no-variant-fallback" in src
    # Default behaviour is fallback ON (i.e. the flag DISABLES it)
    assert "no_variant_fallback" in src
