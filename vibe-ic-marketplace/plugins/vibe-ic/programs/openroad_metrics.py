#!/usr/bin/env python3
"""Ask the tool for its own numbers: `-metrics` on every OpenROAD invocation. W5.

THE THING BEING ADOPTED
=======================
Every OpenROAD-flow-scripts stage runs through ONE 21-line wrapper
(`flow/scripts/flow.sh:15`) which appends `-metrics "$LOG_DIR/$1.json"`, and
each stage script names its namespace on its first line (`detail_route.tcl:1`
is `utl::set_metrics_stage "detailedroute__{}"`). Their aggregator
(`util/genMetrics.py:279-289`) is then a glob-and-merge with NO PARSER, and
`util/checkMetadata.py` compares NAMED quantities against the design's rules
file. The number that is gated is the number the tool computed.

WHAT WE HAD, MEASURED ON THIS TREE at 8e60dd954
===============================================
`grep -rn '\\-metrics ' programs/ mcp-eda/` returns no call site: two docstring
mentions and nothing else. We construct `openroad -no_init -exit <tcl> 2>&1 |
tee <dir>/<name>.log` at a dozen separate places and then read the numbers back
out of `<name>.log` with regexes. OpenROAD was never asked for its own numbers
at all.

Why that is the substrate under every other number: a change in a tool's log
WORDING silently blinds a regex, and a blinded regex does not report "I can no
longer see"; it reports nothing found, which the caller reads as zero, and the
gate goes on printing PASS while blind. `step_metrics.reconcile` states the
rule for the two sources; this module is what makes the first source exist.

WHY A FUNCTION AND NOT TWELVE EDITS
===================================
The metrics path is DERIVED from the `tee` target the call site already names
(`openroad.log` -> `openroad.metrics.json`), so a site cannot be wired halfway:
there is no second literal to keep in step with the first. That is the same
property ORFS gets from `$LOG_DIR/$1.json` — one wrapper, one derivation — and
it is what `openroad_metrics_wiring_check` is able to enforce mechanically.
`with_metrics` is idempotent, so re-wrapping an already-wrapped command is a
no-op rather than a second flag OpenROAD would reject.

WHAT THIS DOES NOT DO, said plainly so a green run is not read as coverage
=========================================================================
Emitting is not gating. This routes the flag, ingests what the tool wrote, and
republishes it through the one metrics channel (`step_metrics.emit`). Which
GATES then read those metrics instead of their log regex is a per-gate
migration; `step_metrics_coverage_check` publishes how many have made it.

chip-AGNOSTIC: no IC, vendor, PDK or process literal appears or can affect it.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import step_metrics as _sm  # noqa: E402  — the one metrics channel
from _atomic_artefact import write_json as _atomic_write_json  # noqa: E402  vibe-ic#1082

RC_OK = 0
RC_VIOLATION = 1
RC_UNDETERMINED = 2

#: The tool writes here, next to the log it already writes, so the two are
#: found together and a run that kept one kept the other.
METRICS_SUFFIX = ".metrics.json"

#: `openroad` followed by its flags, up to the shell pipe/redirect that ends it.
#: Anchored on the executable name rather than on the whole command so a call
#: site that changes its PATH prologue or its `tee` target is still recognised.
#:
#: THE BOUNDARIES ARE THE LOAD-BEARING PART, and they are here because `\b`
#: alone was measured getting it wrong: every call site in this tree opens with
#: `export PATH=/foss/tools/openroad/bin:...`, and `\bopenroad\b` matched the
#: PATH COMPONENT first, so wrapping produced
#: `export PATH=/foss/tools/openroad -metrics /w/openroad.metrics.json/bin:...`
#: — a mangled PATH and a metrics path that is not a path. Excluding `/`, `.`
#: and `-` on both sides is what distinguishes the command from a directory
#: named after it.
_OPENROAD_CALL = re.compile(
    r"(?<![\w/.\-])openroad(?![\w/.\-])(?P<flags>(?:\s+[^\s|;&>]+)*)")

#: The `tee <path>` the call site already names. The metrics path is derived
#: from this and from nothing else.
_TEE_TARGET = re.compile(r"\btee\s+(?P<path>[^\s|;&>]+)")

_METRICS_FLAG = re.compile(r"(?<!\w)-metrics(?!\w)")


class WiringDefect(ValueError):
    """A call site that cannot be wired, with the reason it cannot."""


# --------------------------------------------------------------------------- #
# Derive the metrics path from the log path the site already names
# --------------------------------------------------------------------------- #
def metrics_path_for_log(log_path: str) -> str:
    """`.../openroad.log` -> `.../openroad.metrics.json`.

    Any extension is replaced, and a path with none gains the suffix, so the
    derivation is total: there is no log target this returns nothing for, and
    therefore no call site that can be wired "except that one".
    """
    p = str(log_path)
    stem = p[: -len(Path(p).suffix)] if Path(p).suffix else p
    return stem + METRICS_SUFFIX


def has_metrics(cmd: str) -> bool:
    return bool(_METRICS_FLAG.search(cmd))


def with_metrics(cmd: str, metrics_path: Optional[str] = None) -> str:
    """Return `cmd` with `-metrics <path>` on its OpenROAD invocation.

    IDEMPOTENT: a command that already carries the flag is returned unchanged,
    because the wiring check and the call sites are allowed to disagree about
    who wrapped first without producing a command OpenROAD would reject.

    `metrics_path` is optional ONLY because it is normally derivable; when the
    command names no `tee` target and no path is given this RAISES rather than
    guessing a location, since a metrics file the caller cannot predict is a
    metrics file nothing will ever read.
    """
    if not _OPENROAD_CALL.search(cmd):
        raise WiringDefect(
            f"no openroad invocation in {cmd!r}; there is nothing to wire")
    if has_metrics(cmd):
        return cmd
    if metrics_path is None:
        tee = _TEE_TARGET.search(cmd)
        if not tee:
            raise WiringDefect(
                f"{cmd!r} names no `tee <log>` target and no metrics path was "
                f"given; refusing to invent a path nothing would read")
        metrics_path = metrics_path_for_log(tee.group("path"))

    def _insert(m: re.Match) -> str:
        return f"openroad -metrics {metrics_path}{m.group('flags')}"

    return _OPENROAD_CALL.sub(_insert, cmd, count=1)


# --------------------------------------------------------------------------- #
# Scan — what the wiring check reads
# --------------------------------------------------------------------------- #
def invocations(text: str) -> List[Dict[str, Any]]:
    """Every constructed OpenROAD command in `text`, with its wiring state.

    Reads SOURCE, not a run: the question "does this call site ask the tool for
    its numbers" is answerable statically, and a check that could only answer it
    by running a full place-and-route would be run once and then never again.
    """
    out: List[Dict[str, Any]] = []
    for i, line in enumerate(text.splitlines(), start=1):
        for m in _OPENROAD_CALL.finditer(line):
            flags = m.group("flags") or ""
            # A bare `openroad` with no flags at all is a PATH export, a comment
            # word or a directory name, not an invocation of the binary.
            if not re.search(r"-\w", flags):
                continue
            out.append({"line": i,
                        "text": line.strip(),
                        "flags": flags.strip(),
                        "has_metrics": bool(_METRICS_FLAG.search(flags))})
    return out


# --------------------------------------------------------------------------- #
# Ingest — republish what the tool wrote through the one metrics channel
# --------------------------------------------------------------------------- #
def _sanitize_key_part(part: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", part).strip("_").lower()


def orfs_key_to_schema_key(step: Any, orfs_key: str) -> str:
    """`detailedroute__route__drc_errors` -> `<step>__detailedroute__route__drc_errors`.

    The tool's own namespace is KEPT WHOLE and only prefixed. Flattening it into
    our three-part shape would destroy the one property that makes an ORFS key
    useful — that it says which stage computed it — and `step_metrics.key_defect`
    already allows four parts and more for exactly this reason.
    """
    parts = [p for p in (_sanitize_key_part(p) for p in orfs_key.split("__")) if p]
    if not parts:
        parts = ["unnamed"]
    return "__".join([_sm.normalize_step(step), *parts])


def ingest(project: Path, step: Any, metrics_json: Path) -> Tuple[Optional[Path], Dict[str, Any]]:
    """Read a tool-written metrics JSON and re-emit it under `step`.

    Returns `(emitted_path_or_None, provenance)`. An ABSENT file is reported as
    absent and emits nothing: a run where the tool never wrote its metrics must
    not become a run with zero metrics, because those two read identically
    downstream and only one of them is a measurement.
    """
    f = Path(metrics_json)
    prov: Dict[str, Any] = {"source": str(f), "step": _sm.normalize_step(step),
                            "read": 0, "emitted": 0, "skipped": []}
    if not f.is_file():
        prov["status"] = "absent"
        prov["reason"] = ("the tool wrote no metrics file here; NOT CHECKED, "
                          "not an empty measurement")
        return None, prov
    try:
        doc = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        prov["status"] = "unreadable"
        prov["reason"] = f"{exc}"
        return None, prov
    if not isinstance(doc, dict):
        prov["status"] = "malformed"
        prov["reason"] = "a metrics file must be a flat object of scalars"
        return None, prov

    payload: Dict[str, Any] = {}
    for k, v in doc.items():
        prov["read"] += 1
        if _sm.value_defect(v) is not None:
            prov["skipped"].append({"key": k, "why": _sm.value_defect(v)})
            continue
        payload[orfs_key_to_schema_key(step, str(k))] = v
    if not payload:
        prov["status"] = "empty"
        prov["reason"] = ("the tool's metrics file carried no scalar this "
                          "schema can hold")
        return None, prov
    out = _sm.emit(Path(project), step, payload)
    prov["status"] = "emitted"
    prov["emitted"] = len(payload)
    return out, prov


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("wrap", help="print a command with -metrics wired in")
    w.add_argument("command")
    w.add_argument("--metrics-path", default=None)

    s = sub.add_parser("scan", help="list the OpenROAD invocations in a file")
    s.add_argument("path")

    g = sub.add_parser("ingest", help="republish a tool metrics file as step metrics")
    g.add_argument("project")
    g.add_argument("step")
    g.add_argument("metrics_json")
    g.add_argument("--json", dest="json_out", default=None)

    args = ap.parse_args(list(argv) if argv is not None else None)

    if args.cmd == "wrap":
        try:
            print(with_metrics(args.command, args.metrics_path))
        except WiringDefect as exc:
            print(f"[FAIL] {exc}", file=sys.stderr)
            return RC_VIOLATION
        return RC_OK

    if args.cmd == "scan":
        try:
            text = Path(args.path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"[NOT CHECKED] {exc}", file=sys.stderr)
            return RC_UNDETERMINED
        found = invocations(text)
        wired = sum(1 for i in found if i["has_metrics"])
        print(f"{len(found)} openroad invocation(s), {wired} carrying -metrics")
        for i in found:
            mark = "metrics" if i["has_metrics"] else "NO-METRICS"
            print(f"  {args.path}:{i['line']}  {mark:>10}  {i['text'][:110]}")
        return RC_OK if found else RC_UNDETERMINED

    out, prov = ingest(Path(args.project), args.step, Path(args.metrics_json))
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        # vibe-ic#1082 — a declared report is written through the atomic helper,
        # so an interrupted run leaves no half-written artefact for a downstream
        # gate to read as a measurement.
        _atomic_write_json(Path(args.json_out), prov, indent=1)
    print(f"[{prov['status']}] {prov.get('reason', '')}".rstrip())
    if prov["status"] != "emitted":
        return RC_UNDETERMINED
    print(f"emitted {prov['emitted']} metric(s) from {prov['read']} read -> {out}")
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())
