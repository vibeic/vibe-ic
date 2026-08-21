#!/usr/bin/env python3
"""ppa_contract_build.py — build the measurement contract for one PPA run.

WHAT IT PRODUCES
----------------
A `vibeic.ppa.contract.v1` document: the five identities (problem,
implementation, analysis, toolchain, agent_execution), the run and evidence
manifests that back them, the declared policy, and the document's own digest.
It is the artefact every other PPA claim hashes against, which is why it is
built by a program rather than assembled by hand in each caller.

THE PROPERTY THAT MAKES IT WORTH BUILDING
-----------------------------------------
Given the same declaration and the same bytes under `--root`, this emits a
BYTE-IDENTICAL document. No clock, no hostname, no pid, no absolute path enters
it. `test_ppa_contract_stability.py` proves that by running this program twice
in two PROCESSES and comparing the bytes -- a same-process comparison would
miss a hash seed or an iteration order that happened to be stable within one
interpreter.

The converse is proved too: change one byte of any declared source artefact and
the contract digest moves.

IT ALWAYS WRITES THE CONTRACT, EVEN A FAILING ONE
-------------------------------------------------
The contract is the RECORD of a run, including a run that should not be
compared to anything. Withholding it on a finding would leave the worst runs
undocumented, which is exactly backwards. The exit code carries the verdict;
the document carries the evidence.

IMAGE VERSIONS
--------------
Read from each image's own `org.opencontainers.image.version` OCI label, by
digest. Never stored in this source tree: a version written down here is a copy
that goes stale the next time the image is rebuilt, and then our source is
asserting something about an image it has never opened. If the label cannot be
read the version is NOT_MEASURED with a reason -- never the last one anybody
remembered. `--no-image-labels` skips the read entirely (for a hermetic build);
it still records NOT_MEASURED, so the contract is honest either way.

chip-AGNOSTIC: hashes, declared policy and container references only.

USAGE
-----
    ppa_contract_build.py --declaration DECL.json --root RUN_DIR
                          --out CONTRACT.json [--json REPORT.json]
                          [--no-image-labels]

EXIT CODES
----------
    0  the contract is clean
    1  [REFUSE]       a finding: conflicting facts, a floating verdict-bearing
                      image, a forbidden mutation, an invented default
    2  [CANNOT CHECK] the declaration is absent or unreadable, or something
                      the contract needs was NOT_MEASURED
    3  bad invocation
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _atomic_artefact import write_text as atomic_write_text  # noqa: E402
from _ppa import cli_exit  # PPA_INTERFACES §1: argparse exits 2; a bad invocation is 3
from _ppa import canonical_json, contract as C  # noqa: E402


def _no_label_reader(_digest_ref: str) -> Optional[str]:
    """The hermetic reader: never reads, never guesses, always NOT_MEASURED."""
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--declaration", required=True,
                    help="the vibeic.ppa.contract_declaration.v1 input")
    ap.add_argument("--root", required=True,
                    help="directory the declared artefact paths are relative to")
    ap.add_argument("--out", required=True, help="where to write the contract")
    ap.add_argument("--json", dest="json_out",
                    help="optional machine-readable verdict report")
    ap.add_argument("--no-image-labels", action="store_true",
                    help="do not attempt to read image OCI labels; every "
                         "image version is recorded NOT_MEASURED")
    args, _rc = cli_exit.parse_or_refuse(ap, argv)
    if args is None:
        return _rc

    declaration, reason = C.load_json(Path(args.declaration))
    if reason is not None:
        print(f"[CANNOT CHECK] ppa_contract_build: {reason}", file=sys.stderr)
        print("   The declaration is the whole input. Nothing about this run "
              "has been established, and this is NOT a finding about the "
              "design.", file=sys.stderr)
        return 2
    if not isinstance(declaration, dict):
        print(f"[CANNOT CHECK] ppa_contract_build: {args.declaration} is a "
              f"{type(declaration).__name__}, not a declaration object",
              file=sys.stderr)
        return 2

    root = Path(args.root)
    if not root.is_dir():
        print(f"[CANNOT CHECK] ppa_contract_build: --root {args.root} is not a "
              f"directory, so no declared artefact can be hashed",
              file=sys.stderr)
        return 2

    reader = _no_label_reader if args.no_image_labels else None
    document = C.build(declaration, root, label_reader=reader)

    # canonical bytes, not json.dumps: the file on disk must BE the bytes the
    # digest was taken over, or a reader who re-hashes the file gets a
    # different answer than the document states about itself.
    atomic_write_text(Path(args.out), canonical_json.dumps(document) + "\n")

    findings = C.validate(document)
    rc = C.rc_from(findings)

    if args.json_out:
        atomic_write_text(Path(args.json_out), json.dumps({
            "program": "ppa_contract_build",
            "contract": str(args.out),
            "contract_digest": document["contract_digest"],
            "rc": rc,
            "findings": findings,
        }, indent=2) + "\n")

    print(f"ppa_contract_build: wrote {args.out}")
    print(f"   contract_digest {document['contract_digest']}")
    for kind, record in document["identities"].items():
        if record.get("status") == "MEASURED":
            print(f"   {kind:16s} {record['digest']}")
        else:
            print(f"   {kind:16s} NOT_MEASURED — {record.get('reason', '')}")

    stream = sys.stdout if rc == 0 else sys.stderr
    print(f"{C.marker_for(rc)} ppa_contract_build: {len(findings)} finding(s)",
          file=stream)
    for line in C.format_findings(findings):
        print(line, file=stream)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
