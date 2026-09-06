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
    "sparse_fsm_detect::_sparse_enum_types":
        "SYSTEMVERILOG `typedef enum` DECLARATION grammar, read to learn the "
        "state constants a design declared so #2067 can tell a sparse "
        "(Hamming-separated) encoding from an ordinary one. Both productions "
        "it matches are HDL syntax -- `typedef enum logic [N-1:0] { NAME = "
        "W'bBITS, ... } type_e;` and the sized based literals inside it -- and "
        "there is no form in that grammar that DENIES a constant: "
        "SystemVerilog gives no way to write `CTR_IDLE is NOT 5'b01110`. A "
        "constant is declared or it is absent, and ABSENT IS ALREADY HOW THIS "
        "FUNCTION REPORTS IT: the name never enters `states`, the type never "
        "enters the returned map, and a group that is too small or whose "
        "minimum pairwise Hamming distance is under the floor is simply not "
        "returned -- the caller then declares nothing sparse and the synth "
        "step emits its pre-#2067 byte-identical script. The one place natural "
        "language appears in this input is the comment block in which "
        "OpenTitan documents the encoding's Hamming histogram, and the "
        "function strips comments ITSELF before its first match, so no "
        "sentence reaches these regexes at all; a comment could not un-declare "
        "the enum the next line declares in any case. The direct precedents "
        "are the other HDL-declaration readers in this register, "
        "`testbench_gen::package_first_order` and "
        "`spec_conformance_check::_frame_contract_findings`. Falsifier: "
        "`test_issue2067_sparse_fsm_encoding_preserved.py"
        "::test_the_not_prose_claim_for_the_enum_reader_is_falsifiable`.",
    "spec_conformance_check::_frame_contract_findings":
        "VERILOG DECLARATION grammar. The only text this function searches "
        "ITSELF is `rtl_body`, with one `re.findall` over "
        "`\\b(?:reg|wire|logic)\\b ... (name)` to collect the design's internal "
        "signal names -- HDL declaration syntax, in which there is no form that "
        "DENIES a declaration: SystemVerilog gives no way to write `not wire "
        "x;`. A signal is declared or it is absent, and absent is already how "
        "this function reports it (the name never enters `internals`). "
        "THE PROSE IS NOT READ HERE. Every prose read is delegated to "
        "`_frame_contract.extract_frame_contract`, and THAT is where the real "
        "polarity defect lived and is fixed: measured on e1814e28d, `There is "
        "no 3 cycle latency between the input frame and the output valid` "
        "published `latency = exactly 3 cycles`, byte-identical to the "
        "affirmation, and this function then reported an ERROR against RTL for "
        "violating a bound the document had DENIED. `_frame_contract._denied` "
        "now consults `_prose_polarity.classify_denial` over the CLAUSE a bound "
        "belongs to -- not the sentence, because #2035's own fixture states a "
        "bound and then qualifies it in a semicolon-joined clause containing "
        "`is not`, and a sentence-wide check withdraws the bound that sentence "
        "just declared. Both directions are pinned by "
        "`test_a_denial_in_the_bounds_own_clause_publishes_no_bound` and "
        "`test_a_denial_qualifying_a_DIFFERENT_clause_keeps_the_stated_bound`. "
        "This entry records that the SCANNER's per-function question has no "
        "referent here, not that the question was waived.",
    "spice_correlation_check::parse_sta_corner_basis":
        "STA REPORT HEADER syntax, machine-written by the timing tool and read "
        "to learn which corner the path being correlated was produced at. Two "
        "productions are parsed and both are stamps, not sentences: the "
        "sectioning marker `=== SETUP corner: process=SS "
        "liberty=<path>.lib ===`, and the `OCV_DERATE_APPLIED early=<f> "
        "late=<f>` line. There is no form in that grammar that DENIES a value "
        "-- a report has no way to write `liberty is NOT ..._ss_125C_4v50.lib`. "
        "A stamp is emitted or it is absent, and ABSENT IS ALREADY HOW THIS "
        "FUNCTION REPORTS IT: `liberty` stays the empty string and "
        "`ocv_late_derate` stays None, which its own docstring binds the caller "
        "to treat as `decline to correlate rather than assume the active "
        "corner`. The one genuinely ambiguous input -- a multi-corner writer "
        "stamping TWO liberties into one section -- is likewise answered by "
        "REFUSAL and not by a guess: `declared_liberties` carries the whole set "
        "and `liberty` is answered only when exactly one was declared. So the "
        "polarity question has no referent here, and the failure mode it "
        "guards against (a denied value published as a declaration) cannot "
        "arise from a grammar whose only alternative to a value is silence. "
        "The direct precedents are the other tool-artefact readers in this "
        "register: `lec_post_layout_check::_parse_liberty_pins` and "
        "`phase3_one_shot_runner::_pdk_declared_routing_layers`.",
    "phase3_one_shot_runner::_pdk_declared_routing_layers":
        "Tcl `set ::env(NAME) \"value\"` productions, read out of the PDK's "
        "OWN shipped librelane/OpenLane flow config to learn the routing "
        "layer floors that PDK declares for itself. This is machine-written "
        "Tcl assignment syntax in which there is no form that DENIES a value: "
        "Tcl gives no way to write `set ::env(RT_MIN_LAYER) is NOT Metal2`. A "
        "key is assigned or it is unassigned, and unassigned is already how "
        "this function reports it -- the key simply does not enter `env`, the "
        "field does not enter the returned map, and the empty map is the LOUD "
        "outcome that makes the caller keep the floor it derived. The one "
        "sub-token this parser does drop, a trailing `;# comment` after a bare "
        "value, is dropped because it is Tcl COMMENT syntax, not because it "
        "might carry a negation -- and a comment cannot un-assign the "
        "variable the same line just set. The direct precedent is "
        "`pdk_via_patch_legalize::_routing_rules` immediately below: the same "
        "claim, about the same PDK, in the tech LEF's grammar instead of the "
        "flow config's.",
    "testbench_gen::package_first_order":
        "SystemVerilog `package <name>;` declarations and `<name>::` scope "
        "references, read to compile a package before the package that "
        "imports it -- `verilator --binary` is single-pass. This is HDL "
        "declaration grammar in which there is no form that DENIES a "
        "declaration: SystemVerilog gives no way to write `not package "
        "pkg_x;`. A package is declared or it is absent, and absent is already "
        "how the function reports it -- the name never enters `defines` and "
        "the file is ordered with the non-package files. The ONE construct "
        "that reads as a denial here is a COMMENT, and that is a lexical "
        "exclusion rather than a polarity word: it was a real defect, it is "
        "MEASURED and FIXED in the function itself by `_hdl_code_only`, and "
        "`test_a_commented_out_package_is_not_a_package.py` holds it there. "
        "Consulting `_prose_polarity` on `package pkg_x;` would add a branch "
        "that can never fire, which is a green light rather than a check.",
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
    "phase3_one_shot_runner::_def_specialnet_iterm_map":
        "Routed DEF SPECIALNETS terminal tuples, `- <net> ... ( <inst> <pin> ) "
        "... ;` productions written by the router. DEF has no form that DENIES a "
        "connection: a terminal is listed on a special net or it is not, and "
        "there is no neighbouring sentence that could take it back. Direct "
        "precedent, the SAME grammar exempted for the SAME stated reason: "
        "`digital_hardmacro_gen::_specialnet_entries` (DEF SPECIALNETS) and "
        "`macro_obs_geometry_intersect_check::parse_via_layers` (DEF VIAS). "
        "This function is if anything the stricter reader of the two: it "
        "DISCARDS numeric route-coordinate tuples and top-level PIN/`*` tuples "
        "rather than guessing, and a terminal named on two rails RAISES instead "
        "of letting the later LEC normalization pick one. Consulting "
        "`_prose_polarity` here would add a branch that can never fire, and a "
        "branch that can never fire is a green light rather than a check.",
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
    '_pad_ring::io_terminals':
        "A PDK's own `PAD_PLACE_IO_TERMINALS` Tcl list, `{<master> <pin>}` "
        'entries written by the PDK packaging. Tcl list syntax has no form '
        'that DENIES an entry: a master/pin pair is in the list or it is not, '
        'and an entry whose substitution this reader cannot resolve is '
        'SKIPPED by name rather than half-expanded. Same file family and same '
        'stated reason as `_pad_ring::parse_lef_macros` below. The two '
        'defects this gate was built from (#706 pdk_target, #711 '
        'die_area_budget_um) both read English DESIGN DOCUMENTS, where denial '
        'is spellable and was spelled; consulting `_prose_polarity` here '
        'would add a branch that can never fire.',
    '_pad_ring::parse_lef_macro_classes':
        'LEF `MACRO <name> ... CLASS <class> ; END <name>` productions. '
        "Formal foundry grammar: LEF gives no way to write 'this macro is NOT "
        "CLASS PAD INOUT'. A macro carrying no CLASS simply does not enter "
        'the returned map, which is already how absence is reported. Direct '
        'precedent: `_pad_ring::parse_lef_macros` and '
        '`digital_hardmacro_gen::discover_stdcell_rails`, the same file '
        'format exempted for the same stated reason. The two defects this '
        'gate was built from (#706 pdk_target, #711 die_area_budget_um) both '
        'read English DESIGN DOCUMENTS, where denial is spellable and was '
        'spelled; consulting `_prose_polarity` here would add a branch that '
        'can never fire.',
    '_pad_ring::parse_lef_pin_roles':
        'LEF `PIN <name> ... DIRECTION <d> ; USE <u> ; END <name>` '
        'productions. Formal foundry grammar with no denial form; a pin '
        "declaring neither is OMITTED rather than defaulted, because 'the LEF "
        "did not say' and 'the LEF said INPUT' are already kept apart by this "
        'reader. Same class as `parse_lef_macro_classes` above. The two '
        'defects this gate was built from (#706 pdk_target, #711 '
        'die_area_budget_um) both read English DESIGN DOCUMENTS, where denial '
        'is spellable and was spelled; consulting `_prose_polarity` here '
        'would add a branch that can never fire.',
    '_pad_ring::parse_liberty_pad_cells':
        'Liberty `cell (<name>) { pin (<name>) { direction : ...; function : '
        '...; is_pad : true; } }` attributes. Liberty is a machine-written '
        'timing/function grammar with no form that denies an attribute — an '
        'attribute is stated or absent, and this reader keeps `None` for '
        'absent. Direct precedent: `digital_hardmacro_check::parse_liberty`, '
        'the same file format exempted for the same stated reason. The two '
        'defects this gate was built from (#706 pdk_target, #711 '
        'die_area_budget_um) both read English DESIGN DOCUMENTS, where denial '
        'is spellable and was spelled; consulting `_prose_polarity` here '
        'would add a branch that can never fire.',
    'analog_a5_layout_emit::parse_cell':
        'Magic `.mag` sections and their `rect` / `rlabel` productions, read '
        'through `magic_gencell_layout_lib`. A `.mag` is written by Magic '
        'itself and its grammar has no form that denies a painted rectangle: '
        'a rect is in the section or it is not. The bookkeeping sections '
        '(`checkpaint`, `labels`, `properties`) are skipped BY NAME, not by '
        'reading around them. The two defects this gate was built from (#706 '
        'pdk_target, #711 die_area_budget_um) both read English DESIGN '
        'DOCUMENTS, where denial is spellable and was spelled; consulting '
        '`_prose_polarity` here would add a branch that can never fire.',
    'analog_a5_layout_emit::probe':
        "Magic's OWN stdout, matched on the `A5SCALE <box> <lambda> <lambda>` "
        "line this same function asked Magic to print. A tool's "
        'machine-formatted answer to a command the program issued is not a '
        'claim surrounded by prose that could deny it; a run that prints no '
        'such line is reported as unmeasured rather than defaulted. The two '
        'defects this gate was built from (#706 pdk_target, #711 '
        'die_area_budget_um) both read English DESIGN DOCUMENTS, where denial '
        'is spellable and was spelled; consulting `_prose_polarity` here '
        'would add a branch that can never fire.',
    'analog_a5_pdk_device_limits::deck_rules':
        "A magic DRC deck's own rule statements (`width`, `spacing`, `area`, "
        "`surround` productions in the deck's integer units). The deck is "
        'written by the PDK packaging and states a rule or does not; there is '
        "no deck syntax for 'MINWIDTH is NOT 0.14'. This reader defaults "
        'NOTHING — a rule the deck does not state is absent, and a caller '
        'that needs it must say so. The two defects this gate was built from '
        '(#706 pdk_target, #711 die_area_budget_um) both read English DESIGN '
        'DOCUMENTS, where denial is spellable and was spelled; consulting '
        '`_prose_polarity` here would add a branch that can never fire.',
    'analog_a5_pdk_device_limits::fet_limits':
        "A magic PDK's gencell definitions, `proc <ns>::<model>_defaults {} { "
        'return { ... lmin <n> wmin <n> ... compatible {...} } }` — formal '
        'Tcl written by the PDK packaging, with no form that denies a '
        'default. Where one model recurs across blocks the SMALLEST limit is '
        'taken, because that is what the PDK permits; that is an arithmetic '
        'choice over machine values, not a polarity question. The two defects '
        'this gate was built from (#706 pdk_target, #711 die_area_budget_um) '
        'both read English DESIGN DOCUMENTS, where denial is spellable and '
        'was spelled; consulting `_prose_polarity` here would add a branch '
        'that can never fire.',
    'analog_a6_drc_attribute::top_level_shapes':
        "Magic `.mag` sections and `rect` productions of the layout's own top "
        'cell, read through `magic_gencell_layout_lib`. Identical grammar and '
        'identical reason to `analog_a5_layout_emit::parse_cell` above. The '
        'two defects this gate was built from (#706 pdk_target, #711 '
        'die_area_budget_um) both read English DESIGN DOCUMENTS, where denial '
        'is spellable and was spelled; consulting `_prose_polarity` here '
        'would add a branch that can never fire.',
    'pad_bterm_coincidence_check::def_net_terminals':
        'DEF `NETS` entries, `- <net> ( <inst> <pin> ) ... ;` productions '
        'emitted by the router. DEF has no form that denies a connection: a '
        'terminal is listed on the net or it is not. Direct precedent: '
        '`digital_hardmacro_gen::_specialnet_entries` (DEF SPECIALNETS) and '
        '`macro_obs_geometry_intersect_check::parse_via_layers` (DEF VIAS), '
        'the same grammar exempted for the same stated reason. The two '
        'defects this gate was built from (#706 pdk_target, #711 '
        'die_area_budget_um) both read English DESIGN DOCUMENTS, where denial '
        'is spellable and was spelled; consulting `_prose_polarity` here '
        'would add a branch that can never fire.',
    'pad_bterm_coincidence_check::def_pins':
        'DEF `PINS` entries, `- <pin> + NET <net> + LAYER <l> ( x1 y1 ) ( x2 '
        'y2 ) + PLACED ( x y ) <orient> ;` productions emitted by the router. '
        'Formal DEF grammar with no denial form; a pin with no LAYER/PLACED '
        'pair is recorded with `rect: None` rather than guessed. Direct '
        'precedent: `_ic_release_artefacts::_def_pins`, the same section '
        'exempted for the same stated reason. The two defects this gate was '
        'built from (#706 pdk_target, #711 die_area_budget_um) both read '
        'English DESIGN DOCUMENTS, where denial is spellable and was spelled; '
        'consulting `_prose_polarity` here would add a branch that can never '
        'fire.',
    'pad_bterm_coincidence_check::layer_min_widths':
        'Technology-LEF `LAYER <name> ... WIDTH <n> ; END <name>` '
        'productions. Formal foundry grammar in which there is no way to '
        "write 'WIDTH is NOT 0.14'; a layer stating no WIDTH does not enter "
        'the returned map. Direct precedent: '
        '`pdk_via_patch_legalize::_routing_rules` and '
        '`phase3_one_shot_runner::_pdn_em_width_floor`, the same file format '
        'exempted for the same stated reason. The two defects this gate was '
        'built from (#706 pdk_target, #711 die_area_budget_um) both read '
        'English DESIGN DOCUMENTS, where denial is spellable and was spelled; '
        'consulting `_prose_polarity` here would add a branch that can never '
        'fire.',
    'pdk_dummy_fill_spec::derive':
        "A KLayout DRC rule deck's own Ruby productions — `<sym> = "
        'input(<gds>, <dt>)` layer bindings in `generic_layers.rb`, the '
        '`space(<n>.um)` / `separation(<sym>, <n>.um)` rules in '
        '`rule_decks/dummy_metal.rb`, and the density rule in '
        '`rule_decks/density.rb` — all written by the PDK packaging. THE '
        'ARGUMENT IS NOT THAT THE DECK HAS NO DENIAL FORM. It has exactly '
        'one, the Ruby comment, and this function consults it: every match from '
        'every one of the six module-level patterns is passed through '
        '`_commented(text, m.start())` and dropped when the rule is '
        'commented out. FIVE of the six already did; the sixth, `_RE_RESULT_IS_SUM`, '
        'did not, and that hole was closed in the same change that recorded this '
        'entry rather than being papered over by it. A `_prose_polarity` call would add a SECOND, '
        'English-shaped denial check (`is_denied`, `NEGATION_RE`) over Ruby '
        "source, where 'NOT' is not a construct and cannot appear outside the "
        'comment the deck already uses and this reader already honours — a '
        'call that can never fire, which this register calls a green light '
        'rather than a check. The function also defaults NOTHING: it returns '
        '`None` outright when any of the three decks, the layer map or the '
        'metal-name rows is unreadable or empty. Direct precedent: '
        '`analog_a5_pdk_device_limits::deck_rules` (a magic DRC deck read the '
        'same way) and `analog_a5_pdk_device_limits::fet_limits` (formal Tcl '
        'from the same PDK packaging). The two defects this gate was built '
        'from (#706 pdk_target, #711 die_area_budget_um) both read English '
        'DESIGN DOCUMENTS, where denial is spellable and was spelled.',
    'register_bus_driver_gen::dut_port_types':
        'SystemVerilog module-header port declarations, matched as `module '
        '<dut> ... endmodule` and then `(input|output) <pkg>::<type> <port>` '
        'inside that header, to learn which ports carry a package-typed '
        'struct. The matched text is a production of the HDL grammar written '
        'by a synthesis-bound source file, in which there is no form that '
        "DENIES a port: Verilog gives no way to write 'a is NOT an input'. A "
        'port appears in a declaration or it does not, and absence is already '
        'how this function reports it — a module that is not found returns '
        '`{}` and a port with no package type simply does not enter the map. '
        'Direct precedent: `crosslayer_rewrite_equivalence::module_ports` '
        '(the same declarations, the same reason) and '
        '`register_bus_driver_gen::bus_contract` above, the SAME MODULE '
        "reading the same design's staged package. The two defects this gate "
        'was built from (#706 pdk_target, #711 die_area_budget_um) both read '
        'English DESIGN DOCUMENTS, where denial is spellable and was spelled; '
        'consulting `_prose_polarity` here would add a branch that can never '
        'fire.',
    'register_bus_driver_gen::parameter_overrides':
        'SystemVerilog parameter_port_list default assignments '
        '(`#(parameter int W = 8)`) read from the DUT\'s own module header, and '
        'NAMED PARAMETER ASSIGNMENTS in a module instantiation '
        '(`dut_mod #(.W(16)) u (...)`), read to learn the bus widths the design '
        'actually built with. This is machine-written HDL declaration grammar in '
        'which there is no form that DENIES a value: SystemVerilog gives no way '
        'to write `parameter W is NOT 8`, and no way to write an instantiation '
        'that UN-overrides a parameter. A parameter is given a default or it is '
        'not; it is overridden at the instantiation or it is not. ABSENCE IS '
        'ALREADY THE LOUD OUTCOME IN THIS FUNCTION: a parameter with no default '
        'never enters the returned map, an instantiation with no override for '
        'that name leaves the module default standing, and when neither resolves '
        '`resolve_bus_widths` returns None with the blocking symbol NAMED, so the '
        'caller keeps its existing behaviour instead of binding a guessed width. '
        'The ONE construct that reads as a denial here is a COMMENT, and that is '
        'a lexical exclusion rather than a polarity word: '
        '`strip_hdl_comments_and_strings` blanks comments before either scan. '
        'MEASURED, both directions, in '
        '`test_a_commented_out_parameter_default_is_not_a_default`, '
        '`test_a_default_that_exists_ONLY_in_a_comment_yields_no_parameter`, '
        '`test_a_commented_out_instantiation_is_not_an_override` and '
        '`test_a_commented_out_instantiation_does_not_manufacture_a_conflict`: a '
        'commented `// parameter int W = 99` and a superseded '
        '`// dut_mod #(.W(999)) u_old (...)` are both invisible, while a live '
        'declaration is still read and a real conflict is still detected through '
        'the blanker. Consulting `_prose_polarity` here would add a branch that '
        'can never fire: all 22 denial tokens of its own vocabulary, placed in 8 '
        'positions reachable in the text this function parses, flipped 0 values '
        'over 176 trials, and the 22 that lose the value REFUSE it rather than '
        'inverting it -- while the IDENTICAL texts read as PROSE carry 128 '
        'denials, so the grammar is inert, not the vocabulary. A call that can '
        'never fire is a green light rather than a check. The direct precedents '
        'are `testbench_gen::package_first_order` (the same claim about '
        'SystemVerilog declaration grammar, with the same comment finding) and '
        '`pdk_via_patch_legalize::_routing_rules` (the same claim about LEF).',
    'register_bus_driver_gen::bus_contract':
        'SystemVerilog `typedef struct packed { ... } <name>_t;` and enum '
        "productions in the design's OWN staged package. HDL is a machine "
        'grammar with no prose form that denies a declared field — a field is '
        'in the struct or it is not — and this function REFUSES with a named '
        'reason unless every role a register access needs is present, rather '
        'than defaulting. Direct precedent: '
        '`design_one_shot_runner::step_full_stack_tb_gen`, HDL grammar '
        'exempted for the same stated reason. The two defects this gate was '
        'built from (#706 pdk_target, #711 die_area_budget_um) both read '
        'English DESIGN DOCUMENTS, where denial is spellable and was spelled; '
        'consulting `_prose_polarity` here would add a branch that can never '
        'fire.',
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


#: THE OFFENDER REGISTER — a RATCHET BY MEMBERSHIP, and it is SOURCE.
#:
#: The count was never the instrument. MEASURED across v1.17.51..v1.17.83 the
#: polarity-blind population went 212 -> 213 -> 214 -> 213 -> 214 -> 215, because
#: entries both ENTER and LEAVE; bisecting that number names the wrong landing,
#: while reading the SET named every offender in one pass. So what is pinned here
#: is membership.
#:
#: THE RULE (`--ratchet`): the gate fails when an offender is NOT in this
#: register — that is a landing ADDING one, and it is blocked. Shrinking is
#: welcome: the entry is DELETED IN THE SAME COMMIT that fixes the offender, and
#: an entry left behind after its offender is gone is itself an offender, so the
#: register cannot rot into a list of things that used to be true.
#:
#: THIS IS NOT A BASELINE AND THERE IS NO FLAG THAT WRITES IT. `--write-baseline`
#: and `--record-shrink` write files; this is reviewed like any other source, in
#: the diff, with the owner of each entry named so a reader knows who to ask.
#: The gate printing an errand that points at a write flag is what made the
#: previous shape unusable — a lane fixing one offender was invited to record
#: every other offender that run happened to see as accepted debt.
_OFFENDER_REGISTER: Dict[str, str] = {
    "design_one_shot_runner::_chip_top_resolve_excluded_variant_params":
        "OWNER: lane czaes1. ADDED BY v1.17.85 (af94a508b, 'a wrapper default "
        "naming an excluded variant is derived or refused'). Delete this entry "
        "in the commit that fixes it -- an entry that outlives its offender is "
        "itself an offender and this gate refuses it.",
    "lec_run::lec_proved_points_from_output":
        "OWNER: lane czlecresume (landed v1.17.62, 364d3cc75). Reads the LEC "
        "tool's own output to decide which proof points were proved, and writes "
        "that as a declaration. Out of scope for czmainred by brief; routed to "
        "its owning lane rather than guessed at from outside.",
}


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


def _defines_function(root: Path, name: str) -> bool:
    """Does THIS tree define `module::function`? Parsed, never imported.

    A `def` inside a class or a nested scope still counts: the scanner walks the
    whole module with `ast.walk`, so this must ask the same question the same
    way or the two could disagree about the same name.
    """
    module, _, fn = name.partition("::")
    src = root / "programs" / f"{module}.py"
    if not src.is_file():
        return False
    try:
        tree = ast.parse(src.read_text(errors="replace"))
    except (OSError, SyntaxError):
        return False
    return any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == fn for n in ast.walk(tree))


def _ratchet_verdict(new: List[str], root: Path) -> int:
    """`offenders == register`, by MEMBERSHIP. The landing gate's question.

    Two ways to fail, and they are the two directions of one rule:
      * an offender NOT in the register — a landing ADDED one;
      * a register entry whose module is in this tree and which is no longer an
        offender — it was fixed and the entry was not deleted with the fix.

    SCOPED TO THE TREE BEING SCANNED, the same way `exemption_audit` is: an
    entry whose module is simply not in this checkout is out of scope, not
    stale, or the verdict would depend on which tree the gate was aimed at.

    AND THE SAME ARGUMENT REACHES THE FUNCTION, which is where scoping at the
    module alone breaks. MEASURED 2026-09-06: `design_one_shot_runner::_chip_top
    _resolve_excluded_variant_params` became an offender at v1.17.85, and
    `design_one_shot_runner.py` is in every checkout — so on any tree older than
    that landing a correct entry for it was reported STALE, purely because the
    module file exists and the function does not. That is the same
    tree-dependence the paragraph above forbids, one level down: an entry naming
    a function this tree does not define is a claim about a different tree, not
    a claim that has expired.
    """
    registered = set(_OFFENDER_REGISTER)
    offenders = set(new)
    unregistered = sorted(offenders - registered)
    stale = sorted(n for n in registered - offenders
                   if _defines_function(root, n))

    if unregistered:
        print(f"[FAIL] {len(unregistered)} prose extractor(s) read a value out "
              f"of a sentence and write it as a declaration without asking "
              f"whether the sentence DENIES it, and are NOT in the offender "
              f"register:")
        for n in unregistered:
            print(f"   {n}")
        print(f"\n  Consult `{_POLARITY_MODULE}` — one vocabulary. If this is a "
              f"formal grammar with no negation form, the claim is a "
              f"`_NOT_PROSE` entry carrying its argument, not a register entry.")
        return 1
    if stale:
        print(f"[FAIL] {len(stale)} offender-register entry(ies) no longer name "
              f"an offender — delete the entry in the commit that fixed it:")
        for n in stale:
            print(f"   {n}")
        return 1
    print(f"[PASS] prose_polarity_consulted: offenders are exactly the "
          f"{len(registered)} in the register; no landing added one.")
    return 0


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
    ap.add_argument("--ratchet", action="store_true",
                    help="verdict by MEMBERSHIP against the offender register: "
                         "fail when an offender is unregistered (a landing "
                         "added one) or when an entry outlived its offender")
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
    if a.ratchet:
        return _ratchet_verdict(new, root)
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
