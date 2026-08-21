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

SCRIPT = (Path(__file__).parent.parent
          / "l11_otp_content_consumer_contract_check.py")
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"
sys.path.insert(0, str(SCRIPT.parent))

import l11_otp_content_consumer_contract_check as chk  # noqa: E402

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


def _cats(tmp_path, declared=None):
    rep = chk.audit(_docs(tmp_path), declared=declared)
    return [f["category"] for f in rep["findings"] if f["severity"] == "ERROR"]


# Declaration sites are injected so the tests never depend on the repo's
# live constants — the gate reads them at run time in production.
_AGREE = {"siteA": CANON, "siteB": CANON}


def _run(tmp_path):
    return chk.main([str(tmp_path)])


# ---------------------------------------------------------------------------
# HALF A — resolution / dead consumer read
# ---------------------------------------------------------------------------
def test_resolving_declaration_passes(tmp_path):
    _write(_docs(tmp_path), _well_formed_doc())
    assert _cats(tmp_path, declared=_AGREE) == []


def test_NEGATIVE_control_phantom_declared_name_fails(tmp_path):
    """GUTTED: a declaration site names a file the run never emits.

    Same emitted layer as the passing case — only the declaration moves.
    """
    _write(_docs(tmp_path), _well_formed_doc())
    declared = {"siteA": CANON, "siteB": "L11_SOMETHING_ELSE.json"}
    cats = _cats(tmp_path, declared=declared)
    assert "DEAD_CONSUMER_READ" in cats


def test_live_repo_declarations_agree_and_resolve(tmp_path):
    """The gate's default (live) declaration set must resolve.

    Guards the fix that pointed schema.LAYER_FILE_NAMES['L11'] at the
    filename Phase-1 actually emits.
    """
    _write(_docs(tmp_path), _well_formed_doc())
    declared = chk.declared_layer_filenames()
    assert declared, "no declaration site could be read"
    assert set(declared.values()) == {CANON}, declared
    assert _run(tmp_path) == 0


# ---------------------------------------------------------------------------
# HALF B1/B2 — field map presence and span
# ---------------------------------------------------------------------------
def test_NEGATIVE_control_otp_image_without_field_map_fails(tmp_path):
    doc = _well_formed_doc()
    doc.pop("field_map")
    _write(_docs(tmp_path), doc)
    assert "NO_FIELD_MAP" in _cats(tmp_path, declared=_AGREE)


def test_NEGATIVE_control_field_map_underruns_image_fails(tmp_path):
    """GUTTED: drop the last row — image bytes left with no meaning."""
    doc = _well_formed_doc()
    doc["field_map"] = doc["field_map"][:-1]
    doc["otp_lock_bits"] = []
    _write(_docs(tmp_path), doc)
    assert "FIELD_MAP_UNDERRUNS_IMAGE" in _cats(tmp_path, declared=_AGREE)


def test_NEGATIVE_control_field_map_overruns_image_fails(tmp_path):
    doc = _well_formed_doc()
    doc["field_map"].append(
        {"name": "epsilon_cfg", "address": 9, "width": 8, "default": 0})
    _write(_docs(tmp_path), doc)
    assert "FIELD_MAP_OVERRUNS_IMAGE" in _cats(tmp_path, declared=_AGREE)


def test_NEGATIVE_control_untyped_field_row_fails(tmp_path):
    doc = _well_formed_doc()
    doc["field_map"][1].pop("width")
    _write(_docs(tmp_path), doc)
    assert "UNTYPED_FIELD" in _cats(tmp_path, declared=_AGREE)


def test_image_length_derived_from_content_hex(tmp_path):
    """The span rule must work off content_hex too, not just otp_bytes."""
    doc = _well_formed_doc()
    doc.pop("otp_bytes")
    doc["content_hex"] = "00112233"
    _write(_docs(tmp_path), doc)
    assert _cats(tmp_path, declared=_AGREE) == []


def test_image_length_derived_from_depth_times_width(tmp_path):
    doc = _well_formed_doc()
    doc.pop("otp_bytes")
    doc["depth"] = 4
    doc["width_bits"] = 8
    _write(_docs(tmp_path), doc)
    assert _cats(tmp_path, declared=_AGREE) == []


# ---------------------------------------------------------------------------
# HALF B3 — lock bits
# ---------------------------------------------------------------------------
def test_NEGATIVE_control_lock_bit_without_affects_fails(tmp_path):
    doc = _well_formed_doc()
    doc["otp_lock_bits"][0].pop("protects_range")
    _write(_docs(tmp_path), doc)
    assert "UNSYNTHESISABLE_LOCK_BIT" in _cats(tmp_path, declared=_AGREE)


def test_NEGATIVE_control_lock_bit_without_trigger_fails(tmp_path):
    doc = _well_formed_doc()
    doc["otp_lock_bits"][0].pop("trigger_value")
    _write(_docs(tmp_path), doc)
    assert "UNSYNTHESISABLE_LOCK_BIT" in _cats(tmp_path, declared=_AGREE)


# ---------------------------------------------------------------------------
# SCOPE — no OTP declared must not be punished
# ---------------------------------------------------------------------------
def test_design_without_otp_passes(tmp_path):
    """The overwhelmingly common real shape: L11 emitted, no OTP image.

    Demanding a field map here would be a false positive, not a finding.
    """
    _write(_docs(tmp_path), {
        "schema_version": 2, "doc_class": "otp_content",
        "otp_present": False, "otp_bytes": [], "content_hex": None,
        "otp_layout": None, "depth": None, "width_bits": None,
    })
    assert _cats(tmp_path, declared=_AGREE) == []
    assert _run(tmp_path) == 0


def test_NEGATIVE_control_same_doc_declaring_otp_fails(tmp_path):
    """Flip one field: the moment the doc claims an image, it owes a map."""
    _write(_docs(tmp_path), {
        "schema_version": 2, "doc_class": "otp_content",
        "otp_present": True, "otp_bytes": [1, 2], "otp_layout": None,
    })
    assert "NO_FIELD_MAP" in _cats(tmp_path, declared=_AGREE)


# ---------------------------------------------------------------------------
# SKIP paths must not masquerade as PASS
# ---------------------------------------------------------------------------
def test_no_l11_document_skips(tmp_path):
    _docs(tmp_path)
    assert _run(tmp_path) == 2


def test_no_docs_dir_skips(tmp_path):
    assert chk.main([str(tmp_path)]) == 2


# ---------------------------------------------------------------------------
# Waiver
# ---------------------------------------------------------------------------
def test_waiver_requires_a_real_justification(tmp_path):
    doc = _well_formed_doc()
    doc.pop("field_map")
    _write(_docs(tmp_path), doc)
    assert _run(tmp_path) == 1
    (tmp_path / "waivers.json").write_text(json.dumps({chk.WAIVER_KEY: "nope"}))
    assert _run(tmp_path) == 1
    (tmp_path / "waivers.json").write_text(
        json.dumps({chk.WAIVER_KEY: "y" * (chk.WAIVER_MIN + 1)}))
    assert _run(tmp_path) == 0
