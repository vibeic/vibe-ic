#!/usr/bin/env python3
"""BLOCKING ownership contract for the external benchmark-data gate lane.

The published corpus moved to ``vibeic/benchmark-data``.  A corpus gate left in
the plugin landing lane can only refuse because its subject is absent; simply
dropping that gate would move the same defect to the data repository.  This
checker proves the local half of the hand-off and, when a corpus is supplied,
the repository boundary itself:

* the ten data-owned gates occur in the external runner and not in the plugin
  landing runner;
* every gate is explicitly BLOCKING and names a shipped program;
* a supplied corpus is the exact top level of a clean git checkout whose
  ``origin`` is ``vibeic/benchmark-data``;
* the checkout carries a tracked marker agreeing byte-for-meaning with this
  contract and the files the lane consumes.

Missing, loose, dirty, wrong-remote, and partial pointers are failures.  There
is no absent-corpus PASS mode here: the plugin landing runs the local ownership
check, while the data repository invokes the external runner with an exact
checkout.  Exit 0 = the requested half was proved; exit 1 = contract failure.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple


CONTRACT_REL = Path("tools/ci/benchmark_data_hygiene_contract.json")
REQUIRED_CORPUS_PATHS = (
    ".vibe-ic-corpus.json",
    "evidence_citation_baseline.json",
    "ic/INDEX.md",
    "ic/retention.json",
)
_RUN_RE = re.compile(r'^\s*run\s+"([^"]+)"', re.MULTILINE)


class ContractError(RuntimeError):
    pass


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()[:300]
        raise ContractError(f"git {' '.join(args)} failed under {root}: {detail}")
    return proc.stdout


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ContractError(f"cannot read JSON contract {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{path} must contain a JSON object")
    return value


def _labels(doc: Dict[str, Any], source: Path) -> List[str]:
    rows = doc.get("gates")
    if not isinstance(rows, list) or not rows:
        raise ContractError(f"{source}: gates must be a non-empty array")
    labels: List[str] = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ContractError(f"{source}: gates[{idx}] must be an object")
        label = row.get("label")
        if not isinstance(label, str) or not label.strip():
            raise ContractError(f"{source}: gates[{idx}].label is missing")
        if row.get("blocking") is not True:
            raise ContractError(
                f"{source}: {label!r} does not explicitly declare blocking=true"
            )
        labels.append(label)
    if len(labels) != len(set(labels)):
        raise ContractError(f"{source}: duplicate gate labels are not allowed")
    return labels


def _normal_remote(value: str) -> str:
    value = value.strip().rstrip("/")
    if value.startswith("git@github.com:"):
        value = "https://github.com/" + value[len("git@github.com:") :]
    if value.startswith("ssh://git@github.com/"):
        value = "https://github.com/" + value[len("ssh://git@github.com/") :]
    if value.endswith(".git"):
        value = value[:-4]
    return value.lower()


def check_local(plugin_root: Path) -> Dict[str, Any]:
    plugin_root = plugin_root.resolve()
    contract_path = plugin_root / CONTRACT_REL
    contract = _load_json(contract_path)
    if contract.get("schema_version") != 1:
        raise ContractError("only benchmark-data hygiene schema_version=1 is supported")

    labels = _labels(contract, contract_path)
    external = plugin_root / str(contract.get("external_runner", ""))
    landing = plugin_root / str(contract.get("plugin_landing_runner", ""))
    for path, kind in ((external, "external"), (landing, "plugin landing")):
        if not path.is_file():
            raise ContractError(f"{kind} runner does not exist: {path}")

    external_text = external.read_text(encoding="utf-8")
    landing_text = landing.read_text(encoding="utf-8")
    external_labels = _RUN_RE.findall(external_text)
    external_owned = [label for label in external_labels if label in labels]
    plugin_owned = [label for label in _RUN_RE.findall(landing_text) if label in labels]
    if external_owned != labels:
        raise ContractError(
            "external runner gate order/set differs from the contract: "
            f"contract={labels!r}, runner={external_owned!r}"
        )
    if plugin_owned:
        raise ContractError(
            "data-owned gates remain in the plugin landing lane: "
            + ", ".join(plugin_owned)
        )

    programs = plugin_root / "vibe-ic-marketplace/plugins/vibe-ic/programs"
    for row in contract["gates"]:
        program = row.get("program")
        if not isinstance(program, str) or not (programs / program).is_file():
            raise ContractError(
                f"gate {row.get('label')!r} names an absent program: {program!r}"
            )
        if program not in external_text:
            raise ContractError(
                f"external runner never invokes {program} for {row.get('label')!r}"
            )

    if (plugin_root / "benchmark-data").exists():
        raise ContractError(
            "plugin checkout unexpectedly contains benchmark-data; ownership is ambiguous"
        )
    return {
        "contract_id": contract.get("contract_id"),
        "gate_count": len(labels),
        "plugin_owned": plugin_owned,
        "external_owned": external_owned,
    }


def check_corpus(plugin_root: Path, corpus: Path) -> Dict[str, Any]:
    local = check_local(plugin_root)
    supplied = corpus.expanduser().resolve()
    if not supplied.is_dir():
        raise ContractError(f"corpus pointer is not a directory: {supplied}")
    top = Path(_git(supplied, "rev-parse", "--show-toplevel").strip()).resolve()
    if supplied != top:
        raise ContractError(
            f"corpus pointer must name the exact checkout top level: "
            f"supplied={supplied}, git_top={top}"
        )
    head = _git(top, "rev-parse", "HEAD^{commit}").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ContractError(f"could not resolve an exact corpus commit: {head!r}")

    dirty = _git(top, "status", "--porcelain", "--untracked-files=all").splitlines()
    if dirty:
        raise ContractError(
            f"corpus checkout is dirty ({len(dirty)} path(s)); first: {dirty[0]}"
        )

    contract = _load_json(plugin_root.resolve() / CONTRACT_REL)
    expected_remote = _normal_remote(str(contract.get("canonical_remote", "")))
    origin = _normal_remote(_git(top, "remote", "get-url", "origin").strip())
    if not expected_remote or origin != expected_remote:
        raise ContractError(
            f"corpus origin is not the canonical owner: got={origin!r}, "
            f"expected={expected_remote!r}"
        )

    tracked = set(_git(top, "ls-files").splitlines())
    missing = [rel for rel in REQUIRED_CORPUS_PATHS if rel not in tracked]
    if missing:
        raise ContractError(
            "corpus checkout is partial or predates the ownership contract; "
            "missing tracked path(s): " + ", ".join(missing)
        )

    marker_path = top / str(contract.get("corpus_marker", ""))
    marker = _load_json(marker_path)
    marker_labels = marker.get("gates")
    expected_labels = _labels(contract, plugin_root.resolve() / CONTRACT_REL)
    expected_marker = {
        "schema_version": contract.get("schema_version"),
        "contract_id": contract.get("contract_id"),
        "owner_repository": contract.get("owner_repository"),
        "canonical_remote": contract.get("canonical_remote"),
        "tooling_repository": "vibeic/vibe-ic",
        "tooling_lock": ".vibe-ic-tooling-lock.json",
        "runner": contract.get("external_runner"),
        "gates": expected_labels,
    }
    actual_marker = {key: marker.get(key) for key in expected_marker}
    if actual_marker != expected_marker:
        raise ContractError(
            "corpus marker disagrees with the plugin contract: "
            f"expected={expected_marker!r}, got={actual_marker!r}"
        )
    if marker_labels != expected_labels:
        raise ContractError("corpus marker gate order/set is not exact")

    return {
        **local,
        "corpus_root": str(top),
        "corpus_commit": head,
        "corpus_origin": origin,
        "tracked_paths": len(tracked),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--plugin-root", type=Path, required=True)
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--json", dest="json_out", type=Path)
    args = parser.parse_args(argv)
    try:
        report = (
            check_corpus(args.plugin_root, args.corpus)
            if args.corpus is not None
            else check_local(args.plugin_root)
        )
    except ContractError as exc:
        print(f"[FAIL] benchmark-data hygiene ownership: {exc}", file=sys.stderr)
        return 1
    if args.json_out:
        args.json_out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    suffix = (
        f", corpus={report['corpus_commit']} ({report['tracked_paths']} tracked paths)"
        if "corpus_commit" in report
        else ""
    )
    print(
        f"[PASS] benchmark-data hygiene ownership: {report['gate_count']} BLOCKING "
        f"gate(s) owned only by the external lane{suffix}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
