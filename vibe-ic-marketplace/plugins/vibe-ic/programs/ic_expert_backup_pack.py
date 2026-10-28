#!/usr/bin/env python3
r"""ic_expert_backup_pack.py — assemble the IC-Expert-Agent AI-backup context pack.

GENERAL CORE (benchmark-AGNOSTIC). When a deterministic track cannot author a
body (the common case — a non-standard design), the plugin's answer is NOT a
generic LLM: it is to let the AI act AS the **IC Expert Agent**, USING the two
expert assets the agent owns —

  * expert-SKILLS — the ACTIVE `### Skill:` sections distilled in
    `agents/ic-expert-agent.md` (rendered to `lessons.md` by
    `_lesson_digest.render_lesson_digest`);
  * expert-DB   — the design-class craft in `agents/ic_expert_db/ic_expert_db.json`,
    retrieved for THIS prompt by `ic_expert_db_query.query` and rendered to
    `ic_expert_db.md` by `_lesson_digest.render_ic_expert_db_digest`.

A MEASURED A/B lesson (see `_lesson_digest.render_lesson_digest` note: folding the
DB into the one skills digest LOWERED single-shot recovery 38→31; the two as
INDEPENDENT authors reached 51) makes this a **DUAL-TRACK** hand-off, not one
blob:

  * Track 1 — general-blind author: prompt + interface contract + `lessons.md`.
  * Track 2 — DB-informed author:  prompt + interface contract + `ic_expert_db.md`.
  * Converge — a comparator diffs the two bodies; disagreement is root-caused and
    reconciled (the program-first + AI-backup dual-track convergence doctrine).

This module does the DETERMINISTIC assembly (retrieve + render + write the
contract + emit the hand-off descriptor). The actual LLM authoring is performed
by invoking the `vibe-ic:ic-expert-agent` subagent on the emitted pack — the
hand-off JSON names exactly that invocation, so an orchestrator (a benchmark
driver, `phase1-orchestrate`, or a human) runs it identically. Reads ONLY the
supplied prompt + interface — never any oracle/harness.

CLASS-FIRST ASSEMBLY, AND A PACK THAT REFUSES TO CLAIM IT IS ASSEMBLED (#2094).
A pack assembled for a design whose REGISTERED `ic_class` the expert DB PROFILES
is `ic_class`-driven end to end:

  * its `db_classes` come from the profile — the class SELECTS, the phrase only
    RANKS within the selection (`ic_expert_db_query.query(..., ic_class=...)`);
  * its `interface_contract` is the profile's `integration_contract` — the field
    set this class's generated integration/constraints layers must carry;
  * its `target_module` is recovered from the design INPUT when the caller has
    none to give;
  * and if, after all that, it still carries no target module and no contract,
    it is stamped `assembly_status: NOT_ASSEMBLED` and says why.

That last point is the actual defect this closes. MEASURED on a crypto
accelerator: the pack carried `target_module: null`, `interface_contract: null`,
`expert_skills: []` and five db_classes none of which was crypto — and it was
handed on as a pack, so a 46-expectation review was recorded as having had an
expert pack in hand when the pack contained nothing about the design's class. A
null pack that READS AS ASSEMBLED is worse than no pack: it launders an empty
context into a credited one. So the status is computed and stated.

An `ic_class` the DB does not profile (including the classifier's terminal
CATCH-ALL, whose registry entry says in its own words that designs landing there
"are UNCLASSIFIED, not classified") is left exactly as before: no confinement,
no contract substitution, no refusal, and a byte-identical descriptor. Refusing
a pack for a class nobody has profiled would score the classifier's uncertainty
as the design's deficiency. Profiling the remaining registered classes moves
every design's pack at once and belongs in its own change, on its own corpus
sweep — the gap is DECLARED in the DB, class by class, not left implicit.
"""
from __future__ import annotations

import json
import hashlib
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

SUBAGENT_TYPE = "vibe-ic:ic-expert-agent"


def iface_to_contract_v(iface: List[Dict[str, Any]], target: str) -> str:
    """Header-only `module <target> ( … ); endmodule` from a recovered interface
    — the CONTRACT the AI-backup body must satisfy. Ports only, no behaviour."""
    body = []
    for p in iface or []:
        d = p.get("dir") or "input"
        w = p.get("width")
        rng = f" [{int(w) - 1}:0]" if isinstance(w, int) and w and w > 1 else ""
        body.append(f"  {d}{rng} {p.get('name')}")
    return f"module {target} (\n" + ",\n".join(body) + "\n);\nendmodule\n"


# The design INPUT's own way of naming its top module. THREE GENERAL spec
# conventions, no design/vendor literal: an explicit "top-level module: `x`",
# a prose sentence that names "the module `x`" / "the module **`x`**", and the
# same statement written the other way round — "`x` is the top-level module",
# "`x` provides two top module options". Used ONLY to fill a `target` the caller
# does not have; a caller-supplied target always wins.
#
# ORDER IS THE CONTRACT (#2110). The list is tried in order and the first
# undenied match wins, so a convention APPENDED here can only answer for an
# input on which every earlier one already answered nothing. Measured on the
# 71 corpus projects carrying an `input/` tree: adding the third convention
# moves EXACTLY ONE of them (a processor-core SoC whose spec states the name
# before the phrase, `None` -> the name), and leaves the other 70 — including
# every design that already recovered a name — byte-identical. Prepending it
# instead would have re-answered designs that were already right.
_TARGET_RES = [
    re.compile(r"\btop[-_ ]?(?:level[-_ ]?)?module\b[^\n`]{0,20}[`*]+([A-Za-z_]\w*)[`*]+",
               re.I),
    re.compile(r"\bmodule\b[^\n`]{0,12}[`*]*`([A-Za-z_]\w*)`", re.I),
    # NAME BEFORE PHRASE. The gap excludes the newline, the quoting characters
    # and the table pipe: a spec states this in prose, and a gap allowed to
    # cross a `|` would bind a name from one table cell to a phrase in the
    # next one, which is not a statement anybody wrote.
    re.compile(r"[`*]+([A-Za-z_]\w*)[`*]+[^\n`*|]{0,24}?"
               r"\btop[-_ ]?(?:level[-_ ]?)?module\b", re.I),
]


def recover_target_module(prompt: str) -> Optional[str]:
    """The top-module name the design INPUT states, or None. Input-only.

    POLARITY-AWARE (#712's one vocabulary, `_prose_polarity`). A spec sentence
    is as likely to RETRACT a module name as to declare one — "the module `x`
    is not the top level here", "`x` is no longer the wrapper" — and an
    extractor that takes the first match writes the denied name into the pack's
    `target_module`, where it then reads as the design's own declaration. So
    each candidate is checked against the SENTENCE it sits in, and a denied one
    is skipped rather than returned. Line-wrapped prose gets `LINE_END_BREAKS`:
    a spec written one sentence per line ends sentences with ".\n", and a scope
    that runs past it borrows the neighbouring sentence's polarity."""
    text = prompt or ""
    try:
        import _prose_polarity as _pp
    except Exception:  # noqa: BLE001
        _pp = None
    for rx in _TARGET_RES:
        for m in rx.finditer(text):
            if _pp is not None:
                lo, hi = _pp.sentence_scope(text, m.start(), m.end(),
                                            extra_breaks=_pp.LINE_END_BREAKS)
                if _pp.is_denied(text[lo:hi]):
                    continue
            return m.group(1)
    return None


def integration_contract_md(ic_class: str, requirements: List[str]) -> str:
    """The class-level CONTRACT a layer-expectation hand-off must satisfy: what
    this registered class's generated integration / constraints layers have to
    carry. The analogue of `iface_to_contract_v` for a hand-off whose target is
    a document rather than a module — requirements only, no answers."""
    lines = [f"# Integration contract — registered ic_class `{ic_class}`", "",
             "The generated integration (L9) and constraints (L19) layers for a design",
             "of this class must carry each of the following. These are REQUIREMENTS on",
             "the layers, not answers about this design; read the design input for the",
             "answers.", ""]
    for r in requirements:
        lines.append(f"- {r}")
    return "\n".join(lines) + "\n"


def _db_hits(prompt: str, k: int, ic_class=None) -> List[Dict[str, Any]]:
    try:
        import ic_expert_db_query as _db
        hits = _db.query(prompt, k=k, ic_class=ic_class) or []
    except KeyError:
        # A class profile naming an entry the DB does not carry. This one is
        # NOT swallowed: the blanket `return []` below is the right answer for
        # "retrieval found nothing", and the wrong one for "the class-first
        # configuration is broken" — it would turn a mis-declared profile into
        # a silently empty pack, which is the failure the raise exists to
        # prevent. It reaches the caller, which records it as a stated ERROR.
        raise
    except Exception:
        return []
    out = []
    for h in hits:
        if isinstance(h, dict):
            out.append({"ic_class": h.get("ic_class"),
                        "score": round(float(h.get("score", 0) or 0), 2)})
    return out


def _spec_requirements(prompt: str,
                       context_keys=None, output_target="rtl.sv") -> List[Dict[str, Any]]:
    """Run the deterministic spec detectors on the prompt (+ `input.context` file
    keys) and return the concrete, chip-agnostic requirements an author would
    otherwise silently drop. These are the distilled RCA rules (issue #126): an
    addressable memory region behind the same bus as the CSRs (extraction-gap), a
    lint-review deliverable whose graded axis is `verilator -Wall` cleanliness
    (coverage-gap), and a context-sibling collision advisory (never inline a
    verbatim copy of a separately-compiled context module). Input-only."""
    reqs: List[Dict[str, Any]] = []
    try:
        import spec_memory_region_detect as _mem
        r = _mem.detect_memory_region(prompt)
        if r.get("has_memory_region") and r.get("requirement"):
            reqs.append({
                "kind": "memory_map_completeness",
                "confidence": r.get("confidence"),
                "requirement": r["requirement"],
                "evidence": r.get("evidence", [])[:3],
            })
    except Exception:
        pass
    try:
        import spec_lint_review_detect as _lint
        r = _lint.detect_lint_review(prompt)
        if r.get("is_lint_review") and r.get("requirement"):
            reqs.append({
                "kind": "lint_review_selfgate",
                "requirement": r["requirement"],
                "self_gate": "verilog_selfcheck_lint.py (verilator --lint-only -Wall)",
                "issues_requested": r.get("issues_requested", []),
            })
    except Exception:
        pass
    try:
        import spec_context_sibling_detect as _sib
        r = _sib.detect_context_siblings(prompt, context_keys)
        if r.get("has_siblings") and r.get("requirement"):
            reqs.append({
                "kind": "context_sibling_no_inline",
                "requirement": r["requirement"],
                "sibling_modules": r.get("sibling_modules", []),
                "prose_excluded": r.get("prose_excluded", []),
            })
    except Exception:
        pass
    try:
        import spec_selftb_coverage_detect as _stb
        r = _stb.detect_selftb_coverage(prompt)
        if r.get("shapes") and r.get("requirement"):
            reqs.append({
                "kind": "self_tb_coverage",
                "requirement": r["requirement"],
                "shapes": r.get("shapes", []),
                "authoring_invariants": r.get("authoring_invariants", []),
                "self_tb_scenarios": r.get("self_tb_scenarios", []),
                "parameter_sweeps": r.get("parameter_sweeps", []),
            })
    except Exception:
        pass
    try:
        import spec_named_signal_detect as _sig
        r = _sig.detect_named_signals(prompt)
        if r.get("has_named_signals") and r.get("requirement"):
            requirement = r["requirement"]
            if Path(output_target).suffix.lower() not in {".v", ".sv"}:
                requirement = (
                    f"When authoring {output_target}, preserve the input's "
                    "explicit signal identities and source roles in the "
                    "expectations or review: " + ", ".join(r["named_signals"]) +
                    ". Use the source context to place each fact in its owning "
                    "layer. Keep libraries, parameters, metadata and commands "
                    "in their declared roles; review ambiguous identifiers "
                    "with the expert. This is advisory.")
            reqs.append({
                "kind": "preserve_named_signals",
                "requirement": requirement,
                "named_signals": r.get("named_signals", [])[:20],
                "signal_evidence": r.get("signal_evidence", []),
                "non_signal_identifiers": r.get("non_signal_identifiers", []),
                "ambiguous_identifiers": r.get("ambiguous_identifiers", []),
            })
    except Exception:
        pass
    return reqs


def class_first_disposition(ic_class, availability=None) -> Dict[str, Any]:
    """What CLASS-FIRST did, or did not do, for `ic_class` — for a CONSUMER's
    record, not for the agent's pack.

    Three states, kept apart on purpose. `PROFILED` (the DB declares the class's
    db_classes and integration contract, so retrieval was confined and the pack
    has a defined shape); `NOT_PROFILED` (the class is registered and the DB
    declares no profile for it — retrieval was the unconfined lexical ranking
    and the pack is not refused); `NOT_A_REGISTERED_CLASS` (the caller passed
    something the registry does not name, including the absent/unknown case).
    Collapsing the middle state into the last is how an unprofiled class goes
    silent: the record would say "no class" where the truth is "a class nobody
    has profiled yet".

    `availability` (#2144) is the CALLER's statement of why it had no class to
    pass, as `phase1_expert_parse_track.registered_ic_class_disposition` returns
    it. This function is handed a NAME and cannot itself tell "the classifier
    read the design and could not place it" from "the classifier had not run
    yet" — so the last state above absorbed both, and a reader of a pack
    assembled too early was told the registry did not carry the name. When the
    caller supplies it, it is recorded verbatim under `class_availability` and
    the state's `reason` names it. Omitted (the default) the returned dict is
    byte-identical to the pre-#2144 one, so no existing consumer moves."""
    try:
        import ic_expert_db_query as _dbq
        profile = _dbq.registered_class_profile(ic_class)
        registered = _dbq.is_registered_class(ic_class)
    except Exception as exc:  # noqa: BLE001
        return {"ic_class": ic_class, "profile": "NOT_MEASURED",
                "reason": f"the expert DB could not be read: {exc}"}
    if profile:
        return {"ic_class": ic_class, "registered": True, "profile": "PROFILED",
                "db_class_selection": "CLASS_CONFINED",
                "db_classes": list(profile.get("db_classes") or []),
                "reason": ("the registered class selected the db entries; lexical "
                           "phrase retrieval only ranked within them")}
    if registered:
        return {"ic_class": ic_class, "registered": True, "profile": "NOT_PROFILED",
                "db_class_selection": "LEXICAL_UNCONFINED", "db_classes": [],
                "reason": ("the expert DB declares no profile for this registered "
                           "class, so there is no class-level statement of what an "
                           "assembled pack for it contains. Retrieval and assembly "
                           "are unchanged and the pack is NOT refused — refusing on "
                           "an unprofiled class would score the absence of a profile "
                           "as the design's deficiency")}
    out = {"ic_class": ic_class, "registered": False,
           "profile": "NOT_A_REGISTERED_CLASS",
           "db_class_selection": "LEXICAL_UNCONFINED", "db_classes": [],
           "reason": ("no registered ic_class was supplied, or the name is not one "
                      "the registry carries")}
    if isinstance(availability, dict) and availability.get("reason_class"):
        # STATED, never substituted: the sentence above stays exactly as it was
        # (it is what this function, holding only a name, can say) and the
        # caller's reason is added beside it. Overwriting it would trade one
        # under-determined record for another.
        out["class_availability"] = dict(availability)
        out["reason"] = (
            f"{out['reason']}. The caller states why it had none: "
            f"{availability['reason_class']} — {availability.get('reason', '')}")
    return out


_PHASE1_FRAME_RULES = [
    "Author IC/TEST expectations from the semantic/typed-obligation projection. "
    "Unknown roles and unsupported fields remain possible requirements, never silently nonnormative.",
    "The retained raw reading includes qualification/audit context. Its tool/source/good/CEX pins "
    "remain enforced by their native consumers, not lexical IC L-layer requirements. "
    "Do not infer a role from a filename or a caller's nonnormative label.",
    "Keep real obligations in JSON and mixed records; typed planning and unresolved answers "
    "retain their existing consumers. Do not invent Ldoc fields or tune expectations to outputs.",
    "Return input_frame_sha256 exactly as supplied with the newly authored expectations. "
    "Never retrofit a historical answer. Native-only audit changes do not change this semantic binding.",
]


def phase1_frame(prompt: str, source_frame: dict, *, authoring_schema=None,
                 out_dir: Path | None = None) -> tuple[str, str]:
    """One rendering/binding definition for pack production and read-only reopening."""
    if source_frame.get("semantic_text") != prompt:
        raise ValueError("semantic prompt differs from collector frame")
    semantic = [{"path": m["path"], "text": m["semantic_text"],
                 "responsibility": m["responsibility"]}
                for m in source_frame["members"] if m["semantic_text"]]
    import inspect
    context = {name: hashlib.sha256((out_dir / name).read_bytes()).hexdigest()
               for name in ("lessons.md", "ic_expert_db.md", "contract.md", "contract.v")
               if out_dir is not None and (out_dir / name).is_file()}
    binding = {"semantic_members": semantic, "semantic_text": prompt,
               "responsibility_mapping_sha256": source_frame["responsibility_mapping_sha256"],
               "instructions": _PHASE1_FRAME_RULES,
               "authoring_schema": {k: v for k, v in (authoring_schema or {}).items()
                                    if k != "phase1_root"},
               "expert_context": context,
               "pack_policy_sha256": hashlib.sha256((inspect.getsource(assemble)
                   + inspect.getsource(phase1_frame)).encode()).hexdigest(),
               "status": source_frame["status"], "truncated": source_frame["truncated"],
               "skips": source_frame["files_skipped"]}
    digest = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
    sections = ["# Semantic / typed obligations\n" + prompt,
                "# Retained original reading — audit and qualification context\n"
                "These original bytes are retained for review; their responsibilities are stated per member."]
    for member in source_frame["members"]:
        sections.append(f"## {member['path']} sha256:{member['sha256']} bytes:{member['bytes']} "
                        f"complete:{member['complete']} responsibility:{member['responsibility']}\n"
                        + member["text"])
    return "\n\n".join(sections), digest


def assemble(prompt: str, iface: Optional[List[Dict[str, Any]]], target: Optional[str],
             expert_skills: List[str], verify_gates: List[str],
             out_dir: Path, k: int = 5, context_keys=None,
             output_target: str = "rtl.sv", ic_class=None,
             authoring_schema=None, *, source_frame=None) -> Dict[str, Any]:
    """Assemble the IC-Expert-Agent AI-backup pack into `out_dir`. Returns the
    hand-off descriptor (also written to `out_dir/ic_expert_agent_handoff.json`).
    `context_keys` (optional) = the record's `input.context` file paths, used for
    the context-sibling collision advisory.

    `output_target` names the artefact the agent is asked to author. It defaults
    to `rtl.sv` — the RTL-authoring hand-off this module was built for.
    The assembly itself (retrieve, render the two INDEPENDENT digests, write the
    contract, emit the descriptor) is target-agnostic, so the Phase-1 expert
    PARSE track reuses it verbatim with `l_doc_expectations.json`. Same dual-
    track hand-off, different question asked of it — reusing it is what keeps
    one measured mechanism instead of two similar ones drifting apart.

    `ic_class` is the design's REGISTERED class. Default None → every field is
    computed exactly as before, so a caller that does not know the class gets a
    byte-identical descriptor. When it names a class the expert DB PROFILES, the
    assembly becomes CLASS-FIRST and the descriptor carries a `class_first`
    block stating what the class selected and whether the pack is assembled at
    all. See the module docstring for why the refusal exists."""
    out_dir.mkdir(parents=True, exist_ok=True)
    prompt = prompt or ""

    # ── class-first selection ───────────────────────────────────────────────
    # `profile` is a dict only for a class the DB PROFILES. A registered class
    # mapped to null and a name that is not a class at all are both "no
    # profile" for selection purposes, but they are DIFFERENT facts and the
    # descriptor keeps them apart.
    profile = registered = None
    try:
        import ic_expert_db_query as _dbq
        profile = _dbq.registered_class_profile(ic_class)
        registered = _dbq.is_registered_class(ic_class)
    except Exception:  # noqa: BLE001
        profile, registered = None, None

    # expert-SKILLS digest (Track 1) + expert-DB digest (Track 2).
    n_skills = n_db = 0
    try:
        import _lesson_digest as _ld
        n_skills = _ld.render_lesson_digest(out_dir)
        # SAME ic_class as the descriptor below. `ic_expert_db.md` is the file
        # the agent READS; `db_classes` is only a note about it. Rendering the
        # digest unconfined while the descriptor lists the confined classes
        # would leave the pack DESCRIBING one selection and DELIVERING another.
        n_db = _ld.render_ic_expert_db_digest(out_dir, prompt, k=k,
                                              ic_class=ic_class)
    except KeyError:
        raise
    except Exception:
        pass
    db_classes = _db_hits(prompt, k, ic_class=ic_class)

    # TARGET MODULE, resolved FIRST because the contract choice depends on it.
    # A caller-supplied target always wins; only a profiled class falls back to
    # recovering the name the design INPUT states, because turning recovery on
    # for every class changes every design's pack at once.
    if not target and profile:
        target = recover_target_module(prompt)

    # interface CONTRACT (the load-bearing spec the body must honour).
    contract_rel = None
    contract_kind = None
    if iface and target:
        (out_dir / "contract.v").write_text(iface_to_contract_v(iface, target))
        contract_rel = "contract.v"
        contract_kind = "module_header_v"
    elif profile:
        # No recovered port list, but the CLASS has a declared contract: what
        # this class's generated integration/constraints layers must carry.
        # That is a real contract for a layer-expectation hand-off, and it is
        # the one thing a null pack was missing.
        reqs = [r for r in (profile.get("integration_contract") or [])
                if isinstance(r, str)]
        if reqs:
            (out_dir / "contract.md").write_text(
                integration_contract_md(str(ic_class), reqs))
            contract_rel = "contract.md"
            contract_kind = "class_integration_contract_md"

    handoff = {
        "subagent_type": SUBAGENT_TYPE,
        "role": "IC Expert Agent authors the body using expert-DB + expert-skills",
        "prompt_is_input_only": True,
        "target_module": target,
        "interface_contract": contract_rel,
        "spec_requirements": _spec_requirements(prompt, context_keys, output_target),
        "expert_skills": expert_skills,
        "verify_gates": verify_gates,
        "db_classes": db_classes,
        "dual_track": {
            "track1_general_blind": {
                "context": ["lessons.md"] if n_skills else [],
                "n_skills": n_skills,
            },
            "track2_db_informed": {
                "context": ["ic_expert_db.md"] if n_db else [],
                "n_db_lessons": n_db,
            },
            "converge": "diff the two bodies; root-cause + reconcile disagreement",
        },
        "output_target": output_target,
    }

    # ── assembly status ─────────────────────────────────────────────────────
    # Emitted only for a class the DB PROFILES: only there is "assembled"
    # defined, and only there can the absence of a target/contract be the
    # pack's fault rather than the classifier's silence. For every other class
    # the descriptor is byte-identical to the pre-#2094 one.
    if profile:
        in_class = sorted({h.get("ic_class") for h in db_classes
                           if isinstance(h, dict) and h.get("ic_class")})
        missing = []
        if not target:
            missing.append("target_module")
        if not contract_rel:
            missing.append("interface_contract")
        # THREE states, not two, and the middle one is the reason.
        #   ASSEMBLED             both present.
        #   ASSEMBLED_INCOMPLETE  one present, one missing. The pack DOES carry
        #                         class knowledge; a named field is absent.
        #   NOT_ASSEMBLED         NEITHER present, i.e. nothing class-specific
        #                         at all — the state that was measured.
        # Collapsing the middle into NOT_ASSEMBLED would make this module's own
        # refusal text ("the pack contributed no class knowledge") FALSE for a
        # pack that carries a full class contract and merely could not recover a
        # module name. A refusal that overstates its grounds is the same defect
        # as a pack that overstates its contents, pointed the other way.
        if not missing:
            status = "ASSEMBLED"
        elif len(missing) == 2:
            status = "NOT_ASSEMBLED"
        else:
            status = "ASSEMBLED_INCOMPLETE"
        cf: Dict[str, Any] = {
            "ic_class": ic_class,
            "registered": True,
            "profile": "DECLARED",
            "db_class_selection": "CLASS_CONFINED",
            "db_classes_selected_by_class": list(profile.get("db_classes") or []),
            "db_classes_in_pack": in_class,
            "contract_kind": contract_kind,
            "assembly_status": status,
            "missing_fields": missing,
        }
        if status == "NOT_ASSEMBLED":
            cf["not_assembled_reason"] = (
                f"the registered ic_class {ic_class!r} is PROFILED, so this pack "
                f"has a defined shape, and it carries NEITHER a target_module NOR "
                f"an interface_contract. A pack with nothing class-specific in it "
                f"must not be handed on as an assembled pack: a consumer that "
                f"credits it records a review as having had expert context it "
                f"never had. Supply the interface (or state the top module in the "
                f"design input) and re-assemble.")
        elif status == "ASSEMBLED_INCOMPLETE":
            cf["incomplete_reason"] = (
                f"the pack carries this class's knowledge and is missing "
                f"{missing}. Stated rather than refused: it is not an empty pack, "
                f"and calling it one would overstate the grounds.")
        handoff["class_first"] = cf
    # An unprofiled class adds NO key: the descriptor is the AGENT's reading
    # surface, and "we did not confine the retrieval" is not something the
    # agent can act on. It is something the RECORD must state, so the consumer
    # calls `class_first_disposition()` and writes it into its own record —
    # which is where a reader looks to learn what context the track had. That
    # keeps the pack for an unprofiled class byte-identical to the pre-#2094
    # one, so a change to a profiled class can never be confused with drift
    # somewhere else.

    if output_target == "l_doc_expectations.json":
        # Phase-1 expectation authors compare generated L-docs. State the
        # generated schema explicitly: source documents may use different
        # historical layer numbers, but the generated contract does not.
        # The pack must also carry the INPUT it asks the agent to review. The
        # old descriptor named an output and two lesson digests but did not
        # contain the design input, so an orchestrator could dispatch it only
        # by inventing another, undocumented read surface (#1973).
        input_name = "design_input.txt"
        reading = prompt
        if source_frame is not None:
            reading, _binding = phase1_frame(prompt, source_frame)
            handoff["source_frame"] = source_frame
            handoff["raw_input_frame_sha256"] = hashlib.sha256(
                json.dumps(source_frame, sort_keys=True).encode()).hexdigest()
        (out_dir / input_name).write_text(reading)
        handoff["read_design_input_from"] = input_name
        # THE LAYER CONTRACT (#2150 F5). Two entries were hard-coded here —
        # `{"L9": ..., "L19": ...}` — for projects whose Phase-1 root carries
        # two dozen layer documents. An author handed that pack can address
        # only those two layers, so every expectation was scoped to one of
        # them whatever layer actually owned the fact; and `field_path` was
        # documented as "optional field path" with no vocabulary at all, so
        # the only paths an author could write were invented out of the two
        # prose descriptions. MEASURED: `integration.*` on L9 and
        # `constraints.*` on L19, 46 of 46 refused by the #2127 guard as
        # undeclared. The pack manufactured the authoring defect the guard
        # then reported.
        #
        # So the caller may supply the schema DERIVED from the project's own
        # emitted L-docs, and it replaces both halves. When it does not, the
        # descriptor is byte-identical to the pre-#2150 one: a pack for a
        # caller that cannot derive a schema must not change shape, or a
        # change here becomes indistinguishable from drift somewhere else.
        derived = (authoring_schema or {}) if \
            (authoring_schema or {}).get("status") == "OK" else {}
        if derived:
            handoff["generated_layer_contract"] = {
                stem: info["purpose"]
                for stem, info in sorted(derived["layers"].items())}
            (out_dir / "authoring_schema.json").write_text(
                json.dumps(derived, indent=2, ensure_ascii=False))
            handoff["authoring_schema"] = {
                "file": "authoring_schema.json",
                "schema": derived["schema"],
                "layer_count": len(derived["layers"]),
                "declared_field_path_count": sum(
                    i["declared_field_path_count"]
                    for i in derived["layers"].values()),
                "phase1_root_digest": (derived.get("phase1_root")
                                       or {}).get("digest"),
                "rule": derived["rule"],
            }
        else:
            handoff["generated_layer_contract"] = {
                "L9": "integration specification",
                "L19": "constraints and implementation context",
            }
        shape = {
            "id": "stable rule-and-subject identifier",
            "layer": "generated L-layer name",
            "field_path": ("a field path THIS LAYER DECLARES, per "
                           "authoring_schema.json — or omitted, which states "
                           "that the expectation is about the whole layer"
                           if derived else "optional field path"),
            "requirement": "what the input requires the layer to carry",
            "evidence": ["input-only evidence supporting the expectation"],
            "expected_tokens": (
                derived.get("expected_tokens_rule")
                or ["one or more tokens to compare"]),
        }
        # THE SPLIT FORM (#2150 class 3). Advertised here because a grammar
        # the author is never shown is a grammar nobody writes: the two rows
        # that needed it were filed as design gaps for exactly as long as the
        # pack described one layer per expectation.
        split_shape = {
            "id": "stable rule-and-subject identifier",
            "requirement": "what the input requires, as ONE fact",
            "evidence": ["input-only evidence supporting the expectation"],
            "sub_expectations": [{
                "layer": "generated L-layer name",
                "field_path": "a field path THAT layer declares, or omitted",
                "expected_tokens": (
                    derived.get("expected_tokens_rule")
                    or ["one or more tokens to compare"]),
            }],
        }
        handoff["answer_contract"] = {
            "schema": "vibeic.phase1-expert-expectations.v1",
            "minimum_expectations": 1,
            "shape": {"expectations": [shape]},
            "split_shape": {
                "when": ("the fact is ONE fact and the layers that carry it "
                         "are more than one — every branch must agree, and a "
                         "branch is scoped and guarded exactly as a single "
                         "expectation is"),
                "expectations": [split_shape],
                "not_a_disjunction": ("all branches must agree; a split is "
                                      "never easier to satisfy than any one "
                                      "of its halves"),
            },
            "rules": [
                "read only design_input.txt plus the two expert digests",
                "never read an oracle, harness, golden artifact, or hidden answer",
                "write the JSON object to l_doc_expectations.json",
                "an empty expectations list is incomplete, not a completed review",
            ] + ([
                "address a layer this pack's generated_layer_contract names — "
                "it lists EVERY layer this project emitted, not a subset",
                "a `field_path` must be one authoring_schema.json lists for "
                "the layer you address, or be omitted; an undeclared path is "
                "refused by name at review time and the reading then falls "
                "back to the whole layer, so the finding would describe a "
                "field nothing looked at",
                "state one fact per expectation; when its halves live in "
                "different layers use split_shape rather than naming one "
                "layer and listing every token",
            ] if derived else []),
        }
    if output_target == "l_doc_expectations.json" and source_frame is not None:
        _reading, handoff["input_frame_sha256"] = phase1_frame(
            prompt, source_frame, authoring_schema=authoring_schema, out_dir=out_dir)
        handoff["answer_contract"]["rules"] += _PHASE1_FRAME_RULES
        handoff["answer_contract"]["input_frame_sha256"] = handoff["input_frame_sha256"]
    (out_dir / "ic_expert_agent_handoff.json").write_text(
        json.dumps(handoff, indent=2, ensure_ascii=False))
    return handoff


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True, help="prompt text or @file")
    ap.add_argument("--out", required=True)
    ap.add_argument("--target", default=None)
    ap.add_argument("--skills", default="", help="comma list of expert skills")
    ap.add_argument("--verify", default="", help="comma list of verify gates")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--ic-class", default=None,
                    help="the design's REGISTERED ic_class; when the expert DB "
                         "profiles it, assembly is CLASS-FIRST and the pack states "
                         "whether it is assembled at all")
    a = ap.parse_args(argv)
    prompt = a.prompt
    if prompt.startswith("@"):
        prompt = Path(prompt[1:]).read_text()
    h = assemble(prompt, None, a.target,
                 [s for s in a.skills.split(",") if s],
                 [s for s in a.verify.split(",") if s],
                 Path(a.out), k=a.k, ic_class=a.ic_class)
    print(json.dumps(h, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
