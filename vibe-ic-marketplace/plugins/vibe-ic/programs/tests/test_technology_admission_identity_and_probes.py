"""Registered declarations and actual technology-probe command contracts."""
import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phase3_one_shot_runner as p3
import submission_template_fetch as stf

@pytest.mark.parametrize("declared", ["ihp-sg13g2", "sg13g2", "IHP SG13G2", "ihp_sg13g2"])
def test_registered_identity_and_public_family(declared):
    assert p3._declares_resolved_pdk("ihp-sg13g2", p3._pdk_tokens(declared))

@pytest.mark.parametrize("resolved,declared", [
    ("ihp-sg13g2", "ihp-sg13g2-other"), ("ihp-sg13g2", "sg13g2_maximal"),
    ("ihp-sg13g2", "notihp-sg13g2"), ("sky130A", "sg13g2"),
    ("gf180mcuD", "gf180mcuA"), ("sky130Z", "sky130"),
    ("sky130A", "sky130A.other"), ("custom_auto_detect", "custom_auto_detec")])
def test_unrelated_or_extended_identity_refused(resolved, declared):
    assert not p3._declares_resolved_pdk(resolved, p3._pdk_tokens(declared))

def test_existing_unqualified_revision_family():
    assert p3._declares_resolved_pdk("sky130A", p3._pdk_tokens("sky130"))

@pytest.mark.parametrize("entrypoint,skip", [(None, False), ([], False), (["/dockerstartup/scripts/ui_startup.sh"], True)])
def test_both_probes_obey_actual_image_contract(monkeypatch, entrypoint, skip):
    import _eda_image, _container_exec
    monkeypatch.setattr(_container_exec, "local_exec_mode", lambda *_: False)
    monkeypatch.setenv("VIBEIC_DOCKER_MEMORY", "4g")
    image="repo@sha256:"+"0"*64
    monkeypatch.setattr(_eda_image, "judged_image", lambda **_: _eda_image.JudgedImage(image, "sha256:"+"0"*64, "test", "override", ""))
    calls=[]
    def transport(argv, timeout=None):
        if argv[:3]==["docker","image","inspect"]:
            return 0,json.dumps([{"Config":{"Entrypoint":entrypoint}}]),""
        calls.append(argv)
        assert argv[argv.index("--memory")+1]==argv[argv.index("--memory-swap")+1]=="4g"
        assert argv[argv.index("--network")+1]=="none"
        assert argv[argv.index("--cpus")+1]=="2"
        start=argv.index(image)+1
        assert (argv[start]=="--skip")==skip
        if "bash" in argv: return 0,"FILE=/pdk/tech.lef\n25:DATABASE MICRONS 1000 ;\n",""
        assert any(a.endswith(":/vibeic_programs:ro") for a in argv)
        return 0,'VIBEIC_STREAM_DBU={"cell_gds":"/pdk/cell.gds","value":0.001}\n',""
    monkeypatch.setattr(stf,"_run",transport)
    fact=stf.technology_facts("ihp-sg13g2",image)["database_unit_um"]
    assert fact["unavailable"] is None and fact["value"]==0.001 and fact["database_microns"]==1000
    assert len(calls)==2

@pytest.mark.parametrize("metadata", [None, {}, {"Config":None}, {"Config":{"Entrypoint":["/unknown/wrapper"]}}])
def test_unknown_image_contract_never_launches(monkeypatch, metadata):
    calls=[]
    def transport(argv, timeout=None):
        calls.append(argv)
        return (1,"","inspect refused") if metadata is None else (0,json.dumps([metadata]),"")
    monkeypatch.setattr(stf,"_run",transport)
    rc,out,err=stf._technology_probe("repo@sha256:"+"0"*64,["bash","-lc","true"])
    assert rc==126 and not out and "inspection unavailable" in err
    assert len(calls)==1 and calls[0][:3]==["docker","image","inspect"]

@pytest.mark.parametrize("native", [(3,"","missing stream"),(0,"invalid stream","")])
def test_failed_stream_does_not_inherit_lef_unit(monkeypatch,native):
    import _eda_image, _container_exec
    monkeypatch.setattr(_container_exec,"local_exec_mode",lambda *_:False)
    image="repo@sha256:"+"0"*64
    monkeypatch.setattr(_eda_image,"judged_image",lambda **_:_eda_image.JudgedImage(image,"sha256:"+"0"*64,"test","override",""))
    def transport(argv,timeout=None):
        if argv[:3]==["docker","image","inspect"]:return 0,json.dumps([{"Config":{"Entrypoint":None}}]),""
        if "bash" in argv:return 0,"FILE=/pdk/tech.lef\n25:DATABASE MICRONS 1000 ;\n",""
        return native
    monkeypatch.setattr(stf,"_run",transport)
    f=stf.technology_facts("ihp-sg13g2",image)["database_unit_um"]
    assert f["value"] is None and f["lef_database_unit_um"]==0.001 and f["unavailable"]


def test_docker_omitted_optional_entrypoint_is_entrypointless(monkeypatch):
    calls=[]
    def transport(argv,timeout=None):
        calls.append(argv)
        if argv[:3]==["docker","image","inspect"]:return 0,'[{"Config":{}}]',""
        assert argv[argv.index("repo@sha256:"+"0"*64)+1]=="python3"
        return 0,"read", ""
    monkeypatch.setattr(stf,"_run",transport)
    assert stf._technology_probe("repo@sha256:"+"0"*64,["python3","-c","print(1)"])==(0,"read","")
    assert len(calls)==2
