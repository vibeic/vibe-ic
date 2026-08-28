#!/usr/bin/env python3
"""ORGANIC #700 — independent differential self-verification (N-version) for
blind RTL authoring: `programs/diff_verify_harness.py`.

A single agent that derives BOTH the RTL and its self-TB from ONE reading of
the spec passes its own (possibly wrong) TB — circular. A SECOND independent
reference, cross-checked against the RTL every cycle, surfaces an OVERSIGHT
misread as a designer-vs-reference DIFF.

Tests
=====
POSITIVE
  * 驗收 VERBATIM — a correct exactly-2-cycle delay RTL vs an independent
    `[0,0]+seq[:-2]` reference → AGREE, rc 0 (the live-iverilog run is gated on
    `shutil.which`; SKIPped when the tool is absent so CI is portable).
  * WRONG-delay catch — a 1-cycle-delay RTL vs the 2-cycle reference → MISMATCH,
    rc 1, with the first diverging cycle/signal (the oversight-catch).
  * Pure-logic path — the vector generator + per-cycle comparator are exercised
    WITHOUT iverilog so CI ALWAYS covers the differential comparator.

§4.05 NEGATIVE / NO-LEAK
  * iverilog ABSENT → SKIP with disclosure, NEVER a faked AGREE (rc 0, stdout
    is `SKIP:` not `AGREE`); `--require-tools` turns it into a hard ERROR (rc 2).
  * the harness reads ONLY rtl + ref + generated vectors — no oracle / hidden
    TB / dataset (asserted on the source + the report's `reads_only`).
  * the HONEST scope is stated — the program states it catches OVERSIGHT not
    genuine-ambiguity and does NOT claim to beat the #697 FLOOR (asserted on the
    docstring + every report dict).

chip-AGNOSTIC: structural module/port parse + iverilog drive + integer compare;
no chip/SKU literal (enforced by source_chip_agnostic_check).
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = Path(__file__).resolve().parents[1]
_PROG = _PROGRAMS / "diff_verify_harness.py"
_PLUGIN_ROOT = _PROGRAMS.parent

_spec = importlib.util.spec_from_file_location("diff_verify_harness", str(_PROG))
dvh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dvh)

_HAVE_IVERILOG = (shutil.which("iverilog") is not None
                  and shutil.which("vvp") is not None)

# the 驗收 fixtures, verbatim
_RTL_2CYC = ("module dut(input clk,input [7:0] in,output reg [7:0] out); "
             "reg [7:0] r; always @(posedge clk) begin r<=in; out<=r; end "
             "endmodule\n")
_RTL_1CYC = ("module dut(input clk,input [7:0] in,output reg [7:0] out); "
             "always @(posedge clk) out<=in; endmodule\n")
_REF_2CYC = "def ref(seq): return [0,0]+seq[:-2]\n"


def _write(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body)
    return p


def _run_cli(args):
    r = _pr.run([sys.executable, str(_PROG), *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


# ── POSITIVE ─────────────────────────────────────────────────────────────────
@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_acceptance_verbatim_2cycle_AGREE_rc0(tmp_path):
    """驗收 VERBATIM — correct 2-cycle delay vs independent 2-cycle ref →
    AGREE, rc 0."""
    rtl = _write(tmp_path, "rtl.sv", _RTL_2CYC)
    ref = _write(tmp_path, "ref.py", _REF_2CYC)
    rc, out, err = _run_cli(["--rtl", str(rtl), "--ref", str(ref),
                             "--top", "dut", "--vectors", "random"])
    assert rc == 0, f"expected AGREE rc=0, got rc={rc}\nout={out}\nerr={err}"
    assert "AGREE" in out
    # and it must NOT be a faked AGREE from a SKIP
    assert "SKIP" not in out


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_wrong_1cycle_delay_MISMATCH_rc1(tmp_path):
    """Oversight-catch — a 1-cycle-delay RTL vs the 2-cycle reference → MISMATCH
    rc 1, first diverging cycle/signal reported."""
    rtl = _write(tmp_path, "rtl.sv", _RTL_1CYC)
    ref = _write(tmp_path, "ref.py", _REF_2CYC)
    rc, out, err = _run_cli(["--rtl", str(rtl), "--ref", str(ref),
                             "--top", "dut", "--vectors", "directed"])
    assert rc == 1, f"expected MISMATCH rc=1, got rc={rc}\nout={out}\nerr={err}"
    assert "MISMATCH" in out
    assert "cycle=" in out and "signal=" in out


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp not installed")
def test_acceptance_via_api_report_AGREE(tmp_path):
    """API-level 驗收 — the report dict verdict is AGREE and carries the honest
    scope fields."""
    rtl = _write(tmp_path, "rtl.sv", _RTL_2CYC)
    ref = _write(tmp_path, "ref.py", _REF_2CYC)
    rep = dvh.diff_verify(rtl, ref, "dut", "directed+random+boundary", 16, 0)
    assert rep["verdict"] == "AGREE", rep
    assert rep["driven_input"]["name"] == "in"
    assert rep["sampled_output"]["name"] == "out"
    assert rep["clk"] == "clk"


# ── PURE-LOGIC path (always CI-covered, no iverilog needed) ──────────────────
def test_port_parse_pure_logic():
    """Port header parse is iverilog-free — clk/data-in/data-out classified."""
    name, ports, err = dvh.parse_ports(_RTL_2CYC, "dut")
    assert name == "dut" and err == ""
    clk, resets, din, dout = dvh._classify_ports(ports)
    assert clk is not None and clk.name == "clk"
    assert [p.name for p in din] == ["in"]
    assert [p.name for p in dout] == ["out"]
    assert din[0].width == 8 and dout[0].width == 8


def test_vector_generation_deterministic():
    """Vector generation is deterministic for a given seed; all three kinds and
    a combination are honoured."""
    a = dvh.gen_vectors(["random"], 8, 16, seed=0)
    b = dvh.gen_vectors(["random"], 8, 16, seed=0)
    assert a == b, "random vectors must be seed-deterministic"
    c = dvh.gen_vectors(["random"], 8, 16, seed=1)
    assert a != c, "different seed → different vectors"
    boundary = dvh.gen_vectors(["boundary"], 8, 8, seed=0)
    assert [0] * 8 in boundary and [255] * 8 in boundary
    combo = dvh.gen_vectors(["directed", "random", "boundary"], 8, 4, seed=0)
    assert len(combo) > len(dvh.gen_vectors(["random"], 8, 4, seed=0))


def test_comparator_pure_logic_first_mismatch():
    """The per-cycle comparator (iverilog-free) reports the FIRST divergence."""
    agree, mm = dvh.compare_sequences([0, 0, 1, 2], [0, 0, 1, 2], "out")
    assert agree and mm is None
    agree, mm = dvh.compare_sequences([0, 1, 9, 3], [0, 1, 2, 3], "out")
    assert not agree
    assert mm == {"cycle": 2, "signal": "out", "rtl": 9, "ref": 2}


def test_reference_load_requires_callable_ref(tmp_path):
    """A --ref module without a callable ref(seq) is rejected (not silently
    passed)."""
    bad = _write(tmp_path, "bad.py", "x = 1\n")
    with pytest.raises(ValueError):
        dvh.load_reference(bad)
    good = _write(tmp_path, "good.py", _REF_2CYC)
    ref = dvh.load_reference(good)
    assert ref([0, 1, 2, 3]) == [0, 0, 0, 1]


# ── §4.05 NEGATIVE / NO-LEAK ─────────────────────────────────────────────────
def test_iverilog_absent_SKIP_never_fakes_AGREE(tmp_path, monkeypatch):
    """iverilog ABSENT → SKIP with disclosure, NEVER a faked AGREE (rc 0)."""
    rtl = _write(tmp_path, "rtl.sv", _RTL_2CYC)
    ref = _write(tmp_path, "ref.py", _REF_2CYC)
    _orig = shutil.which
    monkeypatch.setattr(
        dvh.shutil, "which",
        lambda n, *a, **k: None if n in ("iverilog", "vvp")
        else _orig(n, *a, **k))
    rep = dvh.diff_verify(rtl, ref, "dut", "random", 16, 0)
    assert rep["verdict"] == "SKIP", rep
    assert rep["verdict"] != "AGREE"           # the critical no-fake assertion
    assert rep["tool_available"] is False
    assert "not a faked AGREE" in rep["reason"].lower() or \
           "refuse-don't-fake" in rep["reason"].lower()


def test_iverilog_absent_cli_prints_SKIP_not_AGREE(tmp_path):
    """CLI-level: under a shadowed PATH the program prints `SKIP:` (rc 0), never
    `AGREE`. Done via the module API with a monkeypatched which to keep the
    Python interpreter reachable."""
    rtl = _write(tmp_path, "rtl.sv", _RTL_2CYC)
    ref = _write(tmp_path, "ref.py", _REF_2CYC)
    import io
    import contextlib
    _orig = shutil.which
    dvh.shutil.which = (lambda n, *a, **k: None if n in ("iverilog", "vvp")
                        else _orig(n, *a, **k))
    try:
        buf_out, buf_err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf_out), \
                contextlib.redirect_stderr(buf_err):
            rc = dvh.main(["--rtl", str(rtl), "--ref", str(ref),
                           "--top", "dut", "--vectors", "random"])
        assert rc == 0
        assert "AGREE" not in buf_out.getvalue()
        assert "SKIP" in buf_err.getvalue()
        # --require-tools → hard ERROR rc 2
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            rc2 = dvh.main(["--rtl", str(rtl), "--ref", str(ref),
                            "--top", "dut", "--vectors", "random",
                            "--require-tools"])
        assert rc2 == 2
    finally:
        dvh.shutil.which = _orig


def test_no_leak_reads_only_rtl_ref_vectors(tmp_path):
    """NO-LEAK — the report records that it reads ONLY rtl + independent ref +
    generated vectors (no oracle / hidden TB / dataset). The misread cannot leak
    in through the comparison because BOTH sides come from the spec-reader."""
    rtl = _write(tmp_path, "rtl.sv", _RTL_2CYC)
    ref = _write(tmp_path, "ref.py", _REF_2CYC)
    rep = dvh.diff_verify(rtl, ref, "dut", "directed", 8, 0)
    reads = rep["reads_only"].lower()
    assert "rtl" in reads and "reference" in reads and "vectors" in reads
    assert "no oracle" in reads and "hidden tb" in reads and "dataset" in reads
    # the program opens ONLY the rtl (read_text) + ref (load_reference) + a
    # generated TB under a tempdir — it has NO dataset/oracle ACCESS path: no
    # glob/scandir/listdir over an external corpus, no dataset env var.
    src = _PROG.read_text()
    for forbidden in (".glob(", ".rglob(", ".iterdir(", "os.scandir",
                      "os.listdir", "os.environ", "getenv"):
        assert forbidden not in src, \
            f"diff_verify_harness must not access a corpus via {forbidden!r}"


def test_honest_scope_stated_not_silver_bullet():
    """HONEST scope — the program states it catches OVERSIGHT misreads, NOT
    genuine ambiguity, and does NOT claim to beat the #697 FLOOR. Asserted on
    BOTH the docstring and every report dict."""
    doc = (dvh.__doc__ or "").lower()
    assert "oversight" in doc
    assert "ambiguity" in doc and "floor" in doc
    assert "complement" in doc
    assert "#697" in (dvh.__doc__ or "")          # cross-references the floor
    # every report carries the honest scope fields
    rtl = Path(__file__).parent  # any path; we only need a report shape
    # build a report via a real (cheap) parse to get the scope keys
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        rp = Path(d) / "r.sv"
        rp.write_text(_RTL_2CYC)
        fp = Path(d) / "f.py"
        fp.write_text(_REF_2CYC)
        # force the SKIP shape (no tool) so this assertion runs without iverilog
        _orig = shutil.which
        dvh.shutil.which = lambda n, *a, **k: None if n in ("iverilog", "vvp") \
            else _orig(n, *a, **k)
        try:
            rep = dvh.diff_verify(rp, fp, "dut", "directed", 8, 0)
        finally:
            dvh.shutil.which = _orig
    assert "oversight" in rep["catches"].lower()
    assert "ambiguity" in rep["does_not_catch"].lower()
    assert "floor" in rep["does_not_catch"].lower()
    assert any("#697" in c for c in rep["complement_to"])


def test_bad_inputs_rc2(tmp_path):
    """Bad --vectors / missing files → rc 2 (bad input), never a silent pass."""
    rtl = _write(tmp_path, "rtl.sv", _RTL_2CYC)
    ref = _write(tmp_path, "ref.py", _REF_2CYC)
    rc, _, _ = _run_cli(["--rtl", str(rtl), "--ref", str(ref),
                         "--vectors", "bogus"])
    assert rc == 2
    rc, _, _ = _run_cli(["--rtl", str(tmp_path / "nope.sv"), "--ref", str(ref)])
    assert rc == 2


# ── chip-AGNOSTIC guard ──────────────────────────────────────────────────────
def test_chip_agnostic_source_guard():
    prog = _PROGRAMS / "source_chip_agnostic_check.py"
    r = _pr.run([sys.executable, str(prog), str(_PLUGIN_ROOT)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-500:]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
