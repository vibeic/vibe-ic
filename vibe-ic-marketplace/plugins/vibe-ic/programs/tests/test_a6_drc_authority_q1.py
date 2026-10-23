"""A6 DRC authority (owner decision q1, T109): the PDK's extra-rules deck,
the authority rule, the capability control and ENGINE_ARTEFACT, on BOTH arms.

MEASURED on vibeic-eda 0.3.79 / u_hawaii_adc (ihp-sg13g2):
  * the main KLayout deck (`ihp-sg13g2.drc`) grades neither `MIM.e` nor
    `M2.d`; the PDK's extra deck (`rule_decks/sg13g2_maximal.drc`, run by
    IHP's own `run_drc.py` by default) grades both — 272 categories;
  * on the block GDS the extra deck fires `M2.d` (ldo 20; delta_sigma 14
    deep / 272 flat) — a REAL Mn.d (0.144 um2) violation — and `MIM.e` 0;
  * on the PDK's unit `mim.gds` it fires `MIM.e` 1 (the capability control);
  * Magic fires `MIM.e` 4 on ldo's GDS read-back, and the bare `cap_cmim`
    gencell's own GDS round trip reproduces all 4 rectangles; the KLayout
    decks give 0 on that device GDS: an ENGINE_ARTEFACT.

Nothing inside vibe-ic is monkeypatched on the end-to-end paths except the
tool calls themselves (`_docker_exec`, the stub `docker`), which play what
the tools write.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import _plugin_tree  # noqa: F401 — puts programs/ on sys.path
import _eda_pin as PIN
import analog_a6_librelane_drc as LL
import analog_a6_native_pv as PV

from _stated_eda_image import stated_image, state_the_image  # noqa: E402

# STATED, not resolved at import: `PIN.IMAGE_DIGEST` here asked this host's
# docker while the module was collected, so inside the image (no docker) the
# whole file was a collection error. The identity is stated at `_eda_pin`, and
# every read of `PIN.IMAGE_DIGEST` below still goes through it.
IMAGE = stated_image()


@pytest.fixture(autouse=True)
def _stated_identity(monkeypatch):
    state_the_image(monkeypatch)
_M2_D = "Metal2 minimum area < 0.144um^2 (M2.d)"
_MIM_E = "MiM cap spacing to unrelated metal6 < 0.6um (MIM.e)"


def _lyrdb(cats, items):
    c = "".join(f"<category><name>'{n}'</name><description>d</description>"
                f"</category>" for n in cats)
    i = "".join(f"<item><cell>blk</cell><category>'{n}'</category>"
                f"<values><value>polygon: (0,0;1,0;1,1;0,1)</value></values>"
                f"</item>" for n in items)
    return ("<?xml version='1.0' encoding='utf8'?><report-database><cells>"
            "<cell><name>blk</name></cell></cells><categories>" + c +
            "</categories><items>" + i + "</items></report-database>")


def _authority():
    import _a6_drc_authority as A
    return A


# ── the extra deck is found by glob, per PDK ──────────────────────────────
@pytest.mark.parametrize("name", ["sg13g2_maximal.drc",
                                  "sg13cmos5l_maximal.drc"])
def test_the_extra_runset_is_found_by_glob_whatever_the_pdk_calls_it(
        tmp_path, name):
    A = _authority()
    (tmp_path / "rule_decks").mkdir()
    (tmp_path / "rule_decks" / name).write_text("#")
    (tmp_path / "rule_decks" / "layers_def.drc").write_text("#")
    assert [p.name for p in A.extra_runsets(tmp_path)] == [name]


def test_a_testcase_is_matched_to_a_rule_by_the_labels_it_carries():
    A = _authority()
    labels = {"mim.gds": {"top": ["mim"], "labels": [
                  "6.11 MIM", "FAIL", "PASS", "Mim.a/d", "Mim.e"]},
              "metal2.gds": {"top": ["metal2"], "labels": ["M2.d/e"]}}
    assert A.testcases_for_rule(labels, "MIM.e") == ["mim.gds"]
    assert A.testcases_for_rule(labels, "M2.d") == ["metal2.gds"]
    assert A.testcases_for_rule(labels, "MIM.d") == ["mim.gds"]
    assert A.testcases_for_rule(labels, "TM1.b") == []


# ── the authority rule ─────────────────────────────────────────────────────
def test_an_authoritative_hit_fails_even_inside_a_pdk_device_cell():
    """DEVICE_CELL used to excuse `M2.d`; once a deck grades it, the deck's
    hit is the foundry's and FAILs."""
    A = _authority()
    kl = {"graded": ["M2.d", "MIM.e"], "violations": {"M2.d": 20}}
    auth = A.authority(kl, {"M2.d": 60}, {"M2.d"})
    assert auth["blocking"] == {"M2.d": 20}
    assert auth["excused_as_pdk_device_cell_ungraded"] == {}
    assert auth["deferred_engines_agree"] == {"M2.d": 60}


def test_a_disagreement_without_a_capability_control_blocks():
    A = _authority()
    kl = {"graded": ["MIM.e"], "violations": {}}
    for cap in ({}, {"MIM.e": {"result": A.CAP_SILENT}},
                {"MIM.e": {"result": A.CAP_NO_TESTCASE}},
                {"MIM.e": {"result": A.CAP_NOT_MEASURED}}):
        auth = A.authority(kl, {"MIM.e": 4}, (), cap)
        assert auth["blocking"] == {"magic:MIM.e": 4}, cap
        assert auth["blocking_codes"] == {
            "magic:MIM.e": "A6_ENGINE_DISAGREEMENT_UNCONTROLLED"}


def test_a_controlled_disagreement_is_deferred_and_an_engine_artefact_needs_all_four():
    A = _authority()
    kl = {"graded": ["MIM.e"], "violations": {}}
    cap = {"MIM.e": {"result": A.CAP_PASS}}
    rt = {"result": "MEASURED", "rules": {"MIM.e": {
        "block_rects": 4, "reproduced_rects": 4, "reproduced": True,
        "cells": {"cap": 4}, "klayout_on_device_gds": {"cap": 0}}}}
    auth = A.authority(kl, {"MIM.e": 4}, (), cap, rt)
    assert auth["blocking"] == {}
    assert auth["deferred_by_capability_control"] == {"MIM.e": 4}
    assert list(auth["engine_artefact"]) == ["MIM.e"]
    # each condition, removed alone, un-names it (and it stays deferred)
    for broken in (
            {**rt["rules"]["MIM.e"], "reproduced": False},
            {**rt["rules"]["MIM.e"], "klayout_on_device_gds": {"cap": 1}},
            {**rt["rules"]["MIM.e"], "klayout_on_device_gds": {"cap": None}}):
        a2 = A.authority(kl, {"MIM.e": 4}, (), cap,
                         {"result": "MEASURED", "rules": {"MIM.e": broken}})
        assert a2["engine_artefact"] == {} and a2["blocking"] == {}
        assert "MIM.e" in a2["deferred_not_engine_artefact"]
    a3 = A.authority(kl, {"MIM.e": 4}, (), cap,
                     {"result": "NOT_MEASURED", "reason": "no container"})
    assert a3["engine_artefact"] == {}


def test_magic_stays_authoritative_for_rules_no_deck_grades():
    A = _authority()
    kl = {"graded": ["A.1"], "violations": {}}
    auth = A.authority(kl, {"G.1": 3, "U.2": 4}, {"G.1"})
    assert auth["excused_as_pdk_device_cell_ungraded"] == {"G.1": 3}
    assert auth["blocking"] == {"magic:U.2": 4}


# ── native arm: the extra deck runs, and M2.d FAILs ───────────────────────
def _staged_deck(tmp_path: Path) -> Path:
    d = tmp_path / "input/pdk/klayout/tech/drc"
    (d / "rule_decks").mkdir(parents=True)
    (d / "main.drc").write_text("#")
    (d / "rule_decks" / "tpdk_maximal.drc").write_text("#")
    return d / "main.drc"


def _fake_klayout(monkeypatch, bodies, rcs=None):
    """`klayout -b -r <deck>`: write the report the deck named would write."""
    calls = []
    rcs = list(rcs or [])
    monkeypatch.setattr(PV, "_tool_on_path", lambda ctn, t: "/usr/bin/" + t)
    monkeypatch.setattr(PV, "_to_container_path", lambda ctn, p: p)

    def fake_exec(container, cmd, *a, **k):
        import shlex
        argv = shlex.split(cmd)
        deck = argv[argv.index("-r") + 1]
        rpt = next(x.split("=", 1)[1] for x in argv
                   if x.startswith("report="))
        flat = "run_mode=flat" in cmd
        key = Path(deck).name + (":flat" if flat else "")
        calls.append(key)
        Path(rpt).write_text(bodies[key])
        return (rcs.pop(0) if rcs else 0), "", ""
    monkeypatch.setattr(PV, "_docker_exec", fake_exec)
    return calls


def test_the_native_runner_grades_the_extra_runset_beside_the_deck(
        tmp_path, monkeypatch):
    deck = _staged_deck(tmp_path)
    calls = _fake_klayout(monkeypatch, {
        "main.drc": _lyrdb(["A.1", "MIM.c"], []),
        "tpdk_maximal.drc": _lyrdb(["M2.d", "MIM.e"], ["M2.d", "M2.d"]),
        "tpdk_maximal.drc:flat": _lyrdb(["M2.d", "MIM.e"], ["M2.d"] * 7)})
    report = tmp_path / "drc.lyrdb"
    violations, meta = PV._klayout_drc_runner(str(deck), "/x.gds", "blk", "c",
                                              report)
    assert violations == 2
    assert calls == ["main.drc", "tpdk_maximal.drc", "tpdk_maximal.drc:flat"]
    auth = meta.get("authoritative") or {}
    assert set(auth.get("graded") or []) >= {"A.1", "MIM.c", "M2.d", "MIM.e"}
    assert meta["extra_runsets"][0]["flat_counts"] == {"M2.d": 7}
    # graded = distinct rules over both runsets, not `<category>` tags
    # (each violation item carries one too)
    assert meta["rules_pass"] == 4
    assert (tmp_path / "drc.tpdk_maximal.lyrdb").is_file()


def test_a_present_extra_runset_that_grades_nothing_is_no_evidence(
        tmp_path, monkeypatch):
    deck = _staged_deck(tmp_path)
    _fake_klayout(monkeypatch, {"main.drc": _lyrdb(["A.1"], []),
                                "tpdk_maximal.drc": _lyrdb([], [])})
    violations, meta = PV._klayout_drc_runner(str(deck), "/x.gds", "blk", "c",
                                              tmp_path / "drc.lyrdb")
    assert violations is None
    assert "A6_EXTRA_RUNSET_GRADED_NOTHING" in meta["reason"]


def test_one_crash_is_retried_and_recorded_two_are_no_evidence(
        tmp_path, monkeypatch):
    deck = _staged_deck(tmp_path)
    bodies = {"main.drc": _lyrdb(["A.1"], []),
              "tpdk_maximal.drc": _lyrdb(["M2.d"], [])}
    _fake_klayout(monkeypatch, bodies, rcs=[0, 139, 0])
    violations, _ = PV._klayout_drc_runner(str(deck), "/x.gds", "blk", "c",
                                           tmp_path / "drc.lyrdb")
    assert violations == 0
    _fake_klayout(monkeypatch, bodies, rcs=[0, 139, 139])
    violations, meta = PV._klayout_drc_runner(str(deck), "/x.gds", "blk", "c",
                                              tmp_path / "drc.lyrdb")
    assert violations is None and "rc=139" in meta["reason"]


def _block(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    b = project / "phase3/analog/blk"
    b.mkdir(parents=True)
    (b / "blk.gds").write_bytes(b"\x00")
    (b / "blk.sp").write_text(".subckt blk a\n.ends\n")
    return project


def test_native_a6_fails_on_the_extra_decks_m2d_that_device_cell_used_to_excuse(
        tmp_path, monkeypatch):
    project = _block(tmp_path)
    deck = _staged_deck(tmp_path)
    _fake_klayout(monkeypatch, {
        "main.drc": _lyrdb(["A.1"], []),
        "tpdk_maximal.drc": _lyrdb(["M2.d", "MIM.e"], ["M2.d"] * 20),
        "tpdk_maximal.drc:flat": _lyrdb(["M2.d", "MIM.e"], ["M2.d"] * 20)})
    att = {"result": "DEVICE_ONLY",
           "by_class_and_rule": {"DEVICE_CELL": {_M2_D: 60}}}
    st = PV.run_block_pv(project, "blk", {"drc_deck": str(deck)}, "c",
                         second_engine_runner=lambda p, b, c: (att, ""))
    assert st["drc"]["verdict"] == "FAIL"
    assert st["drc"]["violations"] == 20
    text = (project / "phase3/analog/blk/drc.report").read_text()
    assert "result: FAIL" in text
    assert "extra_runset: tpdk_maximal.drc" in text


def test_native_a6_blocks_an_uncontrolled_disagreement(tmp_path, monkeypatch):
    """The deck grades MIM.e and fires 0; Magic fires it 4. Deferred ONLY
    behind a capability control. The control is played SILENT here, so the
    deck's 0 proves nothing and the 4 count."""
    project = _block(tmp_path)
    d = tmp_path / "solo"
    d.mkdir()
    deck = d / "main.drc"
    deck.write_text("#")
    _fake_klayout(monkeypatch, {"main.drc": _lyrdb(["A.1", "MIM.e"], [])})
    seen = []

    def cap(project, block, container, rules, decks):
        seen.append((tuple(rules), tuple(Path(x).name for x in decks)))
        return {r: {"rule": r, "result": "SILENT", "testcases": ["mim.gds"],
                    "fired": {"mim.gds": 0}} for r in rules}
    monkeypatch.setattr(PV, "_native_capability", cap, raising=False)
    monkeypatch.setattr(PV, "_native_roundtrip",
                        lambda *a: {"result": "NOT_MEASURED"}, raising=False)
    att = {"result": "LAYOUT_OWNS", "by_class_and_rule": {"LAYOUT": {_MIM_E: 4}}}
    st = PV.run_block_pv(project, "blk", {"drc_deck": str(deck)}, "c",
                         second_engine_runner=lambda p, b, c: (att, ""))
    assert st["drc"]["verdict"] == "FAIL"
    assert st["drc"]["violations"] == 4
    assert seen == [(("MIM.e",), ("main.drc",))]
    text = (project / "phase3/analog/blk/drc.report").read_text()
    assert "second_engine_uncontrolled_disagreements: MIM.e" in text


def test_native_a6_defers_a_controlled_disagreement_and_names_the_artefact(
        tmp_path, monkeypatch):
    project = _block(tmp_path)
    d = tmp_path / "solo"
    d.mkdir()
    deck = d / "main.drc"
    deck.write_text("#")
    _fake_klayout(monkeypatch, {"main.drc": _lyrdb(["A.1", "MIM.e"], [])})
    monkeypatch.setattr(PV, "_native_capability", lambda p, b, c, rules, d: {
        r: {"rule": r, "result": "PASS", "testcases": ["mim.gds"],
            "fired": {"mim.gds": 1}} for r in rules}, raising=False)
    monkeypatch.setattr(PV, "_native_roundtrip", lambda *a: {
        "result": "MEASURED", "rules": {"MIM.e": {
            "block_rects": 4, "reproduced_rects": 4, "reproduced": True,
            "cells": {"cap": 4}, "klayout_on_device_gds": {"cap": 0}}}},
        raising=False)
    att = {"result": "LAYOUT_OWNS", "by_class_and_rule": {"LAYOUT": {_MIM_E: 4}}}
    st = PV.run_block_pv(project, "blk", {"drc_deck": str(deck)}, "c",
                         second_engine_runner=lambda p, b, c: (att, ""))
    assert st["drc"]["verdict"] == "PASS"
    se = st["drc"]["second_engine"]
    assert list(se["engine_disagreements"]["engine_artefact"]) == ["MIM.e"]
    text = (project / "phase3/analog/blk/drc.report").read_text()
    assert "second_engine_engine_artefact: MIM.e" in text


# ── LibreLane arm, end to end, against a stub docker ──────────────────────
STUB = r'''#!/usr/bin/env python3
import base64, json, os, re, sys
a = sys.argv[1:]
j = " ".join(a)
if a[0] == "run":
    if "--help" in j:
        sys.exit(0)
    if "--entrypoint" in a and a[a.index("--entrypoint") + 1] == "sh" \
            and "A6EXTRA" in a[-1]:
        extra = os.environ.get("STUB_EXTRA_PATH")
        if extra:
            print("A6EXTRA " + extra)
        sys.exit(0)
    if "--entrypoint" in a and a[a.index("--entrypoint") + 1] == "python3" \
            and "A6UNITLABELS" in j:
        print("A6UNITLABELS " + json.dumps({"mim.gds": {
            "top": ["mim"], "labels": ["Mim.e", "FAIL"]}}))
        sys.exit(0)
    if "--entrypoint" in a and a[a.index("--entrypoint") + 1] == "cat":
        sys.stdout.write("GDSBYTES")
        sys.exit(0)
    if "--entrypoint" in a and a[a.index("--entrypoint") + 1] == "python3" \
            and "base64.b64encode" in j:
        print("VIBEIC_UNIT_TESTCASE_B64=" + base64.b64encode(b"GDSBYTES").decode())
        sys.exit(0)
    if "-c" in a and "Config.load" in a[-1]:
        src = re.search(r"p='([^']+)'", a[-1]).group(1)
        out = re.search(r"out='([^']+)'", a[-1]).group(1)
        cfg = json.load(open(src))
        if cfg["meta"]["step"] == "KLayout.DRC":
            cfg["KLAYOUT_DRC_RUNSET"] = os.environ["STUB_MAIN_PATH"]
            cfg["KLAYOUT_DRC_OPTIONS"] = {"no_recommended": True}
        open(out, "w").write(json.dumps(cfg))
        sys.exit(0)
    if "librelane.steps" in a:
        step = a[a.index("--id") + 1]
        folder = a[a.index("-o") + 1]
        cfg = json.load(open(a[a.index("-c") + 1]))
        state = json.load(open(a[a.index("-i") + 1]))
        os.makedirs(os.path.join(folder, "reports"), exist_ok=True)
        if step == "KLayout.DRC":
            name, key = "drc.klayout.lyrdb", "klayout__drc_error__count"
            if cfg["DESIGN_NAME"] == "mim":
                body = os.environ["STUB_UNIT_" + os.path.basename(
                    cfg["KLAYOUT_DRC_RUNSET"]).split(".")[0]]
            elif cfg["KLAYOUT_DRC_RUNSET"] == os.environ["STUB_MAIN_PATH"]:
                body = os.environ["STUB_KLAYOUT"]
            else:
                body = os.environ["STUB_EXTRA"]
        else:
            name, key = "drc.magic.lyrdb", "magic__drc_error__count"
            body = os.environ["STUB_MAGIC"]
        open(os.path.join(folder, "reports", name), "w").write(body)
        state["metrics"] = {key: body.count("<item>")}
        open(os.path.join(folder, "state_out.json"), "w").write(json.dumps(state))
        sys.exit(0)
sys.exit(1)
'''


def _ll_project(tmp_path):
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
def ll_stub(tmp_path, monkeypatch):
    d = tmp_path / "bin"
    d.mkdir()
    (d / "docker").write_text(STUB)
    (d / "docker").chmod(0o755)
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}{os.environ['PATH']}")
    main = "/pdk/tpdk/klayout/drc/main.drc"
    monkeypatch.setenv("STUB_MAIN_PATH", main)
    monkeypatch.setenv("STUB_EXTRA_PATH",
                       "/pdk/tpdk/klayout/drc/rule_decks/tpdk_maximal.drc")
    monkeypatch.setenv("STUB_KLAYOUT", _lyrdb(["A.1"], []))
    monkeypatch.setenv("STUB_EXTRA", _lyrdb(["M2.d", "MIM.e"], ["M2.d"] * 2))
    monkeypatch.setenv("STUB_MAGIC", _lyrdb(["M2.d", "MIM.e"],
                                            ["M2.d"] * 6 + ["MIM.e"] * 4))
    monkeypatch.setenv("STUB_UNIT_main", _lyrdb(["A.1"], []))
    monkeypatch.setenv("STUB_UNIT_tpdk_maximal", _lyrdb(["MIM.e"], ["MIM.e"]))
    return tmp_path


_ATT = {"by_class_and_rule": {"DEVICE_CELL": {_M2_D: 6}}}


def _rec(project):
    return json.loads((project / "phase3/analog/blk/a6_librelane_drc.json")
                      .read_text())


def test_the_ll_arm_runs_the_extra_deck_and_m2d_blocks_while_mim_e_defers(
        ll_stub):
    project = _ll_project(ll_stub)
    assert LL.run(project, "blk", IMAGE, _ATT) == 1
    rec = _rec(project)
    auth = rec.get("authority") or {}
    assert auth.get("blocking") == {"M2.d": 2}
    assert auth.get("deferred_by_capability_control") == {"MIM.e": 4}
    assert (project / "phase3/librelane/analog/blk/a6_klayout_drc_extra"
            ).is_dir()
    # the capability control ran the SAME step on the PDK's own testcase
    assert list((project / "phase3/librelane/analog/_capability").glob(
        "mim_gds/*/01-*/vibeic_receipt.json"))
    # no container named -> the round trip is NOT_MEASURED, no artefact named
    assert auth["engine_artefact"] == {}


def test_the_ll_arm_blocks_mim_e_when_the_deck_cannot_fire_it_on_the_testcase(
        ll_stub, monkeypatch):
    monkeypatch.setenv("STUB_UNIT_tpdk_maximal", _lyrdb(["MIM.e"], []))
    project = _ll_project(ll_stub)
    assert LL.run(project, "blk", IMAGE, _ATT) == 1
    auth = _rec(project).get("authority") or {}
    assert auth.get("blocking") == {"M2.d": 2, "magic:MIM.e": 4}
    assert auth["blocking_codes"] == {
        "magic:MIM.e": "A6_ENGINE_DISAGREEMENT_UNCONTROLLED"}


def test_the_ll_arm_names_an_engine_artefact_only_with_the_round_trip(
        ll_stub, monkeypatch):
    monkeypatch.setenv("STUB_EXTRA", _lyrdb(["M2.d", "MIM.e"], []))
    monkeypatch.setenv("STUB_MAGIC", _lyrdb(["MIM.e"], ["MIM.e"] * 4))
    project = _ll_project(ll_stub)
    rt = {"result": "MEASURED", "rules": {"MIM.e": {
        "block_rects": 4, "reproduced_rects": 4, "reproduced": True,
        "cells": {"cap": 4}, "klayout_on_device_gds": {"cap": 0}}}}
    got = []
    rc = LL.run(project, "blk", IMAGE, _ATT, "ctn",
                lambda p, b, c, rules, decks: got.append((c, rules, decks))
                or rt)
    assert rc == 0
    rec = _rec(project)
    assert list(rec["authority"]["engine_artefact"]) == ["MIM.e"]
    assert rec["result"] == "CLEAN"
    assert got == [("ctn", ["MIM.e"],
                    ["/pdk/tpdk/klayout/drc/main.drc",
                     "/pdk/tpdk/klayout/drc/rule_decks/tpdk_maximal.drc"])]


def test_the_ll_arm_refuses_an_extra_deck_that_graded_nothing(
        ll_stub, monkeypatch):
    monkeypatch.setenv("STUB_EXTRA", _lyrdb([], []))
    project = _ll_project(ll_stub)
    assert LL.run(project, "blk", IMAGE, _ATT) == 1
    rec = _rec(project)
    assert rec["result"] == "NOT_MEASURED"
    assert rec["rule"] == "A6_LL_SIGNOFF_GRADED_NOTHING"


def test_extra_runset_probe_deadline_is_an_environment_refusal(
        ll_stub, monkeypatch):
    import librelane_contract as lc
    project = _ll_project(ll_stub)

    def deadline(*_args):
        raise lc.Refusal("LL_TOOL_DEADLINE", "partial listing: one extra deck")

    monkeypatch.setattr(LL, "image_extra_runsets", deadline)
    assert LL.run(project, "blk", IMAGE, _ATT) == 69
    rec = _rec(project)
    assert rec["result"] == "NOT_MEASURED"
    assert rec["rule"] == "LL_TOOL_DEADLINE"
    assert "partial listing: one extra deck" in rec["detail"]
    assert set(rec["engines"]) == {"KLayout.DRC", "Magic.DRC"}


def test_capability_probe_deadline_writes_a_named_a6_record(
        ll_stub, monkeypatch):
    import librelane_contract as lc
    project = _ll_project(ll_stub)

    def deadline(*_args):
        raise lc.Refusal("LL_TOOL_DEADLINE", "partial unit-label probe")

    monkeypatch.setattr(LL, "_capability_controls", deadline)
    assert LL.run(project, "blk", IMAGE, _ATT) == 69
    rec = _rec(project)
    assert rec["result"] == "NOT_MEASURED"
    assert rec["rule"] == "LL_TOOL_DEADLINE"
    assert "partial unit-label probe" in rec["detail"]
    assert set(rec["engines"]) == {"KLayout.DRC", "Magic.DRC",
                                   "KLayout.DRC extra tpdk_maximal.drc"}


def test_the_attribution_program_names_the_engine_artefact_class():
    import analog_a6_drc_attribute as ATT
    assert "ENGINE_ARTEFACT" in ATT.CLASS_ACTION
    assert callable(getattr(ATT, "gds_roundtrip", None))


def test_the_round_trip_reproduces_only_when_every_block_rectangle_is_placed(
        tmp_path, monkeypatch):
    """Rectangles are compared, not counts: a bare cell's round-trip
    rectangle, moved by each instance's transform, must cover every block
    rectangle of the rule."""
    import analog_a6_drc_attribute as ATT
    project = tmp_path / "p"
    b = project / "phase3/analog/blk"
    b.mkdir(parents=True)
    (b / "blk.gds").write_bytes(b"\x00")
    (b / "cap.mag").write_text("magic\n")
    (b / "layout.mag").write_text(
        "magic\ntech t\n<< checkpaint >>\n"
        "use cap  c1\ntimestamp 1\ntransform 1 0 100 0 1 50\nbox 0 0 1 1\n"
        "<< end >>\n")
    blobs = {"a6gdsblock": "A6TOTAL 2\nV|" + _MIM_E + "|190 90 210 110\n"
                           "V|" + _MIM_E + "|500 500 510 510\n",
             "a6rt_cap_r": "A6TOTAL 1\nV|" + _MIM_E + "|-10 -10 10 10\n"}

    class FakeStage:
        path, host_tmp = "/s", tmp_path

        def put(self, src, name):
            return True, ""

        def put_text(self, text, name):
            return True, ""

        def sh(self, cmd, timeout=0):
            rpt = cmd.split("report=")[1].split()[0]
            (tmp_path / rpt).write_text(_lyrdb(["MIM.e"], []))
            return 0, "", ""

        def get(self, name, dst):
            return (tmp_path / name).is_file(), ""

    monkeypatch.setattr(ATT.Deck, "run",
                        lambda self, script, tag: blobs.get(tag, "A6TOTAL 0\n"))
    rt = ATT.gds_roundtrip(project, "blk", FakeStage(), "rc", ["MIM.e"],
                           ["/d/main.drc"])
    r = rt["rules"]["MIM.e"]
    assert (r["block_rects"], r["reproduced_rects"]) == (2, 1)
    assert r["reproduced"] is False
    assert r["klayout_on_device_gds"] == {"cap": 0}
    blobs["a6gdsblock"] = "A6TOTAL 1\nV|" + _MIM_E + "|190 90 210 110\n"
    rt = ATT.gds_roundtrip(project, "blk", FakeStage(), "rc", ["MIM.e"],
                           ["/d/main.drc"])
    assert rt["rules"]["MIM.e"]["reproduced"] is True
