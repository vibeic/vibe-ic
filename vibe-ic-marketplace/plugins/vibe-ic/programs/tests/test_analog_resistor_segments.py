import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import analog_a2_topology_emit as a2
import analog_a3_netlist_emit as a3
import analog_resistor_segments as segments
from _analog_producer_fixture import A2, A3, bdir, read_json, run_prog
from test_analog_ciff import _project
from test_declared_load_bias_branches import _emit, PDK


ROW = {"name": segments.FIELD, "target": 100.0, "unit": "um"}


STARTUP = {"startup_reset": 1, "startup_reset_tau_ns": 100, "startup_reset_cap_ff": 1000}


def _case(tmp_path, *rows, measured=None, **values):
    project = _project(tmp_path, **values)
    directory = bdir(project, "mod_alpha")
    spec = read_json(directory / "spec.json")
    spec["specs"].extend(rows)
    (directory / "spec.json").write_text(json.dumps(spec))
    if measured:
        record_path = project / "analog/_pdk_char/analog_device_params.json"
        record = read_json(record_path)
        params = record["measured"]["corners"]["typ"]["params"]
        for key, value in measured.items():
            if value is None:
                del params[key]
            else:
                params[key] = value
        record_path.write_text(json.dumps(record))
    return project, directory, run_prog(A2, project)


def _cards(directory):
    """Resistor cards as the netlist renders them, found through the IR's own role."""
    ir = read_json(directory / "topology.json")
    resistors = {d["name"]: len(d["nets"]) for d in ir["devices"] if d["role"] == "res"}
    cards = {}
    for line in (directory / "mod_alpha.sp").read_text().splitlines():
        tokens = line.split()
        name = tokens[0][1:] if tokens and tokens[0].startswith("x") else None
        if name in resistors:
            sizes = dict(t.split("=", 1) for t in tokens if "=" in t)
            width = next(v for k, v in sizes.items() if k in ("w", "r_width", "width"))
            length = next(v for k, v in sizes.items() if k in ("l", "r_length", "length"))
            cards[name] = {"nets": tokens[1:resistors[name] + 1],
                           "w": float(width.rstrip("u")), "l": float(length.rstrip("u"))}
    return cards


def _chain_total_r(cards, name, r_per_um, r_end):
    members = [card for key, card in cards.items() if re.fullmatch(name + r"_s\d+", key)]
    return sum(r_per_um * card["l"] + 2 * r_end for card in members), members


def test_long_resistors_render_as_a_series_chain_with_the_same_total_resistance(tmp_path):
    constants = {"r_per_um_ohm": 520.0, "r_end_ohm": 3.0}
    straight, straight_dir, result = _case(tmp_path / "straight", measured=constants, **STARTUP)
    assert result.returncode == 0, result.stdout + result.stderr
    assert run_prog(A3, straight).returncode == 0
    before = _cards(straight_dir)
    project, directory, result = _case(tmp_path / "segmented", ROW, measured=constants, **STARTUP)
    assert result.returncode == 0, result.stdout + result.stderr
    emitted = run_prog(A3, project)
    assert emitted.returncode == 0, emitted.stdout + emitted.stderr
    after = _cards(directory)
    long_names = [name for name, card in before.items() if card["l"] > 100.0]
    assert long_names
    for name in long_names:
        parent = before[name]
        total, members = _chain_total_r(after, name, 520.0, 3.0)
        assert name not in after
        assert len(members) >= 2
        assert total == pytest.approx(520.0 * parent["l"] + 6.0, rel=2e-5)
        assert len({card["l"] for card in members}) == 1
        assert all(card["l"] <= 100.0 and card["w"] == parent["w"] for card in members)
        assert all(card["nets"][2] == parent["nets"][2] for card in members)
        assert members[0]["nets"][0] == parent["nets"][0]
        assert members[-1]["nets"][1] == parent["nets"][1]
        for left, right in zip(members, members[1:]):
            assert left["nets"][1] == right["nets"][0]
            assert left["nets"][1].startswith(name + "_n")
    for name, card in before.items():
        if card["l"] <= 100.0:
            assert after[name] == card
    assert ("R" + long_names[0] + "_s0 ") in (directory / "mod_alpha.lvs.cdl").read_text()


def test_a_spec_sized_length_stays_spec_bound(tmp_path):
    project, directory, result = _case(tmp_path, ROW, **STARTUP)
    assert result.returncode == 0, result.stdout + result.stderr
    ir = read_json(directory / "topology.json")
    record = next(p for p in ir[segments.RECORD_KEY]["parents"] if p["device"]["name"] == "rpor")
    assert record["param_exprs"], "rpor is sized by an expression"
    assert run_prog(A3, project).returncode == 0
    text = (directory / "mod_alpha.sp").read_text()
    assert "rpor_s0.l" in re.search(r"spec_bound_params=(.*)", text)[1]
    env = a3._a2.rendering_env(ir["pdk_measured_params"], ir["constants"], ir["knobs"],
                               a2.bound_spec_values(project, "mod_alpha")[0],
                               ir.get(a2.EFFECTIVE_SPEC_KEY))
    rows = [row for row in ir["device_param_exprs"] if row["device"] == "rpor_s0"]
    assert a3.safe_eval(rows[-1]["expr"], env) == pytest.approx(record["segment_l_um"])


def test_without_the_row_the_emitted_ir_is_unsegmented_and_the_pass_never_runs(tmp_path, monkeypatch):
    project, directory, result = _case(tmp_path / "subprocess")
    assert result.returncode == 0, result.stdout + result.stderr
    ir = read_json(directory / "topology.json")
    assert segments.RECORD_KEY not in ir
    assert not any(re.search(r"_s\d+$", d["name"]) for d in ir["devices"] if d["role"] == "res")

    def refuse(*_):
        raise AssertionError("no declared row must not reach segmentation")
    monkeypatch.setattr(a2._segments, "apply", refuse)
    rc, report = a2.run(project, None, a3.DEFAULT_PDK)
    assert rc == 0, report
    assert segments.RECORD_KEY not in read_json(directory / "topology.json")


def test_a_row_above_every_resistor_changes_no_device(tmp_path):
    _, plain, result = _case(tmp_path / "plain")
    assert result.returncode == 0
    _, relaxed, result = _case(tmp_path / "relaxed", dict(ROW, target=1e7))
    assert result.returncode == 0, result.stdout + result.stderr
    left, right = read_json(plain / "topology.json"), read_json(relaxed / "topology.json")
    assert segments.RECORD_KEY not in right
    for key in ("devices", "internal_nets", "device_param_exprs"):
        assert left[key] == right[key]


def test_removing_the_chains_restores_the_unsegmented_graph(tmp_path):
    _, plain, _ = _case(tmp_path / "plain")
    _, segmented, result = _case(tmp_path / "segmented", ROW)
    assert result.returncode == 0, result.stdout + result.stderr
    left, right = read_json(plain / "topology.json"), read_json(segmented / "topology.json")
    assert right["devices"] != left["devices"]
    restored = segments.without_segments(right)
    for key in ("devices", "internal_nets", "device_param_exprs"):
        assert restored[key] == left[key]


@pytest.mark.parametrize("row", [
    dict(ROW, target=True), dict(ROW, target="100"), dict(ROW, target=None), dict(ROW, target=0.0),
    dict(ROW, target=-1.0), dict(ROW, target=float("inf")), dict(ROW, target=float("nan")),
    dict(ROW, unit="mm"), {"name": segments.FIELD, "target": 100.0}, {"name": segments.FIELD, "unit": "um"},
])
def test_an_invalid_declaration_is_refused_by_name(tmp_path, row):
    _, directory, result = _case(tmp_path, row)
    assert result.returncode != 0
    gap = read_json(directory / "topology_gap.json")
    assert gap["status"] == segments.SPEC_INVALID
    assert segments.FIELD in json.dumps(gap)
    assert not (directory / "topology.json").exists()


def test_duplicate_rows_are_refused(tmp_path):
    _, directory, result = _case(tmp_path, ROW, ROW)
    assert result.returncode != 0
    assert read_json(directory / "topology_gap.json")["status"] == segments.SPEC_INVALID


@pytest.mark.parametrize("missing", ["r_end_ohm", "r_per_um_ohm"])
def test_missing_contact_constants_are_refused_not_assumed(tmp_path, missing):
    _, directory, result = _case(tmp_path, ROW, measured={missing: None})
    assert result.returncode != 0
    gap = read_json(directory / "topology_gap.json")
    if missing == "r_per_um_ohm":
        assert gap["status"] in (segments.CONSTANTS_MISSING, "ENTRY_REQUIREMENTS_NOT_MET")
    else:
        assert gap["status"] == segments.CONSTANTS_MISSING
    assert not (directory / "topology.json").exists()


def _flat_ir(length, r_end=0.0, internal=()):
    return {"pdk_measured_params": {"r_end_ohm": r_end, "r_per_um_ohm": 520.0},
            "ports": ["a", "b", "vss"], "internal_nets": list(internal), "device_param_exprs": [],
            "devices": [{"name": "r", "role": "res", "nets": ["a", "b", "vss"], "w": .5, "l": length}]}


def test_no_segment_exceeds_the_declared_maximum_when_contacts_lengthen_the_chain():
    ir = segments.apply(_flat_ir(200.0, r_end=-0.02), 100.0, {}, a3.safe_eval)
    assert all(d["l"] <= 100.0 for d in ir["devices"])
    total = sum(520.0 * d["l"] - 0.04 for d in ir["devices"])
    assert total == pytest.approx(520.0 * 200.0 - 0.04, rel=1e-12)


def test_segments_below_the_process_minimum_are_refused():
    with pytest.raises(segments.SegmentRefused) as refused:
        segments.apply(_flat_ir(200.0), 0.3, {}, a3.safe_eval, min_length_um=0.5)
    assert refused.value.status == segments.NOT_REALISABLE


def test_a_name_collision_is_refused_rather_than_merging_two_nets():
    with pytest.raises(segments.SegmentRefused):
        segments.apply(_flat_ir(200.0, internal=["r_n0"]), 100.0, {}, a3.safe_eval)


def test_two_terminal_resistors_keep_their_terminal_count():
    ir = _flat_ir(200.0)
    ir["devices"][0]["nets"] = ["a", "b"]
    chain = segments.apply(ir, 100.0, {}, a3.safe_eval)["devices"]
    assert [d["nets"] for d in chain] == [["a", "r_n0"], ["r_n0", "b"]]


def _segmented_bias_ir(tmp_path):
    ir, *_ = _emit(tmp_path)
    assert any(d["name"] == "r_ib" for d in ir["devices"])
    env = {k: v for k, v in {**ir["pdk_measured_params"], **ir["constants"], **ir["knobs"]}.items()
           if isinstance(v, (int, float))}
    ir["pdk_measured_params"] = {**ir["pdk_measured_params"], "r_end_ohm": 3.0, "r_per_um_ohm": 520.0}
    env.update(r_end_ohm=3.0, r_per_um_ohm=520.0)
    return segments.apply(ir, 50.0, env, a3.safe_eval)


def test_a_segmented_bias_reference_still_passes_its_network_check(tmp_path):
    ir = _segmented_bias_ir(tmp_path)
    assert any(d["name"] == "r_ib_s0" for d in ir["devices"])
    assert a3._validate_ir(ir, PDK) == []


@pytest.mark.parametrize("corrupt", [
    lambda d: d["nets"].__setitem__(0, "vss"),
    lambda d: d.__setitem__("w", 9.0),
    lambda d: d.__setitem__("l", 1.0),
])
def test_a_broken_chain_cannot_hide_behind_its_record(tmp_path, corrupt):
    ir = _segmented_bias_ir(tmp_path)
    corrupt(next(d for d in ir["devices"] if d["name"] == "r_ib_s0"))
    assert any("RESISTOR_SEGMENT_CHAIN_INVALID" in issue for issue in a3._validate_ir(ir, PDK))


MEASURED = {"r_end_ohm": -0.021632088257319992, "r_per_um_ohm": 520.0018720056144}


def _resistor_ir(*lengths, groups=None):
    return {"ports": ["a", "b"], "internal_nets": [], "pdk_measured_params": dict(MEASURED),
            "device_param_exprs": [], "ratio_matching_groups": groups or [],
            "devices": [{"name": name, "role": "res", "nets": ["a", "b", "b"], "w": 0.5, "l": length}
                        for name, length in lengths]}


def test_matched_resistors_of_one_length_get_identical_chains():
    ir = segments.apply(_resistor_ir(("r1", 724.0), ("r2", 724.0)), 100.0, {}, lambda e, v: 0)
    chains = {name: [d["l"] for d in ir["devices"] if d["name"].startswith(name + "_s")]
              for name in ("r1", "r2")}
    assert chains["r1"] == chains["r2"] and len(chains["r1"]) == 8


def test_matched_resistors_that_would_split_differently_are_refused():
    groups = [{"members": [{"instances": ["r1"]}, {"instances": ["r2"]}]}]
    with pytest.raises(segments.SegmentRefused, match="matched resistors"):
        segments.apply(_resistor_ir(("r1", 724.0), ("r2", 650.0), groups=groups),
                       100.0, {}, lambda e, v: 0)


@pytest.mark.parametrize("length", [1923.07, 1282.86, 724.0])
def test_a_chain_stays_within_half_a_percent_on_the_rendered_device(tmp_path, length):
    root = Path(os.environ.get("PDK_ROOT", "/nonexistent")) / "ihp-sg13g2/libs.tech/ngspice"
    if not shutil.which("ngspice") or not (root / "models/cornerRES.lib").is_file():
        pytest.skip("needs ngspice and the IHP model library")
    ir = segments.apply(_resistor_ir(("r", length)), 100.0, {}, lambda e, v: 0)
    chain = [d for d in ir["devices"] if d["name"].startswith("r_s")]
    deck = [f".lib {root}/models/cornerRES.lib res_typ", "Vs s 0 1", "Vc c0 0 1",
            f"xs s 0 0 rppd w=0.5u l={length}u"]
    for index, device in enumerate(chain):
        end = "0" if index == len(chain) - 1 else f"c{index + 1}"
        deck.append(f"xc{index} c{index} {end} 0 rppd w=0.5u l={round(device['l'], 2)}u")
    deck += [".control", f"pre_osdi {root}/osdi/r3_cmc.osdi", "op",
             "print 1/abs(i(vs)) 1/abs(i(vc))", "quit", ".endc", ".end"]
    path = tmp_path / "chain.sp"
    path.write_text("* chain\n" + "\n".join(deck) + "\n")
    run = subprocess.run(["ngspice", "-b", str(path)], cwd=root, text=True, capture_output=True)
    values = [float(v) for v in re.findall(r"= *([0-9.e+-]+)", run.stdout)][-2:]
    assert len(values) == 2 and values[0] > 0, run.stdout[-500:] + run.stderr[-500:]
    assert abs(values[1] / values[0] - 1) <= 0.005, values
