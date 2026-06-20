"""phase1_port_extract — deterministic PORT/PARAM/RESET extraction for Phase-1 NL.

Field measurement (CVDP 12-prompt AI-vs-program audit): the phase1 NL ingester
captured only ~17% of an AI's ports because it (a) only recognised inline Verilog
declarations, (b) `_parse_md_table_ports` did not recognise the common `In/Out`
direction header or `Length` width header, and (c) returned only the single
largest interface table when a spec splits clock/reset, input and output into
SEPARATE tables. This validates the three structural fixes — and asserts the
gates' single-best contract is preserved (union is opt-in).
"""
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import _specrtl_common as S   # noqa: E402
import phase1_port_extract as PX  # noqa: E402

# A spec that splits its interface across THREE tables with `In/Out` + `Length`
# headers and `in`/`out` values — the dominant CVDP form.
_MULTI_TABLE = """\
### Clock / Reset
| Name | In/Out | Length | Description |
|------|--------|--------|-------------|
| Clk  | in     | 1      | clock |
| Rst  | in     | 1      | async reset |

### Input Data
| Name     | In/Out | Length      | Description |
|----------|--------|-------------|-------------|
| In_Data  | in     | `WIDTH`     | data in |
| In_Valid | in     | 1           | valid |

### Output Data
| Name      | In/Out | Length | Description |
|-----------|--------|--------|-------------|
| Out_Data  | out    | 8      | data out |
| Out_Valid | out    | 1      | valid |
"""


def test_in_out_header_recognised():
    assert S._DIR_HDR.match("In/Out")
    assert S._DIR_HDR.match("I/O")          # back-compat
    assert S._DIR_HDR.match("Direction")


def test_length_width_header_recognised():
    assert S._WIDTH_HDR.match("Length")
    assert S._WIDTH_HDR.match("Len")
    assert S._WIDTH_HDR.match("Width")      # back-compat


def test_union_collects_every_interface_table():
    names = {p.name for p in S._parse_md_table_ports(_MULTI_TABLE, union=True)[0]}
    assert names == {"Clk", "Rst", "In_Data", "In_Valid", "Out_Data", "Out_Valid"}


def test_default_is_single_best_table_gate_contract_preserved():
    # §4.05: the conformance gates rely on the single-best contract — default
    # (union=False) must still return ONLY the largest qualifying table.
    best, _ = S._parse_md_table_ports(_MULTI_TABLE)   # union defaults to False
    # the largest table here has 2 ports; best must be one 2-port table, not all 6
    assert len(best) == 2


def test_phase1_extractor_unions_all_ports():
    ports = {p["name"] for p in PX.extract_ports(_MULTI_TABLE)}
    assert ports == {"Clk", "Rst", "In_Data", "In_Valid", "Out_Data", "Out_Valid"}
    # direction + width carried
    by = {p["name"]: p for p in PX.extract_ports(_MULTI_TABLE)}
    assert by["Out_Data"]["dir"] == "output" and by["Out_Data"]["width"] == 8


def test_param_table_and_decl_extracted():
    txt = ("| Name | Default | Description |\n|---|---|---|\n"
           "| WIDTH | 32 | data width |\n| DEPTH | 8 | fifo depth |\n"
           "Also `parameter N = 4;` inline.\n")
    params = {p["name"]: p["default"] for p in PX.extract_params(txt)}
    assert params.get("WIDTH") == "32" and params.get("DEPTH") == "8"
    assert params.get("N") == "4"


def test_reset_polarity_inferred():
    r = PX.extract("input rst_n; // active-low asynchronous reset")
    assert r["reset"]["name"].lower() == "rst_n"
    assert r["reset"]["polarity"] == "active_low"
