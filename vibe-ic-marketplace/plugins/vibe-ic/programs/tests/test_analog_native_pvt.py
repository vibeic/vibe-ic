"""Reference-only PVT consumer controls; fixture logs are not native signoff."""
import itertools
import json
from pathlib import Path

import pytest

import analog_bound_measurements as bound
import analog_native_physical as physical
import analog_native_pvt as pvt


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value, dict) else value)
    return path


def view(path):
    return {"path": str(path), "sha256": physical._sha(path)}


@pytest.fixture
def case(tmp_path):
    project = tmp_path / "design"
    directory = project / "phase3/analog/cell"
    model = put(project / "models/model.lib", "\n".join(
        f".lib device_{process}\n.param model_corner=1\n.endl device_{process}" for process in ("tt", "ss", "ff")))
    net = put(directory / "cell.sp", f'.lib "{model}" device_tt\n.subckt cell vin vout vss\nR0 vout vss 100\n.ends cell\n')
    tb = put(directory / "tb_cell.sp", '* source native testbench\n.include "' + str(net) +
        '"\nv_feed vin 0 1.8\ni_sink vout 0 .0005\nxdut vin vout 0 cell\n.control\nop\n.endc\n.end\n')
    put(directory / "spec.json", {"specs": [
        {"name": "vin", "min": 1.6, "max": 2, "target": 1.8, "unit": "V"},
        {"name": "iout", "min": .1, "max": 1, "target": .5, "unit": "mA"},
        {"name": "vout", "min": 1.1, "max": 1.3, "unit": "V"},
        {"name": "iq", "max": 50, "unit": "uA"}, {"name": "dropout", "max": .5, "unit": "V"},
        {"name": "psrr", "min": 40, "unit": "dB"}]})
    rows = []
    points = [(vin, load) for vin in (1.6, 2) for load in (.0001, .001)] + [(1.8, .0005)]
    for index, (process, temp, (vin, load)) in enumerate(itertools.product(("tt", "ss", "ff"), (-40, 27, 125), points)):
        root = project / "studies" / str(index)
        selected = put(root / "cell.sp", net.read_text().replace("device_tt", "device_" + process))
        template = put(root / "template.sp", tb.read_text().replace(str(net), str(selected))
            .replace("v_feed vin 0 1.8", f"v_feed vin 0 {vin}").replace("i_sink vout 0 .0005", f"i_sink vout 0 {load}"))
        binding = {"analysis": {"kind": "OP", "temperature_c": temp},
            "integration_condition": {"process": "device_" + process, "temp_c": temp, "vin_v": vin, "load_a": load},
            "measurements": {"vout": {"analysis": "OP", "expression": "v(vout)", "unit": "V"},
                             "iq": {"analysis": "OP", "expression": f"(-i(v_feed)-{load})*1e6", "unit": "uA"}}}
        values = {"vout": 1.2, "iq": 30}
        if vin == 1.6:
            binding["measurements"]["dropout"] = {"analysis": "OP", "expression": "v(vin)-v(vout)", "unit": "V",
                "interpretation": "upper_bound_when_regulated", "regulation_measurement": "vout"}
            values["dropout"] = .4
            binding["analysis"].update(kind="DC", source="v_feed", start=1.8, stop=vin, step=-.01)
            for row in binding["measurements"].values():
                row.update(analysis="DC", at="last")
        bindings = put(root / "bindings.json", binding)
        def run(program, argv, **kwargs):
            log = put(root / "native.log", f"Doing analysis at TEMP = {temp:.6f} and TNOM = 27\n" +
                "\n".join(f"MEAS {key}={value}" for key, value in values.items()) + "\n")
            return {"returncode": 0, "log": str(log), "log_sha256": physical._sha(log)}
        record = bound.run_measurements(project, selected, template, binding, root / "native", run)
        assert record["status"] == "PASS", record
        record["native_inputs"].update(bindings=view(bindings), source_netlist=view(net))
        result = put(root / "native/result.json", record)
        rows.append({"result": str(result), "source_netlist": view(net)})
    manifest = put(project / "pvt.json", {"source_netlist": view(net), "rows": rows})
    return project, manifest


def consume(case):
    project, manifest = case
    return pvt.run_pvt_studies(project, "cell", view(manifest))


def edit_record(case, index, change):
    _project, manifest = case
    path = Path(json.loads(manifest.read_text())["rows"][index]["result"])
    record = json.loads(path.read_text())
    change(record)
    put(path, record)


def test_complete_native_contexts_retain_partial_source_measurement_scope(case):
    record = consume(case)
    assert record["status"] == "NOT_MEASURED"
    metrics = record["metrics"]
    assert metrics["total_corners"] == metrics["corners_executed"] == 45
    assert metrics["full_pvt_sweep_executed"] is True and not metrics["gaps"]
    assert metrics["source_measurement_coverage"]["missing"] == ["psrr"]
    assert metrics["source_context_coverage"]["dropout"]["measured_contexts"] == 18
    assert metrics["source_context_coverage"]["vout"]["measured_contexts"] == 45
    assert any(key.endswith(":log:0") for key in record["native_inputs"])
    assert physical._current_native_views(record["native_inputs"])


def test_complete_source_outputs_can_pass_without_inventing_unstated_outputs(case):
    project, _manifest = case
    path = project / "phase3/analog/cell/spec.json"
    spec = json.loads(path.read_text())
    spec["specs"] = [row for row in spec["specs"] if row["name"] != "psrr"]
    put(path, spec)
    assert consume(case)["status"] == "PASS"


@pytest.mark.parametrize("mutation", ["missing", "duplicate"])
def test_missing_or_duplicate_context_cannot_complete_matrix(case, mutation):
    _project, manifest = case
    record = json.loads(manifest.read_text())
    record["rows"] = record["rows"][:-1] if mutation == "missing" else record["rows"][:-1] + [record["rows"][0]]
    put(manifest, record)
    result = consume(case)
    assert result["status"] == "NOT_MEASURED"
    assert result["metrics"]["full_pvt_sweep_executed"] is False
    assert len(result["metrics"]["missing_contexts"]) == 1


def test_real_native_failure_wins_over_missing_source_output(case):
    def change(record):
        log = Path(record["executions"][0]["log"])
        log.write_text(log.read_text() + ";;RESIDUAL_FAIL actual native residual\n")
        record["executions"][0]["log_sha256"] = physical._sha(log)
    edit_record(case, 0, change)
    record = consume(case)
    assert record["status"] == "FAIL"
    assert any(row["status"] == "FAIL" for row in record["metrics"]["contexts"])


def test_measured_source_violation_wins_over_missing_psrr(case):
    def change(record):
        record["measurements"]["vout"] = .9
        log = Path(record["executions"][0]["log"])
        log.write_text(log.read_text().replace("MEAS vout=1.2", "MEAS vout=0.9"))
        record["executions"][0]["log_sha256"] = physical._sha(log)
    edit_record(case, 0, change)
    record = consume(case)
    assert record["status"] == "FAIL"


@pytest.mark.parametrize("mutation", ["temperature", "supply", "process", "device", "postlayout", "closure", "deck"])
def test_unsupported_or_changed_native_context_is_not_credited(case, mutation):
    def change(record):
        views = record["native_inputs"]
        if mutation == "temperature":
            log = Path(record["executions"][0]["log"])
            log.write_text(log.read_text().replace("TEMP = -40.000000", "TEMP = 27.000000"))
            record["executions"][0]["log_sha256"] = physical._sha(log)
        elif mutation == "supply":
            record["bindings"]["integration_condition"]["vin_v"] = 2
            bindings = Path(views["bindings"]["path"])
            put(bindings, record["bindings"])
            views["bindings"] = view(bindings)
        elif mutation == "process":
            record["bindings"]["integration_condition"]["process"] = "device_ff"
            bindings = Path(views["bindings"]["path"])
            put(bindings, record["bindings"])
            views["bindings"] = view(bindings)
        elif mutation in ("device", "postlayout"):
            net = Path(views["netlist"]["path"])
            net.write_text(net.read_text().replace("100", "200") if mutation == "device" else
                           net.read_text().replace(".ends cell", "Rpar vin vout .1\n.ends cell"))
            views["netlist"] = view(net)
            views.update(bound.consumed_input_views(case[0], Path(views["deck"]["path"])))
        elif mutation == "closure":
            del views[next(key for key in views if key.startswith("include:"))]
        elif mutation == "deck":
            deck = Path(views["deck"]["path"])
            deck.write_text(deck.read_text().replace("dc v_feed 1.8", "dc v_feed 1.9"))
            views["deck"] = view(deck)
    edit_record(case, 0, change)
    record = consume(case)
    assert record["status"] == "NOT_MEASURED"
    assert record["metrics"]["corners_executed"] == 44
    assert record["metrics"]["gaps"]


def test_source_hash_drift_refuses_every_historical_context(case):
    project, _manifest = case
    net = project / "phase3/analog/cell/cell.sp"
    net.write_text(net.read_text() + "* new source revision\n")
    record = consume(case)
    assert record["status"] == "NOT_MEASURED"
    assert "current canonical PRE DUT" in record["detail"]


def add_ac_contexts(case):
    """Synthetic native-protocol records exercise the real binding/deck reader."""
    project, manifest = case
    data = json.loads(manifest.read_text())
    for index, original in enumerate(list(data["rows"])):
        op = json.loads(Path(original["result"]).read_text())
        root = project / "ac-studies" / str(index)
        net = Path(op["native_inputs"]["netlist"]["path"])
        template = put(root / "template.sp", Path(op["native_inputs"]["testbench"]["path"]).read_text()
            .replace("v_feed vin 0 " + str(op["bindings"]["integration_condition"]["vin_v"]),
                     "v_feed vin 0 " + str(op["bindings"]["integration_condition"]["vin_v"]) + " ac 1"))
        binding = {"analysis":{"kind":"AC", "temperature_c":op["bindings"]["analysis"]["temperature_c"],
                               "points":10, "start_hz":1, "stop_hz":1e6},
            "integration_condition":op["bindings"]["integration_condition"],
            "measurements":{"rejection_at_default_point":{"analysis":"AC", "expression":"-vdb(vout)",
                "frequency_hz":1000, "unit":"dB", "spec_key":"psrr"}}}
        bindings = put(root / "bindings.json", binding)
        def run(program, argv, **kwargs):
            log = put(root / "native.log", f'Doing analysis at TEMP = {binding["analysis"]["temperature_c"]} and TNOM = 27\n'
                'MEAS rejection_at_default_point=60\n')
            return {"returncode":0, "log":str(log), "log_sha256":physical._sha(log)}
        record = bound.run_measurements(project, net, template, binding, root / "native", run)
        assert record["status"] == "PASS", record
        record["native_inputs"].update(bindings=view(bindings), source_netlist=op["native_inputs"]["source_netlist"])
        path = put(root / "native/result.json", record)
        data["rows"].append({"result":str(path)})
    put(manifest, data)


def test_ac_psrr_and_dc_outputs_can_complete_same_native_context_without_band_invention(case):
    add_ac_contexts(case)
    result = consume(case)
    assert result["status"] == "PASS", result["metrics"]["gaps"]
    assert result["metrics"]["corners_executed"] == 45
    assert result["metrics"]["source_context_coverage"]["psrr"]["measured_contexts"] == 45
    assert result["metrics"]["psrr_measurement_frequency_hz"] == 1000
    assert "no source-provided/all-frequency band" in result["metrics"]["psrr_scope"]
    assert len(result["metrics"]["contexts"]) == 90


@pytest.mark.parametrize("mutation", ["amplitude", "output", "frequency", "duplicate_ac"])
def test_ac_psrr_wrong_source_or_mixed_context_cannot_complete_coverage(case, mutation):
    add_ac_contexts(case)
    project, manifest = case
    data = json.loads(manifest.read_text())
    path = Path(data["rows"][45]["result"])
    record = json.loads(path.read_text())
    if mutation == "duplicate_ac":
        data["rows"][-1] = data["rows"][45]
        put(manifest, data)
    else:
        binding = record["bindings"]
        template = Path(record["native_inputs"]["testbench"]["path"])
        if mutation == "amplitude":
            template.write_text(template.read_text().replace("ac 1", "ac 0.01"))
        elif mutation == "output":
            binding["measurements"]["rejection_at_default_point"]["expression"] = "-vdb(vin)"
        else:
            binding["measurements"]["rejection_at_default_point"]["frequency_hz"] = 100
        bindings = Path(record["native_inputs"]["bindings"]["path"])
        put(bindings, binding)
        deck = Path(record["native_inputs"]["deck"]["path"])
        deck.write_text(bound.emit_deck(bound.contextual_template(template.read_text(), template.parent), binding, deck.parent / "curve.dat"))
        record["native_inputs"].update(testbench=view(template), deck=view(deck), bindings=view(bindings))
        put(path, record)
    result = consume(case)
    assert result["status"] == "NOT_MEASURED"
    assert result["metrics"]["source_context_coverage"]["psrr"]["measured_contexts"] < 45
    assert result["metrics"]["gaps"]


@pytest.mark.parametrize("failure", ["below_source_minimum", "native_residual"])
def test_actual_ac_failure_keeps_precedence_over_other_missing_coverage(case, failure):
    add_ac_contexts(case)
    _project, manifest = case
    data = json.loads(manifest.read_text())
    path = Path(data["rows"][45]["result"])
    record = json.loads(path.read_text());log = Path(record["executions"][0]["log"])
    if failure == "below_source_minimum":
        record["measurements"]["rejection_at_default_point"] = 30
        log.write_text(log.read_text().replace("point=60", "point=30"))
    else:
        log.write_text(log.read_text() + ";;RESIDUAL_FAIL native AC residual\n")
    record["executions"][0]["log_sha256"] = physical._sha(log)
    put(path, record)
    data["rows"].pop()  # Missing another context cannot hide actual AC failure.
    put(manifest, data)
    assert consume(case)["status"] == "FAIL"


@pytest.fixture
def post_case(case):
    project, pre_manifest = case
    add_ac_contexts(case)
    directory = project / 'phase3/analog/cell'; net = directory/'cell.sp'; tb = directory/'tb_cell.sp'
    gds = put(directory/'cell.gds', 'software fixture layout identity')
    tech = put(project/'native.tech', 'extract\nstyle ngspice variants (), (fast)\nend\n')
    work = project/'phase3/librelane/analog/cell/native_analog'
    corners, styles = [], []
    source_body = net.read_text()[net.read_text().index('.subckt'):]
    for style in ('ngspice()', 'ngspice(fast)'):
        root = project/'post'/physical._sha(tech)[:8]/pvt.spice._style_slug(style);root.mkdir(parents=True)
        raw = put(root/'actual.spice', source_body.replace('.ends cell',
            'Rpex vin branch 5\nCpex branch vss 1p\n.ends cell'))
        corners.append({'style':style,'extracted_netlist':str(raw),'sha256':physical._sha(raw)})
        base = root/'cell.sp'
        text, mapping = pvt.spice.post_layout_netlist('cell',pvt.spice.subckt_ports(net.read_text(),'cell'),raw.read_text(),
            pvt.spice.model_binding_lines(net.read_text(),directory,root))
        put(base,text)
        post_tb = put(root/'tb_cell.sp',pvt.spice.post_layout_testbench(tb.read_text(),'cell',base.name,directory,root))
        styles.append({'style':style,'source_post_netlist':view(base),'source_post_testbench':view(post_tb),'rows':[]})
    extraction = put(work/'A13.json',{'status':'PASS','native_inputs':{'net':view(net),'gds':view(gds)},'metrics':{
        'netlist_sha256':physical._sha(net),'layout_sha256':physical._sha(gds),'magic_tech':str(tech),'corners':corners}})
    original = json.loads(pre_manifest.read_text())['rows']
    for group,corner in zip(styles,corners):
        base = Path(group['source_post_netlist']['path']);root=base.parent
        for index,entry in enumerate(original):
            prior = json.loads(Path(entry['result']).read_text());process=prior['bindings']['integration_condition']['process']
            folder=root/f'case-{index}';folder.mkdir()
            selected=put(folder/'cell.sp',base.read_text().replace('device_tt',process))
            template=put(folder/'template.sp',Path(prior['native_inputs']['testbench']['path']).read_text()
                .replace(prior['native_inputs']['netlist']['path'],str(selected)))
            binding=prior['bindings'];bindings=put(folder/'bindings.json',binding)
            def run(program,argv,**kwargs):
                log=put(folder/'native.log',Path(prior['executions'][0]['log']).read_text())
                return {'returncode':0,'log':str(log),'log_sha256':physical._sha(log)}
            record=bound.run_measurements(project,selected,template,binding,folder/'native',run)
            assert record['status']=='PASS',record
            record['native_inputs'].update(bindings=view(bindings),source_netlist=view(net),source_post_netlist=view(base),
                raw_extraction={'path':corner['extracted_netlist'],'sha256':corner['sha256']},extraction_record=view(extraction))
            result=put(folder/'native/result.json',record);group['rows'].append({'result':str(result)})
    manifest=put(project/'post-pvt.json',{'stage':'POST','source_netlist':view(net),'extraction':view(extraction),'styles':styles})
    return project,manifest


def test_complete_post_pvt_validates_every_actual_rc_style_and_source_context(post_case):
    result=consume(post_case)
    assert result['status']=='PASS',result
    assert result['metrics']['stage']=='POST'
    assert result['metrics']['total_corners']==result['metrics']['corners_executed']==90
    assert len(result['metrics']['corners'])==2
    assert all(group['result']['metrics']['psrr_measurement_frequency_hz']==1000 for group in result['metrics']['corners'])


@pytest.mark.parametrize('mutation',['old_raw','changed_base','wrong_source_role','missing_style','missing_context','wrong_layout'])
def test_post_pvt_old_rc_or_incomplete_current_inputs_cannot_pass(post_case,mutation):
    project,manifest=post_case;data=json.loads(manifest.read_text());group=data['styles'][0]
    if mutation=='missing_style':data['styles'].pop()
    elif mutation=='missing_context':group['rows']=group['rows'][:-2]
    elif mutation=='wrong_layout':(project/'phase3/analog/cell/cell.gds').write_text('different actual layout')
    elif mutation=='changed_base':
        path=Path(group['source_post_netlist']['path']);path.write_text(path.read_text().replace('Rpex','Rchanged'))
        group['source_post_netlist']=view(path)
    else:
        path=Path(group['rows'][0]['result']);record=json.loads(path.read_text())
        role='raw_extraction' if mutation=='old_raw' else 'source_netlist'
        record['native_inputs'][role]=view(project/'phase3/analog/cell/tb_cell.sp')
        put(path,record)
    put(manifest,data)
    result=consume(post_case)
    assert result['status']=='NOT_MEASURED'
    assert result['metrics'].get('full_pvt_sweep_executed') is not True


def test_post_native_failure_dominates_another_missing_extraction_style(post_case):
    _project,manifest=post_case;data=json.loads(manifest.read_text());data['styles'].pop()
    path=Path(data['styles'][0]['rows'][0]['result']);record=json.loads(path.read_text())
    log=Path(record['executions'][0]['log']);log.write_text(log.read_text()+';;RESIDUAL_FAIL actual native failure\n')
    record['executions'][0]['log_sha256']=physical._sha(log);put(path,record);put(manifest,data)
    assert consume(post_case)['status']=='FAIL'


def test_post_styles_cannot_claim_one_psrr_scope_from_different_frequency_points(post_case):
    _project,manifest=post_case;data=json.loads(manifest.read_text())
    for entry in data['styles'][1]['rows']:
        path=Path(entry['result']);record=json.loads(path.read_text());binding=record['bindings']
        if binding['analysis']['kind']!='AC':continue
        binding['measurements']['rejection_at_default_point']['frequency_hz']=100
        bindings=Path(record['native_inputs']['bindings']['path']);put(bindings,binding)
        template=Path(record['native_inputs']['testbench']['path']);deck=Path(record['native_inputs']['deck']['path'])
        deck.write_text(bound.emit_deck(bound.contextual_template(template.read_text(),template.parent),binding,deck.parent/'curve.dat'))
        record['native_inputs'].update(bindings=view(bindings),deck=view(deck));put(path,record)
    result=consume(post_case)
    assert result['status']=='NOT_MEASURED'
    assert any('frequency differs between extraction styles' in gap['detail'] for gap in result['metrics']['gaps'])
