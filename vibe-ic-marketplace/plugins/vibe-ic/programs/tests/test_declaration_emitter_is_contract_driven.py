from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))


# A spec that declares a machine-readable declaration contract.  The field
# names are INVENTED for this test on purpose: they belong to no design in this
# repo, so a fix that hard-codes any real design's field list fails here.
_SPEC_WITH_CONTRACT = """\
# L7 — Verification Plan

## 7.0 Plugin Declaration Requirements

The implementer MUST emit `plugin_output/declaration.json` carrying:

| Field | Required | Example |
|---|---|---|
| `widget_port_name` | YES | `"w_in"` |
| `sprocket_count` | YES | `7` |
"""

def _project(tmp_path: Path, spec_text: str) -> Path:
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "L7_verification_plan.md").write_text(spec_text, encoding="utf-8")
    return tmp_path


# #3233: absence of a generic declaration contract does not identify an
# arithmetic top. These sources deliberately have no RTL: applicability must
# come from the native top classification, while an arithmetic top still owes
# the leaf emitter's fields and an explicit contract still takes precedence.
_CRYPTO = """# NeutralCipher

The module **`cipher_unit`** has the following hardware interfaces defined.
It is a crypto accelerator implementing AES encryption and decryption with a
128-bit key, a 128-bit block, and authenticated GCM operation.
{internal}

| Signal | Direction | Type | Width | Description |
|---|---|---|---:|---|
| clk_i | input | logic | 1 | Clock |
| rst_n | input | logic | 1 | Active-low reset |
| block_i | input | logic | 128 | Input cipher block |
| key_i | input | logic | 128 | Cipher key |
| block_o | output | logic | 128 | Output cipher block |
"""

_ARITHMETIC = """# NeutralMultiply

The module **`multiply_unit`** has the following hardware interfaces defined.
This digital arithmetic primitive is an unsigned serial-parallel integer
multiplier. It computes p = (x * y) modulo 2^size with parameter size default8.
The serial operand and result use LSB-first bit order.

| Signal | Direction | Type | Width | Description |
|---|---|---|---:|---|
| clk | input | logic | 1 | Clock |
| rst | input | logic | 1 | Synchronous active-high reset |
| x | input | logic | 8 | Parallel operand |
| y | input | logic | 1 | Serial operand |
| p | output | logic | 1 | Serial product |
"""


def _native_project(tmp_path, text):
    from phase1_doc_one_shot_runner import (
        gen_l1_datasheet, gen_l2_frs, gen_l9_integration_spec,
    )
    from ic_class_profile import detect_ic_class

    project = _project(tmp_path, text)
    docs = {"L7_verification_plan.md": text}
    gen_l1_datasheet(project, docs)
    gen_l2_frs(project, docs)
    l9 = json.loads(Path(gen_l9_integration_spec(project, docs, {}).path).read_text())
    profile = detect_ic_class(project, refresh=True)
    assert not (project / "phase2/stage1/rtl").exists()
    return project, profile, l9


@pytest.mark.parametrize("internal", [
    "Its internal GHASH datapath uses a serial-parallel finite-field multiplier.",
    "The external contract is the cipher core, key handling and block processing.",
])
def test_non_arithmetic_top_without_contract_does_not_require_leaf_choices(tmp_path, internal):
    project, profile, l9 = _native_project(tmp_path, _CRYPTO.format(internal=internal))
    assert profile["ic_class"] == "crypto_accelerator"
    assert l9["top_module"] == "cipher_unit"


def test_registered_non_arithmetic_alias_uses_registry_applicability(tmp_path):
    from programs.tests._hostpaths import require_repo

    registry = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
        "ic_class_registry.json",
    )
    entry = next(c for c in json.loads(registry.read_text())["classes"]
                 if c["name"] == "crypto_accelerator")
    project, profile, _ = _native_project(tmp_path, _CRYPTO.format(internal=""))
    assert profile["ic_class"] == "crypto_accelerator"


def test_native_arithmetic_top_without_rtl_still_refuses_missing_leaf_values(tmp_path):
    project, profile, l9 = _native_project(tmp_path, _ARITHMETIC)
    assert profile["ic_class"] == "digital_arithmetic_primitive"
    assert l9["top_module"] == "multiply_unit"


def test_crypto_explicit_contract_still_requires_its_own_choices(tmp_path):
    project, profile, _ = _native_project(
        tmp_path, _CRYPTO.format(internal="") + "\n" + _SPEC_WITH_CONTRACT,
    )
    assert profile["ic_class"] == "crypto_accelerator"


def test_crypto_optional_undetermined_contract_does_not_emit_arithmetic_choices(tmp_path):
    project, profile, _ = _native_project(
        tmp_path, _CRYPTO.format(internal="") + "\n" +
        _SPEC_WITH_CONTRACT.replace("| YES |", "| optional |"),
    )
    assert profile["ic_class"] == "crypto_accelerator"


def test_missing_contract_emitter_does_not_authorize_non_arithmetic_escape(tmp_path, monkeypatch):
    project, profile, _ = _native_project(tmp_path, _CRYPTO.format(internal=""))
    assert profile["ic_class"] == "crypto_accelerator"
