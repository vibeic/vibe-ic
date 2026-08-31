#!/usr/bin/env python3
"""Project the analog/mixed-signal verification contract into L22.

ENFORCEMENT: ADVISORY PRODUCER, not a gate.  It enriches L22 and never changes
the runner's exit verdict.  Import/runtime failure is printed by the thin
runner adapter as a named fail-open event; it is never reported as a PASS.

WHERE THE VERDICT GOES (vibe-ic#1263 stamp-hygiene, flow-gate enforcement audit)
-------------------------------------------------------------------------------
Two consumers, and until this revision NEITHER could read an outcome:

  * IN-PROCESS — ``phase1_doc_one_shot_runner._post_emit_l22_analog_verification
    _plan`` calls ``run()`` at the tail of Phase 1.  Reachable, but it read only
    ``emitted_count``: a REFUSED projection and a digital no-op both returned 0
    and printed nothing, so the one state worth naming was the silent one.
  * AT THE FLOW BOUNDARY — nothing.  ``flow_gate_enforcement_audit`` reported
    this program ORPHANED ("declares an intent and is reachable from nothing at
    all"), because the runner reaches it through ``from <module> import run``,
    which is not a venue that audit consults, and no flow clause named it.

It is now wired in ``flow/phase1_phase2_phase3.yaml`` at Step D1 as
``advisory_program_exit_zero: "l22_analog_verification_plan_emit . --dry-run"``.
``--dry-run`` is load-bearing: this is a PRODUCER, and an audit that rewrote the
document it is judging would be measuring its own side effect.  The advisory
slot RUNS the program, RECORDS the verdict and never fails the step — which is
what ``ADVISORY`` above has always claimed and what nothing enforced.

That wiring is only worth having because ``_STATUS_EXIT`` (below) made the exit
code a function of the outcome.  It used to be a constant 0.

GENERAL CORE
============
Phase 1 already has the two authoritative, structured inputs this projection
needs:

* ``L5.analog_blocks[].spec.specs[]`` attributes electrical requirements to
  individual analog blocks; and
* ``L7.verification_strategy[]`` carries bullets harvested from the design's
  literal ``Verification intent`` section, including their input evidence.

The pre-existing L22 producer ignored both and emitted only five fixed digital
verification categories.  This emitter joins those two existing structures
into ``L22.fields.verification_plan.analog[]``.  Each row retains the L5 spec
records verbatim, the L5-derived verification intent, and reviewable source
evidence.  A stated PVT matrix is normalized into process and temperature axes
without inventing missing corners.

APPLICABILITY AND NO-LEAK CONTRACT
==================================
The branch is keyed on ``ic_class_registry.json`` through
``class_verification_flags(ic_class).analog_applicable`` and also requires at
least one structured L5 analog block.  An unregistered class, a class marked
``analog_applicable=false``, or an empty L5 block list is a byte-for-byte no-op:
L22 is not rewritten.  This keeps a digital-only IC's derivation identical.

No design, vendor, process, node, or part literal appears here.  Block names,
specifications, intent, and evidence all come from the design's own Phase-1
artifacts.  Re-running is idempotent.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from ic_class_profile import (  # noqa: E402
    class_verification_flags,
    detect_ic_class,
)
from l_doc_consumer_contract import l_doc_fields, load_l_doc  # noqa: E402
import l_doc_generator_stamp as _stamp  # noqa: E402
from _atomic_artefact import write_json as _atomic_write_json  # noqa: E402


TOOL = "l22_analog_verification_plan_emit"
_L22_NAME = "L22_VERIFICATION_PLAN.json"
_L5_NAME = "L5_ADI_SPEC.json"
_INTENT_STRATEGY = "verification_intent_bullet_v634"
_EMITTER_OWNED_PLAN_KEYS = frozenset({
    "schema_version", "track", "ic_class", "analog", "unscoped_intent",
    "corner_matrix",
})

_PROCESS_CORNER_RE = re.compile(
    r"(?<![A-Za-z0-9])(TT|SS|FF|SF|FS)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_TEMPERATURE_LIST_RE = re.compile(
    r"(?P<values>[+\-\N{MINUS SIGN}]?\d+(?:\.\d+)?"
    r"(?:\s*[/,]\s*[+\-\N{MINUS SIGN}]?\d+(?:\.\d+)?){1,})"
    r"\s*(?:\N{DEGREE SIGN}\s*)?[Cc](?![A-Za-z])"
)
_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_IDENTIFIER_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_ASSOCIATION_STOP = frozenset({
    "analog", "block", "circuit", "core", "design", "test", "verify",
    "verification", "simulation", "run", "the", "and", "for", "with",
})


def _read_json(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _generated_docs(project: Path) -> Path:
    return project / "phase1" / "generated_docs"


def _block_specs(block: dict) -> List[dict]:
    spec = block.get("spec")
    rows = spec.get("specs") if isinstance(spec, dict) else None
    if not isinstance(rows, list):
        return []
    return copy.deepcopy([row for row in rows if isinstance(row, dict)])


def _l5_intent(project: Path) -> Tuple[List[dict], Optional[Path]]:
    """Return only L7 entries that the existing L5-intent harvester wrote.

    L7 can also contain digital test strategy, checklist, or protocol entries.
    Copying all of those into every analog row would make the branch wider than
    its evidence.  The extraction-strategy marker is the existing producer's
    typed provenance and is therefore the join key.
    """
    path, doc = load_l_doc(project, "L7")
    payload = l_doc_fields(doc)
    rows = payload.get("verification_strategy")
    if not isinstance(rows, list):
        return [], path
    out: List[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("extraction_strategy") != _INTENT_STRATEGY:
            continue
        method = row.get("method") or row.get("description")
        if not isinstance(method, str) or not method.strip():
            continue
        kept = {
            key: copy.deepcopy(row[key])
            for key in ("phase", "method", "description", "evidence",
                        "extraction_strategy")
            if row.get(key) is not None
        }
        out.append(kept)
    return out, path


def _ordered_unique(values: Iterable[Any]) -> List[Any]:
    out: List[Any] = []
    for value in values:
        if value not in out:
            out.append(value)
    return out


def _number(raw: str) -> Any:
    value = float(raw.replace("\N{MINUS SIGN}", "-"))
    return int(value) if value.is_integer() else value


def _corner_matrix(intent: List[dict]) -> Optional[dict]:
    process: List[str] = []
    temperatures: List[Any] = []
    evidence: List[str] = []
    for row in intent:
        method = str(row.get("method") or row.get("description") or "")
        row_process = [m.group(1).upper()
                       for m in _PROCESS_CORNER_RE.finditer(method)]
        row_temperatures: List[Any] = []
        for match in _TEMPERATURE_LIST_RE.finditer(method):
            row_temperatures.extend(
                _number(v.strip())
                for v in re.split(r"[/,]", match.group("values")))
        if not row_process and not row_temperatures:
            continue
        process.extend(row_process)
        temperatures.extend(row_temperatures)
        source = row.get("evidence")
        if isinstance(source, str) and source.strip():
            evidence.append(source)
    process = _ordered_unique(process)
    temperatures = _ordered_unique(temperatures)
    evidence = _ordered_unique(evidence)
    if not process and not temperatures:
        return None
    out: Dict[str, Any] = {}
    if process:
        out["process"] = process
    if temperatures:
        out["temperature_c"] = temperatures
    if evidence:
        out["source_evidence"] = evidence
    return out


def _source_evidence(block: dict, index: int, intent: List[dict]) -> List[dict]:
    evidence: List[dict] = [{
        "layer": "L5",
        "path": f"phase1/generated_docs/{_L5_NAME}",
        "field": f"analog_blocks[{index}]",
    }]
    seen_paths = {f"phase1/generated_docs/{_L5_NAME}"}
    for spec in _block_specs(block):
        source = spec.get("source")
        if isinstance(source, str) and source and source not in seen_paths:
            seen_paths.add(source)
            evidence.append({"layer": "input", "path": source})
    for row in intent:
        source = row.get("evidence")
        if isinstance(source, str) and source and source not in seen_paths:
            seen_paths.add(source)
            evidence.append({
                "layer": "L7",
                "path": source,
                "derived_from": "L5 Verification intent section",
            })
    return evidence


def _tokens(value: Any) -> set:
    text = str(value or "")
    out = {
        token.lower() for token in _WORD_RE.findall(str(value or ""))
        if len(token) >= 2 and token.lower() not in _ASSOCIATION_STOP
    }
    # Keep complete underscore-delimited identifiers as an additional token.
    # Splitting remains useful for prose, but ``block_a`` and ``block_b`` must
    # not collapse to the shared ``block`` stem merely because their suffixes
    # are one character long.
    out.update(
        token.lower() for token in _IDENTIFIER_RE.findall(text)
        if "_" in token and token.lower() not in _ASSOCIATION_STOP
    )
    return out


def _block_identity_tokens(block: dict) -> set:
    """Tokens the design itself uses to identify one block."""
    return _tokens(block.get("name")) | _tokens(block.get("block")) \
        | _tokens(block.get("type")) | _tokens(block.get("block_type"))


def _block_spec_tokens(block: dict) -> set:
    """Tokens used by the names of one block's L5 specifications."""
    out: set = set()
    for spec in _block_specs(block):
        out |= _tokens(spec.get("name"))
    return out


def _intent_by_block(
        blocks: List[dict], intent: List[dict],
) -> Tuple[List[List[dict]], List[dict]]:
    """Associate intent structurally and retain ambiguous rows unscoped.

    Block identity is stronger evidence than shared specification vocabulary.
    A unique best specification match is used only when no identity matches.
    Tied or unmatched bullets remain at plan scope instead of being falsely
    copied to unrelated blocks.  No block-kind table or design-specific alias
    exists.
    """
    identities = [_block_identity_tokens(block) for block in blocks]
    specifications = [_block_spec_tokens(block) for block in blocks]
    scoped: List[List[dict]] = [[] for _ in blocks]
    unscoped: List[dict] = []
    for requirement in intent:
        text_tokens = _tokens(requirement.get("method")) \
            | _tokens(requirement.get("description"))
        identity_scores = [len(names & text_tokens) for names in identities]
        best_identity = max(identity_scores, default=0)
        if best_identity:
            winners = [i for i, score in enumerate(identity_scores)
                       if score == best_identity]
            targets = winners if len(winners) == 1 else []
        else:
            spec_scores = [len(names & text_tokens)
                           for names in specifications]
            best_spec = max(spec_scores, default=0)
            winners = [i for i, score in enumerate(spec_scores)
                       if score == best_spec and best_spec]
            targets = winners if len(winners) == 1 else []
        if not targets:
            unscoped.append(copy.deepcopy(requirement))
            continue
        for index in targets:
            scoped[index].append(copy.deepcopy(requirement))
    return scoped, unscoped


def _plan(ic_class: str, blocks: List[dict], intent: List[dict]) -> dict:
    rows: List[dict] = []
    scoped_intent, unscoped_intent = _intent_by_block(blocks, intent)
    for index, block in enumerate(blocks):
        name = block.get("name") or block.get("block") or block.get("type")
        if not isinstance(name, str) or not name.strip():
            continue
        rows.append({
            "block": name,
            "block_type": block.get("type") or block.get("block_type"),
            "specifications": _block_specs(block),
            "verification_intent": scoped_intent[index],
            "source_evidence": _source_evidence(
                block, index, scoped_intent[index]),
        })
    plan: Dict[str, Any] = {
        "schema_version": 1,
        "track": "analog_mixed_signal",
        "ic_class": ic_class,
        "analog": rows,
    }
    if unscoped_intent:
        plan["unscoped_intent"] = unscoped_intent
    matrix = _corner_matrix(intent)
    if matrix:
        plan["corner_matrix"] = matrix
    return plan


def run(project: Path, *, ic_class: Optional[str] = None,
        dry_run: bool = False) -> Dict[str, Any]:
    project = project.resolve()
    l22_path = _generated_docs(project) / _L22_NAME
    l5_path = _generated_docs(project) / _L5_NAME
    l22 = _read_json(l22_path)
    l5 = _read_json(l5_path)
    if l22 is None or l5 is None:
        return {
            "tool": TOOL, "status": "SKIPPED",
            "reason": "L5 and L22 must both exist and parse",
            "emitted_count": 0,
        }

    if ic_class is None:
        profile = detect_ic_class(project)
        ic_class = str(profile.get("ic_class") or "unknown")
    flags = class_verification_flags(ic_class)
    if (flags.get("registry_matched") is not True
            or flags.get("analog_applicable") is not True):
        return {
            "tool": TOOL, "status": "NOT_APPLICABLE",
            "reason": (f"IC class {ic_class!r} is not a registry-matched "
                       "analog-applicable class"),
            "ic_class": ic_class, "emitted_count": 0,
        }

    l5_payload = l_doc_fields(l5)
    raw_blocks = l5_payload.get("analog_blocks")
    blocks = ([b for b in raw_blocks if isinstance(b, dict)]
              if isinstance(raw_blocks, list) else [])
    if not blocks:
        return {
            "tool": TOOL, "status": "NOT_APPLICABLE",
            "reason": "L5 declares no structured analog blocks",
            "ic_class": ic_class, "emitted_count": 0,
        }

    intent, l7_path = _l5_intent(project)
    analog_plan = _plan(ic_class, blocks, intent)
    if not analog_plan["analog"]:
        # REFUSED, not SKIPPED, and the distinction is the whole verdict.
        # Everything above this line is "there was nothing to project": a
        # digital class, or no L5/L22 to read. HERE the class IS analog and L5
        # DOES declare blocks — the projection is OWED and could not be made,
        # so L22 ships with no analog verification plan for a chip that has
        # analog. Recording that as SKIPPED made it byte-indistinguishable from
        # a digital no-op, which is this repo's recurring "could not read reads
        # like nothing to read" substitution.
        return {
            "tool": TOOL, "status": "REFUSED",
            "reason": "L5 analog blocks carry no usable block identity",
            "ic_class": ic_class, "emitted_count": 0,
        }

    payload = l22["fields"] if isinstance(l22.get("fields"), dict) else l22
    existing_plan = payload.get("verification_plan")
    if isinstance(existing_plan, dict):
        plan = copy.deepcopy(existing_plan)
        if plan.get("track") == "analog_mixed_signal":
            for key in _EMITTER_OWNED_PLAN_KEYS:
                plan.pop(key, None)
    elif isinstance(existing_plan, list):
        # Protocol synthesis historically emitted this field as a list.  Keep
        # that plan intact while adding the structured analog sibling.
        plan = {"protocol": copy.deepcopy(existing_plan)}
    elif existing_plan is not None:
        plan = {"legacy": copy.deepcopy(existing_plan)}
    else:
        plan = {}
    plan.update(analog_plan)
    if existing_plan == plan:
        return {
            "tool": TOOL, "status": "OK", "ic_class": ic_class,
            "emitted_count": 0, "blocks_total": len(plan["analog"]),
            "doc_written": None,
        }
    if not dry_run:
        payload["verification_plan"] = plan
        _stamp.dump(l22_path, l22)
    return {
        "tool": TOOL, "status": "OK", "ic_class": ic_class,
        "emitted_count": len(plan["analog"]),
        "blocks_total": len(plan["analog"]),
        "intent_count": len(intent),
        "l7_source": (str(l7_path.relative_to(project))
                      if l7_path is not None else None),
        "doc_written": None if dry_run else str(l22_path),
    }


#: status -> process exit code, on this tree's own convention
#: (0 PASS / 1 FAIL / 2 NOT CHECKED, the one `flow_compliance_check` reads).
#:
#: IT USED TO BE `0 if status != "ERROR" else 1`, AND NO CODE PATH EVER
#: RETURNED "ERROR". The exit code was therefore a CONSTANT, so wiring this
#: program into any exit-code slot would have recorded a PASS on every project
#: in existence — a gate that cannot refuse, which is the vacuous-verdict shape
#: this repo already fails elsewhere (`drc_vacuous_pass_check`). The wiring in
#: `flow/phase1_phase2_phase3.yaml` is only worth having because the three
#: outcomes below are distinguishable at the process boundary.
#:
#: rc 2 for NOT_APPLICABLE and SKIPPED is deliberate and is NOT rc 0. The
#: advisory slot reads rc 2 as "n/a (input not present)" and rc 0 as "ok"; a
#: digital IC that projected nothing must not be recorded as an analog
#: verification plan that was made and found clean.
_STATUS_EXIT = {"OK": 0, "REFUSED": 1, "ERROR": 1,
                "NOT_APPLICABLE": 2, "SKIPPED": 2}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog=TOOL, description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--ic-class", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", default=None)
    args = parser.parse_args(argv)
    try:
        report = run(args.project, ic_class=args.ic_class,
                     dry_run=args.dry_run)
    except Exception as exc:            # noqa: BLE001 - a crash is a VERDICT
        # A traceback out of a producer wired on its exit code is rc 1 anyway;
        # what the flow could not read from it was WHICH producer failed and
        # why. Reported in the same shape as every other outcome so the
        # advisory line names the tool instead of the interpreter.
        report = {"tool": TOOL, "status": "ERROR", "reason": f"{exc}",
                  "emitted_count": 0}
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        # vibe-ic#1082: --json names the destination a downstream
        # `required_outputs` check opens, so it must appear whole or not at
        # all. `write_text` creates the final name first and fills it second;
        # a writer that dies in between leaves a truncated L22 plan under the
        # name that reads to every consumer as "the step produced this".
        _atomic_write_json(out, report)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    #: An UNRECOGNISED status is rc 1, never rc 0: a status this table does not
    #: know is a status nothing has decided about, and defaulting it to PASS is
    #: how a new outcome enters the tree already excused.
    return _STATUS_EXIT.get(str(report.get("status")), 1)


if __name__ == "__main__":
    raise SystemExit(main())
