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
import atexit
import concurrent.futures
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import _crash_safe_scratch as _scratch
import _watchdog as _wd
from _atomic_artefact import write_json, write_text
from hygiene_shard_plan import load_profile, plan
from policy_direction_pin_check import acquire_run_lock, recover_all_journals

HOST_LABEL = "gates are host-independent"
# This gate already runs three pytest children concurrently and enforces a
# 60-second starvation bound.  Co-scheduling it with either the mutation farms
# or its opposite A/B arm made BOTH copies time out; the exact d6 subprocess
# completes in 43s alone.  It is therefore a resource-isolated A-then-B wave,
# not a logical dependency.  Every ordinary gate and both policy farms remain
# pipelined across A/B.
LOAD_SENSITIVE_LABELS = ("63x8 census freshness",)
DEFAULT_JOBS = 8
DEFAULT_STALL_GRACE_S = 300
DEFAULT_POLL_S = 5
_FRESH_PREFIX = "hygiene-fresh-"


def _unregister_fresh(scratch: Path) -> None:
    wt = scratch / "wt"
    if not wt.exists():
        return
    subprocess.run(["git", "-C", str(wt), "worktree", "unlock", str(wt)],
                   capture_output=True, text=True)
    subprocess.run(["git", "-C", str(wt), "worktree", "remove", "--force",
                    str(wt)], capture_output=True, text=True)


def _release_fresh(res: Any, repo: Path) -> None:
    _unregister_fresh(res.path)
    res.release()
    subprocess.run(["git", "-C", str(repo), "worktree", "prune"],
                   capture_output=True, text=True)


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


def _run(argv: List[str], cwd: Path, env: Dict[str, str], *,
         progress_path: Path | None = None,
         stall_grace_s: int = DEFAULT_STALL_GRACE_S):
    """Run until natural completion while supervising FORWARD PROGRESS.

    There is deliberately no whole-run timeout.  Output growth or a completed
    gate attestation resets the stall clock, so a slow but progressing shard is
    allowed to finish however long it needs.  Only a process that is both
    silent and making no recorded progress for ``stall_grace_s`` is killed.
    """
    def _popen(command, **kwargs):
        # One process group per shard lets a genuine stall kill the complete
        # descendant tree rather than only its wrapper shell.
        kwargs.pop("stderr", None)
        return subprocess.Popen(
            command, cwd=str(cwd), start_new_session=True,
            stderr=subprocess.STDOUT, **kwargs)

    def _kill_group(proc, _reason):
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        # The wrapper may have exited on TERM while a descendant ignored it.
        # Address the process GROUP even after wait() returned naturally.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    result = _wd.run_supervised(
        argv, env=env, log_path=progress_path,
        stall_grace_s=stall_grace_s, poll_s=DEFAULT_POLL_S,
        hard_ceiling_s=float("inf"), popen_factory=_popen,
        kill=_kill_group)
    body = (result.out or "") + (result.err or "")
    problem = None
    if result.outcome != "natural":
        problem = (f"progress watchdog outcome={result.outcome}, "
                   f"rc={result.rc}; the shard did not complete naturally")
    return result.rc, body, problem


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


def _needs_process_attestation(gate: Dict[str, Any]) -> bool:
    """Whether a denominator row represents an executed checker process.

    ``gate_dispatch_over`` records an empty expansion as a synthetic
    NOT_CHECKED row with the impossible real-item coordinate 0 of 0.  It is
    load-bearing coverage evidence, but no checker process existed to attest.
    Real corpus items are one-based, so this machine shape is unambiguous and
    avoids parsing a human-facing label.
    """
    return gate.get("execution") != "PRECOMPUTED_CORPUS"


_PRECOMPUTED_FIELDS = (
    "label", "state", "execution", "reason_code", "corpus", "corpus_item",
    "corpus_items", "exempt_until", "exempt_reason", "exemption_expired",
)


def _precomputed_arm_records(reference: Dict[str, Any],
                             docs: List[Tuple[Path, Dict[str, Any]]],
                             arm: str, problems: List[str]) -> Dict[str, Dict]:
    """Collect exactly one machine-authenticated precomputed row per label."""
    wanted = {str(g.get("label")): g
              for g in reference.get("gates") or []
              if g.get("execution") == "PRECOMPUTED_CORPUS"}
    found: Dict[str, Dict] = {}
    for label, template in wanted.items():
        rows = [gate for _, doc in docs for gate in (doc.get("gates") or [])
                if str(gate.get("label")) == label
                and gate.get("state") != "OTHER_SHARD"]
        if len(rows) != 1:
            problems.append(
                f"Arm {arm} precomputed {label!r}: expected one owning "
                f"summary record, got {len(rows)}")
            continue
        row = rows[0]
        if row.get("state") != "NOT_CHECKED":
            problems.append(
                f"Arm {arm} precomputed {label!r}: owner state is "
                f"{row.get('state')!r}, expected NOT_CHECKED")
        for field in _PRECOMPUTED_FIELDS:
            if field == "state":
                continue
            if row.get(field) != template.get(field):
                problems.append(
                    f"Arm {arm} precomputed {label!r}: {field} differs "
                    "from the declared record")
        found[label] = {field: row.get(field)
                        for field in _PRECOMPUTED_FIELDS}
    return found


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
        should_have = (_needs_process_attestation(gate)
                       and gate.get("state") in
                       ("PASS", "FAIL", "NOT_CHECKED", "WROTE_CORPUS"))
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
                     "phases": ["pipelined-a-b", "load-sensitive-wave",
                                "host-attestation-compare"],
                     "complete": not problems},
    }


def _summary_rc(doc: Dict[str, Any]) -> int:
    if doc.get("wiring_errors") or not int(doc.get("declared") or 0):
        return 2
    if doc.get("not_checked_unexempted"):
        return 2
    if doc.get("failed") or doc.get("wrote_corpus") \
            or doc.get("exemptions_expired"):
        return 1
    if not int(doc.get("decided") or 0):
        return 2
    return 0


def _completion_message(doc: Dict[str, Any], elapsed: int) -> str:
    prefix = "PASS" if _summary_rc(doc) == 0 else "FAIL"
    return (f"[{prefix}] parallel hygiene DAG completed {doc['decided']} of "
            f"{doc['declared']} gate verdict(s) in {elapsed}s; "
            f"failed={doc['failed']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--summary-json", type=Path, required=True)
    ap.add_argument("--jobs", type=int, default=DEFAULT_JOBS)
    ap.add_argument("--stall-grace", type=int, default=DEFAULT_STALL_GRACE_S,
                    help="seconds with neither output nor a completed gate "
                         "record before a shard is classified STALLED; this "
                         "is not a whole-run runtime limit")
    args = ap.parse_args(argv)

    root = Path(__file__).resolve().parents[4]
    script = root / "tools" / "ci" / "repo_hygiene_gates.sh"
    profile_path = Path(__file__).resolve().parent / "hygiene_gate_profile.json"
    if args.jobs < 1 or args.stall_grace < 1:
        print("[ERROR] jobs and stall-grace must be positive", file=sys.stderr)
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
            root, list_env, stall_grace_s=args.stall_grace)
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
        attested_phase_labels = [
            str(gate.get("label")) for gate in reference.get("gates") or []
            if str(gate.get("label")) != HOST_LABEL
            and _needs_process_attestation(gate)
        ]
        sensitive = [label for label in LOAD_SENSITIVE_LABELS
                     if label in phase_a_labels]
        primary_labels = [label for label in phase_a_labels
                          if label not in set(sensitive)]
        try:
            profile = load_profile(profile_path)
            jobs = min(args.jobs, len(primary_labels))
            buckets, unprofiled = plan(primary_labels, profile, jobs)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"[ERROR] cannot construct measured shard plan: {exc}",
                  file=sys.stderr)
            return 2
        if unprofiled:
            print("[INFO] unprofiled gates assigned with conservative cost: "
                  + ", ".join(unprofiled[:8]))

        # One lock protects the broad orphan-journal recovery for BOTH policy
        # arms.  The two policy parents then use keyed recovery and may overlap;
        # without this cohort the second parent can "repair" the first one's
        # live mutant underneath pytest.
        try:
            acquire_run_lock()
            recovery_rc, recovery_lines = recover_all_journals()
        except OSError as exc:
            print(f"[ERROR] cannot lock/recover policy mutation journals: {exc}",
                  file=sys.stderr)
            return 2
        for line in recovery_lines:
            print(line, file=sys.stderr if recovery_rc else sys.stdout)
        if recovery_rc:
            print("[ERROR] an abandoned policy mutation could not be recovered",
                  file=sys.stderr)
            return 2

        fresh_res, _ = _scratch.reserve(
            _FRESH_PREFIX, remover=_unregister_fresh)
        fresh_root = fresh_res.path / "wt"
        add = subprocess.run(
            ["git", "-C", str(root), "worktree", "add", "-q", "--detach",
             str(fresh_root), "HEAD"], capture_output=True, text=True,
        )
        if add.returncode != 0:
            fresh_res.release()
            print("[ERROR] could not create the pipelined fresh tree: "
                  + (add.stderr or add.stdout).strip()[:240], file=sys.stderr)
            return 2
        cleanup = lambda: _release_fresh(fresh_res, root)
        atexit.register(cleanup)

        total_shards = jobs + (1 if sensitive else 0) + 1
        requested_progress = os.environ.get("GATE_DISPATCH_ATTESTATION_FILE")
        if requested_progress:
            progress_path = Path(requested_progress).resolve()
            progress_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                progress_path.unlink()
            except FileNotFoundError:
                pass
        else:
            progress_path = None

        workers = []
        for i, bucket in enumerate(buckets):
            labels_path = tmp / f"labels-{i}.txt"
            labels_path.write_text("\n".join(bucket) + "\n", encoding="utf-8")
            for arm, arm_root in (("A", root), ("B", fresh_root)):
                summary = tmp / f"summary-{arm}-{i}.json"
                attest = tmp / f"attest-{arm}-{i}.jsonl"
                env = os.environ.copy()
                env["GATE_DISPATCH_ATTESTATION_FILE"] = str(attest)
                if arm == "A" and progress_path is not None:
                    env["GATE_DISPATCH_PROGRESS_FILE"] = str(progress_path)
                else:
                    env.pop("GATE_DISPATCH_PROGRESS_FILE", None)
                env["VIBEIC_POLICY_COHORT_LOCKED"] = "1"
                arm_script = arm_root / "tools" / "ci" / "repo_hygiene_gates.sh"
                argv_i = ["bash", str(arm_script), "--shard",
                          f"{i}/{total_shards}", "--shard-labels",
                          str(labels_path), "--summary-json", str(summary)]
                workers.append((arm, i, bucket, arm_root, summary, attest,
                                argv_i, env))

        def run_worker(row):
            arm, i, bucket, arm_root, summary, attest, argv_i, env = row
            rc, out, err = _run(
                argv_i, arm_root, env, progress_path=attest,
                stall_grace_s=args.stall_grace)
            return arm, i, bucket, summary, attest, rc, out, err

        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs * 2) as pool:
            results = list(pool.map(run_worker, workers))

        # Resource wave 2.  The census owns its machine while each arm runs.
        # A/B concurrency here reproducibly pushes a 43s-alone subprocess past
        # its honest 60s hang bound, so sequence the two outer arms while
        # retaining the census' measured three-way internal parallelism.
        if sensitive:
            sensitive_i = jobs
            labels_path = tmp / "labels-sensitive.txt"
            labels_path.write_text("\n".join(sensitive) + "\n",
                                   encoding="utf-8")
            sensitive_workers = []
            for arm, arm_root in (("A", root), ("B", fresh_root)):
                summary = tmp / f"summary-{arm}-sensitive.json"
                attest = tmp / f"attest-{arm}-sensitive.jsonl"
                env = os.environ.copy()
                env["GATE_DISPATCH_ATTESTATION_FILE"] = str(attest)
                if arm == "A" and progress_path is not None:
                    env["GATE_DISPATCH_PROGRESS_FILE"] = str(progress_path)
                else:
                    env.pop("GATE_DISPATCH_PROGRESS_FILE", None)
                env["VIBEIC_POLICY_COHORT_LOCKED"] = "1"
                arm_script = arm_root / "tools" / "ci" / "repo_hygiene_gates.sh"
                argv_i = ["bash", str(arm_script), "--shard",
                          f"{sensitive_i}/{total_shards}", "--shard-labels",
                          str(labels_path), "--summary-json", str(summary)]
                sensitive_workers.append(
                    (arm, sensitive_i, sensitive, arm_root, summary, attest,
                     argv_i, env))
            for row in sensitive_workers:
                results.append(run_worker(row))

        docs: List[Tuple[Path, Dict[str, Any]]] = []
        a_docs: List[Tuple[Path, Dict[str, Any]]] = []
        b_docs: List[Tuple[Path, Dict[str, Any]]] = []
        a_attestations: List[Dict[str, Any]] = []
        b_attestations: List[Dict[str, Any]] = []
        for arm, i, bucket, summary, attest, rc, out, err in sorted(results):
            print(f"=== hygiene arm {arm} shard {i}/{total_shards}: "
                  f"{len(bucket)} gate(s), rc={rc} ===")
            if out:
                print(out, end="" if out.endswith("\n") else "\n")
            if err:
                problems.append(f"arm {arm} shard {i}: {err}")
            if not summary.is_file():
                problems.append(f"arm {arm} shard {i}: no summary (rc={rc})")
                continue
            try:
                doc = _load_json(summary)
                rows = _load_jsonl(attest)
            except (OSError, ValueError) as exc:
                problems.append(
                    f"arm {arm} shard {i}: incomplete machine record: {exc}")
                continue
            problems.extend(_validate_declarations(
                reference, doc, f"arm {arm} shard {i}"))
            if arm == "B" and doc.get("wiring_errors"):
                problems.append(
                    f"arm B shard {i}: dispatcher wiring error(s): "
                    + "; ".join(str(x) for x in doc["wiring_errors"][:3]))
            if arm == "A":
                docs.append((summary, doc))
                a_docs.append((summary, doc))
                a_attestations.extend(rows)
            else:
                b_docs.append((summary, doc))
                b_attestations.extend(rows)

        # Establish exact A/B coverage before allowing the dependent comparison.
        a_by_label: Dict[str, List[Dict[str, Any]]] = {}
        b_by_label: Dict[str, List[Dict[str, Any]]] = {}
        for row in a_attestations:
            a_by_label.setdefault(str(row.get("label")), []).append(row)
        for row in b_attestations:
            b_by_label.setdefault(str(row.get("label")), []).append(row)
        a_precomputed = _precomputed_arm_records(
            reference, a_docs, "A", problems)
        b_precomputed = _precomputed_arm_records(
            reference, b_docs, "B", problems)
        if a_precomputed != b_precomputed:
            problems.append("Arm A/B precomputed corpus records differ")
        for label in attested_phase_labels:
            if len(a_by_label.get(label, [])) != 1:
                problems.append(
                    f"Arm A {label!r}: expected one attestation, got "
                    f"{len(a_by_label.get(label, []))}")
            if len(b_by_label.get(label, [])) != 1:
                problems.append(
                    f"Arm B {label!r}: expected one attestation, got "
                    f"{len(b_by_label.get(label, []))}")
        if set(a_by_label) - set(attested_phase_labels):
            problems.append("Arm A produced unplanned attestations")
        if set(b_by_label) - set(attested_phase_labels):
            problems.append("Arm B produced unplanned attestations")

        requested_attest = requested_progress
        merged_attest = (Path(requested_attest).resolve() if requested_attest
                         else tmp / "merged-attest.jsonl")
        fresh_attest = tmp / "fresh-attest.jsonl"
        if not problems:
            ordered_a = [a_by_label[label][0]
                         for label in attested_phase_labels]
            ordered_b = [b_by_label[label][0]
                         for label in attested_phase_labels]
            _write_jsonl(merged_attest, ordered_a)
            _write_jsonl(fresh_attest, ordered_b)
            host_labels = tmp / "labels-host.txt"
            host_labels.write_text(HOST_LABEL + "\n", encoding="utf-8")
            host_summary = tmp / "summary-host.json"
            host_env = os.environ.copy()
            host_env["GATE_DISPATCH_ATTESTATION_FILE"] = str(merged_attest)
            host_env["VIBEIC_HOST_FRESH_ATTESTATIONS"] = str(fresh_attest)
            host_env["VIBEIC_POLICY_COHORT_LOCKED"] = "1"
            host_i = jobs + (1 if sensitive else 0)
            host_argv = ["bash", str(script), "--shard",
                         f"{host_i}/{total_shards}", "--shard-labels",
                         str(host_labels), "--summary-json", str(host_summary)]
            hrc, hout, herr = _run(
                host_argv, root, host_env, progress_path=merged_attest,
                stall_grace_s=args.stall_grace)
            print(f"=== hygiene dependent shard {host_i}/{total_shards}: "
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
        _release_fresh(fresh_res, root)
        atexit.unregister(cleanup)
        rc = _summary_rc(final)
        if problems:
            for problem in problems:
                print(f"  [COVERAGE] {problem}", file=sys.stderr)
            print(f"[ERROR] parallel hygiene incomplete after {elapsed}s; "
                  "coverage loss is not a result", file=sys.stderr)
            return 2
        print(_completion_message(final, elapsed))
        return rc


if __name__ == "__main__":
    raise SystemExit(main())
