#!/usr/bin/env python3
"""#czl9prompt — ONE port extractor, reached by BOTH Phase-1 front doors.

Measured on this base (8HD-8, next/czl9docs a9475c03), the SAME byte-identical
input declaring five ports, run through the two front doors:

    docs mode    Phase 1 rc 0, L9 five ports with direction, 554 chars of prose
    prompt mode  Phase 1 rc 1, FAIL: EXTRACTION GAP, L9 ports 0, prose 0

The refusal was CORRECT — an input that declares ports over L documents that
carry none is exactly the gap #czl9docs taught the runner to halt on — and the
outcome was still wrong: an ordinary prompt-mode design with a port list could
not get through Phase 1 at all.

The cause was two extractors for one job. The docs door called
`_l1_inline_direction_bullet_port_extract` (the bullet-states-its-own-direction
grammar, `- input clk`); the prompt door called `phase1_port_extract.extract`,
whose prose fallback is HEADING-anchored and returned [] on the same text.

The fix is not a third extractor. The docs door's implementation MOVED into
`phase1_port_extract` — the module the prompt door already called — and the
docs door imports it back. These tests pin that there is exactly ONE
implementation and that both doors reach it, so the two doors cannot drift
apart again by one of them learning a grammar the other does not.

chip-AGNOSTIC: Verilog direction grammar + Markdown list grammar only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import phase1_port_extract as PPX            # noqa: E402
import phase1_doc_one_shot_runner as DOCS    # noqa: E402
import phase1_one_shot_runner as PROMPT      # noqa: E402

_PORTFUL = (
    "Implement a framed serial receiver.\n"
    "\n"
    " - input  clk\n"
    " - input  rst\n"
    " - input  rx\n"
    " - output cmd_out (4 bits)\n"
    " - output frame_done\n"
    "\n"
    "`cmd_out` must be valid in the same clock cycle that `frame_done`\n"
    "asserts.\n")
_PORTLESS = (
    "This part decodes a framed byte stream. Each frame is one start bit, an\n"
    "8-bit payload and one stop bit. Consecutive frames are separated by at\n"
    "least three idle bit periods.\n")


# ── 1. ONE implementation, not two ────────────────────────────────────

def test_the_bullet_grammar_has_exactly_one_definition():
    """The docs door's name and the shared module's name must be the SAME
    function object. A copy would pass every behavioural test below on the day
    it was made and drift the day after."""
    shared = getattr(PPX, "extract_inline_direction_bullet_ports", None)
    assert shared is not None, (
        "phase1_port_extract must own the inline-direction bullet grammar — "
        "it is the module the PROMPT front door calls")
    assert DOCS._l1_inline_direction_bullet_port_extract is shared, (
        "the docs front door must DELEGATE to the shared implementation, not "
        "hold a second copy of it")


def test_the_interface_prose_emitter_has_exactly_one_definition():
    """L9's prose channel is filled by both doors from the same input, so its
    emitter is shared for the same reason the port grammar is."""
    for docs_name, shared_name in (
            ("_czl9_emit_interface_prose", "emit_interface_prose"),
            ("_czl9_declared_port_names", "declared_port_names"),
            ("_czl9_block_mentions_port", "block_mentions_port")):
        shared = getattr(PPX, shared_name, None)
        assert shared is not None, f"phase1_port_extract must own {shared_name}"
        assert getattr(DOCS, docs_name) is shared, (
            f"{docs_name} must delegate to phase1_port_extract.{shared_name}")


# ── 2. the prompt door's own extractor now reads the port list ────────

def test_extract_ports_reads_a_bullet_that_states_its_own_direction():
    got = [(p["name"], p["dir"]) for p in PPX.extract_ports(_PORTFUL)]
    assert got == [("clk", "input"), ("rst", "input"), ("rx", "input"),
                   ("cmd_out", "output"), ("frame_done", "output")], got


def test_extract_ports_carries_the_stated_width():
    widths = {p["name"]: p["width"] for p in PPX.extract_ports(_PORTFUL)}
    assert widths["cmd_out"] == 4, widths
    assert widths["clk"] == 1, widths


def test_a_portless_input_still_yields_no_ports():
    """The other direction. A behavioural specification that declares no
    interface must stay port-LESS: never default a port list."""
    assert PPX.extract_ports(_PORTLESS) == []


def test_prose_that_merely_mentions_a_direction_word_is_not_a_port():
    """Precision. A sentence is not a declaration, and this union must not
    have bought its ports by loosening that."""
    prose = ("- Input validation is performed by the host before the frame\n"
             "  is presented.\n"
             "- Output of the decoder feeds the command bus.\n")
    assert PPX.extract_ports(prose) == []


def test_the_higher_confidence_sources_still_win():
    """The bullet grammar joins the FALLBACK tier only. A design carrying a
    real interface table must be unaffected by it."""
    tabled = ("| Signal | Direction | Width |\n"
              "|--------|-----------|-------|\n"
              "| a_in   | input     | 8     |\n"
              "| y_out  | output    | 8     |\n"
              "\n"
              " - input  stray_bullet\n")
    got = [p["name"] for p in PPX.extract_ports(tabled)]
    assert got == ["a_in", "y_out"], got


# ── 3. the prompt door writes what it read into L9 ────────────────────

def _stub_project(tmp_path: Path, prompt: str) -> tuple:
    proj = tmp_path / "proj"
    (proj / "input").mkdir(parents=True)
    (proj / "input" / "phase1_prompt.md").write_text(prompt)
    out = proj / "phase1" / "generated_docs"
    out.mkdir(parents=True)
    # the shape the bundled engine really emits: bare NAME STRINGS, no
    # direction. Measured, not invented.
    (out / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(
        {"top_module": "input", "top_ports": ["clk"],
         "stub_origin": "_stub_l_docs_from_prose"}))
    (out / "L1_DATASHEET.json").write_text("{}")
    (out / "L8_RTL_CONSTANTS.json").write_text("{}")
    return proj, out


def test_the_prompt_door_seeds_l9_with_ports_that_carry_a_direction(tmp_path):
    proj, out = _stub_project(tmp_path, _PORTFUL)
    seeded = PROMPT._seed_structural_ports(proj, out)
    assert seeded == 5, seeded
    l9 = json.loads((out / "L9_INTEGRATION_SPEC.json").read_text())
    got = [(e["name"], e["direction"]) for e in l9["ports"]]
    assert got == [("clk", "input"), ("rst", "input"), ("rx", "input"),
                   ("cmd_out", "output"), ("frame_done", "output")], got
    assert [e["name"] for e in l9["top_ports"]] == [e[0] for e in got]


def test_the_prompt_door_fills_l9s_prose_channel_from_the_same_input(tmp_path):
    """A verdict over zero characters is the same shape as a verdict over zero
    ports. The prose channel must carry the input's own sentences."""
    proj, out = _stub_project(tmp_path, _PORTFUL)
    PROMPT._seed_structural_ports(proj, out)
    l9 = json.loads((out / "L9_INTEGRATION_SPEC.json").read_text())
    assert "frame_done" in (l9.get("notes") or ""), l9.get("notes")
    prov = l9.get("interface_prose_provenance") or {}
    assert prov.get("documents") == ["phase1_prompt.md"], prov
    assert prov.get("chars") == len(l9["notes"]), prov


def test_a_richer_l9_is_never_clobbered(tmp_path):
    """Only a STUB L9 is filled. An L9 that already carries structured ports
    keeps them, whatever this extractor would have said."""
    proj, out = _stub_project(tmp_path, _PORTFUL)
    rich = {"ports": [{"name": "already_here", "mode": "input",
                       "direction": "input"}]}
    (out / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(rich))
    PROMPT._seed_structural_ports(proj, out)
    l9 = json.loads((out / "L9_INTEGRATION_SPEC.json").read_text())
    assert [e["name"] for e in l9["ports"]] == ["already_here"]


def test_a_portless_prompt_leaves_l9_port_less(tmp_path):
    proj, out = _stub_project(tmp_path, _PORTLESS)
    assert PROMPT._seed_structural_ports(proj, out) == 0
    l9 = json.loads((out / "L9_INTEGRATION_SPEC.json").read_text())
    assert not [e for e in (l9.get("ports") or []) if isinstance(e, dict)]


# ── 4. the two doors agree about one input ────────────────────────────

def test_both_doors_read_the_same_ports_and_directions_from_one_input():
    """The invariant this lane is about, at the extractor level: whichever door
    a design comes through, the port MEMBERSHIP and the DIRECTIONS are the
    same. (The doors may still label provenance differently — they are
    different readers and say so.)"""
    docs = {(e["name"], e["mode"])
            for e in DOCS._l1_inline_direction_bullet_port_extract(_PORTFUL)}
    prompt = {(p["name"], p["dir"]) for p in PPX.extract_ports(_PORTFUL)}
    assert docs == prompt, {"docs": sorted(docs), "prompt": sorted(prompt)}


def test_the_prompt_doors_source_map_names_its_document(tmp_path):
    proj = tmp_path / "p"
    (proj / "input").mkdir(parents=True)
    (proj / "input" / "phase1_prompt.md").write_text(_PORTFUL)
    srcs = PROMPT._prompt_sources_for(proj)
    assert list(srcs) == ["phase1_prompt.md"], srcs
    assert srcs["phase1_prompt.md"] == _PORTFUL
    assert PROMPT._prompt_text_for(proj) == _PORTFUL
