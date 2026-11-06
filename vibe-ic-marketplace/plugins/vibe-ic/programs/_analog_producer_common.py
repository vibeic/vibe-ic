#!/usr/bin/env python3
"""_analog_producer_common.py — the exit-code contract and metadata helpers shared by the deterministic A-track PRODUCERS.

TWO MEASURED DEFECTS, both of the same family: a published token that means
two different things, with nothing on the token to say which.

(1) rc 2 MEANT BOTH "I DECLINED, AND I WROTE DOWN WHY" AND "YOU TYPED A FLAG
    I DO NOT HAVE".
    Every producer returned 2 for an honest gap; `argparse` returns 2 for a
    usage error. Measured on all three, same tree, same invocation except one
    unknown flag:

        honest gap  -> rc 2, gap file written,     --json report written
        usage error -> rc 2, NO gap file written,  NO --json report written

    The caller that maps rc 2 to a deferral read the usage error as an honest
    gap, so a producer that never ran at all was reported as a producer that
    ran and stood down for a stated reason. The discriminator is the EXIT CODE
    itself: an honest gap keeps this repo's rc-2 "nothing produced, and here is
    why" tier; a usage error leaves it entirely for :data:`EX_USAGE`, and both
    print a line-start token so a caller that reads text rather than rc cannot
    confuse them either.

chip-AGNOSTIC: nothing here knows a design, PDK SKU, vendor or part number.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

# ── exit-code contract ────────────────────────────────────────────────────
#: The producer emitted at least one artefact.
RC_OK = 0
#: There was nothing to run against (no block list, no such block).
RC_NO_INPUT = 1
#: HONEST GAP — the producer declined for a stated reason AND recorded that
#: reason in its named gap file. This is the repo-wide "not produced, and here
#: is why" tier the A-track gates already use, and it is the tier a caller may
#: translate into a deferral.
RC_HONEST_GAP = 2
#: USAGE ERROR — the command line was wrong, so the producer never examined
#: the project at all. `sysexits.h` EX_USAGE. NOT a gap: no gap file was
#: written, no report was written, and nothing about the project was learned.
EX_USAGE = 64

EX_ENV_REFUSED = 69

#: Line-start tokens, for a caller that reads text rather than an exit code.
#: Same shape as the repo's existing `VACUOUS_PASS:` stdout sentinel.
HONEST_GAP_TOKEN = "HONEST_GAP:"
USAGE_ERROR_TOKEN = "USAGE_ERROR:"
ENV_REFUSED_TOKEN = "ENV_REFUSED:"


class ProducerArgumentParser(argparse.ArgumentParser):
    """`argparse` with the usage-error exit code moved off the honest-gap tier.

    Both hooks are overridden on purpose. `error()` covers the common paths
    (unknown flag, missing positional, bad type); `exit()` catches every other
    place argparse raises the same status internally, so the collision cannot
    come back through a path this class did not name.
    """

    def error(self, message: str):                      # noqa: D102
        self.print_usage(sys.stderr)
        print(f"{USAGE_ERROR_TOKEN} {self.prog}: {message}", file=sys.stderr)
        print(f"{USAGE_ERROR_TOKEN} exit {EX_USAGE} — this is NOT an honest "
              f"gap: no gap file and no --json report were written, and the "
              f"project was never examined. An honest gap is exit "
              f"{RC_HONEST_GAP}.", file=sys.stderr)
        sys.exit(EX_USAGE)

    def exit(self, status: int = 0, message: Optional[str] = None):
        if message:
            print(message, file=sys.stderr, end="")
        if status == RC_HONEST_GAP:
            status = EX_USAGE
        sys.exit(status)


def honest_gap_line(producer: str, detail: str) -> str:
    """The stderr line every producer prints when it returns
    :data:`RC_HONEST_GAP`, so the tier is readable without the exit code."""
    return f"{HONEST_GAP_TOKEN} {producer}: {detail}"


def env_refused_line(producer: str, detail: str) -> str:
    """The stderr line every producer prints when it returns
    :data:`EX_ENV_REFUSED`.

    `detail` is THE REFUSAL'S OWN LINE, carried through unchanged. The line
    `_eda_pin` composes names BOTH digests, which is the whole reason it can be
    acted on; a caller that summarises it back to "the environment refused"
    reproduces the silence this tier exists to end.
    """
    return f"{ENV_REFUSED_TOKEN} {producer}: {detail}"


# ── provenance binding ────────────────────────────────────────────────────
#: Prefix of the comment lines a producer stamps into a SPICE artefact. Every
#: line starting with it is excluded from :func:`content_digest`, which is what
#: makes that digest stable across runs and independent of where the run
#: happened.
PROVENANCE_COMMENT_PREFIX = "* _provenance:"


def new_run_ref() -> str:
    """12 hex naming ONE EMISSION — the run event, not the directory.

    Deriving it from the run PATH was the obvious first answer and it is
    wrong: it makes every `cp -a` of a run tree fail its own gate, and a gate
    that fires on an ordinary copy is a gate that gets waived. Deriving it
    from the emission TIMESTAMP alone is wrong too — two runs inside one
    second would share it.

    So it is a nonce, and it is checked by AGREEMENT rather than by
    re-derivation: the same value is stamped into the artefact AND into the
    record beside it. A record carried over from a different run then
    disagrees with the artefact it claims to describe, while a whole tree
    copied intact still agrees with itself. Content identity is a separate
    job with a separate function — see :func:`content_digest`.

    Leaks nothing: clock, pid and a random uuid, hashed.
    """
    seed = f"{time.time_ns()}|{os.getpid()}|{uuid.uuid4()}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


def stamped_run_ref(text: str) -> Optional[str]:
    """The `run_ref` a producer stamped into a SPICE artefact, or None."""
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith(f"{PROVENANCE_COMMENT_PREFIX} run_ref="):
            return s.split("run_ref=", 1)[1].strip()
    return None


def content_digest(text: str) -> str:
    """sha256 over an artefact's CONTENT, with every provenance comment removed.

    Two runs of the same inputs produce the same value; a run in a different
    directory, at a different second, still produces the same value. That is
    what a digest published as proof of content has to do — the digests this
    replaces changed on every run and therefore proved only that a run had
    happened.
    """
    body = [ln for ln in text.splitlines()
            if not ln.lstrip().startswith(PROVENANCE_COMMENT_PREFIX)]
    return hashlib.sha256(("\n".join(body) + "\n").encode("utf-8")).hexdigest()


def json_content_digest(raw: str) -> Optional[str]:
    """sha256 over a JSON artefact's CONTENT, with its `_provenance` removed.

    The JSON sibling of :func:`content_digest`, and it exists for the same
    reason (R-0915-62). `topology.json` carries a `_provenance` block with a
    `produced_at` wall clock, and `analog_a3_netlist_gen_check` compared the
    WHOLE-FILE sha256 of it against the digest the netlist stamped. So a
    topology re-emitted with identical content a second later moved the digest
    and the netlist was declared `A3_NETLIST_STALE_VS_IR` — on a deck whose own
    content had not changed, which the netlist's unchanged `netlist_sha256`
    proves. Measured on a real verdict run (lane icadc, 2026-09-16): the `ldo`
    topology re-emitted at 07:23 local, its digest moved 796eb6b2 -> 711cc1c6,
    the netlist stayed byte-identical at c6fe9b5468bdb153 — and A3 FAILED.

    Sorted keys and fixed separators, so the digest is a property of the
    content and not of the writer's formatting. Returns None on anything that
    is not JSON, because a caller that cannot parse it must fall back rather
    than invent a digest.
    """
    try:
        obj = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if isinstance(obj, dict):
        obj = {k: v for k, v in obj.items() if k != "_provenance"}
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")).hexdigest()


def file_digest(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def provenance_ref(ref: str, rel_path: str, content_sha: str) -> str:
    """The ONE token a report quotes: `<run>/<artefact>@<content>`.

    It names the run AND the artefact AND the content, so the reported digest
    and the reported run are the same string. A digest quoted from a different
    run now shows up as a different run ref instead of as an
    indistinguishable 64-hex blob.
    """
    return f"{ref}/{rel_path}@{content_sha[:12]}"
