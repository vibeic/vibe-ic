import json
import shlex
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analog_native_erc as erc


def _source():
    return ("# Copyright foundry authors; SPDX-License-Identifier: Apache-2.0\n"
            "logger.info('Starting SG13G2 LVS connectivity setup')\n" +
            "\n".join(erc._SOFT) + "\n# RF MOS model mapping\n")


def test_derivative_preserves_source_and_native_checks():
    source = _source()
    deck = erc._derive(source)
    assert deck.startswith(source.splitlines()[0])
    assert "soft_connect(ntap, nwell_drw)" in deck
    assert "soft_connect(cont_drw, ntap)" in deck
    assert "l2n_data.check_extraction_errors" in deck
    assert "RBA::DeviceClassMOS4Transistor" in deck
    assert "polygons_of_net(bulk, i)" in deck
    assert deck.index("name(metal1_con,") < deck.index("soft_connect(ptap, pwell)")


def test_floating_metal_ties_follow_only_declared_native_material_edges():
    deck = erc._derive(_source())
    edges_line = next(line for line in deck.splitlines() if line.startswith("erc_soft_edges = "))
    edges = json.loads(edges_line.split(" = ", 1)[1])
    assert edges == [
        ["ERC_SOFT_pwell", "ERC_SOFT_ptap"],
        ["ERC_SOFT_nwell_drw", "ERC_SOFT_ntap"],
        ["ERC_SOFT_ntap", "ERC_SOFT_cont_drw"],
        ["ERC_SOFT_ptap", "ERC_SOFT_cont_drw"],
        ["ERC_SOFT_ntap1_tie", "ERC_SOFT_cont_drw"],
        ["ERC_SOFT_ptap1_tie", "ERC_SOFT_cont_drw"],
        ["ERC_SOFT_ntap1_well", "ERC_SOFT_ntap1_tie"],
        ["ERC_SOFT_ptap1_sub", "ERC_SOFT_ptap1_tie"],
    ]
    assert "lower.interacting(upper).is_empty?" in deck
    assert "native_soft_tie_path" in deck
    assert "__ERC_SOFT_EDGES__" not in deck
    # These would alter the netlist rather than observe its physical regions.
    for mutation in (".join_nets", "make_top_level_pins", "make_soft_connection_diodes ="):
        assert mutation not in deck


@pytest.mark.parametrize("metal_tied,error,expected", [
    (True, None, "PASS"),
    (False, None, "FAIL"),
    (True, "[soft-connection-check] two soft-connected partial nets", "FAIL"),
])
def test_actual_control_shapes_keep_missing_ties_and_native_errors_decisive(metal_tied, error, expected):
    # Native controls: a floating labelled ring reached through PWELL/PTAP/CONT;
    # the same GDS minus its 14 body contacts; two MOS terminal nets tied only
    # through that high-ohmic well. The third has a tie but remains a failure.
    record = {"mos_bodies": [{"bulk_net": "$1", "metal_tied": metal_tied,
               "native_soft_tie_path": [{"lower_layer": "ERC_SOFT_pwell",
                                          "upper_layer": "ERC_SOFT_ptap"}] if metal_tied else None}],
              "native_extraction_error": error}
    assert erc.grade(record, 0)[0] == expected


def test_unknown_foundry_shape_is_not_silently_accepted():
    with pytest.raises(ValueError, match="unsupported foundry connectivity"):
        erc._derive(_source().replace("connect(pwell, ptap)", "connect(other, ptap)"))


def test_exact_transitive_foundry_closure():
    files = {"/pdk/main.lvs": "# %include rules/connect.lvs\nend\n",
             "/pdk/rules/connect.lvs": "# original license\nconnect(a,b)\n"}
    assert erc._flatten(files, "/pdk/main.lvs") == "# original license\nconnect(a,b)\n\nend\n"
    with pytest.raises(ValueError, match="missing foundry include"):
        erc._flatten({"/pdk/main.lvs": files["/pdk/main.lvs"]}, "/pdk/main.lvs")
    with pytest.raises(ValueError, match="recursive foundry include"):
        erc._flatten({"/a": "# %include a\n"}, "/a")


def test_netgen_setup_never_selected_as_klayout_deck(tmp_path):
    resolved = {"lvs_deck": "/pdk/netgen/setup.tcl", "klayout_dir": "/pdk/klayout"}
    assert erc.select_deck(tmp_path, resolved, "ihp-sg13g2") == "/pdk/klayout/tech/lvs/sg13g2.lvs"
    assert erc.select_deck(tmp_path, resolved, "other-process") == ""
    assert erc.select_deck(tmp_path, {"lvs_deck": "/staged/actual.lvs"}, "process") == "/staged/actual.lvs"


@pytest.mark.parametrize("erc_status,pv_ok,expected", [("PASS", True, "PASS"), ("FAIL", True, "FAIL"), ("NOT_MEASURED", True, "NOT_MEASURED"), ("PASS", False, "NOT_MEASURED")])
def test_actual_a12_consumer_requires_drc_lvs_and_erc(tmp_path, monkeypatch, erc_status, pv_ok, expected):
    import analog_a6_native_pv as pv
    import analog_native_physical as physical
    import analog_pdk_availability as availability
    bdir = tmp_path / "phase3/analog/unit"; bdir.mkdir(parents=True)
    (bdir / "unit.gds").write_bytes(b"layout")
    monkeypatch.setattr(availability, "resolve_pdk", lambda *a, **k: {"available": True, "lvs_deck": "/pdk/actual.lvs"})
    monkeypatch.setattr(pv, "run_block_pv", lambda *a, **k: {"ran": True, "drc": {"verdict": "PASS" if pv_ok else "deferred"}, "lvs": {"verdict": "match"}})
    def native(project, block, *, container, lvs_deck):
        assert lvs_deck == "/pdk/actual.lvs"
        return {"status": erc_status, "detail": "native result", "outputs": [], "native_inputs": {"input": "bound"}}
    monkeypatch.setattr(erc, "run", native)
    result = physical._pv(tmp_path, "unit", "native", "", "process", {"drc_engine": "native"})
    assert result["status"] == expected
    assert result["metrics"]["erc"]["status"] == erc_status
    assert result["native_inputs"] == {"input": "bound"}


@pytest.mark.parametrize("record,rc,status", [
    ({"mos_bodies": [{"metal_tied": True}]}, 0, "PASS"),
    ({"mos_bodies": [{"metal_tied": True}], "native_extraction_error": "soft-connected partial nets"}, 0, "FAIL"),
    ({"mos_bodies": [{"metal_tied": False}]}, 0, "FAIL"),
    ({"mos_bodies": []}, 0, "NOT_MEASURED"),
    ({}, 0, "NOT_MEASURED"),
    ({}, 125, "NOT_MEASURED"),
    ({}, 127, "NOT_MEASURED"),
    ({"mos_bodies": [{"metal_tied": True}]}, 1, "FAIL"),
])
def test_native_verdict_and_empty_extraction(record, rc, status):
    assert erc.grade(record, rc)[0] == status


@pytest.mark.parametrize("drift,native_rc,expected", [(False, 0, "PASS"), (True, 0, "NOT_MEASURED"), (True, 1, "FAIL")])
def test_producer_consumes_native_bulk_evidence_and_retains_failure(tmp_path, monkeypatch, drift, native_rc, expected):
    import analog_a6_native_pv as pv
    bdir = tmp_path / "phase3" / "analog" / "neutral"
    bdir.mkdir(parents=True)
    gds = bdir / "neutral.gds"; gds.write_bytes(b"original layout")
    sources = {"/pdk/main.lvs": _source()}
    monkeypatch.setattr(pv, "_docker_exec_raw", lambda *a, **k: (0, "[INFO] shell environment\nERC_SOURCE=" + json.dumps({"root": "/pdk/main.lvs", "files": sources}) + "\n", ""))
    def native(container, command, **kwargs):
        argv = shlex.split(command)
        fields = [argv[i+1] for i, a in enumerate(argv[:-1]) if a == "-rd"]
        output = Path(next(x.split("=", 1)[1] for x in fields if x.startswith("erc_json=")))
        output.write_text(json.dumps({"extracted_devices": 2, "mos_bodies": [{"metal_tied": True}]}))
        if drift: gds.write_bytes(b"changed layout")
        return native_rc, "native transcript", ""
    monkeypatch.setattr(pv, "_docker_exec", native)
    result = erc.run(tmp_path, "neutral", container="owned-container", lvs_deck="/pdk/main.lvs")
    assert result["status"] == expected
    assert result["returncode"] == native_rc
    assert Path(result["native_inputs"]["erc_deck"]["path"]).is_file()
    assert set(json.loads(Path(result["native_inputs"]["foundry_sources"]["path"]).read_text())) == set(sources)
    assert result["foundry_sources"]["foundry:/pdk/main.lvs"]["sha256"]
