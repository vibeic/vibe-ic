"""L1 directional-prose port extractor — ports stated as a bullet list under
an `Inputs:`/`Output(s):`/`Inout:` heading, in the two forms the
`markdown_bullet_under_heading` walker misses:
  (1) `- [7:0] in: ...`   width-PREFIX before the name
  (2) `- **i_S**: ...`     markdown-BOLD name

Diagnosed in the CVDP convergence run: 54% of blind authoring failures had an
EMPTY L1 pin_table because these forms were unextracted, so a blind RTL author
guessed the port name/case and the cocotb harness failed to bind. Direction
comes from the heading; width from the `[msb:lsb]` prefix or the heading
parenthetical ("1-bit width each"). Emitted via _add_pin (width-aware dedup),
so the new source never drops a port another extractor already found.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase1_doc_one_shot_runner as P1  # noqa: E402


def _by_name(rows):
    return {r["name"]: r for r in rows}


def test_width_prefix_form_under_bulleted_heading():
    # the cvdp_copilot_8x3_priority_encoder_0001 shape
    t = ("Design an 8x3 priority encoder.\n"
         "- Inputs:\n"
         "    - [7:0] in: An 8-bit input vector.\n"
         "- Output:\n"
         "    - [2:0] out: A 3-bit output vector.\n")
    r = _by_name(P1._l1_directional_prose_port_extract(t))
    assert set(r) == {"in", "out"}
    assert r["in"]["mode"] == "input" and r["in"]["width"] == "8"
    assert r["out"]["mode"] == "output" and r["out"]["width"] == "3"


def test_markdown_bold_name_form_with_heading_parenthetical_width():
    # the cvdp_copilot_flop_0001 shape
    t = ("#### Inputs (1-bit width each):\n"
         "- **i_S**: Set signal\n"
         "- **i_R**: Reset signal\n"
         "- **i_clk**: Clock signal\n"
         "#### Outputs (1-bit width each):\n"
         "- **o_Q**: Output\n")
    r = _by_name(P1._l1_directional_prose_port_extract(t))
    assert set(r) == {"i_S", "i_R", "i_clk", "o_Q"}
    assert r["i_S"]["mode"] == "input" and r["i_S"]["width"] == "1"
    assert r["o_Q"]["mode"] == "output" and r["o_Q"]["width"] == "1"
    # case is preserved EXACTLY (the harness-bind failure was case mismatch)
    assert "i_S" in r and "i_s" not in r


def test_plain_heading_and_backtick_name():
    t = ("Inputs:\n"
         "- `data_valid`: asserted when data is ready\n"
         "Outputs:\n"
         "- `result` [15:0]: the computed result\n")
    r = _by_name(P1._l1_directional_prose_port_extract(t))
    assert r["data_valid"]["mode"] == "input"
    assert r["result"]["mode"] == "output" and r["result"]["width"] == "16"


def test_prose_sentence_is_not_scraped():
    # a narrative paragraph mentioning inputs/outputs must yield NO ports
    t = ("Inputs are sampled on the rising edge of the clock and the "
         "output is registered one cycle later. The module processes the "
         "data and produces a result.\n")
    assert P1._l1_directional_prose_port_extract(t) == []


def test_stop_word_tokens_rejected():
    # a bullet whose 'name' is a heading/English stop word never qualifies
    t = ("- Inputs:\n"
         "    - description: this column explains each signal\n"
         "    - signal: the name of the port\n")
    assert P1._l1_directional_prose_port_extract(t) == []


def test_non_definition_bullet_rejected():
    # a bullet with no colon after the name is prose, not a port definition
    t = ("- Inputs:\n"
         "    - the design accepts an 8-bit operand and a valid strobe\n")
    assert P1._l1_directional_prose_port_extract(t) == []


def test_new_strategy_not_in_structured_set_so_never_displaces():
    # directional_prose_port is deliberately OUTSIDE the richer-promotion set
    # so on a name collision a structured-table/Verilog port always wins —
    # the new source can only ADD names or donate width via inheritance.
    assert "directional_prose_port" not in P1._STRUCTURED_PORT_STRATEGIES
    assert "markdown_bullet_under_heading" in P1._STRUCTURED_PORT_STRATEGIES


# ── directional-prose POST-CROSS-WALK FALLBACK (the zero-regression design) ──
# Prose is a WEAK source: it fills pin_table ONLY when it is STILL empty after
# the primary harvest AND the richer L9 mirror — so it can never shadow a
# richer source (the wb2ahb 21→10 / dot_product 13→11 class). It is applied in
# `_post_emit_crosswalk_l9_ports_to_l1_pin_table_v1_6_555`, NOT inside the
# per-file walk and NOT inside the cross-walk.

def _l9(*names):
    return [{"name": n, "direction": "input"} for n in names]


def _mk_proj(tmp_path, l1_pins, prompt):
    import json
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps(
        {"pin_table": l1_pins, "no_pin_table_in_input": not l1_pins}))
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "design_description.md").write_text(prompt)
    return tmp_path


def test_prose_fallback_fills_empty_pin_table(tmp_path):
    # empty L1 + no L9 + a directional-prose prompt → fallback fills it.
    import json
    proj = _mk_proj(tmp_path, [],
                    "Design X.\n- Inputs:\n    - [7:0] in: data\n"
                    "- Output:\n    - [2:0] out: code\n")
    P1._post_emit_crosswalk_l9_ports_to_l1_pin_table_v1_6_555(proj)
    pt = json.loads((proj / "phase1" / "generated_docs"
                     / "L1_DATASHEET.json").read_text())["pin_table"]
    names = {p["name"] for p in pt}
    assert names == {"in", "out"}
    assert all(p["extraction_strategy"] == "directional_prose_port"
               for p in pt)


def test_prose_fallback_never_touches_nonempty_pin_table(tmp_path):
    # a design that ALREADY has ports (richer source) is left EXACTLY as-is —
    # the zero-regression guarantee (wb2ahb 21→21, not 21→10).
    import json
    rich = [{"name": "adr_i", "mode": "input", "width": 32,
             "extraction_strategy": "rst_grid_interface_table"}]
    proj = _mk_proj(tmp_path, rich,
                    "Design Y.\n- Inputs:\n    - [7:0] in: data\n")
    P1._post_emit_crosswalk_l9_ports_to_l1_pin_table_v1_6_555(proj)
    pt = json.loads((proj / "phase1" / "generated_docs"
                     / "L1_DATASHEET.json").read_text())["pin_table"]
    assert [p["name"] for p in pt] == ["adr_i"]   # unchanged, prose NOT added


def test_crosswalk_does_not_overwrite_primary_harvest():
    # a genuine primary-walker L1 is NEVER overwritten/merged (behaviour
    # unchanged for every non-prose design — bounds the blast radius).
    l1 = {"pin_table": [
        {"name": "a", "mode": "input",
         "extraction_strategy": "rst_grid_interface_table"}]}
    changed = P1._v1_6_555_crosswalk_l9_ports_to_l1_pin_table(
        l1, _l9("a", "b", "c"))
    assert changed is False
    assert [p["name"] for p in l1["pin_table"]] == ["a"]


def test_crosswalk_fills_empty_l1_from_l9_unchanged():
    l1 = {"pin_table": []}
    changed = P1._v1_6_555_crosswalk_l9_ports_to_l1_pin_table(
        l1, _l9("x", "y"))
    assert changed is True
    assert {p["name"] for p in l1["pin_table"]} == {"x", "y"}
