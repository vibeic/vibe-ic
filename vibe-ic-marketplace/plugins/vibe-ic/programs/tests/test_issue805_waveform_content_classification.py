"""#805 — the waveform gate decided by FILENAME SUFFIX and never read a byte.

    if p.suffix.lower() in WAVEFORM_SUFFIXES:      # the entire test
        hits.append(str(p))

`grep -cE "read_bytes|magic|header|open\\(.*rb"` over the file: 0. A file was a
waveform iff it was NAMED like one.

THE ARTEFACT THAT DEFEATS THAT, REPRODUCED ON THIS MACHINE
----------------------------------------------------------
`iverilog` built without zlib keeps the requested filename while silently
writing the other format:

    $dumpfile("t.fst"); $dumpvars;
      vvp a.vvp        -> rc 0, 331-byte **ASCII VCD** named t.fst
      vvp a.vvp -fst   -> rc 1 "FST support disabled since zlib not available"
      file t.fst       -> "ASCII text"

`_VCD_NAMED_FST` below is that file's actual bytes. Every suffix-based check
calls it an FST; the shipped EDA image produced the same thing.

WHAT EACH TEST IS WORTH (pre-fix = the suffix-only program at e3aa9b126)
-----------------------------------------------------------------------
BEHAVIOURAL controls — the verdict itself flips, through the real CLI, with no
new symbol involved:

  waveform content under a NON-waveform name   pre rc 0 PASS -> post rc 1 FAIL
  non-waveform content under a .vcd name       pre rc 1 FAIL -> post rc 3
  zero-byte .vcd                               pre rc 1 FAIL -> post rc 3
  a file that cannot be read at all            pre rc 0 PASS -> post rc 3
  named .fst / content VCD                     both rc 1, but only post says
                                               WHICH format it found, and that
                                               the name disagrees

NO-LEAK controls — these do NOT distinguish pre from post. They exist because
every behavioural control above is satisfied by a program that recognises
nothing, and that program would stop catching the real dumps this gate is for:

  a genuine VCD / FST / gzip-wrapped FST / GHW is still a finding
  a tree of ordinary source files still passes at rc 0

STRUCTURE pins — assert on symbols that are new in the fix, so they cannot run
against the pre-fix program at all and prove nothing about it. Named as such.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import struct
import subprocess
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
PROG = _PROGRAMS / "waveform_artifact_hygiene_check.py"

_spec = importlib.util.spec_from_file_location("waveform_hygiene_805", PROG)
WH = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(WH)


def _run(root) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG), str(root)],
                          capture_output=True, text=True, timeout=60)


# ── fixtures: real formats, from their real producers ───────────────────────

#: Verbatim output of `vvp a.vvp` on this machine for a design whose
#: `$dumpfile` names "t.fst" — an ASCII VCD carrying an FST filename.
_VCD_NAMED_FST = (
    b"$date\n\tWed Aug  5 02:59:49 2026\n$end\n"
    b"$version\n\tIcarus Verilog\n$end\n"
    b"$timescale\n\t1s\n$end\n"
    b"$scope module t $end\n"
    b"$var reg 4 ! c [3:0] $end\n"
    b"$upscope $end\n"
    b"$enddefinitions $end\n"
    b"#0\nb0 !\n#5\nb1 !\n#10\nb10 !\n"
)

#: FST header block, built from the writer's own constants
#: (`fstWriterEmitHdrBytes` in gtkwave `fstapi.c`, block-type enum in
#: `fstapi.h`): +0 tag FST_BL_HDR, +1 uint64 section length 329, +9 start
#: time, +17 end time, +25 the endian-test double e. Byte-for-byte the prefix
#: of the real FSTs this detector was checked against outside the repo —
#: gtkwave's `examples/des.fst` and `transaction.fst`, iverilog's
#: `ivtest/dump.fst`, yosys's `tests/sat/grom.fst`.
_FST = (b"\x00" + (329).to_bytes(8, "big")
        + (0).to_bytes(8, "big") + (2).to_bytes(8, "big")
        + struct.pack("<d", 2.7182818284590452354)
        + b"\x00" * 8 + b"\x00" * 280)

#: The repack-on-close variant: FST_BL_ZWRAPPER (254), uint64 section length,
#: uint64 uncompressed length, then ONE gzip stream. Prefix shape of yosys's
#: `tests/sat/stimulus.fst`.
_FST_ZWRAPPED = (b"\xfe" + (199).to_bytes(8, "big") + (560).to_bytes(8, "big")
                 + b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03" + b"\x00" * 64)

#: GHW magic + version, per ghdl's own reader (`libghw.c`: memcmp against
#: "GHDLwave\n", then hdr[9]==16 and hdr[10]==0). Prefix of gtkwave's
#: `lib/libgtkwave/test/files/basic.ghw`.
_GHW = b"GHDLwave\n\x10\x00\x01\x01\x04\x01\x00STR\x00" + b"\x00" * 64

#: A file that is not a waveform in any format — ordinary shipped content.
_NOT_A_WAVEFORM = b"module m; endmodule\n"


# ── BEHAVIOURAL: the verdict flips, through the CLI ─────────────────────────

def test_a_vcd_hiding_under_a_non_waveform_name_is_caught(tmp_path):
    """pre rc 0 PASS -> post rc 1 FAIL.

    The suffix test could not see this at all: a dump written to `sim.log`
    (or any name a Makefile happened to choose) was invisible, which is the
    same hole the .fst/.vcd swap exploits from the other direction.
    """
    (tmp_path / "sim.log").write_bytes(_VCD_NAMED_FST)
    proc = _run(tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "sim.log" in proc.stdout
    assert "content is VCD" in proc.stdout, proc.stdout


def test_an_fst_hiding_under_a_non_waveform_name_is_caught(tmp_path):
    """pre rc 0 PASS -> post rc 1 FAIL. Same hole, binary format."""
    (tmp_path / "dump.dat").write_bytes(_FST)
    proc = _run(tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "content is FST" in proc.stdout, proc.stdout


def test_a_vcd_named_fst_is_reported_as_the_disagreement_it_is(tmp_path):
    """THE LOAD-BEARING CASE — the exact artefact this machine's iverilog
    writes. Both programs exit 1 here, so the rc alone proves nothing; what
    the pre-fix program cannot do is SAY what it found. It reported
    `waveform artifact in shipped tree: .../t.fst` and nothing else, and a
    reader would take that as an FST — which is how the image bug survived.
    """
    (tmp_path / "t.fst").write_bytes(_VCD_NAMED_FST)
    proc = _run(tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "NAME/CONTENT DISAGREE" in proc.stdout, proc.stdout
    assert "named .fst, content is VCD" in proc.stdout, proc.stdout


def test_a_vcd_named_file_that_is_not_a_waveform_is_undetermined(tmp_path):
    """pre rc 1 FAIL -> post rc 3.

    The pre-fix program called this a waveform artifact on the strength of
    its name. It is not one; but neither is it demonstrably clean, so it does
    NOT become a pass — it becomes the third verdict.
    """
    (tmp_path / "notes.vcd").write_bytes(b"these are meeting notes, not a dump\n")
    proc = _run(tmp_path)
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "UNCLASSIFIED" in proc.stdout, proc.stdout
    assert "UNDETERMINED" in proc.stdout.splitlines()[-1], proc.stdout


def test_a_zero_byte_vcd_is_undetermined_not_clean(tmp_path):
    """pre rc 1 FAIL -> post rc 3, and the point is what it must NOT be: 0.

    A dump the simulator opened and never wrote is a FAILED dump. The easy
    content check ("does it start with $date? no -> not a waveform") turns
    every truncated dump into a pass, which is a worse gate than the suffix
    one it replaces.
    """
    (tmp_path / "wave.vcd").write_bytes(b"")
    proc = _run(tmp_path)
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "EMPTY (0 bytes)" in proc.stdout, proc.stdout


@pytest.mark.skipif(os.geteuid() == 0,
                    reason="root can read a 0o000 file, so the case cannot "
                           "be produced here")
def test_an_unreadable_file_is_undetermined_not_clean(tmp_path):
    """pre rc 0 PASS -> post rc 3.

    Nothing about a file that cannot be opened says it is not a waveform
    dump. The pre-fix program never opened anything, so an unreadable file
    was indistinguishable from a clean one; a content-based checker that
    swallowed the OSError would be the same defect with more code.
    """
    victim = tmp_path / "opaque.bin"
    victim.write_bytes(_NOT_A_WAVEFORM)
    victim.chmod(0o000)
    try:
        proc = _run(tmp_path)
        assert proc.returncode == 3, proc.stdout + proc.stderr
        assert "could not be read" in proc.stdout, proc.stdout
    finally:
        victim.chmod(0o644)


def test_a_waveform_outranks_an_unclassifiable_file(tmp_path):
    """A tree holding both reports rc 1: a confirmed dump is the stronger
    fact and must not be downgraded to "could not tell"."""
    (tmp_path / "notes.vcd").write_bytes(b"not a dump\n")
    (tmp_path / "real.vcd").write_bytes(_VCD_NAMED_FST)
    proc = _run(tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr


# ── NO-LEAK: satisfied by pre AND post; they stop a degenerate post ─────────

def test_a_genuine_vcd_is_still_a_finding(tmp_path):
    (tmp_path / "wave.vcd").write_bytes(_VCD_NAMED_FST)
    proc = _run(tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "content is VCD" in proc.stdout


def test_a_genuine_fst_is_still_a_finding(tmp_path):
    """"a correct .fst must still pass" — i.e. still be CAUGHT. Without this
    and the three below, a `sniff_format` that returned None for everything
    would satisfy every behavioural control above."""
    (tmp_path / "wave.fst").write_bytes(_FST)
    proc = _run(tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "content is FST" in proc.stdout


def test_a_gzip_repacked_fst_is_still_a_finding(tmp_path):
    (tmp_path / "wave.fst").write_bytes(_FST_ZWRAPPED)
    proc = _run(tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "content is FST" in proc.stdout


def test_a_genuine_ghw_is_still_a_finding(tmp_path):
    (tmp_path / "wave.ghw").write_bytes(_GHW)
    proc = _run(tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "content is GHW" in proc.stdout


def test_ordinary_source_still_passes_at_zero(tmp_path):
    """The accept case. A gate that refuses everything is not a gate."""
    (tmp_path / "a.v").write_bytes(_NOT_A_WAVEFORM)
    (tmp_path / "b.py").write_bytes(b"print('hi')\n")
    (tmp_path / "c.md").write_bytes(b"# notes\n\nsome $var prose\n")
    proc = _run(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.splitlines()[-1] == "PASS — 0 waveform artifact(s)"


def test_prose_merely_mentioning_a_vcd_keyword_is_not_a_waveform(tmp_path):
    """The false-positive edge of a text format with no magic. `$var` inside a
    document is not a dump; only a document that OPENS with a declaration
    command is."""
    (tmp_path / "doc.md").write_bytes(
        b"# how VCD works\n\nA dump opens with $date and $var lines.\n")
    proc = _run(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr


# ── STRUCTURE pins: about symbols the fix introduces (not pre/post controls) ─

def test_the_three_states_are_all_reachable(tmp_path):
    """The state machine itself, exhaustively — a fix that never emits
    UNDETERMINED is the silent pass this issue is about."""
    (tmp_path / "real.vcd").write_bytes(_VCD_NAMED_FST)
    (tmp_path / "plain.txt").write_bytes(b"hello\n")
    (tmp_path / "hollow.vcd").write_bytes(b"")
    assert WH.classify(tmp_path / "real.vcd")[0] == WH.WAVEFORM
    assert WH.classify(tmp_path / "plain.txt")[0] == WH.NOT_WAVEFORM
    assert WH.classify(tmp_path / "hollow.vcd")[0] == WH.UNDETERMINED


def test_no_content_detector_is_claimed_for_shm(tmp_path):
    """Coverage that cannot be demonstrated is not claimed. A Cadence `.shm`
    database is a DIRECTORY of `.trn`/`.dsd` members, so a *file* by that name
    has no magic to read — it resolves to UNDETERMINED, never to a confirmed
    hit and never to a pass."""
    assert ".shm" in WH.WAVEFORM_SUFFIXES
    assert ".shm" not in WH.CONTENT_DETECTABLE_SUFFIXES
    (tmp_path / "waves.shm").write_bytes(b"\x01\x02\x03")
    state, _fmt, detail = WH.classify(tmp_path / "waves.shm")
    assert state == WH.UNDETERMINED
    assert "NO content detector" in detail, detail


def test_sniff_format_reads_only_bytes(tmp_path):
    """The classifier takes bytes, so no name can reach it. The pre-fix
    program had no function that could be called this way at all."""
    assert WH.sniff_format(_VCD_NAMED_FST) == "vcd"
    assert WH.sniff_format(_FST) == "fst"
    assert WH.sniff_format(_FST_ZWRAPPED) == "fst"
    assert WH.sniff_format(_GHW) == "ghw"
    assert WH.sniff_format(_NOT_A_WAVEFORM) is None
    assert WH.sniff_format(b"") is None


def test_a_truncated_fst_zwrapper_is_not_accepted():
    """The reader treats a zero section length as "not finished compressing,
    this is a failed read". So does this: a half-written repack is not a
    confirmed FST, and it lands in UNDETERMINED under its own name rather
    than being waved through."""
    truncated = b"\xfe" + b"\x00" * 8 + (560).to_bytes(8, "big") + b"\x1f\x8b"
    assert WH.sniff_format(truncated) is None


def test_audit_findings_carry_their_state(tmp_path):
    """`audit()` returns Findings, not paths: a caller asserting
    `findings == []` is asserting the tree is CLEAN, not that nothing was
    named like a waveform."""
    (tmp_path / "real.vcd").write_bytes(_VCD_NAMED_FST)
    (tmp_path / "hollow.fst").write_bytes(b"")
    findings, examined = WH.audit(str(tmp_path))
    assert examined == 2
    by_state = {f.state for f in findings}
    assert by_state == {WH.WAVEFORM, WH.UNDETERMINED}


def test_head_read_is_bounded(tmp_path):
    """A gate that walks a repo must not read a 3 GB dump to classify it."""
    assert WH.HEAD_BYTES <= 4096
    big = tmp_path / "big.vcd"
    big.write_bytes(_VCD_NAMED_FST + b"#1\n" * 200000)
    assert WH.classify(big)[0] == WH.WAVEFORM
