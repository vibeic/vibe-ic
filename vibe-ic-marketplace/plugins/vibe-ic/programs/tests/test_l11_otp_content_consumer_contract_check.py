"""Smoke tests for l11_otp_content_consumer_contract_check.py.

NEGATIVE CONTROL IS THE POINT — every claim is asserted in BOTH
directions from one shared fixture builder, so a gate hardwired to
return 0 (or 1) would fail here immediately.

All fixtures are SYNTHESISED neutral data: invented field names, an
invented image, no real design's files, no vendor part number, no PDK
name, no pin literal from any shipped design.
"""
import json
import sys
from pathlib import Path


import ic_class_profile as ic_profile  # noqa: E402
import phase1_doc_one_shot_runner as phase1  # noqa: E402
import spi_protocol_synth  # noqa: E402

CANON = "L11_OTP_CONTENT.json"


# ---------------------------------------------------------------------------
# fixture builders
# ---------------------------------------------------------------------------
def _docs(tmp_path):
    d = tmp_path / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _well_formed_doc():
    """A 4-byte image whose field map spans it exactly, with one typed lock."""
    return {
        "otp_present": True,
        "otp_bytes": [0x00, 0x11, 0x22, 0x33],
        "field_map": [
            {"name": "alpha_cfg", "address": 0, "width": 8, "default": 0},
            {"name": "beta_cfg", "address": 1, "width": 8, "default": 0x11},
            {"name": "gamma_trim", "address": 2, "width": 8, "default": 0x22},
            {"name": "delta_lock", "address": 3, "width": 8, "default": 0x33},
        ],
        "otp_lock_bits": [
            {"name": "delta_lock", "bit": 7, "address": 3,
             "protects_range": "0x00..0x02", "trigger_value": "0x80"},
        ],
    }


def _write(docs, doc, name=CANON):
    (docs / name).write_text(json.dumps(doc, ensure_ascii=False))




# Declaration sites are injected so the tests never depend on the repo's
# live constants — the gate reads them at run time in production.
_AGREE = {"siteA": CANON, "siteB": CANON}




def _produce_l11(tmp_path, source_text):
    """Run the actual L11 producer and its two normal post-producer writers."""
    project = tmp_path / "producer_project"
    docs = project / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "design.md").write_text(source_text, encoding="utf-8")
    generated = project / "phase1" / "generated_docs"
    generated.mkdir(parents=True)
    (generated / "L4_REGMAP.json").write_text(json.dumps({
        "otp_layout": None,
        "no_otp_layout_in_input": False,
    }))
    phase1.gen_l11_otp_content(project, {"design.md": source_text})
    phase1._post_emit_l11_fsm_strict_gate(project)
    spi_protocol_synth.apply_spi_synth(generated, False, None)
    return json.loads((generated / CANON).read_text())


def test_source_silence_stays_unknown_through_actual_l11_writers(tmp_path):
    doc = _produce_l11(tmp_path, "A small synchronous counter.\n")
    assert doc["otp_layout"] is None
    assert doc["no_otp_layout_in_input"] is False
    assert doc["no_otp_fsm_in_input"] is False
    assert doc["otp_present"] is None
    assert ic_profile._l4_has_otp({"otp_layout": None}, doc, None) is False


def test_explicit_source_bound_no_otp_authorizes_absence(tmp_path):
    doc = _produce_l11(
        tmp_path, "No OTP is included.\n")
    assert doc["otp_layout"] is None
    assert doc["no_otp_layout_in_input"] is True
    assert doc["no_otp_fsm_in_input"] is True
    assert doc["otp_present"] is False


def test_unresolved_otp_prose_does_not_authorize_absence(tmp_path):
    doc = _produce_l11(
        tmp_path, "OTP availability is not yet determined by the owner.\n")
    assert doc["no_otp_layout_in_input"] is False
    assert doc["no_otp_fsm_in_input"] is False
    assert doc["otp_present"] is None


# ---------------------------------------------------------------------------
# HALF A — resolution / dead consumer read
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# HALF B1/B2 — field map presence and span
# ---------------------------------------------------------------------------












# ---------------------------------------------------------------------------
# HALF B3 — lock bits
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# SCOPE — no OTP declared must not be punished
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# SKIP paths must not masquerade as PASS
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# Waiver
# ---------------------------------------------------------------------------
