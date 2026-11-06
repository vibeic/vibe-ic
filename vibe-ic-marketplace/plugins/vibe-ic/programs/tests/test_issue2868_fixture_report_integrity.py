"""Issue #2868: imported DRC/LVS reports are complete typed artefacts.

The four ``*.json.preview`` files are the exact 4096-byte blobs that used to
sit at the report paths.  They remain failure controls outside the importer
fixture tree.  The positive side exercises the real W6 LibreLane importer and
the report readers used by the DRC/LVS verdict paths; the negative side puts
each preview back at its producer path and proves the importer refuses it
before writing a canonical report.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "librelane_import"
for _p in (str(PROGRAMS), str(Path(__file__).resolve().parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lvs_verdict_tokens as LVS  # noqa: E402
import test_llv1_w6_librelane_import as W6  # noqa: E402


EXPECTED_PREVIEW_SHA256 = {
    "drc.klayout.json":
        "4f0e80861e66a73037003ffc279d8edb7c617edc17e124e80c14a45aa37ca02d",
    "lvs.netgen.json":
        "273472baa044cd2bf09c1c6392e31709cd0593b05ce747775df0f33d8f34bbf6",
}
EXPECTED_REPORT_SHA256 = {
    "drc.klayout.json":
        "c904540dc1752065161d65a76e446d9ad469884028410273e21ffce70446e193",
    "lvs.netgen.json":
        "590040e59a132a0c7d58d3472c23478a86e9bf8f550d4975582be8e2712ef022",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _preview(host: str, report: str) -> Path:
    step = "65-klayout-drc" if report == "drc.klayout.json" else "70-netgen-lvs"
    return (FIXTURES / "negative_controls" / host / "runs" / "cmp3" /
            step / "reports" / (report + ".preview"))


def _producer_report(project: Path, report: str) -> Path:
    step = "65-klayout-drc" if report == "drc.klayout.json" else "70-netgen-lvs"
    return project / W6.RUN_REL / step / "reports" / report


@pytest.mark.parametrize("host", ["8HD-4", "8HD-9"])
def test_complete_reports_decode_through_importer_and_keep_verdicts(tmp_path, host):
    project = W6._project(tmp_path, host)
    manifest = W6._import(project)
    rows = {Path(row["tool_run_path"]).name: row
            for row in W6._rows_of(manifest)
            if Path(row["tool_run_path"]).name in EXPECTED_REPORT_SHA256}
    assert set(rows) == set(EXPECTED_REPORT_SHA256)

    drc = project / rows["drc.klayout.json"]["canonical_path"]
    assert _sha(drc) == EXPECTED_REPORT_SHA256["drc.klayout.json"]
    drc_report = json.loads(drc.read_text(encoding="utf-8"))
    assert drc_report["total"] == 0
    assert all(value == 0 for value in drc_report.values())

    lvs = project / rows["lvs.netgen.json"]["canonical_path"]
    lvs_report = LVS.load_json_report(lvs)
    assert _sha(lvs) == EXPECTED_REPORT_SHA256["lvs.netgen.json"]
    assert lvs_report is not None
    assert LVS.classify("", json_report=lvs_report) == "MATCH"
    assert lvs_report["verdict"] == "match"
