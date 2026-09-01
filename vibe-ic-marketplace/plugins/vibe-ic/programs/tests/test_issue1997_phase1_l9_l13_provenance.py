"""Issue #1997: the L9-L13 Phase-1 emitters must preserve input provenance.

The u_hawaii_adc acceptance output was 9/14 in
``phase1_provenance_presence_check``: L1-L8 carried source documents, while
all five L9-L13 writers emitted ``source_documents: []``.  These tests drive
the real emitters with a neutral one-document corpus and pin both directions:
the five documents cite that input after emission, and removing one citation
is observed by the shipped presence gate as an exact L11 failure.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))

import phase1_doc_one_shot_runner as p1  # noqa: E402
import phase1_provenance_presence_check as presence  # noqa: E402


SOURCE = "input/docs/spec.md"
L9_L13 = (
    "L9_INTEGRATION_SPEC.json",
    "L10_TEST_CASES.json",
    "L11_OTP_CONTENT.json",
    "L12_BEHAVIORAL_SEQUENCES.json",
    "L13_LAB_CALIBRATION.json",
)


def _emit_l9_l13(project: Path) -> Path:
    docs = project / "input" / "docs"
    docs.mkdir(parents=True)
    docs.joinpath("spec.md").write_text(
        "# Neutral block\n\n"
        "The block accepts two values and reports their sum.\n",
        encoding="utf-8",
    )
    extracted = {"spec.md": docs.joinpath("spec.md").read_text()}
    l3 = {"opcodes": []}

    p1.gen_l9_integration_spec(project, extracted, l3)
    p1.gen_l10_test_cases(project, extracted, l3)
    p1.gen_l11_otp_content(project, extracted)
    p1.gen_l12_behavioral(project, extracted, l3)
    p1.gen_l13_lab_calibration(project, extracted)
    return project / "phase1" / "generated_docs"


@pytest.mark.parametrize("name", L9_L13)
def test_l9_l13_emitters_propagate_the_scanned_input_document(
        tmp_path, name):
    """Load-bearing negative control: each emitter fails by value pre-fix."""
    generated = _emit_l9_l13(tmp_path)
    doc = json.loads((generated / name).read_text())
    assert doc.get("source_documents") == [SOURCE], (
        f"{name} dropped the input corpus provenance: "
        f"{doc.get('source_documents')!r}")


def test_recursive_input_cites_the_real_path_not_the_encoded_scratch_key(
        tmp_path):
    """Recursive input provenance names the on-disk document exactly."""
    docs = tmp_path / "input" / "docs" / "subdir"
    docs.mkdir(parents=True)
    source = docs / "spec.md"
    source.write_text("# Nested neutral block\n", encoding="utf-8")

    p1.gen_l11_otp_content(
        tmp_path, {"subdir__spec.md": source.read_text()})
    doc = json.loads(
        (tmp_path / "phase1" / "generated_docs" /
         "L11_OTP_CONTENT.json").read_text())

    assert doc.get("source_documents") == ["input/docs/subdir/spec.md"]


def test_presence_gate_observes_a_dropped_emitter_field(tmp_path):
    """Value-bearing mutation: one dropped citation is exactly one red layer."""
    generated = _emit_l9_l13(tmp_path)
    for tag, name in presence.EXPECTED_DOCS:
        path = generated / name
        if not path.exists():
            path.write_text(json.dumps({
                "layer": tag,
                "source_documents": [SOURCE],
            }))

    l11 = generated / "L11_OTP_CONTENT.json"
    doc = json.loads(l11.read_text())
    doc.pop("source_documents", None)
    l11.write_text(json.dumps(doc))

    report = presence.check_dir(generated)
    failed = {
        tag for tag, result in report["per_layer"].items()
        if result["status"] != "PASS"
    }
    assert report["passes"] == 13
    assert failed == {"L11"}
