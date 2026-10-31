"""A6 native per-block PV producer (v1.4.27) — consume staged sign-off decks.

The producer runs native DRC (svrfdrc) + LVS (klayout_pdk_lvs) on a block when
the v1.4.24 resolver resolves the staged decks, writes the block `drc.report` /
`comp.json`, and the A6 gate (analog_a6_block_pv_check) then verdicts on that
REAL evidence. These tests inject fake engine runners (no container) to prove:
  * invocation shape — the runners receive the RESOLVED deck path + block GDS;
  * producer→gate wiring — a clean run PASSes the A6 gate;
  * honest FAIL propagation — a violating DRC / mismatched LVS FAILs A6;
  * the native path is skipped when no decks are resolved / no GDS is present.

NDA hygiene: SYNTHETIC deck / block names only; the injected runners return
NUMBERS, never real foundry deck content.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import analog_a6_native_pv as PV               # noqa: E402
import analog_a6_block_pv_check as A6           # noqa: E402
import _container_exec as _ce                   # noqa: E402 — the guarded argv
import _eda_pin as _pin                         # noqa: E402 — the ONE pin


def test_raw_host_probe_runs_without_entering_a_container(monkeypatch):
    def no_container(*args):
        raise AssertionError('explicit host probe entered a container')

    monkeypatch.setattr(_ce, 'docker_exec_argv', no_container)
    assert PV._docker_exec_raw('host', "printf 'native-host-probe'", 5) == (
        0, 'native-host-probe', '')


def test_raw_named_container_probe_keeps_its_route_and_deadline(monkeypatch):
    command = ['guarded-container-probe']
    calls = []

    def guarded(container, *argv):
        calls.append((container, argv))
        return command

    def execute(argv, **kwargs):
        assert argv == command
        assert kwargs['timeout'] == 7
        return subprocess.CompletedProcess(argv, 3, 'native output', 'native error')

    monkeypatch.setattr(_ce, 'docker_exec_argv', guarded)
    monkeypatch.setattr(PV.subprocess, 'run', execute)
    assert PV._docker_exec_raw('selected-runtime', 'native-command', 7) == (
        3, 'native output', 'native error')
    assert calls == [('selected-runtime', ('bash', '-lc', 'native-command'))]


def test_raw_host_probe_retains_timeout_status(monkeypatch):
    def timeout(argv, **kwargs):
        assert argv == ['bash', '-lc', 'native-command']
        assert kwargs['timeout'] == 7
        raise subprocess.TimeoutExpired(argv, 7, output=b'partial output')

    monkeypatch.setattr(PV.subprocess, 'run', timeout)
    assert PV._docker_exec_raw('host', 'native-command', 7) == (
        124, 'partial output', 'PROBE TIMEOUT after 7s: ' +
        "Command '['bash', '-lc', 'native-command']' timed out after 7 seconds")


def _mk_project(tmp_path: Path, block: str = "u_ldo",
                with_gds: bool = True, with_netlist: bool = True) -> Path:
    ad = tmp_path / "phase3" / "analog"
    bdir = ad / block
    bdir.mkdir(parents=True)
    (ad / "analog_block_list.json").write_text(
        json.dumps({"blocks": [{"name": block, "type": "ldo"}]}))
    if with_gds:
        (bdir / f"{block}.gds").write_bytes(b"\x00GDSII-fake\x00" * 4)
    if with_netlist:
        (bdir / f"{block}.sp").write_text(
            f".subckt {block} vdd vss vin vout\nr1 vin vout 1k\n.ends\n")
    return tmp_path


def _res(drc="/pdk/calibre/foundry_DRC.rule",
         lvs="/pdk/calibre/foundry_LVS.rule"):
    return {"available": True, "source": "project_custom_pdk",
            "family": "foundry", "target": "MyFoundry X180",
            "drc_deck": drc, "lvs_deck": lvs}


def _a6_verdict(project: Path, block: str) -> str:
    out = project / "a6.json"
    A6.main([str(project), "--block", block, "--json", str(out)])
    return json.loads(out.read_text())["verdict"]


# ── invocation shape ────────────────────────────────────────────────────────

def test_runner_receives_resolved_deck_and_gds():
    """The runners receive the resolved deck, the block GDS — and THE CONTAINER
    THE PRODUCER ITSELF SELECTED.

    THE NAME IS DERIVED, NOT WRITTEN DOWN — vibe-ic#2130. This test named the
    container by the literal `vibeic-eda`, which was the shared default until
    `_eda_pin.default_container_name` began deriving it from the required digest
    (`vibeic-eda-<digest12>`) precisely so two different pins cannot be one
    container. A literal is therefore a STALE MODEL of the producer's own
    choice, and on a fleet host the name it froze resolves to whatever container
    somebody left behind: measured 2026-09-07 on 8hd-3, `vibeic-eda` was an
    exited container running sha256:06537f7e… against a pin of sha256:1463dac5…,
    so the guarded `docker exec` argv builder refused and this test was red for
    a reason that had nothing to do with the deck or the GDS.

    So the producer's OWN selection is driven — no container is passed at all —
    and what the runners received is compared against the same derivation the
    producer uses. A pin move re-derives both sides together; a producer that
    hands its runners some other container is what goes red.

    A MEASURED MISMATCH IS REFUSED BY NAME. If the derived container does exist
    on this host and runs bytes other than the pinned ones, that is an operator
    fact and it is reported as one, rather than arriving as an assertion about a
    deck path.
    """
    seen = {}

    def drc_runner(deck, gds, blk, ctn):
        seen["drc"] = (deck, gds, blk, ctn)
        return 0, {"method": "svrf_native", "rules_pass": 10, "rules_skip": 1}

    def lvs_runner(gds, nl, blk, ctn):
        seen["lvs"] = (gds, nl, blk, ctn)
        return "MATCH", {"method": "klayout_pdk_lvs"}

    selected = _pin.default_container_name()

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = _mk_project(Path(td))
        try:
            st = PV.run_block_pv(p, "u_ldo", _res(),
                                 drc_runner=drc_runner, lvs_runner=lvs_runner)
        except _ce.ContainerImageMismatch as exc:
            pytest.fail(
                f"{_pin.CONTAINER_IMAGE_MISMATCH}: the container this producer "
                f"selected, {selected}, exists on this host and runs bytes "
                f"other than the pinned ones, so nothing was measured about "
                f"the deck or the GDS. This is a fact about the host, not "
                f"about the producer — remove or re-create that container. "
                f"The refusal, verbatim: {exc}")
    assert st["ran"] is True
    # NOT VACUOUS: the DRC and LVS paths both have to have reached a runner.
    assert set(seen) == {"drc", "lvs"}, (
        f"the producer reached no runner, so nothing below is a measurement "
        f"of the invocation shape; it reached: {sorted(seen)}")
    # DRC runner saw the RESOLVED staged deck path + the block GDS
    assert seen["drc"][0] == "/pdk/calibre/foundry_DRC.rule"
    assert seen["drc"][1].endswith("u_ldo.gds")
    assert seen["drc"][2] == "u_ldo"
    # …and the container the PRODUCER chose, derived from the pin the same way
    # the producer derives it. Never a literal: see the docstring.
    assert seen["drc"][3] == selected
    assert seen["lvs"][3] == selected
    # LVS runner saw the block GDS + the block source netlist
    assert seen["lvs"][0].endswith("u_ldo.gds")
    assert seen["lvs"][1].endswith("u_ldo.sp")


# ── producer → gate wiring (clean PASS) ─────────────────────────────────────

def test_clean_run_writes_evidence_and_passes_a6(tmp_path):
    p = _mk_project(tmp_path)
    st = PV.run_block_pv(
        p, "u_ldo", _res(), "c",
        drc_runner=lambda *a: (0, {"rules_pass": 42, "rules_skip": 3}),
        lvs_runner=lambda *a: ("MATCH", {"layout_devices": {"nmos": 4}}))
    assert st["ran"] and st["drc"]["verdict"] == "PASS"
    assert st["lvs"]["verdict"] == "match"
    bdir = p / "phase3" / "analog" / "u_ldo"
    assert (bdir / "drc.report").is_file()
    assert (bdir / "comp.json").is_file()
    # the A6 gate now verdicts on the REAL evidence
    assert _a6_verdict(p, "u_ldo") == "PASS"


# ── honest FAIL propagation ─────────────────────────────────────────────────

def test_violating_drc_fails_a6(tmp_path):
    p = _mk_project(tmp_path)
    st = PV.run_block_pv(
        p, "u_ldo", _res(), "c",
        drc_runner=lambda *a: (3, {"rules_pass": 40, "rules_skip": 0}),
        lvs_runner=lambda *a: ("MATCH", {}))
    assert st["drc"]["verdict"] == "FAIL" and st["drc"]["violations"] == 3
    # the written drc.report carries the honest count → A6 FAILs
    rpt = (p / "phase3" / "analog" / "u_ldo" / "drc.report").read_text()
    assert "violations: 3" in rpt
    assert _a6_verdict(p, "u_ldo") == "FAIL"


def test_lvs_mismatch_fails_a6(tmp_path):
    p = _mk_project(tmp_path)
    PV.run_block_pv(
        p, "u_ldo", _res(), "c",
        drc_runner=lambda *a: (0, {"rules_pass": 40}),
        lvs_runner=lambda *a: ("MISMATCH", {}))
    comp = json.loads(
        (p / "phase3" / "analog" / "u_ldo" / "comp.json").read_text())
    assert comp["result"] == "mismatch"
    assert _a6_verdict(p, "u_ldo") == "FAIL"


# ── native path correctly SKIPPED (existing waiver/stub path stands) ────────

def test_no_decks_resolved_does_not_run(tmp_path):
    p = _mk_project(tmp_path)
    res = {"available": True, "source": "container_installed",
           "drc_deck": None, "lvs_deck": None}
    st = PV.run_block_pv(p, "u_ldo", res, "c",
                         drc_runner=lambda *a: (0, {}),
                         lvs_runner=lambda *a: ("MATCH", {}))
    assert st["ran"] is False
    assert not (p / "phase3" / "analog" / "u_ldo" / "drc.report").exists()
    assert not (p / "phase3" / "analog" / "u_ldo" / "comp.json").exists()


def test_no_gds_skips_execution(tmp_path):
    p = _mk_project(tmp_path, with_gds=False)
    st = PV.run_block_pv(p, "u_ldo", _res(), "c",
                         drc_runner=lambda *a: (0, {}),
                         lvs_runner=lambda *a: ("MATCH", {}))
    assert st["ran"] is False
    assert "no block GDS" in st["reason"]


def test_engine_unavailable_leaves_no_evidence(tmp_path):
    """An absent engine publishes refusal, never a clean comparison."""
    p = _mk_project(tmp_path)
    st = PV.run_block_pv(
        p, "u_ldo", _res(), "c",
        drc_runner=lambda *a: (None, {"reason": "svrfdrc not on PATH"}),
        lvs_runner=lambda *a: (None, {"reason": "klayout not on PATH"}))
    assert st["ran"] is False
    bdir = p / "phase3" / "analog" / "u_ldo"
    assert not (bdir / "drc.report").exists()
    doc = json.loads((bdir / "comp.json").read_text())
    assert doc["result"] == "refused"
    assert doc["executed"] is False
    assert _a6_verdict(p, "u_ldo") == "FAIL"
    assert _a6_verdict(p, "u_ldo") == "FAIL"     # no evidence → honest FAIL


# ── report hygiene (NUMBERS ONLY) ───────────────────────────────────────────

def test_drc_report_is_numbers_only(tmp_path):
    p = _mk_project(tmp_path)
    PV.run_block_pv(
        p, "u_ldo", _res(), "c",
        drc_runner=lambda *a: (2, {"rules_pass": 9, "rules_skip": 1}),
        lvs_runner=lambda *a: ("MATCH", {}))
    rpt = (p / "phase3" / "analog" / "u_ldo" / "drc.report").read_text()
    # counts present; NO staged deck path / rule names leaked into the report
    assert "violations: 2" in rpt and "rules_pass: 9" in rpt
    assert "/pdk/" not in rpt
    assert "foundry_DRC.rule" not in rpt


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))


# ── THE RULES THE SIGN-OFF DECK DOES NOT GRADE ──────────────────────────
#
# MEASURED (ihp-sg13g2, image 0.3.46, u_hawaii_adc `delta_sigma` as A5 drew
# it before v1.17.88). The staged KLayout runset grades 560 rules and reports
# 0 violations — and of the PDK's MIM.a..MIM.i family its graded set contains
# only `MIM.c` and `MIM.d`, because the shipped deck comments out its own
# `%include` of the MiM rule file. While it said "0 of 560" that block
# carried eight `Via4 cannot contact MiM cap bottom plate (MIM.i)`, every one
# of them this flow's own paint on the capacitor's plate, and magic — which
# does grade MIM.i — was the only engine in the image that could see them.
#
# Both arms below run the REAL `run_block_pv` bookkeeping over a faked
# attribution, so what is under test is the ADJUDICATION RULE and not magic.

_LYRDB = ("<report><categories>"
          "<category><name>MIM.c</name></category>"
          "<category><name>MIM.d</name></category>"
          "<category><name>M2.b</name></category>"
          "</categories></report>")

_MIM_I = "Via4 cannot contact MiM cap bottom plate (MIM.i)"
_M2_D = "Metal2 minimum area < 0.144um^2 (M2.d)"
_M2_B = "Metal2 spacing < 0.21um (M2.b)"


def _attr(layout_rules):
    return {"result": "LAYOUT_OWNS" if layout_rules else "DEVICE_ONLY",
            "by_class_and_rule": {"LAYOUT": dict(layout_rules)}}


def test_second_engine_adjudicates_a_rule_the_signoff_deck_never_grades():
    got = PV.unadjudicated_rules(_attr({_MIM_I: 8}),
                                 PV.graded_rule_ids(_LYRDB))
    assert got == {"MIM.i": 8}


def test_second_engine_defers_where_the_signoff_deck_does_grade():
    """THE CONTROL that keeps the sign-off engine the authority. Both engines
    grade M2.b; the deck says 0 and that stands. Two engines counting the
    same rule differently is a separate question and not this one."""
    assert PV.unadjudicated_rules(_attr({_M2_B: 99}),
                                 PV.graded_rule_ids(_LYRDB)) == {}


def test_second_engine_never_verdicts_the_pdks_own_cell():
    """THE OTHER CONTROL, and the one that stops this failing every block on
    this PDK. `M2.d` is ungraded by the deck too, and `ldo` carries 60
    rectangles of it — every one inside the PDK's own gencells, which is why
    the attribution puts them in a class this reader does not look at."""
    attribution = {"result": "DEVICE_ONLY",
                   "by_class_and_rule": {"DEVICE_CELL": {_M2_D: 60},
                                         "LAYOUT": {}}}
    assert PV.unadjudicated_rules(attribution, PV.graded_rule_ids(_LYRDB)) == {}


def test_a_rule_id_that_cannot_be_read_is_named_not_defaulted():
    attribution = _attr({"a message with no rule id": 3})
    assert PV.unadjudicated_rules(attribution, PV.graded_rule_ids(_LYRDB)) == {}
    assert PV.unreadable_rule_messages(attribution) == [
        "a message with no rule id"]


def test_graded_set_of_an_absent_report_claims_nothing():
    """"Could not read it" is not "read it and it was empty": an unreadable
    report grades nothing, so nothing is deferred to it."""
    assert PV.graded_rule_ids("") == set()
    assert PV.unadjudicated_rules(_attr({_M2_B: 4}), PV.graded_rule_ids("")) \
        == {"M2.b": 4}


def test_rule_id_is_the_pdks_own_token_in_either_engines_message():
    assert PV.rule_id(_MIM_I) == "MIM.i"
    assert PV.rule_id("Metal1 overlap of Via1 < 0.045um (V1.c1)") == "V1.c1"
    assert PV.rule_id("no id here") is None


def test_every_rule_the_second_engine_saw_has_a_stated_disposition():
    """MEMBERSHIP, not a total. A reader must be able to see which rules
    counted, which were left to the sign-off engine, and which were surfaced
    without a verdict — otherwise a `violations: 0` is unreadable."""
    attribution = {"result": "LAYOUT_OWNS",
                   "by_class_and_rule": {"LAYOUT": {_MIM_I: 8, _M2_B: 2},
                                         "DEVICE_CELL": {_M2_D: 60}}}
    disp = PV.rules_by_disposition(attribution, PV.graded_rule_ids(_LYRDB))
    assert disp == {"adjudicated": {"MIM.i": 8},
                    "deferred": {"M2.b": 2},
                    "reported": {"M2.d": 60}}


def test_the_pdks_own_cell_is_surfaced_rather_than_dropped():
    """It used to appear in no A6 artefact at all: 60 rectangles on one block
    and 816 on the other, of a rule the sign-off deck does not grade either.
    Not this flow's to fix, and not this flow's to hide."""
    attribution = {"result": "DEVICE_ONLY",
                   "by_class_and_rule": {"DEVICE_CELL": {_M2_D: 816},
                                         "LAYOUT": {}}}
    disp = PV.rules_by_disposition(attribution, PV.graded_rule_ids(_LYRDB))
    assert disp["reported"] == {"M2.d": 816}
    assert disp["adjudicated"] == {} and disp["deferred"] == {}


def test_the_record_says_what_a_zero_from_this_engine_does_not_mean():
    """THE ARM THAT STOPS THIS PATH RECREATING THE DEFECT IT CLOSES. The
    sign-off deck's silence was read as cleanliness; this engine reports only
    rules that FIRED, so its own empty set must not be read the same way."""
    got = PV.second_engine_drc(
        Path("/nonexistent"), "blk", "", _LYRDB,
        runner=lambda p, b, c: (_attr({}), ""))
    assert got["violations"] == 0
    assert "does not list rules it graded and passed" in got["coverage"]
    assert "NOT evidence" in got["coverage"]


def _structural_project(tmp_path):
    import analog_a3_netlist_emit as producer
    import _analog_producer_common as identity
    project = _mk_project(tmp_path)
    bdir = project / 'phase3/analog/u_ldo'
    simulation = bdir / 'u_ldo.sp'
    simulation.write_text('.lib /unread/electrical.lib tt\n'
        '.subckt u_ldo vdd vss vin vout\n'
        'xR1 vin vout res_model w=1u l=2u\n.ends u_ldo\n')
    topology = {'block': 'u_ldo', 'ports': ['vdd', 'vss', 'vin', 'vout'],
                'devices': [{'name': 'R1', 'role': 'res', 'nets': ['vin', 'vout']}]}
    (bdir / 'topology.json').write_text(json.dumps(topology))
    (bdir / 'layout_provenance.json').write_text(json.dumps({
        'result': 'OK', 'netlist_content_sha256': identity.content_digest(simulation.read_text())}))
    producer.emit_lvs_view(project, 'u_ldo', expected_simulation_sha256=PV._sha256(simulation))
    return project, bdir, simulation


@pytest.mark.parametrize('deck', ['foundry_lvs.rule', 'foundry.lvs'])
def test_validated_cdl_reaches_native_runner_with_original_simulation_identity(tmp_path, monkeypatch, deck):
    project, bdir, simulation = _structural_project(tmp_path)
    original_sha = PV._sha256(simulation)
    seen = []
    def runner(*args):
        seen.append(args)
        return 'MATCH', {'source_devices': 1, 'layout_devices': 1}
    monkeypatch.setattr(PV, '_default_lvs_runner', runner)
    monkeypatch.setattr(PV, '_klayout_lvs_runset_runner', runner)
    result = PV.run_block_pv(project, 'u_ldo', _res(drc=None, lvs=deck), container='host')
    assert result['lvs']['verdict'] == 'match'
    assert len(seen) == 1
    assert str(bdir / 'u_ldo.lvs.cdl') in seen[0]
    assert str(simulation) not in seen[0]
    doc = json.loads((bdir / 'comp.json').read_text())
    assert doc['layout_netlist_identity']['state'] == 'MATCH'
    binding = doc['lvs_reference_binding']
    assert binding == result['lvs']['lvs_reference_binding']
    assert binding['kind'] == 'validated_a3_lvs_cdl'
    assert binding['simulation']['sha256'] == original_sha == PV._sha256(simulation)
    assert binding['reference']['sha256'] == PV._sha256(bdir / 'u_ldo.lvs.cdl')
    assert binding['provenance']['sha256'] == PV._sha256(bdir / 'lvs_provenance.json')


@pytest.mark.parametrize('missing', [('u_ldo.lvs.cdl',), ('lvs_provenance.json',),
                                     ('u_ldo.lvs.cdl', 'lvs_provenance.json')])
def test_missing_structural_artifact_refuses_and_replaces_old_match(tmp_path, missing):
    project, bdir, simulation = _structural_project(tmp_path)
    for name in missing:
        (bdir / name).unlink()
    (bdir / 'comp.json').write_text(json.dumps({'result': 'match'}))
    (bdir / 'lvs.report').write_text('Circuits match uniquely.\n')
    (bdir / 'lvs_match.flag').write_text('Circuits match uniquely.\n')
    def no_runner(*args):
        raise AssertionError('unqualified structural source reached LVS')
    result = PV.run_block_pv(project, 'u_ldo', _res(drc=None), lvs_runner=no_runner)
    assert result['lvs']['executed'] is False
    assert result['lvs']['verdict'] == 'refused'
    assert json.loads((bdir / 'comp.json').read_text())['result'] == 'refused'
    from analog_a6_block_pv_check import _lvs_match
    assert _lvs_match(bdir) == (None, 'comp.json')


@pytest.mark.parametrize('mutation', ['geometry', 'removed_device'])
def test_changed_cdl_cannot_requalify_by_rehashing_sidecar(tmp_path, mutation):
    import _pad_ring as parser
    project, bdir, simulation = _structural_project(tmp_path)
    view = bdir / 'u_ldo.lvs.cdl'
    original_source = simulation.read_bytes()
    text = view.read_text()
    text = text.replace('w=1u', 'w=9u') if mutation == 'geometry' else '\n'.join(
        line for line in text.splitlines() if not line.lower().startswith('rr1 '))
    view.write_text(text)
    sidecar = bdir / 'lvs_provenance.json'
    record = json.loads(sidecar.read_text())
    record['view_sha256'] = PV._sha256(view)
    record['subcircuits'] = {name: {'ports': ports, 'body': body}
        for name, (ports, body) in parser.parse_spice_subckts(text, preserve_parameters=True).items()}
    sidecar.write_text(json.dumps(record))
    (bdir / 'comp.json').write_text(json.dumps({'result': 'match'}))
    def no_runner(*args):
        raise AssertionError('altered CDL reached LVS')
    result = PV.run_block_pv(project, 'u_ldo', _res(drc=None), lvs_runner=no_runner)
    assert result['lvs']['verdict'] == 'refused'
    assert json.loads((bdir / 'comp.json').read_text())['result'] == 'refused'
    assert simulation.read_bytes() == original_source


def test_lvs_reference_changed_during_run_cannot_publish_match(tmp_path):
    project, bdir, simulation = _structural_project(tmp_path)
    def runner(*args):
        view = bdir / 'u_ldo.lvs.cdl'
        view.write_text(view.read_text().replace('w=1u', 'w=9u'))
        return 'MATCH', {'source_devices': 1}
    result = PV.run_block_pv(project, 'u_ldo', _res(drc=None), lvs_runner=runner)
    assert result['lvs']['verdict'] == 'refused'
    assert json.loads((bdir / 'comp.json').read_text())['result'] == 'refused'


def test_structural_lvs_engine_unavailable_replaces_old_match(tmp_path):
    project, bdir, simulation = _structural_project(tmp_path)
    (bdir / 'comp.json').write_text(json.dumps({'result': 'match'}))
    result = PV.run_block_pv(project, 'u_ldo', _res(drc=None),
        lvs_runner=lambda *args: (None, {'reason': 'engine unavailable'}))
    assert result['lvs']['verdict'] == 'refused'
    assert result['lvs']['rule'] == 'A6_LVS_ENGINE_NOT_MEASURED'
    assert json.loads((bdir / 'comp.json').read_text())['result'] == 'refused'


def test_malformed_structural_sidecar_refuses_before_runner(tmp_path):
    project, bdir, simulation = _structural_project(tmp_path)
    (bdir / 'lvs_provenance.json').write_text('[]')
    (bdir / 'comp.json').write_text(json.dumps({'result': 'match'}))
    def no_runner(*args):
        raise AssertionError('malformed qualification reached LVS')
    result = PV.run_block_pv(project, 'u_ldo', _res(drc=None), lvs_runner=no_runner)
    assert result['lvs']['rule'] == 'A6_STRUCTURAL_LVS_REFERENCE_REFUSED'
    assert json.loads((bdir / 'comp.json').read_text())['result'] == 'refused'


def test_simulation_layout_identity_remains_the_stale_source_guard(tmp_path):
    project, bdir, simulation = _structural_project(tmp_path)
    simulation.write_text(simulation.read_text().replace('w=1u', 'w=2u'))
    def no_runner(*args):
        raise AssertionError('stale A5 source reached native LVS')
    result = PV.run_block_pv(project, 'u_ldo', _res(drc=None), lvs_runner=no_runner)
    assert result['lvs']['rule'] == 'A6_LAYOUT_NOT_OF_THIS_NETLIST'
    assert json.loads((bdir / 'comp.json').read_text())['layout_netlist_identity']['state'] == 'STALE'
