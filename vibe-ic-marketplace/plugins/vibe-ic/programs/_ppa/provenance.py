#!/usr/bin/env python3
"""Where a number came from — artefact hashes, image references, run manifest.

THE QUESTION THIS MODULE ANSWERS
================================
`identity.py` asks "are these the same inputs?" and `contract.py` asks "are
these runs solving the same problem?". Neither can answer without a truthful
record of what was actually read off the disk, which is this module.

THE ONE DISTINCTION EVERYTHING ELSE RESTS ON
============================================
**"I could not read it" and "I read it and it was empty" must never produce the
same record.** An empty file has a perfectly good sha256 --

    e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855

-- and a run that measured an empty report has MEASURED something: that the
report was empty. A run that could not open the report has measured NOTHING.
Collapsing those two is how a check reports clean over a file it never saw, and
it is why `artefact_ref` returns `status: NOT_MEASURED` with a `reason` for an
absent or unreadable path instead of an absent entry or a zero.

The entry is never OMITTED either. A missing row and a NOT_MEASURED row read
identically to a human scanning a table, and only one of them is honest about
having been asked.

WHY PATHS ARE RELATIVE TO A DECLARED ROOT
=========================================
An absolute path is host state. Two runs of the same design on two machines
would produce different identities for the same artefact, and the contract's
entire purpose is to say those two runs were the same. Every reference is
therefore stored relative to a declared root, and a path that escapes that root
is NOT_MEASURED with a reason rather than followed -- a reference reaching
outside the run directory is not reproducible by anyone else, whatever it
contains.

WHY THERE IS NO TIMESTAMP IN THE RUN MANIFEST
=============================================
Deliberate, and it is the reason the contract can be byte-compared at all. A
manifest that differs between two byte-identical runs cannot serve as evidence
that they were identical -- the reader has to decide which differences "do not
count", and that judgement is exactly what a digest exists to remove. When a
run happened is a property of the run LOG. What the run READ is a property of
this manifest. `test_ppa_contract_stability` pins the absence.

IMAGE REFERENCES
================
A tag floats. `repo:latest` names different bytes on different days, so a
verdict that cites a tag cites nothing a third party can fetch. Only a
`repo@sha256:<hex>` reference identifies bytes, and `classify_image_ref` exists
so `contract.py` can refuse a floating reference that carries a verdict.

The image's VERSION is read from its OCI label, never stored in this source
tree. A version number written down here is a copy that goes stale silently the
next time the image is rebuilt, and then our source is asserting something about
an image it has never opened. If the label cannot be read, that is
NOT_MEASURED -- not a guess, and not the last version anybody remembered.

chip-AGNOSTIC: file bytes, container references and JSON. Nothing here reasons
about any IC, vendor, process or product.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

__all__ = [
    "MEASURED", "NOT_MEASURED",
    "EMPTY_FILE_SHA256", "IMAGE_VERSION_LABEL",
    "hash_bytes", "hash_file",
    "artefact_ref", "artefact_refs",
    "classify_image_ref", "is_floating_image_ref",
    "read_image_version", "image_record",
    "run_manifest", "evidence_manifest",
    "MANIFEST_SCHEMA", "EVIDENCE_SCHEMA",
]

MEASURED = "MEASURED"
NOT_MEASURED = "NOT_MEASURED"

MANIFEST_SCHEMA = "vibeic.ppa.run_manifest.v1"
EVIDENCE_SCHEMA = "vibeic.ppa.evidence_manifest.v1"

#: The sha256 of zero bytes. Named so a reader of a record can see at a glance
#: that a file was READ and was EMPTY, which is a measurement, rather than
#: guessing whether the row means "absent".
EMPTY_FILE_SHA256 = (
    "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")

#: The OCI label a compliant image carries its own version in. Read from the
#: image; never mirrored into this source.
IMAGE_VERSION_LABEL = "org.opencontainers.image.version"

#: `[repo/]name@sha256:<64 hex>` -- the only reference form that names bytes.
_DIGEST_RE = re.compile(r"^(?P<repository>[^@\s]+)@(?P<digest>sha256:[0-9a-f]{64})$")
#: A bare digest, which names bytes but not where to fetch them from.
_BARE_DIGEST_RE = re.compile(r"^(?P<digest>sha256:[0-9a-f]{64})$")
#: `repo:tag`, with the tag never containing `/` (which would make it a path).
_TAG_RE = re.compile(r"^(?P<repository>[^:@\s]+(?::\d+)?(?:/[^:@\s]+)*)"
                     r":(?P<tag>[^:/@\s]+)$")

#: Read in 1 MiB blocks so a large GDS or SPEF does not have to fit in memory.
_BLOCK = 1 << 20


def hash_bytes(data: bytes) -> str:
    """`sha256:<64 hex>` over raw BYTES.

    Distinct from `canonical_json.digest_of`, which hashes an OBJECT through
    the one canonical encoding. An artefact on disk is bytes and is hashed as
    bytes: re-encoding a report before hashing it would mean the identity
    describes our parse of the file rather than the file.
    """
    return "sha256:" + hashlib.sha256(data).hexdigest()


def hash_file(path: Path) -> str:
    """`sha256:<64 hex>` over the file's bytes. Raises OSError to the caller.

    Deliberately does not catch: a caller that wants a verdict about an
    unreadable file uses `artefact_ref`, which records WHY. Swallowing the
    error here is what produces a hash-shaped hole nobody can trace.
    """
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(_BLOCK)
            if not block:
                break
            h.update(block)
    return "sha256:" + h.hexdigest()


def _relative_within(root: Path, rel: str) -> Optional[Path]:
    """Resolve `rel` under `root`, or None if it escapes or is absolute.

    `os.path.normpath` before resolution so `a/../../b` is rejected on its
    text, and a second check after resolution so a SYMLINK pointing out of the
    root is rejected too -- the first catches the declaration, the second
    catches the filesystem.
    """
    if os.path.isabs(rel):
        return None
    normalised = os.path.normpath(rel)
    if normalised == ".." or normalised.startswith(".." + os.sep):
        return None
    candidate = root / normalised
    try:
        resolved = candidate.resolve()
        root_resolved = root.resolve()
    except OSError:
        return None
    if resolved != root_resolved and root_resolved not in resolved.parents:
        return None
    return candidate


def artefact_ref(root: Path, rel_path: str, role: str) -> Dict[str, Any]:
    """One row of the evidence table: role, path, and what we could learn.

    Always returns a row. `status` is `MEASURED` with a `sha256` and a byte
    count, or `NOT_MEASURED` with a `reason` -- never a sentinel hash, never a
    zero standing in for "absent", never an omitted row.
    """
    row: Dict[str, Any] = {"role": role, "path": rel_path}
    target = _relative_within(Path(root), rel_path)
    if target is None:
        row["status"] = NOT_MEASURED
        row["reason"] = ("path is absolute or escapes the declared root; a "
                         "reference nobody else can resolve is not evidence")
        return row
    try:
        if target.is_symlink() and not target.exists():
            row["status"] = NOT_MEASURED
            row["reason"] = "dangling symlink"
            return row
        if not target.exists():
            row["status"] = NOT_MEASURED
            row["reason"] = "absent"
            return row
        if not target.is_file():
            row["status"] = NOT_MEASURED
            row["reason"] = "not a regular file"
            return row
        digest = hash_file(target)
        size = target.stat().st_size
    except OSError as exc:
        row["status"] = NOT_MEASURED
        row["reason"] = f"unreadable: {exc.__class__.__name__}"
        return row
    row["status"] = MEASURED
    row["sha256"] = digest
    row["bytes"] = size
    return row


def artefact_refs(root: Path,
                  declarations: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """`artefact_ref` over a declared list, sorted by (role, path).

    Sorted so the order the caller happened to build the list in cannot change
    an identity. Two declarations of the same (role, path) collapse to one row:
    a duplicate is not more evidence.
    """
    rows: Dict[Any, Dict[str, Any]] = {}
    for decl in declarations:
        role = str(decl.get("role", ""))
        rel = str(decl.get("path", ""))
        rows[(role, rel)] = artefact_ref(Path(root), rel, role)
    return [rows[k] for k in sorted(rows)]


def classify_image_ref(ref: str) -> Dict[str, Any]:
    """Say what an image reference actually names.

    `form` is one of:
      `digest`       `repo@sha256:<hex>` -- names bytes AND where to get them
      `bare_digest`  `sha256:<hex>`      -- names bytes, not a registry
      `tag`          `repo:tag`          -- FLOATS; the bytes can change
      `untagged`     `repo`              -- floats, implicitly `:latest`
      `malformed`    nothing recognisable
    """
    text = (ref or "").strip()
    if not text:
        return {"ref": ref, "form": "malformed", "floating": True}
    m = _DIGEST_RE.match(text)
    if m:
        return {"ref": text, "form": "digest", "floating": False,
                "repository": m.group("repository"), "digest": m.group("digest")}
    m = _BARE_DIGEST_RE.match(text)
    if m:
        return {"ref": text, "form": "bare_digest", "floating": False,
                "digest": m.group("digest")}
    m = _TAG_RE.match(text)
    if m:
        return {"ref": text, "form": "tag", "floating": True,
                "repository": m.group("repository"), "tag": m.group("tag")}
    if re.match(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$", text):
        return {"ref": text, "form": "untagged", "floating": True,
                "repository": text}
    return {"ref": text, "form": "malformed", "floating": True}


def is_floating_image_ref(ref: str) -> bool:
    """True when the reference does not pin bytes."""
    return bool(classify_image_ref(ref)["floating"])


def _docker_label_reader(digest_ref: str, timeout_s: int = 60) -> Optional[str]:
    """Read `IMAGE_VERSION_LABEL` off an image by DIGEST, or None.

    None on every failure path -- docker absent, daemon down, image not
    pullable, label unset, `<no value>` from the Go template. The caller turns
    None into NOT_MEASURED. It must never turn it into a version, which is why
    this returns None rather than a fallback string.
    """
    fmt = '{{index .Image.Config.Labels "%s"}}' % IMAGE_VERSION_LABEL
    try:
        proc = subprocess.run(
            ["docker", "buildx", "imagetools", "inspect", digest_ref,
             "--format", fmt],
            capture_output=True, text=True, timeout=timeout_s)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    value = (proc.stdout or "").strip()
    if not value or value == "<no value>":
        return None
    return value


def read_image_version(digest_ref: str,
                       reader: Optional[Callable[[str], Optional[str]]] = None
                       ) -> Dict[str, Any]:
    """The image's own version, or an explicit NOT_MEASURED with a reason.

    `reader` is injectable so this is testable without a docker daemon, and so
    a caller that has already resolved the label can pass it in rather than
    paying for a second registry round-trip. The DEFAULT is the real reader:
    an injectable that defaults to a stub would let a test's convenience become
    production behaviour.
    """
    fn = reader if reader is not None else _docker_label_reader
    value = fn(digest_ref)
    if value is None:
        return {"status": NOT_MEASURED,
                "reason": (f"{IMAGE_VERSION_LABEL} could not be read from "
                           f"the image"),
                "label": IMAGE_VERSION_LABEL}
    return {"status": MEASURED, "value": value, "label": IMAGE_VERSION_LABEL,
            "source": "oci_label"}


def image_record(declaration: Dict[str, Any],
                 reader: Optional[Callable[[str], Optional[str]]] = None
                 ) -> Dict[str, Any]:
    """One image row: what was declared, what it names, and its own version.

    `verdict_bearing` is the caller's declaration that this image produced
    evidence a verdict rests on. It is what makes a floating reference a
    finding rather than a note -- a floating reference to a documentation
    image harms nobody; a floating reference to the image that produced the
    timing report means the timing report cannot be reproduced.

    The version is looked up ONLY for a reference that pins bytes. Reading a
    label off a tag would record the version of whatever the tag pointed at
    at that moment, which is precisely the floating value this refuses.
    """
    ref = str(declaration.get("ref", ""))
    role = str(declaration.get("role", ""))
    verdict_bearing = bool(declaration.get("verdict_bearing", False))
    classified = classify_image_ref(ref)
    row: Dict[str, Any] = {
        "role": role,
        "ref": classified["ref"],
        "form": classified["form"],
        "floating": classified["floating"],
        "verdict_bearing": verdict_bearing,
    }
    if "repository" in classified:
        row["repository"] = classified["repository"]
    if "digest" in classified:
        row["digest"] = classified["digest"]
        row["version"] = read_image_version(ref, reader=reader)
    else:
        row["version"] = {
            "status": NOT_MEASURED,
            "reason": ("the reference does not pin bytes, so any label read "
                       "off it would describe whatever it pointed at at that "
                       "moment"),
            "label": IMAGE_VERSION_LABEL,
        }
    return row


def run_manifest(root_label: str,
                 images: Sequence[Dict[str, Any]],
                 tools: Sequence[Dict[str, Any]],
                 artefacts: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """The `vibeic.ppa.run_manifest.v1` document.

    Carries no clock and no hostname, on purpose -- see the module docstring.
    Everything in it is a function of what was declared and what was on disk,
    so two identical runs produce identical bytes and a difference is
    information rather than noise.
    """
    return {
        "schema": MANIFEST_SCHEMA,
        "root": root_label,
        "images": sorted(images, key=lambda r: (r.get("role", ""), r.get("ref", ""))),
        "tools": sorted(tools, key=lambda r: (r.get("name", ""), r.get("role", ""))),
        "artefacts": sorted(artefacts,
                            key=lambda r: (r.get("role", ""), r.get("path", ""))),
    }


def evidence_manifest(artefacts: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """The subset of the manifest a verdict is allowed to cite.

    Split from the run manifest because they answer different questions: the
    run manifest is everything the run touched, the evidence manifest is what
    the verdict RESTS ON. A number backed by an artefact absent from here is
    a number whose provenance nobody declared.
    """
    rows = sorted(artefacts, key=lambda r: (r.get("role", ""), r.get("path", "")))
    measured = [r for r in rows if r.get("status") == MEASURED]
    return {
        "schema": EVIDENCE_SCHEMA,
        "artefacts": rows,
        "measured_count": len(measured),
        "not_measured_count": len(rows) - len(measured),
    }
