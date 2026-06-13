#!/usr/bin/env python3
"""Tests for wake_pulse_implementation_check.py (LL-11)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "wake_pulse_implementation_check.py"


def _run(tmp_path: Path, strict: bool = False):
    cmd = [sys.executable, str(PROG), str(tmp_path),
           "--json", str(tmp_path / "rep.json")]
    if strict:
        cmd.append("--strict")
    return subprocess.run(cmd, capture_output=True, text=True)


def _make_l2_with_wake(tmp_path: Path):
    """Make an L2 that mentions WAKE structurally but doesn't pin a
    pulse-width number — useful for the structural-only branch."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2_TIMING_WAVEFORM.json").write_text(json.dumps({
        "ibt_us": [20.0, 22.0],
        "tSRS_min_us": 20.0,
        "tWK_us": 24.2,
        "tITO_ms": 5.0,
        "pulse_classes": [
            {"class_name": "WAKE", "min_us": 22.0, "max_us": 28.0},
        ],
    }))


def _make_l8_with_wake(tmp_path: Path):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "internal_clock_MHz": 50,
        "TWK_PULSE": 1210,
        "TITO_TICKS": 250000,
    }))


def _write_rtl(tmp_path: Path, body: str, name: str = "core.sv"):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / name).write_text(body)


def _add_full_waiver(tmp_path: Path):
    """Waive both branches so a doc/RTL-incomplete project still passes."""
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waivers": [
            {"id": "wake_pulse_alternative_implementation",
             "rationale": "External controller drives wake pulse, "
                          "chip RTL is master-receive only."},
            {"id": "wake_pulse_width_skipped_intentional",
             "rationale": "Async protocol with no host BIT0 "
                          "classifier window; value check N/A here."},
        ],
    }))


# --------------------------------------------------------------------
# Structural branch tests (preserved from earlier waves).
# --------------------------------------------------------------------

def test_no_wake_spec_with_full_waiver_passes(tmp_path):
    """v0.119.41: when a project's L2 has no wake-pulse fields AND no
    BIT0 classifier window, the gate now FAILs unless waived. With
    both waivers, the structural + value branches both quiesce."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2_TIMING_WAVEFORM.json").write_text(json.dumps({
        "ibt_us": [20.0, 22.0], "tSRS_min_us": 20.0,
    }))
    _write_rtl(tmp_path, "module foo; endmodule")
    _add_full_waiver(tmp_path)
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_wake_spec_no_impl_fails(tmp_path):
    _make_l2_with_wake(tmp_path)
    _make_l8_with_wake(tmp_path)
    _write_rtl(tmp_path, """\
module core(input clk, output led);
  // No wake state, no wake_drv, no TITO/TWK reference
  assign led = clk;
endmodule
""")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert any(f["rule"] == "WAKE_PULSE_NOT_IMPLEMENTED"
               for f in rep["findings"])


def test_wake_state_detected(tmp_path):
    _make_l2_with_wake(tmp_path)
    _make_l8_with_wake(tmp_path)
    _write_rtl(tmp_path, """\
module core(input clk, output led);
  typedef enum { S_IDLE, S_WAKE_PULSE } st_e;
  st_e st;
  always_ff @(posedge clk) st <= S_IDLE;
  assign led = (st == S_WAKE_PULSE);
endmodule
""")
    r = _run(tmp_path, strict=True)
    # No BIT0 classifier in L2/L8 → value-branch is "wake resolved,
    # bit0 not resolved" → WARN, not FAIL.
    assert r.returncode == 0, r.stdout + r.stderr


def test_wake_signal_detected(tmp_path):
    _make_l2_with_wake(tmp_path)
    _make_l8_with_wake(tmp_path)
    _write_rtl(tmp_path, """\
module core(input clk, output led);
  reg wake_drv;
  always @(posedge clk) wake_drv <= 1'b1;
  assign led = wake_drv;
endmodule
""")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0


def test_counter_pair_detected(tmp_path):
    _make_l2_with_wake(tmp_path)
    _make_l8_with_wake(tmp_path)
    _write_rtl(tmp_path, """\
module core(input clk, output led);
  reg [17:0] tito_cnt;
  reg [10:0] twk_cnt;
  always @(posedge clk) begin
    tito_cnt <= tito_cnt + 1;
    twk_cnt  <= twk_cnt + 1;
  end
  assign led = 1'b0;
endmodule
""")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0


def test_comments_dont_count(tmp_path):
    """A comment containing `wake_drv` must NOT trigger PASS — gate has
    to find an ACTUAL identifier, not a doc-comment ghost."""
    _make_l2_with_wake(tmp_path)
    _make_l8_with_wake(tmp_path)
    _write_rtl(tmp_path, """\
module core(input clk, output led);
  // TODO: implement wake_drv with TITO_TICKS / TWK_PULSE counters
  assign led = clk;
endmodule
""")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1


def test_v031_twake_us_form_recognised(tmp_path):
    """v0.119.31: L2 keys spelled out as `tWAKE_us` / `t_wake_us` are
    accepted alongside the abbreviated `tWK_us`."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2_TIMING_WAVEFORM.json").write_text(json.dumps({
        "ibt_us": [20.0, 22.0],
        "tSRS_min_us": 20.0,
        "tWAKE_us": 24.2,
        "t_ito_ms": 5.0,
    }))
    _write_rtl(tmp_path, """\
module core(input clk);
  reg [18:0] TITO_TICKS_cnt;
  reg [10:0] TWAKE_PULSE_cnt;
  always @(posedge clk) begin
    TITO_TICKS_cnt  <= TITO_TICKS_cnt + 1;
    TWAKE_PULSE_cnt <= TWAKE_PULSE_cnt + 1;
  end
endmodule
""")
    r = _run(tmp_path, strict=True)
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert rep["summary"].get("spec_mandates_wake") is True, \
        f"tWAKE_us must be recognised as wake-spec evidence: {rep}"


def test_waiver_skips(tmp_path):
    """Both legacy and Wave-9 waivers must keep a doc-incomplete project
    from FAILing."""
    _make_l2_with_wake(tmp_path)
    _make_l8_with_wake(tmp_path)
    _write_rtl(tmp_path, "module foo(input clk); endmodule")
    _add_full_waiver(tmp_path)
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0


# ====================================================================
# Wave 9 (v0.119.41) — value-based wake-pulse vs BIT0 classifier.
# Motivated by 1st_benchmark_benchmark_a/phase2_v0119.40-vendor/RESULT.md:
# the project shipped a structurally-correct wake_pulse_gen FSM but
# TWK_PULSE = 5 clk × 200 ns/clk = 1 µs, far below the host BIT0 LOW
# minimum of ~3.6 µs. The previous gate skipped with "spec does not
# mandate periodic wake pulse" because its L2 schema lookup was too
# narrow.
# ====================================================================

def _make_value_branch_docs(tmp_path: Path,
                             *,
                             wake_pulse_us: float,
                             bit0_low_min_us: float,
                             bit0_low_max_us: float = 9.4):
    """Make L docs with explicit µs values to drive the value branch.

    The task spec uses two clocks (5 MHz chip core, 50 MHz host
    receiver) so passing values in µs directly avoids tick/MHz
    arithmetic ambiguity in the tests."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2_TIMING_WAVEFORM.json").write_text(json.dumps({
        "pulse_classes": [
            {"class_name": "WAKE", "min_us": 4.0, "max_us": 8.0},
        ],
        "wake_pulse_us": wake_pulse_us,
    }))
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "internal_clock_MHz": 50,
        "TWK_PULSE": int(wake_pulse_us * 50),  # ticks at 50 MHz
        "TITO_TICKS": 25000,
        "rx_classifier": {
            "bit0_low_min_us": bit0_low_min_us,
            "bit0_low_max_us": bit0_low_max_us,
        },
    }))
    _write_rtl(tmp_path, """\
module core(input clk, output wake_drv);
  reg [10:0] twk_cnt;
  reg [14:0] tito_cnt;
  always @(posedge clk) begin
    twk_cnt <= twk_cnt + 1;
    tito_cnt <= tito_cnt + 1;
  end
  assign wake_drv = 1'b0;
endmodule
""")


def test_wave9_value_pass_happy(tmp_path):
    """wake_pulse_us=4.0 with bit0_low_min_us=3.6 → PASS (≥1.0× and
    >20% margin)."""
    _make_value_branch_docs(
        tmp_path, wake_pulse_us=4.5, bit0_low_min_us=3.6)
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads((tmp_path / "rep.json").read_text())
    s = rep["summary"]
    assert abs(s["wake_pulse_us"] - 4.5) < 0.01, s
    assert abs(s["bit0_low_min_us"] - 3.6) < 0.01, s


def test_wave9_value_fail_too_short(tmp_path):
    """wake_pulse_us=1.0 (TWK_PULSE=5 clk × 200 ns/clk on a 5 MHz
    chip core) with bit0_low_min_us=3.6 → FAIL with explicit ratio in
    message. This is the v0.119.40 fresh-agent bug."""
    _make_value_branch_docs(
        tmp_path, wake_pulse_us=1.0, bit0_low_min_us=3.6)
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1, r.stdout + r.stderr
    rep = json.loads((tmp_path / "rep.json").read_text())
    rules = [f["rule"] for f in rep["findings"]]
    assert "WAKE_PULSE_BELOW_BIT0_MIN" in rules, rules
    msg = next(f["message"] for f in rep["findings"]
               if f["rule"] == "WAKE_PULSE_BELOW_BIT0_MIN")
    # Ratio 1.0/3.6 = 0.28
    assert "ratio=" in msg, msg
    assert "0.28" in msg or "0.27" in msg, msg


def test_wave9_value_warn_boundary(tmp_path):
    """wake_pulse_us=3.6 with bit0_low_min_us=3.6 → PASS with a
    boundary WARN (0% margin from the lower edge)."""
    _make_value_branch_docs(
        tmp_path, wake_pulse_us=3.6, bit0_low_min_us=3.6)
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads((tmp_path / "rep.json").read_text())
    warns = rep["summary"]["warnings"]
    assert any("within" in w and "bit0_low_min_us" in w for w in warns), \
        warns


def test_wave9_synonym_resolution_alt_paths(tmp_path):
    """Same numerical input expressed via alternative synonyms must
    resolve. Here we use `timing.wake_pulse_us` in L2 and
    `rx_classifier.bit0_low_min_us` in L8. Provide RTL with a wake
    state so the structural branch passes, and value branch reads
    via the alternate synonyms."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2.json").write_text(json.dumps({
        "timing": {"wake_pulse_us": 4.0},
    }))
    (docs / "L8.json").write_text(json.dumps({
        "clock_period_ns": 200.0,
        "rx_classifier": {"bit0_low_min_us": 3.6,
                          "bit0_low_max_us": 9.4},
    }))
    _write_rtl(tmp_path, """\
module core(input clk, output wake_drv);
  typedef enum { S_IDLE, S_WAKE_PULSE } st_e;
  st_e st;
  always_ff @(posedge clk) st <= S_IDLE;
  assign wake_drv = (st == S_WAKE_PULSE);
endmodule
""")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads((tmp_path / "rep.json").read_text())
    s = rep["summary"]
    assert abs(s["wake_pulse_us"] - 4.0) < 0.01, s
    assert abs(s["bit0_low_min_us"] - 3.6) < 0.01, s


def test_wave9_synonym_resolution_rtl_constants_path(tmp_path):
    """Same input expressed via `rtl_constants.TWK_PULSE` in L8.
    20 ticks × 50 ns/tick = 1.0 µs would FAIL (< 0.36 µs target).
    Use a generous TWK_PULSE so the value gate PASSes; verify the
    synonym path actually resolved."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L8.json").write_text(json.dumps({
        "rtl_constants": {
            "TWK_PULSE": 200,                # ticks
            "internal_clock_MHz": 50,        # 20 ns/tick → 4.0 µs
        },
        "rx_classifier": {
            "bit0_low_min_us": 3.6,
            "bit0_low_max_us": 9.4,
        },
    }))
    _write_rtl(tmp_path, """\
module core(input clk, output wake_drv);
  reg [10:0] twk_cnt;
  reg [14:0] tito_cnt;
  always @(posedge clk) begin
    twk_cnt <= twk_cnt + 1;
    tito_cnt <= tito_cnt + 1;
  end
  assign wake_drv = 1'b0;
endmodule
""")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads((tmp_path / "rep.json").read_text())
    s = rep["summary"]
    # Resolved via rtl_constants synonym path.
    assert s["wake_pulse_us"] is not None, s
    assert abs(s["wake_pulse_us"] - 4.0) < 0.5, s


def test_wave9_missing_both_fails_no_skip(tmp_path):
    """Wave 9 — when neither wake-pulse nor BIT0 synonym resolves AND
    no waiver, the gate must FAIL (it used to silently SKIP, which is
    what let v0.119.40 slip through)."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2.json").write_text(json.dumps({"unrelated": 1}))
    _write_rtl(tmp_path, "module core; endmodule")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1, r.stdout + r.stderr
    rep = json.loads((tmp_path / "rep.json").read_text())
    rules = [f["rule"] for f in rep["findings"]]
    assert "WAKE_PULSE_VALUES_UNRESOLVED" in rules, rules


def test_wave9_value_waiver_skips(tmp_path):
    """`wake_pulse_width_skipped_intentional` waiver (≥40 chars) must
    silence the value branch even when both synonyms miss."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2.json").write_text(json.dumps({"unrelated": 1}))
    _write_rtl(tmp_path, "module core; endmodule")
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waivers": [{
            "id": "wake_pulse_width_skipped_intentional",
            "rationale": (
                "This protocol has no host BIT0 classifier "
                "window — the master polls asynchronously."),
        }],
    }))
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_wave9_value_waiver_too_short_rejected(tmp_path):
    """Short rationale (<40 chars) must NOT silence the value branch."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2.json").write_text(json.dumps({"unrelated": 1}))
    _write_rtl(tmp_path, "module core; endmodule")
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waivers": [{
            "id": "wake_pulse_width_skipped_intentional",
            "rationale": "skip",
        }],
    }))
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1, r.stdout + r.stderr


# ====================================================================
# Wave 10 (v0.119.42) — WKP-vs-BIT0 mode detection.
# Motivated by 1st_benchmark_benchmark_a/phase2_v0119.41-vendor/RESULT.md:
# the v0.119.41 fresh-agent shipped TWK_PULSE=350 clk @ 50 MHz = 7.0 µs
# which falls inside the BIT0 LOW window [3.92, 12.24] µs and so the
# Wave-9 value gate said PASS. Silicon FAILed because the host EXAMPLE_TESTER
# classifier has a DEDICATED WKP symbol class with WKP_MIN[738] tick =
# 14.76 µs > H0_MAX[612]. A 7 µs pulse is read as BIT0, never as a
# wake event. Wave 10 detects this WKP classifier mode automatically.
# All numbers below mirror the EXAMPLE_CHIP vendor reference table without
# naming the chip — the gate logic is chip-agnostic.
# ====================================================================

def _make_wkp_mode_docs(tmp_path: Path,
                         *,
                         twk_pulse_ticks: int,
                         h0_min_ticks: int = 196,
                         h0_max_ticks: int = 612,
                         wkp_min_ticks: int = 738,
                         clock_mhz: int = 50):
    """Build L8 docs in tick form mirroring a vendor FPGA reference
    table that declares H0_MIN / H0_MAX / WKP_MIN at the same clock
    base. WKP_MIN > H0_MAX selects WKP mode."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2_TIMING_WAVEFORM.json").write_text(json.dumps({
        "pulse_classes": [
            {"class_name": "WAKE", "min_us": 14.0, "max_us": 20.0},
        ],
    }))
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "internal_clock_MHz": clock_mhz,
        "TWK_PULSE": twk_pulse_ticks,
        "TITO_TICKS": 50,
        "rx_classifier_ticks": {
            "h0_min": h0_min_ticks,
            "h0_max": h0_max_ticks,
            "wkp_min": wkp_min_ticks,
        },
        "vendor_fpga_reference_table": {
            "h0_min": h0_min_ticks,
            "h0_max": h0_max_ticks,
            "wkp_min": wkp_min_ticks,
        },
    }))
    _write_rtl(tmp_path, """\
module core(input clk, output wake_drv);
  reg [10:0] twk_cnt;
  reg [14:0] tito_cnt;
  always @(posedge clk) begin
    twk_cnt <= twk_cnt + 1;
    tito_cnt <= tito_cnt + 1;
  end
  assign wake_drv = 1'b0;
endmodule
""")


def test_wkp_mode_pass(tmp_path):
    """wkp_min=738, h0_max=612 (WKP mode); wake_pulse_us=15.0
    (TWK_PULSE=750 @ 50 MHz) → PASS WKP mode."""
    _make_wkp_mode_docs(tmp_path, twk_pulse_ticks=750)
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads((tmp_path / "rep.json").read_text())
    s = rep["summary"]
    assert s["classifier_mode"] == "WKP", s
    assert abs(s["wkp_min_us"] - 14.76) < 0.05, s
    assert "WKP mode" in r.stdout, r.stdout


def test_wkp_mode_fail_too_short(tmp_path):
    """The v0.119.41 RTL bug case: TWK_PULSE=350 @ 50 MHz = 7.0 µs.
    7.0 falls inside [3.92, 12.24] BIT0 window, but WKP_MIN=14.76 µs.
    Must FAIL with WKP mode finding and explicit ratio≈0.47."""
    _make_wkp_mode_docs(tmp_path, twk_pulse_ticks=350)
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1, r.stdout + r.stderr
    rep = json.loads((tmp_path / "rep.json").read_text())
    rules = [f["rule"] for f in rep["findings"]]
    assert "WAKE_PULSE_BELOW_WKP_MIN" in rules, rules
    msg = next(f["message"] for f in rep["findings"]
               if f["rule"] == "WAKE_PULSE_BELOW_WKP_MIN")
    assert "WKP mode" in msg, msg
    assert "wkp_min_us" in msg, msg
    # ratio = 7.0 / 14.76 ≈ 0.474
    assert "ratio=" in msg, msg
    assert "0.47" in msg, msg
    # Critically: no BIT0_ABOVE_MAX finding (we dropped that check)
    assert "WAKE_PULSE_ABOVE_BIT0_MAX" not in rules, rules


def test_wkp_mode_no_upper_bound_check(tmp_path):
    """In WKP mode there is no upper-edge check — wake_pulse_us=50 µs
    must PASS even though it is far above bit0_low_max_us=12.24."""
    # TWK_PULSE=2500 @ 50 MHz = 50 µs
    _make_wkp_mode_docs(tmp_path, twk_pulse_ticks=2500)
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads((tmp_path / "rep.json").read_text())
    rules = [f["rule"] for f in rep["findings"]]
    assert "WAKE_PULSE_ABOVE_BIT0_MAX" not in rules, rules
    assert rep["summary"]["classifier_mode"] == "WKP", rep["summary"]


def test_bit0_mode_unchanged(tmp_path):
    """Only h0_min/h0_max present, no wkp_min → falls back to BIT0
    window check (Wave 9 behaviour preserved)."""
    _make_value_branch_docs(
        tmp_path, wake_pulse_us=4.5, bit0_low_min_us=3.6,
        bit0_low_max_us=9.4)
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads((tmp_path / "rep.json").read_text())
    s = rep["summary"]
    assert s["classifier_mode"] == "BIT0", s
    assert s["wkp_min_us"] is None, s


def test_wkp_not_dominant_uses_bit0(tmp_path):
    """If wkp_min resolves but is ≤ bit0_low_max, WKP does NOT
    dominate — fall back to BIT0 mode (the historic safer path)."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L8.json").write_text(json.dumps({
        "internal_clock_MHz": 50,
        "TWK_PULSE": 350,  # 7 µs — inside BIT0 window
        "TITO_TICKS": 50,
        "rx_classifier_ticks": {
            "h0_min": 196,
            "h0_max": 612,
            "wkp_min": 200,  # ≤ h0_max (612) — not dominant
        },
    }))
    _write_rtl(tmp_path, """\
module core(input clk, output wake_drv);
  reg [10:0] twk_cnt;
  reg [14:0] tito_cnt;
  always @(posedge clk) begin
    twk_cnt <= twk_cnt + 1;
    tito_cnt <= tito_cnt + 1;
  end
  assign wake_drv = 1'b0;
endmodule
""")
    r = _run(tmp_path, strict=True)
    rep = json.loads((tmp_path / "rep.json").read_text())
    s = rep["summary"]
    assert s["classifier_mode"] == "BIT0", s
    # 7.0 µs ∈ [3.92, 12.24] → BIT0 PASS
    assert r.returncode == 0, r.stdout + r.stderr


def test_wkp_mode_override_waiver_silences(tmp_path):
    """`wake_pulse_classifier_mode_override` waiver (≥40 chars)
    silences the value branch when neither mode applies cleanly."""
    _make_wkp_mode_docs(tmp_path, twk_pulse_ticks=350)  # would FAIL
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waivers": [{
            "id": "wake_pulse_classifier_mode_override",
            "rationale": (
                "Custom three-tier symbol classifier documented in "
                "L8.note; vendor table semantics differ from default "
                "WKP-vs-BIT0 dichotomy; waived per protocol owner."),
        }],
    }))
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0, r.stdout + r.stderr
