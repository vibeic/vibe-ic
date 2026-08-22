"""Regression tests for the spec_floor read-side key names (re #495 Stage 0).

A ``spec_floor:`` rule only measures the design if the key it READS is a key
some producer WRITES. Four floors read a spelling no producer emits:

    L11_calibration_tables_min    read L11.tables          producer: calibration_tables
    L12_sequences_min             read L12.sequences       producer: behavioral_sequences
    L9_top_level_port_count_min   read L9.ports (legacy)   producer: top_ports (canonical)
    L3_crc_poly_allowed           read crc.poly            producer: crc.poly_hex /
                                                           crc_parameters.polynomial_hex

Every test below drives the gate's REAL CLI entry point and asserts on the
gate's own observable output (``measured`` values and emitted ``findings``) —
never on the text of the source. Each repaired key gets three tests:

  * PRODUCER spelling alone is now seen (the repair);
  * INCUMBENT spelling alone still reads exactly as before (the guard against
    the repair being a rename that breaks the old path);
  * INCUMBENT present-but-EMPTY must not shadow a populated PRODUCER key (the
    guard that makes the appended alias actually reachable — the incumbent
    readers returned on first key PRESENT, not first key non-empty).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGS = Path(__file__).resolve().parent.parent
QUALITY = PROGS / "phase1_quality_parity_check.py"
EXTENSION = PROGS / "layer_extension_presence_check.py"

# Importing the shared table keeps D1 (every program is referenced by a test)
# satisfied for the module and pins its public surface.
sys.path.insert(0, str(PROGS))
import _spec_floor_keys as SFK  # noqa: E402


def _docs(tmp_path: Path, layers: dict) -> Path:
    d = tmp_path / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    for name, obj in layers.items():
        (d / f"{name}.json").write_text(json.dumps(obj))
    return d


def _run(prog: Path, docs: Path, class_path: str) -> dict:
    r = subprocess.run(
        [sys.executable, str(prog), str(docs), "--class-path", class_path],
        capture_output=True, text=True,
    )
    assert r.stdout.strip(), f"{prog.name} produced no stdout; stderr={r.stderr}"
    return json.loads(r.stdout)


def _rules(out: dict) -> set:
    return {f["rule"] for f in out.get("findings", [])}


# --------------------------------------------------------------------------
# L11 — calibration tables
# --------------------------------------------------------------------------
_L11_TABLE = [{"name": "trim_a", "rows": [1, 2]}, {"name": "trim_b", "rows": [3]}]


def test_l11_producer_spelling_calibration_tables_is_counted(tmp_path):
    """protocol-ic declares L11_calibration_tables_min: 1. A doc carrying only
    the producer spelling must satisfy it."""
    docs = _docs(tmp_path, {"L11_CALIBRATION": {"calibration_tables": _L11_TABLE}})
    out = _run(EXTENSION, docs, "protocol-ic")
    assert out["measured"]["L11_calibration_tables"] == 2
    assert "L11_calibration_tables_min" not in _rules(out)


def test_l11_incumbent_spelling_tables_still_counted(tmp_path):
    docs = _docs(tmp_path, {"L11_CALIBRATION": {"tables": _L11_TABLE}})
    out = _run(EXTENSION, docs, "protocol-ic")
    assert out["measured"]["L11_calibration_tables"] == 2
    assert "L11_calibration_tables_min" not in _rules(out)


def test_l11_empty_incumbent_does_not_shadow_producer_key(tmp_path):
    docs = _docs(tmp_path, {
        "L11_CALIBRATION": {"tables": [], "calibration_tables": _L11_TABLE},
    })
    out = _run(EXTENSION, docs, "protocol-ic")
    assert out["measured"]["L11_calibration_tables"] == 2
    assert "L11_calibration_tables_min" not in _rules(out)


def test_l11_absent_everywhere_still_fails_the_floor(tmp_path):
    """The repair must not turn the floor into a vacuous pass."""
    docs = _docs(tmp_path, {"L11_CALIBRATION": {"otp_present": False}})
    out = _run(EXTENSION, docs, "protocol-ic")
    assert out["measured"]["L11_calibration_tables"] == 0
    assert "L11_calibration_tables_min" in _rules(out)


# --------------------------------------------------------------------------
# L12 — behavioural sequences
# --------------------------------------------------------------------------
_L12_SEQS = [
    {"name": "reset_to_ready", "steps": ["assert rst", "release rst"]},
    {"name": "normal_op", "steps": ["issue cmd", "read status"]},
]


def test_l12_producer_spelling_behavioral_sequences_is_counted(tmp_path):
    docs = _docs(tmp_path, {"L12_BEHAVIORAL_SEQUENCES":
                            {"behavioral_sequences": _L12_SEQS}})
    out = _run(EXTENSION, docs, "protocol-ic")
    assert out["measured"]["L12_sequences"] == 2
    assert "L12_sequences_min" not in _rules(out)


def test_l12_incumbent_spelling_sequences_still_counted(tmp_path):
    docs = _docs(tmp_path, {"L12_BEHAVIORAL_SEQUENCES": {"sequences": _L12_SEQS}})
    out = _run(EXTENSION, docs, "protocol-ic")
    assert out["measured"]["L12_sequences"] == 2
    assert "L12_sequences_min" not in _rules(out)


def test_l12_empty_incumbent_does_not_shadow_producer_key(tmp_path):
    docs = _docs(tmp_path, {"L12_BEHAVIORAL_SEQUENCES":
                            {"sequences": [], "behavioral_sequences": _L12_SEQS}})
    out = _run(EXTENSION, docs, "protocol-ic")
    assert out["measured"]["L12_sequences"] == 2
    assert "L12_sequences_min" not in _rules(out)


def test_l12_unconsumable_dict_incumbent_does_not_shadow_producer_list(tmp_path):
    """A dict-shaped ``sequences`` was always counted as 0 by this gate; it
    must not also hide a list-shaped ``behavioral_sequences``."""
    docs = _docs(tmp_path, {"L12_BEHAVIORAL_SEQUENCES": {
        "sequences": {"frame_transmission": {"steps": []}},
        "behavioral_sequences": _L12_SEQS,
    }})
    out = _run(EXTENSION, docs, "protocol-ic")
    assert out["measured"]["L12_sequences"] == 2
    assert "L12_sequences_min" not in _rules(out)


def test_l12_populated_incumbent_wins_over_shorter_producer_key(tmp_path):
    """Selection is first-NON-EMPTY, not longest and not a union: a doc-set
    carrying BOTH keys reads exactly the count it read before the repair."""
    docs = _docs(tmp_path, {"L12_BEHAVIORAL_SEQUENCES": {
        "sequences": _L12_SEQS + [{"name": "third", "steps": []}],
        "behavioral_sequences": [{"name": "only_one", "steps": []}],
    }})
    out = _run(EXTENSION, docs, "protocol-ic")
    assert out["measured"]["L12_sequences"] == 3


def test_l12_absent_everywhere_still_fails_the_floor(tmp_path):
    docs = _docs(tmp_path, {"L12_BEHAVIORAL_SEQUENCES":
                            {"no_behavioral_sequences_in_input": True}})
    out = _run(EXTENSION, docs, "protocol-ic")
    assert out["measured"]["L12_sequences"] == 0
    assert "L12_sequences_min" in _rules(out)


# --------------------------------------------------------------------------
# L9 — top-level port list
# --------------------------------------------------------------------------
def _ports(n: int) -> list:
    return [{"name": f"p{i}", "direction": "input"} for i in range(n)]


def test_l9_canonical_spelling_top_ports_is_counted(tmp_path):
    """cable-side-id-ic declares L9_top_level_port_count_min: 14."""
    docs = _docs(tmp_path, {"L9_INTEGRATION_SPEC": {"top_ports": _ports(14)}})
    out = _run(QUALITY, docs, "cable-side-id-ic")
    assert out["measured"]["L9_top_level_port_count"] == 14
    assert "L9_top_level_port_count_min" not in _rules(out)


def test_l9_legacy_spelling_ports_still_counted(tmp_path):
    docs = _docs(tmp_path, {"L9_INTEGRATION_SPEC": {"ports": _ports(14)}})
    out = _run(QUALITY, docs, "cable-side-id-ic")
    assert out["measured"]["L9_top_level_port_count"] == 14
    assert "L9_top_level_port_count_min" not in _rules(out)


def test_l9_empty_legacy_ports_does_not_shadow_canonical_top_ports(tmp_path):
    docs = _docs(tmp_path, {"L9_INTEGRATION_SPEC":
                            {"ports": [], "top_ports": _ports(14)}})
    out = _run(QUALITY, docs, "cable-side-id-ic")
    assert out["measured"]["L9_top_level_port_count"] == 14
    assert "L9_top_level_port_count_min" not in _rules(out)


def test_l9_top_module_pins_mirror_is_counted_when_others_empty(tmp_path):
    docs = _docs(tmp_path, {"L9_INTEGRATION_SPEC": {
        "ports": [], "top_ports": [], "top_module_pins": _ports(14),
    }})
    out = _run(QUALITY, docs, "cable-side-id-ic")
    assert out["measured"]["L9_top_level_port_count"] == 14


def test_l9_empty_nested_location_does_not_shadow_root_keys(tmp_path):
    """The orchestrator-nested lookup runs first; an empty nested list must not
    return 0 and skip the populated root key."""
    docs = _docs(tmp_path, {"L9_INTEGRATION_SPEC": {
        "dtop_top_level": {"ports": []}, "top_ports": _ports(14),
    }})
    out = _run(QUALITY, docs, "cable-side-id-ic")
    assert out["measured"]["L9_top_level_port_count"] == 14


def test_l9_no_port_list_anywhere_still_fails_the_floor(tmp_path):
    docs = _docs(tmp_path, {"L9_INTEGRATION_SPEC": {"no_integration_in_input": True}})
    out = _run(QUALITY, docs, "cable-side-id-ic")
    assert out["measured"]["L9_top_level_port_count"] == 0
    assert "L9_top_level_port_count_min" in _rules(out)


# --------------------------------------------------------------------------
# L3 — CRC polynomial
# --------------------------------------------------------------------------
def test_l3_producer_spelling_poly_hex_is_read(tmp_path):
    """cable-side-id-ic allows 0x31; reading `crc.poly_hex` must resolve it and
    clear the whitelist finding that a "poly not found" produced before."""
    docs = _docs(tmp_path, {"L3_CMD_PROTOCOL": {"crc": {"poly_hex": "0x31"}}})
    out = _run(QUALITY, docs, "cable-side-id-ic")
    assert out["measured"]["L3_crc_poly"] == "0x31"
    assert "L3_crc_poly_allowed" not in _rules(out)


def test_l3_producer_spelling_crc_parameters_polynomial_hex_is_read(tmp_path):
    docs = _docs(tmp_path, {"L3_CMD_PROTOCOL":
                            {"crc_parameters": {"polynomial_hex": "0x07"}}})
    out = _run(QUALITY, docs, "cable-side-id-ic")
    assert out["measured"]["L3_crc_poly"] == "0x07"
    assert "L3_crc_poly_allowed" not in _rules(out)


def test_l3_incumbent_spelling_poly_still_read(tmp_path):
    docs = _docs(tmp_path, {"L3_CMD_PROTOCOL": {"crc": {"poly": "0x31"}}})
    out = _run(QUALITY, docs, "cable-side-id-ic")
    assert out["measured"]["L3_crc_poly"] == "0x31"
    assert "L3_crc_poly_allowed" not in _rules(out)


def test_l3_out_of_whitelist_producer_poly_still_fails(tmp_path):
    """The repair widens what the gate can SEE; it must not widen what the gate
    ACCEPTS."""
    docs = _docs(tmp_path, {"L3_CMD_PROTOCOL": {"crc": {"poly_hex": "0xAB"}}})
    out = _run(QUALITY, docs, "cable-side-id-ic")
    assert out["measured"]["L3_crc_poly"] == "0xab"
    assert "L3_crc_poly_allowed" in _rules(out)


def test_l3_null_polynomial_is_not_a_poly(tmp_path):
    """Producers emit `polynomial_hex: null` when the source never stated one;
    that must stay "not found", not become the string 'none'."""
    docs = _docs(tmp_path, {"L3_CMD_PROTOCOL":
                            {"crc_parameters": {"polynomial_hex": None}}})
    out = _run(QUALITY, docs, "cable-side-id-ic")
    assert out["measured"]["L3_crc_poly"] is None
    assert "L3_crc_poly_allowed" in _rules(out)


def test_l3_nested_frame_format_crc_uses_the_same_field_aliases(tmp_path):
    docs = _docs(tmp_path, {"L3_CMD_PROTOCOL":
                            {"frame_format": {"crc": {"poly_hex": "0x31"}}}})
    out = _run(QUALITY, docs, "cable-side-id-ic")
    assert out["measured"]["L3_crc_poly"] == "0x31"
    assert "L3_crc_poly_allowed" not in _rules(out)


# --------------------------------------------------------------------------
# The shared table itself
# --------------------------------------------------------------------------
def test_alias_tables_preserve_incumbent_order_as_a_prefix():
    """The non-regression argument rests on the incumbent keys keeping their
    original relative order and the new spellings being APPENDED."""
    assert SFK.L11_CALIBRATION_TABLE_KEYS[0] == "tables"
    assert SFK.L12_SEQUENCE_KEYS[0] == "sequences"
    assert SFK.L9_TOP_PORT_ROOT_KEYS[:3] == ("top_level_ports", "ports", "dtop_ports")
    assert SFK.L3_CRC_CONTAINER_KEYS[:3] == ("crc", "crc8", "crc_config")
    assert SFK.L3_CRC_POLY_FIELD_KEYS[:2] == ("poly", "polynomial")


def test_first_nonempty_skips_empty_and_wrong_kind():
    doc = {"a": [], "b": {}, "c": {"x": 1}, "d": [1, 2]}
    assert SFK.first_nonempty(doc, ("a", "b", "c", "d")) == ("c", {"x": 1})
    assert SFK.first_nonempty(doc, ("a", "b", "c", "d"), kinds=(list,)) == ("d", [1, 2])
    assert SFK.first_nonempty(doc, ("a", "b")) == (None, None)
    assert SFK.first_nonempty(None, ("a",)) == (None, None)
