"""Invocation-bound evidence for the canonical Default producer path.

Default mode deliberately bypasses the Ultra ``Registry``/``Controller``.  The
canonical runner still needs a small, typed receipt around each native producer
call so a later consumer can tell which invocation produced the bytes it read.
This module records that boundary only; it does not select tools, run gates, or
change producer return values.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

SCHEMA = "vibe-ic/default-invocation-evidence/1"
_RECEIPT_REL = "reports/execution/{invocation}/default/invocation-evidence.jsonl"


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _real(path: Path) -> bool:
    try:
        # The existing flow intentionally exposes canonical outputs through
        # step-folder symlinks.  Accept a link only when its target is a real
        # file; dangling links remain absent.
        return path.is_file() and path.resolve().is_file()
    except (OSError, RuntimeError):
        return False


def _relative(project: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(project.resolve()).as_posix()
    except (OSError, RuntimeError, ValueError):
        return str(path)


def _qualname(producer: Any) -> str:
    module = getattr(producer, "__module__", "")
    name = getattr(producer, "__qualname__", getattr(producer, "__name__", type(producer).__name__))
    return f"{module}:{name}" if module else str(name)


def _status(result: Any) -> Optional[str]:
    value = getattr(result, "status", None)
    if value is None and isinstance(result, Mapping):
        value = result.get("status")
    if value is None and isinstance(result, (list, tuple)):
        values = [_status(item) for item in result]
        if any(item == "FAIL" for item in values):
            return "FAIL"
        if any(item == "PASS" for item in values):
            return "PASS"
        if values:
            return next((item for item in values if item), None)
    return str(value) if value is not None else None


def _runtime_context(project: Path) -> Optional[dict[str, str]]:
    """Read the live authority metadata, returning None for unissued calls."""
    try:
        import execution_policy as policy
        runtime = getattr(policy, "_ordinary_runtime", None)
        if not isinstance(runtime, dict):
            return None
        value = runtime.get("policy") or {}
        if value.get("mode") != "default":
            return None
        bound = Path(runtime["project"]).resolve()
        if bound != project.resolve():
            return None
        request = value.get("request_receipt") or {}
        route = runtime.get("route") or {}
        fields = {
            "invocation_id": request.get("invocation_id"),
            "request_digest": request.get("request_digest") or value.get("request_digest"),
            "route_digest": route.get("route_digest"),
            "source_sha": route.get("source_sha"),
            "project_digest": route.get("project_digest"),
        }
        if any(not isinstance(item, str) or not item for item in fields.values()):
            return None
        return fields
    except (ImportError, KeyError, OSError, RuntimeError, TypeError, ValueError):
        return None


def is_live_default(project: Path) -> bool:
    """Whether this process has an authority-issued Default runtime."""
    return _runtime_context(Path(project)) is not None


def _hash_paths(project: Path, paths: Sequence[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in sorted({str(item) for item in paths if item}):
        path = Path(raw)
        if not path.is_absolute():
            path = project / path
        if _real(path):
            result[_relative(project, path)] = _sha(path)
    return result


def _input_records(project: Path, inputs: Sequence[Any]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Keep every preflight state, including absent and unprobeable inputs."""
    records: list[dict[str, Any]] = []
    hashes: dict[str, str] = {}
    for item in inputs:
        if isinstance(item, Mapping):
            record = dict(item)
            raw = record.get("evidence")
        else:
            record = {"evidence": str(item)}
            raw = item
        exists = False
        if raw:
            path = Path(str(raw))
            if not path.is_absolute():
                path = project / path
            if _real(path):
                exists = True
                relative = _relative(project, path)
                digest = _sha(path)
                hashes[relative] = digest
                record["evidence"] = relative
                record["sha256"] = digest
        record.setdefault("state", "present" if exists else "absent" if raw else "unprobeable")
        record.setdefault("present", exists)
        records.append(record)
    return records, hashes


def declared_gate_programs(flow_steps: Sequence[str], flow_def: Optional[Path] = None) -> tuple[str, ...]:
    """Name the flow-declared consumers without executing them."""
    try:
        import _flow_yaml
        rows = (_flow_yaml.load(flow_def) if flow_def else _flow_yaml.load()).get("steps", ())
        by_id = {str(row.get("id")): row for row in rows}
    except (ImportError, OSError, TypeError, ValueError):
        return ()
    names: set[str] = set()
    for step in flow_steps:
        row = by_id.get(str(step), {})
        for name in row.get("programs") or ():
            names.add(str(name))
        # Some early rows only carry gate commands. Keep the command basename
        # as a declared consumer name; this is metadata, never an execution.
        def visit(value: Any) -> None:
            if isinstance(value, Mapping):
                for item in value.values():
                    visit(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    visit(item)
            elif isinstance(value, str) and value.strip():
                token = value.strip().split()[0]
                if token and token not in {".", "all", "any"}:
                    names.add(token)
        visit(row.get("gate"))
    return tuple(sorted(names))


def declared_outputs(flow_steps: Sequence[str], flow_def: Optional[Path] = None) -> tuple[str, ...]:
    """Return the required-output declarations for a canonical span."""
    try:
        import _flow_yaml
        rows = (_flow_yaml.load(flow_def) if flow_def else _flow_yaml.load()).get("steps", ())
        by_id = {str(row.get("id")): row for row in rows}
    except (ImportError, OSError, TypeError, ValueError):
        return ()
    values: list[str] = []
    for step in flow_steps:
        row = by_id.get(str(step), {})
        for item in row.get("required_outputs") or ():
            values.append(str(item))
    return tuple(values)


def _declared_output_matches(project: Path, patterns: Sequence[str]) -> tuple[dict[str, str], list[str]]:
    """Resolve outputs with the same glob semantics used by preflight."""
    try:
        import flow_compliance_check as compliance
    except ImportError:  # pragma: no cover - production imports the checker
        compliance = None
    paths: list[str] = []
    missing: list[str] = []
    for pattern in patterns:
        alternatives = [item.strip() for item in str(pattern).split(" OR ")]
        hits: list[str] = []
        for alternative in alternatives:
            if compliance is not None:
                hits = list(compliance._glob_first(project, alternative))
            else:
                hits = [_relative(project, item) for item in sorted(project.glob(alternative)) if _real(item)]
            if hits:
                break
        if hits:
            paths.extend(hits)
        else:
            missing.append(str(pattern))
    return _hash_paths(project, paths), missing


def _append(project: Path, invocation: str, entry: dict[str, Any]) -> Path:
    target = project / _RECEIPT_REL.format(invocation=invocation)
    target.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    with target.open("a", encoding="utf-8") as fh:
        fh.write(body + "\n")
    return target


def verify_record(project: Path, record: Mapping[str, Any]) -> tuple[bool, str]:
    """Verify the immutable input/output hashes in one recorded receipt."""
    try:
        if record.get("schema") != SCHEMA:
            return False, "schema"
        expected_digest = record.get("receipt_digest")
        body = {key: value for key, value in record.items() if key != "receipt_digest"}
        actual_digest = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if not isinstance(expected_digest, str) or expected_digest != actual_digest:
            return False, "receipt-digest"
        invocation = record.get("invocation_id")
        if (record.get("gate", {}).get("same_invocation") != invocation or
                record.get("consumer", {}).get("invocation_id") != invocation or
                record.get("consumer", {}).get("receipt_locator") !=
                _RECEIPT_REL.format(invocation=invocation) or
                record.get("gate", {}).get("receipt_locator") !=
                _RECEIPT_REL.format(invocation=invocation)):
            return False, "invocation-binding"
        for item in record.get("input_states") or ():
            if item.get("state") == "absent":
                return False, f"input:{item.get('path') or item.get('evidence')}"
        before = record.get("input_hashes") or {}
        for relative, expected in before.items():
            path = project / str(relative)
            if not _real(path) or _sha(path) != expected:
                return False, f"input:{relative}"
        outputs = record.get("output_hashes") or {}
        missing = record.get("missing_outputs") or []
        for relative, expected in outputs.items():
            path = project / str(relative)
            if not _real(path) or _sha(path) != expected:
                return False, f"output:{relative}"
        # An output absent at invocation cannot be treated as a successful
        # producer receipt later merely because a stale file appeared.
        if missing and record.get("producer_status") == "PASS":
            return False, "missing-output"
        return True, "ok"
    except (OSError, TypeError, ValueError):
        return False, "unreadable"


@dataclass
class Session:
    project: Path
    runner: str
    site: str
    flow_steps: tuple[str, ...]
    invocation: dict[str, str]
    producer: str
    declared_outputs: tuple[str, ...]
    input_hashes: dict[str, str]
    started_at: str
    output_before: dict[str, str]
    gate_programs: tuple[str, ...]
    input_states: tuple[dict[str, Any], ...]
    dispatch_path: str = "step_preflight.gate -> canonical producer"
    producer_kind: str = "canonical-native"

    def bind_dispatch(self, path: str, kind: str, producer: Any = None) -> None:
        self.dispatch_path = str(path)
        self.producer_kind = str(kind)
        if producer is not None:
            self.producer = _qualname(producer)

    def finish(self, result: Any, *, preflight: Any = None) -> dict[str, Any]:
        requested_status = _status(result) or "NOT_MEASURED"
        output_hashes, missing = _declared_output_matches(self.project, self.declared_outputs)
        if requested_status == "PASS" and (
                not self.declared_outputs or missing or output_hashes == self.output_before):
            status = "NOT_MEASURED"
            freshness_reason = ("OUTPUT_NOT_DECLARED" if not self.declared_outputs else
                                "OUTPUT_MISSING" if missing else "OUTPUT_UNCHANGED")
        else:
            status = requested_status
            freshness_reason = None
        identity = getattr(preflight, "identity", None) if preflight is not None else None
        gate = {
            "status": status,
            "preflight_verdict": getattr(preflight, "verdict", None),
            "identity": identity,
            "same_invocation": self.invocation["invocation_id"],
        }
        consumer_status = ("PASS" if status == "PASS" and identity == "confirmed"
                           else "NOT_MEASURED" if identity in (None, "not-applicable", "not-checked")
                           else str(identity))
        consumer = {
            "invocation_id": self.invocation["invocation_id"],
            "status": consumer_status,
            "declared_programs": list(self.gate_programs),
            "receipt_locator": _RECEIPT_REL.format(invocation=self.invocation["invocation_id"]),
            "source": "step_preflight._confirm_identity",
            "reason": ("required output identity confirmed by this invocation"
                       if consumer_status == "PASS" else
                       "canonical downstream gate must consume this locator before chain PASS"),
        }
        entry: dict[str, Any] = {
            "schema": SCHEMA,
            "invocation_id": self.invocation["invocation_id"],
            "request_digest": self.invocation["request_digest"],
            "route_digest": self.invocation["route_digest"],
            "source_sha": self.invocation["source_sha"],
            "project_digest": self.invocation["project_digest"],
            "mode": "default-mode",
            "runner": self.runner,
            "site": self.site,
            # A coarse native call may own several canonical rows. Preserve the
            # span exactly; never expand it into one fake invocation per row.
            "flow_steps": list(self.flow_steps),
            "producer": self.producer,
            "producer_kind": self.producer_kind,
            "dispatch_path": self.dispatch_path,
            "producer_result_status": requested_status,
            "producer_status_reason": freshness_reason,
            "started_at": self.started_at,
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "input_hashes": self.input_hashes,
            "input_states": list(self.input_states),
            "output_before": self.output_before,
            "output_hashes": output_hashes,
            "missing_outputs": missing,
            "producer_status": status,
            "gate": gate,
            "consumer": consumer,
            "chain_status": "PASS" if consumer_status == "PASS" else
                            ("FAIL" if status == "FAIL" else "NOT_MEASURED"),
            "declared_gate_programs": list(self.gate_programs),
            "receipt_kind": "canonical-producer-invocation",
        }
        entry["receipt_locator"] = _RECEIPT_REL.format(invocation=self.invocation["invocation_id"])
        entry["gate"]["receipt_locator"] = entry["receipt_locator"]
        body = dict(entry)
        entry["receipt_digest"] = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        try:
            _append(self.project, self.invocation["invocation_id"], entry)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Default invocation receipt write failed: {exc}") from exc
        ok, reason = verify_record(self.project, entry)
        if not ok:
            raise RuntimeError(f"Default invocation receipt verification failed: {reason}")
        return entry


def start(project: Path, runner: str, site: str, flow_steps: Sequence[str], *,
          producer: Any, inputs: Sequence[Any] = (), declared_outputs: Sequence[str] = (),
          gate_programs: Sequence[str] = (), invocation: Mapping[str, str]) -> Session:
    """Start a receipt from explicit, already-resolved invocation metadata."""
    required = ("invocation_id", "request_digest", "route_digest", "source_sha", "project_digest")
    if any(not isinstance(invocation.get(name), str) or not invocation.get(name) for name in required):
        raise ValueError("invocation metadata must be complete")
    project = Path(project).resolve()
    input_states, input_hashes = _input_records(project, inputs)
    output_before, _ = _declared_output_matches(project, declared_outputs)
    return Session(project, str(runner), str(site), tuple(str(item) for item in flow_steps),
                   {name: str(invocation[name]) for name in required}, _qualname(producer),
                   tuple(str(item) for item in declared_outputs), input_hashes,
                   time.strftime("%Y-%m-%dT%H:%M:%S%z"), output_before,
                   tuple(str(item) for item in gate_programs), tuple(input_states))


def start_from_runtime(project: Path, runner: str, site: str, flow_steps: Sequence[str], *,
                       producer: Any, inputs: Sequence[Mapping[str, Any]] = (),
                       declared_outputs: Sequence[str] = (), gate_programs: Sequence[str] = ()) -> Optional[Session]:
    context = _runtime_context(Path(project))
    if context is None:
        return None
    return start(Path(project), runner, site, flow_steps, producer=producer,
                 inputs=inputs, declared_outputs=declared_outputs, gate_programs=gate_programs,
                 invocation=context)
