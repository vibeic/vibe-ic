#!/usr/bin/env python3
"""
provenance_check.py — Verify a file was produced by a logged tool run.

Pairs with provenance_logger.py. A flow gate asks:
    "does <project>/provenance.jsonl contain an entry that
     (a) names <tool> (in the allow-list),
     (b) exited 0,
     (c) declared <required_output> as one of its outputs, AND
     (d) whose logged hash still matches the file on disk?"

If yes → PASS. If no (no entry, wrong tool, hash mismatch, no file) → FAIL.

``--require-measured`` adds the question this check could never ask
-------------------------------------------------------------------
Everything above binds an ARTEFACT to a RUN. It has never asked whether that
run did any work, and MEASURED 2026-08-27 that is the gap a false sign-off
walks through: ``openroad`` executing the STA script exactly as ``eda_sta``
emitted it read no technology, linked no design, failed every report — and
**exited 0**. Every condition (a)–(d) above is satisfied by that run. The tool
named itself, the exit code was 0, the artefact hashed, and nothing measured
anything.

With ``--require-measured`` the bound entry must also carry the tool's own
``measurement`` record (see ``_mcp_measurement``), and there are THREE
outcomes, not two:

* ``measured: true``  → PASS, as before.
* ``measured: false`` with a hard class → **FAIL**, naming the class and the
  tool's own reason. This is the vacuous run, refused.
* **no record at all** → ``UNMEASURED``: the program prints an ``INCOMPLETE:``
  line and exits **0**. It is not a pass — ``flow_compliance_check`` reads that
  token and dispositions the step in the ``INCOMPLETE`` tier, which is counted
  and rendered separately from PASS and never counted into ``pass_count`` — and
  it is not a failure either, because treating "nobody stated this" as "the
  tool failed" converts an unmeasured thing into a bad result, which is the
  same lie pointing the other way. Every run predating this contract, and every
  artefact produced by a hand-run tool, lands here honestly.

``measured: false`` with the benign class ``NOTHING_TO_MEASURE`` PASSES: the
tool ran and there was legitimately nothing to judge. A gate that refuses that
refuses every design it applies to, and a gate that refuses everything gets
bypassed — which is a deleted gate.

Usage
-----
    provenance_check.py <project_dir> \\
        --output pnr/routed.def --tool openroad,openroad-flow-scripts \\
        --output pnr/drc.rpt    --tool klayout,openroad

Each --output/--tool pair is checked independently; all must pass.

    provenance_check.py <project_dir> --require-entries 5
        — simply asserts the log has >= 5 exit-0 entries (coarse sanity).

Exit codes
----------
    0 = every declared output has a matching valid log entry
    1 = one or more failed
    2 = usage / io error
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _mcp_measurement  # noqa: E402


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return "sha256:" + h.hexdigest()
    except OSError:
        return ""


def _load_log(project: Path) -> List[dict]:
    log = project / "provenance.jsonl"
    if not log.exists():
        return []
    entries: List[dict] = []
    with log.open() as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as exc:
                print(f"provenance_check: malformed line {i}: {exc}",
                      file=sys.stderr)
    return entries


def _bare_digest(value) -> str:
    """A digest with any `sha256:` prefix removed; "" when there is none."""
    s = str(value or "")
    return s[7:] if s.startswith("sha256:") else s


def _declares(entry: dict, out_rel: str, out_sha: str | None) -> bool:
    """Does this entry declare THIS artefact — by path, or by CONTENT?

    A path-only match calls a published artefact undeclared the moment the
    publisher moves it. MEASURED on the published corpus: three cells record
    `phase3/stage3/pnr/<top>.gds` in provenance and ship
    `phase3/stage4/gds/<top>.gds`, with a BYTE-IDENTICAL sha256 in both places.
    The run declared exactly this artefact; only its address changed.

    That is #448's ROUTED_AWAY distinction — "stored elsewhere" is not "never
    produced" — applied to provenance instead of citations. The digest is the
    stronger key anyway: a path match with a different digest would be a
    DIFFERENT file wearing the right name, and this rejects that too.
    """
    outputs = entry.get("outputs", {}) or {}
    if out_rel in outputs:
        return True
    # BOTH sides carry the `sha256:` prefix (`_sha256_file` emits it and the
    # log records it), so normalise both rather than one — stripping only the
    # recorded side compares a bare digest against a prefixed one and never
    # matches, which is exactly the silent no-op this guards against.
    want = _bare_digest(out_sha)
    if not want:
        return False
    return any(_bare_digest(rec) == want for rec in outputs.values())


def _find_entry(entries: List[dict], out_rel: str,
                allowed_tools: set,
                out_sha: str | None = None) -> Tuple[dict | None, List[str]]:
    """Return (matching_entry, reasons_if_none)."""
    reasons: List[str] = []
    matches = []
    for i, e in enumerate(entries):
        if not _declares(e, out_rel, out_sha):
            continue
        if e.get("exit_code", -1) != 0:
            reasons.append(f"entry {e.get('timestamp','?')} "
                           f"for {out_rel} has exit_code="
                           f"{e.get('exit_code')}")
            continue
        if allowed_tools and e.get("tool") not in allowed_tools:
            reasons.append(f"entry {e.get('timestamp','?')} "
                           f"tool '{e.get('tool')}' not in allowed "
                           f"{sorted(allowed_tools)}")
            continue
        matches.append((i, e))
    if not matches:
        if not reasons:
            reasons.append(f"no entry in provenance.jsonl declares "
                           f"'{out_rel}' as an output")
        return None, reasons
    # Pick the most recent matching entry. TIES BREAK TOWARD THE LATER LOG
    # POSITION, not the earlier one: `timestamp` is second-resolution, so a
    # correction written in the same second as the record it supersedes ties,
    # and a stable descending sort would then hand back the SUPERSEDED entry —
    # the opposite of "most recent". (The failure is safe-direction — the
    # superseded digest no longer matches the file, so the check FAILs rather
    # than passing — but it FAILs a corrected ledger for the wrong reason.)
    matches.sort(key=lambda ie: (ie[1].get("timestamp", ""), ie[0]),
                 reverse=True)
    return matches[0][1], []


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("project_dir")
    p.add_argument("--output", action="append", default=[],
                   help="Required output file path (relative to project). "
                        "Pair each with --tool (same index).")
    p.add_argument("--tool", action="append", default=[],
                   help="Comma-separated allowed tool names for the matching "
                        "--output at the same position.")
    p.add_argument("--require-entries", type=int, default=0,
                   help="Shortcut: pass if log has >= N exit-0 entries")
    p.add_argument("--require-measured", action="store_true",
                   help="Also require the bound run to carry positive evidence "
                        "it performed its work (the tool's own `measurement` "
                        "record). measured:false with a hard class FAILs; an "
                        "absent record is UNMEASURED — reported as INCOMPLETE "
                        "at rc 0, which is not a PASS and not a FAIL.")
    p.add_argument("--json", help="Write JSON report to this path")
    args = p.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"provenance_check: not a directory: {project}",
              file=sys.stderr)
        return 2

    entries = _load_log(project)

    report: Dict = {"project": str(project), "log_entries": len(entries),
                    "checks": []}

    # Coarse mode: just count exit-0 entries
    if args.require_entries > 0:
        exit0 = sum(1 for e in entries if e.get("exit_code") == 0)
        ok = exit0 >= args.require_entries
        report["require_entries"] = args.require_entries
        report["exit_zero_entries"] = exit0
        report["ok"] = ok
        if args.json:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(json.dumps(report, indent=2))
        print(f"provenance_check: {exit0} / {args.require_entries} "
              f"exit-0 entries {'OK' if ok else 'FAIL'}")
        return 0 if ok else 1

    if len(args.output) != len(args.tool):
        print("provenance_check: --output and --tool counts must match "
              f"(got {len(args.output)} outputs, {len(args.tool)} tools)",
              file=sys.stderr)
        return 2

    if not args.output:
        print("provenance_check: nothing to check; pass --output/--tool "
              "or --require-entries", file=sys.stderr)
        return 2

    overall_ok = True
    #: Artefacts whose bound run states nothing about whether it measured. They
    #: do not fail the gate and they do not pass it either.
    unmeasured: List[str] = []

    for out_rel_pattern, tools_csv in zip(args.output, args.tool):
        allowed = {t.strip() for t in tools_csv.split(",") if t.strip()}

        # Glob expansion (chip-AGNOSTIC): flow steps reference outputs by
        # pattern (e.g. `phase3/stage3/extracted/*.spef`) because the top
        # cell name is not known at manifest-authoring time. Without
        # expansion the literal `*.spef` path "exists on disk" check fails
        # and Step 22 false-FAILs on every chip whose SPEF is registered
        # under its concrete name. Expand the pattern to the actual file(s);
        # a non-glob path resolves to itself.
        if any(ch in out_rel_pattern for ch in "*?[") :
            matches = sorted(
                str(p.relative_to(project))
                for p in project.glob(out_rel_pattern)
                if p.is_file()
            )
            if not matches:
                check = {"output": out_rel_pattern, "allowed_tools": tools_csv,
                         "status": "FAIL",
                         "reasons": [f"no file on disk matches pattern: "
                                     f"{out_rel_pattern}"]}
                report["checks"].append(check)
                overall_ok = False
                continue
            out_rels = matches
        else:
            out_rels = [out_rel_pattern]

        # Check each concrete output resolved from the pattern.
        for out_rel in out_rels:
            check: Dict = {"output": out_rel, "allowed_tools": tools_csv,
                           "status": "FAIL", "reasons": []}

            # The file must exist on disk
            abs_out = project / out_rel
            if not abs_out.exists():
                check["reasons"].append(f"file on disk missing: {out_rel}")
                report["checks"].append(check)
                overall_ok = False
                continue

            disk_hash = _sha256_file(abs_out)

            # Find a matching entry
            entry, reasons = _find_entry(entries, out_rel, allowed, disk_hash)
            if entry is None:
                check["reasons"].extend(reasons)
                report["checks"].append(check)
                overall_ok = False
                continue

            # Hash match. The entry may declare this artefact under the path
            # the RUN wrote (`_declares` accepts a digest match), so resolve
            # the recorded hash the same way rather than assuming the
            # published path is a key — a KeyError here would turn a
            # successful match into a crash.
            logged_hash = entry["outputs"].get(out_rel)
            if logged_hash is None:
                want = _bare_digest(disk_hash)
                logged_hash = next(
                    (str(v) for v in entry["outputs"].values()
                     if _bare_digest(v) == want), disk_hash)
                check["declared_under"] = next(
                    (k for k, v in entry["outputs"].items()
                     if _bare_digest(v) == want), None)
            if _bare_digest(logged_hash) != _bare_digest(disk_hash):
                check["reasons"].append(
                    f"hash mismatch: log={logged_hash[:18]}... disk={disk_hash[:18]}..."
                    " — file modified after tool run, or log is stale"
                )
                check["logged_hash"] = logged_hash
                check["disk_hash"] = disk_hash
                report["checks"].append(check)
                overall_ok = False
                continue

            # ── THE MEASUREMENT QUESTION, asked where the binding is
            # decided. By here the artefact IS bound to an exit-0 run by this
            # tool; the only thing still unasked is whether that run did any
            # work.
            if args.require_measured:
                meas = _mcp_measurement.from_provenance_entry(entry)
                check["measurement"] = {
                    "declared": meas.declared,
                    "measured": meas.measured,
                    "not_measured_class": meas.reason_class,
                    "not_measured_reason": meas.reason,
                }
                if meas.hard_miss:
                    check["status"] = "FAIL"
                    check["reasons"].append(
                        f"the run bound to this artefact states it measured "
                        f"NOTHING [{meas.reason_class}]: {meas.reason} — the "
                        f"artefact exists and the tool exited 0, and neither "
                        f"is evidence the work was done")
                    report["checks"].append(check)
                    overall_ok = False
                    continue
                if meas.undeclared:
                    # NOT a failure and NOT a pass. See the module docstring.
                    check["status"] = "UNMEASURED"
                    check["reasons"].append(
                        f"the run bound to this artefact declares no "
                        f"measurement record, so whether {entry.get('tool')} "
                        f"performed its work is not stated anywhere — "
                        f"unmeasured, which is neither measured nor failed")
                    check["tool"] = entry.get("tool")
                    check["timestamp"] = entry.get("timestamp")
                    check["version"] = entry.get("version")
                    report["checks"].append(check)
                    unmeasured.append(out_rel)
                    continue

            check["status"] = "PASS"
            check["tool"] = entry.get("tool")
            check["timestamp"] = entry.get("timestamp")
            check["version"] = entry.get("version")
            report["checks"].append(check)

    report["ok"] = overall_ok
    report["unmeasured"] = unmeasured

    # Print summary
    print(f"\n=== provenance_check ({project.name}) ===")
    print(f"  log entries: {len(entries)}")
    for c in report["checks"]:
        # Three icons for three states. UNMEASURED wearing the failure mark
        # would put a thing nobody measured in the same column as a thing that
        # was measured and was wrong.
        icon = {"PASS": "✓", "UNMEASURED": "…"}.get(c["status"], "✗")
        print(f"  {icon} [{c['status']:<10}] {c['output']}")
        if c["status"] == "PASS":
            print(f"         via {c.get('tool')} @ {c.get('timestamp')}")
        else:
            for r in c["reasons"]:
                print(f"         - {r}")

    print(f"\nOverall: {'PASS' if overall_ok else 'FAIL'}")

    # THE DISCLOSURE THAT KEEPS AN UNMEASURED STEP OUT OF THE PASS COLUMN.
    # `flow_compliance_check._stdout_signals_token` reads a line beginning
    # `INCOMPLETE:` off a passing gate and dispositions the whole step into the
    # INCOMPLETE tier — counted and rendered separately, never added to
    # `pass_count`, and never a failure. That tier is exactly what "the tool
    # never said whether it did the work" means, so this prints it rather than
    # inventing a fourth vocabulary for the same fact.
    if overall_ok and unmeasured:
        # DETAIL FIRST, SENTINEL LAST, AND THE SENTINEL SHORT. The consumer
        # (`flow_compliance_check.output_snippet`) keeps only the LAST 300
        # characters of stdout and then requires the token to START A LINE, so
        # a single long line carrying both would lose the token to the tail cut
        # -- the disclosure would exist and be unreadable, which is the
        # "disclosure a path length can delete" failure this repo has already
        # measured once. The names go on their own line above; the sentinel
        # line is kept short enough to survive on its own.
        print(f"  unmeasured artefacts: {', '.join(unmeasured[:5])}"
              + (f" (+{len(unmeasured) - 5} more)" if len(unmeasured) > 5 else ""))
        print(f"INCOMPLETE: {len(unmeasured)} of {len(report['checks'])} "
              f"artefact(s) are bound to a run that declares no measurement "
              f"record; whether the tool performed its work was NOT examined.")

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report, indent=2))

    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
