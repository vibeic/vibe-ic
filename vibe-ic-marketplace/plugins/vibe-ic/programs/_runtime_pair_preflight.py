#!/usr/bin/env python3
"""The PAIR. Three runtime identities, reconciled ONCE, before any fan-out.

WHY THIS MODULE EXISTS
======================
`_eda_pin` already answers three separate questions correctly. Nothing asked
all three together, and nothing asked them BEFORE work started.

MEASURED and reported as #2120. Plugin 1.18.68 and the published EDA 0.3.48 each
passed their own checks and did not form a runnable pair:

  * the installed pin required ``sha256:8c5694ab…``;
  * a fresh pull of the published ``:latest`` resolved to ``sha256:1463dac5…``,
    whose own version label ALSO reads ``0.3.48`` — same version, different
    build, different bytes;
  * a newly started MCP process reported ``16/16 checks passed`` against the
    upgraded shared container.

Sixteen tools were present. None of that is a statement about whether the
dispatcher would select that container or accept its digest, and it did not: the
dispatcher launched workers, runner provenance recorded a digest-derived
container that was absent, and the batch had to be stopped and excluded.

A VERSION IS NOT A DIGEST, AND "16/16 TOOLS" IS NOT "EXECUTION-READY"
====================================================================
Those are the two substitutions this module refuses. Tool availability answers
"can this container run yosys"; the pair answers "is this the container the pin
demands". A deployment can be perfect on the first and unrunnable on the second,
and 0.3.48-vs-0.3.48 is precisely the case where a human reading a version
number cannot tell.

THREE CHECKS, IN THIS ORDER, EACH KEEPING ITS OWN CODE
======================================================
  1. ``pinned_image_present``   — THIS host holds the pinned bytes, under the
     configured repository or under any other name it pulled them from: the
     digest is the identity and the repository is configuration (#2170).
                                             refuses ``IMAGE_NOT_PRESENT``
  2. ``default_container_name`` — which container a run would actually select,
     honouring ``VIBEIC_EDA_CONTAINER``, and whether it exists at all.
                                             refuses ``CONTAINER_ABSENT``
  3. ``container_matches_pin``  — that container's image digest IS the pinned
     digest.                                 refuses ``CONTAINER_IMAGE_MISMATCH``

The sub-codes are not decoration. "the image was never pulled", "the container
is gone" and "the container is the wrong build" need three different actions,
and a preflight that collapses them into one word sends the operator to re-run
the thing that cannot work. Which of the three disagreed is recorded by name.

IT IS AN INFRASTRUCTURE VERDICT, NOT A DESIGN ONE
=================================================
`RUNTIME_INFRASTRUCTURE_NOT_READY` is its own class and is returned BEFORE any
per-design work exists. A design that was never attempted has no FAIL to report
and nothing for an AI repair task to repair; charging the machine's state to the
design is how a deployment defect becomes a score.

DIGESTS ONLY IN THE HEALTH LINE
===============================
`pair_line()` names the two digests and the container, and never a repository.
The repository is deployment configuration -- on this fleet a private registry
address -- and an address does not belong in an artefact that gets committed or
published. The VERBATIM refusal, which `_eda_pin` composes with the repository
in it, is preserved in the run record (a run directory, never committed) because
the reporter of a mismatch has to be able to tell a stale container from a
mis-set ``VIBEIC_EDA_IMAGE_REPO``.

chip-AGNOSTIC: image and container identity only. No design, PDK, vendor, IC or
host-address literal appears here.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _eda_pin as _pin  # noqa: E402 — the ONE place the pin is stated

__all__ = [
    "RUNTIME_PAIR_MATCH",
    "RUNTIME_PAIR_MISMATCH",
    "RUNTIME_INFRASTRUCTURE_NOT_READY",
    "PREFLIGHT_CHECKS",
    "preflight",
    "pair_line",
    "evidence_text",
]

#: The two named states of the pair. `MATCH` is the ONLY one a fan-out may
#: proceed on, and it is reached only when all three checks proved.
RUNTIME_PAIR_MATCH = "RUNTIME_PAIR_MATCH"
RUNTIME_PAIR_MISMATCH = "RUNTIME_PAIR_MISMATCH"

#: The verdict CLASS a dispatcher records when the pair does not match. Its own
#: class deliberately: not a design FAIL, not an AI repair task, not a score.
RUNTIME_INFRASTRUCTURE_NOT_READY = "RUNTIME_INFRASTRUCTURE_NOT_READY"

#: The three checks, in the order they are asked, spelled with the names the
#: report that asked for them uses.
PREFLIGHT_CHECKS = (
    "pinned_image_present",
    "default_container_name",
    "container_matches_pin",
)


def _check(name: str, ok: bool, code: str, detail: str) -> dict:
    return {"check": name, "ok": bool(ok), "code": code, "detail": detail}


def preflight(env=None) -> dict:
    """Reconcile the three identities. Never launches, never mutates, no network.

    Returns a record, always with the same keys, so a caller can write it into a
    run root without deciding what a partial answer looks like::

        verdict         RUNTIME_PAIR_MATCH | RUNTIME_PAIR_MISMATCH
        checks          the three rows above, each with its own code
        container       the container a run WOULD select (never None: the name
                        is derivable even when nothing holds it)
        required_digest the pinned digest
        found_digest    the container's digest, or None when it could not be read
        disagreed       the FIRST check that did not prove, or None
        evidence        the refusals VERBATIM, in order

    `found_digest` is None both when the container is absent and when its image
    carries no registry digest, and `checks` keeps those apart by code. A caller
    that needs the distinction reads the code; one that only gates on the
    verdict does not have to.
    """
    env = os.environ if env is None else env
    if env.get("VIBEIC_LIBRELANE_LOCAL_ATTESTATION"):
        from _container_exec import no_container_route
        if no_container_route():
            import librelane_contract as local
            identity, required, error = None, None, ""
            try:
                required = _pin.resolved_image_digest(env)
                if env[local.LOCAL_ATTESTATION_ENV] != os.environ.get(local.LOCAL_ATTESTATION_ENV):
                    raise local.Refusal("LL_LOCAL_IMAGE_UNATTESTED",
                                        "attestation differs from the process environment")
                identity = local.local_image_attestation(
                    f"{_pin.image_repo(env)}@{required}")
            except (local.Refusal, _pin.ImageNotResolvable) as exc:
                error = str(exc)
            ok = identity is not None
            return {
                "schema": "vibeic.runtime.pair_preflight.v1",
                "verdict": RUNTIME_PAIR_MATCH if ok else RUNTIME_PAIR_MISMATCH,
                "checks": [_check(name, ok, "" if ok else "LOCAL_IMAGE_UNATTESTED",
                                  identity["attestation_sha256"] if ok else error)
                           for name in PREFLIGHT_CHECKS],
                "container": identity["cid"] if ok else "LOCAL",
                "required_digest": required,
                "found_digest": required if ok else None,
                "disagreed": None if ok else PREFLIGHT_CHECKS[0],
                "evidence": [] if ok else [error],
                "execution_route": "LOCAL",
                "local_launch": identity,
            }
    checks: list[dict] = []
    evidence: list[str] = []
    disagreed: Optional[str] = None
    found: Optional[str] = None

    ref, why = _pin.pinned_image_present(env)
    checks.append(_check("pinned_image_present", bool(ref),
                         "" if ref else _pin.IMAGE_NOT_PRESENT,
                         ref or why))
    if not ref:
        disagreed = "pinned_image_present"
        evidence.append(why)

    container = _pin.default_container_name(env)
    state, detail = _pin.container_pin_state(container, env)
    exists = state != "UNREADABLE" or not detail.startswith(_pin.CONTAINER_ABSENT)
    checks.append(_check(
        "default_container_name", exists,
        "" if exists else _pin.CONTAINER_ABSENT,
        container if exists else detail))
    if not exists:
        if disagreed is None:
            disagreed = "default_container_name"
        evidence.append(detail)

    matched = state == "MATCH"
    if matched:
        found = _pin.IMAGE_DIGEST
    elif state == "MISMATCH":
        # The refusal `_eda_pin` composes ends with `found <digest>`; the digest
        # is read back from the module rather than re-inspected so the line the
        # operator is shown and the digest recorded here cannot be two answers.
        found = detail.rsplit("found ", 1)[-1].strip() or None
        if found is not None and not _pin.DIGEST_RE.match(found):
            found = None
    checks.append(_check(
        "container_matches_pin", matched,
        "" if matched else (_pin.CONTAINER_IMAGE_MISMATCH
                            if state == "MISMATCH" else _pin.CONTAINER_ABSENT
                            if detail.startswith(_pin.CONTAINER_ABSENT)
                            else "CONTAINER_IMAGE_UNREADABLE"),
        "" if matched else detail))
    if not matched:
        if disagreed is None:
            disagreed = "container_matches_pin"
        if detail and detail not in evidence:
            evidence.append(detail)

    ok = all(row["ok"] for row in checks)
    return {
        "schema": "vibeic.runtime.pair_preflight.v1",
        "verdict": RUNTIME_PAIR_MATCH if ok else RUNTIME_PAIR_MISMATCH,
        "checks": checks,
        "container": container,
        "required_digest": _pin.IMAGE_DIGEST,
        "found_digest": found,
        "disagreed": disagreed,
        "evidence": evidence,
    }


def pair_line(record: dict) -> str:
    """ONE line, digests and the container name only — never a repository.

    This is the shape that goes into a health report and into any artefact that
    may be committed or published. It carries enough to act on (which container,
    which two digests, which of the three identities disagreed) and nothing that
    names a place on somebody's network.
    """
    found = record.get("found_digest") or "NOT_READ"
    line = (f"{record.get('verdict')} container={record.get('container')} "
            f"required={record.get('required_digest')} found={found}")
    if record.get("verdict") != RUNTIME_PAIR_MATCH:
        line += f" disagreed={record.get('disagreed')}"
    return line


def evidence_text(record: dict) -> str:
    """The refusals VERBATIM, newline-joined, exactly as `_eda_pin` composed them.

    Nothing is re-worded here. A preflight that paraphrases its evidence hands
    the reader a summary of a mismatch instead of the mismatch, and the reader
    then re-runs the thing to see it for themselves.
    """
    return "\n".join(str(line) for line in record.get("evidence") or [])
