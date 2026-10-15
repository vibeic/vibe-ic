#!/usr/bin/env python3
"""Persistent admission for expensive canonical Phase-2/Phase-3 runs.

This is deliberately separate from :mod:`loop_admission_guard`: that module
deduplicates *parameter proposals in one Python search session*.  This module
deduplicates an expensive canonical design span across later invocations of the
same project.  It never changes a design verdict; it only refuses to spend the
same P2/P3 compute twice when no named input, receipt, program, image or
measurement configuration changed.

The ledger is runtime bookkeeping, not a design input.  It lives under the
project's ``.vibeic-state`` directory, which ``design_input_digest`` explicitly
excludes.  A corrupt/unlockable ledger is a named, fail-closed refusal rather
than an invitation to repeat an unprovable run.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

# This module is both imported by the phase runners and independently loaded by
# the hygiene program inventory.  The latter can execute it from an arbitrary
# working directory (and with ``-I``), where Python does not promise that this
# file's directory remains on ``sys.path``.  Keep the explicit sibling lookup
# before either sibling import; a missing sibling must still fail normally.
_PROGRAMS_DIR = str(Path(__file__).resolve().parent)
if _PROGRAMS_DIR not in sys.path:
    sys.path.insert(0, _PROGRAMS_DIR)

import emit_attestation
import _eda_pin


STATE_DIR = ".vibeic-state"
LEDGER_NAME = "canonical-run-admission-v1.jsonl"
DELEGATION_ENV = "VIBE_IC_CANONICAL_ADMISSION_TOKEN"
SCHEMA = 1


@dataclass(frozen=True)
class Admission:
    admitted: bool
    reason: str
    identity_sha256: str
    identity: Dict[str, Any]
    detail: str = ""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_digest(path: Path) -> Optional[str]:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError:
        return None


def _tree_digest(project: Path, relatives: Iterable[str]) -> str:
    """Digest only canonical source inputs, never generated run outputs.

    ``reports/`` and PnR outputs deliberately do not belong here: a report
    rewrite must not masquerade as a source edit that buys another expensive
    run.  The Phase-1 receipt and P3 input artifact are separately bound below.
    """
    rows: list[tuple[str, str]] = []
    for rel in relatives:
        root = project / rel
        if root.is_file():
            digest = _file_digest(root)
            if digest is not None:
                rows.append((rel, digest))
        elif root.is_dir():
            for child in sorted(p for p in root.rglob("*") if p.is_file()):
                digest = _file_digest(child)
                if digest is not None:
                    rows.append((str(child.relative_to(project)), digest))
    h = hashlib.sha256()
    h.update(b"canonical-run-source/v1\n")
    for rel, digest in rows:
        h.update(rel.encode("utf-8", "surrogateescape"))
        h.update(b"\0")
        h.update(digest.encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()


def _program_digest(paths: Iterable[Path]) -> str:
    paths = tuple(Path(os.path.abspath(path)) for path in paths)
    # Preserve source locations within the shared source root, without binding
    # admission to the absolute checkout directory.  Basenames alone lose
    # package moves when two sources share a name and identical bytes.
    source_root = (Path(os.path.commonpath([str(path.parent) for path in paths]))
                   if paths else None)
    rows: list[tuple[str, str]] = []
    for path in paths:
        digest = _file_digest(path)
        rows.append((path.relative_to(source_root).as_posix(), digest or "UNREADABLE"))
    return _sha256_bytes(json.dumps(rows, sort_keys=True).encode("utf-8"))


def _phase3_input_digest(project: Path) -> str:
    # P3 must reopen when Phase-2's actual consumed netlist/constraints moved,
    # not merely because an old report was regenerated.
    return _tree_digest(project, (
        "phase2/stage1/rtl",
        "phase2/stage2/synth",
        "phase2/stage2/constraints",
        "input/constraints",
    ))


def _subject_id(project: Path) -> str:
    manifest = project / "SOURCE_MANIFEST.md"
    digest = _file_digest(manifest)
    # A manifest is the portable benchmark subject identity when supplied; the
    # project basename is only a local fallback for ordinary non-benchmark use.
    return f"source-manifest:{digest}" if digest else f"project:{project.name}"


def build_identity(project: Path, span: str, *, container_image: str,
                   config: Dict[str, Any], program_paths: Iterable[Path]) -> Dict[str, Any]:
    """Return the complete value identity for one expensive span.

    An absent image/receipt is represented by a named value rather than guessed
    away.  It can still be deduplicated, but never states that a measurement had
    a known image or canonical Phase-1 provenance.
    """
    project = Path(project).resolve()
    receipt = emit_attestation.phase1_provenance(project)
    phase1_receipt = receipt.get("digest") if receipt.get("ran") else "NO_PHASE1_RECEIPT"
    identity = {
        "schema": SCHEMA,
        "subject_id": _subject_id(project),
        "span": span,
        "source_input_sha256": _tree_digest(project, (
            # Phase-2 is allowed to start from canonical authored RTL or an
            # authored SDC already staged for its consumers.  They are design
            # inputs, not reports: an RTL/constraint repair must therefore
            # reopen admission, while regenerated reports and this ledger may
            # never do so.
            "input", "phase1/input_doc", "SOURCE_MANIFEST.md",
            "phase2/stage1/rtl", "phase2/stage2/constraints",
            "input/constraints",
        )),
        "phase1_receipt_sha256": phase1_receipt,
        "phase3_input_sha256": (_phase3_input_digest(project)
                                if span == "phase3" else None),
        "program_source_sha256": _program_digest(program_paths),
        "container_image": container_image or "IMAGE_UNAVAILABLE",
        "dispatch_config": config,
    }
    if span == "phase2":
        # professional_tb_gen reads this persistent authored source beside
        # its regenerated bundle. Hash that exact input name, never the
        # sim_professional subtree (JUnit, waves and generated TBs are outputs).
        hooks = tuple(str(path.relative_to(project)) for path in sorted(
            (project / "phase2/stage1/sim_professional").glob(
                "*/expert_reference_tb.py")) if path.is_file())
        if hooks:
            identity["authored_simulation_input_sha256"] = _tree_digest(project, hooks)
        # Reuse the per-case producer's preservation rule and consumer scope;
        # generated scaffolds and simulation reports cannot buy another run.
        from testbench_gen import authored_unit_tb_paths
        cases = tuple(str(path.relative_to(project))
                      for path in authored_unit_tb_paths(project))
        if cases:
            identity["authored_unit_tb_input_sha256"] = _tree_digest(project, cases)
    return identity


def identity_sha256(identity: Dict[str, Any]) -> str:
    return _sha256_bytes(json.dumps(identity, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8"))


def ledger_path(project: Path) -> Path:
    return Path(project) / STATE_DIR / LEDGER_NAME


def canonical_program_paths(programs_dir: Path) -> tuple[Path, ...]:
    """The shared P2/P3 program contract, identical at every entry point."""
    programs_dir = Path(programs_dir).resolve()
    from librelane_contract import PLUGIN_HOST_MODULES

    # Native step implementations are executable inputs just like the runners.
    # Bind their source population too: adding/deleting a plugin source must
    # reopen admission, while bytecode, reports and other generated outputs do not.
    plugin_root = programs_dir / "librelane_plugins"
    plugin_sources = tuple(sorted(
        path for path in plugin_root.rglob("*")
        if path.is_file() and path.suffix in {".py", ".tcl", ".drc"}
        and "__pycache__" not in path.relative_to(plugin_root).parts
    ))
    return (
        programs_dir / "vibe_ic_one_shot_runner.py",
        programs_dir / "design_one_shot_runner.py",
        programs_dir / "phase3_one_shot_runner.py",
        programs_dir / "librelane_contract.py",
        # The canonical runners delegate Default/Ultra dispatch and frontend
        # worker execution through these modules.  A change there must reopen
        # an expensive span; otherwise the admission ledger can reject a real
        # producer fix as duplicate work.
        programs_dir / "execution_policy.py",
        programs_dir / "execution_modes.py",
        programs_dir / "execution_frontend_providers.py",
        programs_dir / "execution_frontend_worker.py",
        programs_dir / "execution_backend_producers.py",
        *(programs_dir / name for name in PLUGIN_HOST_MODULES),
        *plugin_sources,
        programs_dir.parent / "flow" / "phase1_phase2_phase3.yaml",
    )


def image_identity(container: str) -> str:
    """Return a stable actual-image value, including named absence."""
    digest, why_not = _eda_pin.container_image_digest(container)
    return digest or f"IMAGE_UNAVAILABLE:{why_not}"


def admit_span(project: Path, span: str, programs_dir: Path,
               container: str, config: Dict[str, Any]) -> Admission:
    """Convenience entry point so all runners build the same identity."""
    return admit(project, span, container_image=image_identity(container),
                 config=config, program_paths=canonical_program_paths(programs_dir))


def delegated(identity_hash: str) -> bool:
    """True only for a parent runner's same-span delegated child."""
    return os.environ.get(DELEGATION_ENV, "") == identity_hash


def child_env(identity_hash: str, base: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    env = dict(os.environ if base is None else base)
    env[DELEGATION_ENV] = identity_hash
    return env


def _read_ledger(handle) -> list[Dict[str, Any]]:
    handle.seek(0)
    rows: list[Dict[str, Any]] = []
    for line_no, raw in enumerate(handle, 1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"ledger line {line_no} is not JSON: {exc.msg}") from exc
        if not isinstance(row, dict) or not isinstance(row.get("identity_sha256"), str):
            raise ValueError(f"ledger line {line_no} lacks identity_sha256")
        rows.append(row)
    return rows


def admit(project: Path, span: str, *, container_image: str,
          config: Dict[str, Any], program_paths: Iterable[Path]) -> Admission:
    identity = build_identity(project, span, container_image=container_image,
                              config=config, program_paths=program_paths)
    fingerprint = identity_sha256(identity)
    if delegated(fingerprint):
        return Admission(True, "DELEGATED_PARENT_ADMISSION", fingerprint, identity)

    path = ledger_path(project)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+", encoding="utf-8") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                return Admission(False, "ADMISSION_LEDGER_LOCK_UNAVAILABLE",
                                 fingerprint, identity, str(exc))
            try:
                prior = _read_ledger(handle)
            except ValueError as exc:
                return Admission(False, "ADMISSION_LEDGER_CORRUPT",
                                 fingerprint, identity, str(exc))
            for row in prior:
                if row["identity_sha256"] == fingerprint:
                    return Admission(False, "DUPLICATE_NO_NEW_EVIDENCE",
                                     fingerprint, identity,
                                     "same canonical source/receipt/program/image/config "
                                     "already admitted")
            record = {
                "schema": SCHEMA,
                "identity_sha256": fingerprint,
                "identity": identity,
                "status": "ADMITTED",
                "admitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "pid": os.getpid(),
            }
            handle.seek(0, os.SEEK_END)
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            return Admission(True, "ADMITTED", fingerprint, identity)
    except OSError as exc:
        return Admission(False, "ADMISSION_LEDGER_UNAVAILABLE", fingerprint,
                         identity, str(exc))
