"""Source-only current-interface deck and table-format consumer controls."""
import copy
import hashlib
import json

import pytest

import _mixed_signal_current as current
import _mixed_signal_native as consumer
from mixed_signal_m3_run import Refusal
from test_mixed_signal_receiver_noise_contract import _observations, _source_case


def _current_case(project):
    data, noise = _source_case(project)
    driver = project / "input/models/driver.sp"
    driver.write_text("* SOURCE_ONLY model\n.subckt neutral_buffer in out positive negative\nRdrive in out 2\n.ends\n")
    data["analog"].update(drive_transition_ns=0.25, adc_low_v=0.2, adc_high_v=0.8)
    data["canonical"] = {"macro_drive": "drive", "macro_sense": "sense",
        "noise": copy.deepcopy(noise),
        "crosstalk": {"measure_from_ns": 10,
                      "criteria": [{"metric": "peak_crosstalk_v", "units": "V_PEAK", "max": 0.2}]}}
    data["_current"] = {"block": "detector", "post": noise["model"], "ports": ["drive", "sense"], "rails": {},
        "driver_cell": "neutral_buffer", "driver_input": "in", "driver_output": "out",
        "driver_ports": ["in", "out", "positive", "negative"], "driver_sources": ["input/models/driver.sp"],
        "voltages": {"positive": 1, "negative": 0}, "temperature_c": 25,
        "nodes": ["driver:out", "macro:in", "macro:out"],
        "pin_roles": {"driver": "driver:out", "drive": "macro:in", "sense": "macro:out"},
        "rc": {"resistors": [("driver:out", "macro:in", 2)],
               "ground_caps": [("macro:in", 3e-12), ("macro:out", 0)],
               "coupling_caps": [("macro:in", "macro:out", 5e-12)]}}
    row = {"id": noise["id"], "criteria": [{"native_metric": "unknown_samples", "max": 0}],
           "native": {"clock_period_ns": 10, "tran_step_ns": 0.1, "measure_from_ns": 0, "cycles": 3}}
    drive = [{"time_ns": 0, "drive": "0"}, {"time_ns": 10, "drive": "1"},
             {"time_ns": 20, "drive": "0"}]
    return data, row, drive


def test_current_deck_preserves_extracted_rc_population_through_existing_dispatch(tmp_path):
    data, row, drive = _current_case(tmp_path)
    held = copy.deepcopy(data)
    wave = tmp_path / "run_token/case/wave.txt"
    deck = consumer.deck(tmp_path, data, row, drive, wave)

    assert deck == current.deck(tmp_path, data, row, drive, wave)
    assert 'Xlivedriver stimulus live_0 live_driver_positive live_driver_negative neutral_buffer' in deck
    assert 'Xlivereceiver live_1 live_2 detector' in deck
    assert 'Xreferencereceiver reference_1 reference_2 detector' in deck
    assert 'Rlive0 live_0 live_1 2' in deck and 'Rreference0 reference_0 reference_1 2' in deck
    assert sum(line.startswith('Clivec') for line in deck.splitlines()) == 1
    assert not any(line.startswith('Creferencec') for line in deck.splitlines())
    assert not any(line.startswith(('Cliveg1', 'Creferenceg1')) for line in deck.splitlines())
    assert 'wrdata coupling.txt v(live_2) v(reference_2)' in deck
    assert 'noise v(live_2) Vdrive dec 20 100 1000' in deck
    digest = hashlib.sha256((tmp_path / data["_current"]["post"]).read_bytes()).hexdigest()
    assert f'M3NOISE_RUN run_token noise_case {digest}' in deck
    assert data == held
    assert not wave.parent.exists()


@pytest.mark.parametrize("change,rule", [
    ("adc_bounds", "CURRENT_INTERFACE_NOT_SUPPORTED"),
    ("transition", "CURRENT_INTERFACE_NOT_SUPPORTED"),
    ("temperature", "CURRENT_INTERFACE_NOT_SUPPORTED"),
    ("bias", "CURRENT_INTERFACE_NOT_SUPPORTED"),
    ("unbounded_criterion", "CURRENT_INTERFACE_NOT_SUPPORTED"),
])
def test_current_deck_refuses_unsupported_declared_electrical_bounds(tmp_path, change, rule):
    data, row, drive = _current_case(tmp_path)
    if change == "adc_bounds":
        data["analog"]["adc_high_v"] = 2
    elif change == "transition":
        data["analog"]["drive_transition_ns"] = 5
    elif change == "temperature":
        data["_current"]["temperature_c"] = None
    elif change == "bias":
        data["canonical"]["noise"]["dc_drive_v"] = 2
    else:
        del data["canonical"]["crosstalk"]["criteria"][0]["max"]
    with pytest.raises(Refusal) as refused:
        consumer.deck(tmp_path, data, row, drive, tmp_path / "run/case/wave.txt")
    assert refused.value.rule == rule


@pytest.mark.parametrize("population", [[], ["other"], ["detector", "extra"]])
def test_actual_contract_reader_refuses_unresolved_full_population_and_ignores_caller_current(tmp_path, population):
    data, _, _ = _current_case(tmp_path)
    data.update(scope=current.SCOPE)
    data["canonical"].update(block="detector", instance="u_detector")
    path = tmp_path / consumer.CONTRACT
    path.write_text(json.dumps(data))
    declared = tmp_path / "phase1/analog/analog_block_list.json"
    declared.parent.mkdir(parents=True)
    declared.write_text(json.dumps({"blocks": population}))
    held = path.read_bytes()
    with pytest.raises(Refusal) as refused:
        consumer.contract(tmp_path, data["top"])
    assert refused.value.rule == "CURRENT_INTERFACE_NOT_SUPPORTED"
    assert "complete master block population" in str(refused.value)
    assert path.read_bytes() == held
    assert not (tmp_path / "reports").exists()


def _coupling_observations(work, data, row):
    spec = {**data["canonical"]["noise"], "id": row["id"], "top": data["top"], "scope": current.SCOPE}
    _observations(work, spec, log_name="ngspice.log")
    (work / "coupling.txt").write_text(
        "time v(live_2) v(reference_2)\n0 0.2 0\n1e-8 0.15 0.1\n2e-8 0.2 0.1\n3e-8 0.1 0.1\n")


def test_current_measurement_parser_observes_window_and_propagates_stricter_failure(tmp_path):
    data, row, _ = _current_case(tmp_path)
    work = tmp_path / "observations"
    _coupling_observations(work, data, row)
    got = current.measure(tmp_path, data, row, work, "source_run")
    assert got["scope"] == current.SCOPE
    assert got["crosstalk"]["sample_count"] == 3
    assert got["crosstalk"]["criteria"][0]["measured"] == pytest.approx(0.1)
    assert got["noise"]["metrics"]["integrated_output_noise_v_rms"]["measured"] == 3e-8
    assert got["verdict"] == "PASS"
    data["canonical"]["crosstalk"]["criteria"][0]["max"] = 0.09
    assert current.measure(tmp_path, data, row, work, "source_run")["verdict"] == "FAIL"


@pytest.mark.parametrize("change,rule", [
    ("missing_window_end", "FAILED_MEASUREMENT"),
    ("unordered_times", "FAILED_MEASUREMENT"),
    ("empty_window", "CURRENT_INTERFACE_NOT_SUPPORTED"),
])
def test_current_measurement_refuses_incomplete_or_unordered_window(tmp_path, change, rule):
    data, row, _ = _current_case(tmp_path)
    work = tmp_path / "observations"
    _coupling_observations(work, data, row)
    path = work / "coupling.txt"
    if change == "empty_window":
        data["canonical"]["crosstalk"]["measure_from_ns"] = 30
    elif change == "missing_window_end":
        path.write_text("\n".join(path.read_text().splitlines()[:-1]) + "\n")
    else:
        path.write_text(path.read_text().replace("2e-8 0.2", "1e-8 0.2"))
    with pytest.raises(Refusal) as refused:
        current.measure(tmp_path, data, row, work, "source_run")
    assert refused.value.rule == rule


from pathlib import Path

# Reuse the public one-interface ancestor fixture without selecting its native
# measurements. The STA receipt below binds SOURCE_CONTROL bytes, not a tool run.
from test_m3_native_supported import project, current_interface_project
from librelane_contract import validate_step_receipt as _validate_retained_step


def _namespace_case(project, monkeypatch, mode, record_property):
    import librelane_contract as lc
    sta = project / "phase3/librelane/sta"
    config_path = sta / "config.json"
    config = json.loads(config_path.read_text())
    pdk_root = project / "input/pdk"
    fields = {"verilog": "CELL_VERILOG_MODELS", "spice": "CELL_SPICE_MODELS"}
    if mode == "relative":
        for field in fields.values():
            config[field] = [str(Path(p).relative_to(project)) for p in config[field]]
    else:
        for kind, field in fields.items():
            if mode in ("guest_all", "guest_" + kind):
                config[field] = ["/pdk/" + str(Path(p).relative_to(pdk_root)) for p in config[field]]
    config_path.write_text(json.dumps(config) + "\n")
    log = sta / "tt/sta.log"
    if mode in ("guest_all", "guest_liberty"):
        log.write_text(log.read_text().replace(str(pdk_root), "/pdk"))
    root_record = {"cli_pdk_root": "/pdk", "mounts_under_it": [[str(pdk_root), "/pdk"]],
                   "stated_by": "run_chain(pdk_root=...)"}
    (sta / "pdk_root.json").write_text(json.dumps(root_record) + "\n")
    absolute_config = {key: [str(project / p) if not Path(p).is_absolute() else p for p in value]
                       for key, value in config.items() if key in fields.values()}
    fingerprint = {"step": "OpenROAD.STAPostPNR", "config": lc.digest(config_path),
                   "config_files": lc.config_file_hashes(absolute_config, [(pdk_root, "/pdk")])}
    # The library is selected by the actual STA log, not the config model list.
    library = pdk_root / "liberty/current_tt.lib"
    fingerprint["liberty_files"] = {"/pdk/liberty/current_tt.lib": lc.digest(library)}
    (sta / "input_fingerprint.json").write_text(json.dumps(fingerprint) + "\n")
    (sta / "invocation.log").write_text("SOURCE_CONTROL: no native STA execution credit\n")
    names = ("state_out.json", "config.json", "input_fingerprint.json", "pdk_root.json", "invocation.log", "tt/sta.log")
    (sta / "vibeic_receipt.json").write_text(json.dumps({"input": fingerprint,
        "sha256": {name: lc.digest(sta / name) for name in names}}) + "\n")
    ancestor_validator = lc.validate_step_receipt
    monkeypatch.setattr(lc, "validate_step_receipt", lambda folder, step:
                        _validate_retained_step(folder, step) if step == "OpenROAD.STAPostPNR"
                        else ancestor_validator(folder, step))
    return sta


def _namespace_inputs(project, record_property):
    paths = [p for p in project.rglob("*") if p.is_file()]
    record_property("public_input_sha256", hashlib.sha256(json.dumps(
        {str(p.relative_to(project)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)},
        sort_keys=True).encode()).hexdigest())
    record_property("scope", "SOURCE_CONTROL ancestors and normal M3 input consumer; no native execution")


@pytest.mark.parametrize("mode", ["host", "relative", "guest_verilog", "guest_spice", "guest_liberty", "guest_all"])
def test_normal_current_interface_consumes_retained_pdk_namespace(current_interface_project, monkeypatch, record_property, mode):
    project = current_interface_project
    _namespace_case(project, monkeypatch, mode, record_property)
    _namespace_inputs(project, record_property)
    held = (project / consumer.CONTRACT).read_bytes()
    data = consumer.contract(project, "bridge_top")
    paths = consumer.input_paths(project, "bridge_top")
    assert data["scope"] == current.SCOPE
    assert data["digital"]["extra_sources"] == ["input/pdk/neutral/BUF.v", "phase3/analog/hardmacro/receiver/receiver.v"]
    assert data["_current"]["driver_sources"] == ["input/pdk/neutral/cells.sp"]
    assert {"input/pdk/neutral/BUF.v", "input/pdk/neutral/cells.sp", "input/pdk/liberty/current_tt.lib"} <= paths
    assert all((project / path).is_file() and not Path(path).is_absolute() for path in paths)
    assert (project / consumer.CONTRACT).read_bytes() == held
    assert not (project / "reports/analog/mixed_signal/native_runs").exists()


@pytest.mark.parametrize("change", ["missing_receipt", "wrong_producer", "changed_mount", "changed_model"])
def test_normal_current_interface_refuses_unbound_pdk_namespace(current_interface_project, monkeypatch, record_property, change):
    import librelane_contract as lc
    project = current_interface_project
    sta = _namespace_case(project, monkeypatch, "guest_all", record_property)
    if change == "missing_receipt":
        (sta / "vibeic_receipt.json").unlink()
    elif change == "wrong_producer":
        receipt = json.loads((sta / "vibeic_receipt.json").read_text())
        receipt["input"]["step"] = "OpenROAD.STAPrePNR"
        (sta / "vibeic_receipt.json").write_text(json.dumps(receipt))
    elif change == "changed_mount":
        root = json.loads((sta / "pdk_root.json").read_text())
        root["mounts_under_it"][0][0] = str(project / "input/other_pdk")
        (sta / "pdk_root.json").write_text(json.dumps(root))
    else:
        with (project / "input/pdk/neutral/BUF.v").open("a") as stream:
            stream.write("// changed after the retained producer\n")
    _namespace_inputs(project, record_property)
    if change == "wrong_producer":
        with pytest.raises(lc.Refusal) as refused:
            consumer.input_paths(project, "bridge_top")
        assert refused.value.code == "LL_NOT_STAPOSTPNR"
        return
    with pytest.raises(Refusal) as refused:
        consumer.input_paths(project, "bridge_top")
    assert refused.value.rule == "CURRENT_INTERFACE_NOT_SUPPORTED"



@pytest.fixture
def explicit_multiblock_project(current_interface_project, monkeypatch):
    """SOURCE_CONTROL ancestry, two block types and three explicit instances."""
    import copy
    import hashlib
    import analog_a7_post_layout_emit as a7
    import librelane_contract as lc
    import mixed_signal_power_domain_run as power
    from test_m3_native_supported import read, write

    project = current_interface_project
    def put(name, text):
        path = project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    write(project / 'phase1/analog/analog_block_list.json', {'blocks': [
        {'name': 'receiver', 'multiplicity': 2}, {'name': 'receiver_b', 'count': 1}]})
    original = read(project / 'input/mixed_signal/native.json')
    second = project / 'phase3/analog/receiver_b'
    second.mkdir()
    for name in ('receiver.gds', 'receiver.sp', 'topology.json'):
        text = (project / 'phase3/analog/receiver' / name).read_text().replace('receiver', 'receiver_b').replace('receiver_b_r', 'receiver_r')
        (second / name.replace('receiver', 'receiver_b')).write_text(text)
    extracted = put('phase3/librelane/analog/receiver_b/a7_resim/rcx/receiver_b.spice',
        (project / 'phase3/librelane/analog/receiver/a7_resim/rcx/receiver.spice').read_text().replace('receiver', 'receiver_b').replace('receiver_b_r', 'receiver_r'))
    post = project / 'phase3/librelane/analog/receiver_b/a7_resim/receiver_b_post.sp'
    post.write_text(a7.post_layout_netlist('receiver_b', ['drive', 'sense'], extracted.read_text(),
        a7.model_binding_lines((second / 'receiver_b.sp').read_text(), second, post.parent))[0])
    for name in ('vibeic_receipt.json','state_out.json','input_fingerprint.json','pdk_root.json'):
        write(extracted.parent / name, {'scope':'SOURCE_CONTROL'})
    (extracted.parent / 'invocation.log').write_text('SOURCE_CONTROL only\n')
    record = copy.deepcopy(read(project / 'phase3/analog/receiver/a7_post_layout.json'))
    record.update(block='receiver_b', layout_path='phase3/analog/receiver_b/receiver_b.gds',
                  layout_sha256=sha(second / 'receiver_b.gds'))
    record['corners'][0].update(step_dir=str(extracted.parent.relative_to(project)),
        extracted_netlist=str(extracted.relative_to(project)), post_layout_netlist=str(post.relative_to(project)))
    write(second / 'a7_post_layout.json', record)
    write(second / 'pre_vs_post.json', {'_provenance': {'layout_path':record['layout_path'], 'layout_sha256':record['layout_sha256']}})
    macro = project / 'phase3/analog/hardmacro/receiver_b'
    macro.mkdir()
    for suffix in ('.v','.gds','.lib','.lef'):
        (macro / ('receiver_b'+suffix)).write_text((project / 'phase3/analog/hardmacro/receiver' / ('receiver'+suffix)).read_text().replace('receiver','receiver_b'))
    manifest = read(project / 'phase3/analog/hardmacro/receiver/a8_views_provenance.json')
    manifest.update(block='receiver_b', source_gds=record['layout_path'],source_gds_sha256=record['layout_sha256'])
    manifest['views']={suffix:{'path':str((macro/('receiver_b'+suffix)).relative_to(project)), 'sha256':sha(macro/('receiver_b'+suffix))} for suffix in ('.gds','.v','.lib','.lef')}
    write(macro / 'a8_views_provenance.json',manifest)
    monkeypatch.setattr(lc,'validate_step_receipt',lambda folder,_sid:{'sha256':{p.name:sha(p) for p in folder.glob('*.spice')}})
    lib=project/'input/pdk/liberty/current_tt.lib'
    text=lib.read_text();body=next(body for name,body in power.groups(text,'cell') if name=='receiver')
    lib.write_text(text.rsplit('}',1)[0]+'cell(receiver_b) {'+body+'}\n}\n')
    entries=[];cells={};ports={name:{'bits':[i], 'direction':'input'} for i,name in enumerate(('clk','reset_n'),1)}
    lines=['module bridge_top(input clk, reset_n, output '+', '.join(name+'_'+tag for tag in ('a0','a1','b0') for name in ('sense','enable','accepted'))+');']
    components=[]
    header=(project/'phase3/stage3/pnr/current.spef').read_text().split('*NAME_MAP')[0]
    aliases={name:'*'+str(i+1) for i,name in enumerate(name for tag in ('a0','a1','b0') for name in ('u_driver_'+tag,'u_'+tag))}
    spef=[header+'*NAME_MAP\n'+''.join(alias+' '+name+'\n' for name,alias in aliases.items())]
    for index,(tag,block) in enumerate((('a0','receiver'),('a1','receiver'),('b0','receiver_b'))):
        driver,instance='u_driver_'+tag,'u_'+tag
        drive,sense,response='enable_'+tag,'sense_'+tag,'accepted_'+tag
        bits=10+index*3
        ports.update({drive:{'bits':[bits],'direction':'output'},sense:{'bits':[bits+1],'direction':'output'},response:{'bits':[bits+2],'direction':'output'}})
        cells[driver]={'type':'BUF','connections':{'A':[2],'Y':[bits]}}
        cells[instance]={'type':block,'connections':{'drive':[bits],'sense':[bits+1]}}
        lines.extend([f'BUF {driver}(.A(reset_n),.Y({drive}));',f'{block} {instance}(.drive({drive}),.sense({sense}));',f'assign {response}={sense};'])
        components.extend([f'- {driver} BUF + PLACED ( {100+index*2000} 100 ) N ;',f'- {instance} {block} + FIXED ( {1000+index*2000} 1000 ) N ;'])
        spec=copy.deepcopy(original['canonical'])
        spec.update(id=tag,block=block,instance=instance,driver_instance=driver,
                    digital={'drive':drive,'sense':sense,'response':response})
        entries.append(spec)
        spef.extend([f'*D_NET {drive} 0.2\n*CONN\n*I {driver}:Y O\n*I {instance}:drive I\n*P {drive} O\n*CAP\n1 {driver}:Y 0.05\n2 {instance}:drive 0.05\n3 {instance}:drive {instance}:sense 0.1\n*RES\n1 {driver}:Y {instance}:drive 100\n2 {driver}:Y {drive} 1\n*END\n',
                     f'*D_NET {sense} 0.2\n*CONN\n*I {instance}:sense O\n*P {sense} O\n*CAP\n1 {instance}:sense 0.1\n2 {instance}:sense {instance}:drive 0.1\n*RES\n1 {instance}:sense {sense} 1\n*END\n'])
    lines.append('endmodule\n')
    put('phase3/stage3/pnr/bridge_top_pnr.v','\n'.join(lines))
    put('phase3/stage3/pnr/routed.def','DESIGN bridge_top ;\nUNITS DISTANCE MICRONS 1000 ;\nCOMPONENTS 6 ;\n'+'\n'.join(components)+'\nEND COMPONENTS\nEND DESIGN\n')
    put('phase3/stage3/pnr/bridge_top.gds','SOURCE_CONTROL digital layout; not GDS proof\n')
    spef.append('*D_NET reset_n 0.3\n*CONN\n*P reset_n I\n'+''.join(f'*I u_driver_{tag}:A I\n' for tag in ('a0','a1','b0'))+'*CAP\n'+''.join(f'{i+1} u_driver_{tag}:A 0.1\n' for i,tag in enumerate(('a0','a1','b0')))+'*RES\n'+''.join(f'{i+1} reset_n u_driver_{tag}:A 1\n' for i,tag in enumerate(('a0','a1','b0')))+'*END\n')
    spef_text=''.join(spef)
    for name,alias in aliases.items():
        spef_text=spef_text.replace(name+':',alias+':')
    put('phase3/stage3/pnr/current.spef',spef_text)
    write(project/'reports/analog/mixed_signal/power_domain_tool/netlist.json',{'modules':{'bridge_top':{'ports':ports,'cells':cells}}})
    original['canonical']={'interfaces':entries}
    original['digital']['extra_sources'].append('phase3/analog/hardmacro/receiver_b/receiver_b.v')
    original['si']['interfaces']=[{'pin':entry['instance']+'/'+pin,'criteria':[{'metric':'slew_rise_max','max':10}]} for entry in entries for pin in ('drive','sense')]
    write(project/'input/mixed_signal/native.json',original)
    plan=read(project/'phase1/generated_docs/L22_VERIFICATION_PLAN.json')
    row=plan['fields']['verification_plan']['cosim_scenarios'][0]
    plan['fields']['verification_plan']['cosim_scenarios']=[{**copy.deepcopy(row),'id':'mission_'+entry['id'],'interface':entry['id']} for entry in entries]
    write(project/'phase1/generated_docs/L22_VERIFICATION_PLAN.json',plan)
    write(project/'phase1/generated_docs/L5_ADI_SPEC.json',{'doc_id':'L5','fields':{'analog_digital_interfaces':[{'signal':entry['digital'][key]} for entry in entries for key in ('drive','sense')]}})
    return project


@pytest.mark.parametrize('case',['complete','missing_mapping','missing_model','missing_channel','bad_block','cross_coupling'])
def test_explicit_multiblock_current_producer(explicit_multiblock_project,monkeypatch,record_property,case):
    """Existing native loop/readback, SOURCE_CONTROL ancestors, no ADC credit."""
    import mixed_signal_m3_run as m3
    from test_m3_native_supported import read,write
    project=explicit_multiblock_project
    contract=project/'input/mixed_signal/native.json'
    data=read(contract)
    if case=='missing_mapping':
        data['canonical']['interfaces'].pop()
        write(contract,data)
    elif case=='missing_model':
        (project/'phase3/librelane/analog/receiver_b/a7_resim/receiver_b_post.sp').unlink()
    elif case=='missing_channel':
        data['canonical']['interfaces']=[entry for entry in data['canonical']['interfaces'] if entry['id']!='a1']
        write(contract,data)
        plan_path=project/'phase1/generated_docs/L22_VERIFICATION_PLAN.json'
        plan=read(plan_path)
        plan['fields']['verification_plan']['cosim_scenarios']=[row for row in plan['fields']['verification_plan']['cosim_scenarios'] if row['interface']!='a1']
        write(plan_path,plan)
    elif case=='bad_block':
        data['canonical']['interfaces'][2]['noise']['criteria'][0]['max']=0.0
        write(contract,data)
    elif case=='cross_coupling':
        path=project/'phase3/stage3/pnr/current.spef'
        path.write_text(path.read_text().replace('3 *2:drive *2:sense 0.1','3 *2:drive *2:sense 0.1\n4 *2:drive *6:sense 0.01'))
    calls=[]
    original_run=consumer.Engine.run
    def observed(self,command,log,stage,cwd=None):
        calls.append(command)
        return original_run(self,command,log,stage,cwd)
    monkeypatch.setattr(consumer.Engine,'run',observed)
    report=project/'current_multiblock.json'
    rc=m3.main([str(project),'--top','bridge_top','--container','host','--json',str(report)])
    result=read(report) if report.exists() else {}
    record_property('scope','SOURCE_CONTROL ancestry + actual neutral native measurements; no ADC/final-geometry acceptance')
    record_property('producer_result',result)
    record_property('actual_rc',rc)
    if case in ('missing_mapping','missing_model','missing_channel','cross_coupling'):
        assert rc!=0,result
        assert calls==[],calls
        return
    assert rc==({'complete':0,'bad_block':1}[case]),result
    record=read(project/m3.RECEIPT)
    assert record['scenario_ids']==['mission_a0','mission_a1','mission_b0']
    assert record['full_design_verified'] is False
    assert len([cmd for cmd in calls if 'ngspice' in cmd and '-b' in cmd])==3
    si=read(project/m3.SI)
    assert {(row['interface'],row['block'],row['instance']) for row in si['current_interfaces']}=={
        ('a0','receiver','u_a0'),('a1','receiver','u_a1'),('b0','receiver_b','u_b0')}
    assert m3.audit(project,'cosim')['verdict']==('PASS' if case=='complete' else 'FAIL')
    assert m3.audit(project,'si')['verdict']==('PASS' if case=='complete' else 'FAIL')
    if case=='bad_block':
        assert next(row for row in si['current_interfaces'] if row['interface']=='b0')['verdict']=='FAIL'

    if case=='complete':
        # Reuse this one native run for hostile readback controls, then restore
        # its exact bytes. The retained input census must still own every block.
        original_si=(project/m3.SI).read_bytes()
        original_receipt=(project/m3.RECEIPT).read_bytes()
        bad=read(project/m3.SI); bad['current_interfaces'].pop()
        write(project/m3.SI,bad)
        rebound=read(project/m3.RECEIPT); rebound['outputs'][m3.SI]=m3.digest(project/m3.SI)
        write(project/m3.RECEIPT,rebound)
        try:
            missing=m3.audit(project,'si')
            assert missing['passed'] is False,missing
            record_property('rehashed_missing_interface_readback',missing)
        finally:
            (project/m3.SI).write_bytes(original_si)
            (project/m3.RECEIPT).write_bytes(original_receipt)
        post=project/'phase3/librelane/analog/receiver_b/a7_resim/receiver_b_post.sp'
        original_model=post.read_bytes()
        post.write_bytes(original_model+b'\n* changed retained second-block model\n')
        try:
            stale=m3.audit(project,'cosim')
            assert stale['passed'] is False,stale
            record_property('stale_second_block_readback',stale)
        finally:
            post.write_bytes(original_model)
        assert m3.audit(project,'cosim')['passed'] is True
        assert m3.audit(project,'si')['passed'] is True
