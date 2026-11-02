"""A18 behavioral controls through the existing native dispatch (also on main)."""
import hashlib
import json
from pathlib import Path

import pytest

import analog_native_flow as native


def put(root, rel, value):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value, dict) else value)
    return path


def declaration(root):
    ports = {"sample": "input", "result": "output", "serial": "output", "VHI": "input", "VLO": "input",
             "supply": "inout", "VSS": "inout", "supply_io": "inout", "IOVSS": "inout"}
    macros = {}
    for master, pins, kind in (("stage_alpha", {"A": "SIGNAL", "Y": "SIGNAL", "VP": "POWER", "VG": "GROUND"}, "BLOCK"),
                               ("stage_beta", {"A": "SIGNAL", "Y": "SIGNAL", "VP": "POWER", "VG": "GROUND"}, "BLOCK"),
                               ("ref_decap", {"TOP": "SIGNAL", "VSS": "GROUND"}, "BLOCK"),
                               ("bond_cell", {"BOND": "SIGNAL", "CORE": "SIGNAL"}, "PAD")):
        lef = f"MACRO {master}\n CLASS {kind} ;\n SIZE 10 BY 20 ;\n"
        for pin, use in pins.items():
            lef += f" PIN {pin}\n  DIRECTION INOUT ;\n  USE {use} ;\n END {pin}\n"
        lef += f"END {master}\n"
        if master == "bond_cell":
            for auxiliary in ("corner_cell", "bond_filler"):
                lef += f"MACRO {auxiliary}\n CLASS PAD ;\n SIZE 10 BY 10 ;\n"
                lef += " PIN VP\n USE POWER ;\n END VP\n PIN VG\n USE GROUND ;\n END VG\n"
                lef += f"END {auxiliary}\n"
        macros[master] = {}
        for view, data in (("lef", lef), ("gds", "synthetic generation fixture; never executed"),
                           ("spice", f".subckt {master} " + " ".join(reversed(pins))
                            + ("\nCdeclared TOP VSS 25p" if master == "ref_decap" else "")
                            + f"\n.ends {master}\n")):
            path = put(root, f"views/{master}.{view}", data)
            macros[master][view] = str(path.relative_to(root))
    l9 = {"top_module": "neutral_core", "ports": [{"name": n, "direction": d} for n, d in ports.items()],
          "macros": macros, "ties": {"serial": "VSS"}, "instances": [
              {"name": "first", "master": "stage_alpha", "connections": {
                  "A": "sample", "Y": "between", "VP": "supply", "VG": "VSS"},
               "placement": {"location": [100, 100], "orientation": "N"}},
              {"name": "second", "master": "stage_beta", "connections": {
                  "A": "between", "Y": "result", "VP": "supply_io", "VG": "IOVSS"},
               "placement": {"location": [200, 200], "orientation": "FN"}},
              *[{"name": "decap_" + side, "master": "ref_decap",
                 "connections": {"TOP": "VHI" if side == "hi" else "VLO", "VSS": "VSS"},
                 "placement": {"location": [300 + 50 * i, 300], "orientation": "N"}}
                for i, side in enumerate(("hi", "lo"))]],
          "pad_instances": [{"name": f"bond_{n}", "master": "bond_cell", "terminal": "BOND",
                             "connections": {"BOND": n, "CORE": n}} for n in ports]}
    put(root, "phase1/generated_docs/L9_INTEGRATION_SPEC.json", l9)
    put(root, "phase1/generated_docs/L21_POWER_INTENT.json", {"fields": {"power_domains": [
        {"name": "analog", "power_net": "supply", "ground_net": "VSS"},
        {"name": "io", "power_net": "supply_io", "ground_net": "IOVSS"}],
        "hard_macro_supplies": [{"master": m, "pin": p, "rail": n}
                                for m in ("corner_cell", "bond_filler")
                                for p, n in (("VP", "supply_io"), ("VG", "IOVSS"))]}})
    answers = {"deliverable": "DIE", "top_cell": "neutral_core", "fp_sizing": "absolute",
               "die_area_um": [0, 0, 1000, 1000], "die_origin_um": [0, 0],
               "core_area_um": [50, 50, 950, 950],
               "pad_order_by_side": {"south": [f"bond_{n}" for n in ports], "north": [], "east": [], "west": []},
               "pad_signal_map": {f"bond_{n}": n for n in ports},
               "pad_site_name": "bond_site", "pad_corner_site_name": "corner_site",
               "pad_rotations": {"horizontal": "R0", "vertical": "R0", "corner": "R0"},
               "pad_corner_master": "corner_cell", "pad_fillers": ["bond_filler"], "pad_edge_spacing_um": 2}
    put(root, "input/submission_template/tapeout_declaration.json", {
        "schema": "vibe-ic/tapeout_declaration/1", "answers": answers,
        "answer_provenance": {k: {"answered_by": "owner", "citation": "synthetic owner declaration"} for k in answers}})
    return l9


def dispatch(root, *, status="PASS", tamper=False):
    calls = []

    def run(program, argv, **kwargs):
        calls.append(program)
        output = put(root, "phase3/stage3/pnr/routed.def", "DESIGN chip_top ;\nEND DESIGN\n")
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        put(root, "reports/phase3/analog_macro_top_run.json", {
            "producer": "analog_macro_top_run", "component_status": status,
            "reason": "native test result", "outputs": {str(output): digest if not tamper else "0" * 64}})
        return {"returncode": 0, "missing_outputs": [], "outputs": {}}

    options = {"features": {"digital_physical": False}, "config": {}}
    result = native._views("A18", root, {"name": "neutral"}, options, run)
    return result, calls, options


def test_a18_generates_two_macro_config_and_both_netlists(tmp_path):
    declaration(tmp_path)
    result, calls, _ = dispatch(tmp_path)
    assert result["status"] == "PASS", result
    assert calls == ["analog_macro_top_run.py"]
    config = json.loads((tmp_path / "phase3/analog_top/librelane.json").read_text())
    assert config["DESIGN_NAME"] == "chip_top"
    assert config["MACROS"]["stage_alpha"]["instances"] == {
        "u_core__first": {"location": [100, 100], "orientation": "N"}}
    assert config["MACROS"]["stage_beta"]["instances"]["u_core__second"]["orientation"] == "FN"
    assert config["VDD_NETS"] == ["supply", "supply_io"]
    assert config["GND_NETS"] == ["VSS", "IOVSS"]
    assert config["PAD_SOUTH"][0] == "bond_sample"
    assert config["PDN_ENABLE_GLOBAL_CONNECTIONS"] is False
    pdn = (tmp_path / "phase3/analog_top/pdn.tcl").read_text()
    assert "-net {supply_io} -inst_pattern {^u_core__second$}" in pdn
    assert "-net {IOVSS}" in pdn
    assert "eq {bond_filler}" in pdn and "findITerm {VG}" in pdn
    logical = (tmp_path / "phase3/analog_top/chip_top.v").read_text()
    assert "module neutral_core" in logical and "neutral_core u_core" in logical
    assert "assign serial = VSS;" in logical
    flat = (tmp_path / "phase3/analog_top/chip_top.physical.v").read_text()
    assert "stage_alpha u_core__first (.A(core__sample), .Y(between), .VP(supply), .VG(VSS));" in flat
    assert "bond_serial (.BOND(serial), .CORE(VSS))" in flat
    spice = (tmp_path / "phase3/analog_top/chip_top.spice").read_text()
    # The macro declares VG VP Y A, different from connection-map order.
    assert "Xu_core__first VSS supply between core__sample stage_alpha" in spice
    assert "Xu_core__second IOVSS supply_io core__result between stage_beta" in spice
    assert "Xbond_serial VSS serial bond_cell" in spice
    for side, ref, x in (("hi", "VHI", 300), ("lo", "VLO", 350)):
        name = "u_core__decap_" + side
        assert config["MACROS"]["ref_decap"]["instances"][name] == {
            "location": [x, 300], "orientation": "N"}
        assert f"ref_decap {name} (.TOP(core__{ref}), .VSS(VSS));" in flat
        assert f"X{name} VSS core__{ref} ref_decap" in spice
    assert "Cdeclared TOP VSS 25p" in (tmp_path / "views/ref_decap.spice").read_text()
    mapping = json.loads((tmp_path / "reports/phase3/io_pad_chip_top.json").read_text())
    assert (mapping["core_module"], mapping["chip_top_module"]) == ("neutral_core", "chip_top")
    assert result["metric_acceptance"]["status"] == "NOT_MEASURED"


@pytest.mark.parametrize("view", ["gds", "lef", "spice"])
@pytest.mark.parametrize("master", ["stage_beta", "ref_decap"])
def test_a18_missing_macro_view_refuses_by_master_and_view(tmp_path, view, master):
    declaration(tmp_path)
    path = tmp_path / f"views/{master}.{view}"
    path.unlink()
    result, calls, _ = dispatch(tmp_path)
    assert result["status"] == "NOT_MEASURED"
    assert result["detail"] == f"A18_MACRO_VIEW_ABSENT: {master}: {view}: {path}"
    assert calls == []
    assert not (tmp_path / "phase3/analog_top/chip_top.spice").exists()


@pytest.mark.parametrize("mutation, expected", [("top", "A18_CORE_TOP_MISMATCH"),
    ("ground", "A18_IDENTIFIER_INVALID"), ("pin", "A18_CONNECTIVITY_INCOMPLETE"),
    ("supply", "A18_SUPPLY_UNDECLARED"), ("placement", "A18_MACRO_PLACEMENT_ABSENT")])
def test_a18_refuses_undeclared_or_inconsistent_intent(tmp_path, mutation, expected):
    l9 = declaration(tmp_path)
    if mutation == "top":
        l9["top_module"] = "chip_top"
    elif mutation == "pin":
        del l9["instances"][0]["connections"]["VG"]
    elif mutation == "supply":
        l9["instances"][0]["connections"]["VG"] = "invented_return"
    elif mutation == "placement":
        del l9["instances"][0]["placement"]
    elif mutation == "ground":
        put(tmp_path, "phase1/generated_docs/L21_POWER_INTENT.json", {"fields": {"power_domains": [
            {"name": "analog", "power_net": "supply", "ground_net": None}]}})
    put(tmp_path, "phase1/generated_docs/L9_INTEGRATION_SPEC.json", l9)
    result, calls, _ = dispatch(tmp_path)
    assert result["status"] == "NOT_MEASURED"
    assert result["detail"].startswith(expected + ":"), result
    assert calls == []


@pytest.mark.parametrize("status,tamper", [("FAIL", False), ("PASS", True)])
def test_a18_does_not_promote_native_failure_or_changed_outputs(tmp_path, status, tamper):
    declaration(tmp_path)
    result, _, _ = dispatch(tmp_path, status=status, tamper=tamper)
    assert result["status"] == "FAIL", result


def test_a18_runs_chip_once_for_multiple_block_rows(tmp_path):
    declaration(tmp_path)
    first, calls, options = dispatch(tmp_path)
    second = native._views("A18", tmp_path, {"name": "other"}, options,
                           lambda *a, **k: pytest.fail("chip producer repeated"))
    assert first["status"] == second["status"] == "PASS"
    assert len(calls) == 1
    second["status"] = "FAIL"
    assert first["status"] == "PASS"


def test_a18_requires_the_generated_pad_cells_supply_bindings(tmp_path):
    declaration(tmp_path)
    path = tmp_path / "phase1/generated_docs/L21_POWER_INTENT.json"
    l21 = json.loads(path.read_text())
    l21["fields"]["hard_macro_supplies"] = []
    put(tmp_path, str(path.relative_to(tmp_path)), l21)
    result, calls, _ = dispatch(tmp_path)
    assert result["detail"].startswith("A18_AUX_SUPPLY_ABSENT: bond_filler.VP:"), result
    assert calls == []


def test_unchanged_precheck_reads_the_core_wrapper_mapping(tmp_path):
    declaration(tmp_path)
    result, _, _ = dispatch(tmp_path)
    assert result["status"] == "PASS", result
    import general_precheck
    assert general_precheck._recorded_physical_top(tmp_path)["core"] == "neutral_core"


def test_checked_in_registry_dispatches_to_the_macro_top_producer(tmp_path):
    from _hostpaths import require_repo
    import importlib
    registry = json.loads(require_repo("vibe-ic-marketplace", "plugins", "vibe-ic",
                                      "flow", "flow109.json").read_text())
    row = next(r for r in registry["rows"] if r["id"] == "A18")
    adapter = importlib.import_module(row["profiles"][0]["dispatch"]["adapter"])
    declaration(tmp_path)
    result = adapter._views("A18", tmp_path, {"name": "neutral"},
        {"features": {"digital_physical": True}, "config": {}},
        lambda *a, **k: pytest.fail("digital top must retain ownership"))
    assert result["status"] == "NOT_APPLICABLE"


def test_a18_waits_for_all_a17_writers(tmp_path, monkeypatch):
    import threading
    from types import SimpleNamespace
    declaration(tmp_path)
    put(tmp_path, "phase3/analog/analog_block_list.json", {"blocks": [
        {"name": "first", "type": "amplifier"}, {"name": "second", "type": "amplifier"}]})
    put(tmp_path, "input/analog_flow.json", {"workers": 2})
    monkeypatch.setattr(native, "_adapter_transport", lambda p: ("", "", "HOST"))
    first_done = threading.Event()
    completed = set()

    def dispatch_step(step, project, block, options, run):
        if step == "A17":
            if block["name"] == "second":
                assert first_done.wait(2)
                threading.Event().wait(0.05)
            completed.add(block["name"])
            if block["name"] == "first":
                first_done.set()
        elif step == "A18":
            assert completed == {"first", "second"}, "chip assembly raced an A17 writer"
        return {"status": "PASS", "outputs": []}

    monkeypatch.setattr(native, "_dispatch", dispatch_step)
    result = native.run_window(tmp_path, SimpleNamespace(entry_step="A17", exit_step="A18",
        blocks="", pdk="", container=""), features={"digital_physical": False})
    assert result["window_verdict"] == "PASS"


@pytest.mark.parametrize("component_status,expected", [("PASS", "NOT_MEASURED"), ("FAIL", "FAIL")])
def test_macro_implementation_cannot_claim_row_signoff(tmp_path, component_status, expected):
    result = native.consume_default_row_completion(tmp_path, {"requested_step": "A18"}, {
        "component_status": component_status, "native_results": {"steps": [{
            "native_evidence": {"producer": "analog_macro_top_run"}}]}})
    assert result["default_row_status"] == expected
    assert result["delivery_accepted"] is False


def test_a18_accepts_separate_view_bindings_without_changing_instances(tmp_path):
    l9 = declaration(tmp_path)
    catalog = l9.pop("macros")
    put(tmp_path, "phase1/generated_docs/L9_INTEGRATION_SPEC.json", l9)
    put(tmp_path, "input/analog_flow.json", {"analog_top": {"macros": catalog}})
    result, _, _ = dispatch(tmp_path)
    assert result["status"] == "PASS", result
    intent = json.loads((tmp_path / "phase3/analog_top/pdn_intent.json").read_text())
    assert intent["core_instances"] == ["u_core__first", "u_core__second", "u_core__decap_hi", "u_core__decap_lo"]
    assert [(d["power_net"],d["ground_net"]) for d in intent["domains"]] == [("supply","VSS"),("supply_io","IOVSS")]
    spice = (tmp_path / "phase3/analog_top/chip_top.spice").read_text()
    assert "Xu_core__decap_hi" in spice and "Xu_core__decap_lo" in spice


def test_a18_reports_all_missing_external_views_by_master(tmp_path):
    declaration(tmp_path)
    put(tmp_path, "input/analog_flow.json", {"analog_top": {"macros": {
        "required_filter": {}, "required_reference": {}}}})
    result, calls, _ = dispatch(tmp_path)
    assert result["status"] == "NOT_MEASURED", result
    assert result["detail"].startswith("A18_MACRO_VIEW_ABSENT:"), result
    for master in ("required_filter", "required_reference"):
        for view in ("gds", "lef", "spice"):
            assert f"{master}: {view}: not declared" in result["detail"]
    assert calls == []


def test_a18_external_views_cannot_supply_missing_l9_instances(tmp_path):
    l9 = declaration(tmp_path)
    catalog = l9.pop("macros")
    del l9["instances"]
    put(tmp_path, "phase1/generated_docs/L9_INTEGRATION_SPEC.json", l9)
    put(tmp_path, "input/analog_flow.json", {"analog_top": {"macros": catalog}})
    result, calls, _ = dispatch(tmp_path)
    assert result["status"] == "NOT_MEASURED", result
    assert result["detail"].startswith("A18_INSTANCES_ABSENT:"), result
    assert calls == []


def test_native_final_pdn_failure_is_blocking(tmp_path, monkeypatch):
    import subprocess
    import analog_macro_top_pdn as pdn
    def fail(command, **kwargs):
        raise subprocess.CalledProcessError(1,command)
    monkeypatch.setattr(pdn.subprocess,"run",fail)
    with pytest.raises(subprocess.CalledProcessError):
        pdn.check(tmp_path / "native.odb",["supply_renamed","return_renamed"],tmp_path,"openroad")
    script = (tmp_path / "check-final-pdn.tcl").read_text()
    assert "check_power_grid -net {supply_renamed}" in script
    assert "check_power_grid -net {return_renamed}" in script
    assert "exit $failed" in script


def test_pad_only_rail_preserves_each_declared_supply_landing(monkeypatch, tmp_path):
    import sys
    from types import SimpleNamespace as Object
    import analog_macro_top_pdn as pdn

    pins = []
    term = Object(getBPins=lambda: pins)
    net = Object(getSWires=lambda: [])
    block = Object(findNet=lambda name: net, findBTerm=lambda name: term,
                   findInst=lambda name: Object(findITerm=lambda terminal: name))
    database = Object(getChip=lambda: Object(getBlock=lambda: block))

    def new_pin(term):
        pin = Object(setPlacementStatus=lambda status: None)
        pins.append(pin)
        return pin

    odb = Object(
        dbDatabase=Object(create=lambda: database),
        read_db=lambda *args: None, write_db=lambda *args: None, write_def=lambda *args: None,
        dbSWire=Object(create=lambda *args: object()),
        dbBPin=Object(create=new_pin, destroy=lambda pin: pins.remove(pin)),
        dbBox=Object(create=lambda pin, layer, *coords: setattr(pin, "landing", coords)),
        dbSBox=Object(create=lambda *args: None))
    monkeypatch.setitem(sys.modules, "odb", odb)
    monkeypatch.setattr(pdn, "loaded_rails", lambda *args: set())
    monkeypatch.setattr(pdn, "connect_macro_edges", lambda *args: None)
    monkeypatch.setattr(pdn, "connect_pad_ties", lambda *args: None)
    landings = {"pad_supply_a": (0, 0, 2, 2), "pad_supply_b": (10, 0, 12, 2)}
    monkeypatch.setattr(pdn, "bond_geometry", lambda name, side: ("metal", landings[name]))
    monkeypatch.setattr(pdn, "box", lambda rect: rect)
    intent = {"rails": {"supply_io": "POWER"}, "pads": [
        {"name": name, "port": "supply_io", "terminal": "bond", "side": "south"}
        for name in landings]}
    pdn.finish(tmp_path / "native.odb", intent, {}, tmp_path)
    assert [pin.landing for pin in pins] == list(landings.values())


def macro_escape_scene(monkeypatch):
    import sys
    from types import SimpleNamespace as Object
    import analog_macro_top_pdn as pdn

    def rect(a, b, c, d):
        return Object(xMin=lambda: a, yMin=lambda: b, xMax=lambda: c, yMax=lambda: d)

    def layer(name, level):
        return Object(getName=lambda: name, getRoutingLevel=lambda: level, getSpacing=lambda: 0, getMinWidth=lambda: 2)

    metal, mesh = layer("M1", 1), layer("M2", 2)
    via_boxes = [Object(getTechLayer=lambda l=l: l, **vars(rect(-1,-1,1,1)))
                 for l in (metal, mesh)]
    via = Object(getBoxes=lambda: via_boxes)
    target = Object(isVia=lambda: False, getTechLayer=lambda: mesh, **vars(rect(20,0,22,10)))
    supply_wire = Object(getWires=lambda: [target])
    supply = Object(getName=lambda: "supply", getSWires=lambda: [supply_wire])
    foreign_wire = Object(isVia=lambda: False, getTechLayer=lambda: metal, **vars(rect(14,4,16,6)))
    foreign = Object(getName=lambda: "neighbor", getSWires=lambda: [Object(getWires=lambda: [foreign_wire])])
    pin_shapes = [(metal,rect(9,4,10,6))]
    term = Object(getNet=lambda: supply, getGeometries=lambda: pin_shapes,
                  getMTerm=lambda: Object(getName=lambda: "VP"))
    inst = Object(getBBox=lambda: rect(0,0,10,10), getITerms=lambda: [term],
                  getName=lambda: "macro_a", getMaster=lambda: Object(getObstructions=lambda: []))
    block = Object(findInst=lambda name: inst, getInsts=lambda: [inst], getVias=lambda: [via],
                   getNets=lambda: [supply,foreign], getObstructions=lambda: [])
    db = Object(getChip=lambda: Object(getBlock=lambda: block),
                getTech=lambda: Object(getVias=lambda: []))
    created = []
    def point(x, y):
        return Object(x=lambda: x, y=lambda: y)
    monkeypatch.setitem(sys.modules,"odb",Object(Point=point, dbSBox=Object(create=lambda *args: created.append(args))))
    intent = {"core_instances": ["macro_a"], "rails": {"supply": "POWER"}}
    config = {"PDN_VERTICAL_LAYER": "M1", "PDN_HORIZONTAL_LAYER": "M2"}
    return locals()


@pytest.mark.parametrize("obstacle", ["wire", "pin", "macro", "obstruction", "via_enclosure"])
def test_macro_escape_refuses_foreign_net_crossing(monkeypatch, obstacle):
    from types import SimpleNamespace as Object
    from librelane_contract import Refusal
    scene = macro_escape_scene(monkeypatch)
    block, metal, rect = scene["block"], scene["metal"], scene["rect"]
    foreign = scene["foreign"]
    if obstacle != "wire":
        foreign.getSWires = lambda: []
    if obstacle in ("pin", "macro", "obstruction"):
        obstruction = Object(getTechLayer=lambda: metal, **vars(rect(14,4,16,6)))
        pin = Object(getNet=lambda: foreign, getGeometries=lambda: [(metal,rect(14,4,16,6))])
        other = Object(getName=lambda: "macro_b", getBBox=lambda: rect(14,0,16,10),
                       getITerms=lambda: [pin] if obstacle == "pin" else [],
                       getMaster=lambda: Object(getObstructions=lambda: [obstruction] if obstacle == "obstruction" else []),
                       getTransform=lambda: Object(apply=lambda shape: None))
        block.getInsts = lambda: [scene["inst"],other]
        if obstacle == "macro":
            scene["intent"]["core_instances"].append("macro_b")
    if obstacle == "via_enclosure":
        mesh = scene["mesh"]
        scene["target"].__dict__.update(vars(rect(18,0,24,10)))
        scene["via_boxes"][1] = Object(getTechLayer=lambda: mesh, **vars(rect(-2,-2,2,2)))
        foreign.getSWires = lambda: [Object(getWires=lambda: [Object(
            isVia=lambda: False, getTechLayer=lambda: mesh, **vars(rect(20,6,22,8)))])]
    with pytest.raises(Refusal, match="A18_MACRO_PG_ESCAPE_BLOCKED.*macro_a/VP"):
        scene["pdn"].connect_macro_edges(scene["db"],scene["intent"],scene["config"])
    assert scene["created"] == []


def test_macro_escape_selects_an_unblocked_pin_access(monkeypatch):
    scene = macro_escape_scene(monkeypatch)
    scene["pin_shapes"].append((scene["metal"],scene["rect"](9,7,10,9)))
    scene["pdn"].connect_macro_edges(scene["db"],scene["intent"],scene["config"])
    assert scene["created"][0][2:6] == (10,7,21,9)
    assert len(scene["created"]) == 2


def test_macro_escape_requires_full_target_via_enclosure(monkeypatch):
    from librelane_contract import Refusal
    scene = macro_escape_scene(monkeypatch)
    # The centre lies on the target, but its M2 enclosure extends outside it.
    scene["target"].__dict__.update(vars(scene["rect"](20,5,22,10)))
    with pytest.raises(Refusal, match="A18_MACRO_PG_EDGE_ACCESS_ABSENT"):
        scene["pdn"].connect_macro_edges(scene["db"],scene["intent"],scene["config"])
    assert scene["created"] == []



def test_macro_escape_rotates_obstructions_with_native_points(monkeypatch):
    import sys
    from types import SimpleNamespace as Object
    import analog_macro_top_pdn as pdn

    class Point:
        def __init__(self, x, y):
            self.coords = x,y
        def x(self):
            return self.coords[0]
        def y(self):
            return self.coords[1]

    transformed = []
    def apply(point):
        transformed.append(point.coords)
        point.coords = 100-point.y(), 200+point.x()

    monkeypatch.setitem(sys.modules,"odb",Object(Point=Point))
    obstruction = Object(xMin=lambda: 1, yMin=lambda: 2, xMax=lambda: 3, yMax=lambda: 4)
    inst = Object(getTransform=lambda: Object(apply=apply))
    assert pdn.placed_obstruction(inst,obstruction) == (96,201,98,203)
    assert set(transformed) == {(1,2),(1,4),(3,2),(3,4)}


def test_macro_escape_keeps_pin_width_until_local_via_enclosure(monkeypatch):
    from types import SimpleNamespace as Object
    scene = macro_escape_scene(monkeypatch)
    metal, mesh, rect = scene["metal"], scene["mesh"], scene["rect"]
    metal.getMinWidth = lambda: 1640
    metal.getSpacing = lambda: 1640
    scene["foreign"].getSWires = lambda: []
    scene["inst"].getBBox = lambda: rect(0,0,10000,10000)
    scene["pin_shapes"][:] = [(metal,rect(7340,1000,8980,10000))]
    obstruction = Object(getTechLayer=lambda: metal, **vars(rect(4500,1000,5700,8490)))
    scene["inst"].getMaster = lambda: Object(getObstructions=lambda: [obstruction])
    scene["inst"].getTransform = lambda: Object(apply=lambda point: None)
    scene["target"].__dict__.update(vars(rect(0,20000,10000,22200)))
    scene["via_boxes"][:] = [Object(getTechLayer=lambda: metal, **vars(rect(-1100,-950,1100,950))),
                               Object(getTechLayer=lambda: mesh, **vars(rect(-950,-1100,950,1100)))]
    scene["pdn"].connect_macro_edges(scene["db"],scene["intent"],scene["config"])
    assert scene["created"][0][2:6] == (7340,10000,8980,21100)
    assert scene["created"][1][1] is scene["via"]
    assert scene["created"][1][2:4] == (8160,21100)


def test_macro_escape_refuses_pin_below_native_minimum_width(monkeypatch):
    from librelane_contract import Refusal
    scene = macro_escape_scene(monkeypatch)
    scene["foreign"].getSWires = lambda: []
    scene["metal"].getMinWidth = lambda: 3
    with pytest.raises(Refusal, match="A18_MACRO_PG_PIN_TOO_NARROW.*macro_a/VP"):
        scene["pdn"].connect_macro_edges(scene["db"],scene["intent"],scene["config"])
    assert scene["created"] == []


def native_macro_escape_grid(tmp_path, preferred_width=1, pin_width=2, block_via=False):
    """Build a neutral fixed-via PDK, then let native pdngen create its grid."""
    import shutil
    import subprocess
    import analog_macro_top_pdn as pdn
    odb = pytest.importorskip("odb")
    openroad = shutil.which("openroad")
    if not openroad:
        pytest.skip("native OpenROAD is required for the PDN access control")
    lef = tmp_path / "access.lef"
    lef.write_text(f'''VERSION 5.8 ;
BUSBITCHARS "[]" ; DIVIDERCHAR "/" ;
UNITS DATABASE MICRONS 1000 ; END UNITS
MANUFACTURINGGRID 0.001 ;
LAYER M1
 TYPE ROUTING ; DIRECTION HORIZONTAL ; PITCH 2 ; WIDTH {preferred_width} ; MINWIDTH 1 ; SPACING 1 ;
 RESISTANCE RPERSQ 1 ; CAPACITANCE CPERSQDIST 0.01 ;
END M1
LAYER C1
 TYPE CUT ; SPACING 0.2 ;
END C1
LAYER M2
 TYPE ROUTING ; DIRECTION VERTICAL ; PITCH 2 ; WIDTH 1 ; MINWIDTH 1 ; SPACING 1 ;
 RESISTANCE RPERSQ 1 ; CAPACITANCE CPERSQDIST 0.01 ;
END M2
VIA VIA12 DEFAULT
 LAYER M1 ; RECT -0.5 -0.5 0.5 0.5 ;
 LAYER C1 ; RECT -0.1 -0.1 0.1 0.1 ;
 LAYER M2 ; RECT -0.5 -0.5 0.5 0.5 ;
END VIA12
SITE coreSite
 CLASS CORE ; SIZE 1 BY 1 ; SYMMETRY Y ;
END coreSite
MACRO neutral_macro
 CLASS BLOCK ; ORIGIN 0 0 ; SIZE 10 BY 10 ;
 PIN VP
 DIRECTION INOUT ; USE POWER ; PORT LAYER M1 ; RECT 9 {5-pin_width/2} 10 {5+pin_width/2} ; END
 END VP
END neutral_macro
END LIBRARY
''')
    db = odb.dbDatabase.create()
    odb.read_lef(db,str(lef))
    chip = odb.dbChip.create(db,db.getTech())
    block = odb.dbBlock.create(chip,"neutral_top")
    block.setDefUnits(1000)
    block.setDieArea(odb.Rect(0,0,100000,100000))
    power = odb.dbNet.create(block,"SUPPLY")
    power.setSigType("POWER"); power.setSpecial()
    ground = odb.dbNet.create(block,"RETURN")
    ground.setSigType("GROUND"); ground.setSpecial()
    inst = odb.dbInst.create(block,db.findMaster("neutral_macro"),"macro0")
    inst.setPlacementStatus("FIRM")
    inst.findITerm("VP").connect(power)
    initial, generated = tmp_path / "initial.odb", tmp_path / "grid.odb"
    odb.write_db(db,str(initial))
    script = tmp_path / "grid.tcl"
    script.write_text(f'''read_db {{{initial}}}
initialize_floorplan -die_area {{0 0 100 100}} -core_area {{0 0 100 100}} -site coreSite
set_voltage_domain -name Core -power SUPPLY -ground RETURN
define_pdn_grid -name grid -voltage_domains Core
add_pdn_stripe -grid grid -layer M1 -width 1 -pitch 40 -spacing 18 -offset 20 -nets {{SUPPLY RETURN}}
add_pdn_stripe -grid grid -layer M2 -width 1 -pitch 40 -spacing 18 -offset 20 -nets {{SUPPLY RETURN}}
add_pdn_connect -grid grid -layers {{M1 M2}}
pdngen
write_db {{{generated}}}
''')
    result = subprocess.run([openroad,"-exit",str(script)],capture_output=True,text=True)
    (tmp_path / "grid.log").write_text(result.stdout+result.stderr)
    assert result.returncode == 0, result.stdout+result.stderr
    db = odb.dbDatabase.create()
    odb.read_db(db,str(generated))
    block = db.getChip().getBlock()
    assert not list(block.getVias())
    assert db.getTech().findVia("VIA12") is not None
    if block_via:
        via = odb.dbVia.create(block,"equivalent_block_via")
        for shape in db.getTech().findVia("VIA12").getBoxes():
            odb.dbBox.create(via,shape.getTechLayer(),*pdn.box(shape))
    return db


def test_native_macro_escape_accepts_fixed_tech_via(tmp_path):
    import analog_macro_top_pdn as pdn
    db = native_macro_escape_grid(tmp_path)
    power = db.getChip().getBlock().findNet("SUPPLY")
    before = {s.getId() for w in power.getSWires() for s in w.getWires()}
    pdn.connect_macro_edges(db,{"rails": {"SUPPLY": "POWER", "RETURN": "GROUND"},
                               "core_instances": ["macro0"]},
                            {"PDN_VERTICAL_LAYER": "M2", "PDN_HORIZONTAL_LAYER": "M1"})
    added = [s for w in power.getSWires() for s in w.getWires() if s.getId() not in before]
    assert len(added) == 2
    assert any(s.isVia() and s.getTechVia() is not None for s in added)


def test_native_macro_escape_uses_minwidth_instead_of_preferred_width(tmp_path):
    import analog_macro_top_pdn as pdn
    db = native_macro_escape_grid(tmp_path,preferred_width=2,pin_width=1,block_via=True)
    layer = db.getTech().findLayer("M1")
    assert layer.getWidth() == 2000 and layer.getMinWidth() == 1000
    pdn.connect_macro_edges(db,{"rails": {"SUPPLY": "POWER", "RETURN": "GROUND"},
                               "core_instances": ["macro0"]},
                            {"PDN_VERTICAL_LAYER": "M2", "PDN_HORIZONTAL_LAYER": "M1"})
    shapes = [s for w in db.getChip().getBlock().findNet("SUPPLY").getSWires() for s in w.getWires()
              if not s.isVia() and s.getTechLayer() == layer and s.xMin() == 10000]
    assert shapes and all(s.yMax()-s.yMin() == layer.getMinWidth() for s in shapes)


@pytest.mark.parametrize("block_via",[False,True])
def test_native_macro_escape_still_refuses_pin_below_minwidth(tmp_path,block_via):
    import analog_macro_top_pdn as pdn
    from librelane_contract import Refusal
    db = native_macro_escape_grid(tmp_path,preferred_width=2,pin_width=0.8,block_via=block_via)
    with pytest.raises(Refusal,match="A18_MACRO_PG_PIN_TOO_NARROW.*macro0/VP"):
        pdn.connect_macro_edges(db,{"rails": {"SUPPLY": "POWER", "RETURN": "GROUND"},
                                   "core_instances": ["macro0"]},
                                {"PDN_VERTICAL_LAYER": "M2", "PDN_HORIZONTAL_LAYER": "M1"})


@pytest.mark.parametrize("rail_name", ["regulated", "unnamed_supply"])
@pytest.mark.parametrize("missing_side", [None, "west"])
def test_internal_regulator_rail_needs_straps_not_external_pad_bands(tmp_path, rail_name, missing_side):
    """Reviewer counterexample: an internal regulator output feeds a macro PG pin."""
    import analog_macro_top_pdn as pdn
    from librelane_contract import Refusal
    odb = pytest.importorskip("odb")
    lef = '''VERSION 5.8 ;
BUSBITCHARS "[]" ; DIVIDERCHAR "/" ;
UNITS DATABASE MICRONS 1000 ; END UNITS
LAYER M1 TYPE ROUTING ; DIRECTION HORIZONTAL ; PITCH 2 ; WIDTH 1 ; SPACING 1 ; END M1
LAYER C1 TYPE CUT ; SPACING 0.2 ; END C1
LAYER M2 TYPE ROUTING ; DIRECTION VERTICAL ; PITCH 2 ; WIDTH 1 ; SPACING 1 ; END M2
'''
    lef += """VIA VIA12 DEFAULT
 LAYER M1 ; RECT -0.5 -0.5 0.5 0.5 ;
 LAYER C1 ; RECT -0.1 -0.1 0.1 0.1 ;
 LAYER M2 ; RECT -0.5 -0.5 0.5 0.5 ;
END VIA12
"""
    for master, kind, pins in [
        ("pad_cell", "PAD", {"VP": "POWER", "VG": "GROUND"}),
        ("regulator_cell", "BLOCK", {"IN": "POWER", "OUT": "POWER", "VG": "GROUND"}),
        ("load_cell", "BLOCK", {"VP": "POWER", "VG": "GROUND"}),
    ]:
        lef += f'MACRO {master}\n CLASS {kind} ; ORIGIN 0 0 ; SIZE 10 BY 10 ;\n'
        for i, (pin, use) in enumerate(pins.items()):
            x = 1 + 2*i
            lef += f' PIN {pin}\n DIRECTION INOUT ; USE {use} ; PORT LAYER M2 ; RECT {x} 1 {x+1} 2 ; END\n END {pin}\n'
        lef += f'END {master}\n'
    source = tmp_path / "neutral.lef"
    source.write_text(lef + "END LIBRARY\n")
    db = odb.dbDatabase.create()
    odb.read_lef(db, str(source))
    block = odb.dbBlock.create(odb.dbChip.create(db, db.getTech()), "internal_supply_top")
    block.setDefUnits(1000)
    block.setDieArea(odb.Rect(0, 0, 1000000, 1000000))
    block.setCoreArea(odb.Rect(100000, 100000, 900000, 900000))
    rails = {"external_supply": "POWER", "external_return": "GROUND", rail_name: "POWER"}
    nets = {}
    for name, kind in rails.items():
        net = odb.dbNet.create(block, name)
        net.setSigType(kind)
        net.setSpecial()
        nets[name] = net
    def place(name, master, x, y, connections):
        inst = odb.dbInst.create(block, db.findMaster(master), name)
        inst.setLocation(x*1000, y*1000)
        inst.setPlacementStatus("FIRM")
        for pin, net in connections.items():
            inst.findITerm(pin).connect(nets[net])
        return inst
    pads = []
    for side, x, y in [("south", 500, 40), ("east", 950, 500), ("north", 500, 950), ("west", 40, 500)]:
        if side == missing_side:
            continue
        name = "pad_" + side
        place(name, "pad_cell", x, y, {"VP": "external_supply", "VG": "external_return"})
        pads.append({"name": name, "side": side, "port": "external_supply", "terminal": "VP"})
        pads.append({"name": name, "side": side, "port": "external_return", "terminal": "VG"})
    regulator = place("regulator", "regulator_cell", 300, 300,
                      {"IN": "external_supply", "OUT": rail_name, "VG": "external_return"})
    load = place("load", "load_cell", 500, 500, {"VP": rail_name, "VG": "external_return"})
    assert regulator.findITerm("OUT").getNet() == load.findITerm("VP").getNet()
    source = tmp_path / "input.odb"
    odb.write_db(db, str(source))
    config = {"PDN_VERTICAL_LAYER": "M2", "PDN_HORIZONTAL_LAYER": "M1"}
    for axis in ("V", "H"):
        for key, value in [("WIDTH", 1), ("PITCH", 20), ("OFFSET", 2), ("SPACING", 2)]:
            config['PDN_' + axis + key] = value
        for key, value in [("WIDTH", 1), ("SPACING", 1), ("OFFSET", 2)]:
            config['PDN_CORE_RING_' + axis + key] = value
    intent = {"rails": rails, "core_instances": ["regulator", "load"], "pads": pads}
    recipe = tmp_path / "pdn.tcl"
    if missing_side:
        with pytest.raises(Refusal, match="A18_PAD_PG_BAND_ABSENT.*external_supply"):
            pdn.prepare_recipe(source, config, intent, "", recipe)
        return
    pdn.prepare_recipe(source, config, intent, "", recipe)
    lines = recipe.read_text().splitlines()
    stripes = [line for line in lines if line.startswith("add_pdn_stripe")]
    rings = [line for line in lines if line.startswith("add_pdn_ring")]
    assert len(stripes) == 2 and all(rail_name in line for line in stripes)
    assert len(rings) == 3 and all(rail_name not in line for line in rings)
    assert all(rail in "\n".join(rings) for rail in ("external_supply", "external_return"))
    import shutil
    import subprocess
    openroad = shutil.which("openroad")
    assert openroad, "The native image must provide OpenROAD"
    script = tmp_path / "run-pdn.tcl"
    output = tmp_path / "grid.odb"
    script.write_text(f"read_db {{{source}}}\n" + recipe.read_text()
                      + f"pdngen\nwrite_db {{{output}}}\n")
    result = subprocess.run([openroad, "-exit", str(script)], capture_output=True, text=True)
    (tmp_path / "pdngen.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    db = odb.dbDatabase.create()
    odb.read_db(db, str(output))
    internal = db.getChip().getBlock().findNet(rail_name)
    shapes = [shape for wire in internal.getSWires() for shape in wire.getWires()]
    assert any(not shape.isVia() for shape in shapes), "internal rail has no native straps"
    assert any(shape.isVia() for shape in shapes), "internal rail straps are not joined"


def test_generator_keeps_regulator_output_internal_in_pdn_intent(tmp_path):
    from analog_macro_top_gen import generate
    l9 = declaration(tmp_path)
    l9["instances"][0]["connections"]["Y"] = "regulated"
    l9["instances"][1]["connections"].update(A="sample", VP="regulated")
    put(tmp_path, "phase1/generated_docs/L9_INTEGRATION_SPEC.json", l9)
    lef = tmp_path / "views/stage_alpha.lef"
    lef.write_text(lef.read_text().replace(
        "PIN Y\n  DIRECTION INOUT ;\n  USE SIGNAL",
        "PIN Y\n  DIRECTION INOUT ;\n  USE POWER"))
    l21 = tmp_path / "phase1/generated_docs/L21_POWER_INTENT.json"
    power = json.loads(l21.read_text())
    power["fields"]["power_rails"] = [{"name": "regulated", "kind": "POWER"}]
    l21.write_text(json.dumps(power))
    assert generate(tmp_path)["verdict"] == "WROTE"
    intent = json.loads((tmp_path / "phase3/analog_top/pdn_intent.json").read_text())
    assert intent["rails"]["regulated"] == "POWER"
    assert all(pad["port"] != "regulated" for pad in intent["pads"])
    flat = (tmp_path / "phase3/analog_top/chip_top.physical.v").read_text()
    assert ".Y(regulated)" in flat and ".VP(regulated)" in flat
