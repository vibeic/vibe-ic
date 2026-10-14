#!/usr/bin/env python3
"""phase1_expert_parse_track.py — the SECOND track of Phase 1.

ENFORCEMENT: advisory
(Advisory describes the FINDINGS. The track's EXECUTION is mandatory — see
"A track that cannot fail silently" below.)

The gap this closes
-------------------
The doctrine is program-first + AI-backup DUAL-TRACK CONVERGENCE: two tracks
solve the same problem INDEPENDENTLY, then their disagreement is root-caused.
Phase 1 shipped with one track.

  * `ai_deep_review_patches.json` is read by three gates
    (`l_doc_structured_field_count_check`,
    `phase1_doc_input_completeness_check`,
    `phase1_input_vs_generated_completeness_check`) and written by NOTHING.
  * No Phase-1 program invokes the IC Expert to parse anything. Of everything
    referencing `ic_expert_db` / `ic-expert-agent`, most is the DB's own
    tooling (query, capture, health audit, consistency gate, digest renderer);
    the rest is a scope guard, a benchmark dispatcher, a clock-form check, the
    PHASE-2 design runner, an enhancement emitter, a lint and a coverage check,
    and the backup-pack assembler. Not one is a Phase-1 parser.
  * `phase1_doc_one_shot_runner` has no AI-track call site.

So `_split_ai_vs_program()` in the completeness gate is not a track, it is a
COUNTER: it partitions L-doc content that already exists into "AI-patched" vs
"program-extracted" and totals it. With nothing writing the sidecar,
`ai_captured_tokens_count` can only ever be 0. A measured run:
`tokens_missing_everywhere: 52`, `ai_captured_tokens_count: 0`,
`alias_captured_tokens_count: 0` — which reads as the AI performing badly and
is actually the second track never having run at all (issue #312).

What this program is
--------------------
An INDEPENDENT reader of the same design input. It does not consult the
program track's L-docs to decide what SHOULD be there; it derives that from
expert knowledge and the design's own input, and only then compares.

  1. RETRIEVE — expert knowledge for this design, from the assets the IC
     Expert Agent owns: the design-class craft in
     `agents/ic_expert_db/ic_expert_db.json` (via `ic_expert_db_query`) and
     the distilled expert skills in `agents/ic-expert-agent.md` (via
     `_lesson_digest`). Same assets, same retrieval as the authoring path.
  2. EXPECT   — turn the applicable knowledge into CONCRETE, NAMED expectations:
     "this input should have produced <entry> in <layer>", each carrying the
     input evidence it rests on and the verbatim expert lesson it comes from.
  3. COMPARE  — check each expectation against what the program track actually
     emitted, ONE BY ONE.
  4. NAME     — every unmet expectation becomes its own finding, identified by
     rule AND subject. Not a count. `2 expectations unmet` tells nobody what to
     do; `EXPERT_TRACK_EXPECTATION_UNMET::nvm_program_supply::<macro>/<pin>`
     does.

Two sub-tracks, because knowledge splits into two kinds
------------------------------------------------------
  * DETERMINISTIC sub-track — expert knowledge that is machine-evaluable
    against the design's own input. Always runs, needs no LLM. This is where
    a convention with a decidable structural signature lives.
  * AI sub-track — the open-ended reading no rule captures. Handed to the
    `vibe-ic:ic-expert-agent` subagent through `ic_expert_backup_pack`, which
    is the assembler this doctrine already built for exactly this hand-off.

The AI sub-track's answer is CONVERGED, not filed (#312, second landing)
------------------------------------------------------------------------
The first landing of this track wired the AI half as far as reading the
subagent's answer back — and stopped there. Two measured defects made that
half inert, and between them they reproduced, one nesting level in, the exact
shape #312 was filed about:

  1. THE HAND-OFF WAS GATED ON A BACKEND IT DOES NOT USE. `ai_subtrack`
     returned early unless `llm_semantic_confirm.backend_available()` — the
     probe for an in-process `anthropic` SDK plus `ANTHROPIC_API_KEY`. Nothing
     downstream of that probe uses either: `ic_expert_backup_pack.assemble` is
     pure deterministic assembly (retrieve, render two digests, write a
     descriptor), and the answer is authored by the `vibe-ic:ic-expert-agent`
     SUBAGENT, which is a Claude Code agent and imports nothing. So on every
     host without that SDK the track (a) never wrote the pack, so no
     orchestrator could invoke the agent on it, and (b) returned BEFORE the
     `answer.is_file()` check, so an answer sitting on disk was never read.
     A self-sealing loop: the state could never be left, and the reason it
     could never be left was a probe for a backend the path does not touch.
     MEASURED: all 8 published fleet designs reported SKIPPED-CONDITION.

  2. A CONSUMED ANSWER WAS DEAD DATA. Even with the probe forced true and an
     answer present, `evaluate` built findings from `DETERMINISTIC_RULES`
     ALONE. `ai["expectations"]` was serialised into the report and read by
     nothing — `phase1_expert_track_evidence_check` reads only `.status`.
     MEASURED on a published design: an expectation naming a field no L-doc
     contains produced `verdict: PASS`, `findings: 0`, which the evidence
     check then reports as RAN_EMPTY — "the track ran and named NO findings —
     a real zero". The AI's disagreement was rendered as an agreement.

So the fix is the CONVERGE step this doctrine's name already promises:

  * the hand-off and the read-back are unconditional — an `inline_llm_backend`
    fact is RECORDED, and never again allowed to veto a path that does not
    use it;
  * every consumed expectation is checked against the program track's own
    L-docs by `converge_ai_expectation`, DETERMINISTICALLY;
  * every disagreement becomes a named finding of its own, in the same list,
    with the same shape and the same `about: "design"` classification as a
    deterministic one — so it reaches the printed run output and flips the
    evidence check from RAN_EMPTY to RAN.

The comparator is deterministic ON PURPOSE, and it IGNORES any `met` the
answer supplies. An AI half that scored itself would agree with itself, and
"a consumer that reads the file and always agrees" is not a second track — it
is the first track with a witness.

A track that cannot fail silently
---------------------------------
This repo has just measured that 62 of its 72 gates cannot block anything
(#306). A second track that quietly does nothing would be the same disease in
a new place, so the failure modes are pinned:

  * THE AI HALF HAS NOT READ — the sub-track reports `HANDOFF_EMITTED` (the
    pack is written, the subagent has not answered) and emits a NAMED FINDING
    saying so. It is in the findings list, printed, and in the report. It is
    never absent, and never mistaken for "nothing to report". The whole track
    reports `INCOMPLETE` and exits `AWAITING_EXIT_CODE` (4): creating work for
    an expert is not the same event as consuming the expert's answer
    (issue #1973), and it is not a failed run either (issue #2014 D1). The
    report carries an `awaiting` block naming the subagent, the pack and the
    action that ends the wait; `execution.disposition` is `AWAITING`.
    This state replaced `SKIPPED-CONDITION`, which named the wrong fact: the
    obstacle was never a missing LLM, it was that nobody had invoked the agent
    — and the old wording pointed a reader at a host capability instead of at
    the one action that advances the track.
  * THE TRACK ITSELF FAILS — exit 1. The report is a MANDATORY output: the
    runner treats a missing or unparseable report as a Phase-1 failure. So the
    findings are advisory, but running is not optional.
  * THE AI HALF ANSWERED IN A SHAPE THIS CONSUMER CANNOT READ — verdict
    INCOMPLETE, exit 1, a named finding, and the printed `INCOMPLETE:` sentinel.
    NOT `CONSUMED`, and under no combination of the other half's results a
    `PASS`. This state was previously invisible: `data.get("expectations")`
    followed by `exps if isinstance(exps, list) else []` mapped every
    unexpected shape onto the empty list, and the record then read `CONSUMED —
    read 0 expectation(s)`, which is verbatim what an agent with nothing to
    say produces. MEASURED on a real run: an expert review that named two
    cross-layer defects in its own schema was flattened to `[]` and published
    as `verdict PASS, blocking False, 0 findings`. The answer existed and was
    discarded — worse than an ordinary silent pass, because the work was done.
    The refusal NAMES the top-level keys that did arrive, so a reader sees a
    schema mismatch and not an empty answer.
  * NOTHING WAS DECIDED — verdict INCOMPLETE, exit 1, with the reason stated
    per rule. Decided on the DENOMINATOR (`examined_expectations` —
    deterministic expectations from applicable rules plus every converged AI
    one), not on "did a rule apply": a rule can apply and produce no
    expectation, and the AI half can answer with an empty list. Both are zero
    denominators, and a zero denominator cannot complete the expert track —
    this repo's own `gate_zero_denominator_refuses_check`.

EXECUTION CREDIT (issue #1973) AND THE THIRD STATE (issue #2014 D1)
-------------------------------------------------------------------
The earlier runner contract accepted rc 2 as execution and reduced the whole
question to "did a JSON report get written?". That credited
`HANDOFF_EMITTED`, a schema-refused answer, and a genuinely empty answer as a
completed expert track. None of them is credited now: all three are
`INCOMPLETE`, `execution.complete` is false, and the printed `INCOMPLETE:`
sentinel says so. Design findings remain advisory after a real answer is
consumed; the existence and non-zero consumption of that answer are mandatory
execution evidence.

CREDIT AND FAILURE ARE DIFFERENT AXES, and #1973's repair moved both at once.
Withholding credit is right. Making the wait a FAILED RUN was not: a program
cannot spawn the subagent, so `HANDOFF_EMITTED` is what EVERY program-only
invocation produces, and D1's gate clause runs this program directly. MEASURED
on live main v1.16.87, clean Path-A project, program only: rc 1 -> Step D1
`FAIL` ("program failed: phase1_expert_parse_track ."), classified DESIGN_FACT
/ gate-reached-verdict, with step 1 recorded `derived-from-upstream (D1)`. D1 is
the flow's unconditional first step, so that is every design failing the front
door on a state none of them can avoid — a fact about the protocol reported as
a fact about the design.

So the two axes are separated, and the exit code carries three states, not two:
`AWAITING_EXIT_CODE` (4) for the hand-off awaiting its agent, 1 for a record
that cannot be read as either credit or a stated wait, 0 for a real reading.
See `AI_AWAITING_STATES`. The pending set is an ALLOW-LIST: a new failure state
inherits 1.

THE EXPECTATION'S OWN SCOPE IS CHECKED (#2127)
----------------------------------------------
An expectation carries a `layer` and a `field_path`. The comparator read the
first and printed the second. MEASURED on a published Phase-1 run: all 46
consumed expectations named a `field_path` under a top-level key
(`integration.` on L9, `constraints.` on L19) that the addressed layer document
does not declare at any depth — so every finding said

    expected L9.integration.register_map.offsets to carry: <requirement>.
    The program track produced: L9 does not carry [...]

about a field nothing had looked at. The whole layer was searched; the path was
decoration. Two consequences, both closed here:

  * THE PATH IS CHECKED. `field_path_status` compares it against the paths the
    layer document declares, and an expectation naming an undeclared one is
    REFUSED BY NAME (`RULE_AI_FIELD_PATH_UNDECLARED`), `about: "track"`. The
    refusal is ADDITIVE — `met` is still decided over the whole layer — because
    a guard that also moved verdicts could not be told apart from a comparator
    change. MEASURED: 46 of 46 refused on that run; every one of them is an
    authoring defect that had no name.

  * A MISS IS NOT AUTOMATICALLY AN EXTRACTION GAP. When the addressed layer
    misses and ANOTHER layer the program track wrote carries every expected
    token, the fact WAS extracted and the expectation asked the wrong layer.
    That is `RULE_AI_MISSCOPED`, `about: "track"`, naming the owning layer —
    never `about: "design"`. MEASURED on the same run: 11 of 43 disagreements,
    with owners L1_DATASHEET, L2_FRS and L4_REGMAP. Reporting those as missing
    extractions said the tree lacked facts it demonstrably had, and pointed a
    reader at an extractor for a defect that lives in the expectation.

The remedy for a mis-scoped expectation is its `field_path`, or a stated
layer-contract defect — never an extractor. A program cannot decide which of
the two, so the finding names both and decides neither.

AND THE OWNERSHIP ANSWER ITSELF CAN BE FALSE (#2191)
----------------------------------------------------
That misscope directive — "this is NOT a missing extraction and must not be
repaired in an extractor" — is only as good as the ownership test it rests on,
and the test had no floor. It read the WHOLE emitted document, envelope
included, and accepted any token. MEASURED (lane cz2191, host 8HD-4,
2026-09-08) over 482 distinct Phase-1 roots / 13,496 L documents, sampling
9,600 tokens from 120 of them: 58.3% of every (layer, token) ownership relation
was carried ONLY by text the emitter writes ABOUT the document — its
classification stamp, its provenance, the hints it gives an extractor, the
paths of the files it read — and 323 of the 9,600 tokens were carried by EVERY
layer of their root while still being able to assert ownership. On one
`opentitan_aes` root the single token `crypto_accelerator`, a bare `ic_class`
stamp, made all nine of L19..L27 OWN a fact about mechanical transduction that
none of them states.

So the ownership answer is read over `_ownership_units` — the document minus
its envelope — and it needs a token that can tell one layer from another. When
no expected token can, the answer is REFUSED (`RULE_AI_OWNERSHIP_UNDECIDABLE`,
`about: "track"`) rather than returned as an empty list, because an empty list
already means "no layer carries this fact" and is published as a gap in the
DESIGN. `met` is untouched: it is still decided over the whole document, so no
verdict moves and none can be blamed on this guard.

AND THE QUESTION ITSELF CAN BE UNASKABLE (#2150 item 2)
-------------------------------------------------------
#2191 stopped the OWNERSHIP question being answered when it could not be
asked. The same substitution was still happening one level further down, in
the token comparison every verdict rests on.

`phrase_present` reduces both sides with `_norm` — lower-case, every run of
non-`[a-z0-9]` collapsed to one space. Two token shapes do not survive that
reduction as the thing the author wrote, and both are SILENT:

  * a token with NO `[a-z0-9]` character normalises to the empty string, and
    the function returns False on `if not want` BEFORE reading the haystack.
    False for every possible document, including one that states the token
    verbatim. MEASURED on the surviving opentitan_aes root: a CJK token the
    design input states at `phase1_prompt.md:9` was published as a gap in the
    design. This plugin's own briefs are written in Traditional Chinese, so
    the shape is chip-AGNOSTIC.
  * an ELLIPSIS is deleted with every other separator, so `writes ... are
    ignored` silently becomes a demand for the contiguous phrase `writes are
    ignored`. MEASURED: the same input states "writes to these registers are
    ignored" five times, the row was published as a design gap, and the #2150
    decision table then WITHDREW it with the reason that neither the input
    nor any layer states it "in this form". A true expectation deleted on the
    strength of a comparator defect.

ONE such token decides a whole row — `met` is `not missing`, and the
owning-layer answer is the INTERSECTION over the tokens — so the row falls
past every track branch into the design column. MEASURED on live main
610cae2cc: 4 of the 20 surviving DISAGREE rows, and they are one of exactly
FOUR root causes behind those twenty.

So `unaskable_tokens` names them and `RULE_AI_TOKEN_UNASKABLE` refuses them,
`about: "track"`. `met` is untouched, as with #2127's field_path guard and
#2191's ownership refusal: base vs fix on that root, 43 findings before and
43 after, 20 design / 23 track -> 16 design / 27 track, denominator 46
unchanged, and no row becomes an agreement. The refusal is deliberately not a
widening — teaching `_norm` to keep CJK was measured and moves nothing here,
and an ellipsis cannot be honoured at all without making the comparator
weaker the more an author writes.

`authoring_schema` declares the same two rules under `expected_tokens_rule`,
and the hand-off pack carries it: F5 as first landed gave the author a
project-derived vocabulary for `field_path` — the field an expectation only
DECORATES with — and "one or more tokens to compare" for the field every
verdict rests on.

On NOT writing the AI-patch sidecar
-----------------------------------
This track deliberately does NOT write
`phase1/ai_deep_review_patches.json`, even though that file's missing writer is
what exposed the missing track. The three gates that read it MERGE its contents
into the very haystack they then measure for completeness. A track that writes
its own expectations there would be scoring itself: tokens it supplied would
come back as "captured", and coverage would rise by exactly the amount the
track invented. That is the failure mode #309 named `rail_undeclared` — a
design manufacturing 100% coverage against rails that exist only inside its own
mapping.

The report records `ai_patch_sidecar_present` so the missing writer stays a
VISIBLE, separate fact rather than an inference. Closing it is a real task; it
needs a source of patches that is independent of the gate measuring them.

chip-AGNOSTIC. §4.05: reads design INPUT and the design's own generated L-docs.
Never an oracle, a golden artefact or a harness.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import _path_layout as _pl  # noqa: E402
# Module level for `SUBAGENT_TYPE` alone — the name of the agent the
# `awaiting` block has to hand a reader. `ai_subtrack` keeps its own
# guarded import for `assemble`, whose failure is a reportable state.
import ic_expert_backup_pack as _pack  # noqa: E402
import nvm_program_supply_intent as _nps  # noqa: E402
import _reference_flow_boundary as _rfb  # noqa: E402  §4.05 authority (FX_405)

PROGRAM = "phase1_expert_parse_track"
VERSION = "1.0.0"

_EXPERT_DB = (_HERE.parent / "agents" / "ic_expert_db" / "ic_expert_db.json")

RULE_UNMET = "EXPERT_TRACK_EXPECTATION_UNMET"
RULE_AI_SKIPPED = "EXPERT_TRACK_AI_SUBTRACK_SKIPPED"
# A disagreement the AI half named and the comparator confirmed. Deliberately a
# SEPARATE rule id from the deterministic `RULE_UNMET`: a reader must be able to
# tell which track raised a finding, or the two tracks stop being two.
RULE_AI_UNMET = "EXPERT_TRACK_AI_EXPECTATION_UNMET"
# An answer entry the comparator cannot decide either way. It is a finding
# about the TRACK, never silence: an undecidable expectation that vanished
# would make the AI half look like it agreed.
RULE_AI_UNUSABLE = "EXPERT_TRACK_AI_EXPECTATION_UNUSABLE"
# An answer file that PARSES but is not the shape this consumer reads. Its own
# rule id, because the remedy is different from every other one here: nothing
# about the DESIGN is in question, an answer exists and this consumer could not
# read it. Naming it `SKIPPED` would say the agent never answered, which is the
# opposite of what happened.
RULE_AI_ANSWER_SCHEMA_MISMATCH = "EXPERT_TRACK_AI_ANSWER_SCHEMA_MISMATCH"
# The agent answered, and its `expectations` list was genuinely empty. A real
# reading, and a real zero — reported so it can never be read as coverage.
RULE_AI_ANSWER_EMPTY = "EXPERT_TRACK_AI_ANSWER_EMPTY"
# The PACK ITSELF was not assembled (#2094). Its own rule id and `about:
# "track"`, because nothing about the DESIGN is in question: the hand-off went
# out carrying no target module and no interface contract for a class the
# expert DB profiles, i.e. an empty context that READS as an assembled pack.
# Every expectation the agent then writes is authored from the design input
# alone; a record that does not say so credits the pack for coverage it did not
# supply.
RULE_PACK_NOT_ASSEMBLED = "EXPERT_TRACK_PACK_NOT_ASSEMBLED"
# An expectation whose `field_path` names a path the layer it addresses does
# NOT declare (#2127). Its own rule id and `about: "track"`, because nothing
# about the DESIGN is in question: the expectation asked for a field that does
# not exist, and until #2127 the path was carried straight into the finding
# text as though it had been checked. MEASURED on a published Phase-1 run: all
# 46 consumed expectations named a `field_path` under a top-level key
# (`integration.` / `constraints.`) that neither addressed layer declares, and
# the findings read "expected L9.integration.register_map.offsets to carry ..."
# — an authoritative sentence about a field nothing ever looked at.
RULE_AI_FIELD_PATH_UNDECLARED = "EXPERT_TRACK_AI_EXPECTATION_FIELD_PATH_UNDECLARED"
# An expectation the addressed layer does not satisfy, where ANOTHER layer the
# program track wrote carries every one of its expected tokens (#2127). Its own
# rule id and `about: "track"`, because the fact IS extracted: reporting it as
# a design finding says the tree is missing something it demonstrably has.
# MEASURED on the same run: 11 of 43 disagreements — including 5 of the 10 the
# issue classifies as asking the wrong layer — have such a layer.
RULE_AI_MISSCOPED = "EXPERT_TRACK_AI_EXPECTATION_MISSCOPED"
# The ownership question could not be ASKED (#2191). Every expected token is
# carried by more than half the layers searched, so no token can tell one
# layer from another and the answer would decide nothing while reading as
# though it decided everything. `about: "track"`, its own rule id, and NOT
# `RULE_AI_UNMET`: an empty owning-layer list means "no layer carries this
# fact" and is published as a gap in the design, so answering a question that
# could not be asked with a design finding is the exact substitution this
# track exists to prevent. MEASURED on 482 Phase-1 roots (lane cz2191): before
# the content/floor guards, 323 of 9,600 sampled tokens were carried by EVERY
# layer of their root and every one of them could assert ownership.
RULE_AI_OWNERSHIP_UNDECIDABLE = "EXPERT_TRACK_AI_OWNERSHIP_UNDECIDABLE"
# An expectation naming a layer THE L-DOC TAXONOMY DOES NOT DECLARE (#2150).
# `about: "track"`, its own rule id, and deliberately NARROW.
#
# The wider reading was tried first and is wrong. "The root has no such
# document" is NOT by itself a track defect: `l_doc_taxonomy` declares 28
# layers, and a layer it declares that the root does not carry is the PROGRAM
# TRACK failing to emit a document its own taxonomy says applies — a real
# disagreement, and issue #312 pinned it as one on the grounds that silence
# there would be the original defect exactly. That test is right and this
# landing leaves its verdict alone.
#
# What the taxonomy CANNOT account for is a layer that does not exist in the
# contract at all. Then nothing was pointed at: the expectation addresses a
# document this plugin never emits for any class, so the miss is a fact about
# the EXPECTATION (or about the artefact it was computed from), and filing it
# as a design gap says the tree lacks a fact whose home the tree has never
# had. That is #2150 F11's shape — a decision table computed over a different
# Phase-1 root, whose OWNER cells name leaves the judged artefact lacks.
#
# MEASURED on the surviving opentitan_aes root (24 files / 23 codes; the
# taxonomy declares 28): `L24_SIGNOFF` IS declared by the taxonomy, so it
# stays a disagreement and only gains the taxonomy fact and an owning-layer
# answer; a name the taxonomy does not declare is refused here by name.
RULE_AI_LAYER_ABSENT = "EXPERT_TRACK_AI_EXPECTATION_LAYER_ABSENT"
# An expected token the comparator CANNOT ASK FOR (#2150 item 2, re-measured
# on live main 610cae2cc). `about: "track"`, its own rule id, and it does NOT
# fall through to `RULE_AI_UNMET` — for exactly the reason #2191 gave one
# level down: a question that could not be asked must never be answered with
# a gap in the DESIGN.
#
# `present_in_units` decides every token through `phrase_present`, which
# reduces BOTH sides with `_norm` — lower-case, every run of non-`[a-z0-9]`
# collapsed to one space — and then demands a contiguous run of haystack
# tokens. Two token shapes survive that reduction as something the author did
# not write, and both are SILENT:
#
#   * NO_MATCHABLE_CHARACTER — a token with no `[a-z0-9]` character at all
#     normalises to the empty string, and `phrase_present` returns False on
#     `if not want` BEFORE it reads the haystack. So the answer is False for
#     EVERY possible document, including one that states the token verbatim.
#     MEASURED on the surviving opentitan_aes root: the expectation
#     `l19-gcm-scope-disposition-underspecified` expects the token `五種`,
#     which the design input states verbatim at `phase1_prompt.md:9`
#     ("ECB / CBC / CFB-128 / OFB / CTR 五種 block cipher 操作模式"), and
#     `phrase_present("五種", <that very line>)` is False. The row was
#     published as a gap in the design. This plugin's own design briefs are
#     written in Traditional Chinese, so the shape is chip-AGNOSTIC and not
#     an opentitan_aes accident.
#   * ELLIPSIS_ERASED — `_norm` deletes `...` / `…` along with every other
#     separator, so `"writes ... are ignored"` silently becomes a demand for
#     the CONTIGUOUS phrase `writes are ignored`. The author wrote a pattern;
#     the comparator asked a different, stricter question and reported the
#     answer as the author's. MEASURED: the same root's input states "writes
#     to these registers are ignored" five times in `docs/aes_registers.md`,
#     and `l9-idle-gated-writes-are-ignored` was published as a design gap —
#     then WITHDRAWN by the #2150 decision table with the reason "neither the
#     input nor any layer states ['writes ... are ignored'] in this form".
#     A true expectation deleted on the strength of a comparator defect.
#
# ONE unaskable token is enough to decide a row: `met` is `not missing`, and
# the ownership answer is the INTERSECTION over the tokens, so a token no
# layer can carry empties `owning_layers` and the row falls past the misscope
# branch into the design column. MEASURED on live main 610cae2cc: 4 of the 20
# surviving DISAGREE rows are decided by one such token each.
#
# The refusal is the FLOOR, and it is deliberately not a widening. Whether
# `_norm` should preserve CJK is a separate question with its own blast
# radius; it was measured here and it moves NOTHING on this corpus — under a
# CJK-preserving normaliser no emitted layer carries `五種` either, because
# this root's L-docs are English-only. So the honest repair is to stop
# answering, not to answer differently.
RULE_AI_TOKEN_UNASKABLE = "EXPERT_TRACK_AI_EXPECTATION_TOKEN_UNASKABLE"
# A SPLIT expectation whose grammar is self-contradictory or empty (#2150).
# Reuses `RULE_AI_UNUSABLE` rather than inventing a token: an expectation the
# comparator cannot decide is one situation, and it already has a name. What
# is new is that a split can be undecidable in ways a single expectation
# cannot — no branches, a branch with no layer, a branch that itself splits,
# or a parent that states BOTH a split and its own `expected_tokens`.
SPLIT_KEY = "sub_expectations"
#: `field_path_status` / `layer_present` on a SPLIT parent. The parent
#: addresses no single field and no single layer, so answering DECLARED or
#: True for it would be a reading of one branch reported as a reading of the
#: expectation. The branches carry their own, per branch.
SPLIT_MARKER = "SPLIT"
# An expectation the author has WITHDRAWN, with the reason it was withdrawn
# (#2127, second addendum; the disposition #2132 reaches for 12 of its 30 rows).
# A withdrawn expectation is a DECISION, and a decision that leaves no trace is
# indistinguishable from an expectation the agent never wrote — so it is
# recorded, named and counted, and it is `about: "track"` because nothing about
# the design is in question.
RULE_AI_WITHDRAWN = "EXPERT_TRACK_AI_EXPECTATION_WITHDRAWN"
# A withdrawal carrying NO reason. REFUSED: the expectation is converged as if
# it had never been withdrawn, AND the refusal is named. Withdrawal is the one
# operation that can remove a row from what this track reports, so it is the
# one that must not be silent — "never silently delete" is not satisfied by a
# marker that says only that something was deleted.
RULE_AI_WITHDRAWN_NO_REASON = "EXPERT_TRACK_AI_EXPECTATION_WITHDRAWN_WITHOUT_REASON"

# A decision table sitting beside the pack that this artefact's own stamp says
# cannot describe it (#2150 item 6). REPORTED, and the table is NOT applied.
# The refusal is `about: "track"` because nothing about the design is in
# question: a table computed on another Phase-1 root makes claims about a
# DIFFERENT set of layer documents, and a wrong re-pointing reads exactly like
# a right one, so applying it hopefully is how a table stops being evidence.
RULE_DECISION_TABLE_NOT_APPLICABLE = "EXPERT_TRACK_DECISION_TABLE_NOT_APPLICABLE"

#: #2164. The retrieval query was built from a design input this reader could
#: not open. About the TRACK, never about the design: a pack assembled from
#: nothing says nothing about the chip, and the number derived from it is not a
#: measurement of the expert DB's coverage.
RULE_INPUT_NOT_READABLE = "EXPERT_TRACK_DESIGN_INPUT_NOT_READABLE"

# ── the AI sub-track's status vocabulary ────────────────────────────────────
#
# FIVE tokens, not three, because the three collapsed two pairs of genuinely
# different outcomes into one word each — and the report's ONLY downstream
# consumer (`phase1_expert_track_evidence_check`) reads the token and nothing
# else, so a collapsed token is a fact that no longer exists anywhere.
#
#   CONSUMED         an answer was read AND it carried expectations
#   CONSUMED_EMPTY   an answer was read and its `expectations` list was EMPTY.
#                    A real answer and a real zero. Split from CONSUMED because
#                    "the expert had nothing to add" is a legitimate result
#                    that a reader must be able to see AS a zero — under one
#                    token it is indistinguishable from a full reading, and
#                    that is the whole disease this track was built to cure.
#   SCHEMA_MISMATCH  the answer parses as JSON but is not `{"expectations":
#                    [...]}`. NOT a reading, NOT consumed, and never a PASS.
#                    The refusal NAMES the top-level keys that did arrive, so
#                    the reader sees a schema mismatch rather than an empty
#                    answer. MEASURED: one real expert review (verdict "gaps",
#                    complete false, two named cross-layer defects) used its own
#                    schema with no `expectations` key, was coerced to `[]` by
#                    `exps if isinstance(exps, list) else []`, recorded as
#                    "CONSUMED — read 0 expectation(s)", and published as
#                    verdict PASS / 0 findings. The answer existed and was
#                    discarded; a zero denominator passed instead of refusing.
AI_HANDOFF_EMITTED = "HANDOFF_EMITTED"
AI_CONSUMED = "CONSUMED"
AI_CONSUMED_EMPTY = "CONSUMED_EMPTY"
AI_SCHEMA_MISMATCH = "ANSWER_SCHEMA_MISMATCH"
AI_ERROR = "ERROR"
#: The states in which the AI half actually DELIVERED A READING. Everything
#: else — a refused answer, an error, a pack nobody answered — is not one.
AI_READ_STATES = frozenset({AI_CONSUMED, AI_CONSUMED_EMPTY})

# ── the THIRD state: waiting is not failing (#2014 D1) ──────────────────────
#
# `ai_subtrack` is a TWO-PASS protocol and says so in its own hand-off message:
# pass one writes the pack and reports HANDOFF_EMITTED — "invoke subagent
# vibe-ic:ic-expert-agent … and re-run to consume its answer". A PROGRAM cannot
# spawn that subagent, so pass one is what every non-agent invocation produces.
#
# MEASURED on live main v1.16.87, a clean Path-A project, program-only:
#
#     phase1_expert_parse_track .        -> rc 1
#     flow_compliance_check .            -> Step D1 FAIL
#                                           "program failed:
#                                            phase1_expert_parse_track ."
#                                           classified DESIGN_FACT /
#                                           gate-reached-verdict
#     step 1 (Spec-to-RTL)               -> "derived-from-upstream … (D1)"
#
# D1 is the flow's first step and has no `condition:`, so a rc that no
# single-pass input can avoid makes the front door unpassable for every design
# at once. That is not a fact about any design.
#
# THREE states, not two. `phase1_one_shot_runner._expert_track_disposition`
# already draws this line for the RUNNER's exit code (#2014, 1aa24ef268):
# CREDITED / PENDING / DEFECT. It could not draw it for the FLOW, because D1's
# gate clause runs THIS program directly and reads THIS exit code, where
# "nobody has answered yet" and "the answer is unreadable" were one number.
#
#   * AWAITING — a state the protocol defines and the next pass leaves.
#     Exit `AWAITING_EXIT_CODE`. Never credited (`execution.complete` stays
#     False, the verdict word stays INCOMPLETE, the `INCOMPLETE:` sentinel is
#     printed), and never a bare PASS in the roll-up: `flow_compliance_check`
#     maps rc 4 + that sentinel onto the #599 INCOMPLETE tier, which is the
#     word this repo already coined for "not audited, and someone must return".
#   * DEFECT   — ERROR, ANSWER_SCHEMA_MISMATCH, CONSUMED_EMPTY, or a status
#     this reader does not know. Still exit 1.
#
# THE SET IS AN ALLOW-LIST, deliberately: a producer that grows a new failure
# state inherits `1`, never the wait.
#
# CONSUMED_EMPTY IS NOT IN IT, and that is not an oversight. HANDOFF_EMITTED is
# an ORDERING state — the second pass has not happened. CONSUMED_EMPTY is a
# MEASUREMENT state — the pass happened and decided nothing, which is the zero
# denominator `gate_zero_denominator_refuses_check` exists to refuse. Only the
# first is left by re-running.
AI_AWAITING_STATES = frozenset({AI_HANDOFF_EMITTED})

#: Exit code for AWAITING. Not 0 (a naive `rc == 0` consumer must not credit an
#: unanswered hand-off), not 1 (that is a failed run), not 2 (`VACUOUS_PASS`
#: means "nothing applied", and #599 measured that this state is the opposite:
#: the input WAS applicable), not 3 (`_WAIVER_EXIT_CODE`).
AWAITING_EXIT_CODE = 4


def _program_expectations_digest(applicable) -> str:
    """SHA256 over the DETERMINISTIC expectations this run decided.

    The program-derived completion's own identity (R-0915-126-D1). It is
    deliberately NOT a digest of `l_doc_expectations.json`: that file is the
    AI's answer, the program never writes it, and crediting a program run
    against the AI's digest would make the two indistinguishable in the record.
    Canonical JSON so the digest is a function of the expectations and not of
    dict ordering.
    """
    payload = [
        {"rule": r.get("id") or r.get("rule") or r.get("name"),
         "expectations": r.get("expectations") or []}
        for r in applicable
    ]
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()

#: The three dispositions, recorded in the report so no consumer has to infer
#: one from an exit code. Same words as the runner's, on purpose.
DISPOSITION_CREDITED = "CREDITED"
DISPOSITION_AWAITING = "AWAITING"
DISPOSITION_DEFECT = "DEFECT"

_JSON_TYPE_NAMES = {
    dict: "object", list: "array", str: "string",
    bool: "boolean", int: "number", float: "number", type(None): "null",
}


def json_type_name(value: Any) -> str:
    """What a reader of the answer file would call this value's type."""
    return _JSON_TYPE_NAMES.get(type(value), type(value).__name__)


def answer_schema_mismatch(data: Any) -> Optional[Dict[str, Any]]:
    """`None` if the answer is the shape this consumer reads; otherwise a
    STATED description of what arrived instead.

    The description names the TOP-LEVEL KEYS PRESENT, never only the key that
    was wanted. "no expectations key" and "no expectations key, but here are
    the ten keys it does carry, including `cross_layer_inconsistencies`" send a
    reader to two completely different places, and only the second one is where
    the answer actually is.
    """
    if not isinstance(data, dict):
        return {
            "json_type": json_type_name(data),
            "top_level_keys": [],
            "why": (f"the answer's top level is a JSON "
                    f"{json_type_name(data)}, not an object"),
        }
    keys = sorted(str(k) for k in data)
    if "expectations" not in data:
        return {"json_type": "object", "top_level_keys": keys,
                "why": "the answer object carries no `expectations` key"}
    if not isinstance(data["expectations"], list):
        return {"json_type": "object", "top_level_keys": keys,
                "why": (f"`expectations` is a "
                        f"{json_type_name(data['expectations'])}, not a list")}
    return None

# Text extensions that count as design INPUT for expert retrieval.
_INPUT_TEXT_EXTS = (".md", ".txt", ".rst", ".adoc", ".yaml", ".yml", ".json")
_INPUT_TEXT_CAP = 200_000     # keep retrieval bounded on a large spec


# ── expert assets ───────────────────────────────────────────────────────────

def expert_db_lesson(ic_class: str,
                     db_path: Path = _EXPERT_DB) -> Optional[str]:
    """The verbatim first lesson of one expert-DB class.

    Looked up BY CLASS rather than through the lexical top-k. A rule that
    embodies a specific piece of craft must quote THAT craft; letting ranking
    decide would make a finding's justification depend on how the design's
    prose happened to score."""
    try:
        db = json.loads(db_path.read_text(errors="replace"))
    except (OSError, ValueError):
        return None
    for e in db.get("entries") or []:
        if isinstance(e, dict) and e.get("ic_class") == ic_class:
            lessons = e.get("lessons") or []
            if lessons:
                return lessons[0]
    return None


#: `input_text_report` status codes (#2164). FIVE states, and the reason there
#: are five is that four of them used to be spelled as the same empty string.
#: "I could not read it" and "I read it and it was empty" are different facts,
#: and a retrieval query built from the first is not a measurement of anything.
INPUT_READ = "READ"                       #: at least one character was read
INPUT_NO_TREE = "NO_INPUT_TREE"           #: <project>/input does not exist
INPUT_NO_FILES = "NO_FILES_AT_ALL"        #: the tree exists and holds no files
INPUT_UNREADABLE_FORMAT = "UNREADABLE_FORMAT"   #: files, none in a read format
INPUT_READ_AND_EMPTY = "READ_AND_EMPTY"   #: readable files, all of them empty

#: why a file under `input/` contributed nothing.
SKIP_UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
SKIP_ORACLE_PATH = "ORACLE_PATH"          #: deliberate §4.05 exclusion
SKIP_UNREADABLE = "UNREADABLE"            #: the file exists and would not open


def input_text_report(project: Path) -> Dict[str, Any]:
    """The design-input prose AND an account of what was left out.

    THE DEFECT THIS CLOSES, MEASURED (#2164). `input_text` returned a string
    and nothing else, so a project whose entire design input is a PDF returned
    `""` — indistinguishable from a project with no input at all, and from one
    whose files are genuinely empty. That empty string was then handed to
    `ic_expert_db_query.query` as a retrieval QUERY and to the AI sub-track as
    a PROMPT, and every consumer read the result as a measurement. Measured on
    the published corpus: TWELVE projects across five registered classes are in
    that state today, and one of them is a design of a class whose expert-pack
    profile was landed on a population that counted it.

    Returns the text (identical to what `input_text` returns) plus `status`,
    the files that were READ, the files that were SKIPPED with the reason and
    the size of each, and the unsupported suffixes with their counts. The
    account is what makes a zero legible: a caller can say WHICH formats it
    could not read instead of reporting an empty query as an empty design.
    INPUT only (§4.05) — the oracle exclusion is itself recorded, as a
    deliberate skip rather than as a failure."""
    parts: List[str] = []
    read: List[str] = []
    skipped: List[Dict[str, Any]] = []
    total = 0
    truncated = False
    root = project / "input"
    if not root.is_dir():
        return {"text": "", "chars": 0, "status": INPUT_NO_TREE,
                "files_read": [], "files_skipped": [],
                "unsupported_suffixes": {}, "truncated": False,
                "input_root": str(root)}
    n_files = 0
    for q in sorted(root.rglob("*")):
        if not q.is_file():
            continue
        n_files += 1
        try:
            rel = q.relative_to(root)
        except ValueError:
            continue
        try:
            size = q.stat().st_size
        except OSError:
            size = None
        if _nps._is_oracle_parts(rel.parts):
            skipped.append({"path": str(rel), "suffix": q.suffix.lower(),
                            "bytes": size, "reason": SKIP_ORACLE_PATH})
            continue
        if q.suffix.lower() not in _INPUT_TEXT_EXTS:
            skipped.append({"path": str(rel), "suffix": q.suffix.lower(),
                            "bytes": size, "reason": SKIP_UNSUPPORTED_FORMAT})
            continue
        # §4.05 (FX_405), the repo's one authority, judged AFTER the format
        # filter: inside reference_flow/ it may read content to classify, and
        # a file this reader would never open must not be opened for that.
        # MEASURED before this: ibex's `reference_flow/orfs_rules.json` (the
        # golden QoR rules) was read into this text — the retrieval query and
        # the AI sub-track's prompt.
        if _rfb.design_input_denial(project, q):
            skipped.append({"path": str(rel), "suffix": q.suffix.lower(),
                            "bytes": size, "reason": SKIP_ORACLE_PATH})
            continue
        try:
            t = q.read_text(errors="replace")
        except OSError:
            skipped.append({"path": str(rel), "suffix": q.suffix.lower(),
                            "bytes": size, "reason": SKIP_UNREADABLE})
            continue
        read.append(str(rel))
        parts.append(t)
        total += len(t)
        if total >= _INPUT_TEXT_CAP:
            truncated = True
            break
    text = "\n".join(parts)[:_INPUT_TEXT_CAP]
    unsupported: Dict[str, int] = {}
    for sk in skipped:
        if sk["reason"] == SKIP_UNSUPPORTED_FORMAT:
            unsupported[sk["suffix"] or "<none>"] = \
                unsupported.get(sk["suffix"] or "<none>", 0) + 1
    if text:
        status = INPUT_READ
    elif n_files == 0:
        status = INPUT_NO_FILES
    elif read:
        # Files WERE opened and read; they simply had no characters. This is
        # the only empty that is a fact about the design rather than about the
        # reader, and it is the one that must not be lumped in with the others.
        status = INPUT_READ_AND_EMPTY
    else:
        status = INPUT_UNREADABLE_FORMAT
    return {"text": text, "chars": len(text), "status": status,
            "files_read": read, "files_skipped": skipped,
            "unsupported_suffixes": unsupported, "truncated": truncated,
            "input_root": str(root)}


def input_text(project: Path) -> str:
    """Concatenated design-input prose — the retrieval query and the AI
    sub-track's prompt. INPUT only (§4.05).

    Kept as-is for every caller that only wants the text; it is
    `input_text_report(project)["text"]` and nothing else. A caller that has to
    tell an unreadable input from an empty one — which is every caller that
    reports a number derived from it — uses the report."""
    return input_text_report(project)["text"]


def input_readability_disposition(report: Dict[str, Any]) -> Dict[str, Any]:
    """What a CONSUMER must record about the query it was given.

    Three answers, and they are not interchangeable. `MEASURED` — there was
    text and the retrieval ran on it. `NOT_MEASURED` — there was no text, and
    the reason names the formats that were skipped, so a reader learns "the
    spec is a PDF this reader cannot open" rather than "the expert DB offered
    nothing". `MEASURED_EMPTY` — files were read and were genuinely empty,
    which IS a fact about the design and is the only zero that may be reported
    as one."""
    st = report.get("status")
    if st == INPUT_READ:
        return {"retrieval_input": "MEASURED", "chars": report.get("chars", 0)}
    if st == INPUT_READ_AND_EMPTY:
        return {"retrieval_input": "MEASURED_EMPTY", "chars": 0,
                "reason": ("every readable design-input file was opened and "
                           "contained no characters — an empty design input, "
                           "not an unreadable one")}
    unsup = report.get("unsupported_suffixes") or {}
    if st == INPUT_UNREADABLE_FORMAT:
        listed = ", ".join(f"{k} x{v}" for k, v in sorted(unsup.items())) or "none"
        why = (f"the design input holds {len(report.get('files_skipped') or [])} "
               f"file(s), NONE of them in a format this reader opens "
               f"({listed}); readable formats are "
               f"{', '.join(_INPUT_TEXT_EXTS)}")
    elif st == INPUT_NO_TREE:
        why = (f"there is no design-input tree at "
               f"{report.get('input_root')} to read")
    else:
        why = (f"the design-input tree at {report.get('input_root')} holds no "
               f"files at all")
    return {"retrieval_input": "NOT_MEASURED", "chars": 0, "reason": why,
            "unsupported_suffixes": unsup,
            "readable_formats": list(_INPUT_TEXT_EXTS)}


#: `registered_ic_class_disposition` reason codes. See its docstring: these
#: are THREE different zeros and the record must not spell them the same way.
CLASS_CLASSIFIED = "CLASSIFIED"
CLASS_NOT_YET_CLASSIFIABLE = "NOT_YET_CLASSIFIABLE"
CLASS_UNCLASSIFIABLE = "UNCLASSIFIABLE"
CLASS_NOT_MEASURED = "NOT_MEASURED"

#: The L-doc prefixes `ic_class_profile._detect_ic_class_infer` requires before
#: any classification branch can be reached: with L1, L2 and L3 all absent it
#: returns at its own `no_l1_l2_l3_docs` branch without consulting a single
#: feature. Named here so this module asks the question STRUCTURALLY (do those
#: documents exist?) instead of matching the classifier's `decisive_evidence`
#: prose — prose cannot distinguish "the classifier had nothing to read" from
#: "the classifier read and was unconvinced", which is the very distinction
#: this disposition exists to make.
_CLASSIFIER_REQUIRED_L_DOCS = ("L1_", "L2_", "L3_")


def _classifier_has_documents(project: Path) -> bool:
    """True when this tree carries something the classifier can classify FROM.

    Either a class already persisted at `reports/ic_class.json` (#435 — then the
    answer is knowable by definition), or at least one of the three L documents
    the inference needs before it can reach any branch.
    """
    if (project / "reports" / "ic_class.json").is_file():
        return True
    try:
        docs = _pl.generated_docs_dir(project)
    except Exception:  # noqa: BLE001 — an unreadable layout is not a class fact
        return False
    if not docs.is_dir():
        return False
    return any(next(docs.glob(f"{pfx}*.json"), None) is not None
               for pfx in _CLASSIFIER_REQUIRED_L_DOCS)


def registered_ic_class_disposition(project: Path) -> Dict[str, Any]:
    """The design's REGISTERED ic_class AND, when there is none, WHY.

    `registered_ic_class` returns `None` for three different reasons and the
    consumer's record spelled all three the same way — "no registered ic_class
    was supplied, or the name is not one the registry carries". Only one of the
    three is a statement about the DESIGN:

      CLASSIFIED            a registered class was detected; class-first fires.
      NOT_YET_CLASSIFIABLE  this tree carries no persisted class and none of the
                            L documents the classifier reads, so the class is
                            not KNOWABLE at this point in the run. That is an
                            ORDERING fact about when the track was asked — the
                            L docs are step D1's own `required_outputs` and the
                            track is D1's own gate clause, so a run that reaches
                            the track through the flow has them. Reported under
                            its own name because a reader who sees the flat
                            "no registered ic_class" cannot tell this apart from
                            a design the classifier genuinely could not place,
                            and the two need opposite responses: this one is
                            fixed by asking later, that one never is.
      UNCLASSIFIABLE        the classifier DID read L documents and still
                            answered `unknown` — its fail-closed verdict, and a
                            real reading. `unknown` is not a class: handing it
                            to the expert DB would look up a profile for a name
                            that means "we do not know".
      NOT_MEASURED          the classifier could not be consulted at all. Never
                            defaulted to one of the other three: "could not read
                            it" is not "read it and there was nothing".

    #2144. §4.05: reads the classifier's answer about the project, never an
    oracle or golden output.
    """
    try:
        import ic_class_profile as _icp
        profile = _icp.detect_ic_class(project) or {}
    except Exception as exc:  # noqa: BLE001 — a missing class is context, never a fail
        return {"ic_class": None, "reason_class": CLASS_NOT_MEASURED,
                "reason": (f"the classifier could not be consulted ({exc}); "
                           f"this is an unread classifier, not an unclassified "
                           f"design")}
    cls = profile.get("ic_class")
    if cls and cls != "unknown":
        return {"ic_class": cls, "reason_class": CLASS_CLASSIFIED,
                "reason": "the run's own detected class"}
    if not _classifier_has_documents(project):
        return {
            "ic_class": None,
            "reason_class": CLASS_NOT_YET_CLASSIFIABLE,
            "reason": (
                "this tree carries no persisted class and none of the "
                f"{'/'.join(p.rstrip('_') for p in _CLASSIFIER_REQUIRED_L_DOCS)} "
                "documents the classifier reads, so the class is not knowable "
                "HERE — the expert track was asked before step D1 produced the "
                "L documents it classifies from. The class-first pack selection "
                "cannot fire on this tree, and that is a fact about WHEN the "
                "track ran, not about the design"),
        }
    return {
        "ic_class": None,
        "reason_class": CLASS_UNCLASSIFIABLE,
        "reason": ("the classifier read the L documents and answered "
                   "`unknown` — its fail-closed verdict, and a real reading"),
    }


def registered_ic_class(project: Path) -> Optional[str]:
    """The design's REGISTERED ic_class, or None when it has not been detected.

    Read through `ic_class_profile.detect_ic_class`, which returns the profile
    PERSISTED at `reports/ic_class.json` when one exists (#435's persist-once
    contract) — this track must see the class the run itself detected, not a
    second inference taken at a different point in the run. `"unknown"` is the
    classifier's fail-closed answer and is NOT a class: returning it would make
    the expert DB look up a profile for a name that means "we do not know".

    WHY None was returned is `registered_ic_class_disposition` (#2144). This
    function keeps its single-value contract — every caller of it wants a class
    or nothing — and the reason goes in the RECORD, where a reader looks.
    """
    return registered_ic_class_disposition(project).get("ic_class")


def retrieved_classes(prompt: str, k: int = 5, ic_class=None) -> List[Dict[str, Any]]:
    """What the expert DB surfaces for THIS design — recorded so a reviewer can
    see which knowledge the track had in hand, including when it had none.

    CLASS-FIRST (#2094): when `ic_class` names a class the DB profiles, this is
    the CONFINED retrieval, so the record shows the same classes the pack
    carried. Recording an unconfined list beside a confined pack would make the
    record disagree with the artefact it describes."""
    if not prompt.strip():
        return []
    try:
        import ic_expert_db_query as _db
        return [{"ic_class": h.get("ic_class"),
                 "score": round(float(h.get("score", 0) or 0), 2)}
                for h in (_db.query(prompt, k=k, ic_class=ic_class) or [])
                if isinstance(h, dict)]
    except Exception:  # noqa: BLE001 — retrieval is context, never a hard fail
        return []


# ── the deterministic expectation rules ─────────────────────────────────────
#
# Each rule reads the design INPUT, decides what the L-docs SHOULD contain, and
# reports whether the program track produced it. A rule returns a list of
# expectation dicts:
#
#   id            stable identity  <rule>::<subject>
#   layer         which L doc should carry it
#   field_path    where in that layer
#   requirement   what should be there, in words
#   evidence      the INPUT facts the expectation rests on
#   expert_source the DB class + verbatim lesson it comes from
#   met           did the program track produce it?
#   observed      what the program track actually has

_NVM_DB_CLASS = "nvm-fuse-array"


def rule_nvm_program_supply(project: Path) -> Dict[str, Any]:
    """A programmable non-volatile memory that the design means to BURN needs
    its programming supply to arrive from outside, so that supply has to exist
    as a terminal in the pin/pad inventory AND as a rail in the power-intent
    layer, distinct from the core rail.

    The deterministic half of this rule is `nvm_program_supply_intent`, kept as
    its own module rather than inlined here: one convention must have exactly
    one evaluation, so that if this is ever promoted to a blocking gate the two
    cannot drift. A drifting supply rule is how the pin gets lost.

    NOTHING STOPS ON THIS. See `deferred_enforcement` in the report.
    """
    lesson = expert_db_lesson(_NVM_DB_CLASS)
    assessment = _nps.assess(project)
    out: Dict[str, Any] = {
        "rule": "nvm_program_supply",
        "expert_db_class": _NVM_DB_CLASS,
        "expert_lesson": lesson,
        "applicable": bool(assessment.get("applicable")),
        "reason": assessment.get("reason", ""),
        "expectations": [],
    }
    if not assessment.get("applicable"):
        return out

    l21 = _nps.load_l21(project)
    rails = _nps.declared_rails(l21)
    boundary = assessment.get("boundary", {}).get("names", [])
    intent = assessment.get("program_intent", {})

    for pin in assessment.get("pins", []):
        subject = f"{pin['master']}/{pin['pin']}"
        evidence = [
            f"input/pdk_local: macro {pin['master']} declares this pin "
            f"USE POWER in its own LEF, alongside "
            f"{len(assessment['multi_supply_macros'].get(pin['master'], []))} "
            f"distinct supply pins in total",
            f"input RTL: instantiates {pin['master']}",
            f"input RTL: programming-control logic present "
            f"({', '.join(intent.get('role_categories', []))})",
        ]

        # Expectation A — the chip boundary carries a terminal for it.
        hit_pin = _nps._rail_token_match(pin["pin"], boundary)
        out["expectations"].append({
            "id": f"nvm_program_supply::boundary_terminal::{subject}",
            "layer": "L1_DATASHEET",
            "field_path": "fields.pinout / fields.pin_table "
                          "(or L5.pads / L9.top_level_ports)",
            "requirement": (
                f"a boundary terminal for {subject} — the programming supply "
                f"is sourced outside the die and sits above the core rail, so "
                f"it can only enter through a package pin or a probe pad"),
            "evidence": evidence,
            "expert_source": {"db_class": _NVM_DB_CLASS, "lesson": lesson},
            "met": bool(hit_pin) or pin["status"] == "declared_gap",
            "observed": (f"terminal {hit_pin!r}" if hit_pin
                         else "declared integration gap"
                         if pin["status"] == "declared_gap"
                         else "no corresponding terminal in the design's "
                              "boundary inventory"),
        })

        # Expectation B — the power-intent layer declares it as its own rail.
        hit_rail = _nps._rail_token_match(pin["pin"], rails)
        out["expectations"].append({
            "id": f"nvm_program_supply::power_intent_rail::{subject}",
            "layer": "L21_POWER_INTENT",
            "field_path": "fields.power_rails[] / fields.power_domains[]",
            "requirement": (
                f"a rail entry for {subject}, distinct from the core rail — "
                f"the back end builds the supply network from this layer, and "
                f"a supply it never sees is a supply it never builds"),
            "evidence": evidence,
            "expert_source": {"db_class": _NVM_DB_CLASS, "lesson": lesson},
            "met": bool(hit_rail),
            "observed": (f"rail {hit_rail!r}" if hit_rail
                         else f"power-intent layer declares "
                              f"{rails if rails else 'no rails at all'}"),
        })
    return out


DETERMINISTIC_RULES = (rule_nvm_program_supply,)


# ── converge: the AI half's expectations vs the program track's L-docs ──────
#
# This is the half of "dual-track convergence" that the doctrine's name
# promises and the first landing did not have. It is DELIBERATELY deterministic
# and it deliberately recomputes `met` rather than trusting the answer, so the
# AI half cannot mark its own homework.

# The same relative-path family `hardmacro_supply_intent.load_l21` walks, kept
# as one list so a project layout that one of them can read is readable by
# both. A layer the program track wrote where only one of the two looks is a
# disagreement manufactured by path drift, not by the design.
_L_DOC_DIRS = ("generated_docs", "phase1/generated_docs",
               "input/generated_docs")


def _norm(text: Any) -> str:
    """Lower-case, with every run of non-alphanumerics collapsed to one space.

    Not `hardmacro_supply_intent._rail_token_match`: that answers "does this
    ONE pin name equal one of these rail strings", and this answers "does this
    possibly-multi-word phrase occur in this whole document". Reusing a matcher
    across two different questions is how a matcher ends up wrong for both.
    """
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def phrase_present(phrase: str, haystack: str) -> bool:
    """Is a phrase present in the text, ANCHORED AT TOKEN BOUNDARIES?

    Both sides are reduced to alphanumeric tokens; the phrase matches iff some
    CONTIGUOUS run of haystack tokens concatenates to the phrase's tokens
    concatenated. Two properties follow, and both are load-bearing:

      * a phrase can never match INSIDE a token — `VDD` does not match
        `AVDD_REF`, and `REF` does not match `REFHI`. That is the #309
        mis-binding bug, and a comparator that made it would report agreement
        on the strength of a substring, which is a false CLEAN;
      * a separator difference is not a disagreement — `1.8 V` matches
        `1.8V`, `TRIM_SEL` matches `trim sel`. Spec prose and JSON field names
        spell the same fact both ways constantly, and scoring that as a gap
        would fill an advisory channel with noise until nobody read it, which
        is its own way of becoming a report nobody opens.

    The run length is bounded by the phrase's own length (every token
    contributes at least one character), so this stays linear in the document.
    """
    want = _norm(phrase).split()
    if not want:
        return False
    target = "".join(want)
    toks = _norm(haystack).split()
    for i in range(len(toks)):
        acc = ""
        for j in range(i, len(toks)):
            acc += toks[j]
            if len(acc) > len(target):
                break
            if acc == target:
                return True
    return False


#: The ELLIPSIS an author reaches for when the fact is stated with words in
#: between. `_norm` deletes it with every other separator, so it is never a
#: wildcard and never can be without making the comparator weaker the more an
#: author writes — which is the property `_converge_split` refuses for a
#: disjunction, for the same reason.
_TOKEN_ELLIPSIS = re.compile(r"\.\.\.|\u2026")

#: THE EXPECTED-TOKEN LANGUAGE, declared (#2150 F5, second half). F5 shipped a
#: project-derived vocabulary for `field_path` — the field an expectation only
#: DECORATES with — and left `expected_tokens`, the field every verdict rests
#: on, documented as "one or more tokens to compare". An author given that is
#: told nothing about what the comparator can represent, and the two shapes it
#: cannot are exactly the two an author writes when the fact is awkward: a
#: non-Latin token, and a pattern with an ellipsis in it.
TOKEN_LANGUAGE = {
    "matcher": ("each token is compared with `phrase_present`: both the token "
                "and the document are lower-cased and every run of "
                "non-[a-z0-9] characters is collapsed to one space, then the "
                "token matches iff some CONTIGUOUS run of document tokens "
                "concatenates to it"),
    "rules": [
        "a token MUST contain at least one [a-zA-Z0-9] character. A token "
        "written wholly in CJK, Greek, Cyrillic or punctuation normalises to "
        "the empty string and is refused BY EVERY document, including one "
        "that states it verbatim",
        "a token MUST NOT contain an ellipsis (`...` or `\u2026`). It is not "
        "a wildcard: normalisation deletes it, and the expectation silently "
        "becomes a demand for the contiguous phrase with the elided words "
        "removed. State the phrase the document actually uses, or state the "
        "surviving words as SEPARATE tokens",
    ],
    "separators_are_not_a_disagreement": (
        "`1.8 V` matches `1.8V` and `TRIM_SEL` matches `trim sel`; a token "
        "can never match inside a longer word (`REF` does not match `REFHI`)"),
}

#: The reason codes `unaskable_tokens` returns. Codes, not prose, because a
#: consumer must be able to count them without parsing a sentence.
TOKEN_NO_MATCHABLE_CHARACTER = "NO_MATCHABLE_CHARACTER"
TOKEN_ELLIPSIS_ERASED = "ELLIPSIS_ERASED"


def unaskable_tokens(tokens: Any) -> List[Dict[str, Any]]:
    """Which of these expected tokens `present_in_units` cannot ASK for.

    Returns one entry per unaskable token — `token`, `reason` (a code) and
    `asked_instead` (what the comparator would actually have compared, so the
    refusal is falsifiable from the report rather than only by re-running).
    An empty list means every token is representable; it does NOT mean any of
    them is present.

    This is a property of the TOKEN and the matcher alone. It reads no
    document, so it answers identically for every design — which is what
    makes it safe to check before the Phase-1 root is opened, and what makes
    it a fact about the expectation rather than about the chip.
    """
    out: List[Dict[str, Any]] = []
    for t in (tokens or []):
        text = str(t)
        want = _norm(text).split()
        if not want:
            out.append({
                "token": text,
                "reason": TOKEN_NO_MATCHABLE_CHARACTER,
                "asked_instead": "",
                "why": ("no [a-z0-9] character survives normalisation, so "
                        "`phrase_present` returns False on the empty phrase "
                        "BEFORE it reads any document — the answer is False "
                        "for every possible document, including one that "
                        "states this token verbatim"),
            })
            continue
        if _TOKEN_ELLIPSIS.search(text):
            out.append({
                "token": text,
                "reason": TOKEN_ELLIPSIS_ERASED,
                "asked_instead": " ".join(want),
                "why": ("the ellipsis is deleted by normalisation, so the "
                        "comparator did not ask for this pattern — it asked "
                        f"whether the document states {' '.join(want)!r} "
                        "contiguously, which is a stricter question than the "
                        "one written and is answered as though it were the "
                        "same one"),
            })
    return out


def _layer_haystack(blob: Any) -> str:
    """Every key and every scalar of an L-doc, flattened to searchable text.

    Keys count: a layer can carry a fact as a field NAME as legitimately as it
    can carry it as a value, and a comparator blind to one half of the document
    would report a gap the design does not have."""
    out: List[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                out.append(str(k))
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif node is not None:
            out.append(str(node))

    walk(blob)
    return " ".join(out)


def _haystack_units(blob: Any) -> List[str]:
    """The layer's searchable text as INDEPENDENT UNITS — one per key, one per
    scalar — rather than as one joined document (#2127 addendum, #2128).

    `_layer_haystack` joins every key and every scalar with spaces, and
    `phrase_present` then matches any CONTIGUOUS run of that joined stream. The
    join is not a boundary, so a phrase can be assembled out of parts that
    belong to different fields. MEASURED on neutral fixtures:

        {"x": ["power", "domain"]}   phrase "power domain"  -> True
        {"mode": "fast"}             phrase "mode fast"     -> True
        {"busy": {}, "mode": {}}     phrase "busy mode"     -> True

    None of those three documents states the phrase. A run's expected token
    list is then satisfied by an accident of ADJACENCY, and the accident is
    invisible because the report prints the phrase, not where it matched.

    Matching per UNIT keeps every property `phrase_present` was built for — a
    phrase still cannot match inside a token (`REF` does not match `REFHI`),
    and a separator difference is still not a disagreement (`1.8 V` matches
    `1.8V` within one unit) — and removes only the cross-field assembly."""
    out: List[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                out.append(str(k))
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif node is not None:
            out.append(str(node))

    walk(blob)
    return out


def present_in_units(phrase: str, units: List[str]) -> bool:
    """Is the phrase present WITHIN ONE unit? Never assembled across two."""
    return any(phrase_present(phrase, u) for u in units)


def subtree_at(blob: Any, field_path: Any, layer: Any = None) -> Optional[list]:
    """The node(s) the expectation's `field_path` addresses, or None.

    A list on the way down contributes each of its ELEMENTS, so
    `registers.offset` on a list of register records resolves to every
    record's `offset` — the reading the expectation means. Returns None (not
    []) when the path does not resolve, because "the path is not there" and
    "the path is there and empty" are different answers and this repo has
    measured what happens when a program supplies one for the other.
    """
    key = _normalise_field_path(field_path, layer)
    if not key:
        return None
    # The emitter nests the payload under `fields`; some protocol synthesizers
    # write it flat (`l_doc_consumer_contract.l_doc_fields` accepts both). An
    # expectation may spell either, and a spelling difference between a schema
    # and an expectation is not a defect — this repo has measured what scoring
    # one as a defect does to an advisory channel. Both spellings are tried,
    # HERE and only here, so the resolver and the status can never disagree.
    for candidate in _field_path_spellings(key):
        nodes = _walk_field_path(blob, candidate)
        if nodes is not None:
            return nodes
    return None


def _field_path_spellings(key: str) -> List[str]:
    """The one path, in both the nested and the flat spelling."""
    if key.startswith("fields."):
        return [key, key[len("fields."):]]
    return [key, "fields." + key]


def _walk_field_path(blob: Any, key: str) -> Optional[list]:
    """One literal walk of one spelling. `None` when a segment is absent."""
    nodes: List[Any] = [blob]
    for seg in key.split("."):
        nxt: List[Any] = []
        for node in nodes:
            stack = [node]
            while stack:
                cur = stack.pop()
                if isinstance(cur, list):
                    stack.extend(cur)
                elif isinstance(cur, dict):
                    for k, v in cur.items():
                        if str(k).lower() == seg:
                            nxt.append(v)
        if not nxt:
            return None
        nodes = nxt
    return nodes


def resolve_layer_file(project: Path, layer: str) -> Optional[Path]:
    """The L-doc the AI half named, tolerating how it spelled the layer.

    An expert naming `L21` and one naming `L21_POWER_INTENT` mean the same
    layer. Matching on the leading `L<number>` token rather than the full file
    stem keeps a spelling difference from being scored as a design gap — while
    still refusing a layer that does not exist at all."""
    want = (layer or "").strip()
    if not want:
        return None
    m = re.match(r"^\s*(l\s*\d+)", want.lower())
    key = re.sub(r"\s+", "", m.group(1)) if m else None
    for rel in _L_DOC_DIRS:
        d = project / rel
        if not d.is_dir():
            continue
        exact = d / f"{want}.json"
        if exact.is_file():
            return exact
        if not key:
            continue
        for p in sorted(d.glob("*.json")):
            stem = p.stem.lower()
            if stem == key or stem.startswith(key + "_"):
                return p
    return None



# ── the field_path guard (#2127) ────────────────────────────────────────────
#
# `field_path` was carried into the finding text and read by nothing. That is
# not a cosmetic gap: the sentence a reader gets is
#
#     expected L9.integration.register_map.offsets to carry: <requirement>.
#     The program track produced: L9 does not carry [...]
#
# which states that a NAMED field of a NAMED layer is empty. MEASURED on a
# published Phase-1 run: `L9_INTEGRATION_SPEC.json` has no `integration` key at
# any depth, so no such field was ever looked at — the whole layer was searched
# and the path was decoration. An expectation can therefore name any path at
# all and the report will repeat it as fact.
#
# So the path is CHECKED against what the layer document declares, and an
# expectation naming an undeclared one is refused BY NAME. The refusal is
# ADDITIVE — `met` is decided exactly as before, over the whole layer — because
# a guard that also moved verdicts could not be told apart from a comparator
# change, and this one has to be readable on its own.


def _normalise_field_path(field_path: Any, layer: Any = None) -> str:
    """The path as a comparable key: no indices, no layer prefix, lower case.

    A layer-qualified path (`L4_REGMAP.registers[].offset`) means the same
    field as the bare one, and refusing the qualified spelling would refuse
    exactly the repair this guard exists to ask for — an expectation re-scoped
    onto the layer that owns the fact naturally writes that layer into the
    path.
    """
    text = re.sub(r"\[[^\]]*\]", "", str(field_path or "")).strip().strip(".")
    if not text:
        return ""
    parts = [seg for seg in text.split(".") if seg.strip()]
    if (len(parts) > 1
            and re.match(r"^l\d+[a-z]?(_[a-z0-9_]+)?$", parts[0].lower())):
        parts = parts[1:]          # a leading layer token is addressing, not a field
    return ".".join(parts).lower()


def field_path_status(blob: Any, field_path: Any, layer: Any = None) -> str:
    """`DECLARED`, `UNDECLARED`, or `ABSENT` when the expectation named none.

    DERIVED FROM `subtree_at`, and deliberately not from a second walk that
    collects "the paths this document declares". One convention, one
    evaluation: an earlier revision of this landing had exactly that second
    walk, and the two answers disagreed within a day — the collector accepted
    a `fields.`-elided path that the resolver could not reach, so a path read
    DECLARED and then fell back to a whole-layer search anyway. Two answers
    about one path is the same disease as a field_path nothing reads.

    Nothing here looks at the path's VALUE: an empty declared field is a design
    question, an undeclared one is an authoring question, and conflating them
    is how the second became invisible.
    """
    if not _normalise_field_path(field_path, layer):
        return "ABSENT"
    return "DECLARED" if subtree_at(blob, field_path, layer) is not None \
        else "UNDECLARED"


def emitted_layer_files(project: Path) -> List[Path]:
    """Every L-doc the program track wrote for this project, in one list.

    The FIRST readable `_L_DOC_DIRS` entry wins outright. Two directories are a
    staging difference, not two layer sets, and merging them would let a stale
    copy of a layer answer for the live one.
    """
    for rel in _L_DOC_DIRS:
        d = project / rel
        if d.is_dir():
            files = sorted(p for p in d.glob("*.json") if p.is_file())
            if files:
                return files
    return []


#: How deep an authoring schema enumerates. Two segments is what an
#: expectation writes in practice (`fields.notes`, `records.offset`) and it
#: keeps the pack bounded; the DEPTH IS STATED in the schema, so a reader
#: knows a path is absent from the list because it is deeper, not because the
#: layer does not declare it.
AUTHORING_PATH_DEPTH = 2
#: Per-layer cap, also stated. A truncated list that did not say so would be
#: read as "these are all the paths", which is the exact defect this schema
#: exists to end, one level over.
AUTHORING_PATHS_PER_LAYER = 200


def declared_field_paths(blob: Any, layer: Any = None,
                         max_depth: int = AUTHORING_PATH_DEPTH) -> List[str]:
    """The dotted paths this layer document declares, to `max_depth`.

    SELF-VERIFIED AGAINST `subtree_at`, which is what `field_path_status` —
    the guard — resolves with. Every candidate this walk produces is resolved
    before it is emitted, and one that does not resolve is dropped: the schema
    an author is handed must be exactly the set the guard accepts, and this
    module has already measured what two answers about one path cost. An
    earlier revision of the #2127 landing collected "the paths this document
    declares" in a second walk, the two disagreed within a day, and a path
    read DECLARED and then fell back to a whole-layer search anyway.

    So this is not a second authority. It is a candidate generator whose
    output is filtered by the one authority there is.
    """
    out: List[str] = []

    def walk(node: Any, prefix: str, depth: int) -> None:
        if depth > max_depth:
            return
        if isinstance(node, list):
            for v in node:
                walk(v, prefix, depth)
            return
        if not isinstance(node, dict):
            return
        for k, v in node.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            out.append(path)
            walk(v, path, depth + 1)

    walk(blob, "", 1)
    seen: set = set()
    kept: List[str] = []
    for path in out:
        if path in seen:
            continue
        seen.add(path)
        if subtree_at(blob, path, layer) is not None:
            kept.append(path)
    return sorted(kept)


def authoring_schema(project: Path) -> Dict[str, Any]:
    """THE DECLARATION AN EXPECTATION AUTHOR IS HANDED (#2150 F5).

    THE DEFECT THIS CLOSES, measured on the pack this track itself emits.
    `ic_expert_backup_pack` wrote a HARD-CODED two-entry contract —
    `{"L9": "integration specification", "L19": "constraints and
    implementation context"}` — for a project whose Phase-1 root carries 24
    layer documents, and an `answer_contract` documenting `field_path` as
    `"optional field path"` and nothing else. An author handed that pack can
    address only two of the twenty-four layers, and can only INVENT a path out
    of the two prose words it was given. That is where `integration.*` and
    `constraints.*` came from, and why the #2127 guard then refused 46 of 46
    field_paths as undeclared: the pack manufactured the very authoring defect
    the guard was built to catch, and the guard reported the author.

    A guard that refuses at review time and a schema that refuses at authoring
    time are the same declaration read at two moments. This is that
    declaration, derived from the project's own emitted L-docs and filtered
    through `subtree_at` — so a path this schema lists is a path the guard
    accepts, by construction rather than by agreement.

    NOT_MEASURED when no L-doc is readable: an empty schema would be an author
    told that no layer declares anything, which is a false statement about the
    root rather than an absent one.
    """
    files = emitted_layer_files(project)
    if not files:
        return {"status": "NOT_MEASURED",
                "reason": ("no L-doc was found under "
                           f"{list(_L_DOC_DIRS)}, so no authoring schema can "
                           "be derived — this is 'could not read the root', "
                           "never 'read it and no layer declares anything'"),
                "layers": {}}

    import l_doc_taxonomy as _tax
    purpose = {}
    for spec in _tax.L_DOCS_V2:
        purpose[spec.full_name] = f"{spec.title} — {spec.description}"

    layers: Dict[str, Any] = {}
    unreadable: List[str] = []
    for f in files:
        try:
            blob = json.loads(f.read_text(errors="replace"))
        except (OSError, ValueError) as exc:
            # Named, never silently absent: a layer nobody could read is not a
            # layer that declares nothing.
            unreadable.append(f"{f.stem}: {exc.__class__.__name__}")
            continue
        paths = declared_field_paths(blob, f.stem)
        layers[f.stem] = {
            "purpose": purpose.get(f.stem, "no taxonomy entry declares this "
                                           "layer name"),
            "declared_field_path_count": len(paths),
            "declared_field_paths": paths[:AUTHORING_PATHS_PER_LAYER],
            "truncated": len(paths) > AUTHORING_PATHS_PER_LAYER,
        }
    return {
        "status": "OK",
        "schema": "vibeic.phase1-expert-expectation-authoring.v1",
        "phase1_root": phase1_root_identity(project),
        "unreadable": unreadable,
        "enumeration": {
            "max_depth": AUTHORING_PATH_DEPTH,
            "per_layer_cap": AUTHORING_PATHS_PER_LAYER,
            "basis": ("every path here was resolved with the SAME resolver "
                      "the review-time guard uses, so a path this schema "
                      "lists is a path the guard accepts. A path absent from "
                      "a layer's list is either deeper than max_depth or not "
                      "declared — the counts say which"),
        },
        # #2150 F5, second half. The vocabulary above is for `field_path`,
        # which an expectation only DECORATES with — the reading falls back
        # to the whole layer when it does not resolve. `expected_tokens` is
        # the field every verdict rests on, and F5 as first landed declared
        # nothing about it at all. The two shapes the matcher cannot
        # represent are named here, at authoring time, by the same
        # declaration `unaskable_tokens` refuses by at review time.
        "expected_tokens_rule": TOKEN_LANGUAGE,
        "qualified_output_expectation": {
            "input": "plugin_input/qualified-outputs.json",
            "input_schema": "vibeic.phase1-qualified-output-input.v1",
            "id": "qualified_by:<output>", "layer": "L9_INTEGRATION_SPEC",
            "field_path": "top_ports",
            "qualified_by": {"output": "<multi-bit write-data output>",
                             "port": "<one-bit write-enable output>",
                             "active_level": "high|low"},
            "basis": [{"file": "<design INPUT path>", "line": "<integer>",
                       "quote": "<verbatim input quotation>"}],
            "author_input_fields": {
                "top_level": ["schema", "input_files", "interface", "qualifiers"],
                "qualifier": ["output", "port", "active_level", "output_role",
                              "qualifier_role", "channel", "basis", "polarity"],
                "roles": {"output_role": "write_data", "qualifier_role": "write_enable"},
                "polarity": {"kind": "input_requirement|designer_choice",
                             "decision": "<explicit Expert rationale; never inferred from a name>",
                             "basis": "<verbatim INPUT requirement or delegation citations>"},
                "currentness": ("Use the read-only --describe-qualified-output-input "
                                "contract for all current input hashes and implemented ports; "
                                "do not edit its hashes to accept stale input")},
            "rule": ("Author this expectation independently from design INPUT "
                     "and explicit delegated designer choices. Review same-channel "
                     "write-data validity and polarity; a WE name never chooses "
                     "high. The comparator checks the exact relation on all three "
                     "L9 port aliases, not token coincidence. Neither the L9 "
                     "writer nor this track creates or signs its matching answer.")},
        "rule": ("an expectation's `field_path` MUST be one this schema lists "
                 "for the layer it addresses, or be omitted entirely. A path "
                 "no layer declares is refused BY NAME at review time and the "
                 "reading silently falls back to the whole layer, so the "
                 "finding then describes a field nothing looked at"),
        "layers": layers,
    }


def refuse_undeclared_field_path(schema: Dict[str, Any], layer: Any,
                                 field_path: Any) -> Optional[str]:
    """The AUTHORING-time half of the guard: why this path may not be written.

    `None` when the path is acceptable. A REASON when it is not — never a
    bare boolean, because the author has to be told which layer was consulted
    and what it does declare, or the refusal costs more than it saves.

    An ABSENT field_path is acceptable: the expectation then addresses the
    whole layer and says so. That is a weaker claim, not an authoring error,
    and refusing it here would make this schema stricter than the guard it is
    supposed to be the other reading of.
    """
    if schema.get("status") != "OK":
        return None          # nothing was read; refusing on that is a guess
    if not str(field_path or "").strip():
        return None
    layers = schema.get("layers") or {}
    stem = None
    want = str(layer or "").strip().lower()
    if want:
        # TWO PASSES, EXACT FIRST — mirroring `resolve_layer_file`, which
        # tries the exact filename before falling back to the `L<number>`
        # token. One pass is not the same function: two layer documents share
        # a numeric prefix (`L8_RTL_CONSTANTS` and `L8_TIMING_WAVEFORM`), so a
        # single loop that accepts either match returns whichever sorts first
        # and answers about the wrong document. MEASURED on a 504-path sweep
        # of a real root: 502 agreed with the guard and the 2 that did not
        # were both L8, both this collision. Compare identities, not names.
        exact = [n for n in sorted(layers) if n.lower() == want]
        stem = exact[0] if exact else None
        if stem is None:
            m = re.match(r"^\s*(l\s*\d+)", want)
            key = re.sub(r"\s+", "", m.group(1)) if m else None
            if key:
                pref = [n for n in sorted(layers)
                        if n.lower() == key or n.lower().startswith(key + "_")]
                stem = pref[0] if pref else None
    if stem is None:
        return (f"no layer named {layer!r} is in this Phase-1 root; it "
                f"carries {sorted(layers)}")
    declared = layers[stem]["declared_field_paths"]
    norm = _normalise_field_path(field_path, layer)
    if any(_normalise_field_path(d) == norm for d in declared):
        return None
    if layers[stem]["truncated"]:
        # The list is not the whole set, so a miss is not a proof. Say so
        # rather than refuse on an enumeration that admits it is partial.
        return None
    return (f"{stem} declares no field_path {field_path!r}. It declares "
            f"{declared[:20]}"
            + (" (first 20 of "
               f"{layers[stem]['declared_field_path_count']})"
               if len(declared) > 20 else "")
            + ". Address a path this layer declares, or omit `field_path` and "
              "state that the expectation is about the whole layer.")


def taxonomy_layer_stems() -> List[str]:
    """Every L-doc stem `l_doc_taxonomy` declares — the ONE roster.

    Read from the taxonomy module rather than re-listed here: a second list of
    the layers that exist is a second answer to a question this repo already
    answers in one place, and the two drift on the first extension.
    `NOT_MEASURED` is impossible — the roster is a module constant — but an
    import failure must not be spelled as an empty roster, so it raises.
    """
    import l_doc_taxonomy as _tax
    return list(_tax.all_l_doc_full_names())


def layer_declared_by_taxonomy(layer: Any) -> bool:
    """Does the taxonomy declare a layer of this name?

    Matched the way `resolve_layer_file` matches a document — on the leading
    `L<number>` token, plus the exact stem — so a spelling the resolver
    accepts is a spelling this answers for. Two matchers for one question is
    how a layer comes to be present for one reader and absent for the other.
    """
    want = (layer or "").strip()
    if not want:
        return False
    stems = [s.lower() for s in taxonomy_layer_stems()]
    if want.lower() in stems:
        return True
    m = re.match(r"^\s*(l\s*\d+)", want.lower())
    if not m:
        return False
    key = re.sub(r"\s+", "", m.group(1))
    return any(s == key or s.startswith(key + "_") for s in stems)


def phase1_root_identity(project: Path) -> Dict[str, Any]:
    """WHICH Phase-1 root this run judged, as a value a later reader can check.

    Every artefact in the #2127/#2132/#2150 chain — a classification, a
    decision table, a repaired corpus — is an answer ABOUT one Phase-1 root,
    and none of them said which. MEASURED (#2150 F11, re-measured here): the
    table computed for #2132 names `L24_SIGNOFF` as an owning layer and the
    published opentitan_aes root has 23 layer codes in 24 files and no `L24`
    at all, so two of its OWNER cells address a document that does not exist.
    Reading such a table against this root does not disagree with it — it
    silently answers a different question.

    So the root is IDENTIFIED, by MEMBERSHIP (the layer stems) and by CONTENT
    (a digest over each layer's bytes). Membership is the half a substitution
    cannot disturb, and content is the half a re-run can. Both are recorded;
    neither is reduced to the other.

    `NOT_MEASURED` when no L-doc is readable — never an empty root presented
    as a root that was read.
    """
    files = emitted_layer_files(project)
    if not files:
        return {"status": "NOT_MEASURED",
                "reason": ("no L-doc was found under "
                           f"{list(_L_DOC_DIRS)} — this is 'could not read "
                           "the Phase-1 root', never 'read it and it was "
                           "empty'"),
                "layers": [], "digest": None}
    import hashlib
    per = []
    for p in files:
        try:
            raw = p.read_bytes()
        except OSError:
            per.append((p.stem, "UNREADABLE"))
            continue
        per.append((p.stem, hashlib.sha256(raw).hexdigest()))
    joined = "\n".join(f"{stem} {dig}" for stem, dig in sorted(per))
    present = sorted(stem for stem, _ in per)
    declared = taxonomy_layer_stems()
    return {
        "status": "OK",
        "layers": present,
        "layer_count": len(per),
        # WHICH declared layers this root does NOT carry. The half that makes
        # a cross-root artefact readable: an expectation, a classification or
        # a decision table naming one of these was computed against a root
        # that had it, and this one does not — which is a different question
        # from a disagreement, and reads identically without this list.
        "taxonomy_layer_count": len(declared),
        "taxonomy_layers_absent": sorted(set(declared) - set(present)),
        "digest": hashlib.sha256(joined.encode("utf-8")).hexdigest(),
        "digest_basis": ("sha256 over the sorted `<layer stem> <sha256 of the "
                         "layer file>` lines — membership and content, kept "
                         "separable so a reader can see which of the two "
                         "moved"),
        "root_dir": str(files[0].parent),
    }


# ── the OWNERSHIP haystack: the layer's CONTENT, not its envelope (#2191) ────
#
# MEASURED on 8HD-4 (lane cz2191, 2026-09-08) over 482 distinct Phase-1 roots
# / 13,496 L documents found on that host, and over a random sample of 9,600
# tokens drawn from 120 of those roots:
#
#   * 58.3% of every (layer, token) ownership relation was supported ONLY by
#     text the emitter writes ABOUT the document — its identity, its
#     classification stamp, its provenance, the hints it gives an extractor,
#     and the paths of the files it read. Not by anything the layer states.
#   * 323 of the 9,600 sampled tokens were carried by EVERY layer of their
#     root. A token every layer carries cannot say which layer owns the fact.
#     After this exclusion, zero tokens are.
#   * the `ic_class` stamp: 489 distinct (root, value) pairs owned 4,576
#     layers between them; 452 of the 489 (92.4%) own NOTHING once the
#     envelope is out, and the 37 that remain are the roots whose content
#     genuinely names the class.
#   * the emitter's own VERSION STRINGS are the widest offender: on the
#     `opentitan_aes` root the bare token `1` was carried by all 28 layers,
#     and in 21 of them by the envelope ALONE — `_generator.plugin_version`
#     ("1.9.62"), a `schema_version` / `emitted_by` version suffix, or an
#     `extraction_strategy` gate key. Seven layers carry it in content, and
#     those seven are the answer this function should have been giving.
#
# So the envelope is excluded from the ownership reading BY NAME. Top level
# only: these are the keys the emitter writes around the payload, and a
# content field that happens to share one of these names at depth is content.
#
# NOT applied to `met`. The addressed-layer verdict is decided over the whole
# document exactly as it was before this landing, so no verdict moves here and
# a moved verdict can never be attributed to this change (the same separation
# #2127 kept between its field_path guard and its verdict).
_L_DOC_ENVELOPE_KEYS = frozenset({
    "doc_id", "doc_name", "doc_class", "schema_version",
    "applicability", "ic_class", "class_path", "ic_name",
    "emitted_by", "_generator", "extraction_status",
    "extraction_hints", "extraction_strategy", "source_documents",
})

# `extraction_evidence` is the one envelope member that also carries CONTENT:
# it is keyed by SOURCE PATH and each entry quotes the input under `literal`
# with a `label` naming the field and the file:line it came from. The quote is
# a fact the layer recorded; the path and the label are provenance. MEASURED:
# reading the whole subtree is how `L6_CONTROL_LOGIC` came to OWN the token
# `GHASH` — its only two matches were the source filenames
# `input/docs/ghash_masked_algorithm.svg` and
# `input/docs/ghash_masked_block_diagram.svg`, in a layer that states nothing
# about it. Dropping the subtree WHOLESALE was measured too and costs 2.6% of
# tokens their only owner; keeping the values and dropping the path keys and
# the labels costs 0.7%. A design fact is not owned by the name of the file it
# was read from — but it IS owned by a line the layer quoted.
_EVIDENCE_KEY = "extraction_evidence"
_EVIDENCE_PROVENANCE_KEYS = frozenset({"label"})

# A token that MORE of the searched layers carry than not is a property of the
# root, not of a layer: it cannot distinguish one layer from another, and an
# ownership answer built on it decides nothing while reading as though it
# decided everything. MEASURED after the envelope exclusion above, only seven
# distinct tokens in the 9,600-token sample still clear this line, and every
# one of them is structural rather than a design fact: `input`, `fields`,
# `in`, `evidence`, `Input:`, `True`, `False` — the last two being exactly the
# coincidence #2128 measured when an unrelated boolean key made the token
# "false" score.
_TOKEN_BREADTH_CEILING = 0.5

# SCOPE BOUNDARY, stated rather than hidden. The envelope is dropped by NAME at
# the TOP LEVEL, and two shapes it does NOT reach were measured and are left
# for their own issue rather than guessed at:
#
#   * emitter rule/version markers that reach CONTENT fields. The marker
#     `gfm_multitable_header_role_v0_3_2` sitting inside an L1 `pin_table`
#     value satisfies the token `32`, and no top-level name can exclude it
#     because the field it is in is genuinely content.
#   * an ownership question where ZERO layers were searched. `[]` is then a
#     real zero over an empty population, and it is NOT separately statused —
#     `searched_layers` records the population, but a caller that reads only
#     `layers` cannot tell an empty corpus from an answered question.
#
# Both are the same class as the defect this landing fixes and neither is
# fixed here. Measuring them is a separate issue; do not read their absence as
# a claim that they do not exist.


def _ownership_units(blob: Any) -> List[str]:
    """The layer's CONTENT as haystack units — the document minus its
    envelope. See `_L_DOC_ENVELOPE_KEYS` for what is dropped and why."""
    if not isinstance(blob, dict):
        return _haystack_units(blob)
    out: List[str] = []
    for key, value in blob.items():
        if key in _L_DOC_ENVELOPE_KEYS:
            continue
        if key == _EVIDENCE_KEY:
            # values only: the source-path keys are provenance, not content.
            for entry in (value.values() if isinstance(value, dict)
                          else [value]):
                out.extend(_evidence_units(entry))
            continue
        out.append(str(key))
        out.extend(_haystack_units(value))
    return out


def _evidence_units(node: Any) -> List[str]:
    """`_haystack_units` over one evidence entry, minus its `label`."""
    out: List[str] = []

    def walk(cur: Any) -> None:
        if isinstance(cur, dict):
            for k, v in cur.items():
                if k in _EVIDENCE_PROVENANCE_KEYS:
                    continue
                out.append(str(k))
                walk(v)
        elif isinstance(cur, list):
            for v in cur:
                walk(v)
        elif cur is not None:
            out.append(str(cur))

    walk(node)
    return out


def owning_layers_answer(project: Path, tokens: List[str],
                         exclude: Optional[Path] = None) -> Dict[str, Any]:
    """The layers that carry EVERY one of these tokens — the scope answer.

    An expectation the addressed layer does not satisfy is an extraction gap
    ONLY if no layer satisfies it. When one does, the fact was extracted and
    the expectation asked the wrong layer, and saying "the design is missing
    it" is false about the design. Returns the layer file STEMS, sorted, so a
    reader is told where to point the `field_path`.

    EVERY token, never some: a layer carrying part of the fact does not own it,
    and scoring a partial match as ownership would launder a real gap into a
    scope finding the moment one token happened to appear anywhere.

    DELIBERATELY ASYMMETRIC. The addressed layer is read at the field the
    expectation names; the other layers are read whole. The two questions are
    different: the first is "does the layer say it WHERE this expectation says
    it should", the second is "does the program track have this fact AT ALL".
    Scoping the second would need a field_path for a layer the expectation
    never addressed, which nothing supplies — and asking it strictly would turn
    "the fact is here, one layer over" back into "the design is missing it",
    which is the defect this function exists to end.

    READ OVER CONTENT, AND WITH A FLOOR (#2191). Two guards this answer did
    not have, both of which it needed for the same reason: an ownership answer
    that cannot be wrong is not an answer, and the finding built on it
    (`RULE_AI_MISSCOPED`) tells its reader in as many words that the miss
    "is NOT a missing extraction and must not be repaired in an extractor".

      * the haystack is the layer's CONTENT — `_ownership_units`, not
        `_haystack_units`. MEASURED (see that roster): 58.3% of ownership
        relations on this fleet's corpus were carried by the emitter's own
        envelope, and the `ic_class` stamp alone — a bare unit in 9 of the 28
        emitted documents of an `opentitan_aes` root — made `L20_DFT_SCAN_
        TOPOLOGY` and `L27_MEMORY_MODULE_SPD` own a fact about mechanical
        transduction that neither states.
      * a token more of the searched layers carry than not is REFUSED, and
        when no expected token clears that line the whole answer is refused as
        `NO_DISCRIMINATING_TOKEN`. A rule that matches everything decides
        nothing, and the refusal must be a STATUS rather than an empty list:
        `[]` already means "no layer carries this fact", which the caller
        publishes as a finding about the DESIGN. Answering "could not decide"
        with "read it and nothing was there" is the substitution this repo
        keeps measuring the cost of.

    The answer also records WHERE each owning layer carried each token — the
    unit text itself — so the claim can be falsified by reading the report
    rather than by re-running the comparator.
    """
    answer: Dict[str, Any] = {
        "status": "OK",
        "layers": [],
        "searched_layers": 0,
        "token_breadth": {},
        "non_discriminating_tokens": [],
        "evidence": {},
        "refusal": None,
    }
    if not tokens:
        return answer

    # Read every searched layer ONCE. An unreadable document is not content
    # and is not counted in the denominator either: it was never searched, and
    # inflating the population with it would make a token look narrower than
    # the corpus can show.
    searched: List[tuple] = []
    for p in emitted_layer_files(project):
        if exclude is not None and p == exclude:
            continue
        try:
            blob = json.loads(p.read_text(errors="replace"))
        except (OSError, ValueError):
            continue          # unreadable content is not content
        searched.append((p.stem, _ownership_units(blob)))
    answer["searched_layers"] = len(searched)
    if not searched:
        return answer

    # ONE pass, ONE predicate. Breadth, ownership and the evidence text are
    # three readings of the same question — "does this layer carry this token,
    # and where" — and asking it twice is how two answers to one question come
    # to disagree on the first extension.
    wanted = set(tokens)
    hits: Dict[str, Dict[str, str]] = {}
    for stem, units in searched:
        found = {}
        for t in wanted:
            where = next((u for u in units if phrase_present(t, u)), None)
            if where is not None:
                found[t] = where if len(where) <= 200 else where[:200] + "…"
        hits[stem] = found
    breadth = {t: sum(1 for f in hits.values() if t in f) for t in wanted}
    answer["token_breadth"] = breadth

    wide = sorted(t for t in wanted
                  if breadth[t] > _TOKEN_BREADTH_CEILING * len(searched))
    answer["non_discriminating_tokens"] = wide
    if len(wide) == len(wanted):
        answer["status"] = "NO_DISCRIMINATING_TOKEN"
        answer["refusal"] = (
            f"every expected token is carried by more than half of the "
            f"{len(searched)} layer(s) searched ("
            + ", ".join(f"{t!r} by {breadth[t]}" for t in wide)
            + ") — a token more layers carry than not says which ROOT this "
              "is, not which layer owns the fact, so this answer would decide "
              "nothing while reading as though it decided everything. The "
              "ownership question is REFUSED rather than answered with an "
              "empty list, which would be published as a gap in the design")
        return answer

    # EVERY token, never some — the property this function had before #2191
    # and keeps unchanged.
    answer["layers"] = sorted(s for s, f in hits.items() if len(f) == len(wanted))
    answer["evidence"] = {s: hits[s] for s in answer["layers"]}
    return answer


def _split_refusal(base: Dict[str, Any], why: str) -> Dict[str, Any]:
    """A split this comparator cannot decide. `usable` stays False."""
    base["split"] = True
    base["observed"] = why
    return base


def _propagate_ownership_status(base: Dict[str, Any],
                                branches: List[Dict[str, Any]]) -> None:
    """Carry the branches' ownership STATUS up to the split parent (#2191).

    A conjunction is only as decided as its least decided term: if the
    ownership question was REFUSED for any branch that missed, the parent's
    answer is refused too, and the empty `owning_layers` it now carries must
    not be read as "no layer carries this fact" — which is what the consumer
    publishes as a gap in the design. The refusals are named branch by branch
    so a reader can repair the branch rather than the design.
    """
    refused = [b for b in branches
               if b.get("owning_layers_status") == "NO_DISCRIMINATING_TOKEN"]
    if refused:
        base["owning_layers"] = []
        base["owning_layers_status"] = "NO_DISCRIMINATING_TOKEN"
        base["owning_layers_refusal"] = "; ".join(
            f"[{b['id']}] {b['owning_layers_refusal']}" for b in refused)
        base["owning_layers_evidence"] = {}
        return
    if branches and all(b.get("owning_layers_status") == "OK"
                        for b in branches):
        base["owning_layers_status"] = "OK"
    base["owning_layers_evidence"] = {
        stem: hits for b in branches
        for stem, hits in (b.get("owning_layers_evidence") or {}).items()
        if stem in base["owning_layers"]}


def _converge_split(project: Path, base: Dict[str, Any], exp: Any,
                    raw: Any) -> Dict[str, Any]:
    """Decide a SPLIT expectation: N scoped branches, ALL of which must agree.

    Every refusal here is a refusal to DECIDE, never a verdict: an ill-formed
    split is `usable: False` and is reported under `RULE_AI_UNUSABLE`, the
    same way an ill-formed single expectation is. Silently treating a broken
    split as "not met" would put a design finding on the record for an
    authoring mistake, which is the family of defect this whole issue is.
    """
    base["split"] = True
    base["field_path_status"] = SPLIT_MARKER
    base["layer_present"] = SPLIT_MARKER
    base["scope"] = SPLIT_MARKER

    if not base["id"]:
        return _split_refusal(base, "the split expectation names no id, so "
                                    "there is nothing to compare it against")
    # A parent that states BOTH grammars is ambiguous by construction: each
    # would produce a verdict and the report could not say which one decided.
    if exp.get("expected_tokens") or exp.get("layer") or exp.get("field_path"):
        return _split_refusal(
            base,
            f"the expectation states BOTH a {SPLIT_KEY!r} list and its own "
            f"layer/field_path/expected_tokens. Those are two grammars, each "
            f"of which would decide the row, and a report that carried one "
            f"verdict could not say which of them produced it. State the "
            f"split alone: every address belongs to a branch")
    if not isinstance(raw, list):
        return _split_refusal(
            base, f"{SPLIT_KEY!r} is a {json_type_name(raw)}, not a list of "
                  f"branches, so no branch can be read from it")
    if not raw:
        return _split_refusal(
            base, f"{SPLIT_KEY!r} is an empty list. A split with no branches "
                  f"decides nothing, and a denominator of zero cannot be an "
                  f"agreement")

    branches: List[Dict[str, Any]] = []
    for i, sub in enumerate(raw):
        if not isinstance(sub, dict):
            return _split_refusal(
                base, f"branch {i} is a {json_type_name(sub)}, not an object")
        if sub.get(SPLIT_KEY) is not None:
            return _split_refusal(
                base, f"branch {i} carries its own {SPLIT_KEY!r}. A split is "
                      f"exactly one level deep: a nested one would make the "
                      f"row's denominator depend on a shape no reader of the "
                      f"report can see")
        # The branch inherits what it did not state. `requirement` and
        # `evidence` belong to the FACT, which is one fact however many layers
        # carry it; `layer`, `field_path` and `expected_tokens` are the
        # branch's own address and are never inherited.
        child = {
            "id": f"{base['id']}#{i}",
            "layer": sub.get("layer"),
            "field_path": sub.get("field_path"),
            "requirement": sub.get("requirement") or base["requirement"],
            "evidence": sub.get("evidence") or base["evidence"],
            "expert_source": sub.get("expert_source") or base.get(
                "expert_source"),
            "expected_tokens": sub.get("expected_tokens"),
        }
        res = converge_ai_expectation(project, child)
        if not res["usable"]:
            return _split_refusal(
                base, f"branch {i} ({child['id']}) cannot be converged: "
                      f"{res['observed']}. A split is decided only when every "
                      f"branch is")
        branches.append(res)

    base["usable"] = True
    base["sub_results"] = branches
    base["sub_layers"] = [b["layer"] for b in branches]
    # #2150 item 2. The parent states no tokens of its own, so its unaskable
    # set is the union over the branches, each entry naming the branch it
    # belongs to — a refusal that named only the parent would send the author
    # to re-read every branch to find the one token that caused it.
    base["tokens_unaskable"] = [
        {**u, "branch": b["id"]}
        for b in branches for u in (b.get("tokens_unaskable") or [])]

    # A branch addressing a layer this Phase-1 root does not contain (#2150,
    # first commit) makes the whole conjunction undecidable about the DESIGN:
    # one conjunct was never opened. Propagated to the parent so the row is
    # refused ONCE, under the layer-absent rule, naming the branch — rather
    # than decided `met: False` and published as a design gap.
    absent = [b for b in branches if b["layer_present"] is False]
    if absent:
        base["layer_present"] = False
        base["layers_in_root"] = absent[0].get("layers_in_root") or []
        # A conjunction containing a term NO root can ever satisfy is refused
        # as a track finding; one whose absent terms are all declared layers
        # is the program track not emitting documents its contract applies,
        # which is #312's disagreement and stays one. ANY undeclared term is
        # enough: a single unanswerable branch makes the whole conjunction
        # unanswerable, however well-formed the rest of it is.
        base["layer_in_taxonomy"] = all(b["layer_in_taxonomy"]
                                        for b in absent)
        # The parent states no `layer` of its own, so the finding would name
        # none. Name the branches that are actually missing.
        base["layer"] = ", ".join(b["layer"] for b in absent)
        base["owning_layers"] = (
            sorted({L for b in absent for L in b["owning_layers"]})
            if all(b["owning_layers"] for b in absent) else [])
        _propagate_ownership_status(base, absent)
        base["observed"] = (
            f"{len(absent)} of {len(branches)} branch(es) of this split "
            f"address a layer this Phase-1 root does not contain "
            f"({[b['layer'] for b in absent]}), so the conjunction was never "
            f"evaluated: " + "; ".join(f"[{b['id']}] {b['observed']}"
                                       for b in absent))
        return base

    # THE CONJUNCTION. Every branch, never any.
    base["met"] = all(b["met"] for b in branches)
    failed = [b for b in branches if not b["met"]]
    base["missing_tokens"] = sorted({t for b in failed
                                     for t in (b.get("missing_tokens") or [])})
    # The parent's owning-layer answer is the answer for the branches that
    # MISSED, and only when every one of them has one: a split whose failing
    # halves are each carried elsewhere is a re-scope, and one whose failing
    # half is carried nowhere is a disagreement about the design. Mixing the
    # two would let one re-scopable branch launder a real gap.
    base["owning_layers"] = (
        sorted({L for b in failed for L in (b["owning_layers"] or [])})
        if failed and all(b["owning_layers"] for b in failed) else [])
    _propagate_ownership_status(base, failed)
    if base["met"]:
        base["observed"] = (
            f"all {len(branches)} branch(es) of this split agree: "
            + "; ".join(f"{b['layer']}.{b['field_path']} carries "
                        f"{b['expected_tokens']}" for b in branches))
    else:
        base["observed"] = (
            f"{len(failed)} of {len(branches)} branch(es) of this split "
            f"disagree — a split is met only when EVERY branch is: "
            + "; ".join(f"[{b['id']}] {b['observed']}" for b in failed))
    return base


# ── WHERE the fact actually lives (#2150, the layer-contract ruling) ────────
#
# `owning_layers` answers "does any layer carry every token", and that answer
# is a layer NAME. It cannot tell the two cases a layer contract has to keep
# apart, because they produce the same layer name:
#
#   * the fact sits in a field NAMED for it — `L8.clock_domains[].name`,
#     `L4.registers[].reset_value`, `L22.checklist_milestones[].id`. A consumer
#     that wants the fact reads that path. The contract question is only WHICH
#     layer owns it.
#   * the fact sits in a GENERIC bucket — a comparison-table row, a discovered
#     identifier, an evidence literal, a prose section. It is findable only by
#     someone who already knows it is there, which is the same shape as an
#     undeclared fact.
#
# THE RULING (#2150, owner, 2026-09-07): a generic bucket does NOT satisfy a
# layer obligation unless a consumer actually reads it by that path. And the
# repair is NOT to promote every such fact to a field — #2132's rule stands,
# nothing is promoted without a MEASURED consumer. So a fact present in the
# root but declared by no layer is RECORDED as a disagreement with its reason,
# and never rounded up to an agreement.
#
# This block is that recording, and nothing more. It is ADVISORY and strictly
# ADDITIVE: `met` is decided exactly where it was decided before, so a moved
# verdict can never be attributed to it. Measured on a freshly generated
# 28-layer Phase-1 root, lane cz2150b.
#
# The vocabulary below names the plugin's OWN generated-L-doc containers — it
# is a statement about this repo's schema, not about any design, PDK or
# vendor. A container qualifies when its elements are undifferentiated: a row,
# a literal, a discovered name, a prose section. A named record's own field
# (`registers.fields.encoding.description`) is NOT generic — the path says
# what the value is.
GENERIC_CARRIAGE_SEGMENTS = frozenset({
    "auto_cited_sections",
    "auto_discovered_identifiers",
    "auto_discovered_literals",
    "comparison_tables",
    "corroborating_evidence",
    "evidence",
    "extraction_evidence",
    "frs_sections",
    "notes",
    "raw",
    # a raw table ROW, undifferentiated exactly as `comparison_tables.rows` is
    "rows",
    # a source SENTENCE lifted whole (`parameter_couplings.sentence`)
    "sentence",
    # the container that says in its own name that it is not structured
    "unstructured",
    "vendor_short_literals",
})

#: the three row-level answers, and the one that means the reading did not run.
CARRIAGE_NOWHERE = "NOWHERE"
CARRIAGE_GENERIC_ONLY = "GENERIC_ONLY"
CARRIAGE_NAMED_FIELD = "NAMED_FIELD_ELSEWHERE"

CARRIAGE_RULE = (
    "a generic bucket does not satisfy a layer obligation unless a consumer "
    "reads it by that path; a fact present in the root but declared by no "
    "layer is recorded as a disagreement with its reason, never rounded up "
    "to an agreement (#2150)"
)


def is_generic_carriage_path(path: str) -> bool:
    """Does this dotted path pass through a generic container?

    ANY segment, not just the first: `fields.tables.rows` is as generic at
    depth three as `comparison_tables.rows` is at depth two, and reading only
    the head would call the deeper one a named field.
    """
    return any(seg.strip().lower() in GENERIC_CARRIAGE_SEGMENTS
               for seg in str(path or "").split("."))


def token_paths(blob: Any, token: str) -> List[str]:
    """Every dotted path in this document whose SCALAR carries the token.

    List indices are elided — `registers[7].reset_value` and
    `registers[8].reset_value` are one path, because the question is which
    FIELD carries the fact and not how many records do. Uses the same
    `phrase_present` the comparator uses, so the two can never disagree about
    whether a token is present.
    """
    hits: List[str] = []

    def walk(node: Any, path: List[str]) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, path + [str(k)])
        elif isinstance(node, list):
            for v in node:
                walk(v, path)
        elif node is not None and phrase_present(token, str(node)):
            hits.append(".".join(path))

    walk(blob, [])
    return sorted(set(hits))


def token_carriage(project: Path, tokens: List[str],
                   exclude: Optional[Path] = None) -> Dict[str, Any]:
    """WHERE each token lives across the layers, split named vs generic.

    `exclude` is the layer the expectation already addressed: it has been read
    and found wanting, and counting it as somewhere-else would answer the
    question with the layer that raised it.
    """
    per_token: Dict[str, Dict[str, Any]] = {}
    for tok in tokens:
        per_token[tok] = {"named": {}, "generic": {}}
    if not tokens:
        return {"verdict": CARRIAGE_NOWHERE, "per_token": per_token,
                "rule": CARRIAGE_RULE}

    for p in emitted_layer_files(project):
        if exclude is not None and p == exclude:
            continue
        try:
            blob = json.loads(p.read_text(errors="replace"))
        except (OSError, ValueError):
            continue          # unreadable content is not content
        for tok in tokens:
            paths = token_paths(blob, tok)
            named = [q for q in paths if not is_generic_carriage_path(q)]
            generic = [q for q in paths if is_generic_carriage_path(q)]
            if named:
                per_token[tok]["named"][p.stem] = named
            if generic:
                per_token[tok]["generic"][p.stem] = generic

    if any(v["named"] for v in per_token.values()):
        verdict = CARRIAGE_NAMED_FIELD
    elif any(v["generic"] for v in per_token.values()):
        verdict = CARRIAGE_GENERIC_ONLY
    else:
        verdict = CARRIAGE_NOWHERE
    # WHICH tokens the verdict is made of. The verdict above is an OR over
    # tokens — one token in a named field makes the row NAMED_FIELD_ELSEWHERE
    # even where the rest are nowhere — and a reader who cannot see the split
    # would read it as a statement about the whole fact. State it instead of
    # implying it.
    carried = sorted(t for t, v in per_token.items() if v["named"] or v["generic"])
    return {"verdict": verdict, "per_token": per_token, "rule": CARRIAGE_RULE,
            "tokens_carried_elsewhere": carried,
            "tokens_in_no_layer": sorted(set(per_token) - set(carried))}


def carriage_sentence(carriage: Dict[str, Any]) -> str:
    """The one sentence a finding adds, in the words of the ruling."""
    v = carriage.get("verdict")
    if v == CARRIAGE_NOWHERE:
        return ("Carriage: the missing token(s) are in NO other layer either, "
                "so this is a content gap and not a scoping one.")
    per = carriage.get("per_token") or {}
    if v == CARRIAGE_GENERIC_ONLY:
        where = sorted({f"{stem}.{q}"
                        for t in per.values()
                        for stem, qs in t["generic"].items() for q in qs})
        return ("Carriage: the fact is in the root ONLY under a generic "
                f"bucket ({', '.join(where[:4])}) and under no field named "
                "for it. Recorded as a DISAGREEMENT, not promoted: "
                + CARRIAGE_RULE + ".")
    where = sorted({f"{stem}.{q}"
                    for t in per.values()
                    for stem, qs in t["named"].items() for q in qs})
    return ("Carriage: a field NAMED for the fact carries it in another "
            f"layer ({', '.join(where[:4])}), so this is a layer-contract "
            "question — which layer owns it — and not a content gap.")


# ── rendering a SPLIT finding (#2190) ──────────────────────────────────────
# A split parent's `layer`, `field_path` and `expected_tokens` are EMPTY BY
# CONTRACT (`SPLIT_MARKER`, above): it addresses no single field and no single
# layer, so answering DECLARED or True for it would report a reading of one
# branch as a reading of the expectation. That contract is right and is not
# what changed here.
#
# WHAT WAS MEASURED (2026-09-08, lane cz2190, on ab8d9ce834f0). The three
# finding emitters read those parent fields as if a single expectation had
# supplied them, so every finding raised on a split rendered::
#
#   "The AI sub-track asked None for: <requirement>. That layer does not carry
#    it, and ['L4_REGMAP'] DOES — every one of the 0 expected token(s). ...
#    or — if the layer contract really does put it in None — ..."
#
# Three separate falsehoods in one sentence, and the third is load-bearing:
# `every one of the 0 expected token(s)` is a VACUOUS UNIVERSAL printed as the
# positive evidence that the fact was extracted, and the sentence built on it
# then instructs the reader not to repair an extractor. The claim underneath
# is sound — `owning_layers` for a split is computed per failing branch — but
# a reader auditing the finding cannot tell a real re-scope from a vacuous
# one, which is the confusion #2127 existed to remove.
#
# A SPLIT IS ANSWERED BRANCH BY BRANCH, SO IT IS REPORTED BRANCH BY BRANCH.
# The parent's `owning_layers` is a UNION over the failing branches, and a
# union is not an owner: on the measured shape `['L19...', 'L4...']` was
# printed as carrying "every one of" the tokens when L4 carried one half and
# L19 the other and NEITHER carried both. Substituting a real token count into
# the same union sentence would have replaced a vacuous claim with a false
# one. Only the per-branch form is true, so that is the form these render.
def _branch_address(b: Dict[str, Any]) -> str:
    """`LAYER.field_path` — the address ONE branch actually asked."""
    return f"{b['layer']}{'.' + b['field_path'] if b['field_path'] else ''}"


def _branch_token_count(b: Dict[str, Any]) -> int:
    """How many tokens THIS branch compared. Never the parent's zero."""
    return len(b.get("expected_tokens") or [])


def _split_branch_rows(c: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The machine-readable half of a split finding: one row per branch.

    Carried BESIDE the parent's `layer`/`field_path` rather than instead of
    them, and only on a split. A reviewer triaging a run's Phase-1 findings
    had no way to see WHICH addresses a split expectation asked or HOW MANY
    tokens were compared — the parent fields cannot say, by construction, and
    the prose was saying it wrongly. This says it in the one place where each
    answer has a single referent.
    """
    return [{
        "id": b["id"],
        "layer": b["layer"],
        "field_path": b["field_path"],
        "expected_token_count": _branch_token_count(b),
        "met": b["met"],
        "layer_present": b["layer_present"],
        "owning_layers": b.get("owning_layers") or [],
    } for b in (c.get("sub_results") or [])]


def _split_addresses(c: Dict[str, Any]) -> str:
    """Every branch address of a split, in order, for one prose clause."""
    return ", ".join(_branch_address(b) for b in (c.get("sub_results") or []))


def _failed_branches(c: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The branches that DISAGREED — the same set `_converge_split` took the
    parent's `owning_layers` from, recomputed here so the finding text and the
    parent field can never be about two different sets."""
    return [b for b in (c.get("sub_results") or []) if not b["met"]]


def _absent_branches(c: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The branches addressing a layer this Phase-1 root does not carry."""
    return [b for b in (c.get("sub_results") or [])
            if b["layer_present"] is False]


def _converge_qualified_output(project: Path, base: dict, exp: dict) -> dict:
    """An independently authored finite relation, compared without token search.

    This is not a waiver: missing/foreign citations, wrong output roles, a
    malformed expectation or disagreeing aliases stay undecidable/unmet. D1
    review/signing and the oracle's existing trust reader remain unchanged.
    """
    import _qualified_by as qb
    fact, basis = exp.get("qualified_by"), exp.get("basis")
    if (not isinstance(fact, dict) or set(fact) != {"output", "port", "active_level"}
            or not isinstance(fact.get("output"), str)
            or not isinstance(fact.get("port"), str)
            or fact.get("active_level") not in ("high", "low")
            or base["id"] != f"qualified_by:{fact.get('output')}"
            or base["layer"] != qb.EXPECTATION_LAYER
            or base["field_path"] != "top_ports"):
        base["observed"] = "qualified output expectation needs its exact id/layer/path/output/port/high|low contract"
        return base
    if (not isinstance(basis, list) or not basis
            or any(not isinstance(b, dict) or set(b) != {"file", "line", "quote"}
                   or type(b.get("line")) is not int for b in basis)):
        base["observed"] = "qualified output expectation needs exact typed source citations"
        return base
    why = qb.basis_refusal(project, basis, fact["output"], fact["port"])
    if why:
        base["observed"] = f"qualified output expectation basis refused: {why}"
        return base
    base.update(qualified_by=dict(fact), basis=basis, usable=True,
                scope="exact_qualified_output_relation", owning_layers_status="OK")
    path = resolve_layer_file(project, base["layer"])
    if path is None:
        base.update(layer_present=False, layer_in_taxonomy=True,
                    observed="the program track produced no L9_INTEGRATION_SPEC layer at all")
        return base
    base["layer_present"] = True
    try:
        import l_doc_consumer_contract as ldc
        content = ldc.l_doc_fields(json.loads(path.read_text()))
        aliases = []
        for key in ("ports", "top_ports", "top_module_pins"):
            rows = content.get(key)
            if not isinstance(rows, list):
                raise ValueError(f"{key} is not a port list")
            ports = {}
            for row in rows:
                if (not isinstance(row, dict) or not isinstance(row.get("name"), str)
                        or row["name"] in ports):
                    raise ValueError(f"{key} contains malformed or duplicate port rows")
                ports[row["name"]] = row
            d, q = ports.get(fact["output"], {}), ports.get(fact["port"], {})
            if (d.get("direction", d.get("mode")) != "output"
                    or type(d.get("width")) is not int or d["width"] <= 1
                    or q.get("direction", q.get("mode")) != "output"
                    or type(q.get("width")) is not int or q["width"] != 1
                    or fact["output"] == fact["port"]
                    or (content.get("selected_interface_binding") and
                        (d.get("declared_by_staged_top") is not True or
                         q.get("declared_by_staged_top") is not True))
                    or any(re.search(r"(?:^|_)(?:clk|clock|rst|reset|resetn|rstn)(?:$|_)",
                                     name, re.I) for name in (fact["output"], fact["port"]))):
                raise ValueError(f"{key} does not carry the current data-output/qualifier-output roles")
            declared = d.get("qualified_by")
            if not isinstance(declared, dict) or set(declared) != {"port", "active_level", "basis"}:
                raise ValueError(f"{key} has no exact qualified_by field for {fact['output']}")
            why = qb.basis_refusal(project, declared.get("basis"), fact["output"], fact["port"])
            if why:
                raise ValueError(f"{key} field basis refused: {why}")
            aliases.append(declared)
        serialized = [json.dumps(value, sort_keys=True, ensure_ascii=False) for value in aliases]
        if len(set(serialized)) != 1:
            raise ValueError("the three L9 qualified_by aliases disagree")
        base["field_path_status"] = "DECLARED"
        base["met"] = (aliases[0]["port"] == fact["port"] and
                       aliases[0]["active_level"] == fact["active_level"])
        base["observed"] = ("all three L9 aliases carry the exact independently authored relation"
                            if base["met"] else "L9 carries a different qualifier or active level")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        base["observed"] = f"qualified output relation unmet: {exc}"
    return base


def converge_ai_expectation(project: Path, exp: Any) -> Dict[str, Any]:
    """Decide ONE AI expectation against what the program track actually wrote.

    Returns the expectation enriched with `met` / `observed` / `usable`. Any
    `met` the answer carried is DISCARDED before the decision — see the module
    docstring on why the AI half must not score itself.

    TWO GRAMMARS (#2150). An expectation is either SINGLE — one `layer`, one
    optional `field_path`, one `expected_tokens` list — or SPLIT: a
    `sub_expectations` list of branches, each with its own layer, field_path
    and tokens, ALL of which must agree. A split is decided branch by branch
    through exactly the same single-expectation machinery, so scoping, the
    field_path guard and the owning-layer answer apply per branch, unchanged.

    WHY A SPLIT HAD TO EXIST. MEASURED on the surviving opentitan_aes Phase-1
    root: an expectation whose two halves the program track extracted into two
    DIFFERENT layers (the FSM encoding in L1, the power budget in L19) is
    `met: False` in either layer, and `owning_layers` is empty because no
    single layer carries every token. It is therefore published as
    `about: "design"` — "the program track is missing this" — about a fact the
    program track has, in full, twice over. A conjunction that cannot be
    written down is not a fact the corpus lacks; it is a sentence the grammar
    cannot say, and the report blames the design for the difference.

    THE SPLIT IS A CONJUNCTION, NOT A DISJUNCTION. Every branch must agree.
    An "any branch" form would make a two-branch expectation EASIER to satisfy
    than either of its halves, which is a comparator that gets weaker as an
    author writes more — the opposite of what this track is for.
    """
    base: Dict[str, Any] = {
        "id": None, "layer": None, "field_path": None, "requirement": None,
        "evidence": [], "expected_tokens": [],
        "usable": False, "met": False, "observed": "",
        # #2127. `field_path_status` is NOT_MEASURED until a layer document is
        # in hand: an expectation refused before that was never checked against
        # a schema, and recording it as UNDECLARED would report a reading that
        # did not happen. `owning_layers` is [] only where it was computed.
        "field_path_status": "NOT_MEASURED", "owning_layers": [],
        # #2191. WHETHER the ownership question was answered at all.
        # NOT_MEASURED until it is asked; OK when it was decided;
        # NO_DISCRIMINATING_TOKEN when it was REFUSED because no expected
        # token can tell one layer from another. The third state exists
        # because `owning_layers: []` already means "no layer carries this",
        # which the consumer publishes as a finding about the DESIGN — and a
        # question that could not be asked must never be answered with a
        # design gap.
        "owning_layers_status": "NOT_MEASURED",
        "owning_layers_refusal": None,
        # WHERE each owning layer carried each token — the unit text — so the
        # ownership claim can be falsified from the report rather than only by
        # re-running the comparator.
        "owning_layers_evidence": {},
        # WHERE the token search happened: `field_path` when the named path
        # resolved, `whole_layer` when it did not. NOT_MEASURED until a layer
        # document is in hand.
        "scope": "NOT_MEASURED",
        # None = the expectation was not withdrawn. "" = it was withdrawn with
        # no usable reason, which is refused. A non-empty string is the reason.
        "withdrawn_reason": None,
        # #2150. Whether the Phase-1 root CONTAINS the layer this expectation
        # addresses. NOT_MEASURED until the lookup is done, for the same
        # reason `field_path_status` is: an expectation refused before the
        # root was consulted was never checked against one.
        "layer_present": "NOT_MEASURED",
        # Whether the L-doc TAXONOMY declares a layer of this name. Only
        # consulted when the root does not carry the document, so it stays
        # NOT_MEASURED whenever the question did not arise.
        "layer_in_taxonomy": "NOT_MEASURED",
        # #2150 item 2. The expected tokens this comparator CANNOT ASK FOR.
        # Computed from the tokens and the matcher alone, before any document
        # is opened, so it is the same answer for every design.
        "tokens_unaskable": [],
    }
    if not isinstance(exp, dict):
        base["observed"] = ("the answer contained an entry that is not an "
                            "object, so nothing about it can be checked")
        return base

    base.update({
        "id": exp.get("id") or exp.get("expectation_id"),
        "layer": exp.get("layer"),
        "field_path": exp.get("field_path"),
        "requirement": exp.get("requirement"),
        "evidence": exp.get("evidence") or [],
        "expert_source": exp.get("expert_source"),
        "expected_tokens": [t for t in (exp.get("expected_tokens") or [])
                            if isinstance(t, str) and t.strip()],
    })

    # #2127 second addendum — a WITHDRAWAL is read before anything is decided.
    # `withdrawn` may be the reason string itself or an object carrying one;
    # both spellings are accepted, and a reason that is absent, blank or not a
    # string leaves `withdrawn_reason` as "", which the caller REFUSES.
    wd = exp.get("withdrawn")
    if wd is not None and wd is not False:
        reason = wd.get("reason", "") if isinstance(wd, dict) else wd
        # ONLY A STRING IS A REASON. `withdrawn: true` is the bare marker this
        # refusal exists to catch, and an earlier revision of this block ran it
        # through `str()` and recorded the reason as "True" — a withdrawal that
        # refused nothing, spelled exactly like one that stated something. Its
        # own test caught it.
        base["withdrawn_reason"] = reason.strip() if isinstance(reason, str) \
            else ""
        if base["withdrawn_reason"]:
            base["observed"] = (f"WITHDRAWN by the author: "
                                f"{base['withdrawn_reason']}")
            return base
        # fall through: a reasonless withdrawal is not honoured, so the
        # expectation is decided exactly as if it had never carried one.

    # ── SPLIT or SINGLE (#2150) ────────────────────────────────────────────
    # Dispatched HERE: after the withdrawal (a split can be withdrawn like any
    # other row) and before the single-expectation checks, whose `layer` and
    # `expected_tokens` requirements a split parent deliberately does not meet.
    raw_split = exp.get(SPLIT_KEY)
    if raw_split is not None:
        return _converge_split(project, base, exp, raw_split)

    if ("qualified_by" in exp or
            isinstance(base["id"], str) and base["id"].startswith("qualified_by:")):
        return _converge_qualified_output(project, base, exp)

    if not base["id"] or not base["layer"]:
        base["observed"] = ("the expectation names no id and/or no layer, so "
                            "there is nothing to compare it against")
        return base
    if not base["expected_tokens"]:
        base["observed"] = (
            "the expectation carries no `expected_tokens`, so it states a "
            "requirement in prose only. A prose-only expectation cannot be "
            "decided by a program and must not be counted as agreed")
        return base

    base["usable"] = True
    # #2150 item 2 — asked BEFORE the Phase-1 root is opened, because it is a
    # question about the expectation and the matcher, not about the design.
    # Recorded, never acted on here: `met` is decided over the whole layer
    # exactly as it was, so no verdict moves and no moved verdict can be
    # attributed to this check — the separation #2127 and #2191 both kept.
    base["tokens_unaskable"] = unaskable_tokens(base["expected_tokens"])
    path = resolve_layer_file(project, base["layer"])
    if path is None:
        # #2150 — the LAYER is absent from the Phase-1 root. Recorded as its
        # own fact rather than left to fall through: the whole-layer reading
        # never happened, so `met: False` here is not a statement about the
        # design and the caller must not file it as one.
        base["layer_present"] = False
        base["layers_in_root"] = [q.stem for q in emitted_layer_files(project)]
        # Is this a layer the CONTRACT declares? The two cases need different
        # readers: a declared layer the root does not carry is the program
        # track not emitting a document its own taxonomy applies (#312's
        # disagreement, kept), and an undeclared one is an expectation
        # addressing a document this plugin never emits (#2150, refused).
        base["layer_in_taxonomy"] = layer_declared_by_taxonomy(base["layer"])
        # Asked even though the addressed layer is missing: a fact that lives
        # wholly in a layer the root DOES carry is a re-scope with a named
        # destination. `exclude=None` — there is no addressed file to exclude.
        # Additive: it cannot make a row agree, only say where the fact is.
        _own = owning_layers_answer(project, base["expected_tokens"])
        base["owning_layers"] = _own["layers"]
        base["owning_layers_status"] = _own["status"]
        base["owning_layers_refusal"] = _own["refusal"]
        base["owning_layers_evidence"] = _own["evidence"]
        # The FIRST sentence is unchanged from before this landing. Downstream
        # readers (and #312's own test) quote it, and a landing that rewords a
        # sentence it did not need to change makes itself unreviewable.
        base["observed"] = (
            f"the program track produced no {base['layer']} layer at all"
            + (" — and the L-doc taxonomy declares no layer of that name, so "
               "no document of this kind is emitted for any ic_class"
               if not base["layer_in_taxonomy"] else
               f" (the taxonomy DOES declare it; this Phase-1 root carries "
               f"{len(base['layers_in_root'])} layer document(s) and not "
               f"that one)")
            + (f"; {base['owning_layers']} carries every one of the "
               f"{len(base['expected_tokens'])} expected token(s)"
               if base["owning_layers"] else
               f"; and WHERE ELSE the fact lives was not decided — "
               f"{base['owning_layers_refusal']}"
               if base["owning_layers_status"] == "NO_DISCRIMINATING_TOKEN"
               else ""))
        return base
    base["layer_present"] = True
    try:
        blob = json.loads(path.read_text(errors="replace"))
    except (OSError, ValueError) as exc:
        base["observed"] = (f"{base['layer']} exists but does not parse "
                            f"({exc.__class__.__name__}); unreadable content "
                            f"is not content")
        return base

    # #2127 — the guard. Read BEFORE the token search and kept independent of
    # it: `met` is decided over the whole layer exactly as it was, so a moved
    # verdict can never be attributed to this check.
    base["field_path_status"] = field_path_status(
        blob, base["field_path"], base["layer"])
    if base["field_path_status"] == "UNDECLARED":
        base["layer_declares"] = sorted(
            blob.keys() if isinstance(blob, dict) else [])

    # #2127 addendum (#2128) — WHERE the tokens are looked for.
    #
    # The reading is SCOPED to the field the expectation names whenever that
    # path resolves. Unscoped, any field of the layer can satisfy any token:
    # MEASURED on a real run, adding an unrelated boolean key to L19 made the
    # token "false" score and moved a row from 2-missing to 1-missing, on a
    # coincidence. A coincidence can score as agreement in both directions.
    #
    # When the path does NOT resolve there is nowhere to scope to, and the
    # whole-layer reading is kept — moving those verdicts is a much larger
    # decision than this one and would need its own landing — but the scope is
    # RECORDED, so a `met` obtained without scoping is visibly the weaker
    # claim it is rather than passing for a reading at the named field.
    subtree = subtree_at(blob, base["field_path"], base["layer"])
    if subtree is None:
        base["scope"] = "whole_layer"
        units = _haystack_units(blob)
    else:
        base["scope"] = "field_path"
        units = [u for node in subtree for u in _haystack_units(node)]

    missing = [t for t in base["expected_tokens"]
               if not present_in_units(t, units)]
    base["met"] = not missing
    base["missing_tokens"] = missing
    where = (f"{base['layer']}.{base['field_path']}"
             if base["scope"] == "field_path" else
             f"{base['layer']} (WHOLE LAYER — the expectation's field_path "
             f"{base['field_path']!r} does not resolve, so the reading is "
             f"UNSCOPED and any field of the layer could satisfy a token)")
    base["observed"] = (
        f"{where} carries all of {base['expected_tokens']}"
        if not missing else
        f"{where} does not carry {missing} "
        f"(checked {len(base['expected_tokens'])} expected token(s))")
    if missing:
        # Where else in the program track's own output does this fact live?
        # Asked ONLY on a miss: on a hit there is nothing to re-scope, and
        # walking every layer for an expectation already satisfied would be
        # work whose answer nobody reads.
        _own = owning_layers_answer(
            project, base["expected_tokens"], exclude=path)
        base["owning_layers"] = _own["layers"]
        base["owning_layers_status"] = _own["status"]
        base["owning_layers_refusal"] = _own["refusal"]
        base["owning_layers_evidence"] = _own["evidence"]
        # #2150. WHERE the missing tokens live, and under what KIND of path.
        # Asked over the MISSING tokens alone: a token the addressed layer
        # already carries has no carriage question, and folding it in would
        # let a satisfied token supply a named field for an unsatisfied fact.
        #
        # #2191 ADDS BESIDE THIS, NEVER INSTEAD OF IT. `carriage` reads the
        # WHOLE document, envelope included, and answers a different question
        # — under what KIND of path a token sits — while the ownership answer
        # above now reads CONTENT ONLY and answers WHICH layer owns it. Both
        # are kept and neither is derived from the other: a carriage verdict
        # computed off the ownership haystack would silently change what
        # #2150 landed, and #2150 is the contract here.
        base["carriage"] = token_carriage(project, missing, exclude=path)
    return base


# ── the AI sub-track ────────────────────────────────────────────────────────

def ai_subtrack(project: Path, prompt: str, out_dir: Path,
                ic_class=None, class_availability=None) -> Dict[str, Any]:
    """Hand the open-ended reading to the IC Expert Agent.

    Uses `ic_expert_backup_pack` — the assembler this doctrine already built
    for this hand-off (expert-skills digest as one author, expert-DB digest as
    an independent second, then converge). Reused rather than reimplemented;
    it is tested and it is the doctrine's own mechanism.

    A program cannot spawn a subagent, so this emits the pack + the hand-off
    descriptor that names exactly which subagent to invoke, and consumes the
    agent's answer if a previous invocation left one. Every outcome is a
    STATED status:

        HANDOFF_EMITTED         pack ready, agent has not answered yet
        CONSUMED                an answer was read back, carrying expectations
        CONSUMED_EMPTY          an answer was read back and its `expectations`
                                list was empty — a reading, and a real zero
        ANSWER_SCHEMA_MISMATCH  an answer exists and PARSES, but is not this
                                consumer's schema. REFUSED, and the refusal
                                names the top-level keys that did arrive
        ERROR                   assembly failed, or the answer does not parse

    NOTHING HERE IS CONDITIONAL ON AN LLM BACKEND. Assembly is deterministic
    and the author is a SUBAGENT, so the in-process `anthropic` SDK is
    irrelevant to both. It is still probed and RECORDED as
    `inline_llm_backend`, because losing a fact is its own defect — but it can
    no longer veto a path that never used it. That veto is what kept this half
    at SKIPPED-CONDITION on all 8 published designs while making the pack no
    agent could answer and ignoring an answer already on disk (#312).
    """
    status: Dict[str, Any] = {"status": "ERROR", "reason": "",
                              "expectations": [], "pack_dir": str(out_dir)}

    try:
        import llm_semantic_confirm as _llm
        status["inline_llm_backend"] = bool(_llm.backend_available())
    except Exception:  # noqa: BLE001
        status["inline_llm_backend"] = False

    try:
        import ic_expert_backup_pack as _pack
        # CLASS-FIRST (#2094). The design's REGISTERED class goes in, so the
        # pack's db_classes are selected by the class and only ranked by the
        # phrase — and so the pack can say whether it is assembled at all.
        # `iface=None, target=None` stays: this hand-off asks for L-doc
        # expectations, not an RTL body, so there is no recovered port list to
        # hand over. Whether that leaves the pack empty is now the pack's own
        # stated verdict rather than something a reader has to notice.
        # #2150 F5 — the pack carries the AUTHORING schema, derived from this
        # project's own emitted L-docs and filtered through the resolver the
        # review-time guard uses. Passed rather than hard-coded in the pack:
        # the pack cannot see the project, and a contract that names two
        # layers for a root that has two dozen is what made every expectation
        # address one of those two.
        schema = authoring_schema(project)
        status["authoring_schema_status"] = schema["status"]
        status["authoring_schema_layer_count"] = len(schema.get("layers") or {})
        handoff = _pack.assemble(
            prompt=prompt, iface=None, target=None,
            expert_skills=[], verify_gates=[PROGRAM],
            out_dir=out_dir, k=5,
            output_target="l_doc_expectations.json",
            ic_class=ic_class, authoring_schema=schema)
        status["handoff"] = handoff
        # The disposition is recorded for EVERY design, profiled or not: the
        # pack file only gains a `class_first` block when there was a profile
        # to confine it with, so without this the unprofiled case would leave
        # no trace anywhere and "we did not confine" would be indistinguishable
        # from "there was nothing to confine".
        status["class_first"] = _pack.class_first_disposition(
            ic_class, availability=class_availability)
        status["pack_assembly_status"] = (
            (handoff.get("class_first") or {}).get("assembly_status")
            or "NOT_EVALUATED")
    except Exception as exc:  # noqa: BLE001
        status.update(status="ERROR", reason=f"pack assembly failed: {exc}")
        return status

    answer = out_dir / "l_doc_expectations.json"
    if answer.is_file():
        try:
            raw = answer.read_bytes()
            # Identify exactly the bytes parsed below, including a refused
            # answer. Pack-assembly/open failures carry no read receipt.
            status.update(answer_path=str(answer),
                          answer_sha256=hashlib.sha256(raw).hexdigest())
            data = json.loads(raw.decode("utf-8", errors="replace"))
        except (OSError, ValueError) as exc:
            status.update(status=AI_ERROR,
                          reason=f"agent answer does not parse: {exc}")
            return status
        # PARSING IS NOT UNDERSTANDING. An answer that is valid JSON and not
        # this consumer's schema is REFUSED, never consumed: `data.get(...)`
        # followed by `if isinstance(x, list) else []` turns every unexpected
        # shape into the same empty list, and an empty list is exactly what an
        # agent with nothing to say produces. The two must not share a record.
        mismatch = answer_schema_mismatch(data)
        if mismatch is not None:
            keys = mismatch["top_level_keys"]
            status.update(
                status=AI_SCHEMA_MISMATCH,
                reason=(
                    f"the agent answered, and the answer is not the shape this "
                    f"consumer reads: {mismatch['why']}. Top-level key(s) "
                    f"present: {keys if keys else '(none)'}. The answer was "
                    f"NOT read and NOT counted — an answer this consumer "
                    f"cannot read is a refusal, never a reading of zero"),
                answer_path=str(answer),
                answer_json_type=mismatch["json_type"],
                answer_schema_why=mismatch["why"],
                answer_top_level_keys=keys)
            return status
        exps = data["expectations"]
        status.update(
            status=AI_CONSUMED if exps else AI_CONSUMED_EMPTY,
            reason=(f"read {len(exps)} expectation(s) from a prior agent "
                    f"invocation" if exps else
                    "the agent answered and its `expectations` list was empty "
                    "— a real reading of zero, not a missing answer"),
            answer_path=str(answer),
            expectations=exps)
        return status

    status.update(
        status=AI_HANDOFF_EMITTED,
        reason=(f"pack written to {out_dir}; invoke subagent "
                f"{_pack.SUBAGENT_TYPE} on "
                f"{out_dir / 'ic_expert_agent_handoff.json'} and re-run to "
                f"consume its answer"))
    return status


# ── evaluate ────────────────────────────────────────────────────────────────

def evaluate(project: Path) -> Dict[str, Any]:
    # THE REPORT, not just the string (#2164): every number below that is
    # derived from the design input has to be able to say whether the input was
    # readable, and a bare `""` cannot.
    input_report = input_text_report(project)
    prompt = input_report["text"]
    readability = input_readability_disposition(input_report)
    out_dir = _pl.report_path(project, "phase1/expert_parse_track").parent \
        / "expert_parse_track_pack"

    availability = registered_ic_class_disposition(project)
    ic_class = availability.get("ic_class")
    rules = [fn(project) for fn in DETERMINISTIC_RULES]
    ai = ai_subtrack(project, prompt, out_dir, ic_class=ic_class,
                     class_availability=availability)

    # #2150 item 6 — A DECISION TABLE IS DATED BEFORE IT IS USED.
    # A table says, per expectation, where a fact belongs: re-point it to this
    # layer and this field, or withdraw it for this reason. It is authored by
    # reading ONE Phase-1 root and then applied to ANOTHER, and nothing
    # recorded which root it was computed on. MEASURED, applying #2132's 30-row
    # table to the opentitan_aes artefact: two OWNER cells name a leaf that
    # artefact does not declare, and three name fields introduced by work that
    # landed AFTER the emitter that wrote those layers — fields that could not
    # exist in it. None of that is a defect in the table; it is a table
    # computed on a newer root judging an older artefact. So the table carries
    # a stamp, and one whose stamp says it cannot describe this artefact is
    # refused BY NAME rather than applied hopefully.
    decision_table: Dict[str, Any] = {"present": False}
    try:
        import expert_decision_table as _dt
        tpath = out_dir / "decision_table.json"
        if tpath.is_file():
            v = _dt.load(project, tpath)
            decision_table = {
                "present": True, "path": str(tpath), "state": v["state"],
                "reason": v["reason"], "rows": v.get("rows", 0),
                "artefact_stamp": v.get("artefact_stamp"),
                "table_stamp": v.get("table_stamp"),
                "applied": v["state"] in _dt.APPLICABLE,
            }
        else:
            decision_table["reason"] = ("no decision table beside the pack — "
                                        "nothing to date, and nothing applied")
    except Exception as exc:  # noqa: BLE001 — a table that cannot be READ is
        # reported, never raised: the deterministic half of this track is
        # unaffected by it, so the run is not void, and an exception here would
        # take the whole report down with a file nothing else depends on.
        decision_table = {"present": False,
                          "reason": f"{exc.__class__.__name__}: {exc}"}

    findings: List[Dict[str, Any]] = []
    if decision_table.get("present") and not decision_table.get("applied"):
        findings.append({
            "severity": "REVIEW",
            "about": "track",
            "rule": RULE_DECISION_TABLE_NOT_APPLICABLE,
            "message": (
                f"A decision table is present and is NOT applied: "
                f"{decision_table['state']} — {decision_table['reason']}. "
                f"Refused rather than applied hopefully: every OWNER cell in a "
                f"table computed on another Phase-1 root is a claim about "
                f"fields that may not exist here, and a wrong re-pointing "
                f"reads exactly like a right one. Table: "
                f"{decision_table.get('path')}."),
        })
    # #2164, FIRST, because everything after it is derived from the query this
    # names. Reported rather than raised: the deterministic half of the track
    # reads the L documents and is unaffected, so the run is not void — but the
    # AI half's pack was assembled from nothing and no reader may credit it.
    if readability["retrieval_input"] == "NOT_MEASURED":
        findings.append({
            "severity": "REVIEW",
            "about": "track",
            "rule": RULE_INPUT_NOT_READABLE,
            "message": (
                f"The expert retrieval query is 0 characters because "
                f"{readability['reason']}. Everything downstream of it — the "
                f"retrieved expert classes, the phrase ranking inside the "
                f"class-first selection, and the prompt the AI sub-track was "
                f"handed — is NOT_MEASURED, not measured-as-empty. This is "
                f"about the READER, not about the design: the design input is "
                f"there and this track cannot open it."),
        })
    for r in rules:
        for e in r["expectations"]:
            if e["met"]:
                continue
            findings.append({
                "severity": "REVIEW",
                # `about` separates a finding about the DESIGN from one about
                # the TRACK ITSELF. A reader counting "what did the expert
                # track find in this design" must not be handed a run whose
                # only entry says the track's own AI half was unavailable —
                # that is the same conflation of two different zeros this
                # track exists to stop.
                "about": "design",
                "rule": f"{RULE_UNMET}::{e['id']}",
                "layer": e["layer"],
                "field_path": e["field_path"],
                "message": (
                    f"The expert track, reading the same design input "
                    f"independently, expected {e['layer']}."
                    f"{e['field_path']} to carry: {e['requirement']}. The "
                    f"program track produced: {e['observed']}. Grounds: "
                    f"{'; '.join(e['evidence'])}."),
                "expert_source": e["expert_source"],
            })

    # ── CONVERGE: the AI half's answer becomes findings, not a file ─────────
    converged = [converge_ai_expectation(project, e)
                 for e in (ai.get("expectations") or [])]
    ai["converged"] = converged
    for c in converged:
        if c["withdrawn_reason"] == "":
            findings.append({
                "severity": "REVIEW",
                "about": "track",
                "rule": f"{RULE_AI_WITHDRAWN_NO_REASON}::{c['id'] or '<unnamed>'}",
                "layer": c["layer"],
                "message": (
                    "The answer marks this expectation WITHDRAWN and states no "
                    "reason. The withdrawal is REFUSED and the expectation is "
                    "converged below exactly as if it had never carried one: "
                    "withdrawal is the one operation that can remove a row "
                    "from what this track reports, so it is the one that must "
                    "not be silent, and a marker saying only THAT something "
                    "was withdrawn is not a record of the decision."),
            })
            # deliberately NOT `continue` — the row is still decided.
        elif c["withdrawn_reason"]:
            findings.append({
                "severity": "REVIEW",
                "about": "track",
                "rule": f"{RULE_AI_WITHDRAWN}::{c['id']}",
                "layer": c["layer"],
                "field_path": c["field_path"],
                "message": (
                    f"The expectation is WITHDRAWN by its author, and the "
                    f"reason is recorded here rather than the row being "
                    f"deleted: {c['withdrawn_reason']} It is NOT converged "
                    f"against the design and is not a design finding; it "
                    f"remains in the denominator so a reader can see that a "
                    f"decision was taken, not that an expectation was never "
                    f"written."),
            })
            continue

        if not c["usable"]:
            findings.append({
                "severity": "REVIEW",
                # About the TRACK: an entry the comparator could not decide
                # says nothing about the design, and counting it as a design
                # finding would inflate what the AI half found.
                "about": "track",
                "rule": f"{RULE_AI_UNUSABLE}::{c['id'] or '<unnamed>'}",
                "layer": c["layer"],
                "message": (
                    f"The AI sub-track returned an expectation this track "
                    f"cannot converge: {c['observed']}. It is reported rather "
                    f"than dropped — an undecidable expectation that vanished "
                    f"would make the AI half look like it agreed."),
            })
            continue

        # ── the field_path guard, PER BRANCH, for a SPLIT (#2150) ─────────
        # The guard is ADDITIVE and independent of the verdict, so it is
        # emitted per branch and named `<parent id>#<i>`: a split whose third
        # branch names an undeclared path has ONE repairable branch, and a
        # refusal naming only the parent would send the author to re-read all
        # of them. The parent's own `field_path_status` is SPLIT — it
        # addresses no single field, and answering DECLARED for it would
        # report a reading of one branch as a reading of the expectation.
        for b in (c.get("sub_results") or []):
            if b["field_path_status"] != "UNDECLARED":
                continue
            findings.append({
                "severity": "REVIEW",
                "about": "track",
                "rule": f"{RULE_AI_FIELD_PATH_UNDECLARED}::{b['id']}",
                "layer": b["layer"],
                "field_path": b["field_path"],
                "message": (
                    f"Branch {b['id']} of this split expectation named "
                    f"field_path {b['field_path']!r} in {b['layer']}, and "
                    f"that layer declares no such path. It declares "
                    f"{b.get('layer_declares') or '(no top-level keys)'}. "
                    f"The branch is REFUSED by name rather than left to "
                    f"appear as a field that was checked: that branch's "
                    f"reading was decided over the WHOLE layer. Repair the "
                    f"branch's field_path to a path its layer declares."),
            })

        # ── the layer is not in the CONTRACT at all (#2150) ────────────────
        # Refused BY NAME and `about: "track"`, and only for a layer the
        # L-doc taxonomy does not declare. A DECLARED layer this root does not
        # carry stays the disagreement #312 made it: the program track did not
        # emit a document its own taxonomy applies, and silence there was the
        # original defect. What is refused here is an expectation addressing a
        # document this plugin never emits for any ic_class — the shape a
        # decision table computed over a DIFFERENT Phase-1 root produces, and
        # a shape no extractor can ever repair.
        if c["layer_present"] is False and c["layer_in_taxonomy"] is False:
            if c.get("split"):
                # #2190. `_converge_split` joins the absent branches' layer
                # names into the parent's `layer`, which the single form then
                # printed as ONE quoted name: `'L91_NOT_DECLARED, L21_POWER_
                # INTENT'` — a layer nothing declares because it is not a
                # layer name at all. Worse, that sentence asserts the taxonomy
                # declares no layer of "that name" about EVERY joined branch,
                # and the parent's `layer_in_taxonomy` is `all(...)` over the
                # absent branches: ONE undeclared branch is enough to refuse
                # the row, so the others can be declared layers this root
                # simply does not carry — a different fact, and #312's.
                # Separated, and the token counts taken per branch.
                absent = _absent_branches(c)
                undeclared = [b for b in absent if not b["layer_in_taxonomy"]]
                declared_absent = [b for b in absent if b["layer_in_taxonomy"]]
                message = (
                    f"The AI sub-track asked this as a "
                    f"{len(c['sub_results'])}-branch SPLIT, and "
                    f"{len(undeclared)} of its branch(es) address a layer "
                    f"name the L-doc taxonomy does not declare — so no "
                    f"Phase-1 root of any design carries it and no extractor "
                    f"can produce it: "
                    + "; ".join(f"[{b['id']}] {_branch_address(b)}, "
                                f"{_branch_token_count(b)} expected token(s)"
                                for b in undeclared)
                    + (f". Refused WITH them, because a conjunction is "
                       f"answered only when every term is: "
                       + "; ".join(
                           f"[{b['id']}] {_branch_address(b)}, "
                           f"{_branch_token_count(b)} expected token(s), "
                           f"whose layer the taxonomy DOES declare and this "
                           f"root does not carry" for b in declared_absent)
                       if declared_absent else "")
                    + f". This root carries "
                      f"{c.get('layers_in_root') or '(no layer document)'}. "
                      f"The miss is a fact about the EXPECTATION, not about "
                      f"the design"
                    + ("; and each refused branch's half IS carried "
                       "elsewhere — "
                       + "; ".join(
                           f"[{b['id']}] {b['owning_layers']} carries every "
                           f"one of its {_branch_token_count(b)} expected "
                           f"token(s)" for b in absent)
                       + ", so the repair is to re-scope each of those "
                         "branches there"
                       if c["owning_layers"] else
                       ". Either re-scope each branch named above to a layer "
                       "the taxonomy declares, or state that the expectation "
                       "was computed over a DIFFERENT artefact than the one "
                       "being judged — an expectation naming a layer that "
                       "does not exist answers a different question rather "
                       "than disagreeing with this one") + ".")
            else:
                message = (
                    f"The AI sub-track addressed layer {c['layer']!r}, and "
                    f"the L-doc taxonomy declares no layer of that name — so "
                    f"no Phase-1 root of any design carries it and no "
                    f"extractor can produce it. This root carries "
                    f"{c.get('layers_in_root') or '(no layer document)'}. "
                    f"The miss is a fact about the EXPECTATION, not about the "
                    f"design"
                    + (f"; {c['owning_layers']} carries every one of the "
                       f"{len(c['expected_tokens'])} expected token(s), so "
                       f"the repair is to re-scope the expectation there"
                       if c["owning_layers"] else
                       f"; and WHERE ELSE the fact lives could not be "
                       f"determined — {c['owning_layers_refusal']}"
                       if c["owning_layers_status"] ==
                       "NO_DISCRIMINATING_TOKEN" else
                       ". Either re-scope it to a layer the taxonomy "
                       "declares, or state that the expectation was computed "
                       "over a DIFFERENT artefact than the one being judged "
                       "— an expectation naming a layer that does not exist "
                       "answers a different question rather than "
                       "disagreeing with this one") + ".")
            findings.append({
                "severity": "REVIEW",
                "about": "track",
                "rule": f"{RULE_AI_LAYER_ABSENT}::{c['id']}",
                "layer": c["layer"],
                "field_path": c["field_path"],
                "owning_layers": c["owning_layers"],
                "layers_in_root": c.get("layers_in_root") or [],
                "message": message,
                "expert_source": c.get("expert_source"),
                **({"split_branches": _split_branch_rows(c)}
                   if c.get("split") else {}),
            })
            continue

        # ── the field_path guard (#2127) ───────────────────────────────
        # ADDITIVE and independent of the verdict: the expectation named a
        # path the layer does not declare, and until this refusal that path
        # was repeated verbatim in the finding text as though it had been
        # read. Refused BY NAME so the author can repair the ONE expectation,
        # and `about: "track"` so it never counts as something found in the
        # design.
        if c["field_path_status"] == "UNDECLARED":
            findings.append({
                "severity": "REVIEW",
                "about": "track",
                "rule": f"{RULE_AI_FIELD_PATH_UNDECLARED}::{c['id']}",
                "layer": c["layer"],
                "field_path": c["field_path"],
                "message": (
                    f"The AI sub-track named field_path "
                    f"{c['field_path']!r} in {c['layer']}, and that layer "
                    f"declares no such path. It declares "
                    f"{c.get('layer_declares') or '(no top-level keys)'}. "
                    f"The expectation is REFUSED by name rather than left to "
                    f"appear in a finding as a field that was checked: the "
                    f"verdict below was decided over the WHOLE layer, so a "
                    f"reader told that {c['layer']}.{c['field_path']} is "
                    f"empty is being told about a field nothing looked at. "
                    f"Repair the expectation's field_path to a path the "
                    f"owning layer declares."),
            })

        if c["met"]:
            continue

        # ── the fact IS extracted, one layer over (#2127) ──────────────────
        # A miss the addressed layer does not explain: another layer the
        # program track wrote carries EVERY expected token. Reporting that as
        # a design finding says the tree is missing something it demonstrably
        # has — which is how ten expectations asking L9 for a register map
        # were recorded as extraction gaps while the register layer carried
        # the registers. `about: "track"`, because the repair is to the
        # expectation's scope or to the layer contract, never to an extractor.
        # ── the ownership question could not be ASKED (#2191) ──────────────
        # Checked BEFORE the misscope branch, and it does not fall through to
        # `RULE_AI_UNMET`: a refused ownership answer carries an empty
        # `owning_layers`, and letting it reach the design column would file
        # "the program track is missing this" on the strength of a question
        # nobody could answer. `about: "track"` — the repair is to the
        # expectation's tokens.
        # ── a token the comparator could not ASK FOR (#2150 item 2) ───────
        # Checked BEFORE the ownership refusal and before the misscope
        # branch, and it does not fall through to `RULE_AI_UNMET`. One
        # unaskable token empties `owning_layers` (the answer is the
        # intersection over the tokens) and forces `met` False (`met` is `not
        # missing`), so without this branch the row arrives in the design
        # column carrying a verdict the comparator never actually reached.
        # `about: "track"` — the repair is to the expectation's tokens, never
        # to an extractor, and there is nothing here for a Phase-1 emitter to
        # produce.
        if c["tokens_unaskable"]:
            findings.append({
                "severity": "REVIEW",
                "about": "track",
                "rule": f"{RULE_AI_TOKEN_UNASKABLE}::{c['id']}",
                "layer": c["layer"],
                "field_path": c["field_path"],
                "expected_tokens": c["expected_tokens"],
                "tokens_unaskable": c["tokens_unaskable"],
                "message": (
                    f"The AI sub-track asked "
                    f"{c['layer'] or 'a SPLIT expectation'}"
                    f"{'.' + c['field_path'] if c['field_path'] else ''} for: "
                    f"{c['requirement']}. "
                    f"{len(c['tokens_unaskable'])} of its "
                    f"{len(c['expected_tokens']) or 'expected'} token(s) is a "
                    f"token this comparator CANNOT ASK FOR, so the row was "
                    f"never decided about the design: "
                    + "; ".join(
                        (f"[{u['branch']}] " if u.get("branch") else "")
                        + f"{u['token']!r} ({u['reason']}) — {u['why']}"
                        for u in c["tokens_unaskable"])
                    + ". This is NOT a missing extraction and must not be "
                      "repaired in an extractor: no Phase-1 root of any "
                      "design can satisfy it, because the question was never "
                      "put to one. Repair the expectation's tokens to the "
                      "language the matcher reads — see `expected_tokens` in "
                      "the authoring schema — and the row becomes decidable "
                      "in either direction."),
                "expert_source": c.get("expert_source"),
            })
            continue

        if c["owning_layers_status"] == "NO_DISCRIMINATING_TOKEN":
            findings.append({
                "severity": "REVIEW",
                "about": "track",
                "rule": f"{RULE_AI_OWNERSHIP_UNDECIDABLE}::{c['id']}",
                "layer": c["layer"],
                "field_path": c["field_path"],
                "owning_layers": [],
                "expected_tokens": c["expected_tokens"],
                "message": (
                    f"The AI sub-track asked {c['layer']}"
                    f"{'.' + c['field_path'] if c['field_path'] else ''} for: "
                    f"{c['requirement']}. That layer does not carry it. "
                    f"WHETHER ANOTHER LAYER DOES was NOT decided: "
                    f"{c['owning_layers_refusal']}. So this row is neither a "
                    f"re-scope nor a gap in the design — it is an expectation "
                    f"whose tokens cannot distinguish one layer from another. "
                    f"Repair the expectation to name at least one token that "
                    f"can, then the ownership question becomes answerable."),
                "expert_source": c.get("expert_source"),
            })
            continue

        # NO `carriage` ON THIS FINDING, AND THAT IS THE RULED ANSWER, NOT AN
        # OVERSIGHT (#2191 / #2150, owner ruling 2026-09-08). `carriage` is
        # surfaced only on the `RULE_AI_UNMET` finding below; the
        # `RULE_AI_MISSCOPED` branch that follows has never carried one
        # either, and this branch is its sibling — both are `about: "track"`.
        # `base["carriage"]` IS still computed for these rows, so nothing is
        # lost from the record, only from this finding's prose. Making a track
        # finding carry the carriage sentence is a change to #2150's scope and
        # needs #2150's own evidence: WHICH rows, and what the sentence would
        # even say when the ownership answer was REFUSED. Asked and deferred —
        # do not re-derive it.

        if c["owning_layers"]:
            if c.get("split"):
                # #2190. BRANCH BY BRANCH. The parent asked no single layer
                # and compared no tokens of its own, and its `owning_layers`
                # is a union across the disagreeing branches — so the single
                # form's sentence would name `None` as the layer, `0` as the
                # token count, and a union as the carrier of tokens no single
                # member of it carries.
                failed = _failed_branches(c)
                message = (
                    f"The AI sub-track asked this as a "
                    f"{len(c['sub_results'])}-branch SPLIT, and "
                    f"{len(failed)} of its branch(es) disagree, for: "
                    f"{c['requirement']}. The layer each disagreeing branch "
                    f"addressed does not carry that branch's half, and "
                    f"another layer DOES — stated per branch, because a "
                    f"split is decided per branch and no single layer need "
                    f"carry the whole conjunction: "
                    + "; ".join(
                        f"[{b['id']}] asked {_branch_address(b)} for "
                        f"{_branch_token_count(b)} expected token(s), and "
                        f"{b['owning_layers']} carries every one of them"
                        for b in failed)
                    + ". So the fact was extracted and those branches named "
                      "the wrong layer; this is NOT a missing extraction and "
                      "must not be repaired in an extractor. Either re-scope "
                      "each branch named above to the layer that owns its "
                      "half, or — if the layer contract really does put a "
                      "branch's half where that branch asked — record that "
                      "as a layer-contract defect in its own right.")
            else:
                message = (
                    f"The AI sub-track asked {c['layer']}"
                    f"{'.' + c['field_path'] if c['field_path'] else ''} for: "
                    f"{c['requirement']}. That layer does not carry it, and "
                    f"{c['owning_layers']} DOES — every one of the "
                    f"{len(c['expected_tokens'])} expected token(s). So the "
                    f"fact was extracted and the expectation named the wrong "
                    f"layer; this is NOT a missing extraction and must not be "
                    f"repaired in an extractor. Either re-scope the "
                    f"expectation to the layer that owns the fact, or — if "
                    f"the layer contract really does put it in {c['layer']} "
                    f"— record that as a layer-contract defect in its own "
                    f"right.")
            findings.append({
                "severity": "REVIEW",
                "about": "track",
                "rule": f"{RULE_AI_MISSCOPED}::{c['id']}",
                "layer": c["layer"],
                "field_path": c["field_path"],
                "owning_layers": c["owning_layers"],
                "owning_layers_evidence": c["owning_layers_evidence"],
                "message": message,
                "expert_source": c.get("expert_source"),
                **({"split_branches": _split_branch_rows(c)}
                   if c.get("split") else {}),
            })
            continue

        if c.get("split"):
            # #2190. The parent names no layer, so the single form rendered
            # "expected None to carry". Name the conjunction the expectation
            # actually stated: every address, and that EVERY one of them has
            # to agree — which is what makes the `observed` below a verdict on
            # the whole row rather than on the branch it happens to quote.
            addressed = (
                f"a {len(c['sub_results'])}-branch SPLIT — every one of "
                f"{_split_addresses(c)} must agree —")
        else:
            addressed = (
                f"{c['layer']}"
                f"{'.' + c['field_path'] if c['field_path'] else ''}")
        findings.append({
            "severity": "REVIEW",
            "about": "design",
            "rule": f"{RULE_AI_UNMET}::{c['id']}",
            "layer": c["layer"],
            "field_path": c["field_path"],
            "message": (
                f"The AI sub-track, reading the same design input "
                f"independently, expected {addressed} to carry: "
                f"{c['requirement']}. The program track produced: "
                f"{c['observed']}."
                + (f" Grounds: {'; '.join(str(e) for e in c['evidence'])}."
                   if c["evidence"] else "")
                # #2150 — APPENDED, never woven in: the sentences above are
                # what every existing reader parses, and the ruling is a
                # separate statement that must be readable on its own.
                + (" " + carriage_sentence(c["carriage"])
                   if c.get("carriage") else "")),
            "expert_source": c.get("expert_source"),
            # The machine-readable half of the same sentence, so a consumer
            # never has to parse prose to learn the carriage verdict.
            "carriage": c.get("carriage"),
            **({"split_branches": _split_branch_rows(c)}
               if c.get("split") else {}),
        })

    if ai.get("pack_assembly_status") == "NOT_ASSEMBLED":
        cf = (ai.get("handoff") or {}).get("class_first") or {}
        findings.append({
            "severity": "REVIEW",
            # About the TRACK. The design is not what is in question: the
            # hand-off this track emitted carried no class-specific context,
            # and everything the agent writes from it is authored from the
            # design input alone.
            "about": "track",
            "rule": RULE_PACK_NOT_ASSEMBLED,
            "message": (
                f"The expert pack for registered ic_class "
                f"{cf.get('ic_class')!r} is NOT_ASSEMBLED: "
                f"{cf.get('not_assembled_reason')} Anything the AI half "
                f"returns for this run was authored from the design input "
                f"alone; the pack contributed no class knowledge to it. "
                f"Reported rather than left implicit — a null pack that reads "
                f"as an assembled one is credited as context that was never "
                f"there. Pack: {out_dir / 'ic_expert_agent_handoff.json'}."),
        })

    if ai["status"] == AI_SCHEMA_MISMATCH:
        keys = ai.get("answer_top_level_keys") or []
        findings.append({
            "severity": "REVIEW",
            # About the TRACK: the design is not what is in question. An answer
            # arrived and this consumer could not read it.
            "about": "track",
            "rule": RULE_AI_ANSWER_SCHEMA_MISMATCH,
            "message": (
                f"The AI sub-track's answer file EXISTS and parses, and is not "
                f"the shape this consumer reads: "
                f"{ai.get('answer_schema_why')}. It carries "
                f"{len(keys)} top-level key(s): {keys if keys else '(none)'}. "
                f"It is REFUSED rather than coerced to an empty list — an "
                f"answer flattened to zero expectations is recorded in the "
                f"identical words as an agent that had nothing to say, and one "
                f"of those two is a discarded answer. Answer file: "
                f"{ai.get('answer_path')}. Findings below come from the "
                f"deterministic sub-track ALONE — read them as a floor, not as "
                f"coverage."),
        })
    elif ai["status"] == AI_CONSUMED_EMPTY:
        findings.append({
            "severity": "REVIEW",
            # About the TRACK: a reading that named nothing is not a statement
            # about the design, it is a statement about how much was covered.
            "about": "track",
            "rule": RULE_AI_ANSWER_EMPTY,
            "message": (
                f"The AI sub-track answered and named NO expectations "
                f"({ai['status']}): {ai['reason']} This is a real zero and it "
                f"is reported rather than left silent, because an empty "
                f"reading and a full one produce the same zero findings and "
                f"only one of them is coverage."),
        })
    elif ai["status"] not in AI_READ_STATES:
        findings.append({
            "severity": "REVIEW",
            "about": "track",
            "rule": RULE_AI_SKIPPED,
            "message": (
                f"The AI sub-track of the Phase-1 expert track did not deliver "
                f"a reading ({ai['status']}): {ai['reason']} Findings below "
                f"come from the deterministic sub-track ALONE — read them as a "
                f"floor, not as coverage."),
        })

    applicable = [r for r in rules if r["applicable"]]
    # THE DENOMINATOR — how many expectations this run actually DECIDED, from
    # both halves. The verdict is taken from it rather than from "did any rule
    # apply", because those are different questions: a rule can apply and
    # yield no expectation, and the AI half can answer and yield none either.
    # A run that decided nothing has measured nothing, and this repo's own
    # `gate_zero_denominator_refuses_check` exists to stop that from exiting 0.
    det_examined = sum(len(r["expectations"]) for r in applicable)
    examined = det_examined + len(converged)
    # EXECUTION outranks findings. Creating a handoff, refusing an answer,
    # reading an empty answer, or failing to parse one are four different
    # facts, but none is an expert reading with a non-zero denominator. Before
    # #1973 the runner credited all of them because it accepted rc 2 and only
    # checked that this report existed.
    # R-0915-126-D1. THE TRACK IS COMPLETE WHEN IT HAS DECIDED ITS
    # EXPECTATIONS — from EITHER half — and AWAITING now means only "could not
    # read its own subject".
    #
    # What stood here required `AI_CONSUMED` unconditionally, so in a headless,
    # program-only front-door run — where nobody invokes the expert subagent —
    # `execution_complete` was False on every run, the verdict was INCOMPLETE
    # and the exit code was AWAITING (4) forever. MEASURED on spm run13 AND
    # run8 (8HD-4, `reports/audit/phase1/expert_parse_track.json`):
    #
    #     verdict INCOMPLETE · returncode 4 · ai_subtrack HANDOFF_EMITTED
    #     execution.complete False · observed_ai_consumed 0
    #
    # and the pack it emitted holds only the handoff INPUTS
    # (authoring_schema.json, design_input.txt, ic_expert_agent_handoff.json,
    # ic_expert_db.md, lessons.md) — `l_doc_expectations.json`, the file the
    # rc==0 branch of `check_report` hashes, DOES NOT EXIST, because it is the
    # thing the AI is being asked to author. "Nobody invoked the subagent" is a
    # fact about the RUNNER'S OPERATOR and it must not be a verdict about the
    # design's Phase-1 parse.
    #
    # The DETERMINISTIC sub-track already decides expectations on its own —
    # `det_examined` above counts them — and its findings are already reported.
    # When it has decided at least one, this track HAS measured something and
    # is DECIDED. The AI half's absence remains recorded, as coverage, by
    # RULE_AI_SKIPPED above; it is no longer an execution failure.
    #
    # The two derivations are KEPT DISTINCT (the same rule as R-0915-125(a)):
    # an AI answer is credited against `answer_sha256` over the AI's own
    # `l_doc_expectations.json`, which stays the AI's file and is never written
    # by the program; a program-derived completion carries its OWN
    # `program_expectations_sha256` over the deterministic expectations. A
    # reader can always tell which answered.
    ai_complete = ai["status"] == AI_CONSUMED and len(converged) > 0
    # NARROWLY: only when NOTHING WAS EVER ANSWERED. `AI_AWAITING_STATES` is
    # exactly the hand-off-emitted case — nobody invoked the subagent — and it
    # is the ONLY one this may stand in for.
    #
    # It must NOT cover a refusal. When an answer EXISTS and this consumer
    # refused it (AI_SCHEMA_MISMATCH, an unparseable answer, an empty reading),
    # half of a dual track declined to read something real, and no top-line
    # word on that run may imply it was examined — crediting the deterministic
    # half there would fix the label and not the lie. That distinction is held
    # by `test_the_refusal_outranks_a_completely_clean_deterministic_half`,
    # which caught this exact over-reach when the condition here was merely
    # `not ai_complete`.
    program_complete = (not ai_complete
                        and ai["status"] in AI_AWAITING_STATES
                        and det_examined > 0)
    execution_complete = ai_complete or program_complete
    derivation = ("ai" if ai_complete
                  else "program" if program_complete else None)
    program_sha = _program_expectations_digest(applicable) if program_complete \
        else None
    if not execution_complete:
        # AWAITING vs DEFECT — see AI_AWAITING_STATES. The verdict WORD is
        # INCOMPLETE either way, because neither is coverage; what differs is
        # whether re-running is the action that closes it.
        verdict = "INCOMPLETE"
        awaiting = ai["status"] in AI_AWAITING_STATES
        rc = AWAITING_EXIT_CODE if awaiting else 1
    elif not examined:
        # Defensive: AI_CONSUMED currently implies at least one converged
        # expectation. Keep the zero-denominator refusal local so a future
        # status change cannot manufacture a pass.
        verdict, rc = "INCOMPLETE", 1
        awaiting = False
    elif findings:
        verdict, rc = "FINDINGS", 0
        awaiting = False
    else:
        verdict, rc = "PASS", 0
        awaiting = False

    if execution_complete:
        disposition = DISPOSITION_CREDITED
    elif awaiting:
        disposition = DISPOSITION_AWAITING
    else:
        disposition = DISPOSITION_DEFECT

    sidecar = _pl.phase1_ai_deep_review_patches_file(project)
    return {
        "verdict": verdict,
        "rc": rc,
        "blocking": False,
        "enforcement": "advisory (findings) / mandatory (execution)",
        "execution": {
            "complete": execution_complete,
            # WHICH of the three, stated. A reader who has only `complete:
            # false` cannot tell "nobody has answered yet" from "the answer is
            # unreadable", and those two need different people.
            "disposition": disposition,
            "required_ai_status": AI_CONSUMED,
            "required_ai_consumed_min": 1,
            "observed_ai_status": ai["status"],
            "observed_ai_consumed": len(converged),
            # WHICH HALF decided this track: "ai", "program", or null when
            # neither did. Published so an AI answer and a program-derived one
            # are never indistinguishable in the record.
            "derivation": derivation,
            "deterministic_examined": det_examined,
            # The program-derived path's OWN digest. `l_doc_expectations.json`
            # stays the AI's file and is never written here, so a program
            # completion is verified against this instead.
            "program_expectations_sha256": program_sha,
        },
        # WHAT IT IS WAITING FOR, in the words of the action that ends the
        # wait — never a bare state name. Null when nothing is being waited
        # for, so "waiting" and "not waiting" are two readable states rather
        # than a field a reader has to interpret.
        "awaiting": ({
            "what": "the Phase-1 IC-Expert answer (second pass of the "
                    "hand-off protocol)",
            "ai_subtrack_status": ai["status"],
            "action": (f"invoke subagent {_pack.SUBAGENT_TYPE} on "
                       f"{out_dir / 'ic_expert_agent_handoff.json'}, then "
                       f"re-run this track to consume its answer"),
            "credited": False,
            "exit_code": AWAITING_EXIT_CODE,
        } if awaiting else None),
        # WHICH Phase-1 root this run judged (#2150 F11). Every artefact the
        # expert track produces is an answer ABOUT one root, and until now
        # none of them said which — so a classification, a decision table and
        # a repaired corpus computed over three different roots read as three
        # answers to one question. Membership AND content, so a later reader
        # can tell a root that GREW from a root that CHANGED.
        "phase1_root": phase1_root_identity(project),
        # WHETHER the author was handed the declaration (#2150 F5). A run
        # whose pack could not carry one produced expectations authored
        # against two prose words, and a reader has to be able to see that
        # rather than infer it from the field_paths that came back.
        "authoring_schema_status": ai.get("authoring_schema_status",
                                          "NOT_EVALUATED"),
        "retrieved_expert_classes": retrieved_classes(prompt, ic_class=ic_class),
        # #2164. WHETHER that list is a measurement. An empty list from an
        # empty query and an empty list from a query that found nothing are the
        # same JSON and opposite facts; the status is what separates them, and
        # the reason names the formats this reader could not open.
        "retrieval_input": {
            **readability,
            "status": input_report["status"],
            "files_read": len(input_report["files_read"]),
            "files_skipped": input_report["files_skipped"],
            "truncated": input_report["truncated"],
        },
        # WHICH classes the expert DB was allowed to offer, and why. Without
        # this a reader sees a list of db_classes with no way to tell whether
        # the design's own class chose them or a phrase collided.
        "class_first": ai.get("class_first"),
        "pack_assembly_status": ai.get("pack_assembly_status", "NOT_EVALUATED"),
        # A PASS must say how much it looked at. This is that number, split by
        # half so a reader can see WHICH half contributed it — a total of 4
        # means something different when the AI half supplied 0 of it.
        "examined_expectations": examined,
        "denominator": {
            "deterministic": det_examined,
            "ai": len(converged),
            "total": examined,
            "ai_status": ai["status"],
        },
        "deterministic_subtrack": rules,
        "ai_subtrack": ai,
        # The convergence LEDGER. Agreements are counted, not just
        # disagreements, because "the second track always agrees" and "the
        # second track works" are different states that a disagreement-only
        # report renders identical — and the first one is worth knowing about.
        "ai_convergence": {
            "consumed": len(converged),
            "agreed": len([c for c in converged if c["usable"] and c["met"]]),
            "disagreed": len([c for c in converged
                              if c["usable"] and not c["met"]]),
            # UNDECIDABLE excludes a WITHDRAWN row. Both are "not decided", and
            # they are not the same event: one is an answer this comparator
            # could not read, the other is a decision its author took and
            # stated. Under one column a reader cannot tell them apart, which
            # is the two-zeros conflation this whole track exists to prevent.
            "undecidable": len([c for c in converged
                                if not c["usable"] and not c["withdrawn_reason"]]),
            # #2127 — two SUB-populations of `disagreed`, recorded so they can
            # be counted rather than read out of finding prose. Neither moves
            # `agreed`/`disagreed`: `met` is decided exactly as before.
            #   misscoped              the addressed layer misses it and
            #                          another layer the program track wrote
            #                          carries every expected token
            #   field_path_undeclared  the expectation named a path its layer
            #                          does not declare (counted over every
            #                          expectation whose layer was readable,
            #                          met or not)
            "misscoped": len([c for c in converged
                              if c["usable"] and not c["met"]
                              and c["owning_layers"]]),
            # #2191 — rows whose ownership question was REFUSED for want of a
            # token that can tell one layer from another. Counted separately
            # from `misscoped` and from the design column both, because it is
            # neither: a row here is a fact about the EXPECTATION. A count is
            # the only way a reader sees the population without opening each
            # finding, and before this landing every one of these rows was
            # published as a confident re-scope.
            "ownership_undecidable": len(
                [c for c in converged
                 if c["usable"] and not c["met"]
                 and c["owning_layers_status"] == "NO_DISCRIMINATING_TOKEN"]),
            "field_path_undeclared": len(
                [c for c in converged
                 if c["field_path_status"] == "UNDECLARED"]),
            # How many readings could NOT be scoped to the field the
            # expectation named. Every one of them is a weaker claim than the
            # report's wording suggests, and a count is the only way a reader
            # sees that without opening each finding.
            "unscoped_readings": len(
                [c for c in converged if c["scope"] == "whole_layer"]),
            # Withdrawn WITH a reason. A reasonless withdrawal is refused and
            # is therefore NOT counted here — it is still decided, and counting
            # it would make a refused withdrawal look like an honoured one.
            "withdrawn": len([c for c in converged if c["withdrawn_reason"]]),
        },
        # #2150 item 6 — whether a decision table was present, and whether it
        # was applied. An absent key would make "there was no table" and "the
        # table was refused" the same reading.
        "decision_table": decision_table,
        "findings": findings,
        # #312's own rule turned on this landing's scope decision. The
        # deterministic rule below has a real payload and REPORTS every
        # divergence it finds, but nothing in Phase 1 STOPS on it. A deferral
        # nobody can see is the same defect this track exists to name, so the
        # deferral is a recorded fact rather than an absence a reader has to
        # infer from a passing run.
        "deferred_enforcement": {
            "subject": "nvm_program_supply — the programmable-NVM programming "
                       "supply convention",
            "blocking_gate_landed": False,
            "reason": (
                "the findings are advisory. Promoting this convention to a "
                "blocking Phase-1 gate is a separate enforcement decision: its "
                "blocking behaviour has never been observed on a real design "
                "(every design in the fleet corpus assesses as "
                "not-applicable), and a stop that has only ever been exercised "
                "against synthesised fixtures is an unmeasured stop. The "
                "assessment library it would call is here and tested; what is "
                "deferred is the automatic stop, not the knowledge."),
            "issue": "vibe-ic#312",
        },
        "track_health": {
            # A visible fact, not an inference: nothing in the repo writes this
            # file, so the three gates that read it measure a haystack no
            # producer ever fills. See the module docstring on why THIS track
            # must not be that producer.
            "ai_patch_sidecar_path": str(sidecar),
            "ai_patch_sidecar_present": sidecar.is_file(),
            "input_text_chars": len(prompt),
            # A zero here means one of five things and the status says which.
            "input_text_status": input_report["status"],
        },
    }


def check_report(project: Path) -> int:
    """D1 reads Phase 1's evidence without consuming or rewriting its subject.

    Execution is mandatory; findings remain advisory. Missing, malformed or
    stale evidence refuses credit. This path never calls evaluate or emits a
    pack. The producer invocation and answer/root digests identify the reading
    being checked, rather than crediting an audit-time second pass (#2206).
    """
    target = _pl.report_path(project, "phase1/expert_parse_track.json")
    try:
        rep = json.loads(target.read_text())
        if not isinstance(rep, dict) or rep.get("program") != PROGRAM:
            raise ValueError("missing expert-track producer record")
        producer = rep.get("producer")
        if not isinstance(producer, dict) or not producer.get("invocation_id"):
            raise ValueError("producer invocation is not recorded; rerun Phase 1")
        rc = producer.get("returncode")
        if type(rc) is not int or rc not in (0, 1, AWAITING_EXIT_CODE):
            raise ValueError("producer return code is missing or invalid")
        root = rep.get("phase1_root")
        current = phase1_root_identity(project)
        if (not isinstance(root, dict) or current.get("status") != "OK"
                or root.get("digest") != current.get("digest")):
            raise ValueError("Phase-1 layer set changed since the producer reading")
        ai = rep.get("ai_subtrack")
        execution = rep.get("execution")
        if not isinstance(ai, dict) or not isinstance(execution, dict):
            raise ValueError("expert execution record is malformed")
        if rc == 0:
            # R-0915-126-D1: a completed track has DECIDED its expectations,
            # and TWO derivations can do that. They are checked SEPARATELY and
            # against DIFFERENT evidence, so a program-derived reading can
            # never be mistaken for an AI one.
            if (rep.get("verdict") not in ("PASS", "FINDINGS")
                    or execution.get("complete") is not True):
                raise ValueError("zero return code contradicts expert execution")
            # AN ABSENT `derivation` IS THE AI DERIVATION IT ALWAYS WAS.
            # Before R-0915-126-D1 the ONLY route to rc 0 was AI_CONSUMED with
            # a matching `answer_sha256`, so a report written by an older
            # producer — or staged by a fixture that predates this field — is
            # an AI-derived reading, not an unnameable one. Reading its absence
            # as "stale" refused reports that were never wrong: MEASURED on the
            # FIX3I arms, three synthetic intact trees
            # (test_flow_compliance_check_gate x2,
            # test_issue1446_incomplete_in_scope_is_not_green) went
            # "INCOMPLETE: report unavailable or stale: zero return code ..."
            # at Step D1 and cascaded P0/1 to NOT_MEASURED(upstream_failed).
            # Those fixtures stage `ai_subtrack.status = AI_CONSUMED` with a
            # real `answer_sha256` and an `execution` block carrying no
            # `derivation` — a legitimate AI completion, which is why they are
            # NOT re-pinned here.
            #
            # ONLY A DERIVATION THAT IS PRESENT AND UNRECOGNISED IS REFUSED: a
            # report that NAMES a derivation this checker does not know is
            # claiming something it cannot support, and that is a different
            # fact from saying nothing.
            derivation = execution.get("derivation")
            if derivation is None:
                derivation = "ai"
            if derivation == "ai":
                if (ai.get("status") != AI_CONSUMED
                        or type(execution.get("observed_ai_consumed")) is not int
                        or execution["observed_ai_consumed"] < 1):
                    raise ValueError(
                        "zero return code contradicts expert execution")
                # `l_doc_expectations.json` is THE AI'S FILE. The program never
                # writes it, so it is read here only for an AI-derived claim.
                answer = (target.parent / "expert_parse_track_pack"
                          / "l_doc_expectations.json")
                if ai.get("answer_sha256") != hashlib.sha256(
                        answer.read_bytes()).hexdigest():
                    raise ValueError(
                        "current expert answer has no matching producer reading")
            elif derivation == "program":
                # The program-derived path answers for ITSELF, against its own
                # digest over the deterministic expectations it decided.
                digest = execution.get("program_expectations_sha256")
                if not isinstance(digest, str) or len(digest) != 64:
                    raise ValueError(
                        "a program-derived reading must record its own "
                        "program_expectations_sha256")
                if type(execution.get("deterministic_examined")) is not int \
                        or execution["deterministic_examined"] < 1:
                    raise ValueError(
                        "a program-derived reading must have decided at least "
                        "one deterministic expectation")
            else:
                raise ValueError(
                    f"zero return code with an unrecognised execution "
                    f"derivation {derivation!r}")
        elif rc == AWAITING_EXIT_CODE and (
                rep.get("verdict") != "INCOMPLETE"
                or ai.get("status") != AI_HANDOFF_EMITTED):
            # R-0915-126-D1: AWAITING now means the producer could not read its
            # own subject — it is no longer reachable merely because nobody
            # invoked the subagent.
            raise ValueError("awaiting return code contradicts expert execution")
    except (OSError, ValueError, TypeError) as exc:
        print(f"INCOMPLETE: {PROGRAM} report unavailable or stale: {exc}")
        return 1
    prefix = "INCOMPLETE: " if rc else ""
    print(f"{prefix}{PROGRAM}: {rep.get('verdict')} — read-only report check; "
          f"producer={producer.get('invoked_by')} "
          f"invocation={producer['invocation_id']} rc={rc}; report: {target}")
    # SAY THE WORD FOR THE STATE THIS BRANCH JUST PROVED. The `elif` above
    # accepts `rc == AWAITING_EXIT_CODE` only together with verdict INCOMPLETE
    # and `ai.status == AI_HANDOFF_EMITTED` -- the awaiting triple, established
    # right here -- and then this printer said only "INCOMPLETE". The consumer
    # distinguishes the two tiers by an `AWAITING_AGENT_PASS` token that must
    # START a line, and the token appeared nowhere in this file, so every step
    # whose gate is this clause was read as `partial_population`: "the gate
    # reports its input was applicable and was NOT examined". That is a false
    # sentence about a run awaiting a two-pass hand-off whose population
    # answered in full.
    #
    # MEASURED (run21, `--stage-id stage_phase1 --strict` rc=1): step D1 is the
    # only blocker, and all 33 of its gates returned a decisive verdict while
    # this report says `execution.disposition = "AWAITING"`,
    # `observed_ai_status = "HANDOFF_EMITTED"`, `observed_ai_consumed = 0`.
    #
    # LAST LINE, AT COLUMN 0, AND BOTH OF THOSE ARE LOAD-BEARING. The consumer's
    # snippet keeps a 300-char HEAD and a 300-char TAIL, so the verdict line
    # above survives in the head and this one survives in the tail however long
    # the project path is; and the token is only read when it starts a line.
    if rc == AWAITING_EXIT_CODE and str(
            (rep.get("execution") or {}).get("disposition") or "") == "AWAITING":
        print(f"AWAITING_AGENT_PASS: {ai.get('status')} — "
              f"{execution.get('observed_ai_consumed')} of "
              f"{execution.get('required_ai_consumed_min')} required agent "
              f"answer(s) consumed; the hand-off is written and pass two is not "
              f"a program's to make")
    return rc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    ap.add_argument("--check-report", action="store_true",
                    help="read the Phase-1 producer report without running the track")
    ap.add_argument("--invoked-by", default="direct",
                    help="name the invoking phase runner in the producer receipt")
    ap.add_argument("--input-readability", action="store_true",
                    help="print ONLY whether this project's design input can "
                         "be read, and what was skipped — the census a "
                         "corpus-wide loop needs (#2164). Exit 0 either way: "
                         "an unreadable input is a fact to report, not a run "
                         "that failed.")
    args = ap.parse_args(argv)
    if not args.project_dir.is_dir():
        print(f"ERROR: not a directory: {args.project_dir}", file=sys.stderr)
        return 1

    project = args.project_dir.resolve()
    if args.check_report:
        return check_report(project)
    if args.input_readability:
        rep = input_text_report(project)
        disp = input_readability_disposition(rep)
        print(f"{disp['retrieval_input']}\t{rep['status']}\t"
              f"chars={rep['chars']}\tread={len(rep['files_read'])}\t"
              f"skipped={len(rep['files_skipped'])}\t"
              f"unsupported={json.dumps(rep['unsupported_suffixes'], sort_keys=True)}"
              f"\t{project}")
        if disp["retrieval_input"] == "NOT_MEASURED":
            print(f"  reason: {disp['reason']}")
        return 0
    try:
        rep = evaluate(project)
    except Exception as exc:  # noqa: BLE001
        # The track failing is itself reportable. Exit 1: a second track that
        # cannot run must say so loudly, never look like a clean run.
        print(f"{PROGRAM}: ERROR — the expert track did not complete: {exc}",
              file=sys.stderr)
        return 1

    rc = rep.pop("rc")
    rep = {"program": PROGRAM, "version": VERSION, **rep}
    import uuid
    from datetime import datetime, timezone
    rep["producer"] = {"invocation_id": str(uuid.uuid4()),
                       "invoked_by": args.invoked_by,
                       "program": PROGRAM, "returncode": rc,
                       "completed_at": datetime.now(timezone.utc).isoformat()}
    out = json.dumps(rep, indent=2, ensure_ascii=False)

    target = Path(args.json) if args.json else \
        _pl.report_path(project, "phase1/expert_parse_track.json")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(out)
    except OSError as exc:
        print(f"{PROGRAM}: ERROR — report not written to {target}: {exc}",
              file=sys.stderr)
        return 1

    if rep["verdict"] == "INCOMPLETE":
        # The `INCOMPLETE:` sentinel is the house mechanism (#599) for "not
        # audited, and someone must come back". Name the exact state: a handoff
        # is actionable, a schema mismatch is a refused answer, and an empty
        # answer is a measured zero; none is completed execution.
        ai = rep["ai_subtrack"]
        print(f"INCOMPLETE: {PROGRAM} — the AI sub-track did not deliver a "
              f"non-empty schema-readable review ({ai['status']}): "
              f"{ai['reason']} The expert answer was NOT credited as consumed; "
              f"the deterministic findings are a floor, not coverage")
        # The state a reader can ACT on is printed as its own line. "Awaiting"
        # with no named action is the same silence as a bare INCOMPLETE.
        aw = rep.get("awaiting")
        if aw:
            print(f"  awaiting: {aw['what']} — {aw['action']} "
                  f"(exit {aw['exit_code']}: a stated wait, not a failed run; "
                  f"not credited)")
    den = rep["denominator"]
    print(f"{PROGRAM}: {rep['verdict']} — examined "
          f"{den['total']} expectation(s) "
          f"({den['deterministic']} deterministic + {den['ai']} from the AI "
          f"sub-track); {len(rep['findings'])} finding(s); AI sub-track "
          f"{rep['ai_subtrack']['status']}")
    for f in rep["findings"]:
        print(f"  [{f['severity']}] {f['rule']}: {f['message']}")
    print(f"  report: {target}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
