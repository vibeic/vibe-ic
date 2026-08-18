"""rtl_provenance.py — provenance ledger for ``phase2/stage1/rtl/``.

Answers exactly ONE question for the runner:

    *Is there RTL in this project that the generator pipeline did not
    produce?*

Background — the destructive default it replaces
------------------------------------------------
``design_one_shot_runner.step_rtl_gen`` used to rename ``rtl/`` aside to
``rtl.pre_gen_backup/`` and regenerate on EVERY invocation, and the next
invocation ``rmtree``'d that aside before creating its own.  The aside
therefore survived exactly ONE re-run.  Two front-door re-runs over
hand-authored RTL destroyed it beyond recovery — silently, and with the
step still reporting PASS.

That is the normal path, not an error path: an author is *required*
whenever the deterministic generator cannot produce compiling RTL (the
generator emits, the ECO loop returns ``FAIL_ECO_INERT``, a human or an
agent authors the design by hand).  Re-running the front door then
deleted precisely the work that only existed because the generator had
failed.

The ledger
----------
After the runner produces RTL it records, beside ``rtl/``, the exact set
of RTL files it left behind and their SHA-256 digests.  Before the next
generation clobbers anything, :func:`classify` compares the current
``rtl/`` against that record:

``empty``      no RTL present and no validated non-empty ledger — generate
               freely.
``generated``  every present file matches the ledger, including a tree whose
               stamped files were all removed — the generator owns this tree;
               regeneration can be bound to the recorded digests.
``authored``   a file was added or its bytes changed since the runner
               last left the tree — someone authored here.
``unknown``    RTL is present but no ledger exists, so the generator
               cannot prove it produced this tree.

``authored`` and ``unknown`` both mean "do not clobber".  ``unknown`` is
deliberately fail-safe: an absent ledger is not evidence of ownership.

The classification is keyed on provenance ONLY.  It reads no IC class,
no ``ic_class.json``, no design name — a generator-produced tree and an
authored tree are distinguished by what is on disk, so the rule applies
uniformly to every design and every class.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = 1
LEDGER_NAME = "rtl.provenance.json"

#: Files the ledger tracks.  Everything a generator emits as RTL; any
#: other artefact dropped in ``rtl/`` is ignored so unrelated scratch
#: files never masquerade as authorship.
RTL_SUFFIXES = (".v", ".sv", ".vh", ".svh", ".vhd", ".vhdl")

#: Verdicts returned by :func:`classify`.
EMPTY = "empty"
GENERATED = "generated"
AUTHORED = "authored"
UNKNOWN = "unknown"

#: Verdicts that mean "there is work here this generator did not
#: produce — clobbering it destroys someone's authoring".
PRESERVE_VERDICTS = (AUTHORED, UNKNOWN)


def _rtl_dir(project: Path) -> Path:
    return Path(project) / "phase2" / "stage1" / "rtl"


def ledger_path(project: Path) -> Path:
    """The ledger lives BESIDE ``rtl/``, never inside it, so it is never
    itself mistaken for emitted RTL."""
    return _rtl_dir(project).parent / LEDGER_NAME


def iter_rtl_files(rtl_dir: Path) -> List[Path]:
    """Every RTL file under ``rtl/``, recursively, in stable order."""
    if not rtl_dir.is_dir():
        return []
    return sorted(
        (p for p in rtl_dir.rglob("*")
         if p.is_file() and p.suffix.lower() in RTL_SUFFIXES),
        key=lambda p: str(p),
    )


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _relmap(rtl_dir: Path) -> Dict[str, str]:
    """``{relative posix path: sha256}`` for the current ``rtl/``."""
    return {
        p.relative_to(rtl_dir).as_posix(): sha256_file(p)
        for p in iter_rtl_files(rtl_dir)
    }


def stamp(project: Path, generator: Optional[str] = None) -> Dict[str, Any]:
    """Record the current ``rtl/`` as generator-produced.

    Call this ONLY after the runner's own deterministic pipeline has
    written the tree.  Stamping a tree the runner did not produce would
    re-arm the very clobber this module exists to prevent.
    """
    project = Path(project)
    rtl_dir = _rtl_dir(project)
    payload: Dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "generator": generator,
        "stamped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": _relmap(rtl_dir),
    }
    lp = ledger_path(project)
    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload


def load_ledger(project: Path) -> Optional[Dict[str, Any]]:
    lp = ledger_path(project)
    # A provenance record is authority, not merely input data.  Following a
    # symlink here would let bytes outside the project assert ownership of the
    # live RTL tree.
    if lp.is_symlink() or not lp.is_file():
        return None
    try:
        data = json.loads(lp.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if (not isinstance(data, dict)
            or type(data.get("schema")) is not int
            or data.get("schema") != SCHEMA_VERSION):
        return None
    files = data.get("files")
    if not isinstance(files, dict):
        return None
    # stamp() can only produce normalized relative POSIX paths and lowercase
    # SHA-256 digests.  Enforce that exact shape before a removed-only ledger is
    # allowed to prove that a now-empty tree was generator-owned.
    for rel, digest in files.items():
        if (not isinstance(rel, str) or not rel
                or Path(rel).is_absolute()
                or Path(rel).as_posix() != rel
                or any(part in ("", ".", "..") for part in Path(rel).parts)
                or not isinstance(digest, str)
                or len(digest) != 64
                or any(ch not in "0123456789abcdef" for ch in digest)):
            return None
    return data


def classify(project: Path) -> Tuple[str, str, Dict[str, Any]]:
    """Classify the provenance of ``phase2/stage1/rtl/``.

    Returns ``(verdict, human_reason, evidence)``.  ``evidence`` names
    the specific files that drove the verdict so a refusal is
    actionable rather than an opaque "something changed".
    """
    project = Path(project)
    rtl_dir = _rtl_dir(project)
    current = _relmap(rtl_dir)

    lp = ledger_path(project)
    ledger_claim_present = lp.exists() or lp.is_symlink()
    ledger = load_ledger(project)
    if ledger is None:
        ledger_claim_present = (
            ledger_claim_present or lp.exists() or lp.is_symlink())
    if not current:
        recorded: Dict[str, str] = ((ledger or {}).get("files") or {})
        if recorded:
            # Deleting the last generated RTL file is the same provenance state
            # as deleting one of several: the surviving, validated ledger still
            # owns the absent paths.  Callers can now bind any restoration to the
            # recorded digest instead of mistaking the tree for never-generated
            # EMPTY state and emitting changed bytes unconditionally.
            removed = sorted(recorded)
            return (
                GENERATED,
                f"all {len(removed)} provenance-stamped RTL file(s) were "
                "removed; the validated generator ledger remains available "
                "for digest-bound restoration.",
                {"file_count": 0, "removed": removed,
                 "removed_digests": {rel: recorded[rel] for rel in removed},
                 "ledger_generator": ledger.get("generator"),
                 "ledger_stamped_at": ledger.get("stamped_at")},
            )
        if ledger is None and ledger_claim_present:
            return (
                UNKNOWN,
                f"rtl/ holds no RTL files, but provenance ledger "
                f"{LEDGER_NAME} is present and invalid or unreadable. It may "
                "describe a removed generated tree, so fresh generation is "
                "refused rather than bypassing its unavailable digests.",
                {"file_count": 0, "ledger_present": True,
                 "ledger_valid": False},
            )
        return (EMPTY, "rtl/ holds no RTL files — nothing to preserve.",
                {"file_count": 0})

    if ledger is None:
        return (
            UNKNOWN,
            f"rtl/ holds {len(current)} RTL file(s) but there is no "
            f"provenance ledger ({LEDGER_NAME}) recording this generator "
            f"as their producer — provenance cannot be established, so "
            f"the tree is treated as authored.",
            {"file_count": len(current),
             "files": sorted(current)[:20]},
        )

    recorded: Dict[str, str] = ledger.get("files") or {}
    added = sorted(set(current) - set(recorded))
    modified = sorted(f for f in (set(current) & set(recorded))
                      if current[f] != recorded[f])
    # A file the author DELETED is not authorship evidence: regeneration
    # restores it, so nothing is lost by regenerating.
    removed = sorted(set(recorded) - set(current))

    if added or modified:
        bits = []
        if added:
            bits.append(f"{len(added)} file(s) added ({', '.join(added[:5])}"
                        f"{'…' if len(added) > 5 else ''})")
        if modified:
            bits.append(f"{len(modified)} file(s) modified "
                        f"({', '.join(modified[:5])}"
                        f"{'…' if len(modified) > 5 else ''})")
        return (
            AUTHORED,
            "rtl/ diverges from the tree the generator last produced: "
            + "; ".join(bits) + ".",
            {"added": added, "modified": modified, "removed": removed,
             "file_count": len(current),
             "ledger_generator": ledger.get("generator"),
             "ledger_stamped_at": ledger.get("stamped_at")},
        )

    return (
        GENERATED,
        f"all {len(current)} RTL file(s) match the provenance ledger — "
        f"generator-produced, safe to regenerate.",
        {"file_count": len(current), "removed": removed,
         "removed_digests": {rel: recorded[rel] for rel in removed},
         "ledger_generator": ledger.get("generator"),
         "ledger_stamped_at": ledger.get("stamped_at")},
    )


def preserve(project: Path) -> Path:
    """Copy the current ``rtl/`` to a timestamped sibling that NOTHING
    reclaims, and return that path.

    Used only on the explicit-override path.  Unlike
    ``rtl.pre_gen_backup/`` — which the next run deletes — this
    directory is uniquely named per invocation, so an override can
    never be the last step before the work becomes unrecoverable.
    """
    import shutil

    project = Path(project)
    rtl_dir = _rtl_dir(project)
    base = rtl_dir.parent / (
        "rtl.authored_backup."
        + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
    dest = base
    n = 1
    while dest.exists():
        dest = Path(f"{base}.{n}")
        n += 1
    shutil.copytree(rtl_dir, dest)
    lp = ledger_path(project)
    if lp.is_file():
        shutil.copy2(lp, dest.parent / (dest.name + "." + LEDGER_NAME))
    return dest
