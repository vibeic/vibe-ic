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
import time
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))
import fmeda_fault_injection_coverage as fi          # noqa: E402
import fmeda_coverage_check as gate                  # noqa: E402
import ci_harness_timeout_ceiling_check as ceiling_check   # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_REPO_ROOT = ceiling_check.find_repo_root()


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


#: The `--timeout` the CI harness bounds a single test at, READ from the
#: workflows rather than restated here (vibe-ic#542). The landed version of
#: this line was `= 180`, a second copy of a value this file cannot see — the
#: drift shape #527/#530/#534 each spent a version removing. It was also
#: WRONG in a way a copy cannot notice: there are four pytest invocations
#: across two workflows and they declare two different bounds, so the binding
#: one is the minimum, which only a resolver can know.
#: None when no workflow is reachable (a standalone plugin install). The guard
#: below then SKIPs — it does not fall back to a remembered number, because a
#: remembered number is the defect.
CI_HARNESS_TIMEOUT_S = ceiling_check.ci_harness_timeout_seconds(_REPO_ROOT) \
    if _REPO_ROOT else None
#: Every inner timeout in this file. MUST stay well under the harness bound: an
#: inner bound at or above it can never fire, because the harness kills the
#: whole SESSION first — `--maxfail` stops applying, no per-test diagnostic is
#: printed, and the verdict of every other file in the subset is lost with it.
#: The landed value was 300 against a harness of 180, so the program's own
#: timeout was decoration and a stalled backend took the session down instead.
#: The real injection measures in well under a second; 60 s is ~100x headroom
#: and still leaves the harness three times the room it needs to report.
INNER_TIMEOUT_S = 60


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
        self.timeout = INNER_TIMEOUT_S
        self.json = None


def _ecc_project(tmp_path: Path, dec_body: str) -> Path:
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "enc.v").write_text(_ENC)
    (rtl / "dec.v").write_text(dec_body)
    return tmp_path


def _injection_backend_missing() -> str:
    """Empty string when a real injection can run here; else why it cannot.

    ASKS THE CODE PATH, rather than restating its conditions alongside it.
    The first version of this guard checked host `iverilog`/`vvp` — binaries
    `run()` never invoked, because the injection ran `docker run` against an
    image the guard never looked for. On a CI runner, which installs iverilog
    from apt and has no such image, the guard therefore said GO and the run
    went to the registry for 6.68 GB; it was still going when the 180 s harness
    killed the session, so the whole targeted subset reported nothing.

    `resolve_injection_backend` is the same function `run_injection_iverilog`
    dispatches on, so this guard cannot come apart from the path again: it
    skips exactly when the path would have nothing to run on.
    """
    backend, _img, reason = fi.resolve_injection_backend()
    return "" if backend != fi.BACKEND_NONE else reason


def test_dc_below_the_asil_floor_is_a_real_non_zero_exit(tmp_path):
    """FALSIFIABILITY. A decoder whose detect port is tied low: every injected
    single-bit fault escapes, DC lands far below the ASIL-D floor, and `run()`
    returns a NON-ZERO exit with the measured numbers in its report.

    Without this the FAIL arm of the DC comparison was undriveable by the whole
    suite, and the only non-zero exit anyone could produce from this program
    was an argument-validation one.
    """
    missing = _injection_backend_missing()
    if missing:
        import pytest
        pytest.skip(missing)
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
    missing = _injection_backend_missing()
    if missing:
        import pytest
        pytest.skip(missing)
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
    missing = _injection_backend_missing()
    if missing:
        import pytest
        pytest.skip(missing)
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
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    proc = _pr.run(
        [sys.executable, str(PROG_DIR / "fmeda_fault_injection_coverage.py"),
         str(tmp_path), "--rtl-dir", "phase2/stage1/rtl", "--asil", "D",
         "--json", str(tmp_path / "r.json")],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    window = (proc.stdout[-300:] + "\n" + proc.stderr[-300:]).strip()
    assert any(ln.lstrip().startswith("VACUOUS_PASS")
               for ln in window.splitlines()), (
        "the VACUOUS_PASS token did not survive the consumer's 300-char "
        f"window:\n{window}")


# ── the two defects that made this file kill the CI session ──────────────
# Both landed together and are independent: the guard checked a resource the
# code path never consumed, and the inner timeout sat at the harness bound so
# it could never fire. Either one alone still costs the whole subset's result,
# so each gets a guard that fails if it comes back.

def test_no_inner_timeout_can_outlast_the_ci_harness(tmp_path):
    """AN INNER TIMEOUT AT OR ABOVE THE HARNESS BOUND IS DECORATION.

    CI runs `pytest --timeout=180 --timeout-method=thread`. A test that permits
    a subprocess 300 s cannot ever reach its own timeout: at 180 s pytest-timeout
    kills the SESSION, `--maxfail` stops applying, no per-test diagnostic is
    printed, and every other file in the subset loses its verdict too. That is
    exactly what this file did — one stalled backend, zero reported results.

    The walk this test used to carry inline now lives in
    `ci_harness_timeout_ceiling_check` and judges the WHOLE tree (vibe-ic#542).
    This test keeps its own assertion — the file that produced the defect should
    fail on its own when it comes back, not only through a repo-wide gate a
    reader may not run — but it DELEGATES the parsing, so there is one
    implementation of the scan and one source for the bound. The inline copy
    could not see the two shapes the shared one has since grown: a bound spelled
    as a module constant, and a wrapper that forwards `**kwargs` into a
    launcher.
    """
    if CI_HARNESS_TIMEOUT_S is None:
        import pytest
        pytest.skip("no .github/workflows in reach — the harness bound cannot "
                    "be resolved, and a remembered copy of it is the defect "
                    "this test exists to prevent")
    ceiling = CI_HARNESS_TIMEOUT_S // ceiling_check.CEILING_DIVISOR
    findings, unresolved, sites = ceiling_check.scan_source(
        Path(__file__).read_text(), Path(__file__).name, ceiling)
    assert sites, "no bound was READ at all — has the scan stopped working?"
    assert not findings, (
        f"inner bound above the {ceiling}s ceiling (harness "
        f"{CI_HARNESS_TIMEOUT_S}s) — it cannot fire, and the session dies "
        "instead of the test:\n  " + "\n  ".join(str(f) for f in findings))
    assert not unresolved, (
        "a bound above the ceiling on a callee the scan cannot resolve:\n  "
        + "\n  ".join(str(u) for u in unresolved))
    assert INNER_TIMEOUT_S <= ceiling, (
        f"the inner bound needs real headroom under the harness, not merely to "
        f"be under it — the harness must have room to REPORT, and a test that "
        f"makes two bounded calls must fit twice: {INNER_TIMEOUT_S} > "
        f"{ceiling}")


def test_the_skip_guard_is_the_code_paths_own_decision(tmp_path):
    """THE GUARD MUST NOT BE ABLE TO DRIFT FROM THE PATH AGAIN.

    The landed guard asked whether host iverilog/vvp existed while `run()` went
    to `docker run`. The two answers were free to disagree, and on a CI runner
    they did: guard GO, path nothing-to-run-on, 6.68 GB of registry traffic
    inside a 180 s budget.

    So this pins the invariant rather than the implementation: whenever the
    resolver says there is NO backend, `run_injection_iverilog` must decline
    immediately — never reach a launcher — and the guard must skip. Driven
    through the real function with the resolver reporting NONE.
    """
    import time as _t
    calls = []
    orig = fi.resolve_injection_backend
    fi.resolve_injection_backend = lambda *a, **k: (
        fi.BACKEND_NONE, None, "no injection backend: forced for this test")
    orig_run = fi.subprocess.run
    fi.subprocess.run = lambda *a, **k: calls.append(a) or orig_run(*a, **k)
    try:
        # the guard the three end-to-end tests consult
        assert _injection_backend_missing() != "", (
            "resolver says NO backend but the guard would still let the "
            "injection run — the guard is not reading the path's decision")
        t0 = _t.monotonic()
        ec, out, err = fi.run_injection_iverilog(
            tmp_path, ["a.v"], "tb.v", timeout=INNER_TIMEOUT_S)
        elapsed = _t.monotonic() - t0
    finally:
        fi.resolve_injection_backend = orig
        fi.subprocess.run = orig_run
    assert ec == 127, (ec, out, err)
    assert "no injection backend" in err, err
    assert not calls, (
        "with NO backend the path still launched a subprocess — this is the "
        f"defect: {calls}")
    # THE PROPERTY, STATED STRUCTURALLY. "It declined immediately, not by
    # timing out" is `calls == []` three lines up: the ONLY way this path can be
    # slow is to launch something and wait for it, and nothing was launched. The
    # wall clock said the same thing less reliably — a busy host makes a correct
    # decline slow, and the test went red about code that was right.
    #
    # `elapsed` is kept and REPORTED, never asserted on: an observation is
    # useful in a failure message and is not a verdict.
    assert calls == [], (
        f"the decline launched {len(calls)} subprocess(es), so it was NOT the "
        f"code path's own decision — it waited for something: {calls} "
        f"(observed {elapsed:.2f}s)")


def test_the_backend_resolver_prefers_a_local_image_and_never_invents_one(
        monkeypatch):
    """The resolver's two honest answers, and the one it must not give.

    * an image the daemon already has -> use it (container-first preserved, so
      no host that works today changes behaviour);
    * no local image but host iverilog/vvp -> run on the host, which is what
      lets this file's end-to-end tests actually RUN on the CI runner rather
      than skip everywhere;
    * neither -> NONE. It must NOT fall back to the pinned ref the way
      `_resolve_docker_image` does, because that ref is precisely the 6.68 GB
      the daemon would have to fetch.
    """
    monkeypatch.delenv("VIBEIC_EDA_IMAGE", raising=False)
    monkeypatch.delenv("IIC_EDA_IMAGE", raising=False)

    monkeypatch.setattr(fi, "_local_docker_image", lambda: "an/image:local")
    monkeypatch.setattr(fi, "_host_iverilog", lambda: False)
    assert fi.resolve_injection_backend()[:2] == (fi.BACKEND_DOCKER,
                                                  "an/image:local")

    monkeypatch.setattr(fi, "_local_docker_image", lambda: None)
    monkeypatch.setattr(fi, "_host_iverilog", lambda: True)
    assert fi.resolve_injection_backend()[0] == fi.BACKEND_HOST

    monkeypatch.setattr(fi, "_host_iverilog", lambda: False)
    backend, img, reason = fi.resolve_injection_backend()
    assert backend == fi.BACKEND_NONE
    assert img is None, (
        f"resolved {img!r} with nothing available — that ref is a multi-GB "
        f"pull, which is the hang this function exists to prevent")
    assert "no injection backend" in reason


def test_local_image_probe_reports_absence_where_resolve_invents_a_pin(
        monkeypatch):
    """The distinction the whole fix rests on, pinned on ONE fake daemon.

    `_resolve_docker_image` answers "which ref would we name" and always names
    one. `_local_docker_image` answers "which ref can we run WITHOUT a pull"
    and must answer None when the daemon has nothing. Same host, opposite
    answers — and it was the first function's answer being read as the second's
    that sent CI to the registry.
    """
    monkeypatch.delenv("VIBEIC_EDA_IMAGE", raising=False)
    monkeypatch.delenv("IIC_EDA_IMAGE", raising=False)
    monkeypatch.setattr(fi.shutil, "which", lambda n: "/usr/bin/docker")

    class _Absent:
        returncode = 1        # `docker image inspect` -> not present locally

    monkeypatch.setattr(fi.subprocess, "run", lambda *a, **k: _Absent())

    # WHAT CHANGED HERE, AND WHAT DID NOT. This used to read
    # `fi._IMAGE_CANDIDATES[0]` — a pinned literal list that no longer exists,
    # because the image is now RESOLVED from the registry to a digest. The
    # PROPERTY being guarded is unchanged and is the reason this test exists:
    # one function must always name something runnable, and the other must be
    # willing to say "nothing here". Asserting the identity of the invented ref
    # would just re-pin the literal under a different name.
    # MEASURED while writing this: with the daemon holding nothing AND the
    # registry unreachable, resolve lands on the LEGACY image
    # `hpretl/iic-osic-tools:latest` and says so on stderr. That is the module's
    # documented last resort, not a defect — so this test asserts the contract
    # ("always names something runnable"), NOT a particular ref. Asserting
    # "vibeic-eda in it" here would have failed the honest fallback, and
    # asserting "never :latest" would have contradicted it: the no-floating-tag
    # rule belongs to the resolver's own happy path and is guarded there, by
    # `test_the_eda_image_is_resolved_not_remembered.py
    #  ::test_resolve_returns_a_digest_not_a_floating_tag`.
    resolved = fi._resolve_docker_image()
    assert resolved and isinstance(resolved, str), (
        f"resolve must always name a runnable ref; got {resolved!r}")
    assert fi._local_docker_image() is None                       # honest None


# ── What this gate WRITES into the project, not just what it reports ───────
#
# The gate renders its injection testbench into `phase2/stage2/safety/` and
# compiles it there, so two files under a DESIGN-round tree carry this gate's
# timestamp. Anything that dates a run by mtime has to know that, and
# `result_md_audit_provenance_check` imports `REGENERATED_PROJECT_PATHS` to
# find out — so the declaration has to be the paths the gate really writes,
# measured by RUNNING it, not a list beside the code that can drift from it.


def test_the_declared_regenerated_paths_are_the_ones_it_actually_writes(
        tmp_path):
    """Census the project around a REAL injection run.

    Every file `run()` creates outside `reports/` must be declared in
    `REGENERATED_PROJECT_PATHS`, and every declared path must actually appear.
    A stale declaration is worse than none: the freshness rule that consumes
    it would exclude a path nothing writes while still reading the one that
    moved — exactly the run-count-dependent verdict it exists to remove.
    """
    missing = _injection_backend_missing()
    if missing:
        import pytest
        pytest.skip(missing)
    project = _ecc_project(tmp_path, _DEC_OK)
    before = {str(p.relative_to(project))
              for p in project.rglob("*") if p.is_file()}
    rc, rep = fi.run(project, _Args())
    assert rep["applicable"] is True, rep      # the write path really ran
    after = {str(p.relative_to(project))
             for p in project.rglob("*") if p.is_file()}
    created = {p for p in after - before if not p.startswith("reports/")}

    assert created == set(fi.REGENERATED_PROJECT_PATHS), (
        f"the gate writes {sorted(created)} into the project but declares "
        f"{sorted(fi.REGENERATED_PROJECT_PATHS)} — a consumer that trusts the "
        f"declaration would date the run by a file this gate rewrote")


def test_a_second_run_rewrites_exactly_the_declared_paths(tmp_path):
    """…and it is a RE-write on every run, which is why it matters.

    The declaration would be harmless if the gate wrote these once. It does
    not: a second run stamps both again, which is how `phase2/` — a tree the
    freshness rule called "a design-round tree the flow never writes to" —
    carried a verdict that changed with the run count.
    """
    missing = _injection_backend_missing()
    if missing:
        import pytest
        pytest.skip(missing)
    project = _ecc_project(tmp_path, _DEC_OK)
    fi.run(project, _Args())
    stamps = {rel: (project / rel).stat().st_mtime_ns
              for rel in fi.REGENERATED_PROJECT_PATHS}
    time.sleep(0.02)
    fi.run(project, _Args())
    moved = {rel for rel, m in stamps.items()
             if (project / rel).stat().st_mtime_ns != m}
    assert moved == set(fi.REGENERATED_PROJECT_PATHS), (
        f"a re-run re-stamped {sorted(moved)}, not the declared "
        f"{sorted(fi.REGENERATED_PROJECT_PATHS)}")
