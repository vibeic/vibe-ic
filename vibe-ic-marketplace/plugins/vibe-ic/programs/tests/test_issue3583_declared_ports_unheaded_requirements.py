#!/usr/bin/env python3
"""Issue #3583: declared bullet ports and owned unheaded requirements."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import phase1_doc_one_shot_runner as producer  # noqa: E402


VERBATIM = (
    "Implement a module named probe_core.\n"
    "- output alpha (5 bits)\n"
    "The output must remain asserted until the input is acknowledged.\n"
    "Every accepted transaction must be returned in arrival order.\n"
)
FIXTURE = PROGRAMS / "tests" / "fixtures" / "phase1_local" / \
    "neutral_declared_module" / "design.md"


def test_issue3583_intake_fixture_is_the_verbatim_source():
    assert FIXTURE.read_text() == VERBATIM


def _produce(tmp_path: Path, text: str, filename: str = "design.md"):
    docs_dir = tmp_path / "input" / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / filename).write_text(text)
    docs = {filename: text}
    producer.gen_l1_datasheet(tmp_path, docs)
    producer.gen_l2_frs(tmp_path, docs)
    producer.gen_l9_integration_spec(tmp_path, docs, {})
    generated = tmp_path / "phase1" / "generated_docs"
    return tuple(json.loads((generated / name).read_text()) for name in (
        "L1_DATASHEET.json", "L2_FRS.json", "L9_INTEGRATION_SPEC.json"))


def test_issue3583_verbatim_reaches_actual_l2_consumer(tmp_path):
    _l1, l2, _l9 = _produce(tmp_path, VERBATIM)
    assert [row["content"] for row in l2["frs_sections"]] == [VERBATIM.strip()]
    assert l2["frs_sections"][0]["evidence"] == "input/docs/design.md"


def test_issue3583_verbatim_reaches_actual_l9_consumer(tmp_path):
    l1, _l2, l9 = _produce(tmp_path, VERBATIM)
    assert [(p["name"], p["mode"], p["width"]) for p in l1["pin_table"]] == [
        ("alpha", "output", 5)]
    for key in ("ports", "top_ports", "top_module_pins"):
        assert [(p["name"], p["direction"], p["width"], p["msb"], p["lsb"])
                for p in l9[key]] == [("alpha", "output", 5, 4, 0)]
        assert l9[key][0]["evidence"] == "input/docs/design.md"


def test_issue3583_non_port_bullets_remain_refused(tmp_path):
    text = (
        "Implement a module named probe_core.\n"
        "- Input validation is performed by the host.\n"
        "- Output format follows the tool convention.\n"
        "- output the result to the console when done\n"
    )
    l1, _l2, l9 = _produce(tmp_path, text)
    assert l1["pin_table"] == []
    assert all(l9[key] == [] for key in ("ports", "top_ports", "top_module_pins"))


@pytest.mark.parametrize(("filename", "text"), [
    ("setup.md", "Module Name: probe_core\nRun pip install tools.\n"),
    ("design.md", "Module Name: first_core\nModule Name: second_core\nUnknown ownership.\n"),
    ("README.md", "For example:\nmodule sample_unit(input DataIn, output DataOut);\nendmodule\n"),
])
def test_issue3583_unheaded_setup_or_ambiguous_docs_remain_refused(
        tmp_path, filename, text):
    _l1, l2, _l9 = _produce(tmp_path, text, filename)
    assert l2["frs_sections"] == []
    assert l2["no_frs_sections_in_input"] is True


def test_issue3583_headed_document_keeps_existing_section_shape(tmp_path):
    text = (
        "Module Name: probe_core\n\n"
        "## Output behavior\n"
        "The output must remain stable until acknowledged.\n"
    )
    _l1, l2, _l9 = _produce(tmp_path, text)
    assert [(row["section"], row["title"], row["content"],
             row["heading_shape"]) for row in l2["frs_sections"]] == [
        ("h2", "Output behavior",
         "The output must remain stable until acknowledged.", "md_atx")]


@pytest.mark.parametrize("source", [
    "module held_value(output logic [7:0] q); initial q=8'h5a; endmodule\n"
    "module neutral_top(input enable, isolate, output [7:0] y); held_value state(y); endmodule\n",
    "module neutral_top #(parameter W=8)(input [W-1:0] d, output [W-1:0] q); assign q=d; endmodule\n",
    "module neutral_top(d,q); input d; output q; assign q=d; endmodule\n",
])
def test_raw_module_requirements_publish_through_normal_step(tmp_path, source):
    passed, _ = producer._v1_6_580_run_step_with_watchdog(
        lambda: producer.gen_l2_frs(tmp_path, {"design.sv": source}),
        "L2_FRS", "L2_FRS", tmp_path)
    assert passed is True
    path=tmp_path/"phase1/generated_docs/L2_FRS.json"
    body=json.loads(path.read_text())
    assert [row["content"] for row in body["frs_sections"]] == [source.strip()]


@pytest.mark.parametrize("source", [
    "// module neutral_top(input d, output q); endmodule\n",
    "/* module neutral_top(input d, output q); endmodule */\n",
    'The log says "module neutral_top(input d, output q); endmodule".\n',
    "For example:\nmodule neutral_top(input d, output q); endmodule\n",
])
def test_noncurrent_module_header_does_not_author_requirements(tmp_path, source):
    producer.gen_l2_frs(tmp_path, {"design.txt": source})
    body=json.loads((tmp_path/"phase1/generated_docs/L2_FRS.json").read_text())
    assert body["frs_sections"] == []
