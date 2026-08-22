#!/usr/bin/env python3
"""CLI: build the read-only, hash-bound agent context from a manifest.

The library is `_ppa/agent_context.py`; the boundary argument is in its
docstring and is the reason this program carries no file content into its
output. This file is the CLI contract from `docs/PPA_INTERFACES.md` 1.

THE EXIT CODES
==============
    0  a context was built and every ref is hash-bound
    1  REFUSED -- a ref escaped the evidence root, or policy forbids the request
    2  UNDETERMINED -- a declared ref did not resolve, so no context was built
    3  BAD INVOCATION

The 1/2 split is the load-bearing one. "A ref points outside the evidence root"
is a REFUSAL: the manifest asked for something it may not have, and that is a
finding about the request. "A ref did not resolve" is UNDETERMINED: the builder
could not look, and a builder that reports a clean, small context in that case
is a run that never opened its input reporting success.

WHY IT WILL NOT BUILD AN EMPTY CONTEXT
======================================
Zero refs exits 2, not 0. A context over no evidence is not a small context; it
is no context, and handing one to an agent means the agent answers from its
prior alone while the record shows a context was built. That is the empty-tree
shape at the agent boundary.

chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _atomic_artefact import write_text as atomic_write_text  # noqa: E402
from _ppa import agent_context, agent_policy, cli_exit  # noqa: E402

RC_OK = 0
RC_REFUSED = 1
RC_UNDETERMINED = 2
RC_BAD_INVOCATION = 3

MARKER_REFUSE = "[REFUSE]"
MARKER_CANNOT_CHECK = "[CANNOT CHECK]"


def _load(path: Path, what: str) -> Dict[str, Any]:
    if not path.exists():
        raise agent_context.EvidenceMissing(f"{what} {path} does not exist")
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise agent_context.EvidenceMissing(
            f"{what} {path} could not be read: {exc}") from None
    if not raw.strip():
        raise agent_context.EvidenceMissing(
            f"{what} {path} is empty (0 non-whitespace bytes)")
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise agent_context.EvidenceMissing(
            f"{what} {path} is not valid JSON: {exc}") from None
    if not isinstance(doc, dict):
        raise agent_context.EvidenceMissing(
            f"{what} {path} is not a JSON object")
    return doc


def format_report(context: Dict[str, Any], digest: str) -> str:
    out: List[str] = []
    out.append(f"PPA agent context: {context['evidence_count']} ref(s), "
               f"level {context['autonomy_level']}")
    out.append(f"  question   : {context['question']}")
    out.append(f"  root       : {context['evidence_root']}")
    out.append(f"  untrusted  : {context['untrusted_count']} of "
               f"{context['evidence_count']}")
    out.append(f"  handling   : {context['handling']}")
    out.append(f"  context sha: {digest}")
    unknown = [e["path"] for e in context["evidence"] if not e["role_is_known"]]
    if unknown:
        out.append(f"  NOTE       : {len(unknown)} ref(s) carry a role this "
                   f"system does not classify and were treated as UNTRUSTED "
                   f"(fail-safe): {unknown}")
    if context["flagged_paths"]:
        # Loud, and on stdout with the report, because a flagged path is the
        # one finding here a human must actually look at.
        out.append(f"  ATTENTION  : {len(context['flagged_paths'])} ref "
                   f"path(s) are injection-shaped and are carried UNCHANGED "
                   f"and FLAGGED, never rewritten:")
        for e in context["evidence"]:
            if e["path_is_injection_shaped"]:
                out.append(f"      {e['path']!r}: {e['path_flags']}")
    out.append("  content    : none -- this document carries references and "
               "hashes only")
    return "\n".join(out)


def run(manifest_path: Path, policy_path: Optional[Path],
        out_path: Optional[Path]) -> tuple:
    manifest = _load(manifest_path, "manifest")

    policy = None
    if policy_path is not None:
        policy = _load(policy_path, "policy")

    root = manifest.get("evidence_root")
    if not isinstance(root, str) or not root:
        raise agent_context.ContextRefused(
            "manifest declares no evidence_root; the root is the boundary a "
            "ref may not step over, so a manifest without one has no boundary")
    question = manifest.get("question")
    if not isinstance(question, str):
        raise agent_context.ContextRefused(
            "manifest states no question; a context exists to answer one")

    root_path = Path(root)
    if not root_path.is_absolute():
        root_path = (manifest_path.resolve().parent / root_path)

    context = agent_context.build_context(
        root_path, manifest.get("refs") or [], question, policy)

    # The structural claim, checked at runtime and not only in a test.
    agent_context.assert_no_file_content(context, root_path)

    digest = agent_context.context_digest(context)
    context_out = dict(context)
    context_out["context_sha256"] = digest

    if out_path is not None:
        atomic_write_text(
            out_path,
            json.dumps(context_out, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")

    return RC_OK, context, digest


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Build a read-only, hash-bound agent evidence context. "
                    "Carries references and hashes only; never file content.")
    ap.add_argument("manifest", nargs="?",
                    help="JSON manifest: evidence_root, question, refs[]")
    ap.add_argument("--policy", default=None, metavar="PATH")
    ap.add_argument("--out", default=None, metavar="PATH",
                    help="write the context document here")
    ap.add_argument("--json", default=None, metavar="PATH",
                    help="write the machine-readable report here")
    # `parse_args` exits 2 on a usage error, and 2 in this layer means
    # UNDETERMINED -- a caller that treats 2 as "nothing to check here"
    # carries on green over a misspelled flag. §1 says a bad invocation is
    # 3. `parse_or_refuse` reads argparse's exit CODE, so `--help`
    # (SystemExit(0)) stays rc=0 and only the usage error becomes 3.
    args, rc = cli_exit.parse_or_refuse(ap, argv)
    if args is None:
        return rc

    if not args.manifest:
        print("give a manifest path", file=sys.stderr)
        return RC_BAD_INVOCATION

    def _emit(report: Dict[str, Any]) -> None:
        if args.json:
            atomic_write_text(Path(args.json),
                              json.dumps(report, indent=2, sort_keys=True) + "\n",
                              encoding="utf-8")

    try:
        rc, context, digest = run(
            Path(args.manifest),
            Path(args.policy) if args.policy else None,
            Path(args.out) if args.out else None)
    except agent_context.EvidenceMissing as exc:
        print(f"{MARKER_CANNOT_CHECK} {exc}", file=sys.stderr)
        _emit({"schema": "vibeic.ppa.agent_context_report.v1",
               "outcome": "UNDETERMINED", "rc": RC_UNDETERMINED,
               "marker": MARKER_CANNOT_CHECK, "detail": str(exc)})
        return RC_UNDETERMINED
    except (agent_context.ContextRefused, agent_policy.PolicyError) as exc:
        print(f"{MARKER_REFUSE} {exc}", file=sys.stderr)
        _emit({"schema": "vibeic.ppa.agent_context_report.v1",
               "outcome": "REFUSED", "rc": RC_REFUSED,
               "marker": MARKER_REFUSE, "detail": str(exc)})
        return RC_REFUSED

    print(format_report(context, digest))
    _emit({"schema": "vibeic.ppa.agent_context_report.v1",
           "outcome": "BUILT", "rc": RC_OK,
           "context_sha256": digest,
           "evidence_count": context["evidence_count"],
           "untrusted_count": context["untrusted_count"],
           "flagged_paths": context["flagged_paths"]})
    return rc


if __name__ == "__main__":
    sys.exit(main())
