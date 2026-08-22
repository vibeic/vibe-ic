#!/usr/bin/env python3
"""Verify the content-based three-shard harvest consolidation.

The deletion boundary is deliberately stricter than commit ancestry.  Vibe-IC
uses squash landing, so ancestry cannot prove that a worktree's bytes landed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path


EXPECTED_SHARD_COUNTS = {"a": 114, "b": 131, "c": 110}
EXPECTED_TOTAL = 355
EXPECTED_LITERAL_PATHS = 349
EXPECTED_TMP_PATHS = 16
EXPECTED_RESCUE_MANIFEST_ROWS = 530
EXPECTED_RESCUED_COMMITS = 3039
EXPECTED_BUNDLE_FILES = 164
EXPECTED_BUNDLE_SHA256 = (
    "1ea1e03def8d0b7a7e7d09cf12da7dbbafe3f16d529024a1b61b35149b88a677"
)
EXPECTED_BUNDLE_SHA1 = "25b4dd5aa43280bb03c536ffd5a371b1c5fcb6f4"
EXPECTED_BUNDLE_HEAD = "f0ee47468cbc68fcbc70465cc7ecc4f864d2f3c7"
ALLOWED_VERDICTS = {"RECOVER", "ABANDON", "LANDED", "UNREACHABLE"}
DELETION_BOUND = {"ABANDON", "LANDED"}
CONTENT_MARKERS = (
    "sha256",
    "byte for byte",
    "blob",
    "tree",
    "uncommitted",
    "content",
    "nadd=",
    "lines",
    "differ",
    "absent",
    "identical",
    "hash",
    "main has held",
    "working tree",
)
UNCOMMITTED_MARKERS = (
    "uncommitted",
    "held by no commit",
    "on disk only",
    "one disk only",
    "tracked_mods",
)
PROTECTED_UNCOMMITTED = {
    "/home/reyerchu/_agentjob_i1015/wt",
    "/home/reyerchu/_agent_scratch_whatif/wt_C",
    "/home/reyerchu/_wt_1236",
    "/home/reyerchu/_wt_1486",
    "/home/reyerchu/_a1456",
}


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def read_tsv(path: Path, header: list[str]) -> list[list[str]]:
    require(path.is_file(), f"missing file: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle, delimiter="\t"))
    require(bool(rows), f"empty TSV: {path}")
    require(rows[0] == header, f"bad header in {path}: {rows[0]!r}")
    for line_number, row in enumerate(rows[1:], 2):
        require(
            len(row) == len(header),
            f"{path}:{line_number}: expected {len(header)} fields, got {len(row)}",
        )
    return rows[1:]


def run(command: list[str], *, cwd: Path | None = None, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    require(
        result.returncode == 0,
        f"command failed rc={result.returncode}: {' '.join(command)}\n{result.stdout}",
    )
    return result


def digest(path: Path, algorithm: str) -> str:
    value = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def read_inputs(root: Path) -> tuple[dict[str, list[dict[str, str]]], dict[str, list[dict[str, str]]]]:
    sources: dict[str, list[dict[str, str]]] = {}
    verdicts: dict[str, list[dict[str, str]]] = {}
    source_header = ["host", "path", "repo", "head", "branch", "kind", "prior_verdict", "notes"]
    verdict_header = ["path", "verdict", "evidence"]

    for shard, expected in EXPECTED_SHARD_COUNTS.items():
        source_rows = read_tsv(root / f"_harv_shard_{shard}.tsv", source_header)
        verdict_rows = read_tsv(root / f"verdicts_shard_{shard}.tsv", verdict_header)
        require(len(source_rows) == expected, f"shard {shard}: source count {len(source_rows)} != {expected}")
        require(len(verdict_rows) == expected, f"shard {shard}: verdict count {len(verdict_rows)} != {expected}")

        sources[shard] = [dict(zip(source_header, row)) for row in source_rows]
        verdicts[shard] = [dict(zip(verdict_header, row)) for row in verdict_rows]
        require(
            Counter(row["path"] for row in sources[shard])
            == Counter(row["path"] for row in verdicts[shard]),
            f"shard {shard}: source/verdict path multisets differ",
        )

        for row in verdicts[shard]:
            require(row["path"].startswith("/"), f"shard {shard}: path is not absolute: {row['path']}")
            require(row["verdict"] in ALLOWED_VERDICTS, f"shard {shard}: bad verdict: {row['verdict']}")
            evidence = row["evidence"].lower()
            require(
                any(marker in evidence for marker in CONTENT_MARKERS),
                f"shard {shard}: ancestry-only or unmeasured evidence: {row['path']}",
            )
            if row["verdict"] in DELETION_BOUND:
                require(
                    not any(marker in evidence for marker in UNCOMMITTED_MARKERS),
                    f"shard {shard}: uncommitted rescue is deletion-bound: {row['path']}",
                )
    return sources, verdicts


def identify_source(path: str, evidence: str, candidates: list[dict[str, str]]) -> dict[str, str]:
    if len(candidates) == 1:
        return candidates[0]

    host_matches = re.findall(r"\b(?:on\s+)?host\s+(\d+)\b", evidence, flags=re.IGNORECASE)
    by_host = [row for row in candidates if row["host"] in host_matches]
    if len(by_host) == 1:
        return by_host[0]

    by_head = [row for row in candidates if row["head"][:11] in evidence]
    require(len(by_head) == 1, f"cannot disambiguate duplicate path {path!r} by host or HEAD")
    return by_head[0]


def build_joined(
    sources: dict[str, list[dict[str, str]]], verdicts: dict[str, list[dict[str, str]]]
) -> list[list[str]]:
    joined: list[list[str]] = []
    for shard in ("a", "b", "c"):
        candidates_by_path: dict[str, list[dict[str, str]]] = defaultdict(list)
        for source in sources[shard]:
            candidates_by_path[source["path"]].append(source)
        used: set[int] = set()
        for verdict in verdicts[shard]:
            remaining = [
                row
                for row in candidates_by_path[verdict["path"]]
                if id(row) not in used
            ]
            source = identify_source(verdict["path"], verdict["evidence"], remaining)
            used.add(id(source))
            joined.append(
                [source["host"], verdict["path"], verdict["verdict"], verdict["evidence"], shard]
            )
        require(len(used) == len(sources[shard]), f"shard {shard}: not every source row was consumed")
    return joined


def write_joined(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["host", "path", "verdict", "evidence", "shard"])
        writer.writerows(rows)


def verify_joined(root: Path, joined: list[list[str]]) -> dict[str, int]:
    total = len(joined)
    require(total == EXPECTED_TOTAL, f"joined total {total} != {EXPECTED_TOTAL}")
    require(total >= 355, f"joined acceptance requires >=355, got {total}")

    host_path_keys = [(row[0], row[1]) for row in joined]
    require(len(set(host_path_keys)) == total, "duplicate (host,path) ledger key")
    literal_path_counts = Counter(row[1] for row in joined)
    require(len(literal_path_counts) == EXPECTED_LITERAL_PATHS, "unexpected distinct literal-path count")
    duplicated_literals = sum(1 for count in literal_path_counts.values() if count > 1)
    require(duplicated_literals == 6, f"expected 6 duplicated literal paths, got {duplicated_literals}")
    tmp_paths = sum(1 for row in joined if row[1].startswith("/tmp/"))
    require(tmp_paths == EXPECTED_TMP_PATHS, f"expected {EXPECTED_TMP_PATHS} /tmp paths, got {tmp_paths}")

    checked_in = read_tsv(
        root / "verdicts_joined.tsv", ["host", "path", "verdict", "evidence", "shard"]
    )
    require(checked_in == joined, "verdicts_joined.tsv is stale; regenerate with --write-joined")
    verdict_counts = Counter(row[2] for row in joined)
    return {
        "total": total,
        "literal_paths": len(literal_path_counts),
        "duplicate_literals": duplicated_literals,
        "tmp_paths": tmp_paths,
        **{f"verdict_{key.lower()}": verdict_counts[key] for key in sorted(ALLOWED_VERDICTS)},
    }


def verify_overlays(root: Path, joined: list[list[str]]) -> None:
    correction_a = read_tsv(
        root / "CORRECTION_shard_a_false_landed.tsv", ["path", "verdict", "evidence"]
    )
    require(len(correction_a) == 4, f"expected 4 shard-A corrections, got {len(correction_a)}")
    a_rows = {row[1]: row[2:4] for row in joined if row[4] == "a"}
    for path, verdict, evidence in correction_a:
        require(a_rows.get(path) == [verdict, evidence], f"shard-A correction not canonical: {path}")

    correction_c = read_tsv(
        root / "CORRECTION_unreachable_resolved_false_landed.tsv",
        ["host", "path", "verdict", "evidence"],
    )
    require(len(correction_c) == 1, f"expected 1 shard-C correction, got {len(correction_c)}")
    joined_by_key = {(row[0], row[1]): row for row in joined}
    for host, path, verdict, evidence in correction_c:
        require(joined_by_key[(host, path)][2] == verdict, f"shard-C correction not canonical: {path}")
        require("uncommitted" in evidence.lower(), f"shard-C correction lost uncommitted evidence: {path}")

    protected_rows = [row for row in joined if row[1] in PROTECTED_UNCOMMITTED]
    require(len(protected_rows) == len(PROTECTED_UNCOMMITTED), "not all protected uncommitted rows are present")
    for row in protected_rows:
        require(
            row[2] == "RECOVER",
            f"uncommitted rescue must be RECOVER, never safe-to-delete: host={row[0]} path={row[1]}",
        )
        require("uncommitted" in row[3].lower(), f"protected row lost uncommitted evidence: {row[1]}")


def verify_preserved_files(root: Path) -> dict[str, int]:
    rows = read_tsv(
        root / "preserved_untracked_s7" / "MANIFEST.tsv",
        ["original_absolute_path", "host", "shard_c_row", "verdict", "sha256", "preserved_as"],
    )
    require(len(rows) == 4, f"expected 4 preserved untracked files, got {len(rows)}")
    repo_root = root.parent.parent
    for original, _host, shard_path, verdict, expected, preserved_as in rows:
        require(original.startswith("/"), f"preserved source path is not absolute: {original}")
        require(shard_path.startswith("/"), f"preserved shard path is not absolute: {shard_path}")
        require(verdict == "RECOVER", f"preserved untracked file is not RECOVER: {original}")
        require(re.fullmatch(r"[0-9a-f]{64}", expected) is not None, f"bad sha256: {expected}")
        require(digest(repo_root / preserved_as, "sha256") == expected, f"preserved sha256 mismatch: {original}")
    return {"preserved_untracked": len(rows)}


def verify_commit_objects(root: Path) -> dict[str, int]:
    manifest_rows = read_tsv(
        root / "rescue_consolidated_manifest_jharv3.tsv",
        ["rescue_ref", "sha", "already_on_live_origin"],
    )
    require(
        len(manifest_rows) == EXPECTED_RESCUE_MANIFEST_ROWS,
        f"rescue manifest rows {len(manifest_rows)} != {EXPECTED_RESCUE_MANIFEST_ROWS}",
    )
    require(all(row[2] == "NO" for row in manifest_rows), "rescue manifest live-origin state changed")

    rescued_commits = (root / "rescued_commits.txt").read_text(encoding="utf-8").splitlines()
    require(len(rescued_commits) == EXPECTED_RESCUED_COMMITS, "rescued_commits.txt row count changed")
    require(len(set(rescued_commits)) == len(rescued_commits), "duplicate rescued commit SHA")

    preserved_tips = read_tsv(root / "preserved_tips.tsv", ["commit", "ref", "files", "what"])
    require(len(preserved_tips) == 3, f"expected 3 preserved tips, got {len(preserved_tips)}")
    object_ids = [row[1] for row in manifest_rows] + rescued_commits + [row[0] for row in preserved_tips]
    require(all(re.fullmatch(r"[0-9a-f]{40}", oid) for oid in object_ids), "malformed rescue commit SHA")

    repo = Path(run(["git", "-C", str(root), "rev-parse", "--show-toplevel"]).stdout.strip())
    checked = run(
        ["git", "cat-file", "--batch-check=%(objectname) %(objecttype)"],
        cwd=repo,
        input_text="\n".join(object_ids) + "\n",
    ).stdout.splitlines()
    require(len(checked) == len(object_ids), "git cat-file returned an incomplete rescue-object result")
    missing = [line for line in checked if not line.endswith(" commit")]
    require(not missing, f"rescue SHAs missing or not commits: {missing[:3]}")
    reachable = set(run(["git", "rev-list", "HEAD"], cwd=repo).stdout.splitlines())
    unreachable = sorted({oid for oid in object_ids if oid not in reachable})
    require(
        not unreachable,
        f"rescue commit SHAs exist but are not reachable from HEAD: {unreachable[:3]}",
    )
    return {
        "rescue_manifest_rows": len(manifest_rows),
        "rescued_commits": len(rescued_commits),
        "preserved_tips": len(preserved_tips),
    }


def verify_bundle(root: Path, *, full: bool) -> dict[str, str | int]:
    bundle = root / "rescue" / "rescue-2026-08-22.bundle"
    require(bundle.is_file(), f"missing rescue bundle: {bundle}")
    sha256 = digest(bundle, "sha256")
    sha1 = digest(bundle, "sha1")
    require(sha256 == EXPECTED_BUNDLE_SHA256, f"bundle sha256 mismatch: {sha256}")
    require(sha1 == EXPECTED_BUNDLE_SHA1, f"bundle sha1 mismatch: {sha1}")

    manifest_rows = read_tsv_without_header(root / "rescue" / "MANIFEST.sha1", 2)
    require(len(manifest_rows) == EXPECTED_BUNDLE_FILES, f"bundle manifest rows != {EXPECTED_BUNDLE_FILES}")
    manifest = {path: oid for oid, path in manifest_rows}
    require(len(manifest) == EXPECTED_BUNDLE_FILES, "duplicate path in bundle manifest")
    require(all(re.fullmatch(r"[0-9a-f]{40}", oid) for oid in manifest.values()), "bad bundle blob SHA1")

    verify_output = run(["git", "bundle", "verify", str(bundle)]).stdout
    require("complete history" in verify_output.lower(), "bundle does not assert complete history")
    heads = run(["git", "bundle", "list-heads", str(bundle)]).stdout.splitlines()
    require(any(line.startswith(EXPECTED_BUNDLE_HEAD + " HEAD") for line in heads), "unexpected bundle HEAD")

    restored_files = 0
    fsck_rc = "not-run"
    if full:
        with tempfile.TemporaryDirectory(prefix="charvest-bundle-") as temp:
            checkout = Path(temp) / "restore"
            run(["git", "clone", "--quiet", str(bundle), str(checkout)])
            restored_head = run(["git", "rev-parse", "HEAD"], cwd=checkout).stdout.strip()
            require(restored_head == EXPECTED_BUNDLE_HEAD, f"restored HEAD mismatch: {restored_head}")
            run(["git", "fsck", "--full", "--strict"], cwd=checkout)
            fsck_rc = "0"
            tree_lines = run(["git", "ls-tree", "-r", "HEAD"], cwd=checkout).stdout.splitlines()
            tree: dict[str, str] = {}
            for line in tree_lines:
                metadata, path = line.split("\t", 1)
                _mode, object_type, oid = metadata.split()
                require(object_type == "blob", f"non-blob in rescue tree: {path}")
                tree[path] = oid
            require(tree == manifest, "restored bundle tree does not exactly match MANIFEST.sha1")
            restored_files = len(tree)

    return {
        "bundle_sha256": sha256,
        "bundle_sha1": sha1,
        "bundle_manifest_files": len(manifest),
        "restored_files": restored_files,
        "restore_fsck_rc": fsck_rc,
    }


def read_tsv_without_header(path: Path, fields: int) -> list[list[str]]:
    require(path.is_file(), f"missing file: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle, delimiter="\t"))
    for line_number, row in enumerate(rows, 1):
        require(len(row) == fields, f"{path}:{line_number}: expected {fields} fields, got {len(row)}")
    return rows


def validate(root: Path, *, check_joined_file: bool, full_bundle: bool, check_objects: bool) -> tuple[list[list[str]], dict[str, str | int]]:
    sources, verdicts = read_inputs(root)
    joined = build_joined(sources, verdicts)
    verify_overlays(root, joined)
    stats: dict[str, str | int] = {}
    if check_joined_file:
        stats.update(verify_joined(root, joined))
    stats.update(verify_preserved_files(root))
    if check_objects:
        stats.update(verify_commit_objects(root))
    stats.update(verify_bundle(root, full=full_bundle))
    return joined, stats


def negative_control(root: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="charvest-negative-") as temp:
        copy = Path(temp) / "harvest"
        shutil.copytree(root, copy)
        target = copy / "verdicts_shard_a.tsv"
        rows = read_tsv(target, ["path", "verdict", "evidence"])
        mutated = False
        for row in rows:
            if row[0] == "/home/reyerchu/_agentjob_i1015/wt":
                row[1] = "LANDED"
                mutated = True
                break
        require(mutated, "negative-control target is missing")
        with target.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
            writer.writerow(["path", "verdict", "evidence"])
            writer.writerows(rows)
        try:
            validate(copy, check_joined_file=False, full_bundle=False, check_objects=False)
        except VerificationError as error:
            require(
                "uncommitted rescue" in str(error),
                f"negative control failed for the wrong reason: {error}",
            )
        else:
            raise VerificationError("negative control was accepted: uncommitted work was called safe-to-delete")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="clone, restore, and fsck the rescue bundle")
    parser.add_argument("--self-test", action="store_true", help="run the safe-to-delete negative control")
    parser.add_argument("--write-joined", action="store_true", help="regenerate canonical verdicts_joined.tsv")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent

    try:
        joined, stats = validate(
            root,
            check_joined_file=not args.write_joined,
            full_bundle=args.full,
            check_objects=True,
        )
        if args.write_joined:
            write_joined(root / "verdicts_joined.tsv", joined)
            stats.update(verify_joined(root, joined))
        if args.self_test:
            negative_control(root)
    except VerificationError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    print("PASS: content-based harvest consolidation")
    print("shards=" + ",".join(f"{key}:{value}" for key, value in EXPECTED_SHARD_COUNTS.items()))
    print(
        "ledger="
        f"total:{stats['total']},threshold:>=355,host_path_keys:{stats['total']},"
        f"literal_paths:{stats['literal_paths']},duplicate_literals:{stats['duplicate_literals']},"
        f"tmp_paths:{stats['tmp_paths']}"
    )
    print(
        "verdicts="
        f"RECOVER:{stats['verdict_recover']},LANDED:{stats['verdict_landed']},"
        f"ABANDON:{stats['verdict_abandon']},UNREACHABLE:{stats['verdict_unreachable']}"
    )
    print(
        "rescues="
        f"manifest_rows:{stats['rescue_manifest_rows']},rescued_commits:{stats['rescued_commits']},"
        f"preserved_tips:{stats['preserved_tips']},preserved_untracked:{stats['preserved_untracked']}"
    )
    print(
        "bundle="
        f"sha256:{stats['bundle_sha256']},sha1:{stats['bundle_sha1']},"
        f"manifest_files:{stats['bundle_manifest_files']},restored_files:{stats['restored_files']},"
        f"fsck_rc:{stats['restore_fsck_rc']}"
    )
    print("negative_control=" + ("PASS" if args.self_test else "not-run"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
