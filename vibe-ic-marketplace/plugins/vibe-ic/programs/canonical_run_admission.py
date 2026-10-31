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
import stat
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


def _strict_program_digest(
        paths: Iterable[Path]) -> tuple[str, list[tuple[Path, str]]]:
    """Bind canonical program bytes once and report unavailable members.

    Opening with ``O_NOFOLLOW`` and hashing the opened regular file makes the
    availability decision and admitted digest one snapshot.  A caller must not
    preflight these paths and then ask :func:`build_identity` to read them a
    second time: that check-to-use gap can admit an ``UNREADABLE`` placeholder.
    """
    paths = tuple(Path(os.path.abspath(path)) for path in paths)
    source_root = (Path(os.path.commonpath([str(path.parent) for path in paths]))
                   if paths else None)
    rows: list[tuple[str, str]] = []
    unavailable: list[tuple[Path, str]] = []
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    nonblock = getattr(os, "O_NONBLOCK", 0)
    for path in paths:
        reason: Optional[str] = None
        digest: Optional[str] = None
        fd: Optional[int] = None
        if path.is_symlink():
            reason = "symlink"
        else:
            try:
                # A FIFO opened read-only blocks before fstat() can reject it.
                # Nonblocking acquisition lets the descriptor type decide;
                # it has no effect on reads from an ordinary regular file.
                fd = os.open(path, os.O_RDONLY | nofollow | nonblock)
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    reason = "not-regular"
                else:
                    with os.fdopen(fd, "rb") as handle:
                        fd = None
                        digest = _sha256_bytes(handle.read())
            except FileNotFoundError:
                reason = "missing"
            except OSError:
                reason = "unreadable"
            finally:
                if fd is not None:
                    os.close(fd)
        relative = path.relative_to(source_root).as_posix()
        if reason is not None:
            unavailable.append((path, reason))
            digest = "UNAVAILABLE:" + reason
        rows.append((relative, digest))
    return (_sha256_bytes(json.dumps(rows, sort_keys=True).encode("utf-8")),
            unavailable)


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


def _phase2_step1_judgement_binding(project: Path) -> Optional[Dict[str, Any]]:
    """Return one current, checker-approved Step-1 review binding.

    Reports remain excluded from the general admission identity.  This one
    fixed-path receipt is different: it can buy exactly one Phase-2 re-entry
    only after the existing signed-judgement consumer accepts it over the
    current Step-1 subject bytes.  Invalid or stale receipts are therefore
    indistinguishable from an absent receipt for admission purposes.
    """
    import ai_signed_judgement as judgement

    accepted, detail = judgement.check(project, "1")
    prefix = "signed judgement bound to evidence sha256:"
    if not accepted or not detail.startswith(prefix):
        return None

    receipt_path = project / "reports/audit/ai_judgements/1.json"
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    fd: Optional[int] = None
    try:
        if receipt_path.is_symlink():
            return None
        fd = os.open(receipt_path, os.O_RDONLY | nofollow)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        with os.fdopen(fd, "rb") as handle:
            fd = None
            receipt_bytes = handle.read()
        receipt = json.loads(receipt_bytes)
    except (OSError, ValueError, TypeError):
        return None
    finally:
        if fd is not None:
            os.close(fd)
    if not isinstance(receipt, dict):
        return None

    subjects: list[dict[str, str]] = []
    evidence_digest = hashlib.sha256()
    try:
        for path in judgement.evidence(project, "1"):
            rel = path.relative_to(project).as_posix()
            data = path.read_bytes()
            encoded_rel = rel.encode()
            evidence_digest.update(len(encoded_rel).to_bytes(8, "big"))
            evidence_digest.update(encoded_rel)
            evidence_digest.update(len(data).to_bytes(8, "big"))
            evidence_digest.update(data)
            subjects.append({"path": rel, "sha256": _sha256_bytes(data)})
    except (OSError, ValueError):
        return None
    evidence_sha256 = evidence_digest.hexdigest() if subjects else None
    if not evidence_sha256 or detail != prefix + evidence_sha256:
        return None
    if not (receipt.get("schema") == judgement.SCHEMA
            and receipt.get("step_id") == "1"
            and receipt.get("evidence_sha256") == evidence_sha256
            and receipt.get("verdict") == "PASS"
            and isinstance(receipt.get("signed_by"), str)
            and receipt["signed_by"].strip()
            and isinstance(receipt.get("judgement"), str)
            and receipt["judgement"].strip()):
        return None
    return {
        "schema": "vibeic.canonical-signed-judgement-binding.v1",
        "step_id": "1",
        "receipt_path": "reports/audit/ai_judgements/1.json",
        "receipt_sha256": _sha256_bytes(receipt_bytes),
        "evidence_sha256": evidence_sha256,
        "subject_count": len(subjects),
        "subjects": subjects,
    }


def _phase2_reset_judgement_binding(project: Path) -> Optional[Dict[str, Any]]:
    """Bind a current reset-role decision only after its native consumer accepts it."""
    import ai_signed_judgement as judgement
    path = project / "reports/audit/ai_judgements/3.json"
    try:
        if path.is_symlink():
            return None
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                return None
            before = handle.read()
        receipt = json.loads(before)
        accepted, _ = judgement.check(project, "3")
        request = judgement.reset_role_request(project)
        if (not accepted or path.is_symlink() or path.read_bytes() != before
                or not isinstance(receipt, dict)
                or any(not request.get(k) or request[k] != receipt.get(k)
                       for k in ("evidence_sha256", "netlist_sha256"))):
            return None
        return {"receipt_sha256": _sha256_bytes(before),
                "evidence_sha256": request["evidence_sha256"],
                "netlist_sha256": request["netlist_sha256"]}
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _rtl_snapshot_transport_isolatable(project: Path) -> bool:
    """The existing RTL snapshot guard's condition, not report contents.

    Never follow directory links or hash output payloads. Retargeting unsafe
    links and ordinary report churn cannot manufacture distinct retry inputs.
    The producer still checks its actual isolated snapshot before publication.
    """
    from design_one_shot_runner import _symlink_escapes_tree

    def unreadable(error):
        raise error

    try:
        for parent, directories, files in os.walk(project, followlinks=False, onerror=unreadable):
            for name in directories + files:
                path = Path(parent) / name
                if path.is_symlink() and _symlink_escapes_tree(
                        path.relative_to(project).as_posix(), os.readlink(path)):
                    return False
    except OSError:
        return False
    return True


def build_identity(project: Path, span: str, *, container_image: str,
                   config: Dict[str, Any], program_paths: Iterable[Path],
                   program_source_sha256: Optional[str] = None) -> Dict[str, Any]:
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
            "input/constraints", "phase3/librelane_switch.json",
        )),
        "phase1_receipt_sha256": phase1_receipt,
        "phase3_input_sha256": (_phase3_input_digest(project)
                                if span == "phase3" else None),
        "program_source_sha256": (program_source_sha256
                                  if program_source_sha256 is not None
                                  else _program_digest(program_paths)),
        "container_image": container_image or "IMAGE_UNAVAILABLE",
        "dispatch_config": config,
    }
    if span == "phase2":
        if config.get("entry_step") in (None, "1", "rtl_gen"):
            identity["rtl_snapshot_transport_isolatable"] = _rtl_snapshot_transport_isolatable(project)
        judgement_binding = _phase2_step1_judgement_binding(project)
        if judgement_binding is not None:
            identity["current_consumer_evidence_bindings"] = {
                "step1_signed_judgement": judgement_binding,
            }
        reset_binding = _phase2_reset_judgement_binding(project)
        if reset_binding is not None:
            identity.setdefault("current_consumer_evidence_bindings", {})[
                "reset_role_signed_judgement"] = reset_binding
        # professional_tb_gen reads this persistent authored source beside
        # its regenerated bundle. Hash that exact input name, never the
        # sim_professional subtree (JUnit, waves and generated TBs are outputs).
        hooks = tuple(str(path.relative_to(project)) for path in sorted(
            (project / "phase2/stage1/sim_professional").glob(
                "*/expert_reference_tb.py")) if path.is_file())
        if hooks:
            identity["authored_simulation_input_sha256"] = _tree_digest(project, hooks)
        # The generic full-stack consumer selects the first sorted oracle.
        # An authored handoff is an input; its reports, unselected alternatives
        # and the two built-in generators' marked outputs cannot buy a retry.
        from _path_layout import sim_full_stack_dir
        oracles = sorted(sim_full_stack_dir(project).glob("tb_*_oracle.v"))
        if oracles and oracles[0].is_file():
            selected = oracles[0]
            header = selected.read_text(errors="replace").splitlines()[:4]
            generated = any(line.startswith("// Auto-generated by " + emitter + " ")
                            for line in header
                            for emitter in ("oracle_tb_gen", "arith_oracle_tb_gen"))
            if not generated:
                identity["authored_full_stack_oracle_input_sha256"] = _tree_digest(
                    project, (str(selected.relative_to(project)),))
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
        programs_dir / "canonical_run_admission.py",
        # Source-owned row selection/projection is consumed before native
        # dispatch; its repair must not reuse the broken owner's identity.
        programs_dir / "flow109.py",
        programs_dir / "phase3_one_shot_runner.py",
        # Step 13 executes this producer directly.  Its source bytes must reopen
        # a Phase-2 span just like the runner that dispatches it; otherwise a
        # repaired LEC consumer is refused as duplicate work under the identity
        # of the broken producer generation.
        programs_dir / "lec_run.py",
        programs_dir / "librelane_contract.py",
        # The canonical runners delegate Default/Ultra dispatch and frontend
        # worker execution through these modules.  A change there must reopen
        # an expensive span; otherwise the admission ledger can reject a real
        # producer fix as duplicate work.
        programs_dir / "execution_policy.py",
        programs_dir / "execution_modes.py",
        programs_dir / "execution_frontend_providers.py",
        programs_dir / "execution_frontend_worker.py",
        # Phase 2 executes this producer directly for retained RTL refresh.
        programs_dir / "serial_parallel_mul_synth.py",
        programs_dir / "execution_backend_producers.py",
        programs_dir / "drv_capture_plan.py",
        programs_dir / "drv_signoff_capture.py",
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
    paths = canonical_program_paths(programs_dir)
    program_digest, unavailable = _strict_program_digest(paths)
    if span == "phase2" and os.environ.get("VIBEIC_LIBRELANE_LOCAL_ATTESTATION"):
        import librelane_contract
        try:
            attested = librelane_contract.local_image_attestation()
            fields = ("auto_remove", "network_mode", "memory", "memory_swap")
            if type(attested.get("auto_remove")) is not bool:
                raise ValueError("missing attested AutoRemove")
            runtime = {field: attested[field] for field in fields}
        except (librelane_contract.Refusal, KeyError, ValueError) as exc:
            identity = build_identity(project, span, container_image=image_identity(container),
                                      config=config, program_paths=paths,
                                      program_source_sha256=program_digest)
            return Admission(False, "LOCAL_RUNTIME_UNATTESTED", identity_sha256(identity),
                             identity, str(exc))
        config = {**config, "local_runtime_conditions": runtime}
    if unavailable:
        identity = build_identity(
            project, span, container_image=image_identity(container),
            config=config, program_paths=paths,
            program_source_sha256=program_digest)
        root = Path(programs_dir).resolve().parent
        detail = ", ".join(
            f"{path.relative_to(root)} ({reason})"
            for path, reason in unavailable)
        return Admission(
            False, "CANONICAL_PROGRAM_SOURCE_UNAVAILABLE",
            identity_sha256(identity), identity,
            "expected canonical program source is unavailable: " + detail)
    return admit(project, span, container_image=image_identity(container),
                 config=config, program_paths=paths,
                 program_source_sha256=program_digest)


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
          config: Dict[str, Any], program_paths: Iterable[Path],
          program_source_sha256: Optional[str] = None) -> Admission:
    identity = build_identity(project, span, container_image=container_image,
                              config=config, program_paths=program_paths,
                              program_source_sha256=program_source_sha256)
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
