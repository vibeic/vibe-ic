#!/usr/bin/env python3
"""Typed, identity-separated routing for the general front door.

The route is a semantic decision over the visible design request.  Benchmark
bookkeeping is deliberately a second object: it may bind a decision to a
coordinator task after the decision has been made, but it is not part of the
payload sent to a semantic reviewer.

This module is intentionally small.  The canonical flow YAML is the only
source of step order and ``blocks_on`` edges; a receipt binds its digest so a
changed DAG cannot silently reinterpret an old decision.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

try:
    import yaml
except ImportError:  # pragma: no cover - the plugin's canonical parser requires it
    yaml = None  # type: ignore


PROGRAMS = Path(__file__).resolve().parent
FLOW = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"

ROUTE_RECEIPT_SCHEMA = "vibeic.route_decision_receipt.v1"
# Semantic derivation changes must invalidate the existing routing-contract
# digest even when the structured dependency edges themselves are unchanged.
ROUTE_DERIVATION_RULES_VERSION = "3-bounded-original-rtl-input"
SEMANTIC_PAYLOAD_SCHEMA = "vibeic.route_semantic_payload.v1"
COORDINATOR_BINDING_SCHEMA = "vibeic.route_coordinator_binding.v1"
D1_ACTIVATION_SCHEMA = "vibeic.route_d1_activation.v1"
D1_GATE_SCHEMA = "vibeic.route_d1_gate.v1"
EXECUTION_MODE_DIRECTIVE_SCHEMA = "vibeic.execution_mode_directive.v1"
D1_PENDING = "D1_ENTRY_PENDING"
D1_ACTIVATED = "D1_ACTIVATED"
D1_PASS_VERDICTS = frozenset({"PASS"})
_ULTRA_ISSUER_BINDING = "USER_TOP_LEVEL_EXECUTION_DIRECTIVE"

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_INVOCATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
# These names are recognized only at the caller's context envelope.  They are
# never applied recursively: a register ``id``, protocol ``mode`` or nested
# block ``project`` is legitimate design input and must remain AI-visible.
_TOP_LEVEL_COORDINATOR_KEYS = {
    "bench", "benchmark", "benchmark_label", "problem_id", "id",
    "project", "project_path", "prompt_path", "response_path",
    "harness", "harness_path", "golden", "golden_path", "oracle",
    "expected", "expected_answer", "expected_answer_path", "dataset",
    "dataset_path", "run", "run_path", "coordinator_id",
    # These are metadata only when supplied in the legacy mixed envelope.  A
    # real design value belongs under ``design_context`` and is preserved.
    "category", "category_id", "env", "environment", "mode", "execution_mode",
}

_ULTRA_DIRECTIVE_RE = re.compile(
    r"(?:execution\s+mode\s*:\s*ultra|(?:please\s+)?use\s+ultra[-\s]mode)\.?",
    re.IGNORECASE,
)


def sha256_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _clean_step(value: Any) -> str:
    text = str(value).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        text = text[1:-1]
    return text


def canonical_dag(path: Path | None = None, *, input_contract: str = "structured") -> dict:
    """Parse the canonical YAML steps and their declared input dependencies.

    ``blocks_on`` is the ordering edge.  ``required_inputs.from`` is the data
    edge; both are part of the producer/consumer contract and therefore both
    belong in the route closure.  PyYAML is the same parser used by the flow
    checks, so folded and multiline YAML values cannot silently disappear in a
    regex-only projection.
    """
    if input_contract not in {"structured", "original"}:
        raise ValueError(f"unknown route input contract: {input_contract!r}")
    from step_required_inputs_check import input_contract as project_inputs  # noqa: PLC0415

    path = Path(path or FLOW)
    if yaml is None:
        raise ValueError("PyYAML is required to parse the canonical flow")
    try:
        import _flow_yaml
        doc = _flow_yaml.load(path, encoding="utf-8")
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"canonical flow is unreadable: {exc}") from exc
    rows = (doc or {}).get("steps") if isinstance(doc, Mapping) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError("canonical flow has no step declarations")
    steps: list[str] = []
    deps: dict[str, list[str]] = {}
    inputs_from: dict[str, list[str]] = {}
    for row in rows:
        if not isinstance(row, Mapping) or "id" not in row:
            continue
        row = project_inputs(row, input_contract)
        sid = _clean_step(row["id"])
        raw_blocks = row.get("blocks_on") or []
        if not isinstance(raw_blocks, (list, tuple)):
            raise ValueError(f"step {sid} has non-list blocks_on")
        raw_inputs = row.get("required_inputs") or []
        if not isinstance(raw_inputs, list):
            raise ValueError(f"step {sid} has non-list required_inputs")
        from_steps = []
        for item in raw_inputs:
            if not isinstance(item, Mapping) or "from" not in item:
                continue
            source = _clean_step(item["from"])
            if source != "external":
                from_steps.append(source)
        input_values = list(dict.fromkeys(from_steps))
        block_values = [_clean_step(x) for x in raw_blocks]
        combined = list(dict.fromkeys(block_values + input_values))
        steps.append(sid)
        deps[sid] = combined
        inputs_from[sid] = input_values
    if len(set(steps)) != len(steps):
        raise ValueError("canonical flow has duplicate step ids")
    known = set(steps)
    unknown = sorted({dep for values in deps.values() for dep in values if dep not in known})
    if unknown:
        raise ValueError(f"canonical flow has unknown dependencies: {unknown}")
    edges = [[sid, dep] for sid in steps for dep in deps[sid]]
    body = {"input_contract": input_contract,
            "derivation_rules_version": ROUTE_DERIVATION_RULES_VERSION,
            "steps": steps, "blocks_on": deps,
            "required_inputs_from": inputs_from, "edges": edges}
    return {**body, "sha256": sha256_json(body), "source": str(path.resolve())}


def _closure(step: str, deps: Mapping[str, list[str]], seen: set[str] | None = None) -> set[str]:
    seen = set() if seen is None else seen
    if step in seen:
        return seen
    seen.add(step)
    for dep in deps.get(step, []):
        _closure(dep, deps, seen)
    return seen


def dependency_closed_join(minimums: Iterable[str], *, dag: dict | None = None) -> dict:
    """Join lower bounds and return the dependency-closed proof population.

    The returned ``step`` is the least canonical common descendant whose
    dependency closure contains every bound.  A scalar maximum is not a join
    in a DAG: two branches can be ordered later in the YAML while remaining
    unrelated.
    The closure includes every transitive prerequisite of every bound and of
    the selected terminal, so a consumer can never mistake the scalar join for
    permission to omit an earlier branch.
    """
    dag = dag or canonical_dag()
    order = {sid: i for i, sid in enumerate(dag["steps"])}
    values = [str(v) for v in minimums if v is not None]
    if not values:
        raise ValueError("at least one lower bound is required")
    unknown = sorted(set(values) - set(order))
    if unknown:
        raise ValueError(f"unknown lower-bound step(s): {unknown}")
    # Select the first common descendant in declaration order.  This gives
    # the least canonical join, rather than whichever minimum happens to
    # appear latest in the YAML; e.g. proof+GDS joins at 39 while power+GDS
    # joins at 36 in the canonical flow.
    candidates = [sid for sid in dag["steps"]
                  if set(values).issubset(_closure(sid, dag["blocks_on"]))]
    if not candidates:
        raise ValueError("no canonical step contains every lower-bound dependency")
    join = min(candidates, key=lambda sid: order[sid])
    closed: set[str] = set()
    for sid in values:
        closed |= _closure(sid, dag["blocks_on"])
    closed |= _closure(join, dag["blocks_on"])
    return {
        "step": join,
        "minimums": values,
        "closed_steps": [sid for sid in dag["steps"] if sid in closed],
        "dag_sha256": dag["sha256"],
    }


def _semantic_value(value: Any) -> Any:
    """Canonicalize public design data without deleting nested semantics."""
    if isinstance(value, Mapping):
        return {str(k): _semantic_value(v)
                for k, v in sorted(value.items(), key=lambda row: str(row[0]))}
    if isinstance(value, (list, tuple)):
        return [_semantic_value(v) for v in value]
    return value


def _public_design_context(context: Mapping[str, Any] | None) -> dict:
    """Split the coordinator envelope before the semantic payload is built.

    New callers pass ``{"design_context": ..., "coordinator": ...}`` and the
    latter is discarded as a whole.  Legacy callers may still provide one
    mixed mapping; only the exact known top-level coordinator fields are
    removed there.  Nested mappings are treated as design data verbatim.
    """
    if not isinstance(context, Mapping):
        return {}
    if "design_context" in context:
        design = context.get("design_context")
        return _semantic_value(design if isinstance(design, Mapping) else {})
    return _semantic_value({
        key: value for key, value in context.items()
        if str(key).lower() not in _TOP_LEVEL_COORDINATOR_KEYS
        and str(key).lower() != "coordinator"
    })


def build_semantic_payload(prompt: str, *, context: Mapping[str, Any] | None = None,
                           requested_evidence: str | None = None,
                           delivery_target: str | None = None) -> dict:
    """Build the only object exposed to an AI semantic route/review."""
    payload = {
        "schema": SEMANTIC_PAYLOAD_SCHEMA,
        "prompt": str(prompt),
        "prompt_sha256": sha256_text(str(prompt)),
        "context": _public_design_context(context),
        "requested_evidence": requested_evidence,
        "delivery_target": delivery_target,
    }
    payload["semantic_payload_sha256"] = sha256_json(payload)
    return payload


def build_coordinator_binding(*, benchmark: str | None = None,
                              problem_id: str | None = None,
                              project_path: str | None = None,
                              prompt_path: str | None = None,
                              response_path: str | None = None,
                              dataset_path: str | None = None,
                              harness_path: str | None = None,
                              golden_path: str | None = None,
                              expected_path: str | None = None,
                              harness_digest: str | None = None,
                              golden_digest: str | None = None,
                              expected_digest: str | None = None,
                              semantic_payload_sha256: str) -> dict:
    """Bind opaque coordinator identity *after* semantic payload creation."""
    values = {
        "schema": COORDINATOR_BINDING_SCHEMA,
        # Benchmark/problem identity is coordinator-only even inside this
        # binding.  Keep only opaque handles so a serialized binding cannot
        # become an accidental semantic prompt or oracle selector.
        "benchmark_handle": sha256_text(benchmark) if benchmark else None,
        "problem_handle": sha256_text(problem_id) if problem_id else None,
        "project_handle": sha256_text(project_path) if project_path else None,
        "prompt_handle": sha256_text(prompt_path) if prompt_path else None,
        "response_handle": sha256_text(response_path) if response_path else None,
        "dataset_handle": sha256_text(dataset_path) if dataset_path else None,
        "harness_handle": sha256_text(harness_path) if harness_path else None,
        "golden_handle": sha256_text(golden_path) if golden_path else None,
        "expected_handle": sha256_text(expected_path) if expected_path else None,
        "harness_digest": harness_digest,
        "golden_digest": golden_digest,
        "expected_digest": expected_digest,
        "semantic_payload_sha256": semantic_payload_sha256,
    }
    values["binding_sha256"] = sha256_json(values)
    return values


def _minimum_from_maps(nature: str, evidence: str, target: str,
                       nature_table: Mapping[str, Any],
                       evidence_table: Mapping[str, Any],
                       delivery_table: Mapping[str, Any]) -> tuple[str, str, str, str]:
    if nature not in nature_table:
        raise ValueError(f"unknown task nature: {nature!r}")
    if evidence not in evidence_table:
        raise ValueError(f"unknown requested evidence: {evidence!r}")
    if target not in delivery_table:
        raise ValueError(f"unknown delivery target: {target!r}")
    entry = str(nature_table[nature]["entry_step"])
    evidence_step = str(evidence_table[evidence]["exit_step"])
    delivery = delivery_table[target]
    target_step = str(delivery.get("verify_through") or delivery["answer_step"])
    return entry, evidence_step, target_step, str(delivery["answer_step"])


def _route_join(minimums: Iterable[str], *, dag: dict) -> dict:
    """Join route minima while retaining the physical-delivery terminal rule.

    The canonical physical GDS terminal is the owner-visible delivery gate;
    behavioural simulation is still retained in ``closed_steps`` but is not a
    reason to promote a GDS handoff to the later cross-branch proof terminal.
    Proof+GDS and power+GDS do require their common terminals (39 and 36).
    """
    values = [str(v) for v in minimums if v is not None]
    if set(values) >= {"4", "37"} and "5" not in values and "33" not in values:
        physical = dependency_closed_join(("37",), dag=dag)
        closed = set(physical["closed_steps"])
        for sid in values:
            closed |= _closure(sid, dag["blocks_on"])
        return {**physical, "minimums": values,
                "closed_steps": [sid for sid in dag["steps"] if sid in closed]}
    return dependency_closed_join(values, dag=dag)


def _contract_dag(dag: dict | None, input_contract: str) -> dict:
    """Use the same canonical source when selecting its declared alternative."""
    if dag is None:
        return canonical_dag(input_contract=input_contract)
    if dag.get("input_contract", "structured") == input_contract:
        return dag
    source = dag.get("source")
    if not source:
        raise ValueError("a projected route DAG requires its canonical source")
    return canonical_dag(Path(source), input_contract=input_contract)


def _derive_route(*, nature: str, requested_evidence: str, delivery_target: str,
                  nature_table: Mapping[str, Any], evidence_table: Mapping[str, Any],
                  delivery_table: Mapping[str, Any], dag: dict | None = None) -> dict:
    """Derive source authority from trusted semantics, never receipt metadata."""
    entry, evidence_min, target_min, answer = _minimum_from_maps(
        nature, requested_evidence, delivery_target,
        nature_table, evidence_table, delivery_table)
    selected = _contract_dag(dag, "structured")
    joined = _route_join((entry, evidence_min, target_min), dag=selected)
    input_contract = "structured"
    # Source authority follows the requested consumer closure. Completion and
    # modification consume the supplied original request just as generation
    # does; their task nature and authored interface remain unchanged. A
    # debug/simulation entry or a deeper proof still consumes structured docs.
    if (delivery_target == "rtl" and entry in {"D1", "1", "2"}
            and joined["step"] in {"1", "2"}):
        input_contract = "original"
        entry = "1" if entry == "D1" else entry
        selected = _contract_dag(dag, input_contract)
        joined = _route_join((entry, evidence_min, target_min), dag=selected)
    return {"entry_step": entry, "answer_step": answer,
            "input_contract": input_contract, "dag": selected, "joined": joined}


@dataclass(frozen=True)
class RouteDecisionReceipt:
    """A typed decision over the fixed DAG."""

    entry_step: str
    answer_step: str
    verify_through: str
    verify_closed_steps: tuple[str, ...]
    minimum_steps: tuple[str, ...]
    task_nature: str
    requested_evidence: str
    delivery_target: str
    mode_intent: dict
    semantic_payload_sha256: str
    source_sha256: str
    dag_sha256: str
    receipt_sha256: str
    schema: str = ROUTE_RECEIPT_SCHEMA
    input_contract: str = "structured"
    derivation_rules_version: str = ROUTE_DERIVATION_RULES_VERSION

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "input_contract": self.input_contract,
            "derivation_rules_version": self.derivation_rules_version,
            "entry_step": self.entry_step,
            "answer_step": self.answer_step,
            "verify_through": self.verify_through,
            "verify_closed_steps": list(self.verify_closed_steps),
            "minimum_steps": list(self.minimum_steps),
            "task_nature": self.task_nature,
            "requested_evidence": self.requested_evidence,
            "delivery_target": self.delivery_target,
            "mode_intent": self.mode_intent,
            "semantic_payload_sha256": self.semantic_payload_sha256,
            "source_sha256": self.source_sha256,
            "dag_sha256": self.dag_sha256,
            "receipt_sha256": self.receipt_sha256,
        }


def _unambiguous_ultra_text(text: str) -> bool:
    """Accept only an entire top-level directive, never prose substrings.

    Negation/condition/conflict lists are inherently incomplete.  Requiring
    the whole value to be one directive rejects all surrounding prose,
    including quotations, prohibitions and default overrides.
    """
    return isinstance(text, str) and bool(_ULTRA_DIRECTIVE_RE.fullmatch(text.strip()))


def _typed_ultra_directive(value: Any) -> dict | None:
    """Validate the canonical, top-level user execution directive."""
    if not isinstance(value, Mapping):
        return None
    allowed = {
        "schema", "source", "issuer_binding", "execution_mode", "text",
        "evidence_sha256", "directive_sha256", "request_digest",
        "evidence_binding_sha256",
    }
    if set(value) - allowed:
        return None
    if value.get("schema") != EXECUTION_MODE_DIRECTIVE_SCHEMA:
        return None
    if value.get("source") != "user" or value.get("execution_mode") != "ultra":
        return None
    if value.get("issuer_binding") != _ULTRA_ISSUER_BINDING:
        return None
    text = value.get("text")
    if not isinstance(text, str) or not _unambiguous_ultra_text(text):
        return None
    evidence_sha = value.get("evidence_sha256")
    if not isinstance(evidence_sha, str) or not _HEX64.fullmatch(evidence_sha):
        return None
    if evidence_sha != sha256_text(text):
        return None
    body = {
        "schema": EXECUTION_MODE_DIRECTIVE_SCHEMA,
        "source": "user",
        "issuer_binding": _ULTRA_ISSUER_BINDING,
        "execution_mode": "ultra",
        "text": text,
        "evidence_sha256": evidence_sha,
    }
    directive_digest = value.get("directive_sha256")
    if directive_digest != sha256_json(body):
        return None
    return {**body, "directive_sha256": directive_digest}


def mode_intent(*, semantic_request: Mapping[str, Any],
                explicit_user_evidence: Any = None) -> dict:
    """Resolve execution mode only from explicit user evidence.

    Benchmark labels, model defaults and coordinator metadata never count as
    an Ultra request.  The request digest is always emitted for auditability.
    """
    request_digest = sha256_json(_public_design_context(semantic_request))
    typed = _typed_ultra_directive(explicit_user_evidence)
    if typed is not None:
        evidence_body = {**typed, "request_digest": request_digest}
        evidence_body["evidence_binding_sha256"] = sha256_json(evidence_body)
        return {
            "authority": "USER_EXPLICIT_ULTRA",
            "request_digest": request_digest,
            "ultra_match": True,
            "evidence_sha256": typed["evidence_sha256"],
            "issuer_binding": _ULTRA_ISSUER_BINDING,
            "ultra_evidence": evidence_body,
        }
    return {"authority": "PROGRAM_DEFAULT", "request_digest": request_digest,
            "ultra_match": False}


def explicit_ultra_evidence(text: str, *, source: str = "user") -> dict | None:
    """Normalize a complete top-level directive; free prose cannot issue it."""
    if str(source).lower() != "user" or not _unambiguous_ultra_text(text):
        return None
    body = {
        "schema": EXECUTION_MODE_DIRECTIVE_SCHEMA,
        "source": "user",
        "issuer_binding": _ULTRA_ISSUER_BINDING,
        "execution_mode": "ultra",
        "text": text,
        "evidence_sha256": sha256_text(text),
    }
    return {**body, "directive_sha256": sha256_json(body)}


def make_route_receipt(*, nature: str, requested_evidence: str,
                       delivery_target: str, semantic_payload_sha256: str,
                       source_sha256: str, nature_table: Mapping[str, Any],
                       evidence_table: Mapping[str, Any],
                       delivery_table: Mapping[str, Any],
                       explicit_user_evidence: Any = None,
                       dag: dict | None = None) -> dict:
    """Derive all executable steps; semantic AI never supplies step ids."""
    derived = _derive_route(
        nature=nature, requested_evidence=requested_evidence,
        delivery_target=delivery_target, nature_table=nature_table,
        evidence_table=evidence_table, delivery_table=delivery_table, dag=dag)
    dag, joined = derived["dag"], derived["joined"]
    mode = mode_intent(
        semantic_request={"nature": nature, "requested_evidence": requested_evidence,
                          "delivery_target": delivery_target,
                          "semantic_payload_sha256": semantic_payload_sha256},
        explicit_user_evidence=explicit_user_evidence)
    body = {
        "schema": ROUTE_RECEIPT_SCHEMA,
        "input_contract": derived["input_contract"],
        "derivation_rules_version": ROUTE_DERIVATION_RULES_VERSION,
        "entry_step": derived["entry_step"],
        "answer_step": derived["answer_step"],
        "verify_through": joined["step"],
        "verify_closed_steps": joined["closed_steps"],
        "minimum_steps": joined["minimums"],
        "task_nature": nature,
        "requested_evidence": requested_evidence,
        "delivery_target": delivery_target,
        "mode_intent": mode,
        "semantic_payload_sha256": semantic_payload_sha256,
        "source_sha256": source_sha256,
        "dag_sha256": dag["sha256"],
    }
    return {**body, "receipt_sha256": sha256_json(body)}


def validate_route_receipt(receipt: Mapping[str, Any], *, dag: dict | None = None) -> list[str]:
    errors: list[str] = []
    if receipt.get("schema") != ROUTE_RECEIPT_SCHEMA:
        errors.append("ROUTE_RECEIPT_SCHEMA")
    if receipt.get("derivation_rules_version") != ROUTE_DERIVATION_RULES_VERSION:
        errors.append("ROUTE_RECEIPT_DERIVATION_RULES_MISMATCH")
    # Re-derive all minima from the trusted product tables.  Receipt fields are
    # evidence of what was emitted, never authority for lowering the route.
    try:
        import task_nature_route as _tnr  # noqa: PLC0415
        derived = _derive_route(
            nature=str(receipt.get("task_nature")),
            requested_evidence=str(receipt.get("requested_evidence")),
            delivery_target=str(receipt.get("delivery_target")),
            nature_table=_tnr.NATURE_ENTRY, evidence_table=_tnr.EVIDENCE_EXIT,
            delivery_table=_tnr.DELIVERY_TARGETS, dag=dag)
        dag, trusted_join = derived["dag"], derived["joined"]
    except (ImportError, KeyError, TypeError, ValueError):
        errors.append("ROUTE_RECEIPT_TRUSTED_TABLES_INVALID")
        dag = _contract_dag(dag, "structured")
    else:
        if receipt.get("input_contract") != derived["input_contract"]:
            errors.append("ROUTE_RECEIPT_INPUT_CONTRACT_NOT_SEMANTIC_BOUND")
        if receipt.get("entry_step") != derived["entry_step"]:
            errors.append("ROUTE_RECEIPT_ENTRY_NOT_TABLE_BOUND")
        if receipt.get("answer_step") != derived["answer_step"]:
            errors.append("ROUTE_RECEIPT_ANSWER_NOT_TABLE_BOUND")
        if receipt.get("verify_through") != trusted_join["step"]:
            errors.append("ROUTE_RECEIPT_VERIFY_BELOW_MINIMUM")
        if receipt.get("minimum_steps") != trusted_join["minimums"]:
            errors.append("ROUTE_RECEIPT_MINIMUMS_NOT_TABLE_BOUND")
        if receipt.get("verify_closed_steps") != trusted_join["closed_steps"]:
            errors.append("ROUTE_RECEIPT_CLOSURE_NOT_DEPENDENCY_CLOSED")
    if receipt.get("dag_sha256") != dag["sha256"]:
        errors.append("ROUTE_RECEIPT_DAG_MISMATCH")
    for key in ("entry_step", "answer_step", "verify_through"):
        if str(receipt.get(key)) not in dag["steps"]:
            errors.append(f"ROUTE_RECEIPT_UNKNOWN_{key.upper()}")
    closed = receipt.get("verify_closed_steps")
    if not isinstance(closed, list) or any(str(x) not in dag["steps"] for x in closed):
        errors.append("ROUTE_RECEIPT_CLOSURE_INVALID")
    body = {k: receipt.get(k) for k in (
        "schema", "input_contract", "derivation_rules_version",
        "entry_step", "answer_step", "verify_through",
        "verify_closed_steps", "minimum_steps", "task_nature", "requested_evidence",
        "delivery_target", "mode_intent", "semantic_payload_sha256",
        "source_sha256", "dag_sha256")}
    if receipt.get("receipt_sha256") != sha256_json(body):
        errors.append("ROUTE_RECEIPT_DIGEST_MISMATCH")
    for key in ("semantic_payload_sha256", "source_sha256"):
        if not _HEX64.fullmatch(str(receipt.get(key) or "")):
            errors.append(f"ROUTE_RECEIPT_{key.upper()}_INVALID")
    mode = receipt.get("mode_intent")
    if not isinstance(mode, Mapping) or mode.get("authority") not in {
            "PROGRAM_DEFAULT", "USER_EXPLICIT_ULTRA"}:
        errors.append("ROUTE_RECEIPT_MODE_INVALID")
    elif mode.get("authority") == "PROGRAM_DEFAULT":
        if set(mode) != {"authority", "request_digest", "ultra_match"}:
            errors.append("ROUTE_RECEIPT_MODE_SCHEMA_INVALID")
        if mode.get("ultra_match") is not False:
            errors.append("ROUTE_RECEIPT_UNREQUESTED_ULTRA")
    elif mode.get("authority") == "USER_EXPLICIT_ULTRA":
        if set(mode) != {
                "authority", "request_digest", "ultra_match",
                "evidence_sha256", "issuer_binding", "ultra_evidence"}:
            errors.append("ROUTE_RECEIPT_ULTRA_SCHEMA_INVALID")
        # Authority is a typed user evidence contract.  Recomputing the outer
        # receipt digest cannot turn arbitrary metadata into authorization.
        if mode.get("ultra_match") is not True:
            errors.append("ROUTE_RECEIPT_ULTRA_MATCH_REQUIRED")
        request_digest = mode.get("request_digest")
        evidence_digest = mode.get("evidence_sha256")
        if (not isinstance(request_digest, str)
                or not _HEX64.fullmatch(request_digest)):
            errors.append("ROUTE_RECEIPT_ULTRA_REQUEST_DIGEST_INVALID")
        if (not isinstance(evidence_digest, str)
                or not _HEX64.fullmatch(evidence_digest)):
            errors.append("ROUTE_RECEIPT_ULTRA_EVIDENCE_DIGEST_INVALID")
        if mode.get("issuer_binding") != _ULTRA_ISSUER_BINDING:
            errors.append("ROUTE_RECEIPT_ULTRA_ISSUER_UNBOUND")
        evidence = mode.get("ultra_evidence")
        typed = _typed_ultra_directive(evidence)
        if typed is None:
            errors.append("ROUTE_RECEIPT_ULTRA_EVIDENCE_INVALID")
        elif typed["evidence_sha256"] != evidence_digest:
            errors.append("ROUTE_RECEIPT_ULTRA_EVIDENCE_DIGEST_MISMATCH")
        elif typed.get("issuer_binding") != mode.get("issuer_binding"):
            errors.append("ROUTE_RECEIPT_ULTRA_ISSUER_MISMATCH")
        elif isinstance(evidence, Mapping):
            if evidence.get("request_digest") != request_digest:
                errors.append("ROUTE_RECEIPT_ULTRA_REQUEST_DIGEST_MISMATCH")
            ebody = dict(evidence)
            binding_digest = ebody.pop("evidence_binding_sha256", None)
            if binding_digest != sha256_json(ebody):
                errors.append("ROUTE_RECEIPT_ULTRA_BINDING_DIGEST_MISMATCH")
    return errors


def write_d1_pending(path: Path, *, route_receipt: Mapping[str, Any],
                     source_sha256: str, task_sha256: str | None = None) -> dict:
    """Publish the first D1 state before the canonical D1 invocation."""
    receipt = dict(route_receipt)
    errors = validate_route_receipt(receipt)
    if errors:
        raise ValueError("invalid route receipt: " + ", ".join(errors))
    if receipt.get("source_sha256") != source_sha256:
        raise ValueError("D1_PENDING_SOURCE_MISMATCH")
    body = {"schema": D1_ACTIVATION_SCHEMA, "status": D1_PENDING,
            "route_receipt_sha256": receipt["receipt_sha256"],
            "source_sha256": source_sha256}
    if task_sha256 is not None:
        body["task_sha256"] = str(task_sha256)
    return {**body, "activation_sha256": sha256_json(body)}


def activate_d1(*, pending: Mapping[str, Any], route_receipt: Mapping[str, Any],
                provenance: Mapping[str, Any], source_sha256: str,
                task_sha256: str | None = None,
                ldoc_root_handle: str | None = None,
                d1_gate: Mapping[str, Any] | None = None) -> dict:
    """Create a route-bound activation receipt after D1 emitted provenance."""
    route_errors = validate_route_receipt(route_receipt)
    if route_errors:
        raise ValueError("D1_ACTIVATION_ROUTE_INVALID: " + ", ".join(route_errors))
    if pending.get("status") != D1_PENDING:
        raise ValueError('D1_ACTIVATION_PENDING_MISSING' + f": activate_d1.pending.status={pending.get('status')!r}: requires {D1_PENDING!r}")
    if pending.get("route_receipt_sha256") != route_receipt.get("receipt_sha256"):
        raise ValueError("D1_ACTIVATION_ROUTE_MISMATCH")
    if pending.get("source_sha256") != source_sha256 or route_receipt.get("source_sha256") != source_sha256:
        raise ValueError("D1_ACTIVATION_SOURCE_MISMATCH")
    if not str(task_sha256 or "").strip():
        raise ValueError('D1_ACTIVATION_TASK_MISSING' + (": " + "activate_d1.task_sha256 argument must be nonempty"))
    if not str(ldoc_root_handle or "").strip():
        raise ValueError('D1_ACTIVATION_LDOC_ROOT_MISSING' + (": " + "activate_d1.ldoc_root_handle argument must be nonempty; no L-doc directory opened"))
    if pending.get("task_sha256") != str(task_sha256):
        raise ValueError("D1_ACTIVATION_TASK_MISMATCH")
    if (not isinstance(provenance, Mapping)
            or provenance.get("ran") is not True
            or not _HEX64.fullmatch(str(provenance.get("digest") or ""))):
        raise ValueError('D1_ACTIVATION_PROVENANCE_MISSING' + (": " + "activate_d1.provenance.ran must be True and provenance.digest must be a 64-character lowercase hex SHA256"))
    _validate_d1_gate(
        d1_gate, route_receipt=route_receipt, provenance=provenance,
        source_sha256=source_sha256, task_sha256=task_sha256,
        ldoc_root_handle=ldoc_root_handle)
    body = {"schema": D1_ACTIVATION_SCHEMA, "status": D1_ACTIVATED,
            "route_receipt_sha256": route_receipt["receipt_sha256"],
            "source_sha256": source_sha256,
            "d1_provenance_sha256": provenance["digest"],
            "d1_gate_sha256": d1_gate["gate_sha256"],
            "d1_gate": dict(d1_gate),
            "task_sha256": str(task_sha256),
            "ldoc_root_handle": str(ldoc_root_handle)}
    return {**body, "activation_sha256": sha256_json(body)}


def require_d1_activation(activation: Mapping[str, Any] | None,
                          route_receipt: Mapping[str, Any], *, after_d1: bool = True,
                          task_sha256: str | None = None,
                          ldoc_root_handle: str | None = None) -> None:
    """Fail closed on missing or foreign route/source activation."""
    if not after_d1:
        return
    route_errors = validate_route_receipt(route_receipt)
    if route_errors:
        raise ValueError("D1_ACTIVATION_ROUTE_INVALID: " + ", ".join(route_errors))
    if not isinstance(activation, Mapping) or activation.get("status") != D1_ACTIVATED:
        raise ValueError("D1_ACTIVATION_REQUIRED")
    required = {
        "schema", "status", "route_receipt_sha256", "source_sha256",
        "d1_provenance_sha256", "d1_gate_sha256", "d1_gate",
        "task_sha256", "ldoc_root_handle", "activation_sha256",
    }
    if set(activation) != required:
        raise ValueError("D1_ACTIVATION_SCHEMA_FIELDS_INVALID")
    if activation.get("schema") != D1_ACTIVATION_SCHEMA:
        raise ValueError("D1_ACTIVATION_SCHEMA_INVALID")
    if activation.get("route_receipt_sha256") != route_receipt.get("receipt_sha256"):
        raise ValueError("D1_ACTIVATION_ROUTE_MISMATCH")
    if activation.get("source_sha256") != route_receipt.get("source_sha256"):
        raise ValueError("D1_ACTIVATION_SOURCE_MISMATCH")
    if task_sha256 is not None and activation.get("task_sha256") != str(task_sha256):
        raise ValueError("D1_ACTIVATION_TASK_MISMATCH")
    if ldoc_root_handle is not None and activation.get("ldoc_root_handle") != str(ldoc_root_handle):
        raise ValueError("D1_ACTIVATION_LDOC_ROOT_MISMATCH")
    if (not _HEX64.fullmatch(str(activation.get("source_sha256") or ""))
            or not _HEX64.fullmatch(str(activation.get("d1_provenance_sha256") or ""))
            or not _HEX64.fullmatch(str(activation.get("d1_gate_sha256") or ""))):
        raise ValueError("D1_ACTIVATION_DIGEST_FIELD_INVALID")
    if not str(activation.get("task_sha256") or "").strip():
        raise ValueError('D1_ACTIVATION_TASK_MISSING' + (": " + "require_d1_activation.activation.task_sha256 must be nonempty"))
    if not str(activation.get("ldoc_root_handle") or "").strip():
        raise ValueError('D1_ACTIVATION_LDOC_ROOT_MISSING' + (": " + "require_d1_activation.activation.ldoc_root_handle must be nonempty; no L-doc directory opened"))
    gate = activation.get("d1_gate")
    provenance = {"ran": True, "digest": activation["d1_provenance_sha256"]}
    _validate_d1_gate(
        gate, route_receipt=route_receipt, provenance=provenance,
        source_sha256=activation["source_sha256"],
        task_sha256=activation["task_sha256"],
        ldoc_root_handle=activation["ldoc_root_handle"])
    if gate.get("gate_sha256") != activation["d1_gate_sha256"]:
        raise ValueError("D1_ACTIVATION_GATE_DIGEST_MISMATCH")
    body = {k: activation.get(k) for k in (
        "schema", "status", "route_receipt_sha256", "source_sha256",
        "d1_provenance_sha256", "d1_gate_sha256", "d1_gate", "task_sha256",
        "ldoc_root_handle")}
    if activation.get("activation_sha256") != sha256_json(body):
        raise ValueError("D1_ACTIVATION_DIGEST_MISMATCH")


def make_d1_gate(*, verdict: str, route_receipt: Mapping[str, Any],
                 provenance: Mapping[str, Any], source_sha256: str,
                 task_sha256: str, ldoc_root_handle: str,
                 invocation_id: str, report_sha256: str,
                 waiver_receipt: Mapping[str, Any] | None = None) -> dict:
    """Bind the current D1 gate verdict to every activation identity."""
    body = {
        "schema": D1_GATE_SCHEMA,
        "step": "D1",
        "verdict": str(verdict),
        "current_call": True,
        "invocation_id": str(invocation_id),
        "report_sha256": str(report_sha256),
        "route_receipt_sha256": str(route_receipt.get("receipt_sha256")),
        "source_sha256": str(source_sha256),
        "task_sha256": str(task_sha256),
        "ldoc_root_handle": str(ldoc_root_handle),
        "d1_provenance_sha256": str(provenance.get("digest") or ""),
        "waiver_receipt": dict(waiver_receipt) if waiver_receipt is not None else None,
    }
    return {**body, "gate_sha256": sha256_json(body)}


def _validate_d1_gate(gate: Mapping[str, Any] | None, *,
                      route_receipt: Mapping[str, Any],
                      provenance: Mapping[str, Any], source_sha256: str,
                      task_sha256: str | None, ldoc_root_handle: str | None) -> None:
    if not isinstance(gate, Mapping):
        raise ValueError('D1_ACTIVATION_GATE_MISSING' + (": " + "_validate_d1_gate.gate argument must be a current D1 gate object"))
    required = {
        "schema", "step", "verdict", "current_call", "invocation_id",
        "report_sha256", "route_receipt_sha256", "source_sha256", "task_sha256",
        "ldoc_root_handle", "d1_provenance_sha256", "waiver_receipt", "gate_sha256",
    }
    if set(gate) != required:
        raise ValueError("D1_ACTIVATION_GATE_SCHEMA_FIELDS_INVALID")
    if gate.get("schema") != D1_GATE_SCHEMA or gate.get("step") != "D1":
        raise ValueError("D1_ACTIVATION_GATE_INVALID")
    if (gate.get("verdict") not in D1_PASS_VERDICTS
            and gate.get("verdict") != "PASS_WITH_WAIVERS"):
        raise ValueError("D1_ACTIVATION_GATE_NOT_PASS")
    if gate.get("current_call") is not True:
        raise ValueError("D1_ACTIVATION_GATE_NOT_CURRENT")
    invocation_id = gate.get("invocation_id")
    if not isinstance(invocation_id, str) or not _INVOCATION_ID.fullmatch(invocation_id):
        raise ValueError("D1_ACTIVATION_GATE_INVOCATION_INVALID")
    if not _HEX64.fullmatch(str(gate.get("report_sha256") or "")):
        raise ValueError("D1_ACTIVATION_GATE_REPORT_DIGEST_INVALID")
    if not _HEX64.fullmatch(str(gate.get("route_receipt_sha256") or "")):
        raise ValueError("D1_ACTIVATION_GATE_ROUTE_DIGEST_INVALID")
    if not _HEX64.fullmatch(str(gate.get("source_sha256") or "")):
        raise ValueError("D1_ACTIVATION_GATE_SOURCE_DIGEST_INVALID")
    if not str(gate.get("task_sha256") or "").strip():
        raise ValueError('D1_ACTIVATION_GATE_TASK_MISSING' + (": " + "_validate_d1_gate.gate.task_sha256 must be nonempty"))
    if not str(gate.get("ldoc_root_handle") or "").strip():
        raise ValueError('D1_ACTIVATION_GATE_LDOC_ROOT_MISSING' + (": " + "_validate_d1_gate.gate.ldoc_root_handle must be nonempty; no L-doc directory opened"))
    if not _HEX64.fullmatch(str(gate.get("d1_provenance_sha256") or "")):
        raise ValueError("D1_ACTIVATION_GATE_PROVENANCE_DIGEST_INVALID")
    if not _HEX64.fullmatch(str(gate.get("gate_sha256") or "")):
        raise ValueError("D1_ACTIVATION_GATE_DIGEST_INVALID")
    checks = {
        "route_receipt_sha256": route_receipt.get("receipt_sha256"),
        "source_sha256": source_sha256,
        "task_sha256": str(task_sha256),
        "ldoc_root_handle": str(ldoc_root_handle),
        "d1_provenance_sha256": provenance.get("digest"),
    }
    for key, expected in checks.items():
        if gate.get(key) != expected:
            raise ValueError(f"D1_ACTIVATION_GATE_{key.upper()}_MISMATCH")
    if gate.get("verdict") == "PASS_WITH_WAIVERS":
        waiver = gate.get("waiver_receipt")
        if not isinstance(waiver, Mapping):
            raise ValueError('D1_ACTIVATION_WAIVER_MISSING' + (": " + "_validate_d1_gate.gate.waiver_receipt must be an object for PASS_WITH_WAIVERS"))
        _validate_d1_waiver(
            waiver, route_receipt=route_receipt, source_sha256=source_sha256,
            task_sha256=task_sha256, ldoc_root_handle=ldoc_root_handle,
            gate=gate)
    body = {k: gate.get(k) for k in (
        "schema", "step", "verdict", "current_call", "invocation_id",
        "report_sha256", "route_receipt_sha256", "source_sha256", "task_sha256",
        "ldoc_root_handle", "d1_provenance_sha256", "waiver_receipt")}
    if gate.get("gate_sha256") != sha256_json(body):
        raise ValueError("D1_ACTIVATION_GATE_DIGEST_MISMATCH")


def make_d1_waiver(*, route_receipt: Mapping[str, Any], source_sha256: str,
                   task_sha256: str, ldoc_root_handle: str,
                   invocation_id: str, report_sha256: str,
                   authorized_by: str, expires_at: float,
                   reason: str) -> dict:
    """Reject self-issued waivers until a trusted policy producer exists.

    The current main tree has no D1 policy authority artifact.  A caller
    supplied ``authorized_by`` string is therefore only an assertion, not an
    authorization, and must never activate ``PASS_WITH_WAIVERS``.
    """
    raise NotImplementedError("D1_PWW_POLICY_PRODUCER_UNAVAILABLE")


def _validate_d1_waiver(waiver: Mapping[str, Any], *,
                        route_receipt: Mapping[str, Any], source_sha256: str,
                        task_sha256: str | None, ldoc_root_handle: str | None,
                        gate: Mapping[str, Any]) -> None:
    # Do not turn a report's free-form waiver text into policy.  A future
    # trusted producer must be integrated here with a signed/current artifact
    # and all of the bindings below; none exists on current main.
    raise ValueError("D1_PWW_POLICY_PRODUCER_UNAVAILABLE")


def admit_canonical_step(*, step: str, pending: Mapping[str, Any] | None,
                         activation: Mapping[str, Any] | None,
                         route_receipt: Mapping[str, Any],
                         task_sha256: str | None = None,
                         source_sha256: str | None = None,
                         ldoc_root_handle: str | None = None) -> str:
    """Admission boundary used by the fixed runner/coordinator.

    ``D1_ENTRY_PENDING`` can launch exactly D1.  Every later step requires a
    matching activation receipt and therefore current L-doc provenance.
    """
    step = str(step)
    dag = canonical_dag()
    if step not in dag["steps"]:
        raise ValueError("ROUTE_STEP_UNKNOWN")
    if step == "D1":
        if not isinstance(pending, Mapping) or pending.get("status") != D1_PENDING:
            raise ValueError("D1_ENTRY_PENDING_REQUIRED")
        if pending.get("route_receipt_sha256") != route_receipt.get("receipt_sha256"):
            raise ValueError("D1_PENDING_ROUTE_MISMATCH")
        if source_sha256 is not None and pending.get("source_sha256") != source_sha256:
            raise ValueError("D1_PENDING_SOURCE_MISMATCH")
        if task_sha256 is not None and pending.get("task_sha256") != str(task_sha256):
            raise ValueError("D1_PENDING_TASK_MISMATCH")
        return D1_PENDING
    require_d1_activation(
        activation, route_receipt, task_sha256=task_sha256,
        ldoc_root_handle=ldoc_root_handle)
    if source_sha256 is not None and activation.get("source_sha256") != source_sha256:
        raise ValueError("D1_ACTIVATION_SOURCE_MISMATCH")
    return D1_ACTIVATED


def admit_route_closure(*, pending: Mapping[str, Any],
                        activation: Mapping[str, Any],
                        route_receipt: Mapping[str, Any],
                        task_sha256: str, source_sha256: str,
                        ldoc_root_handle: str) -> list[str]:
    """Admit every trusted closure member in canonical order.

    This is deliberately separate from the scalar runner exit: a receipt that
    claims only Step 1 cannot hide Step 4 or any other table-derived proof
    obligation, and each admitted member crosses the same D1 activation gate.
    """
    errors = validate_route_receipt(route_receipt)
    if errors:
        raise ValueError("ROUTE_RECEIPT_INVALID: " + ", ".join(errors))
    dag = canonical_dag()
    admitted = []
    for step in route_receipt["verify_closed_steps"]:
        admit_canonical_step(
            step=step, pending=pending, activation=activation,
            route_receipt=route_receipt, task_sha256=task_sha256,
            source_sha256=source_sha256, ldoc_root_handle=ldoc_root_handle)
        admitted.append(step)
    if admitted != [step for step in dag["steps"]
                    if step in route_receipt["verify_closed_steps"]]:
        raise ValueError("ROUTE_CLOSURE_ADMISSION_ORDER_INVALID")
    return admitted
