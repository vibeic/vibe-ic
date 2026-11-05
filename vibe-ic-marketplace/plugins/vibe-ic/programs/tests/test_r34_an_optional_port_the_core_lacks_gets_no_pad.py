"""r34 (subservient x gf180mcuD as a DIE): an OPTIONAL L9 port the implemented
core does not carry must not get a pad or a core connection.

MEASURED: L3 marks `(optional) i_gpio`, L9 records `optional: true`, the
synthesised core has no `i_gpio`; the wrapper wired `.i_gpio(...)` anyway and
routing refused PADRING_CORE_PORT_CONNECTION_MISMATCH unknown=['i_gpio'].

Both directions: only `optional is True` AND absent is dropped (and recorded);
a required absent port, a present optional port, a truthy-but-not-True flag
and an unreadable netlist all keep the port, so the runner's connection check
still owns every other mismatch.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import io_pad_chip_top_gen as G  # noqa: E402
import phase3_one_shot_runner as R  # noqa: E402

NETLIST = """module core(i_clk, o_gpio);
  input i_clk;
  output o_gpio;
endmodule
"""


def _project(tmp_path: Path, netlist_text=NETLIST) -> Path:
    spec = tmp_path / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    spec.parent.mkdir(parents=True)
    spec.write_text(json.dumps({"top_module": "core"}))
    nl = tmp_path / "core_synth.v"
    if netlist_text is not None:
        nl.write_text(netlist_text)
    return tmp_path


@pytest.fixture
def selected(monkeypatch):
    def pick(project, top):
        return Path(project) / "core_synth.v", "test netlist", False
    monkeypatch.setattr(R, "pnr_input_netlist", pick)


def _names(ports):
    return [p["name"] for p in ports]


def test_an_optional_port_the_core_lacks_is_dropped_and_recorded(tmp_path, selected):
    ports = [{"name": "i_clk", "direction": "input"},
             {"name": "o_gpio", "direction": "output"},
             {"name": "i_gpio", "direction": "input", "optional": True,
              "evidence": "input/docs/L3.md"}]
    kept, dropped = G._drop_unimplemented_optional_ports(_project(tmp_path), ports)
    assert _names(kept) == ["i_clk", "o_gpio"]
    assert [d["name"] for d in dropped] == ["i_gpio"]
    assert dropped[0]["evidence"] == "input/docs/L3.md"


def test_an_optional_port_the_core_carries_keeps_its_pad(tmp_path, selected):
    ports = [{"name": "i_clk"}, {"name": "o_gpio", "optional": True}]
    kept, dropped = G._drop_unimplemented_optional_ports(_project(tmp_path), ports)
    assert _names(kept) == ["i_clk", "o_gpio"] and dropped == []


@pytest.mark.parametrize("flag", [None, False, "true", 1])
def test_a_port_not_declared_optional_is_never_dropped(tmp_path, selected, flag):
    port = {"name": "i_missing"}
    if flag is not None:
        port["optional"] = flag
    kept, dropped = G._drop_unimplemented_optional_ports(
        _project(tmp_path), [{"name": "i_clk"}, port])
    assert "i_missing" in _names(kept) and dropped == []


def test_an_unreadable_netlist_drops_nothing(tmp_path, selected):
    ports = [{"name": "i_clk"}, {"name": "i_gpio", "optional": True}]
    kept, dropped = G._drop_unimplemented_optional_ports(
        _project(tmp_path, netlist_text=None), ports)
    assert _names(kept) == ["i_clk", "i_gpio"] and dropped == []
