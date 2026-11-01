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
