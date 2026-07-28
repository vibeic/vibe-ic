"""Unit tests for fmeda_fault_injection_coverage.py + fmeda_coverage_check.py —
the FMEDA fault-injection diagnostic-coverage engine (pure helpers only; the
iverilog injection run itself is exercised separately against the synthetic
Hamming fixture and is not needed here).

Pins:
  * DC math, ASIL-floor resolution, and verdict logic.
  * injection-transcript parsing incl. the false-alarm / non-inverse BASELINE
    guard (a bogus baseline must invalidate the measurement, never pass).
  * Injection.covered = detect OR match; per-site collapse.
  * deterministic stimulus generation (sweep-small / bounded-large).
  * mechanism auto-detect finds an ECC enc/dec pair AND SKIPs a non-safety
    design (NOT_APPLICABLE — never a fake pass).
  * build_report NOT_APPLICABLE + invalid-baseline FAIL + PASS/FAIL verdict.
  * the independent gate recomputes the verdict and CATCHES a fabricated PASS.
"""
import json
import sys
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))
import fmeda_fault_injection_coverage as fi          # noqa: E402
import fmeda_coverage_check as gate                  # noqa: E402


# ── DC math ──────────────────────────────────────────────────────────────
def test_compute_dc_basic():
    assert fi.compute_dc(96, 112) == 96 * 100.0 / 112
    assert fi.compute_dc(112, 112) == 100.0
    assert fi.compute_dc(0, 10) == 0.0


def test_compute_dc_zero_injected_is_zero_not_full():
    # No evidence must NEVER read as full coverage.
    assert fi.compute_dc(0, 0) == 0.0
    assert fi.compute_dc(5, 0) == 0.0


# ── ASIL floors ────────────────────────────────────────────────────────────
def test_asil_floor_bands():
    assert fi.asil_floor("B") == 90.0
    assert fi.asil_floor("C") == 97.0
    assert fi.asil_floor("D") == 99.0
    assert fi.asil_floor("A") is None       # advisory
    assert fi.asil_floor("QM") is None
    assert fi.asil_floor("d") == 99.0       # case-insensitive


def test_asil_floor_override_wins():
    assert fi.asil_floor("D", 80.0) == 80.0
    assert fi.asil_floor("A", 95.0) == 95.0  # override even when band is None


def test_dc_verdict():
    assert fi.dc_verdict(99.0, 99.0)[0] is True
    assert fi.dc_verdict(98.99, 99.0)[0] is False
    assert fi.dc_verdict(100.0, 99.0)[0] is True
    # None floor → advisory pass
    ok, reason = fi.dc_verdict(12.3, None)
    assert ok is True and "advisory" in reason


# ── transcript parsing + baseline guard ────────────────────────────────────
_GOOD = """\
GOLDEN DATA 0 DETECT 0 MATCH 1
FAULT d0_b0 DETECT 1 MATCH 1
FAULT d0_b1 DETECT 1 MATCH 1
GOLDEN DATA 1 DETECT 0 MATCH 1
FAULT d1_b0 DETECT 0 MATCH 1
FAULT d1_b1 DETECT 0 MATCH 0
"""


def test_parse_good_transcript():
    r = fi.parse_injection_results(_GOOD)
    assert r.golden_ok is True
    assert r.golden_count == 2
    assert r.injected == 4
    # covered = detect OR match: b0/b0/b0 covered, last (0,0) is an ESCAPE
    assert r.detected == 3
    assert abs(r.dc_pct - 75.0) < 1e-9


def test_parse_false_alarm_baseline_invalid():
    bad = "GOLDEN DATA 0 DETECT 1 MATCH 1\nFAULT d0_b0 DETECT 1 MATCH 1\n"
    r = fi.parse_injection_results(bad)
    assert r.golden_ok is False
    assert any("FALSE-ALARM" in n for n in r.baseline_notes)


def test_parse_non_inverse_baseline_invalid():
    bad = "GOLDEN DATA 0 DETECT 0 MATCH 0\nFAULT d0_b0 DETECT 1 MATCH 1\n"
    r = fi.parse_injection_results(bad)
    assert r.golden_ok is False


def test_parse_no_baseline_invalid():
    r = fi.parse_injection_results("FAULT d0_b0 DETECT 1 MATCH 1\n")
    assert r.golden_ok is False
    assert r.injected == 1


def test_injection_covered_logic():
    assert fi.Injection("x", True, False).covered is True    # flagged
    assert fi.Injection("x", False, True).covered is True    # corrected
    assert fi.Injection("x", True, True).covered is True
    assert fi.Injection("x", False, False).covered is False  # escape


def test_per_site_collapse():
    r = fi.parse_injection_results(_GOOD)
    cov, tot = r.per_site()
    assert tot == 2                # sites b0, b1
    assert cov == 2                # b0 covered by both data; b1 covered by d0


def test_per_site_escape():
    # b1 undetected across ALL its stimulus → uncovered site.
    txt = ("GOLDEN DATA 0 DETECT 0 MATCH 1\n"
           "FAULT d0_b0 DETECT 1 MATCH 1\nFAULT d0_b1 DETECT 0 MATCH 0\n"
           "GOLDEN DATA 1 DETECT 0 MATCH 1\n"
           "FAULT d1_b0 DETECT 1 MATCH 1\nFAULT d1_b1 DETECT 0 MATCH 0\n")
    r = fi.parse_injection_results(txt)
    cov, tot = r.per_site()
    assert (cov, tot) == (1, 2)    # only b0 covered


# ── stimulus generation ────────────────────────────────────────────────────
def test_stimulus_sweep_small():
    assert fi._stimulus_values(4) == list(range(16))       # 16 <= 64 → full sweep


def test_stimulus_bounded_large_deterministic():
    a = fi._stimulus_values(16, max_vectors=32)
    b = fi._stimulus_values(16, max_vectors=32)
    assert len(a) == 32 and a == b                          # deterministic
    assert all(0 <= v < (1 << 16) for v in a)
    assert len(set(a)) == 32                                # unique


# ── mechanism auto-detect ──────────────────────────────────────────────────
_ENC = """module ham_enc(input [3:0] data_in, output [6:0] code_out);
assign code_out[2]=data_in[0]; assign code_out[4]=data_in[1];
assign code_out[5]=data_in[2]; assign code_out[6]=data_in[3];
assign code_out[0]=data_in[0]^data_in[1]^data_in[3];
assign code_out[1]=data_in[0]^data_in[2]^data_in[3];
assign code_out[3]=data_in[1]^data_in[2]^data_in[3]; endmodule
"""
_DEC = """module ham_dec(input [6:0] code_in, output [3:0] data_out, output syndrome_err);
wire s0=code_in[0]^code_in[2]^code_in[4]^code_in[6];
wire s1=code_in[1]^code_in[2]^code_in[5]^code_in[6];
wire s2=code_in[3]^code_in[4]^code_in[5]^code_in[6];
assign data_out=code_in[3:0]; assign syndrome_err=s0|s1|s2; endmodule
"""


def test_detect_mechanism_finds_ecc_pair(tmp_path):
    d = tmp_path / "rtl"
    d.mkdir()
    (d / "enc.v").write_text(_ENC)
    (d / "dec.v").write_text(_DEC)
    spec = fi.detect_safety_mechanism(d)
    assert spec is not None
    assert spec.enc_module == "ham_enc"
    assert spec.dec_module == "ham_dec"
    assert spec.detect_port == "syndrome_err"
    assert spec.dec_out == "data_out"
    assert spec.data_width == 4 and spec.code_width == 7


def test_detect_mechanism_skips_non_safety(tmp_path):
    d = tmp_path / "rtl"
    d.mkdir()
    (d / "adder.v").write_text(
        "module adder(input [7:0] a, input [7:0] b, output [8:0] s);"
        " assign s=a+b; endmodule\n")
    assert fi.detect_safety_mechanism(d) is None   # NOT_APPLICABLE, never fake


def test_detect_mechanism_empty_dir(tmp_path):
    assert fi.detect_safety_mechanism(tmp_path) is None


# ── TB rendering ────────────────────────────────────────────────────────────
def _spec(**kw):
    base = dict(kind="ecc", enc_module="e", enc_in="di", enc_out="co",
                dec_module="d", dec_in="ci", dec_out="do", detect_port="err",
                data_width=4, code_width=7, rtl_files=[], source="explicit")
    base.update(kw)
    return fi.MechanismSpec(**base)


def test_build_tb_emits_expected_lines():
    tb = fi.build_ecc_injection_tb(_spec(), max_vectors=64)
    assert "module fmeda_fi_tb" in tb
    assert "GOLDEN DATA" in tb and "FAULT d" in tb
    assert "faulted = code ^ (1'b1 << i)" in tb
    assert "e u_enc" in tb and "d u_dec" in tb
    # 16 stimulus values swept (K=4)
    assert tb.count("tv[") >= 16


def test_build_tb_requires_encoder():
    try:
        fi.build_ecc_injection_tb(_spec(enc_module=None))
        assert False, "expected ValueError"
    except ValueError:
        pass


# ── report assembly ─────────────────────────────────────────────────────────
def test_build_report_not_applicable():
    rep = fi.build_report(None, None, "D", 99.0)
    assert rep["applicable"] is False
    assert rep["verdict"] == "NOT_APPLICABLE"


def test_build_report_invalid_baseline_fails():
    r = fi.parse_injection_results("GOLDEN DATA 0 DETECT 1 MATCH 1\n"
                                   "FAULT d0_b0 DETECT 1 MATCH 1\n")
    rep = fi.build_report(_spec(), r, "D", 99.0)
    assert rep["baseline_valid"] is False
    assert rep["verdict"] == "FAIL"        # bogus baseline is never a pass


def test_build_report_pass_and_fail():
    good = fi.parse_injection_results(
        "GOLDEN DATA 0 DETECT 0 MATCH 1\nFAULT d0_b0 DETECT 1 MATCH 1\n")
    rep = fi.build_report(_spec(), good, "D", 99.0)
    assert rep["verdict"] == "PASS" and rep["diagnostic_coverage_pct"] == 100.0
    weak = fi.parse_injection_results(
        "GOLDEN DATA 0 DETECT 0 MATCH 1\n"
        "FAULT d0_b0 DETECT 1 MATCH 1\nFAULT d0_b1 DETECT 0 MATCH 0\n")
    rep2 = fi.build_report(_spec(), weak, "D", 99.0)
    assert rep2["verdict"] == "FAIL" and rep2["diagnostic_coverage_pct"] == 50.0


# ── independent recompute gate ───────────────────────────────────────────────
def test_gate_vacuous_on_not_applicable():
    res = gate.check({"applicable": False, "reason": "n/a"}, None, None)
    assert res["passed"] is True and res["verdict"] == "VACUOUS_PASS"


def test_gate_recomputes_pass():
    rep = {"applicable": True, "asil": "D", "injected_faults": 112,
           "detected_faults": 112, "baseline_valid": True, "verdict": "PASS"}
    res = gate.check(rep, None, None)
    assert res["passed"] is True and res["recomputed_dc_pct"] == 100.0


def test_gate_catches_fabricated_pass():
    # report LIES verdict=PASS while its own counts say 85.7% < 99% floor.
    rep = {"applicable": True, "asil": "D", "injected_faults": 112,
           "detected_faults": 96, "baseline_valid": True, "verdict": "PASS"}
    res = gate.check(rep, None, None)
    assert res["passed"] is False
    assert res["fabricated_verdict_detected"] is True
    assert "FABRICATED" in res["reason"]


def test_gate_fails_invalid_baseline_even_if_dc_high():
    rep = {"applicable": True, "asil": "D", "injected_faults": 112,
           "detected_faults": 112, "baseline_valid": False, "verdict": "PASS"}
    res = gate.check(rep, None, None)
    assert res["passed"] is False


def test_gate_zero_injected_fails():
    rep = {"applicable": True, "asil": "D", "injected_faults": 0,
           "detected_faults": 0, "baseline_valid": True, "verdict": "PASS"}
    res = gate.check(rep, None, None)
    assert res["passed"] is False


# ── END-TO-END: the DIAGNOSTIC-COVERAGE VERDICT ITSELF ───────────────────
# Everything above pins helpers. None of it drives `run()`, so the comparison
# this program exists to make — measured DC against the ASIL floor — was
# unfalsified by the whole suite: no test built RTL declaring a mechanism and
# ran the real injection. The three below do, through `run()`, with iverilog.
# Together they are the both-directions pair the DC verdict needs.

_DEC_OK = """module ham_dec(input [6:0] code_in, output [3:0] data_out, output syndrome_err);
wire s0=code_in[0]^code_in[2]^code_in[4]^code_in[6];
wire s1=code_in[1]^code_in[2]^code_in[5]^code_in[6];
wire s2=code_in[3]^code_in[4]^code_in[5]^code_in[6];
assign data_out={code_in[6],code_in[5],code_in[4],code_in[2]};
assign syndrome_err=s0|s1|s2; endmodule
"""
#: Same ports, same detection NAME — and the detect flag wired to a constant.
#: A single-bit flip is neither detected nor corrected, so DC collapses. This
#: is the defect the ASIL floor exists to catch, and it is invisible to every
#: structural check: the module still looks like an ECC decoder.
_DEC_BLIND = """module ham_dec(input [6:0] code_in, output [3:0] data_out, output syndrome_err);
assign data_out={code_in[6],code_in[5],code_in[4],code_in[2]};
assign syndrome_err=1'b0; endmodule
"""


class _Args:
    """The `run()` argument surface, spelled out rather than argparse-parsed."""

    def __init__(self, rtl_dir="phase2/stage1/rtl", asil="D"):
        self.rtl_dir = rtl_dir
        self.doc = None
        self.enc_module = self.dec_module = None
        self.enc_in = "data_in"
        self.enc_out = "code_out"
        self.dec_in = "code_in"
        self.dec_out = None
        self.detect_port = None
        self.data_width = 4
        self.code_width = 7
        self.rtl_file = []
        self.asil = asil
        self.min_dc = None
        self.max_vectors = 64
        self.timeout = 300
        self.json = None


def _ecc_project(tmp_path: Path, dec_body: str) -> Path:
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "enc.v").write_text(_ENC)
    (rtl / "dec.v").write_text(dec_body)
    return tmp_path


def _iverilog_available() -> bool:
    import shutil as _sh
    return _sh.which("iverilog") is not None and _sh.which("vvp") is not None


def test_dc_below_the_asil_floor_is_a_real_non_zero_exit(tmp_path):
    """FALSIFIABILITY. A decoder whose detect port is tied low: every injected
    single-bit fault escapes, DC lands far below the ASIL-D floor, and `run()`
    returns a NON-ZERO exit with the measured numbers in its report.

    Without this the FAIL arm of the DC comparison was undriveable by the whole
    suite, and the only non-zero exit anyone could produce from this program
    was an argument-validation one.
    """
    if not _iverilog_available():
        import pytest
        pytest.skip("iverilog/vvp not installed — the injection cannot run")
    project = _ecc_project(tmp_path, _DEC_BLIND)
    rc, rep = fi.run(project, _Args())
    assert rep["applicable"] is True, rep
    assert rep["baseline_valid"] is True, rep
    assert rep["injected_faults"] > 0, rep
    assert rep["diagnostic_coverage_pct"] < rep["dc_floor_pct"], rep
    assert rep["verdict"] == "FAIL", rep
    assert rc == 1, rep


def test_dc_at_or_above_the_asil_floor_is_a_measured_pass(tmp_path):
    """NO FALSE ALARM, and the control that stops the test above from being
    satisfied by "this program always FAILs". The SAME fixture with a WORKING
    syndrome check measures DC >= the floor and exits 0 — and its report says
    `applicable: true`, so this is a MEASURED pass, not the vacuous one a
    non-safety design gets.
    """
    if not _iverilog_available():
        import pytest
        pytest.skip("iverilog/vvp not installed — the injection cannot run")
    project = _ecc_project(tmp_path, _DEC_OK)
    rc, rep = fi.run(project, _Args())
    assert rep["applicable"] is True, rep
    assert rep["baseline_valid"] is True, rep
    assert rep["diagnostic_coverage_pct"] >= rep["dc_floor_pct"], rep
    assert rep["verdict"] == "PASS", rep
    assert rc == 0, rep


def test_the_floor_itself_is_load_bearing(tmp_path):
    """The comparison is against the FLOOR, not against a constant. The blind
    decoder still measures some coverage (a flip in a data bit changes the
    decoded word even with no syndrome), so relaxing the floor below what it
    measures must turn the SAME run green — otherwise `dc_floor_pct` is
    decorative and the verdict is hard-coded.
    """
    if not _iverilog_available():
        import pytest
        pytest.skip("iverilog/vvp not installed — the injection cannot run")
    project = _ecc_project(tmp_path, _DEC_BLIND)
    strict = _Args()
    rc_strict, rep_strict = fi.run(project, strict)
    assert rc_strict == 1, rep_strict

    relaxed = _Args()
    relaxed.min_dc = 0.0
    rc_relaxed, rep_relaxed = fi.run(project, relaxed)
    assert rep_relaxed["dc_floor_pct"] == 0.0, rep_relaxed
    assert (rep_relaxed["diagnostic_coverage_pct"]
            == rep_strict["diagnostic_coverage_pct"]), (
        "the same RTL measured a different DC — the measurement is not "
        "deterministic and neither verdict means anything")
    assert rep_relaxed["verdict"] == "PASS", rep_relaxed
    assert rc_relaxed == 0, rep_relaxed


# ── the two INPUT-SHAPE arms, kept apart on purpose ─────────────────────
def test_absent_rtl_dir_is_a_non_zero_exit(tmp_path):
    """`--rtl-dir` names a path that is not there: nothing was opened, so
    nothing may be claimed. NOT reachable through the flow (FS1's condition
    requires the directory), so it never false-alarms a real run.
    """
    rc, rep = fi.run(tmp_path, _Args())
    assert rc == 1, rep
    assert rep["verdict"] == "FAIL", rep
    assert rep["measurable"] is False, rep
    assert "does not exist" in rep["reason"], rep


def test_source_free_rtl_dir_is_a_disclosed_vacuous_pass_not_a_fail(tmp_path):
    """NO FALSE ALARM. The directory exists and holds no Verilog: the safety
    sign-off must NOT be the step that hard-FAILs on missing RTL — that is a
    precondition of the whole flow, owned by the RTL and synthesis steps.

    But it must also NOT answer NOT_APPLICABLE, which would assert a design
    shape read off an unopened input. The verdict is its own, it is not
    measurable, and it records that zero sources were read.
    """
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    rc, rep = fi.run(tmp_path, _Args())
    assert rc == 0, rep
    assert rep["verdict"] == "UNMEASURED_NO_RTL_READ", rep
    assert rep["verdict"] != "NOT_APPLICABLE"
    assert rep["measurable"] is False, rep
    assert rep["rtl_sources_read"] == 0, rep
    assert rep["applicable"] is False, rep


def test_rtl_with_no_mechanism_keeps_its_honest_not_applicable(tmp_path):
    """The control for the test above: RTL that WAS read and declares no
    safety mechanism still answers NOT_APPLICABLE. The two must not collapse
    into one verdict, or the disclosure carries no information.
    """
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "adder.v").write_text(
        "module adder(input [7:0] a, input [7:0] b, output [8:0] s);"
        " assign s=a+b; endmodule\n")
    rc, rep = fi.run(tmp_path, _Args())
    assert rc == 0, rep
    assert rep["verdict"] == "NOT_APPLICABLE", rep


def test_the_vacuous_token_line_survives_the_consumers_stdout_window(tmp_path):
    """The disclosure is only a disclosure if the consumer can see it.
    `flow_compliance_check._check_program_exit_zero` reads `stdout[-300:]` and
    matches `VACUOUS_PASS` at LINE START, so a token printed AHEAD of a long
    reason is sliced mid-line and the step silently reverts to the plain PASS
    bucket. Measured on `UNMEASURED_NO_RTL_READ`, whose reason is longer than
    the window.
    """
    import subprocess
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    proc = subprocess.run(
        [sys.executable, str(PROG_DIR / "fmeda_fault_injection_coverage.py"),
         str(tmp_path), "--rtl-dir", "phase2/stage1/rtl", "--asil", "D",
         "--json", str(tmp_path / "r.json")],
        capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    window = (proc.stdout[-300:] + "\n" + proc.stderr[-300:]).strip()
    assert any(ln.lstrip().startswith("VACUOUS_PASS")
               for ln in window.splitlines()), (
        "the VACUOUS_PASS token did not survive the consumer's 300-char "
        f"window:\n{window}")
