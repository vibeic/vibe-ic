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

import hashlib
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


# A8 fallback: use the frozen producer's declaration fixture and validators.
# These are file-contract tests, not native Magic/ngspice measurements.
def _a8_subject(tmp_path, content="structure_and_geometry"):
    fixtures = importlib.import_module("test_analog_a8_hardmacro_emit")
    fixtures.test_declared_a3_subject_binding_is_emitted_by_a8(tmp_path)
    project = tmp_path / "proj"
    b = project / "phase3/analog/blk"
    if content != "structure_and_geometry":
        sidecar = b / "netlist_provenance.json"
        doc = json.loads(sidecar.read_text())
        doc["_provenance"]["design_content"] = content
        sidecar.write_text(json.dumps(doc))
        path = b / "a8_measurement.json"
        rec = json.loads(path.read_text())
        rec.pop("design_content")
        rec.pop("subject_binding")
        path.write_text(json.dumps(rec))
        producer = importlib.import_module("analog_a8_hardmacro_emit")
        topo = json.loads((b / "topology.json").read_text())
        measured, why = producer.load_native_measurement(project, "blk", b / "blk.gds", topo)
        assert measured is not None, why
        bound, why = producer._attach_declared_subject_binding(project, "blk", topo, measured)
        assert bound is not None, why
    with pytest.MonkeyPatch.context() as mp:
        _emit_test_views(project, b, mp)
    return project, b


def _rewrite(path, change):
    doc = json.loads(path.read_text())
    change(doc)
    path.write_text(json.dumps(doc))
    if path.name == "a8_measurement.json":
        manifest = path.parents[1] / "hardmacro" / path.parent.name / "a8_views_provenance.json"
        if manifest.is_file():
            package = json.loads(manifest.read_text())
            native = package["native_measurement"]
            native["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            for key in native.keys() - {"path", "sha256"}:
                native[key] = doc.get(key)
            manifest.write_text(json.dumps(package))


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


@pytest.mark.parametrize("key", [
    "netlist_provenance", "a3_netlist", "topology", "spec", "declared_block_list",
])
@pytest.mark.parametrize("mutation", ["stale", "missing"])
def test_a8_current_input_required(tmp_path, key, mutation):
    project, b = _a8_subject(tmp_path)
    rec = json.loads((b / "a8_measurement.json").read_text())
    path = project / rec["subject_binding"][key]
    if mutation == "missing":
        path.unlink()
    else:
        path.write_bytes(path.read_bytes() + b" ")
    assert c.hardmacro_content(b).klass == c.CONTENT_UNDISCLOSED


@pytest.mark.parametrize("key,value", [
    ("producer", "foreign_producer"), ("source", "corner_results"),
    ("block", "other"), ("design_content", "structure_only"),
    ("a3_netlist", "../foreign/blk.sp"), ("spec_sha256", "f" * 64),
    ("declared_block_list_sha256", 123),
])
def test_a8_binding_must_equal_current_a3_declaration(tmp_path, key, value):
    _, b = _a8_subject(tmp_path)
    _rewrite(b / "a8_measurement.json", lambda doc: doc["subject_binding"].__setitem__(key, value))
    assert c.hardmacro_content(b).klass == c.CONTENT_UNDISCLOSED


@pytest.mark.parametrize("value", [None, {}, [], True, "unknown", "structure_only"])
def test_a8_disclosure_cannot_be_invented_or_changed(tmp_path, value):
    _, b = _a8_subject(tmp_path)
    _rewrite(b / "a8_measurement.json", lambda doc: doc.__setitem__("design_content", value))
    assert c.hardmacro_content(b).klass == c.CONTENT_UNDISCLOSED


@pytest.mark.parametrize("value", [None, [], "not-a-binding", {}])
def test_a8_binding_object_required(tmp_path, value):
    _, b = _a8_subject(tmp_path)
    _rewrite(b / "a8_measurement.json", lambda doc: doc.__setitem__("subject_binding", value))
    assert c.hardmacro_content(b).klass == c.CONTENT_UNDISCLOSED


@pytest.mark.parametrize("key,value", [
    ("status", "FAIL"), ("status", "INCOMPLETE"), ("provenance", "ai_authored"),
    ("block", "foreign"), ("value", 0.6), ("value", 0), ("value", None),
    ("unit", "V"), ("image_digest", "unbound-image"),
    ("declared_ports", ["vdd", "vss", "wrong", "vout"]),
])
def test_a8_native_measurement_still_has_to_validate(tmp_path, key, value):
    _, b = _a8_subject(tmp_path)
    _rewrite(b / "a8_measurement.json", lambda doc: doc.__setitem__(key, value))
    assert c.hardmacro_content(b).klass == c.CONTENT_UNDISCLOSED


@pytest.mark.parametrize("filename", [
    "layout.mag", "blk.gds", "post_layout_extracted.spice", "a8_native_measurement.ngspice.log",
])
def test_a8_native_input_bytes_are_current(tmp_path, filename):
    _, b = _a8_subject(tmp_path)
    path = b / filename
    path.write_bytes(path.read_bytes() + b"changed")
    assert c.hardmacro_content(b).klass == c.CONTENT_UNDISCLOSED


def test_a8_wrong_extracted_top_refuses_even_with_current_hash(tmp_path):
    _, b = _a8_subject(tmp_path)
    net = b / "post_layout_extracted.spice"
    net.write_text(".subckt foreign vdd vss vin vout\n.ends foreign\n")
    _rewrite(b / "a8_measurement.json", lambda doc: doc.__setitem__(
        "source_netlist_sha256", hashlib.sha256(net.read_bytes()).hexdigest()))
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
    for i, port in enumerate(["vdd", "vss", "vin", "vout"]):
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
    # Normal CLIs, actual four-view manifest and leakage-only analog Liberty.
    assert "cell_rise" not in (h / "blk.lib").read_text()
    assert gen.main([str(project), "--json", str(project / "gen.json")]) == 0
    assert json.loads((project / "gen.json").read_text())["verdict"] == verdict
    result = liberty.run_audit(project)
    assert result.passed, result.findings
    tier = "design_bound_blocks" if verdict == "PASS" else "structure_only_blocks"
    assert "blk" in result.summary[tier]


@pytest.mark.parametrize("mutation", ["missing_view", "wrong_value", "failed_measurement", "stale_a3"])
def test_a8_existing_consumers_keep_refusals(tmp_path, mutation):
    project, b = _a8_subject(tmp_path)
    h = project / "phase3/analog/hardmacro/blk"
    if mutation == "missing_view":
        (h / "blk.lib").unlink()
    elif mutation == "stale_a3":
        (b / "blk.sp").write_text("* changed A3\n")
    else:
        key, value = ("value", 0.6) if mutation == "wrong_value" else ("status", "FAIL")
        _rewrite(b / "a8_measurement.json", lambda doc: doc.__setitem__(key, value))
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


@pytest.mark.parametrize("mutation", ["missing_manifest", "stale_receipt", "foreign_receipt", "missing_gds"])
def test_a8_package_consumes_exact_current_measurement(tmp_path, mutation):
    project, b = _a8_subject(tmp_path)
    h = project / "phase3/analog/hardmacro/blk"
    manifest = h / "a8_views_provenance.json"
    if mutation == "missing_manifest":
        manifest.unlink()
    elif mutation == "missing_gds":
        (h / "blk.gds").unlink()
    else:
        key, value = ("sha256", "f" * 64) if mutation == "stale_receipt" else ("path", "../foreign/a8_measurement.json")
        _rewrite(manifest, lambda doc: doc["native_measurement"].__setitem__(key, value))
    assert c.hardmacro_content(b).klass == c.CONTENT_UNDISCLOSED
    gen = importlib.import_module("analog_a8_hardmacro_gen_check")
    liberty = importlib.import_module("analog_liberty_nonzero_delay_check")
    assert gen.main([str(project), "--json", str(project / "gen.json")]) == 1
    assert not liberty.run_audit(project).passed


@pytest.mark.parametrize("suffix", [".lef", ".lib", ".gds", ".v"])
def test_a8_all_published_views_remain_current(tmp_path, suffix):
    project, b = _a8_subject(tmp_path)
    path = project / "phase3/analog/hardmacro/blk" / f"blk{suffix}"
    path.write_bytes(path.read_bytes() + b"changed")
    assert c.hardmacro_content(b).klass == c.CONTENT_UNDISCLOSED


@pytest.mark.parametrize("filename", ["netlist_provenance.json", "topology.json", "spec.json"])
def test_a8_malformed_current_a3_input_refuses(tmp_path, filename):
    _, b = _a8_subject(tmp_path)
    (b / filename).write_text("[]")
    assert c.hardmacro_content(b).klass == c.CONTENT_UNDISCLOSED
