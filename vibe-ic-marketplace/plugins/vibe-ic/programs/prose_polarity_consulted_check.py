#!/usr/bin/env python3
"""A prose extractor that never asks whether the sentence DENIES the value.

THIS GATE BLOCKS (rc=1) on a NEW one.

WHY (vibe-ic#712)
-----------------
It happened twice in one day, in two fields, found by the same activity —
retargeting a design from one process to another:

    #706  pdk_target          "This block is NOT targeted at <PDK>."
                              -> pdk_target = <PDK>, outranking the design's own
                                 labelled declaration three lines below.
    #711  die_area_budget_um  a document saying the old fixed die "has NO
                              meaning here and is REMOVED, not translated"
                              re-declared that exact rectangle as a mandate.

Neither is cosmetic. `die_area_budget_um` sits above `auto` in the phase-3
runner's documented precedence, so the design is hard-sized onto a die belonging
to a different chip — citing the design's own document as the authority. Nothing
warned; the floorplan read as declared rather than inherited.

WHAT IT MEASURES
----------------
Not "is this extractor correct" — that is a semantic question and a program that
guessed would produce confident wrong answers. It asks the structural one the
two defects share:

    a function that SEARCHES prose for a value and WRITES that value into a
    declared field, without ever consulting the polarity vocabulary.

A function is in scope when it both matches prose (a module-level `re` pattern
or an inline `re.search`/`findall` over a text argument) and assigns into a
record. It is CLEAN when it reaches `_prose_polarity` — directly, or through a
local alias of one of its names.

WHY NOT A LINT ON THE FIELD NAMES. Because the field is not the tell. Both
defects were in different fields, in different files, written by different
authors, weeks apart. What they share is the shape.

BASELINE, AND WHY IT MAY ONLY SHRINK
------------------------------------
Extractors that predate the vocabulary are recorded, not failed: failing a
pre-existing pile on day one is how a gate ends up switched off, and this repo
has measured that. Anything NEW fails from the first run.

A SHRINK IS A PASS, AND THE COUNT GUARD IT USED TO NAME WAS LAUNDERING
----------------------------------------------------------------------
An extractor that learns to consult polarity makes the register TOO BIG, and
this gate used to answer that with "Re-run with --write-baseline". MEASURED on
the tree this paragraph was written against, that instruction was live
laundering: the population read `polarity-blind 213 (baseline 213)` while
`spec_numeric_pack_extract::_detect_rounding_modes` had LEFT the set and
`_area_unit::liberty_areas` had JOINED it, and the write path's only guard was

    if prev and len(now) > len(prev): refuse

a COUNT. Running the flag the gate had just recommended exited 0 and recorded
the brand-new offender as accepted debt at unchanged size 213 — no size moved,
so nothing looked wrong to a reader either. `flow_gate_enforcement_audit` had
removed this exact hole from itself under vibe-ic#900 ("RATCHET ON MEMBERSHIP,
NOT ON COUNT"); this gate still carried it.

It is a membership test now, and a tightening is recorded by `--record-shrink`,
which writes `previous & current` and cannot add — see `_ratchet_baseline`. The
verdict path never writes: the hygiene suite runs inside the whole-repo
`suite_write_guard` bracket at `tools/gatekeeper-land.sh:690`, which blocks on
any tracked write.

chip-AGNOSTIC: pure AST structure. No chip, PDK, vendor or field literal.

USAGE
-----
    prose_polarity_consulted_check.py [--root .] [--json OUT]
                                      [--record-shrink | --write-baseline]

    exit 0 = no NEW polarity-blind extractor, and the baseline has not grown
    exit 1 = a new one, or the baseline grew (BLOCKING)
    exit 2 = could not be determined — never a vacuous pass
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ratchet_baseline as _ratchet  # noqa: E402

_BASELINE_NAME = "prose_polarity_baseline.json"
_POLARITY_MODULE = "_prose_polarity"
#: The names that ARE consulting polarity. A local alias of any of them counts —
#: both existing callers import under their own name, which is fine.
_POLARITY_NAMES = {
    "is_denied", "NEGATION_RE", "DENIAL_CORE_RE", "DENIAL_RETIRED_RE",
    "blank_bracketed", "sentence_scope",
}
#: Calls that read prose.
_SEARCH_ATTRS = {"search", "findall", "finditer", "match", "fullmatch"}

#: NOT PROSE — the input is a FORMAL GRAMMAR with no negation form.
#:
#: This is not the baseline and must never become one. The baseline is a debt
#: register of extractors that SHOULD consult polarity and do not; this is the
#: much narrower claim that the question does not arise, because the text being
#: read is machine-written syntax in which "not" cannot be spelled. Consulting
#: `_prose_polarity` there would add a call that can never fire, and a call that
#: can never fire is a green light rather than a check.
#:
#: Every entry pays for itself twice:
#:   * the reason must be a real argument (>= _EXEMPT_REASON_MIN chars), and
#:   * `main` FAILS if an exempted function has gone away or has stopped being
#:     polarity-blind — so the set cannot rot into a waiver list, and cannot be
#:     padded with names that were never findings.
#: The count is printed on every run, clean or not.
_EXEMPT_REASON_MIN = 80
_NOT_PROSE: Dict[str, str] = {
    "pdk_via_patch_legalize::_routing_rules":
        "Technology-LEF `LAYER <name> ... TYPE ROUTING ; MINWIDTH <n> ; WIDTH "
        "<n> ; AREA <n> ; END <name>` productions, read out of the PDK's own "
        "tech LEF to learn each routing layer's width and area floors before a "
        "via patch is legalised. These are formal foundry grammar written by "
        "the PDK packaging, in which there is no form that DENIES a rule: LEF "
        "gives no way to write 'MINWIDTH is NOT 0.14'. A rule is present in the "
        "layer body or it is absent, and absence is already how this function "
        "reports it (the layer simply does not enter the returned map; a layer "
        "that is not TYPE ROUTING is skipped by name). The direct precedents "
        "are `digital_hardmacro_gen::discover_stdcell_rails` (LEF MACRO/SIZE/"
        "PIN/LAYER/RECT) and `phase3_one_shot_runner::_pdn_em_width_floor` "
        "(LEF MANUFACTURINGGRID), the same file format exempted for the same "
        "stated reason. The two defects this gate was built from (#706 "
        "pdk_target, #711 die_area_budget_um) both read English design "
        "documents, where denial is spellable and was spelled; consulting "
        "`_prose_polarity` on a tech-LEF layer body would add a branch that "
        "can never fire. Flagged by the v1.15.43/46 landings (vibe-ic#2010 "
        "item 6) and recorded here rather than papered over with a dead call.",
    "pdk_via_patch_legalize::_legalize_generate_rules":
        "Technology-LEF `VIARULE <name> GENERATE ... LAYER <l> ; RECT ... ; "
        "ENCLOSURE <x> <y> ; END <name>` productions: the generated-via rules "
        "whose routing-layer enclosures this function grows to the layer's "
        "width/area floors. The matched text is formal foundry grammar written "
        "by the PDK packaging, in which there is no form that DENIES an "
        "enclosure or a cut rectangle: LEF gives no way to write 'ENCLOSURE is "
        "NOT 0.06 0.06'. An unresolvable rule (no single cut layer, or an "
        "unterminated VIARULE) is already DISCLOSED by name in the returned "
        "`unresolved` list and left byte-identical, so a rule this reader could "
        "not read is never rewritten. Same class as `_routing_rules` above and "
        "as `macro_obs_geometry_intersect_check::parse_via_layers` (DEF VIAS "
        "LAYERS), exempted for the same stated reason. The two defects this "
        "gate was built from (#706 pdk_target, #711 die_area_budget_um) both "
        "read English design documents, where denial is spellable and was "
        "spelled; consulting `_prose_polarity` on a VIARULE body would add a "
        "branch that can never fire. Flagged by the v1.15.43/46 landings "
        "(vibe-ic#2010 item 6).",
    "_ic_release_artefacts::_def_class":
        "Routed DEF UNITS, DIEAREA and COMPONENTS productions. DEF has no syntax "
        "for denying one of these declarations; the value is present in the "
        "machine grammar or absent, and this reader reports absence explicitly.",
    "_ic_release_artefacts::_def_pins":
        "Routed DEF PINS entries and their USE attributes. These are formal DEF "
        "grammar productions, not natural-language claims; a pin or USE field "
        "cannot be negated by prose surrounding the matched declaration.",
    "design_one_shot_runner::step_full_stack_tb_gen":
        "Generated Verilog named-port connection syntax is parsed from the "
        "runner-owned testbench skeleton. The matched `.name(` token is an HDL "
        "grammar production and Verilog has no prose form that denies it.",
    "digital_hardmacro_gen::_specialnet_entries":
        "Routed DEF SPECIALNETS entries and USE attributes are machine-written "
        "grammar. A special-net entry either exists or does not; DEF provides no "
        "natural-language denial form for the parser to consult.",
    "digital_hardmacro_gen::discover_stdcell_rails":
        "LEF MACRO, SIZE, PIN, USE, LAYER and RECT productions are formal foundry "
        "grammar. None can be denied by neighbouring prose, so polarity on these "
        "machine tokens would be an unreachable branch.",
    "digital_hardmacro_gen::run":
        "The matched value is the DESIGN production in the routed DEF chosen for "
        "hard-macro packaging. It is formal DEF syntax, not a prose assertion, "
        "and absence is already a loud refusal in this producer.",
    "em_current_density_check::_def_pg_widths_of":
        "DEF UNITS and SPECIALNETS ROUTED/NEW wire productions are formal layout "
        "grammar. Width tokens cannot be negated in that grammar; missing or "
        "unreadable declarations already produce an empty measured authority.",
    "pdk_analog_characterize::simulator_provenance":
        "The scan reads ngspice's machine/tool version banner, not a design "
        "document. A version token has no surrounding natural-language denial "
        "whose polarity could change the provenance value.",
    "phase3_one_shot_runner::_pdn_em_width_floor":
        "The matches read machine-produced EM report fields plus the LEF "
        "MANUFACTURINGGRID production. These formal measurement grammars cannot "
        "deny their numeric tokens in surrounding prose.",
    "release_docs_check::_parameter_values":
        "SystemVerilog parameter declarations are formal HDL grammar. A parameter "
        "is declared with an expression or is absent; HDL has no prose denial "
        "form that could reverse the extracted integer value.",
    "release_docs_check::constraint_ids":
        "The matcher reads the repository's mandatory-constraint row grammar, "
        "whose identifier and text fields are explicitly delimited. It is a "
        "machine document production, not free prose from which a value is inferred.",
    "crosslayer_rewrite_equivalence::module_ports":
        "Verilog/SystemVerilog module port declarations. The matched text is a "
        "production of the HDL grammar — `module m(input wire [7:0] a, ...)` in the "
        "ANSI form and `module m(a, b); input [7:0] a;` in the non-ANSI form — "
        "written by a synthesis-bound source file, in which there is no form that "
        "DENIES a port: Verilog gives no way to write 'a is NOT an input'. A port "
        "either appears in a declaration or it does not, and absence is already how "
        "this function reports it (the name is simply not in the returned list, and "
        "the caller turns an empty list into NOT_MEASURED rather than into an "
        "empty-but-fine wrapper). This is the same class as the already-exempted "
        "digital_hardmacro_gen::read_interface and _pad_ring::parse_def. The two "
        "defects this gate was built from (#706 pdk_target, #711 die_area_budget_um) "
        "both read English design documents, where denial is spellable and was "
        "spelled; consulting `_prose_polarity` on a port list would add a branch "
        "that can never fire, and a call that can never fire is a green light "
        "rather than a check.",
    "macro_obs_geometry_intersect_check::parse_via_layers":
        "LEF/DEF 5.8 VIAS section. The matched text is `- <viaName> ... "
        "+ LAYERS <lower> <cut> <upper> ;` — a production of the DEF grammar, "
        "emitted by the router, in which there is no form that DENIES a via's "
        "layer pair: DEF gives no way to write 'this via does NOT connect MET1 "
        "and MET2'. The two defects this gate was built from (#706 pdk_target, "
        "#711 die_area_budget_um) both read English design documents, where "
        "denial is spellable and was spelled. Consulting `_prose_polarity` on "
        "a VIAS entry would be an unreachable branch.",
    "input_doc_pdk_claim_vs_installed_pdk_check::_sections_of":
        "SPICE `.lib` section directives inside a PDK corner library. The "
        "matched text is `^\\s*\\.lib\\s+(NAME)\\s*$` -- a production of the "
        "ngspice/SPICE library grammar, written by the foundry's model "
        "packaging, in which there is no form that DENIES a section: SPICE "
        "gives no way to write '.lib mos_tt is NOT defined here'. A section "
        "either appears as a directive or it does not, and absence is already "
        "how this function reports it (the name is simply not in the returned "
        "list). The values written back are those section NAMES, quoted into "
        "the gate's evidence so a reader can re-derive the vocabulary from the "
        "same file -- they are never read as an assertion that could be "
        "negated by surrounding text. Consulting `_prose_polarity` on a `.lib` "
        "directive would add a branch that can never fire, and a call that can "
        "never fire is a green light rather than a check. Contrast the two "
        "defects this gate was built from (#706 pdk_target, #711 "
        "die_area_budget_um): both read English design documents, where denial "
        "is spellable and was spelled -- which is exactly what "
        "vibe-ic#904 is about on the OTHER side of this same gate, where the "
        "CLAIM text is prose and is parsed by the claim scanner, not here.",
    "phase3_one_shot_runner::density_counted_specs":
        "Two machine-written grammars, neither of which can spell a denial. "
        "The first is a LEF/DEF streamout layermap row -- `<lefname> "
        "<purpose> <gdslayer> <gdsdatatype>`, whitespace-separated columns "
        "emitted by the foundry's streamout packaging or by this runner's own "
        "`_synthesize_streamout_layermap`; there is no form in it that says "
        "'met1 FILL is NOT on 68/36'. The second is the KLayout DRC layer "
        "binding `NAME = input(L, D)` / `polygons(L, D)`, a production of the "
        "deck's Ruby DSL, in which a layer is bound or it is not -- a deck "
        "cannot write 'this is NOT layer 68 datatype 36'. Absence is already "
        "how both halves report it: an unmatched row or an unmatched binding "
        "simply does not enter `counted`, and the report publishes the "
        "resulting spec list plus `specs_from_layermap` / `specs_from_deck` "
        "counts so a reader can see exactly what was and was not found. "
        "Nothing here is read as an assertion that surrounding text could "
        "negate. There is also a hard reason it CANNOT consult the module: "
        "this function's source is injected verbatim into the KLayout batch "
        "recipe (`_metal_density_recipe`) and executed inside the container "
        "under KLayout's own interpreter, which has no path to "
        "`_prose_polarity` -- so the call would not merely be unreachable, it "
        "would not import. Contrast the two defects this gate was built from "
        "(#706 pdk_target, #711 die_area_budget_um): both read English design "
        "documents, where denial is spellable and was spelled.",
    "pytest_per_file_junit::_admit":
        "Progress-stream FILENAMES in a parent-owned directory. The matched "
        "text is ONE POSIX path component, minted by this repo's own "
        "`_pytest_progress_plugin.pytest_configure` in exactly two forms -- "
        "`m.<pid>.<ppid>.jsonl` and `w.<workerid>.<pid>.<ppid>.jsonl` -- and "
        "both patterns are anchored `\\A...\\Z`, so the ENTIRE subject IS the "
        "token: there is no surrounding text for a denial to live in, and a "
        "path component has no form that says 'this stream is NOT from pid "
        "41'. A name that does not match is not ignored, it REFUSES the whole "
        "set (`unexpected file in progress directory`), so absence is already "
        "reported more strictly than any polarity branch could report it. "
        "What the function writes -- `self.streams[name]` and "
        "`self.kinds[name]` -- is a demultiplexing key for an open probe, not "
        "a value published as a declaration that a neighbouring sentence "
        "could retract; and the one claim the name does carry, the owning "
        "pid, is not believed either -- it is re-checked against the launched "
        "process and a mismatch refuses the set. Contrast the two defects "
        "this gate was built from (#706 pdk_target, #711 die_area_budget_um): "
        "both read English design documents, where denial is spellable and "
        "was spelled. Consulting `_prose_polarity` on a directory entry would "
        "add a branch that can never fire, and a call that can never fire is "
        "a green light rather than a check.",
    "_pad_ring::parse_def":
        "LEF/DEF 5.8 UNITS / DIEAREA / COMPONENTS records. The matched text is "
        "`UNITS DISTANCE MICRONS <n> ;`, `DIEAREA ( x y ) ( x y ) ;` and the "
        "COMPONENTS entry form `- <inst> <master> + PLACED ( x y ) <orient> ;` "
        "-- productions of the DEF grammar emitted by the floorplanner, in "
        "which there is no form that DENIES a placement: DEF gives no way to "
        "write 'this instance is NOT placed at ( 0 0 )'. A record that is "
        "absent is already reported as absent -- a missing UNITS or DIEAREA "
        "RAISES DefError rather than defaulting -- so absence is refused, not "
        "silently read as a value. The two defects this gate was built from (#706 pdk_target, #711 die_area_budget_um) both read English design documents, where denial is spellable and was spelled.",
    "_pad_ring::parse_lef_macros":
        "LEF 5.8 MACRO / SIZE records. The matched text is `MACRO <name>` and "
        "`SIZE <w> BY <h> ;`, productions of the LEF grammar emitted by the "
        "PDK's own cell library, in which there is no form that DENIES a "
        "footprint: LEF gives no way to write 'this macro is NOT 30 BY 180'. "
        "A MACRO carrying no SIZE simply does not enter the returned map, so "
        "absence is reported by absence rather than by a negated value, and "
        "the body of each macro is bounded at its own END so no neighbouring "
        "text can lend it one. The two defects this gate was built from (#706 pdk_target, #711 die_area_budget_um) both read English design documents, where denial is spellable and was spelled.",
    "_pad_ring::parse_lef_sites":
        "LEF 5.8 SITE declarations. The matched text is the top-level `SITE "
        "<name>` form with its CLASS and SIZE, a production of the LEF grammar "
        "emitted by the PDK, in which there is no form that DENIES a site: LEF "
        "gives no way to write 'this site is NOT CORE'. The function already "
        "distinguishes the two syntactic roles the same keyword plays -- a "
        "top-level SITE that DECLARES one, versus the `SITE <name> ;` "
        "reference inside a MACRO that only names one -- which is a grammar "
        "question, not a polarity question. The two defects this gate was built from (#706 pdk_target, #711 die_area_budget_um) both read English design documents, where denial is spellable and was spelled.",
    "digital_hardmacro_check::parse_lef":
        "LEF 5.8 MACRO / SIZE / ORIGIN / PIN records read as the delivered "
        "abstract's interface. Every matched token is a production of the LEF "
        "grammar written by Magic's LEF writer, in which there is no form that "
        "DENIES a pin: LEF gives no way to write 'this macro does NOT have a "
        "pin named clk'. A pin that is not declared is not in the returned "
        "set, and the gate's verdict is built from the DECLARATION being "
        "present, never from a bad token being absent. The two defects this gate was built from (#706 pdk_target, #711 die_area_budget_um) both read English design documents, where denial is spellable and was spelled.",
    "lec_post_layout_check::_parse_netlist_instances":
        "Structural gate-level Verilog `<cell> <instance> ( .<pin>(<net>), ... "
        ");` instantiations read out of the synth/PnR netlists yosys and "
        "OpenROAD wrote, to learn which nets each cell pin carries on the gold "
        "and gate sides of the post-layout LEC (the pin-permutation re-proof, "
        "round 3 2026-09-02). Netlist syntax is a formal grammar with no form "
        "that DENIES a connection: a port is connected to a net or the "
        "instance does not name it, and absence is how this function reports "
        "it (the pin is simply missing from the returned map, which the "
        "classifier then REJECTS as 'not a permutation'). Same class as "
        "`_pad_ring::parse_def` and `crosslayer_rewrite_equivalence::"
        "module_ports`, exempted for the same stated reason.",
    "lec_post_layout_check::_parse_liberty_pins":
        "Liberty `cell (<name>) { pin(<name>) { direction : <d>; function : "
        "\"<expr>\"; } }` groups read out of the PDK's timing view, to learn "
        "each cell's input/output pins and output functions for the truth-"
        "table symmetry test of the pin-permutation re-proof (round 3 "
        "2026-09-02). The matched text is a production of the Liberty grammar "
        "emitted by the characterisation tool, in which there is no form that "
        "DENIES a pin or a function; a pin without a direction is skipped and "
        "an output without a function is recorded as None, which the "
        "classifier REJECTS ('no Liberty function'). Direct precedent: "
        "`digital_hardmacro_check::parse_liberty`, the same file format "
        "exempted for the same stated reason.",
    "digital_hardmacro_check::parse_liberty":
        "Liberty `cell` / `pin` / `pg_pin` groups read as the timing view's "
        "interface. The matched text is a production of the Liberty grammar "
        "emitted by the characterisation tool, in which there is no form that "
        "DENIES a pin. This function is already built around exactly the "
        "hazard polarity guards against, one level lower: it STRIPS COMMENTS "
        "FIRST and requires the DECLARATION to be present, because "
        "`analog_hardmacro_check` recorded a Liberty containing only `/* the "
        "release was cancelled */` satisfying a bare `\"cell\" in text` test "
        "on the letters inside the word cancelled. The two defects this gate was built from (#706 pdk_target, #711 die_area_budget_um) both read English design documents, where denial is spellable and was spelled.",
    "_area_unit::liberty_areas":
        "Liberty `cell (<name>) {` group headers and the `area : <float>;` "
        "attribute inside each group. The matched text is a production of the "
        "Liberty grammar emitted by the characterisation tool, in which there "
        "is no form that DENIES a cell's area: Liberty gives no way to write "
        "'this cell's area is NOT 1.064'. The direct precedent is "
        "`digital_hardmacro_check::parse_liberty` above -- the SAME file "
        "format, exempted for the same stated reason. Absence is already how "
        "this function reports it: a `cell` group carrying no `area` simply "
        "does not enter the returned map, and each cell's block is bounded by "
        "the NEXT cell header so no neighbouring group can lend it one. The "
        "number is not even believed on its own -- `derive` exists precisely "
        "because a Liberty area carries no declared unit, so every value this "
        "function returns is cross-checked against the same cell's LEF `SIZE` "
        "footprint, a disagreeing distribution REFUSES rather than publishes, "
        "and fewer than MIN_CELLS comparable cells refuses too. Contrast the "
        "two defects this gate was built from (#706 pdk_target, #711 "
        "die_area_budget_um): both read English design documents, where denial "
        "is spellable and was spelled. DISCLOSED, because this entry is where "
        "it belongs: `lef_footprints_um2` in this same module reads LEF the "
        "same formal way and is the same class, but the scan does NOT flag it "
        "-- `_match_derived_names` skips any assignment whose target is not a "
        "bare Name, so the tuple `w, h = float(s.group(1)), float(s.group(2))` "
        "breaks the taint and `out[m.group(1)] = w * h` names nothing derived. "
        "Splitting that one line into two Name assignments makes the scan flag "
        "it (measured). It cannot be listed here while that holds, because "
        "`exemption_audit` FAILS on an exempted name the scan does not flag -- "
        "which is the audit working, not a hole: the set may not be padded "
        "with names that were never findings.",
    "digital_hardmacro_gen::read_interface":
        "The DEF PINS section. The matched text is the entry form `- <pinName> "
        "+ NET <net> + DIRECTION <dir> + USE <use> ;` -- a production of the "
        "DEF grammar emitted by the place-and-route tool, in which there is no "
        "form that DENIES a pin's direction or USE class: DEF gives no way to "
        "write 'this pin is NOT POWER'. The USE scan deliberately reuses the "
        "SAME entry split as the shared `parse_def_pins` reader so the two "
        "cannot disagree about what an entry is, and a pin carrying no USE "
        "records the empty string rather than guessing a class. The two defects this gate was built from (#706 pdk_target, #711 die_area_budget_um) both read English design documents, where denial is spellable and was spelled.",
    "crosslayer_rewrite_equivalence::module_ports":
        "A Verilog-2005 / SystemVerilog MODULE HEADER. The matched text is "
        "`module <name> #(...) (...) ;` and, inside it, the port declaration "
        "form `input|output|inout [wire|reg|logic] [signed] [<range>] <name>` "
        "-- productions of the HDL grammar, in which there is no form that "
        "DENIES a port: Verilog gives no way to write 'this module does NOT "
        "have an input named clk'. What the function returns is not a claim "
        "about the design read out of a sentence; it IS the module's "
        "interface, the same text the frontend elaborates, and the frontend "
        "-- not a neighbouring comment -- is what decides whether the port "
        "exists. A comment reading `// b is not used` leaves `b` in the "
        "elaborated interface, so honouring it would make this reader "
        "disagree with the compiler that consumes the wrapper it builds. A "
        "module that is not found returns [] and the caller turns that into "
        "NOT_MEASURED rather than an empty-but-fine wrapper, so absence is "
        "refused rather than read as a value. The two defects this gate was "
        "built from (#706 pdk_target, #711 die_area_budget_um) both read "
        "English design documents, where denial is spellable and was spelled; "
        "the direct precedents here are `digital_hardmacro_gen::read_interface` "
        "(DEF PINS) and `digital_hardmacro_check::parse_lef` above.",
    # `benchmark_io_adapter::cvdp_package_response` WAS EXEMPTED HERE, and the
    # entry was deleted (not moved) when 5555901e0 refactored it. That function
    # matched `module <name> ... endmodule` itself and stored the module's own
    # bytes; the argument for the exemption was that an HDL grammar production
    # has no form that DENIES a module, over an input whose comments and string
    # literals `_hdl_code_text.strip_hdl_comments_and_strings` had already
    # blanked. The scan HAS NOT STOPPED being right about that text — the text
    # left this function. The regex now lives in
    # `rtl_final_bundle_integrity::module_blocks`, which returns a list
    # comprehension and assigns into no record, so it is not in this gate's
    # scope and an exemption for it would be the same dead entry one file
    # along. Verified on the tree that deleted this: `scan()` names neither
    # `benchmark_io_adapter::cvdp_package_response` nor
    # `rtl_final_bundle_integrity::module_blocks`. `exemption_audit` is what
    # forced the choice, by design: it FAILS on an exempted name the scan does
    # not flag, so the set can only ever change size deliberately.
    "transition_fault_atpg_run::unresolved_cell_types":
        "A gate-level Verilog netlist WRITTEN BY YOSYS, read to answer whether "
        "`read_liberty` + `flatten` actually levelised the cut. THE ARGUMENT "
        "IS ABOUT THE WRITER, NOT ABOUT VERILOG, and the difference matters. "
        "The usual claim in this register -- 'the grammar has no negative "
        "form' -- is NOT sufficient here and is deliberately not made: Verilog "
        "does have COMMENTS, a comment is exactly where a denial would live, "
        "and MEASURED on this function before the reader was repaired, "
        "`/* NOT in the design, REMOVED, not translated: and3_1 _392_ ( */` "
        "and a live `and3_1 _392_ (` returned the BYTE-IDENTICAL {'and3_1': 1}. "
        "What makes the question not arise is that no such comment can reach "
        "this reader. Yosys's frontend DISCARDS every comment its input "
        "carried, so nothing an author wrote survives into the output -- "
        "measured on the flow's own container image (yosys 0.68+) and on a "
        "host yosys 0.9: a cut netlist carrying that denial around a fake "
        "instantiation produced a flat core holding no trace of either the "
        "sentence or the instance. The only comments in the file are yosys's "
        "OWN: the one-line `Generated by Yosys <version>` banner, and the "
        "inline `/* <name> */` it writes between a cell type and its instance "
        "name (recorded by `synth_netlist_check` at v0.1.32 as "
        "`$_DFF_PN0_ /* _04_ */ s4_reg (`). Both are machine-minted "
        "identifiers and a version string; neither is a statement that can "
        "deny an instantiation. AND THE ENTRY DOES NOT REST ON THAT TOOL "
        "BEHAVIOUR, which is what makes it falsifiable rather than an "
        "allowlist: `unresolved_cell_types` now blanks comments itself via "
        "`strip_comments`, so the classification holds whoever wrote the file. "
        "Delete that blanking and the claim made here stops being true, and "
        "`test_a_denied_instantiation_is_not_counted` in "
        "`test_dt1_tool_crash_is_not_a_coverage_number` goes RED naming this "
        "entry -- the instruction there is to delete this entry, not to relax "
        "the test. The blanking is also a repair in its own right, in the "
        "opposite direction: a cell hidden behind yosys's inline comment used "
        "to read as ABSENT, so an UNLEVELISED core passed the post-condition "
        "and the ATPG died later inside `sat`, which is the crash this guard "
        "exists to stop being rendered as a coverage number. Contrast the two "
        "defects this gate was built from (#706 pdk_target, #711 "
        "die_area_budget_um): both read English design documents, where denial "
        "is spellable and was spelled.",
}


def _aliases(tree: ast.Module) -> Set[str]:
    """Local names bound to something from the polarity module."""
    out: Set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and (n.module or "").endswith(_POLARITY_MODULE):
            for a in n.names:
                out.add(a.asname or a.name)
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name.endswith(_POLARITY_MODULE):
                    out.add(a.asname or a.name)
    return out


def _searches_prose(fn: ast.AST) -> bool:
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            if n.func.attr in _SEARCH_ATTRS:
                return True
    return False


#: Modules whose `.compile` mints a PATTERN. Kept to the two spellings that
#: exist in this corpus rather than `attr == "compile"` on anything, so an
#: unrelated `x = obj.compile(...)` cannot borrow the exclusion.
_PATTERN_FACTORY_MODULES = {"re", "regex"}


def _is_compiled_pattern(value: ast.AST) -> bool:
    """`re.compile(...)` -- the INSTRUMENT that reads prose, not a value read
    out of prose.

    A `re.Pattern` is never a declared value taken out of a sentence, whatever
    was concatenated to build it, and no sentence can deny one. Both real
    defects (#706 `pdk_target`, #711 `die_area_budget_um`) wrote the matched
    TEXT into a declared field; memoising the searcher is keeping a tool.

    Without this, a word-boundary helper that caches its own pattern --

        left = r"(?<![A-Za-z0-9_])" if re.match(r"[A-Za-z0-9_]", token) else ""
        pat  = re.compile(left + re.escape(token) + right)
        _CACHE[token] = pat

    -- reads as an extractor publishing a declared value, because the `re.match`
    in the CONDITION marks `left` match-derived and `pat` inherits it. The text
    that goes INTO a pattern is still tracked: an extractor that compiles a
    pattern AND writes the matched text is unchanged, which is pinned by test.

    MEASURED on this corpus before it was written: this removes exactly ONE
    name from the 217 the predicate returns, `policy_direction_pin_check::_names`,
    and no other. Two wider narrowings were built first and REJECTED on the same
    measurement -- dropping the test of a conditional expression also dropped
    `parametric_spec_extractor::extract_arithmetic`, whose
    `"saturate" if re.search(r"saturat", text) else ...` is the #706 defect
    exactly; and excluding slice bounds also dropped
    `l22_checklist_milestone_emit::extract_milestones`, which publishes a
    document's own resolution column. Both are findings, not noise.
    """
    return (isinstance(value, ast.Call)
            and isinstance(value.func, ast.Attribute)
            and value.func.attr == "compile"
            and isinstance(value.func.value, ast.Name)
            and value.func.value.id in _PATTERN_FACTORY_MODULES)


def _match_derived_names(fn: ast.AST) -> Set[str]:
    """Locals bound to a regex match or to text taken out of one.

    `m = RE.search(t)`, `hits = RE.findall(t)`, `val = m.group(1)`, and one hop
    onward (`val = raw.strip()`), which is how both real defects were written.
    A local bound to `re.compile(...)` is NOT one of them -- see
    `_is_compiled_pattern`."""
    out: Set[str] = set()
    for _ in range(3):                       # transitive, cheaply bounded
        grew = False
        for n in ast.walk(fn):
            if not isinstance(n, ast.Assign) or len(n.targets) != 1:
                continue
            t = n.targets[0]
            if not isinstance(t, ast.Name):
                continue
            if _is_compiled_pattern(n.value):
                continue
            for sub in ast.walk(n.value):
                hit = (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                       and sub.func.attr in (_SEARCH_ATTRS | {"group", "groups", "groupdict"})) \
                    or (isinstance(sub, ast.Name) and sub.id in out)
                if hit and t.id not in out:
                    out.add(t.id); grew = True
                    break
        if not grew:
            break
    return out


def _writes_a_declared_value(fn: ast.AST) -> bool:
    """Does it write THE MATCHED VALUE into a record?

    NARROWED, and the narrowing is the work. "Any subscript assignment" caught
    592 functions — every one that greps something and fills a dict — which is
    noise, not disclosure, and a baseline of 592 records nothing. Both real
    defects have a tighter shape: the value taken OUT of the prose is the value
    written IN as the declaration. That is what is asked here.
    """
    derived = _match_derived_names(fn)
    if not derived:
        return False
    for n in ast.walk(fn):
        vals = []
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Subscript)
                                             for t in n.targets):
            vals = [n.value]
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr in ("setdefault", "update"):
            vals = list(n.args[1:]) + [k.value for k in n.keywords]
        for v in vals:
            for sub in ast.walk(v):
                if isinstance(sub, ast.Name) and sub.id in derived:
                    return True
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) \
                        and sub.func.attr in ("group", "groups", "groupdict"):
                    return True
    return False


def _consults_polarity(fn: ast.AST, aliases: Set[str]) -> bool:
    ok = _POLARITY_NAMES | aliases
    for n in ast.walk(fn):
        if isinstance(n, ast.Name) and n.id in ok:
            return True
        if isinstance(n, ast.Attribute) and n.attr in ok:
            return True
    return False


def scan(root: Path) -> List[str]:
    """`module::function` for every polarity-blind prose extractor."""
    found: List[str] = []
    for p in sorted((root / "programs").glob("*.py")):
        if p.stem.startswith("test_") or p.stem == Path(__file__).stem:
            continue
        try:
            tree = ast.parse(p.read_text(errors="replace"))
        except (OSError, SyntaxError):
            continue
        al = _aliases(tree)
        for n in ast.walk(tree):
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not (_searches_prose(n) and _writes_a_declared_value(n)):
                continue
            if _consults_polarity(n, al):
                continue
            found.append(f"{p.stem}::{n.name}")
    return sorted(set(found))


def exemption_audit(blind_incl_exempt: List[str], root: Path) -> List[str]:
    """Why each `_NOT_PROSE` entry is no longer earning its place, if any.

    An exemption that names a function which has been deleted, renamed, or has
    since started consulting polarity is dead weight that makes the set look
    larger than the argument behind it. Reported as a FAILURE, so the only way
    the set changes size is deliberately.

    SCOPED TO THE TREE BEING SCANNED. `--root` is pointed at synthetic trees by
    this gate's own tests and could be pointed at any checkout; an exemption
    whose module is simply not in THAT tree is out of scope, not stale. Judging
    it would make the gate's verdict depend on which tree it was aimed at, which
    is the property a gate must not have."""
    problems: List[str] = []
    live = set(blind_incl_exempt)
    for name, reason in sorted(_NOT_PROSE.items()):
        module = name.split("::", 1)[0]
        if not (root / "programs" / f"{module}.py").is_file():
            continue                       # not this tree's business
        if len(reason.strip()) < _EXEMPT_REASON_MIN:
            problems.append(f"{name}: reason is {len(reason.strip())} chars, "
                            f"under the {_EXEMPT_REASON_MIN} this set requires")
        if name not in live:
            problems.append(
                f"{name}: exempted, but the scan does not flag it — the "
                f"function is gone, renamed, or now consults polarity. Delete "
                f"the entry.")
    return problems


def exemptions_in_scope(root: Path) -> List[str]:
    """The `_NOT_PROSE` names whose module is present in this tree."""
    return sorted(n for n in _NOT_PROSE
                  if (root / "programs"
                      / f"{n.split('::', 1)[0]}.py").is_file())


def _load(p: Path) -> Optional[List[str]]:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    v = d.get("known") if isinstance(d, dict) else d
    return sorted(v) if isinstance(v, list) else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None)
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--write-baseline", action="store_true",
                    help="record the CURRENT set. Refused if that would ADD "
                         "any entry — a debt register is not a waiver list")
    ap.add_argument(_ratchet.RECORD_FLAG, dest="record_shrink",
                    action="store_true",
                    help="record a measured TIGHTENING: write `previous & "
                         "current`, which can only remove entries")
    a = ap.parse_args(argv)

    root = Path(a.root).resolve() if a.root else Path(__file__).resolve().parents[1]
    if not (root / "programs").is_dir():
        print(f"[CANNOT DETERMINE] prose_polarity_consulted: no programs/ under "
              f"{root}. NOT a pass.", file=sys.stderr)
        return 2

    now_all = scan(root)
    exempt_problems = exemption_audit(now_all, root)
    exempted = exemptions_in_scope(root)
    now = [n for n in now_all if n not in set(exempted)]
    bpath = Path(a.baseline) if a.baseline else root / "programs" / _BASELINE_NAME

    if a.write_baseline or a.record_shrink:
        prev = _load(bpath) or []
        # `--record-shrink` writes `previous & current`, a subset of `previous`
        # whatever this run measured. `--write-baseline` writes what this run
        # measured and is refused below if that ADDS anything — the membership
        # test the count guard here was not.
        record = _ratchet.shrunk(prev, now) if a.record_shrink else now
        left = _ratchet.departed(prev, record)
        if prev and a.record_shrink and not left:
            print(f"nothing to record: {bpath} already holds the tightened set "
                  f"({len(prev)} recorded)")
            return 0
        doc = {
            "_comment": "Prose extractors that never consult the polarity of "
                        "the sentence they read (vibe-ic#712). MAY ONLY "
                        "SHRINK. A denied value published as a declaration is "
                        "how a design gets hard-sized onto another chip's die "
                        "while citing its own document as the authority.",
            "known": record,
        }
        try:
            _ratchet.write_shrunk(bpath, doc,
                                  previous_by_register={"known": prev}
                                  if prev else {})
        except _ratchet.ShrinkRefused as exc:
            print(f"[FAIL] prose_polarity baseline: {exc}", file=sys.stderr)
            return 1
        if left:
            print(_ratchet.report_line("known", left, len(prev), len(record)))
        print(f"wrote {bpath} ({len(record)} recorded)")
        return 0

    base = _load(bpath)
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(
            {"polarity_blind": now, "baseline": base}, indent=2) + "\n")
    if base is None:
        print(f"[CANNOT DETERMINE] prose_polarity_consulted: no readable "
              f"baseline at {bpath}; {len(now)} extractor(s) are polarity-blind "
              f"and there is nothing to compare against. NOT a pass.",
              file=sys.stderr)
        return 2

    new = sorted(set(now) - set(base))
    gone = sorted(set(base) - set(now))
    print(f"  prose extractors that write a declared value: polarity-blind "
          f"{len(now)} (baseline {len(base)}); "
          f"{len(exempted)} exempted as formal grammar, not prose")
    for nm in exempted:
        print(f"     NOT PROSE  {nm}")
    if exempt_problems:
        print(f"\n[FAIL] {len(exempt_problems)} exemption(s) no longer carry "
              f"their argument:")
        for p in exempt_problems:
            print(f"   {p}")
        return 1
    if gone:
        # Reported, never failed, and never as an errand pointing at the flag
        # that would ALSO record this run's new offenders as accepted debt.
        # Sizes are the REGISTER's before and after: `len(now)` folds in any
        # arrival and would misreport the shrink on the run where both land.
        print(_ratchet.report_line("known", gone,
                                   len(base), len(base) - len(gone)))
        print(f"           now polarity-aware, so they no longer belong in the "
              f"register. Record it with:\n"
              f"           prose_polarity_consulted_check.py "
              f"{_ratchet.RECORD_FLAG}")
    if new:
        print(f"\n[FAIL] {len(new)} prose extractor(s) read a value out of a "
              f"sentence and write it as a declaration without asking whether "
              f"the sentence DENIES it:")
        for n in new:
            print(f"   {n}")
        print(f"\n  Consult `{_POLARITY_MODULE}` — one vocabulary, so the next "
              f"field does not\n  have to learn this the way `pdk_target` and "
              f"`die_area_budget_um` did.")
        return 1
    if len(now) > len(base):
        print(f"\n[FAIL] the set grew {len(base)} -> {len(now)} with no new "
              f"name — the baseline is stale.")
        return 1
    print(f"[PASS] prose_polarity_consulted: no extractor newly reads a value "
          f"without its polarity.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
