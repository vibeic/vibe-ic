#!/usr/bin/env python3
"""One serialization, one hash — the thing every other PPA identity is built on.

WHY THIS IS THE FIRST FILE, AND WHY IT IS NOT NEGOTIABLE

Every identity in the PPA measurement contract is "the sha256 of this object".
If two programs serialize the same object two ways, they compute two different
identities for one fact, and every downstream claim built on those identities is
comparing things that were never the same. That is the exact defect the contract
exists to remove, so it cannot be reintroduced by the encoder.

THE RULES, and each one is here because the alternative is ambiguous:

  sort_keys=True        two dicts with the same pairs must hash the same,
                        whatever order they were built in
  separators no spaces  `{"a":1}` not `{"a": 1}`; whitespace is not information
                        and a pretty-printer must not change an identity
  ensure_ascii=False    a non-ASCII string has ONE encoding here (UTF-8), not
                        two (raw vs \\uXXXX). Escaping would make the same text
                        hash differently depending on who wrote it
  allow_nan=False       NaN and Infinity are not JSON. A metric that is NaN is
                        NOT_MEASURED with a reason, never a float that survives
                        a round-trip differently in two parsers
  no trailing newline   the bytes hashed are exactly the bytes of the document

FLOATS. A float's shortest repr is stable in CPython 3, so 0.1 serializes as
"0.1" and hashes the same everywhere this runs. What is NOT stable is arithmetic
that produced it: 0.1+0.2 is not 0.3. Producers must therefore hash the value
they PARSED, never a value they recomputed, and any derived number must declare
`status: DERIVED` with the formula so a reader can recompute it themselves.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

__all__ = ["dumps", "dumpb", "sha256", "digest_of"]


def dumps(obj: Any) -> str:
    """The one canonical text form of `obj`."""
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def dumpb(obj: Any) -> bytes:
    """The one canonical BYTE form. Hashing hashes these bytes, not str."""
    return dumps(obj).encode("utf-8")


def sha256(obj: Any) -> str:
    """The canonical identity of `obj`, as 64 lowercase hex characters.

    Returned bare, without the `sha256:` prefix. Call sites that write an
    identity into a document use `digest_of`, which carries the algorithm with
    the value -- a bare hex string does not say what produced it, and this
    repository has already paid for one identity whose algorithm was implied.
    """
    return hashlib.sha256(dumpb(obj)).hexdigest()


def digest_of(obj: Any) -> str:
    """`sha256:<64 hex>` — the form that goes INTO a document."""
    return "sha256:" + sha256(obj)
