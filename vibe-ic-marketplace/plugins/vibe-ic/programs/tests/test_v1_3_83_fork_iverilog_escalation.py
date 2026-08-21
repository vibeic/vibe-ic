"""Tests for the fork-iverilog-14 SV-2012 escalation rung in score_iverilog_tb.py
(landed as v1.3.83).

Motivation: the golden `_ref.sv` of some VerilogEval problems (e.g. Prob151/156
review2015) uses an SV enum type-cast `States'(...)` that stock host iverilog 11
reject with "sorry: This cast operation is not yet supported". Because VerilogEval
compiles TB+ref+sample together, the ref's cast sinks the whole compile → the
scorer reported a false `compile_error` (and even flagged the golden as a dataset
defect). The forked iverilog 14 in the EDA container handles the cast, so the
scorer now escalates on the SV-2012 tool-gap signature and recompiles there,
stripping only the non-functional $dumpfile/$dumpvars (a fork-build forward-ref
quirk that never affects the Mismatches verdict).

§4.05 no-leak: the escalation only changes whether the COMPILE succeeds, never the
PASS/FAIL verdict — a wrong DUT still mismatches through the exact same path
(proven on Prob151: an all-zero stub reports Mismatches 4152/5069). The pure-python
helpers are unit-tested here; the docker path is gated (skips when the container or
docker is absent).
"""
import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = (Path(__file__).resolve().parents[2]
          / "benchmark" / "score_iverilog_tb.py")


def _load():
    spec = importlib.util.spec_from_file_location("score_iverilog_tb", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- _strip_waveform_dumps: removes only waveform-dump lines --------------
def test_strip_waveform_dumps_removes_dump_calls():
    m = _load()
    src = (
        "module tb;\n"
        "  initial begin\n"
        "    $dumpfile(\"wave.vcd\");\n"
        "    $dumpvars(1, tb_mismatch, clk);\n"
        "    a = 1;\n"
        "  end\n"
        "  wire tb_mismatch = ~tb_match;\n"
        "endmodule\n"
    )
    out = m._strip_waveform_dumps(src)
    assert "$dumpfile" not in out
    assert "$dumpvars" not in out
    # functional lines are preserved
    assert "a = 1;" in out
    assert "wire tb_mismatch = ~tb_match;" in out
    assert "module tb;" in out


def test_strip_waveform_dumps_keeps_display_and_finish():
    m = _load()
    src = '  $display("x");\n  $finish;\n  $dumpvars(0, tb);\n'
    out = m._strip_waveform_dumps(src)
    assert "$display" in out and "$finish" in out
    assert "$dumpvars" not in out


# ---- call-scoped strip (adversarial-verify finding on v1.3.83) -------------
def test_strip_is_call_scoped_code_sharing_dump_line_survives():
    """Reproduced verdict-flipping defect: the line-based strip deleted a TB's
    mismatch-checker forever-loop because it SHARED the $dumpvars line, so the TB
    printed 'Mismatches: 0 in 0 samples' and a WRONG DUT scored PASS through the
    fork rung. The strip must remove only the dump CALL; the checker survives."""
    m = _load()
    src = ("module tb;\n"
           "  initial begin\n"
           "    $dumpvars(0, tb); forever @(posedge clk) "
           "if (y !== in) mismatch_count = mismatch_count + 1;\n"
           "  end\n"
           "endmodule\n")
    out = m._strip_waveform_dumps(src)
    assert "$dumpvars" not in out
    # the load-bearing half: the checker sharing the line MUST survive
    assert "forever @(posedge clk)" in out
    assert "mismatch_count = mismatch_count + 1;" in out


def test_strip_multiline_dump_call_removed_whole():
    """A dump call spanning lines is removed WHOLE (no dangling fragment): [^;]
    spans newlines, so the sub eats through the closing ');'."""
    m = _load()
    src = ("  $dumpvars(0,\n"
           "            tb.clk,\n"
           "            tb.q);\n"
           "  q_ref = 1'b0;\n")
    out = m._strip_waveform_dumps(src)
    assert "$dumpvars" not in out
    assert "tb.q);" not in out          # no dangling tail of the call
    assert "q_ref = 1'b0;" in out       # following statement intact


# ---- _iverilog_toolgap_signature: fires on tool-gap, not plain syntax -----
@pytest.mark.parametrize("text", [
    "prob_ref.sv:29: sorry: This cast operation is not yet supported.",
    "t.sv:120: error: Unable to bind wire/reg/memory `tb_mismatch' in `tb'",
    "internal error: something in the elaborator",
    "I don't know how to elaborate: this construct",
])
def test_toolgap_signature_fires_on_sv2012_gaps(text):
    m = _load()
    assert m._iverilog_toolgap_signature(text) is True


@pytest.mark.parametrize("text", [
    "sample.sv:4: syntax error",
    "sample.sv:7: error: Unknown module type: FooBar",
    "error: reg 'q' is not a valid l-value",
    "",
])
def test_toolgap_signature_ignores_plain_rtl_errors(text):
    m = _load()
    assert m._iverilog_toolgap_signature(text) is False


# ---- docker-gated integration: fork path recovers the cast + no-leak ------
def _need_container():
    if not shutil.which("docker"):
        pytest.skip("docker not available")
    m = _load()
    r = subprocess.run(["docker", "exec", m._IV13_CONTAINER, "sh", "-c",
                        "iverilog -V >/dev/null 2>&1 && echo ok"],
                       capture_output=True, text=True)
    if "ok" not in r.stdout:
        pytest.skip(f"EDA container {m._IV13_CONTAINER!r} with iverilog not running")
    return m


def test_fork_iverilog_runs_sv_enum_cast_and_no_leak(tmp_path):
    """A minimal TB whose golden uses an SV enum cast: host iverilog rejects it,
    the fork rung runs it. A correct DUT PASSes; a wrong DUT still mismatches."""
    m = _need_container()
    # golden ref uses an enum type-cast in a $dumpvars-bearing TB
    ref = tmp_path / "r.sv"
    ref.write_text(
        "module RefModule(input [1:0] s, output logic [1:0] y);\n"
        "  typedef enum logic [1:0] {A,B,C,D} st_t;\n"
        "  always_comb y = st_t'(s);\n"
        "endmodule\n"
    )
    tb = tmp_path / "t.sv"
    tb.write_text(
        "module tb;\n"
        "  reg [1:0] s; wire [1:0] yr, yd; integer mism=0, i;\n"
        "  initial begin $dumpfile(\"w.vcd\"); $dumpvars(1, mism); end\n"
        "  RefModule good(.s(s), .y(yr));\n"
        "  TopModule dut(.s(s), .y(yd));\n"
        "  initial begin\n"
        "    for (i=0;i<4;i=i+1) begin s=i; #1; if (yr!==yd) mism=mism+1; end\n"
        "    $display(\"Mismatches: %0d in 4 samples\", mism); $finish;\n"
        "  end\n"
        "endmodule\n"
    )
    good = tmp_path / "good.sv"
    good.write_text("module TopModule(input [1:0] s, output [1:0] y);\n"
                    "  assign y = s;\nendmodule\n")
    bad = tmp_path / "bad.sv"
    bad.write_text("module TopModule(input [1:0] s, output [1:0] y);\n"
                   "  assign y = 2'b00;\nendmodule\n")

    out_good = m._fork_iverilog_compile_run([str(good), str(tb), str(ref)], "tb")
    assert out_good is not None, "fork build should succeed on the SV-cast golden"
    assert "Mismatches: 0 in 4 samples" in out_good

    out_bad = m._fork_iverilog_compile_run([str(bad), str(tb), str(ref)], "tb")
    assert out_bad is not None
    # §4.05 no-leak: a wrong DUT still mismatches (verdict never inflated)
    assert "Mismatches: 0 in" not in out_bad


def test_fork_strip_never_deletes_checker_sharing_dump_line(tmp_path):
    """Verdict-level regression of the adversarial-verify finding: a TB whose
    mismatch-checker forever-loop SHARES the $dumpvars line. Under the line-based
    strip the checker was deleted with the line, mismatch_count stayed 0, and a
    genuinely-WRONG DUT printed the pass-shaped 'Mismatches: 0 in 20 samples'.
    With the call-scoped strip the checker survives: wrong DUT mismatches, correct
    DUT still passes."""
    m = _need_container()
    tb = tmp_path / "t.sv"
    tb.write_text(
        "module tb;\n"
        "  reg clk = 0, in = 0; wire y; integer mismatch_count = 0; integer i;\n"
        "  TopModule dut(.in(in), .y(y));\n"
        "  always #1 clk = ~clk;\n"
        "  initial begin\n"
        # the attack line: dump call + the ONLY mismatch-checker share one line
        "    $dumpvars(0, tb); forever @(posedge clk) "
        "if (y !== in) mismatch_count = mismatch_count + 1;\n"
        "  end\n"
        "  initial begin\n"
        "    for (i = 0; i < 20; i = i + 1) begin @(negedge clk); in = i[0]; end\n"
        "    @(negedge clk);\n"
        "    $display(\"Mismatches: %0d in 20 samples\", mismatch_count);\n"
        "    $finish;\n"
        "  end\n"
        "endmodule\n")
    good = tmp_path / "good.sv"
    good.write_text("module TopModule(input in, output y);\n"
                    "  assign y = in;\nendmodule\n")
    bad = tmp_path / "bad.sv"
    bad.write_text("module TopModule(input in, output y);\n"
                   "  assign y = ~in;\nendmodule\n")

    out_bad = m._fork_iverilog_compile_run([str(bad), str(tb)], "tb")
    assert out_bad is not None and out_bad != m.FORK_SIM_TIMEOUT
    # the checker must have survived the strip: a wrong DUT reports mismatches
    assert "Mismatches: 0 in" not in out_bad, (
        "checker was deleted with the $dumpvars line — wrong DUT scored clean")
    out_good = m._fork_iverilog_compile_run([str(good), str(tb)], "tb")
    assert out_good is not None and out_good != m.FORK_SIM_TIMEOUT
    assert "Mismatches: 0 in 20 samples" in out_good


# ---- gatekeeper remediation (#114 landing): _golden_ref_self_compiles gets the
# ---- SAME tool-gap escalation as the sample path, so an enum-cast golden is not
# ---- falsely stamped "golden_ref_fails_own_tb" (unsatisfiable-by-anyone) on an
# ---- iverilog-11 host while the fork rung happily scores the samples.
class _FakeCompleted:
    def __init__(self, rc, out):
        self.returncode, self.stdout, self.stderr = rc, "", out


# VERBATIM real output of stock Ubuntu 22.04 iverilog 11.0 on the REAL
# VerilogEval-v2 golden (dataset_spec-to-rtl/Prob156_review2015_fancytimer_ref.sv):
_REAL_IV11_SORRY = ("/ds/Prob156_review2015_fancytimer_ref.sv:25: sorry: "
                    "This cast operation is not yet supported.")
# VERBATIM real Prob099 unsatisfiable-TB error (the scorer-PROVEN defect class):
_REAL_PROB099_ERR = "test.sv:71: error: port ``Y2'' is not a port of good1."


def _mk_golden_fixture(tmp_path):
    (tmp_path / "P_ref.sv").write_text(
        "module RefModule(input [1:0] s, output logic [1:0] y);\n"
        "  typedef enum logic [1:0] {A,B,C,D} st_t;\n"
        "  always_comb y = st_t'(s);\nendmodule\n")
    (tmp_path / "P_test.sv").write_text("module tb; endmodule\n")
    return {"ref_suffix": "_ref.sv", "tb_suffix": "_test.sv",
            "module_name_strategy": "always_TopModule"}


def test_golden_self_compile_escalates_toolgap_to_fork(tmp_path, monkeypatch):
    """iverilog-11-host shape: BOTH host compile attempts die with the real
    'sorry: cast' tool-gap, but the fork rung builds the golden -> the golden is
    satisfiable (True), NOT an irreducible dataset defect."""
    m = _load()
    layout = _mk_golden_fixture(tmp_path)
    monkeypatch.setattr(m.subprocess, "run",
                        lambda *a, **k: _FakeCompleted(1, _REAL_IV11_SORRY))
    monkeypatch.setattr(m, "_fork_iverilog_compile_run",
                        lambda srcs, top: "\nMismatches: 0 in 4 samples\n")
    assert m._golden_ref_self_compiles("P", tmp_path, layout) is True


def test_golden_self_compile_fork_unavailable_stays_false(tmp_path, monkeypatch):
    """Stay-effective: same tool-gap host failure but the fork build also fails
    (container absent / genuine gap) -> the prior False verdict is preserved."""
    m = _load()
    layout = _mk_golden_fixture(tmp_path)
    monkeypatch.setattr(m.subprocess, "run",
                        lambda *a, **k: _FakeCompleted(1, _REAL_IV11_SORRY))
    monkeypatch.setattr(m, "_fork_iverilog_compile_run", lambda srcs, top: None)
    assert m._golden_ref_self_compiles("P", tmp_path, layout) is False


def test_golden_self_compile_real_defect_never_escalates(tmp_path, monkeypatch):
    """Stay-clean: a REAL unsatisfiable-TB defect (verbatim Prob099 error shape —
    TB wires a port the golden never declares) must stay False and must NOT even
    attempt the fork (the signature gate keeps the defect class intact)."""
    m = _load()
    layout = _mk_golden_fixture(tmp_path)
    calls = []
    monkeypatch.setattr(m.subprocess, "run",
                        lambda *a, **k: _FakeCompleted(2, _REAL_PROB099_ERR))
    monkeypatch.setattr(m, "_fork_iverilog_compile_run",
                        lambda srcs, top: calls.append(1) or "never")
    assert m._golden_ref_self_compiles("P", tmp_path, layout) is False
    assert not calls, "fork must not be consulted for a non-tool-gap failure"


# ---- Step-2.7 adversarial-review remediations (gatekeeper, #114 landing) ----
def test_candidate_source_is_preserved_verbatim(tmp_path, monkeypatch):
    """Reproduced HIGH: stripping $dumpvars from the CANDIDATE repairs a
    non-compiling submission into a PASS. The fix copies any `preserve`d path
    VERBATIM. Verified at the strip layer (no docker needed): the candidate's
    illegal dump line survives; the TB's dump line is stripped."""
    m = _load()
    cand = tmp_path / "cand.sv"
    cand.write_text("module TopModule(output y);\n"
                    "  initial $dumpvars(0, bogus_sig);\n"
                    "  assign y = 1'b0;\nendmodule\n")
    tb = tmp_path / "tb.sv"
    # real VerilogEval TB shape: the dump call sits on its own line inside an
    # initial begin/end block (that is the line the strip targets)
    tb.write_text("module tb;\n  initial begin\n    $dumpvars(0, tb);\n"
                  "  end\nendmodule\n")
    staged = {}

    def fake_run(cmd, **kw):
        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        if cmd[:2] == ["docker", "cp"]:
            staged[cmd[3].rsplit("/", 1)[-1]] = Path(cmd[2]).read_text()
        elif cmd[:2] == ["docker", "exec"] and "iverilog" in cmd[-1]:
            R.stdout = "__FBUILT__\nMismatches: 0 in 4 samples\n__FORKRC=0\n"
        return R
    monkeypatch.setattr(m.subprocess, "run", fake_run)
    out = m._fork_iverilog_compile_run([str(cand), str(tb)], "tb",
                                       preserve=(str(cand),))
    assert out is not None
    assert "$dumpvars(0, bogus_sig)" in staged["src0.sv"], (
        "candidate must be copied VERBATIM (preserve)")
    assert "$dumpvars" not in staged["src1.sv"], (
        "the benchmark's own TB still gets the dump-strip")


def test_fork_sim_timeout_is_never_a_pass(tmp_path, monkeypatch):
    """Reproduced HIGH: `timeout` SIGTERMs vvp, the TB's `final` block prints
    'Mismatches: 0 in 0 samples', and the raw output would match the pass
    regex — a HANG became a PASS. The fix detects GNU timeout's rc=124 and
    returns the FORK_SIM_TIMEOUT sentinel instead of the output."""
    m = _load()
    src = tmp_path / "s.sv"
    src.write_text("module tb; endmodule\n")

    def fake_run(cmd, **kw):
        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        if cmd[:2] == ["docker", "exec"] and "iverilog" in cmd[-1]:
            # what a SIGTERM'd hung VerilogEval TB actually emits
            R.stdout = "__FBUILT__\nMismatches: 0 in 0 samples\n__FORKRC=124\n"
        return R
    monkeypatch.setattr(m.subprocess, "run", fake_run)
    out = m._fork_iverilog_compile_run([str(src)], "tb")
    assert out == m.FORK_SIM_TIMEOUT
    # and the scorer maps the sentinel to a sim_timeout FAIL, never PASS
    assert not (isinstance(out, str) and out != m.FORK_SIM_TIMEOUT)


def test_dockerless_host_returns_none_instead_of_crashing(tmp_path, monkeypatch):
    """Reproduced MEDIUM/HIGH: with no docker binary the cleanup in `finally`
    raised FileNotFoundError PAST the except, crashing the whole scoring run on
    any candidate typo that trips the tool-gap signature. The guarded cleanup
    must let the rung degrade to None (-> the old compile_error verdict)."""
    m = _load()
    src = tmp_path / "s.sv"
    src.write_text("module tb; endmodule\n")
    monkeypatch.setenv("PATH", str(tmp_path))   # no docker anywhere
    out = m._fork_iverilog_compile_run([str(src)], "tb")
    assert out is None


def test_strip_replaces_call_with_empty_statement_prefix_safe():
    """Gatekeeper remediation on the call-scoped strip: the dump call is
    replaced by an empty statement `;` so (a) an if/else-prefixed dump keeps a
    legal, semantics-preserving arm (bare deletion left `if (dbg) else` — a
    syntax error that deflated a recoverable TB) and (b) an event-control
    prefix cannot silently attach to the following statement."""
    m = _load()
    src = ("  initial begin\n"
           "    if (dbg) $dumpvars(0, tb); else err = err + 1;\n"
           "    @(posedge clk) $dumpfile(\"w.vcd\");\n"
           "    checker_tick = checker_tick + 1;\n"
           "  end\n")
    out = m._strip_waveform_dumps(src)
    assert "$dump" not in out
    assert "if (dbg) ; else err = err + 1;" in out
    assert "@(posedge clk) ;" in out
    assert "checker_tick = checker_tick + 1;" in out


# ---- Step-2.7 reproduced INFLATION on the naive call-scoped form ------------
def test_strip_never_matches_dump_token_in_comment():
    """Reproduced INFLATION vector 1a: '// enable $dumpvars for waves' above an
    unbraced checker — the naive [^;]*; match ate across the newline and
    deleted the TB's sole checker while staying COMPILABLE (wrong DUT printed
    'Mismatches: 0' — false PASS). A commented token must never match."""
    m = _load()
    src = ("module tb;\n"
           "  // enable $dumpvars for waves\n"
           "  always @(posedge clk) if (y !== in) errors = errors + 1;\n"
           "endmodule\n")
    out = m._strip_waveform_dumps(src)
    assert "errors = errors + 1;" in out, "checker must survive a commented token"
    assert "// enable $dumpvars for waves" in out, "comment itself untouched"


def test_strip_never_matches_semicolonless_macro_body():
    """Reproduced INFLATION vector 1b: `define WAVES $dumpvars(0, tb)  (no
    trailing ';' — the idiomatic `WAVES; split). The naive match ate the
    newline + the following checker into the macro body. A call with no
    IMMEDIATE ';' must not match — the macro survives verbatim (worst case its
    expansion later fails the fork build: deflation-only, never inflation)."""
    m = _load()
    src = ("`define WAVES $dumpvars(0, tb)\n"
           "always @(posedge clk) if (y !== in) err = err + 1;\n")
    out = m._strip_waveform_dumps(src)
    assert "`define WAVES $dumpvars(0, tb)" in out, "macro body left verbatim"
    assert "err = err + 1;" in out, "checker must survive"


def test_strip_removes_call_with_semicolon_inside_string_arg():
    """String args are masked before matching, so a ';' INSIDE a $dumpfile
    string no longer stops the match — the call is removed WHOLE (upgrades the
    previously-disclosed dangling-fragment deflation)."""
    m = _load()
    src = '  $dumpfile("a;b.vcd");\n  q_ref = 1\'b0;\n'
    out = m._strip_waveform_dumps(src)
    assert "$dumpfile" not in out
    assert 'b.vcd");' not in out, "no dangling fragment"
    assert "q_ref = 1'b0;" in out
