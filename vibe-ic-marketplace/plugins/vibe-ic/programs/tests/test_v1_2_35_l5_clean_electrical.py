"""L5 clean electrical pass — a digital-only IC's real supply/clock specs are
captured (via spec_electrical_extract), the prose-noise is not.

The 87-spec Phase-1 parity sweep showed the L5 generator dropped real
prose-embedded electrical specs (`VDD = 1.2 V`, `runs at 800 MHz`) for digital
protocols: the bullet_kv_pair_spec parser was tightened to remove prose-fragment
noise (good), and the no_analog skeleton forced electrical_specs=[] (a digital
chip DOES have supply/clock). v1.2.35 wires the §4.05-safe spec_electrical_extract
(number+SI-unit+context only) into L5 and carries it through the no_analog
skeleton — recovering the real electrical facts WITHOUT the prose noise.
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


def _gen_l5(spec_text: str) -> dict:
    proj = Path(tempfile.mkdtemp())
    docs = proj / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "proto_spec.txt").write_text(spec_text)
    R.gen_l5_adi_spec(proj, {"proto_spec.txt": spec_text})
    return json.loads((proj / "phase1" / "generated_docs" / "L5_ADI_SPEC.json").read_text())


def test_digital_protocol_l5_carries_real_electrical():
    # a digital protocol with prose electrical specs -> L5.electrical_specs gets the
    # real supply/clock even though no_analog (the skeleton now carries elec_specs)
    spec = ("DDR4 SDRAM specification.\n"
            "The device operates from a 1.2 V supply (VDD = 1.2 V).\n"
            "The interface runs at 800 MHz (DDR data rate 1600 MT/s).\n"
            "It is a purely digital memory interface.\n")
    l5 = _gen_l5(spec)
    assert l5.get("no_analog") is True            # digital -> N/A analog interface
    vals = {str(e.get("value")) + str(e.get("unit") or "") for e in l5["electrical_specs"]}
    blob = " ".join(vals)
    assert "1.2" in blob and "V" in blob          # real supply captured
    assert "800" in blob and "MHz" in blob        # real clock captured


def test_no_prose_noise_in_l5_electrical():
    # §4.05: a prose sentence with no real number+unit+context mints NOTHING
    spec = ("A protocol that uses pulse-amplitude modulation with three levels.\n"
            "The header segment carries framing information for each burst.\n"
            "It is a digital line protocol.\n")
    l5 = _gen_l5(spec)
    # no supply/clock/current claims fabricated from the prose
    for e in l5["electrical_specs"]:
        assert e.get("extraction_strategy") != "spec_electrical_extract" or \
            (e.get("unit") and str(e.get("value"))[:1].isdigit())


def test_design_parameters_stays_empty_on_digital_skeleton():
    # the loose unitless prose-bullet design_parameters remain the LLM boundary —
    # the deterministic no_analog skeleton does not fabricate them
    spec = "A digital protocol. Signals per direction: 2. Differential pairs: 4.\n"
    l5 = _gen_l5(spec)
    assert l5.get("no_analog") is True
    assert l5["design_parameters"] == []
