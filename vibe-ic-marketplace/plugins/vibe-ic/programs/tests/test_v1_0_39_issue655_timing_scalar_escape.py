"""ORGANIC #655 [MEDIUM] — internal_vs_external_timing_check (the half-duplex
RX/TX timing-split gate) false-FAILed a NON-protocol IC whose L8 carried a bare
scalar clock-FREQUENCY constant in timing_constants[].

Root cause (sibling of #617, different container): the VACUOUS_PASS escape's
`_empty()` special-cased ONLY key=='waveforms' (via #617
_waveforms_carry_protocol_symbols). The sibling timing_constants[] container had
no equivalent protocol-content discriminator. doc-extraction promotes a single
scalar clock-frequency constant (e.g. {name:fclk,value:1.0,unit:MHz}) into L8
from an L5/spec clock table; that one non-empty entry made
`_empty('timing_constants')` return False → `all(_empty(...))` False → the
escape never fired → check() ran and hard-demanded rx_*/tx_* host/DUT LOW-pulse
groups the IC legitimately has none of → missing_rx_group + missing_tx_group
ERROR → Step-2 Lint FAIL that cascades to block the rest of the flow. (L2 also
had protocol_overview=null → half_duplex_l2 is None, not False, so the L2 escape
did not fire either.)

Fix (issue suggested_fix option b): mirror the #617 waveforms[] treatment —
a timing_constants[] entry counts as EMPTY for the escape unless it carries
per-symbol/directional protocol content (rx_/tx_/host_/dut_ tokens, H0/H1/BR/IBT
pulses, _low/_high widths, _counters/_cycles tables). A bare scalar
clock-frequency constant (clk*/fclk-style name, Hz/MHz/GHz unit, one numeric
value, no per-symbol structure) is NOT symbol-timing and must not defeat the
escape.

POSITIVE (#655): a delta-sigma ADC / data-converter-style non-protocol L8 with
timing_constants=[{name:fclk,value:1.0,unit:MHz}], timing_windows=[],
waveforms=[], L2 protocol_overview=null → VACUOUS_PASS (exit 0). A RISC-V CPU
core with len=10 generic clock-frequency constants is the same root cause on a
different chip → also VACUOUS_PASS.

NO-LEAK (the field agent must not be able to slip a genuine half-duplex IC
through):
  - a half-duplex L8 that stores per-symbol counters/cycles in
    timing_constants[] (rx_/tx_/_counters tokens) is NOT treated empty →
    check() runs → STILL FAILs the rx/tx split (missing_rx_group / etc.).
  - the #617 positive case (generic waveforms[] WaveDrom with empty
    timing_constants) STILL VACUOUS_PASSes — this fix is additive.
  - the v068-style flat half-duplex IC (timing_parameters, no split) STILL
    FAILs (no timing_constants escape involved).
  - L2.half_duplex=false → the explicit L2 escape still fires (unchanged).

chip-AGNOSTIC: protocol symbol-timing token shape; no chip name, no unit pinned.
"""
import json
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import internal_vs_external_timing_check as T  # noqa: E402

PROG = str(PLUGIN / "programs" / "internal_vs_external_timing_check.py")

# The #655 round-3 on-disk delta-sigma ADC / data-converter L8 (verbatim shape).
ADC_SCALAR_L8 = {
    "timing_constants": [{"name": "fclk", "value": 1.0, "unit": "MHz"}],
    "timing_windows": [],
    "waveforms": [],
}

# The #617 generic-waveform ibex L8 (verbatim shape) — must stay VACUOUS_PASS.
IBEX_GENERIC_L8 = {
    "timing_windows": [],
    "timing_constants": [],
    "waveforms": [{
        "file_ref": "ibex_load_store_unit.rst",
        "raw_payload": (':name: timing1 :caption: Basic Memory Transaction '
                        '{"signal":[{"name":"clk"},{"name":"addr"},'
                        '{"name":"wdata"},{"name":"rdata"},{"name":"rvalid"}]}'),
    }],
}


def _run(tmp_path, l2, l8):
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    if l2 is not None:
        (gd / "L2_FRS.json").write_text(json.dumps(l2))
    (gd / "L8_TIMING_WAVEFORM.json").write_text(json.dumps(l8))
    r = subprocess.run(
        [sys.executable, PROG, str(gd / "L8_TIMING_WAVEFORM.json"), "--json"],
        capture_output=True, text=True)
    out = json.loads(r.stdout) if r.stdout.strip().startswith("{") else {}
    return r.returncode, out.get("verdict"), [f["rule"] for f in out.get("findings", [])]


# ── predicate units ─────────────────────────────────────────────────────────

def test_predicate_scalar_clock_vs_protocol_timing_constants():
    # bare scalar clock-frequency constants → NOT protocol (count as empty)
    assert T._timing_constants_carry_protocol_symbols(
        [{"name": "fclk", "value": 1.0, "unit": "MHz"}]) is False
    assert T._timing_constants_carry_protocol_symbols([]) is False
    assert T._timing_constants_carry_protocol_symbols(
        [{"name": "clk_i", "value": 50, "unit": "MHz"},
         {"name": "refclk", "value": 25, "unit": "MHz"},
         {"name": "sys_clk", "value": 100, "unit": "MHz"}]) is False
    # directional / per-symbol protocol content → IS protocol (NOT empty)
    assert T._timing_constants_carry_protocol_symbols(
        [{"name": "rx_h1_low_counters", "value": 9}]) is True
    assert T._timing_constants_carry_protocol_symbols(
        [{"name": "tx_ibt_cycles", "value": 60}]) is True
    assert T._timing_constants_carry_protocol_symbols(
        [{"name": "host_break_low", "value": 69}]) is True
    assert T._timing_constants_carry_protocol_symbols(
        [{"name": "BR_low", "value": 31}]) is True


# ── end-to-end POSITIVE (the #655 false-FAIL is fixed) ───────────────────────

def test_adc_scalar_clock_vacuous(tmp_path):
    # The exact #655 round-3 case: scalar fclk only, L2 protocol_overview=null.
    rc, verdict, _ = _run(tmp_path, {"protocol_overview": None}, ADC_SCALAR_L8)
    assert rc == 0 and verdict == "VACUOUS_PASS"


def test_cpu_core_many_scalar_clocks_vacuous(tmp_path):
    # Chip-AGNOSTIC proof: a RISC-V CPU core with len=10 generic clock-frequency
    # constants (same root cause, different chip) also VACUOUS_PASSes.
    cpu = {
        "timing_constants": [
            {"name": f"clk{i}", "value": 10 * (i + 1), "unit": "MHz"}
            for i in range(10)
        ],
        "timing_windows": [],
        "waveforms": [],
    }
    rc, verdict, _ = _run(tmp_path, {"protocol_overview": None}, cpu)
    assert rc == 0 and verdict == "VACUOUS_PASS"


def test_no_l2_file_scalar_clock_vacuous(tmp_path):
    # Even with NO L2 on disk (half_duplex_l2 is None), the content-based
    # escape fires for a scalar-clock-only L8.
    rc, verdict, _ = _run(tmp_path, None, ADC_SCALAR_L8)
    assert rc == 0 and verdict == "VACUOUS_PASS"


# ── end-to-end NO-LEAK (a genuine half-duplex IC STILL FAILs) ────────────────

def test_protocol_timing_constants_still_fails(tmp_path):
    # NO-LEAK: timing_constants[] carrying directional / per-symbol counters is
    # NOT treated empty → check() runs → the strict rx/tx split STILL FAILs.
    hd = {
        "timing_constants": [
            {"name": "rx_h1_low_counters", "value": 9, "unit": "cycles"}],
        "timing_windows": [],
        "waveforms": [],
    }
    rc, verdict, rules = _run(tmp_path, {"protocol_overview": None}, hd)
    assert rc == 1 and verdict == "FAIL"
    assert "missing_tx_group" in rules  # only an rx-flavoured group present


def test_617_generic_waveform_still_vacuous(tmp_path):
    # NO-REGRESSION on #617: generic waveforms[] WaveDrom with empty
    # timing_constants STILL VACUOUS_PASSes. This fix is purely additive.
    rc, verdict, _ = _run(
        tmp_path, {"protocol_overview": None}, IBEX_GENERIC_L8)
    assert rc == 0 and verdict == "VACUOUS_PASS"


def test_v068_flat_half_duplex_still_fails(tmp_path):
    # NO-LEAK: a genuine half-duplex IC with unsplit flat timing must still FAIL
    # (no timing_constants[] escape involved — proves the fix didn't widen the
    # escape for real protocol ICs).
    v068 = {
        "clock_specification": {"main_clk_hz": 5_000_000},
        "timing_parameters": {"tDW0_us": {"nom": 7.2},
                              "tB_break_us": {"nom": 13.8},
                              "tIBT_us": {"nom": 22}},
        "internal_vs_external_note": "prose mentioning internal and external.",
    }
    rc, verdict, _ = _run(tmp_path, None, v068)
    assert rc == 1 and verdict == "FAIL"


def test_l2_half_duplex_false_still_vacuous(tmp_path):
    # NO-REGRESSION: the explicit L2 negative escape is unchanged.
    rc, verdict, _ = _run(
        tmp_path, {"protocol_overview": {"half_duplex": False}}, ADC_SCALAR_L8)
    assert rc == 0 and verdict == "VACUOUS_PASS"
