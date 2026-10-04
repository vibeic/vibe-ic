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
import instrument_calibration as _instrument_calibration  # noqa: E402  R-0915-86(3)

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
    "synth_full_adder_map::discover":
        "ONE MACHINE GRAMMAR, NO SENTENCE. The input is the active PDK Liberty "
        "file: cell/pin blocks, area numbers, directions and quoted Boolean "
        "functions. A candidate is accepted only when all eight evaluated "
        "input combinations equal XOR3 and majority3; an unsupported token, "
        "missing function, nonpositive area or ambiguous minimum refuses it. "
        "There is no prose denial form in these fields. Falsifier: "
        "test_capture_cr14_postroute_recipe.py::"
        "test_liberty_truth_table_and_area_discover_neutral_full_adder.",
    "drv_capture_plan::_stages":
        "TOOL-FILE GRAMMARS, NO SENTENCE. The stage values come from the ABC "
        "script's own `buffer -N <n>` command line, OpenROAD write_sdc's "
        "`set_max_* <n>` commands and the probe's `sta::max_fanout_check_limit "
        "<n>` / `clock <c> is_propagated=<0|1>` lines, all hashed tool output; "
        "a comment or prose line cannot negate a command. test_drv_stage_receipts"
        "::test_synth_flags_come_from_evidence_not_the_receipt falsifies it.",
    "drv_capture_plan::_env":
        "LIBRELANE TCL ASSIGNMENT GRAMMAR, NO SENTENCE. Only a line beginning "
        "with the exact set ::env(NAME) form is an environment assignment; a "
        "comment or prose statement cannot negate one. The final scene inputs "
        "are still checked for file presence and content hashes by the plan.",
    "drv_signoff_annotation::_lef_uses":
        "LEF PIN AND USE GRAMMAR, NO SENTENCE. Only a USE POWER or USE GROUND "
        "token within a named MACRO/PIN block qualifies; other USE forms and "
        "free text cannot negate or create that formal token. The annotation "
        "fixture flips USE POWER to USE SIGNAL and observes refusal.",
    "drv_signoff_capture::openroad_identity":
        "ONE PROBE LINE GRAMMAR, NO SENTENCE. The only text read is the "
        "capture's own probe output, one `OPENROAD_BINARY <path> <sha256> "
        "<version>` line per build, anchored and field-typed (64-hex digest, "
        "one whitespace-free version token); `-g<hash>` is git describe's "
        "commit field. No negation form exists; builds that disagree or a "
        "version with no commit leave the commit absent (tested).",
    "drv_signoff_judge::_liberty_limits":
        "LIBERTY ATTRIBUTE GRAMMAR, NO SENTENCE. Pin limits and related_pin "
        "are parsed from structured cell and pin groups with balanced braces; "
        "a prose negation is not a legal Liberty attribute. Linked limit tests "
        "exercise the numerical hard limit and absent-attribute cases.",
    "drv_signoff_census::_nets":
        "ONE OPENSTA REPORT_NET GRAMMAR, NO SENTENCE. The reader accepts only "
        "anchored 'Net', 'Total capacitance' and 'Number of loads' fields with "
        "complete numeric values, then checks the named load count. A negated "
        "or missing count is rejected instead of becoming an empty net. "
        "Falsifier: tests/test_drv_signoff_judge.py::test_net_census_rejects_negated_count.",
    "drv_signoff_capture::capture":
        "ONE OPENSTA COUNTER GRAMMAR, NO SENTENCE. Capture accepts only "
        "an entire DRV_COUNTER line with an exact max_slew, "
        "max_capacitance or max_fanout key and an unsigned integer. A line "
        "saying NOT DRV_COUNTER cannot match; absent or duplicate counters "
        "refuse capture rather than becoming zero. Falsifier: "
        "tests/test_drv_signoff_judge.py::test_negated_counter_marker_is_not_a_measurement.",
    "drv_signoff_judge::parse_check_types":
        "ONE OPENSTA FIXED TABLE GRAMMAR, NO SENTENCE. The parser opens "
        "only exact max slew/capacitance/fanout title lines, then a Pin line "
        "and numerical limit, measured value and Slack fields. A denial "
        "such as 'not max slew' cannot open a table, while an absent row or "
        "limit blocks sign-off rather than implying zero. Real 0.3.84 "
        "OpenSTA positive/negative Pin blocks calibrate this reader; "
        "tests/test_drv_signoff_judge.py::test_negated_table_title_cannot_be_a_measurement "
        "is its falsifier.",
    "pad_input_drive_check::judge":
        "NO SENTENCE IS READ. The gate reads its producer's JSON record "
        "(verdict/sdc_lines/refused_core_driving_cell keys) and tests exact "
        "SDC command-line membership in the sign-off deck, plus an anchored "
        "`set_driving_cell ... -lib_cell <refused cell>` command match. An SDC "
        "command has no negated form; a comment line never matches a "
        "command. Falsifier: tests/test_pad_input_drive_check.py::"
        "test_a_deck_that_drives_pads_with_the_core_cell_fails.",
    "sdc_environment::_io_pad_view":
        "ONE LIBERTY GROUP GRAMMAR, NO SENTENCE. Only brace-matched "
        "cell/pin/timing/lu_table_template groups and their simple attributes "
        "(is_pad : true, direction, max_transition, related_pin, "
        "variable_N, index_N) are read; comments and prose never form a "
        "group. Liberty has no negation form for an attribute. Falsifier: "
        "tests/test_r0929_pad_input_drive.py::"
        "test_a_pad_without_a_characterised_fast_edge_is_not_measured.",
    "sdc_environment::staged_sdc_pad_input_drive":
        "ONE SDC COMMAND GRAMMAR, NO SENTENCE. A design-staged deck declares "
        "its drive only by an uncommented `set_input_transition` or "
        "`set_driving_cell` command at line start; SDC has no negated form "
        "of a command and a `#` comment never matches. Falsifier: "
        "tests/test_r0929_pad_input_drive.py::"
        "test_a_staged_sdc_without_a_drive_gets_the_ladder_and_a_fresh_record.",
    "sdc_environment::_sdc_environment_design_values":
        "ONE STRICT TABLE GRAMMAR, NO SENTENCE. Only adjacent L9 Markdown "
        "key/value cells whose first cell is one of six exact SDC or flow "
        "keys are read. Numeric fields must parse as the entire cell and "
        "the driving cell must match a complete cell/pin identifier; a "
        "negated value cannot satisfy either grammar and falls through to "
        "the pinned PDK tier. Falsifier: tests/test_capture_cr8_sdc_environment.py"
        "::test_negated_table_value_is_not_a_design_declaration.",
    "librelane_signoff::_liberty_header_pvt":
        "ONE MACHINE GRAMMAR, NO SENTENCE. Liberty header nom_process, "
        "nom_voltage and nom_temperature are numeric attributes anchored at "
        "line start and terminated by semicolons. A missing or duplicate field "
        "returns no PVT, and the scene becomes NOT_MEASURED. A denial cannot "
        "be encoded in this grammar. Falsifier: "
        "tests/test_sta9_scene_binding.py::test_wrong_liberty_header_is_not_measured.",
    "librelane_fill_dfm::_density_ratio_specs":
        "ONE RUBY MACHINE GRAMMAR, NO SENTENCE. The PDK deck is filtered through "
        "deck_code_only before reading extract_single_layer_from_design.call "
        "numeric GDS pairs, STATIC_LAYERS union expressions, or METAL_STACK_MAP "
        "aliases. Comments and quoted messages cannot declare a layer, and "
        "unknown rule identifiers remain NOT_MEASURED rather than receiving "
        "a guessed ratio. Falsifier: tests/test_die_density_finish.py::"
        "test_density_specs_ignore_comment_claims_and_refuse_missing_layers.",
    "isa_suite_producer::objdump_guard":
        "OBJDUMP INSTRUCTION GRAMMAR, NOT PROSE. The reader accepts only a "
        "line-start hexadecimal address, then one four- or eight-hex-digit "
        "instruction parcel and one mnemonic token; its anchored expression "
        "does not capture comments, operands, or free text. A denial therefore "
        "cannot reverse a decoded instruction: text such as `not c.nop` does "
        "not make a parcel or mnemonic and is ignored, while a real c.nop "
        "parcel is caught by the calibrated RVC fixture. A malformed or absent "
        "instruction is not granted a clean result: it simply contributes no "
        "decoded instruction and the actual built image remains independently "
        "size-guarded. The fixed syntax has no negation production, and the "
        "positive calibration includes a real CSR/system mnemonic as a control.",
    "librelane_fill_dfm::lef_geometry":
        "ONE MACHINE GRAMMAR, NO SENTENCE. LEF `MACRO <name> ... END <name>` and "
        "`SITE <name> ... END <name>` blocks from the PDK's own LEFs as the "
        "installed LibreLane resolved them, read for two statements only: "
        "`SIZE <w> BY <h> ;` and `CLASS <word>`, anchored at line start. Both "
        "fields are numbers or one keyword, so no denial can be spelled, and a "
        "master or site with no SIZE is not given one: every placed instance of "
        "it makes `row_occupancy` NOT_MEASURED instead of a number. Falsifier: "
        "tests/test_mig104_fill_dfm.py::test_the_not_prose_claim_for_the_lef_"
        "reader_is_falsifiable.",
    "achieved_period_recorded_check::tool_setup_slack":
        "ONE OPENSTA RECORD. `worst slack max <v>` is report_worst_slack's fixed "
        "output inside a STAPostPNR corner report (the step-23 extra corner Tcl "
        "calls it), matched anchored at line start and end around one number. "
        "The field is a number, so no denial can be spelled in it, and a corner "
        "with no such line is not read as no-slack: it REFUSES "
        "(LL_STA_CORNER_SLACK_MISSING).",
    "_native_postroute_timing::measure":
        "ONE OPENSTA MACHINE RECORD PER CHECK. `report_worst_slack -max/-min "
        "-digits 6` writes `worst slack max|min <number>` at the start and end "
        "of a line. The only payload is a numeric slack; a denial cannot be "
        "spelled in that grammar. Both checks must be present for every "
        "declared corner or NATIVE_POSTROUTE_SLACK_MISSING refuses the scene. "
        "Falsifier: test_sub_ss_external_capture_closure.py::"
        "test_native_slack_requires_both_numeric_tool_records.",
    "_native_postroute_timing::_measurement_sdc":
        "ONE TCL COMMAND GRAMMAR, NO SENTENCE. Only whole lines beginning "
        "`set_timing_derate -early|-late <number>` are parsed from OpenROAD "
        "write_sdc output; the remainder is an optional Tcl comment. A "
        "different value, duplicate command, incomplete pair, or unsupported "
        "command shape REFUSES rather than becoming an OCV measurement. "
        "No negated declaration exists in this command grammar. Falsifier: "
        "test_t102_librelane_postroute_repair.py::"
        "test_native_sdc_derate_parser_refuses_nonformal_commands.",
    "post_route_signoff_corner_check::evaluate_tool":
        "ONE OPENSTA RECORD. `worst slack max|min <v>` is report_worst_slack's "
        "fixed output in each STAPostPNR corner report, one line per analysis, "
        "whose only fields are the analysis keyword and a number. There is no "
        "negated form to emit, and a corner lacking either line REFUSES "
        "(LL_STA_CORNER_SLACK_MISSING) rather than being judged on one side.",
    "clock_target_record_agreement_check::tool_clock_periods":
        "TWO MACHINE RECORDS. `Clock: <name>` / `Period: <p>` is OpenSTA "
        "report_clock_properties' fixed block in LibreLane's corner clock.rpt, "
        "and `STA_TIME_UNIT: <unit>` is stamped by the step-23 corner Tcl with "
        "`puts` from sta::unit_scale_abbreviation/unit_suffix. Every field is a "
        "name, a number or a unit token anchored at line start; an absent unit "
        "or an empty clock report REFUSES instead of guessing.",
    "path_spice_tool::subckt_devices":
        "ONE MACHINE GRAMMAR, NO SENTENCE. SPICE netlist syntax as the PDK's "
        "declared CELL_SPICE_MODELS and Magic's ext2spice write it: `.subckt "
        "<name> <ports>`, `.ends`, and device lines named by their first letter "
        "(X/M/D). It reads a subckt's port list and COUNTS its device lines; "
        "no token is interpreted, so no denial can be spelled. The direction is "
        "safe: a cell whose count reads zero is not simulated from its layout "
        "(inert, or kept on its schematic subckt and named), never promoted to "
        "the layout view. Falsifier: tests/test_f22_spice_corr.py"
        "::test_the_not_prose_claim_for_the_subckt_reader_is_falsifiable.",
    "sdf_gate_sim::declared_dut_binding":
        "TWO MACHINE GRAMMARS, NO SENTENCE. The chip-top Verilog is the "
        "structural netlist `io_pad_chip_top_gen` wrote (comments stripped "
        "first): `module <name>`, `<master> <instance> (.pin(net), ...);` and "
        "`net[bit]` references, read only to TRACE a core port through a pad "
        "to a chip port; the record is that producer's JSON. Verilog has no "
        "negated connection to spell, and every link that does not trace "
        "REFUSES (NO_DECLARED_CHIP_TOP, CORE_PORT_NOT_TRACEABLE, "
        "CHIP_PORT_NOT_ROUTED) instead of binding by name.",
    "librelane_signoff::agreement":
        "TWO MACHINE GRAMMARS, NO SENTENCE. `Reading cell library for the "
        "'<corner>' corner at '<path>'` is LibreLane 3.1 sta/corner.tcl's own "
        "fixed record, anchored at line start with both fields quoted, and is "
        "used only to list the files the tool read; `VIBEIC_ARM <key> <value>` "
        "is printed by this module's own arm Tcl with `puts` from a number the "
        "interpreter computed, anchored at both line ends around two \\S+ "
        "fields. Neither has a negated form ('not VIBEIC_ARM ...' fails the "
        "anchor), and the direction is safe: an unparsed value is None, and "
        "None never AGREEs, so a reading that cannot be made is a refusal.",
    "librelane_signoff::deck_agreement":
        "STAMP LINES THIS FLOW WRITES ITSELF plus one OpenSTA record. "
        "`=== SETUP|HOLD corner: ... ===`, `STA_BASIS_LIBERTY: <path>`, "
        "`STA_BASIS_CORNER: <rc>`, `STA_BASIS_SPEF: <file>` and "
        "`OCV_DERATE_APPLIED early=<x> late=<y>` are emitted by "
        "_emit_mcorner_ocv_sta with `puts $_f` from values it resolved; "
        "`worst slack max|min <v>` is OpenSTA report_worst_slack's fixed "
        "output, matched anchored at both ends. No field is free text, so a "
        "denial cannot be spelled inside one; and every unreadable field "
        "makes the stanza NOT_COMPARABLE, which can never produce AGREE.",
    "librelane_prelayout::check_setup_counts":
        "OpenSTA check_setup prints one fixed-format summary per finding kind, "
        "'Warning: There are|is <N> <kind>.', and prints nothing for a kind "
        "with zero findings; there is no negated form to emit. The reader "
        "only counts those lines after the check_setup header and returns "
        "None when the header is absent, so an unwritten section is "
        "NOT_MEASURED, never zero. Calibrated on real STAPrePNR checks.rpt "
        "pairs (instrument_calibration).",
    "drc_feedback_repair::_def_nets":
        "DEF is a closed machine grammar: UNITS DISTANCE MICRONS, NETS, "
        "ROUTED and END NETS are parser tokens, not sentences. A denial such "
        "as 'not ROUTED' is invalid DEF and cannot be emitted by OpenROAD. "
        "The function refuses absent sections and does not infer sign-off "
        "success from these tokens; it only compares route identities.",
    "drc_feedback_repair::run":
        "The values read here are exact KLayout RDB XML categories, OpenROAD "
        "fixed-format INFO records anchored at both line ends, and a DEF "
        "formal grammar. The route's success is never inferred from free "
        "prose: an absent metric is a named refusal, nonzero is a refusal, "
        "and the original deck must emit a parseable zero-item RDB. A text "
        "line saying 'not [INFO ...]' cannot match the anchored grammar.",
    "sta_signoff_rigor_check::check":
        "TWO STAMP LINES THIS FLOW WRITES ITSELF, in a closed field grammar "
        "(R-0915-154). `# STA_ALIAS_BASIS: <file>` is written by "
        "phase3_one_shot_runner's canonical-alias writer as "
        "`\"# STA_ALIAS_BASIS: \" + _alt.name`, where `_alt` can only be one "
        "of the four `_CANONICAL_POST_ROUTE_STA_BASES` (sta_spef_based.rpt, "
        "sta_mcorner_ocv.rpt, sta_spef_multicorner.rpt, sta.rpt); the reader's "
        "pattern is anchored at line start AND line end around exactly that "
        "closed field, `sta(?:_[a-z0-9]+)*\\.rpt`. `STA_PARASITICS_PROVENANCE: "
        "PNR_SESSION_UNVERIFIED` is emitted by the PnR corner-binding Tcl with "
        "`puts $f` as a CONSTANT, and is matched as that literal between the "
        "same two anchors. Neither grammar has a free-text field, so a denial "
        "cannot be spelled inside one: `STA_ALIAS_BASIS: not sta_mcorner_ocv.rpt` "
        "or `... PNR_SESSION_UNVERIFIED no` fails the anchor and is not read. "
        "AND THE DIRECTION IS SAFE BY CONSTRUCTION, which is the falsifier's "
        "other half: the unverified stamp only ever EXCLUDES a report from "
        "sign-off, and the alias only ever REPLACES the graded bytes with its "
        "basis's own -- neither read can manufacture a PASS. MEASURED in "
        "`test_a_denial_spliced_into_the_stamp_lines_is_not_read`: every "
        "`_prose_polarity` token, CJK included, spliced before, inside and after "
        "each field leaves the reader's answer at 'not a stamp'.",
    "gds_xor_check::restream_env_from_transcript":
        "A TRANSCRIPT THIS FLOW WROTE ITSELF, in a fixed field grammar, and the "
        "same class as `_run_magic_signoff_drc` below. All three patterns read "
        "`phase3/stage3/pnr/stream_out.log`, every line of which the run's own "
        "stream-out recipe emits as `print(f\"<TOKEN> <verb phrase>: {value}\")` "
        "from a value it had ALREADY resolved; each pattern is anchored at line "
        "start AND line end around a closed field type (`\\S+`, one path), so "
        "the grammar has no free-text field in which a denial could be written. "
        "THE RECIPE DOES SAY THE NEGATIVE -- and it says it in productions these "
        "patterns cannot reach: `LEFDEF_MAP not applied (none configured)`, "
        "`LEFDEF_MAP_CONFIGURED_BUT_ABSENT: ...`, `MACRO_GDS merged (no DEF "
        "master matched): <path>`, and `CELL_GDS manual-substituted <n> std "
        "cell(s)` which carries no `: <path>` field at all. A denial therefore "
        "fails the anchor, the key stays OUT of the env dict, and that is "
        "precisely what the denial means: the re-stream passes no such variable "
        "and reads what the run read. MEASURED on run21's real transcript "
        "(spm x gf180mcuD): the tightened patterns return the same three keys "
        "and both macro libraries as the loose ones did. "
        "AND THE VALUE'S CONSEQUENCE IS CHECKED INDEPENDENTLY, which is the "
        "falsifier: a library this reader failed to recover makes the re-streamed "
        "reference too small, and `reference_is_faithful` refuses on the shape "
        "census (rc=1, NOT_DETERMINED) rather than reporting a confident wrong "
        "difference count. So even a grammar change that slipped a denial past "
        "the anchor cannot buy a clean XOR.",
    "phase3_one_shot_runner::_run_magic_signoff_drc":
        "A TRANSCRIPT THIS MODULE WROTE ITSELF, in a fixed field grammar, one "
        "function away. `_magic_signoff_drc_tcl` emits every line this reader "
        "reads -- `tech file: <path>`, `error tiles (drc list count total): "
        "<n>`, `COUNT: <n>` -- with `puts $_fh` from values it fetched from "
        "Magic, and both patterns here are anchored at line start AND line "
        "end with a closed field type (`\\S+` for a path, `-?\\d+` for a "
        "count). There is no free-text field in the grammar, so there is no "
        "sentence in which a denial could be written: `error tiles ... : NOT "
        "0` does not parse, it simply fails the anchor and the reader records "
        "the count as unmeasured. A count that is absent is already how this "
        "function answers -- a transcript with no `COUNT:` trailer is "
        "NOT_MEASURED and never a clean chip, which is the one thing a denial "
        "could otherwise try to buy. MEASURED, NOT ASSERTED, in "
        "`test_a_denial_spliced_into_the_magic_transcript_moves_nothing`: "
        "every token of `_prose_polarity`'s vocabulary, the CJK spellings "
        "included, spliced into each of the three fields and appended to each "
        "of them -- 0 rival answers and 0 values changed, with the negative "
        "control that deleting the trailer DOES move the verdict to "
        "NOT_MEASURED, so the zeros are about the grammar and not a fixture "
        "that could not move.",
    "stated_vector_bus_oracle_gen::bus_contract":
        "A PORT SURFACE, not a sentence. The argument is the DUT's own "
        "`(direction, width, name)` triple list -- `testbench_gen.resolve_dut` "
        "parsing a Verilog/SystemVerilog module header, or L9's `ports` array, "
        "which carries the same identifiers. There is no free-text field in "
        "it, so there is no sentence in which a denial could be written. The "
        "one `.search` reads an IDENTIFIER, normalised to `[a-z0-9_]`, for the "
        "universal active-low suffix, and an identifier has no negation form: "
        "there is no way to spell `this reset is NOT active low` in a "
        "Verilog name. A reset that is active HIGH is spelled without the "
        "suffix, and absence is already how this function answers -- it "
        "publishes `rst_polarity_evidence` naming the suffix it read, or "
        "naming that it read none. MEASURED, NOT ASSERTED, in "
        "`test_r0915_113_5_a_port_surface_is_a_grammar_not_a_sentence`, over "
        "all 21 tokens of `_prose_polarity`'s vocabulary, the CJK spellings "
        "included, in every place a denial could act on this reader: spliced "
        "into the WIDTH field, appended to the DIRECTION field, added as an "
        "extra port, and added as a comment-shaped port -- 84 placements, 0 "
        "rival answers, 0 refusals, 84 unchanged. Spliced INTO the reset "
        "identifier the denial is not a denial at all but a RENAME: the port "
        "`reset_n` is then absent from the input, 16 of 21 publish the port "
        "the design now declares (0 publish a port the input does not "
        "declare) and the 5 CJK tokens land in the NAMED refusal, because "
        "normalisation strips them and the identifier matches no reset role. "
        "NEGATIVE CONTROLS: renaming `reset_n` to `reset` moves "
        "`rst_active_low` True -> False, and dropping the chip-select port "
        "refuses by name (`the DUT declares no cs port`) -- so the zeros are "
        "about the grammar and not a fixture that could not move.",
    "sta_annotation_population::classify":
        "TWO CLOSED MACHINE GRAMMARS, each checked against its own stated "
        "count. OpenSTA's `report_annotated_delay` banner -- `^Found (\\d+) "
        "unannotated drivers\\.$` and its `partially` twin, anchored at line "
        "start AND line end, with the driver inventory between them COUNTED "
        "against the banner's own number and refused on any mismatch -- plus "
        "this flow's one-producer `STA_LINK_INSTANCE` / "
        "`STA_UNCONNECTED_OUTPUT` records; and a DEF `NETS`/`SPECIALNETS` "
        "section whose statement count is likewise checked against the "
        "section header's number. NEITHER HAS A NEGATION FORM: there is no "
        "way to write `this driver is NOT unannotated`. A driver that is "
        "annotated is ABSENT from the inventory, and absence is already how "
        "this function answers -- it names its refusal (`missing native "
        "annotation counts`, `DEF authority absent`, `malformed DEF net "
        "section`) and never defaults. MEASURED, NOT ASSERTED, in "
        "`test_r0920_sta_annotation_population_is_a_grammar_not_a_sentence`: "
        "all 20 tokens of `_prose_polarity`'s vocabulary -- both tiers, the "
        "CJK spellings included -- each carrying a RIVAL declaration (`Found "
        "0 unannotated drivers.`), placed above the banner, below it, and "
        "both, and as a DEF comment above / below / inside the NETS section, "
        "move 0 published answers; the DEF cases move the recorded "
        "`def_sha256` while the verdict stands, so the fixture is reaching "
        "the reader. Spliced INSIDE the banner, all 20 destroy the match and "
        "land in the NAMED refusal rather than publishing the rival count. "
        "NEGATIVE CONTROLS: changing the DEF `USE` moves the classification "
        "to REQUIRED_OR_UNKNOWN, changing the banner count refuses as "
        "inconsistent, and an absent DEF refuses by name -- so the zeros are "
        "about the grammar and not a fixture that could not move.",
    "phase3_one_shot_runner::_spare_tieoff_measured_from_log":
        "MARKERS THIS FLOW PRINTS ITSELF, in a closed field grammar. Both "
        "spare-insertion paths -- the direct Tcl deck "
        "(`_build_spare_postfix_tcl`) and the odbpy step "
        "(`insert_spare_cells.py`) -- emit `SPARE_TIEOFF_CONNECTED <int> of "
        "<int>` and `SPARE_INPUT_PIN <inst> <pin> <use> <net|->` from values "
        "they read out of the database. The pin pattern takes EXACTLY four "
        "whitespace-free fields and is anchored at line end, so there is no "
        "free-text field in which a denial could be written: a line with a "
        "fifth token does not parse, and the grammar's own spelling of `this "
        "pin has no net` is the closed token `-`, which the reader maps to "
        "net=None and refuses tied_off on. A pin that is not listed at all is "
        "what `spare_cell_coverage_check.prove_inputs_tied` refuses (the "
        "spare is not enumerated). FALSIFIER, measured in "
        "test_spare_clock_input_tied_and_proven.py::"
        "test_the_runner_reads_the_enumeration_not_just_the_count: the v5c "
        "log shape with `SPARE_INPUT_PIN spare_dff_0 CLK CLOCK -` reads "
        "tied_off=False naming spare_dff_0/CLK despite `12 of 12`, and the "
        "same log with the net filled in reads tied_off=True.",
    "phase3_one_shot_runner::_spare_insertion_provenance":
        "VERILOG MODULE-ITEM GRAMMAR, read after the function has DELETED "
        "every string literal, line comment and block comment and has "
        "required a complete `module ... endmodule`. The one question it "
        "asks of that text is whether a planned spare-pad name occurs as an "
        "identifier TOKEN, and Verilog has no way to spell `this instance is "
        "NOT here`: an instance that is absent is ABSENT, which is already "
        "the published answer (`planned_not_inserted`). Same class as "
        "`design_one_shot_runner::_chip_top_resolve_excluded_variant_params` "
        "-- module-item grammar out of text its own gatherer has stripped. "
        "MEASURED, NOT ASSERTED, in "
        "`test_r0920_spare_insertion_provenance_is_a_grammar_not_a_sentence`,"
        " over all 20 tokens of `_prose_polarity`'s vocabulary, in BOTH "
        "directions a denial could act: it cannot MINT an insertion -- a "
        "comment naming the pad verbatim, above the module, below it, inside "
        "the body and inline in a port list, moves 0 of 80 answers, because "
        "the strip removes it before tokenising -- and it cannot CANCEL one, "
        "0 of 40 over a wrapper that really does instantiate the pad, which "
        "is this function's own documented contract: the cell insertion "
        "producer owns every `instances` obligation and a wrapper cannot "
        "retire it. A denial inside a `$display` string is stripped too, 0 of "
        "20. NEGATIVE CONTROLS: instantiating the pad moves it out of "
        "`planned_not_inserted`, and a wrapper with no complete module is "
        "refused UNVERIFIED/UNREADABLE by name with the cell obligation "
        "intact -- so the zeros are about the grammar, not a fixture that "
        "could not move.",
    "digital_hardmacro_gen::characterise_liberty":
        "THE MCORNER STA BANNER, a closed grammar with ONE producer: "
        "phase3_one_shot_runner's emitter writes each whole line as `=== "
        "{kind} corner: process={label} liberty={lib}, SPEF={spef} ===`. It is "
        "read only to choose the SETUP-corner library; the arcs come from "
        "OpenSTA write_timing_model, not from the report. No term has a "
        "negation form. MEASURED, NOT ASSERTED, in "
        "`test_r0915_87_characterise_liberty_reads_a_banner_not_a_sentence`, "
        "over all 21 `_prose_polarity` tokens on r27's vendored report. THE "
        "MEASUREMENT CORRECTED THE READER before this entry was written: "
        "`dict(findall)` kept the LAST SETUP banner, so 189 of 294 "
        "banner-quoting denials chose a RIVAL library and reported the macro "
        "characterised against it, and after refusing disagreeing banners a "
        "banner-shaped prefix on the real line still won 21. The banner must "
        "now match the producer's WHOLE line, and SETUP banners naming "
        "different libraries are refused (EXECUTION_ERROR). WHAT REMAINS "
        "MOVES, ALWAYS INTO A REFUSAL: plain-sentence rivals at every boundary, "
        "appended and prefixed, 42 of 294; banner-quoting rivals 42 of 294; "
        "tokens spliced inside the banner 105 of 105 -- every one "
        "BLOCKED_BY_UPSTREAM, and 0 of 693 publish a library the report's own "
        "banner does not name. NEGATIVE CONTROLS: changing the banner's "
        "library path moves the published library, and removing the banner "
        "refuses, so the zeros are about the grammar and not a fixture that "
        "could not move.",
    "testbench_gen::oracle_provenance":
        "A CLOSED TESTBENCH-HEADER GRAMMAR with one producer per term: "
        "`ORACLE_NONE_MARKER` and `stamp_generated` (marker + ONE identifier + "
        "newline) in this same file, and the authored header's line-start "
        "`// CITATION :` term. No term has a negation form -- a file that is "
        "not a floor simply omits the marker. MEASURED, NOT ASSERTED, in "
        "`test_r0915_89_oracle_provenance_reads_a_grammar_not_a_sentence`, "
        "over all 21 tokens of `_prose_polarity`'s vocabulary (both tiers, CJK "
        "included). THE MEASUREMENT CORRECTED THE READER TWICE before this "
        "entry was written: the emitter was taken as the rest of the marker "
        "line (21/21 appended tokens absorbed into the published name), then "
        "as the leading word (21/21 spliced tokens published AS the name); the "
        "line tail must now fullmatch one identifier or the emitter is "
        "refused as \"\". WHAT REMAINS MOVES, AND ALWAYS ONE WAY: rival-"
        "carrying denials at every line boundary, appended and prefixed, move "
        "0 of 336 floor answers and 21 each for generated and authored; "
        "splices inside the grammar move 42/63 floor, 63/63 generated, 21/63 "
        "authored -- and EVERY move lands in one of two disclosed refusals, "
        "emitter \"\" or AUTHORED-uncited (named in `authored_uncited`). A "
        "denial MINTS NO citation (0 of 252). A denial that QUOTES a marker "
        "verbatim costs authorship (authored -> floor/generated) and never "
        "grants it, and `authored_oracle_preserved` makes the identical call "
        "on those bytes, which is the contract this reader must keep rather "
        "than second-guess. NEGATIVE CONTROLS: removing the floor marker, "
        "changing the emitter, and changing the citation value each move the "
        "published answer, so the zeros are about the grammar, not a fixture "
        "that could not move.",
    "analog_incremental_decimator::read_stamp":
        "A CLOSED key=value GRAMMAR written by exactly one producer -- "
        "`stamp()`, four functions above it in the same file -- and read back "
        "by this one, so the pair cannot drift. The line is "
        "`* analog_incremental_decimator: mode=<word> window_clocks=<int> "
        "order=<int> coeff=<float> feedback_delay_clocks=<int>`, and it "
        "carries the decode an INCREMENTAL converter's corner deck must be "
        "graded with: reading one with a free-running converter's FFT "
        "under-reads it, and decoding it with the input's weights instead of "
        "the DAC's under-read it by 7.4 bit (vibe-ic#2321, #2322), so the "
        "deck says which decode it needs rather than a consumer guessing. "
        "THE GRAMMAR HAS NO NEGATION FORM: there is no way to write `this "
        "deck is NOT decoded incrementally` in it. A decode that is not "
        "declared is simply ABSENT, and absence is already how this function "
        "answers -- `NO_STAMP` when no line matches, `BAD_STAMP` LISTING "
        "which of the five fields is missing or will not cast, never a "
        "default, because a default would be a guess about the circuit the "
        "emitter emitted. So the two things a denial could do -- remove a "
        "declaration or reverse one -- are respectively ALREADY HANDLED and "
        "NOT EXPRESSIBLE. MEASURED, NOT ASSERTED, in "
        "`test_r0915_78_read_stamp_is_a_grammar_not_a_sentence`: all 21 "
        "tokens of `_prose_polarity`'s own vocabulary -- both tiers, the five "
        "CJK spellings included -- each carrying a DECLARATION-SHAPED payload "
        "that mints a RIVAL decode (`mode=free_running window_clocks=512 "
        "order=3 coeff=0.05 feedback_delay_clocks=0`), placed in every "
        "position a sentence can physically occupy around the stamp (a "
        "comment line above, below, and both), move 0 of 63 published "
        "answers. The same tokens spliced INSIDE the stamp's own payload -- "
        "immediately after the colon, appended at the end, and in front of a "
        "field name -- move 0 of a further 63, which is the grammar working: "
        "a bare word is not a term in it. AND THE ZERO CARRIES ITS NEGATIVE "
        "CONTROL: changing a VALUE, `window_clocks=256` to `512`, DOES move "
        "the published answer, so the fixture could have moved and the zero "
        "is a statement about the grammar rather than about a fixture that "
        "could never have answered differently. The producer's own output is "
        "checked in the same file, so the claim is about the PAIR and not "
        "about the reader alone: every term `stamp` writes is a "
        "`name=value` and the key set is exactly `STAMP_FIELDS`.",
    "sdf_gate_sim::_run_l10_suite":
        "SIMULATOR AND SHELL DIAGNOSTIC GRAMMAR, read out of a gate-level "
        "TRANSCRIPT to say what one L10 case did: `RC=(\\d+)` is the deck's own "
        "`echo RC=$?`, `Created a vpiInterModPath` and `^SDF INFO: ... Putting "
        "delay` and `^SDF ERROR: ... Unable to match ModPath` are Icarus's "
        "`-sdf-info` channel, and `^\\s*\\[TB <id>\\] PASS` is the case's own "
        "marker. NONE OF THESE HAS A NEGATION FORM. The `-sdf-info` channel "
        "emits ONE LINE PER EVENT: a delay that was applied prints `Putting "
        "delay`, an arc that could not be matched prints `Unable to match "
        "ModPath`. There is no line that says a delay was NOT applied -- a "
        "delay that was not applied produces NO line, and ABSENCE is already "
        "how this reader answers: `delays_applied == 0` sets `annotated` False "
        "and the step then publishes `NOT SDF-ANNOTATED`, and a transcript with "
        "no PASS marker returns verdict None, which `name_unverdicted_case` "
        "names rather than folding into a pass. A shell exit status is a "
        "number and a number cannot be denied. "
        "MEASURED, NOT ASSERTED, in `test_r0915_76_the_transcript_grammar_has_"
        "no_negation_form`: all 21 tokens of `_prose_polarity`'s own vocabulary "
        "-- both tiers, the five CJK spellings included -- each carrying a "
        "declaration-shaped payload that DENIES what the line beside it "
        "reports (`the delay is <token> applied and the arc is <token> "
        "matched`), placed in each of the 19 positions a sentence can occupy in "
        "a six-line transcript: as a whole line at any of the 7 boundaries, "
        "appended to any of the 6 lines, prefixed on any of the 6. "
        "THE MEASUREMENT CORRECTED MY OWN ARGUMENT AND THE CORRECTION IS THE "
        "POINT: 84 of those 399 trials DO move a published answer, and every "
        "one of the 84 is a PREFIX, because `^SDF INFO:` / `^SDF ERROR:` / "
        "`^\\s*\\[TB` are anchored under `re.M` and text in front of the marker "
        "displaces it off the line start. So the moves are real -- and they all "
        "move ONE WAY: delays 2 -> 1, unmatched 1 -> 0, verdict PASS -> None. "
        "NOT ONE trial of the 399 makes any of these readers REPORT A FACT THE "
        "TRANSCRIPT DOES NOT CARRY. A denial can only ever cost a positive "
        "here, and losing a positive is the direction each of these readers "
        "already treats as its refusal, so the polarity question has no bite: "
        "there is nothing a sentence can deny into existence. The 84 are "
        "recorded as a robustness limit -- a `$write` with no newline ahead of "
        "an SDF line under-counts, which can only produce a FALSE `NOT "
        "SDF-ANNOTATED`, never a false annotated -- and not as the argument.",
    "analog_converter_density_grade::_sources":
        "SPICE INDEPENDENT-SOURCE GRAMMAR, read to recover the DC level the "
        "deck drives on each node so the bitstream density a converting "
        "modulator must return can be derived from the deck's own references "
        "-- `(vin_dc - vrefn) / (vrefp - vrefn)` -- instead of from a table of "
        "chip values. THE POLARITY QUESTION HAS NO REFERENT: every input goes "
        "through `analog_pdk_deck_context.spice_code_only` before a single "
        "match, which blanks every `*` comment line and every `;` / `$` "
        "inline comment, and those are the only places English lives in a "
        "SPICE deck. It is not a hypothetical: the A4 decks this reads carry "
        "three prose `*` lines that NAME `v_in`, `vrefp` and their values -- "
        "the power-on sequence note, the vector-retention note and the "
        "resolution-stimulus note. SPICE ALSO HAS NO NEGATION FORM: a source "
        "card cannot say `this is NOT the input level`; a level that is not "
        "declared is simply ABSENT, and absence is already how this function "
        "answers -- a missing `vin` / `vrefp` / `vrefn` is refused by name "
        "(`density_no_input_dc_level`, `density_no_reference_pair`) and never "
        "guessed. MEASURED, NOT ASSERTED, in "
        "`test_r0915_45_density_sources_read_deck_code_only`: all 21 tokens of "
        "`_prose_polarity`'s own vocabulary -- both tiers, the five CJK "
        "spellings included -- each carrying a DECLARATION-SHAPED payload that "
        "mints a rival input level (`v_in vin 0 0.95 is <token> the input "
        "level`), placed in each of the 4 positions a sentence can physically "
        "occupy around these cards (a `*` comment above the card, a `;` and a "
        "`$` inline comment on it, a `*` comment below), move 0 of 84 "
        "published answers. THE MUTATION ARM CORRECTED MY OWN ARGUMENT, "
        "AND THE CORRECTION IS THE INTERESTING PART: with "
        "`spice_code_only` replaced by the identity -- the strip deleted "
        "-- the same 84 trials still move 0, SO THE STRIP IS NOT WHAT "
        "CARRIES THE ZERO. THE ANCHOR IS. `_SRC` must BEGIN a line with a "
        "`v` under `re.M`, and every place English lives in a SPICE deck "
        "begins with something else -- `*` opens a comment line, `;` and "
        "`$` can only follow code, and SPICE has no block comment. The two "
        "are REDUNDANT protections: removing EITHER alone moves 0 of 84, "
        "and removing BOTH moves them, which is what makes the zero a "
        "measurement rather than a property of a fixture that could never "
        "have moved. The strip stays as defence in depth against a future "
        "reader here that is not anchored, recorded as exactly that rather "
        "than as the argument. AND THE ZERO CARRIES ITS NEGATIVE CONTROL: the IDENTICAL "
        "payload spliced in as CODE (a real `v_in` card) DOES move the "
        "published answer to 0.85 with the strip ON, so the fixture could "
        "have moved and the zero is a statement about the grammar.",
    "digital_hardmacro_gen::merge_duplicate_pin_declarations":
        "LEF MACRO/PIN GRAMMAR, read to find the declarations of one pin "
        "inside one macro so their PORT geometry can be carried into a single "
        "declaration. Every reader is a FULLY ANCHORED whole-line match over "
        "a LEF keyword line -- `_PIN_OPEN_RE` is "
        "`^([ \\t]*)PIN[ \\t]+(\\S+)[ \\t]*$`, `_MACRO_OPEN_RE` is the same "
        "shape for MACRO, and the block ends are "
        "`^[ \\t]*END[ \\t]+<name>[ \\t]*$` built from the name just matched. "
        "THE ANCHORING IS THE ARGUMENT AND IT IS FALSIFIABLE IN TWO "
        "DIRECTIONS: the `$` admits EXACTLY ONE token after the keyword, so "
        "no sentence can satisfy it -- `PIN clk is NOT declared here` has "
        "four -- and the `^` with no `#` in the character class means a LEF "
        "comment line, which is the only place English lives in a LEF, cannot "
        "open a block either. LEF ALSO HAS NO NEGATION FORM: the syntax gives "
        "no way to write `this macro does NOT declare pin clk`; a pin that is "
        "not declared is simply absent, and absence is already how this "
        "function reports it -- an unterminated or unmatched PIN is passed "
        "through byte-for-byte and never merged. Nothing is extracted from a "
        "sentence either: the only value written is the pin NAME captured by "
        "the anchored group, and single-valued attributes that DISAGREE "
        "between two declarations raise `DuplicatePinConflict` rather than "
        "being picked. MEASURED, NOT ASSERTED, because an anchoring argument "
        "has been wrong here before: every denial token `_prose_polarity`'s "
        "own patterns spell (18), each carrying a DECLARATION-SHAPED payload "
        "(`# PIN clk is <token> declared here` and three sibling shapes), "
        "placed in each of 4 positions a comment can occupy in this "
        "production, moved 0 of 288 published answers -- the merge report and "
        "the comment text both unchanged, 288 UNCHANGED, 0 moved. THE ZERO "
        "CARRIES ITS CONTROL: the same payload spliced in as CODE (a real "
        "`PIN rst` block) moves the answer, 1 pin declaration to 2, so the "
        "fixture could have moved. Owner: lane mainred.",
    "die_level_deck_rule_attribution::density_rule_evidence":
        "KLAYOUT DRC RULE-DECK GRAMMAR (Ruby DSL), read to record, for each "
        "die-level density rule, the deck's own words for it -- the rule "
        "block's COMMENT-STRIPPED code and which of the deck's whole-die area "
        "identifiers that code references. THE MODULE, NOT THIS READER, IS "
        "WHAT MAKES IT POLARITY-FREE: every byte this function inspects has "
        "already been through `deck_code_only`, which blanks `#` comment "
        "lines and in-line tails, so NO SENTENCE REACHES ANY REGEX -- the same "
        "property `analog_poweron_sequence::plan` records for SPICE, and for "
        "the same reason (English lives in a deck only in its comments). The "
        "one search performed is `\\b<identifier>\\b` for an identifier the "
        "deck itself declared, over code only. A DRC DECK HAS NO NEGATION "
        "FORM: there is no production that says `this rule does NOT read "
        "chip_area`; a rule that does not read it simply does not mention it, "
        "and absence is already how this function reports it -- the matched "
        "list comes back empty and `_die_level_attribution_consult` REFUSES "
        "the attribution on it. MEASURED, NOT ASSERTED: all 21 denial tokens "
        "of `_prose_polarity`'s vocabulary, each carrying a "
        "declaration-shaped payload (`# M2.4 <token> reads chip_area` and "
        "three sibling shapes), placed in each of the 6 positions a comment "
        "can occupy in this production -- 504 variants, 504 UNCHANGED, 0 "
        "moved. THE ZERO CARRIES ITS CONTROL: the same claim spliced in as "
        "CODE (`z = metal3.area / chip_area` under a second rule) MOVES the "
        "answer, so the fixture could have moved. A FIRST PASS OF THIS "
        "MEASUREMENT REPORTED 420 OF 504 MOVED AND WAS WRONG: it compared the "
        "record's BYTE IMAGE, which a blanked comment perturbs by one blank "
        "line, and one of its four payloads was a CODE line rather than a "
        "comment. The answer compared here is the published one -- which "
        "rules are die-level and by which identifier. Owner: lane icsub2.",
    "die_level_deck_rule_attribution::rdb_rule_counts":
        "KLAYOUT REPORT-DATABASE XML, read to count violations per rule id. "
        "Two readers, both element-scoped: `_ITEM_RE` is "
        "`<item>(.*?)</item>` and `_CAT_RE` is "
        "`<category>'?([^<']*)'?</category>`, so the only text that can reach "
        "the published value is what a KLayout deck wrote BETWEEN "
        "`<category>` tags -- a rule id such as `M2.4`, emitted by the tool "
        "and never typed by a person. The English an RDB does carry lives in "
        "`<description>`, `<value>` and any free comment element, and none of "
        "those is a `<category>`. AN RDB HAS NO NEGATION FORM EITHER: there "
        "is no element that says a violation did NOT occur; a rule with no "
        "violation simply has no `<item>`, and this function reports that as "
        "an absent key, which is exactly how `_die_level_attribution_consult` "
        "then refuses to attribute it. MEASURED, NOT ASSERTED: all 21 denial "
        "tokens, each in a declaration-shaped payload, spliced into EVERY "
        "element of the database that carries English -- the database "
        "`<description>`, a category `<description>`, a `<value>`, and a free "
        "`<comment>` inside an item -- 84 variants, 84 UNCHANGED, 0 moved. "
        "THE ZERO CARRIES ITS CONTROL: the same claim written as a real "
        "`<item>` with its own `<category>` moves the counts, so the fixture "
        "could have moved. Owner: lane icsub2.",
    "analog_poweron_sequence::plan":
        "SPICE CARD GRAMMAR, read to decide whether a deck runs a transient, "
        "drives a clock and has exactly one DC source on the named rail -- "
        "and, when it does, to compute the ramp and delay from the deck's own "
        "numbers. `_DC_SOURCE`, `_PULSE` and `_TRAN` are all anchored "
        "`^...$` over one card, so a sentence cannot satisfy them, and SPICE "
        "has no production that DENIES a card: a deck cannot write `v_vdd is "
        "NOT 1.8` -- it writes a different card or none. THE ENTRY WAS FALSE "
        "UNTIL `deck_code_only` LANDED and is recorded here saying so, "
        "because English DOES live in a SPICE deck (a `*` line, an in-line "
        "`$` or `;`) and this module's one UNANCHORED pattern, `_MEAS_WINDOW` "
        "= `\\b(from|to)=(\\S+?)(n?)\\b`, used to run over the whole file. "
        "MEASURED on a deck whose own comment read `* note: the reference run "
        "measured from=1000n to=2000n and is NOT shifted`: the count this "
        "function publishes as `meas_window_endpoints_shifted` included that "
        "comment, so it reported windows that never moved -- the exact "
        "vibe-ic#706/#711 shape, a sentence read as a declaration. Every "
        "reader now goes through `deck_code_only`, which blanks `*` lines and "
        "in-line `$`/`;` tails with `#` (not spaces: `\\s` matches newlines, "
        "so a space filler let `^(\\s*)` swallow the blanked lines and the "
        "rebuild deleted them) while preserving every offset. NO SENTENCE "
        "REACHES ANY REGEX HERE, and that is now a property of the MODULE "
        "rather than of one reader's audit of four patterns. Owner: lane "
        "mainred.",
    "analog_poweron_sequence::apply":
        "THE WRITER BEHIND `plan`, and it reads exactly what `plan` read: it "
        "re-finds the one supply card, the one pulse card and the tran card "
        "by the anchored patterns above, splices a `pwl`, a delayed `pulse` "
        "and a later stop time into their spans, and shifts every "
        "`from=`/`to=` endpoint by one clock period. SPICE CARD GRAMMAR HAS "
        "NO NEGATION FORM, so there is no sentence for polarity to be asked "
        "about -- but this function is the one where reading a sentence "
        "actually CHANGED AN ARTEFACT, which is why the exemption is stated "
        "from a measurement and not from the grammar alone. MEASURED before "
        "`deck_code_only`: on the deck above, `_MEAS_WINDOW.sub` rewrote the "
        "COMMENT line `* note: ... measured from=1000n to=2000n and is NOT "
        "shifted` to `from=2000n to=3000n` -- it overwrote a sentence that "
        "DENIED the value, in the deck that is handed to ngspice. It now "
        "substitutes through `_sub_in_code`, which finds each match in the "
        "blanked copy and splices into the ORIGINAL, so a comment can never "
        "be rewritten and no other byte moves; re-measured on the same deck, "
        "the two comment lines and an in-line `$ window from=9n` come back "
        "byte-identical while the real `.meas` window moves. The negative "
        "control is the same fixture with `deck_code_only` replaced by the "
        "identity: the comment moves again. Owner: lane mainred.",
    "metal_fill_config_gen::density_rule_layer_identifiers":
        "RUBY DRC-DECK GRAMMAR, read to answer which LAYER each of a deck's "
        "die-level density rules measures, so the fill config can be asked "
        "whether it carries an entry that rule can point at (#2148 follow-up, "
        "lane cz2135). The productions it matches are all deck code -- "
        "`<layer>.area` inside a rule block, and the deck-scope alias "
        "`<x>_area = <layer>.area` the block references -- and there is no "
        "form in that grammar that DENIES a layer: Ruby gives no way to write "
        "`metal2 is NOT the layer this rule measures`. NO SENTENCE REACHES "
        "ANY REGEX HERE, WHICH IS WHY THE POLARITY QUESTION HAS NO REFERENT, "
        "and that is a property of the CODE rather than of the deck: a rule "
        "block DOES carry English -- the `# Rule <id>:` header, the `##` notes "
        "beside it, and the human-readable violation message the rule prints "
        "-- and every input is put through "
        "`die_level_deck_rule_attribution.deck_code_only` before a single "
        "match runs. That helper blanks every quoted string and every `#` "
        "comment in ONE left-to-right scan that tracks both states together, "
        "keeping offsets so the deck's own line structure (which the section- "
        "banner block boundary is computed from) is unchanged. THE ENTRY WAS "
        "FALSE UNTIL THAT LANDED and is recorded here saying so: the function "
        "shipped reading the raw block first, which is exactly the #706/#711 "
        "shape, and the ratchet is what named it. MEASURED, NOT ASSERTED: all "
        "21 tokens of `_prose_polarity`'s own denial vocabulary -- both tiers, "
        "including the five CJK spellings -- each carrying a "
        "DECLARATION-SHAPED payload (`plant_layer.area / chip_area`), placed "
        "in each of the 4 positions a sentence can physically occupy in this "
        "production (the rule header comment, a `##` note line, a trailing "
        "`#` comment on the code line that forms the ratio, and the violation "
        "message string), moved 0 of 84 published answers -- 84 UNCHANGED, 0 "
        "moved. THE ZERO CARRIES BOTH CONTROLS. Negative control: the "
        "IDENTICAL payload spliced in as CODE moves the answer (`plant_layer` "
        "joins the rule's layer set), so the fixture could have moved and the "
        "zero is a statement about the grammar. Mutation: with "
        "`deck_code_only` replaced by the identity -- the strip deleted -- "
        "the SAME 84 trials move 84 of 84, so the strip is load-bearing and "
        "not decoration. AND THE FIRST STRIP WAS WRONG, WHICH IS WHY THE SCAN "
        "IS ONE PASS: a two-pass shape (regex-blank the strings, then cut at "
        "the first `#`) is wrong in both directions at once -- a `#` inside a "
        "message is not a comment, and an APOSTROPHE INSIDE AN ENGLISH "
        "COMMENT opens a string literal the regex closes far below, blanking "
        "live code in between. MEASURED on the two open decks in the pinned "
        "image, that shape dropped `PL.8` from a family of 8 and reduced the "
        "other deck's layer identifiers from six distinct names to NONE; the "
        "single scan restores both to the values the landing published. "
        "FINALLY, ABSENT IS ALREADY HOW THIS FUNCTION REPORTS IT: a rule "
        "whose block names no layer yields an EMPTY identifier list, its "
        "caller `density_rule_coverage` puts that rule in the UNCOVERED "
        "bucket, and `density_coverage_refusal` states it BY NAME -- so "
        "`decided` and `could not decide` already reach the reader as "
        "different answers, and the direction of any loss from the strip is "
        "toward the refusal, never toward a supplied value. Owner: lane "
        "cz2135.",
    "design_one_shot_runner::_chip_top_resolve_excluded_variant_params":
        "SYSTEMVERILOG MODULE-ITEM GRAMMAR, read to decide whether a wrapper "
        "parameter default selects a variant the design EXCLUDED from staging "
        "(#731, v1.17.85). The productions it matches are all HDL syntax -- "
        "`parameter <type tokens> <NAME> = <VALUE>` "
        "(`staged_rtl_closure_preflight._PARAM_RE`, and the flagged write is "
        "`wrapper_defaults[_m.group(1)] = _real.group(2).strip()`), module "
        "instantiations, `module <NAME>` definitions, `localparam <NAME> = "
        "<expr>` and generate conditions of the form `<PARAM> == <VALUE>` -- "
        "and there is no form in that grammar that DENIES a default: "
        "SystemVerilog gives no way to write `SecSBoxImpl is NOT SBoxImplDom`. "
        "NO SENTENCE REACHES ANY REGEX HERE, WHICH IS WHY THE POLARITY "
        "QUESTION HAS NO REFERENT. The two inputs are stripped before a single "
        "match runs: the wrapper header is matched on "
        "`_hdl_code_text.strip_hdl_comments_and_strings(param_block)` (the "
        "ORIGINAL is what gets sliced, so the emitted wrapper keeps its "
        "comments byte for byte), and every RTL file is put through THE SAME "
        "BLANKER on top of the `_strip_comments` that "
        "`staged_rtl_closure_preflight._gather` already applied. THAT SECOND "
        "BLANKING IS NOT BELT-AND-BRACES; IT CLOSES A HOLE THIS VERY CLAIM "
        "FOUND. `_gather` strips comments and leaves STRING LITERALS intact, "
        "and a Verilog string mints a declaration exactly as a comment does: "
        "measured while auditing this entry, a body carrying `initial "
        "$display(\"this variant is not used here: parameter sbox_impl_e "
        "SecSBoxImpl = SBoxImplCanright\");` survived the gatherer, was read "
        "by `_pf._PARAM_RE` as the module's own declared default, and RESOLVED "
        "the wrapper parameter to `SBoxImplCanright\"` -- closing quote "
        "included, spliced into the emitted wrapper as broken Verilog, out of "
        "an English sentence that DENIES it. That is #706/#711 arriving "
        "through a string instead of a sentence. The entry was written before "
        "that path was measured and was FALSE until the blanking landed; it is "
        "recorded here because an exemption whose argument was once wrong "
        "should say so. ABSENT IS ALREADY HOW THIS "
        "FUNCTION REPORTS IT, and its refusals are BY NAME rather than "
        "silent: a parameter no declaration names never enters "
        "`wrapper_defaults`, a guard it cannot evaluate is `UNREADABLE_GUARD`, "
        "an undeclared choice is `UNDECLARED_FREE_CHOICE`, and a set it can "
        "only partly spell is `INCOMPLETE_CANDIDATE_SET` -- so `decided` and "
        "`could not decide` already reach the reader as different answers, and "
        "the step that would have run yosys FAILs on either refusal. Its other "
        "input, `declared`, is not prose either: it is the L8 override RECORD, "
        "and a value that does not match `^(?:1'b)?([01])$` is ignored rather "
        "than interpreted. THE FOURTH AND LAST INPUT IS THE ONE PLACE FREE "
        "HUMAN TEXT REALLY DOES REACH A REGEX HERE, and it is the sharpest "
        "part of the argument rather than a hole in it: "
        "`_EXCLUDED_VARIANT_FILE_RE` is "
        "`^(?P<mod>[A-Za-z_]\\w*)\\.(?:sv|v)\\.unused-[\\w.+-]*excluded$`, "
        "whose `[\\w.+-]*` slot an operator fills with a hyphenated phrase "
        "saying WHY a variant was staged out. MEASURED: of the vocabulary's 21 "
        "tokens, 20 are spellable in that slot (`n/a` is not -- the grammar "
        "cannot carry a `/`), all 20 still read as denials in prose, and 0 of "
        "20 move the published answer, because only `mod` is captured. AND THE "
        "DIRECTION THAT DECIDES IT: a consult there would be a DEFECT, not an "
        "improvement. The marker's meaning comes from the naming CONVENTION, "
        "so `foo.sv.unused-not-excluded-at-all-excluded` is still a file the "
        "operator moved out of the staged tree, and a flow that read the `not` "
        "and skipped the marker would stage back a variant that was removed on "
        "purpose -- the exact failure this mechanism exists to prevent. Worse, "
        "the convention's REQUIRED terminal keyword is `excluded`, which IS a "
        "member of the vocabulary (`\\bexclud\\w*\\b`), so the consult would "
        "fire on EVERY marker of EVERY design and switch the mechanism off "
        "entirely. MEASURED by planting it: NINE of the fifteen tests in that "
        "fixture go red -- both core direction tests, all three older mutation "
        "tests, the end-to-end emit and the polarity sweep -- so the mechanism "
        "does not degrade under that consult, it stops. "
        "MEASURED, not asserted: all 21 denial tokens of "
        "`_prose_polarity`'s own vocabulary, placed in 11 positions a sentence "
        "can physically occupy in this production -- both comment forms and a "
        "Verilog string literal, in the wrapper header and in each of the two "
        "RTL files that decide anything -- each carrying a "
        "DECLARATION-SHAPED payload, INVERTED 0 values over 231 trials (231 "
        "UNCHANGED, 0 refused, 0 lost), while the IDENTICAL 231 strings read "
        "as PROSE carry 231 denials. THE ZERO CARRIES A NEGATIVE CONTROL: the "
        "same payloads spliced in as CODE move the published answer at 10 of "
        "the 11 positions (210 live trials), so it is a statement about the "
        "grammar and not about a fixture that could not have moved; the "
        "eleventh "
        "reads `_MODULE_DEF_RE` into `defined`, which a sentence can only ADD "
        "to and where adding never withdraws a candidate, and it is recorded "
        "rather than counted. The grammar is inert, not the vocabulary, so "
        "consulting `_prose_polarity` here would add a branch that can never "
        "fire, and a call that can never fire is a green light rather than a "
        "check. The direct precedents are the other HDL-grammar readers in "
        "this register: `sparse_fsm_detect::_sparse_enum_types`, "
        "`crosslayer_rewrite_equivalence::module_ports` and "
        "`digital_hardmacro_gen::read_interface`. Falsifier: "
        "`test_excluded_variant_param_is_derived_or_refused.py"
        "::test_the_not_prose_claim_for_the_wrapper_param_reader_is_"
        "falsifiable`, which RE-MEASURES the sweep and the negative control on "
        "every run rather than quoting the numbers above.",
    "analog_pdk_deck_context::subckt_geometry_param_names":
        "SPICE `.subckt` FORMAL-PARAMETER LIST, read to learn the names a "
        "foundry's own device subckt gives its geometry, because a MOS names "
        "them `w`/`l` while a passive commonly names them `r_width`/`r_length` "
        "or `c_width`/`c_length` and DEFAULTS those formals to bare `w`/`l`, "
        "which no deck defines. The production it matches is a card and its "
        "`+` continuations -- `.subckt <name> <nodes...> <formal>=<default> "
        "...` -- and there is no form in that grammar that DENIES a formal: "
        "SPICE gives no way to write `r_width is NOT the width`. THE ENTRY WAS "
        "FALSE UNTIL `spice_code_only` LANDED AND IS RECORDED HERE SAYING SO. "
        "The function shipped in this lane reading the card RAW, which is the "
        "#706/#711 shape exactly, and the ratchet is what named it -- the "
        "landing was refused twice before this argument was written, and the "
        "first sweep run against it returned a FALSE ZERO because the fixture "
        "chosen declared `w`/`l` directly and short-circuited before the "
        "suffix search that a sentence can actually reach. MEASURED, NOT "
        "ASSERTED, on the fixture whose answer that search DOES decide: all 21 "
        "tokens of `_prose_polarity`'s own vocabulary -- both tiers, including "
        "the five CJK spellings -- each carrying a DECLARATION-SHAPED payload "
        "that mints two rival geometry names (`the c_width = 3 is <token> the "
        "width, and c_length = 4 is <token> the length`), placed in each of "
        "the 7 positions a sentence can physically occupy in this production "
        "(a `*` comment above the card, a `;` and a `$` inline comment on it, "
        "a `+` continuation comment, a `*` comment inside the body, a quoted "
        "default on the card, and a `;` comment on `.ends`), moved 0 of 147 "
        "published answers. THE MUTATION IS THE OTHER ARM AND IT IS LOUD: with "
        "`spice_code_only` replaced by the identity -- the strip deleted -- the "
        "SAME 147 trials move 84, live at 4 of the 7 positions, so the strip "
        "is load-bearing and not decoration. THE ZERO ALSO CARRIES A NEGATIVE "
        "CONTROL: the IDENTICAL names spliced in as CODE (real formals on the "
        "card, and on a `+` continuation) DO move the published answer with "
        "the strip ON, so the fixture could have moved and the zero is a "
        "statement about the grammar. THE DIRECTION OF EVERY MOVE IS A LOSS, "
        "WHICH IS WHY IT MATTERED: two names match the dimension suffix, the "
        "reader publishes nothing, and the emitter falls back to `w=`/`l=` at "
        "a subckt that declares neither -- so a COMMENT could silently "
        "re-open the very defect this lane fixed. AND ABSENT IS ALREADY HOW "
        "THIS FUNCTION REPORTS IT: an ambiguous or unnamed dimension is "
        "OMITTED from the returned map rather than guessed, its consumer "
        "`known_family_context` publishes that omission in "
        "`device_geometry_params`, and A3 then emits the historical `w=`/`l=` "
        "-- so `read it` and `could not read it` stay different answers. THE "
        "STRIP IS ONE LEFT-TO-RIGHT SCAN tracking comment state and quote "
        "state TOGETHER, with quote state reset at every newline, because a "
        "two-pass shape is wrong in both directions at once: a `;` inside a "
        "quoted expression is not a comment, and an apostrophe inside an "
        "English comment would open a string a later pass closes far below, "
        "blanking live code in between -- the failure "
        "`metal_fill_config_gen::density_rule_layer_identifiers` records in "
        "this same register. It BLANKS and never deletes, so offsets and line "
        "structure survive byte for byte and the `+` continuation walk and the "
        "`.ends` search see the geometry they saw before. IT MOVES NOTHING "
        "REAL: measured against both installed open PDKs, every section, every "
        "device in the transitive closure, every geometry-unit verdict and the "
        "ENTIRE resolved `DeckContext` are IDENTICAL with the strip and with "
        "it deleted (sky130 51 sections / 191 subckts, gf180 50 / 71). "
        "FINALLY, A CONSULT HERE WOULD BE INERT RATHER THAN A CHECK: across "
        "the 412 real `.subckt` cards of the two open PDKs' transitive "
        "closures, `NEGATION_RE` fires on 0 raw cards and 0 code-only cards, "
        "so the branch could never run. The direct precedents are the other "
        "formal-grammar readers in this register: "
        "`design_one_shot_runner::_chip_top_resolve_excluded_variant_params`, "
        "`sparse_fsm_detect::_sparse_enum_types` and "
        "`analog_a3_netlist_emit::dc_op_rail_excursions`. Falsifier: "
        "`test_gf180_family_has_its_own_native_analog_device_template.py"
        "::test_the_not_prose_claim_for_the_subckt_formal_reader_is_"
        "falsifiable`, which RE-MEASURES both arms and the negative control on "
        "every run rather than quoting the numbers above, alongside "
        "`test_the_strip_moves_no_published_answer_on_the_real_open_pdks`. "
        "Owner: lane czgf180.",
    "analog_a3_netlist_emit::dc_op_rail_excursions":
        "NGSPICE OPERATING-POINT TABLE, the `<node> <voltage>` block the "
        "simulator prints on every `-b` run under `Initial Transient "
        "Solution` / `op`, read to learn whether the block's own nodes sit "
        "inside its own supply rails. This is machine-written report syntax "
        "and there is no form in it that DENIES a value: ngspice gives no way "
        "to write `xdut.nn1 is NOT 3.33717`. A row is printed or it is absent, "
        "and ABSENT IS ALREADY HOW THIS FUNCTION REPORTS IT -- the node never "
        "enters `worst`, no pair is returned, and the CALLER does not read "
        "that emptiness as a clean bill: `rail_invariant` records `CHECKED` "
        "against `NOT_MEASURED_NO_SUPPLY` precisely so `checked and clean` and "
        "`could not check` stay different answers. MEASURED, not asserted: all "
        "14 denial tokens of `_prose_polarity`'s own vocabulary, placed in 10 "
        "positions reachable in this production, INVERTED 0 values over 140 "
        "trials -- 129 REFUSE the row rather than flipping it, and the other "
        "11 are the token appearing INSIDE a node name (`xdut.never`), where "
        "the voltage is carried through unchanged and a node so named really "
        "is a node so named -- while the IDENTICAL strings read as PROSE carry "
        "140 denials. The grammar is inert, not the vocabulary. The one "
        "natural-language text anywhere near this reader is the `* condition:` "
        "commentary the A3 producer writes into the testbench it emits, and "
        "that never reaches here: this function is handed the SIMULATOR'S "
        "STDOUT, not the deck. The direct precedents are the other "
        "tool-artefact readers in this register: "
        "`spice_correlation_check::parse_sta_corner_basis`, "
        "`lec_post_layout_check::_parse_liberty_pins` and "
        "`phase3_one_shot_runner::_pdk_declared_routing_layers`. Falsifier: "
        "`test_a3_no_wall_clock_rail_invariant_and_pdk_request.py"
        "::test_the_not_prose_claim_for_the_op_table_reader_is_falsifiable`.",
    "analog_a7_post_layout_emit::remap_probes":
        "NGSPICE CONTROL CARDS of the A3 testbench -- `.save`, `meas`, `let` "
        "and `echo` -- read to point each hierarchical probe `v(<dut>.<net>)` "
        "into the extracted body (`v(<dut>.xrcx.<net>)`) and to take out the "
        "cards whose net the extraction no longer has. It publishes NO VALUE: "
        "what it writes is a node path and the NAMES of the measurements it "
        "took out, and the only thing that decides either is whether `<net>` "
        "is a member of the extracted netlist's node set. ngspice's command "
        "grammar has no form that DENIES a probe -- a card names a vector or "
        "it does not. The one natural-language text in an A3 testbench is its "
        "`*` commentary; a probe written inside a comment is rewritten or "
        "commented like any other text and changes nothing ngspice runs, and "
        "a card whose measurement name cannot be read is NOT listed, so the "
        "pre-layout key it produced is missing post-layout and the caller "
        "REFUSES (A7_POST_MEASUREMENT_MISSING) rather than reading silence. "
        "Direct precedents: `analog_a3_netlist_emit::tran_rail_report` and "
        "`analog_a3_netlist_emit::dc_op_rail_excursions`. Falsifier: "
        "`test_a7_q7_resim_fidelity.py::test_the_not_prose_claim_for_the_"
        "probe_remap_is_falsifiable`, which puts every identifier-shaped "
        "denial token of `_prose_polarity`'s own vocabulary into every name "
        "position of every card kind and requires the output to be the "
        "neutral-name output with the name substituted, while the same "
        "strings read as prose are denied. Owner: lane mig109.",
    "analog_real_corner_sweep::measurement_span":
        "NGSPICE TRANSIENT CARDS of the A3 testbench -- `tran <step> <stop>`, "
        "`meas tran <name> ...` with its `from=`/`to=`/`at=`/`td=` keywords "
        "and `trig`/`targ`/`when` clauses, and the `fourier`/`wrdata` command "
        "words -- read to learn how long the run must be for the cards it "
        "carries. It publishes TIMES (the stop, the last window end) and the "
        "NAMES of the cards that set or hold them. Keywords are matched in "
        "keyword position only, so a node or measurement spelled like a "
        "keyword is a name, and `*` comment lines are skipped. ngspice's "
        "measure grammar has no form that DENIES a window: a card states "
        "`to=` or it does not. Direct precedents: `analog_a7_post_layout_emit"
        "::remap_probes` and `analog_a3_netlist_emit::tran_rail_report`. "
        "Falsifier: `test_t130_a7_budget.py::test_the_not_prose_claim_for_"
        "the_span_reader_is_falsifiable`, which puts every identifier-shaped "
        "denial token of `_prose_polarity`'s own vocabulary into every name "
        "position of every card kind and requires the span to be the "
        "neutral-name span with the name substituted, while the same strings "
        "read as prose are denied. Owner: lane rfa7 (T130).",
    "analog_a7_post_layout_emit::measurement_span":
        "NGSPICE TRANSIENT CARD GRAMMAR, NO SENTENCE. The deck supplies "
        "`tran <step> <stop>` and `meas tran <name>` cards with fixed "
        "`from=`/`to=`/`at=`/`td=` fields. Comment lines are skipped; a "
        "card names a measurement or it does not, with no denial form. "
        "Only parsed time fields determine the stop and unresolved fields "
        "hold the declared stop. Falsifier: test_t130_a7_budget.py::"
        "test_the_not_prose_claim_for_the_span_reader_is_falsifiable; it "
        "puts every identifier-shaped denial word into every card name "
        "position and compares the result with a neutral-name deck while "
        "proving those words do deny actual prose.",
    "analog_a7_post_layout_emit::_echo_without":
        "An ngspice `echo \"MEAS k1=\" $&v1 \" k2=\" $&v2` CARD, rebuilt "
        "without the `key= $&var` pairs whose variable `remap_probes` took "
        "out. It reads the card's own `$&<var>` substitution syntax and the "
        "`<key>=` that precedes it -- the exact format A4's `_run_ngspice` "
        "parses back (`MEAS key= value`) -- and publishes no value: the "
        "removed KEYS are returned so the caller lists them as not compared. "
        "There is no form in this grammar that denies a pair; a pair is "
        "printed or absent. Falsifier: the same "
        "`test_the_not_prose_claim_for_the_probe_remap_is_falsifiable`, "
        "whose echo positions carry each token as a key and as a variable. "
        "Owner: lane mig109.",
    "analog_a3_netlist_emit::tran_rail_report":
        "NGSPICE `meas` RESULT ROWS, the `<name>=  <value> at=  <time>` lines "
        "the simulator prints for every `meas tran` card in a `.control` "
        "block, read to learn whether the block's own nodes stayed inside its "
        "own supply rails WHILE IT RAN -- the transient question the "
        "operating-point table above cannot answer (vibe-ic#2077). Machine-"
        "written report syntax again, and again there is no form in it that "
        "DENIES a value: ngspice gives no way to write `railx_max_nn1 is NOT "
        "3.33717`. A row is printed or it is absent, and ABSENT IS NOT "
        "SILENTLY A CLEAN BILL here either -- this function is handed the "
        "nodes that were ASKED for and returns `nodes_not_measured` as the "
        "asked-minus-answered set, alongside an `invariant` of CHECKED / "
        "NOT_MEASURED_NO_SUPPLY / NOT_MEASURED_NO_CARDS, precisely so that a "
        "deck whose cards ngspice refused cannot read as a transient that was "
        "checked. THE SECOND INPUT IS NOT PROSE EITHER, and it is the one "
        "difference from the operating-point reader beside it: the requested "
        "population comes from `rail_meas_nodes_requested`, which reads THIS "
        "PRODUCER'S OWN EMITTED CARDS off the deck. `_RAIL_MEAS_CARD_RE` "
        "anchors `meas tran railx_` at the start of a line, and every "
        "natural-language line an A3 deck carries -- the `* condition:` "
        "commentary and every `* _provenance:` line -- begins with the SPICE "
        "comment character, which that anchor cannot match. MEASURED, not "
        "asserted, by the falsifier below: all 14 denial tokens of "
        "`_prose_polarity`'s own vocabulary, in every position reachable in "
        "both productions, INVERT 0 values -- they refuse the row, or they "
        "appear INSIDE a node name, where a node so named really is a node so "
        "named -- while the IDENTICAL strings read as PROSE carry denials. The "
        "direct precedent is the other reader of this same simulator's output "
        "in this register, `analog_a3_netlist_emit::dc_op_rail_excursions`. "
        "Falsifier: `test_a3_transient_rail_measurement.py"
        "::test_the_not_prose_claim_for_the_meas_row_reader_is_falsifiable`.",
    "submission_template_fetch::technology_facts":
        "LEF `DATABASE MICRONS <n> ;` — the UNITS production of a PDK's own "
        "tech LEF, read inside the digest-pinned image to transcribe the "
        "database unit the TECHNOLOGY declares for the process this run "
        "targets (#2070). The text reaching the one regex in this function is "
        "a SINGLE machine-written line: the function greps the tech LEF for "
        "the record inside the container and parses only the matched line, so "
        "no sentence reaches it at all. LEF gives no form that DENIES a "
        "value: there is no way to write `DATABASE MICRONS is NOT 2000`, a "
        "record is emitted or it is absent, and ABSENT IS ALREADY HOW THIS "
        "FUNCTION REPORTS IT -- `value` stays None, `unavailable` names which "
        "of the five things it could not read, and the caller "
        "(`submission_template_answers`) then WITHHOLDS the field and "
        "publishes NOT_DETERMINED rather than a number. MEASURED, not "
        "asserted: all 15 denial tokens of `_prose_polarity`'s own vocabulary, "
        "placed in 8 positions reachable in this production, INVERTED 0 values "
        "over 120 trials -- the 30 that lose the value REFUSE it rather than "
        "flipping it -- while the IDENTICAL texts read as PROSE carry 112 "
        "denials. The grammar is inert, not the vocabulary, so consulting "
        "`_prose_polarity` here would add a branch that can never fire, and a "
        "call that can never fire is a green light rather than a check. THE "
        "PROSE THIS PROGRAM DOES READ IS NOT READ HERE: its other new reader, "
        "`declared_pdk_families`, reads L1's tapeout-target ROW, which IS "
        "prose and in which a family IS denied in practice -- and it re-matches "
        "nothing, delegating to phase 1's own extractor "
        "(`_extract_pdk_target_with_provenance` + `_declared_pdk_alternates`), "
        "whose `_FOUNDRY_NEGATION_RE` consult is why a row reading `the design "
        "targets no sky130 process` yields NO family and `no longer sky130; "
        "the target is gf180mcu` yields gf180mcu alone. That is also why this "
        "scanner does not flag it. The direct precedents are the other "
        "LEF/tool-artefact readers in this register: "
        "`pdk_via_patch_legalize::_routing_rules`, "
        "`pad_bterm_coincidence_check::layer_min_widths` and "
        "`phase3_one_shot_runner::_pdk_declared_routing_layers`. Falsifier: "
        "`test_issue2070_the_database_unit_is_a_technology_fact.py"
        "::test_the_not_prose_claim_for_the_tech_lef_reader_is_falsifiable`.",
    "final_summary_rollup_consistency_check::_parse_retired_tally":
        "ONE MACHINE LINE, NO SENTENCE. The tally `flow_compliance_check.py` "
        "printed before R-0915-85 -- `PASS=35  FAIL=0  MISSING=0  "
        "WAIVED-DEFERRED=3  SKIPPED=22  VACUOUS-PASS=3` -- quoted verbatim in "
        "a rendered final_summary.md. It is the checker's own f-string: "
        "nothing but `LABEL=N` tokens, and that grammar has no form that "
        "DENIES a count; `MISSING=0` is how it says none. The function reads "
        "ONLY a line that is entirely such tokens (`_TALLY_LINE_RE.fullmatch`) "
        "and carries the full retired quartet, so a sentence -- the report's "
        "own prose bullet, or any line with a word such as NOT in it -- is "
        "refused by construction and never reaches the counts. An absent "
        "tally is reported as absent, a FAIL naming it. The renderer's "
        "five-word reader of the same line is "
        "`final_report_generate::_parse_audit_tally`. Falsifier: "
        "`test_issue428_final_summary_rollup_consistency.py"
        "::test_the_not_prose_claim_for_the_retired_tally_reader_is_falsifiable`.",
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
    "sparse_fsm_detect::_decision_entries":
        "THE SAME FIVE SYSTEMVERILOG PRODUCTIONS `sparse_fsm_detect."
        "detect_text` classifies, COUNTED rather than classified, so that a "
        "sweep can state whether it entered the sparse/dense decision at all "
        "(vibe-ic#2102). Each is HDL syntax: a `prim_sparse_fsm_flop` "
        "instantiation carrying a `.state_i` connection, a "
        "`PRIM_FLOP_SPARSE_FSM` macro USE, an `(* fsm_encoding = ... *)` "
        "attribute on a declaration, a `typedef enum` body holding at least "
        "MIN_STATES sized based literals, and a `localparam`/`parameter` group "
        "of the same width. There is no form in that grammar that DENIES one: "
        "SystemVerilog gives no way to write `this enum is NOT declared`. A "
        "construct is written or it is absent, and ABSENT IS ALREADY HOW THIS "
        "FUNCTION REPORTS IT -- the count stays 0, the file is recorded "
        "`not_reached` WITH ITS REASON, and the run announces `VACUOUS_PASS` "
        "rather than a clean sweep, so an unread file and a judged one are "
        "already different answers. THE DIRECTION IS THE WHOLE ARGUMENT AND IT "
        "IS THE OPPOSITE OF THE USUAL ONE: a sentence here could only ADD a "
        "construct, never withdraw one -- a commented-out `typedef enum` read "
        "as a declaration would count 1 and turn a file this detector judged "
        "NOTHING in into a REACHED one, which is the false clean this "
        "disclosure exists to end -- and what makes that unreachable is that "
        "the function calls `_strip_comments` and `_strip_macro_definitions` "
        "ITSELF, before its first match, exactly as its sibling "
        "`sparse_fsm_detect::_sparse_enum_types` does and for the same reason. "
        "A denial cannot subtract, because the construct it denies never "
        "entered the match. The one place natural language appears in this "
        "input is the comment block in which OpenTitan documents the "
        "encoding's Hamming histogram, and it is stripped before it is read. "
        "The direct precedents are the other HDL-declaration readers in this "
        "register: `sparse_fsm_detect::_sparse_enum_types`, "
        "`crosslayer_rewrite_equivalence::module_ports` and "
        "`testbench_gen::package_first_order`. Falsifier: "
        "`test_issue2102_sparse_fsm_detect_discloses_its_reach.py"
        "::test_the_not_prose_claim_for_the_reach_counter_is_falsifiable`, "
        "which drives a commented-out FSM through the counter and requires it "
        "to count nothing, and re-measures the strip rather than quoting it.",
    "spec_coverage_check::_rtl_declared_widths":
        "VERILOG DECLARATION GRAMMAR, read to learn the bit WIDTH each signal "
        "was declared at so #2167 can ask whether a testbench literal's SIGNED "
        "and UNSIGNED readings differ at that width. The one production it "
        "matches is HDL syntax -- `<input|output|inout|wire|reg|logic|var|bit> "
        "[signed|unsigned] [<hi>:<lo>] <name>[, <name>]*` closed by `;`, `,`, "
        "`=`, `)` or a newline -- and there is no form in that grammar that "
        "DENIES a declaration: Verilog gives no way to write `a is NOT eight "
        "bits wide`. A signal is declared at a width or its width is not "
        "known, and ABSENT IS ALREADY HOW THIS FUNCTION REPORTS IT: a range "
        "whose bounds are not both plain integer literals (`[WIDTH-1:0]`, "
        "`[8*4-1:0]`, `[`W-1:0]`, a malformed `[31 0]`) yields NO ENTRY rather "
        "than a guessed default, its caller "
        "`_rtl_signed_operand_widths` publishes `None` for that operand, and "
        "`_literal_readings_differ` then declines to judge an unsized literal "
        "instead of assuming a width -- so `decided` and `could not decide` "
        "already reach the reader as different answers, and the direction of "
        "the refusal is toward the coverage GAP that still BLOCKS, never "
        "toward a supplied value. "
        "THE ENTRY WAS FALSE WHEN IT WAS FIRST DRAFTED AND IS RECORDED HERE "
        "SAYING SO. The drafted argument was `it strips comments first`, and "
        "`_specrtl_common.strip_comments` blanks COMMENTS ONLY: a Verilog "
        "string mints a declaration exactly as a comment does. MEASURED on "
        "1172bd02bff1 before the fix, `initial $display(\"port a is NOT four "
        "bits wide: input signed [3:0] a;\");` was read as `a`'s own "
        "declaration, set its width to 4, and FLIPPED the published #2167 "
        "signedness verdict from EXERCISED to NOT -- #706/#711 arriving "
        "through a string, in the very function this gate had flagged. "
        "MEASURED, NOT ASSERTED, after the fix: all 21 tokens of "
        "`_prose_polarity`'s own denial vocabulary -- both tiers, including "
        "the five CJK spellings, each asserted by the sweep to still read as a "
        "denial in prose -- each carrying a DECLARATION-SHAPED payload "
        "(`input [7:0] plant_sig;`), placed in each of the 5 positions a "
        "sentence can physically occupy in a Verilog file (line comment, block "
        "comment, string literal, and the UNTERMINATED form of the last two), "
        "moved 0 of 105 published answers -- 105 UNCHANGED, 0 moved -- where "
        "the same 105 trials against the pre-fix body move 42, all 42 through "
        "a string. THE ZERO CARRIES ITS NEGATIVE CONTROL: the IDENTICAL "
        "payload spliced in as CODE moves the answer (`plant_sig` joins the "
        "map at width 8), so the fixture could have moved and the zero is a "
        "statement about the grammar. "
        "THE STRIP IS TWO HALVES AND EACH IS LOAD-BEARING IN THE OPPOSITE "
        "DIRECTION. `_hdl_code_text.strip_hdl_comments_and_strings` (the "
        "shared #731 blanker, not a private copy) runs FIRST because its ONE "
        "left-to-right alternation is what gets the nesting right -- a `//` "
        "inside a string is not a comment and a `\"` inside a comment is not a "
        "string opener, and two sequential passes get exactly those two cases "
        "backwards -- and `strip_comments` runs SECOND, on residue, where it "
        "still truncates an UNTERMINATED block comment the blanker leaves "
        "alone by design. The blanker's other honest limit, an unterminated "
        "STRING, is closed HERE and not in the shared module (three other call "
        "sites depend on its offset-preserving contract) by cutting the text "
        "at any `\"` that survived both strips -- every such quote is an "
        "unterminated opener, and cutting drops declarations rather than "
        "inventing one. That cut is NOT sufficient on its own and is not "
        "decoration either: MEASURED over this checkout's 31 *.v/*.sv files, "
        "the cut WITHOUT the blanker changes the answer on 17 and empties 3 "
        "outright, while the shipped pair is byte-identical to the pre-fix "
        "body on all 31 -- so the fix closes the sentence path and moves "
        "nothing on real RTL. Finally, a strip that RAISES yields `{}`: "
        "could-not-read is not read-and-empty, and the raw-text fallback the "
        "function shipped with was the one remaining path on which a sentence "
        "could reach the regex at all. "
        "SCOPE, STATED SO THE ENTRY DOES NOT OVERCLAIM: this covers "
        "`_rtl_declared_widths` and nothing else. Its sibling "
        "`spec_coverage_check::_rtl_signed_operand_names` (#2152, already on "
        "main) reads the same file through the same comments-only strip and "
        "MEASURABLY still mints a signed operand, and an alias for one, out of "
        "a denying sentence in a string; that gate does not flag it because it "
        "writes to a set rather than to a record, its error direction is to "
        "ADD drive targets (the coverage-granting direction), and fixing it "
        "changes a shipped #2152 verdict path that this landing did not "
        "measure a corpus for. It is a NOTE in the landing commit and not an "
        "issue, because the hole is in that function's grammar and NOTHING IN "
        "THE TREE REACHES IT: measured over both real-input populations -- the "
        "31 *.v/*.sv files in the checkout (19 carrying a string literal after "
        "comment stripping) and the 5461 HDL-shaped string constants across "
        "the tree's 5492 *.py (363 carrying one) -- 0 of those 382 "
        "string-carrying inputs move the answer, while the three shapes that "
        "WOULD (a declaration, a `$signed(` cast, and the alias hop, each "
        "inside a `$display` string) each make the same comparison fire when "
        "planted into a real file of this tree. Owner ruling, lane cz2167b. "
        "The direct precedents are the other "
        "HDL-declaration readers in this register: "
        "`crosslayer_rewrite_equivalence::module_ports`, "
        "`sparse_fsm_detect::_sparse_enum_types` and "
        "`design_one_shot_runner::_chip_top_resolve_excluded_variant_params`, "
        "whose argument this one repeats deliberately -- that entry was also "
        "false until a string blanking landed. Consulting `_prose_polarity` "
        "here would add a branch that can never fire now that no sentence "
        "reaches the regex, and a call that can never fire is a green light "
        "rather than a check. Owner: lane cz2167b. Falsifier: "
        "`test_issue2167_signedness_is_exercised_not_spelled.py"
        "::test_no_sentence_reaches_the_declared_width_regex_from_any_position` "
        "with its negative control "
        "`::test_the_zero_carries_its_negative_control` and its mutation arm "
        "`::test_the_pre_fix_body_leaks_and_leaks_through_the_string_path`.",
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
    "clock_plan_check::_sdc_primary_clock_sources":
        "SDC `create_clock ... -name <n> [get_ports <p>]` commands, parsed after "
        "`#` comments are stripped (the same comment rule as `_sdc_clock_names`). "
        "SDC is a Tcl command grammar: a clock is created by the command or it "
        "is not, and no neighbouring text can deny it -- a disabled clock is a "
        "deleted or commented command, which the strip removes before matching.",
    "phase3_one_shot_runner::_build_auto_silicon_sdc":
        "The builder's direct text match reads only Liberty's fixed-format "
        "`time_unit : <number><unit>` attribute. C-style and line comments "
        "are blanked before matching, so a disabled unit cannot replace "
        "the active one. Design-doc claims and SDC inputs are read by "
        "delegated resolvers that consult their own contracts; this builder "
        "records their already resolved DRV arguments. Falsifier: "
        "test_step7_asic_sdc_is_authored_once_at_step7.py::"
        "test_commented_liberty_time_unit_cannot_scale_the_auto_sdc, which "
        "compares commented ps claims with the active ns attribute.",
    "phase3_one_shot_runner::_select_placement_arm":
        "The runner's OWN marker line `DIRECT_ARM_CHECK_PLACEMENT_VIOLATIONS <n>`, "
        "printed by `_build_check_placement_verdict_tcl` in the arm deck this "
        "function writes, carrying `check_placement -no_abort`'s integer. It is "
        "a fixed-format record, not a sentence: the count is the only field, a "
        "raise prints a different marker (`_RAISED`), and an absent marker is "
        "read as NOT_MEASURED, never as zero.",
    "librelane_cts_hold::execute":
        "The runner-emitted pnr.tcl's own `read_sdc <path>` command line: a Tcl "
        "command the deck builder writes as the first token of a line, read "
        "back only to find which SDC file the SAME deck times with. Tcl has no "
        "form that DENIES a command: the line is `read_sdc` with a path or it "
        "is not, and a comment (`#`) never starts with `read_sdc`, so the "
        "`(?m)^read_sdc` anchor cannot match prose. Same class as "
        "`design_one_shot_runner::step_full_stack_tb_gen` (runner-owned "
        "generated source parsed back). Absent the line, the deck's default "
        "PnR SDC path is used, and the path is only an input to the step -- no "
        "declaration is written from it.",
    "librelane_contract::def_supply_tcl":
        "A tool-written DEF's SPECIALNETS `- <net> ... + USE POWER|GROUND ;` "
        "and PINS `- <pin> + NET <net> ... + DIRECTION <dir> ;` productions "
        "(LibreLane OpenROAD.GeneratePDN / PadRing output). DEF has no form "
        "that DENIES a net's USE or a pin's NET: an attribute is present in the "
        "production or it is not, and nothing outside the `;`-terminated "
        "statement can take it back. Same grammar, same reason as "
        "`phase3_one_shot_runner::_def_specialnet_iterm_map` (SPECIALNETS) and "
        "`digital_hardmacro_gen::_specialnet_entries`. It creates only nets the "
        "DEF itself marks POWER/GROUND and only pins bound to them; a missing "
        "DIRECTION falls back to INOUT, the DEF default for a supply pin.",
    "phase3_one_shot_runner::_librelane_placed_ring_evidence":
        "Two machine grammars, no sentence. (1) The runner-emitted pnr.tcl: its "
        "own `puts \"LIBRELANE_PLACEMENT_CONSUMED: <path>\"` line, written by "
        "`librelane_contract.placement_consumer_tcl`, and the `read_def <path>` "
        "command before it, both anchored at line start, where a Tcl comment "
        "(`#`) cannot match; Tcl has no form that denies a command. (2) Tool-"
        "written DEF COMPONENTS / NETS / SPECIALNETS productions, read through "
        "`_pad_ring.parse_def` and `_def_net_members`: a component or terminal "
        "is listed or it is not, the same grammar and reason as "
        "`_def_specialnet_iterm_map` above. Nothing is declared from either: "
        "an absent line, component or terminal is a FAIL finding, never a "
        "default.",
    "tap_row_coverage_check::read_lef_masters":
        "Library-LEF MACRO productions (`CLASS`, `SIZE <w> BY <h>`, and per PIN "
        "`USE`, `DIRECTION`, `LAYER`, `RECT`), each anchored at line start inside "
        "its own `MACRO <name> ... END <name>` block. LEF is a formal grammar: a "
        "statement is present or absent and has no form that DENIES it, and a "
        "LEF comment (`#`) never matches the anchored keywords. Nothing is "
        "declared from it: an absent SIZE is `None` (the audit then refuses the "
        "master, NOT_MEASURED), and a master whose supply pins draw no well "
        "shape is simply not counted as a tie. Falsifier: calibration/"
        "tap_coverage_cells.lef, copied verbatim from the PDK cell LEF, drives "
        "the instrument's positive and negative pair. (T96, lane mig96.)",
    "librelane_contract::prune_pdk_root_cache":
        "Directory NAMES under the PDK-root cache, which `_materialise_image_pdk` "
        "itself creates as the 64-hex image ID (`<cache>/<hex>/<pdk>`), matched "
        "with one anchored `fullmatch` to select this resolver's own copies, plus "
        "docker's `{{.ID}}` / `{{.Source}}` template output, one field per line. "
        "No sentence is read: a name has no form that DENIES it, and a name that "
        "does not match is simply not a copy and is never touched. (F25, lane "
        "migf25.)",
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
    "phase3_one_shot_runner::_pdn_em_first_pass_resize":
        "The gap is read from the flow's own OpenROAD Tcl `puts` record, "
        "not from a design document or a diagnostic sentence. "
        "`_pad_connected_ring_tcl` emits `PDN_PAD_RING_PLAN: placed_pads=4 "
        "power_pads=2 side_power_pads=2 gap=17.44um configured_offset=6um "
        "fitted_offset=6um footprint=4.9um clearance=0.46um "
        "layers=Metal4 Metal5 pad_layers=Metal2`. The reader accepts that "
        "whole fixed-field production, anchored at both line ends, with "
        "numeric fields and layer identifiers. This grammar has no denial "
        "production: inserting `not` before or after `gap=17.44um` makes "
        "the record invalid, so no gap is declared. The companion PDN test "
        "checks that such an annotated line yields NOT_MEASURED. The ring "
        "refusal and inert records are separate productions, not alternative "
        "polarity for the gap field.",
    "eda_report_audit::_check_antenna":
        "The counts are machine-written whole-line records from OpenROAD "
        "check_antennas or the runner's report writer. Accepted grammar is "
        "`[INFO ANT-0002] Found 2 net violations.` (also a bare `Found` "
        "line), `antenna check: 2 net violations, 1 pin violations`, or "
        "`antenna clean: NO`; each numeric/status field is anchored at both "
        "line ends with no free-text field. Negative example: `Not Found 0 "
        "net violations.` and `antenna not clean: YES` do not match any "
        "production and cannot declare zero or clean. The companion antenna "
        "test executes the audit on these denial lines and expects no count. "
        "A report with no recognized production is refused for lack of a count; a "
        "negation cannot be interpreted as a clean result.",
    "phase3_one_shot_runner::_pdn_em_width_floor":
        "The matches read machine-produced EM report fields plus the LEF "
        "MANUFACTURINGGRID production. These formal measurement grammars cannot "
        "deny their numeric tokens in surrounding prose.",
    "phase3_one_shot_runner::_build_pdn_tcl":
        "The new MAXWIDTH and SPACING reads take only complete, semicolon-"
        "terminated numeric statements from a named ROUTING LAYER block in "
        "technology LEF. Hash comments are removed before matching, and the "
        "patterns anchor both ends of the statement. LEF has no production "
        "for 'not MAXWIDTH 5 ;' or 'SPACING 9 ; denied'; neither can match. "
        "A missing MAXWIDTH remains unknown rather than an invented cap. "
        "The companion PDN test injects denial text and checks it cannot "
        "change the emitted width or feasibility decision.",
    "release_docs_check::_parameter_values":
        "SystemVerilog parameter declarations are formal HDL grammar. A parameter "
        "is declared with an expression or is absent; HDL has no prose denial "
        "form that could reverse the extracted integer value.",
    "release_docs_check::constraint_ids":
        "The matcher reads the repository's mandatory-constraint row grammar, "
        "whose identifier and text fields are explicitly delimited. It is a "
        "machine document production, not free prose from which a value is inferred.",
    "crosslayer_rewrite_equivalence::module_ports":
        "A Verilog-2005 / SystemVerilog MODULE HEADER. The matched text is "
        "`module <name> #(...) (...) ;` and, inside it, the port declaration "
        "form `input|output|inout [wire|reg|logic] [signed] [<range>] <name>` "
        "-- productions of the HDL grammar, covering BOTH the ANSI form "
        "`module m(input wire [7:0] a, ...)` and the non-ANSI form "
        "`module m(a, b); input [7:0] a;` -- written by a synthesis-bound "
        "source file, in which there is no form that DENIES a port: Verilog "
        "gives no way to write 'this module does NOT have an input named clk', "
        "or 'a is NOT an input'. What the function returns is not a claim "
        "about the design read out of a sentence; it IS the module's "
        "interface, the same text the frontend elaborates, and the frontend "
        "-- not a neighbouring comment -- is what decides whether the port "
        "exists. A comment reading `// b is not used` leaves `b` in the "
        "elaborated interface, so honouring it would make this reader "
        "disagree with the compiler that consumes the wrapper it builds. A "
        "port either appears in a declaration or it does not, and absence is "
        "already how this function reports it: the name is simply not in the "
        "returned list, a module that is not found returns [], and the caller "
        "turns that into NOT_MEASURED rather than into an empty-but-fine "
        "wrapper -- so absence is refused rather than read as a value. The "
        "two defects this gate was built from (#706 pdk_target, #711 "
        "die_area_budget_um) both read English design documents, where denial "
        "is spellable and was spelled; consulting `_prose_polarity` on a port "
        "list would add a branch that can never fire, and a call that can "
        "never fire is a green light rather than a check. The direct "
        "precedents are `digital_hardmacro_gen::read_interface` (DEF PINS), "
        "`digital_hardmacro_check::parse_lef` and `_pad_ring::parse_def`.",
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
    "_pad_ring::parse_liberty_supply_view":
        "LIBERTY GROUP/ATTRIBUTE GRAMMAR, NO SENTENCE. The matched text is "
        "`voltage_map ( <name> , <number> )`, `nom_voltage : <number> ;`, "
        "the `cell ( <name> )`, `pin ( <name> )` and `pg_pin ( <name> )` "
        "group heads, and the simple attributes pg_type / voltage_name / "
        "is_pad / related_power_pin / related_ground_pin / direction, each "
        "`<attr> : <value> ;` -- productions of the Liberty format the PDK's "
        "IO library ships, whose values are a number, a keyword or a pin "
        "name, so no denial can be spelled: Liberty has no way to write 'this "
        "pin is NOT the pad'. Comments are blanked before anything is read, "
        "so a sentence (or a commented-out attribute) cannot lend a value. "
        "An attribute that is absent stays absent and its consumer refuses. "
        "Falsifier: tests/test_fx_supply_pad_pair_multi_rail.py::test_the_"
        "not_prose_claim_for_the_liberty_supply_view_is_falsifiable.",
    "_pad_ring::parse_verilog_bus_ports":
        "Verilog ANSI port-declaration grammar only: `module <id> ... "
        "endmodule` and `input|output|inout [<integer>:<integer>] <id>`. "
        "A range in this grammar has no negation production; an absent or "
        "non-literal range is omitted and the chip-top producer refuses the "
        "corresponding bit connection. Falsifier: "
        "tests/test_io_pad_chip_top_gen.py::test_bussed_pad_connection_is_"
        "one_ordered_verilog_connection.",
    "io_pad_chip_top_gen::run":
        "The only newly read text is the selected PDK IO Verilog model, passed "
        "to `_pad_ring.parse_verilog_bus_ports`, whose formal ANSI declaration "
        "grammar has no denial production. The reader runs only when a PDK LEF "
        "pin has an explicit bit subscript; otherwise no Verilog is read. "
        "Falsifier: tests/test_io_pad_chip_top_gen.py::test_emitted_bussed_pad_"
        "verilog_parses_in_the_pinned_eda_image.",
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
        'DEF `NETS` and `SPECIALNETS` entries, `- <net> ( <inst> <pin> ) ... '
        ';` productions emitted by the router or by OpenROAD '
        '`place_io_terminals` (which writes port nets as SPECIAL). DEF has no '
        'form that denies a connection: a '
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
    "dynamic_ir_vectored_emit::transient_blocks":
        "THE EMITTER'S OWN MARKERS, NO SENTENCE. `=== DYN_IR_REF <net> ... ===` "
        "and `=== DYN_IR PSM <net> ... ===` are `puts` lines this module writes "
        "into its own OpenROAD deck (`_build_transient_tcl`) before each solve; "
        "the reader only cuts the transcript at them and keys each block by "
        "(kind, net). No field is interpreted, so no denial can be spelled, and "
        "a net whose block is missing is ERROR_NO_PSM_IR, never a pass. "
        "Falsifier: tests/test_f20_dynamic_ir_decap_unit_label_and_basis.py"
        "::test_each_net_is_first_solved_quasi_static_as_the_reference.",
    "cpu_datapath_program::design_facts":
        "HDL PORT GRAMMAR, NO SENTENCE. The two patterns read (a) a port's "
        "packed range `[<msb>:<lsb>]`, the width string `testbench_gen."
        "resolve_dut` returns from the RTL's own port list, and (b) the "
        "identifier of an RTL input port to find the reset among the inputs "
        "the declaration did not already bind. Verilog cannot spell a denial "
        "in a range or an identifier; a port is declared or absent, and "
        "absent/ambiguous is already a named refusal (`the reset input ... is "
        "not unique`, `width ... does not resolve`). Every design VALUE the "
        "builder uses -- ISA base, memsize, roles, latency, reset vector -- "
        "comes from typed JSON fields, not from prose. Falsifier: tests/"
        "test_r0929_step5_bar_datapath.py::test_the_builder_refuses_what_the_"
        "input_does_not_state.",
    "mixed_signal_power_domain_run::derive":
        "THREE CLOSED MACHINE GRAMMARS, NO SENTENCE. The UPF text has the "
        "literal command/option arities checked by `power_model`, Liberty is "
        "balanced `cell`/`pin` groups with typed attributes, the native Yosys "
        "JSON is already structured, and the routed DEF contributes only its "
        "anchored `DESIGN` and counted `COMPONENTS` productions. A denial word "
        "cannot negate a component in any of these productions: an absent or "
        "mismatched declaration is a named `Refusal`, never a defaulted value. "
        "Falsifier: `test_red11_formal_input_polarity.py::"
        "test_m2_def_comment_denials_do_not_mint_components` adds denial-shaped "
        "comments and a live component control to the same fixture.",
    "project_outputs_in_tree_check::_auditor_diagnostic_text":
        "TYPED AUDIT-JSON GRAMMAR, NO SENTENCE. This reader accepts a unique-key "
        "JSON object with the required audit envelope, then removes only strings "
        "that fullmatch the producer's closed diagnostic shape `source -> path "
        "(live|dangling|outside-root)`. Free prose and malformed records remain "
        "available to the normal scanner; a denial cannot manufacture a typed "
        "diagnostic or reverse one. Falsifier: `test_red11_formal_input_polarity.py::"
        "test_auditor_diagnostics_do_not_treat_denial_prose_as_records`.",
    "pulse_width_rearm_conformance_check::_suite_paths":
        "SYSTEMVERILOG-COMMENT MARKER GRAMMAR, NO SENTENCE. The suite declares "
        "exactly three line-start `// PWR_<KEY>: <single-token-path>` markers; "
        "each resolved path must exist before the checker runs. A denial prefix "
        "does not open a marker and a denial-shaped token becomes a missing path, "
        "so neither can publish a fixture path or a conformance result. "
        "Falsifier: `test_red11_formal_input_polarity.py::"
        "test_suite_marker_denials_are_refused_or_ignored`.",
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
#:
#: EMPTY, AND THAT IS THE MEANING OF THE RULE, NOT A GAP IN IT. The sole entry
#: (`design_one_shot_runner::_chip_top_resolve_excluded_variant_params`, owner
#: lane czaes1, added by v1.17.85) was deleted in the commit that resolved its
#: offender -- as a `_NOT_PROSE` entry with its argument and its falsifier
#: (#2102 row 2), the function reading SystemVerilog module-item grammar out of
#: text its own two gatherers have already stripped. An entry that outlives its
#: offender is itself an offender and `_ratchet_verdict` refuses it, so leaving
#: this one behind would have moved the red rather than closed it.
_OFFENDER_REGISTER: Dict[str, str] = {}


def scan(root: Path) -> List[str]:
    """`module::function` for every polarity-blind prose extractor."""
    _instrument_calibration.assert_calibrated(
        "prose_polarity_consulted_check::scan")  # R-0915-86(3)
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
              f"register. DELETE those lines from "
              f"programs/{_BASELINE_NAME} as source,\n"
              f"           in the commit that made them polarity-aware. "
              f"Reviewed like code, in the diff.")
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
