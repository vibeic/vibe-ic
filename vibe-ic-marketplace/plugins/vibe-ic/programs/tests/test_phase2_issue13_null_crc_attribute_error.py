"""tests/test_phase2_issue13_null_crc_attribute_error.py — v1.6.80

Closes issue #13. `dict.get(key, default)` returns None when the key
is JSON-null (not missing), so `.startswith(...)` on the result
crashes Phase 2b's aid_class_rtl_gen.py with AttributeError. v1.6.80
fixes the three CRC parameter sites with the `or default` pattern,
which falls through on BOTH missing-key and null-value.

Reject-test triplet (chip-AGNOSTIC — drives the generator only via
synthetic L1/L2/L3 fixtures):

  1. null_values:    L3.crc_parameters.{init_hex,polynomial_reflected_hex}
                     == None  →  must NOT crash, must emit defaults
                     (8'hFF, 8'h8C) into crc8.v.
  2. provided_values: provided literals are normalized + emitted
                     (verifies the fix did NOT clobber real inputs).
  3. missing_keys:   keys absent  →  defaults applied (regression
                     guard against future refactors).
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

PROGRAMS_DIR = (
    Path(__file__).resolve().parent.parent.parent
)
if str(PROGRAMS_DIR) not in sys.path:
    sys.path.insert(0, str(PROGRAMS_DIR))


def _seed_project(project: Path, crc_parameters: dict) -> None:
    """Seed the minimal EXAMPLE_PROTOCOL-class fixture aid_class_rtl_gen.gen()
    needs: L1 (datasheet), L2 (FRS), L3 (cmd protocol with the
    crc_parameters under test). L8 is intentionally omitted so
    timing defaults flow through gen()'s existing fallback path
    — that is unrelated to the CRC null bug."""
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    evidence = {
        "extraction_evidence": {
            "vendor.pdf": [{"literal": "sentinel", "label": "L*"}]
        }
    }
    (gd / "L1_DATASHEET.json").write_text(json.dumps({
        **evidence, "ic_name": "EXAMPLE_PROTOCOL-IC", "interface": "Apple ID Bus",
    }))
    (gd / "L2_FRS.json").write_text(json.dumps({
        **evidence, "ic_name": "EXAMPLE_PROTOCOL-IC",
        "protocol_type": "Apple ID Bus",
    }))
    (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        **evidence, "ic_name": "EXAMPLE_PROTOCOL-IC", "command_count": 1,
        "commands": [{"opcode": "0x74", "name": "GET_ID"}],
        "crc_parameters": crc_parameters,
    }))


def _gen_module():
    """Import (or re-import) aid_class_rtl_gen with PROGRAMS_DIR on
    sys.path. Re-importing per-test avoids module-level state leaks."""
    if "aid_class_rtl_gen" in sys.modules:
        return importlib.reload(sys.modules["aid_class_rtl_gen"])
    return importlib.import_module("aid_class_rtl_gen")


def _read_crc8(project: Path) -> str:
    return (
        project / "phase2" / "stage1" / "rtl" / "crc8.v"
    ).read_text()


# ─── Case 1 — null values (the actual issue #13 crash trigger) ────────────
def test_null_crc_values_do_not_crash_and_emit_defaults(tmp_path: Path):
    project = tmp_path / "null_proj"
    _seed_project(project, {
        "polynomial_hex":           None,
        "polynomial_reflected_hex": None,
        "init_hex":                 None,
    })
    mod = _gen_module()
    # Must NOT raise AttributeError("'NoneType' object has no
    # attribute 'startswith'") — that was the v1.6.79 crash.
    mod.gen(str(project))
    src = _read_crc8(project)
    # Defaults applied. The generator normalizes 0x31 → no transform
    # for poly_hex (used as `8'h{poly}` template literal already), and
    # 8'h8C / 8'hFF are SV-literal defaults that flow in verbatim.
    assert "8'h8C" in src, (
        "default polynomial_reflected_hex should appear in crc8.v"
    )
    assert "8'hFF" in src, (
        "default init_hex should appear in crc8.v"
    )


# ─── Case 2 — provided values honored EXCEPT for canonical-pair
#               enforcement on poly_reflected_hex.
# v1.6.197 (#84 item 3) — when L3 supplies an inconsistent
# polynomial_reflected_hex (e.g. 0xAB when poly_hex=0x31), the
# emitter now FORCES the canonical reflected coefficient (0x8C
# for poly 0x31) so the LSB-first LFSR's wire CRC matches spec.
# Other crc_parameters fields (init_hex etc.) still flow through
# verbatim — only the canonical-pair enforcement is new.
def test_provided_crc_values_override_defaults(tmp_path: Path):
    project = tmp_path / "provided_proj"
    _seed_project(project, {
        "polynomial_hex":           "0x31",
        "polynomial_reflected_hex": "0xAB",   # inconsistent with 0x31
        "init_hex":                 "0xCD",
    })
    mod = _gen_module()
    mod.gen(str(project))
    src = _read_crc8(project)
    # init_hex flows through verbatim (no canonical-pair logic).
    assert "8'hCD" in src, (
        "provided init_hex (0xCD) should normalize into 8'hCD"
    )
    # default init 8'hFF must not leak when real init was provided.
    assert "8'hFF" not in src, (
        "default 8'hFF must not appear when a real init_hex was "
        "provided — fix must not clobber real inputs"
    )
    # v1.6.197 — inconsistent poly_reflected_hex=0xAB is OVERRIDDEN
    # to the canonical 8'h8C for poly_hex=0x31. The "blind
    # passthrough" behaviour was a structural bug because LSB-first
    # LFSR + 0xAB produces wire CRC unmatching spec.
    assert "8'h8C" in src, (
        "v1.6.197: poly=0x31 must pair with reflected coefficient "
        "8'h8C in the right-shift LFSR XOR step"
    )
    assert "8'hAB" not in src, (
        "v1.6.197: inconsistent reflected coefficient 0xAB must be "
        "overridden, not silently emitted"
    )


# ─── Case 3 — missing keys still default cleanly (regression guard) ───────
def test_missing_crc_keys_apply_defaults(tmp_path: Path):
    project = tmp_path / "missing_proj"
    # crc_parameters object exists but is empty — pre-v1.6.80 code
    # already handled this via `.get(k, default)`. Test guards
    # against future regressions of the missing-key path.
    _seed_project(project, {})
    mod = _gen_module()
    mod.gen(str(project))
    src = _read_crc8(project)
    assert "8'h8C" in src
    assert "8'hFF" in src
