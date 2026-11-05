from __future__ import annotations

import json
import shutil
from pathlib import Path
import sys

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

from synth_handoff_netlist_check import _project_path_resolver
from execution_provider_catalog import BACKEND_IDS, coverage_table

PRE_FIX_BASE = "59cd75606885b71ca7d11bbe34baf2541671be68"








def test_machine_readable_owned_coverage_has_exact_dispositions():
    table = coverage_table()
    assert table["row_count"] == 37
    assert table["backend_row_count"] == 23
    assert table["release_row_count"] == 14
    assert sum(row["disposition"] == "implemented" for row in table["rows"]) == 31
    assert sum(row["disposition"] == "unavailable" for row in table["rows"]) == 1
    assert sum(row["disposition"] == "external" for row in table["rows"]) == 5
    assert {row["step_id"] for row in table["rows"]} == set(BACKEND_IDS) | {
        "14", "16", "35", "36", "37.4", "37.5ip", "37.5ic", "38", "39",
        "40", "41", "42", "43", "44"}






















def test_backend_handoff_resolves_only_receipt_project_namespace(tmp_path):
    """A staged backend may rebase receipt project paths, never read ambient originals."""
    staged = tmp_path / "staged"
    folder = staged / "phase3/librelane/02-yosys-synthesis"
    folder.mkdir(parents=True)
    (staged / "phase3/stage1/rtl").mkdir(parents=True)
    source = staged / "phase3/librelane/02-yosys-synthesis/spm.nl.v"
    source.write_text("module spm; endmodule\n")
    original = Path("/original/project/phase3/librelane/02-yosys-synthesis/spm.nl.v")
    resolver = _project_path_resolver(
        staged, folder, {"nl": str(original)})
    assert resolver(original) == source.resolve()
    with pytest.raises(ValueError, match="absent"):
        resolver(Path("/original/project/phase3/librelane/02-yosys-synthesis/missing.v"))
    # A PDK path is external and stays external; it is subsequently checked
    # by the receipt's PDK mount validator rather than mapped to the project.
    assert resolver(Path("/pdk/gf180mcuD/config.tcl")) == Path("/pdk/gf180mcuD/config.tcl")












def test_cdc_native_citation_reader_accepts_carried_proof_and_rejects_changed_log(tmp_path):
    """The real CDC reader accepts the carried native proof set only as-is."""
    from programs.tests import test_t91_step3_cdc_netlist_front_end as cdc_fixture
    import _cdc_netlist as cdc_netlist
    import librelane_contract as ll

    source = cdc_fixture._project(
        tmp_path, "native_source", cdc_fixture.FIX / "multi_clock_sync.v",
        "librelane", cdc_fixture.FIX / "multi_clock_sync.json")
    isolated = tmp_path / "isolated_consumer"
    shutil.copytree(source / "phase2/stage1/rtl", isolated / "phase2/stage1/rtl")
    (isolated / "phase3").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source / "phase3/librelane_switch.json",
                    isolated / "phase3/librelane_switch.json")
    for rel in (
        "reports/phase2/cdc/netlist.json",
        "reports/phase2/cdc/netlist_front_end.json",
        "reports/phase2/cdc/netlist.yosys.log",
        "reports/phase2/cdc/netlist.raw.json",
        "reports/phase2/cdc/netlist.normalize.yosys.log",
    ):
        target = isolated / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / rel, target)

    netlist = cdc_netlist.load(isolated / "reports/phase2/cdc/netlist.json")
    receipt = cdc_netlist.require_binding(
        isolated, isolated / "reports/phase2/cdc/netlist.json", netlist)
    assert receipt["producer"]["step"] == "Yosys.JsonHeader"
    assert receipt["sha256"]["netlist.yosys.log"] == ll.digest(
        isolated / "reports/phase2/cdc/netlist.yosys.log")
    assert receipt["sha256"]["netlist.raw.json"] == ll.digest(
        isolated / "reports/phase2/cdc/netlist.raw.json")
    assert receipt["sha256"]["netlist.normalize.yosys.log"] == ll.digest(
        isolated / "reports/phase2/cdc/netlist.normalize.yosys.log")

    log = isolated / "reports/phase2/cdc/netlist.yosys.log"
    log.write_bytes(log.read_bytes() + b"\nchanged-log-control\n")
    with pytest.raises(cdc_netlist.Refusal, match="CDC_NETLIST_STALE"):
        cdc_netlist.require_binding(
            isolated, isolated / "reports/phase2/cdc/netlist.json", netlist)










_STEP12_POST_DFT = "phase2/stage2/synth/post_dft_netlist.v"
_STEP12_NO_DFT = {
    "dft_present": False, "scan_chains": [], "bist_mbist": [], "jtag_tap": None,
}
























# Production API controls for BR2-001..006; fixtures never qualify native EDA.
from programs.tests import test_execution_modes as H
from programs.tests._hostpaths import require_repo
import execution_adapters_release as release



def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))























def test_br2_002_real_components_stay_distinct_and_claims_have_source_evidence(tmp_path):
    # This real checked-in tool is consumed through the repository resolver.
    assert require_repo() / 'vibe-ic-marketplace/plugins/vibe-ic/programs/tests/fixtures/execution_modes_tool.py' == H.TOOL
    ctx = H.context(tmp_path); controller = H.controller(H.adapter('a'), H.adapter('b'))
    plan = controller.plan(ctx, 'ultra-mode')
    assert plan['arms'] == ['a', 'b']
    assert all(v['scope'] == 'SOURCE_COMPONENT_CLOSURE' and v['native_independence'] == 'NOT_MEASURED'
               for v in plan['independence'].values())
    assert len({v['sha256'] for v in plan['independence'].values()}) == 2














def hardmacro_report(tmp_path, native):
    binding = {'step_id':'37.5ip','required_gates':['digital_hardmacro_check','release_docs_check']}
    # Supply the canonical-result premise of this checker-only fixture.  No
    # current gate invocations or worker issuance are supplied as authority.
    report = {'step_id':'37.5ip','binding':binding,'qualification':'PASS','canonical_status':'PASS',
        'reason':'SOFTWARE_FIXTURE_ONLY','producer_verdict':'PASS','design_verdict':'PASS',
        'outputs':{},'missing_outputs':[], 'gate_records':[{'gate':g,'verdict':'PASS','blocking':True} for g in binding['required_gates']],
        'native_receipts':native}
    dump(tmp_path / 'release-evidence.json', report)
    return release.validate(tmp_path, binding).verdict


def test_br2_005_native_checker_fail_has_precedence(tmp_path):
    assert hardmacro_report(tmp_path, [{'status':'FAIL','processes':[]}]) == 'FAIL'


@pytest.mark.parametrize('native', [[], [{}], [None], ['invalid'], [None, {'status':'FAIL'}], [{'status':'FAIL'}, None]])
def test_br2_005_absent_invalid_and_mixed_evidence(tmp_path, native):
    expected = 'FAIL' if any(isinstance(x,dict) and x.get('status') == 'FAIL' for x in native) else 'NOT_MEASURED'
    assert hardmacro_report(tmp_path, native) == expected


def test_br2_005_valid_checker_positive_is_only_software_fixture(tmp_path):
    processes = [{'binary':name,'rc':0,'version':'fixture','argv':[name],'output_sha256':'a'*64} for name in ('magic','sta')]
    assert hardmacro_report(tmp_path, [{'status':'PRODUCED','processes':processes}]) == 'PASS'
    report = json.loads((tmp_path / 'release-evidence.json').read_text())
    evidence = release.validate(tmp_path, report['binding'])
    assert evidence.detail == 'SOFTWARE_FIXTURE_ONLY'
    assert evidence.metrics['canonical_evidence'] == 0
    assert not evidence.provenance.get('composite_gate_execution')






@pytest.mark.parametrize('native', [[{'status':'FAIL'}], []])
def test_br2_005_fail_precedence_survives_missing_output(tmp_path, native):
    hardmacro_report(tmp_path, native)
    report_path = tmp_path / 'release-evidence.json'
    report = json.loads(report_path.read_text())
    report['outputs'] = {'missing.lib': 'a' * 64}
    dump(report_path, report)
    assert release.validate(tmp_path, report['binding']).verdict == ('FAIL' if native else 'NOT_MEASURED')






# R4 controls extend the reviewed test module without changing earlier cases.


@pytest.mark.parametrize('label', ['16', '39', None])
def test_r4_native_fail_survives_report_step_relabel(tmp_path, label):
    hardmacro_report(tmp_path, [{'status':'FAIL','processes':[]}])
    report = json.loads((tmp_path / 'release-evidence.json').read_text())
    binding = report['binding']
    before = release.validate(tmp_path, binding)
    report['step_id'] = label
    dump(tmp_path / 'release-evidence.json', report)
    after = release.validate(tmp_path, binding)
    assert (before.verdict, after.verdict) == ('FAIL', 'FAIL')
    assert after.detail == 'RELEASE_STEP_IDENTITY_MISMATCH'


@pytest.mark.parametrize('native', [None, {}, {'status':'PASS','processes':[]}])
def test_r4_relabel_cannot_drop_native_requirement(tmp_path, native):
    hardmacro_report(tmp_path, [] if native is None else [native])
    report = json.loads((tmp_path / 'release-evidence.json').read_text())
    binding = report['binding']
    report['step_id'] = '16'
    dump(tmp_path / 'release-evidence.json', report)
    evidence = release.validate(tmp_path, binding)
    assert evidence.verdict == 'NOT_MEASURED'
    assert evidence.detail == 'RELEASE_STEP_IDENTITY_MISMATCH'










# Current canonical backend receipt projection; software controls only.




    # No Controller, observed process, sealed issuance, adoption or native tool
    # exists in this fixture. Projection alone does not authorize any of them.
