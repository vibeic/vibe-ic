#!/usr/bin/env python3
"""Choose the landing validation profile from the merge diff.

The planner is intentionally separate from ``gatekeeper-land.sh``.  The merge
verifier imports/runs the copy from the *base* checkout, so the tree being
judged cannot classify itself as low risk.  A caller may request a stronger
profile, but ``effective_profile`` is always the maximum of the automatic and
requested profiles; there is no downgrade flag.

Profiles implement the software lifecycle split documented in
``vibeic_software_push_gate_review_and_refactor.md``:

``fast``
    Documentation and similarly narrow, non-executable changes.  Exact merge
    identity, cheap landing policy, affected tests and write guards still run.

``standard``
    Localised software changes.  Adds the plugin structural audit and uses the
    import-edge test selection.  It is budgeted as the normal software landing
    path.

``full``
    Milestones, broad changes, gate/test-infrastructure edits, coverage
    removal, IC/benchmark surfaces, or an unusually wide affected-test set.
    This is the historical complete landing battery.

The thresholds are routing limits, not claims that file count predicts exact
wall time.  They stop a known-wide selection from entering a bounded lane; the
record carries the measured selection size so the limits can be replaced by a
per-test timing profile later without changing the policy interface.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

from _atomic_artefact import write_json
from ci_targeted_test_select import MODE_IMPORT_EDGE, select_tests


PROFILES = ("fast", "standard", "full")
PROFILE_RANK = {name: rank for rank, name in enumerate(PROFILES)}

# A standard lane above either limit has already missed the document's <10 min
# objective on this repository.  Full is expensive, but it is honest about the
# job rather than letting an unbounded run wear a bounded profile's name.
STANDARD_MAX_CHANGED_PATHS = 50
STANDARD_MAX_CHANGED_LINES = 2_000
STANDARD_MAX_SELECTED_TEST_FILES = 180

FAST_SUFFIXES = frozenset({".md", ".rst", ".txt", ".png", ".jpg", ".jpeg", ".svg"})

# Editing the mechanism that chooses/runs/judges a gate is never self-certified
# by the short lane.  Prefixes are repo-relative.
FULL_PREFIXES = (
    ".github/",
    "tools/ci/",
    "tools/git-hooks/",
    "benchmark-data/",
    "vibe-ic-marketplace/plugins/vibe-ic/mcp-eda/",
    "vibe-ic-marketplace/plugins/vibe-ic/skills/",
)
FULL_EXACT = frozenset({
    "tools/gatekeeper-land.sh",
    "tools/gatekeeper-verify-merge.sh",
    "tools/install-git-hooks.sh",
    "vibe-ic-marketplace/plugins/vibe-ic/pytest.ini",
    "vibe-ic-marketplace/plugins/vibe-ic/conftest.py",
})
FULL_PROGRAM_STEMS = frozenset({
    "landing_gate_plan",
    "landing_merge_verdict",
    "ci_targeted_test_select",
    "landing_unselectable_pytest_corpus",
    "hygiene_finding_delta",
    "hygiene_shard_plan",
    "hygiene_shard_aggregate",
    "gate_host_independence_check",
    "policy_direction_pin_check",
    "gatekeeper_prepare_landing",
})

PLUGIN_PREFIX = "vibe-ic-marketplace/plugins/vibe-ic"
PLUGIN_JSON = f"{PLUGIN_PREFIX}/.claude-plugin/plugin.json"


class PlanError(RuntimeError):
    """The planner could not establish the inputs needed for a safe profile."""


@dataclass(frozen=True)
class Change:
    status: str
    path: str
    old_path: str = ""
    added_lines: int = 0
    deleted_lines: int = 0


@dataclass(frozen=True)
class Plan:
    schema_version: int
    base: str
    head: str
    automatic_profile: str
    requested_profile: str
    effective_profile: str
    budget_seconds: int | None
    selector_mode: str
    changed_paths: List[str]
    changed_path_count: int
    changed_lines: int
    selected_test_files: int
    selected_tests: List[str]
    deleted_tests: List[str]
    reasons: List[str]
    stages: List[str]


def _git(repo: Path, *args: str) -> str:
    try:
        cp = subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PlanError(f"git {' '.join(args)} could not run: {exc}") from exc
    if cp.returncode:
        raise PlanError(
            f"git {' '.join(args)} failed rc={cp.returncode}: "
            f"{cp.stderr.strip() or '<no diagnostic>'}")
    return cp.stdout


def _name_status(repo: Path, base: str, head: str) -> List[Change]:
    raw = _git(repo, "diff", "--name-status", "--find-renames", "-z", base, head)
    fields = raw.split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    out: List[Change] = []
    i = 0
    while i < len(fields):
        status = fields[i]
        i += 1
        if status.startswith(("R", "C")):
            if i + 1 >= len(fields):
                raise PlanError("truncated rename/copy record from git diff")
            old, new = fields[i], fields[i + 1]
            i += 2
            out.append(Change(status=status[0], path=new, old_path=old))
        else:
            if i >= len(fields):
                raise PlanError("truncated path record from git diff")
            out.append(Change(status=status[:1], path=fields[i]))
            i += 1
    return out


def _numstat(repo: Path, base: str, head: str) -> dict[str, Tuple[int, int]]:
    raw = _git(repo, "diff", "--numstat", "--find-renames", base, head)
    out: dict[str, Tuple[int, int]] = {}
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        add, delete, path = parts[0], parts[1], parts[-1]
        # Binary files use '-'.  They still count as a changed path, but not as
        # invented source lines.
        out[path] = (int(add) if add.isdigit() else 0,
                     int(delete) if delete.isdigit() else 0)
    return out


def changes(repo: Path, base: str, head: str) -> List[Change]:
    stats = _numstat(repo, base, head)
    return [Change(c.status, c.path, c.old_path, *stats.get(c.path, (0, 0)))
            for c in _name_status(repo, base, head)]


def _program_stem(path: str) -> str:
    prefix = f"{PLUGIN_PREFIX}/programs/"
    if not path.startswith(prefix) or not path.endswith(".py"):
        return ""
    rel = path[len(prefix):]
    return Path(rel).stem if "/" not in rel else ""


def _is_test(path: str) -> bool:
    return ("/tests/test_" in path or path.startswith("tools/test_")
            or "/test_" in path and path.endswith(".py"))


def _is_shared_test_infrastructure(path: str) -> bool:
    marker = f"{PLUGIN_PREFIX}/programs/tests/"
    if not path.startswith(marker):
        return False
    rel = path[len(marker):]
    return path.endswith(".py") and not Path(rel).name.startswith("test_")


def _is_fast_path(path: str) -> bool:
    if path.startswith(("benchmark-data/", ".github/", "tools/ci/")):
        return False
    return Path(path).suffix.lower() in FAST_SUFFIXES


def _plugin_version(repo: Path, ref: str) -> str:
    try:
        raw = _git(repo, "show", f"{ref}:{PLUGIN_JSON}")
        return str(json.loads(raw).get("version") or "")
    except (PlanError, ValueError, TypeError):
        return ""


def _is_milestone_version(version: str) -> bool:
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", version.strip())
    return bool(m and int(m.group(3)) == 0)


def _selected_tests(repo: Path, changed_paths: Iterable[str]) -> List[str]:
    plugin = repo / PLUGIN_PREFIX
    try:
        return select_tests(
            list(changed_paths), plugin, PLUGIN_PREFIX,
            mode=MODE_IMPORT_EDGE,
        )
    except Exception as exc:  # noqa: BLE001 - inability routes to full below
        raise PlanError(f"affected-test selection could not be computed: {exc}") from exc


def _stages(profile: str) -> List[str]:
    common = ["merge-identity", "cheap-landing-policy", "affected-tests",
              "write-guard"]
    if profile == "fast":
        return common
    if profile == "standard":
        return common[:-1] + ["plugin-full-audit", "write-guard"]
    return common[:-1] + [
        "repo-tools-tests", "unselectable-tests", "repo-hygiene",
        "plugin-full-audit", "write-guard",
    ]


def plan(repo: Path, base: str, head: str = "HEAD",
         requested: str = "auto") -> Plan:
    repo = repo.resolve()
    base_sha = _git(repo, "rev-parse", base).strip()
    head_sha = _git(repo, "rev-parse", head).strip()
    cs = changes(repo, base_sha, head_sha)
    paths = [c.path for c in cs]
    deleted_tests = sorted(c.path for c in cs if c.status == "D" and _is_test(c.path))
    line_count = sum(c.added_lines + c.deleted_lines for c in cs)
    reasons: List[str] = []

    # The selector comes from the verifier/base, while its subject is the
    # candidate worktree.  Failure to compute is a full-route event, never a
    # reason to call the diff small.
    try:
        selected_tests = _selected_tests(repo, paths)
    except PlanError as exc:
        selected_tests = []
        reasons.append(str(exc))
    selected = len(selected_tests)

    full_reasons: List[str] = []
    if not cs:
        full_reasons.append("the merge diff is empty; a no-op is not a fast landing")
    if deleted_tests:
        full_reasons.append(
            f"{len(deleted_tests)} test file(s) are deleted; coverage shrink needs full review")
    critical = sorted({
        p for p in paths
        if p in FULL_EXACT or p.startswith(FULL_PREFIXES)
        or _program_stem(p) in FULL_PROGRAM_STEMS
        or _is_shared_test_infrastructure(p)
    })
    if critical:
        full_reasons.append(
            "gate/shared/IC infrastructure changed: " + ", ".join(critical[:6])
            + (" …" if len(critical) > 6 else ""))

    base_version = _plugin_version(repo, base_sha)
    head_version = _plugin_version(repo, head_sha)
    if head_version and head_version != base_version and _is_milestone_version(head_version):
        full_reasons.append(
            f"plugin version moves {base_version or '<unknown>'} -> {head_version}; "
            "x.y.0 is a milestone")
    if len(cs) > STANDARD_MAX_CHANGED_PATHS:
        full_reasons.append(
            f"{len(cs)} changed paths exceed the standard limit "
            f"{STANDARD_MAX_CHANGED_PATHS}")
    if line_count > STANDARD_MAX_CHANGED_LINES:
        full_reasons.append(
            f"{line_count} changed lines exceed the standard limit "
            f"{STANDARD_MAX_CHANGED_LINES}")
    if selected == 0:
        full_reasons.append("the affected-test selector produced no measurable set")
    elif selected > STANDARD_MAX_SELECTED_TEST_FILES:
        full_reasons.append(
            f"{selected} affected test files exceed the standard limit "
            f"{STANDARD_MAX_SELECTED_TEST_FILES}")

    if full_reasons:
        automatic = "full"
        reasons.extend(full_reasons)
    elif paths and all(_is_fast_path(p) for p in paths):
        automatic = "fast"
        reasons.append("all changed paths are non-executable documentation/assets")
    else:
        automatic = "standard"
        reasons.append("localised software change within the standard risk limits")

    if requested not in ("auto", *PROFILES):
        raise PlanError(f"unknown requested profile {requested!r}")
    requested_floor = automatic if requested == "auto" else requested
    effective = max((automatic, requested_floor), key=PROFILE_RANK.__getitem__)
    if requested != "auto":
        if PROFILE_RANK[requested_floor] < PROFILE_RANK[automatic]:
            reasons.append(
                f"requested {requested_floor} cannot downgrade automatic {automatic}")
        elif requested_floor != automatic:
            reasons.append(
                f"caller escalated automatic {automatic} to {requested_floor}")

    return Plan(
        schema_version=1,
        base=base_sha,
        head=head_sha,
        automatic_profile=automatic,
        requested_profile=requested,
        effective_profile=effective,
        budget_seconds={"fast": 180, "standard": 600, "full": None}[effective],
        selector_mode=MODE_IMPORT_EDGE,
        changed_paths=paths,
        changed_path_count=len(paths),
        changed_lines=line_count,
        selected_test_files=selected,
        selected_tests=selected_tests,
        deleted_tests=deleted_tests,
        reasons=reasons,
        stages=_stages(effective),
    )


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="choose the minimum safe landing profile from a merge diff")
    ap.add_argument("--repo", type=Path, default=Path("."))
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--request", choices=("auto", *PROFILES), default="auto",
                    help="escalate the automatic profile; cannot downgrade it")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--field", choices=("automatic_profile", "effective_profile",
                                         "budget_seconds"))
    args = ap.parse_args(argv)
    try:
        result = plan(args.repo, args.base, args.head, args.request)
    except PlanError as exc:
        print(f"[FAIL] landing_gate_plan: {exc}", file=sys.stderr)
        return 2
    doc = asdict(result)
    if args.json:
        write_json(args.json, doc, ensure_ascii=True)
    if args.field:
        value = doc[args.field]
        print("" if value is None else value)
        return 0
    print(f"landing_gate_plan: {result.effective_profile.upper()} "
          f"(automatic={result.automatic_profile}, requested={args.request})")
    print(f"  diff: {result.changed_path_count} path(s), "
          f"{result.changed_lines} changed line(s), "
          f"{result.selected_test_files} affected test file(s)")
    budget = (f"{result.budget_seconds}s" if result.budget_seconds is not None
              else "case-by-case")
    print(f"  budget: {budget}")
    for reason in result.reasons:
        print(f"  reason: {reason}")
    print("  stages: " + ", ".join(result.stages))
    return 0


if __name__ == "__main__":
    sys.exit(main())
