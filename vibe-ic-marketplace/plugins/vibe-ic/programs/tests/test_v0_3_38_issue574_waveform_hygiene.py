"""ORGANIC #574 — stray simulation waveform dump (programs/wave.vcd)
shipped inside the plugin programs/ tree, polluting repo-wide audits
(VCD tokens false-match issue-tag greps).  Fixes: the stray dump is
deleted, and waveform_artifact_hygiene_check.py pins the class — no
*.vcd / *.fst / *.ghw / *.shm may exist anywhere in the plugin tree.
"""
import pathlib
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


def test_checker_flags_every_waveform_suffix_it_claims(tmp_path):
    """Every suffix in `WAVEFORM_SUFFIXES` still yields a finding — but each
    one now has to say WHY.

    This test used to write the single byte "x" into each of the four names
    and assert four hits, which was a faithful pin of a program whose entire
    test was the suffix. #805 replaced that with content classification, so
    the four files here carry their real formats and the `.shm` — for which
    no content detector exists or is claimed — lands in UNDETERMINED. The
    count is unchanged; what each element MEANS is not, and the old form
    would have kept passing over a program that had stopped detecting
    anything (four unreadable stubs are also four findings).
    """
    (tmp_path / "a.vcd").write_bytes(b"$date\n\ttoday\n$end\n#0\n")
    (tmp_path / "b.fst").write_bytes(b"\x00" + (329).to_bytes(8, "big")
                                     + b"\x00" * 320)
    (tmp_path / "c.ghw").write_bytes(b"GHDLwave\n\x10\x00\x01\x01" + b"\x00" * 64)
    (tmp_path / "d.shm").write_bytes(b"\x01\x02\x03")
    # v1.9.0 (#564): audit() returns (findings, files_examined) — the
    # denominator is returned rather than re-derived, so a clean scan and a
    # scan of nothing stop printing the same sentence.
    findings, _examined = WH.audit(str(tmp_path))
    assert len(findings) == 4
    got = {pathlib.Path(f.path).name: (f.state, f.fmt) for f in findings}
    assert got == {
        "a.vcd": (WH.WAVEFORM, "vcd"),
        "b.fst": (WH.WAVEFORM, "fst"),
        "c.ghw": (WH.WAVEFORM, "ghw"),
        "d.shm": (WH.UNDETERMINED, ""),
    }, got


def test_checker_passes_clean_tree(tmp_path):
    (tmp_path / "prog.py").write_text("print('hi')\n")
    rc = WH.main([str(tmp_path)])
    assert rc == 0


def test_checker_ignores_pycache_noise(tmp_path):
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "stray.vcd").write_text("$date\n\ttoday\n$end\n#0\n")
    findings, _examined = WH.audit(str(tmp_path))
    assert findings == []


# ── the live pin: the shipped plugin tree must stay waveform-free ───────────

def test_plugin_tree_has_no_waveform_artifacts():
    findings, examined = WH.audit(str(PLUGIN_ROOT))
    assert examined > 0, (
        "the plugin-tree scan examined nothing; a clean verdict over zero "
        "files is the defect #564 added the denominator for")
    # #805: `findings` also carries UNDETERMINED entries — a file that could
    # not be read, or one whose name claims a waveform its content does not
    # confirm. Both belong in this pin: the tree is clean only when nothing
    # in it is unaccounted for.
    assert findings == [], "\n".join(str(f) for f in findings)
