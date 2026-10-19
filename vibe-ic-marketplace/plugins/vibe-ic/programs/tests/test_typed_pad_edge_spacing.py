"""Field-owned spacing boundary, through the ordinary declaration consumer."""
from pathlib import Path
import json
import subprocess
import sys

import pytest

PROG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROG))
sys.path.insert(0, str(PROG / "tests"))
import _tapeout_declaration as TD
from _owner_declared import attest_explicit
from test_pad_assignment_reads_the_pdk_the_run_itself_read import _record


def declaration(project, value, key="pad_edge_spacing_um"):
    doc = TD.blank_declaration()
    doc["answers"][key] = value
    doc[TD.SYNTHESIS_AREA_BUDGET_KEY] = {"status": "NOT_APPLICABLE",
        "rationale": "This fixture checks a schema boundary, not physical size."}
    attest_explicit(doc)
    path = project / TD.DECLARATION_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc))
    return doc


def consumer(project):
    report = project / "declaration-consumer.json"
    done = subprocess.run([sys.executable, str(PROG / "tapeout_declaration_check.py"),
        str(project), "--json", str(report)], capture_output=True, text=True)
    return done.returncode, json.loads(report.read_text())


@pytest.mark.parametrize("value,rc", [
    pytest.param(0, 0, id="integer-zero"),
    pytest.param(0.0, 0, id="float-zero"),
    pytest.param(-0.0, 0, id="negative-zero"),
    pytest.param(0.5, 0, id="positive-float"),
    pytest.param(10**400, 0, id="large-integer-no-float-overflow"),
    pytest.param(-1, 1, id="negative-integer"),
    pytest.param(-0.5, 1, id="negative-float"),
    pytest.param(float("nan"), 1, id="nan"),
    pytest.param(float("inf"), 1, id="positive-infinity"),
    pytest.param(float("-inf"), 1, id="negative-infinity"),
    pytest.param(True, 1, id="boolean-true"),
    pytest.param(False, 1, id="boolean-false"),
    pytest.param("0", 1, id="string-zero"),
    pytest.param("1", 1, id="string-positive"),
])
def test_spacing_boundary_through_ordinary_consumer(tmp_path, value, rc):
    declaration(tmp_path, value)
    actual_rc, report = consumer(tmp_path)
    assert actual_rc == rc, report
    refusals = [(row["rule"], row.get("key")) for row in report["refusals"]]
    assert refusals == ([(TD.RULE_NUMBER_INVALID, "pad_edge_spacing_um")] if rc else []), report


@pytest.mark.parametrize("value,rc", [(0, 1), (-1, 1), (True, 1), ("1", 1), (0.001, 0)])
def test_database_unit_keeps_existing_positive_contract(tmp_path, value, rc):
    declaration(tmp_path, value, "database_unit_um")
    actual_rc, report = consumer(tmp_path)
    assert actual_rc == rc, report
    assert [(row["rule"], row.get("key")) for row in report["refusals"]] == (
        [(TD.RULE_NUMBER_INVALID, "database_unit_um")] if rc else []), report


def test_unanswered_spacing_is_not_a_default(tmp_path):
    doc = declaration(tmp_path, TD.NOT_DETERMINED)
    actual_rc, report = consumer(tmp_path)
    assert (actual_rc, report["refusals"]) == (0, []), report
    assert TD.answer(doc, "pad_edge_spacing_um") == TD.NOT_DETERMINED
    assert doc["answers"]["pad_edge_spacing_um"] == TD.NOT_DETERMINED


def test_absent_spacing_field_remains_malformed(tmp_path):
    doc = declaration(tmp_path, TD.NOT_DETERMINED)
    del doc["answers"]["pad_edge_spacing_um"]
    (tmp_path / TD.DECLARATION_REL).write_text(json.dumps(doc))
    actual_rc, report = consumer(tmp_path)
    assert actual_rc == 1, report
    assert [(row["rule"], row.get("key")) for row in report["refusals"]] == [
        (TD.RULE_FIELD_MISSING, "pad_edge_spacing_um")], report


def test_native_pad_assignment_zero_transcribes_to_typed_declaration(tmp_path):
    source = tmp_path / "reports/phase3/io_pad_chip_top.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps(_record({"PAD_SITE_NAME": "neutral_io",
        "PAD_CORNER_SITE_NAME": "neutral_corner", "PAD_EDGE_SPACING": "0"},
        {"PAD_EDGE_SPACING": "/neutral_pdk/io/config.tcl:9"})))
    produced = subprocess.run([sys.executable, str(PROG / "pad_assignment_gen.py"),
        str(tmp_path)], capture_output=True, text=True)
    assert produced.returncode == 0, produced.stdout + produced.stderr
    config = json.loads((tmp_path / "phase3/stage3/pnr/pad_assignment.json").read_text())
    assert config["PAD_EDGE_SPACING"] == "0"
    assert "/neutral_pdk/io/config.tcl:9" in config["_provenance"]["PAD_EDGE_SPACING"]
    declaration(tmp_path, float(config["PAD_EDGE_SPACING"]))
    actual_rc, report = consumer(tmp_path)
    assert (actual_rc, report["verdict"], report["refusals"]) == (0, "PASS", []), report
