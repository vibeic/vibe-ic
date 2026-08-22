#!/usr/bin/env python3
"""`ppa_ablation_check.py` — every `vibeic.ppa.ablation.v1` document, validated.

WHY THIS GATE EXISTS
====================
`schemas/ppa/ablation.v1.schema.json` was added so that a WITHIN-PROJECT
ablation has a document kind of its own instead of being filed as
`vibeic.ppa.comparison.v2` — the kind whose entire claim is a comparison
against an opponent this project did NOT tune. That was the right repair and it
shipped with one record re-filed under the new kind.

WHAT DID NOT SHIP WITH IT: ANYTHING THAT RUNS.

Measured on `a4caccefe` (v1.11.69), the whole of what reads that schema is:

    programs/tests/test_ablation_is_not_a_head_to_head.py   one pytest, and it
                                                            drives ONE
                                                            hardcoded path
    tools/ci/repo_hygiene_gates.sh                          the word `ablation`
                                                            appears in a
                                                            comment. Nothing
                                                            else.

So a SECOND ablation filed into `records/ablations/` tomorrow is validated by
nothing that runs. `ppa_head_to_head_check` will not judge it — it selects
`vibeic.ppa.comparison.v2` and this document truthfully declares it is not one
— and no other gate opens it. The kind that was created to stop a comparison
escaping its conditions can, with no gate behind it, become the place a
comparison escapes to. That is the hole this program closes, and it is the same
shape as the finding that produced the schema in the first place.

WHAT IT CHECKS, AND WHAT IT DELIBERATELY DOES NOT
=================================================
It applies `ablation.v1.schema.json` to every document that DECLARES that
schema, anywhere under the corpus, and reports the verdict per record and for
the corpus. The schema itself carries the load-bearing clauses and this program
does not restate them in Python — restating a rule is how the two copies drift:

    claim_scope: const within_project     stated, never inferred
    arms: minItems 2                      one arm ablates nothing
    every arm tuned_by_this_project: true THE clause. An arm this project did
                                          NOT tune is an opponent, and a
                                          document holding one is a
                                          head-to-head — it belongs in
                                          comparison.v2 where
                                          `ppa_head_to_head_check` applies the
                                          fairness conditions to it. A schema
                                          failure on this clause is named
                                          separately in the output, because
                                          "some shape violation" and "a
                                          head-to-head is hiding in here" are
                                          not the same sentence to a reader.

IT DOES NOT INVENT REQUIREMENTS THE REVIEWED SCHEMA DOES NOT MAKE. `isolates`
is described in the schema as the thing "without which a reader has two number
sets and no question", and it is NOT in `required`. This gate therefore reports
a missing `isolates` as a NOTE and NOT as a finding. Tightening the schema is a
reviewer's decision; a gate that quietly enforces more than the document it
cites is how a rule nobody agreed to becomes load-bearing.

THE FOUR CORPUS OUTCOMES ARE THE SEAM'S, NOT A NEW SET
======================================================
    ABSENT      the corpus pointer resolves to no directory -> rc 2, the
                pointer NAMED. Nothing was opened.
    VACUOUS     the corpus was walked and holds no record of this kind -> rc 2.
                An empty corpus is NEVER a pass: a gate that has never met an
                artefact cannot have cleared one.
    UNREADABLE  a `*.json` that could not be parsed is not a file that held no
                record — nobody looked -> rc 2, named.
    present     each record judged; the corpus takes the WORST verdict.

`_ppa_corpus` is that seam and this program adds none of its own. Selection is
on the DECLARED `schema` key of the parsed document, never on the filename, so
a record filed under any name is judged.

EXIT CODES — docs/PPA_INTERFACES.md §1
    0  every record of this kind validates
    1  a published record does not — a finding about the record
    2  nothing could be decided (absent / vacuous / unreadable / no engine)
    3  bad invocation or internal error — never a finding about anything

chip-AGNOSTIC: JSON, a schema file and path plumbing. No design, PDK, vendor,
node or SKU literal, and none is reachable from here.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _ppa_corpus as corpus_seam  # noqa: E402  one seam for all corpora
from _atomic_artefact import write_text as atomic_write_text  # noqa: E402
from _ppa import cli_exit  # noqa: E402  §1: argparse exits 2; bad invocation is 3
from _ppa import schema_validation as SV  # noqa: E402

_GATE = "ppa_ablation_check"
_SCANNED = "ablation record(s)"
_KIND = "vibeic.ppa.ablation.v1"
_SCHEMA_FILE = "ablation.v1.schema.json"
_DEFAULT_SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas" / "ppa"

#: The clause whose failure means a head-to-head is hiding in this kind. Used
#: only to LABEL an error the schema already found — never to re-implement it.
_TUNED_CLAUSE = "tuned_by_this_project"


def is_ablation(document: Any) -> bool:
    """Does this parsed document DECLARE it is an ablation record?

    By declaration, per PPA_INTERFACES §5, which requires `schema` as the first
    key of every instance document. Not by filename: the complaint that
    produced the corpus seam is precisely that a record filed under an
    unexpected name is not judged.
    """
    return isinstance(document, dict) and document.get("schema") == _KIND


def _load(path: Path) -> Tuple[Any, Optional[str]]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"could not be read: {exc}"
    except json.JSONDecodeError as exc:
        return None, f"is not JSON: {exc}"


def _schema_or_reason(schema_dir: Path) -> Tuple[Any, Optional[str]]:
    path = Path(schema_dir) / _SCHEMA_FILE
    schema, reason = _load(path)
    if reason is not None:
        return None, f"{path} {reason}"
    return schema, None


def check_record(path: Path, document: Any, schema_dir: Path) -> Tuple[int, List[str]]:
    """`(rc, lines)` for ONE document that declares this kind.

    A DOCUMENT THAT DOES NOT DECLARE THE KIND IS NOT VALIDATED AGAINST IT, and
    that is a verdict of UNDETERMINED rather than a pile of shape violations:
    running this schema over an unrelated document produces a long list of
    failures that read as "this ablation is broken" when the truth is "this is
    not an ablation".
    """
    lines: List[str] = []
    if not isinstance(document, dict):
        return corpus_seam.RC_UNDETERMINED, [
            f"{cli_exit.MARK_CANNOT_CHECK} {_GATE}: {path} holds a "
            f"{type(document).__name__}, not an ablation object. Nothing was "
            f"validated."]
    declared = str(document.get("schema", ""))
    if declared != _KIND:
        return corpus_seam.RC_UNDETERMINED, [
            f"{cli_exit.MARK_CANNOT_CHECK} {_GATE}: {path} declares schema "
            f"{declared!r}, not {_KIND!r}. It was NOT validated against "
            f"{_SCHEMA_FILE}: applying the wrong schema would read as a broken "
            f"ablation rather than as the wrong document."]

    schema, reason = _schema_or_reason(schema_dir)
    if reason is not None:
        return corpus_seam.RC_UNDETERMINED, [
            f"{cli_exit.MARK_CANNOT_CHECK} {_GATE}: {reason}, so {path} was "
            f"NOT validated. This is not the schema passing."]

    # The ENGINE is resolved, never assumed: an installed `jsonschema` that is
    # too old for the declared draft has no validator class for it, and
    # attributing one anyway dies with an AttributeError that would exit 1 —
    # the code §1 reserves for a finding about a design.
    engine, notes = SV.resolve(schema)
    if engine is None:
        return corpus_seam.RC_UNDETERMINED, [
            f"{cli_exit.MARK_CANNOT_CHECK} {_GATE}: {path} was NOT validated: "
            + " ".join(notes) + ". This is not the schema passing."]

    errors = sorted(engine.errors(document),
                    key=lambda e: (list(getattr(e, "path", [])), str(e.message)))
    if not errors:
        lines.append(f"[PASS] {_GATE}: {path} validates against {_KIND} "
                     f"({len(document.get('arms') or [])} arm(s); {notes[0]})")
        if not str(document.get("isolates", "")).strip():
            # A NOTE, not a finding: `isolates` is not in the schema's
            # `required`. See the module docstring.
            lines.append(
                f"  NOTE: it declares no `isolates`, so a reader has two "
                f"number sets and no question. The schema does not require it "
                f"and this gate does not either — tightening that is the "
                f"reviewer's call, not this program's.")
        return corpus_seam.RC_OK, lines

    tuned = [e for e in errors if _TUNED_CLAUSE in list(map(str, getattr(e, "path", [])))
             or _TUNED_CLAUSE in str(e.message)]
    lines.append(f"{cli_exit.MARK_REFUSE} {_GATE}: {path} does not validate "
                 f"against {_KIND} — {len(errors)} violation(s)")
    for err in errors:
        where = "/".join(str(p) for p in getattr(err, "path", [])) or "<document>"
        lines.append(f"  [FAIL] {where}: {err.message}")
    if tuned:
        # Named separately because the two sentences are not the same fact.
        lines.append(
            f"  THE {_TUNED_CLAUSE} CLAUSE IS THE ONE THAT FAILED. Every arm "
            f"of an ablation must declare `{_TUNED_CLAUSE}: true`. An arm this "
            f"project did NOT tune is an OPPONENT, and a document holding one "
            f"is a head-to-head: file it as `vibeic.ppa.comparison.v2` so "
            f"`ppa_head_to_head_check` applies the fairness conditions to it. "
            f"Filing it here is how a comparison escapes those conditions.")
    return corpus_seam.RC_REFUSED, lines


def check_corpus(named: Path, schema_dir: Path, may_be_absent: bool = False,
                 json_out: Optional[str] = None) -> int:
    """Every ablation record under `named`, aggregated by severity."""
    corpus, rc = corpus_seam.open_corpus(named, _GATE, _SCANNED, may_be_absent)
    if corpus is None:
        return rc
    scan = corpus_seam.collect(corpus, is_ablation)
    print(f"{_GATE} --corpus {corpus}: {scan.denominator(_SCANNED)}")
    unread_rc = corpus_seam.report_unreadable(_GATE, scan)
    if not scan.records:
        return corpus_seam.worst_rc(
            [corpus_seam.vacuous(_GATE, corpus, _SCANNED, scan), unread_rc])

    rcs: List[int] = []
    reports: List[Dict[str, Any]] = []
    for path, document in scan.records:
        rc_one, lines = check_record(path, document, schema_dir)
        stream = sys.stdout if rc_one == corpus_seam.RC_OK else sys.stderr
        for line in lines:
            print(line, file=stream)
        rcs.append(rc_one)
        reports.append({"path": str(path), "rc": rc_one, "lines": lines})

    worst = corpus_seam.worst_rc(rcs + [unread_rc])
    refused = sum(1 for r in rcs if r == corpus_seam.RC_REFUSED)
    undet = sum(1 for r in rcs if r == corpus_seam.RC_UNDETERMINED)
    print(f"{_GATE} --corpus {corpus}: {len(rcs)} record(s), {refused} "
          f"refused, {undet} undetermined, {len(rcs) - refused - undet} "
          f"accepted -> rc={worst}")
    if json_out:
        # ATOMIC, never `Path(...).write_text`: this is a DECLARED report
        # destination, and a truncated one is read downstream as this gate's
        # own evidence. `_atomic_artefact_residual.json` is a ratchet that may
        # only ever shrink; a new program does not get to grow it.
        atomic_write_text(Path(json_out), json.dumps({
            "program": _GATE, "mode": "corpus", "corpus": str(corpus),
            "files_opened": scan.files,
            "records": [str(p) for p, _ in scan.records],
            "unreadable": [{"path": str(p), "why": w}
                           for p, w in scan.unreadable],
            "per_record": reports, "rc": worst,
        }, indent=2, sort_keys=True) + "\n")
    return worst


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--record", default=None, metavar="ONE.json",
                    help="validate ONE ablation document")
    ap.add_argument("--corpus", default=None, metavar="DIR",
                    help="validate every ablation record under DIR; exits 2 "
                         "when the corpus carries none")
    ap.add_argument("--corpus-may-be-absent", action="store_true",
                    help="this repository need not carry the published "
                         "corpus. Turns 'nothing anywhere' into a stated "
                         "NO_CORPUS that names its zero, and NEVER excuses a "
                         "$VIBE_IC_BENCHMARK_DATA that is set and unreadable.")
    ap.add_argument("--json", dest="json_out",
                    help="optional machine-readable report; nothing is "
                         "written unless this is given")
    ap.add_argument("--schema-dir", default=str(_DEFAULT_SCHEMA_DIR))
    args, _rc = cli_exit.parse_or_refuse(ap, argv)
    if args is None:
        return _rc

    if args.record is not None and args.corpus is not None:
        # Two population sources in one invocation. Letting one win silently is
        # how a caller who NAMED a document gets a verdict about a different
        # one.
        return corpus_seam.both_given(_GATE, "--record", "--corpus")
    if args.corpus is not None:
        return check_corpus(Path(args.corpus).resolve(),
                            Path(args.schema_dir),
                            args.corpus_may_be_absent, args.json_out)
    if args.record is None:
        # §1: naming no mode at all is a BAD INVOCATION (3), never "I could not
        # look" (2). The message names EVERY mode this gate has — a refusal
        # that hides a mode is how a caller concludes the gate cannot do what
        # it can.
        return cli_exit.refuse(
            _GATE,
            "give --record ONE.json, or --corpus DIR, or "
            "--corpus DIR --corpus-may-be-absent")

    path = Path(args.record)
    document, reason = _load(path)
    if reason is not None:
        print(f"{cli_exit.MARK_CANNOT_CHECK} {_GATE}: {path} {reason}. No "
              f"record was read, so nothing has been established. This is NOT "
              f"a finding about any measurement.", file=sys.stderr)
        return corpus_seam.RC_UNDETERMINED
    rc, lines = check_record(path, document, Path(args.schema_dir))
    stream = sys.stdout if rc == corpus_seam.RC_OK else sys.stderr
    for line in lines:
        print(line, file=stream)
    if args.json_out:
        atomic_write_text(Path(args.json_out), json.dumps({
            "program": _GATE, "mode": "record", "record": str(path),
            "rc": rc, "lines": lines,
        }, indent=2, sort_keys=True) + "\n")
    return rc


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover - the guard, not the path
        # §1: 3 is INTERNAL ERROR. Letting this propagate exits 1, which is
        # reserved for a finding about a published record.
        print(f"{cli_exit.MARK_REFUSE} {_GATE}: internal error "
              f"{type(exc).__name__}: {exc}. Nothing was validated. rc=3 "
              f"(NOT a finding about any record).", file=sys.stderr)
        raise SystemExit(cli_exit.RC_BAD_INVOCATION)
