"""#559 — `oe_pattern_check` read nothing and exited 0.

    $ oe_pattern_check.py --rtl-files /absent.v --out-dir /tmp
    WARNING: file not found: /absent.v
    oe_pattern_check: analyzed 0 file(s), found 0 OE signal(s)
    rc=0

The missing file was WARNed and skipped, and the verdict was
`1 if high_count > 0 else 0` — so a run whose entire `--rtl-files` list was
unreadable exits with the same code as a real scan that found nothing.

THE THIRD INSTANCE OF ONE SHAPE, and the pattern is worth stating because the
three differ in what was already right:

    interface_encoding_audit  printed ERROR, said `0 interfaces analyzed`, rc 0
    fpga_qsf_lint             printed ERROR, said nothing about scope,     rc 1
    oe_pattern_check          printed WARNING, said `analyzed 0 file(s)`,  rc 0

All three DISCLOSED their denominator (`fpga_qsf_lint` only after v1.8.86), and
all three returned a verdict anyway. `gate_discloses_denominator_check` audits
493 gates for the disclosure and passes all of them, correctly — its contract is
"a PASS must say how much it looked at". Refusing on a zero denominator is a
different property, and it is enforced nowhere; each of these was found by
probing one gate at a time.

The boundary asserted below: an EMPTY file is not a MISSING one. An empty file
was opened and read, so `analyzed 1 file(s), found 0 OE signals` is a real
result and rc 0 is correct there.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
PROG = _PROGRAMS / "oe_pattern_check.py"

TRISTATE_RTL = """\
module m(inout wire io, input wire oe, input wire d);
  assign io = oe ? d : 1'bz;
endmodule
"""


def _run(files, out_dir):
    return subprocess.run(
        [sys.executable, str(PROG), "--rtl-files", *[str(f) for f in files],
         "--out-dir", str(out_dir)],
        capture_output=True, text=True, timeout=45)


def test_no_readable_file_is_not_a_pass(tmp_path):
    proc = _run([tmp_path / "absent.v"], tmp_path)
    assert proc.returncode == 2, (
        f"a run that read nothing exited {proc.returncode}; a caller reading "
        f"the exit code cannot tell that from a clean scan")
    assert "VACUOUS_PASS" in proc.stderr


def test_all_files_missing_is_not_a_pass(tmp_path):
    """More than one path, none of them readable — the count must be honest."""
    proc = _run([tmp_path / "a.v", tmp_path / "b.v", tmp_path / "c.v"], tmp_path)
    assert proc.returncode == 2
    assert "3 path(s)" in proc.stderr, proc.stderr


def test_empty_file_is_a_real_scan(tmp_path):
    """The boundary. An empty file was opened; that is a result, not a gap."""
    f = tmp_path / "e.v"
    f.write_text("", encoding="utf-8")
    proc = _run([f], tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "analyzed 1 file" in proc.stdout
    assert "VACUOUS_PASS" not in proc.stderr


def test_a_real_finding_still_fails(tmp_path):
    """The accept/reject boundary in the other direction.

    Every change here makes the gate refuse more; without this a program that
    refused everything would satisfy the tests above.
    """
    f = tmp_path / "m.v"
    f.write_text(TRISTATE_RTL, encoding="utf-8")
    proc = _run([f], tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "found 1 OE signal" in proc.stdout


def test_partial_readability_still_reports(tmp_path):
    """One readable file among missing ones is a scan, not a vacuum.

    Refusing here would lose a real result over an unrelated bad path.
    """
    good = tmp_path / "m.v"
    good.write_text(TRISTATE_RTL, encoding="utf-8")
    proc = _run([tmp_path / "gone.v", good], tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "analyzed 1 file" in proc.stdout
    assert "VACUOUS_PASS" not in proc.stderr


def test_json_report_names_the_files_it_read(tmp_path):
    """The JSON denominator, checked against a known input rather than for
    mere presence — a key that is always non-empty proves nothing."""
    a = tmp_path / "m.v"
    a.write_text(TRISTATE_RTL, encoding="utf-8")
    b = tmp_path / "n.v"
    b.write_text("module n(input wire c);\nendmodule\n", encoding="utf-8")
    _run([tmp_path / "gone.v", a, b], tmp_path)
    doc = json.loads((tmp_path / "oe_pattern_report.json").read_text(encoding="utf-8"))
    assert len(doc["files_analyzed"]) == 2, doc["files_analyzed"]
    assert str(tmp_path / "gone.v") not in doc["files_analyzed"], doc
