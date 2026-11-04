import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phase1_expert_parse_track as track


def _document(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("content.xml", '<document><p>Output remains sticky until reset.</p></document>')


def test_converted_design_document_reaches_expert_input(tmp_path):
    _document(tmp_path / "input/docs/interface.odt")
    report = track.input_text_report(tmp_path)
    assert "Output remains sticky until reset." in report["text"]
    assert report["design_documents"] == ["docs/interface.odt"]
    assert report["files_skipped"] == []
    member, = report["source_frame"]["members"]
    assert member["path"] == "docs/interface.odt"
    assert member["complete"] is True
    assert member["semantic_text"] == "Output remains sticky until reset."


def test_binary_context_does_not_become_a_design_document(tmp_path):
    _document(tmp_path / "input/attachments/context.odt")
    report = track.input_text_report(tmp_path)
    assert "Output remains sticky until reset." not in report["text"]
    assert report["design_documents"] == []
    assert report["files_skipped"][0]["reason"] == track.SKIP_UNSUPPORTED_FORMAT


@pytest.mark.parametrize("extension", ["odt", "docx", "xlsx"])
def test_failed_conversion_does_not_feed_binary_bytes_to_expert(tmp_path, extension):
    path = tmp_path / f"input/docs/broken.{extension}"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\x00\x01not an archive")
    report = track.input_text_report(tmp_path)
    assert report["text"] == ""
    assert report["files_skipped"][0]["path"] == f"docs/broken.{extension}"
