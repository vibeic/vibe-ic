"""Native row-cone equivalence and safe fallback; no claim is waived."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import formal_structural_check as fsc


def cell(kind, a, y, b=None, s=None):
    conn = {"A": a, "Y": y}
    params = {"A_SIGNED": 0, "A_WIDTH": len(a), "Y_WIDTH": len(y)}
    if b is not None:
        conn["B"] = b
        params.update(B_SIGNED=0, B_WIDTH=len(b))
    if s is not None:
        conn["S"] = s
        params = {"WIDTH": len(y)}
    return {"type": kind, "parameters": params, "connections": conn,
            "port_directions": {p: "output" if p == "Y" else "input" for p in conn}}


def model(cells):
    return {"modules": {"transition_pair": {"attributes": {}, "ports": {
        "d": {"direction": "input", "bits": [2]},
        "q": {"direction": "input", "bits": [3]},
        "n": {"direction": "output", "bits": [4]}},
        "cells": cells, "netnames": {}}}}


def relation(kind, a, b, y, *, signed=0):
    return {"type": kind,
            "parameters": {"A_SIGNED": signed, "B_SIGNED": signed,
                           "A_WIDTH": len(a), "B_WIDTH": len(b), "Y_WIDTH": len(y)},
            "connections": {"A": a, "B": b, "Y": y},
            "port_directions": {"A": "input", "B": "input", "Y": "output"}}


def pmux(a, b, s, y):
    return {"type": "$pmux", "parameters": {"WIDTH": len(y), "S_WIDTH": len(s)},
            "connections": {"A": a, "B": b, "S": s, "Y": y},
            "port_directions": {"A": "input", "B": "input", "S": "input", "Y": "output"}}


def pmux_matrix_model(*, undef_selector=False, undef_data=False):
    """Three-arm PMUX plus a total off-cone user of shared PMUX inputs."""
    selector = [10, "x", 12] if undef_selector else [10, 11, 12]
    data = ["x", 4, 5, 6, 7, 8] if undef_data else [4, 5, 6, 7, 8, 9]
    ports = {
        "a": {"direction": "input", "bits": [2, 3]},
        "b": {"direction": "input", "bits": [bit for bit in data if isinstance(bit, int)]},
        "s": {"direction": "input", "bits": [bit for bit in selector if isinstance(bit, int)]},
        "off": {"direction": "input", "bits": [13, 14]},
        "n": {"direction": "output", "bits": [15, 16]},
    }
    cells = {
        "row": pmux([2, 3], data, selector, [15, 16]),
        "offcone": cell("$xor", [2, 3], [17, 18], [13, 14]),
    }
    return {"modules": {"transition_pair": {"attributes": {}, "ports": ports,
                                               "cells": cells, "netnames": {}}}}


@pytest.mark.parametrize("defect,reason", [
    ("feedback", "combinational-feedback"),
    ("multiple", "non-unique-output-driver"),
    ("repeated-output", "non-unique-output-driver"),
    ("literal-output", "non-unique-output-driver"),
    ("input-output", "non-unique-output-driver"),
    ("unknown", "non-total-or-unsupported-cell")])
def test_non_extendable_models_keep_whole_module(defect, reason):
    cells = {"row": cell("$and", [2], [4], [3])}
    cells.update({
        "feedback": {"extra": cell("$eqx", [5], [5], [2])},
        "multiple": {"extra": cell("$not", [2], [4])},
        "repeated-output": {"extra": cell("$not", [2, 3], [5, 5])},
        "literal-output": {"extra": cell("$not", [2], ["0"])},
        "input-output": {"extra": cell("$not", [3], [2])},
        "unknown": {"extra": cell("$unknown", [2], [5])}}[defect])
    assert fsc._reset_row_cone_eligibility(model(cells)) == {"eligible": False, "reason": reason}


@pytest.mark.parametrize("direction", [None, "inout"])
def test_unknown_directions_keep_whole_module(direction):
    data = model({"row": cell("$and", [2], [4], [3])})
    data["modules"]["transition_pair"]["cells"]["row"]["port_directions"]["A"] = direction
    assert fsc._reset_row_cone_eligibility(data) == {
        "eligible": False, "reason": "unknown-native-pin-direction"}


@pytest.mark.parametrize("kind", ["$ge", "$le"])
@pytest.mark.parametrize("signed", [0, 1])
def test_legal_comparison_relations_are_cone_eligible(kind, signed):
    data = model({"row": relation(kind, [2], [3], [4], signed=signed)})
    assert fsc._reset_row_cone_eligibility(data) == {
        "eligible": True, "reason": "single-driver-total-boolean-dag"}


def test_legal_pmux_relation_is_cone_eligible():
    data = model({"row": pmux([2], [3, 5], [6, 7], [4])})
    assert fsc._reset_row_cone_eligibility(data) == {
        "eligible": True, "reason": "single-driver-total-boolean-dag"}


@pytest.mark.parametrize("kind,mutation", [
    ("$ge", lambda c: c["parameters"].__setitem__("Y_WIDTH", 2)),
    ("$le", lambda c: c["connections"].__setitem__("Y", [4, 5])),
    ("$pmux", lambda c: c["parameters"].__setitem__("S_WIDTH", 3)),
    ("$pmux", lambda c: c["connections"].__setitem__("B", [3])),
    ("$pmux", lambda c: c["parameters"].__setitem__("WIDTH", 2)),
    ("$ge", lambda c: c["port_directions"].__setitem__("Y", "input")),
    ("$le", lambda c: c["port_directions"].__setitem__("Y", "input")),
    ("$pmux", lambda c: c["port_directions"].__setitem__("Y", "input")),
    ("$pmux", lambda c: c["port_directions"].__setitem__("S", "output")),
])
def test_malformed_new_total_relations_keep_whole_module(kind, mutation):
    candidate = (relation(kind, [2], [3], [4]) if kind != "$pmux"
                 else pmux([2], [3, 5], [6, 7], [4]))
    mutation(candidate)
    result = fsc._reset_row_cone_eligibility(model({"row": candidate}))
    assert result["eligible"] is False, result
    assert result["reason"] == "malformed-total-cell-shape", result


@pytest.mark.parametrize("defect,expected", [
    ("feedback", "combinational-feedback"),
    ("multiple-driver", "non-unique-output-driver"),
])
def test_pmux_feedback_and_multiple_driver_keep_whole_module(defect, expected):
    cells = {"row": pmux([2], [3, 4], [6, 7], [4])}
    if defect == "multiple-driver":
        cells["other"] = cell("$not", [2], [4])
    assert fsc._reset_row_cone_eligibility(model(cells)) == {
        "eligible": False, "reason": expected}


def native(tmp_path, data, commands, cone):
    if not shutil.which("yosys"):
        pytest.fail("native Yosys required for this focused repair control")
    tmp_path.mkdir()
    (tmp_path / "model.json").write_text(json.dumps(data))
    lines = [f"read_json {tmp_path / 'model.json'}", "hierarchy -top transition_pair"]
    if cone:
        lines += ["select -module transition_pair", "select w:n %% %ci*"]
    for i, cmd in enumerate(commands):
        lines += [f"log VIBEIC_TRANSITION_QUERY {i}",
                  "sat -timeout 10 -enable_undef -set-def-inputs " + cmd + " -show-inputs -show n",
                  f"log VIBEIC_TRANSITION_COMPLETE {i}"]
    script = tmp_path / "query.ys"
    script.write_text("\n".join(lines) + "\n")
    run = subprocess.run(["yosys", "-Q", "-T", "-s", str(script)], capture_output=True, text=True, timeout=30)
    (tmp_path / "native.log").write_text(run.stdout + run.stderr)
    assert run.returncode == 0, run.stdout + run.stderr
    return fsc._transition_query_progress(run.stdout + run.stderr, [str(i) for i in range(len(commands))])


@pytest.mark.parametrize("literal", [None, "x", "z"])
def test_native_undef_shared_q_and_cofactor_are_identical(tmp_path, literal):
    # n uses the exact same shared current Q and undef source twice through
    # reconvergence. The off-cone branch is total but must not normalize X.
    source = 8 if literal is None else literal
    data = model({"inv": cell("$not", [source], [5]),
                  "both": cell("$and", [source], [6], [5]),
                  "row": cell("$mux", [6], [4], [3], [2]),
                  "extra": cell("$xor", [2], [7], [3])})
    assert fsc._reset_row_cone_eligibility(data)["eligible"]
    commands = ["-set-any-undef n", "-prove n 0", "-prove n 1",
                "-set d 1 -prove n q", "-set d 0 -set-any-undef n"]
    full = native(tmp_path / "full", data, commands, False)
    cone = native(tmp_path / "cone", data, commands, True)
    assert full["by_identity"] == cone["by_identity"]
    # Pinned native Yosys treats this Z arithmetic differently from X. Keep
    # that exact native behavior; do not replace it with a Python X/Z rule.
    assert full["by_identity"]["0"]["result"] == ("NO_UNDEF" if literal == "z" else "HAS_UNDEF")
    assert full["by_identity"]["3"]["result"] == "PROVED"


@pytest.mark.parametrize("kind", ["$ge", "$le"])
@pytest.mark.parametrize("signed", [0, 1])
def test_native_comparison_full_and_cone_are_identical(tmp_path, kind, signed):
    data = model({"row": relation(kind, [2], [3], [4], signed=signed),
                  "offcone": cell("$xor", [2], [7], [3])})
    assert fsc._reset_row_cone_eligibility(data)["eligible"]
    expected = int((1 >= 0) if kind == "$ge" else (1 <= 0))
    if signed:
        expected = int((-1 >= 0) if kind == "$ge" else (-1 <= 0))
    commands = [f"-set d 1 -set q 0 -prove n {expected}"]
    full = native(tmp_path / "full", data, commands, False)
    cone = native(tmp_path / "cone", data, commands, True)
    assert full["by_identity"] == cone["by_identity"]
    assert full["by_identity"]["0"]["result"] == "PROVED"


@pytest.mark.parametrize("kind", ["$ge", "$le"])
@pytest.mark.parametrize("signed", [0, 1])
def test_native_comparison_undef_full_and_cone_are_identical(tmp_path, kind, signed):
    data = model({"row": relation(kind, ["x"], [3], [4], signed=signed),
                  "offcone": cell("$xor", [2], [7], [3])})
    assert fsc._reset_row_cone_eligibility(data)["eligible"]
    commands = ["-set q 0 -set-any-undef n"]
    full = native(tmp_path / "full", data, commands, False)
    cone = native(tmp_path / "cone", data, commands, True)
    assert full["by_identity"] == cone["by_identity"]
    assert full["by_identity"]["0"]["result"] == "HAS_UNDEF"


@pytest.mark.parametrize("case,command,expected,undef_selector,undef_data", [
    ("default", "-set a 2'b10 -set b 6'b111001 -set s 3'b000 -set off 2'b11 -prove n 2'b10",
     "PROVED", False, False),
    ("one_hot_0", "-set a 0 -set b 6'b111001 -set s 3'b001 -set off 2'b01 -prove n 1",
     "PROVED", False, False),
    ("one_hot_1", "-set a 0 -set b 6'b111001 -set s 3'b010 -set off 2'b10 -prove n 2",
     "PROVED", False, False),
    ("one_hot_2", "-set a 0 -set b 6'b111001 -set s 3'b100 -set off 2'b11 -prove n 3",
     "PROVED", False, False),
    ("equal_overlap", "-set a 0 -set b 6'b110101 -set s 3'b011 -set off 0 -set-any-undef n",
     "HAS_UNDEF", False, False),
    ("unequal_overlap", "-set a 0 -set b 6'b111001 -set s 3'b011 -set off 1 -set-any-undef n",
     "HAS_UNDEF", False, False),
    ("undefined_selector", "-set a 0 -set b 6'b111100 -set s 0 -set off 2 -set-any-undef n",
     "HAS_UNDEF", True, False),
    ("undefined_data", "-set a 0 -set b 0 -set s 1 -set off 3 -set-any-undef n",
     "HAS_UNDEF", False, True),
])
def test_native_pmux_full_and_cone_matrix_is_identical(
        tmp_path, case, command, expected, undef_selector, undef_data):
    data = pmux_matrix_model(undef_selector=undef_selector, undef_data=undef_data)
    assert fsc._reset_row_cone_eligibility(data) == {
        "eligible": True, "reason": "single-driver-total-boolean-dag"}
    full = native(tmp_path / "full", data, [command], False)
    cone = native(tmp_path / "cone", data, [command], True)
    assert full["by_identity"] == cone["by_identity"], case
    assert full["by_identity"] == {
        "0": {"status": "COMPLETED", "result": expected}}


@pytest.mark.parametrize("case,selector,data,expected_undef", [
    ("default", "000", "111001", "NO_UNDEF"),
    ("one_hot_0", "001", "111001", "NO_UNDEF"),
    ("one_hot_1", "010", "111001", "NO_UNDEF"),
    ("one_hot_2", "100", "111001", "NO_UNDEF"),
    ("equal_overlap", "011", "110101", "HAS_UNDEF"),
    ("unequal_overlap", "011", "111001", "HAS_UNDEF"),
    ("undefined_selector", "0x0", "111100", "HAS_UNDEF"),
    ("undefined_data", "001", "00000x", "HAS_UNDEF"),
])
def test_native_pmux_reset_consumer_preserves_every_full_model_answer(
        tmp_path, monkeypatch, case, selector, data, expected_undef):
    """Exercise the shipped query builder, not the direct SAT helper above."""
    if not shutil.which("yosys"):
        pytest.fail("native Yosys required for this focused consumer control")
    # Native JSON retains literal X and overlapping PMUX arms before any
    # cleanup. The off-cone branch shares A, which stays a defined free input.
    mod = pmux_matrix_model()["modules"]["transition_pair"]
    mod["cells"]["row"] = pmux([2, 3], list(reversed(data)),
                                 list(reversed(selector)), [15, 16])
    mod["ports"].update({
        "rst": {"direction": "input", "bits": [19]},
        "clk": {"direction": "input", "bits": [20]},
        "q": {"direction": "output", "bits": [21, 22]},
        "noise": {"direction": "output", "bits": [17, 18]},
    })
    mod["cells"]["reset"] = cell("$mux", [15, 16], [23, 24],
                                  ["0", "0"], [19])
    mod["cells"]["state"] = {
        "type": "$dff", "parameters": {"WIDTH": 2, "CLK_POLARITY": 1},
        "connections": {"CLK": [20], "D": [23, 24], "Q": [21, 22]},
        "port_directions": {"CLK": "input", "D": "input", "Q": "output"},
    }
    mod["netnames"] = {name: {"bits": port["bits"], "attributes": {}}
                       for name, port in mod["ports"].items()}
    subject = {"modules": {"m": mod}}
    cone = fsc.reset_control_mapping(subject, subject, "m", "rst", tmp_path / "cone")
    with monkeypatch.context() as control:
        control.setattr(fsc, "_reset_row_cone_eligibility", lambda _model: {
            "eligible": False, "reason": "whole-model native control"})
        full = fsc.reset_control_mapping(subject, subject, "m", "rst", tmp_path / "full")
    assert cone["native_row_cone"]["eligible"] is True, cone
    assert full["native_row_cone"]["eligible"] is False, full
    assert cone["raw_identities"] == full["raw_identities"]
    assert len(cone["raw_identities"]) == len(cone["rows"]) == 2
    # Compare the exact identity/result map, including the original domain
    # witness and every role/cofactor query. No aggregate PASS substitutes.
    for mapping in (cone, full):
        progress = mapping["query_progress"]
        assert progress["planned"] == progress["started"] == progress["completed"] == 59, mapping
        assert not progress["unknown"], progress
        assert mapping["native_exit_code"] == 0, mapping
        # The active reset arm is defined zero even when PMUX data is X.
        # Pin this semantic result before the complete-map comparison so a
        # broken root union has a concrete native-value counterexample.
        for row in mapping["rows"]:
            assert row["native_queries"]["zero1"] == "PROVED", (case, row)
    assert cone["query_progress"]["by_identity"] == full["query_progress"]["by_identity"], case
    for index, (left, right) in enumerate(zip(cone["rows"], full["rows"])):
        assert left["native_queries"] == right["native_queries"], case
        assert left["classification"] == right["classification"], case
        expected = "NO_UNDEF" if case == "undefined_data" and index == 1 else expected_undef
        assert left["native_queries"]["undef0"] == expected, (case, left)
        if case.startswith("one_hot_"):
            value = (1, 2, 3)[int(case[-1])]
            proof = "one0" if value & (1 << index) else "zero0"
            assert left["native_queries"][proof] == "PROVED", (case, left)
        assert left["native_queries"]["undef1"] == "NO_UNDEF", (case, left)
    for arm in ("cone", "full"):
        script = (tmp_path / arm / "transition_pair.ys").read_text().splitlines()
        queries = [line for line in script if line.startswith("sat ")]
        assert len(queries) == 59
        assert all("-enable_undef -set-def-inputs" in line for line in queries)
        paired = json.loads((tmp_path / arm / "transition_pair.json").read_text())
        assert sum(c["type"] == "$pmux" for c in
                   paired["modules"]["transition_pair"]["cells"].values()) == 2
    print("PMUX_CONSUMER_ANSWER_SET " + json.dumps({
        "case": case, "answers": cone["query_progress"]["by_identity"],
        "identities": 59, "rows": 2,
    }, sort_keys=True))


def test_native_feedback_can_restrict_shared_domain_and_is_not_pruned(tmp_path):
    data = model({"row": cell("$and", [2], [4], ["1"]),
                  "feedback": cell("$eqx", [5], [5], [2])})
    assert not fsc._reset_row_cone_eligibility(data)["eligible"]
    full = native(tmp_path / "full", data, ["-prove n 1"], False)
    unsound = native(tmp_path / "unsafe-cone", data, ["-prove n 1"], True)
    assert full["by_identity"]["0"]["result"] == "PROVED"
    assert unsound["by_identity"]["0"]["result"] == "REFUTED"
