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
    never absent, and never mistaken for "nothing to report".
    This state replaced `SKIPPED-CONDITION`, which named the wrong fact: the
    obstacle was never a missing LLM, it was that nobody had invoked the agent
    — and the old wording pointed a reader at a host capability instead of at
    the one action that advances the track.
  * THE TRACK ITSELF FAILS — exit 1. The report is a MANDATORY output: the
    runner treats a missing or unparseable report as a Phase-1 failure. So the
    findings are advisory, but running is not optional.
  * NOTHING APPLIES — exit 2 (VACUOUS_PASS) with the reason stated per rule.
    A vacuous pass is a stated verdict, not silence.

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
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import _path_layout as _pl  # noqa: E402
import nvm_program_supply_intent as _nps  # noqa: E402

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


def input_text(project: Path) -> str:
    """Concatenated design-input prose — the retrieval query and the AI
    sub-track's prompt. INPUT only (§4.05)."""
    parts: List[str] = []
    total = 0
    root = project / "input"
    if root.is_dir():
        for p in sorted(root.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in _INPUT_TEXT_EXTS:
                continue
            try:
                rel = p.relative_to(root)
            except ValueError:
                continue
            if _nps._is_oracle_parts(rel.parts):
                continue
            try:
                t = p.read_text(errors="replace")
            except OSError:
                continue
            parts.append(t)
            total += len(t)
            if total >= _INPUT_TEXT_CAP:
                break
    return "\n".join(parts)[:_INPUT_TEXT_CAP]


def retrieved_classes(prompt: str, k: int = 5) -> List[Dict[str, Any]]:
    """What the expert DB surfaces for THIS design — recorded so a reviewer can
    see which knowledge the track had in hand, including when it had none."""
    if not prompt.strip():
        return []
    try:
        import ic_expert_db_query as _db
        return [{"ic_class": h.get("ic_class"),
                 "score": round(float(h.get("score", 0) or 0), 2)}
                for h in (_db.query(prompt, k=k) or []) if isinstance(h, dict)]
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


def converge_ai_expectation(project: Path, exp: Any) -> Dict[str, Any]:
    """Decide ONE AI expectation against what the program track actually wrote.

    Returns the expectation enriched with `met` / `observed` / `usable`. Any
    `met` the answer carried is DISCARDED before the decision — see the module
    docstring on why the AI half must not score itself.
    """
    base: Dict[str, Any] = {
        "id": None, "layer": None, "field_path": None, "requirement": None,
        "evidence": [], "expected_tokens": [],
        "usable": False, "met": False, "observed": "",
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
    path = resolve_layer_file(project, base["layer"])
    if path is None:
        base["observed"] = (f"the program track produced no "
                            f"{base['layer']} layer at all")
        return base
    try:
        blob = json.loads(path.read_text(errors="replace"))
    except (OSError, ValueError) as exc:
        base["observed"] = (f"{base['layer']} exists but does not parse "
                            f"({exc.__class__.__name__}); unreadable content "
                            f"is not content")
        return base

    hay = _layer_haystack(blob)
    missing = [t for t in base["expected_tokens"] if not phrase_present(t, hay)]
    base["met"] = not missing
    base["missing_tokens"] = missing
    base["observed"] = (
        f"{base['layer']} carries all of {base['expected_tokens']}"
        if not missing else
        f"{base['layer']} does not carry {missing} "
        f"(checked {len(base['expected_tokens'])} expected token(s))")
    return base


# ── the AI sub-track ────────────────────────────────────────────────────────

def ai_subtrack(project: Path, prompt: str, out_dir: Path) -> Dict[str, Any]:
    """Hand the open-ended reading to the IC Expert Agent.

    Uses `ic_expert_backup_pack` — the assembler this doctrine already built
    for this hand-off (expert-skills digest as one author, expert-DB digest as
    an independent second, then converge). Reused rather than reimplemented;
    it is tested and it is the doctrine's own mechanism.

    A program cannot spawn a subagent, so this emits the pack + the hand-off
    descriptor that names exactly which subagent to invoke, and consumes the
    agent's answer if a previous invocation left one. Every outcome is a
    STATED status:

        HANDOFF_EMITTED    pack ready, agent has not answered yet
        CONSUMED           an agent answer was read back
        ERROR              assembly failed, or the answer does not parse

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
        handoff = _pack.assemble(
            prompt=prompt, iface=None, target=None,
            expert_skills=[], verify_gates=[PROGRAM],
            out_dir=out_dir, k=5,
            output_target="l_doc_expectations.json")
        status["handoff"] = handoff
    except Exception as exc:  # noqa: BLE001
        status.update(status="ERROR", reason=f"pack assembly failed: {exc}")
        return status

    answer = out_dir / "l_doc_expectations.json"
    if answer.is_file():
        try:
            data = json.loads(answer.read_text(errors="replace"))
        except (OSError, ValueError) as exc:
            status.update(status="ERROR",
                          reason=f"agent answer does not parse: {exc}")
            return status
        exps = data.get("expectations")
        status.update(
            status="CONSUMED",
            reason=f"read {len(exps) if isinstance(exps, list) else 0} "
                   f"expectation(s) from a prior agent invocation",
            expectations=exps if isinstance(exps, list) else [])
        return status

    status.update(
        status="HANDOFF_EMITTED",
        reason=(f"pack written to {out_dir}; invoke subagent "
                f"{_pack.SUBAGENT_TYPE} on "
                f"{out_dir / 'ic_expert_agent_handoff.json'} and re-run to "
                f"consume its answer"))
    return status


# ── evaluate ────────────────────────────────────────────────────────────────

def evaluate(project: Path) -> Dict[str, Any]:
    prompt = input_text(project)
    out_dir = _pl.report_path(project, "phase1/expert_parse_track").parent \
        / "expert_parse_track_pack"

    rules = [fn(project) for fn in DETERMINISTIC_RULES]
    ai = ai_subtrack(project, prompt, out_dir)

    findings: List[Dict[str, Any]] = []
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
        if c["met"]:
            continue
        findings.append({
            "severity": "REVIEW",
            "about": "design",
            "rule": f"{RULE_AI_UNMET}::{c['id']}",
            "layer": c["layer"],
            "field_path": c["field_path"],
            "message": (
                f"The AI sub-track, reading the same design input "
                f"independently, expected {c['layer']}"
                f"{'.' + c['field_path'] if c['field_path'] else ''} to carry: "
                f"{c['requirement']}. The program track produced: "
                f"{c['observed']}."
                + (f" Grounds: {'; '.join(str(e) for e in c['evidence'])}."
                   if c["evidence"] else "")),
            "expert_source": c.get("expert_source"),
        })

    if ai["status"] != "CONSUMED":
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
    if not applicable and ai["status"] != "CONSUMED":
        verdict, rc = "VACUOUS_PASS", 2
    elif findings:
        verdict, rc = "FINDINGS", 0
    else:
        verdict, rc = "PASS", 0

    sidecar = _pl.phase1_ai_deep_review_patches_file(project)
    return {
        "verdict": verdict,
        "rc": rc,
        "blocking": False,
        "enforcement": "advisory (findings) / mandatory (execution)",
        "retrieved_expert_classes": retrieved_classes(prompt),
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
            "undecidable": len([c for c in converged if not c["usable"]]),
        },
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
        },
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    if not args.project_dir.is_dir():
        print(f"ERROR: not a directory: {args.project_dir}", file=sys.stderr)
        return 1

    project = args.project_dir.resolve()
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

    if rep["verdict"] == "VACUOUS_PASS":
        print(f"VACUOUS_PASS: {PROGRAM} — no expert expectation applies to "
              f"this design and the AI sub-track is unavailable")
    print(f"{PROGRAM}: {rep['verdict']} "
          f"({len(rep['findings'])} finding(s); AI sub-track "
          f"{rep['ai_subtrack']['status']})")
    for f in rep["findings"]:
        print(f"  [{f['severity']}] {f['rule']}: {f['message']}")
    print(f"  report: {target}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
