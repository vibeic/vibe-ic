"""ORGANIC #574 — stray simulation waveform dump (programs/wave.vcd)
shipped inside the plugin programs/ tree, polluting repo-wide audits
(VCD tokens false-match issue-tag greps).  Fixes: the stray dump is
deleted, and waveform_artifact_hygiene_check.py pins the class — no
*.vcd / *.fst / *.ghw / *.shm may exist anywhere in the plugin tree.
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = PROG.parent
sys.path.insert(0, str(PROG))
import waveform_artifact_hygiene_check as WH  # noqa: E402


def test_checker_flags_stray_vcd(tmp_path):
    """The issue's exact shape: a wave.vcd inside programs/ must FAIL."""
    (tmp_path / "programs").mkdir()
    (tmp_path / "programs" / "wave.vcd").write_text(
        "$date today $end\n$timescale 1ns $end\n#548\n"
    )
    rc = WH.main([str(tmp_path)])
    assert rc == 1


def test_checker_flags_all_waveform_suffixes(tmp_path):
    for name in ("a.vcd", "b.fst", "c.ghw", "d.shm"):
        (tmp_path / name).write_text("x")
    hits = WH.audit(str(tmp_path))
    assert len(hits) == 4


def test_checker_passes_clean_tree(tmp_path):
    (tmp_path / "prog.py").write_text("print('hi')\n")
    rc = WH.main([str(tmp_path)])
    assert rc == 0


def test_checker_ignores_pycache_noise(tmp_path):
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "stray.vcd").write_text("x")
    assert WH.audit(str(tmp_path)) == []


# ── the live pin: the shipped plugin tree must stay waveform-free ───────────

def test_plugin_tree_has_no_waveform_artifacts():
    hits = WH.audit(str(PLUGIN_ROOT))
    assert hits == [], "\n".join(hits)
