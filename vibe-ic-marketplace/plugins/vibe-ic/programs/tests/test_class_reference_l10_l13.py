"""v0.79 A2 — guard K3 typical_structure L10-L13 coverage for high-coverage classes.

The 5 classes named in v079_backlog A2 (hash-function-csr, block-cipher,
simple-cpu, dsp-block, memory-controller) MUST carry typical_structure
entries for L10/L11/L12/L13 so the per-layer agents have concrete shapes
to anchor against. This test guards against accidental deletion or
schema drift.
"""
from __future__ import annotations

import pytest
import yaml

from _plugin_tree import plugin_path


# flow #486: resolve via the shared plugin-root resolver so this works on
# both the source monorepo and the flattened install cache.
CLASS_REF_PATH = plugin_path("agents", "defaults", "class_reference.yaml")

A2_CLASSES = [
    "hash-function-csr",
    "block-cipher",
    "simple-cpu",
    "dsp-block",
    "memory-controller",
]

L10_L13_KEYS = [
    "L10_test_cases",
    "L11_calibration",
    "L12_behavioral_sequences",
    "L13_lab_calibration",
]


@pytest.fixture(scope="module")
def class_ref():
    return yaml.safe_load(CLASS_REF_PATH.read_text())


@pytest.mark.parametrize("cls", A2_CLASSES)
def test_a2_class_has_typical_structure(class_ref, cls):
    assert cls in class_ref, f"{cls} missing from class_reference.yaml"
    assert "typical_structure" in class_ref[cls], (
        f"{cls}.typical_structure missing — A2 requires this for L10-L13 anchoring"
    )


@pytest.mark.parametrize("cls", A2_CLASSES)
@pytest.mark.parametrize("layer_key", L10_L13_KEYS)
def test_a2_class_has_l10_l13_layer(class_ref, cls, layer_key):
    ts = class_ref[cls]["typical_structure"]
    assert layer_key in ts, (
        f"{cls}.typical_structure.{layer_key} missing — A2 floor not met"
    )


@pytest.mark.parametrize("cls", A2_CLASSES)
def test_a2_l10_test_cases_has_typical_vectors(class_ref, cls):
    """L10 must enumerate concrete test vectors so the L10 per-layer
    agent has a list to anchor against (not just prose)."""
    l10 = class_ref[cls]["typical_structure"]["L10_test_cases"]
    assert isinstance(l10, dict) and "typical_vectors" in l10, (
        f"{cls}.L10_test_cases.typical_vectors missing or wrong shape"
    )
    vectors = l10["typical_vectors"]
    assert isinstance(vectors, list) and len(vectors) >= 3, (
        f"{cls}.L10_test_cases.typical_vectors has fewer than 3 entries — "
        f"A2 floor is at least 3 named test categories"
    )
    for v in vectors:
        # Accept either "description" or "expect" — older entries
        # (dsp-block, memory-controller from v0.78) used "expect"; the
        # v0.79 A2 additions use "description". Both convey the same
        # intent and the per-layer agent reads either.
        assert isinstance(v, dict) and "name" in v and (
            "description" in v or "expect" in v
        ), (
            f"{cls}.L10_test_cases.typical_vectors entries must be "
            f"{{name, description|expect}} dicts; got: {v!r}"
        )


@pytest.mark.parametrize("cls", A2_CLASSES)
def test_a2_l11_calibration_explicit_when_not_applicable(class_ref, cls):
    """For deterministic-logic classes (hash, cipher, CPU), L11 is n/a —
    must be EXPLICITLY marked so the L11 agent doesn't synthesize a
    fictional calibration table."""
    l11 = class_ref[cls]["typical_structure"]["L11_calibration"]
    assert isinstance(l11, dict), f"{cls}.L11_calibration must be a dict"
    if l11.get("not_applicable") is True:
        # Must give a reason, not just a bare flag, so reviewers + agents
        # can see WHY.
        assert l11.get("reason"), (
            f"{cls}.L11_calibration.not_applicable=True without reason — "
            f"A2 schema requires reason field"
        )


@pytest.mark.parametrize("cls", A2_CLASSES)
def test_a2_l12_behavioral_sequences_is_list_of_named_steps(class_ref, cls):
    l12 = class_ref[cls]["typical_structure"]["L12_behavioral_sequences"]
    assert isinstance(l12, list) and len(l12) >= 2, (
        f"{cls}.L12_behavioral_sequences should be a list of at least 2 "
        f"named sequences (init, normal-op at minimum)"
    )
    for seq in l12:
        assert isinstance(seq, dict) and "name" in seq, (
            f"{cls}.L12_behavioral_sequences entries must have 'name'"
        )


@pytest.mark.parametrize("cls", A2_CLASSES)
def test_a2_l13_lab_calibration_has_smoke_tests_or_explicit_na(class_ref, cls):
    l13 = class_ref[cls]["typical_structure"]["L13_lab_calibration"]
    assert isinstance(l13, dict), f"{cls}.L13_lab_calibration must be a dict"
    has_smoke = "typical_smoke_tests" in l13
    is_na = l13.get("not_applicable") is True
    assert has_smoke or is_na, (
        f"{cls}.L13_lab_calibration must either list typical_smoke_tests "
        f"or be explicitly not_applicable"
    )
