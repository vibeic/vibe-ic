"""A6 LibreLane DRC arm: KLayout.DRC + Magic.DRC on the block GDS, with the
graded-rule union and A6's own attribution on top (T94).

MEASURED on vibeic-eda 0.3.77 / u_hawaii_adc: KLayout.DRC graded 549 rules
with 0 violations on both blocks; Magic.DRC on the GDS found M2.d (60 / 954,
the PDK gencell's own, as A6's attribution already says) and MIM.e (4 / 92),
which the native second engine — run on `layout.mag` — never saw. A bare
`cap_cmim` gencell is clean as .mag and fires exactly 4 MIM.e after Magic's
own GDS write/read, so MIM.e stays BLOCKING until an attribution control
exists on the GDS: an ungraded violation on the deliverable with no
attribution is unadjudicated, never excused.

The end-to-end test drives the shipped `run()` through the real contract
against a stub `docker` that only writes what the two LibreLane steps write
(state_out.json, metrics, the lyrdb report).
"""
from __future__ import annotations

import json
import os
import base64
from pathlib import Path
from types import SimpleNamespace

import pytest


import _plugin_tree  # noqa: F401 — puts programs/ on sys.path
import _eda_pin as PIN
import analog_a6_librelane_drc as A6

from _stated_eda_image import stated_image, state_the_image  # noqa: E402

# STATED, not resolved at import: `PIN.IMAGE_DIGEST` here asked this host's
# docker while the module was collected, so inside the image (no docker) the
# whole file was a collection error. The identity is stated at `_eda_pin`, and
# every read of `PIN.IMAGE_DIGEST` below still goes through it.
IMAGE = stated_image()


@pytest.fixture(autouse=True)
def _stated_identity(monkeypatch):
    state_the_image(monkeypatch)


def _lyrdb(cats, items):
    c = "".join(f"<category><name>{n}</name><description>d</description>"
                f"</category>" for n in cats)
    i = "".join(f"<item><cell>blk</cell><category>'{n}'</category>"
                f"<values><value>polygon: (0,0;1,0;1,1;0,1)</value></values>"
                f"</item>" for n in items)
    return ("<?xml version='1.0' encoding='utf8'?><report-database><cells>"
            "<cell><name>blk</name></cell></cells><categories>" + c +
            "</categories><items>" + i + "</items></report-database>")


def test_graded_rules_include_the_ones_that_did_not_fire(tmp_path):
    p = tmp_path / "r.lyrdb"
    p.write_text(_lyrdb(["A.1", "B.2", "C.3"], ["B.2", "B.2"]))
    assert A6.lyrdb_rules(p) == {"graded": ["A.1", "B.2", "C.3"],
                                 "violations": {"B.2": 2}}


def test_only_a_device_cell_attribution_excuses_an_ungraded_magic_rule():
    klayout = {"graded": ["A.1", "M.x"], "violations": {}}
    magic = {"graded": ["G.1", "U.2", "M.x"],
             "violations": {"G.1": 60, "U.2": 4, "M.x": 3}}
    u = A6.union(klayout, magic, {"G.1"})
    assert u["excused_as_pdk_device_cell"] == {"G.1": 60}
    assert u["blocking"] == {"magic:U.2": 4}
    # a rule the sign-off deck grades is its verdict, never Magic's
    assert u["magic_deferred_to_signoff_deck"] == {"M.x": 3}
    u2 = A6.union({"graded": ["A.1"], "violations": {"A.1": 1}},
                  {"graded": [], "violations": {}}, set())
    assert u2["blocking"] == {"A.1": 1}


def test_the_native_attribution_names_device_cell_rules_by_id():
    att = {"by_class_and_rule": {
        "DEVICE_CELL": {"Metal2 minimum area < 0.144um^2 (M2.d)": 60},
        "LAYOUT": {"Something (X.9)": 2}}}
    assert A6.native_device_cell_rules(att) == {"M2.d"}


STUB = r'''#!/usr/bin/env python3
import json, os, re, sys
a = sys.argv[1:]
j = " ".join(a)
if a[0] == "run":
    if "--help" in j:
        sys.exit(0)
    if "-c" in a and "Config.load" in a[-1]:
        src = re.search(r"p='([^']+)'", a[-1]).group(1)
        out = re.search(r"out='([^']+)'", a[-1]).group(1)
        open(out, "w").write(open(src).read())
        sys.exit(0)
    if "librelane.steps" in a:
        step = a[a.index("--id") + 1]
        folder = a[a.index("-o") + 1]
        state = json.load(open(a[a.index("-i") + 1]))
        os.makedirs(os.path.join(folder, "reports"), exist_ok=True)
        if step == "KLayout.DRC":
            name, key = "drc.klayout.lyrdb", "klayout__drc_error__count"
            body = os.environ["STUB_KLAYOUT"]
        else:
            name, key = "drc.magic.lyrdb", "magic__drc_error__count"
            body = os.environ["STUB_MAGIC"]
        open(os.path.join(folder, "reports", name), "w").write(body)
        state["metrics"] = {key: body.count("<item>")}
        open(os.path.join(folder, "state_out.json"), "w").write(json.dumps(state))
        sys.exit(0)
sys.exit(1)
'''


def _project(tmp_path):
    project = tmp_path / "proj"
    b = project / "phase3/analog/blk"
    b.mkdir(parents=True)
    tech = tmp_path / "root/tpdk/libs.tech/magic/t.tech"
    tech.parent.mkdir(parents=True)
    tech.write_text("tech\nend\n")
    (b / "blk.gds").write_bytes(b"\x00\x06\x00\x02\x02\x58")
    (b / "layout_provenance.json").write_text(json.dumps(
        {"pdk_sources": {"magic_tech": str(tech)}}))
    return project


@pytest.fixture
def stub(tmp_path, monkeypatch):
    d = tmp_path / "bin"
    d.mkdir()
    (d / "docker").write_text(STUB)
    (d / "docker").chmod(0o755)
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("STUB_KLAYOUT", _lyrdb(["A.1", "G.x"], []))
    return tmp_path


def test_an_unattributed_ungraded_rule_on_the_gds_blocks(stub, monkeypatch):
    monkeypatch.setenv("STUB_MAGIC", _lyrdb(["G.1", "U.2"],
                                            ["G.1"] * 3 + ["U.2"] * 4))
    project = _project(stub)
    att = {"by_class_and_rule": {"DEVICE_CELL": {"cell rule (G.1)": 3}}}
    assert A6.run(project, "blk", IMAGE, att) == 1
    rec = json.loads((project / "phase3/analog/blk/a6_librelane_drc.json")
                     .read_text())
    assert rec["result"] == "BLOCKING"
    assert rec["union"]["blocking"] == {"magic:U.2": 4}
    assert rec["union"]["signoff_rules_graded"] == 2
    assert len(list((project / "phase3/librelane/analog/blk").glob(
        "a6_*/01-*/vibeic_receipt.json"))) == 2


def test_only_gencell_violations_are_clean(stub, monkeypatch):
    monkeypatch.setenv("STUB_MAGIC", _lyrdb(["G.1"], ["G.1"] * 3))
    project = _project(stub)
    att = {"by_class_and_rule": {"DEVICE_CELL": {"cell rule (G.1)": 3}}}
    assert A6.run(project, "blk", IMAGE, att) == 0


def test_a_runset_that_graded_nothing_is_not_clean(stub, monkeypatch):
    monkeypatch.setenv("STUB_KLAYOUT", _lyrdb([], []))
    monkeypatch.setenv("STUB_MAGIC", _lyrdb([], []))
    assert A6.run(_project(stub), "blk", IMAGE, None) == 1


def test_a6_image_probe_uses_shared_container_supervisor(monkeypatch):
    import librelane_contract as contract
    calls = []

    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return type("CP", (), {"returncode": 0, "stdout": "probe",
                                "stderr": ""})()

    monkeypatch.setattr(contract, "run_container", run)
    result = A6._image_run("img", "python3", ["-c", "print('probe')"])
    assert result.returncode == 0
    assert calls[0][1] == {"probe_deadline_s": contract.PROBE_DEADLINE_S}
    assert calls[0][0][:3] == ["docker", "run", "--rm"]


def test_capability_unit_copy_preserves_binary_data_under_shared_probe(tmp_path,
                                                                       monkeypatch):
    import librelane_contract as contract
    unit_dir = "/deck/testing/testcases/unit"
    cache = tmp_path / "phase3/librelane/analog/_capability/unit_labels.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({"image": "img", "unit_dir": unit_dir,
                                 "labels": {"unit.gds": {"top": ["cell"],
                                                         "labels": ["M1.a"]}}}))
    raw = bytes(range(256)) + b"\x00\xff"
    calls = []

    def copy_probe(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return SimpleNamespace(returncode=0,
                               stdout="[INFO] startup PATH=/tool/bin\n" + A6._UNIT_PAYLOAD_MARKER +
                                      base64.b64encode(raw).decode() + "\n",
                               stderr="")

    monkeypatch.setattr(contract, "run_container", copy_probe)
    arm = SimpleNamespace(project=tmp_path, lc=contract,
                          run=lambda *_a, **_k: tmp_path / "empty_report")
    A6._capability_controls(arm, "block", "img", "/deck/main.lydrc",
                            {"/deck/main.lydrc": {}}, ["M1.a"])
    assert (cache.parent / "unit/unit.gds").read_bytes() == raw
    assert len(calls) == 1
    assert calls[0][1] == {"probe_deadline_s": contract.PROBE_DEADLINE_S}
    assert calls[0][0][-1] == f"{unit_dir}/unit.gds"


@pytest.mark.parametrize('stdout', ['', 'AA==\n', A6._UNIT_PAYLOAD_MARKER,
    A6._UNIT_PAYLOAD_MARKER + 'not!base64',
    A6._UNIT_PAYLOAD_MARKER + 'AA==\n' + A6._UNIT_PAYLOAD_MARKER + 'AA==\n'])
def test_testcase_copy_refuses_missing_malformed_or_ambiguous_payload(stdout):
    with pytest.raises(ValueError):
        A6._unit_case_bytes(stdout)


def test_the_runner_runs_the_arm_only_when_selected_and_it_is_stricter(
        tmp_path, monkeypatch):
    import analog_one_shot_runner as R
    project = _project(tmp_path)
    (project / "phase3/analog/analog_block_list.json").write_text(
        json.dumps({"blocks": [{"name": "blk", "type": "ldo"}]}))
    calls = []
    monkeypatch.setattr(R, "_a6_librelane_arm", lambda *a: calls.append(a) or {
        "blocking": True, "detail": "blocking={'magic:U.2': 4}"})
    real = R._pr.run
    monkeypatch.setattr(R._pr, "run", lambda cmd, *a, **k: (
        type("CP", (), {"returncode": 2, "stdout": "", "stderr": ""})()
        if any("drc_attribute" in str(x) for x in cmd) else real(cmd, *a, **k)))
    R.step_for_block(project, {"name": "blk", "type": "ldo"}, "A6_block_pv",
                     None)
    assert len(calls) == 1 and calls[0][3] == "librelane"
    (project / "phase3/librelane_switch.json").write_text(
        json.dumps({"steps": {"A6": "direct"}}))
    R.step_for_block(project, {"name": "blk", "type": "ldo"},
                     "A6_block_pv", None)
    assert len(calls) == 1
    (project / "phase3/librelane_switch.json").write_text(
        json.dumps({"steps": {"A6": "dual"}}))
    res = R.step_for_block(project, {"name": "blk", "type": "ldo"},
                           "A6_block_pv", None)
    assert len(calls) == 2 and calls[-1][3] == "dual"
    assert res.status == "FAIL" and "magic:U.2" in res.detail
