import hashlib
import zipfile

import pytest

import flow109_metric_acceptance as metrics
from test_flow109_phase1_metric_completion import approve, case


@pytest.mark.parametrize("literal_matches", [True, False])
def test_original_binary_document_citation_uses_native_conversion(tmp_path, monkeypatch, literal_matches):
    payload, _ = case(tmp_path, monkeypatch)
    path = tmp_path / "input/docs/notes.odt"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("content.xml", "<document><p>A declared interface sentence.</p></document>")
    source = {"path": "input/docs/notes.odt", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    literal = "A declared interface sentence." if literal_matches else "A different sentence."
    for section in payload.values():
        section["source_documents"].append(source)
        section["expectations"][0]["evidence"].append(
            f"{source['path']}:1 sha256:{source['sha256']} — {literal}")
    approve(tmp_path, payload)
    if literal_matches:
        authority, _ = metrics._d0102_population(tmp_path, "base_01", "requirements_trace", {})
        assert authority["status"] == "APPROVED"
    else:
        with pytest.raises(metrics.MetricRefusal, match="D0102_REQUIREMENT_LITERAL_DIFFERS"):
            metrics._d0102_population(tmp_path, "base_01", "requirements_trace", {})
