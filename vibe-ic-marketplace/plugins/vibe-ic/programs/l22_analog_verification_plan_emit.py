#!/usr/bin/env python3
"""Project the analog/mixed-signal verification contract into L22.

ROLE: PRODUCER, not a gate.  It enriches L22 and never changes
the runner's exit verdict.  Import/runtime failure is printed by the thin
runner adapter as a named fail-open event; it is never reported as a PASS.

WHERE THE VERDICT GOES
---------------------
The producer has two consumers:

  * IN-PROCESS — ``phase1_doc_one_shot_runner._post_emit_l22_analog_verification
    _plan`` calls ``run()`` at the tail of Phase 1.  Reachable, but it read only
    ``emitted_count``: a REFUSED projection and a digital no-op both returned 0
    and printed nothing, so the one state worth naming was the silent one.
  * AT THE FLOW BOUNDARY — Step D1 declares the producer and its L22 output.

Issue #1980 removed the old ``advisory_program_exit_zero --dry-run`` duplicate.
A producer is not a predicate and must not inflate gate coverage; the runner
adapter owns execution while the final audit reads the declared L22 output.

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
import _prose_polarity as _polarity  # noqa: E402


TOOL = "l22_analog_verification_plan_emit"
_L22_NAME = "L22_VERIFICATION_PLAN.json"
_L5_NAME = "L5_ADI_SPEC.json"
_INTENT_STRATEGY = "verification_intent_bullet_v634"
_EMITTER_OWNED_PLAN_KEYS = frozenset({
    "schema_version", "track", "ic_class", "analog", "unscoped_intent",
    "corner_matrix", "cosim_scenarios", "cosim_scenario_gaps",
    "cosim_status",
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
    # Reuse the existing positive documentation/oracle role contract. These
    # rows remain literal intent in the plan, but do not declare campaigns.
    from phase1_doc_one_shot_runner import _v2055_refuse_verification_intent

    process: List[str] = []
    temperatures: List[Any] = []
    evidence: List[str] = []
    for row in intent:
        method = str(row.get("method") or row.get("description") or "")
        if _v2055_refuse_verification_intent(method, set()) is not None:
            continue
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


def _clauses(intent: List[dict]) -> List[dict]:
    """One intent row per ';'-separated clause of each bullet.

    A bullet can join two requirements about two different blocks with a
    semicolon. MEASURED on a real input: "DC operating point + line/load
    regulation (<regulator>); SNDR/ENOB transient + input sweep (modulator)."
    was attributed WHOLE to the regulator, because the regulator's identity
    token matched and identity outranks specification vocabulary, and the
    modulator's plan carried no intent at all. Split first, then associate: each
    clause is judged on its own words. A bullet with no ';' is returned
    byte-identical. The row keeps its ``phase`` (the L10 join key) and names
    the bullet it came from.
    """
    out: List[dict] = []
    for row in intent:
        method = row.get("method")
        parts = ([p.strip() for p in method.split(";")]
                 if isinstance(method, str) else [])
        parts = [p for p in parts if p]
        if len(parts) < 2:
            out.append(row)
            continue
        for index, part in enumerate(parts):
            clause = copy.deepcopy(row)
            clause["method"] = part
            clause["clause_of"] = method
            clause["clause_index"] = index
            out.append(clause)
    return out


def _plan(ic_class: str, blocks: List[dict], intent: List[dict]) -> dict:
    rows: List[dict] = []
    scoped_intent, unscoped_intent = _intent_by_block(blocks, _clauses(intent))
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


# ── co-simulation scenarios (A9's denominator) ───────────────────────────────
# The A9 co-simulation used to be graded on the scenario list its own producer
# wrote, so the producer decided how many scenarios there were and the gate
# counted them. The set is fixed HERE instead, in Phase 1, from the design
# input alone, before any A9 producer exists. Precedence:
#
#   1. an input section whose heading names co-simulation, taken literally;
#   2. otherwise rows derived ONLY from declarations, each citing its line:
#        R1  a Verification-intent clause naming an L5 quantity of a block
#            whose declared output is digital;
#        R2  a declared cross-block supply/signal relation;
#        R3  a digital boundary pin with a declared range (a clock rate);
#        R4  declared per-window reset semantics;
#   3. the standard categories no rule could derive, written to
#      ``cosim_scenario_gaps`` — disclosed, never executed.
#
# NO NUMBER IS INVENTED. A bound is an L5 record's own min/target/max. The
# structural criteria below are converter DEFINITIONS (sign, monotonic, in
# range, valid logic level, window independence) and carry no number. A row
# with no criterion at all is kept as UNBOUNDED_IN_INPUT: it runs and is
# reported, and can never PASS.
#
# Zero rows is NOT a producer refusal. The analog plan above is still owed and
# still written; ``cosim_status`` says NO_DERIVABLE_SCENARIOS and the gaps say
# why. Only the A9 gate turns that into its own not-verified tier.

_COSIM_STRATEGY_SECTION = "cosim_scenario_section_v1"
_COSIM_HEADING_RE = re.compile(
    r"^\s*#{1,6}\s*(?P<title>.*\b(?:co-?sim\w*|mixed[- ]signal\s+sim\w*)\b.*)$",
    re.IGNORECASE)
_MD_HEADING_RE = re.compile(r"^\s*(?P<hashes>#{1,6})\s")
_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?P<body>\S.*)$")
_SUBCKT_RE = re.compile(r"^\s*\.subckt\s+(?P<name>\S+)\s+(?P<pins>[^*]*)",
                        re.IGNORECASE)
_TABLE_QUOTE_RE = r"\|\s*{name}\s*\|(?P<target>[^|]*)\|(?P<range>[^|]*)\|"
_INPUT_TEXT_SUFFIXES = (".md", ".txt", ".rst", ".sp", ".spi", ".spice", ".cir")
#: Input subtrees that hold the DESIGN's own words. A PDK or a submission
#: template is not a declaration about this design.
_INPUT_TEXT_DIRS = ("docs", "interfaces")

#: A spec row that names the block's OUTPUT and says it is digital. Generic
#: signalling vocabulary; no block, pin or design literal.
_DIGITAL_WORDS = frozenset({"digital", "bitstream", "serial", "logic", "bit"})
_OUTPUT_WORDS = frozenset({"output", "out", "dout"})
_FREQUENCY_UNITS = frozenset({"hz", "khz", "mhz", "ghz"})
_SWEEP_WORDS = frozenset({"sweep", "sweeps", "swept", "ramp"})
_RESET_WORDS = frozenset({"reset", "resets", "rst"})
_WINDOW_WORDS = frozenset({"window", "windows", "conversion"})
_OVERSAMPLING_WORDS = frozenset({"osr", "oversampling"})
_RESOLUTION_WORDS = frozenset({"enob", "sndr", "sinad"})
_POWER_UP_RE = re.compile(r"power[- ]?(?:up|on)|sequenc\w*|start[- ]?up",
                          re.IGNORECASE)
_DECIMATOR_RE = re.compile(r"decimat\w*", re.IGNORECASE)
_RESET_PIN_RE = re.compile(r"\b(?:rst\w*|reset\w*)\b", re.IGNORECASE)
#: The normalised input grid a sweep row is run at. A STIMULUS grid, not a
#: criterion: it decides where the transfer is sampled, and no verdict reads a
#: number from it.
_SWEEP_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)
_STRUCTURAL = ("polarity", "monotonic", "in_range", "logic_level",
               "window_independent")


def _input_lines(project: Path) -> List[Tuple[str, int, str]]:
    """(project-relative path, 1-based line, text) for the design's input."""
    root = project / "input"
    files: List[Path] = []
    for sub in _INPUT_TEXT_DIRS:
        base = root / sub
        if base.is_dir():
            files.extend(p for p in sorted(base.rglob("*"))
                         if p.is_file()
                         and p.suffix.lower() in _INPUT_TEXT_SUFFIXES)
    if root.is_dir():
        files.extend(p for p in sorted(root.glob("*"))
                     if p.is_file() and p.suffix.lower() in _INPUT_TEXT_SUFFIXES)
    out: List[Tuple[str, int, str]] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = path.relative_to(project).as_posix()
        for number, line in enumerate(text.splitlines(), 1):
            out.append((rel, number, line))
    return out


def _cite(rel: str, number: int) -> str:
    return f"{rel}:{number}"


def _cells(line: str) -> List[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _norm_raw(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).replace(
        "\N{EN DASH}", "-").replace("\N{EM DASH}", "-").replace(
        "\N{MINUS SIGN}", "-").lower()


def _spec_line(lines: List[Tuple[str, int, str]], spec: dict
               ) -> Optional[str]:
    """The input table row an L5 spec record was read from."""
    name = str(spec.get("name") or "").strip()
    if not name:
        return None
    source = Path(str(spec.get("source") or "")).name
    target = _norm_raw(spec.get("target_raw"))
    hits = []
    for rel, number, line in lines:
        if not line.lstrip().startswith("|"):
            continue
        cells = _cells(line)
        if len(cells) < 2 or cells[0] != name:
            continue
        if target and _norm_raw(cells[1]) != target:
            continue
        hits.append((Path(rel).name != source, rel, number))
    if not hits:
        return None
    hits.sort()
    return _cite(hits[0][1], hits[0][2])


def _text_line(lines: List[Tuple[str, int, str]], text: str
               ) -> Optional[str]:
    """The input line holding `text` (markup ignored)."""
    def clean(value: str) -> str:
        return re.sub(r"[*_`]+", "", value).strip()
    needle = clean(text)[:60]
    if not needle:
        return None
    for rel, number, line in lines:
        if needle in clean(line):
            return _cite(rel, number)
    return None


def _block_pins(lines: List[Tuple[str, int, str]], block: dict
                ) -> List[dict]:
    """The block's boundary pins as the input's interface netlist declares."""
    names = {str(block.get(k) or "").lower() for k in ("name", "block")}
    names.discard("")
    for rel, number, line in lines:
        m = _SUBCKT_RE.match(line)
        if not m or m.group("name").lower() not in names:
            continue
        pins = [p for p in m.group("pins").split() if "=" not in p]
        return [{"pin": p, "evidence": _cite(rel, number)} for p in pins]
    return []


def _spec_text_tokens(spec: dict) -> set:
    return (_tokens(spec.get("name")) | _tokens(spec.get("note"))
            | _tokens(spec.get("target_raw")))


def _pin_for(pins: List[dict], spec: dict, *, use_text: bool = False
             ) -> Optional[dict]:
    """The one pin a spec record describes, or None when that is not unique."""
    name_tokens = _tokens(spec.get("name"))
    text_tokens = _spec_text_tokens(spec) if use_text else name_tokens
    scores = []
    for pin in pins:
        pname = pin["pin"].lower()
        parts = {t for t in pname.split("_") if t}
        score = 0
        if pname in name_tokens:
            score += 3
        score += len(parts & text_tokens)
        if any(len(pname) >= 3 and pname in tok for tok in name_tokens):
            score += 2
        scores.append(score)
    best = max(scores, default=0)
    if not best or scores.count(best) != 1:
        return None
    return pins[scores.index(best)]


def _has_bound(spec: dict) -> bool:
    return any(isinstance(spec.get(k), (int, float)) for k in ("min", "max"))


def _bound_criterion(block: str, spec: dict, pin: Optional[dict]) -> dict:
    out: Dict[str, Any] = {"block": block, "quantity": spec.get("name"),
                           "unit": spec.get("unit"),
                           "bound_raw": {"target": spec.get("target_raw"),
                                         "range": spec.get("range_raw")}}
    for key in ("min", "max", "target"):
        if isinstance(spec.get(key), (int, float)):
            out[key] = spec[key]
    if pin:
        out["pin"] = pin["pin"]
    return out


def _digital_output(block: dict, pins: List[dict]
                    ) -> Optional[Tuple[dict, Optional[dict]]]:
    """(the spec declaring a digital output, its pin) or None."""
    for spec in _block_specs(block):
        if not (_tokens(spec.get("name")) & _OUTPUT_WORDS):
            continue
        if _spec_text_tokens(spec) & _DIGITAL_WORDS:
            return spec, _pin_for(pins, spec, use_text=True)
    return None


def _grading(criteria: List[dict]) -> str:
    if any("quantity" in c for c in criteria):
        return "BOUNDED"
    if criteria:
        return "STRUCTURAL"
    return "UNBOUNDED_IN_INPUT"


def _corners_of(text: str) -> dict:
    named = [m.group(1).lower() for m in _PROCESS_CORNER_RE.finditer(text)]
    if named:
        return {"process": _ordered_unique(named), "source": "clause"}
    return {"process": ["tt"], "temperature": "nominal",
            "source": "no corner named by the row's own clause"}


def _find_spec(block: dict, words: frozenset) -> Optional[dict]:
    for spec in _block_specs(block):
        if _tokens(spec.get("name")) & words:
            return spec
    return None


def _explicit_section(lines: List[Tuple[str, int, str]], blocks: List[dict]
                      ) -> List[dict]:
    """Rows of an input section headed co-simulation, taken literally."""
    rows: List[dict] = []
    index = 0
    while index < len(lines):
        rel, number, line = lines[index]
        m = _COSIM_HEADING_RE.match(line)
        index += 1
        if not m or _polarity.is_denied(m.group("title")):
            continue
        level = len(_MD_HEADING_RE.match(line).group("hashes"))
        while index < len(lines) and lines[index][0] == rel:
            _, n2, body_line = lines[index]
            h = _MD_HEADING_RE.match(body_line)
            if h and len(h.group("hashes")) <= level:
                break
            index += 1
            b = _BULLET_RE.match(body_line)
            text = b.group("body").strip() if b else ""
            if not text and body_line.lstrip().startswith("|"):
                cells = _cells(body_line)
                if cells and not all(set(c) <= set("-: ") for c in cells):
                    text = " | ".join(c for c in cells if c)
            if not text:
                continue
            words = _tokens(text)
            named = [blk for blk in blocks
                     if _block_identity_tokens(blk) & words]
            criteria: List[dict] = []
            for blk in named:
                bname = str(blk.get("name") or blk.get("block"))
                for spec in _block_specs(blk):
                    if _has_bound(spec) and _tokens(spec.get("name")) & words:
                        criteria.append(_bound_criterion(bname, spec, None))
            rows.append({
                "description": text,
                "blocks": [str(b.get("name") or b.get("block"))
                           for b in named],
                "criteria": criteria,
                "corners": _corners_of(text),
                "grading": _grading(criteria),
                "evidence": [_cite(rel, n2)],
                "extraction_strategy": _COSIM_STRATEGY_SECTION,
            })
    return rows


def _derive_rows(lines: List[Tuple[str, int, str]], blocks: List[dict],
                 scoped_intent: List[List[dict]]) -> Tuple[List[dict], dict]:
    """R1..R4. Returns (rows, facts the gap pass needs)."""
    pins = [_block_pins(lines, blk) for blk in blocks]
    names = [str(blk.get("name") or blk.get("block")) for blk in blocks]
    outputs = [_digital_output(blk, p) for blk, p in zip(blocks, pins)]
    r1: List[dict] = []
    r2: List[dict] = []
    r3: List[dict] = []
    r4: List[dict] = []
    ambiguities: List[dict] = []

    # R1 — an intent clause naming an L5 quantity of a digital-output block.
    for i, blk in enumerate(blocks):
        if outputs[i] is None:
            continue
        out_spec, out_pin = outputs[i]
        observe = ([{"block": names[i], "pin": out_pin["pin"]}]
                   if out_pin else [])
        for clause in scoped_intent[i]:
            text = str(clause.get("method") or "")
            if _polarity.is_denied(text):
                continue
            where = _text_line(lines, str(clause.get("clause_of") or text))
            for phrase in (p.strip() for p in text.split("+")):
                # A bracketed word QUALIFIES the phrase — it names the block
                # the clause is about, which association already used — and is
                # not a quantity the phrase asks for.
                words = _tokens(_polarity.blank_bracketed(phrase))
                named = [s for s in _block_specs(blk)
                         if s.get("name") != out_spec.get("name")
                         and _tokens(s.get("name")) & words]
                evidence = [e for e in [where] if e]
                if named:
                    for spec in named:
                        crit = ([_bound_criterion(names[i], spec, None)]
                                if _has_bound(spec) else [])
                        line = _spec_line(lines, spec)
                        r1.append({
                            "description": phrase,
                            "blocks": [names[i]],
                            "stimulus": {"kind": "transient",
                                         "clause": phrase},
                            "observe": observe,
                            "criteria": crit,
                            "corners": _corners_of(text),
                            "grading": _grading(crit),
                            "evidence": evidence + ([line] if line else []),
                            "rule": "R1",
                        })
                    continue
                if not words & _SWEEP_WORDS:
                    continue
                swept = [s for s in _block_specs(blk)
                         if s.get("name") != out_spec.get("name") and _has_bound(s)
                         and (_tokens(s.get("note")) & words - _SWEEP_WORDS)]
                if len(swept) != 1:
                    continue
                spec = swept[0]
                pin = _pin_for(pins[i], spec)
                ref_words = _tokens(spec.get("note")) - words
                refs = [s for s in _block_specs(blk)
                        if s.get("name") != spec.get("name") and s.get("unit") == spec.get("unit")
                        and _has_bound(s)
                        and _spec_text_tokens(s) & ref_words]
                ref = refs[0] if len(refs) == 1 else None
                stimulus: Dict[str, Any] = {
                    "kind": "dc_sweep", "clause": phrase,
                    "quantity": spec.get("name"), "unit": spec.get("unit"),
                    "declared_range": {k: spec[k] for k in ("min", "max")
                                       if isinstance(spec.get(k),
                                                     (int, float))},
                    "pin": pin["pin"] if pin else None,
                }
                line = _spec_line(lines, spec)
                evidence = evidence + ([line] if line else [])
                if ref is not None and isinstance(ref.get("target"),
                                                  (int, float)):
                    # Expressed against the declared reference, because a
                    # converter's full scale IS its reference: sweeping the
                    # raw range would drive past full scale by construction
                    # wherever the input range exceeds the reference.
                    stimulus.update({
                        "normalised_to": ref.get("name"),
                        "reference_values": [ref["target"]],
                        "u_grid": list(_SWEEP_GRID),
                        "u_definition": "(input - low reference) / reference",
                        "grid_role": "instrument (stimulus sampling, not a bound)",
                    })
                    ref_line = _spec_line(lines, ref)
                    if ref_line:
                        evidence.append(ref_line)
                    if (isinstance(spec.get("max"), (int, float))
                            and spec["max"] > ref["target"]):
                        ambiguities.append({
                            "category": "input_ambiguity",
                            "reason": "range rows not paired",
                            "detail": (f"{spec.get('name')} declares up to "
                                       f"{spec.get('max')} "
                                       f"{spec.get('unit')} while "
                                       f"{ref.get('name')} declares "
                                       f"{ref.get('target')}; the sweep is "
                                       "run over the reference, and "
                                       "overload is graded only up to it"),
                            "evidence": [e for e in (line, ref_line) if e],
                        })
                crit = [{"structural": k, "block": names[i]}
                        for k in ("polarity", "monotonic", "in_range")]
                r1.append({
                    "description": phrase,
                    "blocks": [names[i]],
                    "boundary_pins": ([{"block": names[i], **pin}]
                                      if pin else []),
                    "stimulus": stimulus,
                    "observe": observe,
                    "criteria": crit,
                    "corners": _corners_of(text),
                    "grading": _grading(crit),
                    "evidence": evidence,
                    "rule": "R1",
                })

    # R2 — a spec of one block that names another block: a declared relation.
    for i, blk in enumerate(blocks):
        for spec in _block_specs(blk):
            words = _spec_text_tokens(spec)
            if _polarity.is_denied(str(spec.get("note") or "")):
                continue
            for j, other in enumerate(blocks):
                if j == i or not (_block_identity_tokens(other) & words):
                    continue
                if not _has_bound(spec):
                    continue
                lo = spec.get("min", float("-inf"))
                hi = spec.get("max", float("inf"))
                partners = []
                for cand in _block_specs(other):
                    if cand.get("unit") != spec.get("unit") \
                            or not _has_bound(cand):
                        continue
                    if not (isinstance(cand.get("min"), (int, float))
                            and isinstance(cand.get("max"), (int, float))):
                        continue
                    if cand["max"] < lo or cand["min"] > hi:
                        continue
                    shared = len(_spec_text_tokens(cand) & words)
                    partners.append((shared, cand))
                if not partners:
                    continue
                partners.sort(key=lambda p: -p[0])
                if len(partners) > 1 and partners[0][0] == partners[1][0]:
                    continue
                cand = partners[0][1]
                pin_a = _pin_for(pins[i], spec)
                pin_b = _pin_for(pins[j], cand)
                crit = [_bound_criterion(names[j], cand, pin_b),
                        _bound_criterion(names[i], spec, pin_a)]
                evidence = [e for e in (_spec_line(lines, spec),
                                        _spec_line(lines, cand)) if e]
                boundary = [x for x in (
                    {"block": names[j], **pin_b} if pin_b else None,
                    {"block": names[i], **pin_a} if pin_a else None) if x]
                r2.append({
                    "description": (f"{names[j]}.{cand.get('name')} feeds "
                                    f"{names[i]}.{spec.get('name')}"),
                    "blocks": [names[j], names[i]],
                    "boundary_pins": boundary,
                    "stimulus": {"kind": "transient", "connect": [
                        {"block": b["block"], "pin": b["pin"]}
                        for b in boundary]},
                    "observe": [{"block": b["block"], "pin": b["pin"]}
                                for b in boundary],
                    "criteria": crit,
                    "corners": _corners_of(""),
                    "grading": _grading(crit),
                    "evidence": evidence,
                    "rule": "R2",
                })

    # R3 — a digital boundary pin with a declared range: a clock rate.
    for i, blk in enumerate(blocks):
        for spec in _block_specs(blk):
            if str(spec.get("unit") or "").lower() not in _FREQUENCY_UNITS:
                continue
            points = [spec[k] for k in ("min", "target", "max")
                      if isinstance(spec.get(k), (int, float))]
            pin = _pin_for(pins[i], spec)
            if len(points) < 2 or pin is None:
                continue
            observe = ([{"block": names[i], "pin": outputs[i][1]["pin"]}]
                       if outputs[i] and outputs[i][1] else [])
            crit = ([{"structural": k, "block": names[i]}
                     for k in ("logic_level", "in_range")] if observe else [])
            line = _spec_line(lines, spec)
            r3.append({
                "description": (f"{names[i]}.{pin['pin']} at the declared "
                                f"{spec.get('name')} points"),
                "blocks": [names[i]],
                "boundary_pins": [{"block": names[i], **pin}],
                "stimulus": {"kind": "clock", "pin": pin["pin"],
                             "quantity": spec.get("name"),
                             "unit": spec.get("unit"),
                             "points": _ordered_unique(points)},
                "observe": observe,
                "criteria": crit,
                "corners": _corners_of(""),
                "grading": _grading(crit),
                "evidence": [line] if line else [],
                "rule": "R3",
            })

    # R4 — declared per-window reset semantics.
    for i, blk in enumerate(blocks):
        for spec in _block_specs(blk):
            words = _spec_text_tokens(spec)
            if not (words & _RESET_WORDS and words & _WINDOW_WORDS):
                continue
            if _polarity.is_denied(str(spec.get("note") or "")):
                continue
            observe = ([{"block": names[i], "pin": outputs[i][1]["pin"]}]
                       if outputs[i] and outputs[i][1] else [])
            window = _find_spec(blk, _OVERSAMPLING_WORDS)
            evidence = [e for e in (_spec_line(lines, spec),
                                    _spec_line(lines, window)
                                    if window else None) if e]
            crit = ([{"structural": "window_independent", "block": names[i]}]
                    if observe else [])
            r4.append({
                "description": (f"{names[i]}: consecutive conversion windows "
                                "with the same input give the same code"),
                "blocks": [names[i]],
                "stimulus": {"kind": "held_input", "windows": "consecutive",
                             "window_length": (
                                 {"quantity": window.get("name"),
                                  "value": window.get("target")}
                                 if window else None)},
                "observe": observe,
                "criteria": crit,
                "corners": _corners_of(""),
                "grading": _grading(crit),
                "evidence": evidence,
                "rule": "R4",
            })
    facts = {"pins": dict(zip(names, pins)), "ambiguities": ambiguities,
             "oversampled": [names[i] for i, b in enumerate(blocks)
                             if _find_spec(b, _OVERSAMPLING_WORDS)
                             and outputs[i]]}
    return r1 + r2 + r3 + r4, facts


def _quoted_elsewhere(lines: List[Tuple[str, int, str]], rows: List[dict],
                      blocks: List[dict]) -> List[dict]:
    """A spec the rows use, quoted elsewhere in the input with another range."""
    out: List[dict] = []
    for blk in blocks:
        for spec in _block_specs(blk):
            name = str(spec.get("name") or "")
            home = _spec_line(lines, spec)
            if not name or not home or not any(
                    home in r.get("evidence", []) for r in rows):
                continue
            pattern = re.compile(_TABLE_QUOTE_RE.format(name=re.escape(name)))
            for rel, number, line in lines:
                if _cite(rel, number) == home:
                    continue
                m = pattern.search(line)
                if not m or not m.group("range").strip():
                    continue
                if _norm_raw(m.group("range")) == _norm_raw(spec.get("range_raw")):
                    continue
                out.append({
                    "category": "input_ambiguity",
                    "reason": "a declared range is quoted differently",
                    "detail": (f"{name}: {m.group('range').strip()} at "
                               f"{_cite(rel, number)} vs "
                               f"{spec.get('range_raw')} at {home}; the "
                               "rows take the bound from the L5 record"),
                    "evidence": [_cite(rel, number), home],
                })
    return out


def _gaps(lines: List[Tuple[str, int, str]], rows: List[dict],
          facts: dict) -> List[dict]:
    """The standard co-simulation categories no row covers, each disclosed."""
    gaps: List[dict] = []
    crit = [c for r in rows for c in r.get("criteria", [])]

    def first(regex) -> Optional[str]:
        for rel, number, line in lines:
            if regex.search(line):
                return _cite(rel, number)
        return None

    seq = first(_POWER_UP_RE)
    gaps.append({"category": "power_up_sequencing",
                 "reason": ("no derivation rule reads a declared sequence"
                            if seq else "no power-up sequence is declared"),
                 "evidence": [seq] if seq else []})
    if any(r.get("rule") == "R4" for r in rows):
        declared = [p for pins in facts["pins"].values() for p in pins
                    if _RESET_PIN_RE.fullmatch(p["pin"])]
        if not declared:
            where = None
            for rel, number, line in lines:
                if Path(rel).suffix.lower() in _INPUT_TEXT_SUFFIXES[3:] \
                        and _RESET_PIN_RE.search(line):
                    where = _cite(rel, number)
                    break
            gaps.append({"category": "reset_pin",
                         "reason": ("per-window reset is declared but no "
                                    "block boundary declares a reset pin"),
                         "evidence": [where] if where else []})
    if not any(c.get("structural") == "polarity" for c in crit):
        gaps.append({"category": "connectivity_polarity",
                     "reason": "no row grades sign or polarity at a boundary",
                     "evidence": []})
    if facts["oversampled"]:
        where = first(_DECIMATOR_RE)
        gaps.append({"category": "decimator",
                     "reason": ("the input declares no decimator block; the "
                                "A9 observer is a testbench-side instrument "
                                "derived from the declared order and "
                                "oversampling ratio"),
                     "blocks": facts["oversampled"],
                     "evidence": [where] if where else []})
    if not any(_tokens(c.get("quantity")) & _RESOLUTION_WORDS for c in crit):
        gaps.append({"category": "sinad_sine_fit",
                     "reason": "no row names a resolution quantity",
                     "evidence": []})
    return gaps


def _cosim(project: Path, blocks: List[dict], intent: List[dict]) -> dict:
    """``cosim_scenarios``, ``cosim_scenario_gaps`` and ``cosim_status``."""
    lines = _input_lines(project)
    scoped, _unscoped = _intent_by_block(blocks, _clauses(intent))
    rows = _explicit_section(lines, blocks)
    status = "DECLARED" if rows else None
    facts: dict = {"pins": {}, "ambiguities": [], "oversampled": []}
    if not rows:
        rows, facts = _derive_rows(lines, blocks, scoped)
        status = "DERIVED" if rows else "NO_DERIVABLE_SCENARIOS"
    for number, row in enumerate(rows, 1):
        row["id"] = f"S{number}"
        row.setdefault("boundary_pins", [])
        row.setdefault("observe", [])
    gaps = (_gaps(lines, rows, facts) + facts["ambiguities"]
            + _quoted_elsewhere(lines, rows, blocks)) if status != "DECLARED" \
        else []
    for row in rows:
        if "rule" in row:
            row["extraction_strategy"] = f"derived_{row.pop('rule')}"
    ordered = [{"id": r["id"], **{k: v for k, v in r.items() if k != "id"}}
               for r in rows]
    return {"cosim_scenarios": ordered, "cosim_scenario_gaps": gaps,
            "cosim_status": status}


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
    analog_plan.update(_cosim(project, blocks, intent))
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
        "cosim_status": plan.get("cosim_status"),
        "cosim_scenarios": len(plan.get("cosim_scenarios") or []),
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
