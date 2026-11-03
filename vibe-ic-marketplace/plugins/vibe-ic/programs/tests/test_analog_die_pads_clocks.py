"""Side names reach their ports; typed L9 and L8 facts bind several primary clocks (#3792)."""
import json

import pytest

import io_pad_chip_top_gen as pads
import librelane_contract as contract

NETS = ["in1", "core", "out1", "dout"]


def answers(project, value):
    path = project / "input/step_0_5ic_answers.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"answers": {"pad_signal_map": value}}))


def test_side_names_bind_by_case_when_nothing_is_declared(tmp_path):
    bound = pads._bind_side_names(tmp_path, {"W": ["IN1", "dout"], "E": ["OUT1", "CORE"]}, NETS)
    assert bound == {"W": ["in1", "dout"], "E": ["out1", "core"]}


def test_declared_map_outranks_case(tmp_path):
    answers(tmp_path, {"PWR": "core", "IN1": "out1"})
    assert pads._bind_side_names(tmp_path, {"S": ["PWR", "IN1"]}, NETS) == {"S": ["core", "out1"]}


def test_exact_name_outranks_the_declared_map(tmp_path):
    answers(tmp_path, {"in1": "core"})
    assert pads._bind_side_names(tmp_path, {"S": ["in1"]}, NETS) == {"S": ["in1"]}


def test_declared_map_naming_an_unknown_port_is_refused(tmp_path):
    answers(tmp_path, {"PWR": "absent"})
    with pytest.raises(pads.Refusal) as caught:
        pads._bind_side_names(tmp_path, {"S": ["PWR"]}, NETS)
    assert "SIDE_NAMES_UNKNOWN_PORT" in str(caught.value.args) + str(getattr(caught.value, "rule", ""))


def test_two_ports_differing_only_by_case_stay_unbound(tmp_path):
    nets = ["clk", "CLK"]
    assert pads._bind_side_names(tmp_path, {"S": ["Clk"]}, nets) == {"S": ["Clk"]}


def test_unknown_name_stays_unbound_for_the_existing_refusal(tmp_path):
    assert pads._bind_side_names(tmp_path, {"S": ["GHOST"]}, NETS) == {"S": ["GHOST"]}


CLOCKS = [{"source_pin": name, "period_ns": 1000.0} for name in ("ck1", "ck2")]
PORTS = [{"name": name, "direction": "input"} for name in ("ck1", "ck2")]
GROUPS = [{"name": "g", "clocks": ["ck1", "ck2"], "relationship": "asynchronous"}]


def instance(name, net):
    return {"name": name, "ports": [{"name": "clk", "net": net, "type": "clock", "direction": "input"},
                                    {"name": "vin", "net": "ck2", "type": "analog", "direction": "input"}]}


def l9(*rows):
    return {"top_ports": PORTS, "instances": list(rows)}


def bind(tmp_path, doc, groups=GROUPS):
    return contract._bound_primary_clocks(tmp_path, doc, CLOCKS, tmp_path / "absent.sdc", groups)


def test_typed_instance_clock_ports_and_groups_bind_the_clocks(tmp_path):
    ports, text, _ = bind(tmp_path, l9(instance("A", "ck1"), instance("B", "ck2")))
    assert ports == ["ck1", "ck2"]
    assert "create_clock -name ck1 -period 1000.0 [get_ports ck1]" in text
    assert "set_clock_groups -asynchronous -group [get_clocks ck1] -group [get_clocks ck2]" in text


def test_no_binding_of_either_kind_is_still_refused(tmp_path):
    with pytest.raises(contract.Refusal, match="LL_CLOCK_AMBIGUOUS"):
        bind(tmp_path, l9())


def test_a_non_clock_port_does_not_bind_a_clock(tmp_path):
    with pytest.raises(contract.Refusal, match="unbound primary clock"):
        bind(tmp_path, l9(instance("A", "ck1")))


def test_an_instance_on_an_undeclared_clock_is_refused(tmp_path):
    with pytest.raises(contract.Refusal, match="undeclared or ambiguous"):
        bind(tmp_path, l9(instance("A", "ck1"), instance("B", "ck2"), instance("C", "ghost")))


@pytest.mark.parametrize("groups", [None, [], [{"name": "g", "clocks": ["ck1", "ck2"], "relationship": "synchronous"}]])
def test_clocks_without_a_stated_asynchronous_group_are_still_refused(tmp_path, groups):
    with pytest.raises(contract.Refusal, match="LL_CLOCK_AMBIGUOUS"):
        bind(tmp_path, l9(instance("A", "ck1"), instance("B", "ck2")), groups)


def test_a_staged_sdc_still_owns_the_clocks(tmp_path):
    sdc = tmp_path / "staged.sdc"
    sdc.write_text("create_clock -name ck1 -period 1000.0 [get_ports ck1]\n")
    with pytest.raises(contract.Refusal, match="SDC must declare"):
        contract._bound_primary_clocks(tmp_path, l9(instance("A", "ck1"), instance("B", "ck2")),
                                       CLOCKS, sdc, GROUPS)
