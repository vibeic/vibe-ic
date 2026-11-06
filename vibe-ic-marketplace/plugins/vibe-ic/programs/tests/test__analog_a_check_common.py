#!/usr/bin/env python3
"""Tests for _analog_a_check_common.py — shared A1-A8 gate helpers.

Pins the real shared logic the analog presence/substance gates rely on:
  * load_block_list parses the canonical
    phase3/analog/analog_block_list.json into a list of block names,
    tolerating string-list / list-of-dicts / bare-list / missing /
    garbage forms.
  * select_blocks honours the --block restriction.
  * The report emitters return the runner's exit-code contract:
    VACUOUS_PASS=0, PASS=0, FAIL=1, WAIVED(artefact-missing)=2, and
    write the matching verdict JSON.

logic-pinned.
"""
from __future__ import annotations

import importlib
import json
import shlex
from pathlib import Path

import pytest

import _analog_a_check_common as c


def _block_dir(project):
    d = project / "phase3" / "analog"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── load_block_list — all input shapes ───────────────────────────────
def test_load_block_list_missing_returns_none(tmp_path):
    # No file at all -> None means "no analog work declared".
    assert c.load_block_list(tmp_path) is None


def test_load_block_list_reads_declared_document_without_a_second_list(tmp_path):
    docs = tmp_path / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L5_ADI_SPEC.json").write_text(json.dumps({
        "analog_blocks": [{"name": "unit"}]}))
    assert c.load_block_list(tmp_path) == ["unit"]
    assert c.block_list_path(tmp_path) is None


def test_load_block_list_string_list(tmp_path):
    d = _block_dir(tmp_path)
    (d / "analog_block_list.json").write_text(
        json.dumps({"blocks": ["ldo", "bandgap"]}))
    assert c.load_block_list(tmp_path) == ["ldo", "bandgap"]


def test_load_block_list_dict_entries(tmp_path):
    d = _block_dir(tmp_path)
    (d / "analog_block_list.json").write_text(
        json.dumps({"blocks": [{"name": "ldo"}, {"block": "pll"}, {}]}))
    # dict entries resolved via name/block; empty dict skipped
    assert c.load_block_list(tmp_path) == ["ldo", "pll"]


def test_load_block_list_bare_list(tmp_path):
    d = _block_dir(tmp_path)
    (d / "analog_block_list.json").write_text(json.dumps(["a", "b"]))
    assert c.load_block_list(tmp_path) == ["a", "b"]


def test_load_block_list_garbage_json_returns_empty(tmp_path):
    d = _block_dir(tmp_path)
    (d / "analog_block_list.json").write_text("{not valid json")
    # file present but unparseable -> [] (present, but no usable blocks)
    assert c.load_block_list(tmp_path) == []


def test_load_block_list_no_blocks_key_returns_empty(tmp_path):
    d = _block_dir(tmp_path)
    (d / "analog_block_list.json").write_text(json.dumps({"foo": 1}))
    assert c.load_block_list(tmp_path) == []


# ── select_blocks ────────────────────────────────────────────────────
def test_select_blocks_all_when_no_filter():
    assert c.select_blocks(["a", "b"], None) == ["a", "b"]


def test_select_blocks_filter_overrides_even_if_absent():
    # The runner may have created an out-of-list block dir on re-run.
    assert c.select_blocks(["a", "b"], "c") == ["c"]


# ── report emitters — exit-code contract ─────────────────────────────
def _args(tmp_path, block=None):
    ap = c.make_argparser("a_gate", "doc")
    argv = [str(tmp_path), "--json", str(tmp_path / "r.json")]
    if block:
        argv += ["--block", block]
    return ap.parse_args(argv)


def _verdict(tmp_path):
    return json.loads((tmp_path / "r.json").read_text())["verdict"]


def test_vacuous_pass_exit_0(tmp_path):
    rc = c.vacuous_pass("a_gate", _args(tmp_path), "no analog blocks declared")
    assert rc == 0
    assert _verdict(tmp_path) == "VACUOUS_PASS"


def test_emit_pass_exit_0(tmp_path):
    rc = c.emit_pass("a_gate", _args(tmp_path),
                     {"blocks_pass": 2, "blocks_checked": 2})
    assert rc == 0
    assert _verdict(tmp_path) == "PASS"


def test_emit_fail_exit_1(tmp_path):
    rc = c.emit_fail("a_gate", _args(tmp_path),
                     [{"block": "ldo", "rule": "STUB", "detail": "x"}],
                     {"blocks_checked": 1})
    assert rc == 1
    assert _verdict(tmp_path) == "FAIL"


def test_artefact_missing_for_block_exit_2(tmp_path):
    rc = c.artefact_missing_for_block(
        "a_gate", _args(tmp_path, block="ldo"), "ldo",
        "analog/ldo.sp", "analog-netlist-gen")
    assert rc == 2
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["verdict"] == "WAIVED"
    assert rep["suggested_skill"] == "analog-netlist-gen"


def test_write_report_noop_when_path_none(tmp_path):
    # write_report with no --json path must not raise and must not write.
    ap = c.make_argparser("a_gate", "doc")
    args = ap.parse_args([str(tmp_path)])
    c.write_report(args.json, {"x": 1})
    assert not (tmp_path / "r.json").exists()


# These file-contract tests reuse the existing native transport fixture.
def _a8_subject(tmp_path, content="structure_and_geometry"):
    fixtures = importlib.import_module("test_analog_a8_hardmacro_emit")
    producer = importlib.import_module("analog_a8_hardmacro_emit")
    with pytest.MonkeyPatch.context() as mp:
        project, b, topo = fixtures._source_power_fixture(tmp_path, mp)
        (b / "spec.json").write_text(json.dumps({
            "block": "blk",
            "interface": {"pins": [{"name": port} for port in topo["ports"]]},
        }))
        (b / "netlist_provenance.json").write_text(json.dumps({
            "block": "blk", "_provenance": {"design_content": content},
        }))
        measured, why = producer._native_measurement_produce(
            project, "blk", "", "/pdk", b / "blk.gds", topo)
        assert measured is not None, why
        _emit_test_views(project, b, mp)
    return project, b


def _rewrite(path, change):
    doc = json.loads(path.read_text())
    change(doc)
    path.write_text(json.dumps(doc))


@pytest.mark.parametrize("content,klass", [
    ("structure_and_geometry", c.CONTENT_DESIGN_BOUND),
    ("structure_only", c.CONTENT_STRUCTURE_ONLY),
])
def test_a8_current_declared_native_subject(tmp_path, content, klass):
    project, b = _a8_subject(tmp_path, content)
    before = {p: p.read_bytes() for p in project.rglob("*") if p.is_file()}
    answer = c.hardmacro_content(b)
    assert answer.klass == klass
    assert answer.source == b / "a8_measurement.json"
    assert answer.ceiling == klass and answer.refused is None
    assert before == {p: p.read_bytes() for p in project.rglob("*") if p.is_file()}
    assert not (b / "corner_results.json").exists()


@pytest.mark.parametrize("key", ["netlist_provenance", "topology"])
@pytest.mark.parametrize("mutation", ["missing"])
def test_a8_current_input_required(tmp_path, key, mutation):
    _, b = _a8_subject(tmp_path)
    path = b / f"{key}.json"
    path.unlink()
    assert c.hardmacro_content(b).klass == c.CONTENT_UNDISCLOSED


@pytest.mark.parametrize("key,value", [
    ("status", "FAIL"), ("status", "INCOMPLETE"), ("block", "foreign"),
])
def test_a8_native_measurement_still_has_to_validate(tmp_path, key, value):
    _, b = _a8_subject(tmp_path)
    _rewrite(b / "a8_measurement.json", lambda doc: doc.__setitem__(key, value))
    assert c.hardmacro_content(b).klass == c.CONTENT_UNDISCLOSED


def test_a8_wrong_extracted_top_refuses_even_with_current_hash(tmp_path):
    project, b = _a8_subject(tmp_path)
    rec = json.loads((b / "a8_measurement.json").read_text())
    net = project / rec["source_netlist"]
    net.write_text(".subckt foreign vdd vss vin vout\n.ends foreign\n")
    assert c.hardmacro_content(b).klass == c.CONTENT_UNDISCLOSED


@pytest.mark.parametrize("body", ["{broken", "[]", "null", '{}'])
def test_a8_malformed_record_refuses(tmp_path, body):
    _, b = _a8_subject(tmp_path)
    (b / "a8_measurement.json").write_text(body)
    assert c.hardmacro_content(b).klass == c.CONTENT_UNDISCLOSED


@pytest.mark.parametrize("body,klass", [
    ('{"design_content":"structure_only"}', c.CONTENT_STRUCTURE_ONLY),
    ('{"design_content":"structure_and_geometry"}', c.CONTENT_DESIGN_BOUND),
    ('{"verdict":"FAIL"}', c.CONTENT_UNDISCLOSED),
    ('{"verdict":"INCOMPLETE"}', c.CONTENT_UNDISCLOSED),
    ('{"design_content":"unknown"}', c.CONTENT_UNDISCLOSED),
    ('{}', c.CONTENT_UNDISCLOSED), ('{broken', c.CONTENT_UNDISCLOSED),
])
def test_a8_existing_corner_keeps_precedence(tmp_path, body, klass):
    _, b = _a8_subject(tmp_path)
    corner = b / "corner_results.json"
    corner.write_text(body)
    answer = c.hardmacro_content(b)
    assert answer.klass == klass
    assert answer.source != b / "a8_measurement.json"


def _emit_test_views(project, b, monkeypatch):
    producer = importlib.import_module("analog_a8_hardmacro_emit")
    lef = "MACRO blk\n  SIZE 4 BY 4 ;\n"
    for i, port in enumerate(json.loads((b / "topology.json").read_text())["ports"]):
        lef += (f"  PIN {port}\n    PORT\n      LAYER Metal3 ; RECT {i} 0 {i+1} 1 ;\n"
                f"    END\n  END {port}\n")
    lef += "END blk\n"
    def fake_magic(container, cmd, timeout=900, *, marker=None, log_path=None):
        assert "magic" in cmd
        # Follow the producer's current output contract instead of writing to
        # the historical final path.  The producer deliberately asks Magic to
        # write a unique staging file and publishes it only after a successful,
        # non-empty native result.
        tcl = project / "phase3/analog/hardmacro/blk/blk_lef.tcl"
        write = next(
            (shlex.split(line) for line in tcl.read_text().splitlines()
             if line.startswith("lef write ")),
            None,
        )
        assert write is not None and write[:2] == ["lef", "write"], \
            tcl.read_text()
        path = Path(write[2])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(lef)
        return 0, "A8_LEF_OK", ""
    monkeypatch.setattr(producer, "magicrc_for", lambda *a, **k: "/fixture/sky130A.magicrc")
    monkeypatch.setattr(producer, "_docker_exec", fake_magic)
    result = producer.emit_block(project, "blk", "fixture", "/fixture")
    assert result["emitted"], result
    return project / "phase3/analog/hardmacro/blk"


@pytest.mark.parametrize("content,verdict", [
    ("structure_and_geometry", "PASS"), ("structure_only", "PASS_STRUCTURE_ONLY"),
])
def test_a8_both_existing_consumers_accept_declared_subject(tmp_path, content, verdict):
    project, b = _a8_subject(tmp_path, content)
    h = project / "phase3/analog/hardmacro/blk"
    gen = importlib.import_module("analog_a8_hardmacro_gen_check")
    liberty = importlib.import_module("analog_liberty_nonzero_delay_check")
    # Normal CLIs, emitted views and leakage-only analog Liberty.
    assert "cell_rise" not in (h / "blk.lib").read_text()
    assert gen.main([str(project), "--json", str(project / "gen.json")]) == 0
    assert json.loads((project / "gen.json").read_text())["verdict"] == verdict
    result = liberty.run_audit(project)
    assert result.passed, result.findings
    tier = "design_bound_blocks" if verdict == "PASS" else "structure_only_blocks"
    assert "blk" in result.summary[tier]


@pytest.mark.parametrize("mutation", ["missing_view", "failed_measurement"])
def test_a8_existing_consumers_keep_refusals(tmp_path, mutation):
    project, b = _a8_subject(tmp_path)
    h = project / "phase3/analog/hardmacro/blk"
    if mutation == "missing_view":
        (h / "blk.lib").unlink()
    else:
        _rewrite(b / "a8_measurement.json", lambda doc: doc.__setitem__("status", "FAIL"))
    gen = importlib.import_module("analog_a8_hardmacro_gen_check")
    liberty = importlib.import_module("analog_liberty_nonzero_delay_check")
    assert gen.main([str(project), "--json", str(project / "gen.json")]) == 1
    assert json.loads((project / "gen.json").read_text())["verdict"] == "FAIL"
    assert not liberty.run_audit(project).passed


@pytest.mark.parametrize("filename", ["a8_measurement.json", "netlist_provenance.json"])
def test_a8_complementary_missing_data_cannot_be_combined(tmp_path, filename):
    _, b = _a8_subject(tmp_path)
    (b / filename).unlink()
    assert c.hardmacro_content(b).klass == c.CONTENT_UNDISCLOSED


@pytest.mark.parametrize("mutation", ["missing_gds"])
def test_a8_package_consumes_exact_current_measurement(tmp_path, mutation):
    project, b = _a8_subject(tmp_path)
    h = project / "phase3/analog/hardmacro/blk"
    (h / "blk.gds").unlink()
    assert c.hardmacro_content(b).klass == c.CONTENT_UNDISCLOSED
    gen = importlib.import_module("analog_a8_hardmacro_gen_check")
    liberty = importlib.import_module("analog_liberty_nonzero_delay_check")
    assert gen.main([str(project), "--json", str(project / "gen.json")]) == 1
    assert not liberty.run_audit(project).passed


@pytest.mark.parametrize("filename", ["netlist_provenance.json", "topology.json", "spec.json"])
def test_a8_malformed_current_a3_input_refuses(tmp_path, filename):
    _, b = _a8_subject(tmp_path)
    (b / filename).write_text("[]")
    assert c.hardmacro_content(b).klass == c.CONTENT_UNDISCLOSED
