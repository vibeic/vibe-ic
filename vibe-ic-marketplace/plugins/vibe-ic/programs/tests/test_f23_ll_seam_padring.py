"""F23 -- the LibreLane 15..18 seam: the pad ring and the pad-control ties.

With steps 15, 15.5ic and 17 on LibreLane (T97) the routing session loads the
tool's placed DEF (`librelane_contract.placement_consumer_tcl`), and the
combined chain LL15 -> LL17+18 -> LL19/20 -> direct tail ended rc=1 on two
defects, both measured on spm x gf180mcuD (vibeic-eda 0.3.79):

1. `pad_ring_route_evidence` -> PADRING_CONSUMER_MISSING. The gate looked for
   the direct deck's `read_def -floorplan_initialize` marker, which the seam
   removes, although the ring IS in the consumed DEF (731/731 ring instances
   unmoved, 148/148 ring pins connected, 36/36 port-to-pad connections).
   The gate now judges that evidence on the LibreLane path.
2. post-layout LEC: `u_pad_clk/PD` on a net named `net` from placed.def on.
   LibreLane's RepairDesignPostGPL runs `repair_tie_fanout`, which replaced all
   76 declared `_vibeic_aux_tie_*` ties. The contract now declares them in
   RSZ_DONT_TOUCH_LIST (measured: the same call then inserts 0 ties).
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import librelane_contract as contract  # noqa: E402
import phase3_one_shot_runner as p3  # noqa: E402


def put(path: Path, obj) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))
    return path


# --------------------------------------------------------------------------
# defect 2: the declared pad-control ties survive LibreLane's repair_tie_fanout
# --------------------------------------------------------------------------

def _design(tmp_path: Path, chip_top_record: dict | None) -> Path:
    p = tmp_path / "design"
    put(p / "phase1/generated_docs/L8_TIMING_WAVEFORM.json", {
        "clock_domains": [{"role": "primary", "pdk_scoped_target": "processA",
                           "period_ns": 12, "source_pin": "clk"}]})
    put(p / "phase1/generated_docs/L9_INTEGRATION_SPEC.json", {"top_module": "block"})
    put(p / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json", {"fields": {}})
    put(p / "input/submission_template/tapeout_declaration.json", {"answers": {
        "top_cell": "chip_top", "die_area_um": [0, 0, 100, 100],
        "core_area_um": [10, 10, 90, 90]}})
    if chip_top_record is not None:
        put(p / "reports/phase3/io_pad_chip_top.json", chip_top_record)
    return p


_AUX = [
    {"instance": "u_pad_a", "pin": "PD", "net": "_aux_tie_0",
     "tie_instance": "_aux_tie_cell_0", "tie_master": "TIELO", "tie_pin": "ZN"},
    {"instance": "u_pad_a", "pin": "PU", "net": "_aux_tie_1",
     "tie_instance": "_aux_tie_cell_1", "tie_master": "TIELO", "tie_pin": "ZN"},
]


def test_declared_pad_control_ties_reach_rsz_dont_touch_list(tmp_path):
    p = _design(tmp_path, {"verdict": "WROTE", "aux_pin_signal_connections": _AUX})
    out = p / "phase3/librelane/config.json"
    result = contract.emit_config(p, "processA", out)
    assert result["RSZ_DONT_TOUCH_LIST"] == [
        "_aux_tie_cell_0", "_aux_tie_0", "_aux_tie_cell_1", "_aux_tie_1"]
    written = json.loads(out.read_text())
    assert written["RSZ_DONT_TOUCH_LIST"] == result["RSZ_DONT_TOUCH_LIST"]
    provenance = json.loads(out.with_suffix(".provenance.json").read_text())
    assert "io_pad_chip_top.json.aux_pin_signal_connections" in provenance[
        "RSZ_DONT_TOUCH_LIST"]


@pytest.mark.parametrize("record", [None, {"verdict": "WROTE"},
                                    {"aux_pin_signal_connections": []}])
def test_no_declared_tie_means_no_dont_touch_list(tmp_path, record):
    p = _design(tmp_path, record)
    result = contract.emit_config(p, "processA", p / "phase3/librelane/config.json")
    assert "RSZ_DONT_TOUCH_LIST" not in result


def test_pad_local_tie_protects_its_net_without_freezing_the_entire_pad(tmp_path):
    rows = _AUX + [{"instance": "u_pad_q", "pin": "ENABLE_H",
                    "net": "_local_tie_hi", "tie_instance": "u_pad_q",
                    "tie_master": "GPIO", "tie_pin": "TIE_HI_ESD"}]
    p = _design(tmp_path, {"verdict": "WROTE", "aux_pin_signal_connections": rows})
    result = contract.emit_config(p, "processA", p / "phase3/librelane/config.json")
    protected = result["RSZ_DONT_TOUCH_LIST"]
    assert "_local_tie_hi" in protected
    assert "u_pad_q" not in protected
    assert all(row[key] in protected for row in _AUX
               for key in ("tie_instance", "net"))


@pytest.mark.parametrize("rows", [
    "not-a-list",
    [{"instance": "u_pad_a", "pin": "PD", "net": "_aux_tie_0"}],
    [{"instance": "u_pad_a", "pin": "PD", "net": "", "tie_instance": "t"}],
], ids=["not-a-list", "no-tie-instance", "empty-net"])
def test_an_unreadable_tie_record_is_refused_not_skipped(tmp_path, rows):
    p = _design(tmp_path, {"aux_pin_signal_connections": rows})
    with pytest.raises(contract.Refusal) as exc:
        contract.emit_config(p, "processA", p / "phase3/librelane/config.json")
    assert exc.value.code == "LL_AUX_TIE_RECORD_INVALID"


# --------------------------------------------------------------------------
# defect 1: the pad-ring gate judges the ring in the DEF the route consumed
# --------------------------------------------------------------------------

_RING = "IO_PAD_A"
_CORNER = "IO_CORNER"
_CELL = "STD_CELL_A"


def _def(*, pad_xy=(0, 50000), pad_net="clk", core_net="clk__core",
         pd_net="_aux_tie_0", pad_driver="( PIN clk )", extra_nets=()) -> str:
    """A chip-top DEF shaped as OpenROAD writes it after LibreLane's PadRing:
    the port-to-pad net in SPECIALNETS, the core-side and tie nets in NETS."""
    nets = [f"- {core_net} ( u_pad_clk Y ) ( u_core/_1_ CLK ) + USE SIGNAL ;",
            f"- {pd_net} ( u_pad_clk PD ) ( _aux_tie_cell_0 ZN ) + USE SIGNAL ;",
            *extra_nets]
    special = [f"- {pad_net} {pad_driver} ( u_pad_clk PAD ) + USE SIGNAL ;",
               "- VDD ( PIN VDD ) ( * VDD ) + USE POWER ;"]
    return (
        "VERSION 5.8 ;\nDESIGN chip_top ;\nUNITS DISTANCE MICRONS 1000 ;\n"
        "DIEAREA ( 0 0 ) ( 100000 100000 ) ;\n"
        "COMPONENTS 4 ;\n"
        f"- u_pad_clk {_RING} + FIXED ( {pad_xy[0]} {pad_xy[1]} ) W ;\n"
        f"- u_corner_sw {_CORNER} + FIXED ( 0 0 ) N ;\n"
        f"- _aux_tie_cell_0 {_CELL} + PLACED ( 20000 20000 ) N ;\n"
        f"- u_core/_1_ {_CELL} + PLACED ( 30000 30000 ) N ;\n"
        "END COMPONENTS\n"
        "PINS 2 ;\n- clk + NET clk + DIRECTION INPUT + USE SIGNAL ;\n"
        "- VDD + NET VDD + SPECIAL + DIRECTION INOUT + USE POWER ;\nEND PINS\n"
        f"SPECIALNETS {len(special)} ;\n" + "\n".join(special) + "\nEND SPECIALNETS\n"
        f"NETS {len(nets)} ;\n" + "\n".join(nets) + "\nEND NETS\n"
        "END DESIGN\n")


def _rec(rtype: int, dtype: int, payload: bytes = b"") -> bytes:
    return struct.pack(">HBB", len(payload) + 4, rtype, dtype) + payload


def _name(s: str) -> bytes:
    b = s.encode("ascii")
    return b + (b"\x00" if len(b) % 2 else b"")


def _gds(top: str, refs) -> bytes:
    """A hierarchical GDS whose top references each ring master once."""
    out = [_rec(0x00, 0x02, struct.pack(">h", 600)), _rec(0x01, 0x02, b"\x00" * 24),
           _rec(0x02, 0x06, _name("LIB")), _rec(0x03, 0x05, b"\x00" * 16)]
    for sname in refs:
        out += [_rec(0x05, 0x02, b"\x00" * 24), _rec(0x06, 0x06, _name(sname)),
                _rec(0x07, 0x00)]
    out += [_rec(0x05, 0x02, b"\x00" * 24), _rec(0x06, 0x06, _name(top))]
    for target in refs:
        out += [_rec(0x0A, 0x00), _rec(0x12, 0x06, _name(target)),
                _rec(0x10, 0x03, struct.pack(">2i", 0, 0)), _rec(0x11, 0x00)]
    out += [_rec(0x07, 0x00), _rec(0x04, 0x00)]
    return b"".join(out)


#: A direct deck in the shape `placement_consumer_tcl` transforms (the load,
#: the resume sentinel, the region up to CTS, and the route after it).
_DIRECT_DECK = """read_lef tech.lef
read_verilog chip_top_io.v
link_design chip_top
# <<<PNR_RESUME_ELIDE_BEGIN>>>
puts "PNR_STAGE: padring_ingest"
read_def -floorplan_initialize {floorplan}
puts "PADRING_ROUTING_CONSUMED: {floorplan}"
global_placement -density 0.3
detailed_placement
puts "PNR_STAGE: cts"
clock_tree_synthesis
if {{[catch {{detailed_route -output_drc x.rpt}} dr_err]}} {{ puts $dr_err }}
"""


def _receipt(path: Path, dest: Path) -> None:
    put(path, {"views": {"def": {"dest": str(dest),
                                 "dest_sha256": hashlib.sha256(
                                     dest.read_bytes()).hexdigest()}}})


def _ll_project(tmp_path: Path, *, placed_def: str | None = None,
                deck: str | None = None, log: str | None = None,
                ring_receipt: bool = True) -> Path:
    project = tmp_path / "proj"
    pnr = p3._pl.pnr_dir(project)
    pnr.mkdir(parents=True)
    ref = _def()
    (pnr / "padring.def").write_text(ref)
    (pnr / "placed.def").write_text(ref if placed_def is None else placed_def)
    for name in ("routed.def", "spm.def"):
        (pnr / name).write_text(ref)
    if deck is None:
        deck = contract.placement_consumer_tcl(
            _DIRECT_DECK.format(floorplan=str(pnr / "floorplan.def")),
            str(pnr / "placed.def"), p3._PNR_STAGE_MARKER)
    (pnr / "pnr.tcl").write_text(deck)
    (pnr / "openroad.log").write_text(
        f"LIBRELANE_PLACEMENT_CONSUMED: {pnr / 'placed.def'}\n" if log is None else log)
    (pnr / "spm.gds").write_bytes(_gds("chip_top", [_RING, _CORNER]))
    reports = project / "reports" / "phase3"
    put(reports / "padring.json", {"producer": {
        "pads": [{"instance": "u_pad_clk", "master": _RING}],
        "corners": [{"instance": "u_corner_sw", "master": _CORNER}], "fillers": []}})
    _receipt(reports / "librelane_placement_handoff.json", pnr / "placed.def")
    if ring_receipt:
        _receipt(reports / "librelane_padring_handoff.json", pnr / "padring.def")
    return project


def _run(project: Path):
    gds = p3._pl.pnr_dir(project) / "spm.gds"
    res = p3.step_pad_ring_final_evidence(
        project, "spm", p3.StepResult("gds", "PASS", 0.0, "fixture", [str(gds)],
                                      extras={"streamout_engine": "fixture"}))
    doc = json.loads((project / "reports/phase3/pad_ring_route_evidence.json").read_text())
    return res, doc


def test_the_ring_in_librelanes_placed_def_is_the_routing_consumers_ring(tmp_path):
    """The real seam deck + the tool's DEF carrying the ring: PASS, and the
    evidence names what was judged."""
    res, doc = _run(_ll_project(tmp_path))
    assert doc["findings"] == [], doc["findings"]
    assert res.status == "PASS"
    ev = doc["librelane_ring_evidence"]
    assert ev["consumed_def"].endswith("phase3/stage3/pnr/placed.def")
    assert (ev["ring_instances"], ev["ring_instances_unmoved"]) == (2, 2)
    assert (ev["ring_pins_connected_reference"], ev["ring_pins_connected_consumed"]) == (3, 3)
    assert (ev["ring_port_connections"], ev["ring_port_connections_lost"]) == (1, 0)
    assert "LibreLane" in doc["routing_consumer"]


def test_a_core_side_net_renamed_by_buffering_is_not_a_lost_ring(tmp_path):
    """The resizer may move a pad's core-side pin onto a new buffered net
    (measured: `u_pad_p/A` p__core -> net29). That is LEC's question."""
    placed = _def(core_net="net29")
    res, doc = _run(_ll_project(tmp_path, placed_def=placed))
    assert doc["findings"] == [] and res.status == "PASS"


@pytest.mark.parametrize("placed, code", [
    (_def(pad_xy=(0, 60000)), "PADRING_LL_RING_MOVED"),
    (_def(pad_net="clk_buf", pad_driver="( ibuf Z )", extra_nets=(
        "- clk ( PIN clk ) ( ibuf I ) + USE SIGNAL ;",)), "PADRING_LL_PORT_CONNECTION_LOST"),
    (_def().replace("( u_pad_clk PD ) ", ""), "PADRING_LL_RING_PIN_DISCONNECTED"),
    (_def().replace(f"- u_pad_clk {_RING}", "- u_pad_clk OTHER_MASTER"),
     "PADRING_LL_RING_MOVED"),
], ids=["pad-moved", "port-behind-a-buffer", "pin-disconnected", "master-swapped"])
def test_a_ring_the_consumed_def_does_not_carry_fails(tmp_path, placed, code):
    res, doc = _run(_ll_project(tmp_path, placed_def=placed))
    assert res.status == "FAIL"
    assert any(f.startswith(code) for f in doc["findings"]), doc["findings"]


def test_a_placed_def_the_handoff_did_not_bind_fails(tmp_path):
    project = _ll_project(tmp_path)
    placed = p3._pl.pnr_dir(project) / "placed.def"
    placed.write_text(placed.read_text() + "\n")
    res, doc = _run(project)
    assert res.status == "FAIL"
    assert any(f.startswith("PADRING_LL_PLACEMENT_UNBOUND") for f in doc["findings"])


def test_an_absent_placement_receipt_fails(tmp_path):
    project = _ll_project(tmp_path)
    (project / "reports/phase3/librelane_placement_handoff.json").unlink()
    res, doc = _run(project)
    assert res.status == "FAIL"
    assert any(f.startswith("PADRING_LL_PLACEMENT_UNBOUND") for f in doc["findings"])


def test_a_ring_reference_the_padring_receipt_did_not_bind_fails(tmp_path):
    project = _ll_project(tmp_path)
    put(project / "reports/phase3/librelane_padring_handoff.json",
        {"views": {"def": {"dest": "x/padring.def", "dest_sha256": "0" * 64}}})
    res, doc = _run(project)
    assert res.status == "FAIL"
    assert any(f.startswith("PADRING_LL_RING_UNBOUND") for f in doc["findings"])


def test_no_route_after_the_ingest_is_a_missing_consumer(tmp_path):
    pnr = "phase3/stage3/pnr"
    deck = contract.placement_consumer_tcl(
        _DIRECT_DECK.split("if {{[catch")[0].format(floorplan="f.def"),
        f"/x/{pnr}/placed.def", p3._PNR_STAGE_MARKER)
    res, doc = _run(_ll_project(tmp_path, deck=deck))
    assert res.status == "FAIL"
    assert any("no live detailed_route" in f for f in doc["findings"]), doc["findings"]


def test_a_marker_without_the_read_def_is_a_missing_consumer(tmp_path):
    deck = ('puts "LIBRELANE_PLACEMENT_CONSUMED: /x/placed.def"\n'
            "detailed_route\n")
    res, doc = _run(_ll_project(tmp_path, deck=deck))
    assert res.status == "FAIL"
    assert any("no read_def of placed.def" in f for f in doc["findings"])


def test_the_ingest_must_be_observed_in_the_live_log(tmp_path):
    res, doc = _run(_ll_project(tmp_path, log="nothing here\n"))
    assert res.status == "FAIL"
    assert "PADRING_CONSUMER_NOT_OBSERVED_IN_LIVE_LOG" in doc["findings"]


def test_a_deck_with_neither_ingest_still_fails(tmp_path):
    res, doc = _run(_ll_project(tmp_path, deck="detailed_route\n"))
    assert res.status == "FAIL"
    assert any(f.startswith("PADRING_CONSUMER_MISSING") for f in doc["findings"])
    assert doc["librelane_ring_evidence"] is None


def test_def_net_members_reads_port_nets_from_specialnets():
    members = p3._def_net_members(_def())
    assert members["clk"] == [("PIN", "clk"), ("u_pad_clk", "PAD")]
    assert members["VDD"] == [("PIN", "VDD")]
    assert ("u_pad_clk", "PD") in members["_aux_tie_0"]


def _native_default_ring_project(tmp_path):
    """Neutral retained native packets; no OpenROAD or geometry execution."""
    import _default_backend_fixtures as fixtures
    project = _ll_project(tmp_path)
    pnr = p3._pl.pnr_dir(project)
    for name in ('pnr.tcl', 'openroad.log'):
        (pnr / name).unlink()
    (pnr / 'floorplan.def').write_text(_def())
    reports = project / 'reports/phase3'

    def stage(step, previous, lane):
        folder = project / 'phase3/librelane' / lane
        folder.mkdir(parents=True, exist_ok=True)
        output = folder / 'native.def'
        output.write_text(_def())
        before = json.loads(previous.read_text()) if previous is not None else {'metrics': {}}
        after = {'def': str(output), 'metrics': {}}
        if step == 'OpenROAD.DetailedRouting':
            # Match the real producer contract: the canonical DRC report is
            # named from the routed ODB subject and is bound into the native
            # receipt. An empty report is the valid zero-violation result.
            odb = folder / 'native.odb'
            odb.write_text('SOURCE_FIXTURE: routed ODB subject\n')
            (folder / 'native.drc').write_text('')
            after['odb'] = str(odb)
        folder, _ = fixtures.producer(project, step, before,
            after, lane=lane)
        if previous is not None:
            fp = json.loads((folder / 'input_fingerprint.json').read_text())
            fp['state'] = contract.digest(previous)
            put(folder / 'input_fingerprint.json', fp)
            receipt = json.loads((folder / 'vibeic_receipt.json').read_text())
            receipt['input'] = fp
            receipt['sha256']['input_fingerprint.json'] = contract.digest(
                folder / 'input_fingerprint.json')
            put(folder / 'vibeic_receipt.json', receipt)
        return folder / 'state_out.json'

    ring = stage('OpenROAD.PadRing', None, '15-floorplan/01-openroad-padring')
    contract.handoff_to_direct(ring, {'def': pnr / 'padring.def'},
                               reports / 'librelane_padring_handoff.json')
    initial = put(project / 'phase3/librelane/placement-input.json',
                  {'def': str(pnr / 'floorplan.def'), 'metrics': {}})
    route = None
    for sid, ids, handoff_name, target in (
            ('17', ('OpenROAD.GlobalPlacement', 'OpenROAD.DetailedPlacement'),
             'librelane_placement_handoff.json', 'placed.def'),
            ('21', ('OpenROAD.GlobalRouting', 'OpenROAD.DetailedRouting'),
             'execution-backend-execution-backend-21-handoff.json', 'routed.def')):
        previous = initial
        states = []
        for index, step in enumerate(ids, 1):
            previous = stage(step, previous, f'execution-backend-{sid}/{index:02d}-native')
            states.append({'step': step, 'state': str(previous),
                           'sha256': contract.digest(previous)})
            if step == 'OpenROAD.DetailedRouting':
                route = previous.parent
        put(reports / f'execution-backend-{sid}.json', {
            'ordered_steps': list(ids), 'initial_state': str(initial),
            'initial_sha256': contract.digest(initial), 'states': states})
        contract.handoff_to_direct(previous, {'def': pnr / target}, reports / handoff_name)
        initial = previous
    switch = json.loads((project / 'phase3/librelane_switch.json').read_text())
    switch['steps'] = {'17': 'librelane', '21': 'librelane'}
    put(project / 'phase3/librelane_switch.json', switch)
    return project, route


@pytest.mark.parametrize('change,code', [
    ('current', None),
    ('moved', 'PADRING_LL_RING_MOVED'),
    ('pin-disconnected', 'PADRING_LL_RING_PIN_DISCONNECTED'),
    ('port-lost', 'PADRING_LL_PORT_CONNECTION_LOST'),
    ('receipt-changed', 'PADRING_LL_NATIVE_CONSUMER_UNBOUND'),
    ('broken-chain', 'PADRING_LL_NATIVE_CONSUMER_UNBOUND'),
])
def test_default_ring_reader_uses_native_placement_and_route_consumers(tmp_path, change, code):
    """True final caller/receipt/DEF proof, with neutral native process records."""
    project, route = _native_default_ring_project(tmp_path)
    result, doc = _run(project)
    assert result.status == 'PASS', doc['findings']
    assert doc['findings'] == []
    assert doc['librelane_ring_evidence']['mode'] == 'librelane_native_chain'
    assert len(doc['librelane_ring_evidence']['consumed_defs']) == 3
    if change == 'current':
        return
    if change == 'receipt-changed':
        (route / 'invocation.log').write_text('changed native execution record\n')
    else:
        receipt = json.loads((route / 'vibeic_receipt.json').read_text())
        fp = receipt['input']
        if change == 'broken-chain':
            fp['state'] = '0' * 64
        else:
            before = json.loads((route / 'state_in.json').read_text())
            definition = Path(before['def'])
            text = (_def(pad_xy=(0, 60000)) if change == 'moved' else
                    _def().replace('( u_pad_clk PD ) ', '') if change == 'pin-disconnected' else
                    _def(pad_net='clk_buf', pad_driver='( ibuf Z )', extra_nets=(
                        '- clk ( PIN clk ) ( ibuf I ) + USE SIGNAL ;',)))
            definition.write_text(text)
            producer = definition.parent
            previous_receipt = json.loads((producer / 'vibeic_receipt.json').read_text())
            previous_receipt['sha256'][definition.name] = contract.digest(definition)
            put(producer / 'vibeic_receipt.json', previous_receipt)
            fp['state_files'][str(definition)] = contract.digest(definition)
        put(route / 'input_fingerprint.json', fp)
        receipt['input'] = fp
        receipt['sha256']['input_fingerprint.json'] = contract.digest(route / 'input_fingerprint.json')
        put(route / 'vibeic_receipt.json', receipt)
    result, doc = _run(project)
    assert result.status == 'FAIL'
    assert any(f.startswith(code) for f in doc['findings']), doc['findings']


@pytest.mark.parametrize('change', [
    'current', 'two-candidates', 'wrong-predecessor', 'wrong-adopted',
    'unpromoted', 'failed-repair', 'source-changed', 'output-changed',
    'moved', 'pin-disconnected', 'port-lost',
])
def test_default_ring_follows_only_bound_adopted_postroute_views(tmp_path, change):
    """A genuine native repair may supersede the route packet, never bypass it."""
    import _default_backend_fixtures as fixtures
    import librelane_postroute_repair as repair
    project, route = _native_default_ring_project(tmp_path)
    pnr = p3._pl.pnr_dir(project)
    reports = project / 'reports/phase3'
    initial = put(project / 'phase3/librelane/32-config/bridge/state_in.json',
                  {'def': str(pnr / 'routed.def'), 'metrics': {}})
    state = initial
    candidates = []
    for index in range(2 if change == 'two-candidates' else 1):
        name = f'32-cand{index + 1:02d}'
        folder = project / 'phase3/librelane' / name / '01-native-repair'
        folder.mkdir(parents=True)
        output = folder / 'native.def'
        text = (_def(pad_xy=(0, 60000)) if change == 'moved' else
                _def().replace('( u_pad_clk PD ) ', '') if change == 'pin-disconnected' else
                _def(pad_net='clk_buf', pad_driver='( ibuf Z )', extra_nets=(
                    '- clk ( PIN clk ) ( ibuf I ) + USE SIGNAL ;',)) if change == 'port-lost' else
                _def(core_net=f'repaired_net_{index}'))
        output.write_text(text)
        before = json.loads(state.read_text())
        folder, _ = fixtures.producer(project, repair.REPAIR_STEP, before,
            {'def': str(output), 'metrics': {}}, lane=str(folder.relative_to(
                project / 'phase3/librelane')))
        fp = json.loads((folder / 'input_fingerprint.json').read_text())
        fp['state'] = contract.digest(state)
        if change == 'wrong-predecessor':
            fp['state_files'][before['def']] = '0' * 64
        put(folder / 'input_fingerprint.json', fp)
        receipt = json.loads((folder / 'vibeic_receipt.json').read_text())
        receipt['input'] = fp
        receipt['sha256']['input_fingerprint.json'] = contract.digest(folder / 'input_fingerprint.json')
        put(folder / 'vibeic_receipt.json', receipt)
        previous_name = candidates[-1]['candidate'] if candidates else None
        state = folder / 'state_out.json'
        candidates.append({'candidate': name, 'from': previous_name,
                           'repair_state': str(state), 'closure_decision': 'PROMOTED'})
    report = {'input_state': str(initial), 'adopted': name, 'adopted_state': str(state),
              'verdict': 'PASS', 'candidates': candidates}
    if change == 'wrong-adopted':
        report['adopted_state'] = str(route / 'state_out.json')
    elif change == 'unpromoted':
        candidates[-1]['closure_decision'] = 'ROLLED_BACK'
    elif change == 'failed-repair':
        report['verdict'] = 'FAIL'
    put(project / repair.REPORT_REL, report)
    contract.handoff_to_direct(state, {'def': pnr / 'routed.def'},
                               reports / 'librelane_postroute_repair_handoff.json')
    if change == 'source-changed':
        old = json.loads((reports / 'execution-backend-execution-backend-21-handoff.json').read_text())
        Path(old['views']['def']['source']).write_text('changed historical route')
    elif change == 'output-changed':
        (pnr / 'routed.def').write_text((pnr / 'routed.def').read_text() + '\n')
    result, doc = _run(project)
    expected = 'PASS' if change in ('current', 'two-candidates') else 'FAIL'
    assert result.status == expected, doc['findings']
    if expected == 'PASS':
        assert doc['findings'] == []
        assert doc['librelane_ring_evidence']['adopted_route_state'] == str(state)
    elif change in ('moved', 'pin-disconnected', 'port-lost'):
        code = {'moved': 'PADRING_LL_RING_MOVED',
                'pin-disconnected': 'PADRING_LL_RING_PIN_DISCONNECTED',
                'port-lost': 'PADRING_LL_PORT_CONNECTION_LOST'}[change]
        assert any(f.startswith(code) for f in doc['findings']), doc['findings']
    else:
        assert any(f.startswith('PADRING_LL_NATIVE_CONSUMER_UNBOUND')
                   for f in doc['findings']), doc['findings']
