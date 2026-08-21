#!/usr/bin/env python3
"""ppa_contract_check.py — the validator, and what it must REFUSE.

A contract that nobody validates is a document that agrees with itself. This is
the program that decides whether a run's numbers may be compared to anything,
and every clause below refuses something that otherwise produces a number that
looks fine:

    PPA-C-001  the contract does not hash to its own stated digest — it was
               edited after it was built, so every identity in it describes a
               document that no longer exists                          REFUSE
    PPA-C-002  a VERDICT-BEARING image reference floats (`repo:tag`). The same
               reference resolves to different bytes on different days, so the
               evidence behind the verdict cannot be fetched again    REFUSE
    PPA-C-003  two sources declare one key with two values — the SDC and the
               spec layer disagreeing about the clock is the canonical case.
               Both values and both sources are NAMED. This program does not
               choose between them: choosing buries the disagreement inside a
               digest where nothing downstream can see it              REFUSE
    PPA-C-004  a power metric carries a value with no declared activity basis.
               REFUSE or UNDETERMINED per `policy.missing_power_basis`, and
               never a default — assuming a switching activity produces a
               plausible number for every design         REFUSE / CANNOT CHECK
    PPA-C-005  a candidate mutated something outside the declared allow-list.
               A PPA experiment may move the implementation; moving the problem
               and reporting a win is winning a different contest       REFUSE
    PPA-C-006  an invented number: a declared default, a fact whose origin is
               an assumption, an ESTIMATED metric in final PPA, or a status
               that is not MEASURED still carrying a value             REFUSE
    PPA-C-007  an identity is NOT_MEASURED                       CANNOT CHECK
    PPA-C-008  a metric cites an artefact that is not in the evidence manifest
                                                                       REFUSE
    PPA-C-009  a key opted into authority resolution names a source that is not
               in the authority order, so no winner can be ranked CANNOT CHECK
    PPA-C-010  the document is not a contract, or its schema could not be
               applied                                            CANNOT CHECK
    PPA-C-011  a policy the check depends on was not declared. An ABSENT policy
               is not an empty one — this reports UNDETERMINED rather than a
               refusal it has not established                    CANNOT CHECK
    PPA-C-014  an image pins bytes but its OCI version label could not be read.
               A NOTE, not a verdict: the digest is what a verdict rests on and
               it is intact. `policy.missing_image_version: "UNDETERMINED"`
               promotes it for a caller that needs the label            NOTE
    PPA-C-015  a key was resolved by the declared authority order. Also a NOTE,
               and it NAMES the winner and every value it overrode — which
               source won is exactly the fact a silent resolution destroys NOTE

`_ppa.contract.FINDING_CODES` is the registry these come from; `finding()`
refuses an unregistered code, so this list cannot fall behind the code that
emits them the way it already did once.

WHY A MISSING VALIDATOR IS NOT A PASS
-------------------------------------
If no engine can apply the schema, or the schema file is not in the tree, this
program reports PPA-C-010 and exits 2. It does NOT skip the schema check and
report on the rest, because "I could not apply the schema" and "the schema
found nothing" would then produce the same output — which is the defect this
whole package exists to remove, reappearing in the tool that removes it.

WHICH ENGINE, AND WHY IT IS RESOLVED RATHER THAN IMPORTED (R11)
---------------------------------------------------------------
`_ppa/schema_validation.resolve` picks the engine. It prefers the `jsonschema`
library and falls back to `_ppa/jsonschema_bundled.py`, which ships with the
plugin so the contract's shape is checked on a host that has nothing installed.

The fall-through is not only for an ABSENT library. `import jsonschema` used to
be the whole test here, and it is the wrong question: version 3.2.0 -- what a
current distribution's system package installs -- imports fine and has no
`Draft202012Validator`, which the shipped schemas' declared draft needs. This
program attributed it anyway and died with an uncaught AttributeError, exiting
1: a crash publishing itself as a finding about a design.

chip-AGNOSTIC: it reads one JSON document and one schema.

USAGE
-----
    ppa_contract_check.py --contract CONTRACT.json [--json REPORT.json]
                          [--schema-dir DIR]

EXIT CODES
----------
    0  [PASS]          no finding
    1  [REFUSE]        at least one FAIL. FAIL outranks UNDETERMINED: a
                       confirmed finding is news, and reporting 2 because
                       something else was unchecked would hide it. Both are
                       always listed.
    2  [CANNOT CHECK]  the contract is absent/unreadable, or something needed
                       was UNDETERMINED
    3  bad invocation
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _atomic_artefact import write_text as atomic_write_text  # noqa: E402
from _ppa import contract as C  # noqa: E402
from _ppa import schema_validation as SV  # noqa: E402

#: The plugin root is this file's grandparent; the schemas live beside
#: `programs/`. Resolved from `__file__` so the program measures the tree it
#: ships in rather than the tree it was launched from.
_DEFAULT_SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas" / "ppa"


def schema_findings(document: Any, schema_dir: Path) -> List[Dict[str, Any]]:
    """Apply `contract.v1.schema.json`, or say why it could not be applied.

    A document that does not CLAIM to be `vibeic.ppa.contract.v1` is not
    validated against it. Measured while writing the negative fixture: running
    the schema over an unrelated document produced a pile of FAIL rows and
    rc=1, which reads as "this contract is broken" when the truth is "this is
    not a contract". rc=1 is a claim about a design and nothing here has looked
    at one, so the verdict is UNDETERMINED and the schema is not applied.
    """
    declared = str((document or {}).get("schema", "")) \
        if isinstance(document, dict) else ""
    if declared != C.CONTRACT_SCHEMA:
        return [C.finding(
            "PPA-C-010", C.SEV_UNDETERMINED,
            f"the document declares schema {declared!r}, not "
            f"{C.CONTRACT_SCHEMA!r}. It was not validated against contract.v1: "
            f"a pile of shape violations from applying the wrong schema would "
            f"read as a broken contract rather than as the wrong document",
            declared=declared)]
    path = Path(schema_dir) / "contract.v1.schema.json"
    schema, reason = C.load_json(path)
    if reason is not None:
        return [C.finding(
            "PPA-C-010", C.SEV_UNDETERMINED,
            f"the contract schema could not be read ({reason}), so the "
            f"document's shape was NOT validated",
            schema_path=str(path))]
    # R11. The engine is RESOLVED, never assumed. `import jsonschema` is not
    # the question -- 3.2.0 imports and has no Draft202012Validator, and the
    # previous code went straight on to attribute it and died with an uncaught
    # AttributeError, returning rc=1 (a finding about a DESIGN) from a crash.
    engine, notes = SV.resolve(schema)
    if engine is None:
        return [C.finding(
            "PPA-C-010", C.SEV_UNDETERMINED,
            "the contract's shape was NOT validated: " + " ".join(notes)
            + ". This is not the schema passing",
            schema_path=str(path))]
    out: List[Dict[str, Any]] = []
    out.extend(_apply(engine, document, "contract.v1", "<document root>"))

    # The run manifest is embedded, and `contract.v1` types it only as an
    # object. Validating it here is what stops `run_manifest.v1.schema.json`
    # from being a file that ships and is never applied -- a schema nothing
    # enforces states a rule that is not in force, which is worse than no
    # schema because a reader believes it.
    manifest_schema, reason = C.load_json(
        Path(schema_dir) / "run_manifest.v1.schema.json")
    if reason is not None:
        out.append(C.finding(
            "PPA-C-010", C.SEV_UNDETERMINED,
            f"the run-manifest schema could not be read ({reason}), so the "
            f"embedded run manifest was NOT validated"))
    else:
        m_engine, m_notes = SV.resolve(manifest_schema)
        if m_engine is None:
            out.append(C.finding(
                "PPA-C-010", C.SEV_UNDETERMINED,
                "the embedded run manifest was NOT validated: "
                + " ".join(m_notes)))
        else:
            out.extend(_apply(m_engine, document.get("run_manifest"),
                              "run_manifest.v1", "run_manifest"))
    return out


def _apply(engine: Any, instance: Any, name: str,
           root_label: str) -> List[Dict[str, Any]]:
    """Every violation of one schema, as findings, sorted so reports diff.

    `engine` is whatever `_ppa.schema_validation.resolve` handed back. Its
    errors carry `.message` and `.path` whichever engine produced them, so
    nothing here branches on which one ran.
    """
    rows: List[Dict[str, Any]] = []
    for err in sorted(engine.iter_errors(instance), key=lambda e: list(e.path)):
        where = "/".join(str(p) for p in err.path)
        where = f"{root_label}/{where}" if where else root_label
        rows.append(C.finding(
            "PPA-C-010", C.SEV_FAIL,
            f"the document violates {name} at {where}: {err.message}",
            path=where, schema_name=name))
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--contract", required=True)
    ap.add_argument("--json", dest="json_out",
                    help="optional machine-readable report; nothing is "
                         "written unless this is given")
    ap.add_argument("--schema-dir", default=str(_DEFAULT_SCHEMA_DIR))
    args = ap.parse_args(argv)

    document, reason = C.load_json(Path(args.contract))
    if reason is not None:
        print(f"[CANNOT CHECK] ppa_contract_check: {reason}", file=sys.stderr)
        print("   No contract was read, so nothing has been established about "
              "this run. This is NOT a finding about the design.",
              file=sys.stderr)
        return 2
    if not isinstance(document, dict):
        print(f"[CANNOT CHECK] ppa_contract_check: {args.contract} holds a "
              f"{type(document).__name__}, not a contract object",
              file=sys.stderr)
        return 2

    findings = schema_findings(document, Path(args.schema_dir))
    findings.extend(C.validate(document))
    findings.sort(key=lambda f: (f["code"], f["message"]))
    rc = C.rc_from(findings)

    if args.json_out:
        atomic_write_text(Path(args.json_out), json.dumps({
            "program": "ppa_contract_check",
            "contract": str(args.contract),
            "contract_digest": document.get("contract_digest"),
            "rc": rc,
            "examined": C.denominators(document),
            "findings": findings,
        }, indent=2) + "\n")

    counts = C.denominators(document)
    stream = sys.stdout if rc == 0 else sys.stderr
    print(f"{C.marker_for(rc)} ppa_contract_check: {args.contract} — "
          f"{len(findings)} finding(s)", file=stream)
    for line in C.format_findings(findings):
        print(line, file=stream)
    # Always, and on BOTH streams' verdicts: a `0 finding(s)` over an empty
    # contract and one over a full contract print the same zero, and only the
    # denominator tells them apart.
    for line in C.format_denominators(counts):
        print(line, file=stream)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
