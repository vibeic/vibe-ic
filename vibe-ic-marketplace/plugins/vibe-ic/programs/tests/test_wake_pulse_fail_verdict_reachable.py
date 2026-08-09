#!/usr/bin/env python3
"""`wake_pulse_implementation_check` could not FAIL where it actually runs.

THE DEFECT. The gate's ONLY route to rc 1 was ``return 1 if args.strict else 0``
at the end of ``main``. Its ONLY production caller is the P0 structural umbrella
in ``flow_compliance_check``, whose argv comes from ``_structural_gate_argv``;
this gate is in neither ``_STRUCTURAL_GATE_ARGV_ADAPTERS`` nor
``_STRUCTURAL_GATE_BARE_FLAGS``, so the umbrella builds
``[python, <gate>.py, <project>]`` and ``--strict`` is never supplied. Every
ERROR the gate found printed ``FAIL — ...`` on stdout and exited 0, and
``_eval_gate_worker`` records rc 0 as PASS without reading stdout. A design
whose wake pulse was measurably too short for the host's own declared receive
window was reported as a passing gate.

The gate's own test file could not see this: every case in it passed
``--strict``, i.e. exercised an argv production never builds. That is the second
half of the defect and is why these tests use the REAL BUILDER instead of a
re-typed command line — a re-typed argv agrees with the umbrella by coincidence.

WHAT THESE TESTS PIN, both directions, because one direction is half the
property:

  * FAIL is reachable    — a declared wake pulse below the declared BIT0 LOW
                           minimum exits 1 under the umbrella's own argv.
                           Against the unfixed gate this is rc 0.
  * PASS is still reachable — the same fixture with a pulse inside the window
                           exits 0. A gate that can only ever fail is the same
                           defect pointed the other way.
  * VACUOUS is a third answer, not a silent pass — a project the gate has no
                           subject in exits 2 with the disclosure sentinel, and
                           `_gate_invocation` does NOT misread that rc 2 as the
                           umbrella having called the gate wrongly.

Every fixture is synthetic and protocol-generic: no design name, no PDK, no part
number.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import _gate_invocation as GI  # noqa: E402

GATE = "wake_pulse_implementation_check"


def _load_flow():
    spec = importlib.util.spec_from_file_location(
        "fcc_wake_pulse_reachable", PROGRAMS / "flow_compliance_check.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fcc_wake_pulse_reachable"] = mod
    spec.loader.exec_module(mod)
    return mod


F = _load_flow()


# ---------------------------------------------------------------------------
# Fixtures — a generic single-wire half-duplex accessory bus. The host RX
# classifier declares a BIT0 LOW window; the chip declares the width of the
# wake pulse it drives. Both numbers come from the project's own L docs.
# ---------------------------------------------------------------------------

_RTL_WITH_WAKE_FSM = """\
module core(input clk, input rst_n, output reg wake_drv);
  reg [15:0] twk_cnt;
  reg [19:0] tito_cnt;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      twk_cnt  <= 16'd0;
      tito_cnt <= 20'd0;
      wake_drv <= 1'b0;
    end else begin
      twk_cnt  <= twk_cnt + 1'b1;
      tito_cnt <= tito_cnt + 1'b1;
      wake_drv <= (twk_cnt != 16'd0);
    end
  end
endmodule
"""


def _make_project(tmp_path: Path, *, wake_pulse_us: float,
                  bit0_low_min_us: float = 3.6,
                  bit0_low_max_us: float = 9.4) -> Path:
    """A project the gate HAS a subject in: both numbers are declared."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2_TIMING_WAVEFORM.json").write_text(json.dumps({
        "pulse_classes": [
            {"class_name": "WAKE", "min_us": bit0_low_min_us,
             "max_us": bit0_low_max_us},
        ],
        "wake_pulse_us": wake_pulse_us,
    }))
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "internal_clock_MHz": 50,
        "rx_classifier": {
            "bit0_low_min_us": bit0_low_min_us,
            "bit0_low_max_us": bit0_low_max_us,
        },
    }))
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "core.v").write_text(_RTL_WITH_WAKE_FSM)
    return tmp_path


def _umbrella_argv(project: Path) -> list:
    """EXACTLY what the P0 umbrella runs this gate with.

    Built by `flow_compliance_check._structural_gate_argv`, the same named
    function `_eval_gate_worker` calls, with the same `rtl_dir` the umbrella
    derives. Nothing here re-types a command line.
    """
    rtl_dir = project / "phase2" / "stage1" / "rtl"
    return F._structural_gate_argv(GATE, project, rtl_dir=rtl_dir)


def _run_as_umbrella(project: Path):
    argv = _umbrella_argv(project)
    return subprocess.run(argv, cwd=project, capture_output=True,
                          text=True, timeout=60)


# ---------------------------------------------------------------------------
# The argv the fix had to work under.
# ---------------------------------------------------------------------------

def test_production_argv_supplies_no_strict_flag(tmp_path):
    """The premise of every test below, asserted rather than assumed.

    If a later change wires `--strict` in, this test goes red and whoever does
    it has to decide deliberately — instead of the gate's reachability quietly
    coming to depend on a flag again.
    """
    project = _make_project(tmp_path, wake_pulse_us=4.5)
    argv = _umbrella_argv(project)
    assert "--strict" not in argv, argv
    assert argv[-1] == str(project), argv


# ---------------------------------------------------------------------------
# DIRECTION 1 — the verdict that was unreachable.
# ---------------------------------------------------------------------------

def test_wake_pulse_below_declared_bit0_min_fails_under_umbrella_argv(tmp_path):
    """A pulse the host cannot classify as a wake event must exit 1.

    THIS IS THE MUTATION TEST. Against the unfixed gate the same fixture and
    the same argv produce rc 0, and the umbrella records the gate as PASS while
    its own stdout says `FAIL — ...`.
    """
    project = _make_project(tmp_path, wake_pulse_us=1.0,
                            bit0_low_min_us=3.6, bit0_low_max_us=9.4)
    r = _run_as_umbrella(project)
    assert r.returncode == 1, (
        "the gate found the defect and did not report it: "
        f"rc={r.returncode}\n{r.stdout}{r.stderr}")
    # The rc is a verdict about THIS defect, not an incidental non-zero.
    assert "WAKE_PULSE_BELOW_BIT0_MIN" in r.stdout, r.stdout


def test_the_failing_report_says_it_did_not_pass(tmp_path):
    """The emitted JSON agrees with the exit code.

    `passed` used to be able to be False while the process exited 0 — two
    verdicts from one run, and the consumer read the one that was wrong.
    """
    project = _make_project(tmp_path, wake_pulse_us=1.0)
    out = project / "rep.json"
    argv = _umbrella_argv(project) + ["--json", str(out)]
    r = subprocess.run(argv, cwd=project, capture_output=True, text=True,
                       timeout=60)
    rep = json.loads(out.read_text())
    assert rep["passed"] is False, rep
    assert rep["exit_code"] == r.returncode == 1, (rep, r.returncode)


def test_wake_pulse_above_declared_bit0_max_also_fails(tmp_path):
    """The upper-edge verdict was unreachable for the identical reason."""
    project = _make_project(tmp_path, wake_pulse_us=20.0,
                            bit0_low_min_us=3.6, bit0_low_max_us=9.4)
    r = _run_as_umbrella(project)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "WAKE_PULSE_ABOVE_BIT0_MAX" in r.stdout, r.stdout


# ---------------------------------------------------------------------------
# DIRECTION 2 — the OTHER verdict must still be reachable.
# ---------------------------------------------------------------------------

def test_wake_pulse_inside_declared_window_passes_under_umbrella_argv(tmp_path):
    """Same fixture, same argv, a compliant width -> rc 0 and a PASS line.

    A monitor found on this campaign could only ever say FAIL because its
    success branch was unreachable. Verifying only direction 1 would not have
    caught that.
    """
    project = _make_project(tmp_path, wake_pulse_us=6.0,
                            bit0_low_min_us=3.6, bit0_low_max_us=9.4)
    r = _run_as_umbrella(project)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS — BIT0 mode" in r.stdout, r.stdout
    assert "[ERROR]" not in r.stdout, r.stdout


def test_wkp_mode_passes_and_fails_from_the_same_fixture(tmp_path):
    """Both verdicts of the OTHER classifier mode, from one shared fixture.

    Proves the fix did not reach rc 1 by making one branch unconditional: the
    only difference between these two runs is the declared pulse width.
    """
    def _wkp_project(root: Path, wake_us: float) -> Path:
        docs = root / "phase1" / "generated_docs"
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "L2.json").write_text(json.dumps({
            "wake_pulse_us": wake_us,
        }))
        (docs / "L8.json").write_text(json.dumps({
            "clock_period_ns": 20.0,
            "rx_classifier": {
                "bit0_low_min_us": 3.6,
                "bit0_low_max_us": 9.4,
                "wkp_min_us": 24.0,       # > bit0_low_max -> WKP mode
            },
        }))
        rtl = root / "phase2" / "stage1" / "rtl"
        rtl.mkdir(parents=True, exist_ok=True)
        (rtl / "core.v").write_text(_RTL_WITH_WAKE_FSM)
        return root

    too_short = _wkp_project(tmp_path / "short", 7.0)
    r_fail = _run_as_umbrella(too_short)
    assert r_fail.returncode == 1, r_fail.stdout + r_fail.stderr
    assert "WAKE_PULSE_BELOW_WKP_MIN" in r_fail.stdout, r_fail.stdout

    wide_enough = _wkp_project(tmp_path / "wide", 30.0)
    r_pass = _run_as_umbrella(wide_enough)
    assert r_pass.returncode == 0, r_pass.stdout + r_pass.stderr
    assert "PASS — WKP mode" in r_pass.stdout, r_pass.stdout


# ---------------------------------------------------------------------------
# THE THIRD ANSWER — and the reason making rc 1 reachable did not redden
# every project that already exists.
# ---------------------------------------------------------------------------

def test_project_with_no_wake_subject_is_vacuous_not_failed(tmp_path):
    """A project this gate has no subject in is rc 2, not rc 1 and not rc 0.

    MEASURED over the 117 tracked project directories carrying L docs and/or an
    RTL directory, the pre-fix gate produced an ERROR finding on 105 of them —
    99 of those `WAKE_PULSE_VALUES_UNRESOLVED` on projects whose L docs say
    nothing about a wake pulse. Had rc 1 been made reachable WITHOUT this, the
    corpus would have gone red for a reason none of those projects has.
    """
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2.json").write_text(json.dumps({
        "bus_width_bits": 32, "endianness": "little",
    }))
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "core.v").write_text(
        "module core(input clk, output reg q);\n"
        "  always @(posedge clk) q <= ~q;\n"
        "endmodule\n")
    r = _run_as_umbrella(tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr
    # rc 2 alone is a number; the sentinel says in words it is not a pass.
    assert "VACUOUS_PASS:" in (r.stdout + r.stderr), r.stdout + r.stderr


def test_the_vacuous_rc2_is_not_misread_as_a_caller_defect(tmp_path):
    """rc 2 carries two meanings and the umbrella separates them by TEXT.

    `_gate_invocation.classify_not_invocable` must return None here, or the
    umbrella would record NOT_INVOCABLE — "this gate was never validly
    invoked" — for a gate that ran fine and reported an empty denominator.
    """
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2.json").write_text(json.dumps({"bus_width_bits": 32}))
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "core.v").write_text("module core(input clk); endmodule\n")
    argv = _umbrella_argv(tmp_path)
    r = subprocess.run(argv, cwd=tmp_path, capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 2, r.stdout + r.stderr
    why = GI.classify_not_invocable(
        r.stdout, r.stderr,
        supplied_flags=[a for a in argv if a.startswith("--")])
    assert why is None, why


def test_a_declared_wake_class_keeps_the_unresolved_verdict_reachable(tmp_path):
    """Narrowing applicability must not create a NEW unreachable verdict.

    `WAKE_PULSE_VALUES_UNRESOLVED` is now conditioned on the project declaring
    a wake pulse. If that condition were unsatisfiable the fix would have
    traded one dead branch for another, so here is an input that reaches it.
    """
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2.json").write_text(json.dumps({
        "symbol_classes": [
            {"symbol": "WAKE", "low_polarity": "active_low"},
        ],
    }))
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "core.v").write_text(_RTL_WITH_WAKE_FSM)
    r = _run_as_umbrella(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "WAKE_PULSE_VALUES_UNRESOLVED" in r.stdout, r.stdout


# ---------------------------------------------------------------------------
# The latent crash, kept separate from the verdict work.
# ---------------------------------------------------------------------------

def test_zero_bit0_low_min_does_not_crash(tmp_path):
    """`bit0_low_min_us == 0` used to raise an uncaught ZeroDivisionError.

    A crash is not a verdict. The comparison's OUTCOME is unchanged (a width of
    zero still clears a floor of zero); what changes is that the process
    returns one of its documented codes instead of a traceback.
    """
    project = _make_project(tmp_path, wake_pulse_us=0.0,
                            bit0_low_min_us=0.0, bit0_low_max_us=9.4)
    r = _run_as_umbrella(project)
    assert "ZeroDivisionError" not in r.stderr, r.stderr
    assert r.returncode in (0, 1, 2), (r.returncode, r.stdout, r.stderr)
    assert "not positive" in r.stdout, r.stdout


def test_zero_bit0_low_max_does_not_crash(tmp_path):
    """Same guard, upper edge."""
    project = _make_project(tmp_path, wake_pulse_us=0.0,
                            bit0_low_min_us=0.0, bit0_low_max_us=0.0)
    r = _run_as_umbrella(project)
    assert "ZeroDivisionError" not in r.stderr, r.stderr
    assert r.returncode in (0, 1, 2), (r.returncode, r.stdout, r.stderr)
