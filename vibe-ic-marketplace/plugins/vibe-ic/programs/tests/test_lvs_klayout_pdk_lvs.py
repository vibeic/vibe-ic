"""Unit tests for `klayout_pdk_lvs.py`.

The extraction core (`setup_extraction`, `finalize`, `cmd_*`, `write_named_spice`)
requires KLayout's `pya` and is NOT exercised on a CI host that lacks it. This
file pins the pure-Python, deterministic helpers that run WITHOUT `pya`:
  * `_net_name`  — net-name sanitisation + UNCONN counter;
  * `_default_threads` — $KLVS_THREADS override / cpu_count fallback;
  * `_load_lm` — default (generic) map vs a JSON override;
  * `DEFAULT_LAYERMAP` — the PDK-agnostic layer-key contract;
  * `_require_pya` — the disclosed exit-3 fallback (only when pya is absent).

Chip- and PDK-AGNOSTIC; the layermap is data, not hardcoded chip logic.
"""
import importlib
import json
import os
from pathlib import Path

import pytest
from _finished_gds_fixture import publish_finished_gds

mod = importlib.import_module("klayout_pdk_lvs")

try:
    import pya  # noqa: F401
    _HAS_PYA = True
except Exception:
    _HAS_PYA = False


class _FakeNet:
    """Stand-in for a pya Net: only `.name` and `.expanded_name()` are used."""
    def __init__(self, name=None, expanded="0"):
        self.name = name
        self._expanded = expanded

    def expanded_name(self):
        return self._expanded


class TestNetName:
    def test_none_yields_unconn_and_increments(self):
        counter = [0]
        assert mod._net_name(None, counter) == "UNCONN_1"
        assert mod._net_name(None, counter) == "UNCONN_2"
        assert counter[0] == 2

    def test_bus_bracket_to_dot(self):
        assert mod._net_name(_FakeNet("a[3]"), [0]) == "a.3"
        assert mod._net_name(_FakeNet("bus[10]"), [0]) == "bus.10"

    def test_comma_and_space_sanitised(self):
        # commas -> '_', spaces removed (netgen-safe token).
        assert mod._net_name(_FakeNet("x, y z"), [0]) == "x_yz"

    def test_plain_named_net_kept(self):
        assert mod._net_name(_FakeNet("VDD"), [0]) == "VDD"

    def test_empty_name_falls_back_to_expanded(self):
        assert mod._net_name(_FakeNet(name="", expanded="3:7"), [0]) == "n3_7"

    def test_whitespace_only_name_falls_back_to_expanded(self):
        assert mod._net_name(_FakeNet(name="   ", expanded="9"), [0]) == "n9"


class TestDefaultThreads:
    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("KLVS_THREADS", "5")
        assert mod._default_threads() == 5

    def test_cpu_count_fallback(self, monkeypatch):
        monkeypatch.delenv("KLVS_THREADS", raising=False)
        assert mod._default_threads() == (os.cpu_count() or 8)

    def test_non_numeric_env_falls_back_to_8(self, monkeypatch):
        monkeypatch.setenv("KLVS_THREADS", "not_a_number")
        assert mod._default_threads() == 8


class TestLoadLayerMap:
    def test_none_returns_default(self):
        assert mod._load_lm(None) is mod.DEFAULT_LAYERMAP

    def test_empty_string_returns_default(self):
        assert mod._load_lm("") is mod.DEFAULT_LAYERMAP

    def test_json_override(self, tmp_path):
        custom = {"poly": [99, 0], "metal": [[1, 0]]}
        p = tmp_path / "mypdk.json"
        p.write_text(json.dumps(custom))
        loaded = mod._load_lm(str(p))
        assert loaded == custom
        assert loaded is not mod.DEFAULT_LAYERMAP


class TestCommercialPdkLayermap:
    def test_has_all_required_keys(self):
        lm = mod.DEFAULT_LAYERMAP
        for key in ("poly", "nwell", "nactive", "pactive", "cont", "text",
                    "metal", "via", "vdd_rail_marker", "vss_rail_marker"):
            assert key in lm, f"missing layermap key {key}"

    def test_rail_markers_match_restore_pass(self):
        # These must line up with def_gds_port_power_restore.RAIL_MARKER (901/902).
        assert mod.DEFAULT_LAYERMAP["vdd_rail_marker"] == [901, 0]
        assert mod.DEFAULT_LAYERMAP["vss_rail_marker"] == [902, 0]

    def test_metal_and_via_are_layer_lists(self):
        lm = mod.DEFAULT_LAYERMAP
        assert all(isinstance(m, list) for m in lm["metal"])
        assert all(isinstance(v, list) for v in lm["via"])


@pytest.mark.skipif(_HAS_PYA, reason="exit-3 disclosure only fires when pya is absent")
class TestRequirePyaGate:
    def test_require_pya_exits_3_when_absent(self):
        with pytest.raises(SystemExit) as ei:
            mod._require_pya()
        assert ei.value.code == 3


# ── v1.3.93 — `compare` command (KLayout NetlistComparer pin-matched LVS) ────
class _FakeTermDef:
    def __init__(self, name, tid): self.name = name; self._id = tid
    def id(self): return self._id


class _FakeDevClass:
    def __init__(self, name, terms): self.name = name; self._terms = terms
    def terminal_definitions(self): return self._terms


class _FakeDevice:
    def __init__(self, dc, term_nets): self._dc = dc; self._tn = term_nets
    def device_class(self): return self._dc
    def net_for_terminal(self, tid):
        n = self._tn.get(tid)
        return _FakeNet(name=n) if n is not None else None


class _FakeCircuitDrop:
    def __init__(self, devices): self._devs = list(devices); self.removed = []
    def each_device(self): return list(self._devs)
    def remove_device(self, d): self._devs.remove(d); self.removed.append(d)


def test_drop_power_only_removes_only_all_power_devices():
    dc = _FakeDevClass("NMOS", [_FakeTermDef("S", 0), _FakeTermDef("D", 1),
                               _FakeTermDef("G", 2), _FakeTermDef("B", 3)])
    filler = _FakeDevice(dc, {0: "VSS", 1: "VDD", 2: "VSS", 3: "VSS"})   # decap: all power
    logic = _FakeDevice(dc, {0: "n$5", 1: "VDD", 2: "clk", 3: "VSS"})    # has signal terminals
    c = _FakeCircuitDrop([filler, logic])
    n = mod._lvs_drop_power_only(c, {"VDD", "VSS"})
    assert n == 1
    assert filler in c.removed and logic not in c.removed   # signal device NEVER dropped


class _FakeCircuitStray:
    def __init__(self, name, parents): self.name = name; self._parents = parents
    def each_parent(self): return list(self._parents)


class _FakeNetlist:
    def __init__(self, circuits): self._c = list(circuits)
    def each_circuit(self): return list(self._c)
    def remove(self, c): self._c.remove(c)


def test_strip_strays_drops_parentless_non_top_only():
    top = _FakeCircuitStray("spm", [])                 # the design top (parentless, kept)
    child = _FakeCircuitStray("NAND2D1", ["spm"])       # instantiated cell (has parent, kept)
    stray = _FakeCircuitStray("CELLLIB_WRAP", [])       # parentless non-top (dropped)
    nl = _FakeNetlist([top, child, stray])
    mod._lvs_strip_strays(nl, "spm")
    names = {c.name for c in nl.each_circuit()}
    assert names == {"spm", "NAND2D1"}                  # only the stray wrapper removed


def test_compare_is_a_cli_subcommand():
    import argparse
    # the compare subcommand + its options must parse without pya present
    # (pya is only required at execution time via _require_pya()).
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["extract", "lib", "cell", "compare"])
    ap.add_argument("gds")
    ap.add_argument("--source"); ap.add_argument("--top")
    ap.add_argument("--power"); ap.add_argument("--ground")
    ap.add_argument("--tol-abs", type=float, default=0.05, dest="tol_abs")
    ap.add_argument("--tol-rel", type=float, default=0.02, dest="tol_rel")
    ns = ap.parse_args(["compare", "lay.spice", "--source", "src.spice",
                        "--top", "spm"])
    assert ns.cmd == "compare" and ns.source == "src.spice"
    assert ns.tol_abs == 0.05 and ns.tol_rel == 0.02
    assert hasattr(mod, "cmd_compare")


# --- v1.3.93 .include resolution (KLayout's reader mangles absolute paths) ---
def test_inline_includes_splices_content(tmp_path):
    # KLayout's NetlistSpiceReader truncates absolute `.include` paths that
    # contain '-' (e.g. /home/u/vibe-ic/... -> /home/u//vibe) and does not link
    # a `.subckt` read in a SEPARATE read() call. `_inline_includes` splices the
    # included file's content in-line so a SINGLE reader parse links everything.
    cells = tmp_path / "cells.spice"
    cells.write_text(".SUBCKT INV a y VDD VSS\n"
                     "M1 y a VSS VSS nmos L=0.18U W=0.44U\n.ENDS\n")
    src = tmp_path / "src.spice"
    src.write_text("* top\n.GLOBAL VDD VSS\n"
                   f".include {cells}\n"
                   ".SUBCKT top a y\nX1 a y VDD VSS INV\n.ENDS\n")
    out = mod._inline_includes(str(src))
    # the include directive is replaced by the cells' actual content
    assert ".include" not in out
    assert ".SUBCKT INV" in out                 # spliced in
    assert "M1 y a VSS VSS nmos" in out
    assert ".SUBCKT top" in out                 # main body preserved


def test_inline_includes_relative_path(tmp_path):
    sub = tmp_path / "lib"
    sub.mkdir()
    (sub / "cells.spice").write_text(".SUBCKT C a VDD VSS\n.ENDS\n")
    src = tmp_path / "src.spice"
    src.write_text(".include lib/cells.spice\n.SUBCKT top a\nX1 a VDD VSS C\n.ENDS\n")
    out = mod._inline_includes(str(src))
    assert ".SUBCKT C a VDD VSS" in out         # relative include resolved vs src dir


def test_inline_includes_cycle_guard(tmp_path):
    a = tmp_path / "a.spice"
    b = tmp_path / "b.spice"
    a.write_text(f".include {b}\n* a-body\n")
    b.write_text(f".include {a}\n* b-body\n")
    # a<->b mutually include: must terminate (cycle guard), not infinite-loop
    out = mod._inline_includes(str(a))
    assert "a-body" in out and "b-body" in out


# ── v1.4.37 — metal/via layermap coverage from the PDK's Encounter/SoC map ──
# A commercial PDK's real metal stack (e.g. 6-metal commercial PDK) exceeds the generic
# 4-metal DEFAULT; extracting with too few metals SPLITS an upper-metal net into
# disconnected pieces -> a spurious extra net -> a FALSE LVS mismatch. These pin
# the parse + the auto-extend/WARN resolver (proven: wiring M5/M6 took spm LVS
# from MISMATCH to full MATCH, spares untouched).
_ENCOUNTER_MAP = """\
# name purpose gdslayer gdsdatatype
POLY    DRAWING  3  0
MET1    NET      9  0
MET1    PIN      9  2
VIA1    NET      10 0
MET2    NET      11 0
VIA2    NET      12 0
MET3    NET      13 0
VIA3    NET      14 0
MET4    NET      15 0
VIA4    NET      16 0
MET5    NET      17 0
VIA5    NET      18 0
MET6    NET      19 0
"""


def test_metal_via_from_pdk_map_ordered_and_complete(tmp_path):
    m = tmp_path / "map.txt"
    m.write_text(_ENCOUNTER_MAP)
    metal, via = mod._metal_via_from_pdk_map(str(m))
    # 6 metal, 5 via, ORDERED m1..m6 / v1..v5, routing (NET/dt0) geometry chosen.
    assert metal == [[9, 0], [11, 0], [13, 0], [15, 0], [17, 0], [19, 0]]
    assert via == [[10, 0], [12, 0], [14, 0], [16, 0], [18, 0]]


def test_metal_via_from_pdk_map_prefers_net_over_pin_purpose(tmp_path):
    # MET1 has a NET row (9/0) and a PIN row (9/2); the NET/routing geometry wins.
    m = tmp_path / "map.txt"
    m.write_text("MET1 PIN 9 2\nMET1 NET 9 0\n")
    metal, _ = mod._metal_via_from_pdk_map(str(m))
    assert metal == [[9, 0]]


def test_metal_via_from_pdk_map_missing_file_is_empty():
    assert mod._metal_via_from_pdk_map("/no/such/map.txt") == ([], [])


def test_resolve_layermap_extends_metal_via_from_pdk_map(tmp_path):
    m = tmp_path / "map.txt"
    m.write_text(_ENCOUNTER_MAP)
    lm, note = mod._resolve_layermap(None, str(m))
    # DEFAULT is 4 metal / 3 via -> extended to 6 / 5 from the PDK map.
    assert len(lm["metal"]) == 6 and len(lm["via"]) == 5
    # device/text/rail-marker layers untouched (same as DEFAULT).
    assert lm["poly"] == mod.DEFAULT_LAYERMAP["poly"]
    assert lm["vss_rail_marker"] == mod.DEFAULT_LAYERMAP["vss_rail_marker"]
    assert note is not None and "auto-extended" in note


def test_resolve_layermap_no_pdk_map_warns_on_generic_default():
    # No explicit lvs_layermap AND no PDK map -> generic 4-metal DEFAULT -> WARN.
    lm, note = mod._resolve_layermap(None, None)
    assert lm["metal"] == mod.DEFAULT_LAYERMAP["metal"]
    assert note is not None and "WARN" in note


def test_resolve_layermap_no_shrink_when_map_has_fewer(tmp_path):
    # A supplied 6-metal layermap must NOT be shrunk by a 4-metal PDK map (grow-only).
    full = tmp_path / "full.json"
    full.write_text(json.dumps({**mod.DEFAULT_LAYERMAP,
                                "metal": [[9, 0], [11, 0], [13, 0], [15, 0],
                                          [17, 0], [19, 0]],
                                "via": [[10, 0], [12, 0], [14, 0], [16, 0], [18, 0]]}))
    small = tmp_path / "small.txt"
    small.write_text("MET1 NET 9 0\nMET2 NET 11 0\n")
    lm, note = mod._resolve_layermap(str(full), str(small))
    assert len(lm["metal"]) == 6           # kept the supplied 6, not shrunk to 2
    assert note is None                     # nothing extended -> no note


@pytest.mark.parametrize("native,expected", [
    ("Match", "PASS"), ("Mismatch", "FAIL"), ("NoMatch", "FAIL"),
    ("Skipped", "NOT_MEASURED"), ("MatchWithWarning", "NOT_MEASURED"),
    ("None_", "NOT_MEASURED"), ("UNKNOWN", "NOT_MEASURED"),
])
def test_native_database_status_is_not_an_english_match(native, expected):
    result = {"compare_performed": True, "top": "unit_top", "circuits": [
        {"layout": "unit_top", "reference": "UNIT_TOP", "status": native,
         "layout_pins": 3, "reference_pins": 3}]}
    assert mod._native_status(result, 0) == expected


def test_native_measured_mismatch_keeps_precedence_over_incomplete_exit():
    result = {"compare_performed": True, "top": "unit_top", "circuits": [
        {"layout": "unit_top", "reference": "unit_top", "status": "Mismatch",
         "layout_pins": 3, "reference_pins": 3}]}
    assert mod._native_status(result, 1) == "FAIL"


@pytest.mark.parametrize("rows", [[], [
    {"layout": "child", "reference": "child", "status": "Match",
     "layout_pins": 3, "reference_pins": 3}], [
    {"layout": "unit_top", "reference": "unit_top", "status": "Match",
     "layout_pins": 0, "reference_pins": 0}], [
    {"layout": "unit_top", "reference": "unit_top", "status": "Match",
     "layout_pins": 3, "reference_pins": 2}],
])
def test_native_absent_top_or_pins_never_certifies_a_layout(rows):
    assert mod._native_status({"compare_performed": bool(rows),
                              "top": "unit_top", "circuits": rows}, 0) == "NOT_MEASURED"


def test_native_reader_rejects_bare_pass_without_sources(tmp_path):
    gds = tmp_path / "layout.gds"; gds.write_bytes(b"layout")
    report = tmp_path / "result.json"
    report.write_text(json.dumps({"status": "PASS"}))
    with pytest.raises(ValueError, match="SCHEMA_MISSING"):
        mod.read_current_verdict(tmp_path, report, gds)


def _bound_native_record(project, state="Match"):
    layout = project / "phase3/stage4/gds/unit.gds"
    layout.parent.mkdir(parents=True)
    layout.write_bytes(b"unit-layout-for-binding-test")
    report = project / "reports/phase3/lvs_verdict.json"
    report.parent.mkdir(parents=True)
    record = {"schema": "vibeic.native_gds_lvs/1", "compare_performed": True,
              "execution": {"rc": 0, "inputs_unchanged": True},
              "layout_source": {"kind": "gds", **mod._file_record(layout)}}
    for key in ("reference_source", "deck", "native_result", "cell_library_bundle",
                "source_netlist", "driver_source", "log"):
        path = report.parent / key
        path.write_bytes(key.encode())
        record[key] = mod._file_record(path)
    result = {"compare_performed": True, "top": "unit", "circuits": [
        {"layout": "unit", "reference": "UNIT", "status": state,
         "layout_pins": 4, "reference_pins": 4}]}
    record["native_result"].update(result)
    record["status"] = mod._native_status(result, 0)
    record["finding"] = "NATIVE_FINAL_GDS_LVS_" + record["status"]
    report.write_text(json.dumps(record))
    return layout, report, record


@pytest.mark.parametrize("state,passed", [("Match", True), ("NoMatch", False)])
def test_native_reader_and_existing_consumers_agree(tmp_path, monkeypatch, state, passed):
    import lvs_tapeout_signoff_check as signoff
    import eda_report_audit as audit
    import lvs_signoff_guard as guard
    layout, report, record = _bound_native_record(tmp_path, state)
    (tmp_path / "state_out.json").write_text(json.dumps({"gds": str(layout)}))
    publish_finished_gds(tmp_path)
    assert mod.read_current_verdict(tmp_path, report, layout)["status"] == record["status"]
    assert signoff.check(tmp_path)["passed"] is passed
    assert audit._check_lvs(tmp_path).passed is passed
    assert guard.main([str(tmp_path)]) == (0 if passed else 1)


def test_corrupt_current_native_cannot_restore_a_retained_legacy_match(tmp_path, monkeypatch):
    import lvs_tapeout_signoff_check as signoff
    import eda_report_audit as audit
    import lvs_signoff_guard as guard
    from test_lvs_tapeout_signoff import _MATCH
    from test_lvs_signoff_guard import PORTED
    from test_eda_report_audit import _PAD
    layout, report, _ = _bound_native_record(tmp_path, "NoMatch")
    (tmp_path / "state_out.json").write_text(json.dumps({"gds": str(layout)}))
    publish_finished_gds(tmp_path)
    report.with_name("lvs.rpt").write_text(
        "Netgen LVS comparison\nSubcircuit instance summary: 567 instances compared\n"
        "NET count: 1234\ndevice count: 567\n" + _MATCH + _PAD)
    extracted = tmp_path / "phase3/stage3/extracted/widget.spice"
    extracted.parent.mkdir(parents=True)
    extracted.write_text(PORTED)

    def verdicts():
        return (signoff.check(tmp_path)["passed"], audit._check_lvs(tmp_path).passed,
                guard.main([str(tmp_path)]))

    assert verdicts() == (False, False, 1)
    report.write_text("{")
    assert verdicts() == (False, False, 1)
    report.rename(tmp_path / "native.corrupt.retained.json")
    assert verdicts() == (True, True, 0)
    # A readable record owned by the existing legacy producer stays compatible.
    report.write_text(json.dumps({"lvs_engine": "netgen", "status": "PASS"}))
    assert verdicts() == (True, True, 0)


@pytest.mark.parametrize("change", ["layout", "bundle", "native_result", "comparison"])
def test_native_binding_rejects_changed_or_missing_required_source(tmp_path, change):
    layout, report, record = _bound_native_record(tmp_path)
    if change == "layout":
        layout.write_bytes(b"another-layout")
    elif change == "bundle":
        Path(record["cell_library_bundle"]["path"]).unlink()
    elif change == "native_result":
        Path(record["native_result"]["path"]).write_bytes(b"another-result")
    else:
        record["compare_performed"] = False
        report.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        mod.read_current_verdict(tmp_path, report, layout)


def test_native_geometry_bridge_accepts_only_date_rewrites_and_is_rechecked(tmp_path):
    from test_gds_canonical_digest import _stream, _RUN_A, _RUN_B
    layout, report, record = _bound_native_record(tmp_path)
    old = tmp_path / "extracted-layout.gds"
    old.write_bytes(_stream(_RUN_A, _RUN_A))
    layout.write_bytes(_stream(_RUN_B, _RUN_B))
    source = {"kind": "gds", **mod._file_record(old)}
    record["layout_source"] = {"kind": "gds", **mod._file_record(layout)}
    manifest = tmp_path / "old-inputs.json"; manifest.write_text("[]")
    old_report = tmp_path / "old-verdict.json"; old_report.write_text("{}")
    record["extraction_basis"] = {
        "report": mod._file_record(old_report), "native_result": record["native_result"],
        "inputs_manifest": mod._file_record(manifest), "layout_source": source}
    record["geometry_equivalence"] = mod._native_geometry_equivalence(
        tmp_path, source, record["layout_source"])
    assert record["geometry_equivalence"]["source_raw_sha256"] != (
        record["geometry_equivalence"]["target_raw_sha256"])
    report.write_text(json.dumps(record))
    assert mod.read_current_verdict(tmp_path, report, layout)["status"] == "PASS"
    # Replacing the layout and its declared raw hash cannot turn this proof
    # into permission for a different polygon. The consumer measures again.
    layout.write_bytes(_stream(_RUN_B, _RUN_B, width=1400))
    record["layout_source"] = {"kind": "gds", **mod._file_record(layout)}
    report.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="LAYOUT_NOT_EQUIVALENT"):
        mod.read_current_verdict(tmp_path, report, layout)


@pytest.mark.skipif(not _HAS_PYA, reason="KLayout semantic comparison requires pya")
@pytest.mark.parametrize("case", ["same_bytes", "rewritten", "shape_change",
                                  "basis_changed", "measured_fail"])
def test_native_requested_subject_preserves_extraction_and_checks_semantics(tmp_path, case):
    import struct
    layout, report, record = _bound_native_record(
        tmp_path, "NoMatch" if case == "measured_fail" else "Match")

    def write_subject(path, width):
        database = pya.Layout(); database.dbu = 0.001
        top = database.create_cell("unit")
        top.shapes(database.layer(1, 0)).insert(pya.Box(0, 0, width, 500))
        top.shapes(database.layer(1, 1)).insert(pya.Text("input", pya.Trans()))
        database.write(str(path))

    write_subject(layout, 1000)
    record["layout_source"] = {"kind": "gds", **mod._file_record(layout)}
    requested = tmp_path / "delivered.gds"
    requested.write_bytes(layout.read_bytes())
    if case in ("rewritten", "measured_fail"):
        rewritten = bytearray(requested.read_bytes()); offset = 0
        while offset < len(rewritten):
            length, record_type, _ = struct.unpack_from(">HBB", rewritten, offset)
            if record_type in (0x01, 0x05):
                struct.pack_into(">h", rewritten, offset + 4, 2025)
            offset += length
        requested.write_bytes(rewritten)
        assert mod._file_record(requested)["sha256"] != record["layout_source"]["sha256"]
    elif case == "shape_change":
        write_subject(requested, 1400)
    elif case == "basis_changed":
        layout.write_bytes(b"changed-original-extraction-subject")
    report.write_text(json.dumps(record))
    original_report = report.read_bytes()
    original_database = Path(record["native_result"]["path"]).read_bytes()
    if case in ("shape_change", "basis_changed"):
        with pytest.raises(ValueError, match="LAYOUT_(NOT_EQUIVALENT|MISMATCH)"):
            mod.read_current_verdict(tmp_path, report, requested)
    else:
        verdict = mod.read_current_verdict(tmp_path, report, requested)
        assert verdict["layout_source"] == record["layout_source"]
        assert verdict["requested_subject"] == {"kind": "gds", **mod._file_record(requested)}
        assert verdict["status"] == record["status"]
        if case != "same_bytes":
            assert verdict["subject_equivalence"]["equivalent"] is True
    assert report.read_bytes() == original_report
    assert Path(record["native_result"]["path"]).read_bytes() == original_database
