"""ORGANIC #617 [MEDIUM] — internal_vs_external_timing_check (the half-duplex
RX/TX timing-split gate) false-FAILed a non-half-duplex compute/CPU class. Its
empty-content VACUOUS_PASS escape required timing_windows AND timing_constants
AND waveforms ALL empty, but doc-extraction auto-populates waveforms[] with a
GENERIC single-/few-signal WaveDrom diagram (a basic memory-transaction / bus
diagram from a source .rst) that has zero rx_/tx_ symbol groups. The non-empty
waveforms[] defeated the all(_empty(...)) short-circuit, so check() ran and
hard-demanded rx_*/tx_* host/DUT LOW-pulse groups the IC legitimately has none
of → missing_rx_group + missing_tx_group ERROR → Step-2 Lint FAIL. (L2 also had
protocol_overview=null → half_duplex_l2 is None, not False, so the L2 escape
did not fire either.)

Fix (issue option b): a waveforms[] entry counts as EMPTY for the escape unless
it actually carries half-duplex protocol symbol-timing content (rx_/tx_/host_/
dut_ directional tokens or H0/H1/BR/IBT symbol pulses). A generic WaveDrom
diagram with none → treated empty → VACUOUS_PASS.

POSITIVE (#617): the real ibex L8 (waveforms[] = generic memory-transaction
diagram, timing_windows/timing_constants empty) → VACUOUS_PASS.

NEGATIVE no-leak:
  - a v068-style half-duplex IC with flat host-side `timing_parameters`
    (tDW/tB/tIBT AID symbols) + an internal/external note STILL FAILs
    (missing rx/tx split) — issue option (a), "treat None like False", was
    REJECTED precisely because it would wrongly escape this genuine case.
  - a waveforms[] that DOES carry rx_/tx_ symbol pulses is NOT treated empty
    → check() runs (the gate still enforces the split).
  - L2.half_duplex=false → the explicit L2 escape still fires (unchanged).

chip-AGNOSTIC: protocol symbol-timing token shape; no chip name.
"""
import json
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import internal_vs_external_timing_check as T  # noqa: E402

PROG = str(PLUGIN / "programs" / "internal_vs_external_timing_check.py")

# The real on-disk #617 ibex L8 waveforms entry (verbatim shape).
IBEX_L8 = {
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
    return r.returncode, out.get("verdict")


# ── predicate units ─────────────────────────────────────────────────────────

def test_predicate_generic_vs_protocol_waveforms():
    assert T._waveforms_carry_protocol_symbols(IBEX_L8["waveforms"]) is False
    assert T._waveforms_carry_protocol_symbols([]) is False
    assert T._waveforms_carry_protocol_symbols(
        [{"raw_payload": '{"signal":[{"name":"rx_h1_low"}]}'}]) is True
    assert T._waveforms_carry_protocol_symbols(
        [{"name": "tx_ibt"}]) is True
    assert T._waveforms_carry_protocol_symbols(
        [{"raw_payload": "host_side break pulse"}]) is True


# ── end-to-end ──────────────────────────────────────────────────────────────

def test_ibex_generic_waveform_vacuous(tmp_path):
    rc, verdict = _run(
        tmp_path,
        {"protocol_overview": None, "no_protocol_overview_in_input": True},
        IBEX_L8)
    assert rc == 0 and verdict == "VACUOUS_PASS"


def test_v068_flat_timing_still_fails(tmp_path):
    # NO-LEAK: a genuine half-duplex IC with unsplit flat timing must FAIL.
    v068 = {
        "clock_specification": {"main_clk_hz": 5_000_000},
        "timing_parameters": {"tDW0_us": {"nom": 7.2},
                              "tB_break_us": {"nom": 13.8},
                              "tIBT_us": {"nom": 22}},
        "internal_vs_external_note": "prose mentioning internal and external.",
    }
    rc, verdict = _run(tmp_path, None, v068)
    assert rc == 1 and verdict == "FAIL"


def test_waveforms_with_protocol_symbols_runs_check(tmp_path):
    # NO-LEAK: protocol-symbol waveforms are NOT treated empty → check runs.
    wf = {"timing_windows": [], "timing_constants": [],
          "waveforms": [{"raw_payload": '{"signal":[{"name":"rx_h1_low"},'
                                        '{"name":"tx_ibt"}]}'}]}
    rc, verdict = _run(tmp_path, {"protocol_overview": None}, wf)
    assert verdict != "VACUOUS_PASS"  # the strict check ran


def test_l2_half_duplex_false_still_vacuous(tmp_path):
    # the explicit L2 negative escape is unchanged.
    rc, verdict = _run(
        tmp_path, {"protocol_overview": {"half_duplex": False}}, IBEX_L8)
    assert rc == 0 and verdict == "VACUOUS_PASS"
