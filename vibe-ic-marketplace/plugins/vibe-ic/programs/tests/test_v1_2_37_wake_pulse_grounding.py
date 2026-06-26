"""L8 wake-pulse extraction — no template leak, verbatim-grounded evidence.

phase1_evidence_grounding_check (v1.2.36) surfaced that the L8 wake-pulse
proximity-fallback leaked: a UART datasheet's `tMR Master Reset Pulse Width 5000
ns` matched the GENERIC `pulse width` arm and was emitted as a `wake_pulse`
"vendor measurement" with input-doc provenance — for specs (espi/milstd1553/uart)
with ZERO wake concept. Two fixes:
  * the generic arms (`pulse width` / `response time`) fire ONLY on a
    measurement-HINT file (a PPTX scope-shot where the `wake` label is lost); on
    any other doc a GENUINE `wake`/`wkp` keyword is required;
  * the emitted evidence `literal` is the VERBATIM source quote (so
    phase1_evidence_grounding_check can confirm it), not a synthesised
    "wake_pulse measurement N us" string.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import phase1_doc_one_shot_runner as R  # noqa: E402


def _wake_evidence(fname: str, spec: str):
    p = Path(tempfile.mkdtemp())
    (p / "input" / "docs").mkdir(parents=True)
    (p / "input" / "docs" / fname).write_text(spec)
    R.gen_l8_timing_waveform(p, {fname: spec})
    out = []
    for f in (p / "phase1" / "generated_docs").glob("L8*.json"):
        ev = json.loads(f.read_text()).get("extraction_evidence", {})
        for src, entries in ev.items():
            for e in (entries if isinstance(entries, list) else []):
                if "wake" in json.dumps(e).lower():
                    out.append(e)
    return out


def test_generic_pulse_width_in_protocol_spec_no_leak():
    # the real UART leak: a Master-Reset pulse-width timing param must NOT become
    # a wake-pulse "vendor measurement" in a spec with no wake concept
    ev = _wake_evidence("uart_spec.txt",
                        "tMR  Master Reset Pulse Width  5000 ns. A digital UART core.")
    assert ev == []


def test_generic_arm_preserved_on_measurement_hint_file():
    # the legitimate PPTX scope-shot use case still fires (filename hint present)
    ev = _wake_evidence("scope_measurement.txt",
                        "Pulse width measured 22.4 us on the scope shot.")
    assert ev and any("22.4" in e["literal"] for e in ev)


def test_genuine_wake_line_grounded_verbatim():
    # a genuine wake line fires on any doc, and the evidence literal is VERBATIM
    spec = "The wake pulse low width is 50 us per the datasheet."
    ev = _wake_evidence("dev_spec.txt", spec)
    assert ev and ev[0]["literal"] == spec  # verbatim, not a synthesised string


def test_no_wake_no_measurement_hint_no_emit():
    ev = _wake_evidence("proto_spec.txt",
                        "The bus has a clock and a data line. Response time 5 us.")
    assert ev == []   # generic 'response time' arm gated off a non-measurement file
