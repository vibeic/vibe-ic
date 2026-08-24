#!/usr/bin/env python3
"""Derived-count and lane-provenance checks for the jcap-ppa capture.

Current already-program totals have one authority: the two tables in RESULT.md.
Git-side constraints have one authority too: the immutable lane tip supplied by
the landing receipt, measured from the frozen base through the excluded source.
"""
from __future__ import annotations

from dataclasses import dataclass
import pathlib
import re
import subprocess


NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "twenty-one": 21, "twenty-two": 22,
    "twenty-three": 23, "twenty-four": 24,
}
NUMBER_TOKEN = r"(?:\d+|[a-z]+(?:-[a-z]+)?)"
HISTORY_START = re.compile(
    rf"<!-- already-program-history-start checkpoint=([0-9a-f]{{40}}) "
    rf"claims=({NUMBER_TOKEN}) holding=({NUMBER_TOKEN}) -->"
)
HISTORY_END = "<!-- already-program-history-end -->"


@dataclass(frozen=True)
class ClaimPair:
    claims: int
    holding: int


@dataclass(frozen=True)
class HistoryCheckpoint:
    sha: str
    pair: ClaimPair


def number(token: str) -> int:
    token = token.strip().lower()
    if token.isdigit():
        return int(token)
    if token not in NUMBER_WORDS:
        raise ValueError(f"unrecognised number token {token!r}")
    return NUMBER_WORDS[token]


def table_rows(md: str, header: str) -> list[str]:
    lines = md.splitlines()
    hits = [i for i, line in enumerate(lines) if line.strip() == header]
    if len(hits) != 1:
        return []
    rows: list[str] = []
    i = hits[0] + 2
    while i < len(lines) and lines[i].startswith("| "):
        rows.append(lines[i])
        i += 1
    return rows


def derive_claim_pair(md: str) -> tuple[ClaimPair | None, tuple[int, int], list[str]]:
    first = table_rows(md, "| F | already enforced by | general over |")
    second = table_rows(md, "| class | already enforced by |")
    errors: list[str] = []
    if not first:
        errors.append("already-program finding table is absent or ambiguous")
    if not second:
        errors.append("already-program class table is absent or ambiguous")
    rows = first + second
    disproven = [row for row in rows if "DISPROVEN by execution" in row]
    if len(disproven) != 1:
        errors.append(f"tables contain {len(disproven)} disproven claim rows, expected one")
    if errors:
        return None, (len(first), len(second)), errors
    return ClaimPair(len(rows), len(rows) - len(disproven)), (len(first), len(second)), []


def strip_labeled_history(md: str) -> tuple[str, list[HistoryCheckpoint], list[str]]:
    """Remove explicitly checkpointed history before finding current surfaces."""
    out: list[str] = []
    checkpoints: list[HistoryCheckpoint] = []
    errors: list[str] = []
    pos = 0
    while True:
        start = HISTORY_START.search(md, pos)
        if start is None:
            out.append(md[pos:])
            break
        out.append(md[pos:start.start()])
        end = md.find(HISTORY_END, start.end())
        if end < 0:
            errors.append(f"history checkpoint {start.group(1)} has no end marker")
            out.append(md[start.start():])
            break
        try:
            pair = ClaimPair(number(start.group(2)), number(start.group(3)))
        except ValueError as exc:
            errors.append(str(exc))
        else:
            checkpoints.append(HistoryCheckpoint(start.group(1), pair))
        pos = end + len(HISTORY_END)
    cleaned = "".join(out)
    if HISTORY_END in cleaned or "<!-- already-program-history-start" in cleaned:
        errors.append("unpaired or malformed already-program history marker")
    return cleaned, checkpoints, errors


def _pairs(md: str, name: str, pattern: str) -> tuple[list[ClaimPair], list[str]]:
    found: list[ClaimPair] = []
    errors: list[str] = []
    for match in re.finditer(pattern, md, re.I | re.M | re.S):
        try:
            found.append(ClaimPair(number(match.group("claims")), number(match.group("holding"))))
        except ValueError as exc:
            errors.append(f"{name}: {exc}")
    if len(found) != 1:
        errors.append(f"{name}: found {len(found)} current count surfaces, expected one")
    return found, errors


def validate_current_claim_counts(
    md: str,
) -> tuple[ClaimPair | None, dict[str, ClaimPair], list[HistoryCheckpoint], list[str]]:
    """Bind every current count surface to the pair derived from table rows."""
    current, history, errors = strip_labeled_history(md)
    derived, table_sizes, table_errors = derive_claim_pair(current)
    errors.extend(table_errors)

    patterns = {
        "title": (
            rf"^# .*?and the (?P<claims>{NUMBER_TOKEN}) already-program claims "
            rf"of which (?P<holding>{NUMBER_TOKEN}) hold\s*$"
        ),
        "introduction": (
            rf"(?:current source of truth:|and the count is)\s*\*\*"
            rf"(?:(?:\d+\s*\+\s*)+\d+\s*=\s*)?"
            rf"(?P<claims>{NUMBER_TOKEN})(?:\*\*)?\s+claims\s+examined\s*[—-]\s*"
            rf"(?:of which\s+)?(?:\*\*)?(?P<holding>{NUMBER_TOKEN})\s+hold\b"
        ),
        "summary": (
            rf"\*\*STATUS\*\*:[\s\S]*?\.\s*(?P<claims>{NUMBER_TOKEN})\s+"
            rf"ALREADY-PROGRAM claims examined,\s*(?P<holding>{NUMBER_TOKEN})\s+holding\b"
        ),
        "ladder": (
            rf"^\| ALREADY-PROGRAM \| (?P<claims>{NUMBER_TOKEN}) claims, "
            rf"\*\*(?P<holding>{NUMBER_TOKEN}) hold\*\* \|"
        ),
    }
    surfaces: dict[str, ClaimPair] = {}
    for name, pattern in patterns.items():
        found, parse_errors = _pairs(current, name, pattern)
        errors.extend(parse_errors)
        if len(found) == 1:
            surfaces[name] = found[0]

    component_patterns = {
        "finding-table introduction": rf"^(?P<n>{NUMBER_TOKEN}) are ALREADY-PROGRAM[.:]\s*",
        "class-table introduction": rf"^(?P<n>{NUMBER_TOKEN}) more classes,[^\n]*$",
    }
    for (name, pattern), expected in zip(component_patterns.items(), table_sizes):
        hits = list(re.finditer(pattern, current, re.I | re.M))
        if len(hits) != 1:
            errors.append(f"{name}: found {len(hits)} surfaces, expected one")
            continue
        try:
            got = number(hits[0].group("n"))
        except ValueError as exc:
            errors.append(f"{name}: {exc}")
            continue
        if got != expected:
            errors.append(f"{name}: states {got}, table has {expected} rows")

    if derived is not None:
        for name, pair in surfaces.items():
            if pair != derived:
                errors.append(
                    f"{name}: states {pair.claims}/{pair.holding}, "
                    f"tables derive {derived.claims}/{derived.holding}"
                )
    return derived, surfaces, history, errors


def validate_history_checkpoints(
    repo: pathlib.Path, result_path: pathlib.PurePosixPath, checkpoints: list[HistoryCheckpoint]
) -> list[str]:
    errors: list[str] = []
    for checkpoint in checkpoints:
        obj = subprocess.run(
            ["git", "cat-file", "-e", f"{checkpoint.sha}^{{commit}}"],
            cwd=repo, capture_output=True, text=True,
        )
        if obj.returncode != 0:
            errors.append(f"historical checkpoint {checkpoint.sha} does not resolve")
            continue
        shown = subprocess.run(
            ["git", "show", f"{checkpoint.sha}:{result_path.as_posix()}"],
            cwd=repo, capture_output=True, text=True,
        )
        if shown.returncode != 0:
            errors.append(f"historical checkpoint {checkpoint.sha} lacks {result_path}")
            continue
        pair, _, pair_errors = derive_claim_pair(shown.stdout)
        if pair_errors:
            errors.append(f"historical checkpoint {checkpoint.sha} cannot derive its pair: {pair_errors}")
        elif pair != checkpoint.pair:
            errors.append(
                f"historical checkpoint {checkpoint.sha} is labelled "
                f"{checkpoint.pair.claims}/{checkpoint.pair.holding}, "
                f"but its tables derive {pair.claims}/{pair.holding}"
            )
    return errors


def _git(repo: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def lane_constraint_errors(
    repo: pathlib.Path,
    *,
    head: str,
    lane_tip: str,
    lane_base: str,
    excluded_source: str,
) -> tuple[list[str], list[str]]:
    """Check only base..lane_tip; head may also contain unrelated lane commits."""
    errors: list[str] = []
    details: list[str] = []
    names = {
        "head": head,
        "lane tip receipt": lane_tip,
        "lane base": lane_base,
        "excluded source": excluded_source,
    }
    resolved: dict[str, str] = {}
    for name, value in names.items():
        if not re.fullmatch(r"[0-9a-f]{40}", value):
            errors.append(f"{name} is not an immutable 40-character SHA: {value!r}")
            continue
        proc = _git(repo, "rev-parse", "--verify", f"{value}^{{commit}}")
        if proc.returncode != 0:
            errors.append(f"{name} does not resolve: {value}")
        else:
            resolved[name] = proc.stdout.strip()
    if len(resolved) != len(names):
        return errors, details

    parent = _git(repo, "rev-parse", f"{excluded_source}^")
    if parent.returncode != 0 or parent.stdout.strip() != lane_base:
        errors.append(
            f"excluded source parent is {parent.stdout.strip() or 'unresolved'}, expected frozen base {lane_base}"
        )
    if _git(repo, "merge-base", "--is-ancestor",
            excluded_source, lane_tip).returncode != 0:
        errors.append("lane tip does not descend from the excluded source")

    diff = _git(repo, "diff", "--name-status", lane_base, lane_tip)
    if diff.returncode != 0:
        errors.append("cannot read frozen-base..lane-tip changed paths")
        return errors, details
    changed: list[tuple[str, str]] = []
    for line in diff.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            changed.append((parts[0], parts[-1]))
    details.append(f"lane-owned changed paths: {len(changed)}")

    # A normal squash landing deliberately does not preserve commit ancestry.
    # In that case, prove the thing ancestry was standing in for: every path
    # owned by the immutable lane receipt has the exact received blob at HEAD.
    # This stays scoped to base..lane_tip, so unrelated batch members neither
    # help nor hurt the result.
    if _git(repo, "merge-base", "--is-ancestor",
            lane_tip, head).returncode != 0:
        mismatched = []
        for _status, path in changed:
            tip_blob = _git(repo, "rev-parse", f"{lane_tip}:{path}")
            head_blob = _git(repo, "rev-parse", f"{head}:{path}")
            if (tip_blob.returncode != 0 or head_blob.returncode != 0
                    or tip_blob.stdout.strip() != head_blob.stdout.strip()):
                mismatched.append(path)
        if mismatched:
            errors.append(
                "lane tip is neither an ancestor nor squash-equivalent at "
                f"its owned paths: {mismatched}")
        else:
            details.append(
                "lane receipt is squash-equivalent at every lane-owned path")

    plugin = "vibe-ic-marketplace/plugins/vibe-ic/"
    program_root = plugin + "programs/"
    added_programs = []
    baselines = []
    for status, path in changed:
        if "baseline" in pathlib.PurePosixPath(path).name.lower():
            baselines.append(path)
        if status.startswith("A") and path.startswith(program_root) and path.endswith(".py"):
            rel = pathlib.PurePosixPath(path[len(program_root):])
            if not rel.parts or rel.parts[0] != "tests":
                added_programs.append(path)

    version_diff = _git(
        repo, "diff", lane_base, lane_tip, "--",
        "*plugin.json", "*marketplace.json",
    )
    version_lines = [
        line for line in version_diff.stdout.splitlines()
        if line.startswith(("+", "-"))
        and not line.startswith(("+++", "---"))
        and "version" in line
    ]
    if version_lines:
        errors.append(f"version line(s) changed by lane: {len(version_lines)}")
    if baselines:
        errors.append(f"baseline file(s) changed by lane: {baselines}")
    if added_programs:
        errors.append(f"program file(s) added by lane: {added_programs}")
    return errors, details
