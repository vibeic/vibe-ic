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

For a canonical synthesis alias selected by the native post-map handoff, a
Yosys-only allow-list names the immutable synthesis PARENT. The existing native
handoff validator must prove the current Yosys → OpenROAD transform; both real
writer records must bind, and ``--require-measured`` applies to both runs. The
reported terminal writer remains OpenROAD. Other outputs and tool filters keep
their ordinary terminal-writer meaning.

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
import _tool_log_provenance  # noqa: E402


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
                out_sha: str | None = None,
                project: Path | None = None) -> Tuple[dict | None, List[str]]:
    """Return (matching_entry, reasons_if_none).

    An entry that CLAIMS a witness (a row imported from an external flow's own
    step log, `_tool_log_provenance`, llv1 decision 4a) binds only when that
    witness re-verifies against `project`: a cited log that is gone, rewritten
    or not started by the flow is a fabricated witness, not a weaker one. A
    plain logged run or a #365 back-fill claims none and is judged as before.
    A witness whose reader-free evidence all holds but which the flow-log
    reader may not judge (UNCALIBRATED) still binds; `main` then reports that
    artefact NOT_MEASURED, never PASS, unless the run states it measured
    nothing (a --require-measured hard miss, which FAILs first).
    """
    reasons: List[str] = []
    matches = []
    for i, e in enumerate(entries):
        if not _declares(e, out_rel, out_sha):
            continue
        if _tool_log_provenance.claims_witness(e):
            ok, why = (_tool_log_provenance.verify_witness(e, project)
                       if project is not None else
                       (False, "no project to re-read the witness against"))
            if ok is not True and ok != _tool_log_provenance.UNCALIBRATED:
                reasons.append(f"entry {e.get('timestamp','?')} for {out_rel} "
                               f"claims a witness that does not hold: {why}")
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


def _synthesis_chain(project: Path, entries: List[dict], out_rel: str,
                     allowed: set, cache: dict) -> dict | None:
    """Bind a selected native post-map child to its required Yosys parent.

    This route is only for the canonical synthesis aliases and a Yosys-only
    caller. Ordinary tool filters retain their terminal-writer meaning. The
    existing native handoff validator, not a ledger label or a newer hash,
    proves the transform before the two actual writers are consumed.
    """
    if not allowed or not allowed <= {"yosys", "yosys-abc"}:
        return None
    import _path_layout as layout
    directory = layout.synth_dir(project)
    if (project / out_rel).parent != directory:
        return None
    canonical = str((directory / "netlist.v").relative_to(project))
    try:
        mapped = layout.mapped_synth_netlist(project)
    except (OSError, ValueError, TypeError, AttributeError):
        mapped = None
    aliases = {canonical}
    if mapped is not None:
        aliases.add(str(mapped.relative_to(project)))
    if out_rel not in aliases:
        return None
    try:
        doc = json.loads((directory / "synth_inputs.json").read_text())
        binding = (doc.get("librelane_synthesis") or {}) if isinstance(doc, dict) else {}
        child = binding.get("post_map") if isinstance(binding, dict) else None
    except (OSError, ValueError, TypeError):
        child = None
    try:
        switch = json.loads((project / "phase3/librelane_switch.json").read_text())
        requested = isinstance(switch, dict) and switch.get("post_map_repair", "off") != "off"
    except (OSError, ValueError):
        requested = False
    if child is None and not requested:
        return None
    key = tuple(sorted(allowed))
    if key in cache:
        return cache[key]
    try:
        import synth_handoff_netlist_check as handoff
        native = handoff.bound_handoff(project)
        if not native or native.get("verdict") != "PASS":
            detail = "; ".join((native or {}).get("findings") or ["native handoff absent"])
            raise ValueError(detail)
        if native.get("producer") != "LibreLane.Yosys.Synthesis -> Vibeic.PostMapRepair":
            raise ValueError("requested post-map handoff has no verified native transform")
        parent = Path(native["parent"])
        terminal = Path(native["native"])
        parent_rel = str(parent.relative_to(project))
        terminal_rel = str(terminal.relative_to(project))
        verified_aliases = {str(Path(native[name]).relative_to(project))
                            for name in ("canonical", "mapped")}
        if out_rel not in verified_aliases:
            raise ValueError("output is not a verified post-map synthesis alias")
        parent_sha = _sha256_file(parent)
        parent_entry, reasons = _find_entry(entries, parent_rel, allowed, parent_sha, project)
        if parent_entry is None:
            raise ValueError("native Yosys parent: " + "; ".join(reasons))
        declared = parent_entry.get("outputs", {}).get(parent_rel)
        if declared is None:
            declared = next((value for value in parent_entry.get("outputs", {}).values()
                             if _bare_digest(value) == _bare_digest(parent_sha)), None)
        if not parent_sha or _bare_digest(declared) != _bare_digest(parent_sha):
            raise ValueError("native Yosys parent provenance hash mismatch")
        # A generic OpenROAD record is not a post-map invocation. Its native
        # identity has been checked above; now require its real publisher row.
        terminal_rows = [row for row in entries
                         if row.get("record") == "artefact"
                         and row.get("produced_by") == "Vibeic.PostMapRepair"]
        terminal_sha = _sha256_file(terminal)
        terminal_entry, reasons = _find_entry(
            terminal_rows, out_rel, {"openroad"}, terminal_sha, project)
        if terminal_entry is None:
            raise ValueError("native post-map child: " + "; ".join(reasons))
        result = {"entry": terminal_entry, "parent_entry": parent_entry,
                  "evidence": {
                      "contract": "verified_native_synthesis_postmap_chain",
                      "allowed_tools_scope": "native_yosys_parent",
                      "parent": {"path": parent_rel, "sha256": parent_sha,
                                 "tool": parent_entry["tool"]},
                      "child": {"path": terminal_rel, "sha256": terminal_sha,
                                "tool": terminal_entry["tool"],
                                "produced_by": terminal_entry["produced_by"]},
                      "native_handoff": native["producer"]}}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result = {"error": "native synthesis lineage invalid: " + str(exc)}
    cache[key] = result
    return result


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
    p.add_argument("--pnr-netlist", action="store_true",
                   help="Check the technology-MAPPED synthesis netlist PnR "
                        "routes (named by phase 3 step_synth's "
                        "synth_inputs.json) as the FIRST output; the first "
                        "--tool pairs with it.")
    p.add_argument("--json", help="Write JSON report to this path")
    args = p.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"provenance_check: not a directory: {project}",
              file=sys.stderr)
        return 2

    if args.pnr_netlist:
        # The generic pre-map netlist.v is not what PnR routes; its entry in
        # provenance.jsonl says nothing about the mapped netlist (U11).
        import _path_layout as _pl  # noqa: PLC0415
        mapped = _pl.mapped_synth_netlist(project)
        if mapped is None:
            report = {"project": str(project), "verdict": "NOT_MEASURED",
                      "reason_class": "ASKED_BEFORE_PRODUCER",
                      "reason": ("no mapped synthesis netlist named by "
                                 f"{_pl.SYNTH_INPUTS_SIDECAR}: phase 3's "
                                 "step_synth has not produced the netlist "
                                 "PnR routes")}
            if args.json:
                Path(args.json).parent.mkdir(parents=True, exist_ok=True)
                Path(args.json).write_text(json.dumps(report, indent=2))
            print(f"provenance_check: NOT_MEASURED — {report['reason']}")
            return 2
        args.output.insert(0, str(mapped.relative_to(project)))

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

    # Step 9's clause names the declared GENERIC arm `<synth>/netlist.v`. The
    # netlist PnR routes is the MAPPED arm beside it; when it exists its
    # provenance is required too, under the same tools (U11).
    try:
        import _path_layout as _pl  # noqa: PLC0415
        _generic = str(_pl.synth_dir(project).relative_to(project) / "netlist.v")
        _mapped = _pl.mapped_synth_netlist(project)
    except (ImportError, ValueError, OSError):
        _generic, _mapped = None, None
    if _mapped is not None and _generic in args.output:
        _mrel = str(_mapped.relative_to(project))
        if _mrel not in args.output:
            args.output.append(_mrel)
            args.tool.append(args.tool[args.output.index(_generic)])
            report["pnr_netlist_companion"] = _mrel

    overall_ok = True
    #: Artefacts whose bound run states nothing about whether it measured. They
    #: do not fail the gate and they do not pass it either.
    unmeasured: List[str] = []
    #: Artefacts whose claimed witness the flow-log reader may not judge
    #: (instrument_calibration's contract: NOT_MEASURED, never a FAIL).
    uncalibrated: List[str] = []
    synthesis_chains: dict = {}

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
            chain = _synthesis_chain(project, entries, out_rel, allowed, synthesis_chains)
            parent_entry = None
            if chain is not None:
                if "error" in chain:
                    check["reasons"].append(chain["error"])
                    report["checks"].append(check)
                    overall_ok = False
                    continue
                entry, reasons = chain["entry"], []
                parent_entry = chain["parent_entry"]
                check["synthesis_lineage"] = json.loads(json.dumps(chain["evidence"]))
            else:
                entry, reasons = _find_entry(entries, out_rel, allowed, disk_hash,
                                              project)
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

            # A witness the flow-log reader may not judge. `_find_entry` bound
            # it only after every check that needs no reader held, and it is
            # reported NOT_MEASURED only AFTER the --require-measured hard
            # miss below: a run that states it measured nothing is a FAIL
            # whether or not its witness can be judged.
            unjudged = None
            for source in [entry] + ([parent_entry] if parent_entry is not None else []):
                if _tool_log_provenance.claims_witness(source):
                    ok, why = _tool_log_provenance.verify_witness(source, project)
                    if ok == _tool_log_provenance.UNCALIBRATED:
                        unjudged = why

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
                parent_meas = (_mcp_measurement.from_provenance_entry(parent_entry)
                               if parent_entry is not None else None)
                if parent_meas is not None:
                    check["synthesis_lineage"]["parent"]["measurement"] = {
                        "declared": parent_meas.declared, "measured": parent_meas.measured,
                        "not_measured_class": parent_meas.reason_class,
                        "not_measured_reason": parent_meas.reason}
                hard = meas if meas.hard_miss else (
                    parent_meas if parent_meas is not None and parent_meas.hard_miss else None)
                if hard is not None:
                    check["status"] = "FAIL"
                    check["reasons"].append(
                        f"the run bound to this artefact states it measured "
                        f"NOTHING [{hard.reason_class}]: {hard.reason} — the "
                        f"artefact exists and the tool exited 0, and neither "
                        f"is evidence the work was done")
                    report["checks"].append(check)
                    overall_ok = False
                    continue

            if unjudged is not None:
                check["status"] = "NOT_MEASURED"
                check["reason_class"] = "uncalibrated"
                check["reasons"].append(
                    f"the witness of the run bound to this artefact could "
                    f"not be judged: {unjudged}")
                report["checks"].append(check)
                uncalibrated.append(out_rel)
                continue

            if args.require_measured:
                if meas.undeclared or (parent_meas is not None and parent_meas.undeclared):
                    # NOT a failure and NOT a pass. See the module docstring.
                    check["status"] = "UNMEASURED"
                    check["reasons"].append(
                        f"the run bound to this artefact declares no "
                        f"measurement record, so whether "
                        f"{(parent_entry if parent_meas is not None and parent_meas.undeclared else entry).get('tool')} "
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
    report["uncalibrated"] = uncalibrated

    # Print summary
    print(f"\n=== provenance_check ({project.name}) ===")
    print(f"  log entries: {len(entries)}")
    for c in report["checks"]:
        # Three icons for three states. UNMEASURED wearing the failure mark
        # would put a thing nobody measured in the same column as a thing that
        # was measured and was wrong.
        icon = {"PASS": "✓", "UNMEASURED": "…",
                "NOT_MEASURED": "…"}.get(c["status"], "✗")
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
    if overall_ok and uncalibrated and not unmeasured:
        print(f"  witness not judged (uncalibrated reader): "
              f"{', '.join(uncalibrated[:5])}"
              + (f" (+{len(uncalibrated) - 5} more)" if len(uncalibrated) > 5 else ""))
        print(f"INCOMPLETE: {len(uncalibrated)} of {len(report['checks'])} "
              f"artefact(s) cite a witness the flow-log reader may not judge; "
              f"NOT_MEASURED, reason_class uncalibrated.")
    if overall_ok and unmeasured:
        if uncalibrated:
            print(f"  witness not judged (uncalibrated reader): "
                  f"{', '.join(uncalibrated[:5])}")
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
