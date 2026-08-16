#!/usr/bin/env python3
"""Run repo hygiene as a fail-closed local parallel DAG.

Phase A assigns every gate except host-independence to exactly one measured
shard.  Phase B runs host-independence alone after deterministically merging
the exact process attestations produced by A.  This preserves the dependency
(``host`` consumes every Arm-A record) while removing every false serial edge.

No worker record, no verdict: missing/truncated summaries, duplicate or absent
labels, mismatched declarations, and incomplete attestations all return rc 2.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from _atomic_artefact import write_json, write_text
from hygiene_shard_plan import load_profile, plan

HOST_LABEL = "gates are host-independent"
DEFAULT_JOBS = 8
DEFAULT_WORKER_TIMEOUT = 1800


def _load_json(path: Path) -> Dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("top-level JSON is not an object")
    return doc


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict) or row.get("complete") is not True:
                raise ValueError(f"line {lineno} is not a complete attestation")
            rows.append(row)
    return rows


def _write_jsonl(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text(path, "".join(json.dumps(row, ensure_ascii=True,
                                         sort_keys=True) + "\n" for row in rows))
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _run(argv: List[str], cwd: Path, env: Dict[str, str], timeout: int):
    try:
        proc = subprocess.run(argv, cwd=str(cwd), env=env,
                              stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True,
                              timeout=timeout)
        return proc.returncode, proc.stdout or "", None
    except subprocess.TimeoutExpired as exc:
        body = (exc.stdout or "")
        if isinstance(body, bytes):
            body = body.decode("utf-8", "replace")
        return -9, body, f"did not finish within {timeout}s"
    except OSError as exc:
        return -1, "", f"could not launch: {exc}"


def _validate_declarations(reference: Dict[str, Any], doc: Dict[str, Any],
                           where: str) -> List[str]:
    problems: List[str] = []
    want = [str(g.get("label")) for g in reference.get("gates") or []]
    got = [str(g.get("label")) for g in doc.get("gates") or []]
    if got != want:
        problems.append(f"{where}: declaration order/set differs from --list")
    for key in ("corpora", "undisclosed_loops"):
        if doc.get(key) != reference.get(key):
            problems.append(f"{where}: {key} differs from --list declaration")
    if doc.get("listed_only"):
        problems.append(f"{where}: worker reported listed_only instead of running")
    if doc.get("shard") is None:
        problems.append(f"{where}: worker ignored its shard assignment")
    return problems


def merge_records(reference: Dict[str, Any], docs: List[Tuple[Path, Dict[str, Any]]],
                  attestations: List[Dict[str, Any]], elapsed: int,
                  problems: List[str]) -> Dict[str, Any]:
    """Build the dispatcher's full summary schema from exactly-once shards."""
    labels = [str(g["label"]) for g in reference.get("gates") or []]
    chosen: Dict[str, List[Dict[str, Any]]] = {label: [] for label in labels}
    for path, doc in docs:
        problems.extend(_validate_declarations(reference, doc, str(path)))
        for gate in doc.get("gates") or []:
            if gate.get("state") != "OTHER_SHARD":
                chosen.setdefault(str(gate.get("label")), []).append(gate)

    gates: List[Dict[str, Any]] = []
    for label in labels:
        rows = chosen.get(label, [])
        if len(rows) != 1:
            problems.append(
                f"{label!r}: expected one owning shard record, got {len(rows)}")
            # Preserve the declared denominator even in the refusal artefact.
            template = next(g for g in reference["gates"]
                            if str(g["label"]) == label)
            row = dict(template)
            row["state"] = "NOT_CHECKED"
            row["seconds"] = 0
            gates.append(row)
        else:
            gates.append(rows[0])
    extras = sorted(set(chosen) - set(labels))
    if extras:
        problems.append("unplanned labels ran: " + ", ".join(extras[:6]))

    by_label: Dict[str, List[Dict[str, Any]]] = {}
    for row in attestations:
        by_label.setdefault(str(row.get("label")), []).append(row)
    for label, gate in zip(labels, gates):
        should_have = gate.get("state") in ("PASS", "FAIL", "NOT_CHECKED",
                                             "WROTE_CORPUS")
        count = len(by_label.get(label, []))
        if should_have and count != 1:
            problems.append(
                f"{label!r}: expected one process attestation, got {count}")
    att_extra = sorted(set(by_label) - set(labels))
    if att_extra:
        problems.append("unplanned process attestations: "
                        + ", ".join(att_extra[:6]))

    count = lambda state: sum(g.get("state") == state for g in gates)
    wiring = sorted({str(item) for _, doc in docs
                     for item in (doc.get("wiring_errors") or [])})
    today = {str(doc.get("today")) for _, doc in docs}
    if len(today) != 1:
        problems.append("shards disagree on the run date")
    return {
        "listed_only": False,
        "declared": len(gates),
        "ran": sum(count(s) for s in
                   ("PASS", "FAIL", "NOT_CHECKED", "WROTE_CORPUS")),
        "decided": count("PASS") + count("FAIL"),
        "passed": count("PASS"),
        "failed": count("FAIL"),
        "not_checked": count("NOT_CHECKED"),
        "not_checked_unexempted": [str(g["label"]) for g in gates
                                    if g.get("state") == "NOT_CHECKED"
                                    and not g.get("exempt_until")],
        "exemptions_expired": [str(g["label"]) for g in gates
                               if g.get("exemption_expired")],
        "wiring_errors": wiring + [f"parallel coverage: {p}" for p in problems],
        "today": next(iter(today), str(reference.get("today") or "")),
        "wrote_corpus": count("WROTE_CORPUS"),
        "deferred": count("LISTED"),
        "other_shard": count("OTHER_SHARD"),
        "shard": None,
        "corpora": reference.get("corpora") or [],
        "undisclosed_loops": reference.get("undisclosed_loops") or [],
        "seconds": elapsed,
        "gates": gates,
        "process_attestations": attestations,
        "parallel": {"workers": len(docs) - 1,
                     "phases": ["independent-gates", "host-independence"],
                     "complete": not problems},
    }


def _summary_rc(doc: Dict[str, Any]) -> int:
    if doc.get("wiring_errors") or not int(doc.get("declared") or 0):
        return 2
    if doc.get("failed") or doc.get("wrote_corpus") \
            or doc.get("exemptions_expired"):
        return 1
    if not int(doc.get("decided") or 0):
        return 2
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--summary-json", type=Path, required=True)
    ap.add_argument("--jobs", type=int, default=DEFAULT_JOBS)
    ap.add_argument("--worker-timeout", type=int, default=DEFAULT_WORKER_TIMEOUT)
    args = ap.parse_args(argv)

    root = Path(__file__).resolve().parents[4]
    script = root / "tools" / "ci" / "repo_hygiene_gates.sh"
    profile_path = Path(__file__).resolve().parent / "hygiene_gate_profile.json"
    if args.jobs < 1 or args.worker_timeout < 1:
        print("[ERROR] jobs and worker-timeout must be positive", file=sys.stderr)
        return 2
    started = time.monotonic()
    problems: List[str] = []

    with tempfile.TemporaryDirectory(prefix="hygiene-parallel-") as td:
        tmp = Path(td)
        list_json = tmp / "list.json"
        list_env = os.environ.copy()
        list_env.pop("GATE_DISPATCH_ATTESTATION_FILE", None)
        list_rc, list_out, list_err = _run(
            ["bash", str(script), "--list", "--summary-json", str(list_json)],
            root, list_env, 120)
        if list_err or list_rc != 0 or not list_json.is_file():
            print("[ERROR] could not establish the hygiene denominator: "
                  + (list_err or list_out[-300:]), file=sys.stderr)
            return 2
        try:
            reference = _load_json(list_json)
        except (OSError, ValueError) as exc:
            print(f"[ERROR] unreadable denominator record: {exc}", file=sys.stderr)
            return 2
        labels = [str(g.get("label")) for g in reference.get("gates") or []]
        if labels.count(HOST_LABEL) != 1:
            print(f"[ERROR] expected exactly one {HOST_LABEL!r} declaration, "
                  f"got {labels.count(HOST_LABEL)}", file=sys.stderr)
            return 2
        phase_a_labels = [label for label in labels if label != HOST_LABEL]
        try:
            profile = load_profile(profile_path)
            jobs = min(args.jobs, len(phase_a_labels))
            buckets, unprofiled = plan(phase_a_labels, profile, jobs)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"[ERROR] cannot construct measured shard plan: {exc}",
                  file=sys.stderr)
            return 2
        if unprofiled:
            print("[INFO] unprofiled gates assigned with conservative cost: "
                  + ", ".join(unprofiled[:8]))

        total_shards = jobs + 1
        workers = []
        for i, bucket in enumerate(buckets):
            labels_path = tmp / f"labels-{i}.txt"
            labels_path.write_text("\n".join(bucket) + "\n", encoding="utf-8")
            summary = tmp / f"summary-{i}.json"
            attest = tmp / f"attest-{i}.jsonl"
            env = os.environ.copy()
            env["GATE_DISPATCH_ATTESTATION_FILE"] = str(attest)
            argv_i = ["bash", str(script), "--shard", f"{i}/{total_shards}",
                      "--shard-labels", str(labels_path),
                      "--summary-json", str(summary)]
            workers.append((i, bucket, summary, attest, argv_i, env))

        def run_worker(row):
            i, bucket, summary, attest, argv_i, env = row
            rc, out, err = _run(argv_i, root, env, args.worker_timeout)
            return i, bucket, summary, attest, rc, out, err

        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
            results = list(pool.map(run_worker, workers))

        docs: List[Tuple[Path, Dict[str, Any]]] = []
        a_attestations: List[Dict[str, Any]] = []
        for i, bucket, summary, attest, rc, out, err in sorted(results):
            print(f"=== hygiene shard {i}/{total_shards}: "
                  f"{len(bucket)} gate(s), rc={rc} ===")
            if out:
                print(out, end="" if out.endswith("\n") else "\n")
            if err:
                problems.append(f"shard {i}: {err}")
            if not summary.is_file():
                problems.append(f"shard {i}: no summary (rc={rc})")
                continue
            try:
                doc = _load_json(summary)
                rows = _load_jsonl(attest)
            except (OSError, ValueError) as exc:
                problems.append(f"shard {i}: incomplete machine record: {exc}")
                continue
            docs.append((summary, doc))
            a_attestations.extend(rows)

        # Establish exact Arm-A coverage before allowing the dependent phase.
        a_by_label: Dict[str, List[Dict[str, Any]]] = {}
        for row in a_attestations:
            a_by_label.setdefault(str(row.get("label")), []).append(row)
        for label in phase_a_labels:
            if len(a_by_label.get(label, [])) != 1:
                problems.append(
                    f"Arm A {label!r}: expected one attestation, got "
                    f"{len(a_by_label.get(label, []))}")
        if set(a_by_label) - set(phase_a_labels):
            problems.append("Arm A produced unplanned attestations")

        requested_attest = os.environ.get("GATE_DISPATCH_ATTESTATION_FILE")
        merged_attest = (Path(requested_attest).resolve() if requested_attest
                         else tmp / "merged-attest.jsonl")
        if not problems:
            ordered_a = [a_by_label[label][0] for label in phase_a_labels]
            _write_jsonl(merged_attest, ordered_a)
            host_labels = tmp / "labels-host.txt"
            host_labels.write_text(HOST_LABEL + "\n", encoding="utf-8")
            host_summary = tmp / "summary-host.json"
            host_env = os.environ.copy()
            host_env["GATE_DISPATCH_ATTESTATION_FILE"] = str(merged_attest)
            host_argv = ["bash", str(script), "--shard",
                         f"{jobs}/{total_shards}", "--shard-labels",
                         str(host_labels), "--summary-json", str(host_summary)]
            hrc, hout, herr = _run(host_argv, root, host_env,
                                   args.worker_timeout)
            print(f"=== hygiene dependent shard {jobs}/{total_shards}: "
                  f"1 gate, rc={hrc} ===")
            if hout:
                print(hout, end="" if hout.endswith("\n") else "\n")
            if herr:
                problems.append(f"host-independence shard: {herr}")
            if not host_summary.is_file():
                problems.append(f"host-independence shard: no summary (rc={hrc})")
            else:
                try:
                    docs.append((host_summary, _load_json(host_summary)))
                    all_attestations = _load_jsonl(merged_attest)
                except (OSError, ValueError) as exc:
                    problems.append(
                        f"host-independence shard: incomplete record: {exc}")
                    all_attestations = ordered_a
        else:
            print("[ERROR] dependent host-independence phase not launched: "
                  "Arm A coverage is incomplete", file=sys.stderr)
            all_attestations = a_attestations

        elapsed = int(time.monotonic() - started)
        final = merge_records(reference, docs, all_attestations, elapsed,
                              problems)
        write_json(args.summary_json, final, ensure_ascii=False)
        rc = _summary_rc(final)
        if problems:
            for problem in problems:
                print(f"  [COVERAGE] {problem}", file=sys.stderr)
            print(f"[ERROR] parallel hygiene incomplete after {elapsed}s; "
                  "coverage loss is not a result", file=sys.stderr)
            return 2
        print(f"[PASS] parallel hygiene DAG completed {final['decided']} of "
              f"{final['declared']} gate verdict(s) in {elapsed}s")
        return rc


if __name__ == "__main__":
    raise SystemExit(main())
