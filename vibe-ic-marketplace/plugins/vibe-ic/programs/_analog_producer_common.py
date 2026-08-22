#!/usr/bin/env python3
"""_analog_producer_common.py — the exit-code contract and the provenance
binding shared by the deterministic A-track PRODUCERS.

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

(2) A DIGEST PUBLISHED AS PROOF NAMED NEITHER THE ARTEFACT NOR THE RUN.
    The netlist header quoted `sha256=` of its two inputs. Those files embed a
    wall-clock stamp and an absolute path, so the digest changed on every run
    even when the design content was byte-identical — measured across SIX
    sibling run trees of the same inputs, six different quoted digests, and
    nothing on any of them saying which tree it came from. A digest like that
    is a per-run nonce wearing the clothes of a content identity: a reader can
    neither recompute it nor match it to the run being reported.

    Content identity and run identity are two jobs. They get two functions,
    and both are checkable from bytes that travel WITH the tree — so a run
    directory copied intact still verifies, and only a record lifted out of
    one run and dropped into another does not:

      * :func:`content_digest` — identifies the CONTENT. Every provenance
        comment is removed before hashing, so it is stable across runs of the
        same inputs and a reader recomputes it from the artefact alone.
      * :func:`new_run_ref` — identifies ONE EMISSION. A nonce, stamped into
        the artefact AND into the record beside it, and checked by AGREEMENT
        rather than by re-derivation. See the function for why deriving it
        from the run's path is the wrong answer.
      * :func:`provenance_ref` — the ONE token a report quotes: run, artefact
        and content in one string, so a digest quoted from a different run is
        self-evidently from a different run.
      * :func:`verify_provenance_ref` — the check a reader would otherwise do
        by hand, shipped so a gate does it on every run.

chip-AGNOSTIC: nothing here knows a design, PDK SKU, vendor or part number.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Optional

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

#: Line-start tokens, for a caller that reads text rather than an exit code.
#: Same shape as the repo's existing `VACUOUS_PASS:` stdout sentinel.
HONEST_GAP_TOKEN = "HONEST_GAP:"
USAGE_ERROR_TOKEN = "USAGE_ERROR:"


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


def verify_provenance_ref(ref: Any, rel_path: str, text: str) -> Optional[str]:
    """None when *ref* describes THIS artefact and was produced by the run that
    stamped it; otherwise the reason it does not.

    Three comparisons, all against bytes that travel WITH the tree, so a whole
    run directory copied intact still verifies and a record lifted out of one
    run and dropped into another does not:

      * the run the record claims == the run stamped in the artefact
      * the artefact the record names == the artefact it was read from
      * the content digest the record publishes == the artefact's own
    """
    if not isinstance(ref, str) or ref.count("/") < 1 or "@" not in ref:
        return (f"provenance_ref {ref!r} is not in the "
                f"`<run>/<artefact>@<content>` shape")
    got_run, rest = ref.split("/", 1)
    got_path, got_sha = rest.rsplit("@", 1)
    stamped = stamped_run_ref(text)
    if stamped is None:
        return ("the artefact carries no `run_ref` stamp to check the record "
                "against")
    if got_run != stamped:
        return (f"the record names run {got_run} and the artefact beside it is "
                f"stamped {stamped}. This record was produced by a DIFFERENT "
                f"run than the artefact it claims to describe")
    if got_path != rel_path:
        return (f"the record names artefact {got_path!r}, read from "
                f"{rel_path!r}")
    want_sha = content_digest(text)
    if got_sha != want_sha[:12]:
        return (f"the record publishes content digest {got_sha} — the "
                f"artefact on disk digests to {want_sha[:12]}")
    return None
