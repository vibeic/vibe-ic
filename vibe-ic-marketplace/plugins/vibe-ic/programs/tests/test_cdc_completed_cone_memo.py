"""Neutral unit graphs exercise exact legacy reachability; native tests are separate."""
from pathlib import Path
import sys

import pytest

PROG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROG))
import _cdc_netlist as cdc


def analysis(nl):
    # Exercise the old owner too: it predates the private per-analysis view.
    factory = getattr(cdc, "_AnalysisNetlist", None)
    return factory(nl) if factory is not None else nl


def model(cyclic=False, unknown=False, fallback=False):
    kind = "neutral_unclassified" if unknown else "$xor"
    cells = {
        "a": {"type": kind, "connections": {"A": [20, 1] if cyclic else [1], "B": [] if cyclic else [2], "Y": [10, 11]},
              "port_directions": {} if fallback else {"A": "input", "B": "input", "Y": "output"}},
        "b": {"type": "$xor", "connections": {"A": [10, 2] if cyclic else [3], "B": [] if cyclic else [4], "Y": [20, 21]},
              "port_directions": {"A": "input", "B": "input", "Y": "output"}},
        "c": {"type": "$xor", "connections": {"A": [3], "B": [4], "Y": [30, 31]},
              "port_directions": {"A": "input", "B": "input", "Y": "output"}},
    }
    flops = [cdc.Flop("launch", "$dff", 90, 1, [10], [1]),
             cdc.Flop("capture", "$dff", 91, 1, [20], [3])]
    ports = {"data_i": ("input", [2, 4]), "clk_a": ("input", [90]), "clk_b": ("input", [91])}
    nl = cdc.Netlist("neutral", ports, cells, {1: "launch", 3: "capture"}, flops=flops)
    nl.drivers = {bit: (name, "Y") for name, cell in cells.items() for bit in cell["connections"]["Y"]}
    return nl


@pytest.mark.parametrize("options", [{}, {"cyclic": True}, {"unknown": True}, {"fallback": True}])
def test_shared_multioutput_queries_do_not_repeat_completed_walks(monkeypatch, options):
    nl = model(**options)
    legacy = cdc.Netlist.cone
    walks = 0
    def count(self, bits, skip=None):
        nonlocal walks
        walks += 1
        return legacy(self, bits, skip)
    monkeypatch.setattr(cdc.Netlist, "cone", count)
    view = analysis(nl)
    for bit in [10, 11] * 8:
        actual = view.cone([bit])
        assert actual == legacy(nl, [bit])
        assert actual == ({1}, {2})
    excess_walks = max(walks - 1, 0)
    assert excess_walks == 0, {"complete_legacy_walks": walks}


def test_full_skip_leaf_priority_multi_seed_and_constants_match_legacy():
    nl = model(cyclic=True)
    # Endpoint priority precedes driver lookup even when a model aliases them.
    nl.drivers[1] = ("a", "Y")
    nl.ports["alias_i"] = ("input", [1])
    view = analysis(nl)
    queries = [([10], None), ([20], None), ([11], None), ([21], None),
               ([10], {10}), ([11], {10}), ([11], {20}), ([10], {20}),
               ([11], {1}), ([11], {2}), ([1], None), ([2], None),
               (["0", "1"], None), ([999], None), ([10, 20], {10}),
               ([1, 11], {1}), ([11, 10, 11], {2}), ([10], {1, 2})]
    for seeds, skip in queries:
        assert view.cone(seeds, skip) == cdc.Netlist.cone(nl, seeds, skip)
    assert view.cone([10], {20}) == ({1}, set())
    assert view.cone([20], {10}) == (set(), {2})
    assert view.cone([1]) == ({1}, set())


def test_mutated_returned_sets_do_not_poison_completed_result():
    nl = model(cyclic=True)
    view = analysis(nl)
    q, p = view.cone([10])
    q.clear()
    p.add(999)
    assert view.cone([11]) == ({1}, {2})


def test_new_analysis_uses_current_graph_and_port_mutations():
    nl = model()
    assert analysis(nl).cone([10]) == ({1}, {2})
    nl.cells["a"]["connections"]["A"] = [3]
    nl.cells["a"]["connections"]["B"] = [4]
    nl.ports["new_input_i"] = nl.ports.pop("data_i")
    assert analysis(nl).cone([11]) == ({3}, {4})


def test_lru_eviction_recomputes_without_changing_results():
    from _cdc_cone_memo import CompletedConeMemo
    nl = analysis(model())
    walks = 0
    def legacy(bits, skip=None):
        nonlocal walks
        walks += 1
        return cdc.Netlist.cone(nl, bits, skip)
    memo = CompletedConeMemo(nl, legacy, max_entries=2, max_bytes=1000000)
    for bit in [10, 20, 11, 30, 21]:
        assert memo.cone([bit]) == cdc.Netlist.cone(nl, [bit])
    assert walks == 4
    assert memo.retained_bytes <= 1000000


def test_oversize_and_large_skip_keys_never_bypass_full_walk():
    from _cdc_cone_memo import CompletedConeMemo
    nl = analysis(model(cyclic=True))
    walks = 0
    def legacy(bits, skip=None):
        nonlocal walks
        walks += 1
        return cdc.Netlist.cone(nl, bits, skip)
    memo = CompletedConeMemo(nl, legacy, max_entries=2, max_bytes=1)
    for bit in [10, 11]:
        assert memo.cone([bit]) == ({1}, {2})
    assert walks == 2
    assert memo.retained_bytes == 0
    memo = CompletedConeMemo(nl, legacy, max_entries=2, max_bytes=1000)
    skip = set(range(1000, 2000))
    for bit in [10, 11]:
        assert memo.cone([bit], skip) == ({1}, {2})
    assert walks == 4
    assert memo.retained_bytes == 0


def test_byte_budget_evicts_completed_entries_without_losing_leaves():
    from _cdc_cone_memo import CompletedConeMemo
    nl = analysis(model())
    walks = 0
    def legacy(bits, skip=None):
        nonlocal walks
        walks += 1
        return cdc.Netlist.cone(nl, bits, skip)
    memo = CompletedConeMemo(nl, legacy, max_entries=99, max_bytes=1000000)
    memo.cone([10])
    memo.max_bytes = memo.retained_bytes + 1
    for bit in [20, 11]:
        assert memo.cone([bit]) == cdc.Netlist.cone(nl, [bit])
        assert memo.retained_bytes <= memo.max_bytes
    assert walks == 3


def test_pure_cycle_and_distinct_output_pins_keep_legacy_relation():
    nl = model(cyclic=True)
    nl.cells["a"]["connections"] = {"A": [20], "Y": [10], "Z": [11]}
    nl.cells["a"]["port_directions"] = {"A": "input", "Y": "output", "Z": "output"}
    nl.drivers[11] = ("a", "Z")
    nl.cells["b"]["connections"]["A"] = [10]
    view = analysis(nl)
    for bit in [10, 11, 20, 21]:
        assert view.cone([bit]) == cdc.Netlist.cone(nl, [bit])
        assert view.cone([bit]) == (set(), set())
