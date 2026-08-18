"""Tests for v0.1.59 R10 capture: score_cocotb_mcp.py auto-discovers the
candidate RTL from canonical runner locations when --rtl is omitted.

Captured from v0.1.58 CVDP run: every Shape-D scoring required a manual
`cp phase2/stage1/rtl/<top>.sv work/rtl/<top>.sv` before invoking the
scorer with --rtl work/rtl/<top>.sv.
"""
import importlib.util
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parents[2]
          / "benchmark" / "score_cocotb_mcp.py")


def _load():
    spec = importlib.util.spec_from_file_location("score_cocotb_mcp", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _touch(p: Path, body: str = "// stub"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


# ── Search-order priority (canonical → fallback) ────────────────────────

def test_autodiscover_work_rtl_sv_first(tmp_path):
    """The Shape-D blind-instructions step 3 target wins when present."""
    mod = _load()
    proj = tmp_path / "p"
    _touch(proj / "work" / "rtl" / "foo.sv", "// work/rtl/.sv")
    _touch(proj / "phase2" / "stage1" / "rtl" / "foo.sv", "// phase2/.sv")
    found = mod._autodiscover_rtl(proj, "foo")
    assert found is not None
    assert found.parent.name == "rtl"
    assert "work" in str(found)
    assert found.suffix == ".sv"


def test_autodiscover_falls_back_to_phase2_stage1_rtl(tmp_path):
    """When work/rtl/ is empty, the spec-to-rtl emit path is the fallback."""
    mod = _load()
    proj = tmp_path / "p"
    _touch(proj / "phase2" / "stage1" / "rtl" / "foo.sv")
    found = mod._autodiscover_rtl(proj, "foo")
    assert found is not None
    assert "phase2/stage1/rtl" in str(found).replace("\\", "/")


def test_autodiscover_accepts_dot_v_extension(tmp_path):
    """.v is also valid; .sv preferred but .v matches when no .sv exists."""
    mod = _load()
    proj = tmp_path / "p"
    _touch(proj / "work" / "rtl" / "foo.v")
    found = mod._autodiscover_rtl(proj, "foo")
    assert found is not None
    assert found.suffix == ".v"


def test_autodiscover_returns_none_when_nothing_matches(tmp_path):
    """No RTL anywhere → None; caller emits an explicit error."""
    mod = _load()
    proj = tmp_path / "p"
    proj.mkdir()
    assert mod._autodiscover_rtl(proj, "foo") is None


def test_autodiscover_top_specific(tmp_path):
    """An RTL file for a DIFFERENT top name must NOT match."""
    mod = _load()
    proj = tmp_path / "p"
    _touch(proj / "work" / "rtl" / "other.sv")
    assert mod._autodiscover_rtl(proj, "foo") is None


def test_autodiscover_dot_sv_beats_dot_v_at_same_dir(tmp_path):
    """When both .sv and .v exist in work/rtl/, .sv wins (priority list order)."""
    mod = _load()
    proj = tmp_path / "p"
    _touch(proj / "work" / "rtl" / "foo.sv")
    _touch(proj / "work" / "rtl" / "foo.v")
    found = mod._autodiscover_rtl(proj, "foo")
    assert found.suffix == ".sv"


# ── argparse: --rtl is now optional ────────────────────────────────────

def test_argparse_rtl_is_optional():
    """The --rtl flag must have required=False (so it can be omitted)."""
    src = SCRIPT.read_text()
    rtl_block_start = src.find('ap.add_argument("--rtl"')
    assert rtl_block_start >= 0, "could not find ap.add_argument(\"--rtl\", ...) call"
    # The whole add_argument(...) call until the closing )
    rest = src[rtl_block_start:]
    # Find the matching close-paren by counting; for our purposes, find first )
    # at the same indentation level (the call spans multiple lines but ends in `)`).
    block_end = rest.find('))')  # nested string is fine; find )) ending the call
    if block_end < 0:
        block_end = rest.find(')\n')
    block = rest[:block_end + 1]
    assert "required=False" in block, f"--rtl must be required=False; got block:\n{block}"


def test_argparse_help_text_mentions_autodiscover():
    """The --rtl help text must mention auto-discovery so users know they can
    omit the flag for canonical runner outputs."""
    src = SCRIPT.read_text()
    rtl_block_start = src.find('ap.add_argument("--rtl"')
    assert rtl_block_start >= 0
    rest = src[rtl_block_start:]
    block_end = rest.find('))')
    if block_end < 0:
        block_end = rest.find(')\n')
    block = rest[:block_end + 1].lower()
    assert "auto-discover" in block or "autodiscover" in block
